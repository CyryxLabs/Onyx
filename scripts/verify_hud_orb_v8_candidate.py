"""Verify the frozen default-off HUD/Orb V8 voice-reactive candidate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "docs/onyx/checkpoints/hud-orb-v8-candidate"
MANIFEST = CHECKPOINT / "manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, object]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "onyx.hud-orb.v8.candidate"
    assert data["candidate"] == "hud-orb-v8-voice-reactive-candidate-001"
    assert data["supersedes"] == "hud-orb-v7-cinematic-candidate-003"
    assert data["flag"] == "ONYX_HUD_V8_LIVE=1"
    assert data["default_off"] is True and data["live_activated"] is False
    assert data["quick_widgets"] == 1
    assert data["rollback"] == "exact-installed-hud-v7"
    assert data["performance"] == {
        "speaking_cpu_max_percent": 0.8,
        "idle_cpu_max_percent": 0.15,
        "hidden_cpu_max_percent": 0.15,
        "projection_target_fps_max": 16,
        "voice_layer_fps_max": 12,
        "idle_hidden_voice_layer_fps": 0,
    }
    rows = sorted(data["artifacts"], key=lambda item: item["path"])
    assert len(rows) == 11
    for item in rows:
        assert digest(ROOT / item["path"]) == item["sha256"]
    for path, expected in data["frozen_anchors"].items():
        assert digest(ROOT / path) == expected
    material = "".join(
        f"{item['path']}\0{item['sha256']}\n" for item in rows
    ).encode()
    root = hashlib.sha256(material).hexdigest()
    assert root == data["artifact_root_sha256"]

    metrics = json.loads((CHECKPOINT / "hud-orb-v8.metrics.json").read_text())
    assert metrics["speaking_host_cpu_percent"] <= 0.8
    assert metrics["idle_host_cpu_percent"] <= 0.15
    assert metrics["hidden_host_cpu_percent"] <= 0.15
    assert metrics["speaking_projection_target_fps"] <= 16
    assert metrics["speaking_voice_layer_fps"] <= 12
    assert metrics["idle_voice_layer_fps"] == 0
    assert metrics["hidden_voice_layer_fps"] == 0
    assert metrics["idle_projection_target_fps"] == 0
    assert metrics["hidden_projection_target_fps"] == 0
    assert metrics["speaking_phase_b"] > metrics["speaking_phase_a"] > 0
    assert metrics["idle_phase_a"] == metrics["idle_phase_b"] == 0
    assert metrics["quick_widgets"] == 1
    assert metrics["root_object"] == "onyxLiveShellV8Root"
    assert metrics["renderer_mode"] == "qml-v8-voice-reactive"
    assert digest(CHECKPOINT / "hud-orb-v8-speaking-a-1440x900.png") != digest(
        CHECKPOINT / "hud-orb-v8-speaking-b-1440x900.png"
    )

    layer = (ROOT / "qml/components/OnyxOrbVoiceLayerV8.qml").read_text(
        encoding="utf-8"
    )
    shell = (ROOT / "qml/OnyxLiveShellV8.qml").read_text(encoding="utf-8")
    assert 'projection.state === "SPEAKING"' in layer
    assert "Math.min(12" in layer
    assert "running: voiceLayer.governedFps > 0 && voiceLayer.visible" in layer
    assert "c.clip()" in layer
    assert "for (var i = 0; i < 42; ++i)" in layer
    assert "OnyxLiveShellV7 {" in shell
    assert "OnyxOrbVoiceLayerV8 {" in shell

    core = (ROOT / "core/onyx_hud_orb_v8.py").read_text(encoding="utf-8")
    assert "_InstallationRecordV8" in core
    assert "hud_v7._ACTIVE_INSTALLATIONS" in core
    assert "V7_MODULE_SHA256" in core and "V7_MANIFEST_SHA256" in core
    assert "onyx_live_activation_v10" not in core
    assert "shortcut" not in core.lower()

    result = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            ".pytest-hud-v8-verify",
            "tests/test_onyx_hud_orb_v8_candidate.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0 and "7 passed" in result.stdout
    return {
        "artifacts": len(rows),
        "root": root,
        "focused": 7,
        "speaking_cpu": metrics["speaking_host_cpu_percent"],
        "idle_cpu": metrics["idle_host_cpu_percent"],
        "hidden_cpu": metrics["hidden_host_cpu_percent"],
        "live": False,
    }


if __name__ == "__main__":
    print("HUD_ORB_V8_CANDIDATE_OK", json.dumps(verify(), sort_keys=True))
