from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v35 import (
    RELEASE_V34_ROOT_SHA256,
    RELEASE_V34_SHA256,
)
from scripts.verify_release_workflow_v39 import (
    ReleaseWorkflowV39Error,
    verify_release_workflow_v39,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v34_remains_immutable_under_current_v38() -> None:
    result = verify_release_workflow_v39(ROOT)
    assert result["transition"]["schema"] == "onyx.release-workflow-transition.v39"
    assert result["runtime"]["packaged_subset_contract"] == "v1"
    fixture = ROOT / "tests/fixtures/release_workflow_transition_v34.json"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V34_SHA256
    assert len(RELEASE_V34_ROOT_SHA256) == 64


def test_release_v34_successor_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV39Error)):
        verify_release_workflow_v39(tmp_path)
