"""Independent verifier for the Release V53 portable-test successor."""

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


RELEASE_V53_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v53.json"
)
RELEASE_V53_SHA256: Final = (
    "2d1531743bd7f1a30f680c447d819a1724771c70c98f4006cf940cc8433cac52"
)
RELEASE_V53_ROOT_SHA256: Final = (
    "3b3de7f148463a71ce281d5c55c43fe99e4189d8fc33990da0b22499c4feb9b7"
)
RELEASE_V52_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v52.json"
)
RELEASE_V52_SHA256: Final = (
    "d267bda604226f0136638b5b20f9b2abe7d858e25b61ce4ba0a6214caf016e58"
)
RELEASE_V52_ROOT_SHA256: Final = (
    "69e9d08b89cbd69f35971187ffc475e782bc4cef6d61b50c7a5453954b8211b7"
)
V52_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v52.py")
V52_VERIFIER_SHA256: Final = (
    "18540824e7de068f548b9968248f3c427d2f0c2903f3bb7622a5ce92692db338"
)
V52_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V52_VERIFIER_RECEIPT.json"
)
V52_RECEIPT_SHA256: Final = (
    "5b258b3535b17367c0ac6db1edcd5db8fb0bbbd318e7a029b0c3e56d07356c07"
)
V52_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v52.py")
V52_TEST_SHA256: Final = (
    "fb7345dd02d42b380553770b18bdc3d651f537dd2736514246d7571e51c6ad48"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v53.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V53_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v53.py")


class ReleaseWorkflowV53Error(RuntimeError):
    """Release V53 or its immutable V52 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition_path = _canonical_file(root, RELEASE_V53_RELATIVE)
    if _sha256(transition_path) != RELEASE_V53_SHA256:
        raise ReleaseWorkflowV53Error("Release V53 fixture digest drifted")
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
        or transition.get("schema") != "onyx.release-workflow-transition.v53"
        or transition.get("logical_sequence") != 53
        or transition.get("predecessor")
        != {"path": RELEASE_V52_RELATIVE.as_posix(), "sha256": RELEASE_V52_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V53_ROOT_SHA256
        or _root(transition, 53) != RELEASE_V53_ROOT_SHA256
    ):
        raise ReleaseWorkflowV53Error("Release V53 contract drifted")

    predecessor_path = _canonical_file(root, RELEASE_V52_RELATIVE)
    if _sha256(predecessor_path) != RELEASE_V52_SHA256:
        raise ReleaseWorkflowV53Error("Release V52 predecessor digest drifted")
    predecessor = _strict_json(predecessor_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v52"
        or predecessor.get("logical_sequence") != 52
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V52_ROOT_SHA256
        or _root(predecessor, 52) != RELEASE_V52_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V53 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V52 issued_at")
    ):
        raise ReleaseWorkflowV53Error("Release V52 predecessor contract drifted")
    for relative, expected in (
        (V52_VERIFIER_RELATIVE, V52_VERIFIER_SHA256),
        (V52_RECEIPT_RELATIVE, V52_RECEIPT_SHA256),
        (V52_TEST_RELATIVE, V52_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV53Error(f"Release V52 authority drifted: {relative}")

    for entry in _entries(transition, "Release V53"):
        relative = entry["path"]
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV53Error(f"current release target drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v53-verifier-receipt.v1",
        "release_path": RELEASE_V53_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V53_SHA256,
        "release_root_sha256": RELEASE_V53_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V52_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
        "scope": "portable-cross-platform-test-contract-only",
    }:
        raise ReleaseWorkflowV53Error("Release V53 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v31 import verify_current_hud_acceptance
    from scripts.verify_capability_nexus_current_v1 import verify as verify_capability
    from scripts.verify_current_successor_retirement_v1 import registered_test_ids
    from scripts.verify_phase5_exit_retirement_v1 import load_current_successor_transition

    runtime = verify_current_hud_acceptance(root)
    capability = verify_capability(root)
    phase5 = load_current_successor_transition()
    retired_nodes = registered_test_ids(root)
    if phase5.get("schema") != "onyx.phase5-current-successor-transition.v51":
        raise ReleaseWorkflowV53Error("Phase 5 V51 evidence selector drifted")
    if len(retired_nodes) != 76:
        raise ReleaseWorkflowV53Error("current retirement registry drifted")
    return {
        "transition": transition,
        "v52_predecessor": predecessor,
        "runtime": runtime,
        "capability": capability,
        "phase5": phase5,
        "retired_test_count": len(retired_nodes),
        "receipt": receipt,
        "runtime_authority_changed": False,
        "formal_release_ready": False,
        "publishable": False,
    }


def verify_release_workflow_v53(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseWorkflowV43Error, ReleaseWorkflowV45Error) as exc:
        raise ReleaseWorkflowV53Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v53()
    print(
        json.dumps(
            {
                "release_root_sha256": verified["transition"]["current_root_sha256"],
                "release_schema": verified["transition"]["schema"],
                "retired_test_count": verified["retired_test_count"],
                "runtime_authority_changed": verified["runtime_authority_changed"],
            },
            sort_keys=True,
        )
    )
