"""Converge the recursive V48 freezer claim over immutable V28."""

import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V29.json"
PREDECESSOR = "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V28.json"
SUCCESSOR = "tests/test_release_workflow_transition_v70.py"
HISTORICAL_TEST_IDS = (
    "tests/test_release_workflow_transition_v69.py::test_release_v69_authenticates_converged_phase5_authority",
    "tests/test_freeze_release_source_v48.py::test_freezer_selects_exact_v48_current_authorities",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.current-successor-retirement.v29",
        "issued_at": "2026-08-25T03:30:00-04:00",
        "predecessor": {"path": PREDECESSOR, "sha256": _sha256(root / PREDECESSOR)},
        "policy": {
            "historical_tests_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_sources_are_sha256_bound": True,
            "successor_tests_must_execute": True,
            "exact_nodeids_only": True,
            "v29_precedes_v28_on_overlap": True,
            "recursive_successor_chains_are_converged": True,
        },
        "additional_claims": [
            {
                "id": "phase5-freeze-v48-and-release-v69-to-v70",
                "disposition": "superseded-not-rebound",
                "historical_test_ids": list(HISTORICAL_TEST_IDS),
                "successor_tests": [
                    {"path": SUCCESSOR, "sha256": _sha256(root / SUCCESSOR)}
                ],
                "validated_tests": len(HISTORICAL_TEST_IDS),
                "reason": "V70 converges the exact recursive V48 freezer node directly to current authority while the historical node remains collected.",
            }
        ],
    }


def main() -> None:
    OUTPUT.write_text(
        json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("CURRENT_SUCCESSOR_RETIREMENT_V29_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
