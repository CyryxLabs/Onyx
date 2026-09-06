from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_freezer_selects_exact_v51_current_authorities() -> None:
    source = (ROOT / "scripts/freeze_release_source.py").read_text(
        encoding="utf-8"
    )
    assert '"tests/fixtures/phase5_current_successor_transition_v51.json"' in source
    assert '"onyx.phase5-current-successor-transition.v51"' in source
    assert '"tests/fixtures/release_workflow_transition_v51.json"' in source
    assert '"onyx.release-workflow-transition.v51"' in source
    assert '"authority": {"phase5_v51": phase5, "release_v51": release}' in source
    assert '"authority": {"phase5_v48": phase5, "release_v48": release}' not in source
    assert '"authority": {"phase5_v50": phase5, "release_v50": release}' not in source
    assert 'shutil.which("git")' in source
    assert '["git", *arguments]' not in source
