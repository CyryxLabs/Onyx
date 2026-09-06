from __future__ import annotations

import hashlib
import inspect
import os
import runpy
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core import onyx_live_activation_v9 as live


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v9.pyw"
BOOTSTRAP = ROOT / live.BOOTSTRAP_RELATIVE


class Snapshot:
    display_name = None
    reconciled = True
    state = types.SimpleNamespace(value="unknown")
    name_known = False


class Authority:
    def __init__(self) -> None:
        self.snapshot = Snapshot()

    def reconcile(self):
        return self.snapshot

    def begin_contact(self):
        return "Before we continue, what name should I use for you?"

    def prompt_directive(self):
        return "owner-directive"


def clean_environment() -> dict[str, str]:
    result = dict(os.environ)
    for name in live.CONTROL_FLAGS:
        result.pop(name, None)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def active_environment() -> dict[str, str]:
    result = clean_environment()
    result.update(live.exact_activation_environment())
    return result


def test_v9_truth_table_is_exact_and_bootstrap_empty_environment_is_active():
    launcher = runpy.run_path(str(LAUNCHER), run_name="v9_launcher_contract")
    mode = launcher["_launch_mode"]
    active = live.exact_activation_environment()
    assert mode({}) == "legacy"
    assert mode(active) == "active"
    assert mode(live.exact_rollback_environment()) == "rollback"

    for name in active:
        missing = dict(active)
        missing.pop(name)
        assert mode(missing) == "refuse"
        for ambiguous in ("true", "TRUE", " 1 ", "01"):
            malformed = dict(active)
            malformed[name] = ambiguous
            assert mode(malformed) == "refuse"
    for alias in live.PHASE5_IDENTITY_ALIASES:
        malformed = dict(active)
        malformed[alias] = "onyx-owner"
        assert mode(malformed) == "refuse"

    bootstrap = runpy.run_path(str(BOOTSTRAP), run_name="v9_bootstrap_contract")
    prepared_empty = bootstrap["_bootstrap_environment"]({})
    assert prepared_empty == active
    prepared_dirty = bootstrap["_bootstrap_environment"](
        {
            "PATH": "preserved",
            "CUSTOM": "exact",
            "ONYX_LIVE_ACTIVATION_V7": "1",
            "ONYX_LIVE_ROLLBACK_V8": "1",
            "ONYX_PRINCIPAL_ID": "alias",
        }
    )
    assert prepared_dirty == {"PATH": "preserved", "CUSTOM": "exact", **active}
    assert live.restore_v8_environment(prepared_dirty) == {
        "PATH": "preserved",
        "CUSTOM": "exact",
        **live.v8.exact_activation_environment(),
    }


