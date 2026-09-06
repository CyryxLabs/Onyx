"""Standalone verifier for packaged-runtime Release V91."""

from datetime import datetime
from pathlib import Path
import sys


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.verify_release_workflow_v70 import (  # noqa: E402
    POLICY,
    _entries,
    _file,
    _json,
    _root,
    _sha256,
)

V91 = Path("tests/fixtures/release_workflow_transition_v91.json")
V90 = Path("tests/fixtures/release_workflow_transition_v90.json")
V91_SHA256 = "a34fa6a0198182701c0cb06d6e09547ee60f9712160f9de85d8a6e15aa30f0b3"
V91_ROOT_SHA256 = "c6075d470dfe046ab68ff29d7b812d44fc546306ffe3ecbb77a9157b2c8cffeb"
V90_SHA256 = "d0abf73f16ff8e960a3bd6eb868e03877d9d21d2143f0182b6ef5b9041a24df8"
V90_ROOT_SHA256 = "e5ec0f120589941ec7933838420181fd5d51cd5b3c80f4da59c60c826b2615a6"


class ReleaseWorkflowV91Error(RuntimeError):
    pass


def verify_release_workflow_v91(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V91))
    predecessor = _json(_file(root, V90))
    if (
        _sha256(root / V91) != V91_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v91"
        or transition.get("logical_sequence") != 91
        or transition.get("predecessor")
        != {"path": V90.as_posix(), "sha256": V90_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V91_ROOT_SHA256
        or _root(transition, 91) != V91_ROOT_SHA256
    ):
        raise ReleaseWorkflowV91Error("Release V91 contract drifted")
    if (
        _sha256(root / V90) != V90_SHA256
        or predecessor.get("current_root_sha256") != V90_ROOT_SHA256
        or _root(predecessor, 90) != V90_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV91Error("Release V90 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV91Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v91()["transition"]["current_root_sha256"])
