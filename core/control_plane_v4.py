"""Default-off, externally anchored schema-v4 successor for mission context.

Schema v3 remains an immutable archival source.  This module publishes a new
SQLite database atomically and never changes, copies over, or re-opens the v3
authority tables for writes.  It is intentionally absent from application
startup; the only current constructor is the sealed fixture/test opener.
This same-process Python fixture is not a security boundary; its typed surface
prevents accidental cursor escape while production operational opening remains
unavailable.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import threading
import time
import uuid
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping, Protocol, runtime_checkable

from core import ledger_anchor
from core.control_plane_v3 import (
    ControlPlaneV3Error,
    V3OwnerCapability,
    _ControlPlaneV3Migrator,
    _open_canonical_connection,
    _entry_merkle_tree,
    _entry_merkle_leaf,
    _merkle_parent,
    _mmr_bag,
    _mmr_leaf,
    _mmr_parent,
    _operational_commit_id,
    _operational_delta_digest,
    _operational_payload_root,
    _operational_state_root,
    _typed_record_digest,
    _validate_v3_exact,
)
from core.mission_context_contracts import (
    MissionContextContractError,
    PHASES as _V4_PHASES,
    parse_context_json,
    validate_storage_transition,
)
from memory.store import _harden_mode, _is_reparse, _reject_special


CONTROL_PLANE_V4_FLAG = "ONYX_CONTROL_PLANE_V4"
V4_SCHEMA_VERSION = 4
V4_MIGRATION_ID = "M4-P4.3-MISSION-CONTEXT-V1"
_TRUE = frozenset({"1", "true", "yes", "on"})
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}")
_LOCK = threading.RLock()
_EVENT_PROOF_BATCH = 128
_MAX_V3_CAPTURE_BYTES = 256 * 1024 * 1024
_TRUSTED_WRITE_CHUNK = 1024 * 1024


def _database_page_bytes(connection: sqlite3.Connection) -> int:
    """Return SQLite's allocated bytes without materializing the database."""
    return int(connection.execute("PRAGMA page_count").fetchone()[0]) * int(
        connection.execute("PRAGMA page_size").fetchone()[0]
    )
_CAPABILITY_SEAL = object()
_CAPABILITIES: weakref.WeakKeyDictionary[V4OwnerCapability, bytes] = (
    weakref.WeakKeyDictionary()
)


class ControlPlaneV4Error(RuntimeError):
    pass


class ControlPlaneV4Disabled(ControlPlaneV4Error):
    pass


class ControlPlaneV4IntegrityError(ControlPlaneV4Error):
    pass


class ControlPlaneV4Conflict(ControlPlaneV4Error):
    pass


class ControlPlaneV4IOError(ControlPlaneV4Error):
    pass


def _attempt_cleanup(
    failures: list[BaseException], action: Callable[[], object]
) -> None:
    try:
        action()
    except BaseException as exc:
        failures.append(exc)


def _finish_cleanup(
    label: str,
    failures: list[BaseException],
    primary: BaseException | None,
) -> None:
    if not failures:
        return
    detail = "; ".join(
        f"{index + 1}:{type(exc).__name__}:{exc}"
        for index, exc in enumerate(failures)
    )
    if primary is not None:
        primary.add_note(f"{label} cleanup failures: {detail}")
        return
    failure = ControlPlaneV4IntegrityError(f"{label} cleanup failed")
    failure.add_note(f"cleanup failures: {detail}")
    raise failure from failures[0]


def control_plane_v4_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return str(source.get(CONTROL_PLANE_V4_FLAG, "")).strip().casefold() in _TRUE


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _secure_identity(path: Path, *, label: str) -> tuple[int, int, int, int]:
    try:
        before = path.lstat()
        if (
            path.is_symlink()
            or _is_reparse(path)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        ):
            raise ControlPlaneV4IntegrityError(f"{label} must be one regular unlinked file")
        return before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
    except ControlPlaneV4Error:
        raise
    except OSError:
        raise ControlPlaneV4IOError(f"{label} identity is unavailable") from None


def _private_sidecar_identity(
    path: Path, *, volatile: bool
) -> tuple[int, int] | None:
    """Reject aliases while tolerating bounded Windows WAL/SHM delete-pending gaps."""
    transient = os.name == "nt" and volatile
    attempts = 8 if transient else 2
    deadline = time.monotonic() + 0.025
    for attempt in range(attempts):
        try:
            observed = path.lstat()
        except FileNotFoundError:
            if transient or attempt:
                return None
            continue
        if (
            stat.S_ISLNK(observed.st_mode)
            or _is_reparse(path)
            or not stat.S_ISREG(observed.st_mode)
        ):
            raise ControlPlaneV4IntegrityError(
                "v4 database sidecar must be a private regular file"
            )
        if observed.st_nlink == 1:
            return int(observed.st_dev), int(observed.st_ino)
        if observed.st_nlink > 1 or not transient:
            raise ControlPlaneV4IntegrityError(
                "v4 database sidecar must be a private regular file"
            )
        if attempt + 1 >= attempts or time.monotonic() >= deadline:
            return None
        time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))
    return None


def _file_sha256(path: Path, *, label: str = "v3 snapshot") -> str:
    try:
        expected = _secure_identity(path, label=label)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if opened.st_nlink != 1 or (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            ) != expected:
                raise ControlPlaneV4IntegrityError(f"{label} identity changed")
            hasher = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
            if _secure_identity(path, label=label) != expected:
                raise ControlPlaneV4IntegrityError(f"{label} changed while hashing")
            return hasher.hexdigest()
        finally:
            os.close(descriptor)
    except ControlPlaneV4Error:
        raise
    except OSError:
        raise ControlPlaneV4IOError(f"{label} could not be read") from None


