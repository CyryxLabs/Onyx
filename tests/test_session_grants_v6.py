from __future__ import annotations

import dataclasses
import hashlib
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import core.session_grants_v6 as grants
from scripts import verify_phase5_grants_r6 as evidence_verifier


TARGET_A_ID = hashlib.sha256(b"canonical target a").hexdigest()
TARGET_B_ID = hashlib.sha256(b"canonical target b").hexdigest()
PAYLOAD_A = hashlib.sha256(b"reviewed payload a").hexdigest()
PAYLOAD_B = hashlib.sha256(b"reviewed payload b").hexdigest()
AUDIT_A = hashlib.sha256(b"audit a").hexdigest()
RESULT_A = hashlib.sha256(b"verified result a").hexdigest()
ZERO = "0" * 64
DISPLAY_A = "https://example.com/reports/final"
DISPLAY_B = r"C:\Work\Beta.txt"


def _policy(**overrides: object) -> grants.HostActionPolicy:
    values: dict[str, object] = {"capability": "local-files", "tool": "file-controller", "operation": "write", "risk": "low", "always_explicit": False, "max_data_class": "internal"}
    values.update(overrides)
    return grants.HostActionPolicy(**values)  # type: ignore[arg-type]


def _state(**overrides: object) -> grants.HostState:
    values: dict[str, object] = {"schema_version": grants.GRANT_SCHEMA_VERSION, "policy_version": grants.GRANT_POLICY_VERSION, "principal_id": "owner-one", "session_id": "session-one", "workspace_id": "workspace-one", "mission_ids": ("mission-one", "mission-two"), "policies": (_policy(),), "audit_head": AUDIT_A, "credential_epoch": 7, "vault_generation": 11, "audit_healthy": True, "session_active": True, "kill_switch": False}
    values.update(overrides)
    return grants.HostState(**values)  # type: ignore[arg-type]


def _binding_a(**overrides: object) -> grants.ActionBinding:
    values: dict[str, object] = {"target_identity": TARGET_A_ID, "target_display": DISPLAY_A, "payload_digest": PAYLOAD_A, "payload_summary": "Reviewed report body", "payload_rule_id": "exact-report", "egress": "local-only", "idempotency_key": "report-write-one"}
    values.update(overrides)
    return grants.ActionBinding(**values)  # type: ignore[arg-type]


def _binding_b(**overrides: object) -> grants.ActionBinding:
    values: dict[str, object] = {"target_identity": TARGET_B_ID, "target_display": DISPLAY_B, "payload_digest": PAYLOAD_B, "payload_summary": "Reviewed appendix", "payload_rule_id": "exact-appendix", "egress": "local-only", "idempotency_key": "appendix-write-one"}
    values.update(overrides)
    return grants.ActionBinding(**values)  # type: ignore[arg-type]


def _grant_scope(**overrides: object) -> grants.ResolvedGrantScope:
    a, b = _binding_a(), _binding_b()
    values: dict[str, object] = {"mission_id": "mission-one", "capability": "local-files", "tool": "file-controller", "operation": "write", "bindings": (b, a), "account": "account-one", "path": r"C:\Work\root", "effect": "Write the reviewed report", "environment": "test-env", "data_class": "internal", "reversible": True, "verification_plan": "Read the file and compare its SHA-256 digest", "rollback_plan": "Restore the prior file from the local snapshot", "cost_currency": "USD", "cost_unit": "micro-units", "initial_binding_digest": a.digest(), "initial_cost_micro": 3, "max_cost_per_action_micro": 5, "max_cost_aggregate_micro": 20, "max_uses": 5, "not_before_delay_ms": 0, "lifetime_ms": 10_000}
    values.update(overrides)
    return grants.ResolvedGrantScope(**values)  # type: ignore[arg-type]


def _action(**overrides: object) -> grants.ResolvedAction:
    values: dict[str, object] = {"mission_id": "mission-one", "capability": "local-files", "tool": "file-controller", "operation": "write", "binding": _binding_a(), "account": "account-one", "path": r"C:\Work\root", "effect": "Write the reviewed report", "environment": "test-env", "data_class": "internal", "reversible": True, "verification_plan": "Read the file and compare its SHA-256 digest", "rollback_plan": "Restore the prior file from the local snapshot", "cost_currency": "USD", "cost_unit": "micro-units", "cost_micro": 3}
    values.update(overrides)
    return grants.ResolvedAction(**values)  # type: ignore[arg-type]


