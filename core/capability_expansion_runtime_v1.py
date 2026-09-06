"""Canonical authority bridge for optional capability-expansion modules.

IDS decision: CREATE. Existing modules expose capability behavior but no shared
permission/audit/kill boundary. This bridge adapts the canonical permission
broker and content-free tool audit without owning a parallel authority plane.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from core import permission_broker
from core.tool_audit import AuditReference, append_tool_audit_reference

CAPABILITIES: Final = frozenset(
    {"plugin", "clipboard", "wellness", "personalization", "social"}
)
OPERATIONS: Final = {
    "plugin": frozenset(
        {"status", "list", "inspect", "enable", "disable", "remove", "execute"}
    ),
    "clipboard": frozenset({"status", "opt_in", "pause", "resume", "revoke", "preview"}),
    "wellness": frozenset(
        {
            "create",
            "correct",
            "remove",
            "status",
            "repetition_status",
            "repetition_start",
            "repetition_observe",
            "repetition_stop",
        }
    ),
    "personalization": frozenset(
        {
            "create",
            "confirm",
            "update",
            "remove",
            "status",
            "onboarding_status",
            "onboarding_answer",
        }
    ),
    "social": frozenset(
        {
            "generate",
            "preview",
            "video_inspect",
            "consent",
            "dispatch",
            "reconcile",
            "status",
        }
    ),
}


class CapabilityExpansionDenied(PermissionError):
    """The canonical authority boundary denied dispatch."""


class CapabilityExpansionAuditError(RuntimeError):
    """The canonical audit could not record a dispatch receipt."""


@dataclass(frozen=True, slots=True)
class CapabilityAuditReceiptV1:
    capability: str
    operation: str
    operation_digest: str
    decision: str
    outcome: str
    trace_id: str
    audit_event_hash: str


class CapabilityExpansionRuntimeV1:
    """Broker, latch, dispatch, and audit fence for expansion capabilities."""

    def __init__(
        self,
        *,
        enabled: Mapping[str, bool] | None = None,
        available: Mapping[str, bool] | None = None,
    ) -> None:
        self._enabled = self._flags(enabled)
        self._available = self._flags(available)
        self._revoked: set[str] = set()
        self._killed = False
        self._generation = 0
        self._lock = threading.RLock()
        # Serialize callbacks separately: a blocking tool must never own the
        # authority lock needed by kill/revoke/status.
        self._dispatch_lock = threading.RLock()

    @staticmethod
    def _flags(values: Mapping[str, bool] | None) -> dict[str, bool]:
        source = dict(values or {})
        if set(source) - CAPABILITIES or any(type(value) is not bool for value in source.values()):
            raise ValueError("capability flags are invalid")
        return {name: source.get(name, False) for name in CAPABILITIES}

    @staticmethod
    def _operation(capability: str, operation: str) -> tuple[str, str]:
        if capability not in CAPABILITIES or operation not in OPERATIONS.get(capability, ()):
            raise CapabilityExpansionDenied("unknown capability operation")
        return capability, operation

    def kill(self) -> None:
        with self._lock:
            self._killed = True
            self._generation += 1

    def revoke(self, capability: str) -> None:
        if capability not in CAPABILITIES:
            raise CapabilityExpansionDenied("unknown capability")
        with self._lock:
            self._revoked.add(capability)
            self._generation += 1

    def status(self, capability: str | None = None) -> dict[str, object]:
        names = sorted(CAPABILITIES if capability is None else {capability})
        if any(name not in CAPABILITIES for name in names):
            raise CapabilityExpansionDenied("unknown capability")
        with self._lock:
            result = {}
            for name in names:
                enabled = self._enabled[name] and not self._killed
                available = self._available[name]
                revoked = name in self._revoked
                state = "disabled"
                if enabled and not available:
                    state = "unavailable"
                elif enabled and available and not revoked:
                    state = "approved"
                result[name] = {
                    "status": state,
                    "enabled": enabled,
                    "available": available,
                    "revoked": revoked,
                    "kill_latched": self._killed,
                    "audit_healthy": permission_broker.audit_healthy(),
                    "authority": "core.permission_broker",
                }
            return result

    def assert_dispatchable(self, capability: str, operation: str) -> None:
        """Expose a side-effect-free preflight through the same authority latch."""
        capability, operation = self._operation(capability, operation)
        del operation
        with self._lock:
            self._assert_dispatchable(capability)

    def dispatch(
        self,
        capability: str,
        operation: str,
        dispatch: Callable[[], object],
        *,
        binding: Mapping[str, object] | None = None,
        trace_id: str = "",
    ) -> tuple[object, CapabilityAuditReceiptV1]:
        capability, operation = self._operation(capability, operation)
        if not callable(dispatch):
            raise CapabilityExpansionDenied("dispatch callback is invalid")
        metadata = dict(binding or {})
        canonical = json.dumps(
            {"capability": capability, "operation": operation, "binding": metadata},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        operation_digest = hashlib.sha256(canonical.encode("ascii")).hexdigest()
        with self._lock:
            self._assert_dispatchable(capability)
            generation = self._generation
        allowed, proof = permission_broker.authorize_capability_operation(
            capability,
            operation,
            {"operation_digest": operation_digest},
        )
        if not allowed:
            raise CapabilityExpansionDenied(proof)
        with self._dispatch_lock:
            with self._lock:
                self._assert_dispatchable(capability)
                if generation != self._generation:
                    raise CapabilityExpansionDenied("authority changed before dispatch")
            result = dispatch()
        try:
            reference: AuditReference = append_tool_audit_reference(
                profile=permission_broker.get_trust_profile(),
                tool=f"capability_{capability}",
                action=operation,
                decision="allow",
                reason="exact broker authorization",
                arguments={"operation_digest": operation_digest},
                outcome="dispatched",
                trace_id=trace_id,
            )
        except Exception as exc:
            permission_broker.mark_audit_unhealthy()
            raise CapabilityExpansionAuditError("capability audit append failed") from exc
        return result, CapabilityAuditReceiptV1(
            capability=capability,
            operation=operation,
            operation_digest=operation_digest,
            decision="allow",
            outcome="dispatched",
            trace_id=reference.trace_id,
            audit_event_hash=reference.event_hash,
        )

    def _assert_dispatchable(self, capability: str) -> None:
        if not permission_broker.audit_healthy():
            raise CapabilityExpansionDenied("consequential audit is unhealthy")
        if self._killed:
            raise CapabilityExpansionDenied("global kill is latched")
        if capability in self._revoked:
            raise CapabilityExpansionDenied("capability is revoked")
        if not self._enabled[capability]:
            raise CapabilityExpansionDenied("capability is disabled")
        if not self._available[capability]:
            raise CapabilityExpansionDenied("capability is unavailable")


__all__ = [
    "CAPABILITIES",
    "OPERATIONS",
    "CapabilityAuditReceiptV1",
    "CapabilityExpansionAuditError",
    "CapabilityExpansionDenied",
    "CapabilityExpansionRuntimeV1",
]
