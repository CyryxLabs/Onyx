"""Authenticated, clone-only external coding-agent adapter.

The adapter deliberately owns no mission authority.  A caller must supply an
immutable envelope signed by the host after MissionStore materializes and
approves the exact plan.  Provider work happens only in a detached local clone;
the owner checkout is verified before and after every attempt.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Generator, Mapping, Protocol, Sequence

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from core.missions import contains_secret, redact
from core.phase11_project_autopilot_v1 import _WindowsKillJob
from core.phase11_windows_namespace_v1 import (
    CloneCleanupContractError,
    CloneCleanupWaiting,
    WindowsTrustedDirectoryV1,
    _directory_rows,
)


MISSION_TYPE = "external_coding_agent_v1"
TOOL_NAME = "external_coding_agent_dispatch_v1"
CLEANUP_TOOL_NAME = "external_coding_agent_cleanup_v1"
FEATURE_FLAG = "ONYX_EXTERNAL_CODING_AGENT_V1"
SCHEMA = "onyx.external_agent.mission_envelope.v1"
PROVIDER_ID = "claude-code-cli"
_ENVELOPE_DOMAIN = b"ONYX/EXTERNAL-AGENT/ENVELOPE/V1\0"
_CHECKPOINT_DOMAIN = b"ONYX/EXTERNAL-AGENT/CHECKPOINT/V1\0"
_ARTIFACT_DOMAIN = b"ONYX/EXTERNAL-AGENT/ARTIFACT/V1\0"
_RESERVATION_DOMAIN = b"ONYX/EXTERNAL-AGENT/RESERVATION/V1\0"
_TERMINAL_CLONE_RETENTION = 8
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_MISSION_ID = re.compile(r"^mis_[0-9a-f]{32}$")
_WORKSPACE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,79}$")
_FILE_ID = re.compile(r"^[0-9a-f]{1,32}:[0-9a-f]{1,32}$")
_CREATE_SUSPENDED = getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
_TRUSTED_GIT_INSTALLS_V1 = {
    r"C:\Program Files\Git\cmd\git.exe": frozenset(
        {"34a408843194be320d8a87a3c12cd5c7d2e08d03b24567a41db32e21d12569d2"}
    )
}
_SECRET_NAME = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|COOKIE|PRIVATE_KEY|ACCESS_KEY|API_KEY)",
    re.IGNORECASE,
)
_REDACT_VALUE = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._~+/=-]{8,}|"
    r"((?:api[_-]?key|token|password|secret)\s*[=:]\s*)\S+"
)
_ALLOWED_ENV = {
    "ALLUSERSPROFILE",
    "APPDATA",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
}
_CONTEXT_SUFFIXES = {
    ".c",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".html",
    ".java",
    ".js",
    ".json",
    ".md",
    ".py",
    ".qml",
    ".rs",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


class ExternalAgentError(RuntimeError):
    pass


class ExternalAgentContractError(ExternalAgentError, ValueError):
    pass


class ExternalAgentUnavailable(ExternalAgentError):
    pass


class ExternalAgentWaiting(ExternalAgentError):
    """The provider may have observed the request; automatic retry is forbidden."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _safe_text(value: object, limit: int = 1000) -> str:
    text = str(redact(value)).replace("\x00", "").strip()
    text = _REDACT_VALUE.sub(lambda match: (match.group(1) or match.group(2)) + "[REDACTED]", text)
    return text[:limit]


def _relative_root(value: object) -> str:
    text = str(value).replace("\\", "/").strip()
    path = PurePosixPath(text)
    if (
        not text
        or text.startswith("/")
        or ":" in text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ExternalAgentContractError("allowed root must be a normalized relative path")
    return path.as_posix()


def _under_allowed(path: str, allowed_roots: Sequence[str]) -> bool:
    candidate = PurePosixPath(path.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    for root in allowed_roots:
        boundary = PurePosixPath(root)
        if candidate == boundary or boundary in candidate.parents:
            return True
    return False


def _decode_git_quoted_path(value: str) -> str:
    if not value.startswith('"'):
        if "\t" in value or "\n" in value or "\r" in value:
            raise ExternalAgentContractError("Git patch path is invalid")
        return value
    if len(value) < 2 or not value.endswith('"'):
        raise ExternalAgentContractError("Git quoted path is invalid")
    output = bytearray()
    index = 1
    escapes = {
        "a": 7,
        "b": 8,
        "t": 9,
        "n": 10,
        "v": 11,
        "f": 12,
        "r": 13,
        '"': 34,
        "\\": 92,
    }
    while index < len(value) - 1:
        char = value[index]
        if char != "\\":
            output.extend(char.encode("utf-8", "strict"))
            index += 1
            continue
        index += 1
        if index >= len(value) - 1:
            raise ExternalAgentContractError("Git quoted path escape is invalid")
        escaped = value[index]
        if escaped in escapes:
            output.append(escapes[escaped])
            index += 1
            continue
        if escaped not in "01234567":
            raise ExternalAgentContractError("Git quoted path escape is invalid")
        digits = escaped
        index += 1
        while (
            index < len(value) - 1
            and len(digits) < 3
            and value[index] in "01234567"
        ):
            digits += value[index]
            index += 1
        output.append(int(digits, 8))
    try:
        decoded = output.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise ExternalAgentContractError(
            "Git quoted path encoding is invalid"
        ) from exc
    if any(character in decoded for character in ("\x00", "\n", "\r", "\t")):
        raise ExternalAgentContractError("Git patch path contains control data")
    return decoded


def _encode_git_quoted_path(value: str) -> str:
    """Emit Git's C-style path form without relying on locale or quotePath."""
    output: list[str] = ['"']
    for byte in value.encode("utf-8", "strict"):
        if 0x20 <= byte <= 0x7E and byte not in {0x22, 0x5C}:
            output.append(chr(byte))
        elif byte == 0x22:
            output.append('\\"')
        elif byte == 0x5C:
            output.append("\\\\")
        else:
            output.append(f"\\{byte:03o}")
    output.append('"')
    return "".join(output)


def _run_git(
    git_cli: Path,
    cwd: Path,
    argv: Sequence[str],
    *,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(git_cli), *argv],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        shell=False,
        env=_provider_environment(),
    )


def _run_git_input(
    git_cli: Path,
    cwd: Path,
    argv: Sequence[str],
    payload: bytes,
    *,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(git_cli), *argv],
        cwd=str(cwd),
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        shell=False,
        env=_provider_environment(),
    )


