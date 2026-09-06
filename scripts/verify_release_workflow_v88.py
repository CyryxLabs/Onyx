"""Standalone verifier for bundled-agentic Release V88."""

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

V88 = Path("tests/fixtures/release_workflow_transition_v88.json")
V87 = Path("tests/fixtures/release_workflow_transition_v87.json")
V88_SHA256 = "cedda687e8f5eee6a6cb355f5f3975afe8f44035751bb5203aba0f8ce36b353f"
V88_ROOT_SHA256 = "fc2c506c490e6120ee80d710d321e5fdc8d080394c51f8ce70e97f4a1c615ec9"
V87_SHA256 = "10b5c27e5c214cd962caff58db8469f2b92000f1fc5a0223f477c19a81290376"
V87_ROOT_SHA256 = "d3fcc72fa3b97ec433fd2bb9d71d3df44090c2144e524be54b2c2ac063c9f5d1"


class ReleaseWorkflowV88Error(RuntimeError):
    pass


def verify_release_workflow_v88(project=PROJECT):
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V88))
    predecessor = _json(_file(root, V87))
    if (
        _sha256(root / V88) != V88_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v88"
        or transition.get("logical_sequence") != 88
        or transition.get("predecessor")
        != {"path": V87.as_posix(), "sha256": V87_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V88_ROOT_SHA256
        or _root(transition, 88) != V88_ROOT_SHA256
    ):
        raise ReleaseWorkflowV88Error("Release V88 contract drifted")
    if (
        _sha256(root / V87) != V87_SHA256
        or predecessor.get("current_root_sha256") != V87_ROOT_SHA256
        or _root(predecessor, 87) != V87_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV88Error("Release V87 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV88Error(
                f"current release target drifted: {entry['path']}"
            )
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    print(verify_release_workflow_v88()["transition"]["current_root_sha256"])
