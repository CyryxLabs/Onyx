from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from core import native_vault
from core import owner_profile_v8 as owner_v8
from core import posix_owner_authority_v1 as authority
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1
from memory.store import MemoryStore


pytestmark = pytest.mark.skipif(os.name != "posix", reason="native POSIX authority")


class MemoryVault:
    def __init__(self, storage: dict[tuple[str, str], bytes], reference) -> None:
        self.storage = storage
        self.reference = reference
        self.fail_set = False

    @property
    def key(self) -> tuple[str, str]:
        return self.reference.service, self.reference.account

    def get_bytes(self) -> bytes | None:
        return self.storage.get(self.key)

    def set_bytes(self, secret: bytes | bytearray) -> None:
        if self.fail_set:
            raise RuntimeError("secure backend rejected set")
        self.storage[self.key] = bytes(secret)

    def delete(self) -> bool:
        return self.storage.pop(self.key, None) is not None


class MemoryVaultFactory:
    def __init__(self) -> None:
        self.storage: dict[tuple[str, str], bytes] = {}
        self.vaults: dict[tuple[str, str], MemoryVault] = {}

    def __call__(self, reference) -> MemoryVault:
        key = reference.service, reference.account
        return self.vaults.setdefault(key, MemoryVault(self.storage, reference))


def _private(path: Path) -> Path:
    path.mkdir(parents=True)
    path.chmod(0o700)
    return path


def test_native_host_gate_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(authority.platform, "system", lambda: "FreeBSD")
    with pytest.raises(
        authority.PosixOwnerAuthorityUnavailableV1,
        match="native_host_required",
    ):
        authority._require_native_posix_owner_host_v1()


def test_secure_backend_failure_precedes_all_filesystem_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "must-not-exist"

    def unavailable(_reference):
        class Vault:
            def get_bytes(self):
                raise RuntimeError("no Secret Service session")

            def set_bytes(self, _secret):
                raise AssertionError("mutation forbidden")

            def delete(self):
                raise AssertionError("mutation forbidden")

        return Vault()

    with pytest.raises(
        authority.PosixOwnerAuthorityUnavailableV1,
        match="secure_backend_unavailable",
    ):
        authority.PosixOwnerAuthorityFactoryV1(
            root=root,
            vault_factory=unavailable,
        )
    assert not root.exists()


def test_linux_default_backend_probe_rejects_dbus_error_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if authority.platform.system() != "Linux":
        pytest.skip("Linux Secret Service contract")
    root = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        authority.native_vault,
        "_linux_secret_tool",
        lambda: "/usr/bin/secret-tool",
    )
    monkeypatch.setattr(
        authority.native_vault,
        "_run_backend",
        lambda _argv: subprocess.CompletedProcess(
            _argv,
            1,
            "",
            "Cannot autolaunch D-Bus without X11 $DISPLAY\n",
        ),
    )
    with pytest.raises(
        authority.PosixOwnerAuthorityUnavailableV1,
        match="secure_backend_unavailable",
    ):
        authority.PosixOwnerAuthorityFactoryV1(root=root)
    assert not root.exists()


def test_descriptor_lease_is_reentrant_and_excludes_another_instance(
    tmp_path: Path,
) -> None:
    root = _private(tmp_path / "lease")
    first_boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    second_boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    first = authority.PosixHostTransactionLeaseV1(directory=first_boundary)
    second = authority.PosixHostTransactionLeaseV1(directory=second_boundary)
    failures: list[type[BaseException]] = []
    try:
        with first.hold("owner-primary", timeout_seconds=1.0):
            with first.hold("owner-primary", timeout_seconds=1.0):
                assert first.held

                def contend() -> None:
                    try:
                        with second.hold("owner-primary", timeout_seconds=0.05):
                            pass
                    except BaseException as exc:
                        failures.append(type(exc))

                thread = threading.Thread(target=contend)
                thread.start()
                thread.join(timeout=2.0)
                assert not thread.is_alive()
        assert failures == [owner_v8.HostLeaseConflict]
        with second.hold("owner-primary", timeout_seconds=1.0):
            assert second.held
    finally:
        first.close()
        second.close()
        first_boundary.close()
        second_boundary.close()


