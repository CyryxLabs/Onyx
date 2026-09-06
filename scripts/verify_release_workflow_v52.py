"""Independent verifier for the Release V52 legal-evidence successor."""

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


RELEASE_V52_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v52.json"
)
RELEASE_V52_SHA256: Final = (
    "d267bda604226f0136638b5b20f9b2abe7d858e25b61ce4ba0a6214caf016e58"
)
RELEASE_V52_ROOT_SHA256: Final = (
    "69e9d08b89cbd69f35971187ffc475e782bc4cef6d61b50c7a5453954b8211b7"
)
RELEASE_V51_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v51.json"
)
RELEASE_V51_SHA256: Final = (
    "524594408b9b26297babad1e94f301435234989285137ceaa2b5d6c4241b7984"
)
RELEASE_V51_ROOT_SHA256: Final = (
    "5d573702a0341129afd395f492d64b7966e7d4d72f5bc5bb3870fd353c587228"
)
V51_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v51.py")
V51_VERIFIER_SHA256: Final = (
    "c29ecb6404ad5f9384a1494d08493082471bf9164e2c507307c43ec7a2ab7d37"
)
V51_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V51_VERIFIER_RECEIPT.json"
)
V51_RECEIPT_SHA256: Final = (
    "cdde36b562557e36d5aae799e2800e61ce1c4cf72ce45cf9f0a2db6f1c729217"
)
V51_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v51.py")
V51_TEST_SHA256: Final = (
    "0103a00406ce0f2a90d24123262142cea35af73eefcff0cbd5e34c91340f23dd"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v52.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V52_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v52.py")


class ReleaseWorkflowV52Error(RuntimeError):
    """Release V52 or its immutable V51 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition_path = _canonical_file(root, RELEASE_V52_RELATIVE)
    if _sha256(transition_path) != RELEASE_V52_SHA256:
        raise ReleaseWorkflowV52Error("Release V52 fixture digest drifted")
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
        or transition.get("schema") != "onyx.release-workflow-transition.v52"
        or transition.get("logical_sequence") != 52
        or transition.get("predecessor")
        != {"path": RELEASE_V51_RELATIVE.as_posix(), "sha256": RELEASE_V51_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V52_ROOT_SHA256
        or _root(transition, 52) != RELEASE_V52_ROOT_SHA256
    ):
        raise ReleaseWorkflowV52Error("Release V52 contract drifted")

    predecessor_path = _canonical_file(root, RELEASE_V51_RELATIVE)
    if _sha256(predecessor_path) != RELEASE_V51_SHA256:
        raise ReleaseWorkflowV52Error("Release V51 predecessor digest drifted")
    predecessor = _strict_json(predecessor_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v51"
        or predecessor.get("logical_sequence") != 51
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V51_ROOT_SHA256
        or _root(predecessor, 51) != RELEASE_V51_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V52 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V51 issued_at")
    ):
        raise ReleaseWorkflowV52Error("Release V51 predecessor contract drifted")
    for relative, expected in (
        (V51_VERIFIER_RELATIVE, V51_VERIFIER_SHA256),
        (V51_RECEIPT_RELATIVE, V51_RECEIPT_SHA256),
        (V51_TEST_RELATIVE, V51_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV52Error(f"Release V51 authority drifted: {relative}")

    for entry in _entries(transition, "Release V52"):
        relative = entry["path"]
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV52Error(f"current release target drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v52-verifier-receipt.v1",
        "release_path": RELEASE_V52_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V52_SHA256,
        "release_root_sha256": RELEASE_V52_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V51_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
        "scope": "odfpy-legal-evidence-and-notices-only",
    }:
        raise ReleaseWorkflowV52Error("Release V52 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v31 import verify_current_hud_acceptance
    from scripts.verify_capability_nexus_current_v1 import verify as verify_capability
    from scripts.verify_current_successor_retirement_v1 import registered_test_ids
    from scripts.verify_phase5_exit_retirement_v1 import load_current_successor_transition

    runtime = verify_current_hud_acceptance(root)
    capability = verify_capability(root)
    phase5 = load_current_successor_transition()
    retired_nodes = registered_test_ids(root)
    if phase5.get("schema") != "onyx.phase5-current-successor-transition.v51":
        raise ReleaseWorkflowV52Error("Phase 5 V51 evidence selector drifted")
    if len(retired_nodes) != 74:
        raise ReleaseWorkflowV52Error("current retirement registry drifted")
    return {
        "transition": transition,
        "v51_predecessor": predecessor,
        "runtime": runtime,
        "capability": capability,
        "phase5": phase5,
        "retired_test_count": len(retired_nodes),
        "receipt": receipt,
        "runtime_authority_changed": False,
        "formal_release_ready": False,
        "publishable": False,
    }


def verify_release_workflow_v52(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseWorkflowV43Error, ReleaseWorkflowV45Error) as exc:
        raise ReleaseWorkflowV52Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v52()
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
