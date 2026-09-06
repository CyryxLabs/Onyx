from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PyQt6.QtQuick import QQuickItem
from PyQt6.QtQuickWidgets import QQuickWidget
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import ui
import core.onyx_hud_orb_v8 as hud
from core.onyx_hud_orb_v6 import install_candidate as install_v6
from core.onyx_hud_orb_v6 import uninstall_candidate as uninstall_v6
from core.onyx_hud_orb_v7 import install_candidate as install_v7
from core.onyx_hud_orb_v7 import uninstall_candidate as uninstall_v7


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def clean_installation(monkeypatch: pytest.MonkeyPatch):
    hud.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)
    for flag in (hud.FLAG_NAME, "ONYX_HUD_V7_LIVE", "ONYX_HUD_V6_CANDIDATE"):
        monkeypatch.delenv(flag, raising=False)
    yield
    hud.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)


def test_v8_is_exact_default_off() -> None:
    assert hud.candidate_requested({}) is False
    assert hud.candidate_requested({hud.FLAG_NAME: "1"}) is True
    assert hud.candidate_requested({hud.FLAG_NAME: "true"}) is False


def test_voice_layer_has_speaking_only_governed_motion() -> None:
    text = (ROOT / "qml/components/OnyxOrbVoiceLayerV8.qml").read_text(
        encoding="utf-8"
    )
    assert 'projection.state === "SPEAKING"' in text
    assert "Math.min(12" in text
    assert "running: voiceLayer.governedFps > 0 && voiceLayer.visible" in text
    assert "if (!voiceLayer.speaking)" in text
    assert "for (var i = 0; i < 42; ++i)" in text
    assert "c.clip()" in text
    for forbidden in ("arc ring", "orbit", "square", "RotationAnimator"):
        assert forbidden not in text


def test_shell_is_additive_over_exact_v7_layout() -> None:
    text = (ROOT / "qml/OnyxLiveShellV8.qml").read_text(encoding="utf-8")
    assert "OnyxLiveShellV7 {" in text
    assert 'objectName: "onyxLiveShellV8Root"' in text
    assert "OnyxOrbVoiceLayerV8 {" in text
    assert "projection: root.uiProjection" in text


def test_module_does_not_enable_itself_or_edit_v7() -> None:
    assert os.environ.get(hud.FLAG_NAME) != "1"
    assert hud.V7_MODULE_SHA256 == (
        "31fd7d0df7413ac9dbba3db463de28390bdfaa75e2173dae54c04dfd82a6c150"
    )
    assert hud.V7_MANIFEST_SHA256 == (
        "3be0988e98b4f8222751686386041094606da4366c8111453b381d4cf47c84f2"
    )


def test_v8_one_widget_projection_and_exact_v7_rollback(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv("ONYX_HUD_V7_LIVE", "1")
    monkeypatch.setenv(hud.FLAG_NAME, "1")
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    assert install_v6(ui)
    assert install_v7(ui)
    v7_host = ui._CinematicHudV5Host
    assert hud.install_candidate(ui)
    window = ui.MainWindow("")
    window.resize(1000, 700)
    window.show()
    for _ in range(8):
        app.processEvents()
    try:
        assert window.hud.renderer_mode == "qml-v8-voice-reactive"
        assert window.hud.projection is window._v5_projection
        widgets = [w for w in QApplication.allWidgets() if isinstance(w, QQuickWidget)]
        assert widgets == [window._v5_host._quick]
        qml_root = window._v5_host._quick.rootObject()
        assert qml_root.objectName() == "onyxLiveShellV8Root"
        voice = qml_root.findChild(QQuickItem, "onyxOrbVoiceLayerV8")
        assert voice is not None
        window.hud.set_operational_state("SPEAKING")
        QTest.qWait(300)
        app.processEvents()
        speaking_phase = float(voice.property("phase"))
        assert 0 < speaking_phase <= 6.283185307
        assert int(voice.property("governedFps")) <= 12
        window.hud.set_operational_state("LISTENING")
        QTest.qWait(300)
        app.processEvents()
        assert float(voice.property("phase")) == 0
        assert int(voice.property("governedFps")) == 0
    finally:
        window.close()
        window.deleteLater()
        for _ in range(5):
            app.processEvents()
    assert hud.uninstall_candidate(ui)
    assert ui._CinematicHudV5Host is v7_host


def test_v8_denies_spoofed_v7_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv("ONYX_HUD_V7_LIVE", "1")
    monkeypatch.setenv(hud.FLAG_NAME, "1")
    assert install_v6(ui)
    assert install_v7(ui)
    ui._ONYX_HUD_V7_INSTALLATION = object()
    with pytest.raises(RuntimeError, match="V7 installation is unavailable"):
        hud.install_candidate(ui)


def test_v8_rollback_uses_immutable_internal_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv("ONYX_HUD_V7_LIVE", "1")
    monkeypatch.setenv(hud.FLAG_NAME, "1")
    assert install_v6(ui)
    assert install_v7(ui)
    v7_host = ui._CinematicHudV5Host
    assert hud.install_candidate(ui)
    ui._ONYX_HUD_V8_INSTALLATION = object()
    ui._CinematicHudV5Host = object()
    ui.HUD_V5_LIVE = object()
    assert hud.uninstall_candidate(ui)
    assert ui._CinematicHudV5Host is v7_host
    assert ui.HUD_V5_LIVE is True
