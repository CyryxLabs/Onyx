"""Plan-and-attest-only router for GovernedCapabilityHostV1 bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from core.governance_nucleus_v1 import GovernanceV1ContractError, SessionCapabilityV1
from core.governed_capability_host_v1 import ActionBinding, GovernedCapabilityHostV1


def _digest(value: object) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GovernanceV1ContractError("router plan is not canonical JSON") from exc
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class GovernedRoutePlanV1:
    binding: ActionBinding
    plan_digest: str
    dispatch_authority: str = "GovernedCapabilityHostV1-only"


class UnifiedRouterV1:
    """Create and attest exact host bindings; this type has no dispatch method."""

    def __init__(self, host: GovernedCapabilityHostV1) -> None:
        if type(host) is not GovernedCapabilityHostV1:
            raise GovernanceV1ContractError("exact GovernedCapabilityHostV1 is required")
        self._host = host

    def plan(
        self,
        session: SessionCapabilityV1,
        capability: str,
        operation: str,
        arguments: Mapping[str, object],
    ) -> GovernedRoutePlanV1:
        binding = self._host.bind(session, capability, operation, arguments)
        return GovernedRoutePlanV1(binding, _digest(asdict(binding)))

    def attest(self, plan: GovernedRoutePlanV1) -> bool:
        if type(plan) is not GovernedRoutePlanV1:
            raise GovernanceV1ContractError("exact GovernedRoutePlanV1 is required")
        return plan.dispatch_authority == "GovernedCapabilityHostV1-only" and _digest(asdict(plan.binding)) == plan.plan_digest


__all__ = ["GovernedRoutePlanV1", "UnifiedRouterV1"]
