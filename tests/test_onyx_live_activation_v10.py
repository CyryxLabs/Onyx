from __future__ import annotations

import hashlib
import inspect
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from core import onyx_live_activation_v10 as live


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/Scripts/python.exe"
LAUNCHER = ROOT / live.CANONICAL_LAUNCHER_RELATIVE
BOOTSTRAP = ROOT / live.BOOTSTRAP_RELATIVE


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


def test_truth_table_and_empty_bootstrap_are_exact_v10_with_hud_v7_gate():
    launcher = runpy.run_path(str(LAUNCHER), run_name="v10_launcher_contract")
    mode = launcher["_launch_mode"]
    active = live.exact_activation_environment()
    assert mode({}) == "legacy"
    assert mode(active) == "active"
    assert mode(live.exact_rollback_environment()) == "rollback"
    assert active[live.HUD_V7_FLAG] == "1"
    assert active[live.WIRING_FLAG] == "true"

    for name in active:
        missing = dict(active)
        missing.pop(name)
        assert mode(missing) == "refuse"
        malformed_values = (
            ("TRUE", "1", " 1 ", "01")
            if active[name] == "true"
            else ("TRUE", "true", " 1 ", "01")
        )
        for ambiguous in malformed_values:
            malformed = dict(active)
            malformed[name] = ambiguous
            assert mode(malformed) == "refuse"

    bootstrap = runpy.run_path(str(BOOTSTRAP), run_name="v10_bootstrap_contract")
    assert bootstrap["_bootstrap_environment"]({}) == active
    dirty = bootstrap["_bootstrap_environment"](
        {
            "PATH": "preserved",
            "CUSTOM": "exact",
            "ONYX_LIVE_ACTIVATION_V8": "wrong",
            "ONYX_LIVE_ROLLBACK_V9": "1",
            "ONYX_HUD_V7_LIVE": "TRUE",
        }
    )
    assert dirty == {"PATH": "preserved", "CUSTOM": "exact", **active}
    assert live.restore_v9_environment(dirty) == {
        "PATH": "preserved",
        "CUSTOM": "exact",
        **live.v9.exact_activation_environment(),
    }


def test_missing_or_ambiguous_hud_v7_flag_refuses_before_host_import():
    environment = active_environment()
    environment.pop(live.HUD_V7_FLAG)
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
    assert "ONYX_LIVE_V10_PREIMPORT_REFUSAL CLEAN" in result.stderr


