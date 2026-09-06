"""Standalone verifier for stable calibrated-humanoid Release V73."""

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

V73 = Path("tests/fixtures/release_workflow_transition_v73.json")
V72 = Path("tests/fixtures/release_workflow_transition_v72.json")
V73_SHA256 = "fb22c460f153782af60a300cf3973507b54f04946351e5142826c3a98132a7a0"
V73_ROOT_SHA256 = "a584606431e64c8115e1f6fe75690363ffb4e277c04f6aa61c154cc0b3d2f015"
V72_SHA256 = "b8519c0263f609adeb4cba032cf088b6e424cb5cb9a6709ed76ec36b42224137"
V72_ROOT_SHA256 = "d5b30069f05e549db38641ab527a57d9a9b39c246c0dd1bcfb7a9f9db8fc487c"


class ReleaseWorkflowV73Error(RuntimeError):
    pass


def verify_release_workflow_v73(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V73))
    predecessor = _json(_file(root, V72))
    if (
        _sha256(root / V73) != V73_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v73"
        or transition.get("logical_sequence") != 73
        or transition.get("predecessor")
        != {"path": V72.as_posix(), "sha256": V72_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V73_ROOT_SHA256
        or _root(transition, 73) != V73_ROOT_SHA256
    ):
        raise ReleaseWorkflowV73Error("Release V73 contract drifted")
    if (
        _sha256(root / V72) != V72_SHA256
        or predecessor.get("current_root_sha256") != V72_ROOT_SHA256
        or _root(predecessor, 72) != V72_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV73Error("Release V72 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV73Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v73()["transition"]["current_root_sha256"])
