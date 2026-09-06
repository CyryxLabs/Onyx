"""Independent adversarial audit contracts for the default-off M1b extension."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


_TESTS = Path(__file__).resolve().parent
_ROOT = _TESTS.parent
sys.path[:0] = [os.fspath(_TESTS), os.fspath(_ROOT)]

from test_workspace_registry import (  # noqa: E402
    _control_store,
    _create_memory_database,
    _create_mission_database,
)

from core.workspaces import (  # noqa: E402
    BackfillConflict,
    BackfillSourceError,
    LegacyContextBackfill,
    LegacySnapshotReader,
    LegacyWorkspaceAdapter,
    WorkspaceRegistry,
    _HOST_MARKER,
    _host_owned_source_paths,
)
from core.control_plane import (  # noqa: E402
    ControlPlanePathError,
    _secure_private_directory,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path):
    _secure_private_directory(root)
    mission = _create_mission_database(root / "onyx_missions.sqlite3")
    memory = _create_memory_database(root / "onyx_memory.sqlite3")
    (root / "long_term.json").write_text('{"owner":"preserved"}', encoding="utf-8")
    store = _control_store(root / "runtime" / "control_plane.sqlite3")
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    adapter = LegacyWorkspaceAdapter(registry, _HOST_MARKER)
    with patch("core.workspaces.memory_dir", return_value=root):
        paths = _host_owned_source_paths(_HOST_MARKER)
    reader = LegacySnapshotReader(paths, _HOST_MARKER)
    backfill = LegacyContextBackfill(registry, adapter, reader, enabled=True)
    return mission, memory, store, registry, reader, backfill


def _close_quietly(connection: sqlite3.Connection) -> None:
    try:
        connection.close()
    except sqlite3.Error:
        pass


def _checkpoint_and_close(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()


class LegacyMemoryContractAuditTests(unittest.TestCase):
    def _expect_memory_rejection(self, mutation, message: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, _registry, reader, _backfill = _fixture(root)
            try:
                mutation(memory, root / "onyx_memory.sqlite3")
                _checkpoint_and_close(memory)
                with self.assertRaisesRegex(BackfillSourceError, message):
                    with reader.capture(store.path.parent / "audit-snapshot"):
                        self.fail("invalid memory source was accepted")
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_invalid_memory_kind_is_rejected_even_with_valid_deterministic_id(self):
        def mutate(connection: sqlite3.Connection, _path: Path) -> None:
            row = connection.execute(
                "SELECT id,source,content_hash FROM memories ORDER BY id LIMIT 1"
            ).fetchone()
            forged_kind = "forged"
            forged_id = "mem_" + hashlib.sha256(
                f"{forged_kind}\0{row[1]}\0{row[2]}".encode()
            ).hexdigest()[:24]
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "UPDATE memories SET id=?,kind=? WHERE id=?",
                (forged_id, forged_kind, row[0]),
            )
            connection.commit()

        self._expect_memory_rejection(mutate, "kind")

    def test_invalid_memory_salience_is_rejected_when_check_is_bypassed(self):
        def mutate(connection: sqlite3.Connection, _path: Path) -> None:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE memories SET salience=2.0")
            connection.commit()

        self._expect_memory_rejection(mutate, "salience")

    def test_memory_check_ddl_bypass_is_rejected_with_unchanged_columns(self):
        def mutate(connection: sqlite3.Connection, _path: Path) -> None:
            schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
            connection.execute("PRAGMA writable_schema=ON")
            changed = connection.execute(
                "UPDATE sqlite_master SET sql=replace(replace(sql,?,''),?,'') "
                "WHERE type='table' AND name='memories'",
                (
                    "CHECK(kind IN ('semantic','episodic'))",
                    "CHECK(salience >= 0 AND salience <= 1)",
                ),
            ).rowcount
            self.assertEqual(changed, 1)
            connection.execute(f"PRAGMA schema_version={schema_version + 1}")
            connection.commit()

        self._expect_memory_rejection(mutate, "CHECK|semantic schema")

    def test_physically_corrupt_memory_database_is_rejected_without_further_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, _registry, reader, _backfill = _fixture(root)
            path = root / "onyx_memory.sqlite3"
            try:
                _checkpoint_and_close(memory)
                data = bytearray(path.read_bytes())
                data[:16] = b"not sqlite audit!"
                path.write_bytes(data)
                corrupt_hash = _sha(path)
                with self.assertRaises(BackfillSourceError):
                    with reader.capture(store.path.parent / "corrupt-snapshot"):
                        self.fail("physically corrupt memory database was accepted")
                self.assertEqual(_sha(path), corrupt_hash)
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_orphan_mission_foreign_key_is_rejected_without_reader_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, _registry, reader, _backfill = _fixture(root)
            path = root / "onyx_missions.sqlite3"
            try:
                mission.execute("PRAGMA foreign_keys=OFF")
                mission.execute(
                    "INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "orphan-step",
                        "missing-mission",
                        99,
                        "system_snapshot",
                        "{}",
                        "pending",
                        0,
                        "orphan-idempotency",
                        None,
                        None,
                        None,
                        None,
                        None,
                    ),
                )
                mission.commit()
                _checkpoint_and_close(mission)
                before = _sha(path)
                with self.assertRaisesRegex(BackfillSourceError, "orphan|foreign"):
                    with reader.capture(store.path.parent / "fk-snapshot"):
                        self.fail("orphan mission relation was accepted")
                self.assertEqual(_sha(path), before)
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)


class VerifiedReplayAuditTests(unittest.TestCase):
    def test_every_auditable_candidate_field_is_covered_by_verified_replay(self):
        mutations = {
            "source_identity": ("source_identity=?", ("forged-source-identity",)),
            "source_schema_version": ("source_schema_version=?", (999,)),
            "run_id": ("run_id=?", ("missing-run",)),
            "created_at": ("created_at=?", ("2099-01-01T00:00:00+00:00",)),
            "updated_at": ("updated_at=?", ("2099-01-01T00:00:00+00:00",)),
            "status": ("status=?", ("rejected",)),
            "reason": ("reason=?", ("forged-reason",)),
            "workspace_id": ("workspace_id=?", ("legacy-default",)),
            "logical_hash": ("logical_hash=?", ("f" * 64,)),
        }
        for label, (assignment, parameters) in mutations.items():
            with self.subTest(field=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                mission, memory, store, _registry, _reader, backfill = _fixture(root)
                try:
                    result = backfill.run()
                    external = sqlite3.connect(store.path)
                    try:
                        external.execute("PRAGMA foreign_keys=OFF")
                        target_filter = (
                            "WHERE workspace_id IS NULL "
                            if label == "workspace_id"
                            else ""
                        )
                        external.execute(
                            f"UPDATE legacy_backfill_candidates SET {assignment} "
                            "WHERE candidate_id=(SELECT candidate_id FROM "
                            f"legacy_backfill_candidates {target_filter}"
                            "ORDER BY candidate_id LIMIT 1)",
                            parameters,
                        )
                        external.commit()
                    finally:
                        external.close()
                    with self.assertRaisesRegex(BackfillConflict, "read-back|readback|integrity|foreign"):
                        backfill.run()
                    self.assertEqual(
                        store._require_connection().execute(
                            "SELECT status FROM backfill_runs WHERE run_id=?", (result.run_id,)
                        ).fetchone()[0],
                        "verified",
                    )
                finally:
                    store.close()
                    _close_quietly(mission)
                    _close_quietly(memory)


class BackfillRunRowTamperAuditTests(unittest.TestCase):
    def test_every_verified_run_field_and_payload_invariant_is_revalidated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            try:
                result = backfill.run()
                connection = registry._connection()
                columns = [
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info('backfill_runs')")
                ]
                baseline_row = connection.execute(
                    "SELECT * FROM backfill_runs WHERE run_id=?", (result.run_id,)
                ).fetchone()
                baseline = dict(zip(columns, baseline_row, strict=True))
                payload = json.loads(str(baseline["payload_json"]))

                def changed_payload(**updates: object) -> str:
                    forged = json.loads(json.dumps(payload))
                    forged["result"].update(updates)
                    return json.dumps(forged, sort_keys=True, separators=(",", ":"))

                mutations = {
                    "schema_version": int(baseline["schema_version"]) + 1,
                    "status": "failed",
                    "mission_source_identity": str(baseline["mission_source_identity"]) + ".forged",
                    "mission_source_hash": "f" * 64,
                    "memory_source_identity": str(baseline["memory_source_identity"]) + ".forged",
                    "memory_source_hash": "e" * 64,
                    "started_at": "2099-01-01T00:00:00+00:00",
                    "completed_at": "2099-01-01T00:00:01+00:00",
                    "readback_hash": "d" * 64,
                    "lease_owner": "m1b-owner-forged-final",
                    "lease_expires_at": "2099-01-01T00:00:00+00:00",
                    "heartbeat_at": "2099-01-01T00:00:00+00:00",
                    "lease_epoch": int(baseline["lease_epoch"]) + 1,
                    "payload_run_id": changed_payload(run_id="m1b-backfill-forged"),
                    "payload_status": changed_payload(status="failed"),
                    "payload_mission_scanned": changed_payload(
                        mission_scanned=int(payload["result"]["mission_scanned"]) + 1
                    ),
                    "payload_mission_assigned": changed_payload(
                        mission_assigned=int(payload["result"]["mission_assigned"]) + 1
                    ),
                    "payload_mission_pending": changed_payload(
                        mission_pending=int(payload["result"]["mission_pending"]) + 1
                    ),
                    "payload_memory_scanned": changed_payload(
                        memory_scanned=int(payload["result"]["memory_scanned"]) + 1
                    ),
                    "payload_memory_assigned": changed_payload(memory_assigned=1),
                    "payload_memory_pending": changed_payload(
                        memory_pending=int(payload["result"]["memory_pending"]) + 1
                    ),
                    "payload_candidate_count": changed_payload(
                        candidate_read_back=int(payload["result"]["candidate_read_back"]) + 1
                    ),
                    "payload_context_count": changed_payload(
                        context_read_back=int(payload["result"]["context_read_back"]) + 1
                    ),
                    "payload_readback_hash": changed_payload(readback_hash="c" * 64),
                    "payload_replay_flag": changed_payload(idempotent_replay=True),
                    "payload_unknown_adapter_version": json.dumps(
                        {**payload, "adapter_version": 999},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }

                for label, forged_value in mutations.items():
                    column = "payload_json" if label.startswith("payload_") else label
                    with self.subTest(field=label):
                        self.assertNotEqual(forged_value, baseline[column])
                        connection.execute(
                            f'UPDATE backfill_runs SET "{column}"=? WHERE run_id=?',
                            (forged_value, result.run_id),
                        )
                        try:
                            with self.assertRaises(BackfillConflict):
                                backfill.run()
                        finally:
                            connection.execute(
                                f'UPDATE backfill_runs SET "{column}"=? WHERE run_id=?',
                                (baseline[column], result.run_id),
                            )
                self.assertEqual(
                    connection.execute(
                        "SELECT * FROM backfill_runs WHERE run_id=?", (result.run_id,)
                    ).fetchone(),
                    baseline_row,
                )
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_verified_run_id_tamper_is_rejected_with_foreign_keys_remaining_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            try:
                result = backfill.run()
                connection = registry._connection()
                columns = [
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info('backfill_runs')")
                ]
                original_row = connection.execute(
                    "SELECT * FROM backfill_runs WHERE run_id=?", (result.run_id,)
                ).fetchone()
                forged_id = result.run_id + "-forged"
                forged_row = list(original_row)
                forged_row[columns.index("run_id")] = forged_id
                contexts = connection.execute(
                    "SELECT mission_id,payload_json FROM mission_contexts "
                    "WHERE json_extract(payload_json,'$.run_id')=?",
                    (result.run_id,),
                ).fetchall()
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    f"INSERT INTO backfill_runs VALUES({','.join('?' for _ in columns)})",
                    forged_row,
                )
                connection.execute(
                    "UPDATE legacy_backfill_candidates SET run_id=? WHERE run_id=?",
                    (forged_id, result.run_id),
                )
                for mission_id, payload_text in contexts:
                    context_payload = json.loads(str(payload_text))
                    context_payload["run_id"] = forged_id
                    connection.execute(
                        "UPDATE mission_contexts SET payload_json=? WHERE mission_id=?",
                        (
                            json.dumps(
                                context_payload, sort_keys=True, separators=(",", ":")
                            ),
                            mission_id,
                        ),
                    )
                connection.execute("DELETE FROM backfill_runs WHERE run_id=?", (result.run_id,))
                connection.execute("COMMIT")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

                with self.assertRaises(BackfillConflict):
                    backfill.run()

                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM backfill_runs WHERE run_id=?", (result.run_id,))
                connection.execute(
                    f"INSERT INTO backfill_runs VALUES({','.join('?' for _ in columns)})",
                    original_row,
                )
                connection.execute(
                    "UPDATE legacy_backfill_candidates SET run_id=? WHERE run_id=?",
                    (result.run_id, forged_id),
                )
                for mission_id, payload_text in contexts:
                    connection.execute(
                        "UPDATE mission_contexts SET payload_json=? WHERE mission_id=?",
                        (payload_text, mission_id),
                    )
                connection.execute("DELETE FROM backfill_runs WHERE run_id=?", (forged_id,))
                connection.execute("COMMIT")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)


class IncompleteRunRecoveryAuditTests(unittest.TestCase):
    def test_stale_started_run_without_rows_is_safely_taken_over_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            try:
                result = backfill.run()
                connection = registry._connection()
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM mission_contexts")
                connection.execute("DELETE FROM legacy_backfill_candidates")
                connection.execute(
                    "UPDATE backfill_runs SET status='started',started_at=?,completed_at=NULL,"
                    "readback_hash=NULL,payload_json=?,lease_expires_at=?,heartbeat_at=? "
                    "WHERE run_id=?",
                    (
                        "2000-01-01T00:00:00+00:00",
                        '{"manifest":[]}',
                        "2000-01-01T00:00:00+00:00",
                        "2000-01-01T00:00:00+00:00",
                        result.run_id,
                    ),
                )
                connection.execute("COMMIT")
                with patch("core.workspaces.time.sleep", return_value=None):
                    recovered = backfill.run()
                self.assertEqual(recovered.status, "verified")
                self.assertEqual(recovered.run_id, result.run_id)
                self.assertEqual(
                    connection.execute(
                        "SELECT status FROM backfill_runs WHERE run_id=?", (result.run_id,)
                    ).fetchone()[0],
                    "verified",
                )
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_stale_applied_unverified_run_with_valid_readback_recovers_to_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            try:
                first = backfill.run()
                connection = registry._connection()
                stale = "2000-01-01T00:00:00+00:00"
                connection.execute(
                    "UPDATE legacy_backfill_candidates SET created_at=?,updated_at=? "
                    "WHERE run_id=?",
                    (stale, stale, first.run_id),
                )
                connection.execute(
                    "UPDATE mission_contexts SET created_at=?,updated_at=? "
                    "WHERE json_extract(payload_json,'$.run_id')=?",
                    (stale, stale, first.run_id),
                )
                connection.execute(
                    "UPDATE backfill_runs SET status='applied_unverified',started_at=?,"
                    "completed_at=?,lease_expires_at=?,heartbeat_at=? WHERE run_id=?",
                    (
                        stale,
                        "2000-01-01T00:00:01+00:00",
                        stale,
                        stale,
                        first.run_id,
                    ),
                )
                with patch("core.workspaces.time.sleep", return_value=None):
                    recovered = backfill.run()
                self.assertEqual(recovered.status, "verified")
                self.assertEqual(recovered.run_id, first.run_id)
                self.assertEqual(
                    connection.execute(
                        "SELECT status FROM backfill_runs WHERE run_id=?", (first.run_id,)
                    ).fetchone()[0],
                    "verified",
                )
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_active_concurrent_run_waits_and_accepts_only_verified_terminal_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            try:
                first = backfill.run()
                connection = registry._connection()
                run_columns = [
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info('backfill_runs')")
                ]
                canonical_run = connection.execute(
                    "SELECT * FROM backfill_runs WHERE run_id=?", (first.run_id,)
                ).fetchone()
                self.assertIsNotNone(canonical_run)
                self.assertEqual(json.loads(str(canonical_run[10]))["result"]["status"], "verified")
                connection.execute(
                    "UPDATE backfill_runs SET status='started',started_at=?,lease_expires_at=?,"
                    "heartbeat_at=? WHERE run_id=?",
                    (
                        "2099-01-01T00:00:00+00:00",
                        "2099-01-01T00:00:00+00:00",
                        "2099-01-01T00:00:00+00:00",
                        first.run_id,
                    ),
                )
                calls = 0

                def complete_after_wait(_delay: float) -> None:
                    nonlocal calls
                    calls += 1
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        changed = connection.execute(
                            "UPDATE backfill_runs SET "
                            + ",".join(f'"{column}"=?' for column in run_columns)
                            + " WHERE run_id=?",
                            (*canonical_run, first.run_id),
                        ).rowcount
                        self.assertEqual(changed, 1)
                        connection.execute("COMMIT")
                    except Exception:
                        if connection.in_transaction:
                            connection.execute("ROLLBACK")
                        raise

                with patch("core.workspaces.time.sleep", side_effect=complete_after_wait):
                    replay = backfill.run()
                self.assertGreaterEqual(calls, 1)
                self.assertTrue(replay.idempotent_replay)
                self.assertEqual(replay.run_id, first.run_id)
                self.assertEqual(
                    connection.execute(
                        "SELECT * FROM backfill_runs WHERE run_id=?", (first.run_id,)
                    ).fetchone(),
                    canonical_run,
                )
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)


class BackfillLeaseFencingAuditTests(unittest.TestCase):
    def test_operation_longer_than_ttl_keeps_lease_by_heartbeat_and_is_not_taken_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, reader, first = _fixture(root)
            second_store = _control_store(store.path)
            second_registry = WorkspaceRegistry(second_store, enabled=True).initialize()
            second = LegacyContextBackfill(
                second_registry,
                LegacyWorkspaceAdapter(second_registry, _HOST_MARKER),
                LegacySnapshotReader(reader.paths, _HOST_MARKER),
                enabled=True,
            )
            entered = threading.Event()
            release = threading.Event()

            def long_readback() -> None:
                entered.set()
                self.assertTrue(release.wait(15.0))

            try:
                with patch("core.workspaces.BACKFILL_LEASE_SECONDS", 0.25), patch(
                    "core.workspaces.BACKFILL_HEARTBEAT_SECONDS", 0.05
                ), patch.object(first, "_before_readback", side_effect=long_readback):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        first_future = executor.submit(first.run)
                        self.assertTrue(entered.wait(15.0))
                        initial = registry._connection().execute(
                            "SELECT run_id,lease_owner,lease_epoch FROM backfill_runs"
                        ).fetchone()
                        time.sleep(0.45)
                        second_future = executor.submit(second.run)
                        time.sleep(0.1)
                        release.set()
                        results = (first_future.result(), second_future.result())
                final = registry._connection().execute(
                    "SELECT lease_owner,lease_epoch,status FROM backfill_runs WHERE run_id=?",
                    (initial[0],),
                ).fetchone()
                self.assertEqual(final, (initial[1], initial[2], "verified"))
                self.assertEqual({result.run_id for result in results}, {initial[0]})
                self.assertEqual(sorted(result.idempotent_replay for result in results), [False, True])
            finally:
                release.set()
                second_store.close()
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_expired_worker_is_fenced_after_takeover_increments_epoch_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, reader, first = _fixture(root)
            second_store = _control_store(store.path)
            second_registry = WorkspaceRegistry(second_store, enabled=True).initialize()
            second = LegacyContextBackfill(
                second_registry,
                LegacyWorkspaceAdapter(second_registry, _HOST_MARKER),
                LegacySnapshotReader(reader.paths, _HOST_MARKER),
                enabled=True,
            )
            owner_a = "m1b-owner-worker-a"
            try:
                original = first.run()
                connection = registry._connection()
                connection.execute(
                    "UPDATE backfill_runs SET status='applied_unverified',lease_owner=?,"
                    "lease_expires_at=?,heartbeat_at=?,lease_epoch=1 WHERE run_id=?",
                    (
                        owner_a,
                        "2000-01-01T00:00:00+00:00",
                        "2000-01-01T00:00:00+00:00",
                        original.run_id,
                    ),
                )
                with patch("core.workspaces.BACKFILL_LEASE_SECONDS", 0.25), patch(
                    "core.workspaces.BACKFILL_HEARTBEAT_SECONDS", 0.05
                ):
                    recovered = second.run()
                owner_b, epoch_b, status = connection.execute(
                    "SELECT lease_owner,lease_epoch,status FROM backfill_runs WHERE run_id=?",
                    (original.run_id,),
                ).fetchone()
                self.assertEqual(recovered.status, "verified")
                self.assertNotEqual(owner_b, owner_a)
                self.assertEqual(epoch_b, 2)
                self.assertEqual(status, "verified")

                first._record_failed(original.run_id, owner_a, 1, "late worker A")
                changed = connection.execute(
                    "UPDATE backfill_runs SET status='failed' WHERE run_id=? "
                    "AND lease_owner=? AND lease_epoch=? AND status!='verified'",
                    (original.run_id, owner_a, 1),
                ).rowcount
                self.assertEqual(changed, 0)
                self.assertEqual(
                    connection.execute(
                        "SELECT lease_owner,lease_epoch,status FROM backfill_runs WHERE run_id=?",
                        (original.run_id,),
                    ).fetchone(),
                    (owner_b, 2, "verified"),
                )
            finally:
                second_store.close()
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_owner_or_epoch_divergence_cannot_mark_applied_run_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, reader, backfill = _fixture(root)
            try:
                original = backfill.run()
                connection = registry._connection()
                started = connection.execute(
                    "SELECT started_at FROM backfill_runs WHERE run_id=?", (original.run_id,)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE backfill_runs SET status='applied_unverified',lease_owner=?,"
                    "lease_epoch=7,lease_expires_at=?,heartbeat_at=? WHERE run_id=?",
                    (
                        "m1b-owner-current",
                        "2099-01-01T00:00:00+00:00",
                        "2099-01-01T00:00:00+00:00",
                        original.run_id,
                    ),
                )
                workspace = LegacyWorkspaceAdapter(registry, _HOST_MARKER).resolve()
                with reader.capture(store.path.parent / "lease-fence-snapshot") as snapshot:
                    with patch("core.workspaces.BACKFILL_HEARTBEAT_SECONDS", 0.05):
                        with self.assertRaises(BackfillConflict):
                            backfill._recover_stale_applied(
                                original.run_id,
                                snapshot,
                                workspace,
                                started,
                                "m1b-owner-stale",
                                6,
                            )
                self.assertEqual(
                    connection.execute(
                        "SELECT status,lease_owner,lease_epoch FROM backfill_runs WHERE run_id=?",
                        (original.run_id,),
                    ).fetchone(),
                    ("applied_unverified", "m1b-owner-current", 7),
                )
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)


class UnsafeLegacySourceAuditTests(unittest.TestCase):
    def _assert_no_source_mutation(self, root: Path, before: dict[str, str]) -> None:
        after = {
            name: _sha(root / name)
            for name in before
            if (root / name).is_file() and not (root / name).is_symlink()
        }
        self.assertEqual(after, {name: value for name, value in before.items() if name in after})

    def test_broken_symlink_and_existing_symlink_or_reparse_are_rejected(self):
        for broken in (True, False):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                mission, memory, store, registry, _reader, backfill = _fixture(root)
                source = root / "onyx_missions.sqlite3"
                target = root / "mission-target.sqlite3"
                try:
                    _checkpoint_and_close(mission)
                    source.replace(target)
                    link_target = "missing.sqlite3" if broken else target.name
                    try:
                        source.symlink_to(link_target)
                    except OSError as exc:
                        self.skipTest(f"symlink/reparse creation unavailable: {exc}")
                    target_hash = _sha(target)
                    with self.assertRaises(BackfillSourceError):
                        backfill.run()
                    self.assertEqual(_sha(target), target_hash)
                    self.assertEqual(
                        registry._connection().execute(
                            "SELECT count(*) FROM backfill_runs"
                        ).fetchone()[0],
                        0,
                    )
                finally:
                    store.close()
                    _close_quietly(mission)
                    _close_quietly(memory)

    def test_directory_in_place_of_database_is_rejected_without_mutating_other_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            source = root / "onyx_memory.sqlite3"
            protected = {
                "onyx_missions.sqlite3": _sha(root / "onyx_missions.sqlite3"),
                "long_term.json": _sha(root / "long_term.json"),
            }
            try:
                _checkpoint_and_close(memory)
                source.unlink()
                source.mkdir()
                with self.assertRaises(BackfillSourceError):
                    backfill.run()
                self._assert_no_source_mutation(root, protected)
                self.assertEqual(
                    registry._connection().execute(
                        "SELECT count(*) FROM backfill_runs"
                    ).fetchone()[0],
                    0,
                )
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_fifo_source_is_rejected_without_reading_or_mutating_it(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable on this platform")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            source = root / "onyx_memory.sqlite3"
            try:
                _checkpoint_and_close(memory)
                source.unlink()
                os.mkfifo(source, 0o600)
                with self.assertRaisesRegex(BackfillSourceError, "regular"):
                    backfill.run()
                self.assertTrue(stat.S_ISFIFO(source.lstat().st_mode))
                self.assertEqual(
                    registry._connection().execute(
                        "SELECT count(*) FROM backfill_runs"
                    ).fetchone()[0],
                    0,
                )
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_broad_writable_source_is_rejected_before_snapshot_or_sidecar_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            source = root / "onyx_memory.sqlite3"
            try:
                _checkpoint_and_close(memory)
                before = _sha(source)
                if os.name == "nt":
                    from core.control_plane import (
                        _apply_windows_security_sddl,
                        _current_windows_sid,
                    )

                    current = _current_windows_sid()
                    _apply_windows_security_sddl(
                        source,
                        f"O:{current}D:P"
                        f"(A;;FA;;;SY)(A;;FA;;;{current})(A;;FA;;;WD)",
                    )
                else:
                    source.chmod(0o666)
                with self.assertRaisesRegex(BackfillSourceError, "permission|writable|untrusted|ACL"):
                    backfill.run()
                self.assertEqual(_sha(source), before)
                self.assertEqual(
                    registry._connection().execute(
                        "SELECT count(*) FROM backfill_runs"
                    ).fetchone()[0],
                    0,
                )
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)

    def test_untrusted_source_owner_is_rejected_without_confusing_snapshot_owner(self):
        if os.name != "nt":
            self.skipTest("Windows owner simulation; POSIX requires privileged chown")
        from core.workspaces import _verify_windows_private_ancestor as real_verify

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            source = root / "onyx_memory.sqlite3"
            before = _sha(source)

            def verify(candidate: Path) -> None:
                if Path(candidate) == source:
                    raise ControlPlanePathError("untrusted owner audit sentinel")
                real_verify(Path(candidate))

            try:
                with patch(
                    "core.workspaces._verify_windows_private_ancestor",
                    side_effect=verify,
                ):
                    with self.assertRaisesRegex(BackfillSourceError, "owner|untrusted"):
                        backfill.run()
                self.assertEqual(_sha(source), before)
                self.assertEqual(
                    registry._connection().execute(
                        "SELECT count(*) FROM backfill_runs"
                    ).fetchone()[0],
                    0,
                )
            finally:
                store.close()
                _close_quietly(mission)
                _close_quietly(memory)


if __name__ == "__main__":
    unittest.main()
