from __future__ import annotations

import dataclasses
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import core.session_grants_v11 as grants


TARGET = hashlib.sha256(b"target").hexdigest()
PAYLOAD = hashlib.sha256(b"payload").hexdigest()
AUDIT = hashlib.sha256(b"audit").hexdigest()
RESULT = hashlib.sha256(b"result").hexdigest()


def _policy() -> grants.HostActionPolicy:
    return grants.HostActionPolicy("local-files", "file-controller", "write", "low", False, "internal")


def _state(**changes: object) -> grants.HostState:
    values: dict[str, object] = {
        "schema_version": grants.GRANT_SCHEMA_VERSION,
        "policy_version": grants.GRANT_POLICY_VERSION,
        "principal_id": "owner-one",
        "session_id": "session-one",
        "workspace_id": "workspace-one",
        "mission_ids": ("mission-one",),
        "policies": (_policy(),),
        "audit_head": AUDIT,
        "credential_epoch": 1,
        "vault_generation": 1,
        "audit_healthy": True,
        "session_active": True,
        "kill_switch": False,
    }
    values.update(changes)
    return grants.HostState(**values)  # type: ignore[arg-type]


def _binding(**changes: object) -> grants.ActionBinding:
    values: dict[str, object] = {
        "provider": "local-provider",
        "provider_namespace": "desktop-files",
        "target_identity": TARGET,
        "target_display": r"C:\Work\report.txt",
        "payload_digest": PAYLOAD,
        "payload_summary": "Reviewed report",
        "payload_rule_id": "exact-report",
        "egress": "local-only",
        "idempotency_key": "write-report-one",
    }
    values.update(changes)
    return grants.ActionBinding(**values)  # type: ignore[arg-type]


def _scope(binding: grants.ActionBinding | None = None, **changes: object) -> grants.ResolvedGrantScope:
    exact = binding or _binding()
    values: dict[str, object] = {
        "mission_id": "mission-one",
        "capability": "local-files",
        "tool": "file-controller",
        "operation": "write",
        "bindings": (exact,),
        "account": "account-one",
        "path": r"C:\Work",
        "effect": "Write reviewed report",
        "environment": "test-env",
        "data_class": "internal",
        "reversible": True,
        "verification_plan": "Compare SHA-256",
        "rollback_plan": "Restore snapshot",
        "cost_currency": "USD",
        "cost_unit": "micro-units",
        "initial_binding_digest": exact.digest(),
        "initial_cost_micro": 3,
        "max_cost_per_action_micro": 5,
        "max_cost_aggregate_micro": 20,
        "max_uses": 5,
        "not_before_delay_ms": 0,
        "lifetime_ms": 10_000,
    }
    values.update(changes)
    return grants.ResolvedGrantScope(**values)  # type: ignore[arg-type]


def _action(binding: grants.ActionBinding | None = None) -> grants.ResolvedAction:
    return grants.ResolvedAction(
        "mission-one", "local-files", "file-controller", "write", binding or _binding(),
        "account-one", r"C:\Work", "Write reviewed report", "test-env", "internal", True,
        "Compare SHA-256", "Restore snapshot", "USD", "micro-units", 3,
    )


