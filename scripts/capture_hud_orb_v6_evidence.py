"""Capture physical Windows HUD V6 evidence without activating live Onyx."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

os.environ["ONYX_HUD_V6_CANDIDATE"] = "1"
os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")

# These imports intentionally follow the pre-Qt renderer environment setup.
import psutil  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import ui  # noqa: E402
from core.onyx_hud_orb_v6 import install_candidate  # noqa: E402


def _pump(app: QApplication, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.006)


def _measure(app: QApplication, process: psutil.Process, seconds: float) -> float:
    logical = psutil.cpu_count(logical=True) or 1
    before_cpu = process.cpu_times()
    before_wall = time.perf_counter()
    _pump(app, seconds)
    elapsed = max(1e-6, time.perf_counter() - before_wall)
    after_cpu = process.cpu_times()
    consumed = (after_cpu.user + after_cpu.system) - (
        before_cpu.user + before_cpu.system
    )
    return consumed / elapsed / logical * 100.0


def _wait_for_texture(app: QApplication, window: ui.MainWindow) -> None:
    root = window._v5_host._quick.rootObject()
    texture = root.findChild(QQuickItem, "onyxParticlePresenceTextureV6")
    if texture is None:
        raise RuntimeError("V6 particle texture item is missing")
    deadline = time.perf_counter() + 30.0
    while float(texture.property("progress")) < 1.0:
        if time.perf_counter() >= deadline:
            raise RuntimeError(
                "V6 particle texture did not become ready: "
                f"progress={texture.property('progress')}"
            )
        _pump(app, 0.05)
    _pump(app, 0.75)


def _verify_single_quick_widget(expected: object) -> int:
    """Physically enumerate the process' Qt Quick widgets and fail closed."""

    from PySide6.QtQuickWidgets import QQuickWidget

    widgets = [
        widget
        for widget in QApplication.allWidgets()
        if isinstance(widget, QQuickWidget)
    ]
    if widgets != [expected]:
        raise RuntimeError(
            "physical renderer count mismatch: "
            f"expected the candidate host only, found {len(widgets)}"
        )
    return len(widgets)


def capture(output: Path, metrics: Path) -> dict[str, object]:
    app = QApplication.instance() or QApplication([])
    ui.MainWindow._check_config = lambda _self: True
    if not install_candidate(ui):
        raise RuntimeError("V6 candidate opt-in was not accepted")

    window = ui.MainWindow("")
    window.resize(1440, 900)
    window.show()
    _pump(app, 2.0)
    _wait_for_texture(app, window)
    quick_widget_count = _verify_single_quick_widget(window._v5_host._quick)
    process = psutil.Process()
    try:
        window.hud.set_operational_state("THINKING")
        window.hud.sync_animation()
        _pump(app, 1.0)
        target_fps = window.hud.projection.targetFps
        active_cpu = _measure(app, process, 4.0)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(output), "PNG"):
            raise RuntimeError("physical HUD screenshot could not be saved")

        window.hud.set_operational_state("LISTENING")
        _pump(app, 1.0)
        idle_target_fps = window.hud.projection.targetFps
        idle_cpu = _measure(app, process, 4.0)

        window.hide()
        window.hud.sync_animation()
        _pump(app, 0.5)
        hidden_target_fps = window.hud.projection.targetFps
        hidden_cpu = _measure(app, process, 4.0)

        graphics_api = str(QQuickWindow.graphicsApi())
        result = {
            "platform": sys.platform,
            "graphics_api": graphics_api,
            "resolution": [1440, 900],
            "logical_cpus": psutil.cpu_count(logical=True),
            "active_host_cpu_percent": active_cpu,
            "idle_host_cpu_percent": idle_cpu,
            "hidden_host_cpu_percent": hidden_cpu,
            "active_target_fps": target_fps,
            "idle_target_fps": idle_target_fps,
            "hidden_target_fps": hidden_target_fps,
            "rss_mib": process.memory_info().rss / (1024 * 1024),
            "quick_widgets": quick_widget_count,
            "root_object": window._v5_host._quick.rootObject().objectName(),
            "renderer_mode": window.hud.renderer_mode,
            "settled_measurement": True,
        }
        metrics.parent.mkdir(parents=True, exist_ok=True)
        metrics.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
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
    result = capture(args.output.resolve(), args.metrics.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
