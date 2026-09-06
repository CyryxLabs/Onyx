from __future__ import annotations

from contextlib import contextmanager

import pytest

from core.host_security_boundary_v1 import (
    HostSecurityBoundaryBusy,
    HostSecurityBoundaryError,
)
from core.posix_kill_signal_v1 import PosixKillSignalV1


class _MemorySession:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def exists(self, relative: str, *, directory: bool | None = None) -> bool:
        return relative in self.files and directory is not True

    def publish_create(self, relative: str, content: bytes) -> None:
        if relative in self.files:
            raise HostSecurityBoundaryBusy("exists")
        self.files[relative] = content

    def read(self, relative: str, *, max_bytes: int) -> bytes:
        value = self.files[relative]
        if len(value) > max_bytes:
            raise HostSecurityBoundaryError("bound")
        return value

    def read_optional(self, relative: str, *, max_bytes: int) -> bytes | None:
        value = self.files.get(relative)
        if value is not None and len(value) > max_bytes:
            raise HostSecurityBoundaryError("bound")
        return value


class _MemoryDirectory:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    @contextmanager
    def session(self):
        yield _MemorySession(self.files)


def _signal(directory: _MemoryDirectory, digest: str = "a" * 64) -> PosixKillSignalV1:
    return PosixKillSignalV1(
        directory=directory,
        name="mission-001",
        binding_digest=digest,
    )


def test_kill_signal_is_durable_and_idempotent() -> None:
    directory = _MemoryDirectory()
    first = _signal(directory)
    assert first.is_set() is False

    first.set()
    first.set()
    assert first.is_set() is True

    reopened = _signal(directory)
    assert reopened.is_set() is True


def test_kill_signal_rejects_binding_mismatch() -> None:
    directory = _MemoryDirectory()
    _signal(directory).set()

    with pytest.raises(HostSecurityBoundaryError, match="binding_mismatch"):
        _signal(directory, "b" * 64).is_set()


@pytest.mark.parametrize(
    ("name", "digest"),
    [("../escape", "a" * 64), ("mission", "A" * 64), ("mission", "short")],
)
def test_kill_signal_rejects_untrusted_identifiers(name: str, digest: str) -> None:
    with pytest.raises(HostSecurityBoundaryError):
        PosixKillSignalV1(
            directory=_MemoryDirectory(),
            name=name,
            binding_digest=digest,
        )


def test_closed_kill_signal_fails_closed() -> None:
    signal = _signal(_MemoryDirectory())
    signal.close()

    with pytest.raises(HostSecurityBoundaryError, match="closed"):
        signal.is_set()
    with pytest.raises(HostSecurityBoundaryError, match="closed"):
        signal.set()
