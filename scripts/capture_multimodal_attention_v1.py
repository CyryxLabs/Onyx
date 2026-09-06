"""Capture additive Three.js evidence for pointer and camera attention inputs."""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/onyx/evidence/hud-humanoid-v10/multimodal-attention-v1"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(_QuietHandler, directory=ROOT)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 780})
            page.goto(
                f"http://127.0.0.1:{server.server_address[1]}"
                "/qml/web/onyx-humanoid-three-v1.html",
                wait_until="networkidle",
            )
            page.add_style_tag(content="html,body{background:#020506 !important}")
            page.wait_for_timeout(3100)
            for x, y, source, name in (
                (-1.0, 0.65, "pointer", "01-pointer-upper-left.png"),
                (1.0, -0.60, "pointer", "02-pointer-lower-right.png"),
                (-0.85, -0.20, "camera", "03-camera-gesture-left.png"),
                (0.85, 0.25, "camera", "04-camera-gesture-right.png"),
            ):
                page.evaluate(
                    "([x,y,source])=>window.OnyxEntity.setAttention(x,y,source)",
                    [x, y, source],
                )
                page.wait_for_timeout(650)
                page.screenshot(path=OUTPUT / name)
            print(page.evaluate("window.__ONYX_RENDER_INFO__()"))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
