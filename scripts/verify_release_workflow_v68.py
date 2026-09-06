"""Standalone verifier for current packaged HUD smoke Release V68."""

from datetime import datetime
from pathlib import Path

from scripts.verify_release_workflow_v67 import POLICY, _entries, _file, _json, _root, _sha256

PROJECT = Path(__file__).resolve().parents[1]
V68 = Path("tests/fixtures/release_workflow_transition_v68.json")
V67 = Path("tests/fixtures/release_workflow_transition_v67.json")
V68_SHA256 = "0332a2ba7ea4123dac6f210cd21a5db490fd79ba52a1c334614a322e2338efe3"
V68_ROOT_SHA256 = "ccd6050dbe125451758d3d16e522ab50027ec79952185814222110da736643a6"
V67_SHA256 = "d64ed7dfcdfe612d4ef5fd067847fee3d7c4bd88beb9d77aea0b96feae25ff04"
V67_ROOT_SHA256 = "deadca453f4cd0e13de802c472c7ff29a28ce040c6da53fef1e4fe538884627a"


class ReleaseWorkflowV68Error(RuntimeError):
    pass


def verify_release_workflow_v68(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V68))
    predecessor = _json(_file(root, V67))
    if (_sha256(root / V68) != V68_SHA256 or transition.get("schema") != "onyx.release-workflow-transition.v68" or transition.get("logical_sequence") != 68 or transition.get("predecessor") != {"path": V67.as_posix(), "sha256": V67_SHA256} or transition.get("policy") != POLICY or transition.get("current_root_sha256") != V68_ROOT_SHA256 or _root(transition, 68) != V68_ROOT_SHA256):
        raise ReleaseWorkflowV68Error("Release V68 contract drifted")
    if _sha256(root / V67) != V67_SHA256 or predecessor.get("current_root_sha256") != V67_ROOT_SHA256 or _root(predecessor, 67) != V67_ROOT_SHA256 or datetime.fromisoformat(transition["issued_at"]) <= datetime.fromisoformat(predecessor["issued_at"]):
        raise ReleaseWorkflowV68Error("Release V67 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV68Error(f"current release target drifted: {entry['path']}")
    return {"transition": transition, "formal_release_ready": False, "publishable": False}


if __name__ == "__main__":
    print(verify_release_workflow_v68()["transition"]["current_root_sha256"])
