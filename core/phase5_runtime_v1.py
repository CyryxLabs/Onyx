"""Host-owned Phase 5 integration core (isolated V1 candidate).

This module is intentionally not imported by startup, the permission broker,
the desktop UI, or the dashboard.  It is a small composition boundary for the
already-frozen Session Grants R11 and Capability Nexus V32 contracts plus an
Approval Inbox reader supplied by the host.  Dependencies are injected so an
unaccepted inbox candidate can never become a runtime dependency by import.

The core has no worker thread and no polling loop.  Projection refreshes are
explicit host events.  It never approves, grants, dispatches, executes, or
persists an action.  Its sole non-fallback decision is the exact, provider-free
``local.catalog/catalog_read`` read described by :class:`ActionRequestV1`.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar


PHASE5_RUNTIME_FLAG = "ONYX_PHASE5_RUNTIME_V1"
PHASE5_GRANT_SHADOW_FLAG = "ONYX_PHASE5_GRANT_SHADOW_V1"
PHASE5_APPROVAL_INBOX_FLAG = "ONYX_PHASE5_APPROVAL_INBOX_V1"
PHASE5_LOW_RISK_FLAG = "ONYX_PHASE5_LOW_RISK_V1"
PHASE5_NEXUS_PROJECTION_FLAG = "ONYX_PHASE5_NEXUS_PROJECTION_V1"
PHASE5_LOCAL_CATALOG_READ_FLAG = "ONYX_PHASE5_LOCAL_CATALOG_READ_V1"
PHASE5_DASHBOARD_PROJECTION_FLAG = "ONYX_PHASE5_DASHBOARD_PROJECTION_V1"

MAX_PROJECTION_ITEMS = 128
MAX_PAGE_SIZE = 50
MAX_EVENTS = 128
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


class Phase5RuntimeV1Error(RuntimeError):
    """Base error for the isolated runtime core."""


class Phase5RuntimeV1ContractError(ValueError):
    """A host-supplied value violated the bounded V1 contract."""


class RuntimeDispositionV1(str, Enum):
    FALLBACK = "FALLBACK"
    ALLOW_LOCAL_CATALOG_READ = "ALLOW_LOCAL_CATALOG_READ"
    EXPLICIT = "EXPLICIT"


class RuntimeStateV1(str, Enum):
    DISABLED = "DISABLED"
    READY = "READY"
    DEGRADED = "DEGRADED"
    TERMINATED = "TERMINATED"


class TerminalReasonV1(str, Enum):
    KILL = "kill"
    REVOKE = "revoke"
    ROLLBACK = "rollback"
    END_SESSION = "end_session"
    RECONNECT = "reconnect"
    SHUTDOWN = "shutdown"


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise Phase5RuntimeV1ContractError(f"{label} must be an exact boolean")
    return value


def _safe_id(value: object, label: str) -> str:
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        raise Phase5RuntimeV1ContractError(f"{label} is invalid")
    return value


def _bounded_text(value: object, label: str, maximum: int = MAX_TEXT) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise Phase5RuntimeV1ContractError(f"{label} is invalid")
    return value


def _flag(raw: object) -> bool:
    return type(raw) is str and raw.strip().casefold() in {"1", "true"}


@dataclass(frozen=True, slots=True)
class RuntimeFlagsV1:
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
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> RuntimeFlagsV1:
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
class RuntimeBindingV1:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _safe_id(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class ActionRequestV1:
    invocation_ref: str
    binding: RuntimeBindingV1
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
        if type(self.binding) is not RuntimeBindingV1:
            raise Phase5RuntimeV1ContractError("binding must be exact RuntimeBindingV1")
        for name in ("capability", "operation", "effect", "egress", "risk"):
            object.__setattr__(self, name, _bounded_text(getattr(self, name), name, 128))
        for name in (
            "provider_free", "read_only", "metadata_allowlisted", "reversible",
            "uses_credentials", "privileged", "irreversible",
        ):
            _exact_bool(getattr(self, name), name)
        if type(self.cost_micro) is not int or not 0 <= self.cost_micro <= MAX_INTEGER:
            raise Phase5RuntimeV1ContractError("cost_micro is invalid")
        if self.risk not in _RISKS:
            raise Phase5RuntimeV1ContractError("risk is invalid")
        if type(self.action_classes) is not tuple or len(self.action_classes) > 32:
            raise Phase5RuntimeV1ContractError("action_classes is invalid")
        classes = tuple(_safe_id(item, "action_class").casefold() for item in self.action_classes)
        if len(set(classes)) != len(classes):
            raise Phase5RuntimeV1ContractError("action_classes contains duplicates")
        object.__setattr__(self, "action_classes", tuple(sorted(classes)))


@dataclass(frozen=True, slots=True)
class RuntimeDecisionV1:
    disposition: RuntimeDispositionV1
    reason: str
    trace_id: str
    epoch: int
    advisory_json: str = "{}"

    def __post_init__(self) -> None:
        if type(self.disposition) is not RuntimeDispositionV1:
            raise Phase5RuntimeV1ContractError("decision disposition is invalid")
        _bounded_text(self.reason, "reason", 128)
        _safe_id(self.trace_id, "trace_id")
        if type(self.epoch) is not int or self.epoch < 1:
            raise Phase5RuntimeV1ContractError("decision epoch is invalid")
        if type(self.advisory_json) is not str or len(self.advisory_json.encode()) > MAX_EVENT_DETAIL_BYTES:
            raise Phase5RuntimeV1ContractError("advisory_json is invalid")
        try:
            parsed = json.loads(self.advisory_json)
        except json.JSONDecodeError as exc:
            raise Phase5RuntimeV1ContractError("advisory_json is invalid") from exc
        if type(parsed) is not dict:
            raise Phase5RuntimeV1ContractError("advisory_json must be an object")


@dataclass(frozen=True, slots=True)
class ProjectionBatchV1:
    """One host-triggered projection page; a page can never exceed 50 rows."""

    items: tuple[dict[str, object], ...]
    replace: bool = True
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.items) is not tuple or len(self.items) > MAX_PAGE_SIZE:
            raise Phase5RuntimeV1ContractError("projection batch is invalid")
        if any(type(item) is not dict for item in self.items):
            raise Phase5RuntimeV1ContractError("projection items must be exact dictionaries")
        _exact_bool(self.replace, "replace")
        if self.next_cursor is not None:
            _safe_id(self.next_cursor, "next_cursor")


class ApprovalInboxReaderV1(Protocol):
    def read_page(
        self,
        *,
        binding: RuntimeBindingV1,
        page_size: int,
        cursor: str | None,
    ) -> ProjectionBatchV1: ...


@dataclass(frozen=True, slots=True)
class RuntimeComponentsV1:
    """Adapters supplied by the host; concrete versioned modules stay outside."""

    grant_evaluator: Callable[[str], object] | None = None
    nexus_projector: Callable[[RuntimeBindingV1], ProjectionBatchV1] | None = None
    inbox_factory: Callable[[RuntimeBindingV1], ApprovalInboxReaderV1] | None = None
    grant_terminator: Callable[[str], None] | None = None
    nexus_terminator: Callable[[str], None] | None = None
    inbox_terminator: Callable[[str], None] | None = None
    rollback_callback: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise Phase5RuntimeV1ContractError(f"{name} must be callable")


@dataclass(frozen=True, slots=True)
class ProjectionItemV1:
    item_id: str
    payload_json: str

    def payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        assert type(value) is dict
        return value


@dataclass(frozen=True, slots=True)
class ProjectionPageV1:
    kind: str
    offset: int
    page_size: int
    total: int
    items: tuple[ProjectionItemV1, ...]
    next_offset: int | None


@dataclass(frozen=True, slots=True)
class RuntimeEventV1:
    sequence: int
    kind: str
    outcome: str
    detail_json: str

    def detail(self) -> dict[str, object]:
        value = json.loads(self.detail_json)
        assert type(value) is dict
        return value


@dataclass(frozen=True, slots=True)
class RuntimeStatusV1:
    state: RuntimeStateV1
    reason: str
    epoch: int
    binding: RuntimeBindingV1
    flags: tuple[tuple[str, bool], ...]
    capability_count: int
    inbox_count: int
    event_count: int
    component_failures: tuple[str, ...]
    termination_failures: tuple[str, ...]


class NexusProjectorV1(Protocol):
    def __call__(self, binding: RuntimeBindingV1) -> ProjectionBatchV1: ...


def _json_value(value: object, *, depth: int = 0) -> object:
    if depth > MAX_DEPTH:
        raise Phase5RuntimeV1ContractError("projection nesting is too deep")
    if value is None or type(value) in {bool, int}:
        if type(value) is int and not -MAX_INTEGER <= value <= MAX_INTEGER:
            raise Phase5RuntimeV1ContractError("projection integer is out of bounds")
        return value
    if type(value) is str:
        if len(value) > MAX_TEXT or any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise Phase5RuntimeV1ContractError("projection text is invalid")
        return value
    if type(value) in {list, tuple}:
        if len(value) > 64:
            raise Phase5RuntimeV1ContractError("projection sequence is too large")
        return [_json_value(item, depth=depth + 1) for item in value]
    if type(value) is dict:
        if len(value) > 64:
            raise Phase5RuntimeV1ContractError("projection object is too large")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 128 or _SENSITIVE_KEY.search(key):
                raise Phase5RuntimeV1ContractError("projection key is unsafe")
            result[key] = _json_value(item, depth=depth + 1)
        return result
    raise Phase5RuntimeV1ContractError("projection contains a non-JSON value")


def _projection_record(raw: dict[str, object], *, identifier_key: str) -> ProjectionItemV1:
    normalized = _json_value(raw)
    assert type(normalized) is dict
    identifier = _safe_id(normalized.get(identifier_key), identifier_key)
    encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_PROJECTION_ROW_BYTES:
        raise Phase5RuntimeV1ContractError("projection row is too large")
    return ProjectionItemV1(identifier, encoded)


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
        raise Phase5RuntimeV1ContractError("grant advisory is too large")
    return encoded


_T = TypeVar("_T")


class Phase5RuntimeV1:
    """Bounded, event-driven host policy extension with one terminal boundary."""

    def __init__(
        self,
        *,
        binding: RuntimeBindingV1,
        flags: RuntimeFlagsV1 | None = None,
        components: RuntimeComponentsV1 | None = None,
    ) -> None:
        if type(binding) is not RuntimeBindingV1:
            raise Phase5RuntimeV1ContractError("binding must be exact RuntimeBindingV1")
        if flags is None:
            flags = RuntimeFlagsV1.from_environ()
        if components is None:
            components = RuntimeComponentsV1()
        if type(flags) is not RuntimeFlagsV1 or type(components) is not RuntimeComponentsV1:
            raise Phase5RuntimeV1ContractError("flags and components must be exact V1 values")
        self._binding = binding
        self._flags = flags
        self._components = components
        self._lock = threading.RLock()
        self._epoch = 1
        self._terminated = False
        self._terminal_reason: str | None = None
        self._component_failures: set[str] = set()
        self._termination_failures: set[str] = set()
        self._capabilities: OrderedDict[str, ProjectionItemV1] = OrderedDict()
        self._inbox: OrderedDict[str, ProjectionItemV1] = OrderedDict()
        self._events: deque[RuntimeEventV1] = deque(maxlen=MAX_EVENTS)
        self._event_sequence = 0
        with self._lock:
            self._event_locked("runtime", "bound", {"enabled": flags.runtime})

    @property
    def binding(self) -> RuntimeBindingV1:
        return self._binding

    @property
    def flags(self) -> RuntimeFlagsV1:
        return self._flags

    def _state_locked(self) -> RuntimeStateV1:
        if self._terminated:
            return RuntimeStateV1.TERMINATED
        if not self._flags.runtime:
            return RuntimeStateV1.DISABLED
        if self._component_failures:
            return RuntimeStateV1.DEGRADED
        return RuntimeStateV1.READY

    def _reason_locked(self) -> str:
        if self._terminated:
            return self._terminal_reason or "terminated"
        if not self._flags.runtime:
            return "feature_flag_off"
        if self._component_failures:
            return "component_failure"
        return "ready"

    def status(self) -> RuntimeStatusV1:
        with self._lock:
            return RuntimeStatusV1(
                self._state_locked(), self._reason_locked(), self._epoch, self._binding,
                self._flags.payload(), len(self._capabilities), len(self._inbox), len(self._events),
                tuple(sorted(self._component_failures)), tuple(sorted(self._termination_failures)),
            )

    def _event_locked(self, kind: str, outcome: str, detail: Mapping[str, object]) -> None:
        normalized = _json_value(dict(detail))
        encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > MAX_EVENT_DETAIL_BYTES:
            raise Phase5RuntimeV1ContractError("event detail is too large")
        self._event_sequence += 1
        self._events.append(RuntimeEventV1(self._event_sequence, kind, outcome, encoded))

    def events(self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE) -> tuple[RuntimeEventV1, ...]:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return tuple(self._events)[offset : offset + page_size]

    @staticmethod
    def _page_bounds(offset: int, page_size: int) -> tuple[int, int]:
        if type(offset) is not int or not 0 <= offset <= MAX_PROJECTION_ITEMS:
            raise Phase5RuntimeV1ContractError("offset is invalid")
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise Phase5RuntimeV1ContractError("page_size is invalid")
        return offset, page_size

    def _decision_locked(
        self,
        disposition: RuntimeDispositionV1,
        reason: str,
        advisory_json: str = "{}",
    ) -> RuntimeDecisionV1:
        decision = RuntimeDecisionV1(disposition, reason, self._binding.trace_id, self._epoch, advisory_json)
        self._event_locked("decision", disposition.value, {"reason": reason})
        return decision

    def _set_component_failure_locked(self, name: str, failed: bool) -> None:
        """Change component health and retire every decision from the old state."""

        changed = False
        if failed and name not in self._component_failures:
            self._component_failures.add(name)
            changed = True
        elif not failed and name in self._component_failures:
            self._component_failures.remove(name)
            changed = True
        if changed:
            self._epoch += 1

    @staticmethod
    def _contains_explicit_intent(action: ActionRequestV1) -> bool:
        if action.uses_credentials or action.privileged or action.irreversible or action.action_classes:
            return True
        words = set(re.findall(r"[a-z0-9]+", f"{action.capability} {action.operation}".casefold()))
        return bool(words & _EXPLICIT_WORDS)

    def evaluate(self, action: ActionRequestV1) -> RuntimeDecisionV1:
        with self._lock:
            if self._terminated:
                return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "runtime_terminated")
            # A disabled extension is observationally transparent, including
            # for values the extension itself would reject as malformed.
            if not self._flags.runtime:
                return self._decision_locked(RuntimeDispositionV1.FALLBACK, "feature_flag_off")
            if type(action) is not ActionRequestV1:
                return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "invalid_action_contract")
            if self._contains_explicit_intent(action):
                return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "explicit_action_class")
            if not self._flags.low_risk or not self._flags.local_catalog_read:
                return self._decision_locked(RuntimeDispositionV1.FALLBACK, "extension_path_off")
            if action.binding != self._binding:
                return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "scope_mismatch")
            if self._component_failures:
                return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "component_failure")
            exact_catalog_read = (
                action.capability == "local.catalog"
                and action.operation == "catalog_read"
                and action.provider_free
                and action.read_only
                and action.effect == "none"
                and action.egress == "none"
                and action.metadata_allowlisted
                and action.cost_micro == 0
                and action.risk == "low"
                and action.reversible
                and not action.uses_credentials
                and not action.privileged
                and not action.irreversible
            )
            if not exact_catalog_read:
                return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "not_exact_local_catalog_read")
            lease = self._epoch
            observer = self._components.grant_evaluator if self._flags.grant_shadow else None
            if self._flags.grant_shadow and observer is None:
                self._set_component_failure_locked("grant_shadow", True)
                return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "grant_shadow_unavailable")

        advisory_json = "{}"
        if observer is not None:
            try:
                advisory_json = _advisory(observer(action.invocation_ref))
            except BaseException:
                with self._lock:
                    if self._terminated or self._epoch != lease:
                        return self._decision_locked(
                            RuntimeDispositionV1.EXPLICIT, "authority_revoked_during_evaluation"
                        )
                    self._set_component_failure_locked("grant_shadow", True)
                    return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "grant_shadow_failure")

        with self._lock:
            if self._terminated or self._epoch != lease:
                return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "authority_revoked_during_evaluation")
            if self._component_failures:
                return self._decision_locked(RuntimeDispositionV1.EXPLICIT, "component_failure_during_evaluation")
            return self._decision_locked(
                RuntimeDispositionV1.ALLOW_LOCAL_CATALOG_READ,
                "exact_provider_free_catalog_read",
                advisory_json,
            )

    def legacy_or_decision(self, action: ActionRequestV1, legacy: Callable[[], _T]) -> _T | RuntimeDecisionV1:
        if not callable(legacy):
            raise Phase5RuntimeV1ContractError("legacy fallback must be callable")
        decision = self.evaluate(action)
        if decision.disposition is RuntimeDispositionV1.FALLBACK:
            return legacy()
        return decision

    def decision_is_current(self, decision: RuntimeDecisionV1) -> bool:
        if type(decision) is not RuntimeDecisionV1:
            return False
        with self._lock:
            return (
                decision.disposition is RuntimeDispositionV1.ALLOW_LOCAL_CATALOG_READ
                and not self._terminated
                and not self._component_failures
                and decision.trace_id == self._binding.trace_id
                and decision.epoch == self._epoch
            )

    def _component_failed(self, name: str, lease: int) -> None:
        with self._lock:
            if not self._terminated and lease == self._epoch:
                self._set_component_failure_locked(name, True)
                self._event_locked("component", "failure", {"component": name})

    def _apply_batch_locked(
        self,
        target: OrderedDict[str, ProjectionItemV1],
        batch: ProjectionBatchV1,
        *,
        identifier_key: str,
    ) -> None:
        if type(batch) is not ProjectionBatchV1:
            raise Phase5RuntimeV1ContractError("component returned the wrong batch type")
        records = tuple(_projection_record(item, identifier_key=identifier_key) for item in batch.items)
        if len({item.item_id for item in records}) != len(records):
            raise Phase5RuntimeV1ContractError("projection page contains duplicate identifiers")
        if batch.replace:
            target.clear()
        for record in records:
            target.pop(record.item_id, None)
            target[record.item_id] = record
        while len(target) > MAX_PROJECTION_ITEMS:
            target.popitem(last=False)

    def refresh_capabilities(self) -> ProjectionPageV1:
        with self._lock:
            if self._terminated:
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
            if not self._flags.runtime or not self._flags.nexus_projection:
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
            projector = self._components.nexus_projector
            lease = self._epoch
            if projector is None:
                self._set_component_failure_locked("nexus", True)
                self._event_locked("capabilities", "unavailable", {})
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
        try:
            batch = projector(self._binding)
        except BaseException:
            self._component_failed("nexus", lease)
            return self.capabilities()
        try:
            with self._lock:
                if self._terminated or self._epoch != lease:
                    return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
                self._apply_batch_locked(self._capabilities, batch, identifier_key="capability_id")
                self._set_component_failure_locked("nexus", False)
                self._event_locked("capabilities", "refreshed", {"count": len(batch.items)})
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
        except Phase5RuntimeV1ContractError:
            self._component_failed("nexus", lease)
            return self.capabilities()

    def refresh_inbox(self, *, cursor: str | None = None, page_size: int = MAX_PAGE_SIZE) -> ProjectionPageV1:
        _, page_size = self._page_bounds(0, page_size)
        if cursor is not None:
            _safe_id(cursor, "cursor")
        with self._lock:
            if self._terminated:
                return self._page_locked("inbox", 0, page_size)
            if not self._flags.runtime or not self._flags.approval_inbox:
                return self._page_locked("inbox", 0, page_size)
            factory = self._components.inbox_factory
            lease = self._epoch
            if factory is None:
                self._set_component_failure_locked("inbox", True)
                self._event_locked("inbox", "unavailable", {})
                return self._page_locked("inbox", 0, page_size)
        try:
            reader = factory(self._binding)
            read_page = getattr(reader, "read_page")
            if not callable(read_page):
                raise Phase5RuntimeV1ContractError("inbox reader has no read_page")
            batch = read_page(binding=self._binding, page_size=page_size, cursor=cursor)
        except BaseException:
            self._component_failed("inbox", lease)
            return self.inbox(page_size=page_size)
        try:
            with self._lock:
                if self._terminated or self._epoch != lease:
                    return self._page_locked("inbox", 0, page_size)
                self._apply_batch_locked(self._inbox, batch, identifier_key="item_id")
                self._set_component_failure_locked("inbox", False)
                self._event_locked("inbox", "refreshed", {"count": len(batch.items)})
                return self._page_locked("inbox", 0, page_size)
        except Phase5RuntimeV1ContractError:
            self._component_failed("inbox", lease)
            return self.inbox(page_size=page_size)

    def _page_locked(self, kind: str, offset: int, page_size: int) -> ProjectionPageV1:
        target = self._capabilities if kind == "capabilities" else self._inbox
        values = tuple(target.values())
        items = values[offset : offset + page_size]
        next_offset = offset + len(items) if offset + len(items) < len(values) else None
        return ProjectionPageV1(kind, offset, page_size, len(values), items, next_offset)

    def capabilities(self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE) -> ProjectionPageV1:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return self._page_locked("capabilities", offset, page_size)

    def inbox(self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE) -> ProjectionPageV1:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return self._page_locked("inbox", offset, page_size)

    def dashboard_read(
        self,
        surface: str,
        *,
        offset: int = 0,
        page_size: int = MAX_PAGE_SIZE,
    ) -> RuntimeStatusV1 | ProjectionPageV1 | tuple[RuntimeEventV1, ...]:
        if surface not in {"status", "capabilities", "inbox", "events"}:
            raise Phase5RuntimeV1ContractError("dashboard surface is not read-only allowlisted")
        with self._lock:
            if not self._flags.runtime or not self._flags.dashboard_projection:
                raise Phase5RuntimeV1Error("dashboard projection is disabled")
        if surface == "status":
            return self.status()
        if surface == "capabilities":
            return self.capabilities(offset=offset, page_size=page_size)
        if surface == "inbox":
            return self.inbox(offset=offset, page_size=page_size)
        return self.events(offset=offset, page_size=page_size)

    def terminate(self, reason: TerminalReasonV1) -> RuntimeStatusV1:
        """The sole kill/revoke/rollback/session terminal boundary.

        State is made terminal and projections are cleared before any injected
        callback runs.  Therefore a failing or blocked dependency cannot retain
        authority, and concurrent evaluations fail their epoch check.
        """

        if type(reason) is not TerminalReasonV1:
            raise Phase5RuntimeV1ContractError("terminal reason must be exact")
        with self._lock:
            if self._terminated:
                return self.status()
            self._terminated = True
            self._terminal_reason = reason.value
            self._epoch += 1
            self._capabilities.clear()
            self._inbox.clear()
            self._component_failures.clear()
            self._event_locked("lifecycle", "terminated", {"reason": reason.value})
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
        with self._lock:
            self._termination_failures.update(failures)
            if failures:
                self._event_locked("lifecycle", "termination_callback_failure", {"components": failures})
            return self.status()

    def kill(self) -> RuntimeStatusV1:
        return self.terminate(TerminalReasonV1.KILL)

    def revoke(self) -> RuntimeStatusV1:
        return self.terminate(TerminalReasonV1.REVOKE)

    def rollback(self) -> RuntimeStatusV1:
        return self.terminate(TerminalReasonV1.ROLLBACK)

    def end_session(self) -> RuntimeStatusV1:
        return self.terminate(TerminalReasonV1.END_SESSION)

    def reconnect(self) -> RuntimeStatusV1:
        return self.terminate(TerminalReasonV1.RECONNECT)

    def shutdown(self) -> RuntimeStatusV1:
        return self.terminate(TerminalReasonV1.SHUTDOWN)


__all__ = [
    "PHASE5_RUNTIME_FLAG", "PHASE5_GRANT_SHADOW_FLAG", "PHASE5_APPROVAL_INBOX_FLAG",
    "PHASE5_LOW_RISK_FLAG", "PHASE5_NEXUS_PROJECTION_FLAG", "PHASE5_LOCAL_CATALOG_READ_FLAG",
    "PHASE5_DASHBOARD_PROJECTION_FLAG", "MAX_PROJECTION_ITEMS", "MAX_PAGE_SIZE", "MAX_EVENTS",
    "ActionRequestV1", "ApprovalInboxReaderV1", "NexusProjectorV1", "Phase5RuntimeV1",
    "Phase5RuntimeV1ContractError", "Phase5RuntimeV1Error", "ProjectionBatchV1",
    "ProjectionItemV1", "ProjectionPageV1", "RuntimeBindingV1", "RuntimeComponentsV1",
    "RuntimeDecisionV1", "RuntimeDispositionV1", "RuntimeEventV1", "RuntimeFlagsV1",
    "RuntimeStateV1", "RuntimeStatusV1", "TerminalReasonV1",
]
