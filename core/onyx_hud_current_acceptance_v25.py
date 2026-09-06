"""Current source acceptance for the V10 HUD and packaged-runtime closure.

V25 succeeds the immutable V24 source record.  Unlike the dedicated packaged
subset verifier, this authority intentionally authenticates selectors, build
code and regression tests from the full repository tree.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class CurrentHudAcceptanceV25Error(RuntimeError):
    """The current full-source HUD acceptance closure no longer matches V25."""


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V25-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V24-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "b0983ff42f0d49a3c49a3eaeacae39913ae0c652cbc18ea736c1362572056200"
)
PREDECESSOR_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v24.py"
)
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "7ace2382c7bc734c62d54e12262b3fdbf8e7d34606dde1419b0f33881eea0095"
)
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV10.qml")
CURRENT_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v25.py"
)
CURRENT_QML_CHAIN: Final = (
    Path("qml/OnyxLiveShellV7.qml"),
    Path("qml/OnyxLiveShellV8.qml"),
    Path("qml/OnyxLiveShellV9.qml"),
    Path("qml/OnyxLiveShellV10.qml"),
    Path("qml/components/OnyxOrbEntityV7.qml"),
    Path("qml/components/OnyxOrbVoiceLayerV8.qml"),
)
CURRENT_RUNTIME_PATHS: Final = (
    *CURRENT_QML_CHAIN,
    Path("qml/assets/onyx-orb-particle-v6.png"),
    Path("core/onyx_hud_orb_v10.py"),
    Path("core/ui_projection_v3.py"),
    Path("core/render_governor_v3.py"),
    Path("core/onyx_live_activation_v24.py"),
    Path("core/installer_lifecycle_v1.py"),
    Path("scripts/bootstrap_onyx.pyw"),
    Path("scripts/bootstrap_onyx_live_v24.pyw"),
    Path("scripts/launch_onyx_live_v24.pyw"),
    Path("ui.py"),
    Path("main.py"),
    Path("scripts/build_release.py"),
    Path("scripts/package_hygiene.py"),
    Path("packaging/onyx.spec"),
    Path("tests/conftest.py"),
    Path("tests/test_pyside6_hud_collection_compat.py"),
    Path("core/onyx_packaged_runtime_hud_contract_v1.py"),
    Path("core/onyx_packaged_runtime_hud_contract_v1.manifest.json"),
    Path("tests/test_packaged_runtime_hud_contract_v1.py"),
    Path("tests/test_package_hygiene_v1.py"),
    CURRENT_ACCEPTANCE_RELATIVE,
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
        raise CurrentHudAcceptanceV25Error("noncanonical current HUD path")
    path = project.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise CurrentHudAcceptanceV25Error(f"current HUD input is unavailable: {relative}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(project)
    except (OSError, ValueError) as exc:
        raise CurrentHudAcceptanceV25Error(
            f"current HUD input escapes project: {relative}"
        ) from exc
    if resolved != path.absolute():
        raise CurrentHudAcceptanceV25Error(f"current HUD input is linked: {relative}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CurrentHudAcceptanceV25Error(
                    f"duplicate current HUD manifest key: {key}"
                )
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV25Error("current HUD manifest is unreadable") from exc
    if type(payload) is not dict:
        raise CurrentHudAcceptanceV25Error("current HUD manifest must be an object")
    return payload


def _artifact_root(records: tuple[tuple[Path, str], ...]) -> str:
    material = "".join(
        f"{path.as_posix()}\0{digest}\n"
        for path, digest in sorted(records, key=lambda item: item[0].as_posix())
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _manifest_records(manifest: dict[str, object]) -> tuple[tuple[Path, str], ...]:
    entries = manifest.get("runtime_inputs")
    if type(entries) is not list or len(entries) != len(CURRENT_RUNTIME_PATHS):
        raise CurrentHudAcceptanceV25Error("current HUD input membership drift")
    records: list[tuple[Path, str]] = []
    for expected_path, entry in zip(CURRENT_RUNTIME_PATHS, entries, strict=True):
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or entry.get("path") != expected_path.as_posix()
            or type(entry.get("sha256")) is not str
            or len(entry["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in entry["sha256"])
        ):
            raise CurrentHudAcceptanceV25Error("current HUD input membership drift")
        records.append((expected_path, entry["sha256"]))
    return tuple(records)


def _verify_semantics(project: Path) -> None:
    anchors = (
        (Path("ui.py"), "core.onyx_hud_current_acceptance_v25"),
        (Path("scripts/build_release.py"), "verify_packaged_runtime_hud_subset"),
        (Path("scripts/build_release.py"), "core.onyx_hud_current_acceptance_v25"),
        (Path("scripts/package_hygiene.py"), "range(20, 26)"),
        (Path("scripts/package_hygiene.py"), "verify_packaged_runtime_hud_subset("),
        (Path("packaging/onyx.spec"), '"core.onyx_hud_current_acceptance_v25"'),
        (Path("tests/conftest.py"), '"test_onyx_hud_current_acceptance_v24.py"'),
        (
            Path("tests/test_pyside6_hud_collection_compat.py"),
            'CURRENT_HUD = "tests/test_onyx_hud_current_acceptance_v25.py"',
        ),
    )
    for relative, anchor in anchors:
        if anchor not in _canonical_file(project, relative).read_text(encoding="utf-8"):
            raise CurrentHudAcceptanceV25Error(f"current HUD wiring drift: {relative}")


def verify_current_hud_runtime_inputs(project: Path) -> str:
    """Verify the exact V25 full-source closure declared by its manifest."""

    project = Path(project).resolve()
    manifest = _strict_json(_canonical_file(project, MANIFEST_RELATIVE))
    records = _manifest_records(manifest)
    for relative, expected in records:
        if _sha256(_canonical_file(project, relative)) != expected:
            raise CurrentHudAcceptanceV25Error(f"current HUD input drift: {relative}")
    root = _artifact_root(records)
    if manifest.get("artifact_root_sha256") != root:
        raise CurrentHudAcceptanceV25Error("current HUD artifact root drift")
    for relative, expected in (
        (PREDECESSOR_MANIFEST_RELATIVE, PREDECESSOR_MANIFEST_SHA256),
        (PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_ACCEPTANCE_SHA256),
    ):
        if _sha256(_canonical_file(project, relative)) != expected:
            raise CurrentHudAcceptanceV25Error(f"immutable V24 predecessor drift: {relative}")
    _verify_semantics(project)
    return root


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Verify V25, its immutable V24 predecessor and full source closure."""

    project = Path(project).resolve()
    manifest = _strict_json(_canonical_file(project, MANIFEST_RELATIVE))
    expected_predecessor = {
        "manifest_path": PREDECESSOR_MANIFEST_RELATIVE.as_posix(),
        "manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "acceptance_path": PREDECESSOR_ACCEPTANCE_RELATIVE.as_posix(),
        "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA256,
    }
    if (
        set(manifest) != {
            "schema", "candidate", "decision", "current_root", "runtime_qml_chain",
            "predecessor", "runtime_inputs", "artifact_root_sha256", "semantics",
            "historical_acceptance",
        }
        or manifest.get("schema") != "onyx.hud.current.v25.acceptance.v1"
        or manifest.get("candidate") != "onyx-hud-v10-v37-packaged-runtime-contract-007"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("runtime_qml_chain") != [path.as_posix() for path in CURRENT_QML_CHAIN]
        or manifest.get("predecessor") != expected_predecessor
        or manifest.get("semantics") != {
            "brand": "Onyx by Cyryx Labs",
            "current_source_projection": "V37",
            "current_hud_shell": "V10",
            "stable_activation": "V24",
            "full_source_verified_before_staging": True,
            "packaged_runtime_subset_verified_after_staging": True,
            "development_build_inputs_absent_from_runtime_stage": True,
            "runtime_refusal_bypass": False,
        }
        or manifest.get("historical_acceptance") != {
            "status": "superseded_immutable_evidence",
            "superseded_test_authority": "tests/test_onyx_hud_current_acceptance_v24.py",
            "successor_test_authority": "tests/test_onyx_hud_current_acceptance_v25.py",
        }
    ):
        raise CurrentHudAcceptanceV25Error("current HUD manifest contract drift")
    artifact_root = verify_current_hud_runtime_inputs(project)
    records = _manifest_records(manifest)
    return {
        "candidate": manifest["candidate"],
        "current_root": CURRENT_ROOT.as_posix(),
        "qml_files": len(CURRENT_QML_CHAIN),
        "runtime_inputs": len(CURRENT_RUNTIME_PATHS),
        "artifact_root_sha256": artifact_root,
        "predecessor_manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "stable_activation": "V24",
        "packaged_subset_contract": "v1",
        "manifest_sha256": _sha256(_canonical_file(project, MANIFEST_RELATIVE)),
        "runtime_input_sha256": {
            relative.as_posix(): digest for relative, digest in records
        },
    }


ARTIFACT_ROOT_SHA256: Final = "manifest-bound"


__all__ = [
    "ARTIFACT_ROOT_SHA256", "CURRENT_QML_CHAIN", "CURRENT_ROOT",
    "CURRENT_RUNTIME_PATHS", "CurrentHudAcceptanceV25Error", "MANIFEST_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_RELATIVE", "PREDECESSOR_ACCEPTANCE_SHA256",
    "PREDECESSOR_MANIFEST_RELATIVE", "PREDECESSOR_MANIFEST_SHA256",
    "verify_current_hud_acceptance", "verify_current_hud_runtime_inputs",
]
