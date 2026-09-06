"""Default-off, pre-ranking workspace memory adapter for Phase 7.

The adapter reads workspace authorization metadata first, then opens the
existing MemoryStore database read-only and fetches only authorized record
IDs. It never calls the legacy global search/list methods.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from core.control_plane import ControlPlaneStore
from core.workspaces import (
    LEGACY_WORKSPACE_ID,
    WorkspaceError,
    WorkspaceRecord,
    WorkspaceRegistry,
)
from memory.store import MemoryRecord, MemoryStore


FEATURE_FLAG: Final = "ONYX_PHASE7_WORKSPACE_MEMORY_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxWorkspaceMemoryMetadata.v1"
MAX_METADATA_ROWS: Final = 10_000
MAX_QUERY_CHARS: Final = 2_000
MAX_RESULTS: Final = 50
SENSITIVITIES: Final = ("public", "internal", "confidential", "restricted")
RETRIEVABLE_SENSITIVITIES: Final = frozenset(SENSITIVITIES[:-1])
_WORKSPACE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_PRINCIPAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)
_EXPECTED_MEMORY_COLUMNS = (
    "id",
    "kind",
    "content",
    "source",
    "citation",
    "created_at",
    "updated_at",
    "salience",
    "session_id",
    "task_id",
    "category",
    "memory_key",
    "metadata_json",
    "content_hash",
    "access_count",
    "last_accessed_at",
)
_CONSTRUCTION_KEY = object()
PHASE6_EXIT_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase6-exit-candidate-v1/manifest.json",
        "6c32277bcbf17130eb60103538de6b58966a43dcd6b30a12c2aaf1e2e4b6493d",
    ),
    (
        "docs/onyx/acceptance/VE-P6-EXIT-CANDIDATE-V1-E6-001.md",
        "6e3fa587a55be54dc9da3db03e56d01fa0ad8197284b9c1f012e2d4c80e75d21",
    ),
    (
        "docs/onyx/acceptance/VE-P6-EXIT-CANDIDATE-V1-E6-001.manifest.json",
        "148505d6f49cf297aa6cc55b5eee0a2ac2bde5a2d9ac81051d865de470c4501d",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P6-EXIT-CANDIDATE-V1-E6-001.sha256",
        "2da850020ec9ac60ebfb2bdc652bb1cd4d14b61cbd19a6214291d10bba760877",
    ),
)


class WorkspaceMemoryV1Error(RuntimeError):
    """Base error for the Phase 7 memory adapter."""


class WorkspaceMemoryV1ContractError(ValueError):
    """An input or stored contract is malformed."""


class WorkspaceMemoryV1Denied(PermissionError):
    """Workspace, principal, policy, integrity, or lifecycle drift denied access."""


@dataclass(frozen=True, slots=True)
class WorkspaceMemoryFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise WorkspaceMemoryV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls,
        environ: dict[str, str] | os._Environ[str] | None = None,
    ) -> "WorkspaceMemoryFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class WorkspaceMemoryQueryV1:
    text: str
    limit: int = 8
    include_stale: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.text) is not str
            or not self.text.strip()
            or len(self.text) > MAX_QUERY_CHARS
        ):
            raise WorkspaceMemoryV1ContractError("query text is invalid")
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_RESULTS:
            raise WorkspaceMemoryV1ContractError("query limit is invalid")
        if type(self.include_stale) is not bool:
            raise WorkspaceMemoryV1ContractError("include_stale must be exact bool")


@dataclass(frozen=True, slots=True)
class WorkspaceMemoryResultV1:
    memory_id: str
    workspace_id: str
    principal_id: str
    content: str
    source: str
    citation: str
    memory_kind: str
    memory_status: str
    sensitivity: str
    freshness: str
    source_ids: tuple[str, ...]
    updated_at: str
    valid_until_ms: int | None
    fresh_until_ms: int
    memory_sha256: str
    content_trust: str
    score: float

    def __post_init__(self) -> None:
        if (
            not _SOURCE_ID.fullmatch(self.memory_id)
            or not _WORKSPACE_ID.fullmatch(self.workspace_id)
            or self.workspace_id == LEGACY_WORKSPACE_ID
            or not _PRINCIPAL_ID.fullmatch(self.principal_id)
            or self.memory_kind not in {"semantic", "episodic"}
            or self.memory_status != "approved"
            or self.sensitivity not in RETRIEVABLE_SENSITIVITIES
            or self.freshness not in {"fresh", "stale"}
            or type(self.source_ids) is not tuple
            or not self.source_ids
            or any(not _SOURCE_ID.fullmatch(value) for value in self.source_ids)
            or (
                self.valid_until_ms is not None
                and (type(self.valid_until_ms) is not int or self.valid_until_ms < 0)
            )
            or type(self.fresh_until_ms) is not int
            or self.fresh_until_ms < 0
            or not _HEX64.fullmatch(self.memory_sha256)
            or self.content_trust != "untrusted_data"
            or type(self.score) is not float
            or self.score < 0
        ):
            raise WorkspaceMemoryV1ContractError("memory result contract drift")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WorkspaceMemoryV1ContractError("value is not canonical JSON") from exc


def _exact_key(value: bytes) -> bytes:
    if type(value) is not bytes or not 32 <= len(value) <= 64 or not any(value):
        raise WorkspaceMemoryV1ContractError(
            "integrity key must be 32-64 non-zero bytes"
        )
    return value


def _validate_workspace_id(value: str) -> str:
    if (
        type(value) is not str
        or not _WORKSPACE_ID.fullmatch(value)
        or value == LEGACY_WORKSPACE_ID
    ):
        raise WorkspaceMemoryV1ContractError(
            "explicit non-legacy workspace_id required"
        )
    return value


def _validate_principal_id(value: str) -> str:
    if type(value) is not str or not _PRINCIPAL_ID.fullmatch(value):
        raise WorkspaceMemoryV1ContractError("principal_id is invalid")
    return value


def _validate_sensitivities(value: tuple[str, ...]) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or not value
        or len(set(value)) != len(value)
        or any(item not in RETRIEVABLE_SENSITIVITIES for item in value)
    ):
        raise WorkspaceMemoryV1ContractError(
            "allowed sensitivities must be an exact non-restricted tuple"
        )
    return value


def _memory_payload(record: MemoryRecord) -> dict[str, object]:
    if type(record) is not MemoryRecord:
        raise WorkspaceMemoryV1ContractError("exact MemoryRecord required")
    return {
        "id": record.id,
        "kind": record.kind,
        "content": record.content,
        "source": record.source,
        "citation": record.citation,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "salience": record.salience,
        "session_id": record.session_id,
        "task_id": record.task_id,
        "category": record.category,
        "key": record.key,
        "metadata": record.metadata or {},
    }


def memory_record_sha256_v1(record: MemoryRecord) -> str:
    """Bind the exact existing memory row without its derived search score."""

    return hashlib.sha256(_canonical(_memory_payload(record))).hexdigest()


def _metadata_unsigned(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "hmac_sha256"}


def _metadata_mac(payload: dict[str, object], integrity_key: bytes) -> str:
    return hmac.new(
        _exact_key(integrity_key),
        _canonical(_metadata_unsigned(payload)),
        hashlib.sha256,
    ).hexdigest()


def build_workspace_memory_metadata_v1(
    *,
    record: MemoryRecord,
    workspace_id: str,
    principal_id: str,
    sensitivity: str,
    source_ids: tuple[str, ...],
    valid_from_ms: int,
    valid_until_ms: int | None,
    fresh_until_ms: int,
    integrity_key: bytes,
    memory_status: str = "approved",
    source_status: str = "available",
) -> dict[str, object]:
    """Build signed sidecar metadata; this function performs no persistence."""

    workspace = _validate_workspace_id(workspace_id)
    principal = _validate_principal_id(principal_id)
    key = _exact_key(integrity_key)
    if sensitivity not in SENSITIVITIES:
        raise WorkspaceMemoryV1ContractError("sensitivity is invalid")
    if memory_status not in {
        "candidate",
        "approved",
        "superseded",
        "rejected",
    }:
        raise WorkspaceMemoryV1ContractError("memory status is invalid")
    if source_status not in {"available", "deleted", "revoked"}:
        raise WorkspaceMemoryV1ContractError("source status is invalid")
    if (
        type(source_ids) is not tuple
        or not 1 <= len(source_ids) <= 32
        or len(set(source_ids)) != len(source_ids)
        or any(
            type(value) is not str or not _SOURCE_ID.fullmatch(value)
            for value in source_ids
        )
    ):
        raise WorkspaceMemoryV1ContractError("source_ids are invalid")
    if (
        type(valid_from_ms) is not int
        or valid_from_ms < 0
        or (
            valid_until_ms is not None
            and (type(valid_until_ms) is not int or valid_until_ms <= valid_from_ms)
        )
        or type(fresh_until_ms) is not int
        or fresh_until_ms < valid_from_ms
    ):
        raise WorkspaceMemoryV1ContractError("validity window is invalid")
    payload: dict[str, object] = {
        "schema": SCHEMA,
        "workspace_id": workspace,
        "source_memory_id": record.id,
        "principal_id": principal,
        "sensitivity": sensitivity,
        "memory_status": memory_status,
        "source_status": source_status,
        "source_ids": list(source_ids),
        "valid_from_ms": valid_from_ms,
        "valid_until_ms": valid_until_ms,
        "fresh_until_ms": fresh_until_ms,
        "memory_sha256": memory_record_sha256_v1(record),
        "key_fingerprint_sha256": hashlib.sha256(key).hexdigest(),
    }
    payload["hmac_sha256"] = _metadata_mac(payload, key)
    return payload


def workspace_memory_metadata_id_v1(*, workspace_id: str, source_memory_id: str) -> str:
    workspace = _validate_workspace_id(workspace_id)
    if type(source_memory_id) is not str or not _SOURCE_ID.fullmatch(source_memory_id):
        raise WorkspaceMemoryV1ContractError("source_memory_id is invalid")
    digest = hashlib.sha256(
        f"{SCHEMA}\0{workspace}\0{source_memory_id}".encode("utf-8")
    ).hexdigest()
    return f"wmem_{digest[:24]}"


def _strict_json(text: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise WorkspaceMemoryV1Denied(f"duplicate metadata key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except (TypeError, json.JSONDecodeError) as exc:
        raise WorkspaceMemoryV1Denied("workspace memory metadata is invalid") from exc
    if type(value) is not dict:
        raise WorkspaceMemoryV1Denied("workspace memory metadata must be an object")
    return value


def _verify_phase6_entry(project_root: Path | str) -> None:
    try:
        lexical_root = Path(project_root).absolute()
        root_info = os.lstat(lexical_root)
        root = lexical_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceMemoryV1Denied("Phase 6 entry root is unavailable") from exc
    if (
        root != lexical_root
        or not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or _is_reparse(root_info)
    ):
        raise WorkspaceMemoryV1Denied("Phase 6 entry root is not canonical")
    payloads: dict[str, bytes] = {}
    for relative, expected in PHASE6_EXIT_ROOTS:
        value = Path(relative)
        if value.is_absolute() or ".." in value.parts:
            raise WorkspaceMemoryV1Denied("Phase 6 entry path is unsafe")
        path = root.joinpath(*value.parts)
        try:
            info = os.lstat(path)
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            payload = resolved.read_bytes()
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkspaceMemoryV1Denied(
                "Phase 6 entry evidence is unavailable"
            ) from exc
        if (
            resolved != path.absolute()
            or not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or _is_reparse(info)
            or hashlib.sha256(payload).hexdigest() != expected
        ):
            raise WorkspaceMemoryV1Denied("Phase 6 entry evidence drift denied")
        payloads[relative] = payload
    metadata_path = "docs/onyx/acceptance/VE-P6-EXIT-CANDIDATE-V1-E6-001.manifest.json"
    try:
        metadata_text = payloads[metadata_path].decode("utf-8")
    except UnicodeError as exc:
        raise WorkspaceMemoryV1Denied("Phase 6 entry metadata is not UTF-8") from exc
    metadata = _strict_json(metadata_text)
    claims = metadata.get("claims")
    if (
        metadata.get("acceptance_id") != "VE-P6-EXIT-CANDIDATE-V1-E6-001"
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or type(claims) is not dict
        or claims.get("phase6_exit_complete") is not True
        or claims.get("phase7_default_off_implementation_unlocked") is not True
        or claims.get("runtime_authority_added") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise WorkspaceMemoryV1Denied("Phase 6 entry acceptance contract drift")


def _validate_metadata(
    *,
    payload: dict[str, object],
    row_workspace_id: str,
    row_memory_id: str,
    workspace_id: str,
    key: bytes,
) -> None:
    expected_keys = {
        "schema",
        "workspace_id",
        "source_memory_id",
        "principal_id",
        "sensitivity",
        "memory_status",
        "source_status",
        "source_ids",
        "valid_from_ms",
        "valid_until_ms",
        "fresh_until_ms",
        "memory_sha256",
        "key_fingerprint_sha256",
        "hmac_sha256",
    }
    source_ids = payload.get("source_ids")
    if (
        set(payload) != expected_keys
        or payload.get("schema") != SCHEMA
        or payload.get("workspace_id") != row_workspace_id
        or row_workspace_id != workspace_id
        or payload.get("source_memory_id") != row_memory_id
        or type(payload.get("principal_id")) is not str
        or not _PRINCIPAL_ID.fullmatch(payload["principal_id"])
        or payload.get("sensitivity") not in SENSITIVITIES
        or payload.get("memory_status")
        not in {"candidate", "approved", "superseded", "rejected"}
        or payload.get("source_status") not in {"available", "deleted", "revoked"}
        or type(source_ids) is not list
        or not 1 <= len(source_ids) <= 32
        or len(set(source_ids)) != len(source_ids)
        or any(
            type(value) is not str or not _SOURCE_ID.fullmatch(value)
            for value in source_ids
        )
        or type(payload.get("valid_from_ms")) is not int
        or payload["valid_from_ms"] < 0
        or (
            payload.get("valid_until_ms") is not None
            and (
                type(payload["valid_until_ms"]) is not int
                or payload["valid_until_ms"] <= payload["valid_from_ms"]
            )
        )
        or type(payload.get("fresh_until_ms")) is not int
        or payload["fresh_until_ms"] < payload["valid_from_ms"]
        or type(payload.get("memory_sha256")) is not str
        or not _HEX64.fullmatch(payload["memory_sha256"])
        or payload.get("key_fingerprint_sha256") != hashlib.sha256(key).hexdigest()
        or type(payload.get("hmac_sha256")) is not str
        or not _HEX64.fullmatch(payload["hmac_sha256"])
        or not hmac.compare_digest(payload["hmac_sha256"], _metadata_mac(payload, key))
    ):
        raise WorkspaceMemoryV1Denied("workspace memory metadata integrity denied")


def _is_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _memory_file_identity(path: Path) -> tuple[int, int, int, int, int]:
    try:
        info = os.lstat(path)
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceMemoryV1Denied("memory database is unavailable") from exc
    if (
        resolved != path.absolute()
        or stat.S_ISLNK(info.st_mode)
        or _is_reparse(info)
        or not stat.S_ISREG(info.st_mode)
    ):
        raise WorkspaceMemoryV1Denied(
            "memory database must be a canonical regular file"
        )
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _tokens(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN.findall(value)]


def _lexical_score(query_tokens: list[str], content: str) -> float:
    if not query_tokens:
        return 1.0
    counts: dict[str, int] = {}
    for term in _tokens(content):
        counts[term] = counts.get(term, 0) + 1
    score = 0.0
    for query in set(query_tokens):
        frequency = counts.get(query, 0)
        if frequency:
            score += (frequency * 2.2) / (frequency + 1.2)
    return score / max(1, len(set(query_tokens)))


def _recency_score(updated_at: str, now_ms: int) -> float:
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        days = max(0.0, (now - updated).total_seconds() / 86400)
        return math.exp(-days / 180.0)
    except (ValueError, TypeError, OverflowError):
        return 0.0


def _row_to_memory(row: sqlite3.Row) -> MemoryRecord:
    try:
        metadata = json.loads(row["metadata_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise WorkspaceMemoryV1Denied("legacy memory metadata is invalid") from exc
    if type(metadata) is not dict:
        raise WorkspaceMemoryV1Denied("legacy memory metadata must be an object")
    return MemoryRecord(
        id=row["id"],
        kind=row["kind"],
        content=row["content"],
        source=row["source"],
        citation=row["citation"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        salience=float(row["salience"]),
        session_id=row["session_id"],
        task_id=row["task_id"],
        category=row["category"],
        key=row["memory_key"],
        metadata=metadata,
        score=0.0,
    )


class WorkspaceMemoryAdapterV1:
    """Sealed, read-only hard-filter adapter over one workspace and principal."""

    __slots__ = (
        "_registry",
        "_control_store",
        "_memory_store",
        "_workspace",
        "_principal_id",
        "_allowed_sensitivities",
        "_integrity_key",
        "_key_fingerprint",
        "_control_connection_id",
        "_control_path",
        "_memory_path",
        "_memory_identity",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        registry: WorkspaceRegistry,
        memory_store: MemoryStore,
        workspace_id: str,
        principal_id: str,
        allowed_sensitivities: tuple[str, ...],
        integrity_key: bytes,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise WorkspaceMemoryV1ContractError(
                "use create_workspace_memory_adapter_v1"
            )
        if (
            type(registry) is not WorkspaceRegistry
            or type(memory_store) is not MemoryStore
        ):
            raise WorkspaceMemoryV1ContractError(
                "exact WorkspaceRegistry and MemoryStore required"
            )
        if registry.enabled is not True or not registry.store.is_open:
            raise WorkspaceMemoryV1Denied(
                "initialized enabled workspace registry required"
            )
        if memory_store._initialized is not True:
            raise WorkspaceMemoryV1Denied("initialized MemoryStore required")
        try:
            workspace = registry.require_active(_validate_workspace_id(workspace_id))
        except WorkspaceError as exc:
            raise WorkspaceMemoryV1Denied("active workspace binding denied") from exc
        memory_path = memory_store.path.absolute()
        self._registry = registry
        self._control_store = registry.store
        self._memory_store = memory_store
        self._workspace = workspace
        self._principal_id = _validate_principal_id(principal_id)
        self._allowed_sensitivities = _validate_sensitivities(allowed_sensitivities)
        self._integrity_key = _exact_key(integrity_key)
        self._key_fingerprint = hashlib.sha256(self._integrity_key).hexdigest()
        self._control_connection_id = id(registry.store._require_connection())
        self._control_path = registry.store.path.absolute()
        self._memory_path = memory_path
        self._memory_identity = _memory_file_identity(memory_path)

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("WorkspaceMemoryAdapterV1 cannot be subclassed")

    def __copy__(self) -> object:
        raise TypeError("WorkspaceMemoryAdapterV1 cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("WorkspaceMemoryAdapterV1 cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("WorkspaceMemoryAdapterV1 cannot be serialized")

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
            or type(self._control_store) is not ControlPlaneStore
            or type(self._memory_store) is not MemoryStore
            or self._registry.store is not self._control_store
            or self._registry.enabled is not True
            or not self._control_store.is_open
            or self._control_store.path.absolute() != self._control_path
            or self._memory_store.path.absolute() != self._memory_path
            or self._memory_store._initialized is not True
            or hashlib.sha256(self._integrity_key).hexdigest() != self._key_fingerprint
            or _memory_file_identity(self._memory_path) != self._memory_identity
        ):
            raise WorkspaceMemoryV1Denied("adapter binding drift denied")
        connection = self._control_store._require_connection()
        if id(connection) != self._control_connection_id:
            raise WorkspaceMemoryV1Denied("control-plane connection drift denied")
        try:
            current = self._registry.require_active(self.workspace_id)
        except WorkspaceError as exc:
            raise WorkspaceMemoryV1Denied(
                "active workspace attestation denied"
            ) from exc
        if type(current) is not WorkspaceRecord or current != self._workspace:
            raise WorkspaceMemoryV1Denied("workspace identity drift denied")
        return connection

    def _metadata_rows(
        self, connection: sqlite3.Connection
    ) -> list[tuple[object, ...]]:
        try:
            rows = connection.execute(
                "SELECT memory_metadata_id,workspace_id,source_memory_id,"
                "schema_version,status,payload_json,created_at,updated_at "
                "FROM memory_metadata WHERE workspace_id=? "
                "ORDER BY source_memory_id,memory_metadata_id LIMIT ?",
                (self.workspace_id, MAX_METADATA_ROWS + 1),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise WorkspaceMemoryV1Denied(
                "workspace memory metadata query failed"
            ) from exc
        if len(rows) > MAX_METADATA_ROWS:
            raise WorkspaceMemoryV1Denied("workspace memory metadata bound exceeded")
        return [tuple(row) for row in rows]

    @staticmethod
    def _ambiguous_memory_ids(
        connection: sqlite3.Connection, memory_ids: tuple[str, ...]
    ) -> frozenset[str]:
        if not memory_ids:
            return frozenset()
        ambiguous: set[str] = set()
        try:
            for offset in range(0, len(memory_ids), 400):
                chunk = memory_ids[offset : offset + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    "SELECT source_memory_id FROM memory_metadata "
                    f"WHERE source_memory_id IN ({placeholders}) "
                    "GROUP BY source_memory_id "
                    "HAVING count(DISTINCT workspace_id)>1",
                    chunk,
                ).fetchall()
                ambiguous.update(str(row[0]) for row in rows)
        except sqlite3.DatabaseError as exc:
            raise WorkspaceMemoryV1Denied(
                "workspace ownership ambiguity check failed"
            ) from exc
        return frozenset(ambiguous)

    def _authorized_metadata(
        self,
        connection: sqlite3.Connection,
        *,
        now_ms: int,
        include_stale: bool,
    ) -> dict[str, tuple[dict[str, object], str]]:
        rows = self._metadata_rows(connection)
        ids: list[str] = []
        parsed: list[tuple[str, dict[str, object]]] = []
        for (
            metadata_id,
            row_workspace,
            memory_id,
            schema_version,
            row_status,
            payload_json,
            _created_at,
            _updated_at,
        ) in rows:
            if (
                type(metadata_id) is not str
                or not _SOURCE_ID.fullmatch(metadata_id)
                or row_workspace != self.workspace_id
                or type(memory_id) is not str
                or not _SOURCE_ID.fullmatch(memory_id)
                or schema_version != 1
                or type(row_status) is not str
                or type(payload_json) is not str
            ):
                raise WorkspaceMemoryV1Denied(
                    "workspace memory row contract drift denied"
                )
            if row_status != "active":
                continue
            payload = _strict_json(payload_json)
            _validate_metadata(
                payload=payload,
                row_workspace_id=row_workspace,
                row_memory_id=memory_id,
                workspace_id=self.workspace_id,
                key=self._integrity_key,
            )
            ids.append(memory_id)
            parsed.append((memory_id, payload))
        ambiguous = self._ambiguous_memory_ids(connection, tuple(ids))
        authorized: dict[str, tuple[dict[str, object], str]] = {}
        for memory_id, payload in parsed:
            if memory_id in ambiguous:
                continue
            valid_until = payload["valid_until_ms"]
            if (
                payload["principal_id"] != self.principal_id
                or payload["sensitivity"] not in self._allowed_sensitivities
                or payload["sensitivity"] == "restricted"
                or payload["memory_status"] != "approved"
                or payload["source_status"] != "available"
                or now_ms < payload["valid_from_ms"]
                or (valid_until is not None and now_ms >= valid_until)
            ):
                continue
            freshness = "fresh" if now_ms <= payload["fresh_until_ms"] else "stale"
            if freshness == "stale" and not include_stale:
                continue
            if memory_id in authorized:
                raise WorkspaceMemoryV1Denied(
                    "duplicate authorized memory identity denied"
                )
            authorized[memory_id] = (payload, freshness)
        return authorized

    def _read_memories(
        self, authorized: dict[str, tuple[dict[str, object], str]]
    ) -> dict[str, MemoryRecord]:
        if not authorized:
            return {}
        before = _memory_file_identity(self._memory_path)
        if before != self._memory_identity:
            raise WorkspaceMemoryV1Denied("memory database drift denied")
        connection: sqlite3.Connection | None = None
        try:
            uri = f"{self._memory_path.as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            data_version_before = int(
                connection.execute("PRAGMA data_version").fetchone()[0]
            )
            connection.execute("BEGIN")
            columns = tuple(
                str(row[1])
                for row in connection.execute("PRAGMA table_info(memories)").fetchall()
            )
            version = connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            if (
                columns != _EXPECTED_MEMORY_COLUMNS
                or version is None
                or tuple(version) != ("1",)
            ):
                raise WorkspaceMemoryV1Denied("MemoryStore schema drift denied")
            records: dict[str, MemoryRecord] = {}
            for memory_id, (payload, _freshness) in authorized.items():
                row = connection.execute(
                    "SELECT * FROM memories WHERE id=?",
                    (memory_id,),
                ).fetchone()
                if row is None:
                    raise WorkspaceMemoryV1Denied(
                        "authorized memory reference is unavailable"
                    )
                record = _row_to_memory(row)
                if record.id != memory_id or not hmac.compare_digest(
                    memory_record_sha256_v1(record),
                    payload["memory_sha256"],
                ):
                    raise WorkspaceMemoryV1Denied(
                        "authorized memory content drift denied"
                    )
                records[memory_id] = record
            connection.execute("COMMIT")
            data_version_after = int(
                connection.execute("PRAGMA data_version").fetchone()[0]
            )
            if data_version_after != data_version_before:
                raise WorkspaceMemoryV1Denied(
                    "MemoryStore changed during read-only snapshot"
                )
            return records
        except WorkspaceMemoryV1Error:
            raise
        except sqlite3.DatabaseError as exc:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            raise WorkspaceMemoryV1Denied("read-only MemoryStore query failed") from exc
        finally:
            if connection is not None:
                connection.close()
            if _memory_file_identity(self._memory_path) != before:
                raise WorkspaceMemoryV1Denied(
                    "memory database changed during retrieval"
                )

    def search(
        self,
        query: WorkspaceMemoryQueryV1,
        *,
        now_ms: int,
    ) -> tuple[WorkspaceMemoryResultV1, ...]:
        if type(query) is not WorkspaceMemoryQueryV1:
            raise WorkspaceMemoryV1ContractError("exact query required")
        if type(now_ms) is not int or now_ms < 0:
            raise WorkspaceMemoryV1ContractError("now_ms is invalid")
        connection = self._attest()
        authorized = self._authorized_metadata(
            connection,
            now_ms=now_ms,
            include_stale=query.include_stale,
        )
        records = self._read_memories(authorized)
        query_tokens = _tokens(query.text.strip())
        ranked: list[WorkspaceMemoryResultV1] = []
        for memory_id, record in records.items():
            metadata, freshness = authorized[memory_id]
            lexical = _lexical_score(
                query_tokens,
                f"{record.content} {record.source} {record.citation}",
            )
            if query_tokens and lexical <= 0:
                continue
            score = round(
                lexical * 0.75
                + record.salience * 0.15
                + _recency_score(record.updated_at, now_ms) * 0.10,
                12,
            )
            ranked.append(
                WorkspaceMemoryResultV1(
                    memory_id=record.id,
                    workspace_id=self.workspace_id,
                    principal_id=self.principal_id,
                    content=record.content,
                    source=record.source,
                    citation=record.citation,
                    memory_kind=record.kind,
                    memory_status="approved",
                    sensitivity=str(metadata["sensitivity"]),
                    freshness=freshness,
                    source_ids=tuple(metadata["source_ids"]),
                    updated_at=record.updated_at,
                    valid_until_ms=metadata["valid_until_ms"],
                    fresh_until_ms=metadata["fresh_until_ms"],
                    memory_sha256=str(metadata["memory_sha256"]),
                    content_trust="untrusted_data",
                    score=float(score),
                )
            )
        ranked.sort(
            key=lambda item: (
                -item.score,
                item.updated_at,
                item.memory_id,
            )
        )
        reattested = self._authorized_metadata(
            connection,
            now_ms=now_ms,
            include_stale=query.include_stale,
        )
        if reattested != authorized:
            raise WorkspaceMemoryV1Denied("workspace metadata changed during retrieval")
        self._attest()
        return tuple(ranked[: query.limit])


def create_workspace_memory_adapter_v1(
    *,
    gate: WorkspaceMemoryFeatureGateV1 | None = None,
    registry: WorkspaceRegistry | None = None,
    memory_store: MemoryStore | None = None,
    workspace_id: str | None = None,
    principal_id: str | None = None,
    allowed_sensitivities: tuple[str, ...] | None = None,
    integrity_key: bytes | None = None,
    project_root: Path | str | None = None,
) -> WorkspaceMemoryAdapterV1 | None:
    """Create the read-only adapter only behind the exact Phase 7 flag."""

    selected = WorkspaceMemoryFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not WorkspaceMemoryFeatureGateV1:
        raise WorkspaceMemoryV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_phase6_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    if (
        registry is None
        or memory_store is None
        or workspace_id is None
        or principal_id is None
        or allowed_sensitivities is None
        or integrity_key is None
    ):
        raise WorkspaceMemoryV1ContractError(
            "enabled adapter requires complete host bindings"
        )
    return WorkspaceMemoryAdapterV1(
        construction_key=_CONSTRUCTION_KEY,
        registry=registry,
        memory_store=memory_store,
        workspace_id=workspace_id,
        principal_id=principal_id,
        allowed_sensitivities=allowed_sensitivities,
        integrity_key=integrity_key,
    )


__all__ = [
    "ENABLED_VALUE",
    "FEATURE_FLAG",
    "MAX_METADATA_ROWS",
    "MAX_QUERY_CHARS",
    "MAX_RESULTS",
    "PHASE6_EXIT_ROOTS",
    "RETRIEVABLE_SENSITIVITIES",
    "SCHEMA",
    "SENSITIVITIES",
    "WorkspaceMemoryAdapterV1",
    "WorkspaceMemoryFeatureGateV1",
    "WorkspaceMemoryQueryV1",
    "WorkspaceMemoryResultV1",
    "WorkspaceMemoryV1ContractError",
    "WorkspaceMemoryV1Denied",
    "WorkspaceMemoryV1Error",
    "build_workspace_memory_metadata_v1",
    "create_workspace_memory_adapter_v1",
    "memory_record_sha256_v1",
    "workspace_memory_metadata_id_v1",
]
