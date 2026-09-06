from __future__ import annotations

import copy
import hashlib
import multiprocessing
import os
import pickle
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from core.control_plane import (
    APPLICATION_ID,
    MIGRATION_ID,
    M1A_SCHEMA_STATEMENTS,
    M1A_SCHEMA_VERSION,
    ControlPlaneSchemaError,
    ControlPlaneStore,
    _reference_manifest,
    _schema_fingerprint,
)
from core.workspaces import (
    LEGACY_WORKSPACE_ID,
    BackfillConflict,
    BackfillDisabled,
    BackfillSourceError,
    LegacyContextBackfill,
    LegacyMarkerError,
    LegacySnapshotReader,
    LegacyWorkspaceAdapter,
    WorkspaceExtensionDisabled,
    WorkspaceIdentityError,
    WorkspaceInactive,
    WorkspaceIsolationError,
    WorkspacePendingReview,
    WorkspaceRegistry,
    WorkspaceUnknown,
    _HOST_MARKER,
    _LegacyHostMarker,
    _host_owned_source_paths,
)


def _control_store(path: Path, *, enabled: bool = True) -> ControlPlaneStore:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir", return_value=path.parent
    ):
        return ControlPlaneStore(enabled=enabled)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _process_backfill(sidecar_text: str, source_root_text: str, results: object) -> None:
    store = None
    try:
        store = _control_store(Path(sidecar_text))
        registry = WorkspaceRegistry(store, enabled=True).initialize()
        adapter = LegacyWorkspaceAdapter(registry, _HOST_MARKER)
        with patch("core.workspaces.memory_dir", return_value=Path(source_root_text)):
            paths = _host_owned_source_paths(_HOST_MARKER)
        reader = LegacySnapshotReader(paths, _HOST_MARKER)
        result = LegacyContextBackfill(
            registry, adapter, reader, enabled=True
        ).run()
        results.put(("ok", result.run_id, result.status, result.idempotent_replay))
    except BaseException as exc:
        results.put(("error", type(exc).__name__, str(exc), False))
        raise
    finally:
        if store is not None:
            store.close()


def _mission_event(
    connection: sqlite3.Connection,
    mission_id: str,
    timestamp: float,
    event: str,
    detail: str,
) -> None:
    previous = connection.execute(
        "SELECT event_hash FROM events WHERE mission_id=? ORDER BY seq DESC LIMIT 1",
        (mission_id,),
    ).fetchone()
    prior = str(previous[0]) if previous else ""
    digest = hashlib.sha256(
        f"{mission_id}\0{timestamp:.9f}\0{event}\0{detail}\0{prior}".encode()
    ).hexdigest()
    connection.execute(
        "INSERT INTO events(mission_id,timestamp,event,detail,prev_hash,event_hash) "
        "VALUES(?,?,?,?,?,?)",
        (mission_id, timestamp, event, detail, prior, digest),
    )


