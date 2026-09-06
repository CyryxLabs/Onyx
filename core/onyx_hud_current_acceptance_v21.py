"""Pinned current Onyx V21 HUD/QML and Python-wiring acceptance.

The immutable V7/V8/V9 shells remain historical inputs.  V10 is the only
current shell and adds the explicit owner exit surface without changing those
predecessors or the accepted V23 runtime activation boundary.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class CurrentHudAcceptanceV21Error(RuntimeError):
    """The current production HUD no longer matches its accepted closure."""


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V21-E6-001.manifest.json"
)
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV10.qml")
CURRENT_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v21.py"
)
CURRENT_QML_CHAIN: Final = (
    Path("qml/OnyxLiveShellV7.qml"),
    Path("qml/OnyxLiveShellV8.qml"),
    Path("qml/OnyxLiveShellV9.qml"),
    Path("qml/OnyxLiveShellV10.qml"),
    Path("qml/components/OnyxOrbEntityV7.qml"),
    Path("qml/components/OnyxOrbVoiceLayerV8.qml"),
)
_PINNED_RUNTIME_INPUTS: Final = (
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
        Path("qml/OnyxLiveShellV10.qml"),
        "daa6c7019db1360bd333aa886a5c51250496438f2413f386bbd507a62f3f9f9b",
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
    (
        Path("core/onyx_hud_orb_v10.py"),
        "644bc48b95de594b460a03598eb8a3303d5260f666cc8d884591b8e28a7f4784",
    ),
    (
        Path("ui.py"),
        "6d059f16a7d3c41b7b8d2aa7f901f9e7bad12ce2fa3773d14008062c0c0c41dc",
    ),
    (
        Path("main.py"),
        "92b4618cc149eb326c0404e947b797f0e36b17c3b8f4b4ebf4e0d8e1dec3d752",
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# The manifest binds this verifier's exact bytes.  Its own record is computed
# from the imported module rather than embedded here, avoiding a hash cycle.
CURRENT_RUNTIME_INPUTS: Final = (
    *_PINNED_RUNTIME_INPUTS,
    (CURRENT_ACCEPTANCE_RELATIVE, _sha256(Path(__file__).resolve())),
)


def _canonical_file(project: Path, relative: Path) -> Path:
    project = project.resolve()
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or str(pure) != relative.as_posix():
        raise CurrentHudAcceptanceV21Error("noncanonical current HUD path")
    path = project.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise CurrentHudAcceptanceV21Error(
            f"current HUD input is unavailable: {relative}"
        )
    try:
        path.resolve().relative_to(project)
    except ValueError as exc:
        raise CurrentHudAcceptanceV21Error(
            f"current HUD input escapes project: {relative}"
        ) from exc
    return path


def _strict_json(path: Path) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CurrentHudAcceptanceV21Error(
                    f"duplicate current HUD manifest key: {key}"
                )
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV21Error(
            "current HUD manifest is unreadable"
        ) from exc
    if type(payload) is not dict:
        raise CurrentHudAcceptanceV21Error("current HUD manifest must be an object")
    return payload


def _artifact_root(records: tuple[tuple[Path, str], ...]) -> str:
    material = "".join(
        f"{path.as_posix()}\0{digest}\n"
        for path, digest in sorted(records, key=lambda item: item[0].as_posix())
    ).encode()
    return hashlib.sha256(material).hexdigest()


ARTIFACT_ROOT_SHA256: Final = _artifact_root(CURRENT_RUNTIME_INPUTS)


def _verify_semantics(project: Path) -> None:
    sources = {
        relative: _canonical_file(project, relative).read_text(encoding="utf-8")
        for relative in CURRENT_QML_CHAIN
    }
    joined = "\n".join(sources.values()).casefold()
    forbidden = (
        "jar" + "vis",
        "j." + "a.r.v.i.s",
        "sta" + "rk",
        "mark-" + "xlviii",
        "maax " + "assistant",
    )
    if any(token in joined for token in forbidden):
        raise CurrentHudAcceptanceV21Error("legacy branding detected in current HUD")

    required = {
        Path("qml/OnyxLiveShellV7.qml"): (
            'objectName: "onyxLiveShellV7Root"',
            "OnyxOrbEntityV7 {",
            'objectName: "liveCommandInputV7"',
        ),
        Path("qml/OnyxLiveShellV8.qml"): (
            "OnyxLiveShellV7 {",
            'objectName: "onyxLiveShellV8Root"',
            "OnyxOrbVoiceLayerV8 {",
        ),
        Path("qml/OnyxLiveShellV9.qml"): (
            "OnyxLiveShellV8 {",
            'objectName: "onyxLiveShellV9Root"',
            'objectName: "onyxSpeakingEqualizerV9"',
            'objectName: "onyxAdvancedOperationsPillV9"',
        ),
        Path("qml/OnyxLiveShellV10.qml"): (
            "OnyxLiveShellV9 {",
            'objectName: "onyxLiveShellV10Root"',
            'objectName: "exitOnyxActionV10"',
            'text: "EXIT ONYX"',
            "root.uiProjection.requestExit()",
        ),
        Path("qml/components/OnyxOrbEntityV7.qml"): (
            'objectName: "onyxOrbEntityV7Root"',
            'source: "../assets/onyx-orb-particle-v6.png"',
        ),
        Path("qml/components/OnyxOrbVoiceLayerV8.qml"): (
            'objectName: "onyxOrbVoiceLayerV8"',
            'projection.state === "SPEAKING"',
            "projection.audioLevel",
            "Math.min(12",
        ),
    }
    for relative, anchors in required.items():
        missing = tuple(anchor for anchor in anchors if anchor not in sources[relative])
        if missing:
            raise CurrentHudAcceptanceV21Error(
                f"current HUD semantic drift in {relative.name}: {missing[0]}"
            )

    ui_source = _canonical_file(project, Path("ui.py")).read_text(encoding="utf-8")
    main_source = _canonical_file(project, Path("main.py")).read_text(encoding="utf-8")
    hud_source = _canonical_file(
        project, Path("core/onyx_hud_orb_v10.py")
    ).read_text(encoding="utf-8")
    wiring = (
        (ui_source, "def install_current_hud_v10()"),
        (ui_source, "def uninstall_current_hud_v10()"),
        (ui_source, "core.onyx_hud_current_acceptance_v21"),
        (ui_source, 'callback("hud-exit-action") is not False'),
        (ui_source, "self.request_explicit_exit()"),
        (main_source, "current_hud_installed = install_current_hud_v10()"),
        (main_source, "uninstall_current_hud_v10()"),
        (hud_source, 'ROOT_OBJECT: Final = "onyxLiveShellV10Root"'),
        (hud_source, "def install_current("),
        (hud_source, "def uninstall_candidate("),
    )
    if any(anchor not in source for source, anchor in wiring):
        raise CurrentHudAcceptanceV21Error("current HUD Python wiring drift")


def verify_current_hud_runtime_inputs(project: Path) -> str:
    """Verify exact current QML, image, loader, host and verifier bytes."""

    project = project.resolve()
    for relative, expected in CURRENT_RUNTIME_INPUTS:
        if _sha256(_canonical_file(project, relative)) != expected:
            raise CurrentHudAcceptanceV21Error(
                f"current HUD input drift: {relative}"
            )
    artifact_root = _artifact_root(CURRENT_RUNTIME_INPUTS)
    if artifact_root != ARTIFACT_ROOT_SHA256:
        raise CurrentHudAcceptanceV21Error("current HUD artifact root drift")
    _verify_semantics(project)
    return artifact_root


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Verify the immutable manifest, exact bytes and production semantics."""

    project = project.resolve()
    manifest = _strict_json(_canonical_file(project, MANIFEST_RELATIVE))
    if (
        manifest.get("schema") != "onyx.hud.current.v21.acceptance.v1"
        or manifest.get("candidate") != "onyx-hud-v10-exit-current-pinned-003"
        or manifest.get("decision") != "accepted"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("runtime_qml_chain")
        != [path.as_posix() for path in CURRENT_QML_CHAIN]
    ):
        raise CurrentHudAcceptanceV21Error("current HUD manifest contract drift")
    expected_records = [
        {"path": path.as_posix(), "sha256": digest}
        for path, digest in CURRENT_RUNTIME_INPUTS
    ]
    if manifest.get("runtime_inputs") != expected_records:
        raise CurrentHudAcceptanceV21Error("current HUD input membership drift")
    artifact_root = verify_current_hud_runtime_inputs(project)
    if manifest.get("artifact_root_sha256") != artifact_root:
        raise CurrentHudAcceptanceV21Error("current HUD manifest root drift")
    if manifest.get("semantics") != {
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
        "explicit_exit_action_visible": True,
        "window_close_is_background_only": True,
        "runtime_refusal_bypass": False,
        "pre_runtime_local_exit_only": True,
        "stable_activation": "V23",
    }:
        raise CurrentHudAcceptanceV21Error("current HUD semantic manifest drift")
    historical = manifest.get("historical_acceptance")
    if type(historical) is not dict or historical.get("status") != (
        "superseded_immutable_evidence"
    ) or historical.get("superseded_test_authority") != (
        "tests/test_onyx_hud_current_acceptance_v20.py"
    ) or historical.get("successor_test_authority") != (
        "tests/test_onyx_hud_current_acceptance_v21.py"
    ):
        raise CurrentHudAcceptanceV21Error("historical HUD supersession drift")
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
        "stable_activation": "V23",
    }


__all__ = [
    "ARTIFACT_ROOT_SHA256",
    "CURRENT_QML_CHAIN",
    "CURRENT_ROOT",
    "CURRENT_RUNTIME_INPUTS",
    "CurrentHudAcceptanceV21Error",
    "MANIFEST_RELATIVE",
    "verify_current_hud_acceptance",
    "verify_current_hud_runtime_inputs",
]
