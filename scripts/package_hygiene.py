"""Curate and validate the first-party files shipped with Onyx.

The frozen application imports Python from PyInstaller's archive.  A small
number of source and evidence files must also remain on disk because the live
activation chain verifies their bytes before it starts.  This module keeps that
compatibility closure explicit and prevents the development tree from leaking
into production packages.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import sys
import sysconfig
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from core.onyx_packaged_runtime_hud_contract_v1 import (
    PACKAGED_HUD_ACCEPTANCE_MANIFESTS,
    PACKAGED_HUD_ACCEPTANCE_MODULES,
    PACKAGED_QML_RUNTIME_FILES,
    RUNTIME_TEST_EVIDENCE_FILES,
    SOURCE_ONLY_HUD_AUTHORITY_FILES,
)


RUNTIME_SCRIPT_FILES: Final = (
    # Stable unversioned runtime entry point used by desktop shortcuts and the
    # frozen executable.  It is a production input, not a build helper.
    "scripts/bootstrap_onyx.pyw",
    "scripts/launch_onyx.pyw",
    "scripts/bootstrap_onyx_portable_current_v1.pyw",
    "scripts/launch_onyx_portable_current_v1.pyw",
    # V24 preserves every accepted predecessor launcher and its exact pair.
    *(
        item
        for version in range(8, 25)
        for item in (
            f"scripts/bootstrap_onyx_live_v{version}.pyw",
            f"scripts/launch_onyx_live_v{version}.pyw",
        )
    ),
    # Immutable predecessor evidence read by the V10/V11/V13 preflight chain.
    "scripts/capture_hud_orb_v7_evidence.py",
    "scripts/verify_hud_orb_v7_candidate.py",
    "scripts/capture_hud_orb_v8_evidence.py",
    "scripts/verify_hud_orb_v8_candidate.py",
    "scripts/verify_phase6_live_wiring_v2.py",
)

RUNTIME_HUD_ACCEPTANCE_MODULES: Final = (
    *PACKAGED_HUD_ACCEPTANCE_MODULES,
    "core/onyx_hud_current_acceptance_v35.py",
    "core/onyx_hud_current_acceptance_v36.py",
    "core/onyx_hud_current_acceptance_v37.py",
    "core/onyx_hud_current_acceptance_v38.py",
    "core/onyx_hud_current_acceptance_v39.py",
    "core/onyx_hud_current_acceptance_v40.py",
    "core/onyx_hud_current_acceptance_v41.py",
    "core/onyx_hud_current_acceptance_v42.py",
    "core/onyx_hud_current_acceptance_v43.py",
    "core/onyx_hud_current_acceptance_v44.py",
    "core/onyx_hud_current_acceptance_v45.py",
    "core/onyx_hud_current_acceptance_v46.py",
    "core/onyx_hud_current_acceptance_v47.py",
    "core/onyx_hud_current_acceptance_v48.py",
)
RUNTIME_HUD_ACCEPTANCE_MANIFESTS: Final = (
    *PACKAGED_HUD_ACCEPTANCE_MANIFESTS,
    "docs/onyx/acceptance/VE-HUD-CURRENT-V35-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V36-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V37-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V38-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V39-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V40-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V41-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V42-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V43-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V44-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V45-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V46-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V47-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V48-E6-001.manifest.json",
)
LIQUID_METAL_RUNTIME_FILES: Final = (
    "core/onyx_hud_orb_v13.py",
    "qml/OnyxLiveShellGuardedV2.qml",
    "qml/OnyxLiveShellV12.qml",
    "qml/components/OnyxOrbEntityV9.qml",
)
HUMANOID_PRESENCE_RUNTIME_FILES: Final = (
    "core/onyx_hud_orb_v17.py",
    "core/onyx_packaged_runtime_hud_contract_v16.py",
    "core/onyx_packaged_runtime_hud_contract_v16.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v17.py",
    "core/onyx_packaged_runtime_hud_contract_v17.manifest.json",
    "qml/OnyxLiveShellV16.qml",
    "qml/components/OnyxHumanoidEntityV13.qml",
    "qml/web/onyx-humanoid-three-v4.html",
    "qml/web/onyx-humanoid-three-v5.html",
    "core/onyx_hud_orb_v14.py",
    "core/onyx_packaged_runtime_hud_contract_v6.py",
    "core/onyx_packaged_runtime_hud_contract_v6.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v7.py",
    "core/onyx_packaged_runtime_hud_contract_v7.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v8.py",
    "core/onyx_packaged_runtime_hud_contract_v8.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v9.py",
    "core/onyx_packaged_runtime_hud_contract_v9.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v10.py",
    "core/onyx_packaged_runtime_hud_contract_v10.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v11.py",
    "core/onyx_packaged_runtime_hud_contract_v11.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v12.py",
    "core/onyx_packaged_runtime_hud_contract_v12.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v13.py",
    "core/onyx_packaged_runtime_hud_contract_v13.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v14.py",
    "core/onyx_packaged_runtime_hud_contract_v14.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v15.py",
    "core/onyx_packaged_runtime_hud_contract_v15.manifest.json",
    "core/camera_gesture_attention_v1.py",
    "qml/OnyxLiveShellV13.qml",
    "qml/components/OnyxHumanoidEntityV10.qml",
    "qml/assets/onyx-humanoid-cyryx-v11.png",
    "qml/web/onyx-humanoid-three-v1.html",
    "qml/web/data/onyx-humanoid-pointcloud-v1.js",
    "qml/web/vendor/three/three.module.min.js",
    "qml/web/vendor/three/three.core.min.js",
    "qml/web/vendor/three/LICENSE",
    "core/onyx_hud_orb_v15.py",
    "qml/OnyxLiveShellV14.qml",
    "qml/components/OnyxHumanoidEntityV11.qml",
    "qml/web/onyx-humanoid-three-v2.html",
    "core/onyx_hud_orb_v16.py",
    "qml/OnyxLiveShellV15.qml",
    "qml/components/OnyxHumanoidEntityV12.qml",
    "qml/web/onyx-humanoid-three-v3.html",
)
RUNTIME_HUD_PREDECESSOR_INPUTS: Final = frozenset(
    {"docs/onyx/acceptance/VE-HUD-CURRENT-V32-E6-001.manifest.json"}
)
CAPABILITY_RUNTIME_FILES: Final = (
    "core/network_guardian_v1.py",
    "core/social_official_adapter_v1.py",
    "core/graph_refresh_vault_v2.py",
    "core/phase8_microsoft_graph_oauth_v2.py",
    "core/capability_composition_v1.py",
    "core/capability_ports/__init__.py",
    "core/capability_ports/argos_v1.py",
    "core/capability_ports/budget_v1.py",
    "core/capability_ports/command_center_v1.py",
    "core/capability_ports/evidence_v1.py",
    "core/capability_ports/google_workspace_v1.py",
    "core/capability_ports/graph_v1.py",
    "core/capability_ports/guild_v1.py",
    "core/capability_ports/intelligence_v1.py",
    "core/capability_ports/knowledge_refinery_v1.py",
    "core/capability_ports/mission_context_v1.py",
    "core/capability_ports/model_router_v1.py",
    "core/capability_ports/nexus_v1.py",
    "core/capability_ports/plugin_v1.py",
    "core/capability_ports/project_execution_v1.py",
    "core/capability_ports/social_v1.py",
    "core/capability_ports/strategy_v1.py",
    "core/capability_ports/unified_router_v1.py",
    "core/capability_ports/workspace_v1.py",
    "core/governed_capability_host_v1.py",
    "scripts/onyx_capabilities_cli.py",
)
PACKAGED_RUNTIME_HUD_CONTRACT_MANIFEST: Final = (
    "core/onyx_packaged_runtime_hud_contract_v5.manifest.json"
)
COMPATIBILITY_LAUNCHER_RELATIVE: Final = (
    "packaging/compat/venvwlauncher-python313-x64.exe"
)
COMPATIBILITY_LAUNCHER_SHA256: Final = (
    "51361a2d68a5b4ecf1bad4d7214066e05f9598074e72662e62f7b2e3be3329b3"
)
STAGED_COMPATIBILITY_LAUNCHER: Final = ".venv/Scripts/pythonw.exe"
COMPATIBILITY_NOTICE_RELATIVE: Final = "packaging/compat/PSF-LICENSE.txt"
COMPATIBILITY_NOTICE_SHA256: Final = (
    "62bec384df47b0328307db41455ff6ea2559e5546b394ac69148561b21703120"
)
STAGED_COMPATIBILITY_NOTICE: Final = ".venv/PSF-LICENSE.txt"

# The old integrity contracts unfortunately named a few production hash inputs
# like development artifacts.  They are retained narrowly until that sealed
# predecessor chain is migrated; every other occurrence is rejected.
COMPATIBILITY_EXCEPTIONS: Final = frozenset(
    {
        *RUNTIME_TEST_EVIDENCE_FILES,
        "scripts/capture_hud_orb_v7_evidence.py",
        "scripts/verify_hud_orb_v7_candidate.py",
        "scripts/capture_hud_orb_v8_evidence.py",
        "scripts/verify_hud_orb_v8_candidate.py",
        "scripts/verify_phase6_live_wiring_v2.py",
        "docs/onyx/rejections/HUD_ORB_V6_VISUAL_REJECTION.md",
        "docs/onyx/operations/ONYX_V13_LIVE_PROMOTION_2026-07-23.md",
        "docs/onyx/operations/PHASE11_PROJECT_AUTOPILOT_V1_RUNBOOK.md",
        "docs/onyx/operations/ONYX_V18_DOCUMENT_INTAKE_ACCEPTANCE_2026-07-31.md",
        "docs/onyx/operations/ONYX_V19_DAYOPS_ACCEPTANCE_2026-07-31.md",
        (
            "docs/onyx/checkpoints/phase5-capability-nexus-v32/"
            "phase5-capability-nexus-v32.bundle.json"
        ),
    }
)

# These five inert files are exact inputs of the Cyryx-owned AEXOS 5.3.0
# install manifest.  They are retained so the packaged sidecar can verify its
# 1168-file attestation; this is deliberately not a wildcard for test trees.
AEXOS_ATTESTED_MANIFEST_FILES: Final = frozenset(
    {
        (
            "vendor/aexos-engine-5.3.0/engine/.aexos-core/development/"
            "templates/squad-template/tests/example-agent.test.js"
        ),
        (
            "vendor/aexos-engine-5.3.0/engine/.aexos-core/infrastructure/"
            "tests/project-status-loader.test.js"
        ),
        (
            "vendor/aexos-engine-5.3.0/engine/.aexos-core/infrastructure/"
            "tests/regression-suite-v2.md"
        ),
        (
            "vendor/aexos-engine-5.3.0/engine/.aexos-core/infrastructure/"
            "tests/validate-module.js"
        ),
        (
            "vendor/aexos-engine-5.3.0/engine/.aexos-core/infrastructure/"
            "tests/worktree-manager.test.js"
        ),
    }
)

_TRANSITIVE_INTEGRITY_MANIFESTS: Final = frozenset(
    {
        "docs/onyx/checkpoints/hud-orb-v7-candidate/manifest.json",
        "docs/onyx/checkpoints/hud-orb-v8-candidate/manifest.json",
        "docs/onyx/checkpoints/phase6-live-wiring-v2/manifest.json",
    }
)
_MANDATORY_RUNTIME_DOCS: Final = frozenset(
    {
        # Operator contract for the optional V15/Phase 11 activation path.
        # The activation module does not read this document at runtime, so it
        # must be declared explicitly instead of relying on AST discovery.
        "docs/onyx/PHASE11_LOCAL_PROJECT_AUDIT_LIVE_V1.md",
        # The mutation slice remains default-off, but its installed-host denial,
        # recovery and cleanup contract must ship with the operator package.
        "docs/onyx/operations/PHASE11_PROJECT_AUTOPILOT_V1_RUNBOOK.md",
        # V18.1's source acceptance and residual fail-closed GC limitation
        # must remain frozen with the runtime that exposes attachment intake.
        "docs/onyx/operations/ONYX_V18_DOCUMENT_INTAKE_ACCEPTANCE_2026-07-31.md",
        "docs/onyx/operations/ONYX_V19_DAYOPS_ACCEPTANCE_2026-07-31.md",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V19-E6-001.md",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V19-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V20-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V21-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V22-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V23-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V24-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V25-E6-001.manifest.json",
        # V9 builds this path from individual Path segments, so AST extraction
        # cannot recover the complete relative name.
        "docs/onyx/checkpoints/onyx-live-activation-v9/runtime-manifest.json",
    }
)

_LEGACY_BRAND = re.compile(
    r"jarvis|j\.a\.r\.v\.i\.s|stark|mark[-_ ]?xlviii|maax assistant",
    re.IGNORECASE,
)
_TEXT_SUFFIXES = frozenset(
    {
        ".cfg",
        ".css",
        ".desktop",
        ".html",
        ".ini",
        ".iss",
        ".js",
        ".json",
        ".md",
        ".plist",
        ".py",
        ".pyw",
        ".qml",
        ".snapshot",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)


class PackageHygieneError(RuntimeError):
    """The staged or built package contains a forbidden artifact."""


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def prune_duplicate_browser_payloads(tree: Path) -> tuple[str, ...]:
    """Remove only Playwright's redundant Chromium headless-shell trees."""

    tree = tree.resolve()
    if not tree.is_dir():
        raise PackageHygieneError(f"package tree is unavailable: {tree}")
    removed: list[str] = []
    candidates = sorted(
        tree.rglob("chromium_headless_shell-*"),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for candidate in candidates:
        relative = candidate.relative_to(tree).as_posix()
        parent_parts = tuple(
            part.casefold() for part in candidate.parent.relative_to(tree).parts
        )
        if parent_parts[-4:] != (
            "playwright",
            "driver",
            "package",
            ".local-browsers",
        ):
            raise PackageHygieneError(f"unsafe duplicate browser payload: {relative}")
        if candidate.is_symlink() or not candidate.is_dir():
            raise PackageHygieneError(f"unsafe duplicate browser payload: {relative}")
        resolved = candidate.resolve()
        if resolved == tree or not resolved.is_relative_to(tree):
            raise PackageHygieneError(f"unsafe duplicate browser payload: {relative}")
        shutil.rmtree(candidate)
        removed.append(relative)
    return tuple(sorted(removed))


def assert_embedded_chromium_runtime(tree: Path) -> None:
    """Require the full bundled Chromium and forbid the duplicate shell."""

    tree = tree.resolve()
    if not tree.is_dir():
        raise PackageHygieneError(f"package tree is unavailable: {tree}")
    browser_roots = tuple(
        item
        for item in tree.rglob(".local-browsers")
        if item.is_dir() and not item.is_symlink()
    )
    full = tuple(
        child
        for root in browser_roots
        for child in root.glob("chromium-*")
        if child.is_dir()
        and not child.is_symlink()
        and not child.name.casefold().startswith("chromium_headless_shell-")
    )
    duplicate = tuple(
        child
        for root in browser_roots
        for child in root.glob("chromium_headless_shell-*")
        if child.exists() or child.is_symlink()
    )
    if duplicate:
        raise PackageHygieneError("duplicate Chromium headless shell remains")
    if not full:
        raise PackageHygieneError("full embedded Chromium runtime is unavailable")
    executable_glob = (
        "chrome-*/chrome.exe"
        if sys.platform == "win32"
        else (
            "chrome-*/Chromium.app/Contents/MacOS/Chromium"
            if sys.platform == "darwin"
            else "chrome-*/chrome"
        )
    )
    executables = tuple(
        executable
        for browser in full
        for executable in browser.glob(executable_glob)
        if executable.is_file()
        and not executable.is_symlink()
        and executable.stat().st_size > 0
    )
    if not executables:
        raise PackageHygieneError("full embedded Chromium executable is unavailable")


def _clean_directory(
    path: Path,
    *,
    protected_root: Path,
    allowed_build_root: Path,
) -> None:
    protected = protected_root.resolve()
    allowed = allowed_build_root.resolve()
    candidate = path.absolute()
    current = allowed_build_root.absolute()
    if _is_link_like(current):
        raise PackageHygieneError(
            f"unsafe linked runtime staging destination: {current}"
        )
    try:
        relative = candidate.relative_to(current)
    except ValueError as exc:
        raise PackageHygieneError(
            f"unsafe runtime staging destination: {candidate}"
        ) from exc
    for component in relative.parts:
        current = current / component
        if _is_link_like(current):
            raise PackageHygieneError(
                f"unsafe linked runtime staging destination: {current}"
            )
    resolved = candidate.resolve(strict=False)
    anchor = Path(resolved.anchor)
    if (
        resolved == anchor
        or resolved == protected
        or protected.is_relative_to(resolved)
        or allowed == Path(allowed.anchor)
        or allowed == protected
        or protected.is_relative_to(allowed)
        or resolved == allowed
        or not resolved.is_relative_to(allowed)
    ):
        raise PackageHygieneError(f"unsafe runtime staging destination: {resolved}")
    if candidate.exists():
        if not candidate.is_dir():
            raise PackageHygieneError(
                f"unsafe runtime staging destination: {candidate}"
            )
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True)


