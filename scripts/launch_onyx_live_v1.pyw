"""Opt-in Onyx Live V1 launcher; exact legacy delegation when disabled."""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "runtime" / "logs" / "onyx-live-v1-startup.log"
MASTER = "ONYX_LIVE_ACTIVATION_V1"
ROLLBACK = "ONYX_LIVE_ROLLBACK_V1"
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


def _true(name: str) -> bool:
    value = os.environ.get(name, "")
    return type(value) is str and value.strip().casefold() in {"1", "true"}


def run() -> None:
    os.chdir(ROOT)
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    # Rollback neutralizes all accepted component flags before legacy import;
    # otherwise main.py/ui.py could still observe their standalone opt-ins.
    if _true(ROLLBACK):
        os.environ.pop(MASTER, None)
        for name in CHILDREN:
            os.environ.pop(name, None)
        from scripts.launch_onyx import run as legacy_run

        legacy_run()
        return

    # This is the exact historical/default-off path. Partial child activation
    # through the coordinated launcher is refused before importing main/UI.
    if not _true(MASTER):
        if any(_true(name) for name in CHILDREN):
            raise RuntimeError("Onyx Live V1 child flag set without master")
        from scripts.launch_onyx import run as legacy_run

        legacy_run()
        return

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V1 starting")
        try:
            import main as onyx_main
            from core.onyx_live_activation_v1 import activate_main

            activate_main(onyx_main)
            onyx_main.main()
        except BaseException:
            traceback.print_exc()
            raise
        finally:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Onyx Live V1 stopped")


if __name__ == "__main__":
    run()
