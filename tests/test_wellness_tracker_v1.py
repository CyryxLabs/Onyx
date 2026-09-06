from __future__ import annotations

from pathlib import Path

import pytest

from core.clipboard_intelligence_v1 import StaticOwnerScopeAdapterV1
from core.wellness_tracker_v1 import WellnessTrackerDenied, WellnessTrackerStoreV1


OWNER = "owner-1"
WORKSPACE = "workspace-1"


def store(tmp_path: Path) -> WellnessTrackerStoreV1:
    return WellnessTrackerStoreV1(
        tmp_path / "wellness.sqlite3",
        owner_scope=StaticOwnerScopeAdapterV1(OWNER, WORKSPACE),
    )


def test_create_list_correct_remove_and_idempotency(tmp_path: Path) -> None:
    subject = store(tmp_path)
    first = subject.create_calorie(
        OWNER, WORKSPACE, calories=450, occurred_at="2026-08-23T12:00:00-04:00",
        timezone_name="America/New_York", idempotency_key="meal-1",
    )
    replay = subject.create_calorie(
        OWNER, WORKSPACE, calories=450, occurred_at="2026-08-23T12:00:00-04:00",
        timezone_name="America/New_York", idempotency_key="meal-1",
    )
    assert replay == first
    with pytest.raises(WellnessTrackerDenied, match="conflicts"):
        subject.create_calorie(
            OWNER, WORKSPACE, calories=451, occurred_at="2026-08-23T12:00:00-04:00",
            timezone_name="America/New_York", idempotency_key="meal-1",
        )
    corrected = subject.correct(first.entry_id, OWNER, WORKSPACE, value=500)
    assert corrected.value == 500 and corrected.revision == 2
    subject.remove(first.entry_id, OWNER, WORKSPACE)
    assert subject.list_entries(OWNER, WORKSPACE) == ()


def test_timezone_daily_totals_and_exercise_units(tmp_path: Path) -> None:
    subject = store(tmp_path)
    subject.create_calorie(
        OWNER, WORKSPACE, calories=200, occurred_at="2026-08-24T03:30:00+00:00",
        timezone_name="America/New_York", idempotency_key="late-meal",
    )
    subject.create_exercise(
        OWNER, WORKSPACE, activity="Run", value=30, unit="minutes",
        occurred_at="2026-08-23T18:00:00-04:00", timezone_name="America/New_York",
        idempotency_key="run-1",
    )
    totals = subject.totals(
        OWNER, WORKSPACE, day="2026-08-23", timezone_name="America/New_York"
    )
    assert totals["calories_kcal"] == 200
    assert totals["exercise"] == {"minutes": 30}
    assert "not medical advice" in totals["limitation"]


def test_vision_estimate_is_draft_until_explicit_confirmation(tmp_path: Path) -> None:
    subject = store(tmp_path)
    draft = subject.create_vision_estimate(
        OWNER, WORKSPACE, kind="calorie", value=325,
        occurred_at="2026-08-23T12:00:00-04:00",
        timezone_name="America/New_York", idempotency_key="vision-1",
    )
    assert draft.status == "draft" and draft.source == "vision_estimate"
    assert subject.totals(
        OWNER, WORKSPACE, day="2026-08-23", timezone_name="America/New_York"
    )["calories_kcal"] == 0
    assert subject.confirm(draft.entry_id, OWNER, WORKSPACE).status == "confirmed"
    assert subject.totals(
        OWNER, WORKSPACE, day="2026-08-23", timezone_name="America/New_York"
    )["calories_kcal"] == 325


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.create_calorie(
            OWNER, WORKSPACE, calories=-1, occurred_at="2026-08-23T12:00:00-04:00",
            timezone_name="America/New_York", idempotency_key="bad-1"
        ),
        lambda s: s.create_exercise(
            OWNER, WORKSPACE, activity="Run", value=1, unit="watts",
            occurred_at="2026-08-23T12:00:00-04:00",
            timezone_name="America/New_York", idempotency_key="bad-2"
        ),
        lambda s: s.create_calorie(
            OWNER, WORKSPACE, calories=1, occurred_at="2026-08-23T12:00:00",
            timezone_name="America/New_York", idempotency_key="bad-3"
        ),
    ],
)
def test_invalid_values_units_and_naive_time_are_denied(tmp_path: Path, call) -> None:
    with pytest.raises(WellnessTrackerDenied):
        call(store(tmp_path))


def test_scope_isolation_is_adapter_enforced(tmp_path: Path) -> None:
    subject = store(tmp_path)
    with pytest.raises(WellnessTrackerDenied, match="adapter"):
        subject.list_entries(OWNER, "workspace-2")
