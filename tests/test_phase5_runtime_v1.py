from __future__ import annotations

import dataclasses
import statistics
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest

import core.phase5_runtime_v1 as runtime


def _binding(**changes: object) -> runtime.RuntimeBindingV1:
    values: dict[str, object] = {
        "trace_id": "trace-one",
        "session_id": "session-one",
        "workspace_id": "workspace-one",
        "account_id": "account-one",
        "profile_id": "profile-one",
    }
    values.update(changes)
    return runtime.RuntimeBindingV1(**values)  # type: ignore[arg-type]


def _flags(**changes: bool) -> runtime.RuntimeFlagsV1:
    values = {
        "runtime": True,
        "grant_shadow": False,
        "approval_inbox": False,
        "low_risk": True,
        "nexus_projection": False,
        "local_catalog_read": True,
        "dashboard_projection": False,
    }
    values.update(changes)
    return runtime.RuntimeFlagsV1(**values)


def _action(binding: runtime.RuntimeBindingV1 | None = None, **changes: object) -> runtime.ActionRequestV1:
    values: dict[str, object] = {
        "invocation_ref": "invocation-one",
        "binding": binding or _binding(),
        "capability": "local.catalog",
        "operation": "catalog_read",
        "provider_free": True,
        "read_only": True,
        "effect": "none",
        "egress": "none",
        "metadata_allowlisted": True,
        "cost_micro": 0,
        "risk": "low",
        "reversible": True,
    }
    values.update(changes)
    return runtime.ActionRequestV1(**values)  # type: ignore[arg-type]


def _core(
    *,
    flags: runtime.RuntimeFlagsV1 | None = None,
    components: runtime.RuntimeComponentsV1 | None = None,
    binding: runtime.RuntimeBindingV1 | None = None,
) -> runtime.Phase5RuntimeV1:
    return runtime.Phase5RuntimeV1(
        binding=binding or _binding(),
        flags=flags or _flags(),
        components=components,
    )


