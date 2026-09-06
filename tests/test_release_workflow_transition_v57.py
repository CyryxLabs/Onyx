from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from scripts.generate_release_workflow_v57 import CURRENT_CLOSURE_PATHS
from scripts.verify_release_workflow_v57 import (
    ReleaseWorkflowV57Error,
    verify_release_workflow_v57,
)

ROOT = Path(__file__).resolve().parents[1]


def test_release_v57_authenticates_current_runtime_closure() -> None:
    result = verify_release_workflow_v57(ROOT)
    transition = result["transition"]
    assert transition["logical_sequence"] == 57
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert set(CURRENT_CLOSURE_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False


@pytest.mark.parametrize("tamper_predecessor", [False, True])
def test_release_v57_rejects_transition_or_predecessor_tamper(
    tmp_path: Path, tamper_predecessor: bool
) -> None:
    for relative in (
        Path("tests/fixtures/release_workflow_transition_v56.json"),
        Path("tests/fixtures/release_workflow_transition_v57.json"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    relative = Path(
        "tests/fixtures/release_workflow_transition_v56.json"
        if tamper_predecessor
        else "tests/fixtures/release_workflow_transition_v57.json"
    )
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(ReleaseWorkflowV57Error, match="contract|predecessor"):
        verify_release_workflow_v57(tmp_path)


def test_release_v57_preserves_v56_bytes_and_refreshes_current_targets() -> None:
    v56_path = ROOT / "tests/fixtures/release_workflow_transition_v56.json"
    assert hashlib.sha256(v56_path.read_bytes()).hexdigest() == (
        "381ad6b56ae33cd81237e70dc4870c56b966d999574e8dcff298d77aec165bbf"
    )
    v57 = verify_release_workflow_v57(ROOT)["transition"]
    for entry in v57["current_release_paths"]:
        assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry[
            "sha256"
        ]
