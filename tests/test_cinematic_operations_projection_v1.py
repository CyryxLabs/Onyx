from __future__ import annotations

from typing import Any

import pytest

from core.cinematic_operations_projection_v1 import (
    CinematicOperationsProjectionError,
    CinematicOperationsProjectionV1,
    CinematicOperationsSnapshotV1,
)


def snapshot() -> dict[str, Any]:
    return {
        "status_label": "OPERATIONS READY",
        "goals": [
            {
                "goal_id": "goal.alpha",
                "title": "Prepare the release",
                "detail": "Reconcile the final evidence.",
                "status": "active",
                "priority": "high",
                "due_label": "TODAY",
                "progress": 0.72,
            }
        ],
        "workflow_nodes": [
            {
                "node_id": "node.trigger",
                "workflow_id": "workflow.alpha",
                "label": "Owner request",
                "kind": "trigger",
                "status": "complete",
            },
            {
                "node_id": "node.plan",
                "workflow_id": "workflow.alpha",
                "label": "Governed plan",
                "kind": "plan",
                "status": "active",
            },
        ],
        "workflow_edges": [
            {
                "edge_id": "edge.one",
                "workflow_id": "workflow.alpha",
                "source": "node.trigger",
                "target": "node.plan",
                "route": "next",
            }
        ],
        "devices": [
            {
                "device_id": "device.desktop",
                "name": "Primary workstation",
                "platform": "Windows",
                "status": "online",
                "trust": "bound",
                "last_seen": "NOW",
            }
        ],
        "sites": [
            {
                "site_id": "site.cyryx",
                "name": "Cyryx Labs",
                "branch": "feature/operations",
                "status": "active",
                "preview_state": "ready",
                "updated_label": "2 MIN AGO",
            }
        ],
        "site_files": [
            {
                "file_id": "file.index",
                "site_id": "site.cyryx",
                "name": "index.html",
                "kind": "file",
                "state": "modified",
                "depth": 1,
            }
        ],
        "agents": [
            {
                "agent_id": "agent.release",
                "name": "Release operator",
                "role": "Quality and release",
                "status": "running",
                "task": "Reviewing evidence",
                "load_label": "1 ACTIVE",
            }
        ],
        "inbox": [
            {
                "inbox_id": "inbox.review",
                "title": "Review the package receipt",
                "source": "MISSION LEDGER",
                "status": "pending",
                "age_label": "4 MIN",
            }
        ],
        "events": [
            {
                "event_id": "event.release",
                "title": "Release evidence received",
                "detail": "Receipt awaits independent review.",
                "category": "system",
                "status": "review",
                "time_label": "09:42",
            }
        ],
    }


def test_projection_is_default_off_and_snapshot_is_typed_and_bounded() -> None:
    projection = CinematicOperationsProjectionV1()
    assert projection.enabled is False
    assert projection.activePage == "goals"
    assert projection.requestNavigation("workflow") is False

    projection.set_snapshot(snapshot())
    assert projection.statusLabel == "OPERATIONS READY"
    assert projection.goals[0] == {
        "goal_id": "goal.alpha",
        "title": "Prepare the release",
        "detail": "Reconcile the final evidence.",
        "status": "active",
        "priority": "high",
        "due_label": "TODAY",
        "progress": 0.72,
    }
    assert projection.metrics == {
        "active_goals": 1,
        "workflows": 1,
        "online_devices": 1,
        "active_agents": 1,
        "events_today": 1,
    }
    assert projection.siteFiles == [
        {
            "file_id": "file.index",
            "site_id": "site.cyryx",
            "name": "index.html",
            "kind": "file",
            "state": "modified",
            "depth": 1,
        }
    ]
    assert {item["kind"] for item in projection.safeNodeCatalog} == {
        "trigger",
        "condition",
        "transform",
        "plan",
        "output",
    }


def test_snapshot_rejects_unknown_sensitive_and_unbounded_data() -> None:
    unknown = snapshot()
    unknown["api_key"] = "must not cross projection"
    with pytest.raises(CinematicOperationsProjectionError, match="shape"):
        CinematicOperationsSnapshotV1.parse(unknown)

    sensitive = snapshot()
    sensitive["devices"][0]["token"] = "must not cross projection"
    with pytest.raises(CinematicOperationsProjectionError, match="shape"):
        CinematicOperationsSnapshotV1.parse(sensitive)

    excessive = snapshot()
    excessive["goals"] = excessive["goals"] * 25
    with pytest.raises(CinematicOperationsProjectionError, match="collection"):
        CinematicOperationsSnapshotV1.parse(excessive)

    path_leak = snapshot()
    path_leak["site_files"][0]["name"] = "C:\\private\\index.html"
    with pytest.raises(CinematicOperationsProjectionError, match="file name"):
        CinematicOperationsSnapshotV1.parse(path_leak)


def test_projection_emits_only_validated_ui_intent() -> None:
    calls: list[tuple[object, ...]] = []
    projection = CinematicOperationsProjectionV1(
        enabled=True,
        callbacks={
            "navigate": lambda page: calls.append(("navigate", page)),
            "selection": lambda surface, item_id: calls.append(
                ("selection", surface, item_id)
            ),
            "proposal": lambda kind, payload: calls.append(("proposal", kind, payload)),
        },
    )

    assert projection.requestNavigation("workflow") is True
    assert projection.activePage == "workflow"
    assert projection.requestSelection("workflow", "node.plan") is True
    assert projection.requestProposal(
        "workflow_node_add",
        {
            "workflow_id": "workflow.alpha",
            "kind": "condition",
            "label": "Owner condition",
        },
    )
    assert calls[-1] == (
        "proposal",
        "workflow_node_add",
        {
            "workflow_id": "workflow.alpha",
            "kind": "condition",
            "label": "Owner condition",
        },
    )

    count = len(calls)
    for forbidden in ("shell", "http", "code", "provider"):
        assert (
            projection.requestProposal(
                "workflow_node_add",
                {
                    "workflow_id": "workflow.alpha",
                    "kind": forbidden,
                    "label": "Unsafe node",
                },
            )
            is False
        )
    assert (
        projection.requestProposal(
            "workflow_connect",
            {
                "workflow_id": "workflow.alpha",
                "source": "node.plan",
                "target": "node.plan",
                "route": "next",
            },
        )
        is False
    )
    assert projection.requestProposal("execute_shell", {}) is False
    assert len(calls) == count


def test_callback_failure_is_contained_without_leaking_details() -> None:
    def fail(_page: str) -> None:
        raise RuntimeError("private detail")

    projection = CinematicOperationsProjectionV1(
        enabled=True, callbacks={"navigate": fail}
    )
    assert projection.requestNavigation("devices") is True
    assert projection.lastCallbackError == "navigate: RuntimeError"
    assert "private detail" not in projection.lastCallbackError


def test_reduced_motion_is_host_controlled_and_has_no_scheduler() -> None:
    projection = CinematicOperationsProjectionV1(enabled=True)
    assert projection.reducedMotion is False
    projection.set_reduced_motion(True)
    assert projection.reducedMotion is True
    assert not any(name.lower().endswith("timer") for name in vars(projection))
