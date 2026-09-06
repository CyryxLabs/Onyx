from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V20 = ROOT / "tests/fixtures/release_workflow_transition_v20.json"
V21 = ROOT / "tests/fixtures/release_workflow_transition_v21.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v21_authenticates_v20_and_binds_v32_resident_lifecycle() -> None:
    _clear()
    release = json.loads(V21.read_text(encoding="utf-8"))
    assert hashlib.sha256(V21.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V21_SHA256
    )
    assert (
        hashlib.sha256(V20.read_bytes()).hexdigest()
        == retirement.RELEASE_TRANSITION_V20_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v21"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v20.json",
        "sha256": retirement.RELEASE_TRANSITION_V20_SHA256,
    }
    hashes = {
        entry["path"]: entry["sha256"]
        for entry in release["current_release_paths"]
    }
    assert hashes["main.py"] == (
        "9193fcc8e32f1a8b93c9a265e4e260bddac9c21c2c3dfee4bab966b40cc1ecb4"
    )
    assert hashes["ui.py"] == (
        "708e340670efedd0a6523e2233fcb46314862e74de1a0d1b6a840dea47015b0f"
    )
    assert hashes["tests/fixtures/phase5_current_successor_transition_v32.json"] == (
        "597801d7c0ea273d132ced1e1d936279c68ac4963b3a1235afa742bb1d4afcef"
    )
    assert hashes["tests/test_phase5_current_successor_transition_v32.py"] == (
        "c8669bf972bbb909700ab3c16ae458913f82829967b866bb32ebc2059037aa4c"
    )
    assert hashes["tests/test_close_to_background_v1.py"] == (
        "4a8769936588061b1eba289da49c3b3a468388ed84546f0536515e5fe714cafb"
    )
    assert hashes["tests/test_shutdown_intent_v1.py"] == (
        "6e9da4880cd3e98fa390e762cd04a2a2eec52d59afe8c82a8f7cf20e912ea419"
    )
    assert "scripts/verify_phase5_exit_retirement_v1.py" not in hashes
    assert "tests/test_release_workflow_transition_v21.py" not in hashes
    assert release["current_root_sha256"] == (
        "aec9f8a0dc2d4a5a7a714a7092bde299e256b185c8fb64f7741ba18a37ca698b"
    )
