"""Persistent, tamper-evident public DayOps configuration for Onyx V19.

The profile deliberately contains only public Microsoft application identifiers,
time-zone names, and bindings derived from the active governance identity.  Its
authentication key lives only in the operating-system native secret vault.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Protocol

from core import native_vault
from core.dayops_graph_factory_v1 import DayOpsGraphBindingV1
from core.dayops_live_integration_v1 import (
    IANA_TIMEZONE_KEY,
    OUTLOOK_TIMEZONE_KEY,
    DayOpsConfigurationV1,
)
from core.governance_nucleus_v1 import GovernanceIdentityV1
from core.paths import config_dir
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    ENV_ACCOUNT_ID,
    ENV_CLIENT_ID,
    ENV_TENANT_ID,
    MicrosoftGraphLiveOnboardingV1,
)


SCHEMA: Final = "OnyxDayOpsProfile.v19"
PROFILE_FILENAME: Final = "dayops-profile-v19.json"
PROFILE_KEY_SERVICE: Final = "CyryxLabs.Onyx.DayOpsProfile.v19"
PROFILE_KEY_BYTES: Final = 32
MAX_PROFILE_BYTES: Final = 16_384
_PAYLOAD_FIELDS: Final = frozenset(
    {
        "client_id",
        "tenant_id",
        "account_id",
        "iana_timezone",
        "outlook_timezone",
        "workspace_id",
        "principal_id",
        "credential_alias_name",
    }
)
_ENVELOPE_FIELDS: Final = frozenset({"schema", "payload", "mac"})
_LOCK = threading.RLock()


class DayOpsProfileV19Error(RuntimeError):
    pass


class DayOpsProfileV19ContractError(ValueError):
    pass


class DayOpsProfileV19Unavailable(DayOpsProfileV19Error):
    pass


class DayOpsProfileV19Tamper(DayOpsProfileV19Error):
    pass


class DayOpsProfileV19IdentityMismatch(DayOpsProfileV19Error):
    pass


class SecretBytesVaultV19(Protocol):
    def get_bytes(self) -> bytes | None: ...

    def set_bytes(self, secret: bytes | bytearray) -> None: ...


def _exact_identity(identity: GovernanceIdentityV1) -> GovernanceIdentityV1:
    if type(identity) is not GovernanceIdentityV1:
        raise DayOpsProfileV19ContractError("exact governance identity is required")
    return identity


def _profile_alias(identity: GovernanceIdentityV1, account_id: str) -> str:
    digest = hashlib.sha256(
        (
            f"{identity.workspace_id}\0{identity.principal_id}\0{account_id.casefold()}"
        ).encode("utf-8")
    ).hexdigest()
    return f"dayops-ms-{digest[:24]}"


@dataclass(frozen=True, slots=True)
class DayOpsProfileV19:
    client_id: str
    tenant_id: str
    account_id: str
    iana_timezone: str
    outlook_timezone: str
    workspace_id: str
    principal_id: str
    credential_alias_name: str

    @classmethod
    def create(
        cls,
        identity: GovernanceIdentityV1,
        *,
        client_id: str,
        tenant_id: str,
        account_id: str,
        iana_timezone: str,
        outlook_timezone: str,
    ) -> "DayOpsProfileV19":
        active = _exact_identity(identity)
        values = (
            client_id,
            tenant_id,
            account_id,
            iana_timezone,
            outlook_timezone,
        )
        if any(type(value) is not str or value != value.strip() for value in values):
            raise DayOpsProfileV19ContractError(
                "public DayOps profile values are invalid"
            )
        try:
            onboarding = MicrosoftGraphLiveOnboardingV1(
                client_id, tenant_id, account_id
            )
        except (TypeError, ValueError, PermissionError) as exc:
            raise DayOpsProfileV19ContractError(
                "public Microsoft onboarding identifiers are invalid"
            ) from exc
        timezone_config = DayOpsConfigurationV1.from_environ(
            {
                IANA_TIMEZONE_KEY: iana_timezone,
                OUTLOOK_TIMEZONE_KEY: outlook_timezone,
            }
        )
        if timezone_config is None:
            raise DayOpsProfileV19ContractError(
                "DayOps time-zone configuration is invalid"
            )
        alias = _profile_alias(active, onboarding.account_id)
        # Reuse the accepted binding contract as a compatibility assertion.
        DayOpsGraphBindingV1(
            active.workspace_id,
            active.principal_id,
            alias,
            onboarding,
        )
        return cls(
            onboarding.client_id,
            onboarding.tenant_id,
            onboarding.account_id,
            timezone_config.iana_timezone,
            timezone_config.outlook_timezone,
            active.workspace_id,
            active.principal_id,
            alias,
        )

    def public_environment(self) -> dict[str, str]:
        """Return a private mapping for the accepted V1 adapter factory."""

        from core.dayops_graph_factory_v1 import (  # avoids duplicated literals
            CREDENTIAL_ALIAS_KEY,
            PRINCIPAL_ID_KEY,
            WORKSPACE_ID_KEY,
        )

        return {
            WORKSPACE_ID_KEY: self.workspace_id,
            PRINCIPAL_ID_KEY: self.principal_id,
            CREDENTIAL_ALIAS_KEY: self.credential_alias_name,
            ENV_CLIENT_ID: self.client_id,
            ENV_TENANT_ID: self.tenant_id,
            ENV_ACCOUNT_ID: self.account_id,
            IANA_TIMEZONE_KEY: self.iana_timezone,
            OUTLOOK_TIMEZONE_KEY: self.outlook_timezone,
        }


def profile_key_reference_v19(
    identity: GovernanceIdentityV1,
) -> native_vault.SecretReference:
    active = _exact_identity(identity)
    fingerprint = hashlib.sha256(
        f"{active.workspace_id}\0{active.principal_id}".encode("utf-8")
    ).hexdigest()
    return native_vault.SecretReference(
        PROFILE_KEY_SERVICE,
        f"profile_{fingerprint[:40]}",
        "Cyryx Labs Onyx DayOps public profile authentication key",
    )


def _canonical(schema: str, payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        {"schema": schema, "payload": payload},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise DayOpsProfileV19Tamper("DayOps profile contains duplicate fields")
        value[key] = item
    return value


def _is_reparse(path: Path) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(details, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse)


def _trusted_path(path: Path) -> None:
    if not path.is_absolute():
        raise DayOpsProfileV19ContractError("DayOps profile path must be absolute")
    cursor = path.parent
    existing: list[Path] = []
    while True:
        if cursor.exists():
            existing.append(cursor)
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    if any(_is_reparse(item) for item in existing) or _is_reparse(path):
        raise DayOpsProfileV19Unavailable("DayOps profile path is not trusted")


class DayOpsProfileStoreV19:
    """Atomic profile persistence with a native-vault HMAC boundary."""

    __slots__ = ("_identity", "_key_vault", "path")

    def __init__(
        self,
        identity: GovernanceIdentityV1,
        *,
        path: Path | str | None = None,
        key_vault: SecretBytesVaultV19 | None = None,
    ) -> None:
        self._identity = _exact_identity(identity)
        selected = config_dir() / PROFILE_FILENAME if path is None else Path(path)
        if not selected.is_absolute():
            raise DayOpsProfileV19ContractError("DayOps profile path must be absolute")
        self.path = selected
        self._key_vault = (
            native_vault.NativeSecretVault(profile_key_reference_v19(identity))
            if key_vault is None
            else key_vault
        )
        if not callable(getattr(self._key_vault, "get_bytes", None)) or not callable(
            getattr(self._key_vault, "set_bytes", None)
        ):
            raise DayOpsProfileV19ContractError("profile key vault is invalid")

    @property
    def identity(self) -> GovernanceIdentityV1:
        return self._identity

    def _read_key(self) -> bytes | None:
        try:
            value = self._key_vault.get_bytes()
        except native_vault.NativeVaultError as exc:
            raise DayOpsProfileV19Unavailable(
                "DayOps profile key vault is unavailable"
            ) from exc
        if value is None:
            return None
        if type(value) is not bytes or len(value) != PROFILE_KEY_BYTES:
            raise DayOpsProfileV19Unavailable(
                "DayOps profile authentication key is invalid"
            )
        return value

    def _key_for_save(self) -> bytes:
        key = self._read_key()
        if key is not None:
            return key
        candidate = secrets.token_bytes(PROFILE_KEY_BYTES)
        try:
            self._key_vault.set_bytes(candidate)
        except native_vault.NativeVaultError as exc:
            raise DayOpsProfileV19Unavailable(
                "DayOps profile key vault is unavailable"
            ) from exc
        verified = self._read_key()
        if verified is None or not hmac.compare_digest(verified, candidate):
            raise DayOpsProfileV19Unavailable(
                "DayOps profile key could not be verified"
            )
        return verified

    def save(self, profile: DayOpsProfileV19) -> None:
        if type(profile) is not DayOpsProfileV19:
            raise DayOpsProfileV19ContractError("exact DayOps profile is required")
        expected = DayOpsProfileV19.create(
            self._identity,
            client_id=profile.client_id,
            tenant_id=profile.tenant_id,
            account_id=profile.account_id,
            iana_timezone=profile.iana_timezone,
            outlook_timezone=profile.outlook_timezone,
        )
        if not hmac.compare_digest(
            json.dumps(asdict(expected), sort_keys=True),
            json.dumps(asdict(profile), sort_keys=True),
        ):
            raise DayOpsProfileV19IdentityMismatch(
                "DayOps profile does not match the active identity"
            )
        with _LOCK:
            _trusted_path(self.path)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise DayOpsProfileV19Unavailable(
                    "DayOps profile directory is unavailable"
                ) from exc
            _trusted_path(self.path)
            payload = asdict(profile)
            key = self._key_for_save()
            mac = hmac.new(key, _canonical(SCHEMA, payload), hashlib.sha256).hexdigest()
            encoded = json.dumps(
                {"schema": SCHEMA, "payload": payload, "mac": mac},
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            temporary = self.path.with_name(
                f".{self.path.name}.{secrets.token_hex(8)}.tmp"
            )
            try:
                with temporary.open("xb") as stream:
                    os.chmod(temporary, 0o600)
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                os.chmod(self.path, 0o600)
            except OSError as exc:
                raise DayOpsProfileV19Unavailable(
                    "DayOps profile could not be persisted"
                ) from exc
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def load(self) -> DayOpsProfileV19:
        with _LOCK:
            _trusted_path(self.path)
            key = self._read_key()
            if key is None or not self.path.is_file():
                raise DayOpsProfileV19Unavailable(
                    "DayOps public profile is not provisioned"
                )
            try:
                raw = self.path.read_bytes()
            except OSError as exc:
                raise DayOpsProfileV19Unavailable(
                    "DayOps public profile is unavailable"
                ) from exc
            if not raw or len(raw) > MAX_PROFILE_BYTES:
                raise DayOpsProfileV19Tamper("DayOps profile size is invalid")
            try:
                envelope = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
            except DayOpsProfileV19Tamper:
                raise
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DayOpsProfileV19Tamper("DayOps profile is malformed") from exc
            if type(envelope) is not dict or set(envelope) != _ENVELOPE_FIELDS:
                raise DayOpsProfileV19Tamper("DayOps profile envelope is invalid")
            schema = envelope.get("schema")
            payload = envelope.get("payload")
            mac = envelope.get("mac")
            if (
                schema != SCHEMA
                or type(payload) is not dict
                or set(payload) != _PAYLOAD_FIELDS
                or type(mac) is not str
                or len(mac) != 64
            ):
                raise DayOpsProfileV19Tamper("DayOps profile contract is invalid")
            expected_mac = hmac.new(
                key, _canonical(SCHEMA, payload), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(mac, expected_mac):
                raise DayOpsProfileV19Tamper("DayOps profile authentication failed")
            stored_workspace = payload.get("workspace_id")
            stored_principal = payload.get("principal_id")
            if (
                stored_workspace != self._identity.workspace_id
                or stored_principal != self._identity.principal_id
            ):
                raise DayOpsProfileV19IdentityMismatch(
                    "DayOps profile belongs to a different identity"
                )
            try:
                rebuilt = DayOpsProfileV19.create(
                    self._identity,
                    client_id=payload["client_id"],
                    tenant_id=payload["tenant_id"],
                    account_id=payload["account_id"],
                    iana_timezone=payload["iana_timezone"],
                    outlook_timezone=payload["outlook_timezone"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise DayOpsProfileV19Tamper(
                    "DayOps profile payload is invalid"
                ) from exc
            if asdict(rebuilt) != payload:
                raise DayOpsProfileV19IdentityMismatch(
                    "DayOps profile binding does not match the active identity"
                )
            return rebuilt


__all__ = [
    "DayOpsProfileStoreV19",
    "DayOpsProfileV19",
    "DayOpsProfileV19ContractError",
    "DayOpsProfileV19Error",
    "DayOpsProfileV19IdentityMismatch",
    "DayOpsProfileV19Tamper",
    "DayOpsProfileV19Unavailable",
    "PROFILE_FILENAME",
    "PROFILE_KEY_SERVICE",
    "SCHEMA",
    "profile_key_reference_v19",
]
