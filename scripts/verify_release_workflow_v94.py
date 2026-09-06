"""Standalone verifier for installed-live-lifecycle Release V94."""

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

V94 = Path("tests/fixtures/release_workflow_transition_v94.json")
V93 = Path("tests/fixtures/release_workflow_transition_v93.json")
V94_SHA256 = "2fa11978b0b19228603b6593928e94d7daf5e5bd31634bcd1d90d5c790ad8b6b"
V94_ROOT_SHA256 = "b5ba8c39fb9b5b23a6290e102e8bd88a6a5201b40c3b9c9b61654b944991ffe1"
V93_SHA256 = "6f8883f724c574e4f1a47266bd905a7a35383db17b81b6cfe22b53ae3e0fe813"
V93_ROOT_SHA256 = "1527be5e4b65e5756cc82788230abc5f21431b7d693a6368c31aac9ce96c4d42"


class ReleaseWorkflowV94Error(RuntimeError):
    pass


def verify_release_workflow_v94(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V94))
    predecessor = _json(_file(root, V93))
    if (
        _sha256(root / V94) != V94_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v94"
        or transition.get("logical_sequence") != 94
        or transition.get("predecessor")
        != {"path": V93.as_posix(), "sha256": V93_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V94_ROOT_SHA256
        or _root(transition, 94) != V94_ROOT_SHA256
    ):
        raise ReleaseWorkflowV94Error("Release V94 contract drifted")
    if (
        _sha256(root / V93) != V93_SHA256
        or predecessor.get("current_root_sha256") != V93_ROOT_SHA256
        or _root(predecessor, 93) != V93_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV94Error("Release V93 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV94Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v94()["transition"]["current_root_sha256"])
