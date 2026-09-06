"""Final source acceptance for the Onyx V10 HUD and V24 activation.

V24 succeeds the immutable V23 record.  It binds the final activation bytes,
the only-current pytest selector and every explicit frozen-package declaration
needed to preserve HUD acceptance V20 through V24 without import discovery.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class CurrentHudAcceptanceV24Error(RuntimeError):
    """The final production HUD closure no longer matches V24."""


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V24-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V23-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "596b327705705866ceea11abe268702977840b22e77880bf6c633e9b24dd71e8"
)
PREDECESSOR_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v23.py"
)
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "97277751660fa24055b97acd561dbc4204f81848abd1f88201d8cc82ea4afb67"
)
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV10.qml")
CURRENT_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v24.py"
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
    (Path("core/onyx_live_activation_v24.py"), "a058c74fc9f80455b5f298d473775ece1f0ff805b774a9524a84d3de0493c82f"),
    (Path("core/installer_lifecycle_v1.py"), "17db2d1ed232e56b7f9168d3551324fe002134bfab79fec2b234acaee71b958a"),
    (Path("scripts/bootstrap_onyx.pyw"), "01229cb1aa633f1220daba4b40658ccf0e00b190706f66992665b10f3f9f2dc4"),
    (Path("scripts/bootstrap_onyx_live_v24.pyw"), "ff03df7cf39895998b54a524ebd43fb6ed9039be662c402c134de42011166817"),
    (Path("scripts/launch_onyx_live_v24.pyw"), "84ed7b15ee9590d5264521b1398dc7b27f603e4afb67d684dcd993ba1dbbf457"),
    (Path("ui.py"), "5076f0eab157df0c6498aa64fd51dee6fb2dd19aa8e2b364b8d6a07f609d2114"),
    (Path("main.py"), "e930fef288128707983cd7618cb9ea1c406c5034a3a1a1dcd0f8feb225158fb0"),
    (Path("scripts/build_release.py"), "32873d512c264d014f9e4e2d01585fbdc80c51dd4a9e16acb6193d43dd310d39"),
    (Path("scripts/package_hygiene.py"), "1f8ab8653b89cce78e1cbe3dcc43b3b62191ca1dcf3a205d4adc1d220fa79185"),
    (Path("packaging/onyx.spec"), "f2d6560a1d7870f5995de8bfbfbcdc9e05683d47bf0e17e282493a4214519aee"),
    (Path("tests/conftest.py"), "87afe7663dea28703415ac7b844f0cec042c6c4e6dfd4d80f1d0936c37dca1b1"),
    (Path("tests/test_pyside6_hud_collection_compat.py"), "82598abfe29aacda1bdb97845bf20bdde57ef40bb19328485571d405b6999e73"),
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
        raise CurrentHudAcceptanceV24Error("noncanonical current HUD path")
    path = project.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise CurrentHudAcceptanceV24Error(f"current HUD input is unavailable: {relative}")
    try:
        path.resolve().relative_to(project)
    except ValueError as exc:
        raise CurrentHudAcceptanceV24Error(f"current HUD input escapes project: {relative}") from exc
    return path


def _strict_json(path: Path) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CurrentHudAcceptanceV24Error(f"duplicate current HUD manifest key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV24Error("current HUD manifest is unreadable") from exc
    if type(payload) is not dict:
        raise CurrentHudAcceptanceV24Error("current HUD manifest must be an object")
    return payload


def _artifact_root(records: tuple[tuple[Path, str], ...]) -> str:
    material = "".join(
        f"{path.as_posix()}\0{digest}\n"
        for path, digest in sorted(records, key=lambda item: item[0].as_posix())
    ).encode()
    return hashlib.sha256(material).hexdigest()


ARTIFACT_ROOT_SHA256: Final = _artifact_root(CURRENT_RUNTIME_INPUTS)


def _verify_predecessor(project: Path) -> None:
    for relative, expected in (
        (PREDECESSOR_MANIFEST_RELATIVE, PREDECESSOR_MANIFEST_SHA256),
        (PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_ACCEPTANCE_SHA256),
    ):
        if _sha256(_canonical_file(project, relative)) != expected:
            raise CurrentHudAcceptanceV24Error(f"immutable V23 predecessor drift: {relative}")


def _verify_semantics(project: Path) -> None:
    texts = {
        relative: _canonical_file(project, relative).read_text(encoding="utf-8")
        for relative in (
            *CURRENT_QML_CHAIN,
            Path("ui.py"),
            Path("scripts/build_release.py"),
            Path("scripts/package_hygiene.py"),
            Path("packaging/onyx.spec"),
            Path("tests/conftest.py"),
            Path("tests/test_pyside6_hud_collection_compat.py"),
        )
    }
    joined = "\n".join(texts[path] for path in CURRENT_QML_CHAIN).casefold()
    forbidden = ("jar" + "vis", "j." + "a.r.v.i.s", "sta" + "rk", "mark-" + "xlviii", "maax " + "assistant")
    if any(token in joined for token in forbidden):
        raise CurrentHudAcceptanceV24Error("legacy branding detected in current HUD")
    anchors = (
        (Path("qml/OnyxLiveShellV10.qml"), 'objectName: "onyxLiveShellV10Root"'),
        (Path("qml/components/OnyxOrbVoiceLayerV8.qml"), 'projection.state === "SPEAKING"'),
        (Path("ui.py"), 'core.onyx_hud_current_acceptance_v24'),
        (Path("scripts/build_release.py"), 'core.onyx_hud_current_acceptance_v24'),
        (Path("scripts/package_hygiene.py"), "RUNTIME_HUD_ACCEPTANCE_MODULES"),
        (Path("scripts/package_hygiene.py"), "range(20, 25)"),
        (Path("packaging/onyx.spec"), '"core.onyx_hud_current_acceptance_v22"'),
        (Path("packaging/onyx.spec"), '"core.onyx_hud_current_acceptance_v24"'),
        (Path("packaging/onyx.spec"), "HUD_ACCEPTANCE_MANIFESTS"),
        (Path("tests/conftest.py"), '"test_onyx_hud_current_acceptance_v23.py"'),
        (Path("tests/test_pyside6_hud_collection_compat.py"), 'CURRENT_HUD = "tests/test_onyx_hud_current_acceptance_v24.py"'),
    )
    for relative, anchor in anchors:
        if anchor not in texts[relative]:
            raise CurrentHudAcceptanceV24Error(f"current HUD wiring drift: {relative}")


def verify_current_hud_runtime_inputs(project: Path) -> str:
    """Verify exact final HUD, activation, selector and package bytes."""
    project = project.resolve()
    for relative, expected in CURRENT_RUNTIME_INPUTS:
        if _sha256(_canonical_file(project, relative)) != expected:
            raise CurrentHudAcceptanceV24Error(f"current HUD input drift: {relative}")
    artifact_root = _artifact_root(CURRENT_RUNTIME_INPUTS)
    if artifact_root != ARTIFACT_ROOT_SHA256:
        raise CurrentHudAcceptanceV24Error("current HUD artifact root drift")
    _verify_predecessor(project)
    _verify_semantics(project)
    return artifact_root


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Verify the V24 manifest, immutable V23 predecessor and final closure."""
    project = project.resolve()
    manifest = _strict_json(_canonical_file(project, MANIFEST_RELATIVE))
    expected_predecessor = {
        "manifest_path": PREDECESSOR_MANIFEST_RELATIVE.as_posix(),
        "manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "acceptance_path": PREDECESSOR_ACCEPTANCE_RELATIVE.as_posix(),
        "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA256,
    }
    if (
        manifest.get("schema") != "onyx.hud.current.v24.acceptance.v1"
        or manifest.get("candidate") != "onyx-hud-v10-v37-final-source-pinned-006"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("runtime_qml_chain") != [path.as_posix() for path in CURRENT_QML_CHAIN]
        or manifest.get("predecessor") != expected_predecessor
    ):
        raise CurrentHudAcceptanceV24Error("current HUD manifest contract drift")
    expected_records = [
        {"path": path.as_posix(), "sha256": digest}
        for path, digest in CURRENT_RUNTIME_INPUTS
    ]
    if manifest.get("runtime_inputs") != expected_records:
        raise CurrentHudAcceptanceV24Error("current HUD input membership drift")
    artifact_root = verify_current_hud_runtime_inputs(project)
    if manifest.get("artifact_root_sha256") != artifact_root:
        raise CurrentHudAcceptanceV24Error("current HUD manifest root drift")
    semantics = manifest.get("semantics")
    if semantics != {
        "brand": "Onyx by Cyryx Labs",
        "legacy_external_branding_absent": True,
        "current_source_projection": "V37",
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
        "frozen_predecessor_discovery_explicit": True,
        "single_current_test_authority": True,
    }:
        raise CurrentHudAcceptanceV24Error("current HUD semantic manifest drift")
    historical = manifest.get("historical_acceptance")
    if historical != {
        "status": "superseded_immutable_evidence",
        "superseded_test_authority": "tests/test_onyx_hud_current_acceptance_v23.py",
        "successor_test_authority": "tests/test_onyx_hud_current_acceptance_v24.py",
    }:
        raise CurrentHudAcceptanceV24Error("historical HUD supersession drift")
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
    "ARTIFACT_ROOT_SHA256",
    "CURRENT_QML_CHAIN",
    "CURRENT_ROOT",
    "CURRENT_RUNTIME_INPUTS",
    "CurrentHudAcceptanceV24Error",
    "MANIFEST_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_SHA256",
    "PREDECESSOR_MANIFEST_RELATIVE",
    "PREDECESSOR_MANIFEST_SHA256",
    "verify_current_hud_acceptance",
    "verify_current_hud_runtime_inputs",
]
