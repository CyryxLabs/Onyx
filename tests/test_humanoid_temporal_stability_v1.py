from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from scripts.verify_humanoid_temporal_stability_v1 import analyse_frames


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "qml/web/onyx-humanoid-three-v2.html"
QML = ROOT / "qml/components/OnyxHumanoidEntityV11.qml"


def _humanoid_frame(*, missing_upper_face: bool = False) -> Image.Image:
    image = Image.new("RGB", (1280, 820), "#050607")
    draw = ImageDraw.Draw(image)
    draw.ellipse((485, 45, 795, 560), fill="#355354")
    draw.rectangle((430, 430, 850, 650), fill="#28494a")
    if missing_upper_face:
        draw.rectangle((485, 45, 795, 305), fill="#050607")
    return image


def test_temporal_analyser_rejects_partial_face_loss() -> None:
    frames = [_humanoid_frame() for _ in range(11)]
    frames.insert(5, _humanoid_frame(missing_upper_face=True))

    result = analyse_frames(frames)

    assert result["stable"] is False
    assert result["collapse_indices"] == [5]


def test_temporal_analyser_accepts_continuous_humanoid() -> None:
    result = analyse_frames([_humanoid_frame() for _ in range(12)])

    assert result["stable"] is True
    assert result["collapse_indices"] == []


def test_three_renderer_owns_one_coalesced_animation_loop() -> None:
    source = HTML.read_text(encoding="utf-8")

    assert "preserveDrawingBuffer:true" in source
    assert "alpha:false" in source
    assert "function requestRender()" in source
    assert "requestAnimationFrame(now=>renderFrame" not in source
    assert source.count("renderer.render(scene,camera)") == 1
    assert source.count("requestAnimationFrame(animate)") == 2


def test_webgl_surface_is_opaque_and_context_resilient() -> None:
    html = HTML.read_text(encoding="utf-8")
    qml = QML.read_text(encoding="utf-8")

    assert "background:#050607" in html
    assert "renderer.setClearColor(0x050607, 1)" in html
    assert 'backgroundColor: "#050607"' in qml
    assert "webglcontextlost" in html
    assert "webglcontextrestored" in html
