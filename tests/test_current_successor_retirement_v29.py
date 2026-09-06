from pathlib import Path

from scripts import verify_current_successor_retirement_v29 as verifier
from scripts.generate_current_successor_retirement_v29 import HISTORICAL_TEST_IDS

ROOT = Path(__file__).resolve().parents[1]


def test_v29_converges_recursive_v48_freezer_claim_to_v70() -> None:
    assert set(HISTORICAL_TEST_IDS) <= verifier.registered_test_ids(ROOT)
    assert len(verifier.registered_test_ids(ROOT)) == 415
