from __future__ import annotations

from pathlib import Path

import pytest

from core.event_awareness_v1 import (
    AwarenessDenied,
    AwarenessPolicyV1,
    AwarenessQueueFull,
    AwarenessSignalV1,
    EventDrivenAwarenessV1,
    SignalKindV1,
)
from core.context_graph_v1 import ContextGraphFeatureGateV1, ContextGraphStoreV1
from core.operational_goals_v1 import (
    GoalLevelV1,
    OperationalGoalFeatureGateV1,
    OperationalGoalStoreV1,
)


def _policy(**overrides):
    values = {
        "allowed_sources": ("native.window.events", "native.workspace.events"),
        "max_queue": 8,
        "max_history": 32,
        "max_events_per_minute": 20,
        "max_clock_skew_seconds": 10.0,
        "retention_seconds": 3_600.0,
        "context_switch_threshold": 3,
    }
    values.update(overrides)
    return AwarenessPolicyV1(**values)


def _signal(
    *,
    kind: SignalKindV1 = SignalKindV1.FOREGROUND_CHANGED,
    source_id: str = "native.window.events",
    occurred_at: float = 100.0,
    metadata=None,
    coalesce_key: str | None = None,
):
    return AwarenessSignalV1.create(
        kind=kind,
        source_id=source_id,
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        metadata=metadata or {"application_id": "app.editor"},
        coalesce_key=coalesce_key,
        occurred_at=occurred_at,
    )


def test_idle_awareness_has_no_worker_timer_or_polling():
    awareness = EventDrivenAwarenessV1(_policy())
    assert awareness.background_workers == 0
    assert awareness.polling_interval is None
    assert awareness.queued == 0
    assert awareness.drain(now=100.0) == 0
    assert awareness.queued == 0


def test_raw_clipboard_screen_and_message_content_are_rejected():
    with pytest.raises(AwarenessDenied, match="captured content"):
        _signal(metadata={"clipboard_text": "private value"})
    with pytest.raises(AwarenessDenied, match="captured content"):
        _signal(metadata={"screenshot_image": "base64"})
    with pytest.raises(AwarenessDenied, match="captured content"):
        _signal(metadata={"message_body": "email body"})


def test_allowlist_replay_window_and_rate_budget_fail_closed():
    awareness = EventDrivenAwarenessV1(_policy(max_events_per_minute=1))
    with pytest.raises(AwarenessDenied, match="allowlisted"):
        awareness.publish(
            _signal(source_id="unknown.observer", occurred_at=100.0), now=100.0
        )
    with pytest.raises(AwarenessDenied, match="replay window"):
        awareness.publish(_signal(occurred_at=10.0), now=100.0)
    assert awareness.publish(_signal(occurred_at=100.0), now=100.0)
    with pytest.raises(AwarenessDenied, match="rate budget"):
        awareness.publish(_signal(occurred_at=101.0), now=101.0)


def test_coalescing_keeps_latest_native_state_without_queue_growth():
    awareness = EventDrivenAwarenessV1(_policy())
    assert awareness.publish(
        _signal(
            occurred_at=100.0,
            metadata={"application_id": "app.editor"},
            coalesce_key="foreground-current",
        ),
        now=100.0,
    )
    assert not awareness.publish(
        _signal(
            occurred_at=101.0,
            metadata={"application_id": "app.browser"},
            coalesce_key="foreground-current",
        ),
        now=101.0,
    )
    assert awareness.queued == 1
    assert awareness.drain(now=101.0) == 1
    projection = awareness.projection(
        owner_profile_id="owner_primary", workspace_id="workspace_personal", now=101.0
    )
    assert projection.active_application_id == "app.browser"


def test_queue_full_is_explicit_and_never_silently_drops():
    awareness = EventDrivenAwarenessV1(_policy(max_queue=1))
    assert awareness.publish(_signal(occurred_at=100.0), now=100.0)
    with pytest.raises(AwarenessQueueFull):
        awareness.publish(
            _signal(
                kind=SignalKindV1.WORKSPACE_CHANGED,
                source_id="native.workspace.events",
                occurred_at=101.0,
                metadata={"project_id": "project.onyx"},
            ),
            now=101.0,
        )
    assert awareness.queued == 1


def test_context_projection_and_goal_attention_are_read_only(tmp_path: Path):
    goals = OperationalGoalStoreV1(
        tmp_path / "goals.sqlite3", OperationalGoalFeatureGateV1(True)
    )
    goal = goals.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        level=GoalLevelV1.OBJECTIVE,
        title="Attend to overdue operational work",
        objective="Surface overdue work without mutating execution truth",
        definition_of_done=("runtime_status_observed",),
        target_at=50.0,
    )
    goals.activate(goal.goal_id)
    awareness = EventDrivenAwarenessV1(_policy(), goal_store=goals)
    for index, app in enumerate(("app.editor", "app.browser", "app.terminal", "app.editor")):
        assert awareness.publish(
            _signal(
                occurred_at=100.0 + index,
                metadata={"application_id": app},
            ),
            now=100.0 + index,
        )
    assert awareness.drain(maximum=8, now=104.0) == 4
    before = goals.get(goal.goal_id)
    projection = awareness.projection(
        owner_profile_id="owner_primary", workspace_id="workspace_personal", now=104.0
    )
    after = goals.get(goal.goal_id)
    assert projection.active_application_id == "app.editor"
    assert projection.context_switches == 3
    assert "high_context_switching" in projection.attention
    assert "overdue_goals" in projection.attention
    assert before == after


def test_admitted_signals_feed_durable_context_graph_without_polling(tmp_path: Path):
    graph = ContextGraphStoreV1(
        tmp_path / "context.sqlite3", ContextGraphFeatureGateV1(True)
    )
    awareness = EventDrivenAwarenessV1(_policy(), context_graph=graph)
    assert awareness.publish(
        _signal(
            kind=SignalKindV1.WORKSPACE_CHANGED,
            source_id="native.workspace.events",
            occurred_at=100.0,
            metadata={"project_id": "project.onyx"},
        ),
        now=100.0,
    )
    assert awareness.publish(
        _signal(
            occurred_at=101.0,
            metadata={"application_id": "app.editor"},
        ),
        now=101.0,
    )
    assert awareness.drain(now=101.0) == 2
    projection = graph.projection("owner_primary", "workspace_personal")
    assert projection.active_application_id == "app.editor"
    assert projection.active_project_id == "project.onyx"
    assert projection.edges == (
        ("app.editor", "active_in", "project.onyx", 1),
    )
