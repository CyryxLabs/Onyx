"""Internal handle-relative Windows namespace boundary for Phase 11.

The module is deliberately inert until an enabled instance is constructed.
It centralizes worktree/mission containment, byte-range mission locking and
single-link artifact acquisition without adding a public tool or capability.
"""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Mapping

from ctypes import wintypes

from core.phase11_windows_clone_cleanup_v1 import (
    CloneCleanupContractError,
    CloneCleanupWaiting,
    FileIdentityV1,
    _FILE_SHARE_DELETE,
    _FILE_SHARE_READ,
    _FILE_SHARE_WRITE,
    _FILE_DISPOSITION_DELETE,
    _FILE_DISPOSITION_FORCE_IMAGE_SECTION_CHECK,
    _FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE,
    _FILE_DISPOSITION_INFO_EX,
    _FILE_DISPOSITION_INFO_EX_CLASS,
    _FILE_DISPOSITION_POSIX_SEMANTICS,
    _Handle,
    _FILE_RENAME_INFO_EX_HEAD,
    _FILE_RENAME_REPLACE_IF_EXISTS,
    _IO_STATUS_BLOCK,
    _NATIVE_FILE_RENAME_INFORMATION_EX_CLASS,
    _attributes_and_standard,
    _child_handle,
    _directory_has_entries,
    _directory_rows,
    _identity,
    _is_strict_descendant,
    _root_handle,
    _same_identity,
    _streams,
    _ntdll,
    _raise_rename_failure,
    _flush_directory_best_effort,
    _valid_component,
    _validate_volume,
    _kernel32 as _cleanup_kernel32,
)


_SAFE_MISSION = re.compile(r"^mis_[0-9a-f]{32}$")
_SAFE_RELATIVE_COMPONENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$"
)
_LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
_LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
_FAILED_TRUSTED_CONSTRUCTION_LOCK = threading.RLock()
_FAILED_TRUSTED_CONSTRUCTION_HANDLES: list[_Handle] = []


def _retry_transient_namespace_handle(action):
    """Retry only Windows sharing/lock races, then preserve fail-closed behavior."""

    deadline = time.monotonic() + 1.5
    delay = 0.01
    while True:
        try:
            return action()
        except CloneCleanupWaiting as exc:
            if (
                str(exc) not in {"cleanup_root_handle_busy", "cleanup_entry_handle_busy"}
                or time.monotonic() >= deadline
            ):
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.1)


def _close_trusted_construction_handles(
    handles: tuple[_Handle, ...],
) -> tuple[BaseException, ...]:
    """Close every constructor-owned handle and retain failures for retry."""

    errors: list[BaseException] = []
    failed: list[_Handle] = []
    seen: set[int] = set()
    for handle in reversed(handles):
        marker = id(handle)
        if marker in seen or handle.closed:
            continue
        seen.add(marker)
        try:
            handle.close()
        except BaseException as exc:
            errors.append(exc)
            failed.append(handle)
    if failed:
        with _FAILED_TRUSTED_CONSTRUCTION_LOCK:
            known = {
                id(handle) for handle in _FAILED_TRUSTED_CONSTRUCTION_HANDLES
            }
            _FAILED_TRUSTED_CONSTRUCTION_HANDLES.extend(
                handle for handle in failed if id(handle) not in known
            )
    return tuple(errors)


def _retry_failed_trusted_construction_cleanup() -> None:
    """Drain retained failed constructor handles before granting authority."""

    with _FAILED_TRUSTED_CONSTRUCTION_LOCK:
        pending = tuple(_FAILED_TRUSTED_CONSTRUCTION_HANDLES)
        _FAILED_TRUSTED_CONSTRUCTION_HANDLES.clear()
        # Keep the gate locked across retry and possible reattachment.  A
        # competing constructor must never observe an empty queue while an
        # older authority handle is still being retired.
        errors = _close_trusted_construction_handles(pending)
        if errors:
            raise CloneCleanupContractError(
                "phase11_trusted_constructor_cleanup_pending"
            ) from errors[0]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.LockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_OVERLAPPED),
    ]
    _kernel32.LockFileEx.restype = wintypes.BOOL
    _kernel32.UnlockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_OVERLAPPED),
    ]
    _kernel32.UnlockFileEx.restype = wintypes.BOOL
else:  # pragma: no cover - enabled construction refuses non-Windows
    _kernel32 = None

_ZERO_BLOCK = b"\0" * 65_536


def _validate_regular_single_link(handle: _Handle) -> None:
    _attributes, standard = _attributes_and_standard(handle)
    if bool(standard.Directory) or int(standard.NumberOfLinks) != 1:
        raise CloneCleanupContractError(
            "phase11_namespace_leaf_identity_invalid"
        )
    streams = _streams(handle)
    if any(name != "::$DATA" for name in streams):
        raise CloneCleanupContractError(
            "phase11_namespace_leaf_ads_refused"
        )


def _identities_equal(
    first: FileIdentityV1, second: FileIdentityV1
) -> bool:
    return (
        first.volume_serial == second.volume_serial
        and first.file_id == second.file_id
        and first.volume_guid == second.volume_guid
    )


def _read_regular_handle(handle: _Handle, max_bytes: int) -> bytes:
    _validate_regular_single_link(handle)
    _attributes, standard = _attributes_and_standard(handle)
    size = int(standard.EndOfFile)
    if size < 0 or size > max_bytes:
        raise CloneCleanupContractError(
            "phase11_namespace_artifact_size_invalid"
        )
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        amount = min(65_536, remaining)
        buffer = ctypes.create_string_buffer(amount)
        read = wintypes.DWORD()
        if not _cleanup_kernel32.ReadFile(
            handle.value,
            buffer,
            amount,
            ctypes.byref(read),
            None,
        ):
            raise CloneCleanupContractError(
                "phase11_namespace_artifact_read_failed"
            )
        if not read.value:
            break
        chunks.append(buffer.raw[: read.value])
        remaining -= int(read.value)
    content = b"".join(chunks)
    if len(content) != size:
        raise CloneCleanupContractError(
            "phase11_namespace_artifact_read_incomplete"
        )
    return content


