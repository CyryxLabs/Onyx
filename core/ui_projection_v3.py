"""Acceptance-aware UI projection for the isolated Onyx HUD V3 candidate."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtCore import QObject
from core.qt_compat import pyqtProperty, pyqtSignal, pyqtSlot
from core.render_governor_v3 import RenderGovernorV3
from core.ui_projection import OnyxUIProjection


class OnyxUIProjectionV3(OnyxUIProjection):
    """Preserve V2 contracts and require explicit command acceptance.

    Command text is considered consumed only when the configured callback
    returns the singleton ``True``. Missing callbacks, exceptions, ``False``,
    ``None`` and other truthy values are non-acceptance outcomes.
    """

    actionStatusChanged = pyqtSignal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        governor: RenderGovernorV3 | None = None,
        callbacks: Mapping[str, Callable[..., object]] | None = None,
        owner_name: str = "Sir",
    ) -> None:
        super().__init__(
            parent,
            governor=governor or RenderGovernorV3(),
            callbacks=callbacks,
            owner_name=owner_name,
        )
        self._action_status = "READY"

    @pyqtProperty(str, notify=actionStatusChanged)
    def actionStatus(self) -> str:  # noqa: N802 - QML property spelling
        return self._action_status

    def _set_action_result(self, status: str, error: str = "") -> None:
        status_value = self._clean_text(status, fallback="READY", limit=80)
        error_value = self._clean_text(error, fallback="", limit=160)
        if error_value != self._callback_error:
            self._callback_error = error_value
            self.callbackErrorChanged.emit()
        if status_value != self._action_status:
            self._action_status = status_value
            self.actionStatusChanged.emit()

    @pyqtSlot(str, result=bool)
    def submitCommand(self, command: str) -> bool:  # noqa: N802
        text = self._clean_text(command, fallback="", limit=8000)
        if not text:
            self._set_action_result("COMMAND EMPTY", "command: empty")
            return False

        callback = self._callbacks.get("command")
        if callback is None:
            self._set_action_result("COMMAND UNAVAILABLE", "command: unavailable")
            return False
        try:
            result = callback(text)
        except Exception as exc:  # Preserve the Qt event loop and hide details.
            self._set_action_result(
                "COMMAND FAILED", f"command: {type(exc).__name__}"
            )
            return False
        if result is not True:
            self._set_action_result("COMMAND REJECTED", "command: rejected")
            return False
        self._set_action_result("COMMAND ACCEPTED")
        self.commandRequested.emit(text)
        return True

    def _request_control(self, name: str, signal, *args: object) -> bool:
        signal.emit(*args)
        callback = self._callbacks.get(name)
        label = name.upper()
        if callback is None:
            self._set_action_result(f"{label} UNAVAILABLE", f"{name}: unavailable")
            return False
        try:
            callback(*args)
        except Exception as exc:
            self._set_action_result(
                f"{label} FAILED", f"{name}: {type(exc).__name__}"
            )
            return False
        self._set_action_result(f"{label} REQUESTED")
        return True

    @pyqtSlot(result=bool)
    def requestMuteToggle(self) -> bool:  # noqa: N802
        return self._request_control("mute", self.muteRequested, not self.muted)

    @pyqtSlot(result=bool)
    def requestClose(self) -> bool:  # noqa: N802
        return self._request_control("close", self.closeRequested)


__all__ = ["OnyxUIProjectionV3"]
