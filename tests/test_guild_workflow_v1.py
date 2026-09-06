"""Focused and adversarial tests for the Guild workflow templates/runs V1."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core import guild_handoff_v1 as handoff
from core import guild_profiles_v1 as profiles
from core import guild_workflow_v1 as mod

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


def _story(story_id, status, history, criteria=("works",)):
    return {
        "story_id": story_id,
        "epic_id": "epic_guild",
        "title": f"story {story_id}",
        "acceptance_criteria": list(criteria),
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
            _story("s_review", "in_review",
                   ("draft", "approved", "in_progress", "in_review")),
            _story("s_done", "done",
                   ("draft", "approved", "in_progress", "in_review", "done")),
        ],
        "verdicts": [{"story_id": "s_done", "verdict": "approve",
                      "reviewer_role_id": "qa"}],
        "handoffs": [],
    }
    return handoff.create_guild_story_ledger_v1(PROJECT).build(registry, plan)


def _stage(stage_id="create", op="story_creation", status="approved"):
    return {"stage_id": stage_id, "required_operation": op,
            "story_status_at_completion": status}


def _template(template_id="sdc", stages=None, ref=None, body=None):
    data = f"workflow:{template_id}".encode() if body is None else body
    return {
        "template_id": template_id,
        "stages": [
            _stage("create", "story_creation", "approved"),
            _stage("implement", "implement_story", "in_review"),
            _stage("qa_gate", "quality_verdicts", "done"),
        ] if stages is None else list(stages),
        "source_ref": (
            f"development/workflows/{template_id}.yaml" if ref is None else ref
        ),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": data,
    }


def _run(run_id="r1", template_id="sdc", story_id="s_draft", completed=()):
    return {"run_id": run_id, "template_id": template_id,
            "story_id": story_id, "completed_stages": list(completed)}


def _done_stages():
    return (
        {"stage_id": "create", "assigned_role_id": "sm"},
        {"stage_id": "implement", "assigned_role_id": "dev"},
        {"stage_id": "qa_gate", "assigned_role_id": "qa"},
    )


def _workflow():
    return mod.create_guild_workflow_v1(PROJECT)


def _build(plan_templates=None, plan_runs=()):
    registry = _registry()
    ledger = _ledger(registry)
    workflow = _workflow()
    plan = {"templates": [_template()] if plan_templates is None
            else list(plan_templates), "runs": list(plan_runs)}
    return workflow, workflow.build(registry, ledger, plan)


# ── feature gate + entry-bind ───────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.GuildWorkflowFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on():
    assert mod.GuildWorkflowFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}).enabled is True


def test_entry_bind_passes_real_project():
    assert isinstance(_workflow(), mod.GuildWorkflowV1)


def test_entry_bind_denied_when_absent(tmp_path):
    with pytest.raises(mod.GuildWorkflowV1Denied):
        mod.create_guild_workflow_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        mod.GuildWorkflowV1(construction_key=object())


# ── happy path ──────────────────────────────────────────────────────────────

def test_complete_run_and_projections():
    workflow, snap = _build(plan_runs=[
        _run("r_done", story_id="s_done", completed=_done_stages())])
    assert workflow.is_run_complete("r_done") is True
    assert workflow.run_stage("r_done") == "qa_gate"
    assert snap.runs[0].completed_stages[-1].assigned_role_id == "qa"


def test_empty_run_on_draft_story():
    workflow, _ = _build(plan_runs=[_run("r0", story_id="s_draft")])
    assert workflow.run_stage("r0") is None
    assert workflow.is_run_complete("r0") is False


def test_partial_run_prefix_matches_status():
    workflow, _ = _build(plan_runs=[
        _run("r1", story_id="s_approved",
             completed=[{"stage_id": "create", "assigned_role_id": "po"}])])
    assert workflow.run_stage("r1") == "create"


def test_sorted_snapshot():
    _, snap = _build(plan_templates=[_template("z_t"), _template("a_t", ref="development/workflows/a.yaml")])
    assert [t.template_id for t in snap.templates] == ["a_t", "z_t"]


# ── template gates ──────────────────────────────────────────────────────────

def test_duplicate_stage_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[_template(stages=[
            _stage("dup", "story_creation", "approved"),
            _stage("dup", "implement_story", "done")])])


def test_unknown_completion_status_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[_template(stages=[
            _stage("create", "story_creation", "shipped")])])


def test_regressing_completion_statuses_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[_template(stages=[
            _stage("a", "story_creation", "in_review"),
            _stage("b", "implement_story", "approved"),
            _stage("c", "quality_verdicts", "done")])])


def test_template_must_end_at_done():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[_template(stages=[
            _stage("create", "story_creation", "approved")])])


def test_empty_template_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[_template(stages=[])])


def test_tampered_template_bytes_rejected():
    bad = _template()
    bad["source_bytes"] = b"workflow:tampered"
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[bad])


def test_duplicate_template_id_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[
            _template("dup", ref="development/workflows/one.yaml"),
            _template("dup", ref="development/workflows/two.yaml")])


def test_duplicate_template_source_ref_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[
            _template("a_t", ref="development/workflows/shared.yaml"),
            _template("b_t", ref="development/workflows/shared.yaml")])


def test_template_keys_contract_enforced():
    bad = _template()
    del bad["source_ref"]
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[bad])


# ── run gates ───────────────────────────────────────────────────────────────

def test_status_mismatch_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_runs=[
            _run("r1", story_id="s_draft",
                 completed=[{"stage_id": "create", "assigned_role_id": "sm"}])])


def test_stage_reorder_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_runs=[
            _run("r1", story_id="s_approved",
                 completed=[{"stage_id": "implement",
                             "assigned_role_id": "dev"}])])


def test_run_exceeding_template_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_runs=[
            _run("r1", story_id="s_done",
                 completed=list(_done_stages()) + [
                     {"stage_id": "extra", "assigned_role_id": "dev"}])])


def test_unknown_template_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_runs=[_run("r1", template_id="ghost")])


def test_unknown_story_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_runs=[_run("r1", story_id="ghost")])


def test_assignee_without_operation_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_runs=[
            _run("r1", story_id="s_approved",
                 completed=[{"stage_id": "create",
                             "assigned_role_id": "dev"}])])


def test_exclusive_owner_respected():
    workflow, _ = _build(plan_runs=[
        _run("r1", story_id="s_approved",
             completed=[{"stage_id": "create", "assigned_role_id": "sm"}])])
    assert workflow.run_stage("r1") == "create"


def test_duplicate_run_id_rejected():
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_runs=[_run("dup", story_id="s_draft"),
                          _run("dup", story_id="s_draft")])


def test_run_keys_contract_enforced():
    bad = _run()
    del bad["story_id"]
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_runs=[bad])


# ── structural rejections ───────────────────────────────────────────────────

def test_registry_type_enforced():
    registry = _registry()
    ledger = _ledger(registry)
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _workflow().build({"profiles": []}, ledger,
                          {"templates": [], "runs": []})


def test_ledger_type_enforced():
    registry = _registry()
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _workflow().build(registry, {"stories": []},
                          {"templates": [], "runs": []})


def test_plan_keys_contract_enforced():
    registry = _registry()
    ledger = _ledger(registry)
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _workflow().build(registry, ledger, {"templates": []})


@pytest.mark.parametrize("value", ["", "a\x00b", 5, None])
def test_template_id_text_rejections(value):
    bad = _template()
    bad["template_id"] = value
    with pytest.raises(mod.GuildWorkflowV1ContractError):
        _build(plan_templates=[bad])


def test_no_execution_surface():
    workflow = _workflow()
    for name in ("dispatch", "execute", "run", "activate", "schedule", "assign"):
        assert not hasattr(workflow, name)
