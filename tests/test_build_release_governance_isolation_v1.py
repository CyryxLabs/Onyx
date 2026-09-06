from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from core.onyx_live_activation_v16 import GOVERNANCE_SMOKE_OUTPUT_ENV
from core.onyx_live_activation_v19 import CONTROL_FLAGS
from scripts import build_release


def test_packaged_governance_smoke_removes_inherited_control_flags(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "Onyx.exe").write_bytes(b"fixture")
    inherited = tuple(dict.fromkeys(CONTROL_FLAGS))
    for name in inherited:
        monkeypatch.setenv(name, "inherited-partial-value")
    monkeypatch.setattr(build_release.platform, "system", lambda: "Windows")

    captured: dict[str, str] = {}

    def run(_command, **options):
        environment = options["env"]
        captured.update(environment)
        output = Path(environment[GOVERNANCE_SMOKE_OUTPUT_ENV])
        output.write_text(
            json.dumps(
                {
                    "contract": "OnyxGovernanceSmoke.v1",
                    "status": "passed",
                    "trusted_ui_prompts": 0,
                    "grant_reused": True,
                    "grant_use_count_after_two": 2,
                    "grant_revoke_replaced": True,
                    "grant_expiry_replaced": True,
                    "restart_active_grants": 0,
                    "global_kill_latched": True,
                    "late_result_event": "action-late-blocked",
                    "restart_kill_denied": True,
                    "network_calls": 0,
                    "provider_calls": 0,
                    "catalog_reads": [
                        {"state": "completed", "items": 2},
                        {"state": "completed", "items": 2},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(build_release.subprocess, "run", run)

    build_release.package_governance_smoke_test(bundle)

    assert all(name not in captured for name in inherited)
    assert captured["QT_QPA_PLATFORM"] == "offscreen"