def _copy_relative(root: Path, destination: Path, relative: str) -> None:
    source = root / relative
    if not source.is_file() or source.is_symlink():
        raise PackageHygieneError(f"required runtime input is unavailable: {relative}")
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _assert_exact_capability_sources(root: Path) -> None:
    """Require the closed capability slice and reject undeclared siblings."""

    expected = frozenset(CAPABILITY_RUNTIME_FILES)
    for relative in expected:
        source = root / relative
        if _is_link_like(source) or not source.is_file():
            raise PackageHygieneError(
                f"required capability runtime input is unavailable: {relative}"
            )
        if source.resolve(strict=True) != source.absolute():
            raise PackageHygieneError(
                f"required capability runtime input is linked: {relative}"
            )
    ports = root / "core" / "capability_ports"
    if _is_link_like(ports) or not ports.is_dir():
        raise PackageHygieneError("capability port package is unavailable or linked")
    actual_ports = frozenset(
        source.relative_to(root).as_posix()
        for source in ports.glob("*.py")
        if source.is_file()
    )
    expected_ports = frozenset(
        relative
        for relative in expected
        if relative.startswith("core/capability_ports/")
    )
    if actual_ports != expected_ports:
        raise PackageHygieneError("capability runtime membership drifted")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_compatibility_launcher(root: Path, destination: Path) -> Path:
    """Stage V9's accepted launcher without reading a repository virtualenv."""

    stdlib = Path(sysconfig.get_path("stdlib"))
    installed = stdlib / "venv" / "scripts" / "nt" / "venvwlauncher.exe"
    vendored = root / COMPATIBILITY_LAUNCHER_RELATIVE
    source = next(
        (
            candidate
            for candidate in (installed, vendored)
            if candidate.is_file()
            and not candidate.is_symlink()
            and _sha256(candidate) == COMPATIBILITY_LAUNCHER_SHA256
        ),
        None,
    )
    if source is None:
        raise PackageHygieneError(
            "accepted CPython 3.13 compatibility launcher is unavailable or drifted"
        )
    target = destination / STAGED_COMPATIBILITY_LAUNCHER
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if _sha256(target) != COMPATIBILITY_LAUNCHER_SHA256:
        raise PackageHygieneError("staged compatibility launcher drifted")
    notice = root / COMPATIBILITY_NOTICE_RELATIVE
    if (
        not notice.is_file()
        or notice.is_symlink()
        or _sha256(notice) != COMPATIBILITY_NOTICE_SHA256
    ):
        raise PackageHygieneError(
            "CPython compatibility license is unavailable or drifted"
        )
    staged_notice = destination / STAGED_COMPATIBILITY_NOTICE
    staged_notice.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(notice, staged_notice)
    return target


