from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from core.operational_goals_v1 import (
    GoalLevelV1,
    OperationalGoalFeatureGateV1,
    OperationalGoalStoreV1,
)
from core.operational_rhythm_v1 import (
    OperationalRhythmContractError,
    OperationalRhythmV1,
    RhythmCadenceV1,
)


OWNER = "owner_primary"
WORKSPACE = "workspace_personal"
NOW = 2_000_000_000.0


def _store(tmp_path: Path) -> OperationalGoalStoreV1:
    return OperationalGoalStoreV1(
        tmp_path / "goals.sqlite3", OperationalGoalFeatureGateV1(True)
    )


def _goal(
    store: OperationalGoalStoreV1,
    *,
    title: str,
    level: GoalLevelV1 = GoalLevelV1.OBJECTIVE,
    parent_id: str | None = None,
    target_at: float | None = None,
    owner: str = OWNER,
    workspace: str = WORKSPACE,
):
    goal = store.create(
        owner_profile_id=owner,
        workspace_id=workspace,
        level=level,
        title=title,
        objective=f"Deliver {title}",
        definition_of_done=("verified",),
        parent_id=parent_id,
        target_at=target_at,
    )
    return store.activate(goal.goal_id)


def test_projection_is_deterministic_bounded_and_read_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective = _goal(store, title="Operational objective", target_at=NOW + 50_000)
    key_result = _goal(
        store,
        title="Measurable result",
        level=GoalLevelV1.KEY_RESULT,
        parent_id=objective.goal_id,
        target_at=NOW + 40_000,
    )
    milestone = _goal(
        store,
        title="Overdue milestone",
        level=GoalLevelV1.MILESTONE,
        parent_id=key_result.goal_id,
        target_at=NOW - 1,
    )
    task = _goal(
        store,
        title="Paused task",
        level=GoalLevelV1.TASK,
        parent_id=milestone.goal_id,
        target_at=NOW + 5_000,
    )
    daily = _goal(
        store,
        title="Immediate action",
        level=GoalLevelV1.DAILY_ACTION,
        parent_id=task.goal_id,
        target_at=NOW + 2_000,
    )
    store.pause(task.goal_id, "owner_paused")

    goals = (objective, key_result, milestone, task, daily)
    before = {
        goal.goal_id: (store.get(goal.goal_id).revision, store.events(goal.goal_id))
        for goal in goals
    }

    rhythm = OperationalRhythmV1(store)
    first = rhythm.project(
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        cadence=RhythmCadenceV1.MIDDAY_CHECK,
        now=NOW,
    ).payload()
    second = rhythm.project(
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        cadence="midday_check",
        now=NOW,
    ).payload()

    assert first == second
    assert first["contract"] == "OnyxOperationalRhythm.v1"
    assert first["cadence"] == "midday_check"
    assert [item["title"] for item in first["focus"]] == [
        "Overdue milestone",
        "Immediate action",
        "Measurable result",
    ]
    assert [item["title"] for item in first["actions"]] == [
        "Immediate action",
        "Overdue milestone",
        "Measurable result",
        "Operational objective",
        "Paused task",
    ]
    assert first["warnings"] == (
        "OVERDUE / Overdue milestone",
        "DUE WITHIN 24H / Immediate action",
        "DUE WITHIN 24H / Measurable result",
        "DUE WITHIN 24H / Operational objective",
        "PAUSED / Paused task",
    )
    assert first["counts"] == {
        "active": 4,
        "paused": 1,
        "overdue": 1,
        "focus": 3,
        "actions": 5,
    }
    assert first["read_only"] is True
    assert first["external_dispatch"] is False
    assert first["goal_mutations"] == 0
    assert first["background_workers"] == 0
    assert first["polling_interval"] is None
    after = {
        goal.goal_id: (store.get(goal.goal_id).revision, store.events(goal.goal_id))
        for goal in goals
    }
    assert after == before


def test_projection_is_scope_isolated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    visible = _goal(store, title="Visible objective", target_at=NOW + 1)
    _goal(
        store,
        title="Other workspace secret",
        target_at=NOW - 1,
        workspace="workspace_other",
    )

    payload = OperationalRhythmV1(store).project(
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        cadence="evening_review",
        now=NOW,
    ).payload()

    assert [item["goal_id"] for item in payload["focus"]] == [visible.goal_id]
    assert "Other workspace secret" not in str(payload)


def test_auto_cadence_uses_local_hour_without_background_work(tmp_path: Path) -> None:
    store = _store(tmp_path)
    local_timezone = datetime.now().astimezone().tzinfo
    morning = datetime(2030, 1, 15, 8, 0, tzinfo=local_timezone).timestamp()
    evening = datetime(2030, 1, 15, 20, 0, tzinfo=local_timezone).timestamp()
    rhythm = OperationalRhythmV1(store)

    assert rhythm.project(
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        now=morning,
    ).cadence is RhythmCadenceV1.MORNING_PLAN
    assert rhythm.project(
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        now=evening,
    ).cadence is RhythmCadenceV1.EVENING_REVIEW
    assert rhythm.background_workers == 0
    assert rhythm.polling_interval is None


@pytest.mark.parametrize("cadence", ["", "weekly", None, 1, True])
def test_invalid_cadence_fails_closed(tmp_path: Path, cadence: object) -> None:
    with pytest.raises(OperationalRhythmContractError, match="cadence"):
        OperationalRhythmV1(_store(tmp_path)).project(
            owner_profile_id=OWNER,
            workspace_id=WORKSPACE,
            cadence=cadence,  # type: ignore[arg-type]
            now=NOW,
        )


@pytest.mark.parametrize("now", [-1.0, float("inf"), float("nan"), True, "now"])
def test_invalid_clock_fails_closed(tmp_path: Path, now: object) -> None:
    with pytest.raises(OperationalRhythmContractError, match="clock"):
        OperationalRhythmV1(_store(tmp_path)).project(
            owner_profile_id=OWNER,
            workspace_id=WORKSPACE,
            now=now,  # type: ignore[arg-type]
        )
