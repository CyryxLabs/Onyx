from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.generate_release_workflow_v58 import CURRENT_CLOSURE_PATHS
from scripts.verify_release_workflow_v58 import ReleaseWorkflowV58Error, verify_release_workflow_v58

ROOT = Path(__file__).resolve().parents[1]


def test_release_v58_authenticates_current_runtime_closure() -> None:
    result = verify_release_workflow_v58(ROOT)
    assert result["transition"]["logical_sequence"] == 58
    paths = {entry["path"] for entry in result["transition"]["current_release_paths"]}
    assert set(CURRENT_CLOSURE_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False


@pytest.mark.parametrize("tamper_predecessor", [False, True])
def test_release_v58_rejects_transition_or_predecessor_tamper(tmp_path: Path, tamper_predecessor: bool) -> None:
    for relative in (Path("tests/fixtures/release_workflow_transition_v57.json"), Path("tests/fixtures/release_workflow_transition_v58.json")):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    relative = Path("tests/fixtures/release_workflow_transition_v57.json" if tamper_predecessor else "tests/fixtures/release_workflow_transition_v58.json")
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(ReleaseWorkflowV58Error, match="contract|predecessor"):
        verify_release_workflow_v58(tmp_path)


def test_release_v58_rejects_linked_transition(tmp_path: Path) -> None:
    transition = tmp_path / "tests/fixtures/release_workflow_transition_v58.json"
    transition.parent.mkdir(parents=True)
    target = transition.with_name("release_workflow_transition_v58-real.json")
    shutil.copy2(ROOT / "tests/fixtures/release_workflow_transition_v58.json", target)
    try:
        transition.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ReleaseWorkflowV58Error, match="contract"):
        verify_release_workflow_v58(tmp_path)
