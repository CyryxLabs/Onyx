"""Canonical pre-import launcher for Onyx Live Activation V2."""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "runtime" / "logs" / "onyx-live-v2-startup.log"
MASTER = "ONYX_LIVE_ACTIVATION_V2"
ROLLBACK = "ONYX_LIVE_ROLLBACK_V2"
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
CONTROL = (MASTER, ROLLBACK, *CHILDREN)


def _launch_mode(environ: dict[str, str] | os._Environ[str]) -> str:
    present = {name: environ[name] for name in CONTROL if name in environ}
    if any(value != "1" for value in present.values()):
        return "refuse"
    master = MASTER in present
    rollback = ROLLBACK in present
    children = tuple(name in present for name in CHILDREN)
    complete = all(children)
    empty = not any(children)
    if rollback:
        return "rollback" if (master and complete) or (not master and empty) else "refuse"
    if not master and empty:
        return "legacy"
    if master and complete:
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
        imported = "main" in sys.modules or "ui" in sys.modules
        raise RuntimeError(
            "ONYX_LIVE_V2_PREIMPORT_REFUSAL " + ("DIRTY" if imported else "CLEAN")
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
    from core.onyx_live_activation_v2 import activate_main, preflight_host

    if sys.argv[1:] == ["--preflight-only"]:
        preflight_host(onyx_main)
        print("ONYX_LIVE_V2_HOST_PREFLIGHT_OK")
        return
    if sys.argv[1:]:
        raise RuntimeError("Onyx Live V2 launcher arguments are invalid")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V2 starting")
        try:
            activate_main(onyx_main)
            onyx_main.main()
        except BaseException:
            traceback.print_exc()
            raise
        finally:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Onyx Live V2 stopped")


if __name__ == "__main__":
    run()
