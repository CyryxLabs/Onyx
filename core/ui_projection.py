"""Qt-facing projection for the isolated Onyx HUD/Orb V2 candidate.

This object translates existing host concepts into stable, read-only QML
properties.  It does not import the live window, permission broker or runtime,
and it cannot grant authority.  The host may supply its current callbacks when
the candidate is explicitly integrated later.
"""
from __future__ import annotations

import math
from typing import Callable, Mapping

from PySide6.QtCore import QObject
from core.qt_compat import pyqtProperty, pyqtSignal, pyqtSlot
from core.render_governor import RenderGovernor


_STATE_COPY = {
    "INITIALISING": ("INITIALISING", "Loading local systems"),
    "LISTENING": ("PRESENT", "Listening for your direction"),
    "THINKING": ("REASONING", "Synthesising context"),
    "PROCESSING": ("EXECUTING", "Coordinating active work"),
    "SPEAKING": ("RESPONDING", "Voice channel active"),
    "MUTED": ("SILENT", "Microphone muted"),
    "OFFLINE": ("LOCAL ONLY", "Network intelligence unavailable"),
    "ERROR": ("ATTENTION", "A subsystem needs review"),
}
_CALLBACK_NAMES = frozenset(
    {"command", "mute", "settings", "history", "permissions", "close"}
)


