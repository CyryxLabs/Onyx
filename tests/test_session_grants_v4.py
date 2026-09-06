from __future__ import annotations

import dataclasses
import hashlib
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import core.session_grants_v4 as grants
from scripts import verify_phase5_grants_r4 as evidence_verifier


PAYLOAD_A = hashlib.sha256(b"reviewed payload a").hexdigest()
PAYLOAD_B = hashlib.sha256(b"reviewed payload b").hexdigest()
AUDIT_A = hashlib.sha256(b"audit a").hexdigest()
TARGET_A_RAW = "HTTPS://Example.com:443/reports/final"
TARGET_A = "https://example.com/reports/final"
TARGET_B_RAW = r"C:\Work\Beta.txt"
TARGET_B = "c:/work/beta.txt"


def _policy(**overrides: object) -> grants.HostActionPolicy:
    values: dict[str, object] = {
        "capability": "local-files",
        "tool": "file-controller",
        "operation": "write",
        "risk": "low",
        "always_explicit": False,
        "max_data_class": "internal",
    }
    values.update(overrides)
    return grants.HostActionPolicy(**values)  # type: ignore[arg-type]


def _state(**overrides: object) -> grants.HostState:
    values: dict[str, object] = {
        "schema_version": grants.GRANT_SCHEMA_VERSION,
        "policy_version": grants.GRANT_POLICY_VERSION,
        "principal_id": "owner-one",
        "session_id": "session-one",
        "workspace_id": "workspace-one",
        "mission_ids": ("mission-one", "mission-two"),
        "policies": (_policy(),),
        "audit_head": AUDIT_A,
        "audit_healthy": True,
        "session_active": True,
        "kill_switch": False,
    }
    values.update(overrides)
    return grants.HostState(**values)  # type: ignore[arg-type]


def _payload(**overrides: object) -> grants.AllowedPayload:
    values: dict[str, object] = {
        "payload_digest": PAYLOAD_A,
        "summary": "Reviewed report body",
        "rule_id": "exact-report",
        "egress": "local-only",
        "idempotency_key": "report-write-one",
    }
    values.update(overrides)
    return grants.AllowedPayload(**values)  # type: ignore[arg-type]


def _grant_scope(**overrides: object) -> grants.ResolvedGrantScope:
    values: dict[str, object] = {
        "mission_id": "mission-one",
        "capability": "local-files",
        "tool": "file-controller",
        "operation": "write",
        "targets": (TARGET_B_RAW, TARGET_A_RAW),
        "account": "account-one",
        "path": r"C:\Work\root",
        "effect": "Write the reviewed report",
        "environment": "test-env",
        "data_class": "internal",
        "payloads": (_payload(), _payload(payload_digest=PAYLOAD_B, summary="Reviewed appendix", rule_id="exact-appendix", idempotency_key="appendix-write-one")),
        "reversible": True,
        "verification_plan": "Read the file and compare its SHA-256 digest",
        "rollback_plan": "Restore the prior file from the local snapshot",
        "cost_currency": "USD",
        "cost_unit": "micro-units",
        "initial_target": TARGET_A_RAW,
        "initial_payload_digest": PAYLOAD_A,
        "initial_cost_micro": 3,
        "max_cost_per_action_micro": 5,
        "max_cost_aggregate_micro": 20,
        "max_uses": 5,
        "not_before_delay_ms": 0,
        "lifetime_ms": 10_000,
    }
    values.update(overrides)
    return grants.ResolvedGrantScope(**values)  # type: ignore[arg-type]


def _action(**overrides: object) -> grants.ResolvedAction:
    values: dict[str, object] = {
        "mission_id": "mission-one",
        "capability": "local-files",
        "tool": "file-controller",
        "operation": "write",
        "target": TARGET_A_RAW,
        "account": "account-one",
        "path": r"C:\Work\root",
        "effect": "Write the reviewed report",
        "environment": "test-env",
        "data_class": "internal",
        "payload_digest": PAYLOAD_A,
        "payload_summary": "Reviewed report body",
        "payload_rule_id": "exact-report",
        "egress": "local-only",
        "idempotency_key": "report-write-one",
        "reversible": True,
        "verification_plan": "Read the file and compare its SHA-256 digest",
        "rollback_plan": "Restore the prior file from the local snapshot",
        "cost_currency": "USD",
        "cost_unit": "micro-units",
        "cost_micro": 3,
    }
    values.update(overrides)
    return grants.ResolvedAction(**values)  # type: ignore[arg-type]


