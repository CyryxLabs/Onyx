from __future__ import annotations

import inspect
import sqlite3
import threading
import traceback
from pathlib import Path

import pytest

import core.control_plane as control_plane
import core.control_plane_v3 as control_plane_v3
from core import ledger_anchor
from core.control_plane import ControlPlaneError, ControlPlaneSchemaError, ControlPlaneStore
from core.control_plane_v3 import (
    ControlPlaneV3Conflict,
    ControlPlaneV3IOError,
    ControlPlaneV3IntegrityError,
    ControlPlaneV3Disabled,
    ControlPlaneV3Unavailable,
    _open_for_testing as _raw_open_for_testing,
    _validate_v3_mappings,
    ledger_v3_enabled,
    open_default,
)
from core.domain_ledger import DomainLedgerRepository
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


class _Cancellation(BaseException):
    pass


def _open_for_testing(*args, **kwargs):
    """Every fixture explicitly opts into the isolated migration checkpoint."""

    return _raw_open_for_testing(*args, enabled=True, **kwargs)


def _store(tmp_path, monkeypatch) -> ControlPlaneStore:
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: tmp_path
    )
    return ControlPlaneStore(enabled=True).initialize()


def test_v3_flag_is_strict_and_production_port_is_unwired(monkeypatch):
    assert not ledger_v3_enabled({})
    assert not ledger_v3_enabled({"ONYX_M2B_LEDGER_V3": "yes"})
    assert ledger_v3_enabled({"ONYX_M2B_LEDGER_V3": "true"})
    monkeypatch.delenv("ONYX_M2B_LEDGER_V3", raising=False)
    with pytest.raises(ControlPlaneV3Disabled):
        open_default()
    monkeypatch.setenv("ONYX_M2B_LEDGER_V3", "1")
    with pytest.raises(ControlPlaneV3Unavailable):
        open_default()


def test_test_factory_requires_explicit_enabled_decision():
    parameter = inspect.signature(_raw_open_for_testing).parameters["enabled"]
    assert parameter.default is inspect.Parameter.empty


def test_v3_is_absent_from_startup_mission_tool_and_ui_surfaces():
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
        assert "control_plane_v3" not in source
        assert "ONYX_M2B_LEDGER_V3" not in source


def test_empty_v2_migrates_to_exact_anchored_v3(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    connection = store._require_connection()
    before_metadata = dict(connection.execute("SELECT key,value FROM schema_metadata"))
    before_journal = connection.execute(
        "SELECT migration_id,schema_from,schema_to,status,applied_at,schema_fingerprint "
        "FROM migration_journal ORDER BY schema_to"
    ).fetchall()
    key_vault = _MemoryVault()
    state_vault = _MemoryVault()
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=key_vault,
        state_vault=state_vault,
    )
    status = migrator.migrate(owner)
    assert status.exposed
    assert status.schema_version == 3
    assert migrator.open(owner) == status

    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        metadata = dict(connection.execute("SELECT key,value FROM schema_metadata"))
        assert metadata["created_at"] == before_metadata["created_at"]
        journal = connection.execute(
            "SELECT migration_id,schema_from,schema_to,status,applied_at,schema_fingerprint "
            "FROM migration_journal ORDER BY schema_to"
        ).fetchall()
        assert journal[:2] == before_journal
    finally:
        connection.close()

    with pytest.raises(ControlPlaneSchemaError):
        ControlPlaneStore(enabled=True).initialize()


