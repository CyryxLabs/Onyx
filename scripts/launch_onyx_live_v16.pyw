"""Canonical pre-import launcher for Onyx Live Activation V16."""
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


ROOT = Path(
    getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])
).resolve()
LOG_PATH = data_root() / "runtime/logs/onyx-live-v16-startup.log"


class _WindowsSingleInstanceV1:
    """Hold the stable Onyx GUI mutex shared with V15."""

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


def _phase11_runtime_root() -> Path:
    root = runtime_dir() / "phase11-authority-v1"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _launch_mode(environ: dict[str, str] | os._Environ[str]) -> str:
    from core import onyx_live_activation_v14 as v14
    from core import onyx_live_activation_v15 as v15
    from core import onyx_live_activation_v16 as v16

    present = {
        name: environ[name] for name in v16.CONTROL_FLAGS if name in environ
    }
    if not present:
        return "legacy"
    if present == v14.exact_activation_environment():
        if platform.system() != "Windows" or (
            v16.consume_bootstrap_downgrade_marker_v1("v14")
        ):
            return "v14"
        return "refuse"
    if present == {v16.LIVE_ROLLBACK_FLAG: "1"}:
        return (
            "rollback"
            if v16.consume_bootstrap_downgrade_marker_v1("rollback")
            else "refuse"
        )
    try:
        v16.ActivationFlagsV16.from_canonical_environ(environ)
    except Exception:
        try:
            v15.ActivationFlagsV15.from_canonical_environ(environ)
        except Exception:
            return "refuse"
        return (
            "v15"
            if v16.consume_bootstrap_downgrade_marker_v1("v15")
            else "refuse"
        )
    return "active"


def _run_v15(environment: dict[str, str] | os._Environ[str]) -> None:
    from core.onyx_live_activation_v16 import restore_v15_environment

    restored = restore_v15_environment(environment)
    os.environ.clear()
    os.environ.update(restored)
    runpy.run_path(
        str(ROOT / "scripts" / "launch_onyx_live_v15.pyw"),
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
    mode = _launch_mode(os.environ)
    if mode == "refuse":
        imported = any(name in sys.modules for name in ("main", "ui"))
        raise RuntimeError(
            "ONYX_LIVE_V16_PREIMPORT_REFUSAL "
            + ("DIRTY" if imported else "CLEAN")
        )
    if mode == "active" and platform.system() != "Windows":
        from core.onyx_live_activation_v15 import PLATFORM_REFUSAL_SIGNAL

        raise RuntimeError(PLATFORM_REFUSAL_SIGNAL)
    if mode in {"legacy", "v14", "v15", "rollback"}:
        _run_v15(os.environ)
        return
    if sys.argv[1:] not in (
        [],
        ["--preflight-only"],
        ["--governance-smoke-test"],
    ):
        raise RuntimeError("Onyx Live V16 launcher arguments are invalid")

    single_instance = None
    if not sys.argv[1:]:
        single_instance = _WindowsSingleInstanceV1()
        if not single_instance.acquire():
            return
    controller = None
    try:
        from core.onyx_live_activation_v15 import (
            verify_activation_prerequisites,
        )

        verify_activation_prerequisites(ROOT, os.environ)
        phase11_runtime = _phase11_runtime_root()
        import main as onyx_main

        onyx_main.runtime_dir = lambda: phase11_runtime
        from core.dayops_graph_factory_v1 import (
            create_canonical_dayops_graph_factory_v1,
        )
        from core.onyx_live_activation_v16 import (
            GOVERNANCE_SMOKE_FAILURE_EXIT,
            GovernanceSmokePlatformRefusalV1,
            activate_main,
            run_governance_smoke_v1,
            write_governance_smoke_failure_v1,
        )
        from core.onyx_live_activation_v15 import PLATFORM_REFUSAL_EXIT

        dayops_factory = create_canonical_dayops_graph_factory_v1(
            environ=os.environ, project_root=ROOT
        )
        if sys.argv[1:] == ["--governance-smoke-test"]:
            try:
                payload = run_governance_smoke_v1(
                    onyx_main,
                    dayops_factory=dayops_factory,
                )
            except GovernanceSmokePlatformRefusalV1:
                if getattr(sys, "frozen", False) or getattr(
                    sys, "_MEIPASS", None
                ):
                    os._exit(PLATFORM_REFUSAL_EXIT)
                raise
            except BaseException as exc:
                write_governance_smoke_failure_v1(exc)
                if getattr(sys, "frozen", False) or getattr(
                    sys, "_MEIPASS", None
                ):
                    os._exit(GOVERNANCE_SMOKE_FAILURE_EXIT)
                raise
            if getattr(sys, "frozen", False) or getattr(
                sys, "_MEIPASS", None
            ):
                os._exit(0)
            print(
                "ONYX_GOVERNANCE_SMOKE_OK "
                f"status={payload['status']} provider_calls=0 network_calls=0"
            )
            return

        if sys.argv[1:] == ["--preflight-only"]:
            try:
                controller = activate_main(
                    onyx_main,
                    dayops_factory=dayops_factory,
                )
                controller.instantiate_live(_PreflightUI())
            finally:
                if controller is not None:
                    controller.rollback_all()
            if getattr(sys, "frozen", False) or getattr(
                sys, "_MEIPASS", None
            ):
                os._exit(0)
            print(
                "ONYX_LIVE_V16_HOST_PREFLIGHT_OK "
                "governance=durable-exact-authority "
                "nexus_dispatch=local-catalog-only "
                "network_calls=0 lifecycle=install-instantiate-rollback"
            )
            return

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
            sys.stdout = log
            sys.stderr = log
            print(
                f"\n[{datetime.now(timezone.utc).isoformat()}] "
                "Onyx Live V16 starting"
            )
            try:
                controller = activate_main(
                    onyx_main,
                    dayops_factory=dayops_factory,
                )
                print(
                    "Onyx Governance capability: "
                    f"{controller.governance_capability}"
                )
                onyx_main.main()
            except BaseException:
                traceback.print_exc()
                raise
            finally:
                if controller is not None:
                    controller.rollback_all()
                print(
                    f"[{datetime.now(timezone.utc).isoformat()}] "
                    "Onyx Live V16 stopped"
                )
    finally:
        if single_instance is not None:
            single_instance.close()


if __name__ == "__main__":
    run()
