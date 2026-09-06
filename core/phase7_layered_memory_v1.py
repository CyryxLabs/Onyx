"""Governed seven-layer memory catalog for Onyx Phase 7.

This successor does not replace or modify the accepted Workspace Memory V1
adapter.  It stores signed, typed records in a separate ``lmem_`` namespace in
the existing control-plane ``memory_metadata`` table.  Rows deliberately keep
schema_version=1 and never use the predecessor's ``active`` row status so the
accepted read-only adapter can safely ignore them.

Memory content is evidence, never executable instruction authority.  All
retrieval authorization and lifecycle filters run before lexical ranking.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, NoReturn

from core.control_plane import ControlPlaneStore
from core.workspaces import (
    LEGACY_WORKSPACE_ID,
    WorkspaceError,
    WorkspaceRecord,
    WorkspaceRegistry,
)

FEATURE_FLAG: Final = "ONYX_PHASE7_LAYERED_MEMORY_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxLayeredMemory.v1"
SCHEMA_VERSION: Final = 1
ROW_PREFIX: Final = "lmem_"
MAX_RECORDS: Final = 10_000
MAX_CONTENT_CHARS: Final = 100_000
MAX_QUERY_CHARS: Final = 2_000
MAX_RESULTS: Final = 100
MAX_SOURCES: Final = 32
MAX_RELATIONS: Final = 32
MAX_TAGS: Final = 32

LAYERS: Final = (
    "session_working",
    "episodic_mission",
    "semantic_institutional",
    "decision",
    "procedural",
    "preference",
    "temporal_status",
)
SENSITIVITIES: Final = ("public", "internal", "confidential", "restricted")
RETRIEVABLE_STATUSES: Final = frozenset({"approved"})
LIFECYCLE_STATUSES: Final = frozenset(
    {
        "candidate",
        "approved",
        "rejected",
        "superseded",
        "corrected",
        "deleted",
    }
)

WORKSPACE_MEMORY_ENTRY_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase7-workspace-memory-v1/manifest.json",
        "59ed88abd6967a73f3050d1215fed0c278b21b5c6e5335814abe8267576c9cd7",
    ),
    (
        "docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.md",
        "3490c0f89ba37c81c67f7e76dc2daedac91622e8386efe668e259d4819848825",
    ),
    (
        "docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.manifest.json",
        "c6497c644f447a1bc83b63446c25c8be4071dcf103b5dfbf2a5de7b809edf43a",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P7-WORKSPACE-MEMORY-V1-E6-001.sha256",
        "9628e79458bd8ef76ce8fbbc56939182638b2b10dbf2262b9e4c2b3d677bdfa9",
    ),
)

_WORKSPACE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_PRINCIPAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_ATOM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)
_SECRET_PATTERNS: Final = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgh[opurs]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}\b", re.IGNORECASE),
)
_POISON_PATTERNS: Final = (
    (
        "instruction_override",
        re.compile(
            r"\bignore (?:all |the )?(?:previous|prior) instructions?\b", re.IGNORECASE
        ),
    ),
    (
        "authority_impersonation",
        re.compile(r"\b(?:system|developer) message\s*:", re.IGNORECASE),
    ),
    (
        "tool_coercion",
        re.compile(
            r"\b(?:execute|run)\s+(?:this\s+)?(?:command|tool)\b", re.IGNORECASE
        ),
    ),
)
_WRITE_LOCK = threading.RLock()
_CONSTRUCTION_KEY = object()


class LayeredMemoryV1Error(RuntimeError):
    """Base error for the governed layered-memory catalog."""


class LayeredMemoryV1ContractError(ValueError):
    """An input or stored contract is malformed."""


class LayeredMemoryV1Denied(PermissionError):
    """Authorization, integrity, policy, or lifecycle access was denied."""


class LayeredMemoryV1Conflict(LayeredMemoryV1Error):
    """An immutable identity or concurrent lifecycle transition conflicted."""


@dataclass(frozen=True, slots=True)
class LayeredMemoryFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise LayeredMemoryV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls,
        environ: dict[str, str] | os._Environ[str] | None = None,
    ) -> "LayeredMemoryFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


def _exact_text(name: str, value: object, *, maximum: int = 128) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise LayeredMemoryV1ContractError(f"{name} is invalid")
    if "\x00" in value:
        raise LayeredMemoryV1ContractError(f"{name} contains a NUL byte")
    return value


def _atom(name: str, value: object) -> str:
    text = _exact_text(name, value)
    if not _ATOM.fullmatch(text):
        raise LayeredMemoryV1ContractError(f"{name} is invalid")
    return text


def _workspace_id(value: object) -> str:
    text = _exact_text("workspace_id", value, maximum=64)
    if not _WORKSPACE_ID.fullmatch(text) or text == LEGACY_WORKSPACE_ID:
        raise LayeredMemoryV1ContractError("non-legacy workspace_id is required")
    return text


def _principal_id(value: object) -> str:
    text = _exact_text("principal_id", value)
    if not _PRINCIPAL_ID.fullmatch(text):
        raise LayeredMemoryV1ContractError("principal_id is invalid")
    return text


def _timestamp(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise LayeredMemoryV1ContractError(f"{name} is invalid")
    return value


def _exact_key(value: object) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        raise LayeredMemoryV1ContractError(
            "integrity_key must contain at least 32 bytes"
        )
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LayeredMemoryV1ContractError("value is not canonical JSON") from exc


def _strict_json(text: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LayeredMemoryV1Denied(f"duplicate memory key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except (TypeError, json.JSONDecodeError) as exc:
        raise LayeredMemoryV1Denied("layered memory JSON is invalid") from exc
    if type(value) is not dict:
        raise LayeredMemoryV1Denied("layered memory payload must be an object")
    return value


def _normalized_content(value: str) -> str:
    return " ".join(value.casefold().split())


def _content_sha256(value: str) -> str:
    return hashlib.sha256(_normalized_content(value).encode("utf-8")).hexdigest()


def _entity_sha256(kind: str, key: str) -> str:
    return hashlib.sha256(f"{kind}\0{key.casefold()}".encode("utf-8")).hexdigest()


def _payload_mac(payload: dict[str, object], key: bytes) -> str:
    unsigned = {name: value for name, value in payload.items() if name != "hmac_sha256"}
    return hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()


def _poison_signals(content: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in _POISON_PATTERNS if pattern.search(content))


def _reject_secrets(content: str) -> None:
    if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
        raise LayeredMemoryV1Denied(
            "secret-like content is not eligible for memory persistence"
        )


def layered_memory_id_v1(
    *,
    workspace_id: str,
    principal_id: str,
    layer: str,
    entity_kind: str,
    entity_key: str,
    content_sha256: str,
) -> str:
    workspace = _workspace_id(workspace_id)
    principal = _principal_id(principal_id)
    if layer not in LAYERS:
        raise LayeredMemoryV1ContractError("layer is invalid")
    kind = _atom("entity_kind", entity_kind)
    key = _atom("entity_key", entity_key)
    if type(content_sha256) is not str or not _HEX64.fullmatch(content_sha256):
        raise LayeredMemoryV1ContractError("content_sha256 is invalid")
    digest = hashlib.sha256(
        f"{SCHEMA}\0{workspace}\0{principal}\0{layer}\0{kind}\0{key.casefold()}\0{content_sha256}".encode(
            "utf-8"
        )
    ).hexdigest()
    return f"{ROW_PREFIX}{digest[:32]}"


@dataclass(frozen=True, slots=True)
class LayeredMemorySpecV1:
    layer: str
    entity_kind: str
    entity_key: str
    content: str
    source_ids: tuple[str, ...]
    sensitivity: str
    confidence_bp: int
    valid_from_ms: int
    valid_until_ms: int | None
    fresh_until_ms: int
    retention_until_ms: int | None
    tags: tuple[str, ...] = ()
    status: str = "candidate"
    supersedes_id: str | None = None
    correction_of_id: str | None = None
    contradicts_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.layer not in LAYERS:
            raise LayeredMemoryV1ContractError("layer is invalid")
        _atom("entity_kind", self.entity_kind)
        _atom("entity_key", self.entity_key)
        content = _exact_text("content", self.content, maximum=MAX_CONTENT_CHARS)
        _reject_secrets(content)
        if (
            type(self.source_ids) is not tuple
            or not 1 <= len(self.source_ids) <= MAX_SOURCES
            or len(set(self.source_ids)) != len(self.source_ids)
            or any(_atom("source_id", value) != value for value in self.source_ids)
        ):
            raise LayeredMemoryV1ContractError("source_ids are invalid")
        if self.sensitivity not in SENSITIVITIES:
            raise LayeredMemoryV1ContractError("sensitivity is invalid")
        if type(self.confidence_bp) is not int or not 0 <= self.confidence_bp <= 10_000:
            raise LayeredMemoryV1ContractError("confidence_bp is invalid")
        valid_from = _timestamp("valid_from_ms", self.valid_from_ms)
        if self.valid_until_ms is not None:
            valid_until = _timestamp("valid_until_ms", self.valid_until_ms)
            if valid_until <= valid_from:
                raise LayeredMemoryV1ContractError(
                    "valid_until_ms must follow valid_from_ms"
                )
        fresh_until = _timestamp("fresh_until_ms", self.fresh_until_ms)
        if fresh_until < valid_from or (
            self.valid_until_ms is not None and fresh_until > self.valid_until_ms
        ):
            raise LayeredMemoryV1ContractError("freshness window is invalid")
        if self.retention_until_ms is not None:
            retention = _timestamp("retention_until_ms", self.retention_until_ms)
            if retention <= valid_from:
                raise LayeredMemoryV1ContractError(
                    "retention must follow valid_from_ms"
                )
        if (
            type(self.tags) is not tuple
            or len(self.tags) > MAX_TAGS
            or len(set(self.tags)) != len(self.tags)
            or any(_atom("tag", value) != value for value in self.tags)
        ):
            raise LayeredMemoryV1ContractError("tags are invalid")
        if self.status not in {"candidate", "approved"}:
            raise LayeredMemoryV1ContractError(
                "initial status must be candidate or approved"
            )
        for name, value in (
            ("supersedes_id", self.supersedes_id),
            ("correction_of_id", self.correction_of_id),
        ):
            if value is not None and (
                type(value) is not str
                or not value.startswith(ROW_PREFIX)
                or not _ATOM.fullmatch(value)
            ):
                raise LayeredMemoryV1ContractError(f"{name} is invalid")
        if self.supersedes_id is not None and self.correction_of_id is not None:
            raise LayeredMemoryV1ContractError(
                "correction and supersession are mutually exclusive"
            )
        if (
            type(self.contradicts_ids) is not tuple
            or len(self.contradicts_ids) > MAX_RELATIONS
            or len(set(self.contradicts_ids)) != len(self.contradicts_ids)
            or any(
                type(value) is not str
                or not value.startswith(ROW_PREFIX)
                or not _ATOM.fullmatch(value)
                for value in self.contradicts_ids
            )
        ):
            raise LayeredMemoryV1ContractError("contradicts_ids are invalid")


@dataclass(frozen=True, slots=True)
class LayeredMemoryQueryV1:
    text: str
    layers: tuple[str, ...] = LAYERS
    allowed_sensitivities: tuple[str, ...] = ("public", "internal")
    include_stale: bool = False
    limit: int = 8

    def __post_init__(self) -> None:
        _exact_text("query text", self.text, maximum=MAX_QUERY_CHARS)
        if (
            type(self.layers) is not tuple
            or not self.layers
            or len(set(self.layers)) != len(self.layers)
            or any(value not in LAYERS for value in self.layers)
        ):
            raise LayeredMemoryV1ContractError("query layers are invalid")
        if (
            type(self.allowed_sensitivities) is not tuple
            or not self.allowed_sensitivities
            or len(set(self.allowed_sensitivities)) != len(self.allowed_sensitivities)
            or any(value not in SENSITIVITIES for value in self.allowed_sensitivities)
        ):
            raise LayeredMemoryV1ContractError("allowed_sensitivities are invalid")
        if type(self.include_stale) is not bool:
            raise LayeredMemoryV1ContractError("include_stale must be exact bool")
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_RESULTS:
            raise LayeredMemoryV1ContractError("query limit is invalid")


@dataclass(frozen=True, slots=True)
class LayeredMemoryRecordV1:
    memory_id: str
    workspace_id: str
    principal_id: str
    layer: str
    entity_kind: str
    entity_key: str
    entity_sha256: str
    content: str | None
    content_sha256: str
    source_ids: tuple[str, ...]
    source_status: str
    sensitivity: str
    confidence_bp: int
    status: str
    valid_from_ms: int
    valid_until_ms: int | None
    fresh_until_ms: int
    retention_until_ms: int | None
    tags: tuple[str, ...]
    supersedes_id: str | None
    correction_of_id: str | None
    contradicts_ids: tuple[str, ...]
    poison_signals: tuple[str, ...]
    created_at_ms: int
    updated_at_ms: int
    deleted_at_ms: int | None
    deletion_reason: str | None
    content_trust: str
    instructions_authority: bool
    hmac_sha256: str
    freshness: str
    score: float = 0.0

    def __post_init__(self) -> None:
        if (
            type(self.memory_id) is not str
            or not self.memory_id.startswith(ROW_PREFIX)
            or self.layer not in LAYERS
            or self.status not in LIFECYCLE_STATUSES
            or self.source_status not in {"available", "deleted", "revoked"}
            or self.sensitivity not in SENSITIVITIES
            or not _HEX64.fullmatch(self.entity_sha256)
            or not _HEX64.fullmatch(self.content_sha256)
            or self.content_trust != "untrusted_data"
            or self.instructions_authority is not False
            or not _HEX64.fullmatch(self.hmac_sha256)
            or self.freshness not in {"fresh", "stale", "invalid", "deleted"}
            or type(self.score) is not float
            or self.score < 0
        ):
            raise LayeredMemoryV1ContractError("layered memory record contract drift")
        if self.status == "deleted" and self.content is not None:
            raise LayeredMemoryV1ContractError(
                "deleted memory content was not scrubbed"
            )
        if self.status != "deleted" and type(self.content) is not str:
            raise LayeredMemoryV1ContractError("live memory content is unavailable")


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in WORKSPACE_MEMORY_ENTRY_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise LayeredMemoryV1Denied(
                "Workspace Memory V1 entry evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise LayeredMemoryV1Denied("Workspace Memory V1 entry evidence drift")


def _freshness(
    *,
    status: str,
    source_status: str,
    valid_from_ms: int,
    valid_until_ms: int | None,
    fresh_until_ms: int,
    now_ms: int,
) -> str:
    if status == "deleted" or source_status != "available":
        return "deleted"
    if now_ms < valid_from_ms or (
        valid_until_ms is not None and now_ms >= valid_until_ms
    ):
        return "invalid"
    return "fresh" if now_ms <= fresh_until_ms else "stale"


def _stored_str(payload: dict[str, object], name: str) -> str:
    value = payload[name]
    if type(value) is not str:
        raise LayeredMemoryV1Denied(f"stored {name} type drift")
    return value


def _stored_int(payload: dict[str, object], name: str) -> int:
    value = payload[name]
    if type(value) is not int or value < 0:
        raise LayeredMemoryV1Denied(f"stored {name} type drift")
    return value


def _stored_optional_int(payload: dict[str, object], name: str) -> int | None:
    value = payload[name]
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise LayeredMemoryV1Denied(f"stored {name} type drift")
    return value


def _stored_optional_str(payload: dict[str, object], name: str) -> str | None:
    value = payload[name]
    if value is None:
        return None
    if type(value) is not str:
        raise LayeredMemoryV1Denied(f"stored {name} type drift")
    return value


def _stored_str_tuple(
    payload: dict[str, object],
    name: str,
    *,
    maximum: int,
) -> tuple[str, ...]:
    value = payload[name]
    if (
        type(value) is not list
        or len(value) > maximum
        or any(type(item) is not str for item in value)
    ):
        raise LayeredMemoryV1Denied(f"stored {name} type drift")
    return tuple(value)


def _record_from_payload(
    payload: dict[str, object],
    *,
    row: tuple[object, ...],
    workspace_id: str,
    principal_id: str,
    key: bytes,
    now_ms: int,
) -> LayeredMemoryRecordV1:
    expected_keys = {
        "schema",
        "memory_id",
        "workspace_id",
        "principal_id",
        "layer",
        "entity_kind",
        "entity_key",
        "entity_sha256",
        "content",
        "content_sha256",
        "source_ids",
        "source_status",
        "sensitivity",
        "confidence_bp",
        "status",
        "valid_from_ms",
        "valid_until_ms",
        "fresh_until_ms",
        "retention_until_ms",
        "tags",
        "supersedes_id",
        "correction_of_id",
        "contradicts_ids",
        "poison_signals",
        "created_at_ms",
        "updated_at_ms",
        "deleted_at_ms",
        "deletion_reason",
        "content_trust",
        "instructions_authority",
        "key_fingerprint_sha256",
        "hmac_sha256",
    }
    if set(payload) != expected_keys:
        raise LayeredMemoryV1Denied("layered memory payload shape drift")
    if len(row) != 8:
        raise LayeredMemoryV1Denied("layered memory row shape drift")
    (
        row_id,
        row_workspace,
        source_memory_id,
        schema_version,
        row_status,
        _payload_json,
        row_created,
        row_updated,
    ) = row
    if (
        payload["schema"] != SCHEMA
        or row_id != payload["memory_id"]
        or source_memory_id != payload["memory_id"]
        or row_workspace != workspace_id
        or payload["workspace_id"] != workspace_id
        or payload["principal_id"] != principal_id
        or schema_version != SCHEMA_VERSION
        or row_status != payload["status"]
        or str(payload["created_at_ms"]) != row_created
        or str(payload["updated_at_ms"]) != row_updated
        or payload["key_fingerprint_sha256"] != hashlib.sha256(key).hexdigest()
        or not hmac.compare_digest(
            str(payload["hmac_sha256"]), _payload_mac(payload, key)
        )
    ):
        raise LayeredMemoryV1Denied("layered memory integrity or binding drift")
    try:
        memory_id = _stored_str(payload, "memory_id")
        stored_workspace_id = _stored_str(payload, "workspace_id")
        stored_principal_id = _stored_str(payload, "principal_id")
        layer = _stored_str(payload, "layer")
        entity_kind = _stored_str(payload, "entity_kind")
        entity_key = _stored_str(payload, "entity_key")
        entity_sha256 = _stored_str(payload, "entity_sha256")
        content_sha256 = _stored_str(payload, "content_sha256")
        source_ids = _stored_str_tuple(payload, "source_ids", maximum=MAX_SOURCES)
        source_status = _stored_str(payload, "source_status")
        sensitivity = _stored_str(payload, "sensitivity")
        confidence_bp = _stored_int(payload, "confidence_bp")
        status = _stored_str(payload, "status")
        valid_from_ms = _stored_int(payload, "valid_from_ms")
        valid_until_ms = _stored_optional_int(payload, "valid_until_ms")
        fresh_until_ms = _stored_int(payload, "fresh_until_ms")
        retention_until_ms = _stored_optional_int(payload, "retention_until_ms")
        tags = _stored_str_tuple(payload, "tags", maximum=MAX_TAGS)
        supersedes_id = _stored_optional_str(payload, "supersedes_id")
        correction_of_id = _stored_optional_str(payload, "correction_of_id")
        contradiction_ids = _stored_str_tuple(
            payload, "contradicts_ids", maximum=MAX_RELATIONS
        )
        poison = _stored_str_tuple(
            payload, "poison_signals", maximum=len(_POISON_PATTERNS)
        )
        created_at_ms = _stored_int(payload, "created_at_ms")
        updated_at_ms = _stored_int(payload, "updated_at_ms")
        deleted_at_ms = _stored_optional_int(payload, "deleted_at_ms")
        deletion_reason = _stored_optional_str(payload, "deletion_reason")
        content_trust = _stored_str(payload, "content_trust")
        if payload["instructions_authority"] is not False:
            raise LayeredMemoryV1Denied("stored instructions_authority type drift")
        instructions_authority = False
        hmac_sha256 = _stored_str(payload, "hmac_sha256")
        content = payload["content"]
        if content is not None and type(content) is not str:
            raise LayeredMemoryV1Denied("stored content type drift")
        if (
            content is not None
            and _content_sha256(content) != payload["content_sha256"]
        ):
            raise LayeredMemoryV1Denied("layered memory content hash drift")
        if _entity_sha256(entity_kind, entity_key) != entity_sha256:
            raise LayeredMemoryV1Denied("layered memory entity hash drift")
        record = LayeredMemoryRecordV1(
            memory_id=memory_id,
            workspace_id=stored_workspace_id,
            principal_id=stored_principal_id,
            layer=layer,
            entity_kind=entity_kind,
            entity_key=entity_key,
            entity_sha256=entity_sha256,
            content=content,
            content_sha256=content_sha256,
            source_ids=source_ids,
            source_status=source_status,
            sensitivity=sensitivity,
            confidence_bp=confidence_bp,
            status=status,
            valid_from_ms=valid_from_ms,
            valid_until_ms=valid_until_ms,
            fresh_until_ms=fresh_until_ms,
            retention_until_ms=retention_until_ms,
            tags=tags,
            supersedes_id=supersedes_id,
            correction_of_id=correction_of_id,
            contradicts_ids=contradiction_ids,
            poison_signals=poison,
            created_at_ms=created_at_ms,
            updated_at_ms=updated_at_ms,
            deleted_at_ms=deleted_at_ms,
            deletion_reason=deletion_reason,
            content_trust=content_trust,
            instructions_authority=instructions_authority,
            hmac_sha256=hmac_sha256,
            freshness=_freshness(
                status=status,
                source_status=source_status,
                valid_from_ms=valid_from_ms,
                valid_until_ms=valid_until_ms,
                fresh_until_ms=fresh_until_ms,
                now_ms=now_ms,
            ),
        )
    except LayeredMemoryV1Denied:
        raise
    except (KeyError, TypeError, ValueError, LayeredMemoryV1ContractError) as exc:
        raise LayeredMemoryV1Denied("layered memory payload values drift") from exc
    return record


class LayeredMemoryCatalogV1:
    """Sealed, workspace/principal-bound seven-layer memory catalog."""

    __slots__ = (
        "_registry",
        "_store",
        "_workspace",
        "_principal_id",
        "_integrity_key",
        "_key_fingerprint",
        "_connection_id",
        "_control_path",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        registry: WorkspaceRegistry,
        workspace_id: str,
        principal_id: str,
        integrity_key: bytes,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise LayeredMemoryV1ContractError("use create_layered_memory_catalog_v1")
        if type(registry) is not WorkspaceRegistry:
            raise LayeredMemoryV1ContractError("exact WorkspaceRegistry required")
        if registry.enabled is not True or not registry.store.is_open:
            raise LayeredMemoryV1Denied(
                "initialized enabled workspace registry required"
            )
        workspace = _workspace_id(workspace_id)
        principal = _principal_id(principal_id)
        key = _exact_key(integrity_key)
        try:
            record = registry.require_active(workspace)
        except WorkspaceError as exc:
            raise LayeredMemoryV1Denied("active workspace binding denied") from exc
        self._registry = registry
        self._store = registry.store
        self._workspace = record
        self._principal_id = principal
        self._integrity_key = key
        self._key_fingerprint = hashlib.sha256(key).hexdigest()
        self._connection_id = id(self._store._require_connection())
        self._control_path = self._store.path.absolute()

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("LayeredMemoryCatalogV1 cannot be subclassed")

    def __copy__(self) -> object:
        raise TypeError("LayeredMemoryCatalogV1 cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("LayeredMemoryCatalogV1 cannot be copied")

    def __reduce__(self) -> NoReturn:
        raise TypeError("LayeredMemoryCatalogV1 cannot be serialized")

    @property
    def workspace_id(self) -> str:
        return self._workspace.workspace_id

    @property
    def principal_id(self) -> str:
        return self._principal_id

    @property
    def key_fingerprint_sha256(self) -> str:
        return self._key_fingerprint

    def _attest(self) -> sqlite3.Connection:
        if (
            type(self._registry) is not WorkspaceRegistry
            or type(self._store) is not ControlPlaneStore
            or self._registry.store is not self._store
            or self._registry.enabled is not True
            or not self._store.is_open
            or self._store.path.absolute() != self._control_path
            or hashlib.sha256(self._integrity_key).hexdigest() != self._key_fingerprint
        ):
            raise LayeredMemoryV1Denied("layered memory binding drift denied")
        connection = self._store._require_connection()
        if id(connection) != self._connection_id:
            raise LayeredMemoryV1Denied("control-plane connection drift denied")
        try:
            current = self._registry.require_active(self.workspace_id)
        except WorkspaceError as exc:
            raise LayeredMemoryV1Denied("active workspace attestation denied") from exc
        if type(current) is not WorkspaceRecord or current != self._workspace:
            raise LayeredMemoryV1Denied("workspace identity drift denied")
        return connection

    def _row(
        self, connection: sqlite3.Connection, memory_id: str
    ) -> tuple[object, ...] | None:
        try:
            row = connection.execute(
                "SELECT memory_metadata_id,workspace_id,source_memory_id,"
                "schema_version,status,payload_json,created_at,updated_at "
                "FROM memory_metadata WHERE memory_metadata_id=? AND workspace_id=?",
                (memory_id, self.workspace_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise LayeredMemoryV1Denied("layered memory lookup failed") from exc
        return None if row is None else tuple(row)

    def _parse(self, row: tuple[object, ...], *, now_ms: int) -> LayeredMemoryRecordV1:
        if (
            type(row[0]) is not str
            or not row[0].startswith(ROW_PREFIX)
            or type(row[5]) is not str
        ):
            raise LayeredMemoryV1Denied("layered memory row contract drift")
        return _record_from_payload(
            _strict_json(row[5]),
            row=row,
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            key=self._integrity_key,
            now_ms=now_ms,
        )

    def get(
        self,
        memory_id: str,
        *,
        now_ms: int,
        include_terminal: bool = False,
    ) -> LayeredMemoryRecordV1:
        identifier = _atom("memory_id", memory_id)
        if not identifier.startswith(ROW_PREFIX):
            raise LayeredMemoryV1ContractError("memory_id is invalid")
        _timestamp("now_ms", now_ms)
        if type(include_terminal) is not bool:
            raise LayeredMemoryV1ContractError("include_terminal must be exact bool")
        row = self._row(self._attest(), identifier)
        if row is None:
            raise LayeredMemoryV1Denied("layered memory is unavailable")
        untrusted_header = _strict_json(str(row[5]))
        if untrusted_header.get("principal_id") != self.principal_id:
            raise LayeredMemoryV1Denied("layered memory is unavailable")
        record = self._parse(row, now_ms=now_ms)
        if not include_terminal and record.status in {
            "rejected",
            "superseded",
            "corrected",
            "deleted",
        }:
            raise LayeredMemoryV1Denied("layered memory is terminal")
        self._attest()
        return record

    def _relation_target(
        self,
        connection: sqlite3.Connection,
        memory_id: str,
        *,
        now_ms: int,
        spec: LayeredMemorySpecV1,
    ) -> LayeredMemoryRecordV1:
        row = self._row(connection, memory_id)
        if row is None:
            raise LayeredMemoryV1Denied("memory relation target is unavailable")
        target = self._parse(row, now_ms=now_ms)
        if (
            target.status == "deleted"
            or target.layer != spec.layer
            or target.entity_kind != spec.entity_kind
            or target.entity_key.casefold() != spec.entity_key.casefold()
            or target.created_at_ms > now_ms
        ):
            raise LayeredMemoryV1Denied("memory relation target is incompatible")
        return target

    @staticmethod
    def _payload_for_spec(
        *,
        memory_id: str,
        workspace_id: str,
        principal_id: str,
        key_fingerprint: str,
        spec: LayeredMemorySpecV1,
        now_ms: int,
        integrity_key: bytes,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": SCHEMA,
            "memory_id": memory_id,
            "workspace_id": workspace_id,
            "principal_id": principal_id,
            "layer": spec.layer,
            "entity_kind": spec.entity_kind,
            "entity_key": spec.entity_key,
            "entity_sha256": _entity_sha256(spec.entity_kind, spec.entity_key),
            "content": spec.content,
            "content_sha256": _content_sha256(spec.content),
            "source_ids": list(spec.source_ids),
            "source_status": "available",
            "sensitivity": spec.sensitivity,
            "confidence_bp": spec.confidence_bp,
            "status": spec.status,
            "valid_from_ms": spec.valid_from_ms,
            "valid_until_ms": spec.valid_until_ms,
            "fresh_until_ms": spec.fresh_until_ms,
            "retention_until_ms": spec.retention_until_ms,
            "tags": list(spec.tags),
            "supersedes_id": spec.supersedes_id,
            "correction_of_id": spec.correction_of_id,
            "contradicts_ids": list(spec.contradicts_ids),
            "poison_signals": list(_poison_signals(spec.content)),
            "created_at_ms": now_ms,
            "updated_at_ms": now_ms,
            "deleted_at_ms": None,
            "deletion_reason": None,
            "content_trust": "untrusted_data",
            "instructions_authority": False,
            "key_fingerprint_sha256": key_fingerprint,
        }
        payload["hmac_sha256"] = _payload_mac(payload, integrity_key)
        return payload

    def remember(
        self,
        spec: LayeredMemorySpecV1,
        *,
        now_ms: int,
    ) -> LayeredMemoryRecordV1:
        if type(spec) is not LayeredMemorySpecV1:
            raise LayeredMemoryV1ContractError("exact layered memory spec required")
        _timestamp("now_ms", now_ms)
        if now_ms < spec.valid_from_ms or (
            spec.valid_until_ms is not None and now_ms >= spec.valid_until_ms
        ):
            raise LayeredMemoryV1ContractError("memory is outside its validity window")
        content_sha = _content_sha256(spec.content)
        memory_id = layered_memory_id_v1(
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            layer=spec.layer,
            entity_kind=spec.entity_kind,
            entity_key=spec.entity_key,
            content_sha256=content_sha,
        )
        with _WRITE_LOCK:
            connection = self._attest()
            existing = self._row(connection, memory_id)
            if existing is not None:
                record = self._parse(existing, now_ms=now_ms)
                if (
                    record.status == "deleted"
                    or record.layer != spec.layer
                    or record.entity_kind != spec.entity_kind
                    or record.entity_key != spec.entity_key
                    or record.content != spec.content
                    or record.source_ids != spec.source_ids
                    or record.source_status != "available"
                    or record.sensitivity != spec.sensitivity
                    or record.confidence_bp != spec.confidence_bp
                    or record.valid_from_ms != spec.valid_from_ms
                    or record.valid_until_ms != spec.valid_until_ms
                    or record.fresh_until_ms != spec.fresh_until_ms
                    or record.retention_until_ms != spec.retention_until_ms
                    or record.tags != spec.tags
                    or record.supersedes_id != spec.supersedes_id
                    or record.correction_of_id != spec.correction_of_id
                    or record.contradicts_ids != spec.contradicts_ids
                ):
                    raise LayeredMemoryV1Conflict(
                        "memory identity has different immutable metadata"
                    )
                return record

            relation_ids = tuple(
                value
                for value in (
                    spec.supersedes_id,
                    spec.correction_of_id,
                    *spec.contradicts_ids,
                )
                if value is not None
            )
            if memory_id in relation_ids:
                raise LayeredMemoryV1ContractError("memory cannot relate to itself")
            targets = {
                identifier: self._relation_target(
                    connection, identifier, now_ms=now_ms, spec=spec
                )
                for identifier in relation_ids
            }
            # Entity resolution is explicit: a new value for an existing entity
            # must explain whether it supersedes, corrects, or contradicts.
            try:
                rows = connection.execute(
                    "SELECT memory_metadata_id,workspace_id,source_memory_id,"
                    "schema_version,status,payload_json,created_at,updated_at "
                    "FROM memory_metadata WHERE workspace_id=? "
                    "AND memory_metadata_id LIKE ? ORDER BY memory_metadata_id LIMIT ?",
                    (self.workspace_id, f"{ROW_PREFIX}%", MAX_RECORDS + 1),
                ).fetchall()
            except sqlite3.DatabaseError as exc:
                raise LayeredMemoryV1Denied("entity resolution scan failed") from exc
            if len(rows) > MAX_RECORDS:
                raise LayeredMemoryV1Denied("layered memory bound exceeded")
            related_set = set(relation_ids)
            for prior in self._principal_records(
                connection,
                now_ms=now_ms,
                rows=[tuple(raw) for raw in rows],
            ):
                if (
                    prior.status in {"candidate", "approved"}
                    and prior.layer == spec.layer
                    and prior.entity_sha256
                    == _entity_sha256(spec.entity_kind, spec.entity_key)
                    and prior.content_sha256 != content_sha
                    and prior.memory_id not in related_set
                ):
                    raise LayeredMemoryV1Conflict(
                        "new entity value requires explicit correction, supersession, or contradiction"
                    )

            payload = self._payload_for_spec(
                memory_id=memory_id,
                workspace_id=self.workspace_id,
                principal_id=self.principal_id,
                key_fingerprint=self._key_fingerprint,
                spec=spec,
                now_ms=now_ms,
                integrity_key=self._integrity_key,
            )
            try:
                connection.execute("BEGIN IMMEDIATE")
                # Re-read relation rows while holding the write lock.
                for identifier, original in targets.items():
                    locked = self._row(connection, identifier)
                    if locked is None or self._parse(locked, now_ms=now_ms) != original:
                        raise LayeredMemoryV1Conflict(
                            "memory relation changed concurrently"
                        )
                connection.execute(
                    "INSERT INTO memory_metadata("
                    "memory_metadata_id,workspace_id,source_memory_id,schema_version,"
                    "status,payload_json,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?)",
                    (
                        memory_id,
                        self.workspace_id,
                        memory_id,
                        SCHEMA_VERSION,
                        spec.status,
                        _canonical(payload).decode("utf-8"),
                        str(now_ms),
                        str(now_ms),
                    ),
                )
                transition = (
                    (spec.supersedes_id, "superseded")
                    if spec.supersedes_id is not None
                    else (spec.correction_of_id, "corrected")
                )
                if transition[0] is not None:
                    self._transition_locked(
                        connection,
                        transition[0],
                        to_status=transition[1],
                        now_ms=now_ms,
                        expected_from={"candidate", "approved"},
                    )
                connection.execute("COMMIT")
            except LayeredMemoryV1Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise LayeredMemoryV1Conflict(
                    "memory identity was concurrently claimed"
                ) from exc
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise LayeredMemoryV1Error("layered memory write failed") from exc
            row = self._row(connection, memory_id)
            if row is None:
                raise LayeredMemoryV1Denied("memory write read-back failed")
            record = self._parse(row, now_ms=now_ms)
            self._attest()
            return record

    def _transition_locked(
        self,
        connection: sqlite3.Connection,
        memory_id: str,
        *,
        to_status: str,
        now_ms: int,
        expected_from: set[str],
    ) -> None:
        row = self._row(connection, memory_id)
        if row is None:
            raise LayeredMemoryV1Denied("memory transition target is unavailable")
        record = self._parse(row, now_ms=now_ms)
        if record.status == to_status:
            return
        if record.status not in expected_from or now_ms < record.created_at_ms:
            raise LayeredMemoryV1Conflict("memory lifecycle transition denied")
        payload = _strict_json(str(row[5]))
        payload["status"] = to_status
        payload["updated_at_ms"] = now_ms
        payload["hmac_sha256"] = _payload_mac(payload, self._integrity_key)
        cursor = connection.execute(
            "UPDATE memory_metadata SET status=?,payload_json=?,updated_at=? "
            "WHERE memory_metadata_id=? AND workspace_id=? AND status=?",
            (
                to_status,
                _canonical(payload).decode("utf-8"),
                str(now_ms),
                memory_id,
                self.workspace_id,
                record.status,
            ),
        )
        if cursor.rowcount != 1:
            raise LayeredMemoryV1Conflict("memory lifecycle changed concurrently")

    def transition(
        self,
        memory_id: str,
        *,
        to_status: str,
        now_ms: int,
    ) -> LayeredMemoryRecordV1:
        identifier = _atom("memory_id", memory_id)
        _timestamp("now_ms", now_ms)
        allowed = {
            "approved": {"candidate"},
            "rejected": {"candidate"},
        }
        if to_status not in allowed:
            raise LayeredMemoryV1ContractError(
                "unsupported explicit lifecycle transition"
            )
        with _WRITE_LOCK:
            connection = self._attest()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._transition_locked(
                    connection,
                    identifier,
                    to_status=to_status,
                    now_ms=now_ms,
                    expected_from=allowed[to_status],
                )
                connection.execute("COMMIT")
            except LayeredMemoryV1Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise LayeredMemoryV1Error("memory transition failed") from exc
            return self.get(identifier, now_ms=now_ms, include_terminal=True)

    def _scrub_locked(
        self,
        connection: sqlite3.Connection,
        memory_id: str,
        *,
        now_ms: int,
        reason: str,
        source_status: str,
    ) -> bool:
        row = self._row(connection, memory_id)
        if row is None:
            return False
        record = self._parse(row, now_ms=now_ms)
        if record.status == "deleted":
            return False
        if now_ms < record.created_at_ms:
            raise LayeredMemoryV1ContractError("deletion precedes memory creation")
        payload = _strict_json(str(row[5]))
        payload.update(
            {
                "entity_kind": "tombstone",
                "entity_key": "deleted",
                "entity_sha256": _entity_sha256("tombstone", "deleted"),
                "content": None,
                "source_ids": [],
                "source_status": source_status,
                "tags": [],
                "poison_signals": [],
                "status": "deleted",
                "updated_at_ms": now_ms,
                "deleted_at_ms": now_ms,
                "deletion_reason": reason,
            }
        )
        payload["hmac_sha256"] = _payload_mac(payload, self._integrity_key)
        cursor = connection.execute(
            "UPDATE memory_metadata SET status='deleted',payload_json=?,updated_at=? "
            "WHERE memory_metadata_id=? AND workspace_id=? AND status=?",
            (
                _canonical(payload).decode("utf-8"),
                str(now_ms),
                memory_id,
                self.workspace_id,
                record.status,
            ),
        )
        if cursor.rowcount != 1:
            raise LayeredMemoryV1Conflict("memory deletion changed concurrently")
        return True

    def delete(
        self,
        memory_id: str,
        *,
        now_ms: int,
        reason: str = "principal_request",
    ) -> LayeredMemoryRecordV1:
        identifier = _atom("memory_id", memory_id)
        deletion_reason = _atom("reason", reason)
        _timestamp("now_ms", now_ms)
        with _WRITE_LOCK:
            connection = self._attest()
            try:
                connection.execute("BEGIN IMMEDIATE")
                changed = self._scrub_locked(
                    connection,
                    identifier,
                    now_ms=now_ms,
                    reason=deletion_reason,
                    source_status="deleted",
                )
                if not changed and self._row(connection, identifier) is None:
                    raise LayeredMemoryV1Denied("memory deletion target is unavailable")
                connection.execute("COMMIT")
            except LayeredMemoryV1Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise LayeredMemoryV1Error("memory deletion failed") from exc
            return self.get(identifier, now_ms=now_ms, include_terminal=True)

    def _rows(self, connection: sqlite3.Connection) -> list[tuple[object, ...]]:
        try:
            rows = connection.execute(
                "SELECT memory_metadata_id,workspace_id,source_memory_id,"
                "schema_version,status,payload_json,created_at,updated_at "
                "FROM memory_metadata WHERE workspace_id=? "
                "AND memory_metadata_id LIKE ? ORDER BY memory_metadata_id LIMIT ?",
                (self.workspace_id, f"{ROW_PREFIX}%", MAX_RECORDS + 1),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise LayeredMemoryV1Denied("layered memory list failed") from exc
        if len(rows) > MAX_RECORDS:
            raise LayeredMemoryV1Denied("layered memory bound exceeded")
        return [tuple(row) for row in rows]

    def _principal_records(
        self,
        connection: sqlite3.Connection,
        *,
        now_ms: int,
        rows: list[tuple[object, ...]] | None = None,
    ) -> list[LayeredMemoryRecordV1]:
        selected = self._rows(connection) if rows is None else rows
        records: list[LayeredMemoryRecordV1] = []
        for row in selected:
            payload = _strict_json(str(row[5]))
            if payload.get("schema") != SCHEMA:
                raise LayeredMemoryV1Denied("layered memory schema drift")
            # A principal-bound key cannot authenticate a different
            # principal's record. The stable ID includes the principal and the
            # row is excluded before content parsing or ranking.
            if payload.get("principal_id") != self.principal_id:
                continue
            records.append(self._parse(row, now_ms=now_ms))
        return records

    def delete_source(self, source_id: str, *, now_ms: int) -> tuple[str, ...]:
        source = _atom("source_id", source_id)
        _timestamp("now_ms", now_ms)
        with _WRITE_LOCK:
            connection = self._attest()
            records = self._principal_records(connection, now_ms=now_ms)
            targets = tuple(
                record.memory_id
                for record in records
                if record.status != "deleted" and source in record.source_ids
            )
            try:
                connection.execute("BEGIN IMMEDIATE")
                for memory_id in targets:
                    self._scrub_locked(
                        connection,
                        memory_id,
                        now_ms=now_ms,
                        reason=f"source_deleted:{source}",
                        source_status="deleted",
                    )
                connection.execute("COMMIT")
            except LayeredMemoryV1Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise LayeredMemoryV1Error("source deletion failed") from exc
            self._attest()
            return targets

    def enforce_retention(self, *, now_ms: int) -> tuple[str, ...]:
        _timestamp("now_ms", now_ms)
        with _WRITE_LOCK:
            connection = self._attest()
            records = self._principal_records(connection, now_ms=now_ms)
            targets = tuple(
                record.memory_id
                for record in records
                if record.status != "deleted"
                and record.retention_until_ms is not None
                and now_ms >= record.retention_until_ms
            )
            try:
                connection.execute("BEGIN IMMEDIATE")
                for memory_id in targets:
                    self._scrub_locked(
                        connection,
                        memory_id,
                        now_ms=now_ms,
                        reason="retention_expired",
                        source_status="deleted",
                    )
                connection.execute("COMMIT")
            except LayeredMemoryV1Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise LayeredMemoryV1Error("retention enforcement failed") from exc
            self._attest()
            return targets

    def search(
        self,
        query: LayeredMemoryQueryV1,
        *,
        now_ms: int,
    ) -> tuple[LayeredMemoryRecordV1, ...]:
        if type(query) is not LayeredMemoryQueryV1:
            raise LayeredMemoryV1ContractError("exact layered memory query required")
        _timestamp("now_ms", now_ms)
        connection = self._attest()
        # Authorization, lifecycle, source, validity, sensitivity and freshness
        # filters are completed before any rank score is computed.
        snapshot = self._rows(connection)
        eligible: list[LayeredMemoryRecordV1] = []
        for record in self._principal_records(
            connection,
            now_ms=now_ms,
            rows=snapshot,
        ):
            if (
                record.status not in RETRIEVABLE_STATUSES
                or record.layer not in query.layers
                or record.sensitivity not in query.allowed_sensitivities
                or record.source_status != "available"
                or record.freshness in {"invalid", "deleted"}
                or (record.freshness == "stale" and not query.include_stale)
                or record.content is None
            ):
                continue
            eligible.append(record)
        query_tokens = frozenset(_TOKEN.findall(query.text.casefold()))
        ranked: list[LayeredMemoryRecordV1] = []
        for record in eligible:
            haystack = f"{record.content} {record.entity_kind} {record.entity_key} {' '.join(record.tags)}"
            tokens = frozenset(_TOKEN.findall(haystack.casefold()))
            overlap = len(query_tokens & tokens) / max(1, len(query_tokens))
            if query_tokens and overlap == 0:
                continue
            score = round(
                overlap * 0.70
                + (record.confidence_bp / 10_000) * 0.20
                + (0.10 if record.freshness == "fresh" else 0.03),
                12,
            )
            ranked.append(replace(record, score=float(score)))
        ranked.sort(key=lambda item: (-item.score, -item.updated_at_ms, item.memory_id))
        # A second exact snapshot prevents returning data across a concurrent
        # lifecycle or authorization change.
        if self._rows(connection) != snapshot:
            raise LayeredMemoryV1Denied("layered memory changed during retrieval")
        self._attest()
        return tuple(ranked[: query.limit])

    def export(
        self,
        *,
        now_ms: int,
        allowed_sensitivities: tuple[str, ...],
        include_deleted: bool = False,
    ) -> dict[str, object]:
        _timestamp("now_ms", now_ms)
        if (
            type(allowed_sensitivities) is not tuple
            or not allowed_sensitivities
            or len(set(allowed_sensitivities)) != len(allowed_sensitivities)
            or any(value not in SENSITIVITIES for value in allowed_sensitivities)
        ):
            raise LayeredMemoryV1ContractError("export sensitivities are invalid")
        if type(include_deleted) is not bool:
            raise LayeredMemoryV1ContractError("include_deleted must be exact bool")
        connection = self._attest()
        records: list[dict[str, object]] = []
        rows = self._rows(connection)
        principal_ids = {
            record.memory_id
            for record in self._principal_records(
                connection,
                now_ms=now_ms,
                rows=rows,
            )
        }
        for row in rows:
            if row[0] not in principal_ids:
                continue
            record = self._parse(row, now_ms=now_ms)
            if record.sensitivity not in allowed_sensitivities or (
                record.status == "deleted" and not include_deleted
            ):
                continue
            item = _strict_json(str(row[5]))
            item.pop("hmac_sha256")
            item.pop("key_fingerprint_sha256")
            records.append(item)
        payload: dict[str, object] = {
            "schema": "OnyxLayeredMemoryExport.v1",
            "workspace_id": self.workspace_id,
            "principal_id": self.principal_id,
            "generated_at_ms": now_ms,
            "record_count": len(records),
            "records": records,
            "content_trust": "untrusted_data",
            "instructions_authority": False,
        }
        payload["export_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
        self._attest()
        return payload


def create_layered_memory_catalog_v1(
    *,
    gate: LayeredMemoryFeatureGateV1 | None = None,
    registry: WorkspaceRegistry | None = None,
    workspace_id: str | None = None,
    principal_id: str | None = None,
    integrity_key: bytes | None = None,
    project_root: Path | str | None = None,
) -> LayeredMemoryCatalogV1 | None:
    selected = LayeredMemoryFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not LayeredMemoryFeatureGateV1:
        raise LayeredMemoryV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    if (
        registry is None
        or workspace_id is None
        or principal_id is None
        or integrity_key is None
    ):
        raise LayeredMemoryV1ContractError(
            "enabled catalog requires complete host bindings"
        )
    return LayeredMemoryCatalogV1(
        construction_key=_CONSTRUCTION_KEY,
        registry=registry,
        workspace_id=workspace_id,
        principal_id=principal_id,
        integrity_key=integrity_key,
    )


__all__ = [
    "ENABLED_VALUE",
    "FEATURE_FLAG",
    "LAYERS",
    "LIFECYCLE_STATUSES",
    "LayeredMemoryCatalogV1",
    "LayeredMemoryFeatureGateV1",
    "LayeredMemoryQueryV1",
    "LayeredMemoryRecordV1",
    "LayeredMemorySpecV1",
    "LayeredMemoryV1Conflict",
    "LayeredMemoryV1ContractError",
    "LayeredMemoryV1Denied",
    "LayeredMemoryV1Error",
    "ROW_PREFIX",
    "SCHEMA",
    "SCHEMA_VERSION",
    "SENSITIVITIES",
    "WORKSPACE_MEMORY_ENTRY_ROOTS",
    "create_layered_memory_catalog_v1",
    "layered_memory_id_v1",
]
