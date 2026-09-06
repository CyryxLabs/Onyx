"""Adversarial security contracts for the additive workspace registry/backfill."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import pickle
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


# Reuse the reviewed legacy source fixtures without making ``tests`` a package.
_TESTS_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _TESTS_ROOT.parent
sys.path.insert(0, os.fspath(_PROJECT_ROOT))
sys.path.insert(0, os.fspath(_TESTS_ROOT))
from test_workspace_registry import (  # noqa: E402
    _control_store,
    _create_memory_database,
    _create_mission_database,
)

from core.control_plane import (  # noqa: E402
    APPLICATION_ID,
    MIGRATION_ID,
    M1A_SCHEMA_STATEMENTS,
    M1A_SCHEMA_VERSION,
    ControlPlaneSchemaError,
    _reference_manifest,
    _schema_fingerprint,
)
from core.workspaces import (  # noqa: E402
    BackfillConflict,
    BackfillSourceError,
    LegacyContextBackfill,
    LegacyMarkerError,
    LegacySnapshotReader,
    LegacySourcePaths,
    LegacyWorkspaceAdapter,
    WorkspacePendingReview,
    WorkspaceRegistry,
    _HOST_MARKER,
    _LegacyHostMarker,
    _host_owned_source_paths,
)


def _fixture(root: Path):
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


def _logical_hashes(candidates: tuple[object, ...]) -> dict[str, str]:
    return {
        str(getattr(candidate, "source_id")): str(getattr(candidate, "logical_hash"))
        for candidate in candidates
    }


def _replace_with_same_bytes_and_new_identity(path: Path) -> None:
    before = path.stat()
    replacement = path.with_name(path.name + ".identity-replacement")
    replacement.write_bytes(path.read_bytes())
    os.utime(
        replacement,
        ns=(before.st_atime_ns, before.st_mtime_ns + 10_000_000),
    )
    os.replace(replacement, path)


class WorkspaceRegistrySecurityTests(unittest.TestCase):
    def test_memory_logical_identity_ignores_access_telemetry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, _registry, reader, _backfill = _fixture(root)
            try:
                with reader.capture(store.path.parent / "snapshot-a") as first:
                    first_hashes = _logical_hashes(first.memories)

                memory.execute(
                    "UPDATE memories SET access_count=access_count+1000, "
                    "last_accessed_at='2099-12-31T23:59:59+00:00'"
                )
                memory.commit()

                with reader.capture(store.path.parent / "snapshot-b") as second:
                    second_hashes = _logical_hashes(second.memories)

                self.assertEqual(second_hashes, first_hashes)
                self.assertEqual(len(second_hashes), 2)
            finally:
                store.close()
                mission.close()
                memory.close()

    def test_verified_replay_revalidates_persisted_rows_after_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, registry, _reader, backfill = _fixture(root)
            try:
                result = backfill.run()
                self.assertEqual(result.status, "verified")
                connection = registry._connection()
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM legacy_backfill_candidates WHERE candidate_id=("
                    "SELECT candidate_id FROM legacy_backfill_candidates ORDER BY candidate_id LIMIT 1)"
                )
                connection.execute("COMMIT")

                with self.assertRaisesRegex(BackfillConflict, "read-back|readback|diverg"):
                    backfill.run()
            finally:
                store.close()
                mission.close()
                memory.close()

    def test_host_marker_rejects_every_request_controlled_forgery_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = _control_store(root / "runtime" / "control_plane.sqlite3")
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            try:
                for forgery in (
                    object(),
                    {},
                    "host",
                    os.environ,
                    {"marker": _HOST_MARKER},
                    [_HOST_MARKER],
                ):
                    with self.subTest(forgery=type(forgery).__name__):
                        with self.assertRaises(LegacyMarkerError):
                            LegacyWorkspaceAdapter(registry, forgery)
                        with self.assertRaises(LegacyMarkerError):
                            _host_owned_source_paths(forgery)

                with patch.dict(
                    os.environ,
                    {"ONYX_LEGACY_HOST_MARKER": "host", "ONYX_TEST_ROOT": os.fspath(root)},
                    clear=False,
                ):
                    with self.assertRaises(LegacyMarkerError):
                        LegacyWorkspaceAdapter(registry, os.environ["ONYX_LEGACY_HOST_MARKER"])
                    with self.assertRaises(LegacyMarkerError):
                        _host_owned_source_paths(os.environ["ONYX_LEGACY_HOST_MARKER"])

                with self.assertRaises(TypeError):
                    _LegacyHostMarker()
                with self.assertRaises(TypeError):
                    type("ForgedMarkerSubclass", (_LegacyHostMarker,), {})
                for operation in (
                    lambda: copy.copy(_HOST_MARKER),
                    lambda: copy.deepcopy(_HOST_MARKER),
                    lambda: pickle.dumps(_HOST_MARKER),
                ):
                    with self.subTest(operation=operation), self.assertRaises(TypeError):
                        operation()

                with self.assertRaises(TypeError):
                    LegacySourcePaths(object(), root)
                with self.assertRaises(TypeError):
                    _host_owned_source_paths(_HOST_MARKER, test_root=root)  # type: ignore[call-arg]
                with self.assertRaises(LegacyMarkerError):
                    LegacySnapshotReader(object(), object())  # type: ignore[arg-type]
            finally:
                store.close()

    def test_missing_backfill_run_rejects_mission_and_memory_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _control_store(Path(tmp) / "runtime" / "control_plane.sqlite3")
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            try:
                registry.register(
                    "client-alpha",
                    display_name="Client Alpha",
                    workspace_class="client",
                )
                created = "2026-01-01T00:00:00+00:00"
                missing_payload = json.dumps(
                    {"run_id": "missing-backfill-run", "logical_hash": "0" * 64},
                    sort_keys=True,
                )
                connection = registry._connection()
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO mission_contexts VALUES(?,?,?,?,?,?,?)",
                    (
                        "mis_missing_run",
                        "client-alpha",
                        1,
                        "LEGACY_BACKFILLED",
                        missing_payload,
                        created,
                        created,
                    ),
                )
                connection.execute(
                    "INSERT INTO memory_metadata VALUES(?,?,?,?,?,?,?,?)",
                    (
                        "metadata-missing-run",
                        "client-alpha",
                        "mem_missing_run",
                        1,
                        "active",
                        missing_payload,
                        created,
                        created,
                    ),
                )
                connection.execute("COMMIT")

                with self.assertRaises(WorkspacePendingReview):
                    registry.mission_reference("client-alpha", "mis_missing_run")
                with self.assertRaises(WorkspacePendingReview):
                    registry.memory_reference("client-alpha", "mem_missing_run")
            finally:
                store.close()

    def test_run_id_is_stable_across_inode_and_mtime_only_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, _registry, reader, _backfill = _fixture(root)
            try:
                mission.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                memory.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                mission.close()
                memory.close()

                with reader.capture(store.path.parent / "snapshot-before") as first:
                    first_pair = (first.mission_hash, first.memory_hash)
                    first_run_id = hashlib.sha256(
                        f"{first.mission_hash}\0{first.memory_hash}".encode()
                    ).hexdigest()

                protected = (
                    root / "onyx_missions.sqlite3",
                    root / "onyx_memory.sqlite3",
                    root / "long_term.json",
                )
                byte_hashes = {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in protected
                }
                old_identities = {path.name: path.stat().st_ino for path in protected}
                for path in protected:
                    _replace_with_same_bytes_and_new_identity(path)

                with reader.capture(store.path.parent / "snapshot-after") as second:
                    second_pair = (second.mission_hash, second.memory_hash)
                    second_run_id = hashlib.sha256(
                        f"{second.mission_hash}\0{second.memory_hash}".encode()
                    ).hexdigest()

                self.assertEqual(second_pair, first_pair)
                self.assertEqual(second_run_id, first_run_id)
                self.assertEqual(
                    {
                        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in protected
                    },
                    byte_hashes,
                )
                if all(path.stat().st_ino for path in protected):
                    self.assertTrue(
                        any(path.stat().st_ino != old_identities[path.name] for path in protected)
                    )
            finally:
                store.close()
                try:
                    mission.close()
                except sqlite3.Error:
                    pass
                try:
                    memory.close()
                except sqlite3.Error:
                    pass

    def test_backfill_uses_control_plane_owned_private_staging_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission, memory, store, _registry, reader, backfill = _fixture(root)
            expected_root = store.path.parent / ".m1b-snapshots"
            observed: list[Path] = []
            original_capture = reader.capture

            @contextlib.contextmanager
            def inspected_capture(snapshot_root: Path):
                observed.append(snapshot_root)
                self.assertEqual(snapshot_root, expected_root)
                self.assertEqual(snapshot_root.parent.resolve(), store.path.parent.resolve())
                with original_capture(snapshot_root) as snapshot:
                    self.assertTrue(snapshot_root.is_dir())
                    if os.name != "nt":
                        self.assertEqual(stat.S_IMODE(snapshot_root.stat().st_mode), 0o700)
                    yield snapshot

            try:
                with patch.object(reader, "capture", inspected_capture):
                    result = backfill.run()
                self.assertEqual(result.status, "verified")
                self.assertEqual(observed, [expected_root])
            finally:
                store.close()
                mission.close()
                memory.close()

    def test_semantic_schema_mutations_are_rejected_even_when_columns_remain(self):
        mutations = (
            (
                "mission_immutability_trigger",
                "DROP TRIGGER events_no_update",
                "mission",
                "trigger",
            ),
            (
                "memory_dedupe_contract",
                "DROP INDEX idx_memories_dedupe",
                "memory",
                "semantic schema contract",
            ),
        )
        for label, statement, database, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                mission, memory, store, _registry, reader, _backfill = _fixture(root)
                try:
                    target = mission if database == "mission" else memory
                    target.execute(statement)
                    target.commit()
                    with self.assertRaisesRegex(BackfillSourceError, expected_error):
                        with reader.capture(store.path.parent / "schema-mutation-snapshot"):
                            self.fail("semantically forged legacy schema was accepted")
                finally:
                    store.close()
                    mission.close()
                    memory.close()


class ControlPlaneMigrationSecurityTests(unittest.TestCase):
    @staticmethod
    def _create_nonempty_v1(path: Path) -> None:
        connection = sqlite3.connect(path)
        try:
            for statement in M1A_SCHEMA_STATEMENTS:
                connection.execute(statement)
            fingerprint = _schema_fingerprint(_reference_manifest(version=M1A_SCHEMA_VERSION))
            created = "2026-01-01T00:00:00+00:00"
            connection.executemany(
                "INSERT INTO schema_metadata VALUES(?,?)",
                (
                    ("schema_id", "onyx-control-plane"),
                    ("schema_version", str(M1A_SCHEMA_VERSION)),
                    ("schema_fingerprint", fingerprint),
                    ("created_at", created),
                ),
            )
            connection.execute(
                "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
                (MIGRATION_ID, 0, M1A_SCHEMA_VERSION, "applied", created, fingerprint),
            )
            connection.execute(
                "INSERT INTO workspaces VALUES(?,?,?,?,?,?)",
                ("preexisting", 1, "active", "{}", created, created),
            )
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={M1A_SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()

    def test_v1_to_v2_rejects_nonempty_m1a_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            self._create_nonempty_v1(path)
            before = path.read_bytes()
            store = _control_store(path)
            with self.assertRaisesRegex(ControlPlaneSchemaError, "not empty"):
                store.initialize()
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(store.is_open)


if __name__ == "__main__":
    unittest.main()