class HostFixture:
    def __init__(self) -> None:
        self.clock_value = 1_000
        self.state_value = _state()
        self.state_sequence: list[grants.HostState] = []
        self.clock_sequence: list[int] = []
        self.grant_value: object = _grant_scope()
        self.actions: dict[str, object] = {"action-one": _action(), "action-two": _action(binding=_binding_b())}
        self.outcomes: dict[str, object] = {}
        self.approve_count = 0
        self.resolve_grant_count = 0
        self.resolve_action_count = 0
        self.resolve_outcome_count = 0
        self.verify_receipt_count = 0
        self.prompts: list[grants.ApprovalPrompt] = []
        self.resolve_grant_hook = None
        self.resolve_action_hook = None
        self.resolve_outcome_hook = None
        self.approve_hook = None
        self.verify_receipt_hook = None
        self.verification_mutator = None
        self.clock_hook = None
        self.state_hook = None
        self.outcome_started: threading.Event | None = None
        self.outcome_release: threading.Event | None = None
        self.response_mutator = None
        self.store: grants.SessionGrantShadowStore | None = None
        self._allocated_receipt_sequence = 0
        self._lock = threading.Lock()

    def clock(self) -> int:
        if self.clock_hook:
            self.clock_hook()
        with self._lock:
            if self.clock_sequence:
                return self.clock_sequence.pop(0)
            return self.clock_value

    def state(self) -> grants.HostState:
        if self.state_hook:
            self.state_hook()
        with self._lock:
            if self.state_sequence:
                return self.state_sequence.pop(0)
            return self.state_value

    def resolve_grant(self, _reference: str):
        with self._lock:
            self.resolve_grant_count += 1
        if self.resolve_grant_hook:
            self.resolve_grant_hook()
        return self.grant_value

    def resolve_action(self, reference: str):
        with self._lock:
            self.resolve_action_count += 1
        if self.resolve_action_hook:
            self.resolve_action_hook()
        return self.actions[reference]

    def resolve_outcome(self, reference: str):
        with self._lock:
            self.resolve_outcome_count += 1
        if self.resolve_outcome_hook:
            self.resolve_outcome_hook()
        value = self.outcomes[reference]
        if type(value) is tuple and len(value) == 2:
            reservation_id, status = value
            if status != "verified":
                return grants.ResolvedOutcome(reservation_id, status, None, None, None)
            if self.store is None:
                raise RuntimeError("store is not attached")
            with self._lock:
                self._allocated_receipt_sequence += 1
                receipt_sequence = self._allocated_receipt_sequence
            reservation = self.store._reservations[reservation_id]
            result_digest = RESULT_A
            provider_receipt_id = grants._expected_provider_receipt_id(receipt_sequence, result_digest)
            placeholder = grants.ReceiptVerificationRequest(
                reservation.receipt_challenge,
                reservation.reservation_id,
                reservation.grant_id,
                reservation.scope_digest,
                reservation.binding_digest,
                reservation.action_audit_digest,
                reservation.idempotency_key,
                provider_receipt_id,
                result_digest,
                AUDIT_A,
            )
            receipt_id = grants._expected_receipt_id(receipt_sequence, reservation.receipt_challenge)
            receipt_digest = grants.canonical_receipt_digest(placeholder, receipt_sequence, receipt_id)
            value = grants.ResolvedOutcome(reservation_id, status, result_digest, provider_receipt_id, receipt_digest)
        if self.outcome_started is not None and self.outcome_release is not None:
            self.outcome_started.set()
            if not self.outcome_release.wait(timeout=5):
                raise RuntimeError("outcome barrier timed out")
        return value

    def approve(self, prompt: grants.ApprovalPrompt):
        with self._lock:
            self.approve_count += 1
            sequence = self.approve_count
            self.prompts.append(prompt)
        if self.approve_hook:
            self.approve_hook()
        response = grants.HostApprovalResponse(True, grants._expected_attestation_id(sequence, prompt.challenge_digest), sequence, prompt.challenge_digest, prompt.scope_digest, prompt.prompt_digest)
        if self.response_mutator:
            response = self.response_mutator(response, prompt)
        return response

    def verify_receipt(self, request: grants.ReceiptVerificationRequest):
        with self._lock:
            self.verify_receipt_count += 1
        if self.verify_receipt_hook:
            self.verify_receipt_hook()
        receipt_sequence = int(request.provider_receipt_id.split("-")[1], 16)
        receipt_id = grants._expected_receipt_id(receipt_sequence, request.receipt_challenge)
        value = grants.HostReceiptVerification(
            True,
            receipt_sequence,
            receipt_id,
            request.receipt_challenge,
            request.reservation_id,
            request.grant_id,
            request.scope_digest,
            request.binding_digest,
            request.action_audit_digest,
            request.idempotency_key,
            request.provider_receipt_id,
            request.result_digest,
            request.receipt_digest,
            AUDIT_A,
        )
        value = dataclasses.replace(value, verification_digest=grants.canonical_verification_digest(value))
        if self.verification_mutator:
            value = self.verification_mutator(value, request)
        return value

    def services(self) -> grants.HostServices:
        return grants.HostServices("desktop-root", self.resolve_grant, self.resolve_action, self.resolve_outcome, self.approve, self.verify_receipt, self.state, self.clock)


def _ready(monkeypatch: pytest.MonkeyPatch, scope: grants.ResolvedGrantScope | None = None):
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    if scope is not None:
        host.grant_value = scope
    store = grants.SessionGrantShadowStore(host.services())
    host.store = store
    grant_id = store.request_session_grant("grant-request")
    return host, store, grant_id


def _outcome(reservation_id: str, status: str = "verified") -> tuple[str, str]:
    return reservation_id, status


