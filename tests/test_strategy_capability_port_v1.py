"""Adversarial tests for the provider-free Phase 10 strategy projection."""

import hashlib
from dataclasses import replace

import pytest

from core.capability_ports.strategy_v1 import (
    StrategyAccountBindingV1,
    StrategyCapabilityPortV1,
)
from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.phase10_audience_strategy_v1 import (
    AudienceSegmentV1, AudienceStrategySnapshotV1, ExperimentV1, FunnelStageV1,
    KpiV1, ResearchClaimV1, StrategyPlanV1,
)
from core.phase10_brand_passport_v1 import (
    REQUIRED_POLICY_GUARDS, BrandInventoryV1, BrandPassportV1, SocialAccountV1,
)
from core.phase10_content_draft_v1 import (
    ContentClaimV1, ContentDraftSetSnapshotV1, ContentDraftV1, PolicyReviewRecordV1,
)
from core.phase10_editorial_calendar_v1 import (
    ApprovalRecordV1, EditorialCalendarSnapshotV1, PlannedPostV1,
)


def _sources(*, approval=True):
    inventory = BrandInventoryV1(
        (BrandPassportV1("brand-a", "Brand A", True, frozenset({"linkedin"}), False,
                         REQUIRED_POLICY_GUARDS),),
        (SocialAccountV1("account-a", "brand-a", "linkedin", "brand-a", "test",
                         True, frozenset({"read"})),),
    )
    calendar = EditorialCalendarSnapshotV1(
        (PlannedPostV1("post-a", "account-a", "linkedin", 200, "scheduled", "idem-a", True),),
        (ApprovalRecordV1("post-a", approval, "owner"),) if approval is not None else (),
    )
    claim = ContentClaimV1("claim-a", "Bounded claim", True, "evidence-a")
    drafts = ContentDraftSetSnapshotV1(
        (ContentDraftV1("draft-a", "brand-a", "linkedin", "Draft", "approved", True, (), (claim,)),),
        (PolicyReviewRecordV1("draft-a", True, "owner"),),
    )
    research = ResearchClaimV1("research-a", "Observed", "source-a", "linkedin")
    strategy = AudienceStrategySnapshotV1(
        (AudienceSegmentV1("segment-a", "brand-a", "linkedin", "Audience", (research,)),),
        (KpiV1("kpi-a", "linkedin", "qualified_visits", 10, 30),),
        (FunnelStageV1("stage-a", 1, ("kpi-a",)),),
        (StrategyPlanV1("plan-a", "brand-a", ("g30",), ("g60",), ("g90",)),),
        (ExperimentV1("experiment-a", "Hypothesis", "linkedin", 100, 10, False),),
    )
    return inventory, calendar, drafts, strategy


def _port(*, sources=None, store=None):
    values = _sources() if sources is None else sources
    binding = StrategyAccountBindingV1(
        "workspace-a", "principal-a", "brand-a", "account-a", "linkedin", "brand-a"
    )
    return StrategyCapabilityPortV1(
        binding=binding, inventory=values[0], calendar=values[1], drafts=values[2],
        strategy=values[3],
        source_digest=StrategyCapabilityPortV1.source_digest(*values),
        observation_store={} if store is None else store,
    )


def _scope(**extra):
    return {"workspace_id": "workspace-a", "principal_id": "principal-a", **extra}


def _observation(**changes):
    payload = "provider export row 1"
    value = _scope(
        observation_id="obs-a", account_id="account-a", kpi_id="kpi-a",
        horizon_days=30, observed_value=7, sample_size=100, observed_at=100,
        source_ref="export-a", source_payload=payload,
        source_digest=hashlib.sha256(payload.encode()).hexdigest(),
    )
    value.update(changes)
    return value


def test_projection_is_bounded_redacted_and_never_authorizes_action():
    result = _port()._dispatch_authorized("kpi.query", _scope(kpi_id="kpi-a"))
    assert result["redacted"] is True
    assert result["action_authorized"] is False
    assert result["publication_authorized"] is False
    assert "metric" not in result


def test_calendar_readiness_does_not_publish_or_schedule_external_work():
    port = _port()
    result = port._dispatch_authorized("calendar.query", _scope(post_id="post-a"))
    assert result["calendar_ready"] is True
    assert not hasattr(port, "publish")
    assert not hasattr(port, "schedule")
    assert not hasattr(port, "dispatch_external")


