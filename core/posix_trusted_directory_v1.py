"""Descriptor-bound trusted-directory authority for macOS and Linux."""

from __future__ import annotations

import contextlib
import os
import platform
import re
import sqlite3
import stat
import tempfile
import threading
from collections.abc import Generator
from pathlib import Path

from core.host_security_boundary_v1 import (
    HostSecurityBoundaryBusy,
    HostSecurityBoundaryError,
)

try:  # pragma: no cover - the import is exercised on native POSIX CI.
    import fcntl
except ImportError:  # pragma: no cover - expected on Windows.
    fcntl = None  # type: ignore[assignment]


_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _file_flags() -> int:
    return getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _components(relative: str) -> tuple[str, ...]:
    if not isinstance(relative, str):
        raise TypeError("trusted directory relative path must be text")
    parts = tuple(relative.replace("\\", "/").split("/"))
    if not parts or any(
        not part or part in {".", ".."} or _SAFE_COMPONENT.fullmatch(part) is None
        for part in parts
    ):
        raise HostSecurityBoundaryError("posix_relative_path_invalid")
    return parts


def _identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _validate_directory_info(info: os.stat_result, *, secure: bool) -> None:
    if not stat.S_ISDIR(info.st_mode):
        raise HostSecurityBoundaryError("posix_trusted_directory_invalid")
    if secure and (
        int(info.st_uid) != os.geteuid()
        or stat.S_IMODE(info.st_mode) != _DIRECTORY_MODE
    ):
        raise HostSecurityBoundaryError("posix_trusted_directory_permissions_invalid")


def _validate_file_info(info: os.stat_result) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or int(info.st_uid) != os.geteuid()
        or stat.S_IMODE(info.st_mode) != _FILE_MODE
        or int(info.st_nlink) != 1
    ):
        raise HostSecurityBoundaryError("posix_trusted_file_invalid")


