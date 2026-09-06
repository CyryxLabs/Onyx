"""Focused and adversarial tests for the Guild role-profile registry V1."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core import guild_profiles_v1 as mod

PROJECT = Path(__file__).resolve().parents[1]


def _profile(role_id="dev", persona="Vulcan", allowed=None, exclusive=None,
             delegations=None, gates=None, ref=None, body=None):
    data = f"agent:{role_id}".encode() if body is None else body
    return {
        "role_id": role_id,
        "persona_name": persona,
        "title": f"{role_id} title",
        "scope": f"{role_id} scope",
        "allowed_operations": ["implement_story"] if allowed is None else allowed,
        "exclusive_operations": [] if exclusive is None else exclusive,
        "delegation_targets": [] if delegations is None else delegations,
        "quality_gates": [] if gates is None else gates,
        "source_ref": f"development/agents/{role_id}.md" if ref is None else ref,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": data,
    }


def _constitutional():
    return [
        _profile("architect", "Vega",
                 allowed=["architecture_decisions", "design_review"],
                 exclusive=["architecture_decisions"]),
        _profile("dev", "Vulcan",
                 allowed=["implement_story", "local_commit"],
                 delegations=[{"operation": "git_push",
                               "target_role_id": "devops"}]),
        _profile("devops", "Polaris",
                 allowed=["git_push", "pr_creation", "release_tag"],
                 exclusive=["git_push", "pr_creation", "release_tag"]),
        _profile("po", "Themis",
                 allowed=["story_creation", "story_validation"],
                 exclusive=["story_creation"]),
        _profile("qa", "Argus",
                 allowed=["quality_verdicts"],
                 exclusive=["quality_verdicts"]),
        _profile("sm", "Chronos",
                 allowed=["story_creation"],
                 exclusive=["story_creation"]),
    ]


def _pack(pack_id="team_core", members=None, ref=None):
    data = f"pack:{pack_id}".encode()
    return {
        "pack_id": pack_id,
        "name": "Team Core",
        "member_role_ids": (
            ["architect", "dev", "devops", "po", "qa", "sm"]
            if members is None else members
        ),
        "workflow_refs": ["story-development-cycle.yaml"],
        "source_ref": f"development/agent-teams/{pack_id}.yaml" if ref is None else ref,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": data,
    }


def _plan(profiles=None, packs=(), version=mod.CONSTITUTION_VERSION):
    return {
        "constitution_version": version,
        "profiles": _constitutional() if profiles is None else list(profiles),
        "team_packs": list(packs),
    }


def _registry():
    return mod.create_guild_registry_v1(PROJECT)


# ── feature gate + entry-bind ───────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.GuildProfilesFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on():
    assert mod.GuildProfilesFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}).enabled is True


def test_entry_bind_passes_real_project():
    assert isinstance(_registry(), mod.GuildRegistryV1)


def test_entry_bind_denied_when_absent(tmp_path):
    with pytest.raises(mod.GuildProfilesV1Denied):
        mod.create_guild_registry_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        mod.GuildRegistryV1(construction_key=object())


# ── happy path ──────────────────────────────────────────────────────────────

def test_builds_sorted_snapshot_with_constitutional_matrix():
    snap = _registry().build(_plan())
    assert [p.role_id for p in snap.profiles] == [
        "architect", "dev", "devops", "po", "qa", "sm"]
    assert snap.constitution_version == mod.CONSTITUTION_VERSION
    assert dict(snap.matrix.exclusive_owners) == {
        "architecture_decisions": ("architect",),
        "git_push": ("devops",),
        "pr_creation": ("devops",),
        "quality_verdicts": ("qa",),
        "release_tag": ("devops",),
        "story_creation": ("po", "sm"),
    }


def test_pack_root_is_deterministic():
    first = _registry().build(_plan(packs=[_pack()]))
    second = _registry().build(_plan(packs=[_pack()]))
    assert first.pack_root_sha256 == second.pack_root_sha256
    assert len(first.pack_root_sha256) == 64


def test_team_pack_membership_accepted():
    snap = _registry().build(_plan(packs=[_pack()]))
    assert snap.team_packs[0].pack_id == "team_core"
    assert "devops" in snap.team_packs[0].member_role_ids


def test_is_operation_permitted_projection():
    registry = _registry()
    registry.build(_plan())
    assert registry.is_operation_permitted("devops", "git_push") is True
    assert registry.is_operation_permitted("dev", "git_push") is False
    assert registry.is_operation_permitted("dev", "implement_story") is True
    assert registry.is_operation_permitted("ghost", "git_push") is False
    assert registry.is_operation_permitted("dev", "unknown_op") is False


def test_delegation_target_projection():
    registry = _registry()
    registry.build(_plan())
    assert registry.delegation_target("dev", "git_push") == "devops"
    assert registry.delegation_target("dev", "release_tag") is None
    assert registry.delegation_target("ghost", "git_push") is None


# ── constitutional floor ────────────────────────────────────────────────────

def test_missing_constitutional_owner_role_rejected():
    profiles = [p for p in _constitutional() if p["role_id"] != "devops"]
    dev = next(p for p in profiles if p["role_id"] == "dev")
    dev["delegation_targets"] = []
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


def test_constitutional_op_unclaimed_rejected():
    profiles = _constitutional()
    devops = next(p for p in profiles if p["role_id"] == "devops")
    devops["exclusive_operations"] = ["pr_creation", "release_tag"]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


def test_constitutional_op_claimed_by_wrong_role_rejected():
    profiles = _constitutional()
    devops = next(p for p in profiles if p["role_id"] == "devops")
    devops["allowed_operations"] = ["pr_creation", "release_tag"]
    devops["exclusive_operations"] = ["pr_creation", "release_tag"]
    qa = next(p for p in profiles if p["role_id"] == "qa")
    qa["allowed_operations"] = ["quality_verdicts", "git_push"]
    qa["exclusive_operations"] = ["quality_verdicts", "git_push"]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


def test_extra_claimant_on_constitutional_op_rejected():
    profiles = _constitutional()
    dev = next(p for p in profiles if p["role_id"] == "dev")
    dev["allowed_operations"] = ["implement_story", "git_push"]
    dev["exclusive_operations"] = ["git_push"]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


def test_partial_constitutional_owner_set_rejected():
    profiles = _constitutional()
    sm = next(p for p in profiles if p["role_id"] == "sm")
    sm["allowed_operations"] = ["draft_support"]
    sm["exclusive_operations"] = []
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


# ── one-claim exclusivity ───────────────────────────────────────────────────

def test_exclusive_leak_to_non_owner_rejected():
    profiles = _constitutional()
    dev = next(p for p in profiles if p["role_id"] == "dev")
    dev["allowed_operations"] = ["implement_story", "release_tag"]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


def test_co_owned_non_constitutional_exclusive_accepted():
    profiles = _constitutional()
    dev = next(p for p in profiles if p["role_id"] == "dev")
    qa = next(p for p in profiles if p["role_id"] == "qa")
    dev["allowed_operations"] = ["implement_story", "deploy_preview"]
    dev["exclusive_operations"] = ["deploy_preview"]
    qa["allowed_operations"] = ["quality_verdicts", "deploy_preview"]
    qa["exclusive_operations"] = ["quality_verdicts", "deploy_preview"]
    snap = _registry().build(_plan(profiles))
    assert dict(snap.matrix.exclusive_owners)["deploy_preview"] == ("dev", "qa")


def test_exclusive_not_in_allowed_rejected():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan([
            _profile("solo", allowed=["implement_story"], exclusive=["git_push"]),
        ]))


# ── delegation graph ────────────────────────────────────────────────────────

def test_delegation_to_unknown_role_rejected():
    profiles = _constitutional()
    dev = next(p for p in profiles if p["role_id"] == "dev")
    dev["delegation_targets"] = [
        {"operation": "git_push", "target_role_id": "ghost"}]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


def test_delegation_target_without_operation_rejected():
    profiles = _constitutional()
    dev = next(p for p in profiles if p["role_id"] == "dev")
    dev["delegation_targets"] = [
        {"operation": "quality_verdicts", "target_role_id": "devops"}]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


def test_self_delegation_rejected():
    profiles = _constitutional()
    dev = next(p for p in profiles if p["role_id"] == "dev")
    dev["delegation_targets"] = [
        {"operation": "implement_story", "target_role_id": "dev"}]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


def test_duplicate_delegation_operation_rejected():
    profiles = _constitutional()
    dev = next(p for p in profiles if p["role_id"] == "dev")
    dev["delegation_targets"] = [
        {"operation": "git_push", "target_role_id": "devops"},
        {"operation": "git_push", "target_role_id": "devops"},
    ]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(profiles))


# ── byte-pinned provenance ──────────────────────────────────────────────────

def test_tampered_source_bytes_rejected():
    tampered = _profile("dev")
    tampered["source_bytes"] = b"agent:tampered"
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan([tampered]))


@pytest.mark.parametrize("value", ["ABC", "12" * 31, "g" * 64, 7])
def test_bad_sha_format_rejected(value):
    bad = _profile("dev")
    bad["source_sha256"] = value
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan([bad]))


def test_source_bytes_type_rejected():
    bad = _profile("dev")
    bad["source_bytes"] = "agent:dev"
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan([bad]))


def test_duplicate_source_ref_rejected():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan([
            _profile("a_role", ref="development/agents/shared.md"),
            _profile("b_role", ref="development/agents/shared.md"),
        ]))


# ── structural rejections ───────────────────────────────────────────────────

def test_duplicate_role_id_rejected():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan([
            _profile("dup", ref="development/agents/one.md"),
            _profile("dup", ref="development/agents/two.md"),
        ]))


def test_duplicate_pack_id_rejected():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(packs=[
            _pack("dup", ref="development/agent-teams/one.yaml"),
            _pack("dup", ref="development/agent-teams/two.yaml"),
        ]))


def test_pack_unknown_member_rejected():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(packs=[_pack(members=["architect", "ghost"])]))


def test_pack_empty_members_rejected():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(packs=[_pack(members=[])]))


def test_pack_duplicate_member_rejected():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(packs=[_pack(members=["dev", "dev"])]))


def test_constitution_version_drift_rejected():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(version="1.0.0"))


def test_plan_keys_contract_enforced():
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build({"constitution_version": mod.CONSTITUTION_VERSION,
                           "profiles": []})


def test_profile_keys_contract_enforced():
    bad = _profile("dev")
    del bad["title"]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan([bad]))


@pytest.mark.parametrize("value", ["Push", "9x", "a b", "", "git-push"])
def test_operation_grammar_rejections(value):
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan([_profile("dev", allowed=[value])]))


@pytest.mark.parametrize("value", ["", "a\x00b", 5, None])
def test_role_id_text_rejections(value):
    bad = _profile("dev")
    bad["role_id"] = value
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan([bad]))


def test_item_cap_enforced():
    too_many = [
        _profile(f"role_{index}", ref=f"development/agents/{index}.md")
        for index in range(mod.MAX_ITEMS + 1)
    ]
    with pytest.raises(mod.GuildProfilesV1ContractError):
        _registry().build(_plan(too_many))


def test_no_orchestration_surface():
    registry = _registry()
    for name in ("dispatch", "execute", "run", "activate", "schedule", "assign"):
        assert not hasattr(registry, name)
