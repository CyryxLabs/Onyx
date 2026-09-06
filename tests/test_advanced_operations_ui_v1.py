from __future__ import annotations

from types import SimpleNamespace

import ui


class _Projection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def set_content(self, title: str, text: str) -> None:
        self.calls.append((title, text))


def test_operations_render_is_allowlisted_and_bounded() -> None:
    rendered = ui._advanced_operations_visible_render(
        {
            "status": "ready",
            "capabilities": ("operational_goals", "governed_automation"),
            "automation_queued": 2,
            "awareness_queued": 1,
            "automation_rules": 3,
            "enrolled_devices": 2,
            "site_projects": 1,
            "active_preferences": 4,
            "workflow_graphs": 2,
            "context_nodes": 7,
            "context_edges": 3,
            "workflow_summaries": (
                {
                    "name": "Review workspace changes",
                    "status": "active",
                    "node_kinds": ("trigger", "condition", "plan", "output"),
                },
            ),
            "owner_profile_id": "must-not-render",
            "workspace_id": "must-not-render-either",
        },
        {
            "attention": ("Review the release evidence",),
            "rhythm": {
                "status": "ready",
                "cadence": "morning_plan",
                "focus": (
                    {
                        "title": "Prepare the morning plan",
                        "health": "on_track",
                        "goal_id": "rhythm-id-must-not-render",
                    },
                ),
                "actions": (
                    {
                        "title": "Verify the next result",
                        "level": "daily_action",
                        "goal_id": "action-id-must-not-render",
                    },
                ),
                "warnings": ("DUE WITHIN 24H / Verify the next result",),
            },
            "goals": (
                {
                    "title": "Ship Onyx",
                    "level": "objective",
                    "health": "attention",
                    "score": 0.75,
                    "goal_id": "must-not-render",
                },
            ),
        },
        limit=2000,
    )
    assert "OPERATIONS  /  READY" in rendered
    assert "Ship Onyx" in rendered
    assert "TODAY  /  MORNING PLAN" in rendered
    assert "Prepare the morning plan" in rendered
    assert "Verify the next result" in rendered
    assert "AUTOMATION RULES  /  3" in rendered
    assert "ENROLLED DEVICES  /  2" in rendered
    assert "SITE PROJECTS  /  1" in rendered
    assert "ACTIVE PREFERENCES  /  4" in rendered
    assert "WORKFLOWS  /  2" in rendered
    assert "CONTEXT NODES  /  7" in rendered
    assert "CONTEXT LINKS  /  3" in rendered
    assert "FLOW  /  ACTIVE  /  Review workspace changes" in rendered
    assert "TRIGGER  >  CONDITION  >  PLAN  >  OUTPUT" in rendered
    assert "must-not-render" not in rendered
    assert "rhythm-id-must-not-render" not in rendered
    assert "action-id-must-not-render" not in rendered
    assert len(rendered) <= 2000


def test_operations_hud_action_calls_only_read_projections() -> None:
    projection = _Projection()
    owner = SimpleNamespace(
        _v5_projection=projection,
        on_advanced_status=lambda: {
            "status": "ready",
            "capabilities": ("operational_goals",),
            "automation_queued": 0,
            "awareness_queued": 0,
        },
        on_advanced_attention=lambda: {"attention": (), "goals": ()},
    )
    assert ui.MainWindow._request_v5_advanced_operations(owner) is True
    assert projection.calls[-1][0] == "ADVANCED OPERATIONS"
    assert "OPERATIONS  /  READY" in projection.calls[-1][1]


def test_operations_hud_action_fails_closed_when_callbacks_are_missing() -> None:
    projection = _Projection()
    owner = SimpleNamespace(
        _v5_projection=projection,
        on_advanced_status=None,
        on_advanced_attention=None,
    )
    assert ui.MainWindow._request_v5_advanced_operations(owner) is False
    assert "unavailable" in projection.calls[-1][1]


def test_operations_bridge_and_arc_free_pill_are_publicly_reachable() -> None:
    assert {"on_advanced_status", "on_advanced_attention"} <= set(dir(ui.OnyxUI))
    source = (ui.resource_root() / "qml" / "OnyxLiveShellV9.qml").read_text(
        encoding="utf-8"
    )
    assert 'objectName: "onyxAdvancedOperationsPillV9"' in source
    assert "requestAdvancedOperations()" in source
    assert "radius: height / 2" in source
    assert "c.arc(" not in source and "c.ellipse(" not in source
