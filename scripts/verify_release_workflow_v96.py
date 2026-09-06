"""Standalone verifier for shortcut/bootstrap recovery Release V96."""

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

V96 = Path("tests/fixtures/release_workflow_transition_v96.json")
V95 = Path("tests/fixtures/release_workflow_transition_v95.json")
V96_SHA256 = "b2bcc08c2638a034144a71516f375b1f537ac992b406d0522fd45ee60ad48966"
V96_ROOT_SHA256 = "3571669ebbbe7c68d09581736ddc4898a47b8bc894feea48f86be56daea28f23"
V95_SHA256 = "63d84c702535998084554d9647dd06178663b60ca5c21fb858ab8058ae3b4b3e"
V95_ROOT_SHA256 = "95862c94357b5713746437275f96789de92206a25c7cf10fe77bf71c1400ce52"


class ReleaseWorkflowV96Error(RuntimeError):
    pass


def verify_release_workflow_v96(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V96))
    predecessor = _json(_file(root, V95))
    if (
        _sha256(root / V96) != V96_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v96"
        or transition.get("logical_sequence") != 96
        or transition.get("predecessor")
        != {"path": V95.as_posix(), "sha256": V95_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V96_ROOT_SHA256
        or _root(transition, 96) != V96_ROOT_SHA256
    ):
        raise ReleaseWorkflowV96Error("Release V96 contract drifted")
    if (
        _sha256(root / V95) != V95_SHA256
        or predecessor.get("current_root_sha256") != V95_ROOT_SHA256
        or _root(predecessor, 95) != V95_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV96Error("Release V95 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV96Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v96()["transition"]["current_root_sha256"])
