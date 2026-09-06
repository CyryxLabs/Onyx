from __future__ import annotations

import hashlib
import json
import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.paths import resource_root
from core.ui_projection_v3 import OnyxUIProjectionV3


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def open_shell(app: QApplication, projection: OnyxUIProjectionV3) -> QQuickView:
    view = QQuickView()
    view.rootContext().setContextProperty("onyxUIProjectionV3", projection)
    view.setSource(QUrl.fromLocalFile(str(resource_root() / "qml" / "OnyxShellV3.qml")))
    errors = "\n".join(error.toString() for error in view.errors())
    assert view.status() == QQuickView.Status.Ready, errors
    view.show()
    app.processEvents()
    view.requestActivate()
    app.processEvents()
    return view


@pytest.mark.parametrize(
    ("callback", "expected_status", "expected_error"),
    [
        (None, "COMMAND UNAVAILABLE", "command: unavailable"),
        (lambda _text: False, "COMMAND REJECTED", "command: rejected"),
        (lambda _text: None, "COMMAND REJECTED", "command: rejected"),
        (lambda _text: 1, "COMMAND REJECTED", "command: rejected"),
    ],
)
def test_command_requires_an_explicit_true_result(
    callback, expected_status: str, expected_error: str
) -> None:
    callbacks = {} if callback is None else {"command": callback}
    projection = OnyxUIProjectionV3(callbacks=callbacks)
    assert not projection.submitCommand("do the work")
    assert projection.actionStatus == expected_status
    assert projection.lastCallbackError == expected_error


def test_throwing_command_is_contained_and_sanitized() -> None:
    def fail(_text: str) -> bool:
        raise RuntimeError("never expose this private payload")

    projection = OnyxUIProjectionV3(callbacks={"command": fail})
    assert not projection.submitCommand("do the work")
    assert projection.actionStatus == "COMMAND FAILED"
    assert projection.lastCallbackError == "command: RuntimeError"
    assert "private payload" not in projection.lastCallbackError


def test_true_command_is_the_only_acceptance_and_clears_prior_error() -> None:
    callback = Mock(side_effect=[False, True])
    projection = OnyxUIProjectionV3(callbacks={"command": callback})
    assert not projection.submitCommand("first attempt")
    assert projection.lastCallbackError == "command: rejected"
    assert projection.submitCommand("  execute the plan  ")
    assert callback.call_args_list[1].args == ("execute the plan",)
    assert projection.actionStatus == "COMMAND ACCEPTED"
    assert projection.lastCallbackError == ""


def test_command_signal_is_emitted_only_after_explicit_acceptance() -> None:
    rejected = OnyxUIProjectionV3(callbacks={"command": lambda _text: False})
    rejected_signals: list[str] = []
    rejected.commandRequested.connect(rejected_signals.append)
    assert not rejected.submitCommand("not accepted")
    assert rejected_signals == []

    accepted = OnyxUIProjectionV3(callbacks={"command": lambda _text: True})
    accepted_signals: list[str] = []
    accepted.commandRequested.connect(accepted_signals.append)
    assert accepted.submitCommand("accepted")
    assert accepted_signals == ["accepted"]


@pytest.mark.parametrize(
    ("callback", "preserved"),
    [
        (None, True),
        (lambda _text: False, True),
        (lambda _text: True, False),
    ],
)
def test_enter_preserves_input_until_callback_accepts(
    app: QApplication, callback, preserved: bool
) -> None:
    callbacks = {} if callback is None else {"command": callback}
    projection = OnyxUIProjectionV3(callbacks=callbacks)
    view = open_shell(app, projection)
    command = view.rootObject().findChild(QQuickItem, "commandInputV3")
    assert command is not None and command.isVisible() and command.isEnabled()
    command.setProperty("text", "retain until accepted")
    command.forceActiveFocus()
    app.processEvents()
    assert command.hasActiveFocus()
    QTest.keyClick(view, Qt.Key.Key_Return)
    app.processEvents()
    assert bool(command.property("text")) is preserved
    view.close()
    app.processEvents()


