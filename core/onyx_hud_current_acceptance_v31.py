"""Current HUD acceptance for post-load ambient-motion synchronization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class CurrentHudAcceptanceV31Error(RuntimeError):
    """The V31 source closure or its immutable V30 predecessor drifted."""


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V31-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V30-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "03ac350d5416afb6c801f8f1928c9be76c565d90db866ffb7ac3d907a892faa4"
)
PREDECESSOR_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v30.py"
)
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "65ff03903196f65fc3356d097b5d981618f99def326964d1ff19ed090b74898c"
)
CURRENT_ACCEPTANCE_RELATIVE: Final = Path("core/onyx_hud_current_acceptance_v31.py")
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV11.qml")
CURRENT_RUNTIME_PATHS: Final = (
    Path("qml/OnyxLiveShellV11.qml"),
    Path("qml/OnyxLiveShellGuardedV1.qml"),
    Path("qml/components/OnyxOrbEntityV8.qml"),
    Path("qml/components/OnyxOrbEntityV7.qml"),
    Path("core/orb_motion_v1.py"),
    Path("core/onyx_hud_orb_v11.py"),
    Path("core/onyx_hud_orb_v12.py"),
    Path("core/onyx_packaged_runtime_hud_contract_v1.py"),
    Path("core/onyx_packaged_runtime_hud_contract_v1.manifest.json"),
    Path("scripts/bootstrap_onyx.pyw"),
    Path("scripts/bootstrap_onyx_live_v24.pyw"),
    Path("scripts/package_hygiene.py"),
    Path("scripts/build_release.py"),
    Path("scripts/generate_hud_v31_manifests.py"),
    Path("packaging/onyx.spec"),
    Path("main.py"),
    Path("ui.py"),
    Path("tests/test_onyx_hud_orb_v12.py"),
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    CURRENT_ACCEPTANCE_RELATIVE,
    Path("tests/test_onyx_hud_current_acceptance_v31.py"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path) -> Path:
    root = root.resolve()
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative.as_posix():
        raise CurrentHudAcceptanceV31Error("noncanonical V31 source path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise CurrentHudAcceptanceV31Error(f"V31 source input unavailable: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise CurrentHudAcceptanceV31Error(
            f"V31 source input escapes root: {relative}"
        ) from exc
    if resolved != candidate.absolute():
        raise CurrentHudAcceptanceV31Error(f"V31 source input is linked: {relative}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise CurrentHudAcceptanceV31Error("duplicate V31 manifest key")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV31Error("V31 manifest unreadable") from exc
    if type(value) is not dict:
        raise CurrentHudAcceptanceV31Error("V31 manifest must be an object")
    return value


def _artifact_root(records: list[dict[str, str]]) -> str:
    payload = "".join(
        f"{entry['path']}\0{entry['sha256']}\n"
        for entry in sorted(records, key=lambda item: item["path"])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Authenticate the V12 post-load synchronization over immutable V30."""

    root = Path(project).resolve()
    manifest = _strict_json(_canonical_file(root, MANIFEST_RELATIVE))
    predecessor = {
        "manifest_path": PREDECESSOR_MANIFEST_RELATIVE.as_posix(),
        "manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "acceptance_path": PREDECESSOR_ACCEPTANCE_RELATIVE.as_posix(),
        "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA256,
    }
    semantics = {
        "source_acceptance": "V31-post-load-ambient-motion-successor",
        "frozen_acceptance": "compiled-verifier-anchored-packaged-runtime-v1",
        "stable_activation": "V24",
        "qml_roots_published_at_construction": 1,
        "post_load_lifecycle_resynchronised": True,
        "ambient_motion_policy_reused": True,
        "additional_render_timer_created": False,
        "hidden_motion_stops": True,
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
        or manifest.get("schema") != "onyx.hud.current.v31.acceptance.v1"
        or manifest.get("candidate") != "onyx-hud-v12-ambient-motion-001"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("predecessor") != predecessor
        or manifest.get("semantics") != semantics
    ):
        raise CurrentHudAcceptanceV31Error("V31 manifest contract drift")
    entries = manifest["runtime_inputs"]
    if type(entries) is not list or len(entries) != len(CURRENT_RUNTIME_PATHS):
        raise CurrentHudAcceptanceV31Error("V31 source membership drift")
    records: list[dict[str, str]] = []
    for relative, entry in zip(CURRENT_RUNTIME_PATHS, entries, strict=True):
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or entry.get("path") != relative.as_posix()
            or type(entry.get("sha256")) is not str
            or len(entry["sha256"]) != 64
        ):
            raise CurrentHudAcceptanceV31Error("V31 source membership drift")
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise CurrentHudAcceptanceV31Error(f"V31 source input drift: {relative}")
        records.append(entry)
    artifact_root = _artifact_root(records)
    if manifest.get("artifact_root_sha256") != artifact_root:
        raise CurrentHudAcceptanceV31Error("V31 artifact root drift")
    for relative, expected in (
        (PREDECESSOR_MANIFEST_RELATIVE, PREDECESSOR_MANIFEST_SHA256),
        (PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_ACCEPTANCE_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise CurrentHudAcceptanceV31Error(
                f"immutable V30 predecessor drift: {relative}"
            )
    anchors = (
        (Path("ui.py"), "core.onyx_hud_current_acceptance_v31"),
        (Path("ui.py"), "core.onyx_hud_orb_v12"),
        (Path("core/onyx_hud_orb_v12.py"), "self.sync_animation()"),
        (Path("core/onyx_hud_orb_v12.py"), "V12 does not replace the V11 QML renderer"),
        (Path("tests/test_onyx_hud_orb_v12.py"), "_motion_timer.isActive()"),
        (Path("packaging/onyx.spec"), '"core.onyx_hud_orb_v12"'),
    )
    for relative, anchor in anchors:
        if anchor not in _canonical_file(root, relative).read_text(encoding="utf-8"):
            raise CurrentHudAcceptanceV31Error(f"V31 wiring drift: {relative}")
    return {
        "candidate": manifest["candidate"],
        "current_root": CURRENT_ROOT.as_posix(),
        "runtime_inputs": len(records),
        "artifact_root_sha256": artifact_root,
        "predecessor_manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "stable_activation": "V24",
        "packaged_subset_contract": "v1",
        "qml_roots_published_at_construction": 1,
        "post_load_lifecycle_resynchronised": True,
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
    "CurrentHudAcceptanceV31Error",
    "MANIFEST_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_SHA256",
    "PREDECESSOR_MANIFEST_RELATIVE",
    "PREDECESSOR_MANIFEST_SHA256",
    "verify_current_hud_acceptance",
]
