"""Capture physical evidence for the arc-free HUD V9 successor."""

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
os.environ["ONYX_HUD_V9_LIVE"] = "1"
os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")

from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import ui  # noqa: E402
from core.onyx_hud_orb_v6 import install_candidate as install_v6  # noqa: E402
from core.onyx_hud_orb_v7 import install_candidate as install_v7  # noqa: E402
from core.onyx_hud_orb_v8 import install_candidate as install_v8  # noqa: E402
from core.onyx_hud_orb_v9 import install_candidate as install_v9  # noqa: E402
from scripts.capture_hud_orb_v6_evidence import _pump  # noqa: E402


def capture(output: Path, metrics: Path) -> dict[str, object]:
    app = QApplication.instance() or QApplication([])
    ui.MainWindow._check_config = lambda _self: True
    if not all((install_v6(ui), install_v7(ui), install_v8(ui), install_v9(ui))):
        raise RuntimeError("V9 composition was not installed")
    window = ui.MainWindow("")
    window.resize(1440, 900)
    window.show()
    _pump(app, 1.5)
    try:
        root = window._v5_host._quick.rootObject()
        command = root.findChild(QQuickItem, "liveCommandInputV7")
        voice = root.findChild(QQuickItem, "onyxOrbVoiceLayerV8")
        if command is None or voice is None:
            raise RuntimeError("V9 inherited interaction contract is incomplete")
        canvas_siblings = [
            child
            for child in command.parent().childItems()
            if callable(getattr(child, "requestPaint", None))
        ]
        if len(canvas_siblings) != 1 or canvas_siblings[0].isVisible():
            raise RuntimeError("decorative command arcs remain visible")
        output.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(output), "PNG"):
            raise RuntimeError("V9 screenshot could not be saved")
        result = {
            "resolution": [window.width(), window.height()],
            "graphics_api": str(QQuickWindow.graphicsApi()),
            "root_object": root.objectName(),
            "renderer_mode": window.hud.renderer_mode,
            "decorative_arc_canvases": len(canvas_siblings),
            "visible_decorative_arc_canvases": sum(
                int(item.isVisible()) for item in canvas_siblings
            ),
            "command_input_present": True,
            "voice_layer_present": True,
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
    parser.add_argument("output", type=Path)
    parser.add_argument("metrics", type=Path)
    args = parser.parse_args()
    result = capture(args.output.resolve(), args.metrics.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
