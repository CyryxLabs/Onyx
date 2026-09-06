"""Canonical pre-import launcher for default-off Onyx Live Activation V10."""

from __future__ import annotations

import os
import platform
import runpy
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "runtime/logs/onyx-live-v10-startup.log"
MASTER = "ONYX_LIVE_ACTIVATION_V10"
ROLLBACK = "ONYX_LIVE_ROLLBACK_V10"
WIRING = "ONYX_PHASE6_LIVE_WIRING_V1"
HUD_V7 = "ONYX_HUD_V7_LIVE"
V9_ACTIVE = {
    "ONYX_LIVE_ACTIVATION_V8": "1",
    "ONYX_OWNER_PROFILE_V8_LIVE": "1",
    "ONYX_HUD_V5_LIVE": "1",
    "ONYX_PHASE5_INTEGRATION_V3": "1",
    "ONYX_PHASE5_RUNTIME_V3": "1",
    "ONYX_PHASE5_GRANT_SHADOW_V3": "1",
    "ONYX_PHASE5_APPROVAL_INBOX_V3": "1",
    "ONYX_PHASE5_LOW_RISK_V3": "1",
    "ONYX_PHASE5_NEXUS_PROJECTION_V3": "1",
    "ONYX_PHASE5_LOCAL_CATALOG_READ_V3": "1",
    "ONYX_PHASE5_DASHBOARD_PROJECTION_V3": "1",
    "ONYX_PHASE5_PRINCIPAL_ID": "onyx-owner",
    "ONYX_PHASE5_WORKSPACE_ID": "onyx-local-workspace",
    "ONYX_PHASE5_ACCOUNT_ID": "cyryx-local-account",
    "ONYX_PHASE5_PROFILE_ID": "onyx-owner-profile",
    "ONYX_LIVE_ACTIVATION_V9": "1",
    "ONYX_HUD_V6_CANDIDATE": "1",
}
ALIASES = (
    "ONYX_PRINCIPAL_ID",
    "ONYX_WORKSPACE_ID",
    "ONYX_ACCOUNT_ID",
    "ONYX_PROFILE_ID",
    "PHASE5_PRINCIPAL_ID",
    "PHASE5_WORKSPACE_ID",
    "PHASE5_ACCOUNT_ID",
    "PHASE5_PROFILE_ID",
)
VERSION_CONTROLS = tuple(
    name
    for version in range(1, 11)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CONTROL = (*VERSION_CONTROLS, WIRING, HUD_V7, *V9_ACTIVE, *ALIASES)
ACTIVE = {
    **V9_ACTIVE,
    MASTER: "1",
    WIRING: "true",
    HUD_V7: "1",
}


def _launch_mode(environ: dict[str, str] | os._Environ[str]) -> str:
    present = {name: environ[name] for name in CONTROL if name in environ}
    if not present:
        return "legacy"
    if present == ACTIVE:
        return "active"
    if present == {ROLLBACK: "1"}:
        return "rollback"
    return "refuse"


def _v9_environment(
    environ: dict[str, str] | os._Environ[str],
) -> dict[str, str]:
    result = dict(environ)
    result.pop(MASTER, None)
    result.pop(ROLLBACK, None)
    result.pop(WIRING, None)
    result.pop(HUD_V7, None)
    result.update(V9_ACTIVE)
    return result


def _run_v9(environment: dict[str, str] | os._Environ[str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v9.pyw"),
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
            "ONYX_LIVE_V10_PREIMPORT_REFUSAL " + ("DIRTY" if imported else "CLEAN")
        )
    if mode == "legacy":
        _run_v9(dict(os.environ))
        return
    if mode == "rollback" or platform.system() != "Windows":
        _run_v9(_v9_environment(os.environ))
        return

    from core.onyx_live_activation_v10 import verify_activation_prerequisites

    # Verify every accepted envelope before importing the live host.
    verify_activation_prerequisites(ROOT, os.environ)

    import main as onyx_main
    from core.onyx_live_activation_v10 import activate_main, preflight_host

    if sys.argv[1:] == ["--preflight-only"]:
        contract = preflight_host(onyx_main)
        print(
            "ONYX_LIVE_V10_HOST_PREFLIGHT_OK "
            f"bridge={contract.base.base.base.phase5_probe.bridge_type} "
            "hud=v7 wiring=v1 shortcut=bootstrap-v10 network_calls=0"
        )
        return
    if sys.argv[1:]:
        raise RuntimeError("Onyx Live V10 launcher arguments are invalid")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V10 starting")
        controller = None
        try:
            controller = activate_main(onyx_main)
            onyx_main.main()
        except BaseException:
            traceback.print_exc()
            raise
        finally:
            if controller is not None:
                controller.rollback_installation()
            print(f"[{datetime.now(timezone.utc).isoformat()}] Onyx Live V10 stopped")


if __name__ == "__main__":
    run()
