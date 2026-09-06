from pathlib import Path

from scripts import generate_advanced_operations_successor_retirement_v2 as generator
from scripts import verify_advanced_operations_successor_retirement_v2 as verifier


ROOT = Path(__file__).resolve().parents[1]


def test_v2_retirement_is_exact_and_reproducible() -> None:
    assert verifier.load_record(ROOT) == generator.build(ROOT)


def test_v2_retirement_registers_exact_historical_nodes() -> None:
    assert verifier.registered_test_ids(ROOT) == frozenset(generator.HISTORICAL_TEST_IDS)
