from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtCore import QUrl, qInstallMessageHandler
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication

from core.onyx_hud_current_acceptance_v29 import (
    CURRENT_RUNTIME_PATHS,
    CurrentHudAcceptanceV29Error,
    MANIFEST_RELATIVE,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    verify_current_hud_acceptance,
)


ROOT = Path(__file__).resolve().parents[1]


def _copy_closure(destination: Path) -> None:
    for relative in {
        MANIFEST_RELATIVE,
        PREDECESSOR_ACCEPTANCE_RELATIVE,
        PREDECESSOR_MANIFEST_RELATIVE,
        *CURRENT_RUNTIME_PATHS,
    }:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def test_v29_authenticates_projection_safe_qml_lifecycle() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result["candidate"] == "onyx-hud-v10-qml-teardown-guard-011"
    assert result["qml_roots_published_at_construction"] == 1
    assert result["runtime_inputs"] == len(CURRENT_RUNTIME_PATHS)
    assert result["stable_activation"] == "V24"
    assert result["projection_teardown_guarded"] is True


def test_v29_rejects_runtime_and_predecessor_tamper(tmp_path: Path) -> None:
    _copy_closure(tmp_path)
    with (tmp_path / "qml/OnyxLiveShellV7.qml").open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV29Error, match="source input drift"):
        verify_current_hud_acceptance(tmp_path)

    shutil.rmtree(tmp_path)
    _copy_closure(tmp_path)
    with (tmp_path / PREDECESSOR_MANIFEST_RELATIVE).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(
        CurrentHudAcceptanceV29Error, match="source input drift|predecessor drift"
    ):
        verify_current_hud_acceptance(tmp_path)


def test_current_qml_loads_and_tears_down_without_projection_property_errors() -> None:
    app = QApplication.instance() or QApplication(["onyx-qml-teardown-test"])
    messages: list[str] = []

    def capture(_kind, _context, message: str) -> None:
        messages.append(message)

    previous = qInstallMessageHandler(capture)
    view = QQuickView()
    try:
        view.setSource(QUrl.fromLocalFile(str(ROOT / "qml/OnyxLiveShellV10.qml")))
        app.processEvents()
        assert view.status() == QQuickView.Status.Ready, [
            error.toString() for error in view.errors()
        ]
        view.setSource(QUrl())
        app.processEvents()
    finally:
        view.deleteLater()
        app.processEvents()
        qInstallMessageHandler(previous)

    projection_errors = [
        message
        for message in messages
        if "Cannot read property" in message
        or ("TypeError" in message and "uiProjection" in message)
        or ("TypeError" in message and "projection" in message)
    ]
    assert projection_errors == []
