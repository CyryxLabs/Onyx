"""Independent verifier for the additive Release V56 successor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.verify_release_workflow_v45 import (  # noqa: E402
    POLICY,
    _canonical_file,
    _entries,
    _issued,
    _root,
    _sha256,
    _strict_json,
)

V56 = Path("tests/fixtures/release_workflow_transition_v56.json")
V55 = Path("tests/fixtures/release_workflow_transition_v55.json")
V56_SHA256 = "381ad6b56ae33cd81237e70dc4870c56b966d999574e8dcff298d77aec165bbf"
V56_ROOT_SHA256 = "e974949749bfd2e090b9556dc3b0b5251923b9c9b22d316d396755308767e461"
V55_SHA256 = "161b84b2c7bbb607d6221219037d665889c3579cd395417955e1ff727f093584"
V55_ROOT_SHA256 = "747dd23aba4db6c3c6812c6ed49abf2e137cbc98f0afe4160139b730ae9685e2"
RECEIPT = Path("docs/onyx/checkpoints/RELEASE_WORKFLOW_V56_VERIFIER_RECEIPT.json")


class ReleaseWorkflowV56Error(RuntimeError):
    """Release V56 or its immutable V55 predecessor drifted."""


def verify_release_workflow_v56(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition = _strict_json(_canonical_file(root, V56))
    predecessor = _strict_json(_canonical_file(root, V55))
    if (
        _sha256(root / V56) != V56_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v56"
        or transition.get("logical_sequence") != 56
        or transition.get("predecessor")
        != {"path": V55.as_posix(), "sha256": V55_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V56_ROOT_SHA256
        or _root(transition, 56) != V56_ROOT_SHA256
    ):
        raise ReleaseWorkflowV56Error("Release V56 contract drifted")
    if (
        _sha256(root / V55) != V55_SHA256
        or predecessor.get("current_root_sha256") != V55_ROOT_SHA256
        or _root(predecessor, 55) != V55_ROOT_SHA256
        or _issued(transition["issued_at"], "V56")
        <= _issued(predecessor["issued_at"], "V55")
    ):
        raise ReleaseWorkflowV56Error("Release V55 predecessor drifted")
    for entry in _entries(transition, "Release V56"):
        if _sha256(_canonical_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV56Error(
                f"current release target drifted: {entry['path']}"
            )
    receipt = _strict_json(_canonical_file(root, RECEIPT))
    expected = {
        "schema": "onyx.release-workflow-v56-verifier-receipt.v1",
        "release_path": V56.as_posix(),
        "release_sha256": V56_SHA256,
        "release_root_sha256": V56_ROOT_SHA256,
        "predecessor_sha256": V55_SHA256,
        "verifier_path": "scripts/verify_release_workflow_v56.py",
        "verifier_sha256": _sha256(root / "scripts/verify_release_workflow_v56.py"),
        "test_path": "tests/test_release_workflow_transition_v56.py",
        "test_sha256": _sha256(root / "tests/test_release_workflow_transition_v56.py"),
        "chronology": "normal_successor",
        "scope": "exact-capability-runtime-source-package-closure-only",
    }
    if receipt != expected:
        raise ReleaseWorkflowV56Error("Release V56 verifier receipt drifted")
    return {
        "transition": transition,
        "receipt": receipt,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    result = verify_release_workflow_v56()
    print(
        json.dumps(
            {
                "release_schema": result["transition"]["schema"],
                "release_root_sha256": result["transition"]["current_root_sha256"],
            },
            sort_keys=True,
        )
    )
