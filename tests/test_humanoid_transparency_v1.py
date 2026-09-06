"""Real Chromium pixel checks for the transparent humanoid successor."""

import functools
import http.server
import threading
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class HumanoidTransparencyTests(unittest.TestCase):
    viewport = {"width": 1000, "height": 650}
    def test_geometry_shaders_and_animation_are_unchanged(self):
        old = (ROOT / "qml/web/onyx-humanoid-three-v2.html").read_text()
        expected = old.replace("background:#050607", "background:transparent")
        expected = expected.replace("alpha:false", "alpha:true")
        expected = expected.replace("renderer.setClearColor(0x050607, 1);", "renderer.setClearColor(0x050607, 0);")
        actual = (ROOT / "qml/web/onyx-humanoid-three-v4.html").read_text()
        self.assertEqual(expected.strip(), actual.strip())

    def test_live_and_continuity_frames_have_transparent_corners(self):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "qml/web"))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport=self.viewport)
                    page.goto(f"http://127.0.0.1:{server.server_port}/onyx-humanoid-three-v5.html")
                    page.wait_for_function("window.__ONYX_RENDER_INFO__?.().presentedFrames > 5", timeout=60000)
                    pixels = page.evaluate("""async () => {
                        const canvas = document.querySelector('#present');
                        const ctx = canvas.getContext('2d');
                        const corner = Array.from(ctx.getImageData(0,0,1,1).data);
                        const image = new Image();
                        image.src = window.OnyxEntity.captureFrame();
                        await image.decode();
                        const copy = document.createElement('canvas');
                        copy.width=image.width;copy.height=image.height;
                        const c=copy.getContext('2d');c.drawImage(image,0,0);
                        const data=c.getImageData(0,0,copy.width,copy.height).data;
                        let visible=0;
                        for(let i=3;i<data.length;i+=4) if(data[i]>0) visible++;
                        return {corner, backupCorner:Array.from(c.getImageData(0,0,1,1).data), visible};
                    }""")
                    self.assertEqual(pixels["corner"][3], 0)
                    self.assertEqual(pixels["backupCorner"][3], 0)
                    self.assertGreater(pixels["visible"], 100)
                    health = page.evaluate("""() => {
                        const sample=document.createElement('canvas');
                        sample.width=80;sample.height=45;
                        const ctx=sample.getContext('2d');
                        ctx.fillStyle='#ffffff';ctx.fillRect(0,0,80,45);
                        const complete=frameIsComplete(sample);
                        ctx.clearRect(0,0,80,45);
                        const empty=frameIsComplete(sample);
                        ctx.fillRect(0,0,80,10);
                        const partial=frameIsComplete(sample);
                        return {complete,empty,partial};
                    }""")
                    self.assertEqual(health, {"complete": True, "empty": False, "partial": False})
                    for x, y in ((-1, 1), (1, -1), (0, 0)):
                        before = page.evaluate("window.__ONYX_RENDER_INFO__().presentedFrames")
                        page.evaluate("([x,y]) => { window.OnyxEntity.setState('SPEAKING', .7, false, true); window.OnyxEntity.setAttention(x,y,'pointer'); }", [x, y])
                        page.wait_for_function("n => window.__ONYX_RENDER_INFO__().presentedFrames > n + 3", arg=before, timeout=10000)
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class MobileHumanoidTransparencyTests(HumanoidTransparencyTests):
    viewport = {"width": 390, "height": 430}


if __name__ == "__main__":
    unittest.main()
