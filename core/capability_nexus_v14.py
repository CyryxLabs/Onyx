"""Phase 5.3 Capability Nexus V14: isolated, closed-provenance contracts.

V14 supersedes the rejected V1-V13 candidates without importing them. Descriptor
metadata is a closed typed contract, while content scanning remains confined to
free-text/schema surfaces. The module has no live/startup wiring and exposes no
authorization or dispatch operation.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import hmac
import json
import math
import re
import threading
import time
from types import MappingProxyType
from typing import Callable, Mapping, Sequence
import unicodedata
from urllib.parse import quote, unquote, unquote_to_bytes


CAPABILITY_SCHEMA_VERSION_V14 = "onyx.capability.v14"
NEXUS_CONTRACT_VERSION_V14 = "onyx.capability-nexus.v14"
CATALOG_CONTRACT_VERSION_V14 = "onyx.local-catalog.v14"
LOCK_ORDER_V14 = ("gate_immutable_state", "registry_lock", "adapter_lock")


class CapabilityV14ContractError(ValueError):
    pass


class CapabilityV14DeniedError(PermissionError):
    pass


class OperationKindV14(str, Enum):
    READ = "read"
    DRAFT = "draft"
    MUTATE = "mutate"
    VERIFY = "verify"
    RECONCILE = "reconcile"


class CapabilityStatusV14(str, Enum):
    DISABLED = "disabled"
    AVAILABLE_READ_ONLY = "available_read_only"
    DEGRADED = "degraded"
    BLOCKED_BY_ACCESS = "blocked_by_access"
    BLOCKED_BY_SCOPE = "blocked_by_scope"
    BLOCKED_BY_PLATFORM = "blocked_by_platform"
    BLOCKED_BY_LICENSE = "blocked_by_license"


class TransportKindV14(str, Enum):
    LEGACY = "legacy"
    LOCAL = "local"
    API = "api"
    CLI = "cli"
    SDK = "sdk"
    MCP = "mcp"
    BROWSER = "browser"


class ReadStateV14(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    UNCERTAIN = "uncertain"
    CANCELLED_BEFORE_HOOK = "cancelled_before_hook"
    TIMEOUT_BEFORE_HOOK = "timeout_before_hook"
    DENIED = "denied"
    RATE_LIMITED = "rate_limited"
    EXPIRED_UNCERTAIN = "expired_uncertain"
    UNKNOWN_CORRELATION = "unknown_correlation"


class ReadFailureClassV14(str, Enum):
    NONE = "none"
    AUTH = "auth"
    SCOPE = "scope"
    DISABLED = "disabled"
    KILL = "kill"
    REVOKED = "revoked"
    RATE_LIMIT = "rate_limit"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    HOOK_EXCEPTION = "hook_exception"
    LEDGER_CAPACITY = "ledger_capacity"
    QUOTA = "quota"
    EXPIRED_PENDING = "expired_pending"
    UNCERTAIN_EXPIRED = "uncertain_expired"
    UNKNOWN = "unknown"


_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_ALIAS = re.compile(r"^alias:[a-z0-9][a-z0-9._/-]{0,95}$")
_DOMAIN = re.compile(r"^(?:\*\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE|SECRET|TOKEN|KEY)[A-Z0-9 ]*-----")
_SECRET_ASSIGN = re.compile(
    r"(?i)[\"']?(?:api[_.-]?key|api|key|token|access[_.-]?token|refresh[_.-]?token|password|secret|auth|authorization|cookie|private|private[_.-]?key|bearer)[\"']?\s*[:=]\s*[\"']?[^\s,;\"']{4,}"
)
_SECRET_NAMES = frozenset(
    {
        "apikey", "token", "accesstoken", "refreshtoken", "password", "secret",
        "auth", "authorization", "cookie", "privatekey",
    }
)
_METADATA_ENUMS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "data_source": frozenset({"constructor_allowlist", "healthy", "local_catalog"}),
        "dispatch_path": frozenset({"legacy_unchanged"}),
        "fallback_class": frozenset({"explicit_browser_fallback"}),
        "policy_source": frozenset({"trusted_host_mapping"}),
    }
)
_SAFE_METADATA_KEYS = frozenset({*_METADATA_ENUMS, "declaration_sha256"})
_MAX_METADATA_DECODE_DEPTH = 6
_MAX_METADATA_REPRESENTATIONS = 16
_MAX_METADATA_TOTAL_BYTES = 16_384
_MAX_METADATA_VALUE_BYTES = 4_096
_PERCENT = re.compile(r"%(?:[0-9A-Fa-f]{2})")
_RESIDUAL_UNICODE_ESCAPE = re.compile(r"\\u[0-9A-Fa-f]{4}|\\x[0-9A-Fa-f]{2}")
_RAW_CREDENTIAL_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9]{20,200}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9_-])sk-proj-[A-Za-z0-9_-]{20,200}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{20,255}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{22,255}(?![A-Za-z0-9_])"),
    re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    re.compile(r"(?<![A-Za-z0-9_])sk_(?:live|test)_[A-Za-z0-9]{16,200}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9-])xox[baprs]-[A-Za-z0-9]{8,16}-[A-Za-z0-9-]{16,160}(?![A-Za-z0-9-])"),
    re.compile(r"(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9_.-])SG\.[A-Za-z0-9_-]{16,64}\.[A-Za-z0-9_-]{32,128}(?![A-Za-z0-9_.-])"),
    re.compile(r"(?<![A-Za-z0-9])SK[0-9A-Fa-f]{32}(?![A-Za-z0-9])"),
    re.compile(r"(?i)(?<![A-Za-z0-9])bearer[ \t]+[A-Za-z0-9._~+/=-]{16,2048}(?![A-Za-z0-9._~+/=-])"),
)
_BASIC_AUTH = re.compile(r"(?i)(?<![A-Za-z0-9])basic[ \t]+([A-Za-z0-9+/]{8,2048}={0,2})(?![A-Za-z0-9+/=])")
_CONFUSABLES = str.maketrans(
    {
        # Cyrillic lookalikes used by the protected secret vocabulary.
        "а": "a", "в": "b", "с": "c", "е": "e", "һ": "h", "і": "i",
        "ј": "j", "к": "k", "ӏ": "l", "м": "m", "н": "n", "о": "o",
        "р": "p", "ѕ": "s", "т": "t", "у": "y", "х": "x",
        # Greek lookalikes used by the same vocabulary.
        "α": "a", "β": "b", "ϲ": "c", "ε": "e", "η": "n", "ι": "i",
        "κ": "k", "λ": "l", "μ": "m", "ο": "o", "ρ": "p", "σ": "s",
        "τ": "t", "υ": "y", "χ": "x",
        "ᴏ": "o", "օ": "o",
    }
)
_UNSAFE_BIDI = frozenset({"BN", "LRE", "LRO", "RLE", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"})
_STRUCTURED_METADATA = frozenset(":={}[],'\"")
_JSON_FIELD = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$.-]{0,127}$")
_MAX_JSON_DEPTH = 24
_MAX_JSON_NODES = 4096
_MAX_JSON_SCALAR_BYTES = 65_536
_CREDENTIAL_OPAQUE_NAMES = frozenset(
    {"passwd", "bearer", "accesskey", "credential", "credentials", "cred", "creds"}
)
_SAFE_SEMANTIC_PREFIXES = frozenset(
    {"buildartifact", "documentation", "reference", "release", "version", "catalog", "dataset", "source", "model"}
)
_SAFE_WORDLIKE_PROTECTED_IDENTIFIERS = frozenset({"tokenization", "authentication"})
_NATURAL_SHORT_WORDS = frozenset(
    {
        "access", "account", "age", "an", "api", "be", "call", "catalog",
        "city", "commands", "control", "cookies", "data", "do", "english",
        "fact", "for", "future", "identifier", "in", "job", "keys", "language",
        "local", "long", "memory", "metadata", "model", "must", "name",
        "namespace", "never", "not", "oauth", "of", "one", "only", "or",
        "passwords", "plans", "policy", "policies", "private", "projects", "raw",
        "reference", "request", "review", "save", "searches", "source", "standard",
        "standards", "system", "systems", "the", "term", "time", "to", "tokens",
        "tokenization", "authentication", "use", "user", "values", "when", "workflow",
        "worth",
    }
)
_LEXICAL_MODEL_WORDS = tuple(
    "account action adapter allow application approval architecture assistant "
    "authentication authorization available boundary capability catalog character "
    "collaboration command communication configuration context contract control "
    "credential data database declaration descriptor discovery dispatch document "
    "endpoint evidence execution feature governance identifier implementation "
    "integration interface interoperability language local metadata mission model "
    "multidisciplinary namespace natural network operation permission platform policy "
    "profile projection provider readiness reference registry request responsibility "
    "runtime schema security semantic service session snapshot source standard state "
    "storage system target technical telecommunications token tokenization transport "
    "validation version workflow workspace".split()
)
_ENGLISH_BIGRAMS = frozenset(
    word[index:index + 2]
    for word in _LEXICAL_MODEL_WORDS
    for index in range(len(word) - 1)
)
_ENGLISH_TRIGRAMS = frozenset(
    word[index:index + 3]
    for word in _LEXICAL_MODEL_WORDS
    for index in range(len(word) - 2)
)
_SUSPICIOUS_SEQUENCES = (
    "qwertyuiop", "poiuytrewq", "asdfghjkl", "lkjhgfdsa", "zxcvbnm", "mnbvcxz",
    "abcdefghijklmnopqrstuvwxyz", "zyxwvutsrqponmlkjihgfedcba",
)
_NATURAL_SCORE_THRESHOLD = 0.50


def _normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _confusable_skeleton(unquote(value)))


def _confusable_skeleton(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold().translate(_CONFUSABLES)
    return "".join(character for character in decomposed if not unicodedata.category(character).startswith("M"))


def _letter_script(character: str) -> str | None:
    if not character.isalpha():
        return None
    name = unicodedata.name(character, "")
    for script in ("LATIN", "CYRILLIC", "GREEK"):
        if script in name:
            return script
    return "OTHER"


def _has_suspicious_sequence(value: str) -> bool:
    if len(set(value)) <= 3 or re.search(r"(.)\1{4}", value):
        return True
    return any(
        sequence[index:index + 5] in value
        for sequence in _SUSPICIOUS_SEQUENCES
        for index in range(len(sequence) - 4)
    )


def _english_word_score(value: str) -> float:
    """Return a bounded embedded-model score; 0.50 separates held-out prose from opaque fixtures."""
    if not value.isascii() or not value.isalpha() or len(value) < 4 or _has_suspicious_sequence(value):
        return 0.0
    bigrams = tuple(value[index:index + 2] for index in range(len(value) - 1))
    trigrams = tuple(value[index:index + 3] for index in range(len(value) - 2))
    bigram_coverage = sum(item in _ENGLISH_BIGRAMS for item in bigrams) / len(bigrams)
    trigram_coverage = sum(item in _ENGLISH_TRIGRAMS for item in trigrams) / len(trigrams)
    vowel_ratio = sum(character in "aeiouy" for character in value) / len(value)
    consonant_run = max(map(len, re.findall(r"[^aeiouy]+", value)), default=0)
    vowel_groups = len(re.findall(r"[aeiouy]+", value))
    shape_score = (
        0.5 * (0.2 <= vowel_ratio <= 0.65)
        + 0.3 * (consonant_run <= 4)
        + 0.2 * (vowel_groups >= 2)
    )
    return 0.45 * bigram_coverage + 0.40 * trigram_coverage + 0.15 * shape_score


def _natural_lexeme(value: str) -> bool:
    return (
        value in _NATURAL_SHORT_WORDS
        or value in _SAFE_SEMANTIC_PREFIXES
        or _english_word_score(value) >= _NATURAL_SCORE_THRESHOLD
    )


def _protected_name_canary(value: str) -> bool:
    protected = _SECRET_NAMES | _CREDENTIAL_OPAQUE_NAMES
    normalized = unicodedata.normalize("NFKC", unquote(value))
    camel_boundaries = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized)
    camel_boundaries = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", camel_boundaries)
    skeleton = _confusable_skeleton(camel_boundaries)
    raw_segments: list[str] = []
    buffer: list[str] = []
    for character in skeleton:
        if unicodedata.category(character)[0] in {"L", "N"}:
            buffer.append(character)
        elif buffer:
            raw_segments.append("".join(buffer))
            buffer = []
    if buffer:
        raw_segments.append("".join(buffer))
    segments = tuple(filter(None, (_normalized_name(segment) for segment in raw_segments)))
    has_whitespace = any(character.isspace() for character in normalized)
    identifier_context = camel_boundaries != normalized or (
        not has_whitespace
        and any(not character.isalnum() and not character.isspace() for character in normalized)
    )

    def opaque_remainder(parts: tuple[str, ...]) -> bool:
        if identifier_context:
            opaque_parts = tuple(part for part in parts if part and not _natural_lexeme(part))
            return sum(map(len, opaque_parts)) >= 16
        # Prose permits independently natural words but cannot use one to erase
        # opaque chunks in the same credential-shaped side of a protected span.
        opaque_parts = tuple(part for part in parts if part and not _natural_lexeme(part))
        return sum(map(len, opaque_parts)) >= 16 and (
            len(opaque_parts) >= 2
            or any(len(item) >= 16 for item in opaque_parts)
            or any(any(character.isdigit() for character in item) for item in opaque_parts)
        )

    for start in range(len(segments)):
        for end in range(start + 1, len(segments) + 1):
            name = "".join(segments[start:end])
            if name in protected:
                candidate = (*segments[:start], *segments[end:])
                if opaque_remainder(candidate):
                    return True

    # Case-free concatenations have no lexical boundary. A benign word is safe
    # only when its non-protected remainder is natural and no opaque component
    # exists elsewhere; it is never a substring-wide exemption.
    for segment_index, segment in enumerate(segments):
        for name in protected:
            position = segment.find(name)
            while position >= 0:
                safe_container = next(
                    (
                        (safe, safe_start)
                        for safe in _SAFE_WORDLIKE_PROTECTED_IDENTIFIERS
                        for safe_start in (segment.find(safe),)
                        if safe_start >= 0
                        and safe_start <= position
                        and position + len(name) <= safe_start + len(safe)
                    ),
                    None,
                )
                if safe_container is None:
                    local_remainder = segment[:position] + segment[position + len(name):]
                else:
                    safe, safe_start = safe_container
                    local_remainder = segment[:safe_start] + segment[safe_start + len(safe):]
                candidate = (*segments[:segment_index], local_remainder, *segments[segment_index + 1:])
                if opaque_remainder(candidate):
                    return True
                position = segment.find(name, position + 1)
    return False


def _raw_credential_canary(value: str, *, allow_typed_hash: bool = False) -> bool:
    if _protected_name_canary(value):
        return True
    if any(pattern.search(value) for pattern in _RAW_CREDENTIAL_PATTERNS):
        return True
    for match in _BASIC_AUTH.finditer(value):
        token = match.group(1)
        try:
            decoded = base64.b64decode(token, validate=True)
        except ValueError:
            continue
        if 3 <= len(decoded) <= 1024 and b":" in decoded and all(32 <= byte < 127 for byte in decoded):
            return True
    if re.fullmatch(r"[0-9A-Fa-f]{64}", value):
        return not allow_typed_hash
    opaque = re.fullmatch(r"[A-Za-z0-9_-]{32,512}", value)
    if opaque is None:
        return False
    segments = re.split(r"[_-]", value)
    protected = _SECRET_NAMES | _CREDENTIAL_OPAQUE_NAMES
    for split in range(1, len(segments)):
        prefix = _normalized_name("_".join(segments[:split]))
        tail = "".join(segments[split:])
        if prefix in protected and len(tail) >= 16:
            return True
    safe_prefix = _normalized_name(segments[0])
    if (
        len(segments) > 1
        and safe_prefix in _SAFE_SEMANTIC_PREFIXES
        and segments[0].isalpha()
        and all(segment and segment.isalnum() for segment in segments)
    ):
        return False
    classes = sum(
        any(predicate(ch) for ch in value)
        for predicate in (str.islower, str.isupper, str.isdigit)
    )
    if classes < 3:
        return False
    frequencies = {character: value.count(character) for character in set(value)}
    entropy = -sum((count / len(value)) * math.log2(count / len(value)) for count in frequencies.values())
    return entropy >= 4.0


def _secret_canary(value: str) -> bool:
    candidates = {value, unquote(value)}
    for candidate in tuple(candidates):
        compact = re.sub(r"\s+", "", candidate)
        if 8 <= len(compact) <= 4096 and len(compact) % 4 == 0 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact):
            try:
                padded = compact.replace("-", "+").replace("_", "/") + "=" * (-len(compact) % 4)
                decoded = base64.b64decode(padded, validate=False).decode("utf-8")
            except (ValueError, UnicodeError):
                continue
            candidates.add(decoded)
    return any(_SECRET_ASSIGN.search(item) or _JWT.search(item) or _PEM.search(item) for item in candidates)


def _scan_content_representation(value: str, *, allow_typed_hash: bool = False) -> None:
    normalized = unicodedata.normalize("NFKC", value)
    if any(
        (unicodedata.category(ch) == "Cc" and ch not in {"\t", "\n", "\r"})
        or unicodedata.category(ch) in {"Cf", "Cs"}
        or unicodedata.category(ch).startswith("M")
        or unicodedata.bidirectional(ch) in _UNSAFE_BIDI
        for ch in normalized
    ):
        raise CapabilityV14ContractError("content contains unsupported invisible/bidi/combining characters")
    folded = normalized.casefold()
    skeleton = _confusable_skeleton(normalized)
    if (
        _SECRET_ASSIGN.search(folded)
        or _SECRET_ASSIGN.search(skeleton)
        or _JWT.search(normalized)
        or _PEM.search(normalized.upper())
        or _raw_credential_canary(normalized, allow_typed_hash=allow_typed_hash)
        or _raw_credential_canary(skeleton, allow_typed_hash=allow_typed_hash)
    ):
        raise CapabilityV14ContractError("content representation contains secret material")
    if _RESIDUAL_UNICODE_ESCAPE.search(normalized):
        raise CapabilityV14ContractError("content contains residual character encoding")


def _canonical_percent_decode(value: str) -> str | None:
    if "%" not in value:
        return None
    if _PERCENT.sub("", value).find("%") >= 0:
        raise CapabilityV14ContractError("metadata contains malformed percent encoding")
    try:
        decoded = unquote_to_bytes(value).decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise CapabilityV14ContractError("metadata percent encoding is invalid") from exc
    canonical = quote(decoded, safe="-._~/:@")
    normalize_hex = lambda text: re.sub(  # noqa: E731
        r"%[0-9A-Fa-f]{2}", lambda match: match.group(0).upper(), text
    )
    if normalize_hex(canonical) != normalize_hex(value):
        raise CapabilityV14ContractError("metadata percent encoding is noncanonical")
    return decoded if decoded != value else None


def _canonical_base64_decode(value: str) -> str | None:
    compact = value
    if not 8 <= len(compact) <= _MAX_METADATA_VALUE_BYTES or any(ch.isspace() for ch in compact):
        return None
    if ("+" in compact or "/" in compact) and ("-" in compact or "_" in compact):
        raise CapabilityV14ContractError("metadata Base64 alphabet is ambiguous")
    standard = re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", compact) is not None
    urlsafe = re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", compact) is not None
    if not standard and not urlsafe:
        return None
    if len(compact.rstrip("=")) % 4 == 1:
        return None
    padded = compact.rstrip("=") + "=" * (-len(compact.rstrip("=")) % 4)
    try:
        if urlsafe and not standard:
            raw = base64.b64decode(padded, altchars=b"-_", validate=True)
            canonical = base64.urlsafe_b64encode(raw).decode("ascii")
        else:
            raw = base64.b64decode(padded, validate=True)
            canonical = base64.b64encode(raw).decode("ascii")
        decoded = raw.decode("utf-8", errors="strict")
    except (ValueError, UnicodeDecodeError):
        return None
    if canonical.rstrip("=") != compact.rstrip("="):
        raise CapabilityV14ContractError("metadata Base64 encoding is noncanonical")
    if not decoded or any(unicodedata.category(ch) in {"Cc", "Cf", "Cs"} for ch in decoded):
        return None
    return decoded if decoded != value else None


def _validate_content_decoding_closure(value: str, *, allow_typed_hash: bool = False) -> None:
    encoded_size = len(value.encode("utf-8"))
    if encoded_size > _MAX_METADATA_VALUE_BYTES:
        raise CapabilityV14ContractError("content value exceeds decoding byte budget")
    queue: list[tuple[str, int, tuple[str, ...]]] = [(value, 0, ())]
    seen: set[str] = set()
    total_bytes = 0
    while queue:
        current, depth, ancestors = queue.pop(0)
        if current in seen:
            continue
        if current in ancestors:
            raise CapabilityV14ContractError("content decoding cycle detected")
        seen.add(current)
        if len(seen) > _MAX_METADATA_REPRESENTATIONS:
            raise CapabilityV14ContractError("content decoding representation budget exceeded")
        total_bytes += len(current.encode("utf-8"))
        if total_bytes > _MAX_METADATA_TOTAL_BYTES:
            raise CapabilityV14ContractError("content decoding expansion budget exceeded")
        _scan_content_representation(current, allow_typed_hash=allow_typed_hash)
        normalized = unicodedata.normalize("NFKC", current)
        candidates: list[str] = []
        if normalized != current:
            candidates.append(normalized)
        percent = _canonical_percent_decode(current)
        if percent is not None:
            candidates.append(percent)
        decoded64 = _canonical_base64_decode(current)
        if decoded64 is not None:
            candidates.append(decoded64)
        if depth >= _MAX_METADATA_DECODE_DEPTH and candidates:
            raise CapabilityV14ContractError("content decoding depth exceeded")
        for candidate in candidates:
            if candidate in ancestors:
                raise CapabilityV14ContractError("content decoding cycle detected")
            queue.append((candidate, depth + 1, ancestors + (current,)))


def _text(value: object, label: str, maximum: int, *, empty: bool = False) -> str:
    if type(value) is not str or value != value.strip() or (not value and not empty):
        raise CapabilityV14ContractError(f"{label} must be a canonical exact string")
    if len(value) > maximum or any(
        (ord(ch) < 32 and ch not in {"\t", "\n", "\r"}) or ord(ch) == 127 for ch in value
    ):
        raise CapabilityV14ContractError(f"{label} is out of bounds")
    if _secret_canary(value):
        raise CapabilityV14ContractError(f"{label} resembles secret material")
    return value


def _slug(value: object, label: str) -> str:
    result = _text(value, label, 128)
    if not _SLUG.fullmatch(result):
        raise CapabilityV14ContractError(f"{label} is not a canonical slug")
    return result


def _identifier(value: object, label: str) -> str:
    result = _text(value, label, 128)
    if not _IDENT.fullmatch(result):
        raise CapabilityV14ContractError(f"{label} is not a canonical identifier")
    return result


def _strings(value: object, label: str, *, count: int = 32, size: int = 128, required: bool = False) -> tuple[str, ...]:
    if type(value) not in {tuple, list} or len(value) > count or (required and not value):
        raise CapabilityV14ContractError(f"{label} cardinality is invalid")
    result = tuple(_text(item, f"{label} item", size) for item in value)
    if len(set(result)) != len(result):
        raise CapabilityV14ContractError(f"{label} contains duplicates")
    return tuple(sorted(result))


def _reject_json_secrets(
    value: object,
    label: str,
    *,
    _depth: int = 0,
    _active: set[int] | None = None,
    _budget: list[int] | None = None,
) -> None:
    if _depth > _MAX_JSON_DEPTH:
        raise CapabilityV14ContractError(f"{label} exceeds nesting depth")
    active = set() if _active is None else _active
    budget = [0, 0] if _budget is None else _budget
    budget[0] += 1
    if budget[0] > _MAX_JSON_NODES:
        raise CapabilityV14ContractError(f"{label} exceeds node budget")
    if isinstance(value, Mapping):
        if len(value) > 512:
            raise CapabilityV14ContractError(f"{label} is too large")
        identity = id(value)
        if identity in active:
            raise CapabilityV14ContractError(f"{label} contains a cycle")
        active.add(identity)
        try:
            for key, item in value.items():
                key = _text(key, f"{label} key", 128)
                if not _JSON_FIELD.fullmatch(key) or not key.isascii():
                    raise CapabilityV14ContractError(f"{label} key is not a canonical ASCII identifier")
                if _normalized_name(key) in _SECRET_NAMES:
                    raise CapabilityV14ContractError(f"{label} contains a secret-name field")
                _reject_json_secrets(
                    item, f"{label}.{key}", _depth=_depth + 1, _active=active, _budget=budget
                )
        finally:
            active.remove(identity)
    elif isinstance(value, (tuple, list)):
        if len(value) > 512:
            raise CapabilityV14ContractError(f"{label} is too large")
        identity = id(value)
        if identity in active:
            raise CapabilityV14ContractError(f"{label} contains a cycle")
        active.add(identity)
        try:
            for item in value:
                _reject_json_secrets(item, label, _depth=_depth + 1, _active=active, _budget=budget)
        finally:
            active.remove(identity)
    elif isinstance(value, str):
        item = _text(value, label, 32768, empty=True)
        budget[1] += len(item.encode("utf-8"))
        if budget[1] > _MAX_JSON_SCALAR_BYTES:
            raise CapabilityV14ContractError(f"{label} exceeds scalar byte budget")
        _validate_content_decoding_closure(item)
    elif value is not None:
        if type(value) not in {bool, int, float}:
            raise CapabilityV14ContractError(f"{label} contains an unsupported value")
        if type(value) is float and not math.isfinite(value):
            raise CapabilityV14ContractError(f"{label} contains a non-finite number")
        if type(value) is int and not -(2**63) <= value <= 2**63 - 1:
            raise CapabilityV14ContractError(f"{label} integer is out of bounds")


def _json(value: object, label: str, maximum: int = 65536) -> str:
    _reject_json_secrets(value, label)
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CapabilityV14ContractError(f"{label} is not canonical JSON") from exc
    if len(result.encode("utf-8")) > maximum:
        raise CapabilityV14ContractError(f"{label} exceeds its byte budget")
    return result


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _safe_metadata(value: object) -> tuple[tuple[str, str], ...]:
    if type(value) not in {tuple, list} or len(value) > len(_SAFE_METADATA_KEYS):
        raise CapabilityV14ContractError("metadata must be bounded key/value pairs")
    result: list[tuple[str, str]] = []
    for pair in value:
        if type(pair) not in {tuple, list} or len(pair) != 2:
            raise CapabilityV14ContractError("metadata entry is invalid")
        key = pair[0]
        if type(key) is not str or not key.isascii() or key not in _SAFE_METADATA_KEYS:
            raise CapabilityV14ContractError("metadata key is not declared safe")
        item = pair[1]
        if type(item) is not str or not item.isascii() or not item or item != item.strip() or len(item) > 512:
            raise CapabilityV14ContractError(f"metadata {key} is not an exact ASCII atom")
        if key == "declaration_sha256":
            if not _HEX64.fullmatch(item):
                raise CapabilityV14ContractError("declaration_sha256 is invalid")
        elif item not in _METADATA_ENUMS[key]:
            raise CapabilityV14ContractError(f"metadata {key} is outside its closed enum")
        result.append((key, item))
    if len({key for key, _ in result}) != len(result):
        raise CapabilityV14ContractError("metadata key is duplicated")
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class OperationDescriptorV14:
    operation_id: str
    kind: OperationKindV14
    description: str
    parameter_schema_json: str
    required_scopes: tuple[str, ...]
    data_classes: tuple[str, ...]
    risk_class: str
    approval_class: str
    allowed_targets: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    pagination: str = "unsupported"
    rate_limit: str = "host_policy"
    cancellation: str = "bounded"
    timeout: str = "bounded"
    idempotency: str = "correlation_only"
    receipt: str = "read_observation"
    reconciliation: str = "read_state_only"
    quota: str = "unknown"
    cost: str = "unknown"
    dry_run: str = "unsupported"
    test_account: str = "required_before_activation"
    host_policy: str = "always_confirm"

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _slug(self.operation_id, "operation_id"))
        if type(self.kind) is not OperationKindV14:
            raise CapabilityV14ContractError("operation kind must be exact")
        description = _text(self.description, "description", 4096)
        _validate_content_decoding_closure(description)
        object.__setattr__(self, "description", description)
        if type(self.parameter_schema_json) is not str:
            raise CapabilityV14ContractError("parameter schema must be exact string")
        try:
            parsed = json.loads(self.parameter_schema_json)
        except json.JSONDecodeError as exc:
            raise CapabilityV14ContractError("parameter schema is invalid") from exc
        if _json(parsed, "parameter schema") != self.parameter_schema_json:
            raise CapabilityV14ContractError("parameter schema is noncanonical")
        object.__setattr__(self, "required_scopes", _strings(self.required_scopes, "required_scopes"))
        object.__setattr__(self, "data_classes", _strings(self.data_classes, "data_classes", required=True))
        object.__setattr__(self, "allowed_targets", _strings(self.allowed_targets, "allowed_targets"))
        domains = _strings(self.allowed_domains, "allowed_domains", size=253)
        if any(not _DOMAIN.fullmatch(item) or ".." in item for item in domains):
            raise CapabilityV14ContractError("allowed domain is invalid")
        object.__setattr__(self, "allowed_domains", domains)
        for name in (
            "risk_class", "approval_class", "pagination", "rate_limit", "cancellation", "timeout",
            "idempotency", "receipt", "reconciliation", "quota", "cost", "dry_run", "test_account", "host_policy",
        ):
            object.__setattr__(self, name, _slug(getattr(self, name), name))

    def payload(self) -> dict[str, object]:
        return {name: (getattr(self, name).value if isinstance(getattr(self, name), Enum) else list(getattr(self, name)) if isinstance(getattr(self, name), tuple) else getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class CapabilityDescriptorV14:
    capability_id: str
    capability_version: str
    provider: str
    transport: TransportKindV14
    api_name: str
    api_version: str
    workspace_id: str
    account_id: str
    profile_id: str
    credential_alias: str | None
    operations: tuple[OperationDescriptorV14, ...]
    status: CapabilityStatusV14 = CapabilityStatusV14.DISABLED
    status_reason: str = "candidate_not_activated"
    limitations: tuple[str, ...] = ()
    license_review: str = "not_required_local_only"
    metadata: tuple[tuple[str, str], ...] = ()
    schema_version: str = CAPABILITY_SCHEMA_VERSION_V14

    def __post_init__(self) -> None:
        if self.schema_version != CAPABILITY_SCHEMA_VERSION_V14:
            raise CapabilityV14ContractError("unknown descriptor schema")
        for name in ("capability_id", "capability_version", "provider", "api_name", "api_version"):
            object.__setattr__(self, name, _slug(getattr(self, name), name))
        if type(self.transport) is not TransportKindV14 or type(self.status) is not CapabilityStatusV14:
            raise CapabilityV14ContractError("descriptor enum type is invalid")
        for name in ("workspace_id", "account_id", "profile_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.credential_alias is not None and (
            type(self.credential_alias) is not str or not _ALIAS.fullmatch(self.credential_alias)
        ):
            raise CapabilityV14ContractError("credential_alias must be opaque")
        if type(self.operations) not in {tuple, list} or not self.operations or len(self.operations) > 64:
            raise CapabilityV14ContractError("operation cardinality is invalid")
        operations = tuple(self.operations)
        if any(type(item) is not OperationDescriptorV14 for item in operations):
            raise CapabilityV14ContractError("operation descriptor type is invalid")
        if len({item.operation_id for item in operations}) != len(operations):
            raise CapabilityV14ContractError("duplicate operation")
        object.__setattr__(self, "operations", tuple(sorted(operations, key=lambda item: item.operation_id)))
        object.__setattr__(self, "status_reason", _slug(self.status_reason, "status_reason"))
        object.__setattr__(self, "limitations", _strings(self.limitations, "limitations", size=256))
        object.__setattr__(self, "license_review", _slug(self.license_review, "license_review"))
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))
        if self.status is CapabilityStatusV14.DEGRADED and self.status_reason == "healthy":
            raise CapabilityV14ContractError("degraded descriptor requires a reason")
        if self.transport is TransportKindV14.BROWSER and dict(self.metadata).get("fallback_class") != "explicit_browser_fallback":
            raise CapabilityV14ContractError("browser fallback is not explicit")

    def payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id, "api_name": self.api_name, "api_version": self.api_version,
            "capability_id": self.capability_id, "capability_version": self.capability_version,
            "credential_alias": self.credential_alias, "license_review": self.license_review,
            "limitations": list(self.limitations), "metadata": [list(item) for item in self.metadata],
            "operations": [item.payload() for item in self.operations], "profile_id": self.profile_id,
            "provider": self.provider, "schema_version": self.schema_version, "status": self.status.value,
            "status_reason": self.status_reason, "transport": self.transport.value, "workspace_id": self.workspace_id,
        }

    @property
    def digest(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True, slots=True)
class NexusFeatureGateV14:
    nexus_enabled: bool = False
    shadow_mode: bool = True
    dispatch_enabled: bool = False
    contract_version: str = NEXUS_CONTRACT_VERSION_V14

    def __post_init__(self) -> None:
        if type(self.nexus_enabled) is not bool or type(self.shadow_mode) is not bool or type(self.dispatch_enabled) is not bool:
            raise CapabilityV14ContractError("gate values must be exact booleans")
        if self.contract_version != NEXUS_CONTRACT_VERSION_V14:
            raise CapabilityV14ContractError("gate contract version is invalid")
        if self.nexus_enabled or not self.shadow_mode or self.dispatch_enabled:
            raise CapabilityV14ContractError("V14 is strictly default-off and shadow-only")


@dataclass(frozen=True, slots=True)
class CapabilityProjectionV14:
    descriptor: CapabilityDescriptorV14
    descriptor_digest: str
    workspace_id: str
    account_id: str
    profile_id: str
    projection_status: CapabilityStatusV14
    projection_reason: str
    runtime_available: bool = False
    authority_granted: bool = False

    def __post_init__(self) -> None:
        if type(self.descriptor) is not CapabilityDescriptorV14 or self.descriptor_digest != self.descriptor.digest:
            raise CapabilityV14ContractError("projection descriptor binding drift")
        if (
            self.workspace_id != self.descriptor.workspace_id
            or self.account_id != self.descriptor.account_id
            or self.profile_id != self.descriptor.profile_id
        ):
            raise CapabilityV14ContractError("projection identity binding drift")
        if type(self.projection_status) is not CapabilityStatusV14:
            raise CapabilityV14ContractError("projection status is invalid")
        object.__setattr__(self, "projection_reason", _slug(self.projection_reason, "projection_reason"))
        if type(self.runtime_available) is not bool or type(self.authority_granted) is not bool:
            raise CapabilityV14ContractError("projection booleans must be exact")
        if self.runtime_available or self.authority_granted:
            raise CapabilityV14ContractError("V14 projections cannot convey authority")

    def digest_payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "descriptor_digest": self.descriptor_digest,
            "profile_id": self.profile_id,
            "projection_reason": self.projection_reason,
            "projection_status": self.projection_status.value,
            "workspace_id": self.workspace_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilitySnapshotV14:
    workspace_id: str
    account_id: str
    profile_id: str
    entries: tuple[CapabilityProjectionV14, ...]
    snapshot_digest: str
    contract_version: str = NEXUS_CONTRACT_VERSION_V14

    def __post_init__(self) -> None:
        if self.contract_version != NEXUS_CONTRACT_VERSION_V14:
            raise CapabilityV14ContractError("snapshot contract version is invalid")
        for name in ("workspace_id", "account_id", "profile_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if type(self.entries) is not tuple or any(type(item) is not CapabilityProjectionV14 for item in self.entries):
            raise CapabilityV14ContractError("snapshot entries are invalid")
        if any(
            item.workspace_id != self.workspace_id
            or item.account_id != self.account_id
            or item.profile_id != self.profile_id
            for item in self.entries
        ):
            raise CapabilityV14ContractError("snapshot contains a cross-profile projection")
        expected = _sha(
            {
                "account_id": self.account_id,
                "contract_version": self.contract_version,
                "entries": [item.digest_payload() for item in self.entries],
                "profile_id": self.profile_id,
                "workspace_id": self.workspace_id,
            }
        )
        if self.snapshot_digest != expected:
            raise CapabilityV14ContractError("snapshot digest is invalid")


class CapabilityNexusV14:
    """Descriptor-only registry; lock order is gate immutable -> registry."""

    def __init__(self, gate: NexusFeatureGateV14 | None = None) -> None:
        if gate is None:
            gate = NexusFeatureGateV14()
        if type(gate) is not NexusFeatureGateV14:
            raise CapabilityV14ContractError("registry requires the exact concrete V14 gate")
        self._gate = gate
        self._descriptors: dict[str, CapabilityDescriptorV14] = {}
        self._revoked_aliases: set[str] = set()
        self._kill = False
        self._lock = threading.RLock()

    @property
    def gate(self) -> NexusFeatureGateV14:
        return self._gate

    @property
    def lock_order(self) -> tuple[str, ...]:
        return LOCK_ORDER_V14

    def register(self, descriptor: CapabilityDescriptorV14) -> str:
        if type(descriptor) is not CapabilityDescriptorV14:
            raise CapabilityV14ContractError("registry descriptor type is invalid")
        with self._lock:
            if descriptor.capability_id in self._descriptors:
                raise CapabilityV14ContractError("duplicate capability")
            self._descriptors[descriptor.capability_id] = descriptor
            return descriptor.digest

    def revoke_alias(self, alias: str) -> None:
        if type(alias) is not str or not _ALIAS.fullmatch(alias):
            raise CapabilityV14ContractError("credential alias is invalid")
        with self._lock:
            self._revoked_aliases.add(alias)

    def set_kill(self, active: bool) -> None:
        if type(active) is not bool:
            raise CapabilityV14ContractError("kill state must be exact boolean")
        with self._lock:
            self._kill = active

    def discover(
        self,
        capability_id: str,
        *,
        workspace_id: str,
        account_id: str,
        profile_id: str,
        expected_version: str,
        expected_digest: str,
    ) -> CapabilityProjectionV14:
        capability_id = _slug(capability_id, "capability_id")
        workspace_id = _identifier(workspace_id, "workspace_id")
        account_id = _identifier(account_id, "account_id")
        profile_id = _identifier(profile_id, "profile_id")
        expected_version = _slug(expected_version, "expected_version")
        expected_digest = _text(expected_digest, "expected_digest", 64)
        if not _HEX64.fullmatch(expected_digest):
            raise CapabilityV14ContractError("expected digest is invalid")
        with self._lock:
            descriptor = self._descriptors.get(capability_id)
            if descriptor is None:
                raise CapabilityV14DeniedError("unknown capability")
            if (
                descriptor.workspace_id != workspace_id
                or descriptor.account_id != account_id
                or descriptor.profile_id != profile_id
            ):
                raise CapabilityV14DeniedError("workspace/account/profile mismatch")
            if descriptor.capability_version != expected_version or descriptor.digest != expected_digest:
                raise CapabilityV14DeniedError("version or descriptor drift")
            status, reason = self._status(descriptor)
            return CapabilityProjectionV14(
                descriptor, descriptor.digest, workspace_id, account_id, profile_id, status, reason
            )

    def health_projection(self, *args: object, **kwargs: object) -> CapabilityProjectionV14:
        return self.discover(*args, **kwargs)

    def snapshot(self, *, workspace_id: str, account_id: str, profile_id: str) -> CapabilitySnapshotV14:
        workspace_id = _identifier(workspace_id, "workspace_id")
        account_id = _identifier(account_id, "account_id")
        profile_id = _identifier(profile_id, "profile_id")
        with self._lock:
            entries = tuple(
                CapabilityProjectionV14(
                    descriptor,
                    descriptor.digest,
                    workspace_id,
                    account_id,
                    profile_id,
                    *self._status(descriptor),
                )
                for descriptor in sorted(self._descriptors.values(), key=lambda item: item.capability_id)
                if descriptor.workspace_id == workspace_id
                and descriptor.account_id == account_id
                and descriptor.profile_id == profile_id
            )
        payload = {
            "account_id": account_id,
            "contract_version": NEXUS_CONTRACT_VERSION_V14,
            "entries": [item.digest_payload() for item in entries],
            "profile_id": profile_id,
            "workspace_id": workspace_id,
        }
        return CapabilitySnapshotV14(workspace_id, account_id, profile_id, entries, _sha(payload))

    def _status(self, descriptor: CapabilityDescriptorV14) -> tuple[CapabilityStatusV14, str]:
        if self._kill:
            return CapabilityStatusV14.DISABLED, "global_kill_active"
        if descriptor.credential_alias is not None and descriptor.credential_alias in self._revoked_aliases:
            return CapabilityStatusV14.BLOCKED_BY_ACCESS, "credential_alias_revoked"
        if descriptor.status is CapabilityStatusV14.AVAILABLE_READ_ONLY:
            return CapabilityStatusV14.DISABLED, "nexus_default_off_shadow_only"
        return descriptor.status, descriptor.status_reason


@dataclass(frozen=True, slots=True)
class LegacyParityRecordV14:
    tool_name: str
    host_policy: str
    declaration_json: str
    declaration_digest: str


@dataclass(frozen=True, slots=True)
class LegacyDescriptorSetV14:
    descriptors: tuple[CapabilityDescriptorV14, ...]
    parity_records: tuple[LegacyParityRecordV14, ...]
    snapshot_digest: str

    def declarations(self) -> tuple[dict[str, object], ...]:
        return tuple(json.loads(item.declaration_json) for item in self.parity_records)

    def policy_mapping(self) -> Mapping[str, str]:
        return MappingProxyType({item.tool_name: item.host_policy for item in self.parity_records})


def build_legacy_descriptors_v14(
    tool_declarations: Sequence[Mapping[str, object]],
    policy_mapping: Mapping[str, str],
    *,
    workspace_id: str,
    account_id: str,
    profile_id: str,
    operation_kinds: Mapping[str, OperationKindV14] | None = None,
) -> LegacyDescriptorSetV14:
    if type(tool_declarations) not in {tuple, list} or not tool_declarations or len(tool_declarations) > 128:
        raise CapabilityV14ContractError("legacy declarations are invalid")
    if not isinstance(policy_mapping, Mapping):
        raise CapabilityV14ContractError("legacy policy mapping is invalid")
    workspace_id = _identifier(workspace_id, "workspace_id")
    account_id = _identifier(account_id, "account_id")
    profile_id = _identifier(profile_id, "profile_id")
    parsed: list[tuple[str, Mapping[str, object], str]] = []
    seen: set[str] = set()
    for raw in tool_declarations:
        if not isinstance(raw, Mapping) or set(raw) != {"name", "description", "parameters"}:
            raise CapabilityV14ContractError("legacy declaration shape drift")
        name = _slug(raw.get("name"), "tool name")
        if name in seen:
            raise CapabilityV14ContractError("duplicate legacy declaration")
        seen.add(name)
        _text(raw.get("description"), "legacy description", 4096)
        if not isinstance(raw.get("parameters"), Mapping):
            raise CapabilityV14ContractError("legacy parameter schema is invalid")
        encoded = _json(dict(raw), "legacy declaration")
        parsed.append((name, raw, encoded))
    if set(policy_mapping) != seen:
        raise CapabilityV14ContractError("legacy policy coverage is not exact")
    if operation_kinds is not None and set(operation_kinds) != seen:
        raise CapabilityV14ContractError("legacy operation coverage is not exact")
    descriptors: list[CapabilityDescriptorV14] = []
    records: list[LegacyParityRecordV14] = []
    for name, raw, encoded in parsed:
        policy = _slug(policy_mapping[name], "host policy")
        kind = OperationKindV14.MUTATE if operation_kinds is None else operation_kinds[name]
        if type(kind) is not OperationKindV14:
            raise CapabilityV14ContractError("legacy operation kind is invalid")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        operation = OperationDescriptorV14(
            name,
            kind,
            str(raw["description"]),
            _json(raw["parameters"], "parameter schema"),
            (),
            ("legacy_unclassified",),
            "legacy_host_policy",
            policy,
            pagination="legacy_unchanged",
            rate_limit="legacy_unchanged",
            cancellation="legacy_unchanged",
            timeout="legacy_unchanged",
            idempotency="legacy_unchanged",
            receipt="legacy_unchanged",
            reconciliation="legacy_unchanged",
            quota="legacy_unknown",
            cost="legacy_unknown",
            dry_run="legacy_unchanged",
            test_account="legacy_unchanged",
            host_policy=policy,
        )
        descriptors.append(
            CapabilityDescriptorV14(
                f"legacy.{name}", "v14", "onyx_legacy", TransportKindV14.LEGACY,
                "legacy_dispatcher", "unchanged", workspace_id, account_id, profile_id, None,
                (operation,), CapabilityStatusV14.DISABLED, "shadow_descriptor_only",
                ("legacy_behavior_unchanged", "no_authority", "no_dispatch"),
                "existing_runtime_not_relicensed",
                (("declaration_sha256", digest), ("dispatch_path", "legacy_unchanged"), ("policy_source", "trusted_host_mapping")),
            )
        )
        records.append(LegacyParityRecordV14(name, policy, encoded, digest))
    descriptors.sort(key=lambda item: item.capability_id)
    records.sort(key=lambda item: item.tool_name)
    payload = {
        "descriptors": [item.payload() for item in descriptors],
        "records": [
            {"declaration_digest": item.declaration_digest, "declaration_json": item.declaration_json,
             "host_policy": item.host_policy, "tool_name": item.tool_name}
            for item in records
        ],
    }
    return LegacyDescriptorSetV14(tuple(descriptors), tuple(records), _sha(payload))


@dataclass(frozen=True, slots=True)
class CatalogItemV14:
    item_id: str
    label: str
    category: str
    item_version: str
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))
        object.__setattr__(self, "label", _text(self.label, "label", 160))
        object.__setattr__(self, "category", _slug(self.category, "category"))
        object.__setattr__(self, "item_version", _slug(self.item_version, "item_version"))
        object.__setattr__(self, "tags", _strings(self.tags, "tags", count=16, size=48))

    def payload(self) -> dict[str, object]:
        return {"category": self.category, "item_id": self.item_id, "item_version": self.item_version,
                "label": self.label, "tags": list(self.tags)}


@dataclass(frozen=True, slots=True)
class CancellationTokenV14:
    _event: threading.Event = field(default_factory=threading.Event, init=False, repr=False, compare=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class CatalogReadRequestV14:
    workspace_id: str
    account_id: str
    profile_id: str
    target: str
    correlation_id: str
    page_size: int = 25
    cursor: str | None = None
    timeout_ms: int = 1000
    cancellation: CancellationTokenV14 | None = None

    def __post_init__(self) -> None:
        for name in ("workspace_id", "account_id", "profile_id", "target", "correlation_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if type(self.page_size) is not int or not 1 <= self.page_size <= 100:
            raise CapabilityV14ContractError("page_size is invalid")
        if self.cursor is not None:
            object.__setattr__(self, "cursor", _text(self.cursor, "cursor", 2048))
        if type(self.timeout_ms) is not int or not 1 <= self.timeout_ms <= 30_000:
            raise CapabilityV14ContractError("timeout_ms is invalid")
        if self.cancellation is not None and type(self.cancellation) is not CancellationTokenV14:
            raise CapabilityV14ContractError("cancellation token type is invalid")


@dataclass(frozen=True, slots=True)
class ConnectorHealthV14:
    status: CapabilityStatusV14
    reason: str
    workspace_id: str
    account_id: str
    profile_id: str
    api_version: str
    required_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...]
    quota_remaining: int
    ledger_entries: int
    pending_entries: int
    uncertain_entries: int
    cost_micros: int = 0
    authority_granted: bool = False


@dataclass(frozen=True, slots=True)
class CatalogReadProjectionV14:
    state: ReadStateV14
    failure_class: ReadFailureClassV14
    correlation_id: str
    request_digest: str
    workspace_id: str
    account_id: str
    profile_id: str
    items: tuple[CatalogItemV14, ...]
    next_cursor: str | None
    receipt_digest: str | None
    quota_remaining: int
    retry_after_ms: int | None = None
    authority_granted: bool = False

    def __post_init__(self) -> None:
        if type(self.state) is not ReadStateV14 or type(self.failure_class) is not ReadFailureClassV14:
            raise CapabilityV14ContractError("read projection enum is invalid")
        if self.authority_granted or type(self.authority_granted) is not bool:
            raise CapabilityV14ContractError("read projection cannot grant authority")
        if self.state is not ReadStateV14.COMPLETED and self.items:
            raise CapabilityV14ContractError("non-completed projection cannot expose items")
        if self.state is ReadStateV14.COMPLETED and (
            self.failure_class is not ReadFailureClassV14.NONE or self.receipt_digest is None
        ):
            raise CapabilityV14ContractError("completed projection is incomplete")


@dataclass(frozen=True, slots=True)
class _ReadLedgerEntryV14:
    request_digest: str
    workspace_id: str
    account_id: str
    profile_id: str
    state: ReadStateV14
    failure_class: ReadFailureClassV14
    items: tuple[CatalogItemV14, ...]
    next_cursor: str | None
    receipt_digest: str | None
    reserved_quota: int
    reservation_window: int | None
    created_at: float
    expires_at: float
    hook_started: bool
    retry_after_ms: int | None = None


class LocalCatalogReadAdapterV14:
    """In-memory read-only contract with a no-replay reservation ledger.

    Lock order is adapter lock only.  The hook is always called after releasing
    that lock; this adapter never acquires a registry lock.
    """

    CAPABILITY_ID = "local.catalog"
    REQUIRED_SCOPE = "catalog.metadata.read"
    TARGET = "local_catalog"

    def __init__(
        self,
        items: Sequence[CatalogItemV14],
        *,
        workspace_id: str,
        account_id: str,
        profile_id: str,
        cursor_signing_key: bytes,
        read_hook: Callable[[], None],
        credential_alias: str | None = None,
        auth_available: bool = True,
        granted_scopes: Sequence[str] = (REQUIRED_SCOPE,),
        status: CapabilityStatusV14 = CapabilityStatusV14.DISABLED,
        status_reason: str = "candidate_not_activated",
        quota_limit: int = 100,
        rate_limit: int = 10,
        ledger_capacity: int = 128,
        pending_capacity: int = 16,
        uncertain_capacity: int = 32,
        pending_ttl_seconds: float = 30.0,
        uncertain_ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(items) not in {tuple, list} or len(items) > 1000:
            raise CapabilityV14ContractError("catalog items are invalid")
        copied = tuple(items)
        if any(type(item) is not CatalogItemV14 for item in copied) or len({item.item_id for item in copied}) != len(copied):
            raise CapabilityV14ContractError("catalog items must be exact and unique")
        self._items = tuple(sorted(copied, key=lambda item: item.item_id))
        self._workspace_id = _identifier(workspace_id, "workspace_id")
        self._account_id = _identifier(account_id, "account_id")
        self._profile_id = _identifier(profile_id, "profile_id")
        if type(cursor_signing_key) is not bytes or not 32 <= len(cursor_signing_key) <= 128:
            raise CapabilityV14ContractError("cursor signing key is invalid")
        self._cursor_key = bytes(cursor_signing_key)
        if not callable(read_hook) or not callable(clock):
            raise CapabilityV14ContractError("hook/clock must be callable")
        self._read_hook = read_hook
        self._clock = clock
        if credential_alias is not None and (type(credential_alias) is not str or not _ALIAS.fullmatch(credential_alias)):
            raise CapabilityV14ContractError("credential alias is invalid")
        self._credential_alias = credential_alias
        if type(auth_available) is not bool:
            raise CapabilityV14ContractError("auth state must be exact boolean")
        self._auth = auth_available
        self._scopes = frozenset(_strings(granted_scopes, "granted_scopes"))
        if type(status) is not CapabilityStatusV14 or status not in {
            CapabilityStatusV14.DISABLED, CapabilityStatusV14.AVAILABLE_READ_ONLY, CapabilityStatusV14.DEGRADED
        }:
            raise CapabilityV14ContractError("adapter status is invalid")
        self._status = status
        self._status_reason = _slug(status_reason, "status_reason")
        if status is CapabilityStatusV14.DEGRADED and status_reason == "healthy":
            raise CapabilityV14ContractError("degraded status requires reason")
        for name, value, lower, upper in (
            ("quota_limit", quota_limit, 1, 1_000_000), ("rate_limit", rate_limit, 1, 10000),
            ("ledger_capacity", ledger_capacity, 1, 4096),
            ("pending_capacity", pending_capacity, 1, 1024),
            ("uncertain_capacity", uncertain_capacity, 1, 1024),
        ):
            if type(value) is not int or not lower <= value <= upper:
                raise CapabilityV14ContractError(f"{name} is invalid")
        for name, value in (("pending_ttl_seconds", pending_ttl_seconds), ("uncertain_ttl_seconds", uncertain_ttl_seconds)):
            if type(value) not in {int, float} or not math.isfinite(value) or not 0.001 <= value <= 86_400:
                raise CapabilityV14ContractError(f"{name} is invalid")
        self._quota_limit = quota_limit
        self._rate_limit = rate_limit
        self._capacity = ledger_capacity
        if pending_capacity > uncertain_capacity or uncertain_capacity > ledger_capacity:
            raise CapabilityV14ContractError("pending/uncertain capacities exceed their parent bound")
        self._pending_capacity = pending_capacity
        self._uncertain_capacity = uncertain_capacity
        self._pending_ttl = float(pending_ttl_seconds)
        self._uncertain_ttl = float(uncertain_ttl_seconds)
        self._quota_used = 0
        self._window_second: int | None = None
        self._window_used = 0
        self._ledger: dict[str, _ReadLedgerEntryV14] = {}
        self._kill = False
        self._revoked = False
        self._lock = threading.RLock()
        self._hook_state_lock = threading.Lock()
        self._hook_active = False
        self._snapshot_digest = _sha([item.payload() for item in self._items])

    @property
    def lock_order(self) -> tuple[str, ...]:
        return LOCK_ORDER_V14

    @property
    def descriptor(self) -> CapabilityDescriptorV14:
        operation = OperationDescriptorV14(
            "catalog_read", OperationKindV14.READ, "Read allowlisted provider-free catalog metadata.",
            _json({"properties": {"cursor": {"type": "STRING"}, "page_size": {"type": "INTEGER"}}, "type": "OBJECT"}, "catalog schema"),
            (self.REQUIRED_SCOPE,), ("allowlisted_metadata",), "low", "host_policy_required",
            (self.TARGET,), (), "signed_profile_bound_cursor", "fixed_window_reserved",
            "before_and_after_hook", "before_and_after_hook", "correlation_reservation_no_replay",
            "deterministic_completed_receipt", "pending_uncertain_completed", "exact_reserved_counter",
            "zero_local_micros", "read_only_not_applicable", "provider_free_fixture", "always_confirm",
        )
        return CapabilityDescriptorV14(
            self.CAPABILITY_ID, "v14", "onyx_local", TransportKindV14.LOCAL, "local_catalog",
            CATALOG_CONTRACT_VERSION_V14, self._workspace_id, self._account_id, self._profile_id,
            self._credential_alias, (operation,), self._status, self._status_reason,
            ("metadata_only", "no_live_wiring", "no_mutation", "provider_free"),
            metadata=(("data_source", "constructor_allowlist"),),
        )

    def set_kill(self, active: bool) -> None:
        if type(active) is not bool:
            raise CapabilityV14ContractError("kill state must be exact boolean")
        with self._lock:
            self._kill = active

    def revoke(self) -> None:
        with self._lock:
            self._revoked = True

    def health(self) -> ConnectorHealthV14:
        now = self._clock()
        with self._lock:
            self._expire_pending(now)
            status, reason, _ = self._effective_status()
            pending = sum(item.state is ReadStateV14.PENDING for item in self._ledger.values())
            uncertain = sum(item.state is ReadStateV14.UNCERTAIN for item in self._ledger.values())
            return ConnectorHealthV14(
                status, reason, self._workspace_id, self._account_id, self._profile_id,
                CATALOG_CONTRACT_VERSION_V14, (self.REQUIRED_SCOPE,), tuple(sorted(self._scopes)),
                max(0, self._quota_limit - self._quota_used), len(self._ledger), pending, uncertain,
            )

    def read_page(self, request: CatalogReadRequestV14) -> CatalogReadProjectionV14:
        with self._hook_state_lock:
            if self._hook_active:
                raise CapabilityV14DeniedError("catalog read reentrancy is denied")
            self._hook_active = True
        try:
            return self._read_page_claimed(request)
        finally:
            with self._hook_state_lock:
                self._hook_active = False

    def _read_page_claimed(self, request: CatalogReadRequestV14) -> CatalogReadProjectionV14:
        if type(request) is not CatalogReadRequestV14:
            raise CapabilityV14ContractError("read request type is invalid")
        self._validate_binding(request)
        digest = self._request_digest(request)
        started = self._clock()
        with self._lock:
            self._expire_pending(started)
            prior = self._ledger.get(request.correlation_id)
            if prior is not None:
                if prior.request_digest != digest:
                    raise CapabilityV14DeniedError("correlation request drift")
                return self._projection(request.correlation_id, prior)
            if len(self._ledger) >= self._capacity:
                raise CapabilityV14DeniedError("correlation ledger capacity exhausted")
            if request.cancellation is not None and request.cancellation.cancelled:
                entry = self._terminal_without_reservation(
                    request, digest, ReadStateV14.CANCELLED_BEFORE_HOOK, ReadFailureClassV14.CANCELLED, started
                )
                self._ledger[request.correlation_id] = entry
                return self._projection(request.correlation_id, entry)
            status, reason, failure = self._effective_status()
            if status not in {CapabilityStatusV14.AVAILABLE_READ_ONLY, CapabilityStatusV14.DEGRADED}:
                entry = self._terminal_without_reservation(request, digest, ReadStateV14.DENIED, failure, started)
                self._ledger[request.correlation_id] = entry
                return self._projection(request.correlation_id, entry)
            window = int(started)
            if self._window_second != window:
                self._window_second, self._window_used = window, 0
            if self._window_used >= self._rate_limit:
                entry = self._terminal_without_reservation(
                    request, digest, ReadStateV14.RATE_LIMITED, ReadFailureClassV14.RATE_LIMIT, started, retry_after_ms=1000
                )
                self._ledger[request.correlation_id] = entry
                return self._projection(request.correlation_id, entry)
            if self._quota_used >= self._quota_limit:
                entry = self._terminal_without_reservation(
                    request, digest, ReadStateV14.DENIED, ReadFailureClassV14.QUOTA, started
                )
                self._ledger[request.correlation_id] = entry
                return self._projection(request.correlation_id, entry)
            pending_count = sum(item.state is ReadStateV14.PENDING for item in self._ledger.values())
            uncertain_count = sum(item.state is ReadStateV14.UNCERTAIN for item in self._ledger.values())
            if pending_count >= self._pending_capacity or pending_count + uncertain_count >= self._uncertain_capacity:
                raise CapabilityV14DeniedError("pending/uncertain ledger capacity exhausted")
            offset = self._decode_cursor(request.cursor) if request.cursor else 0
            page = self._items[offset : offset + request.page_size]
            next_offset = offset + len(page)
            next_cursor = self._encode_cursor(next_offset) if next_offset < len(self._items) else None
            self._quota_used += 1
            self._window_used += 1
            entry = _ReadLedgerEntryV14(
                digest, self._workspace_id, self._account_id, self._profile_id,
                ReadStateV14.PENDING, ReadFailureClassV14.NONE, page, next_cursor, None, 1,
                window, started, started + self._pending_ttl, False,
            )
            self._ledger[request.correlation_id] = entry

        # No adapter, registry, or gate lock is held beyond this point.
        pre_hook_now = self._clock()
        if request.cancellation is not None and request.cancellation.cancelled:
            return self._finish_before_hook(
                request, digest, ReadStateV14.CANCELLED_BEFORE_HOOK, ReadFailureClassV14.CANCELLED, pre_hook_now
            )
        if (pre_hook_now - started) * 1000 >= request.timeout_ms:
            return self._finish_before_hook(
                request, digest, ReadStateV14.TIMEOUT_BEFORE_HOOK, ReadFailureClassV14.TIMEOUT, pre_hook_now
            )
        with self._lock:
            current = self._ledger[request.correlation_id]
            status, _, failure = self._effective_status()
            if status not in {CapabilityStatusV14.AVAILABLE_READ_ONLY, CapabilityStatusV14.DEGRADED}:
                return self._finish_before_hook_locked(
                    request.correlation_id, current, ReadStateV14.DENIED, failure, pre_hook_now
                )
            current = replace(current, hook_started=True)
            self._ledger[request.correlation_id] = current
        hook_failed = False
        try:
            self._read_hook()
        except Exception:
            hook_failed = True
        if hook_failed:
            failed_at = self._clock()
            with self._lock:
                current = self._ledger[request.correlation_id]
                if current.state is not ReadStateV14.PENDING:
                    return self._projection(request.correlation_id, current)
                uncertain = replace(
                    current, state=ReadStateV14.UNCERTAIN, failure_class=ReadFailureClassV14.HOOK_EXCEPTION,
                    items=(), next_cursor=None, expires_at=failed_at + self._uncertain_ttl,
                )
                self._ledger[request.correlation_id] = uncertain
                return self._projection(request.correlation_id, uncertain)
        finished = self._clock()
        with self._lock:
            current = self._ledger[request.correlation_id]
            if current.state is not ReadStateV14.PENDING:
                return self._projection(request.correlation_id, current)
            status, _, failure = self._effective_status()
            if request.cancellation is not None and request.cancellation.cancelled:
                return self._finish_uncertain_locked(request.correlation_id, current, ReadFailureClassV14.CANCELLED, finished)
            if (finished - started) * 1000 >= request.timeout_ms:
                return self._finish_uncertain_locked(request.correlation_id, current, ReadFailureClassV14.TIMEOUT, finished)
            if status not in {CapabilityStatusV14.AVAILABLE_READ_ONLY, CapabilityStatusV14.DEGRADED}:
                return self._finish_uncertain_locked(request.correlation_id, current, failure, finished)
            receipt = _sha(
                {"account_id": current.account_id, "correlation_id": request.correlation_id,
                 "item_ids": [item.item_id for item in current.items], "next_cursor": current.next_cursor,
                 "profile_id": current.profile_id, "request_digest": current.request_digest,
                 "state": ReadStateV14.COMPLETED.value, "workspace_id": current.workspace_id}
            )
            completed = replace(
                current, state=ReadStateV14.COMPLETED, failure_class=ReadFailureClassV14.NONE,
                receipt_digest=receipt, expires_at=finished + self._uncertain_ttl,
            )
            self._ledger[request.correlation_id] = completed
            return self._projection(request.correlation_id, completed)

    def reconcile(self, request: CatalogReadRequestV14) -> CatalogReadProjectionV14:
        if type(request) is not CatalogReadRequestV14:
            raise CapabilityV14ContractError("reconcile request type is invalid")
        self._validate_binding(request)
        digest = self._request_digest(request)
        now = self._clock()
        with self._lock:
            self._expire_pending(now)
            entry = self._ledger.get(request.correlation_id)
            if entry is None:
                return CatalogReadProjectionV14(
                    ReadStateV14.UNKNOWN_CORRELATION, ReadFailureClassV14.UNKNOWN,
                    request.correlation_id, digest, self._workspace_id, self._account_id, self._profile_id,
                    (), None, None, max(0, self._quota_limit - self._quota_used),
                )
            if entry.request_digest != digest:
                raise CapabilityV14DeniedError("correlation request drift")
            return self._projection(request.correlation_id, entry)

    def draft(self, *_args: object, **_kwargs: object) -> None:
        raise CapabilityV14DeniedError("catalog adapter has no draft operation")

    def mutate(self, *_args: object, **_kwargs: object) -> None:
        raise CapabilityV14DeniedError("catalog adapter has no mutation operation")

    def _validate_binding(self, request: CatalogReadRequestV14) -> None:
        if (
            request.workspace_id != self._workspace_id or request.account_id != self._account_id
            or request.profile_id != self._profile_id
        ):
            raise CapabilityV14DeniedError("workspace/account/profile mismatch")
        if request.target != self.TARGET:
            raise CapabilityV14DeniedError("target is not allowlisted")

    def _effective_status(self) -> tuple[CapabilityStatusV14, str, ReadFailureClassV14]:
        if self._kill:
            return CapabilityStatusV14.DISABLED, "global_kill_active", ReadFailureClassV14.KILL
        if self._revoked:
            return CapabilityStatusV14.BLOCKED_BY_ACCESS, "credential_alias_revoked", ReadFailureClassV14.REVOKED
        if not self._auth:
            return CapabilityStatusV14.BLOCKED_BY_ACCESS, "authentication_unavailable", ReadFailureClassV14.AUTH
        if self.REQUIRED_SCOPE not in self._scopes:
            return CapabilityStatusV14.BLOCKED_BY_SCOPE, "required_scope_missing", ReadFailureClassV14.SCOPE
        if self._status is CapabilityStatusV14.DISABLED:
            return self._status, self._status_reason, ReadFailureClassV14.DISABLED
        return self._status, self._status_reason, ReadFailureClassV14.NONE

    def _request_digest(self, request: CatalogReadRequestV14) -> str:
        return _sha(
            {"account_id": request.account_id, "correlation_id": request.correlation_id,
             "cursor": request.cursor, "page_size": request.page_size, "profile_id": request.profile_id,
             "target": request.target, "timeout_ms": request.timeout_ms, "workspace_id": request.workspace_id}
        )

    def _encode_cursor(self, offset: int) -> str:
        payload = {"account_id": self._account_id, "capability_id": self.CAPABILITY_ID,
                   "contract_version": CATALOG_CONTRACT_VERSION_V14, "offset": offset,
                   "profile_id": self._profile_id, "snapshot_digest": self._snapshot_digest,
                   "workspace_id": self._workspace_id}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return body.hex() + "." + hmac.new(self._cursor_key, body, hashlib.sha256).hexdigest()

    def _decode_cursor(self, cursor: str) -> int:
        try:
            body_hex, signature = cursor.split(".", 1)
            body = bytes.fromhex(body_hex)
            expected = hmac.new(self._cursor_key, body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise CapabilityV14DeniedError("cursor integrity failure")
            payload = json.loads(body)
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise CapabilityV14DeniedError("cursor integrity failure") from exc
        expected_payload = {"account_id": self._account_id, "capability_id": self.CAPABILITY_ID,
                            "contract_version": CATALOG_CONTRACT_VERSION_V14,
                            "profile_id": self._profile_id, "snapshot_digest": self._snapshot_digest,
                            "workspace_id": self._workspace_id}
        if set(payload) != set(expected_payload) | {"offset"} or any(payload.get(k) != v for k, v in expected_payload.items()):
            raise CapabilityV14DeniedError("cursor profile/snapshot binding drift")
        offset = payload.get("offset")
        if type(offset) is not int or not 0 <= offset < len(self._items):
            raise CapabilityV14DeniedError("cursor offset is invalid")
        return offset

    def _terminal_without_reservation(
        self, request: CatalogReadRequestV14, digest: str, state: ReadStateV14,
        failure: ReadFailureClassV14, now: float, *, retry_after_ms: int | None = None,
    ) -> _ReadLedgerEntryV14:
        return _ReadLedgerEntryV14(
            digest, request.workspace_id, request.account_id, request.profile_id, state, failure,
            (), None, None, 0, None, now, now + self._uncertain_ttl, False, retry_after_ms,
        )

    def _finish_before_hook(
        self, request: CatalogReadRequestV14, digest: str, state: ReadStateV14, failure: ReadFailureClassV14,
        now: float,
    ) -> CatalogReadProjectionV14:
        with self._lock:
            current = self._ledger[request.correlation_id]
            if current.request_digest != digest:
                raise CapabilityV14DeniedError("correlation request drift")
            return self._finish_before_hook_locked(request.correlation_id, current, state, failure, now)

    def _finish_before_hook_locked(
        self, correlation_id: str, current: _ReadLedgerEntryV14, state: ReadStateV14,
        failure: ReadFailureClassV14, now: float,
    ) -> CatalogReadProjectionV14:
        if current.hook_started:
            return self._finish_uncertain_locked(correlation_id, current, failure, now)
        self._release_reservation(current)
        terminal = replace(
            current, state=state, failure_class=failure, items=(), next_cursor=None,
            reserved_quota=0, reservation_window=None, expires_at=now + self._uncertain_ttl,
        )
        self._ledger[correlation_id] = terminal
        return self._projection(correlation_id, terminal)

    def _finish_uncertain_locked(
        self, correlation_id: str, current: _ReadLedgerEntryV14,
        failure: ReadFailureClassV14, now: float,
    ) -> CatalogReadProjectionV14:
        uncertain = replace(
            current, state=ReadStateV14.UNCERTAIN, failure_class=failure,
            items=(), next_cursor=None, expires_at=now + self._uncertain_ttl,
        )
        self._ledger[correlation_id] = uncertain
        return self._projection(correlation_id, uncertain)

    def _release_reservation(self, entry: _ReadLedgerEntryV14) -> None:
        if entry.reserved_quota:
            self._quota_used = max(0, self._quota_used - entry.reserved_quota)
        if entry.reservation_window == self._window_second and self._window_used:
            self._window_used -= 1

    def _expire_pending(self, now: float) -> None:
        for correlation_id, entry in tuple(self._ledger.items()):
            if entry.state is ReadStateV14.PENDING and now >= entry.expires_at:
                uncertain = replace(
                    entry, state=ReadStateV14.UNCERTAIN,
                    failure_class=ReadFailureClassV14.EXPIRED_PENDING,
                    items=(), next_cursor=None, expires_at=now + self._uncertain_ttl,
                )
                self._ledger[correlation_id] = uncertain
            elif entry.state is ReadStateV14.UNCERTAIN and now >= entry.expires_at:
                self._ledger[correlation_id] = replace(
                    entry, state=ReadStateV14.EXPIRED_UNCERTAIN,
                    failure_class=ReadFailureClassV14.UNCERTAIN_EXPIRED,
                    items=(), next_cursor=None, expires_at=now,
                )

    def _projection(self, correlation_id: str, entry: _ReadLedgerEntryV14) -> CatalogReadProjectionV14:
        return CatalogReadProjectionV14(
            entry.state, entry.failure_class, correlation_id, entry.request_digest,
            entry.workspace_id, entry.account_id, entry.profile_id,
            entry.items if entry.state is ReadStateV14.COMPLETED else (),
            entry.next_cursor if entry.state is ReadStateV14.COMPLETED else None,
            entry.receipt_digest if entry.state is ReadStateV14.COMPLETED else None,
            max(0, self._quota_limit - self._quota_used), entry.retry_after_ms,
        )
