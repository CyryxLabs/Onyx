"""Handle-relative Windows cleanup for authenticated Phase 11 clone trees.

This module deliberately owns no mission transition and is default-off.  The
caller must hold both the in-process and cross-process mission locks for the
entire operation and must supply terminal/checkpoint/owner validation.
"""
from __future__ import annotations

import ctypes
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generator, Mapping, Protocol

from ctypes import wintypes

from core import native_vault


FEATURE_FLAG = "ONYX_PHASE11_HANDLE_SAFE_CLONE_CLEANUP_V1"
PROVENANCE_SCHEMA = "onyx.phase11.clone_cleanup.provenance.v1"
CLONE_MARKER_SCHEMA = "onyx.phase11.clone_cleanup.marker.v1"
_PROVENANCE_SLOTS = (
    "clone.cleanup.provenance.slot0.v1.json",
    "clone.cleanup.provenance.slot1.v1.json",
)
MANIFEST_SCHEMA = "onyx.phase11.clone_cleanup.manifest.v1"
JOURNAL_SCHEMA = "onyx.phase11.clone_cleanup.journal.v1"
_DOMAIN = b"ONYX/PHASE11/HANDLE-SAFE-CLONE-CLEANUP/V1\0"
_SAFE_MISSION = re.compile(r"^mis_[0-9a-f]{32}$")
_SAFE_COMPONENT = re.compile(r"^[^\\/:]{1,255}$")
_DEVICE = re.compile(
    r"(?i)^(con|prn|aux|nul|clock\$|conin\$|conout\$|"
    r"com(?:[1-9]|[¹²³])|lpt(?:[1-9]|[¹²³]))(?:\..*)?$"
)

_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_FILE_LIST_DIRECTORY = 0x0001
_FILE_ADD_FILE = 0x0002
_FILE_ADD_SUBDIRECTORY = 0x0004
_FILE_DELETE_CHILD = 0x0040
_FILE_READ_DATA = 0x0001
_FILE_WRITE_DATA = 0x0002
_FILE_READ_EA = 0x0008
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_WRITE_ATTRIBUTES = 0x0100
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_FILE_SHARE_DELETE = 0x4
_OPEN_EXISTING = 3
_FILE_OPEN = 1
_FILE_CREATE = 2
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_ATTRIBUTE_READONLY = 0x00000001
_FILE_ATTRIBUTE_OFFLINE = 0x00001000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_FILE_ATTRIBUTE_CLOUD_MASK = (
    _FILE_ATTRIBUTE_OFFLINE
    | _FILE_ATTRIBUTE_RECALL_ON_OPEN
    | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)
_FILE_DISPOSITION_DELETE = 0x1
_FILE_DISPOSITION_POSIX_SEMANTICS = 0x2
_FILE_DISPOSITION_FORCE_IMAGE_SECTION_CHECK = 0x4
_FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE = 0x10
_FILE_RENAME_REPLACE_IF_EXISTS = 0x1
_ERROR_NO_MORE_FILES = 18
_ERROR_FILE_NOT_FOUND = 2
_ERROR_FILE_EXISTS = 80
_ERROR_ALREADY_EXISTS = 183
_ERROR_SHARING_VIOLATION = 32
_ERROR_LOCK_VIOLATION = 33
_ERROR_ACCESS_DENIED = 5
_DRIVE_REMOTE = 4
_FILE_BASIC_INFO_CLASS = 0
_FILE_STANDARD_INFO_CLASS = 1
_FILE_STREAM_INFO_CLASS = 7
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_FILE_ID_BOTH_DIR_INFO_CLASS = 10
_FILE_ID_BOTH_DIR_RESTART_INFO_CLASS = 11
_FILE_ID_INFO_CLASS = 18
_FILE_DISPOSITION_INFO_EX_CLASS = 21
_NATIVE_FILE_RENAME_INFORMATION_EX_CLASS = 65


class CloneCleanupError(RuntimeError):
    pass


class CloneCleanupWaiting(CloneCleanupError):
    pass


class CloneCleanupContractError(CloneCleanupError):
    pass


class SecretVault(Protocol):
    def get_bytes(self) -> bytes | None: ...
    def set_bytes(self, secret: bytes | bytearray) -> None: ...


def _valid_component(name: str) -> bool:
    trimmed = name.rstrip(". ")
    return bool(
        _SAFE_COMPONENT.fullmatch(name)
        and name not in {".", ".."}
        and name == trimmed
        and not _DEVICE.match(trimmed)
    )


def _flush_directory_best_effort(handle: "_Handle") -> bool:
    """Attempt directory metadata flush; Windows may reject directory flushes."""
    return bool(_kernel32.FlushFileBuffers(handle.value))


VaultFactory = Callable[[native_vault.SecretReference], SecretVault]
OwnerValidator = Callable[[], None]
CheckpointWriter = Callable[[str, str | None], None]
FaultHook = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class CleanupLimitsV1:
    max_bytes: int = 1_000_000_000
    max_files: int = 50_000
    max_directories: int = 10_000
    max_depth: int = 64
    max_seconds: float = 120.0
    max_manifest_bytes: int = 16_000_000

    def __post_init__(self) -> None:
        values = (
            self.max_bytes,
            self.max_files,
            self.max_directories,
            self.max_depth,
            self.max_manifest_bytes,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("cleanup quotas must be positive integers")
        if (
            isinstance(self.max_seconds, bool)
            or not isinstance(self.max_seconds, (int, float))
            or not 1 <= float(self.max_seconds) <= 900
        ):
            raise ValueError("cleanup time quota is invalid")


@dataclass(frozen=True, slots=True)
class FileIdentityV1:
    volume_serial: int
    file_id: str
    volume_guid: str
    resolved_path: str


@dataclass(frozen=True, slots=True)
class _Entry:
    name: str
    logical: str
    identity: FileIdentityV1
    is_directory: bool
    attributes: int
    size: int
    links: int
    depth: int
    streams: tuple[str, ...]


def feature_enabled(environment: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environment is None else environment
    return source.get(FEATURE_FLAG) == "true"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _validate_root_path(value: str | os.PathLike[str]) -> Path:
    path = Path(value)
    text = str(path)
    if (
        os.name != "nt"
        or not path.is_absolute()
        or text.startswith(("\\\\", "\\\\?\\", "\\\\.\\"))
        or ":" in text[2:]
    ):
        raise CloneCleanupContractError("cleanup_root_path_invalid")
    return path


class _FILE_ID_128(ctypes.Structure):
    _fields_ = [("Identifier", ctypes.c_ubyte * 16)]


class _FILE_ID_INFO(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", ctypes.c_ulonglong),
        ("FileId", _FILE_ID_128),
    ]


class _FILE_STANDARD_INFO(ctypes.Structure):
    _fields_ = [
        ("AllocationSize", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("NumberOfLinks", wintypes.DWORD),
        ("DeletePending", wintypes.BOOLEAN),
        ("Directory", wintypes.BOOLEAN),
    ]


class _FILE_BASIC_INFO(ctypes.Structure):
    _fields_ = [
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("FileAttributes", wintypes.DWORD),
    ]


class _FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
    _fields_ = [
        ("FileAttributes", wintypes.DWORD),
        ("ReparseTag", wintypes.DWORD),
    ]


class _FILE_DISPOSITION_INFO_EX(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD)]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", wintypes.LPVOID),
        ("SecurityQualityOfService", wintypes.LPVOID),
    ]


class _IO_STATUS_BLOCK_UNION(ctypes.Union):
    _fields_ = [("Status", ctypes.c_long), ("Pointer", wintypes.LPVOID)]


class _IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = [
        ("u", _IO_STATUS_BLOCK_UNION),
        ("Information", ctypes.c_size_t),
    ]


class _FILE_RENAME_INFO_EX_HEAD(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("RootDirectory", wintypes.HANDLE),
        ("FileNameLength", wintypes.DWORD),
    ]


class _FILE_ID_BOTH_DIR_INFO_HEAD(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.DWORD),
        ("FileIndex", wintypes.DWORD),
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("AllocationSize", ctypes.c_longlong),
        ("FileAttributes", wintypes.DWORD),
        ("FileNameLength", wintypes.DWORD),
        ("EaSize", wintypes.DWORD),
        ("ShortNameLength", ctypes.c_ubyte),
        ("Reserved", ctypes.c_ubyte),
        ("ShortName", wintypes.WCHAR * 12),
        ("FileId", ctypes.c_longlong),
    ]


class _FILE_STREAM_INFO_HEAD(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.DWORD),
        ("StreamNameLength", wintypes.DWORD),
        ("StreamSize", ctypes.c_longlong),
        ("StreamAllocationSize", ctypes.c_longlong),
    ]


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    _kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _kernel32.GetVolumeInformationByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    _kernel32.GetVolumeInformationByHandleW.restype = wintypes.BOOL
    _kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetDriveTypeW.restype = wintypes.UINT
    _kernel32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    ]
    _kernel32.SetFilePointerEx.restype = wintypes.BOOL
    _kernel32.SetEndOfFile.argtypes = [wintypes.HANDLE]
    _kernel32.SetEndOfFile.restype = wintypes.BOOL
    _kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    _kernel32.FlushFileBuffers.restype = wintypes.BOOL
    _kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    _kernel32.ReadFile.restype = wintypes.BOOL
    _kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    _kernel32.WriteFile.restype = wintypes.BOOL
    _ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_OBJECT_ATTRIBUTES),
        ctypes.POINTER(_IO_STATUS_BLOCK),
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
    ]
    _ntdll.NtCreateFile.restype = ctypes.c_long
    _ntdll.NtSetInformationFile.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_IO_STATUS_BLOCK),
        wintypes.LPVOID,
        wintypes.ULONG,
        ctypes.c_int,
    ]
    _ntdll.NtSetInformationFile.restype = ctypes.c_long
    _ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    _ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
else:  # pragma: no cover - enabled constructors refuse non-Windows
    _kernel32 = None
    _ntdll = None