def _provider_environment() -> dict[str, str]:
    output: dict[str, str] = {}
    for name, value in os.environ.items():
        upper = name.upper()
        if upper in _ALLOWED_ENV:
            output[name] = value
    output["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    output["DISABLE_TELEMETRY"] = "1"
    return output


def _file_identity_sha256(path: Path) -> str:
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    return _sha256_bytes(
        _canonical(
            {
                "path": str(resolved),
                "device": int(stat.st_dev),
                "inode": int(stat.st_ino),
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        )
    )


@dataclass(frozen=True, slots=True)
class _ExecutableSnapshotV1:
    path: str
    sha256: str
    identity_sha256: str
    file_id: str


class _PinnedExecutableV1:
    """Hold an executable deny-write/delete while identity and process agree."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(os.path.abspath(os.fspath(path)))
        if not self.path.is_absolute():
            raise ExternalAgentUnavailable(
                "pinned executable path is not absolute"
            )

    @contextmanager
    def open(self) -> Generator[_ExecutableSnapshotV1, None, None]:
        if os.name == "nt":
            import win32con
            import win32file

            ancestor_handles: list[Any] = []
            handle: Any | None = None
            try:
                current = Path(self.path.anchor)
                for component in self.path.parts[1:-1]:
                    current /= component
                    ancestor = win32file.CreateFile(
                        str(current),
                        0x00000080,  # FILE_READ_ATTRIBUTES
                        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                        None,
                        win32con.OPEN_EXISTING,
                        0x00200000 | 0x02000000,
                        None,
                    )
                    ancestor_info = win32file.GetFileInformationByHandle(
                        ancestor
                    )
                    if int(ancestor_info[0]) & 0x00000400:
                        ancestor.Close()
                        raise ExternalAgentUnavailable(
                            "pinned executable has a reparse ancestor"
                        )
                    ancestor_handles.append(ancestor)
                handle = win32file.CreateFile(
                    str(self.path),
                    win32con.GENERIC_READ,
                    win32con.FILE_SHARE_READ,
                    None,
                    win32con.OPEN_EXISTING,
                    win32con.FILE_ATTRIBUTE_NORMAL | 0x00200000,
                    None,
                )
                info = win32file.GetFileInformationByHandle(handle)
                if int(info[0]) & (
                    0x00000010  # FILE_ATTRIBUTE_DIRECTORY
                    | 0x00000400  # FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise ExternalAgentUnavailable(
                        "pinned executable is not a regular non-reparse file"
                    )
                volume = int(info[4])
                size = (int(info[5]) << 32) | int(info[6])
                file_index = (int(info[8]) << 32) | int(info[9])
                file_id = f"{volume:08x}:{file_index:016x}"
                win32file.SetFilePointer(handle, 0, win32con.FILE_BEGIN)
                hasher = hashlib.sha256()
                while True:
                    _status, chunk = win32file.ReadFile(
                        handle, 1024 * 1024
                    )
                    if not chunk:
                        break
                    hasher.update(chunk)
                digest = hasher.hexdigest()
                identity = _sha256_bytes(
                    _canonical(
                        {
                            "path": str(self.path),
                            "volume": volume,
                            "file_index": file_index,
                            "size": size,
                            "last_write": str(info[3]),
                        }
                    )
                )
                yield _ExecutableSnapshotV1(
                    str(self.path), digest, identity, file_id
                )
            finally:
                if handle is not None:
                    handle.Close()
                for ancestor in reversed(ancestor_handles):
                    ancestor.Close()
            return
        current = Path(self.path.anchor)
        for component in self.path.parts[1:]:
            current /= component
            try:
                current.lstat()
            except OSError as exc:
                raise ExternalAgentUnavailable(
                    "pinned executable is unavailable"
                ) from exc
            if current.is_symlink():
                raise ExternalAgentUnavailable(
                    "pinned executable has a linked ancestor"
                )
        if not self.path.is_file():
            raise ExternalAgentUnavailable("pinned executable is unavailable")
        descriptor = os.open(
            self.path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            stat = os.fstat(descriptor)
            file_id = f"{int(stat.st_dev):x}:{int(stat.st_ino):x}"
            os.lseek(descriptor, 0, os.SEEK_SET)
            hasher = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
            digest = hasher.hexdigest()
            identity = _sha256_bytes(
                _canonical(
                    {
                        "path": str(self.path),
                        "device": int(stat.st_dev),
                        "inode": int(stat.st_ino),
                        "size": int(stat.st_size),
                        "mtime_ns": int(stat.st_mtime_ns),
                    }
                )
            )
            yield _ExecutableSnapshotV1(
                str(self.path), digest, identity, file_id
            )
        finally:
            os.close(descriptor)


def _query_windows_process_image_path_v1(
    process: subprocess.Popen[bytes],
) -> Path:
    if os.name != "nt":
        raise ExternalAgentUnavailable(
            "Windows process image verification is unavailable"
        )
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    capacity = 32768
    buffer = ctypes.create_unicode_buffer(capacity)
    size = wintypes.DWORD(capacity)
    process_handle = wintypes.HANDLE(int(getattr(process, "_handle")))
    if not kernel32.QueryFullProcessImageNameW(
        process_handle,
        0,
        buffer,
        ctypes.byref(size),
    ):
        raise ExternalAgentUnavailable(
            "suspended process image path could not be verified"
        )
    value = buffer[: size.value]
    if not value:
        raise ExternalAgentUnavailable(
            "suspended process image path is empty"
        )
    return Path(os.path.abspath(value))


@contextmanager
def _verified_windows_process_image_v1(
    process: subprocess.Popen[bytes],
    approved: _ExecutableSnapshotV1,
) -> Generator[_ExecutableSnapshotV1, None, None]:
    image_path = _query_windows_process_image_path_v1(process)
    with _PinnedExecutableV1(image_path).open() as observed:
        if (
            observed.file_id != approved.file_id
            or not hmac.compare_digest(observed.sha256, approved.sha256)
        ):
            raise ExternalAgentUnavailable(
                "suspended process image identity mismatched approved executable"
            )
        yield observed


def resolve_trusted_git_v1() -> str:
    """Resolve only an explicitly pinned installed Git, never PATH."""
    if os.name != "nt":
        raise ExternalAgentUnavailable(
            "trusted Git resolver is Windows-only in V15"
        )
    for configured, allowed_hashes in _TRUSTED_GIT_INSTALLS_V1.items():
        candidate = Path(configured)
        if not candidate.is_absolute() or not candidate.is_file():
            continue
        with _PinnedExecutableV1(candidate).open() as snapshot:
            if snapshot.sha256 in allowed_hashes:
                return snapshot.path
    raise ExternalAgentUnavailable(
        "installed Git is not in the explicit V15 path/hash allowlist"
    )


@dataclass(frozen=True, slots=True)
class ExternalAgentEnvelopeV1:
    schema: str
    mission_id: str
    workspace_id: str
    workspace_root: str
    repository_commit: str
    owner_git_sha256: str
    repository_blob_manifest_sha256: str
    repository_blob_count: int
    git_executable_path: str
    git_executable_sha256: str
    git_executable_identity_sha256: str
    git_executable_file_id: str
    allowed_roots: tuple[str, ...]
    provider_id: str
    provider_version: str
    provider_executable_path: str
    provider_executable_sha256: str
    provider_executable_identity_sha256: str
    provider_executable_file_id: str
    provider_account_sha256: str
    model: str
    max_budget_usd: float
    max_seconds: int
    max_output_bytes: int
    task_sha256: str
    task_bytes: int
    approval_digest: str
    prior_artifact_sha256: str
    nonce: str
    issued_at_ns: int
    expires_at_ns: int
    signature: str

    @classmethod
    def build(
        cls,
        *,
        signing_key: bytes,
        mission_id: str,
        workspace_id: str,
        workspace_root: str,
        repository_commit: str,
        owner_git_sha256: str,
        repository_blob_manifest_sha256: str,
        repository_blob_count: int,
        git_executable_path: str,
        git_executable_sha256: str,
        git_executable_identity_sha256: str,
        git_executable_file_id: str,
        allowed_roots: Sequence[str],
        provider_version: str,
        provider_executable_path: str,
        provider_executable_sha256: str,
        provider_executable_identity_sha256: str,
        provider_executable_file_id: str,
        provider_account_sha256: str,
        model: str,
        max_budget_usd: float,
        max_seconds: int,
        max_output_bytes: int,
        task: str,
        approval_digest: str,
        prior_artifact_sha256: str = "",
        nonce: str | None = None,
        issued_at_ns: int | None = None,
    ) -> "ExternalAgentEnvelopeV1":
        roots = tuple(sorted({_relative_root(item) for item in allowed_roots}))
        now = time.time_ns() if issued_at_ns is None else issued_at_ns
        payload: dict[str, object] = {
            "schema": SCHEMA,
            "mission_id": mission_id,
            "workspace_id": str(workspace_id),
            "workspace_root": str(Path(workspace_root).resolve()),
            "repository_commit": str(repository_commit).lower(),
            "owner_git_sha256": str(owner_git_sha256).lower(),
            "repository_blob_manifest_sha256": str(
                repository_blob_manifest_sha256
            ).lower(),
            "repository_blob_count": int(repository_blob_count),
            "git_executable_path": os.path.abspath(
                os.fspath(git_executable_path)
            ),
            "git_executable_sha256": str(git_executable_sha256).lower(),
            "git_executable_identity_sha256": str(
                git_executable_identity_sha256
            ).lower(),
            "git_executable_file_id": str(git_executable_file_id).lower(),
            "allowed_roots": list(roots),
            "provider_id": PROVIDER_ID,
            "provider_version": str(provider_version),
            "provider_executable_path": os.path.abspath(
                os.fspath(provider_executable_path)
            ),
            "provider_executable_sha256": str(provider_executable_sha256).lower(),
            "provider_executable_identity_sha256": str(
                provider_executable_identity_sha256
            ).lower(),
            "provider_executable_file_id": str(
                provider_executable_file_id
            ).lower(),
            "provider_account_sha256": str(provider_account_sha256).lower(),
            "model": str(model).lower(),
            "max_budget_usd": float(max_budget_usd),
            "max_seconds": int(max_seconds),
            "max_output_bytes": int(max_output_bytes),
            "task_sha256": _sha256_bytes(task.encode("utf-8")),
            "task_bytes": len(task.encode("utf-8")),
            "approval_digest": str(approval_digest).lower(),
            "prior_artifact_sha256": str(prior_artifact_sha256).lower(),
            "nonce": nonce or uuid.uuid4().hex,
            "issued_at_ns": int(now),
            "expires_at_ns": int(now) + int(max_seconds * 1_000_000_000),
        }
        signature = hmac.new(
            signing_key, _ENVELOPE_DOMAIN + _canonical(payload), hashlib.sha256
        ).hexdigest()
        return cls(
            **{
                **payload,
                "allowed_roots": roots,
                "signature": signature,
            }
        )

    @classmethod
    def from_binding(
        cls, value: object, *, signing_key: bytes
    ) -> "ExternalAgentEnvelopeV1":
        if not isinstance(value, Mapping):
            raise ExternalAgentContractError(
                "external-agent envelope binding is invalid"
            )
        fields = set(cls.__dataclass_fields__)
        if set(value) != fields:
            raise ExternalAgentContractError(
                "external-agent envelope binding fields diverge"
            )
        try:
            envelope = cls(
                **{
                    **dict(value),
                    "allowed_roots": tuple(value["allowed_roots"]),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalAgentContractError(
                "external-agent envelope binding is invalid"
            ) from exc
        envelope.authenticate(signing_key, require_live=False)
        return envelope

    def unsigned(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("signature")
        payload["allowed_roots"] = list(self.allowed_roots)
        return payload

    def authenticate(
        self,
        signing_key: bytes,
        *,
        now_ns: int | None = None,
        require_live: bool = True,
    ) -> None:
        payload = self.unsigned()
        expected = hmac.new(
            signing_key, _ENVELOPE_DOMAIN + _canonical(payload), hashlib.sha256
        ).hexdigest()
        now = time.time_ns() if now_ns is None else now_ns
        if (
            type(self) is not ExternalAgentEnvelopeV1
            or self.schema != SCHEMA
            or _MISSION_ID.fullmatch(self.mission_id) is None
            or _WORKSPACE_ID.fullmatch(self.workspace_id) is None
            or not Path(self.workspace_root).is_absolute()
            or _GIT_COMMIT.fullmatch(self.repository_commit) is None
            or _HEX64.fullmatch(self.owner_git_sha256) is None
            or _HEX64.fullmatch(self.repository_blob_manifest_sha256) is None
            or not 0 <= self.repository_blob_count <= 20_000
            or not Path(self.git_executable_path).is_absolute()
            or _HEX64.fullmatch(self.git_executable_sha256) is None
            or _HEX64.fullmatch(self.git_executable_identity_sha256) is None
            or _FILE_ID.fullmatch(self.git_executable_file_id) is None
            or not self.allowed_roots
            or tuple(sorted(set(self.allowed_roots))) != self.allowed_roots
            or self.provider_id != PROVIDER_ID
            or not self.provider_version
            or not Path(self.provider_executable_path).is_absolute()
            or _HEX64.fullmatch(self.provider_executable_sha256) is None
            or _HEX64.fullmatch(
                self.provider_executable_identity_sha256
            )
            is None
            or _FILE_ID.fullmatch(self.provider_executable_file_id) is None
            or _HEX64.fullmatch(self.provider_account_sha256) is None
            or _MODEL_ID.fullmatch(self.model) is None
            or isinstance(self.max_budget_usd, bool)
            or not math.isfinite(self.max_budget_usd)
            or not 0 < self.max_budget_usd <= 25
            or not 30 <= self.max_seconds <= 3600
            or not 4096 <= self.max_output_bytes <= 2 * 1024 * 1024
            or _HEX64.fullmatch(self.task_sha256) is None
            or not 1 <= self.task_bytes <= 100_000
            or _HEX64.fullmatch(self.approval_digest) is None
            or (
                self.prior_artifact_sha256
                and _HEX64.fullmatch(self.prior_artifact_sha256) is None
            )
            or re.fullmatch(r"[0-9a-f]{32}", self.nonce) is None
            or not 0 < self.issued_at_ns < self.expires_at_ns
            or self.expires_at_ns - self.issued_at_ns
            != self.max_seconds * 1_000_000_000
            or (require_live and now < self.issued_at_ns)
            or (require_live and now > self.expires_at_ns)
            or not hmac.compare_digest(self.signature, expected)
        ):
            raise ExternalAgentContractError(
                "external-agent envelope authentication failed"
            )


@dataclass(frozen=True, slots=True)
class ProviderInvocationV1:
    session_id: str
    workspace: Path
    task: str
    model: str
    max_budget_usd: float
    max_seconds: int
    max_output_bytes: int


@dataclass(frozen=True, slots=True)
class ProviderResultV1:
    status: str
    session_id: str
    summary: str
    cost_usd: float
    output_bytes: int
    provider_error: str = ""
    patch: str = ""
    tests: tuple[str, ...] = ()
    account_receipt_sha256: str = ""


class ProviderV1(Protocol):
    provider_id: str
    version: str
    executable_sha256: str
    executable_identity_sha256: str
    executable_file_id: str

    def health(self) -> dict[str, object]: ...

    def invoke(
        self,
        request: ProviderInvocationV1,
        *,
        cancel: Callable[[], bool],
    ) -> ProviderResultV1: ...

    def cancel(self, session_id: str) -> bool: ...


class _BoundedCapture:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.data = bytearray()
        self.overflow = False
        self.lock = threading.Lock()

    def read(self, stream: Any) -> None:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            with self.lock:
                remaining = self.limit - len(self.data)
                if remaining > 0:
                    self.data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.overflow = True


def _bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_bytes: bytes | None = None,
    timeout: float,
    max_output_bytes: int = 2 * 1024 * 1024,
    approved_executable: _ExecutableSnapshotV1 | None = None,
) -> subprocess.CompletedProcess[bytes]:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW | _CREATE_SUSPENDED
    process = subprocess.Popen(
        list(argv),
        cwd=str(cwd),
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        env=dict(env),
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    job: _WindowsKillJob | None = None
    image_stack = ExitStack()
    try:
        if os.name == "nt":
            if approved_executable is None:
                raise ExternalAgentUnavailable(
                    "approved executable identity is required on Windows"
                )
            job = _WindowsKillJob(
                process,
                before_resume=lambda: image_stack.enter_context(
                    _verified_windows_process_image_v1(
                        process, approved_executable
                    )
                ),
            )
        stdout = _BoundedCapture(max_output_bytes)
        stderr = _BoundedCapture(min(max_output_bytes, 256 * 1024))
        readers = (
            threading.Thread(target=stdout.read, args=(process.stdout,), daemon=True),
            threading.Thread(target=stderr.read, args=(process.stderr,), daemon=True),
        )
        for reader in readers:
            reader.start()
        if input_bytes is not None:
            assert process.stdin is not None
            process.stdin.write(input_bytes)
            process.stdin.close()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if job is not None:
                job.terminate()
            else:
                process.kill()
            process.wait(timeout=5)
            raise
        for reader in readers:
            reader.join(timeout=2)
        if stdout.overflow or stderr.overflow:
            raise ExternalAgentContractError("bounded process output exceeded limit")
        return subprocess.CompletedProcess(
            list(argv),
            process.returncode,
            bytes(stdout.data),
            bytes(stderr.data),
        )
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        if process.poll() is None:
            if job is not None:
                job.terminate()
            else:
                process.kill()
            process.wait(timeout=5)
        if job is not None:
            job.close()
        image_stack.close()


class _HermeticGitV1:
    """Pinned Git executable with config, credential and protocol isolation."""

    def __init__(self, executable: str | os.PathLike[str], state_root: Path) -> None:
        self._pinned = _PinnedExecutableV1(executable)
        with self._pinned.open() as snapshot:
            self.executable = Path(snapshot.path)
            self.executable_sha256 = snapshot.sha256
            self.executable_identity_sha256 = snapshot.identity_sha256
            self.executable_file_id = snapshot.file_id
        self.home = state_root / "git-home"
        self.home.mkdir(parents=True, exist_ok=True)
        self._environment = _provider_environment()
        null = "NUL" if os.name == "nt" else "/dev/null"
        self._environment.update(
            {
                "HOME": str(self.home),
                "USERPROFILE": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / "xdg"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": null,
                "GIT_CEILING_DIRECTORIES": str(state_root),
                "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "never",
                "GIT_ASKPASS": null,
                "SSH_ASKPASS": null,
                "GIT_PROTOCOL_FROM_USER": "0",
                "GIT_OPTIONAL_LOCKS": "0",
            }
        )
        self._prefix = (
            "-c",
            f"core.hooksPath={null}",
            "-c",
            f"core.attributesFile={null}",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.safecrlf=true",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "credential.helper=",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.file.allow=always",
            "-c",
            "filter.lfs.required=false",
            "-c",
            "filter.lfs.smudge=",
            "-c",
            "filter.lfs.clean=",
        )

    def identity(self) -> tuple[str, str, str, str]:
        with self._pinned.open() as snapshot:
            return (
                snapshot.path,
                snapshot.sha256,
                snapshot.identity_sha256,
                snapshot.file_id,
            )

    def verify(
        self,
        *,
        path: str,
        sha256: str,
        identity_sha256: str,
        file_id: str | None = None,
    ) -> None:
        observed = self.identity()
        if (
            os.path.normcase(observed[0])
            != os.path.normcase(os.path.abspath(os.fspath(path)))
            or observed[1]
            != sha256
            or observed[2]
            != identity_sha256
            or observed[3]
            != (file_id or observed[3])
        ):
            raise ExternalAgentUnavailable("pinned Git executable identity drifted")

    def run(
        self,
        cwd: Path,
        argv: Sequence[str],
        *,
        payload: bytes | None = None,
        timeout: float = 30.0,
    ) -> subprocess.CompletedProcess[bytes]:
        with self._pinned.open() as snapshot:
            expected = (
                str(self.executable),
                self.executable_sha256,
                self.executable_identity_sha256,
                self.executable_file_id,
            )
            observed = (
                snapshot.path,
                snapshot.sha256,
                snapshot.identity_sha256,
                snapshot.file_id,
            )
            if observed != expected:
                raise ExternalAgentUnavailable(
                    "pinned Git executable identity drifted"
                )
            return _bounded_process(
                [str(self.executable), *self._prefix, *argv],
                cwd=cwd,
                env=self._environment,
                input_bytes=payload,
                timeout=timeout,
                approved_executable=snapshot,
            )


class _TrustedStateV1:
    """Create-once state under a pinned Windows directory boundary."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ExternalAgentContractError(
                "external-agent state root must be absolute"
            )
        self.root = Path(os.path.abspath(os.fspath(root)))
        self.boundary: WindowsTrustedDirectoryV1 | None = None
        if os.name == "nt":
            try:
                self.boundary = WindowsTrustedDirectoryV1(
                    root=self.root,
                    enabled=True,
                )
            except CloneCleanupContractError as exc:
                raise ExternalAgentContractError(
                    "external-agent state root has an untrusted ancestor"
                ) from exc
        else:
            current = self.root
            while current != current.parent:
                if current.exists() and current.is_symlink():
                    raise ExternalAgentContractError(
                        "external-agent state has a linked ancestor"
                    )
                current = current.parent
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            current = self.root
            while current != current.parent:
                if current.is_symlink():
                    raise ExternalAgentContractError(
                        "external-agent state has a linked ancestor"
                    )
                current = current.parent
        self._portable_lock = threading.RLock()

    def publish(self, relative: str, content: bytes) -> None:
        if self.boundary is not None:
            with self.boundary.session() as session:
                session.publish_create(relative, content)
            return
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            offset = 0
            while offset < len(content):
                offset += os.write(descriptor, content[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def read_optional(self, relative: str, max_bytes: int) -> bytes | None:
        if self.boundary is not None:
            with self.boundary.session() as session:
                return session.read_optional(relative, max_bytes=max_bytes)
        path = self.root / relative
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise ExternalAgentWaiting("external-agent state entry is invalid")
        value = path.read_bytes()
        if len(value) > max_bytes:
            raise ExternalAgentWaiting("external-agent state entry is oversized")
        return value

    def list_files(self, relative: str, prefix: str = "") -> tuple[str, ...]:
        if self.boundary is not None:
            with self.boundary.session() as session:
                with session.parent(f"{relative}/probe", create_directories=True) as (
                    parent,
                    _leaf,
                ):
                    return tuple(
                        sorted(
                            name
                            for name, is_directory, _attrs in _directory_rows(parent)
                            if not is_directory and name.startswith(prefix)
                        )
                    )
        directory = self.root / relative
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return tuple(
            sorted(
                entry.name
                for entry in os.scandir(directory)
                if entry.name.startswith(prefix) and entry.is_file(follow_symlinks=False)
            )
        )

    def list_directories(self, relative: str, prefix: str = "") -> tuple[str, ...]:
        if self.boundary is not None:
            with self.boundary.session() as session:
                with session.parent(f"{relative}/probe", create_directories=True) as (
                    parent,
                    _leaf,
                ):
                    return tuple(
                        sorted(
                            name
                            for name, is_directory, _attrs in _directory_rows(parent)
                            if is_directory and name.startswith(prefix)
                        )
                    )
        directory = self.root / relative
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return tuple(
            sorted(
                entry.name
                for entry in os.scandir(directory)
                if entry.name.startswith(prefix)
                and entry.is_dir(follow_symlinks=False)
            )
        )

    @contextmanager
    def lock(self, name: str) -> Generator[None, None, None]:
        if self.boundary is not None:
            deadline = time.monotonic() + 2.0
            while True:
                stack = ExitStack()
                try:
                    session = stack.enter_context(
                        self.boundary.session()
                    )
                    stack.enter_context(session.lock(name))
                except CloneCleanupWaiting:
                    stack.close()
                    if time.monotonic() >= deadline:
                        raise ExternalAgentWaiting(
                            "external-agent interprocess state lock is busy"
                        ) from None
                    time.sleep(0.01)
                    continue
                try:
                    yield
                finally:
                    stack.close()
                return
        with self._portable_lock:
            yield

    def close(self) -> None:
        if self.boundary is not None:
            self.boundary.close()
            self.boundary = None


class ClaudeCodeCliProviderV1:
    """Official Claude Code CLI boundary with no shell or publishing tools."""

    provider_id = PROVIDER_ID
    execution_account_receipt_supported = False

    def __init__(self, executable: str | os.PathLike[str]) -> None:
        self._pinned = _PinnedExecutableV1(executable)
        with self._pinned.open() as snapshot:
            self.executable = Path(snapshot.path)
            self.executable_sha256 = snapshot.sha256
            self.executable_identity_sha256 = snapshot.identity_sha256
            self.executable_file_id = snapshot.file_id
            version = _bounded_process(
                [snapshot.path, "--version"],
                cwd=self.executable.parent,
                env=_provider_environment(),
                timeout=10,
                approved_executable=snapshot,
            )
        if version.returncode != 0:
            raise ExternalAgentUnavailable("Claude Code version probe failed")
        self.version = _safe_text(version.stdout.decode("utf-8", "replace"), 80)
        if not self.version:
            raise ExternalAgentUnavailable("Claude Code version is unavailable")
        self._lock = threading.RLock()
        self._active: dict[
            str, tuple[subprocess.Popen[bytes], _WindowsKillJob | None]
        ] = {}
        self._health_cache: tuple[float, dict[str, object]] | None = None

    def health(self, *, force: bool = False) -> dict[str, object]:
        with self._lock:
            cached = self._health_cache
        if not force and cached is not None and time.monotonic() - cached[0] <= 2:
            return dict(cached[1])
        with self._pinned.open() as snapshot:
            if (
                snapshot.sha256 != self.executable_sha256
                or snapshot.identity_sha256
                != self.executable_identity_sha256
                or snapshot.file_id != self.executable_file_id
            ):
                raise ExternalAgentUnavailable(
                    "Claude Code executable changed after activation"
                )
            probe = _bounded_process(
                [snapshot.path, "auth", "status"],
                cwd=self.executable.parent,
                env=_provider_environment(),
                timeout=10,
                approved_executable=snapshot,
            )
        logged_in = False
        auth_method = "unavailable"
        account_binding = {
            "auth_method": "unavailable",
            "api_provider": "unavailable",
            "org_id": None,
        }
        try:
            parsed = json.loads(probe.stdout.decode("utf-8", "strict"))
            logged_in = parsed.get("loggedIn") is True
            auth_method = _safe_text(parsed.get("authMethod", "unknown"), 40)
            account_binding = {
                "auth_method": auth_method,
                "api_provider": _safe_text(
                    parsed.get("apiProvider", "unknown"), 40
                ),
                "org_id": _safe_text(parsed.get("orgId", ""), 80) or None,
            }
        except (UnicodeError, json.JSONDecodeError):
            pass
        result = {
            "provider_id": self.provider_id,
            "version": self.version,
            "available": probe.returncode == 0 and logged_in,
            "auth_method": auth_method,
            "executable_path": str(self.executable),
            "binary_sha256": snapshot.sha256,
            "executable_identity_sha256": snapshot.identity_sha256,
            "executable_file_id": snapshot.file_id,
            "account_binding_sha256": _sha256_bytes(
                _canonical(account_binding)
            ),
            "execution_account_receipt_supported": False,
            "suspended_process_image_verified": True,
            "billable_dispatch_available": False,
            "billable_dispatch_unavailable_reason": (
                "claude_cli_has_no_authenticated_execution_bound_account_receipt"
            ),
            "active_sessions": len(self._active),
        }
        with self._lock:
            self._health_cache = (time.monotonic(), dict(result))
        return result

    def invoke(
        self,
        request: ProviderInvocationV1,
        *,
        cancel: Callable[[], bool],
    ) -> ProviderResultV1:
        with self._pinned.open() as snapshot:
            if (
                snapshot.sha256 != self.executable_sha256
                or snapshot.identity_sha256
                != self.executable_identity_sha256
                or snapshot.file_id != self.executable_file_id
            ):
                raise ExternalAgentUnavailable(
                    "Claude Code executable changed after activation"
                )
            if not self.execution_account_receipt_supported:
                raise ExternalAgentUnavailable(
                    "Claude Code cannot bind an authenticated account receipt "
                    "to this execution; billable dispatch is unavailable"
                )
            return self._invoke_pinned(
                request,
                cancel=cancel,
                approved_executable=snapshot,
            )

    def _invoke_pinned(
        self,
        request: ProviderInvocationV1,
        *,
        cancel: Callable[[], bool],
        approved_executable: _ExecutableSnapshotV1,
    ) -> ProviderResultV1:
        if not self.execution_account_receipt_supported:
            raise ExternalAgentUnavailable(
                "execution-bound account receipt is unavailable"
            )
        system = (
            "You are a patch author with no tools. You cannot inspect or modify files. "
            "Use only the repository context embedded in the approved task. Return one "
            "unified Git patch targeting only the allowed paths plus a concise summary. "
            "Do not claim tests ran. Do not emit credentials, commands for publication, "
            "commits, pushes, pull requests, deployment, or changes outside scope."
        )
        schema = json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "patch": {"type": "string", "maxLength": 2000000},
                    "summary": {"type": "string", "maxLength": 4000},
                    "tests": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string", "maxLength": 200},
                    },
                },
                "required": ["patch", "summary", "tests"],
            },
            separators=(",", ":"),
        )
        argv = [
            str(self.executable),
            "-p",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--safe-mode",
            "--disable-slash-commands",
            "--no-chrome",
            "--strict-mcp-config",
            "--mcp-config",
            "{}",
            "--tools",
            "",
            "--json-schema",
            schema,
            "--model",
            request.model,
            "--max-budget-usd",
            f"{request.max_budget_usd:.4f}",
            "--append-system-prompt",
            system,
        ]
        argv.extend(["--session-id", request.session_id])
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                subprocess.CREATE_NO_WINDOW | _CREATE_SUSPENDED
            )
        process = subprocess.Popen(
            argv,
            cwd=str(request.workspace),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=_provider_environment(),
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        job: _WindowsKillJob | None = None
        image_stack = ExitStack()
        if os.name == "nt":
            try:
                job = _WindowsKillJob(
                    process,
                    before_resume=lambda: image_stack.enter_context(
                        _verified_windows_process_image_v1(
                            process, approved_executable
                        )
                    ),
                )
            except BaseException:
                process.kill()
                process.wait(timeout=5)
                image_stack.close()
                raise
        with self._lock:
            if request.session_id in self._active:
                if job is not None:
                    job.terminate()
                    job.close()
                else:
                    process.kill()
                process.wait(timeout=5)
                image_stack.close()
                raise ExternalAgentContractError("provider session is already active")
            self._active[request.session_id] = (process, job)
        try:
            assert process.stdin is not None
            process.stdin.write(request.task.encode("utf-8", errors="strict"))
            process.stdin.close()
        except BaseException:
            if job is not None:
                job.terminate()
                job.close()
            else:
                process.kill()
            process.wait(timeout=5)
            image_stack.close()
            with self._lock:
                self._active.pop(request.session_id, None)
            raise
        stdout = _BoundedCapture(request.max_output_bytes)
        stderr = _BoundedCapture(min(request.max_output_bytes, 64 * 1024))
        threads = (
            threading.Thread(target=stdout.read, args=(process.stdout,), daemon=True),
            threading.Thread(target=stderr.read, args=(process.stderr,), daemon=True),
        )
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + request.max_seconds
        cancelled = False
        timed_out = False
        try:
            while process.poll() is None:
                if cancel():
                    cancelled = True
                    if job is not None:
                        job.terminate()
                    else:
                        process.terminate()
                    break
                if stdout.overflow or stderr.overflow:
                    if job is not None:
                        job.terminate()
                    else:
                        process.terminate()
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    if job is not None:
                        job.terminate()
                    else:
                        process.terminate()
                    break
                time.sleep(0.05)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=2)
        finally:
            with self._lock:
                self._active.pop(request.session_id, None)
            if job is not None:
                job.close()
            image_stack.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        if cancelled:
            return ProviderResultV1(
                "cancelled", request.session_id, "cancelled", 0.0, len(stdout.data)
            )
        if timed_out:
            return ProviderResultV1(
                "timeout", request.session_id, "timeout", 0.0, len(stdout.data)
            )
        if stdout.overflow or stderr.overflow:
            return ProviderResultV1(
                "output_limit",
                request.session_id,
                "output limit exceeded",
                0.0,
                len(stdout.data),
            )
        raw = bytes(stdout.data)
        try:
            document = json.loads(raw.decode("utf-8", "strict"))
        except (UnicodeError, json.JSONDecodeError):
            return ProviderResultV1(
                "failed",
                request.session_id,
                "provider returned invalid structured output",
                0.0,
                len(raw),
                _safe_text(bytes(stderr.data).decode("utf-8", "replace")),
            )
        session_id = _safe_text(document.get("session_id", request.session_id), 80)
        cost = document.get("total_cost_usd", 0.0)
        if isinstance(cost, bool) or not isinstance(cost, (int, float)):
            cost = 0.0
        structured = document.get("structured_output")
        if not isinstance(structured, Mapping):
            raw_result = document.get("result")
            if isinstance(raw_result, str):
                try:
                    structured = json.loads(raw_result)
                except json.JSONDecodeError:
                    structured = None
        if not isinstance(structured, Mapping):
            structured = {}
        patch = structured.get("patch", "")
        tests = structured.get("tests", [])
        if not isinstance(patch, str):
            patch = ""
        if not isinstance(tests, list) or any(
            not isinstance(item, str) for item in tests
        ):
            tests = []
        return ProviderResultV1(
            "succeeded" if process.returncode == 0 else "failed",
            session_id,
            _safe_text(structured.get("summary", ""), 4000),
            float(cost),
            len(raw),
            _safe_text(bytes(stderr.data).decode("utf-8", "replace")),
            patch[:2_000_000],
            tuple(_safe_text(item, 200) for item in tests[:20]),
        )

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            active = self._active.get(session_id)
        if active is None:
            return False
        process, job = active
        if process.poll() is not None:
            return False
        if job is not None:
            job.terminate()
        else:
            process.terminate()
        return True


