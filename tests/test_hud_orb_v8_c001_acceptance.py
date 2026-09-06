from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import ui
import core.onyx_hud_orb_v8 as hud_v8
from core.onyx_hud_orb_v6 import install_candidate as install_v6
from core.onyx_hud_orb_v6 import uninstall_candidate as uninstall_v6
from core.onyx_hud_orb_v7 import install_candidate as install_v7
from core.onyx_hud_orb_v7 import uninstall_candidate as uninstall_v7


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "docs/onyx/checkpoints/hud-orb-v8-candidate"
MANIFEST = CHECKPOINT / "manifest.json"
EXPECTED_MANIFEST = "b3ea35bea9a160803ae01c3ddfc8e4e5811d5547095f7dc21b0ca8f2adbf4152"
EXPECTED_ROOT = "7d32ac55daeb3bb01dcdb18ea112c4d6d71453ff28cf1aed7fb07d9ae803a967"
UNTOUCHED_V10 = {
    "core/onyx_live_activation_v10.py": (
        "546842aeceb8fc5839d0782658ea4272d4bea999b786b96d38d7968c419a2ee7"
    ),
    "docs/onyx/checkpoints/onyx-live-activation-v10/manifest.json": (
        "b22459a5315370f179089cf67d501a687305c2147d2c68ef132575326d47e236"
    ),
    "scripts/bootstrap_onyx_live_v10.pyw": (
        "dd874140b0a7486b4897827196ba43c8bdf010db6c8ac503d473b0daa9fda675"
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def clean_installation(monkeypatch: pytest.MonkeyPatch):
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)
    for flag in (
        hud_v8.FLAG_NAME,
        "ONYX_HUD_V7_LIVE",
        "ONYX_HUD_V6_CANDIDATE",
    ):
        monkeypatch.delenv(flag, raising=False)
    yield
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)


def test_p0_exact_candidate_is_default_off_and_not_live() -> None:
    data = candidate()
    assert digest(MANIFEST) == EXPECTED_MANIFEST
    assert data["candidate"] == "hud-orb-v8-voice-reactive-candidate-001"
    assert data["default_off"] is True and data["live_activated"] is False
    assert hud_v8.candidate_requested({}) is False
    assert hud_v8.candidate_requested({hud_v8.FLAG_NAME: "1"}) is True
    assert hud_v8.candidate_requested({hud_v8.FLAG_NAME: "true"}) is False


def test_p0_particles_are_clipped_inside_orb_and_have_no_external_geometry() -> None:
    layer = (ROOT / "qml/components/OnyxOrbVoiceLayerV8.qml").read_text(
        encoding="utf-8"
    )
    shell = (ROOT / "qml/OnyxLiveShellV8.qml").read_text(encoding="utf-8")
    assert 'projection.state === "SPEAKING"' in layer
    assert "c.clip()" in layer
    assert "for (var i = 0; i < 42; ++i)" in layer
    for forbidden in ("RotationAnimator", "border.width", "QtQuick3D", "WebGL"):
        assert forbidden not in layer
    assert "Canvas {" not in shell
    assert "OnyxLiveShellV7 {" in shell


def test_p1_physical_motion_stops_exactly_at_idle_and_hidden() -> None:
    metrics = json.loads((CHECKPOINT / "hud-orb-v8.metrics.json").read_text())
    assert metrics["graphics_api"] == "GraphicsApi.Direct3D11Rhi"
    assert metrics["speaking_phase_b"] > metrics["speaking_phase_a"] > 0
    assert metrics["idle_phase_a"] == metrics["idle_phase_b"] == 0
    assert metrics["speaking_voice_layer_fps"] == 12
    assert metrics["idle_voice_layer_fps"] == 0
    assert metrics["hidden_voice_layer_fps"] == 0
    assert metrics["idle_projection_target_fps"] == 0
    assert metrics["hidden_projection_target_fps"] == 0


def test_p1_cpu_and_three_physical_captures_are_within_gate() -> None:
    metrics = json.loads((CHECKPOINT / "hud-orb-v8.metrics.json").read_text())
    assert metrics["speaking_host_cpu_percent"] <= 0.8
    assert metrics["idle_host_cpu_percent"] <= 0.15
    assert metrics["hidden_host_cpu_percent"] <= 0.15
    screenshots = [
        CHECKPOINT / "hud-orb-v8-speaking-a-1440x900.png",
        CHECKPOINT / "hud-orb-v8-speaking-b-1440x900.png",
        CHECKPOINT / "hud-orb-v8-idle-1440x900.png",
    ]
    for screenshot in screenshots:
        data = screenshot.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", data[16:24]) == (1440, 900)
    assert digest(screenshots[0]) != digest(screenshots[1])


def test_p2_real_qml_has_one_renderer_and_governed_speaking_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv("ONYX_HUD_V7_LIVE", "1")
    monkeypatch.setenv(hud_v8.FLAG_NAME, "1")
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    assert install_v6(ui) and install_v7(ui) and hud_v8.install_candidate(ui)
    window = ui.MainWindow("")
    window.resize(800, 600)
    window.show()
    QTest.qWait(250)
    app.processEvents()
    try:
        root = window._v5_host._quick.rootObject()
        assert root.objectName() == "onyxLiveShellV8Root"
        voice = root.findChild(QQuickItem, "onyxOrbVoiceLayerV8")
        assert voice is not None
        window.hud.set_operational_state("SPEAKING")
        QTest.qWait(300)
        app.processEvents()
        assert float(voice.property("phase")) > 0
        assert int(voice.property("governedFps")) <= 12
        window.hud.set_operational_state("LISTENING")
        QTest.qWait(200)
        app.processEvents()
        assert float(voice.property("phase")) == 0
        assert int(voice.property("governedFps")) == 0
        widgets = [
            widget
            for widget in QApplication.allWidgets()
            if isinstance(widget, QQuickWidget)
        ]
        assert widgets == [window._v5_host._quick]
    finally:
        window.close()
        window.deleteLater()
        for _ in range(5):
            app.processEvents()


def test_p2_authenticates_real_v7_record_and_rolls_back_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv("ONYX_HUD_V7_LIVE", "1")
    monkeypatch.setenv(hud_v8.FLAG_NAME, "1")
    assert install_v6(ui) and install_v7(ui)
    v7_host = ui._CinematicHudV5Host
    assert hud_v8.install_candidate(ui)
    assert hud_v8.uninstall_candidate(ui)
    assert ui._CinematicHudV5Host is v7_host
    ui._ONYX_HUD_V7_INSTALLATION = object()
    with pytest.raises(RuntimeError, match="V7 installation is unavailable"):
        hud_v8.install_candidate(ui)


def test_p3_candidate_hash_root_and_all_anchors_are_reproducible() -> None:
    data = candidate()
    rows = sorted(data["artifacts"], key=lambda item: item["path"])
    for item in rows:
        assert digest(ROOT / item["path"]) == item["sha256"]
    material = "".join(
        f"{item['path']}\0{item['sha256']}\n" for item in rows
    ).encode()
    assert hashlib.sha256(material).hexdigest() == EXPECTED_ROOT
    for relative, expected in data["frozen_anchors"].items():
        assert digest(ROOT / relative) == expected


def test_p3_v10_is_byte_exact_and_v8_does_not_change_activation_or_shortcuts() -> None:
    for relative, expected in UNTOUCHED_V10.items():
        assert digest(ROOT / relative) == expected
    source = (ROOT / "core/onyx_hud_orb_v8.py").read_text(encoding="utf-8")
    assert "onyx_live_activation_v10" not in source
    assert "shortcut" not in source.lower()

