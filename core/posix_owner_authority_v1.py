"""Descriptor-bound POSIX owner authority for the portable-current stack.

This additive module leaves the accepted Windows V4/V7/V8 implementations
untouched.  It supplies their two host ports on macOS and Linux:

* a reentrant, cross-process transaction lease over a pinned private dirfd;
* a monotonic chain-head CAS stored only in Keychain or Secret Service.

There is deliberately no file, environment, or in-memory production fallback.
The optional factories are narrow test boundaries and are never exposed by the
portable activation entrypoint.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Protocol

from core import native_vault
from core import onyx_live_activation_v4 as v4
from core import owner_profile_v6 as owner_v6
from core import owner_profile_v8 as owner_v8
from core.host_security_boundary_v1 import (
    HostSecurityBoundaryBusy,
    HostSecurityBoundaryError,
)
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1


SUPPORTED_SYSTEMS = frozenset({"Darwin", "Linux"})
LEASE_FILENAME = "owner-profile-v8.transaction.lock"
LEASE_TIMEOUT_SECONDS = owner_v8.LEASE_TIMEOUT_SECONDS
_FILE_MODE = 0o600


class PosixOwnerAuthorityUnavailableV1(RuntimeError):
    """A required POSIX owner authority failed before safe activation."""


class SecureByteVaultV1(Protocol):
    def get_bytes(self) -> bytes | None: ...
    def set_bytes(self, secret: bytes | bytearray) -> None: ...
    def delete(self) -> bool: ...


SecureVaultFactoryV1 = Callable[[native_vault.SecretReference], SecureByteVaultV1]


def _require_native_posix_owner_host_v1() -> str:
    system = platform.system()
    geteuid = getattr(os, "geteuid", None)
    if os.name != "posix" or system not in SUPPORTED_SYSTEMS or not callable(geteuid):
        raise PosixOwnerAuthorityUnavailableV1(
            "posix_owner_authority_native_host_required"
        )
    return system


def _numeric_timeout(value: object) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise TypeError("timeout_seconds must be numeric")
    result = float(value)
    if not 0.05 <= result <= 30.0:
        raise ValueError("timeout_seconds is outside the bounded range")
    return result


class PosixHostTransactionLeaseV1:
    """Cross-process and reentrant lease anchored beneath a pinned dirfd."""

    def __init__(
        self,
        *,
        directory: PosixTrustedDirectoryV1,
        poll_seconds: float = 0.01,
    ) -> None:
        _require_native_posix_owner_host_v1()
        if type(directory) is not PosixTrustedDirectoryV1:
            raise owner_v8.HostLeaseError(
                "POSIX owner lease requires the exact trusted directory"
            )
        directory._validate()
        if type(poll_seconds) not in {int, float} or isinstance(poll_seconds, bool):
            raise TypeError("poll_seconds must be numeric")
        self._poll_seconds = float(poll_seconds)
        if not 0.001 <= self._poll_seconds <= 0.05:
            raise ValueError("poll_seconds is outside the bounded range")
        self._directory = directory
        self._process_lock = threading.RLock()
        self._local = threading.local()
        self._kernel_lease: object | None = None
        self._profile: str | None = None
        self._closed = False

    @property
    def cross_session_guaranteed(self) -> bool:
        return True

    @property
    def held(self) -> bool:
        return int(getattr(self._local, "depth", 0)) > 0

    def _acquire_kernel(self, deadline: float) -> object:
        while True:
            if self._closed:
                raise owner_v8.HostLeaseError("POSIX owner transaction lease is closed")
            try:
                return self._directory.acquire_lock(LEASE_FILENAME)
            except HostSecurityBoundaryBusy as exc:
                if time.monotonic() >= deadline:
                    raise owner_v8.HostLeaseConflict(
                        "POSIX owner transaction lease timed out"
                    ) from exc
                time.sleep(
                    min(self._poll_seconds, max(0.0, deadline - time.monotonic()))
                )
            except HostSecurityBoundaryError as exc:
                raise owner_v8.HostLeaseError(
                    "POSIX owner transaction lease is unavailable"
                ) from exc

    @contextmanager
    def hold(
        self, owner_profile_id: str, *, timeout_seconds: float
    ) -> Iterator[object]:
        profile = owner_v6._identifier(owner_profile_id, "owner_profile_id")
        timeout = _numeric_timeout(timeout_seconds)
        deadline = time.monotonic() + timeout
        if not self._process_lock.acquire(timeout=timeout):
            raise owner_v8.HostLeaseConflict(
                "In-process POSIX owner transaction lease timed out"
            )
        entered = False
        try:
            depth = int(getattr(self._local, "depth", 0))
            if depth:
                if self._profile != profile or self._kernel_lease is None:
                    raise owner_v8.HostLeaseError(
                        "POSIX owner transaction lease reentrancy drifted"
                    )
            else:
                self._kernel_lease = self._acquire_kernel(deadline)
                self._profile = profile
            self._local.depth = depth + 1
            entered = True
            yield self
        finally:
            release_error: BaseException | None = None
            if entered:
                depth = int(getattr(self._local, "depth", 1)) - 1
                self._local.depth = depth
                if depth == 0:
                    kernel, self._kernel_lease = self._kernel_lease, None
                    self._profile = None
                    if kernel is not None:
                        try:
                            kernel.close()
                        except (
                            BaseException
                        ) as exc:  # fail closed after release attempt
                            release_error = exc
            self._process_lock.release()
            if release_error is not None:
                raise owner_v8.HostLeaseError(
                    "POSIX owner transaction lease release failed"
                ) from release_error

    def close(self) -> None:
        with self._process_lock:
            if self.held or self._kernel_lease is not None:
                raise owner_v8.HostLeaseError(
                    "POSIX owner transaction lease is still held"
                )
            self._closed = True


def _native_vault_factory_v1(
    reference: native_vault.SecretReference,
) -> SecureByteVaultV1:
    return native_vault.NativeSecretVault(reference)


def _prove_default_secure_backend_v1(
    system: str,
    reference: native_vault.SecretReference,
) -> None:
    """Prove the default backend is reachable without creating a secret.

    ``secret-tool lookup`` uses status 1 both for a missing item and for some
    D-Bus failures.  The native primitive intentionally maps missing to None;
    activation must additionally reject status 1 carrying an error message.
    """

    if system != "Linux":
        return
    try:
        tool = native_vault._linux_secret_tool()
        result = native_vault._run_backend(
            [
                tool,
                "lookup",
                "service",
                reference.service,
                "account",
                reference.account,
            ]
        )
    except Exception as exc:
        raise PosixOwnerAuthorityUnavailableV1(
            "posix_owner_secure_backend_unavailable"
        ) from exc
    if result.returncode not in {0, 1} or (
        result.returncode == 1 and bool(result.stderr.strip())
    ):
        raise PosixOwnerAuthorityUnavailableV1("posix_owner_secure_backend_unavailable")


class PosixCredentialChainHeadStoreV1:
    """V8 chain-head CAS in Keychain/Secret Service under the host lease."""

    def __init__(
        self,
        *,
        host_lease: PosixHostTransactionLeaseV1,
        timeout_seconds: float = LEASE_TIMEOUT_SECONDS,
        vault_factory: SecureVaultFactoryV1 = _native_vault_factory_v1,
    ) -> None:
        self.system = _require_native_posix_owner_host_v1()
        if type(host_lease) is not PosixHostTransactionLeaseV1:
            raise owner_v8.ChainHeadUnavailable(
                "POSIX chain head requires the exact transaction lease"
            )
        if not callable(vault_factory):
            raise TypeError("vault_factory must be callable")
        self._host_lease = host_lease
        self._timeout_seconds = _numeric_timeout(timeout_seconds)
        self._vault_factory = vault_factory

    @staticmethod
    def _reference(owner_profile_id: str) -> native_vault.SecretReference:
        profile = owner_v6._identifier(owner_profile_id, "owner_profile_id")
        account = "owner-" + hashlib.sha256(profile.encode("ascii")).hexdigest()[:32]
        return native_vault.SecretReference(
            owner_v6.WINDOWS_HEAD_SERVICE,
            account,
            "Onyx owner-profile monotonic chain head",
        )

    @staticmethod
    def _encode(head: owner_v8.ChainHead) -> bytes:
        return owner_v6._canonical(
            {
                "version": head.version,
                "owner_profile_id": head.owner_profile_id,
                "sequence": head.sequence,
                "head_mac": head.head_mac,
            }
        )

    @staticmethod
    def _decode(raw: bytes, owner_profile_id: str) -> owner_v8.ChainHead:
        if type(raw) is not bytes or not raw or len(raw) > 2048:
            raise owner_v8.ChainHeadUnavailable(
                "POSIX chain head has an invalid representation"
            )
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise owner_v8.ChainHeadUnavailable(
                "POSIX chain head is unreadable"
            ) from exc
        if type(value) is not dict or frozenset(value) != owner_v6._HEAD_FIELDS:
            raise owner_v8.ChainHeadUnavailable("POSIX chain head fields are invalid")
        return owner_v8._validate_head(
            owner_v8.ChainHead(
                value["version"],
                value["owner_profile_id"],
                value["sequence"],
                value["head_mac"],
            ),
            owner_profile_id,
        )

    def _vault(self, owner_profile_id: str) -> SecureByteVaultV1:
        try:
            result = self._vault_factory(self._reference(owner_profile_id))
        except Exception as exc:
            raise owner_v8.ChainHeadUnavailable(
                "POSIX chain-head secure backend is unavailable"
            ) from exc
        if not all(
            callable(getattr(result, name, None))
            for name in ("get_bytes", "set_bytes", "delete")
        ):
            raise owner_v8.ChainHeadUnavailable(
                "POSIX chain-head secure backend is invalid"
            )
        return result

    def load(self, owner_profile_id: str) -> owner_v8.ChainHead | None:
        profile = owner_v6._identifier(owner_profile_id, "owner_profile_id")
        try:
            raw = self._vault(profile).get_bytes()
        except owner_v8.ChainHeadUnavailable:
            raise
        except Exception as exc:
            raise owner_v8.ChainHeadUnavailable(
                "POSIX chain-head secure backend is unavailable"
            ) from exc
        return None if raw is None else self._decode(raw, profile)

    def compare_and_set(
        self,
        owner_profile_id: str,
        expected: owner_v8.ChainHead | None,
        desired: owner_v8.ChainHead,
    ) -> bool:
        profile = owner_v6._identifier(owner_profile_id, "owner_profile_id")
        if expected is not None:
            owner_v8._validate_head(expected, profile)
        owner_v8._validate_head(desired, profile)
        owner_v8._validate_transition(expected, desired, profile)
        with self._host_lease.hold(profile, timeout_seconds=self._timeout_seconds):
            observed = self.load(profile)
            if not owner_v8._same_head(observed, expected):
                return False
            encoded = self._encode(desired)
            vault = self._vault(profile)
            try:
                vault.set_bytes(encoded)
                readback = vault.get_bytes()
            except Exception as exc:
                raise owner_v8.ChainHeadUnavailable(
                    "POSIX chain-head CAS failed"
                ) from exc
            if type(readback) is not bytes or not hmac.compare_digest(
                readback, encoded
            ):
                raise owner_v8.ChainHeadUnavailable(
                    "POSIX chain-head CAS readback failed"
                )
            return True

    def delete_if_equal(
        self, owner_profile_id: str, expected: owner_v8.ChainHead
    ) -> bool:
        """Compensate only an exact bootstrap head; never delete divergent state."""

        profile = owner_v6._identifier(owner_profile_id, "owner_profile_id")
        owner_v8._validate_head(expected, profile)
        with self._host_lease.hold(profile, timeout_seconds=self._timeout_seconds):
            if not owner_v8._same_head(self.load(profile), expected):
                return False
            vault = self._vault(profile)
            try:
                removed = vault.delete()
                readback = vault.get_bytes()
            except Exception as exc:
                raise owner_v8.ChainHeadUnavailable(
                    "POSIX chain-head cleanup failed"
                ) from exc
            if not removed or readback is not None:
                raise owner_v8.ChainHeadUnavailable(
                    "POSIX chain-head cleanup readback failed"
                )
            return True


def _key_reference_v1() -> native_vault.SecretReference:
    return native_vault.SecretReference(
        v4.OWNER_KEY_SERVICE,
        v4.OWNER_KEY_ACCOUNT,
        "Onyx Owner Profile V8 journal authentication key",
    )


def _unlink_owned_journal_v1(boundary: PosixTrustedDirectoryV1, relative: str) -> bool:
    """Unlink one exact owned regular file through its pinned parent dirfd."""

    with boundary.session() as session:
        with session._parent(relative) as (parent, leaf):
            try:
                descriptor = os.open(
                    leaf,
                    os.O_RDONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=parent,
                )
            except FileNotFoundError:
                return False
            try:
                info = os.fstat(descriptor)
                named = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or int(info.st_uid) != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != _FILE_MODE
                    or int(info.st_nlink) != 1
                    or (int(info.st_dev), int(info.st_ino))
                    != (int(named.st_dev), int(named.st_ino))
                ):
                    raise HostSecurityBoundaryError(
                        "posix_owner_journal_cleanup_identity_invalid"
                    )
                os.unlink(leaf, dir_fd=parent)
                os.fsync(parent)
                return True
            finally:
                os.close(descriptor)


class PosixOwnerAuthorityFactoryV1:
    """V4 authority factory with pre-mutation secure-backend proof and cleanup."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        config_path: Path | None = None,
        memory: object | None = None,
        vault_factory: SecureVaultFactoryV1 = _native_vault_factory_v1,
    ) -> None:
        self.system = _require_native_posix_owner_host_v1()
        if not callable(vault_factory):
            raise TypeError("vault_factory must be callable")
        if root is None:
            from core.paths import private_control_plane_runtime_dir

            selected = private_control_plane_runtime_dir() / "identity"
        else:
            selected = Path(root)
        if not selected.is_absolute():
            raise PosixOwnerAuthorityUnavailableV1("posix_owner_authority_root_invalid")
        self.root = selected
        self.config_path = config_path
        self.memory = memory
        self._vault_factory = vault_factory
        if vault_factory is _native_vault_factory_v1:
            _prove_default_secure_backend_v1(self.system, _key_reference_v1())
        self._key_vault = self._build_vault(_key_reference_v1())
        self._head_reference = PosixCredentialChainHeadStoreV1._reference(
            v4.OWNER_PROFILE_ID
        )
        self._head_probe = self._build_vault(self._head_reference)
        # These reads prove a real unlocked Keychain/Secret Service boundary.
        # No directory, lock, key, journal, or chain head has been created yet.
        try:
            self._key_vault.get_bytes()
            self._head_probe.get_bytes()
        except Exception as exc:
            raise PosixOwnerAuthorityUnavailableV1(
                "posix_owner_secure_backend_unavailable"
            ) from exc
        self._boundary: PosixTrustedDirectoryV1 | None = None
        self._lease: PosixHostTransactionLeaseV1 | None = None
        self._authority: object | None = None
        self._closed = False

    def _build_vault(
        self, reference: native_vault.SecretReference
    ) -> SecureByteVaultV1:
        try:
            result = self._vault_factory(reference)
        except Exception as exc:
            raise PosixOwnerAuthorityUnavailableV1(
                "posix_owner_secure_backend_unavailable"
            ) from exc
        if not all(
            callable(getattr(result, name, None))
            for name in ("get_bytes", "set_bytes", "delete")
        ):
            raise PosixOwnerAuthorityUnavailableV1("posix_owner_secure_backend_invalid")
        return result

    def __call__(self) -> object:
        if self._closed:
            raise PosixOwnerAuthorityUnavailableV1(
                "posix_owner_authority_factory_closed"
            )
        if self._authority is not None:
            return self._authority
        boundary = PosixTrustedDirectoryV1(root=self.root, enabled=True)
        lease = PosixHostTransactionLeaseV1(directory=boundary)
        heads = PosixCredentialChainHeadStoreV1(
            host_lease=lease,
            vault_factory=self._vault_factory,
        )
        journal = boundary.path / v4.OWNER_JOURNAL_RELATIVE.name
        config = self.config_path
        if config is None:
            from core.paths import config_file

            config = config_file()
        if self.memory is None:
            from memory.memory_manager import get_store

            memory = get_store()
        else:
            memory = self.memory
        self._boundary = boundary
        self._lease = lease
        with lease.hold(
            v4.OWNER_PROFILE_ID,
            timeout_seconds=LEASE_TIMEOUT_SECONDS,
        ):
            journal_exists = journal.exists()
            head = heads.load(v4.OWNER_PROFILE_ID)
            key_before = self._key_vault.get_bytes()
            if key_before is not None and (
                type(key_before) is not bytes or len(key_before) != 32
            ):
                raise PosixOwnerAuthorityUnavailableV1(
                    "posix_owner_journal_key_invalid"
                )
            key = v4._provision_key(
                self._key_vault,
                existing_state=journal_exists or head is not None,
            )
            created_key = key_before is None
            try:
                if not journal_exists:
                    if head is not None and not owner_v8._same_head(
                        head, owner_v8.genesis_head(v4.OWNER_PROFILE_ID)
                    ):
                        raise PosixOwnerAuthorityUnavailableV1(
                            "posix_owner_durable_stores_incomplete"
                        )
                    authority = owner_v8.OwnerProfileAuthority.bootstrap(
                        config_path=Path(config),
                        memory=memory,
                        journal_path=journal,
                        journal_key=key,
                        owner_profile_id=v4.OWNER_PROFILE_ID,
                        runtime_instance=v4.OWNER_RUNTIME_INSTANCE,
                        chain_head_store=heads,
                        transaction_lease=lease,
                    )
                else:
                    authority = owner_v8.OwnerProfileAuthority(
                        config_path=Path(config),
                        memory=memory,
                        journal_path=journal,
                        journal_key=key,
                        owner_profile_id=v4.OWNER_PROFILE_ID,
                        runtime_instance=v4.OWNER_RUNTIME_INSTANCE,
                        chain_head_store=heads,
                        transaction_lease=lease,
                    )
                    if head is None:
                        with authority._hold_transaction_lease():
                            base, records, _raw = (
                                authority.journal_backend.read_snapshot()
                            )
                        genesis = owner_v8.genesis_head(v4.OWNER_PROFILE_ID)
                        if records or not owner_v8._same_head(base, genesis):
                            raise PosixOwnerAuthorityUnavailableV1(
                                "posix_owner_crash_recovery_unsafe"
                            )
                        if not heads.compare_and_set(
                            v4.OWNER_PROFILE_ID, None, genesis
                        ):
                            raise PosixOwnerAuthorityUnavailableV1(
                                "posix_owner_crash_recovery_conflict"
                            )
                self._authority = authority
                return authority
            except BaseException:
                # Compensate only a brand-new genesis attempt. Existing state,
                # divergent secure-vault data, and tampered journals are never
                # deleted or overwritten by recovery.
                if not journal_exists and head is None:
                    genesis = owner_v8.genesis_head(v4.OWNER_PROFILE_ID)
                    try:
                        if owner_v8._same_head(
                            heads.load(v4.OWNER_PROFILE_ID), genesis
                        ):
                            heads.delete_if_equal(v4.OWNER_PROFILE_ID, genesis)
                    except Exception:
                        pass
                    try:
                        _unlink_owned_journal_v1(boundary, journal.name)
                    except Exception:
                        pass
                    if created_key:
                        try:
                            self._key_vault.delete()
                        except Exception:
                            pass
                raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._lease is not None:
            self._lease.close()
        if self._boundary is not None:
            self._boundary.close()
        self._authority = None
        self._lease = None
        self._boundary = None


__all__ = [
    "PosixCredentialChainHeadStoreV1",
    "PosixHostTransactionLeaseV1",
    "PosixOwnerAuthorityFactoryV1",
    "PosixOwnerAuthorityUnavailableV1",
]