def _write_regular_handle(
    handle: _Handle,
    content: bytes,
    *,
    fault_hook: object | None = None,
) -> None:
    _validate_regular_single_link(handle)
    distance = ctypes.c_longlong(0)
    if (
        not _cleanup_kernel32.SetFilePointerEx(
            handle.value, 0, ctypes.byref(distance), 0
        )
        or not _cleanup_kernel32.SetEndOfFile(handle.value)
    ):
        raise CloneCleanupWaiting(
            "phase11_namespace_artifact_write_waiting"
        )
    if callable(fault_hook):
        fault_hook("after_truncate")
    offset = 0
    while offset < len(content):
        amount = min(65_536, len(content) - offset)
        written = wintypes.DWORD()
        block = content[offset : offset + amount]
        if (
            not _cleanup_kernel32.WriteFile(
                handle.value,
                block,
                amount,
                ctypes.byref(written),
                None,
            )
            or int(written.value) != amount
        ):
            raise CloneCleanupWaiting(
                "phase11_namespace_artifact_write_waiting"
            )
        offset += amount
    if callable(fault_hook):
        fault_hook("after_write")
    if not _cleanup_kernel32.FlushFileBuffers(handle.value):
        raise CloneCleanupWaiting(
            "phase11_namespace_artifact_write_waiting"
        )
    if callable(fault_hook):
        fault_hook("after_flush")
    _validate_regular_single_link(handle)
    _attributes, standard = _attributes_and_standard(handle)
    if int(standard.EndOfFile) != len(content):
        raise CloneCleanupContractError(
            "phase11_namespace_artifact_write_incomplete"
        )


def _rename_handle_relative(
    target: _Handle,
    parent: _Handle,
    name: str,
    *,
    replace: bool = False,
) -> None:
    if (
        not _SAFE_RELATIVE_COMPONENT.fullmatch(name)
        or not _valid_component(name)
    ):
        raise CloneCleanupContractError(
            "phase11_namespace_relative_invalid"
        )
    if not replace and any(
        current.casefold() == name.casefold()
        for current, _is_dir, _attrs in _directory_rows(parent)
    ):
        raise CloneCleanupWaiting(
            "phase11_namespace_artifact_exists"
        )
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


