from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "qml/components/OnyxOrbEntityV9.qml"
APPROVED = {
    "#050607",
    "#0A0D0F",
    "#11161A",
    "#1B2227",
    "#8C949E",
    "#C7C9CC",
    "#0F6B68",
    "#19C7C0",
}


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_liquid_metal_v9_uses_only_the_approved_visible_palette() -> None:
    colors = {value.upper() for value in re.findall(r"#[0-9A-Fa-f]{6}", _source())}
    assert colors
    assert colors <= APPROVED


def test_liquid_metal_v9_is_state_audio_and_reduced_motion_aware() -> None:
    source = _source()
    for token in (
        'objectName: "onyxOrbLiquidMetalV9Root"',
        'objectName: "liquidMetalSpecularFlowV9"',
        'operationalState === "SPEAKING"',
        'operationalState === "PROCESSING"',
        'operationalState === "THINKING"',
        "projection.reducedMotion",
        "projection.audioLevel",
    ):
        assert token in source


def test_liquid_metal_v9_has_bounded_governed_motion_without_randomness() -> None:
    source = _source()
    assert "Math.min(24, Math.max(1, projection.targetFps))" in source
    assert "Math.max(42, 1000 / entity.governedFps)" in source
    assert "running: entity.governedFps > 0 && entity.visible" in source
    assert "Math.random" not in source
    assert "WorkerScript" not in source
    assert "ShaderEffect" not in source
