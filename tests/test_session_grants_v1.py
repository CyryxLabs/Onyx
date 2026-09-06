from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from core.permission_broker import build_request
from core.session_grants_v1 import (
    GRANT_EVALUATOR_FLAG,
    GRANT_POLICY_VERSION,
    GRANT_SCHEMA_VERSION,
    GrantContractError,
    SessionGrant,
    SessionGrantStore,
    ShadowActionRequest,
    grant_evaluator_enabled,
    permission_request_digest,
)


NOW = 2_000_000_000_000
SHA_A = hashlib.sha256(b"a").hexdigest()
SHA_B = hashlib.sha256(b"b").hexdigest()
SHA_C = hashlib.sha256(b"c").hexdigest()
SHA_D = hashlib.sha256(b"d").hexdigest()


def _action_digest(**overrides: object) -> str:
    details = {
        "principal_id": "owner-1",
        "session_id": "session-1",
        "workspace_id": "workspace-1",
        "mission_id": "mission-1",
        "capability": "local-files",
        "tool": "file-controller",
        "operation": "write",
        "target_sha256": SHA_A,
        "payload_sha256": SHA_B,
        "risk": "low",
        "data_class": "internal",
        "cost_micro": 3,
    }
    details.update(overrides)
    return permission_request_digest("file-controller.write", "exact action", details)


def _request(**overrides: object) -> ShadowActionRequest:
    values: dict[str, object] = {
        "principal_id": "owner-1",
        "session_id": "session-1",
        "workspace_id": "workspace-1",
        "mission_id": "mission-1",
        "capability": "local-files",
        "tool": "file-controller",
        "operation": "write",
        "target_sha256": SHA_A,
        "payload_sha256": SHA_B,
        "action_digest": _action_digest(),
        "risk": "low",
        "data_class": "internal",
        "cost_micro": 3,
        "requested_at_ms": NOW,
        "always_explicit": False,
    }
    values.update(overrides)
    return ShadowActionRequest(**values)  # type: ignore[arg-type]


def _grant(**overrides: object) -> SessionGrant:
    values: dict[str, object] = {
        "grant_id": "grant-1",
        "schema_version": GRANT_SCHEMA_VERSION,
        "policy_version": GRANT_POLICY_VERSION,
        "principal_id": "owner-1",
        "session_id": "session-1",
        "workspace_id": "workspace-1",
        "mission_id": "mission-1",
        "capability": "local-files",
        "tool": "file-controller",
        "operation": "write",
        "target_sha256": (SHA_A,),
        "payload_sha256": SHA_B,
        "action_digest": _action_digest(),
        "max_data_class": "internal",
        "risk_ceiling": "medium",
        "max_cost_per_action_micro": 5,
        "max_cost_aggregate_micro": 20,
        "max_uses": 3,
        "issued_at_ms": NOW - 1_000,
        "not_before_ms": NOW - 500,
        "expires_at_ms": NOW + 10_000,
        "approval_digest": SHA_C,
        "audit_head": SHA_D,
    }
    values.update(overrides)
    return SessionGrant(**values)  # type: ignore[arg-type]


def _evaluate(store: SessionGrantStore, request: ShadowActionRequest | None = None, **kwargs: object):
    values: dict[str, object] = {
        "current_policy_version": GRANT_POLICY_VERSION,
        "current_audit_head": SHA_D,
        "now_ms": NOW,
        "environ": {GRANT_EVALUATOR_FLAG: "true"},
    }
    values.update(kwargs)
    return store.shadow_evaluate(request or _request(), **values)  # type: ignore[arg-type]


def _store(grant: SessionGrant | None = None) -> SessionGrantStore:
    store = SessionGrantStore("session-1")
    store.issue(grant or _grant())
    return store


def test_permission_digest_is_exact_existing_permission_contract() -> None:
    details = {"b": [2, 3], "a": {"x": True}}
    expected = build_request("tool.operation", "summary", details)
    assert permission_request_digest("tool.operation", "summary", details) == expected["digest"]
    assert permission_request_digest("tool.operation", "summary!", details) != expected["digest"]


@pytest.mark.parametrize("value", ["1", "true", " TRUE "])
def test_feature_flag_requires_explicit_recognized_opt_in(value: str) -> None:
    assert grant_evaluator_enabled({GRANT_EVALUATOR_FLAG: value})
    for disabled in ("", "0", "yes", "on", "enabled", "2"):
        assert not grant_evaluator_enabled({GRANT_EVALUATOR_FLAG: disabled})


def test_flag_off_is_callback_parity_and_never_consumes_grant() -> None:
    store = _store()
    first = _evaluate(store, environ={})
    second = _evaluate(store)
    assert (first.outcome, first.reason) == ("disabled", "feature_flag_off")
    assert second.outcome == "would_allow"
    assert first.callback_required and not first.authority_granted
    assert second.callback_required and not second.authority_granted


def test_exact_match_is_shadow_only_and_consumes_bounded_shadow_use() -> None:
    store = _store(_grant(max_uses=1))
    allowed = _evaluate(store)
    exhausted = _evaluate(store)
    assert (allowed.outcome, allowed.grant_id) == ("would_allow", "grant-1")
    assert allowed.callback_required is True and allowed.authority_granted is False
    assert (exhausted.outcome, exhausted.reason) == ("would_deny", "use_limit")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("principal_id", "owner-2"),
        ("session_id", "session-2"),
        ("workspace_id", "workspace-2"),
        ("mission_id", "mission-2"),
        ("capability", "calendar"),
        ("tool", "calendar"),
        ("operation", "read"),
        ("target_sha256", SHA_C),
        ("payload_sha256", SHA_C),
        ("action_digest", SHA_C),
        ("risk", "high"),
        ("data_class", "confidential"),
    ],
)
def test_every_material_scope_drift_denies(field: str, value: object) -> None:
    decision = _evaluate(_store(), _request(**{field: value}))
    assert decision.outcome == "would_deny"
    assert decision.callback_required and not decision.authority_granted


