"""Independent verifier for the evidence-corrected Release V48 successor."""

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


RELEASE_V48_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v48.json"
)
RELEASE_V48_SHA256: Final = (
    "32ff477f4cfe144c024309b119b3f4e630a703bcee9473071e847d2d257b60db"
)
RELEASE_V48_ROOT_SHA256: Final = (
    "6c1a4bf6cca967b105b7d83b89cba85419953d5d28a151006ea4f3120352573e"
)
RELEASE_V47_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v47.json"
)
RELEASE_V47_SHA256: Final = (
    "96743238fee217e561ceb91734649aa1394f930acc312a30e0491bd7714267cc"
)
RELEASE_V47_ROOT_SHA256: Final = (
    "cc9ce78980e2a714c26f046449a7ed8aa770a19d09322909adbf4106464238b6"
)
V47_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v47.py")
V47_VERIFIER_SHA256: Final = (
    "2c1064fc5cf3a4d4c1a64cbaba1b48ad5d20f9cff8623ad8c5fc7419db05b9d1"
)
V47_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V47_VERIFIER_RECEIPT.json"
)
V47_RECEIPT_SHA256: Final = (
    "8523362cc95808848c960327bb58d21ee7687d1711f52c21a2279fb12c2b3cb9"
)
V47_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v47.py")
V47_TEST_SHA256: Final = (
    "5cc92a45ddfcef96751f5be9bc20e1f7d20a963af76373df27b1971bc74bd219"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v48.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V48_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v48.py")


class ReleaseWorkflowV48Error(RuntimeError):
    """Release V48 or its immutable V47 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition_path = _canonical_file(root, RELEASE_V48_RELATIVE)
    if _sha256(transition_path) != RELEASE_V48_SHA256:
        raise ReleaseWorkflowV48Error("Release V48 fixture digest drifted")
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
        or transition.get("schema") != "onyx.release-workflow-transition.v48"
        or transition.get("logical_sequence") != 48
        or transition.get("predecessor")
        != {"path": RELEASE_V47_RELATIVE.as_posix(), "sha256": RELEASE_V47_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V48_ROOT_SHA256
        or _root(transition, 48) != RELEASE_V48_ROOT_SHA256
    ):
        raise ReleaseWorkflowV48Error("Release V48 contract drifted")

    predecessor_path = _canonical_file(root, RELEASE_V47_RELATIVE)
    if _sha256(predecessor_path) != RELEASE_V47_SHA256:
        raise ReleaseWorkflowV48Error("Release V47 predecessor digest drifted")
    predecessor = _strict_json(predecessor_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v47"
        or predecessor.get("logical_sequence") != 47
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V47_ROOT_SHA256
        or _root(predecessor, 47) != RELEASE_V47_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V48 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V47 issued_at")
    ):
        raise ReleaseWorkflowV48Error("Release V47 predecessor contract drifted")
    for relative, expected in (
        (V47_VERIFIER_RELATIVE, V47_VERIFIER_SHA256),
        (V47_RECEIPT_RELATIVE, V47_RECEIPT_SHA256),
        (V47_TEST_RELATIVE, V47_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV48Error(f"Release V47 authority drifted: {relative}")

    current_entries = _entries(transition, "Release V48")
    for entry in current_entries:
        relative = entry["path"]
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV48Error(f"current release target drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v48-verifier-receipt.v1",
        "release_path": RELEASE_V48_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V48_SHA256,
        "release_root_sha256": RELEASE_V48_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V47_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
    }:
        raise ReleaseWorkflowV48Error("Release V48 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v30 import verify_current_hud_acceptance
    from scripts.verify_capability_nexus_current_v1 import verify as verify_capability
    from scripts.verify_current_successor_retirement_v1 import registered_test_ids
    from scripts.verify_phase5_exit_retirement_v1 import (
        load_current_successor_transition,
    )

    runtime = verify_current_hud_acceptance(root)
    capability = verify_capability(root)
    phase5 = load_current_successor_transition()
    retired_nodes = registered_test_ids(root)
    if phase5.get("schema") != "onyx.phase5-current-successor-transition.v48":
        raise ReleaseWorkflowV48Error("Phase 5 V48 selector drifted")
    if len(retired_nodes) != 67:
        raise ReleaseWorkflowV48Error("current retirement registry drifted")
    return {
        "transition": transition,
        "v47_predecessor": predecessor,
        "runtime": runtime,
        "capability": capability,
        "phase5": phase5,
        "retired_test_count": len(retired_nodes),
        "receipt": receipt,
        "formal_release_ready": False,
        "publishable": False,
    }


def verify_release_workflow_v48(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseWorkflowV43Error, ReleaseWorkflowV45Error) as exc:
        raise ReleaseWorkflowV48Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v48()
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
