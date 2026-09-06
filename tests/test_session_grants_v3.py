from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import core.session_grants_v3 as grants
from scripts import verify_phase5_grants_r3 as evidence_verifier


SHA_A = hashlib.sha256(b"a").hexdigest()
SHA_B = hashlib.sha256(b"b").hexdigest()
SHA_C = hashlib.sha256(b"c").hexdigest()
SHA_D = hashlib.sha256(b"d").hexdigest()
TARGET_A_RAW = "HTTPS://EXAMPLE.com:443/a/../resource-a"
TARGET_A = "https://example.com/resource-a"
TARGET_B_RAW = r"C:\Work\Beta.txt"
TARGET_B = "c:/Work/Beta.txt"


class HostFixture:
    def __init__(self) -> None:
        self.clock_value = 1_000
        self.state_value = _state()
        self.grant_value: grants.ResolvedGrantScope | None = _grant_scope()
        self.action_values: dict[str, grants.ResolvedAction] = {
            "action-one": _action(target=TARGET_A_RAW),
            "action-two": _action(target=TARGET_B_RAW),
        }
        self.approve_result = True
        self.attestation_sequence_override: int | None = None
        self.approve_count = 0
        self.grant_resolve_count = 0
        self.action_resolve_count = 0
        self.prompts: list[grants.ApprovalPrompt] = []
        self.approval_hook = None
        self.grant_factory = None
        self.action_started: threading.Event | None = None
        self.action_release: threading.Event | None = None
        self._lock = threading.Lock()

    def clock(self) -> int:
        with self._lock:
            return self.clock_value

    def state(self) -> grants.HostState:
        with self._lock:
            return self.state_value

    def resolve_grant(self, reference: str) -> grants.ResolvedGrantScope:
        with self._lock:
            self.grant_resolve_count += 1
            factory = self.grant_factory
            value = self.grant_value
        if factory is not None:
            return factory(reference)
        if value is None:
            raise grants.GrantV3ContractError("no fixture grant")
        return value

    def resolve_action(self, reference: str) -> grants.ResolvedAction:
        with self._lock:
            self.action_resolve_count += 1
            value = self.action_values.get(reference)
            started = self.action_started
            release = self.action_release
        if value is None:
            raise grants.GrantV3ContractError("unknown fixture action")
        if started is not None and release is not None:
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test action barrier timed out")
        return value

    def approve(self, prompt: grants.ApprovalPrompt) -> grants.HostApprovalResponse:
        with self._lock:
            self.approve_count += 1
            count = self.approve_count
            self.prompts.append(prompt)
            hook = self.approval_hook
            approved = self.approve_result
        if hook is not None:
            hook()
        sequence = self.attestation_sequence_override or count
        return grants.HostApprovalResponse(approved, f"attestation-{count:04d}", sequence)

    def services(self) -> grants.HostServices:
        return grants.HostServices(
            trust_root_id="desktop-root",
            resolve_grant=self.resolve_grant,
            resolve_action=self.resolve_action,
            approve=self.approve,
            state=self.state,
            monotonic_ms=self.clock,
        )


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
        "audit_head": SHA_D,
        "audit_healthy": True,
        "session_active": True,
        "kill_switch": False,
    }
    values.update(overrides)
    return grants.HostState(**values)  # type: ignore[arg-type]


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
        "initial_target": TARGET_A_RAW,
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
        "cost_micro": 3,
    }
    values.update(overrides)
    return grants.ResolvedAction(**values)  # type: ignore[arg-type]


def _ready(monkeypatch: pytest.MonkeyPatch, scope: grants.ResolvedGrantScope | None = None):
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    if scope is not None:
        host.grant_value = scope
    store = grants.SessionGrantShadowStore(host.services())
    grant_id = store.request_session_grant("grant-request")
    return host, store, grant_id