class OnyxUIProjection(QObject):
    """One bounded projection shared by the V2 shell and Orb renderer."""

    stateChanged = pyqtSignal()
    identityChanged = pyqtSignal()
    renderPolicyChanged = pyqtSignal()
    audioLevelChanged = pyqtSignal()
    transcriptChanged = pyqtSignal()
    callbackErrorChanged = pyqtSignal()

    commandRequested = pyqtSignal(str)
    muteRequested = pyqtSignal(bool)
    settingsRequested = pyqtSignal()
    historyRequested = pyqtSignal()
    permissionsRequested = pyqtSignal()
    closeRequested = pyqtSignal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        governor: RenderGovernor | None = None,
        callbacks: Mapping[str, Callable[..., object]] | None = None,
        owner_name: str = "Sir",
    ) -> None:
        super().__init__(parent)
        self._governor = governor or RenderGovernor()
        supplied = dict(callbacks or {})
        unknown = supplied.keys() - _CALLBACK_NAMES
        if unknown:
            raise ValueError(f"unknown UI callback(s): {', '.join(sorted(unknown))}")
        if any(not callable(callback) for callback in supplied.values()):
            raise TypeError("UI callbacks must be callable")
        self._callbacks = supplied
        self._owner_name = self._clean_text(owner_name, fallback="Sir", limit=80)
        self._audio_level = 0.0
        self._transcript_title = "READY"
        self._transcript_text = "Onyx is standing by."
        self._callback_error = ""
        self._render_signature = self._signature()

    @staticmethod
    def _clean_text(value: object, *, fallback: str, limit: int) -> str:
        text = " ".join(str(value).split())[:limit]
        return text or fallback

    def _signature(self) -> tuple[object, ...]:
        snapshot = self._governor.snapshot()
        return (
            snapshot.target_fps,
            snapshot.animation_running,
            snapshot.particle_budget,
            snapshot.visible,
            snapshot.minimized,
            snapshot.reduced_motion,
            snapshot.muted,
        )

    def _emit_render_if_changed(self) -> None:
        signature = self._signature()
        if signature != self._render_signature:
            self._render_signature = signature
            self.renderPolicyChanged.emit()

    def _invoke(self, name: str, *args: object) -> bool:
        callback = self._callbacks.get(name)
        if callback is None:
            return False
        try:
            callback(*args)
        except Exception as exc:  # UI boundary: preserve the event loop.
            self._callback_error = self._clean_text(
                f"{name}: {type(exc).__name__}", fallback="callback error", limit=160
            )
            self.callbackErrorChanged.emit()
            return False
        return True

    @pyqtProperty(str, notify=stateChanged)
    def state(self) -> str:
        return self._governor.snapshot().state

    @pyqtProperty(str, notify=stateChanged)
    def stateLabel(self) -> str:  # noqa: N802 - QML property spelling
        return _STATE_COPY[self.state][0]

    @pyqtProperty(str, notify=stateChanged)
    def stateDetail(self) -> str:  # noqa: N802 - QML property spelling
        return _STATE_COPY[self.state][1]

    @pyqtProperty(str, notify=identityChanged)
    def ownerName(self) -> str:  # noqa: N802 - QML property spelling
        return self._owner_name

    @pyqtProperty(bool, notify=renderPolicyChanged)
    def muted(self) -> bool:
        return self._governor.snapshot().muted

    @pyqtProperty(bool, notify=renderPolicyChanged)
    def reducedMotion(self) -> bool:  # noqa: N802 - QML property spelling
        return self._governor.snapshot().reduced_motion

    @pyqtProperty(bool, notify=renderPolicyChanged)
    def surfaceVisible(self) -> bool:  # noqa: N802 - QML property spelling
        return self._governor.snapshot().visible

    @pyqtProperty(bool, notify=renderPolicyChanged)
    def minimized(self) -> bool:
        return self._governor.snapshot().minimized

    @pyqtProperty(bool, notify=renderPolicyChanged)
    def animationRunning(self) -> bool:  # noqa: N802 - QML property spelling
        return self._governor.snapshot().animation_running

    @pyqtProperty(int, notify=renderPolicyChanged)
    def targetFps(self) -> int:  # noqa: N802 - QML property spelling
        return self._governor.snapshot().target_fps

    @pyqtProperty(int, notify=renderPolicyChanged)
    def particleBudget(self) -> int:  # noqa: N802 - QML property spelling
        return self._governor.snapshot().particle_budget

    @pyqtProperty(float, notify=audioLevelChanged)
    def audioLevel(self) -> float:  # noqa: N802 - QML property spelling
        return self._audio_level

    @pyqtProperty(str, notify=transcriptChanged)
    def transcriptTitle(self) -> str:  # noqa: N802 - QML property spelling
        return self._transcript_title

    @pyqtProperty(str, notify=transcriptChanged)
    def transcriptText(self) -> str:  # noqa: N802 - QML property spelling
        return self._transcript_text

    @pyqtProperty(str, notify=callbackErrorChanged)
    def lastCallbackError(self) -> str:  # noqa: N802 - QML property spelling
        return self._callback_error

    def set_operational_state(self, state: str) -> None:
        if self._governor.set_state(state):
            self.stateChanged.emit()
        self._emit_render_if_changed()

    @pyqtSlot(str)
    def setOperationalState(self, state: str) -> None:  # noqa: N802
        self.set_operational_state(state)

    def set_muted(self, muted: bool) -> None:
        self._governor.set_muted(muted)
        self._emit_render_if_changed()

    @pyqtSlot(bool)
    def setMuted(self, muted: bool) -> None:  # noqa: N802
        self.set_muted(muted)

    def set_reduced_motion(self, reduced: bool) -> None:
        self._governor.set_reduced_motion(reduced)
        self._emit_render_if_changed()

    @pyqtSlot(bool)
    def setReducedMotion(self, reduced: bool) -> None:  # noqa: N802
        self.set_reduced_motion(reduced)

    def set_surface_active(self, active: bool) -> None:
        self._governor.set_lifecycle(visible=active, minimized=False)
        self._emit_render_if_changed()

    def set_lifecycle(self, *, visible: bool, minimized: bool = False) -> None:
        self._governor.set_lifecycle(visible=visible, minimized=minimized)
        self._emit_render_if_changed()

    @pyqtSlot(bool, bool)
    def setLifecycle(self, visible: bool, minimized: bool) -> None:  # noqa: N802
        self.set_lifecycle(visible=visible, minimized=minimized)

    @pyqtSlot()
    def advance(self) -> None:
        """Publish a settle-to-static transition without owning a timer."""
        self._emit_render_if_changed()

    def set_audio_level(self, level: float, *, now: float | None = None) -> bool:
        value = float(level)
        if not math.isfinite(value):
            return False
        if not self._governor.accept_audio_sample(now=now):
            return False
        value = max(0.0, min(1.0, value))
        if value != self._audio_level:
            self._audio_level = value
            self.audioLevelChanged.emit()
        return True

    @pyqtSlot(float, result=bool)
    def setAudioLevel(self, level: float) -> bool:  # noqa: N802
        return self.set_audio_level(level)

    def report_frame(self, duration_ms: float, *, now: float | None = None) -> bool:
        changed = self._governor.report_frame(duration_ms, now=now)
        self._emit_render_if_changed()
        return changed

    @pyqtSlot(float, result=bool)
    def reportFrame(self, duration_ms: float) -> bool:  # noqa: N802
        return self.report_frame(duration_ms)

    def set_owner_name(self, name: str) -> None:
        normalized = self._clean_text(name, fallback="Sir", limit=80)
        if normalized != self._owner_name:
            self._owner_name = normalized
            self.identityChanged.emit()

    def set_transcript(self, title: str, text: str) -> None:
        title_value = self._clean_text(title, fallback="ONYX", limit=80)
        text_value = self._clean_text(text, fallback="", limit=4000)
        if (title_value, text_value) != (
            self._transcript_title,
            self._transcript_text,
        ):
            self._transcript_title = title_value
            self._transcript_text = text_value
            self.transcriptChanged.emit()

    @pyqtSlot(str, result=bool)
    def submitCommand(self, command: str) -> bool:  # noqa: N802
        text = self._clean_text(command, fallback="", limit=8000)
        if not text:
            return False
        self.commandRequested.emit(text)
        self._invoke("command", text)
        return True

    @pyqtSlot(result=bool)
    def requestMuteToggle(self) -> bool:  # noqa: N802
        requested = not self.muted
        self.muteRequested.emit(requested)
        return self._invoke("mute", requested)

    @pyqtSlot(result=bool)
    def requestSettings(self) -> bool:  # noqa: N802
        self.settingsRequested.emit()
        return self._invoke("settings")

    @pyqtSlot(result=bool)
    def requestHistory(self) -> bool:  # noqa: N802
        self.historyRequested.emit()
        return self._invoke("history")

    @pyqtSlot(result=bool)
    def requestPermissions(self) -> bool:  # noqa: N802
        self.permissionsRequested.emit()
        return self._invoke("permissions")

    @pyqtSlot(result=bool)
    def requestClose(self) -> bool:  # noqa: N802
        self.closeRequested.emit()
        return self._invoke("close")

