from __future__ import annotations

import dataclasses
import threading
import time

import pytest

import core.phase5_runtime_v7 as runtime


def _binding(**changes: object) -> runtime.RuntimeBindingV7:
    values: dict[str, object] = {
        "trace_id": "trace-one",
        "session_id": "session-one",
        "workspace_id": "workspace-one",
        "account_id": "account-one",
        "profile_id": "profile-one",
    }
    values.update(changes)
    return runtime.RuntimeBindingV7(**values)  # type: ignore[arg-type]


def _flags(**changes: object) -> runtime.RuntimeFlagsV7:
    values: dict[str, object] = {
        "runtime": True,
        "grant_shadow": False,
        "approval_inbox": False,
        "low_risk": True,
        "nexus_projection": False,
        "local_catalog_read": True,
        "dashboard_projection": True,
    }
    values.update(changes)
    return runtime.RuntimeFlagsV7(**values)  # type: ignore[arg-type]


def _action(
    binding: runtime.RuntimeBindingV7 | None = None, **changes: object
) -> runtime.ActionRequestV7:
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
    return runtime.ActionRequestV7(**values)  # type: ignore[arg-type]


def _cap(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "capability_id": "cap-one",
        "display_name": "Local Catalog",
        "provider": "Onyx local",
        "version": "1.0",
        "status": "available",
        "operations": ["catalog_read"],
        "limitation": None,
    }
    value.update(changes)
    return value


def _item(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "item_id": "item-one",
        "request_ref": "request-one",
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
    flags: runtime.RuntimeFlagsV7 | None = None,
    components: runtime.RuntimeComponentsV7 | None = None,
) -> runtime.Phase5RuntimeV7:
    return runtime.Phase5RuntimeV7(
        binding=_binding(), flags=flags or _flags(), components=components
    )


class _Inbox:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    def read_page(
        self,
        *,
        binding: runtime.RuntimeBindingV7,
        page_size: int,
        cursor: str | None,
    ) -> runtime.ProjectionBatchV7:
        del binding, page_size
        return runtime.ProjectionBatchV7(
            (self.row,), replace=cursor is None, source_cursor=cursor
        )


def test_v7_flags_are_independent_and_default_off() -> None:
    assert runtime.RuntimeFlagsV7.from_environ({}) == runtime.RuntimeFlagsV7()
    names = [
        runtime.PHASE5_RUNTIME_FLAG,
        runtime.PHASE5_GRANT_SHADOW_FLAG,
        runtime.PHASE5_APPROVAL_INBOX_FLAG,
        runtime.PHASE5_LOW_RISK_FLAG,
        runtime.PHASE5_NEXUS_PROJECTION_FLAG,
        runtime.PHASE5_LOCAL_CATALOG_READ_FLAG,
        runtime.PHASE5_DASHBOARD_PROJECTION_FLAG,
    ]
    for selected in names:
        environment = {name: "false" for name in names}
        environment[selected] = "true"
        assert (
            sum(
                dict(
                    runtime.RuntimeFlagsV7.from_environ(environment).payload()
                ).values()
            )
            == 1
        )


def test_v7_default_off_is_observationally_pure() -> None:
    touched: list[str] = []
    core = _core(
        flags=_flags(runtime=False, grant_shadow=True, nexus_projection=True),
        components=runtime.RuntimeComponentsV7(
            grant_evaluator=lambda value: touched.append(value),
            nexus_projector=lambda binding: (_ for _ in ()).throw(
                AssertionError(binding)
            ),
        ),
    )
    before = core.status()
    marker = object()
    assert core.legacy_or_decision(_action(), lambda: marker) is marker
    assert core.status() == before
    assert core.events() == ()
    assert touched == []