def test_default_off_is_inert_and_opaque(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(grants.GRANT_EVALUATOR_FLAG, raising=False)
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    decision = store.evaluate("action-one")
    assert (decision.outcome, decision.reason) == ("disabled", "feature-flag-off")
    assert decision.callback_required and not decision.authority_granted
    assert host.resolve_action_count == host.resolve_grant_count == host.resolve_outcome_count == 0
    with pytest.raises(grants.GrantV6Disabled):
        store.request_session_grant("grant-request")
    assert tuple(inspect.signature(store.evaluate).parameters) == ("invocation_ref",)
    assert tuple(inspect.signature(store.reserve).parameters) == ("invocation_ref",)
    assert tuple(inspect.signature(store.record_outcome).parameters) == ("outcome_ref",)


def test_exact_action_bindings_prevent_cartesian_product(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    assert store.evaluate("action-one").outcome == "would-allow"
    assert store.evaluate("action-two").outcome == "would-allow"
    host.actions["cross"] = _action(binding=_binding_a(payload_digest=PAYLOAD_B, payload_summary="Reviewed appendix", payload_rule_id="exact-appendix", idempotency_key="appendix-write-one"))
    assert store.evaluate("cross").outcome == "would-deny"
    prompt = host.prompts[0].human_summary
    assert f"target {DISPLAY_A} identity {TARGET_A_ID} + payload {PAYLOAD_A}" in prompt
    assert f"target c:/Work/Beta.txt identity {TARGET_B_ID} + payload {PAYLOAD_B}" in prompt


@pytest.mark.parametrize("field", ["challenge_digest", "scope_digest", "prompt_digest"])
def test_approval_echoes_bind_exact_challenge_scope_and_prompt(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    host.response_mutator = lambda response, _prompt: dataclasses.replace(response, **{field: ZERO})
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV6ContractError, match="reserved digest"):
        store.request_session_grant("grant-request")
    assert store.snapshot_counts()["grants"] == 0


@pytest.mark.parametrize("policy", [_policy(risk="high"), _policy(risk="critical"), _policy(always_explicit=True)])
def test_high_critical_and_always_explicit_never_granted(monkeypatch: pytest.MonkeyPatch, policy: grants.HostActionPolicy) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    host.state_value = dataclasses.replace(host.state_value, policies=(policy,))
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV6Denied, match="high-risk"):
        store.request_session_grant("grant-request")
    assert host.approve_count == 0


def test_evaluate_and_reserve_do_not_consume_until_verified_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    for _ in range(3):
        assert store.evaluate("action-one").outcome == "would-allow"
    assert store._uses[grant_id] == store._costs[grant_id] == 0
    reservation = store.reserve("action-one")
    assert store._uses[grant_id] == store._costs[grant_id] == 0
    assert store.snapshot_counts()["reservations"] == 1
    host.outcomes["outcome-one"] = _outcome(reservation)
    result = store.record_outcome("outcome-one")
    assert result.committed and not result.authority_granted and result.callback_required
    assert store._uses[grant_id] == 1 and store._costs[grant_id] == 3
    assert store.snapshot_counts()["reservations"] == 0


@pytest.mark.parametrize("status", ["cancelled", "denied", "unverified"])
def test_nonverified_outcome_releases_without_consumption(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    host.outcomes["outcome-one"] = _outcome(reservation, status)
    result = store.record_outcome("outcome-one")
    assert not result.committed and result.reason == status
    assert store._uses[grant_id] == store._costs[grant_id] == 0
    assert store.snapshot_counts()["reservations"] == 0
    record = store._outcome_records[reservation]
    assert record.status == status
    assert record.result_digest is record.provider_receipt_id is record.receipt_digest is None


def test_reservations_bound_outstanding_use_and_cost_without_consuming(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch, _grant_scope(max_uses=1, max_cost_per_action_micro=3, max_cost_aggregate_micro=3))
    store.reserve("action-one")
    with pytest.raises(grants.GrantV6Denied, match="idempotency-pending"):
        store.reserve("action-one")
    assert store._uses[grant_id] == store._costs[grant_id] == 0


@pytest.mark.parametrize("control", ["kill", "mark_audit_unhealthy", "end_session", "revoke"])
def test_concurrent_commit_vs_terminal_control_is_atomic(monkeypatch: pytest.MonkeyPatch, control: str) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    host.outcomes["outcome-one"] = _outcome(reservation)
    host.outcome_started = threading.Event()
    host.outcome_release = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(store.record_outcome, "outcome-one")
        assert host.outcome_started.wait(timeout=5)
        getattr(store, control)(grant_id) if control == "revoke" else getattr(store, control)()
        host.outcome_release.set()
        with pytest.raises(grants.GrantV6Denied):
            future.result(timeout=5)
    assert store._uses[grant_id] == store._costs[grant_id] == 0
    assert store.snapshot_counts()["reservations"] == 0


def test_reservation_expiry_releases_without_consumption(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    expires = store._reservations[reservation].expires_at_ms
    host.outcomes["outcome-one"] = _outcome(reservation)
    host.outcomes["outcome-one"] = host.resolve_outcome("outcome-one")
    host.clock_value = expires
    with pytest.raises(grants.GrantV6Denied, match="reservation"):
        store.record_outcome("outcome-one")
    assert store._uses[grant_id] == store._costs[grant_id] == 0


def test_credential_drift_clears_pending_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    store.reserve("action-one")
    host.state_value = dataclasses.replace(host.state_value, credential_epoch=8)
    assert store.evaluate("action-one").outcome == "would-deny"
    assert store.snapshot_counts()["reservations"] == 0


def test_first_snapshot_is_processed_before_resolver_and_second_cannot_aba(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    host.state_sequence = [dataclasses.replace(host.state_value, kill_switch=True)]
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV6Denied):
        store.request_session_grant("grant-request")
    assert host.resolve_grant_count == host.approve_count == 0

    host = HostFixture()
    original = host.state_value
    changed = dataclasses.replace(original, mission_ids=("mission-one", "mission-two", "mission-three"))
    host.state_sequence = [original, changed, original]
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV6Denied, match="resolver"):
        store.request_session_grant("grant-request")
    assert host.resolve_grant_count == 1 and host.approve_count == 0


def test_first_clock_snapshot_updates_high_water_before_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    host.clock_sequence = [1_500, 1_000, 900]
    store = grants.SessionGrantShadowStore(host.services())
    store.request_session_grant("grant-request")
    assert host.prompts[0].scope.issued_at_ms == 1_500
    assert store._clock_high_water == 1_500


def test_first_snapshot_expiry_is_recorded_before_action_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch, _grant_scope(lifetime_ms=5))
    host.clock_value = 1_005

    def assert_already_revoked() -> None:
        assert store.snapshot_counts()["revocations"] == 1

    host.resolve_action_hook = assert_already_revoked
    assert store.evaluate("action-one").outcome == "would-deny"


def test_clock_arithmetic_edge_and_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    lifetime = 10
    host = HostFixture()
    host.clock_value = grants.MAX_MONOTONIC_MS - lifetime
    host.grant_value = _grant_scope(lifetime_ms=lifetime)
    store = grants.SessionGrantShadowStore(host.services())
    store.request_session_grant("grant-request")
    assert host.prompts[0].scope.expires_at_ms == grants.MAX_MONOTONIC_MS

    host = HostFixture()
    host.clock_value = grants.MAX_MONOTONIC_MS - lifetime + 1
    host.grant_value = _grant_scope(lifetime_ms=lifetime)
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV6ContractError, match="overflows"):
        store.request_session_grant("grant-request")
    assert host.approve_count == 0


