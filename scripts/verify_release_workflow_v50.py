"""Independent verifier for the post-R10B Release V50 evidence successor."""

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


RELEASE_V50_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v50.json"
)
RELEASE_V50_SHA256: Final = (
    "b300c424f9d816b6c6061917882c61a07cfcff72496ea3f98539c93805be1814"
)
RELEASE_V50_ROOT_SHA256: Final = (
    "65cc638781c0b430dcf70c5ce15f1d5a65579c36bda5524fc793ca91fdf8cb75"
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
V49_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v49.py")
V49_VERIFIER_SHA256: Final = (
    "1eaa627d6492e110716981bae4183e8f5daac2f1f3cf01c53df5b78ae2c01f3a"
)
V49_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V49_VERIFIER_RECEIPT.json"
)
V49_RECEIPT_SHA256: Final = (
    "be05bf775e6a28a2c2e19f24888023d13747e321bfb1a2cda37e3677d08d6db1"
)
V49_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v49.py")
V49_TEST_SHA256: Final = (
    "b32e642286aa82b6c7d98ba95dd88c6d8a518010f75bb39ba37b4ba350df7e9f"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v50.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V50_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v50.py")


class ReleaseWorkflowV50Error(RuntimeError):
    """Release V50 or its immutable V49 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition_path = _canonical_file(root, RELEASE_V50_RELATIVE)
    if _sha256(transition_path) != RELEASE_V50_SHA256:
        raise ReleaseWorkflowV50Error("Release V50 fixture digest drifted")
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
        or transition.get("schema") != "onyx.release-workflow-transition.v50"
        or transition.get("logical_sequence") != 50
        or transition.get("predecessor")
        != {"path": RELEASE_V49_RELATIVE.as_posix(), "sha256": RELEASE_V49_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V50_ROOT_SHA256
        or _root(transition, 50) != RELEASE_V50_ROOT_SHA256
    ):
        raise ReleaseWorkflowV50Error("Release V50 contract drifted")

    predecessor_path = _canonical_file(root, RELEASE_V49_RELATIVE)
    if _sha256(predecessor_path) != RELEASE_V49_SHA256:
        raise ReleaseWorkflowV50Error("Release V49 predecessor digest drifted")
    predecessor = _strict_json(predecessor_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v49"
        or predecessor.get("logical_sequence") != 49
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V49_ROOT_SHA256
        or _root(predecessor, 49) != RELEASE_V49_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V50 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V49 issued_at")
    ):
        raise ReleaseWorkflowV50Error("Release V49 predecessor contract drifted")
    for relative, expected in (
        (V49_VERIFIER_RELATIVE, V49_VERIFIER_SHA256),
        (V49_RECEIPT_RELATIVE, V49_RECEIPT_SHA256),
        (V49_TEST_RELATIVE, V49_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV50Error(f"Release V49 authority drifted: {relative}")

    for entry in _entries(transition, "Release V50"):
        relative = entry["path"]
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV50Error(f"current release target drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v50-verifier-receipt.v1",
        "release_path": RELEASE_V50_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V50_SHA256,
        "release_root_sha256": RELEASE_V50_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V49_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
        "scope": "post-r10b-technical-evidence-only",
    }:
        raise ReleaseWorkflowV50Error("Release V50 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v31 import verify_current_hud_acceptance
    from scripts.verify_capability_nexus_current_v1 import verify as verify_capability
    from scripts.verify_current_successor_retirement_v1 import registered_test_ids
    from scripts.verify_phase5_exit_retirement_v1 import load_current_successor_transition

    runtime = verify_current_hud_acceptance(root)
    capability = verify_capability(root)
    phase5 = load_current_successor_transition()
    retired_nodes = registered_test_ids(root)
    if phase5.get("schema") != "onyx.phase5-current-successor-transition.v50":
        raise ReleaseWorkflowV50Error("Phase 5 V50 evidence selector drifted")
    if len(retired_nodes) != 67:
        raise ReleaseWorkflowV50Error("current retirement registry drifted")
    return {
        "transition": transition,
        "v49_predecessor": predecessor,
        "runtime": runtime,
        "capability": capability,
        "phase5": phase5,
        "retired_test_count": len(retired_nodes),
        "receipt": receipt,
        "runtime_authority_changed": False,
        "formal_release_ready": False,
        "publishable": False,
    }


def verify_release_workflow_v50(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseWorkflowV43Error, ReleaseWorkflowV45Error) as exc:
        raise ReleaseWorkflowV50Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v50()
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
