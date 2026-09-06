"""Owner-selected Gemini Live voice preference for Onyx."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

VOICES: Final = ("Charon", "Puck", "Kore", "Fenrir", "Aoede")
SCHEMA: Final = "onyx.live-voice-preference/v1"
_COMMAND = re.compile(
    r"^\s*(?:onyx[,;:]?\s*)?(?:use(?: the)? voice|switch to|change (?:your )?voice to|usar(?: a)? voz|mude (?:sua )?voz para)\s+(?P<voice>[a-z]+)\s*$",
    re.IGNORECASE,
)


class LiveVoicePreferenceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LiveVoiceIntentV1:
    matched: bool
    voice: str | None = None


def normalize_voice(value: object) -> str:
    if type(value) is not str:
        raise LiveVoicePreferenceError("voice must be text")
    for voice in VOICES:
        if value.strip().casefold() == voice.casefold():
            return voice
    raise LiveVoicePreferenceError("unsupported Gemini Live voice")


def parse_voice_intent(text: object) -> LiveVoiceIntentV1:
    if type(text) is not str:
        return LiveVoiceIntentV1(False)
    match = _COMMAND.fullmatch(text)
    if match is None:
        return LiveVoiceIntentV1(False)
    try:
        return LiveVoiceIntentV1(True, normalize_voice(match.group("voice")))
    except LiveVoicePreferenceError:
        return LiveVoiceIntentV1(True)


class LiveVoicePreferenceV1:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def get(self) -> str:
        if not self.path.exists():
            return VOICES[0]
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("schema") != SCHEMA:
                raise ValueError
            return normalize_voice(raw.get("voice"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise LiveVoicePreferenceError("voice preference is malformed") from exc

    def set(self, voice: object) -> str:
        selected = normalize_voice(voice)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"schema": SCHEMA, "voice": selected}, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return selected