def test_all_flags_are_separate_and_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    names = (
        runtime.PHASE5_RUNTIME_FLAG,
        runtime.PHASE5_GRANT_SHADOW_FLAG,
        runtime.PHASE5_APPROVAL_INBOX_FLAG,
        runtime.PHASE5_LOW_RISK_FLAG,
        runtime.PHASE5_NEXUS_PROJECTION_FLAG,
        runtime.PHASE5_LOCAL_CATALOG_READ_FLAG,
        runtime.PHASE5_DASHBOARD_PROJECTION_FLAG,
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    assert runtime.RuntimeFlagsV1.from_environ() == runtime.RuntimeFlagsV1()
    for name in names:
        values = {item: "false" for item in names}
        values[name] = "true"
        enabled = dict(runtime.RuntimeFlagsV1.from_environ(values).payload())
        assert sum(enabled.values()) == 1


def test_extension_off_returns_exact_legacy_value_and_never_calls_components() -> None:
    touched: list[str] = []
    components = runtime.RuntimeComponentsV1(
        grant_evaluator=lambda reference: touched.append(reference),
        nexus_projector=lambda binding: (_ for _ in ()).throw(AssertionError(binding)),
    )
    core = _core(flags=_flags(runtime=False, grant_shadow=True), components=components)
    disabled = core
    marker = object()
    calls = 0

    def legacy() -> object:
        nonlocal calls
        calls += 1
        return marker

    assert core.legacy_or_decision(_action(), legacy) is marker
    assert calls == 1
    assert touched == []

    core = _core(flags=_flags(low_risk=False, local_catalog_read=True), components=components)
    assert core.legacy_or_decision(_action(), legacy) is marker
    assert calls == 2
    assert touched == []
    assert disabled.evaluate(object()).disposition is runtime.RuntimeDispositionV1.FALLBACK  # type: ignore[arg-type]


def test_exact_low_risk_catalog_read_is_the_only_allow() -> None:
    core = _core()
    decision = core.evaluate(_action())
    assert decision.disposition is runtime.RuntimeDispositionV1.ALLOW_LOCAL_CATALOG_READ
    assert decision.reason == "exact_provider_free_catalog_read"
    assert core.decision_is_current(decision)


@pytest.mark.parametrize(
    ("change", "value"),
    (
        ("capability", "local.files"),
        ("operation", "catalog_list"),
        ("provider_free", False),
        ("read_only", False),
        ("effect", "write"),
        ("egress", "local-only"),
        ("metadata_allowlisted", False),
        ("cost_micro", 1),
        ("risk", "medium"),
        ("reversible", False),
        ("uses_credentials", True),
        ("privileged", True),
        ("irreversible", True),
    ),
)
def test_near_miss_catalog_reads_are_explicit(change: str, value: object) -> None:
    decision = _core().evaluate(_action(**{change: value}))
    assert decision.disposition is runtime.RuntimeDispositionV1.EXPLICIT


@pytest.mark.parametrize(
    "action_class",
    (
        "money", "send", "publish", "ads", "deploy", "delete", "credentials", "oauth",
        "roles", "install", "privileged", "legal", "political", "crisis", "irreversible",
    ),
)
def test_high_consequence_classes_are_always_explicit(action_class: str) -> None:
    decision = _core().evaluate(_action(action_classes=(action_class,)))
    assert decision.disposition is runtime.RuntimeDispositionV1.EXPLICIT
    assert decision.reason == "explicit_action_class"


def test_high_consequence_class_remains_explicit_when_low_risk_extension_is_off() -> None:
    core = _core(flags=_flags(low_risk=False, local_catalog_read=False))
    decision = core.evaluate(_action(action_classes=("money",)))
    assert decision.disposition is runtime.RuntimeDispositionV1.EXPLICIT


@pytest.mark.parametrize("operation", ("send_message", "publish", "oauth_grant", "delete", "deploy_app"))
def test_high_consequence_operation_words_are_explicit(operation: str) -> None:
    decision = _core().evaluate(_action(operation=operation))
    assert decision.disposition is runtime.RuntimeDispositionV1.EXPLICIT
    assert decision.reason == "explicit_action_class"


def test_exact_scope_binding_mismatch_is_explicit() -> None:
    core = _core()
    for field in ("trace_id", "session_id", "workspace_id", "account_id", "profile_id"):
        foreign = dataclasses.replace(_binding(), **{field: f"foreign-{field}"})
        decision = core.evaluate(_action(foreign))
        assert decision.disposition is runtime.RuntimeDispositionV1.EXPLICIT
        assert decision.reason == "scope_mismatch"


def test_injected_grant_observer_is_advisory_and_bounded() -> None:
    seen: list[str] = []

    def observe(reference: str) -> dict[str, object]:
        seen.append(reference)
        return {"outcome": "disabled", "reason": "feature-flag-off"}

    core = _core(
        flags=_flags(grant_shadow=True),
        components=runtime.RuntimeComponentsV1(grant_evaluator=observe),
    )
    decision = core.evaluate(_action())
    assert decision.disposition is runtime.RuntimeDispositionV1.ALLOW_LOCAL_CATALOG_READ
    assert seen == ["invocation-one"]
    assert decision.advisory_json == '{"outcome":"disabled","reason":"feature-flag-off"}'


def test_enabled_missing_or_failing_grant_observer_fails_closed() -> None:
    missing = _core(flags=_flags(grant_shadow=True)).evaluate(_action())
    assert missing.disposition is runtime.RuntimeDispositionV1.EXPLICIT
    assert missing.reason == "grant_shadow_unavailable"

    def fail(_reference: str) -> object:
        raise RuntimeError("host failure")

    core = _core(
        flags=_flags(grant_shadow=True),
        components=runtime.RuntimeComponentsV1(grant_evaluator=fail),
    )
    failed = core.evaluate(_action())
    assert failed.disposition is runtime.RuntimeDispositionV1.EXPLICIT
    assert core.status().state is runtime.RuntimeStateV1.DEGRADED


def test_kill_during_injected_evaluation_revokes_epoch_and_fails_closed() -> None:
    entered = threading.Event()
    release = threading.Event()

    def observe(_reference: str) -> dict[str, str]:
        entered.set()
        assert release.wait(3)
        return {"outcome": "would-allow"}

    core = _core(
        flags=_flags(grant_shadow=True),
        components=runtime.RuntimeComponentsV1(grant_evaluator=observe),
    )
    decisions: list[runtime.RuntimeDecisionV1] = []
    worker = threading.Thread(target=lambda: decisions.append(core.evaluate(_action())))
    worker.start()
    assert entered.wait(2)
    status = core.kill()
    release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert status.state is runtime.RuntimeStateV1.TERMINATED
    assert decisions[0].disposition is runtime.RuntimeDispositionV1.EXPLICIT
    assert decisions[0].reason == "authority_revoked_during_evaluation"


def test_terminal_boundary_is_idempotent_calls_every_injected_revoker_once_and_clears() -> None:
    calls: list[tuple[str, str]] = []

    def callback(name: str) -> Callable[[str], None]:
        return lambda reason: calls.append((name, reason))

    components = runtime.RuntimeComponentsV1(
        nexus_projector=lambda _binding: runtime.ProjectionBatchV1(
            ({"capability_id": "local.catalog", "status": "available"},)
        ),
        grant_terminator=callback("grant"),
        nexus_terminator=callback("nexus"),
        inbox_terminator=callback("inbox"),
        rollback_callback=callback("rollback"),
    )
    core = _core(flags=_flags(nexus_projection=True), components=components)
    assert core.refresh_capabilities().total == 1
    first = core.reconnect()
    second = core.kill()
    assert first == second
    assert first.capability_count == 0 and first.inbox_count == 0
    assert calls == [
        ("grant", "reconnect"), ("nexus", "reconnect"),
        ("inbox", "reconnect"), ("rollback", "reconnect"),
    ]
    assert core.evaluate(_action()).disposition is runtime.RuntimeDispositionV1.EXPLICIT


@pytest.mark.parametrize(
    ("method", "reason"),
    (
        ("kill", "kill"), ("revoke", "revoke"), ("rollback", "rollback"),
        ("end_session", "end_session"), ("reconnect", "reconnect"), ("shutdown", "shutdown"),
    ),
)
def test_all_lifecycle_events_use_the_single_terminal_boundary(method: str, reason: str) -> None:
    core = _core()
    status = getattr(core, method)()
    assert status.state is runtime.RuntimeStateV1.TERMINATED
    assert status.reason == reason
    assert core.capabilities().total == 0
    assert core.inbox().total == 0


def test_concurrent_terminal_calls_are_linearized_and_callbacks_run_once() -> None:
    entered = threading.Event()
    release = threading.Event()
    callback_count = 0
    callback_lock = threading.Lock()

    def terminate(_reason: str) -> None:
        nonlocal callback_count
        with callback_lock:
            callback_count += 1
        entered.set()
        assert release.wait(3)

    core = _core(components=runtime.RuntimeComponentsV1(grant_terminator=terminate))
    with ThreadPoolExecutor(max_workers=12) as pool:
        first = pool.submit(core.kill)
        assert entered.wait(2)
        others = [pool.submit(core.revoke) for _ in range(10)]
        assert all(item.result(2).state is runtime.RuntimeStateV1.TERMINATED for item in others)
        release.set()
        assert first.result(2).state is runtime.RuntimeStateV1.TERMINATED
    assert callback_count == 1


def test_event_driven_capability_projection_is_bounded_to_128_and_pages_to_50() -> None:
    batches = iter(
        runtime.ProjectionBatchV1(
            tuple({"capability_id": f"capability-{start + index:03d}", "status": "shadow"} for index in range(50)),
            replace=start == 0,
        )
        for start in (0, 50, 100)
    )
    calls = 0

    def project(binding: runtime.RuntimeBindingV1) -> runtime.ProjectionBatchV1:
        nonlocal calls
        calls += 1
        assert binding == _binding()
        return next(batches)

    before_threads = {item.ident for item in threading.enumerate()}
    core = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV1(nexus_projector=project),
    )
    assert calls == 0
    core.refresh_capabilities()
    core.refresh_capabilities()
    core.refresh_capabilities()
    after_threads = {item.ident for item in threading.enumerate()}
    assert calls == 3
    assert before_threads == after_threads
    first = core.capabilities()
    second = core.capabilities(offset=50)
    third = core.capabilities(offset=100)
    assert (first.total, len(first.items), len(second.items), len(third.items)) == (128, 50, 50, 28)
    assert first.items[0].item_id == "capability-022"
    with pytest.raises(runtime.Phase5RuntimeV1ContractError):
        core.capabilities(page_size=51)


