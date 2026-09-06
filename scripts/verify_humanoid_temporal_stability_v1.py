"""Measure temporal stability of the native Onyx humanoid surface."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


def _crop_humanoid(image: Image.Image) -> Image.Image:
    """Crop the immutable V13 humanoid viewport from a native window frame."""

    width, height = image.size
    return image.crop(
        (
            round(width * 0.25),
            round(height * 0.04),
            round(width * 0.75),
            round(height * 0.76),
        )
    )


def _frame_metrics(image: Image.Image) -> dict[str, float | int]:
    grayscale = _crop_humanoid(image).convert("L")
    histogram = grayscale.histogram()
    active_pixels = sum(histogram[9:])
    total_pixels = grayscale.width * grayscale.height
    band_luminance = []
    for band in range(4):
        top = round(grayscale.height * band / 4)
        bottom = round(grayscale.height * (band + 1) / 4)
        band_luminance.append(
            ImageStat.Stat(grayscale.crop((0, top, grayscale.width, bottom))).mean[0]
        )
    return {
        "active_pixels": active_pixels,
        "active_ratio": active_pixels / total_pixels,
        "mean_luminance": ImageStat.Stat(grayscale).mean[0],
        "band_luminance": band_luminance,
    }


def analyse_frames(frames: list[Image.Image]) -> dict[str, object]:
    if len(frames) < 8:
        raise ValueError("temporal stability analysis requires at least eight frames")
    samples = [_frame_metrics(frame) for frame in frames]
    active = [int(sample["active_pixels"]) for sample in samples]
    luminance = [float(sample["mean_luminance"]) for sample in samples]
    median_active = statistics.median(active)
    median_luminance = statistics.median(luminance)
    band_values = [sample["band_luminance"] for sample in samples]
    median_bands = [
        statistics.median(float(values[band]) for values in band_values)
        for band in range(4)
    ]
    active_floor = median_active * 0.72
    luminance_floor = median_luminance * 0.72
    luminance_ceiling = median_luminance * 1.32
    collapse_indices = [
        index
        for index, sample in enumerate(samples)
        if int(sample["active_pixels"]) < active_floor
        or float(sample["mean_luminance"]) < luminance_floor
        or float(sample["mean_luminance"]) > luminance_ceiling
        or any(
            float(sample["band_luminance"][band]) < median_bands[band] * 0.80
            or float(sample["band_luminance"][band]) > median_bands[band] * 1.25
            for band in range(4)
            if median_bands[band] > 1.0
        )
    ]
    differences = []
    for previous, current in zip(frames, frames[1:]):
        delta = ImageChops.difference(
            _crop_humanoid(previous).convert("L"),
            _crop_humanoid(current).convert("L"),
        )
        differences.append(ImageStat.Stat(delta).mean[0])
    return {
        "frame_count": len(frames),
        "median_active_pixels": median_active,
        "minimum_active_pixels": min(active),
        "active_floor": active_floor,
        "median_luminance": median_luminance,
        "minimum_luminance": min(luminance),
        "maximum_luminance": max(luminance),
        "luminance_floor": luminance_floor,
        "luminance_ceiling": luminance_ceiling,
        "median_band_luminance": median_bands,
        "collapse_indices": collapse_indices,
        "maximum_frame_delta": max(differences),
        "mean_frame_delta": statistics.fmean(differences),
        "stable": not collapse_indices,
        "samples": samples,
    }


def capture_native_frames(
    process_id: int,
    *,
    duration_seconds: float,
    interval_seconds: float,
) -> list[Image.Image]:
    # pywinauto imports comtypes and initializes COM. Keep that Windows-only
    # side effect out of pure frame analysis and test collection; the native
    # capture command owns the apartment when it is actually invoked.
    from pywinauto import Application

    application = Application(backend="uia").connect(process=process_id, timeout=20)
    window = application.top_window()
    window.wait("visible ready", timeout=20)
    frames: list[Image.Image] = []
    deadline = time.monotonic() + duration_seconds
    while time.monotonic() < deadline:
        frames.append(window.capture_as_image().convert("RGB"))
        time.sleep(interval_seconds)
    return frames


def _write_evidence(
    output: Path,
    frames: list[Image.Image],
    metrics: dict[str, object],
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    samples = metrics["samples"]
    low_index = min(
        range(len(frames)), key=lambda index: samples[index]["mean_luminance"]
    )
    high_index = max(
        range(len(frames)), key=lambda index: samples[index]["mean_luminance"]
    )
    frames[0].save(output / "first.png")
    frames[low_index].save(output / "lowest-luminance.png")
    frames[high_index].save(output / "highest-luminance.png")
    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--process-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--interval", type=float, default=0.10)
    parser.add_argument("--observe-only", action="store_true")
    args = parser.parse_args()
    frames = capture_native_frames(
        args.process_id,
        duration_seconds=args.duration,
        interval_seconds=args.interval,
    )
    metrics = analyse_frames(frames)
    _write_evidence(args.output.resolve(), frames, metrics)
    print(json.dumps({key: value for key, value in metrics.items() if key != "samples"}))
    return 0 if args.observe_only or metrics["stable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
