"""Focused and adversarial tests for the Phase 10 audience/strategy V1."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import phase10_audience_strategy_v1 as mod

PROJECT = Path(__file__).resolve().parents[1]


def _claim(claim_id="c1", source="report#2026-08", platform="instagram"):
    return {"claim_id": claim_id, "claim_text": "audience grew",
            "source_ref": source, "platform": platform}


def _segment(segment_id="seg1", brand="cyryx_labs", platform="instagram",
             claims=None):
    return {
        "segment_id": segment_id, "brand_id": brand, "platform": platform,
        "description": "founders 25-40",
        "claims": [_claim()] if claims is None else claims,
    }


def _kpi(kpi_id="k1", platform="instagram", metric="follower_growth",
         target=1000, horizon=30):
    return {"kpi_id": kpi_id, "platform": platform, "metric": metric,
            "target_value": target, "horizon_days": horizon}


def _stage(stage_id="awareness", order=1, kpis=("k1",)):
    return {"stage_id": stage_id, "order": order, "kpi_ids": list(kpis)}


def _plan(plan_id="p1", brand="cyryx_labs", g30=("post 3x week",),
          g60=("reach 10k",), g90=("launch series",)):
    return {"plan_id": plan_id, "brand_id": brand, "goals_30": list(g30),
            "goals_60": list(g60), "goals_90": list(g90)}


def _experiment(experiment_id="e1", min_sample=100, observed=250,
                winner=False, platform="instagram"):
    return {"experiment_id": experiment_id, "hypothesis": "carousels win",
            "platform": platform, "min_sample": min_sample,
            "observed_sample": observed, "winner_declared": winner}


def _payload(segments=None, kpis=None, funnel=None, plans=None,
             experiments=None):
    return {
        "segments": [_segment()] if segments is None else list(segments),
        "kpis": [_kpi()] if kpis is None else list(kpis),
        "funnel": [_stage()] if funnel is None else list(funnel),
        "plans": [_plan()] if plans is None else list(plans),
        "experiments": ([_experiment()] if experiments is None
                        else list(experiments)),
    }


def _set():
    return mod.create_audience_strategy_set_v1(PROJECT)


# ── feature gate + entry-bind ───────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.AudienceStrategyFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on():
    assert mod.AudienceStrategyFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}).enabled is True


def test_entry_bind_passes_real_project():
    assert isinstance(_set(), mod.AudienceStrategySetV1)


def test_entry_bind_denied_when_absent(tmp_path):
    with pytest.raises(mod.AudienceStrategyV1Denied):
        mod.create_audience_strategy_set_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        mod.AudienceStrategySetV1(construction_key=object())


# ── happy path ──────────────────────────────────────────────────────────────

def test_builds_full_strategy_snapshot():
    snap = _set().build(_payload())
    assert snap.segments[0].claims[0].source_ref == "report#2026-08"
    assert snap.kpis[0].horizon_days == 30
    assert snap.funnel[0].order == 1
    assert snap.plans[0].goals_90 == ("launch series",)


def test_funnel_sorted_by_order():
    snap = _set().build(_payload(funnel=[
        _stage("conversion", 3), _stage("awareness", 1),
        _stage("engagement", 2)]))
    assert [s.stage_id for s in snap.funnel] == [
        "awareness", "engagement", "conversion"]


def test_winner_with_adequate_sample_supported():
    dataset = _set()
    dataset.build(_payload(experiments=[
        _experiment(min_sample=100, observed=500, winner=True)]))
    assert dataset.is_winner_supported("e1") is True


def test_no_winner_is_not_supported():
    dataset = _set()
    dataset.build(_payload(experiments=[
        _experiment(min_sample=100, observed=500, winner=False)]))
    assert dataset.is_winner_supported("e1") is False
    assert dataset.is_winner_supported("ghost") is False


# ── anti-fabrication gates ──────────────────────────────────────────────────

def test_claim_without_source_rejected():
    bad = _claim()
    bad["source_ref"] = ""
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(segments=[_segment(claims=[bad])]))


def test_segment_without_claims_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(segments=[_segment(claims=[])]))


def test_duplicate_claim_in_segment_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(segments=[
            _segment(claims=[_claim("dup"), _claim("dup")])]))


def test_unknown_segment_platform_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(segments=[_segment(platform="myspace")]))


# ── 30/60/90 cadence ────────────────────────────────────────────────────────

def test_missing_horizon_key_rejected():
    bad = _plan()
    del bad["goals_60"]
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(plans=[bad]))


def test_empty_horizon_goals_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(plans=[_plan(g60=())]))


def test_extra_plan_key_rejected():
    bad = _plan()
    bad["goals_120"] = ["moon"]
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(plans=[bad]))


# ── per-platform KPIs + funnel ──────────────────────────────────────────────

def test_kpi_bad_horizon_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(kpis=[_kpi(horizon=45)]))


def test_kpi_unknown_platform_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(kpis=[_kpi(platform="broadcast")]))


def test_kpi_negative_target_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(kpis=[_kpi(target=-1)]))


def test_funnel_unknown_kpi_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(funnel=[_stage(kpis=("ghost",))]))


def test_duplicate_funnel_order_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(funnel=[
            _stage("a", 1), _stage("b", 1, kpis=("k1",))]))


def test_duplicate_kpi_in_stage_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(funnel=[_stage(kpis=("k1", "k1"))]))


# ── experiment sample floor ─────────────────────────────────────────────────

def test_winner_from_inadequate_sample_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(experiments=[
            _experiment(min_sample=100, observed=99, winner=True)]))


def test_min_sample_below_floor_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(experiments=[
            _experiment(min_sample=mod.EXPERIMENT_MIN_SAMPLE_FLOOR - 1)]))


def test_non_bool_winner_rejected():
    bad = _experiment()
    bad["winner_declared"] = 1
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(experiments=[bad]))


def test_running_experiment_below_min_allowed_without_winner():
    snap = _set().build(_payload(experiments=[
        _experiment(min_sample=100, observed=10, winner=False)]))
    assert snap.experiments[0].observed_sample == 10


# ── structural rejections ───────────────────────────────────────────────────

def test_duplicate_segment_id_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(segments=[_segment("dup"), _segment("dup")]))


def test_duplicate_kpi_id_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(kpis=[_kpi("dup"), _kpi("dup")]))


def test_duplicate_experiment_id_rejected():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(experiments=[
            _experiment("dup"), _experiment("dup")]))


def test_payload_keys_contract_enforced():
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build({"segments": []})


def test_segment_keys_contract_enforced():
    bad = _segment()
    del bad["description"]
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(segments=[bad]))


@pytest.mark.parametrize("value", ["", "a\x00b", 5, None])
def test_segment_id_text_rejections(value):
    bad = _segment()
    bad["segment_id"] = value
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(segments=[bad]))


def test_item_cap_enforced():
    too_many = [_kpi(f"k{i}") for i in range(mod.MAX_ITEMS + 1)]
    with pytest.raises(mod.AudienceStrategyV1ContractError):
        _set().build(_payload(kpis=too_many))


def test_no_action_surface():
    dataset = _set()
    for name in ("publish", "post", "schedule", "dispatch", "execute"):
        assert not hasattr(dataset, name)
