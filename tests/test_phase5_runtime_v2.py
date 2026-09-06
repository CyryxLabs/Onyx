from __future__ import annotations

import copy
import dataclasses
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import core.phase5_runtime_v2 as runtime


def _binding(**changes: object) -> runtime.RuntimeBindingV2:
    values: dict[str, object] = {
        "trace_id": "trace-one",
        "session_id": "session-one",
        "workspace_id": "workspace-one",
        "account_id": "account-one",
        "profile_id": "profile-one",
    }
    values.update(changes)
    return runtime.RuntimeBindingV2(**values)  # type: ignore[arg-type]


def _flags(**changes: object) -> runtime.RuntimeFlagsV2:
    values: dict[str, object] = {
        "runtime": True,
        "grant_shadow": False,
        "approval_inbox": False,
        "low_risk": True,
        "nexus_projection": False,
        "local_catalog_read": True,
        "dashboard_projection": False,
    }
    values.update(changes)
    return runtime.RuntimeFlagsV2(**values)  # type: ignore[arg-type]


def _action(binding: runtime.RuntimeBindingV2 | None = None, **changes: object) -> runtime.ActionRequestV2:
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
    return runtime.ActionRequestV2(**values)  # type: ignore[arg-type]


def _core(
    *,
    flags: runtime.RuntimeFlagsV2 | None = None,
    components: runtime.RuntimeComponentsV2 | None = None,
    binding: runtime.RuntimeBindingV2 | None = None,
) -> runtime.Phase5RuntimeV2:
    return runtime.Phase5RuntimeV2(
        binding=binding or _binding(),
        flags=flags or _flags(),
        components=components,
    )


def test_flags_are_separate_exact_and_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert runtime.RuntimeFlagsV2.from_environ() == runtime.RuntimeFlagsV2()
    for name in names:
        values = {item: "false" for item in names}
        values[name] = "true"
        assert sum(dict(runtime.RuntimeFlagsV2.from_environ(values).payload()).values()) == 1
    for field in runtime.RuntimeFlagsV2.__dataclass_fields__:
        with pytest.raises(runtime.Phase5RuntimeV2ContractError):
            runtime.RuntimeFlagsV2(**{field: 1})


def test_fallback_is_observationally_pure_and_never_calls_components() -> None:
    touched: list[str] = []
    components = runtime.RuntimeComponentsV2(
        grant_evaluator=lambda reference: touched.append(reference),
        nexus_projector=lambda binding: (_ for _ in ()).throw(AssertionError(binding)),
    )
    disabled = _core(flags=_flags(runtime=False, grant_shadow=True), components=components)
    baseline = disabled.status()
    marker = object()
    assert disabled.legacy_or_decision(object(), lambda: marker) is marker  # type: ignore[arg-type]
    assert disabled.status() == baseline
    assert disabled.events() == ()
    assert touched == []

    path_off = _core(flags=_flags(low_risk=False), components=components)
    baseline = path_off.status()
    assert path_off.legacy_or_decision(_action(), lambda: marker) is marker
    assert path_off.status() == baseline
    assert path_off.events() == ()
    assert touched == []


def test_only_exact_catalog_read_is_allowed_and_sealed() -> None:
    core = _core()
    decision = core.evaluate(_action())
    assert decision.disposition is runtime.RuntimeDispositionV2.ALLOW_LOCAL_CATALOG_READ
    assert decision.reason == "exact_provider_free_catalog_read"
    assert core.decision_is_current(decision)


@pytest.mark.parametrize(
    ("change", "value"),
    (
        ("capability", "local.files"), ("operation", "catalog_list"),
        ("provider_free", False), ("read_only", False), ("effect", "write"),
        ("egress", "local"), ("metadata_allowlisted", False), ("cost_micro", 1),
        ("risk", "medium"), ("reversible", False), ("uses_credentials", True),
        ("privileged", True), ("irreversible", True),
    ),
)
def test_near_miss_catalog_reads_are_explicit(change: str, value: object) -> None:
    assert _core().evaluate(_action(**{change: value})).disposition is runtime.RuntimeDispositionV2.EXPLICIT


