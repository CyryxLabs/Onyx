from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.verify_release_workflow_v33 import (
    RELEASE_V32_RELATIVE,
    RELEASE_V32_ROOT_SHA256,
    RELEASE_V32_SHA256,
)
from scripts.verify_release_workflow_v39 import verify_release_workflow_v39


ROOT = Path(__file__).resolve().parents[1]


def test_release_v32_remains_the_exact_immutable_v33_predecessor() -> None:
    verify_release_workflow_v39(ROOT)
    predecessor = json.loads(
        (ROOT / RELEASE_V32_RELATIVE).read_text(encoding="utf-8")
    )
    successor = json.loads(
        (ROOT / "tests/fixtures/release_workflow_transition_v33.json").read_text(
            encoding="utf-8"
        )
    )
    assert hashlib.sha256((ROOT / RELEASE_V32_RELATIVE).read_bytes()).hexdigest() == (
        RELEASE_V32_SHA256
    )
    assert predecessor["schema"] == "onyx.release-workflow-transition.v32"
    assert predecessor["current_root_sha256"] == RELEASE_V32_ROOT_SHA256
    assert successor["predecessor"] == {
        "path": RELEASE_V32_RELATIVE.as_posix(),
        "sha256": RELEASE_V32_SHA256,
    }


def test_release_v32_historical_fixture_was_not_rebound() -> None:
    verified = verify_release_workflow_v39(ROOT)
    assert verified["transition"]["policy"]["historical_hashes_are_rebound"] is False
    current_paths = {
        entry["path"] for entry in verified["transition"]["current_release_paths"]
    }
    assert "tests/fixtures/release_workflow_transition_v32.json" not in current_paths
