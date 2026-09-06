from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from core.camera_gesture_attention_v1 import CameraGestureAttentionTrackerV1


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui.py"


def _frame(*, rectangle: tuple[int, int, int, int] | None = None) -> np.ndarray:
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    if rectangle is not None:
        x1, y1, x2, y2 = rectangle
        cv2.rectangle(frame, (x1, y1), (x2, y2), (235, 235, 235), -1)
    return frame


def _warm(tracker: CameraGestureAttentionTrackerV1) -> None:
    for _ in range(7):
        assert tracker.update(_frame()) is None


def test_tracker_emits_no_identity_data_or_static_background_observation() -> None:
    tracker = CameraGestureAttentionTrackerV1(warmup_frames=3)
    _warm(tracker)
    assert tracker.update(_frame()) is None
    assert set(vars(tracker).keys()).isdisjoint({"frames", "face", "identity"})


def test_moving_hand_sized_foreground_maps_to_mirrored_attention() -> None:
    tracker = CameraGestureAttentionTrackerV1(warmup_frames=3, smoothing=1.0)
    _warm(tracker)
    observation = tracker.update(_frame(rectangle=(22, 45, 88, 135)))
    assert observation is not None
    assert 0.35 < observation.x <= 1.0
    assert -0.25 < observation.y < 0.25
    assert 0.0 < observation.confidence <= 1.0
    assert 0.0035 <= observation.foreground_ratio <= 0.42


def test_tracker_rejects_a_nearly_full_frame_change() -> None:
    tracker = CameraGestureAttentionTrackerV1(warmup_frames=3)
    _warm(tracker)
    assert tracker.update(_frame(rectangle=(0, 0, 319, 179))) is None


def test_hand_sweep_materializes_session_calibration_without_frames() -> None:
    tracker = CameraGestureAttentionTrackerV1(
        warmup_frames=3,
        calibration_observations=4,
        smoothing=1.0,
    )
    _warm(tracker)
    assert tracker.calibration_phase == "gesture"
    for x1 in (18, 72, 132, 206):
        observation = tracker.update(_frame(rectangle=(x1, 45, x1 + 52, 135)))
        assert observation is not None
    assert tracker.calibrated is True
    assert tracker.calibration_phase == "ready"
    assert tracker.calibration_progress == 1.0
    assert set(vars(tracker)).isdisjoint({"frames", "face", "identity"})


def test_live_host_arbitrates_camera_before_global_pointer_without_second_camera() -> None:
    source = UI.read_text(encoding="utf-8")
    for token in (
        "CameraGestureAttentionTrackerV1()",
        "self._cam_attention_sig.emit",
        "self._cam_calibration_sig.emit",
        "projection.cameraActive",
        "QCursor.pos()",
        'self._set_visual_attention(x, y, "camera")',
        'self._set_visual_attention(x, y, "pointer")',
        "self._hud_cam_stack.setCurrentWidget(self._v5_host)",
    ):
        assert token in source
    assert source.count("cv2.VideoCapture(") == 2  # configured device + fallback only