class HostFixture:
    def __init__(self) -> None:
        self.clock_value = 1_000
        self.state_value = _state()
        self.grant_value: grants.ResolvedGrantScope = _grant_scope()
        self.actions = {"action-one": _action(), "action-two": _action(target=TARGET_B_RAW, payload_digest=PAYLOAD_B, payload_summary="Reviewed appendix", payload_rule_id="exact-appendix", idempotency_key="appendix-write-one")}
        self.approve_count = 0
        self.resolve_grant_count = 0
        self.resolve_action_count = 0
        self.prompts: list[grants.ApprovalPrompt] = []
        self.approve_hook = None
        self.state_hook = None
        self.clock_hook = None
        self.response_mutator = None
        self.approve_started: threading.Event | None = None
        self.approve_release: threading.Event | None = None
        self._lock = threading.Lock()

    def clock(self) -> int:
        hook = self.clock_hook
        if hook is not None:
            hook()
        return self.clock_value

    def state(self) -> grants.HostState:
        hook = self.state_hook
        if hook is not None:
            hook()
        return self.state_value

    def resolve_grant(self, _reference: str) -> grants.ResolvedGrantScope:
        with self._lock:
            self.resolve_grant_count += 1
        return self.grant_value

    def resolve_action(self, reference: str) -> grants.ResolvedAction:
        with self._lock:
            self.resolve_action_count += 1
        return self.actions[reference]

    def approve(self, prompt: grants.ApprovalPrompt) -> grants.HostApprovalResponse:
        with self._lock:
            self.approve_count += 1
            sequence = self.approve_count
            self.prompts.append(prompt)
        if self.approve_started is not None and self.approve_release is not None:
            self.approve_started.set()
            if not self.approve_release.wait(timeout=5):
                raise RuntimeError("approval barrier timed out")
        if self.approve_hook is not None:
            self.approve_hook()
        response = grants.HostApprovalResponse(
            True,
            grants._expected_attestation_id(sequence, prompt.challenge_digest),
            sequence,
            prompt.challenge_digest,
            prompt.scope_digest,
            prompt.prompt_digest,
        )
        if self.response_mutator is not None:
            response = self.response_mutator(response, prompt)
        return response

    def services(self) -> grants.HostServices:
        return grants.HostServices("desktop-root", self.resolve_grant, self.resolve_action, self.approve, self.state, self.clock)


def _ready(monkeypatch: pytest.MonkeyPatch, scope: grants.ResolvedGrantScope | None = None):
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    if scope is not None:
        host.grant_value = scope
    store = grants.SessionGrantShadowStore(host.services())
    grant_id = store.request_session_grant("grant-request")
    return host, store, grant_id


def test_default_off_is_inert_and_public_surface_is_opaque(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(grants.GRANT_EVALUATOR_FLAG, raising=False)
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    decision = store.evaluate("action-one")
    assert (decision.outcome, decision.reason) == ("disabled", "feature-flag-off")
    assert decision.callback_required and not decision.authority_granted
    assert host.resolve_action_count == host.resolve_grant_count == host.approve_count == 0
    with pytest.raises(grants.GrantV4Disabled):
        store.request_session_grant("grant-request")
    assert tuple(inspect.signature(store.evaluate).parameters) == ("invocation_ref",)
    assert tuple(inspect.signature(store.request_session_grant).parameters) == ("invocation_ref",)


def test_prompt_and_action_bind_complete_exact_payload_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    prompt = host.prompts[0]
    for value in (
        TARGET_A, TARGET_B, "account-one", "test-env", "Write the reviewed report",
        PAYLOAD_A, PAYLOAD_B, "Reviewed report body", "Reviewed appendix", "local-only",
        "internal", "low", "reversible True", "report-write-one", "appendix-write-one",
        "Read the file", "Restore the prior file", "USD", "micro-units",
    ):
        assert value in prompt.human_summary
    first = store.evaluate("action-one")
    second = store.evaluate("action-two")
    assert first.outcome == second.outcome == "would-allow"
    assert first.grant_id == second.grant_id == grant_id
    assert first.scope_digest == second.scope_digest
    assert first.action_audit_digest != second.action_audit_digest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("payload_digest", hashlib.sha256(b"changed").hexdigest()),
        ("payload_summary", "Changed summary"),
        ("payload_rule_id", "other-rule"),
        ("egress", "named-account"),
        ("idempotency_key", "other-key"),
        ("reversible", False),
        ("verification_plan", "Different verification"),
        ("rollback_plan", "Different rollback"),
        ("cost_currency", "EUR"),
        ("cost_unit", "cents"),
        ("target", "https://example.com/other"),
        ("account", "account-two"),
        ("environment", "prod-env"),
    ],
)
def test_every_material_action_substitution_denies(monkeypatch: pytest.MonkeyPatch, field: str, value: object) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    host.actions["action-one"] = _action(**{field: value})
    assert store.evaluate("action-one").outcome == "would-deny"