def test_default_off_calls_no_host_service_and_changes_no_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(grants.GRANT_EVALUATOR_FLAG, raising=False)
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    disabled = store.evaluate("action-one")
    assert (disabled.outcome, disabled.reason) == ("disabled", "feature-flag-off")
    assert disabled.callback_required and not disabled.authority_granted
    assert host.action_resolve_count == host.grant_resolve_count == host.approve_count == 0
    assert store.snapshot_counts() == {"approvals": 0, "grants": 0, "revocations": 0}
    with pytest.raises(grants.GrantV3Disabled):
        store.request_session_grant("grant-request")
    assert host.grant_resolve_count == host.approve_count == 0


def test_only_opaque_reference_is_accepted_and_callbacks_are_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "1")
    host = HostFixture()
    services = host.services()
    store = grants.SessionGrantShadowStore(services)
    assert tuple(inspect.signature(store.request_session_grant).parameters) == ("invocation_ref",)
    assert tuple(inspect.signature(store.evaluate).parameters) == ("invocation_ref",)
    assert store._services is services
    with pytest.raises(TypeError):
        store.request_session_grant("grant-request", SHA_A)  # type: ignore[call-arg]
    assert not any(
        marker in name
        for name in dir(grants)
        for marker in ("factory", "preview", "register")
    )


def test_approval_receives_complete_human_finite_scope_and_is_attested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, store, grant_id = _ready(monkeypatch)
    assert grant_id == "grant-00000001"
    assert host.approve_count == 1
    prompt = host.prompts[0]
    scope = prompt.scope
    assert scope.targets == (TARGET_B, TARGET_A)
    assert scope.principal_id == "owner-one"
    assert scope.session_id == "session-one"
    assert scope.workspace_id == "workspace-one"
    assert scope.mission_id == "mission-one"
    assert scope.account == "account-one"
    assert scope.path == "c:/Work/root"
    assert scope.effect in prompt.human_summary
    assert scope.environment in prompt.human_summary
    assert all(target in prompt.human_summary for target in scope.targets)
    assert prompt.scope_digest == grants.canonical_scope_digest(scope)
    assert store.snapshot_counts() == {"approvals": 1, "grants": 1, "revocations": 0}


def test_host_denial_or_state_drift_during_approval_issues_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    host.approve_result = False
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV3Denied, match="denied"):
        store.request_session_grant("grant-request")
    assert store.snapshot_counts()["grants"] == 0

    host = HostFixture()
    host.approval_hook = lambda: setattr(
        host,
        "state_value",
        dataclasses.replace(host.state_value, policy_version="onyx-approval-v4"),
    )
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV3Denied, match="changed"):
        store.request_session_grant("grant-request")
    assert store.snapshot_counts()["grants"] == 0


def test_approval_attestation_sequence_cannot_be_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    assert store.request_session_grant("grant-request-one") == "grant-00000001"
    host.attestation_sequence_override = 1
    with pytest.raises(grants.GrantV3Denied, match="sequence was already consumed"):
        store.request_session_grant("grant-request-two")
    assert store.snapshot_counts() == {"approvals": 1, "grants": 1, "revocations": 0}


def test_multi_target_repeated_actions_share_scope_but_get_unique_audit_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, store, grant_id = _ready(monkeypatch)
    first = store.evaluate("action-one")
    host.clock_value += 1
    second = store.evaluate("action-two")
    host.clock_value += 1
    third = store.evaluate("action-one")
    assert [first.outcome, second.outcome, third.outcome] == [
        "would-allow",
        "would-allow",
        "would-allow",
    ]
    assert {first.grant_id, second.grant_id, third.grant_id} == {grant_id}
    assert len({first.scope_digest, second.scope_digest, third.scope_digest}) == 1
    assert len(
        {first.action_audit_digest, second.action_audit_digest, third.action_audit_digest}
    ) == 3
    assert all(item.callback_required and not item.authority_granted for item in (first, second, third))


@pytest.mark.parametrize(
    "action",
    [
        _action(target="target-three"),
        _action(account="account-two"),
        _action(path=r"C:\Other\root"),
        _action(effect="Write a different report"),
        _action(environment="prod-env"),
        _action(operation="delete"),
        _action(mission_id="mission-two"),
        _action(data_class="public"),
    ],
)
def test_out_of_scope_substitution_denies(
    monkeypatch: pytest.MonkeyPatch, action: grants.ResolvedAction
) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    host.action_values["action-out"] = action
    decision = store.evaluate("action-out")
    assert decision.outcome == "would-deny"
    assert decision.authority_granted is False


