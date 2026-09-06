"""Standalone verifier for continuous-audio Release V84."""

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

V84 = Path("tests/fixtures/release_workflow_transition_v84.json")
V83 = Path("tests/fixtures/release_workflow_transition_v83.json")
V84_SHA256 = "40e32d1a77f547e6f98aa398bf57a05497d7ecbf18b7b9336e24135fa48d8532"
V84_ROOT_SHA256 = "5e7abe939291dca8cd1d6ba6ed1bdddd4291e634103f8e48c8a1d45393c7c2b2"
V83_SHA256 = "cc7f807130d73b0e4a90dfe357e553f9fa959e6fae1939fa64b22577aa30df5e"
V83_ROOT_SHA256 = "b89105abc7f4debc9a325d3c6b529bceaccf0d5ef9193dfc0dc410fac757f677"


class ReleaseWorkflowV84Error(RuntimeError):
    pass


def verify_release_workflow_v84(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V84))
    predecessor = _json(_file(root, V83))
    if (
        _sha256(root / V84) != V84_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v84"
        or transition.get("logical_sequence") != 84
        or transition.get("predecessor")
        != {"path": V83.as_posix(), "sha256": V83_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V84_ROOT_SHA256
        or _root(transition, 84) != V84_ROOT_SHA256
    ):
        raise ReleaseWorkflowV84Error("Release V84 contract drifted")
    if (
        _sha256(root / V83) != V83_SHA256
        or predecessor.get("current_root_sha256") != V83_ROOT_SHA256
        or _root(predecessor, 83) != V83_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV84Error("Release V83 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV84Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v84()["transition"]["current_root_sha256"])
