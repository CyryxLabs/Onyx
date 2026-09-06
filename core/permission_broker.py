"""Host-owned approval boundary for consequential assistant actions.

Model-supplied approval claims are deliberately ignored. Tool parameters are
used only to classify and display the exact operation. An action is allowed only
when the trusted host callback returns the digest for that exact request.
"""

from __future__ import annotations

import copy
import contextvars
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from core.tool_audit import append_tool_audit


ApprovalCallback = Callable[[dict], str | None]
Phase5AuthorizationHook = Callable[
    [str, Mapping], tuple[bool, str] | None
]
GovernanceAuthorizationHook = Callable[
    [str, Mapping], tuple[bool, str] | None
]
_callback: ApprovalCallback | None = None
_phase5_authorization_hook: Phase5AuthorizationHook | None = None
_governance_authorization_hook: GovernanceAuthorizationHook | None = None
_trust_profile = "cautious"
_owner_autonomy_enabled = False
_autonomous_workspace_roots: tuple[Path, ...] = ()
_audit_healthy = True
_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("onyx_audit_trace_id",default="")
_GOVERNANCE_SAFETY_TOOLS = frozenset(
    {"close_camera", "mission_global_kill"}
)


class _OwnedPolicyValue(str):
    pass


class _OpaquePolicyLease:
    __slots__ = ()


def register_model_tool_policy_lease(
    *,
    tool: str,
    policy: str,
    actions: frozenset[str],
    autonomous_actions: frozenset[str],
):
    """Failure-atomically register one policy and return an opaque lease."""

    if (
        type(tool) is not str
        or not tool
        or type(policy) is not str
        or policy != "action_policy"
        or type(actions) is not frozenset
        or not actions
        or type(autonomous_actions) is not frozenset
        or not autonomous_actions.issubset(actions)
    ):
        raise ValueError("model-tool policy lease contract is invalid")
    policy_value = _OwnedPolicyValue(policy)
    actions_value = frozenset(actions)
    autonomous_value = frozenset(autonomous_actions)
    return _register_policy_lease(
        tool, policy_value, actions_value, autonomous_value
    )


def release_model_tool_policy_lease(lease: object) -> None:
    """CAS-release only the exact policy objects installed by ``lease``."""

    _release_policy_lease(lease)


def authorize_model_tool_decision_only(
    tool_name: str,
    arguments: Mapping | None = None,
) -> tuple[bool, str]:
    """Return the trusted decision without writing a broker audit record.

    This seam is for integrations that atomically persist one richer semantic
    audit record after their post-verification. Existing callers retain the
    original ``authorize_model_tool`` behavior unchanged.
    """

    args = copy.deepcopy(dict(arguments or {}))
    policy = MODEL_TOOL_POLICIES.get(tool_name)
    action = args.get("action")
    if (
        policy != "action_policy"
        or type(action) is not str
        or action not in MODEL_TOOL_ACTIONS.get(tool_name, frozenset())
    ):
        return False, "Permission denied: model-tool policy is unavailable."
    if not _audit_healthy and action not in _AUTONOMOUS_ACTIONS.get(
        tool_name, frozenset()
    ):
        return False, "Permission denied: consequential audit is unhealthy."
    governance = _governance_authorization_hook
    if governance is not None:
        try:
            governed = governance(tool_name, copy.deepcopy(args))
        except Exception:
            return False, "Permission denied: governance authorization failed."
        if governed is not None:
            if (
                type(governed) is not tuple
                or len(governed) != 2
                or type(governed[0]) is not bool
                or type(governed[1]) is not str
            ):
                return False, "Permission denied: invalid governance result."
            return governed
    if owner_autonomy_enabled() and action in _AUTONOMOUS_ACTIONS.get(
        tool_name, frozenset()
    ):
        if not _audit_healthy:
            return False, "Permission denied: autonomous audit is unhealthy."
        return True, f"autonomous:{tool_name}.{action}"
    operation = f"{tool_name}.{action}"
    return authorize(
        operation,
        f"Allow Onyx to execute consequential operation '{operation}'?",
        {"tool": tool_name, "arguments": args},
    )


def set_audit_trace_id(trace_id: str):
    return _TRACE_ID.set(trace_id[:64])


def reset_audit_trace_id(token) -> None:
    _TRACE_ID.reset(token)


def set_trust_profile(profile: str) -> None:
    global _trust_profile
    _trust_profile = profile if profile in {"cautious", "autonomous"} else "cautious"


