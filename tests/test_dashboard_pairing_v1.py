from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None, reason="fastapi not installed"
)


def _server(tmp_path: Path):
    from dashboard.server import DashboardServer

    root = Path(__file__).resolve().parents[1]
    return DashboardServer(
        local_ip="127.0.0.1",
        cert_dir=tmp_path / "certs",
        uploads_dir=tmp_path / "uploads",
        static_dir=root / "dashboard" / "static",
    )


def test_neutral_pair_page_contains_no_pending_key_or_token(tmp_path) -> None:
    from fastapi.testclient import TestClient

    server = _server(tmp_path)
    key = server.new_key()
    page = TestClient(server.app).get("/pair")
    assert page.status_code == 200
    assert key not in page.text
    assert "?key=" not in page.text
    assert "PAIR WITH ONYX" in page.text


def test_pair_consumes_code_once_and_returns_device_token_in_body(tmp_path) -> None:
    from fastapi.testclient import TestClient

    server = _server(tmp_path)
    client = TestClient(server.app)
    key = server.new_key()
    paired = client.post("/pair", json={"pin": key})
    assert paired.status_code == 200
    payload = paired.json()
    assert payload["ok"] is True
    assert payload["key"] == key
    assert payload["token"]
    assert payload["device_token"]
    assert key not in paired.request.url.path
    assert client.post("/pair", json={"pin": key}).status_code == 401


def test_credential_bearing_auto_login_route_is_retired(tmp_path) -> None:
    from fastapi.testclient import TestClient

    server = _server(tmp_path)
    key = server.new_key()
    retired = TestClient(server.app).get(f"/auto-login?key={key}")
    assert retired.status_code == 410
    assert key in server._pending_keys
