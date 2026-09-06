from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.audio_contract import (
    LIVE_VOICE,
    LiveSessionRotation,
    ORIGINAL_LIVE_MODEL,
    ORIGINAL_VOICE_STYLE_INSTRUCTION,
    VoiceContractError,
    assert_original_live_voice,
)
from core.installer import install_for_config
from core.tts import (
    EdgeTTSEngine,
    ElevenLabsTTSEngine,
    KokoroTTSEngine,
    LocalTTSDisabled,
    create_tts_player,
)


def _config(*, modalities=("AUDIO",), voice: str = LIVE_VOICE) -> object:
    return SimpleNamespace(
        response_modalities=list(modalities),
        speech_config=SimpleNamespace(
            voice_config=SimpleNamespace(
                prebuilt_voice_config=SimpleNamespace(voice_name=voice)
            )
        ),
    )


def test_original_gemini_live_voice_is_the_only_accepted_output() -> None:
    assert LIVE_VOICE == "Charon"
    assert ORIGINAL_LIVE_MODEL == (
        "models/gemini-2.5-flash-native-audio-preview-12-2025"
    )
    assert_original_live_voice(_config())
    assert "natural native-audio voice" in ORIGINAL_VOICE_STYLE_INSTRUCTION
    assert "operating-system text-to-speech" in ORIGINAL_VOICE_STYLE_INSTRUCTION


def test_live_voice_verifier_builds_the_complete_production_config(tmp_path) -> None:
    code = (
        "import json,sys; from pathlib import Path; "
        "from scripts.verify_original_voice_live import _build_production_config; "
        "c=_build_production_config(state_dir=Path(sys.argv[1])); "
        "print(json.dumps({'modalities': c.response_modalities, "
        "'transcription': c.output_audio_transcription is not None}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        check=True,
        capture_output=True,
        cwd=Path(__file__).parents[1],
        text=True,
        timeout=15,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload == {"modalities": ["AUDIO"], "transcription": True}
    assert not (tmp_path / "assistant-identity-profile-v1.json").exists()
    assert not (tmp_path / "spoken-language-memory-v1.json").exists()


def test_goaway_rotation_is_a_dedicated_non_fallback_signal() -> None:
    assert issubclass(LiveSessionRotation, RuntimeError)
    assert "voice" not in str(LiveSessionRotation("rotate")).casefold()


@pytest.mark.parametrize(
    ("modalities", "voice"),
    [
        ((), LIVE_VOICE),
        (("TEXT",), LIVE_VOICE),
        (("AUDIO", "TEXT"), LIVE_VOICE),
        (("AUDIO",), "Aoede"),
        (("AUDIO",), "en-US-GuyNeural"),
        (("AUDIO",), ""),
    ],
)
def test_voice_contract_fails_closed_without_substitution(
    modalities: tuple[str, ...], voice: str
) -> None:
    with pytest.raises(VoiceContractError):
        assert_original_live_voice(_config(modalities=modalities, voice=voice))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: EdgeTTSEngine(),
        lambda: KokoroTTSEngine(),
        lambda: ElevenLabsTTSEngine("key"),
        lambda: create_tts_player({"tts_engine": "edgetts"}),
    ],
)
def test_all_legacy_tts_entrypoints_are_fail_closed(factory) -> None:
    with pytest.raises(LocalTTSDisabled):
        factory()


@pytest.mark.parametrize("engine", ["edgetts", "kokoro", "elevenlabs", "sapi"])
def test_dependency_installer_rejects_local_or_system_tts(engine: str) -> None:
    with pytest.raises(ValueError, match="Gemini Live only"):
        install_for_config({"tts_engine": engine})