def stage_runtime_sources(
    root: Path,
    destination: Path,
    *,
    allowed_build_root: Path | None = None,
) -> None:
    """Stage only production Python sources and sealed compatibility inputs."""

    root = root.resolve()
    _assert_exact_capability_sources(root)
    allowed = root / "build" if allowed_build_root is None else allowed_build_root
    _clean_directory(
        destination,
        protected_root=root,
        allowed_build_root=allowed,
    )
    # The frozen bundle exposes these two integrity inputs at its runtime root.
    # Stage them here as well so the packaged HUD verifier evaluates the same
    # layout before PyInstaller runs instead of a partial core/qml surrogate.
    for relative in ("main.py", "ui.py"):
        _copy_relative(root, destination, relative)
    for source in sorted((root / "core").glob("*.py")):
        relative = source.relative_to(root).as_posix()
        if (
            source.is_file()
            and not source.is_symlink()
            and relative not in SOURCE_ONLY_HUD_AUTHORITY_FILES
        ):
            _copy_relative(root, destination, relative)
    for relative in (
        *CAPABILITY_RUNTIME_FILES,
        *RUNTIME_HUD_ACCEPTANCE_MODULES,
        *RUNTIME_HUD_ACCEPTANCE_MANIFESTS,
        PACKAGED_RUNTIME_HUD_CONTRACT_MANIFEST,
        *RUNTIME_SCRIPT_FILES,
        # Three exact, hash-bound historical source receipts are consumed by
        # the immutable V10/V11/V13 activation chain. They are data inputs,
        # never collected/imported as a pytest suite, and are the only allowed
        # first-party files under tests/ in a production package.
        *RUNTIME_TEST_EVIDENCE_FILES,
    ):
        _copy_relative(root, destination, relative)
    for relative in CAPABILITY_RUNTIME_FILES:
        if _sha256(root / relative) != _sha256(destination / relative):
            raise PackageHygieneError(
                f"staged capability runtime input drifted: {relative}"
            )
    qml_source = root / "qml"
    if qml_source.is_symlink() or not qml_source.is_dir():
        raise PackageHygieneError("production QML tree is unavailable")
    for relative in (
        *PACKAGED_QML_RUNTIME_FILES,
        *LIQUID_METAL_RUNTIME_FILES,
        *HUMANOID_PRESENCE_RUNTIME_FILES,
    ):
        _copy_relative(root, destination, relative)
    stage_compatibility_launcher(root, destination)


