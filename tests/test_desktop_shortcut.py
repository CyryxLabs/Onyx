import os
import sys
import tempfile
import types
import unittest
import gc
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui import MainWindow, WINDOWS_APP_USER_MODEL_ID

PROJECT = Path(__file__).resolve().parents[1]


class DesktopShortcutTests(unittest.TestCase):
    @staticmethod
    def _mock_wscript_desktop(path: Path):
        shell = SimpleNamespace(
            SpecialFolders=lambda name: str(path) if name == "Desktop" else ""
        )
        client = types.ModuleType("win32com.client")
        client.Dispatch = lambda name: shell if name == "WScript.Shell" else None
        win32com = types.ModuleType("win32com")
        win32com.client = client
        return patch.dict(
            sys.modules,
            {"win32com": win32com, "win32com.client": client},
        )

    def test_windows_source_shortcut_uses_diagnostic_launcher(self):
        calls = []
        window = SimpleNamespace(
            _create_lnk_windows=lambda *args: calls.append(args),
            _build_onyx_icon=lambda _path: self.fail(
                "the checked-in official icon must be reused"
            ),
            _log=SimpleNamespace(append_log=lambda _message: None),
        )
        window._desktop_path = lambda current_os: MainWindow._desktop_path(
            window, current_os
        )

        with tempfile.TemporaryDirectory() as tmp, patch(
            "ui.is_frozen", return_value=False
        ), patch("ui.platform.system", return_value="Windows"), patch(
            "ui.Path.home", return_value=Path(tmp) / "wrong-home"
        ), self._mock_wscript_desktop(
            Path(tmp) / "Redirected Desktop"
        ):
            MainWindow._create_desktop_shortcut(window)

        self.assertEqual(len(calls), 1)
        lnk, target, args, work_dir, icon_loc = calls[0]
        self.assertEqual(lnk, str(Path(tmp) / "Redirected Desktop" / "Onyx.lnk"))
        self.assertEqual(
            target,
            str(PROJECT / ".venv" / "Scripts" / "pythonw.exe"),
        )
        self.assertEqual(args, str(PROJECT / "scripts" / "launch_onyx.pyw"))
        self.assertEqual(work_dir, str(PROJECT))
        self.assertEqual(icon_loc, str(PROJECT / "config" / "onyx.ico"))

    def test_windows_frozen_shortcut_uses_active_desktop_and_packaged_binary(self):
        calls = []
        log = []
        window = SimpleNamespace(
            _create_lnk_windows=lambda *args: calls.append(args),
            _log=SimpleNamespace(append_log=log.append),
        )
        window._desktop_path = lambda current_os: MainWindow._desktop_path(
            window, current_os
        )
        packaged = PROJECT / "dist" / "Onyx" / "Onyx.exe"

        with tempfile.TemporaryDirectory() as tmp, patch(
            "ui.is_frozen", return_value=True
        ), patch("ui.platform.system", return_value="Windows"), patch(
            "ui.sys.executable", str(packaged)
        ), patch(
            "ui.Path.home", return_value=Path(tmp) / "wrong-home"
        ), self._mock_wscript_desktop(
            Path(tmp) / "Redirected Desktop"
        ):
            MainWindow._create_desktop_shortcut(window)

        self.assertEqual(
            calls,
            [
                (
                    str(Path(tmp) / "Redirected Desktop" / "Onyx.lnk"),
                    str(packaged),
                    "",
                    str(packaged.parent),
                    f"{packaged},0",
                )
            ],
        )
        self.assertIn("SYS: Desktop shortcut created.", log)

    def test_windows_desktop_resolution_logs_explicit_fallback(self):
        log = []
        window = SimpleNamespace(_log=SimpleNamespace(append_log=log.append))
        client = types.ModuleType("win32com.client")
        client.Dispatch = lambda _name: (_ for _ in ()).throw(
            RuntimeError("COM unavailable")
        )
        win32com = types.ModuleType("win32com")
        win32com.client = client

        with tempfile.TemporaryDirectory() as tmp, patch(
            "ui.Path.home", return_value=Path(tmp)
        ), patch.dict(sys.modules, {"win32com": win32com, "win32com.client": client}):
            resolved = MainWindow._desktop_path(window, "Windows")

        self.assertEqual(resolved, Path(tmp) / "Desktop")
        self.assertEqual(len(log), 1)
        self.assertIn("Active Windows Desktop resolution failed", log[0])
        self.assertIn(str(Path(tmp) / "Desktop"), log[0])

    def test_windows_lnk_quotes_launcher_argument_with_mock_com(self):
        shortcut = SimpleNamespace(save=lambda: None)
        shell = SimpleNamespace(CreateShortCut=lambda _path: shortcut)
        client = types.ModuleType("win32com.client")
        client.Dispatch = lambda name: shell if name == "WScript.Shell" else None
        win32com = types.ModuleType("win32com")
        win32com.client = client

        launcher = str(PROJECT / "scripts" / "launch_onyx.pyw")
        with patch.dict(
            sys.modules,
            {"win32com": win32com, "win32com.client": client},
        ):
            MainWindow._create_lnk_windows(
                "isolated-test.lnk",
                str(PROJECT / ".venv" / "Scripts" / "pythonw.exe"),
                launcher,
                str(PROJECT),
                str(PROJECT / "config" / "onyx.ico"),
            )

        self.assertEqual(shortcut.Arguments, f'"{launcher}"')
        self.assertEqual(shortcut.WorkingDirectory, str(PROJECT))
        self.assertEqual(
            shortcut.IconLocation,
            str(PROJECT / "config" / "onyx.ico"),
        )

    def test_windows_lnk_does_not_quote_an_empty_frozen_argument(self):
        shortcut = SimpleNamespace(save=lambda: None)
        shell = SimpleNamespace(CreateShortCut=lambda _path: shortcut)
        client = types.ModuleType("win32com.client")
        client.Dispatch = lambda name: shell if name == "WScript.Shell" else None
        win32com = types.ModuleType("win32com")
        win32com.client = client

        with patch.dict(
            sys.modules,
            {"win32com": win32com, "win32com.client": client},
        ):
            MainWindow._create_lnk_windows(
                "isolated-frozen-test.lnk",
                str(PROJECT / "dist" / "Onyx" / "Onyx.exe"),
                "",
                str(PROJECT / "dist" / "Onyx"),
                str(PROJECT / "config" / "onyx.ico"),
            )

        self.assertEqual(shortcut.Arguments, "")

    @unittest.skipUnless(sys.platform == "win32", "Windows property store only")
    def test_windows_real_shortcut_has_onyx_taskbar_identity(self):
        import pythoncom
        from win32com.propsys import propsys, pscon
        from win32com.shell import shellcon

        pythoncom.CoInitialize()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                link = Path(temporary) / "Onyx.lnk"
                MainWindow._create_lnk_windows(
                    str(link),
                    str(PROJECT / ".venv" / "Scripts" / "pythonw.exe"),
                    str(PROJECT / "scripts" / "launch_onyx.pyw"),
                    str(PROJECT),
                    str(PROJECT / "config" / "onyx.ico"),
                )
                gc.collect()
                store = propsys.SHGetPropertyStoreFromParsingName(
                    str(link),
                    None,
                    shellcon.GPS_DEFAULT,
                    propsys.IID_IPropertyStore,
                )
                value = store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue()
                self.assertEqual(value, WINDOWS_APP_USER_MODEL_ID)
        finally:
            pythoncom.CoUninitialize()


if __name__ == "__main__":
    unittest.main()
