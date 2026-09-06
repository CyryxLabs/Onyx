"""Standalone verifier for current-upstream parity Release V83."""

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

V83 = Path("tests/fixtures/release_workflow_transition_v83.json")
V82 = Path("tests/fixtures/release_workflow_transition_v82.json")
V83_SHA256 = "cc7f807130d73b0e4a90dfe357e553f9fa959e6fae1939fa64b22577aa30df5e"
V83_ROOT_SHA256 = "b89105abc7f4debc9a325d3c6b529bceaccf0d5ef9193dfc0dc410fac757f677"
V82_SHA256 = "0a34cd398d0af9db6cfbf66af8feb59aa306a2b12aaa34595f0466572cef4c34"
V82_ROOT_SHA256 = "544c38926a8dd0614004271042d7fd4d7158301092a893ce2b4f7792e28ba847"


class ReleaseWorkflowV83Error(RuntimeError):
    pass


def verify_release_workflow_v83(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V83))
    predecessor = _json(_file(root, V82))
    if (
        _sha256(root / V83) != V83_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v83"
        or transition.get("logical_sequence") != 83
        or transition.get("predecessor")
        != {"path": V82.as_posix(), "sha256": V82_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V83_ROOT_SHA256
        or _root(transition, 83) != V83_ROOT_SHA256
    ):
        raise ReleaseWorkflowV83Error("Release V83 contract drifted")
    if (
        _sha256(root / V82) != V82_SHA256
        or predecessor.get("current_root_sha256") != V82_ROOT_SHA256
        or _root(predecessor, 82) != V82_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV83Error("Release V82 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV83Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v83()["transition"]["current_root_sha256"])