def test_mute_and_close_are_visible_focusable_keyboard_actions(
    app: QApplication,
) -> None:
    mute = Mock()
    close = Mock()
    projection = OnyxUIProjectionV3(callbacks={"mute": mute, "close": close})
    view = open_shell(app, projection)
    root = view.rootObject()

    mute_action = root.findChild(QQuickItem, "muteActionV3")
    close_action = root.findChild(QQuickItem, "closeActionV3")
    for action in (mute_action, close_action):
        assert action is not None
        assert action.isVisible() and action.isEnabled()
        assert action.width() >= 44 and action.height() >= 34

    mute_action.forceActiveFocus()
    app.processEvents()
    assert mute_action.hasActiveFocus()
    QTest.keyClick(view, Qt.Key.Key_Space)
    app.processEvents()
    mute.assert_called_once_with(True)

    close_action.forceActiveFocus()
    app.processEvents()
    assert close_action.hasActiveFocus()
    QTest.keyClick(view, Qt.Key.Key_Return)
    app.processEvents()
    close.assert_called_once_with()
    view.close()
    app.processEvents()


def test_v3_accessibility_focus_and_keyboard_contract_is_declared() -> None:
    root = resource_root()
    shell = (root / "qml" / "OnyxShellV3.qml").read_text(encoding="utf-8")
    action = (root / "qml" / "components" / "ActionButtonV3.qml").read_text(
        encoding="utf-8"
    )
    for required in (
        "Accessible.role: Accessible.Button",
        "Accessible.name:",
        "Accessible.description:",
        "Accessible.onPressAction:",
        "activeFocusOnTab: true",
        "Keys.onReturnPressed:",
        "Keys.onSpacePressed:",
    ):
        assert required in action
    for required in (
        "Accessible.role: Accessible.EditableText",
        'Accessible.name: "Direct Onyx"',
        "activeFocusOnTab: true",
        "KeyNavigation.tab:",
    ):
        assert required in shell
    assert "requestMuteToggle()" in shell
    assert "requestClose()" in shell


def test_v3_visual_and_packaging_contract_remains_bounded() -> None:
    root = resource_root()
    shell = (root / "qml" / "OnyxShellV3.qml").read_text(encoding="utf-8")
    action = (root / "qml" / "components" / "ActionButtonV3.qml").read_text(
        encoding="utf-8"
    )
    combined = (shell + "\n" + action).lower()
    for forbidden in ("#sphere", "qtquick3d", "crosshair", "octagon", "bracket"):
        assert forbidden not in combined
    assert "http://" not in combined and "https://" not in combined
    assert "radius: implicitheight / 2" in combined
    spec = (root / "packaging" / "onyx.spec").read_text(encoding="utf-8")
    assert '(str(RUNTIME_SOURCES / "qml"), "qml")' in spec


def test_v3_is_not_live_wired() -> None:
    root = resource_root()
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/permission_broker.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "OnyxShellV3.qml" not in text
        assert "OnyxUIProjectionV3" not in text


def test_rejected_v2_archive_is_exact_and_detects_live_successor_drift() -> None:
    root = resource_root()
    bundle = root / "docs" / "onyx" / "checkpoints" / "hud-orb-v2"
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    drifted: set[str] = set()
    for record in manifest["files"]:
        candidate = root / record["path"]
        assert candidate.is_file(), record["path"]
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual != record["sha256"]:
            drifted.add(record["path"])
    # V2 is a rejected historical checkpoint. The immutable manifest remains
    # authenticated while the live successor is expected to have evolved.
    assert "core/ui_projection.py" in drifted
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == (
        "74f07faa1a5114e2f6eb24e7ee8ab568c7a36d21eb85a0d58a9b98d7b57a15af"
    )
    checkpoint = bundle / "ONYX_HUD_ORB_V2_CHECKPOINT.md"
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == (
        "b164160f5525baade704ddfabe9d9a60e7c3bb0a256269aa6c0225f8e1bb7051"
    )
