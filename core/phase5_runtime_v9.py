"""Host-owned Phase 5 integration core (isolated V9 candidate).

This module is deliberately not imported by a live/startup surface.  V9 keeps
the V1--V6 authority envelope while adding Unicode-aware DLP and a host-owned
termination handshake.  The core never invokes cleanup callbacks and creates
no worker, queue, timer, polling loop, provider or side effect.  Authority is
revoked synchronously; when cleanup is required the host receives an immutable
bounded :class:`TerminationPlanV9` and acknowledges its opaque single-use
actions explicitly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import threading
import time
import unicodedata
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Protocol, TypeVar


PHASE5_RUNTIME_FLAG = "ONYX_PHASE5_RUNTIME_V9"
PHASE5_GRANT_SHADOW_FLAG = "ONYX_PHASE5_GRANT_SHADOW_V9"
PHASE5_APPROVAL_INBOX_FLAG = "ONYX_PHASE5_APPROVAL_INBOX_V9"
PHASE5_LOW_RISK_FLAG = "ONYX_PHASE5_LOW_RISK_V9"
PHASE5_NEXUS_PROJECTION_FLAG = "ONYX_PHASE5_NEXUS_PROJECTION_V9"
PHASE5_LOCAL_CATALOG_READ_FLAG = "ONYX_PHASE5_LOCAL_CATALOG_READ_V9"
PHASE5_DASHBOARD_PROJECTION_FLAG = "ONYX_PHASE5_DASHBOARD_PROJECTION_V9"

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
MAX_TERMINATION_ACTIONS = 4
MAX_CROSS_FIELD_SCAN_BYTES = 8_192

_NORMAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_UUID_HYPHEN_ID = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z"
)
_UUID_COMPACT_ID = re.compile(r"[0-9A-Fa-f]{32}\Z")
_ULID_ID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}\Z", re.IGNORECASE)
_HASH_ID = re.compile(r"(?:[0-9A-Fa-f]{32}|[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64}|[0-9A-Fa-f]{96}|[0-9A-Fa-f]{128})\Z")
_CREDENTIAL_SHAPED_ID = re.compile(
    r"(?:"
    r"sk-(?:proj-)?[A-Za-z0-9_-]*|"
    r"gh[pousr]_[A-Za-z0-9]*|github_pat_[A-Za-z0-9_]*|"
    r"AKIA[A-Za-z0-9._:-]*|AIza[A-Za-z0-9._:-]*|"
    r"(?:bearer|basic)[._:-][A-Za-z0-9._~+/=-]+|"
    r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}"
    r")\Z",
    re.IGNORECASE,
)
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
_COMPACT_SECRET = re.compile(
    r"(?:apikey|authorization|authcode|cookie|password|privatekey|clientsecret|"
    r"accesstoken|refreshtoken|secret|secretkey|sessioncookie|credential|token)"
    r"[a-z0-9]{8,}",
    re.IGNORECASE,
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
_TERMINATION_ACTION_NAMES = ("grant", "nexus", "inbox", "rollback")
_BIDI_UNSAFE = frozenset(
    {
        "LRE",
        "RLE",
        "LRO",
        "RLO",
        "PDF",
        "LRI",
        "RLI",
        "FSI",
        "PDI",
    }
)

# A deliberately small, auditable skeleton for the Greek/Cyrillic glyphs most
# often used to disguise Latin credential labels.  It is applied only to DLP
# shadows: user-facing text is never silently transliterated.
_CONFUSABLE_TO_LATIN = str.maketrans(
    {
        # Cyrillic
        "а": "a", "А": "a", "в": "b", "В": "b", "с": "c", "С": "c",
        "е": "e", "Е": "e", "н": "h", "Н": "h", "і": "i", "І": "i",
        "ј": "j", "Ј": "j", "к": "k", "К": "k", "м": "m", "М": "m",
        "о": "o", "О": "o", "р": "p", "Р": "p", "т": "t", "Т": "t",
        "х": "x", "Х": "x", "у": "y", "У": "y", "ѕ": "s", "Ѕ": "s",
        "ӏ": "l", "Ӏ": "l",
        # Greek
        "α": "a", "Α": "a", "β": "b", "Β": "b", "ϲ": "c", "Ϲ": "c",
        "ε": "e", "Ε": "e", "η": "h", "Η": "h", "ι": "i", "Ι": "i",
        "κ": "k", "Κ": "k", "μ": "m", "Μ": "m", "ν": "v", "Ν": "v",
        "ο": "o", "Ο": "o", "ρ": "p", "Ρ": "p", "τ": "t", "Τ": "t",
        "υ": "y", "Υ": "y", "χ": "x", "Χ": "x", "ζ": "z", "Ζ": "z",
    }
)
_ID_HASH_CONTEXTS = frozenset(
    {
        "trace_id", "session_id", "workspace_id", "account_id", "profile_id",
        "invocation_ref", "capability_id", "item_id", "request_ref", "grant_id",
        "scope_digest", "action_digest", "source_cursor", "next_cursor", "cursor",
    }
)


class Phase5RuntimeV9Error(RuntimeError):
    """Base error for the isolated V9 runtime core."""


class Phase5RuntimeV9ContractError(ValueError):
    """A value violated the closed and bounded V9 host contract."""


class RuntimeDispositionV9(str, Enum):
    FALLBACK = "FALLBACK"
    ALLOW_LOCAL_CATALOG_READ = "ALLOW_LOCAL_CATALOG_READ"
    EXPLICIT = "EXPLICIT"


class RuntimeStateV9(str, Enum):
    DISABLED = "DISABLED"
    READY = "READY"
    DEGRADED = "DEGRADED"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    # Compatibility spelling for callers compiled against the V5 vocabulary.
    TERMINATING = "TERMINATION_PENDING"
    TERMINATION_ERROR = "TERMINATION_ERROR"
    TERMINATED = "TERMINATED"


class TerminalReasonV9(str, Enum):
    KILL = "kill"
    REVOKE = "revoke"
    ROLLBACK = "rollback"
    END_SESSION = "end_session"
    RECONNECT = "reconnect"
    SHUTDOWN = "shutdown"


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise Phase5RuntimeV9ContractError(f"{label} must be an exact boolean")
    return value


def _safe_id(value: object, label: str) -> str:
    """Validate a closed identifier context without generic secret guessing.

    UUID (hyphenated or compact), ULID and allowlisted digest contexts have
    explicit grammars.  Ordinary identifiers use the conservative ASCII
    grammar.  Entropy, generic hex and generic base32 scanners are intentionally
    *not* applied to identifiers; credential *labels* and Unicode spoofing are.
    """
    if type(value) is not str or not value:
        raise Phase5RuntimeV9ContractError(f"{label} is invalid")
    normalized = unicodedata.normalize("NFKC", value)
    if (
        _has_unsafe_unicode(value)
        or _has_unsafe_unicode(normalized)
        or _has_risky_mixed_scripts(value)
        or _has_risky_mixed_scripts(normalized)
    ):
        raise Phase5RuntimeV9ContractError(f"{label} contains unsafe Unicode")
    special = bool(
        _UUID_HYPHEN_ID.fullmatch(normalized)
        or _UUID_COMPACT_ID.fullmatch(normalized)
        or _ULID_ID.fullmatch(normalized)
        or _HASH_ID.fullmatch(normalized)
    )
    if special and label not in _ID_HASH_CONTEXTS:
        raise Phase5RuntimeV9ContractError(f"{label} does not allow opaque IDs")
    if not special and not _NORMAL_ID.fullmatch(normalized):
        raise Phase5RuntimeV9ContractError(f"{label} is invalid")
    if _contains_credential_label(value) or _CREDENTIAL_SHAPED_ID.fullmatch(normalized):
        raise Phase5RuntimeV9ContractError(f"{label} is a credential label")
    return normalized


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


def _has_unsafe_unicode(value: str) -> bool:
    """Reject controls, format/invisible characters and bidi overrides.

    Printable non-ASCII text remains valid.  NFKC handles width and canonical
    compatibility forms, while the scan shadows below neutralize combining and
    separator confusables without mutating user-facing text.
    """
    return any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs"}
        or unicodedata.bidirectional(char) in _BIDI_UNSAFE
        for char in value
    )


def _script_group(char: str) -> str | None:
    if not char.isalpha():
        return None
    name = unicodedata.name(char, "")
    for script in ("LATIN", "GREEK", "CYRILLIC"):
        if script in name:
            return script
    return "OTHER"


def _has_risky_mixed_scripts(value: str) -> bool:
    """Reject Latin/Greek/Cyrillic mixtures used for visual spoofing."""
    scripts = {group for char in value if (group := _script_group(char)) is not None}
    confusable_scripts = scripts & {"LATIN", "GREEK", "CYRILLIC"}
    return len(confusable_scripts) > 1


def _confusable_skeleton(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    pieces: list[str] = []
    for char in normalized.translate(_CONFUSABLE_TO_LATIN):
        category = unicodedata.category(char)
        if category.startswith("M") or category[0] in {"P", "S", "Z"}:
            continue
        pieces.append(char)
    return "".join(pieces)


def _scan_shadows(value: str) -> tuple[str, str, str, str]:
    """Return original, normalized, collapsed and homoglyph-skeleton views."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    # NFKD makes decorated letters visible to the scanner.  Combining marks,
    # punctuation, symbols and separators disappear, exposing labels split as
    # ``a.p.i＿k-e-y`` without changing the user-facing value.
    expanded = unicodedata.normalize("NFKD", normalized)
    pieces: list[str] = []
    for char in expanded:
        category = unicodedata.category(char)
        if category.startswith("M") or category[0] in {"P", "S", "Z"}:
            continue
        pieces.append(char)
    collapsed = "".join(pieces)
    return value, normalized, collapsed, _confusable_skeleton(value)