def _source_doc_references(root: Path) -> set[str]:
    """Collect exact on-disk doc paths referenced by production modules."""

    references: set[str] = set()
    sources = [
        *(
            source
            for source in sorted((root / "core").glob("*.py"))
            if source.relative_to(root).as_posix()
            not in SOURCE_ONLY_HUD_AUTHORITY_FILES
        ),
        root / "main.py",
        root / "ui.py",
        root / "dashboard" / "server.py",
        *(root / relative for relative in RUNTIME_SCRIPT_FILES),
    ]
    for source in sources:
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise PackageHygieneError(
                f"cannot inspect runtime references in {source.relative_to(root)}"
            ) from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value.replace("\\", "/")
            if not value.startswith("docs/onyx/"):
                continue
            candidate = root / value
            if candidate.is_file() and not candidate.is_symlink():
                references.add(value)
    return references


def _manifest_references(root: Path, relative: str) -> set[str]:
    """Return existing first-party files named by a JSON integrity manifest."""

    if not relative.endswith(".json"):
        return set()
    try:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()

    discovered: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(key)
                visit(item)
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, str):
            return
        normalized = value.replace("\\", "/")
        if normalized.startswith(
            ("docs/onyx/", "core/", "scripts/", "tests/", "qml/", "dashboard/")
        ) or normalized in {"main.py", "ui.py"}:
            candidate = root / normalized
            if candidate.is_file() and not candidate.is_symlink():
                discovered.add(normalized)

    visit(payload)
    return discovered


