"""Focused and adversarial tests for the Guild handoff/story ledger V1."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core import guild_handoff_v1 as mod
from core import guild_profiles_v1 as profiles

PROJECT = Path(__file__).resolve().parents[1]


def _profile(role_id, persona, allowed, exclusive=(), delegations=()):
    data = f"agent:{role_id}".encode()
    return {
        "role_id": role_id,
        "persona_name": persona,
        "title": f"{role_id} title",
        "scope": f"{role_id} scope",
        "allowed_operations": list(allowed),
        "exclusive_operations": list(exclusive),
        "delegation_targets": list(delegations),
        "quality_gates": [],
        "source_ref": f"development/agents/{role_id}.md",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": data,
    }


def _registry_snapshot():
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


def _story(story_id="s1", assigned="dev", status="draft", history=("draft",),
           criteria=("it works",), files=()):
    return {
        "story_id": story_id,
        "epic_id": "epic_guild",
        "title": f"story {story_id}",
        "acceptance_criteria": list(criteria),
        "assigned_role_id": assigned,
        "status": status,
        "transition_history": list(history),
        "file_list": list(files),
    }


def _verdict(story_id="s1", verdict="approve", reviewer="qa"):
    return {"story_id": story_id, "verdict": verdict,
            "reviewer_role_id": reviewer}


def _handoff(handoff_id="h1", story_id="s1", from_role="sm", to_role="dev",
             decisions=("use module X",), files=("core/x.py",),
             blockers=(), next_action="implement story"):
    return {
        "handoff_id": handoff_id,
        "story_id": story_id,
        "from_role_id": from_role,
        "to_role_id": to_role,
        "decisions": list(decisions),
        "files_modified": list(files),
        "blockers": list(blockers),
        "next_action": next_action,
    }


def _plan(stories, verdicts=(), handoffs=()):
    return {"stories": list(stories), "verdicts": list(verdicts),
            "handoffs": list(handoffs)}


def _ledger():
    return mod.create_guild_story_ledger_v1(PROJECT)


DONE_HISTORY = ("draft", "approved", "in_progress", "in_review", "done")
LOOP_HISTORY = ("draft", "approved", "in_progress", "in_review",
                "in_progress", "in_review", "done")


# ── feature gate + entry-bind ───────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.GuildHandoffFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on():
    assert mod.GuildHandoffFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}).enabled is True


def test_entry_bind_passes_real_project():
    assert isinstance(_ledger(), mod.GuildStoryLedgerV1)


def test_entry_bind_denied_when_absent(tmp_path):
    with pytest.raises(mod.GuildHandoffV1Denied):
        mod.create_guild_story_ledger_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        mod.GuildStoryLedgerV1(construction_key=object())


# ── happy path ──────────────────────────────────────────────────────────────

def test_full_lifecycle_done_with_approve():
    ledger = _ledger()
    snap = ledger.build(_registry_snapshot(), _plan(
        [_story(status="done", history=DONE_HISTORY)],
        verdicts=[_verdict("s1", "approve")],
    ))
    assert snap.stories[0].status == "done"
    assert ledger.is_done("s1") is True


def test_qa_loop_with_covering_reject():
    ledger = _ledger()
    ledger.build(_registry_snapshot(), _plan(
        [_story(status="done", history=LOOP_HISTORY)],
        verdicts=[_verdict("s1", "reject"), _verdict("s1", "approve")],
    ))
    assert ledger.qa_reject_count("s1") == 1


def test_blocked_story_stuck_in_review_accepted():
    ledger = _ledger()
    snap = ledger.build(_registry_snapshot(), _plan(
        [_story(status="in_review",
                history=("draft", "approved", "in_progress", "in_review"))],
        verdicts=[_verdict("s1", "blocked")],
    ))
    assert snap.stories[0].status == "in_review"


def test_sorted_snapshot_and_projections():
    ledger = _ledger()
    snap = ledger.build(_registry_snapshot(), _plan(
        [_story("z_story"), _story("a_story")],
        handoffs=[_handoff("h1", "a_story")],
    ))
    assert [s.story_id for s in snap.stories] == ["a_story", "z_story"]
    assert ledger.story_status("a_story") == "draft"
    assert ledger.story_status("ghost") is None
    assert ledger.is_done("a_story") is False
    assert snap.handoffs[0].handoff_id == "h1"


# ── lifecycle rejections ────────────────────────────────────────────────────

def test_skipped_stage_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="in_progress", history=("draft", "in_progress"))]))


def test_regression_transition_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="draft", history=DONE_HISTORY + ("draft",))]))


def test_history_must_begin_at_draft():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="approved", history=("approved",))]))


def test_history_must_land_on_status():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="done",
                    history=("draft", "approved", "in_progress", "in_review"))]))


def test_unknown_status_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="published", history=("draft", "published"))]))


def test_unknown_history_status_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(history=("draft", "shipping"))]))


def test_empty_acceptance_criteria_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan([_story(criteria=())]))


def test_unknown_assigned_role_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan([_story(assigned="ghost")]))


# ── QA gates ────────────────────────────────────────────────────────────────

def test_done_without_approve_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="done", history=DONE_HISTORY)]))


def test_done_with_blocked_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="done", history=DONE_HISTORY)],
            verdicts=[_verdict("s1", "approve"), _verdict("s1", "blocked")],
        ))


def test_blocked_story_not_in_review_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="draft")],
            verdicts=[_verdict("s1", "blocked")],
        ))


def test_reviewer_without_authority_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="done", history=DONE_HISTORY)],
            verdicts=[_verdict("s1", "approve", reviewer="dev")],
        ))


def test_reject_cap_exceeded_rejected():
    verdicts = [_verdict("s1", "reject") for _ in range(mod.MAX_QA_REJECTS + 1)]
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="in_review",
                    history=("draft", "approved", "in_progress", "in_review"))],
            verdicts=verdicts,
        ))


def test_loop_edge_without_reject_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(status="done", history=LOOP_HISTORY)],
            verdicts=[_verdict("s1", "approve")],
        ))


def test_verdict_unknown_story_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()], verdicts=[_verdict("ghost")]))


def test_unknown_verdict_value_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()], verdicts=[_verdict("s1", "maybe")]))


# ── bounded handoffs ────────────────────────────────────────────────────────

def test_self_handoff_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()], handoffs=[_handoff(from_role="dev", to_role="dev")]))


def test_handoff_unknown_role_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()], handoffs=[_handoff(to_role="ghost")]))


def test_handoff_unknown_story_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()], handoffs=[_handoff(story_id="ghost")]))


def test_handoff_decision_cap_enforced():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()],
            handoffs=[_handoff(decisions=tuple(f"d{i}" for i in range(6)))]))


def test_handoff_file_cap_enforced():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()],
            handoffs=[_handoff(files=tuple(f"f{i}" for i in range(11)))]))


def test_handoff_blocker_cap_enforced():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()],
            handoffs=[_handoff(blockers=("b1", "b2", "b3", "b4"))]))


def test_handoff_byte_budget_enforced():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()],
            handoffs=[_handoff(next_action="x" * (mod.MAX_HANDOFF_BYTES + 1))]))


def test_duplicate_handoff_id_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story()], handoffs=[_handoff("dup"), _handoff("dup")]))


# ── structural rejections ───────────────────────────────────────────────────

def test_registry_type_enforced():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build({"profiles": []}, _plan([_story()]))


def test_plan_keys_contract_enforced():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), {"stories": []})


def test_story_keys_contract_enforced():
    bad = _story()
    del bad["title"]
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan([bad]))


def test_duplicate_story_id_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan([_story("dup"), _story("dup")]))


def test_duplicate_file_list_entry_rejected():
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan(
            [_story(files=("core/x.py", "core/x.py"))]))


@pytest.mark.parametrize("value", ["", "a\x00b", 5, None])
def test_story_id_text_rejections(value):
    bad = _story()
    bad["story_id"] = value
    with pytest.raises(mod.GuildHandoffV1ContractError):
        _ledger().build(_registry_snapshot(), _plan([bad]))


def test_no_execution_surface():
    ledger = _ledger()
    for name in ("dispatch", "execute", "run", "activate", "schedule", "assign"):
        assert not hasattr(ledger, name)
