"""Capability-bound, content-addressed artifact byte storage.

This module deliberately does not own artifact metadata persistence.  The
successor control-plane store authenticates :class:`ArtifactRecord` manifests;
this service owns only bounded byte publication and byte verification.

There is no default root and no legacy/all-workspaces mode.  A host must first
pin an explicitly allowlisted, already-existing private directory and must opt
in with ``enabled=True``.  Public publish APIs never accept an artifact digest
or destination path.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from enum import Enum
import errno
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import threading
from typing import BinaryIO, Iterator, Mapping
import weakref

from memory.store import contains_secret


ARTIFACT_SCHEMA_VERSION = 1
DEFAULT_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
HARD_MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_MAX_RECORD_CACHE = 256
_POSIX_TEMP_PREFIX = ".onyx-artifact-"
_POSIX_TEMP_NAME = re.compile(r"\.onyx-artifact-[0-9a-f]{64}\.tmp\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z")
_MEDIA_TYPE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}\Z"
)
_SECRET_KEY = re.compile(
    r"(?:api[-_ ]?key|authorization|bearer|client[-_ ]?secret|credential|"
    r"password|private[-_ ]?key|refresh[-_ ]?token|secret|session[-_ ]?token)",
    re.IGNORECASE,
)
_DATA_CLASSES = frozenset({"public", "internal", "confidential"})
_STATUS = "available"
_CAPABILITY_SEAL = object()
_CAPABILITIES: "weakref.WeakKeyDictionary[ArtifactRootCapability, _CapabilityState]" = (
    weakref.WeakKeyDictionary()
)
_CAPABILITIES_LOCK = threading.RLock()


class ArtifactError(RuntimeError):
    """Base artifact-service failure."""


class ArtifactDisabled(ArtifactError):
    """Artifact byte storage was not explicitly enabled."""


class ArtifactContractError(ArtifactError):
    """A caller-supplied contract value is invalid."""


class ArtifactIntegrityError(ArtifactError):
    """Pinned storage or content integrity diverged."""


class ArtifactIOError(ArtifactError):
    """Artifact bytes could not be safely read or published."""


class ArtifactIsolationError(ArtifactError):
    """An artifact belongs to another workspace."""


class ArtifactTooLarge(ArtifactContractError):
    """An artifact exceeded the service's explicit byte bound."""


class _PublicationOutcome(Enum):
    """Identity-safe result of one no-replace CAS publication attempt."""

    CREATED = "created"
    EXACT_EXISTING = "exact_existing"


class _MemoryViewReader:
    """Bounded zero-copy reader over caller-owned bytes-like storage."""

    def __init__(self, value: bytes | bytearray | memoryview) -> None:
        try:
            self._view = memoryview(value).cast("B")
        except (TypeError, ValueError):
            raise ArtifactContractError(
                "data must expose one contiguous bytes-like buffer"
            ) from None
        self._offset = 0

    def read(self, size: int = -1) -> memoryview:
        if size < 0:
            size = self._view.nbytes - self._offset
        end = min(self._view.nbytes, self._offset + size)
        result = self._view[self._offset:end]
        self._offset = end
        return result


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _is_reparse(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _validate_workspace_id(value: str) -> str:
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        raise ArtifactContractError("workspace_id is invalid")
    if value.casefold() in {"all", "all-workspaces", "legacy-default", "*"}:
        raise ArtifactContractError("workspace_id must be explicit and non-legacy")
    if contains_secret(value):
        raise ArtifactContractError("workspace_id appears to contain a secret")
    return value


def _validate_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ArtifactContractError("display_name must be text or None")
    if not value or len(value) > 255 or value in {".", ".."}:
        raise ArtifactContractError("display_name is invalid")
    if any(char in value for char in ("/", "\\", "\0", "\r", "\n")):
        raise ArtifactContractError("display_name must be a leaf metadata value")
    if any(ord(char) < 32 for char in value) or contains_secret(value):
        raise ArtifactContractError("display_name is unsafe")
    return value


def _validate_media_type(value: str) -> str:
    if type(value) is not str or not _MEDIA_TYPE.fullmatch(value):
        raise ArtifactContractError("media_type must be one canonical lowercase MIME type")
    if contains_secret(value):
        raise ArtifactContractError("media_type appears to contain a secret")
    return value


def _validate_data_class(value: str) -> str:
    if type(value) is not str or value not in _DATA_CLASSES:
        if value == "restricted":
            raise ArtifactContractError("restricted artifacts are not permitted")
        raise ArtifactContractError("data_class is invalid")
    return value


def _safe_metadata(value: object, *, depth: int = 0, budget: list[int] | None = None) -> object:
    if budget is None:
        budget = [0]
    if depth > 6:
        raise ArtifactContractError("source_provenance is too deeply nested")
    budget[0] += 1
    if budget[0] > 256:
        raise ArtifactContractError("source_provenance has too many values")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ArtifactContractError("source_provenance contains a non-finite number")
        return value
    if type(value) is str:
        if len(value) > 2048 or contains_secret(value):
            raise ArtifactContractError("source_provenance contains unsafe text")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 128:
                raise ArtifactContractError("source_provenance key is invalid")
            if _SECRET_KEY.search(key) or contains_secret(key):
                raise ArtifactContractError("source_provenance contains a sensitive key")
            result[key] = _safe_metadata(item, depth=depth + 1, budget=budget)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_metadata(item, depth=depth + 1, budget=budget) for item in value]
    raise ArtifactContractError("source_provenance contains an unsupported value")


def _provenance_digest(value: Mapping[str, object] | str) -> str:
    safe = _safe_metadata(value)
    encoded = _canonical(safe)
    if len(encoded) > 16 * 1024:
        raise ArtifactContractError("source_provenance exceeds 16 KiB")
    return _sha(encoded)


