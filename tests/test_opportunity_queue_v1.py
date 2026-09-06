from __future__ import annotations

from pathlib import Path

import pytest

from core.opportunity_economics_v1 import EconomicEvidenceV1, OpportunityEconomicsGuardV1
from core.opportunity_queue_v1 import OpportunityQueueV1, OpportunityQueueV1Denied
from core.web_opportunity_research_v1 import ResearchEvidenceV1


TOKEN = "owner-approval-token-v1"


def _evidence(identifier: str, host: str, *, signals=()) -> ResearchEvidenceV1:
    return ResearchEvidenceV1(
        identifier,
        f"https://{host}/report",
        host,
        "Observed market opportunity",
        "Evidence-backed demand signal",
        "2026-09-04",
        "2026-09-04T12:00:00+00:00",
        signals,
    )


def _economics(cost: int = 200_000):
    return OpportunityEconomicsGuardV1().evaluate(
        revenue=EconomicEvidenceV1(1_000_000, "USD", "contract:1", True),
        direct_variable_cost=EconomicEvidenceV1(cost, "USD", "quote:1", True),
    )


def _queue(tmp_path: Path) -> OpportunityQueueV1:
    return OpportunityQueueV1(
        tmp_path / "opportunities.sqlite3",
        owner_profile_id="owner-1",
        workspace_id="workspace-1",
        owner_approval_token=TOKEN,
        clock=lambda: 100,
    )


def test_two_sources_verified_economics_and_owner_approval_are_all_required(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    candidate = queue.enqueue(
        title="Governed AI operations service",
        score=82,
        evidence=(_evidence("e1", "one.example"), _evidence("e2", "two.example")),
        economics=_economics(),
    )
    assert candidate.state == "candidate"
    assert candidate.independent_publishers == 2
    assert candidate.promotion_eligible is True
    assert candidate.actionable is False
    with pytest.raises(OpportunityQueueV1Denied, match="owner approval"):
        queue.approve_for_review(candidate.opportunity_id, owner_approval_token="wrong-token-xxxxxxxx")
    approved = queue.approve_for_review(candidate.opportunity_id, owner_approval_token=TOKEN)
    assert approved.state == "approved_review"
    assert approved.actionable is False


@pytest.mark.parametrize(
    ("score", "evidence", "cost"),
    [
        (59, (_evidence("e1", "one.example"), _evidence("e2", "two.example")), 200_000),
        (90, (_evidence("e1", "one.example"),), 200_000),
        (90, (_evidence("e1", "one.example"), _evidence("e2", "two.example")), 300_000),
        (90, (_evidence("e1", "one.example", signals=("tool_coercion",)), _evidence("e2", "two.example")), 200_000),
    ],
)
def test_failed_gates_never_promote(tmp_path: Path, score, evidence, cost) -> None:
    queue = _queue(tmp_path)
    candidate = queue.enqueue(
        title="Candidate", score=score, evidence=evidence, economics=_economics(cost)
    )
    assert candidate.promotion_eligible is False
    with pytest.raises(OpportunityQueueV1Denied, match="promotion gates"):
        queue.approve_for_review(candidate.opportunity_id, owner_approval_token=TOKEN)


def test_revoke_preserves_non_actionable_audit_record(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    candidate = queue.enqueue(
        title="Candidate",
        score=80,
        evidence=(_evidence("e1", "one.example"), _evidence("e2", "two.example")),
        economics=_economics(),
    )
    revoked = queue.revoke(candidate.opportunity_id)
    assert revoked.state == "revoked"
    assert revoked.actionable is False

