from __future__ import annotations

import json
import inspect
import os
import stat
import tempfile
import unittest
from pathlib import Path
import subprocess
from unittest.mock import patch

import core.phase11_windows_clone_cleanup_v1 as cleanup_module
from core.phase11_windows_clone_cleanup_v1 import (
    CloneCleanupContractError,
    CloneCleanupWaiting,
    CleanupLimitsV1,
    WindowsCloneCleanupV1,
    feature_enabled,
)


MISSION = "mis_" + ("a" * 32)
BINDING = "b" * 64
ENVELOPE = "e" * 64
OWNER_SHA = "1" * 64


class MemoryVault:
    def __init__(self) -> None:
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)


class FailOnceVault(MemoryVault):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def set_bytes(self, value: bytes | bytearray) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected vault write failure")
        super().set_bytes(value)


@unittest.skipUnless(os.name == "nt", "Windows-only cleanup contract")
class WindowsCloneCleanupV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.base = base
        self.control = base / "control"
        self.mission = self.control / MISSION
        self.clone = self.mission / "clone"
        self.owner = base / "owner"
        self.clone.mkdir(parents=True)
        self.owner.mkdir()
        (self.clone / "payload.txt").write_bytes(b"payload")
        self.vaults: dict[str, MemoryVault] = {}
        self.engine = WindowsCloneCleanupV1(
            worktree_root=self.control,
            signing_key=b"k" * 32,
            vault_factory=lambda reference: self.vaults.setdefault(
                reference.account, MemoryVault()
            ),
            enabled=True,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reserved_windows_components_include_console_and_superscripts(
        self,
    ) -> None:
        refused = (
            "CON",
            "con.txt",
            "CONIN$",
            "conout$.log",
            "COM1",
            "LPT9.dat",
            "COM¹",
            "com².txt",
            "LPT³",
            "name.",
            "name ",
        )
        for name in refused:
            with self.subTest(name=name):
                self.assertFalse(cleanup_module._valid_component(name))
        self.assertTrue(cleanup_module._valid_component("company.txt"))
        self.assertTrue(cleanup_module._valid_component("output.log"))

    def provenance(self) -> dict[str, object]:
        staging = self.base / "clone-staging"
        if staging.exists():
            raise AssertionError("staging already exists")
        if self.clone.exists():
            self.clone.rename(staging)
        self.prepare()
        if staging.exists():
            for child in tuple(staging.iterdir()):
                child.rename(self.clone / child.name)
            staging.rmdir()
        return self.engine.finalize_provenance(
            mission_id=MISSION,
            binding_digest=BINDING,
            envelope_digest=ENVELOPE,
            owner_root=self.owner,
            clone_root=self.clone,
            owner_git_sha256=OWNER_SHA,
        )

    def authenticate(self) -> dict[str, object]:
        return self.engine.authenticate_provenance(
            mission_id=MISSION,
            binding_digest=BINDING,
            envelope_digest=ENVELOPE,
            owner_root=self.owner,
            clone_root=self.clone,
            owner_git_sha256=OWNER_SHA,
        )

    def prepare(self, *, fault_hook=None) -> dict[str, object]:
        return self.engine.prepare_provenance(
            mission_id=MISSION,
            binding_digest=BINDING,
            envelope_digest=ENVELOPE,
            owner_root=self.owner,
            clone_root=self.clone,
            owner_git_sha256=OWNER_SHA,
            fault_hook=fault_hook,
        )

    def make_clone_destination_absent(self) -> None:
        (self.clone / "payload.txt").unlink()
        self.clone.rmdir()

    def cleanup(
        self,
        *,
        fault_hook=None,
        checkpoint=None,
        transitions=None,
    ) -> bool:
        if checkpoint is None:
            checkpoint = {
                "stage": "verified",
                "mission_id": MISSION,
                "binding_digest": BINDING,
                "owner_git_sha256": OWNER_SHA,
            }
        if transitions is None:
            transitions = []
        return self.engine.cleanup(
            mission_id=MISSION,
            binding_digest=BINDING,
            envelope_digest=ENVELOPE,
            owner_root=self.owner,
            clone_root=self.clone,
            owner_git_sha256=OWNER_SHA,
            terminal_state="succeeded",
            checkpoint=checkpoint,
            owner_validator=lambda: None,
            checkpoint_writer=lambda stage, digest: transitions.append(
                (stage, digest)
            ),
            fault_hook=fault_hook,
        )

    def _assert_finalized_terminal_stage_cleanup(
        self, stage: str
    ) -> None:
        self.provenance()
        transitions: list[tuple[str, str | None]] = []
        self.assertTrue(
            self.cleanup(
                checkpoint={
                    "stage": stage,
                    "mission_id": MISSION,
                    "binding_digest": BINDING,
                    "owner_git_sha256": OWNER_SHA,
                },
                transitions=transitions,
            )
        )
        self.assertFalse(self.clone.exists())
        self.assertEqual(transitions[-1][0], "cleaned")
        self.assertRegex(
            str(transitions[-1][1]), r"^[0-9a-f]{64}$"
        )

    def test_patch_applied_terminal_checkpoint_cleans_finalized_clone(
        self,
    ) -> None:
        self._assert_finalized_terminal_stage_cleanup("patch_applied")

    def test_gates_running_terminal_checkpoint_cleans_finalized_clone(
        self,
    ) -> None:
        self._assert_finalized_terminal_stage_cleanup("gates_running")

    def test_default_off_and_exact_true_flag(self) -> None:
        self.assertFalse(feature_enabled({}))
        self.assertFalse(
            feature_enabled(
                {cleanup_module.FEATURE_FLAG: "True"}
            )
        )
        self.assertTrue(
            feature_enabled(
                {cleanup_module.FEATURE_FLAG: "true"}
            )
        )

    def test_provenance_binds_hmac_vault_nonce_and_file_id(self) -> None:
        created = self.provenance()
        authenticated = self.authenticate()
        self.assertEqual(created, authenticated)
        self.assertEqual(created["mission_id"], MISSION)
        self.assertEqual(created["binding_digest"], BINDING)
        self.assertEqual(created["envelope_digest"], ENVELOPE)
        self.assertEqual(len(str(created["nonce"])), 64)
        clone = created["clone_root"]
        assert isinstance(clone, dict)
        identity = clone["identity"]
        assert isinstance(identity, dict)
        self.assertEqual(len(str(identity["file_id"])), 32)
        self.assertTrue(
            str(identity["volume_guid"])
            .casefold()
            .startswith("\\\\?\\volume{")
        )

    def test_legacy_clone_without_provenance_is_refused(self) -> None:
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "provenance_anchor_missing",
        ):
            self.authenticate()

    def test_provenance_file_tamper_is_refused(self) -> None:
        self.provenance()
        path = self.mission / "clone.cleanup.provenance.slot0.v1.json"
        document = json.loads(path.read_bytes())
        document["payload"]["binding_digest"] = "f" * 64
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "document_tampered|anchor_mismatch",
        ):
            self.authenticate()

    def test_vault_anchor_tamper_is_refused(self) -> None:
        self.provenance()
        vault = next(iter(self.vaults.values()))
        assert vault.value is not None
        anchor = json.loads(vault.value)
        anchor["payload"]["nonce"] = "0" * 64
        vault.value = json.dumps(anchor).encode()
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "document_tampered|anchor_mismatch",
        ):
            self.authenticate()

    def test_replay_creation_is_refused(self) -> None:
        self.provenance()
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "legacy_create_provenance_disabled",
        ):
            self.engine.create_provenance()

    def test_swapped_clone_identity_is_refused(self) -> None:
        self.provenance()
        original = self.mission / "original"
        self.clone.rename(original)
        self.clone.mkdir()
        with self.assertRaisesRegex(
            CloneCleanupContractError, "identity_mismatch"
        ):
            self.authenticate()

    def test_alternate_data_stream_is_refused_by_manifest(self) -> None:
        self.provenance()
        with open(f"{self.clone / 'payload.txt'}:hidden", "wb") as stream:
            stream.write(b"secret")
        with cleanup_module._root_handle(
            self.clone, exclusive=False
        ) as root:
            with self.assertRaisesRegex(
                CloneCleanupContractError, "alternate_data_stream"
            ):
                self.engine._manifest_payload(
                    mission_id=MISSION,
                    nonce="0" * 64,
                    root=root,
                    started=self.engine._clock(),
                )

    def test_hardlink_is_refused_by_manifest(self) -> None:
        self.provenance()
        os.link(
            self.clone / "payload.txt",
            self.clone / "payload-link.txt",
        )
        with cleanup_module._root_handle(
            self.clone, exclusive=False
        ) as root:
            with self.assertRaisesRegex(
                CloneCleanupContractError, "hardlink"
            ):
                self.engine._manifest_payload(
                    mission_id=MISSION,
                    nonce="0" * 64,
                    root=root,
                    started=self.engine._clock(),
                )

    def test_real_rename_disposition_final_proof_and_idempotency(self) -> None:
        self.provenance()
        transitions: list[tuple[str, str | None]] = []
        self.assertTrue(self.cleanup(transitions=transitions))
        self.assertFalse(self.clone.exists())
        self.assertFalse(
            any(path.name.startswith(".onyx-cleanup-") for path in self.mission.iterdir())
        )
        self.assertEqual(transitions[-1][0], "cleaned")
        self.assertFalse(self.cleanup(transitions=transitions))

    def test_handle_relative_unicode_long_metadata_rename(self) -> None:
        name = "résumé-" + ("x" * 80) + ".json"
        with self.engine._mission_handles(MISSION) as (
            _worktree,
            mission,
        ):
            self.engine._metadata_write(mission, name, b"payload")
            self.assertEqual(
                self.engine._metadata_read(mission, name), b"payload"
            )
            before = {
                row_name
                for row_name, _is_dir, _attrs in cleanup_module._directory_rows(
                    mission
                )
            }
            self.assertIn(name, before)
            self.engine._metadata_delete(mission, name)

    def test_normal_8dot3_alias_presence_does_not_block_manifest(self) -> None:
        (self.clone / "ordinary-long-filename-for-alias.txt").write_bytes(b"x")
        self.provenance()
        with cleanup_module._root_handle(
            self.clone, exclusive=False
        ) as root:
            manifest = self.engine._manifest_payload(
                mission_id=MISSION,
                nonce="0" * 64,
                root=root,
                started=self.engine._clock(),
            )
        logical = {
            row["logical"]
            for row in manifest["entries"]
            if isinstance(row, dict)
        }
        self.assertIn("ordinary-long-filename-for-alias.txt", logical)

    def test_mission_junction_swap_is_refused(self) -> None:
        self.provenance()
        moved = self.control / f"{MISSION}-moved"
        attacker = self.control / "attacker"
        attacker.mkdir()
        self.mission.rename(moved)
        completed = subprocess.run(
            [
                "cmd",
                "/c",
                "mklink",
                "/J",
                str(self.mission),
                str(attacker),
            ],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self.skipTest("junction creation unavailable")
        with self.assertRaisesRegex(
            CloneCleanupContractError, "reparse_point"
        ):
            self.authenticate()

    def test_fault_injection_recovery_every_destructive_seam(self) -> None:
        seams = (
            "after_cleanup_planned",
            "after_tombstone_rename",
            "before_entry:payload.txt",
            "after_entry:payload.txt",
            "before_root_disposition",
            "after_cleaned_anchor",
        )
        for index, seam in enumerate(seams):
            with self.subTest(seam=seam):
                if index:
                    self.clone.mkdir()
                    (self.clone / "payload.txt").write_bytes(b"payload")
                    self.vaults.clear()
                self.provenance()
                fired = False

                def fault(point: str) -> None:
                    nonlocal fired
                    if point == seam and not fired:
                        fired = True
                        raise RuntimeError(f"fault:{point}")

                with self.assertRaisesRegex(RuntimeError, "fault:"):
                    self.cleanup(fault_hook=fault)
                self.assertTrue(fired)
                self.cleanup()
                self.assertFalse(self.clone.exists())
                self.assertFalse(
                    any(
                        path.name.startswith(".onyx-cleanup-")
                        for path in self.mission.iterdir()
                    )
                )

    def test_open_file_waits_then_recovers_after_handle_closes(self) -> None:
        self.provenance()
        stream = (self.clone / "payload.txt").open("rb")
        try:
            with self.assertRaisesRegex(
                CloneCleanupWaiting,
                "handle_busy|delete_waiting|rename_waiting",
            ):
                self.cleanup()
        finally:
            stream.close()
        self.assertTrue(self.cleanup())
        self.assertFalse(self.clone.exists())

    def test_handle_close_retries_when_closehandle_itself_fails(self) -> None:
        handle = cleanup_module._root_handle(
            self.base,
            exclusive=False,
        )
        original_close_handle = cleanup_module._kernel32.CloseHandle
        attempts = 0

        def fail_inside_closehandle(value: int) -> int:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return 0
            return original_close_handle(value)

        with patch.object(
            cleanup_module._kernel32,
            "CloseHandle",
            side_effect=fail_inside_closehandle,
        ):
            with self.assertRaises(OSError):
                handle.close()
            self.assertFalse(handle.closed)
            handle.close()

        self.assertEqual(attempts, 2)
        self.assertTrue(handle.closed)

    def test_tombstone_collision_is_no_replace_and_sentinel_survives(self) -> None:
        provenance = self.provenance()
        tombstone = self.mission / (
            f".onyx-cleanup-{str(provenance['nonce'])[:16]}"
        )
        tombstone.mkdir()
        sentinel = tombstone / "sentinel.txt"
        sentinel.write_bytes(b"do-not-touch")
        with self.assertRaisesRegex(
            CloneCleanupWaiting, "destination_exists"
        ):
            self.cleanup()
        self.assertEqual(sentinel.read_bytes(), b"do-not-touch")
        sentinel.unlink()
        tombstone.rmdir()
        self.assertTrue(self.cleanup())

    def test_case_variant_tombstone_collision_preserves_sentinel(self) -> None:
        provenance = self.provenance()
        tombstone_name = (
            f".onyx-cleanup-{str(provenance['nonce'])[:16]}"
        )
        case_variant = self.mission / tombstone_name.upper()
        case_variant.mkdir()
        sentinel = case_variant / "sentinel.txt"
        sentinel.write_bytes(b"case-variant-do-not-touch")
        with self.assertRaisesRegex(
            CloneCleanupWaiting, "destination_exists"
        ):
            self.cleanup()
        self.assertEqual(
            sentinel.read_bytes(), b"case-variant-do-not-touch"
        )

    def test_disposition_failure_is_fail_closed_and_retryable(self) -> None:
        self.provenance()
        original = self.engine._dispose
        fired = False

        def fail_once(handle) -> None:
            nonlocal fired
            if not fired:
                fired = True
                raise CloneCleanupContractError(
                    "cleanup_disposition_unsupported:50"
                )
            original(handle)

        self.engine._dispose = fail_once
        with self.assertRaisesRegex(
            CloneCleanupContractError, "disposition_unsupported"
        ):
            self.cleanup()
        self.engine._dispose = original
        self.assertTrue(self.cleanup())

    def test_lazy_quota_stops_before_opening_over_limit_entry(self) -> None:
        (self.clone / "second.txt").write_bytes(b"2")
        (self.clone / "third.txt").write_bytes(b"3")
        limited = WindowsCloneCleanupV1(
            worktree_root=self.control,
            signing_key=b"k" * 32,
            vault_factory=lambda reference: self.vaults.setdefault(
                reference.account, MemoryVault()
            ),
            enabled=True,
            limits=CleanupLimitsV1(max_files=1),
        )
        original = cleanup_module._child_handle
        opened_files: list[str] = []

        def counted(parent, name, **kwargs):
            if not kwargs["directory"]:
                opened_files.append(name)
            return original(parent, name, **kwargs)

        with cleanup_module._root_handle(
            self.clone, exclusive=False
        ) as root, patch.object(
            cleanup_module, "_child_handle", side_effect=counted
        ):
            with self.assertRaisesRegex(
                CloneCleanupContractError, "manifest_quota"
            ):
                limited._manifest_payload(
                    mission_id=MISSION,
                    nonce="0" * 64,
                    root=root,
                    started=limited._clock(),
                )
        self.assertEqual(len(opened_files), 1)

    def test_nested_git_like_tree_is_deleted_in_strict_postorder(self) -> None:
        nested_file = self.clone / ".git" / "objects" / "ab" / ("c" * 38)
        nested_file.parent.mkdir(parents=True)
        nested_file.write_bytes(b"object")
        ref = self.clone / ".git" / "refs" / "heads" / "main"
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b"deadbeef")
        source = self.clone / "src" / "package" / "module.py"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"VALUE = 1\n")
        self.provenance()
        original = self.engine._delete_entry
        order: list[str] = []

        def recording(root, row, **kwargs):
            order.append(str(row["logical"]))
            return original(root, row, **kwargs)

        self.engine._delete_entry = recording
        try:
            self.assertTrue(self.cleanup())
        finally:
            self.engine._delete_entry = original
        self.assertFalse(self.clone.exists())
        positions = {name: index for index, name in enumerate(order)}
        self.assertLess(
            positions[f".git/objects/ab/{'c' * 38}"],
            positions[".git/objects/ab"],
        )
        self.assertLess(
            positions[".git/objects/ab"], positions[".git/objects"]
        )
        self.assertLess(positions[".git/objects"], positions[".git"])
        self.assertLess(
            positions["src/package/module.py"], positions["src/package"]
        )
        self.assertLess(positions["src/package"], positions["src"])

    def test_owner_resolved_inside_worktree_is_refused(self) -> None:
        inside = self.control / "owner-inside"
        inside.mkdir()
        with self.assertRaisesRegex(
            CloneCleanupContractError, "roots_overlap"
        ):
            self.engine.prepare_provenance(
                mission_id=MISSION,
                binding_digest=BINDING,
                envelope_digest=ENVELOPE,
                owner_root=inside,
                clone_root=self.clone,
                owner_git_sha256=OWNER_SHA,
            )

    def test_owner_resolved_ancestor_of_worktree_is_refused(self) -> None:
        ancestor = self.control.parent
        with self.assertRaisesRegex(
            CloneCleanupContractError, "roots_overlap"
        ):
            self.engine.prepare_provenance(
                mission_id=MISSION,
                binding_digest=BINDING,
                envelope_digest=ENVELOPE,
                owner_root=ancestor,
                clone_root=self.clone,
                owner_git_sha256=OWNER_SHA,
            )

    def test_owner_junction_alias_into_clone_is_refused(self) -> None:
        target = self.clone / "junction-owner"
        target.mkdir()
        self.owner.rmdir()
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(self.owner), str(target)],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self.skipTest("junction creation unavailable")
        with self.assertRaisesRegex(
            CloneCleanupContractError, "reparse_point|roots_overlap"
        ):
            self.provenance()

    def test_postscan_ancestor_junction_swap_is_refused(self) -> None:
        nested = self.clone / "nested"
        nested.mkdir()
        (nested / "child.txt").write_bytes(b"inside")
        attacker = self.mission.parent / "attacker-tree"
        attacker.mkdir()
        sentinel = attacker / "sentinel.txt"
        sentinel.write_bytes(b"outside")
        self.provenance()

        def stop_after_manifest(point: str) -> None:
            if point == "after_cleanup_planned":
                raise RuntimeError("stop after manifest")

        with self.assertRaisesRegex(RuntimeError, "stop after manifest"):
            self.cleanup(fault_hook=stop_after_manifest)
        original = self.clone / "nested-original"
        nested.rename(original)
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(nested), str(attacker)],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self.skipTest("junction creation unavailable")
        with self.assertRaisesRegex(
            CloneCleanupContractError, "reparse_point|ancestor_identity"
        ):
            self.cleanup()
        self.assertEqual(sentinel.read_bytes(), b"outside")

    def test_first_attempt_external_truncation_is_refused(self) -> None:
        self.provenance()

        def stop_after_manifest(point: str) -> None:
            if point == "after_cleanup_planned":
                raise RuntimeError("stop after manifest")

        with self.assertRaisesRegex(RuntimeError, "stop after manifest"):
            self.cleanup(fault_hook=stop_after_manifest)
        (self.clone / "payload.txt").write_bytes(b"")
        with self.assertRaisesRegex(
            CloneCleanupContractError, "entry_size_changed"
        ):
            self.cleanup()

    def test_provenance_vault_failure_rolls_forward_exact_file(self) -> None:
        account = f"prov-{MISSION}"
        failing = FailOnceVault()
        self.vaults[account] = failing
        self.make_clone_destination_absent()
        with self.assertRaisesRegex(RuntimeError, "vault write failure"):
            self.prepare()
        provenance_path = (
            self.mission / "clone.cleanup.provenance.slot0.v1.json"
        )
        first_bytes = provenance_path.read_bytes()
        recovered = self.prepare()
        self.assertEqual(first_bytes, provenance_path.read_bytes())
        self.assertEqual(recovered["state"], "prepared")

    def test_cleaned_receipt_refuses_recreated_clone_name(self) -> None:
        self.provenance()
        self.assertTrue(self.cleanup())
        self.clone.mkdir()
        (self.clone / "attacker.txt").write_bytes(b"sentinel")
        with self.assertRaisesRegex(
            CloneCleanupContractError, "cleaned_absence_violated"
        ):
            self.cleanup()
        self.assertEqual(
            (self.clone / "attacker.txt").read_bytes(), b"sentinel"
        )

    def test_preintent_crash_before_clone_recovers_to_exact_empty_dir(self) -> None:
        self.make_clone_destination_absent()

        def fault(point: str) -> None:
            if point == "after_clone_intent":
                raise RuntimeError("crash before clone")

        with self.assertRaisesRegex(RuntimeError, "crash before clone"):
            self.prepare(fault_hook=fault)
        self.assertFalse(self.clone.exists())
        recovered = self.prepare()
        self.assertEqual(recovered["state"], "prepared")
        self.assertEqual(list(self.clone.iterdir()), [])

    def test_preintent_crash_after_directory_marker_recovers(self) -> None:
        self.make_clone_destination_absent()

        def fault(point: str) -> None:
            if point == "after_clone_directory":
                raise RuntimeError("crash after directory")

        with self.assertRaisesRegex(RuntimeError, "crash after directory"):
            self.prepare(fault_hook=fault)
        self.assertTrue(self.clone.exists())
        recovered = self.prepare()
        self.assertEqual(recovered["state"], "prepared")
        self.assertEqual(list(self.clone.iterdir()), [])

    def test_prepared_empty_directory_accepts_real_git_clone_and_finalize(
        self,
    ) -> None:
        self.make_clone_destination_absent()
        prepared = self.prepare()
        self.assertEqual(prepared["state"], "prepared")
        source = self.control.parent / "source-repo"
        source.mkdir()
        subprocess.run(["git", "-C", str(source), "init"], check=True)
        subprocess.run(
            ["git", "-C", str(source), "config", "user.name", "Onyx"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "config",
                "user.email",
                "onyx@example.invalid",
            ],
            check=True,
        )
        (source / "README.md").write_bytes(b"Onyx\n")
        subprocess.run(
            ["git", "-C", str(source), "add", "README.md"], check=True
        )
        subprocess.run(
            ["git", "-C", str(source), "commit", "-m", "base"],
            check=True,
        )
        subprocess.run(
            ["git", "clone", str(source), str(self.clone)],
            check=True,
            capture_output=True,
        )
        finalized = self.engine.finalize_provenance(
            mission_id=MISSION,
            binding_digest=BINDING,
            envelope_digest=ENVELOPE,
            owner_root=self.owner,
            clone_root=self.clone,
            owner_git_sha256=OWNER_SHA,
        )
        self.assertEqual(finalized["state"], "finalized")
        self.assertTrue((self.clone / ".git").is_dir())

    def test_real_packed_git_clone_with_nonzero_directory_eof_is_deleted(
        self,
    ) -> None:
        self.make_clone_destination_absent()
        prepared = self.prepare()
        self.assertEqual(prepared["state"], "prepared")
        source = self.control.parent / "packed-source-repo"
        source.mkdir()
        subprocess.run(["git", "-C", str(source), "init"], check=True)
        subprocess.run(
            ["git", "-C", str(source), "config", "user.name", "Onyx"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "config",
                "user.email",
                "onyx@example.invalid",
            ],
            check=True,
        )
        (source / "README.md").write_bytes(b"Onyx packed clone\n")
        subprocess.run(
            ["git", "-C", str(source), "add", "README.md"], check=True
        )
        subprocess.run(
            ["git", "-C", str(source), "commit", "-m", "base"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "gc", "--aggressive"],
            check=True,
        )
        subprocess.run(
            ["git", "clone", "--no-local", str(source), str(self.clone)],
            check=True,
            capture_output=True,
        )
        finalized = self.engine.finalize_provenance(
            mission_id=MISSION,
            binding_digest=BINDING,
            envelope_digest=ENVELOPE,
            owner_root=self.owner,
            clone_root=self.clone,
            owner_git_sha256=OWNER_SHA,
        )
        self.assertEqual(finalized["state"], "finalized")
        pack = self.clone / ".git" / "objects" / "pack"
        self.assertTrue(any(pack.glob("*.pack")))
        for artifact in pack.iterdir():
            if artifact.is_file():
                os.chmod(artifact, stat.S_IREAD)
        with cleanup_module._root_handle(
            pack, exclusive=False
        ) as pack_handle:
            _attributes, standard = (
                cleanup_module._attributes_and_standard(pack_handle)
            )
            self.assertGreater(int(standard.EndOfFile), 0)
        readonly_artifact = next(pack.glob("*.idx"))
        with cleanup_module._root_handle(
            readonly_artifact, exclusive=False
        ) as artifact_handle:
            attributes, _standard = (
                cleanup_module._attributes_and_standard(
                    artifact_handle
                )
            )
            self.assertTrue(
                int(attributes.FileAttributes)
                & cleanup_module._FILE_ATTRIBUTE_READONLY
            )
        self.assertTrue(self.cleanup())
        self.assertFalse(self.clone.exists())

    def test_readonly_attribute_clear_crash_retries_bound_identity(
        self,
    ) -> None:
        target = self.clone / "payload.txt"
        os.chmod(target, stat.S_IREAD)
        self.provenance()

        def crash(point: str) -> None:
            if point == "after_readonly_cleared:payload.txt":
                raise RuntimeError("crash after readonly clear")

        with self.assertRaisesRegex(
            RuntimeError, "crash after readonly clear"
        ):
            self.cleanup(fault_hook=crash)
        self.assertTrue(self.cleanup())
        self.assertFalse(self.clone.exists())

    def test_readonly_attribute_clear_replacement_is_refused(
        self,
    ) -> None:
        target = self.clone / "payload.txt"
        os.chmod(target, stat.S_IREAD)
        self.provenance()
        replaced = False

        def replace(point: str) -> None:
            nonlocal replaced
            if (
                not replaced
                and point
                == "after_readonly_cleared:payload.txt"
            ):
                replaced = True
                tombstone = next(
                    path
                    for path in self.mission.iterdir()
                    if path.name.startswith(".onyx-cleanup-")
                )
                current = tombstone / "payload.txt"
                moved = current.with_name("original.txt")
                current.rename(moved)
                current.write_bytes(b"replacement")

        with self.assertRaises(PermissionError):
            self.cleanup(fault_hook=replace)
        self.assertTrue(replaced)
        tombstone = next(
            path
            for path in self.mission.iterdir()
            if path.name.startswith(".onyx-cleanup-")
        )
        self.assertEqual(
            (tombstone / "payload.txt").read_bytes(),
            b"payload",
        )

    def test_prepared_partial_clone_cleanup_uses_bound_identity(self) -> None:
        self.make_clone_destination_absent()
        prepared = self.prepare()
        self.assertEqual(prepared["state"], "prepared")
        partial = self.clone / ".git" / "objects" / "partial"
        partial.parent.mkdir(parents=True)
        partial.write_bytes(b"partial")
        transitions: list[tuple[str, str | None]] = []
        result = self.engine.cleanup(
            mission_id=MISSION,
            binding_digest=BINDING,
            envelope_digest=ENVELOPE,
            owner_root=self.owner,
            clone_root=self.clone,
            owner_git_sha256=OWNER_SHA,
            terminal_state="failed",
            checkpoint={
                "stage": "clone_building",
                "mission_id": MISSION,
                "binding_digest": BINDING,
                "owner_git_sha256": OWNER_SHA,
            },
            owner_validator=lambda: None,
            checkpoint_writer=lambda stage, digest: transitions.append(
                (stage, digest)
            ),
        )
        self.assertTrue(result)
        self.assertFalse(self.clone.exists())

    def test_prepared_clone_move_and_replacement_are_refused(self) -> None:
        self.make_clone_destination_absent()
        self.prepare()
        moved = self.mission / "moved-prepared-clone"
        self.clone.rename(moved)
        self.clone.mkdir()
        sentinel = moved / "original-sentinel.txt"
        sentinel.write_bytes(b"bound-original")
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "prepared_clone_identity_mismatch",
        ):
            self.prepare()
        self.assertEqual(list(self.clone.iterdir()), [])
        replacement = self.clone / "replacement.txt"
        replacement.write_bytes(b"attacker")
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "identity_mismatch|path_mismatch",
        ):
            self.engine.finalize_provenance(
                mission_id=MISSION,
                binding_digest=BINDING,
                envelope_digest=ENVELOPE,
                owner_root=self.owner,
                clone_root=self.clone,
                owner_git_sha256=OWNER_SHA,
            )
        self.assertEqual(sentinel.read_bytes(), b"bound-original")
        self.assertEqual(replacement.read_bytes(), b"attacker")

    def test_prepared_retry_refuses_owner_replacement(self) -> None:
        self.make_clone_destination_absent()
        self.prepare()
        original = self.base / "owner-original"
        self.owner.rename(original)
        self.owner.mkdir()
        replacement = self.owner / "replacement.txt"
        replacement.write_bytes(b"attacker")
        sentinel = original / "sentinel.txt"
        sentinel.write_bytes(b"bound-owner")
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "prepared_root_identity_mismatch",
        ):
            self.prepare()
        self.assertEqual(sentinel.read_bytes(), b"bound-owner")
        self.assertEqual(replacement.read_bytes(), b"attacker")

    def test_prepared_retry_refuses_worktree_relocation_replacement(
        self,
    ) -> None:
        self.make_clone_destination_absent()
        self.prepare()
        moved = self.base / "control-original"
        self.control.rename(moved)
        replacement_mission = self.control / MISSION
        replacement_mission.mkdir(parents=True)
        original_mission = moved / MISSION
        for source in original_mission.glob(
            "clone.cleanup.provenance.slot*.v1.json"
        ):
            (replacement_mission / source.name).write_bytes(
                source.read_bytes()
            )
        (replacement_mission / "clone").mkdir()
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "prepared_root_identity_mismatch",
        ):
            self.prepare()
        self.assertTrue((original_mission / "clone").is_dir())
        self.assertTrue((replacement_mission / "clone").is_dir())

    def test_prepared_retry_refuses_mission_relocation_replacement(
        self,
    ) -> None:
        self.make_clone_destination_absent()
        self.prepare()
        moved = self.control / f"{MISSION}-original"
        self.mission.rename(moved)
        self.mission.mkdir()
        for source in moved.glob(
            "clone.cleanup.provenance.slot*.v1.json"
        ):
            (self.mission / source.name).write_bytes(
                source.read_bytes()
            )
        self.clone.mkdir()
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "prepared_root_identity_mismatch",
        ):
            self.prepare()
        self.assertTrue((moved / "clone").is_dir())
        self.assertTrue(self.clone.is_dir())

    def test_preintent_refuses_existing_preseed_clone(self) -> None:
        with self.assertRaisesRegex(
            CloneCleanupContractError, "preseed_refused"
        ):
            self.prepare()

    def test_marker_removed_crash_resumes_without_marker_or_secret_leak(
        self,
    ) -> None:
        self.make_clone_destination_absent()

        def fault(point: str) -> None:
            if point == "after_clone_marker_removed":
                raise RuntimeError("crash after marker removal")

        with self.assertRaisesRegex(RuntimeError, "marker removal"):
            self.prepare(fault_hook=fault)
        self.assertEqual(list(self.clone.iterdir()), [])
        recovered = self.prepare()
        self.assertEqual(recovered["state"], "prepared")
        provenance_text = (
            self.mission / "clone.cleanup.provenance.slot1.v1.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("kkkkkkkk", provenance_text)
        self.assertNotIn(".onyx-clone-owner", provenance_text)

    def test_preopened_mission_delete_handle_forces_wait_then_retry(self) -> None:
        self.provenance()
        with cleanup_module._root_handle(
            self.mission, exclusive=False, delete=True
        ):
            with self.assertRaisesRegex(
                CloneCleanupWaiting, "handle_busy|root_handle_busy"
            ):
                self.cleanup()
        self.assertTrue(self.cleanup())

    def test_preopened_worktree_delete_handle_forces_wait_then_retry(
        self,
    ) -> None:
        self.provenance()
        with cleanup_module._root_handle(
            self.control, exclusive=False, delete=True
        ):
            with self.assertRaisesRegex(
                CloneCleanupWaiting, "root_handle_busy"
            ):
                self.cleanup()
        self.assertTrue(self.cleanup())

    def test_preopened_nested_ancestor_forces_wait_then_retry(self) -> None:
        nested = self.clone / "nested"
        nested.mkdir()
        (nested / "child.txt").write_bytes(b"child")
        self.provenance()
        with cleanup_module._root_handle(
            nested, exclusive=False, delete=True
        ):
            with self.assertRaisesRegex(
                CloneCleanupWaiting,
                "handle_busy|rename_waiting|delete_waiting",
            ):
                self.cleanup()
        self.assertTrue(self.cleanup())

    def test_mission_rename_is_denied_while_cleanup_holds_containment(
        self,
    ) -> None:
        self.provenance()
        moved = self.control / f"{MISSION}-moved"
        attempted = False

        def attempt_rename(point: str) -> None:
            nonlocal attempted
            if point == "before_entry:payload.txt" and not attempted:
                attempted = True
                with self.assertRaises(OSError):
                    self.mission.rename(moved)

        self.assertTrue(self.cleanup(fault_hook=attempt_rename))
        self.assertTrue(attempted)
        self.assertTrue(self.mission.is_dir())
        self.assertFalse(moved.exists())

    def test_clone_name_swap_after_manifest_before_rename_is_refused(
        self,
    ) -> None:
        self.provenance()

        def stop_after_manifest(point: str) -> None:
            if point == "after_cleanup_planned":
                raise RuntimeError("stop before rename")

        with self.assertRaisesRegex(RuntimeError, "stop before rename"):
            self.cleanup(fault_hook=stop_after_manifest)
        original = self.mission / "original-bound-clone"
        self.clone.rename(original)
        self.clone.mkdir()
        replacement = self.clone / "replacement.txt"
        replacement.write_bytes(b"attacker")
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "identity_mismatch|identity_changed",
        ):
            self.cleanup()
        self.assertTrue((original / "payload.txt").is_file())
        self.assertEqual(replacement.read_bytes(), b"attacker")

    def test_two_slot_crash_recovery_every_persist_seam(self) -> None:
        for point, occurrence in (
            ("after_provenance_slot_write", 1),
            ("after_provenance_vault_write", 1),
            ("after_provenance_slot_write", 2),
            ("after_provenance_vault_write", 2),
        ):
            with self.subTest(point=point, occurrence=occurrence):
                if self.clone.exists():
                    for child in tuple(self.clone.iterdir()):
                        if child.is_file():
                            child.unlink()
                    self.clone.rmdir()
                for slot in (
                    "clone.cleanup.provenance.slot0.v1.json",
                    "clone.cleanup.provenance.slot1.v1.json",
                ):
                    path = self.mission / slot
                    if path.exists():
                        path.unlink()
                self.vaults.clear()
                seen = 0

                def fault(current: str) -> None:
                    nonlocal seen
                    if current == point:
                        seen += 1
                        if seen == occurrence:
                            raise RuntimeError(
                                f"persist crash:{point}:{occurrence}"
                            )

                with self.assertRaisesRegex(RuntimeError, "persist crash"):
                    self.prepare(fault_hook=fault)
                recovered = self.prepare()
                self.assertEqual(recovered["state"], "prepared")
                self.assertEqual(list(self.clone.iterdir()), [])

    def test_finalize_two_slot_crash_before_and_after_vault_recovers(
        self,
    ) -> None:
        for point in (
            "after_provenance_slot_write",
            "after_provenance_vault_write",
        ):
            with self.subTest(point=point):
                self.make_clone_destination_absent()
                self.prepare()
                (self.clone / "payload.txt").write_bytes(b"payload")

                def fault(current: str) -> None:
                    if current == point:
                        raise RuntimeError(f"finalize crash:{point}")

                with self.assertRaisesRegex(
                    RuntimeError, "finalize crash"
                ):
                    self.engine.finalize_provenance(
                        mission_id=MISSION,
                        binding_digest=BINDING,
                        envelope_digest=ENVELOPE,
                        owner_root=self.owner,
                        clone_root=self.clone,
                        owner_git_sha256=OWNER_SHA,
                        fault_hook=fault,
                    )
                finalized = self.engine.finalize_provenance(
                    mission_id=MISSION,
                    binding_digest=BINDING,
                    envelope_digest=ENVELOPE,
                    owner_root=self.owner,
                    clone_root=self.clone,
                    owner_git_sha256=OWNER_SHA,
                )
                self.assertEqual(finalized["state"], "finalized")
                # Reset the complete mission for the next subtest.
                if point == "after_provenance_slot_write":
                    self.cleanup()
                    self.clone.mkdir()
                    (self.clone / "payload.txt").write_bytes(b"payload")
                    self.vaults.clear()

    def test_corrupt_inactive_slot_is_ignored_but_active_slot_is_fatal(
        self,
    ) -> None:
        self.provenance()
        inactive = (
            self.mission / "clone.cleanup.provenance.slot1.v1.json"
        )
        inactive.write_bytes(b"corrupt-inactive")
        self.assertEqual(self.authenticate()["state"], "finalized")
        active = (
            self.mission / "clone.cleanup.provenance.slot0.v1.json"
        )
        active.write_bytes(b"corrupt-active")
        with self.assertRaisesRegex(
            CloneCleanupContractError, "anchor_mismatch"
        ):
            self.authenticate()

    def test_new_anchor_with_missing_active_slot_is_fail_closed(self) -> None:
        self.make_clone_destination_absent()
        self.prepare()
        active = (
            self.mission / "clone.cleanup.provenance.slot1.v1.json"
        )
        active.unlink()
        with self.assertRaises(CloneCleanupContractError):
            self.authenticate()

    def test_unanchored_initial_slot_requires_exact_binding(self) -> None:
        self.make_clone_destination_absent()

        def fault(point: str) -> None:
            if point == "after_provenance_slot_write":
                raise RuntimeError("unanchored initial")

        with self.assertRaisesRegex(RuntimeError, "unanchored initial"):
            self.prepare(fault_hook=fault)
        with self.assertRaisesRegex(
            CloneCleanupContractError, "binding_mismatch"
        ):
            self.engine.prepare_provenance(
                mission_id=MISSION,
                binding_digest="f" * 64,
                envelope_digest=ENVELOPE,
                owner_root=self.owner,
                clone_root=self.clone,
                owner_git_sha256=OWNER_SHA,
            )

    def test_crash_after_directory_create_before_marker_recovers(self) -> None:
        self.make_clone_destination_absent()

        def fault(point: str) -> None:
            if point == "after_clone_directory_created_before_marker":
                raise RuntimeError("before marker")

        with self.assertRaisesRegex(RuntimeError, "before marker"):
            self.prepare(fault_hook=fault)
        self.assertTrue(self.clone.is_dir())
        self.assertEqual(list(self.clone.iterdir()), [])
        recovered = self.prepare()
        self.assertEqual(recovered["state"], "prepared")

    def test_ancestor_rename_after_validation_is_denied(self) -> None:
        nested = self.clone / "outer" / "inner"
        nested.mkdir(parents=True)
        (nested / "child.txt").write_bytes(b"child")
        self.provenance()
        moved = self.mission / "escaped-outer"
        attempted = False

        def probe(point: str) -> None:
            nonlocal attempted
            if (
                point == "after_ancestor_validation:outer"
                and not attempted
            ):
                attempted = True
                with self.assertRaises(OSError):
                    (self.clone / "outer").rename(moved)

        self.assertTrue(self.cleanup(fault_hook=probe))
        self.assertTrue(attempted)
        self.assertFalse(moved.exists())