class _Handle:
    def __init__(self, value: int) -> None:
        self.value = value
        self.closed = False
        self._close_lock = threading.Lock()

    def close(self) -> None:
        # CloseHandle is the commit point.  A failed call leaves this exact
        # numeric handle live and retryable, while the lock prevents two close
        # callers from racing the same kernel object.
        with self._close_lock:
            if self.closed:
                return
            if not _kernel32.CloseHandle(self.value):
                raise ctypes.WinError(ctypes.get_last_error())
            self.closed = True

    def __enter__(self) -> "_Handle":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _root_handle(
    path: Path,
    *,
    exclusive: bool,
    delete: bool = False,
    sharing_mask: int | None = None,
    mutate_children: bool = False,
) -> _Handle:
    access = _FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
    if delete:
        access |= _DELETE | _FILE_WRITE_ATTRIBUTES
    if mutate_children:
        # Directory mutation is performed through individually held child
        # handles.  Requiring FILE_DELETE_CHILD here is both unnecessary and
        # incompatible with the standard Windows ``Modify`` ACL inherited by
        # an explicitly supplied ONYX_DATA_DIR.  Deletion remains authorized
        # by DELETE on the exact child handle, preserving identity checks.
        access |= _FILE_ADD_FILE | _FILE_ADD_SUBDIRECTORY
    sharing = (
        sharing_mask
        if sharing_mask is not None
        else (
            0
            if exclusive
            else _FILE_SHARE_READ
            | _FILE_SHARE_WRITE
            | _FILE_SHARE_DELETE
        )
    )
    raw = _kernel32.CreateFileW(
        str(path),
        access,
        sharing,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if raw == _INVALID_HANDLE_VALUE:
        code = ctypes.get_last_error()
        if code in {_ERROR_SHARING_VIOLATION, _ERROR_LOCK_VIOLATION}:
            raise CloneCleanupWaiting("cleanup_root_handle_busy")
        if code == _ERROR_ACCESS_DENIED:
            raise CloneCleanupContractError(
                "cleanup_root_access_denied"
            )
        raise CloneCleanupContractError(f"cleanup_root_open_failed:{code}")
    return _Handle(raw)


def _child_handle(
    parent: _Handle,
    name: str,
    *,
    directory: bool,
    exclusive: bool,
    delete: bool,
    create: bool = False,
    sharing_mask: int | None = None,
    write_data: bool = True,
    mutate_children: bool = False,
) -> _Handle:
    if not _valid_component(name):
        raise CloneCleanupContractError("cleanup_component_invalid")
    buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    unicode_name = _UNICODE_STRING(
        encoded_length, encoded_length + 2, ctypes.cast(buffer, wintypes.LPWSTR)
    )
    attributes = _OBJECT_ATTRIBUTES(
        ctypes.sizeof(_OBJECT_ATTRIBUTES),
        parent.value,
        ctypes.pointer(unicode_name),
        0x40,
        None,
        None,
    )
    handle = wintypes.HANDLE()
    io = _IO_STATUS_BLOCK()
    access = _FILE_READ_ATTRIBUTES | _FILE_READ_EA | _SYNCHRONIZE
    if directory:
        access |= _FILE_LIST_DIRECTORY
        if mutate_children:
            access |= _FILE_ADD_FILE | _FILE_ADD_SUBDIRECTORY
    else:
        access |= _FILE_READ_DATA
    if delete:
        access |= _DELETE | _FILE_WRITE_ATTRIBUTES
        if directory:
            access |= (
                _FILE_ADD_FILE | _FILE_ADD_SUBDIRECTORY | _FILE_DELETE_CHILD
            )
        elif write_data:
            access |= _FILE_WRITE_DATA
    if create:
        access |= _DELETE | _FILE_WRITE_ATTRIBUTES
        if directory:
            access |= _FILE_ADD_FILE | _FILE_ADD_SUBDIRECTORY
        else:
            access |= _FILE_WRITE_DATA
    sharing = (
        sharing_mask
        if sharing_mask is not None
        else (
            0
            if exclusive
            else _FILE_SHARE_READ
            | _FILE_SHARE_WRITE
            | _FILE_SHARE_DELETE
        )
    )
    options = (
        _FILE_OPEN_REPARSE_POINT
        | _FILE_SYNCHRONOUS_IO_NONALERT
        | (_FILE_DIRECTORY_FILE if directory else _FILE_NON_DIRECTORY_FILE)
    )
    status = _ntdll.NtCreateFile(
        ctypes.byref(handle),
        access,
        ctypes.byref(attributes),
        ctypes.byref(io),
        None,
        0,
        sharing,
        _FILE_CREATE if create else _FILE_OPEN,
        options,
        None,
        0,
    )
    if status < 0:
        code = int(_ntdll.RtlNtStatusToDosError(status))
        if create and code in {_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS}:
            # Another trusted constructor won the exact create race.  The
            # caller must re-enumerate and reopen the now-existing child; it
            # must never accept the losing handle attempt as proof of identity.
            raise CloneCleanupWaiting("cleanup_entry_create_raced")
        if code in {_ERROR_SHARING_VIOLATION, _ERROR_LOCK_VIOLATION}:
            raise CloneCleanupWaiting("cleanup_entry_handle_busy")
        if code == _ERROR_ACCESS_DENIED:
            # Read-only and temporarily protected child entries use this path
            # during bounded cleanup; callers revalidate the held identity
            # before any retry or attribute change.
            raise CloneCleanupWaiting("cleanup_entry_handle_busy")
        raise CloneCleanupContractError(f"cleanup_entry_open_failed:{code}")
    return _Handle(handle.value)


def _handle_info(
    handle: _Handle, info_class: int, structure: type[ctypes.Structure]
) -> ctypes.Structure:
    result = structure()
    if not _kernel32.GetFileInformationByHandleEx(
        handle.value, info_class, ctypes.byref(result), ctypes.sizeof(result)
    ):
        raise CloneCleanupContractError(
            f"cleanup_handle_query_failed:{info_class}:{ctypes.get_last_error()}"
        )
    return result


def _final_volume_path(handle: _Handle) -> tuple[str, str]:
    capacity = 512
    while capacity <= 32768:
        buffer = ctypes.create_unicode_buffer(capacity)
        length = _kernel32.GetFinalPathNameByHandleW(
            handle.value, buffer, capacity, 0x00000001
        )
        if not length:
            raise CloneCleanupContractError(
                f"cleanup_volume_guid_query_failed:{ctypes.get_last_error()}"
            )
        if length < capacity:
            final = buffer.value
            match = re.match(
                r"^\\\\\?\\(Volume\{[0-9A-Fa-f-]{36}\}\\)(.*)$", final
            )
            if not match:
                raise CloneCleanupContractError("cleanup_volume_guid_invalid")
            volume_guid = ("\\\\?\\" + match.group(1)).casefold()
            suffix = match.group(2).replace("/", "\\").rstrip("\\")
            resolved = (volume_guid + suffix).casefold()
            return volume_guid, resolved
        capacity = length + 1
    raise CloneCleanupContractError("cleanup_volume_guid_too_long")


def _identity(handle: _Handle) -> FileIdentityV1:
    info = _handle_info(handle, _FILE_ID_INFO_CLASS, _FILE_ID_INFO)
    assert isinstance(info, _FILE_ID_INFO)
    volume_guid, resolved_path = _final_volume_path(handle)
    return FileIdentityV1(
        volume_serial=int(info.VolumeSerialNumber),
        file_id=bytes(info.FileId.Identifier).hex(),
        volume_guid=volume_guid,
        resolved_path=resolved_path,
    )


def _filesystem_name(handle: _Handle) -> str:
    name = ctypes.create_unicode_buffer(64)
    if not _kernel32.GetVolumeInformationByHandleW(
        handle.value, None, 0, None, None, None, name, len(name)
    ):
        raise CloneCleanupContractError(
            f"cleanup_filesystem_query_failed:{ctypes.get_last_error()}"
        )
    return name.value.upper()


def _validate_volume(handle: _Handle) -> FileIdentityV1:
    identity = _identity(handle)
    if _filesystem_name(handle) != "NTFS":
        raise CloneCleanupContractError("cleanup_filesystem_unsupported")
    if _kernel32.GetDriveTypeW(identity.volume_guid) == _DRIVE_REMOTE:
        raise CloneCleanupContractError("cleanup_remote_volume_refused")
    return identity


def _attributes_and_standard(
    handle: _Handle,
) -> tuple[_FILE_ATTRIBUTE_TAG_INFO, _FILE_STANDARD_INFO]:
    attributes = _handle_info(
        handle, _FILE_ATTRIBUTE_TAG_INFO_CLASS, _FILE_ATTRIBUTE_TAG_INFO
    )
    standard = _handle_info(
        handle, _FILE_STANDARD_INFO_CLASS, _FILE_STANDARD_INFO
    )
    assert isinstance(attributes, _FILE_ATTRIBUTE_TAG_INFO)
    assert isinstance(standard, _FILE_STANDARD_INFO)
    if attributes.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise CloneCleanupContractError("cleanup_reparse_point_refused")
    if attributes.FileAttributes & _FILE_ATTRIBUTE_CLOUD_MASK:
        raise CloneCleanupContractError("cleanup_cloud_entry_refused")
    if int(standard.NumberOfLinks) != 1:
        raise CloneCleanupContractError("cleanup_hardlink_refused")
    return attributes, standard


def _streams(handle: _Handle) -> tuple[str, ...]:
    size = 64 * 1024
    buffer = ctypes.create_string_buffer(size)
    if not _kernel32.GetFileInformationByHandleEx(
        handle.value, _FILE_STREAM_INFO_CLASS, buffer, size
    ):
        code = ctypes.get_last_error()
        if code == 38:  # ERROR_HANDLE_EOF: a directory with no stream record.
            return ()
        raise CloneCleanupContractError(f"cleanup_stream_query_failed:{code}")
    names: list[str] = []
    offset = 0
    while True:
        if offset + ctypes.sizeof(_FILE_STREAM_INFO_HEAD) > size:
            raise CloneCleanupContractError("cleanup_stream_record_invalid")
        head = _FILE_STREAM_INFO_HEAD.from_buffer(buffer, offset)
        start = offset + ctypes.sizeof(_FILE_STREAM_INFO_HEAD)
        end = start + int(head.StreamNameLength)
        if end > size or head.StreamNameLength % 2:
            raise CloneCleanupContractError("cleanup_stream_record_invalid")
        name = ctypes.wstring_at(
            ctypes.addressof(buffer) + start, int(head.StreamNameLength) // 2
        )
        names.append(name)
        if not head.NextEntryOffset:
            break
        if head.NextEntryOffset < ctypes.sizeof(_FILE_STREAM_INFO_HEAD):
            raise CloneCleanupContractError("cleanup_stream_record_invalid")
        offset += int(head.NextEntryOffset)
    if any(name != "::$DATA" for name in names):
        raise CloneCleanupContractError("cleanup_alternate_data_stream_refused")
    return tuple(names)


def _directory_rows(
    handle: _Handle,
    *,
    guard: Callable[[], None] | None = None,
    entry_guard: Callable[[bool], None] | None = None,
) -> Generator[tuple[str, bool, int], None, None]:
    buffer_size = 64 * 1024
    first = True
    while True:
        if guard is not None:
            guard()
        buffer = ctypes.create_string_buffer(buffer_size)
        info_class = (
            _FILE_ID_BOTH_DIR_RESTART_INFO_CLASS
            if first
            else _FILE_ID_BOTH_DIR_INFO_CLASS
        )
        first = False
        if not _kernel32.GetFileInformationByHandleEx(
            handle.value, info_class, buffer, buffer_size
        ):
            code = ctypes.get_last_error()
            if code in {_ERROR_NO_MORE_FILES, 38}:
                break
            raise CloneCleanupContractError(
                f"cleanup_directory_enumeration_failed:{code}"
            )
        offset = 0
        while True:
            if offset + ctypes.sizeof(_FILE_ID_BOTH_DIR_INFO_HEAD) > buffer_size:
                raise CloneCleanupContractError("cleanup_directory_record_invalid")
            head = _FILE_ID_BOTH_DIR_INFO_HEAD.from_buffer(buffer, offset)
            start = offset + ctypes.sizeof(_FILE_ID_BOTH_DIR_INFO_HEAD)
            end = start + int(head.FileNameLength)
            if end > buffer_size or head.FileNameLength % 2:
                raise CloneCleanupContractError("cleanup_directory_record_invalid")
            name = ctypes.wstring_at(
                ctypes.addressof(buffer) + start, int(head.FileNameLength) // 2
            )
            if name not in {".", ".."}:
                if (
                    not _valid_component(name)
                ):
                    raise CloneCleanupContractError(
                        "cleanup_component_invalid"
                    )
                attributes = int(head.FileAttributes)
                is_directory = bool(
                    attributes & stat.FILE_ATTRIBUTE_DIRECTORY
                )
                if guard is not None:
                    guard()
                if entry_guard is not None:
                    entry_guard(is_directory)
                yield (
                    name,
                    is_directory,
                    attributes,
                )
                if guard is not None:
                    guard()
            if not head.NextEntryOffset:
                break
            if head.NextEntryOffset < ctypes.sizeof(
                _FILE_ID_BOTH_DIR_INFO_HEAD
            ):
                raise CloneCleanupContractError(
                    "cleanup_directory_record_invalid"
                )
            offset += int(head.NextEntryOffset)


def _directory_has_entries(
    handle: _Handle, *, guard: Callable[[], None] | None = None
) -> bool:
    rows = _directory_rows(handle, guard=guard)
    try:
        return next(rows, None) is not None
    finally:
        rows.close()


def _raise_rename_failure(code: int, *, replace: bool) -> None:
    if not replace and code in {
        _ERROR_FILE_EXISTS,
        _ERROR_ALREADY_EXISTS,
    }:
        raise CloneCleanupWaiting("cleanup_rename_destination_exists")
    if code in {
        _ERROR_SHARING_VIOLATION,
        _ERROR_LOCK_VIOLATION,
        _ERROR_ACCESS_DENIED,
    }:
        raise CloneCleanupWaiting("cleanup_root_rename_waiting")
    raise CloneCleanupContractError(
        f"cleanup_root_rename_unsupported:{code}"
    )


def _identity_payload(identity: FileIdentityV1) -> dict[str, object]:
    return {
        "volume_serial": identity.volume_serial,
        "file_id": identity.file_id,
        "volume_guid": identity.volume_guid,
        "resolved_path": identity.resolved_path,
    }


def _same_identity(
    identity: FileIdentityV1, payload: Mapping[str, object]
) -> bool:
    expected = {
        "volume_serial": payload.get("volume_serial"),
        "file_id": payload.get("file_id"),
        "volume_guid": payload.get("volume_guid"),
    }
    actual = {
        "volume_serial": identity.volume_serial,
        "file_id": identity.file_id,
        "volume_guid": identity.volume_guid,
    }
    return hmac.compare_digest(_canonical(actual), _canonical(expected))


def _is_strict_descendant(child: str, parent: str) -> bool:
    normalized_parent = parent.rstrip("\\")
    return child.startswith(normalized_parent + "\\")


def _validate_root_relationships(
    owner: FileIdentityV1,
    worktree: FileIdentityV1,
    mission: FileIdentityV1,
    clone: FileIdentityV1,
) -> None:
    if not _is_strict_descendant(
        mission.resolved_path, worktree.resolved_path
    ) or not _is_strict_descendant(
        clone.resolved_path, mission.resolved_path
    ):
        raise CloneCleanupContractError("cleanup_root_ancestry_invalid")
    if (
        owner.resolved_path == worktree.resolved_path
        or _is_strict_descendant(
            owner.resolved_path, worktree.resolved_path
        )
        or _is_strict_descendant(
            worktree.resolved_path, owner.resolved_path
        )
    ):
        raise CloneCleanupContractError("cleanup_roots_overlap")


class WindowsCloneCleanupV1:
    """Authenticated, fail-closed clone cleanup.

    The worktree and owner are the only absolute root acquisitions. Mission,
    clone, tombstone, metadata and every clone descendant are opened relative
    to an already-authenticated directory handle.
    """

    def __init__(
        self,
        *,
        worktree_root: str | os.PathLike[str],
        signing_key: bytes,
        vault_factory: VaultFactory | None = None,
        enabled: bool | None = None,
        limits: CleanupLimitsV1 | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            not isinstance(signing_key, bytes)
            or len(signing_key) < 32
        ):
            raise ValueError("cleanup signing key must be at least 32 bytes")
        self._key = bytes(signing_key)
        self._vault_factory = vault_factory or (
            lambda reference: native_vault.NativeSecretVault(reference)
        )
        self.enabled = feature_enabled() if enabled is None else enabled
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be bool")
        if self.enabled and os.name != "nt":
            raise CloneCleanupContractError(
                "cleanup_windows_platform_required"
            )
        if os.name == "nt":
            self.worktree_root = _validate_root_path(worktree_root)
        else:
            self.worktree_root = Path(worktree_root)
            if not self.worktree_root.is_absolute():
                raise CloneCleanupContractError(
                    "cleanup_root_path_invalid"
                )
        self.limits = limits or CleanupLimitsV1()
        self._clock = clock
        self._session_handles: dict[
            str, tuple[_Handle, _Handle]
        ] = {}

    def _mission_dir(self, mission_id: str) -> Path:
        if not _SAFE_MISSION.fullmatch(mission_id):
            raise CloneCleanupContractError("cleanup_mission_id_invalid")
        return self.worktree_root / mission_id

    @contextlib.contextmanager
    def _mission_handles(
        self, mission_id: str, *, containment: bool = False
    ) -> object:
        self._mission_dir(mission_id)
        with contextlib.ExitStack() as stack:
            worktree = stack.enter_context(
                _root_handle(
                    self.worktree_root,
                    exclusive=False,
                    sharing_mask=(
                        _FILE_SHARE_READ if containment else None
                    ),
                )
            )
            worktree_identity = _validate_volume(worktree)
            _attributes_and_standard(worktree)
            child = stack.enter_context(
                _child_handle(
                    worktree,
                    mission_id,
                    directory=True,
                    exclusive=False,
                    delete=True,
                    sharing_mask=(
                        (
                            _FILE_SHARE_READ | _FILE_SHARE_WRITE
                            if containment
                            else None
                        )
                    ),
                )
            )
            child_identity = _validate_volume(child)
            _attributes_and_standard(child)
            if (
                child_identity.volume_serial
                != worktree_identity.volume_serial
                or child_identity.volume_guid
                != worktree_identity.volume_guid
            ):
                raise CloneCleanupContractError(
                    "cleanup_mission_volume_changed"
                )
            yield worktree, child

    def _metadata_read(
        self, mission: _Handle, name: str, *, required: bool = True
    ) -> bytes | None:
        try:
            handle = _child_handle(
                mission,
                name,
                directory=False,
                exclusive=False,
                delete=False,
            )
        except CloneCleanupContractError as exc:
            if not required and str(exc).endswith(
                f":{_ERROR_FILE_NOT_FOUND}"
            ):
                return None
            raise CloneCleanupContractError(
                "cleanup_provenance_missing"
            ) from exc
        with handle:
            _attributes, standard = _attributes_and_standard(handle)
            _streams(handle)
            size = int(standard.EndOfFile)
            if size < 0 or size > self.limits.max_manifest_bytes:
                raise CloneCleanupContractError("cleanup_document_too_large")
            buffer = ctypes.create_string_buffer(size or 1)
            read = wintypes.DWORD()
            if size and not _kernel32.ReadFile(
                handle.value,
                buffer,
                size,
                ctypes.byref(read),
                None,
            ):
                raise CloneCleanupContractError(
                    f"cleanup_metadata_read_failed:{ctypes.get_last_error()}"
                )
            if int(read.value) != size:
                raise CloneCleanupContractError(
                    "cleanup_metadata_read_incomplete"
                )
            return bytes(buffer.raw[:size])

    def _metadata_write(
        self, mission: _Handle, name: str, content: bytes
    ) -> None:
        if len(content) > self.limits.max_manifest_bytes:
            raise CloneCleanupContractError("cleanup_document_too_large")
        temporary = f".cc-{secrets.token_hex(12)}.tmp"
        handle = _child_handle(
            mission,
            temporary,
            directory=False,
            exclusive=True,
            delete=True,
            create=True,
        )
        renamed = False
        try:
            written = wintypes.DWORD()
            if content and not _kernel32.WriteFile(
                handle.value,
                content,
                len(content),
                ctypes.byref(written),
                None,
            ):
                raise CloneCleanupContractError(
                    f"cleanup_metadata_write_failed:{ctypes.get_last_error()}"
                )
            if int(written.value) != len(content):
                raise CloneCleanupContractError(
                    "cleanup_metadata_write_incomplete"
                )
            if not _kernel32.FlushFileBuffers(handle.value):
                raise CloneCleanupContractError(
                    f"cleanup_metadata_flush_failed:{ctypes.get_last_error()}"
                )
            self._rename_by_handle(handle, mission, name, replace=True)
            renamed = True
            _flush_directory_best_effort(mission)
        finally:
            if not renamed:
                try:
                    self._dispose(handle)
                except CloneCleanupError:
                    pass
            handle.close()

    def _metadata_delete(self, mission: _Handle, name: str) -> None:
        try:
            handle = _child_handle(
                mission,
                name,
                directory=False,
                exclusive=True,
                delete=True,
            )
        except CloneCleanupContractError as exc:
            if str(exc).endswith(f":{_ERROR_FILE_NOT_FOUND}"):
                return
            raise
        with handle:
            _attributes_and_standard(handle)
            self._dispose(handle)

    def _vault(self, mission_id: str) -> SecretVault:
        return self._vault_factory(
            native_vault.SecretReference(
                service="Onyx.Phase11CloneCleanupProvenance",
                account=f"prov-{mission_id}",
                label=f"Onyx Phase 11 clone cleanup provenance {mission_id}",
            )
        )

    def _sign(self, payload: Mapping[str, object]) -> dict[str, object]:
        body = dict(payload)
        signature = hmac.new(
            self._key, _DOMAIN + _canonical(body), hashlib.sha256
        ).hexdigest()
        return {"payload": body, "signature": signature}

    def _verify_signed(
        self, document: object, schema: str
    ) -> dict[str, object]:
        if not isinstance(document, dict) or set(document) != {
            "payload",
            "signature",
        }:
            raise CloneCleanupContractError("cleanup_document_invalid")
        payload = document["payload"]
        signature = document["signature"]
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != schema
            or not isinstance(signature, str)
        ):
            raise CloneCleanupContractError("cleanup_document_invalid")
        expected = hmac.new(
            self._key, _DOMAIN + _canonical(payload), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise CloneCleanupContractError("cleanup_document_tampered")
        return payload

    def _read_signed(
        self, mission: _Handle, name: str, schema: str
    ) -> dict[str, object]:
        raw = self._metadata_read(mission, name)
        assert raw is not None
        if len(raw) > self.limits.max_manifest_bytes:
            raise CloneCleanupContractError("cleanup_document_too_large")
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloneCleanupContractError(
                "cleanup_document_invalid"
            ) from exc
        return self._verify_signed(document, schema)

    def _provenance_anchor(
        self,
        *,
        mission_id: str,
        nonce: str,
        encoded: bytes,
        slot: str,
        generation: int,
    ) -> bytes:
        return _canonical(
            self._sign(
                {
                    "schema": PROVENANCE_SCHEMA,
                    "mission_id": mission_id,
                    "nonce": nonce,
                    "provenance_digest": hashlib.sha256(encoded).hexdigest(),
                    "slot": slot,
                    "generation": generation,
                }
            )
        )

    def _persist_provenance(
        self,
        *,
        mission: _Handle,
        mission_id: str,
        payload: Mapping[str, object],
        fault_hook: FaultHook | None = None,
    ) -> None:
        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or len(nonce) != 64:
            raise CloneCleanupContractError(
                "cleanup_provenance_nonce_invalid"
            )
        generation = payload.get("generation")
        if type(generation) is not int or generation < 0:
            raise CloneCleanupContractError(
                "cleanup_provenance_generation_invalid"
            )
        slot = _PROVENANCE_SLOTS[generation % len(_PROVENANCE_SLOTS)]
        encoded = _canonical(self._sign(payload))
        anchor = self._provenance_anchor(
            mission_id=mission_id,
            nonce=nonce,
            encoded=encoded,
            slot=slot,
            generation=generation,
        )
        self._metadata_write(mission, slot, encoded)
        if fault_hook is not None:
            fault_hook("after_provenance_slot_write")
        vault = self._vault(mission_id)
        vault.set_bytes(anchor)
        if fault_hook is not None:
            fault_hook("after_provenance_vault_write")
        if vault.get_bytes() != anchor:
            raise CloneCleanupContractError(
                "cleanup_provenance_anchor_write_failed"
            )

    def _load_provenance(
        self, *, mission: _Handle, mission_id: str
    ) -> tuple[dict[str, object], bytes]:
        raw_anchor = self._vault(mission_id).get_bytes()
        if raw_anchor is None:
            candidates: list[
                tuple[dict[str, object], bytes, str, int]
            ] = []
            for slot_index, slot in enumerate(_PROVENANCE_SLOTS):
                encoded = self._metadata_read(
                    mission, slot, required=False
                )
                if encoded is None:
                    continue
                try:
                    document = json.loads(encoded)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise CloneCleanupContractError(
                        "cleanup_document_invalid"
                    ) from exc
                payload = self._verify_signed(
                    document, PROVENANCE_SCHEMA
                )
                generation = payload.get("generation")
                nonce = payload.get("nonce")
                if (
                    generation != slot_index
                    or generation != 0
                    or not isinstance(nonce, str)
                    or len(nonce) != 64
                ):
                    raise CloneCleanupContractError(
                        "cleanup_provenance_unanchored_invalid"
                    )
                candidates.append((payload, encoded, slot, generation))
            if len(candidates) != 1:
                raise CloneCleanupContractError(
                    "cleanup_provenance_anchor_missing"
                )
            payload, encoded, slot, generation = candidates[0]
            anchor = self._provenance_anchor(
                mission_id=mission_id,
                nonce=str(payload["nonce"]),
                encoded=encoded,
                slot=slot,
                generation=generation,
            )
            vault = self._vault(mission_id)
            vault.set_bytes(anchor)
            if vault.get_bytes() != anchor:
                raise CloneCleanupContractError(
                    "cleanup_provenance_anchor_write_failed"
                )
            return payload, encoded
        try:
            anchor_document = json.loads(raw_anchor)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloneCleanupContractError(
                "cleanup_provenance_anchor_invalid"
            ) from exc
        anchor = self._verify_signed(
            anchor_document, PROVENANCE_SCHEMA
        )
        slot = anchor.get("slot")
        generation = anchor.get("generation")
        if (
            slot not in _PROVENANCE_SLOTS
            or type(generation) is not int
            or generation < 0
            or _PROVENANCE_SLOTS[generation % 2] != slot
        ):
            raise CloneCleanupContractError(
                "cleanup_provenance_anchor_invalid"
            )
        encoded = self._metadata_read(mission, str(slot))
        assert encoded is not None
        if hashlib.sha256(encoded).hexdigest() != anchor.get(
            "provenance_digest"
        ):
            raise CloneCleanupContractError(
                "cleanup_provenance_anchor_mismatch"
            )
        try:
            document = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloneCleanupContractError(
                "cleanup_document_invalid"
            ) from exc
        payload = self._verify_signed(document, PROVENANCE_SCHEMA)
        if (
            payload.get("generation") != generation
            or payload.get("mission_id") != mission_id
            or payload.get("nonce") != anchor.get("nonce")
        ):
            raise CloneCleanupContractError(
                "cleanup_provenance_anchor_mismatch"
            )
        return payload, encoded

    def prepare_provenance(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope_digest: str,
        owner_root: str | os.PathLike[str],
        clone_root: str | os.PathLike[str],
        owner_git_sha256: str,
        fault_hook: FaultHook | None = None,
        containment_handles: tuple[_Handle, _Handle] | None = None,
    ) -> dict[str, object]:
        """Persist intent and bind an exact empty clone directory before git."""
        if not self.enabled:
            raise CloneCleanupContractError("cleanup_feature_disabled")
        owner = _validate_root_path(owner_root)
        clone = _validate_root_path(clone_root)
        mission_dir = self._mission_dir(mission_id)
        if os.path.normcase(os.path.abspath(clone)) != os.path.normcase(
            os.path.abspath(mission_dir / "clone")
        ):
            raise CloneCleanupContractError("cleanup_clone_layout_mismatch")
        if any(
            not isinstance(value, str) or len(value) != 64
            for value in (binding_digest, envelope_digest, owner_git_sha256)
        ):
            raise CloneCleanupContractError("cleanup_binding_invalid")
        handles_context = (
            self._mission_handles(mission_id)
            if containment_handles is None
            else contextlib.nullcontext(containment_handles)
        )
        with _root_handle(owner, exclusive=False) as owner_handle, (
            handles_context
        ) as (worktree_handle, mission_handle):
            owner_identity = _validate_volume(owner_handle)
            _attributes_and_standard(owner_handle)
            worktree_identity = _validate_volume(worktree_handle)
            mission_identity = _validate_volume(mission_handle)
            if (
                owner_identity.resolved_path
                == worktree_identity.resolved_path
                or _is_strict_descendant(
                    owner_identity.resolved_path,
                    worktree_identity.resolved_path,
                )
                or _is_strict_descendant(
                    worktree_identity.resolved_path,
                    owner_identity.resolved_path,
                )
            ):
                raise CloneCleanupContractError("cleanup_roots_overlap")
            has_slots = any(
                self._metadata_read(
                    mission_handle, slot, required=False
                )
                is not None
                for slot in _PROVENANCE_SLOTS
            )
            existing: dict[str, object] | None = None
            if has_slots or self._vault(mission_id).get_bytes() is not None:
                existing, _existing_bytes = self._load_provenance(
                    mission=mission_handle, mission_id=mission_id
                )
                for key, value in {
                    "mission_id": mission_id,
                    "binding_digest": binding_digest,
                    "envelope_digest": envelope_digest,
                    "owner_git_sha256": owner_git_sha256,
                }.items():
                    if existing.get(key) != value:
                        raise CloneCleanupContractError(
                            "cleanup_provenance_binding_mismatch"
                        )
                if existing.get("state") not in {"intent", "prepared"}:
                    raise CloneCleanupContractError(
                        "cleanup_provenance_replay"
                    )
                owner_record = existing.get("owner_root")
                worktree_record = existing.get("worktree_root")
                mission_record = existing.get("mission_root")
                if (
                    not isinstance(owner_record, dict)
                    or owner_record.get("canonical")
                    != os.path.normcase(os.path.abspath(owner))
                    or not isinstance(
                        owner_record.get("identity"), dict
                    )
                    or not isinstance(worktree_record, dict)
                    or not isinstance(
                        worktree_record.get("identity"), dict
                    )
                    or not isinstance(mission_record, dict)
                    or not isinstance(
                        mission_record.get("identity"), dict
                    )
                    or not _same_identity(
                        owner_identity, owner_record["identity"]
                    )
                    or owner_identity.resolved_path
                    != owner_record["identity"].get("resolved_path")
                    or not _same_identity(
                        worktree_identity,
                        worktree_record["identity"],
                    )
                    or worktree_identity.resolved_path
                    != worktree_record["identity"].get(
                        "resolved_path"
                    )
                    or not _same_identity(
                        mission_identity, mission_record["identity"]
                    )
                    or mission_identity.resolved_path
                    != mission_record["identity"].get("resolved_path")
                ):
                    raise CloneCleanupContractError(
                        "cleanup_prepared_root_identity_mismatch"
                    )
            clone_names = {
                name
                for name, is_directory, _attrs in _directory_rows(
                    mission_handle
                )
                if name == "clone" and is_directory
            }
            if existing is None:
                if (
                    clone_names
                    or self._vault(mission_id).get_bytes() is not None
                ):
                    raise CloneCleanupContractError(
                        "cleanup_clone_preseed_refused"
                    )
                payload: dict[str, object] = {
                    "schema": PROVENANCE_SCHEMA,
                    "state": "intent",
                    "generation": 0,
                    "mission_id": mission_id,
                    "binding_digest": binding_digest,
                    "envelope_digest": envelope_digest,
                    "owner_git_sha256": owner_git_sha256,
                    "nonce": secrets.token_hex(32),
                    "owner_root": {
                        "canonical": os.path.normcase(
                            os.path.abspath(owner)
                        ),
                        "identity": _identity_payload(owner_identity),
                    },
                    "worktree_root": {
                        "identity": _identity_payload(worktree_identity)
                    },
                    "mission_root": {
                        "identity": _identity_payload(mission_identity)
                    },
                    "clone_root": {
                        "canonical": os.path.normcase(
                            os.path.abspath(clone)
                        ),
                        "identity": None,
                    },
                }
                self._persist_provenance(
                    mission=mission_handle,
                    mission_id=mission_id,
                    payload=payload,
                    fault_hook=fault_hook,
                )
                existing = payload
                if fault_hook is not None:
                    fault_hook("after_clone_intent")
            nonce = str(existing["nonce"])
            marker_name = ".onyx-clone-owner.v1.json"
            if "clone" not in clone_names:
                clone_handle = _child_handle(
                    mission_handle,
                    "clone",
                    directory=True,
                    exclusive=False,
                    delete=True,
                    create=True,
                )
                try:
                    clone_identity = _validate_volume(clone_handle)
                    _attributes_and_standard(clone_handle)
                    _validate_root_relationships(
                        owner_identity,
                        worktree_identity,
                        mission_identity,
                        clone_identity,
                    )
                    if fault_hook is not None:
                        fault_hook(
                            "after_clone_directory_created_before_marker"
                        )
                    marker = self._sign(
                        {
                            "schema": CLONE_MARKER_SCHEMA,
                            "mission_id": mission_id,
                            "nonce": nonce,
                            "clone_identity": _identity_payload(
                                clone_identity
                            ),
                        }
                    )
                    self._metadata_write(
                        clone_handle, marker_name, _canonical(marker)
                    )
                    if fault_hook is not None:
                        fault_hook("after_clone_directory")
                finally:
                    clone_handle.close()
            with _child_handle(
                mission_handle,
                "clone",
                directory=True,
                exclusive=False,
                delete=True,
                sharing_mask=(
                    _FILE_SHARE_READ | _FILE_SHARE_WRITE
                ),
            ) as clone_handle:
                clone_identity = _validate_volume(clone_handle)
                _attributes_and_standard(clone_handle)
                _validate_root_relationships(
                    owner_identity,
                    worktree_identity,
                    mission_identity,
                    clone_identity,
                )
                if existing.get("state") == "intent":
                    marker_bytes = self._metadata_read(
                        clone_handle, marker_name, required=False
                    )
                    if marker_bytes is None:
                        if _directory_has_entries(clone_handle):
                            raise CloneCleanupContractError(
                                "cleanup_clone_preseed_refused"
                            )
                        recovery_marker = self._sign(
                            {
                                "schema": CLONE_MARKER_SCHEMA,
                                "mission_id": mission_id,
                                "nonce": nonce,
                                "clone_identity": _identity_payload(
                                    clone_identity
                                ),
                            }
                        )
                        self._metadata_write(
                            clone_handle,
                            marker_name,
                            _canonical(recovery_marker),
                        )
                        marker_bytes = self._metadata_read(
                            clone_handle, marker_name
                        )
                    assert marker_bytes is not None
                    try:
                        marker_document = json.loads(marker_bytes)
                    except (
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                    ) as exc:
                        raise CloneCleanupContractError(
                            "cleanup_clone_marker_invalid"
                        ) from exc
                    marker_payload = self._verify_signed(
                        marker_document, CLONE_MARKER_SCHEMA
                    )
                    if (
                        marker_payload.get("mission_id") != mission_id
                        or marker_payload.get("nonce") != nonce
                        or not isinstance(
                            marker_payload.get("clone_identity"), dict
                        )
                        or not _same_identity(
                            clone_identity,
                            marker_payload["clone_identity"],
                        )
                    ):
                        raise CloneCleanupContractError(
                            "cleanup_clone_marker_mismatch"
                        )
                    prepared = dict(existing)
                    prepared["state"] = "prepared"
                    prepared["generation"] = int(
                        existing["generation"]
                    ) + 1
                    prepared["clone_root"] = {
                        "canonical": os.path.normcase(
                            os.path.abspath(clone)
                        ),
                        "identity": _identity_payload(clone_identity),
                    }
                    self._persist_provenance(
                        mission=mission_handle,
                        mission_id=mission_id,
                        payload=prepared,
                        fault_hook=fault_hook,
                    )
                    existing = prepared
                else:
                    clone_record = existing.get("clone_root")
                    if (
                        not isinstance(clone_record, dict)
                        or not isinstance(
                            clone_record.get("identity"), dict
                        )
                        or not _same_identity(
                            clone_identity,
                            clone_record["identity"],
                        )
                        or clone_identity.resolved_path
                        != clone_record["identity"].get(
                            "resolved_path"
                        )
                    ):
                        raise CloneCleanupContractError(
                            "cleanup_prepared_clone_identity_mismatch"
                        )
                self._metadata_delete(clone_handle, marker_name)
                if _directory_has_entries(clone_handle):
                    raise CloneCleanupContractError(
                        "cleanup_clone_preseed_refused"
                    )
                if fault_hook is not None:
                    fault_hook("after_clone_marker_removed")
            return existing

    def inspect_provenance(
        self,
        *,
        mission_id: str,
        containment_handles: tuple[_Handle, _Handle] | None = None,
    ) -> dict[str, object] | None:
        """Read authenticated cross-store state without trusting caller stage."""
        if not self.enabled:
            raise CloneCleanupContractError("cleanup_feature_disabled")
        handles_context = (
            self._mission_handles(mission_id)
            if containment_handles is None
            else contextlib.nullcontext(containment_handles)
        )
        with handles_context as (_worktree_handle, mission_handle):
            raw_anchor = self._vault(mission_id).get_bytes()
            if raw_anchor is not None:
                try:
                    anchor_document = json.loads(raw_anchor)
                    anchor_payload = self._verify_signed(
                        anchor_document, PROVENANCE_SCHEMA
                    )
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    CloneCleanupContractError,
                ):
                    anchor_payload = None
                if (
                    anchor_payload is not None
                    and anchor_payload.get("mission_id")
                    == mission_id
                    and anchor_payload.get("state") == "cleaned"
                ):
                    return anchor_payload
            has_slot = any(
                self._metadata_read(
                    mission_handle, slot, required=False
                )
                is not None
                for slot in _PROVENANCE_SLOTS
            )
            has_anchor = raw_anchor is not None
            if not has_slot and not has_anchor:
                return None
            payload, _encoded = self._load_provenance(
                mission=mission_handle, mission_id=mission_id
            )
            return payload

    def finalize_provenance(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope_digest: str,
        owner_root: str | os.PathLike[str],
        clone_root: str | os.PathLike[str],
        owner_git_sha256: str,
        fault_hook: FaultHook | None = None,
        containment_handles: tuple[_Handle, _Handle] | None = None,
    ) -> dict[str, object]:
        payload = self.authenticate_provenance(
            mission_id=mission_id,
            binding_digest=binding_digest,
            envelope_digest=envelope_digest,
            owner_root=owner_root,
            clone_root=clone_root,
            owner_git_sha256=owner_git_sha256,
            containment_handles=containment_handles,
        )
        if payload.get("state") == "finalized":
            return payload
        if payload.get("state") != "prepared":
            raise CloneCleanupContractError(
                "cleanup_provenance_state_invalid"
            )
        finalized = dict(payload)
        finalized["state"] = "finalized"
        finalized["generation"] = int(payload["generation"]) + 1
        active_handles = containment_handles or self._session_handles.get(
            mission_id
        )
        handles_context = (
            self._mission_handles(mission_id)
            if active_handles is None
            else contextlib.nullcontext(active_handles)
        )
        with handles_context as (_worktree_handle, mission_handle):
            self._persist_provenance(
                mission=mission_handle,
                mission_id=mission_id,
                payload=finalized,
                fault_hook=fault_hook,
            )
        return finalized

    def create_provenance(
        self,
        **_kwargs: object,
    ) -> dict[str, object]:
        raise CloneCleanupContractError(
            "legacy_create_provenance_disabled"
        )

    def authenticate_provenance(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope_digest: str,
        owner_root: str | os.PathLike[str],
        clone_root: str | os.PathLike[str],
        owner_git_sha256: str,
        allow_tombstone: bool = False,
        allow_absent: bool = False,
        containment_handles: tuple[_Handle, _Handle] | None = None,
    ) -> dict[str, object]:
        owner = _validate_root_path(owner_root)
        clone = _validate_root_path(clone_root)
        mission_dir = self._mission_dir(mission_id)
        if os.path.normcase(os.path.abspath(clone)) != os.path.normcase(
            os.path.abspath(mission_dir / "clone")
        ):
            raise CloneCleanupContractError("cleanup_clone_layout_mismatch")
        if containment_handles is None:
            containment_handles = self._session_handles.get(
                mission_id
            )
        handles_context = (
            self._mission_handles(mission_id)
            if containment_handles is None
            else contextlib.nullcontext(containment_handles)
        )
        with handles_context as (
            worktree_handle,
            mission_handle,
        ):
            payload, _encoded = self._load_provenance(
                mission=mission_handle, mission_id=mission_id
            )
            worktree_record = payload.get("worktree_root")
            mission_record = payload.get("mission_root")
            current_worktree = _validate_volume(worktree_handle)
            current_mission = _validate_volume(mission_handle)
            if (
                not isinstance(worktree_record, dict)
                or not isinstance(worktree_record.get("identity"), dict)
                or not _same_identity(
                    current_worktree,
                    worktree_record["identity"],
                )
                or current_worktree.resolved_path
                != worktree_record["identity"].get("resolved_path")
                or not isinstance(mission_record, dict)
                or not isinstance(mission_record.get("identity"), dict)
                or not _same_identity(
                    current_mission,
                    mission_record["identity"],
                )
                or current_mission.resolved_path
                != mission_record["identity"].get("resolved_path")
            ):
                raise CloneCleanupContractError(
                    "cleanup_provenance_identity_mismatch"
                )
            clone_record = payload.get("clone_root")
            if not isinstance(clone_record, dict) or set(clone_record) != {
                "canonical",
                "identity",
            }:
                raise CloneCleanupContractError(
                    "cleanup_provenance_root_invalid"
                )
            if clone_record["canonical"] != os.path.normcase(
                os.path.abspath(clone)
            ):
                raise CloneCleanupContractError(
                    "cleanup_provenance_root_mismatch"
                )
            clone_identity = clone_record["identity"]
            if not isinstance(clone_identity, dict):
                raise CloneCleanupContractError(
                    "cleanup_provenance_root_invalid"
                )
            tombstone = (
                f".onyx-cleanup-{str(payload.get('nonce', ''))[:16]}"
            )
            found = False
            for name, is_directory, _attrs in _directory_rows(mission_handle):
                if not is_directory or name not in {"clone", tombstone}:
                    continue
                if name == tombstone and not allow_tombstone:
                    continue
                with _child_handle(
                    mission_handle,
                    name,
                    directory=True,
                    exclusive=False,
                    delete=False,
                ) as candidate:
                    current = _validate_volume(candidate)
                    if _same_identity(current, clone_identity):
                        expected_path = clone_identity.get("resolved_path")
                        if (
                            name == "clone"
                            and current.resolved_path != expected_path
                        ):
                            raise CloneCleanupContractError(
                                "cleanup_provenance_path_mismatch"
                            )
                        found = True
                    elif name == tombstone:
                        continue
                    else:
                        raise CloneCleanupContractError(
                            "cleanup_provenance_identity_mismatch"
                        )
            if not found and not allow_absent:
                raise CloneCleanupContractError(
                    "cleanup_clone_identity_absent"
                )
        expected_scalars = {
            "mission_id": mission_id,
            "binding_digest": binding_digest,
            "envelope_digest": envelope_digest,
            "owner_git_sha256": owner_git_sha256,
        }
        if any(payload.get(key) != value for key, value in expected_scalars.items()):
            raise CloneCleanupContractError("cleanup_provenance_binding_mismatch")
        owner_record = payload.get("owner_root")
        if not isinstance(owner_record, dict) or set(owner_record) != {
            "canonical",
            "identity",
        }:
            raise CloneCleanupContractError("cleanup_provenance_root_invalid")
        if owner_record["canonical"] != os.path.normcase(
            os.path.abspath(owner)
        ):
            raise CloneCleanupContractError("cleanup_provenance_root_mismatch")
        owner_identity = owner_record["identity"]
        if not isinstance(owner_identity, dict):
            raise CloneCleanupContractError("cleanup_provenance_root_invalid")
        with _root_handle(owner, exclusive=False) as owner_handle:
            _attributes_and_standard(owner_handle)
            current_owner = _validate_volume(owner_handle)
            if not _same_identity(current_owner, owner_identity) or (
                current_owner.resolved_path
                != owner_identity.get("resolved_path")
            ):
                raise CloneCleanupContractError(
                    "cleanup_provenance_identity_mismatch"
                )
        if found:
            _validate_root_relationships(
                current_owner,
                current_worktree,
                current_mission,
                current,
            )
        return payload

    @contextlib.contextmanager
    def clone_session_guard(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope_digest: str,
        owner_root: str | os.PathLike[str],
        clone_root: str | os.PathLike[str],
        owner_git_sha256: str,
        containment_handles: tuple[_Handle, _Handle] | None = None,
    ) -> Generator[Path, None, None]:
        """Pin the authenticated clone identity while caller operations run."""
        provenance = self.authenticate_provenance(
            mission_id=mission_id,
            binding_digest=binding_digest,
            envelope_digest=envelope_digest,
            owner_root=owner_root,
            clone_root=clone_root,
            owner_git_sha256=owner_git_sha256,
            containment_handles=containment_handles,
        )
        if provenance.get("state") not in {"prepared", "finalized"}:
            raise CloneCleanupContractError(
                "cleanup_clone_session_state_invalid"
            )
        expected = provenance.get("clone_root")
        if not isinstance(expected, dict) or not isinstance(
            expected.get("identity"), dict
        ):
            raise CloneCleanupContractError(
                "cleanup_provenance_root_invalid"
            )
        expected_identity = expected["identity"]
        canonical = _validate_root_path(clone_root)

        def validate(handle: _Handle) -> None:
            identity = _validate_volume(handle)
            _attributes, standard = _attributes_and_standard(handle)
            if (
                not _same_identity(identity, expected_identity)
                or identity.resolved_path
                != expected_identity.get("resolved_path")
                or not bool(standard.Directory)
            ):
                raise CloneCleanupContractError(
                    "cleanup_clone_session_identity_changed"
                )

        handles_context = (
            self._mission_handles(mission_id, containment=True)
            if containment_handles is None
            else contextlib.nullcontext(containment_handles)
        )
        with handles_context as (worktree_handle, mission_handle):
            with _child_handle(
                mission_handle,
                "clone",
                directory=True,
                exclusive=False,
                delete=False,
                sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            ) as clone_handle:
                validate(clone_handle)
                if mission_id in self._session_handles:
                    raise CloneCleanupContractError(
                        "cleanup_clone_session_already_active"
                    )
                self._session_handles[mission_id] = (
                    worktree_handle,
                    mission_handle,
                )
                try:
                    try:
                        yield canonical
                    except BaseException as primary:
                        try:
                            validate(clone_handle)
                        except BaseException as validation:
                            primary.add_note(
                                "clone session post-validation failed: "
                                + type(validation).__name__
                            )
                        raise
                    validate(clone_handle)
                finally:
                    current = self._session_handles.get(mission_id)
                    if current == (worktree_handle, mission_handle):
                        self._session_handles.pop(mission_id, None)

    def _scan(
        self, root: _Handle, *, started: float
    ) -> tuple[list[_Entry], dict[str, int]]:
        entries: list[_Entry] = []
        identities: set[tuple[int, str]] = set()
        totals = {"bytes": 0, "files": 0, "directories": 0}

        def time_guard() -> None:
            if self._clock() - started > self.limits.max_seconds:
                raise CloneCleanupWaiting("cleanup_time_quota_exceeded")

        def entry_guard(is_directory: bool) -> None:
            key = "directories" if is_directory else "files"
            maximum = (
                self.limits.max_directories
                if is_directory
                else self.limits.max_files
            )
            if totals[key] + 1 > maximum:
                raise CloneCleanupContractError(
                    "cleanup_manifest_quota_exceeded"
                )

        def add(
            handle: _Handle,
            *,
            name: str,
            logical: str,
            is_directory: bool,
            depth: int,
        ) -> None:
            time_guard()
            if depth > self.limits.max_depth:
                raise CloneCleanupContractError("cleanup_depth_quota_exceeded")
            attributes, standard = _attributes_and_standard(handle)
            if bool(standard.Directory) != is_directory:
                raise CloneCleanupContractError("cleanup_entry_type_changed")
            identity = _identity(handle)
            key = (identity.volume_serial, identity.file_id)
            if key in identities:
                raise CloneCleanupContractError("cleanup_duplicate_file_id")
            identities.add(key)
            streams = _streams(handle)
            size = 0 if is_directory else int(standard.EndOfFile)
            if size < 0:
                raise CloneCleanupContractError("cleanup_entry_size_invalid")
            totals["bytes"] += size
            totals["directories" if is_directory else "files"] += 1
            if (
                totals["bytes"] > self.limits.max_bytes
                or totals["files"] > self.limits.max_files
                or totals["directories"] > self.limits.max_directories
            ):
                raise CloneCleanupContractError("cleanup_manifest_quota_exceeded")
            entries.append(
                _Entry(
                    name=name,
                    logical=logical,
                    identity=identity,
                    is_directory=is_directory,
                    attributes=int(attributes.FileAttributes),
                    size=size,
                    links=int(standard.NumberOfLinks),
                    depth=depth,
                    streams=streams,
                )
            )
            if is_directory:
                for child_name, child_dir, _child_attrs in _directory_rows(
                    handle,
                    guard=time_guard,
                    entry_guard=entry_guard,
                ):
                    child_logical = (
                        child_name
                        if not logical
                        else f"{logical}/{child_name}"
                    )
                    with _child_handle(
                        handle,
                        child_name,
                        directory=child_dir,
                        exclusive=False,
                        delete=False,
                    ) as child:
                        add(
                            child,
                            name=child_name,
                            logical=child_logical,
                            is_directory=child_dir,
                            depth=depth + 1,
                        )

        add(root, name="", logical="", is_directory=True, depth=0)
        return entries, totals

    def _manifest_payload(
        self,
        *,
        mission_id: str,
        nonce: str,
        root: _Handle,
        started: float,
    ) -> dict[str, object]:
        entries, totals = self._scan(root, started=started)
        rows = [
            {
                "name": entry.name,
                "logical": entry.logical,
                "identity": _identity_payload(entry.identity),
                "type": "directory" if entry.is_directory else "file",
                "attributes": entry.attributes,
                "size": entry.size,
                "links": entry.links,
                "depth": entry.depth,
                "streams": list(entry.streams),
            }
            for entry in sorted(entries, key=lambda item: item.logical)
        ]
        payload: dict[str, object] = {
            "schema": MANIFEST_SCHEMA,
            "mission_id": mission_id,
            "nonce": nonce,
            "totals": totals,
            "entries": rows,
        }
        signed_size = len(_canonical(self._sign(payload)))
        if signed_size > self.limits.max_manifest_bytes:
            raise CloneCleanupContractError("cleanup_manifest_too_large")
        return payload

    def _write_signed(
        self,
        mission: _Handle,
        name: str,
        payload: Mapping[str, object],
    ) -> None:
        self._metadata_write(mission, name, _canonical(self._sign(payload)))

    def _journal(
        self,
        *,
        mission: _Handle,
        mission_id: str,
        nonce: str,
        manifest_digest: str,
        state: str,
        tombstone: str,
        root_identity: Mapping[str, object],
        completed: list[str],
        current: str | None,
    ) -> None:
        self._write_signed(
            mission,
            "clone.cleanup.journal.v1.json",
            {
                "schema": JOURNAL_SCHEMA,
                "mission_id": mission_id,
                "nonce": nonce,
                "manifest_digest": manifest_digest,
                "state": state,
                "tombstone": tombstone,
                "root_identity": dict(root_identity),
                "completed": list(completed),
                "current": current,
            },
        )

    def _rename_by_handle(
        self,
        target: _Handle,
        parent: _Handle,
        name: str,
        *,
        replace: bool = False,
    ) -> None:
        if not _valid_component(name):
            raise CloneCleanupContractError("cleanup_tombstone_invalid")
        if not replace and any(
            current.casefold() == name.casefold()
            for current, _is_dir, _attrs in _directory_rows(parent)
        ):
            raise CloneCleanupWaiting("cleanup_rename_destination_exists")
        encoded = name.encode("utf-16-le")
        filename_offset = (
            _FILE_RENAME_INFO_EX_HEAD.FileNameLength.offset
            + ctypes.sizeof(wintypes.DWORD)
        )
        size = max(
            ctypes.sizeof(_FILE_RENAME_INFO_EX_HEAD),
            filename_offset + len(encoded) + ctypes.sizeof(wintypes.WCHAR),
        )
        buffer = ctypes.create_string_buffer(size)
        head = _FILE_RENAME_INFO_EX_HEAD.from_buffer(buffer)
        head.Flags = _FILE_RENAME_REPLACE_IF_EXISTS if replace else 0
        head.RootDirectory = parent.value
        head.FileNameLength = len(encoded)
        ctypes.memmove(
            ctypes.addressof(buffer) + filename_offset,
            encoded,
            len(encoded),
        )
        io = _IO_STATUS_BLOCK()
        status = _ntdll.NtSetInformationFile(
            target.value,
            ctypes.byref(io),
            buffer,
            size,
            _NATIVE_FILE_RENAME_INFORMATION_EX_CLASS,
        )
        if status < 0:
            code = int(_ntdll.RtlNtStatusToDosError(status))
            _raise_rename_failure(code, replace=replace)

    def _dispose(self, handle: _Handle) -> None:
        disposition = _FILE_DISPOSITION_INFO_EX(
            _FILE_DISPOSITION_DELETE
            | _FILE_DISPOSITION_POSIX_SEMANTICS
            | _FILE_DISPOSITION_FORCE_IMAGE_SECTION_CHECK
            | _FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE
        )
        if not _kernel32.SetFileInformationByHandle(
            handle.value,
            _FILE_DISPOSITION_INFO_EX_CLASS,
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        ):
            code = ctypes.get_last_error()
            if code in {
                _ERROR_SHARING_VIOLATION,
                _ERROR_LOCK_VIOLATION,
                _ERROR_ACCESS_DENIED,
            }:
                raise CloneCleanupWaiting("cleanup_entry_delete_waiting")
            raise CloneCleanupContractError(
                f"cleanup_disposition_unsupported:{code}"
            )

    @staticmethod
    def _clear_readonly(handle: _Handle) -> None:
        basic = _handle_info(
            handle, _FILE_BASIC_INFO_CLASS, _FILE_BASIC_INFO
        )
        assert isinstance(basic, _FILE_BASIC_INFO)
        if not basic.FileAttributes & _FILE_ATTRIBUTE_READONLY:
            return
        basic.FileAttributes &= ~_FILE_ATTRIBUTE_READONLY
        if not _kernel32.SetFileInformationByHandle(
            handle.value,
            _FILE_BASIC_INFO_CLASS,
            ctypes.byref(basic),
            ctypes.sizeof(basic),
        ):
            code = ctypes.get_last_error()
            if code in {
                _ERROR_SHARING_VIOLATION,
                _ERROR_LOCK_VIOLATION,
                _ERROR_ACCESS_DENIED,
            }:
                raise CloneCleanupWaiting(
                    "cleanup_readonly_attribute_waiting"
                )
            raise CloneCleanupContractError(
                f"cleanup_readonly_attribute_failed:{code}"
            )
        observed = _handle_info(
            handle, _FILE_BASIC_INFO_CLASS, _FILE_BASIC_INFO
        )
        assert isinstance(observed, _FILE_BASIC_INFO)
        if observed.FileAttributes & _FILE_ATTRIBUTE_READONLY:
            raise CloneCleanupWaiting(
                "cleanup_readonly_attribute_waiting"
            )

    def _open_chain(
        self,
        root: _Handle,
        components: list[str],
        manifest_index: Mapping[str, Mapping[str, object]],
        ancestor_hook: Callable[[str], None] | None = None,
    ) -> list[_Handle]:
        handles: list[_Handle] = []
        parent = root
        logical_parts: list[str] = []
        try:
            for component in components:
                logical_parts.append(component)
                logical = "/".join(logical_parts)
                expected = manifest_index.get(logical)
                if (
                    not isinstance(expected, Mapping)
                    or expected.get("type") != "directory"
                    or not isinstance(expected.get("identity"), Mapping)
                ):
                    raise CloneCleanupContractError(
                        "cleanup_ancestor_manifest_missing"
                    )
                child = _child_handle(
                    parent,
                    component,
                    directory=True,
                    exclusive=False,
                    delete=False,
                    sharing_mask=(
                        _FILE_SHARE_READ | _FILE_SHARE_WRITE
                    ),
                )
                handles.append(child)
                attributes, _standard = _attributes_and_standard(child)
                if (
                    not _same_identity(
                        _identity(child), expected["identity"]
                    )
                    or int(attributes.FileAttributes)
                    != expected.get("attributes")
                    or _streams(child)
                    != tuple(expected.get("streams", []))
                ):
                    raise CloneCleanupContractError(
                        "cleanup_ancestor_identity_changed"
                    )
                if ancestor_hook is not None:
                    ancestor_hook(logical)
                parent = child
            return handles
        except BaseException:
            for handle in reversed(handles):
                handle.close()
            raise

    def _delete_entry(
        self,
        root: _Handle,
        row: Mapping[str, object],
        *,
        manifest_index: Mapping[
            str, Mapping[str, object]
        ],
        allow_truncated: bool,
        guard: Callable[[], None] | None = None,
        ancestor_hook: Callable[[str], None] | None = None,
        fault_hook: FaultHook | None = None,
    ) -> str:
        logical = row.get("logical")
        expected_identity = row.get("identity")
        kind = row.get("type")
        if (
            not isinstance(logical, str)
            or not logical
            or not isinstance(expected_identity, dict)
            or kind not in {"file", "directory"}
        ):
            raise CloneCleanupContractError("cleanup_manifest_entry_invalid")
        components = logical.split("/")
        ancestors = self._open_chain(
            root,
            components[:-1],
            manifest_index,
            ancestor_hook,
        )
        parent = ancestors[-1] if ancestors else root
        target: _Handle | None = None
        readonly_cleared = False
        try:
            try:
                target = _child_handle(
                    parent,
                    components[-1],
                    directory=kind == "directory",
                    exclusive=True,
                    delete=True,
                )
            except CloneCleanupContractError as exc:
                if str(exc).endswith(f":{_ERROR_FILE_NOT_FOUND}"):
                    return "absent"
                raise
            except CloneCleanupWaiting as exc:
                expected_attributes = row.get("attributes")
                if (
                    kind != "file"
                    or not isinstance(expected_attributes, int)
                    or not expected_attributes
                    & _FILE_ATTRIBUTE_READONLY
                    or str(exc) != "cleanup_entry_handle_busy"
                ):
                    raise
                attribute_handle = _child_handle(
                    parent,
                    components[-1],
                    directory=False,
                    exclusive=True,
                    delete=True,
                    write_data=False,
                )
                try:
                    if not _same_identity(
                        _identity(attribute_handle),
                        expected_identity,
                    ):
                        raise CloneCleanupContractError(
                            "cleanup_entry_identity_changed"
                        )
                    attributes, standard = (
                        _attributes_and_standard(attribute_handle)
                    )
                    if (
                        int(attributes.FileAttributes)
                        != expected_attributes
                        or int(standard.EndOfFile)
                        != row.get("size")
                        or _streams(attribute_handle)
                        != tuple(row.get("streams", []))
                    ):
                        raise CloneCleanupContractError(
                            "cleanup_readonly_entry_changed"
                        )
                    self._clear_readonly(attribute_handle)
                    readonly_cleared = True
                finally:
                    attribute_handle.close()
                if fault_hook is not None:
                    fault_hook(
                        "after_readonly_cleared:" + logical
                    )
                target = _child_handle(
                    parent,
                    components[-1],
                    directory=False,
                    exclusive=True,
                    delete=True,
                )
            if not _same_identity(_identity(target), expected_identity):
                raise CloneCleanupContractError("cleanup_entry_identity_changed")
            attributes, standard = _attributes_and_standard(target)
            expected_attributes = row.get("attributes")
            allowed_attributes = {expected_attributes}
            if (
                kind == "file"
                and isinstance(expected_attributes, int)
                and expected_attributes & _FILE_ATTRIBUTE_READONLY
                and (readonly_cleared or allow_truncated)
            ):
                allowed_attributes.add(
                    expected_attributes & ~_FILE_ATTRIBUTE_READONLY
                )
            if int(attributes.FileAttributes) not in allowed_attributes:
                raise CloneCleanupContractError("cleanup_entry_attributes_changed")
            current_size = int(
                standard.EndOfFile if kind == "file" else 0
            )
            expected_size = row.get("size")
            if current_size != expected_size and not (
                kind == "file" and allow_truncated and current_size == 0
            ):
                raise CloneCleanupContractError("cleanup_entry_size_changed")
            if _streams(target) != tuple(row.get("streams", [])):
                raise CloneCleanupContractError("cleanup_entry_streams_changed")
            if kind == "directory" and _directory_has_entries(
                target, guard=guard
            ):
                raise CloneCleanupContractError("cleanup_directory_not_empty")
            if kind == "file":
                distance = ctypes.c_longlong(0)
                if (
                    not _kernel32.SetFilePointerEx(
                        target.value, 0, ctypes.byref(distance), 0
                    )
                    or not _kernel32.SetEndOfFile(target.value)
                    or not _kernel32.FlushFileBuffers(target.value)
                ):
                    raise CloneCleanupWaiting("cleanup_file_truncate_waiting")
            self._dispose(target)
            target.close()
            target = None
            for name, _is_dir, _attrs in _directory_rows(parent):
                if name == components[-1]:
                    raise CloneCleanupWaiting("cleanup_entry_still_present")
            return "deleted"
        finally:
            if target is not None:
                target.close()
            for handle in reversed(ancestors):
                handle.close()

    def _cleaned_receipt(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope_digest: str,
    ) -> dict[str, object] | None:
        raw = self._vault(mission_id).get_bytes()
        if raw is None:
            return None
        try:
            document = json.loads(raw)
            payload = self._verify_signed(document, PROVENANCE_SCHEMA)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            CloneCleanupContractError,
        ):
            return None
        if (
            payload.get("schema") != PROVENANCE_SCHEMA
            or payload.get("mission_id") != mission_id
            or payload.get("binding_digest") != binding_digest
            or payload.get("envelope_digest") != envelope_digest
            or payload.get("state") != "cleaned"
            or not isinstance(payload.get("nonce"), str)
            or len(str(payload["nonce"])) != 64
        ):
            return None
        return payload

    def cleanup(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope_digest: str,
        owner_root: str | os.PathLike[str],
        clone_root: str | os.PathLike[str],
        owner_git_sha256: str,
        terminal_state: str,
        checkpoint: Mapping[str, object],
        owner_validator: OwnerValidator,
        checkpoint_writer: CheckpointWriter,
        fault_hook: FaultHook | None = None,
        containment_handles: tuple[_Handle, _Handle] | None = None,
    ) -> bool:
        if not self.enabled:
            raise CloneCleanupContractError("cleanup_feature_disabled")
        if terminal_state not in {"succeeded", "failed", "cancelled"}:
            raise CloneCleanupWaiting("cleanup_terminal_gate_incomplete")
        if checkpoint.get("stage") not in {
            "bound",
            "clone_preparing",
            "verified",
            "cleanup_planned",
            "deleting",
            "finalizing",
            "root_removed",
            "cleaned",
            "clone_building",
            "clone_ready",
            "patch_applied",
            "gates_running",
        }:
            raise CloneCleanupWaiting("cleanup_checkpoint_incomplete")
        if (
            checkpoint.get("mission_id") != mission_id
            or checkpoint.get("binding_digest") != binding_digest
            or checkpoint.get("owner_git_sha256") != owner_git_sha256
        ):
            raise CloneCleanupContractError("cleanup_checkpoint_binding_mismatch")
        cleaned_receipt = self._cleaned_receipt(
            mission_id=mission_id,
            binding_digest=binding_digest,
            envelope_digest=envelope_digest,
        )
        if cleaned_receipt is not None:
            owner_validator()
            handles_context = (
                self._mission_handles(mission_id, containment=True)
                if containment_handles is None
                else contextlib.nullcontext(containment_handles)
            )
            with handles_context as (
                _worktree_handle,
                mission_handle,
            ):
                tombstone = (
                    f".onyx-cleanup-{str(cleaned_receipt['nonce'])[:16]}"
                )
                if any(
                    name in {"clone", tombstone}
                    for name, _is_directory, _attrs in _directory_rows(
                        mission_handle
                    )
                ):
                    raise CloneCleanupContractError(
                        "cleanup_cleaned_absence_violated"
                    )
                checkpoint_writer("cleaned", None)
                for name in (
                    "clone.cleanup.journal.v1.json",
                    "clone.cleanup.manifest.v1.json",
                    *_PROVENANCE_SLOTS,
                ):
                    self._metadata_delete(mission_handle, name)
            return False
        started = self._clock()

        def cleanup_time_guard() -> None:
            if self._clock() - started > self.limits.max_seconds:
                raise CloneCleanupWaiting("cleanup_time_quota_exceeded")

        owner_validator()
        handles_context = (
            self._mission_handles(mission_id, containment=True)
            if containment_handles is None
            else contextlib.nullcontext(containment_handles)
        )
        with handles_context as (
            _worktree_handle,
            mission_handle,
        ):
            journal_raw = self._metadata_read(
                mission_handle,
                "clone.cleanup.journal.v1.json",
                required=False,
            )
            journal: dict[str, object] | None = None
            if journal_raw is not None:
                try:
                    journal_document = json.loads(journal_raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise CloneCleanupContractError(
                        "cleanup_journal_invalid"
                    ) from exc
                journal = self._verify_signed(
                    journal_document, JOURNAL_SCHEMA
                )
            journal_state = (
                str(journal.get("state")) if journal is not None else ""
            )
            provenance = self.authenticate_provenance(
                mission_id=mission_id,
                binding_digest=binding_digest,
                envelope_digest=envelope_digest,
                owner_root=owner_root,
                clone_root=clone_root,
                owner_git_sha256=owner_git_sha256,
                allow_tombstone=True,
                allow_absent=journal_state in {
                    "finalizing",
                    "root_removed",
                },
                containment_handles=(
                    _worktree_handle,
                    mission_handle,
                ),
            )
            nonce = provenance.get("nonce")
            if not isinstance(nonce, str) or len(nonce) != 64:
                raise CloneCleanupContractError(
                    "cleanup_provenance_nonce_invalid"
                )
            tombstone = f".onyx-cleanup-{nonce[:16]}"
            expected = provenance.get("clone_root")
            if not isinstance(expected, dict) or not isinstance(
                expected.get("identity"), dict
            ):
                raise CloneCleanupContractError(
                    "cleanup_provenance_root_invalid"
                )
            expected_identity = expected["identity"]
            candidate_name: str | None = None
            for name, is_directory, _attrs in _directory_rows(mission_handle):
                if not is_directory or name not in {"clone", tombstone}:
                    continue
                with _child_handle(
                    mission_handle,
                    name,
                    directory=True,
                    exclusive=False,
                    delete=False,
                ) as candidate:
                    if not _same_identity(_identity(candidate), expected_identity):
                        if name == tombstone:
                            continue
                        raise CloneCleanupContractError(
                            "cleanup_provenance_identity_mismatch"
                        )
                if candidate_name is not None:
                    raise CloneCleanupContractError(
                        "cleanup_clone_identity_ambiguous"
                    )
                candidate_name = name
            manifest_payload: dict[str, object]
            manifest_digest: str
            completed: list[str]
            current: str | None
            root_identity = dict(expected_identity)
            if journal is None:
                if candidate_name != "clone":
                    raise CloneCleanupContractError(
                        "cleanup_clone_identity_absent"
                    )
                with _child_handle(
                    mission_handle,
                    "clone",
                    directory=True,
                    exclusive=True,
                    delete=True,
                ) as clone_handle:
                    current_clone = _validate_volume(clone_handle)
                    if (
                        not _same_identity(
                            current_clone, expected_identity
                        )
                        or current_clone.resolved_path
                        != expected_identity.get("resolved_path")
                    ):
                        raise CloneCleanupContractError(
                            "cleanup_clone_identity_changed_before_manifest"
                        )
                    manifest_payload = self._manifest_payload(
                        mission_id=mission_id,
                        nonce=nonce,
                        root=clone_handle,
                        started=started,
                    )
                    self._write_signed(
                        mission_handle,
                        "clone.cleanup.manifest.v1.json",
                        manifest_payload,
                    )
                    encoded_manifest = self._metadata_read(
                        mission_handle,
                        "clone.cleanup.manifest.v1.json",
                    )
                    assert encoded_manifest is not None
                    manifest_digest = hashlib.sha256(
                        encoded_manifest
                    ).hexdigest()
                    completed = []
                    current = None
                    self._journal(
                        mission=mission_handle,
                        mission_id=mission_id,
                        nonce=nonce,
                        manifest_digest=manifest_digest,
                        state="planned",
                        tombstone=tombstone,
                        root_identity=root_identity,
                        completed=completed,
                        current=current,
                    )
                    checkpoint_writer("cleanup_planned", manifest_digest)
                    if fault_hook is not None:
                        fault_hook("after_cleanup_planned")
                    self._rename_by_handle(
                        clone_handle, mission_handle, tombstone
                    )
                    self._journal(
                        mission=mission_handle,
                        mission_id=mission_id,
                        nonce=nonce,
                        manifest_digest=manifest_digest,
                        state="deleting",
                        tombstone=tombstone,
                        root_identity=root_identity,
                        completed=completed,
                        current=current,
                    )
                    checkpoint_writer("deleting", manifest_digest)
                    if fault_hook is not None:
                        fault_hook("after_tombstone_rename")
                candidate_name = tombstone
                journal_state = "deleting"
            else:
                encoded_manifest = self._metadata_read(
                    mission_handle,
                    "clone.cleanup.manifest.v1.json",
                )
                assert encoded_manifest is not None
                try:
                    manifest_document = json.loads(encoded_manifest)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise CloneCleanupContractError(
                        "cleanup_manifest_invalid"
                    ) from exc
                manifest_payload = self._verify_signed(
                    manifest_document, MANIFEST_SCHEMA
                )
                manifest_digest = hashlib.sha256(
                    encoded_manifest
                ).hexdigest()
                if (
                    journal.get("mission_id") != mission_id
                    or journal.get("nonce") != nonce
                    or journal.get("manifest_digest") != manifest_digest
                    or journal.get("tombstone") != tombstone
                    or journal.get("root_identity") != root_identity
                    or journal_state
                    not in {
                        "planned",
                        "deleting",
                        "finalizing",
                        "root_removed",
                    }
                ):
                    raise CloneCleanupContractError(
                        "cleanup_journal_mismatch"
                    )
                raw_completed = journal.get("completed")
                current_value = journal.get("current")
                if (
                    not isinstance(raw_completed, list)
                    or any(
                        not isinstance(item, str) for item in raw_completed
                    )
                    or current_value is not None
                    and not isinstance(current_value, str)
                ):
                    raise CloneCleanupContractError(
                        "cleanup_journal_progress_invalid"
                    )
                completed = list(raw_completed)
                current = current_value
                if journal_state == "planned":
                    if candidate_name == "clone":
                        with _child_handle(
                            mission_handle,
                            "clone",
                            directory=True,
                            exclusive=True,
                            delete=True,
                        ) as clone_handle:
                            current_clone = _validate_volume(
                                clone_handle
                            )
                            if (
                                not _same_identity(
                                    current_clone,
                                    expected_identity,
                                )
                                or current_clone.resolved_path
                                != expected_identity.get(
                                    "resolved_path"
                                )
                            ):
                                raise CloneCleanupContractError(
                                    "cleanup_clone_identity_changed_before_rename"
                                )
                            self._rename_by_handle(
                                clone_handle, mission_handle, tombstone
                            )
                    elif candidate_name != tombstone:
                        raise CloneCleanupContractError(
                            "cleanup_clone_identity_absent"
                        )
                    journal_state = "deleting"
                    candidate_name = tombstone
                    self._journal(
                        mission=mission_handle,
                        mission_id=mission_id,
                        nonce=nonce,
                        manifest_digest=manifest_digest,
                        state=journal_state,
                        tombstone=tombstone,
                        root_identity=root_identity,
                        completed=completed,
                        current=current,
                    )
                if (
                    manifest_payload.get("mission_id") != mission_id
                    or manifest_payload.get("nonce") != nonce
                    or not isinstance(manifest_payload.get("entries"), list)
                ):
                    raise CloneCleanupContractError(
                        "cleanup_manifest_binding_mismatch"
                    )
            manifest_entries = manifest_payload["entries"]
            assert isinstance(manifest_entries, list)
            root_rows = [
                row
                for row in manifest_entries
                if isinstance(row, dict) and row.get("logical") == ""
            ]
            if len(root_rows) != 1 or root_rows[0].get(
                "identity"
            ) != root_identity:
                raise CloneCleanupContractError(
                    "cleanup_manifest_root_mismatch"
                )
            ordered = sorted(
                (
                    row
                    for row in manifest_entries
                    if isinstance(row, dict) and row.get("logical")
                ),
                key=lambda row: int(row.get("depth", -1)),
                reverse=True,
            )
            manifest_index = {
                str(row.get("logical")): row
                for row in manifest_entries
                if isinstance(row, dict)
            }
            if len(manifest_index) != len(manifest_entries):
                raise CloneCleanupContractError(
                    "cleanup_manifest_logical_duplicate"
                )
            if journal_state == "deleting":
                if candidate_name != tombstone:
                    raise CloneCleanupContractError(
                        "cleanup_tombstone_identity_absent"
                    )
                with _child_handle(
                    mission_handle,
                    tombstone,
                    directory=True,
                    exclusive=True,
                    delete=True,
                ) as clone_handle:
                    if not _same_identity(
                        _identity(clone_handle), root_identity
                    ):
                        raise CloneCleanupContractError(
                            "cleanup_manifest_root_mismatch"
                        )
                    owner_validator()
                    completed_set = set(completed)
                    if len(completed_set) != len(completed):
                        raise CloneCleanupContractError(
                            "cleanup_journal_progress_invalid"
                        )
                    known = {
                        str(row.get("logical")) for row in ordered
                    }
                    if not completed_set.issubset(known) or (
                        current is not None and current not in known
                    ):
                        raise CloneCleanupContractError(
                            "cleanup_journal_progress_invalid"
                        )
                    resume_current = current
                    for row in ordered:
                        logical = str(row.get("logical"))
                        if logical in completed_set:
                            continue
                        if (
                            self._clock() - started
                            > self.limits.max_seconds
                        ):
                            raise CloneCleanupWaiting(
                                "cleanup_time_quota_exceeded"
                            )
                        current = logical
                        self._journal(
                            mission=mission_handle,
                            mission_id=mission_id,
                            nonce=nonce,
                            manifest_digest=manifest_digest,
                            state="deleting",
                            tombstone=tombstone,
                            root_identity=root_identity,
                            completed=completed,
                            current=current,
                        )
                        if fault_hook is not None:
                            fault_hook(f"before_entry:{logical}")
                        self._delete_entry(
                            clone_handle,
                            row,
                            manifest_index=manifest_index,
                            allow_truncated=resume_current == logical,
                            guard=cleanup_time_guard,
                            fault_hook=fault_hook,
                            ancestor_hook=(
                                None
                                if fault_hook is None
                                else lambda ancestor: fault_hook(
                                    "after_ancestor_validation:"
                                    + ancestor
                                )
                            ),
                        )
                        resume_current = None
                        completed.append(logical)
                        completed_set.add(logical)
                        current = None
                        self._journal(
                            mission=mission_handle,
                            mission_id=mission_id,
                            nonce=nonce,
                            manifest_digest=manifest_digest,
                            state="deleting",
                            tombstone=tombstone,
                            root_identity=root_identity,
                            completed=completed,
                            current=current,
                        )
                        if fault_hook is not None:
                            fault_hook(f"after_entry:{logical}")
                    owner_validator()
                    self._journal(
                        mission=mission_handle,
                        mission_id=mission_id,
                        nonce=nonce,
                        manifest_digest=manifest_digest,
                        state="finalizing",
                        tombstone=tombstone,
                        root_identity=root_identity,
                        completed=completed,
                        current=None,
                    )
                    checkpoint_writer("finalizing", manifest_digest)
                    if fault_hook is not None:
                        fault_hook("before_root_disposition")
                    self._dispose(clone_handle)
                journal_state = "finalizing"
            elif journal_state == "finalizing" and candidate_name == tombstone:
                with _child_handle(
                    mission_handle,
                    tombstone,
                    directory=True,
                    exclusive=True,
                    delete=True,
                ) as clone_handle:
                    if not _same_identity(
                        _identity(clone_handle), root_identity
                    ):
                        raise CloneCleanupContractError(
                            "cleanup_manifest_root_mismatch"
                        )
                    if _directory_has_entries(
                        clone_handle,
                        guard=cleanup_time_guard,
                    ):
                        raise CloneCleanupContractError(
                            "cleanup_finalizing_root_not_empty"
                        )
                    owner_validator()
                    self._dispose(clone_handle)
            present_names = {
                name
                for name, _is_directory, _attrs in _directory_rows(
                    mission_handle
                )
                if name in {"clone", tombstone}
            }
            if present_names:
                raise CloneCleanupWaiting("cleanup_final_absence_unproven")
            if journal_state not in {"finalizing", "root_removed"}:
                raise CloneCleanupContractError(
                    "cleanup_final_state_invalid"
                )
            worktree_record = provenance.get("worktree_root")
            mission_record = provenance.get("mission_root")
            if (
                not isinstance(worktree_record, dict)
                or not isinstance(worktree_record.get("identity"), dict)
                or not isinstance(mission_record, dict)
                or not isinstance(mission_record.get("identity"), dict)
            ):
                raise CloneCleanupContractError(
                    "cleanup_provenance_root_invalid"
                )
            final_worktree = _validate_volume(_worktree_handle)
            final_mission = _validate_volume(mission_handle)
            if (
                not _same_identity(
                    final_worktree, worktree_record["identity"]
                )
                or final_worktree.resolved_path
                != worktree_record["identity"].get("resolved_path")
                or not _same_identity(
                    final_mission, mission_record["identity"]
                )
                or final_mission.resolved_path
                != mission_record["identity"].get("resolved_path")
            ):
                raise CloneCleanupContractError(
                    "cleanup_final_containment_changed"
                )
            self._journal(
                mission=mission_handle,
                mission_id=mission_id,
                nonce=nonce,
                manifest_digest=manifest_digest,
                state="root_removed",
                tombstone=tombstone,
                root_identity=root_identity,
                completed=completed,
                current=None,
            )
            checkpoint_writer("root_removed", manifest_digest)
            owner_validator()
            cleaned_anchor = _canonical(
                self._sign(
                    {
                        "schema": PROVENANCE_SCHEMA,
                        "mission_id": mission_id,
                        "binding_digest": binding_digest,
                        "envelope_digest": envelope_digest,
                        "state": "cleaned",
                        "nonce": nonce,
                    }
                )
            )
            vault = self._vault(mission_id)
            vault.set_bytes(cleaned_anchor)
            readback = vault.get_bytes()
            if readback is None or not hmac.compare_digest(
                readback, cleaned_anchor
            ):
                raise CloneCleanupContractError(
                    "cleanup_cleaned_anchor_write_failed"
                )
            if fault_hook is not None:
                fault_hook("after_cleaned_anchor")
            checkpoint_writer("cleaned", manifest_digest)
            for name in (
                "clone.cleanup.journal.v1.json",
                "clone.cleanup.manifest.v1.json",
                *_PROVENANCE_SLOTS,
            ):
                self._metadata_delete(mission_handle, name)
        return True
