"""Deterministic render policy for the optional Onyx HUD V2 candidate.

The governor is deliberately independent from Qt.  It never owns a timer or a
thread; the host asks for a snapshot when a lifecycle or frame event occurs.
That keeps visibility, frame-rate and audio throttling policy testable without
starting a renderer.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable


FPS_TIERS = (12, 24, 30)
PARTICLE_BUDGETS = {12: 96, 24: 128, 30: 160}
ACTIVE_STATES = frozenset({"THINKING", "PROCESSING", "SPEAKING"})
KNOWN_STATES = frozenset(
    {
        "INITIALISING",
        "LISTENING",
        "THINKING",
        "PROCESSING",
        "SPEAKING",
        "MUTED",
        "OFFLINE",
        "ERROR",
    }
)


@dataclass(frozen=True, slots=True)
class RenderSnapshot:
    state: str
    target_fps: int
    animation_running: bool
    particle_budget: int
    visible: bool
    minimized: bool
    reduced_motion: bool
    muted: bool


class RenderGovernor:
    """Bounded FPS and lifecycle policy with adaptive hysteresis.

    Slow frames trigger a downgrade after three consecutive misses.  Upgrades
    require a long healthy streak and a cool-down, so borderline hardware does
    not oscillate between tiers.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        settle_seconds: float = 0.65,
        audio_hz: int = 20,
        downgrade_streak: int = 3,
        upgrade_streak: int = 90,
        upgrade_cooldown: float = 5.0,
    ) -> None:
        if settle_seconds < 0:
            raise ValueError("settle_seconds must be non-negative")
        if audio_hz < 1 or audio_hz > 20:
            raise ValueError("audio_hz must be in the inclusive range 1..20")
        if downgrade_streak < 1 or upgrade_streak < 1:
            raise ValueError("frame streak thresholds must be positive")
        self._clock = clock
        self._settle_seconds = float(settle_seconds)
        self._audio_interval = 1.0 / audio_hz
        self._downgrade_streak = int(downgrade_streak)
        self._upgrade_streak = int(upgrade_streak)
        self._upgrade_cooldown = float(upgrade_cooldown)

        now = self._now()
        self._state = "INITIALISING"
        self._visible = False
        self._minimized = False
        self._reduced_motion = False
        self._muted = False
        self._transition_at = now
        self._adaptive_cap = 30
        self._slow_frames = 0
        self._healthy_frames = 0
        self._tier_changed_at = now
        self._last_audio_at: float | None = None

    def _now(self, now: float | None = None) -> float:
        value = self._clock() if now is None else now
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("time must be finite")
        return value

    @staticmethod
    def normalize_state(state: object) -> str:
        value = str(state).strip().upper() or "INITIALISING"
        return value if value in KNOWN_STATES else "ERROR"

    def set_state(self, state: object, *, now: float | None = None) -> bool:
        normalized = self.normalize_state(state)
        if normalized == self._state:
            return False
        self._state = normalized
        self._transition_at = self._now(now)
        return True

    def set_lifecycle(
        self,
        *,
        visible: bool,
        minimized: bool = False,
        now: float | None = None,
    ) -> bool:
        visible = bool(visible)
        minimized = bool(minimized)
        changed = visible != self._visible or minimized != self._minimized
        if not changed:
            return False
        was_renderable = self._visible and not self._minimized
        self._visible = visible
        self._minimized = minimized
        is_renderable = visible and not minimized
        if is_renderable and not was_renderable:
            self._transition_at = self._now(now)
        return True

    def set_muted(self, muted: bool, *, now: float | None = None) -> bool:
        muted = bool(muted)
        if muted == self._muted:
            return False
        self._muted = muted
        self._transition_at = self._now(now)
        return True

    def set_reduced_motion(
        self, reduced: bool, *, now: float | None = None
    ) -> bool:
        reduced = bool(reduced)
        if reduced == self._reduced_motion:
            return False
        self._reduced_motion = reduced
        self._transition_at = self._now(now)
        return True

    def _state_tier(self) -> int:
        if self._state == "SPEAKING":
            return 30
        if self._state in {"THINKING", "PROCESSING"}:
            return 24
        return 12

    def animation_running(self, *, now: float | None = None) -> bool:
        current = self._now(now)
        if (
            not self._visible
            or self._minimized
            or self._reduced_motion
            or self._muted
            or self._state in {"MUTED", "OFFLINE"}
        ):
            return False
        if self._state in ACTIVE_STATES:
            return True
        return current - self._transition_at < self._settle_seconds

    def target_fps(self, *, now: float | None = None) -> int:
        if not self.animation_running(now=now):
            return 0
        return min(self._state_tier(), self._adaptive_cap)

    def snapshot(self, *, now: float | None = None) -> RenderSnapshot:
        current = self._now(now)
        fps = self.target_fps(now=current)
        return RenderSnapshot(
            state=self._state,
            target_fps=fps,
            animation_running=fps > 0,
            particle_budget=PARTICLE_BUDGETS[fps or 12],
            visible=self._visible,
            minimized=self._minimized,
            reduced_motion=self._reduced_motion,
            muted=self._muted,
        )

    def accept_audio_sample(self, *, now: float | None = None) -> bool:
        """Accept no more than one visual audio sample every 50 ms."""
        current = self._now(now)
        if self._last_audio_at is None:
            self._last_audio_at = current
            return True
        if current < self._last_audio_at:
            return False
        if current - self._last_audio_at + 1e-12 < self._audio_interval:
            return False
        self._last_audio_at = current
        return True

    def report_frame(self, duration_ms: float, *, now: float | None = None) -> bool:
        """Observe one measured frame and return whether the tier changed."""
        duration = float(duration_ms)
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("duration_ms must be finite and non-negative")
        current = self._now(now)
        fps = self.target_fps(now=current)
        if fps == 0:
            self._slow_frames = 0
            self._healthy_frames = 0
            return False

        budget_ms = 1000.0 / fps
        if duration > budget_ms * 1.18:
            self._slow_frames += 1
            self._healthy_frames = 0
            if self._slow_frames >= self._downgrade_streak:
                lower = 24 if self._adaptive_cap == 30 else 12
                changed = lower != self._adaptive_cap
                self._adaptive_cap = lower
                self._slow_frames = 0
                self._tier_changed_at = current
                return changed
            return False

        self._slow_frames = 0
        if duration < budget_ms * 0.72:
            self._healthy_frames += 1
        else:
            self._healthy_frames = 0

        if (
            self._healthy_frames >= self._upgrade_streak
            and current - self._tier_changed_at >= self._upgrade_cooldown
            and self._adaptive_cap < 30
        ):
            self._adaptive_cap = 24 if self._adaptive_cap == 12 else 30
            self._healthy_frames = 0
            self._tier_changed_at = current
            return True
        return False
