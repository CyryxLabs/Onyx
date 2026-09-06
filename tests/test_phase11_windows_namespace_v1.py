from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import core.phase11_windows_clone_cleanup_v1 as cleanup_module
import core.phase11_windows_namespace_v1 as namespace_module
from core.phase11_windows_clone_cleanup_v1 import (
    CloneCleanupContractError,
    CloneCleanupWaiting,
)
from core.phase11_windows_namespace_v1 import (
    WindowsNamespaceV1,
    WindowsTrustedDirectoryV1,
)


MISSION = "mis_" + "a" * 32


@unittest.skipUnless(os.name == "nt", "Windows namespace contract")
class WindowsNamespaceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "worktrees"
        self.mission = self.root / MISSION
        self.mission.mkdir(parents=True)
        self.namespace = WindowsNamespaceV1(
            worktree_root=self.root, enabled=True
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_off_has_no_side_effect(self) -> None:
        target = Path(self.temporary.name) / "absent"
        WindowsNamespaceV1(worktree_root=target, enabled=False)
        self.assertFalse(target.exists())

    def test_lock_is_single_link_and_excludes_nested_open(self) -> None:
        with self.namespace.mission(MISSION) as mission:
            with mission.lock() as held:
                self.assertIsNotNone(held.value)
                with self.assertRaisesRegex(
                    CloneCleanupWaiting,
                    "mission_interprocess_lock_busy",
                ):
                    with self.namespace.mission(
                        MISSION
                    ) as competing:
                        with competing.lock():
                            self.fail("competing lock acquired")

    def test_hardlinked_lock_is_refused_without_touching_sentinel(
        self,
    ) -> None:
        sentinel = Path(self.temporary.name) / "sentinel"
        sentinel.write_bytes(b"external")
        os.link(sentinel, self.mission / "mission.lock")
        with self.namespace.mission(MISSION) as mission:
            with self.assertRaisesRegex(
                CloneCleanupContractError, "hardlink|leaf_identity"
            ):
                with mission.lock():
                    self.fail("hardlinked lock accepted")
        self.assertEqual(sentinel.read_bytes(), b"external")

    def test_artifact_reservation_is_single_link_and_name_protected(
        self,
    ) -> None:
        with self.namespace.mission(MISSION) as mission:
            with mission.artifact(
                "source.bundle", create=True, delete_access=True
            ) as held:
                self.assertIsNotNone(held.value)
                with self.assertRaises(CloneCleanupWaiting):
                    with mission.artifact(
                        "source.bundle", delete_access=True
                    ):
                        self.fail("protected artifact reopened")
        sentinel = Path(self.temporary.name) / "artifact-sentinel"
        sentinel.write_bytes(b"external")
        os.link(sentinel, self.mission / "patch.diff")
        with self.namespace.mission(MISSION) as mission:
            with self.assertRaisesRegex(
                CloneCleanupContractError, "hardlink"
            ):
                with mission.artifact(
                    "patch.diff", delete_access=True
                ):
                    self.fail("hardlinked artifact accepted")
        self.assertEqual(sentinel.read_bytes(), b"external")

    def test_bounded_read_and_logical_scrub(self) -> None:
        target = self.mission / "source.bundle"
        target.write_bytes(b"sensitive-bytes")
        with self.namespace.mission(MISSION) as mission:
            self.assertEqual(
                mission.read_artifact(
                    "source.bundle", max_bytes=32
                ),
                b"sensitive-bytes",
            )
            with self.assertRaisesRegex(
                CloneCleanupContractError, "size_invalid"
            ):
                mission.read_artifact(
                    "source.bundle", max_bytes=2
                )
            self.assertTrue(
                mission.scrub_artifact(
                    "source.bundle", max_bytes=32
                )
            )
            self.assertFalse(
                mission.scrub_artifact(
                    "source.bundle", max_bytes=32
                )
            )
        self.assertFalse(target.exists())

    def test_artifact_primary_exception_identity_and_name_swap_denial(
        self,
    ) -> None:
        target = self.mission / "checkpoint.transaction.json"
        target.write_bytes(b"transaction")
        primary = KeyboardInterrupt("primary")
        with self.namespace.mission(MISSION) as mission:
            with self.assertRaises(KeyboardInterrupt) as observed:
                with mission.artifact(
                    "checkpoint.transaction.json",
                    delete_access=True,
                ):
                    with self.assertRaises(PermissionError):
                        target.rename(
                            target.with_name("replacement")
                        )
                    raise primary
        self.assertIs(observed.exception, primary)
        self.assertEqual(target.read_bytes(), b"transaction")

    def test_mission_junction_is_refused(self) -> None:
        external = Path(self.temporary.name) / "external"
        external.mkdir()
        self.mission.rmdir()
        completed = subprocess.run(
            [
                "cmd",
                "/c",
                "mklink",
                "/J",
                str(self.mission),
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
                with self.namespace.mission(MISSION):
                    self.fail("junction mission accepted")
        finally:
            os.rmdir(self.mission)
            self.mission.mkdir()

    def test_real_second_process_lock_and_artifact_contention(
        self,
    ) -> None:
        script = (
            "import sys\n"
            "from core.phase11_windows_namespace_v1 import WindowsNamespaceV1\n"
            f"n=WindowsNamespaceV1(worktree_root={str(self.root)!r}, enabled=True)\n"
            f"with n.mission({MISSION!r}) as s:\n"
            "  with s.lock():\n"
            "    with s.artifact('source.bundle', create=True, delete_access=True):\n"
            "      print('READY', flush=True)\n"
            "      sys.stdin.readline()\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=str(Path.cwd()),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert child.stdout is not None
            self.assertEqual(child.stdout.readline().strip(), "READY")
            with self.namespace.mission(MISSION) as mission:
                with self.assertRaisesRegex(
                    CloneCleanupWaiting,
                    "mission_interprocess_lock_busy",
                ):
                    with mission.lock():
                        self.fail("cross-process lock acquired")
                with self.assertRaises(CloneCleanupWaiting):
                    with mission.artifact(
                        "source.bundle", delete_access=True
                    ):
                        self.fail("cross-process artifact acquired")
        finally:
            if child.stdin is not None:
                child.stdin.write("\n")
                child.stdin.close()
            child.wait(timeout=10)
            if child.stdout is not None:
                child.stdout.close()
            if child.stderr is not None:
                child.stderr.close()
        self.assertEqual(child.returncode, 0)

    def test_trusted_directory_pins_parent_root_and_atomic_leaf(self) -> None:
        trusted_path = Path(self.temporary.name) / "bindings"
        boundary = WindowsTrustedDirectoryV1(
            root=trusted_path, enabled=True
        )
        try:
            with self.assertRaises(PermissionError):
                trusted_path.rename(trusted_path.with_name("swapped"))
            with self.assertRaises(PermissionError):
                trusted_path.parent.rename(
                    trusted_path.parent.with_name("parent-swapped")
                )
            with boundary.session() as session:
                session.publish_create("mission.binding.json", b"signed")
                self.assertEqual(
                    session.read(
                        "mission.binding.json", max_bytes=16
                    ),
                    b"signed",
                )
                self.assertFalse(
                    any(
                        item.name.startswith("tmp-")
                        for item in trusted_path.iterdir()
                    )
                )
        finally:
            boundary.close()

    def test_trusted_directory_close_is_retryable_after_closehandle_failure(
        self,
    ) -> None:
        trusted_path = Path(self.temporary.name) / "retry-close"
        boundary = WindowsTrustedDirectoryV1(root=trusted_path, enabled=True)
        assert boundary.root is not None
        failed_value = boundary.root.value
        original_close_handle = cleanup_module._kernel32.CloseHandle
        attempts = 0

        def fail_inside_closehandle(value: int) -> int:
            nonlocal attempts
            raw_value = getattr(value, "value", value)
            if raw_value == failed_value:
                attempts += 1
                if attempts == 1:
                    return 0
            return original_close_handle(value)

        with patch.object(
            cleanup_module._kernel32,
            "CloseHandle",
            side_effect=fail_inside_closehandle,
        ):
            with self.assertRaisesRegex(
                CloneCleanupContractError,
                "phase11_trusted_directory_close_failed",
            ):
                boundary.close()
            self.assertFalse(boundary._closed)
            self.assertIsNotNone(boundary.root)
            self.assertFalse(boundary.root.closed)
            self.assertIsNone(boundary.parent)

            boundary.close()

        self.assertEqual(attempts, 2)
        self.assertTrue(boundary._closed)
        self.assertIsNone(boundary.root)
        self.assertIsNone(boundary.parent)

    def test_trusted_directory_concurrent_close_calls_close_each_handle_once(
        self,
    ) -> None:
        trusted_path = Path(self.temporary.name) / "concurrent-close"
        boundary = WindowsTrustedDirectoryV1(root=trusted_path, enabled=True)
        original_close_handle = cleanup_module._kernel32.CloseHandle
        calls: list[int] = []

        def record_closehandle(value: int) -> int:
            raw_value = int(getattr(value, "value", value))
            calls.append(raw_value)
            return original_close_handle(value)

        with patch.object(
            cleanup_module._kernel32,
            "CloseHandle",
            side_effect=record_closehandle,
        ):
            threads = [threading.Thread(target=boundary.close) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
                self.assertFalse(thread.is_alive())

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(set(calls)), 2)
        self.assertTrue(boundary._closed)

    def test_trusted_constructor_final_validation_failure_retains_cleanup_retry(
        self,
    ) -> None:
        target = Path(self.temporary.name) / "failed-final-validation"
        original_validate = WindowsTrustedDirectoryV1._validate
        original_close_handle = cleanup_module._kernel32.CloseHandle
        validation_calls = 0
        close_calls = 0
        fail_cleanup = False

        def fail_final_validation(instance) -> None:
            nonlocal fail_cleanup, validation_calls
            validation_calls += 1
            if validation_calls == 1:
                fail_cleanup = True
                raise CloneCleanupContractError(
                    "injected_final_validation_failure"
                )
            original_validate(instance)

        def fail_first_cleanup(value: int) -> int:
            nonlocal close_calls, fail_cleanup
            close_calls += 1
            if fail_cleanup:
                fail_cleanup = False
                return 0
            return original_close_handle(value)

        with (
            patch.object(
                WindowsTrustedDirectoryV1,
                "_validate",
                new=fail_final_validation,
            ),
            patch.object(
                cleanup_module._kernel32,
                "CloseHandle",
                side_effect=fail_first_cleanup,
            ),
        ):
            with self.assertRaisesRegex(
                CloneCleanupContractError,
                "phase11_trusted_constructor_cleanup_failed",
            ):
                WindowsTrustedDirectoryV1(root=target, enabled=True)

        self.assertTrue(
            namespace_module._FAILED_TRUSTED_CONSTRUCTION_HANDLES
        )
        recovered = WindowsTrustedDirectoryV1(
            root=Path(self.temporary.name) / "recovered-authority",
            enabled=True,
        )
        try:
            self.assertFalse(
                namespace_module._FAILED_TRUSTED_CONSTRUCTION_HANDLES
            )
            self.assertGreaterEqual(close_calls, 1)
        finally:
            recovered.close()

    def test_pending_constructor_cleanup_blocks_competing_authority(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        class PermanentlyFailingHandle:
            closed = False

            def close(self) -> None:
                entered.set()
                self.assert_release()
                raise OSError("injected retained handle close failure")

            @staticmethod
            def assert_release() -> None:
                if not release.wait(5):
                    raise AssertionError("cleanup release timed out")

        retained = PermanentlyFailingHandle()
        with namespace_module._FAILED_TRUSTED_CONSTRUCTION_LOCK:
            namespace_module._FAILED_TRUSTED_CONSTRUCTION_HANDLES.append(
                retained
            )
        errors: list[BaseException] = []
        granted: list[WindowsTrustedDirectoryV1] = []

        def construct(name: str) -> None:
            try:
                granted.append(
                    WindowsTrustedDirectoryV1(
                        root=Path(self.temporary.name) / name,
                        enabled=True,
                    )
                )
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=construct, args=("first",))
        second = threading.Thread(target=construct, args=("second",))
        first.start()
        self.assertTrue(entered.wait(5))
        second.start()
        second.join(0.1)
        self.assertTrue(second.is_alive())
        self.assertEqual(granted, [])
        release.set()
        first.join(5)
        second.join(5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(granted, [])
        self.assertEqual(len(errors), 2)
        with namespace_module._FAILED_TRUSTED_CONSTRUCTION_LOCK:
            namespace_module._FAILED_TRUSTED_CONSTRUCTION_HANDLES.clear()

    def test_trusted_directory_rejects_root_and_parent_junctions(
        self,
    ) -> None:
        external = Path(self.temporary.name) / "external"
        external.mkdir()
        for name, parent_link in (
            ("root-link", False),
            ("parent-link", True),
        ):
            container = Path(self.temporary.name) / f"{name}-container"
            container.mkdir()
            linked = container / "linked"
            completed = subprocess.run(
                [
                    "cmd",
                    "/c",
                    "mklink",
                    "/J",
                    str(linked),
                    str(external),
                ],
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                self.skipTest("junction creation unavailable")
            target = linked / "bindings" if parent_link else linked
            try:
                with self.assertRaisesRegex(
                    CloneCleanupContractError, "reparse"
                ):
                    WindowsTrustedDirectoryV1(
                        root=target, enabled=True
                    )
            finally:
                os.rmdir(linked)

    def test_trusted_directory_rejects_hardlink_and_ads(self) -> None:
        trusted_path = Path(self.temporary.name) / "bindings"
        trusted_path.mkdir()
        sentinel = Path(self.temporary.name) / "sentinel"
        sentinel.write_bytes(b"external")
        os.link(sentinel, trusted_path / "mission.binding.json")
        boundary = WindowsTrustedDirectoryV1(
            root=trusted_path, enabled=True
        )
        try:
            with boundary.session() as session:
                with self.assertRaisesRegex(
                    CloneCleanupContractError, "hardlink|leaf_identity"
                ):
                    session.read(
                        "mission.binding.json", max_bytes=32
                    )
                artifact = trusted_path / "artifact.aesgcm"
                artifact.write_bytes(b"ciphertext")
                Path(str(artifact) + ":forbidden").write_bytes(b"ads")
                with self.assertRaisesRegex(
                    CloneCleanupContractError,
                    "ads|alternate_data_stream",
                ):
                    session.read("artifact.aesgcm", max_bytes=32)
            self.assertEqual(sentinel.read_bytes(), b"external")
        finally:
            boundary.close()

    def test_trusted_directory_denies_name_swap_during_read(self) -> None:
        trusted_path = Path(self.temporary.name) / "bindings"
        boundary = WindowsTrustedDirectoryV1(
            root=trusted_path, enabled=True
        )
        try:
            target = trusted_path / "mission.binding.json"
            replacement = trusted_path / "replacement"
            with boundary.session() as session:
                session.publish_create(
                    "mission.binding.json", b"authenticated"
                )
                replacement.write_bytes(b"forged")
                import core.phase11_windows_namespace_v1 as namespace_module

                original = namespace_module._read_regular_handle

                def swap_while_held(handle, max_bytes):
                    with self.assertRaises(PermissionError):
                        os.replace(replacement, target)
                    return original(handle, max_bytes)

                with patch.object(
                    namespace_module,
                    "_read_regular_handle",
                    side_effect=swap_while_held,
                ):
                    self.assertEqual(
                        session.read(
                            "mission.binding.json", max_bytes=32
                        ),
                        b"authenticated",
                    )
        finally:
            boundary.close()

    def test_trusted_directory_missing_chain_two_instance_convergence(
        self,
    ) -> None:
        target = (
            Path(self.temporary.name)
            / "new-owner"
            / "private"
            / "bindings"
        )
        first = WindowsTrustedDirectoryV1(root=target, enabled=True)
        second = WindowsTrustedDirectoryV1(root=target, enabled=True)
        try:
            self.assertEqual(
                first.root_identity.file_id,
                second.root_identity.file_id,
            )
            with first.session() as session:
                session.publish_create("binding.json", b"signed")
            with second.session() as session:
                self.assertEqual(
                    session.read("binding.json", max_bytes=16),
                    b"signed",
                )
        finally:
            second.close()
            first.close()

    def test_trusted_directory_exact_create_race_reopens_winner(self) -> None:
        target = Path(self.temporary.name) / "constructor-create-race"
        original_child_handle = namespace_module._child_handle
        injected = False

        def create_winner_then_lose(parent, name, **kwargs):
            nonlocal injected
            if name == target.name and kwargs.get("create") and not injected:
                injected = True
                with original_child_handle(parent, name, **kwargs):
                    pass
            return original_child_handle(parent, name, **kwargs)

        with patch.object(
            namespace_module,
            "_child_handle",
            side_effect=create_winner_then_lose,
        ):
            boundary = WindowsTrustedDirectoryV1(root=target, enabled=True)
        try:
            self.assertTrue(injected)
            self.assertIsNotNone(boundary.root_identity)
            with cleanup_module._root_handle(
                target, exclusive=False
            ) as reopened:
                reopened_identity = cleanup_module._validate_volume(reopened)
            self.assertEqual(
                boundary.root_identity.file_id,
                reopened_identity.file_id,
            )
        finally:
            boundary.close()

    def test_trusted_directory_accepts_standard_modify_authority_parent(
        self,
    ) -> None:
        """Fresh ONYX_DATA_DIR parents need no broad delete-child grant."""

        from core.control_plane import (
            _apply_windows_security_sddl,
            _current_windows_sid,
        )

        authority = Path(self.temporary.name) / "standard-modify-authority"
        authority.mkdir()
        sid = _current_windows_sid()
        _apply_windows_security_sddl(
            authority,
            (
                f"O:{sid}D:P"
                "(A;OICI;FA;;;SY)"
                f"(A;OICI;0x001301bf;;;{sid})"
            ),
        )
        target = authority / "phase11-live-bindings-v1"

        boundary = WindowsTrustedDirectoryV1(root=target, enabled=True)
        try:
            with boundary.session() as session:
                session.publish_create("binding.json", b"authenticated")
                self.assertEqual(
                    session.read("binding.json", max_bytes=32),
                    b"authenticated",
                )
        finally:
            boundary.close()

    def test_directory_flush_refusal_is_best_effort_and_reopens(self):
        import core.phase11_windows_namespace_v1 as namespace_module

        target = Path(self.temporary.name) / "flush-bindings"
        boundary = WindowsTrustedDirectoryV1(root=target, enabled=True)
        try:
            with (
                patch.object(
                    namespace_module,
                    "_flush_directory_best_effort",
                    return_value=False,
                ) as flush,
                boundary.session() as session,
            ):
                session.publish_create("binding.json", b"durable-file")
            flush.assert_called_once()
            with boundary.session() as session:
                self.assertEqual(
                    session.read("binding.json", max_bytes=32),
                    b"durable-file",
                )
        finally:
            boundary.close()

    def test_trusted_directory_concurrent_junction_precreate_refused(
        self,
    ) -> None:
        import core.phase11_windows_namespace_v1 as namespace_module

        external = Path(self.temporary.name) / "external-race"
        external.mkdir()
        sentinel = external / "sentinel"
        sentinel.write_bytes(b"outside")
        target = (
            Path(self.temporary.name)
            / "raced-parent"
            / "private"
            / "bindings"
        )
        original = namespace_module._child_handle
        injected = False

        def inject(parent, name, **kwargs):
            nonlocal injected
            if kwargs.get("create") and name == "raced-parent" and not injected:
                injected = True
                completed = subprocess.run(
                    [
                        "cmd",
                        "/c",
                        "mklink",
                        "/J",
                        str(Path(self.temporary.name) / name),
                        str(external),
                    ],
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0:
                    self.skipTest("junction creation unavailable")
            return original(parent, name, **kwargs)

        try:
            with patch.object(
                namespace_module,
                "_child_handle",
                side_effect=inject,
            ):
                with self.assertRaises(CloneCleanupContractError):
                    WindowsTrustedDirectoryV1(
                        root=target, enabled=True
                    )
            self.assertTrue(injected)
            self.assertEqual(sentinel.read_bytes(), b"outside")
            self.assertFalse((external / "private").exists())
        finally:
            linked = Path(self.temporary.name) / "raced-parent"
            if linked.exists():
                os.rmdir(linked)


if __name__ == "__main__":
    unittest.main()
