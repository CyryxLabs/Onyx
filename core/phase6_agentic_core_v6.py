"""Isolated Phase 6 Agentic Core V6 ASCII-only lexical correction."""

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
    TerminableProcessExecutorV4,
)
from core.phase6_agentic_core_v5 import (
    AgenticCoreV5,
    AgenticCoreV5ContractError,
    AgenticCoreV5Denied,
    AgenticCoreV5Error,
    AgenticStateStoreV5,
    StrictMissionMaterializerV5,
    _quoted_token,
)


FEATURE_FLAG = "ONYX_PHASE6_AGENTIC_CORE_V6"
SCHEMA_VERSION = 6
_ASCII_WHITESPACE = frozenset(" \t\r\n\f")
_ASCII_WORD_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$")
_ASCII_WORD_CONTINUE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$0123456789"
)
_ASCII_DIGITS = frozenset("0123456789")


class AgenticCoreV6Error(AgenticCoreV5Error):
    """V6 ASCII lexical schema authentication failed."""


class AgenticCoreV6ContractError(AgenticCoreV5ContractError):
    """A V6 caller supplied a non-canonical contract."""


class AgenticCoreV6Denied(AgenticCoreV5Denied):
    """A V6 authority denied an operation."""


class AgenticFeatureGateV6:
    def __init__(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise AgenticCoreV6ContractError("enabled must be an exact boolean")
        self.enabled = enabled

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AgenticFeatureGateV6":
        import os

        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


def _lower_ascii(value: str) -> str:
    return "".join(
        chr(ord(char) + 32) if "A" <= char <= "Z" else char for char in value
    )


def sql_tokens_v6(sql: str) -> tuple[str, ...]:
    """Tokenize with SQLite-relevant ASCII classes and exact Unicode bytes."""

    if type(sql) is not str or not sql:
        raise AgenticCoreV6ContractError("SQL definition must be non-empty text")
    if not any(character not in _ASCII_WHITESPACE for character in sql):
        raise AgenticCoreV6ContractError("SQL definition must contain a token")
    tokens: list[str] = []
    index = 0
    size = len(sql)
    while index < size:
        character = sql[index]
        if character in _ASCII_WHITESPACE:
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
                raise AgenticCoreV6ContractError("unterminated SQL block comment")
            end += 2
            tokens.append("comment-block:" + sql[index:end])
            index = end
            continue
        if character in {"'", '"', "`", "["}:
            try:
                token, index = _quoted_token(sql, index, character)
            except AgenticCoreV5ContractError as exc:
                raise AgenticCoreV6ContractError(str(exc)) from exc
            kind = {"'": "string", '"': "double", "`": "backtick", "[": "bracket"}[
                character
            ]
            tokens.append(f"{kind}:{token}")
            continue
        if character in _ASCII_WORD_START:
            end = index + 1
            while end < size and sql[end] in _ASCII_WORD_CONTINUE:
                end += 1
            tokens.append("word:" + _lower_ascii(sql[index:end]))
            index = end
            continue
        if character in _ASCII_DIGITS:
            end = index + 1
            while end < size and (sql[end] in _ASCII_WORD_CONTINUE or sql[end] == "."):
                end += 1
            tokens.append("number:" + _lower_ascii(sql[index:end]))
            index = end
            continue
        if ord(character) > 127 or character == "\v":
            tokens.append("exact:" + character)
            index += 1
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


def normalized_sql_v6(sql: str) -> str:
    return json.dumps(sql_tokens_v6(sql), ensure_ascii=False, separators=(",", ":"))


def _schema_signature_v6(connection: sqlite3.Connection) -> str:
    objects = []
    for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ):
        if row[3] is None:
            raise AgenticCoreV6Error("schema object has no stored SQL")
        objects.append((row[0], row[1], row[2], sql_tokens_v6(str(row[3]))))
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
        for item in indexes:
            details[f"index_xinfo:{item[1]}"] = [
                tuple(row)
                for row in connection.execute(f"PRAGMA index_xinfo('{item[1]}')")
            ]
    payload = {"objects": objects, "details": details}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class AgenticStateStoreV6(AgenticStateStoreV5):
    _DDL = tuple(
        statement.replace("schema_version=5", "schema_version=6").replace(
            "phase6 v5 lineage is immutable", "phase6 v6 lineage is immutable"
        )
        for statement in AgenticStateStoreV5._DDL
    )

    def __init__(
        self,
        path: Path | str,
        gate: AgenticFeatureGateV6,
        *,
        fence_seconds: float = DEFAULT_FENCE_SECONDS,
    ) -> None:
        if type(gate) is not AgenticFeatureGateV6 or not gate.enabled:
            raise AgenticCoreV6Denied("Phase 6 V6 agentic core is disabled")
        self._path = Path(path)
        if not self._path.is_absolute() or self._path.name in {"", ".", ".."}:
            raise AgenticCoreV6ContractError(
                "an explicit absolute sidecar path is required"
            )
        if (
            isinstance(fence_seconds, bool)
            or not isinstance(fence_seconds, (int, float))
            or not math.isfinite(fence_seconds)
            or not 0.05 <= fence_seconds <= 300.0
        ):
            raise AgenticCoreV6ContractError(
                "materialization fence duration is invalid"
            )
        self._fence_seconds = float(fence_seconds)
        self._coord_path = self._path.with_name(
            f"{self._path.stem}.v6-coordination{self._path.suffix or '.sqlite3'}"
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
            return _schema_signature_v6(connection)
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
                signature = _schema_signature_v6(connection)
                metadata = connection.execute(
                    "SELECT schema_version FROM metadata"
                ).fetchall()
                if (
                    signature != self._expected_signature
                    or int(connection.execute("PRAGMA user_version").fetchone()[0])
                    != SCHEMA_VERSION
                    or [tuple(row) for row in metadata] != [(SCHEMA_VERSION,)]
                    or connection.execute("PRAGMA integrity_check").fetchone()[0]
                    != "ok"
                    or connection.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise AgenticCoreV6Error(
                        "Phase 6 V6 coordination schema authentication failed"
                    )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()


class StrictMissionMaterializerV6(StrictMissionMaterializerV5):
    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        expected = sqlite3.connect(":memory:")
        try:
            expected.execute(self._DDL)
            expected_signature = _schema_signature_v6(expected)
        finally:
            expected.close()
        connection = self._connect()
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
            if count == 0:
                connection.execute(self._DDL)
                connection.commit()
            if _schema_signature_v6(connection) != expected_signature:
                raise AgenticCoreV6Error(
                    "V6 exact-input ledger schema authentication failed"
                )
        finally:
            connection.close()


class AgenticCoreV6(AgenticCoreV5):
    def __init__(
        self,
        state_store: AgenticStateStoreV6,
        mission_store: MissionStore,
        workspace_scope: WorkspaceScopeV1,
        *,
        executor: TerminableProcessExecutorV4 | None = None,
    ) -> None:
        if (
            type(state_store) is not AgenticStateStoreV6
            or type(mission_store) is not MissionStore
            or type(workspace_scope) is not WorkspaceScopeV1
        ):
            raise AgenticCoreV6ContractError(
                "exact V6 state, MissionStore and workspace scope are required"
            )
        self._state = state_store
        self._missions = mission_store
        self._workspace = workspace_scope
        self._executor = executor or TerminableProcessExecutorV4()
        self._materializer = StrictMissionMaterializerV6(mission_store)
        self._closed = False


def create_phase6_agentic_core_v6(
    *,
    gate: AgenticFeatureGateV6,
    sidecar_path: Path | str,
    mission_store: MissionStore,
    workspace_scope: WorkspaceScopeV1,
    fence_seconds: float = DEFAULT_FENCE_SECONDS,
) -> AgenticCoreV6:
    state = AgenticStateStoreV6(sidecar_path, gate, fence_seconds=fence_seconds)
    return AgenticCoreV6(state, mission_store, workspace_scope)


artifact_root_v6 = artifact_root_v2
