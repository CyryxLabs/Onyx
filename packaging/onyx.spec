# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata


ROOT = Path(SPECPATH).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.runtime_distribution_inventory import runtime_distribution_closure
from core.onyx_packaged_runtime_hud_contract_v1 import RUNTIME_TEST_EVIDENCE_FILES

ASSETS = ROOT / "build" / "assets"
RUNTIME_DOCS = ROOT / "build" / "runtime-docs" / "onyx"
RUNTIME_SOURCES = ROOT / "build" / "runtime-sources"
HUD_ACCEPTANCE_MANIFESTS = tuple(
    f"VE-HUD-CURRENT-V{version}-E6-001.manifest.json"
    for version in range(20, 26)
)
VERSION = os.environ.get("ONYX_BUILD_VERSION", "1.1.20")
MACOS_MINIMUM_VERSION = os.environ.get("MACOSX_DEPLOYMENT_TARGET", "15.0")
if sys.platform == "darwin" and MACOS_MINIMUM_VERSION != "15.0":
    raise RuntimeError("Onyx 1.1.20 supports macOS 15.0+; deployment target drifted")

datas = [
    # Source bytes below are immutable integrity inputs read by the accepted
    # Phase 6 verifier. Runtime imports still use the compiled PYZ modules.
    (str(ROOT / "main.py"), "."),
    (str(ROOT / "ui.py"), "."),
    (str(ROOT / "dashboard" / "server.py"), "dashboard"),
    (str(RUNTIME_SOURCES / "core"), "core"),
    (str(RUNTIME_SOURCES / "scripts"), "scripts"),
    # Exact hash-bound V10/V11/V13 source receipts are appended individually
    # below. Never copy a broad development tests directory into production.
    (str(RUNTIME_DOCS), "docs/onyx"),
    # V9's accepted runtime manifest binds this launcher by hash. The build
    # stages the CPython 3.13 compatibility asset without requiring a local
    # repository virtualenv.
    # It is retained only as immutable compatibility evidence; the packaged
    # application executes through Onyx.exe and never activates this file.
    (
        str(RUNTIME_SOURCES / ".venv" / "Scripts" / "pythonw.exe"),
        ".venv/Scripts",
    ),
    (
        str(RUNTIME_SOURCES / ".venv" / "PSF-LICENSE.txt"),
        ".venv",
    ),
    (str(ROOT / "core" / "prompt.txt"), "core"),
    (str(ROOT / "dashboard" / "static"), "dashboard/static"),
    (str(RUNTIME_SOURCES / "qml"), "qml"),
    (str(ASSETS / "onyx.ico"), "assets"),
    (str(ASSETS / "onyx.icns"), "assets"),
    (str(ASSETS / "onyx.png"), "assets"),
    (
        str(ROOT / "packaging" / "macos" / "labs.cyryx.onyx.plist"),
        "autostart",
    ),
]
datas += [
    (
        str(RUNTIME_SOURCES / Path(relative)),
        str(Path(relative).parent).replace("\\", "/"),
    )
    for relative in RUNTIME_TEST_EVIDENCE_FILES
]
datas += [
    (
        str(RUNTIME_DOCS / "acceptance" / manifest),
        "docs/onyx/acceptance",
    )
    for manifest in HUD_ACCEPTANCE_MANIFESTS
]
binaries = []
hiddenimports = []


def _is_development_payload(entry):
    """Reject test/tooling files copied as package data by collect_all()."""

    source_name = Path(str(entry[0])).name.casefold()
    destination = str(entry[1]).replace("\\", "/").casefold()
    parts = [part for part in destination.split("/") if part]
    name = source_name
    return (
        any(
            part in {
                ".pytest_cache",
                ".ruff_cache",
                "__pycache__",
                "test",
                "tests",
                "testing",
            }
            for part in parts
        )
        or any(part.startswith("chromium_headless_shell-") for part in parts)
        or name == "conftest.py"
        or name.startswith(("test_", "_test_"))
        or name.endswith((".pyc", ".pyo"))
    )


def _is_development_module(name):
    parts = [part.casefold() for part in name.split(".") if part]
    return any(
        part in {"test", "tests", "testing"}
        or part.startswith(("test_", "_test_"))
        for part in parts
    )


