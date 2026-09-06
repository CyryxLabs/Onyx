from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import core.onyx_hud_orb_v8 as hud_v8
import core.onyx_hud_orb_v9 as hud_v9
import core.onyx_live_activation_v11 as live_v11
import core.onyx_live_activation_v12 as live_v12
import core.onyx_live_activation_v13 as live_v13
import core.onyx_live_activation_v14 as live_v14
import core.onyx_live_activation_v15 as live_v15
import ui
from core.onyx_hud_current_acceptance_v20 import (
    ARTIFACT_ROOT_SHA256,
    CURRENT_QML_CHAIN,
    CURRENT_RUNTIME_INPUTS,
    CurrentHudAcceptanceV20Error,
    MANIFEST_RELATIVE,
    verify_current_hud_acceptance,
    verify_current_hud_runtime_inputs,
)
from core.onyx_hud_orb_v6 import install_candidate as install_v6
from core.onyx_hud_orb_v6 import uninstall_candidate as uninstall_v6
from core.onyx_hud_orb_v7 import install_candidate as install_v7
from core.onyx_hud_orb_v7 import uninstall_candidate as uninstall_v7


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_hud_installation(monkeypatch: pytest.MonkeyPatch):
    hud_v9.uninstall_candidate(ui)
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)
    for flag in (
        "ONYX_HUD_V6_CANDIDATE",
        "ONYX_HUD_V7_LIVE",
        hud_v8.FLAG_NAME,
        hud_v9.FLAG_NAME,
    ):
        monkeypatch.delenv(flag, raising=False)
    yield
    hud_v9.uninstall_candidate(ui)
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)


def _copy_acceptance(destination: Path) -> None:
    paths = {MANIFEST_RELATIVE, *(path for path, _digest in CURRENT_RUNTIME_INPUTS)}
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def test_current_v20_manifest_and_semantics_are_exact() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result == {
        "candidate": "onyx-hud-v9-exit-current-pinned-002",
        "current_root": "qml/OnyxLiveShellV9.qml",
        "qml_files": 5,
        "runtime_inputs": 6,
        "artifact_root_sha256": ARTIFACT_ROOT_SHA256,
        "rays": 22,
        "equalizer_bars": 48,
        "legacy_branding": 0,
        "arcs_visible": 0,
        "max_fps": 12,
    }
    manifest = json.loads((ROOT / MANIFEST_RELATIVE).read_text(encoding="utf-8"))
    assert manifest["historical_acceptance"]["status"] == (
        "superseded_immutable_evidence"
    )
    assert manifest["historical_acceptance"]["superseded_test_authority"] == (
        "tests/test_onyx_hud_current_acceptance_v19.py"
    )
    assert manifest["historical_acceptance"]["successor_test_authority"] == (
        "tests/test_onyx_hud_current_acceptance_v20.py"
    )
    for relative in manifest["historical_acceptance"]["records"]:
        assert (ROOT / relative).is_file()
    conftest = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    assert '"test_hud_orb_v8_c001_acceptance.py"' in conftest
    assert "_SUPERSEDED_HUD_ACCEPTANCE_TESTS" in conftest


@pytest.mark.parametrize("relative", CURRENT_QML_CHAIN, ids=lambda path: path.name)
def test_every_current_runtime_qml_tamper_fails_closed(
    tmp_path: Path, relative: Path
) -> None:
    _copy_acceptance(tmp_path)
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"\n// tamper")
    with pytest.raises(CurrentHudAcceptanceV20Error, match="input drift"):
        verify_current_hud_acceptance(tmp_path)


def test_current_particle_texture_tamper_fails_closed(tmp_path: Path) -> None:
    _copy_acceptance(tmp_path)
    texture = tmp_path / "qml/assets/onyx-orb-particle-v6.png"
    with texture.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV20Error, match="input drift"):
        verify_current_hud_runtime_inputs(tmp_path)


def test_no_qml_hash_bypass_remains_in_activation_integrity_chain() -> None:
    for version in (10, 11, 12, 13):
        source = (ROOT / f"core/onyx_live_activation_v{version}.py").read_text(
            encoding="utf-8"
        )
        assert 'suffix == ".qml"' not in source
        assert "decoupled from boot integrity" not in source