def _dispose_regular_handle(handle: _Handle) -> None:
    disposition = _FILE_DISPOSITION_INFO_EX(
        _FILE_DISPOSITION_DELETE
        | _FILE_DISPOSITION_POSIX_SEMANTICS
        | _FILE_DISPOSITION_FORCE_IMAGE_SECTION_CHECK
        | _FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE
    )
    _validate_regular_single_link(handle)
    if not _cleanup_kernel32.SetFileInformationByHandle(
        handle.value,
        _FILE_DISPOSITION_INFO_EX_CLASS,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise CloneCleanupWaiting(
            "phase11_namespace_artifact_delete_waiting"
        )


def _dispose_empty_directory_handle(handle: _Handle) -> None:
    attributes, standard = _attributes_and_standard(handle)
    if (
        not bool(standard.Directory)
        or int(attributes.FileAttributes) & 0x00000400
        or _directory_has_entries(handle)
    ):
        raise CloneCleanupContractError(
            "phase11_namespace_cleanup_directory_invalid"
        )
    disposition = _FILE_DISPOSITION_INFO_EX(
        _FILE_DISPOSITION_DELETE
        | _FILE_DISPOSITION_POSIX_SEMANTICS
        | _FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE
    )
    if not _cleanup_kernel32.SetFileInformationByHandle(
        handle.value,
        _FILE_DISPOSITION_INFO_EX_CLASS,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise CloneCleanupWaiting(
            "phase11_namespace_cleanup_directory_waiting"
        )


def _remove_bounded_tree_contents(
    root: _Handle,
    *,
    max_entries: int,
    max_bytes: int,
) -> tuple[int, int]:
    entries = 0
    total_bytes = 0

    def remove_directory(directory: _Handle, depth: int) -> None:
        nonlocal entries, total_bytes
        if depth > 64:
            raise CloneCleanupContractError(
                "phase11_namespace_cleanup_depth_exceeded"
            )
        rows: list[tuple[str, bool, int]] = []
        for row in _directory_rows(directory):
            entries += 1
            if entries > max_entries:
                raise CloneCleanupWaiting(
                    "phase11_namespace_cleanup_entry_quota_exceeded"
                )
            rows.append(row)
        for name, is_directory, raw_attributes in rows:
            if raw_attributes & 0x00000400:
                raise CloneCleanupContractError(
                    "phase11_namespace_cleanup_reparse_forbidden"
                )
            with _child_handle(
                directory,
                name,
                directory=is_directory,
                exclusive=True,
                delete=True,
            ) as child:
                attributes, standard = _attributes_and_standard(child)
                if int(attributes.FileAttributes) & 0x00000400:
                    raise CloneCleanupContractError(
                        "phase11_namespace_cleanup_reparse_forbidden"
                    )
                if is_directory:
                    if not bool(standard.Directory):
                        raise CloneCleanupContractError(
                            "phase11_namespace_cleanup_type_changed"
                        )
                    remove_directory(child, depth + 1)
                    _dispose_empty_directory_handle(child)
                else:
                    if bool(standard.Directory):
                        raise CloneCleanupContractError(
                            "phase11_namespace_cleanup_type_changed"
                        )
                    size = int(standard.EndOfFile)
                    total_bytes += size
                    if total_bytes > max_bytes:
                        raise CloneCleanupWaiting(
                            "phase11_namespace_cleanup_byte_quota_exceeded"
                        )
                    _dispose_regular_handle(child)
        if _directory_has_entries(directory):
            raise CloneCleanupWaiting(
                "phase11_namespace_cleanup_directory_waiting"
            )

    remove_directory(root, 0)
    return entries, total_bytes


@dataclass(slots=True)
class WindowsCloneNamespaceSessionV1:
    namespace: "WindowsNamespaceSessionV1"
    clone: _Handle
    expected_identity: Mapping[str, object]

    def _validate_clone(self) -> None:
        self.namespace._validate_containment()
        identity = _validate_volume(self.clone)
        _attributes, standard = _attributes_and_standard(self.clone)
        if (
            not bool(standard.Directory)
            or not _same_identity(identity, self.expected_identity)
            or identity.resolved_path
            != self.expected_identity.get("resolved_path")
            or not _is_strict_descendant(
                identity.resolved_path,
                _validate_volume(self.namespace.mission).resolved_path,
            )
        ):
            raise CloneCleanupContractError(
                "phase11_namespace_clone_identity_changed"
            )

    @contextlib.contextmanager
    def parent(
        self, relative: str
    ) -> Generator[tuple[_Handle, str], None, None]:
        components = relative.replace("\\", "/").split("/")
        if (
            not components
            or any(
                not component or component in {".", ".."}
                for component in components
            )
        ):
            raise CloneCleanupContractError(
                "phase11_namespace_relative_invalid"
            )
        self._validate_clone()
        with contextlib.ExitStack() as stack:
            current = self.clone
            for component in components[:-1]:
                current = stack.enter_context(
                    _child_handle(
                        current,
                        component,
                        directory=True,
                        exclusive=False,
                        delete=False,
                        sharing_mask=(
                            _FILE_SHARE_READ | _FILE_SHARE_WRITE
                        ),
                    )
                )
                _attributes, standard = _attributes_and_standard(
                    current
                )
                if not bool(standard.Directory):
                    raise CloneCleanupContractError(
                        "phase11_namespace_ancestor_invalid"
                    )
                current_identity = _validate_volume(current)
                clone_identity = _validate_volume(self.clone)
                if not _is_strict_descendant(
                    current_identity.resolved_path,
                    clone_identity.resolved_path,
                ):
                    raise CloneCleanupContractError(
                        "phase11_namespace_ancestor_escape"
                    )
            yield current, components[-1]
            self._validate_clone()

    def read_file(self, relative: str, *, max_bytes: int) -> bytes:
        with self.parent(relative) as (parent, leaf):
            with _child_handle(
                parent,
                leaf,
                directory=False,
                exclusive=False,
                delete=False,
                sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            ) as handle:
                before = _identity(handle)
                content = _read_regular_handle(handle, max_bytes)
                after = _identity(handle)
                if (
                    before.volume_serial != after.volume_serial
                    or before.file_id != after.file_id
                ):
                    raise CloneCleanupContractError(
                        "phase11_namespace_leaf_identity_changed"
                    )
                return content

    def read_file_optional(
        self, relative: str, *, max_bytes: int
    ) -> bytes | None:
        with self.parent(relative) as (parent, leaf):
            names = {
                name
                for name, is_directory, _attrs in _directory_rows(
                    parent
                )
                if not is_directory
            }
            if leaf not in names:
                return None
        return self.read_file(relative, max_bytes=max_bytes)

    @contextlib.contextmanager
    def hold_file(
        self, relative: str
    ) -> Generator[_Handle, None, None]:
        with self.parent(relative) as (parent, leaf):
            with _child_handle(
                parent,
                leaf,
                directory=False,
                exclusive=False,
                delete=False,
                sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            ) as handle:
                _validate_regular_single_link(handle)
                before = _identity(handle)
                yield handle
                _validate_regular_single_link(handle)
                after = _identity(handle)
                if (
                    before.volume_serial != after.volume_serial
                    or before.file_id != after.file_id
                ):
                    raise CloneCleanupContractError(
                        "phase11_namespace_leaf_identity_changed"
                    )

    def write_existing(
        self,
        relative: str,
        content: bytes,
        *,
        expected_sha256: str,
        fault_hook: object | None = None,
    ) -> None:
        import hashlib

        with self.parent(relative) as (parent, leaf):
            with _child_handle(
                parent,
                leaf,
                directory=False,
                exclusive=False,
                delete=True,
                sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            ) as handle:
                before = _identity(handle)
                current = _read_regular_handle(handle, len(content) + 16_777_216)
                if hashlib.sha256(current).hexdigest() != expected_sha256:
                    raise CloneCleanupContractError(
                        "phase11_patch_preimage_changed"
                    )
                _write_regular_handle(
                    handle, content, fault_hook=fault_hook
                )
                after = _identity(handle)
                if (
                    before.volume_serial != after.volume_serial
                    or before.file_id != after.file_id
                ):
                    raise CloneCleanupContractError(
                        "phase11_namespace_leaf_identity_changed"
                    )

    def create_file(
        self,
        relative: str,
        content: bytes,
        *,
        fault_hook: object | None = None,
    ) -> None:
        with self.parent(relative) as (parent, leaf):
            try:
                handle = _child_handle(
                    parent,
                    leaf,
                    directory=False,
                    exclusive=False,
                    delete=True,
                    create=True,
                    sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
                )
            except CloneCleanupWaiting as exc:
                if str(exc) == "cleanup_entry_create_raced":
                    # A patch journal commits the exact missing target before
                    # this operation.  A new leaf at that name is therefore an
                    # adversarial preimage change, not the benign directory
                    # convergence handled by trusted-root construction.
                    raise CloneCleanupContractError(
                        "phase11_patch_add_target_raced"
                    ) from exc
                raise
            with handle:
                _validate_regular_single_link(handle)
                _write_regular_handle(
                    handle, content, fault_hook=fault_hook
                )


@dataclass(slots=True)
class WindowsArtifactWriterV1:
    handle: _Handle
    max_bytes: int
    size: int = 0
    _digest: object = None
    _finished: bool = False

    def __post_init__(self) -> None:
        self._digest = hashlib.sha256()

    def write(self, chunk: bytes) -> None:
        if self._finished or not isinstance(chunk, bytes):
            raise CloneCleanupContractError(
                "phase11_namespace_writer_state_invalid"
            )
        if self.size + len(chunk) > self.max_bytes:
            raise CloneCleanupContractError(
                "phase11_namespace_artifact_size_invalid"
            )
        offset = 0
        while offset < len(chunk):
            amount = min(65_536, len(chunk) - offset)
            written = wintypes.DWORD()
            block = chunk[offset : offset + amount]
            if (
                not _cleanup_kernel32.WriteFile(
                    self.handle.value,
                    block,
                    amount,
                    ctypes.byref(written),
                    None,
                )
                or int(written.value) != amount
            ):
                raise CloneCleanupWaiting(
                    "phase11_namespace_artifact_write_waiting"
                )
            offset += amount
        self.size += len(chunk)
        self._digest.update(chunk)

    def finish(self) -> tuple[int, str]:
        if self._finished:
            raise CloneCleanupContractError(
                "phase11_namespace_writer_state_invalid"
            )
        if not _cleanup_kernel32.FlushFileBuffers(self.handle.value):
            raise CloneCleanupWaiting(
                "phase11_namespace_artifact_write_waiting"
            )
        _validate_regular_single_link(self.handle)
        _attributes, standard = _attributes_and_standard(self.handle)
        if int(standard.EndOfFile) != self.size:
            raise CloneCleanupContractError(
                "phase11_namespace_artifact_write_incomplete"
            )
        self._finished = True
        return self.size, self._digest.hexdigest()


@dataclass(slots=True)
class WindowsNamespaceSessionV1:
    worktree: _Handle
    mission: _Handle
    mission_id: str

    @property
    def borrowed_containment_handles(
        self,
    ) -> tuple[_Handle, _Handle]:
        """Borrowed handles; consumers must never close or retain them."""
        self._validate_containment()
        return self.worktree, self.mission

    def has_entry(
        self, name: str, *, directory: bool | None = None
    ) -> bool:
        """Inspect one child name through the pinned mission handle."""
        self._validate_containment()
        for child_name, is_directory, _attrs in _directory_rows(
            self.mission
        ):
            if child_name == name and (
                directory is None or directory is is_directory
            ):
                return True
        return False

    @contextlib.contextmanager
    def clone_operation(
        self, expected_identity: Mapping[str, object]
    ) -> Generator[WindowsCloneNamespaceSessionV1, None, None]:
        """Own the authenticated clone root for one complete operation."""
        self._validate_containment()
        with _child_handle(
            self.mission,
            "clone",
            directory=True,
            exclusive=False,
            delete=False,
            sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        ) as clone:
            operation = WindowsCloneNamespaceSessionV1(
                self, clone, expected_identity
            )
            operation._validate_clone()
            try:
                yield operation
            except BaseException as primary:
                try:
                    operation._validate_clone()
                except BaseException as validation:
                    primary.add_note(
                        "clone operation post-validation failed: "
                        + type(validation).__name__
                    )
                raise
            operation._validate_clone()

    @contextlib.contextmanager
    def artifact(
        self,
        name: str,
        *,
        create: bool = False,
        delete_access: bool = False,
        deleting: bool = False,
    ) -> Generator[_Handle, None, None]:
        """Acquire one protected regular single-link mission artifact."""
        self._validate_containment()
        names = {row[0] for row in _directory_rows(self.mission)}
        if create and name in names:
            raise CloneCleanupContractError(
                "phase11_namespace_artifact_exists"
            )
        handle = _child_handle(
            self.mission,
            name,
            directory=False,
            exclusive=False,
            delete=delete_access,
            create=create,
            sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        )
        try:
            _validate_regular_single_link(handle)
            before = _identity(handle)
            try:
                yield handle
            except BaseException as primary:
                try:
                    self._validate_artifact_after(handle, before)
                except BaseException as validation:
                    primary.add_note(
                        "artifact post-validation failed: "
                        + type(validation).__name__
                    )
                raise
            if not deleting:
                self._validate_artifact_after(handle, before)
        finally:
            handle.close()

    def _validate_artifact_after(
        self, handle: _Handle, before: FileIdentityV1
    ) -> None:
        _validate_regular_single_link(handle)
        after = _identity(handle)
        if (
            after.volume_serial != before.volume_serial
            or after.file_id != before.file_id
        ):
            raise CloneCleanupContractError(
                "phase11_namespace_artifact_identity_changed"
            )
        self._validate_containment()

    def read_artifact(self, name: str, *, max_bytes: int) -> bytes:
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("artifact read bound is invalid")
        with self.artifact(name) as handle:
            _attributes, standard = _attributes_and_standard(handle)
            size = int(standard.EndOfFile)
            if size < 0 or size > max_bytes:
                raise CloneCleanupContractError(
                    "phase11_namespace_artifact_size_invalid"
                )
            chunks: list[bytes] = []
            remaining = size
            while remaining:
                block_size = min(65_536, remaining)
                buffer = ctypes.create_string_buffer(block_size)
                read = wintypes.DWORD()
                if not _cleanup_kernel32.ReadFile(
                    handle.value,
                    buffer,
                    block_size,
                    ctypes.byref(read),
                    None,
                ):
                    raise CloneCleanupContractError(
                        "phase11_namespace_artifact_read_failed"
                    )
                if not read.value:
                    break
                chunks.append(buffer.raw[: read.value])
                remaining -= read.value
            content = b"".join(chunks)
            if len(content) != size:
                raise CloneCleanupContractError(
                    "phase11_namespace_artifact_read_incomplete"
                )
            return content

    def write_artifact(
        self,
        name: str,
        content: bytes,
        *,
        create: bool,
    ) -> None:
        with self.artifact(
            name,
            create=create,
            delete_access=True,
        ) as handle:
            _write_regular_handle(handle, content)

    @contextlib.contextmanager
    def artifact_writer(
        self, name: str, *, max_bytes: int
    ) -> Generator[WindowsArtifactWriterV1, None, None]:
        with self.artifact(
            name, create=True, delete_access=True
        ) as handle:
            writer = WindowsArtifactWriterV1(handle, max_bytes)
            yield writer
            if not writer._finished:
                raise CloneCleanupContractError(
                    "phase11_namespace_writer_not_finished"
                )

    def scrub_artifact(self, name: str, *, max_bytes: int) -> bool:
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("artifact scrub bound is invalid")
        names = {row[0] for row in _directory_rows(self.mission)}
        if name not in names:
            return False
        with self.artifact(
            name, delete_access=True, deleting=True
        ) as handle:
            _attributes, standard = _attributes_and_standard(handle)
            remaining = int(standard.EndOfFile)
            if remaining < 0 or remaining > max_bytes:
                raise CloneCleanupContractError(
                    "phase11_namespace_artifact_size_invalid"
                )
            distance = ctypes.c_longlong(0)
            if not _cleanup_kernel32.SetFilePointerEx(
                handle.value, 0, ctypes.byref(distance), 0
            ):
                raise CloneCleanupWaiting(
                    "phase11_namespace_artifact_scrub_waiting"
                )
            while remaining:
                amount = min(remaining, len(_ZERO_BLOCK))
                written = wintypes.DWORD()
                if (
                    not _cleanup_kernel32.WriteFile(
                        handle.value,
                        _ZERO_BLOCK,
                        amount,
                        ctypes.byref(written),
                        None,
                    )
                    or written.value != amount
                ):
                    raise CloneCleanupWaiting(
                        "phase11_namespace_artifact_scrub_waiting"
                    )
                remaining -= amount
            if (
                not _cleanup_kernel32.FlushFileBuffers(handle.value)
                or not _cleanup_kernel32.SetFilePointerEx(
                    handle.value, 0, ctypes.byref(distance), 0
                )
                or not _cleanup_kernel32.SetEndOfFile(handle.value)
            ):
                raise CloneCleanupWaiting(
                    "phase11_namespace_artifact_scrub_waiting"
                )
            disposition = _FILE_DISPOSITION_INFO_EX(
                _FILE_DISPOSITION_DELETE
                | _FILE_DISPOSITION_POSIX_SEMANTICS
                | _FILE_DISPOSITION_FORCE_IMAGE_SECTION_CHECK
                | _FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE
            )
            _validate_regular_single_link(handle)
            if not _cleanup_kernel32.SetFileInformationByHandle(
                handle.value,
                _FILE_DISPOSITION_INFO_EX_CLASS,
                ctypes.byref(disposition),
                ctypes.sizeof(disposition),
            ):
                raise CloneCleanupWaiting(
                    "phase11_namespace_artifact_delete_waiting"
                )
        if name in {row[0] for row in _directory_rows(self.mission)}:
            raise CloneCleanupWaiting(
                "phase11_namespace_artifact_delete_waiting"
            )
        return True

    def _validate_containment(self) -> None:
        worktree = _validate_volume(self.worktree)
        mission = _validate_volume(self.mission)
        if not _is_strict_descendant(
            mission.resolved_path, worktree.resolved_path
        ):
            raise CloneCleanupContractError(
                "phase11_namespace_containment_changed"
            )

    @contextlib.contextmanager
    def lock(
        self, name: str = "mission.lock"
    ) -> Generator[_Handle, None, None]:
        self._validate_containment()
        names = {row[0] for row in _directory_rows(self.mission)}
        try:
            handle = _child_handle(
                self.mission,
                name,
                directory=False,
                exclusive=False,
                delete=False,
                create=name not in names,
                sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            )
        except CloneCleanupWaiting as exc:
            raise CloneCleanupWaiting(
                "mission_interprocess_lock_busy"
            ) from exc
        locked = False
        overlap = _OVERLAPPED()
        try:
            _validate_regular_single_link(handle)
            before = _identity(handle)
            assert _kernel32 is not None
            if not _kernel32.LockFileEx(
                handle.value,
                _LOCKFILE_EXCLUSIVE_LOCK
                | _LOCKFILE_FAIL_IMMEDIATELY,
                0,
                1,
                0,
                ctypes.byref(overlap),
            ):
                raise CloneCleanupWaiting(
                    "mission_interprocess_lock_busy"
                )
            locked = True
            _validate_regular_single_link(handle)
            current = _identity(handle)
            if (
                current.volume_serial != before.volume_serial
                or current.file_id != before.file_id
            ):
                raise CloneCleanupContractError(
                    "phase11_namespace_lock_identity_changed"
                )
            yield handle
            _validate_regular_single_link(handle)
            self._validate_containment()
        finally:
            if locked:
                assert _kernel32 is not None
                if not _kernel32.UnlockFileEx(
                    handle.value,
                    0,
                    1,
                    0,
                    ctypes.byref(overlap),
                ):
                    handle.close()
                    raise CloneCleanupContractError(
                        "mission_interprocess_unlock_failed"
                    )
            handle.close()


class WindowsTrustedDirectorySessionV1:
    """Handle-relative I/O within one permanently pinned configured root."""

    def __init__(
        self,
        boundary: "WindowsTrustedDirectoryV1",
    ) -> None:
        self._boundary = boundary

    def _components(self, relative: str) -> tuple[str, ...]:
        components = tuple(relative.replace("\\", "/").split("/"))
        if (
            not components
            or any(
                not _SAFE_RELATIVE_COMPONENT.fullmatch(component)
                or not _valid_component(component)
                for component in components
            )
        ):
            raise CloneCleanupContractError(
                "phase11_namespace_relative_invalid"
            )
        return components

    @contextlib.contextmanager
    def parent(
        self,
        relative: str,
        *,
        create_directories: bool = False,
    ) -> Generator[tuple[_Handle, str], None, None]:
        components = self._components(relative)
        self._boundary._validate()
        with contextlib.ExitStack() as stack:
            current = self._boundary.root
            for component in components[:-1]:
                names = {
                    name.casefold(): is_directory
                    for name, is_directory, _attrs in _directory_rows(
                        current
                    )
                }
                create = (
                    create_directories
                    and component.casefold() not in names
                )
                if (
                    component.casefold() in names
                    and not names[component.casefold()]
                ):
                    raise CloneCleanupContractError(
                        "phase11_namespace_ancestor_invalid"
                    )
                current = stack.enter_context(
                    _child_handle(
                        current,
                        component,
                        directory=True,
                        exclusive=False,
                        delete=False,
                        create=create,
                        sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
                        mutate_children=True,
                    )
                )
                _attributes, standard = _attributes_and_standard(current)
                if not bool(standard.Directory):
                    raise CloneCleanupContractError(
                        "phase11_namespace_ancestor_invalid"
                    )
                identity = _validate_volume(current)
                if not _is_strict_descendant(
                    identity.resolved_path,
                    self._boundary.root_identity.resolved_path,
                ):
                    raise CloneCleanupContractError(
                        "phase11_namespace_ancestor_escape"
                    )
            yield current, components[-1]
            self._boundary._validate()

    def exists(
        self, relative: str, *, directory: bool | None = None
    ) -> bool:
        with self.parent(relative) as (parent, leaf):
            for name, is_directory, _attrs in _directory_rows(parent):
                if name.casefold() == leaf.casefold():
                    return directory is None or is_directory is directory
            return False

    def publish_create(self, relative: str, content: bytes) -> None:
        if not isinstance(content, bytes):
            raise TypeError("trusted directory content must be bytes")
        with self.parent(
            relative, create_directories=True
        ) as (parent, leaf):
            if any(
                name.casefold() == leaf.casefold()
                for name, _is_dir, _attrs in _directory_rows(parent)
            ):
                raise CloneCleanupWaiting(
                    "phase11_namespace_artifact_exists"
                )
            temporary = f"tmp-{os.urandom(16).hex()}.partial"
            handle = _child_handle(
                parent,
                temporary,
                directory=False,
                exclusive=False,
                delete=True,
                create=True,
                sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            )
            published = False
            try:
                before = _identity(handle)
                _write_regular_handle(handle, content)
                _rename_handle_relative(
                    handle, parent, leaf, replace=False
                )
                published = True
                _flush_directory_best_effort(parent)
                _validate_regular_single_link(handle)
                after = _identity(handle)
                if (
                    before.volume_serial != after.volume_serial
                    or before.file_id != after.file_id
                ):
                    raise CloneCleanupContractError(
                        "phase11_namespace_artifact_identity_changed"
                    )
            finally:
                if not published:
                    try:
                        _dispose_regular_handle(handle)
                    except (
                        CloneCleanupContractError,
                        CloneCleanupWaiting,
                    ):
                        pass
                handle.close()
            self._boundary._validate()

    def publish_replace(self, relative: str, content: bytes) -> None:
        """Atomically replace one owned file beneath the pinned root handle."""

        if not isinstance(content, bytes):
            raise TypeError("trusted directory content must be bytes")
        with self.parent(
            relative, create_directories=True
        ) as (parent, leaf):
            names = {
                name.casefold(): is_directory
                for name, is_directory, _attrs in _directory_rows(parent)
            }
            existing = names.get(leaf.casefold())
            if existing is True:
                raise CloneCleanupContractError(
                    "phase11_namespace_artifact_invalid"
                )
            if existing is False:
                with _child_handle(
                    parent,
                    leaf,
                    directory=False,
                    exclusive=False,
                    delete=False,
                    sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
                ) as current:
                    _validate_regular_single_link(current)
            temporary = f"tmp-{os.urandom(16).hex()}.partial"
            handle = _child_handle(
                parent,
                temporary,
                directory=False,
                exclusive=False,
                delete=True,
                create=True,
                sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            )
            published = False
            try:
                before = _identity(handle)
                _write_regular_handle(handle, content)
                _rename_handle_relative(handle, parent, leaf, replace=True)
                published = True
                _flush_directory_best_effort(parent)
                _validate_regular_single_link(handle)
                if not _identities_equal(before, _identity(handle)):
                    raise CloneCleanupContractError(
                        "phase11_namespace_artifact_identity_changed"
                    )
            finally:
                if not published:
                    try:
                        _dispose_regular_handle(handle)
                    except (
                        CloneCleanupContractError,
                        CloneCleanupWaiting,
                    ):
                        pass
                handle.close()
            self._boundary._validate()

    @contextlib.contextmanager
    def read_held(
        self, relative: str, *, max_bytes: int
    ) -> Generator[bytes, None, None]:
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("trusted directory read bound is invalid")
        with self.parent(relative) as (parent, leaf):
            with _child_handle(
                parent,
                leaf,
                directory=False,
                exclusive=False,
                delete=False,
                sharing_mask=_FILE_SHARE_READ,
            ) as handle:
                before = _identity(handle)
                content = _read_regular_handle(handle, max_bytes)
                yield content
                if not _identities_equal(before, _identity(handle)):
                    raise CloneCleanupContractError(
                        "phase11_namespace_artifact_identity_changed"
                    )

    def read(self, relative: str, *, max_bytes: int) -> bytes:
        with self.read_held(
            relative, max_bytes=max_bytes
        ) as content:
            return content

    def read_optional(
        self, relative: str, *, max_bytes: int
    ) -> bytes | None:
        if not self.exists(relative, directory=False):
            return None
        return self.read(relative, max_bytes=max_bytes)

    @contextlib.contextmanager
    def lock(
        self, name: str = "binding.lock"
    ) -> Generator[_Handle, None, None]:
        with self.parent(name) as (parent, leaf):
            names = {
                current.casefold()
                for current, _is_dir, _attrs in _directory_rows(parent)
            }
            try:
                handle = _child_handle(
                    parent,
                    leaf,
                    directory=False,
                    exclusive=False,
                    delete=False,
                    create=leaf.casefold() not in names,
                    sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
                )
            except CloneCleanupWaiting as exc:
                raise CloneCleanupWaiting(
                    "mission_interprocess_lock_busy"
                ) from exc
            locked = False
            overlap = _OVERLAPPED()
            try:
                _validate_regular_single_link(handle)
                before = _identity(handle)
                assert _kernel32 is not None
                if not _kernel32.LockFileEx(
                    handle.value,
                    _LOCKFILE_EXCLUSIVE_LOCK
                    | _LOCKFILE_FAIL_IMMEDIATELY,
                    0,
                    1,
                    0,
                    ctypes.byref(overlap),
                ):
                    raise CloneCleanupWaiting(
                        "mission_interprocess_lock_busy"
                    )
                locked = True
                yield handle
                _validate_regular_single_link(handle)
                if not _identities_equal(before, _identity(handle)):
                    raise CloneCleanupContractError(
                        "phase11_namespace_lock_identity_changed"
                    )
                self._boundary._validate()
            finally:
                if locked:
                    assert _kernel32 is not None
                    if not _kernel32.UnlockFileEx(
                        handle.value,
                        0,
                        1,
                        0,
                        ctypes.byref(overlap),
                    ):
                        handle.close()
                        raise CloneCleanupContractError(
                            "mission_interprocess_unlock_failed"
                        )
                handle.close()


class WindowsTrustedDirectoryV1:
    """Pinned arbitrary configured root for Windows authority artifacts."""

    def __init__(
        self,
        *,
        root: str | os.PathLike[str],
        enabled: bool = False,
        allow_root_quarantine: bool = False,
        share_root_delete: bool = False,
    ) -> None:
        self.enabled = enabled is True
        self.allow_root_quarantine = allow_root_quarantine is True
        self.share_root_delete = share_root_delete is True
        self.path = Path(root)
        self.parent: _Handle | None = None
        self.root: _Handle | None = None
        self.parent_identity: FileIdentityV1 | None = None
        self.root_identity: FileIdentityV1 | None = None
        self._closed = False
        self._close_lock = threading.Lock()
        if not self.enabled:
            return
        _retry_failed_trusted_construction_cleanup()
        if (
            os.name != "nt"
            or not self.path.is_absolute()
            or self.path.name in {"", ".", ".."}
        ):
            raise CloneCleanupContractError(
                "phase11_trusted_directory_unavailable"
            )
        parent_path = self.path.parent
        existing = parent_path
        missing: list[str] = []
        while not existing.exists():
            if existing == existing.parent:
                raise CloneCleanupContractError(
                    "phase11_trusted_parent_unavailable"
                )
            missing.append(existing.name)
            existing = existing.parent
        tracked: list[_Handle] = []

        def track(handle: _Handle) -> _Handle:
            tracked.append(handle)
            return handle

        def retire(handle: _Handle) -> None:
            handle.close()
            tracked.remove(handle)

        parent = track(
            _retry_transient_namespace_handle(lambda: _root_handle(
                existing,
                exclusive=False,
                delete=False,
                sharing_mask=(
                    _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE
                ),
                mutate_children=True,
            ))
        )
        try:
            for component in reversed(missing):
                current_identity = _validate_volume(parent)
                _attributes, current_standard = (
                    _attributes_and_standard(parent)
                )
                if not bool(current_standard.Directory):
                    raise CloneCleanupContractError(
                        "phase11_trusted_parent_invalid"
                    )
                created_identity = None
                try:
                    created = track(
                        _child_handle(
                            parent,
                            component,
                            directory=True,
                            exclusive=False,
                            delete=False,
                            create=True,
                            sharing_mask=(
                                _FILE_SHARE_READ | _FILE_SHARE_WRITE
                            ),
                            mutate_children=True,
                        )
                    )
                except CloneCleanupWaiting as exc:
                    if str(exc) != "cleanup_entry_create_raced":
                        raise
                else:
                    created_identity = _validate_volume(created)
                    _attributes, created_standard = (
                        _attributes_and_standard(created)
                    )
                    if (
                        not bool(created_standard.Directory)
                        or not _is_strict_descendant(
                            created_identity.resolved_path,
                            current_identity.resolved_path,
                        )
                    ):
                        retire(created)
                        raise CloneCleanupContractError(
                            "phase11_trusted_parent_invalid"
                        )
                    retire(created)
                reopened = track(
                    _child_handle(
                        parent,
                        component,
                        directory=True,
                        exclusive=False,
                        delete=False,
                        sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
                        mutate_children=True,
                    )
                )
                reopened_identity = _validate_volume(reopened)
                if created_identity is not None and (
                    not _identities_equal(reopened_identity, created_identity)
                    or reopened_identity.resolved_path
                    != created_identity.resolved_path
                ):
                    retire(reopened)
                    raise CloneCleanupContractError(
                        "phase11_trusted_parent_identity_changed"
                    )
                retire(parent)
                parent = reopened
            parent_identity = _validate_volume(parent)
            _attributes, standard = _attributes_and_standard(parent)
            if not bool(standard.Directory):
                raise CloneCleanupContractError(
                    "phase11_trusted_parent_invalid"
                )
            children = {
                name.casefold(): is_directory
                for name, is_directory, _attrs in _directory_rows(parent)
            }
            if (
                self.path.name.casefold() in children
                and not children[self.path.name.casefold()]
            ):
                raise CloneCleanupContractError(
                    "phase11_trusted_directory_invalid"
                )
            created_root: _Handle | None = None
            if self.path.name.casefold() not in children:
                try:
                    created_root = track(
                        _child_handle(
                            parent,
                            self.path.name,
                            directory=True,
                            exclusive=False,
                            delete=self.allow_root_quarantine,
                            create=True,
                            sharing_mask=(
                                _FILE_SHARE_READ
                                | _FILE_SHARE_WRITE
                                | (
                                    _FILE_SHARE_DELETE
                                    if self.allow_root_quarantine
                                    or self.share_root_delete
                                    else 0
                                )
                            ),
                            mutate_children=True,
                        )
                    )
                except CloneCleanupWaiting as exc:
                    if str(exc) != "cleanup_entry_create_raced":
                        raise
                else:
                    if not self.allow_root_quarantine:
                        retire(created_root)
                        created_root = None
            root_handle = created_root
            if root_handle is None:
                root_handle = track(
                    _retry_transient_namespace_handle(lambda: _child_handle(
                        parent,
                        self.path.name,
                        directory=True,
                        exclusive=False,
                        delete=self.allow_root_quarantine,
                        sharing_mask=(
                            _FILE_SHARE_READ
                            | _FILE_SHARE_WRITE
                            | (
                                _FILE_SHARE_DELETE
                                if self.allow_root_quarantine
                                or self.share_root_delete
                                else 0
                            )
                        ),
                        mutate_children=True,
                    ))
                )
            try:
                root_identity = _validate_volume(root_handle)
                _attributes, standard = _attributes_and_standard(
                    root_handle
                )
                if (
                    not bool(standard.Directory)
                    or not _is_strict_descendant(
                        root_identity.resolved_path,
                        parent_identity.resolved_path,
                    )
                ):
                    raise CloneCleanupContractError(
                        "phase11_trusted_directory_invalid"
                    )
            except BaseException:
                raise
        except BaseException:
            cleanup_errors = _close_trusted_construction_handles(
                tuple(tracked)
            )
            if cleanup_errors:
                raise CloneCleanupContractError(
                    "phase11_trusted_constructor_cleanup_failed"
                ) from cleanup_errors[0]
            raise
        self.parent = parent
        self.root = root_handle
        self.parent_identity = parent_identity
        self.root_identity = root_identity
        try:
            # Final revalidation is still part of construction.  Ownership is
            # transferred out of ``tracked`` only after this check succeeds.
            self._validate()
        except BaseException:
            cleanup_errors = _close_trusted_construction_handles(
                tuple(tracked)
            )
            self.parent = None
            self.root = None
            self.parent_identity = None
            self.root_identity = None
            if cleanup_errors:
                raise CloneCleanupContractError(
                    "phase11_trusted_constructor_cleanup_failed"
                ) from cleanup_errors[0]
            raise
        tracked.clear()

    def _validate(self) -> None:
        if (
            not self.enabled
            or self._closed
            or self.parent is None
            or self.root is None
            or self.parent_identity is None
            or self.root_identity is None
        ):
            raise CloneCleanupContractError(
                "phase11_trusted_directory_closed"
            )
        current_parent = _validate_volume(self.parent)
        current_root = _validate_volume(self.root)
        _attributes, parent_standard = _attributes_and_standard(
            self.parent
        )
        _attributes, root_standard = _attributes_and_standard(self.root)
        if (
            not bool(parent_standard.Directory)
            or not bool(root_standard.Directory)
            or not _identities_equal(
                current_parent, self.parent_identity
            )
            or not _identities_equal(current_root, self.root_identity)
            or current_parent.resolved_path
            != self.parent_identity.resolved_path
            or current_root.resolved_path != self.root_identity.resolved_path
            or not _is_strict_descendant(
                current_root.resolved_path,
                current_parent.resolved_path,
            )
        ):
            raise CloneCleanupContractError(
                "phase11_trusted_directory_identity_changed"
            )

    @contextlib.contextmanager
    def session(
        self,
    ) -> Generator[WindowsTrustedDirectorySessionV1, None, None]:
        self._validate()
        assert self.root is not None
        session = WindowsTrustedDirectorySessionV1(self)
        yield session
        self._validate()

    def quarantine_root(self, name: str) -> Path:
        """Atomically detach this root under its still-pinned parent."""
        self._validate()
        if (
            not _SAFE_RELATIVE_COMPONENT.fullmatch(name)
            or not _valid_component(name)
            or self.root is None
            or self.parent is None
            or self.root_identity is None
            or self.parent_identity is None
            or not self.allow_root_quarantine
        ):
            raise CloneCleanupContractError(
                "phase11_trusted_quarantine_invalid"
            )
        before = _validate_volume(self.root)
        _rename_handle_relative(self.root, self.parent, name, replace=False)
        _flush_directory_best_effort(self.parent)
        after = _validate_volume(self.root)
        if (
            not _identities_equal(before, after)
            or not _is_strict_descendant(
                after.resolved_path,
                self.parent_identity.resolved_path,
            )
            or Path(after.resolved_path).name.casefold() != name.casefold()
        ):
            raise CloneCleanupContractError(
                "phase11_trusted_quarantine_identity_changed"
            )
        self.path = self.path.parent / name
        self.root_identity = after
        self._validate()
        return self.path

    def remove_root_tree(
        self,
        *,
        max_entries: int = 20_000,
        max_bytes: int = 64 * 1024 * 1024,
    ) -> tuple[int, int]:
        """Remove this quarantined root through held relative handles."""
        self._validate()
        if (
            not self.allow_root_quarantine
            or self.root is None
            or self.parent is None
            or type(max_entries) is not int
            or not 1 <= max_entries <= 20_000
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 64 * 1024 * 1024
        ):
            raise CloneCleanupContractError(
                "phase11_trusted_cleanup_invalid"
            )
        entries, total_bytes = _remove_bounded_tree_contents(
            self.root,
            max_entries=max_entries,
            max_bytes=max_bytes,
        )
        _dispose_empty_directory_handle(self.root)
        _flush_directory_best_effort(self.parent)
        return entries, total_bytes

    def close(self) -> None:
        # Retire handles in a serialized two-phase transaction.  Each slot is
        # cleared only after its _Handle confirms CloseHandle success, so a
        # partial failure is retryable and confirmed handles are never closed
        # twice.  The boundary itself commits closed only after both releases.
        with self._close_lock:
            if self._closed:
                return
            errors: list[BaseException] = []
            for name in ("root", "parent"):
                handle = getattr(self, name)
                if handle is None:
                    continue
                try:
                    handle.close()
                except BaseException as exc:
                    errors.append(exc)
                else:
                    setattr(self, name, None)
            if errors:
                raise CloneCleanupContractError(
                    "phase11_trusted_directory_close_failed"
                ) from errors[0]
            self._closed = True


class WindowsNamespaceV1:
    def __init__(
        self,
        *,
        worktree_root: str | os.PathLike[str],
        enabled: bool = False,
    ) -> None:
        self.enabled = enabled is True
        self.worktree_root = Path(worktree_root)
        if not self.enabled:
            return
        if os.name != "nt" or not self.worktree_root.is_absolute():
            raise CloneCleanupContractError(
                "phase11_windows_namespace_unavailable"
            )

    @contextlib.contextmanager
    def mission(
        self, mission_id: str
    ) -> Generator[WindowsNamespaceSessionV1, None, None]:
        if not self.enabled or not _SAFE_MISSION.fullmatch(mission_id):
            raise CloneCleanupContractError(
                "phase11_namespace_mission_invalid"
            )
        with _root_handle(
            self.worktree_root,
            exclusive=False,
            delete=False,
            sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        ) as worktree:
            _attributes_and_standard(worktree)
            with _child_handle(
                worktree,
                mission_id,
                directory=True,
                exclusive=False,
                delete=False,
                sharing_mask=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            ) as mission:
                _attributes_and_standard(mission)
                session = WindowsNamespaceSessionV1(
                    worktree, mission, mission_id
                )
                session._validate_containment()
                yield session
                session._validate_containment()
