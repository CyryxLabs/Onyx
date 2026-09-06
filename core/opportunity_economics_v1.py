"""Evidence-bound economics guard for Onyx opportunity candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final


SCHEMA: Final = "OnyxOpportunityEconomics.v1"
DEFAULT_MARGIN_TARGET_BP: Final = 8_000
MAX_AMOUNT_MICRO: Final = 10**18


class OpportunityEconomicsV1ContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EconomicEvidenceV1:
    amount_micro: int
    currency: str
    source_id: str
    verified: bool

    def __post_init__(self) -> None:
        if (
            type(self.amount_micro) is not int
            or not 0 <= self.amount_micro <= MAX_AMOUNT_MICRO
        ):
            raise OpportunityEconomicsV1ContractError("amount is invalid")
        if (
            type(self.currency) is not str
            or len(self.currency) != 3
            or not self.currency.isalpha()
            or self.currency != self.currency.upper()
        ):
            raise OpportunityEconomicsV1ContractError("currency is invalid")
        if (
            type(self.source_id) is not str
            or not self.source_id
            or len(self.source_id) > 256
            or self.source_id.strip() != self.source_id
        ):
            raise OpportunityEconomicsV1ContractError("source_id is invalid")
        if type(self.verified) is not bool:
            raise OpportunityEconomicsV1ContractError("verified must be exact bool")


@dataclass(frozen=True, slots=True)
class OpportunityEconomicDecisionV1:
    schema: str
    status: str
    reason_code: str
    currency: str | None
    revenue_micro: int | None
    direct_variable_cost_micro: int | None
    gross_profit_micro: int | None
    gross_margin_bp: int | None
    target_margin_bp: int
    meets_target: bool | None
    recommendation_eligible: bool
    evidence_source_ids: tuple[str, ...]
    decision_sha256: str


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


class OpportunityEconomicsGuardV1:
    """Compute margin only from complete, verified, same-currency evidence."""

    def evaluate(
        self,
        *,
        revenue: EconomicEvidenceV1 | None,
        direct_variable_cost: EconomicEvidenceV1 | None,
        target_margin_bp: int = DEFAULT_MARGIN_TARGET_BP,
    ) -> OpportunityEconomicDecisionV1:
        if type(target_margin_bp) is not int or not 0 <= target_margin_bp <= 10_000:
            raise OpportunityEconomicsV1ContractError("target margin is invalid")
        base: dict[str, object] = {
            "schema": SCHEMA,
            "target_margin_bp": target_margin_bp,
        }
        if revenue is None or direct_variable_cost is None:
            return self._unknown(base, "missing_economic_evidence")
        if type(revenue) is not EconomicEvidenceV1 or type(direct_variable_cost) is not EconomicEvidenceV1:
            raise OpportunityEconomicsV1ContractError("exact economic evidence required")
        sources = (revenue.source_id, direct_variable_cost.source_id)
        if not revenue.verified or not direct_variable_cost.verified:
            return self._unknown(base, "unverified_economic_evidence", sources)
        if revenue.currency != direct_variable_cost.currency:
            return self._unknown(base, "currency_mismatch", sources)
        if revenue.amount_micro <= 0:
            return self._unknown(base, "non_positive_revenue", sources)
        gross_profit = revenue.amount_micro - direct_variable_cost.amount_micro
        margin_bp = (gross_profit * 10_000) // revenue.amount_micro
        meets = margin_bp >= target_margin_bp
        payload = base | {
            "status": "verified",
            "reason_code": "target_met" if meets else "below_target",
            "currency": revenue.currency,
            "revenue_micro": revenue.amount_micro,
            "direct_variable_cost_micro": direct_variable_cost.amount_micro,
            "gross_profit_micro": gross_profit,
            "gross_margin_bp": margin_bp,
            "meets_target": meets,
            "recommendation_eligible": meets,
            "evidence_source_ids": sources,
        }
        return OpportunityEconomicDecisionV1(**payload, decision_sha256=_digest(payload))

    @staticmethod
    def _unknown(
        base: dict[str, object], reason: str, sources: tuple[str, ...] = ()
    ) -> OpportunityEconomicDecisionV1:
        payload = base | {
            "status": "unknown",
            "reason_code": reason,
            "currency": None,
            "revenue_micro": None,
            "direct_variable_cost_micro": None,
            "gross_profit_micro": None,
            "gross_margin_bp": None,
            "meets_target": None,
            "recommendation_eligible": False,
            "evidence_source_ids": sources,
        }
        return OpportunityEconomicDecisionV1(**payload, decision_sha256=_digest(payload))


__all__ = [
    "DEFAULT_MARGIN_TARGET_BP",
    "EconomicEvidenceV1",
    "OpportunityEconomicDecisionV1",
    "OpportunityEconomicsGuardV1",
    "OpportunityEconomicsV1ContractError",
    "SCHEMA",
]