def _create_mission_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE schema_meta(version INTEGER NOT NULL);
        CREATE TABLE missions(
          id TEXT PRIMARY KEY,title TEXT NOT NULL,state TEXT NOT NULL,
          created_at REAL NOT NULL,updated_at REAL NOT NULL,max_steps INTEGER NOT NULL,
          max_seconds REAL NOT NULL,max_retries INTEGER NOT NULL,
          provider_cost_limit REAL NOT NULL,tool_allowlist TEXT NOT NULL,
          current_step INTEGER NOT NULL DEFAULT 0,error TEXT,deadline REAL,
          approval_digest TEXT,lease_owner TEXT,lease_expires REAL,lease_heartbeat REAL
        );
        CREATE TABLE steps(
          id TEXT PRIMARY KEY,mission_id TEXT NOT NULL REFERENCES missions(id),
          position INTEGER NOT NULL,tool TEXT NOT NULL,args TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
          idempotency_key TEXT NOT NULL UNIQUE,result TEXT,error TEXT,wait_reason TEXT,
          started_at REAL,completed_at REAL,UNIQUE(mission_id,position)
        );
        CREATE TABLE events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,mission_id TEXT NOT NULL,
          timestamp REAL NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL,
          prev_hash TEXT NOT NULL DEFAULT '',event_hash TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX events_mission ON events(mission_id,seq);
        CREATE TRIGGER events_no_update BEFORE UPDATE ON events
          BEGIN SELECT RAISE(ABORT,'mission events are immutable'); END;
        CREATE TRIGGER events_no_delete BEFORE DELETE ON events
          BEGIN SELECT RAISE(ABORT,'mission events are immutable'); END;
        """
    )
    connection.execute("INSERT INTO schema_meta VALUES(3)")
    rows = (
        (
            "mis_complete",
            "Complete",
            "succeeded",
            1.0,
            2.0,
            1,
            30.0,
            0,
            0.0,
            "[]",
            1,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        (
            "mis_running",
            "Running",
            "running",
            3.0,
            4.0,
            1,
            30.0,
            0,
            0.0,
            "[]",
            0,
            None,
            100.0,
            "digest",
            "worker-1",
            50.0,
            4.0,
        ),
    )
    connection.executemany(
        "INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    for index, mission_id in enumerate(("mis_complete", "mis_running"), 1):
        connection.execute(
            "INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"step_{index}",
                mission_id,
                0,
                "system_snapshot",
                "{}",
                "succeeded" if index == 1 else "pending",
                1 if index == 1 else 0,
                f"idem-{index}",
                "{}" if index == 1 else None,
                None,
                None,
                1.0,
                2.0 if index == 1 else None,
            ),
        )
        _mission_event(connection, mission_id, float(index), "mission.created", "{}")
    connection.commit()
    return connection


def _create_memory_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE memories(
          id TEXT PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ('semantic','episodic')),
          content TEXT NOT NULL,source TEXT NOT NULL,citation TEXT NOT NULL,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
          salience REAL NOT NULL CHECK(salience >= 0 AND salience <= 1),
          session_id TEXT,task_id TEXT,category TEXT,memory_key TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',content_hash TEXT NOT NULL,
          access_count INTEGER NOT NULL DEFAULT 0,last_accessed_at TEXT
        );
        CREATE UNIQUE INDEX idx_memories_dedupe ON memories(kind,source,content_hash);
        CREATE INDEX idx_memories_updated ON memories(updated_at DESC,id);
        CREATE INDEX idx_memories_category_key ON memories(category,memory_key);
        CREATE TABLE memory_audit(
          id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,
          action TEXT NOT NULL,memory_id TEXT,detail TEXT NOT NULL
        );
        """
    )
    connection.execute("INSERT INTO schema_meta VALUES('schema_version','1')")
    for index, content in enumerate(("Owner prefers concise updates", "Cyryx note"), 1):
        kind = "semantic"
        source = "user"
        category = "preference" if index == 1 else None
        memory_key = f"key-{index}" if index == 1 else None
        identity = f"{content.casefold()}\0{category or ''}\0{memory_key or ''}"
        content_hash = hashlib.sha256(identity.encode()).hexdigest()
        memory_id = "mem_" + hashlib.sha256(
            f"{kind}\0{source}\0{content_hash}".encode()
        ).hexdigest()[:24]
        connection.execute(
            "INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                memory_id,
                kind,
                content,
                source,
                "owner",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                0.8,
                "session-a",
                "mis_complete",
                category,
                memory_key,
                '{ "reviewed" : true }',
                content_hash,
                index * 10,
                "2026-01-02T00:00:00+00:00",
            ),
        )
    connection.commit()
    return connection


