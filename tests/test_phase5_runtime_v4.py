from __future__ import annotations

import copy
import dataclasses
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import core.phase5_runtime_v4 as runtime


def _binding(**changes: object) -> runtime.RuntimeBindingV4:
    values: dict[str, object] = {
        "trace_id": "trace-one",
        "session_id": "session-one",
        "workspace_id": "workspace-one",
        "account_id": "account-one",
        "profile_id": "profile-one",
    }
    values.update(changes)
    return runtime.RuntimeBindingV4(**values)  # type: ignore[arg-type]


def _flags(**changes: object) -> runtime.RuntimeFlagsV4:
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
    return runtime.RuntimeFlagsV4(**values)  # type: ignore[arg-type]


def _action(
    binding: runtime.RuntimeBindingV4 | None = None, **changes: object
) -> runtime.ActionRequestV4:
    values: dict[str, object] = {
        "invocation_ref": "opaque-invocation-one",
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
    return runtime.ActionRequestV4(**values)  # type: ignore[arg-type]


def _cap(identifier: str = "cap-one", **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "capability_id": identifier,
        "display_name": "Local Catalog",
        "provider": "Onyx local",
        "version": "1.0",
        "status": "available",
        "operations": ["catalog_read"],
        "limitation": None,
    }
    value.update(changes)
    return value


def _item(identifier: str = "item-one", **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "item_id": identifier,
        "request_ref": f"request-{identifier}",
        "capability": "local.catalog",
        "operation": "catalog_read",
        "risk": "low",
        "state": "pending",
        "summary": "Read local catalog metadata",
        "created_at": "2026-07-21T20:00:00Z",
    }
    value.update(changes)
    return value


def _core(
    *,
    flags: runtime.RuntimeFlagsV4 | None = None,
    components: runtime.RuntimeComponentsV4 | None = None,
) -> runtime.Phase5RuntimeV4:
    return runtime.Phase5RuntimeV4(
        binding=_binding(), flags=flags or _flags(), components=components
    )


def test_flags_are_independent_exact_and_default_off() -> None:
    names = (
        runtime.PHASE5_RUNTIME_FLAG,
        runtime.PHASE5_GRANT_SHADOW_FLAG,
        runtime.PHASE5_APPROVAL_INBOX_FLAG,
        runtime.PHASE5_LOW_RISK_FLAG,
        runtime.PHASE5_NEXUS_PROJECTION_FLAG,
        runtime.PHASE5_LOCAL_CATALOG_READ_FLAG,
        runtime.PHASE5_DASHBOARD_PROJECTION_FLAG,
    )
    assert runtime.RuntimeFlagsV4.from_environ({}) == runtime.RuntimeFlagsV4()
    for name in names:
        values = {item: "false" for item in names}
        values[name] = "true"
        assert (
            sum(dict(runtime.RuntimeFlagsV4.from_environ(values).payload()).values())
            == 1
        )
    for field in runtime.RuntimeFlagsV4.__dataclass_fields__:
        with pytest.raises(runtime.Phase5RuntimeV4ContractError):
            runtime.RuntimeFlagsV4(**{field: 1})


def test_default_off_is_observationally_pure() -> None:
    touched: list[str] = []
    core = _core(
        flags=_flags(runtime=False, grant_shadow=True, nexus_projection=True),
        components=runtime.RuntimeComponentsV4(
            grant_evaluator=lambda reference: touched.append(reference),
            nexus_projector=lambda binding: (_ for _ in ()).throw(
                AssertionError(binding)
            ),
        ),
    )
    before = core.status()
    marker = object()
    assert core.legacy_or_decision(object(), lambda: marker) is marker  # type: ignore[arg-type]
    assert core.status() == before and core.events() == () and touched == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("capability", "local.files"),
        ("operation", "catalog_list"),
        ("provider_free", False),
        ("read_only", False),
        ("effect", "write"),
        ("egress", "local"),
        ("metadata_allowlisted", False),
        ("cost_micro", 1),
        ("risk", "medium"),
        ("reversible", False),
        ("uses_credentials", True),
        ("privileged", True),
        ("irreversible", True),
    ),
)
def test_only_exact_local_catalog_read_can_be_allowed(
    field: str, value: object
) -> None:
    assert (
        _core().evaluate(_action(**{field: value})).disposition
        is runtime.RuntimeDispositionV4.EXPLICIT
    )


