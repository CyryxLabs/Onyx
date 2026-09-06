from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v46 import (
    RELEASE_V46_RELATIVE,
    RELEASE_V46_ROOT_SHA256,
    RELEASE_V46_SHA256,
    ReleaseWorkflowV46Error,
    verify_release_workflow_v46,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v46_authenticates_hud_v30_and_runtime_closure() -> None:
    result = verify_release_workflow_v46(ROOT)
    assert result["transition"]["schema"] == (
        "onyx.release-workflow-transition.v46"
    )
    assert result["transition"]["current_root_sha256"] == RELEASE_V46_ROOT_SHA256
    assert result["v45_predecessor"]["schema"] == (
        "onyx.release-workflow-transition.v45"
    )
    assert result["runtime"]["current_root"] == "qml/OnyxLiveShellV11.qml"
    assert result["blob_count"] == 49
    assert result["head_file_count"] == 26
    fixture = ROOT / RELEASE_V46_RELATIVE
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V46_SHA256


def test_release_v46_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV46Error)):
        verify_release_workflow_v46(tmp_path)
