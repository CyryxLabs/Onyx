"""Standalone verifier for installed-runtime-recovery Release V93."""

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

V93 = Path("tests/fixtures/release_workflow_transition_v93.json")
V92 = Path("tests/fixtures/release_workflow_transition_v92.json")
V93_SHA256 = "6f8883f724c574e4f1a47266bd905a7a35383db17b81b6cfe22b53ae3e0fe813"
V93_ROOT_SHA256 = "1527be5e4b65e5756cc82788230abc5f21431b7d693a6368c31aac9ce96c4d42"
V92_SHA256 = "cfa4abefee544c09fd5308c5e3f7478a8d3f937b4d50a41c3f99810952deb8b0"
V92_ROOT_SHA256 = "24272197412986d91007df790a3b1f3ea38dc1047f17574f55725b0a61142189"


class ReleaseWorkflowV93Error(RuntimeError):
    pass


def verify_release_workflow_v93(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V93))
    predecessor = _json(_file(root, V92))
    if (
        _sha256(root / V93) != V93_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v93"
        or transition.get("logical_sequence") != 93
        or transition.get("predecessor")
        != {"path": V92.as_posix(), "sha256": V92_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V93_ROOT_SHA256
        or _root(transition, 93) != V93_ROOT_SHA256
    ):
        raise ReleaseWorkflowV93Error("Release V93 contract drifted")
    if (
        _sha256(root / V92) != V92_SHA256
        or predecessor.get("current_root_sha256") != V92_ROOT_SHA256
        or _root(predecessor, 92) != V92_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV93Error("Release V92 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV93Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v93()["transition"]["current_root_sha256"])
