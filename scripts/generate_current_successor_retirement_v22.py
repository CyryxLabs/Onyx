"""Generate V61 to V63 release-test retirement over immutable V21."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V22.json"
PREDECESSOR = "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V21.json"
SUCCESSOR = "tests/test_release_workflow_transition_v63.py"
HISTORICAL_TEST_IDS = (
    "tests/test_release_workflow_transition_v61.py::test_release_v61_authenticates_current_runtime_closure",
    "tests/test_release_workflow_transition_v61.py::test_release_v61_rejects_transition_or_predecessor_tamper[False]",
    "tests/test_release_workflow_transition_v61.py::test_release_v61_rejects_transition_or_predecessor_tamper[True]",
    "tests/test_release_workflow_transition_v61.py::test_release_v61_rejects_linked_transition",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.current-successor-retirement.v22",
        "issued_at": "2026-08-24T16:30:00-04:00",
        "predecessor": {"path": PREDECESSOR, "sha256": _sha256(root / PREDECESSOR)},
        "policy": {
            "historical_tests_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_sources_are_sha256_bound": True,
            "successor_tests_must_execute": True,
            "exact_nodeids_only": True,
            "v22_precedes_v21_on_overlap": True,
        },
        "additional_claims": [{
            "id": "release-v61-to-v63-converged-current-authority",
            "disposition": "superseded-not-rebound",
            "historical_test_ids": list(HISTORICAL_TEST_IDS),
            "successor_tests": [{"path": SUCCESSOR, "sha256": _sha256(root / SUCCESSOR)}],
            "validated_tests": len(HISTORICAL_TEST_IDS),
            "reason": "V63 converges current build and retirement wiring while V61 and V62 remain immutable predecessors.",
        }],
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("CURRENT_SUCCESSOR_RETIREMENT_V22_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
