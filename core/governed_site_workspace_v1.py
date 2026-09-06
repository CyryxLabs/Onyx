"""Governed, source-only authoring workspace for Onyx sites.

This boundary is deliberately absent from live activation.  It owns bounded
UTF-8 drafts and produces exact preview/Git/GitHub plans.  It never starts a
listener or browser, never accepts shell text, never executes JavaScript, and
never obtains credentials.  Material effects require a one-use owner approval
issued by this exact workspace instance and an injected typed adapter.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, Final, Mapping, Protocol


FEATURE_FLAG: Final = "ONYX_GOVERNED_SITE_WORKSPACE_V1"
ABSENT_DIGEST: Final = hashlib.sha256(b"OnyxAbsentFile.v1").hexdigest()
MAX_FILE_BYTES: Final = 512 * 1024
MAX_FILES: Final = 512
MAX_DRAFTS: Final = 2_048
MAX_PAGE_SIZE: Final = 100
MAX_PROVIDER_OUTPUT_BYTES: Final = 2 * 1024 * 1024
ALLOWED_EXTENSIONS: Final = frozenset(
    {".html", ".css", ".js", ".json", ".md", ".txt", ".svg", ".xml", ".yaml", ".yml"}
)
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}\Z")
_IDEMPOTENCY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,191}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BRANCH = re.compile(
    r"(?![-/.])(?!.*(?:\.\.|//|@\{|[~^:?*\\\[]))[A-Za-z0-9][A-Za-z0-9._/-]{0,190}(?<![./])\Z"
)
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CAPABILITY_ISSUER = object()


class SiteWorkspaceError(RuntimeError):
    pass


class SiteWorkspaceContractError(ValueError):
    pass


class SiteWorkspaceDenied(PermissionError):
    pass


class SiteWorkspaceOutcomeUnknown(SiteWorkspaceError):
    pass


class SiteIntentStatusV1(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class GitOperationV1(StrEnum):
    STATUS = "status"
    STAGED_DIFF = "staged_diff"
    COMMIT = "commit"
    ROLLBACK = "rollback"


class GitHubOperationV1(StrEnum):
    CREATE_PULL_REQUEST = "create_pull_request"
    CREATE_ISSUE = "create_issue"


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise SiteWorkspaceContractError("value is not canonical JSON") from exc


def _sha(value: bytes | object) -> str:
    return hashlib.sha256(
        value if type(value) is bytes else _canonical(value)
    ).hexdigest()


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise SiteWorkspaceContractError(f"{label} is invalid")
    return value


def _idempotency(value: object) -> str:
    if type(value) is not str or _IDEMPOTENCY.fullmatch(value) is None:
        raise SiteWorkspaceContractError("idempotency_key is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise SiteWorkspaceContractError(f"{label} is invalid")
    return value


def _branch(value: object) -> str:
    if (
        type(value) is not str
        or _BRANCH.fullmatch(value) is None
        or value.endswith(".lock")
    ):
        raise SiteWorkspaceContractError("branch is invalid")
    return value


def _utf8(value: object, *, label: str, maximum: int = MAX_FILE_BYTES) -> bytes:
    if type(value) is not str or "\x00" in value:
        raise SiteWorkspaceContractError(f"{label} is not bounded UTF-8 text")
    raw = value.encode("utf-8", errors="strict")
    if len(raw) > maximum:
        raise SiteWorkspaceContractError(f"{label} exceeds its byte budget")
    return raw


def _real_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise SiteWorkspaceContractError(f"{label} must be absolute")
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SiteWorkspaceDenied(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SiteWorkspaceDenied(f"{label} must be a real directory")
    if getattr(info, "st_file_attributes", 0) & _REPARSE:
        raise SiteWorkspaceDenied(f"{label} cannot be a reparse point")
    return resolved


def _storage_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise SiteWorkspaceContractError("state_path must be an explicit absolute file")
    path.parent.mkdir(parents=True, exist_ok=True)
    _real_directory(path.parent, "state parent")
    if path.exists():
        info = path.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & _REPARSE
        ):
            raise SiteWorkspaceDenied("linked state database is forbidden")


def _relative_path(value: object) -> str:
    if type(value) is not str or not value or "\x00" in value or "\\" in value:
        raise SiteWorkspaceContractError("relative_path is invalid")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise SiteWorkspaceDenied("path traversal is forbidden")
    if candidate.parts[0].casefold() == ".git":
        raise SiteWorkspaceDenied("Git metadata is outside the site file boundary")
    suffix = candidate.suffix.casefold()
    if suffix not in ALLOWED_EXTENSIONS:
        raise SiteWorkspaceDenied("file extension is outside the text allowlist")
    normalized = candidate.as_posix()
    if len(normalized.encode("utf-8")) > 512:
        raise SiteWorkspaceContractError("relative_path exceeds its byte budget")
    return normalized


def _component_safe(root: Path, relative: str, *, allow_missing_leaf: bool) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    cursor = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            if index == len(parts) - 1 and allow_missing_leaf:
                break
            raise SiteWorkspaceDenied("site path component is unavailable")
        except OSError as exc:
            raise SiteWorkspaceDenied("site path component is unavailable") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & _REPARSE
        ):
            raise SiteWorkspaceDenied("linked or reparse site path is forbidden")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise SiteWorkspaceDenied("site parent component is not a directory")
    try:
        candidate.parent.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise SiteWorkspaceDenied("site path escapes the governed root") from exc
    return candidate


def _file_digest(path: Path) -> str:
    if not path.exists():
        return ABSENT_DIGEST
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_nlink != 1
    ):
        raise SiteWorkspaceDenied("site entry is not a regular file")
    if getattr(info, "st_file_attributes", 0) & _REPARSE:
        raise SiteWorkspaceDenied("reparse site file is forbidden")
    if info.st_size > MAX_FILE_BYTES:
        raise SiteWorkspaceDenied("site file exceeds its byte budget")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SiteWorkspaceDenied("binary site file is forbidden") from exc
    if "\x00" in text:
        raise SiteWorkspaceDenied("binary site file is forbidden")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class SiteWorkspaceFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise SiteWorkspaceContractError("enabled must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "SiteWorkspaceFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class SiteWorkspaceScopeV1:
    owner_profile_id: str
    workspace_id: str
    site_id: str
    repository: str

    def __post_init__(self) -> None:
        _identifier(self.owner_profile_id, "owner_profile_id")
        _identifier(self.workspace_id, "workspace_id")
        _identifier(self.site_id, "site_id")
        if (
            type(self.repository) is not str
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise SiteWorkspaceContractError("repository must be exact owner/name")

    def payload(self) -> dict[str, str]:
        return {
            "owner_profile_id": self.owner_profile_id,
            "workspace_id": self.workspace_id,
            "site_id": self.site_id,
            "repository": self.repository,
        }


@dataclass(frozen=True, slots=True)
class SiteFileV1:
    relative_path: str
    byte_count: int
    content_digest: str


@dataclass(frozen=True, slots=True)
class SiteFilePageV1:
    items: tuple[SiteFileV1, ...]
    next_cursor: str | None
    total: int


@dataclass(frozen=True, slots=True)
class SiteDraftV1:
    draft_id: str
    relative_path: str
    version: int
    base_digest: str
    content_digest: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class SiteOperationPlanV1:
    intent_id: str
    operation: str
    scope_digest: str
    payload: Mapping[str, object]
    argv: tuple[str, ...]
    plan_digest: str


@dataclass(frozen=True, slots=True)
class SiteEffectReceiptV1:
    receipt_id: str
    intent_id: str
    operation: str
    outcome: str
    effect_digest: str
    scope_digest: str
    created_at: float


@dataclass(frozen=True, slots=True)
class SitePreviewPlanV1:
    relative_path: str
    content_digest: str
    root_digest: str
    listener_started: bool = False
    browser_started: bool = False
    process_calls: int = 0


@dataclass(frozen=True, slots=True)
class GitExecutionResultV1:
    exit_code: int
    repository_root: str
    branch: str
    stdout: str
    stderr: str
    head_ref: str
    before_head_oid: str
    before_index_digest: str
    after_head_oid: str
    after_index_digest: str
    effect_digest: str | None = None


@dataclass(frozen=True, slots=True)
class _GitSnapshotV1:
    branch: str
    head_ref: str
    head_oid: str
    index_digest: str
    layout_digest: str


@dataclass(frozen=True, slots=True)
class GitHubExecutionResultV1:
    provider_operation_id: str
    repository: str
    state: str
    effect_digest: str


class SiteGitExecutorV1(Protocol):
    def execute(
        self, *, argv: tuple[str, ...], cwd: Path, timeout_seconds: float
    ) -> GitExecutionResultV1: ...
    def reconcile(
        self, *, intent_id: str, plan_digest: str
    ) -> GitExecutionResultV1 | None: ...


class SiteGitHubAdapterV1(Protocol):
    official_adapter_id: str

    def execute(
        self,
        *,
        operation: GitHubOperationV1,
        repository: str,
        payload: Mapping[str, object],
    ) -> GitHubExecutionResultV1: ...
    def reconcile(
        self, *, intent_id: str, plan_digest: str
    ) -> GitHubExecutionResultV1 | None: ...


@dataclass(frozen=True, slots=True)
class OwnerApprovalRequestV1:
    owner_profile_id: str
    workspace_id: str
    site_id: str
    operation: str
    plan_digest: str


class SiteOwnerApprovalCapabilityV1:
    __slots__ = ("_issuer", "_nonce", "_scope_digest", "_plan_digest")

    def __init__(
        self, issuer: object, nonce: str, scope_digest: str, plan_digest: str
    ) -> None:
        if issuer is not _CAPABILITY_ISSUER:
            raise SiteWorkspaceDenied("approval capabilities are host-issued only")
        self._issuer = issuer
        self._nonce = nonce
        self._scope_digest = scope_digest
        self._plan_digest = plan_digest


class GovernedSiteWorkspaceV1:
    """Exact-scope governed site file and repository boundary."""

    _DDL: Final = (
        "CREATE TABLE metadata(schema_version INTEGER NOT NULL,scope_digest TEXT NOT NULL,state_digest TEXT NOT NULL,key_check TEXT NOT NULL)",
        """CREATE TABLE drafts(
        draft_id TEXT PRIMARY KEY,relative_path TEXT NOT NULL,version INTEGER NOT NULL,
        base_digest TEXT NOT NULL,content BLOB NOT NULL,content_digest TEXT NOT NULL,
        created_at REAL NOT NULL,mac TEXT NOT NULL,UNIQUE(relative_path,version))""",
        """CREATE TABLE intents(
        intent_id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,operation TEXT NOT NULL,
        payload_json TEXT NOT NULL,argv_json TEXT NOT NULL,plan_digest TEXT NOT NULL,status TEXT NOT NULL,
        result_json TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL,mac TEXT NOT NULL)""",
        """CREATE TABLE receipts(
        receipt_id TEXT PRIMARY KEY,intent_id TEXT NOT NULL UNIQUE,operation TEXT NOT NULL,
        outcome TEXT NOT NULL,effect_digest TEXT NOT NULL,scope_digest TEXT NOT NULL,
        created_at REAL NOT NULL,mac TEXT NOT NULL)""",
    )

    def __init__(
        self,
        *,
        root: Path | str,
        state_path: Path | str,
        gate: SiteWorkspaceFeatureGateV1,
        scope: SiteWorkspaceScopeV1,
        integrity_key: bytes,
        owner_approver: Callable[[OwnerApprovalRequestV1], bool],
        git_executor: SiteGitExecutorV1 | None = None,
        github_adapter: SiteGitHubAdapterV1 | None = None,
        git_hooks_directory: Path | str | None = None,
    ) -> None:
        if type(gate) is not SiteWorkspaceFeatureGateV1 or not gate.enabled:
            raise SiteWorkspaceDenied("governed site workspace is disabled")
        if type(scope) is not SiteWorkspaceScopeV1:
            raise SiteWorkspaceContractError("exact SiteWorkspaceScopeV1 is required")
        if type(integrity_key) is not bytes or len(integrity_key) < 32:
            raise SiteWorkspaceContractError(
                "integrity_key must contain at least 32 bytes"
            )
        if not callable(owner_approver):
            raise SiteWorkspaceContractError("owner_approver must be callable")
        self.root = _real_directory(Path(root), "site root")
        self.state_path = Path(state_path)
        _storage_path(self.state_path)
        try:
            self.state_path.resolve(strict=False).relative_to(self.root)
        except ValueError:
            pass
        else:
            raise SiteWorkspaceDenied(
                "state database must be outside the published site root"
            )
        self.scope = scope
        self._scope_digest = _sha(
            {"schema": "OnyxSiteScope.v1", **scope.payload(), "root": str(self.root)}
        )
        self._key = integrity_key
        self._owner_approver = owner_approver
        self._git_executor = git_executor
        self._github_adapter = github_adapter
        self._git_hooks_directory = (
            None
            if git_hooks_directory is None
            else _real_directory(Path(git_hooks_directory), "empty Git hooks directory")
        )
        if self._git_hooks_directory is not None and any(
            self._git_hooks_directory.iterdir()
        ):
            raise SiteWorkspaceDenied("Git hooks isolation directory is not empty")
        self._lock = threading.RLock()
        self._issued: dict[str, tuple[SiteOwnerApprovalCapabilityV1, str]] = {}
        self.background_workers = 0
        self.polling_interval = None
        self._initialize()

    @property
    def scope_digest(self) -> str:
        return self._scope_digest

    @staticmethod
    def execution_boundary() -> dict[str, object]:
        return {
            "shell_strings": False,
            "arbitrary_commands": False,
            "javascript_execution": False,
            "preview_listener": False,
            "browser_launch": False,
            "credential_urls": False,
            "background_workers": 0,
            "polling": False,
        }

    def _mac(self, table: str, values: object) -> str:
        return hmac.new(
            self._key, _canonical({"table": table, "values": values}), hashlib.sha256
        ).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        _storage_path(self.state_path)
        connection = sqlite3.connect(self.state_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _schema_digest(connection: sqlite3.Connection) -> str:
        objects: list[tuple[str, str, str, str]] = []
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ):
            if row[3] is None:
                raise SiteWorkspaceError(
                    "site workspace schema contains an untrusted object"
                )
            normalized = re.sub(r"\s+", " ", str(row[3])).strip()
            objects.append((str(row[0]), str(row[1]), str(row[2]), normalized))
        return _sha({"schema": "OnyxGovernedSiteSqlite.v1", "objects": objects})

    @classmethod
    def _expected_schema_digest(cls) -> str:
        with closing(sqlite3.connect(":memory:")) as connection:
            for statement in cls._DDL:
                connection.execute(statement)
            return cls._schema_digest(connection)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
            )
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if count == 0 and version == 0:
                connection.execute("BEGIN IMMEDIATE")
                for statement in self._DDL:
                    connection.execute(statement)
                state_digest = self._state_digest(connection)
                check = self._mac(
                    "metadata",
                    {
                        "schema_version": 1,
                        "scope_digest": self._scope_digest,
                        "state_digest": state_digest,
                    },
                )
                connection.execute(
                    "INSERT INTO metadata VALUES(1,?,?,?)",
                    (self._scope_digest, state_digest, check),
                )
                connection.execute("PRAGMA user_version=1")
                connection.execute("COMMIT")
        self.verify_integrity()

    def verify_integrity(self) -> None:
        with closing(self._connect()) as connection:
            if int(connection.execute("PRAGMA user_version").fetchone()[0]) != 1:
                raise SiteWorkspaceError("site workspace schema version is not trusted")
            metadata = connection.execute("SELECT * FROM metadata").fetchall()
            if len(metadata) != 1:
                raise SiteWorkspaceError("site workspace metadata is not trusted")
            row = metadata[0]
            schema_objects = {
                (str(item[0]), str(item[1]))
                for item in connection.execute(
                    "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                )
            }
            expected_objects = {
                ("table", "metadata"),
                ("table", "drafts"),
                ("table", "intents"),
                ("table", "receipts"),
            }
            if schema_objects != expected_objects:
                raise SiteWorkspaceError(
                    "site workspace schema objects are not trusted"
                )
            if not hmac.compare_digest(
                self._schema_digest(connection), self._expected_schema_digest()
            ):
                raise SiteWorkspaceError("site workspace schema authentication failed")
            state_digest = self._state_digest(connection)
            stored_state = str(row["state_digest"])
            expected = self._mac(
                "metadata",
                {
                    "schema_version": 1,
                    "scope_digest": self._scope_digest,
                    "state_digest": stored_state,
                },
            )
            if str(
                row["scope_digest"]
            ) != self._scope_digest or not hmac.compare_digest(
                str(row["key_check"]), expected
            ):
                raise SiteWorkspaceDenied(
                    "site workspace key or scope authentication failed"
                )
            if not hmac.compare_digest(stored_state, state_digest):
                raise SiteWorkspaceError(
                    "site workspace authenticated state root diverged"
                )
            for table, columns in (
                (
                    "drafts",
                    (
                        "draft_id",
                        "relative_path",
                        "version",
                        "base_digest",
                        "content",
                        "content_digest",
                        "created_at",
                    ),
                ),
                (
                    "intents",
                    (
                        "intent_id",
                        "idempotency_key",
                        "operation",
                        "payload_json",
                        "argv_json",
                        "plan_digest",
                        "status",
                        "result_json",
                        "created_at",
                        "updated_at",
                    ),
                ),
                (
                    "receipts",
                    (
                        "receipt_id",
                        "intent_id",
                        "operation",
                        "outcome",
                        "effect_digest",
                        "scope_digest",
                        "created_at",
                    ),
                ),
            ):
                for item in connection.execute(f"SELECT * FROM {table}"):
                    values = [
                        item[name].hex() if type(item[name]) is bytes else item[name]
                        for name in columns
                    ]
                    if not hmac.compare_digest(
                        str(item["mac"]), self._mac(table, values)
                    ):
                        raise SiteWorkspaceError(
                            f"{table} integrity authentication failed"
                        )
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SiteWorkspaceError("site workspace database integrity failed")

    @staticmethod
    def _state_digest(connection: sqlite3.Connection) -> str:
        state: list[tuple[str, str, str]] = []
        for table, key in (
            ("drafts", "draft_id"),
            ("intents", "intent_id"),
            ("receipts", "receipt_id"),
        ):
            for row in connection.execute(
                f"SELECT {key},mac FROM {table} ORDER BY {key}"
            ):
                state.append((table, str(row[0]), str(row[1])))
        return _sha({"schema": "OnyxSiteAuthenticatedState.v1", "records": state})

    def _refresh_metadata(self, connection: sqlite3.Connection) -> None:
        state_digest = self._state_digest(connection)
        check = self._mac(
            "metadata",
            {
                "schema_version": 1,
                "scope_digest": self._scope_digest,
                "state_digest": state_digest,
            },
        )
        changed = connection.execute(
            "UPDATE metadata SET state_digest=?,key_check=? WHERE schema_version=1 AND scope_digest=?",
            (state_digest, check, self._scope_digest),
        ).rowcount
        if changed != 1:
            raise SiteWorkspaceError("site workspace metadata update failed")

    def _cursor(self, offset: int) -> str:
        body = f"{self._scope_digest}:{offset}".encode("ascii")
        return body.hex() + "." + hmac.new(self._key, body, hashlib.sha256).hexdigest()

    def _cursor_offset(self, cursor: str | None) -> int:
        if cursor is None:
            return 0
        if type(cursor) is not str or cursor.count(".") != 1:
            raise SiteWorkspaceContractError("cursor is invalid")
        body_hex, signature = cursor.split(".", 1)
        try:
            body = bytes.fromhex(body_hex)
            scope, raw_offset = body.decode("ascii").rsplit(":", 1)
            offset = int(raw_offset)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SiteWorkspaceContractError("cursor is invalid") from exc
        expected = hmac.new(self._key, body, hashlib.sha256).hexdigest()
        if (
            scope != self._scope_digest
            or not hmac.compare_digest(signature, expected)
            or offset < 0
        ):
            raise SiteWorkspaceDenied("cursor authentication failed")
        return offset

    def _scan(self) -> tuple[SiteFileV1, ...]:
        found: list[SiteFileV1] = []
        for directory, names, files in os.walk(
            self.root, topdown=True, followlinks=False
        ):
            current = Path(directory)
            safe_names: list[str] = []
            for name in sorted(names):
                if name.casefold() == ".git":
                    continue
                child = current / name
                info = child.lstat()
                if (
                    stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & _REPARSE
                ):
                    raise SiteWorkspaceDenied("linked site tree component is forbidden")
                safe_names.append(name)
            names[:] = safe_names
            for name in sorted(files):
                path = current / name
                relative = path.relative_to(self.root).as_posix()
                _relative_path(relative)
                info = path.lstat()
                if (
                    not stat.S_ISREG(info.st_mode)
                    or stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & _REPARSE
                ):
                    raise SiteWorkspaceDenied(
                        "non-regular site tree entry is forbidden"
                    )
                digest = _file_digest(path)
                found.append(SiteFileV1(relative, info.st_size, digest))
                if len(found) > MAX_FILES:
                    raise SiteWorkspaceDenied("site file count exceeds its quota")
        return tuple(sorted(found, key=lambda item: item.relative_path))

    def list_files(
        self, *, cursor: str | None = None, limit: int = 50
    ) -> SiteFilePageV1:
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise SiteWorkspaceContractError("limit is outside the page budget")
        offset = self._cursor_offset(cursor)
        items = self._scan()
        page = items[offset : offset + limit]
        next_cursor = (
            self._cursor(offset + limit) if offset + limit < len(items) else None
        )
        return SiteFilePageV1(page, next_cursor, len(items))

    def read_text(self, relative_path: str) -> str:
        relative = _relative_path(relative_path)
        target = _component_safe(self.root, relative, allow_missing_leaf=False)
        _file_digest(target)
        return target.read_text(encoding="utf-8", errors="strict")

    def create_draft(
        self, *, relative_path: str, content: str, expected_base_digest: str
    ) -> SiteDraftV1:
        relative = _relative_path(relative_path)
        base = _digest(expected_base_digest, "expected_base_digest")
        raw = _utf8(content, label="content")
        target = _component_safe(self.root, relative, allow_missing_leaf=True)
        observed = _file_digest(target)
        if not hmac.compare_digest(observed, base):
            raise SiteWorkspaceDenied("site file changed before draft creation")
        with self._lock, closing(self._connect()) as connection, connection:
            count = int(connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0])
            if count >= MAX_DRAFTS:
                raise SiteWorkspaceDenied("draft quota exhausted")
            previous = connection.execute(
                "SELECT MAX(version) FROM drafts WHERE relative_path=?", (relative,)
            ).fetchone()[0]
            version = 1 if previous is None else int(previous) + 1
            draft_id = "site_draft_" + uuid.uuid4().hex
            created = time.time()
            content_digest = hashlib.sha256(raw).hexdigest()
            values = [
                draft_id,
                relative,
                version,
                base,
                raw.hex(),
                content_digest,
                created,
            ]
            connection.execute(
                "INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?)",
                (
                    draft_id,
                    relative,
                    version,
                    base,
                    raw,
                    content_digest,
                    created,
                    self._mac("drafts", values),
                ),
            )
            self._refresh_metadata(connection)
        return SiteDraftV1(draft_id, relative, version, base, content_digest, len(raw))

    def _draft_row(self, draft_id: str) -> sqlite3.Row:
        key = _identifier(draft_id, "draft_id")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM drafts WHERE draft_id=?", (key,)
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return row

    def _plan(
        self,
        *,
        operation: str,
        payload: Mapping[str, object],
        idempotency_key: str,
        argv: tuple[str, ...] = (),
    ) -> SiteOperationPlanV1:
        idem = _idempotency(idempotency_key)
        if type(argv) is not tuple or any(type(item) is not str for item in argv):
            raise SiteWorkspaceContractError("argv must be an exact tuple of strings")
        canonical_payload = json.loads(_canonical(dict(payload)).decode("ascii"))
        public_payload = MappingProxyType(dict(canonical_payload))
        plan_digest = _sha(
            {
                "schema": "OnyxSiteOperationPlan.v1",
                "scope_digest": self._scope_digest,
                "operation": operation,
                "payload": canonical_payload,
                "argv": argv,
            }
        )
        with self._lock, closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT * FROM intents WHERE idempotency_key=?", (idem,)
            ).fetchone()
            if existing is not None:
                if str(existing["plan_digest"]) != plan_digest:
                    raise SiteWorkspaceDenied(
                        "idempotency key is bound to another operation"
                    )
                stored_argv = tuple(json.loads(str(existing["argv_json"])))
                if stored_argv != argv:
                    raise SiteWorkspaceDenied(
                        "idempotency key is bound to another command"
                    )
                return SiteOperationPlanV1(
                    str(existing["intent_id"]),
                    operation,
                    self._scope_digest,
                    public_payload,
                    argv,
                    plan_digest,
                )
            intent_id = "site_intent_" + uuid.uuid4().hex
            now = time.time()
            payload_json = _canonical(canonical_payload).decode("ascii")
            argv_json = _canonical(argv).decode("ascii")
            values = [
                intent_id,
                idem,
                operation,
                payload_json,
                argv_json,
                plan_digest,
                SiteIntentStatusV1.PENDING.value,
                None,
                now,
                now,
            ]
            connection.execute(
                "INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (*values, self._mac("intents", values)),
            )
            self._refresh_metadata(connection)
        return SiteOperationPlanV1(
            intent_id,
            operation,
            self._scope_digest,
            public_payload,
            argv,
            plan_digest,
        )

    def plan_apply_draft(
        self, draft_id: str, *, idempotency_key: str
    ) -> SiteOperationPlanV1:
        row = self._draft_row(draft_id)
        return self._plan(
            operation="apply_draft",
            payload={
                "draft_id": str(row["draft_id"]),
                "relative_path": str(row["relative_path"]),
                "version": int(row["version"]),
                "base_digest": str(row["base_digest"]),
                "content_digest": str(row["content_digest"]),
            },
            idempotency_key=idempotency_key,
        )

    def plan_preview(self, *, relative_path: str = "index.html") -> SitePreviewPlanV1:
        relative = _relative_path(relative_path)
        target = _component_safe(self.root, relative, allow_missing_leaf=False)
        digest = _file_digest(target)
        return SitePreviewPlanV1(
            relative,
            digest,
            _sha({"root": str(self.root), "scope": self._scope_digest}),
        )

    def issue_owner_approval(
        self, plan: SiteOperationPlanV1
    ) -> SiteOwnerApprovalCapabilityV1:
        self._validate_plan(plan, require_pending=True)
        request = OwnerApprovalRequestV1(
            self.scope.owner_profile_id,
            self.scope.workspace_id,
            self.scope.site_id,
            plan.operation,
            plan.plan_digest,
        )
        approved = self._owner_approver(request)
        if type(approved) is not bool or not approved:
            raise SiteWorkspaceDenied("owner approval was not granted")
        if len(self._issued) >= 256:
            raise SiteWorkspaceDenied("outstanding owner approval quota is exhausted")
        nonce = uuid.uuid4().hex
        capability = SiteOwnerApprovalCapabilityV1(
            _CAPABILITY_ISSUER, nonce, self._scope_digest, plan.plan_digest
        )
        self._issued[nonce] = (capability, plan.plan_digest)
        return capability

    def _consume(
        self, plan: SiteOperationPlanV1, capability: SiteOwnerApprovalCapabilityV1
    ) -> None:
        if type(capability) is not SiteOwnerApprovalCapabilityV1:
            raise SiteWorkspaceDenied("exact owner approval capability is required")
        registered = self._issued.pop(capability._nonce, None)
        if (
            registered is None
            or registered[0] is not capability
            or registered[1] != plan.plan_digest
            or capability._scope_digest != self._scope_digest
            or capability._plan_digest != plan.plan_digest
        ):
            raise SiteWorkspaceDenied(
                "owner approval capability is invalid or consumed"
            )

    def _validate_plan(
        self, plan: SiteOperationPlanV1, *, require_pending: bool
    ) -> sqlite3.Row:
        if (
            type(plan) is not SiteOperationPlanV1
            or plan.scope_digest != self._scope_digest
            or type(plan.argv) is not tuple
            or any(type(item) is not str for item in plan.argv)
        ):
            raise SiteWorkspaceDenied("operation plan is outside the exact site scope")
        expected = _sha(
            {
                "schema": "OnyxSiteOperationPlan.v1",
                "scope_digest": self._scope_digest,
                "operation": plan.operation,
                "payload": dict(plan.payload),
                "argv": plan.argv,
            }
        )
        if not hmac.compare_digest(plan.plan_digest, expected):
            raise SiteWorkspaceDenied("operation plan authentication failed")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM intents WHERE intent_id=?", (plan.intent_id,)
            ).fetchone()
        if (
            row is None
            or str(row["plan_digest"]) != plan.plan_digest
            or tuple(json.loads(str(row["argv_json"]))) != plan.argv
        ):
            raise SiteWorkspaceDenied("operation intent binding is unavailable")
        if require_pending and str(row["status"]) != SiteIntentStatusV1.PENDING.value:
            raise SiteWorkspaceDenied(f"operation intent is {row['status']}")
        return row

    def _set_intent(
        self,
        intent_id: str,
        *,
        status: SiteIntentStatusV1,
        result: Mapping[str, object] | None,
    ) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if row is None:
                raise KeyError(intent_id)
            now = time.time()
            result_json = (
                None if result is None else _canonical(dict(result)).decode("ascii")
            )
            values = [
                row["intent_id"],
                row["idempotency_key"],
                row["operation"],
                row["payload_json"],
                row["argv_json"],
                row["plan_digest"],
                status.value,
                result_json,
                row["created_at"],
                now,
            ]
            connection.execute(
                "UPDATE intents SET status=?,result_json=?,updated_at=?,mac=? WHERE intent_id=?",
                (
                    status.value,
                    result_json,
                    now,
                    self._mac("intents", values),
                    intent_id,
                ),
            )
            self._refresh_metadata(connection)

    def _receipt(
        self, plan: SiteOperationPlanV1, *, outcome: str, effect_digest: str
    ) -> SiteEffectReceiptV1:
        _digest(effect_digest, "effect_digest")
        with self._lock, closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT * FROM receipts WHERE intent_id=?", (plan.intent_id,)
            ).fetchone()
            if existing is not None:
                return self._receipt_from_row(existing)
            receipt_id = "site_receipt_" + uuid.uuid4().hex
            created = time.time()
            values = [
                receipt_id,
                plan.intent_id,
                plan.operation,
                outcome,
                effect_digest,
                self._scope_digest,
                created,
            ]
            connection.execute(
                "INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?)",
                (*values, self._mac("receipts", values)),
            )
            self._refresh_metadata(connection)
        return SiteEffectReceiptV1(
            receipt_id,
            plan.intent_id,
            plan.operation,
            outcome,
            effect_digest,
            self._scope_digest,
            created,
        )

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> SiteEffectReceiptV1:
        return SiteEffectReceiptV1(
            str(row["receipt_id"]),
            str(row["intent_id"]),
            str(row["operation"]),
            str(row["outcome"]),
            str(row["effect_digest"]),
            str(row["scope_digest"]),
            float(row["created_at"]),
        )

    def get_receipt(self, intent_id: str) -> SiteEffectReceiptV1:
        key = _identifier(intent_id, "intent_id")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM receipts WHERE intent_id=?", (key,)
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return self._receipt_from_row(row)

    def execute_apply_draft(
        self, plan: SiteOperationPlanV1, capability: SiteOwnerApprovalCapabilityV1
    ) -> SiteEffectReceiptV1:
        self._validate_plan(plan, require_pending=True)
        if plan.operation != "apply_draft":
            raise SiteWorkspaceDenied("plan is not a draft application")
        self._consume(plan, capability)
        row = self._draft_row(str(plan.payload["draft_id"]))
        if (
            str(row["content_digest"]) != plan.payload["content_digest"]
            or str(row["base_digest"]) != plan.payload["base_digest"]
        ):
            self._set_intent(
                plan.intent_id,
                status=SiteIntentStatusV1.REJECTED,
                result={"reason": "draft_drift"},
            )
            raise SiteWorkspaceDenied("draft binding changed")
        relative = str(row["relative_path"])
        target = _component_safe(self.root, relative, allow_missing_leaf=True)
        if not hmac.compare_digest(_file_digest(target), str(row["base_digest"])):
            self._set_intent(
                plan.intent_id,
                status=SiteIntentStatusV1.REJECTED,
                result={"reason": "file_drift"},
            )
            raise SiteWorkspaceDenied("site file changed after planning")
        raw = bytes(row["content"])
        if str(row["base_digest"]) == ABSENT_DIGEST and len(self._scan()) >= MAX_FILES:
            self._set_intent(
                plan.intent_id,
                status=SiteIntentStatusV1.REJECTED,
                result={"reason": "file_quota"},
            )
            raise SiteWorkspaceDenied("site file count quota is exhausted")
        effect_started = False
        temp_name: str | None = None
        try:
            _component_safe(self.root, relative, allow_missing_leaf=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".onyx-site-", dir=target.parent
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            _component_safe(self.root, relative, allow_missing_leaf=True)
            if not hmac.compare_digest(_file_digest(target), str(row["base_digest"])):
                raise SiteWorkspaceDenied("site file changed during application")
            effect_started = True
            os.replace(temp_name, target)
            temp_name = None
            observed = _file_digest(target)
            if not hmac.compare_digest(observed, str(row["content_digest"])):
                raise SiteWorkspaceOutcomeUnknown("applied file digest is uncertain")
        except BaseException as exc:
            if temp_name is not None:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
            status = (
                SiteIntentStatusV1.UNKNOWN
                if effect_started
                else SiteIntentStatusV1.REJECTED
            )
            self._set_intent(
                plan.intent_id, status=status, result={"reason": type(exc).__name__}
            )
            if effect_started:
                raise SiteWorkspaceOutcomeUnknown(
                    "draft effect requires reconciliation"
                ) from exc
            raise
        self._set_intent(
            plan.intent_id,
            status=SiteIntentStatusV1.SUCCEEDED,
            result={"content_digest": observed},
        )
        return self._receipt(plan, outcome="applied", effect_digest=observed)

    def reconcile_apply_draft(self, plan: SiteOperationPlanV1) -> SiteEffectReceiptV1:
        row = self._validate_plan(plan, require_pending=False)
        if str(row["status"]) == SiteIntentStatusV1.SUCCEEDED.value:
            return self.get_receipt(plan.intent_id)
        if (
            str(row["status"]) != SiteIntentStatusV1.UNKNOWN.value
            or plan.operation != "apply_draft"
        ):
            raise SiteWorkspaceDenied("draft operation is not reconcilable")
        target = _component_safe(
            self.root, str(plan.payload["relative_path"]), allow_missing_leaf=True
        )
        observed = _file_digest(target)
        if hmac.compare_digest(observed, str(plan.payload["content_digest"])):
            self._set_intent(
                plan.intent_id,
                status=SiteIntentStatusV1.SUCCEEDED,
                result={"content_digest": observed, "reconciled": True},
            )
            return self._receipt(
                plan, outcome="applied_reconciled", effect_digest=observed
            )
        if hmac.compare_digest(observed, str(plan.payload["base_digest"])):
            self._set_intent(
                plan.intent_id,
                status=SiteIntentStatusV1.REJECTED,
                result={"reason": "not_applied", "reconciled": True},
            )
            raise SiteWorkspaceDenied("draft was verified not applied")
        raise SiteWorkspaceOutcomeUnknown("draft outcome remains unknown")

    @staticmethod
    def _trusted_git_bytes(path: Path, *, maximum: int, label: str) -> bytes:
        try:
            info = path.lstat()
        except OSError as exc:
            raise SiteWorkspaceDenied(f"{label} is unavailable") from exc
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & _REPARSE
            or info.st_nlink != 1
            or not 0 < info.st_size <= maximum
        ):
            raise SiteWorkspaceDenied(f"{label} is outside its trusted boundary")
        raw = path.read_bytes()
        if len(raw) != info.st_size or b"\x00" in raw:
            raise SiteWorkspaceDenied(f"{label} changed while being read")
        return raw

    def _git_layout(self) -> tuple[Path, Path, str]:
        marker = self.root / ".git"
        try:
            info = marker.lstat()
        except OSError as exc:
            raise SiteWorkspaceDenied("site root is not a Git worktree") from exc
        marker_payload: dict[str, object]
        if stat.S_ISDIR(info.st_mode):
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & _REPARSE
            ):
                raise SiteWorkspaceDenied("linked Git metadata is forbidden")
            git_dir = _real_directory(marker, "Git directory")
            marker_payload = {"layout": "directory", "git_dir": str(git_dir)}
        elif stat.S_ISREG(info.st_mode):
            raw = self._trusted_git_bytes(
                marker, maximum=4096, label="Git worktree marker"
            )
            try:
                value = raw.decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError as exc:
                raise SiteWorkspaceDenied("Git worktree marker is invalid") from exc
            if not value.startswith("gitdir: ") or "\n" in value or "\r" in value:
                raise SiteWorkspaceDenied("Git worktree marker is invalid")
            supplied = Path(value.removeprefix("gitdir: "))
            candidate = supplied if supplied.is_absolute() else marker.parent / supplied
            git_dir = _real_directory(
                candidate.resolve(strict=True), "Git worktree directory"
            )
            marker_payload = {
                "layout": "linked_worktree",
                "marker_digest": hashlib.sha256(raw).hexdigest(),
                "git_dir": str(git_dir),
            }
        else:
            raise SiteWorkspaceDenied("Git metadata marker is invalid")
        common_marker = git_dir / "commondir"
        if common_marker.exists():
            raw = self._trusted_git_bytes(
                common_marker, maximum=4096, label="Git common-directory marker"
            )
            try:
                supplied_common = Path(raw.decode("utf-8", errors="strict").strip())
            except UnicodeDecodeError as exc:
                raise SiteWorkspaceDenied(
                    "Git common-directory marker is invalid"
                ) from exc
            candidate = (
                supplied_common
                if supplied_common.is_absolute()
                else git_dir / supplied_common
            )
            common_dir = _real_directory(
                candidate.resolve(strict=True), "Git common directory"
            )
            marker_payload["commondir_digest"] = hashlib.sha256(raw).hexdigest()
        else:
            common_dir = git_dir
        marker_payload["common_dir"] = str(common_dir)
        return git_dir, common_dir, _sha(marker_payload)

    def _resolve_git_ref(self, git_dir: Path, common_dir: Path, ref_name: str) -> str:
        current = ref_name
        seen: set[str] = set()
        for _ in range(5):
            if current in seen or not current.startswith("refs/heads/"):
                raise SiteWorkspaceDenied("Git symbolic ref is invalid")
            seen.add(current)
            raw: bytes | None = None
            for base in (git_dir, common_dir):
                candidate = base.joinpath(*PurePosixPath(current).parts)
                if candidate.exists():
                    raw = self._trusted_git_bytes(
                        candidate, maximum=4096, label="Git loose ref"
                    )
                    break
            if raw is not None:
                try:
                    value = raw.decode("ascii", errors="strict").strip()
                except UnicodeDecodeError as exc:
                    raise SiteWorkspaceDenied("Git loose ref is invalid") from exc
                if value.startswith("ref: "):
                    current = value.removeprefix("ref: ")
                    continue
                if _COMMIT.fullmatch(value) is None:
                    raise SiteWorkspaceDenied("Git loose ref object id is invalid")
                return value
            packed = common_dir / "packed-refs"
            if not packed.exists():
                raise SiteWorkspaceDenied("Git branch object id is unavailable")
            packed_raw = self._trusted_git_bytes(
                packed, maximum=16 * 1024 * 1024, label="Git packed refs"
            )
            try:
                lines = packed_raw.decode("ascii", errors="strict").splitlines()
            except UnicodeDecodeError as exc:
                raise SiteWorkspaceDenied("Git packed refs are invalid") from exc
            for line in lines:
                if not line or line[0] in {"#", "^"}:
                    continue
                parts = line.split(" ", 1)
                if len(parts) == 2 and parts[1] == current:
                    if _COMMIT.fullmatch(parts[0]) is None:
                        raise SiteWorkspaceDenied("Git packed object id is invalid")
                    return parts[0]
            raise SiteWorkspaceDenied("Git branch object id is unavailable")
        raise SiteWorkspaceDenied("Git symbolic ref depth is invalid")

    def _git_snapshot_once(self) -> _GitSnapshotV1:
        git_dir, common_dir, layout_digest = self._git_layout()
        head_raw = self._trusted_git_bytes(
            git_dir / "HEAD", maximum=4096, label="Git HEAD"
        )
        try:
            head_value = head_raw.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise SiteWorkspaceDenied("Git HEAD is invalid") from exc
        prefix = "ref: refs/heads/"
        if not head_value.startswith(prefix):
            raise SiteWorkspaceDenied("detached Git HEAD is not supported")
        branch = _branch(head_value.removeprefix(prefix))
        head_ref = "refs/heads/" + branch
        head_oid = self._resolve_git_ref(git_dir, common_dir, head_ref)
        index = git_dir / "index"
        if index.exists():
            index_raw = self._trusted_git_bytes(
                index, maximum=64 * 1024 * 1024, label="Git index"
            )
            index_digest = hashlib.sha256(index_raw).hexdigest()
        else:
            index_digest = ABSENT_DIGEST
        return _GitSnapshotV1(branch, head_ref, head_oid, index_digest, layout_digest)

    def _git_snapshot(self) -> _GitSnapshotV1:
        first = self._git_snapshot_once()
        second = self._git_snapshot_once()
        if first != second:
            raise SiteWorkspaceDenied("Git state changed during snapshot")
        return first

    def plan_git(
        self,
        *,
        operation: GitOperationV1,
        expected_branch: str,
        idempotency_key: str,
        message: str | None = None,
        rollback_commit: str | None = None,
        staged_diff_receipt_id: str | None = None,
    ) -> SiteOperationPlanV1:
        if type(operation) is not GitOperationV1:
            raise SiteWorkspaceContractError("exact GitOperationV1 is required")
        expected = _branch(expected_branch)
        snapshot = self._git_snapshot()
        if snapshot.branch != expected:
            raise SiteWorkspaceDenied("Git branch does not match the approved branch")
        safe_prefix = (
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "diff.external=",
            "-c",
            "core.pager=cat",
            "-c",
            "credential.helper=",
        )
        if operation is GitOperationV1.STATUS:
            argv = safe_prefix + ("status", "--porcelain=v2", "--branch", "--")
        elif operation is GitOperationV1.STAGED_DIFF:
            argv = safe_prefix + (
                "diff",
                "--cached",
                "--no-ext-diff",
                "--stat",
                "--patch",
                "--",
            )
        elif operation is GitOperationV1.COMMIT:
            if self._git_hooks_directory is None:
                raise SiteWorkspaceDenied(
                    "commit planning requires an injected empty hooks directory"
                )
            raw = _utf8(message, label="commit message", maximum=512)
            if b"\r" in raw or b"\n" in raw or raw.startswith(b"-"):
                raise SiteWorkspaceContractError("commit message is invalid")
            if type(staged_diff_receipt_id) is not str:
                raise SiteWorkspaceDenied(
                    "commit requires a staged-diff inspection receipt"
                )
            receipt_key = _identifier(staged_diff_receipt_id, "staged_diff_receipt_id")
            with closing(self._connect()) as connection:
                inspected = connection.execute(
                    "SELECT * FROM receipts WHERE receipt_id=?", (receipt_key,)
                ).fetchone()
            if (
                inspected is None
                or str(inspected["operation"]) != "git.staged_diff"
                or str(inspected["scope_digest"]) != self._scope_digest
                or str(inspected["outcome"]) not in {"git_verified", "git_reconciled"}
            ):
                raise SiteWorkspaceDenied(
                    "staged-diff inspection receipt is not trusted"
                )
            with closing(self._connect()) as connection:
                inspected_intent = connection.execute(
                    "SELECT payload_json FROM intents WHERE intent_id=?",
                    (str(inspected["intent_id"]),),
                ).fetchone()
            if inspected_intent is None:
                raise SiteWorkspaceDenied(
                    "staged-diff inspection intent is unavailable"
                )
            inspected_payload = json.loads(str(inspected_intent["payload_json"]))
            if any(
                inspected_payload.get(field) != getattr(snapshot, field)
                for field in (
                    "head_ref",
                    "head_oid",
                    "index_digest",
                    "layout_digest",
                )
            ):
                raise SiteWorkspaceDenied(
                    "Git state changed after staged-diff inspection"
                )
            argv = safe_prefix + (
                "-c",
                f"core.hooksPath={self._git_hooks_directory}",
                "-c",
                "commit.gpgSign=false",
                "commit",
                "-m",
                raw.decode("utf-8"),
                "--",
            )
        else:
            if self._git_hooks_directory is None:
                raise SiteWorkspaceDenied(
                    "rollback planning requires an injected empty hooks directory"
                )
            if (
                type(rollback_commit) is not str
                or _COMMIT.fullmatch(rollback_commit) is None
            ):
                raise SiteWorkspaceContractError("rollback_commit is invalid")
            argv = safe_prefix + (
                "-c",
                f"core.hooksPath={self._git_hooks_directory}",
                "-c",
                "commit.gpgSign=false",
                "revert",
                "--no-edit",
                "--no-gpg-sign",
                rollback_commit,
            )
        return self._plan(
            operation="git." + operation.value,
            payload={
                "repository": self.scope.repository,
                "branch": expected,
                "head_ref": snapshot.head_ref,
                "head_oid": snapshot.head_oid,
                "index_digest": snapshot.index_digest,
                "layout_digest": snapshot.layout_digest,
                "timeout_seconds": 30.0,
                "staged_diff_receipt_id": staged_diff_receipt_id,
                "staged_diff_digest": (
                    None
                    if operation is not GitOperationV1.COMMIT
                    else str(inspected["effect_digest"])
                ),
            },
            idempotency_key=idempotency_key,
            argv=argv,
        )

    @staticmethod
    def _snapshot_matches_plan(
        snapshot: _GitSnapshotV1, plan: SiteOperationPlanV1
    ) -> bool:
        return (
            snapshot.branch == plan.payload["branch"]
            and snapshot.head_ref == plan.payload["head_ref"]
            and snapshot.head_oid == plan.payload["head_oid"]
            and snapshot.index_digest == plan.payload["index_digest"]
            and snapshot.layout_digest == plan.payload["layout_digest"]
        )

    def _validate_git_result(
        self,
        plan: SiteOperationPlanV1,
        result: GitExecutionResultV1,
        after: _GitSnapshotV1,
    ) -> str:
        if type(result) is not GitExecutionResultV1:
            raise SiteWorkspaceOutcomeUnknown("Git adapter returned an invalid result")
        if type(result.exit_code) is not int or result.exit_code != 0:
            raise SiteWorkspaceError("Git operation returned a known failure")
        try:
            observed_root = Path(result.repository_root).resolve(strict=True)
        except OSError as exc:
            raise SiteWorkspaceOutcomeUnknown(
                "Git repository result is unavailable"
            ) from exc
        before_oid = result.before_head_oid
        after_oid = result.after_head_oid
        if (
            _COMMIT.fullmatch(before_oid) is None
            or _COMMIT.fullmatch(after_oid) is None
            or _HEX64.fullmatch(result.before_index_digest) is None
            or _HEX64.fullmatch(result.after_index_digest) is None
        ):
            raise SiteWorkspaceOutcomeUnknown("Git result object binding is invalid")
        if (
            observed_root != self.root
            or result.branch != plan.payload["branch"]
            or result.head_ref != plan.payload["head_ref"]
            or before_oid != plan.payload["head_oid"]
            or result.before_index_digest != plan.payload["index_digest"]
            or after.branch != result.branch
            or after.head_ref != result.head_ref
            or after.head_oid != after_oid
            or after.index_digest != result.after_index_digest
            or after.layout_digest != plan.payload["layout_digest"]
        ):
            raise SiteWorkspaceOutcomeUnknown("Git result scope diverged")
        if plan.operation in {"git.status", "git.staged_diff"}:
            if (
                after_oid != before_oid
                or after.index_digest != result.before_index_digest
            ):
                raise SiteWorkspaceOutcomeUnknown(
                    "read-only Git operation changed repository state"
                )
        elif plan.operation in {"git.commit", "git.rollback"}:
            if after_oid == before_oid:
                raise SiteWorkspaceOutcomeUnknown(
                    "mutating Git operation did not produce a new commit"
                )
        else:
            raise SiteWorkspaceDenied("Git operation is not allowlisted")
        stdout = _utf8(
            result.stdout, label="Git stdout", maximum=MAX_PROVIDER_OUTPUT_BYTES
        )
        stderr = _utf8(
            result.stderr, label="Git stderr", maximum=MAX_PROVIDER_OUTPUT_BYTES
        )
        adapter_effect = (
            None
            if result.effect_digest is None
            else _digest(result.effect_digest, "effect_digest")
        )
        return _sha(
            {
                "schema": "OnyxGitEffect.v1",
                "plan_digest": plan.plan_digest,
                "stdout_digest": hashlib.sha256(stdout).hexdigest(),
                "stderr_digest": hashlib.sha256(stderr).hexdigest(),
                "adapter_effect_digest": adapter_effect,
                "before_head_oid": before_oid,
                "before_index_digest": result.before_index_digest,
                "after_head_oid": after_oid,
                "after_index_digest": result.after_index_digest,
            }
        )

    def execute_git(
        self, plan: SiteOperationPlanV1, capability: SiteOwnerApprovalCapabilityV1
    ) -> SiteEffectReceiptV1:
        self._validate_plan(plan, require_pending=True)
        if not plan.operation.startswith("git.") or self._git_executor is None:
            raise SiteWorkspaceDenied("exact injected Git executor is unavailable")
        self._consume(plan, capability)
        before = self._git_snapshot()
        if not self._snapshot_matches_plan(before, plan):
            self._set_intent(
                plan.intent_id,
                status=SiteIntentStatusV1.REJECTED,
                result={"reason": "branch_drift"},
            )
            raise SiteWorkspaceDenied(
                "Git branch, ref, HEAD, index, or layout changed after planning"
            )
        try:
            result = self._git_executor.execute(
                argv=plan.argv,
                cwd=self.root,
                timeout_seconds=float(plan.payload["timeout_seconds"]),
            )
            after = self._git_snapshot()
            effect = self._validate_git_result(plan, result, after)
        except BaseException as exc:
            self._set_intent(
                plan.intent_id,
                status=SiteIntentStatusV1.UNKNOWN,
                result={"reason": type(exc).__name__},
            )
            raise SiteWorkspaceOutcomeUnknown(
                "Git outcome requires reconciliation"
            ) from exc
        self._set_intent(
            plan.intent_id,
            status=SiteIntentStatusV1.SUCCEEDED,
            result={"effect_digest": effect},
        )
        outcome = (
            "rollback_verified" if plan.operation == "git.rollback" else "git_verified"
        )
        return self._receipt(plan, outcome=outcome, effect_digest=effect)

    def reconcile_git(self, plan: SiteOperationPlanV1) -> SiteEffectReceiptV1:
        row = self._validate_plan(plan, require_pending=False)
        if str(row["status"]) == SiteIntentStatusV1.SUCCEEDED.value:
            return self.get_receipt(plan.intent_id)
        if (
            str(row["status"]) != SiteIntentStatusV1.UNKNOWN.value
            or self._git_executor is None
        ):
            raise SiteWorkspaceDenied("Git operation is not reconcilable")
        result = self._git_executor.reconcile(
            intent_id=plan.intent_id, plan_digest=plan.plan_digest
        )
        if result is None:
            raise SiteWorkspaceOutcomeUnknown("Git outcome remains unknown")
        after = self._git_snapshot()
        effect = self._validate_git_result(plan, result, after)
        self._set_intent(
            plan.intent_id,
            status=SiteIntentStatusV1.SUCCEEDED,
            result={"effect_digest": effect, "reconciled": True},
        )
        outcome = (
            "rollback_reconciled"
            if plan.operation == "git.rollback"
            else "git_reconciled"
        )
        return self._receipt(plan, outcome=outcome, effect_digest=effect)

    def plan_github(
        self,
        *,
        operation: GitHubOperationV1,
        expected_branch: str,
        title: str,
        body: str,
        idempotency_key: str,
    ) -> SiteOperationPlanV1:
        if type(operation) is not GitHubOperationV1:
            raise SiteWorkspaceContractError("exact GitHubOperationV1 is required")
        branch = _branch(expected_branch)
        title_text = _utf8(title, label="title", maximum=256).decode("utf-8")
        body_text = _utf8(body, label="body", maximum=32_768).decode("utf-8")
        if (
            "https://" in self.scope.repository.casefold()
            or "@" in self.scope.repository
        ):
            raise SiteWorkspaceDenied("token-bearing repository URLs are forbidden")
        return self._plan(
            operation="github." + operation.value,
            payload={
                "repository": self.scope.repository,
                "branch": branch,
                "title": title_text,
                "body_digest": hashlib.sha256(body_text.encode()).hexdigest(),
                "body": body_text,
                "provider": "official_github_api",
            },
            idempotency_key=idempotency_key,
        )

    def execute_github(
        self, plan: SiteOperationPlanV1, capability: SiteOwnerApprovalCapabilityV1
    ) -> SiteEffectReceiptV1:
        self._validate_plan(plan, require_pending=True)
        if not plan.operation.startswith("github.") or self._github_adapter is None:
            raise SiteWorkspaceDenied(
                "exact injected official GitHub adapter is unavailable"
            )
        if (
            getattr(self._github_adapter, "official_adapter_id", None)
            != "onyx.github.official.v1"
        ):
            raise SiteWorkspaceDenied(
                "GitHub adapter is not the official typed boundary"
            )
        self._consume(plan, capability)
        operation = GitHubOperationV1(plan.operation.removeprefix("github."))
        try:
            result = self._github_adapter.execute(
                operation=operation,
                repository=self.scope.repository,
                payload=dict(plan.payload),
            )
            if (
                type(result) is not GitHubExecutionResultV1
                or result.repository != self.scope.repository
                or result.state != "succeeded"
            ):
                raise SiteWorkspaceOutcomeUnknown(
                    "GitHub adapter returned an unbound result"
                )
            provider_effect = _digest(result.effect_digest, "effect_digest")
            effect = _sha(
                {
                    "schema": "OnyxGitHubEffect.v1",
                    "plan_digest": plan.plan_digest,
                    "provider_operation_id": _identifier(
                        result.provider_operation_id, "provider_operation_id"
                    ),
                    "provider_effect_digest": provider_effect,
                }
            )
        except BaseException as exc:
            self._set_intent(
                plan.intent_id,
                status=SiteIntentStatusV1.UNKNOWN,
                result={"reason": type(exc).__name__},
            )
            raise SiteWorkspaceOutcomeUnknown(
                "GitHub outcome requires reconciliation"
            ) from exc
        self._set_intent(
            plan.intent_id,
            status=SiteIntentStatusV1.SUCCEEDED,
            result={"effect_digest": effect},
        )
        return self._receipt(plan, outcome="github_verified", effect_digest=effect)

    def reconcile_github(self, plan: SiteOperationPlanV1) -> SiteEffectReceiptV1:
        row = self._validate_plan(plan, require_pending=False)
        if str(row["status"]) == SiteIntentStatusV1.SUCCEEDED.value:
            return self.get_receipt(plan.intent_id)
        if (
            str(row["status"]) != SiteIntentStatusV1.UNKNOWN.value
            or self._github_adapter is None
            or getattr(self._github_adapter, "official_adapter_id", None)
            != "onyx.github.official.v1"
        ):
            raise SiteWorkspaceDenied("GitHub operation is not reconcilable")
        result = self._github_adapter.reconcile(
            intent_id=plan.intent_id, plan_digest=plan.plan_digest
        )
        if result is None:
            raise SiteWorkspaceOutcomeUnknown("GitHub outcome remains unknown")
        if (
            type(result) is not GitHubExecutionResultV1
            or result.repository != self.scope.repository
            or result.state != "succeeded"
        ):
            raise SiteWorkspaceOutcomeUnknown("GitHub reconciliation remains unbound")
        provider_effect = _digest(result.effect_digest, "effect_digest")
        effect = _sha(
            {
                "schema": "OnyxGitHubEffect.v1",
                "plan_digest": plan.plan_digest,
                "provider_operation_id": _identifier(
                    result.provider_operation_id, "provider_operation_id"
                ),
                "provider_effect_digest": provider_effect,
            }
        )
        self._set_intent(
            plan.intent_id,
            status=SiteIntentStatusV1.SUCCEEDED,
            result={"effect_digest": effect, "reconciled": True},
        )
        return self._receipt(plan, outcome="github_reconciled", effect_digest=effect)


__all__ = [
    "ABSENT_DIGEST",
    "ALLOWED_EXTENSIONS",
    "FEATURE_FLAG",
    "GitExecutionResultV1",
    "GitHubExecutionResultV1",
    "GitHubOperationV1",
    "GitOperationV1",
    "GovernedSiteWorkspaceV1",
    "OwnerApprovalRequestV1",
    "SiteDraftV1",
    "SiteEffectReceiptV1",
    "SiteFilePageV1",
    "SiteFileV1",
    "SiteIntentStatusV1",
    "SiteOperationPlanV1",
    "SiteOwnerApprovalCapabilityV1",
    "SitePreviewPlanV1",
    "SiteWorkspaceContractError",
    "SiteWorkspaceDenied",
    "SiteWorkspaceError",
    "SiteWorkspaceFeatureGateV1",
    "SiteWorkspaceOutcomeUnknown",
    "SiteWorkspaceScopeV1",
]
