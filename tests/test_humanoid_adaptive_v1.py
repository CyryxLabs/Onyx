"""Real renderer counters, alpha, and stop behavior; no promised hardware FPS."""
import functools
import http.server
import json
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def test_real_adaptive_renderer():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(ROOT / 'qml/web'))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1000, 'height': 650})
                page.goto(f'http://127.0.0.1:{server.server_port}/onyx-humanoid-three-v7.html')
                page.wait_for_function('window.__ONYX_RENDER_INFO__?.().presentedFrames > 5', timeout=60000)
                page.evaluate("window.OnyxEntity.setState('SPEAKING',.5,false,true)")
                page.wait_for_function('window.__ONYX_RENDER_INFO__().measuredFps > 0', timeout=15000)
                # Sample after formation and enough frames to exercise recovery.
                start = page.evaluate('window.__ONYX_RENDER_INFO__().renderedFrames')
                page.wait_for_function('n => window.__ONYX_RENDER_INFO__().renderedFrames >= n + 200',
                                       arg=start, timeout=30000)
                info = page.evaluate('window.__ONYX_RENDER_INFO__()')
                assert 0 < info['measuredFps'] <= 65
                assert info['targetFps'] in (24, 30, 60)
                assert info['presentedFrames'] <= info['renderedFrames']
                assert page.evaluate("document.querySelector('#present').getContext('2d').getImageData(0,0,1,1).data[3]") == 0
                page.evaluate("window.OnyxEntity.setState('LISTENING',0,false,false)")
                before = page.evaluate('window.__ONYX_RENDER_INFO__().renderedFrames')
                page.wait_for_timeout(300)
                after = page.evaluate('window.__ONYX_RENDER_INFO__().renderedFrames')
                assert after == before
                print('RENDER_SAMPLE=' + json.dumps(info, sort_keys=True))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
