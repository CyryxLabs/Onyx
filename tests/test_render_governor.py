import math
import time

import pytest

from core.render_governor import FPS_TIERS, RenderGovernor


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def visible_governor(clock: FakeClock, **kwargs) -> RenderGovernor:
    governor = RenderGovernor(clock=clock, **kwargs)
    governor.set_lifecycle(visible=True)
    return governor


def test_idle_becomes_a_static_frame_after_settle() -> None:
    clock = FakeClock()
    governor = visible_governor(clock, settle_seconds=0.5)
    governor.set_state("LISTENING")
    assert governor.snapshot().target_fps == 12
    clock.advance(0.49)
    assert governor.snapshot().animation_running
    clock.advance(0.02)
    snapshot = governor.snapshot()
    assert snapshot.target_fps == 0
    assert not snapshot.animation_running


def test_active_states_use_only_the_three_explicit_tiers() -> None:
    clock = FakeClock()
    governor = visible_governor(clock)
    expected = {"THINKING": 24, "PROCESSING": 24, "SPEAKING": 30}
    for state, fps in expected.items():
        governor.set_state(state)
        snapshot = governor.snapshot()
        assert snapshot.target_fps == fps
        assert snapshot.target_fps in FPS_TIERS


def test_hidden_minimized_muted_and_reduced_motion_stop_rendering() -> None:
    clock = FakeClock()
    governor = visible_governor(clock)
    governor.set_state("SPEAKING")
    assert governor.snapshot().target_fps == 30

    governor.set_lifecycle(visible=True, minimized=True)
    assert governor.snapshot().target_fps == 0
    governor.set_lifecycle(visible=False, minimized=False)
    assert governor.snapshot().target_fps == 0
    governor.set_lifecycle(visible=True)
    governor.set_muted(True)
    assert governor.snapshot().target_fps == 0
    governor.set_muted(False)
    governor.set_reduced_motion(True)
    assert governor.snapshot().target_fps == 0


def test_audio_visual_updates_are_capped_at_twenty_hertz() -> None:
    clock = FakeClock()
    governor = RenderGovernor(clock=clock)
    assert governor.accept_audio_sample()
    clock.advance(0.049)
    assert not governor.accept_audio_sample()
    clock.advance(0.001)
    assert governor.accept_audio_sample()
    clock.advance(0.05)
    assert governor.accept_audio_sample()


def test_adaptation_downgrades_fast_and_upgrades_with_hysteresis() -> None:
    clock = FakeClock()
    governor = visible_governor(
        clock, downgrade_streak=3, upgrade_streak=4, upgrade_cooldown=2.0
    )
    governor.set_state("SPEAKING")
    for _ in range(3):
        governor.report_frame(50.0)
        clock.advance(0.04)
    assert governor.snapshot().target_fps == 24

    for _ in range(4):
        governor.report_frame(5.0)
        clock.advance(0.04)
    assert governor.snapshot().target_fps == 24

    clock.advance(2.0)
    for _ in range(4):
        governor.report_frame(5.0)
        clock.advance(0.04)
    assert governor.snapshot().target_fps == 30


@pytest.mark.parametrize("value", [-1.0, math.nan, math.inf])
def test_invalid_frame_metrics_are_rejected(value: float) -> None:
    governor = RenderGovernor()
    with pytest.raises(ValueError):
        governor.report_frame(value)


def test_governor_hot_path_is_bounded_software_work() -> None:
    clock = FakeClock()
    governor = visible_governor(clock)
    governor.set_state("PROCESSING")
    started = time.perf_counter()
    for _ in range(20_000):
        governor.snapshot()
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0

