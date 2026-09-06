"""Host-owned Phase 5 integration core (isolated V2 candidate).

V2 retains the deliberately narrow V1 authority: only the exact, local,
provider-free ``local.catalog/catalog_read`` operation can be allowed.  It is
still default-off, event-driven, read-only at its projection surfaces, and is
not imported by any live/startup surface.

The V2 boundary snapshots every public contract, authenticates issued allow
decisions by object identity plus a private registry seal, carries upstream
projection cursors end-to-end, and makes termination a blocking single-flight
operation.  There are no worker threads or polling loops.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Protocol, TypeVar


PHASE5_RUNTIME_FLAG = "ONYX_PHASE5_RUNTIME_V2"
PHASE5_GRANT_SHADOW_FLAG = "ONYX_PHASE5_GRANT_SHADOW_V2"
PHASE5_APPROVAL_INBOX_FLAG = "ONYX_PHASE5_APPROVAL_INBOX_V2"
PHASE5_LOW_RISK_FLAG = "ONYX_PHASE5_LOW_RISK_V2"
PHASE5_NEXUS_PROJECTION_FLAG = "ONYX_PHASE5_NEXUS_PROJECTION_V2"
PHASE5_LOCAL_CATALOG_READ_FLAG = "ONYX_PHASE5_LOCAL_CATALOG_READ_V2"
PHASE5_DASHBOARD_PROJECTION_FLAG = "ONYX_PHASE5_DASHBOARD_PROJECTION_V2"

MAX_PROJECTION_ITEMS = 128
MAX_PAGE_SIZE = 50
MAX_EVENTS = 128
MAX_DECISION_SEALS = 128
MAX_PROJECTION_ROW_BYTES = 4_096
MAX_EVENT_DETAIL_BYTES = 2_048
MAX_TEXT = 1_024
MAX_DEPTH = 5
MAX_INTEGER = 9_223_372_036_854_775_807

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:authorization|credential|password|private[_-]?key|secret|token)(?:$|[_-])",
    re.IGNORECASE,
)
_EXPLICIT_WORDS = frozenset(
    {
        "ad", "ads", "advertise", "approve", "buy", "charge", "credential",
        "credentials", "crisis", "delete", "deploy", "email", "grant", "install",
        "invoice", "legal", "message", "money", "oauth", "pay", "payment",
        "political", "privileged", "publish", "purchase", "refund", "role", "roles",
        "send", "transfer",
    }
)
_RISKS = frozenset({"low", "medium", "high", "critical"})


class Phase5RuntimeV2Error(RuntimeError):
    """Base error for the isolated V2 runtime core."""


class Phase5RuntimeV2ContractError(ValueError):
    """A host-supplied value violated the bounded V2 contract."""


class RuntimeDispositionV2(str, Enum):
    FALLBACK = "FALLBACK"
    ALLOW_LOCAL_CATALOG_READ = "ALLOW_LOCAL_CATALOG_READ"
    EXPLICIT = "EXPLICIT"


class RuntimeStateV2(str, Enum):
    DISABLED = "DISABLED"
    READY = "READY"
    DEGRADED = "DEGRADED"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"


class TerminalReasonV2(str, Enum):
    KILL = "kill"
    REVOKE = "revoke"
    ROLLBACK = "rollback"
    END_SESSION = "end_session"
    RECONNECT = "reconnect"
    SHUTDOWN = "shutdown"


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise Phase5RuntimeV2ContractError(f"{label} must be an exact boolean")
    return value


def _safe_id(value: object, label: str) -> str:
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        raise Phase5RuntimeV2ContractError(f"{label} is invalid")
    return value


def _optional_safe_id(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _safe_id(value, label)


def _bounded_text(value: object, label: str, maximum: int = MAX_TEXT) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise Phase5RuntimeV2ContractError(f"{label} is invalid")
    return value


def _flag(raw: object) -> bool:
    return type(raw) is str and raw.strip().casefold() in {"1", "true"}


@dataclass(frozen=True, slots=True)
class RuntimeFlagsV2:
    runtime: bool = False
    grant_shadow: bool = False
    approval_inbox: bool = False
    low_risk: bool = False
    nexus_projection: bool = False
    local_catalog_read: bool = False
    dashboard_projection: bool = False

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _exact_bool(getattr(self, name), name)

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> RuntimeFlagsV2:
        source = os.environ if environ is None else environ
        return cls(
            runtime=_flag(source.get(PHASE5_RUNTIME_FLAG, "")),
            grant_shadow=_flag(source.get(PHASE5_GRANT_SHADOW_FLAG, "")),
            approval_inbox=_flag(source.get(PHASE5_APPROVAL_INBOX_FLAG, "")),
            low_risk=_flag(source.get(PHASE5_LOW_RISK_FLAG, "")),
            nexus_projection=_flag(source.get(PHASE5_NEXUS_PROJECTION_FLAG, "")),
            local_catalog_read=_flag(source.get(PHASE5_LOCAL_CATALOG_READ_FLAG, "")),
            dashboard_projection=_flag(source.get(PHASE5_DASHBOARD_PROJECTION_FLAG, "")),
        )

    def payload(self) -> tuple[tuple[str, bool], ...]:
        return tuple((name, getattr(self, name)) for name in self.__dataclass_fields__)


@dataclass(frozen=True, slots=True)
class RuntimeBindingV2:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _safe_id(getattr(self, name), name))


def _snapshot_binding(value: object) -> RuntimeBindingV2:
    if type(value) is not RuntimeBindingV2:
        raise Phase5RuntimeV2ContractError("binding must be exact RuntimeBindingV2")
    return RuntimeBindingV2(
        trace_id=value.trace_id,
        session_id=value.session_id,
        workspace_id=value.workspace_id,
        account_id=value.account_id,
        profile_id=value.profile_id,
    )


def _snapshot_flags(value: object) -> RuntimeFlagsV2:
    if type(value) is not RuntimeFlagsV2:
        raise Phase5RuntimeV2ContractError("flags must be exact RuntimeFlagsV2")
    return RuntimeFlagsV2(**dict(value.payload()))


@dataclass(frozen=True, slots=True)
class ActionRequestV2:
    invocation_ref: str
    binding: RuntimeBindingV2
    capability: str
    operation: str
    provider_free: bool
    read_only: bool
    effect: str
    egress: str
    metadata_allowlisted: bool
    cost_micro: int
    risk: str
    reversible: bool
    uses_credentials: bool = False
    privileged: bool = False
    irreversible: bool = False
    action_classes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "invocation_ref", _safe_id(self.invocation_ref, "invocation_ref"))
        object.__setattr__(self, "binding", _snapshot_binding(self.binding))
        for name in ("capability", "operation", "effect", "egress", "risk"):
            object.__setattr__(self, name, _bounded_text(getattr(self, name), name, 128))
        for name in (
            "provider_free", "read_only", "metadata_allowlisted", "reversible",
            "uses_credentials", "privileged", "irreversible",
        ):
            _exact_bool(getattr(self, name), name)
        if type(self.cost_micro) is not int or not 0 <= self.cost_micro <= MAX_INTEGER:
            raise Phase5RuntimeV2ContractError("cost_micro is invalid")
        if self.risk not in _RISKS:
            raise Phase5RuntimeV2ContractError("risk is invalid")
        if type(self.action_classes) is not tuple or len(self.action_classes) > 32:
            raise Phase5RuntimeV2ContractError("action_classes is invalid")
        classes = tuple(_safe_id(item, "action_class").casefold() for item in self.action_classes)
        if len(set(classes)) != len(classes):
            raise Phase5RuntimeV2ContractError("action_classes contains duplicates")
        object.__setattr__(self, "action_classes", tuple(sorted(classes)))


def _snapshot_action(value: object) -> ActionRequestV2:
    if type(value) is not ActionRequestV2:
        raise Phase5RuntimeV2ContractError("action must be exact ActionRequestV2")
    return ActionRequestV2(
        invocation_ref=value.invocation_ref,
        binding=value.binding,
        capability=value.capability,
        operation=value.operation,
        provider_free=value.provider_free,
        read_only=value.read_only,
        effect=value.effect,
        egress=value.egress,
        metadata_allowlisted=value.metadata_allowlisted,
        cost_micro=value.cost_micro,
        risk=value.risk,
        reversible=value.reversible,
        uses_credentials=value.uses_credentials,
        privileged=value.privileged,
        irreversible=value.irreversible,
        action_classes=value.action_classes,
    )


@dataclass(frozen=True, slots=True)
class RuntimeDecisionV2:
    disposition: RuntimeDispositionV2
    reason: str
    trace_id: str
    epoch: int
    advisory_json: str = "{}"

    def __post_init__(self) -> None:
        if type(self.disposition) is not RuntimeDispositionV2:
            raise Phase5RuntimeV2ContractError("decision disposition is invalid")
        _bounded_text(self.reason, "reason", 128)
        _safe_id(self.trace_id, "trace_id")
        if type(self.epoch) is not int or self.epoch < 1:
            raise Phase5RuntimeV2ContractError("decision epoch is invalid")
        if type(self.advisory_json) is not str or len(self.advisory_json.encode()) > MAX_EVENT_DETAIL_BYTES:
            raise Phase5RuntimeV2ContractError("advisory_json is invalid")
        try:
            parsed = json.loads(self.advisory_json)
        except json.JSONDecodeError as exc:
            raise Phase5RuntimeV2ContractError("advisory_json is invalid") from exc
        if type(parsed) is not dict:
            raise Phase5RuntimeV2ContractError("advisory_json must be an object")


def _json_value(value: object, *, depth: int = 0) -> object:
    if depth > MAX_DEPTH:
        raise Phase5RuntimeV2ContractError("projection nesting is too deep")
    if value is None or type(value) in {bool, int}:
        if type(value) is int and not -MAX_INTEGER <= value <= MAX_INTEGER:
            raise Phase5RuntimeV2ContractError("projection integer is out of bounds")
        return value
    if type(value) is str:
        if len(value) > MAX_TEXT or any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise Phase5RuntimeV2ContractError("projection text is invalid")
        return value
    if type(value) in {list, tuple}:
        if len(value) > 64:
            raise Phase5RuntimeV2ContractError("projection sequence is too large")
        return [_json_value(item, depth=depth + 1) for item in value]
    if type(value) is dict or type(value) is MappingProxyType:
        if len(value) > 64:
            raise Phase5RuntimeV2ContractError("projection object is too large")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 128 or _SENSITIVE_KEY.search(key):
                raise Phase5RuntimeV2ContractError("projection key is unsafe")
            result[key] = _json_value(item, depth=depth + 1)
        return result
    raise Phase5RuntimeV2ContractError("projection contains a non-JSON value")


def _freeze_json(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProjectionBatchV2:
    """One immutable upstream page with its request and continuation cursors."""

    items: tuple[Mapping[str, object], ...]
    replace: bool = True
    source_cursor: str | None = None
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.items) is not tuple or len(self.items) > MAX_PAGE_SIZE:
            raise Phase5RuntimeV2ContractError("projection batch is invalid")
        normalized: list[Mapping[str, object]] = []
        for item in self.items:
            if type(item) is not dict and type(item) is not MappingProxyType:
                raise Phase5RuntimeV2ContractError("projection items must be exact dictionaries")
            value = _json_value(item)
            assert type(value) is dict
            normalized.append(_freeze_json(value))  # type: ignore[arg-type]
        object.__setattr__(self, "items", tuple(normalized))
        _exact_bool(self.replace, "replace")
        object.__setattr__(self, "source_cursor", _optional_safe_id(self.source_cursor, "source_cursor"))
        object.__setattr__(self, "next_cursor", _optional_safe_id(self.next_cursor, "next_cursor"))
        if self.next_cursor is not None and self.next_cursor == self.source_cursor:
            raise Phase5RuntimeV2ContractError("projection cursor does not advance")


def _snapshot_batch(value: object) -> ProjectionBatchV2:
    if type(value) is not ProjectionBatchV2:
        raise Phase5RuntimeV2ContractError("component returned the wrong batch type")
    items = tuple(dict(_json_value(item)) for item in value.items)
    return ProjectionBatchV2(
        items,
        replace=value.replace,
        source_cursor=value.source_cursor,
        next_cursor=value.next_cursor,
    )


class ApprovalInboxReaderV2(Protocol):
    def read_page(
        self,
        *,
        binding: RuntimeBindingV2,
        page_size: int,
        cursor: str | None,
    ) -> ProjectionBatchV2: ...


@dataclass(frozen=True, slots=True)
class RuntimeComponentsV2:
    grant_evaluator: Callable[[str], object] | None = None
    nexus_projector: Callable[[RuntimeBindingV2], ProjectionBatchV2] | None = None
    inbox_factory: Callable[[RuntimeBindingV2], ApprovalInboxReaderV2] | None = None
    grant_terminator: Callable[[str], None] | None = None
    nexus_terminator: Callable[[str], None] | None = None
    inbox_terminator: Callable[[str], None] | None = None
    rollback_callback: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise Phase5RuntimeV2ContractError(f"{name} must be callable")


def _snapshot_components(value: object) -> RuntimeComponentsV2:
    if type(value) is not RuntimeComponentsV2:
        raise Phase5RuntimeV2ContractError("components must be exact RuntimeComponentsV2")
    return RuntimeComponentsV2(**{name: getattr(value, name) for name in value.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class ProjectionItemV2:
    item_id: str
    payload_json: str

    def payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        assert type(value) is dict
        return value


@dataclass(frozen=True, slots=True)
class ProjectionPageV2:
    kind: str
    offset: int
    page_size: int
    total: int
    items: tuple[ProjectionItemV2, ...]
    next_offset: int | None
    source_cursor: str | None
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class RuntimeEventV2:
    sequence: int
    kind: str
    outcome: str
    detail_json: str

    def detail(self) -> dict[str, object]:
        value = json.loads(self.detail_json)
        assert type(value) is dict
        return value


@dataclass(frozen=True, slots=True)
class RuntimeStatusV2:
    state: RuntimeStateV2
    reason: str
    epoch: int
    binding: RuntimeBindingV2
    flags: tuple[tuple[str, bool], ...]
    capability_count: int
    inbox_count: int
    event_count: int
    component_failures: tuple[str, ...]
    termination_failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DecisionSealV2:
    decision: RuntimeDecisionV2
    public_digest: str
    request_digest: str
    binding_digest: str
    flags_digest: str
    epoch: int
    authority_digest: str


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _binding_digest(binding: RuntimeBindingV2) -> str:
    return _canonical_digest(
        [binding.trace_id, binding.session_id, binding.workspace_id, binding.account_id, binding.profile_id]
    )


def _flags_digest(flags: RuntimeFlagsV2) -> str:
    return _canonical_digest(flags.payload())


def _action_digest(action: ActionRequestV2) -> str:
    return _canonical_digest(
        {
            "invocation_ref": action.invocation_ref,
            "binding": _binding_digest(action.binding),
            "capability": action.capability,
            "operation": action.operation,
            "provider_free": action.provider_free,
            "read_only": action.read_only,
            "effect": action.effect,
            "egress": action.egress,
            "metadata_allowlisted": action.metadata_allowlisted,
            "cost_micro": action.cost_micro,
            "risk": action.risk,
            "reversible": action.reversible,
            "uses_credentials": action.uses_credentials,
            "privileged": action.privileged,
            "irreversible": action.irreversible,
            "action_classes": action.action_classes,
        }
    )


def _decision_digest(decision: RuntimeDecisionV2) -> str:
    return _canonical_digest(
        [decision.disposition.value, decision.reason, decision.trace_id, decision.epoch, decision.advisory_json]
    )


def _authority_digest(
    key: bytes,
    *,
    public_digest: str,
    request_digest: str,
    binding_digest: str,
    flags_digest: str,
    epoch: int,
) -> str:
    payload = "\x00".join(
        (public_digest, request_digest, binding_digest, flags_digest, str(epoch))
    ).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _projection_record(raw: Mapping[str, object], *, identifier_key: str) -> ProjectionItemV2:
    normalized = _json_value(raw)
    assert type(normalized) is dict
    identifier = _safe_id(normalized.get(identifier_key), identifier_key)
    encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_PROJECTION_ROW_BYTES:
        raise Phase5RuntimeV2ContractError("projection row is too large")
    return ProjectionItemV2(identifier, encoded)


def _advisory(value: object) -> str:
    if value is None:
        payload: dict[str, object] = {"outcome": "none"}
    elif type(value) is dict:
        payload = value
    else:
        payload = {}
        for name in ("outcome", "reason", "grant_id", "scope_digest", "action_digest"):
            item = getattr(value, name, None)
            if item is not None and type(item) in {str, int, bool}:
                payload[name] = item
        if not payload:
            payload = {"outcome": type(value).__name__}
    normalized = _json_value(payload)
    encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_EVENT_DETAIL_BYTES:
        raise Phase5RuntimeV2ContractError("grant advisory is too large")
    return encoded


_T = TypeVar("_T")


class Phase5RuntimeV2:
    """Bounded, event-driven host policy extension with one terminal boundary."""

    def __init__(
        self,
        *,
        binding: RuntimeBindingV2,
        flags: RuntimeFlagsV2 | None = None,
        components: RuntimeComponentsV2 | None = None,
    ) -> None:
        if flags is None:
            flags = RuntimeFlagsV2.from_environ()
        if components is None:
            components = RuntimeComponentsV2()
        self._binding = _snapshot_binding(binding)
        self._flags = _snapshot_flags(flags)
        self._components = _snapshot_components(components)
        self._lock = threading.RLock()
        self._terminal_condition = threading.Condition(self._lock)
        self._epoch = 1
        self._terminated = False
        self._termination_running = False
        self._termination_complete = False
        self._termination_owner_thread: int | None = None
        self._terminal_reason: str | None = None
        self._component_failures: set[str] = set()
        self._termination_failures: set[str] = set()
        self._capabilities: OrderedDict[str, ProjectionItemV2] = OrderedDict()
        self._inbox: OrderedDict[str, ProjectionItemV2] = OrderedDict()
        self._capability_source_cursor: str | None = None
        self._capability_next_cursor: str | None = None
        self._inbox_source_cursor: str | None = None
        self._inbox_next_cursor: str | None = None
        self._inbox_started = False
        self._inbox_cursor_history: set[str] = set()
        self._events: deque[RuntimeEventV2] = deque(maxlen=MAX_EVENTS)
        self._event_sequence = 0
        self._decision_seals: OrderedDict[int, _DecisionSealV2] = OrderedDict()
        self._decision_key = secrets.token_bytes(32)

    @property
    def binding(self) -> RuntimeBindingV2:
        with self._lock:
            return _snapshot_binding(self._binding)

    @property
    def flags(self) -> RuntimeFlagsV2:
        with self._lock:
            return _snapshot_flags(self._flags)

    def _clear_projections_locked(self) -> None:
        self._capabilities.clear()
        self._inbox.clear()
        self._capability_source_cursor = None
        self._capability_next_cursor = None
        self._inbox_source_cursor = None
        self._inbox_next_cursor = None
        self._inbox_started = False
        self._inbox_cursor_history.clear()

    def _retire_authority_locked(self) -> None:
        self._epoch += 1
        self._decision_seals.clear()
        self._clear_projections_locked()

    def rebind(self, binding: RuntimeBindingV2) -> RuntimeStatusV2:
        snapshot = _snapshot_binding(binding)
        with self._lock:
            if self._terminated:
                raise Phase5RuntimeV2Error("runtime is terminated")
            self._binding = snapshot
            self._retire_authority_locked()
            self._event_locked("configuration", "binding_replaced", {})
            return self._status_locked()

    def configure_flags(self, flags: RuntimeFlagsV2) -> RuntimeStatusV2:
        snapshot = _snapshot_flags(flags)
        with self._lock:
            if self._terminated:
                raise Phase5RuntimeV2Error("runtime is terminated")
            self._flags = snapshot
            self._retire_authority_locked()
            self._component_failures.clear()
            self._event_locked("configuration", "flags_replaced", {})
            return self._status_locked()

    def replace_components(self, components: RuntimeComponentsV2) -> RuntimeStatusV2:
        snapshot = _snapshot_components(components)
        with self._lock:
            if self._terminated:
                raise Phase5RuntimeV2Error("runtime is terminated")
            self._components = snapshot
            self._retire_authority_locked()
            self._component_failures.clear()
            self._event_locked("configuration", "components_replaced", {})
            return self._status_locked()

    def _state_locked(self) -> RuntimeStateV2:
        if self._termination_running:
            return RuntimeStateV2.TERMINATING
        if self._termination_complete:
            return RuntimeStateV2.TERMINATED
        if not self._flags.runtime:
            return RuntimeStateV2.DISABLED
        if self._component_failures:
            return RuntimeStateV2.DEGRADED
        return RuntimeStateV2.READY

    def _reason_locked(self) -> str:
        if self._terminated:
            return self._terminal_reason or "terminated"
        if not self._flags.runtime:
            return "feature_flag_off"
        if self._component_failures:
            return "component_failure"
        return "ready"

    def _status_locked(self) -> RuntimeStatusV2:
        return RuntimeStatusV2(
            self._state_locked(), self._reason_locked(), self._epoch, _snapshot_binding(self._binding),
            self._flags.payload(), len(self._capabilities), len(self._inbox), len(self._events),
            tuple(sorted(self._component_failures)), tuple(sorted(self._termination_failures)),
        )

    def status(self) -> RuntimeStatusV2:
        with self._lock:
            return self._status_locked()

    def _event_locked(self, kind: str, outcome: str, detail: Mapping[str, object]) -> None:
        normalized = _json_value(dict(detail))
        encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > MAX_EVENT_DETAIL_BYTES:
            raise Phase5RuntimeV2ContractError("event detail is too large")
        self._event_sequence += 1
        self._events.append(RuntimeEventV2(self._event_sequence, kind, outcome, encoded))

    def events(self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE) -> tuple[RuntimeEventV2, ...]:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            selected = tuple(self._events)[offset : offset + page_size]
            return tuple(
                RuntimeEventV2(item.sequence, item.kind, item.outcome, item.detail_json)
                for item in selected
            )

    @staticmethod
    def _page_bounds(offset: int, page_size: int) -> tuple[int, int]:
        if type(offset) is not int or not 0 <= offset <= MAX_PROJECTION_ITEMS:
            raise Phase5RuntimeV2ContractError("offset is invalid")
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise Phase5RuntimeV2ContractError("page_size is invalid")
        return offset, page_size

    def _decision_locked(
        self,
        disposition: RuntimeDispositionV2,
        reason: str,
        advisory_json: str = "{}",
        *,
        request_digest: str | None = None,
        publish: bool = True,
    ) -> RuntimeDecisionV2:
        decision = RuntimeDecisionV2(disposition, reason, self._binding.trace_id, self._epoch, advisory_json)
        if not publish:
            return decision
        self._event_locked("decision", disposition.value, {"reason": reason})
        if disposition is RuntimeDispositionV2.ALLOW_LOCAL_CATALOG_READ:
            if request_digest is None:
                raise Phase5RuntimeV2ContractError("allow decision has no request digest")
            public_digest = _decision_digest(decision)
            binding_digest = _binding_digest(self._binding)
            flags_digest = _flags_digest(self._flags)
            authority_digest = _authority_digest(
                self._decision_key,
                public_digest=public_digest,
                request_digest=request_digest,
                binding_digest=binding_digest,
                flags_digest=flags_digest,
                epoch=self._epoch,
            )
            seal = _DecisionSealV2(
                decision, public_digest, request_digest, binding_digest, flags_digest,
                self._epoch, authority_digest,
            )
            self._decision_seals[id(decision)] = seal
            while len(self._decision_seals) > MAX_DECISION_SEALS:
                self._decision_seals.popitem(last=False)
        return decision

    def _set_component_failure_locked(self, name: str, failed: bool) -> None:
        changed = False
        if failed and name not in self._component_failures:
            self._component_failures.add(name)
            changed = True
        elif not failed and name in self._component_failures:
            self._component_failures.remove(name)
            changed = True
        if changed:
            self._epoch += 1
            self._decision_seals.clear()

    @staticmethod
    def _contains_explicit_intent(action: ActionRequestV2) -> bool:
        if action.uses_credentials or action.privileged or action.irreversible or action.action_classes:
            return True
        words = set(re.findall(r"[a-z0-9]+", f"{action.capability} {action.operation}".casefold()))
        return bool(words & _EXPLICIT_WORDS)

    def evaluate(self, action: ActionRequestV2) -> RuntimeDecisionV2:
        with self._lock:
            if self._terminated:
                return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "runtime_terminated")
            if not self._flags.runtime:
                return self._decision_locked(
                    RuntimeDispositionV2.FALLBACK, "feature_flag_off", publish=False
                )
            try:
                snapshot = _snapshot_action(action)
            except (AttributeError, Phase5RuntimeV2ContractError):
                return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "invalid_action_contract")
            if self._contains_explicit_intent(snapshot):
                return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "explicit_action_class")
            if not self._flags.low_risk or not self._flags.local_catalog_read:
                return self._decision_locked(
                    RuntimeDispositionV2.FALLBACK, "extension_path_off", publish=False
                )
            if snapshot.binding != self._binding:
                return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "scope_mismatch")
            if self._component_failures:
                return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "component_failure")
            exact_catalog_read = (
                snapshot.capability == "local.catalog"
                and snapshot.operation == "catalog_read"
                and snapshot.provider_free
                and snapshot.read_only
                and snapshot.effect == "none"
                and snapshot.egress == "none"
                and snapshot.metadata_allowlisted
                and snapshot.cost_micro == 0
                and snapshot.risk == "low"
                and snapshot.reversible
                and not snapshot.uses_credentials
                and not snapshot.privileged
                and not snapshot.irreversible
            )
            if not exact_catalog_read:
                return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "not_exact_local_catalog_read")
            lease = self._epoch
            digest = _action_digest(snapshot)
            observer = self._components.grant_evaluator if self._flags.grant_shadow else None
            if self._flags.grant_shadow and observer is None:
                self._set_component_failure_locked("grant_shadow", True)
                return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "grant_shadow_unavailable")

        advisory_json = "{}"
        if observer is not None:
            try:
                advisory_json = _advisory(observer(snapshot.invocation_ref))
            except BaseException:
                with self._lock:
                    if self._terminated or self._epoch != lease:
                        return self._decision_locked(
                            RuntimeDispositionV2.EXPLICIT, "authority_revoked_during_evaluation"
                        )
                    self._set_component_failure_locked("grant_shadow", True)
                    return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "grant_shadow_failure")

        with self._lock:
            if self._terminated or self._epoch != lease:
                return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "authority_revoked_during_evaluation")
            if self._component_failures:
                return self._decision_locked(RuntimeDispositionV2.EXPLICIT, "component_failure_during_evaluation")
            return self._decision_locked(
                RuntimeDispositionV2.ALLOW_LOCAL_CATALOG_READ,
                "exact_provider_free_catalog_read",
                advisory_json,
                request_digest=digest,
            )

    def legacy_or_decision(self, action: ActionRequestV2, legacy: Callable[[], _T]) -> _T | RuntimeDecisionV2:
        if not callable(legacy):
            raise Phase5RuntimeV2ContractError("legacy fallback must be callable")
        decision = self.evaluate(action)
        if decision.disposition is RuntimeDispositionV2.FALLBACK:
            return legacy()
        return decision

    def decision_is_current(self, decision: RuntimeDecisionV2) -> bool:
        if type(decision) is not RuntimeDecisionV2:
            return False
        with self._lock:
            seal = self._decision_seals.get(id(decision))
            if seal is None or seal.decision is not decision:
                return False
            if (
                type(decision.disposition) is not RuntimeDispositionV2
                or type(decision.reason) is not str
                or type(decision.trace_id) is not str
                or type(decision.epoch) is not int
                or type(decision.advisory_json) is not str
            ):
                return False
            try:
                public_digest = _decision_digest(decision)
            except (AttributeError, TypeError, ValueError):
                return False
            current_binding_digest = _binding_digest(self._binding)
            current_flags_digest = _flags_digest(self._flags)
            authority_digest = _authority_digest(
                self._decision_key,
                public_digest=public_digest,
                request_digest=seal.request_digest,
                binding_digest=current_binding_digest,
                flags_digest=current_flags_digest,
                epoch=self._epoch,
            )
            return (
                decision.disposition is RuntimeDispositionV2.ALLOW_LOCAL_CATALOG_READ
                and not self._terminated
                and not self._component_failures
                and seal.epoch == self._epoch
                and decision.epoch == self._epoch
                and decision.trace_id == self._binding.trace_id
                and hmac.compare_digest(seal.public_digest, public_digest)
                and hmac.compare_digest(seal.binding_digest, current_binding_digest)
                and hmac.compare_digest(seal.flags_digest, current_flags_digest)
                and hmac.compare_digest(seal.authority_digest, authority_digest)
            )

    def _component_failed(self, name: str, lease: int) -> None:
        with self._lock:
            if not self._terminated and lease == self._epoch:
                self._set_component_failure_locked(name, True)
                self._event_locked("component", "failure", {"component": name})

    @staticmethod
    def _prepare_batch(
        batch: ProjectionBatchV2,
        *,
        identifier_key: str,
    ) -> tuple[ProjectionBatchV2, tuple[ProjectionItemV2, ...]]:
        snapshot = _snapshot_batch(batch)
        records = tuple(_projection_record(item, identifier_key=identifier_key) for item in snapshot.items)
        if len({item.item_id for item in records}) != len(records):
            raise Phase5RuntimeV2ContractError("projection page contains duplicate identifiers")
        return snapshot, records

    @staticmethod
    def _apply_records_locked(
        target: OrderedDict[str, ProjectionItemV2],
        records: tuple[ProjectionItemV2, ...],
        *,
        replace: bool,
        forbid_existing: bool = False,
    ) -> None:
        if forbid_existing and any(record.item_id in target for record in records):
            raise Phase5RuntimeV2ContractError("projection page repeats an earlier identifier")
        if replace:
            target.clear()
        for record in records:
            target.pop(record.item_id, None)
            target[record.item_id] = record
        while len(target) > MAX_PROJECTION_ITEMS:
            target.popitem(last=False)

    def refresh_capabilities(self) -> ProjectionPageV2:
        with self._lock:
            if self._terminated or not self._flags.runtime or not self._flags.nexus_projection:
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
            projector = self._components.nexus_projector
            lease = self._epoch
            binding = _snapshot_binding(self._binding)
            if projector is None:
                self._set_component_failure_locked("nexus", True)
                self._event_locked("capabilities", "unavailable", {})
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
        try:
            snapshot, records = self._prepare_batch(projector(binding), identifier_key="capability_id")
        except BaseException:
            self._component_failed("nexus", lease)
            return self.capabilities()
        with self._lock:
            if self._terminated or self._epoch != lease:
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
            self._apply_records_locked(self._capabilities, records, replace=snapshot.replace)
            self._capability_source_cursor = snapshot.source_cursor
            self._capability_next_cursor = snapshot.next_cursor
            self._set_component_failure_locked("nexus", False)
            self._event_locked("capabilities", "refreshed", {"count": len(records)})
            return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)

    def refresh_inbox(self, *, cursor: str | None = None, page_size: int = MAX_PAGE_SIZE) -> ProjectionPageV2:
        _, page_size = self._page_bounds(0, page_size)
        cursor = _optional_safe_id(cursor, "cursor")
        with self._lock:
            if self._terminated or not self._flags.runtime or not self._flags.approval_inbox:
                return self._page_locked("inbox", 0, page_size)
            if self._inbox_started and self._inbox_next_cursor is not None and cursor != self._inbox_next_cursor:
                raise Phase5RuntimeV2ContractError("inbox cursor is not the expected continuation")
            if self._inbox_started and self._inbox_next_cursor is None and cursor is not None:
                raise Phase5RuntimeV2ContractError("inbox projection has no continuation")
            factory = self._components.inbox_factory
            lease = self._epoch
            binding = _snapshot_binding(self._binding)
            if factory is None:
                self._set_component_failure_locked("inbox", True)
                self._event_locked("inbox", "unavailable", {})
                return self._page_locked("inbox", 0, page_size)
        try:
            reader = factory(binding)
            read_page = getattr(reader, "read_page")
            if not callable(read_page):
                raise Phase5RuntimeV2ContractError("inbox reader has no read_page")
            returned = read_page(binding=_snapshot_binding(binding), page_size=page_size, cursor=cursor)
            snapshot, records = self._prepare_batch(returned, identifier_key="item_id")
            if snapshot.source_cursor != cursor:
                raise Phase5RuntimeV2ContractError("inbox source cursor mismatch")
            if cursor is None and not snapshot.replace:
                raise Phase5RuntimeV2ContractError("first inbox page must replace")
            if cursor is not None and snapshot.replace:
                raise Phase5RuntimeV2ContractError("continuation inbox page cannot replace")
        except BaseException:
            self._component_failed("inbox", lease)
            return self.inbox(page_size=page_size)
        with self._lock:
            if self._terminated or self._epoch != lease:
                return self._page_locked("inbox", 0, page_size)
            if cursor is not None and cursor in self._inbox_cursor_history:
                self._set_component_failure_locked("inbox", True)
                return self._page_locked("inbox", 0, page_size)
            if snapshot.next_cursor is not None and snapshot.next_cursor in self._inbox_cursor_history:
                self._set_component_failure_locked("inbox", True)
                return self._page_locked("inbox", 0, page_size)
            try:
                self._apply_records_locked(
                    self._inbox,
                    records,
                    replace=snapshot.replace,
                    forbid_existing=cursor is not None,
                )
            except Phase5RuntimeV2ContractError:
                self._set_component_failure_locked("inbox", True)
                return self._page_locked("inbox", 0, page_size)
            if cursor is None:
                self._inbox_cursor_history.clear()
            else:
                self._inbox_cursor_history.add(cursor)
            self._inbox_started = True
            self._inbox_source_cursor = snapshot.source_cursor
            self._inbox_next_cursor = snapshot.next_cursor
            self._set_component_failure_locked("inbox", False)
            self._event_locked("inbox", "refreshed", {"count": len(records)})
            return self._page_locked("inbox", 0, page_size)

    def _page_locked(self, kind: str, offset: int, page_size: int) -> ProjectionPageV2:
        if kind == "capabilities":
            target = self._capabilities
            source_cursor = self._capability_source_cursor
            next_cursor = self._capability_next_cursor
        else:
            target = self._inbox
            source_cursor = self._inbox_source_cursor
            next_cursor = self._inbox_next_cursor
        values = tuple(target.values())
        items = tuple(
            ProjectionItemV2(item.item_id, item.payload_json)
            for item in values[offset : offset + page_size]
        )
        next_offset = offset + len(items) if offset + len(items) < len(values) else None
        return ProjectionPageV2(
            kind, offset, page_size, len(values), items, next_offset, source_cursor, next_cursor
        )

    def capabilities(self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE) -> ProjectionPageV2:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return self._page_locked("capabilities", offset, page_size)

    def inbox(self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE) -> ProjectionPageV2:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return self._page_locked("inbox", offset, page_size)

    def dashboard_read(
        self,
        surface: str,
        *,
        offset: int = 0,
        page_size: int = MAX_PAGE_SIZE,
    ) -> RuntimeStatusV2 | ProjectionPageV2 | tuple[RuntimeEventV2, ...]:
        if surface not in {"status", "capabilities", "inbox", "events"}:
            raise Phase5RuntimeV2ContractError("dashboard surface is not read-only allowlisted")
        with self._lock:
            if not self._flags.runtime or not self._flags.dashboard_projection:
                raise Phase5RuntimeV2Error("dashboard projection is disabled")
        if surface == "status":
            return self.status()
        if surface == "capabilities":
            return self.capabilities(offset=offset, page_size=page_size)
        if surface == "inbox":
            return self.inbox(offset=offset, page_size=page_size)
        return self.events(offset=offset, page_size=page_size)

    def terminate(self, reason: TerminalReasonV2) -> RuntimeStatusV2:
        """Run external revocation once; all concurrent callers await its outcome."""

        if type(reason) is not TerminalReasonV2:
            raise Phase5RuntimeV2ContractError("terminal reason must be exact")
        with self._terminal_condition:
            if self._termination_complete:
                return self._status_locked()
            if self._termination_running:
                if self._termination_owner_thread == threading.get_ident():
                    raise Phase5RuntimeV2Error("reentrant termination is not allowed")
                while not self._termination_complete:
                    self._terminal_condition.wait()
                return self._status_locked()
            self._termination_running = True
            self._termination_owner_thread = threading.get_ident()
            self._terminated = True
            self._terminal_reason = reason.value
            self._retire_authority_locked()
            self._component_failures.clear()
            self._event_locked("lifecycle", "terminating", {"reason": reason.value})
            callbacks = (
                ("grant", self._components.grant_terminator),
                ("nexus", self._components.nexus_terminator),
                ("inbox", self._components.inbox_terminator),
                ("rollback", self._components.rollback_callback),
            )

        failures: list[str] = []
        for name, callback in callbacks:
            if callback is None:
                continue
            try:
                callback(reason.value)
            except BaseException:
                failures.append(name)

        with self._terminal_condition:
            self._termination_failures.update(failures)
            self._termination_running = False
            self._termination_owner_thread = None
            self._termination_complete = True
            if failures:
                self._event_locked("lifecycle", "termination_callback_failure", {"components": failures})
            self._event_locked("lifecycle", "terminated", {"reason": reason.value})
            outcome = self._status_locked()
            self._terminal_condition.notify_all()
            return outcome

    def kill(self) -> RuntimeStatusV2:
        return self.terminate(TerminalReasonV2.KILL)

    def revoke(self) -> RuntimeStatusV2:
        return self.terminate(TerminalReasonV2.REVOKE)

    def rollback(self) -> RuntimeStatusV2:
        return self.terminate(TerminalReasonV2.ROLLBACK)

    def end_session(self) -> RuntimeStatusV2:
        return self.terminate(TerminalReasonV2.END_SESSION)

    def reconnect(self) -> RuntimeStatusV2:
        return self.terminate(TerminalReasonV2.RECONNECT)

    def shutdown(self) -> RuntimeStatusV2:
        return self.terminate(TerminalReasonV2.SHUTDOWN)


__all__ = [
    "PHASE5_RUNTIME_FLAG", "PHASE5_GRANT_SHADOW_FLAG", "PHASE5_APPROVAL_INBOX_FLAG",
    "PHASE5_LOW_RISK_FLAG", "PHASE5_NEXUS_PROJECTION_FLAG", "PHASE5_LOCAL_CATALOG_READ_FLAG",
    "PHASE5_DASHBOARD_PROJECTION_FLAG", "MAX_PROJECTION_ITEMS", "MAX_PAGE_SIZE", "MAX_EVENTS",
    "MAX_DECISION_SEALS", "ActionRequestV2", "ApprovalInboxReaderV2", "Phase5RuntimeV2",
    "Phase5RuntimeV2ContractError", "Phase5RuntimeV2Error", "ProjectionBatchV2",
    "ProjectionItemV2", "ProjectionPageV2", "RuntimeBindingV2", "RuntimeComponentsV2",
    "RuntimeDecisionV2", "RuntimeDispositionV2", "RuntimeEventV2", "RuntimeFlagsV2",
    "RuntimeStateV2", "RuntimeStatusV2", "TerminalReasonV2",
]