class DeterministicExternalAgentProviderV1:
    """Non-networked test double; never selected by live discovery."""

    provider_id = PROVIDER_ID
    version = "deterministic-test-double-v1"
    executable_sha256 = "0" * 64
    executable_identity_sha256 = "0" * 64
    executable_file_id = "0:0"
    executable_path = str(Path(__file__).resolve())
    execution_account_receipt_supported = True

    def __init__(self, *, mutation: tuple[str, str] | None = None) -> None:
        self.mutation = mutation
        self.calls: list[ProviderInvocationV1] = []
        self.cancelled: set[str] = set()

    def health(self, *, force: bool = False) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "version": self.version,
            "available": True,
            "auth_method": "test-double",
            "executable_path": self.executable_path,
            "binary_sha256": self.executable_sha256,
            "executable_identity_sha256": self.executable_identity_sha256,
            "executable_file_id": self.executable_file_id,
            "account_binding_sha256": "0" * 64,
            "execution_account_receipt_supported": True,
            "suspended_process_image_verified": True,
            "billable_dispatch_available": True,
            "active_sessions": 0,
        }

    def invoke(
        self,
        request: ProviderInvocationV1,
        *,
        cancel: Callable[[], bool],
    ) -> ProviderResultV1:
        self.calls.append(request)
        if cancel() or request.session_id in self.cancelled:
            return ProviderResultV1(
                "cancelled", request.session_id, "cancelled", 0.0, 0
            )
        if self.mutation is not None:
            relative, content = self.mutation
            target = relative.replace("\\", "/")
            before = _encode_git_quoted_path(f"a/{target}")
            after = _encode_git_quoted_path(f"b/{target}")
            patch = (
                f"diff --git {before} {after}\n"
                f"new file mode 100644\n"
                f"--- /dev/null\n"
                f"+++ {after}\n"
                f"@@ -0,0 +1 @@\n"
                f"+{content.rstrip()}\n"
            )
        else:
            patch = ""
        return ProviderResultV1(
            "succeeded",
            request.session_id,
            "deterministic result",
            0.0,
            20,
            patch=patch,
            account_receipt_sha256="0" * 64,
        )

    def cancel(self, session_id: str) -> bool:
        self.cancelled.add(session_id)
        return True


