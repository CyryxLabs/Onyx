from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import core.onyx_hud_orb_v10 as hud_v10
import core.onyx_hud_orb_v8 as hud_v8
import core.onyx_hud_orb_v9 as hud_v9
import ui
from core.onyx_hud_current_acceptance_v21 import (
    ARTIFACT_ROOT_SHA256,
    CURRENT_RUNTIME_INPUTS,
    CurrentHudAcceptanceV21Error,
    MANIFEST_RELATIVE,
    verify_current_hud_acceptance,
)
from core.onyx_hud_orb_v6 import install_candidate as install_v6
from core.onyx_hud_orb_v6 import uninstall_candidate as uninstall_v6
from core.onyx_hud_orb_v7 import install_candidate as install_v7
from core.onyx_hud_orb_v7 import uninstall_candidate as uninstall_v7


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_v10() -> None:
    hud_v10.uninstall_candidate(ui)
    hud_v9.uninstall_candidate(ui)
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)
    yield
    hud_v10.uninstall_candidate(ui)
    hud_v9.uninstall_candidate(ui)
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)


def _copy_acceptance(destination: Path) -> None:
    for relative in {MANIFEST_RELATIVE, *(p for p, _ in CURRENT_RUNTIME_INPUTS)}:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def test_current_v21_closure_is_exact() -> None:
    assert verify_current_hud_acceptance(ROOT) == {
        "candidate": "onyx-hud-v10-exit-current-pinned-003",
        "current_root": "qml/OnyxLiveShellV10.qml",
        "qml_files": 6,
        "runtime_inputs": 11,
        "artifact_root_sha256": ARTIFACT_ROOT_SHA256,
        "rays": 22,
        "equalizer_bars": 48,
        "legacy_branding": 0,
        "arcs_visible": 0,
        "max_fps": 12,
        "stable_activation": "V23",
    }


@pytest.mark.parametrize("relative", [p for p, _ in CURRENT_RUNTIME_INPUTS])
def test_every_current_input_tamper_fails_closed(
    tmp_path: Path, relative: Path
) -> None:
    _copy_acceptance(tmp_path)
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV21Error, match="input drift"):
        verify_current_hud_acceptance(tmp_path)


def test_real_v10_scene_and_exit_refusal_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv("ONYX_HUD_V7_LIVE", "1")
    monkeypatch.setenv(hud_v8.FLAG_NAME, "1")
    monkeypatch.setenv(hud_v9.FLAG_NAME, "1")
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    monkeypatch.setattr(ui.MainWindow, "_create_desktop_shortcut", lambda _self: None)
    assert install_v6(ui)
    assert install_v7(ui)
    assert hud_v8.install_candidate(ui)
    assert hud_v9.install_candidate(ui)
    assert ui.install_current_hud_v10()
    window = ui.MainWindow("")
    window.show()
    QTest.qWait(200)
    app.processEvents()
    try:
        assert window.hud.renderer_mode == "qml-v10-explicit-exit"
        root = window._v5_host._quick.rootObject()
        assert root.objectName() == "onyxLiveShellV10Root"
        assert root.findChild(QQuickItem, "exitOnyxActionV10") is not None
        window.on_exit_requested = lambda _reason: False
        assert window._v5_host.projection.requestExit() is False
        assert window._exit_requested is False
    finally:
        window.request_explicit_exit()
        window.deleteLater()
        app.processEvents()


def test_stable_bootstrap_and_package_selection_exclude_activation_v24() -> None:
    paths = (
        ROOT / "scripts/bootstrap_onyx.pyw",
        ROOT / "scripts/build_release.py",
        ROOT / "scripts/package_hygiene.py",
        ROOT / "packaging/onyx.spec",
        ROOT / "tests/test_package_hygiene_v1.py",
    )
    joined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "onyx_live_activation_v24" not in joined
    assert "bootstrap_onyx_live_v24" not in joined
    assert "launch_onyx_live_v24" not in joined
    assert 'bootstrap_onyx_live_v23.pyw"' in joined
    assert "onyx_hud_current_acceptance_v21" in joined
