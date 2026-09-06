"""Unsealed V100 SOURCE draft; final registry closure and parent seal pending.

V99 is immutable predecessor evidence, not a live-source gate after authorized
successor edits. No fabricated pins or publication/installation authority.
"""

from datetime import datetime
from pathlib import Path
import re

from scripts.verify_release_workflow_v70 import POLICY, _entries, _file, _json, _root, _sha256
from scripts.verify_release_workflow_v99 import V99, V99_ROOT_SHA256, V99_SHA256

PROJECT = Path(__file__).resolve().parents[1]
V100 = Path("tests/fixtures/release_workflow_transition_v100.json")
V100_SHA256 = "ec9302df2b6bece061e4f0a0c62e922539e82d78d05b0295d27d9386d2241161"
V100_ROOT_SHA256 = "518b785ff485ab32d28d115d76bbcf8b4c23a7bf5dcfc885818977617f333574"


class ReleaseWorkflowV100Error(RuntimeError):
    """V100 is unsealed, unavailable, or its source authority has drifted."""


def _verify(project):
    if not all(
        re.fullmatch(r"[0-9a-f]{64}", pin) for pin in (V100_SHA256, V100_ROOT_SHA256)
    ):
        raise ReleaseWorkflowV100Error("V100 unsealed: awaiting parent 'seal now' and final pins")
    root = Path(project).resolve(strict=True)
    record = _json(_file(root, V100))
    old = _json(_file(root, V99))
    if (
        _sha256(root / V99) != V99_SHA256
        or old.get("current_root_sha256") != V99_ROOT_SHA256
        or _root(old, 99) != V99_ROOT_SHA256
        or len(_entries(old)) != 669
    ):
        raise ReleaseWorkflowV100Error("V99 predecessor drifted")
    if (
        _sha256(root / V100) != V100_SHA256
        or record.get("schema") != "onyx.release-workflow-transition.v100"
        or record.get("logical_sequence") != 100
        or record.get("predecessor") != {"path": V99.as_posix(), "sha256": V99_SHA256}
        or record.get("policy") != POLICY
        or record.get("current_root_sha256") != V100_ROOT_SHA256
        or _root(record, 100) != V100_ROOT_SHA256
        or datetime.fromisoformat(record["issued_at"]) <= datetime.fromisoformat(old["issued_at"])
    ):
        raise ReleaseWorkflowV100Error("V100 contract drifted or unsealed")
    entries = _entries(record)
    paths = {row["path"] for row in entries}
    required = {
        *(row["path"] for row in _entries(old)),
        *(f"tests/fixtures/release_workflow_transition_v{sequence}.json" for sequence in range(71, 100)),
        "scripts/verify_release_workflow_v99.py",
        "scripts/generate_release_workflow_v100.py",
        "tests/test_release_workflow_transition_v100.py",
    }
    if not required.issubset(paths):
        raise ReleaseWorkflowV100Error("V100 dropped predecessor or historical coverage")
    if {V100.as_posix(), "scripts/verify_release_workflow_v100.py"}.intersection(paths):
        raise ReleaseWorkflowV100Error("V100 contains a circular digest dependency")
    for row in entries:
        if _sha256(_file(root, row["path"])) != row["sha256"]:
            raise ReleaseWorkflowV100Error(f"current release target drifted: {row['path']}")
    return {"transition": record, "publishable": False, "formal_release_ready": False}


def verify_release_workflow_v100(project=PROJECT):
    try:
        return _verify(project)
    except ReleaseWorkflowV100Error:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise ReleaseWorkflowV100Error(f"V100 input unavailable or invalid: {exc}") from exc


if __name__ == "__main__":
    print(verify_release_workflow_v100()["transition"]["current_root_sha256"])