def discover_runtime_docs(root: Path) -> tuple[str, ...]:
    """Resolve the transitive documentation closure used by runtime gates."""

    root = root.resolve()
    pending = list(_source_doc_references(root) | _MANDATORY_RUNTIME_DOCS)
    visited: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in visited:
            continue
        visited.add(relative)
        if relative in _TRANSITIVE_INTEGRITY_MANIFESTS:
            for discovered in _manifest_references(root, relative):
                if discovered.startswith("docs/onyx/") and discovered not in visited:
                    pending.append(discovered)
    return tuple(sorted(visited))


def stage_runtime_docs(
    root: Path,
    destination: Path,
    *,
    allowed_build_root: Path | None = None,
) -> tuple[str, ...]:
    """Stage the exact runtime/preflight documentation closure."""

    root = root.resolve()
    allowed = root / "build" if allowed_build_root is None else allowed_build_root
    _clean_directory(
        destination,
        protected_root=root,
        allowed_build_root=allowed,
    )
    selected = discover_runtime_docs(root)
    for relative in selected:
        stripped = Path(relative).relative_to("docs/onyx").as_posix()
        target = destination / stripped
        target.parent.mkdir(parents=True, exist_ok=True)
        source = root / relative
        if not source.is_file() or source.is_symlink():
            raise PackageHygieneError(
                f"required runtime input is unavailable: {relative}"
            )
        shutil.copy2(source, target)
    return selected


