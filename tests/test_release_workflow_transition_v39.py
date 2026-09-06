from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v39 import (
    RELEASE_V39_ROOT_SHA256,
    RELEASE_V39_SHA256,
    ReleaseWorkflowV39Error,
    verify_release_workflow_v39,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v39_authenticates_phase11_long_path_fix_and_v38() -> None:
    result = verify_release_workflow_v39(ROOT)
    assert result["transition"]["schema"] == "onyx.release-workflow-transition.v39"
    assert result["transition"]["current_root_sha256"] == RELEASE_V39_ROOT_SHA256
    assert result["v38_predecessor"]["schema"] == (
        "onyx.release-workflow-transition.v38"
    )
    assert result["runtime"]["packaged_subset_contract"] == "v1"
    fixture = ROOT / "tests/fixtures/release_workflow_transition_v39.json"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V39_SHA256


def test_release_v39_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV39Error)):
        verify_release_workflow_v39(tmp_path)
