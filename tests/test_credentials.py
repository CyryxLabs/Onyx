import io
import json
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from core import credentials


class CredentialTests(unittest.TestCase):
    def test_environment_precedence(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "first", "GOOGLE_API_KEY": "second"}, clear=True), \
             patch.object(credentials, "_backend") as backend:
            self.assertEqual(credentials.get(), "first")
            backend.assert_not_called()

    def test_google_environment_fallback(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "google"}, clear=True), \
             patch.object(credentials, "_backend") as backend:
            self.assertEqual(credentials.get(), "google")
            backend.assert_not_called()

    def test_vault_used_without_environment(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(credentials, "_backend", return_value="vault"):
            self.assertEqual(credentials.get(), "vault")

    def test_required_missing_is_safe(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(credentials, "_backend", return_value=None):
            with self.assertRaises(credentials.CredentialError) as caught:
                credentials.get()
        self.assertNotIn("AIza", str(caught.exception))

    def test_set_verifies_constant_time_readback(self):
        calls = []
        with patch.object(credentials, "_backend", side_effect=lambda op, *a: calls.append((op, a)) or ("value" if op == "get" else None)), \
             patch.object(credentials.hmac, "compare_digest", wraps=credentials.hmac.compare_digest) as compare:
            credentials.set(" value ")
        self.assertEqual(calls[0], ("set", ("value",)))
        compare.assert_called_once_with("value", "value")

    def test_set_failed_verification(self):
        with patch.object(credentials, "_backend", side_effect=[None, "wrong"]):
            with self.assertRaises(credentials.CredentialError):
                credentials.set("secret")

    def test_migration_preserves_settings_and_scrubs_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api_keys.json"
            path.write_text(json.dumps({"gemini_api_key": "secret", "os_system": "windows", "live_model": "model"}), encoding="utf-8")
            with patch.object(credentials, "set") as store, \
                 patch.object(credentials, "_backend", return_value="secret"):
                self.assertTrue(credentials.migrate_legacy(path))
            store.assert_called_once_with("secret")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"os_system": "windows", "live_model": "model"})

    def test_migration_never_scrubs_after_failed_store(self):
        original = {"api_key": "secret", "keep": 7}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api_keys.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            with patch.object(credentials, "set", side_effect=credentials.CredentialError("failed")):
                with self.assertRaises(credentials.CredentialError):
                    credentials.migrate_legacy(path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_migration_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api_keys.json"
            path.write_text('{"os_system":"linux"}', encoding="utf-8")
            with patch.object(credentials, "set") as store:
                self.assertFalse(credentials.migrate_legacy(path))
            store.assert_not_called()

    def test_migration_rejects_directory_without_touching_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-a-file"
            path.mkdir()
            with patch.object(credentials, "set") as store:
                with self.assertRaises(credentials.CredentialError):
                    credentials.migrate_legacy(path)
            store.assert_not_called()

    def test_migration_rejects_symlink_and_never_scrubs_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.json"
            link = Path(tmp) / "api_keys.json"
            original = '{"gemini_api_key":"must-remain","keep":true}'
            target.write_text(original, encoding="utf-8")
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            with patch.object(credentials, "set") as store:
                with self.assertRaises(credentials.CredentialError):
                    credentials.migrate_legacy(link)
            store.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_pre_replace_identity_change_fails_without_false_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api_keys.json"
            path.write_text('{"gemini_api_key":"secret","keep":true}', encoding="utf-8")
            real_reject = credentials._reject_unsafe_config_path
            calls = 0

            def changed(candidate):
                nonlocal calls
                info = real_reject(candidate)
                calls += 1
                if calls > 1:
                    values = list(info)
                    values[1] = info.st_ino + 1
                    return os.stat_result(values)
                return info

            with patch.object(credentials, "set"), \
                 patch.object(credentials, "_backend", return_value="secret"), \
                 patch.object(credentials, "_reject_unsafe_config_path", side_effect=changed):
                with self.assertRaises(credentials.CredentialError):
                    credentials.migrate_legacy(path)
            self.assertIn("gemini_api_key", json.loads(path.read_text()))

    def test_settings_reject_secret_and_preserve_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api_keys.json"
            path.write_text('{"live_model":"m"}', encoding="utf-8")
            credentials.save_settings({"os_system": "windows"}, path)
            self.assertEqual(json.loads(path.read_text()), {"live_model": "m", "os_system": "windows"})
            with self.assertRaises(credentials.CredentialError):
                credentials.save_settings({"gemini_api_key": "no"}, path)

    def test_linux_store_never_puts_secret_in_argv(self):
        secret = "never-in-argv"
        with patch.object(credentials, "_run_backend") as run, patch.object(
            credentials.native_vault,
            "_linux_secret_tool",
            return_value=os.path.abspath("secret-tool-test"),
        ):
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            credentials._linux_set(secret)
            argv = run.call_args.args[0]
            self.assertNotIn(secret, argv)
            self.assertIn(secret, run.call_args.kwargs["secret_input"])

    def test_macos_fails_closed_when_native_framework_is_unavailable(self):
        with patch.object(credentials, "_run_backend") as run, \
             patch.object(
                 credentials,
                 "_mac_security",
                 side_effect=credentials.CredentialError("native framework unavailable"),
             ):
            for operation, args in (
                (credentials._mac_get, ()),
                (credentials._mac_set, ("never-in-argv",)),
                (credentials._mac_delete, ()),
            ):
                with self.subTest(operation=operation.__name__), self.assertRaises(credentials.CredentialError):
                    operation(*args)
            run.assert_not_called()

    def test_windows_write_zeroes_mutable_blob(self):
        api = MagicMock()
        api.CredWriteW.return_value = True
        with patch.object(credentials, "_win_api", return_value=api), \
             patch.object(credentials.ctypes, "memset", wraps=credentials.ctypes.memset) as wipe:
            credentials._windows_set("sensitive")
        wipe.assert_called_once()
        self.assertGreater(wipe.call_args.args[2], 0)

    def test_ui_rolls_back_vault_when_settings_write_fails(self):
        import ui

        window = SimpleNamespace(
            _overlay=MagicMock(),
            _log=MagicMock(),
            _ready=False,
            _apply_state=MagicMock(),
        )
        with patch.object(credentials, "get", return_value="old"), \
             patch.object(credentials, "set") as store, \
             patch.object(credentials, "save_settings", side_effect=OSError("secret path")), \
             patch.object(credentials, "delete") as remove:
            ui.MainWindow._on_setup_done(window, "new-secret", "windows", "Alex")
        self.assertEqual(store.call_args_list, [call("new-secret"), call("old")])
        remove.assert_not_called()
        window._overlay.show_error.assert_called_once_with(
            "Secure setup could not update local settings"
        )
        self.assertFalse(window._ready)

    def test_setup_overlay_allows_os_only_when_credential_exists(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        import ui

        app = QApplication.instance() or QApplication([])
        overlay = ui.SetupOverlay(credential_configured=True)
        emitted = []
        overlay.done.connect(lambda key, system, name: emitted.append((key, system, name)))
        overlay._sel_os = "windows"
        overlay._name_input.setText("Alex")
        overlay._submit()
        app.processEvents()
        self.assertEqual(emitted, [("", "windows", "Alex")])
        self.assertFalse(overlay._key_input.isEnabled())

    def test_cli_status_never_outputs_secret(self):
        secret = "output-must-not-contain-this"
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(credentials, "status", return_value={"configured": True, "source": "vault", "backend": "test"}), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(credentials._main(["status"]), 0)
        self.assertNotIn(secret, stdout.getvalue() + stderr.getvalue())

    def test_status_does_not_return_secret(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}, clear=True), \
             patch.object(credentials.platform, "system", return_value="Windows"):
            info = credentials.status()
        self.assertNotIn("secret", json.dumps(info))


if __name__ == "__main__":
    unittest.main()
