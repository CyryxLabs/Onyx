"""Canonical pre-import launcher for Onyx Live Activation V9."""

from __future__ import annotations

import os
import platform
import runpy
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "runtime" / "logs" / "onyx-live-v9-startup.log"
MASTER = "ONYX_LIVE_ACTIVATION_V9"
ROLLBACK = "ONYX_LIVE_ROLLBACK_V9"
HUD_V6 = "ONYX_HUD_V6_CANDIDATE"
V8_ACTIVE = {
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
    for version in range(1, 10)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CONTROL = (*VERSION_CONTROLS, HUD_V6, *V8_ACTIVE, *ALIASES)
ACTIVE = {**V8_ACTIVE, MASTER: "1", HUD_V6: "1"}


def _launch_mode(environ: dict[str, str] | os._Environ[str]) -> str:
    present = {name: environ[name] for name in CONTROL if name in environ}
    if not present:
        return "legacy"
    if present == ACTIVE:
        return "active"
    if present == {ROLLBACK: "1"}:
        return "rollback"
    return "refuse"


def _run_v8(environment: dict[str, str] | os._Environ[str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    runpy.run_path(
        str(ROOT / "scripts" / "launch_onyx_live_v8.pyw"),
        run_name="__main__",
    )


def _v8_environment(environ: dict[str, str] | os._Environ[str]) -> dict[str, str]:
    result = dict(environ)
    result.pop(MASTER, None)
    result.pop(ROLLBACK, None)
    result.pop(HUD_V6, None)
    result.update(V8_ACTIVE)
    return result


def run() -> None:
    os.chdir(ROOT)
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    mode = _launch_mode(os.environ)
    if mode == "refuse":
        imported = any(
            name in sys.modules
            for name in (
                "main",
                "ui",
                "core.onyx_live_activation_v9",
                "core.onyx_hud_orb_v6",
            )
        )
        raise RuntimeError(
            "ONYX_LIVE_V9_PREIMPORT_REFUSAL " + ("DIRTY" if imported else "CLEAN")
        )
    if mode == "legacy":
        _run_v8(dict(os.environ))
        return
    if mode == "rollback" or platform.system() != "Windows":
        _run_v8(_v8_environment(os.environ))
        return

    import main as onyx_main
    from core.onyx_live_activation_v9 import activate_main, preflight_host

    if sys.argv[1:] == ["--preflight-only"]:
        contract = preflight_host(onyx_main)
        print(
            "ONYX_LIVE_V9_HOST_PREFLIGHT_OK "
            f"bridge={contract.base.base.phase5_probe.bridge_type} "
            f"catalog={contract.base.base.phase5_probe.catalog_entries} "
            "hud=v6 shortcut=bootstrap-v9 network_calls=0"
        )
        return
    if sys.argv[1:]:
        raise RuntimeError("Onyx Live V9 launcher arguments are invalid")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V9 starting")
        try:
            activate_main(onyx_main)
            onyx_main.main()
        except BaseException:
            traceback.print_exc()
            raise
        finally:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Onyx Live V9 stopped")


if __name__ == "__main__":
    run()