def _created_at_from_stat(info: os.stat_result) -> str:
    micros = int(info.st_mtime_ns) // 1_000
    seconds, microsecond = divmod(micros, 1_000_000)
    return datetime.fromtimestamp(seconds, timezone.utc).replace(
        microsecond=microsecond
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Canonical metadata handed to the authenticated successor store."""

    schema_version: int
    artifact_id: str
    workspace_id: str
    sha256: str
    relative_path: str
    media_type: str
    data_class: str
    source_provenance_sha256: str
    display_name: str | None
    size: int
    created_at: str
    status: str

    def canonical_manifest(self) -> bytes:
        """Return deterministic metadata bytes; never artifact content."""

        _validate_record(self)
        return _canonical(asdict(self))

    @property
    def manifest_sha256(self) -> str:
        return _sha(self.canonical_manifest())

    @classmethod
    def from_manifest(cls, value: bytes | bytearray | memoryview | str) -> "ArtifactRecord":
        if isinstance(value, str):
            encoded = value.encode("utf-8")
        elif isinstance(value, (bytes, bytearray, memoryview)):
            encoded = bytes(value)
        else:
            raise ArtifactContractError("artifact manifest must be UTF-8 JSON")
        if len(encoded) > 16 * 1024:
            raise ArtifactContractError("artifact manifest exceeds 16 KiB")
        try:
            decoded = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ArtifactContractError("artifact manifest is invalid") from None
        names = {field.name for field in fields(cls)}
        if not isinstance(decoded, dict) or set(decoded) != names:
            raise ArtifactContractError("artifact manifest schema diverges")
        record = cls(**decoded)
        _validate_record(record)
        if record.canonical_manifest() != encoded:
            raise ArtifactContractError("artifact manifest is noncanonical")
        return record


def _validate_record(record: ArtifactRecord) -> None:
    if type(record) is not ArtifactRecord or record.schema_version != ARTIFACT_SCHEMA_VERSION:
        raise ArtifactContractError("artifact record schema_version is invalid")
    workspace_id = _validate_workspace_id(record.workspace_id)
    if type(record.sha256) is not str or not _DIGEST.fullmatch(record.sha256):
        raise ArtifactContractError("artifact sha256 is noncanonical")
    expected_path = f"{record.sha256[:2]}/{record.sha256}"
    if record.relative_path != expected_path:
        raise ArtifactContractError("artifact relative_path is noncanonical")
    expected_id = "artifact-" + _sha(
        _canonical(["OnyxArtifact.v1", workspace_id, record.sha256])
    )
    if record.artifact_id != expected_id:
        raise ArtifactContractError("artifact_id diverges from content identity")
    _validate_media_type(record.media_type)
    _validate_data_class(record.data_class)
    if not isinstance(record.source_provenance_sha256, str) or not _DIGEST.fullmatch(
        record.source_provenance_sha256
    ):
        raise ArtifactContractError("source_provenance_sha256 is noncanonical")
    _validate_display_name(record.display_name)
    if type(record.size) is not int or not 0 <= record.size <= HARD_MAX_ARTIFACT_BYTES:
        raise ArtifactContractError("artifact size is invalid")
    if type(record.created_at) is not str or not _TIMESTAMP.fullmatch(record.created_at):
        raise ArtifactContractError("artifact created_at is invalid")
    try:
        parsed = datetime.strptime(
            record.created_at, "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        raise ArtifactContractError("artifact created_at is invalid") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != record.created_at:
        raise ArtifactContractError("artifact created_at is noncanonical")
    if record.status != _STATUS:
        raise ArtifactContractError("artifact status is invalid")


class _WindowsAPI:
    """Small NT handle-relative primitive; instantiated only on Windows."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        self.kernel32.CreateFileW.restype = wintypes.HANDLE

        class UNICODE_STRING(ctypes.Structure):
            _fields_ = [
                ("Length", wintypes.USHORT),
                ("MaximumLength", wintypes.USHORT),
                ("Buffer", wintypes.LPWSTR),
            ]

        class OBJECT_ATTRIBUTES(ctypes.Structure):
            _fields_ = [
                ("Length", wintypes.ULONG),
                ("RootDirectory", wintypes.HANDLE),
                ("ObjectName", ctypes.POINTER(UNICODE_STRING)),
                ("Attributes", wintypes.ULONG),
                ("SecurityDescriptor", wintypes.LPVOID),
                ("SecurityQualityOfService", wintypes.LPVOID),
            ]

        class IO_STATUS_BLOCK(ctypes.Structure):
            _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

        class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("dwFileAttributes", wintypes.DWORD),
                ("ftCreationTime", wintypes.FILETIME),
                ("ftLastAccessTime", wintypes.FILETIME),
                ("ftLastWriteTime", wintypes.FILETIME),
                ("dwVolumeSerialNumber", wintypes.DWORD),
                ("nFileSizeHigh", wintypes.DWORD),
                ("nFileSizeLow", wintypes.DWORD),
                ("nNumberOfLinks", wintypes.DWORD),
                ("nFileIndexHigh", wintypes.DWORD),
                ("nFileIndexLow", wintypes.DWORD),
            ]

        self.UNICODE_STRING = UNICODE_STRING
        self.OBJECT_ATTRIBUTES = OBJECT_ATTRIBUTES
        self.IO_STATUS_BLOCK = IO_STATUS_BLOCK
        self.BY_HANDLE_FILE_INFORMATION = BY_HANDLE_FILE_INFORMATION

    def close(self, handle: int) -> None:
        if not self.kernel32.CloseHandle(self.wintypes.HANDLE(handle)):
            raise ArtifactIOError("Windows handle could not be released")

    def identity(self, handle: int, *, directory: bool) -> tuple[int, int, int]:
        info = self.BY_HANDLE_FILE_INFORMATION()
        if not self.kernel32.GetFileInformationByHandle(
            self.wintypes.HANDLE(handle), self.ctypes.byref(info)
        ):
            raise ArtifactIntegrityError("Windows object identity is unavailable")
        if bool(info.dwFileAttributes & 0x400):
            raise ArtifactIntegrityError("linked/reparse artifact storage is forbidden")
        observed_directory = bool(info.dwFileAttributes & 0x10)
        if observed_directory != directory:
            raise ArtifactIntegrityError("artifact storage object has the wrong type")
        if not directory and int(info.nNumberOfLinks) != 1:
            raise ArtifactIntegrityError("artifact file has multiple physical links")
        return (
            int(info.dwVolumeSerialNumber),
            (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow),
            (int(info.nFileSizeHigh) << 32) | int(info.nFileSizeLow),
        )

    def final_path(self, handle: int) -> str:
        size = self.kernel32.GetFinalPathNameByHandleW(
            self.wintypes.HANDLE(handle), None, 0, 0
        )
        if not size:
            raise ArtifactIntegrityError("Windows final path is unavailable")
        buffer = self.ctypes.create_unicode_buffer(size + 1)
        if not self.kernel32.GetFinalPathNameByHandleW(
            self.wintypes.HANDLE(handle), buffer, len(buffer), 0
        ):
            raise ArtifactIntegrityError("Windows final path is unavailable")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return os.path.normcase(os.path.abspath(value))

    def open_absolute_directory(self, path: Path) -> int:
        handle = self.kernel32.CreateFileW(
            str(path), 0x00000001 | 0x00000080 | 0x00100000,
            0x1 | 0x2 | 0x4, None, 3, 0x02000000 | 0x00200000, None,
        )
        invalid = self.ctypes.c_void_p(-1).value
        if not handle or int(handle) == invalid:
            raise ArtifactIntegrityError("artifact root could not be pinned")
        result = int(handle)
        try:
            self.identity(result, directory=True)
            if self.final_path(result) != os.path.normcase(os.path.abspath(path)):
                raise ArtifactIntegrityError("artifact root resolved outside its allowlist")
            return result
        except BaseException:
            self.close(result)
            raise

    def open_relative(
        self, root: int, name: str, *, directory: bool, create: bool = False,
        read_only: bool = False,
    ) -> int:
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ArtifactIntegrityError("relative artifact name is invalid")
        buffer = self.ctypes.create_unicode_buffer(name)
        encoded = name.encode("utf-16-le")
        unicode_name = self.UNICODE_STRING(
            len(encoded), len(encoded) + 2,
            self.ctypes.cast(buffer, self.wintypes.LPWSTR),
        )
        attributes = self.OBJECT_ATTRIBUTES(
            self.ctypes.sizeof(self.OBJECT_ATTRIBUTES),
            self.wintypes.HANDLE(root), self.ctypes.pointer(unicode_name),
            0x40, None, None,
        )
        iosb = self.IO_STATUS_BLOCK()
        output = self.wintypes.HANDLE()
        if directory:
            access = 0x00000001 | 0x00000080 | 0x00100000
        elif read_only:
            access = 0x80000000 | 0x00000080 | 0x00100000
        else:
            access = 0x80000000 | 0x40000000 | 0x00010000 | 0x00100000
        options = 0x00200000 | (0x1 if directory else (0x40 | 0x20))
        disposition = 3 if directory and create else (2 if create else 1)
        status_value = self.ntdll.NtCreateFile(
            self.ctypes.byref(output), access, self.ctypes.byref(attributes),
            self.ctypes.byref(iosb), None, 0x10 if directory else 0x80,
            0x1 | 0x2 | (0x4 if read_only else 0), disposition, options, None, 0,
        )
        if int(status_value) < 0 or not output.value:
            code = int(status_value) & 0xFFFFFFFF
            if not create and code in {0xC0000034, 0xC000003A}:
                raise FileNotFoundError(name)
            if create and code in {0xC0000035, 0xC00000BA}:
                raise FileExistsError(name)
            raise ArtifactIntegrityError(
                f"native relative artifact open failed (ntstatus=0x{code:08x})"
            )
        handle = int(output.value)
        try:
            self.identity(handle, directory=directory)
            return handle
        except BaseException:
            self.close(handle)
            raise

    def rename_no_replace(self, handle: int, target_root: int, name: str) -> None:
        class FILE_RENAME_INFO(self.ctypes.Structure):
            _fields_ = [
                ("ReplaceIfExists", self.ctypes.c_ubyte),
                ("RootDirectory", self.wintypes.HANDLE),
                ("FileNameLength", self.wintypes.DWORD),
                ("FileName", self.wintypes.WCHAR * 1),
            ]

        encoded = name.encode("utf-16-le")
        size = FILE_RENAME_INFO.FileName.offset + len(encoded)
        storage = self.ctypes.create_string_buffer(size)
        info = self.ctypes.cast(storage, self.ctypes.POINTER(FILE_RENAME_INFO)).contents
        info.ReplaceIfExists = False
        info.RootDirectory = self.wintypes.HANDLE(target_root)
        info.FileNameLength = len(encoded)
        self.ctypes.memmove(
            self.ctypes.addressof(storage) + FILE_RENAME_INFO.FileName.offset,
            encoded, len(encoded),
        )
        iosb = self.IO_STATUS_BLOCK()
        status_value = self.ntdll.NtSetInformationFile(
            self.wintypes.HANDLE(handle), self.ctypes.byref(iosb), storage, size, 10
        )
        code = int(status_value) & 0xFFFFFFFF
        if int(status_value) < 0:
            if code in {0xC0000035, 0xC00000BA}:
                raise FileExistsError(name)
            raise ArtifactIntegrityError(
                f"native no-replace artifact publication failed (ntstatus=0x{code:08x})"
            )
        if not self.kernel32.FlushFileBuffers(self.wintypes.HANDLE(handle)):
            raise ArtifactIOError("published artifact handle could not be flushed")

    def delete_handle(self, handle: int) -> None:
        class FILE_DISPOSITION_INFO(self.ctypes.Structure):
            _fields_ = [("DeleteFile", self.wintypes.BOOL)]

        value = FILE_DISPOSITION_INFO(True)
        if not self.kernel32.SetFileInformationByHandle(
            self.wintypes.HANDLE(handle), 4, self.ctypes.byref(value),
            self.ctypes.sizeof(value),
        ):
            raise ArtifactIOError("temporary artifact handle could not be discarded")


