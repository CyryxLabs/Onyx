from types import SimpleNamespace
from unittest.mock import MagicMock

import ui
from PySide6.QtTest import QTest


def _app():
    return ui.QApplication.instance() or ui.QApplication([])


def test_setup_exposes_all_supported_voices_and_preserves_signal(monkeypatch, tmp_path):
    _app()
    monkeypatch.setattr(ui, "memory_dir", lambda: tmp_path)
    ui.LiveVoicePreferenceV1(
        tmp_path / "live_voice_preference_v1.json"
    ).set("Kore")
    overlay = ui.SetupOverlay(credential_configured=True)
    emitted = []
    overlay.done.connect(lambda key, system, name: emitted.append((key, system, name)))

    assert overlay._voice_select.objectName() == "onyxLiveVoiceSelectorV1"
    assert [overlay._voice_select.itemText(index) for index in range(5)] == list(
        ui.VOICES
    )
    assert overlay.selected_voice == "Kore"
    overlay._name_input.setText("Alex")
    overlay._submit()
    assert emitted == [("", overlay._sel_os, "Alex")]
    overlay.close()


def test_setup_persists_selected_voice_through_existing_contract(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(ui, "memory_dir", lambda: tmp_path)
    monkeypatch.setattr("core.credentials.get", lambda required=False: "configured")
    monkeypatch.setattr("core.credentials.save_settings", lambda *_args, **_kwargs: None)
    overlay = SimpleNamespace(selected_voice="Aoede", hide=MagicMock())
    window = SimpleNamespace(
        _overlay=overlay,
        _log=MagicMock(),
        _ready=False,
        _apply_state=MagicMock(),
        _v5_projection=None,
    )

    ui.MainWindow._on_setup_done(window, "", "windows", "Alex")

    assert ui.LiveVoicePreferenceV1(
        tmp_path / "live_voice_preference_v1.json"
    ).get() == "Aoede"
    assert window._ready is True
    assert window._overlay is None
    window._log.append_log.assert_any_call(
        "SYS: Gemini Live voice selected: Aoede; session refresh automatic."
    )


def test_configured_setup_can_dismiss_with_escape_without_mutation(
    monkeypatch, tmp_path
):
    app = _app()
    monkeypatch.setattr(ui, "memory_dir", lambda: tmp_path)
    overlay = ui.SetupOverlay(
        credential_configured=True,
        dismissible=True,
    )
    dismissed: list[bool] = []
    overlay.dismissed.connect(lambda: dismissed.append(True))
    overlay.show()
    overlay._name_input.setFocus()
    app.processEvents()

    QTest.keyClick(overlay._name_input, ui.Qt.Key.Key_Escape)
    app.processEvents()

    assert dismissed == [True]
    overlay.close()


def test_first_boot_setup_cannot_dismiss_with_escape(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setattr(ui, "memory_dir", lambda: tmp_path)
    overlay = ui.SetupOverlay(
        credential_configured=False,
        dismissible=False,
    )
    dismissed: list[bool] = []
    overlay.dismissed.connect(lambda: dismissed.append(True))
    overlay.show()
    overlay._name_input.setFocus()
    app.processEvents()

    QTest.keyClick(overlay._name_input, ui.Qt.Key.Key_Escape)
    app.processEvents()

    assert dismissed == []
    overlay.close()


def test_setup_dismissal_clears_only_the_overlay_reference():
    overlay = MagicMock()
    window = SimpleNamespace(_overlay=overlay, _setup_open_pending=True)

    ui.MainWindow._dismiss_setup(window)

    overlay.hide.assert_called_once_with()
    overlay.deleteLater.assert_called_once_with()
    assert window._overlay is None
    assert window._setup_open_pending is False
