from __future__ import annotations

from pathlib import Path

import pytest

from core.phase9_opportunity_scoring_v1 import (
    DIMENSION_NAMES,
    DIMENSIONS,
    FEATURE_FLAG,
    MAX_ID_BYTES,
    MAX_ITEMS,
    MAX_TITLE_BYTES,
    SCORE_MAX,
    OpportunityScoringFeatureGateV1,
    OpportunityScoringV1ContractError,
    OpportunityScoringV1Denied,
    _band,
    create_opportunity_scoring_v1,
)

ROOT = Path(__file__).resolve().parents[1]
_COST = {name for name, _w, is_cost in DIMENSIONS if is_cost}
# Direction and weights pinned INDEPENDENTLY of the DIMENSIONS tuple, so a
# flipped is_cost flag or a swapped weight cannot mutate the oracle in lockstep.
_EXPECTED_COST = {
    "competition",
    "time_to_mvp_revenue",
    "complexity",
    "legal_platform_risk",
}
_EXPECTED_WEIGHTS = {
    "pain_economic_cost": 3,
    "urgency": 2,
    "buyer_payability": 3,
    "timing": 2,
    "competition": 2,
    "cyryx_advantage": 3,
    "time_to_mvp_revenue": 2,
    "complexity": 2,
    "distribution": 2,
    "moat": 2,
    "legal_platform_risk": 2,
    "evidence_confidence": 3,
}


def _session():
    return create_opportunity_scoring_v1(
        gate=OpportunityScoringFeatureGateV1(True), project_root=ROOT
    )


def _scores(value: int) -> dict[str, int]:
    return {name: value for name in DIMENSION_NAMES}


def _ideal() -> dict[str, int]:
    # benefits max, costs min -> perfect opportunity.
    return {name: (0 if name in _COST else SCORE_MAX) for name in DIMENSION_NAMES}


def _item(scores: dict[str, int], *, opportunity_id: str = "a", title: str = "Opp") -> dict:
    return {"opportunity_id": opportunity_id, "title": title, "scores": scores}


