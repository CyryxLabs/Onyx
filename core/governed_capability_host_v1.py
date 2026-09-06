"""Closed, fail-closed capability dispatch host governed by GovernanceNucleusV1."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
from typing import Callable, Protocol

from core.governance_nucleus_v1 import (
    GovernanceNucleusV1,
    GovernanceV1ContractError,
    GovernanceV1Denied,
    SessionCapabilityV1,
)


def _digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GovernanceV1ContractError("capability arguments are not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ActionBinding:
    binding_id: str
    principal_id: str
    workspace_id: str
    session_id: str
    session_generation: int
    capability: str
    operation: str
    arguments_digest: str
    policy_binding_digest: str


@dataclass(frozen=True, slots=True)
class CapabilityReceipt:
    binding_id: str
    outcome: str
    result: Mapping[str, object] | None
    uncertainty: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class KillReceipt:
    status: str
    nucleus: Mapping[str, object]
    participants: tuple[tuple[str, str], ...]
    uncertainty: bool


class CapabilityPort(Protocol):
    def _bind_host_authorizer(
        self, authorizer: Callable[[object, str, Mapping[str, object]], str]
    ) -> None: ...

    def dispatch(
        self, operation: str, arguments: Mapping[str, object], authorization: object
    ) -> Mapping[str, object]: ...

    def revoke(self, binding_id: str) -> object: ...

    def kill(self) -> object: ...


@dataclass(slots=True)
class _Registration:
    port: CapabilityPort
    operations: frozenset[str]
    policy_digest: str


@dataclass(frozen=True, slots=True)
class _DispatchAuthorization:
    binding_id: str
    capability: str
    operation: str
    arguments_digest: str
    session_generation: int
    nonce: str


def _redacted_result(value: object) -> dict[str, object]:
    """Return the sole result shape allowed across the host boundary."""
    shape = _content_free_shape(value)
    return {
        "schema": "OnyxContentFreeResult.v1",
        "status": "observed",
        "result_digest": _digest(shape),
        "result_type": type(value).__name__[:48],
        "item_count": shape["count"],
        "redacted": True,
    }


def _content_free_shape(value: object) -> dict[str, object]:
    """Derive bounded structural metadata without serializing result content."""
    remaining = [128]
    active: set[int] = set()

    def visit(item: object, depth: int) -> dict[str, object]:
        item_type = type(item)
        metadata: dict[str, object] = {
            "type": item_type.__name__[:48],
            "count": 1,
        }
        if remaining[0] <= 0 or depth >= 8:
            metadata["bounded"] = True
            return metadata
        remaining[0] -= 1

        if isinstance(item, Enum):
            metadata["kind"] = "enum"
            return metadata
        if item_type in (bytes, bytearray, memoryview):
            metadata.update(kind="bytes", count=min(len(item), 10_000))
            return metadata
        if item_type in (str, int, float, bool, type(None)):
            metadata["kind"] = "scalar"
            return metadata

        identity = id(item)
        if identity in active:
            metadata.update(kind="cycle", bounded=True)
            return metadata

        children: list[dict[str, object]] = []
        active.add(identity)
        try:
            if isinstance(item, Mapping):
                metadata.update(kind="mapping", count=min(len(item), 10_000))
                for child in list(item.values())[:32]:
                    children.append(visit(child, depth + 1))
            elif item_type in (list, tuple, set, frozenset):
                metadata.update(kind="sequence", count=min(len(item), 10_000))
                for child in list(item)[:32]:
                    children.append(visit(child, depth + 1))
            elif is_dataclass(item) and not isinstance(item, type):
                declared = fields(item)
                metadata.update(kind="dataclass", count=min(len(declared), 10_000))
                for field in declared[:32]:
                    children.append(
                        visit(object.__getattribute__(item, field.name), depth + 1)
                    )
            else:
                try:
                    attributes = object.__getattribute__(item, "__dict__")
                except (AttributeError, TypeError):
                    attributes = None
                if type(attributes) is dict:
                    metadata.update(
                        kind="object", count=min(len(attributes), 10_000)
                    )
                    for child in list(attributes.values())[:32]:
                        children.append(visit(child, depth + 1))
                else:
                    metadata["kind"] = "opaque"
        finally:
            active.remove(identity)
        if children:
            metadata["children"] = children
        if int(metadata["count"]) > len(children) and metadata["kind"] not in {
            "bytes", "scalar", "enum", "opaque"
        }:
            metadata["truncated"] = True
        return metadata

    return visit(value, 0)


class HostBoundCapabilityPortV1:
    """Concrete-port fence: only a host-issued, one-use capability dispatches."""

    def __init__(self) -> None:
        self.__host_authorizer: Callable[
            [object, str, Mapping[str, object]], str
        ] | None = None

    def _bind_host_authorizer(
        self, authorizer: Callable[[object, str, Mapping[str, object]], str]
    ) -> None:
        if self.__host_authorizer is not None or not callable(authorizer):
            raise GovernanceV1ContractError("capability port host binding is invalid")
        self.__host_authorizer = authorizer

    def dispatch(
        self,
        operation: str,
        arguments: Mapping[str, object],
        authorization: object = None,
    ) -> Mapping[str, object]:
        authorizer = self.__host_authorizer
        if authorizer is None:
            raise GovernanceV1Denied("capability port is not host-bound")
        binding_id = authorizer(authorization, operation, arguments)
        return _redacted_result(self._dispatch_bound(operation, arguments, binding_id))

    def _dispatch_bound(self, operation, arguments, binding_id):
        """Default ports need no binding-specific execution cancellation."""
        return self._dispatch_authorized(operation, arguments)

    def _dispatch_authorized(
        self, operation: str, arguments: Mapping[str, object]
    ) -> object:
        raise NotImplementedError


class GovernedCapabilityHostV1:
    """Dispatch only exact bindings from a constructor-closed registry."""

    def __init__(
        self,
        *,
        nucleus: GovernanceNucleusV1,
        registry: Mapping[str, tuple[CapabilityPort, frozenset[str]]],
    ) -> None:
        if type(nucleus) is not GovernanceNucleusV1:
            raise GovernanceV1ContractError("exact GovernanceNucleusV1 is required")
        if not isinstance(registry, Mapping) or not registry or len(registry) > 32:
            raise GovernanceV1ContractError("closed capability registry is required")
        registrations: dict[str, _Registration] = {}
        for capability, item in registry.items():
            if (
                type(capability) is not str
                or not capability
                or type(item) is not tuple
                or len(item) != 2
                or type(item[1]) is not frozenset
                or not item[1]
                or any(type(op) is not str or not op for op in item[1])
            ):
                raise GovernanceV1ContractError("capability registration is invalid")
            port, operations = item
            if any(not callable(getattr(port, method, None)) for method in ("dispatch", "revoke", "kill")):
                raise GovernanceV1ContractError("capability port lifecycle is incomplete")
            policy = _digest({"capability": capability, "operations": sorted(operations)})
            registrations[capability] = _Registration(port, operations, policy)
        self._nucleus = nucleus
        self._registry = registrations
        self._lock = threading.RLock()
        self._killed = nucleus.killed
        self._revoked: set[str] = set()
        self._inflight: set[str] = set()
        self._kill_receipt: KillReceipt | None = None
        self._shutdown_receipt: KillReceipt | None = None
        self._authorizations: dict[int, _DispatchAuthorization] = {}
        self._bindings: dict[int, ActionBinding] = {}
        for capability, registration in self._registry.items():
            binder = getattr(registration.port, "_bind_host_authorizer", None)
            if not callable(binder):
                raise GovernanceV1ContractError("capability port is not host-bound")
            binder(
                lambda token, operation, arguments, capability=capability: (
                    self._consume_authorization(
                        token, capability, operation, arguments
                    )
                )
            )

    def _consume_authorization(
        self,
        token: object,
        capability: str,
        operation: str,
        arguments: Mapping[str, object],
    ) -> str:
        if type(token) is not _DispatchAuthorization:
            raise GovernanceV1Denied("host-bound dispatch authorization is required")
        with self._lock:
            issued = self._authorizations.pop(id(token), None)
        if issued is not token or (
            token.capability != capability
            or token.operation != operation
            or token.arguments_digest != _digest(dict(arguments))
        ):
            raise GovernanceV1Denied("dispatch authorization is stale or foreign")
        return token.binding_id

    def bind(
        self,
        session: SessionCapabilityV1,
        capability: str,
        operation: str,
        arguments: Mapping[str, object],
    ) -> ActionBinding:
        registration = self._registry.get(capability)
        if registration is None or operation not in registration.operations:
            raise GovernanceV1Denied("unknown capability or operation")
        if not isinstance(arguments, Mapping):
            raise GovernanceV1ContractError("capability arguments must be a mapping")
        arguments_digest = _digest(dict(arguments))
        binding = ActionBinding(
            "binding-" + secrets.token_hex(12),
            session.principal_id,
            session.workspace_id,
            session.session_id,
            session.generation,
            capability,
            operation,
            arguments_digest,
            registration.policy_digest,
        )
        with self._lock:
            if self._killed or self._nucleus.killed:
                raise GovernanceV1Denied("capability host kill is latched")
            self._bindings[id(binding)] = binding
        return binding

    def dispatch(self, binding: ActionBinding, arguments: Mapping[str, object]) -> CapabilityReceipt:
        if type(binding) is not ActionBinding:
            raise GovernanceV1ContractError("exact ActionBinding is required")
        with self._lock:
            issued_binding = self._bindings.pop(id(binding), None)
        if issued_binding is not binding:
            raise GovernanceV1Denied("host-issued one-use ActionBinding is required")
        registration = self._registry.get(binding.capability)
        if registration is None or binding.operation not in registration.operations:
            raise GovernanceV1Denied("unknown capability or operation")
        if _digest(dict(arguments)) != binding.arguments_digest or registration.policy_digest != binding.policy_binding_digest:
            raise GovernanceV1Denied("capability binding digest mismatch")
        with self._lock:
            if self._killed or self._nucleus.killed:
                raise GovernanceV1Denied("capability host kill is latched")
            if binding.binding_id in self._revoked:
                raise GovernanceV1Denied("capability binding is revoked")
            self._nucleus.authorize_capability_binding(**asdict(binding))
            self._inflight.add(binding.binding_id)
            authorization = _DispatchAuthorization(
                binding.binding_id,
                binding.capability,
                binding.operation,
                binding.arguments_digest,
                binding.session_generation,
                secrets.token_hex(32),
            )
            self._authorizations[id(authorization)] = authorization
        outcome = "completed"
        uncertainty = False
        reason = ""
        result: object | None = None
        try:
            result = registration.port.dispatch(
                binding.operation, dict(arguments), authorization
            )
        except Exception as exc:
            outcome, reason = "failed", type(exc).__name__
        finally:
            with self._lock:
                self._inflight.discard(binding.binding_id)
                if self._killed or binding.binding_id in self._revoked:
                    outcome, uncertainty, reason, result = "uncertain", True, "kill-or-revoke-during-dispatch", None
        receipt = CapabilityReceipt(binding.binding_id, outcome, result, uncertainty, reason)
        self._nucleus.record_capability_receipt(
            binding_id=binding.binding_id,
            outcome=outcome,
            receipt_digest=_digest(asdict(receipt)),
            uncertainty=uncertainty,
        )
        return receipt

    def revoke(self, binding_id: str, reason: str = "owner-revoke") -> None:
        with self._lock:
            self._revoked.add(binding_id)
            self._nucleus.revoke_capability_binding(binding_id, reason)
            for registration in self._registry.values():
                registration.port.revoke(binding_id)

    def kill(self) -> KillReceipt:
        with self._lock:
            if self._kill_receipt is not None:
                return self._kill_receipt
            self._killed = True
            # The durable authority latch is the first propagated effect.
            nucleus_receipt = self._nucleus.global_kill()
            statuses, uncertainty = self._stop_participants()
            receipt = KillReceipt(
                "kill-latched", nucleus_receipt, tuple(statuses), uncertainty
            )
            self._kill_receipt = receipt
            return receipt

    def shutdown(self) -> KillReceipt:
        """Stop this process's ports without creating a durable global kill."""

        with self._lock:
            if self._kill_receipt is not None:
                return self._kill_receipt
            if self._shutdown_receipt is not None:
                return self._shutdown_receipt
            self._killed = True
            uncertainty = False
            try:
                self._nucleus.end_session("shutdown")
                nucleus_receipt: Mapping[str, object] = {
                    "status": "session-ended",
                    "durable_global_kill": False,
                }
            except Exception as exc:
                uncertainty = True
                nucleus_receipt = {
                    "status": "incomplete",
                    "durable_global_kill": False,
                    "error": type(exc).__name__,
                }
            statuses, participant_uncertainty = self._stop_participants()
            receipt = KillReceipt(
                "shutdown-local",
                nucleus_receipt,
                tuple(statuses),
                uncertainty or participant_uncertainty,
            )
            self._shutdown_receipt = receipt
            return receipt

    def _stop_participants(self) -> tuple[list[tuple[str, str]], bool]:
        statuses: list[tuple[str, str]] = []
        uncertainty = False
        for capability, registration in sorted(self._registry.items()):
            try:
                observed = registration.port.kill()
                status = (
                    "confirmed"
                    if observed is not False
                    else "incomplete:returned-false"
                )
            except Exception:
                status = "incomplete:exception"
            uncertainty |= not status.startswith("confirmed")
            statuses.append((capability, status))
        return statuses, uncertainty

    @property
    def killed(self) -> bool:
        with self._lock:
            return self._killed or self._nucleus.killed


__all__ = [
    "ActionBinding", "CapabilityPort", "CapabilityReceipt",
    "GovernedCapabilityHostV1", "HostBoundCapabilityPortV1", "KillReceipt",
]
