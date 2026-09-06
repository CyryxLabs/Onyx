"""Default-off planner successor over the accepted DayOps V1 read contract."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from core.dayops_live_integration_v1 import (
    DayOpsExecutionV1,
    DayOpsLiveIntegrationV1,
)
from core.dayops_planner_v1 import plan_dayops_v1

FEATURE_FLAG: Final = "ONYX_DAYOPS_PLANNER_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxDayOpsLiveIntegration.v2"


class DayOpsLiveV2ContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DayOpsPlannerFeatureGateV2:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise DayOpsLiveV2ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> DayOpsPlannerFeatureGateV2:
        source = os.environ if environ is None else environ
        value = source.get(FEATURE_FLAG)
        return cls(type(value) is str and value == ENABLED_VALUE)


class DayOpsLiveIntegrationV2:
    __slots__ = ("_base", "_gate")

    def __init__(
        self,
        *,
        base: DayOpsLiveIntegrationV1,
        gate: DayOpsPlannerFeatureGateV2,
    ) -> None:
        if type(base) is not DayOpsLiveIntegrationV1:
            raise DayOpsLiveV2ContractError("exact V1 integration required")
        if type(gate) is not DayOpsPlannerFeatureGateV2:
            raise DayOpsLiveV2ContractError("sealed planner gate required")
        self._base = base
        self._gate = gate

    def execute(
        self,
        arguments: Mapping[str, object] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> DayOpsExecutionV1:
        result = self._base.execute(arguments, environ=environ, now=now)
        if not self._gate.enabled or result.status != "completed":
            return result
        try:
            selected_now = datetime.now(timezone.utc) if now is None else now
            if type(selected_now) is not datetime or selected_now.tzinfo is None:
                raise DayOpsLiveV2ContractError("timezone-aware clock is required")
            source = os.environ if environ is None else environ
            timezone_name = source.get("ONYX_DAYOPS_IANA_TIMEZONE", "")
            plan = plan_dayops_v1(
                result.result, timezone_name=timezone_name, now=selected_now
            )
        except Exception as exc:
            return DayOpsExecutionV1(
                "failed",
                {
                    "status": "failed",
                    "read_only": True,
                    "result": "DayOps planning failed safely.",
                },
                type(exc).__name__,
            )
        enriched = dict(result.result)
        enriched["planner"] = plan.to_dict()
        enriched["planner"]["plan_sha256"] = plan.plan_sha256
        enriched["planner_candidate"] = True
        return DayOpsExecutionV1("completed", enriched)


def create_dayops_live_integration_v2(
    *,
    base: DayOpsLiveIntegrationV1,
    gate: DayOpsPlannerFeatureGateV2 | None = None,
    environ: Mapping[str, str] | None = None,
) -> DayOpsLiveIntegrationV2:
    selected = (
        DayOpsPlannerFeatureGateV2.from_environ(environ) if gate is None else gate
    )
    return DayOpsLiveIntegrationV2(base=base, gate=selected)


__all__ = [
    "DayOpsLiveIntegrationV2",
    "DayOpsLiveV2ContractError",
    "DayOpsPlannerFeatureGateV2",
    "FEATURE_FLAG",
    "SCHEMA",
    "create_dayops_live_integration_v2",
]