class WorkspaceRegistryM1bTests(unittest.TestCase):
    def _fixture(self, root: Path):
        mission = _create_mission_database(root / "onyx_missions.sqlite3")
        memory = _create_memory_database(root / "onyx_memory.sqlite3")
        (root / "long_term.json").write_text('{"owner":"preserved"}', encoding="utf-8")
        sidecar = root / "runtime" / "control_plane.sqlite3"
        store = _control_store(sidecar)
        registry = WorkspaceRegistry(store, enabled=True).initialize()
        adapter = LegacyWorkspaceAdapter(registry, _HOST_MARKER)
        with patch("core.workspaces.memory_dir", return_value=root):
            paths = _host_owned_source_paths(_HOST_MARKER)
        reader = LegacySnapshotReader(paths, _HOST_MARKER)
        backfill = LegacyContextBackfill(registry, adapter, reader, enabled=True)
        return mission, memory, store, registry, adapter, reader, backfill

    def test_flags_off_and_workspace_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / "runtime" / "control_plane.sqlite3"
            store = _control_store(path)
            registry = WorkspaceRegistry(store)
            with self.assertRaises(WorkspaceExtensionDisabled):
                registry.initialize()
            self.assertFalse(path.exists())

        with tempfile.TemporaryDirectory() as tmp:
            store = _control_store(Path(tmp) / "runtime" / "control_plane.sqlite3")
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            try:
                registry.register(
                    "client-alpha",
                    display_name="Client Alpha",
                    workspace_class="client",
                )
                registry.register(
                    "client-beta",
                    display_name="Client Beta",
                    workspace_class="client",
                    active=False,
                )
                registry.register(
                    "client-gamma",
                    display_name="Client Gamma",
                    workspace_class="client",
                )
                for invalid in (None, "", "UPPER", "../escape", 1, {"workspace_id": "client-alpha"}):
                    with self.subTest(invalid=invalid), self.assertRaises(WorkspaceIdentityError):
                        registry.require_active(invalid)
                with self.assertRaises(WorkspaceUnknown):
                    registry.require_active("unknown-space")
                with self.assertRaises(WorkspaceInactive):
                    registry.require_active("client-beta")
                with self.assertRaises(LegacyMarkerError):
                    registry.get(LEGACY_WORKSPACE_ID)
                connection = registry._connection()
                connection.execute(
                    "INSERT INTO mission_contexts VALUES(?,?,?,?,?,?,?)",
                    (
                        "mis_scoped",
                        "client-alpha",
                        1,
                        "LEGACY_BACKFILLED",
                        '{"run_id":"missing-run"}',
                        "now",
                        "now",
                    ),
                )
                connection.execute(
                    "INSERT INTO memory_metadata VALUES(?,?,?,?,?,?,?,?)",
                    (
                        "memory-meta-scoped",
                        "client-alpha",
                        "mem_scoped",
                        1,
                        "active",
                        '{"run_id":"missing-run"}',
                        "now",
                        "now",
                    ),
                )
                connection.commit()
                with self.assertRaises(WorkspaceIsolationError):
                    registry.mission_reference("client-gamma", "mis_scoped")
                with self.assertRaises(WorkspacePendingReview):
                    registry.mission_reference("client-alpha", "mis_scoped")
                with self.assertRaises(WorkspacePendingReview):
                    registry.memory_reference("client-alpha", "mem_scoped")
            finally:
                store.close()

    def test_legacy_marker_is_identity_only_and_adapter_bound(self):
        for forgery in (object(), {}, "host", os.environ):
            with tempfile.TemporaryDirectory() as tmp:
                store = _control_store(Path(tmp) / "runtime" / "control_plane.sqlite3")
                registry = WorkspaceRegistry(store, enabled=True).initialize()
                try:
                    with self.assertRaises(LegacyMarkerError):
                        LegacyWorkspaceAdapter(registry, forgery)
                finally:
                    store.close()
        with self.assertRaises(TypeError):
            _LegacyHostMarker()
        for operation in (
            lambda: copy.copy(_HOST_MARKER),
            lambda: copy.deepcopy(_HOST_MARKER),
            lambda: pickle.dumps(_HOST_MARKER),
        ):
            with self.assertRaises(TypeError):
                operation()

    def test_backfill_is_verified_idempotent_pending_safe_and_byte_preserving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _adapter, _reader, backfill = self._fixture(root)
            protected = [
                path
                for path in root.iterdir()
                if path.name.startswith("onyx_") or path.name == "long_term.json"
            ]
            before = {path.name: _sha(path) for path in protected}
            try:
                result = backfill.run()
                self.assertEqual(result.status, "verified")
                self.assertEqual((result.mission_scanned, result.mission_assigned), (2, 1))
                self.assertEqual((result.mission_pending, result.memory_pending), (1, 2))
                self.assertEqual((result.candidate_read_back, result.context_read_back), (4, 1))
                replay = backfill.run()
                self.assertTrue(replay.idempotent_replay)
                connection = registry._connection()
                self.assertEqual(
                    connection.execute(
                        "SELECT status,count(*) FROM legacy_backfill_candidates "
                        "GROUP BY status ORDER BY status"
                    ).fetchall(),
                    [("assigned", 1), ("pending_review", 3)],
                )
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM memory_metadata").fetchone()[0], 0
                )
                with self.assertRaises(LegacyMarkerError):
                    registry.mission_reference(LEGACY_WORKSPACE_ID, "mis_complete")
                with self.assertRaises(WorkspaceUnknown):
                    registry.memory_reference("client-alpha", "mem_missing")
                after = {path.name: _sha(path) for path in protected}
                self.assertEqual(after, before)
            finally:
                store.close()
                mission.close()
                memory.close()

    def test_two_concurrent_backfills_converge_on_one_verified_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, adapter, reader, backfill = self._fixture(root)
            second_store = _control_store(store.path)
            second_registry = WorkspaceRegistry(second_store, enabled=True).initialize()
            second_adapter = LegacyWorkspaceAdapter(second_registry, _HOST_MARKER)
            second_reader = LegacySnapshotReader(reader.paths, _HOST_MARKER)
            second_backfill = LegacyContextBackfill(
                second_registry, second_adapter, second_reader, enabled=True
            )
            try:
                with patch.object(
                    backfill, "_before_source_recheck", side_effect=lambda: time.sleep(0.2)
                ):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        results = list(
                            executor.map(lambda operation: operation(), (backfill.run, second_backfill.run))
                        )
                self.assertEqual({result.status for result in results}, {"verified"})
                self.assertEqual(len({result.run_id for result in results}), 1)
                self.assertEqual(
                    sorted(result.idempotent_replay for result in results), [False, True]
                )
                connection = registry._connection()
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM backfill_runs").fetchone()[0], 1
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM legacy_backfill_candidates"
                    ).fetchone()[0],
                    4,
                )
            finally:
                second_store.close()
                store.close()
                mission.close()
                memory.close()

    def test_legacy_source_symlink_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _adapter, _reader, backfill = self._fixture(root)
            mission_path = root / "onyx_missions.sqlite3"
            target = root / "mission-source-target.sqlite3"
            try:
                mission.close()
                mission_path.replace(target)
                mission_path.symlink_to(target.name)
                before = _sha(target)
                with self.assertRaisesRegex(BackfillSourceError, "unsafe mission source path"):
                    backfill.run()
                self.assertEqual(_sha(target), before)
                self.assertEqual(
                    registry._connection().execute(
                        "SELECT count(*) FROM backfill_runs"
                    ).fetchone()[0],
                    0,
                )
            finally:
                store.close()
                mission.close()
                memory.close()

    def test_two_processes_converge_on_one_verified_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _adapter, _reader, _backfill = self._fixture(root)
            context = multiprocessing.get_context("spawn")
            results = context.Queue()
            processes = [
                context.Process(
                    target=_process_backfill,
                    args=(os.fspath(store.path), os.fspath(root), results),
                )
                for _index in range(2)
            ]
            try:
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(30)
                    self.assertEqual(process.exitcode, 0)
                observed = [results.get(timeout=5) for _process in processes]
                self.assertEqual({item[0] for item in observed}, {"ok"})
                self.assertEqual({item[2] for item in observed}, {"verified"})
                self.assertEqual(len({item[1] for item in observed}), 1)
                self.assertEqual(sorted(item[3] for item in observed), [False, True])
                connection = registry._connection()
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM backfill_runs").fetchone()[0], 1
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM legacy_backfill_candidates"
                    ).fetchone()[0],
                    4,
                )
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join(5)
                results.close()
                results.join_thread()
                store.close()
                mission.close()
                memory.close()

    def test_source_change_and_partial_failure_leave_no_candidate_rows(self):
        for mode in ("source", "partial"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                mission, memory, store, registry, _adapter, _reader, backfill = self._fixture(root)
                try:
                    if mode == "source":
                        def mutate_source() -> None:
                            (root / "long_term.json").write_text('{"changed":true}', encoding="utf-8")

                        hook = mutate_source
                        expected = BackfillSourceError
                    else:
                        def fail_partial() -> None:
                            raise BackfillConflict("injected partial failure")

                        hook = fail_partial
                        expected = BackfillConflict
                    with patch.object(backfill, "_before_source_recheck", side_effect=hook):
                        with self.assertRaises(expected):
                            backfill.run()
                    connection = registry._connection()
                    self.assertEqual(
                        connection.execute(
                            "SELECT count(*) FROM legacy_backfill_candidates"
                        ).fetchone()[0],
                        0,
                    )
                    self.assertEqual(
                        connection.execute("SELECT count(*) FROM mission_contexts").fetchone()[0],
                        0,
                    )
                    self.assertEqual(
                        connection.execute("SELECT status FROM backfill_runs").fetchone()[0],
                        "failed",
                    )
                finally:
                    store.close()
                    mission.close()
                    memory.close()

    def test_readback_divergence_marks_run_failed_and_blocks_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _adapter, _reader, backfill = self._fixture(root)

            def diverge() -> None:
                connection = sqlite3.connect(store.path)
                try:
                    connection.execute(
                        "DELETE FROM legacy_backfill_candidates WHERE candidate_id=("
                        "SELECT candidate_id FROM legacy_backfill_candidates LIMIT 1)"
                    )
                    connection.commit()
                finally:
                    connection.close()

            try:
                with patch.object(backfill, "_before_readback", side_effect=diverge):
                    with self.assertRaises(BackfillConflict):
                        backfill.run()
                self.assertEqual(
                    registry._connection().execute(
                        "SELECT status FROM backfill_runs"
                    ).fetchone()[0],
                    "failed",
                )
                with self.assertRaises(BackfillConflict):
                    backfill.run()
            finally:
                store.close()
                mission.close()
                memory.close()

    def test_backfill_flag_default_off(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            mission, memory, store, _registry, _adapter, _reader, _backfill = self._fixture(root)
            disabled = LegacyContextBackfill(_registry, _adapter, _reader)
            try:
                with self.assertRaises(BackfillDisabled):
                    disabled.run()
            finally:
                store.close()
                mission.close()
                memory.close()


class ControlPlaneMigrationV2Tests(unittest.TestCase):
    def _create_v1(self, path: Path, *, forged_workspace: bool = False) -> None:
        connection = sqlite3.connect(path)
        try:
            for statement in M1A_SCHEMA_STATEMENTS:
                connection.execute(statement)
            fingerprint = _schema_fingerprint(_reference_manifest(version=1))
            created = "2026-01-01T00:00:00+00:00"
            connection.executemany(
                "INSERT INTO schema_metadata VALUES(?,?)",
                (
                    ("schema_id", "onyx-control-plane"),
                    ("schema_version", "1"),
                    ("schema_fingerprint", fingerprint),
                    ("created_at", created),
                ),
            )
            connection.execute(
                "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
                (MIGRATION_ID, 0, M1A_SCHEMA_VERSION, "applied", created, fingerprint),
            )
            if forged_workspace:
                connection.execute(
                    "INSERT INTO workspaces VALUES(?,?,?,?,?,?)",
                    ("forged-space", 1, "active", "{}", created, created),
                )
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute("PRAGMA user_version=1")
            connection.commit()
        finally:
            connection.close()

    def test_clean_v1_migrates_and_forged_v1_is_rejected_without_mutation(self):
        for forged in (False, True):
            with self.subTest(forged=forged), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "control_plane.sqlite3"
                self._create_v1(path, forged_workspace=forged)
                before = path.read_bytes()
                store = _control_store(path)
                if forged:
                    with self.assertRaisesRegex(ControlPlaneSchemaError, "not empty"):
                        store.initialize()
                    self.assertEqual(path.read_bytes(), before)
                else:
                    with store:
                        pass
                    connection = sqlite3.connect(path)
                    try:
                        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                        self.assertEqual(
                            connection.execute("SELECT count(*) FROM migration_journal").fetchone()[0],
                            2,
                        )
                    finally:
                        connection.close()


if __name__ == "__main__":
    unittest.main()