class Host:
    def __init__(self) -> None:
        self.gate = grants.MonotonicFeatureGate(True)
        self.now = 1_000
        self.state_value = _state()
        self.scope_value = _scope()
        self.actions: dict[str, grants.ResolvedAction] = {"action": _action()}
        self.outcomes: dict[str, grants.ResolvedOutcome | str] = {}
        self.store: grants.SessionGrantShadowStore | None = None
        self.receipt_sequence = 0
        self.approval_sequence = 0
        self.reconciliation_sequence = 0
        self.verify_result = True
        self.verify_count = 0
        self.verify_hook = None
        self.reconciliation_outcome = "still-uncertain"
        self.reconcile_count = 0
        self.reconcile_started: threading.Event | None = None
        self.reconcile_release: threading.Event | None = None
        self.reconcile_barrier: threading.Barrier | None = None
        self.after_outcome_hook = None
        self.after_approve_hook = None
        self.after_action_hook = None
        self.after_verify_hook = None
        self.after_reconcile_hook = None
        self.after_grant_hook = None
        self.after_clock_hook = None
        self.after_state_hook = None
        self.state_count = 0
        self.clock_count = 0
        self.state_external_lock: threading.Lock | None = None
        self.state_lock_waiting: threading.Event | None = None
        self.malformed_reconciliation = False
        self.fail_next_state = False

    def resolve_grant(self, _reference: str) -> grants.ResolvedGrantScope:
        result = self.scope_value
        if self.after_grant_hook is not None:
            self.after_grant_hook()
        return result

    def resolve_action(self, reference: str) -> grants.ResolvedAction:
        result = self.actions[reference]
        if self.after_action_hook is not None:
            self.after_action_hook()
        return result

    def _effect_outcome(self, reservation_id: str, status: str) -> grants.ResolvedOutcome:
        assert self.store is not None
        reservation = self.store._reservations.get(reservation_id)
        if reservation is None:
            uncertain = next(item for item in self.store._uncertain_records.values() if item.reservation_id == reservation_id)
            reservation = self.store._reservation_from_uncertain(uncertain)
        self.receipt_sequence += 1
        sequence = self.receipt_sequence
        provider_id = grants._expected_provider_receipt_id(sequence, RESULT)
        placeholder = grants.ReceiptVerificationRequest(
            reservation.receipt_challenge, reservation.session_id, reservation.workspace_id,
            reservation.provider, reservation.provider_namespace, reservation.account,
            reservation.tool, reservation.operation, reservation.reservation_id, reservation.grant_id,
            reservation.scope_digest, reservation.binding_digest, reservation.action_audit_digest,
            reservation.idempotency_key, reservation.idempotency_identity_digest,
            reservation.action_fingerprint,
            provider_id, RESULT, AUDIT,
        )
        receipt_id = grants._expected_receipt_id(sequence, reservation.receipt_challenge)
        receipt_digest = grants.canonical_receipt_digest(placeholder, sequence, receipt_id)
        return grants.ResolvedOutcome(reservation_id, status, RESULT, provider_id, receipt_digest)

    def resolve_outcome(self, reference: str) -> grants.ResolvedOutcome:
        value = self.outcomes[reference]
        if isinstance(value, str):
            reservation_id, status = value.split("|")
            if status in {"verified-effect", "dispatch-attempted-with-evidence"}:
                result = self._effect_outcome(reservation_id, "verified-effect" if status == "verified-effect" else "dispatch-attempted")
            else:
                result = grants.ResolvedOutcome(reservation_id, status, None, None, None)
        else:
            result = value
        if self.after_outcome_hook is not None:
            self.after_outcome_hook()
        return result

    def approve(self, prompt: grants.ApprovalPrompt) -> grants.HostApprovalResponse:
        self.approval_sequence += 1
        sequence = self.approval_sequence
        response = grants.HostApprovalResponse(
            True, grants._expected_attestation_id(sequence, prompt.challenge_digest), sequence,
            prompt.challenge_digest, prompt.scope_digest, prompt.prompt_digest,
        )
        if self.after_approve_hook is not None:
            self.after_approve_hook()
        return response

    def verify_receipt(self, request: grants.ReceiptVerificationRequest) -> grants.HostReceiptVerification:
        self.verify_count += 1
        if self.verify_hook is not None:
            self.verify_hook()
        sequence = int(request.provider_receipt_id.split("-")[1], 16)
        receipt_id = grants._expected_receipt_id(sequence, request.receipt_challenge)
        value = grants.HostReceiptVerification(
            self.verify_result, sequence, receipt_id, request.receipt_challenge,
            request.session_id, request.workspace_id, request.provider, request.provider_namespace,
            request.account, request.tool, request.operation, request.reservation_id, request.grant_id,
            request.scope_digest, request.binding_digest, request.action_audit_digest,
            request.idempotency_key, request.idempotency_identity_digest, request.action_fingerprint,
            request.provider_receipt_id,
            request.result_digest, request.receipt_digest, AUDIT,
        )
        result = dataclasses.replace(value, verification_digest=grants.canonical_verification_digest(value))
        if self.after_verify_hook is not None:
            self.after_verify_hook()
        return result

    def reconcile(self, request: grants.ReconciliationRequest) -> grants.HostReconciliation:
        self.reconcile_count += 1
        if self.reconcile_barrier is not None:
            self.reconcile_barrier.wait(timeout=5)
        if self.reconcile_started is not None and self.reconcile_release is not None:
            self.reconcile_started.set()
            assert self.reconcile_release.wait(timeout=5)
        self.reconciliation_sequence += 1
        sequence = self.reconciliation_sequence
        verification = None
        if self.reconciliation_outcome == "confirmed-effect":
            receipt_sequence = self.receipt_sequence + 1
            self.receipt_sequence = receipt_sequence
            result = request.known_result_digest or RESULT
            provider_id = request.known_provider_receipt_id or grants._expected_provider_receipt_id(receipt_sequence, result)
            placeholder = grants.ReceiptVerificationRequest(
                request.receipt_challenge, request.session_id, request.workspace_id,
                request.provider, request.provider_namespace, request.account, request.tool, request.operation,
                self.store._uncertain_records[request.identity_digest].reservation_id, request.grant_id,
                request.scope_digest, request.binding_digest, request.action_audit_digest,
                request.idempotency_key, request.identity_digest, request.action_fingerprint,
                provider_id, result, AUDIT,
            )
            receipt_id = grants._expected_receipt_id(receipt_sequence, request.receipt_challenge)
            receipt_digest = request.known_receipt_digest or grants.canonical_receipt_digest(placeholder, receipt_sequence, receipt_id)
            exact = dataclasses.replace(placeholder, receipt_digest=receipt_digest)
            verification = self.verify_receipt(exact)
        response = grants.HostReconciliation(
            self.reconciliation_outcome, sequence,
            grants._expected_reconciliation_id(sequence, request.reconciliation_challenge),
            request, verification, AUDIT,
        )
        result = dataclasses.replace(response, reconciliation_digest=grants.canonical_reconciliation_digest(response))
        if self.after_reconcile_hook is not None:
            self.after_reconcile_hook()
        if self.malformed_reconciliation:
            return dataclasses.replace(result, reconciliation_digest="f" * 64)
        return result

    def state(self) -> grants.HostState:
        self.state_count += 1
        if self.state_external_lock is not None:
            if self.state_lock_waiting is not None:
                self.state_lock_waiting.set()
            with self.state_external_lock:
                return self._state_result()
        return self._state_result()

    def _state_result(self) -> grants.HostState:
        if self.after_state_hook is not None:
            self.after_state_hook()
        if self.fail_next_state:
            self.fail_next_state = False
            raise RuntimeError("post-outcome state unavailable")
        return self.state_value

    def monotonic_ms(self) -> int:
        self.clock_count += 1
        if self.after_clock_hook is not None:
            self.after_clock_hook()
        return self.now

    def services(self) -> grants.HostServices:
        return grants.HostServices(
            "desktop-root", self.gate, self.resolve_grant, self.resolve_action, self.resolve_outcome,
            self.approve, self.verify_receipt, self.reconcile, self.state, self.monotonic_ms,
        )