@pytest.mark.parametrize("field,value", [("schema_version", 99), ("policy_version", "unknown-policy")])
def test_unknown_schema_policy_stops_before_resolver(monkeypatch: pytest.MonkeyPatch, field: str, value: object) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    tampered = dataclasses.replace(host.state_value)
    object.__setattr__(tampered, field, value)
    host.state_value = tampered
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV6ContractError, match="unknown"):
        store.request_session_grant("grant-request")
    assert host.resolve_grant_count == host.approve_count == 0


@pytest.mark.parametrize("field", ["credential_epoch", "vault_generation"])
def test_credential_rotation_invalidates_permanently(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    original = host.state_value
    host.state_value = dataclasses.replace(original, **{field: getattr(original, field) + 1})
    assert store.evaluate("action-one").outcome == "would-deny"
    assert store.snapshot_counts()["revocations"] == 1
    host.state_value = original
    assert store.evaluate("action-one").outcome == "would-deny"


@pytest.mark.parametrize(
    "display",
    [
        "https://example.com/a\\b", "https://user@example.com/a", "https://%65xample.com/a",
        "https://Example.com/a", "https://example.com./a", "http://127.1/a",
        "http://2130706433/a", "http://0x7f000001/a", "http://127.000.000.001/a",
        "http://127.0.0.256/a", "http://2001:db8::1/a", "http://[2001:0db8::1]/a",
        "https://example.com/%2f", "https://example.com/%2E%2E/a", "https://example.com/a//b",
        r"C:\root\..\escape", r"C:\root\file:ads", r"\\server\share\x", r"C:\CON\x",
    ],
)
def test_target_display_canonicalization_rejects_ambiguous_forms(display: str) -> None:
    with pytest.raises(grants.GrantV6ContractError):
        grants._canonical_target_display(display)


def test_target_display_accepts_strict_ipv4_ipv6_percent_and_preserves_windows_case() -> None:
    assert grants._canonical_target_display("http://127.0.0.1/a") == "http://127.0.0.1/a"
    assert grants._canonical_target_display("http://[2001:db8::1]/%20") == "http://[2001:db8::1]/%20"
    assert grants._canonical_target_display(r"C:\Work\MixedCase.txt") == "c:/Work/MixedCase.txt"


def test_opaque_hex_resource_display_allowed_but_secret_canary_rejected() -> None:
    opaque = "https://example.com/resources/abcdef0123456789abcdef0123456789"
    assert _binding_a(target_display=opaque).target_display == opaque
    secret = "sk-" + "proj-" + "abcdefghijklmnop"
    canary = "https://example.com/" + secret
    with pytest.raises(grants.GrantV6ContractError, match="secret"):
        _binding_a(target_display=canary)


def test_store_and_prompt_never_retain_raw_secret_target(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-" + "proj-" + "abcdefghijklmnop"
    raw_canary = "https://example.com/?token=" + secret
    host, store, _grant_id = _ready(monkeypatch)
    prompt = host.prompts[0].human_summary
    serialized = repr(store._grants) + prompt
    assert raw_canary not in serialized and secret not in serialized
    assert TARGET_A_ID in serialized and DISPLAY_A in serialized
    assert not hasattr(host.prompts[0].scope.bindings[0], "raw_target")


def test_budget_overrun_denies_without_consumption_or_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch, _grant_scope(max_cost_per_action_micro=5, max_cost_aggregate_micro=5))
    host.actions["action-one"] = _action(cost_micro=6)
    assert store.evaluate("action-one").reason == "per-action-cost"
    assert store._uses[grant_id] == store._costs[grant_id] == 0
    assert store.snapshot_counts()["revocations"] == 0
    with pytest.raises(grants.GrantV6Denied, match="per-action-cost"):
        store.reserve("action-one")
    assert store.snapshot_counts()["revocations"] == 0


def test_resolver_and_callback_exceptions_are_typed_and_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    host.store = store
    host.grant_value = {"not": "typed"}
    with pytest.raises(grants.GrantV6ContractError):
        store.request_session_grant("grant-request")
    assert store._fail_closed

    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    host.resolve_grant_hook = lambda: (_ for _ in ()).throw(KeyError("resolver leak"))
    with pytest.raises(grants.GrantV6ContractError, match="callback failed"):
        store.request_session_grant("grant-request")
    assert store._fail_closed


def test_unknown_action_keyerror_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    with pytest.raises(grants.GrantV6ContractError, match="resolve_action callback"):
        store.evaluate("unknown-action")
    assert store._fail_closed


def test_approval_and_outcome_exceptions_are_typed_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    host.approve_hook = lambda: (_ for _ in ()).throw(ValueError("approval leak"))
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV6ContractError, match="approval callback"):
        store.request_session_grant("grant-request")
    assert store._fail_closed

    host, store, _grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    host.outcomes["outcome-one"] = _outcome(reservation)
    host.resolve_outcome_hook = lambda: (_ for _ in ()).throw(KeyError("outcome leak"))
    with pytest.raises(grants.GrantV6ContractError, match="resolve_outcome callback"):
        store.record_outcome("outcome-one")
    assert store._fail_closed and store.snapshot_counts()["reservations"] == 0


