"""Canonical pre-import launcher for arc-free Onyx Live Activation V12."""

from __future__ import annotations

import os
import platform
import runpy
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from core.paths import data_root


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = data_root() / "runtime/logs/onyx-live-v12-startup.log"
MASTER = "ONYX_LIVE_ACTIVATION_V12"
ROLLBACK = "ONYX_LIVE_ROLLBACK_V12"


def _contracts() -> tuple[tuple[str, ...], dict[str, str]]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.onyx_live_activation_v12 import CONTROL_FLAGS
    from core.onyx_live_activation_v12 import exact_activation_environment

    return CONTROL_FLAGS, exact_activation_environment()


def _launch_mode(environ: dict[str, str] | os._Environ[str]) -> str:
    control, active = _contracts()
    present = {name: environ[name] for name in control if name in environ}
    if not present:
        return "legacy"
    if present == active:
        return "active"
    if present == {ROLLBACK: "1"}:
        return "rollback"
    return "refuse"


def _run_v11(environment: dict[str, str] | os._Environ[str]) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.onyx_live_activation_v12 import restore_v11_environment

    os.environ.clear()
    os.environ.update(restore_v11_environment(environment))
    runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v11.pyw"),
        run_name="__main__",
    )


def run() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    mode = _launch_mode(os.environ)
    if mode == "refuse":
        imported = any(name in sys.modules for name in ("main", "ui"))
        raise RuntimeError(
            "ONYX_LIVE_V12_PREIMPORT_REFUSAL " + ("DIRTY" if imported else "CLEAN")
        )
    if mode == "legacy":
        _run_v11(dict(os.environ))
        return
    if mode == "rollback" or platform.system() != "Windows":
        _run_v11(os.environ)
        return

    from core.onyx_live_activation_v12 import verify_activation_prerequisites

    verify_activation_prerequisites(ROOT, os.environ)

    import main as onyx_main
    from core.onyx_live_activation_v12 import activate_main, preflight_host

    if sys.argv[1:] == ["--preflight-only"]:
        contract = preflight_host(onyx_main)
        print(
            "ONYX_LIVE_V12_HOST_PREFLIGHT_OK "
            f"bridge={contract.base.base.base.base.base.phase5_probe.bridge_type} "
            "hud=v9 arcs=0 wiring=v1 shortcut=bootstrap-v12 network_calls=0"
        )
        return
    if sys.argv[1:]:
        raise RuntimeError("Onyx Live V12 launcher arguments are invalid")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V12 starting")
        controller = None
        try:
            controller = activate_main(onyx_main)
            onyx_main.main()
        except BaseException:
            traceback.print_exc()
            raise
        finally:
            if controller is not None:
                controller.rollback_all()
            print(f"[{datetime.now(timezone.utc).isoformat()}] Onyx Live V12 stopped")


if __name__ == "__main__":
    run()
