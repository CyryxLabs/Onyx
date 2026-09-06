"""Standalone verifier for converged Phase 5 Release V69."""

from datetime import datetime
from pathlib import Path

from scripts.verify_release_workflow_v68 import (
    POLICY,
    _entries,
    _file,
    _json,
    _root,
    _sha256,
)

PROJECT = Path(__file__).resolve().parents[1]
V69 = Path("tests/fixtures/release_workflow_transition_v69.json")
V68 = Path("tests/fixtures/release_workflow_transition_v68.json")
V69_SHA256 = "2988ec0b934ebbe356f623c964dc6278002c9899e8b186eca6470c0c7084643c"
V69_ROOT_SHA256 = "ed3f52629cc035358782784cf3e99f266fbf80737dbde7e39b6eb7fed0a0513a"
V68_SHA256 = "0332a2ba7ea4123dac6f210cd21a5db490fd79ba52a1c334614a322e2338efe3"
V68_ROOT_SHA256 = "ccd6050dbe125451758d3d16e522ab50027ec79952185814222110da736643a6"


class ReleaseWorkflowV69Error(RuntimeError):
    pass


def verify_release_workflow_v69(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V69))
    predecessor = _json(_file(root, V68))
    if (
        _sha256(root / V69) != V69_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v69"
        or transition.get("logical_sequence") != 69
        or transition.get("predecessor")
        != {"path": V68.as_posix(), "sha256": V68_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V69_ROOT_SHA256
        or _root(transition, 69) != V69_ROOT_SHA256
    ):
        raise ReleaseWorkflowV69Error("Release V69 contract drifted")
    if (
        _sha256(root / V68) != V68_SHA256
        or predecessor.get("current_root_sha256") != V68_ROOT_SHA256
        or _root(predecessor, 68) != V68_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV69Error("Release V68 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV69Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v69()["transition"]["current_root_sha256"])
