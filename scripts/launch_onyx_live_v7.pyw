"""Canonical pre-import launcher for Onyx Live Activation V7."""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "runtime" / "logs" / "onyx-live-v7-startup.log"
MASTER = "ONYX_LIVE_ACTIVATION_V7"
ROLLBACK = "ONYX_LIVE_ROLLBACK_V7"
CHILDREN = (
    "ONYX_OWNER_PROFILE_V8_LIVE",
    "ONYX_HUD_V5_LIVE",
    "ONYX_PHASE5_INTEGRATION_V3",
    "ONYX_PHASE5_RUNTIME_V3",
    "ONYX_PHASE5_GRANT_SHADOW_V3",
    "ONYX_PHASE5_APPROVAL_INBOX_V3",
    "ONYX_PHASE5_LOW_RISK_V3",
    "ONYX_PHASE5_NEXUS_PROJECTION_V3",
    "ONYX_PHASE5_LOCAL_CATALOG_READ_V3",
    "ONYX_PHASE5_DASHBOARD_PROJECTION_V3",
)
IDENTITIES = {
    "ONYX_PHASE5_PRINCIPAL_ID": "onyx-owner",
    "ONYX_PHASE5_WORKSPACE_ID": "onyx-local-workspace",
    "ONYX_PHASE5_ACCOUNT_ID": "cyryx-local-account",
    "ONYX_PHASE5_PROFILE_ID": "onyx-owner-profile",
}
IDENTITY_ALIASES = (
    "ONYX_PRINCIPAL_ID",
    "ONYX_WORKSPACE_ID",
    "ONYX_ACCOUNT_ID",
    "ONYX_PROFILE_ID",
    "PHASE5_PRINCIPAL_ID",
    "PHASE5_WORKSPACE_ID",
    "PHASE5_ACCOUNT_ID",
    "PHASE5_PROFILE_ID",
)
CONTROL = (MASTER, ROLLBACK, *CHILDREN, *IDENTITIES, *IDENTITY_ALIASES)


def _launch_mode(environ: dict[str, str] | os._Environ[str]) -> str:
    present = {name: environ[name] for name in CONTROL if name in environ}
    if any(name in present for name in IDENTITY_ALIASES):
        return "refuse"
    master = present.get(MASTER)
    rollback = present.get(ROLLBACK)
    child_values = tuple(present.get(name) for name in CHILDREN)
    identity_values = {name: present.get(name) for name in IDENTITIES}
    empty_children = not any(value is not None for value in child_values)
    empty_identities = not any(value is not None for value in identity_values.values())
    complete_children = all(value == "1" for value in child_values)
    complete_identities = identity_values == IDENTITIES

    if rollback is not None:
        return (
            "rollback"
            if rollback == "1"
            and master is None
            and empty_children
            and empty_identities
            else "refuse"
        )
    if master is None and empty_children and empty_identities:
        return "legacy"
    if master == "1" and complete_children and complete_identities:
        return "active"
    return "refuse"


def _legacy() -> None:
    from scripts.launch_onyx import run as legacy_run

    legacy_run()


def run() -> None:
    os.chdir(ROOT)
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    mode = _launch_mode(os.environ)
    if mode == "refuse":
        imported = any(
            name in sys.modules
            for name in ("main", "ui", "core.onyx_live_activation_v7")
        )
        raise RuntimeError(
            "ONYX_LIVE_V7_PREIMPORT_REFUSAL " + ("DIRTY" if imported else "CLEAN")
        )
    if mode == "legacy":
        _legacy()
        return
    if mode == "rollback":
        for name in CONTROL:
            os.environ.pop(name, None)
        _legacy()
        return

    import main as onyx_main
    from core.onyx_live_activation_v7 import activate_main, preflight_host

    if sys.argv[1:] == ["--preflight-only"]:
        contract = preflight_host(onyx_main)
        print(
            "ONYX_LIVE_V7_HOST_PREFLIGHT_OK "
            f"bridge={contract.phase5_probe.bridge_type} "
            f"catalog={contract.phase5_probe.catalog_entries} "
            "network_calls=0"
        )
        return
    if sys.argv[1:]:
        raise RuntimeError("Onyx Live V7 launcher arguments are invalid")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V7 starting")
        try:
            activate_main(onyx_main)
            onyx_main.main()
        except BaseException:
            traceback.print_exc()
            raise
        finally:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Onyx Live V7 stopped")


if __name__ == "__main__":
    run()
