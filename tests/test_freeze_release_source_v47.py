from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_freezer_selects_exact_v47_current_authorities() -> None:
    source = (ROOT / "scripts" / "freeze_release_source.py").read_text(
        encoding="utf-8"
    )
    assert '"tests/fixtures/phase5_current_successor_transition_v47.json"' in source
    assert '"onyx.phase5-current-successor-transition.v47"' in source
    assert '"tests/fixtures/release_workflow_transition_v47.json"' in source
    assert '"onyx.release-workflow-transition.v47"' in source
    assert '"authority": {"phase5_v47": phase5, "release_v47": release}' in source
    assert "phase5_v46" not in source
    assert "release_v46" not in source
