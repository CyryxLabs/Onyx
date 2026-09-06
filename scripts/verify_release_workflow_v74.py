"""Standalone verifier for packaged-parity Release V74."""

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

V74 = Path("tests/fixtures/release_workflow_transition_v74.json")
V73 = Path("tests/fixtures/release_workflow_transition_v73.json")
V74_SHA256 = "28ee9c94ac978506c1fc0a67bf187188bf51a991208bb7921f184b4588213634"
V74_ROOT_SHA256 = "8760e91d3579eb70cee42734626cf367b43eac153e1446c063d4e1e30e339060"
V73_SHA256 = "fb22c460f153782af60a300cf3973507b54f04946351e5142826c3a98132a7a0"
V73_ROOT_SHA256 = "a584606431e64c8115e1f6fe75690363ffb4e277c04f6aa61c154cc0b3d2f015"


class ReleaseWorkflowV74Error(RuntimeError):
    pass


def verify_release_workflow_v74(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V74))
    predecessor = _json(_file(root, V73))
    if (
        _sha256(root / V74) != V74_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v74"
        or transition.get("logical_sequence") != 74
        or transition.get("predecessor")
        != {"path": V73.as_posix(), "sha256": V73_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V74_ROOT_SHA256
        or _root(transition, 74) != V74_ROOT_SHA256
    ):
        raise ReleaseWorkflowV74Error("Release V74 contract drifted")
    if (
        _sha256(root / V73) != V73_SHA256
        or predecessor.get("current_root_sha256") != V73_ROOT_SHA256
        or _root(predecessor, 73) != V73_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV74Error("Release V73 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV74Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v74()["transition"]["current_root_sha256"])