@pytest.mark.parametrize(
    "action_class",
    (
        "money", "send", "publish", "ads", "deploy", "delete", "credentials", "oauth",
        "roles", "install", "privileged", "legal", "political", "crisis", "irreversible",
    ),
)
def test_always_explicit_classes_remain_explicit(action_class: str) -> None:
    decision = _core().evaluate(_action(action_classes=(action_class,)))
    assert decision.disposition is runtime.RuntimeDispositionV2.EXPLICIT
    assert decision.reason == "explicit_action_class"


def test_always_explicit_precedes_low_risk_extension_fallback() -> None:
    core = _core(flags=_flags(low_risk=False, local_catalog_read=False))
    decision = core.evaluate(_action(action_classes=("money",)))
    assert decision.disposition is runtime.RuntimeDispositionV2.EXPLICIT


@pytest.mark.parametrize("operation", ("send_message", "publish", "oauth_grant", "delete", "deploy_app"))
def test_always_explicit_operation_words(operation: str) -> None:
    decision = _core().evaluate(_action(operation=operation))
    assert decision.disposition is runtime.RuntimeDispositionV2.EXPLICIT
    assert decision.reason == "explicit_action_class"


def test_binding_mismatch_is_explicit_for_every_dimension() -> None:
    core = _core()
    for field in runtime.RuntimeBindingV2.__dataclass_fields__:
        foreign = dataclasses.replace(_binding(), **{field: f"foreign-{field}"})
        assert core.evaluate(_action(foreign)).reason == "scope_mismatch"


def test_runtime_snapshots_external_binding_flags_and_component_container() -> None:
    binding = _binding()
    flags = _flags()
    def safe_observer(_reference: str) -> dict[str, str]:
        return {"outcome": "safe"}

    components = runtime.RuntimeComponentsV2(grant_evaluator=safe_observer)
    core = _core(binding=binding, flags=flags, components=components)

    object.__setattr__(binding, "trace_id", "foreign-trace")
    object.__setattr__(flags, "runtime", False)
    object.__setattr__(components, "grant_evaluator", lambda _reference: (_ for _ in ()).throw(RuntimeError()))

    assert core.binding == _binding()
    assert core.flags == _flags()
    assert core.evaluate(_action()).disposition is runtime.RuntimeDispositionV2.ALLOW_LOCAL_CATALOG_READ


def test_returned_binding_and_flags_are_disposable_snapshots() -> None:
    core = _core()
    external_binding = core.binding
    external_flags = core.flags
    object.__setattr__(external_binding, "trace_id", "foreign-trace")
    object.__setattr__(external_flags, "runtime", False)
    assert core.binding == _binding()
    assert core.flags == _flags()
    assert core.evaluate(_action()).disposition is runtime.RuntimeDispositionV2.ALLOW_LOCAL_CATALOG_READ


def test_action_snapshots_binding_and_runtime_resnapshots_action_at_entry() -> None:
    external_binding = _binding()
    action = _action(external_binding)
    object.__setattr__(external_binding, "trace_id", "foreign-trace")
    assert action.binding == _binding()
    core = _core()
    assert core.evaluate(action).disposition is runtime.RuntimeDispositionV2.ALLOW_LOCAL_CATALOG_READ

    object.__setattr__(action, "provider_free", 1)
    invalid = core.evaluate(action)
    assert invalid.disposition is runtime.RuntimeDispositionV2.EXPLICIT
    assert invalid.reason == "invalid_action_contract"


@pytest.mark.parametrize(
    "field",
    (
        "provider_free", "read_only", "metadata_allowlisted", "reversible",
        "uses_credentials", "privileged", "irreversible",
    ),
)
@pytest.mark.parametrize("value", (0, 1, "true", object()))
def test_action_boolean_fields_require_exact_bool(field: str, value: object) -> None:
    with pytest.raises(runtime.Phase5RuntimeV2ContractError):
        _action(**{field: value})


