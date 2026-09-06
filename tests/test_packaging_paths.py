import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import paths


class PackagingPathTests(unittest.TestCase):
    def test_windows_bundle_declares_installed_dayops_console_helper(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "packaging" / "onyx.spec").read_text(encoding="utf-8")
        installer = (
            root / "packaging" / "windows" / "onyx.iss"
        ).read_text(encoding="utf-8")
        self.assertIn('name="Onyx-DayOps"', spec)
        self.assertIn("console=True", spec)
        self.assertIn('dayops_exe,', spec)
        self.assertNotIn("Onyx DayOps Setup", installer)
        self.assertNotIn("{cmd}", installer)

    def test_source_checkout_preserves_existing_local_layout(self):
        with patch.object(paths, "is_frozen", return_value=False):
            self.assertEqual(paths.data_root(), paths.resource_root())

    def test_frozen_windows_uses_local_appdata_not_bundle(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(paths, "is_frozen", return_value=True), \
             patch.object(paths.platform, "system", return_value="Windows"), \
             patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=True):
            self.assertEqual(
                paths.data_root(), Path(tmp) / "Cyryx Labs" / "Onyx"
            )

    def test_frozen_macos_uses_application_support(self):
        with patch.object(paths, "is_frozen", return_value=True), \
             patch.object(paths.platform, "system", return_value="Darwin"), \
             patch.object(paths.Path, "home", return_value=Path("/Users/owner")), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                paths.data_root(),
                Path("/Users/owner/Library/Application Support/Cyryx Labs/Onyx"),
            )

    def test_frozen_linux_honors_xdg_data_home(self):
        with patch.object(paths, "is_frozen", return_value=True), \
             patch.object(paths.platform, "system", return_value="Linux"), \
             patch.dict(os.environ, {"XDG_DATA_HOME": "/data"}, clear=True):
            self.assertEqual(paths.data_root(), Path("/data/cyryx-labs/onyx"))

    def test_frozen_linux_rejects_relative_xdg_data_home(self):
        with patch.object(paths, "is_frozen", return_value=True), \
             patch.object(paths.platform, "system", return_value="Linux"), \
             patch.dict(os.environ, {"XDG_DATA_HOME": "relative-data"}, clear=True):
            with self.assertRaisesRegex(
                paths.PrivateDataPathError, "XDG_DATA_HOME must be an absolute path"
            ):
                paths.data_root()

    def test_explicit_data_override_has_highest_precedence(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"ONYX_DATA_DIR": tmp}, clear=True):
            self.assertEqual(paths.data_root(), Path(tmp).resolve())

    def test_layout_creates_only_expected_writable_directories(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"ONYX_DATA_DIR": tmp}, clear=True):
            root = paths.ensure_data_layout()
            self.assertTrue((root / "config" / "certs").is_dir())
            self.assertTrue((root / "memory").is_dir())
            self.assertTrue((root / "runtime" / "audit").is_dir())
            self.assertTrue((root / "runtime" / "logs").is_dir())
            self.assertTrue((root / "uploads").is_dir())

    @unittest.skipIf(os.name == "nt", "POSIX ownership and mode contract")
    def test_posix_layout_repairs_managed_directories_to_private_mode(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"ONYX_DATA_DIR": str(Path(tmp) / "Onyx")}, clear=True):
            root = Path(tmp) / "Onyx"
            (root / "runtime").mkdir(mode=0o755, parents=True)
            os.chmod(root, 0o755)
            os.chmod(root / "runtime", 0o755)

            paths.ensure_data_layout()

            for candidate in (
                root,
                root / "config",
                root / "config" / "certs",
                root / "memory",
                root / "runtime",
                root / "runtime" / "audit",
                root / "runtime" / "logs",
                root / "uploads",
            ):
                self.assertEqual(candidate.stat().st_mode & 0o777, 0o700)

    @unittest.skipIf(os.name == "nt", "POSIX configured-root contract")
    def test_posix_layout_rejects_non_onyx_existing_root_without_chmod(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shared-data"
            root.mkdir(mode=0o755)
            os.chmod(root, 0o755)
            with patch.dict(
                os.environ, {"ONYX_DATA_DIR": str(root)}, clear=True
            ), patch.object(paths.os, "chmod") as named_chmod, patch.object(
                paths.os, "fchmod"
            ) as descriptor_chmod:
                with self.assertRaisesRegex(
                    paths.PrivateDataPathError, "not an explicitly identifiable Onyx leaf"
                ):
                    paths.ensure_data_layout()
            named_chmod.assert_not_called()
            descriptor_chmod.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX configured-root contract")
    def test_posix_data_root_rejects_broad_and_xdg_roots(self):
        home = Path.home()
        with tempfile.TemporaryDirectory() as xdg:
            for candidate in (Path("/"), Path("/tmp"), home, Path(xdg)):
                environment = {
                    "ONYX_DATA_DIR": str(candidate),
                    "XDG_DATA_HOME": str(Path(xdg)),
                }
                with self.subTest(candidate=candidate), patch.dict(
                    os.environ, environment, clear=True
                ), self.assertRaisesRegex(
                    paths.PrivateDataPathError, "too broad or sensitive"
                ):
                    paths.data_root()

    @unittest.skipIf(os.name == "nt", "POSIX system-namespace contract")
    def test_posix_data_root_rejects_system_namespace_descendants(self):
        candidates = (
            Path("/etc/Onyx"),
            Path("/usr/local/Onyx"),
            Path("/bin/Onyx"),
            Path("/sbin/Onyx"),
            Path("/lib64/Onyx"),
            Path("/var/lib/Onyx"),
            Path("/opt/Cyryx/Onyx"),
            Path("/run/user/Onyx"),
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate), patch.dict(
                os.environ, {"ONYX_DATA_DIR": str(candidate)}, clear=True
            ), self.assertRaisesRegex(
                paths.PrivateDataPathError, "inside a system namespace"
            ):
                paths.data_root()

    @unittest.skipIf(os.name == "nt", "POSIX private-leaf contract")
    def test_posix_data_root_allows_home_and_temporary_private_leaves(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidates = (
                Path.home() / ".local" / "share" / "cyryx-labs" / "onyx",
                Path(temporary) / "isolated" / "Onyx",
            )
            for candidate in candidates:
                with self.subTest(candidate=candidate), patch.dict(
                    os.environ, {"ONYX_DATA_DIR": str(candidate)}, clear=True
                ):
                    self.assertEqual(paths.data_root(), candidate.absolute())

    @unittest.skipIf(os.name == "nt", "POSIX symlink contract")
    def test_posix_layout_rejects_linked_managed_directory(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside, \
             patch.dict(os.environ, {"ONYX_DATA_DIR": tmp}, clear=True):
            (Path(tmp) / "runtime").symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaises(paths.PrivateDataPathError):
                paths.ensure_data_layout()

    @unittest.skipIf(os.name == "nt", "POSIX symlink contract")
    def test_posix_layout_rejects_linked_configured_root(self):
        with tempfile.TemporaryDirectory() as parent, tempfile.TemporaryDirectory() as outside:
            linked_root = Path(parent) / "onyx-data"
            linked_root.symlink_to(Path(outside), target_is_directory=True)
            with patch.dict(
                os.environ, {"ONYX_DATA_DIR": str(linked_root)}, clear=True
            ), self.assertRaisesRegex(
                paths.PrivateDataPathError, "component is linked"
            ):
                paths.ensure_data_layout()

    @unittest.skipIf(os.name == "nt", "POSIX symlink contract")
    def test_posix_layout_rejects_linked_configured_root_ancestor(self):
        with tempfile.TemporaryDirectory() as parent, tempfile.TemporaryDirectory() as outside:
            linked_ancestor = Path(parent) / "redirect"
            linked_ancestor.symlink_to(Path(outside), target_is_directory=True)
            configured = linked_ancestor / "onyx-data"
            with patch.dict(
                os.environ, {"ONYX_DATA_DIR": str(configured)}, clear=True
            ), self.assertRaisesRegex(
                paths.PrivateDataPathError, "component is linked"
            ):
                paths.ensure_data_layout()

    @unittest.skipIf(os.name == "nt", "POSIX ownership contract")
    def test_posix_layout_rejects_foreign_owned_root(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"ONYX_DATA_DIR": tmp}, clear=True), \
             patch.object(paths.os, "geteuid", return_value=os.geteuid() + 1):
            with self.assertRaisesRegex(
                paths.PrivateDataPathError, "not owner-controlled"
            ):
                paths.ensure_data_layout()

    @unittest.skipIf(os.name == "nt", "POSIX source-checkout mode contract")
    def test_posix_source_checkout_layout_never_chmods_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "source"
            config = checkout / "config"
            config.mkdir(parents=True, mode=0o755)
            os.chmod(checkout, 0o755)
            os.chmod(config, 0o755)

            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(paths, "is_frozen", return_value=False), \
                 patch.object(paths, "resource_root", return_value=checkout):
                root = paths.ensure_data_layout()

            self.assertEqual(root, checkout)
            self.assertEqual(checkout.stat().st_mode & 0o777, 0o755)
            self.assertEqual(config.stat().st_mode & 0o777, 0o755)
            self.assertTrue((checkout / "runtime" / "logs").is_dir())


if __name__ == "__main__":
    unittest.main()
