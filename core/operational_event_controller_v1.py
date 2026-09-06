"""Lazy host binding for the metadata-only operational event bridge."""

from __future__ import annotations

import threading
from typing import Mapping

from core.advanced_operations_controller_v1 import (
    HOST_CONTROLLER as ADVANCED_CONTROLLER,
    AdvancedOperationsControllerV1,
)
from core.advanced_operations_live_v1 import AdvancedOperationsSessionV1
from core.operational_event_bridge_v1 import (
    OperationalEventBridgeContractError,
    OperationalEventBridgeV1,
    OperationalEventReceiptV1,
)


HOST_CONTROLLER = "_operational_event_controller_v1"


class OperationalEventControllerDenied(PermissionError):
    pass


class OperationalEventControllerV1:
    def __init__(self, host: object) -> None:
        if host is None:
            raise OperationalEventControllerDenied("host is required")
        self._host = host
        self._operations: AdvancedOperationsSessionV1 | None = None
        self._bridge: OperationalEventBridgeV1 | None = None
        self._closed = False
        self._lock = threading.RLock()
        self.background_workers = 0
        self.polling_interval = None

    def _bind(self) -> OperationalEventBridgeV1:
        if self._closed:
            raise OperationalEventControllerDenied("operational event controller is closed")
        controller = getattr(self._host, ADVANCED_CONTROLLER, None)
        if type(controller) is not AdvancedOperationsControllerV1:
            raise OperationalEventControllerDenied("advanced operations authority is unavailable")
        operations = controller._bind_current()
        if type(operations) is not AdvancedOperationsSessionV1 or operations.closed:
            raise OperationalEventControllerDenied("live operational session is unavailable")
        if operations is not self._operations:
            self._operations = operations
            self._bridge = OperationalEventBridgeV1(
                owner_profile_id=operations.identity.owner_profile_id,
                workspace_id=operations.identity.workspace_id,
                automation=operations.automation,
                awareness=operations.awareness,
            )
        if type(self._bridge) is not OperationalEventBridgeV1:
            raise OperationalEventControllerDenied("event bridge failed to bind")
        return self._bridge

    @staticmethod
    def _public(receipt: OperationalEventReceiptV1) -> dict[str, object]:
        return {
            "contract": receipt.contract,
            "source": receipt.source,
            "status": receipt.status,
            "published": receipt.published,
            "event_digest": receipt.event_digest,
            "content_captured": receipt.content_captured,
            "background_workers": receipt.background_workers,
            "polling_interval": receipt.polling_interval,
        }

    def publish_dayops_brief(self, payload: Mapping[str, object]) -> dict[str, object]:
        with self._lock:
            return self._public(self._bind().publish_dayops_brief(payload))

    def publish_connectivity_result(
        self, operation: str, payload: Mapping[str, object]
    ) -> dict[str, object]:
        if operation not in {"connect", "sign_in", "disconnect"} or type(payload) is not dict:
            raise OperationalEventBridgeContractError("connectivity result is invalid")
        raw = payload.get("status")
        if type(raw) is not str:
            raise OperationalEventBridgeContractError("connectivity status is invalid")
        state = {
            "connected": "connected",
            "disconnected": "disconnected",
            "authentication_required": "authentication_required",
            "configuration_required": "configuration_required",
        }.get(raw, "degraded")
        with self._lock:
            return self._public(
                self._bind().publish_connectivity(provider="microsoft_graph", state=state)
            )

    def publish_mission_state(
        self, *, mission_id: str, state: str, revision: int
    ) -> dict[str, object]:
        with self._lock:
            return self._public(
                self._bind().publish_mission_state(
                    mission_id=mission_id, state=state, revision=revision
                )
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._bridge = None
            self._operations = None


__all__ = [
    "HOST_CONTROLLER",
    "OperationalEventControllerDenied",
    "OperationalEventControllerV1",
]
