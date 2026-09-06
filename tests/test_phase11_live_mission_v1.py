import asyncio
import hashlib
import hmac
import json
import os
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import core.phase11_live_mission_v1 as live_module
from core import native_vault
from core import missions as mission_module
from core.missions import MissionStore, worker_once
from core.permission_broker import set_permission_callback
from core.phase11_live_mission_v1 import (
    BINDING_SCHEMA,
    Phase11LifecycleError,
    Phase11LiveMissionError,
    Phase11LiveMissionV1,
)
from core.phase11_windows_clone_cleanup_v1 import (
    CloneCleanupContractError,
    CloneCleanupWaiting,
)


KEY = b"p" * 32
DOMAIN = b"ONYX/PHASE11/LIVE-BINDING/V1\0"


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    ).stdout


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def _resign(document):
    payload = {
        key: value
        for key, value in document.items()
        if key not in {"binding_digest", "signature"}
    }
    digest = hashlib.sha256(_canonical(payload)).hexdigest()
    document["binding_digest"] = digest
    document["signature"] = hmac.new(
        KEY, DOMAIN + digest.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return document


class MemoryVault:
    def __init__(self):
        self.value = None
        self.fail_set = False

    def get_bytes(self):
        return self.value

    def set_bytes(self, value):
        if self.fail_set:
            raise RuntimeError("injected anchor write failure")
        self.value = bytes(value)


class AnchorVaults:
    def __init__(self):
        self.vaults = {}

    def __call__(self, reference):
        return self.vaults.setdefault(reference.account, MemoryVault())


class Phase11LiveMissionV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "onyx-tests@invalid.local")
        _git(self.root, "config", "user.name", "Onyx Tests")
        (self.root / "project.txt").write_bytes(b"TODO verify phase 11\n")
        _git(self.root, "add", "project.txt")
        _git(self.root, "commit", "-qm", "initial")
        self.store = MissionStore(self.base / "missions.sqlite3")
        self.bindings = self.base / "phase11"
        self.anchors = AnchorVaults()
        self.bridge = Phase11LiveMissionV1(
            self.store,
            binding_dir=self.bindings,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=self.anchors,
        )
        set_permission_callback(lambda request: request["digest"])

    def tearDown(self):
        set_permission_callback(None)
        self.bridge.close()
        self.tmp.cleanup()

    def create(self, **kwargs):
        values = {
            "title": "Inspect this project",
            "workspace_root": str(self.root),
            "query": "TODO",
        }
        values.update(kwargs)
        return self.bridge.create(**values)

    def binding_path(self, mission_id):
        return self.bindings / f"{mission_id}.binding.json"

    def execute(self, mission_id):
        with patch.dict(os.environ, {"ONYX_WORKSPACE_ROOTS": str(self.root)}):
            return worker_once(
                self.store, "phase11-test", self.bridge.runner, lease_seconds=5
            )

    def test_fixed_binding_live_run_status_and_legacy_parity(self):
        mission = self.create()
        binding = json.loads(self.binding_path(mission.id).read_text())
        self.assertEqual(binding["schema"], BINDING_SCHEMA)
        self.assertEqual(
            [step["tool"] for step in binding["fixed_steps"]],
            ["local_system_status", "workspace_inventory", "workspace_text_search"],
        )
        self.assertEqual(
            binding["plan_digest"],
            self.store.plan_summary(mission.id)["plan_digest"],
        )
        events = self.store.events(mission.id)
        bound = next(item for item in events if item["event"] == "phase11.bound")
        self.assertEqual(
            bound["detail"]["binding_digest"], binding["binding_digest"]
        )
        self.bridge.approve(mission.id)
        self.assertEqual(self.execute(mission.id).state, "succeeded")
        status = self.bridge.status(mission.id)
        self.assertEqual(status["state"], "succeeded")
        self.assertEqual(status["verdict"], "PASS")

        legacy = self.store.create(
            "Legacy", [{"tool": "local_note", "args": {"text": "ok"}}]
        )
        self.store.approve(legacy.id)
        self.assertEqual(
            worker_once(self.store, "legacy", self.bridge.runner).state,
            "succeeded",
        )
        self.assertFalse(self.bridge.is_phase11(legacy.id))

    def test_default_off_has_zero_directory_or_vault_side_effects(self):
        target = self.base / "must-not-exist" / "bindings"

        class ForbiddenVault:
            def get_bytes(self):
                raise AssertionError("vault touched while disabled")

            def set_bytes(self, _secret):
                raise AssertionError("vault touched while disabled")

        disabled = Phase11LiveMissionV1(
            self.store,
            binding_dir=target,
            allowed_roots=(self.root,),
            enabled=False,
            key_vault=ForbiddenVault(),
            anchor_vault_factory=self.anchors,
        )
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(Phase11LiveMissionError, "disabled"):
            disabled.status("mis_" + "0" * 32)
        self.assertFalse(target.exists())

    @unittest.skipUnless(os.name == "nt", "Windows startup retry contract")
    def test_windows_binding_startup_retries_only_transient_busy(self):
        candidate = object.__new__(Phase11LiveMissionV1)
        candidate.binding_dir = self.base / "retry-bindings"
        candidate._windows_binding_boundary = None
        boundary = MagicMock()
        with (
            patch(
                "core.phase11_windows_namespace_v1.WindowsTrustedDirectoryV1",
                side_effect=(
                    CloneCleanupWaiting("cleanup_root_handle_busy"),
                    CloneCleanupWaiting("cleanup_root_handle_busy"),
                    boundary,
                ),
            ) as trusted,
            patch.object(live_module.time, "sleep") as sleep,
            patch.object(live_module, "_harden_mode"),
        ):
            candidate._prepare_directory()
        self.assertIs(candidate._windows_binding_boundary, boundary)
        self.assertEqual(trusted.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [0.05, 0.1],
        )

    @unittest.skipUnless(os.name == "nt", "Windows startup race contract")
    def test_concurrent_fresh_binding_create_converges_without_degradation(self):
        import core.phase11_windows_namespace_v1 as namespace_module

        target = self.base / "concurrent-fresh-bindings"
        barrier = threading.Barrier(4)
        original_child = namespace_module._child_handle
        bridges = []
        errors = []

        def synchronized_create(parent, name, **kwargs):
            if name == target.name and kwargs.get("create") is True:
                barrier.wait(5)
            return original_child(parent, name, **kwargs)

        def construct(index: int) -> None:
            try:
                bridges.append(
                    Phase11LiveMissionV1(
                        MissionStore(self.base / f"race-{index}.sqlite3"),
                        binding_dir=target,
                        allowed_roots=(self.root,),
                        enabled=True,
                        key=KEY,
                        anchor_vault_factory=AnchorVaults(),
                    )
                )
            except BaseException as exc:
                errors.append(exc)

        with patch.object(
            namespace_module,
            "_child_handle",
            side_effect=synchronized_create,
        ):
            threads = [
                threading.Thread(target=construct, args=(index,))
                for index in range(4)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)

        try:
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(len(bridges), 4)
            identities = {
                bridge._windows_binding_boundary.root_identity.file_id
                for bridge in bridges
            }
            self.assertEqual(len(identities), 1)
        finally:
            for bridge in bridges:
                bridge.close()

    @unittest.skipUnless(os.name == "nt", "Windows constructor rollback contract")
    def test_failed_constructor_releases_boundary_and_authority_immediately(self):
        import core.phase11_windows_namespace_v1 as namespace_module

        target = self.base / "failed-constructor-bindings"
        failed_store = MissionStore(self.base / "failed-constructor.sqlite3")
        captured_boundaries = []
        captured_capabilities = []
        trusted_directory = namespace_module.WindowsTrustedDirectoryV1
        register_capability = native_vault._register_phase11_anchor_capability

        def capture_boundary(**kwargs):
            boundary = trusted_directory(**kwargs)
            captured_boundaries.append(boundary)
            return boundary

        def capture_capability(capability, owner):
            captured_capabilities.append(capability)
            register_capability(capability, owner)

        with (
            patch.object(
                namespace_module,
                "WindowsTrustedDirectoryV1",
                side_effect=capture_boundary,
            ),
            patch.object(
                native_vault,
                "_register_phase11_anchor_capability",
                side_effect=capture_capability,
            ),
            patch.object(
                live_module,
                "ProjectAutopilotV1",
                side_effect=RuntimeError(
                    "injected post-boundary initialization failure"
                ),
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "injected post-boundary initialization failure",
            ),
        ):
            Phase11LiveMissionV1(
                failed_store,
                binding_dir=target,
                allowed_roots=(self.root,),
                enabled=True,
                key=KEY,
                autopilot_enabled=True,
            )

        self.assertEqual(len(captured_boundaries), 1)
        self.assertTrue(captured_boundaries[0]._closed)
        self.assertIsNone(captured_boundaries[0].root)
        self.assertIsNone(captured_boundaries[0].parent)
        self.assertIsNone(failed_store._phase11_authority_owner)
        self.assertEqual(len(captured_capabilities), 1)
        self.assertFalse(
            native_vault._phase11_anchor_capability_valid(
                captured_capabilities[0]
            )
        )

        recovered = Phase11LiveMissionV1(
            failed_store,
            binding_dir=target,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=AnchorVaults(),
        )
        recovered.close()

    @unittest.skipUnless(os.name == "nt", "Windows startup boundary")
    def test_windows_binding_busy_fails_startup_instead_of_binding_worker(self):
        with (
            patch(
                "core.phase11_windows_namespace_v1.WindowsTrustedDirectoryV1",
                side_effect=CloneCleanupWaiting("cleanup_root_handle_busy"),
            ),
            patch.object(
                live_module,
                "_WINDOWS_BINDING_STARTUP_TIMEOUT_SECONDS",
                0.0,
            ),
            self.assertRaisesRegex(
                Phase11LiveMissionError,
                "phase11_binding_transient_busy",
            ),
        ):
            Phase11LiveMissionV1(
                self.store,
                binding_dir=self.base / "busy-bindings",
                allowed_roots=(self.root,),
                enabled=True,
                key=KEY,
                anchor_vault_factory=self.anchors,
                governed_away_enabled=True,
            )

    @unittest.skipUnless(os.name == "nt", "Windows startup boundary")
    def test_windows_binding_acl_contract_fails_startup_visibly(self):
        with (
            patch(
                "core.phase11_windows_namespace_v1.WindowsTrustedDirectoryV1",
                side_effect=CloneCleanupContractError(
                    "phase11_trusted_directory_unavailable"
                ),
            ),
            self.assertRaisesRegex(
                Phase11LiveMissionError,
                "phase11_binding_acl_or_namespace_invalid",
            ),
        ):
            Phase11LiveMissionV1(
                self.store,
                binding_dir=self.base / "acl-bindings",
                allowed_roots=(self.root,),
                enabled=True,
                key=KEY,
                anchor_vault_factory=self.anchors,
                governed_away_enabled=True,
            )

    @unittest.skipUnless(os.name == "posix", "POSIX permission contract")
    def test_posix_directory_and_binding_modes_are_private(self):
        mission = self.create()
        self.assertEqual(stat.S_IMODE(self.bindings.stat().st_mode), 0o700)
        self.assertEqual(
            stat.S_IMODE(self.binding_path(mission.id).stat().st_mode), 0o600
        )

    def test_model_cannot_choose_tools_and_budget_is_zero(self):
        with self.assertRaises(Phase11LiveMissionError):
            self.create(
                supplied_steps=[
                    {"tool": "workspace_read_text", "args": {"path": "project.txt"}}
                ]
            )
        for kwargs in (
            {"max_steps": 4},
            {"max_seconds": 0},
            {"max_retries": 3},
            {"provider_cost_limit": 0.01},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.create(**kwargs)
        self.assertEqual(self.store.list(), [])

    def test_binding_swap_replay_recompute_and_event_mismatch_fail_closed(self):
        first = self.create(title="First")
        second = self.create(title="Second")
        first_bytes = self.binding_path(first.id).read_bytes()
        second_path = self.binding_path(second.id)
        second_path.write_bytes(first_bytes)
        with self.assertRaises(Phase11LiveMissionError):
            self.bridge.status(second.id)

        first_path = self.binding_path(first.id)
        document = json.loads(first_path.read_text())
        document["fixed_steps"][0]["args"] = {"forged": True}
        first_path.write_bytes(_canonical(_resign(document)))
        with self.assertRaisesRegex(Phase11LiveMissionError, "authority|plan"):
            self.bridge.status(first.id)

        third = self.create(title="Third")
        connection = self.store._connect()
        try:
            connection.execute(
                "UPDATE events SET detail=detail WHERE mission_id=?", (third.id,)
            )
        except Exception:
            pass
        finally:
            connection.close()
        binding = json.loads(self.binding_path(third.id).read_text())
        binding["signature"] = "0" * 64
        self.binding_path(third.id).write_bytes(_canonical(binding))
        with self.assertRaises(Phase11LiveMissionError):
            self.bridge.status(third.id)

    def test_current_plan_tool_args_and_key_tamper_each_fail(self):
        mutations = (
            ("tool", "workspace_hash"),
            ("args", json.dumps({"root": str(self.root), "query": "forged"})),
            ("idempotency_key", "0" * 64),
        )
        for column, value in mutations:
            with self.subTest(column=column):
                mission = self.create(title=f"Tamper {column}")
                connection = self.store._connect()
                try:
                    connection.execute(
                        f"UPDATE steps SET {column}=? "
                        "WHERE mission_id=? AND position=0",
                        (value, mission.id),
                    )
                finally:
                    connection.close()
                with self.assertRaisesRegex(Exception, "plan|contract|diverges"):
                    self.bridge.status(mission.id)

    def test_descriptor_bound_read_detects_path_swap_toctou(self):
        mission = self.create()
        path = self.binding_path(mission.id)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        if os.name == "nt":
            import core.phase11_windows_namespace_v1 as namespace_module

            original_read = namespace_module._read_regular_handle
            swap_denied = False

            def swap_while_held(handle, max_bytes):
                nonlocal swap_denied
                with self.assertRaises(PermissionError):
                    os.replace(replacement, path)
                swap_denied = True
                return original_read(handle, max_bytes)

            with patch.object(
                namespace_module,
                "_read_regular_handle",
                side_effect=swap_while_held,
            ):
                self.bridge.status(mission.id)
            self.assertTrue(swap_denied)
            return
        original_open = os.open
        swapped = False

        def swap_then_open(target, flags, *args):
            nonlocal swapped
            if Path(target) == path and not swapped and not (flags & os.O_WRONLY):
                swapped = True
                os.replace(replacement, path)
            return original_open(target, flags, *args)

        with patch("core.phase11_live_mission_v1.os.open", side_effect=swap_then_open):
            with self.assertRaisesRegex(Phase11LiveMissionError, "changed"):
                self.bridge.status(mission.id)
        self.assertTrue(swapped)

    @unittest.skipUnless(os.name == "nt", "Windows artifact contract")
    def test_encrypted_patch_artifact_identity_tag_aad_and_hold(self):
        mission_id = "mis_" + "a" * 32
        patch_text = "diff --git a/a.txt b/a.txt\n+ONYX_SECRET_STAGE_D\n"
        patch_bytes = patch_text.encode("utf-8")
        patch_sha256 = hashlib.sha256(patch_bytes).hexdigest()
        reference = self.bridge._write_patch_artifact(
            mission_id, patch_text, patch_sha256
        )
        document = {
            "mission_id": mission_id,
            "patch_artifact": reference,
            "autopilot": {"patch_sha256": patch_sha256},
        }
        path = self.bindings / reference["name"]
        ciphertext = path.read_bytes()
        self.assertNotIn(patch_bytes, ciphertext)
        self.assertEqual(
            self.bridge._read_patch_artifact(document), patch_text
        )

        wrong_aad = json.loads(json.dumps(document))
        wrong_aad["autopilot"]["patch_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "decryption"
        ):
            self.bridge._read_patch_artifact(wrong_aad)

        corrupted = bytearray(ciphertext)
        corrupted[-1] ^= 1
        path.write_bytes(corrupted)
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "authentication"
        ):
            self.bridge._read_patch_artifact(document)
        path.write_bytes(ciphertext)

        replacement = path.with_name("replacement.aesgcm")
        replacement.write_bytes(ciphertext)
        original_decrypt = self.bridge._decrypt_patch_artifact
        denied = False

        def replace_during_decrypt(*args):
            nonlocal denied
            with self.assertRaises(PermissionError):
                os.replace(replacement, path)
            denied = True
            return original_decrypt(*args)

        with patch.object(
            self.bridge,
            "_decrypt_patch_artifact",
            side_effect=replace_during_decrypt,
        ):
            self.assertEqual(
                self.bridge._read_patch_artifact(document), patch_text
            )
        self.assertTrue(denied)

        path.unlink()
        sentinel = self.base / "external-sentinel"
        sentinel.write_bytes(ciphertext)
        os.link(sentinel, path)
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "changed"
        ):
            self.bridge._read_patch_artifact(document)
        self.assertEqual(sentinel.read_bytes(), ciphertext)

    def test_drift_and_dirty_bytes_are_preserved(self):
        dirty = self.root / "dirty.bin"
        dirty.write_bytes(b"\x00\xfflocal bytes")
        before = dirty.read_bytes()
        mission = self.create()
        (self.root / "project.txt").write_bytes(b"external drift\n")
        with self.assertRaisesRegex(Phase11LiveMissionError, "drift"):
            self.bridge.approve(mission.id)
        status = self.bridge.status(mission.id)
        self.assertEqual(status["state"], "waiting")
        self.assertEqual(status["verdict"], "DRIFT")
        self.assertEqual(dirty.read_bytes(), before)

    def test_kill_after_runner_discards_late_result_and_restart_remembers(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        original = self.bridge.base_runner

        def kill_after_result(tool, args, key):
            result = original(tool, args, key)
            self.bridge.request_kill(mission.id)
            return result

        self.bridge.base_runner = kill_after_result
        result = self.execute(mission.id)
        self.assertEqual(result.state, "waiting")
        self.assertNotIn(
            "step.succeeded",
            [event["event"] for event in self.store.events(mission.id)],
        )
        restarted = Phase11LiveMissionV1(
            MissionStore(self.store.path),
            binding_dir=self.bindings,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=self.anchors,
        )
        self.assertEqual(restarted.status(mission.id)["reason"], "kill_requested")
        restarted.close()

    def test_kill_polling_uses_only_reconciled_event_fast_path(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        self.bridge._validate_current_binding(
            mission.id, reconcile_kill=True
        )
        state = self.bridge._kill_state(mission.id)
        state.next_durable_check = float("inf")
        with (
            patch.object(self.store, "events", wraps=self.store.events) as events,
            patch.object(
                self.store,
                "authority_snapshot",
                wraps=self.store.authority_snapshot,
            ) as snapshots,
            patch.object(
                self.store,
                "phase11_authority_view_v1",
                wraps=self.store.phase11_authority_view_v1,
            ) as authority_views,
        ):
            for _ in range(2_000):
                self.assertFalse(self.bridge._is_killed(mission.id, state))
        self.assertEqual(events.call_count, 0)
        self.assertEqual(snapshots.call_count, 0)
        self.assertEqual(authority_views.call_count, 0)

    def test_kill_sets_event_immediately_after_durable_append(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        self.bridge._validate_current_binding(
            mission.id, reconcile_kill=True
        )
        state = self.bridge._kill_state(mission.id)
        with patch.object(
            self.store,
            "events",
            side_effect=AssertionError("hot kill path read full history"),
        ):
            self.assertTrue(self.bridge.request_kill(mission.id))
            self.assertTrue(self.bridge._is_killed(mission.id, state))
        self.assertTrue(state.event.is_set())

    def test_runner_reconciles_persisted_kill_before_tool_start(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        self.assertTrue(self.bridge.request_kill(mission.id))
        restarted = Phase11LiveMissionV1(
            MissionStore(self.store.path),
            binding_dir=self.bindings,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=self.anchors,
            base_runner=lambda *_args: self.fail(
                "persisted kill reached the tool runner"
            ),
        )
        with patch.dict(os.environ, {"ONYX_WORKSPACE_ROOTS": str(self.root)}):
            result = worker_once(
                restarted.store,
                "phase11-kill-restart",
                restarted.runner,
                lease_seconds=5,
            )
        self.assertEqual(result.state, "waiting")
        self.assertTrue(restarted._kill_state(mission.id).event.is_set())
        restarted.close()

    def test_kill_fast_path_capacity_fails_closed_without_eviction(self):
        with patch(
            "core.phase11_live_mission_v1._MAX_KILL_FAST_PATH_ENTRIES", 1
        ):
            retained = self.bridge._kill_state(
                "mis_" + "1" * 32, "1" * 64
            )
            with self.assertRaisesRegex(
                Phase11LiveMissionError, "capacity is exhausted"
            ):
                self.bridge._kill_state(
                    "mis_" + "2" * 32, "2" * 64
                )
        self.assertIs(
            self.bridge._kill_state("mis_" + "1" * 32),
            retained,
        )

    def test_authority_high_water_capacity_fails_closed_without_eviction(
        self,
    ):
        existing = "mis_" + "e" * 32
        candidate = "mis_" + "f" * 32
        with live_module._PROCESS_HIGH_WATER_LOCK:
            saved = dict(live_module._PROCESS_HIGH_WATER)
            live_module._PROCESS_HIGH_WATER.clear()
            live_module._PROCESS_HIGH_WATER[existing] = (1, "a" * 64)
        try:
            with patch.object(
                live_module,
                "_MAX_PROCESS_HIGH_WATER_ENTRIES",
                1,
            ):
                with self.assertRaisesRegex(
                    Phase11LiveMissionError, "capacity"
                ):
                    self.bridge._write_anchor(
                        SimpleNamespace(
                            mission_id=candidate,
                            event_seq=1,
                            event_hash="b" * 64,
                        )
                    )
            self.assertEqual(
                live_module._PROCESS_HIGH_WATER,
                {existing: (1, "a" * 64)},
            )
            self.assertNotIn(candidate, self.anchors.vaults)
        finally:
            with live_module._PROCESS_HIGH_WATER_LOCK:
                live_module._PROCESS_HIGH_WATER.clear()
                live_module._PROCESS_HIGH_WATER.update(saved)

    @unittest.skipUnless(os.name == "nt", "Windows named Event contract")
    def test_named_event_cross_bridge_kill_stops_active_autopilot(self):
        binding_dir = self.base / "named-event-bridges"
        shared_store = MissionStore(self.store.path)
        bridge_a = Phase11LiveMissionV1(
            shared_store,
            binding_dir=binding_dir,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=self.anchors,
            autopilot_enabled=True,
        )
        bridge_b = Phase11LiveMissionV1(
            MissionStore(self.store.path),
            binding_dir=binding_dir,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=self.anchors,
            autopilot_enabled=True,
        )
        patch_text = """diff --git a/project.txt b/project.txt
--- a/project.txt
+++ b/project.txt
@@ -1 +1 @@
-TODO verify phase 11
+verified phase 11
"""
        mission = bridge_a.create_autopilot(
            title="Named Event kill",
            workspace_root=str(self.root),
            patch=patch_text,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=30,
        )
        bridge_a.approve(mission.id)
        binding = bridge_a._read_binding(mission.id)
        exact = binding["fixed_steps"][0]
        started = threading.Event()
        result = {}

        def wait_for_kill(**arguments):
            started.set()
            deadline = time.monotonic() + 3
            while not arguments["cancel"]():
                if time.monotonic() >= deadline:
                    return {"status": "succeeded"}
                time.sleep(0.005)
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": "kill_requested",
            }

        def run_a():
            result["value"] = bridge_a.runner(
                exact["tool"],
                exact["args"],
                exact["idempotency_key"],
            )

        bridge_a.autopilot.execute = wait_for_kill
        worker = threading.Thread(target=run_a)
        worker.start()
        self.assertTrue(started.wait(2))
        self.assertTrue(bridge_b.request_kill(mission.id))
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result["value"]["status"], "waiting")
        state_a = bridge_a._kill_state(mission.id)
        state_b = bridge_b._kill_state(mission.id)
        self.assertIsNot(state_a.kernel, state_b.kernel)
        self.assertEqual(state_a.kernel.name, state_b.kernel.name)
        bridge_a.close()
        bridge_b.close()
        self.assertTrue(state_a.kernel._closed)
        self.assertTrue(state_b.kernel._closed)

    @unittest.skipUnless(os.name == "nt", "Windows named Event contract")
    def test_named_event_signal_crosses_real_process_boundary(self):
        name = (
            "Local\\Onyx.Phase11.Kill."
            + hashlib.sha256(os.urandom(32)).hexdigest()
        )
        event = live_module._WindowsNamedKillEvent(name)
        child_source = (
            "import sys,time\n"
            "from core.phase11_live_mission_v1 import _WindowsNamedKillEvent\n"
            "event=_WindowsNamedKillEvent(sys.argv[1])\n"
            "print('ready',flush=True)\n"
            "deadline=time.monotonic()+5\n"
            "while time.monotonic()<deadline and not event.is_set():"
            " time.sleep(0.01)\n"
            "seen=event.is_set()\n"
            "event.close()\n"
            "raise SystemExit(0 if seen else 3)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", child_source, name],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            event.set()
            _stdout, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, stderr)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
            event.close()

    @unittest.skipUnless(os.name == "nt", "Windows named Event contract")
    def test_durable_kill_marker_covers_crash_before_set_event(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        self.bridge._validate_current_binding(
            mission.id, reconcile_kill=True
        )
        state = self.bridge._kill_state(mission.id)
        state.next_durable_check = 0
        other = Phase11LiveMissionV1(
            MissionStore(self.store.path),
            binding_dir=self.bindings,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=self.anchors,
        )
        other._validate_current_binding(mission.id, reconcile_kill=True)
        other._authority_event(
            mission.id,
            "phase11.kill",
            {"reason": "owner_cancel_requested"},
        )
        other.store.cancel(mission.id)
        other._write_anchor(other.store.authority_snapshot(mission.id))
        with (
            patch.object(self.store, "events", wraps=self.store.events) as events,
            patch.object(
                self.store,
                "authority_phase11_kill_marker_v1",
                wraps=self.store.authority_phase11_kill_marker_v1,
            ) as markers,
        ):
            outcome = (
                "waiting"
                if self.bridge._is_killed(mission.id, state)
                else "succeeded"
            )
        self.assertEqual(outcome, "waiting")
        self.assertEqual(events.call_count, 0)
        self.assertEqual(markers.call_count, 1)
        other.close()

    @unittest.skipUnless(os.name == "nt", "Windows named Event contract")
    def test_benign_worker_head_ahead_of_anchor_is_not_a_kill(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        self.bridge._validate_current_binding(
            mission.id, reconcile_kill=True
        )
        anchor = json.loads(self.anchors.vaults[mission.id].value)
        self.assertEqual(
            self.store.claim_next("head-ahead", lease_seconds=5),
            mission.id,
        )
        current = self.store.authority_snapshot(mission.id)
        self.assertGreater(current.event_seq, anchor["event_seq"])
        state = self.bridge._kill_state(mission.id)
        state.next_durable_check = 0
        self.assertFalse(self.bridge._is_killed(mission.id, state))
        self.assertFalse(state.event.is_set())
        self.assertFalse(state.kernel.is_set())

    @unittest.skipUnless(os.name == "nt", "Windows named Event contract")
    def test_signed_kill_after_append_before_anchor_is_detected(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        self.bridge._validate_current_binding(
            mission.id, reconcile_kill=True
        )
        anchor_before = bytes(self.anchors.vaults[mission.id].value)
        signed = self.bridge._sign_authority_detail(
            mission.id,
            "phase11.kill",
            {"reason": "owner_cancel_requested"},
        )
        self.store.append_authority_event_v1(
            mission.id,
            "phase11.kill",
            signed,
            capability=self.bridge._authority_capability,
        )
        self.assertEqual(self.anchors.vaults[mission.id].value, anchor_before)
        state = self.bridge._kill_state(mission.id)
        state.next_durable_check = 0
        self.assertTrue(self.bridge._is_killed(mission.id, state))
        self.assertTrue(state.kernel.is_set())

    def test_missionstore_success_commit_quarantines_authenticated_kill(self):
        mission = self.create()
        self.bridge.approve(mission.id)

        def killed_success(*_args):
            self.bridge._authority_event(
                mission.id,
                "phase11.kill",
                {"reason": "owner_cancel_requested"},
            )
            return {
                "status": "succeeded",
                "data": {"late": True},
                "evidence": [],
                "postconditions": [
                    {"name": "late_result", "satisfied": True}
                ],
                "waiting_for": None,
            }

        result = self.store.run(
            mission.id, killed_success, backoff=lambda _seconds: None
        )
        self.assertEqual(result.state, "waiting")
        events = self.store.events(mission.id)
        kill_seq = next(
            event["seq"]
            for event in events
            if event["event"] == "phase11.kill"
        )
        terminal_events = [
            event["event"] for event in events if event["seq"] > kill_seq
        ]
        self.assertEqual(terminal_events, ["step.waiting"])
        self.assertNotIn("step.succeeded", terminal_events)
        self.assertNotIn("mission.succeeded", terminal_events)
        connection = self.store._connect()
        try:
            step = connection.execute(
                "SELECT state,result,wait_reason FROM steps "
                "WHERE mission_id=? AND position=0",
                (mission.id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(step["state"], "waiting")
        self.assertEqual(json.loads(step["result"])["waiting_for"], "kill_requested")
        self.assertIn("late success discarded", step["wait_reason"])

    @unittest.skipUnless(os.name == "nt", "Windows named Event contract")
    def test_close_waits_for_read_only_runner_before_handle_teardown(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        binding = self.bridge._validate_current_binding(
            mission.id, reconcile_kill=True
        )
        exact = binding["fixed_steps"][0]
        entered = threading.Event()
        release = threading.Event()
        outcome = {}

        def blocked_success(*_args):
            entered.set()
            self.assertTrue(release.wait(5))
            return {
                "status": "succeeded",
                "data": {"ok": True},
                "evidence": [],
                "postconditions": [
                    {"name": "runner_completed", "satisfied": True}
                ],
                "waiting_for": None,
            }

        def run():
            outcome["result"] = self.bridge.runner(
                exact["tool"], exact["args"], exact["idempotency_key"]
            )

        self.bridge.base_runner = blocked_success
        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(entered.wait(5))
        close_outcome = {}

        def close_bridge():
            try:
                self.bridge.close(5.0)
                close_outcome["closed"] = True
            except BaseException as exc:
                close_outcome["error"] = exc

        closer = threading.Thread(target=close_bridge)
        closer.start()
        time.sleep(0.1)
        self.assertTrue(closer.is_alive())
        release.set()
        thread.join(5)
        closer.join(5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertNotIn("error", close_outcome)
        self.assertTrue(close_outcome["closed"])
        self.assertEqual(outcome["result"]["status"], "succeeded")
        self.bridge.close()

    def test_close_aggregates_independent_failures_and_attempts_every_boundary(self):
        events = []

        class Away:
            def active_missions(self):
                events.append("away.active")
                return ()

            def stop_all_for_shutdown(self):
                events.append("away.stop")
                return {"failures": ["injected"]}

            def close(self):
                events.append("away.close")
                raise OSError("away close failed")

        class External:
            def active_missions(self):
                events.append("external.active")
                return ()

            def close(self):
                events.append("external.close")
                raise RuntimeError("external close failed")

        class Autopilot:
            def has_active_processes(self):
                events.append("autopilot.active")
                return True

        class Boundary:
            def close(self):
                events.append("boundary.close")
                raise PermissionError("boundary close failed")

        candidate = object.__new__(Phase11LiveMissionV1)
        candidate._lock = threading.RLock()
        candidate._closed = False
        candidate._closing = False
        candidate._kill_states = {}
        candidate.away_mode = Away()
        candidate.external_agent = External()
        candidate.autopilot = Autopilot()
        candidate._windows_binding_boundary = Boundary()

        with self.assertRaises(Phase11LifecycleError) as raised:
            candidate.close(0.01)

        self.assertEqual(len(raised.exception.failures), 5)
        self.assertIn("away.close", events)
        self.assertIn("external.close", events)
        self.assertIn("boundary.close", events)
        self.assertFalse(candidate._closed)
        self.assertTrue(candidate._closing)

    def test_close_retains_failed_native_handle_and_can_be_retried(self):
        events = []

        class Kernel:
            attempts = 0
            _closed = False

            def close(self):
                self.attempts += 1
                events.append(f"kernel.close.{self.attempts}")
                if self.attempts == 1:
                    raise OSError("transient close failure")
                self._closed = True

        class Boundary:
            def close(self):
                events.append("boundary.close")

        candidate = object.__new__(Phase11LiveMissionV1)
        candidate._lock = threading.RLock()
        candidate._closed = False
        candidate._closing = False
        state = live_module._KillState(kernel=Kernel())
        candidate._kill_states = {"mis_test": state}
        candidate.away_mode = None
        candidate.external_agent = None
        candidate.autopilot = None
        candidate._windows_binding_boundary = Boundary()

        with self.assertRaises(Phase11LifecycleError) as raised:
            candidate.close(0.01)
        self.assertEqual(len(raised.exception.failures), 1)
        self.assertIsNotNone(state.kernel)
        self.assertIsNotNone(candidate._windows_binding_boundary)

        candidate.close(0.01)
        self.assertEqual(
            events,
            ["kernel.close.1", "kernel.close.2", "boundary.close"],
        )
        self.assertIsNotNone(state.kernel)
        self.assertEqual(state.kernel.attempts, 2)
        self.assertIsNone(candidate._windows_binding_boundary)
        self.assertTrue(candidate._closed)

    @unittest.skipUnless(os.name == "nt", "Windows named Event contract")
    def test_named_event_close_failure_remains_retryable(self):
        event = object.__new__(live_module._WindowsNamedKillEvent)
        event._guard = threading.Lock()
        event._readers = 0
        event._closing = False
        event._closed = False
        event._handle = 123

        with patch.object(
            live_module._kernel32,
            "CloseHandle",
            side_effect=(False, True),
        ) as close_handle:
            with self.assertRaises(OSError):
                event.close()
            self.assertFalse(event._closed)
            self.assertFalse(event._closing)
            event.close()

        self.assertEqual(close_handle.call_count, 2)
        self.assertTrue(event._closed)
        self.assertFalse(event._closing)

    @unittest.skipUnless(os.name == "nt", "Windows named Event contract")
    def test_named_event_wrong_security_and_wait_failure_fail_closed(self):
        mission = self.create()
        binding = self.bridge._read_binding(mission.id)
        name = self.bridge._kill_event_name(
            mission.id, binding["binding_digest"]
        )
        handle = live_module._kernel32.CreateEventExW(
            None,
            name,
            1,
            live_module._SYNCHRONIZE
            | live_module._EVENT_MODIFY_STATE
            | live_module._READ_CONTROL,
        )
        self.assertTrue(handle)
        try:
            with self.assertRaisesRegex(
                Phase11LiveMissionError, "security"
            ):
                self.bridge._validate_current_binding(
                    mission.id, reconcile_kill=True
                )
        finally:
            self.assertTrue(live_module._kernel32.CloseHandle(handle))

        second = self.create(title="WAIT_FAILED mission")
        self.bridge._validate_current_binding(
            second.id, reconcile_kill=True
        )
        state = self.bridge._kill_state(second.id)
        with patch.object(
            live_module._kernel32,
            "WaitForSingleObject",
            return_value=0xFFFFFFFF,
        ):
            self.assertTrue(self.bridge._is_killed(second.id, state))

    @unittest.skipUnless(os.name == "nt", "Windows named Event contract")
    def test_named_event_identity_is_bound_and_non_disclosing(self):
        first = self.create(title="First event identity")
        second = self.create(title="Second event identity")
        first_binding = self.bridge._read_binding(first.id)
        second_binding = self.bridge._read_binding(second.id)
        first_name = self.bridge._kill_event_name(
            first.id, first_binding["binding_digest"]
        )
        same_name = self.bridge._kill_event_name(
            first.id, first_binding["binding_digest"]
        )
        second_name = self.bridge._kill_event_name(
            second.id, second_binding["binding_digest"]
        )
        self.assertEqual(first_name, same_name)
        self.assertNotEqual(first_name, second_name)
        self.assertNotIn(first.id, first_name)
        self.assertNotIn(first_binding["binding_digest"], first_name)
        self.bridge._validate_current_binding(
            first.id, reconcile_kill=True
        )
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "binding diverges"
        ):
            self.bridge._kill_state(first.id, "0" * 64)

    def test_status_is_least_disclosure_and_receipts_only_in_events(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        status = self.bridge.status(mission.id)
        encoded = json.dumps(status)
        binding = json.loads(self.binding_path(mission.id).read_text())
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn(binding["signature"], encoded)
        self.assertNotIn(binding["binding_digest"], encoded)
        self.assertEqual(len(status["receipt"]["baseline_digest_prefix"]), 12)
        self.assertEqual(len(status["receipt"]["observed_digest_prefix"]), 12)
        self.assertNotIn("receipts", binding)
        self.assertTrue(
            any(
                event["event"] == "phase11.receipt"
                for event in self.store.events(mission.id)
            )
        )

    def test_live_dispatch_cancel_calls_kill_before_store_cancel(self):
        import main as runtime_module

        class UI:
            muted = True
            current_file = None

            def set_state(self, *_args):
                pass

        runtime = runtime_module.OnyxLive.__new__(runtime_module.OnyxLive)
        runtime.ui = UI()
        runtime._missions = self.store
        runtime._phase11_missions = self.bridge
        mission = self.create()

        async def call(name, args, identity):
            return await runtime._execute_tool(
                SimpleNamespace(name=name, args=args, id=identity)
            )

        with patch.object(runtime_module, "append_tool_audit"):
            response = asyncio.run(
                call("mission_cancel", {"mission_id": mission.id}, "cancel")
            )
        self.assertEqual(response.response["result"]["state"], "cancelled")
        names = [event["event"] for event in self.store.events(mission.id)]
        self.assertLess(names.index("phase11.kill"), names.index("mission.cancelled"))

    def test_fresh_reapproval_schema_matches_mission_run_dispatch(self):
        import main as runtime_module

        declarations = {
            declaration["name"]: declaration
            for declaration in runtime_module.TOOL_DECLARATIONS
        }
        run_properties = declarations["mission_run"]["parameters"]["properties"]
        status_properties = declarations["mission_status"]["parameters"]["properties"]
        self.assertEqual(run_properties["fresh_reapproval"], {"type": "BOOLEAN"})
        self.assertNotIn("fresh_reapproval", status_properties)

        class UI:
            muted = True
            current_file = None

            def set_state(self, *_args):
                pass

        runtime = runtime_module.OnyxLive.__new__(runtime_module.OnyxLive)
        runtime.ui = UI()
        runtime._missions = self.store
        runtime._phase11_missions = self.bridge
        mission = self.create()
        replacement = SimpleNamespace(
            id="mis_" + "f" * 32,
            state="awaiting_approval",
        )
        call = SimpleNamespace(
            name="mission_run",
            args={"mission_id": mission.id, "fresh_reapproval": True},
            id="fresh-reapproval",
        )
        with (
            patch.object(runtime_module, "append_tool_audit"),
            patch.object(self.bridge, "reseed_autopilot", return_value=replacement),
        ):
            response = asyncio.run(runtime._execute_tool(call))
        self.assertEqual(
            response.response["result"],
            {
                "mission_id": replacement.id,
                "state": "awaiting_approval",
                "queued": False,
                "fresh_owner_approval_required": True,
            },
        )

    def test_authority_head_tamper_fails_before_binding_validation(self):
        mission = self.create()
        connection = self.store._connect()
        try:
            connection.execute(
                "UPDATE event_heads SET row_sha256=? WHERE mission_id=?",
                ("0" * 64, mission.id),
            )
        finally:
            connection.close()
        with self.assertRaisesRegex(Exception, "authority event head diverges"):
            self.bridge.status(mission.id)

    def test_forged_public_receipt_and_kill_appends_require_bound_capability(self):
        mission = self.create()
        anchor_before = bytes(self.anchors.vaults[mission.id].value)
        for event, detail in (
            (
                "phase11.receipt",
                {
                    "stage": "before_approve",
                    "verdict": "PASS",
                    "reason": "forged",
                    "baseline_sha256": "0" * 64,
                    "observed_sha256": "0" * 64,
                    "receipt_signature": "0" * 64,
                },
            ),
            ("phase11.kill", {"reason": "owner_cancel_requested"}),
        ):
            with self.subTest(event=event), self.assertRaises(PermissionError):
                self.store.append_authority_event_v1(
                    mission.id,
                    event,
                    detail,
                    capability=object(),
                )
        with self.assertRaisesRegex(Phase11LiveMissionError, "receipt"):
            self.store.append_authority_event_v1(
                mission.id,
                "phase11.receipt",
                {
                    "stage": "before_approve",
                    "schema": "onyx.phase11.verification_receipt.v1",
                    "root": str(self.root),
                    "baseline_sha256": "0" * 64,
                    "observed_sha256": "0" * 64,
                    "verdict": "PASS",
                    "reason": "forged",
                    "issued_at_ns": 1,
                    "receipt_signature": "0" * 64,
                },
                capability=self.bridge._authority_capability,
            )
        with self.assertRaisesRegex(Phase11LiveMissionError, "kill"):
            self.store.append_authority_event_v1(
                mission.id,
                "phase11.kill",
                {"reason": "forged"},
                capability=self.bridge._authority_capability,
            )
        self.assertEqual(self.anchors.vaults[mission.id].value, anchor_before)
        self.assertEqual(
            [
                event["event"]
                for event in self.store.events(mission.id)
                if event["event"].startswith("phase11.")
            ],
            ["phase11.bound"],
        )

    def test_arbitrary_owner_cannot_issue_phase11_append_capability(self):
        self.assertFalse(hasattr(self.store, "_PHASE11_AUTHORITY_ISSUER_SEAL"))

        class FakeBridge:
            def validate(self, *_args):
                pass

        FakeBridge.__module__ = "core.phase11_live_mission_v1"
        FakeBridge.__name__ = "Phase11LiveMissionV1"
        fake = FakeBridge()
        self.assertFalse(
            hasattr(mission_module, "_PHASE11_AUTHORITY_ISSUER_SEAL")
        )
        with self.assertRaises(PermissionError):
            self.store._issue_phase11_authority_capability_v1(
                fake,
                fake.validate,
            )

    def test_status_never_advances_anchor_over_invalid_phase11_event(self):
        mission = self.create()
        anchor_before = bytes(self.anchors.vaults[mission.id].value)
        checkpoint_account = f"{mission.id}.checkpoint"
        checkpoint_before = bytes(
            self.anchors.vaults[checkpoint_account].value
        )
        connection = self.store._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self.store._event(
                connection,
                mission.id,
                "phase11.receipt",
                {
                    "stage": "before_approve",
                    "schema": "forged",
                    "root": str(self.root),
                    "baseline_sha256": "0" * 64,
                    "observed_sha256": "0" * 64,
                    "verdict": "PASS",
                    "reason": "forged",
                    "issued_at_ns": 1,
                    "receipt_signature": "0" * 64,
                },
            )
            connection.execute("COMMIT")
        finally:
            connection.close()
        with self.assertRaisesRegex(Phase11LiveMissionError, "receipt"):
            self.bridge.status(mission.id)
        self.assertEqual(self.anchors.vaults[mission.id].value, anchor_before)
        self.assertEqual(
            self.anchors.vaults[checkpoint_account].value,
            checkpoint_before,
        )

    def test_native_phase11_vault_namespaces_require_opaque_capability(self):
        self.assertFalse(
            hasattr(native_vault, "_issue_anchor_namespace_capability")
        )
        for reference in (
            self.bridge._anchor_reference("mis_" + "a" * 32),
            self.bridge._checkpoint_reference("mis_" + "a" * 32),
        ):
            with self.subTest(service=reference.service), self.assertRaisesRegex(
                native_vault.NativeVaultError, "Protected anchor"
            ):
                native_vault.NativeSecretVault(reference, system="Windows")

    def test_native_anchor_rejects_coherent_database_rollback(self):
        mission = self.create()
        old_database = self.base / "pre-approval.sqlite3"
        source = sqlite3.connect(self.store.path)
        destination = sqlite3.connect(old_database)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        self.bridge.approve(mission.id)
        advanced_anchor = self.anchors.vaults[mission.id].value
        self.assertIsNotNone(advanced_anchor)

        source = sqlite3.connect(old_database)
        destination = sqlite3.connect(self.store.path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        restarted = Phase11LiveMissionV1(
            MissionStore(self.store.path),
            binding_dir=self.bindings,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=self.anchors,
        )
        with self.assertRaisesRegex(Phase11LiveMissionError, "rolled back"):
            restarted.status(mission.id)
        restarted.close()

    def test_replayed_older_signed_anchor_is_rejected_by_checkpoint(self):
        mission = self.create()
        old_anchor = bytes(self.anchors.vaults[mission.id].value)
        self.bridge.approve(mission.id)
        self.anchors.vaults[mission.id].value = old_anchor
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "replay|checkpoint divergence"
        ):
            self.bridge.status(mission.id)

    def test_replayed_older_anchor_and_checkpoint_pair_is_rejected_in_process(self):
        mission = self.create()
        checkpoint_account = f"{mission.id}.checkpoint"
        old_anchor = bytes(self.anchors.vaults[mission.id].value)
        old_checkpoint = bytes(
            self.anchors.vaults[checkpoint_account].value
        )
        self.bridge.approve(mission.id)
        self.anchors.vaults[mission.id].value = old_anchor
        self.anchors.vaults[checkpoint_account].value = old_checkpoint
        restarted = Phase11LiveMissionV1(
            MissionStore(self.store.path),
            binding_dir=self.bindings,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=self.anchors,
        )
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "coordinated anchor replay|high-water"
        ):
            restarted.status(mission.id)
        restarted.close()

    def test_rollback_between_receipt_and_native_approval_is_rejected(self):
        mission = self.create()
        pre_approval_database = self.base / "receipt-before-approval.sqlite3"
        original_approve = self.store.approve

        def capture_then_approve(mission_id):
            source = sqlite3.connect(self.store.path)
            destination = sqlite3.connect(pre_approval_database)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            return original_approve(mission_id)

        with patch.object(self.store, "approve", side_effect=capture_then_approve):
            self.bridge.approve(mission.id)
        self.assertEqual(self.store.get(mission.id).state, "running")

        source = sqlite3.connect(pre_approval_database)
        destination = sqlite3.connect(self.store.path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        restarted = Phase11LiveMissionV1(
            MissionStore(self.store.path),
            binding_dir=self.bindings,
            allowed_roots=(self.root,),
            enabled=True,
            key=KEY,
            anchor_vault_factory=self.anchors,
        )
        with self.assertRaisesRegex(Phase11LiveMissionError, "rolled back"):
            restarted.status(mission.id)
        restarted.close()

    def test_kill_anchor_failure_leaves_memory_clean_and_retry_persists(self):
        mission = self.create()
        vault = self.anchors.vaults[mission.id]
        vault.fail_set = True
        with self.assertRaisesRegex(Phase11LiveMissionError, "could not be persisted"):
            self.bridge.request_kill(mission.id)
        self.assertFalse(
            self.bridge._kill_state(mission.id).event.is_set()
        )
        self.assertTrue(
            any(
                event["event"] == "phase11.kill"
                for event in self.store.events(mission.id)
            )
        )

        vault.fail_set = False
        self.assertFalse(self.bridge.request_kill(mission.id))
        self.assertTrue(
            self.bridge._kill_state(mission.id).event.is_set()
        )
        anchor = json.loads(vault.value)
        self.assertEqual(
            anchor["event_seq"], self.store.authority_snapshot(mission.id).event_seq
        )

    def test_checkpoint_half_write_is_repaired_without_regression(self):
        mission = self.create()
        checkpoint_account = f"{mission.id}.checkpoint"
        checkpoint_vault = self.anchors.vaults[checkpoint_account]
        checkpoint_vault.fail_set = True
        with self.assertRaisesRegex(Phase11LiveMissionError, "checkpoint"):
            self.bridge.request_kill(mission.id)
        anchor = json.loads(self.anchors.vaults[mission.id].value)
        checkpoint = json.loads(checkpoint_vault.value)
        self.assertGreater(anchor["event_seq"], checkpoint["event_seq"])
        self.assertFalse(
            self.bridge._kill_state(mission.id).event.is_set()
        )

        checkpoint_vault.fail_set = False
        status = self.bridge.status(mission.id)
        self.assertEqual(status["reason"], "kill_requested")
        repaired_anchor = json.loads(self.anchors.vaults[mission.id].value)
        repaired_checkpoint = json.loads(checkpoint_vault.value)
        self.assertEqual(
            (repaired_anchor["event_seq"], repaired_anchor["event_hash"]),
            (
                repaired_checkpoint["event_seq"],
                repaired_checkpoint["event_hash"],
            ),
        )
        self.assertEqual(
            repaired_anchor["event_seq"],
            self.store.authority_snapshot(mission.id).event_seq,
        )

    def test_concurrent_anchor_writers_cannot_overwrite_newer_authority(self):
        mission = self.create()
        older = self.store.authority_snapshot(mission.id)
        self.store.cancel(mission.id)
        newer = self.store.authority_snapshot(mission.id)
        self.assertGreater(newer.event_seq, older.event_seq)

        anchor_vault = self.anchors.vaults[mission.id]
        original_set = anchor_vault.set_bytes
        older_written = threading.Event()
        release_older = threading.Event()
        blocked = False

        def blocking_set(value):
            nonlocal blocked
            document = json.loads(bytes(value))
            original_set(value)
            if document["event_seq"] == older.event_seq and not blocked:
                blocked = True
                older_written.set()
                self.assertTrue(release_older.wait(timeout=5))

        anchor_vault.set_bytes = blocking_set
        failures = []

        def write(snapshot):
            try:
                self.bridge._write_anchor(snapshot)
            except BaseException as exc:
                failures.append(exc)

        older_thread = threading.Thread(target=write, args=(older,))
        newer_thread = threading.Thread(target=write, args=(newer,))
        older_thread.start()
        self.assertTrue(older_written.wait(timeout=5))
        newer_thread.start()
        self.assertTrue(newer_thread.is_alive())
        release_older.set()
        older_thread.join(timeout=5)
        newer_thread.join(timeout=5)
        self.assertFalse(older_thread.is_alive())
        self.assertFalse(newer_thread.is_alive())
        self.assertEqual(failures, [])

        anchor = json.loads(anchor_vault.value)
        checkpoint = json.loads(
            self.anchors.vaults[f"{mission.id}.checkpoint"].value
        )
        self.assertEqual(anchor["event_seq"], newer.event_seq)
        self.assertEqual(checkpoint["event_seq"], newer.event_seq)
        self.assertEqual(anchor["event_hash"], newer.event_hash)
        self.assertEqual(checkpoint["event_hash"], newer.event_hash)

    def test_concurrent_kill_wins_before_after_tool_receipt_commit(self):
        mission = self.create()
        self.bridge.approve(mission.id)
        original_record = self.bridge._record_receipt
        injected = False

        def kill_before_after_receipt(mission_id, receipt, stage):
            nonlocal injected
            if stage.startswith("after_tool:") and not injected:
                injected = True
                self.bridge.request_kill(mission_id)
            return original_record(mission_id, receipt, stage)

        with patch.object(
            self.bridge,
            "_record_receipt",
            side_effect=kill_before_after_receipt,
        ):
            result = self.execute(mission.id)
        self.assertTrue(injected)
        self.assertEqual(result.state, "waiting")
        phase_events = [
            event["event"]
            for event in self.store.events(mission.id)
            if event["event"].startswith("phase11.")
        ]
        self.assertEqual(phase_events[-1], "phase11.kill")
        self.assertNotIn(
            "step.succeeded",
            [event["event"] for event in self.store.events(mission.id)],
        )
        self.assertEqual(self.bridge.status(mission.id)["reason"], "kill_requested")

    def test_cancel_still_runs_when_phase11_kill_anchor_write_fails(self):
        import main as runtime_module

        class UI:
            muted = True
            current_file = None

            def set_state(self, *_args):
                pass

        runtime = runtime_module.OnyxLive.__new__(runtime_module.OnyxLive)
        runtime.ui = UI()
        runtime._missions = self.store
        runtime._phase11_missions = self.bridge
        mission = self.create()
        self.anchors.vaults[mission.id].fail_set = True

        async def call():
            return await runtime._execute_tool(
                SimpleNamespace(
                    name="mission_cancel",
                    args={"mission_id": mission.id},
                    id="cancel-anchor-failure",
                )
            )

        with patch.object(runtime_module, "append_tool_audit"):
            response = asyncio.run(call())
        self.assertEqual(
            response.response["result"],
            "Mission operation failed safely. Inspect the local mission status and audit events.",
        )
        self.assertEqual(self.store.get(mission.id).state, "cancelled")
        self.assertFalse(
            self.bridge._kill_state(mission.id).event.is_set()
        )
        names = [event["event"] for event in self.store.events(mission.id)]
        self.assertLess(names.index("phase11.kill"), names.index("mission.cancelled"))

    def test_linked_workspace_root_is_rejected_before_resolution(self):
        linked = self.base / "linked-root"
        try:
            linked.symlink_to(self.root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory links unavailable: {exc}")
        with self.assertRaisesRegex(Phase11LiveMissionError, "linked|reparse"):
            Phase11LiveMissionV1(
                self.store,
                binding_dir=self.base / "other-bindings",
                allowed_roots=(linked,),
                enabled=True,
                key=KEY,
                anchor_vault_factory=self.anchors,
            )

    def test_no_network_and_rollback_failure_is_observable(self):
        with (
            patch.object(socket, "socket", side_effect=AssertionError("network used")),
            patch.object(
                socket, "create_connection", side_effect=AssertionError("network used")
            ),
        ):
            mission = self.create(title="Offline")
            self.bridge.approve(mission.id)
            self.assertEqual(self.execute(mission.id).state, "succeeded")

        with (
            patch.object(
                self.bridge,
                "_write_binding_once",
                side_effect=OSError("primary failure"),
            ),
            patch.object(
                self.store,
                "cancel",
                side_effect=RuntimeError("rollback failure"),
            ),
        ):
            with self.assertRaisesRegex(
                Phase11LiveMissionError, "rollback cancellation failed"
            ):
                self.create(title="Rollback")


if __name__ == "__main__":
    unittest.main()
