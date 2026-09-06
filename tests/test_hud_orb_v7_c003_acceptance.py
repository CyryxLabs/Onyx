from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

import ui
from core.onyx_hud_orb_v6 import install_candidate as install_v6
from core.onyx_hud_orb_v6 import uninstall_candidate as uninstall_v6
from core.onyx_hud_orb_v7 import install_candidate as install_v7
from core.onyx_hud_orb_v7 import uninstall_candidate as uninstall_v7


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "docs/onyx/checkpoints/hud-orb-v7-candidate"
MANIFEST = CHECKPOINT / "manifest.json"
EXPECTED_MANIFEST = "38f77492b6b72eeb8bff8c1bddbe129081bbe79e67b7f8679054d86dff781f03"
EXPECTED_ROOT = "5e0f16fcbf6885ed20b3bf3967a2af24b1d8dc4d174c0fdb7b0f5b78855aafe4"
EXPECTED_SCREENSHOT = "ac05686b74829c59f404da455184e13bc073ce426ad882b4ddef8b12fe873399"
UNTOUCHED = {
    "core/onyx_live_activation_v9.py": (
        "deb26314ef3871cb12fc8e3cee936f88e385122fad242c830580421ccb22a9d2"
    ),
    "core/onyx_live_activation_v10.py": (
        "a644ca196d918865a217d1b07987f314c6a8fe4828cb970292049737fa1de09d"
    ),
    "scripts/launch_onyx_live_v9.pyw": (
        "b06189d5a50ec2b310b8990432d56cf4c5a30b8db9aae83630d579fa945b82aa"
    ),
    "scripts/launch_onyx_live_v9_active.cmd": (
        "08a12c0cb851351a397ad28dfb82336130e4f35a187226ed38a5c96727478552"
    ),
    "scripts/launch_onyx_live_v10.pyw": (
        "b47b039f6c1a6215bcbcda5dea1964260d83cdedaf5210bfd498061446fec0b9"
    ),
    "scripts/launch_onyx_live_v10_active.cmd": (
        "a699f6a3f6b8bcca2d8e871fdefecd402d26a65e57f5650928487d52268fec03"
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_p0_exact_c003_and_prior_candidates_never_live() -> None:
    data = candidate()
    checkpoint = (CHECKPOINT / "HUD_ORB_V7_CHECKPOINT.md").read_text(encoding="utf-8")
    assert data["candidate"] == "hud-orb-v7-cinematic-candidate-003"
    assert data["status"] == "candidate-default-off-e6-pending"
    assert "candidate-002-owner-superseded-never-live" in data["supersedes"]
    assert "Candidate 001" in checkpoint
    assert "Candidate 002" in checkpoint and "never live" in checkpoint
    assert data["default_off"] is True and data["live_activated"] is False


def test_p0_no_external_arc_or_structural_ring() -> None:
    shell = (ROOT / "qml/OnyxLiveShellV7.qml").read_text(encoding="utf-8")
    entity = (ROOT / "qml/components/OnyxOrbEntityV7.qml").read_text(encoding="utf-8")
    above_keel, keel = shell.split("id: keel", maxsplit=1)
    assert "c.arc(" not in above_keel
    assert "c.ellipse(" not in above_keel
    assert "quadraticCurveTo" not in above_keel
    assert keel.count("quadraticCurveTo") == 3
    assert "c.arc(" not in entity and "c.ellipse(" not in entity
    assert "border.width" not in entity
    assert "maskEnabled: true" in entity


def test_p1_all_projection_actions_and_accessibility_survive() -> None:
    shell = (ROOT / "qml/OnyxLiveShellV7.qml").read_text(encoding="utf-8")
    for field in (
        "ownerName",
        "stateLabel",
        "stateDetail",
        "metricsSummary",
        "contentTitle",
        "contentText",
        "transcriptTitle",
        "transcriptText",
        "logText",
    ):
        assert f"uiProjection.{field}" in shell
    for action in (
        "submitCommand(",
        "acceptDroppedFile(",
        "requestFile()",
        "requestInterrupt()",
        "requestMuteToggle()",
        "requestAutonomy()",
        "requestRemote()",
        "requestCamera()",
        "requestSetup()",
        "requestFullscreen()",
        "requestClose()",
        "requestHistory()",
        "requestPermissions()",
    ):
        assert action in shell
    assert "Accessible.role: Accessible.EditableText" in shell
    assert shell.count("Accessible.role: Accessible.Button") == 1
    assert "readonly property bool compact:" in shell


def test_p1_real_v6_authentication_and_drift_safe_rollback_are_present() -> None:
    source = (ROOT / "core/onyx_hud_orb_v7.py").read_text(encoding="utf-8")
    for contract in (
        "V6_MODULE_SHA256",
        "V6_MANIFEST_SHA256",
        "_accepted_v6_host",
        "_InstallationRecordV7",
        "@dataclass(frozen=True, slots=True)",
        "_ACTIVE_INSTALLATIONS",
        "HUD V7 installation drift denied",
        "HUD V7 rollback authentication failed",
    ):
        assert contract in source
    assert 'source.get(FLAG_NAME, "0") == "1"' in source
    assert "installation[" not in source.split("def uninstall_candidate", 1)[1]


def test_p2_physical_capture_and_performance_are_within_gate() -> None:
    screenshot = CHECKPOINT / "hud-orb-v7-c003-1440x900.png"
    metrics = json.loads(
        (CHECKPOINT / "hud-orb-v7-c003.metrics.json").read_text(encoding="utf-8")
    )
    data = screenshot.read_bytes()
    assert digest(screenshot) == EXPECTED_SCREENSHOT
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (1440, 900)
    assert metrics["graphics_api"] == "GraphicsApi.Direct3D11Rhi"
    assert metrics["quick_widgets"] == 1
    assert metrics["active_host_cpu_percent"] <= 0.8
    assert metrics["idle_host_cpu_percent"] <= 0.15
    assert metrics["hidden_host_cpu_percent"] <= 0.15
    assert (
        metrics["active_target_fps"],
        metrics["idle_target_fps"],
        metrics["hidden_target_fps"],
    ) == (16, 0, 0)


def test_p2_cyryx_tokens_and_renderer_boundary() -> None:
    combined = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "qml/OnyxLiveShellV7.qml",
            "qml/components/OnyxOrbEntityV7.qml",
        )
    ).lower()
    for token in (
        "#050607",
        "#0a0d0f",
        "#11161a",
        "#1b2227",
        "#8c949e",
        "#c7c9cc",
        "#0f6b68",
        "#19c7c0",
    ):
        assert token in combined
    for forbidden in ("qtquick3d", "webgl"):
        assert forbidden not in combined
    assert "math.min(12" in combined
    assert "entity.governedfps > 0 && entity.visible" in combined


