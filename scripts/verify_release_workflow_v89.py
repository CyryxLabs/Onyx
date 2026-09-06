"""Standalone verifier for packaged-runtime Release V89."""

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

V89 = Path("tests/fixtures/release_workflow_transition_v89.json")
V88 = Path("tests/fixtures/release_workflow_transition_v88.json")
V89_SHA256 = "6b1a836ace325a19a2dee7f3b35f5a46120ca4633edba6dc4e65bd868bbd1d1e"
V89_ROOT_SHA256 = "05ab623def30efe12a764595e901f12a797679e7fe25d774dd4b7969d1076031"
V88_SHA256 = "cedda687e8f5eee6a6cb355f5f3975afe8f44035751bb5203aba0f8ce36b353f"
V88_ROOT_SHA256 = "fc2c506c490e6120ee80d710d321e5fdc8d080394c51f8ce70e97f4a1c615ec9"


class ReleaseWorkflowV89Error(RuntimeError):
    pass


def verify_release_workflow_v89(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V89))
    predecessor = _json(_file(root, V88))
    if (
        _sha256(root / V89) != V89_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v89"
        or transition.get("logical_sequence") != 89
        or transition.get("predecessor")
        != {"path": V88.as_posix(), "sha256": V88_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V89_ROOT_SHA256
        or _root(transition, 89) != V89_ROOT_SHA256
    ):
        raise ReleaseWorkflowV89Error("Release V89 contract drifted")
    if (
        _sha256(root / V88) != V88_SHA256
        or predecessor.get("current_root_sha256") != V88_ROOT_SHA256
        or _root(predecessor, 88) != V88_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV89Error("Release V88 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV89Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v89()["transition"]["current_root_sha256"])
