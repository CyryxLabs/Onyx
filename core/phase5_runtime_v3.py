"""Host-owned Phase 5 integration core (isolated V3 candidate).

This module is deliberately not imported by a live/startup surface.  V3 keeps
the exact V1/V2 authority envelope, but hardens the integration boundary with
per-component configuration leases, closed projection schemas, bounded/DLP
safe snapshots, finite cursor journeys, and request-bound single-use decision
consumption.  It has no worker, timer, polling loop, provider or side effect.
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


PHASE5_RUNTIME_FLAG = "ONYX_PHASE5_RUNTIME_V3"
PHASE5_GRANT_SHADOW_FLAG = "ONYX_PHASE5_GRANT_SHADOW_V3"
PHASE5_APPROVAL_INBOX_FLAG = "ONYX_PHASE5_APPROVAL_INBOX_V3"
PHASE5_LOW_RISK_FLAG = "ONYX_PHASE5_LOW_RISK_V3"
PHASE5_NEXUS_PROJECTION_FLAG = "ONYX_PHASE5_NEXUS_PROJECTION_V3"
PHASE5_LOCAL_CATALOG_READ_FLAG = "ONYX_PHASE5_LOCAL_CATALOG_READ_V3"
PHASE5_DASHBOARD_PROJECTION_FLAG = "ONYX_PHASE5_DASHBOARD_PROJECTION_V3"

MAX_PROJECTION_ITEMS = 128
MAX_PAGE_SIZE = 50
MAX_EVENTS = 128
MAX_DECISION_SEALS = 128
MAX_CURSOR_HISTORY = 128
MAX_PROJECTION_ROW_BYTES = 4_096
MAX_EVENT_TEXT_BYTES = 512
MAX_JSON_BYTES = 16_384
MAX_JSON_NODES = 512
MAX_FANOUT = 64
MAX_TEXT = 1_024
MAX_DEPTH = 5
MAX_INTEGER = 9_223_372_036_854_775_807

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_RFC3339_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|authorization|auth[_-]?code|cookie|credential|"
    r"password|passport|private[_-]?key|secret|session[_-]?cookie|token)(?:$|[_-])",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:bearer\s+[A-Za-z0-9._~+/=-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:api[_-]?key|authorization|auth[_-]?code|cookie|password|secret|token)\s*[:=]\s*\S+|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b|"
    r"\b(?:\d[ -]*?){13,19}\b)",
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
_CAPABILITY_STATUS = frozenset({"available", "degraded", "blocked", "disabled"})
_INBOX_STATE = frozenset({"pending", "approved", "denied", "expired", "revoked"})
_COMPONENTS = frozenset({"grant_shadow", "nexus", "inbox"})


class Phase5RuntimeV3Error(RuntimeError):
    """Base error for the isolated V3 runtime core."""


class Phase5RuntimeV3ContractError(ValueError):
    """A value violated the closed and bounded V3 host contract."""


class RuntimeDispositionV3(str, Enum):
    FALLBACK = "FALLBACK"
    ALLOW_LOCAL_CATALOG_READ = "ALLOW_LOCAL_CATALOG_READ"
    EXPLICIT = "EXPLICIT"


class RuntimeStateV3(str, Enum):
    DISABLED = "DISABLED"
    READY = "READY"
    DEGRADED = "DEGRADED"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"


class TerminalReasonV3(str, Enum):
    KILL = "kill"
    REVOKE = "revoke"
    ROLLBACK = "rollback"
    END_SESSION = "end_session"
    RECONNECT = "reconnect"
    SHUTDOWN = "shutdown"


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise Phase5RuntimeV3ContractError(f"{label} must be an exact boolean")
    return value


def _safe_id(value: object, label: str) -> str:
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        raise Phase5RuntimeV3ContractError(f"{label} is invalid")
    if _SENSITIVE_VALUE.search(value):
        raise Phase5RuntimeV3ContractError(f"{label} contains sensitive data")
    return value


def _optional_safe_id(value: object, label: str) -> str | None:
    return None if value is None else _safe_id(value, label)


def _text(value: object, label: str, maximum: int = MAX_TEXT, *, redact: bool = True) -> str:
    if (
        type(value) is not str or not value or value != value.strip()
        or len(value.encode("utf-8")) > maximum
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise Phase5RuntimeV3ContractError(f"{label} is invalid")
    if _SENSITIVE_VALUE.search(value):
        if redact:
            return "[REDACTED]"
        raise Phase5RuntimeV3ContractError(f"{label} contains sensitive data")
    return value


def _flag(raw: object) -> bool:
    return type(raw) is str and raw.strip().casefold() in {"1", "true"}


@dataclass(frozen=True, slots=True)
class RuntimeFlagsV3:
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
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> RuntimeFlagsV3:
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
class RuntimeBindingV3:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _safe_id(getattr(self, name), name))


def _binding(value: object) -> RuntimeBindingV3:
    if type(value) is not RuntimeBindingV3:
        raise Phase5RuntimeV3ContractError("binding must be exact RuntimeBindingV3")
    return RuntimeBindingV3(value.trace_id, value.session_id, value.workspace_id, value.account_id, value.profile_id)


def _flags(value: object) -> RuntimeFlagsV3:
    if type(value) is not RuntimeFlagsV3:
        raise Phase5RuntimeV3ContractError("flags must be exact RuntimeFlagsV3")
    return RuntimeFlagsV3(**dict(value.payload()))


@dataclass(frozen=True, slots=True)
class ActionRequestV3:
    invocation_ref: str
    binding: RuntimeBindingV3
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
        object.__setattr__(self, "binding", _binding(self.binding))
        for name in ("capability", "operation", "effect", "egress", "risk"):
            object.__setattr__(self, name, _text(getattr(self, name), name, 128, redact=False))
        for name in (
            "provider_free", "read_only", "metadata_allowlisted", "reversible",
            "uses_credentials", "privileged", "irreversible",
        ):
            _exact_bool(getattr(self, name), name)
        if type(self.cost_micro) is not int or not 0 <= self.cost_micro <= MAX_INTEGER:
            raise Phase5RuntimeV3ContractError("cost_micro is invalid")
        if self.risk not in _RISKS:
            raise Phase5RuntimeV3ContractError("risk is invalid")
        if type(self.action_classes) is not tuple or len(self.action_classes) > 32:
            raise Phase5RuntimeV3ContractError("action_classes is invalid")
        classes = tuple(_safe_id(item, "action_class").casefold() for item in self.action_classes)
        if len(classes) != len(set(classes)):
            raise Phase5RuntimeV3ContractError("action_classes contains duplicates")
        object.__setattr__(self, "action_classes", tuple(sorted(classes)))


def _action(value: object) -> ActionRequestV3:
    if type(value) is not ActionRequestV3:
        raise Phase5RuntimeV3ContractError("action must be exact ActionRequestV3")
    return ActionRequestV3(
        value.invocation_ref, value.binding, value.capability, value.operation,
        value.provider_free, value.read_only, value.effect, value.egress,
        value.metadata_allowlisted, value.cost_micro, value.risk, value.reversible,
        value.uses_credentials, value.privileged, value.irreversible, value.action_classes,
    )


@dataclass(frozen=True, slots=True)
class RuntimeDecisionV3:
    disposition: RuntimeDispositionV3
    reason: str
    trace_id: str
    epoch: int
    advisory_json: str = "{}"

    def __post_init__(self) -> None:
        if type(self.disposition) is not RuntimeDispositionV3:
            raise Phase5RuntimeV3ContractError("decision disposition is invalid")
        _text(self.reason, "reason", 128, redact=False)
        _safe_id(self.trace_id, "trace_id")
        if type(self.epoch) is not int or self.epoch < 1:
            raise Phase5RuntimeV3ContractError("decision epoch is invalid")
        if type(self.advisory_json) is not str or len(self.advisory_json.encode()) > MAX_EVENT_TEXT_BYTES:
            raise Phase5RuntimeV3ContractError("advisory_json is invalid")
        try:
            parsed = json.loads(self.advisory_json)
        except json.JSONDecodeError as exc:
            raise Phase5RuntimeV3ContractError("advisory_json is invalid") from exc
        if type(parsed) is not dict or set(parsed) - {"outcome", "reason", "grant_id", "scope_digest", "action_digest"}:
            raise Phase5RuntimeV3ContractError("advisory_json schema is invalid")


@dataclass(slots=True)
class _Budget:
    nodes: int = 0
    bytes: int = 0
    seen: set[int] | None = None

    def __post_init__(self) -> None:
        self.seen = set()

    def add(self, *, nodes: int = 1, bytes_: int = 0) -> None:
        self.nodes += nodes
        self.bytes += bytes_
        if self.nodes > MAX_JSON_NODES or self.bytes > MAX_JSON_BYTES:
            raise Phase5RuntimeV3ContractError("JSON budget exceeded")


def _json_value(value: object, *, depth: int = 0, budget: _Budget | None = None) -> object:
    """Bound and copy JSON incrementally; cycles and shared containers fail closed."""
    if budget is None:
        budget = _Budget()
    if depth > MAX_DEPTH:
        raise Phase5RuntimeV3ContractError("JSON nesting is too deep")
    budget.add()
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if not -MAX_INTEGER <= value <= MAX_INTEGER:
            raise Phase5RuntimeV3ContractError("JSON integer is out of bounds")
        budget.add(nodes=0, bytes_=len(str(value)))
        return value
    if type(value) is str:
        normalized = _text(value, "JSON text", MAX_TEXT)
        budget.add(nodes=0, bytes_=len(normalized.encode()))
        return normalized
    if type(value) in {list, tuple, dict, MappingProxyType}:
        identity = id(value)
        assert budget.seen is not None
        if identity in budget.seen:
            raise Phase5RuntimeV3ContractError("JSON contains a cycle or shared container")
        budget.seen.add(identity)
    if type(value) in {list, tuple}:
        if len(value) > MAX_FANOUT:
            raise Phase5RuntimeV3ContractError("JSON sequence fanout exceeded")
        return [_json_value(item, depth=depth + 1, budget=budget) for item in value]
    if type(value) is dict or type(value) is MappingProxyType:
        if len(value) > MAX_FANOUT:
            raise Phase5RuntimeV3ContractError("JSON object fanout exceeded")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key.encode()) > 128 or _SENSITIVE_KEY.search(key):
                raise Phase5RuntimeV3ContractError("JSON key is unsafe")
            budget.add(nodes=0, bytes_=len(key.encode()))
            result[key] = _json_value(item, depth=depth + 1, budget=budget)
        return result
    raise Phase5RuntimeV3ContractError("JSON contains a non-JSON value")


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProjectionBatchV3:
    items: tuple[Mapping[str, object], ...]
    replace: bool = True
    source_cursor: str | None = None
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.items) is not tuple or len(self.items) > MAX_PAGE_SIZE:
            raise Phase5RuntimeV3ContractError("projection batch is invalid")
        normalized: list[Mapping[str, object]] = []
        budget = _Budget()
        for item in self.items:
            if type(item) not in {dict, MappingProxyType}:
                raise Phase5RuntimeV3ContractError("projection items must be exact mappings")
            value = _json_value(item, budget=budget)
            assert type(value) is dict
            normalized.append(_freeze(value))  # type: ignore[arg-type]
        object.__setattr__(self, "items", tuple(normalized))
        _exact_bool(self.replace, "replace")
        object.__setattr__(self, "source_cursor", _optional_safe_id(self.source_cursor, "source_cursor"))
        object.__setattr__(self, "next_cursor", _optional_safe_id(self.next_cursor, "next_cursor"))
        if self.next_cursor is not None and self.next_cursor == self.source_cursor:
            raise Phase5RuntimeV3ContractError("projection cursor does not advance")


def _batch(value: object) -> ProjectionBatchV3:
    if type(value) is not ProjectionBatchV3:
        raise Phase5RuntimeV3ContractError("component returned the wrong batch type")
    budget = _Budget()
    return ProjectionBatchV3(
        tuple(dict(_json_value(item, budget=budget)) for item in value.items),
        replace=value.replace, source_cursor=value.source_cursor, next_cursor=value.next_cursor,
    )


class ApprovalInboxReaderV3(Protocol):
    def read_page(
        self, *, binding: RuntimeBindingV3, page_size: int, cursor: str | None,
    ) -> ProjectionBatchV3: ...


@dataclass(frozen=True, slots=True)
class RuntimeComponentsV3:
    grant_evaluator: Callable[[str], object] | None = None
    nexus_projector: Callable[[RuntimeBindingV3], ProjectionBatchV3] | None = None
    inbox_factory: Callable[[RuntimeBindingV3], ApprovalInboxReaderV3] | None = None
    grant_terminator: Callable[[str], None] | None = None
    nexus_terminator: Callable[[str], None] | None = None
    inbox_terminator: Callable[[str], None] | None = None
    rollback_callback: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise Phase5RuntimeV3ContractError(f"{name} must be callable")


def _components(value: object) -> RuntimeComponentsV3:
    if type(value) is not RuntimeComponentsV3:
        raise Phase5RuntimeV3ContractError("components must be exact RuntimeComponentsV3")
    return RuntimeComponentsV3(**{name: getattr(value, name) for name in value.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class ProjectionItemV3:
    item_id: str
    payload_json: str

    def payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        assert type(value) is dict
        return value


@dataclass(frozen=True, slots=True)
class ProjectionPageV3:
    kind: str
    offset: int
    page_size: int
    total: int
    items: tuple[ProjectionItemV3, ...]
    next_offset: int | None
    source_cursor: str | None
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class RuntimeEventV3:
    sequence: int
    kind: str
    outcome: str
    component: str | None = None
    count: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeStatusV3:
    state: RuntimeStateV3
    reason: str
    epoch: int
    binding: RuntimeBindingV3
    flags: tuple[tuple[str, bool], ...]
    capability_count: int
    inbox_count: int
    event_count: int
    component_failures: tuple[str, ...]
    termination_failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DecisionSealV3:
    decision: RuntimeDecisionV3
    public_digest: str
    request_digest: str
    binding_digest: str
    flags_digest: str
    epoch: int
    authority_digest: str


def _digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def _binding_digest(value: RuntimeBindingV3) -> str:
    return _digest([value.trace_id, value.session_id, value.workspace_id, value.account_id, value.profile_id])


def _flags_digest(value: RuntimeFlagsV3) -> str:
    return _digest(value.payload())


def _action_digest(value: ActionRequestV3) -> str:
    return _digest(
        {
            "invocation_ref": value.invocation_ref, "binding": _binding_digest(value.binding),
            "capability": value.capability, "operation": value.operation,
            "provider_free": value.provider_free, "read_only": value.read_only,
            "effect": value.effect, "egress": value.egress,
            "metadata_allowlisted": value.metadata_allowlisted, "cost_micro": value.cost_micro,
            "risk": value.risk, "reversible": value.reversible,
            "uses_credentials": value.uses_credentials, "privileged": value.privileged,
            "irreversible": value.irreversible, "action_classes": value.action_classes,
        }
    )


def _decision_digest(value: RuntimeDecisionV3) -> str:
    return _digest([value.disposition.value, value.reason, value.trace_id, value.epoch, value.advisory_json])


def _authority_digest(
    key: bytes, public: str, request: str, binding: str, flags: str, epoch: int,
) -> str:
    return hmac.new(key, "\0".join((public, request, binding, flags, str(epoch))).encode(), hashlib.sha256).hexdigest()


_CAPABILITY_FIELDS = frozenset(
    {"capability_id", "display_name", "provider", "version", "status", "operations", "limitation"}
)
_INBOX_FIELDS = frozenset(
    {"item_id", "request_ref", "capability", "operation", "risk", "state", "summary", "created_at"}
)


def _closed_capability(raw: Mapping[str, object], binding: RuntimeBindingV3) -> tuple[str, dict[str, object]]:
    if set(raw) != _CAPABILITY_FIELDS:
        raise Phase5RuntimeV3ContractError("capability schema fields are invalid")
    identifier = _safe_id(raw["capability_id"], "capability_id")
    operations = raw["operations"]
    if type(operations) not in {tuple, list} or not 1 <= len(operations) <= 16:
        raise Phase5RuntimeV3ContractError("capability operations are invalid")
    clean_operations = tuple(_safe_id(item, "operation") for item in operations)
    if len(clean_operations) != len(set(clean_operations)):
        raise Phase5RuntimeV3ContractError("capability operations contain duplicates")
    status = _text(raw["status"], "status", 32, redact=False)
    if status not in _CAPABILITY_STATUS:
        raise Phase5RuntimeV3ContractError("capability status is invalid")
    limitation = raw["limitation"]
    if limitation is not None:
        limitation = _text(limitation, "limitation", 512)
    payload: dict[str, object] = {
        "capability_id": identifier,
        "display_name": _text(raw["display_name"], "display_name", 128),
        "provider": _text(raw["provider"], "provider", 128),
        "version": _safe_id(raw["version"], "version"),
        "status": status,
        "operations": clean_operations,
        "limitation": limitation,
        "trace_id": binding.trace_id, "session_id": binding.session_id,
        "workspace_id": binding.workspace_id, "account_id": binding.account_id,
        "profile_id": binding.profile_id,
    }
    return identifier, payload


def _closed_inbox(raw: Mapping[str, object], binding: RuntimeBindingV3) -> tuple[str, dict[str, object]]:
    if set(raw) != _INBOX_FIELDS:
        raise Phase5RuntimeV3ContractError("inbox schema fields are invalid")
    identifier = _safe_id(raw["item_id"], "item_id")
    risk = _text(raw["risk"], "risk", 16, redact=False)
    state = _text(raw["state"], "state", 16, redact=False)
    if risk not in _RISKS or state not in _INBOX_STATE:
        raise Phase5RuntimeV3ContractError("inbox enum is invalid")
    created_at = _text(raw["created_at"], "created_at", 32, redact=False)
    if not _RFC3339_UTC.fullmatch(created_at):
        raise Phase5RuntimeV3ContractError("created_at is invalid")
    payload: dict[str, object] = {
        "item_id": identifier,
        "request_ref": _safe_id(raw["request_ref"], "request_ref"),
        "capability": _text(raw["capability"], "capability", 128),
        "operation": _text(raw["operation"], "operation", 128),
        "risk": risk, "state": state,
        "summary": _text(raw["summary"], "summary", 512),
        "created_at": created_at,
        "trace_id": binding.trace_id, "session_id": binding.session_id,
        "workspace_id": binding.workspace_id, "account_id": binding.account_id,
        "profile_id": binding.profile_id,
    }
    return identifier, payload


def _record(surface: str, raw: Mapping[str, object], binding: RuntimeBindingV3) -> ProjectionItemV3:
    identifier, payload = (
        _closed_capability(raw, binding) if surface == "capabilities" else _closed_inbox(raw, binding)
    )
    normalized = _json_value(payload)
    encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_PROJECTION_ROW_BYTES:
        raise Phase5RuntimeV3ContractError("projection row is too large")
    return ProjectionItemV3(identifier, encoded)


def _advisory(value: object) -> str:
    if value is None:
        raw: dict[str, object] = {"outcome": "none"}
    elif type(value) is dict:
        if set(value) - {"outcome", "reason", "grant_id", "scope_digest", "action_digest"}:
            raise Phase5RuntimeV3ContractError("grant advisory fields are invalid")
        raw = dict(value)
    else:
        raw = {}
        for name in ("outcome", "reason", "grant_id", "scope_digest", "action_digest"):
            item = getattr(value, name, None)
            if item is not None:
                if type(item) not in {str, int, bool}:
                    raise Phase5RuntimeV3ContractError("grant advisory field is invalid")
                raw[name] = item
        if not raw:
            raw = {"outcome": type(value).__name__}
    normalized = _json_value(raw)
    encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_EVENT_TEXT_BYTES:
        raise Phase5RuntimeV3ContractError("grant advisory is too large")
    return encoded


_T = TypeVar("_T")


class Phase5RuntimeV3:
    """Bounded event-driven host extension with no autonomous execution."""

    def __init__(
        self, *, binding: RuntimeBindingV3, flags: RuntimeFlagsV3 | None = None,
        components: RuntimeComponentsV3 | None = None,
    ) -> None:
        self._binding = _binding(binding)
        self._flags = _flags(flags or RuntimeFlagsV3.from_environ())
        self._components = _components(components or RuntimeComponentsV3())
        self._lock = threading.RLock()
        self._terminal_condition = threading.Condition(self._lock)
        self._config_generation = 1
        self._component_generation = {name: 0 for name in _COMPONENTS}
        self._authority_epoch = 1
        self._inbox_journey = 0
        self._terminated = False
        self._termination_running = False
        self._termination_complete = False
        self._termination_owner_thread: int | None = None
        self._terminal_reason: str | None = None
        self._component_failures: set[str] = set()
        self._termination_failures: set[str] = set()
        self._capabilities: OrderedDict[str, ProjectionItemV3] = OrderedDict()
        self._inbox: OrderedDict[str, ProjectionItemV3] = OrderedDict()
        self._capability_source_cursor: str | None = None
        self._capability_next_cursor: str | None = None
        self._inbox_source_cursor: str | None = None
        self._inbox_next_cursor: str | None = None
        self._inbox_started = False
        self._inbox_cursor_history: set[str] = set()
        self._events: deque[RuntimeEventV3] = deque(maxlen=MAX_EVENTS)
        self._event_sequence = 0
        self._decision_seals: OrderedDict[int, _DecisionSealV3] = OrderedDict()
        self._decision_key = secrets.token_bytes(32)

    @property
    def binding(self) -> RuntimeBindingV3:
        with self._lock:
            return _binding(self._binding)

    @property
    def flags(self) -> RuntimeFlagsV3:
        with self._lock:
            return _flags(self._flags)

    def _event_locked(
        self, kind: str, outcome: str, *, component: str | None = None,
        count: int | None = None, reason: str | None = None,
    ) -> None:
        kind = _safe_id(kind, "event kind")
        outcome = _safe_id(outcome, "event outcome")
        component = None if component is None else _safe_id(component, "event component")
        if count is not None and (type(count) is not int or not 0 <= count <= MAX_PROJECTION_ITEMS):
            raise Phase5RuntimeV3ContractError("event count is invalid")
        reason = None if reason is None else _text(reason, "event reason", MAX_EVENT_TEXT_BYTES)
        self._event_sequence += 1
        self._events.append(RuntimeEventV3(self._event_sequence, kind, outcome, component, count, reason))

    def _clear_projections_locked(self) -> None:
        self._capabilities.clear(); self._inbox.clear()
        self._capability_source_cursor = self._capability_next_cursor = None
        self._inbox_source_cursor = self._inbox_next_cursor = None
        self._inbox_started = False
        self._inbox_cursor_history.clear()
        self._inbox_journey += 1

    def _retire_locked(self, *, configuration: bool) -> None:
        if configuration:
            self._config_generation += 1
        self._authority_epoch += 1
        self._decision_seals.clear()
        self._clear_projections_locked()

    def rebind(self, binding: RuntimeBindingV3) -> RuntimeStatusV3:
        snapshot = _binding(binding)
        with self._lock:
            self._ensure_active_locked()
            self._binding = snapshot; self._component_failures.clear()
            self._retire_locked(configuration=True)
            self._event_locked("configuration", "binding_replaced")
            return self._status_locked()

    def configure_flags(self, flags: RuntimeFlagsV3) -> RuntimeStatusV3:
        snapshot = _flags(flags)
        with self._lock:
            self._ensure_active_locked()
            self._flags = snapshot; self._component_failures.clear()
            self._retire_locked(configuration=True)
            self._event_locked("configuration", "flags_replaced")
            return self._status_locked()

    def replace_components(self, components: RuntimeComponentsV3) -> RuntimeStatusV3:
        snapshot = _components(components)
        with self._lock:
            self._ensure_active_locked()
            self._components = snapshot; self._component_failures.clear()
            self._retire_locked(configuration=True)
            self._event_locked("configuration", "components_replaced")
            return self._status_locked()

    def _ensure_active_locked(self) -> None:
        if self._terminated:
            raise Phase5RuntimeV3Error("runtime is terminated")

    def _enabled_component_locked(self, name: str) -> bool:
        return {
            "grant_shadow": self._flags.grant_shadow,
            "nexus": self._flags.nexus_projection,
            "inbox": self._flags.approval_inbox,
        }[name]

    def _state_locked(self) -> RuntimeStateV3:
        if self._termination_running: return RuntimeStateV3.TERMINATING
        if self._termination_complete: return RuntimeStateV3.TERMINATED
        if not self._flags.runtime: return RuntimeStateV3.DISABLED
        if any(self._enabled_component_locked(name) for name in self._component_failures):
            return RuntimeStateV3.DEGRADED
        return RuntimeStateV3.READY

    def _status_locked(self) -> RuntimeStatusV3:
        state = self._state_locked()
        reason = self._terminal_reason if self._terminated else (
            "feature_flag_off" if state is RuntimeStateV3.DISABLED else
            "component_failure" if state is RuntimeStateV3.DEGRADED else "ready"
        )
        return RuntimeStatusV3(
            state, reason or "terminated", self._authority_epoch, _binding(self._binding),
            self._flags.payload(), len(self._capabilities), len(self._inbox), len(self._events),
            tuple(sorted(self._component_failures)), tuple(sorted(self._termination_failures)),
        )

    def status(self) -> RuntimeStatusV3:
        with self._lock: return self._status_locked()

    @staticmethod
    def _page_bounds(offset: int, page_size: int) -> tuple[int, int]:
        if type(offset) is not int or not 0 <= offset <= MAX_PROJECTION_ITEMS:
            raise Phase5RuntimeV3ContractError("offset is invalid")
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise Phase5RuntimeV3ContractError("page_size is invalid")
        return offset, page_size

    def events(self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE) -> tuple[RuntimeEventV3, ...]:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock: return tuple(self._events)[offset:offset + page_size]

    def _set_failure_locked(self, name: str, failed: bool) -> None:
        if name not in _COMPONENTS:
            raise Phase5RuntimeV3ContractError("component is invalid")
        changed = (failed and name not in self._component_failures) or (not failed and name in self._component_failures)
        if failed: self._component_failures.add(name)
        else: self._component_failures.discard(name)
        if changed:
            self._authority_epoch += 1
            self._decision_seals.clear()

    def _component_lease_locked(self, name: str) -> tuple[int, int]:
        self._component_generation[name] += 1
        return self._config_generation, self._component_generation[name]

    def _lease_current_locked(self, name: str, lease: tuple[int, int]) -> bool:
        return lease == (self._config_generation, self._component_generation[name])

    def _record_failure(self, name: str, lease: tuple[int, int], outcome: str = "failure") -> None:
        with self._lock:
            if not self._terminated and self._lease_current_locked(name, lease) and self._enabled_component_locked(name):
                self._set_failure_locked(name, True)
                self._event_locked("component", outcome, component=name)

    @staticmethod
    def _contains_explicit(action: ActionRequestV3) -> bool:
        if action.uses_credentials or action.privileged or action.irreversible or action.action_classes:
            return True
        words = set(re.findall(r"[a-z0-9]+", f"{action.capability} {action.operation}".casefold()))
        return bool(words & _EXPLICIT_WORDS)

    def _decision_locked(
        self, disposition: RuntimeDispositionV3, reason: str, advisory: str = "{}",
        *, request_digest: str | None = None, publish: bool = True,
    ) -> RuntimeDecisionV3:
        decision = RuntimeDecisionV3(disposition, reason, self._binding.trace_id, self._authority_epoch, advisory)
        if not publish: return decision
        self._event_locked("decision", disposition.value, reason=reason)
        if disposition is RuntimeDispositionV3.ALLOW_LOCAL_CATALOG_READ:
            if request_digest is None: raise Phase5RuntimeV3ContractError("allow decision lacks request digest")
            public = _decision_digest(decision); binding = _binding_digest(self._binding); flags = _flags_digest(self._flags)
            authority = _authority_digest(self._decision_key, public, request_digest, binding, flags, self._authority_epoch)
            self._decision_seals[id(decision)] = _DecisionSealV3(
                decision, public, request_digest, binding, flags, self._authority_epoch, authority,
            )
            while len(self._decision_seals) > MAX_DECISION_SEALS:
                self._decision_seals.popitem(last=False)
        return decision

    def evaluate(self, action: ActionRequestV3) -> RuntimeDecisionV3:
        with self._lock:
            if self._terminated: return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "runtime_terminated")
            if not self._flags.runtime:
                return self._decision_locked(RuntimeDispositionV3.FALLBACK, "feature_flag_off", publish=False)
            try: snapshot = _action(action)
            except (AttributeError, Phase5RuntimeV3ContractError):
                return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "invalid_action_contract")
            if self._contains_explicit(snapshot):
                return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "explicit_action_class")
            if not self._flags.low_risk or not self._flags.local_catalog_read:
                return self._decision_locked(RuntimeDispositionV3.FALLBACK, "extension_path_off", publish=False)
            if snapshot.binding != self._binding:
                return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "scope_mismatch")
            exact = (
                snapshot.capability == "local.catalog" and snapshot.operation == "catalog_read"
                and snapshot.provider_free and snapshot.read_only and snapshot.effect == "none"
                and snapshot.egress == "none" and snapshot.metadata_allowlisted and snapshot.cost_micro == 0
                and snapshot.risk == "low" and snapshot.reversible and not snapshot.uses_credentials
                and not snapshot.privileged and not snapshot.irreversible
            )
            if not exact:
                return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "not_exact_local_catalog_read")
            observer = self._components.grant_evaluator if self._flags.grant_shadow else None
            if self._flags.grant_shadow and observer is None:
                self._set_failure_locked("grant_shadow", True)
                return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "grant_shadow_unavailable")
            config_lease = self._config_generation
            component_lease = self._component_lease_locked("grant_shadow") if observer is not None else None

        advisory = "{}"
        if observer is not None:
            try: advisory = _advisory(observer(snapshot.invocation_ref))
            except BaseException:
                assert component_lease is not None
                self._record_failure("grant_shadow", component_lease)
                with self._lock: return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "grant_shadow_failure")

        with self._lock:
            if self._terminated or config_lease != self._config_generation:
                return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "authority_revoked_during_evaluation")
            if component_lease is not None:
                if not self._lease_current_locked("grant_shadow", component_lease):
                    return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "evaluation_superseded")
                self._set_failure_locked("grant_shadow", False)
            if any(self._enabled_component_locked(name) for name in self._component_failures):
                return self._decision_locked(RuntimeDispositionV3.EXPLICIT, "component_failure_during_evaluation")
            return self._decision_locked(
                RuntimeDispositionV3.ALLOW_LOCAL_CATALOG_READ, "exact_provider_free_catalog_read",
                advisory, request_digest=_action_digest(snapshot),
            )

    def legacy_or_decision(self, action: ActionRequestV3, legacy: Callable[[], _T]) -> _T | RuntimeDecisionV3:
        if not callable(legacy): raise Phase5RuntimeV3ContractError("legacy fallback must be callable")
        decision = self.evaluate(action)
        return legacy() if decision.disposition is RuntimeDispositionV3.FALLBACK else decision

    def _current_locked(self, decision: RuntimeDecisionV3, action: ActionRequestV3) -> bool:
        if type(decision) is not RuntimeDecisionV3 or type(action) is not ActionRequestV3: return False
        seal = self._decision_seals.get(id(decision))
        if seal is None or seal.decision is not decision: return False
        try:
            snapshot = _action(action); public = _decision_digest(decision); request = _action_digest(snapshot)
            binding = _binding_digest(self._binding); flags = _flags_digest(self._flags)
            authority = _authority_digest(self._decision_key, public, request, binding, flags, self._authority_epoch)
        except (AttributeError, TypeError, ValueError): return False
        return (
            decision.disposition is RuntimeDispositionV3.ALLOW_LOCAL_CATALOG_READ
            and not self._terminated and not any(self._enabled_component_locked(name) for name in self._component_failures)
            and snapshot.binding == self._binding and seal.epoch == self._authority_epoch
            and decision.epoch == self._authority_epoch and decision.trace_id == self._binding.trace_id
            and hmac.compare_digest(seal.public_digest, public)
            and hmac.compare_digest(seal.request_digest, request)
            and hmac.compare_digest(seal.binding_digest, binding)
            and hmac.compare_digest(seal.flags_digest, flags)
            and hmac.compare_digest(seal.authority_digest, authority)
        )

    def decision_is_current(self, decision: RuntimeDecisionV3, action: ActionRequestV3 | None = None) -> bool:
        """Deprecated one-argument use fails closed; request binding is mandatory."""
        if action is None: return False
        with self._lock: return self._current_locked(decision, action)

    def consume_decision(self, decision: RuntimeDecisionV3, action: ActionRequestV3) -> bool:
        """Atomically consume one exact issued allow for one exact request."""
        with self._lock:
            if not self._current_locked(decision, action): return False
            del self._decision_seals[id(decision)]
            self._event_locked("decision", "consumed", reason="exact_request_consumed")
            return True

    @staticmethod
    def _prepare(
        surface: str, batch: ProjectionBatchV3, binding: RuntimeBindingV3,
    ) -> tuple[ProjectionBatchV3, tuple[ProjectionItemV3, ...]]:
        snapshot = _batch(batch)
        records = tuple(_record(surface, item, binding) for item in snapshot.items)
        if len({record.item_id for record in records}) != len(records):
            raise Phase5RuntimeV3ContractError("projection page contains duplicate identifiers")
        return snapshot, records

    @staticmethod
    def _apply(
        target: OrderedDict[str, ProjectionItemV3], records: tuple[ProjectionItemV3, ...],
        *, replace: bool, forbid_existing: bool = False,
    ) -> None:
        if forbid_existing and any(record.item_id in target for record in records):
            raise Phase5RuntimeV3ContractError("projection repeats an earlier identifier")
        if replace: target.clear()
        for record in records:
            target.pop(record.item_id, None); target[record.item_id] = record
        while len(target) > MAX_PROJECTION_ITEMS: target.popitem(last=False)

    def refresh_capabilities(self) -> ProjectionPageV3:
        with self._lock:
            if self._terminated or not self._flags.runtime or not self._flags.nexus_projection:
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
            projector = self._components.nexus_projector; lease = self._component_lease_locked("nexus")
            binding = _binding(self._binding)
            if projector is None:
                self._set_failure_locked("nexus", True); self._event_locked("capabilities", "unavailable")
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
        try: snapshot, records = self._prepare("capabilities", projector(binding), binding)
        except BaseException:
            self._record_failure("nexus", lease)
            return self.capabilities()
        with self._lock:
            if self._terminated or not self._lease_current_locked("nexus", lease):
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
            self._apply(self._capabilities, records, replace=snapshot.replace)
            self._capability_source_cursor = snapshot.source_cursor; self._capability_next_cursor = snapshot.next_cursor
            self._set_failure_locked("nexus", False)
            self._event_locked("capabilities", "refreshed", count=len(records))
            return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)

    def refresh_inbox(self, *, cursor: str | None = None, page_size: int = MAX_PAGE_SIZE) -> ProjectionPageV3:
        _, page_size = self._page_bounds(0, page_size); cursor = _optional_safe_id(cursor, "cursor")
        with self._lock:
            if self._terminated or not self._flags.runtime or not self._flags.approval_inbox:
                return self._page_locked("inbox", 0, page_size)
            if cursor is None:
                self._inbox.clear(); self._inbox_cursor_history.clear(); self._inbox_started = False
                self._inbox_source_cursor = self._inbox_next_cursor = None; self._inbox_journey += 1
            elif not self._inbox_started or cursor != self._inbox_next_cursor:
                raise Phase5RuntimeV3ContractError("inbox cursor is not the expected continuation")
            if cursor is not None and len(self._inbox_cursor_history) >= MAX_CURSOR_HISTORY:
                self._set_failure_locked("inbox", True); self._event_locked("inbox", "cursor_limit")
                return self._page_locked("inbox", 0, page_size)
            factory = self._components.inbox_factory; lease = self._component_lease_locked("inbox")
            journey = self._inbox_journey; binding = _binding(self._binding)
            if factory is None:
                self._set_failure_locked("inbox", True); self._event_locked("inbox", "unavailable")
                return self._page_locked("inbox", 0, page_size)
        try:
            reader = factory(binding); read_page = getattr(reader, "read_page")
            if not callable(read_page): raise Phase5RuntimeV3ContractError("inbox reader has no read_page")
            snapshot, records = self._prepare(
                "inbox", read_page(binding=_binding(binding), page_size=page_size, cursor=cursor), binding,
            )
            if snapshot.source_cursor != cursor: raise Phase5RuntimeV3ContractError("inbox source cursor mismatch")
            if cursor is None and not snapshot.replace: raise Phase5RuntimeV3ContractError("first inbox page must replace")
            if cursor is not None and snapshot.replace: raise Phase5RuntimeV3ContractError("continuation cannot replace")
            if not records and snapshot.next_cursor is not None:
                raise Phase5RuntimeV3ContractError("empty inbox page cannot continue")
        except BaseException:
            self._record_failure("inbox", lease)
            return self.inbox(page_size=page_size)
        with self._lock:
            if self._terminated or not self._lease_current_locked("inbox", lease) or journey != self._inbox_journey:
                return self._page_locked("inbox", 0, page_size)
            if cursor is not None and cursor in self._inbox_cursor_history:
                self._set_failure_locked("inbox", True); return self._page_locked("inbox", 0, page_size)
            if snapshot.next_cursor is not None and snapshot.next_cursor in self._inbox_cursor_history:
                self._set_failure_locked("inbox", True); return self._page_locked("inbox", 0, page_size)
            try: self._apply(self._inbox, records, replace=snapshot.replace, forbid_existing=cursor is not None)
            except Phase5RuntimeV3ContractError:
                self._set_failure_locked("inbox", True); return self._page_locked("inbox", 0, page_size)
            if cursor is not None: self._inbox_cursor_history.add(cursor)
            self._inbox_started = True; self._inbox_source_cursor = snapshot.source_cursor
            self._inbox_next_cursor = snapshot.next_cursor; self._set_failure_locked("inbox", False)
            self._event_locked("inbox", "refreshed", count=len(records))
            return self._page_locked("inbox", 0, page_size)

    def _page_locked(self, kind: str, offset: int, page_size: int) -> ProjectionPageV3:
        if kind == "capabilities":
            target = self._capabilities; source = self._capability_source_cursor; next_cursor = self._capability_next_cursor
        else:
            target = self._inbox; source = self._inbox_source_cursor; next_cursor = self._inbox_next_cursor
        values = tuple(target.values()); items = tuple(values[offset:offset + page_size])
        next_offset = offset + len(items) if offset + len(items) < len(values) else None
        return ProjectionPageV3(kind, offset, page_size, len(values), items, next_offset, source, next_cursor)

    def capabilities(self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE) -> ProjectionPageV3:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock: return self._page_locked("capabilities", offset, page_size)

    def inbox(self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE) -> ProjectionPageV3:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock: return self._page_locked("inbox", offset, page_size)

    def dashboard_read(
        self, surface: str, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE,
    ) -> RuntimeStatusV3 | ProjectionPageV3 | tuple[RuntimeEventV3, ...]:
        if type(surface) is not str or surface not in {"status", "capabilities", "inbox", "events"}:
            raise Phase5RuntimeV3ContractError("dashboard surface is not allowlisted")
        with self._lock:
            if not self._flags.runtime or not self._flags.dashboard_projection:
                raise Phase5RuntimeV3Error("dashboard projection is disabled")
        if surface == "status": return self.status()
        if surface == "capabilities": return self.capabilities(offset=offset, page_size=page_size)
        if surface == "inbox": return self.inbox(offset=offset, page_size=page_size)
        return self.events(offset=offset, page_size=page_size)

    def terminate(self, reason: TerminalReasonV3) -> RuntimeStatusV3:
        if type(reason) is not TerminalReasonV3: raise Phase5RuntimeV3ContractError("terminal reason must be exact")
        with self._terminal_condition:
            if self._termination_complete: return self._status_locked()
            if self._termination_running:
                if self._termination_owner_thread == threading.get_ident():
                    raise Phase5RuntimeV3Error("reentrant termination is not allowed")
                while not self._termination_complete: self._terminal_condition.wait()
                return self._status_locked()
            self._termination_running = True; self._termination_owner_thread = threading.get_ident()
            self._terminated = True; self._terminal_reason = reason.value
            self._retire_locked(configuration=True); self._component_failures.clear()
            self._event_locked("lifecycle", "terminating", reason=reason.value)
            callbacks = (
                ("grant", self._components.grant_terminator), ("nexus", self._components.nexus_terminator),
                ("inbox", self._components.inbox_terminator), ("rollback", self._components.rollback_callback),
            )
        failures: list[str] = []
        for name, callback in callbacks:
            if callback is None: continue
            try: callback(reason.value)
            except BaseException: failures.append(name)
        with self._terminal_condition:
            self._termination_failures.update(failures); self._termination_running = False
            self._termination_owner_thread = None; self._termination_complete = True
            if failures: self._event_locked("lifecycle", "termination_callback_failure", reason=",".join(failures))
            self._event_locked("lifecycle", "terminated", reason=reason.value)
            result = self._status_locked(); self._terminal_condition.notify_all(); return result

    def kill(self) -> RuntimeStatusV3: return self.terminate(TerminalReasonV3.KILL)
    def revoke(self) -> RuntimeStatusV3: return self.terminate(TerminalReasonV3.REVOKE)
    def rollback(self) -> RuntimeStatusV3: return self.terminate(TerminalReasonV3.ROLLBACK)
    def end_session(self) -> RuntimeStatusV3: return self.terminate(TerminalReasonV3.END_SESSION)
    def reconnect(self) -> RuntimeStatusV3: return self.terminate(TerminalReasonV3.RECONNECT)
    def shutdown(self) -> RuntimeStatusV3: return self.terminate(TerminalReasonV3.SHUTDOWN)


__all__ = [
    "PHASE5_RUNTIME_FLAG", "PHASE5_GRANT_SHADOW_FLAG", "PHASE5_APPROVAL_INBOX_FLAG",
    "PHASE5_LOW_RISK_FLAG", "PHASE5_NEXUS_PROJECTION_FLAG", "PHASE5_LOCAL_CATALOG_READ_FLAG",
    "PHASE5_DASHBOARD_PROJECTION_FLAG", "MAX_PROJECTION_ITEMS", "MAX_PAGE_SIZE", "MAX_EVENTS",
    "MAX_DECISION_SEALS", "MAX_CURSOR_HISTORY", "MAX_JSON_BYTES", "MAX_JSON_NODES", "MAX_FANOUT",
    "ActionRequestV3", "ApprovalInboxReaderV3", "Phase5RuntimeV3", "Phase5RuntimeV3ContractError",
    "Phase5RuntimeV3Error", "ProjectionBatchV3", "ProjectionItemV3", "ProjectionPageV3",
    "RuntimeBindingV3", "RuntimeComponentsV3", "RuntimeDecisionV3", "RuntimeDispositionV3",
    "RuntimeEventV3", "RuntimeFlagsV3", "RuntimeStateV3", "RuntimeStatusV3", "TerminalReasonV3",
]
