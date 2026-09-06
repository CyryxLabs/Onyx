from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_freezer_selects_exact_v48_current_authorities() -> None:
    source = (ROOT / "scripts/freeze_release_source.py").read_text(
        encoding="utf-8"
    )
    assert '"tests/fixtures/phase5_current_successor_transition_v48.json"' in source
    assert '"onyx.phase5-current-successor-transition.v48"' in source
    assert '"tests/fixtures/release_workflow_transition_v48.json"' in source
    assert '"onyx.release-workflow-transition.v48"' in source
    assert '"authority": {"phase5_v48": phase5, "release_v48": release}' in source
