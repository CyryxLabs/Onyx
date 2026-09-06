"""Host-owned Phase 5 integration core (isolated V6 candidate).

This module is deliberately not imported by a live/startup surface.  V6 keeps
the V1--V5 authority envelope while adding context-aware DLP, per-component
causal operation ordering and truthful cooperative termination.  Normal
operation has no worker, timer, polling loop, provider or side effect.  A
process-global, strictly bounded two-worker supervisor is created lazily only
when termination callbacks are submitted.  Python cannot forcibly cancel an
arbitrary local callback; authority is therefore revoked immediately and the
runtime remains ``TERMINATION_PENDING`` until every submitted callback really
returns.  Callers may wait explicitly with :meth:`await_termination`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import queue
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Protocol, TypeVar


PHASE5_RUNTIME_FLAG = "ONYX_PHASE5_RUNTIME_V6"
PHASE5_GRANT_SHADOW_FLAG = "ONYX_PHASE5_GRANT_SHADOW_V6"
PHASE5_APPROVAL_INBOX_FLAG = "ONYX_PHASE5_APPROVAL_INBOX_V6"
PHASE5_LOW_RISK_FLAG = "ONYX_PHASE5_LOW_RISK_V6"
PHASE5_NEXUS_PROJECTION_FLAG = "ONYX_PHASE5_NEXUS_PROJECTION_V6"
PHASE5_LOCAL_CATALOG_READ_FLAG = "ONYX_PHASE5_LOCAL_CATALOG_READ_V6"
PHASE5_DASHBOARD_PROJECTION_FLAG = "ONYX_PHASE5_DASHBOARD_PROJECTION_V6"

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
MAX_TERMINATION_WORKERS = 2
MAX_TERMINATION_QUEUE = 128

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_RFC3339_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|authorization|auth[_-]?code|cookie|credential|"
    r"password|passport|private[_-]?key|secret|session[_-]?cookie|token)(?:$|[_-])",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:"
    r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}\b|"
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----|"
    r"(?:api[_-]?key|authorization|auth[_-]?code|cookie|password|private[_-]?key|"
    r"client[_-]?secret|access[_-]?token|refresh[_-]?token|secret|token)\s*[:=]\s*[\"']?\S{8,}|"
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b|"
    r"\bgh[pousr]_[A-Za-z0-9]{16,}\b|"
    r"\bgithub_pat_[A-Za-z0-9_]{16,}\b|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"\bAIza[0-9A-Za-z_-]{24,}\b|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b|"
    r"\b(?:\d[ -]*?){13,19}\b"
    r")",
    re.IGNORECASE,
)
_SECRET_LABEL = (
    r"(?:authorization|auth[\s_-]*code|cookie|passport|private[\s_-]*key|"
    r"session[\s_-]*cookie|access(?:[\s_-]*(?:token|key))?|"
    r"refresh(?:[\s_-]*token)?|password|pass[\s_-]*phrase|"
    r"api[\s_-]*key|client[\s_-]*secret|credential|secret[\s_-]*key|token)"
)
_NATURAL_LANGUAGE_SECRET = re.compile(
    r"(?:^|[^A-Za-z0-9])"
    + _SECRET_LABEL
    + r"(?:\s+(?:is|was)\s+|\s*[:=]\s*|[\s_-]+|\s*[\"'])"
    r"[\"']?[A-Za-z0-9!@#$%^&*()_+./=~-]{2,}[\"']?",
    re.IGNORECASE,
)
_HEX_SECRET = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")
_BASE32_SECRET = re.compile(r"(?<![A-Za-z2-7])[A-Za-z2-7]{32,}={0,6}(?![A-Za-z2-7=])")
_JWT_SECRET = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
_ENTROPY_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{24,}(?![A-Za-z0-9_+/=-])"
)
_EXPLICIT_WORDS = frozenset(
    {
        "ad",
        "ads",
        "advertise",
        "approve",
        "buy",
        "charge",
        "credential",
        "credentials",
        "crisis",
        "delete",
        "deploy",
        "email",
        "grant",
        "install",
        "invoice",
        "legal",
        "message",
        "money",
        "oauth",
        "pay",
        "payment",
        "political",
        "privileged",
        "publish",
        "purchase",
        "refund",
        "role",
        "roles",
        "send",
        "transfer",
    }
)
_RISKS = frozenset({"low", "medium", "high", "critical"})
_CAPABILITY_STATUS = frozenset({"available", "degraded", "blocked", "disabled"})
_INBOX_STATE = frozenset({"pending", "approved", "denied", "expired", "revoked"})
_COMPONENTS = frozenset({"grant_shadow", "nexus", "inbox"})


class Phase5RuntimeV6Error(RuntimeError):
    """Base error for the isolated V6 runtime core."""


class Phase5RuntimeV6ContractError(ValueError):
    """A value violated the closed and bounded V6 host contract."""


class RuntimeDispositionV6(str, Enum):
    FALLBACK = "FALLBACK"
    ALLOW_LOCAL_CATALOG_READ = "ALLOW_LOCAL_CATALOG_READ"
    EXPLICIT = "EXPLICIT"


class RuntimeStateV6(str, Enum):
    DISABLED = "DISABLED"
    READY = "READY"
    DEGRADED = "DEGRADED"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    # Compatibility spelling for callers compiled against the V5 vocabulary.
    TERMINATING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"


class TerminalReasonV6(str, Enum):
    KILL = "kill"
    REVOKE = "revoke"
    ROLLBACK = "rollback"
    END_SESSION = "end_session"
    RECONNECT = "reconnect"
    SHUTDOWN = "shutdown"


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise Phase5RuntimeV6ContractError(f"{label} must be an exact boolean")
    return value


def _safe_id(value: object, label: str) -> str:
    """Validate an identifier by grammar, never by content-token heuristics.

    Trace/workspace/session identifiers commonly are UUIDs, ULIDs or hashes.
    Treating those fields as prose caused V5 to reject legitimate lowercase or
    uppercase identifiers.  Closed schemas decide which fields are identifiers;
    only prose/content fields pass through the DLP scanner below.
    """
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        raise Phase5RuntimeV6ContractError(f"{label} is invalid")
    # Exact credential labelling is semantic, not an entropy/content guess.
    # Reject it even in an identifier slot while accepting UUID/ULID/hash IDs.
    if _SENSITIVE_VALUE.search(value) or _NATURAL_LANGUAGE_SECRET.search(value):
        raise Phase5RuntimeV6ContractError(f"{label} contains sensitive data")
    return value


def _optional_safe_id(value: object, label: str) -> str | None:
    return None if value is None else _safe_id(value, label)


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    length = len(value)
    return -sum(
        (value.count(char) / length) * math.log2(value.count(char) / length)
        for char in set(value)
    )


def _contains_sensitive_value(value: str) -> bool:
    """Central value DLP used by every admitted string surface.

    Besides known credential families, reject bounded high-entropy tokens.  The
    entropy branch deliberately requires a long, space-free token containing
    letters and digits plus at least one delimiter/case transition so ordinary
    prose, timestamps and short product identifiers remain usable.
    """
    if (
        _SENSITIVE_VALUE.search(value)
        or _NATURAL_LANGUAGE_SECRET.search(value)
        or _JWT_SECRET.search(value)
        or _HEX_SECRET.search(value)
        or _BASE32_SECRET.search(value)
    ):
        return True
    for match in _ENTROPY_TOKEN.finditer(value):
        token = match.group(0).rstrip("=")
        if len(token) < 24:
            continue
        if (
            any(char.isalpha() for char in token)
            and any(char.isdigit() for char in token)
            and _shannon_entropy(token.casefold()) >= 3.5
        ):
            return True
    return False


def _bounded_text(value: object, label: str, maximum: int = MAX_TEXT) -> str:
    """Validate string shape/size without assigning it a semantic DLP role."""
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise Phase5RuntimeV6ContractError(f"{label} is invalid")
    return value


def _text(
    value: object, label: str, maximum: int = MAX_TEXT, *, redact: bool = True
) -> str:
    value = _bounded_text(value, label, maximum)
    if _contains_sensitive_value(value):
        if redact:
            return "[REDACTED]"
        raise Phase5RuntimeV6ContractError(f"{label} contains sensitive data")
    return value


def _flag(raw: object) -> bool:
    return type(raw) is str and raw.strip().casefold() in {"1", "true"}


@dataclass(frozen=True, slots=True)
class RuntimeFlagsV6:
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
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> RuntimeFlagsV6:
        source = os.environ if environ is None else environ
        return cls(
            runtime=_flag(source.get(PHASE5_RUNTIME_FLAG, "")),
            grant_shadow=_flag(source.get(PHASE5_GRANT_SHADOW_FLAG, "")),
            approval_inbox=_flag(source.get(PHASE5_APPROVAL_INBOX_FLAG, "")),
            low_risk=_flag(source.get(PHASE5_LOW_RISK_FLAG, "")),
            nexus_projection=_flag(source.get(PHASE5_NEXUS_PROJECTION_FLAG, "")),
            local_catalog_read=_flag(source.get(PHASE5_LOCAL_CATALOG_READ_FLAG, "")),
            dashboard_projection=_flag(
                source.get(PHASE5_DASHBOARD_PROJECTION_FLAG, "")
            ),
        )

    def payload(self) -> tuple[tuple[str, bool], ...]:
        return tuple((name, getattr(self, name)) for name in self.__dataclass_fields__)


@dataclass(frozen=True, slots=True)
class RuntimeBindingV6:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _safe_id(getattr(self, name), name))


def _binding(value: object) -> RuntimeBindingV6:
    if type(value) is not RuntimeBindingV6:
        raise Phase5RuntimeV6ContractError("binding must be exact RuntimeBindingV6")
    return RuntimeBindingV6(
        value.trace_id,
        value.session_id,
        value.workspace_id,
        value.account_id,
        value.profile_id,
    )


def _flags(value: object) -> RuntimeFlagsV6:
    if type(value) is not RuntimeFlagsV6:
        raise Phase5RuntimeV6ContractError("flags must be exact RuntimeFlagsV6")
    return RuntimeFlagsV6(**dict(value.payload()))


@dataclass(frozen=True, slots=True)
class ActionRequestV6:
    invocation_ref: str
    binding: RuntimeBindingV6
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
        object.__setattr__(
            self, "invocation_ref", _safe_id(self.invocation_ref, "invocation_ref")
        )
        object.__setattr__(self, "binding", _binding(self.binding))
        for name in ("capability", "operation", "effect", "egress", "risk"):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, 128, redact=False)
            )
        for name in (
            "provider_free",
            "read_only",
            "metadata_allowlisted",
            "reversible",
            "uses_credentials",
            "privileged",
            "irreversible",
        ):
            _exact_bool(getattr(self, name), name)
        if type(self.cost_micro) is not int or not 0 <= self.cost_micro <= MAX_INTEGER:
            raise Phase5RuntimeV6ContractError("cost_micro is invalid")
        if self.risk not in _RISKS:
            raise Phase5RuntimeV6ContractError("risk is invalid")
        if type(self.action_classes) is not tuple or len(self.action_classes) > 32:
            raise Phase5RuntimeV6ContractError("action_classes is invalid")
        classes = tuple(
            _safe_id(item, "action_class").casefold() for item in self.action_classes
        )
        if len(classes) != len(set(classes)):
            raise Phase5RuntimeV6ContractError("action_classes contains duplicates")
        object.__setattr__(self, "action_classes", tuple(sorted(classes)))


def _action(value: object) -> ActionRequestV6:
    if type(value) is not ActionRequestV6:
        raise Phase5RuntimeV6ContractError("action must be exact ActionRequestV6")
    return ActionRequestV6(
        value.invocation_ref,
        value.binding,
        value.capability,
        value.operation,
        value.provider_free,
        value.read_only,
        value.effect,
        value.egress,
        value.metadata_allowlisted,
        value.cost_micro,
        value.risk,
        value.reversible,
        value.uses_credentials,
        value.privileged,
        value.irreversible,
        value.action_classes,
    )


@dataclass(frozen=True, slots=True)
class RuntimeDecisionV6:
    disposition: RuntimeDispositionV6
    reason: str
    trace_id: str
    epoch: int
    advisory_json: str = "{}"

    def __post_init__(self) -> None:
        if type(self.disposition) is not RuntimeDispositionV6:
            raise Phase5RuntimeV6ContractError("decision disposition is invalid")
        _text(self.reason, "reason", 128, redact=False)
        _safe_id(self.trace_id, "trace_id")
        if type(self.epoch) is not int or self.epoch < 1:
            raise Phase5RuntimeV6ContractError("decision epoch is invalid")
        if (
            type(self.advisory_json) is not str
            or len(self.advisory_json.encode()) > MAX_EVENT_TEXT_BYTES
        ):
            raise Phase5RuntimeV6ContractError("advisory_json is invalid")
        try:
            parsed = json.loads(self.advisory_json)
        except json.JSONDecodeError as exc:
            raise Phase5RuntimeV6ContractError("advisory_json is invalid") from exc
        if type(parsed) is not dict or set(parsed) - {
            "outcome",
            "reason",
            "grant_id",
            "scope_digest",
            "action_digest",
        }:
            raise Phase5RuntimeV6ContractError("advisory_json schema is invalid")
        normalized = _normalize_advisory(parsed)
        encoded = json.dumps(
            normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        if len(encoded.encode()) > MAX_EVENT_TEXT_BYTES:
            raise Phase5RuntimeV6ContractError("advisory_json is invalid")
        object.__setattr__(self, "advisory_json", encoded)


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
            raise Phase5RuntimeV6ContractError("JSON budget exceeded")


def _json_value(
    value: object,
    *,
    depth: int = 0,
    budget: _Budget | None = None,
    screen_content: bool = True,
) -> object:
    """Bound and copy JSON incrementally; cycles and shared containers fail closed."""
    if budget is None:
        budget = _Budget()
    if depth > MAX_DEPTH:
        raise Phase5RuntimeV6ContractError("JSON nesting is too deep")
    budget.add()
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if not -MAX_INTEGER <= value <= MAX_INTEGER:
            raise Phase5RuntimeV6ContractError("JSON integer is out of bounds")
        budget.add(nodes=0, bytes_=len(str(value)))
        return value
    if type(value) is str:
        normalized = (
            _text(value, "JSON text", MAX_TEXT)
            if screen_content
            else _bounded_text(value, "JSON text", MAX_TEXT)
        )
        budget.add(nodes=0, bytes_=len(normalized.encode()))
        return normalized
    if type(value) in {list, tuple, dict, MappingProxyType}:
        identity = id(value)
        assert budget.seen is not None
        if identity in budget.seen:
            raise Phase5RuntimeV6ContractError(
                "JSON contains a cycle or shared container"
            )
        budget.seen.add(identity)
    if type(value) in {list, tuple}:
        if len(value) > MAX_FANOUT:
            raise Phase5RuntimeV6ContractError("JSON sequence fanout exceeded")
        return [
            _json_value(
                item,
                depth=depth + 1,
                budget=budget,
                screen_content=screen_content,
            )
            for item in value
        ]
    if type(value) is dict or type(value) is MappingProxyType:
        if len(value) > MAX_FANOUT:
            raise Phase5RuntimeV6ContractError("JSON object fanout exceeded")
        result: dict[str, object] = {}
        for key, item in value.items():
            if (
                type(key) is not str
                or not key
                or len(key.encode()) > 128
                or _SENSITIVE_KEY.search(key)
            ):
                raise Phase5RuntimeV6ContractError("JSON key is unsafe")
            budget.add(nodes=0, bytes_=len(key.encode()))
            result[key] = _json_value(
                item,
                depth=depth + 1,
                budget=budget,
                screen_content=screen_content,
            )
        return result
    raise Phase5RuntimeV6ContractError("JSON contains a non-JSON value")


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProjectionBatchV6:
    items: tuple[Mapping[str, object], ...]
    replace: bool = True
    source_cursor: str | None = None
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.items) is not tuple or len(self.items) > MAX_PAGE_SIZE:
            raise Phase5RuntimeV6ContractError("projection batch is invalid")
        normalized: list[Mapping[str, object]] = []
        budget = _Budget()
        for item in self.items:
            if type(item) not in {dict, MappingProxyType}:
                raise Phase5RuntimeV6ContractError(
                    "projection items must be exact mappings"
                )
            # Projection batches are still copied and bounded here, but DLP is
            # applied later by the closed, per-field schema.  This is what lets
            # an item UUID coexist with aggressively screened prose.
            value = _json_value(item, budget=budget, screen_content=False)
            assert type(value) is dict
            normalized.append(_freeze(value))  # type: ignore[arg-type]
        object.__setattr__(self, "items", tuple(normalized))
        _exact_bool(self.replace, "replace")
        object.__setattr__(
            self,
            "source_cursor",
            _optional_safe_id(self.source_cursor, "source_cursor"),
        )
        object.__setattr__(
            self, "next_cursor", _optional_safe_id(self.next_cursor, "next_cursor")
        )
        if self.next_cursor is not None and self.next_cursor == self.source_cursor:
            raise Phase5RuntimeV6ContractError("projection cursor does not advance")


def _batch(value: object) -> ProjectionBatchV6:
    if type(value) is not ProjectionBatchV6:
        raise Phase5RuntimeV6ContractError("component returned the wrong batch type")
    budget = _Budget()
    return ProjectionBatchV6(
        tuple(
            dict(_json_value(item, budget=budget, screen_content=False))
            for item in value.items
        ),
        replace=value.replace,
        source_cursor=value.source_cursor,
        next_cursor=value.next_cursor,
    )


class ApprovalInboxReaderV6(Protocol):
    def read_page(
        self,
        *,
        binding: RuntimeBindingV6,
        page_size: int,
        cursor: str | None,
    ) -> ProjectionBatchV6: ...


@dataclass(frozen=True, slots=True)
class RuntimeComponentsV6:
    grant_evaluator: Callable[[str], object] | None = None
    nexus_projector: Callable[[RuntimeBindingV6], ProjectionBatchV6] | None = None
    inbox_factory: Callable[[RuntimeBindingV6], ApprovalInboxReaderV6] | None = None
    grant_terminator: Callable[[str], None] | None = None
    nexus_terminator: Callable[[str], None] | None = None
    inbox_terminator: Callable[[str], None] | None = None
    rollback_callback: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise Phase5RuntimeV6ContractError(f"{name} must be callable")


def _components(value: object) -> RuntimeComponentsV6:
    if type(value) is not RuntimeComponentsV6:
        raise Phase5RuntimeV6ContractError(
            "components must be exact RuntimeComponentsV6"
        )
    return RuntimeComponentsV6(
        **{name: getattr(value, name) for name in value.__dataclass_fields__}
    )


@dataclass(frozen=True, slots=True)
class ProjectionItemV6:
    item_id: str
    payload_json: str

    def payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        assert type(value) is dict
        return value


@dataclass(frozen=True, slots=True)
class ProjectionPageV6:
    kind: str
    offset: int
    page_size: int
    total: int
    items: tuple[ProjectionItemV6, ...]
    next_offset: int | None
    source_cursor: str | None
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class RuntimeEventV6:
    sequence: int
    kind: str
    outcome: str
    component: str | None = None
    count: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeStatusV6:
    state: RuntimeStateV6
    reason: str
    epoch: int
    binding: RuntimeBindingV6
    flags: tuple[tuple[str, bool], ...]
    capability_count: int
    inbox_count: int
    event_count: int
    component_failures: tuple[str, ...]
    termination_failures: tuple[str, ...]
    termination_timeouts: tuple[str, ...]
    failure_observations: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _DecisionSealV6:
    decision: RuntimeDecisionV6
    public_digest: str
    request_digest: str
    binding_digest: str
    flags_digest: str
    epoch: int
    authority_digest: str


def _digest(value: object) -> str:
    data = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(data).hexdigest()


def _binding_digest(value: RuntimeBindingV6) -> str:
    return _digest(
        [
            value.trace_id,
            value.session_id,
            value.workspace_id,
            value.account_id,
            value.profile_id,
        ]
    )


def _flags_digest(value: RuntimeFlagsV6) -> str:
    return _digest(value.payload())


def _action_digest(value: ActionRequestV6) -> str:
    return _digest(
        {
            "invocation_ref": value.invocation_ref,
            "binding": _binding_digest(value.binding),
            "capability": value.capability,
            "operation": value.operation,
            "provider_free": value.provider_free,
            "read_only": value.read_only,
            "effect": value.effect,
            "egress": value.egress,
            "metadata_allowlisted": value.metadata_allowlisted,
            "cost_micro": value.cost_micro,
            "risk": value.risk,
            "reversible": value.reversible,
            "uses_credentials": value.uses_credentials,
            "privileged": value.privileged,
            "irreversible": value.irreversible,
            "action_classes": value.action_classes,
        }
    )


def _decision_digest(value: RuntimeDecisionV6) -> str:
    return _digest(
        [
            value.disposition.value,
            value.reason,
            value.trace_id,
            value.epoch,
            value.advisory_json,
        ]
    )


def _authority_digest(
    key: bytes,
    public: str,
    request: str,
    binding: str,
    flags: str,
    epoch: int,
) -> str:
    return hmac.new(
        key,
        "\0".join((public, request, binding, flags, str(epoch))).encode(),
        hashlib.sha256,
    ).hexdigest()


_CAPABILITY_FIELDS = frozenset(
    {
        "capability_id",
        "display_name",
        "provider",
        "version",
        "status",
        "operations",
        "limitation",
    }
)
_INBOX_FIELDS = frozenset(
    {
        "item_id",
        "request_ref",
        "capability",
        "operation",
        "risk",
        "state",
        "summary",
        "created_at",
    }
)


def _closed_capability(
    raw: Mapping[str, object], binding: RuntimeBindingV6
) -> tuple[str, dict[str, object]]:
    if set(raw) != _CAPABILITY_FIELDS:
        raise Phase5RuntimeV6ContractError("capability schema fields are invalid")
    identifier = _safe_id(raw["capability_id"], "capability_id")
    operations = raw["operations"]
    if type(operations) not in {tuple, list} or not 1 <= len(operations) <= 16:
        raise Phase5RuntimeV6ContractError("capability operations are invalid")
    clean_operations = tuple(_safe_id(item, "operation") for item in operations)
    if len(clean_operations) != len(set(clean_operations)):
        raise Phase5RuntimeV6ContractError("capability operations contain duplicates")
    status = _text(raw["status"], "status", 32, redact=False)
    if status not in _CAPABILITY_STATUS:
        raise Phase5RuntimeV6ContractError("capability status is invalid")
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
        "trace_id": binding.trace_id,
        "session_id": binding.session_id,
        "workspace_id": binding.workspace_id,
        "account_id": binding.account_id,
        "profile_id": binding.profile_id,
    }
    return identifier, payload


def _closed_inbox(
    raw: Mapping[str, object], binding: RuntimeBindingV6
) -> tuple[str, dict[str, object]]:
    if set(raw) != _INBOX_FIELDS:
        raise Phase5RuntimeV6ContractError("inbox schema fields are invalid")
    identifier = _safe_id(raw["item_id"], "item_id")
    risk = _text(raw["risk"], "risk", 16, redact=False)
    state = _text(raw["state"], "state", 16, redact=False)
    if risk not in _RISKS or state not in _INBOX_STATE:
        raise Phase5RuntimeV6ContractError("inbox enum is invalid")
    created_at = _text(raw["created_at"], "created_at", 32, redact=False)
    if not _RFC3339_UTC.fullmatch(created_at):
        raise Phase5RuntimeV6ContractError("created_at is invalid")
    payload: dict[str, object] = {
        "item_id": identifier,
        "request_ref": _safe_id(raw["request_ref"], "request_ref"),
        "capability": _text(raw["capability"], "capability", 128),
        "operation": _text(raw["operation"], "operation", 128),
        "risk": risk,
        "state": state,
        "summary": _text(raw["summary"], "summary", 512),
        "created_at": created_at,
        "trace_id": binding.trace_id,
        "session_id": binding.session_id,
        "workspace_id": binding.workspace_id,
        "account_id": binding.account_id,
        "profile_id": binding.profile_id,
    }
    return identifier, payload


def _record(
    surface: str, raw: Mapping[str, object], binding: RuntimeBindingV6
) -> ProjectionItemV6:
    identifier, payload = (
        _closed_capability(raw, binding)
        if surface == "capabilities"
        else _closed_inbox(raw, binding)
    )
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if len(encoded.encode()) > MAX_PROJECTION_ROW_BYTES:
        raise Phase5RuntimeV6ContractError("projection row is too large")
    return ProjectionItemV6(identifier, encoded)


def _normalize_advisory(raw: Mapping[str, object]) -> dict[str, object]:
    """Apply DLP according to each field's closed semantic role."""
    if set(raw) - {
        "outcome",
        "reason",
        "grant_id",
        "scope_digest",
        "action_digest",
    }:
        raise Phase5RuntimeV6ContractError("grant advisory fields are invalid")
    normalized: dict[str, object] = {}
    for name, item in raw.items():
        if name in {"grant_id", "scope_digest", "action_digest"}:
            normalized[name] = _safe_id(item, name)
        elif type(item) is str:
            normalized[name] = _text(item, name, 128)
        elif type(item) in {int, bool}:
            normalized[name] = _json_value(item)
        else:
            raise Phase5RuntimeV6ContractError("grant advisory field is invalid")
    return normalized


