from pathlib import Path

from scripts import verify_current_successor_retirement_v26 as verifier
from scripts.generate_current_successor_retirement_v26 import HISTORICAL_TEST_IDS

ROOT = Path(__file__).resolve().parents[1]


def test_v26_binds_bounded_successor_execution_budget() -> None:
    assert set(HISTORICAL_TEST_IDS) <= verifier.registered_test_ids(ROOT)
    assert len(verifier.registered_test_ids(ROOT)) == 412
    assert "timeout=900" in (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
