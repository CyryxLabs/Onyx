from pathlib import Path

from scripts import generate_current_successor_retirement_v21 as generator
from scripts import verify_current_successor_retirement_v21 as verifier


ROOT = Path(__file__).resolve().parents[1]


def test_v21_retirement_is_exact_and_reproducible() -> None:
    assert verifier._claim(ROOT) == generator.build(ROOT)["additional_claims"][0]


def test_v21_registers_all_release_v57_v60_nodes() -> None:
    registered = verifier.registered_test_ids(ROOT)
    assert set(generator.HISTORICAL_TEST_IDS) <= registered
    assert len(registered) == 395
