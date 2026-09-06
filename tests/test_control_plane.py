import builtins
import hashlib
import os
import sqlite3
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from queue import Empty
from unittest.mock import patch

import core.paths as onyx_paths
from core.control_plane import (
    CONTROL_PLANE_FLAG,
    ControlPlaneCorruptionError,
    ControlPlaneDisabled,
    ControlPlaneIOError,
    ControlPlaneLockError,
    ControlPlanePathError,
    ControlPlaneSchemaError,
    ControlPlaneStore,
    _InitializationLock,
    _WindowsNamedMutex,
    _apply_windows_security_sddl,
    _canonical_check_expressions,
    _current_windows_sid,
    _save_windows_dacl,
    _save_windows_security_sddl,
    _secure_windows_acl,
    _verify_windows_ancestor_sddl,
    _verify_windows_private_ancestor,
    _verify_windows_sddl,
    _windows_capability_sid_is_enabled,
    _windows_owner_sid,
    _windows_token_capability_sids,
    control_plane_v1_enabled,
)


EXPECTED_APPLICATION_ID = 0x4F4E5958
EXPECTED_SCHEMA_VERSION = 2
EXPECTED_TABLES = {
    "action_receipts",
    "action_requests",
    "artifact_index",
    "autonomy_envelopes",
    "capability_descriptors",
    "claims",
    "event_envelopes",
    "evidence_records",
    "grants",
    "memory_metadata",
    "migration_journal",
    "mission_contexts",
    "projections",
    "schema_metadata",
    "workspaces",
    "legacy_backfill_candidates",
    "backfill_runs",
}
EXPECTED_INDEXES = {
    "idx_action_receipts_request",
    "idx_action_requests_workspace_mission",
    "idx_artifacts_workspace_status",
    "idx_capabilities_workspace_status",
    "idx_claims_workspace_status",
    "idx_envelopes_workspace_mission",
    "idx_events_workspace_correlation",
    "idx_evidence_workspace_mission",
    "idx_grants_workspace_status_expiry",
    "idx_memory_metadata_workspace_source",
    "idx_mission_contexts_workspace",
    "idx_projections_workspace_type",
    "idx_legacy_candidates_status",
    "idx_legacy_candidates_workspace",
    "idx_memory_metadata_workspace_source_unique",
}
DOMAIN_TABLES = EXPECTED_TABLES - {"migration_journal", "schema_metadata"}

# Independent compact contract: ! means NOT NULL, * means primary key.
EXPECTED_COLUMN_SPECS = {
    "schema_metadata": "key:TEXT!* value:TEXT!",
    "migration_journal": (
        "migration_id:TEXT!* schema_from:INTEGER! schema_to:INTEGER! status:TEXT! "
        "applied_at:TEXT! schema_fingerprint:TEXT!"
    ),
    "workspaces": (
        "workspace_id:TEXT!* schema_version:INTEGER! status:TEXT! payload_json:TEXT! "
        "created_at:TEXT! updated_at:TEXT!"
    ),
    "mission_contexts": (
        "mission_id:TEXT!* workspace_id:TEXT! schema_version:INTEGER! operational_phase:TEXT! "
        "payload_json:TEXT! created_at:TEXT! updated_at:TEXT!"
    ),
    "capability_descriptors": (
        "capability_id:TEXT!* workspace_id:TEXT schema_version:INTEGER! status:TEXT! "
        "payload_json:TEXT! created_at:TEXT! updated_at:TEXT!"
    ),
    "grants": (
        "grant_id:TEXT!* workspace_id:TEXT! schema_version:INTEGER! status:TEXT! "
        "expires_at:TEXT! payload_json:TEXT! created_at:TEXT!"
    ),
    "autonomy_envelopes": (
        "envelope_id:TEXT!* workspace_id:TEXT! mission_id:TEXT schema_version:INTEGER! "
        "status:TEXT! expires_at:TEXT! payload_json:TEXT! created_at:TEXT!"
    ),
    "evidence_records": (
        "evidence_id:TEXT!* workspace_id:TEXT! mission_id:TEXT schema_version:INTEGER! "
        "content_sha256:TEXT payload_json:TEXT! created_at:TEXT!"
    ),
    "claims": (
        "claim_id:TEXT!* workspace_id:TEXT! schema_version:INTEGER! verification_status:TEXT! "
        "payload_json:TEXT! created_at:TEXT! updated_at:TEXT!"
    ),
    "action_requests": (
        "request_id:TEXT!* workspace_id:TEXT! mission_id:TEXT schema_version:INTEGER! "
        "idempotency_key:TEXT! status:TEXT! payload_sha256:TEXT! payload_json:TEXT! "
        "created_at:TEXT! updated_at:TEXT!"
    ),
    "action_receipts": (
        "receipt_id:TEXT!* request_id:TEXT! schema_version:INTEGER! outcome:TEXT! "
        "payload_json:TEXT! created_at:TEXT!"
    ),
    "memory_metadata": (
        "memory_metadata_id:TEXT!* workspace_id:TEXT! source_memory_id:TEXT "
        "schema_version:INTEGER! status:TEXT! payload_json:TEXT! created_at:TEXT! updated_at:TEXT!"
    ),
    "projections": (
        "projection_id:TEXT!* workspace_id:TEXT! schema_version:INTEGER! projection_type:TEXT! "
        "payload_json:TEXT! created_at:TEXT! updated_at:TEXT!"
    ),
    "event_envelopes": (
        "event_id:TEXT!* workspace_id:TEXT! mission_id:TEXT correlation_id:TEXT! "
        "schema_version:INTEGER! event_type:TEXT! payload_json:TEXT! previous_hash:TEXT! "
        "event_hash:TEXT! created_at:TEXT!"
    ),
    "artifact_index": (
        "artifact_id:TEXT!* workspace_id:TEXT! schema_version:INTEGER! sha256:TEXT! "
        "relative_path:TEXT! media_type:TEXT! status:TEXT! created_at:TEXT!"
    ),
    "legacy_backfill_candidates": (
        "candidate_id:TEXT!* source_kind:TEXT! source_identity:TEXT! source_id:TEXT! "
        "source_schema_version:INTEGER! logical_hash:TEXT! run_id:TEXT! status:TEXT! "
        "reason:TEXT! workspace_id:TEXT created_at:TEXT! updated_at:TEXT!"
    ),
    "backfill_runs": (
        "run_id:TEXT!* schema_version:INTEGER! status:TEXT! mission_source_identity:TEXT! "
        "mission_source_hash:TEXT! memory_source_identity:TEXT! memory_source_hash:TEXT! "
        "started_at:TEXT! completed_at:TEXT readback_hash:TEXT payload_json:TEXT! "
        "lease_owner:TEXT! lease_expires_at:TEXT! heartbeat_at:TEXT! lease_epoch:INTEGER!"
    ),
}

