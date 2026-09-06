from __future__ import annotations

from pathlib import Path

from scripts import generate_advanced_operations_successor_retirement_v1 as generator
from scripts import verify_advanced_operations_successor_retirement_v1 as verifier


ROOT = Path(__file__).resolve().parents[1]


def test_retirement_is_reproducible_and_points_only_to_v22() -> None:
    record = verifier.load_record(ROOT)
    assert record == generator.build(ROOT)
    assert record["historical_test_ids"] == list(generator.HISTORICAL_TEST_IDS)
    assert record["successor_test"]["path"] == generator.SUCCESSOR
    assert "v1.py" not in record["successor_test"]["path"]