def test_state_and_clock_exceptions_are_typed_and_terminal_controls_still_work(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    host.clock = lambda: (_ for _ in ()).throw(ValueError("clock leak"))  # type: ignore[method-assign]
    store._services = dataclasses.replace(store._services, monotonic_ms=host.clock)
    with pytest.raises(grants.GrantV6ContractError, match="snapshot callback"):
        store.evaluate("action-one")
    store.kill()
    assert store._killed and store.snapshot_counts()["reservations"] == 0


def test_every_host_callback_executes_outside_store_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    host.store = store

    def prove_unlocked() -> None:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(store.snapshot_counts).result(timeout=1)["grants"] >= 0

    host.clock_hook = prove_unlocked
    host.state_hook = prove_unlocked
    host.resolve_grant_hook = prove_unlocked
    host.resolve_action_hook = prove_unlocked
    host.resolve_outcome_hook = prove_unlocked
    host.approve_hook = prove_unlocked
    host.verify_receipt_hook = prove_unlocked
    store.request_session_grant("grant-request")
    reservation = store.reserve("action-one")
    host.outcomes["outcome-one"] = _outcome(reservation)
    store.record_outcome("outcome-one")


def test_nested_subclass_and_post_return_mutation_cannot_bypass_invariants(monkeypatch: pytest.MonkeyPatch) -> None:
    class EvilBinding(grants.ActionBinding):
        pass

    evil = EvilBinding(TARGET_A_ID, DISPLAY_A, PAYLOAD_A, "Reviewed", "exact-rule", "local-only", "idem-one")
    with pytest.raises(grants.GrantV6ContractError, match="concrete type"):
        _grant_scope(bindings=(evil,), initial_binding_digest=evil.digest())

    binding = _binding_a()
    scope = _grant_scope(bindings=(binding, _binding_b()), initial_binding_digest=binding.digest())
    object.__setattr__(binding, "payload_digest", PAYLOAD_B)
    assert scope.bindings[0].payload_digest in {PAYLOAD_A, PAYLOAD_B}
    assert {item.digest() for item in scope.bindings} == {_binding_a().digest(), _binding_b().digest()}

    host, store, _grant_id = _ready(monkeypatch, scope)
    object.__setattr__(scope.bindings[0], "payload_digest", ZERO)
    assert all(item.payload_digest != ZERO for item in store._grants[next(iter(store._grants))].scope.bindings)


def test_consumed_approval_set_is_explicit_and_revalidated(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    approval_id = next(iter(store._approvals))
    assert approval_id == store._grants[next(iter(store._grants))].approval_id
    assert all(type(item) is str for item in store._approvals)
    assert not isinstance(store._approvals, dict)


def test_exact_concrete_host_state_and_outcome_types_required(monkeypatch: pytest.MonkeyPatch) -> None:
    class EvilState(grants.HostState):
        pass

    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    host.state_value = EvilState(**{field.name: getattr(host.state_value, field.name) for field in dataclasses.fields(grants.HostState)})
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV6ContractError, match="concrete type"):
        store.request_session_grant("grant-request")
    assert store._fail_closed


def test_concurrent_same_idempotency_reservation_has_single_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch, _grant_scope(max_uses=2, max_cost_per_action_micro=3, max_cost_aggregate_micro=6))
    barrier = threading.Barrier(3)

    def reserve_once():
        barrier.wait(timeout=5)
        try:
            return store.reserve("action-one")
        except grants.GrantV6Denied:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve_once) for _ in range(2)]
        barrier.wait(timeout=5)
        results = [future.result(timeout=5) for future in futures]
    assert sum(item is not None for item in results) == 1
    assert store._uses[grant_id] == store._costs[grant_id] == 0


