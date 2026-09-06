"""Read-only daily rhythm over Onyx's evidence-gated operational goals.

The rhythm is a deterministic projection. It does not call a model, change a
goal score, create a mission, schedule a worker or dispatch external work.
Goal truth remains exclusively owned by ``OperationalGoalStoreV1`` and Phase 6
verification receipts.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from core.operational_goals_v1 import (
    GoalLevelV1,
    GoalProjectionV1,
    GoalStatusV1,
    OperationalGoalStoreV1,
)


class OperationalRhythmContractError(ValueError):
    """The caller supplied a non-canonical rhythm request."""


class RhythmCadenceV1(str, Enum):
    AUTO = "auto"
    MORNING_PLAN = "morning_plan"
    MIDDAY_CHECK = "midday_check"
    EVENING_REVIEW = "evening_review"


@dataclass(frozen=True, slots=True)
class RhythmGoalItemV1:
    goal_id: str
    title: str
    level: str
    status: str
    health: str
    score: float
    target_at: float | None

    def payload(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "level": self.level,
            "status": self.status,
            "health": self.health,
            "score": self.score,
            "target_at": self.target_at,
        }


@dataclass(frozen=True, slots=True)
class OperationalRhythmProjectionV1:
    cadence: RhythmCadenceV1
    generated_at: float
    local_date: str
    local_timezone: str
    focus: tuple[RhythmGoalItemV1, ...]
    actions: tuple[RhythmGoalItemV1, ...]
    warnings: tuple[str, ...]
    counts: dict[str, int]

    def payload(self) -> dict[str, object]:
        return {
            "contract": "OnyxOperationalRhythm.v1",
            "status": "ready",
            "cadence": self.cadence.value,
            "generated_at": self.generated_at,
            "local_date": self.local_date,
            "local_timezone": self.local_timezone,
            "focus": tuple(item.payload() for item in self.focus),
            "actions": tuple(item.payload() for item in self.actions),
            "warnings": self.warnings,
            "counts": dict(self.counts),
            "read_only": True,
            "external_dispatch": False,
            "goal_mutations": 0,
            "background_workers": 0,
            "polling_interval": None,
        }


_LEVEL_PRIORITY = {
    GoalLevelV1.DAILY_ACTION: 0,
    GoalLevelV1.TASK: 1,
    GoalLevelV1.MILESTONE: 2,
    GoalLevelV1.KEY_RESULT: 3,
    GoalLevelV1.OBJECTIVE: 4,
}
_HEALTH_PRIORITY = {"overdue": 0, "on_track": 1, "paused": 2}


class OperationalRhythmV1:
    """Build bounded morning/midday/evening projections with zero mutation."""

    def __init__(self, goals: OperationalGoalStoreV1) -> None:
        if type(goals) is not OperationalGoalStoreV1:
            raise OperationalRhythmContractError(
                "exact OperationalGoalStoreV1 is required"
            )
        self._goals = goals
        self.background_workers = 0
        self.polling_interval = None

    @staticmethod
    def _cadence(value: RhythmCadenceV1 | str, local_hour: int) -> RhythmCadenceV1:
        try:
            selected = value if type(value) is RhythmCadenceV1 else RhythmCadenceV1(value)
        except (TypeError, ValueError) as exc:
            raise OperationalRhythmContractError("rhythm cadence is invalid") from exc
        if selected is not RhythmCadenceV1.AUTO:
            return selected
        if local_hour < 12:
            return RhythmCadenceV1.MORNING_PLAN
        if local_hour < 18:
            return RhythmCadenceV1.MIDDAY_CHECK
        return RhythmCadenceV1.EVENING_REVIEW

    @staticmethod
    def _item(projection: GoalProjectionV1) -> RhythmGoalItemV1:
        goal = projection.goal
        return RhythmGoalItemV1(
            goal_id=goal.goal_id,
            title=goal.title,
            level=goal.level.value,
            status=goal.status.value,
            health=projection.health,
            score=projection.score,
            target_at=goal.target_at,
        )

    @staticmethod
    def _focus_key(item: GoalProjectionV1) -> tuple[object, ...]:
        goal = item.goal
        return (
            _HEALTH_PRIORITY.get(item.health, 9),
            1 if goal.status is GoalStatusV1.PAUSED else 0,
            math.inf if goal.target_at is None else goal.target_at,
            _LEVEL_PRIORITY[goal.level],
            goal.created_at,
            goal.goal_id,
        )

    @staticmethod
    def _action_key(item: GoalProjectionV1) -> tuple[object, ...]:
        goal = item.goal
        return (
            1 if goal.status is GoalStatusV1.PAUSED else 0,
            _LEVEL_PRIORITY[goal.level],
            _HEALTH_PRIORITY.get(item.health, 9),
            math.inf if goal.target_at is None else goal.target_at,
            goal.created_at,
            goal.goal_id,
        )

    def project(
        self,
        *,
        owner_profile_id: str,
        workspace_id: str,
        cadence: RhythmCadenceV1 | str = RhythmCadenceV1.AUTO,
        now: float | None = None,
    ) -> OperationalRhythmProjectionV1:
        if now is None:
            timestamp = time.time()
        elif isinstance(now, bool) or not isinstance(now, (int, float)):
            raise OperationalRhythmContractError("rhythm clock is invalid")
        else:
            timestamp = float(now)
        if not math.isfinite(timestamp) or timestamp < 0:
            raise OperationalRhythmContractError("rhythm clock is invalid")

        local = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()
        selected = self._cadence(cadence, local.hour)
        goals = self._goals.attention_queue(
            owner_profile_id=owner_profile_id,
            workspace_id=workspace_id,
            now=timestamp,
        )
        focus = tuple(self._item(item) for item in sorted(goals, key=self._focus_key)[:3])
        actions = tuple(
            self._item(item) for item in sorted(goals, key=self._action_key)[:5]
        )

        warnings: list[str] = []
        for item in sorted(goals, key=self._focus_key):
            goal = item.goal
            if item.health == "overdue":
                warnings.append(f"OVERDUE / {goal.title}")
            elif goal.status is GoalStatusV1.PAUSED:
                warnings.append(f"PAUSED / {goal.title}")
            elif goal.target_at is not None and goal.target_at - timestamp <= 86_400:
                warnings.append(f"DUE WITHIN 24H / {goal.title}")
            if len(warnings) == 8:
                break

        counts = {
            "active": sum(
                item.goal.status is GoalStatusV1.ACTIVE for item in goals
            ),
            "paused": sum(
                item.goal.status is GoalStatusV1.PAUSED for item in goals
            ),
            "overdue": sum(item.health == "overdue" for item in goals),
            "focus": len(focus),
            "actions": len(actions),
        }
        return OperationalRhythmProjectionV1(
            cadence=selected,
            generated_at=timestamp,
            local_date=local.date().isoformat(),
            local_timezone=str(local.tzinfo or "local"),
            focus=focus,
            actions=actions,
            warnings=tuple(warnings),
            counts=counts,
        )


__all__ = [
    "OperationalRhythmContractError",
    "OperationalRhythmProjectionV1",
    "OperationalRhythmV1",
    "RhythmCadenceV1",
    "RhythmGoalItemV1",
]