def test_populated_history_is_typed_linked_and_revisioned(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register(
        "cyryx-primary", display_name="Cyryx Primary", workspace_class="cyryx"
    )
    repository = DomainLedgerRepository(
        registry, "cyryx-primary", enabled=True
    ).initialize()
    evidence = repository.record_evidence(
        "evidence", "shared-chain", "observation", "source", "content"
    )
    first_claim = repository.record_claim(
        "claim", "shared-chain", "statement", [evidence.evidence_id]
    )
    second_claim = repository.record_claim(
        "claim-contradiction",
        "shared-chain",
        "contradiction",
        [evidence.evidence_id],
        contradiction_claim_ids=[first_claim.claim_id],
    )
    repository.record_claim(
        "claim-supersedes",
        "shared-chain",
        "revision",
        [evidence.evidence_id],
        supersedes_claim_id=second_claim.claim_id,
    )
    request = repository.record_action_request(
        "request",
        "shared-chain",
        "shadow.local",
        "observe.preview",
        "target",
        "payload",
    )
    first = repository.record_initial_receipt(
        request.request_id, "first", "unknown"
    )
    repository.record_reconciliation_receipt(
        request.request_id,
        "second",
        "simulated",
        first.receipt_id,
        output="observed",
        verification="matched",
    )
    repository.verify_integrity()

    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)
    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("SELECT count(*) FROM evidence_records").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM claim_evidence_links").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM claim_relations").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM action_receipts").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM action_state_history").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM event_envelopes").fetchone()[0] == 7
        projection = connection.execute(
            "SELECT projection_revision,head_revision,event_count,source_event_id,"
            "state_sha256,created_at,updated_at FROM projections"
        ).fetchone()
        head = connection.execute(
            "SELECT head_revision,event_count,last_event_id,head_hash FROM event_chain_heads"
        ).fetchone()
        assert projection[:2] == (0, 0)
        assert projection[2:5] == (head[1], head[2], head[3])
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    assert migrator.open(owner).exposed


def test_invalid_v2_aborts_before_anchor_and_without_logical_change(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register("cyryx", display_name="Cyryx", workspace_class="cyryx")
    repository = DomainLedgerRepository(registry, "cyryx", enabled=True).initialize()
    repository.record_evidence("bad", "bad", "observation", "source", "content")
    connection = store._require_connection()
    connection.execute(
        "UPDATE event_envelopes SET event_hash=?", ("f" * 64,)
    )
    before = "\n".join(connection.iterdump())
    key_vault = _MemoryVault()
    state_vault = _MemoryVault()
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=key_vault,
        state_vault=state_vault,
    )
    with pytest.raises(ControlPlaneV3IntegrityError):
        migrator.migrate(owner)
    assert "\n".join(connection.iterdump()) == before
    assert key_vault.value is None
    assert state_vault.value is None
    assert not (tmp_path / "anchor.journal").exists()