def get_trust_profile() -> str:
    return _trust_profile


def configure_owner_autonomy(enabled: bool, roots: list[str] | tuple[str, ...]) -> None:
    global _owner_autonomy_enabled, _autonomous_workspace_roots
    _owner_autonomy_enabled = enabled is True
    resolved = []
    for value in roots if isinstance(roots, (list, tuple)) else ():
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, TypeError):
            continue
        if path.is_dir():
            resolved.append(path)
    _autonomous_workspace_roots = tuple(resolved)


def owner_autonomy_enabled() -> bool:
    return _owner_autonomy_enabled and _trust_profile == "autonomous"


def mark_audit_unhealthy() -> None:
    global _audit_healthy
    _audit_healthy = False


def audit_healthy() -> bool:
    return _audit_healthy


def authorize_capability_operation(
    capability: str,
    operation: str,
    binding: Mapping | None = None,
) -> tuple[bool, str]:
    """Authorize one exact capability operation through the host broker.

    Capability expansion callers receive no autonomous shortcut.  The audit
    must be healthy before owner confirmation and the confirmation digest is
    bound to the capability, operation, and caller-supplied content-free
    binding metadata.
    """

    if not _audit_healthy:
        return False, "Permission denied: consequential audit is unhealthy."
    if type(capability) is not str or not capability or type(operation) is not str or not operation:
        return False, "Permission denied: capability operation is invalid."
    action = f"capability.{capability}.{operation}"
    return authorize(
        action,
        f"Allow Onyx to execute consequential operation '{action}'?",
        {
            "capability": capability,
            "operation": operation,
            "binding": copy.deepcopy(dict(binding or {})),
        },
    )


def _protected_system_roots() -> tuple[Path, ...]:
    """Directories whose contents the owner must approve individually.

    Owner rule (2026-08-21): Onyx works freely across the owner's own files;
    the standing restriction is that operating-system and installed-program
    files are never created, altered, moved or removed without an explicit
    approval.  Resolution is by whole path components, so ``C:\\Windows2`` is
    not treated as inside ``C:\\Windows``.
    """
    roots: list[Path] = []
    if os.name == "nt":
        candidates = [
            os.environ.get("SystemRoot", r"C:\Windows"),
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("ProgramData", r"C:\ProgramData"),
            os.environ.get("SystemDrive", "C:") + "\\$Recycle.Bin",
            os.environ.get("SystemDrive", "C:") + "\\System Volume Information",
            os.environ.get("SystemDrive", "C:") + "\\Recovery",
        ]
    else:
        candidates = [
            "/System", "/Library", "/usr", "/bin", "/sbin", "/etc", "/var",
            "/opt", "/boot", "/dev", "/proc", "/sys", "/Applications",
        ]
    for value in candidates:
        try:
            roots.append(Path(value).resolve(strict=False))
        except (OSError, RuntimeError, TypeError):
            continue
    return tuple(roots)


def _is_protected_system_path(target: Path) -> bool:
    for root in _protected_system_roots():
        if target == root or target.is_relative_to(root):
            return True
    # The drive root itself is structural, not an ordinary working folder.
    return target.parent == target


def _redirects_through_a_link(path: Path) -> bool:
    """True when any component of the path *as written* is a link or reparse point."""
    cursor = path if path.exists() else path.parent
    seen = 0
    while cursor.parent != cursor and seen < 64:
        seen += 1
        try:
            info = cursor.lstat()
            if cursor.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                return True
        except OSError:
            return True
        cursor = cursor.parent
    return False


