"""Pinned current Onyx V23 HUD, lifecycle and package-selection acceptance.

V23 succeeds the immutable V22 record.  It keeps the accepted V10 QML shell
and closes the previously implicit Python projection, stable V24 activation,
resident-window lifecycle and package-selection inputs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class CurrentHudAcceptanceV23Error(RuntimeError):
    """The current production HUD closure no longer matches V23."""


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V23-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V22-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "2f1942d2e551e4c3c162a0affa97148ff99390f69e8ac290f2ac08a7881d70db"
)
PREDECESSOR_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v22.py"
)
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "46790dd3ea3ad73814f9fd8bfd342e0bbd17363dda1813d4a8e6af000695d5be"
)
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV10.qml")
CURRENT_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v23.py"
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
    (Path("qml/OnyxLiveShellV7.qml"), "2af16b3990fc6a48ae95eb23c77cdb70fad25f8a83b762ecc2a58cf11ae6d5d8"),
    (Path("qml/OnyxLiveShellV8.qml"), "20c60f4305da7adef80fe9e7e064ebd5c4ea554b8d17bc36a0b5558f9899a86a"),
    (Path("qml/OnyxLiveShellV9.qml"), "61dbf4534378a4f27a46cba8c1ce73b6acb1d375b9466505d7258cdcc357b52b"),
    (Path("qml/OnyxLiveShellV10.qml"), "daa6c7019db1360bd333aa886a5c51250496438f2413f386bbd507a62f3f9f9b"),
    (Path("qml/assets/onyx-orb-particle-v6.png"), "9582f4df844cbf03df45a97d6a7c351e9ad9dd291f097b53326f6d1597e44582"),
    (Path("qml/components/OnyxOrbEntityV7.qml"), "52f5db82488729324e230e6132ec44b19c5f4e529e3c636c904d341736f70131"),
    (Path("qml/components/OnyxOrbVoiceLayerV8.qml"), "585a56b343e72e41571755b05778b1f502573c48d41ac302c154b292bbd649a9"),
    (Path("core/onyx_hud_orb_v10.py"), "644bc48b95de594b460a03598eb8a3303d5260f666cc8d884591b8e28a7f4784"),
    (Path("core/ui_projection_v3.py"), "ecd7676424ed3cc15793c127cdb4d1700e1786faa2c51a917f6b8fc36504e4d8"),
    (Path("core/render_governor_v3.py"), "ee1f2145eb90e930e1663287bc0e71ff6f0809b9b4bce18e445c2f47e80d1de8"),
    (Path("core/onyx_live_activation_v24.py"), "c2e9a3232a361d8c44b5a920022694bf836f5c90f07faaf5bf26c3bc34df8395"),
    (Path("core/installer_lifecycle_v1.py"), "17db2d1ed232e56b7f9168d3551324fe002134bfab79fec2b234acaee71b958a"),
    (Path("scripts/bootstrap_onyx.pyw"), "01229cb1aa633f1220daba4b40658ccf0e00b190706f66992665b10f3f9f2dc4"),
    (Path("scripts/bootstrap_onyx_live_v24.pyw"), "ff03df7cf39895998b54a524ebd43fb6ed9039be662c402c134de42011166817"),
    (Path("scripts/launch_onyx_live_v24.pyw"), "84ed7b15ee9590d5264521b1398dc7b27f603e4afb67d684dcd993ba1dbbf457"),
    (Path("ui.py"), "ead36c094afa8bbdbcc5045ef8a0ebea7a8e91741bd59256d81287ce0d9f1917"),
    (Path("main.py"), "e930fef288128707983cd7618cb9ea1c406c5034a3a1a1dcd0f8feb225158fb0"),
    (Path("scripts/build_release.py"), "c44a5d8217fea09a192a462f203f40e940b3aa8c05874fe0bdefd7740a54e66f"),
    (Path("scripts/package_hygiene.py"), "cacf5d7a6ecf53049db70be88422e275b11628328fbecba5595e4ce52997daa6"),
    (Path("packaging/onyx.spec"), "32347fdfbfa0e4df30701efa689c03ccac5cb7f9b8c042c633a53747f694f118"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


CURRENT_RUNTIME_INPUTS: Final = (
    *_PINNED_RUNTIME_INPUTS,
    (CURRENT_ACCEPTANCE_RELATIVE, _sha256(Path(__file__).resolve())),
)


def _canonical_file(project: Path, relative: Path) -> Path:
    project = project.resolve()
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or str(pure) != relative.as_posix():
        raise CurrentHudAcceptanceV23Error("noncanonical current HUD path")
    path = project.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise CurrentHudAcceptanceV23Error(f"current HUD input is unavailable: {relative}")
    try:
        path.resolve().relative_to(project)
    except ValueError as exc:
        raise CurrentHudAcceptanceV23Error(f"current HUD input escapes project: {relative}") from exc
    return path


def _strict_json(path: Path) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CurrentHudAcceptanceV23Error(f"duplicate current HUD manifest key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV23Error("current HUD manifest is unreadable") from exc
    if type(payload) is not dict:
        raise CurrentHudAcceptanceV23Error("current HUD manifest must be an object")
    return payload


def _artifact_root(records: tuple[tuple[Path, str], ...]) -> str:
    material = "".join(
        f"{path.as_posix()}\0{digest}\n"
        for path, digest in sorted(records, key=lambda item: item[0].as_posix())
    ).encode()
    return hashlib.sha256(material).hexdigest()


ARTIFACT_ROOT_SHA256: Final = _artifact_root(CURRENT_RUNTIME_INPUTS)


def _verify_predecessor(project: Path) -> None:
    predecessor = (
        (PREDECESSOR_MANIFEST_RELATIVE, PREDECESSOR_MANIFEST_SHA256),
        (PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_ACCEPTANCE_SHA256),
    )
    for relative, expected in predecessor:
        if _sha256(_canonical_file(project, relative)) != expected:
            raise CurrentHudAcceptanceV23Error(f"immutable V22 predecessor drift: {relative}")


def _verify_semantics(project: Path) -> None:
    sources = {
        relative: _canonical_file(project, relative).read_text(encoding="utf-8")
        for relative in CURRENT_QML_CHAIN
    }
    joined = "\n".join(sources.values()).casefold()
    forbidden = ("jar" + "vis", "j." + "a.r.v.i.s", "sta" + "rk", "mark-" + "xlviii", "maax " + "assistant")
    if any(token in joined for token in forbidden):
        raise CurrentHudAcceptanceV23Error("legacy branding detected in current HUD")
    required = {
        Path("qml/OnyxLiveShellV7.qml"): ('objectName: "onyxLiveShellV7Root"', "OnyxOrbEntityV7 {", 'objectName: "liveCommandInputV7"'),
        Path("qml/OnyxLiveShellV8.qml"): ("OnyxLiveShellV7 {", 'objectName: "onyxLiveShellV8Root"', "OnyxOrbVoiceLayerV8 {"),
        Path("qml/OnyxLiveShellV9.qml"): ("OnyxLiveShellV8 {", 'objectName: "onyxLiveShellV9Root"', 'objectName: "onyxSpeakingEqualizerV9"', 'objectName: "onyxAdvancedOperationsPillV9"'),
        Path("qml/OnyxLiveShellV10.qml"): ("OnyxLiveShellV9 {", 'objectName: "onyxLiveShellV10Root"', 'objectName: "exitOnyxActionV10"', 'text: "EXIT ONYX"', "root.uiProjection.requestExit()"),
        Path("qml/components/OnyxOrbEntityV7.qml"): ('objectName: "onyxOrbEntityV7Root"', 'source: "../assets/onyx-orb-particle-v6.png"'),
        Path("qml/components/OnyxOrbVoiceLayerV8.qml"): ('objectName: "onyxOrbVoiceLayerV8"', 'projection.state === "SPEAKING"', "projection.audioLevel", "Math.min(12"),
    }
    for relative, anchors in required.items():
        missing = tuple(anchor for anchor in anchors if anchor not in sources[relative])
        if missing:
            raise CurrentHudAcceptanceV23Error(f"current HUD semantic drift in {relative.name}: {missing[0]}")

    texts = {
        relative: _canonical_file(project, relative).read_text(encoding="utf-8")
        for relative in (
            Path("ui.py"), Path("main.py"), Path("core/onyx_hud_orb_v10.py"),
            Path("core/installer_lifecycle_v1.py"),
            Path("core/ui_projection_v3.py"), Path("core/render_governor_v3.py"),
            Path("scripts/bootstrap_onyx.pyw"), Path("scripts/build_release.py"),
            Path("scripts/package_hygiene.py"), Path("packaging/onyx.spec"),
        )
    }
    anchors = (
        (Path("ui.py"), "core.onyx_hud_current_acceptance_v23"),
        (Path("scripts/bootstrap_onyx.pyw"), 'if sys.argv[1:] and sys.argv[1] == "--installer-shutdown":'),
        (Path("scripts/build_release.py"), '"Onyx/_internal/core/onyx_live_activation_v24.py"'),
        (Path("ui.py"), "def install_current_hud_v10()"),
        (Path("ui.py"), "if self._tray_available:"),
        (Path("ui.py"), "self.showMinimized()"),
        (Path("ui.py"), "if self._close_to_background and not self._exit_requested:"),
        (Path("ui.py"), "self.request_explicit_exit()"),
        (Path("main.py"), "current_hud_installed = install_current_hud_v10()"),
        (Path("main.py"), 'hud_root.objectName() != "onyxLiveShellV10Root"'),
        (Path("main.py"), "if hud.install_candidate(ui_module) is not True:"),
        (Path("main.py"), 'if "--package-smoke-test" in sys.argv:'),
        (Path("core/installer_lifecycle_v1.py"), "def installer_client_main("),
        (Path("core/installer_lifecycle_v1.py"), "def request_installer_shutdown("),
        (Path("core/onyx_hud_orb_v10.py"), 'ROOT_OBJECT: Final = "onyxLiveShellV10Root"'),
        (Path("core/onyx_hud_orb_v10.py"), "def install_current("),
        (Path("core/onyx_hud_orb_v10.py"), "def uninstall_candidate("),
        (Path("core/ui_projection_v3.py"), "class OnyxUIProjectionV3"),
        (Path("core/render_governor_v3.py"), "class RenderGovernorV3"),
        (Path("scripts/bootstrap_onyx.pyw"), 'bootstrap_onyx_live_v24.pyw"'),
        (Path("scripts/bootstrap_onyx.pyw"), "def _preflight_package_smoke()"),
        (Path("scripts/bootstrap_onyx.pyw"), "preflight_host(onyx_main, prepared)"),
        (Path("scripts/build_release.py"), "core.onyx_hud_current_acceptance_v23"),
        (Path("scripts/package_hygiene.py"), "VE-HUD-CURRENT-V23-E6-001.manifest.json"),
        (Path("packaging/onyx.spec"), '"core.onyx_hud_current_acceptance_v23"'),
    )
    for relative, anchor in anchors:
        if anchor not in texts[relative]:
            raise CurrentHudAcceptanceV23Error(f"current HUD wiring drift: {relative}")


def verify_current_hud_runtime_inputs(project: Path) -> str:
    """Verify exact current QML, bridge, lifecycle and package-selection bytes."""
    project = project.resolve()
    for relative, expected in CURRENT_RUNTIME_INPUTS:
        if _sha256(_canonical_file(project, relative)) != expected:
            raise CurrentHudAcceptanceV23Error(f"current HUD input drift: {relative}")
    artifact_root = _artifact_root(CURRENT_RUNTIME_INPUTS)
    if artifact_root != ARTIFACT_ROOT_SHA256:
        raise CurrentHudAcceptanceV23Error("current HUD artifact root drift")
    _verify_predecessor(project)
    _verify_semantics(project)
    return artifact_root


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Verify the V23 manifest, immutable V22 predecessor and current closure."""
    project = project.resolve()
    manifest = _strict_json(_canonical_file(project, MANIFEST_RELATIVE))
    if (
        manifest.get("schema") != "onyx.hud.current.v23.acceptance.v1"
        or manifest.get("candidate") != "onyx-hud-v10-v36-runtime-final-pinned-005"
        or manifest.get("decision") != "accepted"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("runtime_qml_chain") != [path.as_posix() for path in CURRENT_QML_CHAIN]
        or manifest.get("predecessor") != {
            "manifest_path": PREDECESSOR_MANIFEST_RELATIVE.as_posix(),
            "manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
            "acceptance_path": PREDECESSOR_ACCEPTANCE_RELATIVE.as_posix(),
            "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA256,
        }
    ):
        raise CurrentHudAcceptanceV23Error("current HUD manifest contract drift")
    expected_records = [
        {"path": path.as_posix(), "sha256": digest}
        for path, digest in CURRENT_RUNTIME_INPUTS
    ]
    if manifest.get("runtime_inputs") != expected_records:
        raise CurrentHudAcceptanceV23Error("current HUD input membership drift")
    artifact_root = verify_current_hud_runtime_inputs(project)
    if manifest.get("artifact_root_sha256") != artifact_root:
        raise CurrentHudAcceptanceV23Error("current HUD manifest root drift")
    if manifest.get("semantics") != {
        "brand": "Onyx by Cyryx Labs",
        "legacy_external_branding_absent": True,
        "current_source_projection": "V36",
        "current_hud_shell": "V10",
        "stable_activation": "V24",
        "orb_internal_voice_rays": 22,
        "speaking_equalizer_bars": 48,
        "governed_max_fps": 12,
        "decorative_keel_arcs_visible": False,
        "speaking_state": "SPEAKING",
        "audio_level_reactive": True,
        "explicit_exit_action_visible": True,
        "window_close_is_background_only": True,
        "no_tray_restore_path": "taskbar_minimize",
        "runtime_refusal_bypass": False,
        "package_hud_v10_offscreen_smoke": True,
    }:
        raise CurrentHudAcceptanceV23Error("current HUD semantic manifest drift")
    historical = manifest.get("historical_acceptance")
    if type(historical) is not dict or historical.get("status") != "superseded_immutable_evidence" or historical.get("superseded_test_authority") != "tests/test_onyx_hud_current_acceptance_v22.py" or historical.get("successor_test_authority") != "tests/test_onyx_hud_current_acceptance_v23.py":
        raise CurrentHudAcceptanceV23Error("historical HUD supersession drift")
    return {
        "candidate": manifest["candidate"],
        "current_root": CURRENT_ROOT.as_posix(),
        "qml_files": len(CURRENT_QML_CHAIN),
        "runtime_inputs": len(CURRENT_RUNTIME_INPUTS),
        "artifact_root_sha256": artifact_root,
        "predecessor_manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "rays": 22,
        "equalizer_bars": 48,
        "legacy_branding": 0,
        "arcs_visible": 0,
        "max_fps": 12,
        "stable_activation": "V24",
    }


__all__ = [
    "ARTIFACT_ROOT_SHA256", "CURRENT_QML_CHAIN", "CURRENT_ROOT",
    "CURRENT_RUNTIME_INPUTS", "CurrentHudAcceptanceV23Error",
    "MANIFEST_RELATIVE", "PREDECESSOR_ACCEPTANCE_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_SHA256", "PREDECESSOR_MANIFEST_RELATIVE",
    "PREDECESSOR_MANIFEST_SHA256", "verify_current_hud_acceptance",
    "verify_current_hud_runtime_inputs",
]
