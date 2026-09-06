"""Standalone verifier for Mark-LII operational-parity Release V82."""

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

V82 = Path("tests/fixtures/release_workflow_transition_v82.json")
V81 = Path("tests/fixtures/release_workflow_transition_v81.json")
V82_SHA256 = "0a34cd398d0af9db6cfbf66af8feb59aa306a2b12aaa34595f0466572cef4c34"
V82_ROOT_SHA256 = "544c38926a8dd0614004271042d7fd4d7158301092a893ce2b4f7792e28ba847"
V81_SHA256 = "35fcaf2743ed7144ea9bfed5b013230f2815b17d1d8bb361f1d13bcf92437d9e"
V81_ROOT_SHA256 = "35da3d1dc9bde6ca57cf1491b03be2b547b955dc82b9965908d6db47d91feaf5"


class ReleaseWorkflowV82Error(RuntimeError):
    pass


def verify_release_workflow_v82(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V82))
    predecessor = _json(_file(root, V81))
    if (
        _sha256(root / V82) != V82_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v82"
        or transition.get("logical_sequence") != 82
        or transition.get("predecessor")
        != {"path": V81.as_posix(), "sha256": V81_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V82_ROOT_SHA256
        or _root(transition, 82) != V82_ROOT_SHA256
    ):
        raise ReleaseWorkflowV82Error("Release V82 contract drifted")
    if (
        _sha256(root / V81) != V81_SHA256
        or predecessor.get("current_root_sha256") != V81_ROOT_SHA256
        or _root(predecessor, 81) != V81_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV82Error("Release V81 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV82Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v82()["transition"]["current_root_sha256"])