def test_descriptor_lease_excludes_another_process(tmp_path: Path) -> None:
    root = _private(tmp_path / "lease-process")
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    lease = authority.PosixHostTransactionLeaseV1(directory=boundary)
    script = """
import sys
from pathlib import Path
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1
from core.posix_owner_authority_v1 import PosixHostTransactionLeaseV1
from core.owner_profile_v8 import HostLeaseConflict
boundary = PosixTrustedDirectoryV1(root=Path(sys.argv[1]), enabled=True)
lease = PosixHostTransactionLeaseV1(directory=boundary)
try:
    with lease.hold('owner-primary', timeout_seconds=0.05):
        raise SystemExit(9)
except HostLeaseConflict:
    raise SystemExit(0)
finally:
    lease.close()
    boundary.close()
"""
    try:
        with lease.hold("owner-primary", timeout_seconds=1.0):
            result = subprocess.run(
                [sys.executable, "-c", script, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        assert result.returncode == 0, result.stderr
    finally:
        lease.close()
        boundary.close()


def test_descriptor_lease_rejects_linked_authority_root(tmp_path: Path) -> None:
    target = _private(tmp_path / "target")
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(Exception, match="trusted_directory|open_failed"):
        PosixTrustedDirectoryV1(root=linked, enabled=True)


def test_descriptor_lease_rejects_foreign_mode_root(tmp_path: Path) -> None:
    root = tmp_path / "broad-mode"
    root.mkdir()
    root.chmod(0o755)
    with pytest.raises(Exception, match="permissions_invalid"):
        PosixTrustedDirectoryV1(root=root, enabled=True)


def test_secure_chain_head_cas_detects_tamper(tmp_path: Path) -> None:
    root = _private(tmp_path / "chain")
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    lease = authority.PosixHostTransactionLeaseV1(directory=boundary)
    vaults = MemoryVaultFactory()
    store = authority.PosixCredentialChainHeadStoreV1(
        host_lease=lease,
        vault_factory=vaults,
    )
    profile = "owner-primary"
    genesis = owner_v8.genesis_head(profile)
    try:
        assert store.load(profile) is None
        assert store.compare_and_set(profile, None, genesis)
        assert store.load(profile) == genesis
        reference = store._reference(profile)
        vaults.storage[(reference.service, reference.account)] = b"plaintext-tamper"
        with pytest.raises(owner_v8.ChainHeadUnavailable):
            store.load(profile)
    finally:
        lease.close()
        boundary.close()


def test_factory_bootstrap_reopen_and_empty_crash_recovery(tmp_path: Path) -> None:
    root = tmp_path / "owner"
    config = tmp_path / "config.json"
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    memory.initialize()
    vaults = MemoryVaultFactory()
    first = authority.PosixOwnerAuthorityFactoryV1(
        root=root,
        config_path=config,
        memory=memory,
        vault_factory=vaults,
    )
    initial = first()
    assert initial.reconcile().reconciled is True
    first.close()

    head_reference = authority.PosixCredentialChainHeadStoreV1._reference(
        authority.v4.OWNER_PROFILE_ID
    )
    assert vaults.storage.pop((head_reference.service, head_reference.account))

    recovered_factory = authority.PosixOwnerAuthorityFactoryV1(
        root=root,
        config_path=config,
        memory=memory,
        vault_factory=vaults,
    )
    recovered = recovered_factory()
    try:
        assert recovered.reconcile().reconciled is True
        assert recovered.set_name("Alice").display_name == "Alice"
    finally:
        recovered_factory.close()

    reopened_factory = authority.PosixOwnerAuthorityFactoryV1(
        root=root,
        config_path=config,
        memory=memory,
        vault_factory=vaults,
    )
    reopened = reopened_factory()
    try:
        snapshot = reopened.reconcile()
        assert snapshot.reconciled is True
        assert snapshot.display_name == "Alice"
    finally:
        reopened_factory.close()


def test_failed_genesis_compensates_journal_and_new_key(tmp_path: Path) -> None:
    root = tmp_path / "owner"
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    memory.initialize()
    vaults = MemoryVaultFactory()
    head_reference = authority.PosixCredentialChainHeadStoreV1._reference(
        authority.v4.OWNER_PROFILE_ID
    )
    head_vault = vaults(head_reference)
    head_vault.fail_set = True
    factory = authority.PosixOwnerAuthorityFactoryV1(
        root=root,
        config_path=tmp_path / "config.json",
        memory=memory,
        vault_factory=vaults,
    )
    with pytest.raises(owner_v8.ChainHeadUnavailable):
        factory()
    key_reference = native_vault.SecretReference(
        authority.v4.OWNER_KEY_SERVICE,
        authority.v4.OWNER_KEY_ACCOUNT,
        "Onyx Owner Profile V8 journal authentication key",
    )
    assert (root / owner_v8.JOURNAL_FILENAME).exists() is False
    assert (key_reference.service, key_reference.account) not in vaults.storage
    factory.close()


def test_linked_journal_is_refused_without_replacement(tmp_path: Path) -> None:
    root = _private(tmp_path / "owner")
    target = tmp_path / "outside.json"
    target.write_text("sentinel", encoding="utf-8")
    journal = root / owner_v8.JOURNAL_FILENAME
    journal.symlink_to(target)
    vaults = MemoryVaultFactory()
    key_reference = native_vault.SecretReference(
        authority.v4.OWNER_KEY_SERVICE,
        authority.v4.OWNER_KEY_ACCOUNT,
        "Onyx Owner Profile V8 journal authentication key",
    )
    vaults.storage[(key_reference.service, key_reference.account)] = b"K" * 32
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    memory.initialize()
    factory = authority.PosixOwnerAuthorityFactoryV1(
        root=root,
        config_path=tmp_path / "config.json",
        memory=memory,
        vault_factory=vaults,
    )
    with pytest.raises(Exception):
        factory()
    assert journal.is_symlink()
    assert target.read_text(encoding="utf-8") == "sentinel"
    factory.close()