EXPECTED_FKS = {
    "mission_contexts": ("workspaces", "workspace_id", "workspace_id"),
    "capability_descriptors": ("workspaces", "workspace_id", "workspace_id"),
    "grants": ("workspaces", "workspace_id", "workspace_id"),
    "autonomy_envelopes": ("workspaces", "workspace_id", "workspace_id"),
    "evidence_records": ("workspaces", "workspace_id", "workspace_id"),
    "claims": ("workspaces", "workspace_id", "workspace_id"),
    "action_requests": ("workspaces", "workspace_id", "workspace_id"),
    "action_receipts": ("action_requests", "request_id", "request_id"),
    "memory_metadata": ("workspaces", "workspace_id", "workspace_id"),
    "projections": ("workspaces", "workspace_id", "workspace_id"),
    "event_envelopes": ("workspaces", "workspace_id", "workspace_id"),
    "artifact_index": ("workspaces", "workspace_id", "workspace_id"),
}
EXPECTED_MULTI_FKS = {
    "legacy_backfill_candidates": {
        ("workspaces", "workspace_id", "workspace_id", "NO ACTION", "NO ACTION", "NONE"),
        ("backfill_runs", "run_id", "run_id", "NO ACTION", "NO ACTION", "NONE"),
    }
}

EXPECTED_EXPLICIT_INDEX_COLUMNS = {
    "idx_mission_contexts_workspace": ("workspace_id",),
    "idx_capabilities_workspace_status": ("workspace_id", "status"),
    "idx_grants_workspace_status_expiry": ("workspace_id", "status", "expires_at"),
    "idx_envelopes_workspace_mission": ("workspace_id", "mission_id"),
    "idx_evidence_workspace_mission": ("workspace_id", "mission_id"),
    "idx_claims_workspace_status": ("workspace_id", "verification_status"),
    "idx_action_requests_workspace_mission": ("workspace_id", "mission_id"),
    "idx_action_receipts_request": ("request_id",),
    "idx_memory_metadata_workspace_source": ("workspace_id", "source_memory_id"),
    "idx_projections_workspace_type": ("workspace_id", "projection_type"),
    "idx_events_workspace_correlation": ("workspace_id", "correlation_id"),
    "idx_artifacts_workspace_status": ("workspace_id", "status"),
    "idx_legacy_candidates_status": ("status", "source_kind"),
    "idx_legacy_candidates_workspace": ("workspace_id", "status"),
}
EXPECTED_UNIQUE_INDEX_COLUMNS = {
    "action_requests": {("idempotency_key",)},
    "event_envelopes": {("event_hash",)},
    "artifact_index": {("workspace_id", "sha256")},
    "legacy_backfill_candidates": {("source_kind", "source_identity", "source_id")},
}


def _multiprocess_initialize(runtime: str, results) -> None:
    try:
        with patch(
            "core.control_plane.private_control_plane_runtime_dir",
            return_value=Path(runtime),
        ):
            with ControlPlaneStore(enabled=True):
                pass
        results.put(None)
    except BaseException as exc:
        results.put(f"{type(exc).__name__}: {exc}")


def make_control_plane_store(
    path: Path, *, enabled: bool | None = True
) -> ControlPlaneStore:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=path.parent,
    ):
        return ControlPlaneStore(enabled=enabled)


def sqlite_objects(path: Path, kind: str) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%'",
                (kind,),
            )
        }
    finally:
        connection.close()