def test_postcommit_crash_recovers_before_exposure(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    key_vault = _MemoryVault()
    state_vault = _MemoryVault()
    journal = tmp_path / "anchor.journal"
    migrator, owner = _open_for_testing(
        store,
        journal_path=journal,
        key_vault=key_vault,
        state_vault=state_vault,
    )

    class _Crash(BaseException):
        pass

    def crash(point):
        if point == "after_sqlite_commit":
            raise _Crash()

    migrator._fault = crash
    with pytest.raises(_Crash):
        migrator.migrate(owner)

    recovered, recovery_owner = _open_for_testing(
        store,
        journal_path=journal,
        key_vault=key_vault,
        state_vault=state_vault,
    )
    status = recovered.recover(recovery_owner)
    assert status.exposed
    assert recovered.open(recovery_owner) == status


def test_immutable_rows_and_trigger_drop_fail_closed(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)
    connection = sqlite3.connect(store.path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE integrity_commits SET state_root=?", ("f" * 64,)
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO legacy_v2_projections VALUES(?,?,?,?,?,?,?)",
                ("x", "legacy-default", 2, "x", "{}", "x", "x"),
            )
        connection.execute("DROP TRIGGER deny_integrity_commits_update")
        connection.execute(
            "CREATE TRIGGER deny_integrity_commits_update BEFORE UPDATE ON integrity_commits "
            "BEGIN SELECT 1; END"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ControlPlaneV3IntegrityError):
        migrator.open(owner)


def test_restored_old_database_is_rejected_by_v3_anchor(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    backup = tmp_path / "v2-backup.sqlite3"
    destination = sqlite3.connect(backup)
    try:
        store._require_connection().backup(destination)
    finally:
        destination.close()
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)
    store.path.write_bytes(backup.read_bytes())
    with pytest.raises((ControlPlaneV3IntegrityError, ControlPlaneV3Conflict)):
        migrator.open(owner)


def test_precommit_prepared_fault_rolls_back_and_is_retriable(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )

    class _Interrupt(BaseException):
        pass

    def interrupt(point):
        if point == "after_anchor_prepare":
            raise _Interrupt()

    migrator._fault = interrupt
    with pytest.raises(_Interrupt):
        migrator.migrate(owner)
    assert store._require_connection().execute("PRAGMA user_version").fetchone()[0] == 2
    migrator._fault = lambda _point: None
    assert migrator.migrate(owner).exposed


@pytest.mark.parametrize("fault_point", ["before_anchor_finalize", "after_anchor_finalize"])
def test_finalize_boundary_fault_is_recoverable(
    tmp_path, monkeypatch, fault_point
):
    store = _store(tmp_path, monkeypatch)
    key_vault = _MemoryVault()
    state_vault = _MemoryVault()
    journal = tmp_path / "anchor.journal"
    migrator, owner = _open_for_testing(
        store,
        journal_path=journal,
        key_vault=key_vault,
        state_vault=state_vault,
    )

    class _Interrupt(BaseException):
        pass

    def interrupt(point):
        if point == fault_point:
            raise _Interrupt()

    migrator._fault = interrupt
    with pytest.raises(_Interrupt):
        migrator.migrate(owner)
    recovered, recovery_owner = _open_for_testing(
        store,
        journal_path=journal,
        key_vault=key_vault,
        state_vault=state_vault,
    )
    assert recovered.recover(recovery_owner).exposed
    assert recovered.open(recovery_owner).exposed


def test_fault_after_finalization_is_already_safe_to_open(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )

    class _Interrupt(BaseException):
        pass

    def interrupt(point):
        if point == "after_finalization_record":
            raise _Interrupt()

    migrator._fault = interrupt
    with pytest.raises(_Interrupt):
        migrator.migrate(owner)
    assert migrator.open(owner).exposed


def test_preexisting_anchor_sequence_is_preserved_and_extended(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register("cyryx", display_name="Cyryx", workspace_class="cyryx")
    repository = DomainLedgerRepository(registry, "cyryx", enabled=True).initialize()
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    assert migrator._ensure_anchor().sequence == 0
    repository.record_evidence("later", "later", "observation", "source", "content")
    ticket = migrator.anchor.prepare(migrator.anchor_owner)
    assert migrator.anchor.finalize(migrator.anchor_owner, ticket).sequence == 1
    status = migrator.migrate(owner)
    assert status.anchor_sequence == 2
    assert migrator.open(owner).anchor_sequence == 2


def test_wal_and_concurrent_migration_converge_to_one_v3(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    assert store._require_connection().execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    barrier = threading.Barrier(2)
    results = []
    failures = []

    def worker():
        try:
            barrier.wait()
            results.append(migrator.migrate(owner))
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert len(results) == 1
    assert len(failures) == 1
    assert migrator.open(owner).exposed


def test_valid_v2_race_between_anchor_and_write_lock_is_denied(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register("cyryx", display_name="Cyryx", workspace_class="cyryx")
    repository = DomainLedgerRepository(registry, "cyryx", enabled=True).initialize()
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    raced = False

    def mutate(point):
        nonlocal raced
        if point == "before_v2_lock" and not raced:
            raced = True
            repository.record_evidence(
                "raced", "raced", "observation", "source", "content"
            )

    migrator._fault = mutate
    with pytest.raises(ControlPlaneV3Conflict):
        migrator.migrate(owner)
    connection = store._require_connection()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert connection.execute(
        "SELECT count(*) FROM evidence_records"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT count(*) FROM sqlite_master WHERE name='legacy_v2_evidence_records'"
    ).fetchone()[0] == 0


def test_malformed_v2_payload_is_normalized_without_detail_leak(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register("cyryx", display_name="Cyryx", workspace_class="cyryx")
    repository = DomainLedgerRepository(registry, "cyryx", enabled=True).initialize()
    evidence = repository.record_evidence(
        "malformed", "malformed", "observation", "source", "content"
    )
    canary = "private-canary-must-not-leak"
    store._require_connection().execute(
        "UPDATE evidence_records SET payload_json=? WHERE evidence_id=?",
        ("{" + canary, evidence.evidence_id),
    )
    key_vault = _MemoryVault()
    state_vault = _MemoryVault()
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=key_vault,
        state_vault=state_vault,
    )
    with pytest.raises(ControlPlaneV3IntegrityError) as failure:
        migrator.migrate(owner)
    assert canary not in str(failure.value)
    assert key_vault.value is None
    assert state_vault.value is None


def test_independent_projection_rederivation_detects_field_drift(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register("cyryx", display_name="Cyryx", workspace_class="cyryx")
    repository = DomainLedgerRepository(registry, "cyryx", enabled=True).initialize()
    repository.record_evidence("projection", "projection", "observation", "s", "c")
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("DROP TRIGGER deny_projections_update")
        connection.execute("UPDATE projections SET updated_at='2000-01-01T00:00:00+00:00'")
        with pytest.raises(ControlPlaneV3IntegrityError, match="projection typed mapping"):
            _validate_v3_mappings(connection)
    finally:
        connection.close()


def _append_synthetic_event_head(connection, *, marker: str):
    head = connection.execute(
        "SELECT workspace_id,correlation_id,head_revision,event_count,head_hash,"
        "first_event_id FROM event_chain_heads ORDER BY head_revision DESC LIMIT 1"
    ).fetchone()
    entity = connection.execute(
        "SELECT workspace_id,mission_id,correlation_id,entity_type,entity_id,"
        "entity_sha256 FROM event_envelopes ORDER BY event_sequence LIMIT 1"
    ).fetchone()
    event_id = f"synthetic-event-{marker}"
    event_hash = marker * 64
    created_at = f"2099-01-0{head[2] + 2}T00:00:00+00:00"
    connection.execute(
        "INSERT INTO event_envelopes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event_id,
            entity[0],
            entity[1],
            entity[2],
            head[3],
            3,
            f"{entity[3]}.recorded",
            entity[3],
            entity[4],
            entity[5],
            None,
            None,
            head[4],
            event_hash,
            "{}",
            created_at,
        ),
    )
    connection.execute(
        "INSERT INTO event_chain_history VALUES(?,?,?,?,?,?)",
        (entity[0], entity[2], head[3], event_id, head[4], event_hash),
    )
    connection.execute(
        "INSERT INTO event_chain_heads VALUES(?,?,?,?,?,?,?,?)",
        (
            entity[0],
            entity[2],
            head[2] + 1,
            head[3] + 1,
            event_hash,
            head[5],
            event_id,
            head[4],
        ),
    )
    return {
        "event_id": event_id,
        "event_hash": event_hash,
        "head_revision": head[2] + 1,
        "event_count": head[3] + 1,
    }


def _projection_candidate(prior, head, *, revision: int):
    return [
        prior["projection_id"],
        revision,
        prior["workspace_id"],
        prior["mission_id"],
        3,
        prior["projection_type"],
        prior["correlation_id"],
        head["head_revision"],
        head["event_count"],
        head["event_id"],
        head["event_hash"],
        prior["state_sha256"],
        "a" * 64,
        "{}",
        prior["created_at"],
        "9999-12-31T23:59:59+00:00",
    ]


def _migrated_single_projection(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    registry.register("cyryx", display_name="Cyryx", workspace_class="cyryx")
    repository = DomainLedgerRepository(registry, "cyryx", enabled=True).initialize()
    repository.record_evidence("projection", "projection", "observation", "s", "c")
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)
    connection = sqlite3.connect(store.path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("projection_type", "different-projection-type"),
        ("correlation_id", "different-correlation"),
        ("workspace_id", "different-workspace"),
        ("mission_id", "different-mission"),
        ("created_at", "2000-01-01T00:00:00+00:00"),
        ("previous_state_sha256", "b" * 64),
    ),
)
def test_projection_revision_rejects_identity_or_state_drift(
    tmp_path, monkeypatch, column, value
):
    connection = _migrated_single_projection(tmp_path, monkeypatch)
    try:
        prior = connection.execute("SELECT * FROM projections").fetchone()
        next_head = _append_synthetic_event_head(connection, marker="d")
        candidate = _projection_candidate(prior, next_head, revision=1)
        columns = [item[1] for item in connection.execute("PRAGMA table_info(projections)")]
        candidate[columns.index(column)] = value
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO projections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                candidate,
            )
        assert connection.execute("SELECT count(*) FROM projections").fetchone()[0] == 1
    finally:
        connection.close()


def test_projection_revision_rejects_regressing_head_and_event_count(
    tmp_path, monkeypatch
):
    connection = _migrated_single_projection(tmp_path, monkeypatch)
    try:
        revision_zero = connection.execute("SELECT * FROM projections").fetchone()
        first_head = _append_synthetic_event_head(connection, marker="d")
        second_head = _append_synthetic_event_head(connection, marker="e")
        revision_one = _projection_candidate(revision_zero, second_head, revision=1)
        connection.execute(
            "INSERT INTO projections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            revision_one,
        )
        prior = connection.execute(
            "SELECT * FROM projections WHERE projection_revision=1"
        ).fetchone()
        regressing = _projection_candidate(prior, first_head, revision=2)
        with pytest.raises(sqlite3.IntegrityError, match="projection revision mismatch"):
            connection.execute(
                "INSERT INTO projections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                regressing,
            )
        assert connection.execute("SELECT count(*) FROM projections").fetchone()[0] == 2
    finally:
        connection.close()


_BOOKKEEPING_FIELD_MUTATIONS = (
    ("integrity_commits", "commit_id", "e" * 64),
    ("integrity_commits", "database_instance_id", "cp-" + "e" * 64),
    ("integrity_commits", "schema_fingerprint", "e" * 64),
    ("integrity_commits", "state_root", "e" * 64),
    ("integrity_commits", "root_row_count", 987654321),
    ("integrity_commits", "algorithm", "sha512-rewritten"),
    ("integrity_commits", "created_at", "2001-01-01T00:00:00+00:00"),
    ("anchor_intents", "intent_id", "d" * 64),
    ("anchor_intents", "commit_id", "d" * 64),
    ("anchor_intents", "anchor_sequence", 987654321),
    ("anchor_intents", "state_root", "d" * 64),
    ("anchor_intents", "status", "offline_rewritten"),
    ("anchor_intents", "created_at", "2002-01-01T00:00:00+00:00"),
    ("anchor_finalizations", "finalization_id", "c" * 64),
    ("anchor_finalizations", "intent_id", "c" * 64),
    ("anchor_finalizations", "anchor_sequence", 987654321),
    ("anchor_finalizations", "state_root", "c" * 64),
    ("anchor_finalizations", "created_at", "2003-01-01T00:00:00+00:00"),
)


def _drop_mutate_restore(connection, table, column, value):
    trigger = f"deny_{table}_update"
    sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (trigger,)
    ).fetchone()[0]
    connection.execute(f'DROP TRIGGER "{trigger}"')
    connection.execute("PRAGMA ignore_check_constraints=ON")
    connection.execute(f'UPDATE "{table}" SET "{column}"=?', (value,))
    connection.execute(sql)
    connection.commit()
    restored = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (trigger,)
    ).fetchone()[0]
    assert restored == sql


