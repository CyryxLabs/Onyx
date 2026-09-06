"""Generate retirement binding from mutable V21 tests to V22 authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "docs/onyx/checkpoints/ADVANCED_OPERATIONS_SUCCESSOR_RETIREMENT_V1.json"
PREDECESSOR = "docs/onyx/acceptance/VE-ADVANCED-OPS-V21-001.manifest.json"
SUCCESSOR = "tests/test_advanced_operations_source_acceptance_v22.py"
HISTORICAL_TEST_IDS = (
    "tests/test_advanced_operations_source_acceptance_v1.py::test_advanced_operations_source_manifest_authenticates_exact_files",
    "tests/test_advanced_operations_source_acceptance_v1.py::test_v21_preserves_exact_v20_source_manifest",
    "tests/test_advanced_operations_source_acceptance_v1.py::test_advanced_operations_source_policy_preserves_host_authority",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    return {
        "schema": "onyx.advanced-operations-successor-retirement.v1",
        "issued_at": "2026-08-23T17:00:00-04:00",
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
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("ADVANCED_OPERATIONS_SUCCESSOR_RETIREMENT_V1_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
