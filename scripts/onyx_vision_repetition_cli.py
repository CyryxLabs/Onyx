"""Machine-readable, camera-free preview for Onyx repetition estimation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


if __package__ in {None, ""}:
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from core.vision_repetition_counter_v1 import (  # noqa: E402
    VisionRepetitionContractError,
    preview_sequence,
)


def _sample(value: str) -> tuple[float, float, float]:
    try:
        position, confidence, observed_at = value.split(":", 2)
        return float(position), float(confidence), float(observed_at)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "sample must use position:confidence:seconds"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onyx-vision-repetitions")
    parser.add_argument("preview-sequence", choices=("preview-sequence",))
    parser.add_argument("--activity", required=True)
    parser.add_argument("--sample", action="append", type=_sample, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = preview_sequence(args.activity, args.sample)
    except VisionRepetitionContractError as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