def test_allow_decision_is_exact_request_single_use_commit() -> None:
    core = _core()
    request = _action()
    decision = core.evaluate(request)
    assert decision.disposition is runtime.RuntimeDispositionV7.ALLOW_LOCAL_CATALOG_READ
    assert core.decision_is_current(decision, request)
    assert not core.decision_is_current(
        decision, dataclasses.replace(request, invocation_ref="opaque-other")
    )
    assert core.consume_decision(decision, request)
    assert not core.consume_decision(decision, request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("capability", "local.files"),
        ("operation", "catalog_write"),
        ("provider_free", False),
        ("read_only", False),
        ("effect", "write"),
        ("egress", "network"),
        ("metadata_allowlisted", False),
        ("cost_micro", 1),
        ("risk", "medium"),
        ("reversible", False),
        ("uses_credentials", True),
        ("privileged", True),
        ("irreversible", True),
    ],
)
def test_only_exact_local_catalog_read_is_allowed(field: str, value: object) -> None:
    assert (
        _core().evaluate(_action(**{field: value})).disposition
        is runtime.RuntimeDispositionV7.EXPLICIT
    )


@pytest.mark.parametrize(
    "unsafe",
    [
        "token：sk-proj-ABCDEFGHIJKLMNOP",
        "api＿key = ABCDEFGHIJKLMNOP",
        "a.p.i＿k-e-y：ABCDEFGHIJKLMNOP",
        "api key：ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰ",
        "secret̲ = ABCDEFGHIJKLMNOP",
        "s.e.c.r.e.t：ABCDEFGHIJKLMNOP",
        "t o k e n：ABCDEFGHIJKLMNOP",
        "auth—code = ABCDEFGHIJKLMNOP",
    ],
)
def test_unicode_dlp_rejects_nfkc_combining_and_separator_confusables(
    unsafe: str,
) -> None:
    with pytest.raises(runtime.Phase5RuntimeV7ContractError):
        runtime.RuntimeBindingV7(
            trace_id="trace-one",
            session_id="session-one",
            workspace_id="workspace-one",
            account_id="account-one",
            profile_id=unsafe,
        )


@pytest.mark.parametrize(
    "unsafe",
    [
        "trace​-one",
        "trace⁠-one",
        "trace﻿-one",
        "trace‮-one",
        "trace‭-one",
        "trace‬-one",
        "trace⁦-one",
        "trace⁧-one",
        "trace⁨-one",
        "trace⁩-one",
        "trace\x00-one",
    ],
)
def test_ids_reject_controls_invisibles_and_bidi(unsafe: str) -> None:
    with pytest.raises(runtime.Phase5RuntimeV7ContractError):
        _binding(trace_id=unsafe)


def test_ids_validate_after_nfkc_and_normal_language_is_not_base32_secret() -> None:
    assert _binding(trace_id="ｔｒａｃｅ-one").trace_id == "trace-one"
    for value in (
        "InternationalizationArchitecture",
        "InternationalizationArchitectureController",
        "CustomerCommunicationConfiguration",
    ):
        assert not runtime._contains_sensitive_value(value)  # noqa: SLF001
        core = _core(
            flags=_flags(nexus_projection=True),
            components=runtime.RuntimeComponentsV7(
                nexus_projector=lambda binding, value=value: runtime.ProjectionBatchV7(
                    (_cap(display_name=value),)
                )
            ),
        )
        core.recover_component("nexus")
        assert core.capabilities().items[0].payload()["display_name"] == value


def test_dlp_covers_binding_capability_inbox_event_and_advisory_surfaces() -> None:
    secret = "api＿key：ABCDEFGHIJKLMNOP"
    with pytest.raises(runtime.Phase5RuntimeV7ContractError):
        _binding(profile_id=secret)
    nexus = _core(
        flags=_flags(nexus_projection=True),
        components=runtime.RuntimeComponentsV7(
            nexus_projector=lambda binding: runtime.ProjectionBatchV7(
                (_cap(limitation=secret),)
            )
        ),
    )
    assert nexus.recover_component("nexus").state is runtime.RuntimeStateV7.READY
    assert nexus.capabilities().items[0].payload()["limitation"] == "[REDACTED]"
    inbox = _core(
        flags=_flags(approval_inbox=True),
        components=runtime.RuntimeComponentsV7(
            inbox_factory=lambda binding: _Inbox(_item(summary=secret))
        ),
    )
    assert inbox.recover_component("inbox").state is runtime.RuntimeStateV7.READY
    assert inbox.inbox().items[0].payload()["summary"] == "[REDACTED]"
    grant = _core(
        flags=_flags(grant_shadow=True),
        components=runtime.RuntimeComponentsV7(
            grant_evaluator=lambda reference: {"reason": secret}
        ),
    )
    assert grant.recover_component("grant_shadow").state is runtime.RuntimeStateV7.READY
    event_core = _core()
    event_core._event_locked("kind", "outcome", reason=secret)  # noqa: SLF001
    assert event_core.events()[0].reason == "[REDACTED]"