def test_p3_candidate_hash_root_and_tamper_detection() -> None:
    data = candidate()
    assert digest(MANIFEST) == EXPECTED_MANIFEST
    rows = sorted(data["artifacts"], key=lambda item: item["path"])
    for item in rows:
        assert digest(ROOT / item["path"]) == item["sha256"]
    material = "".join(f"{item['path']}\0{item['sha256']}\n" for item in rows).encode()
    assert hashlib.sha256(material).hexdigest() == EXPECTED_ROOT
    tampered = material.replace(EXPECTED_SCREENSHOT.encode(), b"0" * 64)
    assert hashlib.sha256(tampered).hexdigest() != EXPECTED_ROOT


def test_p3_v9_v10_and_shortcuts_match_authenticated_pyside_predecessors() -> None:
    for relative, expected in UNTOUCHED.items():
        assert digest(ROOT / relative) == expected


def test_p2_qt_compact_load_actions_and_single_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv("ONYX_HUD_V7_LIVE", "1")
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    assert install_v6(ui) and install_v7(ui)
    window = ui.MainWindow("")
    window.resize(800, 600)
    window.show()
    for _ in range(10):
        app.processEvents()
    try:
        root = window._v5_host._quick.rootObject()
        assert root.objectName() == "onyxLiveShellV7Root"
        assert root.property("compact") is True
        command = root.findChild(QQuickItem, "liveCommandInputV7")
        assert command is not None and command.isVisible() and command.isEnabled()
        widgets = window.findChildren(QQuickWidget)
        assert widgets == [window._v5_host._quick]
    finally:
        window.close()
        window.deleteLater()
        for _ in range(5):
            app.processEvents()
        assert uninstall_v7(ui)
        assert uninstall_v6(ui)
