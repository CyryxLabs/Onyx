"""Chromium integration test for the dashboard microphone AudioWorklet graph."""

from pathlib import Path
import unittest

from playwright.sync_api import Route, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "dashboard" / "static" / "app.html").read_text(encoding="utf-8")

MOCK_BROWSER_APIS = r"""
(() => {
  try { sessionStorage.setItem('onyx_token', 'test-token'); } catch (_) {}
  window.__onyxTest = {
    connections: [],
    disconnects: [],
    sockets: [],
    trackStopped: false,
    contextClosed: false,
  };

  const state = window.__onyxTest;
  const destination = { kind: 'destination' };
  class GraphNode {
    constructor(kind) { this.kind = kind; }
    connect(target) {
      state.connections.push(`${this.kind}->${target.kind}`);
      return target;
    }
    disconnect() { state.disconnects.push(this.kind); }
  }
  class FakeSource extends GraphNode { constructor() { super('source'); } }
  class FakeGain extends GraphNode {
    constructor() { super('gain'); this.gain = { value: 1 }; }
  }
  class FakeWorklet extends GraphNode {
    constructor() {
      super('worklet');
      this.port = { onmessage: null };
      window.__audioWorkletNode = this;
    }
  }
  class FakeScriptProcessor extends GraphNode {
    constructor() { super('script-processor'); this.onaudioprocess = null; }
  }
  class FakeAudioContext {
    constructor(options = {}) {
      this.sampleRate = options.sampleRate || 48000;
      this.state = 'running';
      this.destination = destination;
      this.audioWorklet = { addModule: async () => {} };
    }
    createMediaStreamSource() { return new FakeSource(); }
    createGain() {
      const gain = new FakeGain();
      window.__audioGain = gain;
      return gain;
    }
    createScriptProcessor() { return new FakeScriptProcessor(); }
    async resume() { this.state = 'running'; }
    async close() { state.contextClosed = true; this.state = 'closed'; }
  }
  window.AudioContext = FakeAudioContext;
  window.AudioWorkletNode = FakeWorklet;

  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: async () => ({
        getTracks: () => [{ stop: () => { state.trackStopped = true; } }],
      }),
    },
  });

  window.fetch = async (_url, options = {}) => {
    let scope = 'unknown';
    try { scope = JSON.parse(options.body || '{}').scope || scope; } catch (_) {}
    return {
      status: 200,
      ok: true,
      json: async () => ({ ticket: `${scope}-ticket` }),
    };
  };

  window.WebSocket = class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 1;
      this.sent = [];
      state.sockets.push(this);
      queueMicrotask(() => { if (this.onopen) this.onopen(); });
    }
    send(data) {
      const copy = data.slice(0);
      this.sent.push({
        byteLength: copy.byteLength,
        samples: Array.from(new Int16Array(copy)),
      });
    }
    close() {
      this.readyState = 3;
      queueMicrotask(() => { if (this.onclose) this.onclose({ code: 1000 }); });
    }
  };
})();
"""


class DashboardAudioWorkletBrowserTests(unittest.TestCase):
    def test_modern_graph_is_muted_active_forwards_pcm_and_cleans_up(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script(MOCK_BROWSER_APIS)

            def serve(route: Route) -> None:
                if route.request.url.endswith("/static/crypto.js"):
                    route.fulfill(status=200, content_type="application/javascript", body="")
                else:
                    route.fulfill(status=200, content_type="text/html", body=APP_HTML)

            page.route("**/*", serve)
            page.goto("https://onyx.test/app")
            page.locator("#mic-btn").click(force=True)
            page.wait_for_function(
                "() => typeof window.__audioWorkletNode?.port?.onmessage === 'function'"
            )

            active = page.evaluate("""() => ({
              connections: window.__onyxTest.connections,
              gain: window.__audioGain.gain.value,
              retained: Boolean(_audioSrc && _audioNd && _audioSink),
            })""")
            self.assertEqual(
                active["connections"],
                ["source->worklet", "worklet->gain", "gain->destination"],
            )
            self.assertEqual(active["gain"], 0)
            self.assertTrue(active["retained"])

            page.evaluate("""() => {
              const frame = new Float32Array(1024);
              frame.fill(0.25);
              window.__audioWorkletNode.port.onmessage({ data: frame });
            }""")
            audio_socket = page.evaluate("""() => {
              const socket = window.__onyxTest.sockets.find(
                item => item.url.includes('/ws/phone-audio')
              );
              return socket.sent[0];
            }""")
            self.assertEqual(audio_socket["byteLength"], 2048)
            self.assertEqual(len(audio_socket["samples"]), 1024)
            self.assertEqual(set(audio_socket["samples"]), {8192})

            page.locator("#mic-btn").click(force=True)
            page.wait_for_function("window.__onyxTest.contextClosed")
            stopped = page.evaluate("""() => ({
              disconnects: window.__onyxTest.disconnects,
              trackStopped: window.__onyxTest.trackStopped,
              released: !_audioSrc && !_audioNd && !_audioSink && !_audioCtx && !_micStm,
            })""")
            self.assertCountEqual(stopped["disconnects"], ["source", "worklet", "gain"])
            self.assertTrue(stopped["trackStopped"])
            self.assertTrue(stopped["released"])
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
