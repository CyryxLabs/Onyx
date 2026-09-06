from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

import ui
from core.paths import resource_root


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def close_window(app: QApplication, window: ui.MainWindow) -> None:
    window.close()
    window.deleteLater()
    for _ in range(4):
        app.processEvents()


def test_v5_flag_is_exact_default_off_and_rejected_flags_cannot_activate() -> None:
    source = (resource_root() / "ui.py").read_text(encoding="utf-8")
    assert 'os.environ.get("ONYX_HUD_V5_LIVE", "0").strip() == "1"' in source
    assert "ONYX_HUD_V3_LIVE" not in source
    assert "ONYX_HUD_V4_LIVE" not in source


def test_flag_absent_software_preserves_fallback_timer_and_minimize_safety(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui, "HUD_V5_LIVE", False)
    monkeypatch.setattr(ui, "_QML_SCENE_GRAPH_CLAIMED", False)
    monkeypatch.setenv("ONYX_ORB_RENDERER", "software")
    monkeypatch.setenv("ONYX_ORB_QUALITY", "high")

    def unexpected_gpu(*_args) -> None:
        raise AssertionError("software renderer must not create a QQuickWidget")

    monkeypatch.setattr(ui.OrbHost, "_create_gpu_widget", unexpected_gpu)
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    window = ui.MainWindow("")
    window.show()
    app.processEvents()
    try:
        assert not window._hud_v5_requested
        assert window._v5_host is None
        assert window.hud.renderer_mode == "fallback"
        assert window.hud._quick is None
        assert window.hud.bridge.quality == "high"
        window.hud.set_operational_state("THINKING")
        assert window.hud.fallback._tmr.isActive()
        window.showMinimized()
        app.processEvents()
        assert not window.hud.bridge.active
        assert not window.hud.fallback._tmr.isActive()
        window.showNormal()
        app.processEvents()
        assert window.hud.fallback._tmr.isActive()
    finally:
        close_window(app, window)


@pytest.mark.parametrize("renderer", ["auto", "gpu"])
def test_flag_absent_auto_and_gpu_keep_legacy_renderer_selection_semantics(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, renderer: str
) -> None:
    monkeypatch.setattr(ui, "HUD_V5_LIVE", False)
    monkeypatch.setattr(ui, "_QML_SCENE_GRAPH_CLAIMED", False)
    monkeypatch.setenv("ONYX_ORB_RENDERER", renderer)
    attempted: list[str] = []

    def record_gpu(_host, qml_path) -> None:
        attempted.append(qml_path.name)

    monkeypatch.setattr(ui.OrbHost, "_create_gpu_widget", record_gpu)
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    window = ui.MainWindow("")
    try:
        assert not window._hud_v5_requested
        assert window._v5_host is None
        assert attempted == ["OnyxOrb.qml"]
    finally:
        close_window(app, window)


def test_v5_uses_exactly_one_quick_widget_and_software_fallback(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui, "HUD_V5_LIVE", True)
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    window = ui.MainWindow("")
    window.show()
    app.processEvents()
    try:
        assert window._hud_v5_live
        assert window.hud.renderer_mode == "qml-v5"
        assert window._legacy_hud.renderer_mode == "fallback"
        assert window._legacy_hud._quick is None
        quick_widgets = window.findChildren(QQuickWidget)
        assert quick_widgets == [window._v5_host._quick]
        assert window.centralWidget().objectName() == "OnyxCinematicSurfaceV5"
        root = window._v5_host._quick.rootObject()
        assert root.objectName() == "onyxLiveShellV5Root"
        command = root.findChild(QQuickItem, "liveCommandInputV5")
        assert command is not None and command.isVisible() and command.isEnabled()
    finally:
        close_window(app, window)


def test_v5_minimize_and_restore_resynchronizes_projection_lifecycle(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui, "HUD_V5_LIVE", True)
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    window = ui.MainWindow("")
    window.show()
    app.processEvents()
    try:
        projection = window._v5_host.projection
        window.hud.set_operational_state("THINKING")
        window.hud.sync_animation()
        assert projection.animationRunning
        assert projection.targetFps == 16

        window.showMinimized()
        app.processEvents()
        assert not projection.animationRunning
        assert projection.targetFps == 0

        window.showNormal()
        app.processEvents()
        assert projection.animationRunning
        assert projection.targetFps == 16
    finally:
        close_window(app, window)


