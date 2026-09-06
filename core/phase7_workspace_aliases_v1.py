"""Typed, workspace-scoped aliases for Phase 7.

This module stores signed *locators and identities*, never credential values,
browser cookies, profile contents, or artifact bytes.  It is additive to the
accepted control-plane sidecar and remains exactly default-off.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from core.control_plane import ControlPlaneStore
from core.workspaces import (
    LEGACY_WORKSPACE_ID,
    WorkspaceError,
    WorkspaceRecord,
    WorkspaceRegistry,
)
from memory.store import contains_secret


FEATURE_FLAG: Final = "ONYX_PHASE7_WORKSPACE_ALIASES_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxWorkspaceAlias.v1"
SCHEMA_VERSION: Final = 1
CAPABILITY_PREFIX: Final = "workspace-alias-v1-"
MAX_ALIASES: Final = 2_000
MAX_SCOPES: Final = 32
MAX_DOMAINS: Final = 64
MAX_PAYLOAD_BYTES: Final = 32 * 1024
ALIAS_KINDS: Final = frozenset({"credential", "profile", "artifact"})
SUPPORTED_BROWSERS: Final = frozenset(
    {
        "brave",
        "chrome",
        "edge",
        "firefox",
        "opera",
        "operagx",
        "safari",
        "vivaldi",
    }
)
WORKSPACE_MEMORY_ENTRY_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase7-workspace-memory-v1/manifest.json",
        "59ed88abd6967a73f3050d1215fed0c278b21b5c6e5335814abe8267576c9cd7",
    ),
    (
        "docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.md",
        "3490c0f89ba37c81c67f7e76dc2daedac91622e8386efe668e259d4819848825",
    ),
    (
        "docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.manifest.json",
        "c6497c644f447a1bc83b63446c25c8be4071dcf103b5dfbf2a5de7b809edf43a",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P7-WORKSPACE-MEMORY-V1-E6-001.sha256",
        "9628e79458bd8ef76ce8fbbc56939182638b2b10dbf2262b9e4c2b3d677bdfa9",
    ),
)

_WORKSPACE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_PRINCIPAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_ALIAS_NAME = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_PROVIDER = re.compile(r"^[a-z][a-z0-9.-]{1,63}$")
_ACCOUNT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$")
_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,191}$")
_PROFILE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}/"
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}$"
)
_FORBIDDEN_SUPPLIED_TEXT = re.compile(
    r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|"
    r"private[_ -]?key|authorization|bearer|cookie|session[_ -]?(?:id|token)|"
    r"client[_ -]?secret|secret)",
    re.IGNORECASE,
)
_CONSTRUCTION_KEY = object()
_WRITE_LOCK = threading.RLock()


class WorkspaceAliasV1Error(RuntimeError):
    """Base error for the Phase 7 alias catalog."""


class WorkspaceAliasV1ContractError(ValueError):
    """A caller or stored row violated the typed alias contract."""


class WorkspaceAliasV1Denied(PermissionError):
    """Workspace, principal, lifecycle, or integrity checks denied access."""


class WorkspaceAliasV1Conflict(WorkspaceAliasV1Error):
    """An immutable alias identity already exists with different content."""


@dataclass(frozen=True, slots=True)
class WorkspaceAliasFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise WorkspaceAliasV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls,
        environ: dict[str, str] | os._Environ[str] | None = None,
    ) -> "WorkspaceAliasFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class CredentialAliasSpecV1:
    provider: str
    account_id: str
    tenant_id: str | None = None
    scopes: tuple[str, ...] = ()
    rotate_after_ms: int | None = None
    revoke_after_ms: int | None = None

    def __post_init__(self) -> None:
        _validate_provider(self.provider)
        _validate_account("account_id", self.account_id)
        if self.tenant_id is not None:
            _validate_account("tenant_id", self.tenant_id)
        _validate_scopes(self.scopes)
        _optional_ms("rotate_after_ms", self.rotate_after_ms)
        _optional_ms("revoke_after_ms", self.revoke_after_ms)
        if (
            self.rotate_after_ms is not None
            and self.revoke_after_ms is not None
            and self.rotate_after_ms > self.revoke_after_ms
        ):
            raise WorkspaceAliasV1ContractError(
                "credential rotation cannot follow revocation"
            )


@dataclass(frozen=True, slots=True)
class ProfileAliasSpecV1:
    browser: str
    profile_id: str
    allowed_domains: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.browser) is not str or self.browser not in SUPPORTED_BROWSERS:
            raise WorkspaceAliasV1ContractError("browser is unsupported")
        _validate_identifier("profile_id", self.profile_id, _PROFILE_ID)
        _validate_domains(self.allowed_domains)


@dataclass(frozen=True, slots=True)
class ArtifactAliasSpecV1:
    artifact_id: str
    sha256: str
    relative_path: str
    media_type: str

    def __post_init__(self) -> None:
        _validate_identifier("artifact_id", self.artifact_id, _ARTIFACT_ID)
        _validate_digest_path(self.sha256, self.relative_path)
        if type(self.media_type) is not str or not _MEDIA_TYPE.fullmatch(
            self.media_type
        ):
            raise WorkspaceAliasV1ContractError("media_type is invalid")
        _reject_secret_text("media_type", self.media_type)


AliasSpecV1 = CredentialAliasSpecV1 | ProfileAliasSpecV1 | ArtifactAliasSpecV1


@dataclass(frozen=True, slots=True)
class WorkspaceAliasRecordV1:
    alias_id: str
    workspace_id: str
    principal_id: str
    kind: str
    alias_name: str
    locator: str
    status: str
    created_at_ms: int
    updated_at_ms: int
    revoked_at_ms: int | None
    provider: str | None = None
    account_id: str | None = None
    tenant_id: str | None = None
    scopes: tuple[str, ...] = ()
    vault_service: str | None = None
    vault_account: str | None = None
    rotate_after_ms: int | None = None
    revoke_after_ms: int | None = None
    browser: str | None = None
    profile_id: str | None = None
    allowed_domains: tuple[str, ...] = ()
    artifact_id: str | None = None
    sha256: str | None = None
    relative_path: str | None = None
    media_type: str | None = None
    artifact_schema_version: int | None = None
    artifact_created_at: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.alias_id) is not str
            or not self.alias_id.startswith(CAPABILITY_PREFIX)
            or not _WORKSPACE_ID.fullmatch(self.workspace_id)
            or self.workspace_id == LEGACY_WORKSPACE_ID
            or not _PRINCIPAL_ID.fullmatch(self.principal_id)
            or self.kind not in ALIAS_KINDS
            or not _ALIAS_NAME.fullmatch(self.alias_name)
            or self.status not in {"active", "revoked"}
            or type(self.created_at_ms) is not int
            or type(self.updated_at_ms) is not int
            or self.created_at_ms < 0
            or self.updated_at_ms < self.created_at_ms
            or (
                self.revoked_at_ms is not None
                and (
                    type(self.revoked_at_ms) is not int
                    or self.revoked_at_ms < self.created_at_ms
                )
            )
        ):
            raise WorkspaceAliasV1ContractError("alias record contract drift")
        if self.status == "active" and self.revoked_at_ms is not None:
            raise WorkspaceAliasV1ContractError("active alias cannot be revoked")
        if self.status == "revoked" and self.revoked_at_ms is None:
            raise WorkspaceAliasV1ContractError("revoked alias lacks timestamp")
        if self.kind == "credential":
            if (
                self.provider is None
                or self.account_id is None
                or self.vault_service is None
                or self.vault_account is None
                or self.browser is not None
                or self.artifact_id is not None
            ):
                raise WorkspaceAliasV1ContractError(
                    "credential alias shape drift"
                )
        elif self.kind == "profile":
            if (
                self.browser is None
                or self.profile_id is None
                or not self.allowed_domains
                or self.provider is not None
                or self.artifact_id is not None
            ):
                raise WorkspaceAliasV1ContractError("profile alias shape drift")
        elif (
            self.artifact_id is None
            or self.sha256 is None
            or self.relative_path is None
            or self.media_type is None
            or self.artifact_schema_version is None
            or self.artifact_created_at is None
            or self.provider is not None
            or self.browser is not None
        ):
            raise WorkspaceAliasV1ContractError("artifact alias shape drift")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WorkspaceAliasV1ContractError(
            "value is not canonical JSON"
        ) from exc


def _exact_key(value: bytes) -> bytes:
    if type(value) is not bytes or not 32 <= len(value) <= 64 or not any(value):
        raise WorkspaceAliasV1ContractError(
            "integrity key must be 32-64 non-zero bytes"
        )
    return value


def _reject_secret_text(label: str, value: str) -> str:
    if (
        type(value) is not str
        or not value
        or any(ord(character) < 32 for character in value)
        or _FORBIDDEN_SUPPLIED_TEXT.search(value)
        or contains_secret(value)
    ):
        raise WorkspaceAliasV1ContractError(
            f"{label} contains secret-like or unsafe material"
        )
    return value


def _validate_identifier(label: str, value: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or not value:
        raise WorkspaceAliasV1ContractError(f"{label} is invalid")
    _reject_secret_text(label, value)
    if not pattern.fullmatch(value):
        raise WorkspaceAliasV1ContractError(f"{label} is invalid")
    return value


def _validate_workspace_id(value: str) -> str:
    if (
        type(value) is not str
        or not _WORKSPACE_ID.fullmatch(value)
        or value == LEGACY_WORKSPACE_ID
    ):
        raise WorkspaceAliasV1ContractError(
            "explicit non-legacy workspace_id required"
        )
    return value


def _validate_principal_id(value: str) -> str:
    return _validate_identifier("principal_id", value, _PRINCIPAL_ID)


def _validate_alias_name(value: str) -> str:
    return _validate_identifier("alias_name", value, _ALIAS_NAME)


def _validate_provider(value: str) -> str:
    return _validate_identifier("provider", value, _PROVIDER)


def _validate_account(label: str, value: str) -> str:
    return _validate_identifier(label, value, _ACCOUNT)


def _optional_ms(label: str, value: int | None) -> int | None:
    if value is not None and (type(value) is not int or value < 0):
        raise WorkspaceAliasV1ContractError(f"{label} is invalid")
    return value


def _iso_from_ms(value: int) -> str:
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(
            timespec="milliseconds"
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise WorkspaceAliasV1ContractError("timestamp is out of range") from exc


def _validate_scopes(value: tuple[str, ...]) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or len(value) > MAX_SCOPES
        or len(set(value)) != len(value)
    ):
        raise WorkspaceAliasV1ContractError("scopes are invalid")
    for scope in value:
        _validate_identifier("scope", scope, _SCOPE)
    return value


def _canonical_domain(value: str) -> str:
    if type(value) is not str or not value or len(value) > 253:
        raise WorkspaceAliasV1ContractError("allowed domain is invalid")
    _reject_secret_text("allowed domain", value)
    try:
        domain = value.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise WorkspaceAliasV1ContractError("allowed domain is invalid") from exc
    labels = domain.split(".")
    if (
        len(labels) < 2
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not re.fullmatch(r"[a-z0-9-]+", label)
            for label in labels
        )
    ):
        raise WorkspaceAliasV1ContractError("allowed domain is invalid")
    return domain


def _validate_domains(value: tuple[str, ...]) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or not value
        or len(value) > MAX_DOMAINS
    ):
        raise WorkspaceAliasV1ContractError("allowed_domains are invalid")
    canonical = tuple(_canonical_domain(item) for item in value)
    if canonical != value or len(set(canonical)) != len(canonical):
        raise WorkspaceAliasV1ContractError(
            "allowed_domains must be canonical and unique"
        )
    return value


def _validate_digest_path(digest: str, relative_path: str) -> None:
    if type(digest) is not str or not _HEX64.fullmatch(digest):
        raise WorkspaceAliasV1ContractError("artifact sha256 is noncanonical")
    if relative_path != f"{digest[:2]}/{digest}":
        raise WorkspaceAliasV1ContractError(
            "artifact relative_path is noncanonical"
        )


def workspace_alias_id_v1(
    *,
    workspace_id: str,
    principal_id: str,
    kind: str,
    alias_name: str,
) -> str:
    workspace = _validate_workspace_id(workspace_id)
    principal = _validate_principal_id(principal_id)
    if kind not in ALIAS_KINDS:
        raise WorkspaceAliasV1ContractError("alias kind is invalid")
    name = _validate_alias_name(alias_name)
    digest = hashlib.sha256(
        _canonical([SCHEMA, workspace, principal, kind, name])
    ).hexdigest()
    return CAPABILITY_PREFIX + digest


def credential_vault_locator_v1(
    *,
    workspace_id: str,
    provider: str,
    account_id: str,
    tenant_id: str | None = None,
) -> tuple[str, str, str]:
    """Return stable OS-vault service/account identities, never a secret."""

    workspace = _validate_workspace_id(workspace_id)
    selected_provider = _validate_provider(provider)
    account = _validate_account("account_id", account_id)
    tenant = (
        "default"
        if tenant_id is None
        else _validate_account("tenant_id", tenant_id)
    )
    service = f"CyryxLabs.Onyx.v1.{workspace}.{selected_provider}"
    vault_account = f"{tenant}:{account}"
    locator = f"onyx-vault://v1/{workspace}/{selected_provider}/{tenant}/{account}"
    return service, vault_account, locator


def browser_profile_locator_v1(
    *,
    workspace_id: str,
    browser: str,
    profile_id: str,
) -> str:
    workspace = _validate_workspace_id(workspace_id)
    if type(browser) is not str or browser not in SUPPORTED_BROWSERS:
        raise WorkspaceAliasV1ContractError("browser is unsupported")
    profile = _validate_identifier("profile_id", profile_id, _PROFILE_ID)
    return f"onyx-profile://v1/{workspace}/{browser}/{profile}"


def artifact_locator_v1(*, workspace_id: str, artifact_id: str) -> str:
    workspace = _validate_workspace_id(workspace_id)
    artifact = _validate_identifier("artifact_id", artifact_id, _ARTIFACT_ID)
    return f"onyx-artifact://v1/{workspace}/{artifact}"


def _is_reparse(info: os.stat_result) -> bool:
    return bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _strict_json(text: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise WorkspaceAliasV1Denied(f"duplicate alias key: {key}")
            value[key] = item
        return value

    if type(text) is not str or len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise WorkspaceAliasV1Denied("alias payload is invalid")

    def reject_constant(_value: str) -> object:
        raise WorkspaceAliasV1Denied("alias payload contains a non-finite number")

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (TypeError, json.JSONDecodeError) as exc:
        raise WorkspaceAliasV1Denied("alias payload is invalid") from exc
    if type(parsed) is not dict:
        raise WorkspaceAliasV1Denied("alias payload must be an object")
    return parsed


def _verify_workspace_memory_entry(project_root: Path | str) -> None:
    try:
        lexical_root = Path(project_root).absolute()
        root_info = os.lstat(lexical_root)
        root = lexical_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceAliasV1Denied(
            "Workspace Memory V1 entry root is unavailable"
        ) from exc
    if (
        root != lexical_root
        or not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or _is_reparse(root_info)
    ):
        raise WorkspaceAliasV1Denied(
            "Workspace Memory V1 entry root is not canonical"
        )
    payloads: dict[str, bytes] = {}
    for relative, expected in WORKSPACE_MEMORY_ENTRY_ROOTS:
        value = Path(relative)
        if value.is_absolute() or ".." in value.parts:
            raise WorkspaceAliasV1Denied(
                "Workspace Memory V1 entry path is unsafe"
            )
        path = root.joinpath(*value.parts)
        try:
            info = os.lstat(path)
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            payload = resolved.read_bytes()
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkspaceAliasV1Denied(
                "Workspace Memory V1 entry evidence is unavailable"
            ) from exc
        if (
            resolved != path.absolute()
            or not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or _is_reparse(info)
            or hashlib.sha256(payload).hexdigest() != expected
        ):
            raise WorkspaceAliasV1Denied(
                "Workspace Memory V1 entry evidence drift denied"
            )
        payloads[relative] = payload
    metadata_path = (
        "docs/onyx/acceptance/"
        "VE-P7-WORKSPACE-MEMORY-V1-E6-001.manifest.json"
    )
    try:
        metadata_text = payloads[metadata_path].decode("utf-8")
    except UnicodeError as exc:
        raise WorkspaceAliasV1Denied(
            "Workspace Memory V1 acceptance is not UTF-8"
        ) from exc
    metadata = _strict_json(metadata_text)
    claims = metadata.get("claims")
    if (
        metadata.get("acceptance_id")
        != "VE-P7-WORKSPACE-MEMORY-V1-E6-001"
        or metadata.get("decision") != "accepted"
        or metadata.get("findings")
        != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or type(claims) is not dict
        or claims.get("workspace_memory_v1_accepted") is not True
        or claims.get("pre_ranking_hard_filters") is not True
        or claims.get("runtime_authority_added") is not False
        or claims.get("phase7_exit") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise WorkspaceAliasV1Denied(
            "Workspace Memory V1 acceptance contract drift"
        )


def _payload_mac(payload: dict[str, object], key: bytes) -> str:
    unsigned = {name: value for name, value in payload.items() if name != "hmac_sha256"}
    return hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()


def _spec_kind(spec: AliasSpecV1) -> str:
    if type(spec) is CredentialAliasSpecV1:
        return "credential"
    if type(spec) is ProfileAliasSpecV1:
        return "profile"
    if type(spec) is ArtifactAliasSpecV1:
        return "artifact"
    raise WorkspaceAliasV1ContractError("exact typed alias spec required")


def _descriptor_from_spec(
    spec: AliasSpecV1,
    *,
    workspace_id: str,
    artifact_binding: dict[str, object] | None,
) -> tuple[str, dict[str, object]]:
    kind = _spec_kind(spec)
    if kind == "credential":
        assert type(spec) is CredentialAliasSpecV1
        service, account, locator = credential_vault_locator_v1(
            workspace_id=workspace_id,
            provider=spec.provider,
            account_id=spec.account_id,
            tenant_id=spec.tenant_id,
        )
        return locator, {
            "provider": spec.provider,
            "account_id": spec.account_id,
            "tenant_id": spec.tenant_id,
            "scopes": list(spec.scopes),
            "vault_service": service,
            "vault_account": account,
            "rotate_after_ms": spec.rotate_after_ms,
            "revoke_after_ms": spec.revoke_after_ms,
        }
    if kind == "profile":
        assert type(spec) is ProfileAliasSpecV1
        locator = browser_profile_locator_v1(
            workspace_id=workspace_id,
            browser=spec.browser,
            profile_id=spec.profile_id,
        )
        return locator, {
            "browser": spec.browser,
            "profile_id": spec.profile_id,
            "allowed_domains": list(spec.allowed_domains),
            "dedicated_workspace_profile": True,
        }
    assert type(spec) is ArtifactAliasSpecV1
    if artifact_binding is None:
        raise WorkspaceAliasV1Denied("artifact binding is unavailable")
    locator = artifact_locator_v1(
        workspace_id=workspace_id,
        artifact_id=spec.artifact_id,
    )
    return locator, dict(artifact_binding)


def _build_payload(
    *,
    alias_id: str,
    workspace_id: str,
    principal_id: str,
    kind: str,
    alias_name: str,
    locator: str,
    descriptor: dict[str, object],
    status: str,
    created_at_ms: int,
    updated_at_ms: int,
    revoked_at_ms: int | None,
    key: bytes,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": SCHEMA,
        "alias_id": alias_id,
        "workspace_id": workspace_id,
        "principal_id": principal_id,
        "kind": kind,
        "alias_name": alias_name,
        "locator": locator,
        "descriptor": descriptor,
        "status": status,
        "created_at_ms": created_at_ms,
        "updated_at_ms": updated_at_ms,
        "revoked_at_ms": revoked_at_ms,
        "key_fingerprint_sha256": hashlib.sha256(key).hexdigest(),
    }
    payload["hmac_sha256"] = _payload_mac(payload, key)
    return payload


def _expected_payload_keys() -> set[str]:
    return {
        "schema",
        "alias_id",
        "workspace_id",
        "principal_id",
        "kind",
        "alias_name",
        "locator",
        "descriptor",
        "status",
        "created_at_ms",
        "updated_at_ms",
        "revoked_at_ms",
        "key_fingerprint_sha256",
        "hmac_sha256",
    }


def _validate_descriptor_shape(kind: str, value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise WorkspaceAliasV1Denied("alias descriptor must be an object")
    descriptor = value
    if kind == "credential":
        expected = {
            "provider",
            "account_id",
            "tenant_id",
            "scopes",
            "vault_service",
            "vault_account",
            "rotate_after_ms",
            "revoke_after_ms",
        }
        if set(descriptor) != expected:
            raise WorkspaceAliasV1Denied("credential alias shape drift")
        try:
            spec = CredentialAliasSpecV1(
                provider=descriptor["provider"],  # type: ignore[arg-type]
                account_id=descriptor["account_id"],  # type: ignore[arg-type]
                tenant_id=descriptor["tenant_id"],  # type: ignore[arg-type]
                scopes=tuple(descriptor["scopes"]),  # type: ignore[arg-type]
                rotate_after_ms=descriptor["rotate_after_ms"],  # type: ignore[arg-type]
                revoke_after_ms=descriptor["revoke_after_ms"],  # type: ignore[arg-type]
            )
        except (TypeError, WorkspaceAliasV1ContractError) as exc:
            raise WorkspaceAliasV1Denied("credential alias is invalid") from exc
        if list(spec.scopes) != descriptor["scopes"]:
            raise WorkspaceAliasV1Denied("credential scopes are noncanonical")
        return descriptor
    if kind == "profile":
        expected = {
            "browser",
            "profile_id",
            "allowed_domains",
            "dedicated_workspace_profile",
        }
        if (
            set(descriptor) != expected
            or descriptor.get("dedicated_workspace_profile") is not True
        ):
            raise WorkspaceAliasV1Denied("profile alias shape drift")
        try:
            spec = ProfileAliasSpecV1(
                browser=descriptor["browser"],  # type: ignore[arg-type]
                profile_id=descriptor["profile_id"],  # type: ignore[arg-type]
                allowed_domains=tuple(descriptor["allowed_domains"]),  # type: ignore[arg-type]
            )
        except (TypeError, WorkspaceAliasV1ContractError) as exc:
            raise WorkspaceAliasV1Denied("profile alias is invalid") from exc
        if list(spec.allowed_domains) != descriptor["allowed_domains"]:
            raise WorkspaceAliasV1Denied("profile domains are noncanonical")
        return descriptor
    expected = {
        "artifact_id",
        "sha256",
        "relative_path",
        "media_type",
        "artifact_schema_version",
        "artifact_created_at",
    }
    if set(descriptor) != expected:
        raise WorkspaceAliasV1Denied("artifact alias shape drift")
    try:
        ArtifactAliasSpecV1(
            artifact_id=descriptor["artifact_id"],  # type: ignore[arg-type]
            sha256=descriptor["sha256"],  # type: ignore[arg-type]
            relative_path=descriptor["relative_path"],  # type: ignore[arg-type]
            media_type=descriptor["media_type"],  # type: ignore[arg-type]
        )
    except (TypeError, WorkspaceAliasV1ContractError) as exc:
        raise WorkspaceAliasV1Denied("artifact alias is invalid") from exc
    if (
        type(descriptor["artifact_schema_version"]) is not int
        or descriptor["artifact_schema_version"] < 1
        or type(descriptor["artifact_created_at"]) is not str
        or not descriptor["artifact_created_at"]
    ):
        raise WorkspaceAliasV1Denied("artifact binding metadata is invalid")
    return descriptor


def _record_from_payload(
    payload: dict[str, object],
    *,
    row_alias_id: str,
    row_workspace_id: str,
    row_status: str,
    workspace_id: str,
    principal_id: str,
    key: bytes,
) -> WorkspaceAliasRecordV1:
    if set(payload) != _expected_payload_keys():
        raise WorkspaceAliasV1Denied("alias payload shape drift")
    kind = payload.get("kind")
    alias_name = payload.get("alias_name")
    if (
        payload.get("schema") != SCHEMA
        or payload.get("alias_id") != row_alias_id
        or payload.get("workspace_id") != row_workspace_id
        or row_workspace_id != workspace_id
        or payload.get("principal_id") != principal_id
        or type(kind) is not str
        or kind not in ALIAS_KINDS
        or type(alias_name) is not str
        or row_alias_id
        != workspace_alias_id_v1(
            workspace_id=workspace_id,
            principal_id=principal_id,
            kind=str(kind),
            alias_name=alias_name,
        )
        or payload.get("status") != row_status
        or row_status not in {"active", "revoked"}
        or payload.get("key_fingerprint_sha256")
        != hashlib.sha256(key).hexdigest()
        or type(payload.get("hmac_sha256")) is not str
        or not _HEX64.fullmatch(str(payload["hmac_sha256"]))
        or not hmac.compare_digest(
            str(payload["hmac_sha256"]),
            _payload_mac(payload, key),
        )
    ):
        raise WorkspaceAliasV1Denied("alias identity or authentication drift")
    descriptor = _validate_descriptor_shape(str(kind), payload["descriptor"])
    locator = payload.get("locator")
    if type(locator) is not str:
        raise WorkspaceAliasV1Denied("alias locator is invalid")
    if kind == "credential":
        service, account, expected_locator = credential_vault_locator_v1(
            workspace_id=workspace_id,
            provider=str(descriptor["provider"]),
            account_id=str(descriptor["account_id"]),
            tenant_id=(
                None
                if descriptor["tenant_id"] is None
                else str(descriptor["tenant_id"])
            ),
        )
        if (
            locator != expected_locator
            or descriptor["vault_service"] != service
            or descriptor["vault_account"] != account
        ):
            raise WorkspaceAliasV1Denied("credential locator drift")
    elif kind == "profile":
        expected_locator = browser_profile_locator_v1(
            workspace_id=workspace_id,
            browser=str(descriptor["browser"]),
            profile_id=str(descriptor["profile_id"]),
        )
        if locator != expected_locator:
            raise WorkspaceAliasV1Denied("profile locator drift")
    else:
        expected_locator = artifact_locator_v1(
            workspace_id=workspace_id,
            artifact_id=str(descriptor["artifact_id"]),
        )
        if locator != expected_locator:
            raise WorkspaceAliasV1Denied("artifact locator drift")
    try:
        return WorkspaceAliasRecordV1(
            alias_id=row_alias_id,
            workspace_id=workspace_id,
            principal_id=principal_id,
            kind=str(kind),
            alias_name=alias_name,
            locator=locator,
            status=row_status,
            created_at_ms=payload["created_at_ms"],  # type: ignore[arg-type]
            updated_at_ms=payload["updated_at_ms"],  # type: ignore[arg-type]
            revoked_at_ms=payload["revoked_at_ms"],  # type: ignore[arg-type]
            provider=(
                str(descriptor["provider"]) if kind == "credential" else None
            ),
            account_id=(
                str(descriptor["account_id"]) if kind == "credential" else None
            ),
            tenant_id=(
                descriptor["tenant_id"] if kind == "credential" else None
            ),  # type: ignore[arg-type]
            scopes=(
                tuple(descriptor["scopes"]) if kind == "credential" else ()
            ),  # type: ignore[arg-type]
            vault_service=(
                str(descriptor["vault_service"]) if kind == "credential" else None
            ),
            vault_account=(
                str(descriptor["vault_account"]) if kind == "credential" else None
            ),
            rotate_after_ms=(
                descriptor["rotate_after_ms"] if kind == "credential" else None
            ),  # type: ignore[arg-type]
            revoke_after_ms=(
                descriptor["revoke_after_ms"] if kind == "credential" else None
            ),  # type: ignore[arg-type]
            browser=(str(descriptor["browser"]) if kind == "profile" else None),
            profile_id=(
                str(descriptor["profile_id"]) if kind == "profile" else None
            ),
            allowed_domains=(
                tuple(descriptor["allowed_domains"]) if kind == "profile" else ()
            ),  # type: ignore[arg-type]
            artifact_id=(
                str(descriptor["artifact_id"]) if kind == "artifact" else None
            ),
            sha256=(str(descriptor["sha256"]) if kind == "artifact" else None),
            relative_path=(
                str(descriptor["relative_path"]) if kind == "artifact" else None
            ),
            media_type=(
                str(descriptor["media_type"]) if kind == "artifact" else None
            ),
            artifact_schema_version=(
                descriptor["artifact_schema_version"]
                if kind == "artifact"
                else None
            ),  # type: ignore[arg-type]
            artifact_created_at=(
                str(descriptor["artifact_created_at"])
                if kind == "artifact"
                else None
            ),
        )
    except (TypeError, WorkspaceAliasV1ContractError) as exc:
        raise WorkspaceAliasV1Denied("alias record is invalid") from exc


class WorkspaceAliasCatalogV1:
    """Sealed alias catalog bound to exactly one workspace and principal."""

    __slots__ = (
        "_registry",
        "_store",
        "_workspace",
        "_principal_id",
        "_integrity_key",
        "_key_fingerprint",
        "_connection_id",
        "_control_path",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        registry: WorkspaceRegistry,
        workspace_id: str,
        principal_id: str,
        integrity_key: bytes,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise WorkspaceAliasV1ContractError(
                "use create_workspace_alias_catalog_v1"
            )
        if type(registry) is not WorkspaceRegistry:
            raise WorkspaceAliasV1ContractError(
                "exact WorkspaceRegistry required"
            )
        if registry.enabled is not True or not registry.store.is_open:
            raise WorkspaceAliasV1Denied(
                "initialized enabled workspace registry required"
            )
        try:
            workspace = registry.require_active(
                _validate_workspace_id(workspace_id)
            )
        except WorkspaceError as exc:
            raise WorkspaceAliasV1Denied(
                "active workspace binding denied"
            ) from exc
        self._registry = registry
        self._store = registry.store
        self._workspace = workspace
        self._principal_id = _validate_principal_id(principal_id)
        self._integrity_key = _exact_key(integrity_key)
        self._key_fingerprint = hashlib.sha256(self._integrity_key).hexdigest()
        self._connection_id = id(self._store._require_connection())
        self._control_path = self._store.path.absolute()

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("WorkspaceAliasCatalogV1 cannot be subclassed")

    def __copy__(self) -> object:
        raise TypeError("WorkspaceAliasCatalogV1 cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("WorkspaceAliasCatalogV1 cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("WorkspaceAliasCatalogV1 cannot be serialized")

    @property
    def workspace_id(self) -> str:
        return self._workspace.workspace_id

    @property
    def principal_id(self) -> str:
        return self._principal_id

    @property
    def key_fingerprint_sha256(self) -> str:
        return self._key_fingerprint

    def _attest(self) -> sqlite3.Connection:
        if (
            type(self._registry) is not WorkspaceRegistry
            or type(self._store) is not ControlPlaneStore
            or self._registry.store is not self._store
            or self._registry.enabled is not True
            or not self._store.is_open
            or self._store.path.absolute() != self._control_path
            or hashlib.sha256(self._integrity_key).hexdigest()
            != self._key_fingerprint
        ):
            raise WorkspaceAliasV1Denied("alias catalog binding drift denied")
        connection = self._store._require_connection()
        if id(connection) != self._connection_id:
            raise WorkspaceAliasV1Denied(
                "control-plane connection drift denied"
            )
        try:
            workspace = self._registry.require_active(self.workspace_id)
        except WorkspaceError as exc:
            raise WorkspaceAliasV1Denied(
                "active workspace attestation denied"
            ) from exc
        if type(workspace) is not WorkspaceRecord or workspace != self._workspace:
            raise WorkspaceAliasV1Denied("workspace identity drift denied")
        return connection

    def _artifact_binding(
        self,
        connection: sqlite3.Connection,
        spec: ArtifactAliasSpecV1,
    ) -> dict[str, object]:
        try:
            rows = connection.execute(
                "SELECT workspace_id,schema_version,sha256,relative_path,"
                "media_type,status,created_at FROM artifact_index "
                "WHERE artifact_id=?",
                (spec.artifact_id,),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise WorkspaceAliasV1Denied(
                "artifact index lookup failed"
            ) from exc
        if len(rows) != 1:
            raise WorkspaceAliasV1Denied(
                "artifact alias requires one authoritative index row"
            )
        (
            workspace_id,
            schema_version,
            digest,
            relative_path,
            media_type,
            status,
            created_at,
        ) = tuple(rows[0])
        if (
            workspace_id != self.workspace_id
            or type(schema_version) is not int
            or schema_version < 1
            or digest != spec.sha256
            or relative_path != spec.relative_path
            or media_type != spec.media_type
            or status != "available"
            or type(created_at) is not str
            or not created_at
        ):
            raise WorkspaceAliasV1Denied(
                "artifact index binding or availability drift"
            )
        return {
            "artifact_id": spec.artifact_id,
            "sha256": spec.sha256,
            "relative_path": spec.relative_path,
            "media_type": spec.media_type,
            "artifact_schema_version": schema_version,
            "artifact_created_at": created_at,
        }

    def _reattest_artifact(
        self,
        connection: sqlite3.Connection,
        record: WorkspaceAliasRecordV1,
    ) -> None:
        if record.kind != "artifact":
            return
        assert (
            record.artifact_id is not None
            and record.sha256 is not None
            and record.relative_path is not None
            and record.media_type is not None
        )
        binding = self._artifact_binding(
            connection,
            ArtifactAliasSpecV1(
                artifact_id=record.artifact_id,
                sha256=record.sha256,
                relative_path=record.relative_path,
                media_type=record.media_type,
            ),
        )
        if (
            binding["artifact_schema_version"]
            != record.artifact_schema_version
            or binding["artifact_created_at"] != record.artifact_created_at
        ):
            raise WorkspaceAliasV1Denied(
                "artifact authoritative metadata drift"
            )

    def _row(
        self,
        connection: sqlite3.Connection,
        alias_id: str,
    ) -> tuple[object, ...] | None:
        try:
            row = connection.execute(
                "SELECT capability_id,workspace_id,schema_version,status,"
                "payload_json,created_at,updated_at FROM capability_descriptors "
                "WHERE capability_id=? AND workspace_id=?",
                (alias_id, self.workspace_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise WorkspaceAliasV1Denied("alias lookup failed") from exc
        return None if row is None else tuple(row)

    def _parse_row(
        self,
        row: tuple[object, ...],
    ) -> WorkspaceAliasRecordV1:
        (
            alias_id,
            workspace_id,
            schema_version,
            status,
            payload_json,
            _created_at,
            _updated_at,
        ) = row
        if (
            type(alias_id) is not str
            or not alias_id.startswith(CAPABILITY_PREFIX)
            or workspace_id != self.workspace_id
            or schema_version != SCHEMA_VERSION
            or status not in {"active", "revoked"}
            or type(payload_json) is not str
        ):
            raise WorkspaceAliasV1Denied("alias row contract drift")
        return _record_from_payload(
            _strict_json(payload_json),
            row_alias_id=alias_id,
            row_workspace_id=str(workspace_id),
            row_status=str(status),
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            key=self._integrity_key,
        )

    @staticmethod
    def _available(record: WorkspaceAliasRecordV1, *, now_ms: int) -> bool:
        if record.status != "active":
            return False
        return not (
            record.kind == "credential"
            and record.revoke_after_ms is not None
            and now_ms >= record.revoke_after_ms
        )

    def register(
        self,
        alias_name: str,
        spec: AliasSpecV1,
        *,
        now_ms: int,
    ) -> WorkspaceAliasRecordV1:
        name = _validate_alias_name(alias_name)
        if type(now_ms) is not int or now_ms < 0:
            raise WorkspaceAliasV1ContractError("now_ms is invalid")
        kind = _spec_kind(spec)
        if (
            kind == "credential"
            and (
                (
                    spec.rotate_after_ms is not None  # type: ignore[union-attr]
                    and spec.rotate_after_ms <= now_ms  # type: ignore[union-attr]
                )
                or (
                    spec.revoke_after_ms is not None  # type: ignore[union-attr]
                    and spec.revoke_after_ms <= now_ms  # type: ignore[union-attr]
                )
            )
        ):
            raise WorkspaceAliasV1ContractError(
                "credential lifecycle timestamp is not future-dated"
            )
        alias_id = workspace_alias_id_v1(
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            kind=kind,
            alias_name=name,
        )
        with _WRITE_LOCK:
            connection = self._attest()
            artifact_binding = (
                self._artifact_binding(connection, spec)
                if type(spec) is ArtifactAliasSpecV1
                else None
            )
            locator, descriptor = _descriptor_from_spec(
                spec,
                workspace_id=self.workspace_id,
                artifact_binding=artifact_binding,
            )
            existing_row = self._row(connection, alias_id)
            if existing_row is not None:
                existing = self._parse_row(existing_row)
                self._reattest_artifact(connection, existing)
                expected_locator, expected_descriptor = _descriptor_from_spec(
                    spec,
                    workspace_id=self.workspace_id,
                    artifact_binding=artifact_binding,
                )
                existing_payload = _strict_json(str(existing_row[4]))
                if existing.status == "revoked":
                    raise WorkspaceAliasV1Conflict(
                        "revoked alias identity cannot be resurrected"
                    )
                if (
                    existing.locator != expected_locator
                    or existing_payload["descriptor"] != expected_descriptor
                ):
                    raise WorkspaceAliasV1Conflict(
                        "alias identity already has different immutable content"
                    )
                return existing
            payload = _build_payload(
                alias_id=alias_id,
                workspace_id=self.workspace_id,
                principal_id=self.principal_id,
                kind=kind,
                alias_name=name,
                locator=locator,
                descriptor=descriptor,
                status="active",
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
                revoked_at_ms=None,
                key=self._integrity_key,
            )
            try:
                connection.execute("BEGIN IMMEDIATE")
                if type(spec) is ArtifactAliasSpecV1:
                    locked_binding = self._artifact_binding(connection, spec)
                    if locked_binding != artifact_binding:
                        raise WorkspaceAliasV1Denied(
                            "artifact binding changed before alias publication"
                        )
                connection.execute(
                    "INSERT INTO capability_descriptors("
                    "capability_id,workspace_id,schema_version,status,"
                    "payload_json,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?)",
                    (
                        alias_id,
                        self.workspace_id,
                        SCHEMA_VERSION,
                        "active",
                        _canonical(payload).decode("utf-8"),
                        _iso_from_ms(now_ms),
                        _iso_from_ms(now_ms),
                    ),
                )
                connection.execute("COMMIT")
            except WorkspaceAliasV1Denied:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise WorkspaceAliasV1Conflict(
                    "alias identity was concurrently claimed"
                ) from exc
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise WorkspaceAliasV1Error("alias write failed") from exc
            row = self._row(connection, alias_id)
            if row is None:
                raise WorkspaceAliasV1Denied("alias write read-back failed")
            record = self._parse_row(row)
            self._reattest_artifact(connection, record)
            self._attest()
            return record

    def get(
        self,
        *,
        kind: str,
        alias_name: str,
        now_ms: int,
        include_revoked: bool = False,
    ) -> WorkspaceAliasRecordV1:
        if kind not in ALIAS_KINDS:
            raise WorkspaceAliasV1ContractError("alias kind is invalid")
        name = _validate_alias_name(alias_name)
        if type(now_ms) is not int or now_ms < 0:
            raise WorkspaceAliasV1ContractError("now_ms is invalid")
        if type(include_revoked) is not bool:
            raise WorkspaceAliasV1ContractError(
                "include_revoked must be exact bool"
            )
        connection = self._attest()
        alias_id = workspace_alias_id_v1(
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            kind=kind,
            alias_name=name,
        )
        row = self._row(connection, alias_id)
        if row is None:
            raise WorkspaceAliasV1Denied("alias is unavailable")
        record = self._parse_row(row)
        if not include_revoked and not self._available(record, now_ms=now_ms):
            raise WorkspaceAliasV1Denied("alias is revoked or expired")
        self._reattest_artifact(connection, record)
        self._attest()
        return record

    def list(
        self,
        *,
        now_ms: int,
        kind: str | None = None,
        include_revoked: bool = False,
    ) -> tuple[WorkspaceAliasRecordV1, ...]:
        if type(now_ms) is not int or now_ms < 0:
            raise WorkspaceAliasV1ContractError("now_ms is invalid")
        if kind is not None and kind not in ALIAS_KINDS:
            raise WorkspaceAliasV1ContractError("alias kind is invalid")
        if type(include_revoked) is not bool:
            raise WorkspaceAliasV1ContractError(
                "include_revoked must be exact bool"
            )
        connection = self._attest()
        try:
            rows = connection.execute(
                "SELECT capability_id,workspace_id,schema_version,status,"
                "payload_json,created_at,updated_at FROM capability_descriptors "
                "WHERE workspace_id=? AND capability_id LIKE ? "
                "ORDER BY capability_id LIMIT ?",
                (self.workspace_id, f"{CAPABILITY_PREFIX}%", MAX_ALIASES + 1),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise WorkspaceAliasV1Denied("alias list failed") from exc
        if len(rows) > MAX_ALIASES:
            raise WorkspaceAliasV1Denied("workspace alias bound exceeded")
        records: list[WorkspaceAliasRecordV1] = []
        for raw in rows:
            row = tuple(raw)
            try:
                record = self._parse_row(row)
            except WorkspaceAliasV1Denied:
                payload = _strict_json(str(row[4]))
                if payload.get("principal_id") != self.principal_id:
                    continue
                raise
            if kind is not None and record.kind != kind:
                continue
            if not include_revoked and not self._available(record, now_ms=now_ms):
                continue
            self._reattest_artifact(connection, record)
            records.append(record)
        records.sort(key=lambda item: (item.kind, item.alias_name, item.alias_id))
        self._attest()
        return tuple(records)

    def revoke(
        self,
        *,
        kind: str,
        alias_name: str,
        now_ms: int,
    ) -> WorkspaceAliasRecordV1:
        if kind not in ALIAS_KINDS:
            raise WorkspaceAliasV1ContractError("alias kind is invalid")
        name = _validate_alias_name(alias_name)
        if type(now_ms) is not int or now_ms < 0:
            raise WorkspaceAliasV1ContractError("now_ms is invalid")
        alias_id = workspace_alias_id_v1(
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            kind=kind,
            alias_name=name,
        )
        with _WRITE_LOCK:
            connection = self._attest()
            row = self._row(connection, alias_id)
            if row is None:
                raise WorkspaceAliasV1Denied("alias is unavailable")
            record = self._parse_row(row)
            if record.status == "revoked":
                return record
            if now_ms < record.created_at_ms:
                raise WorkspaceAliasV1ContractError(
                    "revocation precedes alias creation"
                )
            payload = _strict_json(str(row[4]))
            payload["status"] = "revoked"
            payload["updated_at_ms"] = now_ms
            payload["revoked_at_ms"] = now_ms
            payload["hmac_sha256"] = _payload_mac(payload, self._integrity_key)
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE capability_descriptors SET status=?,payload_json=?,"
                    "updated_at=? WHERE capability_id=? AND workspace_id=? "
                    "AND status='active'",
                    (
                        "revoked",
                        _canonical(payload).decode("utf-8"),
                        _iso_from_ms(now_ms),
                        alias_id,
                        self.workspace_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise WorkspaceAliasV1Conflict(
                        "alias lifecycle changed concurrently"
                    )
                connection.execute("COMMIT")
            except WorkspaceAliasV1Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise WorkspaceAliasV1Error("alias revocation failed") from exc
            updated = self._row(connection, alias_id)
            if updated is None:
                raise WorkspaceAliasV1Denied("revocation read-back failed")
            revoked = self._parse_row(updated)
            self._attest()
            return revoked


def create_workspace_alias_catalog_v1(
    *,
    gate: WorkspaceAliasFeatureGateV1 | None = None,
    registry: WorkspaceRegistry | None = None,
    workspace_id: str | None = None,
    principal_id: str | None = None,
    integrity_key: bytes | None = None,
    project_root: Path | str | None = None,
) -> WorkspaceAliasCatalogV1 | None:
    """Construct the catalog only behind the exact accepted Phase 7 entry."""

    selected = (
        WorkspaceAliasFeatureGateV1.from_environ() if gate is None else gate
    )
    if type(selected) is not WorkspaceAliasFeatureGateV1:
        raise WorkspaceAliasV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_workspace_memory_entry(
        Path(__file__).resolve().parents[1]
        if project_root is None
        else project_root
    )
    if (
        registry is None
        or workspace_id is None
        or principal_id is None
        or integrity_key is None
    ):
        raise WorkspaceAliasV1ContractError(
            "enabled catalog requires complete host bindings"
        )
    return WorkspaceAliasCatalogV1(
        construction_key=_CONSTRUCTION_KEY,
        registry=registry,
        workspace_id=workspace_id,
        principal_id=principal_id,
        integrity_key=integrity_key,
    )


__all__ = [
    "ALIAS_KINDS",
    "CAPABILITY_PREFIX",
    "ENABLED_VALUE",
    "FEATURE_FLAG",
    "MAX_ALIASES",
    "MAX_DOMAINS",
    "MAX_PAYLOAD_BYTES",
    "MAX_SCOPES",
    "SCHEMA",
    "SCHEMA_VERSION",
    "SUPPORTED_BROWSERS",
    "WORKSPACE_MEMORY_ENTRY_ROOTS",
    "ArtifactAliasSpecV1",
    "CredentialAliasSpecV1",
    "ProfileAliasSpecV1",
    "WorkspaceAliasCatalogV1",
    "WorkspaceAliasFeatureGateV1",
    "WorkspaceAliasRecordV1",
    "WorkspaceAliasV1Conflict",
    "WorkspaceAliasV1ContractError",
    "WorkspaceAliasV1Denied",
    "WorkspaceAliasV1Error",
    "artifact_locator_v1",
    "browser_profile_locator_v1",
    "create_workspace_alias_catalog_v1",
    "credential_vault_locator_v1",
    "workspace_alias_id_v1",
]