def _contains_credential_label(value: str) -> bool:
    """Recognize credential semantics, including separator/homoglyph disguises."""
    compact_labels = (
        "apikey",
        "authorization",
        "authcode",
        "cookie",
        "credential",
        "password",
        "passphrase",
        "privatekey",
        "sessioncookie",
        "accesskey",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
        "secret",
        "secretkey",
        "token",
    )
    for shadow in _scan_shadows(value):
        if _SENSITIVE_KEY.search(shadow):
            return True
        if re.search(r"(?:^|\b)" + _SECRET_LABEL + r"(?:$|\b)", shadow, re.I):
            return True
        compact = _confusable_skeleton(shadow)
        if compact in compact_labels or any(
            compact.startswith(label) and len(compact) - len(label) >= 8
            for label in compact_labels
        ):
            return True
    return False


def _base32_candidate_is_sensitive(match: re.Match[str], shadow: str) -> bool:
    token = match.group(0)
    if _shannon_entropy(token.casefold().rstrip("=")) < 3.25:
        return False
    prefix = shadow[max(0, match.start() - 48) : match.start()]
    labelled = bool(re.search(_SECRET_LABEL + r"[\s:=_-]*\Z", prefix, re.I))
    encoded_shape = (
        any(char in "234567=" for char in token) or token.rstrip("=").isupper()
    )
    return labelled or encoded_shape


def _contains_sensitive_value(value: str) -> bool:
    """Central value DLP used by every admitted string surface.

    Besides known credential families, reject bounded high-entropy tokens.  The
    entropy branch deliberately requires a long, space-free token containing
    letters and digits plus at least one delimiter/case transition so ordinary
    prose, timestamps and short product identifiers remain usable.
    """
    for shadow in _scan_shadows(value):
        if (
            _SENSITIVE_VALUE.search(shadow)
            or _NATURAL_LANGUAGE_SECRET.search(shadow)
            or _JWT_SECRET.search(shadow)
            or _HEX_SECRET.search(shadow)
            or _COMPACT_SECRET.search(shadow)
        ):
            return True
        if any(
            _base32_candidate_is_sensitive(match, shadow)
            for match in _BASE32_SECRET.finditer(shadow)
        ):
            return True
        for match in _ENTROPY_TOKEN.finditer(shadow):
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
        or _has_unsafe_unicode(value)
        or _has_risky_mixed_scripts(value)
    ):
        raise Phase5RuntimeV9ContractError(f"{label} is invalid")
    return value


def _text(
    value: object, label: str, maximum: int = MAX_TEXT, *, redact: bool = True
) -> str:
    value = _bounded_text(value, label, maximum)
    if _contains_sensitive_value(value):
        if redact:
            return "[REDACTED]"
        raise Phase5RuntimeV9ContractError(f"{label} contains sensitive data")
    return value


def _flag(raw: object) -> bool:
    return type(raw) is str and raw.strip().casefold() in {"1", "true"}


@dataclass(frozen=True, slots=True)
class RuntimeFlagsV9:
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
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> RuntimeFlagsV9:
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
class RuntimeBindingV9:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _safe_id(getattr(self, name), name))


def _binding(value: object) -> RuntimeBindingV9:
    if type(value) is not RuntimeBindingV9:
        raise Phase5RuntimeV9ContractError("binding must be exact RuntimeBindingV9")
    return RuntimeBindingV9(
        value.trace_id,
        value.session_id,
        value.workspace_id,
        value.account_id,
        value.profile_id,
    )


def _flags(value: object) -> RuntimeFlagsV9:
    if type(value) is not RuntimeFlagsV9:
        raise Phase5RuntimeV9ContractError("flags must be exact RuntimeFlagsV9")
    return RuntimeFlagsV9(**dict(value.payload()))


@dataclass(frozen=True, slots=True)
class ActionRequestV9:
    invocation_ref: str
    binding: RuntimeBindingV9
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
            raise Phase5RuntimeV9ContractError("cost_micro is invalid")
        if self.risk not in _RISKS:
            raise Phase5RuntimeV9ContractError("risk is invalid")
        if type(self.action_classes) is not tuple or len(self.action_classes) > 32:
            raise Phase5RuntimeV9ContractError("action_classes is invalid")
        classes = tuple(
            _safe_id(item, "action_class").casefold() for item in self.action_classes
        )
        if len(classes) != len(set(classes)):
            raise Phase5RuntimeV9ContractError("action_classes contains duplicates")
        object.__setattr__(self, "action_classes", tuple(sorted(classes)))