class ControlPlaneM1aTests(unittest.TestCase):
    def test_flag_is_default_off_and_disabled_initialize_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / "runtime" / "control_plane.sqlite3"
            self.assertFalse(control_plane_v1_enabled())
            with self.assertRaises(ControlPlaneDisabled):
                make_control_plane_store(path, enabled=None).initialize()
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())

    def test_opt_in_uses_fixed_runtime_root_and_context_manager_closes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {CONTROL_PLANE_FLAG: "true"}, clear=True
        ):
            runtime = Path(tmp) / "runtime"
            with patch(
                "core.control_plane.private_control_plane_runtime_dir",
                return_value=runtime,
            ):
                store = ControlPlaneStore()
            with store as opened:
                self.assertIs(opened, store)
                self.assertTrue(store.is_open)
                self.assertEqual(
                    store.path,
                    runtime / "control_plane.sqlite3",
                )
            self.assertFalse(store.is_open)

    def test_private_path_rejects_relative_xdg_and_supports_missing_base(self):
        with patch("core.paths.platform.system", return_value="Linux"), patch.dict(
            os.environ,
            {"XDG_DATA_HOME": "relative-data", "ONYX_DATA_DIR": "checkout-data"},
            clear=False,
        ):
            with self.assertRaisesRegex(
                onyx_paths.PrivateDataPathError,
                "XDG_DATA_HOME must be an absolute path",
            ):
                onyx_paths.private_control_plane_runtime_dir()
        with patch("core.paths.platform.system", return_value="Windows"), patch(
            "core.paths._native_windows_local_app_data",
            side_effect=onyx_paths.PrivateDataPathError("native unavailable"),
        ), patch.dict(
            os.environ, {"LOCALAPPDATA": "relative-data", "USERPROFILE": "relative-profile"},
            clear=True,
        ):
            with self.assertRaises(onyx_paths.PrivateDataPathError):
                onyx_paths.private_control_plane_runtime_dir()
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            runtime = (
                Path(tmp)
                / "entirely-missing"
                / "share"
                / "cyryx-labs"
                / "onyx"
                / "runtime"
            )
            with patch(
                "core.control_plane.private_control_plane_runtime_dir",
                return_value=runtime,
            ):
                with ControlPlaneStore(enabled=True):
                    pass
            self.assertTrue((runtime / "control_plane.sqlite3").is_file())

    def test_windows_private_root_requires_known_folder_and_ignores_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "canonical" / "AppData" / "Local"
            malicious = root / "redirected"
            with patch("core.paths.platform.system", return_value="Windows"), patch(
                "core.paths._native_windows_local_app_data", return_value=canonical
            ), patch.dict(
                os.environ,
                {"LOCALAPPDATA": os.fspath(malicious), "USERPROFILE": os.fspath(root)},
                clear=True,
            ):
                self.assertEqual(
                    onyx_paths.private_control_plane_runtime_dir(),
                    canonical / "Cyryx Labs" / "Onyx" / "runtime",
                )

            native_failure = onyx_paths.PrivateDataPathError("native unavailable")
            for environment in (
                {
                    "LOCALAPPDATA": os.fspath(root / "profile" / "AppData" / "Local"),
                    "USERPROFILE": os.fspath(root / "profile"),
                },
                {
                    "LOCALAPPDATA": os.fspath(root / "profile" / ".." / "outside"),
                    "USERPROFILE": os.fspath(root / "profile"),
                },
                {},
            ):
                with self.subTest(environment=environment), patch(
                    "core.paths.platform.system", return_value="Windows"
                ), patch(
                    "core.paths._native_windows_local_app_data", side_effect=native_failure
                ), patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(onyx_paths.PrivateDataPathError):
                        onyx_paths.private_control_plane_runtime_dir()

    def test_windows_ancestor_sddl_allows_read_only_and_rejects_write(self):
        current = "S-1-5-21-1-2-3-1001"
        _verify_windows_ancestor_sddl(
            "D:(A;;FRFX;;;WD)(A;;0x1200a9;;;AU)(D;;FA;;;WD)",
            current,
            current,
        )
        _verify_windows_ancestor_sddl(
            "D:(A;;FA;;;BA)(A;;FR;;;AC)",
            "S-1-5-32-544",
            current,
        )
        guid = "aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb"
        _verify_windows_ancestor_sddl(
            f"D:PAI(OA;OICIID;FR;{guid};;WD)(OD;ID;FA;;{guid};WD)",
            current,
            current,
        )
        for rights in ("FA", "FW", "GA", "GW", "SD", "WD", "WO", "0x2", "0x40", "0x40000"):
            with self.subTest(rights=rights), self.assertRaisesRegex(
                ControlPlanePathError, "untrusted SID"
            ):
                _verify_windows_ancestor_sddl(
                    f"D:(A;;{rights};;;WD)", current, current
                )
        with self.assertRaisesRegex(ControlPlanePathError, "untrusted owner"):
            _verify_windows_ancestor_sddl(
                "D:(A;;FRFX;;;WD)", "S-1-5-21-9-9-9-1009", current
            )

        profile_owner = "S-1-5-21-1-2-3-1002"
        capability = "S-1-15-3-100-200-300"
        capability_dacl = (
            f"D:AI(A;OICIID;FA;;;{profile_owner})"
            f"(A;ID;FA;;;{capability})(A;OICIID;FA;;;SY)"
        )
        self.assertTrue(_windows_capability_sid_is_enabled(capability, 0x00000004))
        self.assertFalse(_windows_capability_sid_is_enabled(capability, 0))
        self.assertFalse(_windows_capability_sid_is_enabled(capability, 0x00000014))
        self.assertFalse(
            _windows_capability_sid_is_enabled("S-1-15-2-1", 0x00000004)
        )
        enabled_capabilities = frozenset(
            {capability}
            if _windows_capability_sid_is_enabled(capability, 0x00000004)
            else set()
        )
        disabled_capabilities = frozenset(
            {capability}
            if _windows_capability_sid_is_enabled(capability, 0)
            else set()
        )
        _verify_windows_ancestor_sddl(
            capability_dacl,
            profile_owner,
            current,
            profile_owner_sid=profile_owner,
            capability_sids=enabled_capabilities,
        )
        for label, unavailable in (
            ("absent", frozenset()),
            ("disabled", disabled_capabilities),
        ):
            with self.subTest(capability=label), self.assertRaisesRegex(
                ControlPlanePathError, "untrusted SID"
            ):
                _verify_windows_ancestor_sddl(
                    capability_dacl,
                    profile_owner,
                    current,
                    profile_owner_sid=profile_owner,
                    capability_sids=unavailable,
                )
        for broad_sid in ("WD", "AU", "BU", "AC", "S-1-5-32-545"):
            with self.subTest(broad_sid=broad_sid), self.assertRaisesRegex(
                ControlPlanePathError, "untrusted SID"
            ):
                _verify_windows_ancestor_sddl(
                    f"D:(A;;FA;;;{broad_sid})",
                    current,
                    current,
                    capability_sids=frozenset({capability}),
                )

        malformed = {
            "null": "D:NO_ACCESS_CONTROL",
            "missing": "not-an-sddl",
            "empty": "D:",
            "trailing": "D:(A;;FR;;;WD)junk",
            "unbalanced": "D:(A;;FR;;;WD",
            "extra_close": "D:(A;;FR;;;WD))",
            "fields": "D:(A;;FR;;WD)",
            "type": "D:(XA;;FR;;;WD)",
            "flags": "D:(A;ZZ;FR;;;WD)",
            "duplicate_flags": "D:(A;OIOI;FR;;;WD)",
            "rights": "D:(A;;ZZ;;;WD)",
            "deny_rights": "D:(D;;GARBAGE;;;WD)",
            "sid": "D:(A;;FR;;;NOT_A_SID)",
            "non_object_guid": f"D:(A;;FR;{guid};;WD)",
            "object_guid": "D:(OA;;FR;not-a-guid;;WD)",
            "controls": "D:ZZ(A;;FR;;;WD)",
        }
        for label, dacl in malformed.items():
            with self.subTest(malformed=label), self.assertRaises(ControlPlanePathError):
                _verify_windows_ancestor_sddl(dacl, current, current)

    def test_windows_existing_base_acl_is_checked_before_managed_creation(self):
        if os.name != "nt":
            self.skipTest("native Windows ancestor ACL probe")
        current = _current_windows_sid()
        with tempfile.TemporaryDirectory() as tmp:
            safe_base = Path(tmp) / "safe-local-app-data"
            safe_base.mkdir()
            _apply_windows_security_sddl(
                safe_base,
                f"O:{current}D:P"
                f"(A;OICI;FA;;;SY)(A;OICI;FA;;;{current})"
                "(A;OICI;GRGX;;;WD)",
            )
            _verify_windows_private_ancestor(safe_base)

        with tempfile.TemporaryDirectory() as tmp:
            unsafe_base = Path(tmp) / "unsafe-local-app-data"
            unsafe_base.mkdir()
            _apply_windows_security_sddl(
                unsafe_base,
                f"O:{current}D:P"
                f"(A;OICI;FA;;;SY)(A;OICI;FA;;;{current})"
                "(A;OICI;FA;;;WD)",
            )
            runtime = unsafe_base / "cyryx-labs" / "onyx" / "runtime"
            with patch(
                "core.control_plane.private_control_plane_runtime_dir",
                return_value=runtime,
            ):
                with self.assertRaisesRegex(ControlPlanePathError, "untrusted SID"):
                    ControlPlaneStore(enabled=True).initialize()
            self.assertFalse((unsafe_base / "cyryx-labs").exists())

    def test_windows_existing_canonical_managed_root_cuts_off_unsafe_base(self):
        if os.name != "nt":
            self.skipTest("native Windows managed-root ACL probe")
        current = _current_windows_sid()
        with tempfile.TemporaryDirectory() as tmp:
            unsafe_base = Path(tmp) / "unsafe-local-app-data"
            unsafe_base.mkdir()
            _apply_windows_security_sddl(
                unsafe_base,
                f"O:{current}D:P"
                f"(A;OICI;FA;;;SY)(A;OICI;FA;;;{current})"
                "(A;OICI;FA;;;WD)",
            )
            vendor = unsafe_base / "Cyryx Labs"
            vendor.mkdir()
            _apply_windows_security_sddl(
                vendor,
                f"O:{current}D:P"
                f"(A;OICI;FA;;;SY)(A;OICI;FA;;;{current})",
            )
            runtime = vendor / "Onyx" / "runtime"
            with patch(
                "core.control_plane.private_control_plane_runtime_dir",
                return_value=runtime,
            ):
                store = ControlPlaneStore(enabled=True).initialize()
                store.close()
            self.assertTrue((runtime / "control_plane.sqlite3").is_file())

    def test_windows_noncanonical_managed_root_under_unsafe_base_stays_closed(self):
        if os.name != "nt":
            self.skipTest("native Windows managed-root ACL probe")
        current = _current_windows_sid()
        with tempfile.TemporaryDirectory() as tmp:
            unsafe_base = Path(tmp) / "unsafe-local-app-data"
            unsafe_base.mkdir()
            _apply_windows_security_sddl(
                unsafe_base,
                f"O:{current}D:P"
                f"(A;OICI;FA;;;SY)(A;OICI;FA;;;{current})"
                "(A;OICI;FA;;;WD)",
            )
            vendor = unsafe_base / "Cyryx Labs"
            vendor.mkdir()
            runtime = vendor / "Onyx" / "runtime"
            with patch(
                "core.control_plane.private_control_plane_runtime_dir",
                return_value=runtime,
            ):
                with self.assertRaisesRegex(ControlPlanePathError, "untrusted SID"):
                    ControlPlaneStore(enabled=True).initialize()
            self.assertFalse((vendor / "Onyx").exists())

    def test_canonical_windows_local_app_data_acl_matches_token_capabilities(self):
        if os.name != "nt":
            self.skipTest("native Windows canonical ACL probe")
        canonical = onyx_paths.windows_local_app_data_dir()
        self.assertTrue(canonical.is_absolute())
        capabilities = _windows_token_capability_sids()
        self.assertTrue(all(sid.startswith("S-1-15-3-") for sid in capabilities))
        production_root = canonical / "Cyryx Labs" / "Onyx"
        production_runtime = production_root / "runtime"
        production_db = production_runtime / "control_plane.sqlite3"
        existed_before = production_root.exists()
        db_existed_before = production_db.exists()
        try:
            _verify_windows_private_ancestor(canonical)
        except ControlPlanePathError as incompatibility:
            self.assertRegex(
                str(incompatibility), "untrusted SID|untrusted owner|capability"
            )
            if not existed_before:
                with patch(
                    "core.control_plane.private_control_plane_runtime_dir",
                    return_value=production_runtime,
                ):
                    with self.assertRaises(ControlPlanePathError):
                        ControlPlaneStore(enabled=True).initialize()
                self.assertFalse(production_root.exists())
                self.assertFalse(production_db.exists())
            else:
                self.assertEqual(production_db.exists(), db_existed_before)
            return

        self.assertEqual(production_root.exists(), existed_before)
        self.assertEqual(production_db.exists(), db_existed_before)
        with tempfile.TemporaryDirectory() as tmp:
            safe_db = Path(tmp) / "runtime" / "control_plane.sqlite3"
            with make_control_plane_store(safe_db):
                pass
            self.assertTrue(safe_db.is_file())

    def test_schema_indexes_metadata_journal_and_zero_domain_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            with make_control_plane_store(path):
                pass
            self.assertEqual(sqlite_objects(path, "table"), EXPECTED_TABLES)
            self.assertEqual(sqlite_objects(path, "index"), EXPECTED_INDEXES)
            self.assertEqual(sqlite_objects(path, "view"), set())
            self.assertEqual(sqlite_objects(path, "trigger"), set())
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA application_id").fetchone()[0],
                    EXPECTED_APPLICATION_ID,
                )
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    EXPECTED_SCHEMA_VERSION,
                )
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM schema_metadata").fetchone()[0],
                    4,
                )
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM migration_journal").fetchone()[0],
                    2,
                )
                for table in DOMAIN_TABLES:
                    self.assertEqual(
                        connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0],
                        0,
                        table,
                    )
                legacy = connection.execute(
                    "SELECT count(*) FROM workspaces WHERE workspace_id='legacy-default'"
                ).fetchone()[0]
                self.assertEqual(legacy, 0)
                self.assertEqual(connection.execute("PRAGMA quick_check").fetchone(), ("ok",))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                connection.close()

    def test_full_semantic_contract_is_independently_hardcoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            with make_control_plane_store(path):
                pass
            connection = sqlite3.connect(path)
            try:
                explicit_indexes = {}
                for table, spec in EXPECTED_COLUMN_SPECS.items():
                    expected_columns = []
                    primary_key = None
                    for token in spec.split():
                        name, annotated_type = token.split(":", 1)
                        not_null = int("!" in annotated_type)
                        is_primary = int("*" in annotated_type)
                        declared_type = annotated_type.rstrip("!*")
                        expected_columns.append(
                            (name, declared_type, not_null, None, is_primary, 0)
                        )
                        if is_primary:
                            primary_key = name
                    actual_columns = [
                        tuple(row[1:])
                        for row in connection.execute(
                            f'PRAGMA table_xinfo("{table}")'
                        ).fetchall()
                    ]
                    self.assertEqual(actual_columns, expected_columns, table)
                    table_flags = connection.execute(
                        f'PRAGMA table_list("{table}")'
                    ).fetchone()
                    self.assertIsNotNone(table_flags)
                    self.assertEqual(tuple(table_flags[4:6]), (1, 0), table)

                    actual_fks = [
                        (row[2], row[3], row[4], row[5], row[6], row[7])
                        for row in connection.execute(
                            f'PRAGMA foreign_key_list("{table}")'
                        ).fetchall()
                    ]
                    if table in EXPECTED_MULTI_FKS:
                        self.assertEqual(set(actual_fks), EXPECTED_MULTI_FKS[table], table)
                    else:
                        expected_fk = EXPECTED_FKS.get(table)
                        expected_fks = (
                            [(*expected_fk, "NO ACTION", "NO ACTION", "NONE")]
                            if expected_fk
                            else []
                        )
                        self.assertEqual(actual_fks, expected_fks, table)

                    saw_primary = False
                    unique_columns = set()
                    for _, index_name, unique, origin, partial in connection.execute(
                        f'PRAGMA index_list("{table}")'
                    ).fetchall():
                        key_columns = tuple(
                            row[2]
                            for row in connection.execute(
                                f'PRAGMA index_xinfo("{index_name}")'
                            ).fetchall()
                            if row[5]
                        )
                        if origin == "c":
                            if index_name == "idx_memory_metadata_workspace_source_unique":
                                self.assertEqual((unique, partial), (1, 1), index_name)
                                self.assertEqual(
                                    key_columns, ("workspace_id", "source_memory_id")
                                )
                            else:
                                self.assertEqual((unique, partial), (0, 0), index_name)
                                explicit_indexes[index_name] = key_columns
                        elif origin == "pk":
                            self.assertEqual((unique, partial, key_columns), (1, 0, (primary_key,)))
                            saw_primary = True
                        else:
                            self.assertEqual((unique, origin, partial), (1, "u", 0))
                            unique_columns.add(key_columns)
                    self.assertTrue(saw_primary, table)
                    self.assertEqual(
                        unique_columns,
                        EXPECTED_UNIQUE_INDEX_COLUMNS.get(table, set()),
                        table,
                    )
                self.assertEqual(explicit_indexes, EXPECTED_EXPLICIT_INDEX_COLUMNS)

                before = connection.execute(
                    "SELECT count(*) FROM migration_journal"
                ).fetchone()[0]
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
                        ("bad-status", 0, 1, "invalid", "now", "0" * 64),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
                        ("bad-hash", 0, 1, "applied", "now", "short"),
                    )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM migration_journal"
                    ).fetchone()[0],
                    before,
                )
            finally:
                connection.close()

    def test_check_contract_mutations_are_rejected_but_formatting_is_ignored(self):
        mutations = {
            "status_widened": (
                "CHECK(status IN ('applied'))",
                "CHECK(status IN ('applied','forged'))",
            ),
            "status_targeted_bypass": (
                "CHECK(status IN ('applied'))",
                "CHECK(status IN ('applied') OR migration_id NOT LIKE '__check_%')",
            ),
            "status_stricter": (
                "CHECK(status IN ('applied'))",
                "CHECK(status IN ('applied') AND migration_id!='blocked')",
            ),
            "status_removed": ("CHECK(status IN ('applied'))", ""),
            "fingerprint_widened": (
                "CHECK(length(schema_fingerprint)=64)",
                "CHECK(length(schema_fingerprint)>=1)",
            ),
            "fingerprint_stricter": (
                "CHECK(length(schema_fingerprint)=64)",
                "CHECK(length(schema_fingerprint)=64 AND schema_fingerprint NOT LIKE 'f%')",
            ),
        }
        for label, (original, replacement) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "control_plane.sqlite3"
                with make_control_plane_store(path):
                    pass
                connection = sqlite3.connect(path)
                try:
                    version = connection.execute("PRAGMA schema_version").fetchone()[0]
                    connection.execute("PRAGMA writable_schema=ON")
                    cursor = connection.execute(
                        "UPDATE sqlite_master SET sql=replace(sql,?,?) "
                        "WHERE type='table' AND name='migration_journal'",
                        (original, replacement),
                    )
                    self.assertEqual(cursor.rowcount, 1)
                    connection.execute(f"PRAGMA schema_version={version + 1}")
                    connection.commit()
                finally:
                    connection.close()
                with self.assertRaisesRegex(ControlPlaneSchemaError, "manifest"):
                    make_control_plane_store(path).initialize()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            with make_control_plane_store(path):
                pass
            connection = sqlite3.connect(path)
            try:
                version = connection.execute("PRAGMA schema_version").fetchone()[0]
                status_check = "CHECK(status IN ('applied'))"
                fingerprint_check = "CHECK(length(schema_fingerprint)=64)"
                connection.execute("PRAGMA writable_schema=ON")
                connection.execute(
                    "UPDATE sqlite_master SET sql=replace(replace(replace(sql,?,?),?,?),?,?) "
                    "WHERE type='table' AND name='migration_journal'",
                    (
                        status_check,
                        "__STATUS_CHECK__",
                        fingerprint_check,
                        status_check,
                        "__STATUS_CHECK__",
                        fingerprint_check,
                    ),
                )
                connection.execute(f"PRAGMA schema_version={version + 1}")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ControlPlaneSchemaError, "manifest"):
                make_control_plane_store(path).initialize()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            with make_control_plane_store(path):
                pass
            connection = sqlite3.connect(path)
            try:
                version = connection.execute("PRAGMA schema_version").fetchone()[0]
                connection.execute("PRAGMA writable_schema=ON")
                cursor = connection.execute(
                    "UPDATE sqlite_master SET sql=replace(sql,'CREATE TABLE ',"
                    "'create /* formatting only */ table ') WHERE type='table'"
                )
                self.assertEqual(cursor.rowcount, len(EXPECTED_TABLES))
                connection.execute(
                    "UPDATE sqlite_master SET sql=replace(sql,?,?) "
                    "WHERE type='table' AND name='migration_journal'",
                    (
                        "CHECK(status IN ('applied'))",
                        "cHeCk /* status */ ( status in ( 'applied' ) )",
                    ),
                )
                connection.execute(
                    "UPDATE sqlite_master SET sql=replace(sql,?,?) "
                    "WHERE type='table' AND name='migration_journal'",
                    (
                        "CHECK(length(schema_fingerprint)=64)",
                        "ChEcK ( length /* nested */ ( schema_fingerprint ) = 64 )",
                    ),
                )
                connection.execute(f"PRAGMA schema_version={version + 1}")
                connection.commit()
            finally:
                connection.close()
            with make_control_plane_store(path):
                pass

        self.assertEqual(
            _canonical_check_expressions(
                "CREATE TABLE t(x TEXT CHECK((x != 'a''b') AND length(\"x\") > 0))"
            ),
            _canonical_check_expressions(
                "create table t(x text check /* c */ ( ( x!='a''b' ) and LENGTH ( \"X\" )>0 ))"
            ),
        )

    def test_initialize_is_idempotent_and_context_exception_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            store = make_control_plane_store(path)
            self.assertIs(store.initialize(), store)
            self.assertIs(store.initialize(), store)
            store.close()
            store.close()
            with self.assertRaisesRegex(RuntimeError, "sentinel"):
                with store:
                    raise RuntimeError("sentinel")
            self.assertFalse(store.is_open)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM migration_journal").fetchone()[0],
                    2,
                )
            finally:
                connection.close()

    def test_future_schema_fails_closed_without_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            with make_control_plane_store(path):
                pass
            connection = sqlite3.connect(path)
            try:
                connection.execute(f"PRAGMA user_version={EXPECTED_SCHEMA_VERSION + 1}")
                connection.execute(
                    "UPDATE schema_metadata SET value=? WHERE key='schema_version'",
                    (str(EXPECTED_SCHEMA_VERSION + 1),),
                )
                connection.commit()
            finally:
                connection.close()
            before = path.read_bytes()
            with self.assertRaisesRegex(ControlPlaneSchemaError, "newer than supported"):
                make_control_plane_store(path).initialize()
            self.assertEqual(path.read_bytes(), before)

    def test_corrupt_database_fails_without_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            path.write_bytes(b"not a sqlite database\x00" * 16)
            before = hashlib.sha256(path.read_bytes()).digest()
            with self.assertRaises(ControlPlaneCorruptionError):
                make_control_plane_store(path).initialize()
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_foreign_nonzero_application_id_is_rejected_even_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA application_id=123")
            connection.commit()
            connection.close()
            before = path.read_bytes()
            with self.assertRaisesRegex(ControlPlaneSchemaError, "foreign SQLite application_id"):
                make_control_plane_store(path).initialize()
            self.assertEqual(path.read_bytes(), before)

    def test_altered_ddl_and_extra_view_or_trigger_are_rejected(self):
        mutations = {
            "column": "ALTER TABLE workspaces ADD COLUMN injected TEXT",
            "view": "CREATE VIEW injected_view AS SELECT 1 AS value",
            "trigger": (
                "CREATE TRIGGER injected_trigger AFTER INSERT ON workspaces "
                "BEGIN SELECT 1; END"
            ),
        }
        for label, sql in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "control_plane.sqlite3"
                with make_control_plane_store(path):
                    pass
                connection = sqlite3.connect(path)
                connection.execute(sql)
                connection.commit()
                connection.close()
                before = path.read_bytes()
                with self.assertRaisesRegex(ControlPlaneSchemaError, "manifest"):
                    make_control_plane_store(path).initialize()
                self.assertEqual(path.read_bytes(), before)

    def test_extra_metadata_and_journal_rows_are_rejected(self):
        def metadata(connection: sqlite3.Connection) -> None:
            connection.execute("INSERT INTO schema_metadata VALUES('extra','value')")

        def journal(connection: sqlite3.Connection) -> None:
            created_at = connection.execute(
                "SELECT value FROM schema_metadata WHERE key='created_at'"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO migration_journal VALUES(?,?,?,?,?,?)",
                ("extra", 1, 1, "applied", created_at, "0" * 64),
            )

        for label, mutation in {
            "metadata": metadata,
            "journal": journal,
        }.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "control_plane.sqlite3"
                with make_control_plane_store(path):
                    pass
                connection = sqlite3.connect(path)
                mutation(connection)
                connection.commit()
                connection.close()
                with self.assertRaises(ControlPlaneSchemaError):
                    make_control_plane_store(path).initialize()

    def test_linked_database_and_parent_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.sqlite3"
            link = root / "control_plane.sqlite3"
            real_parent = root / "real-parent"
            linked_parent = root / "linked-parent"
            real_parent.mkdir()
            try:
                link.symlink_to(target)
                linked_parent.symlink_to(real_parent, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")
            with self.assertRaises(ControlPlanePathError):
                make_control_plane_store(link).initialize()
            with self.assertRaises(ControlPlanePathError):
                make_control_plane_store(linked_parent / "control_plane.sqlite3").initialize()
            self.assertFalse(target.exists())

    def test_runtime_directory_replacement_during_initialize_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime" / "control_plane.sqlite3"
            store = make_control_plane_store(path)
            original_secure = ControlPlaneStore._secure_file

            def replace_parent(instance):
                parent = instance.path.parent
                moved = parent.with_name("runtime-moved")
                parent.rename(moved)
                parent.mkdir()
                return original_secure(instance)

            with patch.object(ControlPlaneStore, "_secure_file", replace_parent):
                with self.assertRaisesRegex(ControlPlanePathError, "directory identity changed"):
                    store.initialize()
            self.assertFalse(path.exists())

    def test_reserved_characters_in_test_path_reopen_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control plane %23 #" / "control_plane.sqlite3"
            with make_control_plane_store(path):
                pass
            with make_control_plane_store(path):
                pass

    def test_production_path_cannot_be_overridden_without_test_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.sqlite3"
            with self.assertRaises(TypeError):
                ControlPlaneStore(enabled=True, _test_path=outside)
            with self.assertRaises(TypeError):
                ControlPlaneStore(outside, enabled=True)  # type: ignore[call-arg]
            self.assertFalse(outside.exists())

    def test_enabled_rejects_strings_and_objects(self):
        for value in ("true", "false", 1, 0, object()):
            with self.subTest(value=value), self.assertRaises(TypeError):
                ControlPlaneStore(enabled=value)  # type: ignore[arg-type]

    def test_permission_failure_leaves_no_initialized_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            failure = ControlPlanePathError("injected chmod failure")
            with patch("core.control_plane._apply_file_permissions", side_effect=failure):
                with self.assertRaisesRegex(ControlPlanePathError, "chmod failure"):
                    make_control_plane_store(path).initialize()
            if path.exists():
                self.assertEqual(sqlite_objects(path, "table"), set())

    def test_owner_only_modes_on_posix(self):
        if os.name == "nt":
            self.skipTest("POSIX mode assertions")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime" / "control_plane.sqlite3"
            with make_control_plane_store(path):
                pass
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_read_only_open_failure_is_typed_and_non_mutating(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            with make_control_plane_store(path):
                pass
            before = path.read_bytes()
            real_open = os.open

            def deny_target(candidate, *args, **kwargs):
                if Path(candidate) == path:
                    raise PermissionError("read-only sentinel")
                return real_open(candidate, *args, **kwargs)

            with patch("core.control_plane.os.open", side_effect=deny_target):
                with self.assertRaises(ControlPlanePathError):
                    make_control_plane_store(path).initialize()
            self.assertEqual(path.read_bytes(), before)

    def test_schema_failure_rolls_back_all_ddl_and_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            statements = (
                "CREATE TABLE should_rollback(id INTEGER PRIMARY KEY)",
                "THIS IS NOT VALID SQL",
            )
            with patch("core.control_plane.M1A_SCHEMA_STATEMENTS", statements):
                with self.assertRaises(ControlPlaneIOError):
                    make_control_plane_store(path).initialize()
            if path.exists():
                connection = sqlite3.connect(path)
                try:
                    self.assertEqual(sqlite_objects(path, "table"), set())
                    self.assertEqual(connection.execute("PRAGMA application_id").fetchone()[0], 0)
                    self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
                finally:
                    connection.close()

    def test_concurrent_initialize_and_close_are_serialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_plane.sqlite3"
            store = make_control_plane_store(path)
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _index: store.initialize(), range(16)))
            self.assertTrue(all(result is store for result in results))
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _index: store.close(), range(16)))
            self.assertFalse(store.is_open)
            with make_control_plane_store(path):
                pass

    def test_eight_windows_processes_initialize_one_sidecar(self):
        if os.name != "nt":
            self.skipTest("native Windows mutex probe")
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            context = get_context("spawn")
            results = context.Queue()
            processes = [
                context.Process(
                    target=_multiprocess_initialize,
                    args=(os.fspath(runtime), results),
                )
                for _ in range(8)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(150)
            self.assertTrue(all(process.exitcode == 0 for process in processes))
            outcomes = []
            for _ in processes:
                try:
                    outcomes.append(results.get(timeout=5))
                except Empty:
                    outcomes.append("missing worker result")
            self.assertEqual(outcomes, [None] * 8)
            with make_control_plane_store(runtime / "control_plane.sqlite3"):
                pass

    def test_windows_managed_acl_verifier_rejects_every_noncanonical_variant(self):
        current = "S-1-5-21-111-222-333-1001"
        canonical_directory = f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{current})"
        canonical_file = f"D:P(A;;FA;;;SY)(A;;FA;;;{current})"
        _verify_windows_sddl(canonical_directory, current, is_directory=True)
        _verify_windows_sddl(canonical_file, current, is_directory=False)

        noncanonical_directory = {
            "generic_all": canonical_directory.replace(";FA;;;SY", ";GA;;;SY"),
            "no_propagate": canonical_directory.replace("OICI", "OICINP", 1),
            "inherit_only": canonical_directory.replace("OICI", "OICIIO", 1),
            "inherited": canonical_directory.replace("OICI", "OICIID", 1),
            "auto_inherited": canonical_directory.replace("D:P", "D:PAI"),
            "unprotected": canonical_directory.replace("D:P", "D:AI"),
            "reversed": (
                f"D:P(A;OICI;FA;;;{current})(A;OICI;FA;;;SY)"
            ),
            "deny": canonical_directory.replace("(A;OICI;FA;;;SY)", "(D;OICI;FA;;;SY)"),
            "extra_ace": canonical_directory + "(A;OICI;FR;;;WD)",
            "object_guid": canonical_directory.replace(
                ";;;SY", ";00000000-0000-0000-0000-000000000000;;SY", 1
            ),
        }
        for label, dacl in noncanonical_directory.items():
            with self.subTest(directory_variant=label), self.assertRaises(
                ControlPlanePathError
            ):
                _verify_windows_sddl(dacl, current, is_directory=True)

        for label, dacl in {
            "file_oi": canonical_file.replace("(A;;", "(A;OI;", 1),
            "file_ci": canonical_file.replace("(A;;", "(A;CI;", 1),
            "file_np": canonical_file.replace("(A;;", "(A;NP;", 1),
        }.items():
            with self.subTest(file_variant=label), self.assertRaises(
                ControlPlanePathError
            ):
                _verify_windows_sddl(dacl, current, is_directory=False)

    def test_windows_acl_failpoints_restore_exact_original_descriptor(self):
        if os.name != "nt":
            self.skipTest("native Windows ACL rollback probe")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollback-probe"
            path.mkdir()
            original = _save_windows_security_sddl(path)
            for failpoint in ("after_apply", "after_readback", "before_verify"):
                with self.subTest(failpoint=failpoint), self.assertRaisesRegex(
                    ControlPlanePathError, "injected Windows ACL failure"
                ):
                    _secure_windows_acl(
                        path,
                        is_directory=True,
                        failpoint=failpoint,
                    )
                self.assertEqual(_save_windows_security_sddl(path), original)

    def test_windows_acl_rollback_failure_is_explicit_and_fail_closed(self):
        if os.name != "nt":
            self.skipTest("Windows rollback failure contract")
        current = "S-1-5-21-111-222-333-1001"
        original = f"O:{current}D:AI(A;ID;FA;;;{current})"
        with (
            patch("core.control_plane._current_windows_sid", return_value=current),
            patch(
                "core.control_plane._save_windows_security_sddl",
                return_value=original,
            ),
            patch(
                "core.control_plane._apply_windows_security_sddl",
                side_effect=[
                    ControlPlanePathError("injected mutation failure"),
                    ControlPlanePathError("injected restore failure"),
                ],
            ),
            self.assertRaisesRegex(
                ControlPlanePathError,
                "mutation failed and exact rollback failed",
            ),
        ):
            _secure_windows_acl(Path("rollback-failure"), is_directory=True)

    def test_windows_acl_rollback_descriptor_mismatch_is_fail_closed(self):
        if os.name != "nt":
            self.skipTest("Windows rollback mismatch contract")
        current = "S-1-5-21-111-222-333-1001"
        original = f"O:{current}D:AI(A;ID;FA;;;{current})"
        drift = f"O:{current}D:P(A;;FA;;;{current})"
        with (
            patch("core.control_plane._current_windows_sid", return_value=current),
            patch(
                "core.control_plane._save_windows_security_sddl",
                side_effect=[original, drift],
            ),
            patch(
                "core.control_plane._apply_windows_security_sddl",
                side_effect=[ControlPlanePathError("mutation failure"), None],
            ),
            self.assertRaisesRegex(
                ControlPlanePathError,
                "mutation failed and exact rollback failed",
            ),
        ):
            _secure_windows_acl(Path("rollback-mismatch"), is_directory=False)

    def test_windows_owner_is_current_user_and_close_failure_keeps_reference(self):
        if os.name == "nt":
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "control_plane.sqlite3"
                with make_control_plane_store(path):
                    pass
                current = _current_windows_sid()
                self.assertEqual(_windows_owner_sid(path), current)
                _verify_windows_sddl(
                    _save_windows_dacl(path), current, is_directory=False
                )
                _verify_windows_sddl(
                    _save_windows_dacl(path.parent), current, is_directory=True
                )

        class FailingConnection:
            def close(self):
                raise sqlite3.OperationalError("injected close failure")

        with tempfile.TemporaryDirectory() as tmp:
            store = make_control_plane_store(Path(tmp) / "control_plane.sqlite3")
            failing = FailingConnection()
            store._connection = failing  # type: ignore[assignment]
            with self.assertRaisesRegex(ControlPlaneIOError, "injected close failure"):
                store.close()
            self.assertIs(store._connection, failing)

    def test_lock_release_always_closes_and_preserves_first_error(self):
        class FakeKernel32:
            def __init__(self, release_ok, close_ok):
                self.release_ok = release_ok
                self.close_ok = close_ok

            def ReleaseMutex(self, _handle):
                return self.release_ok

            def CloseHandle(self, _handle):
                return self.close_ok

        mutex = _WindowsNamedMutex(Path("mutex-test"))
        mutex.handle = 123
        mutex.acquired = True
        with patch.object(mutex, "_kernel32", return_value=FakeKernel32(False, True)):
            with self.assertRaisesRegex(ControlPlaneLockError, "release"):
                mutex.release()
        self.assertIsNone(mutex.handle)
        self.assertFalse(mutex.acquired)

        mutex.handle = 456
        mutex.acquired = True
        with patch.object(mutex, "_kernel32", return_value=FakeKernel32(False, False)):
            with self.assertRaisesRegex(ControlPlaneLockError, "release"):
                mutex.release()
        self.assertEqual(mutex.handle, 456)
        self.assertTrue(mutex.acquired)
        with patch.object(mutex, "_kernel32", return_value=FakeKernel32(True, True)):
            mutex.release()
        self.assertIsNone(mutex.handle)
        self.assertFalse(mutex.acquired)

        lock = _InitializationLock(Path("lock-test"))
        lock.descriptor = 789
        lock.locked = True
        unlock_target = "msvcrt.locking" if os.name == "nt" else "fcntl.flock"
        with patch(unlock_target, side_effect=OSError("unlock sentinel")), patch(
            "core.control_plane.os.lseek", return_value=0
        ), patch("core.control_plane.os.close", return_value=None):
            with self.assertRaisesRegex(ControlPlaneIOError, "unlock sentinel"):
                lock.release()
        self.assertIsNone(lock.descriptor)
        self.assertFalse(lock.locked)

        lock.descriptor = 790
        lock.locked = True
        with patch(unlock_target, side_effect=OSError("first sentinel")), patch(
            "core.control_plane.os.lseek", return_value=0
        ), patch("core.control_plane.os.close", side_effect=OSError("second sentinel")):
            with self.assertRaisesRegex(ControlPlaneIOError, "first sentinel"):
                lock.release()
        self.assertEqual(lock.descriptor, 790)
        self.assertTrue(lock.locked)
        with patch(unlock_target, return_value=None), patch(
            "core.control_plane.os.lseek", return_value=0
        ), patch("core.control_plane.os.close", return_value=None):
            lock.release()
        self.assertIsNone(lock.descriptor)
        self.assertFalse(lock.locked)

        lock.descriptor = 791
        lock.locked = True
        with patch(unlock_target, return_value=None), patch(
            "core.control_plane.os.lseek", return_value=0
        ), patch("core.control_plane.os.close", side_effect=OSError("close sentinel")):
            with self.assertRaisesRegex(ControlPlaneIOError, "close sentinel"):
                lock.release()
        self.assertEqual(lock.descriptor, 791)
        self.assertFalse(lock.locked)
        with patch("core.control_plane.os.close", return_value=None):
            lock.release()
        self.assertIsNone(lock.descriptor)

    def test_existing_mission_memory_and_config_are_never_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protected = {
                root / "memory" / "onyx_missions.sqlite3": b"mission sentinel bytes",
                root / "memory" / "onyx_memory.sqlite3": b"memory sentinel bytes",
                root / "config" / "api_keys.json": b'{"nonsecret":true}\n',
            }
            for path, payload in protected.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            before = {path: hashlib.sha256(path.read_bytes()).digest() for path in protected}
            sidecar = root / "runtime" / "control_plane.sqlite3"
            real_connect = sqlite3.connect
            real_open = builtins.open
            connected: list[str] = []
            opened: list[str] = []

            def tracked_connect(database, *args, **kwargs):
                connected.append(os.fspath(database))
                return real_connect(database, *args, **kwargs)

            def tracked_open(file, *args, **kwargs):
                opened.append(os.fspath(file))
                return real_open(file, *args, **kwargs)

            with patch("core.control_plane.sqlite3.connect", side_effect=tracked_connect), patch(
                "builtins.open", side_effect=tracked_open
            ):
                with make_control_plane_store(sidecar):
                    pass
            forbidden = {os.fspath(path) for path in protected}
            self.assertTrue(forbidden.isdisjoint(connected))
            self.assertTrue(forbidden.isdisjoint(opened))
            for path in protected:
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before[path])

    def test_main_startup_does_not_import_or_open_control_plane(self):
        main_source = (Path(__file__).resolve().parents[1] / "main.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("core.control_plane", main_source)
        self.assertNotIn("core.workspaces", main_source)
        self.assertNotIn("ControlPlaneStore", main_source)

    def test_only_explicit_true_values_enable_environment_flag(self):
        for value in ("true", "TRUE", " true ", "1", " 1 "):
            self.assertTrue(control_plane_v1_enabled({CONTROL_PLANE_FLAG: value}))
        for value in ("", "false", "yes", "on", "enabled", "garbage", "0"):
            self.assertFalse(control_plane_v1_enabled({CONTROL_PLANE_FLAG: value}))


if __name__ == "__main__":
    unittest.main()