class PosixFileLockLeaseV1:
    """Owned lock over one pinned parent/name/file identity tuple.

    Locking only the file descriptor is insufficient: an owner-equivalent
    process can unlink the name, create a new inode, and acquire ``flock`` on
    that replacement while the original inode remains locked.  The retained
    parent-directory lease serializes every compliant acquisition beneath that
    parent, while the identity checks make any out-of-band name substitution a
    typed fail-closed condition.
    """

    def __init__(
        self,
        descriptor: int,
        *,
        parent_descriptor: int,
        leaf: str,
        parent_identity: tuple[int, int],
        file_identity: tuple[int, int],
    ) -> None:
        self._descriptor = descriptor
        self._parent_descriptor = parent_descriptor
        self._leaf = leaf
        self._parent_identity = parent_identity
        self._file_identity = file_identity
        self._closed = False
        self._guard = threading.RLock()

    def _validate(self) -> None:
        if self._closed or self._descriptor < 0 or self._parent_descriptor < 0:
            raise HostSecurityBoundaryError("posix_file_lock_lease_closed")
        try:
            parent = os.fstat(self._parent_descriptor)
            _validate_directory_info(parent, secure=True)
            if _identity(parent) != self._parent_identity:
                raise HostSecurityBoundaryError("posix_lock_parent_identity_changed")

            pinned = os.fstat(self._descriptor)
            _validate_file_info(pinned)
            if _identity(pinned) != self._file_identity:
                raise HostSecurityBoundaryError("posix_lock_file_identity_changed")

            named = os.stat(
                self._leaf,
                dir_fd=self._parent_descriptor,
                follow_symlinks=False,
            )
            _validate_file_info(named)
            if _identity(named) != self._file_identity:
                raise HostSecurityBoundaryError("posix_lock_file_identity_changed")
        except HostSecurityBoundaryError:
            raise
        except (FileNotFoundError, OSError) as exc:
            raise HostSecurityBoundaryError("posix_lock_file_identity_changed") from exc

    def validate(self) -> None:
        """Prove that the held descriptor is still the named lock inode."""

        with self._guard:
            self._validate()

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            descriptor = self._descriptor
            parent_descriptor = self._parent_descriptor
            validation_error: BaseException | None = None
            try:
                self._validate()
            except BaseException as exc:
                validation_error = exc
            # Relinquish ownership before either syscall.  A failing close can
            # still have closed the kernel fd; retaining the integer would let
            # a retry close an unrelated descriptor recycled into that slot.
            self._descriptor = -1
            self._parent_descriptor = -1
            self._closed = True
            assert fcntl is not None
            release_errors: list[BaseException] = []
            for owned_descriptor in (descriptor, parent_descriptor):
                try:
                    fcntl.flock(owned_descriptor, fcntl.LOCK_UN)
                except BaseException as exc:
                    release_errors.append(exc)
                try:
                    os.close(owned_descriptor)
                except BaseException as exc:
                    release_errors.append(exc)
            if validation_error is not None:
                raise validation_error
            if release_errors:
                raise HostSecurityBoundaryError(
                    "posix_file_lock_release_failed"
                ) from release_errors[0]

    def __enter__(self) -> "PosixFileLockLeaseV1":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class PosixDescriptorPathLeaseV1:
    """Pinned POSIX directory descriptor exposed through the host fd VFS.

    SQLite cannot consume ``openat`` descriptors directly.  Linux and macOS
    expose a live directory descriptor as a traversable VFS path.  This lease
    proves that the selected alias resolves to the exact pinned directory and
    keeps the duplicated descriptor alive for the entire SQLite connection.
    """

    def __init__(self, descriptor: int, leaf: str) -> None:
        if os.name != "posix" or descriptor < 0:
            raise HostSecurityBoundaryError("posix_descriptor_path_unavailable")
        _components(leaf)
        if "/" in leaf or "\\" in leaf:
            raise HostSecurityBoundaryError("posix_descriptor_leaf_invalid")
        system = platform.system()
        if system == "Linux":
            alias_root = f"/proc/self/fd/{descriptor}"
        elif system == "Darwin":
            alias_root = f"/dev/fd/{descriptor}"
        else:
            raise HostSecurityBoundaryError("posix_descriptor_host_unsupported")
        try:
            pinned = os.fstat(descriptor)
            aliased = os.stat(alias_root, follow_symlinks=True)
            _validate_directory_info(pinned, secure=True)
            _validate_directory_info(aliased, secure=True)
            if _identity(pinned) != _identity(aliased):
                raise HostSecurityBoundaryError(
                    "posix_descriptor_alias_identity_changed"
                )
        except HostSecurityBoundaryError:
            raise
        except OSError as exc:
            raise HostSecurityBoundaryError(
                "posix_descriptor_path_unavailable"
            ) from exc
        self._descriptor = descriptor
        self._leaf = leaf
        self._alias_root = alias_root
        self._root_identity = _identity(pinned)
        self._closed = False
        self._guard = threading.RLock()

    @property
    def path(self) -> str:
        with self._guard:
            self._validate()
            return f"{self._alias_root}/{self._leaf}"

    def _validate(self) -> None:
        if self._closed or self._descriptor < 0:
            raise HostSecurityBoundaryError("posix_descriptor_path_closed")
        pinned = os.fstat(self._descriptor)
        aliased = os.stat(self._alias_root, follow_symlinks=True)
        _validate_directory_info(pinned, secure=True)
        _validate_directory_info(aliased, secure=True)
        if (
            _identity(pinned) != self._root_identity
            or _identity(aliased) != self._root_identity
        ):
            raise HostSecurityBoundaryError("posix_descriptor_alias_identity_changed")

    def _stat(self, suffix: str = "") -> os.stat_result:
        if suffix not in {"", "-wal", "-shm"}:
            raise HostSecurityBoundaryError("posix_descriptor_suffix_invalid")
        with self._guard:
            self._validate()
            info = os.stat(
                self._leaf + suffix,
                dir_fd=self._descriptor,
                follow_symlinks=False,
            )
            _validate_file_info(info)
            return info

    def exists(self, suffix: str = "") -> bool:
        try:
            self._stat(suffix)
        except FileNotFoundError:
            return False
        return True

    def prepare_sqlite_main(self) -> bool:
        """Create/validate the main 0600 file and prove alias traversal."""

        with self._guard:
            self._validate()
            existing = True
            try:
                descriptor = os.open(
                    self._leaf,
                    os.O_RDWR | _file_flags(),
                    dir_fd=self._descriptor,
                )
            except FileNotFoundError:
                existing = False
                descriptor = os.open(
                    self._leaf,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | _file_flags(),
                    _FILE_MODE,
                    dir_fd=self._descriptor,
                )
            try:
                direct = os.fstat(descriptor)
                _validate_file_info(direct)
                alias = os.open(
                    f"{self._alias_root}/{self._leaf}",
                    os.O_RDWR | _file_flags(),
                )
                try:
                    aliased = os.fstat(alias)
                    _validate_file_info(aliased)
                    if _identity(direct) != _identity(aliased):
                        raise HostSecurityBoundaryError(
                            "posix_descriptor_file_identity_changed"
                        )
                finally:
                    os.close(alias)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return existing

    def identity(self) -> tuple[int, int, int]:
        info = self._stat()
        return (
            int(info.st_dev),
            int(info.st_ino),
            int(getattr(info, "st_birthtime_ns", 0)),
        )

    def storage_signature(self) -> tuple[tuple[str, int, int], ...]:
        result: list[tuple[str, int, int]] = []
        for suffix in ("", "-wal"):
            try:
                info = self._stat(suffix)
            except FileNotFoundError:
                continue
            result.append((suffix, int(info.st_size), int(info.st_mtime_ns)))
        return tuple(result)

    def validate_sqlite_files(self) -> None:
        self._stat()
        for suffix in ("-wal", "-shm"):
            try:
                self._stat(suffix)
            except FileNotFoundError:
                continue

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            descriptor = self._descriptor
            self._descriptor = -1
            self._closed = True
            if descriptor >= 0:
                os.close(descriptor)

    def __enter__(self) -> "PosixDescriptorPathLeaseV1":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class PosixTrustedDirectorySessionV1:
    """Operations anchored beneath a live ``PosixTrustedDirectoryV1`` fd."""

    def __init__(self, boundary: "PosixTrustedDirectoryV1") -> None:
        self._boundary = boundary

    @contextlib.contextmanager
    def _parent(
        self,
        relative: str,
        *,
        create_directories: bool = False,
    ) -> Generator[tuple[int, str], None, None]:
        parts = _components(relative)
        self._boundary._validate()
        descriptor = os.dup(self._boundary._descriptor)
        try:
            for component in parts[:-1]:
                try:
                    child = os.open(component, _directory_flags(), dir_fd=descriptor)
                except FileNotFoundError:
                    if not create_directories:
                        raise HostSecurityBoundaryError(
                            "posix_trusted_ancestor_missing"
                        ) from None
                    try:
                        os.mkdir(component, _DIRECTORY_MODE, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(component, _directory_flags(), dir_fd=descriptor)
                info = os.fstat(child)
                try:
                    _validate_directory_info(info, secure=True)
                except BaseException:
                    os.close(child)
                    raise
                os.close(descriptor)
                descriptor = child
            yield descriptor, parts[-1]
            self._boundary._validate()
        except OSError as exc:
            raise HostSecurityBoundaryError(
                "posix_trusted_path_operation_failed"
            ) from exc
        finally:
            os.close(descriptor)

    def exists(self, relative: str, *, directory: bool | None = None) -> bool:
        with self._parent(relative) as (parent, leaf):
            try:
                info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return False
            if stat.S_ISLNK(info.st_mode):
                raise HostSecurityBoundaryError("posix_trusted_leaf_linked")
            if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
                raise HostSecurityBoundaryError("posix_trusted_leaf_invalid")
            is_directory = stat.S_ISDIR(info.st_mode)
            return directory is None or is_directory is directory

    def ensure_directory(self, relative: str) -> None:
        """Create and pin one private directory below the trusted root."""

        with self._parent(relative, create_directories=True) as (parent, leaf):
            try:
                os.mkdir(leaf, _DIRECTORY_MODE, dir_fd=parent)
            except FileExistsError:
                pass
            descriptor = os.open(leaf, _directory_flags(), dir_fd=parent)
            try:
                _validate_directory_info(os.fstat(descriptor), secure=True)
            finally:
                os.close(descriptor)
            os.fsync(parent)

    def remove_tree(
        self,
        relative: str,
        *,
        max_entries: int = 4_096,
        max_bytes: int = 64 * 1024 * 1024,
        max_depth: int = 32,
        expected_identity: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        """Remove one private subtree after a complete descriptor-bound scan."""

        if (
            type(max_entries) is not int
            or not 1 <= max_entries <= 20_000
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 256 * 1024 * 1024
            or type(max_depth) is not int
            or not 1 <= max_depth <= 64
            or expected_identity is not None
            and (
                type(expected_identity) is not tuple
                or len(expected_identity) != 2
                or any(type(value) is not int or value < 0 for value in expected_identity)
            )
        ):
            raise HostSecurityBoundaryError("posix_trusted_cleanup_bound_invalid")

        entries = 0
        total_bytes = 0

        def scan(descriptor: int, depth: int) -> dict[str, object]:
            nonlocal entries, total_bytes
            if depth > max_depth:
                raise HostSecurityBoundaryError(
                    "posix_trusted_cleanup_depth_exceeded"
                )
            children: dict[str, object] = {}
            try:
                names = sorted(os.listdir(descriptor))
            except OSError as exc:
                raise HostSecurityBoundaryError(
                    "posix_trusted_cleanup_enumeration_failed"
                ) from exc
            for name in names:
                if _SAFE_COMPONENT.fullmatch(name) is None:
                    raise HostSecurityBoundaryError(
                        "posix_trusted_cleanup_entry_invalid"
                    )
                try:
                    info = os.stat(
                        name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise HostSecurityBoundaryError(
                        "posix_trusted_cleanup_entry_changed"
                    ) from exc
                entries += 1
                if entries > max_entries:
                    raise HostSecurityBoundaryError(
                        "posix_trusted_cleanup_entry_bound_exceeded"
                    )
                if stat.S_ISDIR(info.st_mode):
                    _validate_directory_info(info, secure=True)
                    child = os.open(name, _directory_flags(), dir_fd=descriptor)
                    try:
                        pinned = os.fstat(child)
                        _validate_directory_info(pinned, secure=True)
                        if _identity(pinned) != _identity(info):
                            raise HostSecurityBoundaryError(
                                "posix_trusted_cleanup_entry_changed"
                            )
                        descendants = scan(child, depth + 1)
                    finally:
                        os.close(child)
                    children[name] = (
                        "directory",
                        _identity(info),
                        descendants,
                    )
                    continue
                _validate_file_info(info)
                total_bytes += int(info.st_size)
                if total_bytes > max_bytes:
                    raise HostSecurityBoundaryError(
                        "posix_trusted_cleanup_byte_bound_exceeded"
                    )
                children[name] = ("file", _identity(info), int(info.st_size))
            return children

        def remove(descriptor: int, manifest: dict[str, object]) -> None:
            try:
                current_names = set(os.listdir(descriptor))
            except OSError as exc:
                raise HostSecurityBoundaryError(
                    "posix_trusted_cleanup_enumeration_failed"
                ) from exc
            if current_names != set(manifest):
                raise HostSecurityBoundaryError(
                    "posix_trusted_cleanup_entry_changed"
                )
            for name in sorted(manifest):
                expected = manifest[name]
                assert isinstance(expected, tuple)
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if _identity(info) != expected[1]:
                    raise HostSecurityBoundaryError(
                        "posix_trusted_cleanup_entry_changed"
                    )
                if expected[0] == "directory":
                    _validate_directory_info(info, secure=True)
                    child = os.open(name, _directory_flags(), dir_fd=descriptor)
                    try:
                        if _identity(os.fstat(child)) != expected[1]:
                            raise HostSecurityBoundaryError(
                                "posix_trusted_cleanup_entry_changed"
                            )
                        descendants = expected[2]
                        assert isinstance(descendants, dict)
                        remove(child, descendants)
                    finally:
                        os.close(child)
                    os.rmdir(name, dir_fd=descriptor)
                else:
                    _validate_file_info(info)
                    if int(info.st_size) != expected[2]:
                        raise HostSecurityBoundaryError(
                            "posix_trusted_cleanup_entry_changed"
                        )
                    os.unlink(name, dir_fd=descriptor)
            os.fsync(descriptor)

        with self._parent(relative) as (parent, leaf):
            root_info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            _validate_directory_info(root_info, secure=True)
            if (
                expected_identity is not None
                and _identity(root_info) != expected_identity
            ):
                raise HostSecurityBoundaryError(
                    "posix_trusted_cleanup_root_identity_mismatch"
                )
            root = os.open(leaf, _directory_flags(), dir_fd=parent)
            try:
                pinned = os.fstat(root)
                _validate_directory_info(pinned, secure=True)
                if _identity(pinned) != _identity(root_info):
                    raise HostSecurityBoundaryError(
                        "posix_trusted_cleanup_root_changed"
                    )
                manifest = scan(root, 1)
                remove(root, manifest)
            finally:
                os.close(root)
            named = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            _validate_directory_info(named, secure=True)
            if _identity(named) != _identity(root_info):
                raise HostSecurityBoundaryError(
                    "posix_trusted_cleanup_root_changed"
                )
            os.rmdir(leaf, dir_fd=parent)
            os.fsync(parent)
        return entries, total_bytes

    def publish_create(self, relative: str, content: bytes) -> None:
        if not isinstance(content, bytes):
            raise TypeError("trusted directory content must be bytes")
        with self._parent(relative, create_directories=True) as (parent, leaf):
            temporary = f"tmp-{os.urandom(16).hex()}.partial"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _file_flags(),
                _FILE_MODE,
                dir_fd=parent,
            )
            linked = False
            try:
                view = memoryview(content)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise HostSecurityBoundaryError(
                            "posix_trusted_file_write_failed"
                        )
                    view = view[written:]
                os.fsync(descriptor)
                _validate_file_info(os.fstat(descriptor))
                try:
                    os.link(
                        temporary,
                        leaf,
                        src_dir_fd=parent,
                        dst_dir_fd=parent,
                        follow_symlinks=False,
                    )
                except FileExistsError as exc:
                    raise HostSecurityBoundaryBusy(
                        "posix_trusted_artifact_exists"
                    ) from exc
                linked = True
            finally:
                os.close(descriptor)
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
            if not linked:
                raise HostSecurityBoundaryError("posix_trusted_publish_failed")
            published = os.open(leaf, os.O_RDONLY | _file_flags(), dir_fd=parent)
            try:
                _validate_file_info(os.fstat(published))
            finally:
                os.close(published)
            os.fsync(parent)

    def publish_replace(self, relative: str, content: bytes) -> None:
        """Atomically replace one owned regular file under the pinned root."""

        if not isinstance(content, bytes):
            raise TypeError("trusted directory content must be bytes")
        with self._parent(relative, create_directories=True) as (parent, leaf):
            try:
                current = os.open(leaf, os.O_RDONLY | _file_flags(), dir_fd=parent)
            except FileNotFoundError:
                current = -1
            if current >= 0:
                try:
                    _validate_file_info(os.fstat(current))
                finally:
                    os.close(current)
            temporary = f"tmp-{os.urandom(16).hex()}.partial"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _file_flags(),
                _FILE_MODE,
                dir_fd=parent,
            )
            try:
                view = memoryview(content)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise HostSecurityBoundaryError(
                            "posix_trusted_file_write_failed"
                        )
                    view = view[written:]
                os.fsync(descriptor)
                _validate_file_info(os.fstat(descriptor))
                os.replace(
                    temporary,
                    leaf,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                )
            finally:
                os.close(descriptor)
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
            published = os.open(leaf, os.O_RDONLY | _file_flags(), dir_fd=parent)
            try:
                _validate_file_info(os.fstat(published))
            finally:
                os.close(published)
            os.fsync(parent)

    def read(self, relative: str, *, max_bytes: int) -> bytes:
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("trusted directory read bound is invalid")
        with self._parent(relative) as (parent, leaf):
            descriptor = os.open(leaf, os.O_RDONLY | _file_flags(), dir_fd=parent)
            try:
                before = os.fstat(descriptor)
                _validate_file_info(before)
                remaining = max_bytes + 1
                chunks: list[bytes] = []
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 64 * 1024))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                content = b"".join(chunks)
                if len(content) > max_bytes:
                    raise HostSecurityBoundaryError("posix_trusted_read_bound_exceeded")
                after = os.fstat(descriptor)
                _validate_file_info(after)
                if _identity(before) != _identity(after):
                    raise HostSecurityBoundaryError(
                        "posix_trusted_file_identity_changed"
                    )
                return content
            finally:
                os.close(descriptor)

    def read_optional(self, relative: str, *, max_bytes: int) -> bytes | None:
        if not self.exists(relative, directory=False):
            return None
        try:
            return self.read(relative, max_bytes=max_bytes)
        except FileNotFoundError:
            return None

    def descriptor_path(self, relative: str) -> PosixDescriptorPathLeaseV1:
        """Pin the parent of one leaf for descriptor-bound native consumers."""

        with self._parent(relative, create_directories=True) as (parent, leaf):
            return PosixDescriptorPathLeaseV1(os.dup(parent), leaf)

    @contextlib.contextmanager
    def lock(
        self, name: str = "binding.lock"
    ) -> Generator[PosixFileLockLeaseV1, None, None]:
        lease = self._boundary.acquire_lock(name)
        try:
            yield lease
        finally:
            lease.close()


