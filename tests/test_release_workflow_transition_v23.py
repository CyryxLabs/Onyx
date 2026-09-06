from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V22 = ROOT / "tests/fixtures/release_workflow_transition_v22.json"
V23 = ROOT / "tests/fixtures/release_workflow_transition_v23.json"


def test_release_v23_binds_final_v37_runtime_hud_packaging_and_evidence() -> None:
    release = json.loads(V23.read_text(encoding="utf-8"))
    assert hashlib.sha256(V23.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V23_SHA256
    )
    assert hashlib.sha256(V22.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V22_SHA256
    )
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v22.json",
        "sha256": retirement.RELEASE_TRANSITION_V22_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "main.py",
        "ui.py",
        "core/onyx_live_activation_v24.py",
        "scripts/bootstrap_onyx_live_v24.pyw",
        "scripts/launch_onyx_live_v24.pyw",
        "core/installer_lifecycle_v1.py",
        "packaging/windows/onyx.iss",
        "packaging/onyx.spec",
        "core/onyx_hud_orb_v10.py",
        "qml/OnyxLiveShellV10.qml",
        "core/onyx_hud_current_acceptance_v21.py",
        "core/onyx_hud_current_acceptance_v22.py",
        "core/onyx_hud_current_acceptance_v23.py",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V21-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V22-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V23-E6-001.manifest.json",
        "tests/test_onyx_hud_current_acceptance_v21.py",
        "tests/test_onyx_hud_current_acceptance_v22.py",
        "tests/test_onyx_hud_current_acceptance_v23.py",
        "tests/test_onyx_live_activation_v24.py",
        "tests/test_installer_lifecycle_v1.py",
        "tests/test_posix_packaged_default_activation_v1.py",
        "tests/test_governed_shutdown_v35.py",
        "tests/test_runtime_shutdown_hardening_v1.py",
        "tests/test_runtime_construction_transaction_v1.py",
        "tests/test_live_audio_stream_ownership_v1.py",
        "tests/test_dayops_ui_v19.py",
        "tests/test_document_intake_ui_v181.py",
        "docs/onyx/CURRENT_RELEASE_STATUS.md",
        "docs/onyx/FINAL_EVIDENCE_INDEX_1.1.9.md",
        "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V37_2026-08-04.md",
        "tests/fixtures/phase5_current_successor_transition_v34.json",
        "tests/test_phase5_current_successor_transition_v34.py",
        "tests/test_release_workflow_transition_v22.py",
    }.issubset(paths)
    assert {
        "scripts/verify_phase5_exit_retirement_v1.py",
        "tests/fixtures/release_workflow_transition_v23.json",
        "tests/test_release_workflow_transition_v23.py",
    }.isdisjoint(paths)
    assert len(paths) == 176
    assert release["current_root_sha256"] == (
        "e62bd0ae621160623d13599f8df673f62e8134dd6da593b92bf58e4642a98cb7"
    )