def test_setup_request_defers_widget_creation_past_qml_callback(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SETUP must not create QWidget children inside QQuickWidget mouse dispatch."""

    monkeypatch.setattr(ui, "HUD_V5_LIVE", True)
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    window = ui.MainWindow("")
    window.show()
    app.processEvents()
    calls: list[str] = []

    def record_deferred_setup() -> None:
        window._setup_open_pending = False
        calls.append("opened")

    monkeypatch.setattr(window, "_show_setup", record_deferred_setup)
    try:
        projection = window._v5_host.projection
        assert projection.requestSetup()
        assert projection.requestSetup()
        assert calls == []
        assert window._setup_open_pending

        app.processEvents()

        assert calls == ["opened"]
        assert not window._setup_open_pending
        assert window.isVisible()
        assert not window._exit_requested
    finally:
        close_window(app, window)


def test_single_host_source_swaps_live_legacy_live_without_reallocation(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui, "HUD_V5_LIVE", True)
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    window = ui.MainWindow("")
    window.show()
    app.processEvents()
    host = window._v5_host
    quick = host._quick
    try:
        for index in range(20):
            window._restore_legacy_shell(f"cycle-{index}")
            app.processEvents()
            assert window.hud.renderer_mode == "fallback"
            assert not window._v5_log_connected
            assert host._quick is quick
            assert host._quick.source().isEmpty()
            assert host.projection.animationRunning is False
            window._activate_v5_shell()
            app.processEvents()
            assert window.hud is host
            assert window._v5_log_connected
            assert host._quick is quick
            assert host._quick.rootObject().objectName() == "onyxLiveShellV5Root"
    finally:
        close_window(app, window)


def test_fresh_process_transition_stress_exits_cleanly() -> None:
    script = r"""
from PySide6.QtWidgets import QApplication
import ui
ui.HUD_V5_LIVE = True
ui.MainWindow._check_config = lambda self: True
app = QApplication.instance() or QApplication([])
for outer in range(4):
    window = ui.MainWindow("")
    window.show(); app.processEvents()
    host_id = id(window._v5_host._quick)
    for inner in range(30):
        window._restore_legacy_shell("stress"); app.processEvents()
        window._activate_v5_shell(); app.processEvents()
        assert id(window._v5_host._quick) == host_id
    window.close(); window.deleteLater()
    for _ in range(5): app.processEvents()
legacy_probe = ui.OrbHost("")
assert legacy_probe.renderer_mode == "fallback"
assert legacy_probe._quick is None
legacy_probe.deleteLater(); app.processEvents()
print("HUD_V5_STRESS_OK")
"""
    env = os.environ.copy()
    env.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "QSG_RHI_BACKEND": "software",
            "ONYX_HUD_V5_LIVE": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=resource_root(),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HUD_V5_STRESS_OK" in result.stdout
    assert "0xC0000005" not in result.stderr
    assert "fatal" not in result.stderr.lower()


def test_close_quiesces_qml_before_parent_owned_destruction(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing must not destroy QML reentrantly from QQuickWidget::event."""

    monkeypatch.setattr(ui, "HUD_V5_LIVE", True)
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    window = ui.MainWindow("")
    window.show()
    app.processEvents()
    host = window._v5_host
    assert host is not None
    quick = host._quick
    root = quick.rootObject()
    assert root is not None
    assert not quick.source().isEmpty()

    window.close()

    assert host._shutdown
    assert not host._motion_timer.isActive()
    assert not host._scene_signal_connected
    assert quick.rootObject() is root
    assert not quick.source().isEmpty()
    assert window._v5_host is host

    window.deleteLater()
    for _ in range(5):
        app.processEvents()


def test_v5_canvas_is_transparent_additive_and_asset_authoritative() -> None:
    root = resource_root()
    orb = (root / "qml" / "components" / "OnyxOrbCinematicV5.qml").read_text(
        encoding="utf-8"
    )
    lower = orb.lower()
    assert 'source: "../assets/onyx-orb-cinematic-v3.png"' in orb
    assert "ctx.clearRect(0, 0, width, height)" in orb
    assert "Canvas.Threaded" in orb
    assert "Math.min(64, projection.particleBudget)" in orb
    for forbidden in (
        "createradialgradient",
        "ctx.ellipse",
        "fillrect",
        "atmosphere",
        "var body",
        "external ring",
        "qtquick3d",
        "webgl",
    ):
        assert forbidden not in lower


def test_v5_visual_qml_and_asset_remain_self_contained_after_archive_cleanup() -> None:
    root = resource_root()
    shell = (root / "qml" / "OnyxLiveShellV5.qml").read_text(encoding="utf-8")
    orb = (root / "qml" / "components" / "OnyxOrbCinematicV5.qml").read_text(
        encoding="utf-8"
    )
    assert "onyxLiveShellV5Root" in shell
    assert "OnyxOrbCinematicV5" in shell
    assert "onyxOrbCinematicV5Root" in orb
    assert "V4" not in shell and "V4" not in orb
    asset = root / "qml" / "assets" / "onyx-orb-cinematic-v3.png"
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == (
        "44668e57df10b4b47516cf7b35238ced7803523c76ea264a2045bdb35b174de1"
    )


def test_v5_render_policy_is_16_to_12_and_stops_every_inactive_surface() -> None:
    governor = ui._BalancedHudGovernorV5()
    governor.set_lifecycle(visible=True)
    governor.set_state("THINKING")
    assert governor.snapshot().target_fps == 16
    assert governor.snapshot().particle_budget == 64
    for _ in range(3):
        governor.report_frame(90.0)
    assert governor.snapshot().target_fps == 12
    assert governor.snapshot().particle_budget == 48
    governor.set_lifecycle(visible=False)
    assert governor.snapshot().target_fps == 0
    governor.set_lifecycle(visible=True, minimized=True)
    assert governor.snapshot().target_fps == 0
    governor.set_lifecycle(visible=True, minimized=False)
    governor.set_reduced_motion(True)
    assert governor.snapshot().target_fps == 0


def test_v5_preserves_control_accessibility_and_public_api() -> None:
    root = resource_root()
    shell = (root / "qml" / "OnyxLiveShellV5.qml").read_text(encoding="utf-8")
    for label in (
        "FILE",
        "INTERRUPT",
        "MUTE",
        "AUTONOMY",
        "REMOTE",
        "CAMERA",
        "SETUP",
        "FULLSCREEN",
        "CLOSE",
        "HISTORY",
        "ACCESS",
    ):
        assert f'"{label}"' in shell
    for action in (
        "requestFile()",
        "requestInterrupt()",
        "requestMuteToggle()",
        "requestAutonomy()",
        "requestRemote()",
        "requestCamera()",
        "requestSetup()",
        "requestFullscreen()",
        "requestClose()",
        "requestHistory()",
        "requestPermissions()",
    ):
        assert action in shell
    assert "Accessible.role: Accessible.EditableText" in shell
    assert "DropArea" in shell and "acceptDroppedFile" in shell
    required = {
        "muted",
        "current_file",
        "on_text_command",
        "on_remote_clicked",
        "on_interrupt",
        "notify_phone_connected",
        "set_state",
        "write_log",
        "wait_for_api_key",
        "show_content",
        "prompt_reconfig",
        "show_camera_frame",
        "start_camera_stream",
        "stop_camera_stream",
        "start_speaking",
        "stop_speaking",
        "request_permission",
    }
    assert required <= set(dir(ui.OnyxUI))


def test_dashboard_and_packaging_contract_remain_complete() -> None:
    root = resource_root()
    for relative in ("dashboard/static/app.html", "dashboard/static/login.html"):
        text = (root / relative).read_text(encoding="utf-8")
        visible = re.sub(
            r"<script\b[^>]*>.*?</script>", "", text, flags=re.I | re.S
        ).lower()
        for token in (
            "#050607",
            "#0a0d0f",
            "#1b2227",
            "#8c949e",
            "#c7c9cc",
            "#0f6b68",
            "#19c7c0",
        ):
            assert token in visible
        assert "prefers-reduced-motion: reduce" in visible
        assert "webgl" not in visible
    spec = (root / "packaging" / "onyx.spec").read_text(encoding="utf-8")
    assert '(str(RUNTIME_SOURCES / "qml"), "qml")' in spec
    assert '"PySide6.QtQuickWidgets"' in spec
    assert (root / "qml" / "OnyxLiveShellV5.qml").is_file()
    assert (root / "qml" / "components" / "OnyxOrbCinematicV5.qml").is_file()


def test_candidate_003_archive_binds_visual_and_cpu_evidence() -> None:
    root = resource_root()
    manifest_path = (
        root / "docs" / "onyx" / "checkpoints" / "hud-orb-v5-live" / "manifest.json"
    )
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    assert manifest["candidate"] == "ONYX-HUD-ORB-V5-LIVE-INTEGRATION-003"
    assert manifest["status"] == "candidate-default-off"
    assert manifest["activation"] == "ONYX_HUD_V5_LIVE=1"
    frozen_manifest_sha256 = (
        "1b5415c70322cbdbb315046b7ef2a772c16d53a2db0ab326739265fd0d52152a"
    )
    assert hashlib.sha256(manifest_bytes).hexdigest() == frozen_manifest_sha256
    acceptance = (
        root / "docs" / "onyx" / "acceptance" / "VE-HUD-ORB-V5-LIVE-E6-001.md"
    ).read_text(encoding="utf-8")
    assert frozen_manifest_sha256 in acceptance
    records = {
        record["path"]: record
        for record in manifest["files"] + manifest["accepted_v3_anchors"]
    }
    # Candidate 003 is an immutable historical archive. Validate its frozen
    # evidence records instead of rebinding them to mutable current QML bytes.
    assert records["qml/OnyxLiveShellV5.qml"] == {
        "path": "qml/OnyxLiveShellV5.qml",
        "size": 13647,
        "sha256": "9ff4d3d5d3771d1bbf2c2f8fe68793fd05e8cc80fd0c0644d700596d7cd39e47",
    }
    assert records["qml/components/OnyxOrbCinematicV5.qml"] == {
        "path": "qml/components/OnyxOrbCinematicV5.qml",
        "size": 6357,
        "sha256": "adff9ee062fff1c735bd28d4a77591581b6e4ce131067b1724699da5055e2622",
    }
    assert records["qml/assets/onyx-orb-cinematic-v3.png"] == {
        "path": "qml/assets/onyx-orb-cinematic-v3.png",
        "size": 1333775,
        "sha256": "44668e57df10b4b47516cf7b35238ced7803523c76ea264a2045bdb35b174de1",
    }
    shell_record = records["qml/OnyxLiveShellV5.qml"]
    current_shell = root / shell_record["path"]
    assert current_shell.stat().st_size != shell_record["size"]
    assert (
        hashlib.sha256(current_shell.read_bytes()).hexdigest()
        != shell_record["sha256"]
    )
    # Mutable integration hosts must be allowed to advance without rewriting a
    # historical checkpoint; prove that the archive detects that live drift.
    ui_record = records["ui.py"]
    assert (
        hashlib.sha256((root / "ui.py").read_bytes()).hexdigest() != ui_record["sha256"]
    )
    physical = manifest["physical_validation"]
    assert physical["graphics_api"] == "Direct3D11Rhi"
    assert physical["resolution"] == [1440, 900]
    assert physical["active_host_cpu_percent"] <= 0.8
    assert physical["idle_host_cpu_percent"] <= 0.15
    assert physical["hidden_host_cpu_percent"] <= 0.15
    assert physical["active_target_fps"] == 16


def test_accepted_v3_visual_anchors_and_pyside_projection_are_current() -> None:
    root = resource_root()
    expected = {
        "core/render_governor_v3.py": "ee1f2145eb90e930e1663287bc0e71ff6f0809b9b4bce18e445c2f47e80d1de8",
        "qml/OnyxShellV3.qml": "4f450c9ff7b2a9926925273a29fb8cc77533576073f2015be3f87b450c180eac",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest
    projection = (root / "core/ui_projection_v3.py").read_text(encoding="utf-8")
    assert "from PySide6.QtCore" in projection
    assert "Signal" in projection and "PyQt6" not in projection
