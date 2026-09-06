from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

if __package__ in {None, ""}:
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

import sounddevice as sd

from core.audio_device_selection_v1 import AudioDeviceSelectionV1
from core.live_voice_preference_v1 import LiveVoicePreferenceV1, VOICES
from core.paths import memory_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onyx-audio")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    voice = sub.add_parser("voice")
    voice.add_argument("name", choices=VOICES)
    device = sub.add_parser("device")
    device.add_argument("direction", choices=("input", "output"))
    device.add_argument("name")
    args = parser.parse_args(argv)
    voice_profile = LiveVoicePreferenceV1(memory_dir() / "live_voice_preference_v1.json")
    devices = AudioDeviceSelectionV1(memory_dir() / "audio_device_selection_v1.json", sd)
    if args.command == "voice":
        result = {
            "voice": voice_profile.set(args.name),
            "restart_required": False,
            "active_runtime_refresh": "automatic",
        }
    elif args.command == "device":
        result = {
            "device": asdict(devices.select(args.direction, args.name)),
            "restart_required": False,
            "active_runtime_refresh": "automatic",
        }
    else:
        result = {"voice": voice_profile.get(), "voices": VOICES, "devices": devices.status()}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
