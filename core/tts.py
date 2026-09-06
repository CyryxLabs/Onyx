"""Retired local TTS compatibility boundary.

Onyx production speech is generated only by the active Gemini Live session
with the original voice declared in :mod:`core.audio_contract`.  This module
remains as an import-compatible boundary for old integrations, but it cannot
create or play Edge TTS, Windows/system voices, Kokoro, ElevenLabs, or any
other substitute.  Provider degradation therefore results in silence plus an
explicit HUD diagnostic, never an identity-changing fallback voice.
"""

from __future__ import annotations

from typing import NoReturn


class LocalTTSDisabled(RuntimeError):
    """Local/system speech synthesis is forbidden by the Onyx voice contract."""


def _disabled() -> NoReturn:
    raise LocalTTSDisabled(
        "Onyx local/system TTS is disabled; use the original Gemini Live voice"
    )


class _DisabledEngine:
    """Import-compatible fail-closed base for retired engine names."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        _disabled()

    def speak(self, text: str) -> NoReturn:
        _disabled()


class EdgeTTSEngine(_DisabledEngine):
    pass


class KokoroTTSEngine(_DisabledEngine):
    pass


class ElevenLabsTTSEngine(_DisabledEngine):
    pass


class TTSPlayer(_DisabledEngine):
    @property
    def is_playing(self) -> bool:
        return False

    def stop(self) -> None:
        return None


def create_tts_player(config: dict) -> NoReturn:
    """Refuse every legacy local/system voice configuration."""

    _disabled()


__all__ = [
    "EdgeTTSEngine",
    "ElevenLabsTTSEngine",
    "KokoroTTSEngine",
    "LocalTTSDisabled",
    "TTSPlayer",
    "create_tts_player",
]
