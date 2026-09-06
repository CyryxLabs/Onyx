"""Focused and adversarial tests for the Argos world-intelligence V1."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import argos_v1 as mod

PROJECT = Path(__file__).resolve().parents[1]


def _source(source_id="src1", kind="press", rights="cited under fair use"):
    return {"source_id": source_id, "kind": kind,
            "origin": "example-news.test", "rights_note": rights}


def _signal(signal_id="sig1", category="markets", source="src1",
            severity=3, confidence=4, observed=1_750_000_000):
    return {"signal_id": signal_id, "category": category, "region": "global",
            "headline": "markets moved", "source_id": source,
            "observed_at": observed, "severity": severity,
            "confidence": confidence}


def _plan(sources=None, signals=None):
    return {
        "sources": [_source()] if sources is None else list(sources),
        "signals": [_signal()] if signals is None else list(signals),
    }


def _registry():
    return mod.create_argos_registry_v1(PROJECT)


# ── feature gate + entry-bind ───────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.ArgosFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on():
    assert mod.ArgosFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}).enabled is True


def test_entry_bind_passes_real_project():
    assert isinstance(_registry(), mod.ArgosRegistryV1)


def test_entry_bind_denied_when_absent(tmp_path):
    with pytest.raises(mod.ArgosV1Denied):
        mod.create_argos_registry_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.ArgosV1ContractError):
        mod.ArgosRegistryV1(construction_key=object())


# ── happy path + deterministic ranking ──────────────────────────────────────

def test_builds_sorted_snapshot():
    snap = _registry().build(_plan(signals=[
        _signal("z_sig"), _signal("a_sig")]))
    assert [s.signal_id for s in snap.signals] == ["a_sig", "z_sig"]
    assert snap.sources[0].rights_note == "cited under fair use"


def test_ranking_by_weight_then_id():
    registry = _registry()
    registry.build(_plan(signals=[
        _signal("low", severity=1, confidence=1),
        _signal("high", severity=5, confidence=5),
        _signal("mid_b", severity=3, confidence=3),
        _signal("mid_a", severity=3, confidence=3),
    ]))
    ranked = registry.signals_for("markets")
    assert [s.signal_id for s in ranked] == ["high", "mid_a", "mid_b", "low"]


def test_brief_limit_bounds():
    registry = _registry()
    registry.build(_plan(signals=[
        _signal(f"s{i}", severity=(i % 5) + 1) for i in range(10)]))
    assert len(registry.brief(3)) == 3
    with pytest.raises(mod.ArgosV1ContractError):
        registry.brief(0)
    with pytest.raises(mod.ArgosV1ContractError):
        registry.brief(mod.MAX_BRIEF_LIMIT + 1)


def test_signals_for_other_category_empty():
    registry = _registry()
    registry.build(_plan())
    assert registry.signals_for("climate") == ()


def test_is_actionable_structurally_false():
    registry = _registry()
    registry.build(_plan())
    assert registry.is_actionable("sig1") is False
    assert registry.is_actionable("ghost") is False


# ── source + citation gates ─────────────────────────────────────────────────

def test_unregistered_source_rejected():
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(signals=[_signal(source="ghost")]))


def test_missing_rights_note_rejected():
    bad = _source()
    bad["rights_note"] = ""
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(sources=[bad]))


def test_unknown_source_kind_rejected():
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(sources=[_source(kind="rumor_mill")]))


def test_unknown_category_rejected():
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(signals=[_signal(category="astrology")]))


# ── bounded scores + injected time ──────────────────────────────────────────

@pytest.mark.parametrize("severity", [0, 6, "3", None])
def test_severity_bounds_enforced(severity):
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(signals=[_signal(severity=severity)]))


@pytest.mark.parametrize("confidence", [0, 6])
def test_confidence_bounds_enforced(confidence):
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(signals=[_signal(confidence=confidence)]))


@pytest.mark.parametrize("observed", [-1, mod.MAX_OBSERVED_AT + 1, 1.5, "0"])
def test_observed_at_bounds_enforced(observed):
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(signals=[_signal(observed=observed)]))


def test_bool_severity_rejected():
    # bool is an int subclass; exact-type discipline must reject it.
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(signals=[_signal(severity=True)]))


# ── structural rejections ───────────────────────────────────────────────────

def test_duplicate_source_id_rejected():
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(sources=[_source("dup"), _source("dup")]))


def test_duplicate_signal_id_rejected():
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(signals=[_signal("dup"), _signal("dup")]))


def test_plan_keys_contract_enforced():
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build({"sources": []})


def test_signal_keys_contract_enforced():
    bad = _signal()
    del bad["headline"]
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(signals=[bad]))


@pytest.mark.parametrize("value", ["", "a\x00b", 5, None])
def test_signal_id_text_rejections(value):
    bad = _signal()
    bad["signal_id"] = value
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(signals=[bad]))


def test_item_cap_enforced():
    too_many = [_source(f"s{i}") for i in range(mod.MAX_ITEMS + 1)]
    with pytest.raises(mod.ArgosV1ContractError):
        _registry().build(_plan(sources=too_many))


def test_no_action_surface():
    registry = _registry()
    for name in ("publish", "post", "schedule", "dispatch", "execute", "fetch"):
        assert not hasattr(registry, name)