def test_finite_target_set_matches_only_exact_digest() -> None:
    store = _store(_grant(target_sha256=(SHA_A, SHA_C)))
    exact_second = _request(target_sha256=SHA_C, action_digest=_action_digest(target_sha256=SHA_C))
    # The permission digest is separately exact, so a second target also needs
    # its own approved action digest; this v1 grant intentionally stores one.
    assert _evaluate(store, exact_second).outcome == "would_deny"
    assert _evaluate(store, _request()).outcome == "would_allow"


@pytest.mark.parametrize("always_explicit", [True])
def test_always_explicit_action_is_never_covered(always_explicit: bool) -> None:
    decision = _evaluate(_store(), _request(always_explicit=always_explicit))
    assert (decision.outcome, decision.reason) == ("would_deny", "always_explicit")


@pytest.mark.parametrize("risk", ["high", "critical"])
def test_high_and_critical_requests_are_never_covered(risk: str) -> None:
    decision = _evaluate(_store(), _request(risk=risk))
    assert (decision.outcome, decision.reason) == ("would_deny", "risk_not_grantable")


def test_per_action_and_aggregate_cost_bounds_deny() -> None:
    assert _evaluate(_store(), _request(cost_micro=6)).reason == "per_action_cost"
    store = _store(_grant(max_cost_per_action_micro=5, max_cost_aggregate_micro=5, max_uses=3))
    assert _evaluate(store, _request(cost_micro=3)).outcome == "would_allow"
    assert _evaluate(store, _request(cost_micro=3)).reason == "aggregate_cost"


def test_not_before_expiry_policy_and_audit_head_drift_deny() -> None:
    store = _store()
    assert _evaluate(store, now_ms=NOW - 600).outcome == "would_deny"
    assert _evaluate(store, now_ms=NOW + 10_000).outcome == "would_deny"
    assert _evaluate(store, _request(requested_at_ms=NOW - 600)).outcome == "would_deny"
    assert _evaluate(store, _request(requested_at_ms=NOW + 1)).outcome == "would_deny"
    assert _evaluate(store, current_policy_version="changed").outcome == "would_deny"
    assert _evaluate(store, current_audit_head=SHA_C).outcome == "would_deny"


def test_revoke_is_immediate_idempotent_and_prompt_free() -> None:
    store = _store()
    store.revoke("grant-1", reason="owner_revoke", revoked_at_ms=NOW)
    store.revoke("grant-1", reason="owner_revoke", revoked_at_ms=NOW)
    assert _evaluate(store).outcome == "would_deny"


def test_kill_switch_revokes_existing_and_stops_new_grants() -> None:
    store = _store()
    store.kill(at_ms=NOW)
    decision = _evaluate(store)
    assert (decision.outcome, decision.reason) == ("would_deny", "kill_switch")
    with pytest.raises(GrantContractError, match="cannot issue"):
        store.issue(_grant(grant_id="grant-2"))


def test_audit_failure_revokes_existing_and_stops_new_grants() -> None:
    store = _store()
    store.mark_audit_unhealthy(at_ms=NOW)
    decision = _evaluate(store)
    assert (decision.outcome, decision.reason) == ("would_deny", "audit_unhealthy")
    with pytest.raises(GrantContractError, match="cannot issue"):
        store.issue(_grant(grant_id="grant-2"))


def test_restart_constructs_empty_session_store_and_restores_nothing() -> None:
    assert _evaluate(_store()).outcome == "would_allow"
    restarted = SessionGrantStore("session-1")
    decision = _evaluate(restarted)
    assert (decision.outcome, decision.reason) == ("would_deny", "no_exact_unique_grant")


def test_ambiguous_duplicate_scope_denies_instead_of_selecting_one() -> None:
    store = _store()
    store.issue(_grant(grant_id="grant-2"))
    assert _evaluate(store).outcome == "would_deny"


def test_grants_are_frozen_and_no_persistence_api_exists() -> None:
    grant = _grant()
    with pytest.raises(dataclasses.FrozenInstanceError):
        grant.max_uses = 99  # type: ignore[misc]
    assert not hasattr(SessionGrantStore, "save")
    assert not hasattr(SessionGrantStore, "load")
    assert not hasattr(SessionGrantStore, "restore")


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 2},
        {"policy_version": "unknown"},
        {"risk_ceiling": "high"},
        {"target_sha256": ()},
        {"target_sha256": (SHA_A, SHA_A)},
        {"expires_at_ms": NOW - 501},
        {"expires_at_ms": NOW + 24 * 60 * 60 * 1000 + 1},
        {"max_uses": 0},
        {"max_cost_per_action_micro": 6, "max_cost_aggregate_micro": 5},
        {"action_digest": "A" * 64},
    ],
)
def test_malformed_or_overbroad_grants_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(GrantContractError):
        _grant(**changes)


def test_no_startup_ui_dashboard_or_owner_wiring() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        assert "session_grants_v1" not in (root / relative).read_text(encoding="utf-8")