@pytest.mark.parametrize("echo", ["challenge_digest", "scope_digest", "prompt_digest"])
def test_approval_must_echo_exact_challenge_scope_and_prompt(monkeypatch: pytest.MonkeyPatch, echo: str) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    host.response_mutator = lambda response, _prompt: dataclasses.replace(response, **{echo: "0" * 64})
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV4Denied, match="exact prompt"):
        store.request_session_grant("grant-request")
    assert store.snapshot_counts()["grants"] == 0


def test_attestation_id_is_sequence_bound_and_high_water_survives_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    issued = [store.request_session_grant(f"grant-{index:03d}") for index in range(grants.MAX_GRANTS)]
    first_approval_id = store._grants[issued[0]].approval_id
    store.revoke(issued[0])
    store.request_session_grant("grant-replacement")
    assert first_approval_id not in store._approvals
    store.revoke(issued[1])
    host.response_mutator = lambda response, prompt: dataclasses.replace(
        response,
        attestation_id=grants._expected_attestation_id(1, prompt.challenge_digest),
        attestation_sequence=1,
    )
    with pytest.raises(grants.GrantV4Denied):
        store.request_session_grant("grant-replay")
    assert store._last_attestation_sequence == grants.MAX_GRANTS + 1


def test_reused_attestation_id_with_changed_sequence_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    first = store.request_session_grant("grant-one")
    first_id = store._grants[first].approval_id
    host.response_mutator = lambda response, _prompt: dataclasses.replace(
        response, attestation_id=first_id, attestation_sequence=2
    )
    with pytest.raises(grants.GrantV4Denied, match="structurally bound"):
        store.request_session_grant("grant-two")


def test_unknown_schema_or_policy_fails_before_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    for field, value in (("schema_version", 99), ("policy_version", "unknown-policy")):
        host = HostFixture()
        tampered = dataclasses.replace(host.state_value)
        object.__setattr__(tampered, field, value)
        host.state_value = tampered
        store = grants.SessionGrantShadowStore(host.services())
        with pytest.raises(grants.GrantV4ContractError, match="unknown"):
            store.request_session_grant("grant-request")
        assert host.approve_count == 0


