"""Generate the additive V57-V60 to V61 release-test retirement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V21.json"
PREDECESSOR = "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V20.json"
SUCCESSOR = "tests/test_release_workflow_transition_v61.py"
HISTORICAL_TEST_IDS = (
    "tests/test_release_workflow_transition_v57.py::test_release_v57_authenticates_current_runtime_closure",
    "tests/test_release_workflow_transition_v57.py::test_release_v57_rejects_transition_or_predecessor_tamper[False]",
    "tests/test_release_workflow_transition_v57.py::test_release_v57_rejects_transition_or_predecessor_tamper[True]",
    "tests/test_release_workflow_transition_v57.py::test_release_v57_preserves_v56_bytes_and_refreshes_current_targets",
    "tests/test_release_workflow_transition_v58.py::test_release_v58_authenticates_current_runtime_closure",
    "tests/test_release_workflow_transition_v58.py::test_release_v58_rejects_transition_or_predecessor_tamper[False]",
    "tests/test_release_workflow_transition_v58.py::test_release_v58_rejects_transition_or_predecessor_tamper[True]",
    "tests/test_release_workflow_transition_v58.py::test_release_v58_rejects_linked_transition",
    "tests/test_release_workflow_transition_v59.py::test_release_v59_authenticates_current_runtime_closure",
    "tests/test_release_workflow_transition_v59.py::test_release_v59_rejects_transition_or_predecessor_tamper[False]",
    "tests/test_release_workflow_transition_v59.py::test_release_v59_rejects_transition_or_predecessor_tamper[True]",
    "tests/test_release_workflow_transition_v59.py::test_release_v59_rejects_linked_transition",
    "tests/test_release_workflow_transition_v60.py::test_release_v60_authenticates_current_runtime_closure",
    "tests/test_release_workflow_transition_v60.py::test_release_v60_rejects_transition_or_predecessor_tamper[False]",
    "tests/test_release_workflow_transition_v60.py::test_release_v60_rejects_transition_or_predecessor_tamper[True]",
    "tests/test_release_workflow_transition_v60.py::test_release_v60_rejects_linked_transition",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.current-successor-retirement.v21",
        "issued_at": "2026-08-24T15:45:00-04:00",
        "predecessor": {
            "path": PREDECESSOR,
            "sha256": _sha256(root / PREDECESSOR),
        },
        "policy": {
            "historical_tests_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_sources_are_sha256_bound": True,
            "successor_tests_must_execute": True,
            "exact_nodeids_only": True,
            "v21_precedes_v20_on_overlap": True,
        },
        "additional_claims": [
            {
                "id": "release-v57-v60-to-v61-current-authority",
                "disposition": "superseded-not-rebound",
                "historical_test_ids": list(HISTORICAL_TEST_IDS),
                "successor_tests": [
                    {"path": SUCCESSOR, "sha256": _sha256(root / SUCCESSOR)}
                ],
                "validated_tests": len(HISTORICAL_TEST_IDS),
                "reason": (
                    "V61 is the current additive release authority; V57-V60 "
                    "remain immutable historical predecessors."
                ),
            }
        ],
    }


def main() -> None:
    OUTPUT.write_text(
        json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("CURRENT_SUCCESSOR_RETIREMENT_V21_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
