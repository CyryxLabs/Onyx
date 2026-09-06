"""Default-off, local-Docker boundary for bounded Phase 11 executable tests."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, BinaryIO, Callable, Mapping, Protocol, Sequence, cast

if TYPE_CHECKING:
    from core.phase11_execution_ledger_v1 import Phase11ExecutionLedgerV1


FEATURE_FLAG = "ONYX_PHASE11_EXECUTABLE_SANDBOX_V1"
SCHEMA = "onyx.phase11.executable_sandbox.v1"
MAX_ARG_COUNT = 128
MAX_ARG_BYTES = 16 * 1024
MAX_TOTAL_ARG_BYTES = 64 * 1024
MAX_PATH_BYTES = 4 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 300.0
MAX_CONCURRENT_EXECUTIONS = 4
MAX_CLONE_ENTRIES = 20_000
MAX_CLONE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_SECONDS = 30.0
OWNER_LABEL = "com.cyryxlabs.onyx.phase11.owner"
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_APPROVED_EXECUTABLES = frozenset(
    {
        "cargo",
        "cmake",
        "ctest",
        "dotnet",
        "go",
        "gradle",
        "gradlew",
        "mailpit",
        "make",
        "mvn",
        "mvnw",
        "node",
        "npm",
        "pnpm",
        "pytest",
        "python",
        "python3",
        "ruff",
        "yarn",
    }
)
_COMMAND_WRAPPERS = frozenset(
    {
        "bash",
        "busybox",
        "cmd",
        "cmd.exe",
        "dash",
        "env",
        "env.exe",
        "fish",
        "ksh",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "sh",
        "xargs",
        "zsh",
    }
)
_SENSITIVE_OPTION = re.compile(
    r"^(?:--?)?(?:api[-_]?key|auth(?:orization)?|bearer|client[-_]?secret|"
    r"cookie|credential|password|passwd|private[-_]?key|secret|token)$",
    re.IGNORECASE,
)
_SECRET_SHAPE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{12,}|"
    r"\bsk-[A-Za-z0-9_-]{20,}|"
    r"\bghp_[A-Za-z0-9]{20,}|"
    r"\bgithub_pat_[A-Za-z0-9_]{20,}|"
    r"\bxox[baprs]-[A-Za-z0-9-]{20,}|"
    r"\bAIza[A-Za-z0-9_-]{20,}|"
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
    r"[A-Za-z0-9_-]{10,})"
)
_EXECUTION_ID = re.compile(r"^[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_MISSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NPIPE_HOST = re.compile(r"^npipe:////\./pipe/[A-Za-z0-9_.-]+$")
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_MISSIONS: set[str] = set()
_ACTIVE_COUNT = 0


class ExecutableSandboxError(RuntimeError):
    """Base error for the executable sandbox boundary."""


class SandboxDisabledError(ExecutableSandboxError):
    pass


class SandboxContractError(ExecutableSandboxError):
    pass


class SandboxCollisionError(ExecutableSandboxError):
    pass


class SandboxDockerError(ExecutableSandboxError):
    pass


class SandboxCleanupError(ExecutableSandboxError):
    pass


class CancelSignal(Protocol):
    def is_set(self) -> bool: ...


ProcessFactory = Callable[..., subprocess.Popen[bytes]]
PathResolver = Callable[[str], str | os.PathLike[str]]


@dataclass(frozen=True)
class ExecutableSandboxRequestV1:
    mission_id: str
    execution_id: str
    clone_root: str
    image_id: str
    argv: tuple[str, ...]
    timeout_seconds: float = 60.0
    max_output_bytes: int = 512 * 1024
    attempt: int = 1


@dataclass(frozen=True)
class ExecutableSandboxReceiptV1:
    schema: str
    execution_id: str
    attempt: int
    mission_hmac_sha256: str
    image_sha256: str
    argv_hmac_sha256: str
    prelaunch_clone_manifest_hmac_sha256: str
    stdout_hmac_sha256: str
    stderr_hmac_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    exit_code: int | None
    duration_ms: int
    verdict: str
    receipt_hmac_sha256: str


def verify_executable_sandbox_receipt_v1(
    receipt: ExecutableSandboxReceiptV1 | Mapping[str, object],
    *,
    signing_key: bytes,
    mission_id: str,
    execution_id: str,
    image_id: str,
    argv: tuple[str, ...],
    attempt: int = 1,
) -> bool:
    """Independently authenticate a content-free receipt against its request."""
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        return False
    if not isinstance(mission_id, str) or not _MISSION_ID.fullmatch(mission_id):
        return False
    if not isinstance(execution_id, str) or not _EXECUTION_ID.fullmatch(execution_id):
        return False
    if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
        return False
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        return False
    if (
        not isinstance(argv, tuple)
        or not argv
        or any(not isinstance(argument, str) for argument in argv)
    ):
        return False
    try:
        document = (
            asdict(receipt)
            if isinstance(receipt, ExecutableSandboxReceiptV1)
            else dict(receipt)
        )
    except (TypeError, ValueError):
        return False
    expected_keys = {
        field.name for field in ExecutableSandboxReceiptV1.__dataclass_fields__.values()
    }
    if set(document) != expected_keys:
        return False
    signature = document.get("receipt_hmac_sha256")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    unsigned = {**document, "receipt_hmac_sha256": ""}
    expected_signature = _keyed(
        signing_key,
        b"receipt",
        _canonical(unsigned),
    )
    verdict = document.get("verdict")
    return bool(
        document.get("schema") == SCHEMA
        and document.get("execution_id") == execution_id
        and document.get("attempt") == attempt
        and document.get("mission_hmac_sha256")
        == _keyed(signing_key, b"mission", mission_id.encode("utf-8"))
        and document.get("image_sha256") == image_id.removeprefix("sha256:")
        and document.get("argv_hmac_sha256")
        == _keyed(signing_key, b"argv", _canonical(argv))
        and verdict in {"PASS", "FAIL", "CANCELLED", "TIMEOUT", "OUTPUT_LIMIT"}
        and isinstance(document.get("stdout_bytes"), int)
        and not isinstance(document.get("stdout_bytes"), bool)
        and cast(int, document["stdout_bytes"]) >= 0
        and isinstance(document.get("stderr_bytes"), int)
        and not isinstance(document.get("stderr_bytes"), bool)
        and cast(int, document["stderr_bytes"]) >= 0
        and isinstance(document.get("duration_ms"), int)
        and not isinstance(document.get("duration_ms"), bool)
        and cast(int, document["duration_ms"]) >= 0
        and (
            document.get("exit_code") is None
            or (
                isinstance(document.get("exit_code"), int)
                and not isinstance(document.get("exit_code"), bool)
            )
        )
        and all(
            isinstance(document.get(key), str)
            and re.fullmatch(r"[0-9a-f]{64}", str(document[key]))
            for key in (
                "prelaunch_clone_manifest_hmac_sha256",
                "stdout_hmac_sha256",
                "stderr_hmac_sha256",
            )
        )
        and hmac.compare_digest(signature, expected_signature)
    )


def feature_enabled(environment: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environment is None else environment
    return source.get(FEATURE_FLAG) == "true"


def _command_basename(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).name.casefold()


def _secret_shaped_argument(value: str) -> bool:
    if _SECRET_SHAPE.search(value) or re.search(
        r"://[^/\s:@]+:[^/\s@]+@", value
    ):
        return True
    candidate = value
    if "=" in candidate:
        option, _payload = candidate.split("=", 1)
        if _SENSITIVE_OPTION.fullmatch(option):
            return True
    if ":" in candidate:
        header, _payload = candidate.split(":", 1)
        if _SENSITIVE_OPTION.fullmatch(header.strip()):
            return True
    return _SENSITIVE_OPTION.fullmatch(candidate) is not None


def validate_executable_command_v1(value: object) -> tuple[str, ...]:
    """Return one exact, secret-free test/build argv or fail closed."""
    if not isinstance(value, tuple) or not 1 <= len(value) <= MAX_ARG_COUNT:
        raise SandboxContractError("sandbox_command_argv_invalid")
    argv: list[str] = []
    total = 0
    for argument in value:
        if (
            not isinstance(argument, str)
            or not argument
            or any(character in argument for character in ("\x00", "\r", "\n"))
        ):
            raise SandboxContractError("sandbox_command_argument_invalid")
        encoded = argument.encode("utf-8")
        total += len(encoded)
        if len(encoded) > MAX_ARG_BYTES or total > MAX_TOTAL_ARG_BYTES:
            raise SandboxContractError("sandbox_command_arguments_too_large")
        if _secret_shaped_argument(argument):
            raise SandboxContractError("sandbox_secret_shaped_argument_refused")
        argv.append(argument)
    executable = _command_basename(argv[0])
    if executable in _COMMAND_WRAPPERS or executable not in _APPROVED_EXECUTABLES:
        raise SandboxContractError("sandbox_executable_not_approved")
    if any(
        _command_basename(argument) in _COMMAND_WRAPPERS
        for argument in argv[1:]
    ):
        raise SandboxContractError("sandbox_command_wrapper_refused")
    lowered = tuple(argument.casefold() for argument in argv[1:])
    if executable in {"python", "python3"}:
        if any(argument in {"-c", "--command", "-"} for argument in lowered):
            raise SandboxContractError("sandbox_inline_code_refused")
        if "-m" in lowered:
            index = lowered.index("-m")
            if (
                index + 1 >= len(lowered)
                or lowered[index + 1]
                not in {"compileall", "pytest", "unittest"}
            ):
                raise SandboxContractError("sandbox_python_module_refused")
    if executable == "node" and any(
        argument in {"-e", "--eval", "-p", "--print"}
        for argument in lowered
    ):
        raise SandboxContractError("sandbox_inline_code_refused")
    if executable in {"npm", "pnpm", "yarn"}:
        verb = next(
            (
                argument
                for argument in lowered
                if argument and not argument.startswith("-")
            ),
            "",
        )
        if verb not in {"run", "test"}:
            raise SandboxContractError("sandbox_package_command_refused")
    return tuple(argv)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _keyed(signing_key: bytes, domain: bytes, value: bytes) -> str:
    return hmac.new(signing_key, domain + b"\0" + value, hashlib.sha256).hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _reject_link_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            linked = current.is_symlink() or _is_reparse(current)
        except OSError as exc:
            raise SandboxContractError("sandbox_path_inspection_failed") from exc
        if linked:
            raise SandboxContractError("sandbox_linked_path_refused")


def _default_resolver(value: str) -> str:
    return str(Path(value).resolve(strict=True))


def _path_identity(path: Path) -> tuple[int, int, int, int]:
    try:
        details = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise SandboxContractError("sandbox_path_identity_failed") from exc
    return (
        int(details.st_dev),
        int(details.st_ino),
        int(details.st_mode),
        int(details.st_ctime_ns),
    )


class _OutputCapture:
    """Capture fixed per-stream budgets with deterministic stream digests."""

    def __init__(self, limit: int, signing_key: bytes) -> None:
        self.stdout_limit = (limit + 1) // 2
        self.stderr_limit = limit // 2
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.stdout_digest = hmac.new(signing_key, b"stdout\0", hashlib.sha256)
        self.stderr_digest = hmac.new(signing_key, b"stderr\0", hashlib.sha256)
        self.overflow = threading.Event()
        self.failures: list[BaseException] = []

    def consume(self, stream: object, label: str) -> None:
        read = getattr(stream, "read", None)
        if read is None:
            self.failures.append(RuntimeError("sandbox_pipe_missing"))
            return
        target = self.stdout if label == "stdout" else self.stderr
        limit = self.stdout_limit if label == "stdout" else self.stderr_limit
        digest = self.stdout_digest if label == "stdout" else self.stderr_digest
        try:
            while True:
                block = read(65_536)
                if not block:
                    return
                if not isinstance(block, bytes):
                    block = str(block).encode("utf-8", errors="replace")
                remaining = max(0, limit - len(target))
                accepted = block[:remaining]
                if accepted:
                    target.extend(accepted)
                    digest.update(accepted)
                if len(block) > remaining:
                    self.overflow.set()
                    return
        except BaseException as exc:
            self.failures.append(exc)


@dataclass(frozen=True)
class _ProcessResult:
    state: str
    returncode: int | None
    stdout: bytes
    stderr: bytes
    stdout_hmac: str
    stderr_hmac: str


@dataclass
class _SlotLease:
    mission_lock: Path
    slot_stream: BinaryIO
    slot_index: int


@dataclass(frozen=True, slots=True)
class ExecutableSandboxHostV1:
    """Sealed host configuration; the process seam never receives host secrets."""

    docker_cli: str
    docker_host: str
    process_factory: ProcessFactory = subprocess.Popen

    def __post_init__(self) -> None:
        if (
            not isinstance(self.docker_cli, str)
            or not self.docker_cli
            or not isinstance(self.docker_host, str)
            or not self.docker_host
            or not callable(self.process_factory)
        ):
            raise SandboxContractError("sandbox_host_binding_invalid")

    def instantiate(
        self,
        *,
        container_platform: str,
        control_root: str,
        clone_parent: str,
        signing_key: bytes,
        execution_ledger: Phase11ExecutionLedgerV1 | None,
    ) -> "ExecutableTestSandboxV1":
        return ExecutableTestSandboxV1(
            docker_cli=self.docker_cli,
            docker_host=self.docker_host,
            container_platform=container_platform,
            control_root=control_root,
            clone_parent=clone_parent,
            signing_key=signing_key,
            enabled=True,
            process_factory=self.process_factory,
            execution_ledger=execution_ledger,
        )


class ExecutableTestSandboxV1:
    """Run one fixed-image command inside a hardened local Linux container."""

    def __init__(
        self,
        *,
        docker_cli: str,
        docker_host: str | None = None,
        container_platform: str | None = None,
        control_root: str | None = None,
        clone_parent: str | None = None,
        signing_key: bytes | None = None,
        enabled: bool = False,
        process_factory: ProcessFactory = subprocess.Popen,
        path_resolver: PathResolver = _default_resolver,
        clock: Callable[[], float] = time.monotonic,
        execution_ledger: Phase11ExecutionLedgerV1 | None = None,
    ) -> None:
        self._enabled = enabled is True
        self._process_factory = process_factory
        self._path_resolver = path_resolver
        self._clock = clock
        self._execution_ledger = execution_ledger
        self._docker_cli: Path | None = None
        self._docker_host: str | None = None
        self._container_platform: str | None = None
        self._control_root: Path | None = None
        self._clone_parent: Path | None = None
        self._lock_root: Path | None = None
        self._control_root_identity: tuple[int, int, int] | None = None
        self._clone_parent_identity: tuple[int, int, int] | None = None
        self._lock_root_identity: tuple[int, int, int] | None = None
        self._signing_key: bytes | None = None
        self._slot_paths: tuple[Path, ...] = ()
        if self._enabled:
            if not isinstance(signing_key, bytes) or len(signing_key) < 32:
                raise SandboxContractError("sandbox_signing_key_invalid")
            if not isinstance(docker_host, str):
                raise SandboxContractError("sandbox_docker_host_required")
            if container_platform not in {"linux/amd64", "linux/arm64"}:
                raise SandboxContractError("sandbox_container_platform_invalid")
            if not isinstance(control_root, str) or not isinstance(clone_parent, str):
                raise SandboxContractError("sandbox_trusted_roots_required")
            self._signing_key = signing_key
            self._docker_host = self._validated_docker_host(docker_host)
            self._container_platform = container_platform
            self._docker_cli = self._trusted_path(docker_cli, kind="executable")
            self._control_root = self._trusted_path(control_root, kind="directory")
            self._clone_parent = self._trusted_path(clone_parent, kind="directory")
            self._validate_root_ownership(self._control_root)
            self._validate_root_ownership(self._clone_parent)
            lock_root = self._control_root / "phase11-mission-locks"
            try:
                lock_root.mkdir(mode=0o700, exist_ok=True)
            except OSError as exc:
                raise SandboxContractError("sandbox_lock_root_unavailable") from exc
            self._lock_root = self._trusted_path(str(lock_root), kind="directory")
            self._validate_root_ownership(self._lock_root)
            slot_paths: list[Path] = []
            for index in range(MAX_CONCURRENT_EXECUTIONS):
                slot_path = self._control_root / f"phase11-global-slot-{index}.lock"
                try:
                    slot_path.touch(mode=0o600, exist_ok=True)
                    if slot_path.stat().st_size == 0:
                        slot_path.write_bytes(b"\0")
                except OSError as exc:
                    raise SandboxContractError(
                        "sandbox_global_slot_unavailable"
                    ) from exc
                slot_paths.append(self._trusted_path(str(slot_path), kind="file"))
            self._slot_paths = tuple(slot_paths)
            self._control_root_identity = _path_identity(self._control_root)[:3]
            self._clone_parent_identity = _path_identity(self._clone_parent)[:3]
            self._lock_root_identity = _path_identity(self._lock_root)[:3]

    @classmethod
    def from_environment(
        cls,
        *,
        docker_cli: str,
        environment: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> "ExecutableTestSandboxV1":
        return cls(
            docker_cli=docker_cli,
            enabled=feature_enabled(environment),
            **kwargs,
        )

    def integration_binding(self) -> dict[str, object]:
        """Return the non-secret immutable binding required by trusted callers."""
        return {
            "enabled": self._enabled,
            "control_root": (
                None if self._control_root is None else str(self._control_root)
            ),
            "clone_parent": (
                None if self._clone_parent is None else str(self._clone_parent)
            ),
            "container_platform": self._container_platform,
        }

    @staticmethod
    def _validated_docker_host(value: str) -> str:
        if any(character in value for character in ("\x00", "\r", "\n")):
            raise SandboxContractError("sandbox_docker_host_invalid")
        if os.name != "nt" and value.startswith("unix://"):
            socket_path = value.removeprefix("unix://")
            if not socket_path.startswith("/") or "," in socket_path:
                raise SandboxContractError("sandbox_docker_host_invalid")
            requested = Path(socket_path)
            _reject_link_chain(requested)
            try:
                resolved = requested.resolve(strict=True)
                mode = resolved.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise SandboxContractError("sandbox_docker_socket_unavailable") from exc
            if not stat.S_ISSOCK(mode):
                raise SandboxContractError("sandbox_docker_host_not_socket")
            return f"unix://{resolved}"
        if os.name == "nt" and _NPIPE_HOST.fullmatch(value):
            return value
        raise SandboxContractError("sandbox_docker_host_must_be_local")

    @staticmethod
    def _validate_root_ownership(path: Path) -> None:
        if os.name == "nt":
            local_value = os.environ.get("LOCALAPPDATA")
            if not local_value:
                raise SandboxContractError("sandbox_localappdata_unavailable")
            try:
                local_root = Path(local_value).resolve(strict=True)
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise SandboxContractError(
                    "sandbox_user_root_resolution_failed"
                ) from exc
            if resolved == local_root or not resolved.is_relative_to(local_root):
                raise SandboxContractError("sandbox_root_outside_localappdata")
            try:
                win32security: Any = importlib.import_module("win32security")
                ntsecuritycon: Any = importlib.import_module("ntsecuritycon")
                win32api: Any = importlib.import_module("win32api")
                security = win32security.GetNamedSecurityInfo(
                    str(resolved),
                    win32security.SE_FILE_OBJECT,
                    win32security.OWNER_SECURITY_INFORMATION
                    | win32security.DACL_SECURITY_INFORMATION,
                )
                owner = security.GetSecurityDescriptorOwner()
                token = win32security.OpenProcessToken(
                    win32api.GetCurrentProcess(),
                    win32security.TOKEN_QUERY,
                )
                current_sid = win32security.GetTokenInformation(
                    token, win32security.TokenUser
                )[0]
                allowed = {
                    win32security.ConvertSidToStringSid(current_sid),
                    "S-1-5-18",  # Local System
                    "S-1-5-32-544",  # Builtin Administrators
                    "S-1-3-0",  # Creator Owner
                    "S-1-3-4",  # Owner Rights
                }
                owner_value = win32security.ConvertSidToStringSid(owner)
                if owner_value not in allowed:
                    raise SandboxContractError("sandbox_root_owner_invalid")
                dacl = security.GetSecurityDescriptorDacl()
                if dacl is None:
                    raise SandboxContractError("sandbox_root_null_dacl_refused")
                write_mask = (
                    ntsecuritycon.FILE_GENERIC_WRITE
                    | ntsecuritycon.GENERIC_WRITE
                    | ntsecuritycon.GENERIC_ALL
                    | ntsecuritycon.FILE_ALL_ACCESS
                    | ntsecuritycon.DELETE
                    | ntsecuritycon.WRITE_DAC
                    | ntsecuritycon.WRITE_OWNER
                    | ntsecuritycon.FILE_DELETE_CHILD
                )
                evaluated_allow_ace_types = {
                    win32security.ACCESS_ALLOWED_ACE_TYPE,
                    getattr(win32security, "ACCESS_ALLOWED_OBJECT_ACE_TYPE", 5),
                }
                recognized_non_allow_ace_types = {
                    getattr(win32security, name, value)
                    for name, value in (
                        ("ACCESS_DENIED_ACE_TYPE", 1),
                        ("SYSTEM_AUDIT_ACE_TYPE", 2),
                        ("SYSTEM_ALARM_ACE_TYPE", 3),
                        ("ACCESS_DENIED_OBJECT_ACE_TYPE", 6),
                        ("SYSTEM_AUDIT_OBJECT_ACE_TYPE", 7),
                        ("SYSTEM_ALARM_OBJECT_ACE_TYPE", 8),
                        ("ACCESS_DENIED_CALLBACK_ACE_TYPE", 10),
                        ("ACCESS_DENIED_CALLBACK_OBJECT_ACE_TYPE", 12),
                        ("SYSTEM_AUDIT_CALLBACK_ACE_TYPE", 13),
                        ("SYSTEM_ALARM_CALLBACK_ACE_TYPE", 14),
                        ("SYSTEM_AUDIT_CALLBACK_OBJECT_ACE_TYPE", 15),
                        ("SYSTEM_ALARM_CALLBACK_OBJECT_ACE_TYPE", 16),
                    )
                }
                for index in range(dacl.GetAceCount()):
                    ace = dacl.GetAce(index)
                    ace_type = ace[0][0]
                    if ace_type in recognized_non_allow_ace_types:
                        continue
                    if ace_type not in evaluated_allow_ace_types:
                        raise SandboxContractError(
                            "sandbox_root_unsupported_ace_refused"
                        )
                    mask = int(ace[1])
                    # Standard and object access-allow ACE tuples both expose
                    # the trustee SID as their final element.
                    sid = ace[-1]
                    sid_value = win32security.ConvertSidToStringSid(sid)
                    if mask & write_mask and sid_value not in allowed:
                        raise SandboxContractError(
                            "sandbox_root_foreign_write_ace_refused"
                        )
            except SandboxContractError:
                raise
            except Exception as exc:
                raise SandboxContractError(
                    "sandbox_root_acl_validation_failed"
                ) from exc
            return
        details = path.stat(follow_symlinks=False)
        geteuid = getattr(os, "geteuid")
        if details.st_uid != geteuid() or details.st_mode & 0o022:
            raise SandboxContractError("sandbox_trusted_root_permissions_invalid")

    def _trusted_path(self, value: str, *, kind: str) -> Path:
        if not isinstance(value, str):
            raise SandboxContractError("sandbox_path_invalid")
        if len(value.encode("utf-8")) > MAX_PATH_BYTES:
            raise SandboxContractError("sandbox_path_too_large")
        if any(character in value for character in ("\x00", "\r", "\n")):
            raise SandboxContractError("sandbox_path_character_refused")
        requested = Path(value)
        if not requested.is_absolute():
            raise SandboxContractError("sandbox_path_must_be_absolute")
        absolute = requested.absolute()
        _reject_link_chain(absolute)
        try:
            resolved = Path(self._path_resolver(str(absolute)))
        except (OSError, RuntimeError, ValueError) as exc:
            raise SandboxContractError("sandbox_path_resolution_failed") from exc
        if not resolved.is_absolute():
            raise SandboxContractError("sandbox_resolver_returned_relative_path")
        _reject_link_chain(resolved)
        if kind in {"file", "executable"}:
            if not resolved.is_file():
                raise SandboxContractError("sandbox_trusted_file_required")
            if (
                kind == "executable"
                and os.name != "nt"
                and not os.access(resolved, os.X_OK)
            ):
                raise SandboxContractError("docker_cli_not_executable")
        elif not resolved.is_dir():
            raise SandboxContractError("sandbox_trusted_directory_required")
        return resolved

    @staticmethod
    def _host_environment() -> dict[str, str]:
        allowed = ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        environment.update({"DOCKER_CLI_HINTS": "false", "LC_ALL": "C"})
        return environment

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            raise SandboxDockerError("sandbox_docker_process_stuck")

    @staticmethod
    def _close_process_resources(process: subprocess.Popen[bytes]) -> None:
        for name in ("stdin", "stdout", "stderr"):
            stream = getattr(process, name, None)
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    close()
                except OSError:
                    pass

    def _docker_command(self, *arguments: str) -> list[str]:
        assert self._docker_cli is not None and self._docker_host is not None
        return [str(self._docker_cli), "--host", self._docker_host, *arguments]

    def _spawn(self, command: Sequence[str]) -> subprocess.Popen[bytes]:
        try:
            return self._process_factory(
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=self._host_environment(),
            )
        except (OSError, ValueError) as exc:
            raise SandboxDockerError("sandbox_docker_start_failed") from exc

    def _capture_process(
        self,
        command: Sequence[str],
        *,
        timeout: float,
        output_limit: int,
        cancel: CancelSignal | None = None,
    ) -> _ProcessResult:
        assert self._signing_key is not None
        process = self._spawn(command)
        capture = _OutputCapture(output_limit, self._signing_key)
        if process.stdout is None or process.stderr is None:
            self._stop_process(process)
            self._close_process_resources(process)
            raise SandboxDockerError("sandbox_docker_pipes_missing")
        threads = [
            threading.Thread(
                target=capture.consume, args=(process.stdout, "stdout"), daemon=True
            ),
            threading.Thread(
                target=capture.consume, args=(process.stderr, "stderr"), daemon=True
            ),
        ]
        for thread in threads:
            thread.start()
        started = self._clock()
        state = "COMPLETED"
        try:
            while process.poll() is None:
                if capture.overflow.is_set():
                    state = "OUTPUT_LIMIT"
                    self._stop_process(process)
                    break
                if cancel is not None and cancel.is_set():
                    state = "CANCELLED"
                    self._stop_process(process)
                    break
                if self._clock() - started >= timeout:
                    state = "TIMEOUT"
                    self._stop_process(process)
                    break
                time.sleep(0.01)
            for thread in threads:
                thread.join(timeout=0.5)
            if capture.overflow.is_set():
                state = "OUTPUT_LIMIT"
                self._stop_process(process)
            if any(thread.is_alive() for thread in threads):
                self._stop_process(process)
                raise SandboxDockerError("sandbox_output_thread_stuck")
            if capture.failures:
                raise SandboxDockerError(
                    "sandbox_output_capture_failed"
                ) from capture.failures[0]
            if process.poll() is None:
                self._stop_process(process)
            return _ProcessResult(
                state=state,
                returncode=process.returncode,
                stdout=bytes(capture.stdout),
                stderr=bytes(capture.stderr),
                stdout_hmac=capture.stdout_digest.hexdigest(),
                stderr_hmac=capture.stderr_digest.hexdigest(),
            )
        finally:
            self._close_process_resources(process)

    def _inspect_image(self, image_id: str, entrypoint: str) -> None:
        result = self._capture_process(
            self._docker_command("image", "inspect", image_id),
            timeout=10.0,
            output_limit=64 * 1024,
        )
        if result.state != "COMPLETED" or result.returncode != 0:
            raise SandboxDockerError("sandbox_local_image_unavailable")
        try:
            payload = json.loads(result.stdout.decode("utf-8"))
            image = payload[0]
            observed = image["Id"]
            operating_system = image["Os"]
            architecture = image["Architecture"]
            volumes = image["Config"].get("Volumes")
            configured_entrypoint = image["Config"].get("Entrypoint")
        except (IndexError, KeyError, TypeError, UnicodeError, ValueError) as exc:
            raise SandboxDockerError("sandbox_image_inspect_invalid") from exc
        if observed != image_id:
            raise SandboxContractError("sandbox_image_id_mismatch")
        if operating_system != "linux":
            raise SandboxContractError("sandbox_image_os_must_be_linux")
        assert self._container_platform is not None
        expected_architecture = self._container_platform.split("/", 1)[1]
        if architecture != expected_architecture:
            raise SandboxContractError("sandbox_image_architecture_mismatch")
        if volumes is not None:
            raise SandboxContractError("sandbox_image_declared_volumes_refused")
        if configured_entrypoint not in (None, []) and configured_entrypoint != [
            entrypoint
        ]:
            raise SandboxContractError("sandbox_image_entrypoint_mismatch")

    @staticmethod
    def _validate_request(request: ExecutableSandboxRequestV1) -> None:
        try:
            valid_object = isinstance(request, ExecutableSandboxRequestV1)
            mission_id = request.mission_id
            execution_id = request.execution_id
            clone_root = request.clone_root
            image_id = request.image_id
            argv = request.argv
            timeout = request.timeout_seconds
            output_limit = request.max_output_bytes
            attempt = request.attempt
        except (AttributeError, TypeError) as exc:
            raise SandboxContractError("sandbox_request_invalid") from exc
        if not valid_object:
            raise SandboxContractError("sandbox_request_invalid")
        if not isinstance(mission_id, str) or not _MISSION_ID.fullmatch(mission_id):
            raise SandboxContractError("sandbox_mission_id_invalid")
        if not isinstance(execution_id, str) or not _EXECUTION_ID.fullmatch(
            execution_id
        ):
            raise SandboxContractError("sandbox_execution_id_invalid")
        if not isinstance(clone_root, str):
            raise SandboxContractError("sandbox_clone_root_invalid")
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            raise SandboxContractError("sandbox_image_id_must_be_exact_sha256")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise SandboxContractError("sandbox_attempt_invalid")
        if not isinstance(argv, tuple) or not argv or len(argv) > MAX_ARG_COUNT:
            raise SandboxContractError("sandbox_argv_count_invalid")
        total = 0
        for argument in argv:
            if not isinstance(argument, str) or "\x00" in argument:
                raise SandboxContractError("sandbox_argv_invalid")
            size = len(argument.encode("utf-8"))
            if size > MAX_ARG_BYTES:
                raise SandboxContractError("sandbox_argument_too_large")
            total += size
        if total > MAX_TOTAL_ARG_BYTES:
            raise SandboxContractError("sandbox_argv_too_large")
        validate_executable_command_v1(argv)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or not 0 < float(timeout) <= MAX_TIMEOUT_SECONDS
        ):
            raise SandboxContractError("sandbox_timeout_invalid")
        if (
            isinstance(output_limit, bool)
            or not isinstance(output_limit, int)
            or not 0 < output_limit <= MAX_OUTPUT_BYTES
        ):
            raise SandboxContractError("sandbox_output_limit_invalid")

    def _validate_clone(self, value: str) -> tuple[Path, tuple[int, int, int, int]]:
        if any(character in value for character in (",", "\x00", "\r", "\n")):
            raise SandboxContractError("sandbox_mount_path_character_refused")
        clone = self._trusted_path(value, kind="directory")
        assert self._clone_parent is not None
        if clone.parent != self._clone_parent:
            raise SandboxContractError("sandbox_clone_must_be_direct_child")
        self._validate_root_ownership(clone)
        return clone, _path_identity(clone)

    def _clone_manifest(self, clone: Path, cancel: CancelSignal | None = None) -> str:
        assert self._signing_key is not None
        started = self._clock()

        def check_control() -> None:
            if cancel is not None and cancel.is_set():
                raise SandboxContractError("sandbox_clone_manifest_cancelled")
            if self._clock() - started >= MAX_MANIFEST_SECONDS:
                raise SandboxContractError("sandbox_clone_manifest_timeout")

        digest = hmac.new(self._signing_key, b"clone-manifest\0", hashlib.sha256)
        try:
            root_details = clone.stat(follow_symlinks=False)
        except OSError as exc:
            raise SandboxContractError("sandbox_clone_manifest_failed") from exc
        root_identity = _path_identity(clone)
        root_device = int(root_details.st_dev)
        entries = 0
        total_bytes = 0
        bytes_read = 0
        pending = [clone]
        while pending:
            check_control()
            directory = pending.pop()
            try:
                children = []
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        check_control()
                        entries += 1
                        if entries > MAX_CLONE_ENTRIES:
                            raise SandboxContractError("sandbox_clone_entry_limit")
                        children.append(entry)
                children.sort(key=lambda entry: entry.name)
            except OSError as exc:
                raise SandboxContractError("sandbox_clone_manifest_failed") from exc
            for entry in children:
                check_control()
                path = Path(entry.path)
                try:
                    details = path.stat(follow_symlinks=False)
                except OSError as exc:
                    raise SandboxContractError("sandbox_clone_manifest_failed") from exc
                if entry.is_symlink() or _is_reparse(path):
                    raise SandboxContractError("sandbox_clone_link_refused")
                self._validate_root_ownership(path)
                check_control()
                if int(details.st_dev) != root_device:
                    raise SandboxContractError("sandbox_clone_device_escape")
                relative = path.relative_to(clone).as_posix().encode("utf-8")
                if stat.S_ISDIR(details.st_mode):
                    digest.update(
                        _canonical(
                            ["d", relative.decode("utf-8"), int(details.st_mode)]
                        )
                    )
                    pending.append(path)
                    continue
                if not stat.S_ISREG(details.st_mode):
                    raise SandboxContractError("sandbox_clone_special_entry_refused")
                if int(details.st_nlink) != 1:
                    raise SandboxContractError("sandbox_clone_hardlink_refused")
                total_bytes += int(details.st_size)
                if total_bytes > MAX_CLONE_BYTES:
                    raise SandboxContractError("sandbox_clone_byte_limit")
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor: int | None = None
                try:
                    descriptor = os.open(path, flags)
                    opened = os.fstat(descriptor)
                    identity = (
                        int(details.st_dev),
                        int(details.st_ino),
                        int(details.st_size),
                        int(details.st_mtime_ns),
                    )
                    opened_identity = (
                        int(opened.st_dev),
                        int(opened.st_ino),
                        int(opened.st_size),
                        int(opened.st_mtime_ns),
                    )
                    if (
                        identity != opened_identity
                        or not stat.S_ISREG(opened.st_mode)
                        or int(opened.st_nlink) != 1
                    ):
                        raise SandboxContractError(
                            "sandbox_clone_file_identity_changed"
                        )
                    digest.update(
                        _canonical(
                            [
                                "f",
                                relative.decode("utf-8"),
                                int(opened.st_mode),
                                int(opened.st_size),
                                int(opened.st_mtime_ns),
                            ]
                        )
                    )
                    while True:
                        check_control()
                        block = os.read(descriptor, 65_536)
                        if not block:
                            break
                        bytes_read += len(block)
                        if bytes_read > MAX_CLONE_BYTES:
                            raise SandboxContractError(
                                "sandbox_clone_actual_byte_limit"
                            )
                        digest.update(block)
                    after = os.fstat(descriptor)
                    if (
                        int(after.st_size),
                        int(after.st_mtime_ns),
                        int(after.st_ino),
                        int(after.st_dev),
                    ) != (
                        int(opened.st_size),
                        int(opened.st_mtime_ns),
                        int(opened.st_ino),
                        int(opened.st_dev),
                    ):
                        raise SandboxContractError("sandbox_clone_file_changed")
                except SandboxContractError:
                    raise
                except OSError as exc:
                    raise SandboxContractError("sandbox_clone_manifest_failed") from exc
                finally:
                    if descriptor is not None:
                        try:
                            os.close(descriptor)
                        except OSError:
                            pass
        if _path_identity(clone) != root_identity:
            raise SandboxContractError("sandbox_clone_identity_changed")
        return digest.hexdigest()

    def _trusted_roots_unchanged(self) -> bool:
        assert self._control_root is not None
        assert self._clone_parent is not None
        assert self._lock_root is not None
        return (
            _path_identity(self._control_root)[:3] == self._control_root_identity
            and _path_identity(self._clone_parent)[:3] == self._clone_parent_identity
            and _path_identity(self._lock_root)[:3] == self._lock_root_identity
        )

    def _mission_lock_path(self, mission_id: str) -> Path:
        assert self._lock_root is not None and self._signing_key is not None
        name = _keyed(self._signing_key, b"mission-lock", mission_id.encode("utf-8"))
        return self._lock_root / f"{name}.lock"

    @staticmethod
    def _try_global_lock(stream: BinaryIO) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl: Any = importlib.import_module("fcntl")
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    @staticmethod
    def _unlock_global(stream: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl: Any = importlib.import_module("fcntl")
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _acquire_global_slot(self) -> tuple[BinaryIO, int]:
        for index, path in enumerate(self._slot_paths):
            try:
                stream = path.open("r+b", buffering=0)
            except OSError as exc:
                raise SandboxContractError("sandbox_global_slot_open_failed") from exc
            if self._try_global_lock(stream):
                return stream, index
            stream.close()
        raise SandboxCollisionError("sandbox_global_concurrency_limit_reached")

    def _release_global_slot(self, mission_id: str, stream: BinaryIO) -> None:
        try:
            self._unlock_global(stream)
        finally:
            try:
                stream.close()
            finally:
                self._release_process_slot(mission_id)

    def _acquire_slot(self, mission_id: str) -> _SlotLease:
        global _ACTIVE_COUNT
        with _ACTIVE_LOCK:
            if _ACTIVE_COUNT >= MAX_CONCURRENT_EXECUTIONS:
                raise SandboxCollisionError("sandbox_concurrency_limit_reached")
            if mission_id in _ACTIVE_MISSIONS:
                raise SandboxCollisionError("sandbox_mission_already_running")
            _ACTIVE_COUNT += 1
            _ACTIVE_MISSIONS.add(mission_id)
        try:
            slot_stream, slot_index = self._acquire_global_slot()
        except BaseException:
            self._release_process_slot(mission_id)
            raise
        lock_path = self._mission_lock_path(mission_id)
        descriptor: int | None = None
        created = False
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            created = True
            marker = b"ONYX_PHASE11_LOCK_V1\n"
            if os.write(descriptor, marker) != len(marker):
                raise OSError("sandbox_mission_lock_short_write")
            os.close(descriptor)
            descriptor = None
            return _SlotLease(lock_path, slot_stream, slot_index)
        except FileExistsError as exc:
            try:
                raise SandboxCollisionError(
                    "sandbox_mission_cross_process_collision"
                ) from exc
            finally:
                self._release_global_slot(mission_id, slot_stream)
        except OSError as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if created:
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    try:
                        raise SandboxContractError(
                            "sandbox_mission_lock_rollback_failed"
                        ) from exc
                    finally:
                        self._release_global_slot(mission_id, slot_stream)
            try:
                raise SandboxContractError("sandbox_mission_lock_failed") from exc
            finally:
                self._release_global_slot(mission_id, slot_stream)

    @staticmethod
    def _release_process_slot(mission_id: str) -> None:
        global _ACTIVE_COUNT
        with _ACTIVE_LOCK:
            _ACTIVE_MISSIONS.discard(mission_id)
            _ACTIVE_COUNT = max(0, _ACTIVE_COUNT - 1)

    def _release_slot(self, mission_id: str, lease: _SlotLease) -> None:
        try:
            lease.mission_lock.unlink(missing_ok=True)
        finally:
            self._release_global_slot(mission_id, lease.slot_stream)

    @staticmethod
    def _decode_json_object(result: _ProcessResult, error: str) -> dict[str, object]:
        try:
            value = json.loads(result.stdout.decode("utf-8"))
            if isinstance(value, list):
                value = value[0]
            if not isinstance(value, dict):
                raise TypeError
            return value
        except (IndexError, TypeError, UnicodeError, ValueError) as exc:
            raise SandboxDockerError(error) from exc

    def _inspect_container(self, target: str) -> dict[str, object] | None:
        result = self._capture_process(
            self._docker_command("container", "inspect", target),
            timeout=10.0,
            output_limit=64 * 1024,
        )
        if result.state != "COMPLETED":
            raise SandboxCleanupError("sandbox_container_inspect_incomplete")
        if result.returncode != 0:
            lowered = result.stderr.decode("utf-8", errors="ignore").lower()
            if "no such container" in lowered or "no such object" in lowered:
                return None
            raise SandboxCleanupError("sandbox_container_inspect_failed")
        return self._decode_json_object(result, "sandbox_container_inspect_invalid")

    def _cleanup(self, container_name: str, owner_token: str) -> None:
        container = self._inspect_container(container_name)
        if container is None:
            return
        try:
            container_id = container["Id"]
            labels = container["Config"]["Labels"]  # type: ignore[index]
            observed_owner = labels[OWNER_LABEL]  # type: ignore[index]
        except (KeyError, TypeError) as exc:
            raise SandboxCleanupError(
                "sandbox_container_ownership_unverifiable"
            ) from exc
        if (
            not isinstance(container_id, str)
            or not _CONTAINER_ID.fullmatch(container_id)
            or observed_owner != owner_token
        ):
            raise SandboxCleanupError("sandbox_container_ownership_mismatch")
        result = self._capture_process(
            self._docker_command("rm", "--force", "--volumes", container_id),
            timeout=10.0,
            output_limit=4096,
        )
        if result.state != "COMPLETED" or result.returncode != 0:
            raise SandboxCleanupError("sandbox_container_cleanup_failed")
        if self._inspect_container(container_id) is not None:
            raise SandboxCleanupError("sandbox_container_cleanup_unproven")

    def _receipt(
        self,
        request: ExecutableSandboxRequestV1,
        *,
        clone_manifest_hmac: str,
        stdout_hmac: str,
        stderr_hmac: str,
        stdout_bytes: int,
        stderr_bytes: int,
        exit_code: int | None,
        duration_ms: int,
        verdict: str,
    ) -> ExecutableSandboxReceiptV1:
        assert self._signing_key is not None
        receipt = ExecutableSandboxReceiptV1(
            schema=SCHEMA,
            execution_id=request.execution_id,
            attempt=request.attempt,
            mission_hmac_sha256=_keyed(
                self._signing_key, b"mission", request.mission_id.encode("utf-8")
            ),
            image_sha256=request.image_id.removeprefix("sha256:"),
            argv_hmac_sha256=_keyed(
                self._signing_key, b"argv", _canonical(request.argv)
            ),
            prelaunch_clone_manifest_hmac_sha256=clone_manifest_hmac,
            stdout_hmac_sha256=stdout_hmac,
            stderr_hmac_sha256=stderr_hmac,
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
            exit_code=exit_code,
            duration_ms=max(0, duration_ms),
            verdict=verdict,
            receipt_hmac_sha256="",
        )
        signature = _keyed(
            self._signing_key,
            b"receipt",
            _canonical({**asdict(receipt), "receipt_hmac_sha256": ""}),
        )
        return replace(receipt, receipt_hmac_sha256=signature)

    def execute(
        self,
        request: ExecutableSandboxRequestV1,
        *,
        cancel: CancelSignal | None = None,
    ) -> ExecutableSandboxReceiptV1:
        if not self._enabled:
            raise SandboxDisabledError("sandbox_feature_disabled")
        self._validate_request(request)
        clone, clone_identity = self._validate_clone(request.clone_root)
        lease = self._acquire_slot(request.mission_id)
        try:
            container_name: str | None = None
            owner_token: str | None = None
            started = 0.0
            primary_error: BaseException | None = None
            result: _ProcessResult | None = None
            clone_manifest: str | None = None
            container_may_exist = False
            ledger_reserved = False
            ledger_completed = False
            ledger_binding: dict[str, object] | None = None
            try:
                container_name = f"onyx-p11-{secrets.token_hex(16)}"
                owner_token = secrets.token_hex(32)
                started = self._clock()
                clone_manifest = self._clone_manifest(clone, cancel)
                self._inspect_image(request.image_id, request.argv[0])
                if not self._trusted_roots_unchanged():
                    raise SandboxContractError("sandbox_trusted_root_identity_changed")
                if _path_identity(clone) != clone_identity:
                    raise SandboxContractError("sandbox_clone_identity_changed")
                if self._clone_manifest(clone, cancel) != clone_manifest:
                    raise SandboxContractError("sandbox_clone_manifest_changed")
                assert self._container_platform is not None
                mount = (
                    f"type=bind,source={clone},target=/workspace,"
                    "readonly,bind-propagation=rprivate,bind-recursive=disabled"
                )
                command = self._docker_command(
                    "run",
                    "--rm",
                    "--name",
                    container_name,
                    "--label",
                    f"{OWNER_LABEL}={owner_token}",
                    "--pull",
                    "never",
                    "--platform",
                    self._container_platform,
                    "--network",
                    "none",
                    "--log-driver",
                    "none",
                    "--read-only",
                    "--no-healthcheck",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--user",
                    "65532:65532",
                    "--pids-limit",
                    "64",
                    "--memory",
                    "256m",
                    "--memory-swap",
                    "256m",
                    "--cpus",
                    "1.0",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
                    "--mount",
                    mount,
                    "--workdir",
                    "/workspace",
                    "--env",
                    "HOME=/tmp",
                    "--env",
                    "LANG=C.UTF-8",
                    "--env",
                    "LC_ALL=C.UTF-8",
                    "--env",
                    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "--entrypoint",
                    request.argv[0],
                    request.image_id,
                    *request.argv[1:],
                )
                if self._execution_ledger is not None:
                    ledger_binding = {
                        "mission_id": request.mission_id,
                        "execution_id": request.execution_id,
                        "workspace_id": clone_manifest,
                        "image_digest": request.image_id.removeprefix("sha256:"),
                        "argv_digest": hashlib.sha256(
                            _canonical(request.argv)
                        ).hexdigest(),
                        "attempt": request.attempt,
                    }
                    self._execution_ledger.append("intent", **ledger_binding)  # type: ignore[arg-type]
                    self._execution_ledger.append(
                        "dispatch_reserved", **ledger_binding  # type: ignore[arg-type]
                    )
                    ledger_reserved = self._execution_ledger.enabled
                container_may_exist = True
                result = self._capture_process(
                    command,
                    timeout=float(request.timeout_seconds),
                    output_limit=request.max_output_bytes,
                    cancel=cancel,
                )
            except BaseException as exc:
                primary_error = exc
            cleanup_error: BaseException | None = None
            if container_may_exist:
                assert container_name is not None and owner_token is not None
                try:
                    self._cleanup(container_name, owner_token)
                except BaseException as exc:
                    cleanup_error = exc
            if cleanup_error is not None:
                if ledger_reserved and not ledger_completed:
                    assert self._execution_ledger is not None and ledger_binding is not None
                    self._execution_ledger.append("unknown", **ledger_binding)  # type: ignore[arg-type]
                    ledger_completed = True
                if primary_error is not None:
                    raise cleanup_error from primary_error
                raise cleanup_error
            if primary_error is not None:
                if ledger_reserved and not ledger_completed:
                    assert self._execution_ledger is not None and ledger_binding is not None
                    self._execution_ledger.append("unknown", **ledger_binding)  # type: ignore[arg-type]
                    ledger_completed = True
                raise primary_error
            assert result is not None and clone_manifest is not None
            verdict = (
                result.state
                if result.state != "COMPLETED"
                else ("PASS" if result.returncode == 0 else "FAIL")
            )
            receipt = self._receipt(
                request,
                clone_manifest_hmac=clone_manifest,
                stdout_hmac=result.stdout_hmac,
                stderr_hmac=result.stderr_hmac,
                stdout_bytes=len(result.stdout),
                stderr_bytes=len(result.stderr),
                exit_code=result.returncode,
                duration_ms=int((self._clock() - started) * 1000),
                verdict=verdict,
            )
            if ledger_reserved:
                assert self._execution_ledger is not None and ledger_binding is not None
                receipt_document = asdict(receipt)
                if not verify_executable_sandbox_receipt_v1(
                    receipt,
                    signing_key=self._signing_key,
                    mission_id=request.mission_id,
                    execution_id=request.execution_id,
                    image_id=request.image_id,
                    argv=request.argv,
                    attempt=request.attempt,
                ):
                    self._execution_ledger.append(
                        "unknown", **ledger_binding  # type: ignore[arg-type]
                    )
                    ledger_completed = True
                    raise SandboxContractError("sandbox_receipt_verification_failed")
                self._execution_ledger.append(
                    "receipt",
                    receipt=receipt_document,
                    image_id=request.image_id,
                    argv=request.argv,
                    **ledger_binding,  # type: ignore[arg-type]
                )
                ledger_completed = True
            return receipt
        finally:
            primary_error = sys.exc_info()[1]
            try:
                self._release_slot(request.mission_id, lease)
            except BaseException as release_error:
                normalized = SandboxCleanupError("sandbox_mission_slot_release_failed")
                if primary_error is not None:
                    raise normalized from primary_error
                raise normalized from release_error

    def run(
        self,
        request: ExecutableSandboxRequestV1,
        *,
        cancel: CancelSignal | None = None,
    ) -> ExecutableSandboxReceiptV1:
        return self.execute(request, cancel=cancel)


Phase11ExecutableSandboxV1 = ExecutableTestSandboxV1
DockerExecutableSandboxV1 = ExecutableTestSandboxV1
SandboxRequestV1 = ExecutableSandboxRequestV1
SandboxReceiptV1 = ExecutableSandboxReceiptV1
