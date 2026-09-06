from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None, reason="fastapi not installed"
)


ROOT = Path(__file__).resolve().parents[1]


def _server(tmp_path: Path):
    from dashboard.server import DashboardServer

    root = Path(__file__).resolve().parents[1]
    return DashboardServer(
        local_ip="127.0.0.1",
        cert_dir=tmp_path / "certs",
        uploads_dir=tmp_path / "uploads",
        static_dir=root / "dashboard" / "static",
        visual_dir=root / "qml" / "web",
    )


def test_current_gemini_config_keeps_system_instruction_in_payload() -> None:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    payloads = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "live_config_kwargs"
            for target in node.targets
        )
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "dict"
    ]
    assert payloads
    assert "system_instruction" in {
        keyword.arg for keyword in payloads[0].keywords
    }
    constructors = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "LiveConnectConfig"
    ]
    assert any(
        len(node.keywords) == 1
        and node.keywords[0].arg is None
        and isinstance(node.keywords[0].value, ast.Name)
        and node.keywords[0].value.id == "live_config_kwargs"
        for node in constructors
    )


def test_current_hud_bootstrap_selects_v17() -> None:
    source = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert "for version in range(6, 18)" in source
    assert 'RuntimeError("accepted HUD V16 installation refused")' in source


def test_mobile_dashboard_uses_authoritative_threejs_humanoid(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    page = TestClient(_server(tmp_path).app).get("/")

    assert page.status_code == 200
    assert 'src="/visual/onyx-humanoid-three-v5.html"' in page.text
    assert 'id="humanoid-frame"' in page.text
    assert "THREE.JS / HUMANOID ONLINE" in page.text
    assert "api.setState" in page.text
    assert "api.setAttention" in page.text
    assert "pointermove" in page.text
    assert "pointer-events: none" in page.text
    assert "stTxt.textContent = 'Connected'" in page.text
    assert "stTxt.textContent = 'Disconnected'" in page.text
    assert "<img" not in page.text.lower()
    assert "orb" not in page.text.lower()


def test_mobile_layout_preserves_desktop_information_hierarchy(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    page = TestClient(_server(tmp_path).app).get("/")
    body = page.text

    assert 'class="presence-grid"' in body
    assert 'class="context-panel owner-panel"' in body
    assert 'class="context-panel runtime-panel"' in body
    assert "@media (max-width: 680px)" in body
    assert "grid-column: 1 / -1" in body
    assert "minmax(292px, 1fr)" in body
    assert "min-width: 44px" in body
    assert "min-height: 44px" in body
    assert "env(safe-area-inset-bottom)" in body
    assert 'id="feed"' in body
    assert 'id="inp"' in body
    assert 'id="mic-btn"' in body
    assert 'id="file-inp"' in body


def test_visual_route_serves_only_frozen_humanoid_dependency_graph(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_server(tmp_path).app)
    expected = {
        "onyx-humanoid-three-v5.html": "text/html",
        "onyx-humanoid-three-v4.html": "text/html",
        "data/onyx-humanoid-pointcloud-v1.js": "text/javascript",
        "vendor/three/three.module.min.js": "text/javascript",
        "vendor/three/three.core.min.js": "text/javascript",
    }

    for asset, media_type in expected.items():
        response = client.get(f"/visual/{asset}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(media_type)
        assert response.content

    assert client.get("/visual/not-allowlisted.js").status_code == 404
    assert client.get("/visual/%2e%2e/main.py").status_code == 404


def test_visual_route_keeps_dashboard_security_headers(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    response = TestClient(_server(tmp_path).app).get(
        "/visual/onyx-humanoid-three-v5.html"
    )

    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
