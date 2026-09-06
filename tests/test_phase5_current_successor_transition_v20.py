from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V19 = ROOT / "tests/fixtures/phase5_current_successor_transition_v19.json"
V20 = ROOT / "tests/fixtures/phase5_current_successor_transition_v20.json"
RELEASE_V5 = ROOT / "tests/fixtures/release_workflow_transition_v5.json"
RELEASE_V6 = ROOT / "tests/fixtures/release_workflow_transition_v6.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v20_authenticates_v19_and_only_rebinds_release_builder() -> None:
    _clear()
    transition = json.loads(V20.read_text(encoding="utf-8"))
    assert hashlib.sha256(V20.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V20_SHA256
    )
    assert hashlib.sha256(V19.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V19_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v20"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v19.json",
        "sha256": retirement.CURRENT_TRANSITION_V19_SHA256,
    }
    predecessor = json.loads(V19.read_text(encoding="utf-8"))
    changed = {
        current["path"]
        for current, prior in zip(
            transition["historical_bindings"],
            predecessor["historical_bindings"],
            strict=True,
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert changed == {"scripts/build_release.py"}
    assert transition["current_root_sha256"] == (
        "5465c8628191bc735e92738de42cbf94b5d1b064f593b6ee81b38d060f9f9d13"
    )
    assert transition["policy"]["runtime_authority_changes"] is False


def test_release_v6_authenticates_v5_and_binds_linux_release_boundary() -> None:
    _clear()
    release = json.loads(RELEASE_V6.read_text(encoding="utf-8"))
    assert hashlib.sha256(RELEASE_V6.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V6_SHA256
    )
    assert hashlib.sha256(RELEASE_V5.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V5_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v6"
    paths = {item["path"] for item in release["current_release_paths"]}
    assert "packaging/linux/Dockerfile.release-validation" in paths
    assert "tests/test_release_version_v119.py" in paths
    assert release["current_root_sha256"] == (
        "80db75826acb2a06e4b5ff160b7cb93a4381dd1bef5d857af75e100946676b44"
    )
