"""Governed provider-free document intake over accepted Phase 7 components."""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import stat
import sys
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from core.artifact_service import ArtifactRecord, ArtifactService
from core.control_plane import ControlPlaneStore
from core.governance_nucleus_v1 import GovernanceIdentityV1, GovernanceNucleusV1
from core.phase7_approved_sources_v1 import (
    ApprovedSourceSpecV1,
    SourceScoresV1,
    approved_source_id_v1,
)
from core.phase7_document_ingestion_v1 import (
    DocumentEnvelopeV1,
    FORMATS,
    GovernedDocumentIngestorV1,
    IngestionResultV1,
)
from core.phase7_workspace_aliases_v1 import (
    ArtifactAliasSpecV1,
    WorkspaceAliasRecordV1,
)
from memory.store import contains_secret


FEATURE_FLAG: Final = "ONYX_DOCUMENT_INTAKE_LIVE_V1"
ENABLED_VALUE: Final = "true"
TOOL_NAME: Final = "document_intake_read"
ARGUMENTS: Final = frozenset(
    {
        "alias",
        "source",
        "logical_document_id",
        "revision_id",
        "filename",
        "media_type",
    }
)
MAX_PUBLIC_TEXT: Final = 2_000
PUBLIC_ATTACHMENT_FIELDS: Final = frozenset(
    {
        "alias",
        "source",
        "logical_document_id",
        "revision_id",
        "filename",
        "media_type",
    }
)
_WINDOWS_REPARSE_ATTRIBUTE: Final = 0x400


class DocumentIntakeLiveV1Error(RuntimeError):
    """Base live intake failure."""


class DocumentIntakeLiveV1ContractError(ValueError):
    """The closed model-facing request contract was violated."""


class DocumentIntakeLiveV1Denied(PermissionError):
    """Identity, alias, source, artifact, kill or integrity denied the read."""


class DocumentIntakeLiveV1ReconciliationRequired(DocumentIntakeLiveV1Error):
    """An attachment alias may have committed but cannot yet be reattested."""


class DocumentCommitLeaseV1:
    """Linearize caller cancellation against the first durable source write."""

    __slots__ = ("_lock", "_state")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = "open"

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def cancel(self) -> bool:
        with self._lock:
            if self._state == "open":
                self._state = "cancelled"
                return True
            return False

    def permit_commit(self) -> None:
        with self._lock:
            if self._state == "cancelled":
                raise DocumentIntakeLiveV1Denied(
                    "document intake cancelled before commit"
                )
            if self._state == "open":
                self._state = "commit-permitted"
            elif self._state != "commit-permitted":
                raise DocumentIntakeLiveV1Denied(
                    "document intake commit lease is inactive"
                )

    def complete(self) -> None:
        with self._lock:
            if self._state == "commit-permitted":
                self._state = "completed"
            elif self._state == "open":
                self._state = "completed-without-commit"


def tool_declaration_v1() -> dict[str, object]:
    fields = {
        "alias": "Existing artifact alias in the active workspace.",
        "source": "Approved-source name bound to that exact alias.",
        "logical_document_id": "Stable logical document name.",
        "revision_id": "Exact revision name for this artifact.",
        "filename": "Display filename including the supported extension.",
        "media_type": "Exact supported media type matching the artifact.",
    }
    return {
        "name": TOOL_NAME,
        "description": (
            "Read and analyze one already-published, already-aliased document "
            "inside the active Onyx workspace using only its stable alias."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                name: {"type": "STRING", "description": description}
                for name, description in fields.items()
            },
            "required": list(fields),
        },
    }


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _safe_public_text(value: str) -> dict[str, object]:
    text = value.strip()[:MAX_PUBLIC_TEXT]
    if not text or contains_secret(text):
        return {"text": "[redacted]", "redacted": True}
    return {"text": text, "redacted": False}


