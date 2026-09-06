from core.render_governor_v3 import FPS_TIERS, RenderGovernorV3


class FakeClock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        return self.value


def test_v3_preserves_static_idle_and_explicit_fps_tiers() -> None:
    clock = FakeClock()
    governor = RenderGovernorV3(clock=clock, settle_seconds=0.1)
    governor.set_lifecycle(visible=True)
    governor.set_state("LISTENING")
    assert governor.snapshot().target_fps == 12
    clock.value += 0.11
    assert governor.snapshot().target_fps == 0
    for state, expected in (("THINKING", 24), ("PROCESSING", 24), ("SPEAKING", 30)):
        governor.set_state(state)
        assert governor.snapshot().target_fps == expected
        assert expected in FPS_TIERS


def test_v3_hidden_minimized_and_audio_limits_are_preserved() -> None:
    clock = FakeClock()
    governor = RenderGovernorV3(clock=clock)
    governor.set_lifecycle(visible=True)
    governor.set_state("SPEAKING")
    governor.set_lifecycle(visible=True, minimized=True)
    assert governor.snapshot().target_fps == 0
    assert governor.accept_audio_sample()
    clock.value += 0.049
    assert not governor.accept_audio_sample()
    clock.value += 0.001
    assert governor.accept_audio_sample()