def test_cost_and_use_are_atomic_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _grant_scope(
        max_cost_per_action_micro=3,
        max_cost_aggregate_micro=6,
        max_uses=3,
    )
    host, store, _grant_id = _ready(monkeypatch, scope)
    first = store.evaluate("action-one")
    second = store.evaluate("action-two")
    third = store.evaluate("action-one")
    assert first.outcome == second.outcome == "would-allow"
    assert third.outcome == "would-deny"
    assert store.snapshot_counts()["revocations"] == 1


def test_clock_high_water_and_expiry_cannot_roll_back_or_resurrect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, store, _grant_id = _ready(monkeypatch, _grant_scope(lifetime_ms=100))
    host.clock_value = 1_050
    before = store.evaluate("action-one")
    host.clock_value = 1_001
    rolled_back = store.evaluate("action-two")
    assert before.outcome == rolled_back.outcome == "would-allow"
    assert before.action_audit_digest != rolled_back.action_audit_digest
    host.clock_value = 1_100
    assert store.evaluate("action-one").outcome == "would-deny"
    host.clock_value = 1_000
    assert store.evaluate("action-one").reason == "no-exact-grant"


@pytest.mark.parametrize(
    ("change", "rollback"),
    [
        ({"schema_version": 4}, {"schema_version": grants.GRANT_SCHEMA_VERSION}),
        ({"policy_version": "onyx-approval-v4"}, {"policy_version": grants.GRANT_POLICY_VERSION}),
        ({"audit_head": SHA_C}, {"audit_head": SHA_D}),
    ],
)
def test_schema_policy_and_audit_drift_revoke_permanently(
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, object],
    rollback: dict[str, object],
) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    host.state_value = dataclasses.replace(host.state_value, **change)
    assert store.evaluate("action-one").outcome == "would-deny"
    host.state_value = dataclasses.replace(host.state_value, **rollback)
    assert store.evaluate("action-one").reason == "no-exact-grant"


def test_always_explicit_high_critical_and_unknown_policy_deny_before_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    for policy in (
        _policy(always_explicit=True),
        _policy(risk="high"),
        _policy(risk="critical"),
    ):
        host = HostFixture()
        host.state_value = _state(policies=(policy,))
        store = grants.SessionGrantShadowStore(host.services())
        with pytest.raises(grants.GrantV3Denied):
            store.request_session_grant("grant-request")
        assert host.approve_count == 0
    host = HostFixture()
    host.grant_value = _grant_scope(operation="delete")
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV3ContractError, match="policy"):
        store.request_session_grant("grant-request")
    assert host.approve_count == 0


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _grant_scope(initial_cost_micro=6),
        lambda: _grant_scope(max_cost_per_action_micro=6, max_cost_aggregate_micro=5),
        lambda: _grant_scope(not_before_delay_ms=100, lifetime_ms=100),
        lambda: _grant_scope(lifetime_ms=grants.MAX_SESSION_LIFETIME_MS + 1),
        lambda: _grant_scope(targets=(TARGET_A_RAW, TARGET_A)),
        lambda: _grant_scope(initial_target="target-three"),
        lambda: _grant_scope(max_uses=0),
    ],
)
def test_impossible_scope_fails_before_approval(
    monkeypatch: pytest.MonkeyPatch, factory
) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    host.grant_factory = lambda _ref: factory()
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV3ContractError):
        store.request_session_grant("grant-request")
    assert host.approve_count == 0


def test_tampered_resolver_object_is_revalidated_before_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    tampered = _grant_scope()
    object.__setattr__(tampered, "max_uses", 0)
    host.grant_value = tampered
    store = grants.SessionGrantShadowStore(host.services())
    with pytest.raises(grants.GrantV3ContractError):
        store.request_session_grant("grant-request")
    assert host.approve_count == 0


