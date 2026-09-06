from __future__ import annotations

import math

from core.orb_motion_v1 import OrbMotionPolicyV1


def _visible_policy(state: str = "LISTENING") -> OrbMotionPolicyV1:
    policy = OrbMotionPolicyV1()
    policy.configure(state=state, visible=True)
    return policy


def test_state_mapping_is_alive_and_bounded() -> None:
    expected = {
        "INITIALISING": 8,
        "LISTENING": 10,
        "THINKING": 16,
        "PROCESSING": 16,
        "SPEAKING": 24,
        "ERROR": 8,
    }
    for state, fps in expected.items():
        policy = _visible_policy(state)
        assert policy.target_fps == fps
        frame = policy.next_frame()
        assert frame is not None
        assert frame.interval_ms >= 42
        assert math.isfinite(frame.scale)
        assert math.isfinite(frame.rotation)


def test_hidden_minimized_reduced_motion_muted_and_offline_are_static() -> None:
    for options in (
        {"visible": False},
        {"visible": True, "minimized": True},
        {"visible": True, "reduced_motion": True},
        {"visible": True, "muted": True},
        {"visible": True, "state": "MUTED"},
        {"visible": True, "state": "OFFLINE"},
    ):
        policy = OrbMotionPolicyV1()
        policy.configure(**options)
        assert not policy.running
        assert policy.target_fps == 0
        assert policy.next_frame() is None


def test_speaking_motion_uses_audio_and_has_silent_envelope_fallback() -> None:
    quiet = _visible_policy("SPEAKING")
    loud = _visible_policy("SPEAKING")
    loud.configure(audio_level=1.0)
    quiet_frames = [quiet.next_frame() for _ in range(12)]
    loud_frames = [loud.next_frame() for _ in range(12)]
    assert all(frame is not None for frame in quiet_frames + loud_frames)
    quiet_scales = [frame.scale for frame in quiet_frames if frame is not None]
    loud_scales = [frame.scale for frame in loud_frames if frame is not None]
    assert max(quiet_scales) - min(quiet_scales) > 0.004
    assert max(loud_scales) - min(loud_scales) > (
        max(quiet_scales) - min(quiet_scales)
    )
    assert loud.smoothed_audio_level > 0.95


def test_listening_has_a_visible_low_cadence_respiratory_cycle() -> None:
    policy = _visible_policy("LISTENING")
    frames = [policy.next_frame() for _ in range(48)]
    scales = [frame.scale for frame in frames if frame is not None]
    rotations = [frame.rotation for frame in frames if frame is not None]
    assert len(scales) == 48
    assert max(scales) - min(scales) >= 0.020
    assert max(rotations) - min(rotations) >= 0.35
    assert all(0.97 <= scale <= 1.055 for scale in scales)


def test_voice_envelope_has_fast_attack_and_natural_release() -> None:
    policy = _visible_policy("SPEAKING")
    policy.configure(audio_level=1.0)
    policy.next_frame()
    first_attack = policy.smoothed_audio_level
    assert 0.25 < first_attack < 0.5
    for _ in range(11):
        policy.next_frame()
    assert policy.smoothed_audio_level > 0.95

    policy.configure(audio_level=0.0)
    policy.next_frame()
    first_release = policy.smoothed_audio_level
    assert 0.75 < first_release < 0.95
    for _ in range(40):
        policy.next_frame()
    assert policy.smoothed_audio_level < 0.01


def test_low_power_caps_every_state_at_ten_fps() -> None:
    policy = _visible_policy("SPEAKING")
    policy.configure(low_power=True)
    assert policy.target_fps == 10


def test_frame_budget_misses_adapt_down_without_stopping_motion() -> None:
    policy = _visible_policy("SPEAKING")
    assert policy.target_fps == 24
    assert not policy.report_frame(100.0)
    assert not policy.report_frame(100.0)
    assert policy.report_frame(100.0)
    assert policy.target_fps == 16
    assert policy.running
