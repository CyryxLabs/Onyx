"""Verify the frozen default-off HUD/Orb V7 visual candidate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "docs/onyx/checkpoints/hud-orb-v7-candidate"
MANIFEST = CHECKPOINT / "manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, object]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "onyx.hud-orb.v7.candidate"
    assert data["candidate"] == "hud-orb-v7-cinematic-candidate-003"
    assert "candidate-002-owner-superseded-never-live" in data["supersedes"]
    assert data["flag"] == "ONYX_HUD_V7_LIVE=1"
    assert data["default_off"] is True and data["live_activated"] is False
    assert data["quick_widgets"] == 1
    assert data["rollback"] == "exact-installed-hud-v6"
    assert data["performance"] == {
        "active_cpu_max_percent": 0.8,
        "idle_cpu_max_percent": 0.15,
        "hidden_cpu_max_percent": 0.15,
        "projection_target_fps_max": 16,
        "visual_timer_fps_max": 12,
        "idle_hidden_target_fps": 0,
    }
    rows = sorted(data["artifacts"], key=lambda item: item["path"])
    assert len(rows) == 10
    for item in rows:
        assert digest(ROOT / item["path"]) == item["sha256"]
    for path, expected in data["frozen_anchors"].items():
        assert digest(ROOT / path) == expected
    material = "".join(f"{item['path']}\0{item['sha256']}\n" for item in rows).encode()
    root = hashlib.sha256(material).hexdigest()
    assert root == data["artifact_root_sha256"]
    metrics = json.loads((CHECKPOINT / "hud-orb-v7-c003.metrics.json").read_text())
    assert metrics["active_host_cpu_percent"] <= 0.8
    assert metrics["idle_host_cpu_percent"] <= 0.15
    assert metrics["hidden_host_cpu_percent"] <= 0.15
    assert metrics["active_target_fps"] <= 16
    assert metrics["idle_target_fps"] == metrics["hidden_target_fps"] == 0
    assert metrics["quick_widgets"] == 1
    assert metrics["root_object"] == "onyxLiveShellV7Root"
    assert data["verification"] == {
        "focused": "19 passed",
        "physical_capture": "1440x900-d3d11",
        "visual_qa": "c003-approved-no-external-orbit-tracks",
        "external_e6": "pending",
    }
    shell = (ROOT / "qml/OnyxLiveShellV7.qml").read_text(encoding="utf-8")
    entity = (ROOT / "qml/components/OnyxOrbEntityV7.qml").read_text(encoding="utf-8")
    assert "c.arc(" not in shell.split("id: keel", maxsplit=1)[0]
    assert "c.ellipse(" not in shell.split("id: keel", maxsplit=1)[0]
    assert "quadraticCurveTo" not in shell.split("id: keel", maxsplit=1)[0]
    assert "c.arc(" not in entity and "c.ellipse(" not in entity
    assert "border.width" not in entity
    core = (ROOT / "core/onyx_hud_orb_v7.py").read_text(encoding="utf-8")
    assert "_InstallationRecordV7" in core
    assert "V6_MODULE_SHA256" in core and "V6_MANIFEST_SHA256" in core
    assert "onyx_live_activation_v9" not in core
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
            ".pytest-hud-v7-verify",
            "tests/test_onyx_hud_orb_v7_candidate.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0 and "19 passed" in result.stdout
    return {
        "artifacts": len(rows),
        "root": root,
        "focused": 19,
        "active_cpu": metrics["active_host_cpu_percent"],
        "idle_cpu": metrics["idle_host_cpu_percent"],
        "hidden_cpu": metrics["hidden_host_cpu_percent"],
        "live": False,
    }


if __name__ == "__main__":
    print("HUD_ORB_V7_CANDIDATE_OK", json.dumps(verify(), sort_keys=True))
