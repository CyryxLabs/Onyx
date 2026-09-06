"""Focused and adversarial tests for the Guild execution-intent ledger V1."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core import guild_execution_intent_v1 as mod
from core import guild_handoff_v1 as handoff
from core import guild_profiles_v1 as profiles
from core import guild_workflow_v1 as workflow_mod

PROJECT = Path(__file__).resolve().parents[1]


def _profile(role_id, persona, allowed, exclusive=()):
    data = f"agent:{role_id}".encode()
    return {
        "role_id": role_id,
        "persona_name": persona,
        "title": f"{role_id} title",
        "scope": f"{role_id} scope",
        "allowed_operations": list(allowed),
        "exclusive_operations": list(exclusive),
        "delegation_targets": [],
        "quality_gates": [],
        "source_ref": f"development/agents/{role_id}.md",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": data,
    }


def _registry():
    plan = {
        "constitution_version": profiles.CONSTITUTION_VERSION,
        "profiles": [
            _profile("architect", "Vega",
                     ["architecture_decisions"], ["architecture_decisions"]),
            _profile("dev", "Vulcan", ["implement_story", "local_commit"]),
            _profile("devops", "Polaris",
                     ["git_push", "pr_creation", "release_tag"],
                     ["git_push", "pr_creation", "release_tag"]),
            _profile("po", "Themis",
                     ["story_creation", "story_validation"], ["story_creation"]),
            _profile("qa", "Argus", ["quality_verdicts"], ["quality_verdicts"]),
            _profile("sm", "Chronos", ["story_creation"], ["story_creation"]),
        ],
        "team_packs": [],
    }
    return profiles.create_guild_registry_v1(PROJECT).build(plan)


def _story(story_id, status, history):
    return {
        "story_id": story_id,
        "epic_id": "epic_guild",
        "title": f"story {story_id}",
        "acceptance_criteria": ["works"],
        "assigned_role_id": "dev",
        "status": status,
        "transition_history": list(history),
        "file_list": [],
    }


def _ledger(registry):
    plan = {
        "stories": [
            _story("s_draft", "draft", ("draft",)),
            _story("s_approved", "approved", ("draft", "approved")),
        ],
        "verdicts": [],
        "handoffs": [],
    }
    return handoff.create_guild_story_ledger_v1(PROJECT).build(registry, plan)


def _template():
    data = b"workflow:sdc"
    return {
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
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": data,
    }


def _workflow(registry, ledger):
    plan = {
        "templates": [_template()],
        "runs": [
            {"run_id": "r_fresh", "template_id": "sdc", "story_id": "s_draft",
             "completed_stages": []},
            {"run_id": "r_mid", "template_id": "sdc", "story_id": "s_approved",
             "completed_stages": [
                 {"stage_id": "create", "assigned_role_id": "sm"}]},
        ],
    }
    return workflow_mod.create_guild_workflow_v1(PROJECT).build(
        registry, ledger, plan)


def _intent(intent_id="i1", run_id="r_mid", stage_id="implement",
            story_id="s_approved", role="dev", scope=("core",),
            argv=("pytest", "-q"), approval=True):
    return {
        "intent_id": intent_id,
        "run_id": run_id,
        "stage_id": stage_id,
        "story_id": story_id,
        "assigned_role_id": role,
        "patch_scope": list(scope),
        "gate_argv_shape": list(argv),
        "requires_owner_approval": approval,
    }


def _build(intents):
    registry = _registry()
    ledger = _ledger(registry)
    workflow = _workflow(registry, ledger)
    intent_ledger = mod.create_guild_execution_intent_ledger_v1(PROJECT)
    snap = intent_ledger.build(registry, ledger, workflow,
                               {"intents": list(intents)})
    return intent_ledger, snap


# ── feature gate + entry-bind + autopilot pin ───────────────────────────────

def test_feature_gate_default_off():
    assert mod.GuildExecutionIntentFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on():
    assert mod.GuildExecutionIntentFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}).enabled is True


def test_entry_bind_passes_real_project_and_pins_autopilot():
    ledger = mod.create_guild_execution_intent_ledger_v1(PROJECT)
    assert isinstance(ledger, mod.GuildExecutionIntentLedgerV1)


def test_entry_bind_denied_when_absent(tmp_path):
    with pytest.raises(mod.GuildExecutionIntentV1Denied):
        mod.create_guild_execution_intent_ledger_v1(tmp_path)


def test_autopilot_drift_denied(tmp_path):
    # Real guild evidence but a tampered autopilot module must be denied.
    for relative, _ in mod.ACCEPTED_GUILD_WORKFLOW_ROOTS:
        source = PROJECT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    autopilot = tmp_path / mod.AUTOPILOT_MODULE_PATH
    autopilot.parent.mkdir(parents=True, exist_ok=True)
    autopilot.write_bytes(b"MISSION_TYPE = \"project_autopilot_v1\"\n")
    with pytest.raises(mod.GuildExecutionIntentV1Denied):
        mod.create_guild_execution_intent_ledger_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        mod.GuildExecutionIntentLedgerV1(
            construction_key=object(),
            autopilot=mod.AutopilotIdentityV1(
                module_path="x", module_sha256="0" * 64,
                module_bytes=1, mission_type="project_autopilot_v1"),
        )


# ── happy path ──────────────────────────────────────────────────────────────

def test_intent_binds_next_stage_of_partial_run():
    ledger, snap = _build([_intent()])
    assert snap.intents[0].required_operation == "implement_story"
    assert snap.autopilot.module_sha256 == mod.AUTOPILOT_MODULE_SHA256
    assert ledger.intent_for("r_mid", "implement").intent_id == "i1"


def test_intent_binds_first_stage_of_fresh_run():
    _, snap = _build([_intent("i0", run_id="r_fresh", stage_id="create",
                              story_id="s_draft", role="sm")])
    assert snap.intents[0].stage_id == "create"


def test_is_dispatchable_structurally_false():
    ledger, _ = _build([_intent()])
    assert ledger.is_dispatchable("i1") is False
    assert ledger.is_dispatchable("ghost") is False


def test_requires_owner_approval_recorded_true():
    _, snap = _build([_intent()])
    assert snap.intents[0].requires_owner_approval is True


# ── forward-only + coupling gates ───────────────────────────────────────────

def test_wrong_stage_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(stage_id="qa_gate")])


def test_completed_stage_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(stage_id="create", role="sm")])


def test_unknown_run_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(run_id="ghost")])


def test_story_mismatch_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(story_id="s_draft")])


def test_assignee_without_operation_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(role="qa")])


def test_exclusive_owner_respected_for_first_stage():
    _, snap = _build([_intent("i0", run_id="r_fresh", stage_id="create",
                              story_id="s_draft", role="po")])
    assert snap.intents[0].assigned_role_id == "po"


def test_non_owner_of_exclusive_stage_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent("i0", run_id="r_fresh", stage_id="create",
                        story_id="s_draft", role="dev")])


# ── owner gate + scope grammar ──────────────────────────────────────────────

def test_requires_owner_approval_false_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(approval=False)])


@pytest.mark.parametrize("value", [1, "true", None])
def test_requires_owner_approval_non_bool_rejected(value):
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(approval=value)])


def test_empty_patch_scope_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(scope=())])


@pytest.mark.parametrize("value", [
    "../secrets", "/absolute", "C:/windows", "a\\b", "a//b", ".", "..", "a/./b",
])
def test_patch_scope_grammar_rejections(value):
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(scope=(value,))])


def test_duplicate_scope_entry_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(scope=("core", "core"))])


def test_empty_argv_token_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent(argv=("",))])


def test_empty_argv_shape_allowed():
    _, snap = _build([_intent(argv=())])
    assert snap.intents[0].gate_argv_shape == ()


# ── structural rejections ───────────────────────────────────────────────────

def test_duplicate_intent_id_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent("dup"),
                _intent("dup", run_id="r_fresh", stage_id="create",
                        story_id="s_draft", role="sm")])


def test_double_binding_same_stage_rejected():
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([_intent("i1"), _intent("i2")])


def test_registry_type_enforced():
    registry = _registry()
    ledger = _ledger(registry)
    workflow = _workflow(registry, ledger)
    intent_ledger = mod.create_guild_execution_intent_ledger_v1(PROJECT)
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        intent_ledger.build({"x": 1}, ledger, workflow, {"intents": []})


def test_workflow_type_enforced():
    registry = _registry()
    ledger = _ledger(registry)
    intent_ledger = mod.create_guild_execution_intent_ledger_v1(PROJECT)
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        intent_ledger.build(registry, ledger, {"runs": []}, {"intents": []})


def test_plan_keys_contract_enforced():
    registry = _registry()
    ledger = _ledger(registry)
    workflow = _workflow(registry, ledger)
    intent_ledger = mod.create_guild_execution_intent_ledger_v1(PROJECT)
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        intent_ledger.build(registry, ledger, workflow, {"wrong": []})


def test_intent_keys_contract_enforced():
    bad = _intent()
    del bad["patch_scope"]
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([bad])


@pytest.mark.parametrize("value", ["", "a\x00b", 5, None])
def test_intent_id_text_rejections(value):
    bad = _intent()
    bad["intent_id"] = value
    with pytest.raises(mod.GuildExecutionIntentV1ContractError):
        _build([bad])


def test_no_execution_surface():
    ledger, _ = _build([_intent()])
    for name in ("dispatch", "execute", "run", "activate", "schedule", "assign"):
        assert not hasattr(ledger, name)