class WindowsCloneCleanupStaticContractTests(unittest.TestCase):
    def test_win32_exists_errors_map_to_retryable_collision(self) -> None:
        for code in (80, 183):
            with self.subTest(code=code), self.assertRaisesRegex(
                CloneCleanupWaiting, "rename_destination_exists"
            ):
                cleanup_module._raise_rename_failure(
                    code, replace=False
                )

    def test_legacy_create_entrypoint_is_sealed_to_single_refusal(self) -> None:
        source = inspect.getsource(
            cleanup_module.WindowsCloneCleanupV1.create_provenance
        )
        self.assertIn("legacy_create_provenance_disabled", source)
        self.assertNotIn("_metadata_", source)
        self.assertNotIn("_persist_provenance", source)
        self.assertNotIn("_child_handle", source)

    def test_clone_traversal_has_no_path_walk_or_fallback_delete(self) -> None:
        source = Path(cleanup_module.__file__).read_text(encoding="utf-8")
        forbidden = (
            "os.walk(",
            "shutil.rmtree(",
            "Path.rmdir(",
            "MoveFileEx",
            "DeleteFileW",
            "RemoveDirectoryW",
            "FILE_DISPOSITION_ON_CLOSE",
        )
        for pattern in forbidden:
            self.assertNotIn(pattern, source)

    def test_disposition_flags_are_exact_and_do_not_include_on_close(self) -> None:
        flags = (
            cleanup_module._FILE_DISPOSITION_DELETE
            | cleanup_module._FILE_DISPOSITION_POSIX_SEMANTICS
            | cleanup_module._FILE_DISPOSITION_FORCE_IMAGE_SECTION_CHECK
            | cleanup_module._FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE
        )
        self.assertEqual(flags, 0x17)


if __name__ == "__main__":
    unittest.main()
