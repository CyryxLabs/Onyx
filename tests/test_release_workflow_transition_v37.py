from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v39 import (
    RELEASE_V37_ROOT_SHA256,
    RELEASE_V37_SHA256,
    ReleaseWorkflowV39Error,
    verify_release_workflow_v39,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v37_remains_immutable_under_current_v39() -> None:
    result = verify_release_workflow_v39(ROOT)
    assert result["transition"]["schema"] == "onyx.release-workflow-transition.v39"
    assert result["v38_predecessor"]["schema"] == "onyx.release-workflow-transition.v38"
    assert len(RELEASE_V37_ROOT_SHA256) == 64
    assert result["runtime"]["packaged_subset_contract"] == "v1"
    fixture = ROOT / "tests/fixtures/release_workflow_transition_v37.json"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V37_SHA256


def test_release_v37_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV39Error)):
        verify_release_workflow_v39(tmp_path)
