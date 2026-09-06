"""Default-off canonical schema-v3 repository with anchored incremental commits.

This is the M2b-c repository adapter.  It preserves the public M2a domain
contract and remains absent from startup, mission, permission, tool and UI
surfaces.  It records observations only; it cannot dispatch an action.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import TypeVar

from core import ledger_anchor
from core.control_plane import ControlPlaneIOError
from core.control_plane_v3 import (
    LEDGER_V3_FLAG,
    V3_SCHEMA_VERSION,
    ControlPlaneV3Error,
    ControlPlaneV3IntegrityError,
    V3OwnerCapability,
    _ControlPlaneV3Migrator,
    _actual_v3_fingerprint,
    _database_instance_id,
    _entry_merkle_tree,
    _encode_value,
    _mmr_bag,
    _mmr_leaf,
    _mmr_parent,
    _metadata,
    _open_canonical_connection,
    _operational_commit_id,
    _operational_delta_digest,
    _operational_finalization_id,
    _operational_intent_id,
    _operational_payload_root,
    _operational_state_root,
    _typed_record_digest,
    _valid_utc_timestamp,
    _validate_operational_latest,
    _validate_v3_exact,
)
from core.domain_ledger import (
    DOMAIN_CONTRACT_VERSION,
    ActionReceiptRecord,
    ActionRequestRecord,
    ClaimRecord,
    DomainConflict,
    DomainContractError,
    DomainIntegrityError,
    DomainIsolationError,
    DomainLedgerDisabled,
    DomainLedgerError,
    DomainLedgerRepository,
    EvidenceRecord,
    EventEnvelope,
    _APPROVAL_POLICIES,
    _CORRELATION_ID,
    _DATA_CLASSES,
    _ENTITY_ID,
    _FRESHNESS,
    _OUTCOMES,
    _RISKS,
    _SAFE_ID,
    _SOURCE_KINDS,
    _VERIFICATION,
    _basis_points,
    _canonical,
    _correlation_id,
    _entity_id,
    _enum,
    _event_identity,
    _idempotency_key,
    _material_present,
    _now,
    _record_digest,
    _row_digest,
    _safe_key,
    _safe_material,
    _sha,
    _slug,
    _validity_seconds,
)
from core.workspaces import LEGACY_WORKSPACE_ID, WorkspaceRegistry


_ZERO_HASH = "0" * 64
_REPOSITORY_SEAL = object()
_WRITER_TIMEOUT_SECONDS = 30.0
_T = TypeVar("_T")


class _WriteRecoveryRetry(Exception):
    """Internal signal: recovery completed; retry under a fresh writer session."""


_ROW_ID_COLUMNS: dict[str, tuple[str, ...]] = {
    "evidence_records": ("evidence_id",),
    "claims": ("claim_id",),
    "claim_evidence_links": ("claim_id", "evidence_id"),
    "claim_relations": ("relation_id",),
    "action_requests": ("request_id",),
    "action_receipts": ("receipt_id",),
    "action_state_history": ("request_id", "state_sequence"),
    "artifact_index": ("artifact_id",),
    "event_envelopes": ("event_id",),
    "event_chain_history": ("workspace_id", "correlation_id", "event_sequence"),
    "event_chain_heads": ("workspace_id", "correlation_id", "head_revision"),
    "projections": ("workspace_id", "projection_id", "projection_revision"),
    "legacy_v2_evidence_records": ("evidence_id",),
    "legacy_v2_claims": ("claim_id",),
    "legacy_v2_action_requests": ("request_id",),
    "legacy_v2_action_receipts": ("receipt_id",),
    "legacy_v2_event_envelopes": ("event_id",),
    "legacy_v2_projections": ("projection_id",),
    "workspaces": ("workspace_id",),
    "mission_contexts": ("mission_id",),
}

# Keep the implementation registry and acceptance contract independently
# declared.  A missing entry must fail closed instead of silently shrinking the
# genesis/audit universe when this module is edited later.
_EXPECTED_AUDITED_TABLES = frozenset(
    {
        "evidence_records", "claims", "claim_evidence_links", "claim_relations",
        "action_requests", "action_receipts", "action_state_history", "artifact_index",
        "event_envelopes", "event_chain_history", "event_chain_heads", "projections",
        "legacy_v2_evidence_records", "legacy_v2_claims",
        "legacy_v2_action_requests", "legacy_v2_action_receipts",
        "legacy_v2_event_envelopes", "legacy_v2_projections",
        "workspaces", "mission_contexts",
    }
)
_AUDITED_TABLES = tuple(sorted(_ROW_ID_COLUMNS))


def _assert_audited_registry(connection: sqlite3.Connection) -> None:
    implementation = frozenset(_AUDITED_TABLES)
    if implementation != _EXPECTED_AUDITED_TABLES:
        raise DomainIntegrityError("audited-table registry diverges from its contract")
    physical = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    missing = _EXPECTED_AUDITED_TABLES - physical
    if missing:
        raise DomainIntegrityError("audited canonical tables are missing")


def _all_audited_entries(
    connection: sqlite3.Connection,
) -> list[tuple[str, str, str]]:
    _assert_audited_registry(connection)
    entries: list[tuple[str, str, str]] = []
    for table in _AUDITED_TABLES:
        keys = _ROW_ID_COLUMNS[table]
        selected = ",".join(f'"{key}"' for key in keys)
        order = ",".join(f'"{key}"' for key in keys)
        for values in connection.execute(
            f'SELECT {selected} FROM "{table}" ORDER BY {order}'
        ).fetchall():
            entries.append(_entry(connection, table, *values))
    return entries


def _prepare_mmr_append(
    connection: sqlite3.Connection,
    *,
    sequence: int,
    leaf_hash: str,
) -> tuple[
    str,
    tuple[tuple[str, int, str | None, str | None, int], ...],
    tuple[tuple[str, str, int], ...],
    tuple[tuple[int, int, int, str], ...],
]:
    prior: list[tuple[int, str]] = []
    if sequence > 1:
        prior = [
            (int(row[0]), str(row[1]))
            for row in connection.execute(
                "SELECT peak_height,peak_hash FROM operational_mmr_peaks "
                "WHERE commit_sequence=? ORDER BY peak_ordinal",
                (sequence - 1,),
            ).fetchall()
        ]
        if not prior:
            raise DomainIntegrityError("operational MMR predecessor peaks are missing")
    peaks = list(prior)
    nodes: list[tuple[str, int, str | None, str | None, int]] = [
        (leaf_hash, 0, None, None, sequence)
    ]
    edges: list[tuple[str, str, int]] = []
    carry_height = 0
    carry_hash = leaf_hash
    while peaks and peaks[-1][0] == carry_height:
        _height, left_hash = peaks.pop()
        parent_hash = _mmr_parent(carry_height + 1, left_hash, carry_hash)
        nodes.append(
            (parent_hash, carry_height + 1, left_hash, carry_hash, sequence)
        )
        edges.extend(((parent_hash, left_hash, 0), (parent_hash, carry_hash, 1)))
        carry_height += 1
        carry_hash = parent_hash
    peaks.append((carry_height, carry_hash))
    peak_rows = tuple(
        (sequence, ordinal, height, node_hash)
        for ordinal, (height, node_hash) in enumerate(peaks)
    )
    return _mmr_bag(peaks), tuple(nodes), tuple(edges), peak_rows


def _row_identity(values: Iterable[object]) -> str:
    return json.dumps(list(values), ensure_ascii=True, separators=(",", ":"))


def _require_sha256_digest(value: object, field: str) -> str:
    """Reject malformed persisted digests before cryptographic primitives see them."""

    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DomainIntegrityError(f"{field} is not a canonical SHA-256 digest")
    return value


def _row_sha256(connection: sqlite3.Connection, table: str, identity: str) -> str:
    columns = tuple(
        str(row[1])
        for row in connection.execute(f'PRAGMA table_xinfo("{table}")').fetchall()
        if int(row[6]) == 0
    )
    keys = _ROW_ID_COLUMNS[table]
    values = json.loads(identity)
    if not isinstance(values, list) or len(values) != len(keys):
        raise DomainIntegrityError("canonical row identity is invalid")
    where = " AND ".join(f'"{key}"=?' for key in keys)
    selected = ",".join(f'"{column}"' for column in columns)
    rows = connection.execute(
        f'SELECT {selected} FROM "{table}" WHERE {where}', values
    ).fetchall()
    if len(rows) != 1:
        raise DomainIntegrityError("canonical committed row is missing or duplicated")
    digest = hashlib.sha256(b"ONYX-V3-CANONICAL-ROW-V1\0")
    digest.update(_encode_value(table))
    for column in columns:
        digest.update(_encode_value(column))
    for value in rows[0]:
        digest.update(_encode_value(value))
    return digest.hexdigest()


def _entry(connection: sqlite3.Connection, table: str, *identity: object) -> tuple[str, str, str]:
    encoded = _row_identity(identity)
    return table, encoded, _row_sha256(connection, table, encoded)


def _latest_anchor_head_needs_recovery(connection: sqlite3.Connection) -> bool:
    """Compare only indexed append-only heads; middle gaps belong to the cold audit."""

    intent = connection.execute(
        "SELECT intent_id,anchor_sequence,state_root FROM operational_anchor_intents "
        "ORDER BY anchor_sequence DESC LIMIT 1"
    ).fetchone()
    finalization = connection.execute(
        "SELECT intent_id,anchor_sequence,state_root "
        "FROM operational_anchor_finalizations "
        "ORDER BY anchor_sequence DESC LIMIT 1"
    ).fetchone()
    if intent is None:
        if finalization is not None:
            raise DomainIntegrityError("operational finalization exists without an intent")
        return False
    return finalization != intent


def _relation_id(
    workspace_id: str,
    source_claim_id: str,
    target_claim_id: str,
    relation_kind: str,
) -> str:
    return hashlib.sha256(
        b"ONYX-V3-CLAIM-RELATION\0"
        + _canonical(
            [workspace_id, source_claim_id, target_claim_id, relation_kind]
        ).encode("ascii")
    ).hexdigest()


class DomainLedgerV3Repository(DomainLedgerRepository):
    """Workspace-bound M2a-compatible repository over canonical schema v3."""

    def __init__(
        self,
        migrator: _ControlPlaneV3Migrator,
        owner: V3OwnerCapability,
        registry: WorkspaceRegistry,
        workspace_id: str,
        *,
        enabled: bool,
        _seal: object,
    ):
        if _seal is not _REPOSITORY_SEAL:
            raise TypeError("DomainLedgerV3Repository cannot be constructed directly")
        if not isinstance(registry, WorkspaceRegistry):
            raise TypeError("registry must be a WorkspaceRegistry")
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        if not isinstance(workspace_id, str) or not _SAFE_ID.fullmatch(workspace_id):
            raise DomainIsolationError("an explicit valid workspace_id is required")
        if workspace_id == LEGACY_WORKSPACE_ID:
            raise DomainIsolationError("legacy-default is unavailable to M2b-c records")
        migrator._assert_owner(owner)
        self._migrator = migrator
        self._owner = owner
        self.registry = registry
        self.workspace_id = workspace_id
        self.enabled = enabled
        self._fault: Callable[[str], None] = lambda _point: None
        self._before_commit_test_hook: Callable[
            [sqlite3.Connection, list[tuple[str, str, str]]], None
        ] = lambda _connection, _entries: None

    def initialize(self) -> "DomainLedgerRepository":
        if not self.enabled:
            raise DomainLedgerDisabled(
                f"{LEDGER_V3_FLAG} is disabled; M2b-c is not part of runtime"
            )
        self._migrator._assert_owner(self._owner)
        self._recover_if_needed()
        self._ensure_genesis()
        self._hot_open()
        return self

    @property
    def _path(self) -> Path:
        return self._migrator.port.path

    def _assert_enabled(self) -> None:
        if not self.enabled:
            raise DomainLedgerDisabled(f"{LEDGER_V3_FLAG} is disabled")
        self._migrator._assert_owner(self._owner)

    def _validate_workspace_locked(self, connection: sqlite3.Connection) -> None:
        if self.workspace_id == LEGACY_WORKSPACE_ID:
            raise DomainIsolationError("legacy-default is unavailable to M2b-c records")
        row = connection.execute(
            "SELECT status FROM workspaces WHERE workspace_id=?", (self.workspace_id,)
        ).fetchone()
        if row is None or row[0] != "active":
            raise DomainIsolationError("M2b-c workspace is missing or inactive")
        if connection.execute(
            "SELECT 1 FROM operational_commits LIMIT 1"
        ).fetchone() is not None:
            self._validate_entry_witness(
                connection, "workspaces", self.workspace_id, legacy=False
            )

    def _validate_mission_locked(
        self, connection: sqlite3.Connection, mission_id: str | None
    ) -> None:
        if mission_id is None:
            return
        if not isinstance(mission_id, str) or not _SAFE_ID.fullmatch(mission_id):
            raise DomainContractError("mission_id is invalid")
        row = connection.execute(
            "SELECT workspace_id,operational_phase FROM mission_contexts WHERE mission_id=?",
            (mission_id,),
        ).fetchone()
        if row is None:
            raise DomainIsolationError("mission context is unavailable")
        if row[0] != self.workspace_id:
            raise DomainIsolationError("mission context belongs to another workspace")
        if row[1] == "PENDING_REVIEW":
            raise DomainIsolationError("mission context is pending review")
        self._validate_entry_witness(
            connection, "mission_contexts", mission_id, legacy=False
        )

    def _latest_status_locked(self, connection: sqlite3.Connection):
        operational = _validate_operational_latest(
            connection, allow_projected_finalization=False
        )
        if operational is None:
            return _validate_v3_exact(connection, require_finalization=True)
        commit = operational.commit
        from core.control_plane_v3 import V3Status

        return V3Status(
            str(commit[4]),
            V3_SCHEMA_VERSION,
            str(commit[5]),
            str(commit[6]),
            int(commit[14]),
            int(operational.intent[2]),
            True,
        )

    def _hot_open(self) -> None:
        self._assert_enabled()
        connection = _open_canonical_connection(self._path, read_only=True)
        try:
            status = self._latest_status_locked(connection)
            self._validate_workspace_locked(connection)
        finally:
            connection.close()
        anchored = self._migrator.anchor.verify(self._migrator.anchor_owner)
        if (
            anchored.prepared
            or anchored.database_id != status.database_instance_id
            or anchored.schema_fingerprint != status.schema_fingerprint
            or anchored.ledger_root != status.state_root
            or anchored.sequence != status.anchor_sequence
        ):
            raise DomainIntegrityError("canonical v3 anchor diverges")

    @staticmethod
    def _insert_finalization(connection: sqlite3.Connection) -> None:
        state = _validate_operational_latest(
            connection, allow_projected_finalization=True
        )
        if state is None:
            return
        connection.execute(
            "INSERT OR IGNORE INTO operational_anchor_finalizations VALUES(?,?,?,?,?)",
            state.finalization,
        )
        _validate_operational_latest(connection, allow_projected_finalization=False)

    def _recover_if_needed(self) -> None:
        self._assert_enabled()
        port = self._migrator.port
        port.clear_candidate()
        port.project_pending_finalization()
        try:
            with self._migrator.anchor.writer_session(
                self._migrator.anchor_owner, timeout=_WRITER_TIMEOUT_SECONDS
            ) as session:
                probe = _open_canonical_connection(self._path, read_only=True)
                try:
                    needs_recovery = _latest_anchor_head_needs_recovery(probe)
                finally:
                    probe.close()
                recovered = False
                try:
                    session.verify_baseline()
                except ledger_anchor.LedgerAnchorConflict:
                    session.recover()
                    recovered = True
                if not needs_recovery:
                    if recovered:
                        session.verify_committed()
                    return
                connection = _open_canonical_connection(self._path, read_only=False)
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    self._insert_finalization(connection)
                    connection.execute("COMMIT")
                except BaseException:
                    if connection.in_transaction:
                        try:
                            connection.execute("ROLLBACK")
                        except BaseException:
                            pass
                    raise
                finally:
                    if sys.exception() is None:
                        connection.close()
                    else:
                        try:
                            connection.close()
                        except BaseException:
                            pass
                if recovered:
                    session.verify_committed()
                else:
                    session.verify_baseline()
        except (ledger_anchor.LedgerAnchorError, ControlPlaneV3Error) as exc:
            raise DomainIntegrityError("canonical v3 recovery failed") from exc
        finally:
            active = sys.exception()
            cleanup_error: BaseException | None = None
            for cleanup in (port.clear_candidate, port.clear_pending_finalization):
                try:
                    cleanup()
                except BaseException as error:
                    if active is None and cleanup_error is None:
                        cleanup_error = error
            if cleanup_error is not None:
                raise cleanup_error

    def _ensure_genesis(self) -> None:
        """Atomically anchor the complete migrated and authority baseline once."""

        self._assert_enabled()
        probe = _open_canonical_connection(self._path, read_only=True)
        try:
            if probe.execute("SELECT 1 FROM operational_commits LIMIT 1").fetchone():
                return
        finally:
            probe.close()
        port = self._migrator.port
        port.clear_candidate()
        port.project_pending_finalization()
        connection: sqlite3.Connection | None = None
        sqlite_committed = False
        try:
            with self._migrator.anchor.writer_session(
                self._migrator.anchor_owner, timeout=_WRITER_TIMEOUT_SECONDS
            ) as session:
                baseline = session.verify_baseline()
                connection = _open_canonical_connection(self._path, read_only=False)
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM operational_commits LIMIT 1"
                ).fetchone():
                    connection.execute("ROLLBACK")
                    connection.close()
                    connection = None
                    return
                migration = _validate_v3_exact(
                    connection, require_finalization=True
                )
                if (
                    migration.database_instance_id != baseline.database_id
                    or migration.schema_fingerprint != baseline.schema_fingerprint
                    or migration.state_root != baseline.ledger_root
                    or migration.anchor_sequence != baseline.sequence
                ):
                    raise DomainIntegrityError(
                        "migration baseline changed before genesis"
                    )
                entries = _all_audited_entries(connection)
                intent_id, anchor_sequence, root = self._append_commit_locked(
                    connection, baseline, entries, genesis=True
                )
                port.bind_candidate(connection)
                self._fault("before_genesis_anchor_prepare")
                ticket = session.prepare_candidate()
                if ticket.sequence != anchor_sequence:
                    raise DomainIntegrityError("prepared genesis sequence diverges")
                try:
                    self._fault("after_genesis_anchor_prepare")
                    connection.execute("COMMIT")
                    sqlite_committed = True
                except BaseException:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    port.clear_candidate()
                    raise
                port.clear_candidate()
                connection.close()
                connection = None
                self._fault("after_genesis_sqlite_commit")
                finalized = session.finalize_prepared(ticket)
                if finalized.ledger_root != root:
                    raise DomainIntegrityError("finalized genesis root diverges")
                final = _open_canonical_connection(self._path, read_only=False)
                try:
                    final.execute("BEGIN IMMEDIATE")
                    created_at = str(
                        final.execute(
                            "SELECT created_at FROM operational_anchor_intents "
                            "WHERE intent_id=?", (intent_id,)
                        ).fetchone()[0]
                    )
                    final.execute(
                        "INSERT INTO operational_anchor_finalizations VALUES(?,?,?,?,?)",
                        (
                            _operational_finalization_id(
                                intent_id, anchor_sequence, root, created_at
                            ),
                            intent_id,
                            anchor_sequence,
                            root,
                            created_at,
                        ),
                    )
                    _validate_operational_latest(
                        final, allow_projected_finalization=False
                    )
                    final.execute("COMMIT")
                except BaseException:
                    if final.in_transaction:
                        final.execute("ROLLBACK")
                    raise
                finally:
                    final.close()
                session.verify_committed()
        except DomainLedgerError:
            raise
        except (ledger_anchor.LedgerAnchorError, ControlPlaneV3IntegrityError):
            raise DomainIntegrityError("canonical v3 genesis failed") from None
        except (sqlite3.Error, OSError, ControlPlaneV3Error):
            raise ControlPlaneIOError("canonical v3 genesis storage failed") from None
        finally:
            active = sys.exception()
            cleanup_error: BaseException | None = None
            for cleanup in (port.clear_candidate, port.clear_pending_finalization):
                try:
                    cleanup()
                except BaseException as error:
                    if active is None and cleanup_error is None:
                        cleanup_error = error
            if connection is not None:
                if connection.in_transaction and not sqlite_committed:
                    try:
                        connection.execute("ROLLBACK")
                    except BaseException as error:
                        if active is None and cleanup_error is None:
                            cleanup_error = error
                try:
                    connection.close()
                except BaseException as error:
                    if active is None and cleanup_error is None:
                        cleanup_error = error
            if cleanup_error is not None:
                raise cleanup_error

    def _append_commit_locked(
        self,
        connection: sqlite3.Connection,
        baseline: ledger_anchor.AnchorStatus,
        entries: list[tuple[str, str, str]],
        *,
        genesis: bool = False,
    ) -> tuple[str, int, str]:
        _assert_audited_registry(connection)
        ordered = sorted(entries, key=lambda row: (row[0], row[1]))
        if not ordered or len(set((row[0], row[1]) for row in ordered)) != len(ordered):
            raise DomainIntegrityError("operational commit entries are empty or duplicated")
        if any(row[0] not in _EXPECTED_AUDITED_TABLES for row in ordered):
            raise DomainIntegrityError("operational commit references an unaudited table")
        prior = connection.execute(
            "SELECT commit_id,commit_sequence,state_root,genesis_baseline_root,"
            "canonical_row_count,event_count "
            "FROM operational_commits ORDER BY commit_sequence DESC LIMIT 1"
        ).fetchone()
        if prior is None:
            migration = connection.execute(
                "SELECT commit_id,state_root FROM integrity_commits"
            ).fetchone()
            if migration is None:
                raise DomainIntegrityError("migration integrity commit is unavailable")
            if not genesis:
                raise DomainIntegrityError("operational genesis is required before mutation")
            previous_commit_id, previous_root = migration
            genesis_baseline_root = str(previous_root)
            previous_count = 0
            sequence = 1
            previous_events = 0
        else:
            if genesis:
                raise DomainIntegrityError("operational genesis already exists")
            (
                previous_commit_id, prior_sequence, previous_root,
                genesis_baseline_root, previous_count, previous_events,
            ) = prior
            sequence = int(prior_sequence) + 1
        if baseline.ledger_root != previous_root:
            raise DomainIntegrityError("write baseline changed under the anchor lock")
        delta = _operational_delta_digest(ordered)
        entry_merkle_root, leaves, merkle_nodes = _entry_merkle_tree(ordered)
        created_at = _now()
        metadata = _metadata(connection)
        database_id = _database_instance_id(metadata)
        fingerprint = _actual_v3_fingerprint(connection)
        event_delta = sum(1 for row in ordered if row[0] == "event_envelopes")
        if not genesis and event_delta != 1:
            raise DomainIntegrityError("each repository mutation must append one event")
        row_count = int(previous_count) + len(ordered)
        event_count = (
            int(connection.execute("SELECT count(*) FROM event_envelopes").fetchone()[0])
            if genesis
            else int(previous_events) + event_delta
        )
        payload_root = _operational_payload_root(
            sequence=sequence,
            previous_commit_id=str(previous_commit_id),
            previous_state_root=str(previous_root),
            database_id=database_id,
            fingerprint=fingerprint,
            delta_sha256=delta,
            genesis_baseline_root=str(genesis_baseline_root),
            entry_merkle_root=entry_merkle_root,
            entry_count=len(ordered),
            canonical_row_count=row_count,
            event_count=event_count,
            created_at=created_at,
        )
        commit_id = _operational_commit_id(
            state_root=payload_root,
            sequence=sequence,
            previous_commit_id=str(previous_commit_id),
            delta_sha256=delta,
            created_at=created_at,
        )
        mmr_leaf_hash = _mmr_leaf(commit_id, sequence, payload_root)
        mmr_root, mmr_nodes, mmr_edges, mmr_peaks = _prepare_mmr_append(
            connection, sequence=sequence, leaf_hash=mmr_leaf_hash
        )
        root = _operational_state_root(
            sequence=sequence,
            previous_commit_id=str(previous_commit_id),
            previous_state_root=str(previous_root),
            database_id=database_id,
            fingerprint=fingerprint,
            delta_sha256=delta,
            genesis_baseline_root=str(genesis_baseline_root),
            entry_merkle_root=entry_merkle_root,
            mmr_root=mmr_root,
            mmr_size=sequence,
            entry_count=len(ordered),
            canonical_row_count=row_count,
            event_count=event_count,
            created_at=created_at,
        )
        connection.execute(
            "INSERT INTO operational_commits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                commit_id,
                sequence,
                previous_commit_id,
                previous_root,
                database_id,
                fingerprint,
                root,
                delta,
                genesis_baseline_root,
                entry_merkle_root,
                mmr_root,
                mmr_leaf_hash,
                sequence,
                len(ordered),
                row_count,
                event_count,
                created_at,
            ),
        )
        connection.executemany(
            "INSERT INTO operational_commit_entries VALUES(?,?,?,?,?,?,?)",
            [
                (commit_id, ordinal, table, identity, row_sha, ordinal, leaves[ordinal])
                for ordinal, (table, identity, row_sha) in enumerate(ordered)
            ],
        )
        connection.executemany(
            "INSERT INTO operational_entry_merkle_nodes VALUES(?,?,?,?)",
            [(commit_id, level, index, node_hash) for level, index, node_hash in merkle_nodes],
        )
        connection.executemany(
            "INSERT INTO operational_mmr_nodes VALUES(?,?,?,?,?)",
            mmr_nodes,
        )
        connection.executemany(
            "INSERT INTO operational_mmr_edges VALUES(?,?,?)",
            mmr_edges,
        )
        connection.executemany(
            "INSERT INTO operational_mmr_peaks VALUES(?,?,?,?)",
            mmr_peaks,
        )
        anchor_sequence = baseline.sequence + 1
        intent_id = _operational_intent_id(
            commit_id, anchor_sequence, root, created_at
        )
        connection.execute(
            "INSERT INTO operational_anchor_intents VALUES(?,?,?,?,?,?)",
            (
                intent_id,
                commit_id,
                anchor_sequence,
                root,
                "sqlite_committed",
                created_at,
            ),
        )
        _validate_operational_latest(
            connection, allow_projected_finalization=True
        )
        return intent_id, anchor_sequence, root

    def _write(
        self,
        mutation: Callable[[sqlite3.Connection, list], _T],
        *,
        _recovery_retried: bool = False,
    ) -> _T:
        self._assert_enabled()
        port = self._migrator.port
        port.clear_candidate()
        port.project_pending_finalization()
        sqlite_committed = False
        connection: sqlite3.Connection | None = None
        try:
            with self._migrator.anchor.writer_session(
                self._migrator.anchor_owner, timeout=_WRITER_TIMEOUT_SECONDS
            ) as session:
                try:
                    baseline = session.verify_baseline()
                except ledger_anchor.LedgerAnchorConflict:
                    session.recover()
                    raise _WriteRecoveryRetry from None
                probe = _open_canonical_connection(self._path, read_only=True)
                try:
                    needs_finalization = _latest_anchor_head_needs_recovery(probe)
                finally:
                    probe.close()
                if needs_finalization:
                    recovery = _open_canonical_connection(
                        self._path, read_only=False
                    )
                    try:
                        recovery.execute("BEGIN IMMEDIATE")
                        self._insert_finalization(recovery)
                        recovery.execute("COMMIT")
                    except BaseException:
                        if recovery.in_transaction:
                            try:
                                recovery.execute("ROLLBACK")
                            except BaseException:
                                pass
                        raise
                    finally:
                        recovery.close()
                connection = _open_canonical_connection(self._path, read_only=False)
                connection.execute("BEGIN IMMEDIATE")
                current = self._latest_status_locked(connection)
                if (
                    current.database_instance_id != baseline.database_id
                    or current.schema_fingerprint != baseline.schema_fingerprint
                    or current.state_root != baseline.ledger_root
                    or current.anchor_sequence != baseline.sequence
                ):
                    raise DomainIntegrityError("canonical baseline changed before write")
                self._validate_workspace_locked(connection)
                entries: list[tuple[str, str, str]] = []
                result = mutation(connection, entries)
                if not entries:
                    connection.execute("ROLLBACK")
                    connection.close()
                    connection = None
                    return result
                self._before_commit_test_hook(connection, entries)
                intent_id, anchor_sequence, root = self._append_commit_locked(
                    connection, baseline, entries
                )
                port.bind_candidate(connection)
                self._fault("before_anchor_prepare")
                ticket = session.prepare_candidate()
                if ticket.sequence != anchor_sequence:
                    raise DomainIntegrityError("prepared anchor sequence diverges")
                try:
                    self._fault("after_anchor_prepare")
                    connection.execute("COMMIT")
                    sqlite_committed = True
                except BaseException:
                    # A prepared anchor must recover against durable SQLite,
                    # never the still-bound uncommitted candidate snapshot.
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    port.clear_candidate()
                    raise
                port.clear_candidate()
                connection.close()
                connection = None
                self._fault("after_sqlite_commit")
                finalized = session.finalize_prepared(ticket)
                if finalized.ledger_root != root:
                    raise DomainIntegrityError("finalized anchor root diverges")
                self._fault("after_anchor_finalize")
                final = _open_canonical_connection(self._path, read_only=False)
                try:
                    final.execute("BEGIN IMMEDIATE")
                    intent_created_at = str(
                        final.execute(
                            "SELECT created_at FROM operational_anchor_intents "
                            "WHERE intent_id=?",
                            (intent_id,),
                        ).fetchone()[0]
                    )
                    final.execute(
                        "INSERT OR IGNORE INTO operational_anchor_finalizations "
                        "SELECT ?,intent_id,anchor_sequence,state_root,created_at "
                        "FROM operational_anchor_intents WHERE intent_id=?",
                        (
                            _operational_finalization_id(
                                intent_id,
                                anchor_sequence,
                                root,
                                intent_created_at,
                            ),
                            intent_id,
                        ),
                    )
                    _validate_operational_latest(
                        final, allow_projected_finalization=False
                    )
                    final.execute("COMMIT")
                except BaseException:
                    if final.in_transaction:
                        final.execute("ROLLBACK")
                    raise
                finally:
                    final.close()
                session.verify_committed()
                self._fault("after_finalization_record")
                return result
        except _WriteRecoveryRetry:
            if _recovery_retried:
                raise DomainIntegrityError(
                    "canonical v3 write recovery did not converge"
                ) from None
            return self._write(mutation, _recovery_retried=True)
        except DomainLedgerError:
            raise
        except (ledger_anchor.LedgerAnchorError, ControlPlaneV3IntegrityError) as exc:
            raise DomainIntegrityError("canonical v3 integrity operation failed") from exc
        except (sqlite3.Error, OSError, ControlPlaneV3Error) as exc:
            raise ControlPlaneIOError("canonical v3 durable-state operation failed") from exc
        finally:
            active = sys.exception()
            cleanup_error: BaseException | None = None
            for cleanup in (port.clear_candidate, port.clear_pending_finalization):
                try:
                    cleanup()
                except BaseException as error:
                    if active is None and cleanup_error is None:
                        cleanup_error = error
            if connection is not None:
                if connection.in_transaction and not sqlite_committed:
                    try:
                        connection.execute("ROLLBACK")
                    except BaseException as error:
                        if active is None and cleanup_error is None:
                            cleanup_error = error
                try:
                    connection.close()
                except BaseException as error:
                    if active is None and cleanup_error is None:
                        cleanup_error = error
            if cleanup_error is not None:
                raise cleanup_error

    def _validate_entry_witness(
        self,
        connection: sqlite3.Connection,
        table: str,
        *identity: object,
        legacy: bool,
    ) -> None:
        encoded = _row_identity(identity)
        actual = _row_sha256(connection, table, encoded)
        row = connection.execute(
            "SELECT e.entry_ordinal,e.row_sha256,e.leaf_index,e.leaf_hash,c.* "
            "FROM operational_commit_entries e JOIN operational_commits c "
            "ON c.commit_id=e.commit_id WHERE e.table_name=? AND e.row_identity=?",
            (table, encoded),
        ).fetchone()
        if row is None:
            raise DomainIntegrityError("canonical row has no commit witness")
        entry_ordinal, row_sha, leaf_index, leaf_hash, *commit = row
        if len(commit) != 17:
            raise DomainIntegrityError("operational witness commit is invalid")
        (
            commit_id, sequence, previous_commit_id, previous_root, database_id,
            fingerprint, state_root, delta_sha256, genesis_baseline_root,
            entry_merkle_root, mmr_root, mmr_leaf_hash, mmr_size, entry_count,
            canonical_row_count, event_count, created_at,
        ) = commit
        for field, digest in (
            ("row_sha256", row_sha),
            ("entry leaf hash", leaf_hash),
            ("commit id", commit_id),
            ("previous commit id", previous_commit_id),
            ("previous state root", previous_root),
            ("schema fingerprint", fingerprint),
            ("state root", state_root),
            ("delta digest", delta_sha256),
            ("genesis baseline root", genesis_baseline_root),
            ("entry Merkle root", entry_merkle_root),
            ("MMR root", mmr_root),
            ("MMR leaf hash", mmr_leaf_hash),
        ):
            _require_sha256_digest(digest, field)
        if (
            type(entry_ordinal) is not int
            or type(leaf_index) is not int
            or entry_ordinal != leaf_index
            or type(sequence) is not int
            or sequence < 1
            or type(mmr_size) is not int
            or mmr_size != sequence
            or type(entry_count) is not int
            or not 0 <= leaf_index < entry_count
            or type(canonical_row_count) is not int
            or canonical_row_count < entry_count
            or type(event_count) is not int
            or event_count < 0
            or not isinstance(created_at, str)
            or not _valid_utc_timestamp(created_at)
        ):
            raise DomainIntegrityError("operational witness commit fields are invalid")
        if sequence == 1:
            predecessor = connection.execute(
                "SELECT commit_id,state_root,database_instance_id,schema_fingerprint "
                "FROM integrity_commits"
            ).fetchone()
            predecessor_count = 0
        else:
            predecessor = connection.execute(
                "SELECT commit_id,state_root,database_instance_id,schema_fingerprint,"
                "canonical_row_count,genesis_baseline_root FROM operational_commits "
                "WHERE commit_sequence=?",
                (sequence - 1,),
            ).fetchone()
            predecessor_count = int(predecessor[4]) if predecessor is not None else -1
        metadata = _metadata(connection)
        if (
            predecessor is None
            or predecessor[0] != previous_commit_id
            or predecessor[1] != previous_root
            or predecessor[2] != database_id
            or predecessor[3] != fingerprint
            or database_id != _database_instance_id(metadata)
            or fingerprint != _actual_v3_fingerprint(connection)
            or predecessor_count + entry_count != canonical_row_count
            or (sequence == 1 and genesis_baseline_root != predecessor[1])
            or (sequence > 1 and genesis_baseline_root != predecessor[5])
        ):
            raise DomainIntegrityError("operational witness predecessor diverges")
        if row_sha != actual:
            raise DomainIntegrityError("canonical row diverges from its commit witness")
        expected_leaf = hashlib.sha256(b"ONYX-V3-ENTRY-MERKLE-LEAF-V1\0")
        for value in (int(leaf_index), table, encoded, actual):
            expected_leaf.update(_encode_value(value))
        current_hash = expected_leaf.hexdigest()
        if current_hash != leaf_hash:
            raise DomainIntegrityError("canonical row Merkle leaf diverges")
        index = int(leaf_index)
        width = int(entry_count)
        level = 0
        while width > 1:
            sibling_index = index ^ 1
            if sibling_index >= width:
                sibling_hash = current_hash
            else:
                sibling = connection.execute(
                    "SELECT node_hash FROM operational_entry_merkle_nodes "
                    "WHERE commit_id=? AND tree_level=? AND node_index=?",
                    (commit_id, level, sibling_index),
                ).fetchone()
                if sibling is None:
                    raise DomainIntegrityError("canonical row Merkle path is incomplete")
                sibling_hash = _require_sha256_digest(
                    sibling[0], "entry Merkle sibling hash"
                )
            current_hash = (
                hashlib.sha256(
                    b"ONYX-V3-ENTRY-MERKLE-NODE-V1\0"
                    + bytes.fromhex(current_hash)
                    + bytes.fromhex(sibling_hash)
                ).hexdigest()
                if index % 2 == 0
                else hashlib.sha256(
                    b"ONYX-V3-ENTRY-MERKLE-NODE-V1\0"
                    + bytes.fromhex(sibling_hash)
                    + bytes.fromhex(current_hash)
                ).hexdigest()
            )
            index //= 2
            width = (width + 1) // 2
            level += 1
        if current_hash != entry_merkle_root:
            raise DomainIntegrityError("canonical row Merkle root diverges")

        payload_root = _operational_payload_root(
            sequence=sequence,
            previous_commit_id=str(previous_commit_id),
            previous_state_root=str(previous_root),
            database_id=str(database_id),
            fingerprint=str(fingerprint),
            delta_sha256=str(delta_sha256),
            genesis_baseline_root=str(genesis_baseline_root),
            entry_merkle_root=current_hash,
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
        expected_mmr_leaf = _mmr_leaf(expected_commit_id, sequence, payload_root)
        historical_peaks_list: list[tuple[int, str]] = []
        for height, peak_hash in connection.execute(
            "SELECT peak_height,peak_hash FROM operational_mmr_peaks "
            "WHERE commit_sequence=? ORDER BY peak_ordinal", (sequence,)
        ).fetchall():
            if type(height) is not int or height < 0:
                raise DomainIntegrityError("operational MMR peak height is invalid")
            historical_peaks_list.append(
                (height, _require_sha256_digest(peak_hash, "MMR peak hash"))
            )
        historical_peaks = tuple(historical_peaks_list)
        expected_state_root = _operational_state_root(
            sequence=sequence,
            previous_commit_id=str(previous_commit_id),
            previous_state_root=str(previous_root),
            database_id=str(database_id),
            fingerprint=str(fingerprint),
            delta_sha256=str(delta_sha256),
            genesis_baseline_root=str(genesis_baseline_root),
            entry_merkle_root=current_hash,
            mmr_root=str(mmr_root),
            mmr_size=mmr_size,
            entry_count=entry_count,
            canonical_row_count=canonical_row_count,
            event_count=event_count,
            created_at=created_at,
        )
        if (
            commit_id != expected_commit_id
            or mmr_leaf_hash != expected_mmr_leaf
            or not historical_peaks
            or mmr_root != _mmr_bag(historical_peaks)
            or state_root != expected_state_root
        ):
            raise DomainIntegrityError("canonical row commit membership diverges")

        current_hash = expected_mmr_leaf
        visited: set[str] = set()
        while True:
            if current_hash in visited:
                raise DomainIntegrityError("operational MMR path contains a cycle")
            visited.add(current_hash)
            edge = connection.execute(
                "SELECT parent_hash,side FROM operational_mmr_edges WHERE child_hash=?",
                (current_hash,),
            ).fetchone()
            if edge is None:
                break
            parent_hash = _require_sha256_digest(edge[0], "MMR parent hash")
            side = edge[1]
            if type(side) is not int or side not in (0, 1):
                raise DomainIntegrityError("operational MMR edge side is invalid")
            parent = connection.execute(
                "SELECT node_height,left_hash,right_hash FROM operational_mmr_nodes "
                "WHERE node_hash=?", (parent_hash,)
            ).fetchone()
            if parent is not None:
                node_height, left_hash, right_hash = parent
                if type(node_height) is not int or node_height < 1:
                    raise DomainIntegrityError("operational MMR node height is invalid")
                left_hash = _require_sha256_digest(left_hash, "MMR left hash")
                right_hash = _require_sha256_digest(right_hash, "MMR right hash")
            if (
                parent is None
                or _mmr_parent(node_height, left_hash, right_hash) != parent_hash
                or (left_hash, right_hash)[side] != current_hash
            ):
                raise DomainIntegrityError("operational MMR membership path diverges")
            current_hash = parent_hash
        latest = connection.execute(
            "SELECT commit_sequence,mmr_root FROM operational_commits "
            "ORDER BY commit_sequence DESC LIMIT 1"
        ).fetchone()
        if latest is None:
            raise DomainIntegrityError("operational MMR head is unavailable")
        if type(latest[0]) is not int:
            raise DomainIntegrityError("operational MMR head sequence is invalid")
        _require_sha256_digest(latest[1], "operational MMR head root")
        peaks = []
        for height, peak_hash in connection.execute(
            "SELECT peak_height,peak_hash FROM operational_mmr_peaks "
            "WHERE commit_sequence=? ORDER BY peak_ordinal", (latest[0],)
        ).fetchall():
            if type(height) is not int or height < 0:
                raise DomainIntegrityError("operational MMR head peak height is invalid")
            peaks.append(
                (height, _require_sha256_digest(peak_hash, "MMR head peak hash"))
            )
        if current_hash not in {peak_hash for _height, peak_hash in peaks}:
            raise DomainIntegrityError("operational MMR proof does not reach the head")
        if _mmr_bag(peaks) != latest[1]:
            raise DomainIntegrityError("operational MMR head diverges")

    def _validate_artifact_locked(
        self,
        connection: sqlite3.Connection,
        artifact_id: str,
        *,
        workspace_id: str | None = None,
        content_sha256: str | None = None,
        require_available: bool,
    ) -> tuple[object, ...]:
        row = connection.execute(
            "SELECT artifact_id,workspace_id,schema_version,sha256,relative_path,"
            "media_type,status,created_at FROM artifact_index WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise DomainContractError("artifact reference is unavailable in this workspace")
        (
            stored_id, stored_workspace, schema_version, stored_sha, relative_path,
            media_type, status, created_at,
        ) = row
        expected_path = (
            f"{str(stored_sha)[:2]}/{stored_sha}"
            if isinstance(stored_sha, str) and len(stored_sha) == 64
            else None
        )
        if (
            stored_id != artifact_id
            or not isinstance(stored_workspace, str)
            or type(schema_version) is not int
            or schema_version != 2
            or not isinstance(stored_sha, str)
            or len(stored_sha) != 64
            or stored_sha != stored_sha.lower()
            or any(character not in "0123456789abcdef" for character in stored_sha)
            or relative_path != expected_path
            or not isinstance(media_type, str)
            or not media_type
            or not isinstance(status, str)
            or not status
            or not isinstance(created_at, str)
            or not _valid_utc_timestamp(created_at)
            or (workspace_id is not None and stored_workspace != workspace_id)
            or (content_sha256 is not None and stored_sha != content_sha256)
            or (require_available and status != "available")
        ):
            raise DomainIntegrityError("artifact index row is not canonical")
        self._validate_entry_witness(
            connection, "artifact_index", artifact_id, legacy=False
        )
        return tuple(row)

    def _evidence_from_v3(
        self, connection: sqlite3.Connection, row: Iterable[object]
    ) -> EvidenceRecord:
        values = tuple(row)
        if len(values) != 19:
            raise DomainIntegrityError("v3 evidence row width is invalid")
        record = DomainLedgerRepository._evidence_from_row(
            (
                values[0], values[1], values[2], DOMAIN_CONTRACT_VERSION,
                values[7], values[17], values[18],
            )
        )
        expected = (
            record.evidence_id, record.workspace_id, record.mission_id,
            V3_SCHEMA_VERSION, record.correlation_id, record.source_kind,
            record.source_identity_sha256, record.content_sha256, record.artifact_id,
            record.credibility_bp, record.freshness, record.validity_seconds,
            record.observed_at, record.valid_until, record.access_license_sha256,
            record.input_sha256, _record_digest(record), values[17], record.created_at,
        )
        if values != expected:
            raise DomainIntegrityError("v3 evidence typed fields diverge")
        legacy_row = connection.execute(
            "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
            "payload_json,created_at FROM legacy_v2_evidence_records WHERE evidence_id=?",
            (record.evidence_id,),
        ).fetchone()
        if legacy_row is not None:
            if DomainLedgerRepository._evidence_from_row(legacy_row) != record:
                raise DomainIntegrityError("migrated evidence prefix diverges")
        if record.artifact_id is not None:
            self._validate_artifact_locked(
                connection,
                record.artifact_id,
                workspace_id=record.workspace_id,
                content_sha256=record.content_sha256,
                require_available=True,
            )
        self._validate_entry_witness(
            connection, "evidence_records", record.evidence_id,
            legacy=legacy_row is not None,
        )
        return record

    def _claim_from_v3(
        self, connection: sqlite3.Connection, row: Iterable[object]
    ) -> ClaimRecord:
        values = tuple(row)
        if len(values) != 15:
            raise DomainIntegrityError("v3 claim row width is invalid")
        record = DomainLedgerRepository._claim_from_row(
            (
                values[0], values[1], DOMAIN_CONTRACT_VERSION, values[8],
                values[13], values[14], values[14],
            )
        )
        expected = (
            record.claim_id, record.workspace_id, record.mission_id,
            V3_SCHEMA_VERSION, record.correlation_id, record.claim_kind,
            record.statement_sha256, record.confidence_bp,
            record.verification_status, record.validity_seconds,
            record.valid_until, record.input_sha256, _record_digest(record),
            values[13], record.created_at,
        )
        if values != expected:
            raise DomainIntegrityError("v3 claim typed fields diverge")
        legacy_row = connection.execute(
            "SELECT claim_id,workspace_id,schema_version,verification_status,payload_json,"
            "created_at,updated_at FROM legacy_v2_claims WHERE claim_id=?",
            (record.claim_id,),
        ).fetchone()
        if legacy_row is not None:
            if DomainLedgerRepository._claim_from_row(legacy_row) != record:
                raise DomainIntegrityError("migrated claim prefix diverges")
        self._validate_entry_witness(
            connection, "claims", record.claim_id, legacy=legacy_row is not None
        )
        return record

    def _request_from_v3(
        self, connection: sqlite3.Connection, row: Iterable[object]
    ) -> ActionRequestRecord:
        values = tuple(row)
        if len(values) != 20:
            raise DomainIntegrityError("v3 request row width is invalid")
        initial = DomainLedgerRepository._request_from_row(
            (
                values[0], values[1], values[2], DOMAIN_CONTRACT_VERSION,
                values[5], "proposed", values[9], values[18], values[19], values[19],
            )
        )
        if values[17] != _record_digest(initial):
            raise DomainIntegrityError("v3 request base digest diverges")
        states = connection.execute(
            "SELECT request_id,state_sequence,workspace_id,mission_id,state,source_event_id,"
            "source_receipt_id,request_record_sha256,record_sha256,created_at "
            "FROM action_state_history WHERE request_id=? ORDER BY state_sequence",
            (initial.request_id,),
        ).fetchall()
        if not states or [state[1] for state in states] != list(range(len(states))):
            raise DomainIntegrityError("v3 request state history is incomplete")
        for state in states:
            if state[8] != _typed_record_digest("action_state", (*state[:8], state[9])):
                raise DomainIntegrityError("v3 request state digest diverges")
            legacy_state = connection.execute(
                "SELECT 1 FROM legacy_v2_action_requests WHERE request_id=?",
                (initial.request_id,),
            ).fetchone() is not None
            self._validate_entry_witness(
                connection,
                "action_state_history",
                state[0], state[1],
                legacy=legacy_state,
            )
        latest = states[-1]
        record = replace(initial, status=str(latest[4]), updated_at=str(latest[9]))
        typed = (
            record.request_id, record.workspace_id, record.mission_id,
            V3_SCHEMA_VERSION, record.correlation_id, record.idempotency_key,
            record.connector, record.operation, record.target_sha256,
            record.payload_sha256, record.risk, record.approval_policy,
            record.data_class, 1, record.verification_plan_sha256,
            record.rollback_plan_sha256, record.input_sha256,
            _record_digest(initial), values[18], record.created_at,
        )
        if values != typed:
            raise DomainIntegrityError("v3 request typed fields diverge")
        legacy_row = connection.execute(
            "SELECT request_id,workspace_id,mission_id,schema_version,idempotency_key,status,"
            "payload_sha256,payload_json,created_at,updated_at "
            "FROM legacy_v2_action_requests WHERE request_id=?",
            (record.request_id,),
        ).fetchone()
        if legacy_row is not None:
            legacy_record = DomainLedgerRepository._request_from_row(legacy_row)
            # M2a persists the request update immediately after constructing
            # the receipt event, so only updated_at may be later than the
            # derived terminal event timestamp.  Preserve the exact v2 API
            # record while retaining the independently verified state chain.
            if replace(legacy_record, updated_at=record.updated_at) != record:
                raise DomainIntegrityError("migrated request prefix diverges")
            record = legacy_record
        self._validate_entry_witness(
            connection, "action_requests", record.request_id,
            legacy=legacy_row is not None,
        )
        return record

    def _receipt_from_v3(
        self, connection: sqlite3.Connection, row: Iterable[object]
    ) -> ActionReceiptRecord:
        values = tuple(row)
        if len(values) != 22:
            raise DomainIntegrityError("v3 receipt row width is invalid")
        record = DomainLedgerRepository._receipt_from_row(
            (
                values[0], values[1], DOMAIN_CONTRACT_VERSION, values[6],
                values[20], values[21], values[2],
            )
        )
        legacy_row = connection.execute(
            "SELECT r.receipt_id,r.request_id,r.schema_version,r.outcome,r.payload_json,"
            "r.created_at,q.workspace_id FROM legacy_v2_action_receipts r "
            "JOIN legacy_v2_action_requests q ON q.request_id=r.request_id "
            "WHERE r.receipt_id=?",
            (record.receipt_id,),
        ).fetchone()
        request = self._get_action_request_locked(connection, record.request_id)
        state = connection.execute(
            "SELECT state,created_at,source_event_id FROM action_state_history "
            "WHERE request_id=? AND source_receipt_id=?",
            (record.request_id, record.receipt_id),
        ).fetchone()
        if state is None:
            raise DomainIntegrityError("receipt has no derived request state")
        historical_request = replace(
            request, status=str(state[0]), updated_at=str(state[1])
        )
        expected = (
            record.receipt_id, record.request_id, record.workspace_id,
            request.mission_id, V3_SCHEMA_VERSION, record.correlation_id,
            record.outcome, record.provider_request_sha256, record.before_sha256,
            record.after_sha256, record.output_sha256, record.verification_sha256,
            record.rollback_sha256, record.error_class, record.supersedes_receipt_id,
            int(record.reconciliation), record.input_sha256, _record_digest(record),
            values[18], record.observed_at, values[20], record.created_at,
        )
        if legacy_row is None:
            parent_valid = values[18] == _record_digest(historical_request)
        else:
            event_parent = connection.execute(
                "SELECT parent_entity_sha256 FROM event_envelopes "
                "WHERE event_id=? AND workspace_id=? AND correlation_id=? "
                "AND entity_type='action_receipt' AND entity_id=? "
                "AND parent_entity_id=?",
                (
                    state[2], record.workspace_id, record.correlation_id,
                    record.receipt_id, record.request_id,
                ),
            ).fetchone()
            parent_valid = event_parent == (values[18],)
        if values != expected or not parent_valid:
            raise DomainIntegrityError("v3 receipt typed fields diverge")
        if legacy_row is not None:
            if DomainLedgerRepository._receipt_from_row(legacy_row) != record:
                raise DomainIntegrityError("migrated receipt prefix diverges")
        self._validate_entry_witness(
            connection, "action_receipts", record.receipt_id,
            legacy=legacy_row is not None,
        )
        return record

    def _event_from_v3(
        self, connection: sqlite3.Connection, row: Iterable[object]
    ) -> EventEnvelope:
        values = tuple(row)
        if len(values) != 16:
            raise DomainIntegrityError("v3 event row width is invalid")
        event = DomainLedgerRepository._event_from_row(
            (
                values[0], values[1], values[2], values[3],
                DOMAIN_CONTRACT_VERSION, values[6], values[14], values[12],
                values[13], values[15],
            )
        )
        expected = (
            event.event_id, event.workspace_id, event.mission_id,
            event.correlation_id, values[4], V3_SCHEMA_VERSION,
            event.event_type, event.entity_type, event.entity_id,
            event.entity_sha256, event.parent_entity_id,
            event.parent_entity_sha256, event.previous_hash, event.event_hash,
            values[14], event.created_at,
        )
        if values != expected:
            raise DomainIntegrityError("v3 event typed fields diverge")
        legacy_row = connection.execute(
            "SELECT event_id,workspace_id,mission_id,correlation_id,schema_version,event_type,"
            "payload_json,previous_hash,event_hash,created_at "
            "FROM legacy_v2_event_envelopes WHERE event_id=?",
            (event.event_id,),
        ).fetchone()
        if legacy_row is not None:
            if DomainLedgerRepository._event_from_row(legacy_row) != event:
                raise DomainIntegrityError("migrated event prefix diverges")
        self._validate_entry_witness(
            connection, "event_envelopes", event.event_id,
            legacy=legacy_row is not None,
        )
        return event

    def _read(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        self._assert_enabled()
        try:
            anchored = self._migrator.anchor.verify(self._migrator.anchor_owner)
            connection = _open_canonical_connection(self._path, read_only=True)
            try:
                connection.execute("BEGIN")
                status = self._latest_status_locked(connection)
                self._validate_workspace_locked(connection)
                if (
                    anchored.prepared
                    or anchored.database_id != status.database_instance_id
                    or anchored.schema_fingerprint != status.schema_fingerprint
                    or anchored.ledger_root != status.state_root
                    or anchored.sequence != status.anchor_sequence
                ):
                    raise DomainIntegrityError("canonical read baseline diverges")
                return operation(connection)
            finally:
                active = sys.exception()
                cleanup_error: BaseException | None = None
                try:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                except BaseException as error:
                    if active is None:
                        cleanup_error = error
                try:
                    connection.close()
                except BaseException as error:
                    if active is None and cleanup_error is None:
                        cleanup_error = error
                if cleanup_error is not None:
                    raise cleanup_error
        except DomainLedgerError:
            raise
        except (ledger_anchor.LedgerAnchorError, ControlPlaneV3IntegrityError) as exc:
            raise DomainIntegrityError("canonical v3 read integrity failed") from exc
        except (sqlite3.Error, OSError, ControlPlaneV3Error) as exc:
            raise ControlPlaneIOError("canonical v3 read failed") from exc

    def _latest_head_locked(
        self, connection: sqlite3.Connection, correlation_id: str
    ) -> tuple[object, ...] | None:
        row = connection.execute(
            "SELECT workspace_id,correlation_id,head_revision,event_count,head_hash,"
            "first_event_id,last_event_id,previous_head_hash FROM event_chain_heads "
            "WHERE workspace_id=? AND correlation_id=? ORDER BY head_revision DESC LIMIT 1",
            (self.workspace_id, correlation_id),
        ).fetchone()
        if row is None:
            return None
        history = connection.execute(
            "SELECT event_id,event_hash FROM event_chain_history WHERE workspace_id=? "
            "AND correlation_id=? AND event_sequence=?",
            (self.workspace_id, correlation_id, int(row[3]) - 1),
        ).fetchone()
        if history != (row[6], row[4]):
            raise DomainIntegrityError("event head diverges from its last event")
        if int(row[2]) > 0:
            self._validate_entry_witness(
                connection,
                "event_chain_heads",
                row[0], row[1], row[2],
                legacy=False,
            )
        else:
            projection_id = _entity_id("event-head", self.workspace_id, correlation_id)
            legacy = connection.execute(
                "SELECT payload_json FROM legacy_v2_projections WHERE projection_id=?",
                (projection_id,),
            ).fetchone()
            if legacy is None:
                self._validate_entry_witness(
                    connection,
                    "event_chain_heads",
                    row[0], row[1], row[2],
                    legacy=False,
                )
            else:
                payload = json.loads(str(legacy[0]))
                if (
                    payload.get("correlation_id") != correlation_id
                    or payload.get("event_count") != row[3]
                    or payload.get("head_hash") != row[4]
                ):
                    raise DomainIntegrityError("migrated event head prefix diverges")
        return tuple(row)

    def _append_event_locked(
        self,
        connection: sqlite3.Connection,
        entries: list[tuple[str, str, str]],
        *,
        mission_id: str | None,
        correlation_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        entity_sha256: str,
        parent_entity_id: str | None = None,
        parent_entity_sha256: str | None = None,
    ) -> EventEnvelope:
        head = self._latest_head_locked(connection, correlation_id)
        previous_hash = str(head[4]) if head else _ZERO_HASH
        sequence = int(head[3]) if head else 0
        payload_text = _canonical(
            {
                "actor": "m2a-shadow-repository",
                "contract": "EventEnvelope.v1",
                "entity_id": entity_id,
                "entity_sha256": entity_sha256,
                "entity_type": entity_type,
                "parent_entity_id": parent_entity_id,
                "parent_entity_sha256": parent_entity_sha256,
            }
        )
        created_at = _now()
        event_id = _event_identity(
            self.workspace_id,
            mission_id,
            correlation_id,
            event_type,
            payload_text,
            previous_hash,
            created_at,
        )
        event_hash = _row_digest(
            (
                event_id,
                self.workspace_id,
                mission_id,
                correlation_id,
                DOMAIN_CONTRACT_VERSION,
                event_type,
                payload_text,
                previous_hash,
                created_at,
            )
        )
        connection.execute(
            "INSERT INTO event_envelopes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id, self.workspace_id, mission_id, correlation_id, sequence,
                V3_SCHEMA_VERSION, event_type, entity_type, entity_id, entity_sha256,
                parent_entity_id, parent_entity_sha256, previous_hash, event_hash,
                payload_text, created_at,
            ),
        )
        entries.append(_entry(connection, "event_envelopes", event_id))
        connection.execute(
            "INSERT INTO event_chain_history VALUES(?,?,?,?,?,?)",
            (
                self.workspace_id, correlation_id, sequence, event_id,
                previous_hash, event_hash,
            ),
        )
        entries.append(
            _entry(
                connection,
                "event_chain_history",
                self.workspace_id,
                correlation_id,
                sequence,
            )
        )
        head_revision = int(head[2]) + 1 if head else 0
        first_event_id = str(head[5]) if head else event_id
        connection.execute(
            "INSERT INTO event_chain_heads VALUES(?,?,?,?,?,?,?,?)",
            (
                self.workspace_id,
                correlation_id,
                head_revision,
                sequence + 1,
                event_hash,
                first_event_id,
                event_id,
                str(head[4]) if head else None,
            ),
        )
        entries.append(
            _entry(
                connection,
                "event_chain_heads",
                self.workspace_id,
                correlation_id,
                head_revision,
            )
        )
        projection_id = _entity_id("event-head", self.workspace_id, correlation_id)
        prior_projection = connection.execute(
            "SELECT projection_revision,created_at,state_sha256 FROM projections "
            "WHERE workspace_id=? AND projection_id=? "
            "ORDER BY projection_revision DESC LIMIT 1",
            (self.workspace_id, projection_id),
        ).fetchone()
        projection_revision = int(prior_projection[0]) + 1 if prior_projection else 0
        projection_created_at = (
            str(prior_projection[1]) if prior_projection else created_at
        )
        head_payload = _canonical(
            {
                "contract": "EventChainHead.v1",
                "correlation_id": correlation_id,
                "event_count": sequence + 1,
                "head_hash": event_hash,
            }
        )
        projection_values = (
            projection_id,
            projection_revision,
            self.workspace_id,
            mission_id,
            V3_SCHEMA_VERSION,
            "m2a_event_chain_head",
            correlation_id,
            head_revision,
            sequence + 1,
            event_id,
            event_hash,
            str(prior_projection[2]) if prior_projection else None,
            head_payload,
            projection_created_at,
            created_at,
        )
        connection.execute(
            "INSERT INTO projections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                *projection_values[:12],
                _typed_record_digest("projection", projection_values),
                *projection_values[12:],
            ),
        )
        entries.append(
            _entry(
                connection,
                "projections",
                self.workspace_id,
                projection_id,
                projection_revision,
            )
        )
        return DomainLedgerRepository._event_from_row(
            (
                event_id, self.workspace_id, mission_id, correlation_id,
                DOMAIN_CONTRACT_VERSION, event_type, payload_text, previous_hash,
                event_hash, created_at,
            )
        )

    def _get_action_request_locked(
        self, connection: sqlite3.Connection, request_id: str
    ) -> ActionRequestRecord:
        row = connection.execute(
            "SELECT * FROM action_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            raise DomainIsolationError("action request is unavailable in this workspace")
        record = self._request_from_v3(connection, row)
        if record.workspace_id != self.workspace_id:
            raise DomainIsolationError("action request is unavailable in this workspace")
        return record

    def get_evidence(self, evidence_id: str) -> EvidenceRecord:
        def read(connection: sqlite3.Connection) -> EvidenceRecord:
            row = connection.execute(
                "SELECT * FROM evidence_records WHERE evidence_id=?", (evidence_id,)
            ).fetchone()
            if row is None:
                raise DomainIsolationError("evidence is unavailable in this workspace")
            record = self._evidence_from_v3(connection, row)
            if record.workspace_id != self.workspace_id:
                raise DomainIsolationError("evidence is unavailable in this workspace")
            return record

        return self._read(read)

    def list_evidence(
        self, *, mission_id: str | None = None
    ) -> tuple[EvidenceRecord, ...]:
        def read(connection: sqlite3.Connection) -> tuple[EvidenceRecord, ...]:
            self._validate_mission_locked(connection, mission_id)
            rows = connection.execute(
                "SELECT * FROM evidence_records WHERE workspace_id=? AND "
                "(? IS NULL OR mission_id=?) ORDER BY created_at,evidence_id",
                (self.workspace_id, mission_id, mission_id),
            ).fetchall()
            return tuple(self._evidence_from_v3(connection, row) for row in rows)

        return self._read(read)

    def get_claim(self, claim_id: str) -> ClaimRecord:
        def read(connection: sqlite3.Connection) -> ClaimRecord:
            row = connection.execute(
                "SELECT * FROM claims WHERE claim_id=?", (claim_id,)
            ).fetchone()
            if row is None:
                raise DomainIsolationError("claim is unavailable in this workspace")
            record = self._claim_from_v3(connection, row)
            if record.workspace_id != self.workspace_id:
                raise DomainIsolationError("claim is unavailable in this workspace")
            return record

        return self._read(read)

    def list_claims(
        self, *, mission_id: str | None = None
    ) -> tuple[ClaimRecord, ...]:
        def read(connection: sqlite3.Connection) -> tuple[ClaimRecord, ...]:
            self._validate_mission_locked(connection, mission_id)
            rows = connection.execute(
                "SELECT * FROM claims WHERE workspace_id=? AND "
                "(? IS NULL OR mission_id=?) ORDER BY created_at,claim_id",
                (self.workspace_id, mission_id, mission_id),
            ).fetchall()
            return tuple(self._claim_from_v3(connection, row) for row in rows)

        return self._read(read)

    def get_action_request(self, request_id: str) -> ActionRequestRecord:
        return self._read(
            lambda connection: self._get_action_request_locked(connection, request_id)
        )

    def get_receipt(self, receipt_id: str) -> ActionReceiptRecord:
        def read(connection: sqlite3.Connection) -> ActionReceiptRecord:
            row = connection.execute(
                "SELECT * FROM action_receipts WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
            if row is None:
                raise DomainIsolationError("action receipt is unavailable in this workspace")
            record = self._receipt_from_v3(connection, row)
            if record.workspace_id != self.workspace_id:
                raise DomainIsolationError("action receipt is unavailable in this workspace")
            return record

        return self._read(read)

    def list_receipts(self, request_id: str) -> tuple[ActionReceiptRecord, ...]:
        def read(connection: sqlite3.Connection) -> tuple[ActionReceiptRecord, ...]:
            request = self._get_action_request_locked(connection, request_id)
            rows = connection.execute(
                "SELECT r.* FROM action_receipts r JOIN event_envelopes e "
                "ON e.entity_id=r.receipt_id WHERE r.request_id=? "
                "ORDER BY e.event_sequence",
                (request.request_id,),
            ).fetchall()
            return tuple(self._receipt_from_v3(connection, row) for row in rows)

        return self._read(read)

    def list_events(self, correlation_id: str) -> tuple[EventEnvelope, ...]:
        if not isinstance(correlation_id, str) or not _CORRELATION_ID.fullmatch(
            correlation_id
        ):
            raise DomainContractError("correlation_id is invalid")

        def read(connection: sqlite3.Connection) -> tuple[EventEnvelope, ...]:
            rows = connection.execute(
                "SELECT * FROM event_envelopes WHERE workspace_id=? AND correlation_id=? "
                "ORDER BY event_sequence",
                (self.workspace_id, correlation_id),
            ).fetchall()
            events = tuple(self._event_from_v3(connection, row) for row in rows)
            if any(
                event.previous_hash != (events[index - 1].event_hash if index else _ZERO_HASH)
                for index, event in enumerate(events)
            ):
                raise DomainIntegrityError("event chain is disconnected")
            head = self._latest_head_locked(connection, correlation_id)
            if events and (
                head is None
                or int(head[3]) != len(events)
                or head[4] != events[-1].event_hash
            ):
                raise DomainIntegrityError("event chain head diverges")
            if not events and head is not None:
                raise DomainIntegrityError("event head exists without events")
            return events

        return self._read(read)

    def record_evidence(
        self,
        caller_key: str,
        correlation_key: str,
        source_kind: str,
        source_identity: bytes | str,
        content: bytes | str,
        *,
        mission_id: str | None = None,
        credibility_bp: int = 5_000,
        freshness: str = "unknown",
        validity_seconds: int | None = None,
        artifact_id: str | None = None,
        access_license_note: bytes | str = "",
    ) -> EvidenceRecord:
        caller = _safe_key(caller_key, "caller_key")
        correlation_key = _safe_key(correlation_key, "correlation_key")
        source_kind = _enum(source_kind, _SOURCE_KINDS, "source_kind")
        credibility = _basis_points(credibility_bp, "credibility_bp")
        freshness = _enum(freshness, _FRESHNESS, "freshness")
        validity = _validity_seconds(validity_seconds)
        source_hash = _sha(_safe_material(source_identity, "source_identity"))
        content_hash = _sha(_safe_material(content, "content"))
        access_hash = _sha(
            _safe_material(access_license_note, "access_license_note", allow_empty=True)
        )
        if artifact_id is not None:
            artifact_id = _safe_key(artifact_id, "artifact_id")
        correlation = _correlation_id(self.workspace_id, correlation_key)
        evidence_id = _entity_id("evidence", self.workspace_id, caller)
        semantic = {
            "artifact_id": artifact_id,
            "content_sha256": content_hash,
            "correlation_id": correlation,
            "credibility_bp": credibility,
            "freshness": freshness,
            "mission_id": mission_id,
            "source_identity_sha256": source_hash,
            "source_kind": source_kind,
            "validity_seconds": validity,
            "access_license_sha256": access_hash,
        }
        input_hash = _sha(_canonical(semantic))

        def mutation(connection: sqlite3.Connection, entries: list) -> EvidenceRecord:
            self._validate_mission_locked(connection, mission_id)
            existing = connection.execute(
                "SELECT * FROM evidence_records WHERE evidence_id=?", (evidence_id,)
            ).fetchone()
            if existing is not None:
                record = self._evidence_from_v3(connection, existing)
                if record.workspace_id != self.workspace_id:
                    raise DomainIsolationError("evidence identity belongs to another workspace")
                if record.mission_id != mission_id or record.correlation_id != correlation:
                    raise DomainIntegrityError("evidence replay scope diverges")
                if record.input_sha256 != input_hash:
                    raise DomainConflict("evidence caller key was replayed with different input")
                return record
            if artifact_id is not None:
                self._validate_artifact_locked(
                    connection,
                    artifact_id,
                    workspace_id=self.workspace_id,
                    content_sha256=content_hash,
                    require_available=True,
                )
            created_at = _now()
            valid_until = (
                (datetime.fromisoformat(created_at) + timedelta(seconds=validity)).isoformat()
                if validity is not None else None
            )
            payload_text = _canonical(
                {
                    "access_license_sha256": access_hash,
                    "artifact_id": artifact_id,
                    "contract": "EvidenceRecord.v1",
                    "correlation_id": correlation,
                    "credibility_bp": credibility,
                    "freshness": freshness,
                    "input_sha256": input_hash,
                    "observed_at": created_at,
                    "source_identity_sha256": source_hash,
                    "source_kind": source_kind,
                    "valid_until": valid_until,
                    "validity_seconds": validity,
                }
            )
            record = DomainLedgerRepository._evidence_from_row(
                (
                    evidence_id, self.workspace_id, mission_id,
                    DOMAIN_CONTRACT_VERSION, content_hash, payload_text, created_at,
                )
            )
            connection.execute(
                "INSERT INTO evidence_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    evidence_id, self.workspace_id, mission_id, V3_SCHEMA_VERSION,
                    correlation, source_kind, source_hash, content_hash, artifact_id,
                    credibility, freshness, validity, created_at, valid_until,
                    access_hash, input_hash, _record_digest(record), payload_text, created_at,
                ),
            )
            entries.append(_entry(connection, "evidence_records", evidence_id))
            self._append_event_locked(
                connection,
                entries,
                mission_id=mission_id,
                correlation_id=correlation,
                event_type="evidence.recorded",
                entity_type="evidence",
                entity_id=evidence_id,
                entity_sha256=_record_digest(record),
            )
            return record

        return self._write(mutation)

    def record_claim(
        self,
        caller_key: str,
        correlation_key: str,
        statement: bytes | str,
        evidence_ids: Iterable[str],
        *,
        mission_id: str | None = None,
        claim_kind: str = "unknown",
        confidence_bp: int = 0,
        verification_status: str = "unverified",
        validity_seconds: int | None = None,
        contradiction_claim_ids: Iterable[str] = (),
        supersedes_claim_id: str | None = None,
    ) -> ClaimRecord:
        caller = _safe_key(caller_key, "caller_key")
        correlation_key = _safe_key(correlation_key, "correlation_key")
        statement_hash = _sha(_safe_material(statement, "statement"))
        claim_kind = _enum(claim_kind, frozenset({"fact", "forecast", "inference", "recommendation", "unknown"}), "claim_kind")
        confidence = _basis_points(confidence_bp, "confidence_bp")
        status = _enum(verification_status, _VERIFICATION, "verification_status")
        validity = _validity_seconds(validity_seconds)
        evidence = tuple(sorted(set(evidence_ids)))
        contradictions = tuple(sorted(set(contradiction_claim_ids)))
        if any(not isinstance(item, str) or not item.startswith("m2a-evidence-") or not _ENTITY_ID.fullmatch(item) for item in evidence):
            raise DomainContractError("evidence_ids contain an invalid identity")
        if any(not isinstance(item, str) or not item.startswith("m2a-claim-") or not _ENTITY_ID.fullmatch(item) for item in contradictions):
            raise DomainContractError("contradiction_claim_ids contain an invalid identity")
        if supersedes_claim_id is not None and (
            not isinstance(supersedes_claim_id, str)
            or not supersedes_claim_id.startswith("m2a-claim-")
            or not _ENTITY_ID.fullmatch(supersedes_claim_id)
        ):
            raise DomainContractError("supersedes_claim_id is invalid")
        correlation = _correlation_id(self.workspace_id, correlation_key)
        claim_id = _entity_id("claim", self.workspace_id, caller)
        if claim_id in contradictions or claim_id == supersedes_claim_id:
            raise DomainContractError("claim cannot contradict or supersede itself")
        semantic = {
            "claim_kind": claim_kind,
            "confidence_bp": confidence,
            "contradiction_claim_ids": list(contradictions),
            "correlation_id": correlation,
            "evidence_ids": list(evidence),
            "mission_id": mission_id,
            "statement_sha256": statement_hash,
            "supersedes_claim_id": supersedes_claim_id,
            "validity_seconds": validity,
            "verification_status": status,
        }
        input_hash = _sha(_canonical(semantic))

        def mutation(connection: sqlite3.Connection, entries: list) -> ClaimRecord:
            self._validate_mission_locked(connection, mission_id)
            existing = connection.execute(
                "SELECT * FROM claims WHERE claim_id=?", (claim_id,)
            ).fetchone()
            if existing is not None:
                record = self._claim_from_v3(connection, existing)
                if record.workspace_id != self.workspace_id:
                    raise DomainIsolationError("claim identity belongs to another workspace")
                if record.mission_id != mission_id or record.correlation_id != correlation:
                    raise DomainIntegrityError("claim replay scope diverges")
                if record.input_sha256 != input_hash:
                    raise DomainConflict("claim caller key was replayed with different input")
                return record
            sources: dict[str, EvidenceRecord] = {}
            for evidence_id in evidence:
                row = connection.execute(
                    "SELECT * FROM evidence_records WHERE evidence_id=?", (evidence_id,)
                ).fetchone()
                if row is None:
                    raise DomainIsolationError("claim evidence is unavailable or cross-workspace")
                sources[evidence_id] = self._evidence_from_v3(connection, row)
            if any(item.workspace_id != self.workspace_id or item.mission_id != mission_id for item in sources.values()):
                raise DomainIsolationError("claim/evidence mission scopes diverge")
            referenced: dict[str, ClaimRecord] = {}
            for reference in (*contradictions, supersedes_claim_id):
                if reference is None:
                    continue
                row = connection.execute(
                    "SELECT * FROM claims WHERE claim_id=?", (reference,)
                ).fetchone()
                if row is None:
                    raise DomainIsolationError("claim reference is unavailable or cross-workspace")
                referenced[reference] = self._claim_from_v3(connection, row)
            if any(item.workspace_id != self.workspace_id or item.mission_id != mission_id for item in referenced.values()):
                raise DomainIsolationError("claim reference is unavailable or cross-workspace")
            created_at = _now()
            valid_until = (
                (datetime.fromisoformat(created_at) + timedelta(seconds=validity)).isoformat()
                if validity is not None else None
            )
            payload_text = _canonical(
                {
                    "claim_kind": claim_kind,
                    "confidence_bp": confidence,
                    "contract": "Claim.v1",
                    "contradiction_claim_ids": list(contradictions),
                    "correlation_id": correlation,
                    "evidence_ids": list(evidence),
                    "input_sha256": input_hash,
                    "mission_id": mission_id,
                    "statement_sha256": statement_hash,
                    "supersedes_claim_id": supersedes_claim_id,
                    "valid_until": valid_until,
                    "validity_seconds": validity,
                }
            )
            record = DomainLedgerRepository._claim_from_row(
                (
                    claim_id, self.workspace_id, DOMAIN_CONTRACT_VERSION, status,
                    payload_text, created_at, created_at,
                )
            )
            connection.execute(
                "INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    claim_id, self.workspace_id, mission_id, V3_SCHEMA_VERSION,
                    correlation, claim_kind, statement_hash, confidence, status,
                    validity, valid_until, input_hash, _record_digest(record),
                    payload_text, created_at,
                ),
            )
            entries.append(_entry(connection, "claims", claim_id))
            for ordinal, evidence_id in enumerate(evidence):
                connection.execute(
                    "INSERT INTO claim_evidence_links VALUES(?,?,?,?,?)",
                    (claim_id, evidence_id, self.workspace_id, mission_id, ordinal),
                )
                entries.append(_entry(connection, "claim_evidence_links", claim_id, evidence_id))
            for relation_kind, targets in (
                ("contradicts", contradictions),
                ("supersedes", (supersedes_claim_id,) if supersedes_claim_id else ()),
            ):
                for target in targets:
                    relation_id = _relation_id(self.workspace_id, claim_id, target, relation_kind)
                    connection.execute(
                        "INSERT INTO claim_relations VALUES(?,?,?,?,?,?,?)",
                        (relation_id, self.workspace_id, mission_id, claim_id, target, relation_kind, created_at),
                    )
                    entries.append(_entry(connection, "claim_relations", relation_id))
            self._append_event_locked(
                connection,
                entries,
                mission_id=mission_id,
                correlation_id=correlation,
                event_type="claim.recorded",
                entity_type="claim",
                entity_id=claim_id,
                entity_sha256=_record_digest(record),
            )
            return record

        return self._write(mutation)

    def record_action_request(
        self,
        caller_key: str,
        correlation_key: str,
        connector: str,
        operation: str,
        target: bytes | str,
        payload: bytes | str,
        *,
        mission_id: str | None = None,
        risk: str = "low",
        approval_policy: str = "shadow_only",
        data_class: str = "internal",
        dry_run: bool = True,
        verification_plan: bytes | str = "",
        rollback_plan: bytes | str = "",
    ) -> ActionRequestRecord:
        caller = _safe_key(caller_key, "caller_key")
        correlation_key = _safe_key(correlation_key, "correlation_key")
        connector = _slug(connector, "connector")
        operation = _slug(operation, "operation")
        risk = _enum(risk, _RISKS, "risk")
        approval_policy = _enum(approval_policy, _APPROVAL_POLICIES, "approval_policy")
        data_class = _enum(data_class, _DATA_CLASSES, "data_class")
        if type(dry_run) is not bool or dry_run is not True:
            raise DomainContractError("M2a action requests must remain dry-run shadows")
        target_hash = _sha(_safe_material(target, "target"))
        payload_hash = _sha(_safe_material(payload, "payload", allow_empty=True))
        verification_hash = _sha(_safe_material(verification_plan, "verification_plan", allow_empty=True))
        rollback_hash = _sha(_safe_material(rollback_plan, "rollback_plan", allow_empty=True))
        correlation = _correlation_id(self.workspace_id, correlation_key)
        idem = _idempotency_key(self.workspace_id, caller)
        request_id = "m2a-request-" + idem.removeprefix("m2a:")
        semantic = {
            "approval_policy": approval_policy,
            "connector": connector,
            "correlation_id": correlation,
            "data_class": data_class,
            "dry_run": True,
            "mission_id": mission_id,
            "operation": operation,
            "payload_sha256": payload_hash,
            "risk": risk,
            "rollback_plan_sha256": rollback_hash,
            "target_sha256": target_hash,
            "verification_plan_sha256": verification_hash,
        }
        input_hash = _sha(_canonical(semantic))

        def mutation(connection: sqlite3.Connection, entries: list) -> ActionRequestRecord:
            self._validate_mission_locked(connection, mission_id)
            existing = connection.execute(
                "SELECT * FROM action_requests WHERE idempotency_key=?", (idem,)
            ).fetchone()
            if existing is not None:
                record = self._request_from_v3(connection, existing)
                if record.workspace_id != self.workspace_id:
                    raise DomainIsolationError("idempotency key crossed workspace scope")
                if record.input_sha256 != input_hash:
                    raise DomainConflict("action caller key was replayed with different materialized input")
                return record
            created_at = _now()
            payload_text = _canonical(
                {
                    "approval_policy": approval_policy,
                    "connector": connector,
                    "contract": "ActionRequest.v1",
                    "correlation_id": correlation,
                    "data_class": data_class,
                    "dry_run": True,
                    "input_sha256": input_hash,
                    "operation": operation,
                    "risk": risk,
                    "rollback_plan_sha256": rollback_hash,
                    "target_sha256": target_hash,
                    "verification_plan_sha256": verification_hash,
                }
            )
            record = DomainLedgerRepository._request_from_row(
                (
                    request_id, self.workspace_id, mission_id, DOMAIN_CONTRACT_VERSION,
                    idem, "proposed", payload_hash, payload_text, created_at, created_at,
                )
            )
            connection.execute(
                "INSERT INTO action_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id, self.workspace_id, mission_id, V3_SCHEMA_VERSION,
                    correlation, idem, connector, operation, target_hash, payload_hash,
                    risk, approval_policy, data_class, 1, verification_hash,
                    rollback_hash, input_hash, _record_digest(record), payload_text, created_at,
                ),
            )
            entries.append(_entry(connection, "action_requests", request_id))
            event = self._append_event_locked(
                connection,
                entries,
                mission_id=mission_id,
                correlation_id=correlation,
                event_type="action.request.recorded",
                entity_type="action_request",
                entity_id=request_id,
                entity_sha256=_record_digest(record),
            )
            state_values = (
                request_id, 0, self.workspace_id, mission_id, "proposed",
                event.event_id, None, _record_digest(record), created_at,
            )
            connection.execute(
                "INSERT INTO action_state_history VALUES(?,?,?,?,?,?,?,?,?,?)",
                (*state_values[:8], _typed_record_digest("action_state", state_values), state_values[8]),
            )
            entries.append(_entry(connection, "action_state_history", request_id, 0))
            return record

        return self._write(mutation)

    def _record_receipt(
        self,
        request_id: str,
        caller_key: str,
        outcome: str,
        *,
        reconciliation: bool,
        supersedes_receipt_id: str | None,
        provider_request_id: bytes | str = "",
        before: bytes | str = "",
        after: bytes | str = "",
        output: bytes | str = "",
        verification: bytes | str = "",
        rollback: bytes | str = "",
        error_class: str = "",
    ) -> ActionReceiptRecord:
        if (
            not isinstance(request_id, str)
            or not request_id.startswith("m2a-request-")
            or not _ENTITY_ID.fullmatch(request_id)
        ):
            raise DomainContractError("request_id is invalid")
        caller = _safe_key(caller_key, "caller_key")
        outcome = _enum(outcome, _OUTCOMES, "outcome")
        if type(reconciliation) is not bool:
            raise TypeError("reconciliation must be bool")
        if reconciliation != (supersedes_receipt_id is not None):
            raise DomainContractError("reconciliation requires the superseded receipt")
        if supersedes_receipt_id is not None and (
            not isinstance(supersedes_receipt_id, str)
            or not supersedes_receipt_id.startswith("m2a-receipt-")
            or not _ENTITY_ID.fullmatch(supersedes_receipt_id)
        ):
            raise DomainContractError("supersedes_receipt_id is invalid")
        if not isinstance(error_class, str) or (
            error_class and not _slug(error_class, "error_class")
        ):
            raise DomainContractError("error_class is invalid")
        materials = {
            "after": _safe_material(after, "after", allow_empty=True),
            "before": _safe_material(before, "before", allow_empty=True),
            "output": _safe_material(output, "output", allow_empty=True),
            "provider_request": _safe_material(
                provider_request_id, "provider_request_id", allow_empty=True
            ),
            "rollback": _safe_material(rollback, "receipt rollback", allow_empty=True),
            "verification": _safe_material(
                verification, "receipt verification", allow_empty=True
            ),
        }
        hashes = {
            "after_sha256": _sha(materials["after"]),
            "before_sha256": _sha(materials["before"]),
            "output_sha256": _sha(materials["output"]),
            "provider_request_sha256": _sha(materials["provider_request"]),
            "rollback_sha256": _sha(materials["rollback"]),
            "verification_sha256": _sha(materials["verification"]),
        }
        receipt_id = _entity_id("receipt", self.workspace_id, f"{request_id}:{caller}")
        semantic = {
            **hashes,
            "error_class": error_class,
            "outcome": outcome,
            "reconciliation": reconciliation,
            "request_id": request_id,
            "supersedes_receipt_id": supersedes_receipt_id,
        }
        input_hash = _sha(_canonical(semantic))

        def mutation(connection: sqlite3.Connection, entries: list) -> ActionReceiptRecord:
            existing = connection.execute(
                "SELECT * FROM action_receipts WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
            if existing is not None:
                record = self._receipt_from_v3(connection, existing)
                if record.workspace_id != self.workspace_id:
                    raise DomainIsolationError("receipt caller key crossed workspace scope")
                if record.input_sha256 != input_hash:
                    raise DomainConflict("receipt caller key was replayed with different input")
                return record
            request = self._get_action_request_locked(connection, request_id)
            states = connection.execute(
                "SELECT state_sequence,source_receipt_id FROM action_state_history "
                "WHERE request_id=? ORDER BY state_sequence",
                (request_id,),
            ).fetchall()
            receipt_rows = connection.execute(
                "SELECT * FROM action_receipts WHERE request_id=?", (request_id,)
            ).fetchall()
            receipts = [self._receipt_from_v3(connection, row) for row in receipt_rows]
            by_id = {record.receipt_id: record for record in receipts}
            ordered = [by_id[row[1]] for row in states if row[1] is not None]
            if set(by_id) != {record.receipt_id for record in ordered}:
                raise DomainIntegrityError("receipt state order is incomplete")
            if not reconciliation and ordered:
                raise DomainConflict("initial receipt already exists")
            if reconciliation:
                if not ordered or ordered[-1].receipt_id != supersedes_receipt_id:
                    raise DomainConflict("reconciliation must supersede the latest receipt")
                if ordered[-1].outcome not in {"partial", "unknown"}:
                    raise DomainConflict("terminal receipt cannot be reconciled")
            if outcome == "succeeded" and (
                not _material_present(materials["verification"])
                or (
                    not _material_present(materials["after"])
                    and not _material_present(materials["output"])
                )
            ):
                raise DomainContractError(
                    "shadow succeeded requires verification plus after/output observation"
                )
            if outcome == "failed" and (
                not error_class
                or (
                    not _material_present(materials["verification"])
                    and not _material_present(materials["output"])
                )
            ):
                raise DomainContractError(
                    "shadow failed requires error_class plus verification/output evidence"
                )
            created_at = _now()
            payload_text = _canonical(
                {
                    **hashes,
                    "contract": "ActionReceipt.v1",
                    "correlation_id": request.correlation_id,
                    "error_class": error_class,
                    "input_sha256": input_hash,
                    "observed_at": created_at,
                    "reconciliation": reconciliation,
                    "supersedes_receipt_id": supersedes_receipt_id,
                    "workspace_id": self.workspace_id,
                }
            )
            receipt = DomainLedgerRepository._receipt_from_row(
                (
                    receipt_id, request_id, DOMAIN_CONTRACT_VERSION, outcome,
                    payload_text, created_at, self.workspace_id,
                )
            )
            status = "reconciliation_required" if outcome in {"partial", "unknown"} else "recorded"
            current_request = replace(request, status=status, updated_at=created_at)
            parent_digest = _record_digest(current_request)
            connection.execute(
                "INSERT INTO action_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    receipt_id, request_id, self.workspace_id, request.mission_id,
                    V3_SCHEMA_VERSION, request.correlation_id, outcome,
                    hashes["provider_request_sha256"], hashes["before_sha256"],
                    hashes["after_sha256"], hashes["output_sha256"],
                    hashes["verification_sha256"], hashes["rollback_sha256"],
                    error_class, supersedes_receipt_id, int(reconciliation), input_hash,
                    _record_digest(receipt), parent_digest, created_at, payload_text, created_at,
                ),
            )
            entries.append(_entry(connection, "action_receipts", receipt_id))
            event = self._append_event_locked(
                connection,
                entries,
                mission_id=request.mission_id,
                correlation_id=request.correlation_id,
                event_type="action.receipt.recorded",
                entity_type="action_receipt",
                entity_id=receipt_id,
                entity_sha256=_record_digest(receipt),
                parent_entity_id=request_id,
                parent_entity_sha256=parent_digest,
            )
            state_sequence = int(states[-1][0]) + 1
            state_values = (
                request_id, state_sequence, self.workspace_id, request.mission_id,
                status, event.event_id, receipt_id, parent_digest, created_at,
            )
            connection.execute(
                "INSERT INTO action_state_history VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    *state_values[:8],
                    _typed_record_digest("action_state", state_values),
                    state_values[8],
                ),
            )
            entries.append(
                _entry(connection, "action_state_history", request_id, state_sequence)
            )
            return receipt

        return self._write(mutation)

    def record_initial_receipt(
        self,
        request_id: str,
        caller_key: str,
        outcome: str,
        **details: bytes | str,
    ) -> ActionReceiptRecord:
        return self._record_receipt(
            request_id,
            caller_key,
            outcome,
            reconciliation=False,
            supersedes_receipt_id=None,
            **details,
        )

    def record_reconciliation_receipt(
        self,
        request_id: str,
        caller_key: str,
        outcome: str,
        supersedes_receipt_id: str,
        **details: bytes | str,
    ) -> ActionReceiptRecord:
        return self._record_receipt(
            request_id,
            caller_key,
            outcome,
            reconciliation=True,
            supersedes_receipt_id=supersedes_receipt_id,
            **details,
        )

    def verify_integrity(self) -> None:
        """Run the cold, whole-ledger audit; this path is intentionally O(N)."""

        history_verifier = getattr(self._migrator.anchor, "verify_history", None)
        if callable(history_verifier):
            history_verifier(self._migrator.anchor_owner)

        def audit(connection: sqlite3.Connection) -> None:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DomainIntegrityError("canonical SQLite integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise DomainIntegrityError("canonical foreign-key integrity failed")
            operational = _validate_operational_latest(
                connection, allow_projected_finalization=False
            )
            if operational is None:
                _validate_v3_exact(connection, require_finalization=True)
                return
            commit_count, max_sequence = connection.execute(
                "SELECT count(*),max(commit_sequence) FROM operational_commits"
            ).fetchone()
            if commit_count != max_sequence:
                raise DomainIntegrityError("operational commit chain has a gap")
            previous_commit = connection.execute(
                "SELECT commit_id,state_root FROM integrity_commits"
            ).fetchone()
            if previous_commit is None:
                raise DomainIntegrityError("migration integrity predecessor is missing")
            genesis_root = str(previous_commit[1])
            previous_rows = 0
            previous_events = 0
            migration_anchor = connection.execute(
                "SELECT anchor_sequence FROM anchor_intents"
            ).fetchone()
            if migration_anchor is None:
                raise DomainIntegrityError("migration anchor intent is missing")
            migration_anchor_sequence = int(migration_anchor[0])
            calculated_peaks: list[tuple[int, str]] = []
            expected_mmr_nodes: list[tuple[str, int, str | None, str | None, int]] = []
            expected_mmr_edges: list[tuple[str, str, int]] = []
            expected_mmr_peaks: list[tuple[int, int, int, str]] = []
            for sequence in range(1, int(max_sequence) + 1):
                commit = connection.execute(
                    "SELECT * FROM operational_commits WHERE commit_sequence=?",
                    (sequence,),
                ).fetchone()
                if commit is None or len(commit) != 17:
                    raise DomainIntegrityError("operational commit row is invalid")
                (
                    commit_id, stored_sequence, previous_commit_id, previous_root,
                    database_id, fingerprint, state_root, delta_sha256,
                    genesis_baseline_root, entry_merkle_root, mmr_root,
                    mmr_leaf_hash, mmr_size, entry_count, canonical_row_count,
                    event_count, created_at,
                ) = commit
                entry_rows = connection.execute(
                    "SELECT entry_ordinal,table_name,row_identity,row_sha256,leaf_index,leaf_hash "
                    "FROM operational_commit_entries "
                    "WHERE commit_id=? ORDER BY entry_ordinal",
                    (commit_id,),
                ).fetchall()
                entries = [(str(row[1]), str(row[2]), str(row[3])) for row in entry_rows]
                if (
                    stored_sequence != sequence
                    or mmr_size != sequence
                    or len(entries) != entry_count
                    or [row[0] for row in entry_rows] != list(range(len(entries)))
                    or [row[4] for row in entry_rows] != list(range(len(entries)))
                    or (previous_commit_id, previous_root) != previous_commit
                    or genesis_baseline_root != genesis_root
                ):
                    raise DomainIntegrityError("operational commit chain diverges")
                if previous_rows + len(entries) != canonical_row_count:
                    raise DomainIntegrityError("operational row count diverges")
                event_delta = sum(1 for row in entries if row[0] == "event_envelopes")
                if (sequence > 1 and event_delta != 1) or previous_events + event_delta != event_count:
                    raise DomainIntegrityError("operational event count diverges")
                delta = _operational_delta_digest(entries)
                expected_merkle, leaves, merkle_nodes = _entry_merkle_tree(entries)
                stored_merkle_nodes = connection.execute(
                    "SELECT tree_level,node_index,node_hash FROM operational_entry_merkle_nodes "
                    "WHERE commit_id=? ORDER BY tree_level,node_index", (commit_id,)
                ).fetchall()
                if (
                    delta != delta_sha256
                    or expected_merkle != entry_merkle_root
                    or tuple(row[5] for row in entry_rows) != leaves
                    or tuple(stored_merkle_nodes) != merkle_nodes
                ):
                    raise DomainIntegrityError("operational commit Merkle tree diverges")
                payload_root = _operational_payload_root(
                    sequence=sequence,
                    previous_commit_id=str(previous_commit_id),
                    previous_state_root=str(previous_root),
                    database_id=str(database_id),
                    fingerprint=str(fingerprint),
                    delta_sha256=delta,
                    genesis_baseline_root=str(genesis_baseline_root),
                    entry_merkle_root=str(entry_merkle_root),
                    entry_count=int(entry_count),
                    canonical_row_count=int(canonical_row_count),
                    event_count=int(event_count),
                    created_at=str(created_at),
                )
                expected_id = _operational_commit_id(
                    state_root=payload_root,
                    sequence=sequence,
                    previous_commit_id=str(previous_commit_id),
                    delta_sha256=delta,
                    created_at=str(created_at),
                )
                expected_leaf = _mmr_leaf(expected_id, sequence, payload_root)
                carry_height = 0
                carry_hash = expected_leaf
                expected_mmr_nodes.append((expected_leaf, 0, None, None, sequence))
                while calculated_peaks and calculated_peaks[-1][0] == carry_height:
                    _height, left_hash = calculated_peaks.pop()
                    parent_hash = _mmr_parent(carry_height + 1, left_hash, carry_hash)
                    expected_mmr_nodes.append(
                        (parent_hash, carry_height + 1, left_hash, carry_hash, sequence)
                    )
                    expected_mmr_edges.extend(
                        ((parent_hash, left_hash, 0), (parent_hash, carry_hash, 1))
                    )
                    carry_height += 1
                    carry_hash = parent_hash
                calculated_peaks.append((carry_height, carry_hash))
                expected_mmr_peaks.extend(
                    (sequence, ordinal, height, peak_hash)
                    for ordinal, (height, peak_hash) in enumerate(calculated_peaks)
                )
                if (
                    commit_id != expected_id
                    or mmr_leaf_hash != expected_leaf
                    or mmr_root != _mmr_bag(calculated_peaks)
                ):
                    raise DomainIntegrityError("operational MMR commit diverges")
                root = _operational_state_root(
                    sequence=sequence,
                    previous_commit_id=str(previous_commit_id),
                    previous_state_root=str(previous_root),
                    database_id=str(database_id),
                    fingerprint=str(fingerprint),
                    delta_sha256=delta,
                    genesis_baseline_root=str(genesis_baseline_root),
                    entry_merkle_root=str(entry_merkle_root),
                    mmr_root=str(mmr_root),
                    mmr_size=int(mmr_size),
                    entry_count=int(entry_count),
                    canonical_row_count=int(canonical_row_count),
                    event_count=int(event_count),
                    created_at=str(created_at),
                )
                if state_root != root:
                    raise DomainIntegrityError("operational commit digest diverges")
                anchor_sequence = migration_anchor_sequence + sequence
                expected_intent = (
                    _operational_intent_id(
                        str(commit_id), anchor_sequence, str(state_root), str(created_at)
                    ),
                    str(commit_id),
                    anchor_sequence,
                    str(state_root),
                    "sqlite_committed",
                    str(created_at),
                )
                intent = connection.execute(
                    "SELECT intent_id,commit_id,anchor_sequence,state_root,status,created_at "
                    "FROM operational_anchor_intents WHERE commit_id=?",
                    (commit_id,),
                ).fetchone()
                expected_finalization = (
                    _operational_finalization_id(
                        str(expected_intent[0]),
                        anchor_sequence,
                        str(state_root),
                        str(created_at),
                    ),
                    expected_intent[0],
                    anchor_sequence,
                    str(state_root),
                    str(created_at),
                )
                finalization = connection.execute(
                    "SELECT finalization_id,intent_id,anchor_sequence,state_root,created_at "
                    "FROM operational_anchor_finalizations WHERE intent_id=?",
                    (expected_intent[0],),
                ).fetchone()
                if intent != expected_intent or finalization != expected_finalization:
                    raise DomainIntegrityError(
                        "operational anchor history is not exact"
                    )
                previous_commit = (str(commit_id), str(state_root))
                previous_rows = int(canonical_row_count)
                previous_events = int(event_count)

            intent_count = int(connection.execute(
                "SELECT count(*) FROM operational_anchor_intents"
            ).fetchone()[0])
            finalization_count = int(connection.execute(
                "SELECT count(*) FROM operational_anchor_finalizations"
            ).fetchone()[0])
            if intent_count != max_sequence or finalization_count != max_sequence:
                raise DomainIntegrityError("operational anchor history cardinality diverges")

            physical_nodes = connection.execute(
                "SELECT node_hash,node_height,left_hash,right_hash,commit_sequence "
                "FROM operational_mmr_nodes ORDER BY commit_sequence,node_height,node_hash"
            ).fetchall()
            physical_edges = connection.execute(
                "SELECT parent_hash,child_hash,side FROM operational_mmr_edges "
                "ORDER BY parent_hash,side"
            ).fetchall()
            physical_peaks = connection.execute(
                "SELECT commit_sequence,peak_ordinal,peak_height,peak_hash "
                "FROM operational_mmr_peaks ORDER BY commit_sequence,peak_ordinal"
            ).fetchall()
            if (
                sorted(physical_nodes) != sorted(expected_mmr_nodes)
                or sorted(physical_edges) != sorted(expected_mmr_edges)
                or physical_peaks != expected_mmr_peaks
            ):
                raise DomainIntegrityError("operational MMR physical state diverges")

            physical_entries = sorted(_all_audited_entries(connection))
            witness_rows = connection.execute(
                "SELECT e.table_name,e.row_identity,e.row_sha256,c.commit_sequence "
                "FROM operational_commit_entries e JOIN operational_commits c "
                "ON c.commit_id=e.commit_id"
            ).fetchall()
            witnessed_entries = sorted(
                (str(row[0]), str(row[1]), str(row[2])) for row in witness_rows
            )
            if physical_entries != witnessed_entries:
                raise DomainIntegrityError(
                    "canonical physical rows and commit witnesses are not exact"
                )
            if previous_rows != len(physical_entries):
                raise DomainIntegrityError("canonical row count is not exact")
            witness_sequence = {
                (str(row[0]), str(row[1])): int(row[3]) for row in witness_rows
            }

            def require_genesis(table: str, identities: Iterable[tuple[object, ...]]) -> None:
                if any(
                    witness_sequence.get((table, _row_identity(identity))) != 1
                    for identity in identities
                ):
                    raise DomainIntegrityError(
                        f"migrated or authority row is outside operational genesis: {table}"
                    )

            for table in (
                "workspaces", "mission_contexts", "artifact_index",
                "legacy_v2_evidence_records",
                "legacy_v2_claims", "legacy_v2_action_requests",
                "legacy_v2_action_receipts", "legacy_v2_event_envelopes",
                "legacy_v2_projections",
            ):
                keys = _ROW_ID_COLUMNS[table]
                selected = ",".join(f'"{key}"' for key in keys)
                require_genesis(
                    table,
                    connection.execute(f'SELECT {selected} FROM "{table}"').fetchall(),
                )
            for canonical, legacy, key in (
                ("evidence_records", "legacy_v2_evidence_records", "evidence_id"),
                ("claims", "legacy_v2_claims", "claim_id"),
                ("action_requests", "legacy_v2_action_requests", "request_id"),
                ("action_receipts", "legacy_v2_action_receipts", "receipt_id"),
                ("event_envelopes", "legacy_v2_event_envelopes", "event_id"),
            ):
                require_genesis(
                    canonical,
                    connection.execute(
                        f'SELECT c."{key}" FROM "{canonical}" c JOIN "{legacy}" l '
                        f'ON l."{key}"=c."{key}"'
                    ).fetchall(),
                )
            require_genesis(
                "projections",
                connection.execute(
                    "SELECT p.workspace_id,p.projection_id,p.projection_revision "
                    "FROM projections p JOIN legacy_v2_projections l "
                    "ON l.projection_id=p.projection_id "
                    "AND l.workspace_id=p.workspace_id "
                    "WHERE p.projection_revision=0"
                ).fetchall(),
            )
            require_genesis(
                "claim_evidence_links",
                connection.execute(
                    "SELECT x.claim_id,x.evidence_id FROM claim_evidence_links x "
                    "JOIN legacy_v2_claims c ON c.claim_id=x.claim_id "
                    "JOIN legacy_v2_evidence_records e ON e.evidence_id=x.evidence_id"
                ).fetchall(),
            )
            require_genesis(
                "claim_relations",
                connection.execute(
                    "SELECT r.relation_id FROM claim_relations r "
                    "JOIN legacy_v2_claims s ON s.claim_id=r.source_claim_id "
                    "JOIN legacy_v2_claims t ON t.claim_id=r.target_claim_id"
                ).fetchall(),
            )
            require_genesis(
                "action_state_history",
                connection.execute(
                    "SELECT s.request_id,s.state_sequence FROM action_state_history s "
                    "JOIN legacy_v2_action_requests q ON q.request_id=s.request_id"
                ).fetchall(),
            )
            require_genesis(
                "event_chain_history",
                connection.execute(
                    "SELECT h.workspace_id,h.correlation_id,h.event_sequence "
                    "FROM event_chain_history h JOIN legacy_v2_event_envelopes e "
                    "ON e.event_id=h.event_id"
                ).fetchall(),
            )
            legacy_scopes = connection.execute(
                "SELECT workspace_id,correlation_id,count(*) "
                "FROM legacy_v2_event_envelopes GROUP BY workspace_id,correlation_id"
            ).fetchall()
            for workspace_id, correlation_id, legacy_event_count in legacy_scopes:
                require_genesis(
                    "event_chain_heads",
                    connection.execute(
                        "SELECT workspace_id,correlation_id,head_revision "
                        "FROM event_chain_heads WHERE workspace_id=? AND correlation_id=? "
                        "AND event_count<=?",
                        (workspace_id, correlation_id, legacy_event_count),
                    ).fetchall(),
                )

            for row in connection.execute("SELECT artifact_id FROM artifact_index"):
                self._validate_artifact_locked(
                    connection, str(row[0]), require_available=False
                )
            for row in connection.execute("SELECT * FROM evidence_records"):
                self._evidence_from_v3(connection, row)
            for row in connection.execute("SELECT * FROM claims"):
                self._claim_from_v3(connection, row)
                payload = json.loads(str(row[13]))
                evidence_ids = tuple(sorted(set(payload.get("evidence_ids", []))))
                links = connection.execute(
                    "SELECT evidence_id,link_ordinal,workspace_id,mission_id "
                    "FROM claim_evidence_links WHERE claim_id=? ORDER BY link_ordinal",
                    (row[0],),
                ).fetchall()
                if (
                    tuple(str(link[0]) for link in links) != evidence_ids
                    or [int(link[1]) for link in links] != list(range(len(links)))
                    or any(link[2] != row[1] or link[3] != row[2] for link in links)
                ):
                    raise DomainIntegrityError("claim evidence normalization is not exact")
                expected_relations = {
                    (str(target), "contradicts")
                    for target in payload.get("contradiction_claim_ids", [])
                }
                supersedes = payload.get("supersedes_claim_id")
                if supersedes is not None:
                    expected_relations.add((str(supersedes), "supersedes"))
                relations = connection.execute(
                    "SELECT relation_id,target_claim_id,relation_kind,workspace_id,mission_id "
                    "FROM claim_relations WHERE source_claim_id=?",
                    (row[0],),
                ).fetchall()
                if {
                    (str(relation[1]), str(relation[2])) for relation in relations
                } != expected_relations or any(
                    relation[0]
                    != _relation_id(
                        str(row[1]), str(row[0]), str(relation[1]), str(relation[2])
                    )
                    or relation[3] != row[1]
                    or relation[4] != row[2]
                    for relation in relations
                ):
                    raise DomainIntegrityError("claim relation normalization is not exact")
            for row in connection.execute("SELECT * FROM action_requests"):
                self._request_from_v3(connection, row)
            for row in connection.execute("SELECT * FROM action_receipts"):
                self._receipt_from_v3(connection, row)
            events_by_scope: dict[tuple[str, str], list[tuple[object, ...]]] = {}
            for row in connection.execute(
                "SELECT * FROM event_envelopes ORDER BY workspace_id,correlation_id,event_sequence"
            ):
                self._event_from_v3(connection, row)
                events_by_scope.setdefault((str(row[1]), str(row[3])), []).append(tuple(row))
            for (workspace_id, correlation_id), rows in events_by_scope.items():
                if [row[4] for row in rows] != list(range(len(rows))):
                    raise DomainIntegrityError("event sequence has a gap")
                if any(
                    row[12] != (rows[index - 1][13] if index else _ZERO_HASH)
                    for index, row in enumerate(rows)
                ):
                    raise DomainIntegrityError("event chain hash is disconnected")
                histories = connection.execute(
                    "SELECT event_sequence,event_id,previous_hash,event_hash "
                    "FROM event_chain_history WHERE workspace_id=? AND correlation_id=? "
                    "ORDER BY event_sequence",
                    (workspace_id, correlation_id),
                ).fetchall()
                if histories != [
                    (row[4], row[0], row[12], row[13]) for row in rows
                ]:
                    raise DomainIntegrityError("event chain history is not exact")
                heads = connection.execute(
                    "SELECT head_revision,event_count,head_hash,first_event_id,"
                    "last_event_id,previous_head_hash FROM event_chain_heads "
                    "WHERE workspace_id=? AND correlation_id=? ORDER BY head_revision",
                    (workspace_id, correlation_id),
                ).fetchall()
                legacy_count = int(
                    connection.execute(
                        "SELECT count(*) FROM legacy_v2_event_envelopes "
                        "WHERE workspace_id=? AND correlation_id=?",
                        (workspace_id, correlation_id),
                    ).fetchone()[0]
                )
                endpoint_indices = list(
                    range(legacy_count - 1 if legacy_count else 0, len(rows))
                )
                expected_heads = [
                    (
                        revision,
                        event_index + 1,
                        rows[event_index][13],
                        rows[0][0],
                        rows[event_index][0],
                        rows[endpoint_indices[revision - 1]][13]
                        if revision
                        else None,
                    )
                    for revision, event_index in enumerate(endpoint_indices)
                ]
                if heads != expected_heads:
                    raise DomainIntegrityError("event chain head revisions are not exact")
                projections = connection.execute(
                    "SELECT * FROM projections WHERE workspace_id=? AND correlation_id=? "
                    "ORDER BY projection_revision",
                    (workspace_id, correlation_id),
                ).fetchall()
                if len(projections) != len(endpoint_indices):
                    raise DomainIntegrityError("event projection history is not exact")
                prior_state: str | None = None
                for revision, projection in enumerate(projections):
                    event_index = endpoint_indices[revision]
                    expected_digest = _typed_record_digest(
                        "projection", (*projection[:12], *projection[13:])
                    )
                    if (
                        projection[1] != revision
                        or projection[5] != "m2a_event_chain_head"
                        or projection[7] != revision
                        or projection[8] != event_index + 1
                        or projection[9] != rows[event_index][0]
                        or projection[10] != rows[event_index][13]
                        or projection[11] != prior_state
                        or projection[12] != expected_digest
                    ):
                        raise DomainIntegrityError("event projection revision diverges")
                    prior_state = str(projection[10])

        self._read(audit)


def _open_for_testing(
    migrator: _ControlPlaneV3Migrator,
    owner: V3OwnerCapability,
    registry: WorkspaceRegistry,
    workspace_id: str,
    *,
    enabled: bool,
) -> DomainLedgerV3Repository:
    """Explicit test host factory; no production/startup integration is implied."""

    return DomainLedgerV3Repository(
        migrator,
        owner,
        registry,
        workspace_id,
        enabled=enabled,
        _seal=_REPOSITORY_SEAL,
    )


_PUBLIC_REPOSITORY_METHODS = (
    "initialize",
    "verify_integrity",
    "record_evidence",
    "record_claim",
    "record_action_request",
    "record_initial_receipt",
    "record_reconciliation_receipt",
    "get_evidence",
    "list_evidence",
    "get_claim",
    "list_claims",
    "get_action_request",
    "get_receipt",
    "list_receipts",
    "list_events",
)


def _detached_repository_boundary(operation: Callable[..., _T]) -> Callable[..., _T]:
    """Expose only fresh public exceptions, with no private traceback chain."""

    @wraps(operation)
    def guarded(*args: object, **kwargs: object) -> _T:
        fatal: BaseException | None = None
        public: Exception | None = None
        try:
            return operation(*args, **kwargs)
        except BaseException as error:
            if not isinstance(error, Exception):
                fatal = error
            elif isinstance(error, (DomainLedgerError, ControlPlaneIOError)):
                try:
                    public = type(error)(*error.args)
                except Exception:
                    public = DomainIntegrityError("canonical v3 operation failed")
            elif isinstance(error, (TypeError, ValueError)):
                public = type(error)(*error.args)
            elif isinstance(error, (sqlite3.Error, OSError, ControlPlaneV3Error)):
                public = ControlPlaneIOError("canonical v3 durable-state operation failed")
            else:
                public = DomainIntegrityError("canonical v3 operation failed")
        if fatal is not None:
            fatal.__traceback__ = None
            fatal.__cause__ = None
            fatal.__context__ = None
            raise fatal
        if public is None:  # pragma: no cover - exhaustive guard
            public = DomainIntegrityError("canonical v3 operation failed")
        raise public from None

    return guarded


for _public_method_name in _PUBLIC_REPOSITORY_METHODS:
    setattr(
        DomainLedgerV3Repository,
        _public_method_name,
        _detached_repository_boundary(
            getattr(DomainLedgerV3Repository, _public_method_name)
        ),
    )


__all__ = ["DomainLedgerV3Repository"]
