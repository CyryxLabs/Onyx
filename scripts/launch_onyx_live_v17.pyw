"""Canonical pre-import launcher for Onyx Live Activation V17."""
from __future__ import annotations

import ctypes
import os
import platform
import runpy
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from core.paths import data_root, runtime_dir


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LOG_PATH = data_root() / "runtime/logs/onyx-live-v17-startup.log"


class _WindowsSingleInstanceV17:
    """Hold the stable GUI mutex before importing the live host."""

    _WAIT_OBJECT_0 = 0
    _WAIT_ABANDONED = 0x80
    _WAIT_TIMEOUT = 258

    def __init__(self) -> None:
        self.handle = None
        self.acquired = False

    def acquire(self) -> bool:
        if platform.system() != "Windows":
            self.acquired = True
            return True
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, False, r"Local\CyryxLabs.Onyx.Live.V15")
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        result = kernel32.WaitForSingleObject(handle, 3_000)
        if result in {self._WAIT_OBJECT_0, self._WAIT_ABANDONED}:
            self.handle = (kernel32, handle)
            self.acquired = True
            return True
        kernel32.CloseHandle(handle)
        if result == self._WAIT_TIMEOUT:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self.handle is None:
            return
        kernel32, handle = self.handle
        self.handle = None
        try:
            if self.acquired and not kernel32.ReleaseMutex(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.acquired = False
            if not kernel32.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


def _run_v16() -> None:
    from core.onyx_live_activation_v17 import restore_v16_environment

    restored = restore_v16_environment(os.environ)
    os.environ.clear()
    os.environ.update(restored)
    runpy.run_path(
        str(ROOT / "scripts" / "launch_onyx_live_v16.pyw"),
        run_name="__main__",
    )


class _PreflightUI:
    def __init__(self) -> None:
        self.muted = True
        self.current_file = None

    def write_log(self, _value: str) -> None:
        pass

    def set_state(self, _value: str) -> None:
        pass


def run() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if sys.argv[1:] not in (
        [],
        ["--preflight-only"],
        ["--governance-smoke-test"],
        ["--founder-smoke-test"],
    ):
        raise RuntimeError("Onyx Live V17 launcher arguments are invalid")
    if sys.argv[1:] == ["--governance-smoke-test"]:
        _run_v16()
        return

    single_instance = None
    if not sys.argv[1:]:
        single_instance = _WindowsSingleInstanceV17()
        if not single_instance.acquire():
            return
    controller = None
    try:
        from core.onyx_live_activation_v15 import verify_activation_prerequisites
        from core.dayops_graph_factory_v1 import create_canonical_dayops_graph_factory_v1
        from core.onyx_live_activation_v17 import (
            FOUNDER_SMOKE_FAILURE_EXIT,
            FounderSmokePlatformRefusalV17,
            activate_main,
            run_founder_smoke_v17,
            write_founder_smoke_failure_v17,
        )

        verify_activation_prerequisites(ROOT, os.environ)
        phase11_runtime = runtime_dir() / "phase11-authority-v1"
        phase11_runtime.mkdir(parents=True, exist_ok=True)
        import main as onyx_main

        onyx_main.runtime_dir = lambda: phase11_runtime.resolve()
        dayops_factory = create_canonical_dayops_graph_factory_v1(
            environ=os.environ, project_root=ROOT
        )
        if sys.argv[1:] == ["--founder-smoke-test"]:
            try:
                run_founder_smoke_v17(
                    onyx_main,
                    dayops_factory=dayops_factory,
                )
            except FounderSmokePlatformRefusalV17:
                from core.onyx_live_activation_v15 import PLATFORM_REFUSAL_EXIT

                if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
                    os._exit(PLATFORM_REFUSAL_EXIT)
                raise
            except BaseException as exc:
                write_founder_smoke_failure_v17(exc)
                if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
                    os._exit(FOUNDER_SMOKE_FAILURE_EXIT)
                raise
            if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
                os._exit(0)
            return
        controller = activate_main(onyx_main, dayops_factory=dayops_factory)
        if sys.argv[1:] == ["--preflight-only"]:
            controller.instantiate_live(_PreflightUI())
            print(
                "ONYX_LIVE_V17_HOST_PREFLIGHT_OK "
                "founder_brief=provider-free-read-only governance=v16-authority "
                "network_calls=0"
            )
            return

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
            sys.stdout = log
            sys.stderr = log
            print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V17 starting")
            try:
                print(f"Founder Brief capability: {controller.founder_brief_capability}")
                print(f"Onyx Governance capability: {controller.governance_capability}")
                print(f"Onyx Away capability: {controller.away_capability}")
                print(
                    "Onyx External Agent capability: "
                    f"{controller.external_agent_capability}"
                )
                onyx_main.main()
            except BaseException:
                traceback.print_exc()
                raise
            finally:
                print(f"[{datetime.now(timezone.utc).isoformat()}] Onyx Live V17 stopped")
    finally:
        try:
            if controller is not None:
                controller.rollback_to_v16()
        finally:
            if single_instance is not None:
                single_instance.close()


if __name__ == "__main__":
    run()
