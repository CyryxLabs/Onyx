from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V15 = ROOT / "tests/fixtures/phase5_current_successor_transition_v15.json"
V16 = ROOT / "tests/fixtures/phase5_current_successor_transition_v16.json"
RELEASE_V2 = ROOT / "tests/fixtures/release_workflow_transition_v2.json"
RELEASE_V3 = ROOT / "tests/fixtures/release_workflow_transition_v3.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v16_authenticates_exact_v15_predecessor_and_domain_root() -> None:
    transition = json.loads(V16.read_text(encoding="utf-8"))
    assert hashlib.sha256(V16.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V16_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v16"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v15.json",
        "sha256": retirement.CURRENT_TRANSITION_V15_SHA256,
    }
    assert transition["current_root_sha256"] == (
        "83bf7e45fed9ffbf23aff9ab824b4371d53813d317fb5ef181d8b362edb588aa"
    )


def test_v16_records_only_portable_archive_builder_delta() -> None:
    v15 = json.loads(V15.read_text(encoding="utf-8"))
    v16 = json.loads(V16.read_text(encoding="utf-8"))
    deltas = {
        current["path"]
        for current, prior in zip(
            v16["historical_bindings"], v15["historical_bindings"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    successor_deltas = {
        current["path"]
        for current, prior in zip(
            v16["named_successors"], v15["named_successors"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert deltas == {"scripts/build_release.py"}
    assert successor_deltas == set()
    assert v16["policy"]["runtime_authority_changes"] is False


def test_release_v3_authenticates_exact_v2_and_zip_regression_test() -> None:
    transition = json.loads(RELEASE_V3.read_text(encoding="utf-8"))
    assert hashlib.sha256(RELEASE_V3.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V3_SHA256
    )
    assert hashlib.sha256(RELEASE_V2.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V2_SHA256
    )
    assert transition["schema"] == "onyx.release-workflow-transition.v3"
    paths = {
        item["path"]: item["sha256"]
        for item in transition["current_release_paths"]
    }
    assert paths["tests/test_release_preparation_v110.py"] == (
        "374c83d27731ef3f8fbbb34857a1d4ed7b486fd53b50f898f8c95abcd6653e0e"
    )
    assert transition["current_root_sha256"] == (
        "a8409ad8262e989e608f9368b05a9924cfcb9d6a4c203a3d2539bc9f3425e5fc"
    )