@pytest.mark.parametrize("value", (False, True, -1, runtime.MAX_INTEGER + 1, 1.0, "0", object()))
def test_cost_requires_exact_non_boolean_int(value: object) -> None:
    with pytest.raises(runtime.Phase5RuntimeV2ContractError):
        _action(cost_micro=value)


def test_action_strings_are_exact_nonempty_and_not_subclasses() -> None:
    class Text(str):
        pass

    for field in ("capability", "operation", "effect", "egress", "risk"):
        for value in ("", " value", "value ", Text("value")):
            with pytest.raises(runtime.Phase5RuntimeV2ContractError):
                _action(**{field: value})


def test_forged_copied_and_replayed_decisions_are_never_current() -> None:
    core = _core()
    issued = core.evaluate(_action())
    forged = runtime.RuntimeDecisionV2(
        issued.disposition, issued.reason, issued.trace_id, issued.epoch, issued.advisory_json
    )
    assert not core.decision_is_current(forged)
    assert not core.decision_is_current(copy.copy(issued))
    assert not core.decision_is_current(dataclasses.replace(issued))
    assert not _core().decision_is_current(issued)
    assert core.decision_is_current(issued)


def test_mutating_issued_decision_breaks_private_registry_seal() -> None:
    core = _core()
    decision = core.evaluate(_action())
    assert core.decision_is_current(decision)
    object.__setattr__(decision, "reason", "forged-reason")
    assert not core.decision_is_current(decision)

    other = core.evaluate(_action())
    object.__setattr__(other, "disposition", "ALLOW_LOCAL_CATALOG_READ")
    assert not core.decision_is_current(other)


def test_authorized_reconfiguration_advances_epoch_and_invalidates_everything() -> None:
    component = runtime.RuntimeComponentsV2(
        nexus_projector=lambda _binding: runtime.ProjectionBatchV2(
            ({"capability_id": "local.catalog", "status": "shadow"},)
        )
    )
    core = _core(flags=_flags(nexus_projection=True), components=component)
    core.refresh_capabilities()
    decision = core.evaluate(_action())
    previous = core.status().epoch
    assert core.decision_is_current(decision) and core.capabilities().total == 1

    assert core.configure_flags(_flags(nexus_projection=True)).epoch == previous + 1
    assert not core.decision_is_current(decision) and core.capabilities().total == 0
    previous += 1
    assert core.rebind(_binding()).epoch == previous + 1
    previous += 1
    assert core.replace_components(component).epoch == previous + 1


def test_projection_batch_owns_deep_immutable_snapshot() -> None:
    raw = {"capability_id": "local.catalog", "nested": {"items": [1, 2]}}
    batch = runtime.ProjectionBatchV2((raw,))
    raw["capability_id"] = "changed"
    raw["nested"] = {"items": [9]}
    assert batch.items[0]["capability_id"] == "local.catalog"
    with pytest.raises(TypeError):
        batch.items[0]["capability_id"] = "changed"  # type: ignore[index]


def test_projection_pages_and_events_return_disposable_snapshots() -> None:
    core = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV2(
            nexus_projector=lambda _binding: runtime.ProjectionBatchV2(
                ({"capability_id": "local.catalog", "status": "shadow"},)
            )
        ),
    )
    core.refresh_capabilities()
    page = core.capabilities()
    event = core.events()[0]
    object.__setattr__(page.items[0], "item_id", "forged")
    object.__setattr__(event, "kind", "forged")
    assert core.capabilities().items[0].item_id == "local.catalog"
    assert core.events()[0].kind == "capabilities"


def test_capability_projection_is_bounded_event_driven_and_carries_cursors() -> None:
    batches = iter(
        runtime.ProjectionBatchV2(
            tuple({"capability_id": f"capability-{start + index:03d}", "status": "shadow"} for index in range(50)),
            replace=start == 0,
            source_cursor=None if start == 0 else f"source-{start}",
            next_cursor=f"next-{start}",
        )
        for start in (0, 50, 100)
    )
    calls = 0

    def project(binding: runtime.RuntimeBindingV2) -> runtime.ProjectionBatchV2:
        nonlocal calls
        calls += 1
        assert binding == _binding()
        return next(batches)

    before = {thread.ident for thread in threading.enumerate()}
    core = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV2(nexus_projector=project),
    )
    for _ in range(3):
        core.refresh_capabilities()
    after = {thread.ident for thread in threading.enumerate()}
    page = core.capabilities()
    assert calls == 3 and before == after
    assert page.total == 128 and page.items[0].item_id == "capability-022"
    assert page.source_cursor == "source-100" and page.next_cursor == "next-100"


