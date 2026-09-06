from __future__ import annotations

import sqlite3
import inspect
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

import core.control_plane as control_plane
import core.control_plane_v3 as control_plane_v3
import core.domain_ledger as domain_ledger
import core.domain_ledger_v3 as domain_ledger_v3
import pytest
from core.control_plane import ControlPlaneStore
from core.domain_ledger import (
    DomainConflict,
    DomainContractError,
    DomainIntegrityError,
    DomainIsolationError,
    DomainLedgerError,
    DomainLedgerRepository,
)
from core.control_plane_v3 import _open_for_testing as open_migrator_for_testing
from core.domain_ledger_v3 import _open_for_testing as open_repository_for_testing
from core.workspaces import WorkspaceRegistry


class _MemoryVault:
    def __init__(self):
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, secret: bytes | bytearray) -> None:
        self.value = bytes(secret)

    def delete(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


def _fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: tmp_path
    )
    store = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register(
        "cyryx-primary", display_name="Cyryx Primary", workspace_class="cyryx"
    )
    key_vault = _MemoryVault()
    state_vault = _MemoryVault()
    migrator, owner = open_migrator_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=key_vault,
        state_vault=state_vault,
        enabled=True,
    )
    migrator.migrate(owner)
    repository = open_repository_for_testing(
        migrator,
        owner,
        registry,
        "cyryx-primary",
        enabled=True,
    ).initialize()
    return repository, migrator, owner, registry


def _m2a_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: tmp_path
    )
    store = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register(
        "cyryx-primary", display_name="Cyryx Primary", workspace_class="cyryx"
    )
    return store, DomainLedgerRepository(
        registry, "cyryx-primary", enabled=True
    ).initialize()


def _rich_genesis_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: tmp_path
    )
    store = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register(
        "cyryx-primary", display_name="Cyryx Primary", workspace_class="cyryx"
    )
    created = "2026-07-15T00:00:00+00:00"
    store._require_connection().execute(
        "INSERT INTO mission_contexts VALUES(?,?,?,?,?,?,?)",
        (
            "mission-a", "cyryx-primary", 2, "ACTIVE", "{}", created, created,
        ),
    )
    artifact_content = b"rich-artifact-content"
    artifact_sha = hashlib.sha256(artifact_content).hexdigest()
    store._require_connection().execute(
        "INSERT INTO artifact_index VALUES(?,?,?,?,?,?,?,?)",
        (
            "artifact-rich", "cyryx-primary", 2, artifact_sha,
            f"{artifact_sha[:2]}/{artifact_sha}", "application/octet-stream",
            "available", created,
        ),
    )
    legacy = DomainLedgerRepository(
        registry, "cyryx-primary", enabled=True
    ).initialize()
    evidence = legacy.record_evidence(
        "legacy-evidence", "rich-chain", "observation", "source",
        artifact_content, artifact_id="artifact-rich",
    )
    first_claim = legacy.record_claim(
        "legacy-claim-one", "rich-chain", "first", [evidence.evidence_id]
    )
    legacy.record_claim(
        "legacy-claim-two",
        "rich-chain",
        "second",
        [evidence.evidence_id],
        contradiction_claim_ids=[first_claim.claim_id],
    )
    request = legacy.record_action_request(
        "legacy-request", "rich-chain", "shadow.local", "observe", "target", "payload"
    )
    legacy.record_initial_receipt(
        request.request_id,
        "legacy-receipt",
        "simulated",
        output="output",
        verification="verified",
    )
    key_vault = _MemoryVault()
    state_vault = _MemoryVault()
    migrator, owner = open_migrator_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=key_vault,
        state_vault=state_vault,
        enabled=True,
    )
    migrator.migrate(owner)
    repository = open_repository_for_testing(
        migrator, owner, registry, "cyryx-primary", enabled=True
    ).initialize()
    return repository, migrator


def _drop_and_restore_triggers(connection, tables, mutation):
    placeholders = ",".join("?" for _ in tables)
    triggers = connection.execute(
        f"SELECT name,sql FROM sqlite_master WHERE type='trigger' "
        f"AND tbl_name IN ({placeholders}) ORDER BY name",
        tuple(tables),
    ).fetchall()
    for name, _sql in triggers:
        connection.execute(f'DROP TRIGGER "{name}"')
    try:
        mutation()
    finally:
        for _name, sql in triggers:
            connection.execute(sql)


def test_empty_migration_evidence_commit_read_audit_and_reopen(tmp_path, monkeypatch):
    repository, migrator, owner, registry = _fixture(tmp_path, monkeypatch)
    evidence = repository.record_evidence(
        "evidence-one",
        "chain-one",
        "observation",
        "source",
        "content",
        credibility_bp=8000,
        freshness="current",
    )
    assert repository.get_evidence(evidence.evidence_id) == evidence
    assert repository.list_evidence() == (evidence,)
    repository.verify_integrity()

    reopened = open_repository_for_testing(
        migrator,
        owner,
        registry,
        "cyryx-primary",
        enabled=True,
    ).initialize()
    assert reopened.get_evidence(evidence.evidence_id) == evidence
    connection = sqlite3.connect(migrator.port.path)
    try:
        assert connection.execute("SELECT count(*) FROM operational_commits").fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM operational_anchor_finalizations"
        ).fetchone() == (2,)
    finally:
        connection.close()


def test_causal_claim_request_receipt_reconciliation_chain(tmp_path, monkeypatch):
    repository, migrator, owner, registry = _fixture(tmp_path, monkeypatch)
    evidence = repository.record_evidence(
        "evidence", "shared", "observation", "source", "content"
    )
    claim = repository.record_claim(
        "claim",
        "shared",
        "statement",
        [evidence.evidence_id],
        claim_kind="fact",
        confidence_bp=9000,
        verification_status="supported",
    )
    request = repository.record_action_request(
        "request",
        "shared",
        "local",
        "observe",
        "target",
        "payload",
        verification_plan="verify",
        rollback_plan="rollback",
    )
    partial = repository.record_initial_receipt(
        request.request_id,
        "receipt-one",
        "partial",
        provider_request_id="provider-1",
        output="partial-output",
    )
    assert repository.get_action_request(request.request_id).status == "reconciliation_required"
    succeeded = repository.record_reconciliation_receipt(
        request.request_id,
        "receipt-two",
        "succeeded",
        partial.receipt_id,
        provider_request_id="provider-1",
        after="observed-state",
        verification="verified-state",
    )
    assert repository.get_claim(claim.claim_id) == claim
    assert repository.get_receipt(succeeded.receipt_id) == succeeded
    assert repository.list_receipts(request.request_id) == (partial, succeeded)
    assert repository.get_action_request(request.request_id).status == "recorded"
    events = repository.list_events(evidence.correlation_id)
    assert [event.entity_type for event in events] == [
        "evidence",
        "claim",
        "action_request",
        "action_receipt",
        "action_receipt",
    ]
    repository.verify_integrity()

    reopened = open_repository_for_testing(
        migrator,
        owner,
        registry,
        "cyryx-primary",
        enabled=True,
    ).initialize()
    assert reopened.list_events(evidence.correlation_id) == events
    connection = sqlite3.connect(migrator.port.path)
    try:
        assert connection.execute("SELECT count(*) FROM operational_commits").fetchone() == (6,)
        assert connection.execute("SELECT max(commit_sequence) FROM operational_commits").fetchone() == (6,)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "seam",
    (
        "before_anchor_prepare",
        "after_anchor_prepare",
        "after_sqlite_commit",
        "after_anchor_finalize",
        "after_finalization_record",
    ),
)
def test_evidence_write_recovers_every_commit_seam(tmp_path, monkeypatch, seam):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    fired = False

    def fault(point):
        nonlocal fired
        if point == seam and not fired:
            fired = True
            raise RuntimeError(f"crash:{point}")

    repository._fault = fault
    with pytest.raises(DomainIntegrityError, match="canonical v3 operation failed"):
        repository.record_evidence(
            "evidence-crash", "chain-crash", "observation", "source", "content"
        )
    repository._fault = lambda _point: None
    evidence = repository.record_evidence(
        "evidence-crash", "chain-crash", "observation", "source", "content"
    )
    assert repository.get_evidence(evidence.evidence_id) == evidence
    repository.verify_integrity()
    connection = sqlite3.connect(migrator.port.path)
    try:
        assert connection.execute("SELECT count(*) FROM evidence_records").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM event_envelopes").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM operational_commits").fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM operational_anchor_finalizations"
        ).fetchone() == (2,)
    finally:
        connection.close()


def test_exact_replay_returns_record_without_new_commit(tmp_path, monkeypatch):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    first = repository.record_evidence(
        "same", "same-chain", "observation", "source", "content"
    )
    replay = repository.record_evidence(
        "same", "same-chain", "observation", "source", "content"
    )
    assert replay == first
    connection = sqlite3.connect(migrator.port.path)
    try:
        assert connection.execute("SELECT count(*) FROM operational_commits").fetchone() == (2,)
    finally:
        connection.close()


