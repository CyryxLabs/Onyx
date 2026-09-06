from pathlib import Path

from scripts import verify_current_successor_retirement_v22 as verifier
from scripts.generate_current_successor_retirement_v22 import HISTORICAL_TEST_IDS


ROOT = Path(__file__).resolve().parents[1]


def test_v22_converges_v61_routes_to_v63() -> None:
    assert set(HISTORICAL_TEST_IDS) <= verifier.registered_test_ids(ROOT)
    assert len(verifier.registered_test_ids(ROOT)) == 399