def test_inbox_cursor_propagation_is_exact_across_multiple_pages() -> None:
    expected = [None, "cursor-50", "cursor-100"]
    calls: list[str | None] = []

    class Reader:
        def read_page(
            self,
            *,
            binding: runtime.RuntimeBindingV2,
            page_size: int,
            cursor: str | None,
        ) -> runtime.ProjectionBatchV2:
            assert binding == _binding() and page_size == 50
            calls.append(cursor)
            index = expected.index(cursor)
            start = index * 50
            return runtime.ProjectionBatchV2(
                tuple({"item_id": f"approval-{start + offset:03d}", "risk": "low"} for offset in range(50)),
                replace=cursor is None,
                source_cursor=cursor,
                next_cursor=None if index == 2 else expected[index + 1],
            )

    core = _core(
        flags=_flags(approval_inbox=True),
        components=runtime.RuntimeComponentsV2(inbox_factory=lambda _binding: Reader()),
    )
    first = core.refresh_inbox(cursor=None)
    second = core.refresh_inbox(cursor=first.next_cursor)
    third = core.refresh_inbox(cursor=second.next_cursor)
    assert calls == expected
    assert (first.source_cursor, first.next_cursor) == (None, "cursor-50")
    assert (second.source_cursor, second.next_cursor) == ("cursor-50", "cursor-100")
    assert (third.source_cursor, third.next_cursor) == ("cursor-100", None)
    assert third.total == 128
    identifiers = tuple(item.item_id for page in (core.inbox(), core.inbox(offset=50), core.inbox(offset=100)) for item in page.items)
    assert len(identifiers) == len(set(identifiers)) == 128
    assert identifiers[0] == "approval-022" and identifiers[-1] == "approval-149"


def test_inbox_rejects_wrong_call_or_source_cursor_without_partial_publish() -> None:
    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV2:
            return runtime.ProjectionBatchV2(
                ({"item_id": "approval-one", "risk": "low"},),
                source_cursor="forged-cursor",
                next_cursor="next-cursor",
            )

    core = _core(
        flags=_flags(approval_inbox=True),
        components=runtime.RuntimeComponentsV2(inbox_factory=lambda _binding: Reader()),
    )
    assert core.refresh_inbox().total == 0
    assert core.status().component_failures == ("inbox",)


def test_inbox_rejects_duplicate_across_pages_atomically() -> None:
    batches = iter(
        (
            runtime.ProjectionBatchV2(
                ({"item_id": "approval-one", "risk": "low"},), next_cursor="next-one"
            ),
            runtime.ProjectionBatchV2(
                ({"item_id": "approval-one", "risk": "low"},),
                replace=False,
                source_cursor="next-one",
            ),
        )
    )

    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV2:
            return next(batches)

    core = _core(
        flags=_flags(approval_inbox=True),
        components=runtime.RuntimeComponentsV2(inbox_factory=lambda _binding: Reader()),
    )
    assert core.refresh_inbox().total == 1
    assert core.refresh_inbox(cursor="next-one").total == 1
    assert core.status().component_failures == ("inbox",)


def test_dashboard_is_read_only_and_has_no_authority_methods() -> None:
    core = _core(flags=_flags(dashboard_projection=True))
    assert isinstance(core.dashboard_read("status"), runtime.RuntimeStatusV2)
    assert not any(hasattr(core, name) for name in ("approve", "grant", "dispatch", "execute"))
    with pytest.raises(runtime.Phase5RuntimeV2ContractError):
        core.dashboard_read("approve")