def test_partial_environment_refuses_before_main_ui_or_v9_import():
    environment = clean_environment()
    environment[live.LIVE_MASTER_FLAG] = "1"
    result = subprocess.run(
        [str(PYTHON), "-B", str(LAUNCHER), "--preflight-only"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "ONYX_LIVE_V9_PREIMPORT_REFUSAL CLEAN" in result.stderr


def test_empty_host_bootstrap_preflight_composes_v8_and_hud_v6_without_network():
    result = subprocess.run(
        [str(PYTHON), "-B", str(BOOTSTRAP), "--preflight-only"],
        cwd=ROOT,
        env=clean_environment(),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_V9_HOST_PREFLIGHT_OK" in result.stdout
    assert "hud=v6" in result.stdout
    assert "shortcut=bootstrap-v9" in result.stdout
    assert "network_calls=0" in result.stdout


def test_preflight_makes_no_network_socket_call():
    script = f"""
import core.onyx_live_activation_v9
import runpy
import socket
import sys
class NoNetworkSocket(socket.socket):
    def connect(self, *args, **kwargs):
        raise AssertionError("network connect attempted during V9 preflight")
    def connect_ex(self, *args, **kwargs):
        raise AssertionError("network connect_ex attempted during V9 preflight")
socket.socket = NoNetworkSocket
sys.argv = [{str(BOOTSTRAP)!r}, "--preflight-only"]
runpy.run_path({str(BOOTSTRAP)!r}, run_name="__main__")
"""
    result = subprocess.run(
        [str(PYTHON), "-B", "-c", script],
        cwd=ROOT,
        env=clean_environment(),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_V9_HOST_PREFLIGHT_OK" in result.stdout
    assert "network_calls=0" in result.stdout


def test_runtime_manifest_pythonw_bootstrap_hash_and_path_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
):
    manifest_hash = live.RUNTIME_MANIFEST_SHA256
    verified = live._verify_runtime_bundle(ROOT)
    assert verified == {
        "pythonw": ROOT / ".venv" / "Scripts" / "pythonw.exe",
        "bootstrap": BOOTSTRAP,
        "launcher": LAUNCHER,
    }
    monkeypatch.setattr(live, "RUNTIME_MANIFEST_SHA256", "0" * 64)
    with pytest.raises(live.ActivationV9Error, match="evidence drift"):
        live._verify_runtime_bundle(ROOT)
    monkeypatch.setattr(live, "RUNTIME_MANIFEST_SHA256", "not-a-hash")
    with pytest.raises(live.ActivationV9Error, match="unbound acceptance/hash"):
        live._verify_runtime_bundle(ROOT)
    monkeypatch.setattr(live, "RUNTIME_MANIFEST_SHA256", manifest_hash)
    monkeypatch.setattr(live, "RUNTIME_MANIFEST_RELATIVE", Path("../manifest.json"))
    with pytest.raises(live.ActivationV9Error, match="noncanonical"):
        live._verify_runtime_bundle(ROOT)


def test_non_windows_active_launch_delegates_exact_v8(monkeypatch: pytest.MonkeyPatch):
    namespace = runpy.run_path(str(LAUNCHER), run_name="v9_delegate_contract")
    observed: list[dict[str, str]] = []
    function_globals = namespace["run"].__globals__
    monkeypatch.setitem(
        function_globals, "_run_v8", lambda env: observed.append(dict(env))
    )
    monkeypatch.setattr(function_globals["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(sys, "argv", [str(LAUNCHER)])
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        namespace["run"]()
    assert len(observed) == 1
    for name, value in live.v8.exact_activation_environment().items():
        assert observed[0][name] == value
    assert live.LIVE_MASTER_FLAG not in observed[0]
    assert live.HUD_V6_FLAG not in observed[0]
    assert observed[0]["PATH"] == environment["PATH"]


def _mock_com(shortcut: object, links: list[str]):
    shell = SimpleNamespace(
        CreateShortCut=lambda value: links.append(value) or shortcut
    )
    client = types.ModuleType("win32com.client")
    client.Dispatch = lambda name: shell if name == "WScript.Shell" else None
    win32com = types.ModuleType("win32com")
    win32com.client = client
    return patch.dict(
        sys.modules,
        {"win32com": win32com, "win32com.client": client},
    )


def test_v9_installs_v6_before_one_mainwindow_and_setup_uses_v9_shortcut(
    monkeypatch: pytest.MonkeyPatch,
):
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui
        from PySide6.QtQuickWidgets import QQuickWidget
        from PySide6.QtWidgets import QApplication

        monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
        original_shortcut = ui.MainWindow._create_desktop_shortcut
        original_host = ui._CinematicHudV5Host
        contract = live.preflight_host(main, environment)
        controller = live.OnyxLiveActivationV9(
            live.ActivationFlagsV9.from_canonical_environ(environment),
            contract,
            authority_factory=Authority,
        )
        try:
            controller.install()
            assert controller.start().value == "ready"
            assert ui._CinematicHudV5Host is not original_host
            assert "instance._create_desktop_shortcut()" in inspect.getsource(
                ui.MainWindow._on_setup_done
            )

            app = QApplication.instance() or QApplication([])
            window = ui.MainWindow("")
            window.show()
            for _ in range(12):
                app.processEvents()
            try:
                widgets = [
                    widget
                    for widget in QApplication.allWidgets()
                    if isinstance(widget, QQuickWidget)
                ]
                assert widgets == [window._v5_host._quick]
                assert (
                    window._v5_host._quick.rootObject().objectName()
                    == "onyxLiveShellV6Root"
                )
            finally:
                window.close()
                window.deleteLater()
                for _ in range(5):
                    app.processEvents()

            calls: list[tuple[str, str, str, str, str]] = []
            logs: list[str] = []
            fake_window = SimpleNamespace(
                _desktop_path=lambda _os: (
                    Path(tempfile.gettempdir()) / "Desktop With Spaces"
                ),
                _create_lnk_windows=lambda *values: calls.append(values),
                _build_onyx_icon=lambda _path: None,
                _log=SimpleNamespace(append_log=logs.append),
            )
            with (
                patch.object(ui, "is_frozen", return_value=False),
                patch(
                    "core.onyx_live_activation_v9.platform.system",
                    return_value="Windows",
                ),
            ):
                ui.MainWindow._create_desktop_shortcut(fake_window)
                ui.MainWindow._create_desktop_shortcut(fake_window)
            assert len(calls) == 2 and calls[0] == calls[1]
            link, target, arguments, working_directory, icon = calls[0]
            assert link.endswith("Desktop With Spaces\\Onyx.lnk")
            assert target == str(ROOT / ".venv" / "Scripts" / "pythonw.exe")
            assert arguments == str(BOOTSTRAP)
            assert "v7" not in arguments.lower() and "v8" not in arguments.lower()
            assert working_directory == str(ROOT)
            assert icon == str(ROOT / "config" / "onyx.ico")
            assert logs == [
                "SYS: Desktop shortcut created for Onyx Live V9.",
                "SYS: Desktop shortcut created for Onyx Live V9.",
            ]

            saved = 0

            def save() -> None:
                nonlocal saved
                saved += 1

            shortcut = SimpleNamespace(save=save)
            links: list[str] = []
            with _mock_com(shortcut, links):
                ui.MainWindow._create_lnk_windows(
                    link, target, arguments, working_directory, icon
                )
            assert links == [link] and saved == 1
            assert shortcut.TargetPath == target
            assert shortcut.Arguments == f'"{arguments}"'
            assert shortcut.WorkingDirectory == working_directory
            assert shortcut.IconLocation == icon

            controller.rollback_installation()
            assert ui._CinematicHudV5Host is original_host
            assert ui.MainWindow._create_desktop_shortcut is not original_shortcut
            assert live.HUD_V6_FLAG not in os.environ
            assert live.LIVE_MASTER_FLAG not in os.environ
            live.v8.ActivationFlagsV8.from_canonical_environ(os.environ)
        finally:
            controller._base.rollback_all()
            live.hud_v6.uninstall_candidate(ui)


@pytest.mark.parametrize("fail_offset", [1, 2, 3])
def test_each_v9_failpoint_restores_exact_installed_v8(
    fail_offset: int,
):
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui

        original_host = ui._CinematicHudV5Host
        original_shortcut = ui.MainWindow._create_desktop_shortcut
        contract = live.preflight_host(main, environment)
        controller = live.OnyxLiveActivationV9(
            live.ActivationFlagsV9.from_canonical_environ(environment),
            contract,
            authority_factory=Authority,
        )
        try:
            with pytest.raises(live.ActivationV9Error):
                controller.install(fail_after=controller.BASE_SEAM_COUNT + fail_offset)
            assert ui._CinematicHudV5Host is original_host
            assert getattr(ui, "_ONYX_HUD_V6_INSTALLATION", None) is None
            assert ui.MainWindow._create_desktop_shortcut is not original_shortcut
            live.v8.ActivationFlagsV8.from_canonical_environ(os.environ)
        finally:
            controller._base.rollback_all()
            live.hud_v6.uninstall_candidate(ui)
        assert ui.MainWindow._create_desktop_shortcut is original_shortcut


def test_v9_frozen_acceptance_roots_remain_exact():
    expected = {
        "core/onyx_live_activation_v8.py": "a088d0c49851699c5486a59a4db6734b8ec81ed7c01ad821bf8a1ea1966486f4",
        "docs/onyx/checkpoints/onyx-live-activation-v8/manifest.json": "ab28f369248df1ed807aeeee15658193a533881bf68fb2268d49692b52c20392",
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V8-E6-001.md": "ee17b06e2f468c94621e7dda913e3dcda6850f3fbce478f0a5200fa9de1f1c0b",
        "core/onyx_hud_orb_v6.py": "ee5f5f62ab0c799313e7b9ffcf7b3f5364af8b1d80d2d126a63fa4b2290b4233",
        "docs/onyx/checkpoints/hud-orb-v6-candidate/manifest.json": "ba034588791b1003a6743bf037ae32a11285adcac7c4084cba1bc5bb3923ae1c",
        "docs/onyx/acceptance/VE-HUD-ORB-V6-C003-E6-001.md": "c9663515321554cec4e69524ee13eb543194562167da6ac21aafb219bcc65d9f",
        "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
        "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