class _TrustedDirectory:
    """Pinned directory capability used for capture and atomic publication.

    All temporary creation, removal, and publication is descriptor/handle
    relative.  No source-derived byte is written until construction has walked
    every existing component without following a link or reparse point.
    """

    def __init__(self, path: Path):
        self.path = Path(os.path.abspath(path))
        self._fd: int | None = None
        self._fd_chain: list[int] = []
        self._handle: int | None = None
        self._handle_chain: list[int] = []
        self._components: list[str] = []
        self._windows_full_fallbacks: set[int] = set()
        self._windows_anchor_path: Path | None = None
        self._temp_guardians: dict[int, int] = {}
        self._temp_delete_capable: set[int] = set()
        self._anchor_open_fault: Callable[[str, int], None] | None = None
        self._identity: tuple[int, ...] | None = None
        if os.name == "nt":
            self._open_windows()
        else:
            self._open_posix()

    def __enter__(self) -> "_TrustedDirectory":
        return self

    def __exit__(self, _kind, _value, _traceback) -> None:
        self.close()

    def _open_posix(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        current = os.open(self.path.anchor or os.sep, flags | nofollow)
        try:
            self._fd_chain.append(current)
            for component in self.path.parts[1:]:
                if component in {"", os.sep}:
                    continue
                try:
                    child = os.open(component, flags | nofollow, dir_fd=current)
                except FileNotFoundError:
                    os.mkdir(component, 0o700, dir_fd=current)
                    child = os.open(component, flags | nofollow, dir_fd=current)
                observed = os.fstat(child)
                if not stat.S_ISDIR(observed.st_mode):
                    os.close(child)
                    raise ControlPlaneV4IntegrityError(
                        "v4 trusted directory component is not a directory"
                    )
                current = child
                self._components.append(component)
                self._fd_chain.append(current)
            os.fchmod(current, 0o700)
            observed = os.fstat(current)
            self._identity = (observed.st_dev, observed.st_ino)
            self._fd = current
            current = -1
        except BaseException:
            for opened in reversed(self._fd_chain):
                os.close(opened)
            self._fd_chain.clear()
            raise

    @staticmethod
    def _windows_api():
        import ctypes
        from ctypes import wintypes

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

        class FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
            _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

        return ctypes, wintypes, UNICODE_STRING, OBJECT_ATTRIBUTES, IO_STATUS_BLOCK, BY_HANDLE_FILE_INFORMATION, FILE_ATTRIBUTE_TAG_INFO

    @classmethod
    def _win_identity(cls, handle: int, *, directory: bool) -> tuple[int, ...]:
        (
            ctypes, wintypes, _unicode, _attributes, _iosb,
            information_type, tag_type,
        ) = cls._windows_api()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        info = information_type()
        if kernel32.GetFileInformationByHandle(
            wintypes.HANDLE(handle), ctypes.byref(info)
        ):
            tag = tag_type()
            if not kernel32.GetFileInformationByHandleEx(
                wintypes.HANDLE(handle), 9, ctypes.byref(tag), ctypes.sizeof(tag)
            ):
                raise ControlPlaneV4IntegrityError(
                    "v4 trusted Windows reparse identity is unavailable"
                )
            attributes = int(tag.FileAttributes)
            links = int(info.nNumberOfLinks)
            is_directory = bool(info.dwFileAttributes & 0x10)
            identity = (
                int(info.dwVolumeSerialNumber),
                (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow),
                links,
                attributes,
            )
        else:
            # Hardened user-profile ACLs may deny FILE_READ_ATTRIBUTES on an
            # ancestor even though traversal itself is allowed.  NT's handle
            # queries provide the same no-path identity on a SYNCHRONIZE-only
            # handle without weakening no-reparse traversal.
            class FILE_INTERNAL_INFORMATION(ctypes.Structure):
                _fields_ = [("IndexNumber", ctypes.c_longlong)]

            class FILE_STANDARD_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("AllocationSize", ctypes.c_longlong),
                    ("EndOfFile", ctypes.c_longlong),
                    ("NumberOfLinks", wintypes.ULONG),
                    ("DeletePending", ctypes.c_ubyte),
                    ("Directory", ctypes.c_ubyte),
                ]

            ntdll = ctypes.WinDLL("ntdll")
            internal = FILE_INTERNAL_INFORMATION()
            standard = FILE_STANDARD_INFORMATION()
            queries = (
                (internal, 6),  # FileInternalInformation
                (standard, 5),  # FileStandardInformation
            )
            for value, information_class in queries:
                iosb = _iosb()
                status = ntdll.NtQueryInformationFile(
                    wintypes.HANDLE(handle), ctypes.byref(iosb),
                    ctypes.byref(value), ctypes.sizeof(value), information_class,
                )
                if int(status) < 0:
                    raise ControlPlaneV4IntegrityError(
                        "v4 trusted Windows native identity is unavailable "
                        f"(class={information_class},ntstatus="
                        f"0x{int(status) & 0xffffffff:08x})"
                    )
            returned = wintypes.DWORD()
            reparse_buffer = ctypes.create_string_buffer(16 * 1024)
            is_reparse = bool(kernel32.DeviceIoControl(
                wintypes.HANDLE(handle),
                0x000900A8,  # FSCTL_GET_REPARSE_POINT
                None, 0, reparse_buffer, ctypes.sizeof(reparse_buffer),
                ctypes.byref(returned), None,
            ))
            if not is_reparse and ctypes.get_last_error() != 4390:
                raise ControlPlaneV4IntegrityError(
                    "v4 trusted Windows reparse status is unavailable"
                )
            attributes = (0x10 if bool(standard.Directory) else 0) | (
                0x400 if is_reparse else 0
            )
            links = int(standard.NumberOfLinks)
            is_directory = bool(standard.Directory)
            identity = (0, int(internal.IndexNumber), links, attributes)
        if (
            bool(attributes & 0x400)
            or is_directory != directory
            or (not directory and links != 1)
        ):
            raise ControlPlaneV4IntegrityError(
                "v4 trusted Windows handle is linked or has the wrong type"
            )
        return identity

    @staticmethod
    def _win_exact_final_path(handle: int, expected: Path) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetFinalPathNameByHandleW(
            wintypes.HANDLE(handle), buffer, len(buffer), 0
        )
        if not length or length >= len(buffer):
            return False
        observed = buffer.value
        if observed.startswith("\\\\?\\UNC\\"):
            observed = "\\\\" + observed[8:]
        elif observed.startswith("\\\\?\\") or observed.startswith("\\??\\"):
            observed = observed[4:]
        def normalize(value: object) -> str:
            return os.path.normcase(os.path.normpath(os.path.abspath(str(value))))

        return normalize(observed) == normalize(expected)

    @classmethod
    def _nt_open_relative(
        cls,
        root: int,
        name: str,
        *,
        directory: bool,
        create: bool = False,
        open_if_missing: bool = False,
        delete_access: bool = False,
        share_delete: bool = False,
    ) -> int:
        if not name or name in {".", ".."} or "\\" in name or "/" in name:
            raise ControlPlaneV4IntegrityError("v4 relative Windows name is invalid")
        (
            ctypes, wintypes, unicode_type, attributes_type, iosb_type,
            _information, _tag,
        ) = cls._windows_api()
        ntdll = ctypes.WinDLL("ntdll")
        buffer = ctypes.create_unicode_buffer(name)
        unicode_name = unicode_type(
            len(name.encode("utf-16-le")),
            len(name.encode("utf-16-le")) + 2,
            ctypes.cast(buffer, wintypes.LPWSTR),
        )
        attributes = attributes_type(
            ctypes.sizeof(attributes_type),
            wintypes.HANDLE(root),
            ctypes.pointer(unicode_name),
            0x40,
            None,
            None,
        )
        iosb = iosb_type()
        handle = wintypes.HANDLE()
        access = 0x00000020 if directory else 0x00100000
        if not directory:
            access |= 0x80000000 | 0x40000000
        if delete_access:
            access |= 0x00010000
        options = 0x00200000 | (0x1 if directory else (0x40 | 0x20))
        if create and open_if_missing:
            raise ControlPlaneV4IntegrityError(
                "v4 relative Windows creation mode is invalid"
            )
        disposition = 3 if open_if_missing else (2 if create else 1)
        status = ntdll.NtCreateFile(
            ctypes.byref(handle), access, ctypes.byref(attributes), ctypes.byref(iosb),
            None, 0x80 if not directory else 0x10,
            0x1 | 0x2 | (0x4 if share_delete else 0),
            disposition, options, None, 0,
        )
        if int(status) < 0 or not handle.value:
            ntstatus = int(status) & 0xFFFFFFFF
            if (
                not directory
                and not create
                and not open_if_missing
                and ntstatus in {0xC0000034, 0xC000003A}
            ):
                raise FileNotFoundError(name)
            raise ControlPlaneV4IntegrityError(
                "v4 native Windows relative open/create failed "
                f"(ntstatus=0x{ntstatus:08x})"
            )
        try:
            cls._win_identity(int(handle.value), directory=directory)
            return int(handle.value)
        except BaseException:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)
            raise

    def _open_windows(self) -> None:
        import ctypes
        import tempfile
        from ctypes import wintypes

        drive, tail = os.path.splitdrive(str(self.path))
        if not drive or drive.startswith("\\\\"):
            raise ControlPlaneV4IntegrityError(
                "v4 trusted Windows directory requires a local drive"
            )
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        requested_components = [
            component for component in Path(tail).parts
            if component not in {"", "\\", "/"}
        ]
        anchor_path = Path(f"{drive}\\")
        components = requested_components
        try:
            temp_root = Path(os.path.abspath(tempfile.gettempdir()))
            self.path.relative_to(temp_root)
        except ValueError:
            temp_root = None
        if temp_root is not None:
            # Windows can deny every directory-handle access mask (including
            # access 0) at the protected user-profile boundary.  For the OS
            # per-user temp tree, pin the deepest existing directory directly
            # with OPEN_REPARSE_POINT, validate every absolute ancestor before
            # that acquisition, and create every missing descendant relative
            # to the pinned handle.  `_assert_path_binding` reopens this exact
            # anchor and compares file IDs before any bytes and at every seam.
            anchor_path = self.path
            while not anchor_path.exists() and anchor_path != temp_root:
                anchor_path = anchor_path.parent
            if not anchor_path.exists() or anchor_path == anchor_path.parent:
                raise ControlPlaneV4IntegrityError(
                    "v4 trusted Windows temporary anchor is unavailable"
                )
            for prefix_path in reversed(anchor_path.parents):
                if prefix_path == Path(f"{drive}\\"):
                    continue
                try:
                    observed = prefix_path.lstat()
                except OSError:
                    raise ControlPlaneV4IntegrityError(
                        "v4 trusted Windows temporary ancestor is unavailable"
                    ) from None
                if not stat.S_ISDIR(observed.st_mode) or _is_reparse(prefix_path):
                    raise ControlPlaneV4IntegrityError(
                        "v4 trusted Windows temporary ancestor is linked"
                    )
            components = list(self.path.relative_to(anchor_path).parts)
        self._windows_anchor_path = anchor_path
        handle = kernel32.CreateFileW(
            str(anchor_path), 0x00000020 | 0x00000080,
            0x1 | 0x2 | (0x4 if components else 0), None, 3,
            0x02000000 | 0x00200000, None,
        )
        invalid = ctypes.c_void_p(-1).value
        if not handle or int(handle) == invalid:
            raise ControlPlaneV4IntegrityError("v4 trusted Windows root open failed")
        current = int(handle)
        prefix = str(anchor_path)
        try:
            self._win_identity(current, directory=True)
            if not self._win_exact_final_path(current, anchor_path):
                raise ControlPlaneV4IntegrityError(
                    "v4 trusted Windows anchor resolved to another directory"
                )
            self._handle_chain.append(current)
            for index, component in enumerate(components):
                if component in {"", "\\", "/"}:
                    continue
                intermediate = index < len(components) - 1
                try:
                    child = self._nt_open_relative(
                        current,
                        component,
                        directory=True,
                        share_delete=intermediate,
                    )
                except ControlPlaneV4IntegrityError as exc:
                    if "ntstatus=0xc0000022" in str(exc):
                        full = os.path.join(prefix, component)
                        child_handle = kernel32.CreateFileW(
                            full,
                            0x00000020 | 0x00000080,
                            0x1 | 0x2 | (0x4 if intermediate else 0),
                            None,
                            3,
                            0x02000000 | 0x00200000,
                            None,
                        )
                        if not child_handle or int(child_handle) == invalid:
                            child_handle = kernel32.CreateFileW(
                                full, 0,
                                0x1 | 0x2 | (0x4 if intermediate else 0),
                                None, 3, 0x02000000 | 0x00200000, None,
                            )
                        followed_fallback = False
                        if not child_handle or int(child_handle) == invalid:
                            child_handle = kernel32.CreateFileW(
                                full, 0,
                                0x1 | 0x2 | (0x4 if intermediate else 0),
                                None, 3, 0x02000000, None,
                            )
                            followed_fallback = bool(
                                child_handle and int(child_handle) != invalid
                            )
                        if not child_handle or int(child_handle) == invalid:
                            raise ControlPlaneV4IntegrityError(
                                "v4 Win32 ancestor fallback failed "
                                f"(winerror={ctypes.get_last_error()})"
                            ) from None
                        child = int(child_handle)
                        try:
                            if followed_fallback:
                                observed = Path(full).lstat()
                                if (
                                    not stat.S_ISDIR(observed.st_mode)
                                    or _is_reparse(Path(full))
                                    or not self._win_exact_final_path(child, Path(full))
                                ):
                                    raise ControlPlaneV4IntegrityError(
                                        "v4 Win32 ancestor fallback followed a link"
                                    )
                            self._win_identity(child, directory=True)
                        except BaseException:
                            kernel32.CloseHandle(wintypes.HANDLE(child))
                            raise
                        self._windows_full_fallbacks.add(index)
                    else:
                        try:
                            child = self._nt_open_relative(
                                current,
                                component,
                                directory=True,
                                create=True,
                                share_delete=intermediate,
                            )
                        except ControlPlaneV4IntegrityError:
                            # A concurrent creator can win between FILE_OPEN and
                            # FILE_CREATE.  Re-open only through the pinned parent.
                            child = self._nt_open_relative(
                                current,
                                component,
                                directory=True,
                                share_delete=intermediate,
                            )
                current = child
                prefix = os.path.join(prefix, component)
                self._components.append(component)
                self._handle_chain.append(current)
            self._identity = self._win_identity(current, directory=True)
            if not self._win_exact_final_path(current, self.path):
                raise ControlPlaneV4IntegrityError(
                    "v4 trusted Windows final directory resolved elsewhere"
                )
            self._handle = current
            current = 0
        finally:
            if current:
                for opened in reversed(self._handle_chain or [current]):
                    kernel32.CloseHandle(wintypes.HANDLE(opened))
                self._handle_chain.clear()

    def _assert_path_binding(self) -> None:
        """Prove that every pinned parent/name edge still names our handle."""
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            if not self._handle_chain:
                raise ControlPlaneV4IntegrityError("v4 trusted directory is closed")
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if self._windows_anchor_path is None:
                raise ControlPlaneV4IntegrityError("v4 trusted directory is closed")
            prefix = str(self._windows_anchor_path)
            kernel32.CreateFileW.restype = wintypes.HANDLE
            root = kernel32.CreateFileW(
                prefix, 0x00000020 | 0x00000080,
                0x1 | 0x2 | (0x4 if self._components else 0), None, 3,
                0x02000000 | 0x00200000, None,
            )
            invalid = ctypes.c_void_p(-1).value
            if not root or int(root) == invalid:
                raise ControlPlaneV4IntegrityError(
                    "v4 trusted directory anchor binding changed"
                )
            try:
                if self._win_identity(int(root), directory=True) != self._win_identity(
                    self._handle_chain[0], directory=True
                ) or not self._win_exact_final_path(int(root), self._windows_anchor_path):
                    raise ControlPlaneV4IntegrityError(
                        "v4 trusted directory anchor binding changed"
                    )
            finally:
                kernel32.CloseHandle(wintypes.HANDLE(root))
            for index, component in enumerate(self._components):
                parent = self._handle_chain[index]
                expected = self._win_identity(
                    self._handle_chain[index + 1], directory=True
                )
                intermediate = index < len(self._components) - 1
                if index in self._windows_full_fallbacks:
                    full = os.path.join(prefix, component)
                    kernel32.CreateFileW.restype = wintypes.HANDLE
                    value = kernel32.CreateFileW(
                        full, 0x00000020 | 0x00000080,
                        0x1 | 0x2 | (0x4 if intermediate else 0), None, 3,
                        0x02000000 | 0x00200000, None,
                    )
                    invalid = ctypes.c_void_p(-1).value
                    if not value or int(value) == invalid:
                        value = kernel32.CreateFileW(
                            full, 0,
                            0x1 | 0x2 | (0x4 if intermediate else 0), None, 3,
                            0x02000000 | 0x00200000, None,
                        )
                    followed_fallback = False
                    if not value or int(value) == invalid:
                        value = kernel32.CreateFileW(
                            full, 0,
                            0x1 | 0x2 | (0x4 if intermediate else 0), None, 3,
                            0x02000000, None,
                        )
                        followed_fallback = bool(value and int(value) != invalid)
                    if not value or int(value) == invalid:
                        raise ControlPlaneV4IntegrityError(
                            "v4 trusted directory path binding changed"
                        )
                    reopened = int(value)
                    if followed_fallback:
                        observed = Path(full).lstat()
                        if (
                            not stat.S_ISDIR(observed.st_mode)
                            or _is_reparse(Path(full))
                            or not self._win_exact_final_path(reopened, Path(full))
                        ):
                            kernel32.CloseHandle(wintypes.HANDLE(reopened))
                            raise ControlPlaneV4IntegrityError(
                                "v4 trusted directory path binding changed"
                            )
                else:
                    reopened = self._nt_open_relative(
                        parent,
                        component,
                        directory=True,
                        share_delete=intermediate,
                    )
                try:
                    if self._win_identity(reopened, directory=True) != expected:
                        raise ControlPlaneV4IntegrityError(
                            "v4 trusted directory path binding changed"
                        )
                finally:
                    kernel32.CloseHandle(wintypes.HANDLE(reopened))
                prefix = os.path.join(prefix, component)
            if not self._win_exact_final_path(self._handle_chain[-1], self.path):
                raise ControlPlaneV4IntegrityError(
                    "v4 trusted directory final binding changed"
                )
            return
        if not self._fd_chain:
            raise ControlPlaneV4IntegrityError("v4 trusted directory is closed")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        for index, component in enumerate(self._components):
            try:
                reopened = os.open(
                    component, flags | nofollow, dir_fd=self._fd_chain[index]
                )
            except OSError:
                raise ControlPlaneV4IntegrityError(
                    "v4 trusted directory path binding changed"
                ) from None
            try:
                observed = os.fstat(reopened)
                expected = os.fstat(self._fd_chain[index + 1])
                if (observed.st_dev, observed.st_ino) != (
                    expected.st_dev,
                    expected.st_ino,
                ):
                    raise ControlPlaneV4IntegrityError(
                        "v4 trusted directory path binding changed"
                    )
            finally:
                os.close(reopened)

    def _assert_pinned(self, *, require_path_binding: bool = True) -> None:
        if os.name == "nt":
            if self._handle is None or self._win_identity(
                self._handle, directory=True
            ) != self._identity:
                raise ControlPlaneV4IntegrityError("v4 trusted directory changed")
        else:
            if self._fd is None:
                raise ControlPlaneV4IntegrityError("v4 trusted directory is closed")
            observed = os.fstat(self._fd)
            if (observed.st_dev, observed.st_ino) != self._identity:
                raise ControlPlaneV4IntegrityError("v4 trusted directory changed")
        if require_path_binding:
            self._assert_path_binding()

    def harden_descriptor(self, descriptor: int) -> None:
        """Protect and flush the exact publication handle, never a path lookup."""
        identity = self.descriptor_identity(descriptor)
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            if not ctypes.WinDLL("kernel32", use_last_error=True).FlushFileBuffers(
                wintypes.HANDLE(int(msvcrt.get_osfhandle(descriptor)))
            ):
                raise ControlPlaneV4IOError("v4 publication handle could not be flushed")
        else:
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        if self.descriptor_identity(descriptor) != identity:
            raise ControlPlaneV4IntegrityError(
                "v4 publication identity changed while hardening"
            )

    def create_temp(
        self, *, prefix: str, suffix: str, native_only: bool = False
    ) -> tuple[str, int]:
        self._assert_pinned()
        name = f"{prefix}{uuid.uuid4().hex}{suffix}"
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            handle: int | None = self._nt_open_relative(
                int(self._handle), name, directory=False, create=True,
                delete_access=native_only, share_delete=not native_only,
            )
            guardian: int | None = None
            descriptor: int | None = None
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            try:
                if not native_only:
                    kernel32.ReOpenFile.restype = wintypes.HANDLE
                    reopened = kernel32.ReOpenFile(
                        wintypes.HANDLE(handle), 0x00010000 | 0x00100000,
                        0x1 | 0x2, 0x00200000,
                    )
                    invalid = ctypes.c_void_p(-1).value
                    if not reopened or int(reopened) == invalid:
                        raise ControlPlaneV4IntegrityError(
                            "v4 native Windows temporary guardian failed"
                        )
                    guardian = int(reopened)
                descriptor = msvcrt.open_osfhandle(
                    handle, os.O_RDWR | getattr(os, "O_BINARY", 0)
                )
                handle = None  # CRT descriptor now owns the native handle.
                if native_only:
                    self._temp_delete_capable.add(descriptor)
                else:
                    assert guardian is not None
                    self._temp_guardians[descriptor] = guardian
                    guardian = None
                self._assert_pinned()
                return name, descriptor
            except BaseException:
                if descriptor is not None:
                    try:
                        self.discard_temp(descriptor, name)
                    except BaseException as cleanup_error:
                        raise ControlPlaneV4IntegrityError(
                            "v4 Windows temporary cleanup failed"
                        ) from cleanup_error
                else:
                    if guardian is not None:
                        kernel32.CloseHandle(wintypes.HANDLE(guardian))
                    if handle is not None:
                        kernel32.CloseHandle(wintypes.HANDLE(handle))
                    # Handles are closed before the descriptor-relative removal,
                    # so conversion failures cannot strand a locked orphan.
                    self._unlink_relative_required(name)
                raise
        else:
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self._fd,
            )
            try:
                self._assert_pinned()
                return name, descriptor
            except BaseException:
                try:
                    self.discard_temp(descriptor, name)
                except BaseException as cleanup_error:
                    raise ControlPlaneV4IntegrityError(
                        "v4 POSIX temporary cleanup failed"
                    ) from cleanup_error
                raise

    def open_existing(self, name: str) -> int:
        """Open an existing regular file through the pinned directory only."""
        self._assert_pinned()
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            handle = self._nt_open_relative(
                int(self._handle), name, directory=False, share_delete=True
            )
            try:
                descriptor = msvcrt.open_osfhandle(
                    handle, os.O_RDWR | getattr(os, "O_BINARY", 0)
                )
            except BaseException:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(
                    wintypes.HANDLE(handle)
                )
                raise
        else:
            descriptor = os.open(
                name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self._fd
            )
        try:
            self.descriptor_identity(descriptor)
            self._assert_pinned()
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def open_anchor_file(self, name: str, *, create: bool) -> int:
        """Open one anchor artifact relative to this pinned directory."""

        self._assert_pinned()
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            handle = self._nt_open_relative(
                int(self._handle),
                name,
                directory=False,
                open_if_missing=create,
            )
            try:
                descriptor = msvcrt.open_osfhandle(
                    handle, os.O_RDWR | getattr(os, "O_BINARY", 0)
                )
            except BaseException:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(
                    wintypes.HANDLE(handle)
                )
                raise
        else:
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            if create:
                flags |= os.O_CREAT
            descriptor = os.open(name, flags, 0o600, dir_fd=self._fd)
        try:
            if self._anchor_open_fault is not None:
                self._anchor_open_fault(name, descriptor)
            self.descriptor_identity(descriptor)
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            self._assert_pinned()
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def read_all(descriptor: int, *, limit: int) -> bytes:
        size = os.fstat(descriptor).st_size
        if size < 0 or size > limit:
            raise ControlPlaneV4IOError("v4 adoption target exceeds capture limit")
        os.lseek(descriptor, 0, os.SEEK_SET)
        payload = bytearray()
        while len(payload) < size:
            chunk = os.read(descriptor, min(_TRUSTED_WRITE_CHUNK, size - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != size or len(payload) > limit:
            raise ControlPlaneV4IntegrityError("v4 adoption target read diverges")
        return bytes(payload)

    def file_identity(
        self, name: str, *, require_path_binding: bool = True
    ) -> tuple[int, ...]:
        self._assert_pinned(require_path_binding=require_path_binding)
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            handle = self._nt_open_relative(
                int(self._handle), name, directory=False, share_delete=True
            )
            try:
                return self._win_identity(handle, directory=False)
            finally:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(
                    wintypes.HANDLE(handle)
                )
        observed = os.stat(name, dir_fd=self._fd, follow_symlinks=False)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise ControlPlaneV4IntegrityError(
                "v4 trusted temporary is linked or has the wrong type"
            )
        return (observed.st_dev, observed.st_ino, observed.st_nlink)

    @classmethod
    def descriptor_identity(cls, descriptor: int) -> tuple[int, ...]:
        if os.name == "nt":
            import msvcrt

            return cls._win_identity(
                int(msvcrt.get_osfhandle(descriptor)), directory=False
            )
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise ControlPlaneV4IntegrityError(
                "v4 trusted temporary descriptor is linked or has the wrong type"
            )
        return (observed.st_dev, observed.st_ino, observed.st_nlink)

    @classmethod
    def hash_descriptor(cls, descriptor: int) -> str:
        identity = cls.descriptor_identity(descriptor)
        offset = os.lseek(descriptor, 0, os.SEEK_CUR)
        hasher = hashlib.sha256()
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            while True:
                chunk = os.read(descriptor, _TRUSTED_WRITE_CHUNK)
                if not chunk:
                    break
                hasher.update(chunk)
            if cls.descriptor_identity(descriptor) != identity:
                raise ControlPlaneV4IntegrityError(
                    "v4 trusted temporary changed while hashing"
                )
            return hasher.hexdigest()
        finally:
            os.lseek(descriptor, offset, os.SEEK_SET)

    @staticmethod
    def write_all(descriptor: int, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view[:_TRUSTED_WRITE_CHUNK])
            if written <= 0:
                raise ControlPlaneV4IOError("v4 trusted temporary write failed")
            view = view[written:]
        os.fsync(descriptor)

    def publish(
        self,
        temporary_name: str,
        target_name: str,
        *,
        descriptor: int | None = None,
        expected_identity: tuple[int, ...] | None = None,
    ) -> None:
        self._assert_pinned()
        if expected_identity is not None:
            if descriptor is None or self.descriptor_identity(descriptor) != expected_identity:
                raise ControlPlaneV4IntegrityError(
                    "v4 publication descriptor identity diverges"
                )
            if os.name != "nt" and self.file_identity(temporary_name) != expected_identity:
                raise ControlPlaneV4IntegrityError(
                    "v4 publication path identity diverges"
                )
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            owns_handle = True
            if descriptor is None:
                handle = self._nt_open_relative(
                    int(self._handle), temporary_name, directory=False,
                    delete_access=True,
                )
            else:
                guardian = self._temp_guardians.get(descriptor)
                if descriptor in self._temp_delete_capable:
                    handle = int(msvcrt.get_osfhandle(descriptor))
                elif guardian is not None:
                    handle = int(guardian)
                else:
                    raise ControlPlaneV4IntegrityError(
                        "v4 native Windows temporary guardian is unavailable"
                    )
                owns_handle = False
            try:
                class FILE_RENAME_INFO(ctypes.Structure):
                    _fields_ = [
                        ("ReplaceIfExists", ctypes.c_ubyte),
                        ("RootDirectory", wintypes.HANDLE),
                        ("FileNameLength", wintypes.DWORD),
                        ("FileName", wintypes.WCHAR * 1),
                    ]

                encoded = target_name.encode("utf-16-le")
                size = FILE_RENAME_INFO.FileName.offset + len(encoded)
                storage = ctypes.create_string_buffer(size)
                info = ctypes.cast(storage, ctypes.POINTER(FILE_RENAME_INFO)).contents
                info.ReplaceIfExists = False
                info.RootDirectory = wintypes.HANDLE(int(self._handle))
                info.FileNameLength = len(encoded)
                ctypes.memmove(
                    ctypes.addressof(storage) + FILE_RENAME_INFO.FileName.offset,
                    encoded,
                    len(encoded),
                )
                _api = self._windows_api()
                iosb = _api[4]()
                ntdll = ctypes.WinDLL("ntdll")
                status = ntdll.NtSetInformationFile(
                    wintypes.HANDLE(handle), ctypes.byref(iosb), storage, size, 10
                )
                iosb_status = int(iosb.Status or 0)
                if int(status) < 0 or iosb_status < 0:
                    raise ControlPlaneV4IntegrityError(
                        "v4 native Windows relative publication failed"
                    )
                ctypes.WinDLL("kernel32", use_last_error=True).FlushFileBuffers(
                    wintypes.HANDLE(handle)
                )
            finally:
                if owns_handle:
                    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(
                        wintypes.HANDLE(handle)
                    )
        else:
            import ctypes
            import sys

            libc = ctypes.CDLL(None, use_errno=True)
            source = os.fsencode(temporary_name)
            target = os.fsencode(target_name)
            if hasattr(libc, "renameat2"):
                result = libc.renameat2(
                    int(self._fd), source, int(self._fd), target, 1
                )
            elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
                result = libc.renameatx_np(
                    int(self._fd), source, int(self._fd), target, 0x00000004
                )
            else:
                raise ControlPlaneV4IntegrityError(
                    "v4 no-replace relative publication is unavailable"
                )
            if result != 0:
                raise ControlPlaneV4IntegrityError(
                    "v4 no-replace relative publication failed"
                )
            os.fsync(int(self._fd))
        if (
            expected_identity is not None
            and os.name != "nt"
            and self.file_identity(target_name) != expected_identity
        ):
            raise ControlPlaneV4IntegrityError(
                "v4 published path identity diverges"
            )
        self._assert_pinned()

    def _unlink_relative_required(
        self, name: str, *, require_path_binding: bool = True
    ) -> None:
        self._assert_pinned(require_path_binding=require_path_binding)
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            handle = self._nt_open_relative(
                int(self._handle), name, directory=False, delete_access=True
            )
            try:
                class FILE_DISPOSITION_INFO(ctypes.Structure):
                    _fields_ = [("DeleteFile", wintypes.BOOL)]

                disposition = FILE_DISPOSITION_INFO(True)
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                if not kernel32.SetFileInformationByHandle(
                    wintypes.HANDLE(handle), 4, ctypes.byref(disposition),
                    ctypes.sizeof(disposition),
                ):
                    raise ControlPlaneV4IntegrityError(
                        "v4 native Windows relative cleanup failed"
                    )
            finally:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(
                    wintypes.HANDLE(handle)
                )
        else:
            os.unlink(name, dir_fd=self._fd)

    def unlink(self, name: str) -> None:
        try:
            self._unlink_relative_required(name)
        except (FileNotFoundError, OSError, ControlPlaneV4Error):
            pass

    def close_temp(self, descriptor: int) -> None:
        self._temp_delete_capable.discard(descriptor)
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            guardian = self._temp_guardians.pop(descriptor, None)
            if guardian is not None:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(
                    wintypes.HANDLE(guardian)
                )
        os.close(descriptor)

    def discard_temp(self, descriptor: int, name: str) -> None:
        if os.name != "nt":
            try:
                os.unlink(name, dir_fd=self._fd)
            finally:
                os.close(descriptor)
            return
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        deletion = (
            int(msvcrt.get_osfhandle(descriptor))
            if descriptor in self._temp_delete_capable
            else self._temp_guardians.get(descriptor)
        )
        try:
            if deletion is None:
                raise ControlPlaneV4IntegrityError(
                    "v4 native Windows temporary guardian is unavailable"
                )

            class FILE_DISPOSITION_INFO(ctypes.Structure):
                _fields_ = [("DeleteFile", wintypes.BOOL)]

            disposition = FILE_DISPOSITION_INFO(True)
            if not kernel32.SetFileInformationByHandle(
                wintypes.HANDLE(int(deletion)), 4, ctypes.byref(disposition),
                ctypes.sizeof(disposition),
            ):
                raise ControlPlaneV4IntegrityError(
                    "v4 native Windows temporary discard failed"
                )
        finally:
            deletion = self._temp_guardians.pop(descriptor, None)
            delete_capable = descriptor in self._temp_delete_capable
            self._temp_delete_capable.discard(descriptor)
            if deletion is not None and not delete_capable:
                kernel32.CloseHandle(wintypes.HANDLE(int(deletion)))
            os.close(descriptor)

    def close(self) -> None:
        if self._temp_guardians:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            for guardian in self._temp_guardians.values():
                kernel32.CloseHandle(wintypes.HANDLE(guardian))
            self._temp_guardians.clear()
        if self._fd_chain:
            for descriptor in reversed(self._fd_chain):
                os.close(descriptor)
            self._fd_chain.clear()
            self._fd = None
        if self._handle is not None:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            for handle in reversed(self._handle_chain or [self._handle]):
                kernel32.CloseHandle(wintypes.HANDLE(handle))
            self._handle_chain.clear()
            self._handle = None


_COUNT_TABLE = "authenticated_row_counts"


_SCHEMA = (
    """
    CREATE TABLE schema_metadata(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE authenticated_row_counts(
        table_name TEXT PRIMARY KEY CHECK(table_name IN (
            'schema_metadata','migration_journal','source_v3_provenance',
            'workspace_provenance','legacy_context_provenance',
            'mission_context_revisions','mission_phase_events','mutation_journal',
            'state_commits','commit_entries','entry_merkle_nodes','mmr_nodes',
            'mmr_edges','mmr_peaks','mission_head_history','head_map_leaves',
            'head_map_nodes'
        )),
        row_count INTEGER NOT NULL CHECK(row_count>=0)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE migration_journal(
        migration_id TEXT PRIMARY KEY,
        schema_from INTEGER NOT NULL,
        schema_to INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status='applied'),
        applied_at TEXT NOT NULL,
        source_root TEXT NOT NULL CHECK(length(source_root)=64),
        target_fingerprint TEXT NOT NULL CHECK(length(target_fingerprint)=64)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE source_v3_provenance(
        source_id TEXT PRIMARY KEY,
        database_id TEXT NOT NULL,
        schema_fingerprint TEXT NOT NULL CHECK(length(schema_fingerprint)=64),
        state_root TEXT NOT NULL CHECK(length(state_root)=64),
        anchor_sequence INTEGER NOT NULL CHECK(anchor_sequence>=1),
        source_file_sha256 TEXT NOT NULL CHECK(length(source_file_sha256)=64),
        captured_at TEXT NOT NULL,
        row_sha256 TEXT NOT NULL CHECK(length(row_sha256)=64)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE workspace_provenance(
        workspace_id TEXT PRIMARY KEY,
        source_schema_version INTEGER NOT NULL,
        status TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
        source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
        captured_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE legacy_context_provenance(
        mission_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        source_schema_version INTEGER NOT NULL,
        source_operational_phase TEXT NOT NULL,
        source_payload_sha256 TEXT NOT NULL CHECK(length(source_payload_sha256)=64),
        source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256)=64),
        disposition TEXT NOT NULL CHECK(disposition IN ('eligible','pending_review')),
        captured_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id) REFERENCES workspace_provenance(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE mission_context_revisions(
        mission_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision>=0),
        workspace_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL CHECK(schema_version=4),
        correlation_id TEXT NOT NULL,
        operational_phase TEXT NOT NULL,
        context_json TEXT NOT NULL CHECK(json_valid(context_json)),
        mission_snapshot_sha256 TEXT NOT NULL CHECK(length(mission_snapshot_sha256)=64),
        mission_event_seq INTEGER NOT NULL CHECK(mission_event_seq>=0),
        mission_event_sha256 TEXT NOT NULL CHECK(length(mission_event_sha256)=64),
        previous_revision_sha256 TEXT NOT NULL CHECK(length(previous_revision_sha256) IN (0,64)),
        revision_sha256 TEXT NOT NULL CHECK(length(revision_sha256)=64),
        created_at TEXT NOT NULL,
        PRIMARY KEY(mission_id,revision),
        UNIQUE(workspace_id,mission_id,revision),
        UNIQUE(correlation_id,revision),
        FOREIGN KEY(workspace_id) REFERENCES workspace_provenance(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE mission_phase_events(
        event_id TEXT PRIMARY KEY,
        mission_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        workspace_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL CHECK(schema_version=1),
        event_type TEXT NOT NULL CHECK(event_type IN ('initialized','transitioned','terminal_reconciled')),
        from_phase TEXT,
        to_phase TEXT NOT NULL,
        mission_snapshot_sha256 TEXT NOT NULL CHECK(length(mission_snapshot_sha256)=64),
        mission_event_seq INTEGER NOT NULL CHECK(mission_event_seq>=0),
        mission_event_sha256 TEXT NOT NULL CHECK(length(mission_event_sha256)=64),
        previous_event_sha256 TEXT NOT NULL CHECK(length(previous_event_sha256) IN (0,64)),
        event_sha256 TEXT NOT NULL CHECK(length(event_sha256)=64),
        occurred_at TEXT NOT NULL,
        UNIQUE(mission_id,revision),
        FOREIGN KEY(mission_id,revision) REFERENCES mission_context_revisions(mission_id,revision),
        FOREIGN KEY(workspace_id) REFERENCES workspace_provenance(workspace_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE mutation_journal(
        mutation_id TEXT PRIMARY KEY,
        mission_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        operation TEXT NOT NULL CHECK(operation IN ('initialize','transition','reconcile')),
        request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
        result_sha256 TEXT NOT NULL CHECK(length(result_sha256)=64),
        created_at TEXT NOT NULL,
        UNIQUE(mission_id,revision),
        FOREIGN KEY(mission_id,revision) REFERENCES mission_context_revisions(mission_id,revision)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE state_commits(
        sequence INTEGER PRIMARY KEY CHECK(sequence>=1),
        commit_id TEXT NOT NULL UNIQUE CHECK(length(commit_id)=64),
        mutation_id TEXT UNIQUE,
        previous_commit_id TEXT NOT NULL CHECK(length(previous_commit_id) IN (0,64)),
        previous_state_root TEXT NOT NULL CHECK(length(previous_state_root) IN (0,64)),
        delta_sha256 TEXT NOT NULL CHECK(length(delta_sha256)=64),
        payload_root TEXT NOT NULL CHECK(length(payload_root)=64),
        entry_merkle_root TEXT NOT NULL CHECK(length(entry_merkle_root)=64),
        head_map_root TEXT NOT NULL CHECK(length(head_map_root)=64),
        head_count INTEGER NOT NULL CHECK(head_count>=0),
        witness_root TEXT NOT NULL CHECK(length(witness_root)=64),
        mmr_root TEXT NOT NULL CHECK(length(mmr_root)=64),
        mmr_leaf_hash TEXT NOT NULL CHECK(length(mmr_leaf_hash)=64),
        mmr_size INTEGER NOT NULL CHECK(mmr_size>=1),
        entry_count INTEGER NOT NULL CHECK(entry_count>=1),
        canonical_row_count INTEGER NOT NULL CHECK(canonical_row_count>=1),
        event_count INTEGER NOT NULL CHECK(event_count>=0),
        state_root TEXT NOT NULL CHECK(length(state_root)=64),
        counts_json TEXT NOT NULL CHECK(json_valid(counts_json)),
        created_at TEXT NOT NULL,
        commit_sha256 TEXT NOT NULL CHECK(length(commit_sha256)=64),
        FOREIGN KEY(mutation_id) REFERENCES mutation_journal(mutation_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE commit_entries(
        commit_id TEXT NOT NULL,
        entry_ordinal INTEGER NOT NULL CHECK(entry_ordinal>=0),
        table_name TEXT NOT NULL,
        row_identity TEXT NOT NULL,
        row_sha256 TEXT NOT NULL CHECK(length(row_sha256)=64),
        leaf_index INTEGER NOT NULL CHECK(leaf_index>=0),
        leaf_hash TEXT NOT NULL CHECK(length(leaf_hash)=64),
        PRIMARY KEY(commit_id,entry_ordinal),
        UNIQUE(table_name,row_identity),
        FOREIGN KEY(commit_id) REFERENCES state_commits(commit_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE entry_merkle_nodes(
        commit_id TEXT NOT NULL,
        tree_level INTEGER NOT NULL CHECK(tree_level>=0),
        node_index INTEGER NOT NULL CHECK(node_index>=0),
        node_hash TEXT NOT NULL CHECK(length(node_hash)=64),
        PRIMARY KEY(commit_id,tree_level,node_index),
        FOREIGN KEY(commit_id) REFERENCES state_commits(commit_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE mmr_nodes(
        node_hash TEXT PRIMARY KEY CHECK(length(node_hash)=64),
        node_height INTEGER NOT NULL CHECK(node_height>=0),
        left_hash TEXT,
        right_hash TEXT,
        commit_sequence INTEGER NOT NULL CHECK(commit_sequence>=1)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE mmr_edges(
        parent_hash TEXT NOT NULL CHECK(length(parent_hash)=64),
        child_hash TEXT NOT NULL CHECK(length(child_hash)=64),
        side INTEGER NOT NULL CHECK(side IN (0,1)),
        PRIMARY KEY(parent_hash,child_hash)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE mmr_peaks(
        commit_sequence INTEGER NOT NULL CHECK(commit_sequence>=1),
        peak_ordinal INTEGER NOT NULL CHECK(peak_ordinal>=0),
        peak_height INTEGER NOT NULL CHECK(peak_height>=0),
        peak_hash TEXT NOT NULL CHECK(length(peak_hash)=64),
        PRIMARY KEY(commit_sequence,peak_ordinal)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE mission_head_history(
        mission_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision>=0),
        commit_sequence INTEGER NOT NULL CHECK(commit_sequence>=2),
        commit_id TEXT NOT NULL CHECK(length(commit_id)=64),
        revision_sha256 TEXT NOT NULL CHECK(length(revision_sha256)=64),
        event_sha256 TEXT NOT NULL CHECK(length(event_sha256)=64),
        mutation_id TEXT NOT NULL,
        head_sha256 TEXT NOT NULL CHECK(length(head_sha256)=64),
        PRIMARY KEY(mission_id,revision),
        UNIQUE(commit_sequence),
        UNIQUE(mutation_id),
        FOREIGN KEY(commit_id) REFERENCES state_commits(commit_id),
        FOREIGN KEY(mutation_id) REFERENCES mutation_journal(mutation_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE head_map_leaves(
        leaf_hash TEXT PRIMARY KEY CHECK(length(leaf_hash)=64),
        key_hash TEXT NOT NULL CHECK(length(key_hash)=64),
        mission_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision>=0),
        commit_sequence INTEGER NOT NULL CHECK(commit_sequence>=2),
        revision_sha256 TEXT NOT NULL CHECK(length(revision_sha256)=64),
        event_sha256 TEXT NOT NULL CHECK(length(event_sha256)=64),
        mutation_id TEXT NOT NULL,
        created_sequence INTEGER NOT NULL CHECK(created_sequence>=2)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE head_map_nodes(
        node_hash TEXT PRIMARY KEY CHECK(length(node_hash)=64),
        tree_depth INTEGER NOT NULL CHECK(tree_depth>=0 AND tree_depth<256),
        left_hash TEXT NOT NULL CHECK(length(left_hash)=64),
        right_hash TEXT NOT NULL CHECK(length(right_hash)=64),
        created_sequence INTEGER NOT NULL CHECK(created_sequence>=2)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX idx_v4_context_workspace ON mission_context_revisions(workspace_id,mission_id,revision)",
    "CREATE INDEX idx_v4_phase_events_mission ON mission_phase_events(mission_id,revision)",
    "CREATE INDEX idx_v4_mission_head ON mission_head_history(mission_id,revision)",
    "CREATE INDEX idx_v4_mmr_edges_child ON mmr_edges(child_hash,parent_hash)",
)

_TABLES = (
    "schema_metadata",
    "migration_journal",
    "source_v3_provenance",
    "workspace_provenance",
    "legacy_context_provenance",
    "mission_context_revisions",
    "mission_phase_events",
    "mutation_journal",
    "state_commits",
    "commit_entries",
    "entry_merkle_nodes",
    "mmr_nodes",
    "mmr_edges",
    "mmr_peaks",
    "mission_head_history",
    "head_map_leaves",
    "head_map_nodes",
)


def _count_triggers(table: str) -> tuple[str, str]:
    return (
        f"CREATE TRIGGER count_{table}_insert AFTER INSERT ON {table} "
        f"BEGIN UPDATE {_COUNT_TABLE} SET row_count=row_count+1 "
        f"WHERE table_name='{table}'; END",
        f"CREATE TRIGGER count_{table}_delete AFTER DELETE ON {table} "
        f"BEGIN UPDATE {_COUNT_TABLE} SET row_count=row_count-1 "
        f"WHERE table_name='{table}' AND row_count>0; "
        f"SELECT CASE WHEN changes()!=1 THEN RAISE(ABORT,'{table} count underflow') END; END",
    )


_COUNT_TRIGGERS = tuple(
    statement for table in _TABLES for statement in _count_triggers(table)
)
_COUNT_TRIGGER_NAMES = frozenset(
    f"count_{table}_{operation}"
    for table in _TABLES
    for operation in ("insert", "delete")
)


def _immutable_triggers(table: str) -> tuple[str, str]:
    return (
        f"CREATE TRIGGER deny_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'{table} is immutable'); END",
        f"CREATE TRIGGER deny_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'{table} is immutable'); END",
    )


_GUARDS = tuple(statement for table in _TABLES for statement in _immutable_triggers(table))


def _schema_contract(connection: sqlite3.Connection) -> dict[str, object]:
    objects = [
        list(row)
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    ]
    tables: dict[str, object] = {}
    table_names = [row[1] for row in objects if row[0] == "table"]
    for table in table_names:
        quoted = table.replace("'", "''")
        indexes = [list(row) for row in connection.execute(f"PRAGMA index_list('{quoted}')")]
        tables[table] = {
            "xinfo": [list(row) for row in connection.execute(f"PRAGMA table_xinfo('{quoted}')")],
            "foreign_keys": [
                list(row) for row in connection.execute(f"PRAGMA foreign_key_list('{quoted}')")
            ],
            "indexes": [
                {
                    "list": row,
                    "xinfo": [
                        list(item)
                        for item in connection.execute(
                            f"PRAGMA index_xinfo('{str(row[1]).replace(chr(39), chr(39) * 2)}')"
                        )
                    ],
                }
                for row in indexes
            ],
        }
    return {"objects": objects, "tables": tables}


def _reference_schema_contract() -> dict[str, object]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in (*_SCHEMA, *_COUNT_TRIGGERS, *_GUARDS):
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version={V4_SCHEMA_VERSION}")
        return _schema_contract(connection)
    finally:
        connection.close()


_REFERENCE_SCHEMA_CONTRACT = _reference_schema_contract()
_SCHEMA_FINGERPRINT = _digest(["OnyxControlPlaneV4Schema.observed.v1", _REFERENCE_SCHEMA_CONTRACT])


@dataclass(frozen=True, slots=True)
class V4Status:
    database_id: str
    schema_version: int
    schema_fingerprint: str
    state_root: str
    event_count: int
    anchor_sequence: int


@dataclass(frozen=True, slots=True)
class _SourceV3Status:
    database_instance_id: str
    schema_fingerprint: str
    state_root: str
    anchor_sequence: int


@dataclass(frozen=True, slots=True)
class _CapturedV3:
    status: _SourceV3Status
    workspaces: tuple[tuple[object, ...], ...]
    contexts: tuple[tuple[object, ...], ...]
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class V4MissionMutation:
    operation: str
    mutation_id: str
    request_sha256: str
    mission_id: str
    workspace_id: str
    correlation_id: str
    target_phase: str
    context_json: str
    mission_snapshot_sha256: str
    mission_event_seq: int
    mission_event_sha256: str
    expected_revision: int
    created_at: str
    legacy_reviewed_source_sha256: str | None = None


class V4OwnerCapability:
    __slots__ = ("_token", "_seal", "__weakref__")

    def __init__(self, token: bytes, seal: object):
        if seal is not _CAPABILITY_SEAL:
            raise TypeError("V4OwnerCapability cannot be constructed directly")
        self._token = token
        self._seal = seal

    def __copy__(self):
        raise TypeError("V4OwnerCapability cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("V4OwnerCapability cannot be copied")

    def __reduce__(self):
        raise TypeError("V4OwnerCapability cannot be serialized")


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None

    def close_failed() -> None:
        nonlocal connection
        opened, connection = connection, None
        if opened is not None:
            try:
                opened.close()
            except BaseException:
                pass

    try:
        expected_identity: tuple[int, int, int, int] | None = None
        _reject_special(path, allow_missing=not readonly)
        sidecars = {
            suffix: Path(str(path) + suffix)
            for suffix in ("-wal", "-shm", "-journal")
        }

        def validate_sidecars() -> dict[str, tuple[int, int] | None]:
            return {
                suffix: _private_sidecar_identity(
                    sidecar, volatile=suffix in {"-wal", "-shm"}
                )
                for suffix, sidecar in sidecars.items()
            }

        validate_sidecars()
        if path.exists():
            expected_identity = _secure_identity(path, label="v4 database")
        if readonly:
            connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, isolation_level=None)
            connection.execute("PRAGMA query_only=ON")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.parent.is_symlink() or _is_reparse(path.parent):
                raise ControlPlaneV4IntegrityError("v4 database parent is linked")
            try:
                os.chmod(path.parent, 0o700)
            except OSError as exc:
                raise ControlPlaneV4IOError("v4 database parent cannot be protected") from exc
            connection = sqlite3.connect(path, isolation_level=None, timeout=10)
        opened_identity = _secure_identity(path, label="v4 database")
        if expected_identity is not None and opened_identity != expected_identity:
            raise ControlPlaneV4IntegrityError("v4 database identity changed while opening")
        database_path = connection.execute("PRAGMA database_list").fetchone()[2]
        if Path(database_path).resolve(strict=True) != path.resolve(strict=True):
            raise ControlPlaneV4IntegrityError("v4 database handle is bound to another path")
        validate_sidecars()
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        if not readonly:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA secure_delete=ON")
            _harden_mode(path)
            for suffix in ("-wal", "-shm"):
                _harden_mode(Path(str(path) + suffix))
        def authorize(action: int, argument1: str | None, argument2: str | None,
                      _database: str | None, source: str | None) -> int:
            writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
            if action in writes and argument1 == _COUNT_TABLE:
                return (
                    sqlite3.SQLITE_OK
                    if source in _COUNT_TRIGGER_NAMES
                    else sqlite3.SQLITE_DENY
                )
            if action == sqlite3.SQLITE_PRAGMA and str(argument1).lower() == "writable_schema":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        connection.set_authorizer(authorize)
        final_identity = _secure_identity(path, label="v4 database")
        if opened_identity[:2] != final_identity[:2]:
            raise ControlPlaneV4IntegrityError("v4 database identity changed after open")
        validate_sidecars()
        return connection
    except ControlPlaneV4Error:
        close_failed()
        raise
    except (sqlite3.Error, OSError):
        close_failed()
        raise ControlPlaneV4IOError("v4 database is unavailable") from None
    except BaseException:
        close_failed()
        raise


def _row_values(row: sqlite3.Row) -> list[object]:
    return [row[key] for key in row.keys()]


_SMT_DEPTH = 256


def _smt_node_hash(depth: int, left_hash: str, right_hash: str) -> str:
    return _typed_record_digest("V4HeadMapNode.v1", [depth, left_hash, right_hash])


_SMT_EMPTY_MUTABLE = [""] * (_SMT_DEPTH + 1)
_SMT_EMPTY_MUTABLE[_SMT_DEPTH] = _typed_record_digest(
    "V4HeadMapEmpty.v1", [_SMT_DEPTH]
)
for _depth in range(_SMT_DEPTH - 1, -1, -1):
    _SMT_EMPTY_MUTABLE[_depth] = _smt_node_hash(
        _depth, _SMT_EMPTY_MUTABLE[_depth + 1], _SMT_EMPTY_MUTABLE[_depth + 1]
    )
_SMT_EMPTY = tuple(_SMT_EMPTY_MUTABLE)
del _SMT_EMPTY_MUTABLE, _depth


def _smt_key_hash(mission_id: str) -> str:
    return hashlib.sha256(mission_id.encode("utf-8")).hexdigest()


def _smt_key_bits(key_hash: str) -> str:
    return f"{int(key_hash, 16):0256b}"


def _smt_leaf_hash(values: list[object]) -> str:
    return _typed_record_digest("V4HeadMapLeaf.v1", values)


def _smt_path_rows(
    connection: sqlite3.Connection, root_hash: str, key_hash: str
) -> list[sqlite3.Row]:
    bits = _smt_key_bits(key_hash)
    return connection.execute(
        """
        WITH RECURSIVE /*v4:smt-current*/ path(depth,node_hash) AS (
          SELECT 0, ?
          UNION ALL
          SELECT path.depth+1,
                 CASE substr(?,path.depth+1,1)
                   WHEN '0' THEN nodes.left_hash ELSE nodes.right_hash END
          FROM path JOIN head_map_nodes AS nodes ON nodes.node_hash=path.node_hash
          WHERE path.depth < 256
        )
        SELECT path.depth,path.node_hash,nodes.tree_depth,nodes.left_hash,nodes.right_hash,
               leaves.key_hash,leaves.mission_id,leaves.revision,
               leaves.commit_sequence,leaves.revision_sha256,leaves.event_sha256,
               leaves.mutation_id,leaves.created_sequence,leaves.leaf_hash
        FROM path
        LEFT JOIN head_map_nodes AS nodes ON nodes.node_hash=path.node_hash
        LEFT JOIN head_map_leaves AS leaves
          ON path.depth=256 AND leaves.leaf_hash=path.node_hash
        ORDER BY path.depth
        """,
        (root_hash, bits),
    ).fetchall()


def _validate_smt_path(
    rows: list[sqlite3.Row], *, root_hash: str, key_hash: str
) -> sqlite3.Row | None:
    if not rows or int(rows[0]["depth"]) != 0 or rows[0]["node_hash"] != root_hash:
        raise ControlPlaneV4IntegrityError("v4 head-map root path is missing")
    bits = _smt_key_bits(key_hash)
    expected_depth = 0
    current = root_hash
    for row in rows:
        depth = int(row["depth"])
        if depth != expected_depth or row["node_hash"] != current:
            raise ControlPlaneV4IntegrityError("v4 head-map path is discontinuous")
        if depth == _SMT_DEPTH:
            if row["leaf_hash"] is None:
                raise ControlPlaneV4IntegrityError("v4 head-map leaf is missing")
            values = [
                row["key_hash"], row["mission_id"], row["revision"],
                row["commit_sequence"], row["revision_sha256"],
                row["event_sha256"], row["mutation_id"],
            ]
            if (
                row["key_hash"] != key_hash
                or row["leaf_hash"] != _smt_leaf_hash(values)
                or int(row["created_sequence"]) != int(row["commit_sequence"])
            ):
                raise ControlPlaneV4IntegrityError("v4 head-map leaf diverges")
            return row
        if current == _SMT_EMPTY[depth]:
            if row["left_hash"] is not None or row["right_hash"] is not None:
                raise ControlPlaneV4IntegrityError("v4 empty head-map path has a node")
            return None
        left_hash, right_hash = row["left_hash"], row["right_hash"]
        if (
            row["tree_depth"] is None
            or int(row["tree_depth"]) != depth
            or _smt_node_hash(depth, str(left_hash), str(right_hash)) != current
        ):
            raise ControlPlaneV4IntegrityError("v4 head-map node diverges")
        current = str(left_hash if bits[depth] == "0" else right_hash)
        expected_depth += 1
    raise ControlPlaneV4IntegrityError("v4 head-map path ended early")


def _prepare_smt_update(
    connection: sqlite3.Connection,
    *,
    prior_root: str,
    prior_count: int,
    sequence: int,
    mission_id: str,
    revision: int,
    revision_sha256: str,
    event_sha256: str,
    mutation_id: str,
) -> tuple[str, int, tuple[object, ...], tuple[tuple[object, ...], ...]]:
    key_hash = _smt_key_hash(mission_id)
    rows = _smt_path_rows(connection, prior_root, key_hash)
    existing = _validate_smt_path(rows, root_hash=prior_root, key_hash=key_hash)
    by_depth = {int(row["depth"]): row for row in rows}
    bits = _smt_key_bits(key_hash)
    siblings: list[str] = []
    empty_tail = False
    for depth in range(_SMT_DEPTH):
        row = by_depth.get(depth)
        if empty_tail or row is None or row["node_hash"] == _SMT_EMPTY[depth]:
            empty_tail = True
            siblings.append(_SMT_EMPTY[depth + 1])
        else:
            siblings.append(str(row["right_hash"] if bits[depth] == "0" else row["left_hash"]))
    leaf_values: list[object] = [
        key_hash, mission_id, revision, sequence, revision_sha256,
        event_sha256, mutation_id,
    ]
    leaf_hash = _smt_leaf_hash(leaf_values)
    leaf_row: tuple[object, ...] = (leaf_hash, *leaf_values, sequence)
    current = leaf_hash
    nodes: list[tuple[object, ...]] = []
    for depth in range(_SMT_DEPTH - 1, -1, -1):
        sibling = siblings[depth]
        left_hash, right_hash = (
            (current, sibling) if bits[depth] == "0" else (sibling, current)
        )
        current = _smt_node_hash(depth, left_hash, right_hash)
        nodes.append((current, depth, left_hash, right_hash, sequence))
    return current, prior_count + (0 if existing is not None else 1), leaf_row, tuple(nodes)


_CONTENT_TABLES = tuple(table for table in _TABLES if table != "state_commits")
_BOOTSTRAP_TABLES = (
    "schema_metadata",
    "migration_journal",
    "source_v3_provenance",
    "workspace_provenance",
    "legacy_context_provenance",
)


def _table_rows(connection: sqlite3.Connection, table: str) -> list[list[object]]:
    columns = tuple(
        row[1]
        for row in connection.execute(f"PRAGMA table_xinfo('{table}')")
        if row[6] == 0
    )
    if not columns:
        raise ControlPlaneV4IntegrityError("v4 table contract is missing")
    order = ",".join(f'"{column}"' for column in columns)
    return [
        _row_values(row)
        for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY {order}')
    ]


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
        for table in _TABLES
    }


def _physical_counts_bounded(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        f"SELECT /*v4:physical-counts*/ table_name,row_count FROM {_COUNT_TABLE} "
        "ORDER BY table_name LIMIT ?",
        (len(_TABLES) + 1,),
    ).fetchall()
    counts = {str(row[0]): row[1] for row in rows}
    if (
        len(rows) != len(_TABLES)
        or set(counts) != set(_TABLES)
        or any(type(value) is not int or value < 0 for value in counts.values())
    ):
        raise ControlPlaneV4IntegrityError("v4 physical count metadata diverges")
    return {table: int(counts[table]) for table in _TABLES}


def _row_identity(connection: sqlite3.Connection, table: str, row: sqlite3.Row) -> str:
    primary = sorted(
        (
            (int(item[5]), str(item[1]))
            for item in connection.execute(f"PRAGMA table_info('{table}')")
            if int(item[5]) > 0
        )
    )
    if not primary:
        raise ControlPlaneV4IntegrityError("v4 witnessed row has no primary identity")
    return json.dumps(
        [row[column] for _ordinal, column in primary],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _entry(connection: sqlite3.Connection, table: str, row: sqlite3.Row) -> tuple[str, str, str]:
    if table == "mission_head_history":
        witnessed = [
            row["mission_id"], row["revision"], row["commit_sequence"],
            row["revision_sha256"], row["event_sha256"], row["mutation_id"],
        ]
        row_sha = _typed_record_digest("V4MissionHeadWitness.v1", witnessed)
    else:
        row_sha = _typed_record_digest(table, _row_values(row))
    return (
        table,
        _row_identity(connection, table, row),
        row_sha,
    )


def _genesis_entries(connection: sqlite3.Connection) -> tuple[tuple[str, str, str], ...]:
    entries: list[tuple[str, str, str]] = []
    for table in _BOOTSTRAP_TABLES:
        columns = [
            str(item[1]) for item in connection.execute(f"PRAGMA table_xinfo('{table}')")
            if int(item[6]) == 0
        ]
        order = ",".join(f'"{column}"' for column in columns)
        for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
            entries.append(_entry(connection, table, row))
    return tuple(sorted(entries))


def _mutation_entries(
    connection: sqlite3.Connection, mutation_id: str, *, expected_sequence: int | None = None
) -> tuple[tuple[str, str, str], ...]:
    journal = connection.execute(
        "SELECT * FROM mutation_journal WHERE mutation_id=?", (mutation_id,)
    ).fetchone()
    if journal is None:
        raise ControlPlaneV4IntegrityError("v4 state commit mutation is missing")
    mission_id, revision = str(journal["mission_id"]), int(journal["revision"])
    context = connection.execute(
        "SELECT * FROM mission_context_revisions WHERE mission_id=? AND revision=?",
        (mission_id, revision),
    ).fetchone()
    event = connection.execute(
        "SELECT * FROM mission_phase_events WHERE mission_id=? AND revision=?",
        (mission_id, revision),
    ).fetchone()
    if context is None or event is None:
        raise ControlPlaneV4IntegrityError("v4 state commit delta is incomplete")
    entries = [
        _entry(connection, "mission_context_revisions", context),
        _entry(connection, "mission_phase_events", event),
        _entry(connection, "mutation_journal", journal),
    ]
    head = connection.execute(
        "SELECT * FROM mission_head_history WHERE mission_id=? AND revision=?",
        (mission_id, revision),
    ).fetchone()
    if head is not None:
        entries.append(_entry(connection, "mission_head_history", head))
    elif expected_sequence is not None:
        identity = json.dumps([mission_id, revision], ensure_ascii=True, separators=(",", ":"))
        witnessed = [
            mission_id, revision, expected_sequence, context["revision_sha256"],
            event["event_sha256"], mutation_id,
        ]
        entries.append((
            "mission_head_history", identity,
            _typed_record_digest("V4MissionHeadWitness.v1", witnessed),
        ))
    else:
        raise ControlPlaneV4IntegrityError("v4 state commit mission head is missing")
    return tuple(sorted(entries))


def _prepare_mmr_append(
    connection: sqlite3.Connection, *, sequence: int, leaf_hash: str
) -> tuple[
    str,
    tuple[tuple[str, int, str | None, str | None, int], ...],
    tuple[tuple[str, str, int], ...],
    tuple[tuple[int, int, int, str], ...],
]:
    prior: list[tuple[int, str]] = []
    if sequence > 1:
        prior = [
            (int(row[0]), str(row[1]))
            for row in connection.execute(
                "SELECT peak_height,peak_hash FROM mmr_peaks "
                "WHERE commit_sequence=? ORDER BY peak_ordinal",
                (sequence - 1,),
            )
        ]
        if not prior:
            raise ControlPlaneV4IntegrityError("v4 MMR predecessor peaks are missing")
    peaks = list(prior)
    nodes: list[tuple[str, int, str | None, str | None, int]] = [
        (leaf_hash, 0, None, None, sequence)
    ]
    edges: list[tuple[str, str, int]] = []
    carry_height, carry_hash = 0, leaf_hash
    while peaks and peaks[-1][0] == carry_height:
        _height, left_hash = peaks.pop()
        parent_hash = _mmr_parent(carry_height + 1, left_hash, carry_hash)
        nodes.append((parent_hash, carry_height + 1, left_hash, carry_hash, sequence))
        edges.extend(((parent_hash, left_hash, 0), (parent_hash, carry_hash, 1)))
        carry_height += 1
        carry_hash = parent_hash
    peaks.append((carry_height, carry_hash))
    peak_rows = tuple(
        (sequence, ordinal, height, node_hash)
        for ordinal, (height, node_hash) in enumerate(peaks)
    )
    return _mmr_bag(peaks), tuple(nodes), tuple(edges), peak_rows


def _append_state_commit(
    connection: sqlite3.Connection,
    *,
    mutation_id: str | None,
    created_at: str,
) -> sqlite3.Row:
    prior = connection.execute(
        "SELECT * FROM state_commits ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    if prior is None:
        if mutation_id is not None:
            raise ControlPlaneV4IntegrityError("v4 genesis cannot bind a mutation")
        sequence, previous_commit_id, previous_root = 1, "", ""
        entries = _genesis_entries(connection)
        genesis_baseline_root = ""
    else:
        if mutation_id is None:
            raise ControlPlaneV4IntegrityError("v4 operational commit requires a mutation")
        sequence = int(prior["sequence"]) + 1
        previous_commit_id, previous_root = str(prior["commit_id"]), str(prior["state_root"])
        entries = _mutation_entries(connection, mutation_id, expected_sequence=sequence)
        genesis_baseline_root = str(
            connection.execute("SELECT delta_sha256 FROM state_commits WHERE sequence=1").fetchone()[0]
        )
    delta = _operational_delta_digest(entries)
    if prior is None:
        genesis_baseline_root = delta
    entry_merkle_root, leaves, merkle_nodes = _entry_merkle_tree(entries)
    if mutation_id is None:
        head_map_root, head_count = _SMT_EMPTY[0], 0
        head_leaf: tuple[object, ...] | None = None
        head_nodes: tuple[tuple[object, ...], ...] = ()
    else:
        journal_head = connection.execute(
            "SELECT mission_id,revision FROM mutation_journal WHERE mutation_id=?",
            (mutation_id,),
        ).fetchone()
        revision_head = connection.execute(
            "SELECT revision_sha256 FROM mission_context_revisions "
            "WHERE mission_id=? AND revision=?", tuple(journal_head),
        ).fetchone()[0]
        event_head = connection.execute(
            "SELECT event_sha256 FROM mission_phase_events "
            "WHERE mission_id=? AND revision=?", tuple(journal_head),
        ).fetchone()[0]
        head_map_root, head_count, head_leaf, head_nodes = _prepare_smt_update(
            connection,
            prior_root=str(prior["head_map_root"]),
            prior_count=int(prior["head_count"]),
            sequence=sequence,
            mission_id=str(journal_head["mission_id"]),
            revision=int(journal_head["revision"]),
            revision_sha256=str(revision_head),
            event_sha256=str(event_head),
            mutation_id=mutation_id,
        )
    witness_root = _typed_record_digest(
        "V4AuthenticatedWitnessRoot.v1",
        [entry_merkle_root, head_map_root, head_count],
    )
    metadata = dict(connection.execute(
        "SELECT key,value FROM schema_metadata ORDER BY key LIMIT 5"
    ))
    database_id = str(metadata.get("database_id", ""))
    if prior is None:
        canonical_count = len(entries)
        event_count = 0
        counts = _physical_counts_bounded(connection)
    else:
        # Operational appends are incremental.  The authenticated predecessor
        # carries exact counts and canonical rows, so no historical table or
        # state-commit scan is needed on the hot writer path.
        canonical_count = int(prior["canonical_row_count"]) + len(entries)
        event_count = int(prior["event_count"]) + 1
        try:
            counts = json.loads(str(prior["counts_json"]))
        except (TypeError, ValueError):
            raise ControlPlaneV4IntegrityError("v4 predecessor counts are invalid") from None
        if (
            not isinstance(counts, dict)
            or set(counts) != set(_TABLES)
            or any(type(value) is not int or value < 0 for value in counts.values())
            or _canonical(counts) != prior["counts_json"]
        ):
            raise ControlPlaneV4IntegrityError("v4 predecessor counts are invalid")
    payload_root = _operational_payload_root(
        sequence=sequence,
        previous_commit_id=previous_commit_id,
        previous_state_root=previous_root,
        database_id=database_id,
        fingerprint=_SCHEMA_FINGERPRINT,
        delta_sha256=delta,
        genesis_baseline_root=genesis_baseline_root,
        entry_merkle_root=witness_root,
        entry_count=len(entries),
        canonical_row_count=canonical_count,
        event_count=event_count,
        created_at=created_at,
    )
    commit_id = _operational_commit_id(
        state_root=payload_root,
        sequence=sequence,
        previous_commit_id=previous_commit_id,
        delta_sha256=delta,
        created_at=created_at,
    )
    mmr_leaf_hash = _mmr_leaf(commit_id, sequence, payload_root)
    mmr_root, mmr_nodes, mmr_edges, mmr_peaks = _prepare_mmr_append(
        connection, sequence=sequence, leaf_hash=mmr_leaf_hash
    )
    state_root = _operational_state_root(
        sequence=sequence,
        previous_commit_id=previous_commit_id,
        previous_state_root=previous_root,
        database_id=database_id,
        fingerprint=_SCHEMA_FINGERPRINT,
        delta_sha256=delta,
        genesis_baseline_root=genesis_baseline_root,
        entry_merkle_root=witness_root,
        mmr_root=mmr_root,
        mmr_size=sequence,
        entry_count=len(entries),
        canonical_row_count=canonical_count,
        event_count=event_count,
        created_at=created_at,
    )
    counts["state_commits"] += 1
    counts["commit_entries"] += len(entries)
    counts["entry_merkle_nodes"] += len(merkle_nodes)
    counts["mmr_nodes"] += len(mmr_nodes)
    counts["mmr_edges"] += len(mmr_edges)
    counts["mmr_peaks"] += len(mmr_peaks)
    if mutation_id is not None:
        counts["mission_context_revisions"] += 1
        counts["mission_phase_events"] += 1
        counts["mutation_journal"] += 1
        counts["mission_head_history"] += 1
        counts["head_map_leaves"] += 1
        counts["head_map_nodes"] += len(head_nodes)
    counts_json = _canonical(counts)
    commit_values = [
        sequence,
        commit_id,
        mutation_id,
        previous_commit_id,
        previous_root,
        delta,
        payload_root,
        entry_merkle_root,
        head_map_root,
        head_count,
        witness_root,
        mmr_root,
        mmr_leaf_hash,
        sequence,
        len(entries),
        canonical_count,
        event_count,
        state_root,
        counts_json,
        created_at,
    ]
    commit_hash = _typed_record_digest("V4StateCommit.v2", commit_values)
    connection.execute(
        "INSERT INTO state_commits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (*commit_values, commit_hash),
    )
    connection.executemany(
        "INSERT INTO commit_entries VALUES(?,?,?,?,?,?,?)",
        [
            (commit_id, ordinal, table, identity, row_sha, ordinal, leaves[ordinal])
            for ordinal, (table, identity, row_sha) in enumerate(entries)
        ],
    )
    connection.executemany(
        "INSERT INTO entry_merkle_nodes VALUES(?,?,?,?)",
        [(commit_id, level, index, node_hash) for level, index, node_hash in merkle_nodes],
    )
    connection.executemany("INSERT INTO mmr_nodes VALUES(?,?,?,?,?)", mmr_nodes)
    connection.executemany("INSERT INTO mmr_edges VALUES(?,?,?)", mmr_edges)
    connection.executemany("INSERT INTO mmr_peaks VALUES(?,?,?,?)", mmr_peaks)
    if head_leaf is not None:
        connection.execute("INSERT INTO head_map_leaves VALUES(?,?,?,?,?,?,?,?,?)", head_leaf)
        connection.executemany(
            "INSERT INTO head_map_nodes VALUES(?,?,?,?,?)", head_nodes
        )
    if mutation_id is not None:
        journal = connection.execute(
            "SELECT mission_id,revision FROM mutation_journal WHERE mutation_id=?", (mutation_id,)
        ).fetchone()
        revision = connection.execute(
            "SELECT revision_sha256 FROM mission_context_revisions WHERE mission_id=? AND revision=?",
            (journal[0], journal[1]),
        ).fetchone()[0]
        event = connection.execute(
            "SELECT event_sha256 FROM mission_phase_events WHERE mission_id=? AND revision=?",
            (journal[0], journal[1]),
        ).fetchone()[0]
        head_values = [journal[0], journal[1], sequence, commit_id, revision, event, mutation_id]
        connection.execute(
            "INSERT INTO mission_head_history VALUES(?,?,?,?,?,?,?,?)",
            (*head_values, _typed_record_digest("V4MissionHead.v1", head_values)),
        )
    if _physical_counts_bounded(connection) != counts:
        raise ControlPlaneV4IntegrityError(
            "v4 authenticated physical counts diverge during append"
        )
    return connection.execute(
        "SELECT * FROM state_commits WHERE sequence=?", (sequence,)
    ).fetchone()


def _logical_snapshot(connection: sqlite3.Connection) -> ledger_anchor.LedgerSnapshot:
    metadata_rows = connection.execute(
        "SELECT /*v4:anchor-logical*/ key,value FROM schema_metadata ORDER BY key LIMIT 5"
    ).fetchall()
    metadata = dict(metadata_rows)
    expected_keys = {
        "database_id",
        "schema_version",
        "schema_fingerprint",
        "source_v3_database_id",
    }
    if len(metadata_rows) != 4 or set(metadata) != expected_keys:
        raise ControlPlaneV4IntegrityError("v4 schema metadata cardinality is invalid")
    if metadata.get("schema_version") != str(V4_SCHEMA_VERSION):
        raise ControlPlaneV4IntegrityError("v4 schema version is invalid")
    if metadata.get("schema_fingerprint") != _SCHEMA_FINGERPRINT:
        raise ControlPlaneV4IntegrityError("v4 schema fingerprint is invalid")
    database_id = metadata.get("database_id", "")
    if not _SAFE_ID.fullmatch(database_id):
        raise ControlPlaneV4IntegrityError("v4 database identity is invalid")
    head = connection.execute(
        "SELECT /*v4:anchor-logical*/ * FROM state_commits ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    if head is None:
        raise ControlPlaneV4IntegrityError("v4 state head is missing")
    values = [head[key] for key in head.keys() if key != "commit_sha256"]
    if head["commit_sha256"] != _typed_record_digest("V4StateCommit.v2", values):
        raise ControlPlaneV4IntegrityError("v4 state head hash diverges")
    genesis = connection.execute(
        "SELECT /*v4:anchor-logical*/ delta_sha256 FROM state_commits WHERE sequence=1"
    ).fetchone()
    if genesis is None:
        raise ControlPlaneV4IntegrityError("v4 genesis state is missing")
    expected_witness_root = _typed_record_digest(
        "V4AuthenticatedWitnessRoot.v1",
        [head["entry_merkle_root"], head["head_map_root"], head["head_count"]],
    )
    expected_payload = _operational_payload_root(
        sequence=int(head["sequence"]),
        previous_commit_id=str(head["previous_commit_id"]),
        previous_state_root=str(head["previous_state_root"]),
        database_id=database_id,
        fingerprint=_SCHEMA_FINGERPRINT,
        delta_sha256=str(head["delta_sha256"]),
        genesis_baseline_root=str(genesis[0]),
        entry_merkle_root=expected_witness_root,
        entry_count=int(head["entry_count"]),
        canonical_row_count=int(head["canonical_row_count"]),
        event_count=int(head["event_count"]),
        created_at=str(head["created_at"]),
    )
    expected_commit = _operational_commit_id(
        state_root=expected_payload,
        sequence=int(head["sequence"]),
        previous_commit_id=str(head["previous_commit_id"]),
        delta_sha256=str(head["delta_sha256"]),
        created_at=str(head["created_at"]),
    )
    expected_leaf = _mmr_leaf(expected_commit, int(head["sequence"]), expected_payload)
    peaks = [
        (int(row[0]), str(row[1]))
        for row in connection.execute(
            "SELECT peak_height,peak_hash FROM mmr_peaks "
            "/*v4:anchor-logical*/ "
            "WHERE commit_sequence=? ORDER BY peak_ordinal",
            (head["sequence"],),
        )
    ]
    expected_state = _operational_state_root(
        sequence=int(head["sequence"]),
        previous_commit_id=str(head["previous_commit_id"]),
        previous_state_root=str(head["previous_state_root"]),
        database_id=database_id,
        fingerprint=_SCHEMA_FINGERPRINT,
        delta_sha256=str(head["delta_sha256"]),
        genesis_baseline_root=str(genesis[0]),
        entry_merkle_root=expected_witness_root,
        mmr_root=str(head["mmr_root"]),
        mmr_size=int(head["mmr_size"]),
        entry_count=int(head["entry_count"]),
        canonical_row_count=int(head["canonical_row_count"]),
        event_count=int(head["event_count"]),
        created_at=str(head["created_at"]),
    )
    if (
        head["payload_root"] != expected_payload
        or head["witness_root"] != expected_witness_root
        or not _DIGEST.fullmatch(str(head["head_map_root"]))
        or int(head["head_count"]) < 0
        or head["commit_id"] != expected_commit
        or head["mmr_leaf_hash"] != expected_leaf
        or int(head["mmr_size"]) != int(head["sequence"])
        or not peaks
        or _mmr_bag(peaks) != head["mmr_root"]
        or head["state_root"] != expected_state
    ):
        raise ControlPlaneV4IntegrityError("v4 authenticated state head diverges")
    try:
        counts = json.loads(head["counts_json"])
    except (TypeError, ValueError):
        raise ControlPlaneV4IntegrityError("v4 state counts are invalid") from None
    if (
        not isinstance(counts, dict)
        or set(counts) != set(_TABLES)
        or any(type(value) is not int or value < 0 for value in counts.values())
        or _canonical(counts) != head["counts_json"]
    ):
        raise ControlPlaneV4IntegrityError("v4 state counts are invalid")
    event_count = counts["mission_phase_events"]
    if event_count != int(head["event_count"]):
        raise ControlPlaneV4IntegrityError("v4 authenticated event count diverges")
    if _physical_counts_bounded(connection) != counts:
        raise ControlPlaneV4IntegrityError("v4 authenticated physical counts diverge")
    return ledger_anchor.LedgerSnapshot(
        database_id,
        _SCHEMA_FINGERPRINT,
        head["state_root"],
        event_count,
        counts,
    )


class _V4AnchorPort:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._candidate: sqlite3.Connection | None = None

    def bind_candidate(self, connection: sqlite3.Connection) -> None:
        if self._candidate is not None:
            raise ControlPlaneV4Conflict("v4 anchor candidate already bound")
        self._candidate = connection

    def clear_candidate(self) -> None:
        self._candidate = None

    def snapshot(self) -> ledger_anchor.LedgerSnapshot:
        if self._candidate is not None:
            return _logical_snapshot(self._candidate)
        connection = _connect(self.path, readonly=True)
        try:
            connection.execute("BEGIN")
            return _logical_snapshot(connection)
        finally:
            primary = sys.exception()
            failures: list[BaseException] = []
            if connection.in_transaction:
                _attempt_cleanup(failures, lambda: connection.execute("ROLLBACK"))
            _attempt_cleanup(failures, connection.close)
            _finish_cleanup("v4 snapshot", failures, primary)


def _validate_commit_row(
    connection: sqlite3.Connection,
    commit: sqlite3.Row,
    database_id: str,
    *,
    genesis_delta_sha256: str | None = None,
) -> None:
    if genesis_delta_sha256 is None:
        genesis = connection.execute(
            "SELECT /*v4:commit-proof*/ delta_sha256 FROM state_commits WHERE sequence=1"
        ).fetchone()
        if genesis is None:
            raise ControlPlaneV4IntegrityError("v4 genesis is unavailable")
        genesis_delta_sha256 = str(genesis[0])
    witness_root = _typed_record_digest(
        "V4AuthenticatedWitnessRoot.v1",
        [commit["entry_merkle_root"], commit["head_map_root"], commit["head_count"]],
    )
    payload = _operational_payload_root(
        sequence=int(commit["sequence"]),
        previous_commit_id=str(commit["previous_commit_id"]),
        previous_state_root=str(commit["previous_state_root"]),
        database_id=database_id,
        fingerprint=_SCHEMA_FINGERPRINT,
        delta_sha256=str(commit["delta_sha256"]),
        genesis_baseline_root=genesis_delta_sha256,
        entry_merkle_root=witness_root,
        entry_count=int(commit["entry_count"]),
        canonical_row_count=int(commit["canonical_row_count"]),
        event_count=int(commit["event_count"]),
        created_at=str(commit["created_at"]),
    )
    commit_id = _operational_commit_id(
        state_root=payload,
        sequence=int(commit["sequence"]),
        previous_commit_id=str(commit["previous_commit_id"]),
        delta_sha256=str(commit["delta_sha256"]),
        created_at=str(commit["created_at"]),
    )
    leaf = _mmr_leaf(commit_id, int(commit["sequence"]), payload)
    values = [commit[key] for key in commit.keys() if key != "commit_sha256"]
    if (
        commit["payload_root"] != payload
        or commit["witness_root"] != witness_root
        or commit["commit_id"] != commit_id
        or commit["mmr_leaf_hash"] != leaf
        or commit["commit_sha256"] != _typed_record_digest("V4StateCommit.v2", values)
    ):
        raise ControlPlaneV4IntegrityError("v4 witnessed commit diverges")


def _verify_entry_witnesses(
    connection: sqlite3.Connection,
    witnesses: tuple[tuple[str, sqlite3.Row], ...],
    *,
    current_head: sqlite3.Row,
    database_id: str,
    entry_rows: tuple[sqlite3.Row, ...] | None = None,
) -> dict[tuple[str, str], sqlite3.Row]:
    """Verify a bounded witness set with proof material cached for this BEGIN only."""
    expected: dict[tuple[str, str], tuple[str, sqlite3.Row]] = {}
    for table, row in witnesses:
        _entry_table, identity, row_sha = _entry(connection, table, row)
        key = (table, identity)
        prior = expected.get(key)
        if prior is not None and prior[0] != row_sha:
            raise ControlPlaneV4IntegrityError("v4 duplicate witness row diverges")
        expected[key] = (row_sha, row)
    if not expected:
        return {}

    if entry_rows is None:
        # Hot bundle proofs are deliberately tiny (workspace + the exact current
        # mission bundle).  Bulk/list callers must supply range-selected entries
        # instead of growing this predicate with one expression per history row.
        if len(expected) > 16:
            raise ControlPlaneV4IntegrityError(
                "v4 bulk witnesses require authenticated range entries"
            )
        predicate = " OR ".join("(table_name=? AND row_identity=?)" for _key in expected)
        parameters = tuple(value for key in expected for value in key)
        selected_entries = connection.execute(
            f"SELECT /*v4:merkle-entries*/ * FROM commit_entries WHERE {predicate}",
            parameters,
        ).fetchall()
    else:
        selected_entries = entry_rows
    entries: dict[tuple[str, str], sqlite3.Row] = {}
    for entry in selected_entries:
        key = (str(entry["table_name"]), str(entry["row_identity"]))
        if key not in expected or key in entries:
            raise ControlPlaneV4IntegrityError("v4 row witness cardinality diverges")
        entries[key] = entry
    if set(entries) != set(expected):
        raise ControlPlaneV4IntegrityError("v4 row witness cardinality diverges")

    commit_ids = tuple(sorted({str(entry["commit_id"]) for entry in entries.values()}))
    placeholders = ",".join("?" for _item in commit_ids)
    commit_rows = connection.execute(
        f"SELECT /*v4:commit-proof*/ * FROM state_commits WHERE commit_id IN ({placeholders})",
        commit_ids,
    ).fetchall()
    commits = {str(commit["commit_id"]): commit for commit in commit_rows}
    if set(commits) != set(commit_ids):
        raise ControlPlaneV4IntegrityError("v4 row witness commit is missing")
    genesis = connection.execute(
        "SELECT /*v4:commit-proof*/ delta_sha256 FROM state_commits WHERE sequence=1"
    ).fetchone()
    if genesis is None:
        raise ControlPlaneV4IntegrityError("v4 genesis is unavailable")
    for commit in commits.values():
        _validate_commit_row(
            connection, commit, database_id, genesis_delta_sha256=str(genesis[0])
        )

    node_rows = connection.execute(
        f"SELECT /*v4:merkle-paths*/ commit_id,tree_level,node_index,node_hash "
        f"FROM entry_merkle_nodes WHERE commit_id IN ({placeholders})",
        commit_ids,
    ).fetchall()
    merkle_nodes: dict[tuple[str, int, int], str] = {}
    for node in node_rows:
        key = (str(node["commit_id"]), int(node["tree_level"]), int(node["node_index"]))
        if key in merkle_nodes:
            raise ControlPlaneV4IntegrityError("v4 Merkle node cardinality diverges")
        merkle_nodes[key] = str(node["node_hash"])

    result: dict[tuple[str, str], sqlite3.Row] = {}
    for key, entry in entries.items():
        table, identity = key
        row_sha = expected[key][0]
        commit_id = str(entry["commit_id"])
        commit = commits[commit_id]
        ordinal = int(entry["entry_ordinal"])
        leaf = _entry_merkle_leaf(ordinal, table, identity, row_sha)
        if (
            entry["row_sha256"] != row_sha
            or int(entry["leaf_index"]) != ordinal
            or entry["leaf_hash"] != leaf
            or ordinal >= int(commit["entry_count"])
        ):
            raise ControlPlaneV4IntegrityError("v4 row witness leaf diverges")
        current_hash, index = leaf, ordinal
        width, level = int(commit["entry_count"]), 0
        while width > 1:
            sibling_index = index ^ 1
            sibling_hash = (
                merkle_nodes.get((commit_id, level, sibling_index))
                if sibling_index < width else current_hash
            )
            if sibling_hash is None:
                raise ControlPlaneV4IntegrityError("v4 Merkle sibling is missing")
            current_hash = (
                _merkle_parent(current_hash, sibling_hash)
                if index % 2 == 0 else _merkle_parent(sibling_hash, current_hash)
            )
            index //= 2
            width = (width + 1) // 2
            level += 1
            if merkle_nodes.get((commit_id, level, index)) != current_hash:
                raise ControlPlaneV4IntegrityError("v4 Merkle path diverges")
        if current_hash != commit["entry_merkle_root"]:
            raise ControlPlaneV4IntegrityError("v4 Merkle root diverges")
        result[key] = commit

    seed_values = ",".join("(?,?)" for _item in commit_ids)
    seed_parameters: list[object] = []
    for commit_id in commit_ids:
        seed_parameters.extend((commit_id, commits[commit_id]["mmr_leaf_hash"]))
    path_rows = connection.execute(
        f"""
        WITH RECURSIVE /*v4:mmr-paths*/
        seeds(origin,leaf_hash) AS (VALUES {seed_values}),
        path(origin,depth,child_hash,parent_hash,side) AS (
          SELECT seeds.origin,0,seeds.leaf_hash,edges.parent_hash,edges.side
          FROM seeds LEFT JOIN mmr_edges AS edges ON edges.child_hash=seeds.leaf_hash
          UNION ALL
          SELECT path.origin,path.depth+1,path.parent_hash,edges.parent_hash,edges.side
          FROM path LEFT JOIN mmr_edges AS edges ON edges.child_hash=path.parent_hash
          WHERE path.parent_hash IS NOT NULL AND path.depth < ?
        )
        SELECT path.origin,path.depth,path.child_hash,path.parent_hash,path.side,
               nodes.node_height,nodes.left_hash,nodes.right_hash
        FROM path LEFT JOIN mmr_nodes AS nodes ON nodes.node_hash=path.parent_hash
        ORDER BY path.origin,path.depth
        """,
        (*seed_parameters, int(current_head["sequence"]) + 1),
    ).fetchall()
    paths: dict[str, list[sqlite3.Row]] = {commit_id: [] for commit_id in commit_ids}
    for row in path_rows:
        origin = str(row["origin"])
        if origin not in paths:
            raise ControlPlaneV4IntegrityError("v4 MMR path origin diverges")
        paths[origin].append(row)
    peaks = [
        (int(item[0]), str(item[1]))
        for item in connection.execute(
            "SELECT /*v4:mmr-peaks*/ peak_height,peak_hash FROM mmr_peaks "
            "WHERE commit_sequence=? ORDER BY peak_ordinal",
            (current_head["sequence"],),
        )
    ]
    peak_hashes = {item[1] for item in peaks}
    if not peaks or _mmr_bag(peaks) != current_head["mmr_root"]:
        raise ControlPlaneV4IntegrityError("v4 authenticated MMR peaks diverge")
    for commit_id, rows in paths.items():
        current_hash = str(commits[commit_id]["mmr_leaf_hash"])
        visited: set[str] = set()
        terminal = False
        for depth, row in enumerate(rows):
            if int(row["depth"]) != depth or row["child_hash"] != current_hash:
                raise ControlPlaneV4IntegrityError("v4 MMR path is discontinuous")
            if current_hash in visited:
                raise ControlPlaneV4IntegrityError("v4 MMR path contains a cycle")
            visited.add(current_hash)
            if row["parent_hash"] is None:
                terminal = True
                break
            parent_hash, side = str(row["parent_hash"]), int(row["side"])
            if row["node_height"] is None or side not in (0, 1):
                raise ControlPlaneV4IntegrityError("v4 MMR parent is missing")
            left_hash, right_hash = str(row["left_hash"]), str(row["right_hash"])
            if (
                (left_hash if side == 0 else right_hash) != current_hash
                or _mmr_parent(int(row["node_height"]), left_hash, right_hash) != parent_hash
            ):
                raise ControlPlaneV4IntegrityError("v4 MMR path diverges")
            current_hash = parent_hash
        if not terminal or current_hash not in peak_hashes:
            raise ControlPlaneV4IntegrityError("v4 MMR proof does not reach authenticated head")
    return result


def _verify_entry_witness(
    connection: sqlite3.Connection,
    *,
    table: str,
    row: sqlite3.Row,
    current_head: sqlite3.Row,
    database_id: str,
) -> sqlite3.Row:
    identity = _row_identity(connection, table, row)
    return _verify_entry_witnesses(
        connection, ((table, row),), current_head=current_head, database_id=database_id
    )[(table, identity)]


def _validate_exact(connection: sqlite3.Connection) -> ledger_anchor.LedgerSnapshot:
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) != V4_SCHEMA_VERSION:
        raise ControlPlaneV4IntegrityError("v4 user_version is invalid")
    if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
        raise ControlPlaneV4IntegrityError("v4 integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ControlPlaneV4IntegrityError("v4 foreign-key check failed")
    observed_contract = _schema_contract(connection)
    if observed_contract != _REFERENCE_SCHEMA_CONTRACT:
        raise ControlPlaneV4IntegrityError("v4 observed schema contract diverges")
    return _logical_snapshot(connection)


def _validate_semantics(connection: sqlite3.Connection) -> ledger_anchor.LedgerSnapshot:
    snapshot = _validate_exact(connection)
    migration = connection.execute("SELECT * FROM migration_journal").fetchall()
    source_rows = connection.execute("SELECT * FROM source_v3_provenance").fetchall()
    if len(migration) != 1 or len(source_rows) != 1:
        raise ControlPlaneV4IntegrityError("v4 bootstrap provenance cardinality diverges")
    source = source_rows[0]
    source_values = [source[key] for key in source.keys() if key != "row_sha256"]
    if (
        source["source_id"] != "v3-archive"
        or source["row_sha256"] != _digest(source_values)
        or migration[0]["migration_id"] != V4_MIGRATION_ID
        or int(migration[0]["schema_from"]) != 3
        or int(migration[0]["schema_to"]) != 4
        or migration[0]["status"] != "applied"
        or migration[0]["source_root"] != source["state_root"]
        or migration[0]["target_fingerprint"] != _SCHEMA_FINGERPRINT
    ):
        raise ControlPlaneV4IntegrityError("v4 bootstrap provenance diverges")
    captured_at = source["captured_at"]
    if migration[0]["applied_at"] != captured_at:
        raise ControlPlaneV4IntegrityError("v4 bootstrap capture identity diverges")
    for row in connection.execute("SELECT * FROM workspace_provenance"):
        if row["captured_at"] != captured_at or not _DIGEST.fullmatch(row["source_row_sha256"]):
            raise ControlPlaneV4IntegrityError("v4 workspace provenance diverges")
    for row in connection.execute("SELECT * FROM legacy_context_provenance"):
        if row["captured_at"] != captured_at or not _DIGEST.fullmatch(row["source_row_sha256"]):
            raise ControlPlaneV4IntegrityError("v4 legacy provenance diverges")
    actual_counts = _counts(connection)
    physical_counts = _physical_counts_bounded(connection)
    if actual_counts != physical_counts or physical_counts != dict(snapshot.entity_counts):
        raise ControlPlaneV4IntegrityError("v4 authenticated counts diverge")
    if any(actual_counts[table] for table in (
        "mission_context_revisions",
        "mission_phase_events",
        "mutation_journal",
    )) and not all(
        actual_counts[table] == actual_counts["mutation_journal"]
        for table in (
            "mission_context_revisions",
            "mission_phase_events",
            "mutation_journal",
        )
    ):
        raise ControlPlaneV4IntegrityError("v4 operational cardinality diverges")

    commits = connection.execute(
        "SELECT * FROM state_commits ORDER BY sequence"
    ).fetchall()
    mutation_ids = {
        str(row[0]) for row in connection.execute("SELECT mutation_id FROM mutation_journal")
    }
    if len(commits) != len(mutation_ids) + 1:
        raise ControlPlaneV4IntegrityError("v4 state commit cardinality diverges")
    historical_counts = {
        table: actual_counts[table] if table in _BOOTSTRAP_TABLES else 0
        for table in _TABLES
    }
    previous_commit_id = ""
    previous_root = ""
    seen_mutations: set[str] = set()
    expected_entries_rows: list[tuple[object, ...]] = []
    expected_merkle_rows: list[tuple[object, ...]] = []
    expected_mmr_nodes: list[tuple[object, ...]] = []
    expected_mmr_edges: list[tuple[object, ...]] = []
    expected_peak_rows: list[tuple[object, ...]] = []
    expected_head_rows: list[tuple[object, ...]] = []
    expected_smt_leaves: dict[str, tuple[object, ...]] = {}
    expected_smt_nodes: dict[str, tuple[object, ...]] = {}
    current_smt: dict[str, str] = {}
    historical_smt_roots: list[tuple[int, str, int]] = []
    head_map_root, head_count = _SMT_EMPTY[0], 0
    peaks: list[tuple[int, str]] = []
    canonical_row_count = 0
    genesis_baseline_root = ""
    for index, commit in enumerate(commits, start=1):
        if (
            int(commit["sequence"]) != index
            or commit["previous_commit_id"] != previous_commit_id
            or commit["previous_state_root"] != previous_root
        ):
            raise ControlPlaneV4IntegrityError("v4 state commit chain is not contiguous")
        mutation_id = commit["mutation_id"]
        if index == 1:
            if mutation_id is not None:
                raise ControlPlaneV4IntegrityError("v4 genesis binds an operation")
            entries = _genesis_entries(connection)
        else:
            if not isinstance(mutation_id, str) or mutation_id in seen_mutations:
                raise ControlPlaneV4IntegrityError("v4 state commit mutation is invalid")
            seen_mutations.add(mutation_id)
            entries = _mutation_entries(connection, mutation_id)
            for table in (
                "mission_context_revisions", "mission_phase_events", "mutation_journal"
            ):
                historical_counts[table] += 1
        delta = _operational_delta_digest(entries)
        if index == 1:
            genesis_baseline_root = delta
        merkle_root, leaves, merkle_nodes = _entry_merkle_tree(entries)
        canonical_row_count += len(entries)
        if mutation_id is not None:
            journal_smt = connection.execute(
                "SELECT mission_id,revision FROM mutation_journal WHERE mutation_id=?",
                (mutation_id,),
            ).fetchone()
            revision_smt = connection.execute(
                "SELECT revision_sha256 FROM mission_context_revisions "
                "WHERE mission_id=? AND revision=?", tuple(journal_smt),
            ).fetchone()[0]
            event_smt = connection.execute(
                "SELECT event_sha256 FROM mission_phase_events "
                "WHERE mission_id=? AND revision=?", tuple(journal_smt),
            ).fetchone()[0]
            key_hash = _smt_key_hash(str(journal_smt["mission_id"]))
            bits = _smt_key_bits(key_hash)
            current_hash = head_map_root
            siblings: list[str] = []
            for depth in range(_SMT_DEPTH):
                if current_hash == _SMT_EMPTY[depth]:
                    siblings.extend(_SMT_EMPTY[item + 1] for item in range(depth, _SMT_DEPTH))
                    break
                node = expected_smt_nodes.get(current_hash)
                if node is None or int(node[1]) != depth:
                    raise ControlPlaneV4IntegrityError("v4 expected head-map path diverges")
                left_hash, right_hash = str(node[2]), str(node[3])
                siblings.append(right_hash if bits[depth] == "0" else left_hash)
                current_hash = left_hash if bits[depth] == "0" else right_hash
            leaf_values = [
                key_hash, journal_smt["mission_id"], journal_smt["revision"], index,
                revision_smt, event_smt, mutation_id,
            ]
            leaf_hash_smt = _smt_leaf_hash(leaf_values)
            leaf_row_smt = (leaf_hash_smt, *leaf_values, index)
            if leaf_hash_smt in expected_smt_leaves and expected_smt_leaves[leaf_hash_smt] != leaf_row_smt:
                raise ControlPlaneV4IntegrityError("v4 expected head-map leaf collision")
            expected_smt_leaves[leaf_hash_smt] = leaf_row_smt
            current_smt.setdefault(key_hash, leaf_hash_smt)
            current_smt[key_hash] = leaf_hash_smt
            current_hash = leaf_hash_smt
            for depth in range(_SMT_DEPTH - 1, -1, -1):
                sibling = siblings[depth]
                left_hash, right_hash = (
                    (current_hash, sibling) if bits[depth] == "0"
                    else (sibling, current_hash)
                )
                current_hash = _smt_node_hash(depth, left_hash, right_hash)
                node_row = (current_hash, depth, left_hash, right_hash, index)
                prior_node = expected_smt_nodes.get(current_hash)
                if prior_node is not None and prior_node[:4] != node_row[:4]:
                    raise ControlPlaneV4IntegrityError("v4 expected head-map node collision")
                expected_smt_nodes.setdefault(current_hash, node_row)
            head_map_root, head_count = current_hash, len(current_smt)
        witness_root = _typed_record_digest(
            "V4AuthenticatedWitnessRoot.v1", [merkle_root, head_map_root, head_count]
        )
        historical_smt_roots.append((index, head_map_root, head_count))
        payload_root = _operational_payload_root(
            sequence=index,
            previous_commit_id=previous_commit_id,
            previous_state_root=previous_root,
            database_id=snapshot.database_id,
            fingerprint=_SCHEMA_FINGERPRINT,
            delta_sha256=delta,
            genesis_baseline_root=genesis_baseline_root,
            entry_merkle_root=witness_root,
            entry_count=len(entries),
            canonical_row_count=canonical_row_count,
            event_count=index - 1,
            created_at=str(commit["created_at"]),
        )
        commit_id = _operational_commit_id(
            state_root=payload_root,
            sequence=index,
            previous_commit_id=previous_commit_id,
            delta_sha256=delta,
            created_at=str(commit["created_at"]),
        )
        leaf_hash = _mmr_leaf(commit_id, index, payload_root)
        new_nodes: list[tuple[str, int, str | None, str | None, int]] = [
            (leaf_hash, 0, None, None, index)
        ]
        new_edges: list[tuple[str, str, int]] = []
        carry_height, carry_hash = 0, leaf_hash
        while peaks and peaks[-1][0] == carry_height:
            _height, left_hash = peaks.pop()
            parent_hash = _mmr_parent(carry_height + 1, left_hash, carry_hash)
            new_nodes.append((parent_hash, carry_height + 1, left_hash, carry_hash, index))
            new_edges.extend(((parent_hash, left_hash, 0), (parent_hash, carry_hash, 1)))
            carry_height += 1
            carry_hash = parent_hash
        peaks.append((carry_height, carry_hash))
        current_peaks = [
            (index, ordinal, height, node_hash)
            for ordinal, (height, node_hash) in enumerate(peaks)
        ]
        mmr_root = _mmr_bag(peaks)
        state_root = _operational_state_root(
            sequence=index,
            previous_commit_id=previous_commit_id,
            previous_state_root=previous_root,
            database_id=snapshot.database_id,
            fingerprint=_SCHEMA_FINGERPRINT,
            delta_sha256=delta,
            genesis_baseline_root=genesis_baseline_root,
            entry_merkle_root=witness_root,
            mmr_root=mmr_root,
            mmr_size=index,
            entry_count=len(entries),
            canonical_row_count=canonical_row_count,
            event_count=index - 1,
            created_at=str(commit["created_at"]),
        )
        historical_counts["state_commits"] += 1
        historical_counts["commit_entries"] += len(entries)
        historical_counts["entry_merkle_nodes"] += len(merkle_nodes)
        historical_counts["mmr_nodes"] += len(new_nodes)
        historical_counts["mmr_edges"] += len(new_edges)
        historical_counts["mmr_peaks"] += len(current_peaks)
        if mutation_id is not None:
            historical_counts["mission_head_history"] += 1
            historical_counts["head_map_leaves"] += 1
            historical_counts["head_map_nodes"] += _SMT_DEPTH
        expected_counts = dict(historical_counts)
        commit_values = [
            index, commit_id, mutation_id, previous_commit_id, previous_root,
            delta, payload_root, merkle_root, head_map_root, head_count, witness_root,
            mmr_root, leaf_hash, index,
            len(entries), canonical_row_count, index - 1, state_root,
            _canonical(expected_counts), commit["created_at"],
        ]
        if (
            _row_values(commit)[:-1] != commit_values
            or commit["counts_json"] != _canonical(expected_counts)
            or commit["commit_sha256"]
            != _typed_record_digest("V4StateCommit.v2", commit_values)
        ):
            raise ControlPlaneV4IntegrityError("v4 state commit payload diverges")
        expected_entries_rows.extend(
            (commit_id, ordinal, table, identity, row_sha, ordinal, leaves[ordinal])
            for ordinal, (table, identity, row_sha) in enumerate(entries)
        )
        expected_merkle_rows.extend(
            (commit_id, level, node_index, node_hash)
            for level, node_index, node_hash in merkle_nodes
        )
        expected_mmr_nodes.extend(new_nodes)
        expected_mmr_edges.extend(new_edges)
        expected_peak_rows.extend(current_peaks)
        if mutation_id is not None:
            journal = connection.execute(
                "SELECT mission_id,revision FROM mutation_journal WHERE mutation_id=?",
                (mutation_id,),
            ).fetchone()
            revision = connection.execute(
                "SELECT revision_sha256 FROM mission_context_revisions "
                "WHERE mission_id=? AND revision=?", tuple(journal),
            ).fetchone()[0]
            event = connection.execute(
                "SELECT event_sha256 FROM mission_phase_events "
                "WHERE mission_id=? AND revision=?", tuple(journal),
            ).fetchone()[0]
            head_values = [journal[0], journal[1], index, commit_id, revision, event, mutation_id]
            expected_head_rows.append(tuple(
                [*head_values, _typed_record_digest("V4MissionHead.v1", head_values)]
            ))
        previous_commit_id = commit_id
        previous_root = state_root
    if seen_mutations != mutation_ids:
        raise ControlPlaneV4IntegrityError("v4 state commit tail diverges")
    reachable_nodes: set[str] = set()
    reachable_leaves: set[str] = set()
    for _sequence, root_hash, expected_head_count in historical_smt_roots:
        root_nodes: set[str] = set()
        root_leaves: set[str] = set()
        stack = [(0, root_hash)]
        while stack:
            depth, node_hash = stack.pop()
            if node_hash == _SMT_EMPTY[depth]:
                continue
            if depth == _SMT_DEPTH:
                leaf_row = expected_smt_leaves.get(node_hash)
                if leaf_row is None or _smt_leaf_hash(list(leaf_row[1:8])) != node_hash:
                    raise ControlPlaneV4IntegrityError("v4 head-map reachable leaf diverges")
                root_leaves.add(node_hash)
                continue
            node_row = expected_smt_nodes.get(node_hash)
            if (
                node_row is None or int(node_row[1]) != depth
                or _smt_node_hash(depth, str(node_row[2]), str(node_row[3])) != node_hash
            ):
                raise ControlPlaneV4IntegrityError("v4 head-map reachable node diverges")
            if node_hash in root_nodes:
                continue
            root_nodes.add(node_hash)
            stack.append((depth + 1, str(node_row[2])))
            stack.append((depth + 1, str(node_row[3])))
        if len(root_leaves) != expected_head_count:
            raise ControlPlaneV4IntegrityError("v4 historical head_count diverges")
        reachable_nodes.update(root_nodes)
        reachable_leaves.update(root_leaves)
    if (
        reachable_nodes != set(expected_smt_nodes)
        or reachable_leaves != set(expected_smt_leaves)
    ):
        raise ControlPlaneV4IntegrityError("v4 head-map contains unreachable content")
    for table, expected in (
        ("commit_entries", expected_entries_rows),
        ("entry_merkle_nodes", expected_merkle_rows),
        ("mmr_nodes", expected_mmr_nodes),
        ("mmr_edges", expected_mmr_edges),
        ("mmr_peaks", expected_peak_rows),
        ("mission_head_history", expected_head_rows),
        ("head_map_leaves", list(expected_smt_leaves.values())),
        ("head_map_nodes", list(expected_smt_nodes.values())),
    ):
        observed = [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
        if sorted(observed, key=repr) != sorted(expected, key=repr):
            raise ControlPlaneV4IntegrityError(f"v4 {table} reconstruction diverges")

    rows = connection.execute(
        "SELECT * FROM mission_context_revisions ORDER BY mission_id,revision"
    ).fetchall()
    by_mission: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_mission.setdefault(str(row["mission_id"]), []).append(row)
    for mission_id, revisions in by_mission.items():
        prior_revision_hash = ""
        prior_event_hash = ""
        prior_phase: str | None = None
        correlation: str | None = None
        for revision, row in enumerate(revisions):
            if int(row["revision"]) != revision:
                raise ControlPlaneV4IntegrityError("v4 revision chain has a gap")
            try:
                parse_context_json(row["context_json"])
            except MissionContextContractError as exc:
                raise ControlPlaneV4IntegrityError(str(exc)) from None
            revision_values = [
                row["mission_id"], row["revision"], row["workspace_id"],
                row["schema_version"], row["correlation_id"],
                row["operational_phase"], row["context_json"],
                row["mission_snapshot_sha256"], row["mission_event_seq"],
                row["mission_event_sha256"], row["previous_revision_sha256"],
                row["created_at"],
            ]
            expected_revision_hash = _digest(
                ["MissionContextRevision.v1", *revision_values]
            )
            if (
                row["previous_revision_sha256"] != prior_revision_hash
                or row["revision_sha256"] != expected_revision_hash
            ):
                raise ControlPlaneV4IntegrityError("v4 revision hash chain diverges")
            if correlation is None:
                correlation = str(row["correlation_id"])
            elif row["correlation_id"] != correlation:
                raise ControlPlaneV4IntegrityError("v4 correlation identity changed")
            event = connection.execute(
                "SELECT * FROM mission_phase_events WHERE mission_id=? AND revision=?",
                (mission_id, revision),
            ).fetchone()
            journal = connection.execute(
                "SELECT * FROM mutation_journal WHERE mission_id=? AND revision=?",
                (mission_id, revision),
            ).fetchone()
            if event is None or journal is None:
                raise ControlPlaneV4IntegrityError("v4 revision companions are missing")
            event_values = [
                event["mission_id"], event["revision"], event["workspace_id"],
                event["schema_version"], event["event_type"], event["from_phase"],
                event["to_phase"], event["mission_snapshot_sha256"],
                event["mission_event_seq"], event["mission_event_sha256"],
                event["previous_event_sha256"], event["occurred_at"],
            ]
            expected_event_hash = _digest(["MissionPhaseEvent.v1", *event_values])
            expected_event_id = hashlib.sha256(
                (f"{mission_id}\0{expected_event_hash}" if revision == 0 else
                 f"{mission_id}\0{revision}\0{expected_event_hash}").encode()
            ).hexdigest()
            expected_type = "initialized" if revision == 0 else (
                "terminal_reconciled" if journal["operation"] == "reconcile" else "transitioned"
            )
            try:
                validate_storage_transition(
                    str(journal["operation"]), prior_phase, str(row["operational_phase"])
                )
            except MissionContextContractError as exc:
                raise ControlPlaneV4IntegrityError(str(exc)) from None
            if revision == 0 and row["workspace_id"] == "legacy-default":
                provenance = connection.execute(
                    "SELECT disposition FROM legacy_context_provenance WHERE mission_id=?",
                    (mission_id,),
                ).fetchone()
                if provenance is not None and provenance[0] != "eligible":
                    raise ControlPlaneV4IntegrityError(
                        "v4 legacy revision lacks eligible reviewed provenance"
                    )
            if (
                event["workspace_id"] != row["workspace_id"]
                or event["from_phase"] != prior_phase
                or event["to_phase"] != row["operational_phase"]
                or event["mission_snapshot_sha256"] != row["mission_snapshot_sha256"]
                or event["mission_event_seq"] != row["mission_event_seq"]
                or event["mission_event_sha256"] != row["mission_event_sha256"]
                or event["previous_event_sha256"] != prior_event_hash
                or event["event_sha256"] != expected_event_hash
                or event["event_id"] != expected_event_id
                or event["event_type"] != expected_type
                or journal["result_sha256"] != row["revision_sha256"]
                or (revision == 0 and journal["operation"] != "initialize")
                or (revision > 0 and journal["operation"] not in {"transition", "reconcile"})
                or not _DIGEST.fullmatch(str(journal["request_sha256"]))
            ):
                raise ControlPlaneV4IntegrityError("v4 revision/event/result semantics diverge")
            prior_revision_hash = str(row["revision_sha256"])
            prior_event_hash = str(event["event_sha256"])
            prior_phase = str(row["operational_phase"])
    return snapshot


class ControlPlaneV4Store:
    """Same-process fixture successor; it is not a Python security boundary.

    The typed methods never expose a SQL cursor/connection and production
    operational opening remains unavailable.  The store never owns mission
    execution.
    """

    def __init__(
        self,
        source: _ControlPlaneV3Migrator,
        source_owner: V3OwnerCapability,
        path: Path,
        anchor: ledger_anchor.LedgerAnchor,
        anchor_owner: ledger_anchor.OwnerCapability,
        port: _V4AnchorPort,
        journal_path: Path,
        key_vault: _SecretVault,
        state_vault: _SecretVault,
        *,
        enabled: bool,
        token: bytes,
        fixture_operational: bool,
    ):
        self.source = source
        self.source_owner = source_owner
        self.path = Path(path)
        self.anchor = anchor
        self.anchor_owner = anchor_owner
        self.port = port
        self.journal_path = Path(journal_path)
        self.key_vault = key_vault
        self.state_vault = state_vault
        self.enabled = enabled
        self._token = token
        self._fixture_operational = fixture_operational
        self._fault: Callable[[str], None] = lambda _point: None

    def _assert_owner(self, owner: V4OwnerCapability) -> None:
        issued = _CAPABILITIES.get(owner)
        if issued is None or not secrets.compare_digest(issued, self._token):
            raise ControlPlaneV4Conflict("v4 owner capability is invalid")
        if not self.enabled:
            raise ControlPlaneV4Disabled(f"{CONTROL_PLANE_V4_FLAG} is disabled")

    def assert_operational_owner(self, owner: V4OwnerCapability) -> None:
        self._assert_owner(owner)
        if not self._fixture_operational:
            raise ControlPlaneV4Conflict(
                "v4 operational access is unavailable outside the fixture opener"
            )

    def _bootstrap_anchor(
        self, journal_dir: _TrustedDirectory
    ) -> ledger_anchor.AnchorStatus:
        """Bootstrap while recording the new journal in one native identity domain."""
        original_fault = self.anchor._fault
        original_open_fault = journal_dir._anchor_open_fault
        self._bootstrap_journal_identity: tuple[int, ...] | None = None

        journal_dir._assert_pinned()
        try:
            journal_dir.file_identity(self.journal_path.name)
        except FileNotFoundError:
            pass
        else:
            raise ControlPlaneV4IntegrityError(
                "v4 bootstrap journal target is not empty"
            )

        def journal_opened(identity: tuple[int, ...]) -> None:
            journal_dir._assert_pinned()
            if journal_dir.file_identity(self.journal_path.name) != identity:
                raise ControlPlaneV4IntegrityError(
                    "v4 bootstrap journal descriptor identity diverges"
                )
            if (
                self._bootstrap_journal_identity is not None
                and self._bootstrap_journal_identity != identity
            ):
                raise ControlPlaneV4IntegrityError(
                    "v4 bootstrap journal descriptor identity changed"
                )
            self._bootstrap_journal_identity = identity

        def opening_fault(name: str, descriptor: int) -> None:
            if name != self.journal_path.name:
                return
            identity = journal_dir.descriptor_identity(descriptor)
            self._bootstrap_journal_identity = identity
            original_fault("after_capability_journal_create_before_binding")

        def recording_fault(point: str) -> None:
            journal_dir._assert_pinned()
            if self._bootstrap_journal_identity is None:
                raise ControlPlaneV4IntegrityError(
                    "v4 bootstrap journal identity was not recorded"
                )
            original_fault(point)

        self.anchor._fault = recording_fault
        journal_dir._anchor_open_fault = opening_fault
        try:
            status = self.anchor._bootstrap_with_directory_capability(
                self.anchor_owner, journal_dir, journal_opened
            )
            journal_dir._assert_pinned()
            if (
                self._bootstrap_journal_identity is None
                or journal_dir.file_identity(self.journal_path.name)
                != self._bootstrap_journal_identity
            ):
                raise ControlPlaneV4IntegrityError(
                    "v4 bootstrap journal identity diverges"
                )
            return status
        finally:
            journal_dir._anchor_open_fault = original_open_fault
            self.anchor._fault = original_fault

    def _rollback_new_anchor_artifacts(
        self, journal_dir: _TrustedDirectory
    ) -> None:
        """Best-effort removal of an anchor bootstrap that began from empty state."""
        failures: list[BaseException] = []
        for vault in (self.state_vault, self.key_vault):
            try:
                vault.delete()
            except BaseException as exc:
                failures.append(exc)
        try:
            expected = getattr(self, "_bootstrap_journal_identity", None)
            try:
                observed = journal_dir.file_identity(
                    self.journal_path.name, require_path_binding=False
                )
            except FileNotFoundError:
                observed = None
            if observed is not None:
                if expected is None or observed != expected:
                    raise ControlPlaneV4IntegrityError(
                        "v4 bootstrap journal identity changed during rollback"
                    )
                journal_dir._unlink_relative_required(
                    self.journal_path.name, require_path_binding=False
                )
        except BaseException as exc:
            failures.append(exc)
        try:
            try:
                remaining = journal_dir.file_identity(
                    self.journal_path.name, require_path_binding=False
                )
            except FileNotFoundError:
                remaining = None
        except BaseException as exc:
            failures.append(exc)
            remaining = (1,)
        if (
            failures
            or self.key_vault.get_bytes() is not None
            or self.state_vault.get_bytes() is not None
            or remaining is not None
        ):
            detail = (
                f": {type(failures[0]).__name__}: {failures[0]}"
                if failures else ""
            )
            raise ControlPlaneV4IntegrityError(
                "v4 failed bootstrap artifacts could not be rolled back" + detail
            ) from (failures[0] if failures else None)

    def _source_rows(self) -> _CapturedV3:
        """Capture one validated SQLite snapshot under the v3 writer lock.

        Provenance hashes the private backup, never a physical file observed at
        a different logical instant.  The source file is also hashed before and
        after solely as a stability/swap check; that hash is not mixed into the
        captured snapshot identity.
        """
        trusted: _TrustedDirectory | None = None
        temporary_name: str | None = None
        descriptor: int | None = None
        snapshot_connection: sqlite3.Connection | None = None
        try:
            trusted = _TrustedDirectory(self.path.parent)
            source_path = Path(self.source.port.path)
            source_identity = _secure_identity(source_path, label="v3 source")
            if source_identity[2] > _MAX_V3_CAPTURE_BYTES:
                raise ControlPlaneV4IOError("v3 archival source exceeds capture limit")
            source_hash_before = _file_sha256(source_path, label="v3 source")
            with self.source.anchor.writer_session(self.source.anchor_owner) as session:
                anchored = session.verify_baseline()
                source_connection = _open_canonical_connection(
                    source_path, read_only=True
                )
                # Deliberately pristine: destination PRAGMAs before backup can
                # change the clone representation and invalidate v3 exactness.
                snapshot_connection = sqlite3.connect(":memory:")
                try:
                    source_connection.execute("BEGIN")
                    source_pages = _database_page_bytes(source_connection)
                    if source_pages > _MAX_V3_CAPTURE_BYTES:
                        raise ControlPlaneV4IOError(
                            "v3 archival source exceeds capture limit"
                        )
                    validated = _validate_v3_exact(source_connection, require_finalization=True)
                    if (
                        anchored.database_id != validated.database_instance_id
                        or anchored.schema_fingerprint != validated.schema_fingerprint
                        or anchored.ledger_root != validated.state_root
                        or anchored.sequence != validated.anchor_sequence
                    ):
                        raise ControlPlaneV4IntegrityError("v3 source anchor diverges")
                    source_connection.backup(snapshot_connection)
                finally:
                    primary = sys.exception()
                    failures: list[BaseException] = []
                    if source_connection.in_transaction:
                        _attempt_cleanup(
                            failures, lambda: source_connection.execute("ROLLBACK")
                        )
                    _attempt_cleanup(failures, source_connection.close)
                    _finish_cleanup("v3 source connection", failures, primary)
                captured_connection = snapshot_connection
                captured_connection.execute("PRAGMA foreign_keys=ON")
                captured_connection.execute("PRAGMA legacy_alter_table=OFF")
                captured_connection.execute("PRAGMA trusted_schema=OFF")
                try:
                    captured_status = _validate_v3_exact(
                        captured_connection, require_finalization=True
                    )
                    workspaces = tuple(
                        tuple(row)
                        for row in captured_connection.execute(
                            "SELECT workspace_id,schema_version,status,payload_json,created_at,updated_at "
                            "FROM workspaces ORDER BY workspace_id"
                        )
                    )
                    contexts = tuple(
                        tuple(row)
                        for row in captured_connection.execute(
                            "SELECT mission_id,workspace_id,schema_version,operational_phase,payload_json,created_at,updated_at "
                            "FROM mission_contexts ORDER BY mission_id"
                        )
                    )
                    snapshot_bytes = captured_connection.serialize()
                    if len(snapshot_bytes) > _MAX_V3_CAPTURE_BYTES:
                        raise ControlPlaneV4IOError(
                            "v3 captured snapshot exceeds capture limit"
                        )
                finally:
                    captured_connection.close()
                    snapshot_connection = None
                status = _SourceV3Status(
                    captured_status.database_instance_id,
                    captured_status.schema_fingerprint,
                    captured_status.state_root,
                    captured_status.anchor_sequence,
                )
                if (
                    anchored.database_id != status.database_instance_id
                    or anchored.schema_fingerprint != status.schema_fingerprint
                    or anchored.ledger_root != status.state_root
                    or anchored.sequence != status.anchor_sequence
                ):
                    raise ControlPlaneV4IntegrityError("v3 source anchor diverges")
                self._fault("before_v3_capture_temp")
                temporary_name, descriptor = trusted.create_temp(
                    prefix=".onyx-v3-capture-", suffix=".sqlite3", native_only=True
                )
                temporary_identity = trusted.descriptor_identity(descriptor)
                trusted.write_all(descriptor, snapshot_bytes)
                if trusted.descriptor_identity(descriptor) != temporary_identity:
                    raise ControlPlaneV4IntegrityError(
                        "v3 capture temporary identity changed"
                    )
                if os.fstat(descriptor).st_size > _MAX_V3_CAPTURE_BYTES:
                    raise ControlPlaneV4IOError(
                        "v3 captured snapshot exceeds capture limit"
                    )
                snapshot_hash = trusted.hash_descriptor(descriptor)
                if snapshot_hash != hashlib.sha256(snapshot_bytes).hexdigest():
                    raise ControlPlaneV4IntegrityError(
                        "v3 captured snapshot write diverges"
                    )
                del snapshot_bytes
                self._fault("after_v3_snapshot_before_revalidate")
            if (
                _secure_identity(source_path, label="v3 source") != source_identity
                or _file_sha256(source_path, label="v3 source") != source_hash_before
            ):
                raise ControlPlaneV4IntegrityError("v3 source changed during capture")
            return _CapturedV3(status, workspaces, contexts, snapshot_hash)
        except ControlPlaneV4Error:
            raise
        except (ledger_anchor.LedgerAnchorError, ControlPlaneV3Error, sqlite3.Error, OSError):
            raise ControlPlaneV4IntegrityError("v3 archival source validation failed") from None
        finally:
            cleanup_error: BaseException | None = None
            if snapshot_connection is not None:
                try:
                    snapshot_connection.close()
                except BaseException as exc:
                    cleanup_error = exc
            if trusted is not None:
                if descriptor is not None and temporary_name is not None:
                    try:
                        trusted.discard_temp(descriptor, temporary_name)
                    except BaseException as exc:
                        if cleanup_error is None:
                            cleanup_error = exc
                    descriptor = None
                elif temporary_name is not None:
                    try:
                        trusted._unlink_relative_required(temporary_name)
                    except FileNotFoundError:
                        pass
                    except BaseException as exc:
                        if cleanup_error is None:
                            cleanup_error = exc
                try:
                    trusted.close()
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
            if cleanup_error is not None:
                raise ControlPlaneV4IntegrityError(
                    "v3 archival source cleanup failed"
                ) from cleanup_error

    def migrate(self, owner: V4OwnerCapability) -> V4Status:
        self._assert_owner(owner)
        # Pin the journal parent before *any* target/anchor existence decision.
        # The same capability remains alive through bootstrap, verification and
        # rollback, so a renamed/replaced pathname can never redirect setup.
        journal_capability = _TrustedDirectory(self.journal_path.parent)
        try:
            journal_capability._assert_pinned()
            return self._migrate_with_journal(owner, journal_capability)
        finally:
            primary = sys.exception()
            failures: list[BaseException] = []
            _attempt_cleanup(failures, journal_capability.close)
            _finish_cleanup("v4 journal capability", failures, primary)

    def _migrate_with_journal(
        self,
        owner: V4OwnerCapability,
        journal_capability: _TrustedDirectory,
    ) -> V4Status:
        with _LOCK:
            journal_capability._assert_pinned()
            try:
                journal_identity = journal_capability.file_identity(
                    self.journal_path.name
                )
            except FileNotFoundError:
                journal_identity = None
            if self.path.exists():
                if (
                    self.key_vault.get_bytes() is None
                    and self.state_vault.get_bytes() is None
                    and journal_identity is None
                ):
                    # A process may have died after atomic publication and
                    # before the first anchor bootstrap.  Only the exact empty
                    # migration candidate can be adopted; bootstrap itself
                    # still rejects any pre-existing anchor state.
                    captured = self._source_rows()
                    trusted = _TrustedDirectory(self.path.parent)
                    descriptor: int | None = None
                    connection: sqlite3.Connection | None = None
                    candidate_bound = False
                    bootstrap_started = False
                    bootstrap_validated = False
                    try:
                        descriptor = trusted.open_existing(self.path.name)
                        identity = trusted.descriptor_identity(descriptor)
                        file_hash = trusted.hash_descriptor(descriptor)
                        payload = trusted.read_all(
                            descriptor, limit=_MAX_V3_CAPTURE_BYTES
                        )
                        if hashlib.sha256(payload).hexdigest() != file_hash:
                            raise ControlPlaneV4IntegrityError(
                                "v4 adoption target read diverges"
                            )
                        connection = sqlite3.connect(":memory:", isolation_level=None)
                        connection.deserialize(payload)
                        del payload
                        connection.row_factory = sqlite3.Row
                        connection.execute("PRAGMA foreign_keys=ON")
                        connection.execute("PRAGMA trusted_schema=OFF")
                        connection.execute("BEGIN")
                        self._validate_unanchored_publication(captured, connection)
                        self.port.bind_candidate(connection)
                        candidate_bound = True
                        self._fault("after_v4_adoption_validate_before_anchor")
                        trusted._assert_pinned()
                        if (
                            trusted.file_identity(self.path.name) != identity
                            or trusted.descriptor_identity(descriptor) != identity
                            or trusted.hash_descriptor(descriptor) != file_hash
                        ):
                            raise ControlPlaneV4IntegrityError(
                                "v4 adoption target changed before anchor bootstrap"
                            )
                        bootstrap_started = True
                        anchored = self._bootstrap_anchor(journal_capability)
                        trusted._assert_pinned()
                        if (
                            trusted.file_identity(self.path.name) != identity
                            or trusted.descriptor_identity(descriptor) != identity
                            or trusted.hash_descriptor(descriptor) != file_hash
                        ):
                            raise ControlPlaneV4IntegrityError(
                                "v4 adoption target changed during anchor bootstrap"
                            )
                        if self.anchor.verify(self.anchor_owner) != anchored:
                            raise ControlPlaneV4IntegrityError(
                                "v4 adoption bootstrap verification diverges"
                            )
                        bootstrap_validated = True
                    finally:
                        primary = sys.exception()
                        failures: list[BaseException] = []
                        if candidate_bound:
                            _attempt_cleanup(failures, self.port.clear_candidate)
                        if connection is not None:
                            if connection.in_transaction:
                                _attempt_cleanup(
                                    failures, lambda: connection.execute("ROLLBACK")
                                )
                            _attempt_cleanup(failures, connection.close)
                        if descriptor is not None:
                            _attempt_cleanup(failures, lambda: os.close(descriptor))
                        if bootstrap_started and not bootstrap_validated:
                            _attempt_cleanup(
                                failures,
                                lambda: self._rollback_new_anchor_artifacts(
                                    journal_capability
                                ),
                            )
                        _attempt_cleanup(failures, trusted.close)
                        _finish_cleanup("v4 adoption", failures, primary)
                    return self.open(owner)
                return self.open(owner)
            if (
                self.key_vault.get_bytes() is not None
                or self.state_vault.get_bytes() is not None
                or journal_identity is not None
            ):
                raise ControlPlaneV4IntegrityError(
                    "v4 anchor bootstrap target is not empty"
                )
            captured = self._source_rows()
            status = captured.status
            workspaces = captured.workspaces
            contexts = captured.contexts
            source_hash = captured.snapshot_sha256
            trusted = _TrustedDirectory(self.path.parent)
            temporary_name: str | None = None
            descriptor: int | None = None
            published = False
            bootstrap_complete = False
            bootstrap_started = False
            candidate_bound = False
            connection: sqlite3.Connection | None = None
            try:
                connection = sqlite3.connect(":memory:", isolation_level=None)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA secure_delete=ON")
                connection.execute("PRAGMA synchronous=FULL")
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in _SCHEMA:
                        connection.execute(statement)
                    connection.executemany(
                        f"INSERT INTO {_COUNT_TABLE}(table_name,row_count) VALUES(?,0)",
                        [(table,) for table in _TABLES],
                    )
                    for statement in _COUNT_TRIGGERS:
                        connection.execute(statement)
                    database_id = f"onyx-v4-{uuid.uuid4().hex}"
                    captured_at = _utc_now()
                    connection.executemany(
                        "INSERT INTO schema_metadata VALUES(?,?)",
                        (
                            ("database_id", database_id),
                            ("schema_version", str(V4_SCHEMA_VERSION)),
                            ("schema_fingerprint", _SCHEMA_FINGERPRINT),
                            ("source_v3_database_id", status.database_instance_id),
                        ),
                    )
                    source_values = (
                        "v3-archive",
                        status.database_instance_id,
                        status.schema_fingerprint,
                        status.state_root,
                        status.anchor_sequence,
                        source_hash,
                        captured_at,
                    )
                    connection.execute(
                        "INSERT INTO source_v3_provenance VALUES(?,?,?,?,?,?,?,?)",
                        (*source_values, _digest(source_values)),
                    )
                    connection.execute(
                        "INSERT INTO migration_journal VALUES(?,?,?,?,?,?,?)",
                        (
                            V4_MIGRATION_ID,
                            3,
                            4,
                            "applied",
                            captured_at,
                            status.state_root,
                            _SCHEMA_FINGERPRINT,
                        ),
                    )
                    for workspace in workspaces:
                        wid, version, workspace_status, payload, created, updated = workspace
                        source_row = _digest(list(workspace))
                        connection.execute(
                            "INSERT INTO workspace_provenance VALUES(?,?,?,?,?,?)",
                            (
                                wid,
                                version,
                                workspace_status,
                                hashlib.sha256(str(payload).encode()).hexdigest(),
                                source_row,
                                captured_at,
                            ),
                        )
                    for context in contexts:
                        mid, wid, version, phase, payload, created, updated = context
                        disposition = "pending_review" if phase == "PENDING_REVIEW" else "eligible"
                        connection.execute(
                            "INSERT INTO legacy_context_provenance VALUES(?,?,?,?,?,?,?,?)",
                            (
                                mid,
                                wid,
                                version,
                                phase,
                                hashlib.sha256(str(payload).encode()).hexdigest(),
                                _digest(list(context)),
                                disposition,
                                captured_at,
                            ),
                        )
                    for statement in _GUARDS:
                        connection.execute(statement)
                    connection.execute(f"PRAGMA user_version={V4_SCHEMA_VERSION}")
                    _append_state_commit(
                        connection, mutation_id=None, created_at=captured_at
                    )
                    _validate_exact(connection)
                    connection.execute("COMMIT")
                    migrated_bytes = _database_page_bytes(connection)
                    if migrated_bytes > _MAX_V3_CAPTURE_BYTES:
                        raise ControlPlaneV4IOError(
                            "v4 migration publication exceeds capture limit"
                        )
                    self._fault("before_v4_serialize")
                    serialized = connection.serialize()
                    if len(serialized) > _MAX_V3_CAPTURE_BYTES:
                        raise ControlPlaneV4IOError(
                            "v4 migration publication exceeds capture limit"
                        )
                    serialized_size = len(serialized)
                    serialized_sha256 = hashlib.sha256(serialized).hexdigest()
                    connection.execute("BEGIN")
                    self._validate_unanchored_publication(captured, connection)
                except BaseException:
                    primary = sys.exception()
                    failures: list[BaseException] = []
                    if connection.in_transaction:
                        _attempt_cleanup(
                            failures, lambda: connection.execute("ROLLBACK")
                        )
                    _finish_cleanup("v4 migration transaction", failures, primary)
                    raise
                self._fault("before_v4_publication_temp")
                temporary_name, descriptor = trusted.create_temp(
                    prefix=".onyx-v4-", suffix=".sqlite3", native_only=True
                )
                temporary_identity = trusted.descriptor_identity(descriptor)
                trusted.write_all(descriptor, serialized)
                if trusted.descriptor_identity(descriptor) != temporary_identity:
                    raise ControlPlaneV4IntegrityError(
                        "v4 publication temporary identity changed"
                    )
                if (
                    os.fstat(descriptor).st_size != serialized_size
                    or trusted.hash_descriptor(descriptor)
                    != serialized_sha256
                ):
                    raise ControlPlaneV4IntegrityError(
                        "v4 publication temporary write diverges"
                    )
                if serialized_size > _MAX_V3_CAPTURE_BYTES:
                    raise ControlPlaneV4IOError(
                        "v4 migration publication exceeds capture limit"
                    )
                trusted.harden_descriptor(descriptor)
                del serialized
                self._fault("before_v4_publish")
                trusted.publish(
                    temporary_name,
                    self.path.name,
                    descriptor=descriptor,
                    expected_identity=temporary_identity,
                )
                published = True
                if trusted.descriptor_identity(descriptor) != temporary_identity:
                    raise ControlPlaneV4IntegrityError(
                        "v4 published file identity changed"
                    )
                if (
                    os.fstat(descriptor).st_size != serialized_size
                    or trusted.hash_descriptor(descriptor) != serialized_sha256
                ):
                    raise ControlPlaneV4IntegrityError(
                        "v4 published handle bytes diverge"
                    )
                self.port.bind_candidate(connection)
                candidate_bound = True
                try:
                    self._fault("after_v4_publish_before_anchor")
                    trusted._assert_pinned()
                    if (
                        trusted.file_identity(self.path.name) != temporary_identity
                        or trusted.descriptor_identity(descriptor) != temporary_identity
                    ):
                        raise ControlPlaneV4IntegrityError(
                            "v4 publication identity changed before anchor bootstrap"
                        )
                    if (
                        self.key_vault.get_bytes() is not None
                        or self.state_vault.get_bytes() is not None
                    ):
                        raise ControlPlaneV4IntegrityError(
                            "v4 anchor bootstrap target is not empty"
                        )
                    bootstrap_started = True
                    anchored = self._bootstrap_anchor(journal_capability)
                    trusted._assert_pinned()
                    if (
                        trusted.file_identity(self.path.name) != temporary_identity
                        or trusted.descriptor_identity(descriptor) != temporary_identity
                        or os.fstat(descriptor).st_size != serialized_size
                        or trusted.hash_descriptor(descriptor) != serialized_sha256
                    ):
                        raise ControlPlaneV4IntegrityError(
                            "v4 publication target changed during anchor bootstrap"
                        )
                    verified = self.anchor.verify(self.anchor_owner)
                    if anchored != verified:
                        raise ControlPlaneV4IntegrityError(
                            "v4 bootstrap verification diverges"
                        )
                    bootstrap_complete = True
                finally:
                    self.port.clear_candidate()
                    candidate_bound = False
                trusted.close_temp(descriptor)
                descriptor = None
                failures: list[BaseException] = []
                if connection.in_transaction:
                    _attempt_cleanup(
                        failures, lambda: connection.execute("ROLLBACK")
                    )
                _attempt_cleanup(failures, connection.close)
                _finish_cleanup("v4 migration connection", failures, None)
                connection = None
                trusted._assert_pinned()
                return self.open(owner)
            except BaseException:
                raise
            finally:
                primary = sys.exception()
                failures: list[BaseException] = []
                if descriptor is not None:
                    def cleanup_descriptor() -> None:
                        if published:
                            if bootstrap_complete:
                                trusted.close_temp(descriptor)
                            else:
                                trusted.discard_temp(descriptor, self.path.name)
                        else:
                            assert temporary_name is not None
                            trusted.discard_temp(descriptor, temporary_name)
                    _attempt_cleanup(failures, cleanup_descriptor)
                    descriptor = None
                if temporary_name is not None and not published:
                    def cleanup_unpublished_name() -> None:
                        try:
                            trusted._unlink_relative_required(temporary_name)
                        except FileNotFoundError:
                            pass
                    _attempt_cleanup(failures, cleanup_unpublished_name)
                if candidate_bound:
                    _attempt_cleanup(failures, self.port.clear_candidate)
                if connection is not None:
                    if connection.in_transaction:
                        _attempt_cleanup(
                            failures, lambda: connection.execute("ROLLBACK")
                        )
                    _attempt_cleanup(failures, connection.close)
                if bootstrap_started and not bootstrap_complete:
                    _attempt_cleanup(
                        failures,
                        lambda: self._rollback_new_anchor_artifacts(
                            journal_capability
                        ),
                    )
                _attempt_cleanup(failures, trusted.close)
                _finish_cleanup("v4 migration", failures, primary)

    def _validate_unanchored_publication(
        self,
        captured: _CapturedV3,
        connection: sqlite3.Connection,
    ) -> None:
        status = captured.status
        workspaces = captured.workspaces
        contexts = captured.contexts
        source_hash = captured.snapshot_sha256
        try:
            _validate_semantics(connection)
            if any(
                connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                for table in (
                    "mission_context_revisions",
                    "mission_phase_events",
                    "mutation_journal",
                )
            ):
                raise ControlPlaneV4IntegrityError(
                    "unanchored v4 publication contains operational rows"
                )
            source = [tuple(row) for row in connection.execute(
                "SELECT database_id,schema_fingerprint,state_root,anchor_sequence,source_file_sha256 "
                "FROM source_v3_provenance"
            ).fetchall()]
            if source != [
                (
                    status.database_instance_id,
                    status.schema_fingerprint,
                    status.state_root,
                    status.anchor_sequence,
                    source_hash,
                )
            ]:
                raise ControlPlaneV4IntegrityError(
                    "unanchored v4 source provenance diverges"
                )
            metadata = connection.execute(
                "SELECT key,value FROM schema_metadata ORDER BY key LIMIT 5"
            ).fetchall()
            if (
                len(metadata) != 4
                or dict(metadata).get("schema_version") != str(V4_SCHEMA_VERSION)
                or dict(metadata).get("schema_fingerprint") != _SCHEMA_FINGERPRINT
                or dict(metadata).get("source_v3_database_id") != status.database_instance_id
                or not _SAFE_ID.fullmatch(dict(metadata).get("database_id", ""))
            ):
                raise ControlPlaneV4IntegrityError("unanchored v4 metadata diverges")
            migration = connection.execute(
                "SELECT migration_id,schema_from,schema_to,status,source_root,target_fingerprint "
                "FROM migration_journal"
            ).fetchall()
            if [tuple(row) for row in migration] != [(
                V4_MIGRATION_ID, 3, 4, "applied", status.state_root, _SCHEMA_FINGERPRINT
            )]:
                raise ControlPlaneV4IntegrityError("unanchored v4 migration diverges")
            expected_workspaces = {
                str(row[0]): (
                    int(row[1]),
                    str(row[2]),
                    hashlib.sha256(str(row[3]).encode()).hexdigest(),
                    _digest(list(row)),
                )
                for row in workspaces
            }
            observed_workspaces = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT workspace_id,source_schema_version,status,payload_sha256,source_row_sha256 "
                    "FROM workspace_provenance"
                )
            }
            if observed_workspaces != expected_workspaces:
                raise ControlPlaneV4IntegrityError(
                    "unanchored v4 workspace provenance diverges"
                )
            expected_contexts = {
                str(row[0]): (
                    str(row[1]),
                    int(row[2]),
                    str(row[3]),
                    hashlib.sha256(str(row[4]).encode()).hexdigest(),
                    _digest(list(row)),
                    "pending_review" if row[3] == "PENDING_REVIEW" else "eligible",
                )
                for row in contexts
            }
            observed_contexts = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT mission_id,workspace_id,source_schema_version,source_operational_phase,"
                    "source_payload_sha256,source_row_sha256,disposition FROM legacy_context_provenance"
                )
            }
            if observed_contexts != expected_contexts:
                raise ControlPlaneV4IntegrityError(
                    "unanchored v4 mission provenance diverges"
                )
            # The complete candidate is fixed by exact schema/cardinality,
            # exact provenance sets, zero operational rows and one rederived
            # genesis state commit.  No metadata/migration/provenance extras
            # can hide behind dictionary projection.
            if _counts(connection) != dict(_logical_snapshot(connection).entity_counts):
                raise ControlPlaneV4IntegrityError("unanchored v4 row counts diverge")
        finally:
            pass

    @staticmethod
    def _validate_mutation(mutation: V4MissionMutation) -> None:
        if not isinstance(mutation, V4MissionMutation):
            raise TypeError("mutation must be V4MissionMutation")
        if mutation.operation not in {"initialize", "transition", "reconcile"}:
            raise ControlPlaneV4Conflict("v4 mutation operation is invalid")
        for name, value in (
            ("mutation_id", mutation.mutation_id), ("mission_id", mutation.mission_id),
            ("workspace_id", mutation.workspace_id), ("correlation_id", mutation.correlation_id),
        ):
            if not _SAFE_ID.fullmatch(value):
                raise ControlPlaneV4Conflict(f"v4 {name} is invalid")
        for value in (
            mutation.request_sha256, mutation.mission_snapshot_sha256,
            mutation.mission_event_sha256,
        ):
            if not _DIGEST.fullmatch(value):
                raise ControlPlaneV4Conflict("v4 mutation digest is invalid")
        if mutation.target_phase not in _V4_PHASES:
            raise ControlPlaneV4Conflict("v4 mutation phase is invalid")
        if (
            type(mutation.expected_revision) is not int
            or mutation.expected_revision < -1
            or type(mutation.mission_event_seq) is not int
            or mutation.mission_event_seq < 0
        ):
            raise ControlPlaneV4Conflict("v4 mutation revision/event sequence is invalid")
        try:
            parse_context_json(mutation.context_json)
        except MissionContextContractError as exc:
            raise ControlPlaneV4Conflict(str(exc)) from None

    @staticmethod
    def _revision_bundle(
        connection: sqlite3.Connection,
        mission_id: str,
        revision_number: int,
        *,
        current_head: sqlite3.Row,
        database_id: str,
        extra_witnesses: tuple[tuple[str, sqlite3.Row], ...] = (),
        expected_commit_sequence: int | None = None,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        mission_head = connection.execute(
            "SELECT /*v4:bundle-fetch*/ * FROM mission_head_history "
            "WHERE mission_id=? AND revision=?",
            (mission_id, revision_number),
        ).fetchone()
        if mission_head is None:
            raise ControlPlaneV4IntegrityError("v4 mission head is unavailable")
        if (
            expected_commit_sequence is not None
            and int(mission_head["commit_sequence"]) != expected_commit_sequence
        ):
            raise ControlPlaneV4IntegrityError("v4 current head-map commit diverges")
        head_values = [mission_head[key] for key in mission_head.keys() if key != "head_sha256"]
        if mission_head["head_sha256"] != _typed_record_digest("V4MissionHead.v1", head_values):
            raise ControlPlaneV4IntegrityError("v4 mission head hash diverges")
        revision = connection.execute(
            "SELECT /*v4:bundle-fetch*/ * FROM mission_context_revisions "
            "WHERE mission_id=? AND revision=?",
            (mission_id, mission_head["revision"]),
        ).fetchone()
        event = connection.execute(
            "SELECT /*v4:bundle-fetch*/ * FROM mission_phase_events "
            "WHERE mission_id=? AND revision=?",
            (mission_id, mission_head["revision"]),
        ).fetchone()
        journal = connection.execute(
            "SELECT /*v4:bundle-fetch*/ * FROM mutation_journal "
            "WHERE mission_id=? AND revision=?",
            (mission_id, mission_head["revision"]),
        ).fetchone()
        if revision is None or event is None or journal is None:
            raise ControlPlaneV4IntegrityError("v4 mission head bundle is incomplete")
        mission_witnesses = (
            ("mission_head_history", mission_head),
            ("mission_context_revisions", revision),
            ("mission_phase_events", event),
            ("mutation_journal", journal),
        )
        proofs = _verify_entry_witnesses(
            connection,
            (*mission_witnesses, *extra_witnesses),
            current_head=current_head,
            database_id=database_id,
        )
        def proven_commit(table: str, row: sqlite3.Row) -> sqlite3.Row:
            return proofs[(table, _row_identity(connection, table, row))]

        head_commit = proven_commit("mission_head_history", mission_head)
        commits = {
            int(proven_commit(table, row)["sequence"])
            for table, row in mission_witnesses[1:]
        }
        if (
            commits != {int(mission_head["commit_sequence"])}
            or int(head_commit["sequence"]) != int(mission_head["commit_sequence"])
            or (
            mission_head["commit_id"] != head_commit["commit_id"]
            or mission_head["revision_sha256"] != revision["revision_sha256"]
            or mission_head["event_sha256"] != event["event_sha256"]
            or mission_head["mutation_id"] != journal["mutation_id"]
            )
        ):
            raise ControlPlaneV4IntegrityError("v4 mission head witness diverges")
        return dict(revision), dict(event), dict(journal)

    @staticmethod
    def _mission_bundle(
        connection: sqlite3.Connection,
        mission_id: str,
        *,
        extra_witnesses: tuple[tuple[str, sqlite3.Row], ...] = (),
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        current_head = connection.execute(
            "SELECT /*v4:bundle-fetch*/ * FROM state_commits ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        metadata = dict(connection.execute(
            "SELECT /*v4:bundle-fetch*/ key,value FROM schema_metadata ORDER BY key LIMIT 5"
        ))
        if current_head is None:
            raise ControlPlaneV4IntegrityError("v4 current state head is unavailable")
        key_hash = _smt_key_hash(mission_id)
        leaf = _validate_smt_path(
            _smt_path_rows(connection, str(current_head["head_map_root"]), key_hash),
            root_hash=str(current_head["head_map_root"]), key_hash=key_hash,
        )
        if leaf is None or leaf["mission_id"] != mission_id:
            raise ControlPlaneV4IntegrityError("v4 current mission head is unavailable")
        bundle = ControlPlaneV4Store._revision_bundle(
            connection, mission_id, int(leaf["revision"]), current_head=current_head,
            database_id=str(metadata["database_id"]),
            extra_witnesses=extra_witnesses,
            expected_commit_sequence=int(leaf["commit_sequence"]),
        )
        journal = bundle[2]
        if (
            leaf["revision_sha256"] != bundle[0]["revision_sha256"]
            or leaf["event_sha256"] != bundle[1]["event_sha256"]
            or leaf["mutation_id"] != journal["mutation_id"]
        ):
            raise ControlPlaneV4IntegrityError("v4 current head-map payload diverges")
        return bundle

    def read_context_bundle(
        self, owner: V4OwnerCapability, workspace_id: str, mission_id: str
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        self.assert_operational_owner(owner)
        with self._reader_connection(owner) as connection:
            workspace = connection.execute(
                "SELECT /*v4:bundle-fetch*/ * FROM workspace_provenance WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
            if workspace is None:
                raise ControlPlaneV4Conflict("v4 workspace is unknown")
            bundle = self._mission_bundle(
                connection,
                mission_id,
                extra_witnesses=(("workspace_provenance", workspace),),
            )
            if bundle[0]["workspace_id"] != workspace_id:
                raise ControlPlaneV4Conflict("v4 mission belongs to another workspace")
            if workspace["status"] != "active":
                raise ControlPlaneV4Conflict("v4 workspace is inactive")
            return bundle

    @staticmethod
    def _read_authenticated_mission_history(
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
        mission_id: str,
        latest_revision: int,
        current_head: sqlite3.Row,
        database_id: str,
    ) -> tuple[dict[str, object], ...]:
        """Read and prove exactly revisions 0..N using fixed-size range batches.

        The public list operation is necessarily O(N) in its returned history,
        but each SQL statement has a fixed three-bind shape and never constructs
        a per-row OR/VALUES expression.  Every returned revision, event, journal,
        and mission-head row is authenticated to its commit and the current MMR.
        """
        if latest_revision < 0:
            raise ControlPlaneV4IntegrityError("v4 latest mission revision is invalid")
        events_out: list[dict[str, object]] = []
        previous_revision_sha256 = ""
        previous_event_sha256 = ""
        table_queries = {
            "mission_context_revisions": (
                "SELECT /*v4:history-range*/ * FROM mission_context_revisions "
                "WHERE mission_id=? AND revision BETWEEN ? AND ? ORDER BY revision"
            ),
            "mission_phase_events": (
                "SELECT /*v4:history-range*/ * FROM mission_phase_events "
                "WHERE mission_id=? AND revision BETWEEN ? AND ? ORDER BY revision"
            ),
            "mutation_journal": (
                "SELECT /*v4:history-range*/ * FROM mutation_journal "
                "WHERE mission_id=? AND revision BETWEEN ? AND ? ORDER BY revision"
            ),
            "mission_head_history": (
                "SELECT /*v4:history-range*/ * FROM mission_head_history "
                "WHERE mission_id=? AND revision BETWEEN ? AND ? ORDER BY revision"
            ),
        }
        for first in range(0, latest_revision + 1, _EVENT_PROOF_BATCH):
            last = min(latest_revision, first + _EVENT_PROOF_BATCH - 1)
            expected_size = last - first + 1
            batches = {
                table: connection.execute(sql, (mission_id, first, last)).fetchall()
                for table, sql in table_queries.items()
            }
            if any(len(rows) != expected_size for rows in batches.values()):
                raise ControlPlaneV4IntegrityError("v4 mission history contains a gap")
            entry_rows = tuple(
                connection.execute(
                    "SELECT /*v4:history-entry-range*/ entries.* "
                    "FROM mission_head_history AS heads "
                    "JOIN commit_entries AS entries ON entries.commit_id=heads.commit_id "
                    "WHERE heads.mission_id=? AND heads.revision BETWEEN ? AND ? "
                    "AND entries.table_name IN "
                    "('mission_context_revisions','mission_phase_events',"
                    "'mutation_journal','mission_head_history') "
                    "ORDER BY heads.revision,entries.table_name",
                    (mission_id, first, last),
                ).fetchall()
            )
            witnesses = tuple(
                (table, row)
                for table, rows in batches.items()
                for row in rows
            )
            proofs = _verify_entry_witnesses(
                connection,
                witnesses,
                current_head=current_head,
                database_id=database_id,
                entry_rows=entry_rows,
            )
            revisions = batches["mission_context_revisions"]
            events = batches["mission_phase_events"]
            journals = batches["mutation_journal"]
            heads = batches["mission_head_history"]
            for offset in range(expected_size):
                expected_revision = first + offset
                revision = revisions[offset]
                event = events[offset]
                journal = journals[offset]
                head = heads[offset]
                if any(
                    int(row["revision"]) != expected_revision
                    or str(row["mission_id"]) != mission_id
                    for row in (revision, event, journal, head)
                ):
                    raise ControlPlaneV4IntegrityError(
                        "v4 mission history sequence diverges"
                    )
                if (
                    revision["workspace_id"] != workspace_id
                    or event["workspace_id"] != workspace_id
                    or revision["previous_revision_sha256"]
                    != previous_revision_sha256
                    or event["previous_event_sha256"] != previous_event_sha256
                ):
                    raise ControlPlaneV4IntegrityError(
                        "v4 mission history linkage diverges"
                    )
                revision_values = [
                    revision[key]
                    for key in revision.keys()
                    if key != "revision_sha256"
                ]
                event_values = [
                    event[key]
                    for key in event.keys()
                    if key not in {"event_id", "event_sha256"}
                ]
                if (
                    revision["revision_sha256"]
                    != _digest(["MissionContextRevision.v1", *revision_values])
                    or event["event_sha256"]
                    != _digest(["MissionPhaseEvent.v1", *event_values])
                    or journal["result_sha256"] != revision["revision_sha256"]
                    or head["revision_sha256"] != revision["revision_sha256"]
                    or head["event_sha256"] != event["event_sha256"]
                    or head["mutation_id"] != journal["mutation_id"]
                ):
                    raise ControlPlaneV4IntegrityError(
                        "v4 mission history payload diverges"
                    )
                commits = {
                    int(
                        proofs[
                            (table, _row_identity(connection, table, row))
                        ]["sequence"]
                    )
                    for table, row in (
                        ("mission_context_revisions", revision),
                        ("mission_phase_events", event),
                        ("mutation_journal", journal),
                        ("mission_head_history", head),
                    )
                }
                if commits != {int(head["commit_sequence"])}:
                    raise ControlPlaneV4IntegrityError(
                        "v4 mission history commit binding diverges"
                    )
                previous_revision_sha256 = str(revision["revision_sha256"])
                previous_event_sha256 = str(event["event_sha256"])
                events_out.append(dict(event))
        for table in table_queries:
            extra = connection.execute(
                f"SELECT /*v4:history-tail*/ 1 FROM {table} "
                "WHERE mission_id=? AND revision>? LIMIT 1",
                (mission_id, latest_revision),
            ).fetchone()
            if extra is not None:
                raise ControlPlaneV4IntegrityError(
                    "v4 mission history exceeds authenticated head"
                )
        return tuple(events_out)

    def read_mission_events(
        self, owner: V4OwnerCapability, workspace_id: str, mission_id: str
    ) -> tuple[dict[str, object], ...]:
        with self._reader_connection(owner) as connection:
            workspace = connection.execute(
                "SELECT /*v4:bundle-fetch*/ * FROM workspace_provenance WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
            if workspace is None:
                raise ControlPlaneV4Conflict("v4 workspace is unknown")
            bundle = self._mission_bundle(
                connection,
                mission_id,
                extra_witnesses=(("workspace_provenance", workspace),),
            )
            if bundle[0]["workspace_id"] != workspace_id:
                raise ControlPlaneV4Conflict("v4 mission belongs to another workspace")
            if workspace["status"] != "active":
                raise ControlPlaneV4Conflict("v4 workspace is inactive")
            current_head = connection.execute(
                "SELECT /*v4:bundle-fetch*/ * FROM state_commits "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            metadata = dict(connection.execute(
                "SELECT /*v4:bundle-fetch*/ key,value FROM schema_metadata ORDER BY key LIMIT 5"
            ))
            return self._read_authenticated_mission_history(
                connection,
                workspace_id=workspace_id,
                mission_id=mission_id,
                latest_revision=int(bundle[0]["revision"]),
                current_head=current_head,
                database_id=str(metadata["database_id"]),
            )

    def read_revision_bundle(
        self,
        owner: V4OwnerCapability,
        workspace_id: str,
        mission_id: str,
        revision: int,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        self.assert_operational_owner(owner)
        if type(revision) is not int or revision < 0:
            raise ControlPlaneV4Conflict("v4 revision is invalid")
        with self._reader_connection(owner) as connection:
            current_head = connection.execute(
                "SELECT * FROM state_commits ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            metadata = dict(connection.execute(
                "SELECT key,value FROM schema_metadata ORDER BY key LIMIT 5"
            ))
            bundle = self._revision_bundle(
                connection, mission_id, revision, current_head=current_head,
                database_id=str(metadata["database_id"]),
            )
            if bundle[0]["workspace_id"] != workspace_id:
                raise ControlPlaneV4Conflict("v4 mission belongs to another workspace")
            return bundle

    def read_mutation_replay(
        self,
        owner: V4OwnerCapability,
        *,
        workspace_id: str,
        mission_id: str,
        mutation_id: str,
        operation: str,
        request_sha256: str,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]] | None:
        self.assert_operational_owner(owner)
        with self._reader_connection(owner) as connection:
            journal = connection.execute(
                "SELECT * FROM mutation_journal WHERE mutation_id=?", (mutation_id,)
            ).fetchone()
            if journal is None:
                return None
            if (
                journal["mission_id"] != mission_id
                or journal["operation"] != operation
                or journal["request_sha256"] != request_sha256
            ):
                raise ControlPlaneV4Conflict("v4 mutation replay diverges")
            current_head = connection.execute(
                "SELECT * FROM state_commits ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            metadata = dict(connection.execute(
                "SELECT key,value FROM schema_metadata ORDER BY key LIMIT 5"
            ))
            bundle = self._revision_bundle(
                connection, mission_id, int(journal["revision"]),
                current_head=current_head, database_id=str(metadata["database_id"]),
            )
            if bundle[0]["workspace_id"] != workspace_id:
                raise ControlPlaneV4Conflict("v4 mutation replay workspace diverges")
            return bundle

    def read_legacy_provenance(
        self, owner: V4OwnerCapability, mission_id: str
    ) -> dict[str, object] | None:
        with self._reader_connection(owner) as connection:
            row = connection.execute(
                "SELECT * FROM legacy_context_provenance WHERE mission_id=?", (mission_id,)
            ).fetchone()
            if row is None:
                return None
            current_head = connection.execute(
                "SELECT * FROM state_commits ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            metadata = dict(connection.execute(
                "SELECT key,value FROM schema_metadata ORDER BY key LIMIT 5"
            ))
            _verify_entry_witness(
                connection, table="legacy_context_provenance", row=row,
                current_head=current_head, database_id=str(metadata["database_id"]),
            )
            return dict(row)

    def apply_mission_mutation(
        self, owner: V4OwnerCapability, mutation: V4MissionMutation
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        self._validate_mutation(mutation)
        result_revision: int | None = None
        with self._writer_connection(owner, mutation) as connection:
            existing = connection.execute(
                "SELECT * FROM mutation_journal WHERE mutation_id=?", (mutation.mutation_id,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["mission_id"] != mutation.mission_id
                    or existing["operation"] != mutation.operation
                    or existing["request_sha256"] != mutation.request_sha256
                ):
                    raise ControlPlaneV4Conflict("v4 mutation replay diverges")
                result_revision = int(existing["revision"])
            else:
                workspace = connection.execute(
                    "SELECT * FROM workspace_provenance WHERE workspace_id=?",
                    (mutation.workspace_id,),
                ).fetchone()
                if workspace is None or workspace["status"] != "active":
                    raise ControlPlaneV4Conflict("v4 workspace is unavailable")
                prior = connection.execute(
                    "SELECT * FROM mission_context_revisions WHERE mission_id=? "
                    "ORDER BY revision DESC LIMIT 1", (mutation.mission_id,),
                ).fetchone()
                if mutation.workspace_id == "legacy-default":
                    provenance = connection.execute(
                        "SELECT disposition,source_row_sha256 FROM legacy_context_provenance "
                        "WHERE mission_id=?", (mutation.mission_id,),
                    ).fetchone()
                    if provenance is not None and provenance["disposition"] != "eligible":
                        raise ControlPlaneV4Conflict("v4 legacy provenance is pending review")
                    if prior is None:
                        if provenance is not None and (
                            mutation.operation != "initialize"
                            or mutation.legacy_reviewed_source_sha256
                            != provenance["source_row_sha256"]
                        ):
                            raise ControlPlaneV4Conflict(
                                "v4 legacy adoption lacks explicit reviewed provenance"
                            )
                        if provenance is None and mutation.legacy_reviewed_source_sha256 is not None:
                            raise ControlPlaneV4Conflict(
                                "v4 legacy review marker has no source provenance"
                            )
                    elif mutation.legacy_reviewed_source_sha256 is not None:
                        raise ControlPlaneV4Conflict(
                            "v4 legacy review marker is valid only at adoption"
                        )
                if mutation.operation == "initialize":
                    if prior is not None or mutation.expected_revision != -1:
                        raise ControlPlaneV4Conflict("v4 initialize predecessor diverges")
                    revision, previous_revision, previous_event, prior_phase = 0, "", "", None
                    event_type = "initialized"
                else:
                    if prior is None or int(prior["revision"]) != mutation.expected_revision:
                        raise ControlPlaneV4Conflict("v4 mutation predecessor diverges")
                    prior_phase = str(prior["operational_phase"])
                    try:
                        validate_storage_transition(
                            mutation.operation, prior_phase, mutation.target_phase
                        )
                    except MissionContextContractError as exc:
                        raise ControlPlaneV4Conflict(str(exc)) from None
                    revision = int(prior["revision"]) + 1
                    previous_revision = str(prior["revision_sha256"])
                    previous_event = str(connection.execute(
                        "SELECT event_sha256 FROM mission_phase_events WHERE mission_id=? AND revision=?",
                        (mutation.mission_id, prior["revision"]),
                    ).fetchone()[0])
                    event_type = "terminal_reconciled" if mutation.operation == "reconcile" else "transitioned"
                revision_values = [
                    mutation.mission_id, revision, mutation.workspace_id, 4,
                    mutation.correlation_id, mutation.target_phase, mutation.context_json,
                    mutation.mission_snapshot_sha256, mutation.mission_event_seq,
                    mutation.mission_event_sha256, previous_revision, mutation.created_at,
                ]
                revision_hash = _digest(["MissionContextRevision.v1", *revision_values])
                connection.execute(
                    "INSERT INTO mission_context_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (*revision_values[:-1], revision_hash, revision_values[-1]),
                )
                event_values = [
                    mutation.mission_id, revision, mutation.workspace_id, 1, event_type,
                    prior_phase, mutation.target_phase, mutation.mission_snapshot_sha256,
                    mutation.mission_event_seq, mutation.mission_event_sha256,
                    previous_event, mutation.created_at,
                ]
                event_hash = _digest(["MissionPhaseEvent.v1", *event_values])
                event_id = hashlib.sha256(
                    (f"{mutation.mission_id}\0{event_hash}" if revision == 0 else
                     f"{mutation.mission_id}\0{revision}\0{event_hash}").encode()
                ).hexdigest()
                connection.execute(
                    "INSERT INTO mission_phase_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, *event_values[:-1], event_hash, event_values[-1]),
                )
                connection.execute(
                    "INSERT INTO mutation_journal VALUES(?,?,?,?,?,?,?)",
                    (mutation.mutation_id, mutation.mission_id, revision, mutation.operation,
                     mutation.request_sha256, revision_hash, mutation.created_at),
                )
                result_revision = revision
        if result_revision is None:
            raise ControlPlaneV4IntegrityError("v4 mutation result revision is unavailable")
        # The writer lock is intentionally released before this authenticated
        # read.  Bind the result to the journal revision produced/replayed by
        # this call; a concurrent successor must never change our return value.
        self._fault("after_v4_mutation_commit_before_result_read")
        return self.read_revision_bundle(
            owner, mutation.workspace_id, mutation.mission_id, result_revision
        )

    def _recover(self) -> None:
        try:
            try:
                verified = self.anchor.verify(self.anchor_owner)
            except ledger_anchor.LedgerAnchorConflict:
                verified = self.anchor.recover(self.anchor_owner)
        except ledger_anchor.LedgerAnchorError as exc:
            raise ControlPlaneV4IntegrityError("v4 external anchor verification failed") from exc
        if verified.prepared:
            raise ControlPlaneV4IntegrityError("v4 anchor remains prepared")

    def open(self, owner: V4OwnerCapability) -> V4Status:
        self._assert_owner(owner)
        if not self.path.exists():
            raise ControlPlaneV4IOError("v4 successor is not initialized")
        with _LOCK:
            self._recover()
            connection = _connect(self.path, readonly=True)
            try:
                snapshot = _validate_semantics(connection)
            finally:
                connection.close()
            try:
                anchored = self.anchor.verify(self.anchor_owner)
            except ledger_anchor.LedgerAnchorError:
                raise ControlPlaneV4IntegrityError("v4 external anchor verification failed") from None
            if (
                anchored.database_id != snapshot.database_id
                or anchored.schema_fingerprint != snapshot.schema_fingerprint
                or anchored.ledger_root != snapshot.ledger_root
                or anchored.event_count != snapshot.event_count
            ):
                raise ControlPlaneV4IntegrityError("v4 successor anchor diverges")
            return V4Status(
                snapshot.database_id,
                V4_SCHEMA_VERSION,
                snapshot.schema_fingerprint,
                snapshot.ledger_root,
                snapshot.event_count,
                anchored.sequence,
            )

    @contextmanager
    def _reader_connection(self, owner: V4OwnerCapability) -> Iterator[sqlite3.Connection]:
        self.assert_operational_owner(owner)
        with _LOCK:
            connection: sqlite3.Connection | None = None
            try:
                identity = _secure_identity(self.path, label="v4 database")
                self._fault("before_v4_read_open")
                connection = _connect(self.path, readonly=True)
                connection.execute("BEGIN")
                self.port.bind_candidate(connection)
                with self.anchor.writer_session(self.anchor_owner) as session:
                    baseline = session.verify_baseline()
                    yield connection
                    if _secure_identity(self.path, label="v4 database") != identity:
                        raise ControlPlaneV4IntegrityError(
                            "v4 database changed during controlled read"
                        )
                    final_baseline = session.verify_baseline()
                    if final_baseline != baseline:
                        raise ControlPlaneV4IntegrityError(
                            "v4 external anchor changed during controlled read"
                        )
            except ControlPlaneV4Error:
                raise
            except ledger_anchor.LedgerAnchorError:
                raise ControlPlaneV4IntegrityError("v4 anchored read failed") from None
            except sqlite3.Error:
                raise ControlPlaneV4IntegrityError("v4 controlled read failed") from None
            finally:
                primary = sys.exception()
                failures: list[BaseException] = []
                _attempt_cleanup(failures, self.port.clear_candidate)
                if connection is not None:
                    if connection.in_transaction:
                        _attempt_cleanup(
                            failures, lambda: connection.execute("ROLLBACK")
                        )
                    _attempt_cleanup(failures, connection.close)
                _finish_cleanup("v4 controlled read", failures, primary)

    def verify_integrity(self, owner: V4OwnerCapability) -> V4Status:
        """Run the explicit O(N) cold semantic audit."""
        return self.open(owner)

    @contextmanager
    def _writer_connection(
        self, owner: V4OwnerCapability, mutation: V4MissionMutation
    ) -> Iterator[sqlite3.Connection]:
        self.assert_operational_owner(owner)
        with _LOCK:
            self._recover()
            connection: sqlite3.Connection | None = None
            try:
                with self.anchor.writer_session(self.anchor_owner) as session:
                    baseline = session.verify_baseline()
                    connection = _connect(self.path)
                    try:
                        connection.execute("BEGIN IMMEDIATE")
                        if (
                            int(connection.execute("PRAGMA user_version").fetchone()[0])
                            != V4_SCHEMA_VERSION
                            or _schema_contract(connection) != _REFERENCE_SCHEMA_CONTRACT
                        ):
                            raise ControlPlaneV4IntegrityError(
                                "v4 hot writer schema contract diverges"
                            )
                        before = _logical_snapshot(connection)
                        if before.ledger_root != baseline.ledger_root:
                            raise ControlPlaneV4Conflict("v4 baseline changed")
                        before_counts = dict(before.entity_counts)
                        current_head = connection.execute(
                            "SELECT /*v4:writer-hot*/ * FROM state_commits "
                            "ORDER BY sequence DESC LIMIT 1"
                        ).fetchone()
                        metadata = dict(connection.execute(
                            "SELECT /*v4:writer-hot*/ key,value FROM schema_metadata "
                            "ORDER BY key LIMIT 5"
                        ))
                        workspace = connection.execute(
                            "SELECT /*v4:writer-hot*/ * FROM workspace_provenance "
                            "WHERE workspace_id=?", (mutation.workspace_id,),
                        ).fetchone()
                        if workspace is None or workspace["status"] != "active":
                            raise ControlPlaneV4Conflict("v4 workspace is unavailable")
                        extra: list[tuple[str, sqlite3.Row]] = [
                            ("workspace_provenance", workspace)
                        ]
                        if mutation.workspace_id == "legacy-default":
                            legacy = connection.execute(
                                "SELECT /*v4:writer-hot*/ * FROM legacy_context_provenance "
                                "WHERE mission_id=?", (mutation.mission_id,),
                            ).fetchone()
                            if legacy is not None:
                                extra.append(("legacy_context_provenance", legacy))
                        key_hash = _smt_key_hash(mutation.mission_id)
                        leaf = _validate_smt_path(
                            _smt_path_rows(
                                connection, str(current_head["head_map_root"]), key_hash
                            ),
                            root_hash=str(current_head["head_map_root"]),
                            key_hash=key_hash,
                        )
                        if leaf is None:
                            _verify_entry_witnesses(
                                connection, tuple(extra), current_head=current_head,
                                database_id=str(metadata["database_id"]),
                            )
                            if mutation.expected_revision != -1:
                                raise ControlPlaneV4Conflict(
                                    "v4 mutation predecessor diverges"
                                )
                        else:
                            current_bundle = self._revision_bundle(
                                connection,
                                mutation.mission_id,
                                int(leaf["revision"]),
                                current_head=current_head,
                                database_id=str(metadata["database_id"]),
                                extra_witnesses=tuple(extra),
                                expected_commit_sequence=int(leaf["commit_sequence"]),
                            )
                            if current_bundle[0]["workspace_id"] != mutation.workspace_id:
                                raise ControlPlaneV4Conflict(
                                    "v4 mutation workspace diverges"
                                )
                        existing_before = connection.execute(
                            "SELECT /*v4:writer-hot*/ * FROM mutation_journal "
                            "WHERE mutation_id=?", (mutation.mutation_id,),
                        ).fetchone()
                        changes_before = connection.total_changes
                        yield connection
                        if not connection.in_transaction:
                            raise ControlPlaneV4Conflict(
                                "v4 caller ended the host transaction"
                            )
                        user_changes = connection.total_changes - changes_before
                        if user_changes == 0:
                            if existing_before is None:
                                raise ControlPlaneV4Conflict(
                                    "v4 writer produced no authorized mutation"
                                )
                            connection.execute("ROLLBACK")
                            return
                        # Each of the three authorized bundle inserts also
                        # advances one exact physical counter through its
                        # authenticated trigger.
                        if existing_before is not None or user_changes != 6:
                            raise ControlPlaneV4Conflict(
                                "v4 writer mutation shape is not authorized"
                            )
                        journal = connection.execute(
                            "SELECT /*v4:writer-hot*/ * FROM mutation_journal "
                            "WHERE mutation_id=?", (mutation.mutation_id,),
                        ).fetchone()
                        if journal is None:
                            raise ControlPlaneV4Conflict("v4 mutation journal is missing")
                        revision = connection.execute(
                            "SELECT /*v4:writer-hot*/ * FROM mission_context_revisions "
                            "WHERE mission_id=? AND revision=?",
                            (mutation.mission_id, journal["revision"]),
                        ).fetchone()
                        event = connection.execute(
                            "SELECT /*v4:writer-hot*/ * FROM mission_phase_events "
                            "WHERE mission_id=? AND revision=?",
                            (mutation.mission_id, journal["revision"]),
                        ).fetchone()
                        if revision is None or event is None:
                            raise ControlPlaneV4Conflict("v4 mutation bundle is incomplete")
                        revision_values = [
                            revision[key] for key in revision.keys()
                            if key != "revision_sha256"
                        ]
                        event_values = [
                            event[key] for key in event.keys()
                            if key not in {"event_id", "event_sha256"}
                        ]
                        if (
                            journal["mission_id"] != mutation.mission_id
                            or journal["operation"] != mutation.operation
                            or journal["request_sha256"] != mutation.request_sha256
                            or journal["result_sha256"] != revision["revision_sha256"]
                            or revision["revision_sha256"]
                            != _digest(["MissionContextRevision.v1", *revision_values])
                            or event["event_sha256"]
                            != _digest(["MissionPhaseEvent.v1", *event_values])
                        ):
                            raise ControlPlaneV4Conflict("v4 mutation bundle diverges")
                        appended = _append_state_commit(
                            connection,
                            mutation_id=mutation.mutation_id,
                            created_at=str(journal["created_at"]),
                        )
                        after = _logical_snapshot(connection)
                        after_counts = dict(after.entity_counts)
                        fixed_deltas = {
                            "mission_context_revisions": 1,
                            "mission_phase_events": 1,
                            "mutation_journal": 1,
                            "state_commits": 1,
                            "commit_entries": 4,
                            "mission_head_history": 1,
                            "head_map_leaves": 1,
                            "head_map_nodes": _SMT_DEPTH,
                        }
                        sequence = int(appended["sequence"])
                        mmr_nodes_added = int(connection.execute(
                            "SELECT /*v4:writer-hot*/ count(*) FROM mmr_nodes "
                            "WHERE commit_sequence=?", (sequence,),
                        ).fetchone()[0])
                        mmr_edges_added = 2 * int(connection.execute(
                            "SELECT /*v4:writer-hot*/ count(*) FROM mmr_nodes "
                            "WHERE commit_sequence=? AND left_hash IS NOT NULL", (sequence,),
                        ).fetchone()[0])
                        mmr_peaks_added = int(connection.execute(
                            "SELECT /*v4:writer-hot*/ count(*) FROM mmr_peaks "
                            "WHERE commit_sequence=?", (sequence,),
                        ).fetchone()[0])
                        merkle_added = int(connection.execute(
                            "SELECT /*v4:writer-hot*/ count(*) FROM entry_merkle_nodes "
                            "WHERE commit_id=?", (appended["commit_id"],),
                        ).fetchone()[0])
                        fixed_deltas.update({
                            "entry_merkle_nodes": merkle_added,
                            "mmr_nodes": mmr_nodes_added,
                            "mmr_edges": mmr_edges_added,
                            "mmr_peaks": mmr_peaks_added,
                        })
                        for table in _TABLES:
                            expected = before_counts[table] + fixed_deltas.get(table, 0)
                            if after_counts[table] != expected:
                                raise ControlPlaneV4IntegrityError(
                                    "v4 authenticated writer counts diverge"
                                )
                        proven_after = self._mission_bundle(
                            connection, mutation.mission_id,
                            extra_witnesses=(("workspace_provenance", workspace),),
                        )
                        if (
                            proven_after[0]["revision_sha256"]
                            != revision["revision_sha256"]
                            or after.ledger_root != appended["state_root"]
                        ):
                            raise ControlPlaneV4IntegrityError(
                                "v4 appended mission head diverges"
                            )
                        self.port.bind_candidate(connection)
                        self._fault("before_anchor_prepare")
                        ticket = session.prepare_candidate()
                        self._fault("after_anchor_prepare")
                        connection.execute("COMMIT")
                        self.port.clear_candidate()
                        self._fault("after_sqlite_commit")
                        finalized = session.finalize_prepared(ticket)
                        self._fault("after_anchor_finalize")
                        if finalized.ledger_root != after.ledger_root:
                            raise ControlPlaneV4IntegrityError("v4 finalized root diverges")
                        session.verify_committed()
                        reopened = _connect(self.path, readonly=True)
                        try:
                            reopened.execute("BEGIN")
                            if (
                                int(reopened.execute("PRAGMA user_version").fetchone()[0])
                                != V4_SCHEMA_VERSION
                                or _schema_contract(reopened) != _REFERENCE_SCHEMA_CONTRACT
                            ):
                                raise ControlPlaneV4IntegrityError(
                                    "v4 post-write schema contract diverges"
                                )
                            reopened_snapshot = _logical_snapshot(reopened)
                            reopened_bundle = self._mission_bundle(
                                reopened, mutation.mission_id,
                                extra_witnesses=(("workspace_provenance", workspace),),
                            )
                            if (
                                reopened_snapshot.ledger_root != after.ledger_root
                                or reopened_bundle[0]["revision_sha256"]
                                != revision["revision_sha256"]
                            ):
                                raise ControlPlaneV4IntegrityError(
                                    "v4 post-write hot proof diverges"
                                )
                        finally:
                            primary = sys.exception()
                            failures: list[BaseException] = []
                            if reopened.in_transaction:
                                _attempt_cleanup(
                                    failures, lambda: reopened.execute("ROLLBACK")
                                )
                            _attempt_cleanup(failures, reopened.close)
                            _finish_cleanup(
                                "v4 post-write verification", failures, primary
                            )
                    except BaseException:
                        primary = sys.exception()
                        failures: list[BaseException] = []
                        _attempt_cleanup(failures, self.port.clear_candidate)
                        if connection is not None and connection.in_transaction:
                            _attempt_cleanup(
                                failures, lambda: connection.execute("ROLLBACK")
                            )
                        _finish_cleanup("v4 anchored write", failures, primary)
                        raise
                    finally:
                        primary = sys.exception()
                        failures: list[BaseException] = []
                        _attempt_cleanup(failures, self.port.clear_candidate)
                        if connection is not None:
                            _attempt_cleanup(failures, connection.close)
                        _finish_cleanup("v4 writer connection", failures, primary)
            except ControlPlaneV4Error:
                raise
            except ledger_anchor.LedgerAnchorError:
                raise ControlPlaneV4IntegrityError("v4 anchored write failed") from None
            except sqlite3.Error:
                raise ControlPlaneV4IntegrityError("v4 anchored write failed") from None


@runtime_checkable
class _SecretVault(Protocol):
    def get_bytes(self) -> bytes | None: ...
    def set_bytes(self, secret: bytes | bytearray) -> None: ...
    def delete(self) -> bool: ...


def _open_for_testing(
    source: _ControlPlaneV3Migrator,
    source_owner: V3OwnerCapability,
    *,
    path: Path,
    journal_path: Path,
    key_vault: _SecretVault,
    state_vault: _SecretVault,
    enabled: bool,
) -> tuple[ControlPlaneV4Store, V4OwnerCapability]:
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    port = _V4AnchorPort(Path(path))
    anchor, anchor_owner = ledger_anchor._open_for_testing(
        port,
        journal_path=Path(journal_path),
        key_vault=key_vault,
        state_vault=state_vault,
    )
    token = secrets.token_bytes(32)
    store = ControlPlaneV4Store(
        source,
        source_owner,
        Path(path),
        anchor,
        anchor_owner,
        port,
        Path(journal_path),
        key_vault,
        state_vault,
        enabled=enabled,
        token=token,
        fixture_operational=True,
    )
    owner = V4OwnerCapability(token, _CAPABILITY_SEAL)
    _CAPABILITIES[owner] = token
    return store, owner

def open_default() -> None:
    if not control_plane_v4_enabled():
        raise ControlPlaneV4Disabled(f"{CONTROL_PLANE_V4_FLAG} is disabled")
    raise ControlPlaneV4IOError(
        "schema v4 has no production owner/anchor wiring; activation remains gated"
    )


__all__ = [
    "CONTROL_PLANE_V4_FLAG",
    "V4_SCHEMA_VERSION",
    "ControlPlaneV4Conflict",
    "ControlPlaneV4Disabled",
    "ControlPlaneV4Error",
    "ControlPlaneV4IOError",
    "ControlPlaneV4IntegrityError",
    "V4Status",
    "control_plane_v4_enabled",
    "open_default",
]