@pytest.mark.parametrize(
    ("table", "column", "value"),
    _BOOKKEEPING_FIELD_MUTATIONS,
    ids=lambda value: str(value)[:48],
)
def test_each_excluded_bookkeeping_field_is_tamper_evident_after_exact_ddl_restore(
    tmp_path, monkeypatch, table, column, value
):
    store = _store(tmp_path, monkeypatch)
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)
    connection = sqlite3.connect(store.path)
    try:
        _drop_mutate_restore(connection, table, column, value)
    finally:
        connection.close()
    with pytest.raises(ControlPlaneV3IntegrityError):
        migrator.open(owner)


def test_self_consistent_bookkeeping_rewrite_is_rejected_by_external_hmac_binding(
    tmp_path, monkeypatch
):
    store = _store(tmp_path, monkeypatch)
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)
    connection = sqlite3.connect(store.path)
    try:
        trigger_sql = {}
        for table in (
            "integrity_commits",
            "anchor_intents",
            "anchor_finalizations",
        ):
            trigger = f"deny_{table}_update"
            trigger_sql[trigger] = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
                (trigger,),
            ).fetchone()[0]
            connection.execute(f'DROP TRIGGER "{trigger}"')

        commit = connection.execute(
            "SELECT database_instance_id,schema_fingerprint,state_root,root_row_count "
            "FROM integrity_commits"
        ).fetchone()
        sequence = connection.execute(
            "SELECT anchor_sequence FROM anchor_intents"
        ).fetchone()[0]
        rewritten_at = "2004-01-01T00:00:00+00:00"
        root = control_plane_v3._stream_state_root(connection)
        assert (root.digest, root.row_count) == (commit[2], commit[3])
        commit_id = control_plane_v3._integrity_commit_id(
            commit[0], commit[1], root, rewritten_at
        )
        intent_id = control_plane_v3._intent_id(
            commit_id, sequence, root.digest, rewritten_at
        )
        finalization_id = control_plane_v3._finalization_id(
            intent_id, sequence, root.digest, rewritten_at
        )
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "UPDATE integrity_commits SET commit_id=?,created_at=?",
            (commit_id, rewritten_at),
        )
        connection.execute(
            "UPDATE anchor_intents SET intent_id=?,commit_id=?,created_at=?",
            (intent_id, commit_id, rewritten_at),
        )
        connection.execute(
            "UPDATE anchor_finalizations SET finalization_id=?,intent_id=?,created_at=?",
            (finalization_id, intent_id, rewritten_at),
        )
        for sql in trigger_sql.values():
            connection.execute(sql)
        connection.commit()
        connection.execute("PRAGMA foreign_keys=ON")
        # SQLite is now self-consistent and exact-DDL-valid.  Only the external
        # HMAC record still knows the original timestamp and IDs.
        assert control_plane_v3._validate_v3_exact(
            connection, require_finalization=True
        ).exposed
    finally:
        connection.close()
    with pytest.raises(
        ControlPlaneV3IntegrityError, match="v3 integrity verification failed"
    ) as captured:
        migrator.open(owner)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    rendered = "".join(traceback.format_exception(captured.value))
    assert rewritten_at not in rendered
    assert commit_id not in rendered
    assert intent_id not in rendered


