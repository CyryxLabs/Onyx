"""Capture deterministic offscreen evidence for the current humanoid HUD."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core.onyx_hud_orb_v14 as hud_v14  # noqa: E402
import ui  # noqa: E402
from core import onyx_hud_orb_v6 as hud_v6  # noqa: E402
from core import onyx_hud_orb_v7 as hud_v7  # noqa: E402
from core import onyx_hud_orb_v8 as hud_v8  # noqa: E402
from core import onyx_hud_orb_v9 as hud_v9  # noqa: E402


OUTPUT_DIR = ROOT / "docs/onyx/evidence/hud-humanoid-v10"


def main() -> int:
    app = QApplication.instance() or QApplication(["onyx-humanoid-v10-capture"])
    ui.MainWindow._check_config = lambda _self: True
    ui.MainWindow._create_desktop_shortcut = lambda _self: None
    ui.install_current_hud_v10 = lambda: True
    predecessors = (hud_v6, hud_v7, hud_v8, hud_v9)
    for predecessor in predecessors:
        os.environ[predecessor.FLAG_NAME] = "1"
        if not predecessor.install_candidate(ui):
            raise RuntimeError(f"failed to install {predecessor.__name__}")
    if not hud_v14.install_current(ui):
        raise RuntimeError("failed to install humanoid HUD V14")

    window = ui.MainWindow("")
    window.resize(1440, 900)
    window.show()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    captures = ((700, "formation.png"), (1800, "forming-head.png"),
                (3000, "stable.png"))
    for wait_ms, name in captures:
        QTest.qWait(wait_ms)
        app.processEvents()
        output = OUTPUT_DIR / name
        if not window._v5_host._quick.grab().save(str(output), "PNG"):
            raise RuntimeError(f"failed to save humanoid HUD evidence: {name}")
    window._exit_requested = True
    window.close()
    window.deleteLater()
    for _ in range(5):
        app.processEvents()
    hud_v14.uninstall_candidate(ui)
    for predecessor in reversed(predecessors):
        predecessor.uninstall_candidate(ui)
    print(OUTPUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
