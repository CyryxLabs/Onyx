from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v45 import (
    RELEASE_V45_RELATIVE,
    RELEASE_V45_ROOT_SHA256,
    RELEASE_V45_SHA256,
    ReleaseWorkflowV45Error,
    verify_release_workflow_v45,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v45_authenticates_portable_and_hud_corrections() -> None:
    result = verify_release_workflow_v45(ROOT)
    assert result["transition"]["schema"] == (
        "onyx.release-workflow-transition.v45"
    )
    assert result["transition"]["current_root_sha256"] == RELEASE_V45_ROOT_SHA256
    assert result["v44_predecessor"]["schema"] == (
        "onyx.release-workflow-transition.v44"
    )
    assert result["blob_count"] == 49
    assert result["head_file_count"] == 26
    fixture = ROOT / RELEASE_V45_RELATIVE
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V45_SHA256


def test_release_v45_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV45Error)):
        verify_release_workflow_v45(tmp_path)
