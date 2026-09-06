from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v44 import (
    RELEASE_V44_RELATIVE,
    RELEASE_V44_ROOT_SHA256,
    RELEASE_V44_SHA256,
    ReleaseWorkflowV44Error,
    verify_release_workflow_v44,
)
from scripts.verify_release_workflow_v45 import verify_release_workflow_v45


ROOT = Path(__file__).resolve().parents[1]


def test_release_v44_authenticates_fully_hermetic_historical_pack() -> None:
    result = verify_release_workflow_v45(ROOT)
    assert result["v44_predecessor"]["schema"] == (
        "onyx.release-workflow-transition.v44"
    )
    assert result["v44_predecessor"]["current_root_sha256"] == (
        RELEASE_V44_ROOT_SHA256
    )
    assert result["blob_count"] == 49
    assert result["head_file_count"] == 26
    fixture = ROOT / RELEASE_V44_RELATIVE
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V44_SHA256


def test_release_v44_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV44Error)):
        verify_release_workflow_v44(tmp_path)
