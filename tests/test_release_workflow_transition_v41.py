from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v41 import (
    RELEASE_V41_ROOT_SHA256,
    RELEASE_V41_SHA256,
    ReleaseWorkflowV41Error,
    verify_release_workflow_v41,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v41_authenticates_installer_smoke_isolation_and_v40() -> None:
    result = verify_release_workflow_v41(ROOT)
    assert result["transition"]["schema"] == "onyx.release-workflow-transition.v41"
    assert result["transition"]["current_root_sha256"] == RELEASE_V41_ROOT_SHA256
    assert result["v40_predecessor"]["schema"] == (
        "onyx.release-workflow-transition.v40"
    )
    assert result["runtime"]["qml_roots_published_at_construction"] == 1
    fixture = ROOT / "tests/fixtures/release_workflow_transition_v41.json"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V41_SHA256


def test_release_v41_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV41Error)):
        verify_release_workflow_v41(tmp_path)