def test_exact_hud_v7_e6_gate_passes_before_main_and_state_writes():
    script = f"""
import os, sys
from pathlib import Path
from core.onyx_live_activation_v10 import verify_activation_prerequisites
verify_activation_prerequisites(Path({str(ROOT)!r}), os.environ)
print("HUD_V7_E6_PREFLIGHT_OK")
print("HOST_IMPORT", "DIRTY" if "main" in sys.modules or "ui" in sys.modules else "CLEAN")
"""
    state_root = ROOT / live.STATE_ROOT_RELATIVE
    existed = state_root.exists()
    result = subprocess.run(
        [str(PYTHON), "-B", "-c", script],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HUD_V7_E6_PREFLIGHT_OK" in result.stdout
    assert "HOST_IMPORT CLEAN" in result.stdout
    assert state_root.exists() is existed


def test_bootstrap_from_empty_environment_reaches_host_preflight_without_activation():
    result = subprocess.run(
        [str(PYTHON), "-B", str(BOOTSTRAP), "--preflight-only"],
        cwd=ROOT,
        env=clean_environment(),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "ONYX_LIVE_V10_HOST_PREFLIGHT_OK" in output
    assert "live_activation" not in output


def test_accepted_preflight_makes_no_network_socket_call():
    script = f"""
import runpy, socket, sys
class NoNetworkSocket(socket.socket):
    def connect(self, *args, **kwargs):
        raise AssertionError("network connect attempted")
    def connect_ex(self, *args, **kwargs):
        raise AssertionError("network connect_ex attempted")
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
    output = result.stdout + result.stderr
    assert "network connect attempted" not in output
    assert "ONYX_LIVE_V10_HOST_PREFLIGHT_OK" in output


def test_runtime_manifest_is_hash_bound_and_path_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
):
    verified = live._verify_runtime_bundle(ROOT)
    assert verified == {
        "pythonw": ROOT / ".venv/Scripts/pythonw.exe",
        "bootstrap": BOOTSTRAP,
        "launcher": LAUNCHER,
    }
    expected = live.RUNTIME_MANIFEST_SHA256
    monkeypatch.setattr(live, "RUNTIME_MANIFEST_SHA256", "not-bound")
    with pytest.raises(live.ActivationV10Error, match="unbound acceptance/hash"):
        live._verify_runtime_bundle(ROOT)
    monkeypatch.setattr(live, "RUNTIME_MANIFEST_SHA256", expected)
    monkeypatch.setattr(live, "RUNTIME_MANIFEST_RELATIVE", Path("../manifest.json"))
    with pytest.raises(live.ActivationV10Error, match="noncanonical"):
        live._verify_runtime_bundle(ROOT)


def test_non_windows_active_launch_delegates_exact_v9(
    monkeypatch: pytest.MonkeyPatch,
):
    namespace = runpy.run_path(str(LAUNCHER), run_name="v10_delegate_contract")
    observed: list[dict[str, str]] = []
    globals_ = namespace["run"].__globals__
    monkeypatch.setitem(globals_, "_run_v9", lambda env: observed.append(dict(env)))
    monkeypatch.setattr(globals_["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(sys, "argv", [str(LAUNCHER)])
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        namespace["run"]()
    assert len(observed) == 1
    for name, value in live.v9.exact_activation_environment().items():
        assert observed[0][name] == value
    assert live.LIVE_MASTER_FLAG not in observed[0]
    assert live.WIRING_FLAG not in observed[0]
    assert live.HUD_V7_FLAG not in observed[0]


def test_modular_order_is_v9_hud_v7_wiring_v10_shortcut_before_main():
    install = inspect.getsource(live.OnyxLiveActivationV10.install)
    positions = [
        install.index("self._base.install"),
        install.index("self._base.start"),
        install.index("_load_accepted_hud_v7"),
        install.index("_prepare_state_root"),
        install.index("create_phase6_live_wiring_v1"),
        install.index("controller.install"),
        install.index("window_type._create_desktop_shortcut ="),
        install.index("window_type._on_setup_done ="),
        install.index("window_type._check_config ="),
        install.index("window_type.__init__ ="),
    ]
    assert positions == sorted(positions)
    assert "activation = self._base._base._base" in inspect.getsource(
        live.OnyxLiveActivationV10._embedded_v7
    )
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert launcher.index("verify_activation_prerequisites") < launcher.index(
        "import main as onyx_main"
    )
    assert launcher.index("activate_main(onyx_main)") < launcher.index(
        "onyx_main.main()"
    )


def test_no_phase6_user_route_or_protected_seam_overclaim_is_added():
    source = Path(live.__file__).read_text(encoding="utf-8")
    for route in (
        "ui.write_log",
        "command_route",
        "provider_call",
        "planner_route",
    ):
        assert route not in source
    for protected in ("_execute_tool =", "_run_live_loop =", "_send_realtime ="):
        assert protected not in source
    assert live.OnyxLiveActivationV10.TOTAL_SEAM_COUNT == 35


def test_hud_v7_binding_has_four_exact_paths_and_accepted_hashes():
    assert tuple(path for path, _digest in live.HUD_V7_ACCEPTED_ROOTS) == (
        Path("core/onyx_hud_orb_v7.py"),
        Path("docs/onyx/checkpoints/hud-orb-v7-candidate/manifest.json"),
        Path("docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.md"),
        Path("docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json"),
    )
    assert dict(live.HUD_V7_ACCEPTED_ROOTS) == {
        Path("core/onyx_hud_orb_v7.py"): (
            "31fd7d0df7413ac9dbba3db463de28390bdfaa75e2173dae54c04dfd82a6c150"
        ),
        Path("docs/onyx/checkpoints/hud-orb-v7-candidate/manifest.json"): (
            "38f77492b6b72eeb8bff8c1bddbe129081bbe79e67b7f8679054d86dff781f03"
        ),
        Path("docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.md"): (
            "1ef23e14d42a9ff199115cbf1615e68318b492978487d90a1b6cc61c74a32a3d"
        ),
        Path("docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json"): (
            "ef17dfcdb63ebd3b48dcfcb1feb2c0b76a300bd86ff7ae3cdbbae87f94118500"
        ),
    }
    exact = {
        path.as_posix(): f"{index:x}".zfill(64)
        for index, path in enumerate(live.HUD_V7_ACCEPTED_PATHS, start=1)
    }
    assert live.bind_hud_v7_accepted_roots(exact) == tuple(
        (path, exact[path.as_posix()]) for path in live.HUD_V7_ACCEPTED_PATHS
    )
    reordered = dict(reversed(tuple(exact.items())))
    with pytest.raises(live.ActivationV10Error, match="four exact ordered paths"):
        live.bind_hud_v7_accepted_roots(reordered)
    with pytest.raises(live.ActivationV10Error, match="invalid HUD V7 binding"):
        live.bind_hud_v7_accepted_roots(
            {**exact, exact.keys().__iter__().__next__(): "1"}
        )


def _hud_contract_controller(ui_module: ModuleType) -> live.OnyxLiveActivationV10:
    main_window = type("WindowContract", (), {})
    controller = object.__new__(live.OnyxLiveActivationV10)
    controller.contract = SimpleNamespace(
        ui_module=ui_module,
        module=ModuleType("host"),
        main_window=main_window,
        project=ROOT,
    )
    controller._base = SimpleNamespace(
        install=lambda **_kwargs: None, start=lambda: None
    )
    controller._wiring = None
    controller._hud_v7_module = None
    controller._shortcut_v9 = None
    controller._setup_v9 = None
    controller._check_config_v9 = None
    controller._init_v9 = None
    return controller


def test_real_hud_v7_contract_installs_and_rolls_back_with_exact_one_arg(
    monkeypatch: pytest.MonkeyPatch,
):
    ui_module = ModuleType("ui_contract")
    calls: list[tuple[str, ModuleType]] = []
    hud = ModuleType("core.onyx_hud_orb_v7")

    def uninstall(ui: ModuleType) -> bool:
        calls.append(("uninstall", ui))
        return True

    def install(ui: ModuleType) -> bool:
        calls.append(("install", ui))
        hud.uninstall_candidate = lambda _ui: False
        return True

    hud.install_candidate = install
    hud.uninstall_candidate = uninstall
    controller = _hud_contract_controller(ui_module)
    monkeypatch.setattr(
        live,
        "_load_accepted_hud_v7",
        lambda _project: (hud, install, uninstall),
    )

    with pytest.raises(live.ActivationV10Error, match="injected V10 HUD V7"):
        controller.install(fail_after=controller.BASE_SEAM_COUNT + 1)

    assert calls == [("install", ui_module), ("uninstall", ui_module)]
    assert controller._hud_v7_module is None


def test_hud_v7_contract_rejects_truthy_non_bool_install_result(
    monkeypatch: pytest.MonkeyPatch,
):
    ui_module = ModuleType("ui_contract")
    hud = ModuleType("core.onyx_hud_orb_v7")
    hud.install_candidate = lambda _ui: 1
    hud.uninstall_candidate = lambda _ui: True
    controller = _hud_contract_controller(ui_module)
    monkeypatch.setattr(
        live,
        "_load_accepted_hud_v7",
        lambda _project: (
            hud,
            hud.install_candidate,
            hud.uninstall_candidate,
        ),
    )

    with pytest.raises(live.ActivationV10Error, match="installation was not exact"):
        controller.install(fail_after=controller.BASE_SEAM_COUNT + 1)
    assert controller._hud_v7_module is None


def test_hud_v7_in_memory_module_and_function_spoof_are_denied(
    monkeypatch: pytest.MonkeyPatch,
):
    from core import onyx_hud_orb_v7 as canonical

    spoof = ModuleType("core.onyx_hud_orb_v7")
    spoof.__file__ = str(ROOT / "core/onyx_hud_orb_v7.py")
    spoof.install_candidate = lambda _ui: True
    spoof.uninstall_candidate = lambda _ui: True

    def poisoned_helper(_ui: object) -> object:
        return object()

    monkeypatch.setattr(canonical, "_accepted_v6_host", poisoned_helper)
    monkeypatch.setitem(sys.modules, "core.onyx_hud_orb_v7", spoof)
    module, install_hud, uninstall_hud = live._load_accepted_hud_v7(ROOT)
    assert module is not spoof
    assert install_hud.__globals__ is uninstall_hud.__globals__
    assert install_hud.__globals__["_accepted_v6_host"] is not poisoned_helper
    assert install_hud.__globals__["_ACTIVE_INSTALLATIONS"] == {}


def _copy_v10_evidence_closure(destination: Path) -> None:
    manifest = json.loads(
        (ROOT / "docs/onyx/checkpoints/hud-orb-v7-candidate/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    paths = {
        *(path for path, _digest in live.ACCEPTED_ROOTS),
        *(path for path, _digest in live.HUD_V7_ACCEPTED_ROOTS),
        *(Path(record["path"]) for record in manifest["artifacts"]),
        *(Path(path) for path in manifest["frozen_anchors"]),
    }
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


@pytest.mark.parametrize(
    "relative",
    [path for path, _digest in live.HUD_V7_ACCEPTED_ROOTS],
)
def test_each_hud_v7_accepted_root_tamper_fails_closed(
    tmp_path: Path,
    relative: Path,
):
    _copy_v10_evidence_closure(tmp_path)
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(live.ActivationV10Error):
        live._verify_accepted_roots(tmp_path)


@pytest.mark.parametrize(
    "relative", [Path(path) for path in live.HUD_V7_ARTIFACT_PATHS]
)
def test_each_hud_v7_leaf_tamper_fails_closed(
    tmp_path: Path,
    relative: Path,
):
    _copy_v10_evidence_closure(tmp_path)
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(live.ActivationV10Error):
        live._verify_accepted_roots(tmp_path)


def test_cmd_double_click_root_and_configured_owner_shortcut_refresh():
    for relative in (
        "scripts/launch_onyx_live_v10_active.cmd",
        "scripts/launch_onyx_live_v10_rollback.cmd",
    ):
        lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
        assert lines[:2] == ["@echo off", 'cd /d "%~dp0.."']
        assert '".venv\\Scripts\\pythonw.exe"' in lines[-1]

    verifier = (ROOT / "scripts/verify_onyx_live_activation_v10.py").read_text(
        encoding="utf-8"
    )
    assert "tempfile.mkdtemp" in verifier
    assert 'prefix=".pytest-onyx-live-v10-verifier-"' in verifier
    assert '"--basetemp",\n                str(base_temp),' in verifier

    calls: list[str] = []
    configured = SimpleNamespace(
        _ready=True,
        _overlay=None,
        _create_desktop_shortcut=lambda: calls.append("refresh"),
    )
    live._refresh_configured_shortcut(configured)
    assert calls == ["refresh"]
    configured._ready = False
    live._refresh_configured_shortcut(configured)
    assert calls == ["refresh"]


def test_secure_onboarding_accepts_only_secure_valid_unknown_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from core import credentials

    config = tmp_path / "settings.json"
    ui_module = ModuleType("ui_onboarding_contract")
    ui_module.API_FILE = config
    status = {"configured": True}
    monkeypatch.setattr(credentials, "status", lambda: dict(status))

    original_calls: list[object] = []

    def original_check(instance: object) -> bool:
        original_calls.append(instance)
        return False

    instance = object()
    for owner_name in ("", "Sir", "Efendim", "unknown"):
        config.write_text(
            json.dumps({"os_system": "windows", "owner_name": owner_name}),
            encoding="utf-8",
        )
        assert (
            live._secure_onboarding_ready(ui_module, original_check, instance) is True
        )

    config.write_text(
        json.dumps({"os_system": "windows", "owner_name": "Actual Name"}),
        encoding="utf-8",
    )
    assert live._secure_onboarding_ready(ui_module, original_check, instance) is False
    assert (
        live._secure_onboarding_ready(ui_module, lambda _instance: True, instance)
        is True
    )

    config.write_text(
        json.dumps({"os_system": "", "owner_name": ""}),
        encoding="utf-8",
    )
    assert live._secure_onboarding_ready(ui_module, original_check, instance) is False
    config.write_text(
        json.dumps({"os_system": "plan9", "owner_name": ""}),
        encoding="utf-8",
    )
    assert live._secure_onboarding_ready(ui_module, original_check, instance) is False
    config.write_text(
        json.dumps({"os_system": "windows", "owner_name": ""}),
        encoding="utf-8",
    )
    status["configured"] = False
    assert live._secure_onboarding_ready(ui_module, original_check, instance) is False
    status["configured"] = True
    config.write_text("{", encoding="utf-8")
    assert live._secure_onboarding_ready(ui_module, original_check, instance) is False
    assert len(original_calls) == 9


def test_onboarding_rollback_uses_private_immutable_authority() -> None:
    class Window:
        pass

    def original_check(_instance: object) -> bool:
        return False

    def poison_check(_instance: object) -> bool:
        return True

    Window._check_config = poison_check
    controller = object.__new__(live.OnyxLiveActivationV10)
    controller.contract = SimpleNamespace(
        main_window=Window,
        ui_module=ModuleType("ui"),
        module=ModuleType("host"),
    )
    controller._hud_v7_module = None
    controller._wiring = None
    controller._shortcut_v9 = None
    controller._setup_v9 = None
    controller._check_config_v9 = poison_check
    controller._init_v9 = None
    authority = live._RollbackAuthorityV10(
        controller=controller,
        main_window=Window,
        hud_module=ModuleType("hud"),
        uninstall_hud=lambda _ui: True,
        check_config_v9=original_check,
    )
    live._ROLLBACK_AUTHORITIES[id(controller)] = authority
    controller._check_config_v9 = object()
    with patch.dict(os.environ, active_environment(), clear=True):
        controller.rollback_installation()
    assert Window._check_config is original_check
    assert controller._check_config_v9 is None


def test_real_onboarding_failpoint_restores_exact_v9_check_config() -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui

        class Snapshot:
            display_name = None
            reconciled = True
            state = SimpleNamespace(value="unknown")
            name_known = False

        class Authority:
            def __init__(self) -> None:
                self.snapshot = Snapshot()

            def reconcile(self) -> Snapshot:
                return self.snapshot

            def begin_contact(self) -> str:
                return "Before we continue, what name should I use for you?"

            def prompt_directive(self) -> str:
                return "owner-directive"

        contract = live.preflight_host(main, environment)
        controller = live.OnyxLiveActivationV10(
            live.ActivationFlagsV10.from_canonical_environ(environment),
            contract,
            authority_factory=Authority,
        )
        original_check = ui.MainWindow._check_config
        try:
            with pytest.raises(
                live.ActivationV10Error,
                match="injected V10 onboarding seam failure",
            ):
                controller.install(fail_after=controller.TOTAL_SEAM_COUNT - 1)
            assert ui.MainWindow._check_config is original_check
            assert controller._check_config_v9 is None
            assert id(controller) not in live._ROLLBACK_AUTHORITIES
        finally:
            controller._base.rollback_all()


def test_real_host_unknown_owner_ready_and_denials_show_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui
        from core import credentials
        from PySide6.QtWidgets import QApplication

        class Snapshot:
            display_name = None
            reconciled = True
            state = SimpleNamespace(value="unknown")
            name_known = False

        class Authority:
            def __init__(self) -> None:
                self.snapshot = Snapshot()

            def reconcile(self) -> Snapshot:
                return self.snapshot

            def begin_contact(self) -> str:
                return "Before we continue, what name should I use for you?"

            def prompt_directive(self) -> str:
                return "owner-directive"

        config = tmp_path / "api_keys.json"
        status = {"configured": True}
        contract = live.preflight_host(main, environment)
        controller = live.OnyxLiveActivationV10(
            live.ActivationFlagsV10.from_canonical_environ(environment),
            contract,
            authority_factory=Authority,
        )
        shortcut_calls: list[tuple[str, str, str, str, str]] = []
        app = QApplication.instance() or QApplication([])
        original_api_file = ui.API_FILE
        try:
            controller.install()
            monkeypatch.setattr(ui, "API_FILE", config)
            monkeypatch.setattr(credentials, "status", lambda: dict(status))
            monkeypatch.setattr(live.platform, "system", lambda: "Windows")
            monkeypatch.setattr(
                ui.MainWindow,
                "_create_lnk_windows",
                staticmethod(lambda *values: shortcut_calls.append(values)),
            )

            scenarios = (
                (
                    {"os_system": "windows", "owner_name": ""},
                    True,
                    True,
                ),
                (
                    {"os_system": "windows", "owner_name": ""},
                    False,
                    False,
                ),
                (
                    {"owner_name": ""},
                    True,
                    False,
                ),
            )
            for settings, credential_ready, expected_ready in scenarios:
                config.write_text(json.dumps(settings), encoding="utf-8")
                status["configured"] = credential_ready
                window = ui.MainWindow("")
                try:
                    for _ in range(8):
                        app.processEvents()
                    assert window._ready is expected_ready
                    assert (window._overlay is None) is expected_ready
                    if expected_ready:
                        assert window._configured_owner_name() == "Sir"
                finally:
                    window.close()
                    window.deleteLater()
                    for _ in range(3):
                        app.processEvents()

            config.write_text("{", encoding="utf-8")
            status["configured"] = True
            unreadable = ui.MainWindow("")
            try:
                assert unreadable._ready is False
                assert unreadable._overlay is not None
            finally:
                unreadable.close()
                unreadable.deleteLater()
                app.processEvents()

            assert controller.owner_address() == "Sir"
            directive = controller.owner_prompt_directive()
            assert "Before we continue, what name should I use for you?" in directive
            assert "Then call set_owner_name once." in directive
            assert callable(controller.handle_owner_tool)
            assert len(shortcut_calls) == 1
        finally:
            ui.API_FILE = original_api_file
            controller.rollback_all()


def test_accepted_predecessor_envelopes_remain_exact_without_future_discovery():
    expected = {
        "docs/onyx/checkpoints/onyx-live-activation-v9/manifest.json": (
            "38de625b7725dab7aa9c7906f7f3164687f1f20a0cca6e683fe64145bb53142a"
        ),
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.md": (
            "91a3613df269d1fe222c437b92b0d3022f3f2a603ae9689a951e63e0c4e4f0ec"
        ),
        "docs/onyx/checkpoints/phase6-live-wiring-v1/manifest.json": (
            "d98cdd73ae056e3afe5eac2976565d8b301fb1410a8b0498f04c6f7e8c2db6ee"
        ),
        "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.md": (
            "51c542420b55f58409fba1b9a5efe753fb9aabdfebd1bc5e3ab2b9abf1f15dd7"
        ),
        "docs/onyx/checkpoints/phase5-exit-candidate-v2/manifest.json": (
            "b2cf8d781fc1f72a375be444c24ad74c4e59b910adab765a48c7c7b59ae15d2b"
        ),
        "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.md": (
            "052426cc0d62aad20af4ee8f1810d0729698fb0dd74e95cb76c1bbf0f50404d3"
        ),
        "core/onyx_live_activation_v9.py": (
            "deb26314ef3871cb12fc8e3cee936f88e385122fad242c830580421ccb22a9d2"
        ),
        "core/phase6_live_wiring_v1.py": (
            "a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f"
        ),
        "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
        "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
