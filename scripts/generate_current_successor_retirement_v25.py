"""Retire Release V65 and stale HUD V34/V35 nodes over immutable V24."""

import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V25.json"
PREDECESSOR = "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V24.json"
RELEASE_SUCCESSOR = "tests/test_release_workflow_transition_v66.py"
HUD_SUCCESSOR = "tests/test_onyx_hud_current_acceptance_v36.py"
RELEASE_TEST_IDS = (
    "tests/test_release_workflow_transition_v65.py::test_release_v65_authenticates_current_hud_accessibility_authority",
)
HUD_TEST_IDS = (
    "tests/test_onyx_hud_current_acceptance_v34.py::test_v34_authenticates_exact_current_capabilities_and_package_hygiene",
    "tests/test_onyx_hud_current_acceptance_v34.py::test_v34_rejects_current_or_predecessor_tamper[relative0]",
    "tests/test_onyx_hud_current_acceptance_v34.py::test_v34_rejects_current_or_predecessor_tamper[relative1]",
    "tests/test_onyx_hud_current_acceptance_v34.py::test_v34_rejects_current_or_predecessor_tamper[relative2]",
    "tests/test_onyx_hud_current_acceptance_v34.py::test_v34_rejects_linked_capability_input",
    "tests/test_onyx_hud_current_acceptance_v35.py::test_v35_authenticates_v4_current_runtime",
    "tests/test_onyx_hud_current_acceptance_v35.py::test_v35_rejects_current_or_predecessor_tamper[relative0]",
    "tests/test_onyx_hud_current_acceptance_v35.py::test_v35_rejects_current_or_predecessor_tamper[relative1]",
    "tests/test_onyx_hud_current_acceptance_v35.py::test_v35_rejects_current_or_predecessor_tamper[relative2]",
    "tests/test_onyx_hud_current_acceptance_v35.py::test_v35_rejects_linked_v4_input",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.current-successor-retirement.v25",
        "issued_at": "2026-08-24T19:00:00-04:00",
        "predecessor": {"path": PREDECESSOR, "sha256": _sha256(root / PREDECESSOR)},
        "policy": {
            "historical_tests_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_sources_are_sha256_bound": True,
            "successor_tests_must_execute": True,
            "exact_nodeids_only": True,
            "v25_precedes_v24_on_overlap": True,
        },
        "additional_claims": [
            {
                "id": "release-v65-to-v66-complete-hud-retirement",
                "disposition": "superseded-not-rebound",
                "historical_test_ids": list(RELEASE_TEST_IDS),
                "successor_tests": [{"path": RELEASE_SUCCESSOR, "sha256": _sha256(root / RELEASE_SUCCESSOR)}],
                "validated_tests": 1,
                "reason": "V66 binds the complete current HUD retirement while V65 remains immutable.",
            },
            {
                "id": "hud-v34-v35-to-v36-complete-current-acceptance",
                "disposition": "superseded-not-rebound",
                "historical_test_ids": list(HUD_TEST_IDS),
                "successor_tests": [{"path": HUD_SUCCESSOR, "sha256": _sha256(root / HUD_SUCCESSOR)}],
                "validated_tests": len(HUD_TEST_IDS),
                "reason": "Frozen V34/V35 source checks are superseded by authenticated living liquid-metal HUD V36.",
            },
        ],
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("CURRENT_SUCCESSOR_RETIREMENT_V25_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
