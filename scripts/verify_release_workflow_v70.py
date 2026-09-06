"""Standalone verifier for converged V48 freezer Release V70."""

from datetime import datetime
from pathlib import Path

from scripts.verify_release_workflow_v69 import (
    POLICY,
    _entries,
    _file,
    _json,
    _root,
    _sha256,
)

PROJECT = Path(__file__).resolve().parents[1]
V70 = Path("tests/fixtures/release_workflow_transition_v70.json")
V69 = Path("tests/fixtures/release_workflow_transition_v69.json")
V70_SHA256 = "52d90fdd99a2798307423493320b03cda2338edab6365990d4d212a42c0019d4"
V70_ROOT_SHA256 = "86e6f0f5cbaaffb6940911781c5c11f6c4dd61e6ee86fab3aaa4d59d4da9edf0"
V69_SHA256 = "2988ec0b934ebbe356f623c964dc6278002c9899e8b186eca6470c0c7084643c"
V69_ROOT_SHA256 = "ed3f52629cc035358782784cf3e99f266fbf80737dbde7e39b6eb7fed0a0513a"


class ReleaseWorkflowV70Error(RuntimeError):
    pass


def verify_release_workflow_v70(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V70))
    predecessor = _json(_file(root, V69))
    if (
        _sha256(root / V70) != V70_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v70"
        or transition.get("logical_sequence") != 70
        or transition.get("predecessor")
        != {"path": V69.as_posix(), "sha256": V69_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V70_ROOT_SHA256
        or _root(transition, 70) != V70_ROOT_SHA256
    ):
        raise ReleaseWorkflowV70Error("Release V70 contract drifted")
    if (
        _sha256(root / V69) != V69_SHA256
        or predecessor.get("current_root_sha256") != V69_ROOT_SHA256
        or _root(predecessor, 69) != V69_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV70Error("Release V69 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV70Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v70()["transition"]["current_root_sha256"])
