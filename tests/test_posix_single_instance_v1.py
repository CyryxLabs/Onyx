from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.host_security_boundary_v1 import HostSecurityBoundaryBusy
from core.posix_single_instance_v1 import PosixSingleInstanceV1
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1


class _Lease:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


class _Directory:
    def __init__(self, *, busy: bool = False) -> None:
        self.busy = busy
        self.calls: list[str] = []
        self.lease = _Lease()

    def acquire_lock(self, relative: str) -> _Lease:
        self.calls.append(relative)
        if self.busy:
            raise HostSecurityBoundaryBusy("busy")
        return self.lease


def test_single_instance_holds_one_lease_until_close() -> None:
    directory = _Directory()
    instance = PosixSingleInstanceV1(directory=directory)

    assert instance.acquire() is True
    assert instance.acquire() is True
    assert directory.calls == ["onyx-live.lock"]
    assert instance.acquired is True

    instance.close()
    instance.close()
    assert directory.lease.close_count == 1
    assert instance.acquired is False


def test_single_instance_reports_contention_without_ownership() -> None:
    directory = _Directory(busy=True)
    instance = PosixSingleInstanceV1(directory=directory)

    assert instance.acquire() is False
    assert instance.acquired is False


@pytest.mark.parametrize("name", ["../escape", "with/slash", "", ".hidden"])
def test_single_instance_rejects_unsafe_lock_names(name: str) -> None:
    with pytest.raises(ValueError, match="lock name"):
        PosixSingleInstanceV1(directory=_Directory(), name=name)


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX flock")
def test_native_flock_excludes_second_instance_and_recovers(tmp_path: Path) -> None:
    root = tmp_path / "onyx-runtime"
    first_directory = PosixTrustedDirectoryV1(root=root, enabled=True)
    second_directory = PosixTrustedDirectoryV1(root=root, enabled=True)
    first = PosixSingleInstanceV1(directory=first_directory)
    second = PosixSingleInstanceV1(directory=second_directory)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        first.close()
        assert second.acquire() is True
        assert (root / "onyx-live.lock").read_text(encoding="ascii").strip().isdigit()
        assert (root / "onyx-live.lock").stat().st_mode & 0o777 == 0o600
    finally:
        first.close()
        second.close()
        first_directory.close()
        second_directory.close()
