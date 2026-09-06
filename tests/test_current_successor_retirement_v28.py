from pathlib import Path

from scripts import verify_current_successor_retirement_v28 as verifier
from scripts.generate_current_successor_retirement_v28 import HISTORICAL_TEST_IDS

ROOT = Path(__file__).resolve().parents[1]


def test_v28_converges_recursive_phase5_claim_to_v69() -> None:
    assert set(HISTORICAL_TEST_IDS) <= verifier.registered_test_ids(ROOT)
    assert len(verifier.registered_test_ids(ROOT)) == 414