def test_repository_surface_matches_m2a_and_is_absent_from_startup():
    public = (
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
    from core.domain_ledger import DomainLedgerRepository
    from core.domain_ledger_v3 import DomainLedgerV3Repository

    for method in public:
        assert inspect.signature(getattr(DomainLedgerV3Repository, method)) == inspect.signature(
            getattr(DomainLedgerRepository, method)
        )
    root = Path(__file__).parents[1]
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/missions.py",
        "core/mission_tools.py",
        "core/permission_broker.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "domain_ledger_v3" not in source


def test_public_boundary_detaches_private_errors_and_preserves_fatal_identity(
    tmp_path, monkeypatch
):
    repository, _migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)

    class BrokenConnection:
        in_transaction = True

        def execute(self, sql, *_args):
            if sql == "BEGIN":
                return self
            raise sqlite3.OperationalError("private rollback detail")

        def close(self):
            raise OSError("private close detail")

    monkeypatch.setattr(
        domain_ledger_v3,
        "_open_canonical_connection",
        lambda *_args, **_kwargs: BrokenConnection(),
    )
    monkeypatch.setattr(
        repository,
        "_latest_status_locked",
        lambda _connection: (_ for _ in ()).throw(
            DomainIntegrityError("public primary")
        ),
    )
    with pytest.raises(DomainIntegrityError, match="public primary") as denied:
        repository.get_evidence("missing")
    assert denied.value.__cause__ is None
    assert denied.value.__context__ is None
    frames = []
    trace = denied.value.__traceback__
    while trace is not None:
        frames.append(trace.tb_frame.f_code.co_name)
        trace = trace.tb_next
    assert "_read" not in frames
    assert "_latest_status_locked" not in frames

    fatal = KeyboardInterrupt("stop")
    monkeypatch.setattr(
        repository,
        "_latest_status_locked",
        lambda _connection: (_ for _ in ()).throw(fatal),
    )
    with pytest.raises(KeyboardInterrupt) as interrupted:
        repository.get_evidence("missing")
    assert interrupted.value is fatal
    assert fatal.__cause__ is None
    assert fatal.__context__ is None


def test_every_audited_table_requires_exact_physical_and_witness_membership(
    tmp_path, monkeypatch
):
    repository, migrator = _rich_genesis_fixture(tmp_path, monkeypatch)
    path = migrator.port.path
    backup = tmp_path / "rich-baseline.sqlite3"
    with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)

    expected = domain_ledger_v3._EXPECTED_AUDITED_TABLES
    assert frozenset(domain_ledger_v3._AUDITED_TABLES) == expected
    with sqlite3.connect(path) as connection:
        physical = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert expected <= physical
        populated = {
            table
            for table in expected
            if connection.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone()
        }
    assert populated == expected

    def restore() -> None:
        with sqlite3.connect(backup) as source, sqlite3.connect(path) as destination:
            source.backup(destination)

    for table in sorted(expected):
        with sqlite3.connect(path) as connection:
            identity = connection.execute(
                "SELECT row_identity FROM operational_commit_entries "
                "WHERE table_name=? ORDER BY row_identity LIMIT 1", (table,)
            ).fetchone()[0]

            def omit_witness():
                connection.execute(
                    "DELETE FROM operational_commit_entries "
                    "WHERE table_name=? AND row_identity=?", (table, identity)
                )

            _drop_and_restore_triggers(
                connection, ("operational_commit_entries",), omit_witness
            )
            connection.commit()
        with pytest.raises(DomainLedgerError):
            repository.verify_integrity()
        restore()

        keys = domain_ledger_v3._ROW_ID_COLUMNS[table]
        values = json.loads(identity)
        where = " AND ".join(f'"{key}"=?' for key in keys)
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA foreign_keys=OFF")

            def omit_physical():
                connection.execute(
                    f'DELETE FROM "{table}" WHERE {where}', tuple(values)
                )

            _drop_and_restore_triggers(connection, (table,), omit_physical)
            connection.commit()
        with pytest.raises(DomainLedgerError):
            repository.verify_integrity()
        restore()


@pytest.mark.parametrize(
    "omission",
    (
        "claim_evidence_links",
        "claim_relations",
        "action_state_history",
        "event_chain_history",
        "event_chain_heads",
        "projections",
    ),
)
def test_correctly_anchored_producer_omissions_fail_cold_semantics(
    tmp_path, monkeypatch, omission
):
    repository, _migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    evidence = repository.record_evidence(
        "producer-source", "producer-chain", "observation", "source", "content"
    )
    target = None
    if omission in {"claim_evidence_links", "claim_relations"}:
        target = repository.record_claim(
            "producer-target", "producer-chain", "target", [evidence.evidence_id]
        )

    def omit(connection, entries):
        tables = {omission}
        if omission == "event_chain_heads":
            tables.add("projections")
        ordered_tables = sorted(tables, key=lambda table: table == "event_chain_heads")
        trigger_rows = connection.execute(
            "SELECT name,sql,tbl_name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        removed_triggers = [
            (str(name), str(sql))
            for name, sql, table in trigger_rows
            if table in tables
        ]
        for name, _sql in removed_triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        try:
            for table in ordered_tables:
                selected = next(row for row in entries if row[0] == table)
                values = json.loads(selected[1])
                keys = domain_ledger_v3._ROW_ID_COLUMNS[table]
                where = " AND ".join(f'"{key}"=?' for key in keys)
                connection.execute(
                    f'DELETE FROM "{table}" WHERE {where}', tuple(values)
                )
            entries[:] = [row for row in entries if row[0] not in tables]
        finally:
            for _name, sql in removed_triggers:
                connection.execute(sql)

    repository._before_commit_test_hook = omit
    if omission in {"claim_evidence_links", "claim_relations"}:
        repository.record_claim(
            "producer-claim",
            "producer-chain",
            "claim",
            [evidence.evidence_id],
            contradiction_claim_ids=(
                [target.claim_id] if omission == "claim_relations" else []
            ),
        )
    elif omission == "action_state_history":
        repository.record_action_request(
            "producer-request",
            "producer-chain",
            "shadow.local",
            "observe",
            "target",
            "payload",
        )
    else:
        repository.record_evidence(
            "producer-event", "producer-chain", "observation", "source-2", "content-2"
        )
    repository._before_commit_test_hook = lambda _connection, _entries: None
    with pytest.raises(DomainIntegrityError):
        repository.verify_integrity()