class PosixTrustedDirectoryV1:
    """Pin a private 0700 directory and reject name or identity drift."""

    def __init__(
        self,
        *,
        root: str | os.PathLike[str],
        enabled: bool = False,
    ) -> None:
        self.enabled = enabled is True
        self.path = Path(root)
        self._descriptor = -1
        self._root_identity: tuple[int, int] | None = None
        self._closed = False
        self._guard = threading.RLock()
        if not self.enabled:
            return
        if os.name != "posix" or not self.path.is_absolute() or self.path == Path("/"):
            raise HostSecurityBoundaryError("posix_trusted_directory_unavailable")
        self._descriptor = self._open_root(create=True)
        try:
            info = os.fstat(self._descriptor)
            _validate_directory_info(info, secure=True)
            self._root_identity = _identity(info)
            self._validate()
        except BaseException:
            os.close(self._descriptor)
            self._descriptor = -1
            raise

    def _open_root(self, *, create: bool) -> int:
        try:
            descriptor = os.open("/", _directory_flags())
        except OSError as exc:
            raise HostSecurityBoundaryError(
                "posix_trusted_directory_open_failed"
            ) from exc
        try:
            for component in self.path.parts[1:]:
                try:
                    child = os.open(component, _directory_flags(), dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(component, _DIRECTORY_MODE, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(component, _directory_flags(), dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except OSError as exc:
            os.close(descriptor)
            raise HostSecurityBoundaryError(
                "posix_trusted_directory_open_failed"
            ) from exc
        except BaseException:
            os.close(descriptor)
            raise

    def _validate(self) -> None:
        with self._guard:
            if (
                not self.enabled
                or self._closed
                or self._descriptor < 0
                or self._root_identity is None
            ):
                raise HostSecurityBoundaryError("posix_trusted_directory_closed")
            pinned = os.fstat(self._descriptor)
            _validate_directory_info(pinned, secure=True)
            reopened = self._open_root(create=False)
            try:
                named = os.fstat(reopened)
                _validate_directory_info(named, secure=True)
                if (
                    _identity(pinned) != self._root_identity
                    or _identity(named) != self._root_identity
                ):
                    raise HostSecurityBoundaryError(
                        "posix_trusted_directory_identity_changed"
                    )
            finally:
                os.close(reopened)

    @contextlib.contextmanager
    def session(self) -> Generator[PosixTrustedDirectorySessionV1, None, None]:
        self._validate()
        yield PosixTrustedDirectorySessionV1(self)
        self._validate()

    def acquire_lock(self, relative: str) -> PosixFileLockLeaseV1:
        if fcntl is None:
            raise HostSecurityBoundaryError("posix_file_lock_unavailable")
        descriptor = -1
        parent_descriptor = -1
        parent_locked = False
        file_locked = False
        leaf = ""
        try:
            with PosixTrustedDirectorySessionV1(self)._parent(relative) as (
                parent,
                leaf,
            ):
                parent_descriptor = os.dup(parent)
                parent_info = os.fstat(parent_descriptor)
                _validate_directory_info(parent_info, secure=True)
                try:
                    fcntl.flock(
                        parent_descriptor,
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                except BlockingIOError as exc:
                    raise HostSecurityBoundaryBusy(
                        "posix_single_instance_busy"
                    ) from exc
                parent_locked = True

                descriptor = os.open(
                    leaf,
                    os.O_RDWR | os.O_CREAT | _file_flags(),
                    _FILE_MODE,
                    dir_fd=parent_descriptor,
                )
                info = os.fstat(descriptor)
                _validate_file_info(info)
                named = os.stat(
                    leaf,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                _validate_file_info(named)
                if _identity(named) != _identity(info):
                    raise HostSecurityBoundaryError("posix_lock_file_identity_changed")
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise HostSecurityBoundaryBusy(
                        "posix_single_instance_busy"
                    ) from exc
                file_locked = True

                # Recheck the pathname after both kernel locks.  This closes
                # the open-to-flock substitution window for a same-UID peer.
                named = os.stat(
                    leaf,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                _validate_file_info(named)
                if _identity(named) != _identity(info):
                    raise HostSecurityBoundaryError("posix_lock_file_identity_changed")
                os.ftruncate(descriptor, 0)
                record = memoryview(f"{os.getpid()}\n".encode("ascii"))
                while record:
                    written = os.write(descriptor, record)
                    if written <= 0:
                        raise HostSecurityBoundaryError("posix_lock_owner_write_failed")
                    record = record[written:]
                os.fsync(descriptor)
                named = os.stat(
                    leaf,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                _validate_file_info(named)
                if _identity(named) != _identity(info):
                    raise HostSecurityBoundaryError("posix_lock_file_identity_changed")

            lease = PosixFileLockLeaseV1(
                descriptor,
                parent_descriptor=parent_descriptor,
                leaf=leaf,
                parent_identity=_identity(parent_info),
                file_identity=_identity(info),
            )
            descriptor = -1
            parent_descriptor = -1
            return lease
        except BaseException:
            if descriptor >= 0:
                if file_locked:
                    with contextlib.suppress(BaseException):
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                with contextlib.suppress(BaseException):
                    os.close(descriptor)
            if parent_descriptor >= 0:
                if parent_locked:
                    with contextlib.suppress(BaseException):
                        fcntl.flock(parent_descriptor, fcntl.LOCK_UN)
                with contextlib.suppress(BaseException):
                    os.close(parent_descriptor)
            raise

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            descriptor = self._descriptor
            self._descriptor = -1
            self._closed = True
            if descriptor >= 0:
                os.close(descriptor)

    def __enter__(self) -> "PosixTrustedDirectoryV1":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def require_posix_descriptor_sqlite_v1() -> None:
    """Prove this native host can run SQLite/WAL beneath a pinned dirfd.

    The probe is intentionally performed by the private host-capability issuer,
    not inferred from a platform name.  A Darwin host without traversable
    ``/dev/fd/<directory>`` therefore fails closed before V16 installation.
    """

    if os.name != "posix" or platform.system() not in {"Darwin", "Linux"}:
        raise HostSecurityBoundaryError("posix_descriptor_sqlite_host_unsupported")
    root = Path(tempfile.mkdtemp(prefix="onyx-v16-descriptor-"))
    root.chmod(_DIRECTORY_MODE)
    boundary: PosixTrustedDirectoryV1 | None = None
    lease: PosixDescriptorPathLeaseV1 | None = None
    connection: sqlite3.Connection | None = None
    try:
        boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
        with boundary.session() as session:
            lease = session.descriptor_path("governance.sqlite3")
        if lease.prepare_sqlite_main() is not False:
            raise HostSecurityBoundaryError("posix_descriptor_sqlite_probe_preexisting")
        connection = sqlite3.connect(lease.path)
        mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
        if mode is None or str(mode[0]).casefold() != "wal":
            raise HostSecurityBoundaryError("posix_descriptor_sqlite_wal_unavailable")
        connection.execute("CREATE TABLE probe(value INTEGER NOT NULL)")
        connection.execute("INSERT INTO probe VALUES(1)")
        connection.commit()
        if connection.execute("SELECT value FROM probe").fetchone() != (1,):
            raise HostSecurityBoundaryError("posix_descriptor_sqlite_roundtrip_failed")
        lease.validate_sqlite_files()
    except HostSecurityBoundaryError:
        raise
    except Exception as exc:
        raise HostSecurityBoundaryError("posix_descriptor_sqlite_unavailable") from exc
    finally:
        if connection is not None:
            connection.close()
        descriptor = -1 if lease is None else lease._descriptor
        if descriptor >= 0:
            for name in (
                "governance.sqlite3-shm",
                "governance.sqlite3-wal",
                "governance.sqlite3-journal",
                "governance.sqlite3",
            ):
                try:
                    os.unlink(name, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
        if lease is not None:
            lease.close()
        if boundary is not None:
            boundary.close()
        try:
            root.rmdir()
        except OSError as exc:
            raise HostSecurityBoundaryError(
                "posix_descriptor_sqlite_probe_cleanup_failed"
            ) from exc