def _logical_path(relative: str) -> str:
    normalized = relative.replace("\\", "/").lstrip("./")
    for marker in (
        "_internal/",
        "Contents/Resources/",
        "Contents/MacOS/",
    ):
        if marker in normalized:
            normalized = normalized.split(marker, 1)[1]
    if normalized.startswith("onyx/"):
        normalized = "docs/" + normalized
    return normalized


def _is_exception(logical: str) -> bool:
    return logical in AEXOS_ATTESTED_MANIFEST_FILES or any(
        logical.endswith(item) for item in COMPATIBILITY_EXCEPTIONS
    )


def _is_first_party(logical: str) -> bool:
    return logical.startswith(
        (
            "core/",
            "dashboard/",
            "docs/onyx/",
            "qml/",
            "scripts/",
            "tests/",
        )
    ) or logical in {"main.py", "ui.py"}


def sensitive_path_reason(relative: str) -> str | None:
    """Classify machine-local credential, backup and diagnostic paths.

    This check is deliberately path-only.  It must run before any text scan so
    a package gate never opens a credential store merely to decide that the
    file is forbidden.
    """

    normalized = relative.replace("\\", "/").strip("/").casefold()
    parts = tuple(part for part in normalized.split("/") if part)
    directories = parts[:-1]
    if any(part.startswith("user-data-pre-") for part in parts):
        return "machine-local user-data backup"
    if "runtime/phase6-live-wiring-v1/sessions/" in f"{normalized}/":
        return "mutable Phase 6 session state"
    if any(part.startswith("onyx-") and "-diag-" in part for part in directories):
        return "machine-local diagnostic capture"
    if normalized.endswith("config/api_keys.json"):
        return "credential store"
    if normalized.endswith("config/certs/onyx.key"):
        return "private key"
    return None


