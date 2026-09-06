"""Transactional, append-only, content-free owner tool audit."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from core.paths import runtime_dir
from memory.store import contains_secret

AUDIT_PATH = runtime_dir() / "audit" / "tool_audit.sqlite3"
_LOCK = threading.Lock()
_ZERO = "0" * 64
_SEMANTIC_ID_SECRET = re.compile(
    r"(?i)^(?:api[_-]?key|authorization|bearer|client[_-]?secret|password|"
    r"private[_-]?key|refresh[_-]?token|secret|token)[._:-][A-Za-z0-9._:-]{8,}$"
)
_EVENT_COLUMNS = (
    "timestamp",
    "principal",
    "profile",
    "tool",
    "action",
    "decision",
    "reason",
    "target_category",
    "arg_schema",
    "outcome",
    "error_type",
    "trace_id",
    "prev_hash",
    "event_hash",
)
_EXPECTED_TABLE_COLUMNS = {
    "meta": ("key", "value"),
    "events": ("id", *_EVENT_COLUMNS),
    "semantic_events_v2": (
        "trace_id",
        "semantic_digest",
        "contract_json",
        "event_hash",
    ),
}
_REQUIRED_TRIGGERS = {
    "events_no_update",
    "events_no_delete",
    "semantic_events_v2_no_update",
    "semantic_events_v2_no_delete",
}
_TRACE_INDEX = "idx_audit_events_trace_id"


class AuditIntegrityError(RuntimeError):
    pass


def _preserve_cleanup_failure(
    primary: BaseException | None, label: str, cleanup_error: BaseException
) -> None:
    if primary is not None:
        try:
            primary.add_note(f"{label} also failed ({type(cleanup_error).__name__})")
        except BaseException:
            pass
        return
    raise AuditIntegrityError(f"{label} failed") from cleanup_error


@dataclass(frozen=True, slots=True)
class AuditReference:
    """One durable member of the verified tool-audit chain."""

    trace_id: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class SemanticAuditReference:
    """One semantic-v2 decision and its exact legacy-chain member."""

    trace_id: str
    event_hash: str
    semantic_digest: str


_KNOWN_FIELDS = {
    "action",
    "path",
    "name",
    "destination",
    "new_name",
    "query",
    "mode",
    "city",
    "app_name",
    "receiver",
    "mission_id",
    "title",
    "file_path",
    "timeout",
    "category",
    "key",
}


def _shape(arguments: object) -> str:
    if not isinstance(arguments, dict):
        return "{}"
    known = sorted(str(key) for key in arguments if str(key) in _KNOWN_FIELDS)
    counts = {"scalar": 0, "list": 0, "map": 0, "unknown": 0}
    for key, value in arguments.items():
        if str(key) not in _KNOWN_FIELDS:
            counts["unknown"] += 1
        if isinstance(value, dict):
            counts["map"] += 1
        elif isinstance(value, list):
            counts["list"] += 1
        else:
            counts["scalar"] += 1
    return json.dumps(
        {"known_fields": known, "type_counts": counts},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _reject_persisted_strings(value: object, label: str, depth: int = 0) -> None:
    """Reject credential-shaped material in every durable audit string."""

    if depth > 24:
        raise AuditIntegrityError(f"{label} exceeds the nesting limit")
    if isinstance(value, str):
        if contains_secret(value):
            raise AuditIntegrityError(f"{label} contains secret material")
    elif isinstance(value, dict):
        for key, child in value.items():
            _reject_persisted_strings(key, label, depth + 1)
            _reject_persisted_strings(child, label, depth + 1)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_persisted_strings(child, label, depth + 1)


def _connect() -> sqlite3.Connection:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AUDIT_PATH, timeout=5, isolation_level=None)
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,principal TEXT NOT NULL,profile TEXT NOT NULL,tool TEXT NOT NULL,action TEXT NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL,target_category TEXT NOT NULL,arg_schema TEXT NOT NULL,outcome TEXT NOT NULL,error_type TEXT NOT NULL,trace_id TEXT NOT NULL,prev_hash TEXT NOT NULL,event_hash TEXT NOT NULL UNIQUE)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS semantic_events_v2(trace_id TEXT PRIMARY KEY,semantic_digest TEXT NOT NULL UNIQUE,contract_json TEXT NOT NULL CHECK(json_valid(contract_json)),event_hash TEXT NOT NULL UNIQUE,FOREIGN KEY(event_hash) REFERENCES events(event_hash)) WITHOUT ROWID"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'audit immutable'); END"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'audit immutable'); END"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS semantic_events_v2_no_update BEFORE UPDATE ON semantic_events_v2 BEGIN SELECT RAISE(ABORT,'audit semantic contract immutable'); END"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS semantic_events_v2_no_delete BEFORE DELETE ON semantic_events_v2 BEGIN SELECT RAISE(ABORT,'audit semantic contract immutable'); END"
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS {_TRACE_INDEX} ON events(trace_id)")
    conn.execute(
        "INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version','1'),('head',?),('count','0')",
        (_ZERO,),
    )
    if os.name != "nt":
        os.chmod(AUDIT_PATH, 0o600)
    return conn


def _validate_hot_schema(conn: sqlite3.Connection) -> None:
    """Validate the fixed audit tables, immutability guards and hot index."""

    for table, expected in _EXPECTED_TABLE_COLUMNS.items():
        columns = tuple(
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")
        )
        if columns != expected:
            raise AuditIntegrityError("audit schema is invalid")
    triggers = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name IN "
            "(?,?,?,?)",
            tuple(sorted(_REQUIRED_TRIGGERS)),
        )
    }
    if triggers != _REQUIRED_TRIGGERS:
        raise AuditIntegrityError("audit immutability schema is invalid")
    indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(events)")}
    if _TRACE_INDEX not in indexes:
        raise AuditIntegrityError("audit trace index is missing")
    indexed = tuple(
        str(row[2]) for row in conn.execute(f"PRAGMA index_info({_TRACE_INDEX})")
    )
    if indexed != ("trace_id",):
        raise AuditIntegrityError("audit trace index is invalid")


def _event_values(row: sqlite3.Row | tuple[object, ...]) -> list[object]:
    return list(row[:12])


def _verify_event_row(row: sqlite3.Row | tuple[object, ...]) -> str:
    values = _event_values(row)
    previous, event_hash = str(row[12]), str(row[13])
    _reject_persisted_strings(values, "audit event")
    canonical = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
    expected = hashlib.sha256((previous + canonical).encode()).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", previous) or event_hash != expected:
        raise AuditIntegrityError("audit event hash is invalid")
    return event_hash


def _verify_hot_head(conn: sqlite3.Connection) -> tuple[int, str]:
    """Verify only the bounded chain tail used by online operations."""

    _validate_hot_schema(conn)
    meta_rows = conn.execute(
        "SELECT key,value FROM meta ORDER BY key LIMIT 4"
    ).fetchall()
    meta = {str(row[0]): str(row[1]) for row in meta_rows}
    if len(meta_rows) != 3 or set(meta) != {"schema_version", "head", "count"}:
        raise AuditIntegrityError("audit metadata invalid")
    if meta["schema_version"] != "1" or not meta["count"].isdigit():
        raise AuditIntegrityError("audit metadata invalid")
    count = int(meta["count"])
    if count < 0 or not re.fullmatch(r"[0-9a-f]{64}", meta["head"]):
        raise AuditIntegrityError("audit metadata invalid")
    latest = conn.execute(
        "SELECT id,"
        + ",".join(_EVENT_COLUMNS)
        + " FROM events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if count == 0:
        if latest is not None or meta["head"] != _ZERO:
            raise AuditIntegrityError("audit metadata invalid")
        return 0, _ZERO
    if latest is None or int(latest[0]) != count:
        raise AuditIntegrityError("audit metadata invalid")
    event_hash = _verify_event_row(tuple(latest[1:]))
    previous = str(latest[-2])
    if event_hash != meta["head"]:
        raise AuditIntegrityError("audit head is invalid")
    if count == 1:
        if previous != _ZERO:
            raise AuditIntegrityError("audit head predecessor is invalid")
    else:
        predecessor = conn.execute(
            "SELECT id,event_hash FROM events WHERE id<? ORDER BY id DESC LIMIT 1",
            (count,),
        ).fetchone()
        if (
            predecessor is None
            or int(predecessor[0]) != count - 1
            or str(predecessor[1]) != previous
        ):
            raise AuditIntegrityError("audit head predecessor is invalid")
    return count, event_hash


def verify_audit(conn: sqlite3.Connection | None = None) -> tuple[int, str]:
    owned = conn is None
    db = conn or _connect()
    previous = _ZERO
    count = 0
    try:
        _validate_hot_schema(db)
        for row in db.execute(
            "SELECT timestamp,principal,profile,tool,action,decision,reason,target_category,arg_schema,outcome,error_type,trace_id,prev_hash,event_hash FROM events ORDER BY id"
        ):
            values = list(row[:-2])
            prev, event_hash = row[-2], row[-1]
            _reject_persisted_strings(values, "audit event")
            canonical = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
            expected = hashlib.sha256((previous + canonical).encode()).hexdigest()
            if prev != previous or event_hash != expected:
                raise AuditIntegrityError("audit chain invalid")
            previous = event_hash
            count += 1
        meta = dict(db.execute("SELECT key,value FROM meta"))
        if (
            meta.get("schema_version") != "1"
            or meta.get("head") != previous
            or meta.get("count") != str(count)
        ):
            raise AuditIntegrityError("audit metadata invalid")
        for row in db.execute(
            "SELECT trace_id,semantic_digest,contract_json "
            "FROM semantic_events_v2 ORDER BY trace_id"
        ):
            trace_id, digest, encoded = map(str, row)
            try:
                contract = _semantic_contract(json.loads(encoded))
            except json.JSONDecodeError as exc:
                raise AuditIntegrityError(
                    "semantic audit contract JSON is invalid"
                ) from exc
            if _select_semantic_reference(
                db,
                trace_id=trace_id,
                semantic_digest=_semantic_digest(contract),
                encoded=_canonical_object(contract),
            ) is None or digest != _semantic_digest(contract):
                raise AuditIntegrityError("semantic audit binding invalid")
        return count, previous
    finally:
        if owned:
            primary = sys.exception()
            try:
                db.close()
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "audit connection close", cleanup_error
                )


def append_tool_audit_reference(
    *,
    profile: str,
    tool: str,
    action: str,
    decision: str,
    reason: str,
    arguments: object = None,
    outcome: str = "decision",
    trace_id: str = "",
    error_type: str = "",
) -> AuditReference:
    """Append and return a reference while holding the chain writer lock."""

    with _LOCK:
        db = _connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            count, previous = _verify_hot_head(db)
            values = [
                datetime.now(timezone.utc).isoformat(),
                "local-owner",
                profile,
                tool[:80],
                action[:80],
                decision[:40],
                reason[:120],
                "local"
                if tool in {"file_controller", "file_processor", "code_helper"}
                else "tool",
                _shape(arguments),
                outcome[:40],
                error_type[:80],
                trace_id[:64],
            ]
            _reject_persisted_strings(values, "audit event")
            canonical = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
            event_hash = hashlib.sha256((previous + canonical).encode()).hexdigest()
            db.execute(
                "INSERT INTO events(timestamp,principal,profile,tool,action,decision,reason,target_category,arg_schema,outcome,error_type,trace_id,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*values, previous, event_hash),
            )
            db.execute("UPDATE meta SET value=? WHERE key='head'", (event_hash,))
            db.execute("UPDATE meta SET value=? WHERE key='count'", (str(count + 1),))
            final_count, final_head = _verify_hot_head(db)
            if final_count != count + 1 or final_head != event_hash:
                raise AuditIntegrityError("audit append verification failed")
            db.execute("COMMIT")
            return AuditReference(trace_id=str(values[11]), event_hash=event_hash)
        except BaseException as primary:
            try:
                db.execute("ROLLBACK")
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(primary, "audit rollback", cleanup_error)
            raise
        finally:
            primary = sys.exception()
            try:
                db.close()
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "audit connection close", cleanup_error
                )


def append_tool_audit(
    *,
    profile: str,
    tool: str,
    action: str,
    decision: str,
    reason: str,
    arguments: object = None,
    outcome: str = "decision",
    trace_id: str = "",
    error_type: str = "",
) -> str:
    """Backward-compatible hash-only append API."""

    return append_tool_audit_reference(
        profile=profile,
        tool=tool,
        action=action,
        decision=decision,
        reason=reason,
        arguments=arguments,
        outcome=outcome,
        trace_id=trace_id,
        error_type=error_type,
    ).event_hash


def verify_audit_reference(*, trace_id: str, event_hash: str) -> bool:
    """Prove exact trace/hash membership using bounded online checks."""

    if not isinstance(trace_id, str) or not trace_id or len(trace_id) > 64:
        return False
    if not isinstance(event_hash, str) or len(event_hash) != 64:
        return False
    try:
        int(event_hash, 16)
    except ValueError:
        return False
    with _LOCK:
        db = _connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            _verify_hot_head(db)
            row = db.execute(
                "SELECT "
                + ",".join(_EVENT_COLUMNS)
                + " FROM events WHERE trace_id=? AND event_hash=? LIMIT 1",
                (trace_id, event_hash),
            ).fetchone()
            if row is not None:
                _verify_event_row(tuple(row))
            db.execute("COMMIT")
            return row is not None
        except BaseException as primary:
            try:
                db.execute("ROLLBACK")
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "audit reference rollback", cleanup_error
                )
            raise
        finally:
            primary = sys.exception()
            try:
                db.close()
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "audit reference connection close", cleanup_error
                )


def find_audit_reference(*, trace_id: str) -> AuditReference | None:
    """Return the sole verified member for a trace, rejecting ambiguity."""

    if not isinstance(trace_id, str) or not trace_id or len(trace_id) > 64:
        return None
    with _LOCK:
        db = _connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            _verify_hot_head(db)
            rows = db.execute(
                "SELECT "
                + ",".join(_EVENT_COLUMNS)
                + " FROM events WHERE trace_id=? ORDER BY id LIMIT 2",
                (trace_id,),
            ).fetchall()
            if len(rows) > 1:
                raise AuditIntegrityError("audit trace has duplicate members")
            event_hash = None if not rows else _verify_event_row(tuple(rows[0]))
            db.execute("COMMIT")
            if event_hash is None:
                return None
            return AuditReference(trace_id=trace_id, event_hash=event_hash)
        except BaseException as primary:
            try:
                db.execute("ROLLBACK")
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "audit lookup rollback", cleanup_error
                )
            raise
        finally:
            primary = sys.exception()
            try:
                db.close()
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "audit lookup connection close", cleanup_error
                )


_SEMANTIC_REQUEST_FIELDS_V2 = {
    "approval_policy",
    "connector",
    "correlation_id",
    "dry_run",
    "idempotency_key",
    "mission_id",
    "operation",
    "payload_sha256",
    "request_id",
    "request_sha256",
    "risk",
    "source_context_sha256",
    "target_sha256",
    "workspace_id",
}
_SEMANTIC_REQUEST_FIELDS_V3 = _SEMANTIC_REQUEST_FIELDS_V2 | {
    "target",
    "approval_id",
    "schema_version",
}
_SEMANTIC_AUTHORIZATION = {
    "principal": "local-owner",
    "profile": "p4.4-shadow",
    "decision": "allowed",
    "outcome": "decision",
}


def _canonical_object(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise AuditIntegrityError(
            "semantic audit contract is not canonical JSON"
        ) from exc


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _semantic_contract(value: object) -> dict[str, object]:
    """Validate the one P4.4 semantic decision shape without trusting a trace."""

    _reject_persisted_strings(value, "semantic audit contract")
    if not isinstance(value, dict) or set(value) != {
        "contract",
        "request",
        "authorization",
    }:
        raise AuditIntegrityError("semantic audit contract shape is invalid")
    contract_name = value.get("contract")
    if contract_name not in {"OnyxToolAuditSemantic.v2", "OnyxToolAuditSemantic.v3"}:
        raise AuditIntegrityError("semantic audit contract version is invalid")
    version = 2 if contract_name == "OnyxToolAuditSemantic.v2" else 3
    request = value.get("request")
    authorization = value.get("authorization")
    expected_fields = (
        _SEMANTIC_REQUEST_FIELDS_V2 if version == 2 else _SEMANTIC_REQUEST_FIELDS_V3
    )
    if not isinstance(request, dict) or set(request) != expected_fields:
        raise AuditIntegrityError("semantic audit request shape is invalid")
    if not isinstance(authorization, dict) or set(authorization) != {
        "principal",
        "profile",
        "tool",
        "action",
        "decision",
        "outcome",
    }:
        raise AuditIntegrityError("semantic audit authorization shape is invalid")
    for field in (
        "payload_sha256",
        "request_sha256",
        "source_context_sha256",
        "target_sha256",
    ):
        if not _is_digest(request.get(field)):
            raise AuditIntegrityError(f"semantic audit {field} is invalid")
    for field in (
        "approval_policy",
        "connector",
        "correlation_id",
        "idempotency_key",
        "mission_id",
        "operation",
        "request_id",
        "risk",
        "workspace_id",
    ):
        item = request.get(field)
        if not isinstance(item, str) or not item or len(item) > 256:
            raise AuditIntegrityError(f"semantic audit {field} is invalid")
    if type(request.get("dry_run")) is not bool:
        raise AuditIntegrityError("semantic audit dry_run is invalid")
    if version == 3:
        target = request.get("target")
        approval_id = request.get("approval_id")
        if (
            not isinstance(target, str)
            or not target
            or len(target) > 1024
            or any(ord(char) < 32 for char in target)
            or contains_secret(target)
            or hashlib.sha256(target.encode("utf-8")).hexdigest()
            != request.get("target_sha256")
        ):
            raise AuditIntegrityError(
                "semantic audit recoverable target binding is invalid"
            )
        if request.get("schema_version") != 3:
            raise AuditIntegrityError("semantic audit record version is invalid")
        if approval_id is not None and (
            not isinstance(approval_id, str)
            or not approval_id
            or len(approval_id) > 128
            or contains_secret(approval_id)
            or _SEMANTIC_ID_SECRET.fullmatch(approval_id)
        ):
            raise AuditIntegrityError("semantic audit approval_id is invalid")
    for field, item in request.items():
        if isinstance(item, str) and contains_secret(item):
            raise AuditIntegrityError(
                f"semantic audit {field} contains secret material"
            )
    for field, expected in _SEMANTIC_AUTHORIZATION.items():
        if authorization.get(field) != expected:
            raise AuditIntegrityError("semantic audit authorization is not allowed")
    if authorization.get("tool") != request.get("connector") or authorization.get(
        "action"
    ) != request.get("operation"):
        raise AuditIntegrityError("semantic audit authorization/request diverges")
    return {
        "contract": str(contract_name),
        "request": dict(request),
        "authorization": dict(authorization),
    }


def _semantic_trace_id(contract: dict[str, object]) -> str:
    request = contract["request"]
    assert isinstance(request, dict)
    version = str(contract["contract"]).rsplit(".v", 1)[-1]
    return hashlib.sha256(
        (f"ONYX-V5-AUDIT-TRACE.v{version}\0" + _canonical_object(request)).encode(
            "ascii"
        )
    ).hexdigest()


def _semantic_digest(contract: dict[str, object]) -> str:
    version = str(contract["contract"]).rsplit(".v", 1)[-1]
    return hashlib.sha256(
        (f"ONYX-TOOL-AUDIT-SEMANTIC.v{version}\0" + _canonical_object(contract)).encode(
            "ascii"
        )
    ).hexdigest()


def _semantic_reference_from_row(
    row: sqlite3.Row | tuple[object, ...] | None,
    *,
    trace_id: str,
    semantic_digest: str,
    encoded: str,
) -> SemanticAuditReference | None:
    """Validate one indexed semantic row and its exact event member."""

    if row is None:
        return None
    values = tuple(row)
    stored_digest, stored_encoded, stored_event_hash = map(str, values[:3])
    event_values = values[3:]
    if len(event_values) != len(_EVENT_COLUMNS) or event_values[0] is None:
        raise AuditIntegrityError("semantic audit member is missing")
    try:
        decoded = json.loads(stored_encoded)
    except json.JSONDecodeError as exc:
        raise AuditIntegrityError("semantic audit contract JSON is invalid") from exc
    normalized = _semantic_contract(decoded)
    if _canonical_object(normalized) != stored_encoded:
        raise AuditIntegrityError("semantic audit contract is not canonical")
    if (
        stored_digest != semantic_digest
        or stored_encoded != encoded
        or _semantic_digest(normalized) != semantic_digest
        or _semantic_trace_id(normalized) != trace_id
    ):
        raise AuditIntegrityError("semantic audit trace CAS diverged")
    computed_event_hash = _verify_event_row(event_values)
    if stored_event_hash != computed_event_hash:
        raise AuditIntegrityError("semantic audit event binding diverged")
    authorization = normalized["authorization"]
    request = normalized["request"]
    assert isinstance(authorization, dict) and isinstance(request, dict)
    expected = (
        authorization["principal"],
        authorization["profile"],
        authorization["tool"],
        authorization["action"],
        authorization["decision"],
        "tool",
        _shape(request),
        authorization["outcome"],
        "",
        trace_id,
    )
    observed = (
        event_values[1],
        event_values[2],
        event_values[3],
        event_values[4],
        event_values[5],
        event_values[7],
        event_values[8],
        event_values[9],
        event_values[10],
        event_values[11],
    )
    if observed != expected:
        raise AuditIntegrityError("semantic audit binding invalid")
    return SemanticAuditReference(trace_id, stored_event_hash, semantic_digest)


def _select_semantic_reference(
    db: sqlite3.Connection,
    *,
    trace_id: str,
    semantic_digest: str,
    encoded: str,
) -> SemanticAuditReference | None:
    row = db.execute(
        "SELECT s.semantic_digest,s.contract_json,s.event_hash,"
        + ",".join("e." + column for column in _EVENT_COLUMNS)
        + " FROM semantic_events_v2 AS s LEFT JOIN events AS e "
        "ON e.event_hash=s.event_hash WHERE s.trace_id=?",
        (trace_id,),
    ).fetchone()
    return _semantic_reference_from_row(
        row,
        trace_id=trace_id,
        semantic_digest=semantic_digest,
        encoded=encoded,
    )


def append_semantic_tool_audit_reference(
    *, contract: object, reason: str = "explicit provider-free P4.4 observation"
) -> SemanticAuditReference:
    """CAS one allowed semantic decision and legacy-chain event atomically."""

    if (
        not isinstance(reason, str)
        or not reason
        or len(reason) > 120
        or any(ord(char) < 32 for char in reason)
        or contains_secret(reason)
    ):
        raise AuditIntegrityError("semantic audit reason is invalid or sensitive")
    normalized = _semantic_contract(contract)
    _reject_persisted_strings(normalized, "semantic audit contract")
    encoded = _canonical_object(normalized)
    trace_id = _semantic_trace_id(normalized)
    semantic_digest = _semantic_digest(normalized)
    authorization = normalized["authorization"]
    request = normalized["request"]
    assert isinstance(authorization, dict) and isinstance(request, dict)
    with _LOCK:
        db = _connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            count, previous = _verify_hot_head(db)
            prior = _select_semantic_reference(
                db,
                trace_id=trace_id,
                semantic_digest=semantic_digest,
                encoded=encoded,
            )
            if prior is not None:
                db.execute("COMMIT")
                return prior
            if (
                db.execute(
                    "SELECT 1 FROM events WHERE trace_id=? LIMIT 1", (trace_id,)
                ).fetchone()
                is not None
            ):
                raise AuditIntegrityError(
                    "legacy/raw audit trace cannot satisfy semantic-v2 authority"
                )
            values = [
                datetime.now(timezone.utc).isoformat(),
                authorization["principal"],
                authorization["profile"],
                authorization["tool"],
                authorization["action"],
                authorization["decision"],
                reason,
                "tool",
                _shape(request),
                authorization["outcome"],
                "",
                trace_id,
            ]
            _reject_persisted_strings(values, "semantic audit event")
            canonical = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
            event_hash = hashlib.sha256((previous + canonical).encode()).hexdigest()
            db.execute(
                "INSERT INTO events(timestamp,principal,profile,tool,action,decision,reason,target_category,arg_schema,outcome,error_type,trace_id,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*values, previous, event_hash),
            )
            db.execute(
                "INSERT INTO semantic_events_v2(trace_id,semantic_digest,contract_json,event_hash) VALUES(?,?,?,?)",
                (trace_id, semantic_digest, encoded, event_hash),
            )
            db.execute("UPDATE meta SET value=? WHERE key='head'", (event_hash,))
            db.execute("UPDATE meta SET value=? WHERE key='count'", (str(count + 1),))
            final_count, final_head = _verify_hot_head(db)
            reference = _select_semantic_reference(
                db,
                trace_id=trace_id,
                semantic_digest=semantic_digest,
                encoded=encoded,
            )
            if (
                final_count != count + 1
                or final_head != event_hash
                or reference is None
                or reference.event_hash != event_hash
            ):
                raise AuditIntegrityError("semantic audit append verification failed")
            db.execute("COMMIT")
            return reference
        except BaseException as primary:
            try:
                db.execute("ROLLBACK")
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "semantic audit rollback", cleanup_error
                )
            raise
        finally:
            primary = sys.exception()
            try:
                db.close()
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "semantic audit connection close", cleanup_error
                )


def find_semantic_tool_audit_reference(
    *, contract: object
) -> SemanticAuditReference | None:
    normalized = _semantic_contract(contract)
    trace_id = _semantic_trace_id(normalized)
    semantic_digest = _semantic_digest(normalized)
    encoded = _canonical_object(normalized)
    with _LOCK:
        db = _connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            _verify_hot_head(db)
            reference = _select_semantic_reference(
                db,
                trace_id=trace_id,
                semantic_digest=semantic_digest,
                encoded=encoded,
            )
            db.execute("COMMIT")
            return reference
        except BaseException as primary:
            try:
                db.execute("ROLLBACK")
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "semantic audit lookup rollback", cleanup_error
                )
            raise
        finally:
            primary = sys.exception()
            try:
                db.close()
            except BaseException as cleanup_error:
                _preserve_cleanup_failure(
                    primary, "semantic audit lookup connection close", cleanup_error
                )


def verify_semantic_tool_audit_reference(*, contract: object, event_hash: str) -> bool:
    if not _is_digest(event_hash):
        return False
    if not AUDIT_PATH.is_file():
        return False
    reference = find_semantic_tool_audit_reference(contract=contract)
    return reference is not None and reference.event_hash == event_hash
