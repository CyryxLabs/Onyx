from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core import native_vault
from core import posix_trusted_directory_v1 as posix_directory
from core.host_security_boundary_v1 import HostSecurityBoundaryError
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1


def _completed(
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["secret-tool"], returncode, stdout, stderr)


def _vault_reference() -> native_vault.SecretReference:
    return native_vault.SecretReference(
        "Onyx.Cert119.Vault",
        "owner",
        "CERT119 vault probe",
    )


def test_linux_get_returns_none_only_after_successful_backend_probe() -> None:
    calls: list[list[str]] = []
    results = iter((_completed(1), _completed(0)))

    def runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return next(results)

    with patch.object(
        native_vault, "_validate_linux_tool", return_value="/trusted/tool"
    ):
        assert (
            native_vault.linux_get(
                _vault_reference(), runner=runner, tool_path="/trusted/tool"
            )
            is None
        )

    assert calls[0][1] == "lookup"
    assert calls[1][1:3] == ["search", "--all"]
    assert "Onyx.NativeVault.HealthProbe" in calls[1]


@pytest.mark.parametrize(
    ("lookup", "probe", "expected_calls"),
    [
        (_completed(1, stderr="D-Bus unavailable\n"), None, 1),
        (_completed(2), None, 1),
        (_completed(1, stdout="unexpected"), None, 1),
        (_completed(1), _completed(1), 2),
        (_completed(1), _completed(0, stderr="backend warning\n"), 2),
        (_completed(1), _completed(0, stdout="unexpected match\n"), 2),
    ],
)
def test_linux_get_backend_failures_never_become_missing(
    lookup: subprocess.CompletedProcess[str],
    probe: subprocess.CompletedProcess[str] | None,
    expected_calls: int,
) -> None:
    calls: list[list[str]] = []
    results = iter((lookup,) if probe is None else (lookup, probe))

    def runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return next(results)

    with patch.object(
        native_vault, "_validate_linux_tool", return_value="/trusted/tool"
    ):
        with pytest.raises(native_vault.NativeVaultError):
            native_vault.linux_get(
                _vault_reference(), runner=runner, tool_path="/trusted/tool"
            )
    assert len(calls) == expected_calls


def test_linux_get_success_with_stderr_fails_closed() -> None:
    def runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(0, "onyx-native-binary-v1:QQ==", "backend warning\n")

    with patch.object(
        native_vault, "_validate_linux_tool", return_value="/trusted/tool"
    ):
        with pytest.raises(native_vault.NativeVaultError):
            native_vault.linux_get(
                _vault_reference(), runner=runner, tool_path="/trusted/tool"
            )


_CONTENDER = r"""
import os
import sys
from pathlib import Path
from core.host_security_boundary_v1 import HostSecurityBoundaryBusy
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

if os.geteuid() != int(sys.argv[2]):
    raise SystemExit(4)
boundary = PosixTrustedDirectoryV1(root=Path(sys.argv[1]), enabled=True)
lease = None
try:
    lease = boundary.acquire_lock("owner.lock")
except HostSecurityBoundaryBusy:
    raise SystemExit(0)
finally:
    if lease is not None:
        lease.close()
    boundary.close()
raise SystemExit(9)
"""


