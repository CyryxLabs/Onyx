"""Exercise READY, LISTENING and SPEAKING as temporal Three.js sequences."""

from __future__ import annotations

import io
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_humanoid_temporal_stability_v1 import (  # noqa: E402
    _write_evidence,
    analyse_frames,
)


OUTPUT = ROOT / "evidence/live/humanoid-three-temporal-v1"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def _capture_sequence(page: object, count: int = 30) -> list[Image.Image]:
    frames = []
    for _ in range(count):
        encoded = page.screenshot(type="png")
        frames.append(Image.open(io.BytesIO(encoded)).convert("RGB"))
        page.wait_for_timeout(40)
    return frames


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(_QuietHandler, directory=ROOT)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report: dict[str, object] = {}
    console_errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 820})
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.goto(
                f"http://127.0.0.1:{server.server_address[1]}"
                "/qml/web/onyx-humanoid-three-v2.html",
                wait_until="networkidle",
            )
            page.wait_for_function("window.__ONYX_THREE_READY__ === true")
            page.wait_for_timeout(3100)
            scenarios = (
                ("ready", "READY", 0.0, (640, 410)),
                ("listening", "LISTENING", 0.0, (310, 210)),
                ("speaking", "SPEAKING", 0.82, (970, 610)),
            )
            for name, mode, audio, pointer in scenarios:
                page.evaluate(
                    "([mode,audio])=>window.OnyxEntity.setState(mode,audio,false,true)",
                    [mode, audio],
                )
                page.mouse.move(*pointer)
                page.wait_for_timeout(300)
                frames = _capture_sequence(page)
                metrics = analyse_frames(frames)
                _write_evidence(OUTPUT / name, frames, metrics)
                report[name] = {
                    key: value for key, value in metrics.items() if key != "samples"
                }
            report["renderer"] = page.evaluate("window.__ONYX_RENDER_INFO__()")
            report["console_errors"] = console_errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    stable = all(bool(report[name]["stable"]) for name in ("ready", "listening", "speaking"))
    stable = stable and not console_errors
    report["stable"] = stable
    (OUTPUT / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report))
    return 0 if stable else 1


if __name__ == "__main__":
    raise SystemExit(main())
