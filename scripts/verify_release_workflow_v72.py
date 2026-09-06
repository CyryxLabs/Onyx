"""Standalone verifier for the humanoid-presence Release V72."""

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

V72 = Path("tests/fixtures/release_workflow_transition_v72.json")
V71 = Path("tests/fixtures/release_workflow_transition_v71.json")
V72_SHA256 = "b8519c0263f609adeb4cba032cf088b6e424cb5cb9a6709ed76ec36b42224137"
V72_ROOT_SHA256 = "d5b30069f05e549db38641ab527a57d9a9b39c246c0dd1bcfb7a9f9db8fc487c"
V71_SHA256 = "cb368372543f2ddb07735a472c3d81dd5cdc87150f07d50a247ef944c326fe38"
V71_ROOT_SHA256 = "f116e6869e562ec2cb9928ce4d6c5ffc4950c64400e38677f9a36e4323a9ba27"


class ReleaseWorkflowV72Error(RuntimeError):
    pass


def verify_release_workflow_v72(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V72))
    predecessor = _json(_file(root, V71))
    if (
        _sha256(root / V72) != V72_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v72"
        or transition.get("logical_sequence") != 72
        or transition.get("predecessor")
        != {"path": V71.as_posix(), "sha256": V71_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V72_ROOT_SHA256
        or _root(transition, 72) != V72_ROOT_SHA256
    ):
        raise ReleaseWorkflowV72Error("Release V72 contract drifted")
    if (
        _sha256(root / V71) != V71_SHA256
        or predecessor.get("current_root_sha256") != V71_ROOT_SHA256
        or _root(predecessor, 71) != V71_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV72Error("Release V71 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV72Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v72()["transition"]["current_root_sha256"])