def test_feature_gate_is_exact_and_default_off() -> None:
    assert not OpportunityScoringFeatureGateV1.from_environ({}).enabled
    assert OpportunityScoringFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "yes", "True"):
        assert not OpportunityScoringFeatureGateV1.from_environ(
            {FEATURE_FLAG: value}
        ).enabled
    assert (
        create_opportunity_scoring_v1(
            gate=OpportunityScoringFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


def test_factory_is_sealed_and_entry_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(OpportunityScoringV1ContractError, match="sealed feature gate"):
        create_opportunity_scoring_v1(gate=True)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "core.phase9_opportunity_scoring_v1.ACCEPTED_INGESTION_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(OpportunityScoringV1Denied, match="evidence unavailable"):
        create_opportunity_scoring_v1(
            gate=OpportunityScoringFeatureGateV1(True), project_root=ROOT
        )


def test_entry_bind_detects_evidence_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.phase9_opportunity_scoring_v1.ACCEPTED_INGESTION_ROOTS",
        (("docs/onyx/checkpoints/phase9-intelligence-ingestion-v1/manifest.json", "0" * 64),),
    )
    with pytest.raises(OpportunityScoringV1Denied, match="evidence drift"):
        create_opportunity_scoring_v1(
            gate=OpportunityScoringFeatureGateV1(True), project_root=ROOT
        )


def test_perfect_and_worst_scores() -> None:
    session = _session()
    assert session is not None
    best = session.score(_item(_ideal()))
    assert best.total_score == 100 and best.band == "priority" and best.rank == 1
    worst = session.score(
        _item({name: (SCORE_MAX if name in _COST else 0) for name in DIMENSION_NAMES})
    )
    assert worst.total_score == 0 and worst.band == "watch"


def test_cost_dimensions_are_inverted() -> None:
    session = _session()
    assert session is not None
    base = session.score(_item(_scores(3)))
    worse_risk = dict(_scores(3))
    worse_risk["legal_platform_risk"] = SCORE_MAX
    better_risk = dict(_scores(3))
    better_risk["legal_platform_risk"] = 0
    assert session.score(_item(better_risk)).total_score > base.total_score
    assert session.score(_item(worse_risk)).total_score < base.total_score
    # a cost dimension's effective value is the inverse of its raw score.
    dim = {d.name: d for d in session.score(_item(worse_risk)).dimensions}[
        "legal_platform_risk"
    ]
    assert dim.raw == SCORE_MAX and dim.effective == 0 and dim.points == 0


def test_breakdown_is_transparent_and_totals_reconcile() -> None:
    session = _session()
    assert session is not None
    result = session.score(_item(_scores(4)))
    assert tuple(d.name for d in result.dimensions) == DIMENSION_NAMES
    max_points = sum(d.max_points for d in result.dimensions)
    earned = sum(d.points for d in result.dimensions)
    assert max_points == 140
    assert result.total_score == (earned * 100 + max_points // 2) // max_points
    for d in result.dimensions:
        expected_effective = (SCORE_MAX - d.raw) if d.is_cost else d.raw
        assert d.effective == expected_effective
        assert d.points == d.weight * d.effective
        assert d.max_points == d.weight * SCORE_MAX


def test_bands_cover_all_four_levels() -> None:
    session = _session()
    assert session is not None
    # uniform raw v -> earned 12v+40 over 140; _ideal() -> 100.
    assert session.score(_item(_scores(1))).band == "watch"  # total 37
    assert session.score(_item(_scores(3))).band == "consider"  # total 54
    assert session.score(_item(_scores(5))).band == "pursue"  # total 71
    assert session.score(_item(_ideal())).band == "priority"  # total 100


def test_band_thresholds_are_exact_at_boundaries() -> None:
    # pin the ladder at each boundary so a >= -> > shift is caught.
    assert _band(0) == "watch"
    assert _band(39) == "watch"
    assert _band(40) == "consider"
    assert _band(59) == "consider"
    assert _band(60) == "pursue"
    assert _band(79) == "pursue"
    assert _band(80) == "priority"
    assert _band(100) == "priority"


def test_dimension_directions_and_weights_are_pinned() -> None:
    session = _session()
    assert session is not None
    cost = {name for name, _w, is_cost in DIMENSIONS if is_cost}
    benefit = {name for name, _w, is_cost in DIMENSIONS if not is_cost}
    assert cost == _EXPECTED_COST
    assert benefit == set(DIMENSION_NAMES) - _EXPECTED_COST
    assert {name: weight for name, weight, _c in DIMENSIONS} == _EXPECTED_WEIGHTS
    # each cost dimension independently: raising raw risk lowers the total.
    for dim in _EXPECTED_COST:
        low = _scores(3)
        low[dim] = 0
        high = _scores(3)
        high[dim] = 5
        assert (
            session.score(_item(low)).total_score
            > session.score(_item(high)).total_score
        )
    # each benefit dimension independently: raising raw raises the total.
    for dim in set(DIMENSION_NAMES) - _EXPECTED_COST:
        low = _scores(3)
        low[dim] = 0
        high = _scores(3)
        high[dim] = 5
        assert (
            session.score(_item(high)).total_score
            > session.score(_item(low)).total_score
        )


def test_low_confidence_flag() -> None:
    session = _session()
    assert session is not None
    low = dict(_ideal())
    low["evidence_confidence"] = 1
    assert session.score(_item(low)).low_confidence is True
    ok = dict(_ideal())
    ok["evidence_confidence"] = 2
    assert session.score(_item(ok)).low_confidence is False


def test_batch_ranks_by_total_then_id() -> None:
    session = _session()
    assert session is not None
    strong = _item(_ideal(), opportunity_id="strong")
    weak = _item(_scores(1), opportunity_id="weak")
    # two items with the same total tie-break by opportunity_id ascending.
    tie_b = _item(_scores(3), opportunity_id="b")
    tie_a = _item(_scores(3), opportunity_id="a")
    results = session.score_batch([weak, tie_b, strong, tie_a])
    rank_by_id = {r.opportunity_id: r.rank for r in results}
    assert rank_by_id["strong"] == 1
    assert rank_by_id["a"] < rank_by_id["b"]  # equal totals -> id order
    assert rank_by_id["weak"] == 4
    # results are returned in input order.
    assert [r.opportunity_id for r in results] == ["weak", "b", "strong", "a"]


def test_batch_rejects_duplicates_and_oversize() -> None:
    session = _session()
    assert session is not None
    with pytest.raises(OpportunityScoringV1ContractError, match="duplicate opportunity_id"):
        session.score_batch([_item(_scores(3), opportunity_id="x"), _item(_scores(4), opportunity_id="x")])
    with pytest.raises(OpportunityScoringV1ContractError, match="batch is invalid"):
        session.score_batch("notalist")
    with pytest.raises(OpportunityScoringV1ContractError, match="batch is invalid"):
        session.score_batch([_item(_scores(3), opportunity_id=str(i)) for i in range(MAX_ITEMS + 1)])


def test_rejects_malformed_scores() -> None:
    session = _session()
    assert session is not None
    with pytest.raises(OpportunityScoringV1ContractError, match="item must be an object"):
        session.score("notdict")
    with pytest.raises(OpportunityScoringV1ContractError, match="scores must be an object"):
        session.score({"opportunity_id": "a", "title": "t", "scores": "no"})
    missing = _scores(3)
    del missing["urgency"]
    with pytest.raises(OpportunityScoringV1ContractError, match="cover every dimension"):
        session.score(_item(missing))
    extra = _scores(3)
    extra["made_up"] = 3
    with pytest.raises(OpportunityScoringV1ContractError, match="cover every dimension"):
        session.score(_item(extra))
    for bad in (-1, SCORE_MAX + 1):
        rng = _scores(3)
        rng["moat"] = bad
        with pytest.raises(OpportunityScoringV1ContractError, match="out of range"):
            session.score(_item(rng))
    boolean = _scores(3)
    boolean["moat"] = True  # bool must be rejected despite being an int subclass
    with pytest.raises(OpportunityScoringV1ContractError, match="out of range"):
        session.score(_item(boolean))
    nonint = _scores(3)
    nonint["moat"] = 3.0
    with pytest.raises(OpportunityScoringV1ContractError, match="out of range"):
        session.score(_item(nonint))
    with pytest.raises(OpportunityScoringV1ContractError, match="opportunity_id"):
        session.score(_item(_scores(3), opportunity_id=""))
    with pytest.raises(OpportunityScoringV1ContractError, match="title"):
        session.score({"opportunity_id": "a", "title": "x\x00y", "scores": _scores(3)})
    # non-str and oversize id/title reject on the _text type and byte-length guards.
    with pytest.raises(OpportunityScoringV1ContractError, match="opportunity_id"):
        session.score({"opportunity_id": 123, "title": "t", "scores": _scores(3)})
    with pytest.raises(OpportunityScoringV1ContractError, match="opportunity_id"):
        session.score(_item(_scores(3), opportunity_id="x" * (MAX_ID_BYTES + 1)))
    with pytest.raises(OpportunityScoringV1ContractError, match="title"):
        session.score(
            {"opportunity_id": "a", "title": "t" * (MAX_TITLE_BYTES + 1), "scores": _scores(3)}
        )


def test_deterministic_and_dimensions_invariant() -> None:
    session = _session()
    assert session is not None
    item = _item(_scores(3))
    assert session.score(item) == session.score(item)
    assert len(DIMENSIONS) == 12
    assert len(set(DIMENSION_NAMES)) == 12
    assert all(weight > 0 for _n, weight, _c in DIMENSIONS)


def test_source_has_no_network_model_or_action() -> None:
    source = (ROOT / "core" / "phase9_opportunity_scoring_v1.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "import requests",
        "urllib.request",
        "http",
        "socket",
        "subprocess",
        "llm",
        "openai",
        "dispatch(",
        "def buy",
        "def sell",
        "def trade",
    ):
        assert forbidden not in source, forbidden
