"""Standalone verifier for voice-selector Release V86."""

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

V86 = Path("tests/fixtures/release_workflow_transition_v86.json")
V85 = Path("tests/fixtures/release_workflow_transition_v85.json")
V86_SHA256 = "18bf445b1e40d213efaa46f82a16d48f8838c7b6702fc2efbbc0284ef6a2c5ed"
V86_ROOT_SHA256 = "3d9bc9e2a95670e4a57fb80e245f16f00a9a3b396c560b9b12afb2a372277af3"
V85_SHA256 = "891e63d0872eb033d620c9f5447ed863f6393995f37a5799c8b2d1c04296ed11"
V85_ROOT_SHA256 = "2fe88ddc8d109d6979f32be20d23aa4f101dfb16853dec4f38a087f2d24848ec"


class ReleaseWorkflowV86Error(RuntimeError):
    pass


def verify_release_workflow_v86(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V86))
    predecessor = _json(_file(root, V85))
    if (
        _sha256(root / V86) != V86_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v86"
        or transition.get("logical_sequence") != 86
        or transition.get("predecessor")
        != {"path": V85.as_posix(), "sha256": V85_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V86_ROOT_SHA256
        or _root(transition, 86) != V86_ROOT_SHA256
    ):
        raise ReleaseWorkflowV86Error("Release V86 contract drifted")
    if (
        _sha256(root / V85) != V85_SHA256
        or predecessor.get("current_root_sha256") != V85_ROOT_SHA256
        or _root(predecessor, 85) != V85_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV86Error("Release V85 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV86Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v86()["transition"]["current_root_sha256"])
