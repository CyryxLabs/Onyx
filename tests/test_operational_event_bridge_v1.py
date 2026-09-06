from __future__ import annotations

import hashlib

import pytest

from core.event_awareness_v1 import AwarenessPolicyV1, EventDrivenAwarenessV1
from core.governed_automation_v1 import EventDrivenAutomationRuntimeV1
from core.operational_event_bridge_v1 import (
    OperationalEventBridgeContractError,
    OperationalEventBridgeV1,
)


class _Automation:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event):
        self.events.append(event)
        return ()


def _bridge():
    captured = _Automation()
    automation = object.__new__(EventDrivenAutomationRuntimeV1)
    automation.publish = captured.publish
    awareness = EventDrivenAwarenessV1(
        AwarenessPolicyV1(
            allowed_sources=(
                "native_calendar_events",
                "native_mail_events",
                "native_connectivity_events",
                "native_mission_events",
            )
        )
    )
    return (
        OperationalEventBridgeV1(
            owner_profile_id="owner_test",
            workspace_id="workspace_test",
            automation=automation,
            awareness=awareness,
        ),
        captured,
        awareness,
    )


def test_dayops_publishes_counts_and_proof_without_provider_content() -> None:
    bridge, captured, awareness = _bridge()
    proof = hashlib.sha256(b"normalized brief").hexdigest()
    receipt = bridge.publish_dayops_brief(
        {
            "status": "completed",
            "brief_sha256": proof,
            "calendar_has_more": False,
            "mail_has_more": True,
            "events": [{"subject": "Secret board meeting"}],
            "unread_messages": [{"subject": "Confidential acquisition"}],
        }
    )

    assert receipt.status == "published"
    assert receipt.published == 2
    assert receipt.content_captured is False
    assert bridge.background_workers == 0
    assert bridge.polling_interval is None
    assert len(captured.events) == 2
    rendered = repr(captured.events)
    assert "Secret board meeting" not in rendered
    assert "Confidential acquisition" not in rendered
    assert proof in rendered
    assert awareness.queued == 2


def test_noncompleted_dayops_result_is_not_fabricated_as_live_event() -> None:
    bridge, captured, awareness = _bridge()
    receipt = bridge.publish_dayops_brief(
        {"status": "authentication_required", "result": "sign in"}
    )
    assert receipt.status == "not_published"
    assert receipt.published == 0
    assert captured.events == []
    assert awareness.queued == 0


def test_connectivity_and_mission_events_are_metadata_only() -> None:
    bridge, captured, awareness = _bridge()
    connectivity = bridge.publish_connectivity(
        provider="microsoft_graph", state="connected"
    )
    mission = bridge.publish_mission_state(
        mission_id="mission_sensitive_customer_name", state="running", revision=3
    )
    assert connectivity.published == mission.published == 1
    assert len(captured.events) == 2
    assert awareness.queued == 2
    assert "mission_sensitive_customer_name" not in repr(captured.events)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "completed", "events": [], "unread_messages": []},
        {
            "status": "completed",
            "events": "not-a-list",
            "unread_messages": [],
            "calendar_has_more": False,
            "mail_has_more": False,
            "brief_sha256": "0" * 64,
        },
    ],
)
def test_dayops_contract_rejects_unproved_or_unbounded_shapes(payload) -> None:
    bridge, _, _ = _bridge()
    with pytest.raises(OperationalEventBridgeContractError):
        bridge.publish_dayops_brief(payload)
