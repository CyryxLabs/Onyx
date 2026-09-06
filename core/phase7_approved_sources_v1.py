"""Approved-source registry for the Phase 7 Company Graph.

Sources are signed workspace/principal policy records.  The registry never
fetches a URL, opens an artifact, interprets source instructions, or grants
source content authority over Onyx.
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
from pathlib import Path
from typing import Final
from urllib.parse import SplitResult, urlsplit, urlunsplit

from core.control_plane import ControlPlaneStore
from core.phase7_workspace_aliases_v1 import (
    WorkspaceAliasCatalogV1,
    WorkspaceAliasRecordV1,
)
from core.workspaces import (
    LEGACY_WORKSPACE_ID,
    WorkspaceError,
    WorkspaceRecord,
    WorkspaceRegistry,
)
from memory.store import contains_secret


FEATURE_FLAG: Final = "ONYX_PHASE7_APPROVED_SOURCES_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxApprovedSource.v1"
SCHEMA_VERSION: Final = 1
CAPABILITY_PREFIX: Final = "approved-source-v1-"
MAX_SOURCES: Final = 5_000
MAX_PAYLOAD_BYTES: Final = 48 * 1024
SOURCE_KINDS: Final = frozenset(
    {
        "analytics",
        "brand_system",
        "company_governance",
        "company_strategy",
        "customer_research",
        "decision_record",
        "issue",
        "meeting_note",
        "product_artifact",
        "pull_request",
        "release",
        "repository",
        "roadmap",
        "sales_pipeline",
        "task_system",
        "technical_specification",
        "test_report",
    }
)
AUTHORITIES: Final = frozenset(
    {"authoritative_primary", "official", "corroborating", "secondary"}
)
RIGHTS: Final = frozenset(
    {
        "internal_authorized",
        "licensed",
        "open_license",
        "owner_created",
        "public_domain",
        "public_metadata",
        "user_owned",
    }
)
SENSITIVITIES: Final = frozenset({"public", "internal", "confidential"})
LOCATOR_KINDS: Final = frozenset({"artifact_alias", "https"})
SCORE_FIELDS: Final = (
    "expertise_bp",
    "primary_evidence_bp",
    "editorial_quality_bp",
    "recency_bp",
    "correction_history_bp",
    "incentive_independence_bp",
    "corroboration_bp",
    "relevance_bp",
)
ALIASES_ENTRY_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase7-workspace-aliases-v1/manifest.json",
        "ec1938f4b1671187ed8384f104bb6082b0bd75d157cf4c8f12e259beb5612ca4",
    ),
    (
        "docs/onyx/acceptance/VE-P7-WORKSPACE-ALIASES-V1-E6-001.md",
        "27b61a9ef3351728f0811af6d86a83d4a8dfa80e00640b0ac847bce9917e22cf",
    ),
    (
        "docs/onyx/acceptance/VE-P7-WORKSPACE-ALIASES-V1-E6-001.manifest.json",
        "98ca596125e43dec17424d06d6716528e319cd129cc5a7737372626c89a5343c",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P7-WORKSPACE-ALIASES-V1-E6-001.sha256",
        "5f80d972ac6d8c4eef521a7015a027cbe81d61833d4c27b4868bf7c659b01d41",
    ),
)

_WORKSPACE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_PRINCIPAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_SOURCE_NAME = re.compile(r"^[a-z][a-z0-9-]{2,79}$")
_DIVERSITY_GROUP = re.compile(r"^[a-z][a-z0-9.-]{1,79}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CONSTRUCTION_KEY = object()
_WRITE_LOCK = threading.RLock()


class ApprovedSourceV1Error(RuntimeError):
    """Base approved-source registry error."""


class ApprovedSourceV1ContractError(ValueError):
    """Caller input violated the approved-source contract."""


class ApprovedSourceV1Denied(PermissionError):
    """Scope, lifecycle, policy, or integrity denied source use."""


class ApprovedSourceV1Conflict(ApprovedSourceV1Error):
    """An immutable source identity already has different content."""


@dataclass(frozen=True, slots=True)
class ApprovedSourceFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ApprovedSourceV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls,
        environ: dict[str, str] | os._Environ[str] | None = None,
    ) -> "ApprovedSourceFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class SourceScoresV1:
    expertise_bp: int
    primary_evidence_bp: int
    editorial_quality_bp: int
    recency_bp: int
    correction_history_bp: int
    incentive_independence_bp: int
    corroboration_bp: int
    relevance_bp: int

    def __post_init__(self) -> None:
        if any(
            type(getattr(self, field)) is not int
            or not 0 <= getattr(self, field) <= 10_000
            for field in SCORE_FIELDS
        ):
            raise ApprovedSourceV1ContractError(
                "source scores must be exact basis points"
            )

    @property
    def credibility_bp(self) -> int:
        return sum(getattr(self, field) for field in SCORE_FIELDS) // len(
            SCORE_FIELDS
        )

    def payload(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in SCORE_FIELDS}


@dataclass(frozen=True, slots=True)
class ApprovedSourceSpecV1:
    source_kind: str
    authority: str
    rights: str
    sensitivity: str
    locator_kind: str
    locator: str
    citation: str
    diversity_group: str
    scores: SourceScoresV1
    valid_from_ms: int
    valid_until_ms: int | None
    fresh_until_ms: int
    artifact_alias_name: str | None = None

    def __post_init__(self) -> None:
        if self.source_kind not in SOURCE_KINDS:
            raise ApprovedSourceV1ContractError("source_kind is invalid")
        if self.authority not in AUTHORITIES:
            raise ApprovedSourceV1ContractError("authority is invalid")
        if self.rights not in RIGHTS:
            raise ApprovedSourceV1ContractError("rights is invalid")
        if self.sensitivity not in SENSITIVITIES:
            raise ApprovedSourceV1ContractError("sensitivity is invalid")
        if self.locator_kind not in LOCATOR_KINDS:
            raise ApprovedSourceV1ContractError("locator_kind is invalid")
        _safe_text("locator", self.locator, 2_048)
        _safe_text("citation", self.citation, 2_048)
        _identifier("diversity_group", self.diversity_group, _DIVERSITY_GROUP)
        if type(self.scores) is not SourceScoresV1:
            raise ApprovedSourceV1ContractError("exact source scores required")
        _timestamp("valid_from_ms", self.valid_from_ms)
        _optional_timestamp("valid_until_ms", self.valid_until_ms)
        _timestamp("fresh_until_ms", self.fresh_until_ms)
        if self.fresh_until_ms < self.valid_from_ms:
            raise ApprovedSourceV1ContractError(
                "freshness cannot precede validity"
            )
        if (
            self.valid_until_ms is not None
            and (
                self.valid_until_ms <= self.valid_from_ms
                or self.fresh_until_ms > self.valid_until_ms
            )
        ):
            raise ApprovedSourceV1ContractError(
                "source validity window is invalid"
            )
        if self.locator_kind == "https":
            canonical = canonical_https_locator_v1(self.locator)
            if canonical != self.locator or self.citation != canonical:
                raise ApprovedSourceV1ContractError(
                    "HTTPS locator/citation must be canonical and identical"
                )
            if self.artifact_alias_name is not None:
                raise ApprovedSourceV1ContractError(
                    "HTTPS source cannot carry an artifact alias"
                )
        else:
            if (
                self.artifact_alias_name is None
                or not _SOURCE_NAME.fullmatch(self.artifact_alias_name)
                or self.locator != self.citation
                or not self.locator.startswith("onyx-artifact://v1/")
            ):
                raise ApprovedSourceV1ContractError(
                    "artifact source locator is invalid"
                )


@dataclass(frozen=True, slots=True)
class ApprovedSourceRecordV1:
    source_id: str
    source_name: str
    workspace_id: str
    principal_id: str
    source_kind: str
    authority: str
    rights: str
    sensitivity: str
    locator_kind: str
    locator: str
    citation: str
    diversity_group: str
    scores: SourceScoresV1
    credibility_bp: int
    source_identity_sha256: str
    valid_from_ms: int
    valid_until_ms: int | None
    fresh_until_ms: int
    artifact_alias_name: str | None
    artifact_id: str | None
    artifact_sha256: str | None
    status: str
    created_at_ms: int
    updated_at_ms: int
    revoked_at_ms: int | None
    content_trust: str
    instructions_authority: bool

    def __post_init__(self) -> None:
        if (
            not self.source_id.startswith(CAPABILITY_PREFIX)
            or not _SOURCE_NAME.fullmatch(self.source_name)
            or not _WORKSPACE_ID.fullmatch(self.workspace_id)
            or self.workspace_id == LEGACY_WORKSPACE_ID
            or not _PRINCIPAL_ID.fullmatch(self.principal_id)
            or self.status not in {"approved", "revoked"}
            or self.credibility_bp != self.scores.credibility_bp
            or not _HEX64.fullmatch(self.source_identity_sha256)
            or self.content_trust != "untrusted_data"
            or self.instructions_authority is not False
            or type(self.created_at_ms) is not int
            or type(self.updated_at_ms) is not int
            or self.updated_at_ms < self.created_at_ms
            or (
                self.status == "approved" and self.revoked_at_ms is not None
            )
            or (
                self.status == "revoked"
                and (
                    type(self.revoked_at_ms) is not int
                    or self.revoked_at_ms < self.created_at_ms
                )
            )
        ):
            raise ApprovedSourceV1ContractError("source record contract drift")

    @property
    def access_license_note(self) -> str:
        return f"rights:{self.rights}"


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
        raise ApprovedSourceV1ContractError(
            "value is not canonical JSON"
        ) from exc


def _exact_key(value: bytes) -> bytes:
    if type(value) is not bytes or not 32 <= len(value) <= 64 or not any(value):
        raise ApprovedSourceV1ContractError(
            "integrity key must be 32-64 non-zero bytes"
        )
    return value


def _safe_text(label: str, value: str, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 32 for character in value)
        or contains_secret(value)
    ):
        raise ApprovedSourceV1ContractError(
            f"{label} contains unsafe or secret-like material"
        )
    return value


def _identifier(
    label: str,
    value: str,
    pattern: re.Pattern[str],
) -> str:
    _safe_text(label, value, 160)
    if not pattern.fullmatch(value):
        raise ApprovedSourceV1ContractError(f"{label} is invalid")
    return value


def _workspace_id(value: str) -> str:
    if (
        type(value) is not str
        or not _WORKSPACE_ID.fullmatch(value)
        or value == LEGACY_WORKSPACE_ID
    ):
        raise ApprovedSourceV1ContractError(
            "explicit non-legacy workspace_id required"
        )
    return value


def _principal_id(value: str) -> str:
    return _identifier("principal_id", value, _PRINCIPAL_ID)


def _source_name(value: str) -> str:
    return _identifier("source_name", value, _SOURCE_NAME)


def _timestamp(label: str, value: int) -> int:
    if type(value) is not int or value < 0:
        raise ApprovedSourceV1ContractError(f"{label} is invalid")
    return value


def _optional_timestamp(label: str, value: int | None) -> int | None:
    if value is not None:
        _timestamp(label, value)
    return value


def canonical_https_locator_v1(value: str) -> str:
    _safe_text("HTTPS locator", value, 2_048)
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ApprovedSourceV1ContractError("HTTPS locator is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise ApprovedSourceV1ContractError("HTTPS locator is invalid")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ApprovedSourceV1ContractError("HTTPS host is invalid") from exc
    if (
        len(host) > 253
        or "." not in host
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not re.fullmatch(r"[a-z0-9-]+", label)
            for label in host.split(".")
        )
    ):
        raise ApprovedSourceV1ContractError("HTTPS host is invalid")
    port = ":443" if parsed.port == 443 else ""
    path = parsed.path or "/"
    canonical = urlunsplit(
        SplitResult("https", host + port, path, parsed.query, "")
    )
    if canonical != value:
        raise ApprovedSourceV1ContractError(
            "HTTPS locator must already be canonical"
        )
    return canonical


def domain_material_sha256_v1(value: str) -> str:
    """Match DomainLedgerRepository's framed text identity."""

    _safe_text("domain material", value, 8_192)
    return hashlib.sha256(b"m2a:text\0" + value.encode("utf-8")).hexdigest()