def test_corrected_activation_pin_chain_matches_current_bytes() -> None:
    def digest(relative: str) -> str:
        return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()

    assert dict(live_v11.V10_ACCEPTED_ROOTS)[
        Path("core/onyx_live_activation_v10.py")
    ] == digest("core/onyx_live_activation_v10.py")
    assert dict(live_v12.V11_ACCEPTED_ROOTS)[
        Path("core/onyx_live_activation_v11.py")
    ] == digest("core/onyx_live_activation_v11.py")
    assert dict(live_v13.V12_FROZEN_ROOTS)[
        Path("core/onyx_live_activation_v12.py")
    ] == digest("core/onyx_live_activation_v12.py")
    assert dict(live_v14.V13_FROZEN_ROOTS)[
        Path("core/onyx_live_activation_v13.py")
    ] == digest("core/onyx_live_activation_v13.py")
    assert dict(live_v15.V14_FROZEN_ROOTS)[
        Path("core/onyx_live_activation_v14.py")
    ] == digest("core/onyx_live_activation_v14.py")


def test_real_current_pyside6_hud_is_v9_arc_free_and_voice_reactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv("ONYX_HUD_V7_LIVE", "1")
    monkeypatch.setenv(hud_v8.FLAG_NAME, "1")
    monkeypatch.setenv(hud_v9.FLAG_NAME, "1")
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    monkeypatch.setattr(
        ui.MainWindow, "_create_desktop_shortcut", lambda _self: None
    )
    assert install_v6(ui)
    assert install_v7(ui)
    assert hud_v8.install_candidate(ui)
    assert hud_v9.install_candidate(ui)

    window = ui.MainWindow("")
    window.resize(1000, 700)
    window.show()
    QTest.qWait(250)
    app.processEvents()
    try:
        assert window.hud.renderer_mode == "qml-v9-arc-free"
        root = window._v5_host._quick.rootObject()
        assert root is not None
        assert root.objectName() == "onyxLiveShellV9Root"
        entity = root.findChild(QQuickItem, "onyxOrbEntityV7Root")
        voice = root.findChild(QQuickItem, "onyxOrbVoiceLayerV8")
        equalizer = root.findChild(QQuickItem, "onyxSpeakingEqualizerV9")
        command = root.findChild(QQuickItem, "liveCommandInputV7")
        exit_action = root.findChild(QQuickItem, "exitOnyxActionV7")
        assert entity is not None
        assert voice is not None
        assert equalizer is not None
        assert command is not None
        assert exit_action is not None
        assert exit_action.isVisible()
        assert exit_action.property("label") == "EXIT ONYX"
        exit_reasons: list[str] = []
        window.on_exit_requested = lambda reason: exit_reasons.append(reason) or True
        assert window._v5_host.projection.requestExit() is True
        assert exit_reasons == ["hud-exit-action"]
        arc_canvases = [
            child
            for child in command.parent().childItems()
            if callable(getattr(child, "requestPaint", None))
        ]
        assert len(arc_canvases) == 1
        assert not arc_canvases[0].isVisible()

        window.hud.set_operational_state("SPEAKING")
        QTest.qWait(300)
        app.processEvents()
        assert 0 < int(voice.property("governedFps")) <= 12
        assert float(voice.property("phase")) > 0
        assert int(equalizer.property("gfps")) <= 12
        assert float(equalizer.property("phase")) > 0

        window.hud.set_operational_state("LISTENING")
        QTest.qWait(200)
        app.processEvents()
        assert int(voice.property("governedFps")) == 0
        assert float(voice.property("phase")) == 0
        assert int(equalizer.property("gfps")) == 0
        assert float(equalizer.property("phase")) == 0
        quick_widgets = [
            widget
            for widget in QApplication.allWidgets()
            if isinstance(widget, QQuickWidget)
        ]
        assert quick_widgets == [window._v5_host._quick]
    finally:
        window.close()
        window.deleteLater()
        for _ in range(5):
            app.processEvents()
