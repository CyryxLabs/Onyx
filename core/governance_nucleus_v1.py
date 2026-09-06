"""Durable live governance authority for Onyx V16.

This successor composes the accepted Phase 4/5 contracts without changing
their frozen implementations.  It owns the live workspace/session identity,
an authenticated append-only action ledger, exact bounded low-risk grants, the
trusted approval-inbox callback, truthful capability projections, and the
global mutation kill latch.

The module never dispatches a provider.  Capability Nexus dispatch remains the
existing provider-free ``local_catalog_read`` path owned by
``Phase5IntegrationV3``.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import threading
import time
import weakref
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Final, Iterator, Protocol

from core import approval_inbox_v15 as inbox_v15
from core import native_vault
from core import session_grants_v11 as grants_v11
from core.control_plane import _reject_link_chain
from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1
from core.workspaces import WorkspaceRecord


SCHEMA_VERSION: Final = 1
POLICY_VERSION: Final = "governance-live-v1"
DEFAULT_WORKSPACE_ID: Final = "onyx-local-workspace"
DEFAULT_WORKSPACE_DISPLAY: Final = "Onyx Local Workspace"
DEFAULT_PRINCIPAL_ID: Final = "onyx-owner"
DEFAULT_ACCOUNT_ID: Final = "cyryx-local-account"
DEFAULT_PROFILE_ID: Final = "onyx-owner-profile"
DEFAULT_GRANT_TTL_MS: Final = 15 * 60 * 1000
DEFAULT_GRANT_MAX_USES: Final = 8
MAX_EVENTS: Final = 250_000
MAX_PENDING: Final = 512
DOWNGRADE_RECEIPT_TTL_MS: Final = 10 * 60 * 1000
DOWNGRADE_RECEIPT_SERVICE: Final = "Onyx.GovernanceV16"
DOWNGRADE_RECEIPT_ACCOUNT: Final = "owner-downgrade-receipt"
DOWNGRADE_SIGNING_ACCOUNT: Final = "owner-downgrade-signing-key"
DOWNGRADE_TARGETS: Final = frozenset({"v15", "v14", "rollback"})
ZERO_HMAC: Final = "0" * 64
EMPTY_ATTACHMENT_DIGEST: Final = hashlib.sha256(
    b'{"attachments":[],"contract":"GovernanceAttachmentSet.v1"}'
).hexdigest()

_ID = re.compile(r"[a-z][a-z0-9-]{2,127}\Z")
_CAPABILITY_OPERATION = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SECRET_FIELD = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|"
    r"authorization|cookie|credential)",
    re.IGNORECASE,
)
_INVOCATION: contextvars.ContextVar[str] = contextvars.ContextVar(
    "onyx_governance_invocation_v1", default=""
)


class GovernanceV1Error(RuntimeError):
    """The live governance authority could not complete an operation."""


class GovernanceV1ContractError(ValueError):
    """An input is outside the exact V1 governance contract."""


class GovernanceV1IntegrityError(GovernanceV1Error):
    """Durable governance state failed authentication."""


class GovernanceV1Denied(PermissionError):
    """The requested action is not authorized by current governance state."""


class SecretVaultV1(Protocol):
    def get_bytes(self) -> bytes | None: ...

    def set_bytes(self, value: bytes | bytearray) -> None: ...

    def delete(self) -> bool: ...


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GovernanceV1ContractError("value is not canonical JSON") from exc


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise GovernanceV1ContractError(f"{label} is not a canonical identifier")
    return value


def _capability_operation(value: object) -> str:
    # Operation namespaces are not identity IDs. Concrete ports declare dotted
    # names (execute.test.echo) and underscores; the host still enforces its
    # exact constructor-closed registry and argument/policy digest binding.
    if type(value) is not str or not 3 <= len(value) <= 128 or _CAPABILITY_OPERATION.fullmatch(value) is None:
        raise GovernanceV1ContractError("operation is not a canonical capability operation")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise GovernanceV1ContractError(f"{label} is not a SHA-256 digest")
    return value


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _safe_arguments(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or len(value) > 128:
        raise GovernanceV1ContractError("action arguments are invalid")
    result: dict[str, object] = {}
    nodes = 0

    def visit(item: object, *, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if nodes > 2048 or depth > 8:
            raise GovernanceV1ContractError("action arguments exceed bounds")
        if isinstance(item, Mapping):
            if len(item) > 128:
                raise GovernanceV1ContractError("action argument mapping is too large")
            output: dict[str, object] = {}
            for raw_key, child in item.items():
                if type(raw_key) is not str or not raw_key or len(raw_key) > 128:
                    raise GovernanceV1ContractError("action argument key is invalid")
                if _SECRET_FIELD.search(raw_key):
                    # Secrets may be used by the tool through its own credential
                    # boundary, but never copied into the governance ledger.
                    output[raw_key] = "<redacted>"
                else:
                    output[raw_key] = visit(child, depth=depth + 1)
            return output
        if isinstance(item, (tuple, list)):
            if len(item) > 256:
                raise GovernanceV1ContractError("action argument list is too large")
            return [visit(child, depth=depth + 1) for child in item]
        if item is None or type(item) in {bool, int, float}:
            return item
        if type(item) is str:
            if len(item.encode("utf-8")) > 16_384:
                raise GovernanceV1ContractError("action argument string is too large")
            return item
        raise GovernanceV1ContractError("action argument type is unsupported")

    for key, item in value.items():
        if type(key) is not str:
            raise GovernanceV1ContractError("action argument key is invalid")
        result[key] = visit(item, depth=0)
    return result


def _summary(value: Mapping[str, object]) -> str:
    names = sorted(str(key) for key in value if not _SECRET_FIELD.search(str(key)))
    text = "fields:" + ",".join(names[:12])
    return text[:240] or "no public fields"


@dataclass(frozen=True, slots=True)
class GovernanceIdentityV1:
    principal_id: str
    workspace_id: str
    account_id: str
    profile_id: str
    workspace_display: str = DEFAULT_WORKSPACE_DISPLAY

    def __post_init__(self) -> None:
        for name in ("principal_id", "workspace_id", "account_id", "profile_id"):
            _identifier(getattr(self, name), name)
        if (
            type(self.workspace_display) is not str
            or not self.workspace_display.strip()
            or self.workspace_display != self.workspace_display.strip()
            or len(self.workspace_display) > 160
        ):
            raise GovernanceV1ContractError("workspace_display is invalid")

    @property
    def digest(self) -> str:
        return _sha({"contract": "GovernanceIdentity.v1", **asdict(self)})


@dataclass(frozen=True, slots=True)
class SessionCapabilityV1:
    session_id: str
    principal_id: str
    workspace_id: str
    account_id: str
    profile_id: str
    generation: int
    issued_at_ms: int
    capability_hmac: str

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "principal_id",
            "workspace_id",
            "account_id",
            "profile_id",
        ):
            _identifier(getattr(self, name), name)
        if type(self.generation) is not int or self.generation < 1:
            raise GovernanceV1ContractError("session generation is invalid")
        if type(self.issued_at_ms) is not int or self.issued_at_ms < 0:
            raise GovernanceV1ContractError("session timestamp is invalid")
        _digest(self.capability_hmac, "capability_hmac")

    def unsigned_payload(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("capability_hmac")
        return value


@dataclass(frozen=True, slots=True)
class ToolPolicyV1:
    tool: str
    operation: str
    provider: str
    provider_namespace: str
    account_id: str
    capability: str
    risk: str
    always_explicit: bool
    data_class: str
    egress: str
    health: str

    def __post_init__(self) -> None:
        for name in (
            "tool",
            "operation",
            "provider",
            "provider_namespace",
            "account_id",
            "capability",
            "health",
        ):
            _identifier(getattr(self, name), name)
        if self.risk not in {"low", "medium", "high", "critical"}:
            raise GovernanceV1ContractError("policy risk is invalid")
        if type(self.always_explicit) is not bool:
            raise GovernanceV1ContractError("always_explicit must be bool")
        if self.data_class not in {"public", "internal", "confidential", "restricted"}:
            raise GovernanceV1ContractError("data_class is invalid")
        if self.egress not in {"none", "internal", "external"}:
            raise GovernanceV1ContractError("egress is invalid")
        # Reuse the accepted Phase 5 policy contract as the lower-level
        # validation boundary. Governance V1 only adds live ownership around it.
        grants_v11.HostActionPolicy(
            self.capability,
            self.tool,
            self.operation,
            self.risk,
            self.always_explicit,
            self.data_class,
        )


@dataclass(frozen=True, slots=True)
class ActionBindingV1:
    action_id: str
    invocation_id: str
    principal_id: str
    workspace_id: str
    session_id: str
    provider: str
    provider_namespace: str
    account_id: str
    capability: str
    tool: str
    operation: str
    target_digest: str
    payload_digest: str
    payload_summary: str
    idempotency_key: str
    accepted_binding_digest: str
    risk: str
    always_explicit: bool
    data_class: str
    egress: str
    created_at_ms: int
    expires_at_ms: int

    def __post_init__(self) -> None:
        for name in (
            "action_id",
            "invocation_id",
            "principal_id",
            "workspace_id",
            "session_id",
            "provider",
            "provider_namespace",
            "account_id",
            "capability",
            "tool",
            "operation",
            "idempotency_key",
        ):
            _identifier(getattr(self, name), name)
        _digest(self.target_digest, "target_digest")
        _digest(self.payload_digest, "payload_digest")
        _digest(self.accepted_binding_digest, "accepted_binding_digest")
        if (
            type(self.payload_summary) is not str
            or not self.payload_summary
            or len(self.payload_summary) > 240
        ):
            raise GovernanceV1ContractError("payload_summary is invalid")
        if self.risk not in {"low", "medium", "high", "critical"}:
            raise GovernanceV1ContractError("action risk is invalid")
        if type(self.always_explicit) is not bool:
            raise GovernanceV1ContractError("always_explicit must be bool")
        if self.data_class not in {"public", "internal", "confidential", "restricted"}:
            raise GovernanceV1ContractError("action data_class is invalid")
        if self.egress not in {"none", "internal", "external"}:
            raise GovernanceV1ContractError("action egress is invalid")
        if (
            type(self.created_at_ms) is not int
            or type(self.expires_at_ms) is not int
            or self.created_at_ms < 0
            or self.expires_at_ms <= self.created_at_ms
        ):
            raise GovernanceV1ContractError("action lifetime is invalid")

    @property
    def digest(self) -> str:
        return _sha({"contract": "GovernanceActionBinding.v1", **asdict(self)})

    @property
    def grant_scope_digest(self) -> str:
        """Exact reusable scope excluding only invocation/time identities."""
        payload = asdict(self)
        for name in (
            "action_id",
            "invocation_id",
            "created_at_ms",
            "expires_at_ms",
        ):
            payload.pop(name)
        return _sha({"contract": "GovernanceGrantScope.v1", **payload})


@dataclass(frozen=True, slots=True)
class GrantRecordV1:
    grant_id: str
    binding_digest: str
    principal_id: str
    workspace_id: str
    session_id: str
    provider: str
    account_id: str
    tool: str
    operation: str
    issued_at_ms: int
    expires_at_ms: int
    max_uses: int
    used: int = 0
    revoked_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PendingApprovalV1:
    item_id: str
    request_digest: str
    binding: ActionBindingV1
    reason: str


@dataclass(frozen=True, slots=True)
class GovernanceEventV1:
    sequence: int
    event_type: str
    entity_id: str
    workspace_id: str
    payload: dict[str, object]
    previous_hmac: str
    event_hmac: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class GovernanceStatusV1:
    available: bool
    killed: bool
    principal_id: str
    workspace_id: str
    session_id: str | None
    session_generation: int
    ledger_sequence: int
    pending_approvals: int
    active_grants: int
    attempted_unknown: int
    capability_count: int
    limitations: tuple[str, ...]
    kill_propagation: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class GovernanceCommitFenceV1:
    fence_id: str
    session_id: str
    workspace_id: str
    session_generation: int

    def __post_init__(self) -> None:
        _identifier(self.fence_id, "fence_id")
        _identifier(self.session_id, "session_id")
        _identifier(self.workspace_id, "workspace_id")
        if type(self.session_generation) is not int or self.session_generation < 1:
            raise GovernanceV1ContractError("commit fence generation is invalid")


_POLICIES: Final[tuple[ToolPolicyV1, ...]] = (
    ToolPolicyV1(
        "system-status", "read", "onyx-local", "local-system",
        DEFAULT_ACCOUNT_ID, "system-observation", "low", False, "internal",
        "none", "available",
    ),
    ToolPolicyV1(
        "memory-search", "read", "onyx-local", "local-memory",
        DEFAULT_ACCOUNT_ID, "memory-read", "low", False, "confidential",
        "none", "available",
    ),
    ToolPolicyV1(
        "weather-report", "read", "open-meteo", "public-weather-api",
        "public-anonymous", "weather-read", "low", False, "public",
        "external", "configured-unverified",
    ),
    ToolPolicyV1(
        "web-search", "read", "google-gemini", "google-search-grounding",
        DEFAULT_ACCOUNT_ID, "public-web-search", "low", False, "public",
        "external", "configured-unverified",
    ),
    ToolPolicyV1(
        "mission-status", "read", "onyx-local", "mission-store",
        DEFAULT_ACCOUNT_ID, "mission-read", "low", False, "internal",
        "none", "available",
    ),
    ToolPolicyV1(
        "founder-brief-read", "read", "onyx-local", "founder-snapshot-v1",
        DEFAULT_ACCOUNT_ID, "founder-brief-read", "low", False,
        "confidential", "none", "available",
    ),
    ToolPolicyV1(
        "document-intake-read", "read", "onyx-local", "document-intake-v1",
        DEFAULT_ACCOUNT_ID, "document-intake-read", "low", False,
        "confidential", "none", "available",
    ),
    ToolPolicyV1(
        "day-brief-read", "read", "microsoft-graph", "dayops-v19",
        DEFAULT_ACCOUNT_ID, "day-brief-read", "low", False,
        "confidential", "external", "configured-unverified",
    ),
    # Workspace file work the owner reviewed for autonomy (ADR-0061): these
    # are declared evaluable rather than always-explicit, but never "low", so
    # they can only be granted through the owner-autonomy evaluator, which
    # independently confirms the configured profile and root containment.
    # Deliberately absent, so they keep falling through to always-explicit:
    # `delete` (least reversible local action) and `organize_desktop`.
    *(
        ToolPolicyV1(
            "file-controller", operation, "onyx-local", "local-filesystem",
            DEFAULT_ACCOUNT_ID, "workspace-read", "medium", False,
            "confidential", "none", "available",
        )
        for operation in ("list", "read", "find", "info", "disk-usage", "largest")
    ),
    *(
        ToolPolicyV1(
            "file-controller", operation, "onyx-local", "local-filesystem",
            DEFAULT_ACCOUNT_ID, "workspace-write", "high", False,
            "confidential", "none", "available",
        )
        for operation in (
            "write", "create-file", "create-folder", "copy", "move", "rename",
        )
    ),
    # Routine local assistant work the owner already configured as autonomous
    # (`_AUTONOMOUS_TOOLS` in the broker).  Declared evaluable rather than
    # always-explicit so an interruption is not required for every reminder or
    # remembered note, but never "low", so the evaluator still confirms the
    # configured profile first.  Deliberately absent, so they keep asking:
    # send-message, shutdown-onyx, flight-finder and every mission mutation.
    *(
        ToolPolicyV1(
            tool, "execute", "onyx-local", "local-assistant",
            DEFAULT_ACCOUNT_ID, "assistant-action", risk, False,
            "confidential", "none", "available",
        )
        for tool, risk in (
            ("save-memory", "medium"),
            ("reminder", "medium"),
            ("screen-process", "medium"),
            ("open-app", "high"),
        )
    ),
)

_ALWAYS_EXPLICIT_TOOLS: Final = frozenset(
    {
        "open-app",
        "send-message",
        "reminder",
        "screen-process",
        "flight-finder",
        "shutdown-onyx",
        "save-memory",
        "mission-create",
        "mission-cancel",
        "mission-reconcile",
        "mission-external-agent-cleanup",
        "mission-resume",
    }
)

# Owner scope decision, 2026-08-21: Onyx acts freely across the owner's own
# machine — opening, reading, writing, creating, organising — and the standing
# restriction is that operating-system and installed-program files are never
# altered without an explicit approval.  These tools are therefore declared
# evaluable rather than always-explicit; the owner-autonomy evaluator still
# runs, and for file work it refuses any target inside a protected system root.
#
# Deliberately NOT here, and still always-explicit:
#   send-message      outward-facing communication on the owner's behalf
#   shutdown-onyx     ends the session that would be needed to intervene
#   dev-agent         executes arbitrary code, so no path rule can hold the
#                     system-file restriction the owner asked for
#   mission-*         creates or cancels long-running autonomous work
_OWNER_EVALUABLE_TOOLS: Final = frozenset(
    {
        "file-controller",
        "file-processor",
        "browser-control",
        "computer-control",
        "desktop-control",
        "computer-settings",
        "code-helper",
        "youtube-video",
        "game-updater",
        "open-app",
        "save-memory",
        "reminder",
        "screen-process",
    }
)


def _tool_id(value: str) -> str:
    result = value.strip().casefold().replace("_", "-")
    return _identifier(result, "tool")


def _operation(tool: str, arguments: Mapping[str, object]) -> str:
    raw = arguments.get("action")
    if type(raw) is str and raw.strip():
        return _identifier(
            raw.strip().casefold().replace("_", "-").replace(" ", "-"),
            "operation",
        )
    return "read" if tool in {
        "system-status",
        "memory-search",
        "weather-report",
        "web-search",
        "mission-status",
        "founder-brief-read",
        "document-intake-read",
        "day-brief-read",
    } else "execute"


def _policy_for(
    tool_name: str, arguments: Mapping[str, object], account_id: str
) -> ToolPolicyV1:
    tool = _tool_id(tool_name)
    operation = _operation(tool, arguments)
    for policy in _POLICIES:
        if policy.tool == tool and policy.operation == operation:
            if policy.account_id == DEFAULT_ACCOUNT_ID:
                return replace(policy, account_id=account_id)
            return policy
    if tool in _OWNER_EVALUABLE_TOOLS:
        # Evaluable, never granted outright: the evaluator still confirms the
        # owner's configured profile, and refuses protected system paths.
        return ToolPolicyV1(
            tool,
            operation,
            "onyx-local",
            "local-owner-scope",
            account_id,
            "owner-scope-action",
            "high",
            False,
            "confidential",
            "internal",
            "available",
        )
    if tool in _ALWAYS_EXPLICIT_TOOLS:
        return ToolPolicyV1(
            tool,
            operation,
            "onyx-host",
            "trusted-local-ui",
            account_id,
            "host-confirmed-action",
            "high",
            True,
            "confidential",
            "external" if tool in {"send-message", "flight-finder"} else "internal",
            "available",
        )
    # Unknown and action-policy mutations remain structurally explicit.
    return ToolPolicyV1(
        tool,
        operation,
        "onyx-host",
        "trusted-local-ui",
        account_id,
        "host-confirmed-action",
        "high",
        True,
        "confidential",
        "internal",
        "available",
    )


class _GovernanceLedgerV1:
    """Authenticated append-only SQLite ledger with native-vault head anchor."""

    _SCHEMA = (
        "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
        "CREATE TABLE events("
        "sequence INTEGER PRIMARY KEY,event_type TEXT NOT NULL,"
        "entity_id TEXT NOT NULL,workspace_id TEXT NOT NULL,"
        "payload_json TEXT NOT NULL,previous_hmac TEXT NOT NULL,"
        "event_hmac TEXT NOT NULL UNIQUE,created_at_ms INTEGER NOT NULL)",
        "CREATE INDEX events_workspace_sequence ON events(workspace_id,sequence)",
        "CREATE INDEX events_entity_sequence ON events(entity_id,sequence)",
        "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
        "BEGIN SELECT RAISE(ABORT,'governance events are immutable'); END",
        "CREATE TRIGGER events_no_delete BEFORE DELETE ON events "
        "BEGIN SELECT RAISE(ABORT,'governance events are immutable'); END",
    )
    _EXPECTED_OBJECTS: Final = frozenset(
        {
            ("table", "metadata", "metadata"),
            ("table", "events", "events"),
            ("index", "events_workspace_sequence", "events"),
            ("index", "events_entity_sequence", "events"),
            ("trigger", "events_no_update", "events"),
            ("trigger", "events_no_delete", "events"),
        }
    )

    def __init__(
        self,
        path: Path,
        *,
        key_vault: SecretVaultV1,
        head_vault: SecretVaultV1,
        pending_vault: SecretVaultV1,
        trusted_directory_factory: Callable[..., object] | None = None,
        require_windows_boundary: bool | None = None,
        require_host_boundary: bool | None = None,
    ) -> None:
        self.path = Path(path)
        self.key_vault = key_vault
        self.head_vault = head_vault
        self.pending_vault = pending_vault
        self._key = b""
        self._lock = threading.RLock()
        self._trusted_directory_factory = (
            trusted_directory_factory or WindowsTrustedDirectoryV1
        )
        if require_windows_boundary is not None and require_host_boundary is not None:
            raise GovernanceV1ContractError(
                "governance boundary requirement is ambiguous"
            )
        self._require_host_boundary = (
            os.name == "nt"
            if require_windows_boundary is None and require_host_boundary is None
            else (
                require_windows_boundary is True
                if require_host_boundary is None
                else require_host_boundary is True
            )
        )
        self._require_windows_boundary = self._require_host_boundary
        self._trusted_directory: object | None = None
        self._descriptor_path: object | None = None
        self._connection: sqlite3.Connection | None = None
        self._connection_finalizer: weakref.finalize | None = None
        self._file_identity: tuple[int, int, int] | None = None
        self._storage_signature: tuple[tuple[str, int, int], ...] = ()
        self._verified_tail: tuple[int, str] = (0, ZERO_HMAC)
        self._data_version = 0

    def _prepare_root(self) -> None:
        if not self.path.is_absolute():
            raise GovernanceV1IntegrityError(
                "governance database path must be absolute"
            )
        try:
            if self._require_host_boundary:
                self._trusted_directory = self._trusted_directory_factory(
                    root=self.path.parent,
                    enabled=True,
                )
                if os.name != "nt":
                    from core.posix_trusted_directory_v1 import (
                        PosixDescriptorPathLeaseV1,
                        PosixTrustedDirectoryV1,
                    )

                    if type(self._trusted_directory) is not PosixTrustedDirectoryV1:
                        raise GovernanceV1IntegrityError(
                            "exact POSIX governance boundary is required"
                        )
                    with self._trusted_directory.session() as session:
                        descriptor_path = session.descriptor_path(self.path.name)
                    if type(descriptor_path) is not PosixDescriptorPathLeaseV1:
                        raise GovernanceV1IntegrityError(
                            "exact POSIX descriptor path is required"
                        )
                    self._descriptor_path = descriptor_path
            else:
                self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                _reject_link_chain(self.path.parent)
            if self.path.exists():
                info = self.path.lstat()
                if (
                    stat.S_ISLNK(info.st_mode)
                    or not stat.S_ISREG(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & 0x400
                ):
                    raise GovernanceV1IntegrityError(
                        "governance database is not a regular trusted file"
                    )
                _reject_link_chain(self.path)
        except GovernanceV1IntegrityError:
            raise
        except Exception as exc:
            raise GovernanceV1IntegrityError(
                "governance trusted directory is unavailable"
            ) from exc

    def close(self) -> None:
        with self._lock:
            connection, self._connection = self._connection, None
            finalizer, self._connection_finalizer = (
                self._connection_finalizer,
                None,
            )
            boundary, self._trusted_directory = self._trusted_directory, None
            descriptor_path, self._descriptor_path = self._descriptor_path, None
            try:
                if finalizer is not None and finalizer.alive:
                    finalizer()
                elif connection is not None:
                    connection.close()
            finally:
                try:
                    close_descriptor = getattr(descriptor_path, "close", None)
                    if callable(close_descriptor):
                        close_descriptor()
                finally:
                    close = getattr(boundary, "close", None)
                    if callable(close):
                        close()

    def _path_identity(self) -> tuple[int, int, int]:
        if os.name != "nt" and self._require_host_boundary:
            session = getattr(self._trusted_directory, "session", None)
            identity = getattr(self._descriptor_path, "identity", None)
            if not callable(session) or not callable(identity):
                raise GovernanceV1IntegrityError(
                    "governance descriptor identity is unavailable"
                )
            try:
                with session():
                    return identity()
            except Exception as exc:
                raise GovernanceV1IntegrityError(
                    "governance database identity is unavailable"
                ) from exc
        try:
            info = self.path.stat()
        except OSError as exc:
            raise GovernanceV1IntegrityError(
                "governance database identity is unavailable"
            ) from exc
        return (
            int(info.st_dev),
            int(info.st_ino),
            int(getattr(info, "st_birthtime_ns", 0)),
        )

    def _current_storage_signature(self) -> tuple[tuple[str, int, int], ...]:
        if os.name != "nt" and self._require_host_boundary:
            session = getattr(self._trusted_directory, "session", None)
            signature = getattr(self._descriptor_path, "storage_signature", None)
            validate = getattr(self._descriptor_path, "validate_sqlite_files", None)
            if (
                not callable(session)
                or not callable(signature)
                or not callable(validate)
            ):
                raise GovernanceV1IntegrityError(
                    "governance descriptor storage is unavailable"
                )
            try:
                with session():
                    validate()
                    return signature()
            except Exception as exc:
                raise GovernanceV1IntegrityError(
                    "governance storage signature is unavailable"
                ) from exc
        result: list[tuple[str, int, int]] = []
        for suffix in ("", "-wal"):
            candidate = Path(str(self.path) + suffix)
            try:
                info = candidate.stat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise GovernanceV1IntegrityError(
                    "governance storage signature is unavailable"
                ) from exc
            result.append((suffix, int(info.st_size), int(info.st_mtime_ns)))
        return tuple(result)

    def _connection_or_raise(self) -> sqlite3.Connection:
        connection = self._connection
        if connection is None:
            raise GovernanceV1IntegrityError("governance ledger is closed")
        return connection

    @staticmethod
    def _head_bytes(sequence: int, event_hmac: str) -> bytes:
        return _canonical(
            {
                "contract": "OnyxGovernanceHead.v1",
                "sequence": sequence,
                "event_hmac": event_hmac,
            }
        )

    def _event_hmac(
        self,
        sequence: int,
        event_type: str,
        entity_id: str,
        workspace_id: str,
        payload_json: str,
        previous: str,
        created_at_ms: int,
    ) -> str:
        return hmac.new(
            self._key,
            b"ONYX-GOVERNANCE-EVENT.v1\0"
            + _canonical(
                {
                    "sequence": sequence,
                    "event_type": event_type,
                    "entity_id": entity_id,
                    "workspace_id": workspace_id,
                    "payload_json": payload_json,
                    "previous_hmac": previous,
                    "created_at_ms": created_at_ms,
                }
            ),
            hashlib.sha256,
        ).hexdigest()

    def initialize(self) -> "_GovernanceLedgerV1":
        self._prepare_root()
        sqlite_path: str | Path = self.path
        if os.name != "nt" and self._require_host_boundary:
            prepare = getattr(self._descriptor_path, "prepare_sqlite_main", None)
            descriptor_name = getattr(self._descriptor_path, "path", None)
            if not callable(prepare) or not isinstance(descriptor_name, str):
                raise GovernanceV1IntegrityError(
                    "governance descriptor-bound sqlite is unavailable"
                )
            try:
                existing = bool(prepare())
                sqlite_path = descriptor_name
            except Exception as exc:
                raise GovernanceV1IntegrityError(
                    "governance descriptor-bound sqlite is unavailable"
                ) from exc
        else:
            existing = self.path.exists()
        key = self.key_vault.get_bytes()
        head = self.head_vault.get_bytes()
        pending = self.pending_vault.get_bytes()
        if not existing and any(value is not None for value in (key, head, pending)):
            raise GovernanceV1IntegrityError(
                "governance database is missing while durable vault state exists"
            )
        if existing and (key is None or head is None):
            raise GovernanceV1IntegrityError(
                "governance durable stores are incomplete"
            )
        if key is None:
            key = secrets.token_bytes(32)
            self.key_vault.set_bytes(key)
            key = self.key_vault.get_bytes()
        if type(key) is not bytes or len(key) != 32:
            raise GovernanceV1IntegrityError("governance key is invalid")
        self._key = key
        with self._lock:
            connection = sqlite3.connect(sqlite_path, check_same_thread=False)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=FULL")
                if not existing:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    for statement in self._SCHEMA:
                        connection.execute(statement)
                    connection.executemany(
                        "INSERT INTO metadata(key,value) VALUES(?,?)",
                        (
                            ("schema_version", str(SCHEMA_VERSION)),
                            ("policy_version", POLICY_VERSION),
                        ),
                    )
                    connection.commit()
                    self.head_vault.set_bytes(self._head_bytes(0, ZERO_HMAC))
                self._verify_schema(connection)
                self._recover_pending(connection)
                self._verify_chain(connection)
                self._connection = connection
                self._connection_finalizer = weakref.finalize(
                    self, connection.close
                )
                self._file_identity = self._path_identity()
                self._verified_tail = self._tail(connection)
                self._data_version = int(
                    connection.execute("PRAGMA data_version").fetchone()[0]
                )
                self._storage_signature = self._current_storage_signature()
            except BaseException:
                connection.close()
                raise
        return self

    def _verify_incremental(self, connection: sqlite3.Connection) -> None:
        if self._file_identity != self._path_identity():
            raise GovernanceV1IntegrityError(
                "governance database identity was replaced"
            )
        observed_version = int(
            connection.execute("PRAGMA data_version").fetchone()[0]
        )
        observed_signature = self._current_storage_signature()
        pending = self.pending_vault.get_bytes()
        if (
            pending is not None
            or observed_version != self._data_version
            or observed_signature != self._storage_signature
        ):
            self._verify_schema(connection)
            self._recover_pending(connection)
            self._verify_chain(connection)
            self._verified_tail = self._tail(connection)
            self._data_version = int(
                connection.execute("PRAGMA data_version").fetchone()[0]
            )
            self._storage_signature = self._current_storage_signature()
            return
        tail = self._tail(connection)
        if tail != self._verified_tail:
            raise GovernanceV1IntegrityError(
                "governance incremental tail diverges"
            )
        if self.head_vault.get_bytes() != self._head_bytes(*tail):
            raise GovernanceV1IntegrityError(
                "governance incremental head anchor diverges"
            )

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise GovernanceV1IntegrityError("governance schema version diverges")
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        if metadata != {
            "schema_version": str(SCHEMA_VERSION),
            "policy_version": POLICY_VERSION,
        }:
            raise GovernanceV1IntegrityError("governance metadata diverges")
        objects = {
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                "SELECT type,name,tbl_name FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        if objects != self._EXPECTED_OBJECTS:
            raise GovernanceV1IntegrityError(
                "governance sqlite schema objects diverge"
            )
        expected_connection = sqlite3.connect(":memory:")
        try:
            for statement in self._SCHEMA:
                expected_connection.execute(statement)
            expected_sql = {
                (str(row[0]), str(row[1])): " ".join(str(row[2]).split())
                for row in expected_connection.execute(
                    "SELECT type,name,sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%'"
                )
            }
        finally:
            expected_connection.close()
        observed_sql = {
            (str(row[0]), str(row[1])): " ".join(str(row[2]).split())
            for row in connection.execute(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        if observed_sql != expected_sql:
            raise GovernanceV1IntegrityError(
                "governance sqlite schema definitions diverge"
            )
        columns = tuple(
            (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
            for row in connection.execute("PRAGMA table_info(events)")
        )
        if columns != (
            ("sequence", "INTEGER", 0, 1),
            ("event_type", "TEXT", 1, 0),
            ("entity_id", "TEXT", 1, 0),
            ("workspace_id", "TEXT", 1, 0),
            ("payload_json", "TEXT", 1, 0),
            ("previous_hmac", "TEXT", 1, 0),
            ("event_hmac", "TEXT", 1, 0),
            ("created_at_ms", "INTEGER", 1, 0),
        ):
            raise GovernanceV1IntegrityError(
                "governance events table contract diverges"
            )

    def _tail(self, connection: sqlite3.Connection) -> tuple[int, str]:
        row = connection.execute(
            "SELECT sequence,event_hmac FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        return (0, ZERO_HMAC) if row is None else (int(row[0]), str(row[1]))

    def _recover_pending(self, connection: sqlite3.Connection) -> None:
        raw = self.pending_vault.get_bytes()
        if raw is None:
            return
        try:
            marker = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GovernanceV1IntegrityError("governance pending marker is corrupt") from exc
        if type(marker) is not dict or set(marker) != {
            "contract",
            "before_sequence",
            "before_hmac",
            "after_sequence",
            "after_hmac",
            "marker_hmac",
        }:
            raise GovernanceV1IntegrityError("governance pending marker is invalid")
        supplied = str(marker.pop("marker_hmac"))
        expected = hmac.new(
            self._key,
            b"ONYX-GOVERNANCE-PENDING.v1\0" + _canonical(marker),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise GovernanceV1IntegrityError("governance pending marker failed auth")
        before = int(marker["before_sequence"]), str(marker["before_hmac"])
        after = int(marker["after_sequence"]), str(marker["after_hmac"])
        tail = self._tail(connection)
        anchored_raw = self.head_vault.get_bytes()
        if anchored_raw is None:
            raise GovernanceV1IntegrityError("governance head is missing")
        before_head = self._head_bytes(*before)
        after_head = self._head_bytes(*after)
        if tail == after and anchored_raw == before_head:
            self.head_vault.set_bytes(self._head_bytes(*after))
        elif tail == after and anchored_raw == after_head:
            # Commit and anchor completed; only the crash-stale marker remains.
            pass
        elif tail != before or anchored_raw != before_head:
            raise GovernanceV1IntegrityError("governance pending recovery diverges")
        if (
            not self.pending_vault.delete()
            and self.pending_vault.get_bytes() is not None
        ):
            raise GovernanceV1IntegrityError("governance pending marker was not cleared")

    def _verify_chain(self, connection: sqlite3.Connection) -> None:
        previous = ZERO_HMAC
        sequence = 0
        for row in connection.execute(
            "SELECT sequence,event_type,entity_id,workspace_id,payload_json,"
            "previous_hmac,event_hmac,created_at_ms FROM events ORDER BY sequence"
        ):
            observed = int(row[0])
            if observed != sequence + 1 or str(row[5]) != previous:
                raise GovernanceV1IntegrityError("governance chain is discontinuous")
            expected = self._event_hmac(
                observed,
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                previous,
                int(row[7]),
            )
            if not hmac.compare_digest(str(row[6]), expected):
                raise GovernanceV1IntegrityError("governance event authentication failed")
            sequence, previous = observed, expected
        anchored = self.head_vault.get_bytes()
        if anchored != self._head_bytes(sequence, previous):
            raise GovernanceV1IntegrityError("governance head anchor diverges")

    def append(
        self,
        event_type: str,
        entity_id: str,
        workspace_id: str,
        payload: Mapping[str, object],
        *,
        enforce_unique_entity: bool = False,
    ) -> GovernanceEventV1:
        _identifier(event_type, "event_type")
        _identifier(entity_id, "entity_id")
        _identifier(workspace_id, "workspace_id")
        payload_json = _canonical(dict(payload)).decode("ascii")
        if len(payload_json) > 32_768:
            raise GovernanceV1ContractError("governance event is too large")
        with self._lock:
            connection = self._connection_or_raise()
            try:
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("BEGIN IMMEDIATE")
                if self.pending_vault.get_bytes() is not None:
                    raise GovernanceV1IntegrityError(
                        "governance pending marker must be recovered before append"
                    )
                self._verify_incremental(connection)
                if enforce_unique_entity and connection.execute(
                    "SELECT 1 FROM events WHERE event_type=? AND entity_id=? "
                    "LIMIT 1",
                    (event_type, entity_id),
                ).fetchone() is not None:
                    raise GovernanceV1Denied(
                        "governance event identity was already consumed"
                    )
                prior_sequence, prior_hmac = self._tail(connection)
                if prior_sequence >= MAX_EVENTS:
                    raise GovernanceV1Error("governance ledger capacity reached")
                sequence = prior_sequence + 1
                created = _now_ms()
                event_hmac = self._event_hmac(
                    sequence,
                    event_type,
                    entity_id,
                    workspace_id,
                    payload_json,
                    prior_hmac,
                    created,
                )
                marker = {
                    "contract": "OnyxGovernancePending.v1",
                    "before_sequence": prior_sequence,
                    "before_hmac": prior_hmac,
                    "after_sequence": sequence,
                    "after_hmac": event_hmac,
                }
                marker["marker_hmac"] = hmac.new(
                    self._key,
                    b"ONYX-GOVERNANCE-PENDING.v1\0" + _canonical(marker),
                    hashlib.sha256,
                ).hexdigest()
                self.pending_vault.set_bytes(_canonical(marker))
                connection.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?,?,?,?)",
                    (
                        sequence,
                        event_type,
                        entity_id,
                        workspace_id,
                        payload_json,
                        prior_hmac,
                        event_hmac,
                        created,
                    ),
                )
                connection.commit()
                self.head_vault.set_bytes(self._head_bytes(sequence, event_hmac))
                if (
                    not self.pending_vault.delete()
                    and self.pending_vault.get_bytes() is not None
                ):
                    raise GovernanceV1IntegrityError(
                        "governance pending marker was not cleared"
                    )
                self._verified_tail = (sequence, event_hmac)
                self._data_version = int(
                    connection.execute("PRAGMA data_version").fetchone()[0]
                )
                self._storage_signature = self._current_storage_signature()
                return GovernanceEventV1(
                    sequence,
                    event_type,
                    entity_id,
                    workspace_id,
                    json.loads(payload_json),
                    prior_hmac,
                    event_hmac,
                    created,
                )
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise

    def has_durable_event(self, event_type: str, entity_id: str) -> bool:
        """Read an authenticated tail even when pending-marker cleanup failed."""
        _identifier(event_type, "event_type")
        _identifier(entity_id, "entity_id")
        with self._lock:
            connection = self._connection_or_raise()
            try:
                connection.execute("BEGIN")
                if self.pending_vault.get_bytes() is None:
                    self._verify_incremental(connection)
                else:
                    # This reader is used immediately after an append cleanup
                    # failure to establish whether the committed+anchored kill
                    # event is durable. Do not clear the marker in-process:
                    # later writes must remain blocked until a clean reopen.
                    self._verify_schema(connection)
                    self._verify_chain(connection)
                return connection.execute(
                    "SELECT 1 FROM events WHERE event_type=? AND entity_id=? "
                    "LIMIT 1",
                    (event_type, entity_id),
                ).fetchone() is not None
            finally:
                if connection.in_transaction:
                    connection.rollback()

    def latest_durable_event(
        self, event_types: tuple[str, ...], entity_id: str
    ) -> GovernanceEventV1 | None:
        """Return the authenticated latest event for one bounded lifecycle."""

        if (
            type(event_types) is not tuple
            or not event_types
            or len(event_types) > 8
        ):
            raise GovernanceV1ContractError("event type set is invalid")
        normalized = tuple(_identifier(value, "event_type") for value in event_types)
        if len(set(normalized)) != len(normalized):
            raise GovernanceV1ContractError("event type set contains duplicates")
        entity = _identifier(entity_id, "entity_id")
        placeholders = ",".join("?" for _value in normalized)
        with self._lock:
            connection = self._connection_or_raise()
            try:
                connection.execute("BEGIN")
                self._verify_incremental(connection)
                row = connection.execute(
                    "SELECT sequence,event_type,entity_id,workspace_id,"
                    "payload_json,previous_hmac,event_hmac,created_at_ms "
                    f"FROM events WHERE entity_id=? AND event_type IN ({placeholders}) "
                    "ORDER BY sequence DESC LIMIT 1",
                    (entity, *normalized),
                ).fetchone()
                connection.commit()
                if row is None:
                    return None
                return GovernanceEventV1(
                    int(row[0]),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    json.loads(str(row[4])),
                    str(row[5]),
                    str(row[6]),
                    int(row[7]),
                )
            finally:
                if connection.in_transaction:
                    connection.rollback()

    def _read_events(self, workspace_id: str | None) -> tuple[GovernanceEventV1, ...]:
        with self._lock:
            connection = self._connection_or_raise()
            try:
                connection.execute("BEGIN")
                self._verify_incremental(connection)
                query = (
                    "SELECT sequence,event_type,entity_id,workspace_id,"
                    "payload_json,previous_hmac,event_hmac,created_at_ms "
                    "FROM events ORDER BY sequence"
                    if workspace_id is None
                    else
                    "SELECT sequence,event_type,entity_id,workspace_id,"
                    "payload_json,previous_hmac,event_hmac,created_at_ms "
                    "FROM events WHERE workspace_id=? ORDER BY sequence"
                )
                parameters = () if workspace_id is None else (workspace_id,)
                result = tuple(
                    GovernanceEventV1(
                        int(row[0]),
                        str(row[1]),
                        str(row[2]),
                        str(row[3]),
                        json.loads(str(row[4])),
                        str(row[5]),
                        str(row[6]),
                        int(row[7]),
                    )
                    for row in connection.execute(query, parameters)
                )
                connection.commit()
                return result
            finally:
                if connection.in_transaction:
                    connection.rollback()

    def events(self, workspace_id: str) -> tuple[GovernanceEventV1, ...]:
        return self._read_events(_identifier(workspace_id, "workspace_id"))

    def _events_global(self) -> tuple[GovernanceEventV1, ...]:
        return self._read_events(None)


class GovernanceApprovalInboxAuthorityV1:
    """The sole V16 approve/deny/revoke UI authority."""

    def __init__(self, owner: "GovernanceNucleusV1") -> None:
        self._owner = owner
        self._trusted_callback: Callable[[dict], str | None] | None = None

    def wrap(
        self, callback: Callable[[dict], str | None]
    ) -> Callable[[dict], str | None]:
        if not callable(callback):
            raise GovernanceV1ContractError("trusted approval callback is required")
        if getattr(callback, "_onyx_governance_inbox_v1", None) is not None:
            raise GovernanceV1ContractError(
                "trusted approval callback is already governance wrapped"
            )
        if (
            self._trusted_callback is not None
            and self._trusted_callback is not callback
        ):
            raise GovernanceV1ContractError(
                "trusted approval callback authority is already bound"
            )
        self._trusted_callback = callback

        def decide(request: dict) -> str | None:
            return self._owner._explicit_decision(request, callback)

        setattr(decide, "_onyx_governance_inbox_v1", self)
        return decide

    def _decide_trusted(self, request: dict) -> str | None:
        callback = self._trusted_callback
        if callback is None:
            raise GovernanceV1Denied("trusted approval UI is unavailable")
        return self._owner._explicit_decision(request, callback)

    def revoke_grant(self, grant_id: str) -> None:
        self._owner._revoke_grant(grant_id, "owner-revoke")


class GovernanceDashboardFacadeV1:
    """One read/kill facade for both Phase 5 and Governance V1."""

    def __init__(
        self,
        nucleus: "GovernanceNucleusV1",
        phase5: object | None,
        phase11: object | None,
        mission_worker: object | None = None,
    ) -> None:
        self._nucleus = nucleus
        self._phase5 = phase5
        self._phase11 = phase11
        self._mission_worker = mission_worker

    def status_payload(self) -> dict[str, object]:
        return self._nucleus.status_payload()

    def dashboard_read(
        self, surface: str, *, offset: int = 0, page_size: int = 50
    ) -> dict[str, object]:
        return self._nucleus.dashboard_read(
            surface,
            offset=offset,
            page_size=page_size,
            phase5=self._phase5,
        )

    def kill(self) -> dict[str, object]:
        return self._nucleus.global_kill(
            phase5=self._phase5,
            phase11=self._phase11,
            mission_worker=self._mission_worker,
        )

    def revoke_grant(self, grant_id: str) -> None:
        self._nucleus.approval_inbox.revoke_grant(grant_id)


class GovernanceNucleusV1:
    """Live authority composed before any model/provider session is opened."""

    # Owner autonomy is evaluated, never assumed.  Absent an installed
    # evaluator the hook behaves exactly as it always has: only exact low-risk
    # reads are granted, and everything else defers to the owner.
    _owner_autonomy_evaluator: object | None = None

    def __init__(
        self,
        *,
        path: Path,
        identity: GovernanceIdentityV1,
        key_vault: SecretVaultV1 | None = None,
        head_vault: SecretVaultV1 | None = None,
        pending_vault: SecretVaultV1 | None = None,
        trusted_directory_factory: Callable[..., object] | None = None,
        require_windows_boundary: bool | None = None,
        require_host_boundary: bool | None = None,
        workspace_records: tuple[WorkspaceRecord, ...] = (),
    ) -> None:
        if type(identity) is not GovernanceIdentityV1:
            raise GovernanceV1ContractError("exact governance identity is required")
        self.identity = identity
        if type(workspace_records) is not tuple or any(
            type(item) is not WorkspaceRecord for item in workspace_records
        ):
            raise GovernanceV1ContractError(
                "exact WorkspaceRegistry records are required"
            )
        if not workspace_records:
            workspace_records = (
                WorkspaceRecord(
                    identity.workspace_id,
                    identity.workspace_display,
                    "personal",
                    "active",
                    1,
                    "governance-v1",
                    "governance-v1",
                ),
            )
        if (
            len({item.workspace_id for item in workspace_records})
            != len(workspace_records)
            or any(item.status != "active" for item in workspace_records)
        ):
            raise GovernanceV1ContractError(
                "WorkspaceRegistry records must be unique and active"
            )
        primary = next(
            (
                item
                for item in workspace_records
                if item.workspace_id == identity.workspace_id
            ),
            None,
        )
        if primary is None or primary.display_name != identity.workspace_display:
            raise GovernanceV1ContractError(
                "active workspace identity is absent from WorkspaceRegistry"
            )
        self.workspace_records = workspace_records
        self._lock = threading.RLock()
        self._session: SessionCapabilityV1 | None = None
        self._grants: dict[str, GrantRecordV1] = {}
        self._actions: dict[str, ActionBindingV1] = {}
        self._action_states: dict[str, str] = {}
        self._invocations: dict[str, str] = {}
        self._pending: dict[str, PendingApprovalV1] = {}
        self._session_generation = 0
        self._killed = False
        self._kill_propagation: dict[str, str] = {}
        self._source_epoch = 0
        self._approval_inbox = GovernanceApprovalInboxAuthorityV1(self)
        key_vault = key_vault or native_vault.NativeSecretVault(
            native_vault.SecretReference(
                "Onyx.GovernanceV1", "ledger-key",
                "Onyx Governance V1 ledger authentication key",
            )
        )
        head_vault = head_vault or native_vault.NativeSecretVault(
            native_vault.SecretReference(
                "Onyx.GovernanceV1", "ledger-head",
                "Onyx Governance V1 ledger head",
            )
        )
        pending_vault = pending_vault or native_vault.NativeSecretVault(
            native_vault.SecretReference(
                "Onyx.GovernanceV1", "ledger-pending",
                "Onyx Governance V1 pending commit",
            )
        )
        ledger = _GovernanceLedgerV1(
            Path(path),
            key_vault=key_vault,
            head_vault=head_vault,
            pending_vault=pending_vault,
            trusted_directory_factory=trusted_directory_factory,
            require_windows_boundary=require_windows_boundary,
            require_host_boundary=require_host_boundary,
        )
        try:
            self._ledger = ledger.initialize()
        except BaseException:
            ledger.close()
            raise
        self._key = key_vault.get_bytes()
        if type(self._key) is not bytes or len(self._key) != 32:
            raise GovernanceV1IntegrityError("governance key readback failed")
        self._restore()
        self._ensure_workspaces()
        self._inbox_session_id = "governance-session"
        self._inbox_projection = self._new_inbox_projection(
            self._inbox_session_id
        )

    def _new_inbox_projection(
        self, session_id: str
    ) -> inbox_v15.ApprovalInboxProjectionV15:
        source = inbox_v15.HostInboxSourceV15(
            principal_id=self.identity.principal_id,
            session_id=session_id,
            capture_callback=self._capture_inbox,
        )
        return inbox_v15.ApprovalInboxProjectionV15(
            gate=inbox_v15.ApprovalInboxFeatureGateV15(
                environ={inbox_v15.APPROVAL_INBOX_V15_FLAG: "true"},
                epoch_reader=lambda: 1,
            ),
            source=source,
            clock=inbox_v15.MonotonicInboxClockV15(),
        )

    def _reset_inbox_projection(self, session_id: str) -> None:
        self._inbox_session_id = session_id
        self._inbox_projection = self._new_inbox_projection(session_id)

    @property
    def approval_inbox(self) -> GovernanceApprovalInboxAuthorityV1:
        return self._approval_inbox

    @property
    def killed(self) -> bool:
        with self._lock:
            return self._killed

    def close(self) -> None:
        try:
            self.end_session("shutdown")
        finally:
            self._ledger.close()

    def _restore(self) -> None:
        for event in self._ledger._events_global():
            payload = event.payload
            if event.event_type == "global-kill-latched":
                self._killed = True
                continue
            if event.event_type == "global-kill-released":
                if (
                    payload.get("principal_id") != self.identity.principal_id
                    or payload.get("identity_digest") != self.identity.digest
                    or type(payload.get("released_latch_sequence")) is not int
                ):
                    raise GovernanceV1IntegrityError(
                        "global kill release identity is invalid"
                    )
                self._killed = False
                self._kill_propagation.clear()
                continue
            if event.event_type == "global-kill-propagation":
                subsystem = str(payload.get("subsystem", ""))
                status = str(payload.get("status", ""))
                if subsystem and status:
                    self._kill_propagation[subsystem] = status
                continue
            if event.event_type == "workspace-registered":
                continue
            if event.workspace_id != self.identity.workspace_id:
                continue
            if event.event_type == "session-started":
                self._session_generation = max(
                    self._session_generation, int(payload["generation"])
                )
            elif event.event_type == "session-ended":
                if (
                    self._session is not None
                    and self._session.session_id == event.entity_id
                ):
                    self._session = None
            elif event.event_type == "grant-issued":
                grant = GrantRecordV1(**payload)
                self._grants[grant.grant_id] = grant
            elif event.event_type == "grant-used":
                grant_id = str(payload["grant_id"])
                prior = self._grants.get(grant_id)
                if prior is not None:
                    self._grants[grant_id] = replace(
                        prior, used=int(payload["used"])
                    )
            elif event.event_type == "grant-revoked":
                grant_id = str(payload["grant_id"])
                prior = self._grants.get(grant_id)
                if prior is not None:
                    self._grants[grant_id] = replace(
                        prior, revoked_reason=str(payload["reason"])
                    )
            elif event.event_type == "action-intent":
                raw = payload.get("binding")
                if type(raw) is dict:
                    binding = ActionBindingV1(**raw)
                    self._actions[binding.action_id] = binding
                    self._invocations[binding.invocation_id] = binding.action_id
                    self._action_states[binding.action_id] = "intent"
            elif event.event_type in {
                "action-approved",
                "action-denied",
                "action-receipt",
                "action-attempted-unknown",
                "action-late-blocked",
                "action-approval-failed",
            }:
                self._action_states[event.entity_id] = event.event_type.removeprefix(
                    "action-"
                )
            elif event.event_type == "governance-audit-failed":
                self._action_states[event.entity_id] = "audit-failed"
        # An approval is the last durable boundary before host dispatch. If a
        # process disappears without a terminal receipt, execution may or may
        # not have happened. Reconcile that crash window once, durably and
        # fail-closed; it must never be inferred as success or retried.
        for action_id, state in tuple(self._action_states.items()):
            if state != "approved":
                continue
            binding = self._actions.get(action_id)
            if binding is None:
                raise GovernanceV1IntegrityError(
                    "approved action binding is unavailable"
                )
            self._ledger.append(
                "action-attempted-unknown",
                action_id,
                binding.workspace_id,
                {
                    "binding_digest": binding.digest,
                    "error_type": "ProcessRestartBeforeTerminalReceipt",
                    "reason": "approved-without-terminal-receipt",
                },
            )
            self._action_states[action_id] = "attempted-unknown"
        # Sessions never survive process restart. Persist the revocation before
        # any new session capability can be issued.
        for grant in tuple(self._grants.values()):
            if grant.revoked_reason is None:
                self._revoke_grant(grant.grant_id, "process-restart")

    def _ensure_workspaces(self) -> None:
        for record in self.workspace_records:
            events = self._ledger.events(record.workspace_id)
            matching = [
                item for item in events
                if item.event_type == "workspace-registered"
                and item.entity_id == record.workspace_id
            ]
            record_identity = GovernanceIdentityV1(
                self.identity.principal_id,
                record.workspace_id,
                self.identity.account_id,
                self.identity.profile_id,
                record.display_name,
            )
            expected = {
                "identity_digest": record_identity.digest,
                "principal_id": self.identity.principal_id,
                "account_id": self.identity.account_id,
                "profile_id": self.identity.profile_id,
                "workspace_display": record.display_name,
                "workspace_class": record.workspace_class,
                "workspace_schema_version": record.schema_version,
            }
            if matching:
                if matching[-1].payload != expected:
                    raise GovernanceV1IntegrityError("workspace identity diverged")
                continue
            if self._killed:
                raise GovernanceV1Denied(
                    "global kill prevents new workspace registration"
                )
            self._ledger.append(
                "workspace-registered",
                record.workspace_id,
                record.workspace_id,
                expected,
            )

    def _session_hmac(self, payload: Mapping[str, object]) -> str:
        return hmac.new(
            self._key,
            b"ONYX-GOVERNANCE-SESSION.v1\0" + _canonical(dict(payload)),
            hashlib.sha256,
        ).hexdigest()

    def _refresh_kill_latch(self) -> bool:
        latest = self._ledger.latest_durable_event(
            ("global-kill-latched", "global-kill-released"),
            "global-kill",
        )
        self._killed = (
            latest is not None and latest.event_type == "global-kill-latched"
        )
        return self._killed

    def release_global_kill(
        self,
        *,
        confirmation: str,
        reason: str = "owner-explicit-recovery",
    ) -> dict[str, object]:
        """Release a durable kill only through an explicit owner recovery act.

        Normal startup never calls this method. The authenticated ledger keeps
        both the original safety latch and the later owner-authorized release.
        A fresh process is still required to rebuild killed participant ports.
        """

        if confirmation != "RELEASE ONYX GLOBAL KILL":
            raise GovernanceV1Denied("explicit global kill release is required")
        if reason != "owner-explicit-recovery":
            raise GovernanceV1ContractError("global kill release reason is invalid")
        with self._lock:
            latest = self._ledger.latest_durable_event(
                ("global-kill-latched", "global-kill-released"),
                "global-kill",
            )
            if latest is None or latest.event_type != "global-kill-latched":
                self._killed = False
                return {
                    "status": "not-latched",
                    "restart_required": False,
                }
            if self._session is not None:
                raise GovernanceV1Denied(
                    "global kill release requires no active session"
                )
            released = self._ledger.append(
                "global-kill-released",
                "global-kill",
                self.identity.workspace_id,
                {
                    "principal_id": self.identity.principal_id,
                    "identity_digest": self.identity.digest,
                    "released_latch_sequence": latest.sequence,
                    "reason": reason,
                },
            )
            self._killed = False
            self._kill_propagation.clear()
            return {
                "status": "released",
                "released_latch_sequence": latest.sequence,
                "release_sequence": released.sequence,
                "restart_required": True,
            }

    def begin_session(self) -> SessionCapabilityV1:
        with self._lock:
            if self._refresh_kill_latch():
                raise GovernanceV1Denied("global kill is latched")
            if self._session is not None:
                return self._session
            self._session_generation += 1
            issued = _now_ms()
            session_id = (
                f"session-{self._session_generation}-"
                f"{secrets.token_hex(8)}"
            )
            unsigned = {
                "session_id": session_id,
                "principal_id": self.identity.principal_id,
                "workspace_id": self.identity.workspace_id,
                "account_id": self.identity.account_id,
                "profile_id": self.identity.profile_id,
                "generation": self._session_generation,
                "issued_at_ms": issued,
            }
            capability = SessionCapabilityV1(
                **unsigned, capability_hmac=self._session_hmac(unsigned)
            )
            self._ledger.append(
                "session-started",
                session_id,
                self.identity.workspace_id,
                {
                    **unsigned,
                    "capability_hmac": capability.capability_hmac,
                },
            )
            self._session = capability
            self._reset_inbox_projection(session_id)
            return capability

    def _verify_session(self, capability: SessionCapabilityV1 | None = None) -> SessionCapabilityV1:
        session = self._session if capability is None else capability
        if type(session) is not SessionCapabilityV1 or self._session != session:
            raise GovernanceV1Denied("session capability is unavailable")
        if self._refresh_kill_latch():
            raise GovernanceV1Denied("global kill is latched")
        expected = self._session_hmac(session.unsigned_payload())
        if not hmac.compare_digest(expected, session.capability_hmac):
            raise GovernanceV1Denied("session capability authentication failed")
        return session

    def end_session(self, reason: str) -> None:
        if type(reason) is not str or not reason or len(reason) > 80:
            raise GovernanceV1ContractError("session end reason is invalid")
        with self._lock:
            session = self._session
            if session is None:
                return
            self._ledger.append(
                "session-ended",
                session.session_id,
                session.workspace_id,
                {"reason": reason, "generation": session.generation},
            )
            self._session = None
            self._reset_inbox_projection("governance-session")
            for grant in tuple(self._grants.values()):
                if (
                    grant.session_id == session.session_id
                    and grant.revoked_reason is None
                ):
                    self._revoke_grant(grant.grant_id, "session-ended")

    @contextmanager
    def local_commit_fence(self) -> Iterator[GovernanceCommitFenceV1]:
        """Linearize one bounded local commit against kill and audit freeze.

        The same lock used by :meth:`global_kill` remains held across the
        caller's durable commit phase. Pure projection work must happen before
        entering this context.
        """

        with self._lock:
            if self._refresh_kill_latch():
                raise GovernanceV1Denied("global kill is latched")
            session = self._verify_session()
            from core import permission_broker

            if not permission_broker.audit_healthy():
                raise GovernanceV1Denied("governance audit is unhealthy")
            token = GovernanceCommitFenceV1(
                fence_id="fence-" + secrets.token_hex(12),
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                session_generation=session.generation,
            )
            yield token

    @staticmethod
    def begin_invocation(value: object) -> contextvars.Token[str]:
        raw = str(value or "").strip()
        identity = "invocation-" + hashlib.sha256(raw.encode()).hexdigest()[:24]
        return _INVOCATION.set(identity)

    @staticmethod
    def end_invocation(token: contextvars.Token[str]) -> None:
        _INVOCATION.reset(token)

    def _binding(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        explicit_request_digest: str | None = None,
    ) -> ActionBindingV1:
        session = self._verify_session()
        raw_arguments = dict(arguments)
        invocation_reference = raw_arguments.pop(
            "_governance_invocation_ref", None
        )
        invocation = (
            "invocation-"
            + hashlib.sha256(
                str(invocation_reference or "").strip().encode()
            ).hexdigest()[:24]
            if type(invocation_reference) is str
            else _INVOCATION.get()
        )
        if not invocation:
            invocation = "invocation-" + secrets.token_hex(12)
        safe = _safe_arguments(raw_arguments)
        raw_arguments_digest = hashlib.sha256(
            _canonical(raw_arguments)
        ).hexdigest()
        policy = _policy_for(tool_name, safe, session.account_id)
        payload_digest = _sha(
            {
                "contract": "GovernanceActionPayload.v1",
                "tool": policy.tool,
                "operation": policy.operation,
                "arguments_digest": raw_arguments_digest,
                "explicit_request_digest": explicit_request_digest,
            }
        )
        target = {
            key: safe.get(key)
            for key in (
                "path",
                "file_path",
                "destination",
                "recipient",
                "email",
                "url",
                "city",
                "mission_id",
                "workspace_id",
                "manifest_ref",
            )
            if key in safe
        }
        target_digest = _sha(
            {
                "contract": "GovernanceActionTarget.v1",
                "workspace_id": session.workspace_id,
                "provider": policy.provider,
                "account_id": policy.account_id,
                "target": target,
            }
        )
        action_id = "action-" + hashlib.sha256(
            f"{invocation}\0{payload_digest}".encode()
        ).hexdigest()[:24]
        now = _now_ms()
        idempotency_key = (
            "idem-"
            + hashlib.sha256(
                f"{session.workspace_id}\0{payload_digest}".encode()
            ).hexdigest()[:24]
        )
        accepted_binding = grants_v11.ActionBinding(
            policy.provider,
            policy.provider_namespace,
            target_digest,
            "target-" + target_digest[:16],
            payload_digest,
            _summary(safe),
            "governance-v1",
            {
                "none": "none",
                "internal": "local-only",
                "external": "named-account",
            }[policy.egress],
            idempotency_key,
        )
        return ActionBindingV1(
            action_id=action_id,
            invocation_id=invocation,
            principal_id=session.principal_id,
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            provider=policy.provider,
            provider_namespace=policy.provider_namespace,
            account_id=policy.account_id,
            capability=policy.capability,
            tool=policy.tool,
            operation=policy.operation,
            target_digest=target_digest,
            payload_digest=payload_digest,
            payload_summary=_summary(safe),
            idempotency_key=idempotency_key,
            accepted_binding_digest=accepted_binding.digest(),
            risk=policy.risk,
            always_explicit=policy.always_explicit,
            data_class=policy.data_class,
            egress=policy.egress,
            created_at_ms=now,
            expires_at_ms=now + DEFAULT_GRANT_TTL_MS,
        )

    def _persist_intent(self, binding: ActionBindingV1, authority: str) -> None:
        prior = self._actions.get(binding.action_id)
        if prior is not None:
            if prior != binding:
                raise GovernanceV1IntegrityError("action identity collision")
            return
        self._ledger.append(
            "action-intent",
            binding.action_id,
            binding.workspace_id,
            {
                "binding": asdict(binding),
                "binding_digest": binding.digest,
                "authority": authority,
            },
        )
        self._actions[binding.action_id] = binding
        self._invocations[binding.invocation_id] = binding.action_id
        self._action_states[binding.action_id] = "intent"
        self._source_epoch += 1

    def _find_grant(self, binding: ActionBindingV1, now: int) -> GrantRecordV1 | None:
        for grant in self._grants.values():
            if (
                grant.binding_digest == binding.grant_scope_digest
                and grant.principal_id == binding.principal_id
                and grant.workspace_id == binding.workspace_id
                and grant.session_id == binding.session_id
                and grant.provider == binding.provider
                and grant.account_id == binding.account_id
                and grant.tool == binding.tool
                and grant.operation == binding.operation
                and grant.revoked_reason is None
                and now <= grant.expires_at_ms
                and grant.used < grant.max_uses
            ):
                return grant
        return None

    def _issue_grant(self, binding: ActionBindingV1) -> GrantRecordV1:
        if binding.always_explicit or binding.risk != "low":
            raise GovernanceV1Denied("always-explicit action cannot receive a grant")
        grant_id = "grant-" + hashlib.sha256(
            f"{binding.digest}\0{secrets.token_hex(8)}".encode()
        ).hexdigest()[:24]
        grant = GrantRecordV1(
            grant_id,
            binding.grant_scope_digest,
            binding.principal_id,
            binding.workspace_id,
            binding.session_id,
            binding.provider,
            binding.account_id,
            binding.tool,
            binding.operation,
            binding.created_at_ms,
            binding.expires_at_ms,
            DEFAULT_GRANT_MAX_USES,
        )
        self._ledger.append(
            "grant-issued", grant_id, binding.workspace_id, asdict(grant)
        )
        self._grants[grant_id] = grant
        return grant

    def _consume_grant(self, grant: GrantRecordV1, binding: ActionBindingV1) -> None:
        now = _now_ms()
        current = self._grants.get(grant.grant_id)
        if (
            current != grant
            or current is None
            or current.revoked_reason is not None
            or now > current.expires_at_ms
            or current.used >= current.max_uses
            or not hmac.compare_digest(
                current.binding_digest, binding.grant_scope_digest
            )
        ):
            raise GovernanceV1Denied("grant is stale or outside exact binding")
        used = current.used + 1
        self._ledger.append(
            "grant-used",
            current.grant_id,
            current.workspace_id,
            {
                "grant_id": current.grant_id,
                "binding_digest": binding.grant_scope_digest,
                "used": used,
                "max_uses": current.max_uses,
            },
        )
        self._grants[current.grant_id] = replace(current, used=used)
        if used >= current.max_uses:
            self._revoke_grant(current.grant_id, "use-exhausted")

    def _revoke_grant(self, grant_id: str, reason: str) -> None:
        _identifier(grant_id, "grant_id")
        current = self._grants.get(grant_id)
        if current is None:
            raise GovernanceV1ContractError("unknown grant_id")
        if current.revoked_reason is not None:
            return
        self._ledger.append(
            "grant-revoked",
            grant_id,
            current.workspace_id,
            {"grant_id": grant_id, "reason": reason},
        )
        self._grants[grant_id] = replace(current, revoked_reason=reason)
        self._source_epoch += 1

    def set_owner_autonomy_evaluator(self, evaluator: object | None) -> None:
        """Install the evaluator consulted for non-explicit owner autonomy.

        Passing ``None`` restores the default posture, where only exact
        low-risk reads are granted without asking.
        """
        with self._lock:
            self._owner_autonomy_evaluator = evaluator

    def _owner_autonomy_allows(
        self, tool_name: str, arguments: Mapping[str, object], policy: object
    ) -> bool:
        """Fail closed: only an explicit ``True`` from the evaluator grants."""
        evaluator = self._owner_autonomy_evaluator
        if evaluator is None or not callable(evaluator):
            return False
        try:
            return evaluator(tool_name, arguments, getattr(policy, "risk", "")) is True
        except Exception:
            return False

    def authorization_hook(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> tuple[bool, str] | None:
        """Authorize exact low-risk reads and evaluated owner-autonomy work."""
        with self._lock:
            tool = _tool_id(tool_name)
            if tool in {
                "close-camera",
                "mission-global-kill",
            }:
                return None
            if self._refresh_kill_latch():
                return False, "Permission denied: global mutation kill is latched."
            policy = _policy_for(tool_name, arguments, self.identity.account_id)
            # Always-explicit work is never autonomous, at any risk tier and
            # under any owner configuration.  This is the absolute boundary.
            if policy.always_explicit:
                return None
            authority = "bounded-low-risk-grant"
            if policy.risk != "low":
                # Critical operations stay explicit even for an autonomous
                # owner; below that, autonomy must be granted by an installed
                # evaluator that independently confirms scope and containment.
                if policy.risk == "critical":
                    return None
                if not self._owner_autonomy_allows(tool_name, arguments, policy):
                    return None
                authority = "owner-autonomy-grant"
            binding = self._binding(tool_name, arguments)
            self._persist_intent(binding, authority)
            if authority == "bounded-low-risk-grant":
                now = _now_ms()
                grant = self._find_grant(binding, now) or self._issue_grant(binding)
                self._consume_grant(grant, binding)
                proof = f"governance-grant:{grant.grant_id}"
                approved: dict[str, object] = {
                    "binding_digest": binding.digest,
                    "grant_id": grant.grant_id,
                    "authority": authority,
                }
            else:
                # Reusable grants stay reserved for exact low-risk reads.  An
                # autonomous authorization is single-shot: it approves this
                # binding alone, and the next operation is evaluated afresh.
                proof = f"owner-autonomy:{binding.action_id}"
                approved = {
                    "binding_digest": binding.digest,
                    "authority": authority,
                }
            self._ledger.append(
                "action-approved",
                binding.action_id,
                binding.workspace_id,
                approved,
            )
            self._action_states[binding.action_id] = "approved"
            return True, proof

    def authorization_audit_failed(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> None:
        """Compensate a grant when the broker cannot durably audit its use."""
        with self._lock:
            binding = self._binding(tool_name, arguments)
            current = self._actions.get(binding.action_id)
            if current is None:
                return
            revoked: list[str] = []
            for grant in tuple(self._grants.values()):
                if (
                    grant.binding_digest == current.grant_scope_digest
                    and grant.revoked_reason is None
                ):
                    self._revoke_grant(grant.grant_id, "broker-audit-failed")
                    revoked.append(grant.grant_id)
            self._ledger.append(
                "governance-audit-failed",
                current.action_id,
                current.workspace_id,
                {
                    "binding_digest": current.digest,
                    "revoked_grant_ids": revoked,
                    "authority": "permission-broker-audit",
                },
            )
            self._action_states[current.action_id] = "audit-failed"
            self._source_epoch += 1

    def authorize_capability_binding(
        self,
        *,
        binding_id: str,
        principal_id: str,
        workspace_id: str,
        session_id: str,
        session_generation: int,
        capability: str,
        operation: str,
        arguments_digest: str,
        policy_binding_digest: str,
    ) -> None:
        """Authorize one exact capability-host dispatch through this authority.

        The capability host owns no policy state.  It supplies a closed-registry
        policy digest and this nucleus validates live identity, session, audit,
        and kill state before durably recording the decision.
        """
        _identifier(binding_id, "binding_id")
        _identifier(capability, "capability")
        _capability_operation(operation)
        _digest(arguments_digest, "arguments_digest")
        _digest(policy_binding_digest, "policy_binding_digest")
        with self._lock:
            session = self._verify_session()
            if (
                principal_id != session.principal_id
                or workspace_id != session.workspace_id
                or session_id != session.session_id
                or session_generation != session.generation
            ):
                raise GovernanceV1Denied("capability binding identity is stale or foreign")
            from core import permission_broker

            if not permission_broker.audit_healthy():
                raise GovernanceV1Denied("governance audit is unhealthy")
            self._ledger.append(
                "capability-dispatch-authorized",
                binding_id,
                workspace_id,
                {
                    "principal_id": principal_id,
                    "session_id": session_id,
                    "session_generation": session_generation,
                    "capability": capability,
                    "operation": operation,
                    "arguments_digest": arguments_digest,
                    "policy_binding_digest": policy_binding_digest,
                },
            )

    def record_capability_receipt(
        self,
        *,
        binding_id: str,
        outcome: str,
        receipt_digest: str,
        uncertainty: bool,
    ) -> None:
        """Durably record the terminal or uncertain capability-host result."""
        _identifier(binding_id, "binding_id")
        _digest(receipt_digest, "receipt_digest")
        if outcome not in {"completed", "failed", "revoked", "uncertain"}:
            raise GovernanceV1ContractError("capability outcome is invalid")
        if type(uncertainty) is not bool:
            raise GovernanceV1ContractError("uncertainty must be bool")
        with self._lock:
            self._ledger.append(
                "capability-dispatch-receipt",
                binding_id,
                self.identity.workspace_id,
                {
                    "outcome": outcome,
                    "receipt_digest": receipt_digest,
                    "uncertainty": uncertainty,
                },
            )

    def revoke_capability_binding(self, binding_id: str, reason: str) -> None:
        """Record an explicit host-binding revocation in the authority ledger."""
        _identifier(binding_id, "binding_id")
        if type(reason) is not str or not reason or len(reason) > 120:
            raise GovernanceV1ContractError("capability revocation reason is invalid")
        with self._lock:
            self._ledger.append(
                "capability-binding-revoked",
                binding_id,
                self.identity.workspace_id,
                {"reason": reason},
            )

    def assert_dispatch_allowed(
        self,
        *,
        invocation_id: object,
        tool_name: str,
        authorization_proof: str,
    ) -> None:
        """Linearize the final host dispatch decision against global kill.

        The permission broker runs before the concrete host action.  A global
        kill may therefore win after approval but before the host reaches the
        side-effecting branch.  This fence is called at that last common host
        boundary.  Existing genuinely prompt-free operations have an empty
        proof and no governance binding; every governed operation must instead
        still own the exact approved invocation recorded by this nucleus.
        """
        tool = _tool_id(tool_name)
        if type(authorization_proof) is not str:
            raise GovernanceV1ContractError("authorization proof is invalid")
        invocation = "invocation-" + hashlib.sha256(
            str(invocation_id or "").strip().encode()
        ).hexdigest()[:24]
        with self._lock:
            if tool in {"close-camera", "mission-global-kill"}:
                return
            if self._refresh_kill_latch():
                raise GovernanceV1Denied("global kill is latched")
            if tool == "local-catalog-read":
                # This single provider-free read has an independent exact
                # Phase 5 capability and audit boundary in permission_broker.
                return
            action_id = self._invocations.get(invocation)
            if action_id is None:
                if authorization_proof == "":
                    return
                raise GovernanceV1Denied(
                    "governance dispatch binding is unavailable"
                )
            if self._action_states.get(action_id) != "approved":
                raise GovernanceV1Denied(
                    "governance action is not approved for dispatch"
                )

    def _explicit_decision(
        self,
        request: dict,
        callback: Callable[[dict], str | None],
    ) -> str | None:
        legacy_fields = {"action", "summary", "details", "digest"}
        if type(request) is not dict or set(request) not in (legacy_fields, legacy_fields | {"nonce"}):
            raise GovernanceV1ContractError("approval request contract diverged")
        if "nonce" in request and (type(request["nonce"]) is not str or re.fullmatch(r"[0-9a-f]{32}", request["nonce"]) is None):
            raise GovernanceV1ContractError("approval request nonce is invalid")
        supplied_digest = _digest(request["digest"], "approval digest")
        # The broker authenticates its nonce too. Omitting it here rejects
        # every current owner approval; stripping it would enable replay.
        expected = _sha({key: value for key, value in request.items() if key != "digest"})
        if not hmac.compare_digest(supplied_digest, expected):
            raise GovernanceV1Denied("approval request authentication failed")
        details = request.get("details")
        if not isinstance(details, Mapping):
            raise GovernanceV1ContractError("approval details are invalid")
        tool = details.get("tool")
        arguments = details.get("arguments")
        if type(tool) is not str or not isinstance(arguments, Mapping):
            raise GovernanceV1ContractError("approval action is incomplete")
        with self._lock:
            if self._refresh_kill_latch():
                return None
            binding = self._binding(
                tool, arguments, explicit_request_digest=supplied_digest
            )
            if not binding.always_explicit:
                raise GovernanceV1Denied(
                    "low-risk grants cannot enter the explicit approval inbox"
                )
            self._persist_intent(binding, "approval-inbox")
            item_id = "approval-" + binding.action_id.removeprefix("action-")
            if len(self._pending) >= MAX_PENDING:
                self._ledger.append(
                    "action-denied",
                    binding.action_id,
                    binding.workspace_id,
                    {
                        "binding_digest": binding.digest,
                        "request_digest": supplied_digest,
                        "authority": "approval-inbox-capacity",
                    },
                )
                self._action_states[binding.action_id] = "denied"
                raise GovernanceV1Denied("approval inbox capacity reached")
            self._pending[item_id] = PendingApprovalV1(
                item_id, supplied_digest, binding, str(request["summary"])[:240]
            )
            self._source_epoch += 1
        decision: str | None = None
        callback_error: BaseException | None = None
        try:
            decision = callback(json.loads(json.dumps(request)))
        except BaseException as exc:
            callback_error = exc
        finally:
            with self._lock:
                self._pending.pop(item_id, None)
                self._source_epoch += 1
        if callback_error is not None:
            with self._lock:
                self._ledger.append(
                    "action-approval-failed",
                    binding.action_id,
                    binding.workspace_id,
                    {
                        "binding_digest": binding.digest,
                        "request_digest": supplied_digest,
                        "authority": "approval-inbox",
                        "error_type": type(callback_error).__name__[:120],
                    },
                )
                self._action_states[binding.action_id] = "approval-failed"
            raise GovernanceV1Denied(
                "trusted approval callback failed"
            ) from callback_error
        with self._lock:
            killed_after_callback = self._refresh_kill_latch()
            approved = (
                not killed_after_callback
                and type(decision) is str
                and hmac.compare_digest(decision, supplied_digest)
            )
            event_type = (
                "action-late-blocked"
                if killed_after_callback
                else "action-approved" if approved else "action-denied"
            )
            payload = {
                "binding_digest": binding.digest,
                "request_digest": supplied_digest,
                "authority": "approval-inbox",
            }
            if killed_after_callback:
                payload["reason"] = "global-kill-latched"
            self._ledger.append(
                event_type,
                binding.action_id,
                binding.workspace_id,
                payload,
            )
            self._action_states[binding.action_id] = event_type.removeprefix(
                "action-"
            )
        return decision if approved else None

    def record_outcome(
        self,
        *,
        invocation_id: str,
        outcome: str,
        result: object | None,
        error_type: str = "",
    ) -> None:
        invocation = "invocation-" + hashlib.sha256(
            str(invocation_id or "").strip().encode()
        ).hexdigest()[:24]
        with self._lock:
            action_id = self._invocations.get(invocation)
            if action_id is None:
                return
            binding = self._actions[action_id]
            state = self._action_states.get(action_id)
            if state not in {"approved", "intent"}:
                return
            if self._refresh_kill_latch():
                event_type = "action-late-blocked"
                payload = {
                    "binding_digest": binding.digest,
                    "reason": "global-kill-latched",
                }
            elif outcome == "attempted_unknown":
                event_type = "action-attempted-unknown"
                payload = {
                    "binding_digest": binding.digest,
                    "error_type": str(error_type)[:120],
                }
            else:
                event_type = "action-receipt"
                payload = {
                    "binding_digest": binding.digest,
                    "outcome": str(outcome)[:80],
                    "result_digest": _sha(result),
                    "error_type": str(error_type)[:120],
                }
            self._ledger.append(
                event_type, action_id, binding.workspace_id, payload
            )
            self._action_states[action_id] = event_type.removeprefix("action-")

    def request_downgrade_receipt(
        self,
        target: str,
        *,
        receipt_vault: SecretVaultV1 | None = None,
        signing_key_vault: SecretVaultV1 | None = None,
        now_ms: int | None = None,
    ) -> None:
        """Issue one authenticated receipt only through the bound trusted UI."""
        if target not in DOWNGRADE_TARGETS:
            raise GovernanceV1ContractError("downgrade target is invalid")
        with self._lock:
            self._refresh_kill_latch()
            session = self._verify_session()
            binding = {
                "principal_id": session.principal_id,
                "workspace_id": session.workspace_id,
                "session_id": session.session_id,
                "account_id": self.identity.account_id,
                "profile_id": self.identity.profile_id,
                "target": target,
                "one_time": True,
            }
        from core.permission_broker import build_request

        request = build_request(
            "onyx-v16-downgrade",
            f"Allow one Onyx V16 downgrade launch to {target}?",
            {"tool": "onyx-v16-downgrade", "arguments": binding},
        )
        token = self.begin_invocation(
            "downgrade-" + secrets.token_hex(12)
        )
        try:
            decision = self._approval_inbox._decide_trusted(request)
        finally:
            self.end_invocation(token)
        if type(decision) is not str or not hmac.compare_digest(
            decision, request["digest"]
        ):
            raise GovernanceV1Denied("downgrade was not approved by trusted UI")
        issued = _now_ms() if now_ms is None else now_ms
        if type(issued) is not int or issued < 0:
            raise GovernanceV1ContractError("downgrade issue time is invalid")
        receipt_store = receipt_vault or native_vault.NativeSecretVault(
            native_vault.SecretReference(
                DOWNGRADE_RECEIPT_SERVICE,
                DOWNGRADE_RECEIPT_ACCOUNT,
                "Onyx V16 one-time owner-authorized downgrade receipt",
            )
        )
        signing_store = signing_key_vault or native_vault.NativeSecretVault(
            native_vault.SecretReference(
                DOWNGRADE_RECEIPT_SERVICE,
                DOWNGRADE_SIGNING_ACCOUNT,
                "Onyx V16 downgrade receipt authentication key",
            )
        )
        key = signing_store.get_bytes()
        if key is None:
            signing_store.set_bytes(secrets.token_bytes(32))
            key = signing_store.get_bytes()
        if type(key) is not bytes or len(key) != 32:
            raise GovernanceV1IntegrityError("downgrade signing key is invalid")
        payload = {
            "contract": "OnyxV16DowngradeReceipt.v2",
            **binding,
            "request_digest": request["digest"],
            "issued_at_ms": issued,
            "expires_at_ms": issued + DOWNGRADE_RECEIPT_TTL_MS,
            "nonce": secrets.token_hex(16),
        }
        payload["receipt_hmac"] = hmac.new(
            key,
            b"ONYX-V16-DOWNGRADE-RECEIPT.v2\0" + _canonical(payload),
            hashlib.sha256,
        ).hexdigest()
        self._ledger.append(
            "downgrade-receipt-issued",
            "downgrade-" + str(payload["nonce"]),
            session.workspace_id,
            {
                "target": target,
                "request_digest": request["digest"],
                "session_id": session.session_id,
                "expires_at_ms": payload["expires_at_ms"],
            },
        )
        encoded = _canonical(payload)
        receipt_store.set_bytes(encoded)
        if receipt_store.get_bytes() != encoded:
            raise GovernanceV1IntegrityError("downgrade receipt readback failed")

    def _capture_inbox(self) -> inbox_v15.HostInboxSnapshotV15:
        with self._lock:
            session_id = self._inbox_session_id
            review_items = tuple(self._pending.values()) + tuple(
                PendingApprovalV1(
                    "reconcile-" + action_id.removeprefix("action-"),
                    binding.digest,
                    binding,
                    "Attempted outcome unknown; owner reconciliation required.",
                )
                for action_id, binding in self._actions.items()
                if self._action_states.get(action_id) == "attempted-unknown"
            )
            items = tuple(
                inbox_v15.HostInboxItemV15(
                    item.item_id,
                    item.binding.action_id,
                    item.binding.principal_id,
                    session_id,
                    item.binding.workspace_id,
                    self.identity.workspace_display,
                    "session-action",
                    "Live action",
                    item.binding.account_id,
                    item.binding.account_id,
                    item.binding.provider,
                    "v1",
                    item.binding.tool,
                    item.binding.operation,
                    "production",
                    item.reason,
                    "exact target digest",
                    item.binding.target_digest,
                    item.binding.payload_summary,
                    item.binding.payload_digest,
                    EMPTY_ATTACHMENT_DIGEST,
                    POLICY_VERSION,
                    "governance-action-v1",
                    item.binding.data_class,
                    {
                        "none": "none",
                        "internal": "local-only",
                        "external": "named-account",
                    }[item.binding.egress],
                    "owner-confirmed consequential action",
                    "reversible" if item.binding.risk != "critical" else "irreversible",
                    "exact idempotency binding",
                    item.binding.digest,
                    "verify observed action result",
                    "stop and reconcile on uncertainty",
                    0,
                    "USD",
                    item.binding.risk,
                    item.binding.created_at_ms,
                    item.binding.expires_at_ms,
                    True,
                    False,
                )
                for item in sorted(
                    review_items, key=lambda value: value.item_id
                )
            )
            return inbox_v15.HostInboxSnapshotV15(
                self._source_epoch, time.monotonic_ns() // 1_000_000, items
            )

    def global_kill(
        self,
        *,
        phase5: object | None = None,
        phase11: object | None = None,
        mission_worker: object | None = None,
    ) -> dict[str, object]:
        """Persist and anchor kill before revoking sessions or stopping bridges."""
        latch_persistence = "confirmed"
        internal_cleanup: list[str] = []
        with self._lock:
            if not self._refresh_kill_latch():
                # Latch memory before the durable transition. If append fails
                # after commit+anchor, authenticated tail reconstruction keeps
                # the live process fail-closed.
                self._killed = True
                try:
                    self._ledger.append(
                        "global-kill-latched",
                        "global-kill",
                        self.identity.workspace_id,
                        {
                            "principal_id": self.identity.principal_id,
                            "identity_digest": self.identity.digest,
                            "reason": "owner-global-kill",
                        },
                    )
                except BaseException as exc:
                    if not self._ledger.has_durable_event(
                        "global-kill-latched", "global-kill"
                    ):
                        self._killed = False
                        raise
                    latch_persistence = (
                        "confirmed-cleanup-incomplete:"
                        + type(exc).__name__
                    )
            session = self._session
            if session is not None:
                try:
                    self._ledger.append(
                        "session-ended",
                        session.session_id,
                        session.workspace_id,
                        {
                            "reason": "global-kill",
                            "generation": session.generation,
                        },
                    )
                except BaseException as exc:
                    internal_cleanup.append(
                        "session-receipt:" + type(exc).__name__
                    )
                finally:
                    self._session = None
                    self._reset_inbox_projection("governance-session")
            for grant in tuple(self._grants.values()):
                if grant.revoked_reason is None:
                    try:
                        self._revoke_grant(grant.grant_id, "global-kill")
                    except BaseException as exc:
                        self._grants[grant.grant_id] = replace(
                            grant,
                            revoked_reason="global-kill-receipt-incomplete",
                        )
                        internal_cleanup.append(
                            "grant-receipt:" + type(exc).__name__
                        )
            self._pending.clear()
            self._source_epoch += 1
        from core import permission_broker

        def freeze_legacy_authority() -> None:
            permission_broker.configure_owner_autonomy(False, ())
            permission_broker.set_phase5_authorization_hook(None)

        calls: tuple[tuple[str, Callable[[], object] | None], ...] = (
            (
                "phase5",
                getattr(phase5, "kill", None) if phase5 is not None else None,
            ),
            (
                "phase11",
                getattr(phase11, "request_global_away_kill", None)
                if phase11 is not None
                else None,
            ),
            (
                "mission-worker",
                (
                    lambda: mission_worker.stop(timeout=5.0)
                )
                if mission_worker is not None
                and callable(getattr(mission_worker, "stop", None))
                else None,
            ),
            ("legacy-authorization", freeze_legacy_authority),
        )
        propagation: dict[str, str] = {}
        for name, method in calls:
            if method is None:
                status = "incomplete:unavailable"
            else:
                try:
                    observed = method()
                except Exception as exc:
                    status = f"incomplete:{type(exc).__name__}"
                else:
                    status = (
                        "incomplete:returned-false"
                        if observed is False
                        else "confirmed"
                    )
            propagation[name] = status
            try:
                with self._lock:
                    self._ledger.append(
                        "global-kill-propagation",
                        "global-kill",
                        self.identity.workspace_id,
                        {"subsystem": name, "status": status},
                    )
                    self._kill_propagation[name] = status
            except Exception as exc:
                propagation[name] = (
                    status + f";receipt-{type(exc).__name__}"
                )
        return {
            "status": "kill-latched",
            "mutations_frozen": True,
            "sessions_revoked": True,
            "latch_persistence": latch_persistence,
            "internal_cleanup": tuple(internal_cleanup),
            "propagation": propagation,
        }

    def status(self) -> GovernanceStatusV1:
        with self._lock:
            events = self._ledger.events(self.identity.workspace_id)
            active = sum(
                grant.revoked_reason is None
                and grant.used < grant.max_uses
                and _now_ms() <= grant.expires_at_ms
                for grant in self._grants.values()
            )
            attempted = sum(
                state == "attempted-unknown"
                for state in self._action_states.values()
            )
            return GovernanceStatusV1(
                True,
                self._killed,
                self.identity.principal_id,
                self.identity.workspace_id,
                self._session.session_id if self._session else None,
                self._session_generation,
                len(events),
                len(self._pending),
                active,
                attempted,
                len(_POLICIES) + 1,
                (
                    "nexus-dispatch-local-catalog-only",
                    "external-provider-health-configured-unverified",
                    "no-email-browser-or-external-agent-activation",
                ),
                tuple(
                    sorted(
                        {
                            name: self._kill_propagation.get(
                                name,
                                "incomplete:not-recorded"
                                if self._killed
                                else "not-requested",
                            )
                            for name in (
                                "legacy-authorization",
                                "mission-worker",
                                "phase11",
                                "phase5",
                            )
                        }.items()
                    )
                ),
            )

    def status_payload(self) -> dict[str, object]:
        return {"surface": "status", "data": asdict(self.status())}

    @staticmethod
    def _phase5_catalog_available(phase5: object | None) -> bool:
        if phase5 is None:
            return False
        status_reader = getattr(phase5, "status_payload", None)
        if not callable(status_reader):
            return False
        try:
            payload = status_reader()
            data = payload.get("data") if isinstance(payload, Mapping) else None
            if not isinstance(data, Mapping):
                return False
            state = data.get("state")
            state = getattr(state, "value", state)
            failures = data.get("component_failures", ())
            flags = dict(data.get("flags", ()))
            return (
                state == "READY"
                and not failures
                and flags.get("local_catalog_read") is True
                and flags.get("low_risk") is True
            )
        except Exception:
            return False

    def capabilities_payload(
        self, phase5: object | None = None
    ) -> dict[str, object]:
        local_catalog_available = self._phase5_catalog_available(phase5)
        entries = [
            {
                "capability": policy.capability,
                "tool": policy.tool,
                "operation": policy.operation,
                "provider": policy.provider,
                "provider_namespace": policy.provider_namespace,
                "account_id": policy.account_id,
                "workspace_id": self.identity.workspace_id,
                "status": policy.health,
                "dispatch_available": False,
                "authorization": (
                    "bounded-low-risk-grant"
                    if not policy.always_explicit
                    else "always-explicit"
                ),
            }
            for policy in _POLICIES
        ]
        entries.append(
            {
                "capability": "local-catalog",
                "tool": "local-catalog-read",
                "operation": "read",
                "provider": "onyx-local",
                "provider_namespace": "provider-free-catalog",
                "account_id": self.identity.account_id,
                "workspace_id": self.identity.workspace_id,
                "status": (
                    "available-read-only"
                    if local_catalog_available
                    else "unavailable-phase5-unhealthy"
                ),
                "dispatch_available": local_catalog_available,
                "authorization": "phase5-exact-local-read",
            }
        )
        return {
            "surface": "capabilities",
            "data": {
                "truthful": True,
                "nexus_dispatch_allowlist": ["local-catalog-read"],
                "items": entries,
            },
        }

    def dashboard_read(
        self,
        surface: str,
        *,
        offset: int = 0,
        page_size: int = 50,
        phase5: object | None = None,
    ) -> dict[str, object]:
        if type(offset) is not int or type(page_size) is not int:
            raise GovernanceV1ContractError("dashboard pagination is invalid")
        if surface == "status":
            return self.status_payload()
        if surface == "capabilities":
            return self.capabilities_payload(phase5)
        if surface != "inbox":
            raise GovernanceV1ContractError("unknown governance dashboard surface")
        query = inbox_v15.InboxQueryV15(workspace_id=self.identity.workspace_id)
        page = self._inbox_projection.open_page(
            query=query, page_size=min(max(page_size, 1), 100)
        )
        items = [asdict(item) for item in page.items]
        return {
            "surface": "inbox",
            "data": {
                "items": items[offset : offset + page_size],
                "authority": "governance-approval-inbox-v1",
                "approval_action_available": False,
                "decision_channel": "trusted-local-ui-only",
                "execution_available": False,
            },
        }

    def dashboard_facade(
        self,
        phase5: object | None,
        phase11: object | None,
        mission_worker: object | None = None,
    ) -> GovernanceDashboardFacadeV1:
        return GovernanceDashboardFacadeV1(
            self, phase5, phase11, mission_worker
        )


def create_governance_nucleus_v1(
    *,
    path: Path,
    principal_id: str = DEFAULT_PRINCIPAL_ID,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    account_id: str = DEFAULT_ACCOUNT_ID,
    profile_id: str = DEFAULT_PROFILE_ID,
    workspace_display: str = DEFAULT_WORKSPACE_DISPLAY,
    key_vault: SecretVaultV1 | None = None,
    head_vault: SecretVaultV1 | None = None,
    pending_vault: SecretVaultV1 | None = None,
    trusted_directory_factory: Callable[..., object] | None = None,
    require_windows_boundary: bool | None = None,
    require_host_boundary: bool | None = None,
    workspace_records: tuple[WorkspaceRecord, ...] = (),
) -> GovernanceNucleusV1:
    return GovernanceNucleusV1(
        path=Path(path),
        identity=GovernanceIdentityV1(
            principal_id,
            workspace_id,
            account_id,
            profile_id,
            workspace_display,
        ),
        key_vault=key_vault,
        head_vault=head_vault,
        pending_vault=pending_vault,
        trusted_directory_factory=trusted_directory_factory,
        require_windows_boundary=require_windows_boundary,
        require_host_boundary=require_host_boundary,
        workspace_records=workspace_records,
    )


__all__ = [
    "ActionBindingV1",
    "DEFAULT_ACCOUNT_ID",
    "DEFAULT_PRINCIPAL_ID",
    "DEFAULT_PROFILE_ID",
    "DEFAULT_WORKSPACE_ID",
    "GovernanceApprovalInboxAuthorityV1",
    "GovernanceCommitFenceV1",
    "GovernanceDashboardFacadeV1",
    "GovernanceIdentityV1",
    "GovernanceNucleusV1",
    "GovernanceStatusV1",
    "GovernanceV1ContractError",
    "GovernanceV1Denied",
    "GovernanceV1Error",
    "GovernanceV1IntegrityError",
    "GrantRecordV1",
    "PendingApprovalV1",
    "SessionCapabilityV1",
    "ToolPolicyV1",
    "create_governance_nucleus_v1",
]
