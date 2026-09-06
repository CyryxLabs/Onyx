from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v40 import (
    RELEASE_V40_ROOT_SHA256,
    RELEASE_V40_SHA256,
    ReleaseWorkflowV40Error,
    verify_release_workflow_v40,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v40_authenticates_single_root_fix_and_v39() -> None:
    result = verify_release_workflow_v40(ROOT)
    assert result["transition"]["schema"] == "onyx.release-workflow-transition.v40"
    assert result["transition"]["current_root_sha256"] == RELEASE_V40_ROOT_SHA256
    assert result["v39_predecessor"]["schema"] == (
        "onyx.release-workflow-transition.v39"
    )
    assert result["runtime"]["candidate"] == (
        "onyx-hud-v10-v40-single-root-accessibility-stability-009"
    )
    assert result["runtime"]["qml_roots_published_at_construction"] == 1
    fixture = ROOT / "tests/fixtures/release_workflow_transition_v40.json"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V40_SHA256


def test_release_v40_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV40Error)):
        verify_release_workflow_v40(tmp_path)
