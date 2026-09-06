"""Closed, evidence-backed Onyx capability parity registry.

This registry reports local implementation coverage only. Packaging,
installation, physical-device behavior, and live providers are supplied as
separate evidence sets and can never be inferred from source files.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib
import importlib.util
import os
from pathlib import Path
import sys
from typing import Final, Iterable


class CapabilityParityError(RuntimeError):
    """The parity registry or its evidence is incomplete."""


@dataclass(frozen=True, slots=True)
class CapabilityParityRowV1:
    capability_id: str
    evidence: tuple[str, ...]
    test_evidence: tuple[str, ...]
    host_surface: str
    live_dependency: str = "none"
    source_state: str = "implemented"
    test_state: str = "declared-not-run-in-report"
    package_state: str = "pending-successor"
    installed_state: str = "pending-successor"
    device_account_state: str = "not-applicable"
    live_provider_state: str = "not-applicable"


def _row(
    capability_id: str,
    evidence: tuple[str, ...],
    tests: tuple[str, ...],
    host_surface: str = "voice-and-local-host",
    live_dependency: str = "none",
) -> CapabilityParityRowV1:
    return CapabilityParityRowV1(capability_id, evidence, tests, host_surface, live_dependency)


CAPABILITIES: Final = (
    _row("plugin_system", ("core/plugin_runtime_v1.py", "scripts/onyx_plugin_cli.py"), ("tests/test_plugin_runtime_v1.py",), "governed-cli-and-host", "certified-native-sandbox"),
    _row("real_time_voice", ("main.py", "core/audio_contract.py"), ("tests/test_original_voice_contract_v1.py",), live_dependency="gemini-live-and-audio-device"),
    _row("affective_dialog", ("core/enhanced_live_audio_v1.py", "main.py"), ("tests/test_enhanced_live_audio_v1.py",), live_dependency="supported-gemini-live-preview"),
    _row("proactive_audio", ("core/enhanced_live_audio_v1.py", "main.py"), ("tests/test_enhanced_live_audio_v1.py",), live_dependency="supported-gemini-live-preview"),
    _row("unlimited_sessions", ("core/session_continuity_v1.py", "core/live_voice_continuity_v1.py"), ("tests/test_session_continuity_v1.py", "tests/test_live_voice_continuity_v1.py"), live_dependency="gemini-live"),
    _row("system_control", ("actions/computer_control.py", "actions/computer_settings.py", "actions/open_app.py"), ("tests/test_regressions.py",)),
    _row("autonomous_tasks", ("core/phase11_live_mission_v1.py", "core/phase11_project_autopilot_v1.py"), ("tests/test_phase11_live_mission_v1.py", "tests/test_phase11_project_autopilot_v1.py"), "governed-mission-host"),
    _row("visual_awareness", ("actions/screen_processor.py", "core/camera_gesture_attention_v1.py"), ("tests/test_camera_gesture_attention_v1.py",), live_dependency="screen-camera-owner-consent"),
    _row("persistent_memory", ("memory/memory_manager.py", "core/phase7_workspace_memory_v1.py"), ("tests/test_memory_store.py", "tests/test_phase7_workspace_memory_v1.py")),
    _row("hybrid_input", ("main.py", "ui.py"), ("tests/test_regressions.py",), "accepted-hud-host"),
    _row("morning_briefing", ("main.py",), ("tests/test_regressions.py",), live_dependency="news-provider"),
    _row("proactive_checkins", ("actions/proactive.py", "main.py"), ("tests/test_regressions.py",)),
    _row("session_memory", ("memory/memory_manager.py", "core/session_continuity_v1.py"), ("tests/test_session_continuity_v1.py",)),
    _row("background_monitoring", ("actions/reminder.py", "main.py"), ("tests/test_regressions.py",), live_dependency="web-search"),
    _row("hardware_monitoring", ("actions/system_monitor.py", "main.py"), ("tests/test_regressions.py",), live_dependency="host-sensors"),
    _row("weather_report", ("actions/weather_report.py",), ("tests/test_regressions.py",), live_dependency="weather-provider"),
    _row("dynamic_content_panel", ("ui.py", "dashboard/server.py"), ("tests/test_regressions.py",), "accepted-hud-and-dashboard"),
    _row("multi_mode_web_search", ("actions/web_search.py", "core/phase6_research_cells_v1.py"), ("tests/test_phase6_research_cells_v1.py",), live_dependency="web-providers"),
    _row("smart_reminders", ("actions/reminder.py",), ("tests/test_regressions.py",), live_dependency="os-scheduler"),
    _row("flight_finder", ("actions/flight_finder.py",), ("tests/test_regressions.py",), live_dependency="flight-provider"),
    _row("game_updater", ("actions/game_updater.py",), ("tests/test_regressions.py",), live_dependency="installed-game-client"),
    _row("file_processor", ("actions/file_processor.py",), ("tests/test_regressions.py",)),
    _row("code_helper", ("actions/code_helper.py", "actions/dev_agent.py"), ("tests/test_regressions.py",), live_dependency="configured-model"),
    _row("browser_control", ("actions/browser_control.py",), ("tests/test_regressions.py",), live_dependency="installed-browser"),
    _row("send_message", ("actions/send_message.py", "core/official_messaging_v1.py"), ("tests/test_official_messaging_v1.py",), live_dependency="authorized-messaging-account"),
    _row("youtube_control", ("actions/youtube_video.py",), ("tests/test_youtube_video_behavior.py",), live_dependency="youtube-and-browser"),
    _row("desktop_control", ("actions/desktop.py", "actions/computer_control.py"), ("tests/test_desktop_path_resolution.py",)),
    _row("silent_language_memory", ("core/spoken_language_memory_v1.py", "main.py", "scripts/onyx_identity_cli.py"), ("tests/test_spoken_language_memory_v1.py",), "voice-text-and-cli"),
    _row("remote_dashboard", ("dashboard/server.py", "dashboard/security.py"), ("tests/test_dashboard_upload_security.py",), "authenticated-dashboard", "lan-device-pairing"),
    _row("auto_start", ("core/autostart_registration_v1.py",), ("tests/test_cross_platform_autostart_v1.py",), live_dependency="os-startup-registration"),
    _row("clipboard_intelligence", ("core/clipboard_intelligence_v1.py", "core/capability_expansion_service_v1.py"), ("tests/test_clipboard_intelligence_v1.py",), "explicit-gesture-host"),
    _row("assistant_customization", ("core/assistant_identity_profile_v1.py", "main.py", "scripts/onyx_identity_cli.py"), ("tests/test_assistant_identity_profile_v1.py",), "voice-text-and-cli"),
    _row("repetition_counter", ("core/vision_repetition_counter_v1.py", "core/capability_expansion_service_v1.py"), ("tests/test_vision_repetition_counter_v1.py",), "camera-signal-and-cli", "physical-camera-calibration"),
    _row("video_upload", ("core/social_video_asset_v1.py", "core/social_publish_v1.py", "scripts/onyx_social_cli.py"), ("tests/test_social_video_asset_v1.py", "tests/test_social_publish_v1.py"), "governed-cli", "official-provider-oauth-and-test-account"),
    _row("calorie_tracker", ("core/wellness_tracker_v1.py", "scripts/onyx_personal_tools_cli.py"), ("tests/test_wellness_tracker_v1.py",), "governed-cli-and-host"),
    _row("live_voice_selection", ("core/live_voice_preference_v1.py", "main.py", "scripts/onyx_audio_cli.py"), ("tests/test_mark_lii_audio_parity_v1.py", "tests/test_live_voice_continuity_v1.py"), "voice-text-and-cli", "gemini-live"),
    _row("audio_device_selection", ("core/audio_device_selection_v1.py", "main.py", "scripts/onyx_audio_cli.py"), ("tests/test_mark_lii_audio_parity_v1.py", "tests/test_live_audio_stream_ownership_v1.py"), "voice-runtime-and-cli", "physical-audio-device"),
    _row("owner_memory_control", ("memory/memory_manager.py",), ("tests/test_memory_store.py", "tests/test_mark_lii_undo_confirmation_parity_v1.py"), "owner-cli-and-voice"),
    _row("bounded_undo", ("core/undo_journal_v1.py", "actions/file_controller.py", "actions/computer_settings.py", "main.py"), ("tests/test_mark_lii_undo_confirmation_parity_v1.py",), "voice-and-local-host"),
    _row("owner_confirmation", ("core/permission_broker.py", "main.py"), ("tests/test_mark_lii_undo_confirmation_parity_v1.py", "tests/test_regressions.py"), "trusted-local-host"),
    _row("local_action_resolution", ("actions/computer_settings.py", "main.py"), ("tests/test_mark_lii_undo_confirmation_parity_v1.py",), "voice-and-local-host"),
    _row("unicode_safe_diagnostics", ("main.py",), ("tests/test_mark_lii_undo_confirmation_parity_v1.py",), "windows-runtime"),
)

REFERENCE_REPOSITORY: Final = "https://github.com/FatihMakes/Mark-LI.git"
REFERENCE_HEAD: Final = "234dd792737f3acd38ca836aadae94c24ef0ad56"
REFERENCE_FUNCTIONAL_PARENT: Final = "c131a1b4f72e477bd4c6735142f3aaee36acc792"
OWNER_EXCLUDED_VISUAL_CAPABILITIES: Final = (
    "reference-orb",
    "reference-layout",
    "live-theme-redesign",
    "reference-boot-visual",
)

PACKAGED_RUNTIME_MODULES: Final = (
    "core.assistant_identity_profile_v1",
    "core.capability_parity_v1",
    "core.social_content_strategy_v1",
    "core.spoken_language_memory_v1",
    "core.live_voice_preference_v1",
    "core.audio_device_selection_v1",
    "core.undo_journal_v1",
    "core.vision_repetition_counter_v1",
    "core.wellness_tracker_v1",
    "scripts.onyx_identity_cli",
    "scripts.onyx_parity_cli",
    "scripts.onyx_personal_tools_cli",
    "scripts.onyx_plugin_cli",
    "scripts.onyx_social_cli",
    "scripts.onyx_audio_cli",
)


def _normalized(paths: Iterable[str]) -> frozenset[str]:
    return frozenset(str(Path(item)).replace("\\", "/") for item in paths)


def _module_name_from_evidence(relative: str) -> str:
    path = Path(relative)
    if path.suffix != ".py" or "tests" in path.parts:
        raise CapabilityParityError(
            f"runtime parity evidence is not an importable module: {relative}"
        )
    return ".".join(path.with_suffix("").parts)


def validate_source_parity_v1(root: Path | str) -> dict[str, object]:
    base = Path(root).resolve()
    identifiers = [row.capability_id for row in CAPABILITIES]
    if len(identifiers) != len(set(identifiers)):
        raise CapabilityParityError("capability registry contains duplicate identifiers")
    missing: list[str] = []
    for row in CAPABILITIES:
        for relative in (*row.evidence, *row.test_evidence):
            path = base / relative
            if not path.is_file():
                missing.append(relative)
    if missing:
        raise CapabilityParityError(f"parity evidence is missing: {sorted(set(missing))}")
    return {
        "schema": "onyx.capability-parity/v1",
        "reference_repository": REFERENCE_REPOSITORY,
        "reference_head": REFERENCE_HEAD,
        "reference_functional_parent": REFERENCE_FUNCTIONAL_PARENT,
        "owner_excluded_visual_capabilities": OWNER_EXCLUDED_VISUAL_CAPABILITIES,
        "source_contract_coverage_percent": 100.0,
        "capability_count": len(CAPABILITIES),
        "missing_evidence": [],
        "capabilities": [asdict(row) for row in CAPABILITIES],
        "evidence_files": sorted(_normalized(
            relative for row in CAPABILITIES for relative in (*row.evidence, *row.test_evidence)
        )),
        "package_verified": False,
        "installed_verified": False,
        "live_provider_verified": False,
        "operational_parity_certified": False,
        "evidence_limit": "Source-contract coverage does not prove package, installation, device, OAuth, account, or live-provider behavior.",
    }


def validate_packaged_parity_v1(root: Path | str) -> dict[str, object]:
    """Prove the capability registry is executable from frozen package bytes.

    Source tests are intentionally absent from production packages. Their source
    gate runs before freezing; this gate resolves every declared runtime evidence
    module through the frozen importer and rejects any origin outside ``_MEIPASS``.
    """

    if not getattr(sys, "frozen", False):
        raise CapabilityParityError("packaged parity requires a frozen Onyx executable")
    base = Path(root).resolve(strict=True)
    frozen_root = Path(getattr(sys, "_MEIPASS", "")).resolve(strict=True)
    if base != frozen_root:
        raise CapabilityParityError("packaged parity root is not the frozen runtime root")
    identifiers = [row.capability_id for row in CAPABILITIES]
    if len(identifiers) != len(set(identifiers)):
        raise CapabilityParityError("capability registry contains duplicate identifiers")
    runtime_modules = {
        _module_name_from_evidence(relative)
        for row in CAPABILITIES
        for relative in row.evidence
    }
    origins: dict[str, str] = {}
    for module_name in sorted(runtime_modules | set(PACKAGED_RUNTIME_MODULES)):
        spec = importlib.util.find_spec(module_name)
        if spec is None or not spec.origin:
            raise CapabilityParityError(
                f"packaged parity module is unavailable: {module_name}"
            )
        # PYZ modules expose a trusted virtual origin below ``_MEIPASS``; the
        # individual ``.py`` path need not exist on disk. ``find_spec`` proves
        # the frozen loader owns it, while the lexical boundary blocks host
        # or checkout fallbacks.
        origin = Path(str(spec.origin)).resolve(strict=False)
        if module_name in PACKAGED_RUNTIME_MODULES:
            module = importlib.import_module(module_name)
            imported_origin = Path(
                str(getattr(module, "__file__", ""))
            ).resolve(strict=False)
            if imported_origin != origin:
                raise CapabilityParityError(
                    f"packaged parity import origin drifted: {module_name}"
                )
        try:
            origin.relative_to(frozen_root)
        except ValueError as exc:
            raise CapabilityParityError(
                f"packaged parity module escaped frozen runtime: {module_name}"
            ) from exc
        origins[module_name] = os.path.relpath(origin, frozen_root).replace("\\", "/")
    return {
        "schema": "onyx.capability-parity/v1",
        "reference_repository": REFERENCE_REPOSITORY,
        "reference_head": REFERENCE_HEAD,
        "reference_functional_parent": REFERENCE_FUNCTIONAL_PARENT,
        "owner_excluded_visual_capabilities": OWNER_EXCLUDED_VISUAL_CAPABILITIES,
        "source_contract_coverage_percent": 100.0,
        "capability_count": len(CAPABILITIES),
        "missing_evidence": [],
        "capabilities": [asdict(row) for row in CAPABILITIES],
        "evidence_files": sorted(_normalized(
            relative
            for row in CAPABILITIES
            for relative in (*row.evidence, *row.test_evidence)
        )),
        "package_verified": True,
        "installed_verified": False,
        "live_provider_verified": False,
        "operational_parity_certified": False,
        "module_origins": origins,
        "evidence_limit": (
            "Frozen package parity does not prove installation identity, physical "
            "devices, OAuth/account state, provider effects, signing, or public "
            "release eligibility."
        ),
    }


__all__ = [
    "CAPABILITIES",
    "CapabilityParityError",
    "CapabilityParityRowV1",
    "PACKAGED_RUNTIME_MODULES",
    "REFERENCE_FUNCTIONAL_PARENT",
    "REFERENCE_HEAD",
    "REFERENCE_REPOSITORY",
    "OWNER_EXCLUDED_VISUAL_CAPABILITIES",
    "validate_packaged_parity_v1",
    "validate_source_parity_v1",
]