def _autonomous_file_target_allowed(args: Mapping, action: str) -> bool:
    if action not in {
        "create_file",
        "create_folder",
        "move",
        "copy",
        "rename",
        "write",
        "delete",
        "organize_desktop",
    }:
        return True
    raw = args.get("path")
    name = args.get("name", "")
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or not isinstance(name, str)
    ):
        return False
    try:
        base = Path(raw).expanduser()
        part = Path(name)
        if part.is_absolute() or ".." in part.parts:
            return False
        # Check the path as given, before resolution.  Resolving first would
        # erase a symlink from the ancestry, so a link planted inside an
        # ordinary folder could silently redirect a write somewhere the owner
        # never named.  Both locations may well be permitted; being sent
        # somewhere other than where you pointed is the part that is not.
        if _redirects_through_a_link(base):
            return False
        source = (base / part if name else base).resolve(strict=False)
        targets = [source]
        if action in {"move", "copy"}:
            destination = args.get("destination")
            if not isinstance(destination, str) or not destination.strip():
                return False
            dest = Path(destination).expanduser().resolve(strict=False)
            targets.append(dest / source.name if dest.is_dir() else dest)
        elif action == "rename":
            new_name = args.get("new_name")
            new_part = (
                Path(new_name) if isinstance(new_name, str) else Path("..")
            )
            if (
                new_part.is_absolute()
                or ".." in new_part.parts
                or len(new_part.parts) != 1
            ):
                return False
            targets.append((source.parent / new_part).resolve(strict=False))
    except (OSError, RuntimeError):
        return False
    source_root = Path(__file__).resolve().parents[1]
    for target in targets:
        if target == source_root or target.is_relative_to(source_root):
            return False
        if _is_protected_system_path(target):
            return False
        cursor = target if target.exists() else target.parent
        while True:
            try:
                st = cursor.lstat()
                if (
                    cursor.is_symlink()
                    or getattr(st, "st_file_attributes", 0) & 0x400
                ):
                    return False
            except OSError:
                return False
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
    return True


# Every model-exposed tool must appear here. ``prompt_free`` is reserved for
# operations that neither expose private/local information nor create risk;
# immediate safety-stop operations also belong there so consent can be revoked
# without friction.
# ``action_policy`` tools are classified by their exact, recognized action, and
# ``self_approved`` tools own a stronger immutable-artifact approval flow.
_PHASE5_LOCAL_CATALOG_TOOL = "local_catalog_read"

MODEL_TOOL_POLICIES = {
    "open_app": "always_confirm",
    "web_search": "always_confirm",
    "opportunity_research": "always_confirm",
    "opportunity_monitor": "action_policy",
    "department_plan": "always_confirm",
    "system_status": "always_confirm",
    "weather_report": "always_confirm",
    "send_message": "always_confirm",
    "reminder": "always_confirm",
    "youtube_video": "action_policy",
    "screen_process": "always_confirm",
    "close_camera": "prompt_free",
    "computer_settings": "action_policy",
    "browser_control": "action_policy",
    "file_controller": "action_policy",
    "desktop_control": "action_policy",
    "code_helper": "action_policy",
    "dev_agent": "self_approved",
    "computer_control": "action_policy",
    "game_updater": "action_policy",
    "flight_finder": "always_confirm",
    "shutdown_onyx": "always_confirm",
    "file_processor": "action_policy",
    "save_memory": "always_confirm",
    "memory_search": "always_confirm",
    "business_document_generate": "always_confirm",
    "phone_call_prepare": "always_confirm",
    # Undo can only consume a bounded reverse operation that Onyx itself
    # registered in the current process. It reduces prior authority and does
    # not accept a model-supplied target.
    "undo": "prompt_free",
    # Mission orchestration requests are consequential control-plane changes.
    "mission_create": "always_confirm",
    # Running is orchestration-only: awaiting missions receive the single exact
    # canonical-plan confirmation inside MissionStore.approve, and every
    # executable step is separately checked by the mission-tool policy.
    "mission_run": "prompt_free",
    "mission_cancel": "always_confirm",
    "mission_status": "always_confirm",
    # Outcome reconciliation is an explicit owner decision. It must never be
    # inherited from autonomous mode or treated as a model assertion.
    "mission_reconcile": "always_confirm",
    "mission_external_agent_cleanup": "always_confirm",
    # Safety controls never need permission to reduce authority. Resuming the
    # unchanged envelope is still owner-confirmed.
    "mission_pause": "prompt_free",
    "mission_takeover": "prompt_free",
    "mission_resume": "always_confirm",
    "mission_global_kill": "prompt_free",
}