def test_unknown_version_drift_fails_closed_and_cannot_resurrect(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    original = host.state_value
    tampered = dataclasses.replace(original)
    object.__setattr__(tampered, "schema_version", grants.GRANT_SCHEMA_VERSION + 1)
    host.state_value = tampered
    with pytest.raises(grants.GrantV4ContractError, match="unknown"):
        store.evaluate("action-one")
    assert store.snapshot_counts()["revocations"] == 1
    host.state_value = original
    assert store.evaluate("action-one").reason == "audit-unhealthy"


@pytest.mark.parametrize(
    "state",
    [
        _state(mission_ids=("mission-one", "mission-two", "mission-three")),
        _state(policies=(_policy(risk="medium"),)),
        _state(policies=(_policy(max_data_class="confidential"),)),
        _state(policies=(_policy(always_explicit=True),)),
    ],
)
def test_full_semantic_state_drift_revokes_permanently(monkeypatch: pytest.MonkeyPatch, state: grants.HostState) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    original = host.state_value
    host.state_value = state
    assert store.evaluate("action-one").outcome == "would-deny"
    assert store.snapshot_counts()["revocations"] == 1
    host.state_value = original
    assert store.evaluate("action-one").outcome == "would-deny"


@pytest.mark.parametrize("control", ["kill", "mark_audit_unhealthy", "end_session", "revoke"])
def test_approval_race_terminal_control_wins(monkeypatch: pytest.MonkeyPatch, control: str) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    existing = store.request_session_grant("grant-existing") if control == "revoke" else None
    host.approve_started = threading.Event()
    host.approve_release = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(store.request_session_grant, "grant-racing")
        assert host.approve_started.wait(timeout=5)
        if control == "revoke":
            store.revoke(existing or "")
        else:
            getattr(store, control)()
        host.approve_release.set()
        with pytest.raises(grants.GrantV4Denied, match="changed"):
            future.result(timeout=5)


@pytest.mark.parametrize("control,reason", [("kill", "kill-switch"), ("mark_audit_unhealthy", "audit-unhealthy"), ("end_session", "session-ended")])
def test_terminal_controls_need_no_valid_host_callback(monkeypatch: pytest.MonkeyPatch, control: str, reason: str) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    host.clock_hook = lambda: (_ for _ in ()).throw(RuntimeError("clock broken"))
    host.state_hook = lambda: (_ for _ in ()).throw(RuntimeError("state broken"))
    getattr(store, control)()
    decision = store.evaluate("action-one")
    assert (decision.outcome, decision.reason) == ("would-deny", reason)
    assert store.snapshot_counts()["revocations"] == 1


def test_revoke_needs_no_valid_host_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, grant_id = _ready(monkeypatch)
    host.clock_hook = lambda: (_ for _ in ()).throw(RuntimeError("clock broken"))
    host.state_hook = lambda: (_ for _ in ()).throw(RuntimeError("state broken"))
    store.revoke(grant_id)
    assert store.snapshot_counts()["revocations"] == 1


def test_callbacks_are_never_invoked_while_store_lock_is_held(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())

    def prove_unlocked() -> None:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(store.snapshot_counts).result(timeout=1)["grants"] >= 0

    host.clock_hook = prove_unlocked
    host.state_hook = prove_unlocked
    host.approve_hook = prove_unlocked
    store.request_session_grant("grant-request")
    store.evaluate("action-one")


def test_clock_rollback_cannot_resurrect_expired_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch, _grant_scope(lifetime_ms=5))
    host.clock_value = 1_005
    assert store.evaluate("action-one").outcome == "would-deny"
    host.clock_value = 1_000
    assert store.evaluate("action-one").outcome == "would-deny"
    assert store.snapshot_counts()["revocations"] == 1


def test_budget_overrun_does_not_revoke_usable_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch, _grant_scope(max_cost_per_action_micro=5, max_cost_aggregate_micro=5))
    host.actions["action-one"] = _action(cost_micro=6)
    assert store.evaluate("action-one").reason == "per-action-cost"
    assert store.snapshot_counts()["revocations"] == 0
    host.actions["action-one"] = _action(cost_micro=3)
    assert store.evaluate("action-one").outcome == "would-allow"
    assert store.snapshot_counts()["revocations"] == 0
    assert store.evaluate("action-one").reason == "aggregate-cost"
    assert store.snapshot_counts()["revocations"] == 0
    host.actions["action-one"] = _action(cost_micro=2)
    assert store.evaluate("action-one").outcome == "would-allow"
    assert store.snapshot_counts()["revocations"] == 1


@pytest.mark.parametrize(
    "value",
    [
        r"C:\root\..\escape",
        r"C:\root\file.txt:stream",
        r"\\server\share\file",
        r"C:\CON\file",
        r"C:\root\alias.\file",
        r"C:\\root\file",
        "https://example.com/a/%2f/b",
        "https://example.com/a/%2E%2E/b",
        "https://example.com/a//b",
        "https://example.com:99999/a",
        "http://::1/a",
        "https://user@example.com/a",
        "https://example.com/a#fragment",
        "https://example.com./a",
        "/root//alias",
    ],
)
def test_ambiguous_targets_fail_with_contract_error(value: str) -> None:
    with pytest.raises(grants.GrantV4ContractError):
        grants._normalize_target(value)


def test_uri_ipv6_and_percent_encoded_identity_are_conservative() -> None:
    assert grants._normalize_target("HTTPS://[2001:0db8::1]:443/a") == "https://[2001:db8::1]/a"
    encoded = grants._normalize_target("https://example.com/%41")
    plain = grants._normalize_target("https://example.com/A")
    assert encoded == "https://example.com/%41"
    assert encoded != plain


