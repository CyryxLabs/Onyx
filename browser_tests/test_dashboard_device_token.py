"""Chromium regression tests for Onyx dashboard credential storage."""

from pathlib import Path
import unittest

from playwright.sync_api import Route, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
LOGIN_HTML = (ROOT / "dashboard" / "static" / "login.html").read_text(encoding="utf-8")
APP_HTML = (ROOT / "dashboard" / "static" / "app.html").read_text(encoding="utf-8")


class DashboardDeviceTokenBrowserTests(unittest.TestCase):
    def test_rejected_device_token_is_not_reused_on_reload(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script("""(() => {
              const seededKey = '__onyxTestDeviceSeeded';
              const callsKey = '__onyxTestDeviceLoginCalls';
              if (!sessionStorage.getItem(seededKey)) {
                localStorage.setItem('onyx_device_token', 'expired-device');
                sessionStorage.setItem(callsKey, '0');
                sessionStorage.setItem(seededKey, '1');
              }
              Object.defineProperty(window, '__deviceLoginCalls', {
                configurable: true,
                get: () => Number(sessionStorage.getItem(callsKey) || '0'),
              });
              window.fetch = async () => {
                sessionStorage.setItem(callsKey, String(window.__deviceLoginCalls + 1));
                return { json: async () => ({ ok: false }) };
              };
            })();""")

            def serve(route: Route) -> None:
                route.fulfill(status=200, content_type="text/html", body=LOGIN_HTML)

            page.route("**/*", serve)
            page.goto("https://onyx.test/login")
            page.wait_for_function("window.__deviceLoginCalls === 1")
            page.wait_for_function("!localStorage.getItem('onyx_device_token')")
            page.reload()
            page.wait_for_timeout(100)
            self.assertEqual(page.evaluate("window.__deviceLoginCalls"), 1)
            browser.close()

    def test_current_session_credentials_enable_authenticated_app(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script("""(() => {
              sessionStorage.setItem('onyx_token', 'current-token');
              sessionStorage.setItem('onyx_key', 'current-key');
              window.fetch = async () => ({
                status: 200,
                ok: true,
                json: async () => ({ ticket: 'test-ticket' }),
              });
              window.WebSocket = class {
                constructor() { this.readyState = 1; }
              };
            })();""")

            def serve(route: Route) -> None:
                if route.request.url.endswith("/static/crypto.js"):
                    route.fulfill(status=200, content_type="text/javascript", body="")
                else:
                    route.fulfill(status=200, content_type="text/html", body=APP_HTML)

            page.route("**/*", serve)
            page.goto("https://onyx.test/")
            self.assertEqual(page.evaluate("sessionStorage.getItem('onyx_token')"), "current-token")
            self.assertEqual(page.evaluate("sessionStorage.getItem('onyx_key')"), "current-key")
            browser.close()

    def test_session_expiry_removes_current_keys(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script("""(() => {
              if (location.pathname === '/') {
                sessionStorage.setItem('onyx_token', 'current-token');
                sessionStorage.setItem('onyx_key', 'current-key');
              }
              window.fetch = async () => ({ status: 401, ok: false });
            })();""")

            def serve(route: Route) -> None:
                if route.request.url.endswith("/static/crypto.js"):
                    route.fulfill(status=200, content_type="text/javascript", body="")
                elif route.request.url.endswith("/login"):
                    route.fulfill(status=200, content_type="text/html", body="<title>Login</title>")
                else:
                    route.fulfill(status=200, content_type="text/html", body=APP_HTML)

            page.route("**/*", serve)
            page.goto("https://onyx.test/")
            page.wait_for_url("**/login")
            for key in ("onyx_token", "onyx_key"):
                self.assertIsNone(page.evaluate(f"sessionStorage.getItem('{key}')"))
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