def assert_safe_build_input_paths(paths: Iterable[Path], root: Path) -> None:
    """Reject sensitive path classes before a build tool can consume them."""

    resolved_root = root.resolve()
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise PackageHygieneError(
                f"build input escaped project root: {resolved}"
            ) from exc
        reason = sensitive_path_reason(relative)
        if reason is not None:
            raise PackageHygieneError(
                f"sensitive path entered build inputs: {relative}: {reason}"
            )


def package_hygiene_violations(tree: Path) -> tuple[str, ...]:
    """Return deterministic violations for a staged or built directory tree."""

    tree = tree.resolve()
    violations: list[str] = []
    if not tree.is_dir():
        return (f"package tree is unavailable: {tree}",)
    for path in sorted(item for item in tree.rglob("*") if item.is_file()):
        relative = path.relative_to(tree).as_posix()
        logical = _logical_path(relative)
        lowered = logical.casefold()
        parts = lowered.split("/")
        name = parts[-1]
        exception = _is_exception(logical)

        reason = sensitive_path_reason(relative)
        if reason is not None:
            pass
        elif "__pycache__" in parts or name.endswith((".pyc", ".pyo")):
            reason = "Python cache"
        elif name.endswith((".log", ".junit.xml", ".bundle.json")) and not exception:
            reason = "development evidence"
        elif name.startswith("pytest") and name.endswith((".zip", ".tar", ".tar.gz")):
            reason = "pytest runtime archive"
        elif any(part in {".pytest_cache", ".ruff_cache"} for part in parts):
            reason = "tool cache"
        elif any(part.startswith("chromium_headless_shell-") for part in parts):
            reason = "duplicate browser payload"
        elif (
            any(part in {"test", "tests", "testing"} for part in parts)
            or name == "conftest.py"
            or name.startswith(("test_", "_test_"))
        ) and not exception:
            reason = (
                "development-only source"
                if _is_first_party(logical)
                else "third-party development payload"
            )
        elif "docs/onyx/corrections/" in lowered and not exception:
            reason = "correction history"
        elif "docs/onyx/operations/" in lowered and not exception:
            reason = "operations history"
        elif "docs/onyx/research/" in lowered and not exception:
            reason = "research history"
        elif "docs/onyx/rejections/" in lowered and not exception:
            reason = "rejection history"
        elif "/scripts/build_" in f"/{lowered}" or lowered.startswith("scripts/build_"):
            reason = "build evidence script"
        elif (
            (
                lowered.startswith("scripts/capture_")
                or lowered.startswith("scripts/verify_")
            )
            and _is_first_party(logical)
            and not exception
        ):
            reason = "development-only source"

        if (
            reason is None
            and not exception
            and _is_first_party(logical)
            and path.suffix.casefold() in _TEXT_SUFFIXES
        ):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                text = ""
            if _LEGACY_BRAND.search(text):
                reason = "legacy brand token"
        if reason is not None:
            violations.append(f"{logical}: {reason}")
    return tuple(violations)


