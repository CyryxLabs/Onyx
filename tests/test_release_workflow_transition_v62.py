from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.generate_release_workflow_v62 import CURRENT_CLOSURE_PATHS
from scripts.verify_release_workflow_v62 import (
    ReleaseWorkflowV62Error,
    verify_release_workflow_v62,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_v62_authenticates_current_build_and_retirement_closure() -> None:
    result = verify_release_workflow_v62(ROOT)
    assert result["transition"]["logical_sequence"] == 62
    paths = {entry["path"] for entry in result["transition"]["current_release_paths"]}
    assert set(CURRENT_CLOSURE_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False


@pytest.mark.parametrize("tamper_predecessor", [False, True])
def test_release_v62_rejects_transition_or_predecessor_tamper(
    tmp_path: Path, tamper_predecessor: bool
) -> None:
    for relative in (V61 := Path("tests/fixtures/release_workflow_transition_v61.json"), Path("tests/fixtures/release_workflow_transition_v62.json")):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    relative = V61 if tamper_predecessor else Path("tests/fixtures/release_workflow_transition_v62.json")
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(ReleaseWorkflowV62Error, match="contract|predecessor"):
        verify_release_workflow_v62(tmp_path)
