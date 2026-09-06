"""Current HUD acceptance for the Onyx 1.1.10 engineering integration batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class CurrentHudAcceptanceV32Error(RuntimeError):
    """The V32 source closure or its immutable V31 predecessor drifted."""


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V32-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V31-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "c294b3fe766bcd33a51451c3b1ac01eeb59e6b948d7eccf230a564ced5e3dc92"
)
PREDECESSOR_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v31.py"
)
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "bc81427d6918403df94699864f8a5ca4c7be881cdf98c18b351c2d2afe35c405"
)
CURRENT_ACCEPTANCE_RELATIVE: Final = Path("core/onyx_hud_current_acceptance_v32.py")
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV11.qml")
CURRENT_RUNTIME_PATHS: Final = (
    Path("qml/OnyxLiveShellV11.qml"),
    Path("qml/OnyxLiveShellGuardedV1.qml"),
    Path("qml/components/OnyxOrbEntityV8.qml"),
    Path("core/onyx_hud_orb_v12.py"),
    Path("core/version.py"),
    Path("core/autostart_registration_v1.py"),
    Path("core/topic_monitor_v1.py"),
    Path("core/permission_broker.py"),
    Path("actions/computer_settings.py"),
    Path("actions/reminder.py"),
    Path("actions/file_controller.py"),
    Path("actions/desktop.py"),
    Path("actions/youtube_video.py"),
    Path("core/onyx_packaged_runtime_hud_contract_v1.py"),
    Path("core/onyx_packaged_runtime_hud_contract_v1.manifest.json"),
    Path("scripts/package_hygiene.py"),
    Path("scripts/build_release.py"),
    Path("scripts/generate_hud_v32_manifests.py"),
    Path("packaging/onyx.spec"),
    Path("main.py"),
    Path("ui.py"),
    Path("tests/test_autostart_registration_v1.py"),
    Path("tests/test_topic_monitor_v1.py"),
    Path("tests/test_regressions.py"),
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    CURRENT_ACCEPTANCE_RELATIVE,
    Path("tests/test_onyx_hud_current_acceptance_v32.py"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path) -> Path:
    root = root.resolve()
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative.as_posix():
        raise CurrentHudAcceptanceV32Error("noncanonical V32 source path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise CurrentHudAcceptanceV32Error(f"V32 source input unavailable: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise CurrentHudAcceptanceV32Error(
            f"V32 source input escapes root: {relative}"
        ) from exc
    if resolved != candidate.absolute():
        raise CurrentHudAcceptanceV32Error(f"V32 source input is linked: {relative}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise CurrentHudAcceptanceV32Error("duplicate V32 manifest key")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV32Error("V32 manifest unreadable") from exc
    if type(value) is not dict:
        raise CurrentHudAcceptanceV32Error("V32 manifest must be an object")
    return value


def _artifact_root(records: list[dict[str, str]]) -> str:
    payload = "".join(
        f"{entry['path']}\0{entry['sha256']}\n"
        for entry in sorted(records, key=lambda item: item["path"])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Authenticate the 1.1.10 integration over immutable HUD V31."""

    root = Path(project).resolve()
    manifest = _strict_json(_canonical_file(root, MANIFEST_RELATIVE))
    predecessor = {
        "manifest_path": PREDECESSOR_MANIFEST_RELATIVE.as_posix(),
        "manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "acceptance_path": PREDECESSOR_ACCEPTANCE_RELATIVE.as_posix(),
        "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA256,
    }
    semantics = {
        "source_acceptance": "V32-1.1.10-engineering-integration-successor",
        "frozen_acceptance": "compiled-verifier-anchored-packaged-runtime-v1",
        "release_version": "1.1.10",
        "stable_activation": "V24",
        "qml_root": "V11",
        "orb_controller": "V12",
        "new_renderer_created": False,
        "owner_scope_protections_preserved": True,
        "runtime_refusal_bypass": False,
    }
    if (
        set(manifest)
        != {
            "schema",
            "candidate",
            "decision",
            "current_root",
            "predecessor",
            "runtime_inputs",
            "artifact_root_sha256",
            "semantics",
        }
        or manifest.get("schema") != "onyx.hud.current.v32.acceptance.v1"
        or manifest.get("candidate") != "onyx-hud-v32-1.1.10-integration-001"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("predecessor") != predecessor
        or manifest.get("semantics") != semantics
    ):
        raise CurrentHudAcceptanceV32Error("V32 manifest contract drift")
    entries = manifest["runtime_inputs"]
    if type(entries) is not list or len(entries) != len(CURRENT_RUNTIME_PATHS):
        raise CurrentHudAcceptanceV32Error("V32 source membership drift")
    records: list[dict[str, str]] = []
    for relative, entry in zip(CURRENT_RUNTIME_PATHS, entries, strict=True):
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or entry.get("path") != relative.as_posix()
            or type(entry.get("sha256")) is not str
            or len(entry["sha256"]) != 64
        ):
            raise CurrentHudAcceptanceV32Error("V32 source membership drift")
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise CurrentHudAcceptanceV32Error(f"V32 source input drift: {relative}")
        records.append(entry)
    artifact_root = _artifact_root(records)
    if manifest.get("artifact_root_sha256") != artifact_root:
        raise CurrentHudAcceptanceV32Error("V32 artifact root drift")
    for relative, expected in (
        (PREDECESSOR_MANIFEST_RELATIVE, PREDECESSOR_MANIFEST_SHA256),
        (PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_ACCEPTANCE_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise CurrentHudAcceptanceV32Error(
                f"immutable V31 predecessor drift: {relative}"
            )
    anchors = (
        (Path("ui.py"), "core.onyx_hud_current_acceptance_v32"),
        (Path("ui.py"), "core.onyx_hud_orb_v12"),
        (Path("qml/OnyxLiveShellV11.qml"), 'objectName: "onyxLiveShellV11Root"'),
        (Path("core/onyx_hud_orb_v12.py"), "V12 does not replace the V11 QML renderer"),
        (Path("packaging/onyx.spec"), '"core.onyx_hud_orb_v12"'),
        (Path("packaging/onyx.spec"), '"core.onyx_hud_current_acceptance_v32"'),
        (Path("main.py"), 'os.environ.get("ONYX_BUILD_VERSION", "1.1.10")'),
    )
    for relative, anchor in anchors:
        if anchor not in _canonical_file(root, relative).read_text(encoding="utf-8"):
            raise CurrentHudAcceptanceV32Error(f"V32 wiring drift: {relative}")
    return {
        "candidate": manifest["candidate"],
        "current_root": CURRENT_ROOT.as_posix(),
        "runtime_inputs": len(records),
        "artifact_root_sha256": artifact_root,
        "predecessor_manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "release_version": "1.1.10",
        "stable_activation": "V24",
        "packaged_subset_contract": "v1",
        "qml_root": "V11",
        "orb_controller": "V12",
        "manifest_sha256": _sha256(_canonical_file(root, MANIFEST_RELATIVE)),
        "runtime_input_sha256": {
            entry["path"]: entry["sha256"] for entry in records
        },
    }


ARTIFACT_ROOT_SHA256: Final = "manifest-bound"


__all__ = [
    "ARTIFACT_ROOT_SHA256",
    "CURRENT_ACCEPTANCE_RELATIVE",
    "CURRENT_ROOT",
    "CURRENT_RUNTIME_PATHS",
    "CurrentHudAcceptanceV32Error",
    "MANIFEST_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_SHA256",
    "PREDECESSOR_MANIFEST_RELATIVE",
    "PREDECESSOR_MANIFEST_SHA256",
    "verify_current_hud_acceptance",
]
