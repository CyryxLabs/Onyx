"""Standalone verifier for mobile-humanoid and current-test Release V81."""

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

V81 = Path("tests/fixtures/release_workflow_transition_v81.json")
V80 = Path("tests/fixtures/release_workflow_transition_v80.json")
V81_SHA256 = "35fcaf2743ed7144ea9bfed5b013230f2815b17d1d8bb361f1d13bcf92437d9e"
V81_ROOT_SHA256 = "35da3d1dc9bde6ca57cf1491b03be2b547b955dc82b9965908d6db47d91feaf5"
V80_SHA256 = "35bdfed6a1999291897b63a921c6653991da9e3dee75efc73b51ee4ae48e96ce"
V80_ROOT_SHA256 = "6f1abd1bf52e3a0eaa7272987d0b4427339b6e840ef7aa4336731300664ef55f"


class ReleaseWorkflowV81Error(RuntimeError):
    pass


def verify_release_workflow_v81(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V81))
    predecessor = _json(_file(root, V80))
    if (
        _sha256(root / V81) != V81_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v81"
        or transition.get("logical_sequence") != 81
        or transition.get("predecessor")
        != {"path": V80.as_posix(), "sha256": V80_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V81_ROOT_SHA256
        or _root(transition, 81) != V81_ROOT_SHA256
    ):
        raise ReleaseWorkflowV81Error("Release V81 contract drifted")
    if (
        _sha256(root / V80) != V80_SHA256
        or predecessor.get("current_root_sha256") != V80_ROOT_SHA256
        or _root(predecessor, 80) != V80_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV81Error("Release V80 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV81Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v81()["transition"]["current_root_sha256"])