def test_declared_maxima_form_a_satisfiable_contract() -> None:
    targets = tuple(
        "https://example.com/" + (chr(97 + index) * (grants.MAX_TARGET_LENGTH - 20))
        for index in range(grants.MAX_TARGETS)
    )
    assert all(len(item) == grants.MAX_TARGET_LENGTH for item in targets)
    payloads = tuple(
        _payload(
            payload_digest=hashlib.sha256(f"payload-{index}".encode()).hexdigest(),
            summary=(f"summary-{index}-" + "x" * grants.MAX_PAYLOAD_SUMMARY_LENGTH)[: grants.MAX_PAYLOAD_SUMMARY_LENGTH],
            rule_id=f"rule-{index}",
            idempotency_key=f"idem-{index}",
        )
        for index in range(grants.MAX_PAYLOADS)
    )
    scope = _grant_scope(
        targets=targets,
        payloads=payloads,
        initial_target=targets[0],
        initial_payload_digest=payloads[0].payload_digest,
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
    store = grants.SessionGrantShadowStore(host.services())
    grant = store._scope_from_resolved(scope, host.state_value, host.clock_value)
    assert len(store._human_summary(grant)) <= grants.MAX_PROMPT_LENGTH
    missions = tuple(f"mission-{index:03d}" for index in range(grants.MAX_MISSIONS))
    policies = tuple(_policy(operation=f"op-{index:03d}") for index in range(grants.MAX_POLICIES))
    assert len(_state(mission_ids=missions, policies=policies).policies) == grants.MAX_POLICIES


def test_store_cardinality_limits_are_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    issued = [store.request_session_grant(f"scope-{index:03d}") for index in range(grants.MAX_GRANTS)]
    assert store.snapshot_counts() == {
        "approvals": grants.MAX_APPROVALS,
        "grants": grants.MAX_GRANTS,
        "revocations": 0,
    }
    with pytest.raises(grants.GrantV4CapacityError):
        store.request_session_grant("scope-overflow")
    for grant_id in issued:
        store.revoke(grant_id)
    assert store.snapshot_counts()["revocations"] == grants.MAX_REVOCATIONS


def test_every_recoverable_string_routes_through_secret_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    original = grants.contains_secret

    def traced(*values: object) -> bool:
        seen.extend(str(value) for value in values if value is not None)
        return original(*values)

    monkeypatch.setattr(grants, "contains_secret", traced)
    host, store, _grant_id = _ready(monkeypatch)
    decision = store.evaluate("action-one")
    expected = {
        "owner-one", "workspace-one", TARGET_A_RAW, TARGET_A, PAYLOAD_A,
        "Reviewed report body", "exact-report", "local-only", "report-write-one",
        host.prompts[0].scope_digest, host.prompts[0].challenge_digest,
        host.prompts[0].prompt_digest, decision.action_audit_digest,
    }
    assert expected <= set(seen)


def test_concurrent_use_and_cost_are_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch, _grant_scope(max_uses=1, max_cost_per_action_micro=3, max_cost_aggregate_micro=3))
    barrier = threading.Barrier(3)

    def evaluate() -> grants.ShadowGrantDecision:
        barrier.wait(timeout=5)
        return store.evaluate("action-one")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(evaluate) for _ in range(2)]
        barrier.wait(timeout=5)
        decisions = [item.result(timeout=5) for item in futures]
    assert sum(item.outcome == "would-allow" for item in decisions) == 1
    assert sum(item.outcome == "would-deny" for item in decisions) == 1


def test_no_runtime_wiring_and_shadow_flags_are_frozen() -> None:
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py", "core/permission_broker.py"):
        candidate = root / relative
        if candidate.is_file():
            assert "session_grants_v4" not in candidate.read_text(encoding="utf-8")
    decision = grants.ShadowGrantDecision("would-deny", "no-exact-grant", None, "0" * 64, "1" * 64)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        decision.authority_granted = True  # type: ignore[misc]