def test_prepared_anchor_recovers_between_prepare_and_finalize(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    key_vault = _MemoryVault()
    state_vault = _MemoryVault()
    journal = tmp_path / "anchor.journal"
    migrator, owner = _open_for_testing(
        store,
        journal_path=journal,
        key_vault=key_vault,
        state_vault=state_vault,
    )

    class _Crash(BaseException):
        pass

    def crash(point):
        if point == "before_anchor_finalize":
            raise _Crash()

    migrator._fault = crash
    with pytest.raises(_Crash):
        migrator.migrate(owner)

    recovered, recovery_owner = _open_for_testing(
        store,
        journal_path=journal,
        key_vault=key_vault,
        state_vault=state_vault,
    )
    status = recovered.recover(recovery_owner)
    assert status.exposed
    assert recovered.open(recovery_owner) == status


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (OSError("private-canary:C:/sensitive/path"), ControlPlaneV3IOError),
        (
            sqlite3.OperationalError("private-canary:C:/sensitive/path"),
            ControlPlaneV3IOError,
        ),
        (
            ControlPlaneError("private-canary:C:/sensitive/path"),
            ControlPlaneV3IOError,
        ),
        (
            ControlPlaneSchemaError("private-canary:C:/sensitive/path"),
            ControlPlaneV3IntegrityError,
        ),
        (
            ControlPlaneV3IntegrityError("private-canary:C:/sensitive/path"),
            ControlPlaneV3IntegrityError,
        ),
        (
            ledger_anchor.LedgerAnchorIOError(
                "private-canary:C:/sensitive/path"
            ),
            ControlPlaneV3IOError,
        ),
        (
            ledger_anchor.LedgerAnchorIntegrityError(
                "private-canary:C:/sensitive/path"
            ),
            ControlPlaneV3IntegrityError,
        ),
    ),
)
def test_public_boundary_normalizes_host_and_anchor_failures_without_leak(
    tmp_path, monkeypatch, failure, expected
):
    store = _store(tmp_path, monkeypatch)
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)

    def fail(_owner):
        raise failure

    monkeypatch.setattr(migrator.anchor, "verify", fail)
    with pytest.raises(expected) as captured:
        migrator.open(owner)
    message = str(captured.value)
    rendered = "".join(traceback.format_exception(captured.value))
    assert "private-canary" not in message
    assert "sensitive" not in message
    assert "private-canary" not in rendered
    assert "C:/sensitive/path" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert captured.value is not failure