@pytest.mark.parametrize(
    "action_class",
    (
        "money",
        "send",
        "publish",
        "ads",
        "deploy",
        "delete",
        "credentials",
        "oauth",
        "roles",
        "install",
        "privileged",
        "legal",
        "political",
        "crisis",
        "irreversible",
    ),
)
def test_always_explicit_classes(action_class: str) -> None:
    decision = _core().evaluate(_action(action_classes=(action_class,)))
    assert decision.disposition is runtime.RuntimeDispositionV4.EXPLICIT
    assert decision.reason == "explicit_action_class"


def test_decision_requires_exact_request_and_is_single_use() -> None:
    core = _core()
    action = _action()
    decision = core.evaluate(action)
    assert decision.disposition is runtime.RuntimeDispositionV4.ALLOW_LOCAL_CATALOG_READ
    assert not core.decision_is_current(decision)
    assert core.decision_is_current(decision, action)
    assert not core.decision_is_current(
        decision, dataclasses.replace(action, invocation_ref="other-invocation")
    )
    assert not core.consume_decision(copy.copy(decision), action)
    assert core.consume_decision(decision, action)
    assert not core.consume_decision(decision, action)
    assert not core.decision_is_current(decision, action)


def test_decision_for_one_request_cannot_authorize_equivalent_looking_other_request() -> (
    None
):
    core = _core()
    issued_for = _action(invocation_ref="opaque-first")
    decision = core.evaluate(issued_for)
    for other in (
        _action(invocation_ref="opaque-second"),
        _action(
            binding=_binding(workspace_id="workspace-two"),
            invocation_ref="opaque-first",
        ),
        _action(operation="catalog_list", invocation_ref="opaque-first"),
    ):
        assert not core.consume_decision(decision, other)
    assert core.consume_decision(decision, issued_for)


def test_authority_is_retired_by_configuration_failure_and_termination() -> None:
    core = _core()
    action = _action()
    decision = core.evaluate(action)
    core.configure_flags(_flags(dashboard_projection=True))
    assert not core.consume_decision(decision, action)
    current = core.evaluate(action)
    core.revoke()
    assert not core.consume_decision(current, action)


def test_closed_capability_schema_projects_only_runtime_binding() -> None:
    supplied = _cap()
    core = _core(
        flags=_flags(nexus_projection=True, dashboard_projection=True),
        components=runtime.RuntimeComponentsV4(
            nexus_projector=lambda binding: runtime.ProjectionBatchV4((supplied,)),
        ),
    )
    page = core.refresh_capabilities()
    payload = page.items[0].payload()
    assert set(payload) == {
        "capability_id",
        "display_name",
        "provider",
        "version",
        "status",
        "operations",
        "limitation",
        "trace_id",
        "session_id",
        "workspace_id",
        "account_id",
        "profile_id",
    }
    for field in runtime.RuntimeBindingV4.__dataclass_fields__:
        assert payload[field] == getattr(_binding(), field)
    assert core.dashboard_read("capabilities") == page


@pytest.mark.parametrize(
    "field",
    (
        "workspace_id",
        "account_id",
        "profile_id",
        "trace_id",
        "apiKey",
        "token",
        "arbitrary",
    ),
)
def test_capability_rejects_provider_authority_secret_and_arbitrary_fields(
    field: str,
) -> None:
    raw = _cap()
    raw[field] = "foreign-or-secret"
    core = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV4(
            nexus_projector=lambda _binding: runtime.ProjectionBatchV4((raw,))
        ),
    )
    assert core.refresh_capabilities().total == 0
    assert core.status().component_failures == ("nexus",)


