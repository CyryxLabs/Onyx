"""Lifetime single-instance lock for macOS and Linux launchers."""

from __future__ import annotations

import re
import threading
from typing import Protocol

from core.host_security_boundary_v1 import HostSecurityBoundaryBusy


_SAFE_LOCK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")


class _LockLease(Protocol):
    def close(self) -> None: ...


class _LockDirectory(Protocol):
    def acquire_lock(self, relative: str) -> _LockLease: ...


class PosixSingleInstanceV1:
    """Keep a non-blocking trusted-directory lock for the process lifetime."""

    def __init__(
        self,
        *,
        directory: _LockDirectory,
        name: str = "onyx-live.lock",
    ) -> None:
        if _SAFE_LOCK_NAME.fullmatch(name) is None:
            raise ValueError("POSIX single-instance lock name is invalid")
        self._directory = directory
        self._name = name
        self._lease: _LockLease | None = None
        self._guard = threading.Lock()

    @property
    def acquired(self) -> bool:
        with self._guard:
            return self._lease is not None

    def acquire(self) -> bool:
        with self._guard:
            if self._lease is not None:
                return True
            try:
                lease = self._directory.acquire_lock(self._name)
            except HostSecurityBoundaryBusy:
                return False
            self._lease = lease
            return True

    def close(self) -> None:
        with self._guard:
            if self._lease is None:
                return
            # Transfer ownership out before close.  If close reports an error
            # after the kernel released its fd, a retry must not act on a
            # recycled descriptor through the old lease.
            lease = self._lease
            self._lease = None
            lease.close()

    def __enter__(self) -> "PosixSingleInstanceV1":
        if not self.acquire():
            raise HostSecurityBoundaryBusy("posix_single_instance_busy")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
