"""Standalone verifier for packaged-runtime Release V90."""

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

V90 = Path("tests/fixtures/release_workflow_transition_v90.json")
V89 = Path("tests/fixtures/release_workflow_transition_v89.json")
V90_SHA256 = "d0abf73f16ff8e960a3bd6eb868e03877d9d21d2143f0182b6ef5b9041a24df8"
V90_ROOT_SHA256 = "e5ec0f120589941ec7933838420181fd5d51cd5b3c80f4da59c60c826b2615a6"
V89_SHA256 = "6b1a836ace325a19a2dee7f3b35f5a46120ca4633edba6dc4e65bd868bbd1d1e"
V89_ROOT_SHA256 = "05ab623def30efe12a764595e901f12a797679e7fe25d774dd4b7969d1076031"


class ReleaseWorkflowV90Error(RuntimeError):
    pass


def verify_release_workflow_v90(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V90))
    predecessor = _json(_file(root, V89))
    if (
        _sha256(root / V90) != V90_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v90"
        or transition.get("logical_sequence") != 90
        or transition.get("predecessor")
        != {"path": V89.as_posix(), "sha256": V89_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V90_ROOT_SHA256
        or _root(transition, 90) != V90_ROOT_SHA256
    ):
        raise ReleaseWorkflowV90Error("Release V90 contract drifted")
    if (
        _sha256(root / V89) != V89_SHA256
        or predecessor.get("current_root_sha256") != V89_ROOT_SHA256
        or _root(predecessor, 89) != V89_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV90Error("Release V89 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV90Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v90()["transition"]["current_root_sha256"])
