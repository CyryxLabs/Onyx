"""Capture physical HUD V8 voice-reactive evidence without changing live Onyx."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ["ONYX_HUD_V6_CANDIDATE"] = "1"
os.environ["ONYX_HUD_V7_LIVE"] = "1"
os.environ["ONYX_HUD_V8_LIVE"] = "1"
os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")

import psutil  # noqa: E402
from PyQt6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import ui  # noqa: E402
from core.onyx_hud_orb_v6 import install_candidate as install_v6  # noqa: E402
from core.onyx_hud_orb_v7 import install_candidate as install_v7  # noqa: E402
from core.onyx_hud_orb_v8 import install_candidate as install_v8  # noqa: E402
from scripts.capture_hud_orb_v6_evidence import (  # noqa: E402
    _measure,
    _pump,
    _verify_single_quick_widget,
)
from scripts.capture_hud_orb_v7_evidence import _measure_quiescent  # noqa: E402


def _save(window: ui.MainWindow, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(output), "PNG"):
        raise RuntimeError(f"screenshot save failed: {output}")


def capture(
    speaking_a: Path,
    speaking_b: Path,
    idle: Path,
    metrics: Path,
) -> dict[str, object]:
    app = QApplication.instance() or QApplication([])
    ui.MainWindow._check_config = lambda _self: True
    if not install_v6(ui) or not install_v7(ui) or not install_v8(ui):
        raise RuntimeError("V8 composition was not installed")
    window = ui.MainWindow("")
    window.resize(1440, 900)
    window.show()
    _pump(app, 2.0)
    quick_widgets = _verify_single_quick_widget(window._v5_host._quick)
    root = window._v5_host._quick.rootObject()
    voice = root.findChild(QQuickItem, "onyxOrbVoiceLayerV8")
    if voice is None:
        raise RuntimeError("V8 voice particle layer is missing")
    process = psutil.Process()
    try:
        window.hud.set_operational_state("SPEAKING")
        window.hud.projection.set_audio_level(0.82)
        window.hud.sync_animation()
        _pump(app, 0.35)
        phase_a = float(voice.property("phase"))
        _save(window, speaking_a)
        _pump(app, 0.7)
        phase_b = float(voice.property("phase"))
        _save(window, speaking_b)
        speaking_fps = int(voice.property("governedFps"))
        speaking_target_fps = window.hud.projection.targetFps
        speaking_cpu = _measure(app, process, 4.0)

        window.hud.set_operational_state("LISTENING")
        _pump(app, 1.0)
        idle_phase_a = float(voice.property("phase"))
        _pump(app, 0.5)
        idle_phase_b = float(voice.property("phase"))
        idle_fps = int(voice.property("governedFps"))
        idle_target_fps = window.hud.projection.targetFps
        idle_cpu = _measure_quiescent(app, process, 4.0)
        _save(window, idle)

        window.hide()
        window.hud.sync_animation()
        _pump(app, 0.5)
        hidden_fps = int(voice.property("governedFps"))
        hidden_target_fps = window.hud.projection.targetFps
        hidden_cpu = _measure_quiescent(app, process, 4.0)
        result = {
            "resolution": [1440, 900],
            "graphics_api": str(QQuickWindow.graphicsApi()),
            "speaking_host_cpu_percent": speaking_cpu,
            "idle_host_cpu_percent": idle_cpu,
            "hidden_host_cpu_percent": hidden_cpu,
            "speaking_projection_target_fps": speaking_target_fps,
            "idle_projection_target_fps": idle_target_fps,
            "hidden_projection_target_fps": hidden_target_fps,
            "speaking_voice_layer_fps": speaking_fps,
            "idle_voice_layer_fps": idle_fps,
            "hidden_voice_layer_fps": hidden_fps,
            "speaking_phase_a": phase_a,
            "speaking_phase_b": phase_b,
            "idle_phase_a": idle_phase_a,
            "idle_phase_b": idle_phase_b,
            "quick_widgets": quick_widgets,
            "root_object": root.objectName(),
            "renderer_mode": window.hud.renderer_mode,
        }
        metrics.parent.mkdir(parents=True, exist_ok=True)
        metrics.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        window.close()
        window.deleteLater()
        _pump(app, 0.1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("speaking_a", type=Path)
    parser.add_argument("speaking_b", type=Path)
    parser.add_argument("idle", type=Path)
    parser.add_argument("metrics", type=Path)
    args = parser.parse_args()
    result = capture(
        args.speaking_a.resolve(),
        args.speaking_b.resolve(),
        args.idle.resolve(),
        args.metrics.resolve(),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
