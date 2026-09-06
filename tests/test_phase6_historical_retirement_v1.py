from pathlib import Path

import pytest

from scripts import verify_phase6_current_v1 as current
from scripts import verify_phase6_historical_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_NODE = (
    "tests/test_phase6_exit_candidate_v1.py::"
    "test_every_evidence_root_is_unique_and_rehashes"
)


def test_retirement_authenticates_exact_nodes_sources_and_successor() -> None:
    ledger = retirement.load_retirement_ledger(ROOT)
    registered = retirement.registered_test_ids(ROOT)
    binding = retirement.successor_binding(
        EXAMPLE_NODE,
        successor_contract=current.ACCEPTANCE_ID,
        successor_verifier="scripts.verify_phase6_current_v1",
        successor_marker=current.MARKER,
        project=ROOT,
    )
    assert ledger["counts"]["retired_nodes"] == 45
    assert len(registered) == 45
    assert binding["historical_test_id"] == EXAMPLE_NODE
    assert binding["disposition"].endswith("-not-rebound")


def test_retirement_rejects_unregistered_or_missing_collected_node() -> None:
    with pytest.raises(
        retirement.Phase6HistoricalRetirementV1Error,
        match="lacks exact retirement",
    ):
        retirement.successor_binding(
            "tests/test_phase6_exit_candidate_v1.py::not_registered",
            successor_contract=current.ACCEPTANCE_ID,
            successor_verifier="scripts.verify_phase6_current_v1",
            successor_marker=current.MARKER,
            project=ROOT,
        )
    with pytest.raises(
        retirement.Phase6HistoricalRetirementV1Error,
        match="no longer collected",
    ):
        retirement.require_registered_tests_collected(
            (),
            covered_sources=("tests/test_phase6_exit_candidate_v1.py",),
            project=ROOT,
        )


def test_retirement_ledger_digest_is_external(tmp_path: Path) -> None:
    ledger = tmp_path / retirement.LEDGER
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes((ROOT / retirement.LEDGER).read_bytes() + b" ")
    with pytest.raises(
        retirement.Phase6HistoricalRetirementV1Error,
        match="ledger digest drifted",
    ):
        retirement.load_retirement_ledger(tmp_path)
