"""Independent verifier for the ambient-motion Release V49 successor."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.verify_release_workflow_v45 import (  # noqa: E402
    POLICY,
    ReleaseWorkflowV43Error,
    ReleaseWorkflowV45Error,
    _canonical_file,
    _entries,
    _issued,
    _root,
    _sha256,
    _strict_json,
)


RELEASE_V49_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v49.json"
)
RELEASE_V49_SHA256: Final = (
    "7282fdb38d77607b58fceb965a0dac218629e8a4f1d0d2e995c27f31f8fabfad"
)
RELEASE_V49_ROOT_SHA256: Final = (
    "2511c0f0e5a4856c1fb598ed0276cd1a1854eb319a8d23476ccf05b58f0ba864"
)
RELEASE_V48_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v48.json"
)
RELEASE_V48_SHA256: Final = (
    "32ff477f4cfe144c024309b119b3f4e630a703bcee9473071e847d2d257b60db"
)
RELEASE_V48_ROOT_SHA256: Final = (
    "6c1a4bf6cca967b105b7d83b89cba85419953d5d28a151006ea4f3120352573e"
)
V48_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v48.py")
V48_VERIFIER_SHA256: Final = (
    "1b1241dc4aee474a356950d363e7d52bdfaaf563c424719e0eca6788fdad711f"
)
V48_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V48_VERIFIER_RECEIPT.json"
)
V48_RECEIPT_SHA256: Final = (
    "71b2341f47e747eacc821d1e6cedb0912c25c5fb94cc04a221be0abe17552829"
)
V48_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v48.py")
V48_TEST_SHA256: Final = (
    "0e51276130f3382a3d6e45179a82056420d7ceb64651b95e13bd4ea1dc9b4b35"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v49.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V49_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v49.py")


class ReleaseWorkflowV49Error(RuntimeError):
    """Release V49 or its immutable V48 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition_path = _canonical_file(root, RELEASE_V49_RELATIVE)
    if _sha256(transition_path) != RELEASE_V49_SHA256:
        raise ReleaseWorkflowV49Error("Release V49 fixture digest drifted")
    transition = _strict_json(transition_path)
    if (
        set(transition)
        != {
            "schema",
            "issued_at",
            "logical_sequence",
            "predecessor",
            "policy",
            "current_release_paths",
            "current_root_sha256",
        }
        or transition.get("schema") != "onyx.release-workflow-transition.v49"
        or transition.get("logical_sequence") != 49
        or transition.get("predecessor")
        != {"path": RELEASE_V48_RELATIVE.as_posix(), "sha256": RELEASE_V48_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V49_ROOT_SHA256
        or _root(transition, 49) != RELEASE_V49_ROOT_SHA256
    ):
        raise ReleaseWorkflowV49Error("Release V49 contract drifted")

    predecessor_path = _canonical_file(root, RELEASE_V48_RELATIVE)
    if _sha256(predecessor_path) != RELEASE_V48_SHA256:
        raise ReleaseWorkflowV49Error("Release V48 predecessor digest drifted")
    predecessor = _strict_json(predecessor_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v48"
        or predecessor.get("logical_sequence") != 48
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V48_ROOT_SHA256
        or _root(predecessor, 48) != RELEASE_V48_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V49 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V48 issued_at")
    ):
        raise ReleaseWorkflowV49Error("Release V48 predecessor contract drifted")
    for relative, expected in (
        (V48_VERIFIER_RELATIVE, V48_VERIFIER_SHA256),
        (V48_RECEIPT_RELATIVE, V48_RECEIPT_SHA256),
        (V48_TEST_RELATIVE, V48_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV49Error(f"Release V48 authority drifted: {relative}")

    for entry in _entries(transition, "Release V49"):
        relative = entry["path"]
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV49Error(f"current release target drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v49-verifier-receipt.v1",
        "release_path": RELEASE_V49_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V49_SHA256,
        "release_root_sha256": RELEASE_V49_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V48_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
    }:
        raise ReleaseWorkflowV49Error("Release V49 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v31 import verify_current_hud_acceptance
    from scripts.verify_capability_nexus_current_v1 import verify as verify_capability
    from scripts.verify_current_successor_retirement_v1 import registered_test_ids
    from scripts.verify_phase5_exit_retirement_v1 import load_current_successor_transition

    runtime = verify_current_hud_acceptance(root)
    capability = verify_capability(root)
    phase5 = load_current_successor_transition()
    retired_nodes = registered_test_ids(root)
    if phase5.get("schema") != "onyx.phase5-current-successor-transition.v49":
        raise ReleaseWorkflowV49Error("Phase 5 V49 selector drifted")
    if len(retired_nodes) != 67:
        raise ReleaseWorkflowV49Error("current retirement registry drifted")
    return {
        "transition": transition,
        "v48_predecessor": predecessor,
        "runtime": runtime,
        "capability": capability,
        "phase5": phase5,
        "retired_test_count": len(retired_nodes),
        "receipt": receipt,
        "formal_release_ready": False,
        "publishable": False,
    }


def verify_release_workflow_v49(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseWorkflowV43Error, ReleaseWorkflowV45Error) as exc:
        raise ReleaseWorkflowV49Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v49()
    print(
        json.dumps(
            {
                "release_root_sha256": verified["transition"]["current_root_sha256"],
                "release_schema": verified["transition"]["schema"],
                "retired_test_count": verified["retired_test_count"],
                "runtime_root_sha256": verified["runtime"]["artifact_root_sha256"],
            },
            sort_keys=True,
        )
    )