def test_inbox_is_factory_injected_event_driven_bounded_and_read_only() -> None:
    calls: list[tuple[runtime.RuntimeBindingV1, int, str | None]] = []

    class Reader:
        def read_page(
            self,
            *,
            binding: runtime.RuntimeBindingV1,
            page_size: int,
            cursor: str | None,
        ) -> runtime.ProjectionBatchV1:
            calls.append((binding, page_size, cursor))
            return runtime.ProjectionBatchV1(
                tuple({"item_id": f"approval-{index:03d}", "risk": "high"} for index in range(page_size))
            )

    factories: list[runtime.RuntimeBindingV1] = []

    def factory(binding: runtime.RuntimeBindingV1) -> Reader:
        factories.append(binding)
        return Reader()

    core = _core(
        flags=_flags(approval_inbox=True, dashboard_projection=True),
        components=runtime.RuntimeComponentsV1(inbox_factory=factory),
    )
    assert factories == [] and calls == []
    page = core.refresh_inbox(page_size=50)
    assert page.total == 50 and len(page.items) == 50
    assert factories == [_binding()]
    assert calls == [(_binding(), 50, None)]
    dashboard = core.dashboard_read("inbox")
    assert isinstance(dashboard, runtime.ProjectionPageV1)
    assert not any(hasattr(core, name) for name in ("approve", "grant", "dispatch", "execute"))
    with pytest.raises(runtime.Phase5RuntimeV1ContractError):
        core.dashboard_read("approve")


