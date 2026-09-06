"""Standalone verifier for live-qualification Release V75."""

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

V75 = Path("tests/fixtures/release_workflow_transition_v75.json")
V74 = Path("tests/fixtures/release_workflow_transition_v74.json")
V75_SHA256 = "829cb6957786d699aa84f55caf76aed573912e5cde325d8969d5358447d397c6"
V75_ROOT_SHA256 = "08772d477ecb305e45c61f0c7e1e6bc755fed2162465a24c4e83c05beba57dc6"
V74_SHA256 = "28ee9c94ac978506c1fc0a67bf187188bf51a991208bb7921f184b4588213634"
V74_ROOT_SHA256 = "8760e91d3579eb70cee42734626cf367b43eac153e1446c063d4e1e30e339060"


class ReleaseWorkflowV75Error(RuntimeError):
    pass


def verify_release_workflow_v75(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V75))
    predecessor = _json(_file(root, V74))
    if (
        _sha256(root / V75) != V75_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v75"
        or transition.get("logical_sequence") != 75
        or transition.get("predecessor")
        != {"path": V74.as_posix(), "sha256": V74_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V75_ROOT_SHA256
        or _root(transition, 75) != V75_ROOT_SHA256
    ):
        raise ReleaseWorkflowV75Error("Release V75 contract drifted")
    if (
        _sha256(root / V74) != V74_SHA256
        or predecessor.get("current_root_sha256") != V74_ROOT_SHA256
        or _root(predecessor, 74) != V74_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV75Error("Release V74 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV75Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v75()["transition"]["current_root_sha256"])
