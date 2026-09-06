"""Standalone verifier for conversational-reliability Release V92."""

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

V92 = Path("tests/fixtures/release_workflow_transition_v92.json")
V91 = Path("tests/fixtures/release_workflow_transition_v91.json")
V92_SHA256 = "cfa4abefee544c09fd5308c5e3f7478a8d3f937b4d50a41c3f99810952deb8b0"
V92_ROOT_SHA256 = "24272197412986d91007df790a3b1f3ea38dc1047f17574f55725b0a61142189"
V91_SHA256 = "a34fa6a0198182701c0cb06d6e09547ee60f9712160f9de85d8a6e15aa30f0b3"
V91_ROOT_SHA256 = "c6075d470dfe046ab68ff29d7b812d44fc546306ffe3ecbb77a9157b2c8cffeb"


class ReleaseWorkflowV92Error(RuntimeError):
    pass


def verify_release_workflow_v92(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V92))
    predecessor = _json(_file(root, V91))
    if (
        _sha256(root / V92) != V92_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v92"
        or transition.get("logical_sequence") != 92
        or transition.get("predecessor")
        != {"path": V91.as_posix(), "sha256": V91_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V92_ROOT_SHA256
        or _root(transition, 92) != V92_ROOT_SHA256
    ):
        raise ReleaseWorkflowV92Error("Release V92 contract drifted")
    if (
        _sha256(root / V91) != V91_SHA256
        or predecessor.get("current_root_sha256") != V91_ROOT_SHA256
        or _root(predecessor, 91) != V91_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV92Error("Release V91 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV92Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v92()["transition"]["current_root_sha256"])
