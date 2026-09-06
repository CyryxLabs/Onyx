"""Deterministic camera-motion attention for the living Onyx presence.

The tracker consumes frames from the camera stream already owned by ``ui.py``.
It does not open a device, retain frames, identify a person, or call a model.
Its only output is a bounded attention coordinate for a prominent foreground
gesture such as a hand moving in front of the camera.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CameraGestureAttention:
    """One privacy-minimal, normalized gesture-attention observation."""

    x: float
    y: float
    confidence: float
    foreground_ratio: float


class CameraGestureAttentionTrackerV1:
    """Track the largest moving foreground gesture against a learned backdrop."""

    def __init__(
        self,
        *,
        analysis_width: int = 320,
        warmup_frames: int = 12,
        calibration_observations: int = 8,
        minimum_foreground_ratio: float = 0.0035,
        maximum_foreground_ratio: float = 0.42,
        smoothing: float = 0.34,
        mirror_x: bool = True,
    ) -> None:
        if analysis_width < 96:
            raise ValueError("analysis_width must be at least 96")
        if warmup_frames < 1:
            raise ValueError("warmup_frames must be positive")
        if calibration_observations < 3:
            raise ValueError("calibration_observations must be at least 3")
        self.analysis_width = int(analysis_width)
        self._warmup_frames = int(warmup_frames)
        self._warmup_remaining = self._warmup_frames
        self._calibration_observations = int(calibration_observations)
        self._calibration_points: list[tuple[float, float, float]] = []
        self._calibrated = False
        self.minimum_foreground_ratio = float(minimum_foreground_ratio)
        self.maximum_foreground_ratio = float(maximum_foreground_ratio)
        self.smoothing = max(0.01, min(1.0, float(smoothing)))
        self.mirror_x = bool(mirror_x)
        self._background: Any | None = None
        self._smoothed: tuple[float, float] | None = None

    def reset(self) -> None:
        self._background = None
        self._smoothed = None
        self._warmup_remaining = self._warmup_frames
        self._calibration_points.clear()
        self._calibrated = False

    @property
    def calibration_phase(self) -> str:
        """Return the privacy-minimal live calibration phase."""

        if self._warmup_remaining > 0:
            return "background"
        if self._calibrated:
            return "ready"
        return "gesture"

    @property
    def calibration_progress(self) -> float:
        """Return bounded progress without exposing or retaining a frame."""

        if self._calibrated:
            return 1.0
        if self._warmup_remaining > 0:
            background = 1.0 - self._warmup_remaining / self._warmup_frames
            return max(0.0, min(0.24, background * 0.24))
        sample_progress = min(
            1.0,
            len(self._calibration_points) / self._calibration_observations,
        )
        if self._calibration_points:
            xs = [point[0] for point in self._calibration_points]
            ys = [point[1] for point in self._calibration_points]
            span = max(max(xs) - min(xs), max(ys) - min(ys))
            movement_progress = min(1.0, span / 0.42)
        else:
            movement_progress = 0.0
        return 0.25 + 0.74 * min(sample_progress, movement_progress)

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    def _observe_calibration(
        self,
        *,
        x: float,
        y: float,
        confidence: float,
        foreground_ratio: float,
    ) -> None:
        if self._calibrated or confidence < 0.12:
            return
        self._calibration_points.append((x, y, foreground_ratio))
        del self._calibration_points[: -max(24, self._calibration_observations)]
        if len(self._calibration_points) < self._calibration_observations:
            return
        xs = [point[0] for point in self._calibration_points]
        ys = [point[1] for point in self._calibration_points]
        if max(max(xs) - min(xs), max(ys) - min(ys)) < 0.42:
            return
        ratios = sorted(point[2] for point in self._calibration_points)
        median_ratio = ratios[len(ratios) // 2]
        # Adapt only inside conservative hand-sized limits. This improves a
        # distant/small hand without allowing noise or a full-frame lighting
        # change to become a valid target.
        self.minimum_foreground_ratio = max(
            0.0018,
            min(self.minimum_foreground_ratio, median_ratio * 0.24),
        )
        self.maximum_foreground_ratio = min(
            0.50,
            max(self.maximum_foreground_ratio, ratios[-1] * 1.55),
        )
        self._calibrated = True

    def update(self, frame: Any) -> CameraGestureAttention | None:
        """Return a bounded observation, or ``None`` when no gesture is reliable."""

        import cv2
        import numpy as np

        if frame is None or not hasattr(frame, "shape") or len(frame.shape) < 2:
            return None
        source_height, source_width = frame.shape[:2]
        if source_width < 2 or source_height < 2:
            return None

        analysis_height = max(
            72, int(round(source_height * self.analysis_width / source_width))
        )
        reduced = cv2.resize(
            frame,
            (self.analysis_width, analysis_height),
            interpolation=cv2.INTER_AREA,
        )
        gray = cv2.cvtColor(reduced, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (9, 9), 0)

        if self._background is None:
            self._background = gray.astype(np.float32)
            self._warmup_remaining -= 1
            return None

        if self._warmup_remaining > 0:
            cv2.accumulateWeighted(gray, self._background, 0.30)
            self._warmup_remaining -= 1
            return None

        backdrop = cv2.convertScaleAbs(self._background)
        delta = cv2.absdiff(gray, backdrop)
        threshold_value = max(14.0, float(np.percentile(delta, 84)) * 1.20)
        _, mask = cv2.threshold(delta, threshold_value, 255, cv2.THRESH_BINARY)
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        # Learn only quiet pixels so a hand does not immediately disappear into
        # the background model while it is being used as an attention target.
        cv2.accumulateWeighted(gray, self._background, 0.025, mask=cv2.bitwise_not(mask))

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        frame_area = float(self.analysis_width * analysis_height)
        foreground_ratio = area / frame_area
        if not (
            self.minimum_foreground_ratio
            <= foreground_ratio
            <= self.maximum_foreground_ratio
        ):
            return None

        moments = cv2.moments(contour)
        if abs(float(moments.get("m00", 0.0))) < 1e-6:
            return None
        centre_x = float(moments["m10"] / moments["m00"]) / self.analysis_width
        centre_y = float(moments["m01"] / moments["m00"]) / analysis_height
        if self.mirror_x:
            centre_x = 1.0 - centre_x
        target_x = max(-1.0, min(1.0, centre_x * 2.0 - 1.0))
        target_y = max(-1.0, min(1.0, 1.0 - centre_y * 2.0))

        if self._smoothed is None:
            smooth_x, smooth_y = target_x, target_y
        else:
            previous_x, previous_y = self._smoothed
            smooth_x = previous_x + (target_x - previous_x) * self.smoothing
            smooth_y = previous_y + (target_y - previous_y) * self.smoothing
        self._smoothed = (smooth_x, smooth_y)

        movement_strength = min(1.0, float(delta[mask > 0].mean()) / 46.0)
        area_strength = min(
            1.0,
            max(0.0, foreground_ratio - self.minimum_foreground_ratio) / 0.055,
        )
        confidence = max(0.0, min(1.0, movement_strength * (0.35 + area_strength * 0.65)))
        observation = CameraGestureAttention(
            x=smooth_x,
            y=smooth_y,
            confidence=confidence,
            foreground_ratio=foreground_ratio,
        )
        self._observe_calibration(
            x=observation.x,
            y=observation.y,
            confidence=observation.confidence,
            foreground_ratio=observation.foreground_ratio,
        )
        return observation