def _append_runtime_tree(source, destination, retained_development_paths=frozenset()):
    """Append a runtime tree file-by-file so development payload is excluded."""

    if not source.is_dir():
        raise RuntimeError(f"required runtime tree is unavailable: {source}")
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        target = str(Path(destination) / relative.parent).replace("\\", "/")
        entry = (str(path), target)
        if (
            relative.as_posix() in retained_development_paths
            or not _is_development_payload(entry)
        ):
            datas.append(entry)


# Cyryx-owned, exact-version AEXOS sidecar. The engine bytes retain their own
# license and the runtime tree retains every dependency/Node notice, while
# package tests and caches never enter the production bundle. Five inert files
# remain because the exact AEXOS install manifest attests them by path/hash.
_AEXOS_VENDOR = ROOT / "vendor" / "aexos-engine-5.3.0"
_AEXOS_ATTESTED_MANIFEST_FILES = frozenset(
    {
        (
            ".aexos-core/development/templates/squad-template/tests/"
            "example-agent.test.js"
        ),
        ".aexos-core/infrastructure/tests/project-status-loader.test.js",
        ".aexos-core/infrastructure/tests/regression-suite-v2.md",
        ".aexos-core/infrastructure/tests/validate-module.js",
        ".aexos-core/infrastructure/tests/worktree-manager.test.js",
    }
)
_append_runtime_tree(
    _AEXOS_VENDOR / "engine",
    "vendor/aexos-engine-5.3.0/engine",
    retained_development_paths=_AEXOS_ATTESTED_MANIFEST_FILES,
)
_append_runtime_tree(
    _AEXOS_VENDOR / "runtime", "vendor/aexos-engine-5.3.0/runtime"
)
_append_runtime_tree(
    _AEXOS_VENDOR / "node", "vendor/aexos-engine-5.3.0/node"
)


