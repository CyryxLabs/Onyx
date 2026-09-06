"""Isolated Phase 6 Agentic Core V5 lexical schema correction.

V5 preserves frozen V1-V4 behavior and replaces only unsafe SQL normalization
with a quote/comment-aware lexical signature. It is strict default-off and is
not live-wired.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
from pathlib import Path
from typing import Mapping

from core.missions import MissionStore
from core.phase6_agentic_core_v1 import (
    AgenticFeatureGateV1,
    AgenticStateStoreV1,
    WorkspaceScopeV1,
)
from core.phase6_agentic_core_v2 import artifact_root_v2
from core.phase6_agentic_core_v4 import (
    DEFAULT_FENCE_SECONDS,
    AgenticCoreV4,
    AgenticCoreV4ContractError,
    AgenticCoreV4Denied,
    AgenticCoreV4Error,
    AgenticStateStoreV4,
    StrictMissionMaterializerV4,
    TerminableProcessExecutorV4,
)


FEATURE_FLAG = "ONYX_PHASE6_AGENTIC_CORE_V5"
SCHEMA_VERSION = 5


class AgenticCoreV5Error(AgenticCoreV4Error):
    """V5 lexical schema authentication failed."""


class AgenticCoreV5ContractError(AgenticCoreV4ContractError):
    """A V5 caller supplied a non-canonical contract."""


class AgenticCoreV5Denied(AgenticCoreV4Denied):
    """A V5 authority denied an operation."""


class AgenticFeatureGateV5:
    def __init__(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise AgenticCoreV5ContractError("enabled must be an exact boolean")
        self.enabled = enabled

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AgenticFeatureGateV5":
        import os

        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


def _quoted_token(sql: str, start: int, quote: str) -> tuple[str, int]:
    index = start + 1
    size = len(sql)
    closing = "]" if quote == "[" else quote
    while index < size:
        if sql[index] != closing:
            index += 1
            continue
        if index + 1 < size and sql[index + 1] == closing:
            index += 2
            continue
        return sql[start : index + 1], index + 1
    raise AgenticCoreV5ContractError("unterminated quoted SQL token")


def sql_tokens_v5(sql: str) -> tuple[str, ...]:
    """Tokenize SQL without modifying any quoted or comment byte content."""

    if type(sql) is not str or not sql.strip():
        raise AgenticCoreV5ContractError("SQL definition must be non-empty text")
    tokens: list[str] = []
    index = 0
    size = len(sql)
    while index < size:
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            end = index + 2
            while end < size and sql[end] not in "\r\n":
                end += 1
            tokens.append("comment-line:" + sql[index:end])
            index = end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                raise AgenticCoreV5ContractError("unterminated SQL block comment")
            end += 2
            tokens.append("comment-block:" + sql[index:end])
            index = end
            continue
        if character in {"'", '"', "`", "["}:
            token, index = _quoted_token(sql, index, character)
            kind = {"'": "string", '"': "double", "`": "backtick", "[": "bracket"}[
                character
            ]
            tokens.append(f"{kind}:{token}")
            continue
        if character.isalpha() or character in {"_", "$"}:
            end = index + 1
            while end < size and (sql[end].isalnum() or sql[end] in {"_", "$"}):
                end += 1
            tokens.append("word:" + sql[index:end].lower())
            index = end
            continue
        if character.isdigit():
            end = index + 1
            while end < size and (sql[end].isalnum() or sql[end] in {".", "_"}):
                end += 1
            tokens.append("number:" + sql[index:end].lower())
            index = end
            continue
        matched = False
        for operator in ("->>", "<=", ">=", "!=", "==", "<>", "||", "->"):
            if sql.startswith(operator, index):
                tokens.append("operator:" + operator)
                index += len(operator)
                matched = True
                break
        if matched:
            continue
        tokens.append("punctuation:" + character)
        index += 1
    return tuple(tokens)


def normalized_sql_v5(sql: str) -> str:
    """Canonical JSON encoding of lexical tokens; useful for audit evidence."""

    return json.dumps(sql_tokens_v5(sql), ensure_ascii=False, separators=(",", ":"))


def _schema_signature_v5(connection: sqlite3.Connection) -> str:
    objects = []
    for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ):
        if row[3] is None:
            raise AgenticCoreV5Error("schema object has no stored SQL")
        objects.append((row[0], row[1], row[2], sql_tokens_v5(str(row[3]))))
    tables = [row[1] for row in objects if row[0] == "table"]
    details: dict[str, object] = {}
    for table in tables:
        details[f"table_xinfo:{table}"] = [
            tuple(row) for row in connection.execute(f"PRAGMA table_xinfo('{table}')")
        ]
        details[f"foreign_key_list:{table}"] = [
            tuple(row)
            for row in connection.execute(f"PRAGMA foreign_key_list('{table}')")
        ]
        indexes = [
            tuple(row) for row in connection.execute(f"PRAGMA index_list('{table}')")
        ]
        details[f"index_list:{table}"] = indexes
        for index in indexes:
            details[f"index_xinfo:{index[1]}"] = [
                tuple(row)
                for row in connection.execute(f"PRAGMA index_xinfo('{index[1]}')")
            ]
    payload = {"objects": objects, "details": details}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class AgenticStateStoreV5(AgenticStateStoreV4):
    """V4 authority with lexical-state-safe schema authentication."""

    _DDL = tuple(
        statement.replace("schema_version=4", "schema_version=5").replace(
            "phase6 v4 lineage is immutable", "phase6 v5 lineage is immutable"
        )
        for statement in AgenticStateStoreV4._DDL
    )

    def __init__(
        self,
        path: Path | str,
        gate: AgenticFeatureGateV5,
        *,
        fence_seconds: float = DEFAULT_FENCE_SECONDS,
    ) -> None:
        if type(gate) is not AgenticFeatureGateV5 or not gate.enabled:
            raise AgenticCoreV5Denied("Phase 6 V5 agentic core is disabled")
        self._path = Path(path)
        if not self._path.is_absolute() or self._path.name in {"", ".", ".."}:
            raise AgenticCoreV5ContractError(
                "an explicit absolute sidecar path is required"
            )
        if (
            isinstance(fence_seconds, bool)
            or not isinstance(fence_seconds, (int, float))
            or not math.isfinite(fence_seconds)
            or not 0.05 <= fence_seconds <= 300.0
        ):
            raise AgenticCoreV5ContractError(
                "materialization fence duration is invalid"
            )
        self._fence_seconds = float(fence_seconds)
        self._coord_path = self._path.with_name(
            f"{self._path.stem}.v5-coordination{self._path.suffix or '.sqlite3'}"
        )
        self._plans = AgenticStateStoreV1(self._path, AgenticFeatureGateV1(True))
        self._lock = threading.RLock()
        self._expected_signature = self._build_expected_signature()
        self.initialize()

    @classmethod
    def _build_expected_signature(cls) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            for statement in cls._DDL:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO metadata(schema_version) VALUES(?)", (SCHEMA_VERSION,)
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            return _schema_signature_v5(connection)
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock:
            self._coord_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            try:
                existing = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if existing == 0 and version == 0:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in self._DDL:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO metadata(schema_version) VALUES(?)",
                        (SCHEMA_VERSION,),
                    )
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    connection.execute("COMMIT")
                signature = _schema_signature_v5(connection)
                metadata = connection.execute(
                    "SELECT schema_version FROM metadata"
                ).fetchall()
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                if (
                    signature != self._expected_signature
                    or int(connection.execute("PRAGMA user_version").fetchone()[0])
                    != SCHEMA_VERSION
                    or [tuple(row) for row in metadata] != [(SCHEMA_VERSION,)]
                    or integrity != "ok"
                    or foreign_keys
                ):
                    raise AgenticCoreV5Error(
                        "Phase 6 V5 coordination schema authentication failed"
                    )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()


class StrictMissionMaterializerV5(StrictMissionMaterializerV4):
    """V4 exact-input materializer with V5-safe ledger authentication."""

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        expected = sqlite3.connect(":memory:")
        try:
            expected.execute(self._DDL)
            expected_signature = _schema_signature_v5(expected)
        finally:
            expected.close()
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
            if rows == 0:
                connection.execute(self._DDL)
                connection.commit()
            if _schema_signature_v5(connection) != expected_signature:
                raise AgenticCoreV5Error(
                    "V5 exact-input ledger schema authentication failed"
                )
        finally:
            connection.close()


class AgenticCoreV5(AgenticCoreV4):
    """V4 process/compute/materialization closure over V5 authenticated state."""

    def __init__(
        self,
        state_store: AgenticStateStoreV5,
        mission_store: MissionStore,
        workspace_scope: WorkspaceScopeV1,
        *,
        executor: TerminableProcessExecutorV4 | None = None,
    ) -> None:
        if (
            type(state_store) is not AgenticStateStoreV5
            or type(mission_store) is not MissionStore
            or type(workspace_scope) is not WorkspaceScopeV1
        ):
            raise AgenticCoreV5ContractError(
                "exact V5 state, MissionStore and workspace scope are required"
            )
        self._state = state_store
        self._missions = mission_store
        self._workspace = workspace_scope
        self._executor = executor or TerminableProcessExecutorV4()
        self._materializer = StrictMissionMaterializerV5(mission_store)
        self._closed = False


def create_phase6_agentic_core_v5(
    *,
    gate: AgenticFeatureGateV5,
    sidecar_path: Path | str,
    mission_store: MissionStore,
    workspace_scope: WorkspaceScopeV1,
    fence_seconds: float = DEFAULT_FENCE_SECONDS,
) -> AgenticCoreV5:
    state = AgenticStateStoreV5(sidecar_path, gate, fence_seconds=fence_seconds)
    return AgenticCoreV5(state, mission_store, workspace_scope)


artifact_root_v5 = artifact_root_v2
