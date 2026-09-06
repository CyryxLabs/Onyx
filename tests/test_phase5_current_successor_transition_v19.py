from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import main
from core import live_voice_continuity_v1 as continuity
from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V18 = ROOT / "tests/fixtures/phase5_current_successor_transition_v18.json"
V19 = ROOT / "tests/fixtures/phase5_current_successor_transition_v19.json"
RELEASE_V5 = ROOT / "tests/fixtures/release_workflow_transition_v5.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v19_authenticates_v18_and_only_rebinds_main_history() -> None:
    _clear()
    transition = json.loads(V19.read_text(encoding="utf-8"))
    assert hashlib.sha256(V19.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V19_SHA256
    )
    assert hashlib.sha256(V18.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V18_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v19"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v18.json",
        "sha256": retirement.CURRENT_TRANSITION_V18_SHA256,
    }
    assert transition["current_root_sha256"] == (
        "c0dc1de139e86a46a046aac5799edd6e990b3ce033d3fa9e75094574a18c1b38"
    )
    predecessor = json.loads(V18.read_text(encoding="utf-8"))
    changed = {
        current["path"]
        for current, prior in zip(
            transition["historical_bindings"],
            predecessor["historical_bindings"],
            strict=True,
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert changed == {"main.py"}
    assert transition["policy"]["runtime_authority_changes"] is False


def test_v19_keeps_native_audio_alive_around_transport_rotation() -> None:
    network = inspect.getsource(continuity._run_provider_network_loop_v1)
    lifetime = inspect.getsource(continuity.run_provider_loop_v1)
    microphone = inspect.getsource(main.OnyxLive._listen_audio)
    assert "instance._listen_audio()" not in network
    assert "instance._play_audio()" not in network
    assert "instance._listen_audio()" in lifetime
    assert "instance._play_audio()" in lifetime
    assert "self.session is not None" in microphone


def test_v19_keeps_release_v5_exactly_bound() -> None:
    _clear()
    release = json.loads(RELEASE_V5.read_text(encoding="utf-8"))
    assert hashlib.sha256(RELEASE_V5.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V5_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v5"
    assert release["current_root_sha256"] == (
        "5c1c1d3fd401ad1212b24b1b784b41304982f1a15a51258fd63ca8c41877fd9f"
    )
