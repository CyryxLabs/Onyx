"""Standalone verifier for atomic-interrupt Release V85."""

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

V85 = Path("tests/fixtures/release_workflow_transition_v85.json")
V84 = Path("tests/fixtures/release_workflow_transition_v84.json")
V85_SHA256 = "891e63d0872eb033d620c9f5447ed863f6393995f37a5799c8b2d1c04296ed11"
V85_ROOT_SHA256 = "2fe88ddc8d109d6979f32be20d23aa4f101dfb16853dec4f38a087f2d24848ec"
V84_SHA256 = "40e32d1a77f547e6f98aa398bf57a05497d7ecbf18b7b9336e24135fa48d8532"
V84_ROOT_SHA256 = "5e7abe939291dca8cd1d6ba6ed1bdddd4291e634103f8e48c8a1d45393c7c2b2"


class ReleaseWorkflowV85Error(RuntimeError):
    pass


def verify_release_workflow_v85(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V85))
    predecessor = _json(_file(root, V84))
    if (
        _sha256(root / V85) != V85_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v85"
        or transition.get("logical_sequence") != 85
        or transition.get("predecessor")
        != {"path": V84.as_posix(), "sha256": V84_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V85_ROOT_SHA256
        or _root(transition, 85) != V85_ROOT_SHA256
    ):
        raise ReleaseWorkflowV85Error("Release V85 contract drifted")
    if (
        _sha256(root / V84) != V84_SHA256
        or predecessor.get("current_root_sha256") != V84_ROOT_SHA256
        or _root(predecessor, 84) != V84_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV85Error("Release V84 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV85Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v85()["transition"]["current_root_sha256"])
