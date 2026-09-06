"""Default-off, inert Phase 4 M1a control-plane sidecar.

This module owns only the empty, versioned SQLite schema and migration journal.
It is deliberately not imported by the application startup path.  Workspaces,
legacy adapters, backfills, grants, connectors, and runtime projections belong
to later reviewed migrations.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import sqlite3
import stat
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.paths import (
    PrivateDataPathError,
    private_control_plane_runtime_dir,
    windows_local_app_data_dir,
)


CONTROL_PLANE_FLAG = "ONYX_CONTROL_PLANE_V1"
SCHEMA_ID = "onyx-control-plane"
M1A_SCHEMA_VERSION = 1
SCHEMA_VERSION = 2
APPLICATION_ID = 0x4F4E5958
MIGRATION_ID = "m1a-inert-schema-v1"
M1B_MIGRATION_ID = "m1b-legacy-backfill-ledger-v2"


class ControlPlaneError(RuntimeError):
    """Base error for the inert control-plane sidecar."""


class ControlPlaneDisabled(ControlPlaneError):
    """Raised when M1a is used without an explicit opt-in."""


class ControlPlaneSchemaError(ControlPlaneError):
    """Raised for corrupt, foreign, or unsupported sidecar schemas."""


class ControlPlaneCorruptionError(ControlPlaneSchemaError):
    """Raised when SQLite reports physical or relational corruption."""


class ControlPlanePathError(ControlPlaneError):
    """Raised when the fixed sidecar path cannot be used safely."""


class ControlPlaneIOError(ControlPlaneError):
    """Raised for sidecar connection and lifecycle I/O failures."""


class ControlPlaneLockError(ControlPlanePathError):
    """Raised when the cross-process initialization lock fails."""


class ControlPlaneLockTimeout(ControlPlaneLockError):
    """Raised when another initializer holds the lock too long."""


class ControlPlaneLockAbandoned(ControlPlaneLockError):
    """Raised when a Windows lock owner exited without releasing it."""


DOMAIN_TABLES = (
    "action_receipts",
    "action_requests",
    "artifact_index",
    "autonomy_envelopes",
    "capability_descriptors",
    "claims",
    "event_envelopes",
    "evidence_records",
    "grants",
    "memory_metadata",
    "mission_contexts",
    "projections",
    "workspaces",
    "legacy_backfill_candidates",
    "backfill_runs",
)
M1A_DOMAIN_TABLES = DOMAIN_TABLES[:-2]

M1A_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE schema_metadata(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE migration_journal(
        migration_id TEXT PRIMARY KEY,
        schema_from INTEGER NOT NULL,
        schema_to INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('applied')),
        applied_at TEXT NOT NULL,
        schema_fingerprint TEXT NOT NULL CHECK(length(schema_fingerprint)=64)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE workspaces(
        workspace_id TEXT PRIMARY KEY,
        schema_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE mission_contexts(
        mission_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        operational_phase TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE capability_descriptors(
        capability_id TEXT PRIMARY KEY,
        workspace_id TEXT,
        schema_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE grants(
        grant_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE autonomy_envelopes(
        envelope_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        schema_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE evidence_records(
        evidence_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        schema_version INTEGER NOT NULL,
        content_sha256 TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE claims(
        claim_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        verification_status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE action_requests(
        request_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        schema_version INTEGER NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE action_receipts(
        receipt_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        outcome TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(request_id) REFERENCES action_requests(request_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE memory_metadata(
        memory_metadata_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        source_memory_id TEXT,
        schema_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE projections(
        projection_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        projection_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE event_envelopes(
        event_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        correlation_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        previous_hash TEXT NOT NULL,
        event_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE artifact_index(
        artifact_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        media_type TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(workspace_id, sha256),
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX idx_mission_contexts_workspace ON mission_contexts(workspace_id)",
    "CREATE INDEX idx_capabilities_workspace_status ON capability_descriptors(workspace_id,status)",
    "CREATE INDEX idx_grants_workspace_status_expiry ON grants(workspace_id,status,expires_at)",
    "CREATE INDEX idx_envelopes_workspace_mission ON autonomy_envelopes(workspace_id,mission_id)",
    "CREATE INDEX idx_evidence_workspace_mission ON evidence_records(workspace_id,mission_id)",
    "CREATE INDEX idx_claims_workspace_status ON claims(workspace_id,verification_status)",
    "CREATE INDEX idx_action_requests_workspace_mission ON action_requests(workspace_id,mission_id)",
    "CREATE INDEX idx_action_receipts_request ON action_receipts(request_id)",
    "CREATE INDEX idx_memory_metadata_workspace_source ON memory_metadata(workspace_id,source_memory_id)",
    "CREATE INDEX idx_projections_workspace_type ON projections(workspace_id,projection_type)",
    "CREATE INDEX idx_events_workspace_correlation ON event_envelopes(workspace_id,correlation_id)",
    "CREATE INDEX idx_artifacts_workspace_status ON artifact_index(workspace_id,status)",
)

M1B_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE legacy_backfill_candidates(
        candidate_id TEXT PRIMARY KEY,
        source_kind TEXT NOT NULL CHECK(source_kind IN ('mission','memory')),
        source_identity TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_schema_version INTEGER NOT NULL,
        logical_hash TEXT NOT NULL CHECK(length(logical_hash)=64),
        run_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending_review','assigned','rejected')),
        reason TEXT NOT NULL,
        workspace_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(source_kind,source_identity,source_id),
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
        FOREIGN KEY(run_id) REFERENCES backfill_runs(run_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE backfill_runs(
        run_id TEXT PRIMARY KEY,
        schema_version INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('started','applied_unverified','verified','failed')),
        mission_source_identity TEXT NOT NULL,
        mission_source_hash TEXT NOT NULL CHECK(length(mission_source_hash)=64),
        memory_source_identity TEXT NOT NULL,
        memory_source_hash TEXT NOT NULL CHECK(length(memory_source_hash)=64),
        started_at TEXT NOT NULL,
        completed_at TEXT,
        readback_hash TEXT CHECK(readback_hash IS NULL OR length(readback_hash)=64),
        payload_json TEXT NOT NULL,
        lease_owner TEXT NOT NULL,
        lease_expires_at TEXT NOT NULL,
        heartbeat_at TEXT NOT NULL,
        lease_epoch INTEGER NOT NULL CHECK(lease_epoch >= 1)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX idx_legacy_candidates_status ON legacy_backfill_candidates(status,source_kind)",
    "CREATE INDEX idx_legacy_candidates_workspace ON legacy_backfill_candidates(workspace_id,status)",
    "CREATE UNIQUE INDEX idx_memory_metadata_workspace_source_unique "
    "ON memory_metadata(workspace_id,source_memory_id) WHERE source_memory_id IS NOT NULL",
)

EXPECTED_TABLES = frozenset((*DOMAIN_TABLES, "migration_journal", "schema_metadata"))
EXPECTED_INDEXES = frozenset(
    {
        "idx_action_receipts_request",
        "idx_action_requests_workspace_mission",
        "idx_artifacts_workspace_status",
        "idx_capabilities_workspace_status",
        "idx_claims_workspace_status",
        "idx_envelopes_workspace_mission",
        "idx_events_workspace_correlation",
        "idx_evidence_workspace_mission",
        "idx_grants_workspace_status_expiry",
        "idx_memory_metadata_workspace_source",
        "idx_mission_contexts_workspace",
        "idx_projections_workspace_type",
        "idx_legacy_candidates_status",
        "idx_legacy_candidates_workspace",
        "idx_memory_metadata_workspace_source_unique",
    }
)


_CONTROL_PLANE_LOCK = threading.RLock()
_METADATA_KEYS = frozenset({"schema_id", "schema_version", "schema_fingerprint", "created_at"})


def control_plane_v1_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return true only for an explicit recognized opt-in value."""
    source = os.environ if environ is None else environ
    return source.get(CONTROL_PLANE_FLAG, "").strip().casefold() in {"1", "true"}


def control_plane_path() -> Path:
    """Return the only production sidecar path, under the canonical runtime root."""
    return private_control_plane_runtime_dir() / "control_plane.sqlite3"


def _quote_pragma_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


_SQL_NUMBER = re.compile(
    r"(?:0[xX][0-9a-fA-F]+|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)"
)
_SQL_OPERATORS = ("->>", "!=", "<=", ">=", "==", "<>", "||", "->")


