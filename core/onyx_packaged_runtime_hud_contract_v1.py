"""Fail-closed contract for the HUD data staged into frozen Onyx packages.

The source acceptance contract intentionally authenticates development and
build selectors that must never be copied into the curated runtime source
tree.  This companion contract authenticates only the on-disk runtime subset:
HUD predecessor evidence, the live visual/runtime modules and the diagnostic
launch chain.  It also proves that build and test authorities did not leak
into the package stage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


class PackagedRuntimeHudContractV1Error(RuntimeError):
    """The curated packaged-runtime HUD closure is incomplete or drifted."""


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v1.manifest.json"
)
SCHEMA: Final = "onyx.packaged-runtime-hud.v1"
SOURCE_ACCEPTANCE_CANDIDATE: Final = (
    "onyx-hud-v10-v37-packaged-runtime-contract-007"
)
SOURCE_ACCEPTANCE_MODULE: Final = "core/onyx_hud_current_acceptance_v25.py"
SOURCE_ACCEPTANCE_MODULE_SHA256: Final = (
    "1d65cf04a302b261c5874180ee2d8a5028a651fe507f12f720df1ec4631f2d00"
)
SOURCE_ACCEPTANCE_MANIFEST: Final = (
    "docs/onyx/acceptance/VE-HUD-CURRENT-V25-E6-001.manifest.json"
)
SOURCE_ACCEPTANCE_MANIFEST_SHA256: Final = (
    "539b0026cdc5df10f01426ffb57cbc134a4dbe74172037936e3296fa741178f5"
)
# This digest is compiled into PyInstaller's PYZ.  The verifier source is
# deliberately source/compiled-only and therefore is not one of the manifest
# records it authenticates; that removes the verifier <-> manifest hash cycle.
# The deterministic generator replaces this value only after producing the
# on-disk packaged manifest.
PACKAGED_MANIFEST_SHA256: Final = (
    "ffcd839564e211f62fc446858eb915eb60182725287cadae8f286a9a3aeb5360"
)

# Historical test modules retained strictly as immutable runtime hash evidence.
# This tuple is the single membership authority used by the source stager, the
# manifest generator and this packaged verifier.  Pytest and every other test
# or development file remain excluded from the installed application.
RUNTIME_TEST_EVIDENCE_FILES: Final = (
    "tests/test_onyx_hud_orb_v7_candidate.py",
    "tests/test_onyx_hud_orb_v8_candidate.py",
    "tests/test_phase6_live_wiring_v2.py",
)

# Single exact membership authority for HUD acceptance evidence that remains
# on disk in installed packages.  V26+ are full-repository build authorities,
# while the packaged verifier itself lives only as compiled PYZ code.
PACKAGED_HUD_ACCEPTANCE_MODULES: Final = tuple(
    f"core/onyx_hud_current_acceptance_v{version}.py"
    for version in range(19, 26)
)
PACKAGED_HUD_ACCEPTANCE_MANIFESTS: Final = tuple(
    f"docs/onyx/acceptance/VE-HUD-CURRENT-V{version}-E6-001.manifest.json"
    for version in range(19, 26)
)

# Single compiled membership authority for QML admitted into the frozen
# runtime.  Source-side prototypes may coexist under ``qml/`` but cannot grant
# themselves package authority merely by matching a broad glob.  Every member
# below is also required to have an individual hash record in the authenticated
# packaged manifest.
PACKAGED_QML_RUNTIME_FILES: Final = (
    "qml/OnyxLiveShellGuardedV1.qml",
    "qml/OnyxLiveShellV10.qml",
    "qml/OnyxLiveShellV11.qml",
    "qml/OnyxLiveShellV3.qml",
    "qml/OnyxLiveShellV4.qml",
    "qml/OnyxLiveShellV5.qml",
    "qml/OnyxLiveShellV6.qml",
    "qml/OnyxLiveShellV7.qml",
    "qml/OnyxLiveShellV8.qml",
    "qml/OnyxLiveShellV9.qml",
    "qml/OnyxOrb.qml",
    "qml/OnyxShell.qml",
    "qml/OnyxShellV3.qml",
    "qml/assets/onyx-orb-cinematic-v3.png",
    "qml/assets/onyx-orb-particle-v6.png",
    "qml/components/ActionButtonV3.qml",
    "qml/components/HoloPanel.qml",
    "qml/components/OnyxOrbCinematicV3.qml",
    "qml/components/OnyxOrbCinematicV4.qml",
    "qml/components/OnyxOrbCinematicV5.qml",
    "qml/components/OnyxOrbEntityV7.qml",
    "qml/components/OnyxOrbEntityV8.qml",
    "qml/components/OnyxOrbParticleV6.qml",
    "qml/components/OnyxOrbV2.qml",
    "qml/components/OnyxOrbVoiceLayerV8.qml",
    "qml/components/StatusPill.qml",
    "qml/components/TelemetryBar.qml",
)
SOURCE_ONLY_HUD_AUTHORITY_FILES: Final = (
    "core/onyx_hud_current_acceptance_v26.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json",
    "core/onyx_hud_current_acceptance_v27.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V27-E6-001.manifest.json",
    "core/onyx_hud_current_acceptance_v28.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V28-E6-001.manifest.json",
    "core/onyx_hud_current_acceptance_v29.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V29-E6-001.manifest.json",
    "core/onyx_hud_current_acceptance_v30.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V30-E6-001.manifest.json",
    "core/onyx_hud_current_acceptance_v31.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V31-E6-001.manifest.json",
    "core/onyx_hud_current_acceptance_v32.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V32-E6-001.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v1.py",
)

_EXACT_SET_GLOBS: Final = {
    "hud_acceptance_modules": "core/onyx_hud_current_acceptance_v*.py",
    "hud_acceptance_manifests": (
        "docs/onyx/acceptance/VE-HUD-CURRENT-V*-E6-001.manifest.json"
    ),
    "qml_runtime": "qml/**/*",
    "runtime_evidence_tests": "tests/*.py",
}

FORBIDDEN_PATHS: Final = (
    "main.py",
    "ui.py",
    "packaging/onyx.spec",
    "scripts/build_release.py",
    "scripts/package_hygiene.py",
    "tests/conftest.py",
    "tests/test_onyx_hud_current_acceptance_v25.py",
    "tests/test_pyside6_hud_collection_compat.py",
    *SOURCE_ONLY_HUD_AUTHORITY_FILES,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_file(root: Path, relative: str) -> Path:
    parsed = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or parsed.is_absolute()
        or parsed.as_posix() != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise PackagedRuntimeHudContractV1Error(
            f"noncanonical packaged-runtime path: {relative!r}"
        )
    candidate = root.joinpath(*parsed.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise PackagedRuntimeHudContractV1Error(
            f"required packaged-runtime input is unavailable: {relative}"
        )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise PackagedRuntimeHudContractV1Error(
            f"packaged-runtime input escapes stage: {relative}"
        ) from exc
    if resolved != candidate.absolute():
        raise PackagedRuntimeHudContractV1Error(
            f"packaged-runtime input is linked: {relative}"
        )
    return resolved


def _strict_manifest(path: Path) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PackagedRuntimeHudContractV1Error(
                    f"duplicate packaged-runtime manifest key: {key}"
                )
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime manifest is unreadable"
        ) from exc
    if type(payload) is not dict:
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime manifest must be an object"
        )
    return payload


def _artifact_root(records: list[dict[str, str]]) -> str:
    material = "".join(
        f"{record['path']}\0{record['sha256']}\n"
        for record in sorted(records, key=lambda item: item["path"])
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _actual_glob_set(root: Path, pattern: str) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.glob(pattern)
        if path.is_file() and not path.is_symlink()
    )


def expected_exact_sets(root: Path) -> dict[str, list[str]]:
    """Return canonical exact-set membership for generation and verification."""

    # Broad globs are leak detectors only.  Membership is declared here, not
    # inferred from whichever files happen to be present in a source tree.
    return {
        "hud_acceptance_modules": list(PACKAGED_HUD_ACCEPTANCE_MODULES),
        "hud_acceptance_manifests": list(PACKAGED_HUD_ACCEPTANCE_MANIFESTS),
        "qml_runtime": list(PACKAGED_QML_RUNTIME_FILES),
        "runtime_evidence_tests": list(RUNTIME_TEST_EVIDENCE_FILES),
    }


def verify_packaged_runtime_hud_subset(
    stage: Path,
    *,
    source_acceptance: dict[str, object],
    allowed_forbidden_paths: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Authenticate the exact guarded HUD/diagnostic subset in ``stage``."""

    root = Path(stage).resolve(strict=True)
    if not root.is_dir():
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime stage is unavailable"
        )
    manifest_path = _canonical_file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != PACKAGED_MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime manifest digest drifted"
        )
    manifest = _strict_manifest(manifest_path)
    if set(manifest) != {
        "schema",
        "required_files",
        "exact_sets",
        "forbidden_paths",
        "artifact_root_sha256",
    } or manifest.get("schema") != SCHEMA:
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime manifest contract drifted"
        )

    if (
        source_acceptance.get("candidate") != SOURCE_ACCEPTANCE_CANDIDATE
        or type(source_acceptance.get("manifest_sha256")) is not str
        or type(source_acceptance.get("runtime_input_sha256")) is not dict
    ):
        raise PackagedRuntimeHudContractV1Error(
            "full-source V25 acceptance receipt is unavailable"
        )
    source_hashes = source_acceptance["runtime_input_sha256"]
    receipt_bound = {
        "core/onyx_hud_current_acceptance_v25.py": source_hashes.get(
            "core/onyx_hud_current_acceptance_v25.py"
        ),
        "docs/onyx/acceptance/VE-HUD-CURRENT-V25-E6-001.manifest.json": (
            source_acceptance["manifest_sha256"]
        ),
    }
    for relative, expected in receipt_bound.items():
        if (
            type(expected) is not str
            or len(expected) != 64
            or _sha256(_canonical_file(root, relative)) != expected
        ):
            raise PackagedRuntimeHudContractV1Error(
                f"source-receipt packaged-runtime drift: {relative}"
            )

    records = manifest.get("required_files")
    if type(records) is not list or not records:
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime required-file registry drifted"
        )
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        if type(record) is not dict or set(record) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV1Error(
                "packaged-runtime file binding is malformed"
            )
        relative = record.get("path")
        expected = record.get("sha256")
        if (
            type(relative) is not str
            or relative in seen
            or type(expected) is not str
            or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
        ):
            raise PackagedRuntimeHudContractV1Error(
                "packaged-runtime file binding is invalid"
            )
        seen.add(relative)
        path = _canonical_file(root, relative)
        if _sha256(path) != expected:
            raise PackagedRuntimeHudContractV1Error(
                f"packaged-runtime input drift: {relative}"
            )
        normalized.append({"path": relative, "sha256": expected})
    if [record["path"] for record in normalized] != sorted(seen):
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime file membership is not canonical"
        )
    if not set(PACKAGED_QML_RUNTIME_FILES).issubset(seen):
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime QML hash bindings drifted"
        )

    exact_sets = manifest.get("exact_sets")
    if type(exact_sets) is not dict or set(exact_sets) != set(_EXACT_SET_GLOBS):
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime exact-set registry drifted"
        )
    canonical_sets = expected_exact_sets(root)
    for name, pattern in _EXACT_SET_GLOBS.items():
        expected = exact_sets.get(name)
        if (
            type(expected) is not list
            or any(type(item) is not str for item in expected)
            or expected != sorted(set(expected))
            or expected != canonical_sets[name]
            or _actual_glob_set(root, pattern) != expected
        ):
            raise PackagedRuntimeHudContractV1Error(
                f"packaged-runtime exact membership drift: {name}"
            )

    if not allowed_forbidden_paths.issubset({"main.py", "ui.py"}):
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime forbidden allowlist drifted"
        )
    forbidden = manifest.get("forbidden_paths")
    if forbidden != list(FORBIDDEN_PATHS):
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime forbidden-path registry drifted"
        )
    leaked = [
        relative
        for relative in FORBIDDEN_PATHS
        if relative not in allowed_forbidden_paths and (root / relative).exists()
    ]
    if leaked:
        raise PackagedRuntimeHudContractV1Error(
            f"development/build input leaked into runtime stage: {leaked[0]}"
        )

    artifact_root = _artifact_root(normalized)
    if manifest.get("artifact_root_sha256") != artifact_root:
        raise PackagedRuntimeHudContractV1Error(
            "packaged-runtime artifact root drifted"
        )
    return {
        "schema": SCHEMA,
        "required_files": len(normalized),
        "artifact_root_sha256": artifact_root,
        "guarded_sets": len(_EXACT_SET_GLOBS),
        "forbidden_paths": len(FORBIDDEN_PATHS),
        "source_receipt_files": len(receipt_bound),
    }


