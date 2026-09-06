"""Standalone verifier for converged release-documentation Release V71."""

from datetime import datetime
from pathlib import Path
from scripts.verify_release_workflow_v70 import (
    POLICY,
    _entries,
    _file,
    _json,
    _root,
    _sha256,
)

PROJECT = Path(__file__).resolve().parents[1]
V71 = Path("tests/fixtures/release_workflow_transition_v71.json")
V70 = Path("tests/fixtures/release_workflow_transition_v70.json")
V71_SHA256 = "cb368372543f2ddb07735a472c3d81dd5cdc87150f07d50a247ef944c326fe38"
V71_ROOT_SHA256 = "f116e6869e562ec2cb9928ce4d6c5ffc4950c64400e38677f9a36e4323a9ba27"
V70_SHA256 = "52d90fdd99a2798307423493320b03cda2338edab6365990d4d212a42c0019d4"
V70_ROOT_SHA256 = "86e6f0f5cbaaffb6940911781c5c11f6c4dd61e6ee86fab3aaa4d59d4da9edf0"


class ReleaseWorkflowV71Error(RuntimeError):
    pass


def verify_release_workflow_v71(project=PROJECT):
    r = Path(project).resolve(strict=True)
    t = _json(_file(r, V71))
    p = _json(_file(r, V70))
    if (
        _sha256(r / V71) != V71_SHA256
        or t.get("schema") != "onyx.release-workflow-transition.v71"
        or t.get("logical_sequence") != 71
        or t.get("predecessor") != {"path": V70.as_posix(), "sha256": V70_SHA256}
        or t.get("policy") != POLICY
        or t.get("current_root_sha256") != V71_ROOT_SHA256
        or _root(t, 71) != V71_ROOT_SHA256
    ):
        raise ReleaseWorkflowV71Error("Release V71 contract drifted")
    if (
        _sha256(r / V70) != V70_SHA256
        or p.get("current_root_sha256") != V70_ROOT_SHA256
        or _root(p, 70) != V70_ROOT_SHA256
        or datetime.fromisoformat(t["issued_at"])
        <= datetime.fromisoformat(p["issued_at"])
    ):
        raise ReleaseWorkflowV71Error("Release V70 predecessor drifted")
    for e in _entries(t):
        if _sha256(_file(r, e["path"])) != e["sha256"]:
            raise ReleaseWorkflowV71Error(
                f"current release target drifted: {e['path']}"
            )
    return {"transition": t, "formal_release_ready": False, "publishable": False}


if __name__ == "__main__":
    print(verify_release_workflow_v71()["transition"]["current_root_sha256"])
