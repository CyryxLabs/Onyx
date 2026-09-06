"""Independent verifier for the additive Release V57 successor."""

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

V57 = Path("tests/fixtures/release_workflow_transition_v57.json")
V56 = Path("tests/fixtures/release_workflow_transition_v56.json")
V57_SHA256 = "7b866cac1987c43466d00118c1a81dc3761c307ec6455d51a9f46a01b1b0e16d"
V57_ROOT_SHA256 = "6154deffad8e5d5da41b83efe38d857d91a78ad6be9d68a0e7f3ace976b0122a"
V56_SHA256 = "381ad6b56ae33cd81237e70dc4870c56b966d999574e8dcff298d77aec165bbf"
V56_ROOT_SHA256 = "e974949749bfd2e090b9556dc3b0b5251923b9c9b22d316d396755308767e461"
RECEIPT = Path("docs/onyx/checkpoints/RELEASE_WORKFLOW_V57_VERIFIER_RECEIPT.json")


class ReleaseWorkflowV57Error(RuntimeError):
    """Release V57 or its immutable V56 predecessor drifted."""


def verify_release_workflow_v57(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    try:
        transition = _strict_json(_canonical_file(root, V57))
        predecessor = _strict_json(_canonical_file(root, V56))
    except RuntimeError as error:
        raise ReleaseWorkflowV57Error("Release V57 contract or predecessor drifted") from error
    if (
        _sha256(root / V57) != V57_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v57"
        or transition.get("logical_sequence") != 57
        or transition.get("predecessor")
        != {"path": V56.as_posix(), "sha256": V56_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V57_ROOT_SHA256
        or _root(transition, 57) != V57_ROOT_SHA256
    ):
        raise ReleaseWorkflowV57Error("Release V57 contract drifted")
    if (
        _sha256(root / V56) != V56_SHA256
        or predecessor.get("current_root_sha256") != V56_ROOT_SHA256
        or _root(predecessor, 56) != V56_ROOT_SHA256
        or _issued(transition["issued_at"], "V57")
        <= _issued(predecessor["issued_at"], "V56")
    ):
        raise ReleaseWorkflowV57Error("Release V56 predecessor drifted")
    for entry in _entries(transition, "Release V57"):
        if _sha256(_canonical_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV57Error(
                f"current release target drifted: {entry['path']}"
            )
    receipt = _strict_json(_canonical_file(root, RECEIPT))
    expected = {
        "schema": "onyx.release-workflow-v57-verifier-receipt.v1",
        "release_path": V57.as_posix(),
        "release_sha256": V57_SHA256,
        "release_root_sha256": V57_ROOT_SHA256,
        "predecessor_sha256": V56_SHA256,
        "verifier_path": "scripts/verify_release_workflow_v57.py",
        "verifier_sha256": _sha256(root / "scripts/verify_release_workflow_v57.py"),
        "test_path": "tests/test_release_workflow_transition_v57.py",
        "test_sha256": _sha256(root / "tests/test_release_workflow_transition_v57.py"),
        "chronology": "normal_successor",
        "scope": "current-runtime-v3-hud-v34-retirement-v16-closure-only",
    }
    if receipt != expected:
        raise ReleaseWorkflowV57Error("Release V57 verifier receipt drifted")
    return {
        "transition": transition,
        "receipt": receipt,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    result = verify_release_workflow_v57()
    print(
        json.dumps(
            {
                "release_schema": result["transition"]["schema"],
                "release_root_sha256": result["transition"]["current_root_sha256"],
            },
            sort_keys=True,
        )
    )