@pytest.mark.parametrize(
    ("method", "reason"),
    (
        ("kill", "kill"), ("revoke", "revoke"), ("rollback", "rollback"),
        ("end_session", "end_session"), ("reconnect", "reconnect"), ("shutdown", "shutdown"),
    ),
)
def test_every_terminal_api_uses_single_boundary(method: str, reason: str) -> None:
    status = getattr(_core(), method)()
    assert status.state is runtime.RuntimeStateV2.TERMINATED
    assert status.reason == reason


def test_concurrent_terminal_callers_wait_for_blocked_revoker_and_share_outcome() -> None:
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

    core = _core(components=runtime.RuntimeComponentsV2(grant_terminator=terminate))
    with ThreadPoolExecutor(max_workers=12) as pool:
        first = pool.submit(core.kill)
        assert entered.wait(2)
        others = [pool.submit(core.revoke) for _ in range(10)]
        time.sleep(0.05)
        assert not first.done() and not any(item.done() for item in others)
        assert core.status().state is runtime.RuntimeStateV2.TERMINATING
        release.set()
        outcomes = [first.result(2), *(item.result(2) for item in others)]
    assert callback_count == 1
    assert all(item == outcomes[0] for item in outcomes)
    assert outcomes[0].state is runtime.RuntimeStateV2.TERMINATED
    assert outcomes[0].reason == "kill"


def test_terminal_callback_failure_is_shared_and_fail_closed() -> None:
    entered = threading.Event()
    release = threading.Event()

    def fail(_reason: str) -> None:
        entered.set()
        assert release.wait(3)
        raise RuntimeError("external failure")

    core = _core(components=runtime.RuntimeComponentsV2(grant_terminator=fail))
    decision = core.evaluate(_action())
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(core.shutdown)
        assert entered.wait(2)
        second = pool.submit(core.revoke)
        time.sleep(0.05)
        assert not second.done()
        assert not core.decision_is_current(decision)
        release.set()
        one, two = first.result(2), second.result(2)
    assert one == two
    assert one.state is runtime.RuntimeStateV2.TERMINATED
    assert one.termination_failures == ("grant",)


def test_reentrant_terminal_callback_fails_closed_without_deadlock() -> None:
    holder: dict[str, runtime.Phase5RuntimeV2] = {}

    def reenter(_reason: str) -> None:
        holder["core"].revoke()

    core = _core(components=runtime.RuntimeComponentsV2(grant_terminator=reenter))
    holder["core"] = core
    status = core.kill()
    assert status.state is runtime.RuntimeStateV2.TERMINATED
    assert status.reason == "kill"
    assert status.termination_failures == ("grant",)


def test_kill_during_grant_observation_fails_closed_without_deadlock() -> None:
    entered = threading.Event()
    release = threading.Event()

    def observe(_reference: str) -> dict[str, str]:
        entered.set()
        assert release.wait(3)
        return {"outcome": "would-allow"}

    core = _core(
        flags=_flags(grant_shadow=True),
        components=runtime.RuntimeComponentsV2(grant_evaluator=observe),
    )
    decisions: list[runtime.RuntimeDecisionV2] = []
    worker = threading.Thread(target=lambda: decisions.append(core.evaluate(_action())))
    worker.start()
    assert entered.wait(2)
    status = core.kill()
    release.set()
    worker.join(2)
    assert status.state is runtime.RuntimeStateV2.TERMINATED
    assert decisions[0].reason == "authority_revoked_during_evaluation"


def test_decision_registry_is_bounded_and_p95_below_25ms() -> None:
    core = _core()
    action = _action()
    samples: list[float] = []
    decisions: list[runtime.RuntimeDecisionV2] = []
    for _ in range(1_000):
        started = time.perf_counter_ns()
        decisions.append(core.evaluate(action))
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    p95 = statistics.quantiles(samples, n=100, method="inclusive")[94]
    assert p95 <= 25.0
    assert not core.decision_is_current(decisions[0])
    assert core.decision_is_current(decisions[-1])
    assert core.status().event_count == runtime.MAX_EVENTS
