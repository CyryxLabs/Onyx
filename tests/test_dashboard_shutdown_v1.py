from __future__ import annotations

import asyncio

from dashboard import server as dashboard_server


def test_dashboard_serve_cancels_https_alias_when_primary_stops(
    monkeypatch,
) -> None:
    events: list[str] = []
    config_options: list[dict[str, object]] = []

    class FakeServer:
        def __init__(self, _config) -> None:
            pass

        async def serve(self) -> None:
            events.append("primary-start")
            await asyncio.sleep(0)
            events.append("primary-stop")

    async def fake_alias(_self) -> None:
        events.append("alias-start")
        try:
            await asyncio.Event().wait()
        finally:
            events.append("alias-stop")

    host = object.__new__(dashboard_server.DashboardServer)
    host._uploads_dir_injected = True
    host._uploads_dir = None
    host._cert_dir = dashboard_server.Path("certs")
    host._ip = "127.0.0.1"
    host.app = object()
    monkeypatch.setattr(dashboard_server, "_DEPS_OK", True)
    monkeypatch.setattr(dashboard_server, "_ensure_crypto_js", lambda: None)
    monkeypatch.setattr(dashboard_server, "_ensure_network_access", lambda _port: None)
    monkeypatch.setattr(host, "_ssl_enabled", lambda: True)
    monkeypatch.setattr(host, "_serve_alias", fake_alias.__get__(host))
    monkeypatch.setattr(dashboard_server.uvicorn, "Server", FakeServer)
    def config(*_args, **options):
        config_options.append(options)
        return object()

    monkeypatch.setattr(dashboard_server.uvicorn, "Config", config)

    asyncio.run(host.serve())

    assert events == ["primary-start", "alias-start", "primary-stop", "alias-stop"]
    assert config_options == [
        {
            "host": "0.0.0.0",
            "port": dashboard_server.PORT,
            "log_level": "warning",
            "lifespan": "off",
            "ssl_keyfile": str(host._cert_dir / dashboard_server.ONYX_KEY_NAME),
            "ssl_certfile": str(host._cert_dir / dashboard_server.ONYX_CERT_NAME),
        }
    ]


def test_dashboard_alias_disables_unused_lifespan_task(monkeypatch) -> None:
    config_options: list[dict[str, object]] = []

    class FakeServer:
        def __init__(self, _config) -> None:
            pass

        async def serve(self) -> None:
            return None

    host = object.__new__(dashboard_server.DashboardServer)
    host._cert_dir = dashboard_server.Path("certs")
    host._ip = "127.0.0.1"
    host.app = object()
    monkeypatch.setattr(dashboard_server, "_ensure_network_access", lambda _port: None)
    monkeypatch.setattr(dashboard_server.uvicorn, "Server", FakeServer)

    def config(*_args, **options):
        config_options.append(options)
        return object()

    monkeypatch.setattr(dashboard_server.uvicorn, "Config", config)

    asyncio.run(host._serve_alias())

    assert config_options[0]["lifespan"] == "off"
    assert config_options[0]["port"] == dashboard_server.PORT + 1
