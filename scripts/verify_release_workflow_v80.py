"""Standalone verifier for governed-shutdown recovery Release V80."""

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

V80 = Path("tests/fixtures/release_workflow_transition_v80.json")
V79 = Path("tests/fixtures/release_workflow_transition_v79.json")
V80_SHA256 = "35bdfed6a1999291897b63a921c6653991da9e3dee75efc73b51ee4ae48e96ce"
V80_ROOT_SHA256 = "6f1abd1bf52e3a0eaa7272987d0b4427339b6e840ef7aa4336731300664ef55f"
V79_SHA256 = "7d576995c3a33ed731b6eb5c532b5d52d0fb77fee9c495f48ebb36fb5482f546"
V79_ROOT_SHA256 = "5a10c94a7fcedea0540f650ffc893d20019d0c993da09343d102f5a9518a41d7"


class ReleaseWorkflowV80Error(RuntimeError):
    pass


def verify_release_workflow_v80(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V80))
    predecessor = _json(_file(root, V79))
    if (
        _sha256(root / V80) != V80_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v80"
        or transition.get("logical_sequence") != 80
        or transition.get("predecessor")
        != {"path": V79.as_posix(), "sha256": V79_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V80_ROOT_SHA256
        or _root(transition, 80) != V80_ROOT_SHA256
    ):
        raise ReleaseWorkflowV80Error("Release V80 contract drifted")
    if (
        _sha256(root / V79) != V79_SHA256
        or predecessor.get("current_root_sha256") != V79_ROOT_SHA256
        or _root(predecessor, 79) != V79_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV80Error("Release V79 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV80Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v80()["transition"]["current_root_sha256"])