def test_strict_ids_workspace_secret_and_target_normalization() -> None:
    assert grants._normalize_target(TARGET_A_RAW) == TARGET_A
    assert grants._normalize_target(TARGET_B_RAW) == TARGET_B
    assert grants._normalize_target("/tmp/a/../b") == "/tmp/b"
    for invalid in (
        "../relative",
        "abcdef0123456789abcdef0123456789",
        "long-token-like-identifier-value-0001",
        "A" * 40,
        "sk-proj-abcdefghijklmnop",
    ):
        with pytest.raises(grants.GrantV3ContractError):
            grants._safe_id(invalid, "identifier")
    for workspace in (
        "ab",
        "Workspace-One",
        "../workspace",
        "workspace-token-like-identifier-0001",
        "a" * 40,
    ):
        with pytest.raises(grants.GrantV3ContractError):
            grants._workspace_id(workspace)
    with pytest.raises(grants.GrantV3ContractError):
        grants._normalize_target("https://example.com/?token=sk-proj-abcdefghijklmnop")


def test_every_recoverable_string_uses_project_secret_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    original = grants.contains_secret

    def traced(*values: object) -> bool:
        seen.extend(str(value) for value in values if value is not None)
        return original(*values)

    monkeypatch.setattr(grants, "contains_secret", traced)
    host, store, _grant_id = _ready(monkeypatch)
    decision = store.evaluate("action-one")
    expected = {
        "owner-one",
        "session-one",
        "workspace-one",
        "mission-one",
        "local-files",
        "file-controller",
        "write",
        TARGET_A_RAW,
        TARGET_A,
        TARGET_B_RAW,
        TARGET_B,
        "account-one",
        "Write the reviewed report",
        "test-env",
        host.prompts[0].scope_digest,
        decision.action_audit_digest,
    }
    assert expected <= set(seen)


def test_collection_bounds_and_deterministic_terminal_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(grants.GrantV3ContractError, match="mission collection"):
        _state(mission_ids=tuple(f"mission-{index:03d}" for index in range(grants.MAX_MISSIONS + 1)))
    with pytest.raises(grants.GrantV3ContractError, match="policy collection"):
        _state(
            policies=tuple(
                _policy(operation=f"write-{index:03d}")
                for index in range(grants.MAX_POLICIES + 1)
            )
        )
    with pytest.raises(grants.GrantV3ContractError, match="target collection"):
        _grant_scope(targets=tuple(f"target-{index:03d}" for index in range(grants.MAX_TARGETS + 1)))

    monkeypatch.setenv(grants.GRANT_EVALUATOR_FLAG, "true")
    host = HostFixture()
    store = grants.SessionGrantShadowStore(host.services())
    issued = [store.request_session_grant(f"grant-ref-{index:03d}") for index in range(grants.MAX_GRANTS)]
    assert store.snapshot_counts() == {
        "approvals": grants.MAX_APPROVALS,
        "grants": grants.MAX_GRANTS,
        "revocations": 0,
    }
    with pytest.raises(grants.GrantV3CapacityError):
        store.request_session_grant("grant-overflow")
    store.revoke(issued[0])
    replacement = store.request_session_grant("grant-replacement")
    assert replacement != issued[0]
    counts = store.snapshot_counts()
    assert counts["grants"] == grants.MAX_GRANTS
    assert counts["approvals"] == grants.MAX_APPROVALS
    assert counts["revocations"] == 0


def test_concurrent_use_and_cost_allow_only_one_at_exact_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, store, _grant_id = _ready(
        monkeypatch,
        _grant_scope(max_uses=1, max_cost_per_action_micro=3, max_cost_aggregate_micro=3),
    )
    barrier = threading.Barrier(3)

    def evaluate() -> grants.ShadowGrantDecision:
        barrier.wait(timeout=5)
        return store.evaluate("action-one")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(evaluate) for _ in range(2)]
        barrier.wait(timeout=5)
        decisions = [future.result(timeout=5) for future in futures]
    assert sum(item.outcome == "would-allow" for item in decisions) == 1
    assert sum(item.outcome == "would-deny" for item in decisions) == 1
    assert store.snapshot_counts()["revocations"] == 1
    assert host.action_resolve_count == 2


