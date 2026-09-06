"""Standalone verifier for governed continuous-intelligence Release V87."""

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

V87 = Path("tests/fixtures/release_workflow_transition_v87.json")
V86 = Path("tests/fixtures/release_workflow_transition_v86.json")
V87_SHA256 = "10b5c27e5c214cd962caff58db8469f2b92000f1fc5a0223f477c19a81290376"
V87_ROOT_SHA256 = "d3fcc72fa3b97ec433fd2bb9d71d3df44090c2144e524be54b2c2ac063c9f5d1"
V86_SHA256 = "18bf445b1e40d213efaa46f82a16d48f8838c7b6702fc2efbbc0284ef6a2c5ed"
V86_ROOT_SHA256 = "3d9bc9e2a95670e4a57fb80e245f16f00a9a3b396c560b9b12afb2a372277af3"


class ReleaseWorkflowV87Error(RuntimeError):
    pass


def verify_release_workflow_v87(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V87))
    predecessor = _json(_file(root, V86))
    if (
        _sha256(root / V87) != V87_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v87"
        or transition.get("logical_sequence") != 87
        or transition.get("predecessor")
        != {"path": V86.as_posix(), "sha256": V86_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V87_ROOT_SHA256
        or _root(transition, 87) != V87_ROOT_SHA256
    ):
        raise ReleaseWorkflowV87Error("Release V87 contract drifted")
    if (
        _sha256(root / V86) != V86_SHA256
        or predecessor.get("current_root_sha256") != V86_ROOT_SHA256
        or _root(predecessor, 86) != V86_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV87Error("Release V86 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV87Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v87()["transition"]["current_root_sha256"])
