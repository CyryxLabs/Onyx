from __future__ import annotations

import json

import pytest

from core.vision_repetition_counter_v1 import (
    VisionRepetitionContractError,
    VisionRepetitionCounterV1,
    preview_sequence,
)
from scripts import onyx_vision_repetition_cli


def _calibration() -> list[tuple[float, float, float]]:
    return [
        (0.65, 0.9, 0.0),
        (0.55, 0.9, 0.1),
        (0.25, 0.9, 0.2),
        (-0.15, 0.9, 0.3),
        (-0.60, 0.9, 0.4),
        (-0.45, 0.9, 0.5),
        (0.15, 0.9, 0.6),
        (0.62, 0.9, 0.7),
    ]


def test_complete_cycles_are_draft_estimates_only() -> None:
    samples = _calibration() + [
        (-0.60, 0.9, 1.0),
        (0.65, 0.9, 1.6),
        (-0.60, 0.9, 2.2),
        (0.65, 0.9, 2.8),
    ]
    result = preview_sequence("push-up", samples)
    assert result.status == "draft"
    assert result.calibrated is True
    assert result.repetitions == 2
    assert "Owner confirmation required" in result.limitation


def test_noise_low_confidence_and_partial_cycles_do_not_count() -> None:
    counter = VisionRepetitionCounterV1()
    counter.start("squat")
    for sample in _calibration():
        counter.update(*sample)
    counter.update(-0.7, 0.2, 1.0)
    counter.update(0.7, 0.2, 1.1)
    counter.update(-0.7, 0.9, 1.2)
    result = counter.stop()
    assert result.repetitions == 0
    assert result.ignored_samples == 2


def test_stale_signal_resets_phase_and_requires_a_fresh_complete_cycle() -> None:
    counter = VisionRepetitionCounterV1(stale_seconds=1.0)
    counter.start("push-up")
    for sample in _calibration():
        counter.update(*sample)
    counter.update(-0.7, 0.9, 1.0)
    counter.update(0.7, 0.9, 4.0)
    assert counter.snapshot().repetitions == 0
    counter.update(-0.7, 0.9, 4.6)
    counter.update(0.7, 0.9, 5.2)
    assert counter.stop().repetitions == 1


@pytest.mark.parametrize(
    "sample",
    [
        (1.1, 0.5, 0.0),
        (0.0, 1.1, 0.0),
        (0.0, 0.5, -1.0),
        (float("nan"), 0.5, 0.0),
    ],
)
def test_invalid_signal_is_rejected(sample: tuple[float, float, float]) -> None:
    counter = VisionRepetitionCounterV1()
    counter.start("push-up")
    with pytest.raises(VisionRepetitionContractError):
        counter.update(*sample)


def test_cli_is_camera_free_and_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    args = ["preview-sequence", "--activity", "push-up"]
    for position, confidence, observed_at in _calibration():
        args.append(f"--sample={position}:{confidence}:{observed_at}")
    assert onyx_vision_repetition_cli.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["contract"] == "OnyxVisionRepetitionEstimate.v1"
    assert output["status"] == "draft"


def test_counter_retains_no_frame_or_identity_surface() -> None:
    counter = VisionRepetitionCounterV1()
    assert not any(
        token in name.lower()
        for name in vars(counter)
        for token in ("frame", "image", "face", "identity")
    )


def test_preview_sequence_has_a_hard_sample_bound() -> None:
    samples = ((0.0, 0.9, float(index)) for index in range(10_001))
    with pytest.raises(VisionRepetitionContractError, match="sample bound"):
        preview_sequence("push-up", samples)