def test_central_dlp_redacts_sensitive_values_from_all_dashboard_projection() -> None:
    canary = "api_key=SUPER-SECRET-CANARY"
    core = _core(
        flags=_flags(nexus_projection=True, dashboard_projection=True),
        components=runtime.RuntimeComponentsV4(
            nexus_projector=lambda _binding: runtime.ProjectionBatchV4(
                (_cap(display_name=canary, limitation=canary),)
            ),
        ),
    )
    payload = core.refresh_capabilities().items[0].payload()
    rendered = (
        repr(core.dashboard_read("capabilities"))
        + repr(core.dashboard_read("status"))
        + repr(core.dashboard_read("events"))
    )
    assert (
        payload["display_name"] == "[REDACTED]"
        and payload["limitation"] == "[REDACTED]"
    )
    assert "SUPER-SECRET-CANARY" not in rendered


def test_closed_inbox_schema_and_runtime_scope_projection() -> None:
    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV4:
            return runtime.ProjectionBatchV4(
                (_item(),), source_cursor=None, next_cursor=None
            )

    core = _core(
        flags=_flags(approval_inbox=True, dashboard_projection=True),
        components=runtime.RuntimeComponentsV4(inbox_factory=lambda _binding: Reader()),
    )
    payload = core.refresh_inbox().items[0].payload()
    assert set(payload) == {
        "item_id",
        "request_ref",
        "capability",
        "operation",
        "risk",
        "state",
        "summary",
        "created_at",
        "trace_id",
        "session_id",
        "workspace_id",
        "account_id",
        "profile_id",
    }
    assert payload["workspace_id"] == "workspace-one"


@pytest.mark.parametrize(
    "field", ("workspace_id", "account_id", "profile_id", "secret", "arbitrary")
)
def test_inbox_rejects_cross_scope_secret_and_arbitrary_fields(field: str) -> None:
    raw = _item()
    raw[field] = "provider-controlled"

    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV4:
            return runtime.ProjectionBatchV4((raw,), source_cursor=None)

    core = _core(
        flags=_flags(approval_inbox=True),
        components=runtime.RuntimeComponentsV4(inbox_factory=lambda _binding: Reader()),
    )
    assert core.refresh_inbox().total == 0 and core.status().component_failures == (
        "inbox",
    )


def test_json_budget_rejects_cycle_shared_dag_depth_fanout_and_million_expansion_early() -> (
    None
):
    cycle: list[object] = []
    cycle.append(cycle)
    shared: list[object] = ["leaf"]
    dag = [shared, shared]
    deep: object = "leaf"
    for _ in range(runtime.MAX_DEPTH + 2):
        deep = [deep]
    million = [shared] * 1_000_000
    for value in (cycle, dag, deep, million):
        with pytest.raises(runtime.Phase5RuntimeV4ContractError):
            runtime.ProjectionBatchV4(({"capability_id": "cap", "payload": value},))
    repeated_item = _cap()
    with pytest.raises(runtime.Phase5RuntimeV4ContractError):
        runtime.ProjectionBatchV4((repeated_item, repeated_item))


def test_json_budget_counts_incrementally_and_does_not_mutate_input() -> None:
    operations = [f"read-{index}" for index in range(16)]
    raw = _cap(operations=operations)
    batch = runtime.ProjectionBatchV4((raw,))
    operations.append("late-mutation")
    assert tuple(batch.items[0]["operations"]) == tuple(
        f"read-{index}" for index in range(16)
    )


