"""Current HUD acceptance successor for the symlink-safe 1.1.10 runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class CurrentHudAcceptanceV33Error(RuntimeError):
    """The V33 source closure or immutable V32 predecessor drifted."""


MANIFEST_RELATIVE: Final = Path("docs/onyx/acceptance/VE-HUD-CURRENT-V33-E6-001.manifest.json")
PREDECESSOR_MANIFEST_RELATIVE: Final = Path("docs/onyx/acceptance/VE-HUD-CURRENT-V32-E6-001.manifest.json")
PREDECESSOR_MANIFEST_SHA256: Final = "c2ae65be74b6c324a2f59e4d7b14499fec026c830eab25c6ab1c9aa5a19bbcdc"
PREDECESSOR_ACCEPTANCE_RELATIVE: Final = Path("core/onyx_hud_current_acceptance_v32.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = "0ce32693cd5f4311481a364de622d37d594bfd703dd034a451581945b80b2020"
CURRENT_ACCEPTANCE_RELATIVE: Final = Path("core/onyx_hud_current_acceptance_v33.py")
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV11.qml")
CURRENT_RUNTIME_PATHS: Final = (
    Path("qml/OnyxLiveShellV11.qml"), Path("qml/OnyxLiveShellGuardedV1.qml"),
    Path("qml/components/OnyxOrbEntityV8.qml"), Path("core/onyx_hud_orb_v12.py"),
    Path("core/version.py"), Path("core/autostart_registration_v1.py"),
    Path("core/topic_monitor_v1.py"), Path("core/permission_broker.py"),
    Path("actions/computer_settings.py"), Path("actions/reminder.py"),
    Path("actions/file_controller.py"), Path("actions/desktop.py"),
    Path("actions/youtube_video.py"), Path("core/onyx_packaged_runtime_hud_contract_v1.py"),
    Path("core/onyx_packaged_runtime_hud_contract_v1.manifest.json"),
    Path("scripts/package_hygiene.py"), Path("scripts/build_release.py"),
    Path("packaging/onyx.spec"), Path("main.py"), Path("ui.py"),
    Path("tests/test_autostart_registration_v1.py"), Path("tests/test_topic_monitor_v1.py"),
    Path("tests/test_regressions.py"), PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE, Path("scripts/generate_hud_v32_manifests.py"),
    Path("tests/test_onyx_hud_current_acceptance_v32.py"), CURRENT_ACCEPTANCE_RELATIVE,
    Path("scripts/generate_hud_v33_manifests.py"),
    Path("tests/test_onyx_hud_current_acceptance_v33.py"),
    Path("tests/test_package_hygiene_v1.py"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path) -> Path:
    root = root.resolve()
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative.as_posix():
        raise CurrentHudAcceptanceV33Error("noncanonical V33 source path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise CurrentHudAcceptanceV33Error(f"V33 source input unavailable: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise CurrentHudAcceptanceV33Error(f"V33 source input escapes root: {relative}") from exc
    if resolved != candidate.absolute():
        raise CurrentHudAcceptanceV33Error(f"V33 source input is linked: {relative}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise CurrentHudAcceptanceV33Error("duplicate V33 manifest key")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV33Error("V33 manifest unreadable") from exc
    if type(value) is not dict:
        raise CurrentHudAcceptanceV33Error("V33 manifest must be an object")
    return value


def _artifact_root(records: list[dict[str, str]]) -> str:
    payload = "".join(f"{entry['path']}\0{entry['sha256']}\n" for entry in sorted(records, key=lambda item: item["path"])).encode()
    return hashlib.sha256(payload).hexdigest()


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Authenticate current bytes while preserving link/reparse refusal semantics."""
    root = Path(project).resolve()
    manifest = _strict_json(_canonical_file(root, MANIFEST_RELATIVE))
    predecessor = {
        "manifest_path": PREDECESSOR_MANIFEST_RELATIVE.as_posix(),
        "manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "acceptance_path": PREDECESSOR_ACCEPTANCE_RELATIVE.as_posix(),
        "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA256,
    }
    semantics = {
        "source_acceptance": "V33-1.1.10-symlink-safe-package-successor",
        "frozen_acceptance": "explicit-smoke-without-packaged-test-sources",
        "release_version": "1.1.10", "stable_activation": "V24",
        "qml_root": "V11", "orb_controller": "V12", "new_renderer_created": False,
        "owner_scope_protections_preserved": True, "runtime_refusal_bypass": False,
        "symlink_and_reparse_protection_preserved": True,
        "staging_destination_link_protection_preserved": True,
        "packaged_test_sources": False,
    }
    if (set(manifest) != {"schema", "candidate", "decision", "current_root", "predecessor", "runtime_inputs", "packaged_runtime_inputs", "artifact_root_sha256", "packaged_artifact_root_sha256", "semantics"}
        or manifest.get("schema") != "onyx.hud.current.v33.acceptance.v1"
        or manifest.get("candidate") != "onyx-hud-v33-1.1.10-symlink-safe-001"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("predecessor") != predecessor or manifest.get("semantics") != semantics):
        raise CurrentHudAcceptanceV33Error("V33 manifest contract drift")
    entries = manifest["runtime_inputs"]
    if type(entries) is not list or len(entries) != len(CURRENT_RUNTIME_PATHS):
        raise CurrentHudAcceptanceV33Error("V33 source membership drift")
    records: list[dict[str, str]] = []
    for relative, entry in zip(CURRENT_RUNTIME_PATHS, entries, strict=True):
        if type(entry) is not dict or set(entry) != {"path", "sha256"} or entry.get("path") != relative.as_posix() or type(entry.get("sha256")) is not str or len(entry["sha256"]) != 64:
            raise CurrentHudAcceptanceV33Error("V33 source membership drift")
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise CurrentHudAcceptanceV33Error(f"V33 source input drift: {relative}")
        records.append(entry)
    if manifest.get("artifact_root_sha256") != _artifact_root(records):
        raise CurrentHudAcceptanceV33Error("V33 artifact root drift")
    for relative, expected in ((PREDECESSOR_MANIFEST_RELATIVE, PREDECESSOR_MANIFEST_SHA256), (PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_ACCEPTANCE_SHA256)):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise CurrentHudAcceptanceV33Error(f"immutable V32 predecessor drift: {relative}")
    broker = _canonical_file(root, Path("core/permission_broker.py")).read_text(encoding="utf-8")
    for anchor in ("_redirects_through_a_link(base)", "cursor.is_symlink()", 'getattr(info, "st_file_attributes", 0) & 0x400', "before resolution"):
        if anchor not in broker:
            raise CurrentHudAcceptanceV33Error("V33 symlink/reparse protection drift")
    hygiene = _canonical_file(root, Path("scripts/package_hygiene.py")).read_text(encoding="utf-8")
    for anchor in ("unsafe linked runtime staging destination", "verify_current_hud_acceptance(root)"):
        if anchor not in hygiene:
            raise CurrentHudAcceptanceV33Error("V33 staging protection drift")
    return {"candidate": manifest["candidate"], "runtime_inputs": len(records), "artifact_root_sha256": manifest["artifact_root_sha256"], "manifest_sha256": _sha256(_canonical_file(root, MANIFEST_RELATIVE)), "symlink_and_reparse_protection_preserved": True, "packaged_test_sources": False}


