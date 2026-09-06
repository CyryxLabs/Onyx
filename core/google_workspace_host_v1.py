"""Default-off host authority for the source-only Google Workspace connector.

This module deliberately has no import from an Onyx activation, launcher, tool
registry, or UI.  Native vaults plus the scoped host lease provide a compare-
and-swap guarantee only between cooperating Onyx processes.  They do not prove
hardware monotonicity and cannot reject privileged vault replacement, operating
system backup restoration, or native-vault rollback.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import base64
import ctypes
import os
import platform
import re
import secrets
import socket
import stat
import threading
import time
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Iterator, Protocol
from urllib.parse import parse_qsl, urlsplit

from core import native_vault
from core.google_workspace_connector_v1 import (
    READ_SCOPES,
    GoogleGrantMetadataStoreV1,
    GoogleHttpTransportV1,
    GoogleMetadataGenerationAnchorV1,
    GoogleOAuthSettingsV1,
    GooglePendingAuthorizationV1,
    GoogleProviderReceiptV1,
    GoogleReadResultV1,
    GoogleTokenBundleV1,
    GoogleWorkspaceBindingV1,
    GoogleWorkspaceBudgetV1,
    GoogleWorkspaceConnectorV1,
    GoogleWorkspaceFeatureGateV1,
    GoogleWorkspaceV1ContractError,
    GoogleWorkspaceV1Denied,
    GoogleWorkspaceV1UnknownOutcome,
    HmacGoogleIdentityPseudonymizerV1,
    SqliteGoogleGrantMetadataStoreV1,
    StdlibGoogleHttpTransportV1,
    create_google_workspace_connector_v1,
)
from core.paths import private_control_plane_runtime_dir


HOST_SCHEMA: Final = "OnyxGoogleWorkspaceHost.v1"
ROOT_SERVICE: Final = "Onyx.GoogleWorkspace.Root.v1"
RECORD_SERVICE_PREFIX: Final = "Onyx.GoogleWorkspace.Host.v1"
MAX_GENERATION: Final = (1 << 63) - 1
MAX_RECORD_BYTES: Final = 48_000
CHUNK_BYTES: Final = 1_400
MAX_CHUNKS: Final = 36
LEASE_TIMEOUT_SECONDS: Final = 5.0
LOOPBACK_TIMEOUT_SECONDS: Final = 600.0
MAX_REQUEST_LINE_BYTES: Final = 4_096
MAX_HEADERS_BYTES: Final = 12_288
MAX_BROWSER_RESPONSE_BYTES: Final = 1_024
MAX_HEADER_LINE_BYTES: Final = 2_048
MAX_HEADER_COUNT: Final = 64
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CLIENT_ID = re.compile(r"^[A-Za-z0-9._:-]{8,512}$")


class GoogleWorkspaceHostV1Error(RuntimeError):
    pass


class GoogleWorkspaceHostV1ContractError(ValueError):
    pass


class GoogleWorkspaceHostV1Denied(PermissionError):
    pass


class GoogleWorkspaceHostV1UnknownOutcome(GoogleWorkspaceHostV1Error):
    pass


def _raise_clean(error: Exception) -> None:
    try:
        raise error from None
    except Exception:
        error.__cause__ = None
        error.__context__ = None
        error.__suppress_context__ = True
        raise


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        _raise_clean(GoogleWorkspaceHostV1ContractError("host value is invalid"))


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise GoogleWorkspaceHostV1ContractError(f"{label} is invalid")
    return value


def _valid_generation(value: object, *, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_GENERATION:
        raise GoogleWorkspaceHostV1ContractError("anchor generation is invalid")
    return value


def _hmac(key: bytes, domain: str, payload: bytes) -> str:
    return hmac.new(
        key,
        b"OnyxGoogleHostMac.v1\x00" + domain.encode("ascii") + b"\x00" + payload,
        hashlib.sha256,
    ).hexdigest()


def _derive(root: bytes, domain: str) -> bytes:
    if type(root) is not bytes or len(root) != 32 or _IDENTIFIER.fullmatch(domain) is None:
        raise GoogleWorkspaceHostV1ContractError("host key derivation input is invalid")
    return hmac.new(
        root,
        b"OnyxGoogleHostKdf.v1\x00" + domain.encode("ascii"),
        hashlib.sha256,
    ).digest()


def _scope_seed(binding: GoogleWorkspaceBindingV1) -> str:
    if type(binding) is not GoogleWorkspaceBindingV1:
        raise GoogleWorkspaceHostV1ContractError("exact workspace binding required")
    return _digest(
        _canonical(
            {
                "schema": "OnyxGoogleHostRootBinding.v1",
                "owner": binding.owner_id,
                "workspace": binding.workspace_id,
                "provider": "google-workspace",
                "account": binding.account_id,
            }
        )
    )


def _related_state_witness_path(scope_seed: str) -> Path:
    if type(scope_seed) is not str or _DIGEST.fullmatch(scope_seed) is None:
        raise GoogleWorkspaceHostV1ContractError("Google state witness scope is invalid")
    return (
        private_control_plane_runtime_dir()
        / "google-workspace-host"
        / f"authority-{scope_seed}.state"
    )


def _related_state_exists_v1(scope_seed: str) -> bool:
    return _read_related_state_witness_v1(scope_seed) is not None


def _read_related_state_witness_v1(scope_seed: str) -> str | None:
    path = _related_state_witness_path(scope_seed)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        _raise_clean(
            GoogleWorkspaceHostV1Denied("Google external state witness is unavailable")
        )
    attributes = getattr(info, "st_file_attributes", 0)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise GoogleWorkspaceHostV1Denied("Google external state witness is invalid")
    try:
        raw = path.read_bytes()
    except OSError:
        _raise_clean(
            GoogleWorkspaceHostV1Denied("Google external state witness is invalid")
        )
    return _decode_external_witness_raw_v1(raw, scope_seed)


def _decode_external_witness_raw_v1(raw: bytes, scope_seed: str) -> str:
    try:
        if type(raw) is not bytes or not raw or len(raw) > 512:
            raise ValueError
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError, ValueError):
        _raise_clean(
            GoogleWorkspaceHostV1Denied("Google external state witness is invalid")
        )
    if (
        type(value) is not dict
        or set(value) != {"schema", "scope", "state"}
        or value["schema"] != "OnyxGoogleWorkspaceExternalState.v2"
        or value["scope"] != scope_seed
        or value["state"] not in {"PREPARED", "COMMITTED"}
    ):
        raise GoogleWorkspaceHostV1Denied("Google external state witness is invalid")
    state = str(value["state"])
    if raw != _external_witness_payload_v1(scope_seed, state):
        raise GoogleWorkspaceHostV1Denied("Google external state witness is invalid")
    return state


class SecureByteVaultV1(Protocol):
    def get_bytes(self) -> bytes | None: ...
    def set_bytes(self, secret: bytes | bytearray) -> None: ...
    def delete(self) -> bool: ...


class ScopedHostLeaseV1(Protocol):
    @contextmanager
    def hold(self, scope: str, *, timeout_seconds: float) -> Iterator[object]: ...


class _ReadOnlyNoLeaseV1:
    @contextmanager
    def hold(self, scope: str, *, timeout_seconds: float) -> Iterator[object]:
        del scope, timeout_seconds
        raise GoogleWorkspaceHostV1Denied(
            "read-only Google status cannot mutate host state"
        )
        yield self


VaultFactoryV1 = Callable[[native_vault.SecretReference], SecureByteVaultV1]


class NativeGoogleHostLeaseV1:
    """Native cross-process lease adapter reusing accepted owner patterns."""

    def __init__(self, *, system: str | None = None, root: Path | None = None) -> None:
        selected = platform.system() if system is None else system
        if selected not in {"Windows", "Darwin", "Linux"}:
            raise GoogleWorkspaceHostV1Denied("native Google host lease is unavailable")
        self.system = selected
        self._boundary = None
        self._closed = False
        self._lease_closed = False
        self._boundary_closed = False
        try:
            if selected == "Windows":
                if platform.system() != "Windows":
                    raise GoogleWorkspaceHostV1Denied(
                        "native Google host lease is unavailable"
                    )
                from core.owner_profile_v8 import WindowsHostTransactionLease

                self._lease = WindowsHostTransactionLease()
            else:
                if os.name != "posix" or platform.system() != selected:
                    raise GoogleWorkspaceHostV1Denied(
                        "native Google host lease is unavailable"
                    )
                from core.posix_owner_authority_v1 import PosixHostTransactionLeaseV1
                from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

                directory = root or (
                    private_control_plane_runtime_dir() / "google-workspace-host"
                )
                self._boundary = PosixTrustedDirectoryV1(root=directory, enabled=True)
                self._lease = PosixHostTransactionLeaseV1(directory=self._boundary)
        except GoogleWorkspaceHostV1Denied:
            raise
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google host lease is unavailable"))

    @contextmanager
    def hold(self, scope: str, *, timeout_seconds: float) -> Iterator[object]:
        if type(scope) is not str or _IDENTIFIER.fullmatch(scope) is None:
            raise GoogleWorkspaceHostV1ContractError("host lease scope is invalid")
        if self._closed:
            raise GoogleWorkspaceHostV1Denied("native Google host lease is unavailable")
        context = self._lease.hold(scope, timeout_seconds=timeout_seconds)
        try:
            context.__enter__()
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google host lease is unavailable"))
        primary: BaseException | None = None
        primary_traceback = None
        release_failed = False
        try:
            yield self
        except BaseException as exc:
            primary = exc
            primary_traceback = exc.__traceback__
        finally:
            try:
                context.__exit__(
                    None if primary is None else type(primary),
                    primary,
                    primary_traceback,
                )
            except BaseException:
                release_failed = True
        if primary is not None:
            raise primary.with_traceback(primary_traceback)
        if release_failed:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google host lease is unavailable"))

    def close(self) -> None:
        if self._closed:
            return
        failed = False
        close_lease = getattr(self._lease, "close", None)
        if not self._lease_closed and callable(close_lease):
            try:
                close_lease()
                self._lease_closed = True
            except Exception:
                failed = True
        elif not callable(close_lease):
            self._lease_closed = True
        boundary = self._boundary
        if not self._boundary_closed and boundary is not None:
            try:
                boundary.close()
                self._boundary_closed = True
                self._boundary = None
            except Exception:
                failed = True
        elif boundary is None:
            self._boundary_closed = True
        self._closed = self._lease_closed and self._boundary_closed
        if failed:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google host lease is unavailable"))


def _native_vault_factory(reference: native_vault.SecretReference) -> SecureByteVaultV1:
    return native_vault.NativeSecretVault(reference)


@dataclass(frozen=True, slots=True, repr=False)
class GoogleWorkspaceHostConfigurationV1:
    binding: GoogleWorkspaceBindingV1
    client_id: str
    callback_port: int

    def __post_init__(self) -> None:
        if type(self.binding) is not GoogleWorkspaceBindingV1:
            raise GoogleWorkspaceHostV1ContractError("exact workspace binding required")
        if type(self.client_id) is not str or _CLIENT_ID.fullmatch(self.client_id) is None:
            raise GoogleWorkspaceHostV1ContractError("Google client configuration is invalid")
        if type(self.callback_port) is not int or not 1024 <= self.callback_port <= 65535:
            raise GoogleWorkspaceHostV1ContractError("Google callback port is invalid")

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.callback_port}/oauth2/callback"


class GoogleWorkspaceRootAuthorityV1:
    """Explicit native-vault provisioning and domain-separated host keys."""

    DOMAINS: Final = (
        "metadata-anchor-auth",
        "identity-pseudonymization",
        "configuration-auth",
        "token-auth",
        "pending-authorization-auth",
        "metadata-file-auth",
    )

    def __init__(
        self,
        binding: GoogleWorkspaceBindingV1,
        *,
        lease: ScopedHostLeaseV1,
        vault_factory: VaultFactoryV1 = _native_vault_factory,
        related_state_probe: Callable[[], bool] | None = None,
    ) -> None:
        if not callable(vault_factory) or not callable(getattr(lease, "hold", None)):
            raise GoogleWorkspaceHostV1ContractError("host authority capability is invalid")
        self.binding = binding
        self.scope_seed = _scope_seed(binding)
        self.scope = "google-" + self.scope_seed[:48]
        self._lease = lease
        self._factory = vault_factory
        self._related_state_probe = (
            (lambda: _related_state_exists_v1(self.scope_seed))
            if related_state_probe is None
            else related_state_probe
        )
        if not callable(self._related_state_probe):
            raise GoogleWorkspaceHostV1ContractError(
                "Google external state witness capability is invalid"
            )
        self._reference = native_vault.SecretReference(
            ROOT_SERVICE,
            "scope-" + self.scope_seed[:48],
            "Onyx Google Workspace root authority",
        )
        self._marker_reference = native_vault.SecretReference(
            "Onyx.GoogleWorkspace.RootMarker.v1",
            "scope-" + self.scope_seed[:48],
            "Onyx Google Workspace root binding marker",
        )
        self._witness_reference = native_vault.SecretReference(
            "Onyx.GoogleWorkspace.StateWitness.v1",
            "scope-" + self.scope_seed[:48],
            "Onyx Google Workspace external state witness",
        )

    def _vault(self) -> SecureByteVaultV1:
        try:
            vault = self._factory(self._reference)
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google root authority is unavailable"))
        if any(not callable(getattr(vault, name, None)) for name in ("get_bytes", "set_bytes", "delete")):
            raise GoogleWorkspaceHostV1Denied("native Google root authority is unavailable")
        return vault

    def _marker_vault(self) -> SecureByteVaultV1:
        try:
            vault = self._factory(self._marker_reference)
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google root authority is unavailable"))
        if any(not callable(getattr(vault, name, None)) for name in ("get_bytes", "set_bytes", "delete")):
            raise GoogleWorkspaceHostV1Denied("native Google root authority is unavailable")
        return vault

    def _witness_vault(self) -> SecureByteVaultV1:
        try:
            vault = self._factory(self._witness_reference)
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google root authority is unavailable"))
        if any(not callable(getattr(vault, name, None)) for name in ("get_bytes", "set_bytes", "delete")):
            raise GoogleWorkspaceHostV1Denied("native Google root authority is unavailable")
        return vault

    def _marker(self, root: bytes) -> bytes:
        body = {
            "schema": "OnyxGoogleWorkspaceRootBinding.v1",
            "scope": self.scope_seed,
            "root_digest": _digest(root),
        }
        return _canonical(
            {**body, "mac": _hmac(root, "root-binding-marker", _canonical(body))}
        )

    def _witness(self, root: bytes) -> bytes:
        body = {
            "schema": "OnyxGoogleWorkspaceStateWitness.v1",
            "scope": self.scope_seed,
            "root_digest": _digest(root),
        }
        return _canonical(
            {**body, "mac": _hmac(root, "external-state-witness", _canonical(body))}
        )

    def _validate_authority(
        self, root: object, marker: object, witness: object
    ) -> bytes | None:
        if root is None and marker is None and witness is None:
            try:
                related = self._related_state_probe()
            except GoogleWorkspaceHostV1Denied:
                raise
            except Exception:
                _raise_clean(
                    GoogleWorkspaceHostV1Denied(
                        "Google external state witness is unavailable"
                    )
                )
            if related is not False:
                raise GoogleWorkspaceHostV1Denied(
                    "native Google root authority is missing with related state"
                )
            return None
        if (
            type(root) is not bytes
            or len(root) != 32
            or type(marker) is not bytes
            or type(witness) is not bytes
        ):
            raise GoogleWorkspaceHostV1Denied("native Google root authority is incomplete")
        if not hmac.compare_digest(marker, self._marker(root)) or not hmac.compare_digest(
            witness, self._witness(root)
        ):
            raise GoogleWorkspaceHostV1Denied("native Google root binding drift")
        return root

    def provision(self) -> bool:
        """Create once.  Return True only when this call created the root."""
        with self._lease.hold(self.scope, timeout_seconds=LEASE_TIMEOUT_SECONDS):
            vault = self._vault()
            marker_vault = self._marker_vault()
            witness_vault = self._witness_vault()
            try:
                existing = vault.get_bytes()
                marker = marker_vault.get_bytes()
                witness = witness_vault.get_bytes()
            except Exception:
                _raise_clean(GoogleWorkspaceHostV1Denied("native Google root authority is unavailable"))
            validated = self._validate_authority(existing, marker, witness)
            if validated is not None:
                return False
            value = secrets.token_bytes(32)
            marker_value = self._marker(value)
            witness_value = self._witness(value)
            try:
                # The independent witness is committed first.  A crash at any
                # later step leaves a detectable partial authority, never a
                # state that can be silently reprovisioned.
                witness_vault.set_bytes(witness_value)
                vault.set_bytes(value)
                if not hmac.compare_digest(vault.get_bytes() or b"", value):
                    raise GoogleWorkspaceHostV1UnknownOutcome(
                        "Google root provisioning outcome is unknown"
                    )
                marker_vault.set_bytes(marker_value)
                observed = vault.get_bytes()
                observed_marker = marker_vault.get_bytes()
                observed_witness = witness_vault.get_bytes()
            except Exception:
                _raise_clean(GoogleWorkspaceHostV1UnknownOutcome("Google root provisioning outcome is unknown"))
            if (
                type(observed) is not bytes
                or type(observed_marker) is not bytes
                or type(observed_witness) is not bytes
                or not hmac.compare_digest(observed, value)
                or not hmac.compare_digest(observed_marker, marker_value)
                or not hmac.compare_digest(observed_witness, witness_value)
            ):
                raise GoogleWorkspaceHostV1UnknownOutcome(
                    "Google root provisioning outcome is unknown"
                )
            return True

    def load(self) -> bytes:
        with self._lease.hold(self.scope, timeout_seconds=LEASE_TIMEOUT_SECONDS):
            try:
                value = self._vault().get_bytes()
                marker = self._marker_vault().get_bytes()
                witness = self._witness_vault().get_bytes()
            except Exception:
                _raise_clean(GoogleWorkspaceHostV1Denied("native Google root authority is unavailable"))
            validated = self._validate_authority(value, marker, witness)
            if validated is None:
                raise GoogleWorkspaceHostV1Denied("native Google root authority is unavailable")
            return validated

    def load_observable(self) -> bytes:
        """Authenticate stable authority without acquiring the operation lease."""
        try:
            value = self._vault().get_bytes()
            marker = self._marker_vault().get_bytes()
            witness = self._witness_vault().get_bytes()
        except Exception:
            _raise_clean(
                GoogleWorkspaceHostV1Denied(
                    "native Google root authority is unavailable"
                )
            )
        validated = self._validate_authority(value, marker, witness)
        if validated is None:
            raise GoogleWorkspaceHostV1Denied(
                "native Google root authority is unavailable"
            )
        return validated

    def keys(self) -> dict[str, bytes]:
        root = self.load()
        return {domain: _derive(root, domain) for domain in self.DOMAINS}


class _AuthenticatedNativeRecordV1:
    """Authenticated, bounded, generation-addressed vault record."""

    def __init__(
        self,
        *,
        kind: str,
        alias: str,
        binding_digest: str,
        key: bytes,
        lease: ScopedHostLeaseV1,
        lease_scope: str,
        vault_factory: VaultFactoryV1,
    ) -> None:
        if _IDENTIFIER.fullmatch(kind) is None or _IDENTIFIER.fullmatch(alias) is None:
            raise GoogleWorkspaceHostV1ContractError("native record namespace is invalid")
        _valid_digest(binding_digest, "record binding")
        if type(key) is not bytes or len(key) != 32:
            raise GoogleWorkspaceHostV1ContractError("record authentication key is invalid")
        self.kind = kind
        self.alias = alias
        self.binding_digest = binding_digest
        self._key = key
        self._lease = lease
        self._lease_scope = lease_scope
        self._factory = vault_factory

    def _reference(self, account: str) -> native_vault.SecretReference:
        return native_vault.SecretReference(
            f"{RECORD_SERVICE_PREFIX}.{self.kind}",
            account,
            f"Onyx Google Workspace {self.kind} record",
        )

    def _vault(self, account: str) -> SecureByteVaultV1:
        try:
            vault = self._factory(self._reference(account))
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google record is unavailable"))
        if any(not callable(getattr(vault, name, None)) for name in ("get_bytes", "set_bytes", "delete")):
            raise GoogleWorkspaceHostV1Denied("native Google record is unavailable")
        return vault

    def _decode_manifest(self, raw: bytes) -> dict[str, object]:
        if type(raw) is not bytes or not raw or len(raw) > 2_048:
            raise GoogleWorkspaceHostV1Denied("native Google record is invalid")
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google record is invalid"))
        required = {"schema", "kind", "binding", "payload_digest", "chunks", "mac"}
        if type(value) is not dict or set(value) != required:
            raise GoogleWorkspaceHostV1Denied("native Google record is invalid")
        mac = value.pop("mac")
        expected = _hmac(self._key, f"manifest-{self.kind}", _canonical(value))
        if type(mac) is not str or not hmac.compare_digest(mac, expected):
            raise GoogleWorkspaceHostV1Denied("native Google record authentication failed")
        value["mac"] = mac
        if (
            value["schema"] != HOST_SCHEMA
            or value["kind"] != self.kind
            or value["binding"] != self.binding_digest
            or type(value["payload_digest"]) is not str
            or _DIGEST.fullmatch(value["payload_digest"]) is None
            or type(value["chunks"]) is not int
            or not 1 <= value["chunks"] <= MAX_CHUNKS
        ):
            raise GoogleWorkspaceHostV1Denied("native Google record binding drift")
        return value

    def _chunk_account(self, payload_digest: str, index: int) -> str:
        return f"{self.alias}.c.{payload_digest}.{index:02d}"

    def _transaction_account(self) -> str:
        return f"{self.alias}.txn"

    def _transaction_raw(
        self,
        *,
        operation: str,
        target_digest: str,
        target_chunks: int,
        previous_digest: str | None,
        previous_chunks: int | None,
    ) -> bytes:
        body = {
            "schema": "OnyxGoogleWorkspaceVaultTransaction.v1",
            "operation": operation,
            "kind": self.kind,
            "binding": self.binding_digest,
            "target_digest": target_digest,
            "target_chunks": target_chunks,
            "previous_digest": previous_digest,
            "previous_chunks": previous_chunks,
        }
        return _canonical(
            {**body, "mac": _hmac(self._key, f"transaction-{self.kind}", _canonical(body))}
        )

    def _decode_transaction(self, raw: bytes) -> dict[str, object]:
        if type(raw) is not bytes or not raw or len(raw) > 2_048:
            raise GoogleWorkspaceHostV1Denied("native Google transaction is invalid")
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google transaction is invalid"))
        fields = {
            "schema", "operation", "kind", "binding", "target_digest", "target_chunks",
            "previous_digest", "previous_chunks", "mac",
        }
        if type(value) is not dict or set(value) != fields:
            raise GoogleWorkspaceHostV1Denied("native Google transaction is invalid")
        mac = value.pop("mac")
        expected = _hmac(self._key, f"transaction-{self.kind}", _canonical(value))
        if type(mac) is not str or not hmac.compare_digest(mac, expected):
            raise GoogleWorkspaceHostV1Denied("native Google transaction authentication failed")
        value["mac"] = mac
        if (
            value["schema"] != "OnyxGoogleWorkspaceVaultTransaction.v1"
            or value["operation"] not in {"write", "delete"}
            or value["kind"] != self.kind
            or value["binding"] != self.binding_digest
            or type(value["target_digest"]) is not str
            or _DIGEST.fullmatch(value["target_digest"]) is None
            or type(value["target_chunks"]) is not int
            or not 1 <= value["target_chunks"] <= MAX_CHUNKS
        ):
            raise GoogleWorkspaceHostV1Denied("native Google transaction binding drift")
        previous_digest = value["previous_digest"]
        previous_chunks = value["previous_chunks"]
        if (previous_digest is None) != (previous_chunks is None):
            raise GoogleWorkspaceHostV1Denied("native Google transaction is invalid")
        if previous_digest is not None and (
            type(previous_digest) is not str
            or _DIGEST.fullmatch(previous_digest) is None
            or type(previous_chunks) is not int
            or not 1 <= previous_chunks <= MAX_CHUNKS
        ):
            raise GoogleWorkspaceHostV1Denied("native Google transaction is invalid")
        return value

    def _read_manifest_unlocked(self) -> dict[str, object] | None:
        try:
            raw_manifest = self._vault(self.alias).get_bytes()
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google record is unavailable"))
        return None if raw_manifest is None else self._decode_manifest(raw_manifest)

    def _read_payload_unlocked(
        self, manifest: dict[str, object]
    ) -> tuple[object, dict[str, object]]:
        parts: list[bytes] = []
        try:
            for index in range(int(manifest["chunks"])):
                chunk = self._vault(
                    self._chunk_account(str(manifest["payload_digest"]), index)
                ).get_bytes()
                if type(chunk) is not bytes or not chunk or len(chunk) > CHUNK_BYTES:
                    raise GoogleWorkspaceHostV1Denied("native Google record is incomplete")
                parts.append(chunk)
        except GoogleWorkspaceHostV1Denied:
            raise
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google record is unavailable"))
        raw = b"".join(parts)
        if len(raw) > MAX_RECORD_BYTES or not hmac.compare_digest(
            _digest(raw), str(manifest["payload_digest"])
        ):
            raise GoogleWorkspaceHostV1Denied("native Google record authentication failed")
        try:
            envelope = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google record is invalid"))
        if type(envelope) is not dict or set(envelope) != {"payload", "mac"}:
            raise GoogleWorkspaceHostV1Denied("native Google record is invalid")
        expected = _hmac(self._key, f"payload-{self.kind}", _canonical(envelope["payload"]))
        if type(envelope["mac"]) is not str or not hmac.compare_digest(envelope["mac"], expected):
            raise GoogleWorkspaceHostV1Denied("native Google record authentication failed")
        return envelope["payload"], manifest

    def _verified_delete(self, account: str) -> None:
        try:
            result = self._vault(account).delete()
            observed = self._vault(account).get_bytes()
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1UnknownOutcome("native Google record outcome is unknown"))
        if type(result) is not bool or observed is not None:
            raise GoogleWorkspaceHostV1UnknownOutcome("native Google record outcome is unknown")

    def _delete_chunks_by(self, payload_digest: str, chunks: int) -> None:
        for index in range(chunks):
            self._verified_delete(self._chunk_account(payload_digest, index))

    def _recover_unlocked(self) -> None:
        try:
            raw_transaction = self._vault(self._transaction_account()).get_bytes()
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1UnknownOutcome("native Google record recovery is unknown"))
        if raw_transaction is None:
            return
        transaction = self._decode_transaction(raw_transaction)
        manifest = self._read_manifest_unlocked()
        current_digest = None if manifest is None else manifest["payload_digest"]
        target_digest = str(transaction["target_digest"])
        previous_digest = transaction["previous_digest"]
        if transaction["operation"] == "delete":
            if current_digest not in {None, target_digest}:
                raise GoogleWorkspaceHostV1Denied(
                    "native Google transaction state drift"
                )
            if manifest is not None:
                self._verified_delete(self.alias)
            self._delete_chunks_by(
                target_digest, int(transaction["target_chunks"])
            )
            self._verified_delete(self._transaction_account())
            return
        if current_digest == target_digest:
            assert manifest is not None
            try:
                self._read_payload_unlocked(manifest)
            except GoogleWorkspaceHostV1Denied:
                _raise_clean(
                    GoogleWorkspaceHostV1UnknownOutcome(
                        "native Google record recovery is unknown"
                    )
                )
            if previous_digest is not None and previous_digest != target_digest:
                self._delete_chunks_by(
                    str(previous_digest), int(transaction["previous_chunks"])
                )
        elif current_digest == previous_digest:
            self._delete_chunks_by(target_digest, int(transaction["target_chunks"]))
        else:
            raise GoogleWorkspaceHostV1Denied("native Google transaction state drift")
        self._verified_delete(self._transaction_account())

    def _read_unlocked(self) -> tuple[object, dict[str, object]] | None:
        self._recover_unlocked()
        manifest = self._read_manifest_unlocked()
        if manifest is None:
            return None
        return self._read_payload_unlocked(manifest)

    def read(self) -> object | None:
        with self._lease.hold(self._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS):
            current = self._read_unlocked()
            return None if current is None else current[0]

    def write(self, payload: object) -> None:
        raw_payload = _canonical(payload)
        envelope = _canonical(
            {
                "payload": payload,
                "mac": _hmac(self._key, f"payload-{self.kind}", raw_payload),
            }
        )
        if not envelope or len(envelope) > MAX_RECORD_BYTES:
            raise GoogleWorkspaceHostV1ContractError("native Google record exceeds its bound")
        parts = [envelope[index : index + CHUNK_BYTES] for index in range(0, len(envelope), CHUNK_BYTES)]
        if not parts or len(parts) > MAX_CHUNKS:
            raise GoogleWorkspaceHostV1ContractError("native Google record exceeds its bound")
        payload_digest = _digest(envelope)
        body = {
            "schema": HOST_SCHEMA,
            "kind": self.kind,
            "binding": self.binding_digest,
            "payload_digest": payload_digest,
            "chunks": len(parts),
        }
        manifest_raw = _canonical(
            {**body, "mac": _hmac(self._key, f"manifest-{self.kind}", _canonical(body))}
        )
        with self._lease.hold(self._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS):
            previous = self._read_unlocked()
            previous_manifest = None if previous is None else previous[1]
            transaction_raw = self._transaction_raw(
                operation="write",
                target_digest=payload_digest,
                target_chunks=len(parts),
                previous_digest=None if previous_manifest is None else str(previous_manifest["payload_digest"]),
                previous_chunks=None if previous_manifest is None else int(previous_manifest["chunks"]),
            )
            try:
                transaction_vault = self._vault(self._transaction_account())
                transaction_vault.set_bytes(transaction_raw)
                transaction_readback = transaction_vault.get_bytes()
                if type(transaction_readback) is not bytes or not hmac.compare_digest(
                    transaction_readback, transaction_raw
                ):
                    raise GoogleWorkspaceHostV1UnknownOutcome(
                        "native Google record outcome is unknown"
                    )
                for index, part in enumerate(parts):
                    vault = self._vault(self._chunk_account(payload_digest, index))
                    vault.set_bytes(part)
                    observed = vault.get_bytes()
                    if type(observed) is not bytes or not hmac.compare_digest(observed, part):
                        raise GoogleWorkspaceHostV1UnknownOutcome(
                            "native Google record outcome is unknown"
                        )
                manifest_vault = self._vault(self.alias)
                manifest_vault.set_bytes(manifest_raw)
                observed_manifest = manifest_vault.get_bytes()
                if type(observed_manifest) is not bytes or not hmac.compare_digest(
                    observed_manifest, manifest_raw
                ):
                    raise GoogleWorkspaceHostV1UnknownOutcome(
                        "native Google record outcome is unknown"
                    )
                readback = self._read_payload_unlocked(self._decode_manifest(manifest_raw))
                if readback is None or _canonical(readback[0]) != raw_payload:
                    raise GoogleWorkspaceHostV1UnknownOutcome(
                        "native Google record outcome is unknown"
                    )
                if previous_manifest is not None and previous_manifest["payload_digest"] != payload_digest:
                    self._delete_chunks_by(
                        str(previous_manifest["payload_digest"]), int(previous_manifest["chunks"])
                    )
                self._verified_delete(self._transaction_account())
            except GoogleWorkspaceHostV1UnknownOutcome:
                raise
            except Exception:
                _raise_clean(GoogleWorkspaceHostV1UnknownOutcome("native Google record outcome is unknown"))

    def delete(self) -> bool:
        with self._lease.hold(self._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS):
            previous = self._read_unlocked()
            if previous is None:
                return False
            manifest = previous[1]
            transaction_raw = self._transaction_raw(
                operation="delete",
                target_digest=str(manifest["payload_digest"]),
                target_chunks=int(manifest["chunks"]),
                previous_digest=str(manifest["payload_digest"]),
                previous_chunks=int(manifest["chunks"]),
            )
            try:
                transaction_vault = self._vault(self._transaction_account())
                transaction_vault.set_bytes(transaction_raw)
                transaction_readback = transaction_vault.get_bytes()
                if type(transaction_readback) is not bytes or not hmac.compare_digest(
                    transaction_readback, transaction_raw
                ):
                    raise GoogleWorkspaceHostV1UnknownOutcome(
                        "native Google record outcome is unknown"
                    )
                self._verified_delete(self.alias)
            except Exception:
                _raise_clean(GoogleWorkspaceHostV1UnknownOutcome("native Google record outcome is unknown"))
            self._delete_chunks_by(
                str(previous[1]["payload_digest"]), int(previous[1]["chunks"])
            )
            self._verified_delete(self._transaction_account())
            return True


class NativeGoogleMetadataGenerationAnchorV1(GoogleMetadataGenerationAnchorV1):
    """Cooperating-process CAS in a native vault; not a hardware counter."""

    def __init__(
        self,
        *,
        binding_digest: str,
        authentication_key: bytes,
        lease: ScopedHostLeaseV1,
        lease_scope: str,
        vault_factory: VaultFactoryV1 = _native_vault_factory,
    ) -> None:
        self._binding = _valid_digest(binding_digest, "anchor binding")
        self._key = authentication_key
        self._lease = lease
        self._lease_scope = lease_scope
        self._factory = vault_factory

    def _record(self, store_reference: str) -> _AuthenticatedNativeRecordV1:
        reference = _valid_digest(store_reference, "metadata store reference")
        alias_digest = _hmac(self._key, "anchor-alias", reference.encode("ascii"))
        return _AuthenticatedNativeRecordV1(
            kind="anchor",
            alias="a-" + alias_digest[:48],
            binding_digest=self._binding,
            key=self._key,
            lease=self._lease,
            lease_scope=self._lease_scope,
            vault_factory=self._factory,
        )

    def read(self, store_reference: str) -> int | None:
        payload = self._record(store_reference).read()
        if payload is None:
            return None
        if type(payload) is not dict or set(payload) != {"store", "generation"}:
            raise GoogleWorkspaceHostV1Denied("native Google anchor is invalid")
        if not hmac.compare_digest(str(payload["store"]), store_reference):
            raise GoogleWorkspaceHostV1Denied("native Google anchor binding drift")
        try:
            return _valid_generation(payload["generation"])
        except GoogleWorkspaceHostV1ContractError:
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google anchor is invalid"))

    def compare_and_swap(
        self, store_reference: str, expected: int | None, replacement: int
    ) -> bool:
        expected = _valid_generation(expected, optional=True)
        replacement = _valid_generation(replacement)
        if expected is None:
            if replacement != 0:
                raise GoogleWorkspaceHostV1ContractError("anchor initialization must be generation zero")
        elif expected >= MAX_GENERATION or replacement != expected + 1:
            raise GoogleWorkspaceHostV1ContractError("anchor transition is invalid")
        record = self._record(store_reference)
        with self._lease.hold(self._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS):
            payload = record._read_unlocked()
            current = None
            if payload is not None:
                value = payload[0]
                if type(value) is not dict or set(value) != {"store", "generation"}:
                    raise GoogleWorkspaceHostV1Denied("native Google anchor is invalid")
                if not hmac.compare_digest(str(value["store"]), store_reference):
                    raise GoogleWorkspaceHostV1Denied("native Google anchor binding drift")
                try:
                    current = _valid_generation(value["generation"])
                except GoogleWorkspaceHostV1ContractError:
                    _raise_clean(
                        GoogleWorkspaceHostV1Denied("native Google anchor is invalid")
                    )
            if current != expected:
                return False
            record.write({"store": store_reference, "generation": replacement})
            observed = record._read_unlocked()
            if observed is None or observed[0] != {
                "store": store_reference,
                "generation": replacement,
            }:
                raise GoogleWorkspaceHostV1UnknownOutcome("native Google anchor outcome is unknown")
            return True


class NativeGoogleConfigurationVaultV1:
    def __init__(self, *, record: _AuthenticatedNativeRecordV1) -> None:
        self._record = record

    def load(self) -> GoogleWorkspaceHostConfigurationV1 | None:
        value = self._record.read()
        if value is None:
            return None
        if type(value) is not dict or set(value) != {
            "owner", "workspace", "account", "client_id", "callback_port"
        }:
            raise GoogleWorkspaceHostV1Denied("native Google configuration is invalid")
        try:
            return GoogleWorkspaceHostConfigurationV1(
                GoogleWorkspaceBindingV1(
                    value["owner"], value["workspace"], value["account"]
                ),
                value["client_id"],
                value["callback_port"],
            )
        except (GoogleWorkspaceV1ContractError, GoogleWorkspaceHostV1ContractError):
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google configuration is invalid"))

    def configure(self, value: GoogleWorkspaceHostConfigurationV1) -> bool:
        if type(value) is not GoogleWorkspaceHostConfigurationV1:
            raise GoogleWorkspaceHostV1ContractError("exact host configuration required")
        payload = {
            "owner": value.binding.owner_id,
            "workspace": value.binding.workspace_id,
            "account": value.binding.account_id,
            "client_id": value.client_id,
            "callback_port": value.callback_port,
        }
        with self._record._lease.hold(
            self._record._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS
        ):
            found = self._record._read_unlocked()
            existing = None if found is None else found[0]
            if existing is not None:
                if not hmac.compare_digest(_canonical(existing), _canonical(payload)):
                    raise GoogleWorkspaceHostV1Denied("native Google configuration conflict")
                return False
            self._record.write(payload)
            observed = self._record._read_unlocked()
            if observed is None or not hmac.compare_digest(
                _canonical(observed[0]), _canonical(payload)
            ):
                raise GoogleWorkspaceHostV1UnknownOutcome("Google configuration outcome is unknown")
            return True


class NativeGoogleTokenVaultV1:
    def __init__(self, *, record: _AuthenticatedNativeRecordV1) -> None:
        self._record = record

    @staticmethod
    def _encode(value: GoogleTokenBundleV1) -> dict[str, object]:
        if type(value) is not GoogleTokenBundleV1:
            raise GoogleWorkspaceHostV1ContractError("exact Google token bundle required")
        return {
            "binding": value.binding_digest,
            "access_b64": base64.b64encode(
                value.access_token.encode("utf-8", errors="strict")
            ).decode("ascii"),
            "refresh_b64": base64.b64encode(
                value.refresh_token.encode("utf-8", errors="strict")
            ).decode("ascii"),
            "expires": value.access_expires_at_epoch_s,
            "scopes": list(value.scopes),
            "generation": value.generation,
        }

    @staticmethod
    def _decode(value: object) -> GoogleTokenBundleV1:
        if type(value) is not dict or set(value) != {
            "binding", "access_b64", "refresh_b64", "expires", "scopes", "generation"
        } or type(value["scopes"]) is not list:
            raise GoogleWorkspaceHostV1Denied("native Google token is invalid")
        try:
            if type(value["access_b64"]) is not str or type(value["refresh_b64"]) is not str:
                raise ValueError
            access = base64.b64decode(
                value["access_b64"].encode("ascii", errors="strict"), validate=True
            ).decode("utf-8", errors="strict")
            refresh = base64.b64decode(
                value["refresh_b64"].encode("ascii", errors="strict"), validate=True
            ).decode("utf-8", errors="strict")
            return GoogleTokenBundleV1(
                value["binding"], access, refresh,
                value["expires"], tuple(value["scopes"]), value["generation"]
            )
        except (GoogleWorkspaceV1ContractError, UnicodeError, ValueError):
            _raise_clean(GoogleWorkspaceHostV1Denied("native Google token is invalid"))

    def resolve(self, binding_digest: str) -> GoogleTokenBundleV1 | None:
        _valid_digest(binding_digest, "token binding")
        if not hmac.compare_digest(binding_digest, self._record.binding_digest):
            raise GoogleWorkspaceHostV1Denied("native Google token binding drift")
        value = self._record.read()
        token = None if value is None else self._decode(value)
        if token is not None and not hmac.compare_digest(token.binding_digest, binding_digest):
            raise GoogleWorkspaceHostV1Denied("native Google token binding drift")
        return token

    def compare_and_set(
        self,
        binding_digest: str,
        expected_digest: str | None,
        value: GoogleTokenBundleV1,
    ) -> bool:
        _valid_digest(binding_digest, "token binding")
        if expected_digest is not None:
            _valid_digest(expected_digest, "expected token digest")
        if not hmac.compare_digest(binding_digest, self._record.binding_digest):
            raise GoogleWorkspaceHostV1Denied("native Google token binding drift")
        with self._record._lease.hold(
            self._record._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS
        ):
            found = self._record._read_unlocked()
            current = None if found is None else self._decode(found[0])
            actual = None if current is None else current.digest
            if actual is None:
                if expected_digest is not None:
                    return False
            elif expected_digest is None or not hmac.compare_digest(actual, expected_digest):
                return False
            if not hmac.compare_digest(value.binding_digest, binding_digest):
                raise GoogleWorkspaceHostV1Denied("native Google token binding drift")
            self._record.write(self._encode(value))
            observed = self._record._read_unlocked()
            if observed is None or not hmac.compare_digest(
                self._decode(observed[0]).digest, value.digest
            ):
                raise GoogleWorkspaceHostV1UnknownOutcome("native Google token outcome is unknown")
            return True

    def delete(self, binding_digest: str, expected_digest: str) -> bool:
        _valid_digest(binding_digest, "token binding")
        _valid_digest(expected_digest, "expected token digest")
        if not hmac.compare_digest(binding_digest, self._record.binding_digest):
            raise GoogleWorkspaceHostV1Denied("native Google token binding drift")
        with self._record._lease.hold(
            self._record._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS
        ):
            found = self._record._read_unlocked()
            if found is None:
                return False
            current = self._decode(found[0])
            if not hmac.compare_digest(current.digest, expected_digest):
                return False
            return self._record.delete()


class NativeGooglePendingVaultV1:
    def __init__(
        self,
        *,
        binding_digest: str,
        key: bytes,
        lease: ScopedHostLeaseV1,
        lease_scope: str,
        vault_factory: VaultFactoryV1,
    ) -> None:
        self._binding = _valid_digest(binding_digest, "pending binding")
        self._key = key
        self._lease = lease
        self._lease_scope = lease_scope
        self._factory = vault_factory
        status_alias = _hmac(
            self._key, "pending-status-alias", self._binding.encode("ascii")
        )
        self._status_record = _AuthenticatedNativeRecordV1(
            kind="pending-status", alias="ps-" + status_alias[:48],
            binding_digest=self._binding, key=self._key, lease=self._lease,
            lease_scope=self._lease_scope, vault_factory=self._factory,
        )

    def _record(self, state_digest: str) -> _AuthenticatedNativeRecordV1:
        state = _valid_digest(state_digest, "pending state digest")
        alias = _hmac(self._key, "pending-alias", state.encode("ascii"))
        return _AuthenticatedNativeRecordV1(
            kind="pending", alias="p-" + alias[:48], binding_digest=self._binding,
            key=self._key, lease=self._lease, lease_scope=self._lease_scope,
            vault_factory=self._factory,
        )

    def store(self, state_digest: str, value: GooglePendingAuthorizationV1) -> None:
        if type(value) is not GooglePendingAuthorizationV1:
            raise GoogleWorkspaceHostV1ContractError("exact pending authorization required")
        if not hmac.compare_digest(value.binding_digest, self._binding):
            raise GoogleWorkspaceHostV1Denied("pending authorization binding drift")
        record = self._record(state_digest)
        with self._lease.hold(
            self._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS
        ):
            if record._read_unlocked() is not None:
                raise GoogleWorkspaceHostV1Denied("pending authorization already exists")
            record.write({
                "binding": value.binding_digest, "state": value.state,
                "verifier": value.code_verifier, "redirect": value.redirect_uri,
                "expires": value.expires_at_epoch_s, "scopes": list(value.scopes),
            })

    def consume(self, state_digest: str) -> GooglePendingAuthorizationV1 | None:
        record = self._record(state_digest)
        with self._lease.hold(self._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS):
            found = record._read_unlocked()
            if found is None:
                return None
            value = found[0]
            if type(value) is not dict or set(value) != {
                "binding", "state", "verifier", "redirect", "expires", "scopes"
            } or type(value["scopes"]) is not list:
                raise GoogleWorkspaceHostV1Denied("pending authorization is invalid")
            try:
                pending = GooglePendingAuthorizationV1(
                    value["binding"], value["state"], value["verifier"],
                    value["redirect"], value["expires"], tuple(value["scopes"]),
                )
            except GoogleWorkspaceV1ContractError:
                _raise_clean(GoogleWorkspaceHostV1Denied("pending authorization is invalid"))
            if not hmac.compare_digest(pending.binding_digest, self._binding):
                raise GoogleWorkspaceHostV1Denied("pending authorization binding drift")
            if record.delete() is not True:
                raise GoogleWorkspaceHostV1UnknownOutcome("pending authorization outcome is unknown")
            return pending

    def _decode_status(self, value: object) -> dict[str, object]:
        if (
            type(value) is not dict
            or set(value) != {"schema", "binding", "state", "expires"}
            or value["schema"] != "OnyxGoogleWorkspacePendingStatus.v1"
            or value["binding"] != self._binding
            or type(value["state"]) is not str
            or _DIGEST.fullmatch(value["state"]) is None
            or type(value["expires"]) is not int
        ):
            raise GoogleWorkspaceHostV1Denied("pending authorization status is invalid")
        return value

    def mark_active(
        self, state_digest: str, expires_at_epoch_s: int, *, now_epoch_s: int
    ) -> None:
        state = _valid_digest(state_digest, "pending state digest")
        if (
            type(expires_at_epoch_s) is not int
            or type(now_epoch_s) is not int
            or now_epoch_s < 0
            or expires_at_epoch_s <= now_epoch_s
        ):
            raise GoogleWorkspaceHostV1ContractError("pending expiry is invalid")
        payload = {
            "schema": "OnyxGoogleWorkspacePendingStatus.v1",
            "binding": self._binding,
            "state": state,
            "expires": expires_at_epoch_s,
        }
        with self._lease.hold(self._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS):
            current = self._status_record._read_unlocked()
            if current is not None:
                observed_status = self._decode_status(current[0])
                if int(observed_status["expires"]) >= now_epoch_s:
                    raise GoogleWorkspaceHostV1Denied(
                        "pending authorization already active"
                    )
                if self._status_record.delete() is not True:
                    raise GoogleWorkspaceHostV1UnknownOutcome(
                        "pending authorization status outcome is unknown"
                    )
            self._status_record.write(payload)
            observed = self._status_record._read_unlocked()
            if observed is None or not hmac.compare_digest(
                _canonical(observed[0]), _canonical(payload)
            ):
                raise GoogleWorkspaceHostV1UnknownOutcome(
                    "pending authorization status outcome is unknown"
                )

    def clear_active(self, state_digest: str) -> None:
        state = _valid_digest(state_digest, "pending state digest")
        with self._lease.hold(self._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS):
            current = self._status_record._read_unlocked()
            if current is None:
                return
            value = current[0]
            value = self._decode_status(value)
            if not hmac.compare_digest(value["state"], state):
                raise GoogleWorkspaceHostV1Denied("pending authorization status drift")
            if self._status_record.delete() is not True:
                raise GoogleWorkspaceHostV1UnknownOutcome(
                    "pending authorization status outcome is unknown"
                )

    def is_active(self, now_epoch_s: int) -> bool:
        if type(now_epoch_s) is not int or now_epoch_s < 0:
            raise GoogleWorkspaceHostV1ContractError("pending status time is invalid")
        # Observation must remain available to sibling processes while the
        # consequential operation owns the host lease.  The marker is stable
        # before the receiver starts and is authenticated without recovery or
        # mutation here; mark/clear retain the serialized lease path.
        value = _peek_stable_record_v1(self._status_record)
        if value is None:
            return False
        value = self._decode_status(value)
        return now_epoch_s <= value["expires"]


@dataclass(frozen=True, slots=True, repr=False)
class GoogleLoopbackCallbackV1:
    callback_uri: str
    provider_attempted: bool = False


class GoogleOAuthLoopbackReceiverV1:
    """One-shot literal-IPv4 loopback HTTP receiver with bounded parsing."""

    def __init__(
        self,
        redirect_uri: str,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        epoch_clock: Callable[[], float] = time.time,
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ) -> None:
        parsed = urlsplit(redirect_uri)
        if (
            parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port is None or parsed.path != "/oauth2/callback"
            or parsed.query or parsed.fragment or parsed.username is not None
            or parsed.password is not None
        ):
            raise GoogleWorkspaceHostV1ContractError("loopback redirect is invalid")
        self.redirect_uri = redirect_uri
        self.port = parsed.port
        self._monotonic = monotonic_clock
        self._epoch = epoch_clock
        self._socket_factory = socket_factory
        self._guard = threading.RLock()
        self._cancel = threading.Event()
        self._listener: socket.socket | None = None
        self._connection: socket.socket | None = None
        self._close_lock = threading.Lock()
        self._lifecycle = "open"

    @staticmethod
    def _response(connection: socket.socket, status: int) -> None:
        text = "Authorization received. You may close this window." if status == 200 else "Authorization request denied."
        body = text.encode("utf-8")[:MAX_BROWSER_RESPONSE_BYTES]
        reason = "OK" if status == 200 else "Bad Request"
        payload = (
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain; charset=utf-8\r\n"
            "Cache-Control: no-store\r\nPragma: no-cache\r\nConnection: close\r\n"
            f"Content-Length: {len(body)}\r\n\r\n"
        ).encode("ascii") + body
        connection.sendall(payload)

    def _cancelled(self, cancel_event: threading.Event | None) -> bool:
        return self._cancel.is_set() or (
            cancel_event is not None and cancel_event.is_set()
        )

    def _read_bounded_request(
        self,
        connection: socket.socket,
        *,
        deadline: float,
        cancel_event: threading.Event | None,
    ) -> bytes:
        data = bytearray()
        while b"\r\n\r\n" not in data:
            if self._cancelled(cancel_event):
                raise GoogleWorkspaceHostV1Denied("OAuth callback cancelled")
            left = deadline - float(self._monotonic())
            if left <= 0:
                raise GoogleWorkspaceHostV1Denied("OAuth callback deadline expired")
            connection.settimeout(max(0.01, min(0.25, left)))
            try:
                chunk = connection.recv(1024)
            except TimeoutError:
                continue
            if not chunk:
                break
            data.extend(chunk)
            first_end = data.find(b"\r\n")
            if first_end < 0 and len(data) > MAX_REQUEST_LINE_BYTES:
                raise GoogleWorkspaceHostV1Denied("OAuth callback request line is invalid")
            if first_end >= 0:
                if first_end > MAX_REQUEST_LINE_BYTES:
                    raise GoogleWorkspaceHostV1Denied("OAuth callback request line is invalid")
                if len(data) - first_end - 2 > MAX_HEADERS_BYTES + 4:
                    raise GoogleWorkspaceHostV1Denied("OAuth callback headers exceed their bound")
        return bytes(data)

    def _parse_callback_request(self, data: bytes, peer: object) -> str:
        if (
            type(peer) not in {tuple, list}
            or len(peer) < 1
            or peer[0] != "127.0.0.1"
        ):
            raise GoogleWorkspaceHostV1Denied("OAuth callback peer is forbidden")
        header_end = data.find(b"\r\n\r\n")
        if header_end < 0:
            raise GoogleWorkspaceHostV1Denied("OAuth callback request is incomplete")
        try:
            lines = data[:header_end].decode("ascii", errors="strict").split("\r\n")
        except UnicodeError:
            _raise_clean(GoogleWorkspaceHostV1Denied("OAuth callback request is invalid"))
        if not lines or len(lines[0].encode("ascii")) > MAX_REQUEST_LINE_BYTES:
            raise GoogleWorkspaceHostV1Denied("OAuth callback request line is invalid")
        request = lines[0].split(" ")
        if len(request) != 3 or request[0] != "GET" or request[2] != "HTTP/1.1":
            raise GoogleWorkspaceHostV1Denied("OAuth callback method is forbidden")
        target = request[1]
        if "#" in target or "@" in target or not target.startswith("/oauth2/callback?"):
            raise GoogleWorkspaceHostV1Denied("OAuth callback target is forbidden")
        parsed_target = urlsplit(target)
        if parsed_target.scheme or parsed_target.netloc or parsed_target.path != "/oauth2/callback":
            raise GoogleWorkspaceHostV1Denied("OAuth callback target is forbidden")
        if len(lines) - 1 > MAX_HEADER_COUNT:
            raise GoogleWorkspaceHostV1Denied("OAuth callback headers exceed their bound")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if len(line.encode("ascii")) > MAX_HEADER_LINE_BYTES or ":" not in line:
                raise GoogleWorkspaceHostV1Denied("OAuth callback headers are invalid")
            name, value = line.split(":", 1)
            lowered = name.strip().casefold()
            if not lowered or lowered in headers:
                raise GoogleWorkspaceHostV1Denied("OAuth callback headers are invalid")
            headers[lowered] = value.strip()
        if headers.get("host") != f"127.0.0.1:{self.port}":
            raise GoogleWorkspaceHostV1Denied("OAuth callback host is forbidden")
        if "content-length" in headers or "transfer-encoding" in headers:
            raise GoogleWorkspaceHostV1Denied("OAuth callback body is forbidden")
        if data[header_end + 4 :]:
            raise GoogleWorkspaceHostV1Denied("OAuth callback body is forbidden")
        try:
            pairs = parse_qsl(parsed_target.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            _raise_clean(GoogleWorkspaceHostV1Denied("OAuth callback query is invalid"))
        names = [name for name, _ in pairs]
        if (
            len(names) not in {2, 3} or len(set(names)) != len(names)
            or set(names) - {"code", "state", "error"} or "state" not in names
            or (("code" in names) == ("error" in names))
        ):
            raise GoogleWorkspaceHostV1Denied("OAuth callback query is forbidden")
        return f"{self.redirect_uri}?{parsed_target.query}"

    def receive(
        self,
        authorization_url: str,
        *,
        expires_at_epoch_s: int,
        browser_open: Callable[[str], bool] = webbrowser.open,
        cancel_event: threading.Event | None = None,
    ) -> GoogleLoopbackCallbackV1:
        with self._guard:
            if self._lifecycle != "open" or self._listener is not None:
                raise GoogleWorkspaceHostV1Denied("OAuth loopback receiver is unavailable")
            self._cancel.clear()
        now_epoch = float(self._epoch())
        remaining = min(
            LOOPBACK_TIMEOUT_SECONDS,
            max(0.0, float(expires_at_epoch_s) - now_epoch),
        )
        if remaining <= 0:
            raise GoogleWorkspaceHostV1Denied("OAuth callback deadline expired")
        deadline = float(self._monotonic()) + remaining
        listener = None
        connection = None
        try:
            listener = self._socket_factory(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            listener.bind(("127.0.0.1", self.port))
            listener.listen(1)
            with self._guard:
                if self._lifecycle != "open":
                    raise GoogleWorkspaceHostV1Denied("OAuth callback cancelled")
                self._listener = listener
            listener.settimeout(min(0.25, remaining))
            try:
                opened = browser_open(authorization_url)
            except Exception:
                _raise_clean(GoogleWorkspaceHostV1Denied("OAuth browser capability failed"))
            if opened is not True:
                raise GoogleWorkspaceHostV1Denied("OAuth browser capability failed")
            while True:
                if self._cancel.is_set() or (
                    cancel_event is not None and cancel_event.is_set()
                ):
                    raise GoogleWorkspaceHostV1Denied("OAuth callback cancelled")
                left = deadline - float(self._monotonic())
                if left <= 0:
                    raise GoogleWorkspaceHostV1Denied("OAuth callback deadline expired")
                listener.settimeout(min(0.25, left))
                try:
                    connection, peer = listener.accept()
                    with self._guard:
                        self._connection = connection
                    break
                except TimeoutError:
                    continue
            data = self._read_bounded_request(
                connection, deadline=deadline, cancel_event=cancel_event
            )
            callback = self._parse_callback_request(data, peer)
            self._response(connection, 200)
            return GoogleLoopbackCallbackV1(callback)
        except (GoogleWorkspaceHostV1ContractError, GoogleWorkspaceHostV1Denied):
            if connection is not None:
                try:
                    self._response(connection, 400)
                except Exception:
                    pass
            raise
        except Exception:
            _raise_clean(GoogleWorkspaceHostV1Denied("OAuth loopback receiver is unavailable"))
        finally:
            cleanup_failed = False
            for attribute, resource in (
                ("_connection", connection), ("_listener", listener)
            ):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        cleanup_failed = True
                        with self._guard:
                            if getattr(self, attribute) is None:
                                setattr(self, attribute, resource)
                    else:
                        with self._guard:
                            if getattr(self, attribute) is resource:
                                setattr(self, attribute, None)
            with self._guard:
                if cleanup_failed:
                    self._lifecycle = "closing"
                elif self._lifecycle == "closing" and (
                    self._connection is None and self._listener is None
                ):
                    self._lifecycle = "closed"
            if cleanup_failed:
                _raise_clean(
                    GoogleWorkspaceHostV1UnknownOutcome(
                        "OAuth loopback cleanup outcome is unknown"
                    )
                )

    def close(self) -> None:
        if not self._close_lock.acquire(timeout=LEASE_TIMEOUT_SECONDS):
            _raise_clean(
                GoogleWorkspaceHostV1UnknownOutcome(
                    "OAuth loopback cleanup outcome is unknown"
                )
            )
        try:
            with self._guard:
                if self._lifecycle == "closed":
                    return
                self._lifecycle = "closing"
                self._cancel.set()
                resources = (
                    ("_connection", self._connection),
                    ("_listener", self._listener),
                )
            failures = False
            for attribute, resource in resources:
                if resource is None:
                    continue
                try:
                    resource.close()
                except Exception:
                    failures = True
                else:
                    with self._guard:
                        if getattr(self, attribute) is resource:
                            setattr(self, attribute, None)
            with self._guard:
                if (
                    not failures
                    and self._connection is None
                    and self._listener is None
                ):
                    self._lifecycle = "closed"
            if failures:
                _raise_clean(
                    GoogleWorkspaceHostV1UnknownOutcome(
                        "OAuth loopback cleanup outcome is unknown"
                    )
                )
        finally:
            self._close_lock.release()


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceHostStatusV1:
    enabled: bool
    configured: bool
    connected: bool
    supported_backend: str
    binding_digest: str
    anchor_generation: int | None
    anchor_health: str
    scopes: tuple[str, ...]
    pending_loopback: bool
    reconciliation: str
    trust_limit: str = "cooperating-process-cas-only"


def _peek_stable_record_v1(
    record: _AuthenticatedNativeRecordV1, *, attempts: int = 4
) -> object | None:
    if type(attempts) is not int or not 1 <= attempts <= 8:
        raise GoogleWorkspaceHostV1ContractError("status retry bound is invalid")
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            transaction = record._vault(record._transaction_account()).get_bytes()
            if transaction is not None:
                raise GoogleWorkspaceHostV1Denied(
                    "native Google record is changing"
                )
            manifest = record._read_manifest_unlocked()
            if manifest is None:
                return None
            return record._read_payload_unlocked(manifest)[0]
        except GoogleWorkspaceHostV1Denied as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(0.015)
    assert last is not None
    raise last


def read_google_workspace_host_status_v1(
    configuration: GoogleWorkspaceHostConfigurationV1,
    *,
    epoch_clock: Callable[[], float] = time.time,
    vault_factory: VaultFactoryV1 = _native_vault_factory,
) -> GoogleWorkspaceHostStatusV1:
    """Read-only cross-process status that never acquires the operation lease."""
    if type(configuration) is not GoogleWorkspaceHostConfigurationV1:
        raise GoogleWorkspaceHostV1ContractError("exact host configuration required")
    if (
        vault_factory is _native_vault_factory
        and _read_related_state_witness_v1(
            _scope_seed(configuration.binding)
        ) != "COMMITTED"
    ):
        raise GoogleWorkspaceHostV1Denied(
            "Google external state witness is incomplete"
        )
    lease = _ReadOnlyNoLeaseV1()
    root = GoogleWorkspaceRootAuthorityV1(
        configuration.binding, lease=lease, vault_factory=vault_factory
    )
    root_value = root.load_observable()
    keys = {domain: _derive(root_value, domain) for domain in root.DOMAINS}
    binding_digest = _binding_digest(
        keys["identity-pseudonymization"], configuration.binding
    )
    alias = "b-" + binding_digest[:48]
    config_record = _AuthenticatedNativeRecordV1(
        kind="config", alias=alias, binding_digest=binding_digest,
        key=keys["configuration-auth"], lease=lease, lease_scope=root.scope,
        vault_factory=vault_factory,
    )
    config_value = _peek_stable_record_v1(config_record)
    expected_config = {
        "owner": configuration.binding.owner_id,
        "workspace": configuration.binding.workspace_id,
        "account": configuration.binding.account_id,
        "client_id": configuration.client_id,
        "callback_port": configuration.callback_port,
    }
    if config_value is None or not hmac.compare_digest(
        _canonical(config_value), _canonical(expected_config)
    ):
        raise GoogleWorkspaceHostV1Denied("native Google configuration conflict")
    token_record = _AuthenticatedNativeRecordV1(
        kind="token", alias=alias, binding_digest=binding_digest,
        key=keys["token-auth"], lease=lease, lease_scope=root.scope,
        vault_factory=vault_factory,
    )
    token_value = _peek_stable_record_v1(token_record)
    token = None if token_value is None else NativeGoogleTokenVaultV1._decode(token_value)
    connected = token is not None and hmac.compare_digest(
        token.binding_digest, binding_digest
    ) and token.scopes == READ_SCOPES
    pending = NativeGooglePendingVaultV1(
        binding_digest=binding_digest,
        key=keys["pending-authorization-auth"], lease=lease,
        lease_scope=root.scope, vault_factory=vault_factory,
    )
    pending_loopback = pending.is_active(int(epoch_clock()))
    backend = vault_factory(root._reference)
    backend_name = getattr(backend, "backend_name", "injected-source-vault")
    return GoogleWorkspaceHostStatusV1(
        True, True, connected, str(backend_name), binding_digest, None,
        "read-only", READ_SCOPES, pending_loopback,
        "connected" if connected else "disconnected",
    )


@dataclass(slots=True)
class _GoogleHostOperationStateV1:
    mutation_possible: bool = False


class GoogleWorkspaceHostServiceV1:
    def __init__(
        self,
        *,
        connector: GoogleWorkspaceConnectorV1,
        receiver: GoogleOAuthLoopbackReceiverV1,
        browser_open: Callable[[str], bool],
        epoch_clock: Callable[[], float] = time.time,
        backend_name: str,
        anchor: NativeGoogleMetadataGenerationAnchorV1,
        store_reference: str,
        pending_vault: NativeGooglePendingVaultV1,
        host_lease: ScopedHostLeaseV1,
        lease_scope: str,
        parent_authority: _GoogleMetadataParentAuthorityV1 | None = None,
    ) -> None:
        if type(connector) is not GoogleWorkspaceConnectorV1:
            raise GoogleWorkspaceHostV1ContractError("exact Google connector required")
        self._connector = connector
        self._receiver = receiver
        self._browser_open = browser_open
        self._epoch = epoch_clock
        self._backend_name = backend_name
        self._anchor = anchor
        self._store_reference = store_reference
        self._pending_vault = pending_vault
        self._host_lease = host_lease
        self._parent_authority = parent_authority
        if type(lease_scope) is not str or _IDENTIFIER.fullmatch(lease_scope) is None:
            raise GoogleWorkspaceHostV1ContractError("host lease scope is invalid")
        self._lease_scope = lease_scope
        self._state_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._lifecycle = "open"

    @contextmanager
    def _operation(self) -> Iterator[_GoogleHostOperationStateV1]:
        # Lock order is local operation lock -> reentrant scoped native host
        # lease -> nested connector/vault lease calls.  The outer lease spans
        # the complete external operation and serializes sibling services.
        if not self._operation_lock.acquire(timeout=LEASE_TIMEOUT_SECONDS):
            raise GoogleWorkspaceHostV1Denied("Google host operation is busy")
        state = _GoogleHostOperationStateV1()
        lease_context = self._host_lease.hold(
            self._lease_scope, timeout_seconds=LEASE_TIMEOUT_SECONDS
        )
        entered = False
        primary: BaseException | None = None
        primary_traceback = None
        release_error: BaseException | None = None
        try:
            try:
                lease_context.__enter__()
                entered = True
                with self._state_lock:
                    if self._lifecycle != "open":
                        raise GoogleWorkspaceHostV1Denied("Google host service is closed")
                yield state
            except BaseException as exc:
                primary = exc
                primary_traceback = exc.__traceback__
            finally:
                if entered:
                    try:
                        lease_context.__exit__(
                            None if primary is None else type(primary),
                            primary,
                            primary_traceback,
                        )
                    except BaseException as exc:
                        release_error = exc
        finally:
            self._operation_lock.release()
        if primary is not None:
            raise primary.with_traceback(primary_traceback)
        if release_error is not None:
            if state.mutation_possible:
                _raise_clean(
                    GoogleWorkspaceHostV1UnknownOutcome(
                        "Google host operation outcome is unknown"
                    )
                )
            _raise_clean(GoogleWorkspaceHostV1Denied("Google host lease is unavailable"))

    def _cleanup_pending(self, state_digest: str) -> None:
        try:
            value = self._pending_vault.consume(state_digest)
        except Exception:
            _raise_clean(
                GoogleWorkspaceHostV1UnknownOutcome(
                    "Google pending authorization cleanup is unknown"
                )
            )
        if value is not None and type(value) is not GooglePendingAuthorizationV1:
            raise GoogleWorkspaceHostV1UnknownOutcome(
                "Google pending authorization cleanup is unknown"
            )

    def status(self) -> GoogleWorkspaceHostStatusV1:
        with self._state_lock:
            if self._lifecycle != "open":
                raise GoogleWorkspaceHostV1Denied("Google host service is closed")
        pending_loopback = self._pending_vault.is_active(int(self._epoch()))
        current = self._connector.status()
        generation = self._anchor.read(self._store_reference)
        return GoogleWorkspaceHostStatusV1(
            True, True, current.connected, self._backend_name,
            current.binding_digest, generation, "available", READ_SCOPES,
            pending_loopback, current.provider_state,
        )

    def connect(self, *, budget: GoogleWorkspaceBudgetV1 | None = None) -> GoogleProviderReceiptV1:
        with self._operation() as operation:
            now = int(self._epoch())
            start = self._connector.begin_authorization(now_epoch_s=now)
            operation.mutation_possible = True
            self._pending_vault.mark_active(
                start.state_digest, start.expires_at_epoch_s, now_epoch_s=now
            )
            primary: BaseException | None = None
            primary_traceback = None
            result: GoogleProviderReceiptV1 | None = None
            try:
                callback = self._receiver.receive(
                    start.authorization_url,
                    expires_at_epoch_s=start.expires_at_epoch_s,
                    browser_open=self._browser_open,
                )
                try:
                    result = self._connector.complete_authorization(
                        callback.callback_uri,
                        now_epoch_s=int(self._epoch()),
                        budget=budget,
                    )
                except (GoogleWorkspaceV1UnknownOutcome, GoogleWorkspaceV1Denied):
                    raise
                except Exception:
                    _raise_clean(
                        GoogleWorkspaceHostV1UnknownOutcome(
                            "Google connection outcome is unknown"
                        )
                    )
            except BaseException as exc:
                primary = exc
                primary_traceback = exc.__traceback__
            finally:
                cleanup_failed = False
                try:
                    self._cleanup_pending(start.state_digest)
                except Exception:
                    cleanup_failed = True
                try:
                    self._pending_vault.clear_active(start.state_digest)
                except Exception:
                    cleanup_failed = True
                if primary is not None:
                    raise primary.with_traceback(primary_traceback)
                if cleanup_failed:
                    _raise_clean(
                        GoogleWorkspaceHostV1UnknownOutcome(
                            "Google pending authorization cleanup is unknown"
                        )
                    )
            assert result is not None
            return result

    def disconnect(self, *, budget: GoogleWorkspaceBudgetV1 | None = None) -> GoogleProviderReceiptV1:
        with self._operation() as operation:
            operation.mutation_possible = True
            return self._connector.revoke(now_epoch_s=int(self._epoch()), budget=budget)

    def test_gmail(self, *, budget: GoogleWorkspaceBudgetV1 | None = None) -> GoogleReadResultV1:
        with self._operation():
            return self._connector.list_gmail_messages(
                query="is:unread", now_epoch_s=int(self._epoch()), budget=budget
            )

    def test_calendar(
        self, *, time_min: str, time_max: str,
        budget: GoogleWorkspaceBudgetV1 | None = None,
    ) -> GoogleReadResultV1:
        with self._operation():
            return self._connector.list_calendar_events(
                time_min=time_min, time_max=time_max,
                now_epoch_s=int(self._epoch()), budget=budget,
            )

    def close(self) -> None:
        if not self._close_lock.acquire(timeout=LEASE_TIMEOUT_SECONDS):
            _raise_clean(
                GoogleWorkspaceHostV1UnknownOutcome(
                    "Google host cleanup outcome is unknown"
                )
            )
        try:
            with self._state_lock:
                if self._lifecycle == "closed":
                    return
                self._lifecycle = "closing"
            errors = False
            try:
                close_receiver = getattr(self._receiver, "close", None)
                if callable(close_receiver):
                    close_receiver()
            except Exception:
                errors = True
            acquired = self._operation_lock.acquire(timeout=LEASE_TIMEOUT_SECONDS)
            if not acquired:
                _raise_clean(
                    GoogleWorkspaceHostV1UnknownOutcome(
                        "Google host cleanup outcome is unknown"
                    )
                )
            try:
                if self._parent_authority is not None:
                    self._parent_authority.close()
            except Exception:
                errors = True
            try:
                close_lease = getattr(self._host_lease, "close", None)
                if callable(close_lease):
                    close_lease()
            except Exception:
                errors = True
            finally:
                self._operation_lock.release()
            if errors:
                _raise_clean(
                    GoogleWorkspaceHostV1UnknownOutcome(
                        "Google host cleanup outcome is unknown"
                    )
                )
            with self._state_lock:
                self._lifecycle = "closed"
        finally:
            self._close_lock.release()

    def __enter__(self) -> "GoogleWorkspaceHostServiceV1":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _binding_digest(identity_key: bytes, binding: GoogleWorkspaceBindingV1) -> str:
    identity = HmacGoogleIdentityPseudonymizerV1(identity_key)
    return identity.pseudonym(
        "binding", _canonical(
            [binding.owner_id, binding.workspace_id, binding.account_id]
        ).decode("ascii")
    )


@dataclass(frozen=True, slots=True)
class _GoogleWorkspaceHostPartsV1:
    root: GoogleWorkspaceRootAuthorityV1
    configuration: NativeGoogleConfigurationVaultV1
    token: NativeGoogleTokenVaultV1
    pending: NativeGooglePendingVaultV1
    anchor: NativeGoogleMetadataGenerationAnchorV1
    identity: HmacGoogleIdentityPseudonymizerV1
    binding_digest: str
    backend_name: str


def _host_parts_v1(
    configuration: GoogleWorkspaceHostConfigurationV1,
    *,
    lease: ScopedHostLeaseV1,
    vault_factory: VaultFactoryV1,
    provision: bool,
) -> _GoogleWorkspaceHostPartsV1:
    root = GoogleWorkspaceRootAuthorityV1(
        configuration.binding, lease=lease, vault_factory=vault_factory
    )
    if provision:
        root.provision()
    keys = root.keys()
    binding_digest = _binding_digest(
        keys["identity-pseudonymization"], configuration.binding
    )
    alias = "b-" + binding_digest[:48]
    config_record = _AuthenticatedNativeRecordV1(
        kind="config", alias=alias, binding_digest=binding_digest,
        key=keys["configuration-auth"], lease=lease, lease_scope=root.scope,
        vault_factory=vault_factory,
    )
    token_record = _AuthenticatedNativeRecordV1(
        kind="token", alias=alias, binding_digest=binding_digest,
        key=keys["token-auth"], lease=lease, lease_scope=root.scope,
        vault_factory=vault_factory,
    )
    backend = _native_vault_factory(
        native_vault.SecretReference(
            ROOT_SERVICE, "scope-" + root.scope_seed[:48],
            "Onyx Google Workspace root authority",
        )
    ).backend_name if vault_factory is _native_vault_factory else "injected-source-vault"
    return _GoogleWorkspaceHostPartsV1(
        root,
        NativeGoogleConfigurationVaultV1(record=config_record),
        NativeGoogleTokenVaultV1(record=token_record),
        NativeGooglePendingVaultV1(
            binding_digest=binding_digest,
            key=keys["pending-authorization-auth"], lease=lease,
            lease_scope=root.scope, vault_factory=vault_factory,
        ),
        NativeGoogleMetadataGenerationAnchorV1(
            binding_digest=binding_digest,
            authentication_key=keys["metadata-anchor-auth"], lease=lease,
            lease_scope=root.scope, vault_factory=vault_factory,
        ),
        HmacGoogleIdentityPseudonymizerV1(keys["identity-pseudonymization"]),
        binding_digest,
        backend,
    )


def configure_google_workspace_host_v1(
    configuration: GoogleWorkspaceHostConfigurationV1,
) -> bool:
    """Explicit production provisioning; native backends only."""
    if type(configuration) is not GoogleWorkspaceHostConfigurationV1:
        raise GoogleWorkspaceHostV1ContractError("exact host configuration required")
    lease = NativeGoogleHostLeaseV1()
    mutation_possible = False
    primary: BaseException | None = None
    primary_traceback = None
    release_error: BaseException | None = None
    result = False
    parent_authority: _GoogleMetadataParentAuthorityV1 | None = None
    root = GoogleWorkspaceRootAuthorityV1(
        configuration.binding, lease=lease, vault_factory=_native_vault_factory
    )
    lease_context = lease.hold(
        root.scope, timeout_seconds=LEASE_TIMEOUT_SECONDS
    )
    entered = False
    try:
        try:
            lease_context.__enter__()
            entered = True
            mutation_possible = True
            parent_authority = _validated_metadata_parent_v1()
            witness_state, created_prepared = _prepare_related_state_witness_v1(
                root.scope_seed, parent=parent_authority
            )
            if created_prepared:
                GoogleWorkspaceRootAuthorityV1(
                    configuration.binding,
                    lease=lease,
                    vault_factory=_native_vault_factory,
                    related_state_probe=lambda: False,
                ).provision()
            elif witness_state == "PREPARED":
                # Resume only with a complete existing authority.  PREPARED plus
                # absent or partial authority is ambiguous and must fail closed.
                root.load_observable()
            else:
                root.provision()
            parts = _host_parts_v1(
                configuration, lease=lease, vault_factory=_native_vault_factory,
                provision=False,
            )
            result = parts.configuration.configure(configuration)
            parent_authority.validate()
            metadata = SqliteGoogleGrantMetadataStoreV1(
                parent_authority.root / f"{parts.binding_digest}.sqlite3",
                parts.root.keys()["metadata-file-auth"],
                parts.anchor,
            )
            if not callable(getattr(metadata, "get", None)):
                raise GoogleWorkspaceHostV1Denied(
                    "Google metadata store is unavailable"
                )
            parent_authority.validate()
            _commit_related_state_witness_v1(
                parts.root.scope_seed, parent=parent_authority
            )
        except BaseException as exc:
            primary = exc
            primary_traceback = exc.__traceback__
        finally:
            if entered:
                try:
                    lease_context.__exit__(
                        None if primary is None else type(primary),
                        primary,
                        primary_traceback,
                    )
                except BaseException as exc:
                    release_error = exc
    except BaseException as exc:
        if primary is None:
            primary = exc
            primary_traceback = exc.__traceback__
    finally:
        if parent_authority is not None:
            try:
                parent_authority.close()
            except BaseException as exc:
                if release_error is None:
                    release_error = exc
        try:
            lease.close()
        except BaseException as exc:
            if release_error is None:
                release_error = exc
    if primary is not None:
        raise primary.with_traceback(primary_traceback)
    if release_error is not None:
        if mutation_possible:
            _raise_clean(
                GoogleWorkspaceHostV1UnknownOutcome(
                    "Google host release outcome is unknown"
                )
            )
        _raise_clean(GoogleWorkspaceHostV1Denied("Google host lease is unavailable"))
    return result


def _directory_identity_v1(path: Path) -> tuple[int, int, int]:
    try:
        info = path.lstat()
    except OSError:
        _raise_clean(
            GoogleWorkspaceHostV1Denied(
                "Google metadata parent authority is invalid"
            )
        )
    attributes = getattr(info, "st_file_attributes", 0)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise GoogleWorkspaceHostV1Denied(
            "Google metadata parent authority is invalid"
        )
    return (int(info.st_dev), int(info.st_ino), int(info.st_mode))


def _native_filesystem_path_v1(path: Path) -> Path:
    """Use the Windows extended path form without changing logical authority."""

    if os.name != "nt":
        return path
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


@dataclass(slots=True)
class _OwnedExternalWitnessTempV1:
    path: Path
    descriptor: int | None
    state: str = "open"

    @classmethod
    def create(cls, path: Path) -> _OwnedExternalWitnessTempV1:
        descriptor = os.open(
            _native_filesystem_path_v1(path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        return cls(path, descriptor)

    def close_once(self) -> None:
        descriptor = self.descriptor
        if descriptor is None:
            return
        try:
            os.close(descriptor)
        except OSError:
            # close() failure makes descriptor ownership unknowable.  POSIX may
            # already have released and reused the number; Windows test seams
            # can have the same ambiguity.  Abandon it irrevocably and require
            # process restart.  Never fstat, retry or close this number again.
            self.descriptor = None
            self.state = "abandoned-restart-required"
            raise GoogleWorkspaceHostV1UnknownOutcome(
                "Google external state witness cleanup outcome is unknown"
            ) from None
        self.descriptor = None
        self.state = "closed"


_ABANDONED_EXTERNAL_WITNESS_TEMPS_V1: set[Path] = set()
_EXTERNAL_WITNESS_RESTART_ROOTS_V1: set[Path] = set()
_ABANDONED_EXTERNAL_WITNESS_GUARD_V1 = threading.RLock()


def _abandoned_external_witness_temps_for_root_v1(root: Path) -> tuple[Path, ...]:
    with _ABANDONED_EXTERNAL_WITNESS_GUARD_V1:
        return tuple(
            path
            for path in _ABANDONED_EXTERNAL_WITNESS_TEMPS_V1
            if path.parent == root
        )


def _external_witness_restart_required_v1(root: Path) -> bool:
    with _ABANDONED_EXTERNAL_WITNESS_GUARD_V1:
        return root in _EXTERNAL_WITNESS_RESTART_ROOTS_V1


def _mark_external_witness_restart_required_v1(root: Path) -> None:
    with _ABANDONED_EXTERNAL_WITNESS_GUARD_V1:
        _EXTERNAL_WITNESS_RESTART_ROOTS_V1.add(root)


class _GoogleMetadataParentAuthorityV1:
    """Pinned metadata parent plus owned pending-temp cleanup registry."""

    def __init__(self, root: Path, identity: tuple[int, int, int]) -> None:
        self.root = root
        self.identity = identity
        self._closed = False
        self._handle = None
        self._dirfd: int | None = None
        self._dirfd_identity: tuple[int, int, int] | None = None
        self._pending_external_witness_temps: list[Path] = list(
            _abandoned_external_witness_temps_for_root_v1(root)
        )
        self._restart_required = bool(
            self._pending_external_witness_temps
        ) or _external_witness_restart_required_v1(root)
        self._windows_identity: tuple[int, int, int] | None = None
        if platform.system() == "Windows":
            self._handle, self._windows_identity = self._open_windows_pin(root)
        else:
            self._dirfd = os.open(
                root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            info = os.fstat(self._dirfd)
            self._dirfd_identity = (
                int(info.st_dev), int(info.st_ino), int(info.st_mode)
            )

    @staticmethod
    def _open_windows_pin(path: Path) -> tuple[int, tuple[int, int, int]]:
        from ctypes import wintypes

        class ByHandleFileInformation(ctypes.Structure):
            _fields_ = [
                ("attributes", wintypes.DWORD),
                ("creation_low", wintypes.DWORD),
                ("creation_high", wintypes.DWORD),
                ("access_low", wintypes.DWORD),
                ("access_high", wintypes.DWORD),
                ("write_low", wintypes.DWORD),
                ("write_high", wintypes.DWORD),
                ("volume_serial", wintypes.DWORD),
                ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD),
                ("links", wintypes.DWORD),
                ("file_index_high", wintypes.DWORD),
                ("file_index_low", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        get_information = kernel32.GetFileInformationByHandle
        get_information.argtypes = (
            wintypes.HANDLE, ctypes.POINTER(ByHandleFileInformation)
        )
        get_information.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        handle = create_file(
            str(path), 0x00010000 | 0x0080,
            0x00000001 | 0x00000002, None, 3,
            0x02000000 | 0x00200000, None,
        )
        invalid = ctypes.c_void_p(-1).value
        if handle in {None, invalid}:
            _raise_clean(
                GoogleWorkspaceHostV1Denied(
                    "Google metadata parent authority is unavailable"
                )
            )
        information = ByHandleFileInformation()
        if not get_information(
            handle, ctypes.byref(information)
        ) or information.attributes & 0x00000400:
            close_handle(handle)
            _raise_clean(
                GoogleWorkspaceHostV1Denied(
                    "Google metadata parent authority is invalid"
                )
            )
        identity = (
            int(information.volume_serial),
            int(information.file_index_high),
            int(information.file_index_low),
        )
        return int(handle), identity

    def _windows_handle_identity(self) -> tuple[int, int, int]:
        if self._handle is None:
            raise GoogleWorkspaceHostV1Denied(
                "Google metadata parent authority is unavailable"
            )
        from ctypes import wintypes

        class ByHandleFileInformation(ctypes.Structure):
            _fields_ = [
                ("attributes", wintypes.DWORD),
                ("creation_low", wintypes.DWORD),
                ("creation_high", wintypes.DWORD),
                ("access_low", wintypes.DWORD),
                ("access_high", wintypes.DWORD),
                ("write_low", wintypes.DWORD),
                ("write_high", wintypes.DWORD),
                ("volume_serial", wintypes.DWORD),
                ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD),
                ("links", wintypes.DWORD),
                ("file_index_high", wintypes.DWORD),
                ("file_index_low", wintypes.DWORD),
            ]

        get_information = ctypes.WinDLL(
            "kernel32", use_last_error=True
        ).GetFileInformationByHandle
        get_information.argtypes = (
            wintypes.HANDLE, ctypes.POINTER(ByHandleFileInformation)
        )
        get_information.restype = wintypes.BOOL
        information = ByHandleFileInformation()
        if not get_information(self._handle, ctypes.byref(information)):
            _raise_clean(
                GoogleWorkspaceHostV1Denied(
                    "Google metadata parent authority is unavailable"
                )
            )
        if information.attributes & 0x00000400:
            raise GoogleWorkspaceHostV1Denied(
                "Google metadata parent authority is invalid"
            )
        return (
            int(information.volume_serial),
            int(information.file_index_high),
            int(information.file_index_low),
        )

    def validate(self) -> None:
        if self._closed:
            raise GoogleWorkspaceHostV1Denied(
                "Google metadata parent authority is closed"
            )
        if _directory_identity_v1(self.root) != self.identity:
            raise GoogleWorkspaceHostV1Denied(
                "Google metadata parent authority drift"
            )
        if self._windows_identity is not None:
            if self._windows_handle_identity() != self._windows_identity:
                raise GoogleWorkspaceHostV1Denied(
                    "Google metadata parent authority drift"
                )
        if self._dirfd is not None:
            try:
                info = os.fstat(self._dirfd)
            except OSError:
                _raise_clean(
                    GoogleWorkspaceHostV1Denied(
                        "Google metadata parent authority is unavailable"
                    )
                )
            if (
                int(info.st_dev), int(info.st_ino), int(info.st_mode)
            ) != self._dirfd_identity:
                raise GoogleWorkspaceHostV1Denied(
                    "Google metadata parent authority drift"
                )

    def retain_external_witness_temp(
        self, temporary: _OwnedExternalWitnessTempV1
    ) -> None:
        if temporary.state != "abandoned-restart-required":
            return
        path = temporary.path
        with _ABANDONED_EXTERNAL_WITNESS_GUARD_V1:
            _ABANDONED_EXTERNAL_WITNESS_TEMPS_V1.add(path)
            _EXTERNAL_WITNESS_RESTART_ROOTS_V1.add(self.root)
        if path not in self._pending_external_witness_temps:
            self._pending_external_witness_temps.append(path)
        self._restart_required = True

    def drain_external_witness_temps(self) -> None:
        if self._restart_required or _abandoned_external_witness_temps_for_root_v1(
            self.root
        ):
            self._restart_required = True
            raise GoogleWorkspaceHostV1UnknownOutcome(
                "Google external state witness restart is required"
            )

    def witness_mutation_allowed(self) -> None:
        self.drain_external_witness_temps()

    def sync_directory(self) -> None:
        if self._dirfd is None:
            return
        self.validate()
        try:
            os.fsync(self._dirfd)
        except OSError:
            _raise_clean(
                GoogleWorkspaceHostV1UnknownOutcome(
                    "Google external state witness parent outcome is unknown"
                )
            )

    def _close_windows_pin_once(self) -> None:
        if self._handle is None:
            return
        # Confirm the original handle still owns the pinned directory before a
        # retry.  An invalid/reused handle is never passed to CloseHandle.
        if self._windows_handle_identity() != self._windows_identity:
            self._handle = None
            raise GoogleWorkspaceHostV1UnknownOutcome(
                "Google metadata parent cleanup outcome is unknown"
            )
        from ctypes import wintypes

        close_handle = ctypes.WinDLL(
            "kernel32", use_last_error=True
        ).CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        if not close_handle(self._handle):
            try:
                self._windows_handle_identity()
            except GoogleWorkspaceHostV1Denied:
                self._handle = None
            raise GoogleWorkspaceHostV1UnknownOutcome(
                "Google metadata parent cleanup outcome is unknown"
            )
        self._handle = None

    def _close_posix_pin_once(self) -> None:
        descriptor = self._dirfd
        if descriptor is None:
            return
        try:
            os.close(descriptor)
        except OSError:
            # POSIX close error ownership is unspecified.  Irrevocably abandon
            # the number; never fstat or retry it in this process.
            self._dirfd = None
            self._restart_required = True
            _mark_external_witness_restart_required_v1(self.root)
            raise GoogleWorkspaceHostV1UnknownOutcome(
                "Google metadata parent cleanup outcome is unknown"
            ) from None
        self._dirfd = None

    def close(self) -> None:
        if self._closed:
            if self._restart_required:
                raise GoogleWorkspaceHostV1UnknownOutcome(
                    "Google external state witness restart is required"
                )
            return
        outcome: GoogleWorkspaceHostV1UnknownOutcome | None = None
        if self._restart_required:
            outcome = GoogleWorkspaceHostV1UnknownOutcome(
                "Google external state witness restart is required"
            )
        else:
            try:
                _cleanup_all_external_witness_temps_v1(self)
            except GoogleWorkspaceHostV1UnknownOutcome as exc:
                outcome = exc
        if self._handle is not None:
            try:
                self._close_windows_pin_once()
            except GoogleWorkspaceHostV1UnknownOutcome as exc:
                if outcome is None:
                    outcome = exc
        if self._dirfd is not None:
            try:
                self._close_posix_pin_once()
            except GoogleWorkspaceHostV1UnknownOutcome as exc:
                if outcome is None:
                    outcome = exc
        if self._handle is None and self._dirfd is None:
            self._closed = True
        if outcome is not None:
            _raise_clean(outcome)


def _validated_metadata_parent_v1() -> _GoogleMetadataParentAuthorityV1:
    root = private_control_plane_runtime_dir() / "google-workspace-host"
    if not root.is_absolute() or root == Path(root.anchor):
        raise GoogleWorkspaceHostV1Denied(
            "Google metadata parent authority is invalid"
        )

    current = Path(root.anchor)
    _directory_identity_v1(current)
    missing = False
    for component in root.parts[1:]:
        current /= component
        if not missing:
            try:
                _directory_identity_v1(current)
                continue
            except GoogleWorkspaceHostV1Denied:
                if current.exists() or current.is_symlink():
                    raise
                missing = True
        try:
            os.mkdir(current)
        except FileExistsError:
            pass
        except OSError:
            _raise_clean(
                GoogleWorkspaceHostV1Denied(
                    "Google metadata parent authority is invalid"
                )
            )
        _directory_identity_v1(current)
    parent = _GoogleMetadataParentAuthorityV1(root, _directory_identity_v1(root))
    try:
        if not parent._restart_required:
            _cleanup_all_external_witness_temps_v1(parent)
    except BaseException:
        try:
            parent.close()
        except BaseException:
            _raise_clean(
                GoogleWorkspaceHostV1UnknownOutcome(
                    "Google metadata parent cleanup outcome is unknown"
                )
            )
        raise
    return parent


def _validated_metadata_path_v1(binding_digest: str) -> Path:
    _valid_digest(binding_digest, "metadata binding")
    parent = _validated_metadata_parent_v1()
    try:
        parent.validate()
        return parent.root / f"{binding_digest}.sqlite3"
    finally:
        parent.close()


def _external_witness_payload_v1(scope_seed: str, state: str) -> bytes:
    if state not in {"PREPARED", "COMMITTED"}:
        raise GoogleWorkspaceHostV1ContractError(
            "Google external state witness state is invalid"
        )
    return _canonical(
        {
            "schema": "OnyxGoogleWorkspaceExternalState.v2",
            "scope": scope_seed,
            "state": state,
        }
    )


def _durable_write_external_witness_v1(
    scope_seed: str,
    state: str,
    *,
    parent: _GoogleMetadataParentAuthorityV1,
) -> None:
    path = _related_state_witness_path(scope_seed)
    parent.validate()
    if path.parent != parent.root:
        raise GoogleWorkspaceHostV1Denied("Google external state witness is invalid")
    payload = _external_witness_payload_v1(scope_seed, state)
    parent.drain_external_witness_temps()
    _cleanup_external_witness_temps_v1(path, parent=parent)
    temporary = path.with_name(f".{path.name}.tmp-{secrets.token_hex(16)}")
    owned: _OwnedExternalWitnessTempV1 | None = None
    close_attempted = False
    outcome: GoogleWorkspaceHostV1UnknownOutcome | None = None
    try:
        owned = _OwnedExternalWitnessTempV1.create(temporary)
        if owned.state != "open" or owned.descriptor is None:
            parent.retain_external_witness_temp(owned)
            raise GoogleWorkspaceHostV1UnknownOutcome(
                "Google external state witness outcome is unknown"
            )
        offset = 0
        while offset < len(payload):
            written = os.write(owned.descriptor, payload[offset:])
            if (
                type(written) is not int
                or written <= 0
                or written > len(payload) - offset
            ):
                raise OSError("bounded external witness write failed")
            offset += written
        os.fsync(owned.descriptor)
        close_attempted = True
        try:
            owned.close_once()
        except GoogleWorkspaceHostV1UnknownOutcome:
            parent.retain_external_witness_temp(owned)
            raise
        _validate_external_witness_temp_v1(
            temporary, scope_seed=scope_seed, expected_state=state
        )
        parent.validate()
        _before_external_witness_replace_v1()
        _atomic_replace_external_witness_v1(temporary, path)
        _after_external_witness_replace_v1()
        _sync_external_witness_parent_v1(parent)
        parent.validate()
        if _read_related_state_witness_v1(scope_seed) != state:
            raise GoogleWorkspaceHostV1UnknownOutcome(
                "Google external state witness outcome is unknown"
            )
    except GoogleWorkspaceHostV1UnknownOutcome as exc:
        outcome = exc
    except Exception:
        outcome = GoogleWorkspaceHostV1UnknownOutcome(
            "Google external state witness outcome is unknown"
        )
    finally:
        if (
            owned is not None
            and owned.descriptor is not None
            and not close_attempted
        ):
            close_attempted = True
            try:
                owned.close_once()
            except GoogleWorkspaceHostV1UnknownOutcome as close_outcome:
                parent.retain_external_witness_temp(owned)
                if outcome is None:
                    outcome = close_outcome
        try:
            _cleanup_external_witness_temps_v1(path, parent=parent)
        except GoogleWorkspaceHostV1UnknownOutcome as cleanup_outcome:
            if outcome is None:
                outcome = cleanup_outcome
        except Exception:
            if outcome is None:
                outcome = GoogleWorkspaceHostV1UnknownOutcome(
                    "Google external state witness cleanup outcome is unknown"
                )
    if outcome is not None:
        _raise_clean(outcome)


def _managed_external_witness_temp_v1(path: Path, name: str) -> bool:
    return re.fullmatch(
        re.escape(f".{path.name}.tmp-") + r"[0-9a-f]{32}", name
    ) is not None


def _any_managed_external_witness_temp_v1(name: str) -> bool:
    return re.fullmatch(
        r"\.authority-[0-9a-f]{64}\.state\.tmp-[0-9a-f]{32}", name
    ) is not None


def _unlink_external_witness_temp_entry_v1(entry: Path) -> None:
    native_entry = _native_filesystem_path_v1(entry)
    info = native_entry.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise OSError("managed external witness temp is invalid")
    native_entry.unlink()


def _cleanup_all_external_witness_temps_v1(
    parent: _GoogleMetadataParentAuthorityV1,
) -> None:
    parent.validate()
    abandoned = set(_abandoned_external_witness_temps_for_root_v1(parent.root))
    try:
        for entry in tuple(parent.root.iterdir()):
            if (
                _any_managed_external_witness_temp_v1(entry.name)
                and entry not in abandoned
            ):
                _unlink_external_witness_temp_entry_v1(entry)
    except OSError:
        _raise_clean(
            GoogleWorkspaceHostV1UnknownOutcome(
                "Google external state witness cleanup outcome is unknown"
            )
        )
    parent.validate()


def _cleanup_external_witness_temps_v1(
    path: Path, *, parent: _GoogleMetadataParentAuthorityV1
) -> None:
    parent.validate()
    abandoned = set(_abandoned_external_witness_temps_for_root_v1(parent.root))
    try:
        entries = tuple(parent.root.iterdir())
        for entry in entries:
            if (
                not _managed_external_witness_temp_v1(path, entry.name)
                or entry in abandoned
            ):
                continue
            _unlink_external_witness_temp_entry_v1(entry)
    except OSError:
        _raise_clean(
            GoogleWorkspaceHostV1UnknownOutcome(
                "Google external state witness cleanup outcome is unknown"
            )
        )
    parent.validate()


def _validate_external_witness_temp_v1(
    path: Path, *, scope_seed: str, expected_state: str
) -> None:
    try:
        native_path = _native_filesystem_path_v1(path)
        info = native_path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise OSError("external witness temp is invalid")
        raw = native_path.read_bytes()
    except OSError:
        _raise_clean(
            GoogleWorkspaceHostV1UnknownOutcome(
                "Google external state witness outcome is unknown"
            )
        )
    if _decode_external_witness_raw_v1(raw, scope_seed) != expected_state:
        raise GoogleWorkspaceHostV1UnknownOutcome(
            "Google external state witness outcome is unknown"
        )


def _before_external_witness_replace_v1() -> None:
    return None


def _after_external_witness_replace_v1() -> None:
    return None


def _atomic_replace_external_witness_v1(source: Path, destination: Path) -> None:
    if os.name == "nt":
        from ctypes import wintypes

        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        move.restype = wintypes.BOOL
        if not move(
            str(_native_filesystem_path_v1(source)),
            str(_native_filesystem_path_v1(destination)),
            0x00000001 | 0x00000008,
        ):
            _raise_clean(
                GoogleWorkspaceHostV1UnknownOutcome(
                    "Google external state witness replace outcome is unknown"
                )
            )
        return
    try:
        os.replace(source, destination)
    except OSError:
        _raise_clean(
            GoogleWorkspaceHostV1UnknownOutcome(
                "Google external state witness replace outcome is unknown"
            )
        )


def _sync_external_witness_parent_v1(
    parent: _GoogleMetadataParentAuthorityV1,
) -> None:
    parent.sync_directory()


def _prepare_related_state_witness_v1(
    scope_seed: str, *, parent: _GoogleMetadataParentAuthorityV1
) -> tuple[str, bool]:
    current = _read_related_state_witness_v1(scope_seed)
    if current is not None:
        return current, False
    _durable_write_external_witness_v1(
        scope_seed, "PREPARED", parent=parent
    )
    return "PREPARED", True


def _commit_related_state_witness_v1(
    scope_seed: str, *, parent: _GoogleMetadataParentAuthorityV1
) -> None:
    current = _read_related_state_witness_v1(scope_seed)
    if current == "COMMITTED":
        parent.validate()
        return
    if current != "PREPARED":
        raise GoogleWorkspaceHostV1Denied(
            "Google external state witness is incomplete"
        )
    _durable_write_external_witness_v1(
        scope_seed, "COMMITTED", parent=parent
    )


def _write_related_state_witness_v1(scope_seed: str) -> None:
    parent = _validated_metadata_parent_v1()
    try:
        _prepare_related_state_witness_v1(scope_seed, parent=parent)
        _commit_related_state_witness_v1(scope_seed, parent=parent)
    finally:
        parent.close()


def create_google_workspace_host_service_v1(
    *,
    gate: GoogleWorkspaceFeatureGateV1,
    configuration: GoogleWorkspaceHostConfigurationV1 | None,
) -> GoogleWorkspaceHostServiceV1 | None:
    """Production factory. Disabled/incomplete calls are exactly side-effect free."""
    if type(gate) is not GoogleWorkspaceFeatureGateV1:
        raise GoogleWorkspaceHostV1ContractError("exact feature gate required")
    if not gate.enabled or type(configuration) is not GoogleWorkspaceHostConfigurationV1:
        return None
    lease = NativeGoogleHostLeaseV1()
    mutation_possible = False
    receiver = None
    parent_authority = None
    try:
        if _read_related_state_witness_v1(
            _scope_seed(configuration.binding)
        ) != "COMMITTED":
            raise GoogleWorkspaceHostV1Denied(
                "Google external state witness is incomplete"
            )
        parts = _host_parts_v1(
            configuration, lease=lease, vault_factory=_native_vault_factory,
            provision=False,
        )
        stored = parts.configuration.load()
        if stored != configuration:
            lease.close()
            return None
        mutation_possible = True
        parent_authority = _validated_metadata_parent_v1()
        parent_authority.validate()
        metadata_path = parent_authority.root / f"{parts.binding_digest}.sqlite3"
        settings = GoogleOAuthSettingsV1(
            configuration.client_id, configuration.redirect_uri
        )
        metadata = SqliteGoogleGrantMetadataStoreV1(
            metadata_path, parts.root.keys()["metadata-file-auth"], parts.anchor
        )
        parent_authority.validate()
        connector = create_google_workspace_connector_v1(
            gate=gate, settings=settings, binding=configuration.binding,
            token_resolver=parts.token, token_persister=parts.token,
            pending_vault=parts.pending, metadata_store=metadata,
            transport=StdlibGoogleHttpTransportV1(),
            identity_pseudonymizer=parts.identity,
        )
        assert connector is not None
        receiver = GoogleOAuthLoopbackReceiverV1(configuration.redirect_uri)
        return GoogleWorkspaceHostServiceV1(
            connector=connector, receiver=receiver, browser_open=webbrowser.open,
            backend_name=parts.backend_name, anchor=parts.anchor,
            store_reference=metadata._store_reference,
            pending_vault=parts.pending, host_lease=lease,
            lease_scope=parts.root.scope,
            parent_authority=parent_authority,
        )
    except Exception:
        cleanup_failed = False
        if receiver is not None:
            try:
                receiver.close()
            except Exception:
                cleanup_failed = True
        if parent_authority is not None:
            try:
                parent_authority.close()
            except Exception:
                cleanup_failed = True
        try:
            lease.close()
        except Exception:
            cleanup_failed = True
        if cleanup_failed and mutation_possible:
            _raise_clean(
                GoogleWorkspaceHostV1UnknownOutcome(
                    "Google host construction outcome is unknown"
                )
            )
        raise


def _create_google_workspace_host_parts_for_test_v1(
    configuration: GoogleWorkspaceHostConfigurationV1,
    *, lease: ScopedHostLeaseV1, vault_factory: VaultFactoryV1,
    provision: bool = True,
) -> _GoogleWorkspaceHostPartsV1:
    """Explicit source-test seam; unreachable from the production factory."""
    return _host_parts_v1(
        configuration, lease=lease, vault_factory=vault_factory, provision=provision
    )


def _create_google_workspace_host_service_for_test_v1(
    *,
    gate: GoogleWorkspaceFeatureGateV1,
    configuration: GoogleWorkspaceHostConfigurationV1,
    metadata_store: GoogleGrantMetadataStoreV1,
    transport: GoogleHttpTransportV1,
    receiver: GoogleOAuthLoopbackReceiverV1,
    browser_open: Callable[[str], bool],
    lease: ScopedHostLeaseV1,
    vault_factory: VaultFactoryV1,
    epoch_clock: Callable[[], float] = time.time,
    parent_authority: _GoogleMetadataParentAuthorityV1 | None = None,
) -> GoogleWorkspaceHostServiceV1 | None:
    if type(gate) is not GoogleWorkspaceFeatureGateV1 or not gate.enabled:
        return None
    parts = _host_parts_v1(
        configuration, lease=lease, vault_factory=vault_factory, provision=True
    )
    parts.configuration.configure(configuration)
    connector = create_google_workspace_connector_v1(
        gate=gate,
        settings=GoogleOAuthSettingsV1(configuration.client_id, configuration.redirect_uri),
        binding=configuration.binding, token_resolver=parts.token,
        token_persister=parts.token, pending_vault=parts.pending,
        metadata_store=metadata_store, transport=transport,
        identity_pseudonymizer=parts.identity,
    )
    assert connector is not None
    return GoogleWorkspaceHostServiceV1(
        connector=connector, receiver=receiver, browser_open=browser_open,
        epoch_clock=epoch_clock, backend_name=parts.backend_name,
        anchor=parts.anchor, store_reference="0" * 64,
        pending_vault=parts.pending, host_lease=lease,
        lease_scope=parts.root.scope,
        parent_authority=parent_authority,
    )


__all__ = [name for name in globals() if name.startswith("Google") or name.startswith("NativeGoogle") or name in {
    "configure_google_workspace_host_v1", "create_google_workspace_host_service_v1"
}]