class ExternalCodingAgentAdapterV1:
    """Durable single-attempt adapter driven by authenticated mission authority."""

    def __init__(
        self,
        *,
        state_root: str | os.PathLike[str],
        signing_key: bytes,
        provider: ProviderV1,
        git_cli: str | os.PathLike[str],
        model: str,
        max_budget_usd: float,
        max_seconds: int,
        max_output_bytes: int,
        rate_limit_calls: int = 4,
        rate_window_seconds: int = 60,
        enabled: bool = False,
        terminal_state_resolver: Callable[[str], str] | None = None,
    ) -> None:
        if enabled is not True:
            raise ExternalAgentUnavailable("external coding agent is disabled")
        if not isinstance(signing_key, bytes) or len(signing_key) < 16:
            raise ExternalAgentContractError("adapter signing key is invalid")
        self.state_root = Path(os.path.abspath(os.fspath(state_root)))
        self._state = _TrustedStateV1(self.state_root)
        for directory in (
            "artifacts",
            "checkpoints",
            "clones",
            "git-home",
            "quarantine",
            "reservations",
            "tasks",
        ):
            self._state.list_files(directory)
        for lock_name in (
            "checkpoint.lock",
            "cleanup.lock",
            "reservation.lock",
        ):
            if self._state.read_optional(lock_name, 1) is None:
                self._state.publish(lock_name, b"")
        self._recover_orphan_clones()
        self._key = bytes(signing_key)
        self.provider = provider
        self._git = _HermeticGitV1(git_cli, self.state_root)
        self.git_cli = self._git.executable
        self._terminal_state = terminal_state_resolver or (lambda _mission_id: "")
        if (
            _MODEL_ID.fullmatch(str(model).lower()) is None
            or isinstance(max_budget_usd, bool)
            or not isinstance(max_budget_usd, (int, float))
            or not math.isfinite(max_budget_usd)
            or not 0 < float(max_budget_usd) <= 25
            or isinstance(max_seconds, bool)
            or not isinstance(max_seconds, int)
            or not 30 <= max_seconds <= 3600
            or isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or not 4096 <= max_output_bytes <= 2 * 1024 * 1024
            or isinstance(rate_limit_calls, bool)
            or not isinstance(rate_limit_calls, int)
            or not 1 <= rate_limit_calls <= 60
            or isinstance(rate_window_seconds, bool)
            or not isinstance(rate_window_seconds, int)
            or not 10 <= rate_window_seconds <= 3600
        ):
            raise ExternalAgentContractError(
                "external-agent host budget is invalid"
            )
        self.model = str(model).lower()
        self.max_budget_usd = float(max_budget_usd)
        self.max_seconds = max_seconds
        self.max_output_bytes = max_output_bytes
        self.rate_limit_calls = rate_limit_calls
        self.rate_window_seconds = rate_window_seconds
        self._lock = threading.RLock()
        self._active: dict[str, str] = {}

    def _recover_orphan_clones(self) -> None:
        for name in self._state.list_directories("clones", "building-"):
            if self._quarantine_count() >= _TERMINAL_CLONE_RETENTION:
                raise ExternalAgentWaiting(
                    "external-agent quarantine retention is full"
                )
            source = self.state_root / "clones" / name
            orphan_name = f"orphan-{time.time_ns()}-{uuid.uuid4().hex}"
            if os.name == "nt":
                boundary = WindowsTrustedDirectoryV1(
                    root=source,
                    enabled=True,
                    allow_root_quarantine=True,
                )
                try:
                    boundary.quarantine_root(orphan_name)
                finally:
                    boundary.close()
            else:
                destination = self.state_root / "quarantine" / orphan_name
                os.replace(source, destination)
                directory = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)

    def _quarantine_rows(self) -> tuple[tuple[str, str], ...]:
        rows = [
            ("clones", name)
            for name in self._state.list_directories(
                "clones", "terminal-"
            )
        ]
        rows.extend(
            ("clones", name)
            for name in self._state.list_directories(
                "clones", "orphan-"
            )
        )
        rows.extend(
            ("quarantine", name)
            for name in self._state.list_directories(
                "quarantine", "orphan-"
            )
        )
        return tuple(sorted(rows, key=lambda row: (row[1], row[0])))

    def _quarantine_count(self) -> int:
        return len(self._quarantine_rows())

    def cleanup_quarantine(
        self,
        *,
        owner_confirmed: bool,
        retain: int = 0,
    ) -> dict[str, int]:
        if owner_confirmed is not True:
            raise ExternalAgentContractError(
                "external-agent quarantine cleanup requires owner confirmation"
            )
        if type(retain) is not int or not 0 <= retain <= 7:
            raise ExternalAgentContractError(
                "external-agent quarantine retention target is invalid"
            )
        if os.name != "nt":
            raise ExternalAgentUnavailable(
                "handle-safe external-agent cleanup is Windows-only in V1"
            )
        removed = 0
        removed_entries = 0
        removed_bytes = 0
        with self._state.lock("cleanup.lock"):
            rows = self._quarantine_rows()
            for relative, name in rows[: max(0, len(rows) - retain)]:
                boundary = WindowsTrustedDirectoryV1(
                    root=self.state_root / relative / name,
                    enabled=True,
                    allow_root_quarantine=True,
                )
                try:
                    entries, total_bytes = boundary.remove_root_tree()
                finally:
                    boundary.close()
                removed += 1
                removed_entries += entries
                removed_bytes += total_bytes
        return {
            "removed": removed,
            "removed_entries": removed_entries,
            "removed_bytes": removed_bytes,
            "retained": self._quarantine_count(),
            "retention_cap": _TERMINAL_CLONE_RETENTION,
        }

    def _quarantine_terminal_clone(
        self,
        clone: Path,
        envelope: ExternalAgentEnvelopeV1,
        outcome: str,
    ) -> Path:
        safe_outcome = re.sub(r"[^a-z0-9_-]", "_", outcome.lower())[:32]
        terminal_name = (
            f"terminal-{time.time_ns()}-{safe_outcome}-"
            f"{envelope.mission_id}-{envelope.nonce[:12]}"
        )
        if os.name == "nt":
            boundary = WindowsTrustedDirectoryV1(
                root=clone,
                enabled=True,
                allow_root_quarantine=True,
            )
            try:
                return boundary.quarantine_root(terminal_name)
            finally:
                boundary.close()
        if not clone.exists():
            return clone
        destination = clone.parent / terminal_name
        os.replace(clone, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return destination

    def health(self) -> dict[str, object]:
        status = self._provider_health(force=False)
        status["git_available"] = self.git_cli.is_file()
        status["git_executable_path"] = str(self._git.executable)
        status["git_executable_sha256"] = self._git.executable_sha256
        status["git_executable_identity_sha256"] = (
            self._git.executable_identity_sha256
        )
        status["git_executable_file_id"] = self._git.executable_file_id
        status["clone_only"] = True
        status["push_capable"] = False
        status["pr_creation_capable"] = False
        status["model"] = self.model
        status["max_budget_usd"] = self.max_budget_usd
        status["max_seconds"] = self.max_seconds
        status["max_output_bytes"] = self.max_output_bytes
        status["rate_limit_calls"] = self.rate_limit_calls
        status["rate_window_seconds"] = self.rate_window_seconds
        status["quarantine_count"] = self._quarantine_count()
        status["quarantine_retention_cap"] = _TERMINAL_CLONE_RETENTION
        return status

    def _provider_health(self, *, force: bool) -> dict[str, object]:
        method = self.provider.health
        try:
            return dict(method(force=force))  # type: ignore[call-arg]
        except TypeError:
            return dict(method())

    @staticmethod
    def _provider_matches(
        health: Mapping[str, object],
        envelope: ExternalAgentEnvelopeV1,
    ) -> bool:
        return (
            health.get("available") is True
            and health.get("provider_id") == envelope.provider_id
            and health.get("binary_sha256")
            == envelope.provider_executable_sha256
            and os.path.normcase(str(health.get("executable_path", "")))
            == os.path.normcase(envelope.provider_executable_path)
            and health.get("executable_identity_sha256")
            == envelope.provider_executable_identity_sha256
            and health.get("executable_file_id")
            == envelope.provider_executable_file_id
            and health.get("account_binding_sha256")
            == envelope.provider_account_sha256
            and health.get("version") == envelope.provider_version
            and health.get("execution_account_receipt_supported") is True
            and health.get("suspended_process_image_verified") is True
            and health.get("billable_dispatch_available") is True
        )

    def _checkpoint_path(self, mission_id: str) -> Path:
        return self.state_root / "checkpoints" / f"{mission_id}.json"

    def _clone_path(self, mission_id: str, nonce: str) -> Path:
        return self.state_root / "clones" / f"{mission_id}-{nonce[:12]}"

    def protect_task(
        self, mission_id: str, task: str, task_sha256: str
    ) -> dict[str, object]:
        if _MISSION_ID.fullmatch(mission_id) is None:
            raise ExternalAgentContractError("external-agent mission id is invalid")
        plaintext = task.encode("utf-8", errors="strict")
        if (
            not plaintext
            or len(plaintext) > 100_000
            or not hmac.compare_digest(_sha256_bytes(plaintext), task_sha256)
        ):
            raise ExternalAgentContractError("external-agent task artifact is invalid")
        nonce = os.urandom(12)
        associated = f"{mission_id}:{task_sha256}".encode("ascii")
        artifact_key = hmac.new(
            self._key, _ARTIFACT_DOMAIN + b"TASK-KEY", hashlib.sha256
        ).digest()
        ciphertext = nonce + AESGCM(artifact_key).encrypt(
            nonce, plaintext, associated
        )
        relative = f"tasks/{mission_id}.task.aesgcm"
        self._state.publish(relative, ciphertext)
        return {
            "schema": "onyx.external_agent.task_artifact.v1",
            "name": relative,
            "ciphertext_sha256": _sha256_bytes(ciphertext),
            "ciphertext_bytes": len(ciphertext),
            "plaintext_bytes": len(plaintext),
            "task_sha256": task_sha256,
        }

    def read_task(
        self,
        envelope: ExternalAgentEnvelopeV1,
        reference: Mapping[str, object],
    ) -> str:
        envelope.authenticate(self._key, require_live=False)
        expected = f"tasks/{envelope.mission_id}.task.aesgcm"
        if (
            reference.get("schema") != "onyx.external_agent.task_artifact.v1"
            or reference.get("name") != expected
            or reference.get("task_sha256") != envelope.task_sha256
            or reference.get("plaintext_bytes") != envelope.task_bytes
            or not isinstance(reference.get("ciphertext_bytes"), int)
            or not 28 < int(reference["ciphertext_bytes"]) <= 100_028
        ):
            raise ExternalAgentContractError(
                "external-agent task reference is invalid"
            )
        ciphertext = self._state.read_optional(expected, 100_028)
        if ciphertext is None:
            raise ExternalAgentContractError(
                "external-agent task artifact is unavailable"
            )
        if (
            len(ciphertext) != reference["ciphertext_bytes"]
            or _sha256_bytes(ciphertext) != reference.get("ciphertext_sha256")
        ):
            raise ExternalAgentContractError(
                "external-agent task artifact authentication failed"
            )
        associated = (
            f"{envelope.mission_id}:{envelope.task_sha256}".encode("ascii")
        )
        artifact_key = hmac.new(
            self._key, _ARTIFACT_DOMAIN + b"TASK-KEY", hashlib.sha256
        ).digest()
        try:
            plaintext = AESGCM(artifact_key).decrypt(
                ciphertext[:12], ciphertext[12:], associated
            )
            task = plaintext.decode("utf-8", errors="strict")
        except (InvalidTag, ValueError, UnicodeError) as exc:
            raise ExternalAgentContractError(
                "external-agent task decryption failed"
            ) from exc
        if (
            len(plaintext) != envelope.task_bytes
            or _sha256_bytes(plaintext) != envelope.task_sha256
        ):
            raise ExternalAgentContractError(
                "external-agent task plaintext drift"
            )
        return task

    def _write_checkpoint(self, mission_id: str, payload: Mapping[str, object]) -> None:
        with self._state.lock("checkpoint.lock"):
            prior = self._read_checkpoint(mission_id)
            sequence = 1 if prior is None else int(prior.get("sequence", 0)) + 1
            unsigned = {
                **dict(payload),
                "schema": "onyx.external_agent.checkpoint.v1",
                "sequence": sequence,
            }
            signature = hmac.new(
                self._key,
                _CHECKPOINT_DOMAIN + _canonical(unsigned),
                hashlib.sha256,
            ).hexdigest()
            self._state.publish(
                f"checkpoints/{mission_id}.{sequence:08d}.json",
                _canonical({**unsigned, "signature": signature}),
            )

    def _read_checkpoint(self, mission_id: str) -> dict[str, object] | None:
        names = self._state.list_files("checkpoints", f"{mission_id}.")
        if not names:
            return None
        name = names[-1]
        try:
            raw = self._state.read_optional(f"checkpoints/{name}", 256 * 1024)
            if raw is None:
                raise OSError("checkpoint disappeared")
            document = json.loads(raw.decode("utf-8", "strict"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ExternalAgentWaiting("external-agent checkpoint is unavailable") from exc
        if not isinstance(document, dict):
            raise ExternalAgentWaiting("external-agent checkpoint is invalid")
        signature = document.pop("signature", None)
        expected = hmac.new(
            self._key,
            _CHECKPOINT_DOMAIN + _canonical(document),
            hashlib.sha256,
        ).hexdigest()
        if (
            document.get("schema") != "onyx.external_agent.checkpoint.v1"
            or document.get("mission_id") != mission_id
            or not isinstance(signature, str)
            or not hmac.compare_digest(signature, expected)
        ):
            raise ExternalAgentWaiting("external-agent checkpoint authentication failed")
        document["signature"] = signature
        return document

    def status(self, mission_id: str) -> dict[str, object]:
        checkpoint = self._read_checkpoint(mission_id)
        if checkpoint is None:
            return {
                "mission_id": mission_id,
                "attempt_state": "not_started",
                "dispatch_permitted": True,
            }
        return {
            "mission_id": mission_id,
            "attempt_state": str(checkpoint.get("attempt_state", "attempted_unknown")),
            "stage": str(checkpoint.get("stage", "unknown")),
            "session_id_prefix": str(checkpoint.get("session_id", ""))[:12],
            "receipt_sha256_prefix": str(
                checkpoint.get("receipt_sha256", "")
            )[:12],
            "cost_usd": float(checkpoint.get("cost_usd", 0.0)),
            "changed_path_count": int(
                checkpoint.get("changed_path_count", 0)
            ),
            "dispatch_permitted": False,
            "draft_pr_creation_authorized": False,
        }

    def artifact_sha256(self, mission_id: str) -> str:
        checkpoint = self._read_checkpoint(mission_id)
        if (
            checkpoint is None
            or checkpoint.get("attempt_state") != "succeeded"
            or _HEX64.fullmatch(str(checkpoint.get("artifact_sha256", ""))) is None
        ):
            raise ExternalAgentWaiting(
                "prior external-agent artifact is unavailable"
            )
        return str(checkpoint["artifact_sha256"])

    def _reserve_dispatch(self, envelope: ExternalAgentEnvelopeV1) -> None:
        threshold = time.time_ns() - self.rate_window_seconds * 1_000_000_000
        with self._state.lock("reservation.lock"):
            existing = self._state.read_optional(
                f"reservations/{envelope.mission_id}.json", 32 * 1024
            )
            if existing is not None:
                raise ExternalAgentWaiting(
                    "external-agent attempt already reserved; automatic retry is forbidden"
                )
            observed = 0
            reserved_cost = 0.0
            for name in self._state.list_files("reservations", "mis_"):
                raw = self._state.read_optional(f"reservations/{name}", 32 * 1024)
                if raw is None:
                    raise ExternalAgentWaiting(
                        "external-agent reservation ledger is unavailable"
                    )
                try:
                    document = json.loads(raw.decode("utf-8", "strict"))
                    signature = document.pop("signature")
                except (UnicodeError, json.JSONDecodeError, KeyError):
                    raise ExternalAgentWaiting(
                        "external-agent reservation ledger is invalid"
                    ) from None
                expected = hmac.new(
                    self._key,
                    _RESERVATION_DOMAIN + _canonical(document),
                    hashlib.sha256,
                ).hexdigest()
                if not isinstance(signature, str) or not hmac.compare_digest(
                    signature, expected
                ):
                    raise ExternalAgentWaiting(
                        "external-agent reservation authentication failed"
                    )
                if int(document.get("reserved_at_ns", 0)) >= threshold:
                    observed += 1
                    reserved_cost += float(document.get("max_budget_usd", 0.0))
            if (
                observed >= self.rate_limit_calls
                or reserved_cost + envelope.max_budget_usd
                > self.rate_limit_calls * self.max_budget_usd
            ):
                raise ExternalAgentWaiting(
                    "external-agent rate budget is exhausted"
                )
            reservation = {
                "schema": "onyx.external_agent.reservation.v1",
                "mission_id": envelope.mission_id,
                "approval_digest": envelope.approval_digest,
                "max_budget_usd": envelope.max_budget_usd,
                "reserved_at_ns": time.time_ns(),
            }
            signature = hmac.new(
                self._key,
                _RESERVATION_DOMAIN + _canonical(reservation),
                hashlib.sha256,
            ).hexdigest()
            self._state.publish(
                f"reservations/{envelope.mission_id}.json",
                _canonical({**reservation, "signature": signature}),
            )

    def _owner_state(self, root: Path) -> tuple[str, str]:
        head = self._git.run(root, ["rev-parse", "--verify", "HEAD^{commit}"])
        status = self._git.run(
            root, ["status", "--porcelain=v1", "--untracked-files=all"]
        )
        if head.returncode != 0 or status.returncode != 0:
            raise ExternalAgentContractError("owner repository inspection failed")
        commit = head.stdout.decode("ascii", "strict").strip().lower()
        digest = _sha256_bytes(commit.encode("ascii") + b"\0" + status.stdout)
        return commit, digest

    def capture_owner_state(
        self, workspace_root: str | os.PathLike[str]
    ) -> tuple[str, str]:
        return self._owner_state(Path(workspace_root).resolve())

    def _blob_manifest(
        self,
        root: Path,
        commit: str,
        allowed_roots: Sequence[str],
    ) -> tuple[tuple[dict[str, str], ...], str]:
        roots = tuple(sorted({_relative_root(item) for item in allowed_roots}))
        listed = self._git.run(
            root,
            ["ls-tree", "-r", "-z", "--full-tree", commit, "--", *roots],
            timeout=60,
        )
        if listed.returncode != 0:
            raise ExternalAgentContractError(
                "approved commit tree enumeration failed"
            )
        rows: list[dict[str, str]] = []
        for raw in listed.stdout.split(b"\0"):
            if not raw:
                continue
            try:
                metadata, raw_path = raw.split(b"\t", 1)
                mode, kind, object_id = metadata.decode("ascii").split(" ", 2)
                path = raw_path.decode("utf-8", "strict").replace("\\", "/")
            except (ValueError, UnicodeError) as exc:
                raise ExternalAgentContractError(
                    "approved commit tree manifest is invalid"
                ) from exc
            if (
                kind != "blob"
                or mode not in {"100644", "100755"}
                or not _under_allowed(path, roots)
                or path.startswith(".git/")
            ):
                raise ExternalAgentContractError(
                    "approved commit contains an unsupported entry"
                )
            rows.append({"path": path, "mode": mode, "blob": object_id.lower()})
        rows.sort(key=lambda item: item["path"])
        if len(rows) > 20_000:
            raise ExternalAgentContractError(
                "approved commit blob manifest is too large"
            )
        canonical = _canonical(rows)
        return tuple(rows), _sha256_bytes(canonical)

    def build_commit_packet(
        self,
        *,
        workspace_root: str | os.PathLike[str],
        repository_commit: str,
        objective: object,
        allowed_roots: Sequence[str],
    ) -> tuple[str, tuple[str, ...], str, int]:
        safe_objective = str(objective).strip()
        if (
            not safe_objective
            or len(safe_objective.encode("utf-8")) > 12_000
            or contains_secret(safe_objective)
        ):
            raise ExternalAgentContractError(
                "external-agent objective is invalid"
            )
        roots = tuple(sorted({_relative_root(item) for item in allowed_roots}))
        root = Path(workspace_root).resolve()
        rows, manifest_sha256 = self._blob_manifest(
            root, repository_commit, roots
        )
        context: list[str] = []
        context_bytes = 0
        for row in rows:
            path = row["path"]
            if (
                PurePosixPath(path).suffix.lower() not in _CONTEXT_SUFFIXES
                or _SECRET_NAME.search(path)
            ):
                continue
            blob = self._git.run(
                root,
                ["cat-file", "blob", row["blob"]],
                timeout=30,
            )
            if blob.returncode != 0 or len(blob.stdout) > 64_000:
                continue
            try:
                text = blob.stdout.decode("utf-8", "strict")
            except UnicodeError:
                continue
            if contains_secret(text):
                continue
            block = (
                f"\n--- BEGIN COMMIT BLOB {row['blob']} {path} ---\n"
                f"{text}\n--- END COMMIT BLOB {row['blob']} {path} ---\n"
            )
            size = len(block.encode("utf-8"))
            if context_bytes + size > 76_000:
                break
            context.append(block)
            context_bytes += size
        packet = (
            "ONYX EXTERNAL CODING MISSION V1\n"
            f"Repository commit: {repository_commit}\n"
            f"Blob manifest SHA-256: {manifest_sha256}\n"
            f"Allowed roots: {', '.join(roots)}\n"
            "Output contract: return only a unified Git patch, concise summary, "
            "and tests you recommend; do not claim tests ran.\n"
            f"Objective:\n{safe_objective}\n"
            "Authorized source context follows. Every file block came from an "
            "exact blob in the approved commit tree; the live worktree was not read.\n"
            + "".join(context)
        )
        if len(packet.encode("utf-8")) > 100_000:
            raise ExternalAgentContractError(
                "external-agent mission packet is too large"
            )
        return packet, roots, manifest_sha256, len(rows)

    def _materialize_clone(
        self, envelope: ExternalAgentEnvelopeV1
    ) -> Path:
        root = Path(envelope.workspace_root)
        rows, manifest_sha256 = self._blob_manifest(
            root,
            envelope.repository_commit,
            envelope.allowed_roots,
        )
        if (
            manifest_sha256 != envelope.repository_blob_manifest_sha256
            or len(rows) != envelope.repository_blob_count
        ):
            raise ExternalAgentWaiting(
                "approved commit blob manifest drifted"
            )
        if self._quarantine_count() >= _TERMINAL_CLONE_RETENTION:
            raise ExternalAgentWaiting(
                "external-agent quarantine retention is full; "
                "owner cleanup is required"
            )
        final_name = f"{envelope.mission_id}-{envelope.nonce[:12]}"
        building_name = f"building-{final_name}"
        clone = self.state_root / "clones" / final_name
        building = self.state_root / "clones" / building_name
        if final_name in self._state.list_directories("clones"):
            raise ExternalAgentWaiting("external-agent clone already exists")
        if building_name in self._state.list_directories("clones"):
            raise ExternalAgentWaiting(
                "external-agent orphan clone requires quarantine"
            )
        if self._state.boundary is not None:
            with self._state.boundary.session() as session:
                with session.parent(
                    f"clones/{building_name}/probe",
                    create_directories=True,
                ):
                    pass
            clone_boundary = WindowsTrustedDirectoryV1(
                root=building,
                enabled=True,
                allow_root_quarantine=True,
            )
            try:
                with clone_boundary.session() as session:
                    total = 0
                    for row in rows:
                        blob = self._git.run(
                            root,
                            ["cat-file", "blob", row["blob"]],
                            timeout=30,
                        )
                        if blob.returncode != 0:
                            raise ExternalAgentContractError(
                                "approved commit blob materialization failed"
                            )
                        total += len(blob.stdout)
                        if total > 64 * 1024 * 1024:
                            raise ExternalAgentContractError(
                                "approved commit materialization is too large"
                            )
                        session.publish_create(row["path"], blob.stdout)
                clone_boundary.quarantine_root(final_name)
            finally:
                clone_boundary.close()
        else:
            building.mkdir(parents=True, exist_ok=False, mode=0o700)
            total = 0
            for row in rows:
                blob = self._git.run(
                    root, ["cat-file", "blob", row["blob"]], timeout=30
                )
                if blob.returncode != 0:
                    raise ExternalAgentContractError(
                        "approved commit blob materialization failed"
                    )
                total += len(blob.stdout)
                if total > 64 * 1024 * 1024:
                    raise ExternalAgentContractError(
                        "approved commit materialization is too large"
                    )
                target = building / row["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob.stdout)
            os.replace(building, clone)
            directory = os.open(clone.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return clone

    def _artifact(
        self,
        envelope: ExternalAgentEnvelopeV1,
        patch: bytes,
    ) -> dict[str, object]:
        artifact_key = hmac.new(
            self._key, _ARTIFACT_DOMAIN + b"KEY", hashlib.sha256
        ).digest()
        nonce = os.urandom(12)
        associated = _canonical(
            {
                "mission_id": envelope.mission_id,
                "approval_digest": envelope.approval_digest,
                "task_sha256": envelope.task_sha256,
            }
        )
        ciphertext = AESGCM(artifact_key).encrypt(nonce, patch, associated)
        name = f"{envelope.mission_id}.draft-pr.patch.aesgcm"
        content = nonce + ciphertext
        self._state.publish(f"artifacts/{name}", content)
        return {
            "kind": "draft_pr_handoff",
            "path_ref": f"artifacts/{name}",
            "plaintext_sha256": _sha256_bytes(patch),
            "plaintext_bytes": len(patch),
            "ciphertext_sha256": _sha256_bytes(content),
            "encrypted": True,
            "external_pr_created": False,
        }

    def _canonical_patch_paths(
        self,
        clone: Path,
        patch: bytes,
    ) -> list[str]:
        if any(
            line.startswith(("rename from ", "rename to ", "copy from ", "copy to "))
            for line in patch.decode("utf-8", "strict").splitlines()
        ):
            raise ExternalAgentContractError(
                "external-agent V1 does not accept rename/copy patches"
            )
        result = self._git.run(
            clone,
            ["apply", "--numstat", "-"],
            payload=patch,
            timeout=60,
        )
        if result.returncode != 0:
            raise ExternalAgentContractError(
                "provider patch failed canonical Git parsing"
            )
        paths: list[str] = []
        try:
            output = result.stdout.decode("ascii", "strict")
        except UnicodeError as exc:
            raise ExternalAgentContractError(
                "canonical Git patch path output is invalid"
            ) from exc
        for line in output.splitlines():
            fields = line.split("\t", 2)
            if len(fields) != 3 or not fields[0] or not fields[1]:
                raise ExternalAgentContractError(
                    "canonical Git patch path output is invalid"
                )
            path = _decode_git_quoted_path(fields[2])
            if not path:
                raise ExternalAgentContractError(
                    "canonical Git patch path is empty"
                )
            paths.append(path.replace("\\", "/"))
        if patch.strip() and not paths:
            raise ExternalAgentContractError(
                "canonical Git parser returned no path for a non-empty patch"
            )
        return sorted(set(paths))

    def execute(
        self,
        *,
        envelope: ExternalAgentEnvelopeV1,
        task: str,
        cancel: Callable[[], bool],
    ) -> dict[str, object]:
        envelope.authenticate(self._key)
        task_bytes = task.encode("utf-8")
        if (
            len(task_bytes) != envelope.task_bytes
            or not hmac.compare_digest(_sha256_bytes(task_bytes), envelope.task_sha256)
        ):
            raise ExternalAgentContractError("external-agent task authentication failed")
        self._git.verify(
            path=envelope.git_executable_path,
            sha256=envelope.git_executable_sha256,
            identity_sha256=envelope.git_executable_identity_sha256,
            file_id=envelope.git_executable_file_id,
        )
        root = Path(envelope.workspace_root)
        before_commit, before_digest = self._owner_state(root)
        if (
            before_commit != envelope.repository_commit
            or before_digest != envelope.owner_git_sha256
        ):
            raise ExternalAgentWaiting("owner repository drifted before provider dispatch")
        existing = self._read_checkpoint(envelope.mission_id)
        if existing is not None:
            raise ExternalAgentWaiting(
                "external-agent attempt already exists; automatic retry is forbidden"
            )
        if cancel():
            raise ExternalAgentWaiting("kill requested before provider dispatch")
        self._reserve_dispatch(envelope)
        clone = self._materialize_clone(envelope)
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, envelope.signature))
        pre_intent_health = self._provider_health(force=True)
        if not self._provider_matches(pre_intent_health, envelope):
            self._quarantine_terminal_clone(
                clone, envelope, "provider_identity_pre_intent"
            )
            raise ExternalAgentUnavailable(
                "external-agent provider identity diverged before intent"
            )
        intent = {
            "mission_id": envelope.mission_id,
            "binding_approval_digest": envelope.approval_digest,
            "task_sha256": envelope.task_sha256,
            "repository_commit": envelope.repository_commit,
            "repository_blob_manifest_sha256": (
                envelope.repository_blob_manifest_sha256
            ),
            "git_executable_sha256": envelope.git_executable_sha256,
            "git_executable_identity_sha256": (
                envelope.git_executable_identity_sha256
            ),
            "git_executable_file_id": envelope.git_executable_file_id,
            "provider_id": envelope.provider_id,
            "provider_version": envelope.provider_version,
            "provider_executable_path": envelope.provider_executable_path,
            "provider_executable_sha256": envelope.provider_executable_sha256,
            "provider_executable_identity_sha256": (
                envelope.provider_executable_identity_sha256
            ),
            "provider_executable_file_id": (
                envelope.provider_executable_file_id
            ),
            "provider_account_sha256": envelope.provider_account_sha256,
            "model": envelope.model,
            "max_budget_usd": envelope.max_budget_usd,
            "max_seconds": envelope.max_seconds,
            "max_output_bytes": envelope.max_output_bytes,
            "session_id": session_id,
            "prior_artifact_sha256": envelope.prior_artifact_sha256,
            "stage": "intent_persisted",
            "attempt_state": "attempted_unknown",
            "issued_at_ns": time.time_ns(),
        }
        self._write_checkpoint(envelope.mission_id, intent)
        if cancel():
            self._write_checkpoint(
                envelope.mission_id,
                {**intent, "stage": "cancelled_before_provider", "attempt_state": "cancelled"},
            )
            self._quarantine_terminal_clone(
                clone, envelope, "cancelled_before_provider"
            )
            raise ExternalAgentWaiting("kill requested after durable intent")
        pre_spawn_health = self._provider_health(force=True)
        if not self._provider_matches(pre_spawn_health, envelope):
            self._write_checkpoint(
                envelope.mission_id,
                {
                    **intent,
                    "stage": "provider_identity_drift_pre_spawn",
                    "attempt_state": "attempted_unknown",
                },
            )
            self._quarantine_terminal_clone(
                clone, envelope, "provider_identity_pre_spawn"
            )
            raise ExternalAgentWaiting(
                "external-agent provider identity drifted after intent"
            )
        with self._lock:
            if envelope.mission_id in self._active:
                raise ExternalAgentWaiting("external-agent mission is already active")
            self._active[envelope.mission_id] = session_id
        try:
            try:
                result = self.provider.invoke(
                    ProviderInvocationV1(
                        session_id=session_id,
                        workspace=clone,
                        task=task,
                        model=envelope.model,
                        max_budget_usd=envelope.max_budget_usd,
                        max_seconds=envelope.max_seconds,
                        max_output_bytes=envelope.max_output_bytes,
                    ),
                    cancel=cancel,
                )
            except BaseException:
                self._quarantine_terminal_clone(
                    clone, envelope, "provider_exception"
                )
                raise
        finally:
            with self._lock:
                self._active.pop(envelope.mission_id, None)
        if not hmac.compare_digest(
            result.account_receipt_sha256,
            envelope.provider_account_sha256,
        ):
            self._write_checkpoint(
                envelope.mission_id,
                {
                    **intent,
                    "stage": "execution_account_receipt_missing",
                    "attempt_state": "attempted_unknown",
                },
            )
            self._quarantine_terminal_clone(
                clone, envelope, "account_receipt_missing"
            )
            raise ExternalAgentWaiting(
                "provider result lacks the authenticated execution account receipt"
            )
        post_health = self._provider_health(force=True)
        try:
            self._git.verify(
                path=envelope.git_executable_path,
                sha256=envelope.git_executable_sha256,
                identity_sha256=envelope.git_executable_identity_sha256,
                file_id=envelope.git_executable_file_id,
            )
        except ExternalAgentUnavailable:
            self._write_checkpoint(
                envelope.mission_id,
                {
                    **intent,
                    "stage": "git_identity_drift_post_result",
                    "attempt_state": "attempted_unknown",
                },
            )
            self._quarantine_terminal_clone(
                clone, envelope, "git_identity_drift"
            )
            raise ExternalAgentWaiting(
                "pinned Git identity drifted after provider attempt"
            ) from None
        if not self._provider_matches(post_health, envelope):
            self._write_checkpoint(
                envelope.mission_id,
                {
                    **intent,
                    "stage": "provider_identity_drift_post_result",
                    "attempt_state": "attempted_unknown",
                },
            )
            self._quarantine_terminal_clone(
                clone, envelope, "provider_identity_drift"
            )
            raise ExternalAgentWaiting(
                "external-agent provider identity drifted after provider attempt"
            )
        if result.cost_usd > envelope.max_budget_usd:
            result = ProviderResultV1(
                "failed",
                result.session_id,
                "provider reported budget overflow",
                result.cost_usd,
                result.output_bytes,
            )
        patch_bytes = result.patch.encode("utf-8", errors="strict")
        if len(patch_bytes) > envelope.max_output_bytes:
            result = ProviderResultV1(
                "output_limit",
                result.session_id,
                "provider patch exceeded output limit",
                result.cost_usd,
                result.output_bytes,
            )
            patch_bytes = b""
        patch_paths: list[str] = []
        if result.status == "succeeded" and patch_bytes.strip():
            try:
                patch_paths = self._canonical_patch_paths(clone, patch_bytes)
            except (ExternalAgentContractError, UnicodeError):
                result = ProviderResultV1(
                    "failed",
                    result.session_id,
                    "provider patch failed canonical Git path parsing",
                    result.cost_usd,
                    result.output_bytes,
                    account_receipt_sha256=result.account_receipt_sha256,
                )
                patch_bytes = b""
        if any(
            not _under_allowed(path, envelope.allowed_roots)
            for path in patch_paths
        ):
            result = ProviderResultV1(
                "failed",
                result.session_id,
                "provider patch targeted a path outside the approved roots",
                result.cost_usd,
                result.output_bytes,
            )
            patch_bytes = b""
        if result.status == "succeeded" and patch_bytes.strip() and not patch_paths:
            canonical_empty = self._git.run(
                clone,
                ["apply", "--check", "--whitespace=error-all", "-"],
                payload=patch_bytes,
                timeout=60,
            )
            if canonical_empty.returncode == 0:
                patch_bytes = b""
            else:
                result = ProviderResultV1(
                    "failed",
                    result.session_id,
                    "provider returned a non-canonical empty patch",
                    result.cost_usd,
                    result.output_bytes,
                    account_receipt_sha256=result.account_receipt_sha256,
                )
        if result.status == "succeeded" and not patch_bytes.strip():
            after_commit, after_digest = self._owner_state(root)
            if after_commit != before_commit or after_digest != before_digest:
                self._write_checkpoint(
                    envelope.mission_id,
                    {
                        **intent,
                        "stage": "owner_repository_drift",
                        "attempt_state": "attempted_unknown",
                    },
                )
                self._quarantine_terminal_clone(
                    clone, envelope, "owner_repository_drift"
                )
                raise ExternalAgentWaiting(
                    "owner repository changed during provider attempt"
                )
            no_change_receipt = {
                "schema": "onyx.external_agent.receipt.v1",
                "mission_id": envelope.mission_id,
                "status": "no_change",
                "task_sha256": envelope.task_sha256,
                "repository_commit": envelope.repository_commit,
                "completed_at_ns": time.time_ns(),
            }
            receipt_sha256 = _sha256_bytes(_canonical(no_change_receipt))
            receipt_signature = hmac.new(
                self._key,
                _CHECKPOINT_DOMAIN
                + b"RECEIPT\0"
                + _canonical(no_change_receipt),
                hashlib.sha256,
            ).hexdigest()
            self._write_checkpoint(
                envelope.mission_id,
                {
                    **intent,
                    "stage": "no_change_receipt_persisted",
                    "attempt_state": "no_change",
                    "receipt_sha256": receipt_sha256,
                    "receipt_signature": receipt_signature,
                    "changed_path_count": 0,
                    "cost_usd": round(result.cost_usd, 6),
                },
            )
            self._quarantine_terminal_clone(clone, envelope, "no_change")
            if cancel() or self._terminal_state(envelope.mission_id) in {
                "cancelled",
                "failed",
            }:
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": "late external-agent result discarded after kill",
                }
            return {
                "status": "succeeded",
                "data": {
                    "outcome": "no_change",
                    "changed_paths": [],
                    "cost_usd": round(result.cost_usd, 6),
                    "draft_pr_handoff": False,
                    "external_pr_created": False,
                },
                "evidence": [
                    {
                        "kind": "external_agent_no_change_receipt",
                        "sha256": receipt_sha256,
                        "signature": receipt_signature,
                    }
                ],
                "postconditions": [
                    {"name": "owner_repository_unchanged", "satisfied": True},
                    {"name": "no_patch_materialized", "satisfied": True},
                    {"name": "draft_pr_handoff_absent", "satisfied": True},
                ],
                "waiting_for": None,
            }
        if result.status == "succeeded" and patch_bytes:
            checked = self._git.run(
                clone,
                ["apply", "--check", "--whitespace=error-all", "-"],
                payload=patch_bytes,
                timeout=60,
            )
            if checked.returncode == 0:
                applied = self._git.run(
                    clone,
                    ["apply", "--whitespace=error-all", "-"],
                    payload=patch_bytes,
                    timeout=60,
                )
            else:
                applied = checked
            if checked.returncode != 0 or applied.returncode != 0:
                result = ProviderResultV1(
                    "failed",
                    result.session_id,
                    "provider patch failed controlled application",
                    result.cost_usd,
                    result.output_bytes,
                )
        after_commit, after_digest = self._owner_state(root)
        if after_commit != before_commit or after_digest != before_digest:
            self._write_checkpoint(
                envelope.mission_id,
                {
                    **intent,
                    "stage": "owner_repository_drift",
                    "attempt_state": "attempted_unknown",
                },
            )
            self._quarantine_terminal_clone(
                clone, envelope, "owner_repository_drift"
            )
            raise ExternalAgentWaiting("owner repository changed during provider attempt")
        changed_paths = sorted(set(patch_paths)) if result.status == "succeeded" else []
        if any(
            not _under_allowed(path, envelope.allowed_roots)
            for path in changed_paths
        ):
            result = ProviderResultV1(
                "failed",
                result.session_id,
                "provider changed a path outside the approved roots",
                result.cost_usd,
                result.output_bytes,
            )
        reverse = (
            self._git.run(
                clone,
                ["apply", "--reverse", "--check", "-"],
                payload=patch_bytes,
                timeout=60,
            )
            if patch_bytes
            else None
        )
        if reverse is not None and reverse.returncode != 0:
            result = ProviderResultV1(
                "failed",
                result.session_id,
                "applied patch could not be independently verified",
                result.cost_usd,
                result.output_bytes,
            )
        artifact = (
            self._artifact(envelope, patch_bytes)
            if result.status == "succeeded"
            and patch_bytes
            and reverse is not None
            and reverse.returncode == 0
            else None
        )
        receipt_payload = {
            "schema": "onyx.external_agent.receipt.v1",
            "mission_id": envelope.mission_id,
            "session_id_sha256": _sha256_bytes(result.session_id.encode("utf-8")),
            "provider_id": envelope.provider_id,
            "provider_version": envelope.provider_version,
            "task_sha256": envelope.task_sha256,
            "repository_commit": envelope.repository_commit,
            "allowed_roots": list(envelope.allowed_roots),
            "status": result.status,
            "summary": _safe_text(result.summary, 1000),
            "provider_error": _safe_text(result.provider_error, 240),
            "cost_usd": round(result.cost_usd, 6),
            "output_bytes": result.output_bytes,
            "changed_paths": changed_paths[:500],
            "diff_check": "pass" if reverse is not None and reverse.returncode == 0 else "fail",
            "artifact": artifact,
            "owner_repository_unchanged": True,
            "external_pr_created": False,
            "completed_at_ns": time.time_ns(),
        }
        receipt_sha256 = _sha256_bytes(_canonical(receipt_payload))
        receipt_signature = hmac.new(
            self._key,
            _CHECKPOINT_DOMAIN + b"RECEIPT\0" + _canonical(receipt_payload),
            hashlib.sha256,
        ).hexdigest()
        terminal = (
            "succeeded"
            if result.status == "succeeded"
            and artifact is not None
            and all(
                _under_allowed(path, envelope.allowed_roots)
                for path in changed_paths
            )
            else result.status
        )
        self._write_checkpoint(
            envelope.mission_id,
            {
                **intent,
                "stage": "receipt_persisted",
                "attempt_state": terminal,
                "receipt_sha256": receipt_sha256,
                "receipt_signature": receipt_signature,
                "artifact_sha256": (
                    artifact["plaintext_sha256"] if artifact is not None else ""
                ),
                "changed_path_count": len(changed_paths),
                "cost_usd": round(result.cost_usd, 6),
            },
        )
        self._quarantine_terminal_clone(clone, envelope, terminal)
        if cancel() or self._terminal_state(envelope.mission_id) in {
            "cancelled",
            "failed",
        }:
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": "late external-agent result discarded after kill",
            }
        evidence = [
            {
                "kind": "external_agent_receipt",
                "sha256": receipt_sha256,
                "signature": receipt_signature,
                "provider": envelope.provider_id,
                "session_id_sha256": receipt_payload["session_id_sha256"],
            }
        ]
        if artifact is not None:
            evidence.append(
                {
                    "kind": "draft_pr_handoff",
                    "sha256": artifact["plaintext_sha256"],
                    "bytes": artifact["plaintext_bytes"],
                    "encrypted": True,
                    "external_pr_created": False,
                }
            )
        if terminal != "succeeded":
            return {
                "status": "waiting",
                "data": {
                    "provider_status": terminal,
                    "changed_path_count": len(changed_paths),
                },
                "evidence": evidence,
                "postconditions": [],
                "waiting_for": f"external_agent_{terminal}",
            }
        return {
            "status": "succeeded",
            "data": {
                "summary": receipt_payload["summary"],
                "changed_paths": changed_paths[:100],
                "cost_usd": receipt_payload["cost_usd"],
                "draft_pr_handoff": True,
                "external_pr_created": False,
            },
            "evidence": evidence,
            "postconditions": [
                {"name": "owner_repository_unchanged", "satisfied": True},
                {"name": "diff_check_passed", "satisfied": True},
                {"name": "draft_pr_not_created", "satisfied": True},
            ],
            "waiting_for": None,
        }

    def cancel(self, mission_id: str) -> bool:
        with self._lock:
            session_id = self._active.get(mission_id)
        if session_id is None:
            return False
        return self.provider.cancel(session_id)

    def active_missions(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active))

    def close(self) -> None:
        for mission_id in self.active_missions():
            self.cancel(mission_id)
        self._state.close()


def discover_claude_code_provider_v1() -> ClaudeCodeCliProviderV1:
    executable = shutil.which("claude")
    if not executable:
        raise ExternalAgentUnavailable("Claude Code CLI is not installed")
    provider = ClaudeCodeCliProviderV1(executable)
    if provider.health().get("available") is not True:
        raise ExternalAgentUnavailable("Claude Code account is unavailable")
    return provider


__all__ = [
    "ClaudeCodeCliProviderV1",
    "CLEANUP_TOOL_NAME",
    "DeterministicExternalAgentProviderV1",
    "ExternalAgentContractError",
    "ExternalAgentEnvelopeV1",
    "ExternalAgentError",
    "ExternalAgentUnavailable",
    "ExternalAgentWaiting",
    "ExternalCodingAgentAdapterV1",
    "FEATURE_FLAG",
    "MISSION_TYPE",
    "PROVIDER_ID",
    "ProviderInvocationV1",
    "ProviderResultV1",
    "TOOL_NAME",
    "discover_claude_code_provider_v1",
    "resolve_trusted_git_v1",
]