def assert_package_hygiene(tree: Path) -> None:
    violations = package_hygiene_violations(tree)
    if violations:
        raise PackageHygieneError(
            "production package hygiene failed:\n- " + "\n- ".join(violations)
        )


__all__ = [
    "AEXOS_ATTESTED_MANIFEST_FILES",
    "COMPATIBILITY_EXCEPTIONS",
    "CAPABILITY_RUNTIME_FILES",
    "LIQUID_METAL_RUNTIME_FILES",
    "HUMANOID_PRESENCE_RUNTIME_FILES",
    "COMPATIBILITY_LAUNCHER_RELATIVE",
    "COMPATIBILITY_LAUNCHER_SHA256",
    "COMPATIBILITY_NOTICE_RELATIVE",
    "COMPATIBILITY_NOTICE_SHA256",
    "PackageHygieneError",
    "RUNTIME_SCRIPT_FILES",
    "RUNTIME_HUD_ACCEPTANCE_MANIFESTS",
    "RUNTIME_HUD_ACCEPTANCE_MODULES",
    "RUNTIME_HUD_PREDECESSOR_INPUTS",
    "RUNTIME_TEST_EVIDENCE_FILES",
    "SOURCE_ONLY_HUD_AUTHORITY_FILES",
    "STAGED_COMPATIBILITY_LAUNCHER",
    "STAGED_COMPATIBILITY_NOTICE",
    "assert_safe_build_input_paths",
    "assert_package_hygiene",
    "assert_embedded_chromium_runtime",
    "discover_runtime_docs",
    "package_hygiene_violations",
    "prune_duplicate_browser_payloads",
    "stage_runtime_docs",
    "stage_runtime_sources",
    "stage_compatibility_launcher",
    "sensitive_path_reason",
]
