"""Metadata-only operational events for the existing Onyx agentic core.

The bridge owns no connector, timer, worker, provider or executor. Trusted host
callbacks explicitly publish already-normalized state transitions into the
existing governed-automation and awareness queues. Provider content is never
copied into event metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from core.event_awareness_v1 import (
    AwarenessSignalV1,
    EventDrivenAwarenessV1,
    SignalKindV1,
)
from core.governed_automation_v1 import (
    AutomationEventV1,
    EventDrivenAutomationRuntimeV1,
)


_HEX64 = re.compile(r"[0-9a-f]{64}")
_MISSION_STATE = frozenset(
    {"draft", "approved", "running", "waiting", "paused", "succeeded", "failed", "cancelled"}
)
_CONNECTIVITY = frozenset(
    {"connected", "disconnected", "degraded", "authentication_required", "configuration_required"}
)


class OperationalEventBridgeError(RuntimeError):
    pass


class OperationalEventBridgeContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OperationalEventReceiptV1:
    contract: str
    source: str
    status: str
    published: int
    event_digest: str
    content_captured: bool = False
    background_workers: int = 0
    polling_interval: None = None


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_count(value: object, label: str) -> int:
    if type(value) is not list or len(value) > 10_000:
        raise OperationalEventBridgeContractError(f"{label} is invalid")
    return len(value)


class OperationalEventBridgeV1:
    """Publish explicit host events into the existing two local queues."""

    def __init__(
        self,
        *,
        owner_profile_id: str,
        workspace_id: str,
        automation: EventDrivenAutomationRuntimeV1,
        awareness: EventDrivenAwarenessV1,
    ) -> None:
        if (
            type(owner_profile_id) is not str
            or type(workspace_id) is not str
            or type(automation) is not EventDrivenAutomationRuntimeV1
            or type(awareness) is not EventDrivenAwarenessV1
        ):
            raise OperationalEventBridgeContractError("exact live event authorities are required")
        self.owner_profile_id = owner_profile_id
        self.workspace_id = workspace_id
        self.automation = automation
        self.awareness = awareness
        self.background_workers = 0
        self.polling_interval = None

    def _publish(
        self,
        *,
        source: str,
        event_type: str,
        kind: SignalKindV1,
        metadata: dict[str, object],
        coalesce_key: str,
    ) -> None:
        event = AutomationEventV1.create(
            event_type=event_type,
            source_id=source,
            owner_profile_id=self.owner_profile_id,
            workspace_id=self.workspace_id,
            metadata=metadata,
            coalesce_key=coalesce_key,
        )
        signal = AwarenessSignalV1.create(
            kind=kind,
            source_id=source,
            owner_profile_id=self.owner_profile_id,
            workspace_id=self.workspace_id,
            metadata=metadata,
            coalesce_key=coalesce_key,
            occurred_at=event.occurred_at,
        )
        self.automation.publish(event)
        self.awareness.publish(signal, now=event.occurred_at)

    def publish_dayops_brief(
        self, payload: Mapping[str, object]
    ) -> OperationalEventReceiptV1:
        if type(payload) is not dict:
            raise OperationalEventBridgeContractError("exact DayOps mapping is required")
        status = payload.get("status")
        if type(status) is not str or not status or len(status) > 64:
            raise OperationalEventBridgeContractError("DayOps status is invalid")
        if status != "completed":
            return OperationalEventReceiptV1(
                "OnyxOperationalEventReceipt.v1",
                "microsoft_dayops",
                "not_published",
                0,
                _digest({"status": status}),
            )
        events = _bounded_count(payload.get("events"), "calendar events")
        messages = _bounded_count(payload.get("unread_messages"), "unread messages")
        calendar_more = payload.get("calendar_has_more")
        mail_more = payload.get("mail_has_more")
        brief_ref = payload.get("brief_sha256")
        if (
            type(calendar_more) is not bool
            or type(mail_more) is not bool
            or type(brief_ref) is not str
            or _HEX64.fullmatch(brief_ref) is None
        ):
            raise OperationalEventBridgeContractError("DayOps brief proof is invalid")
        calendar_metadata = {
            "brief_ref": brief_ref,
            "event_count": events,
            "has_more": calendar_more,
            "read_only": True,
        }
        mail_metadata = {
            "brief_ref": brief_ref,
            "has_more": mail_more,
            "read_only": True,
            "unread_count": messages,
        }
        self._publish(
            source="native_calendar_events",
            event_type="calendar.brief.updated",
            kind=SignalKindV1.CALENDAR_ATTENTION,
            metadata=calendar_metadata,
            coalesce_key="calendar_dayops_brief",
        )
        self._publish(
            source="native_mail_events",
            event_type="mail.unread.updated",
            kind=SignalKindV1.MAIL_ATTENTION,
            metadata=mail_metadata,
            coalesce_key="mail_dayops_brief",
        )
        return OperationalEventReceiptV1(
            "OnyxOperationalEventReceipt.v1",
            "microsoft_dayops",
            "published",
            2,
            _digest({"calendar": calendar_metadata, "mail": mail_metadata}),
        )

    def publish_connectivity(
        self, *, provider: str, state: str
    ) -> OperationalEventReceiptV1:
        if provider != "microsoft_graph" or state not in _CONNECTIVITY:
            raise OperationalEventBridgeContractError("connectivity state is invalid")
        metadata = {"provider": provider, "state": state}
        self._publish(
            source="native_connectivity_events",
            event_type="connectivity.microsoft_graph.changed",
            kind=SignalKindV1.CONNECTIVITY_CHANGED,
            metadata=metadata,
            coalesce_key="microsoft_graph_connectivity",
        )
        return OperationalEventReceiptV1(
            "OnyxOperationalEventReceipt.v1",
            provider,
            "published",
            1,
            _digest(metadata),
        )

    def publish_mission_state(
        self, *, mission_id: str, state: str, revision: int
    ) -> OperationalEventReceiptV1:
        if (
            type(mission_id) is not str
            or not mission_id
            or len(mission_id) > 192
            or state not in _MISSION_STATE
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
        ):
            raise OperationalEventBridgeContractError("mission state is invalid")
        mission_ref = hashlib.sha256(mission_id.encode("utf-8")).hexdigest()
        metadata = {"mission_ref": mission_ref, "revision": revision, "state": state}
        self._publish(
            source="native_mission_events",
            event_type="mission.state.changed",
            kind=SignalKindV1.MISSION_STATE,
            metadata=metadata,
            coalesce_key="mission_" + mission_ref[:24],
        )
        return OperationalEventReceiptV1(
            "OnyxOperationalEventReceipt.v1",
            "mission_store",
            "published",
            1,
            _digest(metadata),
        )


__all__ = [
    "OperationalEventBridgeContractError",
    "OperationalEventBridgeError",
    "OperationalEventBridgeV1",
    "OperationalEventReceiptV1",
]