def _canonical_sql_tokens(sql: str) -> tuple[tuple[str, str], ...]:
    """Tokenize reviewed SQLite DDL while discarding comments and formatting."""
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(sql):
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                raise ControlPlaneSchemaError("unterminated SQL block comment in schema")
            index = end + 2
            continue
        if character in {"'", '"', "`"}:
            quote = character
            kind = "STRING" if quote == "'" else "IDENT"
            value: list[str] = []
            index += 1
            while index < len(sql):
                if sql[index] == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        value.append(quote)
                        index += 2
                        continue
                    index += 1
                    break
                value.append(sql[index])
                index += 1
            else:
                raise ControlPlaneSchemaError("unterminated quoted SQL token in schema")
            normalized = "".join(value)
            tokens.append((kind, normalized if kind == "STRING" else normalized.casefold()))
            continue
        if character == "[":
            end = sql.find("]", index + 1)
            if end < 0:
                raise ControlPlaneSchemaError("unterminated bracketed SQL identifier")
            tokens.append(("IDENT", sql[index + 1 : end].casefold()))
            index = end + 1
            continue
        if character.isalpha() or character in {"_", "$"}:
            end = index + 1
            while end < len(sql) and (sql[end].isalnum() or sql[end] in {"_", "$"}):
                end += 1
            tokens.append(("WORD", sql[index:end].casefold()))
            index = end
            continue
        number = _SQL_NUMBER.match(sql, index)
        if number is not None:
            tokens.append(("NUMBER", number.group(0).casefold()))
            index = number.end()
            continue
        operator = next(
            (candidate for candidate in _SQL_OPERATORS if sql.startswith(candidate, index)),
            None,
        )
        if operator is not None:
            tokens.append(("SYMBOL", operator))
            index += len(operator)
            continue
        tokens.append(("SYMBOL", character))
        index += 1
    return tuple(tokens)


def _canonical_check_expressions(sql: str) -> tuple[tuple[tuple[str, str], ...], ...]:
    tokens = _canonical_sql_tokens(sql)
    checks: list[tuple[tuple[str, str], ...]] = []
    index = 0
    while index < len(tokens):
        if tokens[index] != ("WORD", "check"):
            index += 1
            continue
        if index + 1 >= len(tokens) or tokens[index + 1] != ("SYMBOL", "("):
            raise ControlPlaneSchemaError("CHECK clause is missing its expression")
        depth = 1
        cursor = index + 2
        expression: list[tuple[str, str]] = []
        while cursor < len(tokens) and depth:
            token = tokens[cursor]
            if token == ("SYMBOL", "("):
                depth += 1
            elif token == ("SYMBOL", ")"):
                depth -= 1
                if depth == 0:
                    break
            expression.append(token)
            cursor += 1
        if depth:
            raise ControlPlaneSchemaError("unterminated CHECK expression in schema")
        checks.append(tuple(expression))
        index = cursor + 1
    return tuple(checks)


def _canonical_check_manifest(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, tuple[tuple[tuple[str, str], ...], ...]], ...]:
    return tuple(
        (name, _canonical_check_expressions(sql or ""))
        for name, sql in connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    )


def _check_contract(connection: sqlite3.Connection) -> tuple[tuple[str, bool], ...]:
    """Probe every M1 CHECK constraint without leaving durable rows."""
    probes = (
        (
            "migration_journal.status.rejects_invalid",
            "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
            ("__check_status__", 0, 1, "invalid", "2000-01-01T00:00:00+00:00", "0" * 64),
            False,
        ),
        (
            "migration_journal.status.accepts_applied",
            "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
            ("__accept_status__", 0, 1, "applied", "2000-01-01T00:00:00+00:00", "0" * 64),
            True,
        ),
        (
            "migration_journal.schema_fingerprint_length.rejects_short",
            "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
            ("__check_fingerprint__", 0, 1, "applied", "2000-01-01T00:00:00+00:00", "short"),
            False,
        ),
        (
            "migration_journal.schema_fingerprint_length.accepts_64",
            "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
            ("__accept_fingerprint__", 0, 1, "applied", "2000-01-01T00:00:00+00:00", "f" * 64),
            True,
        ),
    )
    results: list[tuple[str, bool]] = []
    for index, (name, sql, parameters, expected_acceptance) in enumerate(probes):
        savepoint = f"m1_check_{index}"
        connection.execute(f"SAVEPOINT {savepoint}")
        accepted = True
        try:
            try:
                connection.execute(sql, parameters)
            except sqlite3.IntegrityError:
                accepted = False
        finally:
            connection.execute(f"ROLLBACK TO {savepoint}")
            connection.execute(f"RELEASE {savepoint}")
        results.append((name, accepted is expected_acceptance))
    return tuple(results)


def _schema_manifest(
    connection: sqlite3.Connection, *, include_behavior: bool = True
) -> dict[str, object]:
    """Return a SQLite-version-stable semantic schema description.

    SQLite documents table_xinfo, foreign_key_list, index_list and index_xinfo
    as its schema-introspection interfaces: https://www.sqlite.org/pragma.html
    """
    objects = tuple(
        tuple(row)
        for row in connection.execute(
            "SELECT type,name,tbl_name FROM sqlite_master "
            "WHERE type IN ('table','index','view','trigger') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY type,name,tbl_name"
        ).fetchall()
    )
    tables: list[tuple[object, ...]] = []
    for table_name in sorted(row[1] for row in objects if row[0] == "table"):
        quoted_table = _quote_pragma_identifier(table_name)
        columns = tuple(
            tuple(row)
            for row in connection.execute(f"PRAGMA table_xinfo({quoted_table})").fetchall()
        )
        table_list = connection.execute(f"PRAGMA table_list({quoted_table})").fetchall()
        table_flags = (
            (int(table_list[0][4]), int(table_list[0][5])) if table_list else (None, None)
        )
        foreign_keys = tuple(
            sorted(
                tuple(row)
                for row in connection.execute(
                    f"PRAGMA foreign_key_list({quoted_table})"
                ).fetchall()
            )
        )
        indexes: list[tuple[object, ...]] = []
        for _seq, index_name, unique, origin, partial in connection.execute(
            f"PRAGMA index_list({quoted_table})"
        ).fetchall():
            quoted_index = _quote_pragma_identifier(index_name)
            index_columns = tuple(
                (row[1], row[2], row[3], row[4])
                for row in connection.execute(
                    f"PRAGMA index_xinfo({quoted_index})"
                ).fetchall()
                if row[5]
            )
            stable_name = index_name if origin == "c" else None
            indexes.append((stable_name, unique, origin, partial, index_columns))
        tables.append(
            (
                table_name,
                columns,
                table_flags,
                foreign_keys,
                tuple(sorted(indexes, key=lambda row: (str(row[0]), row[2], row[4]))),
            )
        )
    table_names = {row[1] for row in objects if row[0] == "table"}
    checks = (
        _check_contract(connection)
        if include_behavior and "migration_journal" in table_names
        else ()
    )
    return {
        "manifest_version": 2,
        "objects": objects,
        "tables": tuple(tables),
        "check_expressions": _canonical_check_manifest(connection),
        "checks": checks,
    }


def _reference_manifest(
    *, include_behavior: bool = True, version: int = SCHEMA_VERSION
) -> dict[str, object]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in M1A_SCHEMA_STATEMENTS:
            connection.execute(statement)
        if version == SCHEMA_VERSION:
            for statement in M1B_SCHEMA_STATEMENTS:
                connection.execute(statement)
        elif version != M1A_SCHEMA_VERSION:
            raise ControlPlaneSchemaError(f"unsupported reference schema version {version}")
        return _schema_manifest(connection, include_behavior=include_behavior)
    finally:
        connection.close()


