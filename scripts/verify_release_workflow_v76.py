"""Standalone verifier for lifecycle-identity Release V76."""

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

V76 = Path("tests/fixtures/release_workflow_transition_v76.json")
V75 = Path("tests/fixtures/release_workflow_transition_v75.json")
V76_SHA256 = "e36d919cd05671ce537d1774a33e8293f5678ed50be189fc209c48375a5388f5"
V76_ROOT_SHA256 = "80e2fb457fe568860e5ad7993b0fe3a5e1e31ba05d2aae59eb2666b5df3071c8"
V75_SHA256 = "829cb6957786d699aa84f55caf76aed573912e5cde325d8969d5358447d397c6"
V75_ROOT_SHA256 = "08772d477ecb305e45c61f0c7e1e6bc755fed2162465a24c4e83c05beba57dc6"


class ReleaseWorkflowV76Error(RuntimeError):
    pass


def verify_release_workflow_v76(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V76))
    predecessor = _json(_file(root, V75))
    if (
        _sha256(root / V76) != V76_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v76"
        or transition.get("logical_sequence") != 76
        or transition.get("predecessor")
        != {"path": V75.as_posix(), "sha256": V75_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V76_ROOT_SHA256
        or _root(transition, 76) != V76_ROOT_SHA256
    ):
        raise ReleaseWorkflowV76Error("Release V76 contract drifted")
    if (
        _sha256(root / V75) != V75_SHA256
        or predecessor.get("current_root_sha256") != V75_ROOT_SHA256
        or _root(predecessor, 75) != V75_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV76Error("Release V75 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV76Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v76()["transition"]["current_root_sha256"])