def test_binding_and_text_limits_are_jointly_satisfiable() -> None:
    bindings = tuple(
        _binding_a(
            target_identity=hashlib.sha256(f"target-{index}".encode()).hexdigest(),
            target_display=f"https://example.com/resource/{index:02d}/" + "a" * 64,
            payload_digest=hashlib.sha256(f"payload-{index}".encode()).hexdigest(),
            payload_summary=(f"summary-{index}-" + "x" * grants.MAX_PAYLOAD_SUMMARY_LENGTH)[: grants.MAX_PAYLOAD_SUMMARY_LENGTH // 2],
            payload_rule_id=f"rule-{index:02d}",
            idempotency_key=f"idem-{index:02d}",
        )
        for index in range(grants.MAX_BINDINGS)
    )
    scope = _grant_scope(
        bindings=bindings,
        initial_binding_digest=bindings[0].digest(),
        effect="e" * grants.MAX_EFFECT_LENGTH,
        verification_plan="v" * grants.MAX_PLAN_LENGTH,
        rollback_plan="r" * grants.MAX_PLAN_LENGTH,
        max_uses=grants.MAX_USES,
        initial_cost_micro=grants.MAX_COST_MICRO,
        max_cost_per_action_micro=grants.MAX_COST_MICRO,
        max_cost_aggregate_micro=grants.MAX_COST_MICRO,
        lifetime_ms=grants.MAX_SESSION_LIFETIME_MS,
    )
    host = HostFixture()
    internal = grants.SessionGrantShadowStore._scope_from_resolved(scope, host.state_value, "desktop-root", 0)
    assert len(internal.bindings) == grants.MAX_BINDINGS
    assert len(grants.SessionGrantShadowStore._human_summary(internal)) <= grants.MAX_PROMPT_LENGTH
    long_display = "https://example.com/" + "a" * (grants.MAX_TARGET_DISPLAY_LENGTH - len("https://example.com/"))
    assert len(_binding_a(target_display=long_display).target_display) == grants.MAX_TARGET_DISPLAY_LENGTH
    assert len(_binding_a(payload_summary="s" * grants.MAX_PAYLOAD_SUMMARY_LENGTH).payload_summary) == grants.MAX_PAYLOAD_SUMMARY_LENGTH


def test_reservation_and_receipt_limits_are_bounded_and_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    host.store = store
    action_refs: list[str] = []
    for grant_index in range(9):
        bindings = tuple(
            _binding_a(
                target_identity=hashlib.sha256(f"target-{grant_index}-{index}".encode()).hexdigest(),
                target_display=f"https://example.com/g/{grant_index}/b/{index}",
                payload_digest=hashlib.sha256(f"payload-{grant_index}-{index}".encode()).hexdigest(),
                payload_summary=f"Reviewed item {grant_index} {index}",
                payload_rule_id=f"rule-g{grant_index:02d}-b{index:02d}",
                idempotency_key=f"idem-g{grant_index:02d}-b{index:02d}",
            )
            for index in range(grants.MAX_BINDINGS)
        )
        environment = f"env-g{grant_index:02d}"
        path = f"https://example.com/scope/g/{grant_index}"
        host.grant_value = _grant_scope(
            bindings=bindings,
            environment=environment,
            path=path,
            initial_binding_digest=bindings[0].digest(),
            initial_cost_micro=0,
            max_cost_per_action_micro=0,
            max_cost_aggregate_micro=0,
            max_uses=grants.MAX_USES,
        )
        store.request_session_grant(f"grant-request-{grant_index}")
        for index, binding in enumerate(bindings):
            ref = f"action-g{grant_index:02d}-b{index:02d}"
            host.actions[ref] = _action(binding=binding, environment=environment, path=path, cost_micro=0)
            action_refs.append(ref)
    reservations = [store.reserve(ref) for ref in action_refs[: grants.MAX_RESERVATIONS]]
    assert len(reservations) == grants.MAX_RESERVATIONS
    with pytest.raises(grants.GrantV6CapacityError, match="reservation capacity"):
        store.reserve(action_refs[grants.MAX_RESERVATIONS])
    for index, reservation in enumerate(reservations):
        ref = f"cancel-{index:03d}"
        host.outcomes[ref] = _outcome(reservation, "cancelled")
        store.record_outcome(ref)
    assert store.snapshot_counts()["reservations"] == 0

    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    host.store = store
    for index in range(grants.MAX_RECEIPTS + 1):
        host.grant_value = _grant_scope(initial_cost_micro=0, max_cost_per_action_micro=0, max_cost_aggregate_micro=0, max_uses=1)
        store.request_session_grant(f"receipt-grant-{index:04d}")
        host.actions["action-one"] = _action(cost_micro=0)
        reservation = store.reserve("action-one")
        ref = f"receipt-{index:04d}"
        host.outcomes[ref] = _outcome(reservation)
        store.record_outcome(ref)
    assert store.snapshot_counts()["receipts"] == grants.MAX_RECEIPTS
    assert store.snapshot_counts()["outcomes"] == grants.MAX_OUTCOMES


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("receipt_challenge", PAYLOAD_B),
        ("reservation_id", "reservation-99999999"),
        ("grant_id", "grant-99999999"),
        ("scope_digest", PAYLOAD_B),
        ("binding_digest", PAYLOAD_B),
        ("action_audit_digest", PAYLOAD_B),
        ("idempotency_key", "different-idem"),
        ("provider_receipt_id", "provider-0000000000000001-deadbeef"),
        ("result_digest", PAYLOAD_B),
        ("receipt_digest", PAYLOAD_B),
    ],
)
def test_receipt_verification_binds_every_exact_echo(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    host.outcomes["outcome-one"] = _outcome(reservation)

    def mutate(value: grants.HostReceiptVerification, _request: grants.ReceiptVerificationRequest):
        changed = dataclasses.replace(value, **{field: replacement})
        return dataclasses.replace(changed, verification_digest=grants.canonical_verification_digest(changed))

    host.verification_mutator = mutate
    with pytest.raises(grants.GrantV6ContractError):
        store.record_outcome("outcome-one")
    assert store._uses[grant_id] == store._costs[grant_id] == 0
    assert store._fail_closed and store.snapshot_counts()["reservations"] == 0


@pytest.mark.parametrize("reserved", ["0" * 64, "f" * 64])
def test_reserved_digest_rejected_at_receipt_and_action_boundaries(reserved: str) -> None:
    with pytest.raises(grants.GrantV6ContractError, match="reserved digest"):
        _binding_a(payload_digest=reserved)
    with pytest.raises(grants.GrantV6ContractError, match="reserved digest"):
        grants.ResolvedOutcome(
            "reservation-00000001",
            "verified",
            reserved,
            "provider-0000000000000001-deadbeef",
            PAYLOAD_A,
        )
    with pytest.raises(grants.GrantV6ContractError, match="reserved digest"):
        grants.ResolvedOutcome(
            "reservation-00000001",
            "verified",
            RESULT_A,
            "provider-0000000000000001-deadbeef",
            reserved,
        )


def test_outcome_status_alone_never_commits_without_typed_receipt_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    host.outcomes["outcome-one"] = _outcome(reservation)
    host.verification_mutator = lambda value, _request: dataclasses.replace(
        dataclasses.replace(value, verified=False),
        verification_digest=grants.canonical_verification_digest(dataclasses.replace(value, verified=False)),
    )
    result = store.record_outcome("outcome-one")
    assert not result.committed and result.reason == "unverified"
    assert host.verify_receipt_count == 1
    assert store._uses[grant_id] == store._costs[grant_id] == 0


def test_idempotency_releases_on_cancel_and_consumes_only_after_verified_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    first = store.reserve("action-one")
    assert store.evaluate("action-one").reason == "idempotency-pending"
    host.outcomes["cancel-first"] = _outcome(first, "cancelled")
    assert not store.record_outcome("cancel-first").committed
    assert store.evaluate("action-one").outcome == "would-allow"

    second = store.reserve("action-one")
    host.outcomes["commit-second"] = _outcome(second)
    assert store.record_outcome("commit-second").committed
    assert store.evaluate("action-one").reason == "idempotency-consumed"
    with pytest.raises(grants.GrantV6Denied, match="idempotency-consumed"):
        store.reserve("action-one")
    assert store._uses[grant_id] == 1 and store._costs[grant_id] == 3


def test_unverified_receipt_releases_idempotency_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    host.outcomes["unverified-first"] = _outcome(reservation)

    def reject(value: grants.HostReceiptVerification, _request: grants.ReceiptVerificationRequest):
        changed = dataclasses.replace(value, verified=False)
        return dataclasses.replace(changed, verification_digest=grants.canonical_verification_digest(changed))

    host.verification_mutator = reject
    assert not store.record_outcome("unverified-first").committed
    host.verification_mutator = None
    retry = store.reserve("action-one")
    assert retry != reservation


def test_receipt_replay_cannot_commit_distinct_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    first = store.reserve("action-one")
    host.outcomes["first"] = _outcome(first)
    captured: list[grants.HostReceiptVerification] = []
    host.verification_mutator = lambda value, _request: captured.append(value) or value
    assert store.record_outcome("first").committed

    second = store.reserve("action-two")
    host.outcomes["second"] = _outcome(second)
    host.verification_mutator = lambda _value, _request: captured[0]
    with pytest.raises(grants.GrantV6ContractError, match="exact action"):
        store.record_outcome("second")
    assert store._uses[grant_id] == 1 and store._fail_closed


def test_duplicate_provider_receipt_identity_is_rejected_by_lifetime_high_water(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    first = store.reserve("action-one")
    host.outcomes["first"] = _outcome(first)
    assert store.record_outcome("first").committed
    provider_id = next(iter(store._provider_receipt_ids))

    second = store.reserve("action-two")
    reservation = store._reservations[second]
    placeholder = grants.ReceiptVerificationRequest(
        reservation.receipt_challenge,
        reservation.reservation_id,
        reservation.grant_id,
        reservation.scope_digest,
        reservation.binding_digest,
        reservation.action_audit_digest,
        reservation.idempotency_key,
        provider_id,
        RESULT_A,
        AUDIT_A,
    )
    receipt_id = grants._expected_receipt_id(1, reservation.receipt_challenge)
    receipt_digest = grants.canonical_receipt_digest(placeholder, 1, receipt_id)
    host.outcomes["duplicate-provider"] = grants.ResolvedOutcome(second, "verified", RESULT_A, provider_id, receipt_digest)
    with pytest.raises(grants.GrantV6Denied, match="replay"):
        store.record_outcome("duplicate-provider")
    assert store._uses[grant_id] == 1 and store.evaluate("action-two").outcome == "would-allow"


def test_receipt_high_water_survives_bounded_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grants, "MAX_RECEIPTS", 1)
    host, store, _grant_id = _ready(monkeypatch)
    first = store.reserve("action-one")
    host.outcomes["first"] = _outcome(first)
    assert store.record_outcome("first").committed
    first_sequence = store._last_receipt_sequence
    second = store.reserve("action-two")
    host.outcomes["second"] = _outcome(second)
    assert store.record_outcome("second").committed
    assert len(store._receipts) == 1
    assert store._last_receipt_sequence > first_sequence


def test_receipt_challenges_are_distinct_nonreserved_and_not_host_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    _host, store, _grant_id = _ready(monkeypatch)
    first = store.reserve("action-one")
    second = store.reserve("action-two")
    challenges = {store._reservations[first].receipt_challenge, store._reservations[second].receipt_challenge}
    assert len(challenges) == 2
    assert not challenges & grants._RESERVED_DIGESTS


def test_receipt_verifier_exception_is_typed_and_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    host.outcomes["outcome-one"] = _outcome(reservation)
    host.verify_receipt_hook = lambda: (_ for _ in ()).throw(KeyError("verifier leak"))
    with pytest.raises(grants.GrantV6ContractError, match="receipt verifier callback"):
        store.record_outcome("outcome-one")
    assert store._fail_closed and grant_id in store._revocations


def test_receipt_verifier_requires_exact_concrete_type(monkeypatch: pytest.MonkeyPatch) -> None:
    class EvilVerification(grants.HostReceiptVerification):
        pass

    host, store, _grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    host.outcomes["outcome-one"] = _outcome(reservation)

    def evil(value: grants.HostReceiptVerification, _request: grants.ReceiptVerificationRequest):
        return EvilVerification(**{field.name: getattr(value, field.name) for field in dataclasses.fields(value)})

    host.verification_mutator = evil
    with pytest.raises(grants.GrantV6ContractError, match="concrete type"):
        store.record_outcome("outcome-one")
    assert store._fail_closed


def test_concurrent_duplicate_outcome_commits_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action-one")
    host.outcomes["duplicate"] = _outcome(reservation)
    host.outcomes["duplicate"] = host.resolve_outcome("duplicate")
    barrier = threading.Barrier(3)

    def commit_once():
        barrier.wait(timeout=5)
        try:
            return store.record_outcome("duplicate").committed
        except grants.GrantV6Denied:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(commit_once) for _ in range(2)]
        barrier.wait(timeout=5)
        results = [future.result(timeout=5) for future in futures]
    assert results.count(True) == 1
    assert store._uses[grant_id] == 1