# This is intentionally independent of model-provided schema validation. Calls
# can arrive malformed or from a future model/schema, so the runtime boundary
# must reject blank and unknown actions before asking the user anything.
MODEL_TOOL_ACTIONS = {
    "opportunity_monitor": frozenset(
        {"configure", "status", "run", "digests", "kill", "resume"}
    ),
    "youtube_video": frozenset({"play", "summarize", "get_info", "trending"}),
    "computer_settings": frozenset({
        "volume_set", "type_text", "write_on_screen", "type", "write",
        "press_key", "reload_n", "refresh_n", "reload_page_n", "volume_up",
        "volume_down", "mute", "unmute", "toggle_mute", "brightness_up",
        "brightness_down", "sleep_display", "screen_off", "pause_video",
        "play_pause", "close_app", "close_window", "full_screen", "fullscreen",
        "minimize", "maximize", "snap_left", "snap_right", "switch_window",
        "show_desktop", "task_manager", "focus_search", "refresh_page", "reload",
        "close_tab", "new_tab", "next_tab", "prev_tab", "go_back", "go_forward",
        "zoom_in", "zoom_out", "zoom_reset", "find_on_page", "scroll_up",
        "enable_autostart", "disable_autostart", "autostart_status",
        "scroll_down", "scroll_top", "scroll_bottom", "page_up", "page_down",
        "copy", "paste", "cut", "undo", "redo", "select_all", "save", "enter",
        "escape", "screenshot", "lock_screen", "open_settings", "file_explorer",
        "open_run", "dark_mode", "toggle_wifi", "restart", "shutdown",
    }),
    "browser_control": frozenset({
        "go_to", "search", "click", "type", "scroll", "fill_form", "smart_click",
        "smart_type", "get_text", "get_url", "press", "new_tab", "close_tab",
        "screenshot", "back", "forward", "reload", "switch", "list_browsers",
        "close", "close_all",
    }),
    "file_controller": frozenset({
        "list", "create_file", "create_folder", "delete", "move", "copy", "rename",
        "read", "write", "find", "largest", "disk_usage", "organize_desktop", "info",
    }),
    "desktop_control": frozenset({
        "wallpaper", "wallpaper_url", "current_wallpaper", "organize", "clean",
        "list", "stats",
    }),
    "code_helper": frozenset({
        "explain", "run", "screen_debug",
    }),
    "computer_control": frozenset({
        "type", "smart_type", "click", "left_click", "double_click", "right_click",
        "move", "drag", "hotkey", "press", "scroll", "copy", "paste", "screenshot",
        "screen_find", "screen_click", "wait", "clear_field", "focus_window",
        "random_data", "user_data",
    }),
    "game_updater": frozenset({
        "update", "install", "list", "download_status", "schedule", "cancel_schedule",
        "schedule_status",
    }),
    "file_processor": frozenset({
        "describe", "ocr", "resize", "compress", "convert", "info", "summarize",
        "extract_text", "to_word", "fix", "reformat", "translate_hint", "word_count",
        "to_bullet", "analyze", "stats", "filter", "sort", "validate", "format",
        "to_csv", "explain", "review", "optimize", "run", "document", "test",
        "transcribe", "trim", "extract_audio", "extract_frame", "list", "extract",
    }),
}

_PROMPT_FREE_ACTIONS = {
    "opportunity_monitor": frozenset({"status", "digests", "kill"}),
    # These generate no local/private data and produce no external side effect.
    "computer_control": frozenset({"random_data", "wait"}),
    # These read public YouTube metadata. Saving/opening content is confirmed.
    "youtube_video": frozenset({"get_info", "trending"}),
}

_AUTONOMOUS_TOOLS = frozenset({"open_app", "web_search", "system_status", "weather_report", "reminder", "screen_process", "save_memory", "memory_search", "mission_create", "mission_cancel", "mission_status", "flight_finder", "day_brief_read"})
_AUTONOMOUS_ACTIONS = {
    "browser_control": MODEL_TOOL_ACTIONS["browser_control"] - {"fill_form"},
    "file_controller": MODEL_TOOL_ACTIONS["file_controller"] - {"delete"},
    "computer_control": MODEL_TOOL_ACTIONS["computer_control"],
    "desktop_control": MODEL_TOOL_ACTIONS["desktop_control"] - {"clean"},
    "computer_settings": MODEL_TOOL_ACTIONS["computer_settings"] - {"restart", "shutdown", "toggle_wifi", "lock_screen", "open_settings",
        # Registering Onyx to launch at every login is persistent
        # configuration, so it is confirmed once rather than assumed.
        "enable_autostart", "disable_autostart"},
    "youtube_video": MODEL_TOOL_ACTIONS["youtube_video"],
    "file_processor": MODEL_TOOL_ACTIONS["file_processor"] - {"run"},
    "game_updater": frozenset({"list", "download_status", "schedule_status", "cancel_schedule"}),
    "code_helper": frozenset({"explain", "screen_debug"}),
}


