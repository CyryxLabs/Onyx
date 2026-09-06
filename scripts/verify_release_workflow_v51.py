"""Independent verifier for the Release V51 exact-qualification successor."""

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


RELEASE_V51_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v51.json"
)
RELEASE_V51_SHA256: Final = (
    "524594408b9b26297babad1e94f301435234989285137ceaa2b5d6c4241b7984"
)
RELEASE_V51_ROOT_SHA256: Final = (
    "5d573702a0341129afd395f492d64b7966e7d4d72f5bc5bb3870fd353c587228"
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
V50_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v50.py")
V50_VERIFIER_SHA256: Final = (
    "4462e395d56cf7888e27e484f58498a499b1070c52b344fa57b552d97c22b243"
)
V50_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V50_VERIFIER_RECEIPT.json"
)
V50_RECEIPT_SHA256: Final = (
    "dc33d429729738c484f34e646102d46d55e3201a6a87581468d88efe29a59fd6"
)
V50_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v50.py")
V50_TEST_SHA256: Final = (
    "d9c817d7e78dad08765468bb9ca15de9dd6d356f28e66253224f527295a0a263"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v51.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V51_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v51.py")


class ReleaseWorkflowV51Error(RuntimeError):
    """Release V51 or its immutable V50 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition_path = _canonical_file(root, RELEASE_V51_RELATIVE)
    if _sha256(transition_path) != RELEASE_V51_SHA256:
        raise ReleaseWorkflowV51Error("Release V51 fixture digest drifted")
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
        or transition.get("schema") != "onyx.release-workflow-transition.v51"
        or transition.get("logical_sequence") != 51
        or transition.get("predecessor")
        != {"path": RELEASE_V50_RELATIVE.as_posix(), "sha256": RELEASE_V50_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V51_ROOT_SHA256
        or _root(transition, 51) != RELEASE_V51_ROOT_SHA256
    ):
        raise ReleaseWorkflowV51Error("Release V51 contract drifted")

    predecessor_path = _canonical_file(root, RELEASE_V50_RELATIVE)
    if _sha256(predecessor_path) != RELEASE_V50_SHA256:
        raise ReleaseWorkflowV51Error("Release V50 predecessor digest drifted")
    predecessor = _strict_json(predecessor_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v50"
        or predecessor.get("logical_sequence") != 50
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V50_ROOT_SHA256
        or _root(predecessor, 50) != RELEASE_V50_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V51 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V50 issued_at")
    ):
        raise ReleaseWorkflowV51Error("Release V50 predecessor contract drifted")
    for relative, expected in (
        (V50_VERIFIER_RELATIVE, V50_VERIFIER_SHA256),
        (V50_RECEIPT_RELATIVE, V50_RECEIPT_SHA256),
        (V50_TEST_RELATIVE, V50_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV51Error(f"Release V50 authority drifted: {relative}")

    for entry in _entries(transition, "Release V51"):
        relative = entry["path"]
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV51Error(f"current release target drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v51-verifier-receipt.v1",
        "release_path": RELEASE_V51_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V51_SHA256,
        "release_root_sha256": RELEASE_V51_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V50_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
        "scope": "exact-native-qualification-pipeline-only",
    }:
        raise ReleaseWorkflowV51Error("Release V51 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v31 import verify_current_hud_acceptance
    from scripts.verify_capability_nexus_current_v1 import verify as verify_capability
    from scripts.verify_current_successor_retirement_v1 import registered_test_ids
    from scripts.verify_phase5_exit_retirement_v1 import load_current_successor_transition

    runtime = verify_current_hud_acceptance(root)
    capability = verify_capability(root)
    phase5 = load_current_successor_transition()
    retired_nodes = registered_test_ids(root)
    if phase5.get("schema") != "onyx.phase5-current-successor-transition.v51":
        raise ReleaseWorkflowV51Error("Phase 5 V51 evidence selector drifted")
    if len(retired_nodes) != 72:
        raise ReleaseWorkflowV51Error("current retirement registry drifted")
    return {
        "transition": transition,
        "v50_predecessor": predecessor,
        "runtime": runtime,
        "capability": capability,
        "phase5": phase5,
        "retired_test_count": len(retired_nodes),
        "receipt": receipt,
        "runtime_authority_changed": False,
        "formal_release_ready": False,
        "publishable": False,
    }


def verify_release_workflow_v51(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseWorkflowV43Error, ReleaseWorkflowV45Error) as exc:
        raise ReleaseWorkflowV51Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v51()
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
