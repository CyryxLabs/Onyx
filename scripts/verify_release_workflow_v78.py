"""Standalone verifier for compositor-continuity Release V78."""

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

V78 = Path("tests/fixtures/release_workflow_transition_v78.json")
V77 = Path("tests/fixtures/release_workflow_transition_v77.json")
V78_SHA256 = "a8b9a4a0e1b9fd4d9361a8f0c18fe42f7852b5b69247c4f7a764593266bd7bc0"
V78_ROOT_SHA256 = "da225596c44d3ea58de72d345e91653d94942c644d49470d9bbed8b6ba87e645"
V77_SHA256 = "97fdd81b2a81c6cfe150a503b52e1dd3008521141252e0601d9d3d38871ef055"
V77_ROOT_SHA256 = "cc447bc44671e6e5082465c610aaf12dfdf88851e3cbc107cd1ee18ab0ebd1f5"


class ReleaseWorkflowV78Error(RuntimeError):
    pass


def verify_release_workflow_v78(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V78))
    predecessor = _json(_file(root, V77))
    if (
        _sha256(root / V78) != V78_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v78"
        or transition.get("logical_sequence") != 78
        or transition.get("predecessor")
        != {"path": V77.as_posix(), "sha256": V77_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V78_ROOT_SHA256
        or _root(transition, 78) != V78_ROOT_SHA256
    ):
        raise ReleaseWorkflowV78Error("Release V78 contract drifted")
    if (
        _sha256(root / V77) != V77_SHA256
        or predecessor.get("current_root_sha256") != V77_ROOT_SHA256
        or _root(predecessor, 77) != V77_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV78Error("Release V77 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV78Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v78()["transition"]["current_root_sha256"])
