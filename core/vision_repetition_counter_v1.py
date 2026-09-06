"""Privacy-minimal repetition estimates from an existing normalized camera signal.

This module never opens a camera and never receives or retains image data.  The
live host may feed it the bounded vertical coordinate already produced by the
opted-in camera-attention pipeline.  Results are estimates and must remain
drafts until the owner confirms them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Final, Iterable


FEATURE_FLAG: Final = "ONYX_VISION_REPETITION_COUNTER_V1"
MIN_CALIBRATION_SAMPLES: Final = 8
MAX_CALIBRATION_SAMPLES: Final = 64
MAX_PREVIEW_SAMPLES: Final = 10_000


class VisionRepetitionContractError(ValueError):
    """The caller supplied an invalid or ambiguous signal contract."""


@dataclass(frozen=True, slots=True)
class RepetitionEstimateV1:
    contract: str
    activity: str
    status: str
    repetitions: int
    calibrated: bool
    confidence: float
    lower_threshold: float | None
    upper_threshold: float | None
    ignored_samples: int
    limitation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class VisionRepetitionCounterV1:
    """Count complete low-to-high cycles with calibration and hysteresis."""

    LIMITATION = (
        "Camera-derived repetition estimate only; no form, identity, medical, "
        "fitness-outcome, or device-certification claim. Owner confirmation required."
    )

    def __init__(
        self,
        *,
        minimum_confidence: float = 0.32,
        minimum_calibration_span: float = 0.42,
        minimum_cycle_seconds: float = 0.45,
        stale_seconds: float = 2.5,
    ) -> None:
        for value, label in (
            (minimum_confidence, "minimum_confidence"),
            (minimum_calibration_span, "minimum_calibration_span"),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise VisionRepetitionContractError(f"{label} must be numeric")
            if not 0.0 < float(value) <= 1.0:
                raise VisionRepetitionContractError(f"{label} is outside its bound")
        if not 0.1 <= float(minimum_cycle_seconds) <= 30.0:
            raise VisionRepetitionContractError("minimum_cycle_seconds is outside its bound")
        if not 0.5 <= float(stale_seconds) <= 60.0:
            raise VisionRepetitionContractError("stale_seconds is outside its bound")
        self.minimum_confidence = float(minimum_confidence)
        self.minimum_calibration_span = float(minimum_calibration_span)
        self.minimum_cycle_seconds = float(minimum_cycle_seconds)
        self.stale_seconds = float(stale_seconds)
        self._activity = ""
        self._active = False
        self._calibration: list[float] = []
        self._lower: float | None = None
        self._upper: float | None = None
        self._phase = "seeking_upper"
        self._repetitions = 0
        self._ignored = 0
        self._last_accepted_at: float | None = None
        self._last_cycle_at: float | None = None
        self._confidence_total = 0.0
        self._confidence_samples = 0

    @staticmethod
    def _activity_name(value: object) -> str:
        if type(value) is not str or not (1 <= len(value.strip()) <= 120):
            raise VisionRepetitionContractError("activity is empty or exceeds its bound")
        return value.strip()

    @staticmethod
    def _sample(position: object, confidence: object, observed_at: object) -> tuple[float, float, float]:
        values = (position, confidence, observed_at)
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            for value in values
        ):
            raise VisionRepetitionContractError("signal sample must contain finite numbers")
        bounded_position = float(position)
        bounded_confidence = float(confidence)
        timestamp = float(observed_at)
        if not -1.0 <= bounded_position <= 1.0:
            raise VisionRepetitionContractError("position is outside the normalized range")
        if not 0.0 <= bounded_confidence <= 1.0:
            raise VisionRepetitionContractError("confidence is outside its bound")
        if timestamp < 0.0:
            raise VisionRepetitionContractError("observed_at cannot be negative")
        return bounded_position, bounded_confidence, timestamp

    def start(self, activity: str) -> RepetitionEstimateV1:
        self._activity = self._activity_name(activity)
        self._active = True
        self._calibration.clear()
        self._lower = None
        self._upper = None
        self._phase = "seeking_upper"
        self._repetitions = 0
        self._ignored = 0
        self._last_accepted_at = None
        self._last_cycle_at = None
        self._confidence_total = 0.0
        self._confidence_samples = 0
        return self.snapshot()

    def stop(self) -> RepetitionEstimateV1:
        self._active = False
        return self.snapshot()

    @property
    def active(self) -> bool:
        return self._active

    def update(
        self, position: float, confidence: float, observed_at: float
    ) -> RepetitionEstimateV1:
        if not self._active:
            raise VisionRepetitionContractError("repetition counter is not active")
        position_value, confidence_value, timestamp = self._sample(
            position, confidence, observed_at
        )
        if self._last_accepted_at is not None and timestamp <= self._last_accepted_at:
            raise VisionRepetitionContractError("signal timestamps must increase")
        if confidence_value < self.minimum_confidence:
            self._ignored += 1
            return self.snapshot()
        if (
            self._last_accepted_at is not None
            and timestamp - self._last_accepted_at > self.stale_seconds
        ):
            self._phase = "seeking_upper"
        self._last_accepted_at = timestamp
        self._confidence_total += confidence_value
        self._confidence_samples += 1

        if self._lower is None or self._upper is None:
            self._calibration.append(position_value)
            del self._calibration[:-MAX_CALIBRATION_SAMPLES]
            if len(self._calibration) >= MIN_CALIBRATION_SAMPLES:
                low = min(self._calibration)
                high = max(self._calibration)
                span = high - low
                if span >= self.minimum_calibration_span:
                    self._lower = low + span * 0.28
                    self._upper = high - span * 0.28
                    self._phase = (
                        "seeking_lower" if position_value >= self._upper else "seeking_upper"
                    )
            return self.snapshot()

        if self._phase == "seeking_upper":
            if position_value >= self._upper:
                self._phase = "seeking_lower"
        elif self._phase == "seeking_lower":
            if position_value <= self._lower:
                self._phase = "returning_upper"
        elif position_value >= self._upper:
            if (
                self._last_cycle_at is None
                or timestamp - self._last_cycle_at >= self.minimum_cycle_seconds
            ):
                self._repetitions += 1
                self._last_cycle_at = timestamp
            self._phase = "seeking_lower"
        return self.snapshot()

    def snapshot(self) -> RepetitionEstimateV1:
        calibrated = self._lower is not None and self._upper is not None
        if not self._active:
            status = "draft" if self._activity else "idle"
        else:
            status = "tracking" if calibrated else "calibrating"
        confidence = (
            self._confidence_total / self._confidence_samples
            if self._confidence_samples
            else 0.0
        )
        return RepetitionEstimateV1(
            contract="OnyxVisionRepetitionEstimate.v1",
            activity=self._activity,
            status=status,
            repetitions=self._repetitions,
            calibrated=calibrated,
            confidence=round(confidence, 6),
            lower_threshold=self._lower,
            upper_threshold=self._upper,
            ignored_samples=self._ignored,
            limitation=self.LIMITATION,
        )


def preview_sequence(
    activity: str, samples: Iterable[tuple[float, float, float]]
) -> RepetitionEstimateV1:
    """Exercise the exact counter contract without opening a camera."""

    counter = VisionRepetitionCounterV1()
    counter.start(activity)
    for index, (position, confidence, observed_at) in enumerate(samples):
        if index >= MAX_PREVIEW_SAMPLES:
            raise VisionRepetitionContractError("preview sequence exceeds its sample bound")
        counter.update(position, confidence, observed_at)
    return counter.stop()


__all__ = [
    "FEATURE_FLAG",
    "RepetitionEstimateV1",
    "VisionRepetitionContractError",
    "VisionRepetitionCounterV1",
    "preview_sequence",
]
