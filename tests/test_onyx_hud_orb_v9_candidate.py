from __future__ import annotations

from pathlib import Path

import pytest

import core.onyx_hud_orb_v9 as candidate


PROJECT = Path(__file__).resolve().parents[1]


def test_v9_is_exactly_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(candidate.FLAG_NAME, raising=False)
    assert candidate.candidate_requested() is False
    monkeypatch.setenv(candidate.FLAG_NAME, "true")
    assert candidate.candidate_requested() is False
    monkeypatch.setenv(candidate.FLAG_NAME, "1")
    assert candidate.candidate_requested() is True


def test_v9_source_removes_only_decorative_arc_canvas() -> None:
    source = (PROJECT / candidate.QML_RELATIVE_PATH).read_text(encoding="utf-8")
    assert "OnyxLiveShellV8" in source
    assert 'objectName: "onyxLiveShellV9Root"' in source
    assert 'findObject(root, "liveCommandInputV7")' in source
    assert "candidate.visible = false" in source
    assert "removed !== 1" in source
    assert "OnyxOrbVoiceLayerV8" not in source


def test_v9_accepted_v8_anchors_are_current() -> None:
    assert candidate._sha256(PROJECT / candidate.V8_MODULE_RELATIVE_PATH) == (
        candidate.V8_MODULE_SHA256
    )
    assert candidate._sha256(PROJECT / candidate.V8_MANIFEST_RELATIVE_PATH) == (
        candidate.V8_MANIFEST_SHA256
    )
