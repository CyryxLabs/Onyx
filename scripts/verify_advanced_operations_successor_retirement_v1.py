"""Verify the append-only Advanced Operations V21 to V22 retirement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.generate_advanced_operations_successor_retirement_v1 import (
    HISTORICAL_TEST_IDS,
    PREDECESSOR,
    SUCCESSOR,
)


PROJECT = Path(__file__).resolve().parents[1]
RECORD = "docs/onyx/checkpoints/ADVANCED_OPERATIONS_SUCCESSOR_RETIREMENT_V1.json"


class AdvancedOperationsSuccessorRetirementV1Error(RuntimeError):
    """The Advanced Operations retirement binding drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_record(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / RECORD).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise AdvancedOperationsSuccessorRetirementV1Error("retirement is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AdvancedOperationsSuccessorRetirementV1Error("retirement is invalid") from error
    expected = {
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
    if record != expected:
        raise AdvancedOperationsSuccessorRetirementV1Error("retirement contract drifted")
    return record


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(load_record(project)["historical_test_ids"])


if __name__ == "__main__":
    print("ADVANCED_OPERATIONS_SUCCESSOR_RETIREMENT_V1_OK", f"tests={len(registered_test_ids())}")
