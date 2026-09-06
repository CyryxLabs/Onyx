"""Generate V64 to V65 release-test retirement over immutable V23."""

import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V24.json"
PREDECESSOR = "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V23.json"
SUCCESSOR = "tests/test_release_workflow_transition_v65.py"
HISTORICAL_TEST_IDS = (
    "tests/test_release_workflow_transition_v64.py::test_release_v64_authenticates_corrected_current_authority",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.current-successor-retirement.v24",
        "issued_at": "2026-08-24T18:00:00-04:00",
        "predecessor": {"path": PREDECESSOR, "sha256": _sha256(root / PREDECESSOR)},
        "policy": {
            "historical_tests_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_sources_are_sha256_bound": True,
            "successor_tests_must_execute": True,
            "exact_nodeids_only": True,
            "v24_precedes_v23_on_overlap": True,
        },
        "additional_claims": [{
            "id": "release-v64-to-v65-current-hud-accessibility-authority",
            "disposition": "superseded-not-rebound",
            "historical_test_ids": list(HISTORICAL_TEST_IDS),
            "successor_tests": [{"path": SUCCESSOR, "sha256": _sha256(root / SUCCESSOR)}],
            "validated_tests": 1,
            "reason": "V65 binds the corrected current HUD accessibility invariant while V64 remains immutable.",
        }],
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("CURRENT_SUCCESSOR_RETIREMENT_V24_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
