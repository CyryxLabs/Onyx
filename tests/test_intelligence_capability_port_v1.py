"""Adversarial tests for the provider-free intelligence capability port."""

from types import SimpleNamespace

import pytest

from core.capability_ports.intelligence_v1 import (
    IntelligenceCapabilityPortV1,
    IntelligenceSourceGrantV1,
)
from core.governance_nucleus_v1 import GovernanceV1Denied
from core.phase7_company_graph_v1 import CompanyGraphProjectorV1
from core.phase7_founder_command_v1 import FounderCommandGeneratorV1
from core.phase9_intelligence_ingestion_v1 import IntelligenceIngestionSessionV1
from core.phase9_opportunity_scoring_v1 import OpportunityScoringSessionV1


NOW = 2_000_000


def _engines(monkeypatch, *, empty=False):
    projector = object.__new__(CompanyGraphProjectorV1)
    projector._workspace_id = "workspace-a"
    projector._principal_id = "principal-a"
    founder = object.__new__(FounderCommandGeneratorV1)
    founder._workspace_id = "workspace-a"
    founder._principal_id = "principal-a"
    ingestion = object.__new__(IntelligenceIngestionSessionV1)
    ingestion._now_epoch_s = lambda: NOW // 1000
    scoring = object.__new__(OpportunityScoringSessionV1)
    graph = SimpleNamespace(
        graph_sha256="a" * 64,
        items=() if empty else (SimpleNamespace(claim_id="claim-current"),),
        contradictions=() if empty else (("claim-old", "claim-current"),),
        supersessions=() if empty else (("claim-old", "claim-current"),),
    )
    monkeypatch.setattr(CompanyGraphProjectorV1, "project", lambda *_a, **_k: graph)
    monkeypatch.setattr(
        FounderCommandGeneratorV1,
        "generate",
        lambda *_a, **kw: SimpleNamespace(
            brief_sha256=("d" if kw["cadence"] == "daily" else "w") * 64,
            items=graph.items,
            abstentions=("no evidence-linked action",) if empty else (),
            recommended_top_actions=(),
        ),
    )
    monkeypatch.setattr(
        IntelligenceIngestionSessionV1,
        "ingest",
        lambda _self, rows: SimpleNamespace(
            items=tuple(
                SimpleNamespace(item_id=row["item_id"], duplicate_of=None) for row in rows
            )
        ),
    )
    monkeypatch.setattr(
        OpportunityScoringSessionV1,
        "score_batch",
        lambda _self, rows: tuple(
            SimpleNamespace(
                opportunity_id=row["opportunity_id"],
                rank=index + 1,
                total_score=row.get("total_score", 50),
                band="consider",
            )
            for index, row in enumerate(sorted(rows, key=lambda row: row["opportunity_id"]))
        ),
    )
    return projector, founder, ingestion, scoring


def _port(monkeypatch, *, url="https://example.com/report", fresh_until=NOW + 1, empty=False):
    projector, founder, ingestion, scoring = _engines(monkeypatch, empty=empty)
    intelligence = () if empty else (
        {"item_id": "intel-a", "source_id": "source-a", "url": url},
    )
    opportunities = () if empty else (
        {"opportunity_id": "opp-b", "total_score": 90},
        {"opportunity_id": "opp-a", "total_score": 90},
    )
    return IntelligenceCapabilityPortV1(
        workspace_id="workspace-a",
        principal_id="principal-a",
        projector=projector,
        founder=founder,
        ingestion=ingestion,
        scoring=scoring,
        assertions=(),
        intelligence_items=intelligence,
        opportunities=opportunities,
        source_grants=() if empty else (
            IntelligenceSourceGrantV1(
                "source-a", "https://example.com/report", "licensed",
                "workspace-a", "principal-a", fresh_until,
            ),
        ),
        now_ms=lambda: NOW,
    )


def _scope(**changes):
    value = {"workspace_id": "workspace-a", "principal_id": "principal-a"}
    value.update(changes)
    return value


def test_cross_workspace_is_denied(monkeypatch):
    with pytest.raises(GovernanceV1Denied, match="cross-workspace"):
        _port(monkeypatch)._dispatch_authorized(
            "claims.query", _scope(workspace_id="workspace-b")
        )


def test_forged_citation_is_denied(monkeypatch):
    with pytest.raises(GovernanceV1Denied, match="provenance"):
        _port(monkeypatch, url="https://example.com/forged")._dispatch_authorized(
            "claims.query", _scope()
        )


def test_redirect_or_route_escape_is_denied(monkeypatch):
    with pytest.raises(GovernanceV1Denied, match="route escape"):
        _port(monkeypatch, url="https://example.com/a/%2e%2e/private")._dispatch_authorized(
            "claims.query", _scope()
        )


def test_stale_source_and_superseded_conflict_fail_closed(monkeypatch):
    with pytest.raises(GovernanceV1Denied, match="freshness"):
        _port(monkeypatch, fresh_until=NOW - 1)._dispatch_authorized(
            "conflicts.query", _scope()
        )
    result = _port(monkeypatch)._dispatch_authorized("conflicts.query", _scope())
    assert result["count"] == 0
    assert result["stale_conflicts_excluded"] is True


def test_score_is_advisory_and_cannot_act(monkeypatch):
    port = _port(monkeypatch)
    result = port._dispatch_authorized("opportunities.query", _scope())
    assert [row[0] for row in result["ranking"]] == ["opp-a", "opp-b"]
    assert result["action_authorized"] is False
    assert result["write_authorized"] is False
    assert result["dispatch_authorized"] is False
    assert result["schedule_authorized"] is False
    assert not any(hasattr(port, name) for name in ("write", "dispatch_external", "schedule"))


def test_daily_and_weekly_briefs_are_deterministic(monkeypatch):
    port = _port(monkeypatch)
    daily_a = port._dispatch_authorized("brief.daily", _scope())
    daily_b = port._dispatch_authorized("brief.daily", _scope())
    weekly = port._dispatch_authorized("brief.weekly", _scope())
    assert daily_a == daily_b
    assert daily_a["cadence"] == "daily"
    assert weekly["cadence"] == "weekly"
    assert daily_a["projection_digest"] != weekly["projection_digest"]


def test_empty_state_is_bounded_redacted_and_side_effect_free(monkeypatch):
    port = _port(monkeypatch, empty=True)
    for operation in ("claims.query", "conflicts.query", "opportunities.query", "brief.daily"):
        result = port._dispatch_authorized(operation, _scope())
        assert result["empty"] is True
        assert result["count"] == 0
        assert result["redacted"] is True
        assert result["read_only"] is True
        assert result["provider_dispatch"] is False
