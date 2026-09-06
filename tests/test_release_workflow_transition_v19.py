from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V18 = ROOT / "tests/fixtures/release_workflow_transition_v18.json"
V19 = ROOT / "tests/fixtures/release_workflow_transition_v19.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v19_authenticates_v18_and_binds_final_cleanroom_successor() -> None:
    _clear()
    release = json.loads(V19.read_text(encoding="utf-8"))
    assert hashlib.sha256(V19.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V19_SHA256
    assert hashlib.sha256(V18.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V18_SHA256
    assert release["schema"] == "onyx.release-workflow-transition.v19"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v18.json",
        "sha256": retirement.RELEASE_TRANSITION_V18_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "core/content_lifecycle_projection_v1.py",
        "core/portable_accessibility_actions_v1.py",
        "core/site_recipe_catalog_v1.py",
        "tests/test_content_lifecycle_projection_v1.py",
        "tests/test_portable_accessibility_actions_v1.py",
        "tests/test_site_recipe_catalog_v1.py",
        "tests/fixtures/phase5_current_successor_transition_v31.json",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "56e9531b8f3e8e38ae76d0e36a07322fdb07ef694767ab4e2d6c9b226d25481a"
    )
