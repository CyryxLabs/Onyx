"""Canonical pre-import launcher for Onyx Live Activation V15."""
from __future__ import annotations

import os
import platform
import runpy
import sys
import traceback
import ctypes
from datetime import datetime, timezone
from pathlib import Path

from core.paths import data_root, runtime_dir


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LOG_PATH = data_root() / "runtime/logs/onyx-live-v15-startup.log"
MASTER = "ONYX_LIVE_ACTIVATION_V15"
ROLLBACK = "ONYX_LIVE_ROLLBACK_V15"


class _WindowsSingleInstanceV1:
    """Hold one native per-session GUI instance without touching owner data."""

    _WAIT_OBJECT_0 = 0
    _WAIT_ABANDONED = 0x80
    _WAIT_TIMEOUT = 258

    def __init__(
        self,
        *,
        name: str = r"Local\CyryxLabs.Onyx.Live.V15",
        wait_milliseconds: int = 3_000,
    ) -> None:
        self.name = name
        self.wait_milliseconds = wait_milliseconds
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
        kernel32.WaitForSingleObject.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
        )
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        result = kernel32.WaitForSingleObject(
            handle, self.wait_milliseconds
        )
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


def _phase11_runtime_root():
    """Create a namespace whose parent has no live database or log handles."""
    root = runtime_dir() / "phase11-authority-v1"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _contracts():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.onyx_live_activation_v15 import CONTROL_FLAGS
    from core.onyx_live_activation_v14 import exact_activation_environment as v14_environment
    return CONTROL_FLAGS, v14_environment()


def _launch_mode(environ):
    control, v14_active = _contracts()
    present = {name: environ[name] for name in control if name in environ}
    if not present:
        return "legacy"
    if present == v14_active:
        return "v14"
    if present == {ROLLBACK: "1"}:
        return "rollback"
    try:
        from core.onyx_live_activation_v15 import ActivationFlagsV15
        ActivationFlagsV15.from_canonical_environ(environ)
    except Exception:
        return "refuse"
    return "active"


def _run_v14(environment):
    from core.onyx_live_activation_v15 import restore_v14_environment
    restored = restore_v14_environment(dict(environment))
    os.environ.clear()
    os.environ.update(restored)
    runpy.run_path(str(ROOT / "scripts/launch_onyx_live_v14.pyw"), run_name="__main__")


class _PreflightUI:
    def __init__(self):
        self.muted = True
        self.current_file = None

    def write_log(self, _value):
        pass

    def set_state(self, _value):
        pass


def run() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    mode = _launch_mode(os.environ)
    if mode == "refuse":
        imported = any(name in sys.modules for name in ("main", "ui"))
        raise RuntimeError(
            "ONYX_LIVE_V15_PREIMPORT_REFUSAL " + ("DIRTY" if imported else "CLEAN")
        )
    if mode == "active" and platform.system() != "Windows":
        from core.onyx_live_activation_v15 import PLATFORM_REFUSAL_SIGNAL

        raise RuntimeError(PLATFORM_REFUSAL_SIGNAL)
    if mode in {"legacy", "v14", "rollback"}:
        _run_v14(os.environ)
        return
    if sys.argv[1:] not in ([], ["--preflight-only"]):
        raise RuntimeError("Onyx Live V15 launcher arguments are invalid")

    single_instance = None
    if not sys.argv[1:]:
        single_instance = _WindowsSingleInstanceV1()
        if not single_instance.acquire():
            return

    try:
        from core.onyx_live_activation_v15 import verify_activation_prerequisites
        verify_activation_prerequisites(ROOT, os.environ)
        phase11_runtime = _phase11_runtime_root()
        import main as onyx_main
        # ``main`` deliberately resolves this seam at OnyxLive construction time.
        # Point it at the dedicated namespace prepared before main opened any
        # database, audit or log handle.
        onyx_main.runtime_dir = lambda: phase11_runtime
        from core.dayops_graph_factory_v1 import create_canonical_dayops_graph_factory_v1
        from core.onyx_live_activation_v15 import activate_main

        controller = None
        if sys.argv[1:] == ["--preflight-only"]:
            try:
                controller = activate_main(
                    onyx_main,
                    dayops_factory=create_canonical_dayops_graph_factory_v1(
                        environ=os.environ, project_root=ROOT
                    ),
                )
                controller.instantiate_live(_PreflightUI())
            finally:
                if controller is not None:
                    controller.rollback_all()
            if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
                # The frozen host can retain optional-library worker threads after
                # the verified rollback, and a GUI-subsystem stdout stream may not
                # have a reader.  End the successful diagnostic before printing.
                os._exit(0)
            print(
                "ONYX_LIVE_V15_HOST_PREFLIGHT_OK phase11=immutable-binding "
                "autopilot=authenticated-executable-envelope "
                f"executable_capability={controller.executable_capability} "
                f"away_capability={controller.away_capability} "
                "worker=reachable network_calls=0 lifecycle=install-instantiate-rollback"
            )
            return

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
            sys.stdout = log
            sys.stderr = log
            print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V15 starting")
            try:
                controller = activate_main(
                    onyx_main,
                    dayops_factory=create_canonical_dayops_graph_factory_v1(
                        environ=os.environ, project_root=ROOT
                    ),
                )
                print(
                    "Onyx executable capability: "
                    f"{controller.executable_capability}"
                )
                print(f"Onyx Away capability: {controller.away_capability}")
                onyx_main.main()
            except BaseException:
                traceback.print_exc()
                raise
            finally:
                if controller is not None:
                    controller.rollback_all()
                print(f"[{datetime.now(timezone.utc).isoformat()}] Onyx Live V15 stopped")
    finally:
        if single_instance is not None:
            single_instance.close()


if __name__ == "__main__":
    run()
