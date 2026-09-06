from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V11 = ROOT / "tests/fixtures/release_workflow_transition_v11.json"
V12 = ROOT / "tests/fixtures/release_workflow_transition_v12.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v12_authenticates_v11_and_binds_pinned_appimage_runtime() -> None:
    _clear()
    release = json.loads(V12.read_text(encoding="utf-8"))

    assert hashlib.sha256(V12.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V12_SHA256
    )
    assert hashlib.sha256(V11.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V11_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v12"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v11.json",
        "sha256": retirement.RELEASE_TRANSITION_V11_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        ".github/workflows/release-packages.yml",
        "docs/INSTALLATION.md",
        "scripts/build_release.py",
        "scripts/run_linux_release_validation.sh",
        "tests/fixtures/phase5_current_successor_transition_v25.json",
        "tests/test_native_release_gate_v1.py",
        "tests/test_phase5_current_successor_transition_v25.py",
        "tests/test_release_version_v119.py",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "0fd0eef7848653c32b4ab2b45b9b395c35e67b4e0b2c61185ee2bdaa6123cf8b"
    )
