"""Durable metadata-only context graph for event-driven Onyx awareness.

The graph stores identifiers and transitions already admitted by the awareness
policy.  It never captures screen, clipboard, message, transcript or process
content and owns no timer, worker, provider, listener or execution authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


FEATURE_FLAG = "ONYX_CONTEXT_GRAPH_V1"
SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_KIND = re.compile(r"[a-z][a-z0-9_.-]{2,95}")
_ALLOWED_METADATA = frozenset(
    {"application_id", "project_id", "state", "mission_id", "goal_id"}
)
_SENSITIVE_PARTS = frozenset(
    {"body", "clipboard", "content", "cookie", "image", "message", "screenshot", "secret", "text", "token", "transcript"}
)


class ContextGraphError(RuntimeError):
    pass


class ContextGraphContractError(ValueError):
    pass


class ContextGraphDenied(PermissionError):
    pass


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ContextGraphContractError(f"{label} is invalid")
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ContextGraphContractError("context graph path is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ContextGraphDenied("linked context graph storage is forbidden")
    if os.name != "nt":
        os.chmod(path.parent, 0o700)


@dataclass(frozen=True, slots=True)
class ContextGraphFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ContextGraphContractError("context graph feature gate is invalid")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ContextGraphFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class ContextGraphProjectionV1:
    owner_profile_id: str
    workspace_id: str
    active_application_id: str | None
    active_project_id: str | None
    nodes: tuple[tuple[str, str], ...]
    edges: tuple[tuple[str, str, str, int], ...]
    observations: int
    generated_at: float


class ContextGraphStoreV1:
    def __init__(self, path: Path | str, gate: ContextGraphFeatureGateV1) -> None:
        if type(gate) is not ContextGraphFeatureGateV1 or not gate.enabled:
            raise ContextGraphDenied("context graph is disabled")
        self.path = Path(path)
        _private_path(self.path)
        self._lock = threading.RLock()
        self._initialize()

    @property
    def background_workers(self) -> int:
        return 0

    @property
    def polling_interval(self) -> None:
        return None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS context_meta(
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS context_nodes(
                    owner_profile_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    node_kind TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    observations INTEGER NOT NULL,
                    PRIMARY KEY(owner_profile_id,workspace_id,node_kind,node_id)
                );
                CREATE TABLE IF NOT EXISTS context_edges(
                    owner_profile_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    observations INTEGER NOT NULL,
                    PRIMARY KEY(owner_profile_id,workspace_id,source_id,relation,target_id)
                );
                CREATE TABLE IF NOT EXISTS context_state(
                    owner_profile_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    active_application_id TEXT,
                    active_project_id TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner_profile_id,workspace_id)
                );
                CREATE TABLE IF NOT EXISTS context_events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_profile_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    signal_kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    occurred_at REAL NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS context_events_no_update
                BEFORE UPDATE ON context_events
                BEGIN
                    SELECT RAISE(ABORT, 'context events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS context_events_no_delete
                BEFORE DELETE ON context_events
                BEGIN
                    SELECT RAISE(ABORT, 'context events are append-only');
                END;
                """
            )
            row = connection.execute(
                "SELECT value FROM context_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO context_meta VALUES('schema_version',?)",
                    (str(SCHEMA_VERSION),),
                )
            elif str(row[0]) != str(SCHEMA_VERSION):
                raise ContextGraphDenied("context graph schema diverged")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ContextGraphDenied("context graph integrity check failed")
            self._verify_events(connection)

    @staticmethod
    def _verify_events(connection: sqlite3.Connection) -> None:
        expected_previous = "0" * 64
        for row in connection.execute(
            "SELECT owner_profile_id,workspace_id,signal_kind,payload_json,"
            "previous_hash,event_hash,occurred_at FROM context_events ORDER BY sequence"
        ):
            try:
                payload = json.loads(str(row[3]))
                expected_hash = hashlib.sha256(
                    _canonical(
                        {
                            "owner": str(row[0]),
                            "workspace": str(row[1]),
                            "kind": str(row[2]),
                            "payload": payload,
                            "previous_hash": expected_previous,
                            "occurred_at": float(row[6]),
                        }
                    ).encode()
                ).hexdigest()
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ContextGraphDenied("context event chain diverged") from exc
            if str(row[4]) != expected_previous or str(row[5]) != expected_hash:
                raise ContextGraphDenied("context event chain diverged")
            expected_previous = expected_hash

    @staticmethod
    def _upsert_node(
        connection: sqlite3.Connection,
        owner: str,
        workspace: str,
        kind: str,
        node_id: str,
        occurred_at: float,
    ) -> None:
        connection.execute(
            "INSERT INTO context_nodes VALUES(?,?,?,?,?,?,1) "
            "ON CONFLICT(owner_profile_id,workspace_id,node_kind,node_id) DO UPDATE "
            "SET last_seen=excluded.last_seen,observations=observations+1",
            (owner, workspace, kind, node_id, occurred_at, occurred_at),
        )

    @staticmethod
    def _upsert_edge(
        connection: sqlite3.Connection,
        owner: str,
        workspace: str,
        source: str,
        relation: str,
        target: str,
        occurred_at: float,
    ) -> None:
        connection.execute(
            "INSERT INTO context_edges VALUES(?,?,?,?,?,?,?,1) "
            "ON CONFLICT(owner_profile_id,workspace_id,source_id,relation,target_id) "
            "DO UPDATE SET last_seen=excluded.last_seen,observations=observations+1",
            (owner, workspace, source, relation, target, occurred_at, occurred_at),
        )

    def observe(
        self,
        *,
        signal_kind: str,
        owner_profile_id: str,
        workspace_id: str,
        occurred_at: float,
        metadata: Mapping[str, str],
    ) -> None:
        kind = signal_kind if type(signal_kind) is str else ""
        if _KIND.fullmatch(kind) is None:
            raise ContextGraphContractError("context signal kind is invalid")
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        if (
            isinstance(occurred_at, bool)
            or not isinstance(occurred_at, (int, float))
            or occurred_at <= 0
        ):
            raise ContextGraphContractError("context occurred_at is invalid")
        if type(metadata) is not dict:
            raise ContextGraphDenied("context graph metadata is not allowlisted")
        if any(
            set(key.replace("-", ".").replace("_", ".").split("."))
            & _SENSITIVE_PARTS
            for key in metadata
        ):
            raise ContextGraphDenied("context graph metadata is not allowlisted")
        clean = {
            key: _identifier(value, f"context {key}")
            for key, value in sorted(metadata.items())
            if key in _ALLOWED_METADATA
        }
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_events(connection)
            state = connection.execute(
                "SELECT * FROM context_state WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            ).fetchone()
            application = clean.get("application_id") or (
                None if state is None else state["active_application_id"]
            )
            project = clean.get("project_id") or (
                None if state is None else state["active_project_id"]
            )
            if "application_id" in clean:
                self._upsert_node(
                    connection, owner, workspace, "application", clean["application_id"], float(occurred_at)
                )
            if "project_id" in clean:
                self._upsert_node(
                    connection, owner, workspace, "project", clean["project_id"], float(occurred_at)
                )
            if application and project:
                self._upsert_edge(
                    connection,
                    owner,
                    workspace,
                    str(application),
                    "active_in",
                    str(project),
                    float(occurred_at),
                )
            connection.execute(
                "INSERT INTO context_state VALUES(?,?,?,?,?) "
                "ON CONFLICT(owner_profile_id,workspace_id) DO UPDATE SET "
                "active_application_id=excluded.active_application_id,"
                "active_project_id=excluded.active_project_id,updated_at=excluded.updated_at",
                (owner, workspace, application, project, float(occurred_at)),
            )
            previous = connection.execute(
                "SELECT event_hash FROM context_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = "0" * 64 if previous is None else str(previous[0])
            payload = _canonical(clean)
            digest = hashlib.sha256(
                _canonical(
                    {
                        "owner": owner,
                        "workspace": workspace,
                        "kind": kind,
                        "payload": clean,
                        "previous_hash": previous_hash,
                        "occurred_at": float(occurred_at),
                    }
                ).encode()
            ).hexdigest()
            connection.execute(
                "INSERT INTO context_events(owner_profile_id,workspace_id,signal_kind,payload_json,previous_hash,event_hash,occurred_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (owner, workspace, kind, payload, previous_hash, digest, float(occurred_at)),
            )
            connection.execute("COMMIT")

    def projection(
        self, owner_profile_id: str, workspace_id: str
    ) -> ContextGraphProjectionV1:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        with self._connect() as connection:
            self._verify_events(connection)
            state = connection.execute(
                "SELECT * FROM context_state WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            ).fetchone()
            nodes = tuple(
                (str(row[0]), str(row[1]))
                for row in connection.execute(
                    "SELECT node_kind,node_id FROM context_nodes WHERE owner_profile_id=? "
                    "AND workspace_id=? ORDER BY node_kind,node_id",
                    (owner, workspace),
                )
            )
            edges = tuple(
                (str(row[0]), str(row[1]), str(row[2]), int(row[3]))
                for row in connection.execute(
                    "SELECT source_id,relation,target_id,observations FROM context_edges "
                    "WHERE owner_profile_id=? AND workspace_id=? ORDER BY source_id,relation,target_id",
                    (owner, workspace),
                )
            )
            observations = int(
                connection.execute(
                    "SELECT COUNT(*) FROM context_events WHERE owner_profile_id=? AND workspace_id=?",
                    (owner, workspace),
                ).fetchone()[0]
            )
        return ContextGraphProjectionV1(
            owner,
            workspace,
            None if state is None else state["active_application_id"],
            None if state is None else state["active_project_id"],
            nodes,
            edges,
            observations,
            time.time(),
        )


__all__ = [
    "FEATURE_FLAG",
    "ContextGraphContractError",
    "ContextGraphDenied",
    "ContextGraphError",
    "ContextGraphFeatureGateV1",
    "ContextGraphProjectionV1",
    "ContextGraphStoreV1",
]
