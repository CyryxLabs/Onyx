from pathlib import Path
from scripts import verify_current_successor_retirement_v30 as verifier
from scripts.generate_current_successor_retirement_v30 import HISTORICAL_TEST_IDS

ROOT = Path(__file__).resolve().parents[1]


def test_v30_converges_recursive_release_documentation_claim_to_v71():
    assert set(HISTORICAL_TEST_IDS) <= verifier.registered_test_ids(ROOT)
    assert len(verifier.registered_test_ids(ROOT)) == 416
