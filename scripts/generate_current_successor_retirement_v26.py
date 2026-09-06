"""Retire Release V66 to bounded-execution Release V67 over immutable V25."""

import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V26.json"
PREDECESSOR = "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V25.json"
SUCCESSOR = "tests/test_release_workflow_transition_v67.py"
HISTORICAL_TEST_IDS = (
    "tests/test_release_workflow_transition_v66.py::test_release_v66_authenticates_complete_current_hud_retirement",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.current-successor-retirement.v26",
        "issued_at": "2026-08-24T21:45:00-04:00",
        "predecessor": {"path": PREDECESSOR, "sha256": _sha256(root / PREDECESSOR)},
        "policy": {
            "historical_tests_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_sources_are_sha256_bound": True,
            "successor_tests_must_execute": True,
            "exact_nodeids_only": True,
            "v26_precedes_v25_on_overlap": True,
            "successor_timeout_seconds": 900,
        },
        "additional_claims": [{
            "id": "release-v66-to-v67-bounded-successor-execution",
            "disposition": "superseded-not-rebound",
            "historical_test_ids": list(HISTORICAL_TEST_IDS),
            "successor_tests": [{"path": SUCCESSOR, "sha256": _sha256(root / SUCCESSOR)}],
            "validated_tests": 1,
            "reason": "V67 retains fail-closed execution with a 900-second budget for the authenticated additive lineage.",
        }],
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("CURRENT_SUCCESSOR_RETIREMENT_V26_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
