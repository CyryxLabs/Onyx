"""Current full-source HUD acceptance over immutable V25 package evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class CurrentHudAcceptanceV26Error(RuntimeError):
    """The V26 source/runtime split or its V25 predecessor drifted."""


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V25-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "539b0026cdc5df10f01426ffb57cbc134a4dbe74172037936e3296fa741178f5"
)
PREDECESSOR_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v25.py"
)
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "1d65cf04a302b261c5874180ee2d8a5028a651fe507f12f720df1ec4631f2d00"
)
CURRENT_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v26.py"
)
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV10.qml")
CURRENT_RUNTIME_PATHS: Final = (
    Path("qml/OnyxLiveShellV10.qml"),
    Path("qml/components/OnyxOrbEntityV7.qml"),
    Path("qml/components/OnyxOrbVoiceLayerV8.qml"),
    Path("qml/assets/onyx-orb-particle-v6.png"),
    Path("core/onyx_hud_orb_v10.py"),
    Path("core/native_startup_smoke_v1.py"),
    Path("core/onyx_packaged_runtime_hud_contract_v1.py"),
    Path("core/onyx_packaged_runtime_hud_contract_v1.manifest.json"),
    Path("scripts/bootstrap_onyx.pyw"),
    Path("scripts/bootstrap_onyx_live_v24.pyw"),
    Path("scripts/package_hygiene.py"),
    Path("scripts/build_release.py"),
    Path("packaging/onyx.spec"),
    Path("ui.py"),
    Path("tests/conftest.py"),
    Path("tests/test_native_startup_smoke_v1.py"),
    Path("tests/test_packaged_runtime_hud_contract_v1.py"),
    Path("tests/test_frozen_bootstrap_diagnostics_v1.py"),
    Path("tests/test_hud_source_frozen_selection_v1.py"),
    Path("tests/test_pyside6_hud_collection_compat.py"),
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    CURRENT_ACCEPTANCE_RELATIVE,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path) -> Path:
    root = root.resolve()
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative.as_posix():
        raise CurrentHudAcceptanceV26Error("noncanonical V26 source path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise CurrentHudAcceptanceV26Error(f"V26 source input unavailable: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise CurrentHudAcceptanceV26Error(f"V26 source input escapes root: {relative}") from exc
    if resolved != candidate.absolute():
        raise CurrentHudAcceptanceV26Error(f"V26 source input is linked: {relative}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise CurrentHudAcceptanceV26Error("duplicate V26 manifest key")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV26Error("V26 manifest unreadable") from exc
    if type(value) is not dict:
        raise CurrentHudAcceptanceV26Error("V26 manifest must be an object")
    return value


def _artifact_root(records: list[dict[str, str]]) -> str:
    payload = "".join(
        f"{entry['path']}\0{entry['sha256']}\n"
        for entry in sorted(records, key=lambda item: item["path"])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Authenticate the complete V26 source authority; never use in frozen hosts."""

    root = Path(project).resolve()
    manifest = _strict_json(_canonical_file(root, MANIFEST_RELATIVE))
    predecessor = {
        "manifest_path": PREDECESSOR_MANIFEST_RELATIVE.as_posix(),
        "manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "acceptance_path": PREDECESSOR_ACCEPTANCE_RELATIVE.as_posix(),
        "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA256,
    }
    if (
        set(manifest) != {
            "schema", "candidate", "decision", "current_root", "predecessor",
            "runtime_inputs", "artifact_root_sha256", "semantics",
        }
        or manifest.get("schema") != "onyx.hud.current.v26.acceptance.v1"
        or manifest.get("candidate")
        != "onyx-hud-v10-v38-frozen-diagnostic-closure-008"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("predecessor") != predecessor
        or manifest.get("semantics") != {
            "source_acceptance": "V26-full-repository",
            "frozen_acceptance": "compiled-verifier-anchored-packaged-runtime-v1",
            "stable_activation": "V24",
            "native_v24_option_injection": False,
            "diagnostic_exception_mode": "noninteractive-exit-70",
            "runtime_refusal_bypass": False,
        }
    ):
        raise CurrentHudAcceptanceV26Error("V26 manifest contract drift")
    entries = manifest["runtime_inputs"]
    if type(entries) is not list or len(entries) != len(CURRENT_RUNTIME_PATHS):
        raise CurrentHudAcceptanceV26Error("V26 source membership drift")
    records: list[dict[str, str]] = []
    for relative, entry in zip(CURRENT_RUNTIME_PATHS, entries, strict=True):
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or entry.get("path") != relative.as_posix()
            or type(entry.get("sha256")) is not str
            or len(entry["sha256"]) != 64
        ):
            raise CurrentHudAcceptanceV26Error("V26 source membership drift")
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise CurrentHudAcceptanceV26Error(f"V26 source input drift: {relative}")
        records.append(entry)
    artifact_root = _artifact_root(records)
    if manifest.get("artifact_root_sha256") != artifact_root:
        raise CurrentHudAcceptanceV26Error("V26 artifact root drift")
    for relative, expected in (
        (PREDECESSOR_MANIFEST_RELATIVE, PREDECESSOR_MANIFEST_SHA256),
        (PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_ACCEPTANCE_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise CurrentHudAcceptanceV26Error(f"immutable V25 predecessor drift: {relative}")
    anchors = (
        (Path("ui.py"), "core.onyx_hud_current_acceptance_v26"),
        (Path("ui.py"), "verify_packaged_runtime_hud_contract(root)"),
        (Path("scripts/package_hygiene.py"), '"scripts/bootstrap_onyx.pyw"'),
        (Path("scripts/package_hygiene.py"), "SOURCE_ONLY_HUD_AUTHORITY_FILES"),
        (Path("packaging/onyx.spec"), '"core.onyx_packaged_runtime_hud_contract_v1"'),
    )
    for relative, anchor in anchors:
        if anchor not in _canonical_file(root, relative).read_text(encoding="utf-8"):
            raise CurrentHudAcceptanceV26Error(f"V26 wiring drift: {relative}")
    return {
        "candidate": manifest["candidate"],
        "current_root": CURRENT_ROOT.as_posix(),
        "runtime_inputs": len(records),
        "artifact_root_sha256": artifact_root,
        "predecessor_manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "stable_activation": "V24",
        "packaged_subset_contract": "v1",
        "manifest_sha256": _sha256(_canonical_file(root, MANIFEST_RELATIVE)),
        "runtime_input_sha256": {entry["path"]: entry["sha256"] for entry in records},
    }


ARTIFACT_ROOT_SHA256: Final = "manifest-bound"


__all__ = [
    "ARTIFACT_ROOT_SHA256", "CURRENT_ACCEPTANCE_RELATIVE", "CURRENT_ROOT",
    "CURRENT_RUNTIME_PATHS", "CurrentHudAcceptanceV26Error", "MANIFEST_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_RELATIVE", "PREDECESSOR_ACCEPTANCE_SHA256",
    "PREDECESSOR_MANIFEST_RELATIVE", "PREDECESSOR_MANIFEST_SHA256",
    "verify_current_hud_acceptance",
]
