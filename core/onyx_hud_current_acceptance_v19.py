"""Pinned current Onyx V19 HUD/QML integrity and semantic acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class CurrentHudAcceptanceV19Error(RuntimeError):
    """The current production HUD no longer matches its accepted closure."""


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V19-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "fdfac0662c467ae654ccb9b55079b4df26c7ad9fca0beb2d37823d05f8ab51b8"
)
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV9.qml")
CURRENT_QML_CHAIN: Final = (
    Path("qml/OnyxLiveShellV7.qml"),
    Path("qml/OnyxLiveShellV8.qml"),
    Path("qml/OnyxLiveShellV9.qml"),
    Path("qml/components/OnyxOrbEntityV7.qml"),
    Path("qml/components/OnyxOrbVoiceLayerV8.qml"),
)
CURRENT_RUNTIME_INPUTS: Final = (
    (
        Path("qml/OnyxLiveShellV7.qml"),
        "2af16b3990fc6a48ae95eb23c77cdb70fad25f8a83b762ecc2a58cf11ae6d5d8",
    ),
    (
        Path("qml/OnyxLiveShellV8.qml"),
        "20c60f4305da7adef80fe9e7e064ebd5c4ea554b8d17bc36a0b5558f9899a86a",
    ),
    (
        Path("qml/OnyxLiveShellV9.qml"),
        "61dbf4534378a4f27a46cba8c1ce73b6acb1d375b9466505d7258cdcc357b52b",
    ),
    (
        Path("qml/assets/onyx-orb-particle-v6.png"),
        "9582f4df844cbf03df45a97d6a7c351e9ad9dd291f097b53326f6d1597e44582",
    ),
    (
        Path("qml/components/OnyxOrbEntityV7.qml"),
        "52f5db82488729324e230e6132ec44b19c5f4e529e3c636c904d341736f70131",
    ),
    (
        Path("qml/components/OnyxOrbVoiceLayerV8.qml"),
        "585a56b343e72e41571755b05778b1f502573c48d41ac302c154b292bbd649a9",
    ),
)
ARTIFACT_ROOT_SHA256: Final = (
    "aa744179ab47421c58311ec859b47638a985158cb71df4953b47843f93ba2673"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_file(project: Path, relative: Path) -> Path:
    project = project.resolve()
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or str(pure) != relative.as_posix():
        raise CurrentHudAcceptanceV19Error("noncanonical current HUD path")
    path = project.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise CurrentHudAcceptanceV19Error(
            f"current HUD input is unavailable: {relative}"
        )
    try:
        path.resolve().relative_to(project)
    except ValueError as exc:
        raise CurrentHudAcceptanceV19Error(
            f"current HUD input escapes project: {relative}"
        ) from exc
    return path


def _strict_json(path: Path) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CurrentHudAcceptanceV19Error(
                    f"duplicate current HUD manifest key: {key}"
                )
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV19Error(
            "current HUD manifest is unreadable"
        ) from exc
    if type(payload) is not dict:
        raise CurrentHudAcceptanceV19Error("current HUD manifest must be an object")
    return payload


def _verify_semantics(project: Path) -> None:
    text = {
        relative: _canonical_file(project, relative).read_text(encoding="utf-8")
        for relative in CURRENT_QML_CHAIN
    }
    joined = "\n".join(text.values()).casefold()
    forbidden = (
        "jar" + "vis",
        "j." + "a.r.v.i.s",
        "sta" + "rk",
        "mark-" + "xlviii",
        "maax " + "assistant",
    )
    if any(token in joined for token in forbidden):
        raise CurrentHudAcceptanceV19Error("legacy branding detected in current HUD")

    v7 = text[Path("qml/OnyxLiveShellV7.qml")]
    v8 = text[Path("qml/OnyxLiveShellV8.qml")]
    v9 = text[Path("qml/OnyxLiveShellV9.qml")]
    entity = text[Path("qml/components/OnyxOrbEntityV7.qml")]
    voice = text[Path("qml/components/OnyxOrbVoiceLayerV8.qml")]

    required_v7 = (
        'objectName: "onyxLiveShellV7Root"',
        'text: "ONYX"',
        'text: "CYRYX LABS  /  COGNITIVE ENTITY"',
        "OnyxOrbEntityV7 {",
        'objectName: "liveCommandInputV7"',
        "requestAutonomy()",
        "requestRemote()",
        "requestCamera()",
        "requestSetup()",
    )
    required_v8 = (
        "OnyxLiveShellV7 {",
        'objectName: "onyxLiveShellV8Root"',
        "OnyxOrbVoiceLayerV8 {",
    )
    required_v9 = (
        "OnyxLiveShellV8 {",
        'objectName: "onyxLiveShellV9Root"',
        'objectName: "onyxSpeakingEqualizerV9"',
        "var bars = 48",
        "candidate.visible = false",
        "removed !== 1",
        'proj.state === "SPEAKING"',
        "proj.audioLevel",
        "Math.min(12",
        'objectName: "onyxAdvancedOperationsPillV9"',
        "requestAdvancedOperations()",
    )
    required_entity = (
        'objectName: "onyxOrbEntityV7Root"',
        'source: "../assets/onyx-orb-particle-v6.png"',
        "Math.min(12",
    )
    required_voice = (
        'objectName: "onyxOrbVoiceLayerV8"',
        'projection.state === "SPEAKING"',
        "projection.audioLevel",
        "var rays = 22",
        "Math.min(12",
        "running: voiceLayer.governedFps > 0 && voiceLayer.visible",
    )
    for name, source, required in (
        ("V7 shell", v7, required_v7),
        ("V8 shell", v8, required_v8),
        ("V9 shell", v9, required_v9),
        ("V7 entity", entity, required_entity),
        ("V8 voice layer", voice, required_voice),
    ):
        missing = tuple(anchor for anchor in required if anchor not in source)
        if missing:
            raise CurrentHudAcceptanceV19Error(
                f"current HUD semantic drift in {name}: {missing[0]}"
            )


def verify_current_hud_runtime_inputs(project: Path) -> str:
    """Verify exact current QML/image inputs at source, stage, or bundle root."""

    project = project.resolve()
    for relative, expected in CURRENT_RUNTIME_INPUTS:
        path = _canonical_file(project, relative)
        if _sha256(path) != expected:
            raise CurrentHudAcceptanceV19Error(
                f"current HUD input drift: {relative}"
            )

    material = "".join(
        f"{path.as_posix()}\0{digest}\n"
        for path, digest in sorted(
            CURRENT_RUNTIME_INPUTS, key=lambda item: item[0].as_posix()
        )
    ).encode()
    artifact_root = hashlib.sha256(material).hexdigest()
    if (
        artifact_root != ARTIFACT_ROOT_SHA256
    ):
        raise CurrentHudAcceptanceV19Error("current HUD artifact root drift")
    _verify_semantics(project)
    return artifact_root


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Verify exact bytes, manifest, and production semantics without discovery."""

    project = project.resolve()
    manifest_path = _canonical_file(project, MANIFEST_RELATIVE)
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise CurrentHudAcceptanceV19Error("current HUD manifest drift")
    manifest = _strict_json(manifest_path)
    if (
        manifest.get("schema") != "onyx.hud.current.v19.acceptance.v1"
        or manifest.get("candidate") != "onyx-hud-v9-current-pinned-001"
        or manifest.get("decision") != "accepted"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("runtime_qml_chain")
        != [path.as_posix() for path in CURRENT_QML_CHAIN]
    ):
        raise CurrentHudAcceptanceV19Error("current HUD manifest contract drift")

    records = manifest.get("runtime_inputs")
    expected_records = [
        {"path": path.as_posix(), "sha256": digest}
        for path, digest in CURRENT_RUNTIME_INPUTS
    ]
    if records != expected_records:
        raise CurrentHudAcceptanceV19Error("current HUD input membership drift")
    artifact_root = verify_current_hud_runtime_inputs(project)
    if manifest.get("artifact_root_sha256") != artifact_root:
        raise CurrentHudAcceptanceV19Error("current HUD manifest root drift")

    semantics = manifest.get("semantics")
    if type(semantics) is not dict or semantics != {
        "brand": "Onyx by Cyryx Labs",
        "legacy_external_branding_absent": True,
        "orb_internal_voice_rays": 22,
        "speaking_equalizer_bars": 48,
        "governed_max_fps": 12,
        "decorative_keel_arcs_visible": False,
        "speaking_state": "SPEAKING",
        "audio_level_reactive": True,
        "advanced_operations_projection_owner_invoked": True,
        "advanced_operations_polling": False,
    }:
        raise CurrentHudAcceptanceV19Error("current HUD semantic manifest drift")
    historical = manifest.get("historical_acceptance")
    if type(historical) is not dict or historical.get("status") != (
        "superseded_immutable_evidence"
    ) or historical.get("superseded_test_authority") != (
        "tests/test_hud_orb_v8_c001_acceptance.py"
    ) or historical.get("successor_test_authority") != (
        "tests/test_onyx_hud_current_acceptance_v19.py"
    ):
        raise CurrentHudAcceptanceV19Error("historical HUD supersession drift")
    return {
        "candidate": manifest["candidate"],
        "current_root": CURRENT_ROOT.as_posix(),
        "qml_files": len(CURRENT_QML_CHAIN),
        "runtime_inputs": len(CURRENT_RUNTIME_INPUTS),
        "artifact_root_sha256": artifact_root,
        "rays": 22,
        "equalizer_bars": 48,
        "legacy_branding": 0,
        "arcs_visible": 0,
        "max_fps": 12,
    }


__all__ = [
    "ARTIFACT_ROOT_SHA256",
    "CURRENT_QML_CHAIN",
    "CURRENT_ROOT",
    "CURRENT_RUNTIME_INPUTS",
    "CurrentHudAcceptanceV19Error",
    "MANIFEST_RELATIVE",
    "MANIFEST_SHA256",
    "verify_current_hud_acceptance",
    "verify_current_hud_runtime_inputs",
]