def test_inbox_accumulation_is_bounded_to_128() -> None:
    batches = iter(
        runtime.ProjectionBatchV1(
            tuple({"item_id": f"approval-{start + index:03d}", "risk": "low"} for index in range(50)),
            replace=start == 0,
        )
        for start in (0, 50, 100)
    )

    class Reader:
        def read_page(
            self,
            *,
            binding: runtime.RuntimeBindingV1,
            page_size: int,
            cursor: str | None,
        ) -> runtime.ProjectionBatchV1:
            assert binding == _binding() and page_size == 50 and cursor is None
            return next(batches)

    core = _core(
        flags=_flags(approval_inbox=True),
        components=runtime.RuntimeComponentsV1(inbox_factory=lambda _binding: Reader()),
    )
    core.refresh_inbox()
    core.refresh_inbox()
    core.refresh_inbox()
    assert core.inbox().total == 128
    assert core.inbox().items[0].item_id == "approval-022"


def test_projection_contract_failure_is_atomic_and_latches_component_degraded() -> None:
    valid = runtime.ProjectionBatchV1(({"capability_id": "local.catalog", "status": "shadow"},))
    invalid = runtime.ProjectionBatchV1(({"capability_id": "other", "access_token": "not-projected"},))
    batches = iter((valid, invalid))
    core = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV1(nexus_projector=lambda _binding: next(batches)),
    )
    assert core.refresh_capabilities().total == 1
    assert core.refresh_capabilities().total == 1
    assert core.capabilities().items[0].item_id == "local.catalog"
    assert core.status().component_failures == ("nexus",)
    assert core.evaluate(_action()).disposition is runtime.RuntimeDispositionV1.EXPLICIT


def test_component_health_epoch_prevents_old_decision_resurrection_after_recovery() -> None:
    batches = iter(
        (
            runtime.ProjectionBatchV1(({"capability_id": "first", "status": "shadow"},)),
            runtime.ProjectionBatchV1(({"capability_id": "bad", "secret_token": "x"},)),
            runtime.ProjectionBatchV1(({"capability_id": "recovered", "status": "shadow"},)),
        )
    )
    core = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV1(nexus_projector=lambda _binding: next(batches)),
    )
    core.refresh_capabilities()
    old = core.evaluate(_action())
    assert core.decision_is_current(old)
    core.refresh_capabilities()
    assert not core.decision_is_current(old)
    core.refresh_capabilities()
    assert core.status().component_failures == ()
    assert not core.decision_is_current(old)
    assert core.decision_is_current(core.evaluate(_action()))


def test_termination_callback_failure_cannot_retain_authority() -> None:
    def fail(_reason: str) -> None:
        raise RuntimeError("failure")

    core = _core(components=runtime.RuntimeComponentsV1(grant_terminator=fail))
    allowed = core.evaluate(_action())
    status = core.shutdown()
    assert status.state is runtime.RuntimeStateV1.TERMINATED
    assert status.termination_failures == ("grant",)
    assert not core.decision_is_current(allowed)


def test_in_memory_decision_p95_is_below_25ms() -> None:
    core = _core()
    samples: list[float] = []
    action = _action()
    for _ in range(1_000):
        started = time.perf_counter_ns()
        assert core.evaluate(action).disposition is runtime.RuntimeDispositionV1.ALLOW_LOCAL_CATALOG_READ
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    p95 = statistics.quantiles(samples, n=100, method="inclusive")[94]
    assert p95 <= 25.0
    assert len(core.events()) <= runtime.MAX_PAGE_SIZE
    assert core.status().event_count == runtime.MAX_EVENTS