def _ready(monkeypatch: pytest.MonkeyPatch, host: Host | None = None) -> tuple[Host, grants.SessionGrantShadowStore, str]:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    fixture = host or Host()
    store = grants.SessionGrantShadowStore(fixture.services())
    fixture.store = store
    grant_id = store.request_session_grant("grant")
    return fixture, store, grant_id


def test_external_mutation_identity_excludes_grant_and_binding() -> None:
    source = grants.canonical_idempotency_identity(_scope_from_resolved_for_test(), _binding())
    assert len(source) == 64


def _scope_from_resolved_for_test() -> grants.GrantScope:
    resolved = _scope()
    return grants.SessionGrantShadowStore._scope_from_resolved(resolved, _state(), "desktop-root", 1_000)


def test_verified_effect_consumes_and_receipt_is_self_sufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    decision = store.record_outcome(reservation, "done")
    assert decision.committed and decision.reason == "verified-commit"
    assert store._mutation_ledger[identity].state == "consumed_verified"
    assert store._uses[grant_id] == 1
    receipt = next(iter(store._receipts.values()))
    assert receipt.provider == "local-provider" and receipt.idempotency_identity_digest == identity
    store.revoke(grant_id)
    assert receipt == next(iter(store._receipts.values()))


@pytest.mark.parametrize("status", ["cancelled-before-dispatch", "definitive-no-effect"])
def test_definite_no_dispatch_or_effect_releases_for_retry(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|{status}"
    decision = store.record_outcome(reservation, "done")
    if status == "cancelled-before-dispatch":
        assert decision.reason == "uncertain-needs-reconciliation"
        assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"
        with pytest.raises(grants.GrantV11Denied, match="idempotency-uncertain"):
            store.reserve("action")
        host.reconciliation_outcome = "confirmed-no-effect"
        store.reconcile_uncertain(identity)
    else:
        assert decision.reason == status
        assert store._mutation_ledger[identity].state == "definitive_no_effect"
    assert store.reserve("action") != reservation


def test_dispatch_attempt_is_quarantined_and_cannot_retry_across_successor_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|dispatch-attempted"
    assert store.record_outcome(reservation, "done").reason == "uncertain-needs-reconciliation"
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"
    store.revoke(grant_id)
    successor = store.request_session_grant("successor")
    assert successor != grant_id
    assert store.evaluate("action").reason == "idempotency-uncertain"
    with pytest.raises(grants.GrantV11Denied):
        store.reserve("action")


def test_unverified_receipt_remains_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    host = Host()
    host.verify_result = False
    host, store, _grant = _ready(monkeypatch, host)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    assert store.record_outcome(reservation, "done").reason == "uncertain-needs-reconciliation"
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"
    assert identity in store._uncertain_records


def test_confirmed_no_effect_releases_quarantine(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|dispatch-attempted"
    store.record_outcome(reservation, "done")
    host.reconciliation_outcome = "confirmed-no-effect"
    result = store.reconcile_uncertain(identity)
    assert result.outcome == "confirmed-no-effect"
    assert store._mutation_ledger[identity].state == "definitive_no_effect"
    assert identity not in store._uncertain_records
    assert store.reserve("action")


def test_still_uncertain_stays_quarantined(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|dispatch-attempted"
    store.record_outcome(reservation, "done")
    result = store.reconcile_uncertain(identity)
    assert result.outcome == "still-uncertain"
    assert identity in store._uncertain_records
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"


def test_confirmed_effect_consumes_with_full_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|dispatch-attempted"
    store.record_outcome(reservation, "done")
    host.reconciliation_outcome = "confirmed-effect"
    result = store.reconcile_uncertain(identity)
    assert result.outcome == "confirmed-effect" and result.receipt_digest != "0" * 64
    assert store._mutation_ledger[identity].state == "consumed_verified"
    assert identity not in store._uncertain_records
    assert len(store._receipts) == 1


def test_confirmed_effect_preserves_known_quarantined_receipt_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    host = Host()
    host.verify_result = False
    host, store, _grant = _ready(monkeypatch, host)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    store.record_outcome(reservation, "done")
    known = store._uncertain_records[identity].receipt_digest
    host.verify_result = True
    host.reconciliation_outcome = "confirmed-effect"
    result = store.reconcile_uncertain(identity)
    assert result.receipt_digest == known
    assert next(iter(store._receipts.values())).receipt_digest == known


def test_direct_outcome_unrelated_revoke_keeps_uncertain_until_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_a = _ready(monkeypatch)
    alternate = _binding(idempotency_key="write-report-two", target_identity=hashlib.sha256(b"target-two").hexdigest())
    host.scope_value = _scope(alternate)
    host.actions["other"] = _action(alternate)
    grant_b = store.request_session_grant("grant-b")
    reservation = store.reserve("other")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    host.after_outcome_hook = lambda: store.revoke(grant_a)
    result = store.record_outcome(reservation, "done")
    assert not result.committed and result.reason == "uncertain-needs-reconciliation"
    assert identity in store._uncertain_records
    with pytest.raises(grants.GrantV11Denied, match="idempotency-uncertain"):
        store.reserve("other")
    host.after_outcome_hook = None
    host.reconciliation_outcome = "confirmed-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-effect"
    assert store._uses[grant_b] == 1


def test_direct_outcome_same_grant_revoke_never_releases_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    host.after_outcome_hook = lambda: store.revoke(grant_id)
    decision = store.record_outcome(reservation, "done")
    assert decision.reason == "uncertain-needs-reconciliation"
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"
    with pytest.raises(grants.GrantV11Denied):
        store.reserve("action")
    host.after_outcome_hook = None
    host.reconciliation_outcome = "confirmed-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-effect"
    assert store._revocations[grant_id].reason == "owner-revoke"


def test_direct_outcome_malformed_response_keeps_uncertain_and_reconciles(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["bad"] = object()  # type: ignore[assignment]
    with pytest.raises(grants.GrantV11ContractError, match="outcome resolver"):
        store.record_outcome(reservation, "bad")
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"
    with pytest.raises(grants.GrantV11Denied):
        store.reserve("action")
    host.reconciliation_outcome = "confirmed-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-effect"


def test_relevant_revoke_after_dispatch_leaves_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|dispatch-attempted"
    store.record_outcome(reservation, "done")
    store.revoke(grant_id)
    assert identity in store._uncertain_records
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"


def test_concurrent_reconciliation_only_one_response_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|dispatch-attempted"
    store.record_outcome(reservation, "done")
    host.reconciliation_outcome = "confirmed-no-effect"
    host.reconcile_started = threading.Event()
    host.reconcile_release = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(store.reconcile_uncertain, identity)
        assert host.reconcile_started.wait(timeout=5)
        second = pool.submit(store.reconcile_uncertain, identity)
        host.reconcile_release.set()
        outcomes = []
        for future in (first, second):
            try:
                outcomes.append(future.result(timeout=5).outcome)
            except grants.GrantV11Denied:
                outcomes.append("denied")
    assert outcomes.count("confirmed-no-effect") == 1
    assert outcomes.count("denied") == 1


def test_terminal_controls_release_pending_but_preserve_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    uncertain_reservation = store.reserve("action")
    identity = store._reservations[uncertain_reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{uncertain_reservation}|dispatch-attempted"
    store.record_outcome(uncertain_reservation, "done")
    store.kill()
    assert identity in store._uncertain_records
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"


def test_pre_dispatch_transition_survives_absence_timeout_and_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    _host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    notice = store.mark_dispatch_attempted(reservation)
    assert notice.identity_digest == identity and not notice.authority_granted
    store.end_session()
    assert identity in store._uncertain_records
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"


def test_verified_outcome_after_explicit_dispatch_transition_can_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    store.mark_dispatch_attempted(reservation)
    host.outcomes["done"] = f"{reservation}|verified-effect"
    assert store.record_outcome(reservation, "done").committed


def test_identity_contract_has_minimum_namespace_and_no_grant_or_binding_fields() -> None:
    scope = _scope_from_resolved_for_test()
    binding = _binding()
    expected = grants._sha({
        "account": scope.account,
        "contract": "ExternalMutationIdentity.v11",
        "idempotency_key": binding.idempotency_key,
        "operation": scope.operation,
        "provider": binding.provider,
        "provider_namespace": binding.provider_namespace,
        "session_id": scope.session_id,
        "tool": scope.tool,
        "workspace_id": scope.workspace_id,
    })
    assert grants.canonical_idempotency_identity(scope, binding) == expected


def test_same_external_namespace_key_cannot_reserve_across_distinct_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _binding()
    second = _binding(
        target_identity=hashlib.sha256(b"different-target").hexdigest(),
        target_display=r"C:\Work\other.txt",
        payload_digest=hashlib.sha256(b"different-payload").hexdigest(),
    )
    host = Host()
    host.scope_value = _scope(first, bindings=(first, second))
    host.actions["other"] = _action(second)
    _host, store, _grant = _ready(monkeypatch, host)
    store.reserve("action")
    assert store.evaluate("other").reason == "idempotency-action-mismatch"
    with pytest.raises(grants.GrantV11Denied, match="idempotency-action-mismatch"):
        store.reserve("other")


def test_consumed_external_namespace_key_survives_successor_grant_and_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, first_grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    host.outcomes["done"] = f"{reservation}|verified-effect"
    store.record_outcome(reservation, "done")
    store.revoke(first_grant)
    successor_binding = _binding(
        target_identity=hashlib.sha256(b"successor-target").hexdigest(),
        target_display=r"C:\Work\successor.txt",
        payload_digest=hashlib.sha256(b"successor-payload").hexdigest(),
    )
    host.scope_value = _scope(successor_binding)
    host.actions["successor"] = _action(successor_binding)
    store.request_session_grant("successor-grant")
    assert store.evaluate("successor").reason == "idempotency-action-mismatch"


def test_relevant_semantic_drift_after_dispatch_quarantines_verified_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    host.verify_hook = lambda: setattr(host, "state_value", _state(credential_epoch=2))
    decision = store.record_outcome(reservation, "done")
    assert decision.reason == "uncertain-needs-reconciliation"
    assert identity in store._uncertain_records
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"


def test_reconciliation_after_terminal_resolves_once_and_replay_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    store.mark_dispatch_attempted(reservation)
    store.kill()
    host.reconciliation_outcome = "confirmed-no-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-no-effect"
    with pytest.raises(grants.GrantV11Denied, match="already reconciled"):
        store.reconcile_uncertain(identity)


@pytest.mark.parametrize("status", ["cancelled-before-dispatch", "definitive-no-effect"])
def test_released_identity_retries_only_identical_action_fingerprint(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    original = store._reservations[reservation]
    identity = original.idempotency_identity_digest
    fingerprint = original.action_fingerprint
    host.outcomes["done"] = f"{reservation}|{status}"
    store.record_outcome(reservation, "done")
    assert store._mutation_ledger[identity].action_fingerprint == fingerprint
    changed = _binding(
        target_identity=hashlib.sha256(b"released-state-target-change").hexdigest(),
        target_display=r"C:\Work\changed.txt",
        payload_digest=hashlib.sha256(b"released-state-payload-change").hexdigest(),
    )
    host.scope_value = _scope(changed)
    host.actions["changed"] = _action(changed)
    store.revoke(original.grant_id)
    store.request_session_grant("changed-grant")
    assert store.evaluate("changed").reason == "idempotency-action-mismatch"
    assert store._mutation_ledger[identity].action_fingerprint == fingerprint


def test_two_concurrent_still_uncertain_callbacks_cannot_aba_double_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    store.mark_dispatch_attempted(reservation)
    initial = store._uncertain_records[identity]
    host.reconciliation_outcome = "still-uncertain"
    host.reconcile_barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.reconcile_uncertain, identity) for _ in range(2)]
        outcomes: list[str] = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=5).outcome)
            except grants.GrantV11Denied:
                outcomes.append("denied")
    assert outcomes.count("still-uncertain") == 1
    assert outcomes.count("denied") == 1
    current = store._uncertain_records[identity]
    assert current.revision == initial.revision + 1
    assert current.reconciliation_count == 1
    assert current.reconciliation_history_root != initial.reconciliation_history_root


def test_reconciliation_history_is_bounded_per_identity_and_full_capacity_still_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    store.mark_dispatch_attempted(reservation)
    monkeypatch.setattr(grants, "MAX_LEDGER_IDENTITIES", 1)
    assert not hasattr(grants, "MAX_RECONCILIATIONS")
    for _ in range(24):
        assert store.reconcile_uncertain(identity).outcome == "still-uncertain"
    assert not hasattr(store, "_reconciliations")
    assert store._uncertain_records[identity].reconciliation_count == 24
    host.reconciliation_outcome = "confirmed-no-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-no-effect"
    ledger = store._mutation_ledger[identity]
    assert ledger.state == "definitive_no_effect"
    assert ledger.reconciliation_count == 25
    assert ledger.latest_reconciliation_sequence == 25


def test_zero_cost_zero_aggregate_direct_and_reconciled_commits_do_not_exhaust_aggregate(monkeypatch: pytest.MonkeyPatch) -> None:
    zero_scope = _scope(initial_cost_micro=0, max_cost_per_action_micro=0, max_cost_aggregate_micro=0, max_uses=2)
    direct_host = Host()
    direct_host.scope_value = zero_scope
    direct_host.actions["action"] = dataclasses.replace(_action(), cost_micro=0)
    direct_host, direct_store, direct_grant = _ready(monkeypatch, direct_host)
    direct_reservation = direct_store.reserve("action")
    direct_host.outcomes["done"] = f"{direct_reservation}|verified-effect"
    assert direct_store.record_outcome(direct_reservation, "done").committed
    assert direct_grant not in direct_store._revocations

    reconciled_host = Host()
    reconciled_host.scope_value = zero_scope
    reconciled_host.actions["action"] = dataclasses.replace(_action(), cost_micro=0)
    reconciled_host, reconciled_store, reconciled_grant = _ready(monkeypatch, reconciled_host)
    reconciled_reservation = reconciled_store.reserve("action")
    identity = reconciled_store._reservations[reconciled_reservation].idempotency_identity_digest
    reconciled_store.mark_dispatch_attempted(reconciled_reservation)
    reconciled_host.reconciliation_outcome = "confirmed-effect"
    assert reconciled_store.reconcile_uncertain(identity).outcome == "confirmed-effect"
    assert reconciled_grant not in reconciled_store._revocations
    with pytest.raises(grants.GrantV11ContractError, match="revocation_reason"):
        reconciled_store._revoke_locked(reconciled_grant, "reconciled-effect", reconciled_host.now)


def test_default_off_reconciliation_preserves_uncertainty_without_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    store.mark_dispatch_attempted(reservation)
    before = store._uncertain_records[identity]
    host.gate.set_enabled(False)
    with pytest.raises(grants.GrantV11Disabled):
        store.reconcile_uncertain(identity)
    assert host.reconcile_count == 0
    assert store._uncertain_records[identity] == before
    host.gate.set_enabled(True)
    host.reconciliation_outcome = "confirmed-no-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-no-effect"


def test_verified_effect_post_snapshot_failure_preserves_material_for_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    host.after_outcome_hook = lambda: setattr(host, "fail_next_state", True)
    with pytest.raises(grants.GrantV11ContractError, match="snapshot callback failed"):
        store.record_outcome(reservation, "done")
    uncertain = store._uncertain_records[identity]
    assert uncertain.provider_receipt_id is not None
    assert uncertain.result_digest is not None and uncertain.receipt_digest is not None
    assert uncertain.action_fingerprint == store._mutation_ledger[identity].action_fingerprint
    host.after_outcome_hook = None
    host.reconciliation_outcome = "confirmed-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-effect"
    assert store._mutation_ledger[identity].state == "consumed_verified"


def _epoch_aba(host: Host) -> None:
    host.gate.set_enabled(False)
    host.gate.set_enabled(True)


def test_epoch_aba_after_outcome_stops_callbacks_and_preserves_uncertainty(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    host.after_outcome_hook = lambda: _epoch_aba(host)
    with pytest.raises(grants.GrantV11Disabled, match="feature epoch changed"):
        store.record_outcome(reservation, "done")
    uncertain = store._uncertain_records[identity]
    assert uncertain.receipt_digest is None
    assert host.verify_count == 0
    with pytest.raises(grants.GrantV11Denied):
        store.reserve("action")
    host.after_outcome_hook = None
    host.reconciliation_outcome = "confirmed-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-effect"


def test_grant_issue_toggle_after_approval_aborts_without_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = Host()
    store = grants.SessionGrantShadowStore(host.services())
    host.store = store
    host.after_approve_hook = lambda: _epoch_aba(host)
    with pytest.raises(grants.GrantV11Disabled, match="feature epoch changed"):
        store.request_session_grant("grant")
    assert store._grants == {}
    assert store._approvals == set()
    assert store._last_attestation_sequence == 0


def test_host_services_requires_exact_concrete_gate_authority() -> None:
    host = Host()
    services = host.services()

    class DerivedGate(grants.MonotonicFeatureGate):
        pass

    with pytest.raises(grants.GrantV11ContractError, match="exact MonotonicFeatureGate"):
        dataclasses.replace(services, feature_gate=DerivedGate(True))
    with pytest.raises(grants.GrantV11ContractError, match="exact MonotonicFeatureGate"):
        dataclasses.replace(services, feature_gate=lambda: grants.FeatureGateSnapshot(True, 1))  # type: ignore[arg-type]


def test_host_lock_reentry_and_store_snapshot_have_no_ab_ba_deadlock(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    external_lock = threading.Lock()
    host.state_external_lock = external_lock
    host.state_lock_waiting = threading.Event()
    holder_ready = threading.Event()
    results: list[str] = []

    def host_lock_holder() -> None:
        with external_lock:
            holder_ready.set()
            assert host.state_lock_waiting is not None
            assert host.state_lock_waiting.wait(timeout=2)
            results.append(f"snapshot:{store.snapshot_counts()['grants']}")

    def evaluator() -> None:
        assert holder_ready.wait(timeout=2)
        results.append(f"evaluate:{store.evaluate('action').outcome}")

    first = threading.Thread(target=host_lock_holder)
    second = threading.Thread(target=evaluator)
    first.start()
    second.start()
    first.join(timeout=3)
    second.join(timeout=3)
    assert not first.is_alive() and not second.is_alive()
    assert sorted(results) == ["evaluate:would-allow", "snapshot:1"]


@pytest.mark.parametrize("method_name", ["evaluate", "reserve"])
def test_action_callback_toggle_aborts_evaluate_and_reserve_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    host, store, _grant = _ready(monkeypatch)
    before = (store._action_sequence, store._sequence, dict(store._reservations), dict(store._mutation_ledger))
    host.after_action_hook = lambda: _epoch_aba(host)
    with pytest.raises(grants.GrantV11Disabled, match="feature epoch changed"):
        getattr(store, method_name)("action")
    assert store._action_sequence == before[0]
    assert store._reservations == before[2] and store._mutation_ledger == before[3]
    assert next(iter(store._revocations.values())).reason == "feature-gate-epoch"


def test_callback_toggle_then_failure_does_not_run_fail_closed_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    before = (store._fail_closed, store._global_generation, dict(store._revocations))

    def toggle_and_fail() -> None:
        _epoch_aba(host)
        raise RuntimeError("callback failed after feature-token change")

    host.after_action_hook = toggle_and_fail
    with pytest.raises(grants.GrantV11Disabled, match="feature epoch changed"):
        store.evaluate("action")
    assert store._fail_closed == before[0] and store._global_generation == before[1]
    assert next(iter(store._revocations.values())).reason == "feature-gate-epoch"


def test_receipt_verifier_toggle_aborts_commit_without_use_or_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    host.after_verify_hook = lambda: _epoch_aba(host)
    with pytest.raises(grants.GrantV11Disabled, match="feature epoch changed"):
        store.record_outcome(reservation, "done")
    assert store._uses[grant_id] == 0
    assert store._costs[grant_id] == 0
    assert store._receipts == {}
    assert identity in store._uncertain_records
    assert store._mutation_ledger[identity].state == "uncertain_needs_reconciliation"


def test_reconciliation_toggle_after_callback_aborts_without_history_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    store.mark_dispatch_attempted(reservation)
    before_uncertain = store._uncertain_records[identity]
    before_ledger = store._mutation_ledger[identity]
    before_sequence = store._last_reconciliation_sequence
    host.after_reconcile_hook = lambda: _epoch_aba(host)
    with pytest.raises(grants.GrantV11Disabled, match="feature epoch changed"):
        store.reconcile_uncertain(identity)
    assert host.reconcile_count == 1
    assert store._uncertain_records[identity] == before_uncertain
    assert store._mutation_ledger[identity] == before_ledger
    assert store._last_reconciliation_sequence == before_sequence


def test_raw_environment_is_bootstrap_only_and_strict_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(grants.GRANT_EVALUATOR_FLAG, raising=False)
    host = Host()
    host.gate = grants.MonotonicFeatureGate(environ={})
    store = grants.SessionGrantShadowStore(host.services())
    host.store = store
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    with pytest.raises(grants.GrantV11Disabled, match="host gate"):
        store.request_session_grant("grant")
    assert store._grants == {} and host.approval_sequence == 0


def test_off_on_epoch_revokes_old_grant_and_it_never_resurrects(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, old_grant = _ready(monkeypatch)
    old_epoch = store._grants[old_grant].issue_epoch
    _epoch_aba(host)
    decision = store.evaluate("action")
    assert decision.outcome == "would-deny" and decision.reason == "no-exact-grant"
    assert store._revocations[old_grant].reason == "feature-gate-epoch"
    assert store._grants[old_grant].issue_epoch == old_epoch
    new_grant = store.request_session_grant("new-grant")
    assert new_grant != old_grant
    assert store._grants[new_grant].issue_epoch > old_epoch
    assert store.evaluate("action").grant_id == new_grant


@pytest.mark.parametrize("callback_name", ["after_clock_hook", "after_state_hook", "after_grant_hook"])
def test_epoch_aba_is_checked_between_each_snapshot_and_resolver_callback(
    monkeypatch: pytest.MonkeyPatch,
    callback_name: str,
) -> None:
    host, store, grant_id = _ready(monkeypatch)
    before_state = host.state_count
    setattr(host, callback_name, lambda: _epoch_aba(host))
    with pytest.raises(grants.GrantV11Disabled, match="feature epoch changed"):
        store.request_session_grant("next-grant")
    assert store._revocations[grant_id].reason == "feature-gate-epoch"
    assert len(store._grants) == 1
    if callback_name == "after_clock_hook":
        assert host.state_count == before_state


def test_malformed_reconciliation_after_epoch_aba_has_no_extra_fail_closed_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    store.mark_dispatch_attempted(reservation)
    before = store._uncertain_records[identity]
    host.malformed_reconciliation = True
    host.after_reconcile_hook = lambda: _epoch_aba(host)
    with pytest.raises(grants.GrantV11Disabled, match="feature epoch changed"):
        store.reconcile_uncertain(identity)
    assert store._uncertain_records[identity] == before
    assert store._fail_closed is False
    assert store._revocations[grant_id].reason == "feature-gate-epoch"


def _two_binding_host(*, max_uses: int, max_cost: int) -> tuple[Host, grants.ActionBinding]:
    host = Host()
    first = _binding()
    second = _binding(
        target_identity=hashlib.sha256(b"target-two").hexdigest(),
        target_display=r"C:\Work\report-two.txt",
        payload_digest=hashlib.sha256(b"payload-two").hexdigest(),
        idempotency_key="write-report-two",
    )
    host.scope_value = _scope(first, bindings=(first, second), max_uses=max_uses, max_cost_aggregate_micro=max_cost)
    host.actions["other"] = _action(second)
    return host, second


@pytest.mark.parametrize(
    ("max_uses", "max_cost", "expected_reason"),
    [(1, 5, "out-of-scope"), (3, 5, "aggregate-cost")],
)
def test_uncertain_action_holds_provisional_use_and_cost_until_no_effect(
    monkeypatch: pytest.MonkeyPatch,
    max_uses: int,
    max_cost: int,
    expected_reason: str,
) -> None:
    host, _second = _two_binding_host(max_uses=max_uses, max_cost=max_cost)
    host, store, _grant = _ready(monkeypatch, host)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    store.mark_dispatch_attempted(reservation)
    assert store.evaluate("other").reason == expected_reason
    with pytest.raises(grants.GrantV11Denied, match=expected_reason):
        store.reserve("other")
    host.reconciliation_outcome = "confirmed-no-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-no-effect"
    assert store.reserve("other")


def test_concurrent_distinct_bindings_cannot_overbook_one_provisional_use(monkeypatch: pytest.MonkeyPatch) -> None:
    host, _second = _two_binding_host(max_uses=1, max_cost=5)
    _host, store, _grant = _ready(monkeypatch, host)

    def attempt(reference: str) -> str:
        try:
            return store.reserve(reference)
        except grants.GrantV11Denied as exc:
            return f"denied:{exc}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(attempt, ("action", "other")))
    assert sum(item.startswith("reservation-") for item in results) == 1
    assert sum(item.startswith("denied:") for item in results) == 1
    assert len(store._reservations) == 1


def test_confirmed_effect_converts_provisional_capacity_without_double_count(monkeypatch: pytest.MonkeyPatch) -> None:
    host, _second = _two_binding_host(max_uses=2, max_cost=6)
    host, store, grant_id = _ready(monkeypatch, host)
    first = store.reserve("action")
    first_identity = store._reservations[first].idempotency_identity_digest
    store.mark_dispatch_attempted(first)
    host.reconciliation_outcome = "confirmed-effect"
    assert store.reconcile_uncertain(first_identity).outcome == "confirmed-effect"
    assert store._uses[grant_id] == 1 and store._costs[grant_id] == 3
    second = store.reserve("other")
    second_identity = store._reservations[second].idempotency_identity_digest
    store.mark_dispatch_attempted(second)
    assert store.reconcile_uncertain(second_identity).outcome == "confirmed-effect"
    assert store._uses[grant_id] == 2 and store._costs[grant_id] == 6
    assert store._uses[grant_id] <= 2 and store._costs[grant_id] <= 6


def test_old_epoch_uncertainty_reconciles_without_resurrecting_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    store.mark_dispatch_attempted(reservation)
    _epoch_aba(host)
    host.reconciliation_outcome = "confirmed-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-effect"
    assert store._revocations[grant_id].reason == "feature-gate-epoch"
    assert store._uses[grant_id] == 1 and store._costs[grant_id] == 3
    assert identity not in store._uncertain_records
    assert store.evaluate("action").reason == "no-exact-grant"


def test_verified_material_is_persisted_before_post_verifier_snapshot_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant = _ready(monkeypatch)
    reservation = store.reserve("action")
    identity = store._reservations[reservation].idempotency_identity_digest
    host.outcomes["done"] = f"{reservation}|verified-effect"
    host.after_verify_hook = lambda: setattr(host, "fail_next_state", True)
    with pytest.raises(grants.GrantV11ContractError, match="snapshot callback failed"):
        store.record_outcome(reservation, "done")
    uncertain = store._uncertain_records[identity]
    assert uncertain.provider_receipt_id is not None
    assert uncertain.result_digest is not None
    assert uncertain.receipt_digest is not None
    assert uncertain.verification_digest is not None
    assert uncertain.verification_audit_digest is not None
    assert uncertain.verification_verified is True
    assert uncertain.verification_sequence is not None
    assert uncertain.verification_receipt_id is not None
    assert uncertain.verification_challenge == uncertain.receipt_challenge
    host.after_verify_hook = None
    host.reconciliation_outcome = "confirmed-effect"
    assert store.reconcile_uncertain(identity).outcome == "confirmed-effect"
    assert store._mutation_ledger[identity].state == "consumed_verified"