class _PinnedDirectory:
    """Pinned root and descriptor-relative child operations."""

    def __init__(self, root: Path, *, authorized_identity: tuple[int, ...]) -> None:
        self.root = Path(os.path.abspath(root))
        self._closed = False
        self._close_lock = threading.RLock()
        self._windows: _WindowsAPI | None = None
        self._root_handle: int | None = None
        self._root_fd: int | None = None
        self._fd_chain: list[int] = []
        self._root_identity: tuple[int, ...]
        # POSIX has no portable unlink-by-open-descriptor primitive.  Keep the
        # single quarantine slot and every publication decision under one
        # process-local/re-entrant lock plus an inter-process flock on the
        # pinned root descriptor.  The thread lock is necessary because flock
        # semantics alone do not serialize users of the same open file
        # description inside one process.
        self._posix_publication_lock = threading.RLock()
        self._posix_publication_depth = 0
        if os.name == "nt":
            self._windows = _WindowsAPI()
            self._root_handle = self._windows.open_absolute_directory(self.root)
            self._root_identity = self._windows.identity(
                self._root_handle, directory=True
            )[:2]
        else:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            current = os.open(self.root.anchor or os.sep, flags)
            self._fd_chain.append(current)
            try:
                for component in self.root.parts[1:]:
                    if component in {"", os.sep}:
                        continue
                    child = os.open(component, flags, dir_fd=current)
                    observed = os.fstat(child)
                    if not stat.S_ISDIR(observed.st_mode):
                        os.close(child)
                        raise ArtifactIntegrityError(
                            "artifact root ancestor is not a directory"
                        )
                    self._fd_chain.append(child)
                    current = child
                self._root_fd = current
                self._root_identity = _identity(os.fstat(current))
            except BaseException:
                for opened in reversed(self._fd_chain):
                    os.close(opened)
                self._fd_chain.clear()
                raise
        if self._root_identity != authorized_identity:
            self.close()
            raise ArtifactIntegrityError(
                "artifact root changed while its capability was authorized"
            )
        self._authorized_identity = authorized_identity

    def _path_identity(self) -> tuple[int, ...]:
        try:
            if os.name == "nt":
                assert self._windows is not None
                handle = self._windows.open_absolute_directory(self.root)
                try:
                    return self._windows.identity(handle, directory=True)[:2]
                finally:
                    self._windows.close(handle)
            observed = self.root.lstat()
        except OSError:
            raise ArtifactIntegrityError("artifact root path binding changed") from None
        if not stat.S_ISDIR(observed.st_mode) or self.root.is_symlink():
            raise ArtifactIntegrityError("artifact root path binding changed")
        return _identity(observed)

    def assert_pinned(self) -> None:
        if self._closed:
            raise ArtifactIntegrityError("artifact root capability is closed")
        if os.name == "nt":
            assert self._windows is not None and self._root_handle is not None
            if self._windows.identity(self._root_handle, directory=True)[:2] != self._root_identity:
                raise ArtifactIntegrityError("artifact root identity changed")
        else:
            assert self._root_fd is not None
            if _identity(os.fstat(self._root_fd)) != self._root_identity:
                raise ArtifactIntegrityError("artifact root identity changed")
        if self._path_identity() != self._authorized_identity:
            raise ArtifactIntegrityError("artifact root path binding changed")

    @contextmanager
    def prefix(self, name: str, *, create: bool) -> Iterator[int]:
        if not re.fullmatch(r"[0-9a-f]{2}", name):
            raise ArtifactIntegrityError("artifact prefix is invalid")
        self.assert_pinned()
        handle: int | None = None
        if os.name == "nt":
            assert self._windows is not None and self._root_handle is not None
            try:
                handle = self._windows.open_relative(
                    self._root_handle, name, directory=True, create=create
                )
            except FileNotFoundError:
                raise ArtifactIntegrityError("artifact prefix does not exist") from None
        else:
            assert self._root_fd is not None
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=self._root_fd)
                    os.fsync(self._root_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise ArtifactIOError(
                        "artifact prefix could not be created"
                    ) from exc
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                handle = os.open(name, flags, dir_fd=self._root_fd)
            except FileNotFoundError:
                raise ArtifactIntegrityError("artifact prefix does not exist") from None
            except OSError as exc:
                raise ArtifactIntegrityError(
                    "artifact prefix is linked, inaccessible, or not a directory"
                ) from exc
            observed = os.fstat(handle)
            if not stat.S_ISDIR(observed.st_mode):
                os.close(handle)
                raise ArtifactIntegrityError("artifact prefix is not a directory")
            try:
                os.fchmod(handle, 0o700)
            except OSError as exc:
                os.close(handle)
                raise ArtifactIOError("artifact prefix permissions could not be pinned") from exc
        try:
            self.assert_pinned()
            yield handle
        finally:
            if handle is not None:
                if os.name == "nt":
                    assert self._windows is not None
                    self._windows.close(handle)
                else:
                    os.close(handle)

    @contextmanager
    def publication_lock(self) -> Iterator[None]:
        """Serialize POSIX CAS publication and quarantine ownership.

        Windows publication already uses handle-relative no-replace and
        handle-based deletion, so it intentionally keeps the existing path.
        """

        if os.name == "nt":
            yield
            return
        assert self._root_fd is not None
        import fcntl

        with self._posix_publication_lock:
            if self._posix_publication_depth == 0:
                fcntl.flock(self._root_fd, fcntl.LOCK_EX)
            self._posix_publication_depth += 1
            try:
                yield
            finally:
                self._posix_publication_depth -= 1
                if self._posix_publication_depth == 0:
                    fcntl.flock(self._root_fd, fcntl.LOCK_UN)

    def create_temp(self) -> tuple[str, int, tuple[int, ...]]:
        self.assert_pinned()
        if os.name == "nt":
            name = f".onyx-artifact-{secrets.token_hex(16)}.tmp"
            import msvcrt

            assert self._windows is not None and self._root_handle is not None
            handle = self._windows.open_relative(
                self._root_handle, name, directory=False, create=True
            )
            try:
                descriptor = msvcrt.open_osfhandle(
                    handle, os.O_RDWR | getattr(os, "O_BINARY", 0)
                )
            except BaseException:
                try:
                    self._windows.delete_handle(handle)
                finally:
                    self._windows.close(handle)
                raise
            identity = self.descriptor_identity(descriptor)
            return name, descriptor, identity
        assert self._root_fd is not None
        if self._posix_publication_depth <= 0:
            raise ArtifactIntegrityError(
                "POSIX temporary artifact requires the publication lock"
            )
        # Linux can keep the publication inode anonymous until the one atomic
        # linkat(AT_EMPTY_PATH) that installs the canonical name.  Apart from
        # avoiding crash residue, this removes every pathname-based cleanup
        # decision from the Linux success and failure paths.
        if sys.platform.startswith("linux") and hasattr(os, "O_TMPFILE"):
            flags = (
                os.O_RDWR | os.O_TMPFILE | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                descriptor = os.open(".", flags, 0o600, dir_fd=self._root_fd)
            except OSError as exc:
                # O_TMPFILE is optional at the filesystem level.  Fall back to
                # one unpredictable leaf, but never auto-delete that leaf: an
                # offline owner can reconcile it without risking a peer inode.
                if exc.errno not in {
                    errno.EOPNOTSUPP, errno.EINVAL, errno.EISDIR,
                    errno.ENOENT, errno.EPERM,
                }:
                    raise ArtifactIOError(
                        "anonymous POSIX artifact could not be created"
                    ) from exc
            else:
                identity = self.descriptor_identity(descriptor)
                if int(os.fstat(descriptor).st_nlink) != 0:
                    os.close(descriptor)
                    raise ArtifactIntegrityError(
                        "anonymous artifact unexpectedly has a filesystem link"
                    )
                return "", descriptor, identity

        self._audit_stale_temps()
        flags = (
            os.O_RDWR | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        )
        for _attempt in range(16):
            name = f"{_POSIX_TEMP_PREFIX}{secrets.token_hex(32)}.tmp"
            try:
                descriptor = os.open(name, flags, 0o600, dir_fd=self._root_fd)
            except FileExistsError:
                continue
            except OSError as exc:
                raise ArtifactIOError(
                    "POSIX temporary artifact could not be created"
                ) from exc
            try:
                identity = self.descriptor_identity(descriptor)
                info = os.fstat(descriptor)
                if int(info.st_nlink) != 1:
                    raise ArtifactIntegrityError(
                        "temporary artifact unexpectedly has multiple links"
                    )
                self._assert_named_identity(self._root_fd, name, identity)
                return name, descriptor, identity
            except BaseException:
                os.close(descriptor)
                raise
        raise ArtifactIntegrityError(
            "unique POSIX temporary artifact name allocation was exhausted"
        )

    def _audit_stale_temps(self) -> None:
        """Retain and report legacy named residue without pathname deletion.

        No portable POSIX operation can unlink *the inode held by a descriptor*.
        Even under the service flock a same-UID process can replace a leaf
        between identity inspection and ``unlinkat``.  Consequently the online
        reaper is deliberately audit-only; reconciliation must be performed by
        an offline owner that can exclude peer mutation.
        """

        if os.name == "nt":
            return
        assert self._root_fd is not None
        if self._posix_publication_depth <= 0:
            raise ArtifactIntegrityError("stale artifact audit requires the lock")
        try:
            names = os.listdir(self._root_fd)
        except OSError as exc:
            raise ArtifactIOError("artifact root could not be enumerated") from exc
        residue = sorted(name for name in names if _POSIX_TEMP_NAME.fullmatch(name))
        if residue:
            raise ArtifactIntegrityError(
                "named POSIX artifact residue retained for explicit offline "
                f"reconciliation ({len(residue)} leaf/leaves)"
            )

    def descriptor_identity(self, descriptor: int) -> tuple[int, ...]:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise ArtifactIntegrityError("artifact handle is not a regular file")
        if os.name == "nt":
            import msvcrt

            assert self._windows is not None
            return self._windows.identity(
                int(msvcrt.get_osfhandle(descriptor)), directory=False
            )[:2]
        return _identity(observed)

    def flush(self, descriptor: int) -> None:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)

    @staticmethod
    def _digest_descriptor(descriptor: int, size: int) -> str:
        os.lseek(descriptor, 0, os.SEEK_SET)
        remaining = size
        hasher = hashlib.sha256()
        while remaining:
            chunk = os.read(descriptor, min(_CHUNK_BYTES, remaining))
            if not chunk:
                raise ArtifactIntegrityError("published artifact ended during verification")
            hasher.update(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ArtifactIntegrityError("published artifact grew during verification")
        return hasher.hexdigest()

    @staticmethod
    def _named_identity(directory: int, name: str) -> tuple[int, int] | None:
        try:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ArtifactIOError("artifact directory entry could not be inspected") from exc
        if not stat.S_ISREG(info.st_mode):
            raise ArtifactIntegrityError("artifact directory entry is not a regular file")
        return _identity(info)

    @classmethod
    def _assert_named_identity(
        cls, directory: int, name: str, expected: tuple[int, ...]
    ) -> None:
        observed = cls._named_identity(directory, name)
        if observed != expected:
            raise ArtifactIntegrityError("artifact directory entry identity changed")

    @classmethod
    def remove_untrusted_canonical(cls, directory: int, name: str) -> None:
        """Fail closed while retaining an uncertain canonical directory entry.

        A same-UID peer can replace ``name`` after any identity check.  Online
        pathname deletion could therefore erase the peer's inode.  The CAS
        never trusts this entry and leaves it intact for offline reconciliation.
        """

        observed = cls._named_identity(directory, name)
        if observed is None:
            return
        raise ArtifactIntegrityError(
            "untrusted canonical artifact retained for explicit offline "
            "reconciliation"
        )

    @staticmethod
    def _linux_link_descriptor(
        descriptor: int, prefix: int, digest: str
    ) -> None:
        """Create the canonical name from the held inode, never the temp name."""

        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        linkat = getattr(libc, "linkat", None)
        if linkat is None:
            raise ArtifactIntegrityError("Linux descriptor-bound linkat is unavailable")
        linkat.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_int,
        ]
        linkat.restype = ctypes.c_int
        target = os.fsencode(digest)
        # AT_EMPTY_PATH binds the operation directly to the open inode.  Some
        # kernels require CAP_DAC_READ_SEARCH for this form; /proc/self/fd is a
        # descriptor-bound fallback and AT_SYMLINK_FOLLOW resolves that exact
        # process-local handle rather than a caller-controlled filesystem leaf.
        result = linkat(descriptor, b"", prefix, target, 0x1000)
        error = ctypes.get_errno()
        if result != 0 and error in {errno.ENOENT, errno.EPERM, errno.EINVAL}:
            proc_name = os.fsencode(f"/proc/self/fd/{descriptor}")
            result = linkat(-100, proc_name, prefix, target, 0x400)
            error = ctypes.get_errno()
        if result == 0:
            return
        if error == errno.EEXIST:
            raise FileExistsError(digest)
        raise ArtifactIntegrityError(
            f"Linux descriptor-bound publication failed (errno={error})"
        )

    def publish(
        self, temp_name: str, descriptor: int, prefix: int, digest: str,
        expected: tuple[int, ...],
    ) -> _PublicationOutcome:
        if self.descriptor_identity(descriptor) != expected:
            raise ArtifactIntegrityError("temporary artifact descriptor identity changed")
        self.assert_pinned()
        if os.name == "nt":
            import msvcrt

            assert self._windows is not None
            self._windows.rename_no_replace(
                int(msvcrt.get_osfhandle(descriptor)), prefix, digest
            )
        else:
            assert self._root_fd is not None
            anonymous = temp_name == ""
            if not anonymous and not _POSIX_TEMP_NAME.fullmatch(temp_name):
                raise ArtifactIntegrityError("POSIX temporary artifact name is invalid")
            if not anonymous:
                self._assert_named_identity(self._root_fd, temp_name, expected)
            import ctypes

            libc = ctypes.CDLL(None, use_errno=True)
            target = os.fsencode(digest)
            if sys.platform.startswith("linux") and anonymous:
                try:
                    self._linux_link_descriptor(descriptor, prefix, digest)
                except FileExistsError:
                    existing = self.open_existing_optional(prefix, digest)
                    if existing is None:
                        raise ArtifactIntegrityError(
                            "canonical artifact disappeared after publication race"
                        ) from None
                    try:
                        existing_info = os.fstat(existing)
                        if (
                            int(existing_info.st_size) != int(os.fstat(descriptor).st_size)
                            or self._digest_descriptor(
                                existing, int(existing_info.st_size)
                            ) != digest
                        ):
                            raise ArtifactIntegrityError(
                                "canonical artifact race contained mismatched bytes; "
                                "uncertain peer retained"
                            )
                    finally:
                        os.close(existing)
                    # An exact winner is idempotent.  Closing our still-
                    # anonymous loser descriptor discards only our inode.
                    return _PublicationOutcome.EXACT_EXISTING
                canonical = self._named_identity(prefix, digest)
                if canonical != expected:
                    raise ArtifactIntegrityError(
                        "canonical artifact identity diverged during publication; "
                        "uncertain peer retained"
                    )
                held = os.fstat(descriptor)
                if int(held.st_nlink) != 1:
                    raise ArtifactIntegrityError(
                        "published artifact acquired an unexpected hardlink"
                    )
            elif sys.platform == "darwin":
                source = os.fsencode(temp_name)
                if not hasattr(libc, "renameatx_np"):
                    raise ArtifactIntegrityError(
                        "macOS renameatx_np(RENAME_EXCL) is unavailable"
                    )
                result = libc.renameatx_np(
                    self._root_fd, source, prefix, target, 0x00000004
                )
                if result != 0:
                    if ctypes.get_errno() == errno.EEXIST:
                        raise FileExistsError(digest)
                    raise ArtifactIntegrityError(
                        "macOS no-replace artifact publication failed"
                    )
            elif hasattr(libc, "renameat2"):
                source = os.fsencode(temp_name)
                result = libc.renameat2(self._root_fd, source, prefix, target, 1)
                if result != 0:
                    if ctypes.get_errno() == errno.EEXIST:
                        raise FileExistsError(digest)
                    raise ArtifactIntegrityError("no-replace artifact publication failed")
            else:
                raise ArtifactIntegrityError("atomic no-replace publication is unavailable")
            os.fsync(prefix)
            os.fsync(self._root_fd)
        if self.descriptor_identity(descriptor) != expected:
            raise ArtifactIntegrityError("published artifact handle identity changed")
        expected_info = os.fstat(descriptor)
        reopened = self.open_existing(prefix, digest)
        try:
            reopened_info = os.fstat(reopened)
            if (
                self.descriptor_identity(reopened) != expected
                or int(reopened_info.st_size) != int(expected_info.st_size)
                or self._digest_descriptor(reopened, int(expected_info.st_size)) != digest
            ):
                raise ArtifactIntegrityError(
                    "published artifact identity, size, or digest diverged"
                )
        finally:
            os.close(reopened)
        self.assert_pinned()
        return _PublicationOutcome.CREATED

    def discard_temp(
        self, name: str, descriptor: int, expected: tuple[int, ...], *, published: bool
    ) -> bool:
        """Discard only the originally opened temporary inode."""

        if os.name == "nt":
            if published:
                return False
            if self.descriptor_identity(descriptor) != expected:
                raise ArtifactIntegrityError("temporary artifact identity changed")
            import msvcrt

            assert self._windows is not None
            self._windows.delete_handle(int(msvcrt.get_osfhandle(descriptor)))
            return False
        assert self._root_fd is not None
        if self._posix_publication_depth <= 0:
            raise ArtifactIntegrityError(
                "POSIX temporary artifact lost its publication lock"
            )
        if self.descriptor_identity(descriptor) != expected:
            raise ArtifactIntegrityError("temporary artifact identity changed")
        if name == "":
            links = int(os.fstat(descriptor).st_nlink)
            expected_links = 1 if published else 0
            if links != expected_links:
                raise ArtifactIntegrityError(
                    "anonymous artifact link state diverged; any canonical "
                    "entry was retained for offline reconciliation"
                )
            return False
        if not _POSIX_TEMP_NAME.fullmatch(name):
            raise ArtifactIntegrityError("unexpected POSIX temporary artifact name")
        observed = self._named_identity(self._root_fd, name)
        if observed is None:
            return False
        if observed != expected:
            raise ArtifactIntegrityError(
                "temporary artifact name was substituted; replacement retained"
            )
        # A pathname unlink here would recreate the exact stat->unlink race
        # this boundary is designed to eliminate.  Keep the inode and make the
        # retention explicit to the caller/audit trail.
        return True

    def open_existing_optional(self, prefix: int, digest: str) -> int | None:
        if not _DIGEST.fullmatch(digest):
            raise ArtifactIntegrityError("artifact digest name is invalid")
        if os.name == "nt":
            import msvcrt

            assert self._windows is not None
            try:
                handle = self._windows.open_relative(
                    prefix, digest, directory=False, read_only=True
                )
            except FileNotFoundError:
                return None
            try:
                return msvcrt.open_osfhandle(
                    handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
                )
            except BaseException:
                self._windows.close(handle)
                raise
        try:
            observed = os.stat(digest, dir_fd=prefix, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(observed.st_mode) or int(observed.st_nlink) != 1:
            raise ArtifactIntegrityError("artifact path is linked or non-regular")
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
            getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(digest, flags, dir_fd=prefix)
        held = os.fstat(descriptor)
        after = os.stat(digest, dir_fd=prefix, follow_symlinks=False)
        if (
            not stat.S_ISREG(held.st_mode)
            or int(held.st_nlink) != 1
            or _identity(observed) != _identity(held)
            or _identity(after) != _identity(held)
        ):
            os.close(descriptor)
            raise ArtifactIntegrityError("artifact identity changed during open")
        return descriptor

    def open_existing(self, prefix: int, digest: str) -> int:
        descriptor = self.open_existing_optional(prefix, digest)
        if descriptor is None:
            raise ArtifactIntegrityError("artifact bytes are missing")
        return descriptor

    def assert_name_identity(self, prefix: int, name: str, descriptor: int) -> None:
        """Prove the canonical directory entry still names the verified handle."""

        expected = self.descriptor_identity(descriptor)
        if os.name == "nt":
            assert self._windows is not None
            reopened = self._windows.open_relative(
                prefix, name, directory=False, read_only=True
            )
            try:
                observed = self._windows.identity(reopened, directory=False)[:2]
            finally:
                self._windows.close(reopened)
        else:
            try:
                info = os.stat(name, dir_fd=prefix, follow_symlinks=False)
            except OSError:
                raise ArtifactIntegrityError(
                    "artifact path changed during verification"
                ) from None
            if not stat.S_ISREG(info.st_mode) or int(info.st_nlink) != 1:
                raise ArtifactIntegrityError("artifact path is linked or non-regular")
            observed = _identity(info)
        if observed != expected:
            raise ArtifactIntegrityError("artifact path identity changed during verification")

    def close(self) -> None:
        """Release pinned handles with a retryable two-phase commit.

        A failed OS close leaves the failed handle recorded and ``_closed``
        false.  POSIX ancestors are released incrementally, but the root
        descriptor (the live authority used by operations) is always released
        last.  A retry therefore neither double-closes confirmed releases nor
        exposes an authority whose root disappeared during a partial attempt.
        """

        with self._close_lock:
            if self._closed:
                return
            if os.name == "nt":
                if self._windows is not None and self._root_handle is not None:
                    handle = self._root_handle
                    self._windows.close(handle)
                    # Commit only after CloseHandle confirms success.
                    self._root_handle = None
                self._closed = self._root_handle is None
                return

            # Every ancestor may be discarded while the independently-opened
            # root descriptor stays authoritative.  Remove an entry only after
            # os.close confirms it, so later retries cannot double-close a file
            # descriptor that the host may already have reused.
            while len(self._fd_chain) > 1:
                opened = self._fd_chain[0]
                os.close(opened)
                del self._fd_chain[0]

            if self._fd_chain:
                opened = self._fd_chain[0]
                if self._root_fd is not None and opened != self._root_fd:
                    raise ArtifactIntegrityError(
                        "artifact root descriptor chain diverged during close"
                    )
                os.close(opened)
                del self._fd_chain[0]
                self._root_fd = None
            elif self._root_fd is not None:
                # Fail closed rather than risk double-closing an untracked file
                # descriptor whose numeric value may have been reused.
                raise ArtifactIntegrityError(
                    "artifact root descriptor is missing from its pinned chain"
                )
            self._closed = True


class _CapabilityState:
    """Shared, sealed authority and operation lifecycle for one pinned root."""

    def __init__(
        self, pinned: _PinnedDirectory, *, owner_nonce: bytes,
        workspace_id: str | None,
    ) -> None:
        self.pinned = pinned
        self._condition = threading.Condition(threading.RLock())
        self._owner_digest = hashlib.sha256(owner_nonce).digest()
        self._binding_key = secrets.token_bytes(32)
        self._workspace_id: str | None = None
        self._binding_digest: bytes | None = None
        self._active = 0
        self._closing = False
        self._closed = False
        self._local = threading.local()
        if workspace_id is not None:
            self.bind_workspace(workspace_id, owner_nonce=owner_nonce)

    def _binding_payload(self, workspace_id: str) -> bytes:
        return _canonical(
            [
                "OnyxArtifactRootCapability.v1",
                workspace_id,
                os.path.normcase(str(self.pinned.root)),
                list(self.pinned._authorized_identity),
                self._owner_digest.hex(),
            ]
        )

    def _expected_binding(self, workspace_id: str) -> bytes:
        return hmac.new(
            self._binding_key, self._binding_payload(workspace_id), hashlib.sha256
        ).digest()

    def validate_owner(self, owner_nonce: bytes) -> None:
        if not hmac.compare_digest(
            self._owner_digest, hashlib.sha256(owner_nonce).digest()
        ):
            raise ArtifactIntegrityError("artifact capability object binding diverged")

    def bind_workspace(self, workspace_id: str, *, owner_nonce: bytes) -> None:
        workspace_id = _validate_workspace_id(workspace_id)
        with self._condition:
            self.validate_owner(owner_nonce)
            if self._closing or self._closed:
                raise ArtifactIntegrityError("artifact root capability is closed")
            if self._workspace_id is None:
                self.pinned.assert_pinned()
                self._workspace_id = workspace_id
                self._binding_digest = self._expected_binding(workspace_id)
            elif self._workspace_id != workspace_id:
                raise ArtifactIsolationError(
                    "artifact root capability belongs to another workspace"
                )
            if self._binding_digest is None or not hmac.compare_digest(
                self._binding_digest, self._expected_binding(workspace_id)
            ):
                raise ArtifactIntegrityError("artifact capability binding diverged")

    @contextmanager
    def operation(self, workspace_id: str, *, owner_nonce: bytes) -> Iterator[None]:
        with self._condition:
            self.bind_workspace(workspace_id, owner_nonce=owner_nonce)
            if self._closing or self._closed:
                raise ArtifactIntegrityError("artifact root capability is closing")
            self._active += 1
            self._local.depth = int(getattr(self._local, "depth", 0)) + 1
        try:
            self.pinned.assert_pinned()
            yield
            self.pinned.assert_pinned()
        finally:
            with self._condition:
                self._local.depth -= 1
                self._active -= 1
                if self._active == 0:
                    self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            if int(getattr(self._local, "depth", 0)):
                raise ArtifactIntegrityError(
                    "artifact capability cannot close from an in-flight operation"
                )
            # Serialize concurrent close callers.  A caller arriving while a
            # close is in progress must not race the pinned handle release. If
            # that attempt fails, the waiter becomes an explicit retry.
            while self._closing:
                self._condition.wait()
                if self._closed:
                    return
            self._closing = True
            while self._active:
                self._condition.wait()
        try:
            # Keep the lifecycle in ``closing`` while the host handle is
            # released.  New operations therefore fail closed, but active
            # operations have already drained before this commit attempt.
            self.pinned.close()
        except BaseException:
            # Closing is retryable: a failed handle release must not make the
            # authority appear closed or allow its capability/finalizer/host
            # boundary to be discarded by ArtifactRootCapability.close().
            with self._condition:
                self._closing = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._closed = True
            self._closing = False
            self._condition.notify_all()


class ArtifactRootCapability:
    """Opaque, non-copyable proof of one host-allowlisted pinned root."""

    __slots__ = (
        "_seal",
        "_nonce",
        "_finalizer",
        "_host_boundary",
        "_close_lock",
        "__weakref__",
    )

    def __init__(self, seal: object) -> None:
        if seal is not _CAPABILITY_SEAL:
            raise TypeError("ArtifactRootCapability cannot be constructed directly")
        self._seal = seal
        self._nonce = secrets.token_bytes(32)
        self._finalizer: weakref.finalize | None = None
        self._host_boundary: object | None = None
        self._close_lock = threading.RLock()

    def __copy__(self) -> "ArtifactRootCapability":
        raise TypeError("ArtifactRootCapability cannot be copied")

    def __deepcopy__(self, _memo: object) -> "ArtifactRootCapability":
        raise TypeError("ArtifactRootCapability cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("ArtifactRootCapability cannot be serialized")

    def close(self) -> None:
        """Release the host-owned directory handle; services then fail closed."""

        # One capability owns the complete close transaction.  In particular,
        # the state commit, registry removal, finalizer detach and host-boundary
        # release must not be observed or repeated by a competing close caller.
        with self._close_lock:
            with _CAPABILITIES_LOCK:
                state = _CAPABILITIES.get(self)
            if state is not None:
                state.validate_owner(self._nonce)
                # Closing the pinned state is the commit point. Until it
                # succeeds, retain every authority reference so a caller can
                # retry and an abandoned capability retains its finalizer.
                state.close()
                with _CAPABILITIES_LOCK:
                    _CAPABILITIES.pop(self, None)
            boundary = self._host_boundary
            if boundary is not None:
                try:
                    boundary.close()
                except BaseException as exc:
                    # State is already closed, but the boundary remains owned
                    # by this capability so an explicit retry is real.
                    raise ArtifactIntegrityError(
                        "artifact host boundary close failed"
                    ) from exc
                self._host_boundary = None
            # Keep the finalizer armed until both the pinned state and the
            # host boundary have confirmed closure.  If boundary.close()
            # fails and the caller abandons this capability, GC still has a
            # best-effort fallback over the already-idempotent state close.
            if self._finalizer is not None and self._finalizer.alive:
                self._finalizer.detach()


def _finalize_host_capability(state: _CapabilityState, boundary: object) -> None:
    """Best-effort GC cleanup in the required pinned-state -> boundary order."""

    state.close()
    boundary.close()


def _authorize_root_for_testing(
    root: Path | str, *, allowlisted_roots: tuple[Path | str, ...],
    workspace_id: str | None = None,
) -> ArtifactRootCapability:
    """Test/host seam: pin one exact pre-created private allowlisted root."""

    path = Path(os.path.abspath(root))
    normalized = os.path.normcase(str(path))
    allowed = {os.path.normcase(os.path.abspath(item)) for item in allowlisted_roots}
    if normalized not in allowed:
        raise ArtifactIsolationError("artifact root is outside the host allowlist")
    try:
        observed = path.lstat()
    except OSError as exc:
        raise ArtifactIntegrityError("artifact root must already exist") from exc
    if not stat.S_ISDIR(observed.st_mode) or path.is_symlink() or _is_reparse(path):
        raise ArtifactIntegrityError("artifact root must be one regular unlinked directory")
    if os.name != "nt":
        if hasattr(os, "geteuid") and observed.st_uid != os.geteuid():
            raise ArtifactIsolationError("artifact root is not owned by the current host")
        if stat.S_IMODE(observed.st_mode) & 0o077:
            raise ArtifactIsolationError("artifact root must be private (0700 or stricter)")
        authorized_identity: tuple[int, ...] = _identity(observed)
    else:
        api = _WindowsAPI()
        handle = api.open_absolute_directory(path)
        try:
            authorized_identity = api.identity(handle, directory=True)[:2]
        finally:
            api.close(handle)
    if workspace_id is not None:
        workspace_id = _validate_workspace_id(workspace_id)
    pinned = _PinnedDirectory(path, authorized_identity=authorized_identity)
    capability = ArtifactRootCapability(_CAPABILITY_SEAL)
    try:
        state = _CapabilityState(
            pinned, owner_nonce=capability._nonce, workspace_id=workspace_id
        )
    except BaseException:
        pinned.close()
        raise
    with _CAPABILITIES_LOCK:
        _CAPABILITIES[capability] = state
    capability._finalizer = weakref.finalize(capability, state.close)
    return capability


def authorize_host_root_v1(
    boundary: object,
    *,
    workspace_id: str,
) -> ArtifactRootCapability:
    """Consume one accepted Windows trusted-directory boundary as CAS authority.

    Production activation must already have pinned and validated the exact
    root through ``WindowsTrustedDirectoryV1``. The returned opaque capability
    owns that boundary until close, so replacement/reparse drift remains
    observable for the entire ArtifactService lifetime.
    """

    from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

    if (
        os.name != "nt"
        or type(boundary) is not WindowsTrustedDirectoryV1
        or boundary.enabled is not True
        or boundary.root_identity is None
    ):
        raise ArtifactIsolationError(
            "artifact host root requires an exact Windows trusted boundary"
        )
    boundary._validate()
    path = boundary.path.resolve(strict=True)
    try:
        capability = _authorize_root_for_testing(
            path,
            allowlisted_roots=(path,),
            workspace_id=workspace_id,
        )
    except BaseException:
        boundary.close()
        raise
    with _CAPABILITIES_LOCK:
        state = _CAPABILITIES.get(capability)
    if state is None:
        capability.close()
        boundary.close()
        raise ArtifactIntegrityError("artifact capability registration was lost")
    prior_finalizer = capability._finalizer
    if prior_finalizer is not None and prior_finalizer.alive:
        prior_finalizer.detach()
    capability._host_boundary = boundary
    capability._finalizer = weakref.finalize(
        capability,
        _finalize_host_capability,
        state,
        boundary,
    )
    return capability


class ArtifactService:
    """Workspace-scoped artifact byte publisher and verifier."""

    def __init__(
        self, root: ArtifactRootCapability, *, workspace_id: str,
        enabled: bool = False, max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    ) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        if type(root) is not ArtifactRootCapability or root._seal is not _CAPABILITY_SEAL:
            raise ArtifactContractError("a host-owned artifact root capability is required")
        with _CAPABILITIES_LOCK:
            state = _CAPABILITIES.get(root)
        if state is None:
            raise ArtifactIntegrityError("artifact root capability is invalid or closed")
        self._root = root
        self.workspace_id = _validate_workspace_id(workspace_id)
        state.bind_workspace(self.workspace_id, owner_nonce=root._nonce)
        self._state = state
        self._pinned = state.pinned
        if type(max_bytes) is not int or not 1 <= max_bytes <= HARD_MAX_ARTIFACT_BYTES:
            raise ArtifactContractError("max_bytes is invalid")
        self.max_bytes = max_bytes
        self.enabled = enabled
        self._lock = threading.RLock()
        self._records: dict[str, ArtifactRecord] = {}

    def _remember_record(self, record: ArtifactRecord) -> ArtifactRecord:
        """Keep only a bounded optimization cache; CAS lookup remains durable."""

        prior = self._records.get(record.sha256)
        if prior is not None and prior != record:
            raise ArtifactContractError(
                "content identity replay changed artifact metadata"
            )
        self._records.pop(record.sha256, None)
        self._records[record.sha256] = record
        while len(self._records) > _MAX_RECORD_CACHE:
            self._records.pop(next(iter(self._records)))
        return record

    def _assert_enabled(self) -> None:
        if not self.enabled:
            raise ArtifactDisabled("artifact service is disabled")

    @contextmanager
    def _operation(self) -> Iterator[None]:
        self._assert_enabled()
        with _CAPABILITIES_LOCK:
            registered = _CAPABILITIES.get(self._root)
        if registered is None:
            raise ArtifactIntegrityError("artifact root capability is closed")
        if registered is not self._state or self._pinned is not self._state.pinned:
            raise ArtifactIntegrityError("artifact service capability binding diverged")
        with self._state.operation(
            self.workspace_id, owner_nonce=self._root._nonce
        ):
            yield

    def close(self) -> None:
        """Close the shared capability after all in-flight operations finish."""

        self._root.close()

    def _record(
        self, *, digest: str, info: os.stat_result, media_type: str,
        data_class: str, provenance_digest: str, display_name: str | None,
    ) -> ArtifactRecord:
        record = ArtifactRecord(
            schema_version=ARTIFACT_SCHEMA_VERSION,
            artifact_id="artifact-" + _sha(
                _canonical(["OnyxArtifact.v1", self.workspace_id, digest])
            ),
            workspace_id=self.workspace_id,
            sha256=digest,
            relative_path=f"{digest[:2]}/{digest}",
            media_type=media_type,
            data_class=data_class,
            source_provenance_sha256=provenance_digest,
            display_name=display_name,
            size=int(info.st_size),
            created_at=_created_at_from_stat(info),
            status=_STATUS,
        )
        _validate_record(record)
        return record

    def publish_bytes(
        self, data: bytes | bytearray | memoryview, *, media_type: str,
        data_class: str, source_provenance: Mapping[str, object] | str,
        display_name: str | None = None,
    ) -> ArtifactRecord:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ArtifactContractError("data must be bytes-like")
        reader = _MemoryViewReader(data)
        view = reader._view
        if view.nbytes > self.max_bytes:
            raise ArtifactTooLarge("artifact exceeds the configured byte bound")
        with self._operation():
            # POSIX cannot safely discard a loser temporary path after an
            # attacker-controlled rename.  Hash the bounded in-memory input and
            # resolve the common idempotent-CAS case before allocating the one
            # quarantine slot, under the same root-wide publication lock.
            if os.name != "nt":
                validated_media_type = _validate_media_type(media_type)
                validated_data_class = _validate_data_class(data_class)
                validated_display_name = _validate_display_name(display_name)
                provenance_digest = _provenance_digest(source_provenance)
                digest = hashlib.sha256(view).hexdigest()
                with self._lock, self._pinned.publication_lock():
                    with self._pinned.prefix(digest[:2], create=True) as prefix:
                        existing = self._pinned.open_existing_optional(prefix, digest)
                        if existing is not None:
                            os.close(existing)
                            verified = self._verified_descriptor(
                                prefix, digest, digest, view.nbytes
                            )
                            try:
                                info = os.fstat(verified)
                            finally:
                                os.close(verified)
                            record = self._record(
                                digest=digest,
                                info=info,
                                media_type=validated_media_type,
                                data_class=validated_data_class,
                                provenance_digest=provenance_digest,
                                display_name=validated_display_name,
                            )
                            return self._remember_record(record)
                    return self._publish_stream_impl(
                        reader,
                        media_type=validated_media_type,
                        data_class=validated_data_class,
                        source_provenance=source_provenance,
                        display_name=validated_display_name,
                    )
            return self._publish_stream_impl(
                reader, media_type=media_type, data_class=data_class,
                source_provenance=source_provenance, display_name=display_name,
            )

    def publish_stream(
        self, source: BinaryIO, *, media_type: str, data_class: str,
        source_provenance: Mapping[str, object] | str,
        display_name: str | None = None,
    ) -> ArtifactRecord:
        with self._operation():
            return self._publish_stream_impl(
                source, media_type=media_type, data_class=data_class,
                source_provenance=source_provenance, display_name=display_name,
            )

    def _publish_stream_impl(
        self, source: BinaryIO, *, media_type: str, data_class: str,
        source_provenance: Mapping[str, object] | str,
        display_name: str | None = None,
    ) -> ArtifactRecord:
        if os.name != "nt":
            return self._publish_stream_posix(
                source,
                media_type=media_type,
                data_class=data_class,
                source_provenance=source_provenance,
                display_name=display_name,
            )
        if not hasattr(source, "read"):
            raise ArtifactContractError("source must be a binary readable stream")
        media_type = _validate_media_type(media_type)
        data_class = _validate_data_class(data_class)
        display_name = _validate_display_name(display_name)
        provenance_digest = _provenance_digest(source_provenance)
        with self._lock, self._pinned.publication_lock():
            temp_name, descriptor, temp_identity = self._pinned.create_temp()
            published = False
            try:
                hasher = hashlib.sha256()
                size = 0
                while True:
                    chunk = source.read(min(_CHUNK_BYTES, self.max_bytes - size + 1))
                    if chunk is None or chunk == b"":
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise ArtifactContractError("source returned non-binary data")
                    try:
                        payload = memoryview(chunk).cast("B")
                    except (TypeError, ValueError):
                        raise ArtifactContractError(
                            "source returned a non-contiguous binary buffer"
                        ) from None
                    incoming = payload.nbytes
                    if incoming > self.max_bytes - size:
                        raise ArtifactTooLarge("artifact exceeds the configured byte bound")
                    size += incoming
                    if size > self.max_bytes:
                        raise ArtifactTooLarge("artifact exceeds the configured byte bound")
                    hasher.update(payload)
                    offset = 0
                    while offset < payload.nbytes:
                        written = os.write(descriptor, payload[offset:])
                        if written <= 0:
                            raise ArtifactIOError("temporary artifact write made no progress")
                        offset += written
                self._pinned.flush(descriptor)
                if self._pinned.descriptor_identity(descriptor) != temp_identity:
                    raise ArtifactIntegrityError("temporary artifact identity changed")
                info = os.fstat(descriptor)
                digest = hasher.hexdigest()
                if int(info.st_size) != size:
                    raise ArtifactIntegrityError("temporary artifact size diverges")
                os.lseek(descriptor, 0, os.SEEK_SET)
                if self._hash_descriptor(descriptor, expected_size=size) != digest:
                    raise ArtifactIntegrityError("temporary artifact readback diverges")
                try:
                    with self._pinned.prefix(digest[:2], create=True) as prefix:
                        try:
                            outcome = self._pinned.publish(
                                temp_name, descriptor, prefix, digest,
                                temp_identity,
                            )
                            published = outcome is _PublicationOutcome.CREATED
                        except FileExistsError:
                            existing = self._verified_descriptor(prefix, digest, digest, size)
                            try:
                                existing_info = os.fstat(existing)
                            finally:
                                os.close(existing)
                            record = self._record(
                                digest=digest, info=existing_info, media_type=media_type,
                                data_class=data_class, provenance_digest=provenance_digest,
                                display_name=display_name,
                            )
                            return self._remember_record(record)
                except ArtifactError:
                    raise
                with self._pinned.prefix(digest[:2], create=False) as prefix:
                    verified = self._verified_descriptor(
                        prefix, digest, digest, size
                    )
                    try:
                        final_info = os.fstat(verified)
                    finally:
                        os.close(verified)
                record = self._record(
                    digest=digest, info=final_info, media_type=media_type,
                    data_class=data_class, provenance_digest=provenance_digest,
                    display_name=display_name,
                )
                return self._remember_record(record)
            except ArtifactError:
                raise
            except OSError as exc:
                raise ArtifactIOError("artifact publication failed") from exc
            finally:
                primary = sys.exception()
                cleanup_error: BaseException | None = None
                retained_quarantine = False
                try:
                    retained_quarantine = self._pinned.discard_temp(
                        temp_name, descriptor, temp_identity, published=published
                    )
                except BaseException as exc:  # Preserve a primary publication error.
                    cleanup_error = exc
                try:
                    os.close(descriptor)
                except BaseException as exc:
                    cleanup_error = cleanup_error or exc
                if cleanup_error is not None:
                    if primary is not None:
                        primary.add_note(
                            "temporary artifact cleanup failure: "
                            f"{type(cleanup_error).__name__}: {cleanup_error}"
                        )
                    else:
                        raise ArtifactIntegrityError(
                            "temporary artifact cleanup failed"
                        ) from cleanup_error
                if retained_quarantine:
                    retained = ArtifactIntegrityError(
                        "failed publication retained one bounded POSIX quarantine; "
                        "explicit offline reconciliation is required"
                    )
                    if primary is not None:
                        primary.add_note(str(retained))
                    else:
                        raise retained

    def _publish_stream_posix(
        self, source: BinaryIO, *, media_type: str, data_class: str,
        source_provenance: Mapping[str, object] | str,
        display_name: str | None = None,
    ) -> ArtifactRecord:
        """Bound and hash before allocating a POSIX publication inode.

        The anonymous spool separates fallible/untrusted stream ingestion from
        the descriptor-relative CAS mutation.  Under the root-wide flock we
        first resolve an existing digest, which makes duplicate stream/file
        publication idempotent.  Publication is descriptor-bound on Linux;
        unique temp leaves are only cleanup handles, never byte authorities.
        """

        if not hasattr(source, "read"):
            raise ArtifactContractError("source must be a binary readable stream")
        media_type = _validate_media_type(media_type)
        data_class = _validate_data_class(data_class)
        display_name = _validate_display_name(display_name)
        provenance_digest = _provenance_digest(source_provenance)

        try:
            with tempfile.TemporaryFile(mode="w+b") as spool:
                hasher = hashlib.sha256()
                size = 0
                while True:
                    chunk = source.read(min(_CHUNK_BYTES, self.max_bytes - size + 1))
                    if chunk is None or chunk == b"":
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise ArtifactContractError("source returned non-binary data")
                    try:
                        payload = memoryview(chunk).cast("B")
                    except (TypeError, ValueError):
                        raise ArtifactContractError(
                            "source returned a non-contiguous binary buffer"
                        ) from None
                    incoming = payload.nbytes
                    if incoming > self.max_bytes - size:
                        raise ArtifactTooLarge(
                            "artifact exceeds the configured byte bound"
                        )
                    size += incoming
                    hasher.update(payload)
                    written = spool.write(payload)
                    if written != incoming:
                        raise ArtifactIOError("anonymous artifact spool write diverged")
                spool.flush()
                digest = hasher.hexdigest()
                spool.seek(0)

                with self._lock, self._pinned.publication_lock():
                    with self._pinned.prefix(digest[:2], create=True) as prefix:
                        existing = self._pinned.open_existing_optional(prefix, digest)
                        if existing is not None:
                            try:
                                info = os.fstat(existing)
                                if (
                                    int(info.st_size) != size
                                    or self._hash_descriptor(
                                        existing, expected_size=size
                                    ) != digest
                                ):
                                    raise ArtifactIntegrityError(
                                        "existing artifact size or sha256 diverges; "
                                        "uncertain canonical retained"
                                    )
                            finally:
                                os.close(existing)
                            record = self._record(
                                digest=digest,
                                info=info,
                                media_type=media_type,
                                data_class=data_class,
                                provenance_digest=provenance_digest,
                                display_name=display_name,
                            )
                            return self._remember_record(record)

                    temp_name, descriptor, temp_identity = self._pinned.create_temp()
                    published = False
                    try:
                        remaining = size
                        while remaining:
                            chunk = spool.read(min(_CHUNK_BYTES, remaining))
                            if not chunk:
                                raise ArtifactIntegrityError(
                                    "anonymous artifact spool ended early"
                                )
                            offset = 0
                            while offset < len(chunk):
                                count = os.write(descriptor, chunk[offset:])
                                if count <= 0:
                                    raise ArtifactIOError(
                                        "temporary artifact write made no progress"
                                    )
                                offset += count
                            remaining -= len(chunk)
                        self._pinned.flush(descriptor)
                        if self._pinned.descriptor_identity(descriptor) != temp_identity:
                            raise ArtifactIntegrityError(
                                "temporary artifact identity changed"
                            )
                        info = os.fstat(descriptor)
                        if int(info.st_size) != size:
                            raise ArtifactIntegrityError(
                                "temporary artifact size diverges"
                            )
                        if self._hash_descriptor(descriptor, expected_size=size) != digest:
                            raise ArtifactIntegrityError(
                                "temporary artifact readback diverges"
                            )
                        with self._pinned.prefix(digest[:2], create=False) as prefix:
                            outcome = self._pinned.publish(
                                temp_name, descriptor, prefix, digest,
                                temp_identity,
                            )
                            published = outcome is _PublicationOutcome.CREATED
                            verified = self._verified_descriptor(
                                prefix, digest, digest, size
                            )
                            try:
                                final_info = os.fstat(verified)
                            finally:
                                os.close(verified)
                        record = self._record(
                            digest=digest,
                            info=final_info,
                            media_type=media_type,
                            data_class=data_class,
                            provenance_digest=provenance_digest,
                            display_name=display_name,
                        )
                        return self._remember_record(record)
                    finally:
                        primary = sys.exception()
                        cleanup_error: BaseException | None = None
                        retained = False
                        try:
                            retained = self._pinned.discard_temp(
                                temp_name,
                                descriptor,
                                temp_identity,
                                published=published,
                            )
                        except BaseException as exc:
                            cleanup_error = exc
                        try:
                            os.close(descriptor)
                        except BaseException as exc:
                            cleanup_error = cleanup_error or exc
                        if cleanup_error is not None:
                            if primary is not None:
                                primary.add_note(
                                    "temporary artifact cleanup failure: "
                                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                                )
                            else:
                                raise ArtifactIntegrityError(
                                    "temporary artifact cleanup failed"
                                ) from cleanup_error
                        if retained:
                            note = (
                                "failed publication retained one bounded POSIX "
                                "quarantine; explicit offline reconciliation is required"
                            )
                            if primary is not None:
                                primary.add_note(note)
                            else:
                                raise ArtifactIntegrityError(note)
        except ArtifactError:
            raise
        except OSError as exc:
            raise ArtifactIOError("artifact publication failed") from exc

    def publish_file(
        self, source: Path | str, *, media_type: str, data_class: str,
        source_provenance: Mapping[str, object] | str,
        display_name: str | None = None,
    ) -> ArtifactRecord:
        with self._operation():
            return self._publish_file_impl(
                source, media_type=media_type, data_class=data_class,
                source_provenance=source_provenance, display_name=display_name,
            )

    def _publish_file_impl(
        self, source: Path | str, *, media_type: str, data_class: str,
        source_provenance: Mapping[str, object] | str,
        display_name: str | None = None,
    ) -> ArtifactRecord:
        path = Path(source)
        try:
            before = path.lstat()
        except OSError as exc:
            raise ArtifactIOError("artifact source is unavailable") from exc
        if (
            not stat.S_ISREG(before.st_mode) or path.is_symlink() or _is_reparse(path)
            or int(getattr(before, "st_nlink", 1)) != 1
        ):
            raise ArtifactIntegrityError("artifact source must be one regular unlinked file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        if os.name != "nt":
            # If a regular path is swapped to a FIFO between lstat and open,
            # opening must fail promptly rather than waiting for a writer.
            flags |= getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            held = os.fstat(descriptor)
            if not stat.S_ISREG(held.st_mode):
                raise ArtifactIntegrityError(
                    "artifact source must remain a regular file"
                )
            after = path.lstat()
            if (
                not stat.S_ISREG(held.st_mode)
                or _identity(before) != _identity(held)
                or _identity(after) != _identity(held)
                or path.is_symlink() or _is_reparse(path)
            ):
                raise ArtifactIntegrityError("artifact source identity changed during open")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                return self._publish_stream_impl(
                    handle, media_type=media_type, data_class=data_class,
                    source_provenance=source_provenance,
                    display_name=display_name if display_name is not None else path.name,
                )
        finally:
            os.close(descriptor)

    @staticmethod
    def _hash_descriptor(descriptor: int, *, expected_size: int) -> str:
        os.lseek(descriptor, 0, os.SEEK_SET)
        remaining = expected_size
        hasher = hashlib.sha256()
        while remaining:
            chunk = os.read(descriptor, min(_CHUNK_BYTES, remaining))
            if not chunk:
                raise ArtifactIntegrityError("artifact ended before its declared size")
            hasher.update(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ArtifactIntegrityError("artifact exceeds its declared size")
        return hasher.hexdigest()

    def _verified_descriptor(
        self, prefix: int, name: str, digest: str, expected_size: int,
        *, expected_created_at: str | None = None,
    ) -> int:
        descriptor = self._pinned.open_existing(prefix, name)
        try:
            before = os.fstat(descriptor)
            before_identity = self._pinned.descriptor_identity(descriptor)
            if int(before.st_size) != expected_size or expected_size > self.max_bytes:
                raise ArtifactIntegrityError("artifact size diverges from its record")
            if (
                expected_created_at is not None
                and _created_at_from_stat(before) != expected_created_at
            ):
                raise ArtifactIntegrityError("artifact timestamp diverges from its record")
            if self._hash_descriptor(descriptor, expected_size=expected_size) != digest:
                raise ArtifactIntegrityError("artifact sha256 diverges from its record")
            after = os.fstat(descriptor)
            if (
                self._pinned.descriptor_identity(descriptor) != before_identity
                or int(after.st_size) != int(before.st_size)
                or int(after.st_mtime_ns) != int(before.st_mtime_ns)
                or int(getattr(after, "st_nlink", 1)) != 1
                or not stat.S_ISREG(after.st_mode)
            ):
                raise ArtifactIntegrityError(
                    "artifact identity, size, or timestamp changed during verification"
                )
            self._pinned.assert_name_identity(prefix, name, descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _validate_access(self, record: ArtifactRecord) -> None:
        _validate_record(record)
        if record.workspace_id != self.workspace_id:
            raise ArtifactIsolationError("artifact belongs to another workspace")
        if record.size > self.max_bytes:
            raise ArtifactTooLarge("artifact record exceeds the configured byte bound")

    def lookup(self, record: ArtifactRecord) -> ArtifactRecord:
        with self._operation():
            self._validate_access(record)
            with self._lock, self._pinned.prefix(
                record.sha256[:2], create=False
            ) as prefix:
                descriptor = self._verified_descriptor(
                    prefix, record.sha256, record.sha256, record.size,
                    expected_created_at=record.created_at,
                )
                os.close(descriptor)
        return record

    def recover_indexed_record(
        self,
        *,
        artifact_id: str,
        sha256: str,
        relative_path: str,
        media_type: str,
        created_at: str,
        data_class: str = "internal",
    ) -> ArtifactRecord:
        """Reconstitute one control-plane indexed record under the pinned CAS.

        The legacy control-plane artifact index intentionally stores no byte
        count.  Callers must not inspect a filesystem path to fill that gap.
        This method opens the content-addressed object relative to the pinned
        root, derives its size and timestamp from the held descriptor, hashes
        the complete bytes, and only then returns an exact ``ArtifactRecord``.
        """

        if (
            type(artifact_id) is not str
            or type(sha256) is not str
            or _DIGEST.fullmatch(sha256) is None
        ):
            raise ArtifactContractError("indexed artifact identity is invalid")
        if relative_path != f"{sha256[:2]}/{sha256}":
            raise ArtifactContractError("indexed artifact path is noncanonical")
        validated_media_type = _validate_media_type(media_type)
        validated_data_class = _validate_data_class(data_class)
        with self._operation():
            with self._lock, self._pinned.prefix(
                sha256[:2], create=False
            ) as prefix:
                descriptor = self._pinned.open_existing(prefix, sha256)
                try:
                    self._pinned.assert_name_identity(prefix, sha256, descriptor)
                    before_identity = self._pinned.descriptor_identity(descriptor)
                    info = os.fstat(descriptor)
                    if int(info.st_size) > self.max_bytes:
                        raise ArtifactTooLarge(
                            "indexed artifact exceeds the configured byte bound"
                        )
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or int(getattr(info, "st_nlink", 1)) != 1
                        or _created_at_from_stat(info) != created_at
                        or self._hash_descriptor(
                            descriptor, expected_size=int(info.st_size)
                        )
                        != sha256
                        or self._pinned.descriptor_identity(descriptor)
                        != before_identity
                    ):
                        raise ArtifactIntegrityError(
                            "indexed artifact identity or bytes diverged"
                        )
                    record = self._record(
                        digest=sha256,
                        info=info,
                        media_type=validated_media_type,
                        data_class=validated_data_class,
                        provenance_digest=_sha(
                            _canonical(
                                [
                                    "OnyxArtifactIndexRecovery.v1",
                                    self.workspace_id,
                                    artifact_id,
                                    sha256,
                                ]
                            )
                        ),
                        display_name=None,
                    )
                    if record.artifact_id != artifact_id:
                        raise ArtifactIntegrityError(
                            "indexed artifact identity diverged"
                        )
                    prior = self._records.get(sha256)
                    if prior is not None:
                        if (
                            prior.artifact_id != artifact_id
                            or prior.workspace_id != self.workspace_id
                            or prior.relative_path != relative_path
                            or prior.media_type != media_type
                            or prior.created_at != created_at
                            or prior.size != int(info.st_size)
                        ):
                            raise ArtifactIntegrityError(
                                "indexed artifact metadata diverged"
                            )
                        return prior
                    return self._remember_record(record)
                finally:
                    os.close(descriptor)

    def read(self, record: ArtifactRecord) -> bytes:
        with self._operation():
            self._validate_access(record)
            with self._lock, self._pinned.prefix(
                record.sha256[:2], create=False
            ) as prefix:
                descriptor = self._verified_descriptor(
                    prefix, record.sha256, record.sha256, record.size,
                    expected_created_at=record.created_at,
                )
                try:
                    before = os.fstat(descriptor)
                    before_identity = self._pinned.descriptor_identity(descriptor)
                    hasher = hashlib.sha256()
                    data = bytearray()
                    remaining = record.size
                    while remaining:
                        chunk = os.read(descriptor, min(_CHUNK_BYTES, remaining))
                        if not chunk:
                            raise ArtifactIntegrityError(
                                "artifact ended during bounded read"
                            )
                        hasher.update(chunk)
                        data.extend(chunk)
                        remaining -= len(chunk)
                    if os.read(descriptor, 1):
                        raise ArtifactIntegrityError("artifact grew during bounded read")
                    after = os.fstat(descriptor)
                    if (
                        hasher.hexdigest() != record.sha256
                        or self._pinned.descriptor_identity(descriptor) != before_identity
                        or int(after.st_size) != record.size
                        or int(after.st_mtime_ns) != int(before.st_mtime_ns)
                        or int(getattr(after, "st_nlink", 1)) != 1
                        or not stat.S_ISREG(after.st_mode)
                        or _created_at_from_stat(after) != record.created_at
                    ):
                        raise ArtifactIntegrityError(
                            "artifact changed during bounded read"
                        )
                    self._pinned.assert_name_identity(
                        prefix, record.sha256, descriptor
                    )
                    return bytes(data)
                finally:
                    os.close(descriptor)

    @contextmanager
    def open(self, record: ArtifactRecord) -> Iterator[io.BytesIO]:
        """Yield a verified in-memory reader; no mutable filesystem handle escapes."""

        handle = io.BytesIO(self.read(record))
        try:
            yield handle
        finally:
            handle.close()


__all__ = [
    "ARTIFACT_SCHEMA_VERSION", "DEFAULT_MAX_ARTIFACT_BYTES",
    "HARD_MAX_ARTIFACT_BYTES", "ArtifactContractError", "ArtifactDisabled",
    "ArtifactError", "ArtifactIOError", "ArtifactIntegrityError",
    "ArtifactIsolationError", "ArtifactRecord", "ArtifactRootCapability",
    "ArtifactService", "ArtifactTooLarge", "authorize_host_root_v1",
]