def _schema_fingerprint(manifest: dict[str, object] | None = None) -> str:
    canonical = json.dumps(
        _reference_manifest() if manifest is None else manifest,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except FileNotFoundError:
        return False
    except AttributeError:
        return False
    except OSError as exc:
        raise ControlPlanePathError(f"could not inspect control-plane path {path}: {exc}") from exc


def _reject_link_chain(path: Path) -> None:
    current = path
    while True:
        try:
            linked = current.is_symlink()
        except OSError as exc:
            raise ControlPlanePathError(f"could not inspect control-plane path {current}: {exc}") from exc
        if linked or _is_reparse(current):
            raise ControlPlanePathError(
                f"linked/reparse control-plane path is not allowed: {current}"
            )
        if current.parent == current:
            return
        current = current.parent


def _identity_from_stat(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _path_identity(path: Path) -> tuple[int, int]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ControlPlanePathError(f"could not inspect control-plane file {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(path) or not stat.S_ISREG(info.st_mode):
        raise ControlPlanePathError("control-plane database must be a regular non-linked file")
    return _identity_from_stat(info)


def _directory_identity(path: Path) -> tuple[int, int]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ControlPlanePathError(f"could not inspect private runtime directory: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(path) or not stat.S_ISDIR(info.st_mode):
        raise ControlPlanePathError("control-plane runtime must be a regular non-linked directory")
    return _identity_from_stat(info)


def _assert_directory_identity(path: Path, expected: tuple[int, int]) -> None:
    _reject_link_chain(path)
    if _directory_identity(path) != expected:
        raise ControlPlanePathError("control-plane runtime directory identity changed")


def _assert_path_identity(path: Path, expected: tuple[int, int]) -> None:
    _reject_link_chain(path)
    if _path_identity(path) != expected:
        raise ControlPlanePathError("control-plane file identity changed during initialization")


def _assert_connection_target(connection: sqlite3.Connection, expected: Path) -> None:
    try:
        rows = connection.execute("PRAGMA database_list").fetchall()
    except sqlite3.DatabaseError as exc:
        raise ControlPlaneIOError(f"could not identify opened SQLite database: {exc}") from exc
    main = [row[2] for row in rows if row[1] == "main"]
    if len(main) != 1 or Path(os.path.abspath(main[0])) != expected:
        raise ControlPlanePathError("SQLite opened an unexpected control-plane file")


_SID_PATTERN = re.compile(r"^S-\d+(?:-\d+)+$")
_SYSTEM_SID = "S-1-5-18"
_BUILTIN_ADMINISTRATORS_SID = "S-1-5-32-544"
_SE_GROUP_ENABLED = 0x00000004
_SE_GROUP_USE_FOR_DENY_ONLY = 0x00000010
_SDDL_ALIAS_SIDS = {
    "AC": "S-1-15-2-1",
    "AO": "S-1-5-32-548",
    "AU": "S-1-5-11",
    "BA": _BUILTIN_ADMINISTRATORS_SID,
    "BG": "S-1-5-32-546",
    "BO": "S-1-5-32-551",
    "BU": "S-1-5-32-545",
    "CO": "S-1-3-0",
    "OW": "S-1-3-4",
    "RC": "S-1-5-12",
    "SY": _SYSTEM_SID,
    "WD": "S-1-1-0",
}


def _current_windows_sid() -> str:
    """Resolve the process-token user SID without spawning a helper process."""

    if os.name != "nt":
        raise ControlPlanePathError("Windows SID verification is unavailable")
    from ctypes import wintypes

    token_query = 0x0008
    token_user_class = 1
    error_insufficient_buffer = 122

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = (("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD))

    class _TokenUser(ctypes.Structure):
        _fields_ = (("User", _SidAndAttributes),)

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = ()
    get_current_process.restype = wintypes.HANDLE
    open_process_token = advapi32.OpenProcessToken
    open_process_token.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    open_process_token.restype = wintypes.BOOL
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    get_token_information.restype = wintypes.BOOL
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    convert_sid.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p

    token = wintypes.HANDLE()
    if not open_process_token(
        get_current_process(), token_query, ctypes.byref(token)
    ):
        raise ControlPlanePathError(
            "could not open current Windows token: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    try:
        required = wintypes.DWORD()
        if get_token_information(
            token,
            token_user_class,
            None,
            0,
            ctypes.byref(required),
        ):
            raise ControlPlanePathError(
                "Windows token user query returned an invalid size probe"
            )
        if (
            ctypes.get_last_error() != error_insufficient_buffer
            or required.value < ctypes.sizeof(_TokenUser)
        ):
            raise ControlPlanePathError(
                "could not size Windows token user data: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        buffer = ctypes.create_string_buffer(required.value)
        if not get_token_information(
            token,
            token_user_class,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise ControlPlanePathError(
                "could not read Windows token user data: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        sid_text = wintypes.LPWSTR()
        if not convert_sid(token_user.User.Sid, ctypes.byref(sid_text)):
            raise ControlPlanePathError(
                "could not convert Windows token user SID: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        try:
            sid = sid_text.value or ""
            if not _SID_PATTERN.fullmatch(sid):
                raise ControlPlanePathError(
                    "Windows token returned an invalid current-user SID"
                )
            return sid
        finally:
            if sid_text:
                local_free(sid_text)
    finally:
        if token and not close_handle(token):
            raise ControlPlanePathError(
                "could not close current Windows token: "
                f"Win32 error {ctypes.get_last_error()}"
            )


def _windows_owner_sid(path: Path) -> str:
    """Read a file owner with GetNamedSecurityInfoW and free native buffers."""
    if os.name != "nt":
        raise ControlPlanePathError("Windows owner verification is unavailable")
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_security = advapi32.GetNamedSecurityInfoW
    get_security.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_security.restype = wintypes.DWORD
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    convert_sid.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    owner = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = get_security(
        os.fspath(path), 1, 0x00000001, ctypes.byref(owner), None, None, None,
        ctypes.byref(descriptor),
    )
    if result != 0 or not owner.value or not descriptor.value:
        raise ControlPlanePathError(f"could not read Windows owner SID: Win32 error {result}")
    sid_text = wintypes.LPWSTR()
    try:
        if not convert_sid(owner, ctypes.byref(sid_text)):
            raise ControlPlanePathError(
                f"could not convert Windows owner SID: Win32 error {ctypes.get_last_error()}"
            )
        value = sid_text.value or ""
        if not _SID_PATTERN.fullmatch(value):
            raise ControlPlanePathError("Windows owner query returned an invalid SID")
        return value
    finally:
        if sid_text:
            local_free(sid_text)
        local_free(descriptor)


def _windows_token_capability_sids() -> frozenset[str]:
    """Return enabled capability SIDs carried by the current process token."""
    if os.name != "nt":
        raise ControlPlanePathError("Windows token capability inspection is unavailable")
    from ctypes import wintypes

    token_query = 0x0008
    token_capabilities = 30
    error_insufficient_buffer = 122

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = (("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD))

    class _TokenGroups(ctypes.Structure):
        _fields_ = (
            ("GroupCount", wintypes.DWORD),
            ("Groups", _SidAndAttributes * 1),
        )

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = ()
    get_current_process.restype = wintypes.HANDLE
    open_process_token = advapi32.OpenProcessToken
    open_process_token.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    open_process_token.restype = wintypes.BOOL
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    get_token_information.restype = wintypes.BOOL
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    convert_sid.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p

    token = wintypes.HANDLE()
    if not open_process_token(get_current_process(), token_query, ctypes.byref(token)):
        raise ControlPlanePathError(
            f"could not open current Windows token: Win32 error {ctypes.get_last_error()}"
        )
    try:
        required = wintypes.DWORD()
        if get_token_information(
            token, token_capabilities, None, 0, ctypes.byref(required)
        ):
            raise ControlPlanePathError("Windows capability query returned an invalid size probe")
        if ctypes.get_last_error() != error_insufficient_buffer or required.value == 0:
            raise ControlPlanePathError(
                f"could not size Windows capability token data: Win32 error {ctypes.get_last_error()}"
            )
        buffer = ctypes.create_string_buffer(required.value)
        if not get_token_information(
            token,
            token_capabilities,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise ControlPlanePathError(
                f"could not read Windows capability token data: Win32 error {ctypes.get_last_error()}"
            )
        header = ctypes.cast(buffer, ctypes.POINTER(_TokenGroups)).contents
        group_count = int(header.GroupCount)
        minimum_size = _TokenGroups.Groups.offset + group_count * ctypes.sizeof(
            _SidAndAttributes
        )
        if group_count > 4096 or minimum_size > len(buffer):
            raise ControlPlanePathError("Windows capability token data is malformed")
        groups = ctypes.cast(
            ctypes.addressof(buffer) + _TokenGroups.Groups.offset,
            ctypes.POINTER(_SidAndAttributes * group_count),
        ).contents
        capabilities: set[str] = set()
        for group in groups:
            attributes = int(group.Attributes)
            sid_text = wintypes.LPWSTR()
            try:
                if not convert_sid(group.Sid, ctypes.byref(sid_text)):
                    raise ControlPlanePathError(
                        f"could not convert Windows capability SID: Win32 error {ctypes.get_last_error()}"
                    )
                sid = sid_text.value or ""
                if not _SID_PATTERN.fullmatch(sid):
                    raise ControlPlanePathError(
                        "Windows capability query returned an invalid SID"
                    )
                if _windows_capability_sid_is_enabled(sid, attributes):
                    capabilities.add(sid)
            finally:
                if sid_text:
                    local_free(sid_text)
        return frozenset(capabilities)
    finally:
        close_handle(token)


def _windows_capability_sid_is_enabled(sid: str, attributes: int) -> bool:
    """Return whether an exact capability SID is an effective allow principal."""
    return (
        bool(_SID_PATTERN.fullmatch(sid))
        and sid.startswith("S-1-15-3-")
        and bool(attributes & _SE_GROUP_ENABLED)
        and not bool(attributes & _SE_GROUP_USE_FOR_DENY_ONLY)
    )


def _canonical_windows_profile_owner_sid() -> str:
    try:
        canonical = windows_local_app_data_dir()
    except PrivateDataPathError as exc:
        raise ControlPlanePathError(
            f"could not resolve canonical Windows private-data root: {exc}"
        ) from exc
    return _windows_owner_sid(canonical)


def _save_windows_security_sddl(path: Path) -> str:
    """Read owner plus DACL as canonical SDDL without a helper process."""
    if os.name != "nt":
        raise ControlPlanePathError("Windows security verification is unavailable")
    from ctypes import wintypes

    owner_security_information = 0x00000001
    dacl_security_information = 0x00000004
    security_information = owner_security_information | dacl_security_information
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_security = advapi32.GetNamedSecurityInfoW
    get_security.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_security.restype = wintypes.DWORD
    convert_descriptor = (
        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    )
    convert_descriptor.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert_descriptor.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = get_security(
        os.fspath(path),
        1,
        security_information,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0 or not owner.value or not descriptor.value:
        raise ControlPlanePathError(
            f"could not read Windows security descriptor: Win32 error {result}"
        )
    text = wintypes.LPWSTR()
    try:
        if not convert_descriptor(
            descriptor,
            1,
            security_information,
            ctypes.byref(text),
            None,
        ):
            raise ControlPlanePathError(
                "could not convert Windows security descriptor to SDDL: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        value = text.value or ""
        owner_prefix = value[2 : value.find("D:")]
        if (
            not value.startswith("O:")
            or "D:" not in value
            or not (
                _SID_PATTERN.fullmatch(owner_prefix)
                or owner_prefix in _SDDL_ALIAS_SIDS
            )
        ):
            raise ControlPlanePathError(
                "Windows security conversion returned invalid SDDL"
            )
        return value
    finally:
        if text:
            local_free(text)
        local_free(descriptor)


def _save_windows_dacl(path: Path) -> str:
    """Read only the canonical DACL component used by existing verifiers."""

    value = _save_windows_security_sddl(path)
    return value[value.index("D:") :]


def _verify_windows_sddl(dacl: str, current_sid: str, *, is_directory: bool) -> None:
    if not _SID_PATTERN.fullmatch(current_sid):
        raise ControlPlanePathError("Windows sidecar owner SID is invalid")
    first_ace = dacl.find("(")
    control_flags = dacl[2:first_ace] if first_ace >= 0 else ""
    if not dacl.startswith("D:") or control_flags != "P":
        raise ControlPlanePathError(
            f"Windows sidecar DACL controls are not canonical: {dacl}"
        )
    ace_texts = re.findall(r"\(([^()]*)\)", dacl)
    expected_flags = "OICI" if is_directory else ""
    expected = [
        ["A", expected_flags, "FA", "", "", "SY"],
        ["A", expected_flags, "FA", "", "", current_sid],
    ]
    observed = [item.split(";") for item in ace_texts]
    if observed != expected or dacl != (
        "D:P" + "".join(f"({';'.join(item)})" for item in expected)
    ):
        raise ControlPlanePathError(
            "Windows sidecar DACL must contain canonical SYSTEM then owner ACEs"
        )


_WINDOWS_DANGEROUS_FILE_MASK = (
    0x00000002  # FILE_WRITE_DATA / FILE_ADD_FILE
    | 0x00000004  # FILE_APPEND_DATA / FILE_ADD_SUBDIRECTORY
    | 0x00000010  # FILE_WRITE_EA
    | 0x00000040  # FILE_DELETE_CHILD
    | 0x00000100  # FILE_WRITE_ATTRIBUTES
    | 0x00010000  # DELETE
    | 0x00040000  # WRITE_DAC
    | 0x00080000  # WRITE_OWNER
    | 0x10000000  # GENERIC_ALL
    | 0x40000000  # GENERIC_WRITE
)
_WINDOWS_SAFE_SYMBOLIC_RIGHTS = frozenset({"FR", "FX", "GR", "GX", "RC"})
_WINDOWS_DANGEROUS_SYMBOLIC_RIGHTS = frozenset(
    {"FA", "FW", "GA", "GW", "SD", "WD", "WO"}
)
_WINDOWS_DACL_CONTROL_FLAGS = frozenset({"P", "AR", "AI"})
_WINDOWS_ACE_TYPES = frozenset({"A", "D", "OA", "OD"})
_WINDOWS_ACE_FLAGS = frozenset({"CI", "OI", "NP", "IO", "ID", "SA", "FA", "TP", "CR"})
_WINDOWS_RIGHTS_TOKENS = frozenset(
    {
        "GA", "GR", "GW", "GX", "RC", "SD", "WD", "WO",
        "RP", "WP", "CC", "DC", "LC", "SW", "LO", "DT", "CR",
        "FA", "FR", "FW", "FX", "KA", "KR", "KW", "KX",
        "NR", "NW", "NX",
    }
)
_WINDOWS_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _split_sddl_tokens(value: str, allowed: frozenset[str], label: str) -> tuple[str, ...]:
    if not value:
        return ()
    tokens: list[str] = []
    cursor = 0
    ordered = sorted(allowed, key=lambda token: (-len(token), token))
    while cursor < len(value):
        token = next(
            (candidate for candidate in ordered if value.startswith(candidate, cursor)),
            None,
        )
        if token is None or token in tokens:
            raise ControlPlanePathError(f"invalid Windows SDDL {label}: {value}")
        tokens.append(token)
        cursor += len(token)
    return tuple(tokens)


def _validate_windows_sddl_rights(rights: str) -> None:
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", rights):
        return
    if not rights:
        raise ControlPlanePathError("Windows SDDL ACE rights are empty")
    _split_sddl_tokens(rights, _WINDOWS_RIGHTS_TOKENS, "rights")


def _parse_windows_dacl_sddl(dacl: str) -> tuple[tuple[str, ...], ...]:
    if not dacl.startswith("D:"):
        raise ControlPlanePathError("Windows ancestor SDDL is missing its DACL")
    payload = dacl[2:]
    if payload.startswith("NO_ACCESS_CONTROL"):
        raise ControlPlanePathError("Windows ancestor has a null DACL")
    ace_start = payload.find("(")
    controls = payload if ace_start < 0 else payload[:ace_start]
    _split_sddl_tokens(controls, _WINDOWS_DACL_CONTROL_FLAGS, "DACL controls")
    if ace_start < 0:
        raise ControlPlanePathError("Windows ancestor DACL is empty")
    cursor = ace_start
    aces: list[tuple[str, ...]] = []
    while cursor < len(payload):
        if payload[cursor] != "(":
            raise ControlPlanePathError("Windows ancestor SDDL contains trailing junk")
        close = payload.find(")", cursor + 1)
        if close < 0:
            raise ControlPlanePathError("Windows ancestor SDDL has an unbalanced ACE")
        ace = payload[cursor + 1 : close]
        if "(" in ace:
            raise ControlPlanePathError("Windows ancestor SDDL has a nested ACE")
        fields = tuple(ace.split(";"))
        if len(fields) != 6:
            raise ControlPlanePathError("Windows private-data ancestor has malformed DACL")
        ace_type, flags, rights, object_guid, inherit_guid, sid = fields
        if ace_type not in _WINDOWS_ACE_TYPES:
            raise ControlPlanePathError(f"unsupported Windows SDDL ACE type {ace_type}")
        _split_sddl_tokens(flags, _WINDOWS_ACE_FLAGS, "ACE flags")
        _validate_windows_sddl_rights(rights)
        is_object_ace = ace_type in {"OA", "OD"}
        if not is_object_ace and (object_guid or inherit_guid):
            raise ControlPlanePathError("non-object Windows ACE contains an object GUID")
        for guid in (object_guid, inherit_guid):
            if guid and not _WINDOWS_GUID.fullmatch(guid):
                raise ControlPlanePathError(f"invalid Windows SDDL object GUID {guid}")
        if not (_SID_PATTERN.fullmatch(sid) or sid in _SDDL_ALIAS_SIDS):
            raise ControlPlanePathError(f"unsupported Windows SDDL SID {sid}")
        aces.append(fields)
        cursor = close + 1
    return tuple(aces)


def _native_validate_windows_dacl(dacl: str) -> None:
    if os.name != "nt":
        return
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    get_dacl = advapi32.GetSecurityDescriptorDacl
    get_dacl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL),
    ]
    get_dacl.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    if not convert(dacl, 1, ctypes.byref(descriptor), None):
        raise ControlPlanePathError(
            f"Windows rejected ancestor SDDL: Win32 error {ctypes.get_last_error()}"
        )
    try:
        present = wintypes.BOOL()
        defaulted = wintypes.BOOL()
        native_dacl = ctypes.c_void_p()
        if not get_dacl(
            descriptor, ctypes.byref(present), ctypes.byref(native_dacl), ctypes.byref(defaulted)
        ):
            raise ControlPlanePathError(
                f"could not inspect native Windows DACL: Win32 error {ctypes.get_last_error()}"
            )
        if not present.value or not native_dacl.value:
            raise ControlPlanePathError("Windows ancestor has a missing or null native DACL")
    finally:
        local_free(descriptor)


def _windows_rights_grant_write(rights: str) -> bool:
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", rights):
        return bool(int(rights, 16) & _WINDOWS_DANGEROUS_FILE_MASK)
    if not rights or len(rights) % 2:
        raise ControlPlanePathError(f"unrecognized Windows ancestor rights: {rights}")
    tokens = {rights[index : index + 2] for index in range(0, len(rights), 2)}
    if tokens & _WINDOWS_DANGEROUS_SYMBOLIC_RIGHTS:
        return True
    unknown = tokens - _WINDOWS_SAFE_SYMBOLIC_RIGHTS
    if unknown:
        raise ControlPlanePathError(
            f"unrecognized Windows ancestor rights: {','.join(sorted(unknown))}"
        )
    return False


def _verify_windows_ancestor_sddl(
    dacl: str,
    owner_sid: str,
    current_sid: str,
    *,
    profile_owner_sid: str | None = None,
    capability_sids: frozenset[str] = frozenset(),
) -> None:
    aces = _parse_windows_dacl_sddl(dacl)
    _native_validate_windows_dacl(dacl)
    trusted = {current_sid, _SYSTEM_SID, _BUILTIN_ADMINISTRATORS_SID}
    if profile_owner_sid is not None:
        if not _SID_PATTERN.fullmatch(profile_owner_sid):
            raise ControlPlanePathError("canonical Windows profile owner SID is invalid")
        trusted.add(profile_owner_sid)
    if owner_sid not in trusted:
        raise ControlPlanePathError(
            f"Windows private-data ancestor has untrusted owner {owner_sid}"
        )
    for fields in aces:
        ace_type, _flags, rights, _object_guid, _inherit_guid, sid = fields
        if ace_type in {"D", "OD"}:
            continue
        normalized = _SDDL_ALIAS_SIDS.get(sid, sid)
        if normalized in trusted:
            continue
        if _windows_rights_grant_write(rights):
            if normalized.startswith("S-1-15-3-") and normalized in capability_sids:
                continue
            raise ControlPlanePathError(
                f"Windows private-data ancestor grants write/delete rights to untrusted SID {sid}"
            )


def _verify_windows_private_ancestor(path: Path) -> None:
    current_sid = _current_windows_sid()
    owner_sid = _windows_owner_sid(path)
    dacl = re.sub(r";;;OW\)", f";;;{owner_sid})", _save_windows_dacl(path))
    _verify_windows_ancestor_sddl(
        dacl,
        owner_sid,
        current_sid,
        profile_owner_sid=_canonical_windows_profile_owner_sid(),
        capability_sids=_windows_token_capability_sids(),
    )


def _apply_windows_security_sddl(path: Path, sddl: str) -> None:
    """Apply one owner+DACL descriptor using native Win32 authority only."""
    if os.name != "nt" or type(sddl) is not str:
        raise ControlPlanePathError("Windows security application is unavailable")
    from ctypes import wintypes

    owner_security_information = 0x00000001
    dacl_security_information = 0x00000004
    dacl_index = sddl.find("D:")
    first_ace = sddl.find("(", dacl_index)
    owner_prefix = sddl[2:dacl_index] if dacl_index >= 0 else ""
    if (
        not sddl.startswith("O:")
        or dacl_index < 0
        or first_ace < 0
        or not (
            _SID_PATTERN.fullmatch(owner_prefix)
            or owner_prefix in _SDDL_ALIAS_SIDS
        )
    ):
        raise ControlPlanePathError("Windows security SDDL is invalid")
    security_information = owner_security_information | dacl_security_information
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    convert_descriptor = (
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    )
    convert_descriptor.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert_descriptor.restype = wintypes.BOOL
    set_security = advapi32.SetFileSecurityW
    set_security.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    set_security.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    if not convert_descriptor(sddl, 1, ctypes.byref(descriptor), None):
        raise ControlPlanePathError(
            "could not build Windows security descriptor: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    try:
        if not set_security(os.fspath(path), security_information, descriptor):
            raise ControlPlanePathError(
                "could not apply Windows security descriptor: "
                f"Win32 error {ctypes.get_last_error()}"
            )
    finally:
        local_free(descriptor)


def _secure_windows_acl(
    path: Path,
    *,
    is_directory: bool,
    failpoint: str | None = None,
) -> None:
    """Transactionally apply and verify the canonical owner/SYSTEM DACL."""
    if os.name != "nt":
        return
    if failpoint not in {None, "after_apply", "after_readback", "before_verify"}:
        raise ValueError("Windows ACL failpoint is invalid")
    current_sid = _current_windows_sid()
    ace_flags = "OICI" if is_directory else ""
    desired = (
        f"O:{current_sid}D:P"
        f"(A;{ace_flags};FA;;;SY)"
        f"(A;{ace_flags};FA;;;{current_sid})"
    )
    original = _save_windows_security_sddl(path)
    try:
        _apply_windows_security_sddl(path, desired)
        if failpoint == "after_apply":
            raise ControlPlanePathError("injected Windows ACL failure after apply")
        observed = _save_windows_security_sddl(path)
        if failpoint == "after_readback":
            raise ControlPlanePathError("injected Windows ACL failure after readback")
        if failpoint == "before_verify":
            raise ControlPlanePathError("injected Windows ACL failure before verify")
        _verify_windows_sddl(
            observed[observed.index("D:") :],
            current_sid,
            is_directory=is_directory,
        )
        if not observed.startswith(f"O:{current_sid}D:"):
            raise ControlPlanePathError(
                "Windows sidecar owner changed during ACL application"
            )
    except BaseException as primary:
        try:
            _apply_windows_security_sddl(path, original)
            restored = _save_windows_security_sddl(path)
            if restored != original:
                raise ControlPlanePathError(
                    "Windows ACL rollback descriptor verification failed"
                )
        except BaseException as rollback:
            compound = ControlPlanePathError(
                "Windows ACL mutation failed and exact rollback failed"
            )
            compound.add_note(
                f"mutation_error={type(primary).__name__}; "
                f"rollback_error={type(rollback).__name__}"
            )
            raise compound from rollback
        raise


def _verify_existing_windows_private_directory(path: Path) -> None:
    """Prove one existing managed directory is already an owner-only boundary.

    Windows hosts may grant sandbox capabilities access to ``LOCALAPPDATA``
    itself.  A protected, canonical Onyx vendor directory cuts off that
    inheritance, so the broad ancestor no longer describes access to the
    control-plane subtree.  This verifier is deliberately read-only: a linked,
    foreign-owned or non-canonical directory cannot become the trust anchor by
    being repaired after the fact.
    """

    if os.name != "nt":
        raise ControlPlanePathError("Windows private-directory verification is unavailable")
    _reject_link_chain(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise ControlPlanePathError(
            f"could not inspect existing Onyx private directory: {exc}"
        ) from exc
    if not stat.S_ISDIR(info.st_mode) or _is_reparse(path):
        raise ControlPlanePathError(
            "existing Onyx private boundary must be a regular non-linked directory"
        )
    current_sid = _current_windows_sid()
    owner_sid = _windows_owner_sid(path)
    if owner_sid != current_sid:
        raise ControlPlanePathError(
            "existing Onyx private boundary is not owned by the current user"
        )
    descriptor = _save_windows_security_sddl(path)
    dacl_index = descriptor.find("D:")
    if dacl_index < 0 or not descriptor.startswith(f"O:{current_sid}D:"):
        raise ControlPlanePathError(
            "existing Onyx private boundary has a non-canonical owner descriptor"
        )
    _verify_windows_sddl(
        descriptor[dacl_index:],
        current_sid,
        is_directory=True,
    )


def _managed_private_directories(path: Path) -> tuple[Path, ...]:
    runtime = path.parent
    app = runtime.parent
    vendor = app.parent
    if (
        runtime.name == "runtime"
        and app.name.casefold() == "onyx"
        and vendor.name.casefold() in {"cyryx labs", "cyryx-labs"}
    ):
        return vendor, app, runtime
    return (runtime,)


def _secure_private_directory(path: Path) -> None:
    _reject_link_chain(path)
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ControlPlanePathError("control-plane parent is not a directory")
        if os.name == "nt":
            _secure_windows_acl(path, is_directory=True)
        else:
            getuid = getattr(os, "getuid", None)
            if getuid is not None and info.st_uid != getuid():
                raise ControlPlanePathError("control-plane runtime directory is not user-owned")
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if _identity_from_stat(opened) != _identity_from_stat(info):
                    raise ControlPlanePathError("control-plane runtime directory identity changed")
                os.fchmod(descriptor, 0o700)
                mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
            finally:
                os.close(descriptor)
            if mode != 0o700:
                raise ControlPlanePathError(
                    f"control-plane runtime directory mode is {oct(mode)}, expected 0o700"
                )
    except ControlPlaneError:
        raise
    except OSError as exc:
        raise ControlPlanePathError(f"could not secure control-plane runtime directory: {exc}") from exc


def _prepare_parent(path: Path) -> None:
    managed = _managed_private_directories(path)
    base = managed[0].parent
    missing_base: list[Path] = []
    cursor = base
    while not cursor.exists():
        if cursor.parent == cursor:
            raise ControlPlanePathError("private-data base has no existing filesystem ancestor")
        missing_base.append(cursor)
        cursor = cursor.parent
    _reject_link_chain(cursor)
    if len(managed) > 1 and os.name == "nt" and not missing_base:
        # Prefer an already-protected Onyx root over the broad LOCALAPPDATA
        # ancestor.  The fallback preserves the creation/repair contract: if
        # the managed root is absent or not independently trustworthy, the
        # ancestor must still be safe before anything is created or mutated.
        managed_boundary_is_private = False
        if managed[0].exists():
            try:
                _verify_existing_windows_private_directory(managed[0])
            except ControlPlanePathError:
                pass
            else:
                managed_boundary_is_private = True
        if not managed_boundary_is_private:
            _verify_windows_private_ancestor(base)
    for directory in reversed(missing_base):
        try:
            directory.mkdir(mode=0o700)
        except OSError as exc:
            raise ControlPlanePathError(
                f"could not create private-data base directory: {exc}"
            ) from exc
        _secure_private_directory(directory)
    if len(managed) > 1 and os.name != "nt":
        ancestor = base
        while True:
            _reject_link_chain(ancestor)
            try:
                info = ancestor.lstat()
            except OSError as exc:
                raise ControlPlanePathError(
                    f"could not inspect private-data ancestor {ancestor}: {exc}"
                ) from exc
            if stat.S_IMODE(info.st_mode) & 0o022:
                raise ControlPlanePathError(
                    f"private-data ancestor is writable by another principal: {ancestor}"
                )
            if ancestor.parent == ancestor:
                break
            ancestor = ancestor.parent
    for directory in managed:
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise ControlPlanePathError(
                f"could not create control-plane private directory: {exc}"
            ) from exc
        _secure_private_directory(directory)


def _apply_file_permissions(descriptor: int, path: Path) -> None:
    if os.name == "nt":
        _secure_windows_acl(path, is_directory=False)
        return
    try:
        os.fchmod(descriptor, 0o600)
        mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
    except OSError as exc:
        raise ControlPlanePathError(f"could not apply owner-only sidecar permissions: {exc}") from exc
    if mode != 0o600:
        raise ControlPlanePathError(
            f"control-plane file mode is {oct(mode)}, expected 0o600"
        )


class _WindowsNamedMutex:
    """Native per-path mutex acquired before any filesystem preparation.

    API contract: CreateMutexW/WaitForSingleObject/ReleaseMutex/CloseHandle:
    https://learn.microsoft.com/windows/win32/api/synchapi/nf-synchapi-createmutexw
    """

    def __init__(self, path: Path):
        canonical = os.path.normcase(os.path.abspath(path))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.name = f"Local\\CyryxLabs.Onyx.ControlPlane.{digest}"
        self.handle: int | None = None
        self.acquired = False

    @staticmethod
    def _kernel32():
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        return kernel32

    def acquire(self) -> None:
        if os.name != "nt":
            return
        kernel32 = self._kernel32()
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ControlPlaneLockError(
                f"could not create Windows control-plane mutex: {ctypes.get_last_error()}"
            )
        self.handle = int(handle)
        outcome = int(kernel32.WaitForSingleObject(handle, 120_000))
        if outcome == 0:
            self.acquired = True
            return
        if outcome == 0x80:
            self.acquired = True
            try:
                self.release()
            except ControlPlaneError:
                pass
            raise ControlPlaneLockAbandoned("Windows control-plane mutex was abandoned")
        try:
            self._close_handle()
        except ControlPlaneError:
            pass
        if outcome == 0x102:
            raise ControlPlaneLockTimeout("timed out waiting for Windows control-plane mutex")
        raise ControlPlaneLockError(
            f"Windows control-plane mutex wait failed: {ctypes.get_last_error()}"
        )

    def _close_handle(self) -> None:
        if self.handle is None:
            return
        if not self._kernel32().CloseHandle(self.handle):
            raise ControlPlaneLockError(
                f"could not close Windows control-plane mutex: {ctypes.get_last_error()}"
            )
        self.handle = None

    def release(self) -> None:
        if self.handle is None:
            return
        first_error: ControlPlaneError | None = None
        kernel32 = self._kernel32()
        if self.acquired:
            if not kernel32.ReleaseMutex(self.handle):
                first_error = ControlPlaneLockError(
                    f"could not release Windows control-plane mutex: {ctypes.get_last_error()}"
                )
            else:
                self.acquired = False
        if not kernel32.CloseHandle(self.handle):
            close_error = ControlPlaneLockError(
                f"could not close Windows control-plane mutex: {ctypes.get_last_error()}"
            )
            if first_error is None:
                first_error = close_error
        else:
            self.handle = None
            self.acquired = False
        if first_error is not None:
            raise first_error

    def __del__(self) -> None:
        try:
            self.release()
        except BaseException:
            pass


class _InitializationLock:
    """Cross-process lock held in the already secured runtime directory."""

    def __init__(self, directory: Path):
        self.path = directory / "control_plane.init.lock"
        self.descriptor: int | None = None
        self.locked = False

    def acquire(self) -> None:
        _reject_link_chain(self.path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ControlPlanePathError("control-plane init lock is not a regular file")
            identity = _identity_from_stat(info)
            _assert_path_identity(self.path, identity)
            _apply_file_permissions(descriptor, self.path)
            if info.st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            self.locked = True
            _assert_path_identity(self.path, identity)
            self.descriptor = descriptor
        except ControlPlaneError:
            if "descriptor" in locals():
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise
        except (OSError, ImportError) as exc:
            if "descriptor" in locals():
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise ControlPlanePathError(f"could not acquire control-plane init lock: {exc}") from exc

    def release(self) -> None:
        descriptor = self.descriptor
        if descriptor is None:
            return
        first_error: ControlPlaneError | None = None
        if self.locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            except (OSError, ImportError) as exc:
                first_error = ControlPlaneIOError(
                    f"could not release control-plane init lock: {exc}"
                )
                first_error.__cause__ = exc
            else:
                self.locked = False
        try:
            os.close(descriptor)
        except OSError as exc:
            close_error = ControlPlaneIOError(
                f"could not close control-plane init lock: {exc}"
            )
            close_error.__cause__ = exc
            if first_error is None:
                first_error = close_error
        else:
            self.descriptor = None
            self.locked = False
        if first_error is not None:
            raise first_error


def _valid_utc_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


class ControlPlaneStore:
    """Serialized owner for the versioned M1 control-plane SQLite sidecar."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
    ):
        if enabled is not None and type(enabled) is not bool:
            raise TypeError("enabled must be bool or None")
        try:
            self._runtime_root = Path(private_control_plane_runtime_dir())
        except PrivateDataPathError as exc:
            raise ControlPlanePathError(
                f"could not resolve fixed control-plane runtime: {exc}"
            ) from exc
        self.path = self._runtime_root / "control_plane.sqlite3"
        self.enabled = control_plane_v1_enabled() if enabled is None else enabled
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> "ControlPlaneStore":
        return self.initialize()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        with _CONTROL_PLANE_LOCK:
            return self._connection is not None

    def close(self) -> None:
        with _CONTROL_PLANE_LOCK:
            connection = self._connection
            if connection is None:
                return
            try:
                connection.close()
            except sqlite3.DatabaseError as exc:
                raise ControlPlaneIOError(f"could not close control-plane sidecar: {exc}") from exc
            self._connection = None

    def _require_connection(self) -> sqlite3.Connection:
        """Return the initialized connection for trusted sidecar services."""
        with _CONTROL_PLANE_LOCK:
            if self._connection is None:
                raise ControlPlaneIOError("control-plane sidecar is not initialized")
            return self._connection

    def _resolved_path(self) -> Path:
        try:
            candidate = Path(os.path.abspath(self.path.expanduser()))
            production = Path(
                os.path.abspath((self._runtime_root / "control_plane.sqlite3").expanduser())
            )
        except (OSError, RuntimeError) as exc:
            raise ControlPlanePathError(f"could not resolve control-plane path: {exc}") from exc
        if candidate != production:
            raise ControlPlanePathError("production control-plane path must remain under runtime_dir")
        return candidate

    @staticmethod
    def _integrity_checks(connection: sqlite3.Connection) -> None:
        try:
            quick = connection.execute("PRAGMA quick_check").fetchall()
            full = connection.execute("PRAGMA integrity_check").fetchall()
            foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.DatabaseError as exc:
            raise ControlPlaneCorruptionError(
                f"control-plane integrity checks could not run: {exc}"
            ) from exc
        if quick != [("ok",)] or full != [("ok",)] or foreign:
            raise ControlPlaneCorruptionError("control-plane database integrity check failed")

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        ControlPlaneStore._integrity_checks(connection)
        try:
            application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            actual_manifest = _schema_manifest(connection)
        except sqlite3.DatabaseError as exc:
            raise ControlPlaneCorruptionError(f"could not inspect control-plane schema: {exc}") from exc
        if application_id != APPLICATION_ID:
            raise ControlPlaneSchemaError("database is not an Onyx control-plane sidecar")
        if version > SCHEMA_VERSION:
            raise ControlPlaneSchemaError(
                f"control-plane schema {version} is newer than supported {SCHEMA_VERSION}"
            )
        if version != SCHEMA_VERSION:
            raise ControlPlaneSchemaError(
                f"control-plane schema {version} is unsupported; expected {SCHEMA_VERSION}"
            )
        reference = _reference_manifest()
        if actual_manifest != reference:
            raise ControlPlaneSchemaError("control-plane sqlite_master manifest does not match M1a")
        fingerprint = _schema_fingerprint(actual_manifest)
        try:
            metadata_rows = connection.execute(
                "SELECT key,value FROM schema_metadata ORDER BY key"
            ).fetchall()
            journal_rows = connection.execute(
                "SELECT migration_id,schema_from,schema_to,status,applied_at,schema_fingerprint "
                "FROM migration_journal ORDER BY migration_id"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise ControlPlaneSchemaError(f"control-plane metadata is unreadable: {exc}") from exc
        metadata = dict(metadata_rows)
        if len(metadata_rows) != len(_METADATA_KEYS) or set(metadata) != _METADATA_KEYS:
            raise ControlPlaneSchemaError("control-plane metadata keys are not exact")
        if metadata["schema_id"] != SCHEMA_ID:
            raise ControlPlaneSchemaError("control-plane schema identity is invalid")
        if metadata["schema_version"] != str(SCHEMA_VERSION):
            raise ControlPlaneSchemaError("control-plane schema version metadata is unsupported")
        if metadata["schema_fingerprint"] != fingerprint:
            raise ControlPlaneSchemaError("control-plane schema fingerprint is invalid")
        if not _valid_utc_timestamp(metadata["created_at"]):
            raise ControlPlaneSchemaError("control-plane creation timestamp is invalid")
        m1a_fingerprint = _schema_fingerprint(
            _reference_manifest(version=M1A_SCHEMA_VERSION)
        )
        if len(journal_rows) != 2:
            raise ControlPlaneSchemaError("control-plane migration journal is not exact")
        m1a_row, m1b_row = journal_rows
        if m1a_row != (
            MIGRATION_ID,
            0,
            M1A_SCHEMA_VERSION,
            "applied",
            metadata["created_at"],
            m1a_fingerprint,
        ):
            raise ControlPlaneSchemaError("control-plane M1a migration journal is invalid")
        if (
            m1b_row[0:4]
            != (M1B_MIGRATION_ID, M1A_SCHEMA_VERSION, SCHEMA_VERSION, "applied")
            or not _valid_utc_timestamp(str(m1b_row[4]))
            or m1b_row[5] != fingerprint
        ):
            raise ControlPlaneSchemaError("control-plane M1b migration journal is invalid")

    @staticmethod
    def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
        manifest = _schema_manifest(connection)
        reference = _reference_manifest(version=M1A_SCHEMA_VERSION)
        if manifest != reference:
            raise ControlPlaneSchemaError("control-plane M1a manifest is not migratable")
        metadata_rows = connection.execute(
            "SELECT key,value FROM schema_metadata ORDER BY key"
        ).fetchall()
        metadata = dict(metadata_rows)
        m1a_fingerprint = _schema_fingerprint(reference)
        if (
            len(metadata_rows) != len(_METADATA_KEYS)
            or set(metadata) != _METADATA_KEYS
            or metadata.get("schema_id") != SCHEMA_ID
            or metadata.get("schema_version") != str(M1A_SCHEMA_VERSION)
            or metadata.get("schema_fingerprint") != m1a_fingerprint
            or not _valid_utc_timestamp(str(metadata.get("created_at", "")))
        ):
            raise ControlPlaneSchemaError("control-plane M1a metadata is not migratable")
        journal_rows = connection.execute(
            "SELECT migration_id,schema_from,schema_to,status,applied_at,schema_fingerprint "
            "FROM migration_journal ORDER BY migration_id"
        ).fetchall()
        expected_m1a = (
            MIGRATION_ID,
            0,
            M1A_SCHEMA_VERSION,
            "applied",
            metadata["created_at"],
            m1a_fingerprint,
        )
        if journal_rows != [expected_m1a]:
            raise ControlPlaneSchemaError("control-plane M1a journal is not migratable")
        for table in M1A_DOMAIN_TABLES:
            count = int(
                connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            )
            if count != 0:
                raise ControlPlaneSchemaError(
                    f"control-plane M1a domain table {table} is not empty"
                )
        for statement in M1B_SCHEMA_STATEMENTS:
            connection.execute(statement)
        fingerprint = _schema_fingerprint(_schema_manifest(connection))
        applied_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "UPDATE schema_metadata SET value=? WHERE key='schema_version'",
            (str(SCHEMA_VERSION),),
        )
        connection.execute(
            "UPDATE schema_metadata SET value=? WHERE key='schema_fingerprint'",
            (fingerprint,),
        )
        connection.execute(
            "INSERT INTO migration_journal("
            "migration_id,schema_from,schema_to,status,applied_at,schema_fingerprint"
            ") VALUES(?,?,?,?,?,?)",
            (
                M1B_MIGRATION_ID,
                M1A_SCHEMA_VERSION,
                SCHEMA_VERSION,
                "applied",
                applied_at,
                fingerprint,
            ),
        )
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _preflight_existing(self) -> tuple[int, int]:
        _reject_link_chain(self.path)
        identity = _path_identity(self.path)
        uri = f"{self.path.as_uri()}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5, check_same_thread=False)
        except sqlite3.DatabaseError as exc:
            raise ControlPlaneIOError(f"could not open existing control-plane sidecar: {exc}") from exc
        try:
            self._integrity_checks(connection)
            application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            manifest = _schema_manifest(connection, include_behavior=False)
            if application_id not in (0, APPLICATION_ID):
                raise ControlPlaneSchemaError(
                    f"foreign SQLite application_id {application_id} is not allowed"
                )
            if version > SCHEMA_VERSION:
                raise ControlPlaneSchemaError(
                    f"control-plane schema {version} is newer than supported {SCHEMA_VERSION}"
                )
            if manifest["objects"]:
                if application_id != APPLICATION_ID:
                    raise ControlPlaneSchemaError("database is not an Onyx control-plane sidecar")
                expected_manifest = _reference_manifest(
                    include_behavior=False, version=version
                )
                if manifest != expected_manifest:
                    raise ControlPlaneSchemaError(
                        "control-plane sqlite_master manifest does not match its version"
                    )
            elif application_id != 0 or version != 0:
                raise ControlPlaneSchemaError("empty control-plane file has incompatible markers")
        except ControlPlaneError:
            raise
        except sqlite3.DatabaseError as exc:
            raise ControlPlaneCorruptionError(f"control-plane database is corrupt: {exc}") from exc
        finally:
            try:
                connection.close()
            except sqlite3.DatabaseError:
                pass
        _assert_path_identity(self.path, identity)
        return identity

    def _secure_file(self) -> tuple[tuple[int, int], bool]:
        flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        created = False
        prior_identity: tuple[int, int] | None = None
        try:
            descriptor = os.open(self.path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            prior_identity = self._preflight_existing()
            try:
                descriptor = os.open(self.path, flags)
            except OSError as exc:
                raise ControlPlanePathError(f"could not securely open control-plane file: {exc}") from exc
        except OSError as exc:
            raise ControlPlanePathError(f"could not securely create control-plane file: {exc}") from exc
        identity: tuple[int, int] | None = None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ControlPlanePathError("control-plane descriptor is not a regular file")
            identity = _identity_from_stat(info)
            if prior_identity is not None and identity != prior_identity:
                raise ControlPlanePathError("control-plane file changed after read-only preflight")
            _assert_path_identity(self.path, identity)
            _apply_file_permissions(descriptor, self.path)
            return identity, created
        except BaseException:
            if created and identity is not None:
                try:
                    if _path_identity(self.path) == identity:
                        self.path.unlink()
                except (OSError, ControlPlaneError):
                    pass
            raise
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

    @staticmethod
    def _rollback_and_close(connection: sqlite3.Connection | None) -> None:
        if connection is None:
            return
        try:
            connection.execute("ROLLBACK")
        except sqlite3.DatabaseError:
            pass
        try:
            connection.close()
        except sqlite3.DatabaseError:
            pass

    def initialize(self) -> "ControlPlaneStore":
        """Create or validate M1a atomically after explicit opt-in."""
        if not self.enabled:
            raise ControlPlaneDisabled(
                f"{CONTROL_PLANE_FLAG} is disabled; M1a is not part of default startup"
            )
        with _CONTROL_PLANE_LOCK:
            if self._connection is not None:
                self._validate_schema(self._connection)
                return self
            connection: sqlite3.Connection | None = None
            init_lock: _InitializationLock | None = None
            named_mutex: _WindowsNamedMutex | None = None
            created = False
            committed = False
            identity: tuple[int, int] | None = None
            parent_identity: tuple[int, int] | None = None
            try:
                self.path = self._resolved_path()
                if os.name == "nt":
                    named_mutex = _WindowsNamedMutex(self.path)
                    named_mutex.acquire()
                _reject_link_chain(self.path)
                _prepare_parent(self.path)
                parent_identity = _directory_identity(self.path.parent)
                if os.name != "nt":
                    init_lock = _InitializationLock(self.path.parent)
                    init_lock.acquire()
                identity, created = self._secure_file()
                _assert_directory_identity(self.path.parent, parent_identity)
                # SQLITE_OPEN_NOFOLLOW is an sqlite3_open_v2 C flag, not a URI
                # parameter, and Python's sqlite3.connect does not expose open
                # flags. See https://www.sqlite.org/c3ref/open.html. The secured
                # directory, no-follow descriptor, OS lock and identity checks
                # are the fail-closed stdlib equivalent; mode=rw forbids create
                # and read-only fallback for this already pre-created file.
                uri = f"{self.path.as_uri()}?mode=rw"
                connection = sqlite3.connect(
                    uri,
                    uri=True,
                    timeout=5,
                    isolation_level=None,
                    check_same_thread=False,
                )
                _assert_connection_target(connection, self.path)
                _assert_path_identity(self.path, identity)
                _assert_directory_identity(self.path.parent, parent_identity)
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA trusted_schema=OFF")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("BEGIN IMMEDIATE")
                if not _schema_manifest(connection)["objects"]:
                    for statement in M1A_SCHEMA_STATEMENTS:
                        connection.execute(statement)
                    now = datetime.now(timezone.utc).isoformat()
                    fingerprint = _schema_fingerprint(_schema_manifest(connection))
                    connection.executemany(
                        "INSERT INTO schema_metadata(key,value) VALUES(?,?)",
                        (
                            ("schema_id", SCHEMA_ID),
                            ("schema_version", str(M1A_SCHEMA_VERSION)),
                            ("schema_fingerprint", fingerprint),
                            ("created_at", now),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO migration_journal("
                        "migration_id,schema_from,schema_to,status,applied_at,schema_fingerprint"
                        ") VALUES(?,?,?,?,?,?)",
                        (
                            MIGRATION_ID,
                            0,
                            M1A_SCHEMA_VERSION,
                            "applied",
                            now,
                            fingerprint,
                        ),
                    )
                    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version={M1A_SCHEMA_VERSION}")
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version == M1A_SCHEMA_VERSION:
                    self._migrate_v1_to_v2(connection)
                self._validate_schema(connection)
                _assert_path_identity(self.path, identity)
                _assert_directory_identity(self.path.parent, parent_identity)
                connection.execute("COMMIT")
                committed = True
                self._connection = connection
                return self
            except ControlPlaneError:
                self._rollback_and_close(connection)
                raise
            except sqlite3.DatabaseError as exc:
                self._rollback_and_close(connection)
                raise ControlPlaneIOError(
                    f"could not initialize control-plane SQLite connection: {exc}"
                ) from exc
            except OSError as exc:
                self._rollback_and_close(connection)
                raise ControlPlanePathError(
                    f"could not initialize control-plane path: {exc}"
                ) from exc
            finally:
                if created and not committed and identity is not None:
                    try:
                        if _path_identity(self.path) == identity:
                            self.path.unlink()
                    except (OSError, ControlPlaneError):
                        pass
                if init_lock is not None:
                    try:
                        init_lock.release()
                    except ControlPlaneError:
                        if not committed:
                            raise
                        try:
                            init_lock.release()
                        except ControlPlaneError:
                            pass
                if named_mutex is not None:
                    try:
                        named_mutex.release()
                    except ControlPlaneError:
                        if not committed:
                            raise
                        try:
                            named_mutex.release()
                        except ControlPlaneError:
                            pass