@pytest.mark.parametrize("safety", ["revoke", "kill", "audit", "session"])
def test_concurrent_safety_barrier_wins_before_evaluation_consumption(
    monkeypatch: pytest.MonkeyPatch, safety: str
) -> None:
    host, store, grant_id = _ready(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    host.action_started = started
    host.action_release = release
    result: list[grants.ShadowGrantDecision] = []

    thread = threading.Thread(target=lambda: result.append(store.evaluate("action-one")))
    thread.start()
    assert started.wait(timeout=5)
    if safety == "revoke":
        store.revoke(grant_id)
    elif safety == "kill":
        store.kill()
    elif safety == "audit":
        store.mark_audit_unhealthy()
    else:
        store.end_session()
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(result) == 1 and result[0].outcome == "would-deny"
    assert result[0].authority_granted is False


def test_public_decision_safety_fields_are_not_constructor_inputs() -> None:
    decision = grants.ShadowGrantDecision(
        "would-allow", "exact-session-grant", "grant-00000001", SHA_A, SHA_B
    )
    assert decision.callback_required is True and decision.authority_granted is False
    with pytest.raises(TypeError):
        grants.ShadowGrantDecision(  # type: ignore[call-arg]
            "would-allow",
            "exact-session-grant",
            "grant-00000001",
            SHA_A,
            SHA_B,
            callback_required=False,
            authority_granted=True,
        )
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.authority_granted = True  # type: ignore[misc]


def test_restart_restores_no_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    host, store, _grant_id = _ready(monkeypatch)
    assert store.evaluate("action-one").outcome == "would-allow"
    restarted = grants.SessionGrantShadowStore(host.services())
    assert restarted.evaluate("action-one").reason == "no-exact-grant"
    assert not hasattr(restarted, "save")
    assert not hasattr(restarted, "load")
    assert not hasattr(restarted, "restore")


def test_no_startup_ui_provider_owner_wiring_and_v1_v2_remain_present() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "session_grants_v3" not in source
        assert "ONYX_GRANT_EVALUATOR" not in source
    for relative in (
        "core/session_grants_v1.py",
        "core/session_grants_v2.py",
        "tests/test_session_grants_v1.py",
        "tests/test_session_grants_v2.py",
    ):
        assert (root / relative).is_file()


def test_scope_payload_is_canonical_sorted_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, _store, _grant_id = _ready(monkeypatch)
    scope = host.prompts[0].scope
    payload = grants._scope_payload(scope)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert json.loads(serialized)["targets"] == sorted(json.loads(serialized)["targets"])
    assert not grants.contains_secret(serialized)


def _write_text(root: Path, relative: str, value: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _write_manifest(root: Path, relative: str, paths: tuple[str, ...]) -> None:
    lines = [
        f"{hashlib.sha256((root / path).read_bytes()).hexdigest()}  {path}\n"
        for path in paths
    ]
    _write_text(root, relative, "".join(lines))


def _fixture_limits() -> dict[str, int]:
    return {
        "max_approvals": grants.MAX_APPROVALS,
        "max_cost_micro": grants.MAX_COST_MICRO,
        "max_grants": grants.MAX_GRANTS,
        "max_missions": grants.MAX_MISSIONS,
        "max_policies": grants.MAX_POLICIES,
        "max_revocations": grants.MAX_REVOCATIONS,
        "max_session_lifetime_ms": grants.MAX_SESSION_LIFETIME_MS,
        "max_targets": grants.MAX_TARGETS,
        "max_uses": grants.MAX_USES,
    }


def _fixture_code() -> str:
    lines = ["from memory.store import contains_secret\n"]
    for bundle_key, constant in evidence_verifier._LIMIT_CONSTANTS.items():
        lines.append(f"{constant} = {_fixture_limits()[bundle_key]}\n")
    return "".join(lines)


def _refresh_bundle_and_manifests(root: Path, bundle: dict[str, object]) -> None:
    leaf_paths = tuple(
        path for path in evidence_verifier.ARTIFACT_PATHS if path != evidence_verifier.BUNDLE
    )
    bundle["files"] = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in leaf_paths
    }
    _write_text(
        root,
        evidence_verifier.BUNDLE,
        json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
    )
    _write_manifest(
        root, evidence_verifier.ARTIFACT_MANIFEST, evidence_verifier.ARTIFACT_PATHS
    )
    _write_manifest(root, evidence_verifier.TOP_MANIFEST, evidence_verifier.TOP_PATHS)


def _evidence_tree(root: Path) -> tuple[dict[str, object], str, dict[str, str]]:
    timestamp = "2026-07-20T01:00:00-04:00"
    base = "1" * 40
    environment = evidence_verifier._environment()
    _write_text(root, "core/__init__.py", "# core\n")
    _write_text(root, "core/session_grants_v3.py", _fixture_code())
    _write_text(root, "memory/__init__.py", "# memory\n")
    _write_text(root, "memory/store.py", "def contains_secret(*values): return False\n")
    _write_text(root, "scripts/verify_phase5_grants_r3.py", "# verifier seed\n")
    _write_text(
        root,
        "tests/test_session_grants_v3.py",
        "import core.session_grants_v3\nfrom scripts import verify_phase5_grants_r3\n",
    )
    _write_text(
        root,
        "docs/onyx/checkpoints/phase5-grants-r3/PHASE5_1_GRANTS_SHADOW_R3_CHECKPOINT.md",
        "# checkpoint\n",
    )
    _write_text(
        root,
        evidence_verifier.JUNIT,
        '<?xml version="1.0"?><testsuites><testsuite errors="0" failures="0" skipped="0" tests="39" timestamp="'
        + timestamp
        + '"></testsuite></testsuites>\n',
    )
    _write_text(
        root,
        evidence_verifier.RAW_LOG,
        f"timestamp={timestamp}\npassed=39\nfailed=0\nerrors=0\nskipped=0\nresult=39 passed\nexit_code=0\n",
    )
    _write_text(
        root,
        evidence_verifier.STATIC_LOG,
        "ruff_exit_code=0\npy_compile_exit_code=0\ndiff_check_exit_code=0\nv1_historical_files=10\nv2_evidence_root=1\nv2_evidence_artifacts=8\n",
    )
    bundle: dict[str, object] = {
        "base_commit": base,
        "contract": "Phase5SessionGrantShadowEvidence.v3",
        "counts": {"errors": 0, "failed": 0, "passed": 39, "skipped": 0},
        "dag": {
            "artifact_points_to": list(evidence_verifier.ARTIFACT_PATHS),
            "bundle_excludes_manifest_and_self_hashes": True,
            "root": evidence_verifier.TOP_MANIFEST,
            "root_points_to": [evidence_verifier.ARTIFACT_MANIFEST],
        },
        "dependency_closure": list(evidence_verifier.DECLARED_LOCAL_CLOSURE),
        "environment": environment,
        "feature_flag": {"default": False, "name": grants.GRANT_EVALUATOR_FLAG},
        "files": {},
        "limits": _fixture_limits(),
        "root_anchor": {"externally_anchored": False, "required_before_acceptance": True},
        "status": "candidate-default-off-not-accepted",
        "timestamp": timestamp,
    }
    _refresh_bundle_and_manifests(root, bundle)
    return bundle, base, environment


def test_r3_evidence_semantic_exact_dag_and_dependency_closure_pass(tmp_path: Path) -> None:
    _bundle, base, environment = _evidence_tree(tmp_path)
    result = evidence_verifier.verify_evidence(
        tmp_path, current_base_commit=base, current_environment=environment
    )
    assert result == {
        "artifact_files": 11,
        "artifact_manifest_sha256": hashlib.sha256(
            (tmp_path / evidence_verifier.ARTIFACT_MANIFEST).read_bytes()
        ).hexdigest(),
        "dependencies": 6,
        "root_files": 1,
        "root_manifest_sha256": hashlib.sha256(
            (tmp_path / evidence_verifier.TOP_MANIFEST).read_bytes()
        ).hexdigest(),
        "tests": 39,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("counts", {"errors": 0, "failed": 0, "passed": 40, "skipped": 0}),
        ("limits", {**_fixture_limits(), "max_uses": grants.MAX_USES + 1}),
        ("base_commit", "2" * 40),
        (
            "dependency_closure",
            [item for item in evidence_verifier.DECLARED_LOCAL_CLOSURE if item != "memory/store.py"],
        ),
        ("environment", {**evidence_verifier._environment(), "python": "0.0.0"}),
        ("timestamp", "2026-07-20T01:00:00"),
        ("root_anchor", {"externally_anchored": True, "required_before_acceptance": False}),
    ],
)
def test_r3_evidence_false_count_limit_base_dependency_environment_time_anchor_reject(
    tmp_path: Path, field: str, value: object
) -> None:
    bundle, base, environment = _evidence_tree(tmp_path)
    bundle[field] = value
    _refresh_bundle_and_manifests(tmp_path, bundle)
    with pytest.raises(evidence_verifier.Phase5GrantR3EvidenceError):
        evidence_verifier.verify_evidence(
            tmp_path, current_base_commit=base, current_environment=environment
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "order", "crlf", "self-hash"])
def test_r3_evidence_manifest_exact_set_order_canonical_and_self_hash_reject(
    tmp_path: Path, mutation: str
) -> None:
    _bundle, base, environment = _evidence_tree(tmp_path)
    manifest = tmp_path / evidence_verifier.ARTIFACT_MANIFEST
    lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
    if mutation == "missing":
        manifest.write_text("".join(lines[:-1]), encoding="utf-8", newline="\n")
    elif mutation == "extra":
        manifest.write_text(
            "".join(lines) + f"{'0' * 64}  unexpected.txt\n",
            encoding="utf-8",
            newline="\n",
        )
    elif mutation == "order":
        manifest.write_text("".join(reversed(lines)), encoding="utf-8", newline="\n")
    elif mutation == "crlf":
        manifest.write_bytes(manifest.read_bytes().replace(b"\n", b"\r\n"))
    else:
        manifest.write_text(
            "".join(lines)
            + f"{'0' * 64}  {evidence_verifier.ARTIFACT_MANIFEST}\n",
            encoding="utf-8",
            newline="\n",
        )
    _write_manifest(tmp_path, evidence_verifier.TOP_MANIFEST, evidence_verifier.TOP_PATHS)
    with pytest.raises(evidence_verifier.Phase5GrantR3EvidenceError):
        evidence_verifier.verify_evidence(
            tmp_path, current_base_commit=base, current_environment=environment
        )


