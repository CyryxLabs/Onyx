"""Capture deterministic formation and interaction frames from the Three.js HUD."""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "onyx" / "evidence" / "hud-humanoid-v10" / "motion-v2"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    handler = partial(_QuietHandler, directory=ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 780})
            page.goto(
                f"http://127.0.0.1:{port}/qml/web/onyx-humanoid-three-v1.html",
                wait_until="networkidle",
            )
            page.add_style_tag(content="html,body{background:#020506 !important}")
            for wait_ms, filename in (
                (250, "01-formation-0250.png"),
                (650, "02-formation-0900.png"),
                (900, "03-formation-1800.png"),
                (1200, "04-ready-3000.png"),
            ):
                page.wait_for_timeout(wait_ms)
                page.screenshot(path=OUTPUT / filename)
            page.evaluate("window.OnyxEntity.setState('LISTENING',0,false,true)")
            page.wait_for_timeout(600)
            page.screenshot(path=OUTPUT / "05-listening.png")
            page.evaluate("window.OnyxEntity.setState('SPEAKING',.85,false,true)")
            page.wait_for_timeout(600)
            page.screenshot(path=OUTPUT / "06-speaking.png")
            page.mouse.move(230, 180)
            page.wait_for_timeout(500)
            page.screenshot(path=OUTPUT / "06a-pointer-upper-left.png")
            page.mouse.move(1170, 580)
            page.wait_for_timeout(650)
            page.screenshot(path=OUTPUT / "06b-pointer-lower-right.png")
            page.evaluate("window.OnyxEntity.setState('READY',0,false,false)")
            page.set_viewport_size({"width": 1200, "height": 675})
            page.wait_for_timeout(250)
            page.screenshot(path=OUTPUT / "07-paused-resized.png")
            print(page.evaluate("window.__ONYX_RENDER_INFO__()"))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
