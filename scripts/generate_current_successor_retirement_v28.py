"""Converge the recursive Phase 5 claim and Release V68 over immutable V27."""

import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V28.json"
PREDECESSOR = "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V27.json"
SUCCESSOR = "tests/test_release_workflow_transition_v69.py"
HISTORICAL_TEST_IDS = (
    "tests/test_release_workflow_transition_v68.py::test_release_v68_authenticates_current_packaged_hud_smoke",
    "tests/test_freeze_release_source_v47.py::test_freezer_selects_exact_v47_current_authorities",
    "tests/test_phase5_current_successor_transition_v10.py::test_v13_current_target_drift_fails_closed",
    "tests/test_phase5_current_successor_transition_v10.py::test_v13_manifest_tamper_fails_closed",
    "tests/test_phase5_current_successor_transition_v10.py::test_v13_predecessor_tamper_fails_closed",
    "tests/test_phase5_current_successor_transition_v2.py::test_transition_preserves_every_predecessor_binding_without_rebinding",
    "tests/test_phase5_current_successor_transition_v37.py::test_v37_authenticates_v36_and_current_package_authorities",
    "tests/test_phase5_current_successor_transition_v38.py::test_v38_authenticates_v37_and_frozen_runtime_authorities",
    "tests/test_phase5_current_successor_transition_v40.py::test_v40_is_the_immutable_predecessor_of_current_v41",
    "tests/test_phase5_current_successor_transition_v41.py::test_v41_is_the_immutable_predecessor_of_current_v42",
    "tests/test_phase5_current_successor_transition_v42.py::test_v42_is_the_immutable_predecessor_of_current_v43",
    "tests/test_phase5_current_successor_transition_v45.py::test_v45_authenticates_v44_and_current_portable_release_corrections",
    "tests/test_phase5_current_successor_transition_v47.py::test_v47_authenticates_v46_and_current_security_successor",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.current-successor-retirement.v28",
        "issued_at": "2026-08-25T00:30:00-04:00",
        "predecessor": {"path": PREDECESSOR, "sha256": _sha256(root / PREDECESSOR)},
        "policy": {"historical_tests_are_rewritten": False, "historical_hashes_are_rebound": False, "registered_nodes_must_remain_collected": True, "successor_sources_are_sha256_bound": True, "successor_tests_must_execute": True, "exact_nodeids_only": True, "v28_precedes_v27_on_overlap": True, "recursive_successor_chains_are_converged": True},
        "additional_claims": [{"id": "phase5-v37-v47-and-release-v68-to-v69", "disposition": "superseded-not-rebound", "historical_test_ids": list(HISTORICAL_TEST_IDS), "successor_tests": [{"path": SUCCESSOR, "sha256": _sha256(root / SUCCESSOR)}], "validated_tests": len(HISTORICAL_TEST_IDS), "reason": "V69 converges the exact recursive Phase 5 nodes directly to current authority while every historical node remains collected."}],
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("CURRENT_SUCCESSOR_RETIREMENT_V28_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