for package in ("playwright", "google.genai", "uvicorn", "qrcode", "tzdata"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += [item for item in package_datas if not _is_development_payload(item)]
    binaries += [
        item for item in package_binaries if not _is_development_payload(item)
    ]
    hiddenimports += [
        name
        for name in package_hidden
        if not _is_development_module(name)
    ]

hiddenimports += collect_submodules("actions")
hiddenimports += collect_submodules("memory")
hiddenimports += collect_submodules("dashboard")
hiddenimports += [
    "core.capability_composition_v1",
    "core.capability_ports",
    "core.capability_ports.argos_v1",
    "core.capability_ports.budget_v1",
    "core.capability_ports.command_center_v1",
    "core.capability_ports.evidence_v1",
    "core.capability_ports.google_workspace_v1",
    "core.capability_ports.graph_v1",
    "core.capability_ports.guild_v1",
    "core.capability_ports.intelligence_v1",
    "core.capability_ports.knowledge_refinery_v1",
    "core.capability_ports.mission_context_v1",
    "core.capability_ports.model_router_v1",
    "core.capability_ports.nexus_v1",
    "core.capability_ports.plugin_v1",
    "core.capability_ports.project_execution_v1",
    "core.capability_ports.social_v1",
    "core.capability_ports.strategy_v1",
    "core.capability_ports.unified_router_v1",
    "core.capability_ports.workspace_v1",
    "core.governed_capability_host_v1",
    "scripts.onyx_capabilities_cli",
    "core.governance_nucleus_v1",
    "core.onyx_live_activation_v16",
    "core.founder_snapshot_live_v1",
    "core.onyx_live_activation_v17",
    "core.onyx_live_activation_v18",
    "core.onyx_live_activation_v19",
    "core.onyx_live_activation_v20",
    "core.onyx_live_activation_v21",
    "core.onyx_live_activation_v22",
    "core.onyx_live_activation_v23",
    "core.onyx_live_activation_v24",
    "core.owner_context_controller_v1",
    "core.owner_context_profile_v1",
    "core.operational_event_bridge_v1",
    "core.operational_event_controller_v1",
    "core.advanced_operations_live_v1",
    "core.advanced_operations_controller_v1",
    "core.operational_goals_v1",
    "core.governed_automation_v1",
    "core.event_awareness_v1",
    "core.device_mesh_v1",
    "core.device_mesh_https_v1",
    "core.device_pairing_v1",
    "core.official_messaging_v1",
    "core.site_recipe_catalog_v1",
    "core.portable_accessibility_actions_v1",
    "core.content_lifecycle_projection_v1",
    "core.personality_preferences_v1",
    "core.site_projects_v1",
    "core.automation_adapters_v1",
    "core.native_workspace_events_v1",
    "scripts.missing_distribution_license_bundle",
    "core.onyx_portable_current_activation_v1",
    "core.onyx_hud_current_acceptance_v19",
    "core.onyx_hud_current_acceptance_v20",
    "core.onyx_hud_current_acceptance_v21",
    "core.onyx_hud_current_acceptance_v22",
    "core.onyx_hud_current_acceptance_v23",
    "core.onyx_hud_current_acceptance_v24",
    "core.onyx_hud_current_acceptance_v25",
    "core.onyx_hud_current_acceptance_v32",
    "core.onyx_hud_current_acceptance_v35",
    "core.onyx_hud_current_acceptance_v36",
    "core.onyx_hud_current_acceptance_v37",
    "core.onyx_hud_current_acceptance_v38",
    "core.onyx_hud_current_acceptance_v39",
    "core.onyx_hud_current_acceptance_v40",
    "core.onyx_hud_current_acceptance_v41",
    "core.onyx_hud_current_acceptance_v43",
    "core.onyx_hud_current_acceptance_v44",
    "core.onyx_hud_current_acceptance_v45",
    "core.onyx_hud_current_acceptance_v46",
    "core.onyx_hud_current_acceptance_v47",
    "core.onyx_hud_current_acceptance_v48",
    "core.onyx_hud_orb_v17",
    "core.network_guardian_v1",
    "core.social_official_adapter_v1",
    "core.graph_refresh_vault_v2",
    "core.phase8_microsoft_graph_oauth_v2",
    "core.onyx_packaged_runtime_hud_contract_v16",
    "core.onyx_packaged_runtime_hud_contract_v17",
    "core.onyx_packaged_runtime_hud_contract_v1",
    "core.onyx_packaged_runtime_hud_contract_v4",
    "core.onyx_packaged_runtime_hud_contract_v5",
    "core.onyx_packaged_runtime_hud_contract_v6",
    "core.onyx_packaged_runtime_hud_contract_v7",
    "core.onyx_packaged_runtime_hud_contract_v8",
    "core.onyx_packaged_runtime_hud_contract_v9",
    "core.onyx_packaged_runtime_hud_contract_v10",
    "core.onyx_packaged_runtime_hud_contract_v12",
    "core.onyx_packaged_runtime_hud_contract_v13",
    "core.onyx_packaged_runtime_hud_contract_v14",
    "core.onyx_packaged_runtime_hud_contract_v15",
    "core.camera_gesture_attention_v1",
    "core.spoken_language_memory_v1",
    "core.assistant_identity_profile_v1",
    "core.live_voice_preference_v1",
    "core.audio_device_selection_v1",
    "core.social_content_strategy_v1",
    "core.capability_parity_v1",
    "core.vision_repetition_counter_v1",
    "core.wellness_tracker_v1",
    "core.continuous_learning_v1",
    "core.governed_personalization_v1",
    "core.aexos_engine_adapter_v1",
    "core.aexos_department_router_v1",
    "core.opportunity_economics_v1",
    "core.opportunity_queue_v1",
    "core.opportunity_monitor_v1",
    "core.web_opportunity_research_v1",
    "scripts.onyx_identity_cli",
    "scripts.onyx_audio_cli",
    "core.undo_journal_v1",
    "scripts.onyx_parity_cli",
    "scripts.onyx_social_cli",
    "scripts.onyx_personal_tools_cli",
    "scripts.onyx_learning_cli",
    "scripts.onyx_agentic_cli",
    "scripts.onyx_plugin_cli",
    "core.onyx_hud_orb_v10",
    "core.onyx_hud_orb_v11",
    "core.onyx_hud_orb_v12",
    "core.onyx_hud_orb_v13",
    "core.onyx_hud_orb_v14",
    "core.onyx_hud_orb_v15",
    "core.onyx_hud_orb_v16",
    "core.document_intake_live_v1",
    "core.dayops_profile_v19",
    "core.dayops_graph_factory_v19",
    "core.dayops_identity_provisioning_v19",
    "core.dayops_connection_v19",
    "core.native_startup_smoke_v1",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
]
if sys.platform == "win32":
    # Phase 11's executable sandbox imports these only inside its Windows
    # ownership/ACL boundary, so PyInstaller cannot discover them statically.
    # ``win32timezone`` is imported dynamically by pywintypes while the frozen
    # V15 host probes the pinned external-agent executables.
    hiddenimports += [
        "ntsecuritycon",
        "win32api",
        "win32con",
        "win32file",
        "win32pipe",
        "win32security",
        "win32timezone",
    ]

for distribution in runtime_distribution_closure(ROOT / "requirements.txt"):
    # Preserve exact wheel metadata and every upstream license file supplied by
    # that wheel. Missing metadata is a build error, not a silent omission.
    datas += copy_metadata(distribution.metadata["Name"])

icon = ASSETS / ("onyx.ico" if sys.platform == "win32" else "onyx.icns")
version_file = ASSETS / "version_info.txt" if sys.platform == "win32" else None

a = Analysis(
    [str(ROOT / "scripts" / "bootstrap_onyx.pyw")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt6",
        "pytest",
        # Onyx speech identity is Gemini Live/Charon only.  These legacy/local
        # synthesizers must never enter the production dependency graph.
        "edge_tts",
        "elevenlabs",
        "kokoro",
        # Undeclared packages from the developer's global Python environment
        # are discovered through optional imports/hooks but are not production
        # Onyx dependencies. Gemini Live owns speech, and the declared document
        # stack does not require these ML/test payloads.
        "torch",
        "transformers",
        "sklearn",
        "nltk",
        "pyarrow",
        "scipy",
        "matplotlib",
        "tensorboard",
        # MouseInfo is an optional GPL utility imported behind PyAutoGUI's
        # guarded `mouseInfo()` helper. Onyx never exposes that helper; keeping
        # it out preserves every automation action without distributing the
        # unrelated GPL application.
        "mouseinfo",
        "pyttsx3",
        "google.genai._test_api_client",
        "google.genai.tests",
        "qrcode.tests",
    ],
    noarchive=False,
    optimize=1,
)
if sys.platform == "win32":
    # QtCore binds the system ICU supplied by supported Windows hosts. Never
    # let PyInstaller capture an unrelated unversioned ICU from an ambient
    # Poppler/toolchain PATH; it shadows System32 and breaks QtCore at import.
    _forbidden_windows_qt_icu = {"icuuc.dll", "icudt78.dll"}
    a.binaries = [
        entry
        for entry in a.binaries
        if Path(str(entry[0])).name.casefold() not in _forbidden_windows_qt_icu
    ]
pyz = PYZ(a.pure)

# The installed DayOps provisioner is a deliberately small, console-enabled
# one-file helper. It carries only the four accepted Phase 7 alias-entry
# evidence files required by the sealed catalog; it does not import or alter
# the graphical Onyx entrypoint.
dayops_entry_datas = [
    (
        str(ROOT / "docs" / "onyx" / "checkpoints" / "phase7-workspace-memory-v1" / "manifest.json"),
        "docs/onyx/checkpoints/phase7-workspace-memory-v1",
    ),
    (
        str(ROOT / "docs" / "onyx" / "acceptance" / "VE-P7-WORKSPACE-MEMORY-V1-E6-001.md"),
        "docs/onyx/acceptance",
    ),
    (
        str(ROOT / "docs" / "onyx" / "acceptance" / "VE-P7-WORKSPACE-MEMORY-V1-E6-001.manifest.json"),
        "docs/onyx/acceptance",
    ),
    (
        str(ROOT / "docs" / "onyx" / "VE-ACCEPTANCE-P7-WORKSPACE-MEMORY-V1-E6-001.sha256"),
        "docs/onyx",
    ),
]
dayops_a = Analysis(
    [str(ROOT / "scripts" / "provision_dayops_v14.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=dayops_entry_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt6", "PySide6", "pytest"],
    noarchive=False,
    optimize=1,
)
dayops_pyz = PYZ(dayops_a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Onyx",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon),
    version=str(version_file) if version_file else None,
)

dayops_exe = EXE(
    dayops_pyz,
    dayops_a.scripts,
    dayops_a.binaries,
    dayops_a.datas,
    [],
    name="Onyx-DayOps",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon),
    version=str(version_file) if version_file else None,
)

bundle = COLLECT(
    exe,
    dayops_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Onyx",
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle,
        name="Onyx.app",
        icon=str(icon),
        bundle_identifier="labs.cyryx.onyx",
        info_plist={
            "CFBundleName": "Onyx",
            "CFBundleDisplayName": "Onyx",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": MACOS_MINIMUM_VERSION,
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "Onyx uses the microphone for real-time voice interaction.",
            "NSCameraUsageDescription": "Onyx uses the camera only when the owner requests visual assistance.",
            "NSScreenCaptureUsageDescription": "Onyx captures the screen only when the owner requests visual assistance.",
        },
    )