@pytest.mark.parametrize(
    "display",
    ["//server/path", "https://example.com/%41", "https://example.com/%4a", "https://example.com/%4A", "https://example.com/%2a"],
)
def test_r6_canonicalization_rejects_posix_double_slash_and_percent_aliases(display: str) -> None:
    with pytest.raises(grants.GrantV6ContractError):
        grants._canonical_target_display(display)


def test_r6_canonicalization_accepts_uppercase_allowed_percent_escape() -> None:
    assert grants._canonical_target_display("https://example.com/%2A") == "https://example.com/%2A"


def test_evidence_relative_import_closure_rejects_omission(tmp_path) -> None:
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("from . import helper\n", encoding="utf-8")
    (tmp_path / "pkg" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "sub" / "__init__.py").write_text("from .worker import run\n", encoding="utf-8")
    (tmp_path / "pkg" / "sub" / "worker.py").write_text("from ..helper import VALUE\ndef run(): return VALUE\n", encoding="utf-8")
    closure = evidence_verifier.local_import_closure(tmp_path, ("pkg/sub/__init__.py",))
    assert closure == ("pkg/__init__.py", "pkg/helper.py", "pkg/sub/__init__.py", "pkg/sub/worker.py")
    with pytest.raises(evidence_verifier.Phase5GrantR6EvidenceError, match="dependency"):
        evidence_verifier._require_equal(list(closure[:-1]), list(closure), "dependency")


