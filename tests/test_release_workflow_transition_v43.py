from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v43 import (
    RELEASE_V43_RELATIVE,
    RELEASE_V43_ROOT_SHA256,
    RELEASE_V43_SHA256,
    ReleaseWorkflowV43Error,
    verify_release_workflow_v43,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v43_authenticates_hermetic_historical_blob_pack() -> None:
    fixture = ROOT / RELEASE_V43_RELATIVE
    transition = json.loads(fixture.read_text(encoding="utf-8"))
    assert transition["schema"] == "onyx.release-workflow-transition.v43"
    assert transition["current_root_sha256"] == RELEASE_V43_ROOT_SHA256
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V43_SHA256
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert "tests/fixtures/r11_historical_blobs_v1.zip" in paths
    assert "scripts/verify_r11_projection_retirement_v1.py" in paths


def test_release_v43_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV43Error)):
        verify_release_workflow_v43(tmp_path)
