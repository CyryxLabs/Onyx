from pathlib import Path

from scripts import verify_current_successor_retirement_v25 as verifier
from scripts.generate_current_successor_retirement_v25 import HUD_TEST_IDS, RELEASE_TEST_IDS

ROOT = Path(__file__).resolve().parents[1]


def test_v25_closes_release_and_hud_retirement_gaps() -> None:
    assert set(RELEASE_TEST_IDS) | set(HUD_TEST_IDS) <= verifier.registered_test_ids(ROOT)
    assert len(verifier.registered_test_ids(ROOT)) == 411
