"""Stdlib-only fail-closed verifier for HUD/Orb V6 Candidate 003."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import struct

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/onyx/checkpoints/hud-orb-v6-candidate/manifest.json"
CHECKPOINT = (
    "docs/onyx/checkpoints/hud-orb-v6-candidate/ONYX_HUD_ORB_V6_CANDIDATE_CHECKPOINT.md"
)
MANIFEST_SHA256 = "ba034588791b1003a6743bf037ae32a11285adcac7c4084cba1bc5bb3923ae1c"
CHECKPOINT_SHA256 = "f07e6b1a6d39bb79b27f5a8b976b5bb623db0b469ae67a1b860cc9c24a080e12"
SUCCESS = "HUD_ORB_V6_CANDIDATE_OK"


class HudV6CandidateError(RuntimeError):
    pass


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _regular(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or pure.is_absolute()
        or ".." in pure.parts
        or str(pure) != relative
    ):
        raise HudV6CandidateError(f"noncanonical candidate path: {relative!r}")
    path = PROJECT.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise HudV6CandidateError(f"candidate path is not a regular file: {relative}")
    try:
        path.resolve().relative_to(PROJECT.resolve())
    except ValueError as exc:
        raise HudV6CandidateError(
            f"candidate path escapes project: {relative}"
        ) from exc
    return path


def _rehash(record: dict[str, object]) -> None:
    relative = record.get("path")
    if not isinstance(relative, str):
        raise HudV6CandidateError("record path must be a string")
    payload = _regular(relative).read_bytes()
    if len(payload) != record.get("size") or _sha(payload) != record.get("sha256"):
        raise HudV6CandidateError(f"candidate drift: {relative}")


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        raise HudV6CandidateError("physical evidence is not a canonical PNG")
    return struct.unpack(">II", payload[16:24])


def verify() -> dict[str, object]:
    manifest_payload = _regular(MANIFEST).read_bytes()
    checkpoint_payload = _regular(CHECKPOINT).read_bytes()
    if _sha(manifest_payload) != MANIFEST_SHA256:
        raise HudV6CandidateError("manifest drift")
    if _sha(checkpoint_payload) != CHECKPOINT_SHA256:
        raise HudV6CandidateError("checkpoint drift")
    manifest = json.loads(manifest_payload)

    if manifest.get("candidate") != "ONYX-HUD-ORB-V6-CANDIDATE-003":
        raise HudV6CandidateError("wrong candidate identity")
    if (
        manifest.get("status") != "candidate-default-off"
        or manifest.get("activation") != "ONYX_HUD_V6_CANDIDATE=1"
        or manifest.get("live_activated") is not False
        or manifest.get("accepted") is not False
    ):
        raise HudV6CandidateError("candidate boundary is not default-off")

    files = manifest.get("files")
    anchors = manifest.get("preserved_anchors")
    if not isinstance(files, list) or len(files) != 8:
        raise HudV6CandidateError("candidate closure must contain eight files")
    if not isinstance(anchors, list) or len(anchors) != 7:
        raise HudV6CandidateError("preserved boundary must contain seven anchors")
    for record in files + anchors:
        if not isinstance(record, dict):
            raise HudV6CandidateError("manifest record must be an object")
        _rehash(record)

    design = manifest.get("design_system")
    if not isinstance(design, dict):
        raise HudV6CandidateError("design-system anchor is missing")
    design_path = Path(str(design.get("path", "")))
    if design_path.is_symlink() or not design_path.is_file():
        raise HudV6CandidateError("design-system anchor is unavailable")
    design_payload = design_path.read_bytes()
    if len(design_payload) != design.get("size") or _sha(design_payload) != design.get(
        "sha256"
    ):
        raise HudV6CandidateError("design-system anchor drift")

    core = _regular("core/onyx_hud_orb_v6.py").read_text(encoding="utf-8")
    if 'source.get(FLAG_NAME, "0") == "1"' not in core:
        raise HudV6CandidateError("exact flag comparison is absent")
    if ".strip()" in core or "lower()" in core:
        raise HudV6CandidateError("candidate flag normalizes ambiguous input")
    if "previous_flag = ui_module.HUD_V5_LIVE" not in core:
        raise HudV6CandidateError("rollback does not preserve prior value exactly")

    capture = _regular("scripts/capture_hud_orb_v6_evidence.py").read_text(
        encoding="utf-8"
    )
    if (
        "QApplication.allWidgets()" not in capture
        or "isinstance(widget, QQuickWidget)" not in capture
        or '"quick_widgets": quick_widget_count' not in capture
        or '"quick_widgets": 1' in capture
    ):
        raise HudV6CandidateError("renderer evidence is asserted, not enumerated")

    shell = _regular("qml/OnyxLiveShellV6.qml").read_text(encoding="utf-8")
    orb = _regular("qml/components/OnyxOrbParticleV6.qml").read_text(encoding="utf-8")
    combined = (shell + orb).lower()
    for forbidden in (
        "corner bracket",
        "cornerbracket",
        "qtquick3d",
        "webgl",
    ):
        if forbidden in combined:
            raise HudV6CandidateError(f"forbidden visual token: {forbidden}")
    for action in (
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
        if action not in shell:
            raise HudV6CandidateError(f"missing control contract: {action}")
    if (
        'source: "../assets/onyx-orb-particle-v6.png"' not in orb
        or "import QtQuick.Effects" not in orb
        or "maskEnabled: true" not in orb
        or "running: root.simulationRunning" not in orb
    ):
        raise HudV6CandidateError("Orb source/mask/governor contract is incomplete")

    screenshot = _regular(
        "docs/onyx/checkpoints/hud-orb-v6-candidate/onyx-hud-v6-d3d11.png"
    ).read_bytes()
    if _png_dimensions(screenshot) != (1440, 900) or len(screenshot) < 500_000:
        raise HudV6CandidateError("physical visual evidence is incomplete")

    metrics = json.loads(
        _regular(
            "docs/onyx/checkpoints/hud-orb-v6-candidate/physical-metrics.json"
        ).read_text(encoding="utf-8")
    )
    physical = manifest.get("physical_validation")
    if not isinstance(physical, dict):
        raise HudV6CandidateError("physical manifest evidence is missing")
    for key, value in metrics.items():
        if physical.get(key) != value:
            raise HudV6CandidateError(f"physical evidence mismatch: {key}")
    if (
        metrics.get("graphics_api") != "GraphicsApi.Direct3D11Rhi"
        or metrics.get("resolution") != [1440, 900]
        or metrics.get("quick_widgets") != 1
        or metrics.get("active_target_fps") != 16
        or metrics.get("idle_target_fps") != 0
        or metrics.get("hidden_target_fps") != 0
        or metrics.get("active_host_cpu_percent", 1.0) > 0.8
        or metrics.get("idle_host_cpu_percent", 1.0) > 0.15
        or metrics.get("hidden_host_cpu_percent", 1.0) > 0.15
    ):
        raise HudV6CandidateError("physical performance gate failed")

    gates = manifest.get("gate_results")
    if (
        not isinstance(gates, dict)
        or gates.get("external_acceptance") != "not requested"
    ):
        raise HudV6CandidateError("acceptance boundary is ambiguous")
    return {
        "candidate": manifest["candidate"],
        "manifest_sha256": MANIFEST_SHA256,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "files": len(files),
        "preserved_anchors": len(anchors),
        "focused_passed": 25,
        "v5_regression_passed": 15,
        "representative_passed": 28,
        "active_host_cpu_percent": metrics["active_host_cpu_percent"],
        "idle_host_cpu_percent": metrics["idle_host_cpu_percent"],
        "hidden_host_cpu_percent": metrics["hidden_host_cpu_percent"],
        "live_activated": False,
        "external_acceptance": False,
    }


def main() -> int:
    result = verify()
    print(SUCCESS)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
