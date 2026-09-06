"""Standalone verifier for humanoid render-stability Release V77."""

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

V77 = Path("tests/fixtures/release_workflow_transition_v77.json")
V76 = Path("tests/fixtures/release_workflow_transition_v76.json")
V77_SHA256 = "97fdd81b2a81c6cfe150a503b52e1dd3008521141252e0601d9d3d38871ef055"
V77_ROOT_SHA256 = "cc447bc44671e6e5082465c610aaf12dfdf88851e3cbc107cd1ee18ab0ebd1f5"
V76_SHA256 = "e36d919cd05671ce537d1774a33e8293f5678ed50be189fc209c48375a5388f5"
V76_ROOT_SHA256 = "80e2fb457fe568860e5ad7993b0fe3a5e1e31ba05d2aae59eb2666b5df3071c8"


class ReleaseWorkflowV77Error(RuntimeError):
    pass


def verify_release_workflow_v77(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V77))
    predecessor = _json(_file(root, V76))
    if (
        _sha256(root / V77) != V77_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v77"
        or transition.get("logical_sequence") != 77
        or transition.get("predecessor")
        != {"path": V76.as_posix(), "sha256": V76_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V77_ROOT_SHA256
        or _root(transition, 77) != V77_ROOT_SHA256
    ):
        raise ReleaseWorkflowV77Error("Release V77 contract drifted")
    if (
        _sha256(root / V76) != V76_SHA256
        or predecessor.get("current_root_sha256") != V76_ROOT_SHA256
        or _root(predecessor, 76) != V76_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV77Error("Release V76 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV77Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v77()["transition"]["current_root_sha256"])
