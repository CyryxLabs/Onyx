"""Focused and adversarial tests for the Guild governed project envelope V1."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core import guild_execution_intent_v1 as intent_mod
from core import guild_handoff_v1 as handoff
from core import guild_profiles_v1 as profiles
from core import guild_project_envelope_v1 as mod
from core import guild_workflow_v1 as workflow_mod

PROJECT = Path(__file__).resolve().parents[1]


def _profile(role_id, persona, allowed, exclusive=()):
    data = f"agent:{role_id}".encode()
    return {
        "role_id": role_id, "persona_name": persona,
        "title": f"{role_id} title", "scope": f"{role_id} scope",
        "allowed_operations": list(allowed),
        "exclusive_operations": list(exclusive),
        "delegation_targets": [], "quality_gates": [],
        "source_ref": f"development/agents/{role_id}.md",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": data,
    }


def _pack(pack_id="team_core"):
    data = f"pack:{pack_id}".encode()
    return {
        "pack_id": pack_id, "name": "Team Core",
        "member_role_ids": ["dev", "qa", "sm"],
        "workflow_refs": ["story-development-cycle.yaml"],
        "source_ref": f"development/agent-teams/{pack_id}.yaml",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": data,
    }


def _registry():
    plan = {
        "constitution_version": profiles.CONSTITUTION_VERSION,
        "profiles": [
            _profile("architect", "Vega", ["architecture_decisions"],
                     ["architecture_decisions"]),
            _profile("dev", "Vulcan", ["implement_story"]),
            _profile("devops", "Polaris",
                     ["git_push", "pr_creation", "release_tag"],
                     ["git_push", "pr_creation", "release_tag"]),
            _profile("po", "Themis", ["story_creation"], ["story_creation"]),
            _profile("qa", "Argus", ["quality_verdicts"], ["quality_verdicts"]),
            _profile("sm", "Chronos", ["story_creation"], ["story_creation"]),
        ],
        "team_packs": [_pack()],
    }
    return profiles.create_guild_registry_v1(PROJECT).build(plan)


def _intents(registry):
    story_plan = {
        "stories": [{
            "story_id": "s1", "epic_id": "e1", "title": "story",
            "acceptance_criteria": ["works"], "assigned_role_id": "dev",
            "status": "approved", "transition_history": ["draft", "approved"],
            "file_list": [],
        }],
        "verdicts": [], "handoffs": [],
    }
    ledger = handoff.create_guild_story_ledger_v1(PROJECT).build(
        registry, story_plan)
    template_bytes = b"workflow:sdc"
    workflow_plan = {
        "templates": [{
            "template_id": "sdc",
            "stages": [
                {"stage_id": "create", "required_operation": "story_creation",
                 "story_status_at_completion": "approved"},
                {"stage_id": "implement", "required_operation": "implement_story",
                 "story_status_at_completion": "in_review"},
                {"stage_id": "qa_gate", "required_operation": "quality_verdicts",
                 "story_status_at_completion": "done"},
            ],
            "source_ref": "development/workflows/sdc.yaml",
            "source_sha256": hashlib.sha256(template_bytes).hexdigest(),
            "source_bytes": template_bytes,
        }],
        "runs": [{
            "run_id": "r1", "template_id": "sdc", "story_id": "s1",
            "completed_stages": [{"stage_id": "create",
                                  "assigned_role_id": "sm"}],
        }],
    }
    workflow = workflow_mod.create_guild_workflow_v1(PROJECT).build(
        registry, ledger, workflow_plan)
    intent_plan = {"intents": [{
        "intent_id": "i1", "run_id": "r1", "stage_id": "implement",
        "story_id": "s1", "assigned_role_id": "dev",
        "patch_scope": ["core"], "gate_argv_shape": ["pytest", "-q"],
        "requires_owner_approval": True,
    }]}
    return intent_mod.create_guild_execution_intent_ledger_v1(PROJECT).build(
        registry, ledger, workflow, intent_plan)


def _budget(cost=1_000_000, loss=100_000, missions=5):
    return {"cost_cap_micro": cost, "loss_budget_micro": loss,
            "max_missions": missions}


def _kpi(kpi_id="k1", target=100):
    return {"kpi_id": kpi_id, "metric": "shipped_features",
            "target_value": target, "measurement_ref": "ledger#weekly"}


def _decommission(failures=3, breach="revoke_and_decommission",
                  kpi="revoke_and_decommission", kill="control_plane#kill"):
    return {"max_consecutive_gate_failures": failures,
            "on_budget_breach": breach, "on_kpi_failure": kpi,
            "kill_switch_ref": kill}


def _envelope(project_id="p1", pack="team_core", intents=("i1",),
              budget=None, kpis=None, decommission=None):
    return {
        "project_id": project_id, "team_pack_id": pack,
        "intent_ids": list(intents),
        "budget": _budget() if budget is None else budget,
        "kpis": [_kpi()] if kpis is None else list(kpis),
        "decommission": _decommission() if decommission is None else decommission,
    }


def _build(envelopes):
    registry = _registry()
    intents = _intents(registry)
    ledger = mod.create_guild_project_ledger_v1(PROJECT)
    snap = ledger.build(registry, intents, {"envelopes": list(envelopes)})
    return ledger, snap


# ── feature gate + entry-bind ───────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.GuildProjectEnvelopeFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on():
    assert mod.GuildProjectEnvelopeFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}).enabled is True


def test_entry_bind_passes_real_project():
    assert isinstance(mod.create_guild_project_ledger_v1(PROJECT),
                      mod.GuildProjectLedgerV1)


def test_entry_bind_denied_when_absent(tmp_path):
    with pytest.raises(mod.GuildProjectEnvelopeV1Denied):
        mod.create_guild_project_ledger_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        mod.GuildProjectLedgerV1(construction_key=object())


# ── happy path + projections ────────────────────────────────────────────────

def test_builds_governed_envelope():
    ledger, snap = _build([_envelope()])
    assert snap.envelopes[0].decommission.on_budget_breach == "revoke_and_decommission"
    assert snap.envelopes[0].budget.cost_cap_micro == 1_000_000
    assert ledger.decommission_outcome("p1") == "revoke_and_decommission"


def test_is_active_structurally_false():
    ledger, _ = _build([_envelope()])
    assert ledger.is_active("p1") is False
    assert ledger.is_active("ghost") is False


def test_remaining_cost_and_breach_projection():
    ledger, _ = _build([_envelope()])
    assert ledger.remaining_cost_micro("p1", 400_000) == 600_000
    assert ledger.is_budget_breached("p1", 400_000) is False
    assert ledger.remaining_cost_micro("p1", 1_000_000) == 0
    assert ledger.is_budget_breached("p1", 1_500_000) is True


def test_unknown_project_projection_rejected():
    ledger, _ = _build([_envelope()])
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        ledger.remaining_cost_micro("ghost", 0)
    assert ledger.decommission_outcome("ghost") is None


def test_sorted_snapshot():
    _, snap = _build([_envelope("z_p", intents=()), _envelope("a_p")])
    assert [e.project_id for e in snap.envelopes] == ["a_p", "z_p"]


# ── decommission policy (owner's termination rule) ──────────────────────────

def test_softer_budget_outcome_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(decommission=_decommission(breach="warn_only"))])


def test_softer_kpi_outcome_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(decommission=_decommission(kpi="notify"))])


def test_missing_kill_switch_ref_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(decommission=_decommission(kill=""))])


def test_zero_gate_failure_tolerance_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(decommission=_decommission(failures=0))])


def test_missing_decommission_field_rejected():
    bad = _decommission()
    del bad["on_kpi_failure"]
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(decommission=bad)])


def test_decommission_vocabulary_is_closed():
    assert mod.DECOMMISSION_OUTCOMES == ("revoke_and_decommission",)


# ── hard budgets ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cost", [0, -1, mod.MAX_BUDGET_MICRO + 1, "1000", None])
def test_cost_cap_bounds_enforced(cost):
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(budget=_budget(cost=cost))])


def test_loss_exceeding_cost_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(budget=_budget(cost=1000, loss=1001))])


def test_zero_loss_budget_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(budget=_budget(loss=0))])


def test_zero_missions_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(budget=_budget(missions=0))])


def test_budget_keys_contract_enforced():
    bad = _budget()
    del bad["max_missions"]
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(budget=bad)])


# ── KPIs + intent coupling ──────────────────────────────────────────────────

def test_envelope_without_kpi_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(kpis=[])])


def test_duplicate_kpi_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(kpis=[_kpi("dup"), _kpi("dup")])])


def test_negative_kpi_target_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(kpis=[_kpi(target=-1)])])


def test_unknown_intent_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(intents=("ghost",))])


def test_duplicate_intent_binding_within_envelope_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(intents=("i1", "i1"))])


def test_intent_bound_by_two_envelopes_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope("p1"), _envelope("p2")])


def test_unknown_team_pack_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope(pack="ghost_pack")])


# ── structural rejections ───────────────────────────────────────────────────

def test_duplicate_project_id_rejected():
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([_envelope("dup"), _envelope("dup", intents=())])


def test_registry_type_enforced():
    registry = _registry()
    intents = _intents(registry)
    ledger = mod.create_guild_project_ledger_v1(PROJECT)
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        ledger.build({"x": 1}, intents, {"envelopes": []})


def test_intents_type_enforced():
    registry = _registry()
    ledger = mod.create_guild_project_ledger_v1(PROJECT)
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        ledger.build(registry, {"intents": []}, {"envelopes": []})


def test_plan_keys_contract_enforced():
    registry = _registry()
    intents = _intents(registry)
    ledger = mod.create_guild_project_ledger_v1(PROJECT)
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        ledger.build(registry, intents, {"wrong": []})


def test_envelope_keys_contract_enforced():
    bad = _envelope()
    del bad["budget"]
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([bad])


@pytest.mark.parametrize("value", ["", "a\x00b", 5, None])
def test_project_id_text_rejections(value):
    bad = _envelope()
    bad["project_id"] = value
    with pytest.raises(mod.GuildProjectEnvelopeV1ContractError):
        _build([bad])


def test_no_execution_surface():
    ledger = mod.create_guild_project_ledger_v1(PROJECT)
    for name in ("dispatch", "execute", "run", "activate", "spend",
                 "decommission", "schedule"):
        assert not hasattr(ledger, name)
