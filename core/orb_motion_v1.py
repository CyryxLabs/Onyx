"""Low-CPU state-driven motion policy for the current Onyx Orb."""

from __future__ import annotations

import math
from dataclasses import dataclass


_STATES = frozenset(
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
class OrbMotionFrameV1:
    interval_ms: int
    scale: float
    rotation: float
    phase: float


class OrbMotionPolicyV1:
    """Organic ambient/voice motion with adaptive frame-budget backoff.

    The policy deliberately keeps the renderer cadence low.  Perceptible life
    comes from a roughly five-second respiratory envelope and audio smoothing,
    not from brute-force frame rate.
    """

    def __init__(self) -> None:
        self.state = "INITIALISING"
        self.visible = False
        self.minimized = False
        self.reduced_motion = False
        self.muted = False
        self.low_power = False
        self.audio_level = 0.0
        self._smoothed_audio_level = 0.0
        self.phase = 0.0
        self._adaptive_fps = 24
        self._slow_streak = 0
        self._healthy_streak = 0

    def configure(
        self,
        *,
        state: object | None = None,
        visible: object | None = None,
        minimized: object | None = None,
        reduced_motion: object | None = None,
        muted: object | None = None,
        low_power: object | None = None,
        audio_level: object | None = None,
    ) -> None:
        if state is not None:
            normalized = str(state).strip().upper()
            self.state = normalized if normalized in _STATES else "ERROR"
        if visible is not None:
            self.visible = bool(visible)
        if minimized is not None:
            self.minimized = bool(minimized)
        if reduced_motion is not None:
            self.reduced_motion = bool(reduced_motion)
        if muted is not None:
            self.muted = bool(muted)
        if low_power is not None:
            self.low_power = bool(low_power)
        if audio_level is not None:
            try:
                value = float(audio_level)
            except (TypeError, ValueError):
                value = 0.0
            self.audio_level = max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0

    @property
    def target_fps(self) -> int:
        if (
            not self.visible
            or self.minimized
            or self.reduced_motion
            or self.muted
            or self.state in {"MUTED", "OFFLINE"}
        ):
            return 0
        requested = {
            "SPEAKING": 24,
            "THINKING": 16,
            "PROCESSING": 16,
            "LISTENING": 10,
            "INITIALISING": 8,
            "ERROR": 8,
        }[self.state]
        if self.low_power:
            requested = min(requested, 10)
        return min(requested, self._adaptive_fps)

    @property
    def running(self) -> bool:
        return self.target_fps > 0

    @property
    def smoothed_audio_level(self) -> float:
        """Return the bounded envelope used by speech motion diagnostics."""

        return self._smoothed_audio_level

    def next_frame(self) -> OrbMotionFrameV1 | None:
        fps = self.target_fps
        if fps <= 0:
            return None
        frame_seconds = 1.0 / fps
        target_audio = self.audio_level if self.state == "SPEAKING" else 0.0
        time_constant = (
            0.10 if target_audio > self._smoothed_audio_level else 0.28
        )
        smoothing = 1.0 - math.exp(-frame_seconds / time_constant)
        self._smoothed_audio_level += (
            target_audio - self._smoothed_audio_level
        ) * smoothing

        # Radians per second.  LISTENING is a calm 4.8-second breath; active
        # states accelerate without ever requiring a high idle frame rate.
        angular_velocity = {
            "SPEAKING": 2.05 + self._smoothed_audio_level * 1.45,
            "THINKING": 1.62,
            "PROCESSING": 1.78,
            "LISTENING": math.tau / 4.8,
            "INITIALISING": math.tau / 5.6,
            "ERROR": math.tau / 6.4,
        }[self.state]
        self.phase = (self.phase + angular_velocity * frame_seconds) % math.tau

        if self.state == "SPEAKING":
            voice = self._smoothed_audio_level
            respiration = 0.0055 * math.sin(self.phase * 0.55 + 0.35)
            vocal_pulse = (0.006 + voice * 0.012) * math.sin(
                self.phase * 1.70
            )
            scale = 1.0 + respiration + voice * 0.018 + vocal_pulse
            rotation = (
                math.sin(self.phase * 0.43) * (0.65 + voice * 1.55)
                + math.sin(self.phase * 1.31) * voice * 0.42
            )
        elif self.state in {"THINKING", "PROCESSING"}:
            scale = (
                1.0
                + math.sin(self.phase) * 0.009
                + math.sin(self.phase * 0.5 + 0.65) * 0.0025
            )
            rotation = (
                math.sin(self.phase * 0.47) * 0.95
                + math.sin(self.phase * 1.09) * 0.22
            )
        elif self.state == "LISTENING":
            scale = (
                1.0
                + math.sin(self.phase) * 0.011
                + math.sin(self.phase * 0.5 + 0.65) * 0.0025
            )
            rotation = (
                math.sin(self.phase * 0.38) * 0.42
                + math.sin(self.phase * 0.91) * 0.10
            )
        else:
            scale = (
                1.0
                + math.sin(self.phase) * 0.007
                + math.sin(self.phase * 0.5 + 0.65) * 0.002
            )
            rotation = math.sin(self.phase * 0.36) * 0.32
        return OrbMotionFrameV1(
            interval_ms=max(42, round(1000 / fps)),
            scale=max(0.97, min(1.055, scale)),
            rotation=max(-3.0, min(3.0, rotation)),
            phase=self.phase,
        )

    def report_frame(self, duration_ms: object) -> bool:
        """Adapt after sustained misses; recover slowly to avoid oscillation."""

        try:
            duration = float(duration_ms)
        except (TypeError, ValueError):
            return False
        fps = self.target_fps
        if fps <= 0 or not math.isfinite(duration) or duration < 0:
            return False
        budget = 1000.0 / fps
        if duration > budget * 1.18:
            self._slow_streak += 1
            self._healthy_streak = 0
            if self._slow_streak >= 3:
                previous = self._adaptive_fps
                self._adaptive_fps = 16 if previous > 16 else 12
                self._slow_streak = 0
                return self._adaptive_fps != previous
            return False
        self._slow_streak = 0
        if duration < budget * 0.55:
            self._healthy_streak += 1
            if self._healthy_streak >= 180 and self._adaptive_fps < 24:
                previous = self._adaptive_fps
                self._adaptive_fps = 16 if previous == 12 else 24
                self._healthy_streak = 0
                return self._adaptive_fps != previous
        else:
            self._healthy_streak = 0
        return False


__all__ = ["OrbMotionFrameV1", "OrbMotionPolicyV1"]