def test_r3_evidence_bundle_cycle_noncanonical_raw_static_and_leaf_tamper_reject(
    tmp_path: Path,
) -> None:
    for mutation in ("cycle", "pretty", "raw", "static", "leaf"):
        case = tmp_path / mutation
        bundle, base, environment = _evidence_tree(case)
        if mutation == "cycle":
            bundle["self_sha256"] = SHA_A
            _refresh_bundle_and_manifests(case, bundle)
        elif mutation == "pretty":
            _write_text(case, evidence_verifier.BUNDLE, json.dumps(bundle, indent=2) + "\n")
            _write_manifest(
                case, evidence_verifier.ARTIFACT_MANIFEST, evidence_verifier.ARTIFACT_PATHS
            )
            _write_manifest(case, evidence_verifier.TOP_MANIFEST, evidence_verifier.TOP_PATHS)
        elif mutation == "raw":
            raw = case / evidence_verifier.RAW_LOG
            raw.write_text(
                raw.read_text(encoding="utf-8").replace("passed=39", "passed=40"),
                encoding="utf-8",
                newline="\n",
            )
            _refresh_bundle_and_manifests(case, bundle)
        elif mutation == "static":
            static = case / evidence_verifier.STATIC_LOG
            static.write_text(
                static.read_text(encoding="utf-8").replace(
                    "ruff_exit_code=0", "ruff_exit_code=1"
                ),
                encoding="utf-8",
                newline="\n",
            )
            _refresh_bundle_and_manifests(case, bundle)
        else:
            (case / "memory/store.py").write_text("tampered\n", encoding="utf-8")
        with pytest.raises(evidence_verifier.Phase5GrantR3EvidenceError):
            evidence_verifier.verify_evidence(
                case, current_base_commit=base, current_environment=environment
            )
