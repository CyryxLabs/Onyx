"""Desktop bootstrap that establishes the exact active V8 environment."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v8.pyw"
ACTIVE = {
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
    for version in range(1, 9)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CLEAR = (*VERSION_CONTROLS, *ACTIVE, *ALIASES)


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> dict[str, str]:
    result = dict(environ)
    for name in CLEAR:
        result.pop(name, None)
    result.update(ACTIVE)
    return result


def run() -> None:
    if sys.argv[1:] not in ([], ["--preflight-only"]):
        raise RuntimeError("Onyx Live V8 bootstrap arguments are invalid")
    if not LAUNCHER.is_file():
        raise RuntimeError("Onyx Live V8 canonical launcher is unavailable")
    prepared = _bootstrap_environment(os.environ)
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
