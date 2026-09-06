from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.verify_release_workflow_v50 import verify_release_workflow_v50


ROOT = Path(__file__).resolve().parents[1]


def test_release_v50_authenticates_post_r10b_evidence_successor() -> None:
    result = verify_release_workflow_v50(ROOT)
    transition = result["transition"]
    assert transition["schema"] == "onyx.release-workflow-transition.v50"
    assert transition["logical_sequence"] == 50
    assert transition["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v49.json",
        "sha256": hashlib.sha256(
            (ROOT / "tests/fixtures/release_workflow_transition_v49.json").read_bytes()
        ).hexdigest(),
    }
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {
        "docs/onyx/DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md",
        "docs/onyx/checkpoints/LEGAL_DECISION_PACKET_R10B_V1.json",
        "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_2026-08-04.md",
        "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V23_2026-08-04.md",
        "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V24_2026-08-04.md",
        "docs/onyx/operations/ONYX_1_1_9_V31_WINDOWS_ACCEPTANCE_2026-08-04.md",
        "docs/onyx/operations/ONYX_1_1_9_V41_LINUX_BUILD_FAILURE_2026-08-10.md",
        "docs/onyx/operations/ONYX_1_1_9_V41_SBOM_RECONCILIATION_2026-08-10.md",
        "docs/onyx/operations/ONYX_1_1_9_V41_WINDOWS_ACCEPTANCE_2026-08-10.md",
        "scripts/reconcile_release_compliance_v1.py",
        "scripts/verify_legal_decision_packet_r10b_v1.py",
        "tests/test_release_compliance_reconciliation_v1.py",
        "tests/test_current_release_documentation_r10b.py",
        "tests/test_legal_decision_packet_r10b_v1.py",
    } <= paths
    assert result["runtime"]["post_load_lifecycle_resynchronised"] is True
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
