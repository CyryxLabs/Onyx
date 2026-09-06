from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from core.host_security_boundary_v1 import (
    KillSignalV1,
    SingleInstanceV1,
    TrustedDirectorySessionV1,
    TrustedDirectoryV1,
)


class _Session:
    def exists(self, relative: str, *, directory: bool | None = None) -> bool:
        return False

    def publish_create(self, relative: str, content: bytes) -> None:
        return None

    def read(self, relative: str, *, max_bytes: int) -> bytes:
        return b""

    def read_optional(self, relative: str, *, max_bytes: int) -> bytes | None:
        return None

    @contextmanager
    def lock(self, name: str = "binding.lock"):
        yield object()


class _Directory:
    path = Path("/tmp/onyx")

    @contextmanager
    def session(self):
        yield _Session()

    def close(self) -> None:
        return None


class _KillSignal:
    def is_set(self) -> bool:
        return False

    def set(self) -> None:
        return None

    def close(self) -> None:
        return None


class _SingleInstance:
    def acquire(self) -> bool:
        return True

    def close(self) -> None:
        return None


def test_portable_boundaries_are_structural_runtime_contracts() -> None:
    assert isinstance(_Session(), TrustedDirectorySessionV1)
    assert isinstance(_Directory(), TrustedDirectoryV1)
    assert isinstance(_KillSignal(), KillSignalV1)
    assert isinstance(_SingleInstance(), SingleInstanceV1)
