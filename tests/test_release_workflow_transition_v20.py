from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V19 = ROOT / "tests/fixtures/release_workflow_transition_v19.json"
V20 = ROOT / "tests/fixtures/release_workflow_transition_v20.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v20_authenticates_v19_and_binds_v31_documentation() -> None:
    _clear()
    release = json.loads(V20.read_text(encoding="utf-8"))
    assert (
        hashlib.sha256(V20.read_bytes()).hexdigest()
        == retirement.RELEASE_TRANSITION_V20_SHA256
    )
    assert hashlib.sha256(V19.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V19_SHA256
    assert release["schema"] == "onyx.release-workflow-transition.v20"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v19.json",
        "sha256": retirement.RELEASE_TRANSITION_V19_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "docs/onyx/CURRENT_RELEASE_STATUS.md",
        "docs/onyx/DOCUMENTATION_INDEX.md",
        "docs/onyx/DOCUMENT_SUPERSESSION_REGISTRY_V31_2026-08-04.md",
        "docs/onyx/FINAL_EVIDENCE_INDEX_1.1.9.md",
        "docs/onyx/LEGAL_RELEASE_APPROVAL_1.1.9.md",
        "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V31_2026-08-04.md",
        "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V24_2026-08-04.md",
        "docs/onyx/THIRD_PARTY_LICENSE_REVIEW_WORKLIST_1.1.9.md",
        "docs/onyx/operations/ONYX_1_1_9_V24_WINDOWS_ACCEPTANCE_2026-08-04.md",
        "docs/onyx/operations/ONYX_1_1_9_V31_WINDOWS_ACCEPTANCE_2026-08-04.md",
        "tests/test_documentation_precedence_v1.py",
    }.issubset(paths)
    hashes = {
        entry["path"]: entry["sha256"]
        for entry in release["current_release_paths"]
    }
    assert hashes["docs/onyx/LEGAL_RELEASE_APPROVAL_1.1.9.md"] == (
        "ed4d8e5580cf06bf998af329afd0b7347d90585b0553d4f017a4a3db25669ec1"
    )
    assert hashes["docs/onyx/THIRD_PARTY_LICENSE_REVIEW_WORKLIST_1.1.9.md"] == (
        "d3db03d4ce07a95d39575735e42a5c344161c1c9025fe463a5e36de0c23c5a9a"
    )
    assert release["current_root_sha256"] == (
        "3ebd6dd11a6a8c55001e70c883d411b26857ba02100436f3617226d5d7d6a971"
    )
