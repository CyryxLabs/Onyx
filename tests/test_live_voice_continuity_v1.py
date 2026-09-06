from __future__ import annotations

from types import SimpleNamespace

from core.enhanced_live_audio_v1 import EnhancedAudioModeV1

def test_live_config_pins_style_compression_and_resume_handle(monkeypatch) -> None:
    import main

    host = main.OnyxLive.__new__(main.OnyxLive)
    host._phase5 = None
    host._live_session_resume_handle = "resume-token"
    monkeypatch.setattr(main, "load_memory", lambda: {})
    monkeypatch.setattr(main, "_load_owner_name", lambda: "")
    monkeypatch.setattr(main, "_load_system_prompt", lambda: "SYSTEM")

    config = main.OnyxLive._build_config(host)

    assert config.session_resumption.handle == "resume-token"
    assert config.context_window_compression.sliding_window is not None
    assert "natural native-audio voice" in str(config.system_instruction)
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Charon"


def test_receive_path_retains_handle_and_rotates_before_audio_fallback() -> None:
    source = __import__("inspect").getsource(
        __import__("main").OnyxLive._receive_audio
    )
    assert "session_resumption_update" in source
    assert "_live_session_resume_handle" in source
    assert "response.go_away" in source
    assert "raise LiveSessionRotation" in source
    assert "create_tts_player" not in source


class _UI:
    def __init__(self) -> None:
        self.logs: list[str] = []

    def write_log(self, value: str) -> None:
        self.logs.append(value)


def _fallback_host():
    import main

    host = main.OnyxLive.__new__(main.OnyxLive)
    host.ui = _UI()
    host._enhanced_audio_status = SimpleNamespace(
        selected_mode=EnhancedAudioModeV1.ENHANCED
    )
    host._enhanced_audio_fallback_retained = False
    host._enhanced_audio_fallback_allowed = True
    return host


def test_connect_rejection_latches_exactly_one_next_reconnect_fallback() -> None:
    host = _fallback_host()
    rejection = RuntimeError("1007 Request contains an invalid argument")

    assert host._retain_enhanced_audio_fallback(
        rejection, session_established=False
    ) is True
    assert host._enhanced_audio_fallback_retained is True
    assert host._conn_backoff == 0

    # A second setup rejection cannot arm another fallback or form a loop.
    assert host._retain_enhanced_audio_fallback(
        rejection, session_established=False
    ) is False
    assert len(host.ui.logs) == 1


def test_loop_seam_does_not_downgrade_network_or_mid_session_failure() -> None:
    network_host = _fallback_host()
    assert network_host._retain_enhanced_audio_fallback(
        TimeoutError("connect timed out"), session_established=False
    ) is False
    assert network_host._enhanced_audio_fallback_retained is False

    established_host = _fallback_host()
    assert established_host._retain_enhanced_audio_fallback(
        RuntimeError("1007 Request contains an invalid argument"),
        session_established=True,
    ) is False
    assert established_host._enhanced_audio_fallback_retained is False

    disabled_host = _fallback_host()
    disabled_host._enhanced_audio_fallback_allowed = False
    assert disabled_host._retain_enhanced_audio_fallback(
        RuntimeError("1007 Request contains an invalid argument"),
        session_established=False,
    ) is False
    assert disabled_host._enhanced_audio_fallback_retained is False