def test_evidence_import_closure_includes_relative_module_and_package_initializers(tmp_path) -> None:
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("from . import helper\n", encoding="utf-8")
    (tmp_path / "pkg" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "sub" / "__init__.py").write_text("from .worker import run\n", encoding="utf-8")
    (tmp_path / "pkg" / "sub" / "worker.py").write_text("from ..helper import VALUE\ndef run(): return VALUE\n", encoding="utf-8")
    closure = evidence_verifier.local_import_closure(tmp_path, ("pkg/sub/__init__.py",))
    assert closure == (
        "pkg/__init__.py",
        "pkg/helper.py",
        "pkg/sub/__init__.py",
        "pkg/sub/worker.py",
    )
    omitted = tuple(path for path in closure if path != "pkg/helper.py")
    with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="dependency"):
        evidence_verifier._validate_dependency_binding(list(omitted), closure)


def test_evidence_junit_rejects_declared_tests_without_testcases(tmp_path) -> None:
    path = tmp_path / evidence_verifier.JUNIT
    path.parent.mkdir(parents=True)
    path.write_text(
        '<testsuites><testsuite tests="54" failures="0" errors="0" skipped="0" timestamp="2026-07-20T00:00:00-04:00"/></testsuites>',
        encoding="utf-8",
    )
    with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="no testcase"):
        evidence_verifier._junit_counts(tmp_path)


def test_evidence_junit_reconciles_testcase_failures(tmp_path) -> None:
    path = tmp_path / evidence_verifier.JUNIT
    path.parent.mkdir(parents=True)
    path.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0" timestamp="2026-07-20T00:00:00-04:00"><testcase name="false-pass"><failure/></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="testcase"):
        evidence_verifier._junit_counts(tmp_path)


def test_evidence_manifest_and_bundle_reject_noncanonical_or_cycle_fields(tmp_path) -> None:
    manifest = tmp_path / "manifest.sha256"
    manifest.write_bytes(("0" * 64 + "  b\n" + "1" * 64 + "  a\n").encode())
    with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="set/order"):
        evidence_verifier._parse_manifest(manifest, ("a", "b"))
    manifest.write_bytes(("0" * 64 + "  a\r\n").encode())
    with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="encoding"):
        evidence_verifier._parse_manifest(manifest, ("a",))
    bundle_path = tmp_path / evidence_verifier.BUNDLE
    bundle_path.parent.mkdir(parents=True)
    cycle = {key: None for key in evidence_verifier._BUNDLE_KEYS}
    cycle["self_sha256"] = "0" * 64
    bundle_path.write_text(__import__("json").dumps(cycle, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="shape"):
        evidence_verifier._read_bundle(tmp_path)


def test_evidence_history_reconstructs_and_rejects_omission_or_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evidence_verifier, "_run_history_verifiers", lambda _root: None)
    history = evidence_verifier._history(evidence_verifier.PROJECT)
    assert history["v1"]["files"] == 10  # type: ignore[index]
    assert history["v2"]["artifacts"] == 8  # type: ignore[index]
    assert history["v3"]["artifacts"] == 11  # type: ignore[index]
    for tampered in ({"v1": history["v1"], "v2": history["v2"]}, {**history, "v3": {**history["v3"], "artifacts": 10}}):  # type: ignore[misc]
        with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="historical"):
            evidence_verifier._validate_history_binding(tampered, history)


def test_evidence_material_limits_and_payload_prompt_claims_match_code(tmp_path) -> None:
    limits = evidence_verifier._constants(evidence_verifier.PROJECT)
    assert set(limits) == set(evidence_verifier._LIMIT_CONSTANTS)
    assert limits["max_prompt_length"] == grants.MAX_PROMPT_LENGTH
    assert limits["max_payloads"] == grants.MAX_PAYLOADS
    with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="limits"):
        evidence_verifier._validate_limit_binding({**limits, "max_payloads": limits["max_payloads"] + 1}, limits)
    evidence_verifier._validate_code_claims(evidence_verifier.PROJECT)
    source = (evidence_verifier.PROJECT / "core/session_grants_v4.py").read_text(encoding="utf-8")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "session_grants_v4.py").write_text(
        source.replace("what leaves device", "egress details"), encoding="utf-8"
    )
    with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="prompt claim"):
        evidence_verifier._validate_code_claims(tmp_path)
    (tmp_path / "core" / "session_grants_v4.py").write_text(
        source.replace("    payload_digest: str\n", ""), encoding="utf-8"
    )
    with pytest.raises(evidence_verifier.Phase5GrantR4EvidenceError, match="payload"):
        evidence_verifier._validate_code_claims(tmp_path)