def _build_policy_lease_authority():
    lock = threading.RLock()
    records: dict[
        object, tuple[str, str, frozenset[str], frozenset[str]]
    ] = {}

    def register(
        tool: str,
        policy_value: str,
        actions_value: frozenset[str],
        autonomous_value: frozenset[str],
    ) -> object:
        lease = _OpaquePolicyLease()
        owned_actions = frozenset(tuple(actions_value))
        owned_autonomous = frozenset(tuple(autonomous_value))
        with lock:
            if (
                tool in MODEL_TOOL_POLICIES
                or tool in MODEL_TOOL_ACTIONS
                or tool in _AUTONOMOUS_ACTIONS
            ):
                raise ValueError("model-tool policy is already registered")
            applied: list[tuple[dict, object, object]] = []
            try:
                MODEL_TOOL_POLICIES[tool] = policy_value
                applied.append((MODEL_TOOL_POLICIES, tool, policy_value))
                MODEL_TOOL_ACTIONS[tool] = owned_actions
                applied.append((MODEL_TOOL_ACTIONS, tool, owned_actions))
                _AUTONOMOUS_ACTIONS[tool] = owned_autonomous
                applied.append((_AUTONOMOUS_ACTIONS, tool, owned_autonomous))
                records[lease] = (
                    tool,
                    policy_value,
                    owned_actions,
                    owned_autonomous,
                )
            except BaseException:
                for registry, key, owned in reversed(applied):
                    if registry.get(key) is owned:
                        registry.pop(key, None)
                raise
        return lease

    def release(lease: object) -> None:
        with lock:
            record = records.get(lease)
            if record is None:
                raise ValueError("model-tool policy lease is invalid")
            tool, policy, actions, autonomous = record
            if (
                MODEL_TOOL_POLICIES.get(tool) is not policy
                or MODEL_TOOL_ACTIONS.get(tool) is not actions
                or _AUTONOMOUS_ACTIONS.get(tool) is not autonomous
            ):
                raise RuntimeError("model-tool policy lease ownership drifted")
            MODEL_TOOL_POLICIES.pop(tool)
            MODEL_TOOL_ACTIONS.pop(tool)
            _AUTONOMOUS_ACTIONS.pop(tool)
            records.pop(lease)

    return register, release


_register_policy_lease, _release_policy_lease = _build_policy_lease_authority()

# Mission-internal tools are not exposed directly to the Live model. They still
# have an explicit centralized policy so the executor cannot invent a bypass.
MISSION_TOOL_POLICIES = {
    "local_note": "data_only",
    "local_checklist": "data_only",
    "workspace_inventory": "provider_free_read_only",
    "workspace_text_search": "provider_free_read_only",
    "workspace_read_text": "provider_free_read_only",
    "workspace_hash": "provider_free_read_only",
    "local_system_status": "provider_free_read_only",
    "readiness_summary": "provider_free_read_only",
    "phase11_project_autopilot_v1": "signed_isolated_worktree",
    "phase11_governed_browser_away_v1": "signed_read_only_browser",
    "external_coding_agent_dispatch_v1": "signed_external_patch_only",
}


def authorize_mission_tool(tool_name: str, arguments: Mapping | None = None) -> tuple[bool, str]:
    """Authorize an allowlisted mission step without widening Live policies."""
    policy = MISSION_TOOL_POLICIES.get(tool_name)
    if policy in {
        "data_only",
        "provider_free_read_only",
        "signed_isolated_worktree",
        "signed_read_only_browser",
        "signed_external_patch_only",
    }:
        return True, f"mission-policy:{policy}"
    return authorize_model_tool(tool_name, arguments)


def set_permission_callback(callback: ApprovalCallback | None) -> None:
    global _callback
    _callback = callback


def get_permission_callback() -> ApprovalCallback | None:
    """Return the current trusted host callback for reversible seam wrapping."""
    return _callback


def set_phase5_authorization_hook(
    callback: Phase5AuthorizationHook | None,
) -> None:
    """Install the session-owned Phase 5 low-risk evaluator.

    The hook is not a general permission callback: it may handle only its
    closed local contract and must return ``None`` for every legacy tool.
    """
    global _phase5_authorization_hook
    if callback is not None and not callable(callback):
        raise TypeError("Phase 5 authorization hook must be callable")
    _phase5_authorization_hook = callback


