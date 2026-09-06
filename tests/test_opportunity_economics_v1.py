from __future__ import annotations

import pytest

from core.opportunity_economics_v1 import (
    EconomicEvidenceV1,
    OpportunityEconomicsGuardV1,
    OpportunityEconomicsV1ContractError,
)


def evidence(amount: int, source: str, *, verified: bool = True, currency: str = "USD"):
    return EconomicEvidenceV1(amount, currency, source, verified)


def test_verified_margin_meets_eighty_percent_guardrail() -> None:
    decision = OpportunityEconomicsGuardV1().evaluate(
        revenue=evidence(1_000_000, "contract:1"),
        direct_variable_cost=evidence(200_000, "invoice:1"),
    )
    assert decision.status == "verified"
    assert decision.gross_margin_bp == 8_000
    assert decision.meets_target is True
    assert decision.recommendation_eligible is True


def test_below_target_is_truthful_and_not_recommendation_eligible() -> None:
    decision = OpportunityEconomicsGuardV1().evaluate(
        revenue=evidence(1_000_000, "contract:1"),
        direct_variable_cost=evidence(250_001, "invoice:1"),
    )
    assert decision.reason_code == "below_target"
    assert decision.gross_margin_bp == 7_499
    assert decision.recommendation_eligible is False


@pytest.mark.parametrize(
    ("revenue", "cost", "reason"),
    [
        (None, None, "missing_economic_evidence"),
        (evidence(1_000, "quote", verified=False), evidence(100, "cost"), "unverified_economic_evidence"),
        (evidence(1_000, "quote", currency="USD"), evidence(100, "cost", currency="CAD"), "currency_mismatch"),
        (evidence(0, "quote"), evidence(0, "cost"), "non_positive_revenue"),
    ],
)
def test_unknown_inputs_never_invent_a_margin(revenue, cost, reason: str) -> None:
    decision = OpportunityEconomicsGuardV1().evaluate(
        revenue=revenue, direct_variable_cost=cost
    )
    assert decision.status == "unknown"
    assert decision.reason_code == reason
    assert decision.gross_margin_bp is None
    assert decision.meets_target is None
    assert decision.recommendation_eligible is False


def test_economic_contract_rejects_bad_currency_and_target() -> None:
    with pytest.raises(OpportunityEconomicsV1ContractError, match="currency"):
        evidence(100, "source", currency="usd")
    with pytest.raises(OpportunityEconomicsV1ContractError, match="target"):
        OpportunityEconomicsGuardV1().evaluate(
            revenue=None, direct_variable_cost=None, target_margin_bp=10_001
        )

