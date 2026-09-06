"""Capture physical HUD V7 evidence without changing live activation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ["ONYX_HUD_V6_CANDIDATE"] = "1"
os.environ["ONYX_HUD_V7_LIVE"] = "1"
os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")

import psutil  # noqa: E402
from PyQt6.QtQuick import QQuickWindow  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import ui  # noqa: E402
from core.onyx_hud_orb_v6 import install_candidate as install_v6  # noqa: E402
from core.onyx_hud_orb_v7 import install_candidate as install_v7  # noqa: E402
from scripts.capture_hud_orb_v6_evidence import (  # noqa: E402
    _measure,
    _pump,
    _verify_single_quick_widget,
)


def _measure_quiescent(
    app: QApplication, process: psutil.Process, seconds: float
) -> float:
    """Measure a static scene without an artificial high-frequency pump."""
    logical = psutil.cpu_count(logical=True) or 1
    before = process.cpu_times()
    started = time.perf_counter()
    while time.perf_counter() - started < seconds:
        app.processEvents()
        time.sleep(0.25)
    elapsed = time.perf_counter() - started
    after = process.cpu_times()
    return (
        ((after.user + after.system) - (before.user + before.system))
        / elapsed
        / logical
        * 100
    )


def capture(output: Path, metrics: Path) -> dict[str, object]:
    app = QApplication.instance() or QApplication([])
    ui.MainWindow._check_config = lambda _self: True
    if not install_v6(ui) or not install_v7(ui):
        raise RuntimeError("V7 composition was not installed")
    window = ui.MainWindow("")
    window.resize(1440, 900)
    window.show()
    _pump(app, 2.0)
    count = _verify_single_quick_widget(window._v5_host._quick)
    process = psutil.Process()
    try:
        window.hud.set_operational_state("THINKING")
        window.hud.sync_animation()
        _pump(app, 1.0)
        active_fps = window.hud.projection.targetFps
        active_cpu = _measure(app, process, 4.0)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(output), "PNG"):
            raise RuntimeError("screenshot save failed")
        window.hud.set_operational_state("LISTENING")
        _pump(app, 1.0)
        idle_fps = window.hud.projection.targetFps
        idle_cpu = _measure_quiescent(app, process, 4.0)
        window.hide()
        window.hud.sync_animation()
        _pump(app, 0.5)
        hidden_fps = window.hud.projection.targetFps
        hidden_cpu = _measure_quiescent(app, process, 4.0)
        result = {
            "resolution": [1440, 900],
            "graphics_api": str(QQuickWindow.graphicsApi()),
            "active_host_cpu_percent": active_cpu,
            "idle_host_cpu_percent": idle_cpu,
            "hidden_host_cpu_percent": hidden_cpu,
            "active_target_fps": active_fps,
            "idle_target_fps": idle_fps,
            "hidden_target_fps": hidden_fps,
            "quick_widgets": count,
            "root_object": window._v5_host._quick.rootObject().objectName(),
            "renderer_mode": window.hud.renderer_mode,
        }
        metrics.parent.mkdir(parents=True, exist_ok=True)
        metrics.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return result
    finally:
        window.close()
        window.deleteLater()
        _pump(app, 0.1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("metrics", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            capture(args.output.resolve(), args.metrics.resolve()), sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
