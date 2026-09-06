"""Transcript-free persistent spoken-language preference for Onyx.

Only a language code, confidence, evidence count, and timestamp are persisted.
Raw text is never stored. Detection is deliberately conservative: uncertain
Latin-script text stays uncommitted while distinctive scripts can commit from a
single strong observation.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

SCHEMA: Final = "onyx.spoken-language-memory/v1"
MAX_TEXT_CHARS: Final = 4_000
SUPPORTED_LANGUAGES: Final = frozenset(
    {"ar", "de", "en", "es", "fr", "it", "ja", "ko", "pt", "ru", "zh"}
)
_LANGUAGE_NAMES: Final = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
    "ru": "Russian",
    "zh": "Chinese",
}
_MARKERS: Final = {
    "pt": frozenset({"agora", "ainda", "como", "estou", "isso", "meu", "minha", "nao", "não", "para", "preciso", "quero", "voce", "você"}),
    "en": frozenset({"and", "can", "hello", "how", "is", "please", "that", "the", "this", "what", "with", "you"}),
    "es": frozenset({"ahora", "como", "cómo", "esto", "hola", "para", "por", "puedes", "quiero", "que", "una", "usted"}),
    "fr": frozenset({"avec", "bonjour", "ceci", "comment", "est", "je", "pour", "que", "une", "vous"}),
    "de": frozenset({"aber", "bitte", "das", "der", "die", "ein", "hallo", "ich", "ist", "mit", "und", "wie"}),
    "it": frozenset({"adesso", "che", "ciao", "come", "con", "io", "per", "questo", "sono", "una"}),
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


class SpokenLanguageMemoryError(ValueError):
    """The language-memory contract was violated."""


@dataclass(frozen=True, slots=True)
class LanguageObservationV1:
    language: str | None
    confidence: float
    strong_script: bool = False


@dataclass(frozen=True, slots=True)
class SpokenLanguageStateV1:
    language: str | None = None
    confidence: float = 0.0
    evidence_count: int = 0
    source: str = "unconfirmed"
    updated_at_ns: int = 0

    @property
    def confirmed(self) -> bool:
        return self.language in SUPPORTED_LANGUAGES and self.source in {
            "automatic",
            "owner-confirmed",
        }


def _script_observation(text: str) -> LanguageObservationV1 | None:
    counts = {"ar": 0, "ja": 0, "ko": 0, "ru": 0, "zh": 0}
    for character in text:
        code = ord(character)
        name = unicodedata.name(character, "")
        if "ARABIC" in name:
            counts["ar"] += 1
        elif "HIRAGANA" in name or "KATAKANA" in name:
            counts["ja"] += 1
        elif "HANGUL" in name:
            counts["ko"] += 1
        elif "CYRILLIC" in name:
            counts["ru"] += 1
        elif 0x4E00 <= code <= 0x9FFF:
            counts["zh"] += 1
    language, count = max(counts.items(), key=lambda item: item[1])
    if count < 3:
        return None
    visible = max(1, sum(not character.isspace() for character in text))
    return LanguageObservationV1(language, min(0.99, count / visible + 0.45), True)


def detect_spoken_language_v1(text: object) -> LanguageObservationV1:
    if type(text) is not str:
        raise SpokenLanguageMemoryError("transcript must be text")
    normalized = unicodedata.normalize("NFC", text).strip()[:MAX_TEXT_CHARS]
    if not normalized:
        return LanguageObservationV1(None, 0.0)
    scripted = _script_observation(normalized)
    if scripted is not None:
        return scripted
    words = [word.casefold() for word in _WORD.findall(normalized)]
    if len(words) < 3:
        return LanguageObservationV1(None, 0.0)
    scores = {
        language: sum(word in markers for word in words)
        for language, markers in _MARKERS.items()
    }
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    language, score = ordered[0]
    runner_up = ordered[1][1]
    if score < 2 or score == runner_up:
        return LanguageObservationV1(None, 0.0)
    confidence = min(0.95, 0.45 + (score / max(4, len(words))) + (score - runner_up) * 0.08)
    return LanguageObservationV1(language, confidence)


class SpokenLanguageMemoryV1:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._pending_language: str | None = None
        self._pending_count = 0

    def _read(self) -> SpokenLanguageStateV1:
        if not self.path.exists():
            return SpokenLanguageStateV1()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.pop("schema", None) != SCHEMA or set(raw) != {
                "language", "confidence", "evidence_count", "source", "updated_at_ns"
            }:
                raise ValueError
            state = SpokenLanguageStateV1(**raw)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SpokenLanguageMemoryError("language memory is malformed") from exc
        if state.language not in SUPPORTED_LANGUAGES or not state.confirmed:
            raise SpokenLanguageMemoryError("language memory is malformed")
        return state

    def _write(self, state: SpokenLanguageStateV1) -> SpokenLanguageStateV1:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": SCHEMA, **asdict(state)}
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return state

    def status(self) -> SpokenLanguageStateV1:
        return self._read()

    def observe(self, transcript: object) -> SpokenLanguageStateV1:
        current = self._read()
        if current.source == "owner-confirmed":
            return current
        observation = detect_spoken_language_v1(transcript)
        if observation.language is None or observation.confidence < 0.65:
            return current
        if observation.language == self._pending_language:
            self._pending_count += 1
        else:
            self._pending_language = observation.language
            self._pending_count = 1
        threshold = 1 if observation.strong_script and observation.confidence >= 0.75 else 2
        if self._pending_count < threshold:
            return current
        return self._write(SpokenLanguageStateV1(
            language=observation.language,
            confidence=observation.confidence,
            evidence_count=self._pending_count,
            source="automatic",
            updated_at_ns=time.time_ns(),
        ))

    def set_owner_language(self, language: str) -> SpokenLanguageStateV1:
        normalized = str(language).strip().casefold()
        if normalized not in SUPPORTED_LANGUAGES:
            raise SpokenLanguageMemoryError("unsupported language")
        self._pending_language = None
        self._pending_count = 0
        return self._write(SpokenLanguageStateV1(
            language=normalized,
            confidence=1.0,
            evidence_count=1,
            source="owner-confirmed",
            updated_at_ns=time.time_ns(),
        ))

    def revoke(self) -> SpokenLanguageStateV1:
        self.path.unlink(missing_ok=True)
        self._pending_language = None
        self._pending_count = 0
        return SpokenLanguageStateV1()

    def prompt_instruction(self) -> str:
        state = self._read()
        if not state.confirmed or state.language is None:
            return ""
        return (
            "[OWNER LANGUAGE — LOCAL CONFIRMED PREFERENCE]\n"
            f"Respond naturally in {_LANGUAGE_NAMES[state.language]} unless the owner explicitly asks for another language. "
            "This preference changes language only; it grants no authority and does not change Onyx voice identity.\n"
        )


__all__ = [
    "LanguageObservationV1",
    "SpokenLanguageMemoryError",
    "SpokenLanguageMemoryV1",
    "SpokenLanguageStateV1",
    "SUPPORTED_LANGUAGES",
    "detect_spoken_language_v1",
]
