from pathlib import Path

from scripts import verify_current_successor_retirement_v27 as verifier
from scripts.generate_current_successor_retirement_v27 import HISTORICAL_TEST_IDS

ROOT = Path(__file__).resolve().parents[1]


def test_v27_binds_current_packaged_hud_smoke() -> None:
    assert set(HISTORICAL_TEST_IDS) <= verifier.registered_test_ids(ROOT)
    assert len(verifier.registered_test_ids(ROOT)) == 413