def owner_autonomy_evaluator(
    tool_name: str, arguments: Mapping | None, risk: str = ""
) -> bool:
    """Decide whether configured owner autonomy covers this exact operation.

    Installed into the governance nucleus so an autonomous grant travels the
    same intent/grant/approval path as any other governed authorization, and
    therefore satisfies the dispatch fence.  Returning ``True`` here is never
    sufficient on its own: the nucleus has already refused always-explicit and
    critical work before consulting this evaluator.
    """
    if not owner_autonomy_enabled() or not _audit_healthy:
        return False
    args = dict(arguments or {})
    action = str(args.get("action") or "")
    # The nucleus has already refused always-explicit and critical work before
    # reaching here, so what remains is the owner's standing restriction:
    # operating-system and installed-program files are never created, altered,
    # moved or removed without an explicit approval.  Non-mutating work and
    # non-file tools pass straight through.
    return _autonomous_file_target_allowed(args, action)


def set_governance_authorization_hook(
    callback: GovernanceAuthorizationHook | None,
) -> None:
    """Install the V16 exact low-risk/kill authority.

    ``None`` delegates an always-explicit action to the trusted approval inbox.
    A concrete decision is authoritative only for the exact current arguments.
    """
    global _governance_authorization_hook
    if callback is not None and not callable(callback):
        raise TypeError("Governance authorization hook must be callable")
    _governance_authorization_hook = callback