def test_historical_row_rewrite_is_rejected_by_hot_merkle_mmr_proof(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    first = repository.record_evidence(
        "historical-first", "historical-first", "observation", "source", "one"
    )
    repository.record_evidence(
        "historical-second", "historical-second", "observation", "source", "two"
    )
    with sqlite3.connect(migrator.port.path) as connection:
        _drop_and_restore_triggers(
            connection,
            ("evidence_records",),
            lambda: connection.execute(
                "UPDATE evidence_records SET created_at=? WHERE evidence_id=?",
                ("2026-07-15T00:00:00+00:00", first.evidence_id),
            ),
        )
        connection.commit()
    with pytest.raises(DomainIntegrityError):
        repository.get_evidence(first.evidence_id)


def test_coherent_nonlatest_row_merkle_rewrite_is_rejected_before_mmr_proof(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    first = repository.record_evidence(
        "coherent-first", "coherent-first", "observation", "source", "one"
    )
    repository.record_evidence(
        "coherent-second", "coherent-second", "observation", "source", "two"
    )
    with sqlite3.connect(migrator.port.path) as connection:
        commit_id = connection.execute(
            "SELECT commit_id FROM operational_commit_entries "
            "WHERE table_name='evidence_records' AND row_identity=?",
            (domain_ledger_v3._row_identity((first.evidence_id,)),),
        ).fetchone()[0]

        def rewrite_row_witness_and_merkle_root():
            row = list(connection.execute(
                "SELECT * FROM evidence_records WHERE evidence_id=?",
                (first.evidence_id,),
            ).fetchone())
            forged_content = hashlib.sha256(b"coherently-forged-content").hexdigest()
            forged_input = hashlib.sha256(b"coherently-forged-input").hexdigest()
            payload = json.loads(str(row[17]))
            payload["input_sha256"] = forged_input
            payload_text = domain_ledger._canonical(payload)
            forged_record = domain_ledger.DomainLedgerRepository._evidence_from_row(
                (row[0], row[1], row[2], 1, forged_content, payload_text, row[18])
            )
            row[7] = forged_content
            row[15] = forged_input
            row[16] = domain_ledger._record_digest(forged_record)
            row[17] = payload_text
            connection.execute(
                "UPDATE evidence_records SET content_sha256=?,input_sha256=?,"
                "record_sha256=?,legacy_payload_json=? WHERE evidence_id=?",
                (forged_content, forged_input, row[16], payload_text, first.evidence_id),
            )
            identity = domain_ledger_v3._row_identity((first.evidence_id,))
            rewritten_sha = domain_ledger_v3._row_sha256(
                connection, "evidence_records", identity
            )
            entries = [
                [str(item[0]), str(item[1]), str(item[2])]
                for item in connection.execute(
                    "SELECT table_name,row_identity,row_sha256 "
                    "FROM operational_commit_entries WHERE commit_id=? "
                    "ORDER BY entry_ordinal", (commit_id,)
                ).fetchall()
            ]
            target = next(
                item for item in entries
                if item[0] == "evidence_records" and item[1] == identity
            )
            target[2] = rewritten_sha
            merkle_root, leaves, nodes = control_plane_v3._entry_merkle_tree(
                [tuple(item) for item in entries]
            )
            connection.execute(
                "UPDATE operational_commit_entries SET row_sha256=?,leaf_hash=? "
                "WHERE commit_id=? AND table_name='evidence_records' AND row_identity=?",
                (rewritten_sha, leaves[entries.index(target)], commit_id, identity),
            )
            connection.execute(
                "DELETE FROM operational_entry_merkle_nodes WHERE commit_id=?",
                (commit_id,),
            )
            connection.executemany(
                "INSERT INTO operational_entry_merkle_nodes VALUES(?,?,?,?)",
                [(commit_id, level, index, digest) for level, index, digest in nodes],
            )
            connection.execute(
                "UPDATE operational_commits SET entry_merkle_root=? WHERE commit_id=?",
                (merkle_root, commit_id),
            )

        _drop_and_restore_triggers(
            connection,
            (
                "evidence_records", "operational_commit_entries",
                "operational_entry_merkle_nodes", "operational_commits",
            ),
            rewrite_row_witness_and_merkle_root,
        )
        connection.commit()
    with pytest.raises(DomainIntegrityError):
        repository.get_evidence(first.evidence_id)


@pytest.mark.parametrize("mutation", ("workspace", "hash_path", "path", "status"))
def test_artifact_index_is_genesis_witnessed_and_hot_semantically_bound(
    tmp_path, monkeypatch, mutation
):
    repository, migrator = _rich_genesis_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(migrator.port.path) as connection:
        evidence_id = str(connection.execute(
            "SELECT evidence_id FROM evidence_records WHERE artifact_id='artifact-rich'"
        ).fetchone()[0])

        def mutate_artifact():
            if mutation == "workspace":
                connection.execute(
                    "UPDATE artifact_index SET workspace_id='forged-workspace' "
                    "WHERE artifact_id='artifact-rich'"
                )
            elif mutation == "hash_path":
                forged = hashlib.sha256(b"forged-artifact").hexdigest()
                connection.execute(
                    "UPDATE artifact_index SET sha256=?,relative_path=? "
                    "WHERE artifact_id='artifact-rich'",
                    (forged, f"{forged[:2]}/{forged}"),
                )
            elif mutation == "path":
                connection.execute(
                    "UPDATE artifact_index SET relative_path='../forged' "
                    "WHERE artifact_id='artifact-rich'"
                )
            else:
                connection.execute(
                    "UPDATE artifact_index SET status='unavailable' "
                    "WHERE artifact_id='artifact-rich'"
                )

        connection.execute("PRAGMA foreign_keys=OFF")
        _drop_and_restore_triggers(connection, ("artifact_index",), mutate_artifact)
        connection.commit()
    with pytest.raises(DomainIntegrityError):
        repository.get_evidence(evidence_id)


def test_artifact_index_is_frozen_after_operational_genesis(tmp_path, monkeypatch):
    _repository, migrator = _rich_genesis_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(migrator.port.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="frozen by operational genesis"):
            connection.execute(
                "UPDATE artifact_index SET status='unavailable' "
                "WHERE artifact_id='artifact-rich'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="frozen by operational genesis"):
            connection.execute("DELETE FROM artifact_index WHERE artifact_id='artifact-rich'")


@pytest.mark.parametrize("mutation", ("extra", "missing"))
def test_artifact_index_physical_extras_and_omissions_fail_cold_exactness(
    tmp_path, monkeypatch, mutation
):
    repository, migrator = _rich_genesis_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(migrator.port.path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")

        def mutate_artifact_membership():
            if mutation == "missing":
                connection.execute(
                    "DELETE FROM artifact_index WHERE artifact_id='artifact-rich'"
                )
                return
            digest = hashlib.sha256(b"unwitnessed-extra-artifact").hexdigest()
            connection.execute(
                "INSERT INTO artifact_index VALUES(?,?,?,?,?,?,?,?)",
                (
                    "artifact-extra", "cyryx-primary", 2, digest,
                    f"{digest[:2]}/{digest}", "application/octet-stream",
                    "available", "2026-07-15T00:00:00+00:00",
                ),
            )

        _drop_and_restore_triggers(
            connection, ("artifact_index",), mutate_artifact_membership
        )
        connection.commit()
    with pytest.raises(DomainIntegrityError):
        repository.verify_integrity()


def test_coordinated_artifact_and_evidence_rewrite_fails_semantic_reconciliation(
    tmp_path, monkeypatch
):
    repository, migrator = _rich_genesis_fixture(tmp_path, monkeypatch)
    forged = hashlib.sha256(b"coordinated-forged-artifact").hexdigest()
    with sqlite3.connect(migrator.port.path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")

        def coordinate_rows():
            connection.execute(
                "UPDATE artifact_index SET sha256=?,relative_path=? "
                "WHERE artifact_id='artifact-rich'",
                (forged, f"{forged[:2]}/{forged}"),
            )
            connection.execute(
                "UPDATE evidence_records SET content_sha256=? "
                "WHERE artifact_id='artifact-rich'", (forged,)
            )

        _drop_and_restore_triggers(
            connection, ("artifact_index", "evidence_records"), coordinate_rows
        )
        row = connection.execute(
            "SELECT * FROM evidence_records WHERE artifact_id='artifact-rich'"
        ).fetchone()
        with pytest.raises(DomainIntegrityError):
            repository._evidence_from_v3(connection, row)


def test_artifact_producer_omission_cannot_shrink_independent_audit_registry(
    tmp_path, monkeypatch
):
    _repository, migrator = _rich_genesis_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        domain_ledger_v3,
        "_AUDITED_TABLES",
        tuple(
            table
            for table in domain_ledger_v3._AUDITED_TABLES
            if table != "artifact_index"
        ),
    )
    with sqlite3.connect(migrator.port.path) as connection:
        with pytest.raises(DomainIntegrityError, match="registry diverges"):
            domain_ledger_v3._all_audited_entries(connection)


def test_middle_commit_removal_is_rejected_before_exposure(tmp_path, monkeypatch):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    repository.record_evidence(
        "middle-first", "middle-first", "observation", "source", "one"
    )
    repository.record_evidence(
        "middle-second", "middle-second", "observation", "source", "two"
    )
    with sqlite3.connect(migrator.port.path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        _drop_and_restore_triggers(
            connection,
            ("operational_commits",),
            lambda: connection.execute(
                "DELETE FROM operational_commits WHERE commit_sequence=2"
            ),
        )
        connection.commit()
    with pytest.raises(DomainIntegrityError):
        repository.list_evidence()


def test_latest_anchor_recovery_probe_is_indexed_and_history_bounded():
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE operational_anchor_intents("
            "intent_id TEXT PRIMARY KEY, anchor_sequence INTEGER UNIQUE, state_root TEXT)"
        )
        connection.execute(
            "CREATE TABLE operational_anchor_finalizations("
            "intent_id TEXT PRIMARY KEY, anchor_sequence INTEGER UNIQUE, state_root TEXT)"
        )
        rows = [
            (f"intent-{sequence:05d}", sequence, f"root-{sequence:05d}")
            for sequence in range(1, 10_001)
        ]
        connection.executemany(
            "INSERT INTO operational_anchor_intents VALUES(?,?,?)", rows
        )
        connection.executemany(
            "INSERT INTO operational_anchor_finalizations VALUES(?,?,?)", rows
        )
        plans = []
        for table in (
            "operational_anchor_intents", "operational_anchor_finalizations"
        ):
            plan = connection.execute(
                f"EXPLAIN QUERY PLAN SELECT intent_id,anchor_sequence,state_root "
                f"FROM {table} ORDER BY anchor_sequence DESC LIMIT 1"
            ).fetchall()
            plans.extend(str(row[3]).upper() for row in plan)
        assert all("INDEX" in detail for detail in plans)
        traced: list[str] = []
        connection.set_trace_callback(traced.append)
        assert not domain_ledger_v3._latest_anchor_head_needs_recovery(connection)
        probes = [
            statement for statement in traced
            if statement.lstrip().upper().startswith("SELECT")
        ]
        assert len(probes) == 2
        assert all("LIMIT 1" in statement.upper() for statement in probes)

        connection.set_trace_callback(None)
        connection.execute(
            "DELETE FROM operational_anchor_finalizations WHERE anchor_sequence=10000"
        )
        assert domain_ledger_v3._latest_anchor_head_needs_recovery(connection)
    finally:
        connection.close()


def test_coordinated_authority_and_witness_rewrite_is_rejected(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    identity = domain_ledger_v3._row_identity(("cyryx-primary",))
    with sqlite3.connect(migrator.port.path) as connection:
        def rewrite_authority_and_flat_witness():
            connection.execute(
                "UPDATE workspaces SET payload_json=? WHERE workspace_id=?",
                ('{"display_name":"forged"}', "cyryx-primary"),
            )
            rewritten = domain_ledger_v3._row_sha256(
                connection, "workspaces", identity
            )
            connection.execute(
                "UPDATE operational_commit_entries SET row_sha256=? "
                "WHERE table_name='workspaces' AND row_identity=?",
                (rewritten, identity),
            )

        _drop_and_restore_triggers(
            connection,
            ("workspaces", "operational_commit_entries"),
            rewrite_authority_and_flat_witness,
        )
        connection.commit()
    with pytest.raises(DomainIntegrityError):
        repository.list_evidence()


def test_m2a_and_v3_differential_contract_parity(tmp_path, monkeypatch):
    tied = "2026-07-15T12:00:00+00:00"
    monkeypatch.setattr(domain_ledger, "_now", lambda: tied)
    monkeypatch.setattr(domain_ledger_v3, "_now", lambda: tied)
    m2a_store, m2a = _m2a_fixture(tmp_path / "m2a", monkeypatch)
    v3, migrator, _owner, _registry = _fixture(tmp_path / "v3", monkeypatch)

    def lifecycle(repository):
        evidence = repository.record_evidence(
            "evidence-parity", "parity-chain", "observation", "source", "content",
            credibility_bp=8_000, freshness="current", validity_seconds=3_600,
        )
        claim = repository.record_claim(
            "claim-parity", "parity-chain", "statement", [evidence.evidence_id],
            claim_kind="fact", confidence_bp=8_000,
            verification_status="supported", validity_seconds=3_600,
        )
        request = repository.record_action_request(
            "request-parity", "parity-chain", "shadow.local", "render.preview",
            "target", "payload", verification_plan="verify", rollback_plan="discard",
        )
        first = repository.record_initial_receipt(
            request.request_id, "receipt-parity-one", "unknown",
            provider_request_id="provider", output="pending",
            verification="not observed", error_class="observation_timeout",
        )
        current = repository.get_action_request(request.request_id)
        second = repository.record_reconciliation_receipt(
            request.request_id, "receipt-parity-two", "simulated", first.receipt_id,
            provider_request_id="provider", output="observed", verification="verified",
        )
        final = repository.get_action_request(request.request_id)
        replay = repository.record_evidence(
            "evidence-parity", "parity-chain", "observation", "source", "content",
            credibility_bp=8_000, freshness="current", validity_seconds=3_600,
        )
        with pytest.raises(DomainConflict) as conflict:
            repository.record_evidence(
                "evidence-parity", "parity-chain", "observation", "source", "changed",
                credibility_bp=8_000, freshness="current", validity_seconds=3_600,
            )
        return {
            "evidence": evidence, "claim": claim, "request": request,
            "first": first, "current": current, "second": second, "final": final,
            "replay": replay, "evidence_list": repository.list_evidence(),
            "claim_list": repository.list_claims(),
            "receipts": repository.list_receipts(request.request_id),
            "events": repository.list_events(evidence.correlation_id),
            "conflict": (type(conflict.value), str(conflict.value)),
        }

    try:
        assert lifecycle(v3) == lifecycle(m2a)
        for repository in (m2a, v3):
            for method, missing, message in (
                (repository.get_evidence, "m2a-evidence-" + "0" * 64,
                 "evidence is unavailable in this workspace"),
                (repository.get_claim, "m2a-claim-" + "0" * 64,
                 "claim is unavailable in this workspace"),
                (repository.get_action_request, "m2a-action-request-" + "0" * 64,
                 "action request is unavailable in this workspace"),
                (repository.get_receipt, "m2a-receipt-" + "0" * 64,
                 "action receipt is unavailable in this workspace"),
            ):
                with pytest.raises(DomainIsolationError, match=message):
                    method(missing)
            with pytest.raises(DomainContractError, match="correlation_id is invalid"):
                repository.list_events("invalid correlation")
        assert m2a_store._require_connection().execute(
            "SELECT count(*) FROM event_envelopes"
        ).fetchone() == (5,)
        with sqlite3.connect(migrator.port.path) as connection:
            assert connection.execute(
                "SELECT count(*) FROM event_envelopes"
            ).fetchone() == (5,)
            assert connection.execute(
                "SELECT count(*) FROM operational_commits"
            ).fetchone() == (6,)
        m2a.verify_integrity()
        v3.verify_integrity()
    finally:
        m2a_store.close()


def test_concurrent_writers_converge_and_serialize_commit_sequences(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)

    def run(callables):
        barrier = threading.Barrier(len(callables))
        results = []
        failures = []

        def worker(operation):
            try:
                barrier.wait(timeout=10)
                results.append(operation())
            except BaseException as exc:
                failures.append(exc)

        threads = [threading.Thread(target=worker, args=(operation,)) for operation in callables]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert all(not thread.is_alive() for thread in threads)
        assert failures == [], [
            (repr(exc), repr(exc.__cause__)) for exc in failures
        ]
        return results

    identical = run(
        [
            lambda: repository.record_evidence(
                "same-concurrent", "same-chain", "observation", "source", "content"
            )
            for _ in range(4)
        ]
    )
    assert len({record.evidence_id for record in identical}) == 1

    distinct = run(
        [
            lambda index=index: repository.record_evidence(
                f"distinct-{index}", f"chain-{index}", "observation",
                f"source-{index}", f"content-{index}",
            )
            for index in range(4)
        ]
    )
    assert len({record.evidence_id for record in distinct}) == 4
    with sqlite3.connect(migrator.port.path) as connection:
        assert connection.execute(
            "SELECT commit_sequence FROM operational_commits ORDER BY commit_sequence"
        ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,)]
        assert connection.execute(
            "SELECT count(*) FROM evidence_records"
        ).fetchone() == (5,)
        assert connection.execute(
            "SELECT count(*) FROM event_envelopes"
        ).fetchone() == (5,)
    repository.verify_integrity()


def test_incremental_hot_path_does_not_call_cold_validator_or_streaming_root(
    tmp_path, monkeypatch
):
    repository, _migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    repository.record_evidence(
        "hot-baseline", "hot-baseline", "observation", "source", "content"
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("cold O(N) validator reached from incremental hot path")

    monkeypatch.setattr(control_plane_v3, "_validate_v3_exact", forbidden)
    monkeypatch.setattr(domain_ledger_v3, "_validate_v3_exact", forbidden)
    monkeypatch.setattr(control_plane_v3, "_stream_state_root", forbidden)
    started = time.perf_counter()
    second = repository.record_evidence(
        "hot-second", "hot-second", "observation", "source", "content"
    )
    elapsed = time.perf_counter() - started
    assert repository.get_evidence(second.evidence_id) == second
    assert elapsed < domain_ledger_v3._WRITER_TIMEOUT_SECONDS


def test_hot_write_uses_only_indexed_latest_anchor_heads_with_long_history(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    for index in range(8):
        repository.record_evidence(
            f"head-history-{index}",
            f"head-history-{index}",
            "observation",
            "source",
            f"content-{index}",
        )

    traced = []
    original_open = domain_ledger_v3._open_canonical_connection

    def traced_open(*args, **kwargs):
        connection = original_open(*args, **kwargs)
        connection.set_trace_callback(traced.append)
        return connection

    monkeypatch.setattr(domain_ledger_v3, "_open_canonical_connection", traced_open)
    repository.record_evidence(
        "head-history-final", "head-history-final", "observation", "source", "final"
    )
    normalized = [" ".join(statement.split()).lower() for statement in traced]
    assert any(
        "from operational_anchor_intents order by anchor_sequence desc limit 1"
        in statement
        for statement in normalized
    )
    assert any(
        "from operational_anchor_finalizations order by anchor_sequence desc limit 1"
        in statement
        for statement in normalized
    )
    assert not any(
        "operational_anchor_intents" in statement and "left join" in statement
        for statement in normalized
    )

    with sqlite3.connect(migrator.port.path) as connection:
        for table in (
            "operational_anchor_intents",
            "operational_anchor_finalizations",
        ):
            plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT intent_id,anchor_sequence,state_root "
                f"FROM {table} ORDER BY anchor_sequence DESC LIMIT 1"
            ).fetchall()
            assert any("index" in str(row[3]).lower() for row in plan), plan


def test_healthy_write_uses_one_writer_session_and_one_baseline_verification(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    counts = {"writer_session": 0, "verify_baseline": 0}
    original_writer_session = migrator.anchor.writer_session

    class CountingSession:
        def __init__(self, context):
            self.context = context
            self.session = None

        def __enter__(self):
            self.session = self.context.__enter__()
            return self

        def __exit__(self, *args):
            return self.context.__exit__(*args)

        def verify_baseline(self):
            counts["verify_baseline"] += 1
            return self.session.verify_baseline()

        def __getattr__(self, name):
            return getattr(self.session, name)

    def counted_writer_session(*args, **kwargs):
        counts["writer_session"] += 1
        return CountingSession(original_writer_session(*args, **kwargs))

    monkeypatch.setattr(migrator.anchor, "writer_session", counted_writer_session)
    repository.record_evidence(
        "single-writer-session", "healthy-write", "observation", "source", "content"
    )
    assert counts == {"writer_session": 1, "verify_baseline": 1}


def test_missing_latest_finalization_fails_reads_and_is_recovered_by_next_write(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    first = repository.record_evidence(
        "recover-latest-first", "recover-latest", "observation", "source", "one"
    )
    with sqlite3.connect(migrator.port.path) as connection:
        latest_intent = connection.execute(
            "SELECT intent_id FROM operational_anchor_intents "
            "ORDER BY anchor_sequence DESC LIMIT 1"
        ).fetchone()[0]

        def remove_latest_finalization():
            connection.execute(
                "DELETE FROM operational_anchor_finalizations WHERE intent_id=?",
                (latest_intent,),
            )

        _drop_and_restore_triggers(
            connection,
            ("operational_anchor_finalizations",),
            remove_latest_finalization,
        )
        connection.commit()

    with pytest.raises(DomainIntegrityError):
        repository.get_evidence(first.evidence_id)
    second = repository.record_evidence(
        "recover-latest-second", "recover-latest", "observation", "source", "two"
    )
    assert repository.get_evidence(second.evidence_id) == second
    with sqlite3.connect(migrator.port.path) as connection:
        intent_count = connection.execute(
            "SELECT count(*) FROM operational_anchor_intents"
        ).fetchone()[0]
        finalization_count = connection.execute(
            "SELECT count(*) FROM operational_anchor_finalizations"
        ).fetchone()[0]
    assert intent_count == finalization_count
    repository.verify_integrity()


def test_cold_audit_rejects_missing_middle_finalization(tmp_path, monkeypatch):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    records = [
        repository.record_evidence(
            f"middle-finalization-{index}",
            "middle-finalization",
            "observation",
            "source",
            f"content-{index}",
        )
        for index in range(3)
    ]
    with sqlite3.connect(migrator.port.path) as connection:
        middle_intent = connection.execute(
            "SELECT intent_id FROM operational_anchor_intents "
            "WHERE anchor_sequence=2"
        ).fetchone()[0]

        def remove_middle_finalization():
            connection.execute(
                "DELETE FROM operational_anchor_finalizations WHERE intent_id=?",
                (middle_intent,),
            )

        _drop_and_restore_triggers(
            connection,
            ("operational_anchor_finalizations",),
            remove_middle_finalization,
        )
        connection.commit()

    assert repository.list_evidence() == tuple(records)
    with pytest.raises(DomainIntegrityError):
        repository.verify_integrity()


def test_busy_writer_returns_bounded_conflict_without_partial_state(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(domain_ledger_v3, "_WRITER_TIMEOUT_SECONDS", 0.1)
    acquired = threading.Event()
    release = threading.Event()
    holder_failure = []

    def hold_anchor():
        try:
            with migrator.anchor.writer_session(
                migrator.anchor_owner, timeout=1.0
            ) as session:
                session.verify_baseline()
                acquired.set()
                release.wait(5)
        except BaseException as exc:
            holder_failure.append(exc)

    holder = threading.Thread(target=hold_anchor)
    holder.start()
    assert acquired.wait(5)
    started = time.perf_counter()
    with pytest.raises(DomainIntegrityError) as denied:
        repository.record_evidence(
            "busy-denied", "busy-denied", "observation", "source", "content"
        )
    elapsed = time.perf_counter() - started
    release.set()
    holder.join(5)
    assert not holder.is_alive()
    assert holder_failure == []
    assert denied.value.__cause__ is None
    assert denied.value.__context__ is None
    assert elapsed < 1.0
    with sqlite3.connect(migrator.port.path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM evidence_records"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM event_envelopes"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM operational_commits"
        ).fetchone() == (1,)


def test_external_anchor_rejects_database_rollback_and_commit_suffix_truncation(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    first = repository.record_evidence(
        "rollback-first", "rollback-first", "observation", "source", "content"
    )
    backup = tmp_path / "commit-one.sqlite3"
    shutil.copy2(migrator.port.path, backup)
    repository.record_evidence(
        "rollback-second", "rollback-second", "observation", "source", "content"
    )
    shutil.copy2(backup, migrator.port.path)
    with pytest.raises(DomainIntegrityError):
        repository.get_evidence(first.evidence_id)

    # Restore the valid two-commit database, then surgically remove only its
    # latest commit suffix while leaving the externally anchored state intact.
    # Rebuild it deterministically because the old backup is the rollback case.
    repository, migrator, _owner, _registry = _fixture(
        tmp_path / "suffix", monkeypatch
    )
    first = repository.record_evidence(
        "suffix-first", "suffix-first", "observation", "source", "content"
    )
    repository.record_evidence(
        "suffix-second", "suffix-second", "observation", "source", "content"
    )
    with sqlite3.connect(migrator.port.path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")

        def truncate():
            latest = connection.execute(
                "SELECT commit_id FROM operational_commits WHERE commit_sequence=3"
            ).fetchone()[0]
            intent = connection.execute(
                "SELECT intent_id FROM operational_anchor_intents WHERE commit_id=?",
                (latest,),
            ).fetchone()[0]
            connection.execute(
                "DELETE FROM operational_anchor_finalizations WHERE intent_id=?", (intent,)
            )
            connection.execute(
                "DELETE FROM operational_anchor_intents WHERE intent_id=?", (intent,)
            )
            connection.execute(
                "DELETE FROM operational_commit_entries WHERE commit_id=?", (latest,)
            )
            connection.execute(
                "DELETE FROM operational_commits WHERE commit_id=?", (latest,)
            )

        _drop_and_restore_triggers(
            connection,
            (
                "operational_commits", "operational_commit_entries",
                "operational_anchor_intents", "operational_anchor_finalizations",
            ),
            truncate,
        )
        connection.commit()
    with pytest.raises(DomainIntegrityError):
        repository.get_evidence(first.evidence_id)


def test_row_and_witness_tamper_and_self_consistent_root_rewrite_are_rejected(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(tmp_path, monkeypatch)
    evidence = repository.record_evidence(
        "tamper-row", "tamper-row", "observation", "source", "content"
    )
    with sqlite3.connect(migrator.port.path) as connection:
        def rewrite_row_and_witness():
            connection.execute(
                "UPDATE evidence_records SET created_at=? WHERE evidence_id=?",
                ("2026-07-15T00:00:00+00:00", evidence.evidence_id),
            )
            identity = domain_ledger_v3._row_identity((evidence.evidence_id,))
            rewritten = domain_ledger_v3._row_sha256(
                connection, "evidence_records", identity
            )
            connection.execute(
                "UPDATE operational_commit_entries SET row_sha256=? "
                "WHERE table_name='evidence_records' AND row_identity=?",
                (rewritten, identity),
            )

        _drop_and_restore_triggers(
            connection,
            ("evidence_records", "operational_commit_entries"),
            rewrite_row_and_witness,
        )
        connection.commit()
    with pytest.raises(DomainIntegrityError):
        repository.get_evidence(evidence.evidence_id)
    with pytest.raises(DomainIntegrityError):
        repository.verify_integrity()


def test_nonempty_migrated_prefix_accepts_new_multi_commit_suffix_and_reopens(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: tmp_path
    )
    store = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register(
        "cyryx-primary", display_name="Cyryx Primary", workspace_class="cyryx"
    )
    legacy = DomainLedgerRepository(
        registry, "cyryx-primary", enabled=True
    ).initialize()
    legacy_evidence = legacy.record_evidence(
        "legacy-evidence", "shared-prefix", "observation", "legacy-source",
        "legacy-content",
    )
    legacy_claim = legacy.record_claim(
        "legacy-claim", "shared-prefix", "legacy-statement",
        [legacy_evidence.evidence_id], claim_kind="fact",
    )
    legacy_request = legacy.record_action_request(
        "legacy-request", "shared-prefix", "shadow.local", "observe.preview",
        "legacy-target", "legacy-payload",
    )
    legacy_receipt = legacy.record_initial_receipt(
        legacy_request.request_id, "legacy-receipt", "simulated",
        output="legacy-output", verification="legacy-verification",
    )
    key_vault = _MemoryVault()
    state_vault = _MemoryVault()
    migrator, owner = open_migrator_for_testing(
        store, journal_path=tmp_path / "anchor.journal", key_vault=key_vault,
        state_vault=state_vault, enabled=True,
    )
    migrator.migrate(owner)
    repository = open_repository_for_testing(
        migrator, owner, registry, "cyryx-primary", enabled=True
    ).initialize()
    assert repository.get_evidence(legacy_evidence.evidence_id) == legacy_evidence
    assert repository.get_claim(legacy_claim.claim_id) == legacy_claim
    assert repository.get_receipt(legacy_receipt.receipt_id) == legacy_receipt
    assert repository.get_action_request(legacy_request.request_id).status == "recorded"

    new_evidence = repository.record_evidence(
        "new-evidence", "shared-prefix", "observation", "new-source", "new-content"
    )
    new_claim = repository.record_claim(
        "new-claim", "shared-prefix", "new-statement", [new_evidence.evidence_id],
        claim_kind="inference",
    )
    new_request = repository.record_action_request(
        "new-request", "shared-prefix", "shadow.local", "observe.preview",
        "new-target", "new-payload",
    )
    partial = repository.record_initial_receipt(
        new_request.request_id, "new-receipt-one", "partial", output="partial"
    )
    final = repository.record_reconciliation_receipt(
        new_request.request_id, "new-receipt-two", "succeeded", partial.receipt_id,
        after="observed", verification="verified",
    )
    assert repository.list_evidence() == (legacy_evidence, new_evidence)
    assert repository.list_claims() == (legacy_claim, new_claim)
    assert repository.list_receipts(legacy_request.request_id) == (legacy_receipt,)
    assert repository.list_receipts(new_request.request_id) == (partial, final)
    events = repository.list_events(legacy_evidence.correlation_id)
    assert len(events) == 9
    assert [event.entity_type for event in events] == [
        "evidence", "claim", "action_request", "action_receipt",
        "evidence", "claim", "action_request", "action_receipt", "action_receipt",
    ]
    repository.verify_integrity()
    with sqlite3.connect(migrator.port.path) as connection:
        heads = connection.execute(
            "SELECT head_revision,event_count,last_event_id,head_hash,previous_head_hash "
            "FROM event_chain_heads WHERE workspace_id=? AND correlation_id=? "
            "ORDER BY head_revision",
            ("cyryx-primary", legacy_evidence.correlation_id),
        ).fetchall()
        assert [row[:2] for row in heads] == [
            (revision, event_count)
            for revision, event_count in enumerate(range(4, 10))
        ]
        assert [row[2] for row in heads] == [event.event_id for event in events[3:]]
        assert [row[4] for row in heads] == [
            None,
            *[row[3] for row in heads[:-1]],
        ]
        projections = connection.execute(
            "SELECT projection_revision,head_revision,event_count,source_event_id,"
            "state_sha256,previous_state_sha256 FROM projections "
            "WHERE workspace_id=? AND correlation_id=? ORDER BY projection_revision",
            ("cyryx-primary", legacy_evidence.correlation_id),
        ).fetchall()
        assert [row[:4] for row in projections] == [
            (revision, revision, event_count, events[event_count - 1].event_id)
            for revision, event_count in enumerate(range(4, 10))
        ]
        assert [row[5] for row in projections] == [
            None,
            *[row[4] for row in projections[:-1]],
        ]
    reopened = open_repository_for_testing(
        migrator, owner, registry, "cyryx-primary", enabled=True
    ).initialize()
    assert reopened.list_events(legacy_evidence.correlation_id) == events
    assert reopened.get_claim(new_claim.claim_id) == new_claim
    reopened.verify_integrity()
    with sqlite3.connect(migrator.port.path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM legacy_v2_event_envelopes"
        ).fetchone() == (4,)
        assert connection.execute(
            "SELECT count(*) FROM operational_commits"
        ).fetchone() == (6,)


def test_self_consistent_internal_root_rewrite_is_fenced_by_external_anchor(
    tmp_path, monkeypatch
):
    # Rewrite every internal digest consistently; the external anchor must
    # still fence the forged new root.
    repository, migrator, _owner, _registry = _fixture(
        tmp_path / "root-rewrite", monkeypatch
    )
    evidence = repository.record_evidence(
        "root-rewrite", "root-rewrite", "observation", "source", "content"
    )
    with sqlite3.connect(migrator.port.path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")

        def rewrite_root():
            connection.execute(
                "UPDATE evidence_records SET created_at=? WHERE evidence_id=?",
                ("2026-07-15T00:00:00+00:00", evidence.evidence_id),
            )
            identity = domain_ledger_v3._row_identity((evidence.evidence_id,))
            commit = connection.execute(
                "SELECT * FROM operational_commits WHERE commit_sequence=2"
            ).fetchone()
            entries = [
                list(row)
                for row in connection.execute(
                    "SELECT table_name,row_identity,row_sha256 "
                    "FROM operational_commit_entries WHERE commit_id=? "
                    "ORDER BY entry_ordinal",
                    (commit[0],),
                ).fetchall()
            ]
            for entry in entries:
                if entry[:2] == ["evidence_records", identity]:
                    entry[2] = domain_ledger_v3._row_sha256(
                        connection, "evidence_records", identity
                    )
            ordered = [tuple(entry) for entry in entries]
            delta = control_plane_v3._operational_delta_digest(entries)
            merkle_root, leaves, merkle_nodes = (
                control_plane_v3._entry_merkle_tree(ordered)
            )
            payload_root = control_plane_v3._operational_payload_root(
                sequence=2,
                previous_commit_id=commit[2],
                previous_state_root=commit[3],
                database_id=commit[4],
                fingerprint=commit[5],
                delta_sha256=delta,
                genesis_baseline_root=commit[8],
                entry_merkle_root=merkle_root,
                entry_count=commit[13],
                canonical_row_count=commit[14],
                event_count=commit[15],
                created_at=commit[16],
            )
            commit_id = control_plane_v3._operational_commit_id(
                state_root=payload_root,
                sequence=2,
                previous_commit_id=commit[2],
                delta_sha256=delta,
                created_at=commit[16],
            )
            mmr_leaf = control_plane_v3._mmr_leaf(commit_id, 2, payload_root)
            intent = connection.execute(
                "SELECT * FROM operational_anchor_intents WHERE commit_id=?",
                (commit[0],),
            ).fetchone()
            finalization = connection.execute(
                "SELECT * FROM operational_anchor_finalizations WHERE intent_id=?",
                (intent[0],),
            ).fetchone()
            connection.execute(
                "DELETE FROM operational_anchor_finalizations WHERE intent_id=?",
                (intent[0],),
            )
            connection.execute(
                "DELETE FROM operational_anchor_intents WHERE intent_id=?", (intent[0],)
            )
            connection.execute(
                "DELETE FROM operational_entry_merkle_nodes WHERE commit_id=?",
                (commit[0],),
            )
            connection.execute(
                "DELETE FROM operational_commit_entries WHERE commit_id=?", (commit[0],)
            )
            connection.execute(
                "DELETE FROM operational_mmr_peaks WHERE commit_sequence=2"
            )
            connection.execute(
                "DELETE FROM operational_mmr_edges WHERE parent_hash IN "
                "(SELECT node_hash FROM operational_mmr_nodes WHERE commit_sequence=2)"
            )
            connection.execute(
                "DELETE FROM operational_mmr_nodes WHERE commit_sequence=2"
            )
            connection.execute(
                "DELETE FROM operational_commits WHERE commit_sequence=2"
            )
            mmr_root, mmr_nodes, mmr_edges, mmr_peaks = (
                domain_ledger_v3._prepare_mmr_append(
                    connection, sequence=2, leaf_hash=mmr_leaf
                )
            )
            root = control_plane_v3._operational_state_root(
                sequence=2,
                previous_commit_id=commit[2],
                previous_state_root=commit[3],
                database_id=commit[4],
                fingerprint=commit[5],
                delta_sha256=delta,
                genesis_baseline_root=commit[8],
                entry_merkle_root=merkle_root,
                mmr_root=mmr_root,
                mmr_size=2,
                entry_count=commit[13],
                canonical_row_count=commit[14],
                event_count=commit[15],
                created_at=commit[16],
            )
            intent_id = control_plane_v3._operational_intent_id(
                commit_id, intent[2], root, intent[5]
            )
            final_id = control_plane_v3._operational_finalization_id(
                intent_id, intent[2], root, intent[5]
            )
            connection.execute(
                "INSERT INTO operational_commits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    commit_id, 2, commit[2], commit[3], commit[4], commit[5],
                    root, delta, commit[8], merkle_root, mmr_root, mmr_leaf, 2,
                    commit[13], commit[14], commit[15], commit[16],
                ),
            )
            connection.executemany(
                "INSERT INTO operational_commit_entries VALUES(?,?,?,?,?,?,?)",
                [
                    (commit_id, ordinal, *entry, ordinal, leaves[ordinal])
                    for ordinal, entry in enumerate(ordered)
                ],
            )
            connection.executemany(
                "INSERT INTO operational_entry_merkle_nodes VALUES(?,?,?,?)",
                [
                    (commit_id, level, index, node_hash)
                    for level, index, node_hash in merkle_nodes
                ],
            )
            connection.executemany(
                "INSERT INTO operational_mmr_nodes VALUES(?,?,?,?,?)", mmr_nodes
            )
            connection.executemany(
                "INSERT INTO operational_mmr_edges VALUES(?,?,?)", mmr_edges
            )
            connection.executemany(
                "INSERT INTO operational_mmr_peaks VALUES(?,?,?,?)", mmr_peaks
            )
            connection.execute(
                "INSERT INTO operational_anchor_intents VALUES(?,?,?,?,?,?)",
                (intent_id, commit_id, intent[2], root, intent[4], intent[5]),
            )
            connection.execute(
                "INSERT INTO operational_anchor_finalizations VALUES(?,?,?,?,?)",
                (final_id, intent_id, finalization[2], root, finalization[4]),
            )

        _drop_and_restore_triggers(
            connection,
            (
                "evidence_records", "operational_commits",
                "operational_commit_entries", "operational_anchor_intents",
                "operational_anchor_finalizations", "operational_entry_merkle_nodes",
                "operational_mmr_nodes", "operational_mmr_edges",
                "operational_mmr_peaks",
            ),
            rewrite_root,
        )
        connection.commit()
    with pytest.raises(DomainIntegrityError):
        repository.get_evidence(evidence.evidence_id)


def test_nonlatest_forge_recomputes_all_downstream_commits_but_external_root_fences_it(
    tmp_path, monkeypatch
):
    repository, migrator, _owner, _registry = _fixture(
        tmp_path / "downstream-root-rewrite", monkeypatch
    )
    first = repository.record_evidence(
        "downstream-first", "downstream-chain", "observation", "source", "one"
    )
    repository.record_evidence(
        "downstream-second", "downstream-chain", "observation", "source", "two"
    )
    external_before = migrator.anchor.verify(migrator.anchor_owner)
    with sqlite3.connect(migrator.port.path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")

        def rewrite_nonlatest_and_every_descendant():
            original_commits = {
                int(row[1]): tuple(row)
                for row in connection.execute(
                    "SELECT * FROM operational_commits WHERE commit_sequence>=2 "
                    "ORDER BY commit_sequence"
                ).fetchall()
            }
            original_entries = {
                sequence: [
                    [str(item[0]), str(item[1]), str(item[2])]
                    for item in connection.execute(
                        "SELECT e.table_name,e.row_identity,e.row_sha256 "
                        "FROM operational_commit_entries e "
                        "JOIN operational_commits c ON c.commit_id=e.commit_id "
                        "WHERE c.commit_sequence=? ORDER BY e.entry_ordinal",
                        (sequence,),
                    ).fetchall()
                ]
                for sequence in original_commits
            }
            original_bookkeeping = {}
            for sequence, commit in original_commits.items():
                intent = connection.execute(
                    "SELECT * FROM operational_anchor_intents WHERE commit_id=?",
                    (commit[0],),
                ).fetchone()
                finalization = connection.execute(
                    "SELECT * FROM operational_anchor_finalizations WHERE intent_id=?",
                    (intent[0],),
                ).fetchone()
                original_bookkeeping[sequence] = (tuple(intent), tuple(finalization))

            connection.execute(
                "UPDATE evidence_records SET created_at=? WHERE evidence_id=?",
                ("2026-07-15T00:00:00+00:00", first.evidence_id),
            )
            identity = domain_ledger_v3._row_identity((first.evidence_id,))
            rewritten_sha = domain_ledger_v3._row_sha256(
                connection, "evidence_records", identity
            )
            target = next(
                entry for entry in original_entries[2]
                if entry[0] == "evidence_records" and entry[1] == identity
            )
            target[2] = rewritten_sha

            affected_ids = tuple(commit[0] for commit in original_commits.values())
            affected_nodes = tuple(
                str(row[0]) for row in connection.execute(
                    "SELECT node_hash FROM operational_mmr_nodes "
                    "WHERE commit_sequence>=2"
                ).fetchall()
            )
            placeholders = ",".join("?" for _ in affected_ids)
            node_placeholders = ",".join("?" for _ in affected_nodes)
            connection.execute(
                "DELETE FROM operational_anchor_finalizations WHERE intent_id IN ("
                f"SELECT intent_id FROM operational_anchor_intents WHERE commit_id IN ({placeholders}))",
                affected_ids,
            )
            connection.execute(
                f"DELETE FROM operational_anchor_intents WHERE commit_id IN ({placeholders})",
                affected_ids,
            )
            connection.execute(
                "DELETE FROM operational_mmr_peaks WHERE commit_sequence>=2"
            )
            if affected_nodes:
                connection.execute(
                    f"DELETE FROM operational_mmr_edges WHERE parent_hash IN ({node_placeholders}) "
                    f"OR child_hash IN ({node_placeholders})",
                    (*affected_nodes, *affected_nodes),
                )
            connection.execute(
                "DELETE FROM operational_mmr_nodes WHERE commit_sequence>=2"
            )
            connection.execute(
                f"DELETE FROM operational_entry_merkle_nodes WHERE commit_id IN ({placeholders})",
                affected_ids,
            )
            connection.execute(
                f"DELETE FROM operational_commit_entries WHERE commit_id IN ({placeholders})",
                affected_ids,
            )
            connection.execute(
                f"DELETE FROM operational_commits WHERE commit_id IN ({placeholders})",
                affected_ids,
            )

            predecessor = connection.execute(
                "SELECT commit_id,state_root FROM operational_commits "
                "WHERE commit_sequence=1"
            ).fetchone()
            previous_commit_id, previous_root = map(str, predecessor)
            for sequence in sorted(original_commits):
                old = original_commits[sequence]
                entries = [tuple(entry) for entry in original_entries[sequence]]
                delta = control_plane_v3._operational_delta_digest(entries)
                merkle_root, leaves, merkle_nodes = (
                    control_plane_v3._entry_merkle_tree(entries)
                )
                payload_root = control_plane_v3._operational_payload_root(
                    sequence=sequence,
                    previous_commit_id=previous_commit_id,
                    previous_state_root=previous_root,
                    database_id=str(old[4]),
                    fingerprint=str(old[5]),
                    delta_sha256=delta,
                    genesis_baseline_root=str(old[8]),
                    entry_merkle_root=merkle_root,
                    entry_count=int(old[13]),
                    canonical_row_count=int(old[14]),
                    event_count=int(old[15]),
                    created_at=str(old[16]),
                )
                commit_id = control_plane_v3._operational_commit_id(
                    state_root=payload_root,
                    sequence=sequence,
                    previous_commit_id=previous_commit_id,
                    delta_sha256=delta,
                    created_at=str(old[16]),
                )
                leaf = control_plane_v3._mmr_leaf(
                    commit_id, sequence, payload_root
                )
                mmr_root, mmr_nodes, mmr_edges, peaks = (
                    domain_ledger_v3._prepare_mmr_append(
                        connection, sequence=sequence, leaf_hash=leaf
                    )
                )
                state_root = control_plane_v3._operational_state_root(
                    sequence=sequence,
                    previous_commit_id=previous_commit_id,
                    previous_state_root=previous_root,
                    database_id=str(old[4]),
                    fingerprint=str(old[5]),
                    delta_sha256=delta,
                    genesis_baseline_root=str(old[8]),
                    entry_merkle_root=merkle_root,
                    mmr_root=mmr_root,
                    mmr_size=sequence,
                    entry_count=int(old[13]),
                    canonical_row_count=int(old[14]),
                    event_count=int(old[15]),
                    created_at=str(old[16]),
                )
                connection.execute(
                    "INSERT INTO operational_commits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        commit_id, sequence, previous_commit_id, previous_root,
                        old[4], old[5], state_root, delta, old[8], merkle_root,
                        mmr_root, leaf, sequence, old[13], old[14], old[15], old[16],
                    ),
                )
                connection.executemany(
                    "INSERT INTO operational_commit_entries VALUES(?,?,?,?,?,?,?)",
                    [
                        (commit_id, ordinal, *entry, ordinal, leaves[ordinal])
                        for ordinal, entry in enumerate(entries)
                    ],
                )
                connection.executemany(
                    "INSERT INTO operational_entry_merkle_nodes VALUES(?,?,?,?)",
                    [
                        (commit_id, level, index, node_hash)
                        for level, index, node_hash in merkle_nodes
                    ],
                )
                connection.executemany(
                    "INSERT INTO operational_mmr_nodes VALUES(?,?,?,?,?)", mmr_nodes
                )
                connection.executemany(
                    "INSERT INTO operational_mmr_edges VALUES(?,?,?)", mmr_edges
                )
                connection.executemany(
                    "INSERT INTO operational_mmr_peaks VALUES(?,?,?,?)", peaks
                )
                old_intent, old_finalization = original_bookkeeping[sequence]
                intent_id = control_plane_v3._operational_intent_id(
                    commit_id, int(old_intent[2]), state_root, str(old_intent[5])
                )
                finalization_id = control_plane_v3._operational_finalization_id(
                    intent_id,
                    int(old_finalization[2]),
                    state_root,
                    str(old_finalization[4]),
                )
                connection.execute(
                    "INSERT INTO operational_anchor_intents VALUES(?,?,?,?,?,?)",
                    (
                        intent_id, commit_id, old_intent[2], state_root,
                        old_intent[4], old_intent[5],
                    ),
                )
                connection.execute(
                    "INSERT INTO operational_anchor_finalizations VALUES(?,?,?,?,?)",
                    (
                        finalization_id, intent_id, old_finalization[2],
                        state_root, old_finalization[4],
                    ),
                )
                previous_commit_id, previous_root = commit_id, state_root

        _drop_and_restore_triggers(
            connection,
            (
                "evidence_records", "operational_commits",
                "operational_commit_entries", "operational_entry_merkle_nodes",
                "operational_mmr_nodes", "operational_mmr_edges",
                "operational_mmr_peaks", "operational_anchor_intents",
                "operational_anchor_finalizations",
            ),
            rewrite_nonlatest_and_every_descendant,
        )
        connection.commit()
        forged_root = str(connection.execute(
            "SELECT state_root FROM operational_commits "
            "ORDER BY commit_sequence DESC LIMIT 1"
        ).fetchone()[0])
        # The coordinated forgery is self-consistent inside SQLite: the latest
        # operational validator and the row's Merkle-to-MMR witness both pass.
        # Only the independently stored external anchor is left unchanged.
        internally_valid = control_plane_v3._validate_operational_latest(
            connection, allow_projected_finalization=False
        )
        assert internally_valid is not None
        assert str(internally_valid.commit[6]) == forged_root
        repository._validate_entry_witness(
            connection, "evidence_records", first.evidence_id, legacy=False
        )
    assert forged_root != external_before.ledger_root
    with pytest.raises(DomainIntegrityError):
        repository.get_evidence(first.evidence_id)


@pytest.mark.parametrize(
    "corruption",
    ("entry_leaf", "merkle_sibling", "mmr_node_hash", "mmr_peak_hash"),
)
def test_hot_witness_rejects_malformed_persisted_digests_as_fresh_integrity_errors(
    tmp_path, monkeypatch, corruption
):
    repository, migrator, _owner, _registry = _fixture(
        tmp_path / corruption, monkeypatch
    )
    evidence = repository.record_evidence(
        f"malformed-{corruption}", "malformed-digest", "observation", "source", "body"
    )
    identity = domain_ledger_v3._row_identity((evidence.evidence_id,))
    malformed = "g" * 64
    with sqlite3.connect(migrator.port.path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA ignore_check_constraints=ON")
        witness = connection.execute(
            "SELECT e.commit_id,e.leaf_index,c.entry_count,c.mmr_leaf_hash "
            "FROM operational_commit_entries e JOIN operational_commits c "
            "ON c.commit_id=e.commit_id WHERE e.table_name=? AND e.row_identity=?",
            ("evidence_records", identity),
        ).fetchone()
        assert witness is not None
        commit_id, leaf_index, entry_count, mmr_leaf = witness

        def corrupt_digest():
            if corruption == "entry_leaf":
                connection.execute(
                    "UPDATE operational_commit_entries SET leaf_hash=? "
                    "WHERE commit_id=? AND leaf_index=?",
                    (malformed, commit_id, leaf_index),
                )
            elif corruption == "merkle_sibling":
                sibling_index = int(leaf_index) ^ 1
                assert sibling_index < int(entry_count)
                connection.execute(
                    "UPDATE operational_entry_merkle_nodes SET node_hash=? "
                    "WHERE commit_id=? AND tree_level=0 AND node_index=?",
                    (malformed, commit_id, sibling_index),
                )
            elif corruption == "mmr_node_hash":
                parent = connection.execute(
                    "SELECT parent_hash FROM operational_mmr_edges WHERE child_hash=?",
                    (mmr_leaf,),
                ).fetchone()
                assert parent is not None
                connection.execute(
                    "UPDATE operational_mmr_nodes SET left_hash=? WHERE node_hash=?",
                    (malformed, parent[0]),
                )
            else:
                connection.execute(
                    "UPDATE operational_mmr_peaks SET peak_hash=? "
                    "WHERE commit_sequence=(SELECT commit_sequence FROM operational_commits "
                    "WHERE commit_id=?) AND peak_ordinal=0",
                    (malformed, commit_id),
                )

        table = {
            "entry_leaf": "operational_commit_entries",
            "merkle_sibling": "operational_entry_merkle_nodes",
            "mmr_node_hash": "operational_mmr_nodes",
            "mmr_peak_hash": "operational_mmr_peaks",
        }[corruption]
        _drop_and_restore_triggers(connection, (table,), corrupt_digest)
        connection.commit()

        with pytest.raises(DomainIntegrityError) as direct:
            repository._validate_entry_witness(
                connection, "evidence_records", evidence.evidence_id, legacy=False
            )
        assert direct.value.__cause__ is None
        assert direct.value.__context__ is None

    with pytest.raises(DomainIntegrityError) as public:
        repository.get_evidence(evidence.evidence_id)
    assert public.value.__cause__ is None
    assert public.value.__context__ is None


def test_fixed_operational_crypto_vectors_match_independent_reference():
    def encode(value):
        if isinstance(value, int):
            payload = str(value).encode("ascii")
            return b"I" + len(payload).to_bytes(8, "big") + payload
        payload = value.encode("utf-8")
        return b"S" + len(payload).to_bytes(8, "big") + payload

    entries = (
        ("evidence_records", '["e-fixed"]', "11" * 32),
        ("claims", '["c-fixed"]', "ab" * 32),
        ("event_envelopes", '["event-fixed"]', "cd" * 32),
    )
    delta_hash = hashlib.sha256(b"ONYX-V3-OPERATIONAL-DELTA-V1\0")
    for entry in entries:
        for value in entry:
            delta_hash.update(encode(value))
    delta_hash.update(encode(len(entries)))
    delta = delta_hash.hexdigest()

    leaves = []
    for ordinal, (table, identity, row_hash) in enumerate(entries):
        leaf_hash = hashlib.sha256(b"ONYX-V3-ENTRY-MERKLE-LEAF-V1\0")
        for value in (ordinal, table, identity, row_hash):
            leaf_hash.update(encode(value))
        leaves.append(leaf_hash.hexdigest())
    level = list(leaves)
    while len(level) > 1:
        parents = []
        for index in range(0, len(level), 2):
            left = level[index]
            # The fixed three-entry vector exercises the specified odd-leaf
            # duplication rule independently of production code.
            right = level[index + 1] if index + 1 < len(level) else left
            parents.append(hashlib.sha256(
                b"ONYX-V3-ENTRY-MERKLE-NODE-V1\0"
                + bytes.fromhex(left)
                + bytes.fromhex(right)
            ).hexdigest())
        level = parents
    merkle = level[0]

    sequence = 4
    previous_commit_id = "66" * 32
    previous_state_root = "77" * 32
    database_id = "db-vector"
    fingerprint = "88" * 32
    genesis_baseline_root = "99" * 32
    created_at = "2026-07-15T12:34:56+00:00"
    payload_bytes = json.dumps(
        [
            sequence, previous_commit_id, previous_state_root, database_id,
            fingerprint, delta, genesis_baseline_root, merkle,
            len(entries), 42, 7, created_at,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload_root = hashlib.sha256(
        b"ONYX-V3-OPERATIONAL-PAYLOAD-V2\0" + payload_bytes
    ).hexdigest()
    commit_bytes = json.dumps(
        [payload_root, sequence, previous_commit_id, delta, created_at],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    commit_id = hashlib.sha256(
        b"ONYX-V3-OPERATIONAL-COMMIT-V1\0" + commit_bytes
    ).hexdigest()
    mmr_leaf_hash = hashlib.sha256(b"ONYX-V3-MMR-LEAF-V1\0")
    for value in (commit_id, sequence, payload_root):
        mmr_leaf_hash.update(encode(value))
    mmr_leaf = mmr_leaf_hash.hexdigest()
    prior_high = "aa" * 32
    prior_low = "bb" * 32
    low_parent_hash = hashlib.sha256(b"ONYX-V3-MMR-NODE-V1\0")
    for value in (1, prior_low, mmr_leaf):
        low_parent_hash.update(encode(value))
    low_parent = low_parent_hash.hexdigest()
    high_parent_hash = hashlib.sha256(b"ONYX-V3-MMR-NODE-V1\0")
    for value in (2, prior_high, low_parent):
        high_parent_hash.update(encode(value))
    high_parent = high_parent_hash.hexdigest()
    peaks_hash = hashlib.sha256(b"ONYX-V3-MMR-PEAKS-V1\0")
    peaks_hash.update(encode(2))
    peaks_hash.update(encode(high_parent))
    peaks_hash.update(encode(1))
    mmr_bag = peaks_hash.hexdigest()
    state_bytes = json.dumps(
        [
            sequence, previous_commit_id, previous_state_root, database_id,
            fingerprint, delta, genesis_baseline_root, merkle, mmr_bag,
            sequence, len(entries), 42, 7, created_at,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    state_root = hashlib.sha256(
        b"ONYX-V3-OPERATIONAL-ROOT-V2\0" + state_bytes
    ).hexdigest()

    assert control_plane_v3._operational_delta_digest(entries) == delta
    produced_merkle, produced_leaves, _nodes = (
        control_plane_v3._entry_merkle_tree(entries)
    )
    assert produced_leaves == tuple(leaves)
    assert produced_merkle == merkle
    assert control_plane_v3._operational_payload_root(
        sequence=sequence,
        previous_commit_id=previous_commit_id,
        previous_state_root=previous_state_root,
        database_id=database_id,
        fingerprint=fingerprint,
        delta_sha256=delta,
        genesis_baseline_root=genesis_baseline_root,
        entry_merkle_root=merkle,
        entry_count=len(entries),
        canonical_row_count=42,
        event_count=7,
        created_at=created_at,
    ) == payload_root
    assert control_plane_v3._operational_commit_id(
        state_root=payload_root,
        sequence=sequence,
        previous_commit_id=previous_commit_id,
        delta_sha256=delta,
        created_at=created_at,
    ) == commit_id
    assert control_plane_v3._mmr_leaf(commit_id, sequence, payload_root) == mmr_leaf
    assert control_plane_v3._mmr_parent(1, prior_low, mmr_leaf) == low_parent
    assert control_plane_v3._mmr_parent(2, prior_high, low_parent) == high_parent
    assert control_plane_v3._mmr_bag(((2, high_parent),)) == mmr_bag
    reference_db = sqlite3.connect(":memory:")
    try:
        reference_db.execute(
            "CREATE TABLE operational_mmr_peaks("
            "commit_sequence INTEGER,peak_ordinal INTEGER,"
            "peak_height INTEGER,peak_hash TEXT)"
        )
        reference_db.executemany(
            "INSERT INTO operational_mmr_peaks VALUES(?,?,?,?)",
            ((3, 0, 1, prior_high), (3, 1, 0, prior_low)),
        )
        produced_bag, produced_nodes, produced_edges, produced_peaks = (
            domain_ledger_v3._prepare_mmr_append(
                reference_db, sequence=sequence, leaf_hash=mmr_leaf
            )
        )
    finally:
        reference_db.close()
    assert produced_bag == mmr_bag
    assert produced_nodes == (
        (mmr_leaf, 0, None, None, sequence),
        (low_parent, 1, prior_low, mmr_leaf, sequence),
        (high_parent, 2, prior_high, low_parent, sequence),
    )
    assert produced_edges == (
        (low_parent, prior_low, 0), (low_parent, mmr_leaf, 1),
        (high_parent, prior_high, 0), (high_parent, low_parent, 1),
    )
    assert produced_peaks == ((sequence, 0, 2, high_parent),)
    assert control_plane_v3._operational_state_root(
        sequence=sequence,
        previous_commit_id=previous_commit_id,
        previous_state_root=previous_state_root,
        database_id=database_id,
        fingerprint=fingerprint,
        delta_sha256=delta,
        genesis_baseline_root=genesis_baseline_root,
        entry_merkle_root=merkle,
        mmr_root=mmr_bag,
        mmr_size=sequence,
        entry_count=len(entries),
        canonical_row_count=42,
        event_count=7,
        created_at=created_at,
    ) == state_root
    assert {
        "delta": delta,
        "entry_leaf": leaves[0],
        "merkle": merkle,
        "payload_root": payload_root,
        "commit_id": commit_id,
        "mmr_leaf": mmr_leaf,
        "mmr_parent_low": low_parent,
        "mmr_parent_high": high_parent,
        "mmr_bag": mmr_bag,
        "state_root": state_root,
    } == {
        "delta": "ac6a9c3a8f36cd406b3e8e95b7f9f59ede56e71526583d925f548cee67f37fe4",
        "entry_leaf": "85842f4f818d3fa9d408ccddc1214e836c69a3ef7c863b67d15062fc827a6c52",
        "merkle": "06f74ccbb88298ac13062fa1597b0a463117a17b440b4b5949a4b5d3dc438900",
        "payload_root": "3206a418f0dec77f8ba01e01500ac3b9e6224c96c130c80366e6250d2de8b116",
        "commit_id": "9e800d97eb5cfa22703ec9521c525183bfa1c4a01b5c29a64f8769534b3de127",
        "mmr_leaf": "ba33aaee3b28a0c25187e44c36fcba9088361a727601f5ef2ff089dc40e0b62f",
        "mmr_parent_low": "4763e2324f3ae557d68d2d8d8c313df05ad60f59f32c16a99c9166d12a9dab7c",
        "mmr_parent_high": "5c992445e499a77d64fd8ebece292ddb7e379740b385683fd16c4169240ce628",
        "mmr_bag": "417771d8e7e34615f89b9d1ca460b0e83fe79bf6e1be04b0d13c8fedc6558eab",
        "state_root": "9d44547cd0ad01fd92b134772dc61405d981ae21a194362905a58c189de427e5",
    }