def test_public_boundary_normalizes_sqlite_failure_without_leak(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)

    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("private-canary:C:/sensitive/path")

    monkeypatch.setattr(control_plane_v3, "_open_canonical_connection", fail)
    with pytest.raises(ControlPlaneV3IOError) as captured:
        migrator.open(owner)
    assert "private-canary" not in str(captured.value)
    assert "sensitive" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "private-canary" not in "".join(
        traceback.format_exception(captured.value)
    )


@pytest.mark.parametrize(
    "interrupt", (KeyboardInterrupt(), SystemExit(7), _Cancellation("cancel"))
)
def test_public_boundary_never_swallows_process_interrupts(
    tmp_path, monkeypatch, interrupt
):
    store = _store(tmp_path, monkeypatch)
    migrator, owner = _open_for_testing(
        store,
        journal_path=tmp_path / "anchor.journal",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
    )
    migrator.migrate(owner)

    def fail(_owner):
        raise interrupt

    monkeypatch.setattr(migrator.anchor, "verify", fail)
    with pytest.raises(type(interrupt)) as captured:
        migrator.open(owner)
    assert captured.value is interrupt


@pytest.mark.parametrize("failing_pragma", (1, 2, 3, 4))
def test_canonical_connection_closes_after_each_pragma_failure(
    tmp_path, monkeypatch, failing_pragma
):
    class FakeConnection:
        def __init__(self):
            self.calls = 0
            self.closed = False

        def execute(self, _statement):
            self.calls += 1
            if self.calls == failing_pragma:
                raise sqlite3.OperationalError(
                    "private-canary:C:/sensitive/database.sqlite3"
                )

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(control_plane_v3.sqlite3, "connect", lambda *_a, **_k: connection)
    with pytest.raises(ControlPlaneV3IOError) as captured:
        control_plane_v3._open_canonical_connection(
            tmp_path / "database.sqlite3", read_only=False
        )
    assert connection.closed
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "private-canary" not in "".join(
        traceback.format_exception(captured.value)
    )


@pytest.mark.parametrize("failing_pragma", (1, 2, 3, 4))
def test_canonical_connection_closes_and_propagates_cancellation(
    tmp_path, monkeypatch, failing_pragma
):
    cancellation = _Cancellation(f"cancel-at-pragma-{failing_pragma}")

    class FakeConnection:
        def __init__(self):
            self.calls = 0
            self.closed = False

        def execute(self, _statement):
            self.calls += 1
            if self.calls == failing_pragma:
                raise cancellation

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(control_plane_v3.sqlite3, "connect", lambda *_a, **_k: connection)
    with pytest.raises(_Cancellation) as captured:
        control_plane_v3._open_canonical_connection(
            tmp_path / "database.sqlite3", read_only=False
        )
    assert captured.value is cancellation
    assert connection.closed