def authenticated_v25_source_receipt() -> dict[str, object]:
    """Return the compiled, immutable source receipt used by package checks."""

    return {
        "candidate": SOURCE_ACCEPTANCE_CANDIDATE,
        "manifest_sha256": SOURCE_ACCEPTANCE_MANIFEST_SHA256,
        "runtime_input_sha256": {
            SOURCE_ACCEPTANCE_MODULE: SOURCE_ACCEPTANCE_MODULE_SHA256,
        },
    }


def verify_packaged_runtime_hud_contract(resource_root: Path) -> dict[str, object]:
    """Authenticate the frozen HUD without requiring repository-only inputs.

    The compiled verifier pins the exact build-time V25 source receipt.  The
    bundle must carry that V25 module and manifest byte-for-byte, after which
    the curated subset manifest authenticates every runtime HUD input.  Final
    PyInstaller roots legitimately contain production ``main.py``/``ui.py``
    data outside the curated source stage, so only the build-stage verifier
    enforces the stage-local absence registry.
    """

    root = Path(resource_root).resolve(strict=True)
    for relative, expected in (
        (SOURCE_ACCEPTANCE_MODULE, SOURCE_ACCEPTANCE_MODULE_SHA256),
        (SOURCE_ACCEPTANCE_MANIFEST, SOURCE_ACCEPTANCE_MANIFEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise PackagedRuntimeHudContractV1Error(
                f"authenticated source receipt drift: {relative}"
            )
    receipt = authenticated_v25_source_receipt()
    result = verify_packaged_runtime_hud_subset(
        root,
        source_acceptance=receipt,
        allowed_forbidden_paths=frozenset({"main.py", "ui.py"}),
    )
    return {**result, "source_acceptance": "V25-authenticated"}


__all__ = [
    "MANIFEST_RELATIVE",
    "FORBIDDEN_PATHS",
    "PACKAGED_HUD_ACCEPTANCE_MANIFESTS",
    "PACKAGED_HUD_ACCEPTANCE_MODULES",
    "PACKAGED_MANIFEST_SHA256",
    "PackagedRuntimeHudContractV1Error",
    "PACKAGED_QML_RUNTIME_FILES",
    "RUNTIME_TEST_EVIDENCE_FILES",
    "SCHEMA",
    "SOURCE_ACCEPTANCE_CANDIDATE",
    "SOURCE_ACCEPTANCE_MANIFEST",
    "SOURCE_ACCEPTANCE_MANIFEST_SHA256",
    "SOURCE_ACCEPTANCE_MODULE",
    "SOURCE_ACCEPTANCE_MODULE_SHA256",
    "SOURCE_ONLY_HUD_AUTHORITY_FILES",
    "authenticated_v25_source_receipt",
    "expected_exact_sets",
    "verify_packaged_runtime_hud_contract",
    "verify_packaged_runtime_hud_subset",
]
