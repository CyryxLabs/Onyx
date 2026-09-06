from __future__ import annotations

import json

from core.spoken_language_memory_v1 import (
    SpokenLanguageMemoryV1,
    detect_spoken_language_v1,
)


def test_language_detection_requires_repeated_latin_evidence_and_retains_no_text(tmp_path):
    path = tmp_path / "language.json"
    memory = SpokenLanguageMemoryV1(path)
    transcript = "Quero que voce explique isso agora para mim"
    assert memory.observe(transcript).confirmed is False
    state = memory.observe(transcript)
    assert state.language == "pt"
    assert state.source == "automatic"
    persisted = path.read_text(encoding="utf-8")
    assert transcript not in persisted
    assert set(json.loads(persisted)) == {
        "schema", "language", "confidence", "evidence_count", "source", "updated_at_ns"
    }


def test_strong_script_commits_once_and_manual_override_is_sticky(tmp_path):
    memory = SpokenLanguageMemoryV1(tmp_path / "language.json")
    assert memory.observe("こんにちは、今日は元気ですか").language == "ja"
    assert memory.set_owner_language("en").source == "owner-confirmed"
    assert memory.observe("Quero que voce explique isso agora").language == "en"
    assert "English" in memory.prompt_instruction()
    assert memory.revoke().confirmed is False


def test_short_or_ambiguous_text_is_not_guessed():
    assert detect_spoken_language_v1("hello").language is None
    assert detect_spoken_language_v1("como para este").language is None
