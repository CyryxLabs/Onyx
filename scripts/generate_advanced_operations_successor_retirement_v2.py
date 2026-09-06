"""Generate retirement binding from mutable V22 tests to V23 authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/ADVANCED_OPERATIONS_SUCCESSOR_RETIREMENT_V2.json"
PREDECESSOR = "docs/onyx/acceptance/VE-ADVANCED-OPS-V22-001.manifest.json"
SUCCESSOR = "tests/test_advanced_operations_source_acceptance_v23.py"
HISTORICAL_TEST_IDS = (
    "tests/test_advanced_operations_source_acceptance_v22.py::test_v22_is_reproducible_exact_and_append_only",
    "tests/test_advanced_operations_source_acceptance_v22.py::test_v22_rejects_selection_scope_reduction",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.advanced-operations-successor-retirement.v2",
        "issued_at": "2026-08-24T15:30:00-04:00",
        "predecessor": {"path": PREDECESSOR, "sha256": _sha256(root / PREDECESSOR)},
        "policy": {
            "historical_manifests_are_immutable": True,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_test_is_sha256_bound": True,
        },
        "historical_test_ids": list(HISTORICAL_TEST_IDS),
        "successor_test": {"path": SUCCESSOR, "sha256": _sha256(root / SUCCESSOR)},
    }


def main() -> None:
    OUTPUT.write_text(
        json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("ADVANCED_OPERATIONS_SUCCESSOR_RETIREMENT_V2_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
