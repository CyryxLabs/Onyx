from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v47 import (
    RELEASE_V47_RELATIVE,
    RELEASE_V47_ROOT_SHA256,
    RELEASE_V47_SHA256,
    ReleaseWorkflowV47Error,
    verify_release_workflow_v47,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v47_authenticates_dependency_safe_successor() -> None:
    result = verify_release_workflow_v47(ROOT)
    assert result["transition"]["schema"] == (
        "onyx.release-workflow-transition.v47"
    )
    assert result["transition"]["current_root_sha256"] == RELEASE_V47_ROOT_SHA256
    assert result["v46_predecessor"]["schema"] == (
        "onyx.release-workflow-transition.v46"
    )
    assert result["runtime"]["current_root"] == "qml/OnyxLiveShellV11.qml"
    assert result["blob_count"] == 49
    assert result["head_file_count"] == 26
    fixture = ROOT / RELEASE_V47_RELATIVE
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V47_SHA256


def test_release_v47_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV47Error)):
        verify_release_workflow_v47(tmp_path)