def _advisory(value: object) -> str:
    if value is None:
        raw: dict[str, object] = {"outcome": "none"}
    elif type(value) is dict:
        raw = dict(value)
    else:
        raw = {}
        for name in ("outcome", "reason", "grant_id", "scope_digest", "action_digest"):
            item = getattr(value, name, None)
            if item is not None:
                if type(item) not in {str, int, bool}:
                    raise Phase5RuntimeV6ContractError(
                        "grant advisory field is invalid"
                    )
                raw[name] = item
        if not raw:
            raw = {"outcome": type(value).__name__}
    normalized = _normalize_advisory(raw)
    encoded = json.dumps(
        normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if len(encoded.encode()) > MAX_EVENT_TEXT_BYTES:
        raise Phase5RuntimeV6ContractError("grant advisory is too large")
    return encoded


_T = TypeVar("_T")


_TERMINATION_LOCAL = threading.local()


class _TerminationSupervisor:
    """Lazily started process-global bounded callback executor.

    One queued job represents all callbacks for one runtime.  This keeps both
    worker and queue cardinality independent of callback count and prevents the
    per-runtime daemon leak that V5 permitted when callbacks never returned.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue(
            maxsize=MAX_TERMINATION_QUEUE
        )
        self._lock = threading.Lock()
        self._started = False

    def _start_locked(self) -> None:
        if self._started:
            return
        self._started = True
        for index in range(MAX_TERMINATION_WORKERS):
            threading.Thread(
                target=self._worker,
                name=f"phase5-v6-termination-supervisor-{index}",
                daemon=True,
            ).start()

    def submit(self, job: Callable[[], None]) -> bool:
        with self._lock:
            self._start_locked()
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                return False
            return True

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                job()
            except BaseException:
                # Runtime-owned jobs catch and publish callback failures.  This
                # final guard keeps the global worker alive if a host bug leaks.
                pass
            finally:
                self._queue.task_done()


_TERMINATION_SUPERVISOR = _TerminationSupervisor()


class Phase5RuntimeV6:
    """Bounded event-driven host extension with no autonomous execution."""

    def __init__(
        self,
        *,
        binding: RuntimeBindingV6,
        flags: RuntimeFlagsV6 | None = None,
        components: RuntimeComponentsV6 | None = None,
        termination_callback_timeout_seconds: float = 1.0,
    ) -> None:
        if (
            type(termination_callback_timeout_seconds) not in {int, float}
            or type(termination_callback_timeout_seconds) is bool
            or not math.isfinite(float(termination_callback_timeout_seconds))
            or not 0.001 <= float(termination_callback_timeout_seconds) <= 30.0
        ):
            raise Phase5RuntimeV6ContractError(
                "termination_callback_timeout_seconds is invalid"
            )
        self._binding = _binding(binding)
        self._flags = _flags(flags or RuntimeFlagsV6.from_environ())
        self._components = _components(components or RuntimeComponentsV6())
        self._lock = threading.RLock()
        self._terminal_condition = threading.Condition(self._lock)
        self._config_generation = 1
        # A component generation describes its effective binding/configuration,
        # not an individual call.  Unrelated/no-op configuration must not make
        # an in-flight failure disappear.
        self._component_generation = {name: 1 for name in _COMPONENTS}
        self._component_operation_sequence = {name: 0 for name in _COMPONENTS}
        self._component_failure_observation = {name: 0 for name in _COMPONENTS}
        self._authority_epoch = 1
        self._inbox_journey = 0
        self._terminated = False
        self._termination_running = False
        self._termination_complete = False
        self._termination_job_submitted = False
        self._termination_callbacks: tuple[
            tuple[str, Callable[[str], None]], ...
        ] = ()
        self._termination_pending_callbacks: set[str] = set()
        self._termination_callback_timeout_seconds = float(
            termination_callback_timeout_seconds
        )
        self._terminal_reason: str | None = None
        # Failure includes UNVERIFIED.  It is intentionally sticky and can be
        # removed only by recover_component after a successful current-generation
        # probe.  Ordinary refresh/evaluation never heals authority implicitly.
        self._component_failures: set[str] = {
            name for name in _COMPONENTS if self._enabled_component_locked(name)
        }
        self._termination_failures: set[str] = set()
        self._termination_timeouts: set[str] = set()
        self._capabilities: OrderedDict[str, ProjectionItemV6] = OrderedDict()
        self._inbox: OrderedDict[str, ProjectionItemV6] = OrderedDict()
        self._capability_source_cursor: str | None = None
        self._capability_next_cursor: str | None = None
        self._inbox_source_cursor: str | None = None
        self._inbox_next_cursor: str | None = None
        self._inbox_started = False
        self._inbox_cursor_history: set[str] = set()
        self._events: deque[RuntimeEventV6] = deque(maxlen=MAX_EVENTS)
        self._event_sequence = 0
        self._decision_seals: OrderedDict[int, _DecisionSealV6] = OrderedDict()
        self._decision_key = secrets.token_bytes(32)

    @property
    def binding(self) -> RuntimeBindingV6:
        with self._lock:
            return _binding(self._binding)

    @property
    def flags(self) -> RuntimeFlagsV6:
        with self._lock:
            return _flags(self._flags)

    def _event_locked(
        self,
        kind: str,
        outcome: str,
        *,
        component: str | None = None,
        count: int | None = None,
        reason: str | None = None,
    ) -> None:
        kind = _safe_id(kind, "event kind")
        outcome = _safe_id(outcome, "event outcome")
        component = (
            None if component is None else _safe_id(component, "event component")
        )
        if count is not None and (
            type(count) is not int or not 0 <= count <= MAX_PROJECTION_ITEMS
        ):
            raise Phase5RuntimeV6ContractError("event count is invalid")
        reason = (
            None
            if reason is None
            else _text(reason, "event reason", MAX_EVENT_TEXT_BYTES)
        )
        self._event_sequence += 1
        self._events.append(
            RuntimeEventV6(
                self._event_sequence, kind, outcome, component, count, reason
            )
        )

    def _clear_projections_locked(self) -> None:
        self._capabilities.clear()
        self._inbox.clear()
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

    def rebind(self, binding: RuntimeBindingV6) -> RuntimeStatusV6:
        snapshot = _binding(binding)
        with self._lock:
            self._ensure_active_locked()
            if snapshot == self._binding:
                return self._status_locked()
            self._binding = snapshot
            for name in _COMPONENTS:
                self._component_generation[name] += 1
                if self._enabled_component_locked(name):
                    self._component_failures.add(name)
            self._retire_locked(configuration=True)
            self._event_locked("configuration", "binding_replaced")
            return self._status_locked()

    def configure_flags(self, flags: RuntimeFlagsV6) -> RuntimeStatusV6:
        snapshot = _flags(flags)
        with self._lock:
            self._ensure_active_locked()
            if snapshot == self._flags:
                return self._status_locked()
            previous = self._flags
            self._flags = snapshot
            previous_enabled = {
                "grant_shadow": previous.grant_shadow,
                "nexus": previous.nexus_projection,
                "inbox": previous.approval_inbox,
            }
            current_enabled = {
                "grant_shadow": snapshot.grant_shadow,
                "nexus": snapshot.nexus_projection,
                "inbox": snapshot.approval_inbox,
            }
            for name in _COMPONENTS:
                if (
                    previous_enabled[name] != current_enabled[name]
                    or previous.runtime != snapshot.runtime
                ):
                    self._component_generation[name] += 1
                if current_enabled[name] and (
                    not previous_enabled[name]
                    or (not previous.runtime and snapshot.runtime)
                ):
                    self._component_failures.add(name)
            self._retire_locked(configuration=True)
            self._event_locked("configuration", "flags_replaced")
            return self._status_locked()

    def replace_components(self, components: RuntimeComponentsV6) -> RuntimeStatusV6:
        snapshot = _components(components)
        with self._lock:
            self._ensure_active_locked()
            fields = tuple(snapshot.__dataclass_fields__)
            if all(
                getattr(snapshot, name) is getattr(self._components, name)
                for name in fields
            ):
                return self._status_locked()
            previous = self._components
            self._components = snapshot
            component_fields = {
                "grant_shadow": ("grant_evaluator", "grant_terminator"),
                "nexus": ("nexus_projector", "nexus_terminator"),
                "inbox": ("inbox_factory", "inbox_terminator"),
            }
            for name, names in component_fields.items():
                if any(
                    getattr(previous, field) is not getattr(snapshot, field)
                    for field in names
                ):
                    self._component_generation[name] += 1
                    if self._enabled_component_locked(name):
                        self._component_failures.add(name)
            self._retire_locked(configuration=True)
            self._event_locked("configuration", "components_replaced")
            return self._status_locked()

    def _ensure_active_locked(self) -> None:
        if self._terminated:
            raise Phase5RuntimeV6Error("runtime is terminated")

    def _enabled_component_locked(self, name: str) -> bool:
        return {
            "grant_shadow": self._flags.grant_shadow,
            "nexus": self._flags.nexus_projection,
            "inbox": self._flags.approval_inbox,
        }[name]

    def _state_locked(self) -> RuntimeStateV6:
        if self._termination_running:
            return RuntimeStateV6.TERMINATION_PENDING
        if self._termination_complete:
            return RuntimeStateV6.TERMINATED
        if not self._flags.runtime:
            return RuntimeStateV6.DISABLED
        if any(
            self._enabled_component_locked(name)
            and (
                name in self._component_failures
                or self._component_callable_locked(name) is None
            )
            for name in _COMPONENTS
        ):
            return RuntimeStateV6.DEGRADED
        return RuntimeStateV6.READY

    def _status_locked(self) -> RuntimeStatusV6:
        state = self._state_locked()
        reason = (
            self._terminal_reason
            if self._terminated
            else (
                "feature_flag_off"
                if state is RuntimeStateV6.DISABLED
                else "component_failure"
                if state is RuntimeStateV6.DEGRADED
                else "ready"
            )
        )
        return RuntimeStatusV6(
            state,
            reason or "terminated",
            self._authority_epoch,
            _binding(self._binding),
            self._flags.payload(),
            len(self._capabilities),
            len(self._inbox),
            len(self._events),
            tuple(sorted(self._component_failures)),
            tuple(sorted(self._termination_failures)),
            tuple(sorted(self._termination_timeouts)),
            tuple(sorted(self._component_failure_observation.items())),
        )

    def status(self) -> RuntimeStatusV6:
        with self._lock:
            return self._status_locked()

    @staticmethod
    def _page_bounds(offset: int, page_size: int) -> tuple[int, int]:
        if type(offset) is not int or not 0 <= offset <= MAX_PROJECTION_ITEMS:
            raise Phase5RuntimeV6ContractError("offset is invalid")
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise Phase5RuntimeV6ContractError("page_size is invalid")
        return offset, page_size

    def events(
        self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE
    ) -> tuple[RuntimeEventV6, ...]:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return tuple(self._events)[offset : offset + page_size]

    def _set_failure_locked(self, name: str, failed: bool) -> None:
        if name not in _COMPONENTS:
            raise Phase5RuntimeV6ContractError("component is invalid")
        changed = (failed and name not in self._component_failures) or (
            not failed and name in self._component_failures
        )
        if failed:
            self._component_failure_observation[name] += 1
            self._component_failures.add(name)
        else:
            self._component_failures.discard(name)
        if changed:
            self._authority_epoch += 1
            self._decision_seals.clear()

    def _component_lease_locked(self, name: str) -> tuple[int, int]:
        return self._component_generation[name], id(
            self._component_callable_locked(name)
        )

    def _lease_current_locked(self, name: str, lease: tuple[int, int]) -> bool:
        return lease == (
            self._component_generation[name],
            id(self._component_callable_locked(name)),
        )

    def _next_operation_locked(self, name: str) -> int:
        """Issue the only sequence that may next publish for a component."""
        self._component_operation_sequence[name] += 1
        return self._component_operation_sequence[name]

    def _operation_current_locked(self, name: str, sequence: int) -> bool:
        return self._component_operation_sequence[name] == sequence

    def _component_callable_locked(self, name: str) -> object | None:
        if name == "grant_shadow":
            return self._components.grant_evaluator
        if name == "nexus":
            return self._components.nexus_projector
        if name == "inbox":
            return self._components.inbox_factory
        raise Phase5RuntimeV6ContractError("component is invalid")

    def _record_failure(
        self,
        name: str,
        lease: tuple[int, int],
        operation_sequence: int | None = None,
        outcome: str = "failure",
    ) -> None:
        with self._lock:
            if (
                not self._terminated
                and self._lease_current_locked(name, lease)
                and (
                    operation_sequence is None
                    or self._operation_current_locked(name, operation_sequence)
                )
                and self._enabled_component_locked(name)
            ):
                self._set_failure_locked(name, True)
                self._event_locked("component", outcome, component=name)

    @staticmethod
    def _contains_explicit(action: ActionRequestV6) -> bool:
        if (
            action.uses_credentials
            or action.privileged
            or action.irreversible
            or action.action_classes
        ):
            return True
        words = set(
            re.findall(
                r"[a-z0-9]+", f"{action.capability} {action.operation}".casefold()
            )
        )
        return bool(words & _EXPLICIT_WORDS)

    def _decision_locked(
        self,
        disposition: RuntimeDispositionV6,
        reason: str,
        advisory: str = "{}",
        *,
        request_digest: str | None = None,
        publish: bool = True,
    ) -> RuntimeDecisionV6:
        decision = RuntimeDecisionV6(
            disposition, reason, self._binding.trace_id, self._authority_epoch, advisory
        )
        if not publish:
            return decision
        self._event_locked("decision", disposition.value, reason=reason)
        if disposition is RuntimeDispositionV6.ALLOW_LOCAL_CATALOG_READ:
            if request_digest is None:
                raise Phase5RuntimeV6ContractError(
                    "allow decision lacks request digest"
                )
            public = _decision_digest(decision)
            binding = _binding_digest(self._binding)
            flags = _flags_digest(self._flags)
            authority = _authority_digest(
                self._decision_key,
                public,
                request_digest,
                binding,
                flags,
                self._authority_epoch,
            )
            self._decision_seals[id(decision)] = _DecisionSealV6(
                decision,
                public,
                request_digest,
                binding,
                flags,
                self._authority_epoch,
                authority,
            )
            while len(self._decision_seals) > MAX_DECISION_SEALS:
                self._decision_seals.popitem(last=False)
        return decision

    def evaluate(self, action: ActionRequestV6) -> RuntimeDecisionV6:
        with self._lock:
            if self._terminated:
                return self._decision_locked(
                    RuntimeDispositionV6.EXPLICIT, "runtime_terminated"
                )
            if not self._flags.runtime:
                return self._decision_locked(
                    RuntimeDispositionV6.FALLBACK, "feature_flag_off", publish=False
                )
            try:
                snapshot = _action(action)
            except (AttributeError, Phase5RuntimeV6ContractError):
                return self._decision_locked(
                    RuntimeDispositionV6.EXPLICIT, "invalid_action_contract"
                )
            if self._contains_explicit(snapshot):
                return self._decision_locked(
                    RuntimeDispositionV6.EXPLICIT, "explicit_action_class"
                )
            if not self._flags.low_risk or not self._flags.local_catalog_read:
                return self._decision_locked(
                    RuntimeDispositionV6.FALLBACK, "extension_path_off", publish=False
                )
            if snapshot.binding != self._binding:
                return self._decision_locked(
                    RuntimeDispositionV6.EXPLICIT, "scope_mismatch"
                )
            exact = (
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
            if not exact:
                return self._decision_locked(
                    RuntimeDispositionV6.EXPLICIT, "not_exact_local_catalog_read"
                )
            if any(
                self._enabled_component_locked(name)
                and (
                    name in self._component_failures
                    or self._component_callable_locked(name) is None
                )
                for name in _COMPONENTS
            ):
                return self._decision_locked(
                    RuntimeDispositionV6.EXPLICIT, "component_unverified_or_failed"
                )
            observer = (
                self._components.grant_evaluator if self._flags.grant_shadow else None
            )
            if self._flags.grant_shadow and observer is None:
                self._set_failure_locked("grant_shadow", True)
                return self._decision_locked(
                    RuntimeDispositionV6.EXPLICIT, "grant_shadow_unavailable"
                )
            config_lease = self._config_generation
            component_lease = (
                self._component_lease_locked("grant_shadow")
                if observer is not None
                else None
            )

        advisory = "{}"
        if observer is not None:
            try:
                advisory = _advisory(observer(snapshot.invocation_ref))
            except BaseException:
                assert component_lease is not None
                self._record_failure("grant_shadow", component_lease)
                with self._lock:
                    return self._decision_locked(
                        RuntimeDispositionV6.EXPLICIT, "grant_shadow_failure"
                    )

        with self._lock:
            if self._terminated or config_lease != self._config_generation:
                return self._decision_locked(
                    RuntimeDispositionV6.EXPLICIT, "authority_revoked_during_evaluation"
                )
            if component_lease is not None:
                if not self._lease_current_locked("grant_shadow", component_lease):
                    return self._decision_locked(
                        RuntimeDispositionV6.EXPLICIT, "evaluation_superseded"
                    )
            if any(
                self._enabled_component_locked(name)
                for name in self._component_failures
            ):
                return self._decision_locked(
                    RuntimeDispositionV6.EXPLICIT, "component_failure_during_evaluation"
                )
            return self._decision_locked(
                RuntimeDispositionV6.ALLOW_LOCAL_CATALOG_READ,
                "exact_provider_free_catalog_read",
                advisory,
                request_digest=_action_digest(snapshot),
            )

    def legacy_or_decision(
        self, action: ActionRequestV6, legacy: Callable[[], _T]
    ) -> _T | RuntimeDecisionV6:
        if not callable(legacy):
            raise Phase5RuntimeV6ContractError("legacy fallback must be callable")
        decision = self.evaluate(action)
        return (
            legacy()
            if decision.disposition is RuntimeDispositionV6.FALLBACK
            else decision
        )

    def _current_locked(
        self, decision: RuntimeDecisionV6, action: ActionRequestV6
    ) -> bool:
        if (
            type(decision) is not RuntimeDecisionV6
            or type(action) is not ActionRequestV6
        ):
            return False
        seal = self._decision_seals.get(id(decision))
        if seal is None or seal.decision is not decision:
            return False
        try:
            snapshot = _action(action)
            public = _decision_digest(decision)
            request = _action_digest(snapshot)
            binding = _binding_digest(self._binding)
            flags = _flags_digest(self._flags)
            authority = _authority_digest(
                self._decision_key,
                public,
                request,
                binding,
                flags,
                self._authority_epoch,
            )
        except (AttributeError, TypeError, ValueError):
            return False
        return (
            decision.disposition is RuntimeDispositionV6.ALLOW_LOCAL_CATALOG_READ
            and not self._terminated
            and not any(
                self._enabled_component_locked(name)
                for name in self._component_failures
            )
            and snapshot.binding == self._binding
            and seal.epoch == self._authority_epoch
            and decision.epoch == self._authority_epoch
            and decision.trace_id == self._binding.trace_id
            and hmac.compare_digest(seal.public_digest, public)
            and hmac.compare_digest(seal.request_digest, request)
            and hmac.compare_digest(seal.binding_digest, binding)
            and hmac.compare_digest(seal.flags_digest, flags)
            and hmac.compare_digest(seal.authority_digest, authority)
        )

    def decision_is_current(
        self, decision: RuntimeDecisionV6, action: ActionRequestV6 | None = None
    ) -> bool:
        """Deprecated one-argument use fails closed; request binding is mandatory."""
        if action is None:
            return False
        with self._lock:
            return self._current_locked(decision, action)

    def consume_decision(
        self, decision: RuntimeDecisionV6, action: ActionRequestV6
    ) -> bool:
        """Atomically consume one exact issued allow for one exact request."""
        with self._lock:
            if not self._current_locked(decision, action):
                return False
            del self._decision_seals[id(decision)]
            self._event_locked("decision", "consumed", reason="exact_request_consumed")
            return True

    @staticmethod
    def _prepare(
        surface: str,
        batch: ProjectionBatchV6,
        binding: RuntimeBindingV6,
    ) -> tuple[ProjectionBatchV6, tuple[ProjectionItemV6, ...]]:
        snapshot = _batch(batch)
        records = tuple(_record(surface, item, binding) for item in snapshot.items)
        if len({record.item_id for record in records}) != len(records):
            raise Phase5RuntimeV6ContractError(
                "projection page contains duplicate identifiers"
            )
        return snapshot, records

    @staticmethod
    def _apply(
        target: OrderedDict[str, ProjectionItemV6],
        records: tuple[ProjectionItemV6, ...],
        *,
        replace: bool,
        forbid_existing: bool = False,
    ) -> None:
        if forbid_existing and any(record.item_id in target for record in records):
            raise Phase5RuntimeV6ContractError(
                "projection repeats an earlier identifier"
            )
        if replace:
            target.clear()
        for record in records:
            target.pop(record.item_id, None)
            target[record.item_id] = record
        while len(target) > MAX_PROJECTION_ITEMS:
            target.popitem(last=False)

    def refresh_capabilities(self) -> ProjectionPageV6:
        with self._lock:
            if (
                self._terminated
                or not self._flags.runtime
                or not self._flags.nexus_projection
            ):
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
            projector = self._components.nexus_projector
            lease = self._component_lease_locked("nexus")
            operation_sequence = self._next_operation_locked("nexus")
            binding = _binding(self._binding)
            if projector is None:
                self._set_failure_locked("nexus", True)
                self._event_locked("capabilities", "unavailable")
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
        try:
            snapshot, records = self._prepare(
                "capabilities", projector(binding), binding
            )
        except BaseException:
            self._record_failure("nexus", lease, operation_sequence)
            return self.capabilities()
        with self._lock:
            if (
                self._terminated
                or not self._lease_current_locked("nexus", lease)
                or not self._operation_current_locked("nexus", operation_sequence)
            ):
                return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)
            self._apply(self._capabilities, records, replace=snapshot.replace)
            self._capability_source_cursor = snapshot.source_cursor
            self._capability_next_cursor = snapshot.next_cursor
            self._event_locked("capabilities", "refreshed", count=len(records))
            return self._page_locked("capabilities", 0, MAX_PAGE_SIZE)

    def refresh_inbox(
        self, *, cursor: str | None = None, page_size: int = MAX_PAGE_SIZE
    ) -> ProjectionPageV6:
        _, page_size = self._page_bounds(0, page_size)
        try:
            cursor = _optional_safe_id(cursor, "cursor")
        except Phase5RuntimeV6ContractError:
            with self._lock:
                if not self._terminated:
                    self._event_locked(
                        "inbox", "cursor_rejected", reason="invalid_cursor"
                    )
            raise
        with self._lock:
            if (
                self._terminated
                or not self._flags.runtime
                or not self._flags.approval_inbox
            ):
                return self._page_locked("inbox", 0, page_size)
            if cursor is None:
                self._inbox.clear()
                self._inbox_cursor_history.clear()
                self._inbox_started = False
                self._inbox_source_cursor = self._inbox_next_cursor = None
                self._inbox_journey += 1
            elif not self._inbox_started or cursor != self._inbox_next_cursor:
                self._event_locked(
                    "inbox", "cursor_rejected", reason="unexpected_cursor"
                )
                raise Phase5RuntimeV6ContractError(
                    "inbox cursor is not the expected continuation"
                )
            if (
                cursor is not None
                and len(self._inbox_cursor_history) >= MAX_CURSOR_HISTORY
            ):
                self._set_failure_locked("inbox", True)
                self._event_locked("inbox", "cursor_limit")
                return self._page_locked("inbox", 0, page_size)
            factory = self._components.inbox_factory
            lease = self._component_lease_locked("inbox")
            operation_sequence = self._next_operation_locked("inbox")
            journey = self._inbox_journey
            binding = _binding(self._binding)
            if factory is None:
                self._set_failure_locked("inbox", True)
                self._event_locked("inbox", "unavailable")
                return self._page_locked("inbox", 0, page_size)
        try:
            reader = factory(binding)
            read_page = getattr(reader, "read_page")
            if not callable(read_page):
                raise Phase5RuntimeV6ContractError("inbox reader has no read_page")
            snapshot, records = self._prepare(
                "inbox",
                read_page(
                    binding=_binding(binding), page_size=page_size, cursor=cursor
                ),
                binding,
            )
            if snapshot.source_cursor != cursor:
                raise Phase5RuntimeV6ContractError("inbox source cursor mismatch")
            if cursor is None and not snapshot.replace:
                raise Phase5RuntimeV6ContractError("first inbox page must replace")
            if cursor is not None and snapshot.replace:
                raise Phase5RuntimeV6ContractError("continuation cannot replace")
            if not records and snapshot.next_cursor is not None:
                raise Phase5RuntimeV6ContractError("empty inbox page cannot continue")
        except BaseException:
            self._record_failure("inbox", lease, operation_sequence)
            return self.inbox(page_size=page_size)
        with self._lock:
            if (
                self._terminated
                or not self._lease_current_locked("inbox", lease)
                or not self._operation_current_locked("inbox", operation_sequence)
                or journey != self._inbox_journey
            ):
                return self._page_locked("inbox", 0, page_size)
            if cursor is not None and cursor in self._inbox_cursor_history:
                self._set_failure_locked("inbox", True)
                self._event_locked(
                    "inbox", "cursor_rejected", reason="repeated_cursor"
                )
                return self._page_locked("inbox", 0, page_size)
            if (
                snapshot.next_cursor is not None
                and snapshot.next_cursor in self._inbox_cursor_history
            ):
                self._set_failure_locked("inbox", True)
                self._event_locked(
                    "inbox", "cursor_rejected", reason="cursor_cycle"
                )
                return self._page_locked("inbox", 0, page_size)
            try:
                self._apply(
                    self._inbox,
                    records,
                    replace=snapshot.replace,
                    forbid_existing=cursor is not None,
                )
            except Phase5RuntimeV6ContractError:
                self._set_failure_locked("inbox", True)
                return self._page_locked("inbox", 0, page_size)
            if cursor is not None:
                self._inbox_cursor_history.add(cursor)
            self._inbox_started = True
            self._inbox_source_cursor = snapshot.source_cursor
            self._inbox_next_cursor = snapshot.next_cursor
            self._event_locked("inbox", "refreshed", count=len(records))
            return self._page_locked("inbox", 0, page_size)

    def recover_component(self, name: str) -> RuntimeStatusV6:
        """Explicitly probe one enabled component and clear only its current failure.

        The probe is executed outside the host lock.  Its generation/identity
        lease is checked again before publishing data or healing state.  A
        concurrent failure that finishes after recovery therefore remains
        sticky, while an old component/configuration can never heal the current
        one.
        """
        if type(name) is not str or name not in _COMPONENTS:
            raise Phase5RuntimeV6ContractError("component is invalid")
        with self._lock:
            self._ensure_active_locked()
            if not self._flags.runtime:
                raise Phase5RuntimeV6Error("runtime is disabled")
            if not self._enabled_component_locked(name):
                raise Phase5RuntimeV6ContractError("component is not enabled")
            component = self._component_callable_locked(name)
            lease = self._component_lease_locked(name)
            operation_sequence = self._next_operation_locked(name)
            failure_observation = self._component_failure_observation[name]
            binding = _binding(self._binding)
            if component is None:
                self._set_failure_locked(name, True)
                self._event_locked("component", "recovery_unavailable", component=name)
                return self._status_locked()

        snapshot: ProjectionBatchV6 | None = None
        records: tuple[ProjectionItemV6, ...] = ()
        try:
            if name == "grant_shadow":
                assert callable(component)
                _advisory(component("phase5-v6-probe"))
            elif name == "nexus":
                assert callable(component)
                snapshot, records = self._prepare(
                    "capabilities", component(binding), binding
                )
            else:
                assert callable(component)
                reader = component(binding)
                read_page = getattr(reader, "read_page")
                if not callable(read_page):
                    raise Phase5RuntimeV6ContractError("inbox reader has no read_page")
                snapshot, records = self._prepare(
                    "inbox",
                    read_page(
                        binding=_binding(binding), page_size=MAX_PAGE_SIZE, cursor=None
                    ),
                    binding,
                )
                if snapshot.source_cursor is not None or not snapshot.replace:
                    raise Phase5RuntimeV6ContractError(
                        "inbox recovery must return a first replacement page"
                    )
                if not records and snapshot.next_cursor is not None:
                    raise Phase5RuntimeV6ContractError(
                        "empty inbox page cannot continue"
                    )
        except BaseException:
            self._record_failure(
                name, lease, operation_sequence, "recovery_failure"
            )
            return self.status()

        with self._lock:
            if (
                self._terminated
                or not self._flags.runtime
                or not self._enabled_component_locked(name)
                or not self._lease_current_locked(name, lease)
                or not self._operation_current_locked(name, operation_sequence)
                or self._component_failure_observation[name]
                != failure_observation
                or binding != self._binding
            ):
                return self._status_locked()
            if name == "nexus":
                assert snapshot is not None
                self._apply(self._capabilities, records, replace=snapshot.replace)
                self._capability_source_cursor = snapshot.source_cursor
                self._capability_next_cursor = snapshot.next_cursor
            elif name == "inbox":
                assert snapshot is not None
                self._inbox.clear()
                self._inbox_cursor_history.clear()
                self._inbox_journey += 1
                self._apply(self._inbox, records, replace=True)
                self._inbox_started = True
                self._inbox_source_cursor = snapshot.source_cursor
                self._inbox_next_cursor = snapshot.next_cursor
            self._set_failure_locked(name, False)
            self._event_locked(
                "component", "recovered", component=name, count=len(records)
            )
            return self._status_locked()

    def _page_locked(self, kind: str, offset: int, page_size: int) -> ProjectionPageV6:
        if kind == "capabilities":
            target = self._capabilities
            source = self._capability_source_cursor
            next_cursor = self._capability_next_cursor
        else:
            target = self._inbox
            source = self._inbox_source_cursor
            next_cursor = self._inbox_next_cursor
        values = tuple(target.values())
        items = tuple(values[offset : offset + page_size])
        next_offset = offset + len(items) if offset + len(items) < len(values) else None
        return ProjectionPageV6(
            kind,
            offset,
            page_size,
            len(values),
            items,
            next_offset,
            source,
            next_cursor,
        )

    def capabilities(
        self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE
    ) -> ProjectionPageV6:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return self._page_locked("capabilities", offset, page_size)

    def inbox(
        self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE
    ) -> ProjectionPageV6:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return self._page_locked("inbox", offset, page_size)

    def dashboard_read(
        self,
        surface: str,
        *,
        offset: int = 0,
        page_size: int = MAX_PAGE_SIZE,
    ) -> RuntimeStatusV6 | ProjectionPageV6 | tuple[RuntimeEventV6, ...]:
        if type(surface) is not str or surface not in {
            "status",
            "capabilities",
            "inbox",
            "events",
        }:
            raise Phase5RuntimeV6ContractError("dashboard surface is not allowlisted")
        with self._lock:
            if not self._flags.runtime or not self._flags.dashboard_projection:
                raise Phase5RuntimeV6Error("dashboard projection is disabled")
        if surface == "status":
            return self.status()
        if surface == "capabilities":
            return self.capabilities(offset=offset, page_size=page_size)
        if surface == "inbox":
            return self.inbox(offset=offset, page_size=page_size)
        return self.events(offset=offset, page_size=page_size)

    def terminate(self, reason: TerminalReasonV6) -> RuntimeStatusV6:
        """Revoke authority now and schedule truthful cooperative cleanup.

        Callback execution is deliberately asynchronous and globally bounded.
        A returned ``TERMINATION_PENDING`` status means at least one callback
        has not actually returned (or its bounded supervisor job could not yet
        be queued).  Arbitrary Python callbacks are not serializable and cannot
        be forcibly cancelled safely; V6 never claims otherwise.
        """
        if type(reason) is not TerminalReasonV6:
            raise Phase5RuntimeV6ContractError("terminal reason must be exact")
        with self._terminal_condition:
            if self._termination_complete:
                return self._status_locked()
            if self._termination_running:
                self._try_submit_termination_locked()
                return self._status_locked()
            self._termination_running = True
            self._terminated = True
            self._terminal_reason = reason.value
            self._retire_locked(configuration=True)
            self._component_failures.clear()
            self._event_locked(
                "lifecycle", "termination_pending", reason=reason.value
            )
            self._termination_callbacks = tuple(
                (name, callback)
                for name, callback in (
                    ("grant", self._components.grant_terminator),
                    ("nexus", self._components.nexus_terminator),
                    ("inbox", self._components.inbox_terminator),
                    ("rollback", self._components.rollback_callback),
                )
                if callback is not None
            )
            self._termination_pending_callbacks = {
                name for name, _callback in self._termination_callbacks
            }
            if not self._termination_callbacks:
                self._finish_termination_locked(set())
            else:
                self._try_submit_termination_locked()
            return self._status_locked()

    def _try_submit_termination_locked(self) -> bool:
        if (
            not self._termination_running
            or self._termination_complete
            or self._termination_job_submitted
            or not self._termination_callbacks
        ):
            return self._termination_job_submitted
        accepted = _TERMINATION_SUPERVISOR.submit(self._run_termination_callbacks)
        if accepted:
            self._termination_job_submitted = True
            return True
        if "supervisor_queue_saturated" not in self._termination_failures:
            self._termination_failures.add("supervisor_queue_saturated")
            self._event_locked(
                "lifecycle",
                "termination_queue_saturated",
                reason="supervisor_queue_saturated",
            )
        return False

    def _run_termination_callbacks(self) -> None:
        failures: set[str] = set()
        _TERMINATION_LOCAL.runtime_id = id(self)
        try:
            with self._lock:
                callbacks = self._termination_callbacks
                reason = self._terminal_reason or TerminalReasonV6.SHUTDOWN.value
            for name, callback in callbacks:
                try:
                    callback(reason)
                except BaseException:
                    failures.add(name)
                finally:
                    with self._lock:
                        self._termination_pending_callbacks.discard(name)
        except BaseException:
            failures.add("host")
        finally:
            try:
                del _TERMINATION_LOCAL.runtime_id
            except AttributeError:
                pass
            with self._terminal_condition:
                self._finish_termination_locked(failures)

    def _finish_termination_locked(self, failures: set[str]) -> None:
        self._termination_failures.update(failures)
        self._termination_running = False
        self._termination_complete = True
        self._termination_callbacks = ()
        self._termination_pending_callbacks.clear()
        if failures:
            self._event_locked(
                "lifecycle",
                "termination_callback_failure",
                reason=",".join(sorted(failures)),
            )
        self._event_locked(
            "lifecycle", "terminated", reason=self._terminal_reason or "terminated"
        )
        self._terminal_condition.notify_all()

    def await_termination(self, timeout: float | None = None) -> RuntimeStatusV6:
        """Wait on the condition once requested by a caller; never poll.

        Calls made from this runtime's own callback return pending immediately,
        which makes nested terminate/await flows bounded and deadlock-free.
        """
        if timeout is None:
            timeout = self._termination_callback_timeout_seconds
        if (
            type(timeout) not in {int, float}
            or type(timeout) is bool
            or not math.isfinite(float(timeout))
            or not 0.0 <= float(timeout) <= 300.0
        ):
            raise Phase5RuntimeV6ContractError("termination timeout is invalid")
        timeout = float(timeout)
        with self._terminal_condition:
            if not self._termination_running:
                return self._status_locked()
            if getattr(_TERMINATION_LOCAL, "runtime_id", None) == id(self):
                return self._status_locked()
            self._try_submit_termination_locked()
            deadline = time.monotonic() + timeout
            while self._termination_running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    pending_names = set(self._termination_pending_callbacks)
                    self._termination_timeouts.update(pending_names or {"supervisor"})
                    self._event_locked(
                        "lifecycle",
                        "termination_wait_timeout",
                        reason=",".join(sorted(pending_names or {"supervisor"})),
                    )
                    break
                self._terminal_condition.wait(remaining)
            return self._status_locked()

    def kill(self) -> RuntimeStatusV6:
        return self.terminate(TerminalReasonV6.KILL)

    def revoke(self) -> RuntimeStatusV6:
        return self.terminate(TerminalReasonV6.REVOKE)

    def rollback(self) -> RuntimeStatusV6:
        return self.terminate(TerminalReasonV6.ROLLBACK)

    def end_session(self) -> RuntimeStatusV6:
        return self.terminate(TerminalReasonV6.END_SESSION)

    def reconnect(self) -> RuntimeStatusV6:
        return self.terminate(TerminalReasonV6.RECONNECT)

    def shutdown(self) -> RuntimeStatusV6:
        return self.terminate(TerminalReasonV6.SHUTDOWN)


__all__ = [
    "PHASE5_RUNTIME_FLAG",
    "PHASE5_GRANT_SHADOW_FLAG",
    "PHASE5_APPROVAL_INBOX_FLAG",
    "PHASE5_LOW_RISK_FLAG",
    "PHASE5_NEXUS_PROJECTION_FLAG",
    "PHASE5_LOCAL_CATALOG_READ_FLAG",
    "PHASE5_DASHBOARD_PROJECTION_FLAG",
    "MAX_PROJECTION_ITEMS",
    "MAX_PAGE_SIZE",
    "MAX_EVENTS",
    "MAX_DECISION_SEALS",
    "MAX_CURSOR_HISTORY",
    "MAX_TERMINATION_WORKERS",
    "MAX_TERMINATION_QUEUE",
    "MAX_JSON_BYTES",
    "MAX_JSON_NODES",
    "MAX_FANOUT",
    "ActionRequestV6",
    "ApprovalInboxReaderV6",
    "Phase5RuntimeV6",
    "Phase5RuntimeV6ContractError",
    "Phase5RuntimeV6Error",
    "ProjectionBatchV6",
    "ProjectionItemV6",
    "ProjectionPageV6",
    "RuntimeBindingV6",
    "RuntimeComponentsV6",
    "RuntimeDecisionV6",
    "RuntimeDispositionV6",
    "RuntimeEventV6",
    "RuntimeFlagsV6",
    "RuntimeStateV6",
    "RuntimeStatusV6",
    "TerminalReasonV6",
]
