"""V101 SOURCE authority verifier; rejects unsealed pins and source drift.

V100 is immutable predecessor evidence, not a live-source gate after authorized
successor edits. No fabricated pins or publication/installation authority.
"""

from datetime import datetime
from pathlib import Path
import re

from scripts.verify_release_workflow_v70 import POLICY, _entries, _file, _json, _root, _sha256
from scripts.verify_release_workflow_v100 import V100, V100_ROOT_SHA256, V100_SHA256

PROJECT = Path(__file__).resolve().parents[1]
V101 = Path("tests/fixtures/release_workflow_transition_v101.json")
V101_SHA256 = "f0a93e50d4ef85b19a7292786335b99dce22bd8e8f07bc8759d608323d00ef26"
V101_ROOT_SHA256 = "040f3f09334e56c8080650028c19396f4368c439007af55357a3b34ce117a396"


class ReleaseWorkflowV101Error(RuntimeError):
    """V101 is unsealed, unavailable, or its source authority has drifted."""


def _verify(project):
    if not all(
        re.fullmatch(r"[0-9a-f]{64}", pin) for pin in (V101_SHA256, V101_ROOT_SHA256)
    ):
        raise ReleaseWorkflowV101Error("V101 unsealed: awaiting parent 'seal now' and final pins")
    root = Path(project).resolve(strict=True)
    record = _json(_file(root, V101))
    old = _json(_file(root, V100))
    if (
        _sha256(root / V100) != V100_SHA256
        or old.get("current_root_sha256") != V100_ROOT_SHA256
        or _root(old, 100) != V100_ROOT_SHA256
        or len(_entries(old)) != 687
    ):
        raise ReleaseWorkflowV101Error("V100 predecessor drifted")
    if (
        _sha256(root / V101) != V101_SHA256
        or record.get("schema") != "onyx.release-workflow-transition.v101"
        or record.get("logical_sequence") != 101
        or record.get("predecessor") != {"path": V100.as_posix(), "sha256": V100_SHA256}
        or record.get("policy") != POLICY
        or record.get("current_root_sha256") != V101_ROOT_SHA256
        or _root(record, 101) != V101_ROOT_SHA256
        or datetime.fromisoformat(record["issued_at"]) <= datetime.fromisoformat(old["issued_at"])
    ):
        raise ReleaseWorkflowV101Error("V101 contract drifted or unsealed")
    entries = _entries(record)
    paths = {row["path"] for row in entries}
    required = {
        *(row["path"] for row in _entries(old)),
        *(f"tests/fixtures/release_workflow_transition_v{sequence}.json" for sequence in range(71, 101)),
        "scripts/verify_release_workflow_v100.py",
        "scripts/generate_release_workflow_v101.py",
        "tests/test_release_workflow_transition_v101.py",
    }
    if not required.issubset(paths):
        raise ReleaseWorkflowV101Error("V101 dropped predecessor or historical coverage")
    if {V101.as_posix(), "scripts/verify_release_workflow_v101.py"}.intersection(paths):
        raise ReleaseWorkflowV101Error("V101 contains a circular digest dependency")
    for row in entries:
        if _sha256(_file(root, row["path"])) != row["sha256"]:
            raise ReleaseWorkflowV101Error(f"current release target drifted: {row['path']}")
    return {"transition": record, "publishable": False, "formal_release_ready": False}


def verify_release_workflow_v101(project=PROJECT):
    try:
        return _verify(project)
    except ReleaseWorkflowV101Error:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise ReleaseWorkflowV101Error(f"V101 input unavailable or invalid: {exc}") from exc


if __name__ == "__main__":
    print(verify_release_workflow_v101()["transition"]["current_root_sha256"])
