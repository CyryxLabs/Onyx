"""Persistent, governed, local-first mission control for Onyx.

Mission approval is not a blanket tool grant: every consequential step is routed
through the existing host-owned permission broker immediately before execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import re
import sqlite3
import stat
import sys
import threading
import time
import uuid
import weakref
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.permission_broker import (
    MISSION_TOOL_POLICIES,
    authorize,
    authorize_mission_tool,
    set_permission_callback,
)
from core.paths import memory_dir
from memory.store import _harden_mode, _is_reparse, contains_secret

SCHEMA_VERSION = 6
MIN_LEASE_SECONDS = 5.0
MAX_LEASE_SECONDS = 300.0
DEFAULT_DB = memory_dir() / "onyx_missions.sqlite3"
STATES = frozenset(
    {
        "draft",
        "awaiting_approval",
        "running",
        "waiting",
        "paused",
        "succeeded",
        "failed",
        "cancelled",
    }
)
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
TRANSITIONS = {
    "draft": {"awaiting_approval", "cancelled"},
    "awaiting_approval": {"cancelled"},
    "running": {"waiting", "paused", "succeeded", "failed", "cancelled"},
    "waiting": {"cancelled"},
    "paused": {"running", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}
_SECRET_KEY = re.compile(
    r"(?i)(api.?key|password|secret|token|authorization|cookie|credential)"
)
_INJECTION = re.compile(
    r"(?i)(ignore (?:all |the )?(?:previous|prior) instructions|system\s*:|developer\s*:|BEGIN (?:SYSTEM|PROMPT))"
)
_REFERENCE = re.compile(r"^\{\{step\.(\d+)\.result(?:\.([A-Za-z0-9_.-]+))?\}\}$")
RESULT_STATUSES = frozenset({"succeeded", "failed", "waiting"})
MIN_POLL_SECONDS = 0.1
MAX_POLL_SECONDS = 60.0


# Version 5 is a sealed MissionStore schema. Keep these definitions in one
# place so a database which already claims v5 can be authenticated before any
# repair-capable DDL is executed. SQLite-owned objects (``sqlite_*``) are not
# part of this application schema and are deliberately excluded.
_MISSION_SCHEMA_V5_TABLES = {
    "schema_meta": "CREATE TABLE schema_meta(version INTEGER NOT NULL)",
    "missions": """CREATE TABLE missions(id TEXT PRIMARY KEY,title TEXT NOT NULL,state TEXT NOT NULL,
      created_at REAL NOT NULL,updated_at REAL NOT NULL,max_steps INTEGER NOT NULL,max_seconds REAL NOT NULL,
      max_retries INTEGER NOT NULL,provider_cost_limit REAL NOT NULL,tool_allowlist TEXT NOT NULL,
      current_step INTEGER NOT NULL DEFAULT 0,error TEXT,deadline REAL,approval_digest TEXT,
      lease_owner TEXT,lease_expires REAL,lease_heartbeat REAL)""",
    "steps": """CREATE TABLE steps(id TEXT PRIMARY KEY,mission_id TEXT NOT NULL REFERENCES missions(id),
      position INTEGER NOT NULL,tool TEXT NOT NULL,args TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,idempotency_key TEXT NOT NULL UNIQUE,result TEXT,error TEXT,
      wait_reason TEXT,started_at REAL,completed_at REAL,UNIQUE(mission_id,position))""",
    "events": """CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,mission_id TEXT NOT NULL,
      timestamp REAL NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL,
      prev_hash TEXT NOT NULL DEFAULT '',event_hash TEXT NOT NULL DEFAULT '')""",
    "event_heads": """CREATE TABLE event_heads(
      mission_id TEXT PRIMARY KEY REFERENCES missions(id),
      seq INTEGER NOT NULL UNIQUE,
      timestamp REAL NOT NULL,
      event TEXT NOT NULL,
      detail TEXT NOT NULL,
      prev_hash TEXT NOT NULL,
      event_hash TEXT NOT NULL,
      row_sha256 TEXT NOT NULL,
      projection_sha256 TEXT NOT NULL
    ) WITHOUT ROWID""",
}
_MISSION_SCHEMA_V5_INDEXES = {
    "events_mission": "CREATE INDEX events_mission ON events(mission_id,seq)",
}
_MISSION_SCHEMA_V6_INDEXES = {
    **_MISSION_SCHEMA_V5_INDEXES,
    "events_mission_event_seq": (
        "CREATE INDEX events_mission_event_seq ON events(mission_id,event,seq)"
    ),
}
_MISSION_SCHEMA_V5_TRIGGERS = {
    "events_no_update": """CREATE TRIGGER events_no_update BEFORE UPDATE ON events
      BEGIN SELECT RAISE(ABORT,'mission events are immutable'); END""",
    "events_no_delete": """CREATE TRIGGER events_no_delete BEFORE DELETE ON events
      BEGIN SELECT RAISE(ABORT,'mission events are immutable'); END""",
}

_MISSION_SCHEMA_V1_TABLES = {
    "schema_meta": _MISSION_SCHEMA_V5_TABLES["schema_meta"],
    "missions": """CREATE TABLE missions(id TEXT PRIMARY KEY,title TEXT NOT NULL,state TEXT NOT NULL,
      created_at REAL NOT NULL,updated_at REAL NOT NULL,max_steps INTEGER NOT NULL,max_seconds REAL NOT NULL,
      max_retries INTEGER NOT NULL,provider_cost_limit REAL NOT NULL,tool_allowlist TEXT NOT NULL,
      current_step INTEGER NOT NULL DEFAULT 0,error TEXT,deadline REAL,approval_digest TEXT)""",
    "steps": _MISSION_SCHEMA_V5_TABLES["steps"],
    "events": """CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,mission_id TEXT NOT NULL,
      timestamp REAL NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL)""",
}
_MISSION_SCHEMA_V2_TABLES = {
    **_MISSION_SCHEMA_V1_TABLES,
    "events": _MISSION_SCHEMA_V5_TABLES["events"],
}
_MISSION_SCHEMA_V3_TABLES = {
    **_MISSION_SCHEMA_V2_TABLES,
    "missions": _MISSION_SCHEMA_V5_TABLES["missions"],
}
_MISSION_SCHEMA_V4_TABLES = {
    **_MISSION_SCHEMA_V3_TABLES,
    "event_heads": """CREATE TABLE event_heads(
      mission_id TEXT PRIMARY KEY REFERENCES missions(id),
      seq INTEGER NOT NULL UNIQUE,
      timestamp REAL NOT NULL,
      event TEXT NOT NULL,
      detail TEXT NOT NULL,
      prev_hash TEXT NOT NULL,
      event_hash TEXT NOT NULL,
      row_sha256 TEXT NOT NULL
    ) WITHOUT ROWID""",
}
_MISSION_LEGACY_SCHEMAS = {
    1: (_MISSION_SCHEMA_V1_TABLES, _MISSION_SCHEMA_V5_INDEXES, {}),
    2: (_MISSION_SCHEMA_V2_TABLES, _MISSION_SCHEMA_V5_INDEXES, {}),
    3: (
        _MISSION_SCHEMA_V3_TABLES,
        _MISSION_SCHEMA_V5_INDEXES,
        _MISSION_SCHEMA_V5_TRIGGERS,
    ),
    4: (
        _MISSION_SCHEMA_V4_TABLES,
        _MISSION_SCHEMA_V5_INDEXES,
        _MISSION_SCHEMA_V5_TRIGGERS,
    ),
    5: (
        _MISSION_SCHEMA_V5_TABLES,
        _MISSION_SCHEMA_V5_INDEXES,
        _MISSION_SCHEMA_V5_TRIGGERS,
    ),
}
_STEP_STATES = frozenset(
    {"pending", "running", "succeeded", "failed", "waiting", "skipped"}
)


def _canonical_schema_sql(value: str | None) -> str:
    """Canonicalize only unquoted SQL formatting/keywords.

    SQLite may normalize keyword case and insignificant whitespace in
    ``sqlite_schema``.  Quoted identifiers and string literals are semantic
    bytes, however: changing their case/content must never authenticate as the
    sealed v5 DDL.  Keep quoted spans byte-exact while normalizing only the
    unquoted spans between them.
    """
    if value is None:
        return ""
    output: list[str] = []
    unquoted: list[str] = []

    def flush_unquoted() -> None:
        if not unquoted:
            return
        text = "".join(unquoted)
        text = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "", text, flags=re.IGNORECASE)
        output.append(re.sub(r"\s+", "", text).casefold())
        unquoted.clear()

    index = 0
    while index < len(value):
        opener = value[index]
        if opener not in {"'", '"', "`", "["}:
            unquoted.append(opener)
            index += 1
            continue
        flush_unquoted()
        closer = "]" if opener == "[" else opener
        start = index
        index += 1
        while index < len(value):
            if value[index] != closer:
                index += 1
                continue
            # SQL quote escaping doubles the delimiter. Bracket identifiers
            # use the same doubled-close convention in SQLite.
            if index + 1 < len(value) and value[index + 1] == closer:
                index += 2
                continue
            index += 1
            break
        else:
            # An unterminated quoted span cannot be a valid sealed definition;
            # preserve it literally so it cannot collapse onto valid DDL.
            index = len(value)
        output.append(value[start:index])
    flush_unquoted()
    return "".join(output).rstrip(";")


class MissionError(RuntimeError):
    pass


class InvalidTransition(MissionError):
    pass


class BudgetExceeded(MissionError):
    pass


def _now() -> float:
    return time.time()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _worker_owner(owner: object) -> str:
    raw = str(owner).strip()
    if not raw or len(raw) > 120 or contains_secret(raw) or redact(raw) != raw:
        raise ValueError("invalid worker owner")
    return raw


def _lease_seconds(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not MIN_LEASE_SECONDS <= value <= MAX_LEASE_SECONDS
    ):
        raise ValueError("invalid worker lease")
    return float(value)


def redact(value: Any) -> Any:
    """Bound and redact untrusted values before persistence or display."""
    if isinstance(value, Mapping):
        return {
            str(redact(k))[:120]: (
                "[REDACTED]"
                if _SECRET_KEY.search(str(k)) or contains_secret(k)
                else redact(v)
            )
            for k, v in list(value.items())[:200]
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value[:200]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value).replace("\x00", "")[:8000]
    if contains_secret(text):
        return "[REDACTED]"
    if _INJECTION.search(text):
        text = _INJECTION.sub("[UNTRUSTED-INSTRUCTION]", text)
    return text


def _json(value: Any) -> str:
    return json.dumps(
        redact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


safe_redact = redact


def _evidence_from_data(value: Any, output: list[dict[str, str]]) -> None:
    """Collect bounded local citations without interpreting tool output as instructions."""
    if len(output) >= 100:
        return
    if isinstance(value, Mapping):
        citation = value.get("citation")
        if citation is not None:
            safe = str(redact(citation)).strip()[:1000]
            if safe and safe != "[REDACTED]":
                item = {"type": "citation", "value": safe}
                if item not in output:
                    output.append(item)
        for child in list(value.values())[:200]:
            _evidence_from_data(child, output)
    elif isinstance(value, (list, tuple)):
        for child in value[:200]:
            _evidence_from_data(child, output)


def normalize_mission_result(value: Any) -> dict[str, Any]:
    """Normalize a runner value into the bounded local mission-result schema.

    Plain legacy values are retained as redacted data but fail closed to
    ``waiting`` because runner completion does not prove an outcome. A runner
    must use the structured contract and provide explicit deterministic
    postconditions before it can report success.
    """
    contract_keys = {"status", "data", "evidence", "postconditions", "waiting_for"}
    structured = isinstance(value, Mapping) and bool(contract_keys.intersection(value))
    if not structured:
        data = redact(value)
        evidence: list[dict[str, str]] = []
        _evidence_from_data(data, evidence)
        return {
            "status": "waiting",
            "data": data,
            "evidence": evidence,
            "postconditions": [],
            "waiting_for": "runner returned an unstructured result; explicit outcome verification required",
        }

    assert isinstance(value, Mapping)
    data = redact(value.get("data"))
    waiting = value.get("waiting_for")
    waiting_for = str(redact(waiting)).strip()[:1000] if waiting is not None else None
    raw_status = value.get("status", "waiting" if waiting_for else "succeeded")
    status = str(raw_status).strip().lower()

    evidence = []
    raw_evidence = value.get("evidence", [])
    schema_error: str | None = None
    if not isinstance(raw_evidence, (list, tuple)):
        schema_error = "result evidence must be a list"
    else:
        evidence = [redact(item) for item in raw_evidence[:100]]
    discovered: list[dict[str, str]] = []
    _evidence_from_data(data, discovered)
    for item in discovered:
        if item not in evidence and len(evidence) < 100:
            evidence.append(item)

    postconditions: list[dict[str, Any]] = []
    raw_postconditions = value.get("postconditions", [])
    if not isinstance(raw_postconditions, (list, tuple)):
        schema_error = schema_error or "result postconditions must be a list"
    else:
        for index, raw in enumerate(raw_postconditions[:100]):
            if not isinstance(raw, Mapping):
                schema_error = (
                    schema_error or f"postcondition {index} must be an object"
                )
                continue
            name = str(redact(raw.get("name", ""))).strip()[:240]
            satisfied = raw.get("satisfied")
            if not name or not isinstance(satisfied, bool):
                schema_error = schema_error or f"postcondition {index} is invalid"
                continue
            condition: dict[str, Any] = {"name": name, "satisfied": satisfied}
            if "detail" in raw:
                condition["detail"] = redact(raw["detail"])
            postconditions.append(condition)

    if status not in RESULT_STATUSES:
        schema_error = schema_error or "result status is invalid"
    if schema_error:
        status = "waiting"
        waiting_for = schema_error
    elif status == "waiting" and not waiting_for:
        waiting_for = "runner requires explicit outcome confirmation"
    elif status == "succeeded" and not postconditions:
        status = "waiting"
        waiting_for = "result has no verifiable postconditions"

    return redact(
        {
            "status": status,
            "data": data,
            "evidence": evidence,
            "postconditions": postconditions,
            "waiting_for": waiting_for,
        }
    )


def verify_mission_result(value: Any) -> dict[str, Any]:
    """Fail closed when a declared deterministic postcondition is not proven."""
    result = normalize_mission_result(value)
    if result["status"] == "succeeded":
        unverified = [
            condition.get("name", "postcondition")
            for condition in result["postconditions"]
            if condition.get("satisfied") is not True
        ]
        if unverified:
            result["status"] = "waiting"
            result["waiting_for"] = "unverified postconditions: " + ", ".join(
                unverified[:20]
            )
    return redact(result)


def _run_bounded(
    runner: "ToolRunner", tool: str, args: dict[str, Any], key: str, timeout: float
) -> tuple[bool, Any]:
    """Bound pure local computation; the daemon may finish late but cannot commit."""
    results: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            results.put((True, runner(tool, args, key)))
        except BaseException as exc:
            results.put((False, exc))

    worker = threading.Thread(target=target, name="onyx-mission-pure", daemon=True)
    worker.start()
    try:
        return results.get(timeout=max(0.0, timeout))
    except queue.Empty:
        return False, TimeoutError("deadline exceeded")


def _resolve_references(conn: sqlite3.Connection, mid: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_references(conn, mid, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_references(conn, mid, v) for v in value]
    if not isinstance(value, str):
        return value
    match = _REFERENCE.fullmatch(value)
    if not match:
        return value
    row = conn.execute(
        "SELECT result FROM steps WHERE mission_id=? AND position=? AND state='succeeded'",
        (mid, int(match.group(1))),
    ).fetchone()
    if not row:
        raise MissionError("template reference requires a prior succeeded step")
    stored = json.loads(row[0])
    current = stored.get("data", stored.get("untrusted_tool_output"))
    for part in (match.group(2) or "").split(".") if match.group(2) else ():
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise MissionError("template reference field is unavailable")
    return redact(current)


@dataclass(frozen=True)
class Mission:
    id: str
    title: str
    state: str
    created_at: float
    updated_at: float
    max_steps: int
    max_seconds: float
    max_retries: int
    provider_cost_limit: float
    tool_allowlist: list[str]
    current_step: int
    error: str | None


@dataclass(frozen=True)
class MissionAuthoritySnapshot:
    """Atomic durable authority view; transient lease fields are excluded."""

    mission_id: str
    state: str
    current_step: int
    max_steps: int
    max_seconds: float
    max_retries: int
    provider_cost_limit: float
    tool_allowlist: tuple[str, ...]
    event_seq: int
    event_hash: str
    snapshot_hash: str


_ISSUED_PHASE11_AUTHORITY_CAPABILITIES: weakref.WeakKeyDictionary[
    _Phase11AuthorityCapability,
    tuple[
        weakref.ReferenceType[MissionStore],
        weakref.ReferenceType[object],
        weakref.WeakMethod,
    ],
] = weakref.WeakKeyDictionary()


class _Phase11AuthorityCapability:
    """Opaque, process-local append authority bound to one bridge and store."""

    __slots__ = ("_factory", "_nonce", "__weakref__")

    def __init__(self, nonce: bytes, factory: object) -> None:
        self._nonce = nonce
        self._factory = factory

    def __copy__(self):
        raise TypeError("Phase 11 authority capability cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("Phase 11 authority capability cannot be copied")

    def __reduce__(self):
        raise TypeError("Phase 11 authority capability cannot be serialized")


_PHASE11_EVENT_SIGNATURE_DOMAIN = b"ONYX/PHASE11/AUTHORITY-EVENT/V1\0"


def _phase11_event_signature_message(
    mission_id: str, event: str, detail: Mapping[str, Any]
) -> bytes:
    unsigned = {
        key: value for key, value in detail.items() if key != "authority_signature"
    }
    return _PHASE11_EVENT_SIGNATURE_DOMAIN + json.dumps(
        {
            "mission_id": mission_id,
            "event": event,
            "detail": unsigned,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_step_projection(step: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": step["id"],
        "position": int(step["position"]),
        "tool": step["tool"],
        "args": json.loads(step["args"]),
        "state": step["state"],
        "attempts": int(step["attempts"]),
        "idempotency_key": step["idempotency_key"],
        "result": json.loads(step["result"]) if step["result"] is not None else None,
        "error": step["error"],
        "wait_reason": step["wait_reason"],
        "started_at": step["started_at"],
        "completed_at": step["completed_at"],
    }


def _authority_projection(
    mission: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    event_seq: int,
    event_hash: str,
) -> dict[str, Any]:
    """Canonical durable authority projection (lease/runtime fields excluded)."""
    return {
        "contract": "MissionAuthorityProjection.v1",
        "id": mission["id"],
        "state": mission["state"],
        "current_step": int(mission["current_step"]),
        "max_steps": int(mission["max_steps"]),
        "max_seconds": float(mission["max_seconds"]),
        "max_retries": int(mission["max_retries"]),
        "provider_cost_limit": float(mission["provider_cost_limit"]),
        "tool_allowlist": json.loads(mission["tool_allowlist"]),
        "steps": [_canonical_step_projection(step) for step in steps],
        "event_seq": int(event_seq),
        "event_hash": event_hash,
    }


def _authority_projection_hash(
    mission: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    event_seq: int,
    event_hash: str,
) -> str:
    return hashlib.sha256(
        json.dumps(
            _authority_projection(mission, steps, event_seq, event_hash),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


ToolRunner = Callable[[str, dict[str, Any], str], Any]


class MissionStore:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._initialized = False
        self._migration_fault: Callable[[str], None] = lambda _point: None
        self._phase11_authority_factory = object()
        self._phase11_authority_owner: weakref.ReferenceType[object] | None = None

    @staticmethod
    def _private_file_identity(
        path: Path, *, volatile_sidecar: bool = False
    ) -> tuple[int, int] | None:
        transient = (
            os.name == "nt"
            and volatile_sidecar
            and str(path).endswith(("-wal", "-shm"))
        )
        attempts = 8 if transient else 2
        deadline = time.monotonic() + 0.025
        for attempt in range(attempts):
            try:
                info = path.lstat()
            except FileNotFoundError:
                if transient or attempt:
                    return None
                continue
            attrs = getattr(info, "st_file_attributes", 0)
            reparse = bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
            if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode):
                raise MissionError(
                    "Mission database files must be private regular files"
                )
            if info.st_nlink == 1:
                return int(info.st_dev), int(info.st_ino)
            if info.st_nlink > 1 or not transient:
                raise MissionError(
                    "Mission database files must be private regular files"
                )
            if attempt + 1 >= attempts:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(0.001, remaining))
        return None

    def _connect(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = None
        try:
            paths = [
                self.path,
                *(
                    Path(str(self.path) + suffix)
                    for suffix in ("-wal", "-shm", "-journal")
                ),
            ]
            volatile = {Path(str(self.path) + suffix) for suffix in ("-wal", "-shm")}

            def identities():
                return {
                    path: self._private_file_identity(
                        path, volatile_sidecar=path in volatile
                    )
                    for path in paths
                }

            before = identities()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.parent.is_symlink() or _is_reparse(self.path.parent):
                raise MissionError("Refusing linked mission directory")
            parent_identity = self.path.parent.stat()
            conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            after = identities()
            if after[self.path] is None:
                raise MissionError("Mission database is missing after open")
            if before[self.path] is not None and before[self.path] != after[self.path]:
                raise MissionError("Mission database identity changed while opening")
            parent_after = self.path.parent.stat()
            if (parent_identity.st_dev, parent_identity.st_ino) != (
                parent_after.st_dev,
                parent_after.st_ino,
            ):
                raise MissionError("Mission database directory changed while opening")
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA secure_delete=ON")
            _harden_mode(self.path)
            for suffix in ("-wal", "-shm"):
                _harden_mode(Path(str(self.path) + suffix))
            identities()
            return conn
        except MissionError:
            if conn is not None:
                conn.close()
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            if conn is not None:
                conn.close()
            raise MissionError(f"Mission database unavailable: {exc}") from exc

    @staticmethod
    def _schema_snapshot(
        c: sqlite3.Connection,
    ) -> tuple[tuple[str, str, str, str | None], ...]:
        return tuple(
            (str(row[0]), str(row[1]), str(row[2]), row[3])
            for row in c.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_schema "
                "ORDER BY type,name,tbl_name"
            ).fetchall()
        )

    @staticmethod
    def _claimed_schema_version(
        c: sqlite3.Connection,
        snapshot: tuple[tuple[str, str, str, str | None], ...],
    ) -> int | None:
        application_objects = [
            row for row in snapshot if not row[1].startswith("sqlite_")
        ]
        if not any(
            row[0] == "table" and row[1] == "schema_meta" for row in application_objects
        ):
            if application_objects:
                raise MissionError("Mission schema provenance is missing")
            return None
        try:
            versions = c.execute("SELECT version FROM schema_meta").fetchall()
        except sqlite3.DatabaseError as exc:
            raise MissionError("Mission schema version contract diverges") from exc
        if len(versions) != 1:
            raise MissionError("Mission schema version cardinality diverges")
        value = versions[0][0]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise MissionError("Mission schema version contract diverges")
        return value

    @staticmethod
    def _validate_schema_contract(
        snapshot: tuple[tuple[str, str, str, str | None], ...],
        *,
        version: int,
        tables: Mapping[str, str],
        indexes: Mapping[str, str],
        triggers: Mapping[str, str],
    ) -> None:
        expected: dict[tuple[str, str], tuple[str, str]] = {}
        expected.update({("table", name): (name, sql) for name, sql in tables.items()})
        expected.update(
            {("index", name): ("events", sql) for name, sql in indexes.items()}
        )
        expected.update(
            {("trigger", name): ("events", sql) for name, sql in triggers.items()}
        )
        observed = {
            (kind, name): (table_name, sql)
            for kind, name, table_name, sql in snapshot
            if not name.startswith("sqlite_")
        }
        if set(observed) != set(expected):
            raise MissionError(f"Mission schema v{version} object inventory diverges")
        for identity, (expected_table, expected_sql) in expected.items():
            observed_table, observed_sql = observed[identity]
            if observed_table != expected_table or _canonical_schema_sql(
                observed_sql
            ) != _canonical_schema_sql(expected_sql):
                raise MissionError(
                    f"Mission schema v{version} {identity[0]} {identity[1]} diverges"
                )

    @classmethod
    def _validate_v6_schema(
        cls,
        snapshot: tuple[tuple[str, str, str, str | None], ...],
    ) -> None:
        cls._validate_schema_contract(
            snapshot,
            version=6,
            tables=_MISSION_SCHEMA_V5_TABLES,
            indexes=_MISSION_SCHEMA_V6_INDEXES,
            triggers=_MISSION_SCHEMA_V5_TRIGGERS,
        )

    @classmethod
    def _validate_legacy_schema(
        cls,
        snapshot: tuple[tuple[str, str, str, str | None], ...],
        version: int,
    ) -> None:
        try:
            tables, indexes, triggers = _MISSION_LEGACY_SCHEMAS[version]
        except KeyError:
            raise MissionError("Mission legacy schema version is unsupported") from None
        cls._validate_schema_contract(
            snapshot,
            version=version,
            tables=tables,
            indexes=indexes,
            triggers=triggers,
        )

    @staticmethod
    def _validated_steps(
        c: sqlite3.Connection, mission: Mapping[str, Any]
    ) -> tuple[sqlite3.Row, ...]:
        mission_id = str(mission["id"])
        state = mission["state"]
        if state not in STATES:
            raise MissionError("Mission execution state is invalid")
        scalar_bounds = (
            isinstance(mission["max_steps"], int)
            and not isinstance(mission["max_steps"], bool)
            and 1 <= mission["max_steps"] <= 500
            and isinstance(mission["max_retries"], int)
            and not isinstance(mission["max_retries"], bool)
            and 0 <= mission["max_retries"] <= 20
            and isinstance(mission["max_seconds"], (int, float))
            and not isinstance(mission["max_seconds"], bool)
            and math.isfinite(mission["max_seconds"])
            and 0.01 <= mission["max_seconds"] <= 86400
            and isinstance(mission["provider_cost_limit"], (int, float))
            and not isinstance(mission["provider_cost_limit"], bool)
            and math.isfinite(mission["provider_cost_limit"])
            and float(mission["provider_cost_limit"]) == 0.0
        )
        if not scalar_bounds:
            raise MissionError("Mission execution budget contract diverges")
        try:
            tool_allowlist = json.loads(mission["tool_allowlist"])
        except (TypeError, ValueError, json.JSONDecodeError):
            raise MissionError("Mission tool allowlist is invalid") from None
        if (
            not isinstance(tool_allowlist, list)
            or not tool_allowlist
            or tool_allowlist != sorted(set(tool_allowlist))
            or any(
                not isinstance(tool, str) or tool not in MISSION_TOOL_POLICIES
                for tool in tool_allowlist
            )
            or _json(tool_allowlist) != mission["tool_allowlist"]
        ):
            raise MissionError("Mission tool allowlist contract diverges")
        rows = tuple(
            c.execute(
                "SELECT * FROM steps WHERE mission_id=? ORDER BY position",
                (mission_id,),
            )
        )
        if not rows or len(rows) > int(mission["max_steps"]):
            raise MissionError("Mission canonical plan cardinality diverges")
        if [row["position"] for row in rows] != list(range(len(rows))):
            raise MissionError("Mission canonical plan positions diverge")
        current_step = mission["current_step"]
        if (
            isinstance(current_step, bool)
            or not isinstance(current_step, int)
            or not 0 <= current_step <= len(rows)
        ):
            raise MissionError("Mission current step diverges")
        for row in rows:
            if (
                str(row["mission_id"]) != mission_id
                or not isinstance(row["id"], str)
                or not row["id"]
                or row["state"] not in _STEP_STATES
                or row["tool"] not in tool_allowlist
                or isinstance(row["attempts"], bool)
                or not isinstance(row["attempts"], int)
                or not 0 <= row["attempts"] <= int(mission["max_retries"]) + 1
            ):
                raise MissionError("Mission canonical step contract diverges")
            try:
                args = json.loads(row["args"])
                result = (
                    json.loads(row["result"]) if row["result"] is not None else None
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                raise MissionError("Mission canonical step JSON is invalid") from None
            if (
                not isinstance(args, dict)
                or _json(args) != row["args"]
                or (row["result"] is not None and _json(result) != row["result"])
            ):
                raise MissionError("Mission canonical step JSON diverges")
            expected_idempotency = hashlib.sha256(
                f"{mission_id}:{row['position']}:{row['tool']}:{row['args']}".encode()
            ).hexdigest()
            if row["idempotency_key"] != expected_idempotency:
                raise MissionError("Mission step idempotency contract diverges")
        states = [str(row["state"]) for row in rows]
        if any(value != "succeeded" for value in states[:current_step]):
            raise MissionError("Mission completed step prefix diverges")
        if state == "succeeded":
            if current_step != len(rows) or any(
                value != "succeeded" for value in states
            ):
                raise MissionError("Mission completion proof diverges")
        elif state in {"draft", "awaiting_approval"}:
            if current_step != 0 or any(value != "pending" for value in states):
                raise MissionError("Mission unstarted plan state diverges")
        elif state != "cancelled":
            if any(value != "pending" for value in states[current_step + 1 :]):
                raise MissionError("Mission future step state diverges")
            if current_step < len(rows):
                allowed_current = {
                    "running": {"pending", "running"},
                    "paused": {"pending"},
                    "waiting": {"waiting"},
                    "failed": {"failed"},
                }.get(state, set())
                if states[current_step] not in allowed_current:
                    raise MissionError("Mission active step state diverges")
            elif state not in {"running", "failed"}:
                raise MissionError("Mission terminal cursor state diverges")
        return rows

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            c = self._connect()
            try:
                c.execute("BEGIN IMMEDIATE")
                pre_migration_schema = self._schema_snapshot(c)
                claimed_version = self._claimed_schema_version(c, pre_migration_schema)
                if claimed_version is not None and claimed_version > SCHEMA_VERSION:
                    raise MissionError(
                        "Mission database schema is newer than this runtime"
                    )
                if claimed_version is not None and claimed_version < SCHEMA_VERSION:
                    self._validate_legacy_schema(pre_migration_schema, claimed_version)
                current_schema = claimed_version == SCHEMA_VERSION
                if current_schema:
                    self._validate_v6_schema(pre_migration_schema)
                persisted_version = claimed_version or 0
                event_heads_existed = any(
                    kind == "table" and name == "event_heads"
                    for kind, name, _table_name, _sql in pre_migration_schema
                )
                pre_migration_head_columns = (
                    {item[1] for item in c.execute("PRAGMA table_info(event_heads)")}
                    if event_heads_existed
                    else set()
                )
                if (
                    persisted_version < 5
                    and "projection_sha256" in pre_migration_head_columns
                ):
                    raise MissionError("Mission schema migration provenance diverges")

                if not current_schema:
                    for sql in _MISSION_SCHEMA_V5_TABLES.values():
                        if sql.startswith("CREATE TABLE event_heads"):
                            continue
                        c.execute(
                            sql.replace(
                                "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
                            )
                        )
                    for sql in _MISSION_SCHEMA_V6_INDEXES.values():
                        c.execute(
                            sql.replace(
                                "CREATE INDEX ",
                                "CREATE INDEX IF NOT EXISTS ",
                                1,
                            )
                        )
                    if claimed_version is None:
                        c.execute(
                            "INSERT INTO schema_meta VALUES(?)", (SCHEMA_VERSION,)
                        )

                if persisted_version < 2:
                    columns = {r[1] for r in c.execute("PRAGMA table_info(events)")}
                    if "prev_hash" not in columns:
                        c.execute(
                            "ALTER TABLE events ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''"
                        )
                    if "event_hash" not in columns:
                        c.execute(
                            "ALTER TABLE events ADD COLUMN event_hash TEXT NOT NULL DEFAULT ''"
                        )
                    previous_by_mission: dict[str, str] = {}
                    for old in c.execute(
                        "SELECT seq,mission_id,timestamp,event,detail FROM events ORDER BY mission_id,seq"
                    ).fetchall():
                        previous = previous_by_mission.get(old["mission_id"], "")
                        digest = hashlib.sha256(
                            f"{old['mission_id']}\0{old['timestamp']:.9f}\0{old['event']}\0{old['detail']}\0{previous}".encode()
                        ).hexdigest()
                        c.execute(
                            "UPDATE events SET prev_hash=?,event_hash=? WHERE seq=?",
                            (previous, digest, old["seq"]),
                        )
                        previous_by_mission[old["mission_id"]] = digest
                if not current_schema:
                    columns = {r[1] for r in c.execute("PRAGMA table_info(missions)")}
                    if "lease_owner" not in columns:
                        c.execute("ALTER TABLE missions ADD COLUMN lease_owner TEXT")
                    if "lease_expires" not in columns:
                        c.execute("ALTER TABLE missions ADD COLUMN lease_expires REAL")
                    if "lease_heartbeat" not in columns:
                        c.execute(
                            "ALTER TABLE missions ADD COLUMN lease_heartbeat REAL"
                        )
                    if not event_heads_existed:
                        c.execute(_MISSION_SCHEMA_V5_TABLES["event_heads"])
                    elif "projection_sha256" not in pre_migration_head_columns:
                        expected_legacy_columns = {
                            "mission_id",
                            "seq",
                            "timestamp",
                            "event",
                            "detail",
                            "prev_hash",
                            "event_hash",
                            "row_sha256",
                        }
                        if pre_migration_head_columns != expected_legacy_columns:
                            raise MissionError(
                                "Mission authority projection schema diverges"
                            )
                        c.execute("ALTER TABLE event_heads RENAME TO event_heads_v4")
                        c.execute(_MISSION_SCHEMA_V5_TABLES["event_heads"])
                        c.execute(
                            "INSERT INTO event_heads(mission_id,seq,timestamp,event,detail,"
                            "prev_hash,event_hash,row_sha256,projection_sha256) "
                            "SELECT mission_id,seq,timestamp,event,detail,prev_hash,event_hash,"
                            "row_sha256,'' FROM event_heads_v4"
                        )
                        c.execute("DROP TABLE event_heads_v4")
                    self._migration_fault("after_event_heads_schema")
                previous_by_mission: dict[str, str] = {}
                latest_by_mission: dict[str, sqlite3.Row] = {}
                durable_missions = {
                    str(item[0]) for item in c.execute("SELECT id FROM missions")
                }
                for old in c.execute(
                    "SELECT * FROM events ORDER BY mission_id,seq"
                ).fetchall():
                    previous = previous_by_mission.get(old["mission_id"], "")
                    expected = hashlib.sha256(
                        f"{old['mission_id']}\0{old['timestamp']:.9f}\0{old['event']}\0{old['detail']}\0{previous}".encode()
                    ).hexdigest()
                    if old["prev_hash"] != previous or old["event_hash"] != expected:
                        raise MissionError("Mission audit integrity check failed")
                    previous_by_mission[old["mission_id"]] = expected
                    latest_by_mission[old["mission_id"]] = old
                missions_by_id = {
                    str(item["id"]): item
                    for item in c.execute("SELECT * FROM missions")
                }
                foreign_key_violations = c.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                if foreign_key_violations:
                    raise MissionError("Mission foreign-key integrity diverges")
                steps_by_mission = {
                    mission_id: self._validated_steps(c, mission)
                    for mission_id, mission in missions_by_id.items()
                }
                event_missions = set(latest_by_mission)
                if durable_missions != event_missions:
                    raise MissionError(
                        "Mission authority mission/event key-set diverges"
                    )
                expected_heads: dict[str, tuple[object, ...]] = {}
                for old in latest_by_mission.values():
                    event_values = (
                        old["mission_id"],
                        old["seq"],
                        old["timestamp"],
                        old["event"],
                        old["detail"],
                        old["prev_hash"],
                        old["event_hash"],
                    )
                    projection_hash = _authority_projection_hash(
                        missions_by_id[str(old["mission_id"])],
                        steps_by_mission[str(old["mission_id"])],
                        int(old["seq"]),
                        str(old["event_hash"]),
                    )
                    row_hash = hashlib.sha256(
                        json.dumps(
                            (*event_values, projection_hash),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest()
                    expected_heads[str(old["mission_id"])] = (
                        *event_values,
                        row_hash,
                        projection_hash,
                    )
                observed_heads = {
                    str(item["mission_id"]): tuple(item)
                    for item in c.execute(
                        "SELECT mission_id,seq,timestamp,event,detail,prev_hash,event_hash,"
                        "row_sha256,projection_sha256 FROM event_heads"
                    )
                }
                if set(observed_heads) - set(expected_heads):
                    raise MissionError(
                        "Mission authority projection contains an extra head"
                    )
                for mission_id, values in expected_heads.items():
                    observed = observed_heads.get(mission_id)
                    if observed is None:
                        if persisted_version >= SCHEMA_VERSION:
                            raise MissionError(
                                "Mission authority projection head is missing"
                            )
                        c.execute(
                            "INSERT INTO event_heads VALUES(?,?,?,?,?,?,?,?,?)", values
                        )
                    elif observed != values:
                        # A v4 head has no authenticated authority commitment.
                        # Upgrade only that exact legacy shape inside this same
                        # migration transaction; any other divergence is fatal.
                        if (
                            persisted_version < SCHEMA_VERSION
                            and len(observed) == 9
                            and observed[:7] == values[:7]
                            and observed[8] == ""
                            and observed[7]
                            == hashlib.sha256(
                                json.dumps(
                                    observed[:7],
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ).encode()
                            ).hexdigest()
                        ):
                            c.execute(
                                "UPDATE event_heads SET row_sha256=?,projection_sha256=? "
                                "WHERE mission_id=?",
                                (values[7], values[8], mission_id),
                            )
                        else:
                            raise MissionError("Mission authority projection diverges")
                final_head_missions = {
                    str(item[0])
                    for item in c.execute("SELECT mission_id FROM event_heads")
                }
                if not (durable_missions == event_missions == final_head_missions):
                    raise MissionError(
                        "Mission authority mission/event/head key-set diverges"
                    )
                if not current_schema:
                    self._migration_fault("after_event_heads_backfill")
                    c.execute("UPDATE schema_meta SET version=?", (SCHEMA_VERSION,))
                    for sql in _MISSION_SCHEMA_V5_TRIGGERS.values():
                        c.execute(
                            sql.replace(
                                "CREATE TRIGGER ", "CREATE TRIGGER IF NOT EXISTS ", 1
                            )
                        )
                    self._migration_fault("before_migration_commit")
                self._validate_v6_schema(self._schema_snapshot(c))
                c.execute("COMMIT")
                self._initialized = True
            except BaseException as exc:
                if c.in_transaction:
                    c.execute("ROLLBACK")
                if isinstance(exc, MissionError):
                    raise
                if isinstance(exc, sqlite3.DatabaseError):
                    raise MissionError(
                        f"Mission database initialization failed: {exc}"
                    ) from exc
                raise
            finally:
                c.close()

    def _event(self, c: sqlite3.Connection, mid: str, event: str, detail: Any) -> None:
        timestamp = _now()
        safe_event = str(redact(event))[:120]
        safe_detail = _json(detail)
        previous = c.execute(
            "SELECT event_hash FROM events WHERE mission_id=? ORDER BY seq DESC LIMIT 1",
            (mid,),
        ).fetchone()
        prev_hash = previous[0] if previous else ""
        event_hash = hashlib.sha256(
            f"{mid}\0{timestamp:.9f}\0{safe_event}\0{safe_detail}\0{prev_hash}".encode()
        ).hexdigest()
        cursor = c.execute(
            "INSERT INTO events(mission_id,timestamp,event,detail,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
            (mid, timestamp, safe_event, safe_detail, prev_hash, event_hash),
        )
        values = (
            mid,
            int(cursor.lastrowid),
            timestamp,
            safe_event,
            safe_detail,
            prev_hash,
            event_hash,
        )
        mission = c.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
        if mission is None:
            raise MissionError("Mission authority projection mission is unavailable")
        steps = self._validated_steps(c, mission)
        projection_hash = _authority_projection_hash(
            mission, steps, int(cursor.lastrowid), event_hash
        )
        row_hash = hashlib.sha256(
            json.dumps(
                (*values, projection_hash),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        c.execute(
            "INSERT INTO event_heads VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(mission_id) DO UPDATE SET "
            "seq=excluded.seq,timestamp=excluded.timestamp,event=excluded.event,"
            "detail=excluded.detail,prev_hash=excluded.prev_hash,"
            "event_hash=excluded.event_hash,row_sha256=excluded.row_sha256,"
            "projection_sha256=excluded.projection_sha256",
            (*values, row_hash, projection_hash),
        )

    def create(
        self,
        title: str,
        steps: list[Mapping[str, Any]],
        *,
        tool_allowlist: list[str] | None = None,
        max_steps: int = 25,
        max_seconds: float = 900,
        max_retries: int = 2,
        provider_cost_limit: float = 0.0,
    ) -> Mission:
        self.initialize()
        title = str(redact(title)).strip()[:240]
        if not title or not steps:
            raise ValueError("title and at least one step are required")
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or not 1 <= max_steps <= 500
            or len(steps) > max_steps
        ):
            raise ValueError("invalid step budget")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= 20
        ):
            raise ValueError("invalid retry budget")
        if (
            isinstance(max_seconds, bool)
            or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds)
            or not 0.01 <= max_seconds <= 86400
        ):
            raise ValueError("invalid time budget")
        if (
            isinstance(provider_cost_limit, bool)
            or not isinstance(provider_cost_limit, (int, float))
            or not math.isfinite(provider_cost_limit)
            or provider_cost_limit != 0
        ):
            raise ValueError(
                "paid provider missions are unavailable; cost budget must be zero"
            )
        tools = sorted(set(tool_allowlist or [str(s.get("tool", "")) for s in steps]))
        if not all(t and t in tools for t in tools):
            raise ValueError("invalid tool allowlist")
        unsupported = sorted(set(tools) - set(MISSION_TOOL_POLICIES))
        if unsupported:
            raise BudgetExceeded(
                "Executable missions currently support only provider-free local tools; "
                f"unsupported: {', '.join(str(redact(x)) for x in unsupported)}"
            )
        estimated_cost = 0.0
        for position, spec in enumerate(steps):
            cost = spec.get("estimated_provider_cost", 0.0)
            if (
                isinstance(cost, bool)
                or not isinstance(cost, (int, float))
                or not math.isfinite(cost)
                or cost < 0
            ):
                raise ValueError(
                    f"step {position} has an invalid provider cost estimate"
                )
            estimated_cost += float(cost)
        if estimated_cost > provider_cost_limit:
            raise BudgetExceeded(
                f"planned provider cost {estimated_cost:.4f} exceeds budget {provider_cost_limit:.4f}"
            )
        mid, when = _id("mis"), _now()
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "INSERT INTO missions(id,title,state,created_at,updated_at,max_steps,max_seconds,max_retries,provider_cost_limit,tool_allowlist,current_step,error,deadline,approval_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    mid,
                    title,
                    "draft",
                    when,
                    when,
                    max_steps,
                    float(max_seconds),
                    max_retries,
                    float(provider_cost_limit),
                    _json(tools),
                    0,
                    None,
                    None,
                    None,
                ),
            )
            for pos, spec in enumerate(steps):
                tool = str(spec.get("tool", "")).strip()
                args = dict(spec.get("args") or {})
                if not tool or tool not in tools:
                    raise ValueError(f"step {pos} uses an unallowed tool")
                idem = hashlib.sha256(
                    f"{mid}:{pos}:{tool}:{_json(args)}".encode()
                ).hexdigest()
                c.execute(
                    "INSERT INTO steps(id,mission_id,position,tool,args,idempotency_key) VALUES(?,?,?,?,?,?)",
                    (_id("step"), mid, pos, tool, _json(args), idem),
                )
            self._event(
                c,
                mid,
                "mission.created",
                {
                    "steps": len(steps),
                    "paid_cost_budget": provider_cost_limit,
                    "estimated_paid_cost": estimated_cost,
                },
            )
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()
        self.transition(mid, "awaiting_approval", {"reason": "plan ready"})
        return self.get(mid)

    def create_idempotent(
        self,
        materialization_key: str,
        title: str,
        steps: list[Mapping[str, Any]],
        *,
        tool_allowlist: list[str] | None = None,
        max_steps: int = 25,
        max_seconds: float = 900,
        max_retries: int = 2,
        provider_cost_limit: float = 0.0,
    ) -> Mission:
        """Atomically create or return one exact deterministic mission.

        The key is never persisted. It derives the mission identity, while the
        complete immutable plan is compared on every replay. Concurrent callers
        with the same key therefore converge on one MissionStore row; reuse with
        any different title, step, allowlist, or budget fails closed.
        """

        self.initialize()
        if not isinstance(materialization_key, str) or not re.fullmatch(
            r"[A-Za-z0-9_.:-]{8,192}", materialization_key
        ):
            raise ValueError("invalid materialization key")
        safe_title = str(redact(title)).strip()[:240]
        if not safe_title or not steps:
            raise ValueError("title and at least one step are required")
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or not 1 <= max_steps <= 500
            or len(steps) > max_steps
        ):
            raise ValueError("invalid step budget")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= 20
        ):
            raise ValueError("invalid retry budget")
        if (
            isinstance(max_seconds, bool)
            or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds)
            or not 0.01 <= max_seconds <= 86400
        ):
            raise ValueError("invalid time budget")
        if (
            isinstance(provider_cost_limit, bool)
            or not isinstance(provider_cost_limit, (int, float))
            or not math.isfinite(provider_cost_limit)
            or provider_cost_limit != 0
        ):
            raise ValueError(
                "paid provider missions are unavailable; cost budget must be zero"
            )
        tools = sorted(
            set(tool_allowlist or [str(spec.get("tool", "")) for spec in steps])
        )
        if not tools or any(not tool for tool in tools):
            raise ValueError("invalid tool allowlist")
        unsupported = sorted(set(tools) - set(MISSION_TOOL_POLICIES))
        if unsupported:
            raise BudgetExceeded(
                "Executable missions currently support only provider-free local tools; "
                f"unsupported: {', '.join(str(redact(item)) for item in unsupported)}"
            )
        normalized_steps: list[tuple[str, str]] = []
        estimated_cost = 0.0
        for position, spec in enumerate(steps):
            tool = str(spec.get("tool", "")).strip()
            if not tool or tool not in tools:
                raise ValueError(f"step {position} uses an unallowed tool")
            args = dict(spec.get("args") or {})
            cost = spec.get("estimated_provider_cost", 0.0)
            if (
                isinstance(cost, bool)
                or not isinstance(cost, (int, float))
                or not math.isfinite(cost)
                or cost < 0
            ):
                raise ValueError(
                    f"step {position} has an invalid provider cost estimate"
                )
            estimated_cost += float(cost)
            normalized_steps.append((tool, _json(args)))
        if estimated_cost > provider_cost_limit:
            raise BudgetExceeded(
                f"planned provider cost {estimated_cost:.4f} exceeds budget "
                f"{provider_cost_limit:.4f}"
            )
        mid = (
            "mis_"
            + hashlib.sha256(
                f"OnyxMissionMaterialization.v1\0{materialization_key}".encode("utf-8")
            ).hexdigest()
        )
        when = _now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM missions WHERE id=?", (mid,)
            ).fetchone()
            if existing is not None:
                self._validated_steps(connection, existing)
                existing_steps = connection.execute(
                    "SELECT position,tool,args,idempotency_key FROM steps "
                    "WHERE mission_id=? ORDER BY position",
                    (mid,),
                ).fetchall()
                exact = (
                    existing["title"] == safe_title
                    and int(existing["max_steps"]) == max_steps
                    and float(existing["max_seconds"]) == float(max_seconds)
                    and int(existing["max_retries"]) == max_retries
                    and float(existing["provider_cost_limit"])
                    == float(provider_cost_limit)
                    and existing["tool_allowlist"] == _json(tools)
                    and len(existing_steps) == len(normalized_steps)
                )
                if exact:
                    for position, (tool, args_json) in enumerate(normalized_steps):
                        row = existing_steps[position]
                        expected_key = hashlib.sha256(
                            f"{mid}:{position}:{tool}:{args_json}".encode()
                        ).hexdigest()
                        if (
                            row["position"] != position
                            or row["tool"] != tool
                            or row["args"] != args_json
                            or row["idempotency_key"] != expected_key
                        ):
                            exact = False
                            break
                if not exact:
                    raise MissionError(
                        "materialization key is already bound to another immutable plan"
                    )
                connection.execute("COMMIT")
                return self.get(mid)
            connection.execute(
                "INSERT INTO missions(id,title,state,created_at,updated_at,max_steps,"
                "max_seconds,max_retries,provider_cost_limit,tool_allowlist,current_step,"
                "error,deadline,approval_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    mid,
                    safe_title,
                    "draft",
                    when,
                    when,
                    max_steps,
                    float(max_seconds),
                    max_retries,
                    float(provider_cost_limit),
                    _json(tools),
                    0,
                    None,
                    None,
                    None,
                ),
            )
            for position, (tool, args_json) in enumerate(normalized_steps):
                idempotency_key = hashlib.sha256(
                    f"{mid}:{position}:{tool}:{args_json}".encode()
                ).hexdigest()
                step_id = (
                    "step_" + hashlib.sha256(f"{mid}:{position}".encode()).hexdigest()
                )
                connection.execute(
                    "INSERT INTO steps(id,mission_id,position,tool,args,idempotency_key) "
                    "VALUES(?,?,?,?,?,?)",
                    (step_id, mid, position, tool, args_json, idempotency_key),
                )
            self._event(
                connection,
                mid,
                "mission.created",
                {
                    "steps": len(normalized_steps),
                    "paid_cost_budget": provider_cost_limit,
                    "estimated_paid_cost": estimated_cost,
                    "idempotent_materialization": True,
                },
            )
            connection.execute(
                "UPDATE missions SET state='awaiting_approval',updated_at=? WHERE id=?",
                (_now(), mid),
            )
            self._event(
                connection,
                mid,
                "mission.awaiting_approval",
                {"reason": "idempotent plan ready"},
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        return self.get(mid)

    def plan_summary(self, mid: str) -> dict[str, Any]:
        """Return the immutable safe plan and its canonical approval digest."""
        self.initialize()
        c = self._connect()
        try:
            mission = c.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
            if mission is None:
                raise KeyError(mid)
            steps = c.execute(
                "SELECT position,tool,args FROM steps WHERE mission_id=? ORDER BY position",
                (mid,),
            ).fetchall()
            plan = {
                "mission_id": mid,
                "title": mission["title"],
                "steps": [
                    {
                        "position": r["position"],
                        "tool": r["tool"],
                        "args": json.loads(r["args"]),
                    }
                    for r in steps
                ],
                "budgets": {
                    "steps": mission["max_steps"],
                    "seconds": mission["max_seconds"],
                    "retries": mission["max_retries"],
                    "paid_cost": mission["provider_cost_limit"],
                },
            }
            canonical = _json(plan)
            return {
                "plan": plan,
                "plan_digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            }
        finally:
            c.close()

    def get(self, mid: str) -> Mission:
        self.initialize()
        c = self._connect()
        try:
            r = c.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
            if not r:
                raise KeyError(mid)
            return Mission(
                r["id"],
                r["title"],
                r["state"],
                r["created_at"],
                r["updated_at"],
                r["max_steps"],
                r["max_seconds"],
                r["max_retries"],
                r["provider_cost_limit"],
                json.loads(r["tool_allowlist"]),
                r["current_step"],
                r["error"],
            )
        finally:
            c.close()

    def _authority_snapshot_in_transaction(
        self, connection: sqlite3.Connection, mid: str
    ) -> MissionAuthoritySnapshot:
        mission = connection.execute(
            "SELECT * FROM missions WHERE id=?", (mid,)
        ).fetchone()
        if mission is None:
            raise KeyError(mid)
        head = connection.execute(
            "SELECT * FROM event_heads WHERE mission_id=?", (mid,)
        ).fetchone()
        latest = connection.execute(
            "SELECT * FROM events WHERE mission_id=? ORDER BY seq DESC LIMIT 1",
            (mid,),
        ).fetchone()
        if head is None or latest is None:
            raise MissionError("Mission authority event head is unavailable")
        prior = connection.execute(
            "SELECT event_hash FROM events WHERE mission_id=? AND seq<? "
            "ORDER BY seq DESC LIMIT 1",
            (mid, int(latest["seq"])),
        ).fetchone()
        previous_hash = str(prior[0]) if prior is not None else ""
        event_hash = hashlib.sha256(
            f"{mid}\0{latest['timestamp']:.9f}\0{latest['event']}\0"
            f"{latest['detail']}\0{previous_hash}".encode()
        ).hexdigest()
        values = (
            mid,
            int(latest["seq"]),
            float(latest["timestamp"]),
            latest["event"],
            latest["detail"],
            latest["prev_hash"],
            latest["event_hash"],
        )
        row_hash = hashlib.sha256(
            json.dumps(
                (*values, head["projection_sha256"]),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        projection_hash = _authority_projection_hash(
            mission,
            self._validated_steps(connection, mission),
            int(latest["seq"]),
            event_hash,
        )
        if (
            latest["prev_hash"] != previous_hash
            or latest["event_hash"] != event_hash
            or tuple(
                head[key]
                for key in (
                    "mission_id",
                    "seq",
                    "timestamp",
                    "event",
                    "detail",
                    "prev_hash",
                    "event_hash",
                )
            )
            != values
            or head["row_sha256"] != row_hash
            or head["projection_sha256"] != projection_hash
        ):
            raise MissionError("Mission authority event head diverges")
        payload = {
            "contract": "MissionAuthoritySnapshot.v1",
            "id": mission["id"],
            "state": mission["state"],
            "current_step": mission["current_step"],
            "max_steps": mission["max_steps"],
            "max_seconds": mission["max_seconds"],
            "max_retries": mission["max_retries"],
            "provider_cost_limit": mission["provider_cost_limit"],
            "tool_allowlist": json.loads(mission["tool_allowlist"]),
            "event_seq": int(latest["seq"]),
            "event_hash": event_hash,
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return MissionAuthoritySnapshot(
            mission["id"],
            mission["state"],
            int(mission["current_step"]),
            int(mission["max_steps"]),
            float(mission["max_seconds"]),
            int(mission["max_retries"]),
            float(mission["provider_cost_limit"]),
            tuple(json.loads(mission["tool_allowlist"])),
            int(latest["seq"]),
            event_hash,
            snapshot_hash,
        )

    def authority_snapshot(self, mid: str) -> MissionAuthoritySnapshot:
        """Read mission authority and its verified event head in one transaction."""
        self.initialize()
        c = self._connect()
        try:
            c.execute("BEGIN")
            snapshot = self._authority_snapshot_in_transaction(c, mid)
            c.execute("COMMIT")
            return snapshot
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    @staticmethod
    def _events_in_transaction(
        connection: sqlite3.Connection, mid: str
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        previous = ""
        for row in connection.execute(
            "SELECT * FROM events WHERE mission_id=? ORDER BY seq", (mid,)
        ):
            expected = hashlib.sha256(
                f"{mid}\0{row['timestamp']:.9f}\0{row['event']}\0"
                f"{row['detail']}\0{previous}".encode()
            ).hexdigest()
            if row["prev_hash"] != previous or row["event_hash"] != expected:
                raise MissionError("Mission audit integrity check failed")
            output.append(
                {
                    "seq": row["seq"],
                    "timestamp": row["timestamp"],
                    "event": row["event"],
                    "detail": json.loads(row["detail"]),
                    "event_hash": row["event_hash"],
                }
            )
            previous = row["event_hash"]
        return output

    def phase11_authority_view_v1(self, mid: str) -> dict[str, Any]:
        """Return one atomic authenticated view used by the Phase 11 bridge."""
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            snapshot = self._authority_snapshot_in_transaction(connection, mid)
            events = self._events_in_transaction(connection, mid)
            if (
                not events
                or events[-1]["seq"] != snapshot.event_seq
                or events[-1]["event_hash"] != snapshot.event_hash
            ):
                raise MissionError("Mission authority view diverges")
            mission = connection.execute(
                "SELECT title,max_steps,max_seconds,max_retries,"
                "provider_cost_limit FROM missions WHERE id=?",
                (mid,),
            ).fetchone()
            if mission is None:
                raise KeyError(mid)
            rows = connection.execute(
                "SELECT position,tool,args,idempotency_key FROM steps "
                "WHERE mission_id=? ORDER BY position",
                (mid,),
            ).fetchall()
            fixed_steps = [
                {
                    "tool": str(row["tool"]),
                    "args": json.loads(row["args"]),
                    "idempotency_key": str(row["idempotency_key"]),
                }
                for row in rows
            ]
            plan = {
                "mission_id": mid,
                "title": mission["title"],
                "steps": [
                    {
                        "position": row["position"],
                        "tool": row["tool"],
                        "args": json.loads(row["args"]),
                    }
                    for row in rows
                ],
                "budgets": {
                    "steps": mission["max_steps"],
                    "seconds": mission["max_seconds"],
                    "retries": mission["max_retries"],
                    "paid_cost": mission["provider_cost_limit"],
                },
            }
            plan_digest = hashlib.sha256(_json(plan).encode("utf-8")).hexdigest()
            connection.execute("COMMIT")
            return {
                "snapshot": snapshot,
                "events": events,
                "fixed_steps": fixed_steps,
                "plan_digest": plan_digest,
            }
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _issue_phase11_authority_capability_v1(
        self,
        owner: object,
        validator: Callable[[str, str, Mapping[str, Any]], None],
    ) -> object:
        """Issue one opaque append capability bound to this store and owner."""
        if owner is None or not callable(validator):
            raise TypeError("Phase 11 authority capability owner is invalid")
        existing = (
            self._phase11_authority_owner()
            if self._phase11_authority_owner is not None
            else None
        )
        if existing is not None and existing is not owner:
            raise PermissionError("Phase 11 authority owner is already bound")
        try:
            owner_reference = weakref.ref(owner)
            validator_reference = weakref.WeakMethod(validator)
        except TypeError as exc:
            raise TypeError(
                "Phase 11 authority owner and validator must be weak-referenceable"
            ) from exc
        capability = _Phase11AuthorityCapability(
            os.urandom(32), self._phase11_authority_factory
        )
        self._phase11_authority_owner = owner_reference
        _ISSUED_PHASE11_AUTHORITY_CAPABILITIES[capability] = (
            weakref.ref(self),
            owner_reference,
            validator_reference,
        )
        return capability

    def _revoke_phase11_authority_capability_v1(
        self, capability: object, owner: object
    ) -> None:
        """Revoke authority issued to an initialization that did not complete."""

        if not isinstance(capability, _Phase11AuthorityCapability):
            return
        with self._lock:
            issued = _ISSUED_PHASE11_AUTHORITY_CAPABILITIES.get(capability)
            if issued is None or issued[0]() is not self or issued[1]() is not owner:
                return
            _ISSUED_PHASE11_AUTHORITY_CAPABILITIES.pop(capability, None)
            current_owner = (
                self._phase11_authority_owner()
                if self._phase11_authority_owner is not None
                else None
            )
            if current_owner is owner:
                self._phase11_authority_owner = None

    def _phase11_authority_validator(
        self, capability: object
    ) -> Callable[[str, str, Mapping[str, Any]], None]:
        if not isinstance(capability, _Phase11AuthorityCapability):
            raise PermissionError("Phase 11 authority capability is required")
        issued = _ISSUED_PHASE11_AUTHORITY_CAPABILITIES.get(capability)
        if (
            capability._factory is not self._phase11_authority_factory
            or issued is None
            or issued[0]() is not self
            or issued[1]() is None
        ):
            raise PermissionError("Phase 11 authority capability is invalid")
        validator = issued[2]()
        if validator is None:
            raise PermissionError("Phase 11 authority capability is revoked")
        return validator

    @staticmethod
    def _verify_phase11_event_signature_v1(
        mission_id: str,
        event: str,
        detail: Mapping[str, Any],
        existing: Sequence[Mapping[str, Any]],
    ) -> None:
        schemas = {
            "phase11.bound": {
                "mission_type",
                "binding_digest",
                "binding_signature",
                "authority_public_key",
                "authority_signature",
            },
            "phase11.receipt": {
                "stage",
                "schema",
                "root",
                "baseline_sha256",
                "observed_sha256",
                "verdict",
                "reason",
                "issued_at_ns",
                "receipt_signature",
                "authority_signature",
            },
            "phase11.kill": {"reason", "authority_signature"},
            "phase11.reconciliation": {
                "schema",
                "decision",
                "resolution_id",
                "binding_digest",
                "plan_digest",
                "gate_index",
                "execution_id",
                "intent_sha256",
                "recovered_receipt_sha256",
                "decision_hmac_sha256",
                "issued_at_ns",
                "authority_signature",
            },
        }
        if set(detail) != schemas[event]:
            raise MissionError("Phase 11 authority event schema is invalid")
        if any(row["event"] == "phase11.kill" for row in existing):
            raise MissionError("Phase 11 authority is terminal after kill")
        if event == "phase11.bound":
            public_key_hex = detail.get("authority_public_key")
        else:
            bound = [row for row in existing if row["event"] == "phase11.bound"]
            if len(bound) != 1:
                raise MissionError("Phase 11 authority binding is unavailable")
            try:
                bound_detail = json.loads(bound[0]["detail"])
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise MissionError("Phase 11 authority binding is malformed") from exc
            public_key_hex = bound_detail.get("authority_public_key")
        signature_hex = detail.get("authority_signature")
        if (
            not isinstance(public_key_hex, str)
            or len(public_key_hex) != 64
            or not isinstance(signature_hex, str)
            or len(signature_hex) != 128
        ):
            raise MissionError("Phase 11 authority signature fields are invalid")
        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(public_key_hex)
            )
            signature = bytes.fromhex(signature_hex)
            public_key.verify(
                signature,
                _phase11_event_signature_message(mission_id, event, detail),
            )
        except (ValueError, InvalidSignature) as exc:
            raise MissionError("Phase 11 authority event signature is invalid") from exc

    def _phase11_kill_in_transaction(
        self, connection: sqlite3.Connection, mid: str
    ) -> bool:
        """Authenticate a Phase 11 kill at the success-commit boundary.

        Generic missions pay only one indexed absence lookup.  A mission is
        governed by this guard only after one valid ``phase11.bound`` event has
        been appended through the opaque Phase 11 capability.  Both authority
        queries are bounded and use ``events_mission_event_seq``.
        """
        bound_rows = connection.execute(
            "SELECT event,detail FROM events WHERE mission_id=? "
            "AND event='phase11.bound' ORDER BY seq LIMIT 2",
            (mid,),
        ).fetchall()
        if not bound_rows:
            return False
        if len(bound_rows) != 1:
            raise MissionError("Phase 11 authority binding cardinality diverges")
        bound_detail = json.loads(bound_rows[0]["detail"])
        if not isinstance(bound_detail, dict):
            raise MissionError("Phase 11 authority binding is malformed")
        self._verify_phase11_event_signature_v1(mid, "phase11.bound", bound_detail, ())
        kill_rows = connection.execute(
            "SELECT * FROM events WHERE mission_id=? "
            "AND event='phase11.kill' ORDER BY seq DESC LIMIT 2",
            (mid,),
        ).fetchall()
        if not kill_rows:
            return False
        if len(kill_rows) != 1:
            raise MissionError("Phase 11 kill cardinality diverges")
        kill = kill_rows[0]
        try:
            kill_detail = json.loads(kill["detail"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MissionError("Phase 11 kill authority is malformed") from exc
        if not isinstance(kill_detail, dict):
            raise MissionError("Phase 11 kill authority is malformed")
        self._verify_phase11_event_signature_v1(
            mid, "phase11.kill", kill_detail, bound_rows
        )
        prior = connection.execute(
            "SELECT event_hash FROM events WHERE mission_id=? AND seq<? "
            "ORDER BY seq DESC LIMIT 1",
            (mid, int(kill["seq"])),
        ).fetchone()
        previous = str(prior["event_hash"]) if prior is not None else ""
        expected = hashlib.sha256(
            f"{mid}\0{kill['timestamp']:.9f}\0{kill['event']}\0"
            f"{kill['detail']}\0{previous}".encode()
        ).hexdigest()
        if kill["prev_hash"] != previous or kill["event_hash"] != expected:
            raise MissionError("Mission audit integrity check failed")
        self._authority_snapshot_in_transaction(connection, mid)
        return True

    def _quarantine_phase11_success_in_transaction(
        self,
        connection: sqlite3.Connection,
        mid: str,
        *,
        step: Mapping[str, Any] | None,
    ) -> bool:
        if not self._phase11_kill_in_transaction(connection, mid):
            return False
        reason = "Phase 11 kill requested; late success discarded"
        discarded = {
            "status": "waiting",
            "data": None,
            "evidence": [],
            "postconditions": [],
            "waiting_for": "kill_requested",
        }
        if step is None:
            connection.execute(
                "UPDATE missions SET state='cancelled',error=?,updated_at=? "
                "WHERE id=? AND state='running'",
                (reason, _now(), mid),
            )
            self._event(
                connection,
                mid,
                "mission.cancelled",
                {
                    "reason": "phase11 kill",
                    "active_result": "success discarded",
                },
            )
        else:
            connection.execute(
                "UPDATE steps SET state='waiting',wait_reason=?,result=? "
                "WHERE id=? AND state='running'",
                (reason, _json(discarded), step["id"]),
            )
            connection.execute(
                "UPDATE missions SET state='waiting',error=?,updated_at=? "
                "WHERE id=? AND state='running'",
                (reason, _now(), mid),
            )
            self._event(
                connection,
                mid,
                "step.waiting",
                {
                    "step": step["position"],
                    "reason": "kill_requested",
                    "evidence_count": 0,
                    "late_result": "discarded",
                },
            )
        return True

    def append_authority_event_v1(
        self,
        mid: str,
        event: str,
        detail: Mapping[str, Any],
        *,
        capability: object,
    ) -> MissionAuthoritySnapshot:
        """Append one narrow extension event through MissionStore authority.

        This API deliberately admits only the Phase 11 namespace.  It preserves
        the sealed schema and routes the append through the same event-head and
        durable projection update used by native MissionStore transitions.
        """
        if event not in {
            "phase11.bound",
            "phase11.receipt",
            "phase11.kill",
            "phase11.reconciliation",
        }:
            raise ValueError("unsupported MissionStore authority extension event")
        if not isinstance(detail, Mapping):
            raise TypeError("authority event detail must be a mapping")
        validator = self._phase11_authority_validator(capability)
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._authority_snapshot_in_transaction(connection, mid)
            normalized = dict(detail)
            validator(mid, event, normalized)
            existing = connection.execute(
                "SELECT event,detail FROM events WHERE mission_id=? "
                "AND event LIKE 'phase11.%' ORDER BY seq",
                (mid,),
            ).fetchall()
            reconciliation_details: list[Mapping[str, Any]] = []
            for row in existing:
                if row["event"] != "phase11.reconciliation":
                    continue
                try:
                    prior_detail = json.loads(row["detail"])
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise MissionError(
                        "Phase 11 reconciliation authority is malformed"
                    ) from exc
                if not isinstance(prior_detail, Mapping):
                    raise MissionError("Phase 11 reconciliation authority is malformed")
                reconciliation_details.append(prior_detail)
            if (
                any(
                    item.get("decision") == "abandon" for item in reconciliation_details
                )
                and event != "phase11.kill"
            ):
                raise MissionError(
                    "Phase 11 authority is terminal after reconciliation abandon"
                )
            if event == "phase11.reconciliation" and any(
                item.get("resolution_id") == normalized.get("resolution_id")
                for item in reconciliation_details
            ):
                raise MissionError("Phase 11 reconciliation replay detected")
            self._verify_phase11_event_signature_v1(mid, event, normalized, existing)
            bound = [row for row in existing if row["event"] == "phase11.bound"]
            if event == "phase11.bound":
                if existing:
                    raise MissionError("Phase 11 authority is already bound")
            elif len(bound) != 1:
                raise MissionError("Phase 11 authority binding is unavailable")
            self._event(connection, mid, event, normalized)
            snapshot = self._authority_snapshot_in_transaction(connection, mid)
            connection.execute("COMMIT")
            return snapshot
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def authority_event_at(self, mid: str, seq: int) -> dict[str, Any]:
        """Return one hash-verified authority event at an exact sequence."""
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
            raise ValueError("authority event sequence must be a positive integer")
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            snapshot = self._authority_snapshot_in_transaction(connection, mid)
            if seq > snapshot.event_seq:
                raise MissionError("authority event sequence is ahead of current head")
            events = self._events_in_transaction(connection, mid)
            event = next((item for item in events if item["seq"] == seq), None)
            if event is None:
                raise MissionError("authority event is unavailable")
            connection.execute("COMMIT")
            return event
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def authority_event_marker_v1(self, mid: str, seq: int) -> dict[str, Any]:
        """Verify one exact event against its predecessor and current authority head."""
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
            raise ValueError("authority event sequence must be a positive integer")
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            snapshot = self._authority_snapshot_in_transaction(connection, mid)
            if seq > snapshot.event_seq:
                raise MissionError("authority event sequence is ahead of current head")
            row = connection.execute(
                "SELECT * FROM events WHERE mission_id=? AND seq=?",
                (mid, seq),
            ).fetchone()
            prior = connection.execute(
                "SELECT event_hash FROM events WHERE mission_id=? AND seq<? "
                "ORDER BY seq DESC LIMIT 1",
                (mid, seq),
            ).fetchone()
            if row is None:
                raise MissionError("authority event is unavailable")
            previous = str(prior["event_hash"]) if prior is not None else ""
            expected = hashlib.sha256(
                f"{mid}\0{row['timestamp']:.9f}\0{row['event']}\0"
                f"{row['detail']}\0{previous}".encode()
            ).hexdigest()
            if row["prev_hash"] != previous or row["event_hash"] != expected:
                raise MissionError("Mission audit integrity check failed")
            connection.execute("COMMIT")
            return {
                "seq": row["seq"],
                "timestamp": row["timestamp"],
                "event": row["event"],
                "detail": json.loads(row["detail"]),
                "event_hash": row["event_hash"],
            }
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def authority_phase11_kill_marker_v1(
        self, mid: str, through_seq: int
    ) -> dict[str, Any]:
        """Return a bounded verified kill marker and the caller's anchor row.

        ``through_seq`` is the native-vault anchor known to the caller.  The
        MissionStore head may legitimately be newer because normal worker
        events are committed independently.  A signed kill may also be newer
        when a process crashes after the database append but before advancing
        the native-vault anchor, so the marker search covers the current
        authenticated MissionStore head while separately proving the anchor
        row requested by the caller.
        """
        if (
            isinstance(through_seq, bool)
            or not isinstance(through_seq, int)
            or through_seq <= 0
        ):
            raise ValueError("authority head sequence must be a positive integer")
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            snapshot = self._authority_snapshot_in_transaction(connection, mid)
            if through_seq > snapshot.event_seq:
                raise MissionError("authority marker anchor is ahead of head")
            anchor_row = connection.execute(
                "SELECT * FROM events WHERE mission_id=? AND seq=?",
                (mid, through_seq),
            ).fetchone()
            if anchor_row is None:
                raise MissionError("authority marker anchor is unavailable")
            anchor_prior = connection.execute(
                "SELECT event_hash FROM events WHERE mission_id=? AND seq<? "
                "ORDER BY seq DESC LIMIT 1",
                (mid, through_seq),
            ).fetchone()
            anchor_previous = (
                str(anchor_prior["event_hash"]) if anchor_prior is not None else ""
            )
            anchor_expected = hashlib.sha256(
                f"{mid}\0{anchor_row['timestamp']:.9f}\0"
                f"{anchor_row['event']}\0{anchor_row['detail']}\0"
                f"{anchor_previous}".encode()
            ).hexdigest()
            if (
                anchor_row["prev_hash"] != anchor_previous
                or anchor_row["event_hash"] != anchor_expected
            ):
                raise MissionError("Mission audit integrity check failed")
            row = connection.execute(
                "SELECT * FROM events WHERE mission_id=? "
                "AND event='phase11.kill' AND seq<=? "
                "ORDER BY seq DESC LIMIT 1",
                (mid, snapshot.event_seq),
            ).fetchone()
            marker = None
            if row is not None:
                prior = connection.execute(
                    "SELECT event_hash FROM events WHERE mission_id=? AND seq<? "
                    "ORDER BY seq DESC LIMIT 1",
                    (mid, int(row["seq"])),
                ).fetchone()
                previous = str(prior["event_hash"]) if prior is not None else ""
                expected = hashlib.sha256(
                    f"{mid}\0{row['timestamp']:.9f}\0{row['event']}\0"
                    f"{row['detail']}\0{previous}".encode()
                ).hexdigest()
                if row["prev_hash"] != previous or row["event_hash"] != expected:
                    raise MissionError("Mission audit integrity check failed")
                marker = {
                    "seq": row["seq"],
                    "timestamp": row["timestamp"],
                    "event": row["event"],
                    "detail": json.loads(row["detail"]),
                    "event_hash": row["event_hash"],
                }
            connection.execute("COMMIT")
            return {
                "anchor_seq": int(anchor_row["seq"]),
                "anchor_hash": str(anchor_row["event_hash"]),
                "head_seq": snapshot.event_seq,
                "head_hash": snapshot.event_hash,
                "kill": marker,
            }
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def authority_plan_steps_v1(self, mid: str) -> list[dict[str, Any]]:
        """Return the exact persisted plan surface after authority validation."""
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            self._authority_snapshot_in_transaction(connection, mid)
            rows = connection.execute(
                "SELECT tool,args,idempotency_key FROM steps "
                "WHERE mission_id=? ORDER BY position",
                (mid,),
            ).fetchall()
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        return [
            {
                "tool": str(row["tool"]),
                "args": json.loads(row["args"]),
                "idempotency_key": str(row["idempotency_key"]),
            }
            for row in rows
        ]

    def authority_mission_for_step_key_v1(self, key: str) -> str | None:
        """Resolve one persisted idempotency key after validating its mission."""
        if not isinstance(key, str) or not key:
            raise ValueError("step idempotency key must be a non-empty string")
        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT mission_id FROM steps WHERE idempotency_key=?", (key,)
            ).fetchone()
            if row is not None:
                self._authority_snapshot_in_transaction(connection, str(row[0]))
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        if row is None:
            return None
        return str(row[0])

    def list(self) -> list[Mission]:
        self.initialize()
        c = self._connect()
        try:
            return [
                self.get(r[0])
                for r in c.execute(
                    "SELECT id FROM missions ORDER BY created_at DESC"
                ).fetchall()
            ]
        finally:
            c.close()

    def transition(self, mid: str, target: str, detail: Any | None = None) -> Mission:
        if target not in STATES:
            raise InvalidTransition(target)
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT state FROM missions WHERE id=?", (mid,)).fetchone()
            if not row:
                raise KeyError(mid)
            if target not in TRANSITIONS[row[0]]:
                raise InvalidTransition(f"{row[0]} -> {target}")
            c.execute(
                "UPDATE missions SET state=?,updated_at=? WHERE id=?",
                (target, _now(), mid),
            )
            self._event(c, mid, f"mission.{target}", detail or {})
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()
        return self.get(mid)

    def approve(self, mid: str) -> Mission:
        mission = self.get(mid)
        if mission.state != "awaiting_approval":
            raise InvalidTransition("mission is not awaiting approval")
        summary = self.plan_summary(mid)
        ok, digest = authorize(
            "mission.approve",
            f"Allow Onyx to start mission '{mission.title}'?",
            summary,
        )
        if not ok:
            raise PermissionError(digest)
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT state FROM missions WHERE id=?", (mid,)).fetchone()
            current = self.plan_summary(mid)
            if (
                not row
                or row["state"] != "awaiting_approval"
                or current["plan_digest"] != summary["plan_digest"]
            ):
                raise InvalidTransition(
                    "mission changed or was cancelled during approval"
                )
            deadline = _now() + mission.max_seconds
            changed = c.execute(
                "UPDATE missions SET state='running',updated_at=?,deadline=?,approval_digest=? WHERE id=? AND state='awaiting_approval'",
                (_now(), deadline, summary["plan_digest"], mid),
            ).rowcount
            if changed != 1:
                raise InvalidTransition("approval lost a concurrent state change")
            self._event(
                c,
                mid,
                "mission.approved",
                {"plan_digest": summary["plan_digest"], "host_approval_digest": digest},
            )
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()
        return self.get(mid)

    def runtime_authority_v1(self, mid: str) -> dict[str, object]:
        """Return the approved deadline/lease tuple for a claimed live step."""
        if not isinstance(mid, str) or not re.fullmatch(r"mis_[A-Za-z0-9_]+", mid):
            raise MissionError("mission id is invalid")
        c = self._connect()
        try:
            row = c.execute(
                "SELECT state,deadline,approval_digest,lease_owner,"
                "lease_expires FROM missions WHERE id=?",
                (mid,),
            ).fetchone()
        finally:
            c.close()
        if (
            not row
            or row["state"] != "running"
            or isinstance(row["deadline"], bool)
            or not isinstance(row["deadline"], (int, float))
            or not math.isfinite(row["deadline"])
            or not isinstance(row["approval_digest"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["approval_digest"])
            or not isinstance(row["lease_owner"], str)
            or not row["lease_owner"]
            or isinstance(row["lease_expires"], bool)
            or not isinstance(row["lease_expires"], (int, float))
            or not math.isfinite(row["lease_expires"])
        ):
            raise MissionError("runtime authority is unavailable")
        return {
            "deadline_ns": int(float(row["deadline"]) * 1_000_000_000),
            "approval_digest": row["approval_digest"],
            "lease_owner_digest": hashlib.sha256(
                row["lease_owner"].encode("utf-8")
            ).hexdigest(),
            "lease_expires_ns": int(float(row["lease_expires"]) * 1_000_000_000),
        }

    def run(
        self,
        mid: str,
        runner: ToolRunner,
        *,
        clock: Callable[[], float] = _now,
        lease_owner: str | None = None,
        backoff: Callable[[float], None] = time.sleep,
    ) -> Mission:
        mission = self.get(mid)
        if mission.state not in {"running", "paused"}:
            raise InvalidTransition(
                "mission cannot run; resolve waiting steps explicitly"
            )
        if mission.state == "paused":
            self.transition(mid, "running", {"reason": "resume"})
        c = self._connect()
        try:
            while True:
                c.execute("BEGIN IMMEDIATE")
                m = c.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
                if m["lease_owner"] and m["lease_owner"] != lease_owner:
                    c.execute("COMMIT")
                    raise MissionError("mission is leased by another worker")
                if m["state"] != "running":
                    c.execute("COMMIT")
                    return self.get(mid)
                if clock() > m["deadline"]:
                    c.execute(
                        "UPDATE steps SET state='failed',error='deadline exceeded' WHERE mission_id=? AND position=? AND state IN ('pending','running')",
                        (mid, m["current_step"]),
                    )
                    c.execute(
                        "UPDATE missions SET state='failed',error='deadline exceeded' WHERE id=? AND state='running'",
                        (mid,),
                    )
                    self._event(
                        c,
                        mid,
                        "mission.failed",
                        {"error": "deadline exceeded", "step": m["current_step"]},
                    )
                    c.execute("COMMIT")
                    return self.get(mid)
                step = c.execute(
                    "SELECT * FROM steps WHERE mission_id=? AND state NOT IN ('succeeded','skipped') ORDER BY position LIMIT 1",
                    (mid,),
                ).fetchone()
                if not step:
                    completed = self._validated_steps(c, m)
                    if int(m["current_step"]) != len(completed) or any(
                        item["state"] != "succeeded" for item in completed
                    ):
                        raise MissionError(
                            "Mission completion lacks a canonical step proof"
                        )
                    if self._quarantine_phase11_success_in_transaction(
                        c, mid, step=None
                    ):
                        c.execute("COMMIT")
                        return self.get(mid)
                    c.execute(
                        "UPDATE missions SET state='succeeded',updated_at=? WHERE id=?",
                        (_now(), mid),
                    )
                    self._event(c, mid, "mission.succeeded", {})
                    c.execute("COMMIT")
                    return self.get(mid)
                if step["state"] == "running":
                    # A crash may occur after the side effect. Never replay blindly.
                    c.execute(
                        "UPDATE steps SET state='waiting',wait_reason='restart requires outcome confirmation' WHERE id=?",
                        (step["id"],),
                    )
                    c.execute("UPDATE missions SET state='waiting' WHERE id=?", (mid,))
                    self._event(
                        c, mid, "step.recovery_wait", {"step": step["position"]}
                    )
                    c.execute("COMMIT")
                    return self.get(mid)
                args = _resolve_references(c, mid, json.loads(step["args"]))
                ok, denial = authorize_mission_tool(step["tool"], args)
                if not ok:
                    c.execute(
                        "UPDATE steps SET state='failed',error=? WHERE id=?",
                        (str(redact(denial)), step["id"]),
                    )
                    c.execute(
                        "UPDATE missions SET state='failed',error='step permission denied' WHERE id=?",
                        (mid,),
                    )
                    self._event(
                        c,
                        mid,
                        "step.permission_denied",
                        {"step": step["position"], "reason": denial},
                    )
                    c.execute("COMMIT")
                    return self.get(mid)
                attempts = step["attempts"] + 1
                c.execute(
                    "UPDATE steps SET state='running',attempts=?,started_at=? WHERE id=?",
                    (attempts, _now(), step["id"]),
                )
                self._event(
                    c,
                    mid,
                    "step.started",
                    {"step": step["position"], "attempt": attempts},
                )
                c.execute("COMMIT")
                remaining = max(0.0, float(m["deadline"]) - clock())
                completed, outcome = _run_bounded(
                    runner, step["tool"], args, step["idempotency_key"], remaining
                )
                c.execute("BEGIN IMMEDIATE")
                latest_m = c.execute(
                    "SELECT * FROM missions WHERE id=?", (mid,)
                ).fetchone()
                latest_s = c.execute(
                    "SELECT * FROM steps WHERE id=?", (step["id"],)
                ).fetchone()
                if (
                    lease_owner is not None
                    and latest_m
                    and latest_m["lease_owner"] != lease_owner
                ):
                    c.execute("COMMIT")
                    return self.get(mid)
                if (
                    lease_owner is not None
                    and latest_m
                    and (
                        not isinstance(latest_m["lease_expires"], (int, float))
                        or not math.isfinite(latest_m["lease_expires"])
                        or latest_m["lease_expires"] < clock()
                    )
                ):
                    reason = (
                        "worker lease expired; explicit outcome resolution required"
                    )
                    c.execute(
                        "UPDATE steps SET state='waiting',wait_reason=? WHERE id=? AND state='running'",
                        (reason, step["id"]),
                    )
                    c.execute(
                        "UPDATE missions SET state='waiting',error='worker lease expired',updated_at=? WHERE id=? AND state='running' AND lease_owner=?",
                        (_now(), mid, lease_owner),
                    )
                    self._event(
                        c,
                        mid,
                        "worker.lease_expired",
                        {
                            "owner": lease_owner,
                            "step": step["position"],
                            "reason": reason,
                        },
                    )
                    c.execute("COMMIT")
                    return self.get(mid)
                if (
                    not latest_m
                    or latest_m["state"] != "running"
                    or not latest_s
                    or latest_s["state"] != "running"
                    or latest_m["current_step"] != step["position"]
                ):
                    c.execute("COMMIT")
                    return self.get(mid)
                if clock() > float(latest_m["deadline"]):
                    c.execute(
                        "UPDATE steps SET state='failed',error='deadline exceeded' WHERE id=? AND state='running'",
                        (step["id"],),
                    )
                    c.execute(
                        "UPDATE missions SET state='failed',error='deadline exceeded',updated_at=? WHERE id=? AND state='running'",
                        (_now(), mid),
                    )
                    self._event(
                        c,
                        mid,
                        "mission.failed",
                        {"error": "deadline exceeded", "step": step["position"]},
                    )
                    c.execute("COMMIT")
                    return self.get(mid)
                if not completed and isinstance(outcome, TimeoutError):
                    c.execute(
                        "UPDATE steps SET state='failed',error='deadline exceeded' WHERE id=? AND state='running'",
                        (step["id"],),
                    )
                    c.execute(
                        "UPDATE missions SET state='failed',error='deadline exceeded',updated_at=? WHERE id=? AND state='running'",
                        (_now(), mid),
                    )
                    self._event(c, mid, "step.timed_out", {"step": step["position"]})
                    c.execute("COMMIT")
                    return self.get(mid)
                if not completed:
                    exc = outcome
                    message = str(redact(exc))
                    if attempts <= latest_m["max_retries"]:
                        c.execute(
                            "UPDATE steps SET state='pending',error=? WHERE id=?",
                            (message, step["id"]),
                        )
                        self._event(
                            c,
                            mid,
                            "step.retry",
                            {
                                "step": step["position"],
                                "attempt": attempts,
                                "error": message,
                            },
                        )
                        c.execute("COMMIT")
                        backoff(min(30.0, 2.0 ** (attempts - 1)))
                        continue
                    c.execute(
                        "UPDATE steps SET state='failed',error=? WHERE id=?",
                        (message, step["id"]),
                    )
                    c.execute(
                        "UPDATE missions SET state='failed',error='retry budget exhausted' WHERE id=?",
                        (mid,),
                    )
                    self._event(
                        c,
                        mid,
                        "mission.failed",
                        {"step": step["position"], "error": message},
                    )
                    c.execute("COMMIT")
                    return self.get(mid)
                else:
                    result = verify_mission_result(outcome)
                if result["status"] == "waiting":
                    reason = str(result["waiting_for"])
                    c.execute(
                        "UPDATE steps SET state='waiting',wait_reason=?,result=? WHERE id=? AND state='running'",
                        (reason, _json(result), step["id"]),
                    )
                    c.execute(
                        "UPDATE missions SET state='waiting',updated_at=? WHERE id=? AND state='running'",
                        (_now(), mid),
                    )
                    self._event(
                        c,
                        mid,
                        "step.waiting",
                        {
                            "step": step["position"],
                            "reason": reason,
                            "evidence_count": len(result["evidence"]),
                        },
                    )
                    c.execute("COMMIT")
                    return self.get(mid)
                if result["status"] == "failed":
                    message = "runner reported a verified failure"
                    c.execute(
                        "UPDATE steps SET state='failed',error=?,result=?,completed_at=? WHERE id=? AND state='running'",
                        (message, _json(result), _now(), step["id"]),
                    )
                    c.execute(
                        "UPDATE missions SET state='failed',error='step reported failure',updated_at=? WHERE id=? AND state='running'",
                        (_now(), mid),
                    )
                    self._event(
                        c,
                        mid,
                        "mission.failed",
                        {
                            "step": step["position"],
                            "error": message,
                            "evidence_count": len(result["evidence"]),
                        },
                    )
                    c.execute("COMMIT")
                    return self.get(mid)
                if self._quarantine_phase11_success_in_transaction(c, mid, step=step):
                    c.execute("COMMIT")
                    return self.get(mid)
                c.execute(
                    "UPDATE steps SET state='succeeded',result=?,completed_at=? WHERE id=? AND state='running'",
                    (_json(result), _now(), step["id"]),
                )
                c.execute(
                    "UPDATE missions SET current_step=?,updated_at=? WHERE id=? AND state='running'",
                    (step["position"] + 1, _now(), mid),
                )
                self._event(
                    c,
                    mid,
                    "step.succeeded",
                    {
                        "step": step["position"],
                        "evidence_count": len(result["evidence"]),
                        "postconditions": [
                            condition["name"] for condition in result["postconditions"]
                        ],
                    },
                )
                c.execute("COMMIT")
        finally:
            c.close()

    def cancel(self, mid: str) -> Mission:
        """Atomically cancel and discard any in-flight result before it can commit."""
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            m = c.execute("SELECT state FROM missions WHERE id=?", (mid,)).fetchone()
            if not m:
                raise KeyError(mid)
            if m["state"] == "cancelled" and self._phase11_kill_in_transaction(c, mid):
                c.execute("COMMIT")
                return self.get(mid)
            if "cancelled" not in TRANSITIONS[m["state"]]:
                raise InvalidTransition(f"{m['state']} -> cancelled")
            discarded = {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": "cancelled while outcome was unknown; late result discarded",
            }
            c.execute(
                "UPDATE steps SET state='skipped',wait_reason='cancelled; late result discarded',result=?,completed_at=? WHERE mission_id=? AND state='running'",
                (_json(discarded), _now(), mid),
            )
            c.execute(
                "UPDATE missions SET state='cancelled',updated_at=? WHERE id=?",
                (_now(), mid),
            )
            self._event(
                c,
                mid,
                "mission.cancelled",
                {"reason": "user interrupt", "active_result": "discarded"},
            )
            c.execute("COMMIT")
        except Exception:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()
        return self.get(mid)

    def claim_next(
        self,
        owner: str,
        *,
        lease_seconds: float = 30,
        clock: Callable[[], float] = _now,
    ) -> str | None:
        self.initialize()
        owner = _worker_owner(owner)
        lease_seconds = _lease_seconds(lease_seconds)
        now = clock()
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT id FROM missions WHERE state='running' AND (lease_owner IS NULL OR lease_expires<?) ORDER BY created_at,id LIMIT 1",
                (now,),
            ).fetchone()
            if not row:
                c.execute("COMMIT")
                return None
            changed = c.execute(
                "UPDATE missions SET lease_owner=?,lease_expires=?,lease_heartbeat=? WHERE id=? AND state='running' AND (lease_owner IS NULL OR lease_expires<?)",
                (owner, now + lease_seconds, now, row["id"], now),
            ).rowcount
            if changed != 1:
                c.execute("ROLLBACK")
                return None
            self._event(
                c,
                row["id"],
                "worker.claimed",
                {"owner": owner, "lease_seconds": lease_seconds},
            )
            c.execute("COMMIT")
            return row["id"]
        except Exception:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def heartbeat(self, mid: str, owner: str, *, lease_seconds: float = 30) -> bool:
        self.initialize()
        owner = _worker_owner(owner)
        lease_seconds = _lease_seconds(lease_seconds)
        now = _now()
        c = self._connect()
        try:
            with c:
                return (
                    c.execute(
                        "UPDATE missions SET lease_expires=?,lease_heartbeat=? WHERE id=? AND state='running' AND lease_owner=?",
                        (now + lease_seconds, now, mid, owner),
                    ).rowcount
                    == 1
                )
        finally:
            c.close()

    def release_lease(self, mid: str, owner: str) -> None:
        self.initialize()
        c = self._connect()
        try:
            with c:
                c.execute(
                    "UPDATE missions SET lease_owner=NULL,lease_expires=NULL,lease_heartbeat=NULL WHERE id=? AND lease_owner=?",
                    (mid, owner),
                )
        finally:
            c.close()

    def resolve(
        self, mid: str, action: str, *, user_input: str | None = None
    ) -> Mission:
        """Resolve an uncertain/waiting step without ever silently replaying it."""
        if action not in {"succeeded", "retry", "failed"}:
            raise ValueError("resolution must be succeeded, retry, or failed")
        safe_input = redact(user_input) if user_input else None
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            m = c.execute(
                "SELECT state,max_retries FROM missions WHERE id=?", (mid,)
            ).fetchone()
            step = c.execute(
                "SELECT * FROM steps WHERE mission_id=? AND state='waiting' ORDER BY position LIMIT 1",
                (mid,),
            ).fetchone()
            if not m or m["state"] != "waiting" or not step:
                raise InvalidTransition("mission has no waiting step to resolve")
            if action == "succeeded":
                resolved = verify_mission_result(
                    {
                        "status": "succeeded",
                        "data": {"user_resolution": safe_input or "confirmed"},
                        "evidence": [],
                        "postconditions": [
                            {"name": "owner_confirmed_outcome", "satisfied": True}
                        ],
                        "waiting_for": None,
                    }
                )
                c.execute(
                    "UPDATE steps SET state='succeeded',result=?,completed_at=? WHERE id=?",
                    (_json(resolved), _now(), step["id"]),
                )
                target = "running"
            elif action == "retry":
                if int(step["attempts"]) >= int(m["max_retries"]) + 1:
                    raise BudgetExceeded("retry budget exhausted")
                c.execute(
                    "UPDATE steps SET state='pending',wait_reason=NULL WHERE id=?",
                    (step["id"],),
                )
                target = "running"
            else:
                c.execute(
                    "UPDATE steps SET state='failed',error=? WHERE id=?",
                    (str(safe_input or "user marked failed"), step["id"]),
                )
                target = "failed"
            next_position = (
                step["position"] + 1 if action == "succeeded" else step["position"]
            )
            c.execute(
                "UPDATE missions SET state=?,current_step=?,updated_at=? WHERE id=?",
                (target, next_position, _now(), mid),
            )
            self._event(
                c,
                mid,
                "step.resolved",
                {
                    "step": step["position"],
                    "resolution": action,
                    "user_input": safe_input,
                },
            )
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()
        return self.get(mid)

    def pause(self, mid: str) -> Mission:
        """Pause idle work, or quarantine an active unknown outcome for resolution."""
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            m = c.execute("SELECT state FROM missions WHERE id=?", (mid,)).fetchone()
            if not m:
                raise KeyError(mid)
            if m["state"] != "running":
                raise InvalidTransition(f"{m['state']} -> paused")
            active = c.execute(
                "SELECT id,position FROM steps WHERE mission_id=? AND state='running' ORDER BY position LIMIT 1",
                (mid,),
            ).fetchone()
            if active:
                reason = "paused while step outcome was unknown; explicit resolution required"
                discarded = {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": reason,
                }
                c.execute(
                    "UPDATE steps SET state='waiting',wait_reason=?,result=? WHERE id=? AND state='running'",
                    (reason, _json(discarded), active["id"]),
                )
                c.execute(
                    "UPDATE missions SET state='waiting',updated_at=? WHERE id=? AND state='running'",
                    (_now(), mid),
                )
                self._event(
                    c,
                    mid,
                    "step.paused_waiting",
                    {
                        "step": active["position"],
                        "reason": reason,
                        "active_result": "discarded",
                    },
                )
            else:
                c.execute(
                    "UPDATE missions SET state='paused',updated_at=? WHERE id=? AND state='running'",
                    (_now(), mid),
                )
                self._event(c, mid, "mission.paused", {"reason": "user pause"})
            c.execute("COMMIT")
        except Exception:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()
        return self.get(mid)

    def events(self, mid: str) -> list[dict[str, Any]]:
        self.initialize()
        c = self._connect()
        try:
            output = []
            previous = ""
            for r in c.execute(
                "SELECT * FROM events WHERE mission_id=? ORDER BY seq", (mid,)
            ):
                expected = hashlib.sha256(
                    f"{mid}\0{r['timestamp']:.9f}\0{r['event']}\0{r['detail']}\0{previous}".encode()
                ).hexdigest()
                if r["prev_hash"] != previous or r["event_hash"] != expected:
                    raise MissionError("Mission audit integrity check failed")
                output.append(
                    {
                        "seq": r["seq"],
                        "timestamp": r["timestamp"],
                        "event": r["event"],
                        "detail": json.loads(r["detail"]),
                        "event_hash": r["event_hash"],
                    }
                )
                previous = r["event_hash"]
            return output
        finally:
            c.close()


def _local_runner(tool: str, args: dict[str, Any], key: str) -> Any:
    """CLI dry-run tools have no external side effects or provider calls."""
    if tool == "local_note":
        data = {"idempotency_key": key, "note": str(args.get("text", ""))[:500]}
        return {
            "status": "succeeded",
            "data": data,
            "evidence": [],
            "postconditions": [
                {"name": "note_materialized_in_mission_result", "satisfied": True}
            ],
            "waiting_for": None,
        }
    if tool == "local_checklist":
        data = {"items": [str(x)[:200] for x in args.get("items", [])[:50]]}
        return {
            "status": "succeeded",
            "data": data,
            "evidence": [],
            "postconditions": [
                {"name": "checklist_materialized_in_mission_result", "satisfied": True}
            ],
            "waiting_for": None,
        }
    from core.mission_tools import run as run_workspace_tool

    return run_workspace_tool(tool, args, key)


def worker_once(
    store: MissionStore,
    owner: str,
    runner: ToolRunner | None = None,
    *,
    lease_seconds: float = 60,
) -> Mission | None:
    """Claim and execute at most one approved mission with a renewable lease."""
    owner = _worker_owner(owner)
    lease_seconds = _lease_seconds(lease_seconds)
    selected_runner = runner or _local_runner
    runner_owner = getattr(selected_runner, "__self__", None)
    authority_observer = getattr(runner_owner, "anchor_current_authority", None)
    mid = store.claim_next(owner, lease_seconds=lease_seconds)
    if mid is None:
        return None
    stopped = threading.Event()

    def heartbeats() -> None:
        while not stopped.wait(max(0.25, lease_seconds / 3)):
            if not store.heartbeat(mid, owner, lease_seconds=lease_seconds):
                return

    beat = threading.Thread(
        target=heartbeats, name="onyx-mission-heartbeat", daemon=True
    )
    beat.start()
    try:
        if not store.heartbeat(mid, owner, lease_seconds=lease_seconds):
            raise MissionError("worker lease was lost before execution")
        result = store.run(
            mid, selected_runner, lease_owner=owner, backoff=lambda _: None
        )
        if callable(authority_observer):
            authority_observer(mid)
        return result
    finally:
        stopped.set()
        beat.join(timeout=1)
        store.release_lease(mid, owner)


class MissionWorker:
    """Application-owned foreground worker for already-approved local missions.

    This object owns only polling and lease lifecycle. It deliberately delegates
    all state transitions to ``MissionStore`` and never opens the mission database
    or broadens the tool policy itself.
    """

    def __init__(
        self,
        store: MissionStore,
        runner: ToolRunner,
        *,
        owner: str | None = None,
        poll_interval: float = 1.0,
        lease_seconds: float = 60.0,
        on_error: Callable[[str], None] | None = None,
    ):
        if (
            isinstance(poll_interval, bool)
            or not isinstance(poll_interval, (int, float))
            or not math.isfinite(poll_interval)
        ):
            raise ValueError("invalid worker poll interval")
        self.store = store
        self.runner = runner
        self.owner = _worker_owner(
            owner or f"app-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        )
        self.poll_interval = min(
            MAX_POLL_SECONDS, max(MIN_POLL_SECONDS, float(poll_interval))
        )
        self.lease_seconds = _lease_seconds(lease_seconds)
        self.on_error = on_error
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def start(self) -> bool:
        """Start one polling thread; return False when it is already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="onyx-mission-worker", daemon=True
            )
            self._thread.start()
            return True

    def stop(self, timeout: float | None = 15.0) -> bool:
        """Request a clean stop and wait boundedly for the current local step."""
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout < 0
        ):
            raise ValueError("invalid worker stop timeout")
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        stopped = not thread or not thread.is_alive()
        if stopped:
            with self._lock:
                if self._thread is thread:
                    self._thread = None
        return stopped

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = worker_once(
                    self.store,
                    self.owner,
                    self.runner,
                    lease_seconds=self.lease_seconds,
                )
            except Exception as exc:
                if self.on_error:
                    try:
                        self.on_error(str(redact(exc)))
                    except Exception:
                        pass
                result = None
            if result is None and self._stop.wait(self.poll_interval):
                return


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Governed Onyx missions")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("title")
    c.add_argument("--plan", required=True, help="JSON list of steps")
    for name in ("show", "approve", "run", "pause", "resume", "cancel", "events"):
        q = sub.add_parser(name)
        q.add_argument("mission_id")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("mission_id")
    resolve.add_argument("resolution", choices=("succeeded", "retry", "failed"))
    resolve.add_argument("--input")
    worker = sub.add_parser("worker")
    mode = worker.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--poll", type=float)
    worker.add_argument(
        "--owner", default=f"cli-{os.getpid() if hasattr(os, 'getpid') else 'worker'}"
    )
    sub.add_parser("doctor")
    example = sub.add_parser("example")
    example.add_argument("--root", default=str(Path.cwd()))
    sub.add_parser("list")
    a = p.parse_args(argv)
    s = MissionStore(a.db)
    try:
        if a.cmd == "create":
            out = asdict(s.create(a.title, json.loads(a.plan)))
        elif a.cmd == "list":
            out = [asdict(x) for x in s.list()]
        elif a.cmd == "show":
            out = asdict(s.get(a.mission_id))
        elif a.cmd == "approve":
            summary = s.plan_summary(a.mission_id)
            if not sys.stdin.isatty():
                raise PermissionError("interactive trusted approval requires a TTY")
            print(
                json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
                file=sys.stderr,
            )
            expected = f"APPROVE {summary['plan_digest']}"
            typed = input(f"Type exactly '{expected}' to approve: ")
            set_permission_callback(
                lambda request: request["digest"] if typed == expected else None
            )
            try:
                out = asdict(s.approve(a.mission_id))
            finally:
                set_permission_callback(None)
        elif a.cmd in {"run", "resume"}:
            out = asdict(s.run(a.mission_id, _local_runner, backoff=lambda _: None))
        elif a.cmd == "pause":
            out = asdict(s.pause(a.mission_id))
        elif a.cmd == "cancel":
            out = asdict(s.cancel(a.mission_id))
        elif a.cmd == "resolve":
            out = asdict(s.resolve(a.mission_id, a.resolution, user_input=a.input))
        elif a.cmd == "doctor":
            from core.mission_tools import WorkspaceToolError, _roots

            try:
                roots = [str(x) for x in _roots()]
                root_error = None
            except WorkspaceToolError as exc:
                roots = []
                root_error = str(redact(exc))
            s.initialize()
            out = {
                "database": str(s.path),
                "mission_db_writes": True,
                "workspace_writes": False,
                "network_tools": False,
                "paid_tools": False,
                "provider_free_tools": sorted(MISSION_TOOL_POLICIES),
                "workspace_roots": roots,
                "workspace_root_error": root_error,
                "lease_seconds_range": [MIN_LEASE_SECONDS, MAX_LEASE_SECONDS],
            }
        elif a.cmd == "example":
            out = asdict(
                s.create(
                    "Daily workspace audit",
                    [
                        {
                            "tool": "workspace_inventory",
                            "args": {"root": a.root, "max_files": 500},
                        },
                        {
                            "tool": "workspace_text_search",
                            "args": {
                                "root": a.root,
                                "query": "TODO",
                                "max_results": 50,
                            },
                        },
                        {
                            "tool": "workspace_read_text",
                            "args": {
                                "root": a.root,
                                "path": "{{step.1.result.matches.0.path}}",
                                "max_bytes": 65536,
                            },
                        },
                        {
                            "tool": "workspace_hash",
                            "args": {
                                "root": a.root,
                                "path": "{{step.1.result.matches.0.path}}",
                            },
                        },
                        {"tool": "local_system_status", "args": {}},
                    ],
                )
            )
        elif a.cmd == "worker":
            if a.once:
                result = worker_once(s, a.owner)
                out = asdict(result) if result else {"idle": True}
            else:
                interval = max(0.1, min(float(a.poll), 60.0))
                processed = 0
                try:
                    while True:
                        result = worker_once(s, a.owner)
                        if result is None:
                            time.sleep(interval)
                        else:
                            processed += 1
                except KeyboardInterrupt:
                    out = {"stopped": True, "processed": processed}
        else:
            out = s.events(a.mission_id)
        print(json.dumps(out, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        MissionError,
        PermissionError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"error": str(redact(exc))}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
