from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.opportunity_monitor_v1 import OpportunityMonitorV1
from core.web_opportunity_research_v1 import WebOpportunityResearchV1


class Provider:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, *, mode: str, max_results: int):
        self.calls += 1
        assert query == "AI operations demand"
        assert mode == "news"
        assert max_results == 8
        return (
            {
                "title": "AI operations demand expands for enterprises",
                "body": "Enterprise AI operations demand shows rising growth",
                "url": "https://one.example/report/1",
                "source": "One",
                "date": "2026-09-04T12:00:00+00:00",
            },
            {
                "title": "Enterprise AI operations demand declines",
                "body": "A survey reports falling demand for AI operations",
                "url": "https://two.example/report/2",
                "source": "Two",
                "date": "2026-09-04T11:00:00+00:00",
            },
            {
                "title": "Unapproved host",
                "body": "Must be filtered by the exact source registry",
                "url": "https://outside.example/report/3",
            },
        )


def _monitor(tmp_path: Path, now: list[int]) -> OpportunityMonitorV1:
    return OpportunityMonitorV1(
        tmp_path / "monitor.sqlite3",
        owner_profile_id="owner-1",
        workspace_id="workspace-1",
        clock=lambda: now[0],
    )


def test_scheduled_monitor_is_allowlisted_leased_and_non_actionable(tmp_path: Path) -> None:
    now = [int(datetime(2026, 9, 4, 13, tzinfo=timezone.utc).timestamp())]
    monitor = _monitor(tmp_path, now)
    policy = monitor.configure(
        schedule_id="ai-operations",
        query="AI operations demand",
        allowed_domains=("one.example", "two.example"),
        interval_seconds=900,
    )
    assert policy.next_due_at == now[0]
    provider = Provider()
    researcher = WebOpportunityResearchV1(
        provider,
        clock=lambda: datetime.fromtimestamp(now[0], timezone.utc),
    )
    digests = monitor.run_due(researcher)
    assert len(digests) == 1
    digest = digests[0]
    assert provider.calls == 1
    assert len(digest.assessments) == 2
    assert digest.fresh_count == 2
    assert digest.contradiction_count == 2
    assert digest.promotion_authorized is False
    assert digest.external_action_authorized is False
    assert monitor.run_due(researcher) == ()

    now[0] += 900
    assert len(monitor.run_due(researcher)) == 1
    assert provider.calls == 2


def test_kill_is_durable_and_resume_preserves_the_same_policy(tmp_path: Path) -> None:
    now = [100_000]
    monitor = _monitor(tmp_path, now)
    monitor.configure(
        schedule_id="market",
        query="AI operations demand",
        allowed_domains=("one.example",),
    )
    monitor.kill()
    assert monitor.killed() is True
    provider = Provider()
    researcher = WebOpportunityResearchV1(
        provider,
        clock=lambda: datetime.fromtimestamp(now[0], timezone.utc),
    )
    assert monitor.run_due(researcher) == ()
    assert provider.calls == 0
    monitor.resume()
    assert monitor.killed() is False
    assert len(monitor.run_due(researcher)) == 1


def test_owner_and_workspace_scopes_cannot_overwrite_each_other(tmp_path: Path) -> None:
    now = [100_000]
    first = _monitor(tmp_path, now)
    second = OpportunityMonitorV1(
        tmp_path / "monitor.sqlite3",
        owner_profile_id="owner-2",
        workspace_id="workspace-2",
        clock=lambda: now[0],
    )
    first.configure(
        schedule_id="same-id",
        query="AI operations demand",
        allowed_domains=("one.example",),
    )
    second.configure(
        schedule_id="same-id",
        query="Different market demand",
        allowed_domains=("two.example",),
    )
    assert first.policies()[0].query == "AI operations demand"
    assert second.policies()[0].query == "Different market demand"
