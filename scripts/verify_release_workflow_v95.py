"""Standalone verifier for shortcut/bootstrap recovery Release V95."""

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

V95 = Path("tests/fixtures/release_workflow_transition_v95.json")
V94 = Path("tests/fixtures/release_workflow_transition_v94.json")
V95_SHA256 = "63d84c702535998084554d9647dd06178663b60ca5c21fb858ab8058ae3b4b3e"
V95_ROOT_SHA256 = "95862c94357b5713746437275f96789de92206a25c7cf10fe77bf71c1400ce52"
V94_SHA256 = "2fa11978b0b19228603b6593928e94d7daf5e5bd31634bcd1d90d5c790ad8b6b"
V94_ROOT_SHA256 = "b5ba8c39fb9b5b23a6290e102e8bd88a6a5201b40c3b9c9b61654b944991ffe1"


class ReleaseWorkflowV95Error(RuntimeError):
    pass


def verify_release_workflow_v95(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V95))
    predecessor = _json(_file(root, V94))
    if (
        _sha256(root / V95) != V95_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v95"
        or transition.get("logical_sequence") != 95
        or transition.get("predecessor")
        != {"path": V94.as_posix(), "sha256": V94_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V95_ROOT_SHA256
        or _root(transition, 95) != V95_ROOT_SHA256
    ):
        raise ReleaseWorkflowV95Error("Release V95 contract drifted")
    if (
        _sha256(root / V94) != V94_SHA256
        or predecessor.get("current_root_sha256") != V94_ROOT_SHA256
        or _root(predecessor, 94) != V94_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV95Error("Release V94 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV95Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v95()["transition"]["current_root_sha256"])