def test_concurrent_component_failures_are_both_recorded_regardless_of_finish_order() -> (
    None
):
    barrier = threading.Barrier(2)
    release_nexus = threading.Event()
    release_inbox = threading.Event()

    def nexus(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        barrier.wait()
        release_nexus.wait()
        raise RuntimeError("nexus failed")

    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV4:
            barrier.wait()
            release_inbox.wait()
            raise RuntimeError("inbox failed")

    core = _core(
        flags=_flags(nexus_projection=True, approval_inbox=True),
        components=runtime.RuntimeComponentsV4(
            nexus_projector=nexus, inbox_factory=lambda _binding: Reader()
        ),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(core.refresh_capabilities)
        second = pool.submit(core.refresh_inbox)
        release_inbox.set()
        time.sleep(0.01)
        release_nexus.set()
        first.result()
        second.result()
    assert core.status().component_failures == ("inbox", "nexus")
    assert core.status().state is runtime.RuntimeStateV4.DEGRADED


def test_partial_component_recovery_never_becomes_ready_or_allow() -> None:
    state = {"nexus": False, "inbox": False}

    def nexus(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        if not state["nexus"]:
            raise RuntimeError
        return runtime.ProjectionBatchV4((_cap(),))

    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV4:
            if not state["inbox"]:
                raise RuntimeError
            return runtime.ProjectionBatchV4((_item(),), source_cursor=None)

    core = _core(
        flags=_flags(nexus_projection=True, approval_inbox=True),
        components=runtime.RuntimeComponentsV4(
            nexus_projector=nexus, inbox_factory=lambda _binding: Reader()
        ),
    )
    core.refresh_capabilities()
    core.refresh_inbox()
    state["nexus"] = True
    core.recover_component("nexus")
    assert core.status().component_failures == ("inbox",)
    assert core.status().state is runtime.RuntimeStateV4.DEGRADED
    assert core.evaluate(_action()).disposition is runtime.RuntimeDispositionV4.EXPLICIT
    state["inbox"] = True
    core.recover_component("inbox")
    assert (
        core.status().component_failures == ()
        and core.status().state is runtime.RuntimeStateV4.READY
    )


def test_opposite_concurrent_failure_completion_order_is_also_lossless() -> None:
    barrier = threading.Barrier(2)
    release_nexus = threading.Event()
    release_inbox = threading.Event()

    def nexus(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        barrier.wait()
        release_nexus.wait()
        raise RuntimeError

    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV4:
            barrier.wait()
            release_inbox.wait()
            raise RuntimeError

    core = _core(
        flags=_flags(nexus_projection=True, approval_inbox=True),
        components=runtime.RuntimeComponentsV4(
            nexus_projector=nexus, inbox_factory=lambda _binding: Reader()
        ),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        n = pool.submit(core.refresh_capabilities)
        i = pool.submit(core.refresh_inbox)
        release_nexus.set()
        time.sleep(0.01)
        release_inbox.set()
        n.result()
        i.result()
    assert core.status().component_failures == ("inbox", "nexus")


def test_concurrent_failure_after_ordinary_success_remains_until_explicit_recovery() -> (
    None
):
    first_entered = threading.Event()
    release_first = threading.Event()
    call = 0

    def nexus(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        nonlocal call
        call += 1
        if call == 1:
            first_entered.set()
            release_first.wait()
            raise RuntimeError
        return runtime.ProjectionBatchV4((_cap(),))

    core = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV4(nexus_projector=nexus),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        stale = pool.submit(core.refresh_capabilities)
        first_entered.wait()
        fresh = pool.submit(core.refresh_capabilities)
        fresh.result()
        release_first.set()
        stale.result()
    assert core.status().component_failures == ("nexus",)
    assert core.capabilities().total == 1
    assert core.recover_component("nexus").component_failures == ()


def test_cursor_chain_is_bounded_fail_closed_and_restartable() -> None:
    calls = 0

    class Reader:
        def read_page(
            self, *, cursor: str | None, **_kwargs: object
        ) -> runtime.ProjectionBatchV4:
            nonlocal calls
            calls += 1
            index = 0 if cursor is None else int(cursor.split("-")[1])
            next_cursor = f"cursor-{index + 1}"
            return runtime.ProjectionBatchV4(
                (_item(f"item-{index}"),),
                replace=cursor is None,
                source_cursor=cursor,
                next_cursor=next_cursor,
            )

    core = _core(
        flags=_flags(approval_inbox=True),
        components=runtime.RuntimeComponentsV4(inbox_factory=lambda _binding: Reader()),
    )
    page = core.refresh_inbox()
    for _ in range(10_000):
        page = core.refresh_inbox(cursor=page.next_cursor)
    assert calls == runtime.MAX_CURSOR_HISTORY + 1
    assert core.status().component_failures == ("inbox",)
    restarted = core.refresh_inbox(cursor=None)
    assert calls == runtime.MAX_CURSOR_HISTORY + 2
    assert restarted.source_cursor is None and restarted.next_cursor == "cursor-1"
    assert core.status().component_failures == ("inbox",)
    assert core.recover_component("inbox").component_failures == ()


def test_empty_page_with_continuation_fails_closed_without_looping() -> None:
    calls = 0

    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV4:
            nonlocal calls
            calls += 1
            return runtime.ProjectionBatchV4(
                (), source_cursor=None, next_cursor="repeat"
            )

    core = _core(
        flags=_flags(approval_inbox=True),
        components=runtime.RuntimeComponentsV4(inbox_factory=lambda _binding: Reader()),
    )
    assert core.refresh_inbox().next_cursor is None
    assert calls == 1 and core.status().component_failures == ("inbox",)


def test_repeated_or_wrong_cursor_is_rejected_without_provider_call() -> None:
    calls: list[str | None] = []

    class Reader:
        def read_page(
            self, *, cursor: str | None, **_kwargs: object
        ) -> runtime.ProjectionBatchV4:
            calls.append(cursor)
            return runtime.ProjectionBatchV4(
                (_item("first" if cursor is None else "second"),),
                replace=cursor is None,
                source_cursor=cursor,
                next_cursor="next-two" if cursor is None else None,
            )

    core = _core(
        flags=_flags(approval_inbox=True),
        components=runtime.RuntimeComponentsV4(inbox_factory=lambda _binding: Reader()),
    )
    page = core.refresh_inbox()
    assert page.next_cursor == "next-two"
    with pytest.raises(runtime.Phase5RuntimeV4ContractError):
        core.refresh_inbox(cursor="wrong")
    assert calls == [None]
    page = core.refresh_inbox(cursor="next-two")
    assert page.source_cursor == "next-two"


def test_dashboard_surfaces_are_closed_read_only_and_never_expose_secret_names() -> (
    None
):
    core = _core(flags=_flags(dashboard_projection=True))
    assert dataclasses.fields(core.dashboard_read("status")) == dataclasses.fields(
        runtime.RuntimeStatusV4
    )
    assert core.dashboard_read("events") == ()
    for surface in (
        "mutate",
        "approve",
        "grant",
        "dispatch",
        "kill",
        "apiKey",
        "token",
        "secret",
    ):
        with pytest.raises(runtime.Phase5RuntimeV4ContractError):
            core.dashboard_read(surface)


def test_terminal_boundary_is_blocking_single_flight_and_clears_authority() -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def terminator(reason: str) -> None:
        calls.append(reason)
        entered.set()
        release.wait()

    core = _core(components=runtime.RuntimeComponentsV4(grant_terminator=terminator))
    action = _action()
    decision = core.evaluate(action)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(core.kill)
        entered.wait()
        second = pool.submit(core.revoke)
        assert not second.done()
        release.set()
        results = (first.result(), second.result())
    assert calls == ["kill"] and all(
        result.state is runtime.RuntimeStateV4.TERMINATED for result in results
    )
    assert not core.consume_decision(decision, action)


def test_hot_path_performance_p95_under_25ms_and_memory_is_bounded() -> None:
    core = _core()
    action = _action()
    samples: list[float] = []
    for _ in range(2_000):
        start = time.perf_counter()
        decision = core.evaluate(action)
        core.consume_decision(decision, action)
        samples.append((time.perf_counter() - start) * 1_000)
    p95 = statistics.quantiles(samples, n=100)[94]
    assert p95 < 25
    assert len(core.events()) <= runtime.MAX_PAGE_SIZE
    assert len(core._events) <= runtime.MAX_EVENTS  # noqa: SLF001
    assert len(core._decision_seals) <= runtime.MAX_DECISION_SEALS  # noqa: SLF001


def test_two_hundred_noop_reconfigurations_after_failure_are_observationally_pure() -> (
    None
):
    def failing(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        raise RuntimeError("failure")

    components = runtime.RuntimeComponentsV4(nexus_projector=failing)
    flags = _flags(nexus_projection=True, dashboard_projection=True)
    binding = _binding()
    core = _core(flags=flags, components=components)
    core.refresh_capabilities()
    before = (
        core.status(),
        core.events(),
        core.capabilities(),
        core.inbox(),
        core._config_generation,
        dict(core._component_generation),  # noqa: SLF001
    )
    for _ in range(200):
        assert core.configure_flags(flags).component_failures == ("nexus",)
        assert core.rebind(binding).component_failures == ("nexus",)
        assert core.replace_components(components).component_failures == ("nexus",)
    after = (
        core.status(),
        core.events(),
        core.capabilities(),
        core.inbox(),
        core._config_generation,
        dict(core._component_generation),  # noqa: SLF001
    )
    assert after == before


def test_inflight_failure_survives_noop_and_unrelated_real_reconfiguration() -> None:
    entered = threading.Event()
    release = threading.Event()
    should_fail = False

    def projector(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        if should_fail:
            entered.set()
            release.wait()
            raise RuntimeError("late failure")
        return runtime.ProjectionBatchV4((_cap(),))

    components = runtime.RuntimeComponentsV4(nexus_projector=projector)
    flags = _flags(nexus_projection=True)
    core = _core(flags=flags, components=components)
    assert core.recover_component("nexus").component_failures == ()
    should_fail = True
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(core.refresh_capabilities)
        entered.wait()
        for _ in range(200):
            core.configure_flags(flags)
            core.rebind(_binding())
            core.replace_components(components)
        core.configure_flags(dataclasses.replace(flags, dashboard_projection=True))
        release.set()
        pending.result()
    assert core.status().component_failures == ("nexus",)
    assert core.status().state is runtime.RuntimeStateV4.DEGRADED


def test_old_generation_failure_cannot_poison_recovered_replacement() -> None:
    entered = threading.Event()
    release = threading.Event()

    def old(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        entered.set()
        release.wait()
        raise RuntimeError("old generation")

    def current(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        return runtime.ProjectionBatchV4((_cap("current"),))

    core = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV4(nexus_projector=old),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        stale = pool.submit(core.refresh_capabilities)
        entered.wait()
        core.replace_components(runtime.RuntimeComponentsV4(nexus_projector=current))
        assert core.recover_component("nexus").component_failures == ()
        release.set()
        stale.result()
    assert core.status().component_failures == ()
    assert core.capabilities().items[0].item_id == "current"


def test_enabling_missing_or_new_components_is_degraded_until_explicit_probe() -> None:
    base = _flags(nexus_projection=False, approval_inbox=False)
    core = _core(flags=base)
    enabled = dataclasses.replace(base, nexus_projection=True, approval_inbox=True)
    status = core.configure_flags(enabled)
    assert status.state is runtime.RuntimeStateV4.DEGRADED
    assert status.component_failures == ("inbox", "nexus")
    assert core.evaluate(_action()).disposition is runtime.RuntimeDispositionV4.EXPLICIT
    assert core.refresh_capabilities().total == 0
    assert core.refresh_inbox().total == 0

    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV4:
            return runtime.ProjectionBatchV4((_item(),), source_cursor=None)

    components = runtime.RuntimeComponentsV4(
        nexus_projector=lambda _binding: runtime.ProjectionBatchV4((_cap(),)),
        inbox_factory=lambda _binding: Reader(),
    )
    core.replace_components(components)
    core.refresh_capabilities()
    core.refresh_inbox()
    assert core.status().component_failures == ("inbox", "nexus")
    assert core.recover_component("nexus").component_failures == ("inbox",)
    assert core.evaluate(_action()).disposition is runtime.RuntimeDispositionV4.EXPLICIT
    assert core.recover_component("inbox").component_failures == ()
    assert core.status().state is runtime.RuntimeStateV4.READY


def test_recovery_clears_only_after_successful_probe_of_current_generation() -> None:
    old_entered = threading.Event()
    release_old = threading.Event()

    def old(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        old_entered.set()
        release_old.wait()
        return runtime.ProjectionBatchV4((_cap("old"),))

    attempts = 0

    def current(_binding: runtime.RuntimeBindingV4) -> runtime.ProjectionBatchV4:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("probe failed")
        return runtime.ProjectionBatchV4((_cap("current"),))

    core = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV4(nexus_projector=old),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        stale_recovery = pool.submit(core.recover_component, "nexus")
        old_entered.wait()
        core.replace_components(runtime.RuntimeComponentsV4(nexus_projector=current))
        release_old.set()
        stale_recovery.result()
    assert core.status().component_failures == ("nexus",)
    assert core.recover_component("nexus").component_failures == ("nexus",)
    assert core.recover_component("nexus").component_failures == ()
    assert core.capabilities().items[0].item_id == "current"


_SECRET_CANARIES = (
    "sk-proj-AbCdEf0123456789AbCdEf0123456789",
    "ghp_AbCdEf0123456789AbCdEf0123456789AbCd",
    "github_pat_AbCdEf0123456789_AbCdEf0123456789",
    "AKIAABCDEFGHIJKLMNOP",
    "AIzaAbCdEf0123456789_AbCdEf0123456789",
    "Bearer AbCdEf0123456789.AbCdEf0123456789",
    "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
    "eyJAbCdEf0123456789.AbCdEf0123456789.AbCdEf0123456789",
    "-----BEGIN RSA PRIVATE KEY-----",
    "access_token=AbCdEf0123456789AbCdEf0123456789",
    "refresh-token:AbCdEf0123456789AbCdEf0123456789",
    "Ab9_Qx7Lm2Np8Vr4Ts6Wy0Za5Bc3De1Fg",
)


@pytest.mark.parametrize("canary", _SECRET_CANARIES)
def test_value_dlp_redacts_secret_families_from_every_projection_surface(
    canary: str,
) -> None:
    class Reader:
        def read_page(self, **_kwargs: object) -> runtime.ProjectionBatchV4:
            return runtime.ProjectionBatchV4(
                (_item(summary=canary),), source_cursor=None
            )

    core = _core(
        flags=_flags(
            nexus_projection=True, approval_inbox=True, dashboard_projection=True
        ),
        components=runtime.RuntimeComponentsV4(
            nexus_projector=lambda _binding: runtime.ProjectionBatchV4(
                (_cap(display_name=canary, provider=canary, limitation=canary),)
            ),
            inbox_factory=lambda _binding: Reader(),
        ),
    )
    core.recover_component("nexus")
    core.recover_component("inbox")
    with core._lock:  # noqa: SLF001
        core._event_locked("dlp_probe", "observed", reason=canary)  # noqa: SLF001
    rendered = repr(
        (
            core.dashboard_read("status"),
            core.dashboard_read("capabilities"),
            core.dashboard_read("inbox"),
            core.dashboard_read("events"),
        )
    )
    assert canary not in rendered
    assert "[REDACTED]" in rendered


@pytest.mark.parametrize("canary", _SECRET_CANARIES)
def test_value_dlp_rejects_secret_canaries_from_action_strings(canary: str) -> None:
    with pytest.raises(runtime.Phase5RuntimeV4ContractError):
        _action(capability=canary)


def test_live_modules_do_not_import_v4_candidate() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/permission_broker.py",
    ):
        assert "phase5_runtime_v4" not in (root / relative).read_text(encoding="utf-8")
