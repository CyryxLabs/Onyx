"""Retire Release V67 to packaged-smoke Release V68 over immutable V26."""

import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V27.json"
PREDECESSOR = "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V26.json"
SUCCESSOR = "tests/test_release_workflow_transition_v68.py"
HISTORICAL_TEST_IDS = (
    "tests/test_release_workflow_transition_v67.py::test_release_v67_authenticates_bounded_successor_execution_budget",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.current-successor-retirement.v27",
        "issued_at": "2026-08-25T00:20:00-04:00",
        "predecessor": {"path": PREDECESSOR, "sha256": _sha256(root / PREDECESSOR)},
        "policy": {
            "historical_tests_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_sources_are_sha256_bound": True,
            "successor_tests_must_execute": True,
            "exact_nodeids_only": True,
            "v27_precedes_v26_on_overlap": True,
        },
        "additional_claims": [{
            "id": "release-v67-to-v68-current-packaged-hud-smoke",
            "disposition": "superseded-not-rebound",
            "historical_test_ids": list(HISTORICAL_TEST_IDS),
            "successor_tests": [{"path": SUCCESSOR, "sha256": _sha256(root / SUCCESSOR)}],
            "validated_tests": 1,
            "reason": "V68 binds the current shell V12 and host V13 packaged smoke while V67 remains immutable.",
        }],
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("CURRENT_SUCCESSOR_RETIREMENT_V27_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
