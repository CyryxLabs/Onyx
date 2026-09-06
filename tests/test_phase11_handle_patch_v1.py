from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import core.phase11_windows_clone_cleanup_v1 as cleanup_module
from core.phase11_handle_patch_v1 import (
    HandlePatchEngineV1,
    JOURNAL_NAME,
    parse_canonical_patch,
)
from core.phase11_windows_clone_cleanup_v1 import (
    CloneCleanupContractError,
)
from core.phase11_windows_namespace_v1 import WindowsNamespaceV1


MISSION = "mis_" + "a" * 32
MODIFY = """diff --git a/demo.txt b/demo.txt
--- a/demo.txt
+++ b/demo.txt
@@ -1 +1 @@
-before
+after
"""
ADD = """diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+hello
+world
"""
NESTED = """diff --git a/pkg/value.txt b/pkg/value.txt
--- a/pkg/value.txt
+++ b/pkg/value.txt
@@ -1 +1 @@
-old
+new
"""


class HandlePatchV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "control"
        self.mission_dir = self.root / MISSION
        self.clone = self.mission_dir / "clone"
        self.clone.mkdir(parents=True)
        (self.clone / "demo.txt").write_bytes(b"before\n")
        (self.clone / "pkg").mkdir()
        (self.clone / "pkg" / "value.txt").write_bytes(b"old\n")
        self.namespace = WindowsNamespaceV1(
            worktree_root=self.root, enabled=True
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _identity(self) -> dict[str, object]:
        with cleanup_module._root_handle(
            self.clone, exclusive=False
        ) as handle:
            return cleanup_module._identity_payload(
                cleanup_module._validate_volume(handle)
            )

    def _apply(self, patch: str, *, fault_hook=None) -> None:
        with self.namespace.mission(MISSION) as mission:
            with mission.lock():
                with mission.clone_operation(
                    self._identity()
                ) as clone:
                    HandlePatchEngineV1(
                        signing_key=b"k" * 32,
                        mission=mission,
                        clone=clone,
                    ).apply(patch, fault_hook=fault_hook)

    def test_real_handle_relative_modify_and_add(self) -> None:
        self._apply(MODIFY)
        self._apply(ADD)
        self.assertEqual(
            (self.clone / "demo.txt").read_bytes(), b"after\n"
        )
        self.assertEqual(
            (self.clone / "new.txt").read_bytes(),
            b"hello\nworld\n",
        )
        self.assertFalse(
            (self.mission_dir / JOURNAL_NAME).exists()
        )

    def test_modify_crash_rolls_back_from_encrypted_journal_and_replays(
        self,
    ) -> None:
        crashed = False

        def crash(point: str) -> None:
            nonlocal crashed
            if not crashed and point == "after_truncate":
                crashed = True
                raise RuntimeError("crash after truncate")

        with self.assertRaisesRegex(
            RuntimeError, "crash after truncate"
        ):
            self._apply(MODIFY, fault_hook=crash)
        journal = self.mission_dir / JOURNAL_NAME
        self.assertTrue(journal.is_file())
        raw = journal.read_bytes()
        self.assertNotIn(b"before", raw)
        self.assertNotIn(b"after", raw)
        document = json.loads(raw)
        self.assertIn("rollback_ciphertext", document["payload"])
        self._apply(MODIFY)
        self.assertEqual(
            (self.clone / "demo.txt").read_bytes(), b"after\n"
        )
        self.assertFalse(journal.exists())

    def test_policy_and_preimage_conflicts_fail_closed(self) -> None:
        delete = """diff --git a/demo.txt b/demo.txt
--- a/demo.txt
+++ /dev/null
@@ -1 +0,0 @@
-before
"""
        with self.assertRaisesRegex(
            CloneCleanupContractError, "delete_or_path_change"
        ):
            parse_canonical_patch(delete)
        with self.assertRaisesRegex(
            CloneCleanupContractError, "newline_policy"
        ):
            parse_canonical_patch(MODIFY.rstrip("\n"))
        conflict = MODIFY.replace("-before", "-different")
        with self.assertRaisesRegex(
            CloneCleanupContractError, "preimage_mismatch"
        ):
            self._apply(conflict)
        self.assertEqual(
            (self.clone / "demo.txt").read_bytes(), b"before\n"
        )
        (self.clone / "demo.txt").write_bytes(b"\xff\n")
        with self.assertRaisesRegex(
            CloneCleanupContractError, "utf8_required"
        ):
            self._apply(MODIFY)
        self.assertEqual(
            (self.clone / "demo.txt").read_bytes(), b"\xff\n"
        )

    def test_root_nested_and_existing_leaf_swaps_are_denied(self) -> None:
        observed: set[str] = set()

        def race(point: str) -> None:
            if point != "after_truncate" or observed:
                return
            targets = (
                ("root", self.clone, self.clone.with_name("moved")),
                (
                    "nested",
                    self.clone / "pkg",
                    self.clone / "pkg-moved",
                ),
                (
                    "leaf",
                    self.clone / "pkg" / "value.txt",
                    self.clone / "pkg" / "value-moved.txt",
                ),
            )
            for name, source, target in targets:
                with self.assertRaises(PermissionError):
                    source.rename(target)
                observed.add(name)

        self._apply(NESTED, fault_hook=race)
        self.assertEqual(observed, {"root", "nested", "leaf"})
        self.assertEqual(
            (self.clone / "pkg" / "value.txt").read_bytes(),
            b"new\n",
        )

    def test_new_leaf_race_fails_without_overwriting_attacker(self) -> None:
        raced = False

        def race(point: str) -> None:
            nonlocal raced
            if not raced and point == "after_journal":
                raced = True
                (self.clone / "new.txt").write_bytes(b"attacker")

        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "phase11_patch_add_target_raced",
        ):
            self._apply(ADD, fault_hook=race)
        self.assertTrue(raced)
        self.assertEqual(
            (self.clone / "new.txt").read_bytes(), b"attacker"
        )
        self.assertTrue((self.mission_dir / JOURNAL_NAME).is_file())

    def test_hardlink_ads_and_nested_junction_are_refused(self) -> None:
        outside = Path(self.temporary.name) / "outside.txt"
        os.link(self.clone / "demo.txt", outside)
        with self.assertRaisesRegex(
            CloneCleanupContractError, "hardlink"
        ):
            self._apply(MODIFY)
        self.assertEqual(outside.read_bytes(), b"before\n")

        os.unlink(outside)
        with open(
            str(self.clone / "demo.txt") + ":evil",
            "wb",
        ) as stream:
            stream.write(b"evil")
        with self.assertRaisesRegex(
            CloneCleanupContractError,
            "alternate_data_stream|ads",
        ):
            self._apply(MODIFY)
        os.unlink(str(self.clone / "demo.txt") + ":evil")

        external = Path(self.temporary.name) / "external"
        external.mkdir()
        marker = external / "value.txt"
        marker.write_bytes(b"sentinel\n")
        original = self.clone / "pkg-original"
        (self.clone / "pkg").rename(original)
        completed = subprocess.run(
            [
                "cmd",
                "/c",
                "mklink",
                "/J",
                str(self.clone / "pkg"),
                str(external),
            ],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self.skipTest("junction creation unavailable")
        try:
            with self.assertRaisesRegex(
                CloneCleanupContractError, "reparse"
            ):
                self._apply(NESTED)
            self.assertEqual(marker.read_bytes(), b"sentinel\n")
        finally:
            os.rmdir(self.clone / "pkg")

    def test_all_modify_and_add_commit_seams_replay_idempotently(
        self,
    ) -> None:
        for index, seam in enumerate(
            (
                "after_journal",
                "after_truncate",
                "after_write",
                "after_flush",
                "after_commit",
            )
        ):
            with self.subTest(seam=seam):
                target = self.clone / f"case-{index}.txt"
                target.write_bytes(b"before\n")
                patch = MODIFY.replace(
                    "demo.txt", f"case-{index}.txt"
                )
                crashed = False

                def crash(point: str) -> None:
                    nonlocal crashed
                    if not crashed and point == seam:
                        crashed = True
                        raise RuntimeError(seam)

                with self.assertRaisesRegex(RuntimeError, seam):
                    self._apply(patch, fault_hook=crash)
                self._apply(patch)
                self.assertEqual(target.read_bytes(), b"after\n")
        crashed = False

        def crash_add(point: str) -> None:
            nonlocal crashed
            if not crashed and point == "after_commit":
                crashed = True
                raise RuntimeError("add commit")

        with self.assertRaisesRegex(RuntimeError, "add commit"):
            self._apply(ADD, fault_hook=crash_add)
        self._apply(ADD)
        self.assertEqual(
            (self.clone / "new.txt").read_bytes(),
            b"hello\nworld\n",
        )

    def test_forged_plaintext_and_hardlinked_journals_never_bypass(
        self,
    ) -> None:
        journal = self.mission_dir / JOURNAL_NAME
        journal.write_bytes(MODIFY.encode("utf-8"))
        with self.assertRaisesRegex(
            CloneCleanupContractError, "journal_invalid"
        ):
            self._apply(MODIFY)
        self.assertEqual(
            (self.clone / "demo.txt").read_bytes(), b"before\n"
        )
        journal.unlink()
        sentinel = Path(self.temporary.name) / "journal-sentinel"
        sentinel.write_bytes(b"sentinel")
        os.link(sentinel, journal)
        with self.assertRaisesRegex(
            CloneCleanupContractError, "hardlink"
        ):
            self._apply(MODIFY)
        self.assertEqual(sentinel.read_bytes(), b"sentinel")
        self.assertEqual(
            (self.clone / "demo.txt").read_bytes(), b"before\n"
        )


if __name__ == "__main__":
    unittest.main()
