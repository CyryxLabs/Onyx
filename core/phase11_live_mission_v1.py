"""Immutable, default-off Phase 11 binding over MissionStore authority."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from core import native_vault
from core.missions import (
    Mission,
    MissionError,
    MissionStore,
    ToolRunner,
    _local_runner,
    redact,
)
from core.paths import private_control_plane_runtime_dir
from core.phase11_local_project_audit_v1 import (
    LocalProjectAuditV1,
    ProjectSnapshotV1,
    VerificationReceiptV1,
)
from core.phase11_project_autopilot_v1 import (
    AutopilotEnvelopeV1,
    ExecutableGateEnvelopeV1,
    ExecutableGatePlanV1,
    MAX_PATCH_BYTES,
    MISSION_TYPE as AUTOPILOT_MISSION_TYPE,
    ProjectAutopilotV1,
    TOOL_NAME as AUTOPILOT_TOOL_NAME,
    derive_executable_sandbox_subkey_v1,
    feature_enabled as autopilot_feature_enabled,
)
from core.phase11_execution_ledger_v1 import Phase11ExecutionLedgerV1
from core.phase11_executable_sandbox_v1 import (
    ExecutableSandboxHostV1,
    verify_executable_sandbox_receipt_v1,
)
from core.phase11_governed_away_v1 import (
    BrowserActionEnvelopeV1,
    GovernedAwayError,
    GovernedAwayModeV1,
    GovernedAwayUnavailable,
    GovernedAwayWaiting,
    MISSION_TYPE as AWAY_MISSION_TYPE,
    TOOL_NAME as AWAY_TOOL_NAME,
    action_intent_digest,
)
from core.external_agent_adapter_v1 import (
    ExternalAgentContractError,
    ExternalAgentEnvelopeV1,
    ExternalAgentUnavailable,
    ExternalAgentWaiting,
    ExternalCodingAgentAdapterV1,
    MISSION_TYPE as EXTERNAL_AGENT_MISSION_TYPE,
    TOOL_NAME as EXTERNAL_AGENT_TOOL_NAME,
)
from memory.store import _harden_mode, _is_reparse


MISSION_TYPE = "local_project_audit_v1"
FEATURE_FLAG = "ONYX_PHASE11_LOCAL_PROJECT_AUDIT_V1"
WORKSPACE_ROOTS_FLAG = "ONYX_WORKSPACE_ROOTS"
BINDING_SCHEMA = "onyx.phase11.live_binding.v1"
_DOMAIN = b"ONYX/PHASE11/LIVE-BINDING/V1\0"
_ANCHOR_DOMAIN = b"ONYX/PHASE11/AUTHORITY-ANCHOR/V1\0"
_EVENT_SIGNATURE_DOMAIN = b"ONYX/PHASE11/AUTHORITY-EVENT/V1\0"
_RECONCILIATION_DOMAIN = b"ONYX/PHASE11/EXECUTABLE-RECONCILIATION/V1\0"
_RECONCILIATION_SCHEMA = "onyx.phase11.executable_reconciliation.v1"
_EXECUTION_LEDGER_SUBKEY_DOMAIN = b"ONYX/PHASE11/EXECUTION-LEDGER/SUBKEY/V1\0"
_KILL_EVENT_NAME_DOMAIN = b"ONYX/PHASE11/KILL-EVENT-NAME/V1\0"
_PLAN_TOOLS = ("local_system_status", "workspace_inventory", "workspace_text_search")
_MAX_BINDING_BYTES = 2_000_000
_MAX_EXECUTABLE_PLAN_ARTIFACT_BYTES = 128 * 1024
_MAX_KILL_FAST_PATH_ENTRIES = 4_096
_MAX_PROCESS_HIGH_WATER_ENTRIES = 4_096
_KILL_DURABLE_REFRESH_SECONDS = 1.0
_WINDOWS_BINDING_STARTUP_TIMEOUT_SECONDS = 5.0
_WINDOWS_BINDING_STARTUP_RETRY_SECONDS = 0.05
_MAX_EXTERNAL_AGENT_TASK_BYTES = 100_000
_EXTERNAL_CONTEXT_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".py",
        ".qml",
        ".rs",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
_EXTERNAL_SECRET_PATH = re.compile(
    r"(?i)(?:^|[._/-])(?:\\.env|credential|secret|private.?key|token|cookie)(?:[._/-]|$)"
)
_PROCESS_HIGH_WATER_LOCK = threading.RLock()
_PROCESS_HIGH_WATER: dict[str, tuple[int, str]] = {}
_VAULT_REFERENCE = native_vault.SecretReference(
    "Onyx.Phase11LiveBinding",
    "binding-v1",
    "Onyx Phase 11 immutable binding key",
)


class Phase11LiveMissionError(MissionError):
    pass


class Phase11LifecycleError(Phase11LiveMissionError):
    """One lifecycle operation failed at multiple independent boundaries."""

    def __init__(self, message: str, failures: Iterable[BaseException]) -> None:
        collected = tuple(failures)
        if not collected:
            raise ValueError("Phase 11 lifecycle failures cannot be empty")
        super().__init__(message)
        self.failures = collected
        for index, failure in enumerate(collected, start=1):
            self.add_note(
                f"failure[{index}]={type(failure).__name__}: {failure}"
            )


class BindingKeyVault(Protocol):
    def get_bytes(self) -> bytes | None: ...
    def set_bytes(self, secret: bytes | bytearray) -> None: ...


AnchorVaultFactory = Callable[[native_vault.SecretReference], BindingKeyVault]


class HostBoundaryFactory(Protocol):
    def __call__(
        self,
        *,
        root: str | os.PathLike[str],
        enabled: bool,
    ) -> object: ...


class KillSignalBoundary(Protocol):
    def is_set(self) -> bool: ...

    def set(self) -> None: ...

    def close(self) -> None: ...


class KillSignalFactory(Protocol):
    def __call__(
        self,
        *,
        directory: object | None,
        name: str,
        binding_digest: str,
    ) -> KillSignalBoundary: ...


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _WAIT_OBJECT_0 = 0
    _WAIT_TIMEOUT = 258
    _ERROR_ALREADY_EXISTS = 183
    _TOKEN_QUERY = 0x0008
    _EVENT_MODIFY_STATE = 0x0002
    _SYNCHRONIZE = 0x00100000
    _READ_CONTROL = 0x00020000
    _OWNER_SECURITY_INFORMATION = 0x00000001
    _DACL_SECURITY_INFORMATION = 0x00000004
    _LABEL_SECURITY_INFORMATION = 0x00000010
    _SE_KERNEL_OBJECT = 6

    class _SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = [
            ("Sid", wintypes.LPVOID),
            ("Attributes", wintypes.DWORD),
        ]

    class _TokenUser(ctypes.Structure):
        _fields_ = [("User", _SidAndAttributes)]

    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    _kernel32.LocalFree.restype = wintypes.HLOCAL
    _kernel32.CreateEventExW.argtypes = [
        ctypes.POINTER(_SecurityAttributes),
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _kernel32.CreateEventExW.restype = wintypes.HANDLE
    _kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.SetEvent.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi32.GetTokenInformation.restype = wintypes.BOOL
    _advapi32.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
        wintypes.BOOL
    )
    _advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = (
        wintypes.BOOL
    )
    _advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    _advapi32.GetSecurityInfo.restype = wintypes.DWORD


def _windows_error(message: str) -> OSError:
    if os.name != "nt":
        return OSError(message)
    return ctypes.WinError(ctypes.get_last_error())


def _current_windows_sid() -> str:
    if os.name != "nt":
        raise Phase11LiveMissionError(
            "Phase 11 named kill events require Windows"
        )
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(
        _kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise _windows_error("OpenProcessToken failed")
    try:
        required = wintypes.DWORD()
        _advapi32.GetTokenInformation(
            token, 1, None, 0, ctypes.byref(required)
        )
        if required.value <= 0:
            raise _windows_error("GetTokenInformation sizing failed")
        buffer = ctypes.create_string_buffer(required.value)
        if not _advapi32.GetTokenInformation(
            token, 1, buffer, required, ctypes.byref(required)
        ):
            raise _windows_error("GetTokenInformation failed")
        token_user = ctypes.cast(
            buffer, ctypes.POINTER(_TokenUser)
        ).contents
        sid_text = wintypes.LPWSTR()
        if not _advapi32.ConvertSidToStringSidW(
            token_user.User.Sid, ctypes.byref(sid_text)
        ):
            raise _windows_error("ConvertSidToStringSidW failed")
        try:
            return str(sid_text.value)
        finally:
            _kernel32.LocalFree(sid_text)
    finally:
        if not _kernel32.CloseHandle(token):
            raise _windows_error("token CloseHandle failed")


def _security_descriptor_sddl(descriptor: object) -> str:
    text = wintypes.LPWSTR()
    flags = (
        _OWNER_SECURITY_INFORMATION
        | _DACL_SECURITY_INFORMATION
        | _LABEL_SECURITY_INFORMATION
    )
    if not _advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        descriptor, 1, flags, ctypes.byref(text), None
    ):
        raise _windows_error("security descriptor conversion failed")
    try:
        return str(text.value).replace("S:AI(", "S:(")
    finally:
        _kernel32.LocalFree(text)


class _WindowsNamedKillEvent:
    def __init__(self, name: str) -> None:
        if os.name != "nt" or not name.startswith("Local\\Onyx.Phase11.Kill."):
            raise Phase11LiveMissionError("named kill event boundary is invalid")
        sid = _current_windows_sid()
        rights = _SYNCHRONIZE | _EVENT_MODIFY_STATE
        sddl = (
            f"O:{sid}D:P(A;;0x{rights:08x};;;SY)"
            f"(A;;0x{rights:08x};;;{sid})S:(ML;;NW;;;ME)"
        )
        expected = wintypes.LPVOID()
        if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(expected), None
        ):
            raise _windows_error("kill event security descriptor failed")
        attributes = _SecurityAttributes(
            ctypes.sizeof(_SecurityAttributes), expected, False
        )
        try:
            handle = _kernel32.CreateEventExW(
                ctypes.byref(attributes),
                name,
                1,
                rights | _READ_CONTROL,
            )
            already_exists = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
            if not handle:
                raise _windows_error("CreateEventExW failed")
            self._handle = handle
            self.name = name
            self._guard = threading.Lock()
            self._readers = 0
            self._closing = False
            self._closed = False
            if already_exists:
                self._verify_existing_security(expected)
        except BaseException:
            handle = getattr(self, "_handle", None)
            if handle:
                _kernel32.CloseHandle(handle)
            raise
        finally:
            _kernel32.LocalFree(expected)

    def _verify_existing_security(self, expected: object) -> None:
        observed = wintypes.LPVOID()
        result = _advapi32.GetSecurityInfo(
            self._handle,
            _SE_KERNEL_OBJECT,
            _OWNER_SECURITY_INFORMATION
            | _DACL_SECURITY_INFORMATION
            | _LABEL_SECURITY_INFORMATION,
            None,
            None,
            None,
            None,
            ctypes.byref(observed),
        )
        if result != 0 or not observed:
            raise Phase11LiveMissionError(
                "existing named kill event security is unverifiable"
            )
        try:
            if _security_descriptor_sddl(observed) != _security_descriptor_sddl(
                expected
            ):
                raise Phase11LiveMissionError(
                    "existing named kill event security diverges"
                )
        finally:
            _kernel32.LocalFree(observed)

    def _enter(self) -> object:
        with self._guard:
            if self._closed or self._closing:
                raise OSError("named kill event handle is closing")
            self._readers += 1
            return self._handle

    def _leave(self) -> None:
        with self._guard:
            self._readers -= 1

    def is_set(self) -> bool:
        handle = self._enter()
        try:
            result = _kernel32.WaitForSingleObject(handle, 0)
            if result == _WAIT_OBJECT_0:
                return True
            if result == _WAIT_TIMEOUT:
                return False
            raise _windows_error("WaitForSingleObject failed")
        finally:
            self._leave()

    def set(self) -> None:
        handle = self._enter()
        try:
            if not _kernel32.SetEvent(handle):
                raise _windows_error("SetEvent failed")
        finally:
            self._leave()

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            if self._readers:
                raise OSError("named kill event handle is active")
            self._closing = True
            handle = self._handle
        try:
            if not _kernel32.CloseHandle(handle):
                raise _windows_error("kill event CloseHandle failed")
        except BaseException:
            with self._guard:
                self._closing = False
            raise
        with self._guard:
            self._closed = True
            self._closing = False


@dataclass
class _KillState:
    event: threading.Event = field(default_factory=threading.Event)
    binding_digest: str = ""
    kernel: KillSignalBoundary | None = None
    kernel_closed: bool = False
    next_durable_check: float = 0.0
    durable_check_lock: threading.Lock = field(default_factory=threading.Lock)
    lifecycle_lock: threading.Lock = field(default_factory=threading.Lock)
    active_runners: int = 0


def feature_enabled(environment: dict[str, str] | None = None) -> bool:
    source = os.environ if environment is None else environment
    return source.get(FEATURE_FLAG) == "true"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _snapshot_from_dict(value: dict[str, Any]) -> ProjectSnapshotV1:
    from core.phase11_local_project_audit_v1 import DirtyFileDigestV1

    return ProjectSnapshotV1(
        schema=str(value["schema"]),
        root=str(value["root"]),
        head=str(value["head"]),
        status_sha256=str(value["status_sha256"]),
        dirty_files=tuple(DirtyFileDigestV1(**item) for item in value["dirty_files"]),
        dirty_bytes=int(value["dirty_bytes"]),
        snapshot_sha256=str(value["snapshot_sha256"]),
        signature=str(value["signature"]),
    )


def _redacted_reason(value: object) -> str:
    safe = str(redact(value)).strip()
    return safe[:160] if safe else "phase11_verification_failed"


def _reject_linked_ancestors(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if not current.exists():
            continue
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or _is_reparse(current):
            raise Phase11LiveMissionError(
                "Phase 11 binding path contains a linked or reparse ancestor"
            )


def _validated_raw_root(value: str | os.PathLike[str]) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        raise Phase11LiveMissionError(
            "Phase 11 workspace roots must be explicit absolute paths"
        )
    absolute = raw.absolute()
    _reject_linked_ancestors(absolute)
    if not absolute.is_dir():
        raise Phase11LiveMissionError("Phase 11 workspace root is unavailable")
    return absolute.resolve()


class Phase11LiveMissionV1:
    """Bind a fixed audit or isolated mutation slice to authenticated authority."""

    def __init__(
        self,
        store: MissionStore,
        *,
        binding_dir: str | os.PathLike[str],
        allowed_roots: Iterable[str | os.PathLike[str]],
        enabled: bool = False,
        base_runner: ToolRunner = _local_runner,
        key: bytes | None = None,
        key_vault: BindingKeyVault | None = None,
        anchor_vault_factory: AnchorVaultFactory | None = None,
        trusted_directory_factory: HostBoundaryFactory | None = None,
        kill_signal_factory: KillSignalFactory | None = None,
        autopilot_enabled: bool | None = None,
        executable_sandbox_enabled: bool = False,
        executable_sandbox_host: ExecutableSandboxHostV1 | None = None,
        approved_executable_image_ids: Iterable[str] = (),
        executable_platform: str | None = None,
        governed_away_enabled: bool = False,
        governed_away_driver: object | None = None,
        external_agent_enabled: bool = False,
        external_agent_factory: object | None = None,
    ) -> None:
        self.store = store
        self.binding_dir = Path(binding_dir)
        self.enabled = enabled is True
        self.unavailable_reason: str | None = None
        self.away_unavailable_reason: str | None = None
        self.base_runner = base_runner
        self._lock = threading.RLock()
        self._kill_states: dict[str, _KillState] = {}
        self._host_binding_boundary: Any | None = None
        self._windows_binding_boundary: Any | None = None
        self._trusted_directory_factory = trusted_directory_factory
        self._kill_signal_factory = kill_signal_factory
        self._kill_event_namespace = hashlib.sha256(
            os.path.normcase(str(self.binding_dir.absolute())).encode("utf-8")
        ).digest()
        self._closed = False
        self._closing = False
        self._reconciliation_fault: Callable[[str], None] = lambda _point: None
        self._authority_capability: object | None = None
        self._authority_signing_key: Ed25519PrivateKey | None = None
        self._authority_public_key = ""
        roots = tuple(_validated_raw_root(item) for item in allowed_roots)
        if not roots:
            raise ValueError("Phase 11 requires at least one explicit workspace root")
        self._allowed_roots = frozenset(str(item) for item in roots)
        self._key: bytes | None = None
        self._execution_ledger: Phase11ExecutionLedgerV1 | None = None
        self.audit: LocalProjectAuditV1 | None = None
        self.autopilot: ProjectAutopilotV1 | None = None
        self._executable_sandbox_enabled = executable_sandbox_enabled is True
        if (
            executable_sandbox_host is not None
            and type(executable_sandbox_host) is not ExecutableSandboxHostV1
        ):
            raise Phase11LiveMissionError(
                "executable sandbox host binding is invalid"
            )
        self._executable_sandbox_host = executable_sandbox_host
        self._approved_executable_image_ids = frozenset(
            approved_executable_image_ids
        )
        self._executable_platform = executable_platform
        self.away_mode: GovernedAwayModeV1 | None = None
        self.external_agent: ExternalCodingAgentAdapterV1 | None = None
        self.external_agent_unavailable_reason: str | None = None
        self._external_agent_enabled = external_agent_enabled is True
        self._external_agent_factory: Callable[..., object] | None = None
        self._native_anchor_capability_registered = False
        self._anchor_vault_factory = anchor_vault_factory or (
            lambda reference: native_vault.NativeSecretVault(reference)
        )
        if not self.enabled:
            return
        try:
            self._prepare_directory()
            if not self.enabled:
                return
            self._key = bytes(key) if key is not None else self._vault_key(key_vault)
            if len(self._key) < 16:
                raise ValueError("Phase 11 binding key must contain at least 16 bytes")
            if self._executable_sandbox_enabled:
                boundary = self._host_binding_boundary
                if boundary is None:
                    raise Phase11LiveMissionError(
                        "executable execution ledger requires trusted directory"
                    )
                ledger_subkey = hmac.new(
                    self._key,
                    _EXECUTION_LEDGER_SUBKEY_DOMAIN,
                    hashlib.sha256,
                ).digest()
                self._execution_ledger = Phase11ExecutionLedgerV1(
                    host_secret=ledger_subkey,
                    trusted_directory=boundary,
                    receipt_signing_key=derive_executable_sandbox_subkey_v1(
                        self._key
                    ),
                    receipt_verifier=verify_executable_sandbox_receipt_v1,
                    enabled=True,
                )
            self.audit = LocalProjectAuditV1(
                allowed_roots=roots,
                receipt_key=self._key,
            )
            use_autopilot = (
                autopilot_feature_enabled()
                if autopilot_enabled is None
                else autopilot_enabled is True
            )
            if self._executable_sandbox_enabled and (
                not use_autopilot
                or self._executable_sandbox_host is None
                or not self._approved_executable_image_ids
                or self._executable_platform not in {"linux/amd64", "linux/arm64"}
            ):
                raise Phase11LiveMissionError(
                    "executable Project Autopilot requires the complete live boundary"
                )
            authority_seed = hashlib.sha256(
                self._key + _EVENT_SIGNATURE_DOMAIN + b"ED25519"
            ).digest()
            self._authority_signing_key = Ed25519PrivateKey.from_private_bytes(
                authority_seed
            )
            self._authority_public_key = (
                self._authority_signing_key.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                ).hex()
            )
            self._authority_capability = (
                self.store._issue_phase11_authority_capability_v1(
                    self,
                    self._validate_authority_append,
                )
            )
            if anchor_vault_factory is None:
                native_vault._register_phase11_anchor_capability(
                    self._authority_capability, self
                )
                self._native_anchor_capability_registered = True
                self._anchor_vault_factory = lambda reference: (
                    native_vault.NativeSecretVault(
                        reference,
                        capability=self._authority_capability,
                    )
                )
            if use_autopilot:
                autopilot_worktree_root = (
                    private_control_plane_runtime_dir()
                    / "phase11-autopilot-worktrees-v1"
                    / hashlib.sha256(
                        os.path.normcase(
                            str(self.binding_dir.absolute())
                        ).encode("utf-8")
                    ).hexdigest()[:16]
                    if self._executable_sandbox_enabled
                    else self.binding_dir.parent
                    / "phase11-autopilot-worktrees-v1"
                )
                self.autopilot = ProjectAutopilotV1(
                    worktree_root=autopilot_worktree_root,
                    signing_key=self._key,
                    enabled=True,
                    checkpoint_vault_factory=self._anchor_vault_factory,
                    terminal_state_resolver=lambda mission_id: self.store.get(
                        mission_id
                    ).state,
                    executable_sandbox_enabled=self._executable_sandbox_enabled,
                    executable_sandbox_host=self._executable_sandbox_host,
                    approved_executable_image_ids=self._approved_executable_image_ids,
                    execution_ledger=self._execution_ledger,
                    require_execution_ledger=self._executable_sandbox_enabled,
                )
            if governed_away_enabled is True:
                try:
                    self.away_mode = GovernedAwayModeV1(
                        root=self.binding_dir.parent / "phase11-away-v1",
                        signing_key=self._key,
                        enabled=True,
                        driver=governed_away_driver,
                    )
                except GovernedAwayUnavailable as exc:
                    self.away_unavailable_reason = exc.reason
            if self._external_agent_enabled:
                if not callable(external_agent_factory):
                    self.external_agent_unavailable_reason = (
                        "provider_factory_unavailable"
                    )
                else:
                    self._external_agent_factory = external_agent_factory
        except BaseException as exc:
            failures = self._rollback_failed_initialization()
            for failure in failures:
                exc.add_note(
                    "Phase 11 initialization rollback failed: "
                    f"{type(failure).__name__}: {failure}"
                )
            raise

    def _rollback_failed_initialization(self) -> list[BaseException]:
        """Release every boundary acquired by an incomplete constructor."""

        failures: list[BaseException] = []
        for resource_name in ("external_agent", "away_mode"):
            resource = getattr(self, resource_name, None)
            close = getattr(resource, "close", None)
            if callable(close):
                try:
                    close()
                except BaseException as exc:
                    failures.append(exc)
                else:
                    setattr(self, resource_name, None)
        capability = getattr(self, "_authority_capability", None)
        if capability is not None:
            if self._native_anchor_capability_registered:
                try:
                    native_vault._unregister_phase11_anchor_capability(
                        capability, self
                    )
                except BaseException as exc:
                    failures.append(exc)
                else:
                    self._native_anchor_capability_registered = False
            try:
                self.store._revoke_phase11_authority_capability_v1(
                    capability, self
                )
            except BaseException as exc:
                failures.append(exc)
            else:
                self._authority_capability = None
        boundary = getattr(self, "_host_binding_boundary", None)
        if boundary is None:
            boundary = getattr(self, "_windows_binding_boundary", None)
        if boundary is not None:
            try:
                boundary.close()
            except BaseException as exc:
                failures.append(exc)
            else:
                if getattr(self, "_host_binding_boundary", None) is boundary:
                    self._host_binding_boundary = None
                if getattr(self, "_windows_binding_boundary", None) is boundary:
                    self._windows_binding_boundary = None
        if not failures:
            self._closed = True
            self._closing = False
        return failures

    def _require_enabled(self) -> LocalProjectAuditV1:
        if not self.enabled or self.audit is None or self._key is None:
            if self.unavailable_reason is None:
                raise Phase11LiveMissionError(
                    f"{MISSION_TYPE} is disabled; enable {FEATURE_FLAG} exactly"
                )
            reason = self.unavailable_reason
            raise Phase11LiveMissionError(
                f"{MISSION_TYPE} is unavailable: {reason}"
            )
        return self.audit

    def _ensure_external_agent(self) -> ExternalCodingAgentAdapterV1:
        """Discover the optional coding provider only for an explicit operation."""

        with self._lock:
            if self._closed or self._closing:
                raise Phase11LiveMissionError(
                    "external coding agent is unavailable: phase11_closing"
                )
            if self.external_agent is not None:
                return self.external_agent
            if not self.enabled or self._key is None:
                raise Phase11LiveMissionError(
                    "external coding agent is unavailable: phase11_disabled"
                )
            factory = self._external_agent_factory
            if not self._external_agent_enabled:
                reason = "provider_not_explicitly_enabled"
            elif factory is None:
                reason = self.external_agent_unavailable_reason or (
                    "provider_factory_unavailable"
                )
            else:
                reason = ""
            if reason:
                self.external_agent_unavailable_reason = reason
                raise Phase11LiveMissionError(
                    f"external coding agent is unavailable: {reason}"
                )
            try:
                candidate = factory(
                    state_root=self.binding_dir.parent
                    / "phase11-external-agent-v1",
                    signing_key=self._key,
                    terminal_state_resolver=lambda mission_id: self.store.get(
                        mission_id
                    ).state,
                )
                if type(candidate) is not ExternalCodingAgentAdapterV1:
                    close = getattr(candidate, "close", None)
                    if callable(close):
                        try:
                            close()
                        except BaseException:
                            pass
                    raise ExternalAgentUnavailable(
                        "external-agent factory returned an invalid adapter"
                    )
            except ExternalAgentUnavailable as exc:
                reason = str(exc)[:160] or "provider_unavailable"
                self.external_agent_unavailable_reason = reason
                raise Phase11LiveMissionError(
                    f"external coding agent is unavailable: {reason}"
                ) from exc
            self.external_agent = candidate
            self.external_agent_unavailable_reason = None
            return candidate

    def _prepare_directory(self) -> None:
        boundary_factory = getattr(self, "_trusted_directory_factory", None)
        if boundary_factory is not None:
            try:
                boundary = boundary_factory(
                    root=self.binding_dir,
                    enabled=True,
                )
            except Exception as exc:
                raise Phase11LiveMissionError(
                    "Phase 11 trusted binding startup failed: "
                    "phase11_binding_factory_failed"
                ) from exc
            self._host_binding_boundary = boundary
            if os.name == "nt":
                # Compatibility alias for the existing Windows descriptor I/O.
                self._windows_binding_boundary = boundary
            _harden_mode(self.binding_dir)
            return
        if os.name == "nt":
            from core.phase11_windows_clone_cleanup_v1 import (
                CloneCleanupContractError,
                CloneCleanupWaiting,
            )
            from core.phase11_windows_namespace_v1 import (
                WindowsTrustedDirectoryV1,
            )

            deadline = (
                time.monotonic()
                + _WINDOWS_BINDING_STARTUP_TIMEOUT_SECONDS
            )
            delay = _WINDOWS_BINDING_STARTUP_RETRY_SECONDS
            while True:
                try:
                    self._windows_binding_boundary = (
                        WindowsTrustedDirectoryV1(
                            root=self.binding_dir,
                            enabled=True,
                        )
                    )
                    self._host_binding_boundary = (
                        self._windows_binding_boundary
                    )
                    break
                except CloneCleanupWaiting:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise Phase11LiveMissionError(
                            "Phase 11 trusted binding startup timed out: "
                            "phase11_binding_transient_busy"
                        ) from None
                    time.sleep(min(delay, remaining))
                    delay = min(delay * 2, 0.5)
                except CloneCleanupContractError as exc:
                    raise Phase11LiveMissionError(
                        "Phase 11 trusted binding startup failed: "
                        "phase11_binding_acl_or_namespace_invalid"
                    ) from exc
            _harden_mode(self.binding_dir)
            return
        _reject_linked_ancestors(self.binding_dir.parent)
        self.binding_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _reject_linked_ancestors(self.binding_dir)
        info = self.binding_dir.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise Phase11LiveMissionError(
                "Phase 11 binding directory must be a regular directory"
            )
        if os.name == "posix":
            os.chmod(self.binding_dir, 0o700)
            if stat.S_IMODE(self.binding_dir.stat().st_mode) != 0o700:
                raise Phase11LiveMissionError(
                    "Phase 11 binding directory permissions are unsafe"
                )
        else:
            _harden_mode(self.binding_dir)

    @staticmethod
    def _vault_key(key_vault: BindingKeyVault | None) -> bytes:
        vault = key_vault or native_vault.NativeSecretVault(_VAULT_REFERENCE)
        value = vault.get_bytes()
        if value is None:
            candidate = secrets.token_bytes(32)
            vault.set_bytes(candidate)
            value = vault.get_bytes()
            if value is None or not hmac.compare_digest(value, candidate):
                raise Phase11LiveMissionError(
                    "Phase 11 native vault verification failed"
                )
        if len(value) != 32:
            raise Phase11LiveMissionError("Phase 11 native vault key is invalid")
        return bytes(value)

    def _binding_path(self, mission_id: str) -> Path:
        if not mission_id.startswith("mis_") or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            for char in mission_id
        ):
            raise Phase11LiveMissionError("invalid Phase 11 mission id")
        return self.binding_dir / f"{mission_id}.binding.json"

    def _patch_artifact_path(self, mission_id: str) -> Path:
        self._binding_path(mission_id)
        directory = self.binding_dir / "artifacts"
        if os.name != "nt":
            directory.mkdir(mode=0o700, exist_ok=True)
            _reject_linked_ancestors(directory)
        return directory / f"{mission_id}.patch.aesgcm"

    def _patch_cipher_key(self) -> bytes:
        if self._key is None:
            raise Phase11LiveMissionError("Phase 11 binding key is unavailable")
        return hashlib.sha256(
            b"ONYX/PHASE11/PATCH-ARTIFACT/AESGCM/V1\0" + self._key
        ).digest()

    def _write_patch_artifact(
        self, mission_id: str, patch: str, patch_sha256: str
    ) -> dict[str, Any]:
        plaintext = patch.encode("utf-8", errors="strict")
        if (
            not plaintext
            or len(plaintext) > MAX_PATCH_BYTES
            or hashlib.sha256(plaintext).hexdigest() != patch_sha256
        ):
            raise Phase11LiveMissionError("patch artifact input is invalid")
        nonce = secrets.token_bytes(12)
        associated = f"{mission_id}:{patch_sha256}".encode("ascii")
        encrypted = nonce + AESGCM(self._patch_cipher_key()).encrypt(
            nonce, plaintext, associated
        )
        path = self._patch_artifact_path(mission_id)
        if os.name == "nt":
            boundary = self._windows_binding_boundary
            if boundary is None:
                raise Phase11LiveMissionError(
                    "Phase 11 binding namespace is unavailable"
                )
            try:
                with boundary.session() as session:
                    session.publish_create(
                        f"artifacts/{path.name}", encrypted
                    )
            except Exception as exc:
                raise Phase11LiveMissionError(
                    "patch artifact publish failed"
                ) from exc
            return {
                "schema": "onyx.phase11.patch_artifact.v1",
                "name": f"artifacts/{path.name}",
                "ciphertext_sha256": hashlib.sha256(encrypted).hexdigest(),
                "ciphertext_bytes": len(encrypted),
                "plaintext_bytes": len(plaintext),
            }
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags, 0o600)
        try:
            offset = 0
            while offset < len(encrypted):
                written = os.write(descriptor, encrypted[offset : offset + 65_536])
                if written <= 0:
                    raise Phase11LiveMissionError("patch artifact write failed")
                offset += written
            os.fsync(descriptor)
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode) or observed.st_size != len(encrypted):
                raise Phase11LiveMissionError("patch artifact write failed")
        finally:
            os.close(descriptor)
        _harden_mode(path)
        return {
            "schema": "onyx.phase11.patch_artifact.v1",
            "name": f"artifacts/{path.name}",
            "ciphertext_sha256": hashlib.sha256(encrypted).hexdigest(),
            "ciphertext_bytes": len(encrypted),
            "plaintext_bytes": len(plaintext),
        }

    def _read_patch_artifact(self, document: Mapping[str, Any]) -> str:
        mission_id = str(document.get("mission_id", ""))
        raw = document.get("patch_artifact")
        autopilot = document.get("autopilot")
        if not isinstance(raw, Mapping) or not isinstance(autopilot, Mapping):
            raise Phase11LiveMissionError("patch artifact reference is unavailable")
        expected_name = f"artifacts/{mission_id}.patch.aesgcm"
        if (
            raw.get("schema") != "onyx.phase11.patch_artifact.v1"
            or raw.get("name") != expected_name
            or not isinstance(raw.get("ciphertext_bytes"), int)
            or not 28 < int(raw["ciphertext_bytes"]) <= MAX_PATCH_BYTES + 28
            or not isinstance(raw.get("plaintext_bytes"), int)
            or not 0 < int(raw["plaintext_bytes"]) <= MAX_PATCH_BYTES
        ):
            raise Phase11LiveMissionError("patch artifact reference is invalid")
        path = self.binding_dir / Path(expected_name)
        if os.name == "nt":
            boundary = self._windows_binding_boundary
            if boundary is None:
                raise Phase11LiveMissionError(
                    "Phase 11 binding namespace is unavailable"
                )
            try:
                with boundary.session() as session:
                    with session.read_held(
                        expected_name, max_bytes=MAX_PATCH_BYTES + 28
                    ) as encrypted:
                        if len(encrypted) != int(raw["ciphertext_bytes"]):
                            raise Phase11LiveMissionError(
                                "patch artifact changed"
                            )
                        return self._decrypt_patch_artifact(
                            mission_id, raw, autopilot, encrypted
                        )
            except Exception as exc:
                if isinstance(exc, Phase11LiveMissionError):
                    raise
                raise Phase11LiveMissionError(
                    "patch artifact changed"
                ) from exc
        else:
            _reject_linked_ancestors(path)
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(
                os, "O_NOFOLLOW", 0
            )
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_size != int(raw["ciphertext_bytes"])
                ):
                    raise Phase11LiveMissionError("patch artifact changed")
                encrypted = b""
                while len(encrypted) < opened.st_size:
                    block = os.read(
                        descriptor,
                        min(65_536, opened.st_size - len(encrypted)),
                    )
                    if not block:
                        raise Phase11LiveMissionError(
                            "patch artifact read failed"
                        )
                    encrypted += block
            finally:
                os.close(descriptor)
        return self._decrypt_patch_artifact(
            mission_id, raw, autopilot, encrypted
        )

    def _decrypt_patch_artifact(
        self,
        mission_id: str,
        raw: Mapping[str, Any],
        autopilot: Mapping[str, Any],
        encrypted: bytes,
    ) -> str:
        if hashlib.sha256(encrypted).hexdigest() != raw.get("ciphertext_sha256"):
            raise Phase11LiveMissionError("patch artifact authentication failed")
        patch_sha256 = str(autopilot.get("patch_sha256", ""))
        associated = f"{mission_id}:{patch_sha256}".encode("ascii")
        try:
            plaintext = AESGCM(self._patch_cipher_key()).decrypt(
                encrypted[:12], encrypted[12:], associated
            )
            patch = plaintext.decode("utf-8", errors="strict")
        except (InvalidTag, ValueError, UnicodeError) as exc:
            raise Phase11LiveMissionError("patch artifact decryption failed") from exc
        if (
            len(plaintext) != raw["plaintext_bytes"]
            or hashlib.sha256(plaintext).hexdigest() != patch_sha256
        ):
            raise Phase11LiveMissionError("patch artifact plaintext drift")
        return patch

    def _executable_plan_artifact_path(self, mission_id: str) -> Path:
        self._binding_path(mission_id)
        directory = self.binding_dir / "artifacts"
        if os.name != "nt":
            directory.mkdir(mode=0o700, exist_ok=True)
            _reject_linked_ancestors(directory)
        return directory / f"{mission_id}.executable-plan.aesgcm"

    def _executable_plan_cipher_key(self) -> bytes:
        if self._key is None:
            raise Phase11LiveMissionError("Phase 11 binding key is unavailable")
        return hashlib.sha256(
            b"ONYX/PHASE11/EXECUTABLE-PLAN/AESGCM/V1\0" + self._key
        ).digest()

    def _write_executable_plan_artifact(
        self, mission_id: str, plan: ExecutableGatePlanV1
    ) -> dict[str, Any]:
        payload = {
            "schema": plan.schema,
            "image_id": plan.image_id,
            "platform": plan.platform,
            "gates": [
                {
                    "argv": list(gate.argv),
                    "timeout_seconds": gate.timeout_seconds,
                    "max_output_bytes": gate.max_output_bytes,
                }
                for gate in plan.gates
            ],
            "plan_digest": plan.plan_digest,
        }
        plaintext = _canonical(payload)
        if (
            not plaintext
            or len(plaintext) > _MAX_EXECUTABLE_PLAN_ARTIFACT_BYTES
        ):
            raise Phase11LiveMissionError(
                "executable plan artifact input is invalid"
            )
        plaintext_sha256 = hashlib.sha256(plaintext).hexdigest()
        nonce = secrets.token_bytes(12)
        associated = (
            f"{mission_id}:{plan.plan_digest}:{plaintext_sha256}"
        ).encode("ascii")
        encrypted = nonce + AESGCM(
            self._executable_plan_cipher_key()
        ).encrypt(nonce, plaintext, associated)
        path = self._executable_plan_artifact_path(mission_id)
        relative = f"artifacts/{path.name}"
        if os.name == "nt":
            boundary = self._windows_binding_boundary
            if boundary is None:
                raise Phase11LiveMissionError(
                    "Phase 11 binding namespace is unavailable"
                )
            try:
                with boundary.session() as session:
                    session.publish_create(relative, encrypted)
            except Exception as exc:
                raise Phase11LiveMissionError(
                    "executable plan artifact publish failed"
                ) from exc
        else:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(path, flags, 0o600)
            try:
                offset = 0
                while offset < len(encrypted):
                    written = os.write(
                        descriptor, encrypted[offset : offset + 65_536]
                    )
                    if written <= 0:
                        raise Phase11LiveMissionError(
                            "executable plan artifact write failed"
                        )
                    offset += written
                os.fsync(descriptor)
                observed = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(observed.st_mode)
                    or observed.st_size != len(encrypted)
                ):
                    raise Phase11LiveMissionError(
                        "executable plan artifact write failed"
                    )
            finally:
                os.close(descriptor)
            _harden_mode(path)
        return {
            "schema": "onyx.phase11.executable_plan_artifact.v1",
            "name": relative,
            "plan_digest": plan.plan_digest,
            "plaintext_sha256": plaintext_sha256,
            "plaintext_bytes": len(plaintext),
            "ciphertext_sha256": hashlib.sha256(encrypted).hexdigest(),
            "ciphertext_bytes": len(encrypted),
        }

    def _read_executable_plan_artifact(
        self, document: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        mission_id = str(document.get("mission_id", ""))
        raw = document.get("executable_plan_artifact")
        metadata = document.get("executable_autopilot")
        expected_name = (
            f"artifacts/{mission_id}.executable-plan.aesgcm"
        )
        if (
            not isinstance(raw, Mapping)
            or not isinstance(metadata, Mapping)
            or raw.get("schema")
            != "onyx.phase11.executable_plan_artifact.v1"
            or raw.get("name") != expected_name
            or raw.get("plan_digest") != metadata.get("plan_digest")
            or not isinstance(raw.get("plan_digest"), str)
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(raw.get("plan_digest"))
            )
            or not isinstance(raw.get("plaintext_sha256"), str)
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(raw.get("plaintext_sha256"))
            )
            or type(raw.get("plaintext_bytes")) is not int
            or not 0
            < int(raw["plaintext_bytes"])
            <= _MAX_EXECUTABLE_PLAN_ARTIFACT_BYTES
            or not isinstance(raw.get("ciphertext_sha256"), str)
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(raw.get("ciphertext_sha256"))
            )
            or type(raw.get("ciphertext_bytes")) is not int
            or not 28
            < int(raw["ciphertext_bytes"])
            <= _MAX_EXECUTABLE_PLAN_ARTIFACT_BYTES + 28
        ):
            raise Phase11LiveMissionError(
                "executable plan artifact reference is invalid"
            )
        path = self.binding_dir / Path(expected_name)
        if os.name == "nt":
            boundary = self._windows_binding_boundary
            if boundary is None:
                raise Phase11LiveMissionError(
                    "Phase 11 binding namespace is unavailable"
                )
            try:
                with boundary.session() as session:
                    with session.read_held(
                        expected_name,
                        max_bytes=_MAX_EXECUTABLE_PLAN_ARTIFACT_BYTES
                        + 28,
                    ) as encrypted:
                        encrypted = bytes(encrypted)
            except Exception as exc:
                raise Phase11LiveMissionError(
                    "executable plan artifact changed"
                ) from exc
        else:
            _reject_linked_ancestors(path)
            flags = os.O_RDONLY | getattr(
                os, "O_BINARY", 0
            ) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_size != int(raw["ciphertext_bytes"])
                ):
                    raise Phase11LiveMissionError(
                        "executable plan artifact changed"
                    )
                encrypted = b""
                while len(encrypted) < opened.st_size:
                    block = os.read(
                        descriptor,
                        min(65_536, opened.st_size - len(encrypted)),
                    )
                    if not block:
                        raise Phase11LiveMissionError(
                            "executable plan artifact read failed"
                        )
                    encrypted += block
            finally:
                os.close(descriptor)
        if (
            len(encrypted) != int(raw["ciphertext_bytes"])
            or hashlib.sha256(encrypted).hexdigest()
            != raw.get("ciphertext_sha256")
        ):
            raise Phase11LiveMissionError(
                "executable plan artifact authentication failed"
            )
        associated = (
            f"{mission_id}:{raw['plan_digest']}:{raw['plaintext_sha256']}"
        ).encode("ascii")
        try:
            plaintext = AESGCM(
                self._executable_plan_cipher_key()
            ).decrypt(encrypted[:12], encrypted[12:], associated)
            payload = json.loads(plaintext.decode("ascii", errors="strict"))
        except (InvalidTag, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise Phase11LiveMissionError(
                "executable plan artifact decryption failed"
            ) from exc
        if (
            len(plaintext) != int(raw["plaintext_bytes"])
            or hashlib.sha256(plaintext).hexdigest()
            != raw["plaintext_sha256"]
            or not isinstance(payload, Mapping)
        ):
            raise Phase11LiveMissionError(
                "executable plan artifact plaintext drift"
            )
        return payload

    def _sign(self, digest: str) -> str:
        key = self._key
        if key is None:
            raise Phase11LiveMissionError("Phase 11 binding key is unavailable")
        return hmac.new(key, _DOMAIN + digest.encode("ascii"), hashlib.sha256).hexdigest()

    @staticmethod
    def _anchor_reference(mission_id: str) -> native_vault.SecretReference:
        return native_vault.SecretReference(
            "Onyx.Phase11AuthorityAnchor",
            mission_id,
            "Onyx Phase 11 mission authority high-water anchor",
        )

    @staticmethod
    def _checkpoint_reference(mission_id: str) -> native_vault.SecretReference:
        return native_vault.SecretReference(
            "Onyx.Phase11AuthorityCheckpoint",
            f"{mission_id}.checkpoint",
            "Onyx Phase 11 non-replayable authority checkpoint",
        )

    def _authority_vault(
        self, reference: native_vault.SecretReference
    ) -> BindingKeyVault:
        try:
            vault = self._anchor_vault_factory(reference)
        except Exception as exc:
            raise Phase11LiveMissionError(
                "Phase 11 authority anchor vault is unavailable"
            ) from exc
        if not callable(getattr(vault, "get_bytes", None)) or not callable(
            getattr(vault, "set_bytes", None)
        ):
            raise Phase11LiveMissionError(
                "Phase 11 authority anchor vault contract diverges"
            )
        return vault

    def _anchor_vault(self, mission_id: str) -> BindingKeyVault:
        return self._authority_vault(self._anchor_reference(mission_id))

    def _checkpoint_vault(self, mission_id: str) -> BindingKeyVault:
        return self._authority_vault(self._checkpoint_reference(mission_id))

    def _anchor_document(self, snapshot: Any) -> dict[str, Any]:
        payload = {
            "schema": "onyx.phase11.authority_anchor.v1",
            "mission_id": snapshot.mission_id,
            "event_seq": snapshot.event_seq,
            "event_hash": snapshot.event_hash,
        }
        key = self._key
        if key is None:
            raise Phase11LiveMissionError("Phase 11 binding key is unavailable")
        signature = hmac.new(
            key, _ANCHOR_DOMAIN + _canonical(payload), hashlib.sha256
        ).hexdigest()
        return {**payload, "signature": signature}

    def _write_anchor(self, snapshot: Any) -> None:
        with _PROCESS_HIGH_WATER_LOCK:
            self._write_anchor_locked(snapshot)

    def _write_anchor_locked(self, snapshot: Any) -> None:
        document = self._anchor_document(snapshot)
        raw = _canonical(document)
        process_high = _PROCESS_HIGH_WATER.get(snapshot.mission_id)
        if (
            process_high is None
            and len(_PROCESS_HIGH_WATER)
            >= _MAX_PROCESS_HIGH_WATER_ENTRIES
        ):
            raise Phase11LiveMissionError(
                "Phase 11 process high-water capacity is exhausted"
            )
        if process_high is not None and (
            snapshot.event_seq < process_high[0]
            or (
                snapshot.event_seq == process_high[0]
                and snapshot.event_hash != process_high[1]
            )
        ):
            raise Phase11LiveMissionError(
                "Phase 11 process authority high-water cannot move backward"
            )
        checkpoint = self._read_checkpoint(snapshot.mission_id, required=False)
        if checkpoint is not None:
            if checkpoint["event_seq"] > snapshot.event_seq:
                raise Phase11LiveMissionError(
                    "Phase 11 authority checkpoint cannot move backward"
                )
            if (
                checkpoint["event_seq"] == snapshot.event_seq
                and checkpoint["event_hash"] != snapshot.event_hash
            ):
                raise Phase11LiveMissionError(
                    "Phase 11 authority checkpoint fork detected"
                )
        vault = self._anchor_vault(snapshot.mission_id)
        try:
            vault.set_bytes(raw)
            observed = vault.get_bytes()
        except Exception as exc:
            raise Phase11LiveMissionError(
                "Phase 11 authority anchor could not be persisted"
            ) from exc
        if observed is None or not hmac.compare_digest(bytes(observed), raw):
            raise Phase11LiveMissionError(
                "Phase 11 authority anchor verification failed"
            )
        anchor_sha256 = hashlib.sha256(raw).hexdigest()
        checkpoint_payload = {
            "schema": "onyx.phase11.authority_checkpoint.v1",
            "mission_id": snapshot.mission_id,
            "event_seq": snapshot.event_seq,
            "event_hash": snapshot.event_hash,
            "anchor_sha256": anchor_sha256,
        }
        key = self._key
        if key is None:
            raise Phase11LiveMissionError("Phase 11 binding key is unavailable")
        checkpoint_document = {
            **checkpoint_payload,
            "signature": hmac.new(
                key,
                _ANCHOR_DOMAIN + b"CHECKPOINT\0" + _canonical(checkpoint_payload),
                hashlib.sha256,
            ).hexdigest(),
        }
        checkpoint_raw = _canonical(checkpoint_document)
        checkpoint_vault = self._checkpoint_vault(snapshot.mission_id)
        try:
            checkpoint_vault.set_bytes(checkpoint_raw)
            observed_checkpoint = checkpoint_vault.get_bytes()
        except Exception as exc:
            raise Phase11LiveMissionError(
                "Phase 11 authority checkpoint could not be persisted"
            ) from exc
        if observed_checkpoint is None or not hmac.compare_digest(
            bytes(observed_checkpoint), checkpoint_raw
        ):
            raise Phase11LiveMissionError(
                "Phase 11 authority checkpoint verification failed"
            )
        current = _PROCESS_HIGH_WATER.get(snapshot.mission_id)
        if current is not None and snapshot.event_seq < current[0]:
            raise Phase11LiveMissionError(
                "Phase 11 process authority high-water raced backward"
            )
        _PROCESS_HIGH_WATER[snapshot.mission_id] = (
            snapshot.event_seq,
            snapshot.event_hash,
        )

    def _read_checkpoint(
        self, mission_id: str, *, required: bool = True
    ) -> dict[str, Any] | None:
        try:
            raw = self._checkpoint_vault(mission_id).get_bytes()
        except Exception as exc:
            raise Phase11LiveMissionError(
                "Phase 11 authority checkpoint could not be read"
            ) from exc
        if raw is None:
            if not required:
                return None
            raise Phase11LiveMissionError(
                "Phase 11 authority checkpoint is unavailable"
            )
        if not 1 <= len(raw) <= 2048:
            raise Phase11LiveMissionError(
                "Phase 11 authority checkpoint is malformed"
            )
        try:
            document = json.loads(bytes(raw).decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise Phase11LiveMissionError(
                "Phase 11 authority checkpoint is malformed"
            ) from exc
        if not isinstance(document, dict):
            raise Phase11LiveMissionError(
                "Phase 11 authority checkpoint contract diverges"
            )
        payload = {
            item: value for item, value in document.items() if item != "signature"
        }
        key = self._key
        if key is None:
            raise Phase11LiveMissionError("Phase 11 binding key is unavailable")
        expected = hmac.new(
            key,
            _ANCHOR_DOMAIN + b"CHECKPOINT\0" + _canonical(payload),
            hashlib.sha256,
        ).hexdigest()
        if (
            set(document)
            != {
                "schema",
                "mission_id",
                "event_seq",
                "event_hash",
                "anchor_sha256",
                "signature",
            }
            or document.get("schema") != "onyx.phase11.authority_checkpoint.v1"
            or document.get("mission_id") != mission_id
            or isinstance(document.get("event_seq"), bool)
            or not isinstance(document.get("event_seq"), int)
            or document["event_seq"] <= 0
            or not isinstance(document.get("event_hash"), str)
            or len(document["event_hash"]) != 64
            or not isinstance(document.get("anchor_sha256"), str)
            or len(document["anchor_sha256"]) != 64
            or not isinstance(document.get("signature"), str)
            or not hmac.compare_digest(document["signature"], expected)
        ):
            raise Phase11LiveMissionError(
                "Phase 11 authority checkpoint authentication failed"
            )
        return document

    def _read_anchor(self, mission_id: str) -> dict[str, Any]:
        try:
            raw = self._anchor_vault(mission_id).get_bytes()
        except Exception as exc:
            raise Phase11LiveMissionError(
                "Phase 11 authority anchor could not be read"
            ) from exc
        if raw is None or not 1 <= len(raw) <= 2048:
            raise Phase11LiveMissionError(
                "Phase 11 authority anchor is unavailable"
            )
        try:
            document = json.loads(bytes(raw).decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise Phase11LiveMissionError(
                "Phase 11 authority anchor is malformed"
            ) from exc
        if not isinstance(document, dict):
            raise Phase11LiveMissionError(
                "Phase 11 authority anchor contract diverges"
            )
        payload = {
            key: value for key, value in document.items() if key != "signature"
        }
        key = self._key
        if key is None:
            raise Phase11LiveMissionError("Phase 11 binding key is unavailable")
        expected = hmac.new(
            key, _ANCHOR_DOMAIN + _canonical(payload), hashlib.sha256
        ).hexdigest()
        if (
            set(document)
            != {
                "schema",
                "mission_id",
                "event_seq",
                "event_hash",
                "signature",
            }
            or document.get("schema") != "onyx.phase11.authority_anchor.v1"
            or document.get("mission_id") != mission_id
            or isinstance(document.get("event_seq"), bool)
            or not isinstance(document.get("event_seq"), int)
            or document["event_seq"] <= 0
            or not isinstance(document.get("event_hash"), str)
            or len(document["event_hash"]) != 64
            or not isinstance(document.get("signature"), str)
            or not hmac.compare_digest(document["signature"], expected)
        ):
            raise Phase11LiveMissionError(
                "Phase 11 authority anchor authentication failed"
            )
        return document

    def _validate_anchor(self, snapshot: Any, *, advance: bool = False) -> None:
        with _PROCESS_HIGH_WATER_LOCK:
            self._validate_anchor_locked(snapshot, advance=advance)

    def _validate_anchor_locked(
        self, snapshot: Any, *, advance: bool = False
    ) -> None:
        anchor = self._read_anchor(snapshot.mission_id)
        checkpoint = self._read_checkpoint(snapshot.mission_id)
        anchor_raw = _canonical(anchor)
        pair_diverges = (
            checkpoint["event_seq"] != anchor["event_seq"]
            or checkpoint["event_hash"] != anchor["event_hash"]
            or not hmac.compare_digest(
                checkpoint["anchor_sha256"], hashlib.sha256(anchor_raw).hexdigest()
            )
        )
        process_high = _PROCESS_HIGH_WATER.get(snapshot.mission_id)
        if process_high is not None and (
            anchor["event_seq"] < process_high[0]
            or (
                anchor["event_seq"] == process_high[0]
                and anchor["event_hash"] != process_high[1]
            )
        ):
            raise Phase11LiveMissionError(
                "Phase 11 coordinated anchor replay detected in trusted process"
            )
        if pair_diverges:
            if anchor["event_seq"] <= checkpoint["event_seq"]:
                raise Phase11LiveMissionError(
                    "Phase 11 authority anchor replay or checkpoint divergence detected"
                )
            if anchor["event_seq"] > snapshot.event_seq:
                raise Phase11LiveMissionError(
                    "MissionStore authority rolled back behind partial native anchor"
                )
            partial_event = self.store.authority_event_at(
                snapshot.mission_id, anchor["event_seq"]
            )
            if not hmac.compare_digest(
                str(partial_event["event_hash"]), anchor["event_hash"]
            ):
                raise Phase11LiveMissionError(
                    "Phase 11 partial anchor is not an authenticated authority ancestor"
                )
            self._write_anchor_locked(snapshot)
            anchor = self._read_anchor(snapshot.mission_id)
            checkpoint = self._read_checkpoint(snapshot.mission_id)
            anchor_raw = _canonical(anchor)
            if (
                checkpoint["event_seq"] != anchor["event_seq"]
                or checkpoint["event_hash"] != anchor["event_hash"]
                or not hmac.compare_digest(
                    checkpoint["anchor_sha256"],
                    hashlib.sha256(anchor_raw).hexdigest(),
                )
            ):
                raise Phase11LiveMissionError(
                    "Phase 11 authority pair repair did not converge"
                )
        if anchor["event_seq"] > snapshot.event_seq:
            raise Phase11LiveMissionError(
                "MissionStore authority rolled back behind native anchor"
            )
        anchored_event = self.store.authority_event_at(
            snapshot.mission_id, anchor["event_seq"]
        )
        if not hmac.compare_digest(
            str(anchored_event["event_hash"]), anchor["event_hash"]
        ):
            raise Phase11LiveMissionError(
                "MissionStore authority does not contain native anchor"
            )
        if advance and anchor["event_seq"] < snapshot.event_seq:
            self._write_anchor(snapshot)

    def _write_binding_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
        document = {
            **payload,
            "binding_digest": digest,
            "signature": self._sign(digest),
        }
        path = self._binding_path(str(payload["mission_id"]))
        data = _canonical(document)
        if os.name == "nt":
            boundary = self._windows_binding_boundary
            if boundary is None:
                raise Phase11LiveMissionError(
                    "Phase 11 binding namespace is unavailable"
                )
            try:
                with boundary.session() as session:
                    session.publish_create(path.name, data)
            except Exception as exc:
                raise Phase11LiveMissionError(
                    "Phase 11 binding publish failed"
                ) from exc
            _harden_mode(path)
            return document
        _reject_linked_ancestors(path.parent)
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags, 0o600)
        try:
            offset = 0
            while offset < len(data):
                written = os.write(descriptor, data[offset:])
                if written <= 0:
                    raise OSError("binding write made no progress")
                offset += written
            os.fsync(descriptor)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_size != len(data)
            ):
                raise Phase11LiveMissionError(
                    "Phase 11 binding identity changed during creation"
                )
        finally:
            os.close(descriptor)
        if os.name == "posix":
            os.chmod(path, 0o600)
            if stat.S_IMODE(path.stat().st_mode) != 0o600:
                raise Phase11LiveMissionError(
                    "Phase 11 binding permissions are unsafe"
                )
        else:
            _harden_mode(path)
        return document

    def _read_binding(
        self, mission_id: str, *, required: bool = True
    ) -> dict[str, Any] | None:
        self._require_enabled()
        path = self._binding_path(mission_id)
        if os.name == "nt":
            boundary = self._windows_binding_boundary
            if boundary is None:
                raise Phase11LiveMissionError(
                    "Phase 11 binding namespace is unavailable"
            )
            try:
                with boundary.session() as session:
                    if not session.exists(
                        path.name, directory=False
                    ):
                        if required:
                            raise Phase11LiveMissionError(
                                "Phase 11 immutable binding is unavailable"
                            )
                        return None
                    with session.read_held(
                        path.name, max_bytes=_MAX_BINDING_BYTES
                    ) as raw:
                        return self._validate_binding_document(
                            mission_id, raw
                        )
            except Exception as exc:
                if isinstance(exc, Phase11LiveMissionError):
                    raise
                raise Phase11LiveMissionError(
                    "Phase 11 binding identity is invalid"
                ) from exc
        _reject_linked_ancestors(path.parent)
        try:
            before = path.lstat()
        except FileNotFoundError:
            if required:
                raise Phase11LiveMissionError(
                    "Phase 11 immutable binding is unavailable"
                )
            return None
        if (
            stat.S_ISLNK(before.st_mode)
            or _is_reparse(path)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 1 <= before.st_size <= _MAX_BINDING_BYTES
        ):
            raise Phase11LiveMissionError("Phase 11 binding identity is invalid")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                (opened.st_dev, opened.st_ino)
                != (before.st_dev, before.st_ino)
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_size != before.st_size
            ):
                raise Phase11LiveMissionError(
                    "Phase 11 binding identity changed during open"
                )
            chunks: list[bytes] = []
            remaining = _MAX_BINDING_BYTES + 1
            while remaining:
                block = os.read(descriptor, min(65_536, remaining))
                if not block:
                    break
                chunks.append(block)
                remaining -= len(block)
            raw = b"".join(chunks)
        finally:
            os.close(descriptor)
        after = path.lstat()
        if (
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            or stat.S_ISLNK(after.st_mode)
            or _is_reparse(path)
            or len(raw) != before.st_size
        ):
            raise Phase11LiveMissionError(
                "Phase 11 binding changed during descriptor-bound read"
            )
        return self._validate_binding_document(mission_id, raw)

    def _validate_binding_document(
        self, mission_id: str, raw: bytes
    ) -> dict[str, Any]:
        try:
            document = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise Phase11LiveMissionError("Phase 11 binding is malformed") from exc
        if not isinstance(document, dict):
            raise Phase11LiveMissionError("Phase 11 binding contract diverges")
        payload = {
            key: value
            for key, value in document.items()
            if key not in {"binding_digest", "signature"}
        }
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
        if (
            document.get("schema") != BINDING_SCHEMA
            or document.get("mission_id") != mission_id
            or document.get("mission_type")
            not in {
                MISSION_TYPE,
                AUTOPILOT_MISSION_TYPE,
                AWAY_MISSION_TYPE,
                EXTERNAL_AGENT_MISSION_TYPE,
            }
            or not isinstance(document.get("binding_digest"), str)
            or not hmac.compare_digest(document["binding_digest"], digest)
            or not isinstance(document.get("signature"), str)
            or not hmac.compare_digest(document["signature"], self._sign(digest))
        ):
            raise Phase11LiveMissionError(
                "Phase 11 binding authentication failed"
            )
        return document

    def _validate_authority_detail(
        self,
        document: Mapping[str, Any],
        event: str,
        detail: Mapping[str, Any],
    ) -> None:
        if event == "phase11.bound":
            expected_keys = {
                "mission_type",
                "binding_digest",
                "binding_signature",
                "authority_public_key",
                "authority_signature",
            }
            if (
                set(detail) != expected_keys
                or detail.get("mission_type") != document.get("mission_type")
                or detail.get("binding_digest") != document.get("binding_digest")
                or detail.get("binding_signature") != document.get("signature")
                or detail.get("authority_public_key")
                != document.get("authority_public_key")
            ):
                raise Phase11LiveMissionError(
                    "Phase 11 authority binding detail is invalid"
                )
            self._verify_authority_signature(document, event, detail)
            return
        if event == "phase11.kill":
            if (
                set(detail) != {"reason", "authority_signature"}
                or detail.get("reason") != "owner_cancel_requested"
            ):
                raise Phase11LiveMissionError(
                    "Phase 11 kill authority detail is invalid"
                )
            self._verify_authority_signature(document, event, detail)
            return
        if event == "phase11.reconciliation":
            expected_keys = {
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
            }
            executable = document.get("executable_autopilot")
            unsigned = {
                key: value
                for key, value in detail.items()
                if key not in {"authority_signature", "decision_hmac_sha256"}
            }
            key = self._key
            expected_hmac = (
                ""
                if key is None
                else hmac.new(
                    key,
                    _RECONCILIATION_DOMAIN + _canonical(unsigned),
                    hashlib.sha256,
                ).hexdigest()
            )
            resolution_projection = {
                item: unsigned.get(item)
                for item in (
                    "schema",
                    "decision",
                    "binding_digest",
                    "plan_digest",
                    "gate_index",
                    "execution_id",
                    "intent_sha256",
                    "recovered_receipt_sha256",
                )
            }
            expected_resolution_id = (
                ""
                if key is None
                else hmac.new(
                    key,
                    _RECONCILIATION_DOMAIN
                    + b"RESOLUTION\0"
                    + _canonical(resolution_projection),
                    hashlib.sha256,
                ).hexdigest()
            )
            if (
                set(detail) != expected_keys
                or document.get("mission_type") != AUTOPILOT_MISSION_TYPE
                or not isinstance(executable, Mapping)
                or detail.get("schema") != _RECONCILIATION_SCHEMA
                or detail.get("decision") not in {
                    "still_unknown",
                    "abandon",
                    "recovered_receipt",
                }
                or detail.get("binding_digest") != document.get("binding_digest")
                or detail.get("plan_digest") != executable.get("plan_digest")
                or isinstance(executable.get("gate_count"), bool)
                or not isinstance(executable.get("gate_count"), int)
                or isinstance(detail.get("gate_index"), bool)
                or not isinstance(detail.get("gate_index"), int)
                or not 0
                <= int(detail["gate_index"])
                < int(executable["gate_count"])
                or not isinstance(detail.get("execution_id"), str)
                or re.fullmatch(r"[0-9a-f]{64}", str(detail["execution_id"]))
                is None
                or not isinstance(detail.get("intent_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", str(detail["intent_sha256"]))
                is None
                or (
                    detail.get("decision") == "recovered_receipt"
                    and re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(detail.get("recovered_receipt_sha256", "")),
                    )
                    is None
                )
                or (
                    detail.get("decision") != "recovered_receipt"
                    and detail.get("recovered_receipt_sha256") != ""
                )
                or not isinstance(detail.get("issued_at_ns"), int)
                or isinstance(detail.get("issued_at_ns"), bool)
                or int(detail["issued_at_ns"]) <= 0
                or not isinstance(detail.get("decision_hmac_sha256"), str)
                or not hmac.compare_digest(
                    str(detail["decision_hmac_sha256"]), expected_hmac
                )
                or not hmac.compare_digest(
                    str(detail.get("resolution_id", "")),
                    expected_resolution_id,
                )
            ):
                raise Phase11LiveMissionError(
                    "Phase 11 executable reconciliation authority is invalid"
                )
            self._verify_authority_signature(document, event, detail)
            return
        if event != "phase11.receipt":
            raise Phase11LiveMissionError("unsupported Phase 11 authority event")
        if document.get("mission_type") != MISSION_TYPE:
            raise Phase11LiveMissionError(
                "autopilot authority does not accept read-only receipts"
            )
        expected_keys = {
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
        }
        stage = detail.get("stage")
        if (
            set(detail) != expected_keys
            or not isinstance(stage, str)
            or not 1 <= len(stage) <= 80
            or (
                stage != "before_approve"
                and stage
                not in {
                    *(f"before_tool:{tool}" for tool in _PLAN_TOOLS),
                    *(f"after_tool:{tool}" for tool in _PLAN_TOOLS),
                }
            )
        ):
            raise Phase11LiveMissionError(
                "Phase 11 receipt authority schema is invalid"
            )
        try:
            receipt = VerificationReceiptV1(
                schema=str(detail["schema"]),
                root=str(detail["root"]),
                baseline_sha256=str(detail["baseline_sha256"]),
                observed_sha256=str(detail["observed_sha256"]),
                verdict=str(detail["verdict"]),
                reason=str(detail["reason"]),
                issued_at_ns=detail["issued_at_ns"],
                signature=str(detail["receipt_signature"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise Phase11LiveMissionError(
                "Phase 11 receipt authority schema is invalid"
            ) from exc
        baseline = document.get("baseline")
        if (
            not isinstance(baseline, Mapping)
            or receipt.root != baseline.get("root")
            or receipt.baseline_sha256 != baseline.get("snapshot_sha256")
        ):
            raise Phase11LiveMissionError(
                "Phase 11 receipt authority binding diverges"
            )
        self._require_enabled().validate_receipt(receipt)
        self._verify_authority_signature(document, event, detail)

    @staticmethod
    def _authority_signature_message(
        mission_id: str, event: str, detail: Mapping[str, Any]
    ) -> bytes:
        unsigned = {
            key: value
            for key, value in detail.items()
            if key != "authority_signature"
        }
        return _EVENT_SIGNATURE_DOMAIN + _canonical(
            {
                "mission_id": mission_id,
                "event": event,
                "detail": unsigned,
            }
        )

    def _sign_authority_detail(
        self, mission_id: str, event: str, detail: Mapping[str, Any]
    ) -> dict[str, Any]:
        signing_key = self._authority_signing_key
        if signing_key is None:
            raise Phase11LiveMissionError(
                "Phase 11 authority signing identity is unavailable"
            )
        normalized = dict(detail)
        normalized["authority_signature"] = signing_key.sign(
            self._authority_signature_message(mission_id, event, normalized)
        ).hex()
        return normalized

    def _verify_authority_signature(
        self,
        document: Mapping[str, Any],
        event: str,
        detail: Mapping[str, Any],
    ) -> None:
        public_hex = document.get("authority_public_key")
        signature_hex = detail.get("authority_signature")
        if (
            not isinstance(public_hex, str)
            or len(public_hex) != 64
            or not isinstance(signature_hex, str)
            or len(signature_hex) != 128
        ):
            raise Phase11LiveMissionError(
                "Phase 11 authority signature fields are invalid"
            )
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex)).verify(
                bytes.fromhex(signature_hex),
                self._authority_signature_message(
                    str(document["mission_id"]), event, detail
                ),
            )
        except (KeyError, ValueError, InvalidSignature) as exc:
            raise Phase11LiveMissionError(
                "Phase 11 authority event signature is invalid"
            ) from exc

    def _validate_authority_append(
        self, mission_id: str, event: str, detail: Mapping[str, Any]
    ) -> None:
        document = self._read_binding(mission_id)
        if document is None:
            raise Phase11LiveMissionError(
                "Phase 11 immutable binding is unavailable"
            )
        self._validate_authority_detail(document, event, detail)

    def _validate_authority_history(
        self,
        document: Mapping[str, Any],
        events: Iterable[Mapping[str, Any]],
    ) -> None:
        phase_events = [
            event
            for event in events
            if str(event.get("event", "")).startswith("phase11.")
        ]
        if (
            not phase_events
            or phase_events[0].get("event") != "phase11.bound"
            or sum(
                event.get("event") == "phase11.bound" for event in phase_events
            )
            != 1
            or sum(event.get("event") == "phase11.kill" for event in phase_events)
            > 1
        ):
            raise Phase11LiveMissionError(
                "Phase 11 authority event history is invalid"
            )
        killed = False
        abandoned = False
        reconciliation_ids: set[str] = set()
        for item in phase_events:
            event = str(item.get("event", ""))
            detail = item.get("detail")
            if not isinstance(detail, Mapping):
                raise Phase11LiveMissionError(
                    "Phase 11 authority event detail is invalid"
                )
            if killed or (abandoned and event != "phase11.kill"):
                raise Phase11LiveMissionError(
                    "Phase 11 authority event follows terminal reconciliation"
                )
            self._validate_authority_detail(document, event, detail)
            killed = event == "phase11.kill"
            if event == "phase11.reconciliation":
                resolution_id = str(detail.get("resolution_id", ""))
                if resolution_id in reconciliation_ids:
                    raise Phase11LiveMissionError(
                        "Phase 11 reconciliation replay detected"
                    )
                reconciliation_ids.add(resolution_id)
                abandoned = detail.get("decision") == "abandon"

    def _authority_event(
        self, mission_id: str, event: str, detail: dict[str, Any]
    ) -> None:
        capability = self._authority_capability
        if capability is None:
            raise Phase11LiveMissionError(
                "Phase 11 authority capability is unavailable"
            )
        signed_detail = self._sign_authority_detail(
            mission_id, event, detail
        )
        snapshot = self.store.append_authority_event_v1(
            mission_id, event, signed_detail, capability=capability
        )
        self._write_anchor(snapshot)

    def _events(self, mission_id: str) -> list[dict[str, Any]]:
        return self.store.events(mission_id)

    @staticmethod
    def _budgets(
        *,
        max_steps: object,
        max_seconds: object,
        max_retries: object,
        provider_cost_limit: object,
    ) -> tuple[int, float, int]:
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or max_steps != len(_PLAN_TOOLS)
        ):
            raise ValueError(f"{MISSION_TYPE} max_steps must be {len(_PLAN_TOOLS)}")
        if (
            isinstance(max_seconds, bool)
            or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds)
            or not 1 <= float(max_seconds) <= 900
        ):
            raise ValueError(f"{MISSION_TYPE} max_seconds must be between 1 and 900")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= 2
        ):
            raise ValueError(f"{MISSION_TYPE} max_retries must be between 0 and 2")
        if (
            isinstance(provider_cost_limit, bool)
            or not isinstance(provider_cost_limit, (int, float))
            or not math.isfinite(provider_cost_limit)
            or float(provider_cost_limit) != 0.0
        ):
            raise ValueError(f"{MISSION_TYPE} provider cost must be zero")
        return max_steps, float(max_seconds), max_retries

    @staticmethod
    def _fixed_plan(root: str, query: str) -> list[dict[str, Any]]:
        return [
            {"tool": "local_system_status", "args": {}},
            {
                "tool": "workspace_inventory",
                "args": {
                    "root": root,
                    "path": ".",
                    "max_files": 500,
                    "max_dirs": 200,
                    "max_seconds": 5,
                },
            },
            {
                "tool": "workspace_text_search",
                "args": {
                    "root": root,
                    "path": ".",
                    "query": query,
                    "max_files": 500,
                    "max_dirs": 200,
                    "max_results": 100,
                    "max_seconds": 5,
                },
            },
        ]

    def _database_steps(self, mission_id: str) -> list[dict[str, Any]]:
        return self.store.authority_plan_steps_v1(mission_id)

    def _validate_current_binding(
        self,
        mission_id: str,
        *,
        advance_anchor: bool = False,
        reconcile_kill: bool = False,
    ) -> dict[str, Any]:
        authority_view = self.store.phase11_authority_view_v1(mission_id)
        authority = authority_view["snapshot"]
        document = self._read_binding(mission_id)
        assert document is not None
        events = authority_view["events"]
        self._validate_authority_history(document, events)
        bindings = [
            event
            for event in events
            if event["event"] == "phase11.bound"
        ]
        if len(bindings) != 1:
            raise Phase11LiveMissionError(
                "Phase 11 authority binding cardinality diverges"
            )
        detail = bindings[0]["detail"]
        if (
            detail.get("binding_digest") != document["binding_digest"]
            or detail.get("binding_signature") != document["signature"]
            or detail.get("mission_type") != document.get("mission_type")
        ):
            raise Phase11LiveMissionError(
                "Phase 11 authority binding does not match immutable binding"
            )
        if (
            authority_view["plan_digest"] != document.get("plan_digest")
            or authority_view["fixed_steps"] != document.get("fixed_steps")
        ):
            raise Phase11LiveMissionError(
                "Phase 11 current mission plan diverges from immutable binding"
            )
        baseline = _snapshot_from_dict(document["baseline"])
        self._require_enabled().validate_snapshot(baseline)
        if document.get("mission_type") == AUTOPILOT_MISSION_TYPE:
            if self.autopilot is None:
                raise Phase11LiveMissionError(
                    "project_autopilot_v1 is not explicitly enabled"
                )
            autopilot = document.get("autopilot")
            fixed_args = (
                document.get("fixed_steps", [{}])[0].get("args", {})
            )
            if (
                not isinstance(autopilot, Mapping)
                or autopilot.get("input_digest")
                != fixed_args.get("input_digest")
            ):
                raise Phase11LiveMissionError(
                    "Phase 11 autopilot envelope diverges from fixed plan"
                )
            executable_plan = self._executable_plan(document)
            executable_fields = {
                "executable_plan_digest",
                "executable_image_id",
                "executable_platform",
                "executable_gate_count",
            }
            if executable_plan is None:
                if (
                    fixed_args.get("repository_code_execution") is not False
                    or executable_fields.intersection(fixed_args)
                ):
                    raise Phase11LiveMissionError(
                        "static Project Autopilot truth state diverges"
                    )
            else:
                if (
                    fixed_args.get("repository_code_execution") is not True
                    or fixed_args.get("executable_plan_digest")
                    != executable_plan.plan_digest
                    or fixed_args.get("executable_image_id")
                    != executable_plan.image_id
                    or fixed_args.get("executable_platform")
                    != executable_plan.platform
                    or fixed_args.get("executable_gate_count")
                    != len(executable_plan.gates)
                ):
                    raise Phase11LiveMissionError(
                        "executable Project Autopilot plan diverges from fixed plan"
                    )
        if document.get("mission_type") == AWAY_MISSION_TYPE:
            if self.away_mode is None or self._key is None:
                raise Phase11LiveMissionError(
                    "governed browser Away Mode is not explicitly enabled"
                )
            try:
                envelope = BrowserActionEnvelopeV1.from_binding(
                    document.get("away"),
                    signing_key=self._key,
                )
            except (GovernedAwayError, GovernedAwayWaiting) as exc:
                raise Phase11LiveMissionError(
                    "governed browser Away envelope is invalid"
                ) from exc
            fixed_steps = document.get("fixed_steps", [])
            fixed_args = fixed_steps[0].get("args", {}) if fixed_steps else {}
            if (
                envelope.mission_id != mission_id
                or envelope.workspace_root != baseline.root
                or envelope.approval_digest != document.get("plan_digest")
                or len(fixed_steps) != 1
                or fixed_steps[0].get("tool") != AWAY_TOOL_NAME
                or fixed_args
                != {
                    "intent_digest": envelope.intent_digest,
                    "principal_id": envelope.principal_id,
                    "away_session_id": envelope.away_session_id,
                    "lease_generation": envelope.lease_generation,
                    "workspace_id": envelope.workspace_id,
                    "profile_id": envelope.profile_id,
                    "provider_id": envelope.provider_id,
                    "account_id": envelope.account_id,
                    "target_url": envelope.target_url,
                    "target_origin": envelope.target_origin,
                    "target_domain": envelope.target_domain,
                    "allowed_domains": list(envelope.allowed_domains),
                    "action": envelope.action,
                    "capture_screenshot": envelope.capture_screenshot,
                    "max_seconds": envelope.max_seconds,
                    "max_uses": envelope.max_uses,
                    "network_request_budget": (
                        envelope.network_request_budget
                    ),
                    "output_byte_budget": envelope.output_byte_budget,
                    "screenshot_budget": envelope.screenshot_budget,
                    "paid_cost_budget": envelope.paid_cost_budget,
                    "approval_policy_id": envelope.approval_policy_id,
                    "key_epoch": envelope.key_epoch,
                    "stop_policy": list(envelope.stop_policy),
                    "issued_at_ns": envelope.issued_at_ns,
                    "not_before_ns": envelope.not_before_ns,
                    "expires_at_ns": envelope.expires_at_ns,
                    "computer_control": False,
                    "runtime_nonce": document.get("away_runtime_nonce"),
                }
            ):
                raise Phase11LiveMissionError(
                    "governed browser Away plan diverges from immutable binding"
                )
        if document.get("mission_type") == EXTERNAL_AGENT_MISSION_TYPE:
            if self._key is None:
                raise Phase11LiveMissionError(
                    "external coding agent is not explicitly enabled"
                )
            adapter = self._ensure_external_agent()
            envelope = self._external_agent_envelope(document)
            fixed_steps = document.get("fixed_steps", [])
            fixed_args = fixed_steps[0].get("args", {}) if fixed_steps else {}
            expected_args = {
                "workspace_id": envelope.workspace_id,
                "repository_commit": envelope.repository_commit,
                "owner_git_sha256": envelope.owner_git_sha256,
                "repository_blob_manifest_sha256": (
                    envelope.repository_blob_manifest_sha256
                ),
                "repository_blob_count": envelope.repository_blob_count,
                "git_executable_path": envelope.git_executable_path,
                "git_executable_sha256": envelope.git_executable_sha256,
                "git_executable_identity_sha256": (
                    envelope.git_executable_identity_sha256
                ),
                "git_executable_file_id": envelope.git_executable_file_id,
                "allowed_roots": list(envelope.allowed_roots),
                "provider_id": envelope.provider_id,
                "provider_version": envelope.provider_version,
                "provider_executable_path": str(
                    redact(envelope.provider_executable_path)
                ),
                "provider_executable_sha256": (
                    envelope.provider_executable_sha256
                ),
                "provider_executable_identity_sha256": (
                    envelope.provider_executable_identity_sha256
                ),
                "provider_executable_file_id": (
                    envelope.provider_executable_file_id
                ),
                "provider_account_sha256": (
                    envelope.provider_account_sha256
                ),
                "model": envelope.model,
                "provider_budget_usd": envelope.max_budget_usd,
                "max_seconds": envelope.max_seconds,
                "max_output_bytes": envelope.max_output_bytes,
                "task_sha256": envelope.task_sha256,
                "task_bytes": envelope.task_bytes,
                "prior_artifact_sha256": envelope.prior_artifact_sha256,
                "mutation_boundary": "detached_clone_patch_output_only",
                "external_pr_creation": False,
                "runtime_nonce": envelope.nonce,
            }
            if (
                envelope.mission_id != mission_id
                or envelope.workspace_root != baseline.root
                or envelope.repository_commit != baseline.head
                or envelope.approval_digest != document.get("plan_digest")
                or len(fixed_steps) != 1
                or fixed_steps[0].get("tool") != EXTERNAL_AGENT_TOOL_NAME
                or fixed_args != expected_args
            ):
                raise Phase11LiveMissionError(
                    "external-agent plan diverges from immutable binding"
                )
            adapter.read_task(
                envelope,
                document.get("external_agent_task_artifact", {}),
            )
        self._validate_anchor(authority, advance=advance_anchor)
        if reconcile_kill:
            self._reconcile_kill_state(
                mission_id,
                events,
                binding_digest=str(document["binding_digest"]),
            )
        return document

    def create(
        self,
        *,
        title: object,
        workspace_root: object,
        objective: object = "",
        query: object = "",
        supplied_steps: object = None,
        max_steps: object = len(_PLAN_TOOLS),
        max_seconds: object = 120,
        max_retries: object = 0,
        provider_cost_limit: object = 0,
    ) -> Mission:
        audit = self._require_enabled()
        if supplied_steps not in (None, []):
            raise Phase11LiveMissionError(
                "Phase 11 tools are host-authored; model-supplied steps are forbidden"
            )
        safe_title = str(title).strip()
        safe_query = str(query or objective).strip()
        if not safe_title or not safe_query or len(safe_query) > 300:
            raise ValueError(
                "Phase 11 title and a query/objective up to 300 characters are required"
            )
        steps_budget, seconds_budget, retry_budget = self._budgets(
            max_steps=max_steps,
            max_seconds=max_seconds,
            max_retries=max_retries,
            provider_cost_limit=provider_cost_limit,
        )
        baseline = audit.capture(str(workspace_root))
        if baseline.root not in self._allowed_roots:
            raise Phase11LiveMissionError(
                "Phase 11 project root must exactly match a configured mission workspace root"
            )
        mission = self.store.create(
            safe_title,
            self._fixed_plan(baseline.root, safe_query),
            tool_allowlist=list(_PLAN_TOOLS),
            max_steps=steps_budget,
            max_seconds=seconds_budget,
            max_retries=retry_budget,
            provider_cost_limit=0.0,
        )
        try:
            payload = {
                "schema": BINDING_SCHEMA,
                "mission_id": mission.id,
                "mission_type": MISSION_TYPE,
                "authority_public_key": self._authority_public_key,
                "baseline": asdict(baseline),
                "plan_digest": self.store.plan_summary(mission.id)["plan_digest"],
                "fixed_steps": self._database_steps(mission.id),
            }
            binding = self._write_binding_once(payload)
            self._authority_event(
                mission.id,
                "phase11.bound",
                {
                    "mission_type": MISSION_TYPE,
                    "binding_digest": binding["binding_digest"],
                    "binding_signature": binding["signature"],
                    "authority_public_key": self._authority_public_key,
                },
            )
            self._validate_current_binding(mission.id)
        except BaseException as primary:
            try:
                self.store.cancel(mission.id)
            except BaseException as rollback:
                failure = Phase11LiveMissionError(
                    "Phase 11 creation failed and rollback cancellation failed"
                )
                failure.add_note(f"primary failure type: {type(primary).__name__}")
                raise failure from rollback
            raise
        return mission

    def _autopilot_envelope(
        self, document: Mapping[str, Any]
    ) -> AutopilotEnvelopeV1:
        raw = document.get("autopilot")
        if not isinstance(raw, Mapping):
            raise Phase11LiveMissionError("autopilot envelope is unavailable")
        patch = self._read_patch_artifact(document)
        envelope = AutopilotEnvelopeV1.build(
            root=str(raw.get("root", "")),
            base_head=str(raw.get("base_head", "")),
            owner_git_sha256=str(raw.get("owner_git_sha256", "")),
            patch=patch,
            gates=raw.get("gates"),
            max_seconds=raw.get("max_seconds"),
            max_output_bytes=raw.get("max_output_bytes"),
        )
        if (
            envelope.input_digest != raw.get("input_digest")
            or envelope.patch_sha256 != raw.get("patch_sha256")
            or list(envelope.patch_paths) != raw.get("patch_paths")
        ):
            raise Phase11LiveMissionError(
                "autopilot envelope authentication failed"
            )
        return envelope

    def _executable_plan_from_input(
        self,
        *,
        image_id: object,
        platform: object,
        gates: object,
    ) -> ExecutableGatePlanV1:
        if not self._executable_sandbox_enabled or self.autopilot is None:
            raise Phase11LiveMissionError(
                "executable Project Autopilot is not explicitly enabled"
            )
        if platform != self._executable_platform:
            raise Phase11LiveMissionError(
                "executable Project Autopilot platform is not the activated platform"
            )
        if not isinstance(gates, (list, tuple)):
            raise ValueError("executable_gates must be an explicit non-empty array")
        normalized: list[dict[str, object]] = []
        for item in gates:
            if not isinstance(item, Mapping) or set(item) != {
                "argv",
                "timeout_seconds",
                "max_output_bytes",
            }:
                raise ValueError("executable gate contract is invalid")
            argv = item["argv"]
            if not isinstance(argv, (list, tuple)):
                raise ValueError("executable gate argv must be an array")
            normalized.append(
                {
                    "argv": tuple(argv),
                    "timeout_seconds": item["timeout_seconds"],
                    "max_output_bytes": item["max_output_bytes"],
                }
            )
        return ExecutableGatePlanV1.build(
            image_id=image_id,
            platform=platform,
            gates=normalized,
            approved_image_ids=self._approved_executable_image_ids,
        )

    def _executable_plan(
        self, document: Mapping[str, Any]
    ) -> ExecutableGatePlanV1 | None:
        raw = document.get("executable_autopilot")
        if raw is None:
            if document.get("executable_plan_artifact") is not None:
                raise Phase11LiveMissionError(
                    "orphan executable plan artifact is invalid"
                )
            return None
        if not isinstance(raw, Mapping) or set(raw) != {
            "schema",
            "image_id",
            "platform",
            "gate_count",
            "plan_digest",
        }:
            raise Phase11LiveMissionError(
                "executable Project Autopilot binding is invalid"
            )
        protected = self._read_executable_plan_artifact(document)
        plan = self._executable_plan_from_input(
            image_id=protected.get("image_id"),
            platform=protected.get("platform"),
            gates=protected.get("gates"),
        )
        if (
            raw.get("schema") != plan.schema
            or raw.get("image_id") != plan.image_id
            or raw.get("platform") != plan.platform
            or raw.get("gate_count") != len(plan.gates)
            or raw.get("plan_digest") != plan.plan_digest
            or protected.get("schema") != plan.schema
            or protected.get("plan_digest") != plan.plan_digest
        ):
            raise Phase11LiveMissionError(
                "executable Project Autopilot plan authentication failed"
            )
        return plan

    def _executable_envelope(
        self,
        document: Mapping[str, Any],
        primary: AutopilotEnvelopeV1,
    ) -> ExecutableGateEnvelopeV1 | None:
        plan = self._executable_plan(document)
        if plan is None:
            return None
        if self._key is None:
            raise Phase11LiveMissionError(
                "executable Project Autopilot authority key is unavailable"
            )
        return ExecutableGateEnvelopeV1.build(
            image_id=plan.image_id,
            platform=plan.platform,
            gates=[
                {
                    "argv": gate.argv,
                    "timeout_seconds": gate.timeout_seconds,
                    "max_output_bytes": gate.max_output_bytes,
                }
                for gate in plan.gates
            ],
            approved_image_ids=self._approved_executable_image_ids,
            mission_id=str(document["mission_id"]),
            gate_index=0,
            primary_envelope=primary,
            binding_digest=str(document["binding_digest"]),
            signing_key=self._key,
        )

    def _external_agent_packet(
        self,
        *,
        workspace_root: str,
        repository_commit: str,
        objective: object,
        allowed_roots: object,
    ) -> tuple[str, tuple[str, ...], str, int]:
        adapter = self._ensure_external_agent()
        if (
            not isinstance(allowed_roots, (list, tuple))
            or not allowed_roots
            or len(allowed_roots) > 32
        ):
            raise ValueError("external-agent allowed_roots are required")
        normalized: list[str] = []
        for raw in allowed_roots:
            value = str(raw).replace("\\", "/").strip().strip("/")
            path = Path(value)
            if (
                not value
                or path.is_absolute()
                or ":" in value
                or any(part in {"", ".", "..", ".git"} for part in path.parts)
                or _EXTERNAL_SECRET_PATH.search(value)
            ):
                raise ValueError("external-agent allowed root is invalid")
            normalized.append(value)
        try:
            return adapter.build_commit_packet(
                workspace_root=workspace_root,
                repository_commit=repository_commit,
                objective=objective,
                allowed_roots=tuple(normalized),
            )
        except ExternalAgentContractError as exc:
            raise ValueError(str(exc)) from exc

    def _external_agent_envelope(
        self, document: Mapping[str, Any]
    ) -> ExternalAgentEnvelopeV1:
        if self._key is None:
            raise Phase11LiveMissionError("Phase 11 binding key is unavailable")
        try:
            return ExternalAgentEnvelopeV1.from_binding(
                document.get("external_agent"),
                signing_key=self._key,
            )
        except ExternalAgentContractError as exc:
            raise Phase11LiveMissionError(
                "external-agent envelope authentication failed"
            ) from exc

    def create_external_agent(
        self,
        *,
        title: object,
        workspace_root: object,
        workspace_id: object,
        objective: object,
        allowed_roots: object,
        prior_mission_id: object = "",
        supplied_steps: object = None,
        max_steps: object = 1,
        max_seconds: object = None,
        max_retries: object = 0,
        provider_cost_limit: object = None,
        max_output_bytes: object = None,
    ) -> Mission:
        audit = self._require_enabled()
        adapter = self._ensure_external_agent()
        if self._key is None:
            raise Phase11LiveMissionError("Phase 11 binding key is unavailable")
        if supplied_steps not in (None, []):
            raise Phase11LiveMissionError(
                "external-agent steps are host-authored; supplied steps are forbidden"
            )
        safe_title = str(title).strip()
        if not safe_title or len(safe_title) > 200:
            raise ValueError("external-agent title is invalid")
        safe_workspace_id = str(workspace_id).strip().lower()
        health = adapter.health()
        expected_seconds = int(health["max_seconds"])
        expected_output = int(health["max_output_bytes"])
        expected_budget = float(health["max_budget_usd"])
        if health.get("billable_dispatch_available") is not True:
            raise Phase11LiveMissionError(
                "external coding agent billable dispatch is unavailable: "
                + str(
                    health.get(
                        "billable_dispatch_unavailable_reason",
                        "execution_account_receipt_unavailable",
                    )
                )[:120]
            )
        if max_steps != 1 or max_retries != 0:
            raise ValueError("external-agent mission requires one step and zero retries")
        if max_seconds is not None and max_seconds != expected_seconds:
            raise ValueError("external-agent timeout is activation-owned")
        if max_output_bytes is not None and max_output_bytes != expected_output:
            raise ValueError("external-agent output budget is activation-owned")
        if (
            provider_cost_limit is not None
            and (
                isinstance(provider_cost_limit, bool)
                or not isinstance(provider_cost_limit, (int, float))
                or float(provider_cost_limit) != expected_budget
            )
        ):
            raise ValueError("external-agent provider budget is activation-owned")
        baseline = audit.capture(str(workspace_root))
        if baseline.root not in self._allowed_roots:
            raise Phase11LiveMissionError(
                "external-agent root must match a configured workspace root"
            )
        if baseline.dirty_files or baseline.dirty_bytes:
            raise Phase11LiveMissionError(
                "external-agent requires a clean immutable owner worktree"
            )
        repository_commit, owner_git_sha256 = adapter.capture_owner_state(
            baseline.root
        )
        packet, roots, blob_manifest_sha256, blob_count = self._external_agent_packet(
            workspace_root=baseline.root,
            repository_commit=repository_commit,
            objective=objective,
            allowed_roots=allowed_roots,
        )
        prior_id = str(prior_mission_id).strip()
        prior_artifact_sha256 = ""
        if prior_id:
            prior_binding = self._validate_current_binding(prior_id)
            if (
                prior_binding.get("mission_type") != EXTERNAL_AGENT_MISSION_TYPE
                or self.store.get(prior_id).state != "succeeded"
                or adapter.status(prior_id).get("attempt_state") != "succeeded"
            ):
                raise Phase11LiveMissionError(
                    "external-agent follow-up requires a succeeded prior mission"
                )
            prior_artifact_sha256 = adapter.artifact_sha256(prior_id)
        task_sha256 = hashlib.sha256(packet.encode("utf-8")).hexdigest()
        runtime_nonce = secrets.token_hex(16)
        step = {
            "tool": EXTERNAL_AGENT_TOOL_NAME,
            "args": {
                "workspace_id": safe_workspace_id,
                "repository_commit": repository_commit,
                "owner_git_sha256": owner_git_sha256,
                "repository_blob_manifest_sha256": blob_manifest_sha256,
                "repository_blob_count": blob_count,
                "git_executable_path": str(health["git_executable_path"]),
                "git_executable_sha256": str(health["git_executable_sha256"]),
                "git_executable_identity_sha256": str(
                    health["git_executable_identity_sha256"]
                ),
                "git_executable_file_id": str(
                    health["git_executable_file_id"]
                ),
                "allowed_roots": list(roots),
                "provider_id": str(health["provider_id"]),
                "provider_version": str(health["version"]),
                "provider_executable_path": str(
                    redact(health["executable_path"])
                ),
                "provider_executable_sha256": str(health["binary_sha256"]),
                "provider_executable_identity_sha256": str(
                    health["executable_identity_sha256"]
                ),
                "provider_executable_file_id": str(
                    health["executable_file_id"]
                ),
                "provider_account_sha256": str(
                    health["account_binding_sha256"]
                ),
                "model": str(health["model"]),
                "provider_budget_usd": expected_budget,
                "max_seconds": expected_seconds,
                "max_output_bytes": expected_output,
                "task_sha256": task_sha256,
                "task_bytes": len(packet.encode("utf-8")),
                "prior_artifact_sha256": prior_artifact_sha256,
                "mutation_boundary": "detached_clone_patch_output_only",
                "external_pr_creation": False,
                "runtime_nonce": runtime_nonce,
            },
        }
        mission = self.store.create(
            safe_title,
            [step],
            tool_allowlist=[EXTERNAL_AGENT_TOOL_NAME],
            max_steps=1,
            max_seconds=float(expected_seconds),
            max_retries=0,
            provider_cost_limit=0.0,
        )
        try:
            plan_digest = self.store.plan_summary(mission.id)["plan_digest"]
            envelope = ExternalAgentEnvelopeV1.build(
                signing_key=self._key,
                mission_id=mission.id,
                workspace_id=safe_workspace_id,
                workspace_root=baseline.root,
                repository_commit=repository_commit,
                owner_git_sha256=owner_git_sha256,
                repository_blob_manifest_sha256=blob_manifest_sha256,
                repository_blob_count=blob_count,
                git_executable_path=str(health["git_executable_path"]),
                git_executable_sha256=str(health["git_executable_sha256"]),
                git_executable_identity_sha256=str(
                    health["git_executable_identity_sha256"]
                ),
                git_executable_file_id=str(
                    health["git_executable_file_id"]
                ),
                allowed_roots=roots,
                provider_version=str(health["version"]),
                provider_executable_path=str(health["executable_path"]),
                provider_executable_sha256=str(health["binary_sha256"]),
                provider_executable_identity_sha256=str(
                    health["executable_identity_sha256"]
                ),
                provider_executable_file_id=str(
                    health["executable_file_id"]
                ),
                provider_account_sha256=str(
                    health["account_binding_sha256"]
                ),
                model=str(health["model"]),
                max_budget_usd=expected_budget,
                max_seconds=expected_seconds,
                max_output_bytes=expected_output,
                task=packet,
                approval_digest=plan_digest,
                prior_artifact_sha256=prior_artifact_sha256,
                nonce=runtime_nonce,
            )
            payload = {
                "schema": BINDING_SCHEMA,
                "mission_id": mission.id,
                "mission_type": EXTERNAL_AGENT_MISSION_TYPE,
                "authority_public_key": self._authority_public_key,
                "baseline": asdict(baseline),
                "external_agent": {
                    **asdict(envelope),
                    "allowed_roots": list(envelope.allowed_roots),
                },
                "external_agent_task_artifact": adapter.protect_task(
                    mission.id, packet, task_sha256
                ),
                "plan_digest": plan_digest,
                "fixed_steps": self._database_steps(mission.id),
            }
            binding = self._write_binding_once(payload)
            self._authority_event(
                mission.id,
                "phase11.bound",
                {
                    "mission_type": EXTERNAL_AGENT_MISSION_TYPE,
                    "binding_digest": binding["binding_digest"],
                    "binding_signature": binding["signature"],
                    "authority_public_key": self._authority_public_key,
                },
            )
            self._validate_current_binding(mission.id)
        except BaseException as primary:
            try:
                self.store.cancel(mission.id)
            except BaseException as rollback:
                failure = Phase11LiveMissionError(
                    "external-agent creation failed and rollback failed"
                )
                failure.add_note(f"primary failure type: {type(primary).__name__}")
                raise failure from rollback
            raise
        return mission

    def create_autopilot(
        self,
        *,
        title: object,
        workspace_root: object,
        patch: object,
        gates: object,
        supplied_steps: object = None,
        max_steps: object = 1,
        max_seconds: object = 300,
        max_retries: object = 0,
        provider_cost_limit: object = 0,
        max_output_bytes: object = 2 * 1024 * 1024,
        executable_image_id: object = None,
        executable_platform: object = None,
        executable_gates: object = None,
    ) -> Mission:
        audit = self._require_enabled()
        if self.autopilot is None:
            raise Phase11LiveMissionError(
                "project_autopilot_v1 is not explicitly enabled"
            )
        if supplied_steps not in (None, []):
            raise Phase11LiveMissionError(
                "autopilot steps are host-authored; model-supplied steps are forbidden"
            )
        safe_title = str(title).strip()
        if not safe_title:
            raise ValueError("autopilot title is required")
        if max_steps != 1:
            raise ValueError("project_autopilot_v1 max_steps must be 1")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries != 0
        ):
            raise ValueError("project_autopilot_v1 max_retries must be 0")
        if (
            isinstance(provider_cost_limit, bool)
            or not isinstance(provider_cost_limit, (int, float))
            or float(provider_cost_limit) != 0.0
        ):
            raise ValueError("project_autopilot_v1 provider cost must be zero")
        baseline = audit.capture(str(workspace_root))
        if baseline.root not in self._allowed_roots:
            raise Phase11LiveMissionError(
                "autopilot root must exactly match a configured workspace root"
            )
        if baseline.dirty_files or baseline.dirty_bytes:
            raise Phase11LiveMissionError(
                "autopilot requires a clean immutable owner worktree"
            )
        owner_git_sha256 = self.autopilot.capture_owner_git_state(baseline.root)
        envelope = AutopilotEnvelopeV1.build(
            root=baseline.root,
            base_head=baseline.head,
            owner_git_sha256=owner_git_sha256,
            patch=patch,
            gates=gates,
            max_seconds=max_seconds,
            max_output_bytes=max_output_bytes,
        )
        executable_supplied = any(
            value is not None
            for value in (
                executable_image_id,
                executable_platform,
                executable_gates,
            )
        )
        if executable_supplied and not all(
            value is not None
            for value in (
                executable_image_id,
                executable_platform,
                executable_gates,
            )
        ):
            raise ValueError(
                "executable image, platform and gates must be supplied together"
            )
        executable_plan = (
            self._executable_plan_from_input(
                image_id=executable_image_id,
                platform=executable_platform,
                gates=executable_gates,
            )
            if executable_supplied
            else None
        )
        runtime_nonce = secrets.token_hex(16)
        step = {
            "tool": AUTOPILOT_TOOL_NAME,
            "args": {
                "input_digest": envelope.input_digest,
                "base_head": envelope.base_head,
                "owner_git_sha256": envelope.owner_git_sha256,
                "patch_sha256": envelope.patch_sha256,
                "patch_paths": list(envelope.patch_paths),
                "static_gates": [list(gate.argv) for gate in envelope.gates],
                "repository_code_execution": executable_plan is not None,
                "mutation_boundary": "standalone_clone",
                "runtime_nonce": runtime_nonce,
            },
        }
        if executable_plan is not None:
            step["args"].update(
                {
                    "executable_plan_digest": executable_plan.plan_digest,
                    "executable_image_id": executable_plan.image_id,
                    "executable_platform": executable_plan.platform,
                    "executable_gate_count": len(executable_plan.gates),
                }
            )
        mission = self.store.create(
            safe_title,
            [step],
            tool_allowlist=[AUTOPILOT_TOOL_NAME],
            max_steps=1,
            max_seconds=float(max_seconds),
            max_retries=0,
            provider_cost_limit=0.0,
        )
        try:
            autopilot_payload = asdict(envelope)
            autopilot_payload["gates"] = [
                {
                    "argv": list(gate.argv),
                    "timeout_seconds": gate.timeout_seconds,
                }
                for gate in envelope.gates
            ]
            autopilot_payload["patch_paths"] = list(envelope.patch_paths)
            autopilot_payload["runtime_nonce"] = runtime_nonce
            executable_payload = None
            if executable_plan is not None:
                executable_payload = {
                    "schema": executable_plan.schema,
                    "image_id": executable_plan.image_id,
                    "platform": executable_plan.platform,
                    "gate_count": len(executable_plan.gates),
                    "plan_digest": executable_plan.plan_digest,
                }
            patch_artifact = self._write_patch_artifact(
                mission.id, str(patch), envelope.patch_sha256
            )
            payload = {
                "schema": BINDING_SCHEMA,
                "mission_id": mission.id,
                "mission_type": AUTOPILOT_MISSION_TYPE,
                "authority_public_key": self._authority_public_key,
                "baseline": asdict(baseline),
                "autopilot": autopilot_payload,
                "patch_artifact": patch_artifact,
                "plan_digest": self.store.plan_summary(mission.id)["plan_digest"],
                "fixed_steps": self._database_steps(mission.id),
            }
            if executable_payload is not None:
                payload["executable_autopilot"] = executable_payload
                payload["executable_plan_artifact"] = (
                    self._write_executable_plan_artifact(
                        mission.id, executable_plan
                    )
                )
            binding = self._write_binding_once(payload)
            self._authority_event(
                mission.id,
                "phase11.bound",
                {
                    "mission_type": AUTOPILOT_MISSION_TYPE,
                    "binding_digest": binding["binding_digest"],
                    "binding_signature": binding["signature"],
                    "authority_public_key": self._authority_public_key,
                },
            )
            self._validate_current_binding(mission.id)
        except BaseException as primary:
            try:
                self.store.cancel(mission.id)
            except BaseException as rollback:
                failure = Phase11LiveMissionError(
                    "autopilot creation failed and rollback cancellation failed"
                )
                failure.add_note(f"primary failure type: {type(primary).__name__}")
                raise failure from rollback
            raise
        return mission

    def create_away(
        self,
        *,
        title: object,
        workspace_root: object,
        workspace_id: object,
        target_url: object,
        allowed_domains: object,
        action: object = "observe",
        capture_screenshot: object = True,
        supplied_steps: object = None,
        max_steps: object = 1,
        max_seconds: object = 60,
        max_retries: object = 0,
        provider_cost_limit: object = 0,
    ) -> Mission:
        """Create one exact, read-only browser observation mission."""
        audit = self._require_enabled()
        if self.away_mode is None or self._key is None:
            reason = self.away_unavailable_reason
            raise Phase11LiveMissionError(
                "governed browser Away Mode is unavailable"
                + (f": {reason}" if reason else "")
            )
        away_availability = self.away_mode.availability()
        if away_availability.get("browser") is not True:
            reason = str(
                away_availability.get("browser_reason", "unavailable")
            )
            if reason.startswith("global_kill"):
                raise Phase11LiveMissionError(
                    f"global Away kill boundary is blocked: {reason}"
                )
            raise Phase11LiveMissionError(
                f"governed browser Away Mode is blocked: {reason}"
            )
        if supplied_steps not in (None, []):
            raise Phase11LiveMissionError(
                "Away Mode steps are host-authored; supplied steps are forbidden"
            )
        safe_title = str(title).strip()
        if not safe_title or len(safe_title) > 200:
            raise ValueError("Away Mode title is required")
        if max_steps != 1:
            raise ValueError("governed_browser_away_v1 max_steps must be 1")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries != 0
        ):
            raise ValueError("governed_browser_away_v1 max_retries must be 0")
        if (
            isinstance(provider_cost_limit, bool)
            or not isinstance(provider_cost_limit, (int, float))
            or float(provider_cost_limit) != 0.0
        ):
            raise ValueError("governed_browser_away_v1 provider cost must be zero")
        baseline = audit.capture(str(workspace_root))
        if baseline.root not in self._allowed_roots:
            raise Phase11LiveMissionError(
                "Away Mode root must exactly match a configured workspace root"
            )
        runtime_nonce = secrets.token_hex(16)
        away_session_id = "away_" + runtime_nonce
        issued_at_ns = time.time_ns()
        stop_policy = (
            "cancel",
            "domain_drift",
            "dialog",
            "download",
            "global_kill",
            "mfa",
            "popup",
            "target_drift",
            "timeout",
        )
        try:
            intent_digest = action_intent_digest(
                workspace_id=workspace_id,
                workspace_root=baseline.root,
                action=action,
                target_url=target_url,
                allowed_domains=allowed_domains,
                capture_screenshot=capture_screenshot,
                max_seconds=max_seconds,
            )
        except GovernedAwayError as exc:
            raise Phase11LiveMissionError(str(exc)) from exc
        canonical_envelope = BrowserActionEnvelopeV1.build(
            signing_key=self._key,
            mission_id="mis_placeholder",
            principal_id="owner-local",
            away_session_id=away_session_id,
            lease_generation=1,
            workspace_id=workspace_id,
            workspace_root=baseline.root,
            profile_id="profile-public-v1",
            provider_id="playwright-chromium",
            account_id="none",
            action=action,
            target_url=target_url,
            allowed_domains=allowed_domains,
            capture_screenshot=capture_screenshot,
            max_seconds=max_seconds,
            max_uses=1,
            network_request_budget=64,
            output_byte_budget=16_384,
            screenshot_budget=int(capture_screenshot is True),
            paid_cost_budget=0,
            approval_policy_id="missionstore.exact-plan.v1",
            approval_digest="0" * 64,
            key_epoch=1,
            stop_policy=stop_policy,
            issued_at_ns=issued_at_ns,
            not_before_ns=issued_at_ns,
            nonce=runtime_nonce,
        )
        step = {
            "tool": AWAY_TOOL_NAME,
            "args": {
                "intent_digest": intent_digest,
                "principal_id": canonical_envelope.principal_id,
                "away_session_id": canonical_envelope.away_session_id,
                "lease_generation": canonical_envelope.lease_generation,
                "workspace_id": canonical_envelope.workspace_id,
                "profile_id": canonical_envelope.profile_id,
                "provider_id": canonical_envelope.provider_id,
                "account_id": canonical_envelope.account_id,
                "target_url": canonical_envelope.target_url,
                "target_origin": canonical_envelope.target_origin,
                "target_domain": canonical_envelope.target_domain,
                "allowed_domains": list(canonical_envelope.allowed_domains),
                "action": canonical_envelope.action,
                "capture_screenshot": canonical_envelope.capture_screenshot,
                "max_seconds": canonical_envelope.max_seconds,
                "max_uses": canonical_envelope.max_uses,
                "network_request_budget": (
                    canonical_envelope.network_request_budget
                ),
                "output_byte_budget": canonical_envelope.output_byte_budget,
                "screenshot_budget": canonical_envelope.screenshot_budget,
                "paid_cost_budget": canonical_envelope.paid_cost_budget,
                "approval_policy_id": canonical_envelope.approval_policy_id,
                "key_epoch": canonical_envelope.key_epoch,
                "stop_policy": list(canonical_envelope.stop_policy),
                "issued_at_ns": canonical_envelope.issued_at_ns,
                "not_before_ns": canonical_envelope.not_before_ns,
                "expires_at_ns": canonical_envelope.expires_at_ns,
                "computer_control": False,
                "runtime_nonce": runtime_nonce,
            },
        }
        mission = self.store.create(
            safe_title,
            [step],
            tool_allowlist=[AWAY_TOOL_NAME],
            max_steps=1,
            max_seconds=float(canonical_envelope.max_seconds),
            max_retries=0,
            provider_cost_limit=0.0,
        )
        try:
            plan_digest = self.store.plan_summary(mission.id)["plan_digest"]
            envelope = BrowserActionEnvelopeV1.build(
                signing_key=self._key,
                mission_id=mission.id,
                principal_id=canonical_envelope.principal_id,
                away_session_id=canonical_envelope.away_session_id,
                lease_generation=canonical_envelope.lease_generation,
                workspace_id=canonical_envelope.workspace_id,
                workspace_root=baseline.root,
                profile_id=canonical_envelope.profile_id,
                provider_id=canonical_envelope.provider_id,
                account_id=canonical_envelope.account_id,
                action=canonical_envelope.action,
                target_url=canonical_envelope.target_url,
                allowed_domains=canonical_envelope.allowed_domains,
                capture_screenshot=canonical_envelope.capture_screenshot,
                max_seconds=canonical_envelope.max_seconds,
                max_uses=canonical_envelope.max_uses,
                network_request_budget=(
                    canonical_envelope.network_request_budget
                ),
                output_byte_budget=canonical_envelope.output_byte_budget,
                screenshot_budget=canonical_envelope.screenshot_budget,
                paid_cost_budget=canonical_envelope.paid_cost_budget,
                approval_policy_id=canonical_envelope.approval_policy_id,
                approval_digest=plan_digest,
                key_epoch=canonical_envelope.key_epoch,
                stop_policy=canonical_envelope.stop_policy,
                issued_at_ns=canonical_envelope.issued_at_ns,
                not_before_ns=canonical_envelope.not_before_ns,
                nonce=runtime_nonce,
            )
            if envelope.intent_digest != intent_digest:
                raise Phase11LiveMissionError(
                    "Away Mode intent changed during mission materialization"
                )
            payload = {
                "schema": BINDING_SCHEMA,
                "mission_id": mission.id,
                "mission_type": AWAY_MISSION_TYPE,
                "authority_public_key": self._authority_public_key,
                "baseline": asdict(baseline),
                "away": envelope.as_binding(),
                "away_runtime_nonce": runtime_nonce,
                "plan_digest": plan_digest,
                "fixed_steps": self._database_steps(mission.id),
            }
            binding = self._write_binding_once(payload)
            self._authority_event(
                mission.id,
                "phase11.bound",
                {
                    "mission_type": AWAY_MISSION_TYPE,
                    "binding_digest": binding["binding_digest"],
                    "binding_signature": binding["signature"],
                    "authority_public_key": self._authority_public_key,
                },
            )
            self._validate_current_binding(mission.id)
        except BaseException as primary:
            try:
                self.store.cancel(mission.id)
            except BaseException as rollback:
                failure = Phase11LiveMissionError(
                    "Away Mode creation failed and rollback cancellation failed"
                )
                failure.add_note(
                    f"primary failure type: {type(primary).__name__}"
                )
                raise failure from rollback
            raise
        return mission

    def reseed_autopilot(self, mission_id: str) -> Mission:
        """Create a new pending mission after exact owner/envelope revalidation."""
        binding = self._validate_current_binding(mission_id)
        if binding.get("mission_type") != AUTOPILOT_MISSION_TYPE:
            raise Phase11LiveMissionError(
                "fresh reapproval is only available for project_autopilot_v1"
            )
        if self.autopilot is None:
            raise Phase11LiveMissionError(
                "project_autopilot_v1 is not explicitly enabled"
            )
        checkpoint = self.autopilot.checkpoint_status_for_fresh_reapproval(
            mission_id
        )
        has_unknown_execution = (
            isinstance(checkpoint, Mapping)
            and (
                checkpoint.get("repository_code_execution_state")
                == "attempted_unknown"
                or checkpoint.get("executable_gate_intent") is not None
            )
        )
        has_reconciliation = any(
            event.get("event") == "phase11.reconciliation"
            for event in self._events(mission_id)
        )
        if has_unknown_execution or has_reconciliation:
            raise Phase11LiveMissionError(
                "fresh reapproval is forbidden after executable "
                "attempted-unknown or reconciliation authority"
            )
        raw = binding.get("autopilot")
        if not isinstance(raw, Mapping):
            raise Phase11LiveMissionError("autopilot envelope is unavailable")
        patch = self._read_patch_artifact(binding)
        old_envelope = self._autopilot_envelope(binding)
        audit = self._require_enabled()
        baseline = audit.capture(old_envelope.root)
        if (
            baseline.root != old_envelope.root
            or baseline.head != old_envelope.base_head
            or baseline.dirty_files
            or baseline.dirty_bytes
            or self.autopilot is None
            or self.autopilot.capture_owner_git_state(baseline.root)
            != old_envelope.owner_git_sha256
        ):
            raise Phase11LiveMissionError(
                "fresh reapproval owner state diverged"
            )
        rebuilt = AutopilotEnvelopeV1.build(
            root=old_envelope.root,
            base_head=old_envelope.base_head,
            owner_git_sha256=old_envelope.owner_git_sha256,
            patch=patch,
            gates=raw.get("gates"),
            max_seconds=raw.get("max_seconds"),
            max_output_bytes=raw.get("max_output_bytes"),
        )
        if rebuilt.input_digest != old_envelope.input_digest:
            raise Phase11LiveMissionError(
                "fresh reapproval envelope diverged"
            )
        previous = self.store.get(mission_id)
        executable_plan = self._executable_plan(binding)
        replacement = self.create_autopilot(
            title=f"{previous.title} (fresh reapproval)",
            workspace_root=old_envelope.root,
            patch=patch,
            gates=raw.get("gates"),
            max_seconds=old_envelope.max_seconds,
            max_output_bytes=old_envelope.max_output_bytes,
            executable_image_id=(
                None if executable_plan is None else executable_plan.image_id
            ),
            executable_platform=(
                None if executable_plan is None else executable_plan.platform
            ),
            executable_gates=(
                None
                if executable_plan is None
                else [
                    {
                        "argv": list(gate.argv),
                        "timeout_seconds": gate.timeout_seconds,
                        "max_output_bytes": gate.max_output_bytes,
                    }
                    for gate in executable_plan.gates
                ]
            ),
        )
        return replacement

    def reconcile_executable_attempt(
        self,
        mission_id: str,
        *,
        decision: object,
        recovered_receipt: object = None,
        host_execution_absence_proof: object = None,
    ) -> dict[str, Any]:
        """Record an owner reconciliation without guessing an outcome.

        Recovery accepts only the exact authenticated receipt already committed
        to the host-owned execution ledger.  Non-execution is never inferred.
        """
        if not isinstance(decision, str) or decision not in {
            "still_unknown",
            "abandon",
            "recovered_receipt",
            "proven_not_executed",
        }:
            raise ValueError("unsupported executable reconciliation decision")
        if decision == "recovered_receipt":
            if recovered_receipt is None:
                raise Phase11LiveMissionError(
                    "recovered receipt evidence is required"
                )
            if not isinstance(recovered_receipt, Mapping):
                raise Phase11LiveMissionError(
                    "recovered receipt evidence is invalid"
                )
        if decision == "proven_not_executed":
            if host_execution_absence_proof is None:
                raise Phase11LiveMissionError(
                    "host-owned execution absence proof is required"
                )
            raise Phase11LiveMissionError(
                "host-owned durable dispatch ledger is unavailable; "
                "proven-not-executed reconciliation is refused"
            )
        if (
            decision != "recovered_receipt"
            and recovered_receipt is not None
        ) or host_execution_absence_proof is not None:
            raise Phase11LiveMissionError(
                "reconciliation evidence is forbidden for this decision"
            )
        with self._lock:
            document = self._validate_current_binding(
                mission_id, advance_anchor=True
            )
            if document.get("mission_type") != AUTOPILOT_MISSION_TYPE:
                raise Phase11LiveMissionError(
                    "executable reconciliation requires project_autopilot_v1"
                )
            if self.autopilot is None:
                raise Phase11LiveMissionError(
                    "project_autopilot_v1 is not explicitly enabled"
                )
            mission = self.store.get(mission_id)
            events = self._events(mission_id)
            existing_reconciliations = [
                event
                for event in events
                if event.get("event") == "phase11.reconciliation"
            ]
            checkpoint = self.autopilot.checkpoint_status(mission_id)
            executable = document.get("executable_autopilot")
            if (
                checkpoint is None
                or not isinstance(executable, Mapping)
                or checkpoint.get("executable_plan_digest")
                != executable.get("plan_digest")
                or checkpoint.get("repository_code_execution_state")
                != "attempted_unknown"
                or not isinstance(
                    checkpoint.get("executable_gate_intent"), Mapping
                )
            ):
                raise Phase11LiveMissionError(
                    "no authenticated attempted-unknown executable intent exists"
                )
            intent = dict(checkpoint["executable_gate_intent"])
            if (
                set(intent) != {"index", "execution_id"}
                or intent.get("index")
                != checkpoint.get("executable_gate_index")
                or isinstance(intent.get("index"), bool)
                or not isinstance(intent.get("index"), int)
                or not isinstance(intent.get("execution_id"), str)
                or re.fullmatch(
                    r"[0-9a-f]{64}", str(intent.get("execution_id"))
                )
                is None
            ):
                raise Phase11LiveMissionError(
                    "attempted-unknown executable intent is invalid"
                )
            recovered_digest = ""
            if decision == "recovered_receipt":
                ledger = self._execution_ledger
                if ledger is None or ledger.enabled is not True:
                    raise Phase11LiveMissionError(
                        "host-owned durable receipt ledger is unavailable"
                    )
                assert isinstance(recovered_receipt, Mapping)
                attempt = recovered_receipt.get("attempt")
                if (
                    isinstance(attempt, bool)
                    or not isinstance(attempt, int)
                    or attempt < 1
                    or recovered_receipt.get("execution_id")
                    != intent.get("execution_id")
                ):
                    raise Phase11LiveMissionError(
                        "recovered receipt binding is invalid"
                    )
                authenticated = ledger.authenticated_receipt(
                    mission_id=mission_id,
                    execution_id=str(intent["execution_id"]),
                    attempt=attempt,
                )
                if authenticated is None or dict(recovered_receipt) != authenticated:
                    raise Phase11LiveMissionError(
                        "recovered receipt is not authenticated by the execution ledger"
                    )
                recovered_digest = hashlib.sha256(
                    _canonical(authenticated)
                ).hexdigest()
            if mission.state not in {"waiting", "cancelled"}:
                raise Phase11LiveMissionError(
                    "executable reconciliation requires a waiting mission"
                )
            if mission.state == "cancelled" and decision != "abandon":
                raise Phase11LiveMissionError(
                    "cancelled executable intent is terminal"
                )
            intent_sha256 = hashlib.sha256(_canonical(intent)).hexdigest()
            resolution_projection = {
                "schema": _RECONCILIATION_SCHEMA,
                "decision": decision,
                "binding_digest": str(document["binding_digest"]),
                "plan_digest": str(executable["plan_digest"]),
                "gate_index": int(intent["index"]),
                "execution_id": str(intent["execution_id"]),
                "intent_sha256": intent_sha256,
                "recovered_receipt_sha256": recovered_digest,
            }
            assert self._key is not None
            resolution_id = hmac.new(
                self._key,
                _RECONCILIATION_DOMAIN
                + b"RESOLUTION\0"
                + _canonical(resolution_projection),
                hashlib.sha256,
            ).hexdigest()
            matching = [
                event
                for event in existing_reconciliations
                if isinstance(event.get("detail"), Mapping)
                and hmac.compare_digest(
                    str(event["detail"].get("resolution_id", "")),
                    resolution_id,
                )
            ]
            if len(matching) > 1:
                raise Phase11LiveMissionError(
                    "duplicate executable reconciliation authority detected"
                )
            if not matching:
                if any(
                    isinstance(event.get("detail"), Mapping)
                    and event["detail"].get("decision") == "abandon"
                    for event in existing_reconciliations
                ):
                    raise Phase11LiveMissionError(
                        "executable reconciliation is terminal after abandon"
                    )
                unsigned = {
                    **resolution_projection,
                    "resolution_id": resolution_id,
                    "issued_at_ns": time.time_ns(),
                }
                unsigned["decision_hmac_sha256"] = hmac.new(
                    self._key,
                    _RECONCILIATION_DOMAIN + _canonical(unsigned),
                    hashlib.sha256,
                ).hexdigest()
                self._authority_event(
                    mission_id,
                    "phase11.reconciliation",
                    unsigned,
                )
            self._reconciliation_fault("after_reconciliation_anchor")
            if decision == "abandon":
                self.request_kill(mission_id)
                self._reconciliation_fault("after_kill_anchor")
                self.store.cancel(mission_id)
            return {
                "mission_id": mission_id,
                "decision": str(decision),
                "resolution_id_prefix": resolution_id[:12],
                "repository_code_execution_state": (
                    "recovered_receipt"
                    if decision == "recovered_receipt"
                    else "attempted_unknown"
                ),
                "dispatch_permitted": False,
                "terminal": decision == "abandon",
            }

    def _phase11_binding(
        self, mission_id: str, *, reconcile_kill: bool = False
    ) -> dict[str, Any] | None:
        self._require_enabled()
        binding = self._read_binding(mission_id, required=False)
        if binding is None:
            bound = any(
                event["event"] == "phase11.bound"
                for event in self._events(mission_id)
            )
            if bound:
                raise Phase11LiveMissionError(
                    "Phase 11 immutable binding availability diverges"
                )
            return None
        return self._validate_current_binding(
            mission_id, reconcile_kill=reconcile_kill
        )

    def is_phase11(self, mission_id: str) -> bool:
        return self._phase11_binding(mission_id) is not None

    def _record_receipt(
        self, mission_id: str, receipt: VerificationReceiptV1, stage: str
    ) -> None:
        audit = self._require_enabled()
        audit.validate_receipt(receipt)
        self._authority_event(
            mission_id,
            "phase11.receipt",
            {
                "stage": stage,
                "schema": receipt.schema,
                "root": receipt.root,
                "verdict": receipt.verdict,
                "reason": receipt.reason,
                "baseline_sha256": receipt.baseline_sha256,
                "observed_sha256": receipt.observed_sha256,
                "issued_at_ns": receipt.issued_at_ns,
                "receipt_signature": receipt.signature,
            },
        )

    def approve(self, mission_id: str) -> Mission:
        with self._lock:
            binding = self._validate_current_binding(mission_id)
            receipt = self._require_enabled().verify(
                _snapshot_from_dict(binding["baseline"])
            )
            if binding.get("mission_type") == MISSION_TYPE:
                self._record_receipt(mission_id, receipt, "before_approve")
            if receipt.verdict != "PASS":
                raise Phase11LiveMissionError(
                    "workspace drift detected; Phase 11 mission is waiting"
                )
            mission = self.store.approve(mission_id)
            self._validate_current_binding(mission_id, advance_anchor=True)
            return mission

    def anchor_current_authority(self, mission_id: str) -> None:
        """Authenticate Phase 11 history and advance the native high-water mark."""
        with self._lock:
            if not self.is_phase11(mission_id):
                return
            self._validate_current_binding(mission_id, advance_anchor=True)

    def request_kill(self, mission_id: str) -> bool:
        with self._lock:
            self._validate_current_binding(mission_id, reconcile_kill=True)
            state = self._kill_state(mission_id)
            if state.event.is_set():
                self._write_anchor(self.store.authority_snapshot(mission_id))
                return False
            self._authority_event(
                mission_id,
                "phase11.kill",
                {"reason": "owner_cancel_requested"},
            )
            state.event.set()
            try:
                assert state.kernel is not None
                state.kernel.set()
            finally:
                if self.autopilot is not None:
                    self.autopilot.kill(mission_id)
                if self.away_mode is not None:
                    binding = self._read_binding(mission_id, required=False)
                    if (
                        binding is not None
                        and binding.get("mission_type") == AWAY_MISSION_TYPE
                    ):
                        self.away_mode.kill(mission_id)
                if self.external_agent is not None:
                    binding = self._read_binding(mission_id, required=False)
                    if (
                        binding is not None
                        and binding.get("mission_type")
                        == EXTERNAL_AGENT_MISSION_TYPE
                    ):
                        self.external_agent.cancel(mission_id)
            return True

    def away_control(self, mission_id: str, action: str) -> dict[str, object]:
        """Persist Away pause/takeover as terminal controls before driver stop."""
        with self._lock:
            binding = self._validate_current_binding(
                mission_id, reconcile_kill=True
            )
            if binding.get("mission_type") != AWAY_MISSION_TYPE:
                raise Phase11LiveMissionError(
                    "Away control requires a governed browser mission"
                )
            if self.away_mode is None:
                raise Phase11LiveMissionError("Away Mode is unavailable")
            mapping = {
                "pause": "paused",
                "takeover": "takeover",
                "resume": "running",
            }
            state = mapping.get(action)
            if state is None:
                raise ValueError("Away control action is invalid")
            mission = self.store.get(mission_id)
            if mission.state not in {"awaiting_approval", "running"}:
                raise Phase11LiveMissionError(
                    "Away control requires a pending or running mission"
                )
            try:
                return self.away_mode.control(mission_id, state)
            except GovernedAwayError as exc:
                raise Phase11LiveMissionError(str(exc)) from exc

    def request_global_away_kill(self) -> dict[str, object]:
        """Latch the global boundary, then durably kill every live Away mission."""
        with self._lock:
            if self.away_mode is None:
                raise Phase11LiveMissionError("Away Mode is unavailable")
            self.away_mode.latch_global_kill()
            killed: list[str] = []
            failures: list[dict[str, str]] = []
            for mission in self.store.list():
                if mission.state not in {
                    "awaiting_approval",
                    "running",
                    "paused",
                    "waiting",
                }:
                    continue
                try:
                    binding = self._read_binding(mission.id, required=False)
                except Exception as exc:
                    failures.append(
                        {
                            "mission_id": mission.id,
                            "stage": "binding_validation",
                            "error": type(exc).__name__,
                        }
                    )
                    continue
                if (
                    binding is None
                    or binding.get("mission_type") != AWAY_MISSION_TYPE
                ):
                    continue
                try:
                    if self.request_kill(mission.id):
                        killed.append(mission.id)
                    else:
                        failures.append(
                            {
                                "mission_id": mission.id,
                                "stage": "durable_mission_kill",
                                "error": "kill_not_persisted",
                            }
                        )
                except Exception as exc:
                    failures.append(
                        {
                            "mission_id": mission.id,
                            "stage": "durable_mission_kill",
                            "error": type(exc).__name__,
                        }
                    )
            stopped = self.away_mode.stop_all_for_global_kill()
            for failure in stopped["failures"]:
                failures.append(
                    {
                        "mission_id": str(failure).split(":", 1)[0],
                        "stage": "driver_stop",
                        "error": str(failure).split(":", 1)[-1],
                    }
                )
            remaining = list(self.away_mode.active_missions())
            for mission_id in remaining:
                failures.append(
                    {
                        "mission_id": mission_id,
                        "stage": "driver_stop_verification",
                        "error": "driver_still_active",
                    }
                )
            return {
                "global_kill": "latched" if not failures else "incomplete",
                "new_away_actions_blocked": True,
                "missions_killed": killed,
                "drivers_stopped": stopped["stopped"],
                "failures": failures,
            }

    def reconcile_away_attempt(
        self, mission_id: str, *, decision: object
    ) -> dict[str, object]:
        """Keep an uncertain read blocked or abandon it; never redispatch."""
        with self._lock:
            binding = self._validate_current_binding(
                mission_id, reconcile_kill=True
            )
            if binding.get("mission_type") != AWAY_MISSION_TYPE:
                raise Phase11LiveMissionError(
                    "Away reconciliation requires a governed browser mission"
                )
            if self.away_mode is None:
                raise Phase11LiveMissionError("Away Mode is unavailable")
            if decision not in {"still_unknown", "abandon"}:
                raise ValueError("Away reconciliation decision is invalid")
            mission = self.store.get(mission_id)
            if mission.state != "waiting":
                raise Phase11LiveMissionError(
                    "Away reconciliation requires an uncertain waiting mission"
                )
            attempt = self.away_mode.reconciliation_status(mission_id)
            if attempt["attempt_state"] == "not_started":
                raise Phase11LiveMissionError(
                    "Away reconciliation has no durable execution intent"
                )
            if decision == "still_unknown":
                return {
                    "mission_id": mission_id,
                    "decision": "still_unknown",
                    **attempt,
                    "state": "waiting",
                }
            self.request_kill(mission_id)
            cancelled = self.store.cancel(mission_id)
            self.anchor_current_authority(mission_id)
            return {
                "mission_id": mission_id,
                "decision": "abandon",
                **attempt,
                "state": cancelled.state,
            }

    def cleanup_autopilot(self, mission_id: str) -> bool:
        """Request terminal cleanup through the configured Phase 11 backend."""
        with self._lock:
            binding = self._validate_current_binding(mission_id)
            if binding.get("mission_type") != AUTOPILOT_MISSION_TYPE:
                raise Phase11LiveMissionError(
                    "controlled cleanup is only available for project_autopilot_v1"
                )
            mission = self.store.get(mission_id)
            if mission.state not in {"cancelled", "failed", "succeeded"}:
                raise Phase11LiveMissionError(
                    "controlled cleanup requires a terminal mission"
                )
            if self.autopilot is None:
                raise Phase11LiveMissionError(
                    "project_autopilot_v1 is not explicitly enabled"
                )
            envelope = self._autopilot_envelope(binding)
            return self.autopilot.cleanup(
                mission_id=mission_id,
                binding_digest=str(binding["binding_digest"]),
                owner_root=envelope.root,
                envelope=envelope,
            )

    def cleanup_external_agent_quarantine(
        self,
        *,
        retain: int = 0,
    ) -> dict[str, int]:
        """Owner-confirmed bounded cleanup for external-agent quarantine."""
        adapter = self._ensure_external_agent()
        return adapter.cleanup_quarantine(
            owner_confirmed=True,
            retain=retain,
        )

    def _kill_event_digest(self, mission_id: str, binding_digest: str) -> str:
        key = self._key
        if (
            key is None
            or not mission_id.startswith("mis_")
            or len(binding_digest) != 64
            or any(character not in "0123456789abcdef" for character in binding_digest)
        ):
            raise Phase11LiveMissionError(
                "named kill event identity is invalid"
            )
        return hmac.new(
            key,
            _KILL_EVENT_NAME_DOMAIN
            + self._kill_event_namespace
            + b"\0"
            + mission_id.encode("ascii", errors="strict")
            + b"\0"
            + binding_digest.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def _kill_event_name(self, mission_id: str, binding_digest: str) -> str:
        return (
            "Local\\Onyx.Phase11.Kill."
            + self._kill_event_digest(mission_id, binding_digest)
        )

    def _portable_kill_signal_name(
        self, mission_id: str, binding_digest: str
    ) -> str:
        return "phase11-" + self._kill_event_digest(
            mission_id, binding_digest
        )

    def _kill_state(
        self, mission_id: str, binding_digest: str | None = None
    ) -> _KillState:
        with self._lock:
            state = self._kill_states.get(mission_id)
            if state is not None:
                if (
                    binding_digest is not None
                    and not hmac.compare_digest(
                        state.binding_digest, binding_digest
                    )
                ):
                    raise Phase11LiveMissionError(
                        "named kill event binding diverges"
                    )
                return state
            if self._closed:
                raise Phase11LiveMissionError(
                    "Phase 11 kill event registry is closed"
                )
            if binding_digest is None:
                raise Phase11LiveMissionError(
                    "named kill event requires authenticated binding"
                )
            if len(self._kill_states) >= _MAX_KILL_FAST_PATH_ENTRIES:
                raise Phase11LiveMissionError(
                    "Phase 11 kill fast-path capacity is exhausted"
                )
            kill_signal_factory = getattr(self, "_kill_signal_factory", None)
            if kill_signal_factory is None:
                if os.name != "nt":
                    raise Phase11LiveMissionError(
                        "Phase 11 named kill events require Windows"
                    )
                kernel: KillSignalBoundary = _WindowsNamedKillEvent(
                    self._kill_event_name(mission_id, binding_digest)
                )
            else:
                try:
                    kernel = kill_signal_factory(
                        directory=getattr(
                            self, "_host_binding_boundary", None
                        ),
                        name=self._portable_kill_signal_name(
                            mission_id, binding_digest
                        ),
                        binding_digest=binding_digest,
                    )
                except Exception as exc:
                    raise Phase11LiveMissionError(
                        "Phase 11 kill signal factory failed"
                    ) from exc
                if not all(
                    callable(getattr(kernel, method, None))
                    for method in ("is_set", "set", "close")
                ):
                    raise Phase11LiveMissionError(
                        "Phase 11 kill signal boundary is invalid"
                    )
            state = _KillState(
                binding_digest=binding_digest,
                kernel=kernel,
                next_durable_check=(
                    time.monotonic() + _KILL_DURABLE_REFRESH_SECONDS
                ),
            )
            self._kill_states[mission_id] = state
            return state

    def _reconcile_kill_state(
        self,
        mission_id: str,
        events: Iterable[Mapping[str, Any]],
        *,
        binding_digest: str,
    ) -> _KillState:
        state = self._kill_state(mission_id, binding_digest)
        killed = any(event.get("event") == "phase11.kill" for event in events)
        if killed:
            state.event.set()
            assert state.kernel is not None
            state.kernel.set()
        elif state.kernel is not None and state.kernel.is_set():
            raise Phase11LiveMissionError(
                "named kill event is signaled without durable authority"
            )
        return state

    def _durable_kill_marker(self, mission_id: str, state: _KillState) -> bool:
        anchor = self._read_anchor(mission_id)
        marker_view = self.store.authority_phase11_kill_marker_v1(
            mission_id, int(anchor["event_seq"])
        )
        if (
            int(marker_view["anchor_seq"]) != int(anchor["event_seq"])
            or not hmac.compare_digest(
                str(marker_view["anchor_hash"]), str(anchor["event_hash"])
            )
        ):
            raise Phase11LiveMissionError(
                "durable kill marker diverges from authority anchor"
            )
        marker = marker_view.get("kill")
        if marker is None:
            return False
        if not isinstance(marker, Mapping):
            raise Phase11LiveMissionError(
                "durable kill marker contract diverges"
            )
        document = self._read_binding(mission_id)
        if document is None or not hmac.compare_digest(
            str(document["binding_digest"]), state.binding_digest
        ):
            raise Phase11LiveMissionError(
                "durable kill marker binding diverges"
            )
        detail = marker.get("detail")
        if not isinstance(detail, Mapping):
            raise Phase11LiveMissionError(
                "durable kill marker detail is invalid"
            )
        self._validate_authority_detail(document, "phase11.kill", detail)
        return True

    def _is_killed(
        self, mission_id: str, state: _KillState | None = None
    ) -> bool:
        state = state or self._kill_state(mission_id)
        if state.event.is_set():
            return True
        try:
            if state.kernel is None or state.kernel.is_set():
                state.event.set()
                return True
        except OSError:
            state.event.set()
            return True
        now = time.monotonic()
        if now < state.next_durable_check:
            return False
        if not state.durable_check_lock.acquire(blocking=False):
            return state.event.is_set()
        try:
            if now < state.next_durable_check:
                return state.event.is_set()
            state.next_durable_check = (
                now + _KILL_DURABLE_REFRESH_SECONDS
            )
            try:
                if self._durable_kill_marker(mission_id, state):
                    state.event.set()
                    assert state.kernel is not None
                    state.kernel.set()
            except Exception:
                state.event.set()
        finally:
            state.durable_check_lock.release()
        return state.event.is_set()

    def _begin_shutdown_failures(self) -> list[BaseException]:
        """Block new work and attempt every independent shutdown request."""

        with self._lock:
            if self._closed:
                return []
            self._closing = True
        failures: list[BaseException] = []
        if self.away_mode is not None:
            try:
                away_missions = tuple(self.away_mode.active_missions())
            except BaseException as exc:
                failures.append(exc)
                away_missions = ()
            for mission_id in away_missions:
                try:
                    self.request_kill(mission_id)
                except BaseException as exc:
                    failures.append(exc)
            try:
                stopped = self.away_mode.stop_all_for_shutdown()
                if stopped["failures"]:
                    failures.append(
                        Phase11LiveMissionError(
                            "Away driver stop reported failures"
                        )
                    )
            except BaseException as exc:
                failures.append(exc)
        if self.external_agent is not None:
            try:
                external_missions = tuple(
                    self.external_agent.active_missions()
                )
            except BaseException as exc:
                failures.append(exc)
                external_missions = ()
            for mission_id in external_missions:
                try:
                    self.request_kill(mission_id)
                except BaseException as exc:
                    failures.append(exc)
        return failures

    def begin_shutdown(self) -> None:
        """Block new runners and request durable Away stop without closing handles."""

        failures = self._begin_shutdown_failures()
        if failures:
            raise Phase11LifecycleError(
                "Phase 11 shutdown request is incomplete", failures
            ) from failures[0]

    def close(self, timeout: float = 15.0) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Phase 11 close timeout is invalid")
        deadline = time.monotonic() + float(timeout)
        with self._lock:
            if self._closed:
                return
        failures = self._begin_shutdown_failures()
        if self.away_mode is not None:
            try:
                away_active = tuple(self.away_mode.active_missions())
                while away_active and time.monotonic() < deadline:
                    time.sleep(0.02)
                    away_active = tuple(self.away_mode.active_missions())
                if away_active:
                    failures.append(
                        Phase11LiveMissionError(
                            "Away drivers did not confirm shutdown"
                        )
                    )
            except BaseException as exc:
                failures.append(exc)
        while time.monotonic() < deadline:
            with self._lock:
                active_runners = sum(
                    state.active_runners
                    for state in self._kill_states.values()
                )
            if active_runners == 0:
                break
            time.sleep(0.02)
        with self._lock:
            if self.autopilot is not None:
                try:
                    autopilot_active = self.autopilot.has_active_processes()
                except BaseException as exc:
                    failures.append(exc)
                else:
                    if autopilot_active:
                        failures.append(
                            Phase11LiveMissionError(
                                "Project Autopilot jobs remain active"
                            )
                        )
            states = tuple(self._kill_states.values())
            for state in states:
                with state.lifecycle_lock:
                    if state.active_runners:
                        failures.append(
                            Phase11LiveMissionError(
                                "Phase 11 runners did not confirm shutdown"
                            )
                        )
        if self.away_mode is not None:
            try:
                self.away_mode.close()
            except BaseException as exc:
                failures.append(exc)
        if self.external_agent is not None:
            try:
                self.external_agent.close()
            except BaseException as exc:
                failures.append(exc)
        for state in states:
            if state.kernel is not None:
                with state.lifecycle_lock:
                    if state.active_runners:
                        continue
                try:
                    state.kernel.close()
                except BaseException as exc:
                    failures.append(exc)
                else:
                    state.kernel_closed = True
        boundary = getattr(self, "_host_binding_boundary", None)
        if boundary is None:
            boundary = getattr(self, "_windows_binding_boundary", None)
        if boundary is not None:
            with self._lock:
                native_handles_open = any(
                    state.active_runners
                    or (
                        state.kernel is not None
                        and not state.kernel_closed
                    )
                    for state in self._kill_states.values()
                )
            if not native_handles_open:
                try:
                    boundary.close()
                except BaseException as exc:
                    failures.append(exc)
                else:
                    if getattr(self, "_host_binding_boundary", None) is boundary:
                        self._host_binding_boundary = None
                    if getattr(self, "_windows_binding_boundary", None) is boundary:
                        self._windows_binding_boundary = None
        if failures:
            raise Phase11LifecycleError(
                "Phase 11 shutdown is incomplete", failures
            ) from failures[0]
        with self._lock:
            self._kill_states.clear()
            self._closed = True
            self._closing = False

    def __del__(self) -> None:
        try:
            self.close()
        except BaseException:
            pass

    def runner(self, tool: str, args: dict[str, Any], key: str) -> Any:
        self._require_enabled()
        with self._lock:
            if self._closing or self._closed:
                raise Phase11LiveMissionError(
                    "Phase 11 is shutting down"
                )
        mission_id = self.store.authority_mission_for_step_key_v1(key)
        if mission_id is None:
            return self.base_runner(tool, args, key)
        binding = self._phase11_binding(
            mission_id, reconcile_kill=True
        )
        if binding is None:
            return self.base_runner(tool, args, key)
        with self._lock:
            if self._closing or self._closed:
                raise Phase11LiveMissionError(
                    "Phase 11 is shutting down"
                )
            kill_state = self._kill_state(mission_id)
            with kill_state.lifecycle_lock:
                kill_state.active_runners += 1
        try:
            return self._run_bound(
                tool, args, key, mission_id, binding, kill_state
            )
        finally:
            with kill_state.lifecycle_lock:
                kill_state.active_runners -= 1

    def _run_bound(
        self,
        tool: str,
        args: dict[str, Any],
        key: str,
        mission_id: str,
        binding: Mapping[str, Any],
        kill_state: _KillState,
    ) -> Any:
        exact = next(
            (
                step
                for step in binding["fixed_steps"]
                if step["idempotency_key"] == key
            ),
            None,
        )
        mission_type = binding.get("mission_type")
        if (
            exact is None
            or exact["tool"] != tool
            or exact["args"] != args
            or (
                mission_type == MISSION_TYPE
                and tool not in _PLAN_TOOLS
            )
            or (
                mission_type == AUTOPILOT_MISSION_TYPE
                and tool != AUTOPILOT_TOOL_NAME
            )
            or (
                mission_type == AWAY_MISSION_TYPE
                and tool != AWAY_TOOL_NAME
            )
            or (
                mission_type == EXTERNAL_AGENT_MISSION_TYPE
                and tool != EXTERNAL_AGENT_TOOL_NAME
            )
        ):
            raise Phase11LiveMissionError(
                "Phase 11 runner invocation diverges from immutable binding"
            )
        if mission_type == AUTOPILOT_MISSION_TYPE:
            if self.autopilot is None:
                raise Phase11LiveMissionError(
                    "project_autopilot_v1 is not explicitly enabled"
                )
            if self._is_killed(mission_id, kill_state):
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": "kill_requested",
                }
            envelope = self._autopilot_envelope(binding)
            executable_envelope = self._executable_envelope(binding, envelope)
            return self.autopilot.execute(
                mission_id=mission_id,
                binding_digest=str(binding["binding_digest"]),
                envelope=envelope,
                patch=self._read_patch_artifact(binding),
                cancel=lambda: self._is_killed(mission_id, kill_state),
                executable_plan=executable_envelope,
            )
        if mission_type == AWAY_MISSION_TYPE:
            if self.away_mode is None or self._key is None:
                raise Phase11LiveMissionError(
                    "governed browser Away Mode is not explicitly enabled"
                )
            if self._is_killed(mission_id, kill_state):
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": "kill_requested",
                }
            try:
                envelope = BrowserActionEnvelopeV1.from_binding(
                    binding.get("away"),
                    signing_key=self._key,
                )
                runtime_authority = self.store.runtime_authority_v1(
                    mission_id
                )
                if (
                    runtime_authority["approval_digest"]
                    != envelope.approval_digest
                ):
                    raise Phase11LiveMissionError(
                        "Away runtime approval digest diverges"
                    )
                approved_deadline_ns = min(
                    int(runtime_authority["deadline_ns"]),
                    int(runtime_authority["lease_expires_ns"]),
                )
                return self.away_mode.execute(
                    envelope=envelope,
                    binding_digest=str(binding["binding_digest"]),
                    execution_id_digest=hashlib.sha256(
                        (
                            str(key)
                            + "\0"
                            + str(runtime_authority["lease_owner_digest"])
                        ).encode("utf-8")
                    ).hexdigest(),
                    approved_deadline_ns=approved_deadline_ns,
                    cancel=lambda: self._is_killed(mission_id, kill_state),
                )
            except GovernedAwayWaiting as exc:
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": _redacted_reason(exc),
                }
            except GovernedAwayError as exc:
                raise Phase11LiveMissionError(
                    "governed browser Away execution failed safely"
                ) from exc
        if mission_type == EXTERNAL_AGENT_MISSION_TYPE:
            adapter = self._ensure_external_agent()
            if self._is_killed(mission_id, kill_state):
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": "kill_requested",
                }
            envelope = self._external_agent_envelope(binding)
            try:
                return adapter.execute(
                    envelope=envelope,
                    task=adapter.read_task(
                        envelope,
                        binding.get("external_agent_task_artifact", {}),
                    ),
                    cancel=lambda: self._is_killed(mission_id, kill_state),
                )
            except (ExternalAgentUnavailable, ExternalAgentWaiting) as exc:
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": _redacted_reason(exc),
                }
            except ExternalAgentContractError as exc:
                raise Phase11LiveMissionError(
                    "external-agent execution failed safely"
                ) from exc
        if self._is_killed(mission_id, kill_state):
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": "Phase 11 kill requested before read-only step",
            }
        baseline = _snapshot_from_dict(binding["baseline"])
        before = self._require_enabled().verify(baseline)
        try:
            self._record_receipt(mission_id, before, f"before_tool:{tool}")
        except MissionError:
            if self._is_killed(mission_id, kill_state):
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": "Phase 11 kill won before receipt commit",
                }
            raise
        if before.verdict != "PASS":
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": "workspace drift detected before read-only step",
            }
        outcome = self.base_runner(tool, args, key)
        if self._is_killed(mission_id, kill_state):
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": "Phase 11 late result discarded after kill",
            }
        after = self._require_enabled().verify(baseline)
        try:
            self._record_receipt(mission_id, after, f"after_tool:{tool}")
        except MissionError:
            if self._is_killed(mission_id, kill_state):
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": "Phase 11 concurrent kill discarded result",
                }
            raise
        if after.verdict != "PASS":
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": "workspace drift detected after read-only step",
            }
        return outcome

    def status(self, mission_id: str) -> dict[str, Any]:
        self._require_enabled()
        self._validate_current_binding(mission_id, advance_anchor=True)
        mission = self.store.get(mission_id)
        events = self._events(mission_id)
        mission_type = str(
            self._read_binding(mission_id)["mission_type"]
        )
        receipt_events = [
            event for event in events if event["event"] == "phase11.receipt"
        ]
        latest = receipt_events[-1]["detail"] if receipt_events else None
        killed = any(event["event"] == "phase11.kill" for event in events)
        reconciliations = [
            event["detail"]
            for event in events
            if event["event"] == "phase11.reconciliation"
            and isinstance(event.get("detail"), Mapping)
        ]
        verdict = str(latest["verdict"]) if latest else None
        reason = (
            "kill_requested"
            if killed
            else str(latest["reason"])
            if latest
            else mission.error or mission.state
        )
        projected_state = (
            "waiting"
            if (killed or verdict == "DRIFT")
            and mission.state not in {"failed", "cancelled", "succeeded"}
            else mission.state
        )
        receipt = None
        if latest:
            receipt = {
                "stage": str(latest["stage"])[:80],
                "verdict": verdict,
                "reason": _redacted_reason(latest["reason"]),
                "baseline_digest_prefix": str(latest["baseline_sha256"])[:12],
                "observed_digest_prefix": str(latest["observed_sha256"])[:12],
            }
        result = {
            "mission_id": mission.id,
            "title": mission.title,
            "mission_type": mission_type,
            "state": projected_state,
            "current_step": mission.current_step,
            "reason": _redacted_reason(reason),
            "receipt": receipt,
            "verdict": verdict,
            "provider_cost": 0.0,
        }
        if (
            mission_type == AUTOPILOT_MISSION_TYPE
            and self.autopilot is not None
        ):
            checkpoint = self.autopilot.checkpoint_status(mission_id)
            if checkpoint is not None:
                result["autopilot"] = {
                    "stage": str(checkpoint.get("stage", ""))[:80],
                    "gates_completed": int(checkpoint.get("gate_index", 0)),
                    "controlled_clone_retained": Path(
                        str(checkpoint.get("clone", ""))
                    ).exists(),
                    "waiting_reason": _redacted_reason(
                        checkpoint.get("waiting_reason") or "none"
                    ),
                }
                if "executable_plan_digest" in checkpoint:
                    result["autopilot"].update(
                        {
                            "executable_gates_completed": int(
                                checkpoint.get("executable_gate_index", 0)
                            ),
                            "repository_code_execution_state": str(
                                checkpoint.get(
                                    "repository_code_execution_state",
                                    "not_started",
                                )
                            ),
                        }
                    )
                    if reconciliations:
                        latest_reconciliation = reconciliations[-1]
                        result["autopilot"]["reconciliation"] = {
                            "decision": str(
                                latest_reconciliation.get(
                                    "decision", "still_unknown"
                                )
                            ),
                            "resolution_id_prefix": str(
                                latest_reconciliation.get("resolution_id", "")
                            )[:12],
                            "dispatch_permitted": False,
                        }
        if mission_type == AWAY_MISSION_TYPE and self.away_mode is not None:
            result["away_mode"] = self.away_mode.status(mission_id)
        if mission_type == EXTERNAL_AGENT_MISSION_TYPE:
            external_status = self._ensure_external_agent().status(mission_id)
            result["external_agent"] = external_status
            result["provider_cost"] = float(
                external_status.get("cost_usd", 0.0)
            )
        return result


__all__ = [
    "BINDING_SCHEMA",
    "FEATURE_FLAG",
    "MISSION_TYPE",
    "EXTERNAL_AGENT_MISSION_TYPE",
    "Phase11LifecycleError",
    "Phase11LiveMissionError",
    "Phase11LiveMissionV1",
    "WORKSPACE_ROOTS_FLAG",
    "feature_enabled",
]
