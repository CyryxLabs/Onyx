"""State and quality bridge shared by the Qt Widgets and QML Orb renderers."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject
from core.qt_compat import pyqtProperty, pyqtSignal
from core.paths import config_file


QUALITY_BUDGETS = {"low": 256, "medium": 512, "high": 896}
ACTIVE_STATES = frozenset({"THINKING", "PROCESSING", "SPEAKING"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _settings(path: Path | None = None) -> dict:
    try:
        value = json.loads((path or config_file()).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def configured_quality(path: Path | None = None) -> str:
    """Return a validated low/medium/high tier; low is the fail-safe default."""
    value = os.environ.get("ONYX_ORB_QUALITY")
    if value is None:
        value = _settings(path).get("orb_quality", "low")
    normalized = str(value).strip().lower()
    return normalized if normalized in QUALITY_BUDGETS else "low"


def configured_reduced_motion(path: Path | None = None) -> bool:
    value = os.environ.get("ONYX_REDUCED_MOTION")
    if value is not None:
        return value.strip().lower() in _TRUE_VALUES
    return _settings(path).get("reduced_motion") is True


class OrbStateBridge(QObject):
    """Transition-driven state exposed to QML without a Python animation timer."""

    stateChanged = pyqtSignal()
    activeChanged = pyqtSignal()
    mutedChanged = pyqtSignal()
    reducedMotionChanged = pyqtSignal()
    qualityChanged = pyqtSignal()
    particleBudgetChanged = pyqtSignal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        quality: str | None = None,
        reduced_motion: bool | None = None,
    ) -> None:
        super().__init__(parent)
        selected = (quality or configured_quality()).strip().lower()
        self._quality = selected if selected in QUALITY_BUDGETS else "low"
        self._reduced_motion = (
            configured_reduced_motion()
            if reduced_motion is None
            else bool(reduced_motion)
        )
        self._state = "INITIALISING"
        self._muted = False
        self._surface_active = False
        self._active = False

    def _compute_active(self) -> bool:
        return (
            self._surface_active
            and not self._muted
            and not self._reduced_motion
            and self._state in ACTIVE_STATES
        )

    def _refresh_active(self) -> None:
        active = self._compute_active()
        if active != self._active:
            self._active = active
            self.activeChanged.emit()

    @pyqtProperty(str, notify=stateChanged)
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        normalized = str(state).strip().upper() or "INITIALISING"
        if normalized == self._state:
            return
        self._state = normalized
        self.stateChanged.emit()
        self._refresh_active()

    @pyqtProperty(bool, notify=activeChanged)
    def active(self) -> bool:
        return self._active

    def set_surface_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._surface_active:
            return
        self._surface_active = active
        self._refresh_active()

    @pyqtProperty(bool, notify=mutedChanged)
    def muted(self) -> bool:
        return self._muted

    def set_muted(self, muted: bool) -> None:
        muted = bool(muted)
        if muted == self._muted:
            return
        self._muted = muted
        self.mutedChanged.emit()
        self._refresh_active()

    @pyqtProperty(bool, notify=reducedMotionChanged)
    def reducedMotion(self) -> bool:  # noqa: N802 - QML property spelling
        return self._reduced_motion

    def set_reduced_motion(self, reduced: bool) -> None:
        reduced = bool(reduced)
        if reduced == self._reduced_motion:
            return
        self._reduced_motion = reduced
        self.reducedMotionChanged.emit()
        self._refresh_active()

    @pyqtProperty(str, notify=qualityChanged)
    def quality(self) -> str:
        return self._quality

    @pyqtProperty(int, notify=particleBudgetChanged)
    def particleBudget(self) -> int:  # noqa: N802 - QML property spelling
        return QUALITY_BUDGETS[self._quality]

    def set_quality(self, quality: str) -> None:
        normalized = str(quality).strip().lower()
        if normalized not in QUALITY_BUDGETS:
            normalized = "low"
        if normalized == self._quality:
            return
        self._quality = normalized
        self.qualityChanged.emit()
        self.particleBudgetChanged.emit()
