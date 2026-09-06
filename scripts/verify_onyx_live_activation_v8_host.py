"""Fresh-process shortcut and host gate for Onyx Live Activation V8."""

from __future__ import annotations

import runpy
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core import onyx_live_activation_v8 as live  # noqa: E402


LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v8.pyw"
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


def _host_seams(contract: live.HostContractV8) -> tuple[object, ...]:
    module = contract.module
    host = contract.base.base.onyx_live
    window = contract.main_window
    return (
        module._load_owner_name,
        module._load_system_prompt,
        module.TOOL_DECLARATIONS,
        host.__init__,
        host._start_phase5_session,
        host._stop_phase5_session,
        host._execute_tool,
        host._send_realtime,
        host._on_text_command,
        host._process_dashboard_commands,
        host._run_live_loop,
        window._create_desktop_shortcut,
        window._configured_owner_name,
        window._show_setup,
        window._on_setup_done,
        window.__init__,
        window.closeEvent,
    )


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


def run() -> None:
    environment = live.exact_activation_environment()
    launcher = runpy.run_path(str(LAUNCHER), run_name="v8_host_gate")
    launch_mode = launcher["_launch_mode"]
    assert launch_mode({}) == "legacy"
    assert launch_mode(environment) == "active"
    assert launch_mode(live.exact_rollback_environment()) == "rollback"

    refused = 0
    for name in (
        live.LIVE_MASTER_FLAG,
        *live.CHILD_FLAGS,
        *live.PHASE5_IDENTITY_FLAGS,
    ):
        candidate = dict(environment)
        candidate.pop(name)
        assert launch_mode(candidate) == "refuse"
        refused += 1
    for name in live.PHASE5_IDENTITY_FLAGS:
        candidate = dict(environment)
        candidate[name] += "-wrong"
        assert launch_mode(candidate) == "refuse"
        refused += 1
    for alias in live.PHASE5_IDENTITY_ALIASES:
        candidate = dict(environment)
        candidate[alias] = "onyx-owner"
        assert launch_mode(candidate) == "refuse"
        refused += 1

    bootstrap = runpy.run_path(str(BOOTSTRAP), run_name="v8_bootstrap_gate")
    prepared = bootstrap["_bootstrap_environment"](
        {
            "PATH": "preserved",
            "ONYX_LIVE_ACTIVATION_V7": "1",
            "ONYX_LIVE_ROLLBACK_V5": "1",
            "ONYX_PRINCIPAL_ID": "alias",
        }
    )
    assert prepared["PATH"] == "preserved"
    assert launch_mode(prepared) == "active"
    assert prepared == {"PATH": "preserved", **environment}

    contract = live.preflight_host(main, environment)
    original = _host_seams(contract)
    failed = live.OnyxLiveActivationV8(
        live.ActivationFlagsV8.from_canonical_environ(environment),
        contract,
        authority_factory=Authority,
    )
    try:
        failed.install(fail_after=failed.TOTAL_SEAM_COUNT)
    except live.ActivationV8Error:
        pass
    else:
        raise AssertionError("V8 seam failpoint was not injected")
    post_v7 = _host_seams(contract)
    assert post_v7 != original
    assert post_v7[11] is original[11]
    failed._base.rollback_installation()
    assert _host_seams(contract) == original

    controller = live.OnyxLiveActivationV8(
        live.ActivationFlagsV8.from_canonical_environ(environment),
        live.preflight_host(main, environment),
        authority_factory=Authority,
    )
    controller.install()
    assert controller.start().value == "ready"
    v8_installed = _host_seams(controller.contract)
    assert v8_installed != original
    assert v8_installed[11] is not original[11]

    calls: list[tuple[str, str, str, str, str]] = []
    logs: list[str] = []
    window = SimpleNamespace(
        _desktop_path=lambda _os: Path(tempfile.gettempdir()) / "Desktop With Spaces",
        _create_lnk_windows=lambda *values: calls.append(values),
        _build_onyx_icon=lambda _path: (_ for _ in ()).throw(
            AssertionError("official icon should be reused")
        ),
        _log=SimpleNamespace(append_log=logs.append),
    )
    with (
        patch.object(controller.contract.ui_module, "is_frozen", return_value=False),
        patch("core.onyx_live_activation_v8.platform.system", return_value="Windows"),
    ):
        controller.contract.main_window._create_desktop_shortcut(window)
        controller.contract.main_window._create_desktop_shortcut(window)
    assert len(calls) == 2 and calls[0] == calls[1]
    link, target, arguments, working_directory, icon = calls[0]
    assert link.endswith("Desktop With Spaces\\Onyx.lnk")
    assert target == str(ROOT / ".venv" / "Scripts" / "pythonw.exe")
    assert arguments == str(BOOTSTRAP)
    assert arguments != str(ROOT / live.LEGACY_LAUNCHER_RELATIVE)
    assert working_directory == str(ROOT)
    assert icon == str(ROOT / "config" / "onyx.ico")
    assert logs == [
        "SYS: Desktop shortcut created for Onyx Live V8.",
        "SYS: Desktop shortcut created for Onyx Live V8.",
    ]

    saved = 0

    def save() -> None:
        nonlocal saved
        saved += 1

    shortcut = SimpleNamespace(save=save)
    links: list[str] = []
    with _mock_com(shortcut, links):
        controller.contract.main_window._create_lnk_windows(
            link, target, arguments, working_directory, icon
        )
    assert links == [link]
    assert saved == 1
    assert shortcut.TargetPath == target
    assert shortcut.Arguments == f'"{arguments}"'
    assert shortcut.WorkingDirectory == working_directory
    assert shortcut.IconLocation == icon

    packaged_calls: list[tuple[str, str, str, str, str]] = []
    packaged = ROOT / "dist" / "Onyx" / "Onyx.exe"
    packaged_window = SimpleNamespace(
        _desktop_path=lambda _os: Path(tempfile.gettempdir()) / "Packaged Desktop",
        _create_lnk_windows=lambda *values: packaged_calls.append(values),
        _log=SimpleNamespace(append_log=lambda _message: None),
    )
    with (
        patch.object(controller.contract.ui_module, "is_frozen", return_value=True),
        patch("core.onyx_live_activation_v8.platform.system", return_value="Windows"),
        patch.object(controller.contract.ui_module.sys, "executable", str(packaged)),
    ):
        controller.contract.main_window._create_desktop_shortcut(packaged_window)
    assert packaged_calls == [
        (
            str(Path(tempfile.gettempdir()) / "Packaged Desktop" / "Onyx.lnk"),
            str(packaged),
            "",
            str(packaged.parent),
            f"{packaged},0",
        )
    ]

    controller.rollback_installation()
    post_v8_rollback = _host_seams(controller.contract)
    assert post_v8_rollback[11] is original[11]
    assert post_v8_rollback != original
    controller._base.rollback_installation()
    assert _host_seams(controller.contract) == original

    print("ONYX_LIVE_ACTIVATION_V8_SHORTCUT_OK")
    print(
        f"canonical_identities=4 refused_variants={refused} seams=24 "
        "rollback=post-v7-exact idempotent=2x com_quoting=pass "
        "shortcut=bootstrap-v8 bootstrap_mode=active hud=v5 "
        "legacy_launcher=forbidden frozen_behavior=preserved "
        "network_calls=0 live_activation=not_performed"
    )


if __name__ == "__main__":
    run()
