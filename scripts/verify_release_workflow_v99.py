"""V99 SOURCE verifier, explicitly unsealed until the parent's final seal.

V98 remains immutable historical authority. A successful source verification
does not certify publication, installation, or live operation.
"""

from datetime import datetime
from pathlib import Path
import re

from scripts.verify_release_workflow_v70 import POLICY, _entries, _file, _json, _root, _sha256
from scripts.verify_release_workflow_v98 import V98, V98_ROOT_SHA256, V98_SHA256

PROJECT = Path(__file__).resolve().parents[1]
V99 = Path("tests/fixtures/release_workflow_transition_v99.json")
V99_SHA256 = "ac6ae93d21f03707460e8cc566df36376005a02d7ea29dc91d71d8401fd89f83"
V99_ROOT_SHA256 = "d259df44d908a87ac543df642114ffe0ed11b67b7645ce2b6621a42061967533"


class ReleaseWorkflowV99Error(RuntimeError):
    """V99 is unsealed, unavailable, or its source authority has drifted."""


def _verify(project):
    if not all(
        re.fullmatch(r"[0-9a-f]{64}", pin) for pin in (V99_SHA256, V99_ROOT_SHA256)
    ):
        raise ReleaseWorkflowV99Error("V99 unsealed: awaiting parent 'seal now' and final pins")
    root = Path(project).resolve(strict=True)
    record = _json(_file(root, V99))
    old = _json(_file(root, V98))
    if (
        _sha256(root / V98) != V98_SHA256
        or old.get("current_root_sha256") != V98_ROOT_SHA256
        or _root(old, 98) != V98_ROOT_SHA256
        or len(_entries(old)) != 609
    ):
        raise ReleaseWorkflowV99Error("V98 predecessor drifted")
    if (
        _sha256(root / V99) != V99_SHA256
        or record.get("schema") != "onyx.release-workflow-transition.v99"
        or record.get("logical_sequence") != 99
        or record.get("predecessor") != {"path": V98.as_posix(), "sha256": V98_SHA256}
        or record.get("policy") != POLICY
        or record.get("current_root_sha256") != V99_ROOT_SHA256
        or _root(record, 99) != V99_ROOT_SHA256
        or datetime.fromisoformat(record["issued_at"]) <= datetime.fromisoformat(old["issued_at"])
    ):
        raise ReleaseWorkflowV99Error("V99 contract drifted or unsealed")
    entries = _entries(record)
    paths = {row["path"] for row in entries}
    required = {
        *(row["path"] for row in _entries(old)),
        *(f"tests/fixtures/release_workflow_transition_v{sequence}.json" for sequence in range(71, 99)),
        "scripts/verify_release_workflow_v98.py",
        "scripts/generate_release_workflow_v99.py",
        "tests/test_release_workflow_transition_v99.py",
    }
    if not required.issubset(paths):
        raise ReleaseWorkflowV99Error("V99 dropped predecessor or historical coverage")
    if {V99.as_posix(), "scripts/verify_release_workflow_v99.py"}.intersection(paths):
        raise ReleaseWorkflowV99Error("V99 contains a circular digest dependency")
    for row in entries:
        if _sha256(_file(root, row["path"])) != row["sha256"]:
            raise ReleaseWorkflowV99Error(f"current release target drifted: {row['path']}")
    return {"transition": record, "publishable": False, "formal_release_ready": False}


def verify_release_workflow_v99(project=PROJECT):
    try:
        return _verify(project)
    except ReleaseWorkflowV99Error:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise ReleaseWorkflowV99Error(f"V99 input unavailable or invalid: {exc}") from exc


if __name__ == "__main__":
    print(verify_release_workflow_v99()["transition"]["current_root_sha256"])
