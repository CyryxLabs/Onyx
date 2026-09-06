from pathlib import Path
import shutil

import pytest

from scripts.verify_release_workflow_v98 import (
    PROJECT, V97, V98, ReleaseWorkflowV98Error, verify_release_workflow_v98,
)


def test_current_source_is_not_public_or_live_certification():
    result = verify_release_workflow_v98()
    assert result["publishable"] is False
    assert result["formal_release_ready"] is False


@pytest.mark.parametrize("changed", [V97, V98, Path("core/live_voice_continuity_v1.py")])
def test_rejects_tampered_predecessor_manifest_and_runtime(tmp_path, changed):
    result = verify_release_workflow_v98()
    paths = {V97, V98, *(Path(row["path"]) for row in result["transition"]["current_release_paths"])}
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / path, target)
    with (tmp_path / changed).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ReleaseWorkflowV98Error):
        verify_release_workflow_v98(tmp_path)
