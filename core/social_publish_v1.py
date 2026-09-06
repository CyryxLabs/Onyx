"""Provider-independent social preview and governed single-dispatch publication.

The provider boundary is injected.  This module performs no network I/O and the
factory is disabled unless its exact feature flag is enabled.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import signal
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Mapping, Protocol

FEATURE_FLAG: Final = "ONYX_SOCIAL_PUBLISH_V1"
ENABLED_VALUE: Final = "true"
MAX_TEXT_BYTES: Final = 20_000
MAX_ID_BYTES: Final = 256
STATUSES: Final = (
    "previewed",
    "consented",
    "dispatching",
    "verified",
    "uncertain_needs_reconciliation",
    "invalidated",
)
SUPPORTED_PLATFORMS: Final = frozenset(
    {"instagram", "linkedin", "x", "facebook", "youtube", "tiktok"}
)


class SocialPublishContractError(ValueError):
    """Input or state-transition contract violation."""


class SocialPublishDenied(PermissionError):
    """Governance denied an external mutation."""


class SocialPublishUncertain(RuntimeError):
    """Provider outcome cannot safely be classified after dispatch."""


def _text(value: object, maximum: int, field: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise SocialPublishContractError(f"{field} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise SocialPublishContractError(f"{field} contract violation")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class SocialPublishFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise SocialPublishContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "SocialPublishFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class CaptionRequestV1:
    workspace_id: str
    principal_id: str
    account_id: str
    target: str
    caption: str
    media_digests: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in ("workspace_id", "principal_id", "account_id", "target"):
            _text(getattr(self, field), MAX_ID_BYTES, field)
        _text(self.caption, MAX_TEXT_BYTES, "caption")
        for field in ("media_digests", "provenance", "warnings"):
            value = getattr(self, field)
            if type(value) is not tuple:
                raise SocialPublishContractError(f"{field} must be a tuple")
            maximum = MAX_TEXT_BYTES if field == "warnings" else MAX_ID_BYTES
            for item in value:
                _text(item, maximum, field)
        if len(self.media_digests) != len(set(self.media_digests)):
            raise SocialPublishContractError("media_digests contains duplicates")


@dataclass(frozen=True, slots=True)
class CaptionGenerationRequestV1:
    brief: str
    brand: str
    platform: str
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.brief, MAX_TEXT_BYTES, "brief")
        _text(self.brand, MAX_ID_BYTES, "brand")
        _text(self.platform, MAX_ID_BYTES, "platform")
        if self.platform not in SUPPORTED_PLATFORMS:
            raise SocialPublishContractError("platform is unsupported")
        if type(self.source_refs) is not tuple:
            raise SocialPublishContractError("source_refs must be a tuple")
        for item in self.source_refs:
            _text(item, MAX_ID_BYTES, "source_refs")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise SocialPublishContractError("source_refs contains duplicates")


@dataclass(frozen=True, slots=True)
class CaptionDraftV1:
    request_identity: str
    status: str
    caption: str
    brand: str
    platform: str
    provenance: tuple[str, ...]
    warnings: tuple[str, ...]


def generate_caption_draft(request: CaptionGenerationRequestV1) -> CaptionDraftV1:
    """Generate a deterministic local draft without a model or provider call."""
    identity = _digest(
        {
            "schema": "onyx.local-caption-generation.v1",
            "brief": request.brief,
            "brand": request.brand,
            "platform": request.platform,
            "source_refs": request.source_refs,
        }
    )
    caption = f"{request.brand} — {request.brief}"
    provenance = (
        "generator:onyx-local-template-v1",
        f"request:{identity}",
        *(f"source:{item}" for item in request.source_refs),
    )
    warnings = (
        "Draft only; generation does not approve or publish content.",
        "Validate claims, rights, disclosures, and platform policy before consent.",
    )
    return CaptionDraftV1(
        request_identity=identity,
        status="draft",
        caption=caption,
        brand=request.brand,
        platform=request.platform,
        provenance=provenance,
        warnings=warnings,
    )


@dataclass(frozen=True, slots=True)
class CaptionPreviewV1:
    request_digest: str
    payload_digest: str
    target_digest: str
    account_digest: str
    media_digest: str
    caption: str
    provenance: tuple[str, ...]
    warnings: tuple[str, ...]
    consent_text: str


@dataclass(frozen=True, slots=True)
class ProviderDispatchV1:
    idempotency_key: str
    request_digest: str
    account_id: str
    target: str
    caption: str
    media_digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderReceiptV1:
    provider_request_id: str
    content_id: str | None

    def __post_init__(self) -> None:
        _text(self.provider_request_id, MAX_ID_BYTES, "provider_request_id")
        if self.content_id is not None:
            _text(self.content_id, MAX_ID_BYTES, "content_id")


@dataclass(frozen=True, slots=True)
class ProviderObservationV1:
    outcome: str
    content_id: str | None

    def __post_init__(self) -> None:
        if self.outcome not in {"verified", "absent", "unknown"}:
            raise SocialPublishContractError("provider observation outcome is unknown")
        if self.content_id is not None:
            _text(self.content_id, MAX_ID_BYTES, "content_id")


class SocialProviderAdapterV1(Protocol):
    def dispatch(self, request: ProviderDispatchV1) -> ProviderReceiptV1: ...

    def observe(self, receipt: ProviderReceiptV1) -> ProviderObservationV1: ...


@dataclass(frozen=True, slots=True)
class PublicationRecordV1:
    preview: CaptionPreviewV1
    status: str
    consented: bool = False
    dispatch_attempted: bool = False
    receipt: ProviderReceiptV1 | None = None
    observation: ProviderObservationV1 | None = None


def preview_caption(request: CaptionRequestV1) -> CaptionPreviewV1:
    """Create a deterministic preview; it cannot reach a provider."""
    payload = {"caption": request.caption, "media_digests": request.media_digests}
    target = {"workspace_id": request.workspace_id, "target": request.target}
    account = {"workspace_id": request.workspace_id, "account_id": request.account_id}
    media_digest = _digest(request.media_digests)
    request_digest = _digest(
        {
            "schema": "onyx.social-caption-preview.v1",
            "principal_id": request.principal_id,
            "payload": payload,
            "target": target,
            "account": account,
            "provenance": request.provenance,
            "warnings": request.warnings,
        }
    )
    consent = f"PUBLISH EXACT PREVIEW {request_digest}"
    return CaptionPreviewV1(
        request_digest=request_digest,
        payload_digest=_digest(payload),
        target_digest=_digest(target),
        account_digest=_digest(account),
        media_digest=media_digest,
        caption=request.caption,
        provenance=request.provenance,
        warnings=request.warnings,
        consent_text=consent,
    )


class SocialPublicationV1:
    """Durable authority record enforcing consent, one dispatch, and readback."""

    def __init__(self, adapter: SocialProviderAdapterV1, ledger_path: Path) -> None:
        if adapter is None:
            raise SocialPublishContractError("an injected provider adapter is required")
        if not isinstance(ledger_path, Path) or not ledger_path.is_absolute():
            raise SocialPublishContractError("ledger_path must be an absolute Path")
        self._adapter = adapter
        self.path = ledger_path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS social_publications_v1 (
                request_digest TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                principal_id TEXT NOT NULL, request_json TEXT NOT NULL,
                preview_json TEXT NOT NULL, status TEXT NOT NULL,
                consented INTEGER NOT NULL DEFAULT 0,
                dispatch_attempted INTEGER NOT NULL DEFAULT 0,
                receipt_json TEXT, observation_json TEXT, dispatch_pid INTEGER)"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS social_active_v1 (
                workspace_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                PRIMARY KEY (workspace_id, principal_id))"""
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(social_publications_v1)"
                )
            }
            if "dispatch_pid" not in columns:
                connection.execute(
                    "ALTER TABLE social_publications_v1 ADD COLUMN dispatch_pid INTEGER"
                )
            for row in connection.execute(
                "SELECT request_digest,dispatch_pid FROM social_publications_v1 "
                "WHERE status='dispatching'"
            ):
                if not self._pid_alive(row["dispatch_pid"]):
                    connection.execute(
                        "UPDATE social_publications_v1 SET status=? WHERE request_digest=?",
                        ("uncertain_needs_reconciliation", row["request_digest"]),
                    )
            connection.commit()

    @staticmethod
    def _pid_alive(pid: int | None) -> bool:
        if pid is None:
            return False
        if pid == os.getpid():
            return True
        try:
            os.kill(pid, signal.SIG_DFL)
        except (OSError, ValueError):
            return False
        return True

    @staticmethod
    def _json(value: object) -> str:
        return _canonical(value).decode("utf-8")

    @staticmethod
    def _record(row: sqlite3.Row) -> PublicationRecordV1:
        preview_data = json.loads(row["preview_json"])
        preview_data["provenance"] = tuple(preview_data["provenance"])
        preview_data["warnings"] = tuple(preview_data["warnings"])
        receipt = (
            ProviderReceiptV1(**json.loads(row["receipt_json"]))
            if row["receipt_json"]
            else None
        )
        observation = (
            ProviderObservationV1(**json.loads(row["observation_json"]))
            if row["observation_json"]
            else None
        )
        return PublicationRecordV1(
            preview=CaptionPreviewV1(**preview_data),
            status=row["status"],
            consented=bool(row["consented"]),
            dispatch_attempted=bool(row["dispatch_attempted"]),
            receipt=receipt,
            observation=observation,
        )

    @staticmethod
    def _request_json(request: CaptionRequestV1) -> str:
        return SocialPublicationV1._json(asdict(request))

    def _invalidate_drift(
        self, connection: sqlite3.Connection, request: CaptionRequestV1, digest: str
    ) -> bool:
        active = connection.execute(
            "SELECT request_digest FROM social_active_v1 WHERE workspace_id=? AND principal_id=?",
            (request.workspace_id, request.principal_id),
        ).fetchone()
        if active is None or active["request_digest"] == digest:
            return active is not None
        connection.execute(
            """UPDATE social_publications_v1 SET status='invalidated', consented=0
            WHERE request_digest=? AND status IN ('previewed','consented')""",
            (active["request_digest"],),
        )
        return False

    def create_preview(self, request: CaptionRequestV1) -> PublicationRecordV1:
        preview = preview_caption(request)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._invalidate_drift(connection, request, preview.request_digest)
            existing = connection.execute(
                "SELECT * FROM social_publications_v1 WHERE request_digest=?",
                (preview.request_digest,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO social_publications_v1
                    (request_digest,workspace_id,principal_id,request_json,preview_json,status)
                    VALUES (?,?,?,?,?,'previewed')""",
                    (
                        preview.request_digest,
                        request.workspace_id,
                        request.principal_id,
                        self._request_json(request),
                        self._json(asdict(preview)),
                    ),
                )
            connection.execute(
                """INSERT INTO social_active_v1 VALUES (?,?,?)
                ON CONFLICT(workspace_id,principal_id) DO UPDATE SET request_digest=excluded.request_digest""",
                (request.workspace_id, request.principal_id, preview.request_digest),
            )
            row = connection.execute(
                "SELECT * FROM social_publications_v1 WHERE request_digest=?",
                (preview.request_digest,),
            ).fetchone()
            connection.commit()
        return self._record(row)

    def consent(
        self, request: CaptionRequestV1, *, exact_consent: str
    ) -> PublicationRecordV1:
        preview = preview_caption(request)
        if exact_consent != preview.consent_text:
            raise SocialPublishDenied("exact explicit consent did not match preview")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = self._invalidate_drift(connection, request, preview.request_digest)
            changed = (
                connection.execute(
                    """UPDATE social_publications_v1 SET status='consented', consented=1
                WHERE request_digest=? AND request_json=? AND status='previewed'""",
                    (preview.request_digest, self._request_json(request)),
                ).rowcount
                if active
                else 0
            )
            if changed != 1:
                if active:
                    connection.rollback()
                else:
                    connection.commit()
                raise SocialPublishDenied("a current preview is required")
            row = connection.execute(
                "SELECT * FROM social_publications_v1 WHERE request_digest=?",
                (preview.request_digest,),
            ).fetchone()
            connection.commit()
        return self._record(row)

    def dispatch(self, request: CaptionRequestV1) -> PublicationRecordV1:
        preview = preview_caption(request)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = self._invalidate_drift(connection, request, preview.request_digest)
            changed = (
                connection.execute(
                    """UPDATE social_publications_v1
                SET status='dispatching', dispatch_attempted=1, dispatch_pid=?
                WHERE request_digest=? AND request_json=? AND status='consented'
                AND consented=1 AND dispatch_attempted=0""",
                    (os.getpid(), preview.request_digest, self._request_json(request)),
                ).rowcount
                if active
                else 0
            )
            if changed != 1:
                if active:
                    connection.rollback()
                else:
                    connection.commit()
                raise SocialPublishDenied("dispatch unavailable; blind retry denied")
            connection.commit()
        dispatch = ProviderDispatchV1(
            idempotency_key=preview.request_digest,
            request_digest=preview.request_digest,
            account_id=request.account_id,
            target=request.target,
            caption=request.caption,
            media_digests=request.media_digests,
        )
        try:
            receipt = self._adapter.dispatch(dispatch)
        except Exception as exc:
            self._update(
                preview.request_digest, status="uncertain_needs_reconciliation"
            )
            raise SocialPublishUncertain("post-dispatch outcome is uncertain") from exc
        if type(receipt) is not ProviderReceiptV1:
            self._update(
                preview.request_digest, status="uncertain_needs_reconciliation"
            )
            raise SocialPublishUncertain("provider receipt contract is uncertain")
        record = self._update(preview.request_digest, receipt=receipt)
        return self._observe(preview.request_digest, record)

    def _update(
        self,
        request_digest: str,
        *,
        status: str | None = None,
        receipt: ProviderReceiptV1 | None = None,
        observation: ProviderObservationV1 | None = None,
    ) -> PublicationRecordV1:
        assignments, values = [], []
        if status is not None:
            assignments.append("status=?")
            values.append(status)
        if receipt is not None:
            assignments.append("receipt_json=?")
            values.append(self._json(asdict(receipt)))
        if observation is not None:
            assignments.append("observation_json=?")
            values.append(self._json(asdict(observation)))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                f"UPDATE social_publications_v1 SET {', '.join(assignments)} WHERE request_digest=?",
                (*values, request_digest),
            )
            row = connection.execute(
                "SELECT * FROM social_publications_v1 WHERE request_digest=?",
                (request_digest,),
            ).fetchone()
            connection.commit()
        if row is None:
            raise SocialPublishContractError("unknown request digest")
        return self._record(row)

    def reconcile(self, request_digest: str) -> PublicationRecordV1:
        record = self.status(request_digest)
        if record.status != "uncertain_needs_reconciliation":
            raise SocialPublishDenied("record does not require reconciliation")
        if record.receipt is None:
            raise SocialPublishUncertain(
                "no receipt available; manual reconciliation required"
            )
        return self._observe(request_digest, record)

    def _observe(
        self, request_digest: str, record: PublicationRecordV1
    ) -> PublicationRecordV1:
        assert record.receipt is not None
        try:
            observation = self._adapter.observe(record.receipt)
        except Exception as exc:
            self._update(request_digest, status="uncertain_needs_reconciliation")
            raise SocialPublishUncertain("provider readback is uncertain") from exc
        if type(observation) is not ProviderObservationV1:
            self._update(request_digest, status="uncertain_needs_reconciliation")
            raise SocialPublishUncertain("provider observation contract is uncertain")
        verified = (
            observation.outcome == "verified"
            and observation.content_id is not None
            and observation.content_id == record.receipt.content_id
        )
        status = "verified" if verified else "uncertain_needs_reconciliation"
        return self._update(request_digest, status=status, observation=observation)

    def status(self, request_digest: str) -> PublicationRecordV1:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM social_publications_v1 WHERE request_digest=?",
                (request_digest,),
            ).fetchone()
        if row is None:
            raise SocialPublishContractError("unknown request digest")
        return self._record(row)


def create_social_publication_v1(
    *,
    gate: SocialPublishFeatureGateV1,
    adapter: SocialProviderAdapterV1 | None = None,
    ledger_path: Path | None = None,
) -> SocialPublicationV1 | None:
    if type(gate) is not SocialPublishFeatureGateV1:
        raise SocialPublishContractError("feature gate contract violation")
    if not gate.enabled:
        return None
    if adapter is None:
        raise SocialPublishDenied("social provider adapter is disabled/unavailable")
    if ledger_path is None:
        raise SocialPublishDenied("an explicit durable ledger path is required")
    return SocialPublicationV1(adapter, ledger_path)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "STATUSES",
    "SUPPORTED_PLATFORMS",
    "SocialPublishFeatureGateV1",
    "CaptionGenerationRequestV1",
    "CaptionDraftV1",
    "generate_caption_draft",
    "CaptionRequestV1",
    "CaptionPreviewV1",
    "ProviderDispatchV1",
    "ProviderReceiptV1",
    "ProviderObservationV1",
    "SocialProviderAdapterV1",
    "PublicationRecordV1",
    "SocialPublicationV1",
    "SocialPublishContractError",
    "SocialPublishDenied",
    "SocialPublishUncertain",
    "preview_caption",
    "create_social_publication_v1",
]