def verify_packaged_runtime_hud_subset(stage: Path, *, project: Path) -> dict[str, object]:
    """Authenticate the V33 staged runtime and reject packaged test sources."""
    root = Path(project).resolve()
    staged = Path(stage).resolve(strict=True)
    manifest = _strict_json(_canonical_file(root, MANIFEST_RELATIVE))
    records = manifest.get("packaged_runtime_inputs")
    if type(records) is not list or not records:
        raise CurrentHudAcceptanceV33Error("V33 packaged membership drift")
    normalized: list[dict[str, str]] = []
    for entry in records:
        if type(entry) is not dict or set(entry) != {"path", "sha256"} or type(entry.get("path")) is not str or type(entry.get("sha256")) is not str:
            raise CurrentHudAcceptanceV33Error("V33 packaged membership drift")
        relative = Path(entry["path"])
        if "tests" in relative.parts or _sha256(_canonical_file(staged, relative)) != entry["sha256"]:
            raise CurrentHudAcceptanceV33Error(f"V33 packaged runtime drift: {relative}")
        normalized.append(entry)
    if _artifact_root(normalized) != manifest.get("packaged_artifact_root_sha256"):
        raise CurrentHudAcceptanceV33Error("V33 packaged artifact root drift")
    if (staged / "tests").exists():
        raise CurrentHudAcceptanceV33Error("V33 packaged tests are forbidden")
    return {"packaged_runtime_inputs": len(normalized), "packaged_test_sources": False}


__all__ = ["CURRENT_RUNTIME_PATHS", "CurrentHudAcceptanceV33Error", "MANIFEST_RELATIVE", "PREDECESSOR_ACCEPTANCE_RELATIVE", "PREDECESSOR_MANIFEST_RELATIVE", "verify_current_hud_acceptance", "verify_packaged_runtime_hud_subset"]
