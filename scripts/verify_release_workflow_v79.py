"""Standalone verifier for startup trust-boundary Release V79."""

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

V79 = Path("tests/fixtures/release_workflow_transition_v79.json")
V78 = Path("tests/fixtures/release_workflow_transition_v78.json")
V79_SHA256 = "7d576995c3a33ed731b6eb5c532b5d52d0fb77fee9c495f48ebb36fb5482f546"
V79_ROOT_SHA256 = "5a10c94a7fcedea0540f650ffc893d20019d0c993da09343d102f5a9518a41d7"
V78_SHA256 = "a8b9a4a0e1b9fd4d9361a8f0c18fe42f7852b5b69247c4f7a764593266bd7bc0"
V78_ROOT_SHA256 = "da225596c44d3ea58de72d345e91653d94942c644d49470d9bbed8b6ba87e645"


class ReleaseWorkflowV79Error(RuntimeError):
    pass


def verify_release_workflow_v79(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V79))
    predecessor = _json(_file(root, V78))
    if (
        _sha256(root / V79) != V79_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v79"
        or transition.get("logical_sequence") != 79
        or transition.get("predecessor")
        != {"path": V78.as_posix(), "sha256": V78_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V79_ROOT_SHA256
        or _root(transition, 79) != V79_ROOT_SHA256
    ):
        raise ReleaseWorkflowV79Error("Release V79 contract drifted")
    if (
        _sha256(root / V78) != V78_SHA256
        or predecessor.get("current_root_sha256") != V78_ROOT_SHA256
        or _root(predecessor, 78) != V78_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV79Error("Release V78 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV79Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v79()["transition"]["current_root_sha256"])
