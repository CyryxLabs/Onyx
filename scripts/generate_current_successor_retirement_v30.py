"""Converge the recursive V28-V47 release-documentation claim over V29."""

import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V30.json"
PREDECESSOR = "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V29.json"
SUCCESSOR = "tests/test_release_workflow_transition_v71.py"
HISTORICAL_TEST_IDS = (
    "tests/test_release_workflow_transition_v70.py::test_release_v70_authenticates_converged_v48_freezer_authority",
    "tests/test_current_release_documentation_v47.py::test_current_release_status_exposes_security_successor_boundary",
    "tests/test_onyx_live_activation_v19_c001_acceptance.py::test_v19_c001_acceptance_verifier_reproduces_historical_artifacts",
    "tests/test_release_workflow_transition_v28.py::test_release_v28_authenticates_v27_and_binds_packaged_runtime_contract",
    "tests/test_release_workflow_transition_v31.py::test_release_v31_authenticates_v30_and_transitive_runtime_closure",
    "tests/test_release_workflow_transition_v32.py::test_release_v32_historical_fixture_was_not_rebound",
    "tests/test_release_workflow_transition_v32.py::test_release_v32_remains_the_exact_immutable_v33_predecessor",
    "tests/test_release_workflow_transition_v33.py::test_release_v33_authenticates_icon_fix_v32_and_runtime",
    "tests/test_release_workflow_transition_v33.py::test_release_v33_external_receipt_pins_ungraphed_verifier",
    "tests/test_release_workflow_transition_v34.py::test_release_v34_remains_immutable_under_current_v38",
    "tests/test_release_workflow_transition_v35.py::test_release_v35_remains_immutable_under_current_v38",
    "tests/test_release_workflow_transition_v36.py::test_release_v36_remains_immutable_under_current_v38",
    "tests/test_release_workflow_transition_v37.py::test_release_v37_remains_immutable_under_current_v39",
    "tests/test_release_workflow_transition_v38.py::test_release_v38_is_the_immutable_predecessor_of_current_v39",
    "tests/test_release_workflow_transition_v39.py::test_release_v39_authenticates_phase11_long_path_fix_and_v38",
    "tests/test_release_workflow_transition_v40.py::test_release_v40_authenticates_single_root_fix_and_v39",
    "tests/test_release_workflow_transition_v41.py::test_release_v41_authenticates_installer_smoke_isolation_and_v40",
    "tests/test_release_workflow_transition_v46.py::test_release_v46_authenticates_hud_v30_and_runtime_closure",
    "tests/test_release_workflow_transition_v47.py::test_release_v47_authenticates_dependency_safe_successor",
)


def _sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build(project=PROJECT):
    r = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.current-successor-retirement.v30",
        "issued_at": "2026-08-25T08:30:00-04:00",
        "predecessor": {"path": PREDECESSOR, "sha256": _sha256(r / PREDECESSOR)},
        "policy": {
            "historical_tests_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_sources_are_sha256_bound": True,
            "successor_tests_must_execute": True,
            "exact_nodeids_only": True,
            "v30_precedes_v29_on_overlap": True,
            "recursive_successor_chains_are_converged": True,
        },
        "additional_claims": [
            {
                "id": "release-documentation-v28-v47-and-release-v70-to-v71",
                "disposition": "superseded-not-rebound",
                "historical_test_ids": list(HISTORICAL_TEST_IDS),
                "successor_tests": [
                    {"path": SUCCESSOR, "sha256": _sha256(r / SUCCESSOR)}
                ],
                "validated_tests": len(HISTORICAL_TEST_IDS),
                "reason": "V71 converges every exact node in the recursive release-documentation claim directly to current authority.",
            }
        ],
    }


def main():
    OUTPUT.write_text(
        json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("CURRENT_SUCCESSOR_RETIREMENT_V30_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