def build_request(action: str, summary: str, details: Mapping | None = None) -> dict:
    payload = {
        "action": str(action),
        "summary": str(summary),
        "details": copy.deepcopy(dict(details or {})),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {**payload, "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def authorize(action: str, summary: str, details: Mapping | None = None) -> tuple[bool, str]:
    base = build_request(action, summary, details)
    nonce = secrets.token_hex(16)
    payload = {
        "action": base["action"],
        "summary": base["summary"],
        "details": base["details"],
        "nonce": nonce,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    request = {**payload, "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
    callback = _callback
    if callback is None:
        return False, "Permission denied: no trusted host confirmation UI is available."
    issued_at = time.monotonic()
    try:
        decision = callback(copy.deepcopy(request))
    except Exception as exc:
        return False, f"Permission denied: trusted host confirmation failed: {exc}"
    if not isinstance(decision, str) or not hmac.compare_digest(decision, request["digest"]):
        return False, "Permission denied by the trusted host."
    if time.monotonic() - issued_at > 300.0:
        return False, "Permission denied: trusted host confirmation expired."
    return True, request["digest"]


def authorize_model_tool(tool_name: str, arguments: Mapping | None = None) -> tuple[bool, str]:
    """Apply the centralized model-tool risk policy.

    Unknown tools/actions fail closed.  Tool arguments are evidence shown to the
    trusted host, never an authorization signal.  ``dev_agent`` is the sole
    exception because it separately approves immutable artifacts and hashes.
    """
    global _audit_healthy
    trace_id=_TRACE_ID.get()
    policy = MODEL_TOOL_POLICIES.get(tool_name)
    args = copy.deepcopy(dict(arguments or {}))
    if policy is None and tool_name != _PHASE5_LOCAL_CATALOG_TOOL:
        return False, f"Permission denied: no risk policy exists for tool '{tool_name}'."

    # Validate outbound data before asking for consent. A compare request may
    # intentionally omit ``query`` when it supplies two or more concrete items;
    # every other search mode needs an explicit query.
    if tool_name == "web_search":
        mode = str(args.get("mode", "search")).lower().strip() or "search"
        if mode not in {"search", "news", "research", "price", "compare"}:
            return False, f"Permission denied: unsupported web search mode '{mode}'."
        query = str(args.get("query", "")).strip()
        items = args.get("items", [])
        valid_items = (
            isinstance(items, list)
            and len(items) >= 2
            and all(isinstance(item, str) and item.strip() for item in items)
        )
        if mode == "compare" and not valid_items:
            return False, "Permission denied: compare mode requires at least two non-empty items."
        if mode != "compare" and not query:
            return False, f"Permission denied: web search mode '{mode}' requires a query."
    if tool_name == "opportunity_research":
        query = str(args.get("query", "")).strip()
        mode = str(args.get("mode", "search")).strip().casefold() or "search"
        maximum = args.get("max_results", 8)
        if not query:
            return False, "Permission denied: opportunity_research requires a query."
        if mode not in {"search", "news"}:
            return False, "Permission denied: opportunity_research mode is invalid."
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 20:
            return False, "Permission denied: opportunity_research result cap is invalid."
    if tool_name == "department_plan":
        task = str(args.get("task", "")).strip()
        story_id = str(args.get("story_id", "")).strip()
        budget = args.get("budget_micro_usd")
        squads = args.get("squads", [])
        if not task or not story_id:
            return False, "Permission denied: department_plan requires task and story_id."
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
            return False, "Permission denied: department_plan budget is invalid."
        if not isinstance(squads, list) or len(squads) > 4 or not all(
            isinstance(item, str) and item.strip() for item in squads
        ):
            return False, "Permission denied: department_plan squads are invalid."
    if (
        tool_name == "mission_create"
        and str(args.get("mission_type", "")).strip()
        == "external_coding_agent_v1"
    ):
        story_id = str(args.get("story_id", "")).strip()
        budget = args.get("budget_micro_usd")
        squads = args.get("squads", [])
        if not story_id:
            return False, "Permission denied: external agent requires an AEXOS story_id."
        if (
            isinstance(budget, bool)
            or not isinstance(budget, int)
            or not 0 <= budget <= 25_000_000
        ):
            return False, "Permission denied: external agent AEXOS budget is invalid."
        if not isinstance(squads, list) or len(squads) > 4 or not all(
            isinstance(item, str) and item.strip() for item in squads
        ):
            return False, "Permission denied: external agent AEXOS squads are invalid."
    if tool_name == "weather_report" and not str(args.get("city", "")).strip():
        return False, "Permission denied: weather_report requires a city."
    if tool_name == "memory_search" and not str(args.get("query", "")).strip():
        return False, "Permission denied: memory_search requires a query."

    # The host has already materialized the invocation reference in main.py;
    # the session-owned hook validates the remaining bounded catalog fields.
    # This is deliberately before legacy autonomy/callback handling and cannot
    # authorize any other tool.
    if tool_name == _PHASE5_LOCAL_CATALOG_TOOL:
        hook = _phase5_authorization_hook
        if hook is None:
            return False, "Permission denied: local catalog integration is disabled."
        try:
            result = hook(tool_name, copy.deepcopy(args))
        except Exception as exc:
            return False, (
                "Permission denied: Phase 5 local authorization failed: "
                f"{type(exc).__name__}"
            )
        if (
            type(result) is not tuple
            or len(result) != 2
            or type(result[0]) is not bool
            or type(result[1]) is not str
        ):
            return False, "Permission denied: invalid Phase 5 authorization result."
        approved, reason = result
        try:
            append_tool_audit(
                profile=_trust_profile,
                tool=tool_name,
                action="catalog_read",
                decision="allow" if approved else "deny",
                reason="phase5-exact-local-read" if approved else "phase5-denied",
                arguments=args,
                trace_id=trace_id,
            )
        except Exception:
            _audit_healthy = False
            return False, "Permission denied: audit failed before action."
        return approved, reason

    action = str(args.get("action", "")).lower().strip().replace(" ", "_").replace("-", "_")
    if policy == "action_policy":
        known_actions = MODEL_TOOL_ACTIONS.get(tool_name)
        if not action:
            return False, f"Permission denied: tool '{tool_name}' requires an explicit action."
        if known_actions is None or action not in known_actions:
            return False, f"Permission denied: unknown action '{action}' for tool '{tool_name}'."
        if tool_name == "opportunity_monitor" and action == "configure":
            if not str(args.get("schedule_id", "")).strip() or not str(
                args.get("query", "")
            ).strip():
                return False, "Permission denied: opportunity monitor requires schedule_id and query."
            domains = args.get("allowed_domains")
            if not isinstance(domains, list) or not 1 <= len(domains) <= 16 or not all(
                isinstance(item, str) and item.strip() for item in domains
            ):
                return False, "Permission denied: opportunity monitor domains are invalid."
        if tool_name == "file_processor" and not str(args.get("file_path", "")).strip():
            return False, "Permission denied: file_processor requires an exact file path."
        if tool_name == "file_processor" and action == "run":
            file_path = str(args.get("file_path", "")).strip()
            path = Path(file_path)
            if not path.is_absolute() or not path.is_file():
                return False, "Permission denied: file_processor.run requires an exact existing absolute file path."
            run_args, timeout = args.get("args"), args.get("timeout")
            digest, size = args.get("source_sha256"), args.get("source_size")
            if not isinstance(run_args, list) or any(not isinstance(item, str) for item in run_args):
                return False, "Permission denied: file_processor.run arguments were not materialized."
            if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
                return False, "Permission denied: file_processor.run timeout was not materialized."
            if not isinstance(digest, str) or len(digest) != 64:
                return False, "Permission denied: file_processor.run source hash was not materialized."
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                return False, "Permission denied: file_processor.run source size was not materialized."
        # This approval binds the input action only. The file processor must not
        # treat it as approval for model/OCR/transcription bytes that do not yet
        # exist; those results remain preview-only even when ``save`` is true.
        if tool_name == "code_helper":
            file_path = str(args.get("file_path", "")).strip()
            if file_path:
                path = Path(file_path)
                if not path.is_absolute() or not path.is_file():
                    return False, "Permission denied: code_helper requires an exact existing absolute file path."
            if action == "run":
                if not file_path:
                    return False, "Permission denied: code_helper.run requires an exact file path."
                run_args = args.get("args")
                timeout = args.get("timeout")
                if not isinstance(run_args, list) or any(not isinstance(item, str) for item in run_args):
                    return False, "Permission denied: code_helper.run arguments were not materialized."
                if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
                    return False, "Permission denied: code_helper.run timeout was not materialized."
                digest, size = args.get("source_sha256"), args.get("source_size")
                if not isinstance(digest, str) or len(digest) != 64:
                    return False, "Permission denied: code_helper.run source hash was not materialized."
                if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                    return False, "Permission denied: code_helper.run source size was not materialized."

    if tool_name == "youtube_video" and action == "summarize" and not args.get("save", False):
        return True, ""
    if policy == "action_policy" and action in _PROMPT_FREE_ACTIONS.get(tool_name, frozenset()):
        return True, ""

    governance = _governance_authorization_hook
    if governance is not None:
        if not _audit_healthy and tool_name not in _GOVERNANCE_SAFETY_TOOLS:
            return False, "Permission denied: governance audit is unhealthy."
        try:
            governed = governance(tool_name, copy.deepcopy(args))
        except Exception as exc:
            return False, (
                "Permission denied: governance authorization failed: "
                f"{type(exc).__name__}"
            )
        if governed is not None:
            if (
                type(governed) is not tuple
                or len(governed) != 2
                or type(governed[0]) is not bool
                or type(governed[1]) is not str
            ):
                return False, "Permission denied: invalid governance result."
            approved, reason = governed
            try:
                append_tool_audit(
                    profile=_trust_profile,
                    tool=tool_name,
                    action=action,
                    decision="allow" if approved else "deny",
                    reason=(
                        "governance-exact-low-risk"
                        if approved
                        else "governance-denied"
                    ),
                    arguments=args,
                    trace_id=trace_id,
                )
            except Exception:
                _audit_healthy = False
                if approved:
                    owner = getattr(governance, "__self__", None)
                    compensate = getattr(
                        owner, "authorization_audit_failed", None
                    )
                    if callable(compensate):
                        try:
                            compensate(tool_name, copy.deepcopy(args))
                        except Exception:
                            pass
                return False, "Permission denied: audit failed before action."
            return approved, reason

    if policy in {"prompt_free", "self_approved"} and (
        governance is None or tool_name in _GOVERNANCE_SAFETY_TOOLS
    ):
        return True, ""

    if governance is None and owner_autonomy_enabled():
        if not _audit_healthy:
            return False, "Permission denied: autonomous audit is unhealthy."
        operation = f"{tool_name}.{action}" if action else tool_name
        allowed = tool_name in _AUTONOMOUS_TOOLS or action in _AUTONOMOUS_ACTIONS.get(tool_name, frozenset())
        if tool_name == "file_controller" and allowed:
            allowed = _autonomous_file_target_allowed(args, action)
        if allowed:
            try:
                append_tool_audit(profile=_trust_profile, tool=tool_name, action=action, decision="allow", reason=f"autonomous:{operation}", arguments=args, trace_id=trace_id)
            except Exception:
                _audit_healthy=False
                return False,"Permission denied: autonomous audit failed."
            return True, f"autonomous:{operation}"

    operation = f"{tool_name}.{action}" if action else tool_name
    summary = f"Allow Onyx to execute consequential operation '{operation}'?"
    approved, reason = authorize(
        operation, summary, {"tool": tool_name, "arguments": args}
    )
    try:
        append_tool_audit(
            profile=_trust_profile,
            tool=tool_name,
            action=action,
            decision="allow" if approved else "deny",
            reason="trusted-confirmation" if approved else "host-denied",
            arguments=args,
            trace_id=trace_id,
        )
    except Exception:
        _audit_healthy = False
        return False, "Permission denied: audit failed before action."
    return approved, reason