class DocumentIntakeControllerV1:
    """Exact identity-bound adapter from aliases/CAS to the accepted ingestor."""

    __slots__ = (
        "identity",
        "_nucleus",
        "_store",
        "_artifacts",
        "_aliases",
        "_sources",
        "_ingestor",
        "_closed",
        "_closing",
        "_active",
        "_lock",
        "_condition",
        "_local",
        "_provision_lock",
    )

    def __init__(
        self,
        *,
        identity: GovernanceIdentityV1,
        nucleus: GovernanceNucleusV1,
        store: ControlPlaneStore,
        artifacts: ArtifactService,
        aliases: object,
        sources: object,
        ingestor: GovernedDocumentIngestorV1,
    ) -> None:
        if (
            type(identity) is not GovernanceIdentityV1
            or type(nucleus) is not GovernanceNucleusV1
            or type(store) is not ControlPlaneStore
            or type(artifacts) is not ArtifactService
            or type(ingestor) is not GovernedDocumentIngestorV1
            or nucleus.identity != identity
            or artifacts.workspace_id != identity.workspace_id
            or getattr(aliases, "workspace_id", None) != identity.workspace_id
            or getattr(aliases, "principal_id", None) != identity.principal_id
            or getattr(sources, "workspace_id", None) != identity.workspace_id
            or getattr(sources, "principal_id", None) != identity.principal_id
        ):
            raise DocumentIntakeLiveV1ContractError(
                "exact identity-bound intake components are required"
            )
        self.identity = identity
        self._nucleus = nucleus
        self._store = store
        self._artifacts = artifacts
        self._aliases = aliases
        self._sources = sources
        self._ingestor = ingestor
        self._closed = False
        self._closing = False
        self._active = 0
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._local = threading.local()
        self._provision_lock = threading.RLock()

    @property
    def available(self) -> bool:
        with self._lock:
            return not self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if getattr(self._local, "operation_depth", 0):
                raise DocumentIntakeLiveV1Denied(
                    "document intake cannot close from its active operation"
                )
            while self._closing:
                self._condition.wait()
                if self._closed:
                    return
            self._closing = True
            while self._active:
                self._condition.wait()
        try:
            self._artifacts.close()
        except BaseException:
            # Artifact authority close is the commit point.  Keep the
            # controller retryable and wake exactly one waiting close path;
            # operations remain denied for the whole failed attempt.
            with self._lock:
                self._closing = False
                self._condition.notify_all()
            raise
        with self._lock:
            self._closed = True
            self._closing = False
            self._condition.notify_all()

    @contextmanager
    def _operation(self):
        with self._lock:
            if self._closed or self._closing:
                raise DocumentIntakeLiveV1Denied("document intake is closed")
            self._active += 1
            self._local.operation_depth = (
                getattr(self._local, "operation_depth", 0) + 1
            )
        try:
            yield
        finally:
            with self._lock:
                depth = getattr(self._local, "operation_depth", 0)
                if depth <= 1:
                    try:
                        del self._local.operation_depth
                    except AttributeError:
                        pass
                else:
                    self._local.operation_depth = depth - 1
                self._active -= 1
                if not self._active:
                    self._condition.notify_all()

    def _exact_arguments(self, arguments: Mapping[str, object]) -> dict[str, str]:
        if type(arguments) is not dict or set(arguments) != ARGUMENTS:
            raise DocumentIntakeLiveV1ContractError(
                "document intake arguments are not exact"
            )
        result: dict[str, str] = {}
        for name in sorted(ARGUMENTS):
            value = arguments.get(name)
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 255
                or (name != "media_type" and "/" in value)
                or "\\" in value
                or ".." in value
                or contains_secret(value)
            ):
                raise DocumentIntakeLiveV1ContractError(
                    f"document intake {name} is invalid"
                )
            result[name] = value
        return result

    @staticmethod
    def _within(candidate: Path, root: Path) -> bool:
        try:
            return os.path.commonpath((candidate, root)) == str(root)
        except ValueError:
            return False

    @staticmethod
    def _normalized_absolute(path: Path | str) -> Path:
        """Normalize one local path, including Windows namespace spellings."""

        value = os.path.abspath(os.fspath(path))
        if os.name == "nt":
            if value.startswith("\\\\?\\UNC\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\"):
                value = value[4:]
        return Path(os.path.normcase(value))

    @classmethod
    def _protected_directory(cls, path: Path | str, *, label: str) -> Path:
        """Resolve a required protected directory or deny all intake."""

        try:
            candidate = Path(path)
            if not candidate.is_absolute():
                raise OSError("protected path is not absolute")
            resolved = candidate.resolve(strict=True)
            observed = resolved.lstat()
        except (OSError, RuntimeError, ValueError) as exc:
            raise DocumentIntakeLiveV1Denied(
                f"attachment protected {label} boundary is unavailable"
            ) from exc
        if not stat.S_ISDIR(observed.st_mode):
            raise DocumentIntakeLiveV1Denied(
                f"attachment protected {label} boundary is unavailable"
            )
        return cls._normalized_absolute(resolved)

    def _materialize_attachment_path(
        self, source: Path | str
    ) -> tuple[Path, tuple[int, int, int, int]]:
        if type(source) is not str and not isinstance(source, Path):
            raise DocumentIntakeLiveV1ContractError(
                "attachment requires one host-selected path"
            )
        raw = Path(source)
        if not raw.is_absolute():
            raise DocumentIntakeLiveV1Denied(
                "attachment path must be absolute"
            )
        try:
            resolved = raw.resolve(strict=True)
            observed = resolved.lstat()
        except OSError as exc:
            raise DocumentIntakeLiveV1Denied(
                "attachment source is unavailable"
            ) from exc
        if (
            self._normalized_absolute(raw)
            != self._normalized_absolute(resolved)
            or not stat.S_ISREG(observed.st_mode)
            or resolved.is_symlink()
            or int(getattr(observed, "st_nlink", 1)) != 1
        ):
            raise DocumentIntakeLiveV1Denied(
                "attachment must be one regular unlinked file"
            )
        for component in (resolved, *resolved.parents):
            try:
                info = component.lstat()
            except OSError as exc:
                raise DocumentIntakeLiveV1Denied(
                    "attachment path chain is unavailable"
                ) from exc
            if component.is_symlink() or (
                int(getattr(info, "st_file_attributes", 0))
                & _WINDOWS_REPARSE_ATTRIBUTE
            ):
                raise DocumentIntakeLiveV1Denied(
                    "attachment path chain contains a link or reparse point"
                )
        pinned_root = getattr(self._artifacts._pinned, "root", None)
        if pinned_root is None:
            raise DocumentIntakeLiveV1Denied(
                "attachment protected CAS boundary is unavailable"
            )
        protected: list[Path] = [
            self._protected_directory(
                Path(__file__).resolve().parents[1], label="application"
            ),
            self._protected_directory(
                Path(sys.executable).parent, label="installation"
            ),
            self._protected_directory(
                self._store.path.parent, label="control-plane"
            ),
            self._protected_directory(pinned_root, label="CAS"),
        ]
        for name in (
            "SystemRoot",
            "WINDIR",
            "ProgramFiles",
            "ProgramFiles(x86)",
            "ProgramData",
        ):
            value = os.environ.get(name, "").strip()
            if value:
                protected.append(
                    self._protected_directory(value, label=f"environment:{name}")
                )
        normalized = self._normalized_absolute(resolved)
        if any(
            self._within(normalized, root)
            for root in protected
        ):
            raise DocumentIntakeLiveV1Denied(
                "attachment source is inside a protected root"
            )
        identity = (
            int(observed.st_dev),
            int(observed.st_ino),
            int(observed.st_size),
            int(observed.st_mtime_ns),
        )
        return resolved, identity

    @staticmethod
    def _attachment_media_type(path: Path) -> str:
        suffix = path.suffix.casefold()
        matches = sorted(
            media_type
            for media_type, (_format, suffixes) in FORMATS.items()
            if suffix in suffixes
        )
        if len(matches) != 1:
            raise DocumentIntakeLiveV1ContractError(
                "attachment format is unsupported or ambiguous"
            )
        return matches[0]

    def _index_attachment(self, record: ArtifactRecord) -> bool:
        connection = self._store._require_connection()
        expected = (
            record.artifact_id,
            self.identity.workspace_id,
            record.schema_version,
            record.sha256,
            record.relative_path,
            record.media_type,
            "available",
            record.created_at,
        )
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT artifact_id,workspace_id,schema_version,sha256,"
                "relative_path,media_type,status,created_at FROM artifact_index "
                "WHERE artifact_id=? OR (workspace_id=? AND sha256=?)",
                (
                    record.artifact_id,
                    self.identity.workspace_id,
                    record.sha256,
                ),
            ).fetchall()
            if rows:
                if len(rows) != 1 or tuple(rows[0]) != expected:
                    raise DocumentIntakeLiveV1Denied(
                        "attachment artifact index conflict"
                    )
                connection.execute("COMMIT")
                return False
            connection.execute(
                "INSERT INTO artifact_index VALUES(?,?,?,?,?,?,?,?)",
                expected,
            )
            connection.execute("COMMIT")
            return True
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _rollback_attachment_index(self, record: ArtifactRecord) -> None:
        connection = self._store._require_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM artifact_index WHERE artifact_id=? AND "
                "workspace_id=? AND sha256=? AND relative_path=? AND "
                "media_type=? AND status='available' AND created_at=?",
                (
                    record.artifact_id,
                    self.identity.workspace_id,
                    record.sha256,
                    record.relative_path,
                    record.media_type,
                    record.created_at,
                ),
            )
            if cursor.rowcount != 1:
                raise DocumentIntakeLiveV1Denied(
                    "attachment index rollback requires reconciliation"
                )
            connection.execute("COMMIT")
        except BaseException as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise DocumentIntakeLiveV1Denied(
                "attachment index rollback requires reconciliation"
            ) from exc

    def provision_trusted_attachment(
        self,
        source: Path | str,
        *,
        commit_lease: DocumentCommitLeaseV1 | None = None,
    ) -> dict[str, str]:
        """Host-only QFileDialog/drop adapter; never expose the source path."""

        with self._operation(), self._provision_lock:
            if self._nucleus.killed:
                raise DocumentIntakeLiveV1Denied(
                    "attachment provisioning denied by global kill"
                )
            path, identity = self._materialize_attachment_path(source)
            media_type = self._attachment_media_type(path)
            if (
                not path.name
                or path.name != path.name.strip()
                or len(path.name) > 255
                or ".." in path.name
                or contains_secret(path.name)
            ):
                raise DocumentIntakeLiveV1ContractError(
                    "attachment filename is invalid"
                )
            record = self._artifacts.publish_file(
                path,
                media_type=media_type,
                data_class="internal",
                source_provenance={
                    "kind": "trusted_ui_attachment",
                    "selection": "qfiledialog_or_drop",
                },
                display_name=path.name,
            )
            after_path, after_identity = self._materialize_attachment_path(path)
            if after_path != path or after_identity != identity:
                raise DocumentIntakeLiveV1Denied(
                    "attachment source changed during publication"
                )
            token = record.sha256[:32]
            alias_name = f"attachment-{token}"
            public = {
                "alias": alias_name,
                "source": f"attachment-source-{token}",
                "logical_document_id": f"attachment-{token}",
                "revision_id": f"sha256-{record.sha256}",
                "filename": path.name,
                "media_type": media_type,
            }
            # Validate the model-facing contract before artifact_index or
            # alias metadata can commit. Generated digest fields are safe by
            # construction; the host-selected filename was rejected before
            # CAS publication.
            public = self._exact_arguments(public)
            lease = (
                DocumentCommitLeaseV1() if commit_lease is None else commit_lease
            )
            if type(lease) is not DocumentCommitLeaseV1:
                raise DocumentIntakeLiveV1ContractError(
                    "exact attachment commit lease is required"
                )
            inserted = False
            try:
                with self._nucleus.local_commit_fence():
                    lease.permit_commit()
                    inserted = self._index_attachment(record)
                    try:
                        alias = self._aliases.register(
                            alias_name,
                            ArtifactAliasSpecV1(
                                artifact_id=record.artifact_id,
                                sha256=record.sha256,
                                relative_path=record.relative_path,
                                media_type=record.media_type,
                            ),
                            now_ms=_now_ms(),
                        )
                    except BaseException as registration_error:
                        try:
                            alias = self._aliases.get(
                                kind="artifact",
                                alias_name=alias_name,
                                now_ms=_now_ms(),
                            )
                        except BaseException:
                            # register may have committed before raising. If
                            # readback fails for any reason, even an apparent
                            # absence, a concurrent commit can race that read.
                            # Deleting the artifact index could then strand a
                            # durable alias. Retain the exact row fail-closed.
                            raise DocumentIntakeLiveV1ReconciliationRequired(
                                "attachment_alias_reconciliation_required"
                            ) from registration_error
                    if (
                        alias.artifact_id != record.artifact_id
                        or alias.sha256 != record.sha256
                        or alias.relative_path != record.relative_path
                        or alias.media_type != record.media_type
                    ):
                        if inserted:
                            self._rollback_attachment_index(record)
                        raise DocumentIntakeLiveV1Denied(
                            "attachment alias binding conflict"
                        )
                if self._nucleus.killed:
                    raise DocumentIntakeLiveV1Denied(
                        "attachment provisioning denied by global kill"
                    )
                if set(public) != PUBLIC_ATTACHMENT_FIELDS:
                    raise DocumentIntakeLiveV1Denied(
                        "attachment public projection is not exact"
                    )
                rendered = repr(public)
                if (
                    str(path) in rendered
                    or record.artifact_id in rendered
                    or self.identity.workspace_id in rendered
                ):
                    raise DocumentIntakeLiveV1Denied(
                        "attachment public projection leaked host metadata"
                    )
                return public
            finally:
                lease.complete()

    def _indexed_record(
        self, alias: WorkspaceAliasRecordV1
    ) -> ArtifactRecord:
        if (
            type(alias) is not WorkspaceAliasRecordV1
            or alias.kind != "artifact"
            or alias.status != "active"
            or alias.workspace_id != self.identity.workspace_id
            or alias.principal_id != self.identity.principal_id
            or alias.artifact_id is None
            or alias.sha256 is None
            or alias.relative_path is None
            or alias.media_type is None
            or alias.artifact_created_at is None
        ):
            raise DocumentIntakeLiveV1Denied("artifact alias binding denied")
        row = self._store._require_connection().execute(
            "SELECT artifact_id,workspace_id,schema_version,sha256,"
            "relative_path,media_type,status,created_at FROM artifact_index "
            "WHERE artifact_id=? AND workspace_id=?",
            (alias.artifact_id, self.identity.workspace_id),
        ).fetchone()
        expected = (
            alias.artifact_id,
            self.identity.workspace_id,
            alias.artifact_schema_version,
            alias.sha256,
            alias.relative_path,
            alias.media_type,
            "available",
            alias.artifact_created_at,
        )
        if row is None or tuple(row) != expected:
            raise DocumentIntakeLiveV1Denied("artifact index binding drift")
        return self._artifacts.recover_indexed_record(
            artifact_id=alias.artifact_id,
            sha256=alias.sha256,
            relative_path=alias.relative_path,
            media_type=alias.media_type,
            created_at=alias.artifact_created_at,
        )

    def _register_or_attest_source(
        self,
        *,
        source_name: str,
        alias: WorkspaceAliasRecordV1,
        now_ms: int,
    ) -> object:
        assert alias.sha256 is not None
        source_id = approved_source_id_v1(
            workspace_id=self.identity.workspace_id,
            principal_id=self.identity.principal_id,
            source_name=source_name,
        )
        try:
            row = self._store._require_connection().execute(
                "SELECT capability_id FROM capability_descriptors "
                "WHERE capability_id=? AND workspace_id=?",
                (source_id, self.identity.workspace_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise DocumentIntakeLiveV1Denied(
                "approved source existence could not be attested"
            ) from exc
        if row is not None:
            # An existing identity must pass the registry's complete fresh,
            # lifecycle, MAC and artifact-binding attestation.  Never turn a
            # stale, revoked or corrupt identity into a registration attempt.
            source = self._sources.get(
                source_name, now_ms=now_ms, require_fresh=True
            )
        else:
            source = self._sources.register(
                source_name,
                ApprovedSourceSpecV1(
                    source_kind="product_artifact",
                    authority="authoritative_primary",
                    rights="user_owned",
                    sensitivity="internal",
                    locator_kind="artifact_alias",
                    locator=alias.locator,
                    citation=alias.locator,
                    diversity_group="onyx-document-intake",
                    scores=SourceScoresV1(
                        expertise_bp=8_000,
                        primary_evidence_bp=10_000,
                        editorial_quality_bp=7_000,
                        recency_bp=10_000,
                        correction_history_bp=5_000,
                        incentive_independence_bp=5_000,
                        corroboration_bp=5_000,
                        relevance_bp=10_000,
                    ),
                    valid_from_ms=now_ms,
                    valid_until_ms=now_ms + 86_400_000,
                    fresh_until_ms=now_ms + 86_400_000,
                    artifact_alias_name=alias.alias_name,
                ),
                now_ms=now_ms,
            )
        if (
            source.workspace_id != self.identity.workspace_id
            or source.principal_id != self.identity.principal_id
            or source.locator_kind != "artifact_alias"
            or source.artifact_alias_name != alias.alias_name
            or source.artifact_id != alias.artifact_id
            or source.artifact_sha256 != alias.sha256
            or source.status != "approved"
        ):
            raise DocumentIntakeLiveV1Denied("approved source binding drift")
        return source

    def _public_projection(
        self,
        result: IngestionResultV1,
        *,
        alias_name: str,
    ) -> dict[str, object]:
        citation_base = (
            f"onyx-artifact://v1/alias/{alias_name}/sha256/"
            f"{result.document_sha256}"
        )

        def statements(values: tuple[object, ...]) -> list[dict[str, object]]:
            return [
                {
                    "kind": str(getattr(item, "statement_kind", "")),
                    **_safe_public_text(str(getattr(item, "text", ""))),
                    "citations": len(getattr(item, "citation_ids", ())),
                    "confidence_bp": int(getattr(item, "confidence_bp", 0)),
                    "instructions_authority": False,
                }
                for item in values
            ]

        public = {
            "status": "completed",
            "read_only": True,
            "content_trust": "untrusted_data",
            "instructions_authority": False,
            "document": {
                "alias": alias_name,
                "logical_document": result.logical_document_id,
                "revision": result.revision_id,
                "filename": result.filename,
                "media_type": result.media_type,
                "format": result.format,
            },
            "citations": [
                {
                    "ref": f"{citation_base}#{item.unit_kind}-{item.unit_index}",
                    "kind": item.unit_kind,
                    "index": item.unit_index,
                    "redacted": True,
                    "instructions_authority": False,
                }
                for item in result.citations
            ],
            "requirements": statements(result.requirements),
            "decisions": statements(result.decisions),
            "qa": [
                {
                    "severity": item.severity,
                    "code": item.code,
                    "surface": item.surface,
                    **_safe_public_text(item.detail),
                }
                for item in result.qa_findings
            ],
            "poison_signals": [
                _safe_public_text(str(value)) for value in result.poison_signals
            ],
            "render_status": result.render_status,
            "ocr_status": result.ocr_status,
        }
        rendered = repr(public)
        forbidden = (
            self.identity.workspace_id,
            self.identity.principal_id,
            self.identity.account_id,
            self.identity.profile_id,
            result.source_id,
        )
        if any(value and value in rendered for value in forbidden):
            raise DocumentIntakeLiveV1Denied("document projection redaction failed")
        return public

    def execute(
        self,
        arguments: Mapping[str, object],
        *,
        commit_lease: DocumentCommitLeaseV1 | None = None,
    ) -> dict[str, object]:
        values = self._exact_arguments(arguments)
        with self._operation():
            if self._nucleus.killed:
                raise DocumentIntakeLiveV1Denied(
                    "document intake denied by global kill"
                )
            now_ms = _now_ms()
            alias = self._aliases.get(
                kind="artifact", alias_name=values["alias"], now_ms=now_ms
            )
            if alias.media_type != values["media_type"]:
                raise DocumentIntakeLiveV1Denied(
                    "document media type differs from alias"
                )
            record = self._indexed_record(alias)
            content = self._artifacts.read(record)
            if not hmac.compare_digest(
                hashlib.sha256(content).hexdigest(), record.sha256
            ):
                raise DocumentIntakeLiveV1Denied("document bytes changed")
            lease = (
                DocumentCommitLeaseV1() if commit_lease is None else commit_lease
            )
            if type(lease) is not DocumentCommitLeaseV1:
                raise DocumentIntakeLiveV1ContractError(
                    "exact document commit lease is required"
                )
            try:
                with self._nucleus.local_commit_fence():
                    lease.permit_commit()
                    self._register_or_attest_source(
                        source_name=values["source"], alias=alias, now_ms=now_ms
                    )
                if self._nucleus.killed:
                    raise DocumentIntakeLiveV1Denied(
                        "document intake denied by global kill"
                    )
                result = self._ingestor.ingest(
                    DocumentEnvelopeV1(
                        source_name=values["source"],
                        logical_document_id=values["logical_document_id"],
                        revision_id=values["revision_id"],
                        filename=values["filename"],
                        media_type=values["media_type"],
                        content_bytes=content,
                        observed_locator=alias.locator,
                        retrieved_at_ms=now_ms,
                    ),
                    now_ms=now_ms,
                )
                self._ingestor.verify_result(result, now_ms=now_ms)
                # Linearize result publication against global kill. A kill
                # either owns this fence first and suppresses the result, or
                # publication wins and the later kill applies to future reads.
                with self._nucleus.local_commit_fence():
                    if self._nucleus.killed:
                        raise DocumentIntakeLiveV1Denied(
                            "document intake result suppressed by global kill"
                        )
                    return self._public_projection(
                        result, alias_name=alias.alias_name
                    )
            finally:
                lease.complete()


__all__ = [
    "ARGUMENTS",
    "DocumentCommitLeaseV1",
    "DocumentIntakeControllerV1",
    "DocumentIntakeLiveV1ContractError",
    "DocumentIntakeLiveV1Denied",
    "DocumentIntakeLiveV1Error",
    "DocumentIntakeLiveV1ReconciliationRequired",
    "ENABLED_VALUE",
    "FEATURE_FLAG",
    "TOOL_NAME",
    "tool_declaration_v1",
]
