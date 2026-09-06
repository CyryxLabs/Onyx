"""Standalone verifier for bounded successor execution Release V67."""

from datetime import datetime
from pathlib import Path

from scripts.verify_release_workflow_v66 import POLICY, _entries, _file, _json, _root, _sha256

PROJECT = Path(__file__).resolve().parents[1]
V67 = Path("tests/fixtures/release_workflow_transition_v67.json")
V66 = Path("tests/fixtures/release_workflow_transition_v66.json")
V67_SHA256 = "d64ed7dfcdfe612d4ef5fd067847fee3d7c4bd88beb9d77aea0b96feae25ff04"
V67_ROOT_SHA256 = "deadca453f4cd0e13de802c472c7ff29a28ce040c6da53fef1e4fe538884627a"
V66_SHA256 = "0c116b7546bca0686415060567d878364f95540465b3152a0667bee1f369fbc0"
V66_ROOT_SHA256 = "4fb58fae8be24d0ddd87128559cbf96e74946362935089ae2b842fee88172c90"


class ReleaseWorkflowV67Error(RuntimeError):
    pass


def verify_release_workflow_v67(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V67))
    predecessor = _json(_file(root, V66))
    if (_sha256(root / V67) != V67_SHA256 or transition.get("schema") != "onyx.release-workflow-transition.v67" or transition.get("logical_sequence") != 67 or transition.get("predecessor") != {"path": V66.as_posix(), "sha256": V66_SHA256} or transition.get("policy") != POLICY or transition.get("current_root_sha256") != V67_ROOT_SHA256 or _root(transition, 67) != V67_ROOT_SHA256):
        raise ReleaseWorkflowV67Error("Release V67 contract drifted")
    if _sha256(root / V66) != V66_SHA256 or predecessor.get("current_root_sha256") != V66_ROOT_SHA256 or _root(predecessor, 66) != V66_ROOT_SHA256 or datetime.fromisoformat(transition["issued_at"]) <= datetime.fromisoformat(predecessor["issued_at"]):
        raise ReleaseWorkflowV67Error("Release V66 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV67Error(f"current release target drifted: {entry['path']}")
    return {"transition": transition, "formal_release_ready": False, "publishable": False}


if __name__ == "__main__":
    print(verify_release_workflow_v67()["transition"]["current_root_sha256"])