def _contend(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _CONTENDER, str(root), str(os.geteuid())],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX flock")
@pytest.mark.parametrize("substitution", ["unlink", "rename"])
def test_same_uid_recreated_lock_cannot_split_brain(
    tmp_path: Path,
    substitution: str,
) -> None:
    root = tmp_path / "trusted"
    first_boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    lease = first_boundary.acquire_lock("owner.lock")
    lock_path = root / "owner.lock"
    displaced = root / "owner.lock.displaced"
    if substitution == "unlink":
        lock_path.unlink()
    else:
        lock_path.rename(displaced)
    lock_path.write_text("replacement\n", encoding="ascii")
    lock_path.chmod(0o600)
    replacement_identity = (lock_path.stat().st_dev, lock_path.stat().st_ino)

    try:
        contender = _contend(root)
        assert contender.returncode == 0, contender.stderr
        with pytest.raises(
            HostSecurityBoundaryError,
            match="lock_file_identity_changed|trusted_file_invalid",
        ):
            lease.validate()
        with pytest.raises(
            HostSecurityBoundaryError,
            match="lock_file_identity_changed|trusted_file_invalid",
        ):
            lease.close()
        assert lock_path.read_text(encoding="ascii") == "replacement\n"
        assert (
            lock_path.stat().st_dev,
            lock_path.stat().st_ino,
        ) == replacement_identity

        # The replacement becomes lockable only after the stable parent lease
        # has been released; recovery never unlinks the peer's inode.
        second_boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
        try:
            recovered = second_boundary.acquire_lock("owner.lock")
            recovered.close()
        finally:
            second_boundary.close()
    finally:
        with pytest.raises(HostSecurityBoundaryError, match="lease_closed"):
            lease.validate()
        first_boundary.close()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX flock")
def test_substitution_during_acquisition_fails_without_unlinking_peer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "trusted"
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    real_flock = posix_directory.fcntl.flock
    exclusive_calls = 0

    def substitute_after_file_flock(descriptor: int, operation: int) -> None:
        nonlocal exclusive_calls
        real_flock(descriptor, operation)
        if operation & posix_directory.fcntl.LOCK_EX:
            exclusive_calls += 1
            if exclusive_calls == 2:
                (root / "owner.lock").unlink()
                (root / "owner.lock").write_text("replacement\n", encoding="ascii")
                (root / "owner.lock").chmod(0o600)

    monkeypatch.setattr(posix_directory.fcntl, "flock", substitute_after_file_flock)
    try:
        with pytest.raises(
            HostSecurityBoundaryError,
            match="lock_file_identity_changed",
        ):
            boundary.acquire_lock("owner.lock")
        assert (root / "owner.lock").read_text(encoding="ascii") == "replacement\n"
    finally:
        boundary.close()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX flock")
def test_lock_crash_recovery_releases_stable_parent_anchor(tmp_path: Path) -> None:
    root = tmp_path / "crash"
    root.mkdir(mode=0o700)
    child = r"""
import sys
from pathlib import Path
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1
boundary = PosixTrustedDirectoryV1(root=Path(sys.argv[1]), enabled=True)
lease = boundary.acquire_lock("owner.lock")
print("ready", flush=True)
sys.stdin.read()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child, str(root)],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        process.kill()
        process.wait(timeout=10)

        boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
        try:
            recovered = boundary.acquire_lock("owner.lock")
            recovered.close()
        finally:
            boundary.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_lock_symlink_is_typed_and_target_is_untouched(tmp_path: Path) -> None:
    root = tmp_path / "trusted"
    root.mkdir(mode=0o700)
    target = tmp_path / "outside"
    target.write_text("sentinel", encoding="ascii")
    target.chmod(0o600)
    (root / "owner.lock").symlink_to(target)
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    try:
        with pytest.raises(HostSecurityBoundaryError):
            boundary.acquire_lock("owner.lock")
        assert target.read_text(encoding="ascii") == "sentinel"
        assert (root / "owner.lock").is_symlink()
    finally:
        boundary.close()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_lock_hardlink_is_rejected_by_link_count(tmp_path: Path) -> None:
    root = tmp_path / "trusted"
    root.mkdir(mode=0o700)
    target = tmp_path / "outside"
    target.write_text("sentinel", encoding="ascii")
    target.chmod(0o600)
    os.link(target, root / "owner.lock")
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    try:
        with pytest.raises(HostSecurityBoundaryError, match="trusted_file_invalid"):
            boundary.acquire_lock("owner.lock")
        assert target.read_text(encoding="ascii") == "sentinel"
        assert target.stat().st_nlink == 2
    finally:
        boundary.close()