def test_missing_approval_cannot_be_projected_as_publish_ready():
    values = list(_sources())
    values[1] = replace(values[1], approvals=())
    with pytest.raises(GovernanceV1Denied, match="unapproved"):
        _port(sources=tuple(values))


def test_tampered_phase10_source_digest_is_denied():
    values = _sources()
    with pytest.raises(GovernanceV1Denied, match="provenance"):
        StrategyCapabilityPortV1(
            binding=StrategyAccountBindingV1(
                "workspace-a", "principal-a", "brand-a", "account-a", "linkedin", "brand-a"
            ),
            inventory=values[0], calendar=values[1], drafts=values[2], strategy=values[3],
            source_digest="0" * 64, observation_store={},
        )


def test_malformed_uncited_research_is_rejected_even_if_dataclass_was_forged():
    values = list(_sources())
    bad_claim = replace(values[3].segments[0].claims[0], source_ref="")
    values[3] = replace(values[3], segments=(replace(values[3].segments[0], claims=(bad_claim,)),))
    with pytest.raises(GovernanceV1ContractError, match="provenance"):
        _port(sources=tuple(values))


def test_cross_workspace_and_principal_are_denied():
    port = _port()
    with pytest.raises(GovernanceV1Denied, match="cross-workspace"):
        port._dispatch_authorized("audience.query", _scope(workspace_id="workspace-b"))
    with pytest.raises(GovernanceV1Denied, match="cross-workspace"):
        port._dispatch_authorized("audience.query", _scope(principal_id="principal-b"))


def test_route_account_mismatch_is_denied():
    values = list(_sources())
    values[1] = replace(
        values[1], posts=(replace(values[1].posts[0], account_id="account-b"),)
    )
    with pytest.raises(GovernanceV1Denied, match="calendar route"):
        _port(sources=tuple(values))


def test_append_is_idempotent_replay_safe_and_stale_safe():
    store = {}
    port = _port(store=store)
    assert port._dispatch_authorized("observation.append", _observation())["status"] == "appended"
    assert port._dispatch_authorized("observation.append", _observation())["status"] == "replayed"
    with pytest.raises(GovernanceV1Denied, match="replay payload"):
        port._dispatch_authorized("observation.append", _observation(observed_value=8))
    with pytest.raises(GovernanceV1Denied, match="stale"):
        port._dispatch_authorized(
            "observation.append", _observation(observation_id="obs-b", observed_at=99)
        )
    assert len(store) == 1


def test_observation_requires_valid_provenance_closed_kpi_and_sample_floor():
    port = _port()
    with pytest.raises(GovernanceV1Denied, match="provenance"):
        port._dispatch_authorized("observation.append", _observation(source_digest="0" * 64))
    with pytest.raises(GovernanceV1ContractError, match="KPI"):
        port._dispatch_authorized("observation.append", _observation(horizon_days=60))
    with pytest.raises(GovernanceV1ContractError, match="sample floor"):
        port._dispatch_authorized("observation.append", _observation(sample_size=99))


def test_no_metric_means_no_action():
    result = _port()._dispatch_authorized("observation.query", _scope(kpi_id="kpi-a"))
    assert result["has_metric"] is False
    assert result["action_authorized"] is False


def test_provider_constructor_is_never_called_and_no_external_post(monkeypatch):
    import core.phase10_provider_connector_v1 as provider_module

    def forbidden(*args, **kwargs):
        raise AssertionError("provider constructor or external call was reached")

    monkeypatch.setattr(provider_module, "create_provider_connector_v1", forbidden)
    port = _port()
    port._dispatch_authorized("audience.query", _scope())
    port._dispatch_authorized("observation.append", _observation())


def test_exact_phase10_types_are_required():
    values = _sources()
    with pytest.raises(GovernanceV1ContractError, match="exact Phase 10"):
        StrategyCapabilityPortV1(
            binding=StrategyAccountBindingV1(
                "workspace-a", "principal-a", "brand-a", "account-a", "linkedin", "brand-a"
            ),
            inventory={"passports": []}, calendar=values[1], drafts=values[2],
            strategy=values[3], source_digest="0" * 64, observation_store={},
        )
