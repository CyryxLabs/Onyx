"""Default-off M2b-b schema-v3 migration and verified read-only opener.

This module is deliberately absent from startup.  It migrates an exact,
populated control-plane v2 database only through an owner capability and an
M2b-a ledger anchor.  It does not contain an operational writer API; existing
v2 WorkspaceRegistry/DomainLedger writers continue to reject user_version 3.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import weakref
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from core import ledger_anchor
from core.control_plane import (
    APPLICATION_ID,
    M1A_SCHEMA_VERSION,
    M1B_MIGRATION_ID,
    MIGRATION_ID,
    SCHEMA_ID,
    SCHEMA_VERSION as V2_SCHEMA_VERSION,
    ControlPlaneError,
    ControlPlaneSchemaError,
    ControlPlaneStore,
    _canonical_sql_tokens,
    _reference_manifest,
    _schema_fingerprint,
    _schema_manifest,
    _valid_utc_timestamp,
)
from core.domain_ledger import (
    DomainIntegrityError,
    DomainLedgerError,
    DomainLedgerRepository,
    _record_digest,
)
from core.workspaces import LEGACY_WORKSPACE_ID, WorkspaceRegistry


LEDGER_V3_FLAG = "ONYX_M2B_LEDGER_V3"
V3_SCHEMA_VERSION = 3
M2B_MIGRATION_ID = "m2b-immutable-ledger-v3"
_ZERO_HASH = "0" * 64
_DIGEST = re.compile(r"[0-9a-f]{64}")
_DATABASE_INSTANCE_ID = re.compile(r"cp-[0-9a-f]{64}")
_V3_LOCK = threading.RLock()
_CAPABILITY_SEAL = object()
_CAPABILITY_REGISTRY: weakref.WeakKeyDictionary[
    V3OwnerCapability, bytes
] = weakref.WeakKeyDictionary()

_LEGACY_RENAMES = (
    ("evidence_records", "legacy_v2_evidence_records"),
    ("claims", "legacy_v2_claims"),
    ("action_requests", "legacy_v2_action_requests"),
    ("action_receipts", "legacy_v2_action_receipts"),
    ("event_envelopes", "legacy_v2_event_envelopes"),
    ("projections", "legacy_v2_projections"),
)
_ANCHOR_EXCLUDED_TABLES = frozenset(
    {
        "integrity_commits",
        "anchor_intents",
        "anchor_finalizations",
        "operational_commits",
        "operational_commit_entries",
        "operational_entry_merkle_nodes",
        "operational_mmr_nodes",
        "operational_mmr_edges",
        "operational_mmr_peaks",
        "operational_anchor_intents",
        "operational_anchor_finalizations",
    }
)
_BOOKKEEPING_BINDING_NAMESPACE = b"ONYX-CONTROL-PLANE-V3-BOOKKEEPING-SHA256-V1\0"
_BOOKKEEPING_LIMB_PREFIX = "v3_bookkeeping_sha256_v1_"
_BOOKKEEPING_COLUMNS = (
    (
        "integrity_commits",
        (
            "commit_id",
            "database_instance_id",
            "schema_fingerprint",
            "state_root",
            "root_row_count",
            "algorithm",
            "created_at",
        ),
    ),
    (
        "anchor_intents",
        (
            "intent_id",
            "commit_id",
            "anchor_sequence",
            "state_root",
            "status",
            "created_at",
        ),
    ),
    (
        "anchor_finalizations",
        (
            "finalization_id",
            "intent_id",
            "anchor_sequence",
            "state_root",
            "created_at",
        ),
    ),
)


class ControlPlaneV3Error(ControlPlaneError):
    """Base safe failure for the isolated schema-v3 checkpoint."""


class ControlPlaneV3Disabled(ControlPlaneV3Error):
    """Raised unless M2b-b is explicitly enabled."""


class ControlPlaneV3Unavailable(ControlPlaneV3Error):
    """Raised because production anchor ownership is intentionally unwired."""


class ControlPlaneV3IntegrityError(ControlPlaneV3Error):
    """Raised for ambiguous history, invalid roots, or anchor divergence."""


class ControlPlaneV3Conflict(ControlPlaneV3Error):
    """Raised for stale capabilities or incomplete migration state."""


class ControlPlaneV3IOError(ControlPlaneV3Error):
    """Raised for transaction or durable-state reconciliation failures."""


def _sanitized_v3_error(error: Exception) -> ControlPlaneV3Error:
    """Create a detached public error without retaining private exception state."""

    if isinstance(error, ControlPlaneV3Disabled):
        return ControlPlaneV3Disabled("v3 is disabled")
    if isinstance(error, ControlPlaneV3Unavailable):
        return ControlPlaneV3Unavailable("v3 is unavailable")
    if isinstance(error, ControlPlaneV3Conflict):
        return ControlPlaneV3Conflict("v3 state transition conflict")
    if isinstance(error, ControlPlaneV3IntegrityError):
        return ControlPlaneV3IntegrityError("v3 integrity verification failed")
    if isinstance(error, ControlPlaneV3IOError):
        return ControlPlaneV3IOError("v3 durable-state operation failed")
    if isinstance(error, ControlPlaneV3Error):
        return ControlPlaneV3Error("v3 operation failed")
    if isinstance(error, ControlPlaneSchemaError):
        return ControlPlaneV3IntegrityError("v3 integrity verification failed")
    if isinstance(error, ControlPlaneError):
        return ControlPlaneV3IOError("v3 durable-state operation failed")
    if isinstance(
        error,
        (ledger_anchor.LedgerAnchorIOError, ledger_anchor.LedgerAnchorVaultError),
    ):
        return ControlPlaneV3IOError("v3 durable-state operation failed")
    if isinstance(error, ledger_anchor.LedgerAnchorError):
        return ControlPlaneV3IntegrityError("v3 integrity verification failed")
    return ControlPlaneV3IOError("v3 durable-state operation failed")


def _public_v3_boundary(method):
    """Expose detached, stable errors and preserve process cancellation."""

    @functools.wraps(method)
    def guarded(*args, **kwargs):
        public_error: ControlPlaneV3Error | None = None
        try:
            return method(*args, **kwargs)
        except (
            ControlPlaneV3Error,
            ControlPlaneError,
            ledger_anchor.LedgerAnchorError,
            OSError,
            sqlite3.Error,
        ) as error:
            public_error = _sanitized_v3_error(error)

        # This raise deliberately occurs after the except suite.  ``from None``
        # only suppresses display of an active exception; it still retains that
        # exception in ``__context__``.  Raising here leaves no private object or
        # traceback reachable from the public failure.  BaseException process
        # interrupts/cancellations never match the normalization clause above.
        assert public_error is not None
        raise public_error

    return guarded


def ledger_v3_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(LEDGER_V3_FLAG, "").strip().casefold() in {"1", "true"}


class V3OwnerCapability:
    __slots__ = ("_token", "_seal", "__weakref__")

    def __init__(self, token: bytes, seal: object):
        if seal is not _CAPABILITY_SEAL:
            raise TypeError("V3OwnerCapability cannot be constructed directly")
        self._token = token
        self._seal = seal

    def __copy__(self):
        raise TypeError("V3OwnerCapability cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("V3OwnerCapability cannot be copied")

    def __reduce__(self):
        raise TypeError("V3OwnerCapability cannot be serialized")

    def __repr__(self) -> str:
        return "<V3OwnerCapability sealed>"


@dataclass(frozen=True, slots=True)
class V3Status:
    database_instance_id: str
    schema_version: int
    schema_fingerprint: str
    state_root: str
    root_row_count: int
    anchor_sequence: int
    exposed: bool


@dataclass(frozen=True, slots=True)
class _RootResult:
    digest: str
    row_count: int
    table_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _BookkeepingState:
    commit: tuple[object, ...]
    intent: tuple[object, ...]
    finalization: tuple[object, ...]
    anchor_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _OperationalState:
    commit: tuple[object, ...]
    entries: tuple[tuple[object, ...], ...]
    intent: tuple[object, ...]
    finalization: tuple[object, ...]
    anchor_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _V2History:
    evidence: tuple[object, ...]
    claims: tuple[object, ...]
    requests: tuple[object, ...]
    receipts: tuple[object, ...]
    events: tuple[object, ...]
    chains: tuple[tuple[tuple[str, str], tuple[object, ...]], ...]
    legacy_digests: tuple[tuple[str, str, int], ...]


@runtime_checkable
class _SecretVault(Protocol):
    def get_bytes(self) -> bytes | None: ...

    def set_bytes(self, secret: bytes | bytearray) -> None: ...

    def delete(self) -> bool: ...


def _immutable_triggers(
    table: str, *, deny_insert: bool
) -> tuple[str, ...]:
    operations = ("INSERT", "UPDATE", "DELETE") if deny_insert else ("UPDATE", "DELETE")
    return tuple(
        f"CREATE TRIGGER deny_{table}_{operation.lower()} BEFORE {operation} ON {table} "
        f"BEGIN SELECT RAISE(ABORT,'{table} is immutable'); END"
        for operation in operations
    )


_RENAME_STATEMENTS = tuple(
    f"ALTER TABLE {source} RENAME TO {target}" for source, target in _LEGACY_RENAMES
)

_V3_TABLE_STATEMENTS = (
    "CREATE UNIQUE INDEX idx_v3_mission_context_scope "
    "ON mission_contexts(workspace_id,mission_id)",
    """
    CREATE TABLE evidence_records(
        evidence_id TEXT PRIMARY KEY CHECK(length(evidence_id) BETWEEN 1 AND 192),
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        schema_version INTEGER NOT NULL CHECK(schema_version=3),
        correlation_id TEXT NOT NULL CHECK(length(correlation_id) BETWEEN 1 AND 192),
        source_kind TEXT NOT NULL CHECK(source_kind IN
            ('artifact','local_read','mission_result','observation','provider','public_url')),
        source_identity_sha256 TEXT NOT NULL CHECK(length(source_identity_sha256)=64 AND source_identity_sha256=lower(source_identity_sha256) AND source_identity_sha256 NOT GLOB '*[^0-9a-f]*'),
        content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64 AND content_sha256=lower(content_sha256) AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
        artifact_id TEXT,
        credibility_bp INTEGER NOT NULL CHECK(credibility_bp BETWEEN 0 AND 10000),
        freshness TEXT NOT NULL CHECK(freshness IN ('current','historical','unknown')),
        validity_seconds INTEGER CHECK(validity_seconds IS NULL OR validity_seconds BETWEEN 1 AND 31536000),
        observed_at TEXT NOT NULL CHECK(length(observed_at) BETWEEN 20 AND 40),
        valid_until TEXT CHECK((validity_seconds IS NULL)=(valid_until IS NULL)),
        access_license_sha256 TEXT NOT NULL CHECK(length(access_license_sha256)=64 AND access_license_sha256=lower(access_license_sha256) AND access_license_sha256 NOT GLOB '*[^0-9a-f]*'),
        input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64 AND input_sha256=lower(input_sha256) AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64 AND record_sha256=lower(record_sha256) AND record_sha256 NOT GLOB '*[^0-9a-f]*'),
        legacy_payload_json TEXT NOT NULL CHECK(json_valid(legacy_payload_json) AND json_type(legacy_payload_json)='object'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        UNIQUE(workspace_id,evidence_id),
        UNIQUE(workspace_id,mission_id,evidence_id),
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
        FOREIGN KEY(workspace_id,mission_id) REFERENCES mission_contexts(workspace_id,mission_id),
        FOREIGN KEY(artifact_id) REFERENCES artifact_index(artifact_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE claims(
        claim_id TEXT PRIMARY KEY CHECK(length(claim_id) BETWEEN 1 AND 192),
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        schema_version INTEGER NOT NULL CHECK(schema_version=3),
        correlation_id TEXT NOT NULL CHECK(length(correlation_id) BETWEEN 1 AND 192),
        claim_kind TEXT NOT NULL CHECK(claim_kind IN ('fact','forecast','inference','recommendation','unknown')),
        statement_sha256 TEXT NOT NULL CHECK(length(statement_sha256)=64 AND statement_sha256=lower(statement_sha256) AND statement_sha256 NOT GLOB '*[^0-9a-f]*'),
        confidence_bp INTEGER NOT NULL CHECK(confidence_bp BETWEEN 0 AND 10000),
        verification_status TEXT NOT NULL CHECK(verification_status IN ('contradicted','supported','unknown','unverified')),
        validity_seconds INTEGER CHECK(validity_seconds IS NULL OR validity_seconds BETWEEN 1 AND 31536000),
        valid_until TEXT CHECK((validity_seconds IS NULL)=(valid_until IS NULL)),
        input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64 AND input_sha256=lower(input_sha256) AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64 AND record_sha256=lower(record_sha256) AND record_sha256 NOT GLOB '*[^0-9a-f]*'),
        legacy_payload_json TEXT NOT NULL CHECK(json_valid(legacy_payload_json) AND json_type(legacy_payload_json)='object'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        UNIQUE(workspace_id,claim_id),
        UNIQUE(workspace_id,mission_id,claim_id),
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
        FOREIGN KEY(workspace_id,mission_id) REFERENCES mission_contexts(workspace_id,mission_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE claim_evidence_links(
        claim_id TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        link_ordinal INTEGER NOT NULL CHECK(link_ordinal>=0),
        PRIMARY KEY(claim_id,evidence_id),
        UNIQUE(claim_id,link_ordinal),
        FOREIGN KEY(workspace_id,mission_id,claim_id) REFERENCES claims(workspace_id,mission_id,claim_id),
        FOREIGN KEY(workspace_id,mission_id,evidence_id) REFERENCES evidence_records(workspace_id,mission_id,evidence_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE claim_relations(
        relation_id TEXT PRIMARY KEY CHECK(length(relation_id)=64 AND relation_id=lower(relation_id) AND relation_id NOT GLOB '*[^0-9a-f]*'),
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        source_claim_id TEXT NOT NULL,
        target_claim_id TEXT NOT NULL,
        relation_kind TEXT NOT NULL CHECK(relation_kind IN ('contradicts','supersedes')),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        CHECK(source_claim_id<>target_claim_id),
        UNIQUE(workspace_id,source_claim_id,target_claim_id,relation_kind),
        FOREIGN KEY(workspace_id,mission_id,source_claim_id) REFERENCES claims(workspace_id,mission_id,claim_id),
        FOREIGN KEY(workspace_id,mission_id,target_claim_id) REFERENCES claims(workspace_id,mission_id,claim_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE action_requests(
        request_id TEXT PRIMARY KEY CHECK(length(request_id) BETWEEN 1 AND 192),
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        schema_version INTEGER NOT NULL CHECK(schema_version=3),
        correlation_id TEXT NOT NULL CHECK(length(correlation_id) BETWEEN 1 AND 192),
        idempotency_key TEXT NOT NULL,
        connector TEXT NOT NULL CHECK(length(connector) BETWEEN 1 AND 80),
        operation TEXT NOT NULL CHECK(length(operation) BETWEEN 1 AND 80),
        target_sha256 TEXT NOT NULL CHECK(length(target_sha256)=64 AND target_sha256=lower(target_sha256) AND target_sha256 NOT GLOB '*[^0-9a-f]*'),
        payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64 AND payload_sha256=lower(payload_sha256) AND payload_sha256 NOT GLOB '*[^0-9a-f]*'),
        risk TEXT NOT NULL CHECK(risk IN ('critical','high','low','medium')),
        approval_policy TEXT NOT NULL CHECK(approval_policy IN ('always_explicit','exact_callback','shadow_only')),
        data_class TEXT NOT NULL CHECK(data_class IN ('confidential','internal','public','restricted')),
        dry_run INTEGER NOT NULL CHECK(dry_run=1),
        verification_plan_sha256 TEXT NOT NULL CHECK(length(verification_plan_sha256)=64 AND verification_plan_sha256=lower(verification_plan_sha256) AND verification_plan_sha256 NOT GLOB '*[^0-9a-f]*'),
        rollback_plan_sha256 TEXT NOT NULL CHECK(length(rollback_plan_sha256)=64 AND rollback_plan_sha256=lower(rollback_plan_sha256) AND rollback_plan_sha256 NOT GLOB '*[^0-9a-f]*'),
        input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64 AND input_sha256=lower(input_sha256) AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64 AND record_sha256=lower(record_sha256) AND record_sha256 NOT GLOB '*[^0-9a-f]*'),
        legacy_payload_json TEXT NOT NULL CHECK(json_valid(legacy_payload_json) AND json_type(legacy_payload_json)='object'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        UNIQUE(workspace_id,request_id),
        UNIQUE(workspace_id,mission_id,request_id),
        UNIQUE(workspace_id,idempotency_key),
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
        FOREIGN KEY(workspace_id,mission_id) REFERENCES mission_contexts(workspace_id,mission_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE action_receipts(
        receipt_id TEXT PRIMARY KEY CHECK(length(receipt_id) BETWEEN 1 AND 192),
        request_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        schema_version INTEGER NOT NULL CHECK(schema_version=3),
        correlation_id TEXT NOT NULL CHECK(length(correlation_id) BETWEEN 1 AND 192),
        outcome TEXT NOT NULL CHECK(outcome IN ('cancelled','failed','partial','rejected','simulated','succeeded','unknown')),
        provider_request_sha256 TEXT NOT NULL CHECK(length(provider_request_sha256)=64 AND provider_request_sha256=lower(provider_request_sha256) AND provider_request_sha256 NOT GLOB '*[^0-9a-f]*'),
        before_sha256 TEXT NOT NULL CHECK(length(before_sha256)=64 AND before_sha256=lower(before_sha256) AND before_sha256 NOT GLOB '*[^0-9a-f]*'),
        after_sha256 TEXT NOT NULL CHECK(length(after_sha256)=64 AND after_sha256=lower(after_sha256) AND after_sha256 NOT GLOB '*[^0-9a-f]*'),
        output_sha256 TEXT NOT NULL CHECK(length(output_sha256)=64 AND output_sha256=lower(output_sha256) AND output_sha256 NOT GLOB '*[^0-9a-f]*'),
        verification_sha256 TEXT NOT NULL CHECK(length(verification_sha256)=64 AND verification_sha256=lower(verification_sha256) AND verification_sha256 NOT GLOB '*[^0-9a-f]*'),
        rollback_sha256 TEXT NOT NULL CHECK(length(rollback_sha256)=64 AND rollback_sha256=lower(rollback_sha256) AND rollback_sha256 NOT GLOB '*[^0-9a-f]*'),
        error_class TEXT NOT NULL CHECK(length(error_class)<=80),
        supersedes_receipt_id TEXT,
        reconciliation INTEGER NOT NULL CHECK(reconciliation IN (0,1)),
        input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64 AND input_sha256=lower(input_sha256) AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64 AND record_sha256=lower(record_sha256) AND record_sha256 NOT GLOB '*[^0-9a-f]*'),
        parent_request_sha256 TEXT NOT NULL CHECK(length(parent_request_sha256)=64 AND parent_request_sha256=lower(parent_request_sha256) AND parent_request_sha256 NOT GLOB '*[^0-9a-f]*'),
        observed_at TEXT NOT NULL CHECK(length(observed_at) BETWEEN 20 AND 40),
        legacy_payload_json TEXT NOT NULL CHECK(json_valid(legacy_payload_json) AND json_type(legacy_payload_json)='object'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        UNIQUE(workspace_id,receipt_id),
        FOREIGN KEY(workspace_id,mission_id,request_id) REFERENCES action_requests(workspace_id,mission_id,request_id),
        FOREIGN KEY(supersedes_receipt_id) REFERENCES action_receipts(receipt_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE action_state_history(
        request_id TEXT NOT NULL,
        state_sequence INTEGER NOT NULL CHECK(state_sequence>=0),
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        state TEXT NOT NULL CHECK(state IN ('proposed','recorded','reconciliation_required')),
        source_event_id TEXT NOT NULL,
        source_receipt_id TEXT,
        request_record_sha256 TEXT NOT NULL CHECK(length(request_record_sha256)=64 AND request_record_sha256=lower(request_record_sha256) AND request_record_sha256 NOT GLOB '*[^0-9a-f]*'),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64 AND record_sha256=lower(record_sha256) AND record_sha256 NOT GLOB '*[^0-9a-f]*'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        PRIMARY KEY(request_id,state_sequence),
        UNIQUE(source_event_id),
        FOREIGN KEY(workspace_id,mission_id,request_id) REFERENCES action_requests(workspace_id,mission_id,request_id),
        FOREIGN KEY(source_receipt_id) REFERENCES action_receipts(receipt_id),
        FOREIGN KEY(source_event_id) REFERENCES event_envelopes(event_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE projections(
        projection_id TEXT NOT NULL CHECK(length(projection_id) BETWEEN 1 AND 192),
        projection_revision INTEGER NOT NULL CHECK(projection_revision>=0),
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        schema_version INTEGER NOT NULL CHECK(schema_version=3),
        projection_type TEXT NOT NULL CHECK(length(projection_type) BETWEEN 1 AND 96),
        correlation_id TEXT NOT NULL CHECK(length(correlation_id) BETWEEN 1 AND 192),
        head_revision INTEGER NOT NULL CHECK(head_revision>=0),
        event_count INTEGER NOT NULL CHECK(event_count>=0),
        source_event_id TEXT,
        state_sha256 TEXT NOT NULL CHECK(length(state_sha256)=64 AND state_sha256=lower(state_sha256) AND state_sha256 NOT GLOB '*[^0-9a-f]*'),
        previous_state_sha256 TEXT,
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64 AND record_sha256=lower(record_sha256) AND record_sha256 NOT GLOB '*[^0-9a-f]*'),
        legacy_payload_json TEXT NOT NULL CHECK(json_valid(legacy_payload_json) AND json_type(legacy_payload_json)='object'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        updated_at TEXT NOT NULL CHECK(length(updated_at) BETWEEN 20 AND 40),
        CHECK((projection_revision=0 AND previous_state_sha256 IS NULL) OR
              (projection_revision>0 AND length(previous_state_sha256)=64 AND previous_state_sha256=lower(previous_state_sha256) AND previous_state_sha256 NOT GLOB '*[^0-9a-f]*')),
        PRIMARY KEY(workspace_id,projection_id,projection_revision),
        UNIQUE(source_event_id),
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
        FOREIGN KEY(workspace_id,mission_id) REFERENCES mission_contexts(workspace_id,mission_id),
        FOREIGN KEY(source_event_id) REFERENCES event_envelopes(event_id),
        FOREIGN KEY(workspace_id,correlation_id,head_revision)
          REFERENCES event_chain_heads(workspace_id,correlation_id,head_revision)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE event_envelopes(
        event_id TEXT PRIMARY KEY CHECK(length(event_id) BETWEEN 1 AND 192),
        workspace_id TEXT NOT NULL,
        mission_id TEXT,
        correlation_id TEXT NOT NULL,
        event_sequence INTEGER NOT NULL CHECK(event_sequence>=0),
        schema_version INTEGER NOT NULL CHECK(schema_version=3),
        event_type TEXT NOT NULL CHECK(event_type IN ('action.receipt.recorded','action.request.recorded','claim.recorded','evidence.recorded')),
        entity_type TEXT NOT NULL CHECK(entity_type IN ('action_receipt','action_request','claim','evidence')),
        entity_id TEXT NOT NULL,
        entity_sha256 TEXT NOT NULL CHECK(length(entity_sha256)=64 AND entity_sha256=lower(entity_sha256) AND entity_sha256 NOT GLOB '*[^0-9a-f]*'),
        parent_entity_id TEXT,
        parent_entity_sha256 TEXT,
        previous_hash TEXT NOT NULL CHECK(length(previous_hash)=64 AND previous_hash=lower(previous_hash) AND previous_hash NOT GLOB '*[^0-9a-f]*'),
        event_hash TEXT NOT NULL UNIQUE CHECK(length(event_hash)=64 AND event_hash=lower(event_hash) AND event_hash NOT GLOB '*[^0-9a-f]*'),
        legacy_payload_json TEXT NOT NULL CHECK(json_valid(legacy_payload_json) AND json_type(legacy_payload_json)='object'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        CHECK((parent_entity_id IS NULL)=(parent_entity_sha256 IS NULL)),
        UNIQUE(workspace_id,correlation_id,event_sequence),
        UNIQUE(workspace_id,correlation_id,event_sequence,event_id),
        UNIQUE(workspace_id,correlation_id,event_id),
        UNIQUE(workspace_id,correlation_id,event_hash),
        FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
        FOREIGN KEY(workspace_id,mission_id) REFERENCES mission_contexts(workspace_id,mission_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE event_chain_history(
        workspace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        event_sequence INTEGER NOT NULL CHECK(event_sequence>=0),
        event_id TEXT NOT NULL,
        previous_hash TEXT NOT NULL CHECK(length(previous_hash)=64),
        event_hash TEXT NOT NULL CHECK(length(event_hash)=64),
        PRIMARY KEY(workspace_id,correlation_id,event_sequence),
        UNIQUE(event_id),
        FOREIGN KEY(workspace_id,correlation_id,event_sequence,event_id)
          REFERENCES event_envelopes(workspace_id,correlation_id,event_sequence,event_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE event_chain_heads(
        workspace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        head_revision INTEGER NOT NULL CHECK(head_revision>=0),
        event_count INTEGER NOT NULL CHECK(event_count>=0),
        head_hash TEXT NOT NULL CHECK(length(head_hash)=64 AND head_hash=lower(head_hash) AND head_hash NOT GLOB '*[^0-9a-f]*'),
        first_event_id TEXT NOT NULL,
        last_event_id TEXT NOT NULL,
        previous_head_hash TEXT,
        CHECK((head_revision=0 AND previous_head_hash IS NULL) OR
              (head_revision>0 AND length(previous_head_hash)=64 AND previous_head_hash=lower(previous_head_hash) AND previous_head_hash NOT GLOB '*[^0-9a-f]*')),
        PRIMARY KEY(workspace_id,correlation_id,head_revision),
        UNIQUE(workspace_id,correlation_id,last_event_id),
        FOREIGN KEY(workspace_id,correlation_id,first_event_id)
          REFERENCES event_envelopes(workspace_id,correlation_id,event_id),
        FOREIGN KEY(workspace_id,correlation_id,last_event_id)
          REFERENCES event_envelopes(workspace_id,correlation_id,event_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE integrity_commits(
        commit_id TEXT PRIMARY KEY CHECK(length(commit_id)=64 AND commit_id=lower(commit_id) AND commit_id NOT GLOB '*[^0-9a-f]*'),
        database_instance_id TEXT NOT NULL,
        schema_fingerprint TEXT NOT NULL CHECK(length(schema_fingerprint)=64),
        state_root TEXT NOT NULL CHECK(length(state_root)=64),
        root_row_count INTEGER NOT NULL CHECK(root_row_count>=0),
        algorithm TEXT NOT NULL CHECK(algorithm='sha256-type-tagged-v1'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        UNIQUE(database_instance_id,state_root)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE anchor_intents(
        intent_id TEXT PRIMARY KEY CHECK(length(intent_id)=64),
        commit_id TEXT NOT NULL,
        anchor_sequence INTEGER NOT NULL CHECK(anchor_sequence>=1),
        state_root TEXT NOT NULL CHECK(length(state_root)=64),
        status TEXT NOT NULL CHECK(status='sqlite_committed'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        UNIQUE(commit_id),
        FOREIGN KEY(commit_id) REFERENCES integrity_commits(commit_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE anchor_finalizations(
        finalization_id TEXT PRIMARY KEY CHECK(length(finalization_id)=64),
        intent_id TEXT NOT NULL UNIQUE,
        anchor_sequence INTEGER NOT NULL CHECK(anchor_sequence>=1),
        state_root TEXT NOT NULL CHECK(length(state_root)=64),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        FOREIGN KEY(intent_id) REFERENCES anchor_intents(intent_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE operational_commits(
        commit_id TEXT PRIMARY KEY CHECK(length(commit_id)=64 AND commit_id=lower(commit_id) AND commit_id NOT GLOB '*[^0-9a-f]*'),
        commit_sequence INTEGER NOT NULL UNIQUE CHECK(commit_sequence>=1),
        previous_commit_id TEXT NOT NULL CHECK(length(previous_commit_id)=64 AND previous_commit_id=lower(previous_commit_id) AND previous_commit_id NOT GLOB '*[^0-9a-f]*'),
        previous_state_root TEXT NOT NULL CHECK(length(previous_state_root)=64 AND previous_state_root=lower(previous_state_root) AND previous_state_root NOT GLOB '*[^0-9a-f]*'),
        database_instance_id TEXT NOT NULL,
        schema_fingerprint TEXT NOT NULL CHECK(length(schema_fingerprint)=64),
        state_root TEXT NOT NULL CHECK(length(state_root)=64 AND state_root=lower(state_root) AND state_root NOT GLOB '*[^0-9a-f]*'),
        delta_sha256 TEXT NOT NULL CHECK(length(delta_sha256)=64 AND delta_sha256=lower(delta_sha256) AND delta_sha256 NOT GLOB '*[^0-9a-f]*'),
        genesis_baseline_root TEXT NOT NULL CHECK(length(genesis_baseline_root)=64 AND genesis_baseline_root=lower(genesis_baseline_root) AND genesis_baseline_root NOT GLOB '*[^0-9a-f]*'),
        entry_merkle_root TEXT NOT NULL CHECK(length(entry_merkle_root)=64 AND entry_merkle_root=lower(entry_merkle_root) AND entry_merkle_root NOT GLOB '*[^0-9a-f]*'),
        mmr_root TEXT NOT NULL CHECK(length(mmr_root)=64 AND mmr_root=lower(mmr_root) AND mmr_root NOT GLOB '*[^0-9a-f]*'),
        mmr_leaf_hash TEXT NOT NULL UNIQUE CHECK(length(mmr_leaf_hash)=64 AND mmr_leaf_hash=lower(mmr_leaf_hash) AND mmr_leaf_hash NOT GLOB '*[^0-9a-f]*'),
        mmr_size INTEGER NOT NULL UNIQUE CHECK(mmr_size>=1),
        entry_count INTEGER NOT NULL CHECK(entry_count>=1),
        canonical_row_count INTEGER NOT NULL CHECK(canonical_row_count>=1),
        event_count INTEGER NOT NULL CHECK(event_count>=0),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        UNIQUE(database_instance_id,state_root)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE operational_commit_entries(
        commit_id TEXT NOT NULL,
        entry_ordinal INTEGER NOT NULL CHECK(entry_ordinal>=0),
        table_name TEXT NOT NULL CHECK(table_name IN
            ('action_receipts','action_requests','action_state_history','artifact_index','claim_evidence_links','claim_relations','claims','event_chain_heads','event_chain_history','event_envelopes','evidence_records','legacy_v2_action_receipts','legacy_v2_action_requests','legacy_v2_claims','legacy_v2_event_envelopes','legacy_v2_evidence_records','legacy_v2_projections','mission_contexts','projections','workspaces')),
        row_identity TEXT NOT NULL CHECK(length(row_identity) BETWEEN 1 AND 512),
        row_sha256 TEXT NOT NULL CHECK(length(row_sha256)=64 AND row_sha256=lower(row_sha256) AND row_sha256 NOT GLOB '*[^0-9a-f]*'),
        leaf_index INTEGER NOT NULL CHECK(leaf_index>=0),
        leaf_hash TEXT NOT NULL CHECK(length(leaf_hash)=64 AND leaf_hash=lower(leaf_hash) AND leaf_hash NOT GLOB '*[^0-9a-f]*'),
        PRIMARY KEY(commit_id,entry_ordinal),
        UNIQUE(commit_id,leaf_index),
        UNIQUE(table_name,row_identity),
        FOREIGN KEY(commit_id) REFERENCES operational_commits(commit_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE operational_entry_merkle_nodes(
        commit_id TEXT NOT NULL,
        tree_level INTEGER NOT NULL CHECK(tree_level>=0),
        node_index INTEGER NOT NULL CHECK(node_index>=0),
        node_hash TEXT NOT NULL CHECK(length(node_hash)=64 AND node_hash=lower(node_hash) AND node_hash NOT GLOB '*[^0-9a-f]*'),
        PRIMARY KEY(commit_id,tree_level,node_index),
        FOREIGN KEY(commit_id) REFERENCES operational_commits(commit_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE operational_mmr_nodes(
        node_hash TEXT PRIMARY KEY CHECK(length(node_hash)=64 AND node_hash=lower(node_hash) AND node_hash NOT GLOB '*[^0-9a-f]*'),
        node_height INTEGER NOT NULL CHECK(node_height>=0),
        left_hash TEXT,
        right_hash TEXT,
        commit_sequence INTEGER NOT NULL CHECK(commit_sequence>=1),
        CHECK((node_height=0 AND left_hash IS NULL AND right_hash IS NULL) OR
              (node_height>0 AND length(left_hash)=64 AND length(right_hash)=64))
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE operational_mmr_edges(
        parent_hash TEXT NOT NULL,
        child_hash TEXT NOT NULL,
        side INTEGER NOT NULL CHECK(side IN (0,1)),
        PRIMARY KEY(parent_hash,side),
        UNIQUE(child_hash),
        FOREIGN KEY(parent_hash) REFERENCES operational_mmr_nodes(node_hash),
        FOREIGN KEY(child_hash) REFERENCES operational_mmr_nodes(node_hash)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE operational_mmr_peaks(
        commit_sequence INTEGER NOT NULL,
        peak_ordinal INTEGER NOT NULL CHECK(peak_ordinal>=0),
        peak_height INTEGER NOT NULL CHECK(peak_height>=0),
        peak_hash TEXT NOT NULL,
        PRIMARY KEY(commit_sequence,peak_ordinal),
        UNIQUE(commit_sequence,peak_height),
        FOREIGN KEY(commit_sequence) REFERENCES operational_commits(commit_sequence),
        FOREIGN KEY(peak_hash) REFERENCES operational_mmr_nodes(node_hash)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE operational_anchor_intents(
        intent_id TEXT PRIMARY KEY CHECK(length(intent_id)=64),
        commit_id TEXT NOT NULL UNIQUE,
        anchor_sequence INTEGER NOT NULL UNIQUE CHECK(anchor_sequence>=2),
        state_root TEXT NOT NULL CHECK(length(state_root)=64),
        status TEXT NOT NULL CHECK(status='sqlite_committed'),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        FOREIGN KEY(commit_id) REFERENCES operational_commits(commit_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE operational_anchor_finalizations(
        finalization_id TEXT PRIMARY KEY CHECK(length(finalization_id)=64),
        intent_id TEXT NOT NULL UNIQUE,
        anchor_sequence INTEGER NOT NULL UNIQUE CHECK(anchor_sequence>=2),
        state_root TEXT NOT NULL CHECK(length(state_root)=64),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
        FOREIGN KEY(intent_id) REFERENCES operational_anchor_intents(intent_id)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX idx_v3_evidence_scope ON evidence_records(workspace_id,mission_id)",
    "CREATE INDEX idx_v3_claims_scope ON claims(workspace_id,mission_id)",
    "CREATE INDEX idx_v3_requests_scope ON action_requests(workspace_id,mission_id)",
    "CREATE INDEX idx_v3_receipts_request ON action_receipts(request_id)",
    "CREATE INDEX idx_v3_projections_scope ON projections(workspace_id,mission_id,projection_type)",
    "CREATE INDEX idx_v3_events_chain ON event_envelopes(workspace_id,correlation_id,event_sequence)",
)

_FROZEN_AUTHORITY_TABLES = frozenset({"workspaces", "mission_contexts"})
_IMMUTABLE_V3_TABLES = (
    "workspaces",
    "mission_contexts",
    "evidence_records",
    "claims",
    "claim_evidence_links",
    "claim_relations",
    "action_requests",
    "action_receipts",
    "action_state_history",
    "projections",
    "event_envelopes",
    "event_chain_history",
    "event_chain_heads",
    "integrity_commits",
    "anchor_intents",
    "anchor_finalizations",
    "operational_commits",
    "operational_commit_entries",
    "operational_entry_merkle_nodes",
    "operational_mmr_nodes",
    "operational_mmr_edges",
    "operational_mmr_peaks",
    "operational_anchor_intents",
    "operational_anchor_finalizations",
)

_V3_GUARD_STATEMENTS = tuple(
    statement
    for table, deny_insert in (
        *((target, True) for _source, target in _LEGACY_RENAMES),
        *((table, table in _FROZEN_AUTHORITY_TABLES) for table in _IMMUTABLE_V3_TABLES),
    )
    for statement in _immutable_triggers(table, deny_insert=deny_insert)
) + tuple(
    f"CREATE TRIGGER deny_artifact_index_{operation.lower()}_after_genesis "
    f"BEFORE {operation} ON artifact_index "
    "WHEN EXISTS(SELECT 1 FROM operational_commits) "
    "BEGIN SELECT RAISE(ABORT,'artifact_index is frozen by operational genesis'); END"
    for operation in ("INSERT", "UPDATE", "DELETE")
)

_V3_SCHEMA_STATEMENTS = (
    *_RENAME_STATEMENTS,
    *_V3_TABLE_STATEMENTS,
)

_V3_SCOPE_TRIGGER_STATEMENTS = (
    """
    CREATE TRIGGER validate_evidence_artifact_scope BEFORE INSERT ON evidence_records
    WHEN NEW.artifact_id IS NOT NULL
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM artifact_index a
        WHERE a.artifact_id=NEW.artifact_id AND a.workspace_id=NEW.workspace_id
      ) THEN RAISE(ABORT,'evidence/artifact workspace mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_claim_evidence_scope BEFORE INSERT ON claim_evidence_links
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM claims c JOIN evidence_records e
          ON e.evidence_id=NEW.evidence_id
         AND e.workspace_id=NEW.workspace_id
        WHERE c.claim_id=NEW.claim_id
          AND c.workspace_id=NEW.workspace_id
          AND ((c.mission_id=NEW.mission_id) OR (c.mission_id IS NULL AND NEW.mission_id IS NULL))
          AND ((e.mission_id=NEW.mission_id) OR (e.mission_id IS NULL AND NEW.mission_id IS NULL))
      ) THEN RAISE(ABORT,'claim/evidence scope mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_claim_relation_scope BEFORE INSERT ON claim_relations
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM claims s JOIN claims t
          ON t.claim_id=NEW.target_claim_id
         AND t.workspace_id=NEW.workspace_id
        WHERE s.claim_id=NEW.source_claim_id
          AND s.workspace_id=NEW.workspace_id
          AND ((s.mission_id=NEW.mission_id) OR (s.mission_id IS NULL AND NEW.mission_id IS NULL))
          AND ((t.mission_id=NEW.mission_id) OR (t.mission_id IS NULL AND NEW.mission_id IS NULL))
      ) THEN RAISE(ABORT,'claim relation scope mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_receipt_scope BEFORE INSERT ON action_receipts
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM action_requests q
        WHERE q.request_id=NEW.request_id AND q.workspace_id=NEW.workspace_id
          AND ((q.mission_id=NEW.mission_id) OR (q.mission_id IS NULL AND NEW.mission_id IS NULL))
      ) THEN RAISE(ABORT,'receipt/request scope mismatch') END;
      SELECT CASE WHEN NEW.supersedes_receipt_id IS NOT NULL AND NOT EXISTS(
        SELECT 1 FROM action_receipts prior
        WHERE prior.receipt_id=NEW.supersedes_receipt_id
          AND prior.request_id=NEW.request_id
          AND prior.workspace_id=NEW.workspace_id
          AND ((prior.mission_id=NEW.mission_id) OR (prior.mission_id IS NULL AND NEW.mission_id IS NULL))
      ) THEN RAISE(ABORT,'receipt supersedes scope/order mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_action_state_scope BEFORE INSERT ON action_state_history
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM action_requests q
        WHERE q.request_id=NEW.request_id AND q.workspace_id=NEW.workspace_id
          AND ((q.mission_id=NEW.mission_id) OR (q.mission_id IS NULL AND NEW.mission_id IS NULL))
      ) THEN RAISE(ABORT,'action state/request scope mismatch') END;
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM event_envelopes e
        WHERE e.event_id=NEW.source_event_id
          AND e.workspace_id=NEW.workspace_id
          AND e.entity_type=CASE WHEN NEW.source_receipt_id IS NULL
                                 THEN 'action_request' ELSE 'action_receipt' END
          AND e.entity_id=COALESCE(NEW.source_receipt_id,NEW.request_id)
          AND ((e.mission_id=NEW.mission_id) OR (e.mission_id IS NULL AND NEW.mission_id IS NULL))
      ) THEN RAISE(ABORT,'action state/source event mismatch') END;
      SELECT CASE WHEN NEW.source_receipt_id IS NOT NULL AND NOT EXISTS(
        SELECT 1 FROM action_receipts r
        WHERE r.receipt_id=NEW.source_receipt_id
          AND r.request_id=NEW.request_id
          AND r.workspace_id=NEW.workspace_id
          AND ((r.mission_id=NEW.mission_id) OR (r.mission_id IS NULL AND NEW.mission_id IS NULL))
      ) THEN RAISE(ABORT,'action state/source receipt mismatch') END;
      SELECT CASE WHEN NEW.source_receipt_id IS NULL AND NOT EXISTS(
        SELECT 1 FROM action_requests q WHERE q.request_id=NEW.request_id
          AND q.record_sha256=NEW.request_record_sha256
      ) THEN RAISE(ABORT,'initial action state request digest mismatch') END;
      SELECT CASE WHEN NEW.source_receipt_id IS NOT NULL AND NOT EXISTS(
        SELECT 1 FROM action_receipts r WHERE r.receipt_id=NEW.source_receipt_id
          AND r.parent_request_sha256=NEW.request_record_sha256
      ) THEN RAISE(ABORT,'action state request digest mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_event_entity_scope BEFORE INSERT ON event_envelopes
    BEGIN
      SELECT CASE NEW.entity_type
        WHEN 'evidence' THEN CASE WHEN NOT EXISTS(
          SELECT 1 FROM evidence_records x WHERE x.evidence_id=NEW.entity_id
            AND x.workspace_id=NEW.workspace_id
            AND x.record_sha256=NEW.entity_sha256
            AND ((x.mission_id=NEW.mission_id) OR (x.mission_id IS NULL AND NEW.mission_id IS NULL))
        ) THEN RAISE(ABORT,'event/evidence scope mismatch') END
        WHEN 'claim' THEN CASE WHEN NOT EXISTS(
          SELECT 1 FROM claims x WHERE x.claim_id=NEW.entity_id
            AND x.workspace_id=NEW.workspace_id
            AND x.record_sha256=NEW.entity_sha256
            AND ((x.mission_id=NEW.mission_id) OR (x.mission_id IS NULL AND NEW.mission_id IS NULL))
        ) THEN RAISE(ABORT,'event/claim scope mismatch') END
        WHEN 'action_request' THEN CASE WHEN NOT EXISTS(
          SELECT 1 FROM action_requests x WHERE x.request_id=NEW.entity_id
            AND x.workspace_id=NEW.workspace_id
            AND x.record_sha256=NEW.entity_sha256
            AND ((x.mission_id=NEW.mission_id) OR (x.mission_id IS NULL AND NEW.mission_id IS NULL))
        ) THEN RAISE(ABORT,'event/request scope mismatch') END
        WHEN 'action_receipt' THEN CASE WHEN NOT EXISTS(
          SELECT 1 FROM action_receipts x WHERE x.receipt_id=NEW.entity_id
            AND x.workspace_id=NEW.workspace_id
            AND x.record_sha256=NEW.entity_sha256
            AND ((x.mission_id=NEW.mission_id) OR (x.mission_id IS NULL AND NEW.mission_id IS NULL))
        ) THEN RAISE(ABORT,'event/receipt scope mismatch') END
      END;
      SELECT CASE WHEN NEW.entity_type='action_receipt' AND NOT EXISTS(
        SELECT 1 FROM action_receipts r
        WHERE r.receipt_id=NEW.entity_id AND r.request_id=NEW.parent_entity_id
          AND r.parent_request_sha256=NEW.parent_entity_sha256
      ) THEN RAISE(ABORT,'receipt event parent mismatch') END;
      SELECT CASE WHEN NEW.entity_type<>'action_receipt' AND NEW.parent_entity_id IS NOT NULL
        THEN RAISE(ABORT,'unexpected event parent') END;
    END
    """,
    """
    CREATE TRIGGER validate_event_chain_history BEFORE INSERT ON event_chain_history
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM event_envelopes e
        WHERE e.event_id=NEW.event_id AND e.workspace_id=NEW.workspace_id
          AND e.correlation_id=NEW.correlation_id
          AND e.event_sequence=NEW.event_sequence
          AND e.previous_hash=NEW.previous_hash AND e.event_hash=NEW.event_hash
      ) THEN RAISE(ABORT,'event history/envelope mismatch') END;
      SELECT CASE WHEN NEW.event_sequence=0 AND NEW.previous_hash<>'0000000000000000000000000000000000000000000000000000000000000000'
        THEN RAISE(ABORT,'event chain genesis mismatch') END;
      SELECT CASE WHEN NEW.event_sequence>0 AND NOT EXISTS(
        SELECT 1 FROM event_chain_history prior
        WHERE prior.workspace_id=NEW.workspace_id
          AND prior.correlation_id=NEW.correlation_id
          AND prior.event_sequence=NEW.event_sequence-1
          AND prior.event_hash=NEW.previous_hash
      ) THEN RAISE(ABORT,'event chain predecessor mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_event_chain_head BEFORE INSERT ON event_chain_heads
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM event_chain_history first
        WHERE first.workspace_id=NEW.workspace_id
          AND first.correlation_id=NEW.correlation_id
          AND first.event_sequence=0 AND first.event_id=NEW.first_event_id
      ) OR NOT EXISTS(
        SELECT 1 FROM event_chain_history last
        WHERE last.workspace_id=NEW.workspace_id
          AND last.correlation_id=NEW.correlation_id
          AND last.event_sequence=NEW.event_count-1
          AND last.event_id=NEW.last_event_id AND last.event_hash=NEW.head_hash
      ) OR EXISTS(
        SELECT 1 FROM event_chain_history extra
        WHERE extra.workspace_id=NEW.workspace_id
          AND extra.correlation_id=NEW.correlation_id
          AND extra.event_sequence=NEW.event_count
      )
      THEN RAISE(ABORT,'event head is not history-derived') END;
      SELECT CASE WHEN NEW.head_revision>0 AND NOT EXISTS(
        SELECT 1 FROM event_chain_heads prior
        WHERE prior.workspace_id=NEW.workspace_id
          AND prior.correlation_id=NEW.correlation_id
          AND prior.head_revision=NEW.head_revision-1
          AND prior.head_hash=NEW.previous_head_hash
          AND prior.event_count<NEW.event_count
      ) THEN RAISE(ABORT,'event head revision mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_projection_scope BEFORE INSERT ON projections
    BEGIN
      SELECT CASE WHEN NEW.source_event_id IS NOT NULL AND NOT EXISTS(
        SELECT 1 FROM event_envelopes e
        WHERE e.event_id=NEW.source_event_id AND e.workspace_id=NEW.workspace_id
          AND e.correlation_id=NEW.correlation_id
          AND ((e.mission_id=NEW.mission_id) OR (e.mission_id IS NULL AND NEW.mission_id IS NULL))
      ) THEN RAISE(ABORT,'projection/source event scope mismatch') END;
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM event_chain_heads h
        WHERE h.workspace_id=NEW.workspace_id
          AND h.correlation_id=NEW.correlation_id
          AND h.head_revision=NEW.head_revision
          AND h.event_count=NEW.event_count
          AND h.last_event_id=NEW.source_event_id
          AND h.head_hash=NEW.state_sha256
      ) THEN RAISE(ABORT,'projection is not event-head derived') END;
      SELECT CASE WHEN NEW.projection_revision>0 AND NOT EXISTS(
        SELECT 1 FROM projections prior
        WHERE prior.workspace_id=NEW.workspace_id
          AND prior.projection_id=NEW.projection_id
          AND prior.projection_revision=NEW.projection_revision-1
          AND prior.projection_type=NEW.projection_type
          AND prior.correlation_id=NEW.correlation_id
          AND prior.state_sha256=NEW.previous_state_sha256
          AND prior.head_revision<NEW.head_revision
          AND prior.event_count<NEW.event_count
          AND prior.created_at=NEW.created_at
          AND prior.updated_at<=NEW.updated_at
          AND ((prior.mission_id=NEW.mission_id) OR (prior.mission_id IS NULL AND NEW.mission_id IS NULL))
      ) THEN RAISE(ABORT,'projection revision mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_integrity_commit BEFORE INSERT ON integrity_commits
    BEGIN
      SELECT CASE WHEN NEW.database_instance_id<>(
        SELECT value FROM schema_metadata WHERE key='database_instance_id'
      ) OR NEW.schema_fingerprint<>(
        SELECT value FROM schema_metadata WHERE key='schema_fingerprint'
      ) THEN RAISE(ABORT,'integrity commit metadata mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_anchor_intent BEFORE INSERT ON anchor_intents
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM integrity_commits c WHERE c.commit_id=NEW.commit_id
          AND c.state_root=NEW.state_root
      ) THEN RAISE(ABORT,'anchor intent/commit mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_anchor_finalization BEFORE INSERT ON anchor_finalizations
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM anchor_intents i WHERE i.intent_id=NEW.intent_id
          AND i.anchor_sequence=NEW.anchor_sequence
          AND i.state_root=NEW.state_root
      ) THEN RAISE(ABORT,'anchor finalization/intent mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_operational_commit BEFORE INSERT ON operational_commits
    BEGIN
      SELECT CASE WHEN NEW.commit_sequence=1 AND NOT EXISTS(
        SELECT 1 FROM integrity_commits prior
        WHERE prior.commit_id=NEW.previous_commit_id
          AND prior.state_root=NEW.previous_state_root
          AND prior.database_instance_id=NEW.database_instance_id
          AND prior.schema_fingerprint=NEW.schema_fingerprint
      ) THEN RAISE(ABORT,'operational genesis commit mismatch') END;
      SELECT CASE WHEN NEW.commit_sequence>1 AND NOT EXISTS(
        SELECT 1 FROM operational_commits prior
        WHERE prior.commit_sequence=NEW.commit_sequence-1
          AND prior.commit_id=NEW.previous_commit_id
          AND prior.state_root=NEW.previous_state_root
          AND prior.database_instance_id=NEW.database_instance_id
          AND prior.schema_fingerprint=NEW.schema_fingerprint
          AND prior.canonical_row_count<NEW.canonical_row_count
          AND prior.event_count<NEW.event_count
      ) THEN RAISE(ABORT,'operational commit predecessor mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_operational_entry BEFORE INSERT ON operational_commit_entries
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM operational_commits c
        WHERE c.commit_id=NEW.commit_id AND NEW.entry_ordinal<c.entry_count
      ) THEN RAISE(ABORT,'operational commit entry mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_operational_anchor_intent BEFORE INSERT ON operational_anchor_intents
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM operational_commits c WHERE c.commit_id=NEW.commit_id
          AND c.state_root=NEW.state_root
      ) THEN RAISE(ABORT,'operational anchor intent/commit mismatch') END;
    END
    """,
    """
    CREATE TRIGGER validate_operational_anchor_finalization BEFORE INSERT ON operational_anchor_finalizations
    BEGIN
      SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM operational_anchor_intents i WHERE i.intent_id=NEW.intent_id
          AND i.anchor_sequence=NEW.anchor_sequence
          AND i.state_root=NEW.state_root
      ) THEN RAISE(ABORT,'operational anchor finalization/intent mismatch') END;
    END
    """,
)

_V3_FINALIZE_SCHEMA_STATEMENTS = (
    *_V3_SCOPE_TRIGGER_STATEMENTS,
    *_V3_GUARD_STATEMENTS,
)


def _reference_manifest_v3(*, include_behavior: bool = True) -> dict[str, object]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA legacy_alter_table=OFF")
        from core.control_plane import M1A_SCHEMA_STATEMENTS, M1B_SCHEMA_STATEMENTS

        for statement in (*M1A_SCHEMA_STATEMENTS, *M1B_SCHEMA_STATEMENTS):
            connection.execute(statement)
        for statement in (*_V3_SCHEMA_STATEMENTS, *_V3_FINALIZE_SCHEMA_STATEMENTS):
            connection.execute(statement)
        return _schema_manifest(connection, include_behavior=include_behavior)
    finally:
        connection.close()


def _ddl_sql_manifest(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (str(kind), str(name), str(owner), _canonical_sql_tokens(str(sql or "")))
        for kind, name, owner, sql in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE type IN ('table','index','view','trigger') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY type,name,tbl_name"
        ).fetchall()
    )


def _reference_ddl_sql_v3() -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA legacy_alter_table=OFF")
        from core.control_plane import M1A_SCHEMA_STATEMENTS, M1B_SCHEMA_STATEMENTS

        for statement in (*M1A_SCHEMA_STATEMENTS, *M1B_SCHEMA_STATEMENTS):
            connection.execute(statement)
        for statement in (*_V3_SCHEMA_STATEMENTS, *_V3_FINALIZE_SCHEMA_STATEMENTS):
            connection.execute(statement)
        return _ddl_sql_manifest(connection)
    finally:
        connection.close()


def _v3_fingerprint() -> str:
    return _schema_fingerprint(
        {
            "semantic": _reference_manifest_v3(include_behavior=False),
            "ddl_sql": _reference_ddl_sql_v3(),
        }
    )


def _actual_v3_fingerprint(connection: sqlite3.Connection) -> str:
    return _schema_fingerprint(
        {
            "semantic": _schema_manifest(connection, include_behavior=False),
            "ddl_sql": _ddl_sql_manifest(connection),
        }
    )


def _database_instance_id(metadata: Mapping[str, str]) -> str:
    existing = metadata.get("database_instance_id")
    if existing is not None:
        if not _DATABASE_INSTANCE_ID.fullmatch(existing):
            raise ControlPlaneV3IntegrityError("database_instance_id is invalid")
        return existing
    created_at = metadata.get("created_at", "")
    if not _valid_utc_timestamp(created_at):
        raise ControlPlaneV3IntegrityError("control-plane created_at is invalid")
    return "cp-" + hashlib.sha256(
        f"{SCHEMA_ID}\0{created_at}".encode("utf-8")
    ).hexdigest()


def _assert_v3_rename_contract(connection: sqlite3.Connection) -> None:
    if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
        raise ControlPlaneV3IntegrityError("foreign keys must remain enabled")
    if int(connection.execute("PRAGMA legacy_alter_table").fetchone()[0]) != 0:
        raise ControlPlaneV3IntegrityError("legacy ALTER TABLE behavior is forbidden")
    objects = {
        (str(kind), str(name)): str(owner)
        for kind, name, owner in connection.execute(
            "SELECT type,name,tbl_name FROM sqlite_master "
            "WHERE type IN ('table','index') AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    for source, target in _LEGACY_RENAMES:
        if ("table", target) not in objects or ("table", source) not in objects:
            raise ControlPlaneV3IntegrityError(
                f"v3 canonical/legacy table pair is incomplete: {source}"
            )
    legacy_indexes = {
        "idx_evidence_workspace_mission": "legacy_v2_evidence_records",
        "idx_claims_workspace_status": "legacy_v2_claims",
        "idx_action_requests_workspace_mission": "legacy_v2_action_requests",
        "idx_action_receipts_request": "legacy_v2_action_receipts",
        "idx_events_workspace_correlation": "legacy_v2_event_envelopes",
        "idx_projections_workspace_type": "legacy_v2_projections",
    }
    for index, target in legacy_indexes.items():
        if objects.get(("index", index)) != target:
            raise ControlPlaneV3IntegrityError(
                f"legacy index ownership changed: {index}"
            )
    receipt_targets = {
        str(row[2])
        for row in connection.execute(
            'PRAGMA foreign_key_list("legacy_v2_action_receipts")'
        ).fetchall()
    }
    if receipt_targets != {"legacy_v2_action_requests"}:
        raise ControlPlaneV3IntegrityError(
            "legacy receipt foreign key was not retargeted atomically"
        )


def _integrity_commit_id(
    database_instance_id: str,
    schema_fingerprint: str,
    root: _RootResult,
    created_at: str,
) -> str:
    payload = json.dumps(
        [
            database_instance_id,
            schema_fingerprint,
            root.digest,
            root.row_count,
            "sha256-type-tagged-v1",
            created_at,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-V3-INTEGRITY-COMMIT\0" + payload).hexdigest()


def _validate_v3_mappings_unchecked(connection: sqlite3.Connection) -> None:
    legacy_evidence = tuple(
        DomainLedgerRepository._evidence_from_row(row)
        for row in connection.execute(
            "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
            "payload_json,created_at FROM legacy_v2_evidence_records ORDER BY evidence_id"
        ).fetchall()
    )
    legacy_claims = tuple(
        DomainLedgerRepository._claim_from_row(row)
        for row in connection.execute(
            "SELECT claim_id,workspace_id,schema_version,verification_status,payload_json,"
            "created_at,updated_at FROM legacy_v2_claims ORDER BY claim_id"
        ).fetchall()
    )
    legacy_requests = tuple(
        DomainLedgerRepository._request_from_row(row)
        for row in connection.execute(
            "SELECT request_id,workspace_id,mission_id,schema_version,idempotency_key,status,"
            "payload_sha256,payload_json,created_at,updated_at "
            "FROM legacy_v2_action_requests ORDER BY request_id"
        ).fetchall()
    )
    legacy_receipts = tuple(
        DomainLedgerRepository._receipt_from_row(row)
        for row in connection.execute(
            "SELECT r.receipt_id,r.request_id,r.schema_version,r.outcome,r.payload_json,"
            "r.created_at,q.workspace_id FROM legacy_v2_action_receipts r "
            "JOIN legacy_v2_action_requests q ON q.request_id=r.request_id "
            "ORDER BY r.receipt_id"
        ).fetchall()
    )
    legacy_events = tuple(
        DomainLedgerRepository._event_from_row(row)
        for row in connection.execute(
            "SELECT event_id,workspace_id,mission_id,correlation_id,schema_version,event_type,"
            "payload_json,previous_hash,event_hash,created_at "
            "FROM legacy_v2_event_envelopes ORDER BY event_id"
        ).fetchall()
    )
    chains = _ordered_v2_events(legacy_events)
    evidence_payloads = dict(
        connection.execute(
            "SELECT evidence_id,payload_json FROM legacy_v2_evidence_records"
        ).fetchall()
    )
    claim_payloads = dict(
        connection.execute("SELECT claim_id,payload_json FROM legacy_v2_claims").fetchall()
    )
    request_payloads = dict(
        connection.execute(
            "SELECT request_id,payload_json FROM legacy_v2_action_requests"
        ).fetchall()
    )
    receipt_payloads = dict(
        connection.execute(
            "SELECT receipt_id,payload_json FROM legacy_v2_action_receipts"
        ).fetchall()
    )
    event_payloads = dict(
        connection.execute(
            "SELECT event_id,payload_json FROM legacy_v2_event_envelopes"
        ).fetchall()
    )
    receipt_events = {
        event.entity_id: event
        for chain in chains.values()
        for event in chain
        if event.entity_type == "action_receipt"
    }

    expected_evidence = [
        (
            record.evidence_id,
            record.workspace_id,
            record.mission_id,
            V3_SCHEMA_VERSION,
            record.correlation_id,
            record.source_kind,
            record.source_identity_sha256,
            record.content_sha256,
            record.artifact_id,
            record.credibility_bp,
            record.freshness,
            record.validity_seconds,
            record.observed_at,
            record.valid_until,
            record.access_license_sha256,
            record.input_sha256,
            _record_digest(record),
            evidence_payloads[record.evidence_id],
            record.created_at,
        )
        for record in legacy_evidence
    ]
    if connection.execute("SELECT * FROM evidence_records ORDER BY evidence_id").fetchall() != expected_evidence:
        raise ControlPlaneV3IntegrityError("v3 evidence typed mapping diverges")
    expected_claims = [
        (
            record.claim_id,
            record.workspace_id,
            record.mission_id,
            V3_SCHEMA_VERSION,
            record.correlation_id,
            record.claim_kind,
            record.statement_sha256,
            record.confidence_bp,
            record.verification_status,
            record.validity_seconds,
            record.valid_until,
            record.input_sha256,
            _record_digest(record),
            claim_payloads[record.claim_id],
            record.created_at,
        )
        for record in legacy_claims
    ]
    if connection.execute("SELECT * FROM claims ORDER BY claim_id").fetchall() != expected_claims:
        raise ControlPlaneV3IntegrityError("v3 claim typed mapping diverges")
    expected_requests = [
        (
            record.request_id,
            record.workspace_id,
            record.mission_id,
            V3_SCHEMA_VERSION,
            record.correlation_id,
            record.idempotency_key,
            record.connector,
            record.operation,
            record.target_sha256,
            record.payload_sha256,
            record.risk,
            record.approval_policy,
            record.data_class,
            1,
            record.verification_plan_sha256,
            record.rollback_plan_sha256,
            record.input_sha256,
            _record_digest(replace(record, status="proposed", updated_at=record.created_at)),
            request_payloads[record.request_id],
            record.created_at,
        )
        for record in legacy_requests
    ]
    if connection.execute("SELECT * FROM action_requests ORDER BY request_id").fetchall() != expected_requests:
        raise ControlPlaneV3IntegrityError("v3 request typed mapping diverges")
    requests_by_id = {record.request_id: record for record in legacy_requests}
    expected_receipts = sorted(
        [
            (
                record.receipt_id,
                record.request_id,
                record.workspace_id,
                requests_by_id[record.request_id].mission_id,
                V3_SCHEMA_VERSION,
                record.correlation_id,
                record.outcome,
                record.provider_request_sha256,
                record.before_sha256,
                record.after_sha256,
                record.output_sha256,
                record.verification_sha256,
                record.rollback_sha256,
                record.error_class,
                record.supersedes_receipt_id,
                int(record.reconciliation),
                record.input_sha256,
                _record_digest(record),
                receipt_events[record.receipt_id].parent_entity_sha256,
                record.observed_at,
                receipt_payloads[record.receipt_id],
                record.created_at,
            )
            for record in legacy_receipts
        ],
        key=lambda row: row[0],
    )
    if connection.execute("SELECT * FROM action_receipts ORDER BY receipt_id").fetchall() != expected_receipts:
        raise ControlPlaneV3IntegrityError("v3 receipt typed mapping diverges")

    expected_events = []
    expected_history = []
    expected_heads = []
    for (workspace_id, correlation_id), chain in sorted(chains.items()):
        for sequence, event in enumerate(chain):
            expected_events.append(
                (
                    event.event_id,
                    event.workspace_id,
                    event.mission_id,
                    event.correlation_id,
                    sequence,
                    V3_SCHEMA_VERSION,
                    event.event_type,
                    event.entity_type,
                    event.entity_id,
                    event.entity_sha256,
                    event.parent_entity_id,
                    event.parent_entity_sha256,
                    event.previous_hash,
                    event.event_hash,
                    event_payloads[event.event_id],
                    event.created_at,
                )
            )
            expected_history.append(
                (
                    workspace_id,
                    correlation_id,
                    sequence,
                    event.event_id,
                    event.previous_hash,
                    event.event_hash,
                )
            )
        expected_heads.append(
            (
                workspace_id,
                correlation_id,
                0,
                len(chain),
                chain[-1].event_hash,
                chain[0].event_id,
                chain[-1].event_id,
                None,
            )
        )
    if connection.execute("SELECT * FROM event_envelopes ORDER BY event_id").fetchall() != sorted(expected_events):
        raise ControlPlaneV3IntegrityError("v3 event envelope mapping diverges")
    if connection.execute(
        "SELECT * FROM event_chain_history ORDER BY workspace_id,correlation_id,event_sequence"
    ).fetchall() != expected_history:
        raise ControlPlaneV3IntegrityError("v3 event history mapping diverges")
    if connection.execute(
        "SELECT * FROM event_chain_heads ORDER BY workspace_id,correlation_id,head_revision"
    ).fetchall() != expected_heads:
        raise ControlPlaneV3IntegrityError("v3 event head mapping diverges")

    expected_projections = []
    for (
        projection_id,
        workspace_id,
        _version,
        projection_type,
        payload_json,
        created_at,
        updated_at,
    ) in connection.execute(
        "SELECT projection_id,workspace_id,schema_version,projection_type,payload_json,"
        "created_at,updated_at FROM legacy_v2_projections ORDER BY projection_id"
    ).fetchall():
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise ControlPlaneV3IntegrityError("legacy projection payload is invalid")
        correlation_id = payload.get("correlation_id")
        chain = chains.get((workspace_id, correlation_id), ())
        if (
            projection_type != "m2a_event_chain_head"
            or not chain
            or payload.get("event_count") != len(chain)
            or payload.get("head_hash") != chain[-1].event_hash
            or created_at != chain[0].created_at
            or updated_at != chain[-1].created_at
        ):
            raise ControlPlaneV3IntegrityError("legacy projection/head mapping diverges")
        values = (
            projection_id,
            0,
            workspace_id,
            chain[-1].mission_id,
            V3_SCHEMA_VERSION,
            projection_type,
            correlation_id,
            0,
            len(chain),
            chain[-1].event_id,
            chain[-1].event_hash,
            None,
            payload_json,
            created_at,
            updated_at,
        )
        expected_projections.append(
            (*values[:12], _typed_record_digest("projection", values), *values[12:])
        )
    actual_projections = connection.execute(
        "SELECT * FROM projections ORDER BY workspace_id,projection_id,projection_revision"
    ).fetchall()
    if actual_projections != sorted(expected_projections, key=lambda row: (row[2], row[0], row[1])):
        raise ControlPlaneV3IntegrityError("v3 projection typed mapping diverges")

    for table, key, records in (
        ("evidence_records", "evidence_id", legacy_evidence),
        ("claims", "claim_id", legacy_claims),
        ("action_receipts", "receipt_id", legacy_receipts),
    ):
        actual = dict(
            connection.execute(
                f'SELECT "{key}",record_sha256 FROM "{table}"'
            ).fetchall()
        )
        expected = {getattr(record, key): _record_digest(record) for record in records}
        if actual != expected:
            raise ControlPlaneV3IntegrityError(f"v3 {table} record mapping diverges")
    request_hashes = dict(
        connection.execute("SELECT request_id,record_sha256 FROM action_requests")
    )
    expected_request_hashes = {
        record.request_id: _record_digest(
            replace(record, status="proposed", updated_at=record.created_at)
        )
        for record in legacy_requests
    }
    if request_hashes != expected_request_hashes:
        raise ControlPlaneV3IntegrityError("v3 request record mapping diverges")

    expected_links = sorted(
        (
            claim.claim_id,
            evidence_id,
            claim.workspace_id,
            claim.mission_id,
            ordinal,
        )
        for claim in legacy_claims
        for ordinal, evidence_id in enumerate(claim.evidence_ids)
    )
    actual_links = connection.execute(
        "SELECT claim_id,evidence_id,workspace_id,mission_id,link_ordinal "
        "FROM claim_evidence_links ORDER BY claim_id,link_ordinal"
    ).fetchall()
    if actual_links != expected_links:
        raise ControlPlaneV3IntegrityError("v3 claim/evidence normalization diverges")

    claims_by_id = {claim.claim_id: claim for claim in legacy_claims}
    expected_relation_keys: set[tuple[str, str, str, str, str | None]] = set()
    for claim in legacy_claims:
        for target in claim.contradiction_claim_ids:
            source, destination = sorted((claim.claim_id, target))
            expected_relation_keys.add(
                (source, destination, "contradicts", claim.workspace_id, claim.mission_id)
            )
        if claim.supersedes_claim_id is not None:
            expected_relation_keys.add(
                (
                    claim.claim_id,
                    claim.supersedes_claim_id,
                    "supersedes",
                    claim.workspace_id,
                    claim.mission_id,
                )
            )
    expected_relations = sorted(
        [
        (
            _relation_id(workspace_id, mission_id, source, target, kind),
            workspace_id,
            mission_id,
            source,
            target,
            kind,
            claims_by_id[source].created_at,
        )
        for source, target, kind, workspace_id, mission_id in expected_relation_keys
        ],
        key=lambda row: row[0],
    )
    actual_relations = connection.execute(
        "SELECT relation_id,workspace_id,mission_id,source_claim_id,target_claim_id,"
        "relation_kind,created_at FROM claim_relations ORDER BY relation_id"
    ).fetchall()
    if actual_relations != expected_relations:
        raise ControlPlaneV3IntegrityError("v3 claim relation normalization diverges")

    receipt_by_id = {record.receipt_id: record for record in legacy_receipts}
    expected_states = []
    for request in legacy_requests:
        chain = chains.get((request.workspace_id, request.correlation_id), ())
        related = tuple(
            event
            for event in chain
            if (event.entity_type == "action_request" and event.entity_id == request.request_id)
            or (
                event.entity_type == "action_receipt"
                and event.parent_entity_id == request.request_id
            )
        )
        if not related or related[0].entity_type != "action_request":
            raise ControlPlaneV3IntegrityError("legacy request event history is incomplete")
        derived = [
            (
                "proposed",
                related[0].event_id,
                None,
                related[0].entity_sha256,
                related[0].created_at,
            )
        ]
        for event in related[1:]:
            receipt = receipt_by_id[event.entity_id]
            state = (
                "reconciliation_required"
                if receipt.outcome in {"partial", "unknown"}
                else "recorded"
            )
            derived.append(
                (
                    state,
                    event.event_id,
                    receipt.receipt_id,
                    event.parent_entity_sha256,
                    event.created_at,
                )
            )
        if derived[-1][0] != request.status:
            raise ControlPlaneV3IntegrityError("legacy request terminal state diverges")
        for sequence, (state, event_id, receipt_id, request_hash, created_at) in enumerate(
            derived
        ):
            values = (
                request.request_id,
                sequence,
                request.workspace_id,
                request.mission_id,
                state,
                event_id,
                receipt_id,
                request_hash,
                created_at,
            )
            expected_states.append(
                (*values[:8], _typed_record_digest("action_state", values), values[8])
            )
    actual_states = connection.execute(
        "SELECT request_id,state_sequence,workspace_id,mission_id,state,source_event_id,"
        "source_receipt_id,request_record_sha256,record_sha256,created_at "
        "FROM action_state_history ORDER BY request_id,state_sequence"
    ).fetchall()
    if actual_states != sorted(expected_states):
        raise ControlPlaneV3IntegrityError("v3 action-state derivation diverges")

    entity_tables = {
        "evidence": ("evidence_records", "evidence_id"),
        "claim": ("claims", "claim_id"),
        "action_request": ("action_requests", "request_id"),
        "action_receipt": ("action_receipts", "receipt_id"),
    }
    events = connection.execute(
        "SELECT event_id,entity_type,entity_id,entity_sha256,parent_entity_id,"
        "parent_entity_sha256 FROM event_envelopes ORDER BY event_id"
    ).fetchall()
    for _event_id, entity_type, entity_id, entity_hash, parent_id, parent_hash in events:
        table, key = entity_tables[str(entity_type)]
        row = connection.execute(
            f'SELECT record_sha256 FROM "{table}" WHERE "{key}"=?', (entity_id,)
        ).fetchone()
        if row != (entity_hash,):
            raise ControlPlaneV3IntegrityError("v3 event entity digest diverges")
        if entity_type == "action_receipt":
            receipt = connection.execute(
                "SELECT request_id,parent_request_sha256 FROM action_receipts "
                "WHERE receipt_id=?",
                (entity_id,),
            ).fetchone()
            if receipt != (parent_id, parent_hash):
                raise ControlPlaneV3IntegrityError("v3 receipt parent digest diverges")
        elif parent_id is not None or parent_hash is not None:
            raise ControlPlaneV3IntegrityError("v3 non-receipt event has a parent")

    for row in connection.execute(
        "SELECT request_id,state_sequence,workspace_id,mission_id,state,source_event_id,"
        "source_receipt_id,request_record_sha256,record_sha256,created_at "
        "FROM action_state_history ORDER BY request_id,state_sequence"
    ).fetchall():
        expected = _typed_record_digest("action_state", (*row[:8], row[9]))
        if row[8] != expected:
            raise ControlPlaneV3IntegrityError("v3 action-state digest diverges")

    for row in connection.execute(
        "SELECT projection_id,projection_revision,workspace_id,mission_id,schema_version,"
        "projection_type,correlation_id,head_revision,event_count,source_event_id,state_sha256,"
        "previous_state_sha256,record_sha256,legacy_payload_json,created_at,updated_at "
        "FROM projections ORDER BY workspace_id,projection_id,projection_revision"
    ).fetchall():
        values = (*row[:12], row[13], row[14], row[15])
        if row[12] != _typed_record_digest("projection", values):
            raise ControlPlaneV3IntegrityError("v3 projection digest diverges")
        head = connection.execute(
            "SELECT event_count,last_event_id,head_hash FROM event_chain_heads "
            "WHERE workspace_id=? AND correlation_id=? AND head_revision=?",
            (row[2], row[6], row[7]),
        ).fetchone()
        if head != (row[8], row[9], row[10]):
            raise ControlPlaneV3IntegrityError("v3 projection/head mapping diverges")

    for source, target in _LEGACY_RENAMES:
        legacy_count = int(connection.execute(f'SELECT count(*) FROM "{target}"').fetchone()[0])
        canonical_count = int(connection.execute(f'SELECT count(*) FROM "{source}"').fetchone()[0])
        if legacy_count != canonical_count:
            raise ControlPlaneV3IntegrityError(
                f"v3 canonical row count diverges from {source} legacy history"
            )


def _validate_v3_mappings(connection: sqlite3.Connection) -> None:
    try:
        _validate_v3_mappings_unchecked(connection)
    except ControlPlaneV3Error:
        raise
    except (DomainLedgerError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ControlPlaneV3IntegrityError(
            "legacy-to-v3 mapping data is malformed"
        ) from None


def _validate_v3_exact(
    connection: sqlite3.Connection, *, require_finalization: bool = True
) -> V3Status:
    try:
        if int(connection.execute("PRAGMA application_id").fetchone()[0]) != APPLICATION_ID:
            raise ControlPlaneV3IntegrityError("v3 application_id is invalid")
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) != V3_SCHEMA_VERSION:
            raise ControlPlaneV3IntegrityError("v3 user_version is invalid")
        if _schema_manifest(connection, include_behavior=False) != _reference_manifest_v3(
            include_behavior=False
        ):
            raise ControlPlaneV3IntegrityError("v3 semantic schema manifest diverges")
        if _ddl_sql_manifest(connection) != _reference_ddl_sql_v3():
            raise ControlPlaneV3IntegrityError("v3 exact DDL SQL manifest diverges")
        _assert_v3_rename_contract(connection)
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ControlPlaneV3IntegrityError("v3 SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ControlPlaneV3IntegrityError("v3 foreign-key integrity failed")
        metadata_rows = connection.execute(
            "SELECT key,value FROM schema_metadata ORDER BY key"
        ).fetchall()
        metadata = dict(metadata_rows)
        keys = {
            "schema_id",
            "schema_version",
            "schema_fingerprint",
            "created_at",
            "database_instance_id",
        }
        fingerprint = _v3_fingerprint()
        if (
            len(metadata_rows) != len(keys)
            or set(metadata) != keys
            or metadata.get("schema_id") != SCHEMA_ID
            or metadata.get("schema_version") != str(V3_SCHEMA_VERSION)
            or metadata.get("schema_fingerprint") != fingerprint
            or not _valid_utc_timestamp(metadata.get("created_at", ""))
            or metadata.get("database_instance_id") != _database_instance_id(metadata)
        ):
            raise ControlPlaneV3IntegrityError("v3 schema metadata is invalid")
        journal = connection.execute(
            "SELECT migration_id,schema_from,schema_to,status,applied_at,schema_fingerprint "
            "FROM migration_journal ORDER BY schema_to"
        ).fetchall()
        m1a_fingerprint = _schema_fingerprint(
            _reference_manifest(version=M1A_SCHEMA_VERSION)
        )
        v2_fingerprint = _schema_fingerprint(_reference_manifest(version=V2_SCHEMA_VERSION))
        if len(journal) != 3:
            raise ControlPlaneV3IntegrityError("v3 migration journal length is invalid")
        expected = (
            (MIGRATION_ID, 0, M1A_SCHEMA_VERSION, "applied", m1a_fingerprint),
            (M1B_MIGRATION_ID, M1A_SCHEMA_VERSION, V2_SCHEMA_VERSION, "applied", v2_fingerprint),
            (M2B_MIGRATION_ID, V2_SCHEMA_VERSION, V3_SCHEMA_VERSION, "applied", fingerprint),
        )
        for row, contract in zip(journal, expected, strict=True):
            if (
                (row[0], row[1], row[2], row[3], row[5]) != contract
                or not _valid_utc_timestamp(str(row[4]))
            ):
                raise ControlPlaneV3IntegrityError("v3 migration journal is invalid")
        if journal[0][4] != metadata["created_at"]:
            raise ControlPlaneV3IntegrityError("v3 M1 creation identity changed")

        _validate_v3_mappings(connection)
        root = _stream_state_root(connection)
        bookkeeping = _validate_bookkeeping(
            connection,
            database_id=metadata["database_instance_id"],
            fingerprint=fingerprint,
            root=root,
            allow_projected_finalization=not require_finalization,
        )
        sequence = bookkeeping.intent[2]
        return V3Status(
            metadata["database_instance_id"],
            V3_SCHEMA_VERSION,
            fingerprint,
            root.digest,
            root.row_count,
            sequence,
            require_finalization,
        )
    except ControlPlaneV3Error:
        raise
    except sqlite3.DatabaseError as exc:
        raise ControlPlaneV3IntegrityError("v3 database is unreadable") from exc


def _encode_value(value: object) -> bytes:
    if value is None:
        return b"N"
    if type(value) is int:
        payload = str(value).encode("ascii")
        return b"I" + len(payload).to_bytes(8, "big") + payload
    if type(value) is float:
        raise ControlPlaneV3IntegrityError("floating SQLite values are not root-canonical")
    if isinstance(value, bytes):
        return b"B" + len(value).to_bytes(8, "big") + value
    if isinstance(value, str):
        payload = value.encode("utf-8", errors="strict")
        return b"S" + len(payload).to_bytes(8, "big") + payload
    raise ControlPlaneV3IntegrityError("unsupported SQLite value in state root")


def _bookkeeping_digest(
    rows: tuple[tuple[str, tuple[str, ...], tuple[tuple[object, ...], ...]], ...]
) -> bytes:
    """Canonically bind excluded rows into the external HMAC anchor.

    The namespace, table/column names, table cardinality and type-tagged values
    (including NULL) are all part of the digest domain.  Eight 32-bit limbs fit
    the ledger-anchor entity-count contract without truncating SHA-256.
    """

    digest = hashlib.sha256(_BOOKKEEPING_BINDING_NAMESPACE)
    for table, columns, table_rows in rows:
        table_bytes = table.encode("ascii")
        digest.update(b"T" + len(table_bytes).to_bytes(4, "big") + table_bytes)
        digest.update(b"K" + len(columns).to_bytes(4, "big"))
        for column in columns:
            column_bytes = column.encode("ascii")
            digest.update(
                b"C" + len(column_bytes).to_bytes(4, "big") + column_bytes
            )
        digest.update(b"Q" + len(table_rows).to_bytes(8, "big"))
        for row in table_rows:
            if len(row) != len(columns):
                raise ControlPlaneV3IntegrityError(
                    "v3 bookkeeping row shape is invalid"
                )
            digest.update(b"R")
            for value in row:
                digest.update(_encode_value(value))
    return digest.digest()


def _bookkeeping_anchor_counts(digest: bytes) -> tuple[tuple[str, int], ...]:
    if len(digest) != 32:
        raise ControlPlaneV3IntegrityError("v3 bookkeeping digest is invalid")
    return tuple(
        (
            f"{_BOOKKEEPING_LIMB_PREFIX}{index:02d}",
            int.from_bytes(digest[offset : offset + 4], "big"),
        )
        for index, offset in enumerate(range(0, len(digest), 4))
    )


def _validate_bookkeeping(
    connection: sqlite3.Connection,
    *,
    database_id: str,
    fingerprint: str,
    root: _RootResult,
    allow_projected_finalization: bool,
) -> _BookkeepingState:
    selected: dict[str, tuple[tuple[object, ...], ...]] = {}
    for table, columns in _BOOKKEEPING_COLUMNS:
        quoted_columns = ",".join(f'"{column}"' for column in columns)
        selected[table] = tuple(
            connection.execute(
                f'SELECT {quoted_columns} FROM "{table}" ORDER BY 1'
            ).fetchall()
        )

    commits = selected["integrity_commits"]
    intents = selected["anchor_intents"]
    finalizations = selected["anchor_finalizations"]
    if len(commits) != 1:
        raise ControlPlaneV3IntegrityError(
            "v3 integrity commit cardinality is invalid"
        )
    if len(intents) != 1:
        raise ControlPlaneV3IntegrityError("v3 anchor intent cardinality is invalid")
    if len(finalizations) > 1:
        raise ControlPlaneV3IntegrityError(
            "v3 anchor finalization cardinality is invalid"
        )

    commit = commits[0]
    commit_created_at = commit[6]
    if not isinstance(commit_created_at, str) or not _valid_utc_timestamp(
        commit_created_at
    ):
        raise ControlPlaneV3IntegrityError("v3 integrity commit timestamp is invalid")
    expected_commit_id = _integrity_commit_id(
        database_id, fingerprint, root, commit_created_at
    )
    expected_commit = (
        expected_commit_id,
        database_id,
        fingerprint,
        root.digest,
        root.row_count,
        "sha256-type-tagged-v1",
        commit_created_at,
    )
    if commit != expected_commit:
        raise ControlPlaneV3IntegrityError("v3 state root is not committed exactly")

    intent = intents[0]
    intent_created_at = intent[5]
    sequence = intent[2]
    if (
        type(sequence) is not int
        or sequence < 1
        or not isinstance(intent_created_at, str)
        or not _valid_utc_timestamp(intent_created_at)
    ):
        raise ControlPlaneV3IntegrityError("v3 anchor intent fields are invalid")
    expected_intent_id = _intent_id(
        expected_commit_id, sequence, root.digest, intent_created_at
    )
    expected_intent = (
        expected_intent_id,
        expected_commit_id,
        sequence,
        root.digest,
        "sqlite_committed",
        intent_created_at,
    )
    if intent != expected_intent:
        raise ControlPlaneV3IntegrityError("v3 anchor intent is not exact")

    # The finalization timestamp is fixed before prepare and inherited from the
    # intent.  This lets the prepared external record authenticate the exact
    # future row without making the SQLite state root circular.
    finalization_created_at = intent_created_at
    expected_finalization = (
        _finalization_id(
            expected_intent_id,
            sequence,
            root.digest,
            finalization_created_at,
        ),
        expected_intent_id,
        sequence,
        root.digest,
        finalization_created_at,
    )
    if finalizations:
        if finalizations != (expected_finalization,):
            raise ControlPlaneV3IntegrityError("v3 anchor finalization is not exact")
        bound_finalizations = finalizations
    elif allow_projected_finalization:
        bound_finalizations = (expected_finalization,)
    else:
        raise ControlPlaneV3IntegrityError("v3 anchor finalization is missing")

    bound_rows = (
        (
            "integrity_commits",
            _BOOKKEEPING_COLUMNS[0][1],
            commits,
        ),
        ("anchor_intents", _BOOKKEEPING_COLUMNS[1][1], intents),
        (
            "anchor_finalizations",
            _BOOKKEEPING_COLUMNS[2][1],
            bound_finalizations,
        ),
    )
    anchor_counts = _bookkeeping_anchor_counts(_bookkeeping_digest(bound_rows))
    return _BookkeepingState(commit, intent, expected_finalization, anchor_counts)


def _root_tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        if row[0] not in _ANCHOR_EXCLUDED_TABLES
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    escaped = table.replace('"', '""')
    rows = connection.execute(f'PRAGMA table_xinfo("{escaped}")').fetchall()
    columns = tuple(str(row[1]) for row in rows if int(row[6]) == 0)
    if not columns:
        raise ControlPlaneV3IntegrityError(f"root table {table} has no stored columns")
    return columns


def _table_order(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    escaped = table.replace('"', '""')
    rows = connection.execute(f'PRAGMA table_xinfo("{escaped}")').fetchall()
    primary = tuple(str(row[1]) for row in sorted(rows, key=lambda item: int(item[5])) if row[5])
    return primary or tuple(str(row[1]) for row in rows if int(row[6]) == 0)


def _stream_state_root(connection: sqlite3.Connection) -> _RootResult:
    digest = hashlib.sha256(b"ONYX-CONTROL-PLANE-STATE-ROOT-V1\0")
    row_count = 0
    counts: list[tuple[str, int]] = []
    for table in _root_tables(connection):
        table_bytes = table.encode("utf-8")
        digest.update(b"T" + len(table_bytes).to_bytes(4, "big") + table_bytes)
        columns = _table_columns(connection, table)
        for column in columns:
            encoded = column.encode("utf-8")
            digest.update(b"C" + len(encoded).to_bytes(4, "big") + encoded)
        quoted = '"' + table.replace('"', '""') + '"'
        selected = ",".join('"' + name.replace('"', '""') + '"' for name in columns)
        ordered = ",".join(
            '"' + name.replace('"', '""') + '"' for name in _table_order(connection, table)
        )
        count = 0
        cursor = connection.execute(f"SELECT {selected} FROM {quoted} ORDER BY {ordered}")
        while True:
            rows = cursor.fetchmany(256)
            if not rows:
                break
            for row in rows:
                digest.update(b"R")
                for value in row:
                    digest.update(_encode_value(value))
                count += 1
                row_count += 1
        counts.append((table, count))
    return _RootResult(digest.hexdigest(), row_count, tuple(counts))


def _logical_table_digest(
    connection: sqlite3.Connection, table: str, *, logical_name: str | None = None
) -> tuple[str, str, int]:
    columns = _table_columns(connection, table)
    quoted = '"' + table.replace('"', '""') + '"'
    selected = ",".join('"' + name.replace('"', '""') + '"' for name in columns)
    ordered = ",".join(
        '"' + name.replace('"', '""') + '"' for name in _table_order(connection, table)
    )
    domain_name = table if logical_name is None else logical_name
    digest = hashlib.sha256(b"ONYX-V2-LEGACY-TABLE-V1\0" + domain_name.encode())
    count = 0
    for row in connection.execute(f"SELECT {selected} FROM {quoted} ORDER BY {ordered}"):
        for value in row:
            digest.update(_encode_value(value))
        count += 1
    return domain_name, digest.hexdigest(), count


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = connection.execute(
            "SELECT key,value FROM schema_metadata ORDER BY key"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise ControlPlaneV3IntegrityError("schema metadata is unreadable") from exc
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in rows):
        raise ControlPlaneV3IntegrityError("schema metadata representation is invalid")
    return dict(rows)


def _ordered_v2_events(events: Iterable[object]) -> dict[tuple[str, str], tuple[object, ...]]:
    grouped: dict[tuple[str, str], list[object]] = {}
    for event in events:
        grouped.setdefault((event.workspace_id, event.correlation_id), []).append(event)
    ordered: dict[tuple[str, str], tuple[object, ...]] = {}
    for key, items in grouped.items():
        children: dict[str, object] = {}
        for event in items:
            if event.previous_hash in children:
                raise ControlPlaneV3IntegrityError("v2 event chain forks")
            children[event.previous_hash] = event
        chain: list[object] = []
        cursor = _ZERO_HASH
        while cursor in children:
            event = children[cursor]
            chain.append(event)
            cursor = event.event_hash
        if len(chain) != len(items):
            raise ControlPlaneV3IntegrityError("v2 event chain is disconnected or cyclic")
        ordered[key] = tuple(chain)
    return ordered


def _topological_v2_receipts(
    receipts: Iterable[object],
    chains: Iterable[tuple[tuple[str, str], tuple[object, ...]]],
) -> tuple[object, ...]:
    """Order self-referencing receipts without trusting wall-clock timestamps."""
    records = {record.receipt_id: record for record in receipts}
    event_rank: dict[str, int] = {}
    ordinal = 0
    for _scope, chain in chains:
        for event in chain:
            if event.entity_type == "action_receipt":
                if event.entity_id in event_rank:
                    raise ControlPlaneV3IntegrityError("receipt has duplicate events")
                event_rank[event.entity_id] = ordinal
                ordinal += 1
    if set(event_rank) != set(records):
        raise ControlPlaneV3IntegrityError("receipt event coverage is ambiguous")
    remaining = set(records)
    emitted: set[str] = set()
    ordered: list[object] = []
    while remaining:
        ready = []
        for receipt_id in remaining:
            predecessor = records[receipt_id].supersedes_receipt_id
            if predecessor is None or predecessor in emitted:
                ready.append(receipt_id)
            elif predecessor not in records:
                raise ControlPlaneV3IntegrityError(
                    "receipt supersedes an unavailable receipt"
                )
        if not ready:
            raise ControlPlaneV3IntegrityError("receipt supersession graph is cyclic")
        ready.sort(key=lambda receipt_id: (event_rank[receipt_id], receipt_id))
        for receipt_id in ready:
            record = records[receipt_id]
            predecessor = record.supersedes_receipt_id
            if predecessor is not None:
                prior = records[predecessor]
                if (
                    prior.request_id != record.request_id
                    or prior.workspace_id != record.workspace_id
                ):
                    raise ControlPlaneV3IntegrityError(
                        "receipt supersession crosses request scope"
                    )
            remaining.remove(receipt_id)
            emitted.add(receipt_id)
            ordered.append(record)
    return tuple(ordered)


def _preflight_v2_unchecked(
    store: ControlPlaneStore, connection: sqlite3.Connection
) -> _V2History:
    ControlPlaneStore._validate_schema(connection)
    registry = WorkspaceRegistry(store, enabled=True)
    workspace_ids = tuple(
        row[0]
        for row in connection.execute(
            "SELECT workspace_id FROM workspaces ORDER BY workspace_id"
        ).fetchall()
        if row[0] != LEGACY_WORKSPACE_ID
    )
    for workspace_id in workspace_ids:
        repository = DomainLedgerRepository(
            registry, str(workspace_id), enabled=True
        )
        try:
            repository._verify_locked(connection)
        except DomainIntegrityError:
            raise ControlPlaneV3IntegrityError(
                "v2 domain ledger failed verification"
            ) from None

    evidence = tuple(
        DomainLedgerRepository._evidence_from_row(row)
        for row in connection.execute(
            "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
            "payload_json,created_at FROM evidence_records ORDER BY evidence_id"
        ).fetchall()
    )
    claims = tuple(
        DomainLedgerRepository._claim_from_row(row)
        for row in connection.execute(
            "SELECT claim_id,workspace_id,schema_version,verification_status,payload_json,"
            "created_at,updated_at FROM claims ORDER BY claim_id"
        ).fetchall()
    )
    requests = tuple(
        DomainLedgerRepository._request_from_row(row)
        for row in connection.execute(
            "SELECT request_id,workspace_id,mission_id,schema_version,idempotency_key,status,"
            "payload_sha256,payload_json,created_at,updated_at FROM action_requests "
            "ORDER BY request_id"
        ).fetchall()
    )
    receipts = tuple(
        DomainLedgerRepository._receipt_from_row(row)
        for row in connection.execute(
            "SELECT r.receipt_id,r.request_id,r.schema_version,r.outcome,r.payload_json,"
            "r.created_at,q.workspace_id FROM action_receipts r JOIN action_requests q "
            "ON q.request_id=r.request_id ORDER BY r.receipt_id"
        ).fetchall()
    )
    events = tuple(
        DomainLedgerRepository._event_from_row(row)
        for row in connection.execute(
            "SELECT event_id,workspace_id,mission_id,correlation_id,schema_version,event_type,"
            "payload_json,previous_hash,event_hash,created_at FROM event_envelopes "
            "ORDER BY event_id"
        ).fetchall()
    )
    chains = _ordered_v2_events(events)
    legacy = tuple(
        _logical_table_digest(connection, source) for source, _target in _LEGACY_RENAMES
    )
    return _V2History(
        evidence,
        claims,
        requests,
        receipts,
        events,
        tuple(sorted(chains.items())),
        legacy,
    )


def _preflight_v2(store: ControlPlaneStore, connection: sqlite3.Connection) -> _V2History:
    try:
        return _preflight_v2_unchecked(store, connection)
    except ControlPlaneV3Error:
        raise
    except (DomainLedgerError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ControlPlaneV3IntegrityError("v2 domain history is malformed") from None


def _relation_id(
    workspace_id: str,
    mission_id: str | None,
    source: str,
    target: str,
    kind: str,
) -> str:
    payload = json.dumps(
        [workspace_id, mission_id, source, target, kind],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-CLAIM-RELATION-V3\0" + payload).hexdigest()


def _typed_record_digest(kind: str, values: Iterable[object]) -> str:
    encoded = json.dumps(
        [kind, *values],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-V3-TYPED-RECORD\0" + encoded).hexdigest()


def _copy_v2_history(connection: sqlite3.Connection, history: _V2History) -> None:
    evidence_payloads = dict(
        connection.execute(
            "SELECT evidence_id,payload_json FROM legacy_v2_evidence_records"
        ).fetchall()
    )
    claim_payloads = dict(
        connection.execute("SELECT claim_id,payload_json FROM legacy_v2_claims").fetchall()
    )
    request_payloads = dict(
        connection.execute(
            "SELECT request_id,payload_json FROM legacy_v2_action_requests"
        ).fetchall()
    )
    receipt_payloads = dict(
        connection.execute(
            "SELECT receipt_id,payload_json FROM legacy_v2_action_receipts"
        ).fetchall()
    )
    event_payloads = dict(
        connection.execute(
            "SELECT event_id,payload_json FROM legacy_v2_event_envelopes"
        ).fetchall()
    )

    if any(record.workspace_id == LEGACY_WORKSPACE_ID for record in history.evidence):
        raise ControlPlaneV3IntegrityError("legacy-default evidence cannot migrate to v3")
    if any(record.workspace_id == LEGACY_WORKSPACE_ID for record in history.claims):
        raise ControlPlaneV3IntegrityError("legacy-default claims cannot migrate to v3")
    if any(record.workspace_id == LEGACY_WORKSPACE_ID for record in history.requests):
        raise ControlPlaneV3IntegrityError("legacy-default requests cannot migrate to v3")

    for record in history.evidence:
        connection.execute(
            "INSERT INTO evidence_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.evidence_id,
                record.workspace_id,
                record.mission_id,
                V3_SCHEMA_VERSION,
                record.correlation_id,
                record.source_kind,
                record.source_identity_sha256,
                record.content_sha256,
                record.artifact_id,
                record.credibility_bp,
                record.freshness,
                record.validity_seconds,
                record.observed_at,
                record.valid_until,
                record.access_license_sha256,
                record.input_sha256,
                _record_digest(record),
                evidence_payloads[record.evidence_id],
                record.created_at,
            ),
        )

    claims_by_id = {record.claim_id: record for record in history.claims}
    relation_keys: set[tuple[str, str, str, str, str | None]] = set()
    for record in history.claims:
        connection.execute(
            "INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.claim_id,
                record.workspace_id,
                record.mission_id,
                V3_SCHEMA_VERSION,
                record.correlation_id,
                record.claim_kind,
                record.statement_sha256,
                record.confidence_bp,
                record.verification_status,
                record.validity_seconds,
                record.valid_until,
                record.input_sha256,
                _record_digest(record),
                claim_payloads[record.claim_id],
                record.created_at,
            ),
        )
    for record in history.claims:
        for ordinal, evidence_id in enumerate(record.evidence_ids):
            connection.execute(
                "INSERT INTO claim_evidence_links VALUES(?,?,?,?,?)",
                (
                    record.claim_id,
                    evidence_id,
                    record.workspace_id,
                    record.mission_id,
                    ordinal,
                ),
            )
        for target in record.contradiction_claim_ids:
            source, destination = sorted((record.claim_id, target))
            relation_keys.add(
                (source, destination, "contradicts", record.workspace_id, record.mission_id)
            )
        if record.supersedes_claim_id is not None:
            relation_keys.add(
                (
                    record.claim_id,
                    record.supersedes_claim_id,
                    "supersedes",
                    record.workspace_id,
                    record.mission_id,
                )
            )
    for source, target, kind, workspace_id, mission_id in sorted(
        relation_keys, key=lambda value: tuple("" if item is None else item for item in value)
    ):
        source_record = claims_by_id.get(source)
        target_record = claims_by_id.get(target)
        if (
            source_record is None
            or target_record is None
            or source_record.workspace_id != workspace_id
            or target_record.workspace_id != workspace_id
            or source_record.mission_id != mission_id
            or target_record.mission_id != mission_id
        ):
            raise ControlPlaneV3IntegrityError("claim relation crosses canonical scope")
        connection.execute(
            "INSERT INTO claim_relations VALUES(?,?,?,?,?,?,?)",
            (
                _relation_id(workspace_id, mission_id, source, target, kind),
                workspace_id,
                mission_id,
                source,
                target,
                kind,
                source_record.created_at,
            ),
        )

    requests_by_id = {record.request_id: record for record in history.requests}
    for record in history.requests:
        connection.execute(
            "INSERT INTO action_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.request_id,
                record.workspace_id,
                record.mission_id,
                V3_SCHEMA_VERSION,
                record.correlation_id,
                record.idempotency_key,
                record.connector,
                record.operation,
                record.target_sha256,
                record.payload_sha256,
                record.risk,
                record.approval_policy,
                record.data_class,
                1,
                record.verification_plan_sha256,
                record.rollback_plan_sha256,
                record.input_sha256,
                _record_digest(
                    replace(record, status="proposed", updated_at=record.created_at)
                ),
                request_payloads[record.request_id],
                record.created_at,
            ),
        )

    receipt_by_id = {record.receipt_id: record for record in history.receipts}
    chain_map = dict(history.chains)
    receipt_order = _topological_v2_receipts(history.receipts, history.chains)
    receipt_events = {
        event.entity_id: event
        for _scope, chain in history.chains
        for event in chain
        if event.entity_type == "action_receipt"
    }
    for record in receipt_order:
        request = requests_by_id.get(record.request_id)
        if request is None:
            raise ControlPlaneV3IntegrityError("receipt request is unavailable")
        connection.execute(
            "INSERT INTO action_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.receipt_id,
                record.request_id,
                record.workspace_id,
                request.mission_id,
                V3_SCHEMA_VERSION,
                record.correlation_id,
                record.outcome,
                record.provider_request_sha256,
                record.before_sha256,
                record.after_sha256,
                record.output_sha256,
                record.verification_sha256,
                record.rollback_sha256,
                record.error_class,
                record.supersedes_receipt_id,
                int(record.reconciliation),
                record.input_sha256,
                _record_digest(record),
                receipt_events[record.receipt_id].parent_entity_sha256,
                record.observed_at,
                receipt_payloads[record.receipt_id],
                record.created_at,
            ),
        )

    for (workspace_id, correlation_id), chain in history.chains:
        for sequence, event in enumerate(chain):
            connection.execute(
                "INSERT INTO event_envelopes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.workspace_id,
                    event.mission_id,
                    event.correlation_id,
                    sequence,
                    V3_SCHEMA_VERSION,
                    event.event_type,
                    event.entity_type,
                    event.entity_id,
                    event.entity_sha256,
                    event.parent_entity_id,
                    event.parent_entity_sha256,
                    event.previous_hash,
                    event.event_hash,
                    event_payloads[event.event_id],
                    event.created_at,
                ),
            )
            connection.execute(
                "INSERT INTO event_chain_history VALUES(?,?,?,?,?,?)",
                (
                    workspace_id,
                    correlation_id,
                    sequence,
                    event.event_id,
                    event.previous_hash,
                    event.event_hash,
                ),
            )
        if chain:
            connection.execute(
                "INSERT INTO event_chain_heads VALUES(?,?,?,?,?,?,?,?)",
                (
                    workspace_id,
                    correlation_id,
                    0,
                    len(chain),
                    chain[-1].event_hash,
                    chain[0].event_id,
                    chain[-1].event_id,
                    None,
                ),
            )

    for (
        projection_id,
        workspace_id,
        _schema_version,
        projection_type,
        payload_json,
        created_at,
        updated_at,
    ) in connection.execute(
        "SELECT projection_id,workspace_id,schema_version,projection_type,payload_json,"
        "created_at,updated_at FROM legacy_v2_projections ORDER BY projection_id"
    ).fetchall():
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ControlPlaneV3IntegrityError("v2 projection payload is invalid") from exc
        if not isinstance(payload, dict):
            raise ControlPlaneV3IntegrityError("v2 projection payload must be an object")
        correlation_id = payload.get("correlation_id")
        head_hash = payload.get("head_hash")
        event_count = payload.get("event_count")
        chain = chain_map.get((workspace_id, correlation_id), ())
        if (
            projection_type != "m2a_event_chain_head"
            or not chain
            or type(event_count) is not int
            or event_count != len(chain)
            or head_hash != chain[-1].event_hash
            or created_at != chain[0].created_at
            or updated_at != chain[-1].created_at
        ):
            raise ControlPlaneV3IntegrityError(
                "v2 projection does not equal its verified event head"
            )
        mission_id = chain[-1].mission_id
        source_event_id = chain[-1].event_id
        values = (
            projection_id,
            0,
            workspace_id,
            mission_id,
            V3_SCHEMA_VERSION,
            projection_type,
            correlation_id,
            0,
            event_count,
            source_event_id,
            head_hash,
            None,
            payload_json,
            created_at,
            updated_at,
        )
        connection.execute(
            "INSERT INTO projections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*values[:12], _typed_record_digest("projection", values), *values[12:]),
        )

    for request in history.requests:
        chain = chain_map.get((request.workspace_id, request.correlation_id), ())
        related_events = [
            event
            for event in chain
            if (
                event.entity_type == "action_request"
                and event.entity_id == request.request_id
            )
            or (
                event.entity_type == "action_receipt"
                and event.parent_entity_id == request.request_id
            )
        ]
        if not related_events or related_events[0].entity_type != "action_request":
            raise ControlPlaneV3IntegrityError("request event history is incomplete")
        states: list[tuple[str, str, str | None, str, str]] = [
            (
                "proposed",
                related_events[0].event_id,
                None,
                related_events[0].entity_sha256,
                related_events[0].created_at,
            )
        ]
        for event in related_events[1:]:
            receipt = receipt_by_id.get(event.entity_id)
            if receipt is None:
                raise ControlPlaneV3IntegrityError("request history receipt is unavailable")
            state = (
                "reconciliation_required"
                if receipt.outcome in {"partial", "unknown"}
                else "recorded"
            )
            states.append(
                (
                    state,
                    event.event_id,
                    receipt.receipt_id,
                    event.parent_entity_sha256,
                    event.created_at,
                )
            )
        if states[-1][0] != request.status:
            raise ControlPlaneV3IntegrityError("derived request state diverges from v2")
        for sequence, (
            state,
            event_id,
            receipt_id,
            request_record_sha256,
            created_at,
        ) in enumerate(states):
            state_record_sha256 = _typed_record_digest(
                "action_state",
                (
                    request.request_id,
                    sequence,
                    request.workspace_id,
                    request.mission_id,
                    state,
                    event_id,
                    receipt_id,
                    request_record_sha256,
                    created_at,
                ),
            )
            connection.execute(
                "INSERT INTO action_state_history VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    request.request_id,
                    sequence,
                    request.workspace_id,
                    request.mission_id,
                    state,
                    event_id,
                    receipt_id,
                    request_record_sha256,
                    state_record_sha256,
                    created_at,
                ),
            )


def _assert_legacy_parity(connection: sqlite3.Connection, history: _V2History) -> None:
    expected = dict((name, (digest, count)) for name, digest, count in history.legacy_digests)
    for source, target in _LEGACY_RENAMES:
        _name, digest, count = _logical_table_digest(
            connection, target, logical_name=source
        )
        if expected.get(source) != (digest, count):
            raise ControlPlaneV3IntegrityError(
                f"legacy v2 table {source} changed during migration"
            )


def _open_canonical_connection(path: Path, *, read_only: bool) -> sqlite3.Connection:
    mode = "ro" if read_only else "rw"
    connection: sqlite3.Connection | None = None
    public_error: ControlPlaneV3IOError | None = None
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode={mode}",
            uri=True,
            timeout=5,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA legacy_alter_table=OFF")
        connection.execute("PRAGMA trusted_schema=OFF")
        if not read_only:
            connection.execute("PRAGMA synchronous=FULL")
        return connection
    except BaseException as error:
        if connection is not None:
            try:
                connection.close()
            except BaseException:
                pass
        if not isinstance(error, Exception):
            raise
        public_error = ControlPlaneV3IOError(
            "could not open canonical v3 database"
        )

    # As at the public method boundary, detach ordinary host/SQLite failures
    # instead of retaining their message, path, cause, or traceback context.
    assert public_error is not None
    raise public_error


def _validate_v2_readonly(connection: sqlite3.Connection) -> None:
    if int(connection.execute("PRAGMA application_id").fetchone()[0]) != APPLICATION_ID:
        raise ControlPlaneV3IntegrityError("v2 application identity is invalid")
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) != V2_SCHEMA_VERSION:
        raise ControlPlaneV3IntegrityError("v2 schema version is invalid")
    if _schema_manifest(connection, include_behavior=False) != _reference_manifest(
        version=V2_SCHEMA_VERSION, include_behavior=False
    ):
        raise ControlPlaneV3IntegrityError("v2 semantic schema manifest diverges")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ControlPlaneV3IntegrityError("v2 SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ControlPlaneV3IntegrityError("v2 foreign-key integrity failed")
    metadata = _metadata(connection)
    if metadata.get("schema_fingerprint") != _schema_fingerprint(
        _reference_manifest(version=V2_SCHEMA_VERSION)
    ):
        raise ControlPlaneV3IntegrityError("v2 schema fingerprint is invalid")


class _DatabaseAnchorPort:
    """Snapshot source whose candidate is bound only by the migration owner."""

    def __init__(self, path: Path):
        self.path = Path(path)
        # Snapshot overrides belong to the lock-owning writer thread.  Keeping
        # them thread-local prevents a waiter from clearing or observing an
        # in-flight candidate while it queues on the external anchor lock.
        self._local = threading.local()

    def bind_candidate(self, connection: sqlite3.Connection) -> None:
        if getattr(self._local, "candidate", None) is not None:
            raise ControlPlaneV3Conflict("an anchor candidate is already bound")
        self._local.candidate = connection

    def clear_candidate(self) -> None:
        self._local.candidate = None

    def project_pending_finalization(self) -> None:
        self._local.project_finalization = True

    def clear_pending_finalization(self) -> None:
        self._local.project_finalization = False

    def snapshot(self) -> ledger_anchor.LedgerSnapshot:
        candidate = getattr(self._local, "candidate", None)
        project_finalization = bool(
            getattr(self._local, "project_finalization", False)
        )
        owned = candidate is None
        connection = (
            _open_canonical_connection(self.path, read_only=True)
            if owned
            else candidate
        )
        if connection is None:  # pragma: no cover - narrows the Optional type
            raise ControlPlaneV3IOError("anchor snapshot connection is unavailable")
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version == V2_SCHEMA_VERSION:
                if owned:
                    _validate_v2_readonly(connection)
                else:
                    ControlPlaneStore._validate_schema(connection)
            elif version == V3_SCHEMA_VERSION:
                if _schema_manifest(
                    connection, include_behavior=False
                ) != _reference_manifest_v3(include_behavior=False):
                    raise ControlPlaneV3IntegrityError(
                        "anchor candidate v3 manifest diverges"
                    )
                if _ddl_sql_manifest(connection) != _reference_ddl_sql_v3():
                    raise ControlPlaneV3IntegrityError(
                        "anchor candidate v3 DDL SQL diverges"
                    )
                _assert_v3_rename_contract(connection)
            else:
                raise ControlPlaneV3IntegrityError(
                    "anchor snapshot schema version is unsupported"
                )
            metadata = _metadata(connection)
            database_id = _database_instance_id(metadata)
            fingerprint = (
                _schema_fingerprint(_reference_manifest(version=V2_SCHEMA_VERSION))
                if version == V2_SCHEMA_VERSION
                else _actual_v3_fingerprint(connection)
            )
            if version == V3_SCHEMA_VERSION:
                operational = _validate_operational_latest(
                    connection,
                    allow_projected_finalization=project_finalization,
                )
                if operational is not None:
                    commit = operational.commit
                    return ledger_anchor.LedgerSnapshot(
                        database_id,
                        fingerprint,
                        str(commit[6]),
                        int(commit[15]),
                        {
                            "ledger_events": int(commit[15]),
                            "root_rows": int(commit[14]),
                            "v3_operational_sequence": int(commit[1]),
                            **dict(operational.anchor_counts),
                        },
                    )
            root = _stream_state_root(connection)
            event_count = int(
                connection.execute("SELECT count(*) FROM event_envelopes").fetchone()[0]
            )
            counts = {"ledger_events": event_count, "root_rows": root.row_count}
            if version == V3_SCHEMA_VERSION:
                bookkeeping = _validate_bookkeeping(
                    connection,
                    database_id=database_id,
                    fingerprint=fingerprint,
                    root=root,
                    allow_projected_finalization=project_finalization,
                )
                counts.update(dict(bookkeeping.anchor_counts))
            return ledger_anchor.LedgerSnapshot(
                database_id,
                fingerprint,
                root.digest,
                event_count,
                counts,
            )
        finally:
            if owned:
                connection.close()


def _intent_id(
    commit_id: str, sequence: int, root: str, created_at: str
) -> str:
    payload = json.dumps(
        [commit_id, sequence, root, "sqlite_committed", created_at],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-V3-ANCHOR-INTENT\0" + payload).hexdigest()


def _finalization_id(
    intent_id: str, sequence: int, root: str, created_at: str
) -> str:
    payload = json.dumps(
        [intent_id, sequence, root, created_at],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-V3-ANCHOR-FINAL\0" + payload).hexdigest()


_OPERATIONAL_COMMIT_COLUMNS = (
    "commit_id",
    "commit_sequence",
    "previous_commit_id",
    "previous_state_root",
    "database_instance_id",
    "schema_fingerprint",
    "state_root",
    "delta_sha256",
    "genesis_baseline_root",
    "entry_merkle_root",
    "mmr_root",
    "mmr_leaf_hash",
    "mmr_size",
    "entry_count",
    "canonical_row_count",
    "event_count",
    "created_at",
)
_OPERATIONAL_ENTRY_COLUMNS = (
    "commit_id",
    "entry_ordinal",
    "table_name",
    "row_identity",
    "row_sha256",
    "leaf_index",
    "leaf_hash",
)
_OPERATIONAL_BINDING_NAMESPACE = b"ONYX-V3-OPERATIONAL-BOOKKEEPING-V2\0"


def _operational_delta_digest(
    entries: Iterable[tuple[str, str, str]],
) -> str:
    digest = hashlib.sha256(b"ONYX-V3-OPERATIONAL-DELTA-V1\0")
    count = 0
    for table, identity, row_sha256 in entries:
        digest.update(_encode_value(table))
        digest.update(_encode_value(identity))
        digest.update(_encode_value(row_sha256))
        count += 1
    digest.update(_encode_value(count))
    return digest.hexdigest()


def _entry_merkle_leaf(
    ordinal: int, table: str, identity: str, row_sha256: str
) -> str:
    digest = hashlib.sha256(b"ONYX-V3-ENTRY-MERKLE-LEAF-V1\0")
    for value in (ordinal, table, identity, row_sha256):
        digest.update(_encode_value(value))
    return digest.hexdigest()


def _merkle_parent(left: str, right: str) -> str:
    return hashlib.sha256(
        b"ONYX-V3-ENTRY-MERKLE-NODE-V1\0" + bytes.fromhex(left) + bytes.fromhex(right)
    ).hexdigest()


def _entry_merkle_tree(
    entries: Iterable[tuple[str, str, str]],
) -> tuple[str, tuple[str, ...], tuple[tuple[int, int, str], ...]]:
    leaves = tuple(
        _entry_merkle_leaf(index, table, identity, row_sha)
        for index, (table, identity, row_sha) in enumerate(entries)
    )
    if not leaves:
        raise ControlPlaneV3IntegrityError("entry Merkle tree is empty")
    nodes: list[tuple[int, int, str]] = [
        (0, index, leaf) for index, leaf in enumerate(leaves)
    ]
    level = 0
    current = list(leaves)
    while len(current) > 1:
        next_level: list[str] = []
        for index in range(0, len(current), 2):
            left = current[index]
            right = current[index + 1] if index + 1 < len(current) else left
            next_level.append(_merkle_parent(left, right))
        level += 1
        nodes.extend((level, index, value) for index, value in enumerate(next_level))
        current = next_level
    return current[0], leaves, tuple(nodes)


def _mmr_leaf(commit_id: str, sequence: int, payload_root: str) -> str:
    digest = hashlib.sha256(b"ONYX-V3-MMR-LEAF-V1\0")
    for value in (commit_id, sequence, payload_root):
        digest.update(_encode_value(value))
    return digest.hexdigest()


def _mmr_parent(height: int, left: str, right: str) -> str:
    digest = hashlib.sha256(b"ONYX-V3-MMR-NODE-V1\0")
    for value in (height, left, right):
        digest.update(_encode_value(value))
    return digest.hexdigest()


def _mmr_bag(peaks: Iterable[tuple[int, str]]) -> str:
    digest = hashlib.sha256(b"ONYX-V3-MMR-PEAKS-V1\0")
    count = 0
    for height, peak_hash in peaks:
        digest.update(_encode_value(height))
        digest.update(_encode_value(peak_hash))
        count += 1
    digest.update(_encode_value(count))
    return digest.hexdigest()


def _operational_payload_root(
    *,
    sequence: int,
    previous_commit_id: str,
    previous_state_root: str,
    database_id: str,
    fingerprint: str,
    delta_sha256: str,
    genesis_baseline_root: str,
    entry_merkle_root: str,
    entry_count: int,
    canonical_row_count: int,
    event_count: int,
    created_at: str,
) -> str:
    payload = json.dumps(
        [
            sequence, previous_commit_id, previous_state_root, database_id,
            fingerprint, delta_sha256, genesis_baseline_root, entry_merkle_root,
            entry_count, canonical_row_count, event_count, created_at,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-V3-OPERATIONAL-PAYLOAD-V2\0" + payload).hexdigest()


def _operational_state_root(
    *,
    sequence: int,
    previous_commit_id: str,
    previous_state_root: str,
    database_id: str,
    fingerprint: str,
    delta_sha256: str,
    genesis_baseline_root: str,
    entry_merkle_root: str,
    mmr_root: str,
    mmr_size: int,
    entry_count: int,
    canonical_row_count: int,
    event_count: int,
    created_at: str,
) -> str:
    payload = json.dumps(
        [
            sequence,
            previous_commit_id,
            previous_state_root,
            database_id,
            fingerprint,
            delta_sha256,
            genesis_baseline_root,
            entry_merkle_root,
            mmr_root,
            mmr_size,
            entry_count,
            canonical_row_count,
            event_count,
            created_at,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-V3-OPERATIONAL-ROOT-V2\0" + payload).hexdigest()


def _operational_commit_id(
    *,
    state_root: str,
    sequence: int,
    previous_commit_id: str,
    delta_sha256: str,
    created_at: str,
) -> str:
    payload = json.dumps(
        [state_root, sequence, previous_commit_id, delta_sha256, created_at],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-V3-OPERATIONAL-COMMIT-V1\0" + payload).hexdigest()


def _operational_intent_id(
    commit_id: str, sequence: int, root: str, created_at: str
) -> str:
    payload = json.dumps(
        [commit_id, sequence, root, "sqlite_committed", created_at],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-V3-OPERATIONAL-INTENT-V1\0" + payload).hexdigest()


def _operational_finalization_id(
    intent_id: str, sequence: int, root: str, created_at: str
) -> str:
    payload = json.dumps(
        [intent_id, sequence, root, created_at],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"ONYX-V3-OPERATIONAL-FINAL-V1\0" + payload).hexdigest()


def _operational_anchor_counts(digest: bytes) -> tuple[tuple[str, int], ...]:
    if len(digest) != 32:
        raise ControlPlaneV3IntegrityError("operational bookkeeping digest is invalid")
    value = int.from_bytes(digest, "big")
    limb_bits = 52
    mask = (1 << limb_bits) - 1
    return tuple(
        (
            f"v3_operational_sha256_v1_{index:02d}",
            (value >> ((4 - index) * limb_bits)) & mask,
        )
        for index in range(5)
    )


def _validate_operational_latest(
    connection: sqlite3.Connection,
    *,
    allow_projected_finalization: bool,
) -> _OperationalState | None:
    selected = ",".join(_OPERATIONAL_COMMIT_COLUMNS)
    commit = connection.execute(
        f"SELECT {selected} FROM operational_commits "
        "ORDER BY commit_sequence DESC LIMIT 1"
    ).fetchone()
    if commit is None:
        return None
    (
        commit_id, sequence, previous_commit_id, previous_root, database_id,
        fingerprint, state_root, delta_sha256, genesis_baseline_root,
        entry_merkle_root, mmr_root, mmr_leaf_hash, mmr_size, entry_count,
        canonical_row_count, event_count, created_at,
    ) = commit
    if (
        type(sequence) is not int
        or sequence < 1
        or type(mmr_size) is not int
        or mmr_size != sequence
        or type(entry_count) is not int
        or entry_count < 1
        or type(canonical_row_count) is not int
        or canonical_row_count < 1
        or type(event_count) is not int
        or event_count < 0
        or not isinstance(created_at, str)
        or not _valid_utc_timestamp(created_at)
    ):
        raise ControlPlaneV3IntegrityError("operational commit fields are invalid")
    if sequence == 1:
        predecessor = connection.execute(
            "SELECT commit_id,state_root,root_row_count FROM integrity_commits"
        ).fetchone()
        predecessor_count = 0
    else:
        predecessor = connection.execute(
            "SELECT commit_id,state_root,canonical_row_count,genesis_baseline_root "
            "FROM operational_commits "
            "WHERE commit_sequence=?",
            (sequence - 1,),
        ).fetchone()
        predecessor_count = int(predecessor[2]) if predecessor is not None else -1
    if (
        predecessor is None
        or predecessor[0] != previous_commit_id
        or predecessor[1] != previous_root
        or predecessor_count + entry_count != canonical_row_count
        or (sequence == 1 and genesis_baseline_root != predecessor[1])
        or (sequence > 1 and genesis_baseline_root != predecessor[3])
    ):
        raise ControlPlaneV3IntegrityError("operational commit predecessor diverges")
    payload_root = _operational_payload_root(
        sequence=sequence,
        previous_commit_id=str(previous_commit_id),
        previous_state_root=str(previous_root),
        database_id=str(database_id),
        fingerprint=str(fingerprint),
        delta_sha256=str(delta_sha256),
        genesis_baseline_root=str(genesis_baseline_root),
        entry_merkle_root=str(entry_merkle_root),
        entry_count=entry_count,
        canonical_row_count=canonical_row_count,
        event_count=event_count,
        created_at=created_at,
    )
    expected_commit_id = _operational_commit_id(
        state_root=payload_root,
        sequence=sequence,
        previous_commit_id=str(previous_commit_id),
        delta_sha256=str(delta_sha256),
        created_at=created_at,
    )
    expected_leaf = _mmr_leaf(expected_commit_id, sequence, payload_root)
    peaks = tuple(connection.execute(
        "SELECT peak_height,peak_hash FROM operational_mmr_peaks "
        "WHERE commit_sequence=? ORDER BY peak_ordinal", (sequence,)
    ).fetchall())
    leaf_node = connection.execute(
        "SELECT node_height,left_hash,right_hash,commit_sequence "
        "FROM operational_mmr_nodes WHERE node_hash=?", (expected_leaf,)
    ).fetchone()
    if (
        mmr_leaf_hash != expected_leaf
        or leaf_node != (0, None, None, sequence)
        or not peaks
        or mmr_root != _mmr_bag((int(row[0]), str(row[1])) for row in peaks)
    ):
        raise ControlPlaneV3IntegrityError("operational MMR state diverges")
    current_hash = expected_leaf
    visited: set[str] = set()
    while True:
        if current_hash in visited:
            raise ControlPlaneV3IntegrityError("operational MMR path contains a cycle")
        visited.add(current_hash)
        edge = connection.execute(
            "SELECT parent_hash,side FROM operational_mmr_edges WHERE child_hash=?",
            (current_hash,),
        ).fetchone()
        if edge is None:
            break
        parent = connection.execute(
            "SELECT node_height,left_hash,right_hash FROM operational_mmr_nodes "
            "WHERE node_hash=?", (edge[0],)
        ).fetchone()
        if (
            parent is None
            or parent[1] is None
            or parent[2] is None
            or _mmr_parent(int(parent[0]), str(parent[1]), str(parent[2])) != edge[0]
            or (str(parent[1]), str(parent[2]))[int(edge[1])] != current_hash
        ):
            raise ControlPlaneV3IntegrityError("operational MMR path diverges")
        current_hash = str(edge[0])
    if current_hash not in {str(row[1]) for row in peaks}:
        raise ControlPlaneV3IntegrityError("operational MMR leaf is not in the head")
    expected_root = _operational_state_root(
        sequence=sequence,
        previous_commit_id=str(previous_commit_id),
        previous_state_root=str(previous_root),
        database_id=str(database_id),
        fingerprint=str(fingerprint),
        delta_sha256=str(delta_sha256),
        genesis_baseline_root=str(genesis_baseline_root),
        entry_merkle_root=str(entry_merkle_root),
        mmr_root=str(mmr_root),
        mmr_size=mmr_size,
        entry_count=entry_count,
        canonical_row_count=canonical_row_count,
        event_count=event_count,
        created_at=created_at,
    )
    if state_root != expected_root or commit_id != expected_commit_id:
        raise ControlPlaneV3IntegrityError("operational commit identity diverges")
    metadata = _metadata(connection)
    if (
        database_id != _database_instance_id(metadata)
        or fingerprint != _actual_v3_fingerprint(connection)
    ):
        raise ControlPlaneV3IntegrityError("operational commit metadata diverges")
    migration_sequence = connection.execute(
        "SELECT anchor_sequence FROM anchor_intents"
    ).fetchone()
    if migration_sequence is None:
        raise ControlPlaneV3IntegrityError("migration anchor intent is unavailable")
    expected_anchor_sequence = int(migration_sequence[0]) + sequence
    intent = connection.execute(
        "SELECT intent_id,commit_id,anchor_sequence,state_root,status,created_at "
        "FROM operational_anchor_intents WHERE commit_id=?",
        (commit_id,),
    ).fetchone()
    expected_intent = (
        _operational_intent_id(
            expected_commit_id,
            expected_anchor_sequence,
            expected_root,
            created_at,
        ),
        expected_commit_id,
        expected_anchor_sequence,
        expected_root,
        "sqlite_committed",
        created_at,
    )
    if intent != expected_intent:
        raise ControlPlaneV3IntegrityError("operational anchor intent diverges")
    expected_finalization = (
        _operational_finalization_id(
            str(expected_intent[0]),
            expected_anchor_sequence,
            expected_root,
            created_at,
        ),
        expected_intent[0],
        expected_anchor_sequence,
        expected_root,
        created_at,
    )
    finalization = connection.execute(
        "SELECT finalization_id,intent_id,anchor_sequence,state_root,created_at "
        "FROM operational_anchor_finalizations WHERE intent_id=?",
        (expected_intent[0],),
    ).fetchone()
    if finalization is None:
        if not allow_projected_finalization:
            raise ControlPlaneV3IntegrityError(
                "operational anchor finalization is missing"
            )
        bound_finalization = expected_finalization
    elif finalization != expected_finalization:
        raise ControlPlaneV3IntegrityError(
            "operational anchor finalization diverges"
        )
    else:
        bound_finalization = finalization
    binding = hashlib.sha256(_OPERATIONAL_BINDING_NAMESPACE)
    binding.update(_bookkeeping_digest(
        (
            ("operational_commits", _OPERATIONAL_COMMIT_COLUMNS, (commit,)),
            (
                "operational_mmr_peaks",
                ("peak_height", "peak_hash"),
                peaks,
            ),
            (
                "operational_anchor_intents",
                _BOOKKEEPING_COLUMNS[1][1],
                (expected_intent,),
            ),
            (
                "operational_anchor_finalizations",
                _BOOKKEEPING_COLUMNS[2][1],
                (bound_finalization,),
            ),
        )
    ))
    return _OperationalState(
        commit,
        (),
        expected_intent,
        expected_finalization,
        _operational_anchor_counts(binding.digest()),
    )


class _ControlPlaneV3Migrator:
    def __init__(
        self,
        store: ControlPlaneStore,
        anchor: object,
        anchor_owner: object,
        port: _DatabaseAnchorPort,
        *,
        journal_path: Path,
        key_vault: _SecretVault,
        state_vault: _SecretVault,
        enabled: bool,
        token: bytes,
    ):
        self.store = store
        self.anchor = anchor
        self.anchor_owner = anchor_owner
        self.port = port
        self.journal_path = Path(journal_path)
        self.key_vault = key_vault
        self.state_vault = state_vault
        self.enabled = enabled
        self._token = token

    def _fault(self, _point: str) -> None:
        return None

    def _assert_owner(self, owner: V3OwnerCapability) -> None:
        issued = _CAPABILITY_REGISTRY.get(owner)
        if issued is None or not hmac.compare_digest(issued, self._token):
            raise ControlPlaneV3Conflict("v3 owner capability is invalid or stale")
        if not self.enabled:
            raise ControlPlaneV3Disabled(
                f"{LEDGER_V3_FLAG} is disabled; schema v3 remains inactive"
            )

    def _ensure_anchor(self) -> object:
        try:
            key = self.key_vault.get_bytes()
            state = self.state_vault.get_bytes()
        except Exception:
            raise ControlPlaneV3IOError("anchor vault preflight failed") from None
        journal_exists = self.journal_path.exists()
        journal_size = self.journal_path.stat().st_size if journal_exists else 0
        if key is None and state is None and journal_size == 0:
            return self.anchor.bootstrap(self.anchor_owner)
        if key is None or state is None or not journal_exists:
            raise ControlPlaneV3IntegrityError("anchor artifacts are incomplete")
        try:
            return self.anchor.verify(self.anchor_owner)
        except ledger_anchor.LedgerAnchorConflict:
            status = self.anchor.recover(self.anchor_owner)
            return self.anchor.verify(self.anchor_owner) if status.prepared else status

    @staticmethod
    def _insert_finalization(
        connection: sqlite3.Connection,
        *,
        intent_id: str,
        sequence: int,
        root: str,
    ) -> None:
        intent = connection.execute(
            "SELECT created_at FROM anchor_intents WHERE intent_id=?",
            (intent_id,),
        ).fetchone()
        if (
            intent is None
            or not isinstance(intent[0], str)
            or not _valid_utc_timestamp(intent[0])
        ):
            raise ControlPlaneV3IntegrityError(
                "anchor finalization intent is unavailable"
            )
        created_at = intent[0]
        existing = connection.execute(
            "SELECT finalization_id,intent_id,anchor_sequence,state_root,created_at "
            "FROM anchor_finalizations"
        ).fetchall()
        expected = (
            _finalization_id(intent_id, sequence, root, created_at),
            intent_id,
            sequence,
            root,
            created_at,
        )
        if existing:
            if existing != [expected]:
                raise ControlPlaneV3IntegrityError(
                    "anchor finalization conflicts with durable state"
                )
            return
        connection.execute(
            "INSERT INTO anchor_finalizations VALUES(?,?,?,?,?)",
            expected,
        )

    @_public_v3_boundary
    def migrate(self, owner: V3OwnerCapability) -> V3Status:
        self._assert_owner(owner)
        with _V3_LOCK:
            connection = self.store._require_connection()
            ControlPlaneStore._validate_schema(connection)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA legacy_alter_table=OFF")
            # Never create an anchor for structurally valid but semantically
            # ambiguous v2 history.  The transaction repeats this preflight
            # after acquiring the write lock to close the concurrency window.
            _preflight_v2(self.store, connection)
            anchored = self._ensure_anchor()
            current = self.port.snapshot()
            if (
                anchored.database_id != current.database_id
                or anchored.schema_fingerprint != current.schema_fingerprint
                or anchored.ledger_root != current.ledger_root
            ):
                raise ControlPlaneV3IntegrityError(
                    "v2 database does not match its committed anchor"
                )
            ticket = None
            sqlite_committed = False
            try:
                self._fault("before_v2_lock")
                connection.execute("BEGIN IMMEDIATE")
                self.port.bind_candidate(connection)
                try:
                    locked_v2 = self.port.snapshot()
                finally:
                    self.port.clear_candidate()
                if (
                    anchored.database_id != locked_v2.database_id
                    or anchored.schema_fingerprint != locked_v2.schema_fingerprint
                    or anchored.ledger_root != locked_v2.ledger_root
                    or anchored.event_count != locked_v2.event_count
                ):
                    raise ControlPlaneV3Conflict(
                        "v2 changed between anchor verification and migration lock"
                    )
                history = _preflight_v2(self.store, connection)
                metadata = _metadata(connection)
                database_id = _database_instance_id(metadata)
                for statement in _V3_SCHEMA_STATEMENTS:
                    connection.execute(statement)
                _assert_v3_rename_contract(connection)
                _copy_v2_history(connection, history)
                _assert_legacy_parity(connection, history)
                connection.execute(
                    "INSERT INTO schema_metadata(key,value) VALUES('database_instance_id',?)",
                    (database_id,),
                )
                fingerprint = _v3_fingerprint()
                connection.execute(
                    "UPDATE schema_metadata SET value=? WHERE key='schema_version'",
                    (str(V3_SCHEMA_VERSION),),
                )
                connection.execute(
                    "UPDATE schema_metadata SET value=? WHERE key='schema_fingerprint'",
                    (fingerprint,),
                )
                connection.execute(
                    "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
                    (
                        M2B_MIGRATION_ID,
                        V2_SCHEMA_VERSION,
                        V3_SCHEMA_VERSION,
                        "applied",
                        datetime.now(timezone.utc).isoformat(),
                        fingerprint,
                    ),
                )
                connection.execute(f"PRAGMA user_version={V3_SCHEMA_VERSION}")
                for statement in _V3_FINALIZE_SCHEMA_STATEMENTS:
                    connection.execute(statement)
                _assert_v3_rename_contract(connection)
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ControlPlaneV3IntegrityError(
                        "v3 foreign keys failed after history copy"
                    )
                _validate_v3_mappings(connection)
                root = _stream_state_root(connection)
                bookkeeping_created_at = datetime.now(timezone.utc).isoformat()
                commit_id = _integrity_commit_id(
                    database_id,
                    fingerprint,
                    root,
                    bookkeeping_created_at,
                )
                connection.execute(
                    "INSERT INTO integrity_commits VALUES(?,?,?,?,?,?,?)",
                    (
                        commit_id,
                        database_id,
                        fingerprint,
                        root.digest,
                        root.row_count,
                        "sha256-type-tagged-v1",
                        bookkeeping_created_at,
                    ),
                )
                expected_sequence = anchored.sequence + 1
                intent_id = _intent_id(
                    commit_id,
                    expected_sequence,
                    root.digest,
                    bookkeeping_created_at,
                )
                connection.execute(
                    "INSERT INTO anchor_intents VALUES(?,?,?,?,?,?)",
                    (
                        intent_id,
                        commit_id,
                        expected_sequence,
                        root.digest,
                        "sqlite_committed",
                        bookkeeping_created_at,
                    ),
                )
                self.port.project_pending_finalization()
                self.port.bind_candidate(connection)
                self._fault("before_anchor_prepare")
                ticket = self.anchor.prepare(self.anchor_owner)
                if ticket.sequence != expected_sequence:
                    raise ControlPlaneV3Conflict(
                        "prepared anchor sequence changed during migration"
                    )
                self._fault("after_anchor_prepare")
                connection.execute("COMMIT")
                sqlite_committed = True
                self.port.clear_candidate()
                self.store.close()
                self._fault("after_sqlite_commit")
                reopened = _open_canonical_connection(self.port.path, read_only=True)
                try:
                    staged = _validate_v3_exact(reopened, require_finalization=False)
                finally:
                    reopened.close()
                self._fault("before_anchor_finalize")
                anchor_status = self.anchor.finalize(self.anchor_owner, ticket)
                if (
                    anchor_status.ledger_root != staged.state_root
                    or anchor_status.schema_fingerprint != staged.schema_fingerprint
                    or anchor_status.database_id != staged.database_instance_id
                ):
                    raise ControlPlaneV3IntegrityError(
                        "finalized anchor diverges from canonical reopen"
                    )
                self._fault("after_anchor_finalize")
                final = _open_canonical_connection(self.port.path, read_only=False)
                try:
                    final.execute("BEGIN IMMEDIATE")
                    self._insert_finalization(
                        final,
                        intent_id=intent_id,
                        sequence=ticket.sequence,
                        root=root.digest,
                    )
                    final.execute("COMMIT")
                    status = _validate_v3_exact(final, require_finalization=True)
                except BaseException:
                    try:
                        final.execute("ROLLBACK")
                    except sqlite3.DatabaseError:
                        pass
                    raise
                finally:
                    final.close()
                verified = self.anchor.verify(self.anchor_owner)
                if verified.ledger_root != status.state_root:
                    raise ControlPlaneV3IntegrityError(
                        "exposed v3 root diverges from committed anchor"
                    )
                self._fault("after_finalization_record")
                return status
            except BaseException:
                self.port.clear_candidate()
                if not sqlite_committed:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.DatabaseError:
                        pass
                    if ticket is not None:
                        try:
                            self.anchor.recover(self.anchor_owner)
                        except ledger_anchor.LedgerAnchorError:
                            pass
                raise
            finally:
                self.port.clear_candidate()
                self.port.clear_pending_finalization()

    @_public_v3_boundary
    def recover(self, owner: V3OwnerCapability) -> V3Status:
        self._assert_owner(owner)
        with _V3_LOCK:
            self.port.clear_candidate()
            self.port.project_pending_finalization()
            connection: sqlite3.Connection | None = None
            try:
                anchor_status = self.anchor.recover(self.anchor_owner)
                connection = _open_canonical_connection(self.port.path, read_only=False)
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version == V2_SCHEMA_VERSION:
                    ControlPlaneStore._validate_schema(connection)
                    raise ControlPlaneV3Conflict(
                        "prepared v3 migration was rolled back to exact v2"
                    )
                staged = _validate_v3_exact(connection, require_finalization=False)
                if (
                    anchor_status.database_id != staged.database_instance_id
                    or anchor_status.schema_fingerprint != staged.schema_fingerprint
                    or anchor_status.ledger_root != staged.state_root
                    or anchor_status.prepared
                ):
                    raise ControlPlaneV3IntegrityError(
                        "recovered anchor diverges from durable v3"
                    )
                intent = connection.execute(
                    "SELECT intent_id,anchor_sequence,state_root FROM anchor_intents"
                ).fetchone()
                connection.execute("BEGIN IMMEDIATE")
                self._insert_finalization(
                    connection,
                    intent_id=intent[0],
                    sequence=intent[1],
                    root=intent[2],
                )
                connection.execute("COMMIT")
                return _validate_v3_exact(connection, require_finalization=True)
            except BaseException:
                if connection is not None:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.DatabaseError:
                        pass
                raise
            finally:
                self.port.clear_pending_finalization()
                if connection is not None:
                    connection.close()

    @_public_v3_boundary
    def open(self, owner: V3OwnerCapability) -> V3Status:
        self._assert_owner(owner)
        with _V3_LOCK:
            connection = _open_canonical_connection(self.port.path, read_only=True)
            try:
                status = _validate_v3_exact(connection, require_finalization=True)
            finally:
                connection.close()
            anchored = self.anchor.verify(self.anchor_owner)
            if (
                anchored.prepared
                or anchored.database_id != status.database_instance_id
                or anchored.schema_fingerprint != status.schema_fingerprint
                or anchored.ledger_root != status.state_root
                or anchored.sequence != status.anchor_sequence
            ):
                raise ControlPlaneV3IntegrityError(
                    "v3 cannot be exposed because its anchor diverges"
                )
            return status


def _open_for_testing(
    store: ControlPlaneStore,
    *,
    journal_path: Path,
    key_vault: _SecretVault,
    state_vault: _SecretVault,
    enabled: bool,
) -> tuple[_ControlPlaneV3Migrator, V3OwnerCapability]:
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    if not isinstance(key_vault, _SecretVault) or not isinstance(state_vault, _SecretVault):
        raise TypeError("vaults must implement the secret-vault contract")
    path = Path(store.path)
    port = _DatabaseAnchorPort(path)
    anchor, anchor_owner = ledger_anchor._open_for_testing(
        port,
        journal_path=Path(journal_path),
        key_vault=key_vault,
        state_vault=state_vault,
    )
    token = secrets.token_bytes(32)
    migrator = _ControlPlaneV3Migrator(
        store,
        anchor,
        anchor_owner,
        port,
        journal_path=Path(journal_path),
        key_vault=key_vault,
        state_vault=state_vault,
        enabled=enabled,
        token=token,
    )
    owner = V3OwnerCapability(token, _CAPABILITY_SEAL)
    _CAPABILITY_REGISTRY[owner] = token
    return migrator, owner


def open_default() -> None:
    if not ledger_v3_enabled():
        raise ControlPlaneV3Disabled(
            f"{LEDGER_V3_FLAG} is disabled; schema v3 remains inactive"
        )
    raise ControlPlaneV3Unavailable(
        "M2b-b has no production owner/anchor wiring; M2b-c is required"
    )


__all__ = [
    "LEDGER_V3_FLAG",
    "ControlPlaneV3Conflict",
    "ControlPlaneV3Disabled",
    "ControlPlaneV3Error",
    "ControlPlaneV3IOError",
    "ControlPlaneV3IntegrityError",
    "ControlPlaneV3Unavailable",
    "ledger_v3_enabled",
    "open_default",
]