def test_projection_reads_are_closed_bounded_and_context_bound() -> None:
    core = _core(
        flags=_flags(nexus_projection=True, approval_inbox=True),
        components=runtime.RuntimeComponentsV7(
            nexus_projector=lambda binding: runtime.ProjectionBatchV7((_cap(),)),
            inbox_factory=lambda binding: _Inbox(_item()),
        ),
    )
    assert core.recover_component("nexus").state is runtime.RuntimeStateV7.DEGRADED
    assert core.recover_component("inbox").state is runtime.RuntimeStateV7.READY
    cap = core.capabilities().items[0].payload()
    item = core.inbox().items[0].payload()
    for payload in (cap, item):
        assert payload["trace_id"] == "trace-one"
        assert payload["workspace_id"] == "workspace-one"
    assert core.dashboard_read("status") == core.status()
    with pytest.raises(runtime.Phase5RuntimeV7ContractError):
        core.dashboard_read("approve")


def _all_termination_components() -> runtime.RuntimeComponentsV7:
    return runtime.RuntimeComponentsV7(
        termination_actions=("grant", "nexus", "inbox", "rollback")
    )


def test_termination_is_host_owned_bounded_and_never_invokes_callbacks() -> None:
    before_threads = {thread.ident for thread in threading.enumerate()}
    core = _core(components=_all_termination_components())
    status = core.kill()
    assert status.state is runtime.RuntimeStateV7.TERMINATION_PENDING
    plan = core.termination_plan()
    assert isinstance(plan, runtime.TerminationPlanV7)
    assert len(plan.actions) == runtime.MAX_TERMINATION_ACTIONS == 4
    assert tuple(action.action for action in plan.actions) == (
        "grant",
        "nexus",
        "inbox",
        "rollback",
    )
    assert core.pending_termination_actions() == plan.actions
    assert {thread.ident for thread in threading.enumerate()} == before_threads


def test_no_action_termination_is_immediate_and_plan_is_stable() -> None:
    core = _core()
    first = core.shutdown()
    plan = core.termination_plan()
    assert first.state is runtime.RuntimeStateV7.TERMINATED
    assert isinstance(plan, runtime.TerminationPlanV7) and plan.actions == ()
    assert core.revoke() == first
    assert core.termination_plan() is plan


def test_ack_tokens_are_bound_single_use_and_failures_are_fail_closed() -> None:
    core = _core(components=_all_termination_components())
    assert core.revoke().state is runtime.RuntimeStateV7.TERMINATION_PENDING
    actions = core.pending_termination_actions()
    forged = actions[0].token[:-1] + ("0" if actions[0].token[-1] != "0" else "1")
    with pytest.raises(runtime.Phase5RuntimeV7ContractError):
        core.ack_termination_action(forged, success=True)
    for item in actions[:-1]:
        assert (
            core.ack_termination_action(item.token, success=True).state
            is runtime.RuntimeStateV7.TERMINATION_PENDING
        )
    last = actions[-1]
    final = core.ack_termination_action(
        last.token, success=False, error="Host rollback failed safely"
    )
    assert final.state is runtime.RuntimeStateV7.TERMINATED
    assert final.termination_failures == ("rollback",)
    assert core.pending_termination_actions() == ()
    with pytest.raises(runtime.Phase5RuntimeV7ContractError):
        core.ack_termination_action(last.token, success=True)