def approved_source_id_v1(
    *,
    workspace_id: str,
    principal_id: str,
    source_name: str,
) -> str:
    digest = hashlib.sha256(
        _canonical(
            [
                SCHEMA,
                _workspace_id(workspace_id),
                _principal_id(principal_id),
                _source_name(source_name),
            ]
        )
    ).hexdigest()
    return CAPABILITY_PREFIX + digest


def _is_reparse(info: os.stat_result) -> bool:
    return bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _strict_json(text: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ApprovedSourceV1Denied(f"duplicate source key: {key}")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise ApprovedSourceV1Denied("source payload has a non-finite number")

    if type(text) is not str or len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ApprovedSourceV1Denied("source payload is invalid")
    try:
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (TypeError, json.JSONDecodeError) as exc:
        raise ApprovedSourceV1Denied("source payload is invalid") from exc
    if type(value) is not dict:
        raise ApprovedSourceV1Denied("source payload must be an object")
    return value


def _verify_aliases_entry(project_root: Path | str) -> None:
    try:
        lexical_root = Path(project_root).absolute()
        root_info = os.lstat(lexical_root)
        root = lexical_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ApprovedSourceV1Denied("aliases entry root is unavailable") from exc
    if (
        root != lexical_root
        or not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or _is_reparse(root_info)
    ):
        raise ApprovedSourceV1Denied("aliases entry root is not canonical")
    payloads: dict[str, bytes] = {}
    for relative, expected in ALIASES_ENTRY_ROOTS:
        value = Path(relative)
        if value.is_absolute() or ".." in value.parts:
            raise ApprovedSourceV1Denied("aliases entry path is unsafe")
        path = root.joinpath(*value.parts)
        try:
            info = os.lstat(path)
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            payload = resolved.read_bytes()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ApprovedSourceV1Denied(
                "aliases entry evidence is unavailable"
            ) from exc
        if (
            resolved != path.absolute()
            or not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or _is_reparse(info)
            or hashlib.sha256(payload).hexdigest() != expected
        ):
            raise ApprovedSourceV1Denied("aliases entry evidence drift denied")
        payloads[relative] = payload
    metadata_path = (
        "docs/onyx/acceptance/"
        "VE-P7-WORKSPACE-ALIASES-V1-E6-001.manifest.json"
    )
    try:
        metadata = _strict_json(payloads[metadata_path].decode("utf-8"))
    except UnicodeError as exc:
        raise ApprovedSourceV1Denied(
            "aliases acceptance is not UTF-8"
        ) from exc
    claims = metadata.get("claims")
    if (
        metadata.get("acceptance_id")
        != "VE-P7-WORKSPACE-ALIASES-V1-E6-001"
        or metadata.get("decision") != "accepted"
        or metadata.get("findings")
        != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or type(claims) is not dict
        or claims.get("workspace_aliases_v1_accepted") is not True
        or claims.get("secret_storage") is not False
        or claims.get("secret_resolution") is not False
        or claims.get("runtime_authority_added") is not False
        or claims.get("phase7_exit") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise ApprovedSourceV1Denied(
            "aliases acceptance contract drift"
        )


def _payload_mac(payload: dict[str, object], key: bytes) -> str:
    unsigned = {
        name: value for name, value in payload.items() if name != "hmac_sha256"
    }
    return hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()


def _expected_payload_keys() -> set[str]:
    return {
        "schema",
        "source_id",
        "source_name",
        "workspace_id",
        "principal_id",
        "source_kind",
        "authority",
        "rights",
        "sensitivity",
        "locator_kind",
        "locator",
        "citation",
        "diversity_group",
        "scores",
        "credibility_bp",
        "source_identity_sha256",
        "valid_from_ms",
        "valid_until_ms",
        "fresh_until_ms",
        "artifact_alias_name",
        "artifact_id",
        "artifact_sha256",
        "status",
        "created_at_ms",
        "updated_at_ms",
        "revoked_at_ms",
        "content_trust",
        "instructions_authority",
        "key_fingerprint_sha256",
        "hmac_sha256",
    }


def _record_from_payload(
    payload: dict[str, object],
    *,
    row_source_id: str,
    row_workspace_id: str,
    row_status: str,
    workspace_id: str,
    principal_id: str,
    key: bytes,
) -> ApprovedSourceRecordV1:
    if set(payload) != _expected_payload_keys():
        raise ApprovedSourceV1Denied("source payload shape drift")
    source_name = payload.get("source_name")
    scores_value = payload.get("scores")
    if type(scores_value) is not dict or set(scores_value) != set(SCORE_FIELDS):
        raise ApprovedSourceV1Denied("source scores shape drift")
    try:
        scores = SourceScoresV1(
            **{field: scores_value[field] for field in SCORE_FIELDS}
        )
    except (TypeError, ApprovedSourceV1ContractError) as exc:
        raise ApprovedSourceV1Denied("source scores are invalid") from exc
    if (
        payload.get("schema") != SCHEMA
        or payload.get("source_id") != row_source_id
        or payload.get("workspace_id") != row_workspace_id
        or row_workspace_id != workspace_id
        or payload.get("principal_id") != principal_id
        or type(source_name) is not str
        or row_source_id
        != approved_source_id_v1(
            workspace_id=workspace_id,
            principal_id=principal_id,
            source_name=source_name,
        )
        or payload.get("status") != row_status
        or row_status not in {"approved", "revoked"}
        or payload.get("credibility_bp") != scores.credibility_bp
        or payload.get("source_identity_sha256")
        != domain_material_sha256_v1(str(payload.get("locator")))
        or payload.get("content_trust") != "untrusted_data"
        or payload.get("instructions_authority") is not False
        or payload.get("key_fingerprint_sha256")
        != hashlib.sha256(key).hexdigest()
        or type(payload.get("hmac_sha256")) is not str
        or not _HEX64.fullmatch(str(payload["hmac_sha256"]))
        or not hmac.compare_digest(
            str(payload["hmac_sha256"]),
            _payload_mac(payload, key),
        )
    ):
        raise ApprovedSourceV1Denied(
            "source identity or authentication drift"
        )
    try:
        record = ApprovedSourceRecordV1(
            source_id=row_source_id,
            source_name=source_name,
            workspace_id=workspace_id,
            principal_id=principal_id,
            source_kind=payload["source_kind"],  # type: ignore[arg-type]
            authority=payload["authority"],  # type: ignore[arg-type]
            rights=payload["rights"],  # type: ignore[arg-type]
            sensitivity=payload["sensitivity"],  # type: ignore[arg-type]
            locator_kind=payload["locator_kind"],  # type: ignore[arg-type]
            locator=payload["locator"],  # type: ignore[arg-type]
            citation=payload["citation"],  # type: ignore[arg-type]
            diversity_group=payload["diversity_group"],  # type: ignore[arg-type]
            scores=scores,
            credibility_bp=payload["credibility_bp"],  # type: ignore[arg-type]
            source_identity_sha256=payload["source_identity_sha256"],  # type: ignore[arg-type]
            valid_from_ms=payload["valid_from_ms"],  # type: ignore[arg-type]
            valid_until_ms=payload["valid_until_ms"],  # type: ignore[arg-type]
            fresh_until_ms=payload["fresh_until_ms"],  # type: ignore[arg-type]
            artifact_alias_name=payload["artifact_alias_name"],  # type: ignore[arg-type]
            artifact_id=payload["artifact_id"],  # type: ignore[arg-type]
            artifact_sha256=payload["artifact_sha256"],  # type: ignore[arg-type]
            status=row_status,
            created_at_ms=payload["created_at_ms"],  # type: ignore[arg-type]
            updated_at_ms=payload["updated_at_ms"],  # type: ignore[arg-type]
            revoked_at_ms=payload["revoked_at_ms"],  # type: ignore[arg-type]
            content_trust=payload["content_trust"],  # type: ignore[arg-type]
            instructions_authority=payload["instructions_authority"],  # type: ignore[arg-type]
        )
        ApprovedSourceSpecV1(
            source_kind=record.source_kind,
            authority=record.authority,
            rights=record.rights,
            sensitivity=record.sensitivity,
            locator_kind=record.locator_kind,
            locator=record.locator,
            citation=record.citation,
            diversity_group=record.diversity_group,
            scores=record.scores,
            valid_from_ms=record.valid_from_ms,
            valid_until_ms=record.valid_until_ms,
            fresh_until_ms=record.fresh_until_ms,
            artifact_alias_name=record.artifact_alias_name,
        )
    except (TypeError, ApprovedSourceV1ContractError) as exc:
        raise ApprovedSourceV1Denied("source record is invalid") from exc
    if record.locator_kind == "artifact_alias":
        if (
            type(record.artifact_id) is not str
            or type(record.artifact_sha256) is not str
            or not _HEX64.fullmatch(record.artifact_sha256)
        ):
            raise ApprovedSourceV1Denied("artifact source binding is invalid")
    elif (
        record.artifact_alias_name is not None
        or record.artifact_id is not None
        or record.artifact_sha256 is not None
    ):
        raise ApprovedSourceV1Denied("HTTPS source carries artifact metadata")
    return record


class ApprovedSourceRegistryV1:
    """Sealed source policy registry for one workspace and principal."""

    __slots__ = (
        "_registry",
        "_store",
        "_aliases",
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
        aliases: WorkspaceAliasCatalogV1,
        workspace_id: str,
        principal_id: str,
        integrity_key: bytes,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise ApprovedSourceV1ContractError(
                "use create_approved_source_registry_v1"
            )
        if (
            type(registry) is not WorkspaceRegistry
            or type(aliases) is not WorkspaceAliasCatalogV1
        ):
            raise ApprovedSourceV1ContractError(
                "exact workspace registry and alias catalog required"
            )
        if registry.enabled is not True or not registry.store.is_open:
            raise ApprovedSourceV1Denied(
                "initialized enabled workspace registry required"
            )
        workspace = _workspace_id(workspace_id)
        principal = _principal_id(principal_id)
        key = _exact_key(integrity_key)
        try:
            record = registry.require_active(workspace)
        except WorkspaceError as exc:
            raise ApprovedSourceV1Denied(
                "active workspace binding denied"
            ) from exc
        if (
            aliases.workspace_id != workspace
            or aliases.principal_id != principal
            or aliases.key_fingerprint_sha256
            != hashlib.sha256(key).hexdigest()
        ):
            raise ApprovedSourceV1Denied("alias catalog binding denied")
        self._registry = registry
        self._store = registry.store
        self._aliases = aliases
        self._workspace = record
        self._principal_id = principal
        self._integrity_key = key
        self._key_fingerprint = hashlib.sha256(key).hexdigest()
        self._connection_id = id(self._store._require_connection())
        self._control_path = self._store.path.absolute()

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("ApprovedSourceRegistryV1 cannot be subclassed")

    def __copy__(self) -> object:
        raise TypeError("ApprovedSourceRegistryV1 cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("ApprovedSourceRegistryV1 cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("ApprovedSourceRegistryV1 cannot be serialized")

    @property
    def workspace_id(self) -> str:
        return self._workspace.workspace_id

    @property
    def principal_id(self) -> str:
        return self._principal_id

    @property
    def key_fingerprint_sha256(self) -> str:
        return self._key_fingerprint

    @property
    def registry(self) -> WorkspaceRegistry:
        return self._registry

    def _attest(self) -> sqlite3.Connection:
        if (
            type(self._registry) is not WorkspaceRegistry
            or type(self._store) is not ControlPlaneStore
            or type(self._aliases) is not WorkspaceAliasCatalogV1
            or self._registry.store is not self._store
            or self._registry.enabled is not True
            or not self._store.is_open
            or self._store.path.absolute() != self._control_path
            or self._aliases.workspace_id != self.workspace_id
            or self._aliases.principal_id != self.principal_id
            or self._aliases.key_fingerprint_sha256 != self._key_fingerprint
            or hashlib.sha256(self._integrity_key).hexdigest()
            != self._key_fingerprint
        ):
            raise ApprovedSourceV1Denied("source registry binding drift denied")
        connection = self._store._require_connection()
        if id(connection) != self._connection_id:
            raise ApprovedSourceV1Denied(
                "control-plane connection drift denied"
            )
        try:
            current = self._registry.require_active(self.workspace_id)
        except WorkspaceError as exc:
            raise ApprovedSourceV1Denied(
                "active workspace attestation denied"
            ) from exc
        if type(current) is not WorkspaceRecord or current != self._workspace:
            raise ApprovedSourceV1Denied("workspace identity drift denied")
        return connection

    def _artifact_binding(
        self,
        spec: ApprovedSourceSpecV1,
        *,
        now_ms: int,
    ) -> WorkspaceAliasRecordV1 | None:
        if spec.locator_kind != "artifact_alias":
            return None
        assert spec.artifact_alias_name is not None
        try:
            record = self._aliases.get(
                kind="artifact",
                alias_name=spec.artifact_alias_name,
                now_ms=now_ms,
            )
        except Exception as exc:
            raise ApprovedSourceV1Denied(
                "approved source artifact alias is unavailable"
            ) from exc
        if record.locator != spec.locator:
            raise ApprovedSourceV1Denied(
                "approved source artifact locator drift"
            )
        return record

    def _row(
        self,
        connection: sqlite3.Connection,
        source_id: str,
    ) -> tuple[object, ...] | None:
        try:
            row = connection.execute(
                "SELECT capability_id,workspace_id,schema_version,status,"
                "payload_json,created_at,updated_at FROM capability_descriptors "
                "WHERE capability_id=? AND workspace_id=?",
                (source_id, self.workspace_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise ApprovedSourceV1Denied("source lookup failed") from exc
        return None if row is None else tuple(row)

    def _parse_row(
        self,
        row: tuple[object, ...],
    ) -> ApprovedSourceRecordV1:
        (
            source_id,
            workspace_id,
            schema_version,
            status,
            payload_json,
            _created_at,
            _updated_at,
        ) = row
        if (
            type(source_id) is not str
            or not source_id.startswith(CAPABILITY_PREFIX)
            or workspace_id != self.workspace_id
            or schema_version != SCHEMA_VERSION
            or status not in {"approved", "revoked"}
            or type(payload_json) is not str
        ):
            raise ApprovedSourceV1Denied("source row contract drift")
        return _record_from_payload(
            _strict_json(payload_json),
            row_source_id=source_id,
            row_workspace_id=str(workspace_id),
            row_status=str(status),
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            key=self._integrity_key,
        )

    @staticmethod
    def _available(
        record: ApprovedSourceRecordV1,
        *,
        now_ms: int,
        require_fresh: bool,
    ) -> bool:
        return (
            record.status == "approved"
            and now_ms >= record.valid_from_ms
            and (
                record.valid_until_ms is None
                or now_ms < record.valid_until_ms
            )
            and (not require_fresh or now_ms <= record.fresh_until_ms)
        )

    def register(
        self,
        source_name: str,
        spec: ApprovedSourceSpecV1,
        *,
        now_ms: int,
    ) -> ApprovedSourceRecordV1:
        name = _source_name(source_name)
        if type(spec) is not ApprovedSourceSpecV1:
            raise ApprovedSourceV1ContractError(
                "exact approved source spec required"
            )
        _timestamp("now_ms", now_ms)
        if now_ms < spec.valid_from_ms or (
            spec.valid_until_ms is not None and now_ms >= spec.valid_until_ms
        ):
            raise ApprovedSourceV1ContractError(
                "source is outside its validity window"
            )
        source_id = approved_source_id_v1(
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            source_name=name,
        )
        with _WRITE_LOCK:
            connection = self._attest()
            artifact = self._artifact_binding(spec, now_ms=now_ms)
            existing = self._row(connection, source_id)
            if existing is not None:
                record = self._parse_row(existing)
                if record.status == "revoked":
                    raise ApprovedSourceV1Conflict(
                        "revoked source identity cannot be resurrected"
                    )
                expected_artifact_id = (
                    artifact.artifact_id if artifact is not None else None
                )
                expected_artifact_sha = (
                    artifact.sha256 if artifact is not None else None
                )
                if (
                    record.source_kind != spec.source_kind
                    or record.authority != spec.authority
                    or record.rights != spec.rights
                    or record.sensitivity != spec.sensitivity
                    or record.locator_kind != spec.locator_kind
                    or record.locator != spec.locator
                    or record.citation != spec.citation
                    or record.diversity_group != spec.diversity_group
                    or record.scores != spec.scores
                    or record.valid_from_ms != spec.valid_from_ms
                    or record.valid_until_ms != spec.valid_until_ms
                    or record.fresh_until_ms != spec.fresh_until_ms
                    or record.artifact_alias_name
                    != spec.artifact_alias_name
                    or record.artifact_id != expected_artifact_id
                    or record.artifact_sha256 != expected_artifact_sha
                ):
                    raise ApprovedSourceV1Conflict(
                        "source identity already has different immutable content"
                    )
                return record
            payload: dict[str, object] = {
                "schema": SCHEMA,
                "source_id": source_id,
                "source_name": name,
                "workspace_id": self.workspace_id,
                "principal_id": self.principal_id,
                "source_kind": spec.source_kind,
                "authority": spec.authority,
                "rights": spec.rights,
                "sensitivity": spec.sensitivity,
                "locator_kind": spec.locator_kind,
                "locator": spec.locator,
                "citation": spec.citation,
                "diversity_group": spec.diversity_group,
                "scores": spec.scores.payload(),
                "credibility_bp": spec.scores.credibility_bp,
                "source_identity_sha256": domain_material_sha256_v1(
                    spec.locator
                ),
                "valid_from_ms": spec.valid_from_ms,
                "valid_until_ms": spec.valid_until_ms,
                "fresh_until_ms": spec.fresh_until_ms,
                "artifact_alias_name": spec.artifact_alias_name,
                "artifact_id": (
                    artifact.artifact_id if artifact is not None else None
                ),
                "artifact_sha256": (
                    artifact.sha256 if artifact is not None else None
                ),
                "status": "approved",
                "created_at_ms": now_ms,
                "updated_at_ms": now_ms,
                "revoked_at_ms": None,
                "content_trust": "untrusted_data",
                "instructions_authority": False,
                "key_fingerprint_sha256": self._key_fingerprint,
            }
            payload["hmac_sha256"] = _payload_mac(
                payload,
                self._integrity_key,
            )
            try:
                connection.execute("BEGIN IMMEDIATE")
                locked_artifact = self._artifact_binding(spec, now_ms=now_ms)
                if locked_artifact != artifact:
                    raise ApprovedSourceV1Denied(
                        "artifact alias changed before source publication"
                    )
                connection.execute(
                    "INSERT INTO capability_descriptors("
                    "capability_id,workspace_id,schema_version,status,"
                    "payload_json,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?)",
                    (
                        source_id,
                        self.workspace_id,
                        SCHEMA_VERSION,
                        "approved",
                        _canonical(payload).decode("utf-8"),
                        str(now_ms),
                        str(now_ms),
                    ),
                )
                connection.execute("COMMIT")
            except ApprovedSourceV1Denied:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ApprovedSourceV1Conflict(
                    "source identity was concurrently claimed"
                ) from exc
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ApprovedSourceV1Error("source write failed") from exc
            row = self._row(connection, source_id)
            if row is None:
                raise ApprovedSourceV1Denied("source write read-back failed")
            record = self._parse_row(row)
            self._reattest_artifact(record, now_ms=now_ms)
            self._attest()
            return record

    def _reattest_artifact(
        self,
        record: ApprovedSourceRecordV1,
        *,
        now_ms: int,
    ) -> None:
        if record.locator_kind != "artifact_alias":
            return
        assert record.artifact_alias_name is not None
        try:
            alias = self._aliases.get(
                kind="artifact",
                alias_name=record.artifact_alias_name,
                now_ms=now_ms,
            )
        except Exception as exc:
            raise ApprovedSourceV1Denied(
                "approved source artifact binding drift"
            ) from exc
        if (
            alias.locator != record.locator
            or alias.artifact_id != record.artifact_id
            or alias.sha256 != record.artifact_sha256
        ):
            raise ApprovedSourceV1Denied(
                "approved source artifact binding drift"
            )

    def get(
        self,
        source_name: str,
        *,
        now_ms: int,
        require_fresh: bool = True,
        include_revoked: bool = False,
    ) -> ApprovedSourceRecordV1:
        name = _source_name(source_name)
        _timestamp("now_ms", now_ms)
        if type(require_fresh) is not bool or type(include_revoked) is not bool:
            raise ApprovedSourceV1ContractError(
                "lifecycle selectors must be exact bool"
            )
        connection = self._attest()
        source_id = approved_source_id_v1(
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            source_name=name,
        )
        row = self._row(connection, source_id)
        if row is None:
            raise ApprovedSourceV1Denied("approved source is unavailable")
        record = self._parse_row(row)
        if (
            not include_revoked
            and not self._available(
                record,
                now_ms=now_ms,
                require_fresh=require_fresh,
            )
        ):
            raise ApprovedSourceV1Denied(
                "approved source is revoked, invalid, or stale"
            )
        self._reattest_artifact(record, now_ms=now_ms)
        self._attest()
        return record

    def list(
        self,
        *,
        now_ms: int,
        allowed_sensitivities: tuple[str, ...],
        require_fresh: bool = True,
    ) -> tuple[ApprovedSourceRecordV1, ...]:
        _timestamp("now_ms", now_ms)
        if (
            type(allowed_sensitivities) is not tuple
            or not allowed_sensitivities
            or len(set(allowed_sensitivities)) != len(
                allowed_sensitivities
            )
            or any(value not in SENSITIVITIES for value in allowed_sensitivities)
        ):
            raise ApprovedSourceV1ContractError(
                "allowed sensitivities are invalid"
            )
        if type(require_fresh) is not bool:
            raise ApprovedSourceV1ContractError(
                "require_fresh must be exact bool"
            )
        connection = self._attest()
        try:
            rows = connection.execute(
                "SELECT capability_id,workspace_id,schema_version,status,"
                "payload_json,created_at,updated_at FROM capability_descriptors "
                "WHERE workspace_id=? AND capability_id LIKE ? "
                "ORDER BY capability_id LIMIT ?",
                (self.workspace_id, f"{CAPABILITY_PREFIX}%", MAX_SOURCES + 1),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise ApprovedSourceV1Denied("source list failed") from exc
        if len(rows) > MAX_SOURCES:
            raise ApprovedSourceV1Denied("approved source bound exceeded")
        records: list[ApprovedSourceRecordV1] = []
        for row in rows:
            try:
                record = self._parse_row(tuple(row))
            except ApprovedSourceV1Denied:
                payload = _strict_json(str(row[4]))
                if payload.get("principal_id") != self.principal_id:
                    continue
                raise
            if (
                record.sensitivity not in allowed_sensitivities
                or not self._available(
                    record,
                    now_ms=now_ms,
                    require_fresh=require_fresh,
                )
            ):
                continue
            self._reattest_artifact(record, now_ms=now_ms)
            records.append(record)
        records.sort(key=lambda item: (item.source_kind, item.source_name))
        self._attest()
        return tuple(records)

    def revoke(
        self,
        source_name: str,
        *,
        now_ms: int,
    ) -> ApprovedSourceRecordV1:
        name = _source_name(source_name)
        _timestamp("now_ms", now_ms)
        source_id = approved_source_id_v1(
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            source_name=name,
        )
        with _WRITE_LOCK:
            connection = self._attest()
            row = self._row(connection, source_id)
            if row is None:
                raise ApprovedSourceV1Denied("approved source is unavailable")
            record = self._parse_row(row)
            if record.status == "revoked":
                return record
            if now_ms < record.created_at_ms:
                raise ApprovedSourceV1ContractError(
                    "revocation precedes source creation"
                )
            payload = _strict_json(str(row[4]))
            payload["status"] = "revoked"
            payload["updated_at_ms"] = now_ms
            payload["revoked_at_ms"] = now_ms
            payload["hmac_sha256"] = _payload_mac(
                payload,
                self._integrity_key,
            )
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE capability_descriptors SET status=?,payload_json=?,"
                    "updated_at=? WHERE capability_id=? AND workspace_id=? "
                    "AND status='approved'",
                    (
                        "revoked",
                        _canonical(payload).decode("utf-8"),
                        str(now_ms),
                        source_id,
                        self.workspace_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ApprovedSourceV1Conflict(
                        "source lifecycle changed concurrently"
                    )
                connection.execute("COMMIT")
            except ApprovedSourceV1Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ApprovedSourceV1Error("source revocation failed") from exc
            updated = self._row(connection, source_id)
            if updated is None:
                raise ApprovedSourceV1Denied("revocation read-back failed")
            revoked = self._parse_row(updated)
            self._attest()
            return revoked


def create_approved_source_registry_v1(
    *,
    gate: ApprovedSourceFeatureGateV1 | None = None,
    registry: WorkspaceRegistry | None = None,
    aliases: WorkspaceAliasCatalogV1 | None = None,
    workspace_id: str | None = None,
    principal_id: str | None = None,
    integrity_key: bytes | None = None,
    project_root: Path | str | None = None,
) -> ApprovedSourceRegistryV1 | None:
    selected = (
        ApprovedSourceFeatureGateV1.from_environ() if gate is None else gate
    )
    if type(selected) is not ApprovedSourceFeatureGateV1:
        raise ApprovedSourceV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_aliases_entry(
        Path(__file__).resolve().parents[1]
        if project_root is None
        else project_root
    )
    if (
        registry is None
        or aliases is None
        or workspace_id is None
        or principal_id is None
        or integrity_key is None
    ):
        raise ApprovedSourceV1ContractError(
            "enabled registry requires complete host bindings"
        )
    return ApprovedSourceRegistryV1(
        construction_key=_CONSTRUCTION_KEY,
        registry=registry,
        aliases=aliases,
        workspace_id=workspace_id,
        principal_id=principal_id,
        integrity_key=integrity_key,
    )


__all__ = [
    "ALIASES_ENTRY_ROOTS",
    "AUTHORITIES",
    "CAPABILITY_PREFIX",
    "ENABLED_VALUE",
    "FEATURE_FLAG",
    "LOCATOR_KINDS",
    "MAX_SOURCES",
    "RIGHTS",
    "SCHEMA",
    "SCORE_FIELDS",
    "SENSITIVITIES",
    "SOURCE_KINDS",
    "ApprovedSourceFeatureGateV1",
    "ApprovedSourceRecordV1",
    "ApprovedSourceRegistryV1",
    "ApprovedSourceSpecV1",
    "ApprovedSourceV1Conflict",
    "ApprovedSourceV1ContractError",
    "ApprovedSourceV1Denied",
    "ApprovedSourceV1Error",
    "SourceScoresV1",
    "approved_source_id_v1",
    "canonical_https_locator_v1",
    "create_approved_source_registry_v1",
    "domain_material_sha256_v1",
]
