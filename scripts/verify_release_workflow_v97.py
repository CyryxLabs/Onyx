"""V97 current source verifier; V96 remains immutable historical authority."""

from datetime import datetime
from pathlib import Path

from scripts.verify_release_workflow_v70 import POLICY, _entries, _file, _json, _root, _sha256
from scripts.verify_release_workflow_v96 import V96, V96_SHA256, V96_ROOT_SHA256

PROJECT = Path(__file__).resolve().parents[1]
V97 = Path("tests/fixtures/release_workflow_transition_v97.json")
V97_SHA256 = "97230b1beeecd0359b3ea43c874df77687eb3c435dd4616bfa8568d19a7deefc"
V97_ROOT_SHA256 = "c10c6bbde010acab746a48e4f355c72e7125245b64328ec3e4b0dd43fc0e8483"


class ReleaseWorkflowV97Error(RuntimeError):
    pass


def verify_release_workflow_v97(project=PROJECT):
    root = Path(project).resolve(strict=True)
    record = _json(_file(root, V97))
    old = _json(_file(root, V96))
    if (_sha256(root / V96) != V96_SHA256 or _root(old, 96) != V96_ROOT_SHA256):
        raise ReleaseWorkflowV97Error("V96 predecessor drifted")
    if (
        _sha256(root / V97) != V97_SHA256
        or record.get("schema") != "onyx.release-workflow-transition.v97"
        or record.get("logical_sequence") != 97
        or record.get("predecessor") != {"path": V96.as_posix(), "sha256": V96_SHA256}
        or record.get("policy") != POLICY
        or record.get("current_root_sha256") != V97_ROOT_SHA256
        or _root(record, 97) != V97_ROOT_SHA256
        or datetime.fromisoformat(record["issued_at"]) <= datetime.fromisoformat(old["issued_at"])
    ):
        raise ReleaseWorkflowV97Error("V97 contract drifted or unsealed")
    entries = _entries(record)
    if not {row["path"] for row in _entries(old)}.issubset({row["path"] for row in entries}):
        raise ReleaseWorkflowV97Error("V97 dropped predecessor coverage")
    for row in entries:
        if _sha256(_file(root, row["path"])) != row["sha256"]:
            raise ReleaseWorkflowV97Error(f"current release target drifted: {row['path']}")
    return {"transition": record, "publishable": False, "formal_release_ready": False}


if __name__ == "__main__":
    print(verify_release_workflow_v97()["transition"]["current_root_sha256"])