def _action(value: object) -> ActionRequestV9:
    if type(value) is not ActionRequestV9:
        raise Phase5RuntimeV9ContractError("action must be exact ActionRequestV9")
    return ActionRequestV9(
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
class RuntimeDecisionV9:
    disposition: RuntimeDispositionV9
    reason: str
    trace_id: str
    epoch: int
    advisory_json: str = "{}"

    def __post_init__(self) -> None:
        if type(self.disposition) is not RuntimeDispositionV9:
            raise Phase5RuntimeV9ContractError("decision disposition is invalid")
        _text(self.reason, "reason", 128, redact=False)
        _safe_id(self.trace_id, "trace_id")
        if type(self.epoch) is not int or self.epoch < 1:
            raise Phase5RuntimeV9ContractError("decision epoch is invalid")
        if (
            type(self.advisory_json) is not str
            or len(self.advisory_json.encode()) > MAX_EVENT_TEXT_BYTES
        ):
            raise Phase5RuntimeV9ContractError("advisory_json is invalid")
        try:
            parsed = json.loads(self.advisory_json)
        except json.JSONDecodeError as exc:
            raise Phase5RuntimeV9ContractError("advisory_json is invalid") from exc
        if type(parsed) is not dict or set(parsed) - {
            "outcome",
            "reason",
            "grant_id",
            "scope_digest",
            "action_digest",
        }:
            raise Phase5RuntimeV9ContractError("advisory_json schema is invalid")
        normalized = _normalize_advisory(parsed)
        encoded = json.dumps(
            normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        if len(encoded.encode()) > MAX_EVENT_TEXT_BYTES:
            raise Phase5RuntimeV9ContractError("advisory_json is invalid")
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
            raise Phase5RuntimeV9ContractError("JSON budget exceeded")


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
        raise Phase5RuntimeV9ContractError("JSON nesting is too deep")
    budget.add()
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if not -MAX_INTEGER <= value <= MAX_INTEGER:
            raise Phase5RuntimeV9ContractError("JSON integer is out of bounds")
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
            raise Phase5RuntimeV9ContractError(
                "JSON contains a cycle or shared container"
            )
        budget.seen.add(identity)
    if type(value) in {list, tuple}:
        if len(value) > MAX_FANOUT:
            raise Phase5RuntimeV9ContractError("JSON sequence fanout exceeded")
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
            raise Phase5RuntimeV9ContractError("JSON object fanout exceeded")
        result: dict[str, object] = {}
        for key, item in value.items():
            normalized_key = (
                unicodedata.normalize("NFKC", key) if type(key) is str else ""
            )
            if (
                type(key) is not str
                or not key
                or _has_unsafe_unicode(key)
                or len(normalized_key.encode()) > 128
                or any(_SENSITIVE_KEY.search(shadow) for shadow in _scan_shadows(key))
            ):
                raise Phase5RuntimeV9ContractError("JSON key is unsafe")
            budget.add(nodes=0, bytes_=len(normalized_key.encode()))
            if normalized_key in result:
                raise Phase5RuntimeV9ContractError("JSON keys collide after NFKC")
            result[normalized_key] = _json_value(
                item,
                depth=depth + 1,
                budget=budget,
                screen_content=screen_content,
            )
        return result
    raise Phase5RuntimeV9ContractError("JSON contains a non-JSON value")


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProjectionBatchV9:
    items: tuple[Mapping[str, object], ...]
    replace: bool = True
    source_cursor: str | None = None
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.items) is not tuple or len(self.items) > MAX_PAGE_SIZE:
            raise Phase5RuntimeV9ContractError("projection batch is invalid")
        normalized: list[Mapping[str, object]] = []
        budget = _Budget()
        for item in self.items:
            if type(item) not in {dict, MappingProxyType}:
                raise Phase5RuntimeV9ContractError(
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
            raise Phase5RuntimeV9ContractError("projection cursor does not advance")


def _batch(value: object) -> ProjectionBatchV9:
    if type(value) is not ProjectionBatchV9:
        raise Phase5RuntimeV9ContractError("component returned the wrong batch type")
    budget = _Budget()
    return ProjectionBatchV9(
        tuple(
            dict(_json_value(item, budget=budget, screen_content=False))
            for item in value.items
        ),
        replace=value.replace,
        source_cursor=value.source_cursor,
        next_cursor=value.next_cursor,
    )


class ApprovalInboxReaderV9(Protocol):
    def read_page(
        self,
        *,
        binding: RuntimeBindingV9,
        page_size: int,
        cursor: str | None,
    ) -> ProjectionBatchV9: ...


@dataclass(frozen=True, slots=True)
class RuntimeComponentsV9:
    grant_evaluator: Callable[[str], object] | None = None
    nexus_projector: Callable[[RuntimeBindingV9], ProjectionBatchV9] | None = None
    inbox_factory: Callable[[RuntimeBindingV9], ApprovalInboxReaderV9] | None = None
    termination_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("grant_evaluator", "nexus_projector", "inbox_factory"):
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise Phase5RuntimeV9ContractError(f"{name} must be callable")
        if (
            type(self.termination_actions) is not tuple
            or len(self.termination_actions) > MAX_TERMINATION_ACTIONS
            or any(
                type(name) is not str or name not in _TERMINATION_ACTION_NAMES
                for name in self.termination_actions
            )
            or len(set(self.termination_actions)) != len(self.termination_actions)
            or tuple(
                name
                for name in _TERMINATION_ACTION_NAMES
                if name in self.termination_actions
            )
            != self.termination_actions
        ):
            raise Phase5RuntimeV9ContractError("termination_actions is invalid")


def _components(value: object) -> RuntimeComponentsV9:
    if type(value) is not RuntimeComponentsV9:
        raise Phase5RuntimeV9ContractError(
            "components must be exact RuntimeComponentsV9"
        )
    return RuntimeComponentsV9(
        **{name: getattr(value, name) for name in value.__dataclass_fields__}
    )


@dataclass(frozen=True, slots=True)
class ProjectionItemV9:
    item_id: str
    payload_json: str

    def payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        assert type(value) is dict
        return value


@dataclass(frozen=True, slots=True)
class ProjectionPageV9:
    kind: str
    offset: int
    page_size: int
    total: int
    items: tuple[ProjectionItemV9, ...]
    next_offset: int | None
    source_cursor: str | None
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class RuntimeEventV9:
    sequence: int
    kind: str
    outcome: str
    component: str | None = None
    count: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeStatusV9:
    state: RuntimeStateV9
    reason: str
    epoch: int
    binding: RuntimeBindingV9
    flags: tuple[tuple[str, bool], ...]
    capability_count: int
    inbox_count: int
    event_count: int
    component_failures: tuple[str, ...]
    termination_failures: tuple[str, ...]
    termination_timeouts: tuple[str, ...]
    failure_observations: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class TerminationActionV9:
    """Opaque cleanup request.  Only the host knows how to perform it."""

    action: str
    token: str
    runtime_id: str
    epoch: int
    reason: str


@dataclass(frozen=True, slots=True)
class TerminationPlanV9:
    """Immutable, bounded cleanup plan issued once per runtime."""

    runtime_id: str
    epoch: int
    reason: str
    actions: tuple[TerminationActionV9, ...]


@dataclass(frozen=True, slots=True)
class _DecisionSealV9:
    decision: RuntimeDecisionV9
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


def _binding_digest(value: RuntimeBindingV9) -> str:
    return _digest(
        [
            value.trace_id,
            value.session_id,
            value.workspace_id,
            value.account_id,
            value.profile_id,
        ]
    )


def _flags_digest(value: RuntimeFlagsV9) -> str:
    return _digest(value.payload())


def _action_digest(value: ActionRequestV9) -> str:
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


def _decision_digest(value: RuntimeDecisionV9) -> str:
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


def _cross_field_sensitive(
    raw: Mapping[str, object],
    *,
    label_fields: tuple[str, ...],
    value_fields: tuple[str, ...],
) -> bool:
    """Detect credential meaning split between closed schema roles.

    Every label/value pair is examined; long values are not exempt.  Scanning
    is nevertheless bounded independently of attacker-controlled input.  Each
    field contributes at most its normal text allowance and all shadows share
    one cumulative byte budget.
    """

    remaining = MAX_CROSS_FIELD_SCAN_BYTES

    def admitted_prefix(value: str) -> str:
        nonlocal remaining
        if remaining <= 0:
            return ""
        pieces: list[str] = []
        used = 0
        # MAX_TEXT is the largest normal string-field allowance in this module.
        field_budget = min(MAX_TEXT, remaining)
        for char in value:
            size = len(char.encode("utf-8"))
            if used + size > field_budget:
                break
            pieces.append(char)
            used += size
        remaining -= used
        return "".join(pieces)

    labels = [
        admitted_prefix(raw[name])
        for name in label_fields
        if type(raw.get(name)) is str
    ]
    values = [
        admitted_prefix(raw[name])
        for name in value_fields
        if type(raw.get(name)) is str
    ]
    for item in labels:
        assert type(item) is str
        if _contains_credential_label(item):
            return True
    # Pairwise and aggregate views catch e.g. label="api key", value="abc123"
    # and labels split as display_name="api", provider="key".
    aggregate = " ".join(labels)
    if aggregate and _contains_credential_label(aggregate):
        return True
    for label in labels:
        for value in values:
            # A complete secret label already present in the value is handled
            # by the value surface's ordinary redact/reject policy.  This guard
            # is specifically for meaning created only by joining field roles.
            if not _contains_credential_label(value) and _contains_credential_label(
                f"{label}={value}"
            ):
                return True
    return False


def _redact_cross_field_values(
    raw: Mapping[str, object],
    *,
    label_fields: tuple[str, ...],
    value_fields: tuple[str, ...],
) -> dict[str, object]:
    clean = dict(raw)
    if _cross_field_sensitive(
        clean, label_fields=label_fields, value_fields=value_fields
    ):
        for name in (*label_fields, *value_fields):
            if type(clean.get(name)) is str:
                clean[name] = "[REDACTED]"
    return clean


def _closed_capability(
    raw: Mapping[str, object], binding: RuntimeBindingV9
) -> tuple[str, dict[str, object]]:
    if set(raw) != _CAPABILITY_FIELDS:
        raise Phase5RuntimeV9ContractError("capability schema fields are invalid")
    raw = _redact_cross_field_values(
        raw,
        label_fields=("display_name", "provider"),
        value_fields=("limitation",),
    )
    identifier = _safe_id(raw["capability_id"], "capability_id")
    operations = raw["operations"]
    if type(operations) not in {tuple, list} or not 1 <= len(operations) <= 16:
        raise Phase5RuntimeV9ContractError("capability operations are invalid")
    clean_operations = tuple(_safe_id(item, "operation") for item in operations)
    if len(clean_operations) != len(set(clean_operations)):
        raise Phase5RuntimeV9ContractError("capability operations contain duplicates")
    status = _text(raw["status"], "status", 32, redact=False)
    if status not in _CAPABILITY_STATUS:
        raise Phase5RuntimeV9ContractError("capability status is invalid")
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
    raw: Mapping[str, object], binding: RuntimeBindingV9
) -> tuple[str, dict[str, object]]:
    if set(raw) != _INBOX_FIELDS:
        raise Phase5RuntimeV9ContractError("inbox schema fields are invalid")
    raw = _redact_cross_field_values(
        raw,
        label_fields=("capability", "operation"),
        value_fields=("summary",),
    )
    identifier = _safe_id(raw["item_id"], "item_id")
    risk = _text(raw["risk"], "risk", 16, redact=False)
    state = _text(raw["state"], "state", 16, redact=False)
    if risk not in _RISKS or state not in _INBOX_STATE:
        raise Phase5RuntimeV9ContractError("inbox enum is invalid")
    created_at = _text(raw["created_at"], "created_at", 32, redact=False)
    if not _RFC3339_UTC.fullmatch(created_at):
        raise Phase5RuntimeV9ContractError("created_at is invalid")
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
    surface: str, raw: Mapping[str, object], binding: RuntimeBindingV9
) -> ProjectionItemV9:
    identifier, payload = (
        _closed_capability(raw, binding)
        if surface == "capabilities"
        else _closed_inbox(raw, binding)
    )
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if len(encoded.encode()) > MAX_PROJECTION_ROW_BYTES:
        raise Phase5RuntimeV9ContractError("projection row is too large")
    return ProjectionItemV9(identifier, encoded)


