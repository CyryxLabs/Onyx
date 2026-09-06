from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

import ui


class _ImmediateThread:
    def __init__(self, *, target, daemon, name):
        self.target = target
        self.daemon = daemon
        self.name = name

    def start(self) -> None:
        self.target()


def _callbacks(calls: list[object]):
    def status():
        calls.append("status")
        return {"status": "disconnected", "read_only": True}

    def connect(payload):
        calls.append(("connect", dict(payload)))
        return {"status": "prepared"}

    def sign_in(echo, cancel_requested):
        assert not cancel_requested()
        echo("Verification URL : https://microsoft.com/devicelogin")
        echo("User code        : ABCD-EFGH")
        calls.append("sign_in")
        return {"status": "connected", "read_only": True}

    def disconnect():
        calls.append("disconnect")
        return {"status": "disconnected", "read_only": True}

    def today_brief():
        calls.append("today_brief")
        return {"status": "completed", "read_only": True, "events": []}

    return {
        "status": status,
        "connect": connect,
        "sign_in": sign_in,
        "disconnect": disconnect,
        "today_brief": today_brief,
    }


def _runtime_dispatch(calls: list[object]):
    def dispatch(boundary, worker, complete):
        calls.append(("dispatch", boundary))
        try:
            complete(worker(), None)
        except BaseException as exc:
            complete(None, exc)
        return True

    return dispatch


def test_dayops_dialog_keeps_device_code_on_trusted_surface() -> None:
    app = QApplication.instance() or QApplication([])
    calls: list[object] = []
    owner = QWidget()
    owner._v5_projection = None
    dialog = ui.DayOpsConnectionDialog(
        owner, _callbacks(calls), _runtime_dispatch(calls)
    )
    dialog._client_id.setText("12345678-1234-4123-8123-123456789abc")
    dialog._tenant_id.setText("common")
    dialog._account_id.setText("owner@example.com")
    with patch.object(ui.threading, "Thread", _ImmediateThread):
        dialog._connect()
    app.processEvents()

    assert calls[-1] == "sign_in"
    assert calls[-3] == ("dispatch", "dayops-connect")
    payload = calls[-2][1]
    assert payload == {
        "client_id": "12345678-1234-4123-8123-123456789abc",
        "tenant_id": "common",
        "account_id": "owner@example.com",
        "iana_timezone": "America/New_York",
        "outlook_timezone": "Eastern Standard Time",
    }
    rendered = dialog._output.toPlainText()
    assert "microsoft.com/devicelogin" in rendered
    assert "ABCD-EFGH" in rendered
    assert "refresh_token" not in rendered
    assert dialog._status.text() == "STATUS  /  CONNECTED"
    dialog.close()


def test_dayops_ui_bridge_is_additive_and_setup_accessible() -> None:
    required = {
        "on_dayops_status",
        "on_dayops_connect",
        "on_dayops_sign_in",
        "on_dayops_disconnect",
        "on_dayops_today_brief",
    }
    assert required <= set(dir(ui.OnyxUI))
    overlay = ui.SetupOverlay(credential_configured=True)
    assert (
        overlay.findChild(ui.QPushButton, "onyxDayOpsConnectionButtonV19") is not None
    )
    overlay.close()


def test_dayops_dialog_rejects_partial_connection_without_host_call() -> None:
    QApplication.instance() or QApplication([])
    calls: list[object] = []
    owner = QWidget()
    owner._v5_projection = None
    dialog = ui.DayOpsConnectionDialog(
        owner, _callbacks(calls), _runtime_dispatch(calls)
    )
    dialog._client_id.setText("12345678-1234-4123-8123-123456789abc")
    dialog._connect()
    assert calls == []
    assert "REQUIRED" in dialog._status.text()
    dialog.close()


def test_dayops_render_limits_are_explicit_and_preserve_coverage_markers() -> None:
    payload = {
        "status": "completed",
        "planner": {
            "coverage": {
                "source_truncated": True,
                "output_truncated": False,
                "calendar_pagination": "incomplete",
                "mail_pagination": "complete",
            }
        },
    }
    rendered = "x" * 20_000
    dialog = ui._dayops_visible_render(rendered, limit=12_000, payload=payload)
    projection = ui._dayops_visible_render(rendered, limit=4_000, payload=payload)
    assert len(dialog) == 12_000
    assert len(projection) == 4_000
    for result in (dialog, projection):
        assert "[TRUNCATED:" in result
        assert "source_truncated=True" in result
        assert "calendar=incomplete" in result