def test_foreign_runtime_token_is_rejected() -> None:
    one = _core(components=_all_termination_components())
    two = _core(components=_all_termination_components())
    one.kill()
    two.kill()
    token = one.pending_termination_actions()[0].token
    with pytest.raises(runtime.Phase5RuntimeV7ContractError):
        two.ack_termination_action(token, success=True)


def test_wait_timeout_never_claims_external_cleanup_or_reopens_runtime() -> None:
    core = _core(components=_all_termination_components())
    core.kill()
    timed = core.await_termination(0.001)
    assert timed.state is runtime.RuntimeStateV7.TERMINATION_PENDING
    assert set(timed.termination_timeouts) == {"grant", "nexus", "inbox", "rollback"}
    assert core.evaluate(_action()).reason == "runtime_terminated"
    with pytest.raises(runtime.Phase5RuntimeV7Error):
        core.rebind(_binding(trace_id="trace-two"))


def test_repeated_and_concurrent_termination_get_same_plan_without_blocking() -> None:
    core = _core(components=_all_termination_components())
    statuses: list[runtime.RuntimeStatusV7] = []
    threads = [
        threading.Thread(target=lambda: statuses.append(core.kill())) for _ in range(64)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(1.0)
    assert len(statuses) == 64
    assert {status.state for status in statuses} == {
        runtime.RuntimeStateV7.TERMINATION_PENDING
    }
    plan = core.termination_plan()
    assert plan is not None
    assert core.termination_plan() is plan
    assert len({action.token for action in plan.actions}) == 4


def test_132_runtimes_create_no_threads_or_queues_and_do_not_starve() -> None:
    before = {thread.ident for thread in threading.enumerate()}
    cores = [_core(components=_all_termination_components()) for _ in range(132)]
    started = time.perf_counter()
    for core in cores:
        assert core.kill().state is runtime.RuntimeStateV7.TERMINATION_PENDING
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0
    assert {thread.ident for thread in threading.enumerate()} == before
    for core in cores:
        for item in core.pending_termination_actions():
            core.ack_termination_action(item.token, success=True)
        assert core.status().state is runtime.RuntimeStateV7.TERMINATED


def test_stale_allow_cannot_commit_after_termination_begins() -> None:
    core = _core(components=_all_termination_components())
    request = _action()
    decision = core.evaluate(request)
    assert decision.disposition is runtime.RuntimeDispositionV7.ALLOW_LOCAL_CATALOG_READ
    core.kill()
    assert not core.consume_decision(decision, request)


def test_late_grant_failure_cannot_overwrite_newer_recovery() -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def evaluator(reference: str) -> dict[str, str]:
        nonlocal calls
        with calls_lock:
            calls += 1
            number = calls
        if number == 2:
            entered.set()
            assert release.wait(2.0)
            raise RuntimeError("old failure")
        return {"outcome": "observed"}

    core = _core(
        flags=_flags(grant_shadow=True),
        components=runtime.RuntimeComponentsV7(grant_evaluator=evaluator),
    )
    assert core.recover_component("grant_shadow").state is runtime.RuntimeStateV7.READY
    result: list[runtime.RuntimeDecisionV7] = []
    thread = threading.Thread(target=lambda: result.append(core.evaluate(_action())))
    thread.start()
    assert entered.wait(1.0)
    assert core.recover_component("grant_shadow").state is runtime.RuntimeStateV7.READY
    release.set()
    thread.join(1.0)
    assert result[0].reason == "grant_shadow_failure"
    assert core.status().state is runtime.RuntimeStateV7.READY
    assert core.status().component_failures == ()


def test_termination_ack_error_is_dlp_screened() -> None:
    core = _core(components=_all_termination_components())
    core.kill()
    token = core.pending_termination_actions()[0].token
    core.ack_termination_action(
        token, success=False, error="api＿key：ABCDEFGHIJKLMNOP"
    )
    assert len(core.pending_termination_actions()) == 3
    event = [
        item for item in core.events() if item.outcome == "termination_action_failed"
    ][0]
    assert event.reason == "[REDACTED]"