def _normalize_advisory(raw: Mapping[str, object]) -> dict[str, object]:
    """Apply DLP according to each field's closed semantic role."""
    if set(raw) - {
        "outcome",
        "reason",
        "grant_id",
        "scope_digest",
        "action_digest",
    }:
        raise Phase5RuntimeV9ContractError("grant advisory fields are invalid")
    if _cross_field_sensitive(
        raw,
        label_fields=("outcome",),
        value_fields=("reason", "grant_id", "scope_digest", "action_digest"),
    ):
        raise Phase5RuntimeV9ContractError("grant advisory contains sensitive data")
    normalized: dict[str, object] = {}
    for name, item in raw.items():
        if name in {"grant_id", "scope_digest", "action_digest"}:
            normalized[name] = _safe_id(item, name)
        elif type(item) is str:
            normalized[name] = _text(item, name, 128)
        elif type(item) in {int, bool}:
            normalized[name] = _json_value(item)
        else:
            raise Phase5RuntimeV9ContractError("grant advisory field is invalid")
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
                    raise Phase5RuntimeV9ContractError(
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
        raise Phase5RuntimeV9ContractError("grant advisory is too large")
    return encoded


_T = TypeVar("_T")


class Phase5RuntimeV9:
    """Bounded event-driven host extension with no autonomous execution."""

    def __init__(
        self,
        *,
        binding: RuntimeBindingV9,
        flags: RuntimeFlagsV9 | None = None,
        components: RuntimeComponentsV9 | None = None,
        termination_wait_timeout_seconds: float = 1.0,
    ) -> None:
        if (
            type(termination_wait_timeout_seconds) not in {int, float}
            or type(termination_wait_timeout_seconds) is bool
            or not math.isfinite(float(termination_wait_timeout_seconds))
            or not 0.001 <= float(termination_wait_timeout_seconds) <= 30.0
        ):
            raise Phase5RuntimeV9ContractError(
                "termination_wait_timeout_seconds is invalid"
            )
        self._binding = _binding(binding)
        self._flags = _flags(flags or RuntimeFlagsV9.from_environ())
        self._components = _components(components or RuntimeComponentsV9())
        self._lock = threading.RLock()
        self._terminal_condition = threading.Condition(self._lock)
        self._config_generation = 1
        # A component generation describes its effective binding/configuration,
        # not an individual call.  Unrelated/no-op configuration must not make
        # an in-flight failure disappear.
        self._component_generation = {name: 1 for name in _COMPONENTS}
        self._component_operation_sequence = {name: 0 for name in _COMPONENTS}
        self._component_failure_observation = {name: 0 for name in _COMPONENTS}
        # Termination material is fully constructed before runtime authority is
        # created.  If entropy/token construction is unavailable, initialization
        # fails and no READY instance can exist.  A runtime terminates once, so
        # the first (and only) monotonically increasing termination id is 1.
        self._runtime_id = secrets.token_hex(16)
        if type(self._runtime_id) is not str or len(self._runtime_id) != 32:
            raise Phase5RuntimeV9Error("termination token material is unavailable")
        # The host boundary is a fixed four-step cleanup contract.  Component
        # enablement cannot narrow it: disabled paths are acknowledged as host
        # no-ops, which prevents a malformed configuration from yielding a
        # falsely actionless TERMINATED state.
        self._termination_actions_declaration = self._components.termination_actions
        requested_actions = _TERMINATION_ACTION_NAMES
        plan_templates: dict[str, TerminationPlanV9] = {}
        pending_templates: dict[str, OrderedDict[str, TerminationActionV9]] = {}
        for terminal_reason in TerminalReasonV9:
            actions: list[TerminationActionV9] = []
            for action in requested_actions:
                nonce = secrets.token_hex(16)
                signature = secrets.token_hex(32)
                if (
                    type(nonce) is not str
                    or len(nonce) != 32
                    or type(signature) is not str
                    or len(signature) != 64
                ):
                    raise Phase5RuntimeV9Error(
                        "termination token material is unavailable"
                    )
                token = ".".join(
                    (self._runtime_id, "1", action, nonce, signature)
                )
                actions.append(
                    TerminationActionV9(
                        action, token, self._runtime_id, 1, terminal_reason.value
                    )
                )
            immutable_actions = tuple(actions)
            if (
                len(immutable_actions) != len(requested_actions)
                or len({item.token for item in immutable_actions})
                != len(immutable_actions)
            ):
                raise Phase5RuntimeV9Error("termination plan construction failed")
            plan_templates[terminal_reason.value] = TerminationPlanV9(
                self._runtime_id, 1, terminal_reason.value, immutable_actions
            )
            pending_templates[terminal_reason.value] = OrderedDict(
                (item.token, item) for item in immutable_actions
            )
        self._termination_plan_templates = MappingProxyType(plan_templates)
        self._termination_pending_templates = MappingProxyType(pending_templates)
        self._termination_action_names = requested_actions
        self._termination_id = 0

        self._authority_epoch = 1
        self._inbox_journey = 0
        self._terminated = False
        self._termination_complete = False
        self._termination_wait_timeout_seconds = float(termination_wait_timeout_seconds)
        self._termination_plan: TerminationPlanV9 | None = None
        self._termination_pending: OrderedDict[str, TerminationActionV9] = OrderedDict()
        self._termination_acknowledged: set[str] = set()
        self._terminal_reason: str | None = None
        # Failure includes UNVERIFIED.  It is intentionally sticky and can be
        # removed only by recover_component after a successful current-generation
        # probe.  Ordinary refresh/evaluation never heals authority implicitly.
        self._component_failures: set[str] = {
            name for name in _COMPONENTS if self._enabled_component_locked(name)
        }
        self._termination_failures: set[str] = set()
        self._termination_timeouts: set[str] = set()
        self._capabilities: OrderedDict[str, ProjectionItemV9] = OrderedDict()
        self._inbox: OrderedDict[str, ProjectionItemV9] = OrderedDict()
        self._capability_source_cursor: str | None = None
        self._capability_next_cursor: str | None = None
        self._inbox_source_cursor: str | None = None
        self._inbox_next_cursor: str | None = None
        self._inbox_started = False
        self._inbox_cursor_history: set[str] = set()
        self._events: deque[RuntimeEventV9] = deque(maxlen=MAX_EVENTS)
        self._event_sequence = 0
        self._decision_seals: OrderedDict[int, _DecisionSealV9] = OrderedDict()
        self._decision_key = secrets.token_bytes(32)

    @property
    def binding(self) -> RuntimeBindingV9:
        with self._lock:
            return _binding(self._binding)

    @property
    def flags(self) -> RuntimeFlagsV9:
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
        if _cross_field_sensitive(
            {
                "kind": kind,
                "outcome": outcome,
                "component": component,
                "reason": reason,
            },
            label_fields=("kind", "outcome", "component"),
            value_fields=("reason",),
        ):
            raise Phase5RuntimeV9ContractError("event contains sensitive data")
        kind = _safe_id(kind, "event kind")
        outcome = _safe_id(outcome, "event outcome")
        component = (
            None if component is None else _safe_id(component, "event component")
        )
        if count is not None and (
            type(count) is not int or not 0 <= count <= MAX_PROJECTION_ITEMS
        ):
            raise Phase5RuntimeV9ContractError("event count is invalid")
        reason = (
            None
            if reason is None
            else _text(reason, "event reason", MAX_EVENT_TEXT_BYTES)
        )
        self._event_sequence += 1
        self._events.append(
            RuntimeEventV9(
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

    def rebind(self, binding: RuntimeBindingV9) -> RuntimeStatusV9:
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

    def configure_flags(self, flags: RuntimeFlagsV9) -> RuntimeStatusV9:
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

    def replace_components(self, components: RuntimeComponentsV9) -> RuntimeStatusV9:
        snapshot = _components(components)
        with self._lock:
            self._ensure_active_locked()
            if snapshot.termination_actions != self._termination_actions_declaration:
                raise Phase5RuntimeV9ContractError(
                    "termination_actions are immutable after initialization"
                )
            fields = tuple(snapshot.__dataclass_fields__)
            if all(
                getattr(snapshot, name) is getattr(self._components, name)
                for name in fields
            ):
                return self._status_locked()
            previous = self._components
            self._components = snapshot
            component_fields = {
                "grant_shadow": ("grant_evaluator",),
                "nexus": ("nexus_projector",),
                "inbox": ("inbox_factory",),
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
            raise Phase5RuntimeV9Error("runtime is terminated")

    def _enabled_component_locked(self, name: str) -> bool:
        return {
            "grant_shadow": self._flags.grant_shadow,
            "nexus": self._flags.nexus_projection,
            "inbox": self._flags.approval_inbox,
        }[name]

    def _state_locked(self) -> RuntimeStateV9:
        if self._terminated and "TERMINATION_ERROR" in self._termination_failures:
            return RuntimeStateV9.TERMINATION_ERROR
        if self._terminated and not self._termination_complete:
            return RuntimeStateV9.TERMINATION_PENDING
        if self._termination_complete:
            return RuntimeStateV9.TERMINATED
        if not self._flags.runtime:
            return RuntimeStateV9.DISABLED
        if any(
            self._enabled_component_locked(name)
            and (
                name in self._component_failures
                or self._component_callable_locked(name) is None
            )
            for name in _COMPONENTS
        ):
            return RuntimeStateV9.DEGRADED
        return RuntimeStateV9.READY

    def _status_locked(self) -> RuntimeStatusV9:
        state = self._state_locked()
        reason = (
            self._terminal_reason
            if self._terminated
            else (
                "feature_flag_off"
                if state is RuntimeStateV9.DISABLED
                else "component_failure"
                if state is RuntimeStateV9.DEGRADED
                else "ready"
            )
        )
        return RuntimeStatusV9(
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

    def status(self) -> RuntimeStatusV9:
        with self._lock:
            return self._status_locked()

    @staticmethod
    def _page_bounds(offset: int, page_size: int) -> tuple[int, int]:
        if type(offset) is not int or not 0 <= offset <= MAX_PROJECTION_ITEMS:
            raise Phase5RuntimeV9ContractError("offset is invalid")
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise Phase5RuntimeV9ContractError("page_size is invalid")
        return offset, page_size

    def events(
        self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE
    ) -> tuple[RuntimeEventV9, ...]:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return tuple(self._events)[offset : offset + page_size]

    def _set_failure_locked(self, name: str, failed: bool) -> None:
        if name not in _COMPONENTS:
            raise Phase5RuntimeV9ContractError("component is invalid")
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
        raise Phase5RuntimeV9ContractError("component is invalid")

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
    def _contains_explicit(action: ActionRequestV9) -> bool:
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
        disposition: RuntimeDispositionV9,
        reason: str,
        advisory: str = "{}",
        *,
        request_digest: str | None = None,
        publish: bool = True,
    ) -> RuntimeDecisionV9:
        decision = RuntimeDecisionV9(
            disposition, reason, self._binding.trace_id, self._authority_epoch, advisory
        )
        if not publish:
            return decision
        self._event_locked("decision", disposition.value, reason=reason)
        if disposition is RuntimeDispositionV9.ALLOW_LOCAL_CATALOG_READ:
            if request_digest is None:
                raise Phase5RuntimeV9ContractError(
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
            self._decision_seals[id(decision)] = _DecisionSealV9(
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

    def evaluate(self, action: ActionRequestV9) -> RuntimeDecisionV9:
        with self._lock:
            if self._terminated:
                return self._decision_locked(
                    RuntimeDispositionV9.EXPLICIT, "runtime_terminated"
                )
            if not self._flags.runtime:
                return self._decision_locked(
                    RuntimeDispositionV9.FALLBACK, "feature_flag_off", publish=False
                )
            try:
                snapshot = _action(action)
            except (AttributeError, Phase5RuntimeV9ContractError):
                return self._decision_locked(
                    RuntimeDispositionV9.EXPLICIT, "invalid_action_contract"
                )
            if self._contains_explicit(snapshot):
                return self._decision_locked(
                    RuntimeDispositionV9.EXPLICIT, "explicit_action_class"
                )
            if not self._flags.low_risk or not self._flags.local_catalog_read:
                return self._decision_locked(
                    RuntimeDispositionV9.FALLBACK, "extension_path_off", publish=False
                )
            if snapshot.binding != self._binding:
                return self._decision_locked(
                    RuntimeDispositionV9.EXPLICIT, "scope_mismatch"
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
                    RuntimeDispositionV9.EXPLICIT, "not_exact_local_catalog_read"
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
                    RuntimeDispositionV9.EXPLICIT, "component_unverified_or_failed"
                )
            observer = (
                self._components.grant_evaluator if self._flags.grant_shadow else None
            )
            if self._flags.grant_shadow and observer is None:
                self._set_failure_locked("grant_shadow", True)
                return self._decision_locked(
                    RuntimeDispositionV9.EXPLICIT, "grant_shadow_unavailable"
                )
            config_lease = self._config_generation
            component_lease = (
                self._component_lease_locked("grant_shadow")
                if observer is not None
                else None
            )
            operation_sequence = (
                self._next_operation_locked("grant_shadow")
                if observer is not None
                else None
            )

        advisory = "{}"
        if observer is not None:
            try:
                advisory = _advisory(observer(snapshot.invocation_ref))
            except BaseException:
                assert component_lease is not None
                assert operation_sequence is not None
                self._record_failure(
                    "grant_shadow", component_lease, operation_sequence
                )
                with self._lock:
                    return self._decision_locked(
                        RuntimeDispositionV9.EXPLICIT, "grant_shadow_failure"
                    )

        with self._lock:
            if self._terminated or config_lease != self._config_generation:
                return self._decision_locked(
                    RuntimeDispositionV9.EXPLICIT, "authority_revoked_during_evaluation"
                )
            if component_lease is not None:
                if not self._lease_current_locked("grant_shadow", component_lease):
                    return self._decision_locked(
                        RuntimeDispositionV9.EXPLICIT, "evaluation_superseded"
                    )
                assert operation_sequence is not None
                if not self._operation_current_locked(
                    "grant_shadow", operation_sequence
                ):
                    return self._decision_locked(
                        RuntimeDispositionV9.EXPLICIT, "evaluation_superseded"
                    )
            if any(
                self._enabled_component_locked(name)
                for name in self._component_failures
            ):
                return self._decision_locked(
                    RuntimeDispositionV9.EXPLICIT, "component_failure_during_evaluation"
                )
            return self._decision_locked(
                RuntimeDispositionV9.ALLOW_LOCAL_CATALOG_READ,
                "exact_provider_free_catalog_read",
                advisory,
                request_digest=_action_digest(snapshot),
            )

    def legacy_or_decision(
        self, action: ActionRequestV9, legacy: Callable[[], _T]
    ) -> _T | RuntimeDecisionV9:
        if not callable(legacy):
            raise Phase5RuntimeV9ContractError("legacy fallback must be callable")
        decision = self.evaluate(action)
        return (
            legacy()
            if decision.disposition is RuntimeDispositionV9.FALLBACK
            else decision
        )

    def _current_locked(
        self, decision: RuntimeDecisionV9, action: ActionRequestV9
    ) -> bool:
        if (
            type(decision) is not RuntimeDecisionV9
            or type(action) is not ActionRequestV9
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
            decision.disposition is RuntimeDispositionV9.ALLOW_LOCAL_CATALOG_READ
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
        self, decision: RuntimeDecisionV9, action: ActionRequestV9 | None = None
    ) -> bool:
        """Deprecated one-argument use fails closed; request binding is mandatory."""
        if action is None:
            return False
        with self._lock:
            return self._current_locked(decision, action)

    def consume_decision(
        self, decision: RuntimeDecisionV9, action: ActionRequestV9
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
        batch: ProjectionBatchV9,
        binding: RuntimeBindingV9,
    ) -> tuple[ProjectionBatchV9, tuple[ProjectionItemV9, ...]]:
        snapshot = _batch(batch)
        records = tuple(_record(surface, item, binding) for item in snapshot.items)
        if len({record.item_id for record in records}) != len(records):
            raise Phase5RuntimeV9ContractError(
                "projection page contains duplicate identifiers"
            )
        return snapshot, records

    @staticmethod
    def _apply(
        target: OrderedDict[str, ProjectionItemV9],
        records: tuple[ProjectionItemV9, ...],
        *,
        replace: bool,
        forbid_existing: bool = False,
    ) -> None:
        if forbid_existing and any(record.item_id in target for record in records):
            raise Phase5RuntimeV9ContractError(
                "projection repeats an earlier identifier"
            )
        if replace:
            target.clear()
        for record in records:
            target.pop(record.item_id, None)
            target[record.item_id] = record
        while len(target) > MAX_PROJECTION_ITEMS:
            target.popitem(last=False)

    def refresh_capabilities(self) -> ProjectionPageV9:
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
    ) -> ProjectionPageV9:
        _, page_size = self._page_bounds(0, page_size)
        try:
            cursor = _optional_safe_id(cursor, "cursor")
        except Phase5RuntimeV9ContractError:
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
                raise Phase5RuntimeV9ContractError(
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
                raise Phase5RuntimeV9ContractError("inbox reader has no read_page")
            snapshot, records = self._prepare(
                "inbox",
                read_page(
                    binding=_binding(binding), page_size=page_size, cursor=cursor
                ),
                binding,
            )
            if snapshot.source_cursor != cursor:
                raise Phase5RuntimeV9ContractError("inbox source cursor mismatch")
            if cursor is None and not snapshot.replace:
                raise Phase5RuntimeV9ContractError("first inbox page must replace")
            if cursor is not None and snapshot.replace:
                raise Phase5RuntimeV9ContractError("continuation cannot replace")
            if not records and snapshot.next_cursor is not None:
                raise Phase5RuntimeV9ContractError("empty inbox page cannot continue")
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
                self._event_locked("inbox", "cursor_rejected", reason="repeated_cursor")
                return self._page_locked("inbox", 0, page_size)
            if (
                snapshot.next_cursor is not None
                and snapshot.next_cursor in self._inbox_cursor_history
            ):
                self._set_failure_locked("inbox", True)
                self._event_locked("inbox", "cursor_rejected", reason="cursor_cycle")
                return self._page_locked("inbox", 0, page_size)
            try:
                self._apply(
                    self._inbox,
                    records,
                    replace=snapshot.replace,
                    forbid_existing=cursor is not None,
                )
            except Phase5RuntimeV9ContractError:
                self._set_failure_locked("inbox", True)
                return self._page_locked("inbox", 0, page_size)
            if cursor is not None:
                self._inbox_cursor_history.add(cursor)
            self._inbox_started = True
            self._inbox_source_cursor = snapshot.source_cursor
            self._inbox_next_cursor = snapshot.next_cursor
            self._event_locked("inbox", "refreshed", count=len(records))
            return self._page_locked("inbox", 0, page_size)

    def recover_component(self, name: str) -> RuntimeStatusV9:
        """Explicitly probe one enabled component and clear only its current failure.

        The probe is executed outside the host lock.  Its generation/identity
        lease is checked again before publishing data or healing state.  A
        concurrent failure that finishes after recovery therefore remains
        sticky, while an old component/configuration can never heal the current
        one.
        """
        if type(name) is not str or name not in _COMPONENTS:
            raise Phase5RuntimeV9ContractError("component is invalid")
        with self._lock:
            self._ensure_active_locked()
            if not self._flags.runtime:
                raise Phase5RuntimeV9Error("runtime is disabled")
            if not self._enabled_component_locked(name):
                raise Phase5RuntimeV9ContractError("component is not enabled")
            component = self._component_callable_locked(name)
            lease = self._component_lease_locked(name)
            operation_sequence = self._next_operation_locked(name)
            failure_observation = self._component_failure_observation[name]
            binding = _binding(self._binding)
            if component is None:
                self._set_failure_locked(name, True)
                self._event_locked("component", "recovery_unavailable", component=name)
                return self._status_locked()

        snapshot: ProjectionBatchV9 | None = None
        records: tuple[ProjectionItemV9, ...] = ()
        try:
            if name == "grant_shadow":
                assert callable(component)
                _advisory(component("phase5-v9-probe"))
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
                    raise Phase5RuntimeV9ContractError("inbox reader has no read_page")
                snapshot, records = self._prepare(
                    "inbox",
                    read_page(
                        binding=_binding(binding), page_size=MAX_PAGE_SIZE, cursor=None
                    ),
                    binding,
                )
                if snapshot.source_cursor is not None or not snapshot.replace:
                    raise Phase5RuntimeV9ContractError(
                        "inbox recovery must return a first replacement page"
                    )
                if not records and snapshot.next_cursor is not None:
                    raise Phase5RuntimeV9ContractError(
                        "empty inbox page cannot continue"
                    )
        except BaseException:
            self._record_failure(name, lease, operation_sequence, "recovery_failure")
            return self.status()

        with self._lock:
            if (
                self._terminated
                or not self._flags.runtime
                or not self._enabled_component_locked(name)
                or not self._lease_current_locked(name, lease)
                or not self._operation_current_locked(name, operation_sequence)
                or self._component_failure_observation[name] != failure_observation
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

    def _page_locked(self, kind: str, offset: int, page_size: int) -> ProjectionPageV9:
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
        return ProjectionPageV9(
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
    ) -> ProjectionPageV9:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return self._page_locked("capabilities", offset, page_size)

    def inbox(
        self, *, offset: int = 0, page_size: int = MAX_PAGE_SIZE
    ) -> ProjectionPageV9:
        offset, page_size = self._page_bounds(offset, page_size)
        with self._lock:
            return self._page_locked("inbox", offset, page_size)

    def dashboard_read(
        self,
        surface: str,
        *,
        offset: int = 0,
        page_size: int = MAX_PAGE_SIZE,
    ) -> RuntimeStatusV9 | ProjectionPageV9 | tuple[RuntimeEventV9, ...]:
        if type(surface) is not str or surface not in {
            "status",
            "capabilities",
            "inbox",
            "events",
        }:
            raise Phase5RuntimeV9ContractError("dashboard surface is not allowlisted")
        with self._lock:
            if not self._flags.runtime or not self._flags.dashboard_projection:
                raise Phase5RuntimeV9Error("dashboard projection is disabled")
        if surface == "status":
            return self.status()
        if surface == "capabilities":
            return self.capabilities(offset=offset, page_size=page_size)
        if surface == "inbox":
            return self.inbox(offset=offset, page_size=page_size)
        return self.events(offset=offset, page_size=page_size)

    def terminate(self, reason: TerminalReasonV9) -> RuntimeStatusV9:
        """Revoke authority synchronously and publish one host-owned plan.

        The closed ``termination_actions`` declaration contains names only;
        this core never receives cleanup callables.  The host maps each opaque
        action name to its own cleanup path and
        acknowledges the corresponding single-use token.  Until every action
        is acknowledged the runtime truthfully remains ``TERMINATION_PENDING``
        and rejects new work.  There is deliberately no implicit deadline or
        abandonment policy that could pretend external cleanup happened.
        """
        if type(reason) is not TerminalReasonV9:
            raise Phase5RuntimeV9ContractError("terminal reason must be exact")
        with self._terminal_condition:
            if self._terminated:
                return self._status_locked()

            # Fail closed first.  From this line onward every decision seal is
            # stale and no component/configuration path can publish authority.
            self._terminated = True
            self._terminal_reason = reason.value
            self._termination_id += 1
            # Install the complete host-readable plan immediately after the
            # authoritative fail-closed bit.  Even a fault in retirement or
            # telemetry below therefore cannot produce an actionless transition.
            self._termination_plan = self._termination_plan_templates[reason.value]
            self._termination_pending = self._termination_pending_templates[
                reason.value
            ]
            try:
                self._retire_locked(configuration=True)
                self._component_failures.clear()
                if self._termination_plan.actions:
                    self._event_locked(
                        "lifecycle",
                        "termination_pending",
                        count=len(self._termination_plan.actions),
                        reason=reason.value,
                    )
                else:
                    self._finish_termination_locked()
            except Exception:
                # Authority is already revoked and the complete constant plan is
                # already host-readable.  Never restore READY or publish a
                # falsely complete TERMINATED state after an internal fault.
                self._termination_complete = False
                self._termination_failures.add("TERMINATION_ERROR")
            return self._status_locked()

    def termination_plan(self) -> TerminationPlanV9 | None:
        """Return the original immutable plan, including acknowledged actions."""
        with self._lock:
            return self._termination_plan

    def pending_termination_actions(self) -> tuple[TerminationActionV9, ...]:
        """Return the bounded outstanding host-owned actions in plan order."""
        with self._lock:
            return tuple(self._termination_pending.values())

    def _validate_termination_token_locked(self, token: object) -> TerminationActionV9:
        if type(token) is not str or not 1 <= len(token) <= 256:
            raise Phase5RuntimeV9ContractError("termination token is invalid")
        if token in self._termination_acknowledged:
            raise Phase5RuntimeV9ContractError("termination token was already used")
        item = self._termination_pending.get(token)
        if item is None:
            raise Phase5RuntimeV9ContractError("termination token is unknown")
        if (
            item.runtime_id != self._runtime_id
            or item.epoch != self._termination_id
            or item.reason != self._terminal_reason
        ):
            raise Phase5RuntimeV9ContractError("termination token binding is invalid")
        return item

    def ack_termination_action(
        self,
        token: str,
        *,
        success: bool,
        error: str | None = None,
    ) -> RuntimeStatusV9:
        """Commit one host cleanup result; tokens cannot be forged or replayed."""
        success = _exact_bool(success, "termination success")
        if success and error is not None:
            raise Phase5RuntimeV9ContractError(
                "successful termination acknowledgement cannot include error"
            )
        clean_error = (
            None
            if error is None
            else _text(error, "termination error", MAX_EVENT_TEXT_BYTES)
        )
        if not success and clean_error is None:
            clean_error = "host_reported_failure"
        with self._terminal_condition:
            item = self._validate_termination_token_locked(token)
            del self._termination_pending[token]
            self._termination_acknowledged.add(token)
            if success:
                self._event_locked(
                    "lifecycle",
                    "termination_action_acknowledged",
                    component=item.action,
                )
            else:
                self._termination_failures.add(item.action)
                self._event_locked(
                    "lifecycle",
                    "termination_action_failed",
                    component=item.action,
                    reason=clean_error,
                )
            if not self._termination_pending:
                self._finish_termination_locked()
            return self._status_locked()

    def _finish_termination_locked(self) -> None:
        self._termination_complete = True
        self._event_locked(
            "lifecycle", "terminated", reason=self._terminal_reason or "terminated"
        )
        self._terminal_condition.notify_all()

    def await_termination(self, timeout: float | None = None) -> RuntimeStatusV9:
        """Wait to a monotonic deadline; spurious notifications cannot end it."""
        if timeout is None:
            timeout = self._termination_wait_timeout_seconds
        if (
            type(timeout) not in {int, float}
            or type(timeout) is bool
            or not math.isfinite(float(timeout))
            or not 0.0 <= float(timeout) <= 300.0
        ):
            raise Phase5RuntimeV9ContractError("termination timeout is invalid")
        timeout = float(timeout)
        with self._terminal_condition:
            if not self._terminated or self._termination_complete:
                return self._status_locked()
            deadline = time.monotonic() + timeout
            while not self._termination_complete:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    break
                self._terminal_condition.wait_for(
                    lambda: self._termination_complete,
                    timeout=remaining,
                )
            if not self._termination_complete:
                pending_names = {
                    item.action for item in self._termination_pending.values()
                }
                self._termination_timeouts.update(pending_names)
                self._event_locked(
                    "lifecycle",
                    "termination_wait_timeout",
                    reason=",".join(sorted(pending_names)),
                )
            return self._status_locked()

    def kill(self) -> RuntimeStatusV9:
        return self.terminate(TerminalReasonV9.KILL)

    def revoke(self) -> RuntimeStatusV9:
        return self.terminate(TerminalReasonV9.REVOKE)

    def rollback(self) -> RuntimeStatusV9:
        return self.terminate(TerminalReasonV9.ROLLBACK)

    def end_session(self) -> RuntimeStatusV9:
        return self.terminate(TerminalReasonV9.END_SESSION)

    def reconnect(self) -> RuntimeStatusV9:
        return self.terminate(TerminalReasonV9.RECONNECT)

    def shutdown(self) -> RuntimeStatusV9:
        return self.terminate(TerminalReasonV9.SHUTDOWN)


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
    "MAX_TERMINATION_ACTIONS",
    "MAX_JSON_BYTES",
    "MAX_JSON_NODES",
    "MAX_FANOUT",
    "ActionRequestV9",
    "ApprovalInboxReaderV9",
    "Phase5RuntimeV9",
    "Phase5RuntimeV9ContractError",
    "Phase5RuntimeV9Error",
    "ProjectionBatchV9",
    "ProjectionItemV9",
    "ProjectionPageV9",
    "RuntimeBindingV9",
    "RuntimeComponentsV9",
    "RuntimeDecisionV9",
    "RuntimeDispositionV9",
    "RuntimeEventV9",
    "RuntimeFlagsV9",
    "RuntimeStateV9",
    "RuntimeStatusV9",
    "TerminalReasonV9",
    "TerminationActionV9",
    "TerminationPlanV9",
]
