"""Pure, shared MissionContext.v1 payload and lifecycle contract.

This module performs deterministic validation only.  It grants no authority
and deliberately has no database, owner-capability, tool, provider, or UI
dependency.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from memory.store import contains_secret


CONTEXT_CONTRACT = "MissionContext.v1"
PHASES = frozenset({
    "INTAKE", "CLARIFY_OR_SCOPE", "RESEARCH", "PLAN", "POLICY_CHECK",
    "WAITING_FOR_APPROVAL", "EXECUTE", "VERIFY", "CONFIRM", "MONITOR",
    "ADAPT", "COMPLETE", "BLOCKED", "FAILED", "CANCELLED",
})
TERMINAL_PHASES = frozenset({"COMPLETE", "FAILED", "CANCELLED"})
PHASE_STATES = {
    "INTAKE": frozenset({"draft"}),
    "CLARIFY_OR_SCOPE": frozenset({"draft"}),
    "RESEARCH": frozenset({"draft"}),
    "PLAN": frozenset({"draft"}),
    "POLICY_CHECK": frozenset({"draft"}),
    "WAITING_FOR_APPROVAL": frozenset({"awaiting_approval"}),
    "EXECUTE": frozenset({"running", "waiting", "paused"}),
    "VERIFY": frozenset({"running", "waiting", "paused"}),
    "CONFIRM": frozenset({"running", "waiting", "paused"}),
    "MONITOR": frozenset({"running", "waiting", "paused"}),
    "ADAPT": frozenset({"running", "waiting", "paused"}),
    "COMPLETE": frozenset({"succeeded"}),
    "BLOCKED": frozenset({"waiting"}),
    "FAILED": frozenset({"failed"}),
    "CANCELLED": frozenset({"cancelled"}),
}
TERMINAL_FOR_STATE = {
    "succeeded": "COMPLETE", "failed": "FAILED", "cancelled": "CANCELLED",
}
INITIAL_PHASE_FOR_STATE = {
    "draft": "INTAKE", "awaiting_approval": "WAITING_FOR_APPROVAL",
    "running": "EXECUTE", "waiting": "BLOCKED", "paused": "ADAPT",
    **TERMINAL_FOR_STATE,
}
PHASE_TRANSITIONS_V1 = {
    "INTAKE": frozenset({"CLARIFY_OR_SCOPE", "RESEARCH", "PLAN", "POLICY_CHECK", "BLOCKED", "FAILED", "CANCELLED"}),
    "CLARIFY_OR_SCOPE": frozenset({"RESEARCH", "PLAN", "POLICY_CHECK", "BLOCKED", "FAILED", "CANCELLED"}),
    "RESEARCH": frozenset({"CLARIFY_OR_SCOPE", "PLAN", "POLICY_CHECK", "BLOCKED", "FAILED", "CANCELLED"}),
    "PLAN": frozenset({"CLARIFY_OR_SCOPE", "RESEARCH", "POLICY_CHECK", "BLOCKED", "FAILED", "CANCELLED"}),
    "POLICY_CHECK": frozenset({"CLARIFY_OR_SCOPE", "PLAN", "WAITING_FOR_APPROVAL", "EXECUTE", "BLOCKED", "FAILED", "CANCELLED"}),
    "WAITING_FOR_APPROVAL": frozenset({"POLICY_CHECK", "EXECUTE", "BLOCKED", "FAILED", "CANCELLED"}),
    "EXECUTE": frozenset({"VERIFY", "MONITOR", "ADAPT", "BLOCKED", "FAILED", "CANCELLED"}),
    "VERIFY": frozenset({"EXECUTE", "CONFIRM", "ADAPT", "BLOCKED", "FAILED", "CANCELLED"}),
    "CONFIRM": frozenset({"MONITOR", "ADAPT", "COMPLETE", "BLOCKED", "FAILED", "CANCELLED"}),
    "MONITOR": frozenset({"ADAPT", "COMPLETE", "BLOCKED", "FAILED", "CANCELLED"}),
    "ADAPT": frozenset({"PLAN", "POLICY_CHECK", "EXECUTE", "VERIFY", "MONITOR", "BLOCKED", "FAILED", "CANCELLED"}),
    "BLOCKED": frozenset({"CLARIFY_OR_SCOPE", "RESEARCH", "PLAN", "POLICY_CHECK", "EXECUTE", "VERIFY", "CONFIRM", "MONITOR", "ADAPT", "FAILED", "CANCELLED"}),
    "COMPLETE": frozenset(), "FAILED": frozenset(), "CANCELLED": frozenset(),
}

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}")
_DATA_CLASSES = frozenset({"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"})
_PAYLOAD_KEYS = frozenset({
    "contract", "objective", "definition_of_done", "scope", "exclusions",
    "data_classification", "allowed_targets", "budget_dimensions",
    "autonomy_mode", "autonomy_expires_at", "checkpoint", "rollback_plan",
    "recovery_status",
})


class MissionContextContractError(ValueError):
    pass


def _text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise MissionContextContractError(f"{name} must be text")
    if not value or value != " ".join(value.split()) or len(value) > maximum:
        raise MissionContextContractError(f"{name} is invalid")
    if contains_secret(value):
        raise MissionContextContractError(f"{name} contains restricted material")
    return value


def _string_list(value: object, name: str) -> None:
    if type(value) is not list or len(value) > 100:
        raise MissionContextContractError(f"{name} must be a bounded list")
    items = [_text(item, name, 1000) for item in value]
    if len(items) != len(set(items)):
        raise MissionContextContractError(f"{name} contains duplicates")


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_context_payload(payload: object) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != _PAYLOAD_KEYS:
        raise MissionContextContractError("mission context keys diverge")
    if payload.get("contract") != CONTEXT_CONTRACT:
        raise MissionContextContractError("mission context contract is unknown")
    _text(payload["objective"], "objective", 4000)
    for name in ("definition_of_done", "scope", "exclusions", "allowed_targets"):
        _string_list(payload[name], name)
    data_class = _text(payload["data_classification"], "data_classification", 32)
    if data_class not in _DATA_CLASSES or data_class != data_class.upper():
        raise MissionContextContractError("data_classification is invalid")
    budgets = payload["budget_dimensions"]
    if type(budgets) is not dict or len(budgets) > 32:
        raise MissionContextContractError("budget_dimensions must be a bounded object")
    for key, raw in budgets.items():
        name = _text(key, "budget dimension", 64)
        if not _SAFE_ID.fullmatch(name):
            raise MissionContextContractError("budget dimension name is invalid")
        if (
            isinstance(raw, bool) or not isinstance(raw, (int, float))
            or not math.isfinite(raw) or raw < 0 or raw > 1e15
        ):
            raise MissionContextContractError("budget dimension value is invalid")
    mode = _text(payload["autonomy_mode"], "autonomy_mode", 64)
    if not _SAFE_ID.fullmatch(mode):
        raise MissionContextContractError("autonomy_mode is invalid")
    expiry = payload["autonomy_expires_at"]
    if expiry is not None:
        expiry = _text(expiry, "autonomy_expires_at", 40)
        try:
            datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MissionContextContractError("autonomy_expires_at is invalid") from exc
    _text(payload["checkpoint"], "checkpoint", 1000)
    _text(payload["rollback_plan"], "rollback_plan", 4000)
    _text(payload["recovery_status"], "recovery_status", 1000)
    return payload


def parse_context_json(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        raise MissionContextContractError("mission context JSON must be text")
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        raise MissionContextContractError("mission context JSON is invalid") from None
    validate_context_payload(payload)
    if canonical(payload) != value:
        raise MissionContextContractError("mission context JSON is noncanonical")
    return payload


def validate_phase_for_state(phase: object, state: object) -> str:
    if not isinstance(phase, str) or phase not in PHASES:
        raise MissionContextContractError("operational phase is invalid")
    if not isinstance(state, str) or state not in PHASE_STATES[phase]:
        raise MissionContextContractError(f"phase {phase} is incompatible with mission state {state}")
    return phase


def validate_storage_transition(operation: str, prior_phase: str | None, target: str) -> None:
    if operation == "initialize":
        if prior_phase is not None:
            raise MissionContextContractError("initialize has a predecessor")
        return
    if prior_phase not in PHASES or target not in PHASES:
        raise MissionContextContractError("phase transition uses an unknown phase")
    if operation == "transition":
        if prior_phase in TERMINAL_PHASES or target not in PHASE_TRANSITIONS_V1[prior_phase]:
            raise MissionContextContractError("phase transition is invalid")
        return
    if operation == "reconcile":
        if target not in TERMINAL_PHASES:
            raise MissionContextContractError("terminal reconciliation is invalid")
        return
    raise MissionContextContractError("mutation operation is invalid")


__all__ = [
    "CONTEXT_CONTRACT", "INITIAL_PHASE_FOR_STATE", "MissionContextContractError",
    "PHASES", "PHASE_STATES", "PHASE_TRANSITIONS_V1", "TERMINAL_FOR_STATE",
    "TERMINAL_PHASES", "canonical", "parse_context_json", "validate_context_payload",
    "validate_phase_for_state", "validate_storage_transition",
]
