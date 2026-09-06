"""Portable host-security contracts for additive native activation work.

The interfaces in this module do not select an activation or weaken the
existing Windows V19 boundary.  They provide the smallest common surface that
future portable activation code can receive through dependency injection.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol, runtime_checkable


class HostSecurityBoundaryError(RuntimeError):
    """A host boundary could not establish or preserve its security contract."""


class HostSecurityBoundaryBusy(HostSecurityBoundaryError):
    """A non-blocking host boundary is already owned or an artifact exists."""


@runtime_checkable
class TrustedDirectorySessionV1(Protocol):
    """Descriptor-relative operations inside one pinned trusted directory."""

    def exists(self, relative: str, *, directory: bool | None = None) -> bool: ...

    def publish_create(self, relative: str, content: bytes) -> None: ...

    def read(self, relative: str, *, max_bytes: int) -> bytes: ...

    def read_optional(self, relative: str, *, max_bytes: int) -> bytes | None: ...

    def lock(self, name: str = "binding.lock") -> AbstractContextManager[object]: ...


@runtime_checkable
class TrustedDirectoryV1(Protocol):
    """Pinned directory authority shared by host-specific implementations."""

    path: Path

    def session(self) -> AbstractContextManager[TrustedDirectorySessionV1]: ...

    def close(self) -> None: ...


@runtime_checkable
class KillSignalV1(Protocol):
    """Cross-process, mission-bound kill signal."""

    def is_set(self) -> bool: ...

    def set(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class SingleInstanceV1(Protocol):
    """Non-blocking lifetime lock used by a native GUI launcher."""

    def acquire(self) -> bool: ...

    def close(self) -> None: ...