def test_evidence_junit_requires_real_testcases_and_reconciles_failures(tmp_path) -> None:
    path = tmp_path / evidence_verifier.JUNIT
    path.parent.mkdir(parents=True)
    path.write_text('<testsuites><testsuite tests="51" failures="0" errors="0" skipped="0" timestamp="2026-07-20T00:00:00-04:00"/></testsuites>', encoding="utf-8")
    with pytest.raises(evidence_verifier.Phase5GrantR6EvidenceError, match="no testcase"):
        evidence_verifier._junit_counts(tmp_path)
    path.write_text('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0" timestamp="2026-07-20T00:00:00-04:00"><testcase><failure/></testcase></testsuite></testsuites>', encoding="utf-8")
    with pytest.raises(evidence_verifier.Phase5GrantR6EvidenceError, match="testcase"):
        evidence_verifier._junit_counts(tmp_path)


def test_evidence_normative_graph_rejects_explicit_parent_omission() -> None:
    omitted = tuple(item for item in evidence_verifier.NORMATIVE_NODES if item != "docs/onyx/VERIFICATION_EVIDENCE.md")
    with pytest.raises(evidence_verifier.Phase5GrantR6EvidenceError, match="recursive normative set"):
        evidence_verifier.derive_normative_graph(evidence_verifier.PROJECT, omitted)
    assert evidence_verifier.derive_normative_graph(evidence_verifier.PROJECT) == evidence_verifier.NORMATIVE_GRAPH
    assert "docs/MISSIONS.md" in evidence_verifier.NORMATIVE_NODES
    assert sum("/adrs/ADR-" in item for item in evidence_verifier.NORMATIVE_NODES) == 5


def test_evidence_reconstructs_v1_through_v5_and_rejects_history_drift() -> None:
    history = evidence_verifier._run_history(evidence_verifier.PROJECT)
    assert {name: item["artifacts"] if "artifacts" in item else item["files"] for name, item in history.items()} == {"v1": 10, "v2": 8, "v3": 11, "v4": 20, "v5": 32}
    tampered = {**history, "v5": {**history["v5"], "artifacts": 31}}
    with pytest.raises(evidence_verifier.Phase5GrantR6EvidenceError, match="history"):
        evidence_verifier._require_equal(tampered, history, "history")


def test_evidence_limits_and_semantic_claims_are_code_derived(tmp_path) -> None:
    limits = evidence_verifier._constants(evidence_verifier.PROJECT)
    assert set(limits) == set(evidence_verifier._LIMIT_CONSTANTS)
    assert limits["max_reservations"] == grants.MAX_RESERVATIONS
    assert limits["max_bindings"] == grants.MAX_BINDINGS
    with pytest.raises(evidence_verifier.Phase5GrantR6EvidenceError, match="limits"):
        evidence_verifier._require_equal({**limits, "max_bindings": 999}, limits, "limits")
    evidence_verifier._validate_code_claims(evidence_verifier.PROJECT)
    source = (evidence_verifier.PROJECT / "core/session_grants_v6.py").read_text(encoding="utf-8")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "session_grants_v6.py").write_text(source.replace("    target_identity: str\n", ""), encoding="utf-8")
    with pytest.raises(evidence_verifier.Phase5GrantR6EvidenceError, match="binding claim"):
        evidence_verifier._validate_code_claims(tmp_path)


def test_evidence_manifest_bundle_and_whitespace_scope_are_exact(tmp_path) -> None:
    manifest = tmp_path / "manifest.sha256"
    manifest.write_bytes(("0" * 64 + "  b\n" + "1" * 64 + "  a\n").encode())
    with pytest.raises(evidence_verifier.Phase5GrantR6EvidenceError, match="set/order"):
        evidence_verifier._parse_manifest(manifest, ("a", "b"))
    bundle = tmp_path / evidence_verifier.BUNDLE
    bundle.parent.mkdir(parents=True)
    value = {key: None for key in evidence_verifier._BUNDLE_KEYS}
    value["self_sha256"] = ZERO
    bundle.write_text(__import__("json").dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(evidence_verifier.Phase5GrantR6EvidenceError, match="shape"):
        evidence_verifier._read_bundle(tmp_path)
    assert evidence_verifier.WHITESPACE_SCOPE == [
        "core/session_grants_v6.py", "scripts/check_phase5_grants_r6_whitespace.py",
        "scripts/verify_phase5_grants_r6.py", "tests/test_session_grants_v6.py",
    ]


def test_no_runtime_wiring_and_frozen_shadow_flags() -> None:
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    assert evidence_verifier._run_static_gates(root)["live_entrypoint_scan"] == 0
    for relative in evidence_verifier.LIVE_ENTRYPOINTS:
        assert "session_grants_v6" not in (root / relative).read_text(encoding="utf-8")
    decision = grants.ShadowGrantDecision("would-deny", "no-exact-grant", None, ZERO, "1" * 64)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        decision.authority_granted = True  # type: ignore[misc]
