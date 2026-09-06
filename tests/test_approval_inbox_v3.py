from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from core import approval_inbox_v3 as inbox
from scripts import verify_phase5_approval_inbox_v3 as evidence


ON = {inbox.APPROVAL_INBOX_FLAG: "true"}
OFF = {inbox.APPROVAL_INBOX_FLAG: "false"}


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def host_item(
    item_id: str = "approval-one",
    *,
    workspace_id: str = "cyryx-main",
    mission_id: str | None = "mission-one",
    risk: str = "low",
    always_explicit: bool = False,
    batch_eligible: bool = True,
    created_at_ms: int = 100,
    expires_at_ms: int = 10_000,
) -> inbox.HostInboxItem:
    return inbox.HostInboxItem(
        item_id,
        workspace_id,
        "Cyryx Labs",
        "Operations account",
        mission_id,
        "Daily operations",
        "Prepare the reviewed daily work item",
        "Create a reversible provider draft",
        "Named provider draft folder",
        digest(f"target-{item_id}"),
        "Draft with reviewed title and summary; no raw body",
        digest(f"payload-{item_id}"),
        "internal",
        "named-account",
        "Creates one non-live draft for later review",
        "reversible",
        "The exact request key prevents duplicate drafts",
        digest(f"idempotency-{item_id}"),
        "Read back draft metadata and compare its digest",
        "Delete the non-live draft after a separate exact approval",
        25_000,
        "USD",
        risk,
        created_at_ms,
        expires_at_ms,
        always_explicit,
        batch_eligible,
    )


def host_snapshot(
    items: object = None,
    *,
    revision: str = "revision-one",
    epoch: int = 1,
    captured_at_ms: int = 200,
    valid_until_ms: int = 900,
    audit_healthy: bool = True,
    session_active: bool = True,
    kill_switch: bool = False,
) -> inbox.HostInboxSnapshot:
    if items is None:
        items = (host_item(),)
    return inbox.HostInboxSnapshot(
        inbox.INBOX_SCHEMA_VERSION,
        revision,
        epoch,
        "owner-main",
        "session-main",
        captured_at_ms,
        valid_until_ms,
        audit_healthy,
        session_active,
        kill_switch,
        items,
    )


def projection(callback, clock: inbox.DeterministicInboxClock | None = None):
    source = inbox.HostInboxSource(callback, "owner-main", "session-main")
    clock = clock or inbox.DeterministicInboxClock(1_000)
    return inbox.ApprovalInboxProjection(source, clock), source, clock


def test_strict_default_off_has_no_clock_or_source_callback() -> None:
    calls = 0

    def source():
        nonlocal calls
        calls += 1
        return host_snapshot()

    service, _source, clock = projection(source)
    clock.set_for_test(0)  # would permanently fail if read
    for raw in ("", "yes", "on", "enabled", "2", " truex ", True):
        page = service.open_page(environ={inbox.APPROVAL_INBOX_FLAG: raw})  # type: ignore[dict-item]
        assert page.status == "disabled"
        assert page.items == ()
        assert page.page_digest is None
        assert page.authority_granted is False
        assert page.execution_available is False
    assert calls == 0


def test_explicit_host_composition_is_pinned_but_not_claimed_as_same_process_secrecy() -> None:
    source = inbox.HostInboxSource(lambda: host_snapshot(), "owner-main", "session-main")
    clock = inbox.DeterministicInboxClock(1_000)
    service = inbox.ApprovalInboxProjection(source, clock)
    with pytest.raises(AttributeError, match="pinned"):
        service._source = inbox.HostInboxSource(lambda: host_snapshot(), "owner-main", "session-main")
    with pytest.raises(AttributeError, match="pinned"):
        service._clock = inbox.DeterministicInboxClock(1)
    with pytest.raises(AttributeError, match="immutable"):
        source._callback = lambda: host_snapshot()
    separate = inbox.ApprovalInboxProjection(
        inbox.HostInboxSource(lambda: host_snapshot(), "owner-main", "session-main"),
        inbox.DeterministicInboxClock(1_000),
    )
    assert separate.open_page(environ=ON).authority_granted is False
    doc = inspect.getdoc(inbox)
    assert "same-process callers can build a separate inert projection" in doc
    assert "creates no runtime wiring" in doc


def test_read_apis_accept_no_source_items_or_authority_fields() -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    assert set(inspect.signature(service.open_page).parameters) == {
        "query",
        "page_size",
        "environ",
    }
    assert set(inspect.signature(service.continue_page).parameters) == {"cursor", "environ"}
    assert set(inspect.signature(service.preview_calm_batch).parameters) == {
        "snapshot_token",
        "selected_item_ids",
        "environ",
    }


def test_exact_source_output_types_only_no_subclass_or_custom_mapping() -> None:
    class SnapshotSubclass(inbox.HostInboxSnapshot):
        pass

    values = host_snapshot()
    subclass = SnapshotSubclass(*[getattr(values, field) for field in values.__dataclass_fields__])
    for result in ({"items": ()}, subclass, object()):
        service, _source, _clock = projection(lambda result=result: result)
        with pytest.raises(inbox.ApprovalInboxV3ContractError, match="concrete type"):
            service.open_page(environ=ON)


def test_bounds_are_checked_before_any_item_traversal_or_copy_hook() -> None:
    hooks = {"iter": 0, "deepcopy": 0, "attribute": 0}

    class Hook:
        def __iter__(self):
            hooks["iter"] += 1
            raise AssertionError("iteration hook executed")

        def __deepcopy__(self, _memo):
            hooks["deepcopy"] += 1
            raise AssertionError("deepcopy hook executed")

        def __getattribute__(self, name):
            if name not in {"__class__", "__dict__"}:
                hooks["attribute"] += 1
            return object.__getattribute__(self, name)

    oversized = tuple(Hook() for _ in range(inbox.MAX_ITEMS + 1))
    service, _source, _clock = projection(lambda: host_snapshot(oversized))
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="exceeds"):
        service.open_page(environ=ON)
    assert hooks == {"iter": 0, "deepcopy": 0, "attribute": 0}

    custom = Hook()
    service, _source, _clock = projection(lambda: host_snapshot(custom))
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="exact tuple"):
        service.open_page(environ=ON)
    assert hooks == {"iter": 0, "deepcopy": 0, "attribute": 0}

    service, _source, _clock = projection(lambda: host_snapshot((Hook(),)))
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="concrete type"):
        service.open_page(environ=ON)
    assert hooks == {"iter": 0, "deepcopy": 0, "attribute": 0}


def test_raw_callback_exception_is_not_chained_or_recoverable() -> None:
    canary = "sk-proj-SUPERSECRETCANARY1234567890"

    def source():
        raise RuntimeError(canary, {"payload": canary})

    service, _source, _clock = projection(source)
    with pytest.raises(inbox.ApprovalInboxV3Unavailable) as caught:
        service.open_page(environ=ON)
    error = caught.value
    assert error.args == ("host-source-failed",)
    assert error.__cause__ is None
    assert error.__context__ is None
    combined = repr(error) + repr(error.args) + repr(error.__cause__) + repr(error.__context__)
    assert canary not in combined


@pytest.mark.parametrize(
    "field",
    [
        "workspace_display",
        "account_display",
        "mission_display",
        "reason",
        "action",
        "target_display",
        "payload_summary",
        "effect_summary",
        "idempotency_summary",
        "verification_plan",
        "rollback_plan",
    ],
)
def test_every_recoverable_display_field_rejects_secrets(field: str) -> None:
    malicious = replace(
        host_item(), **{field: "api_key=sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"}
    )
    service, _source, _clock = projection(lambda: host_snapshot((malicious,)))
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="secret-like"):
        service.open_page(environ=ON)


def test_complete_review_fields_are_immutable_non_authority_and_digest_internal() -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    page = service.open_page(environ=ON)
    item = page.items[0]
    expected = {
        "workspace_id",
        "workspace_display",
        "account_display",
        "mission_id",
        "mission_display",
        "reason",
        "action",
        "target_display",
        "target_digest",
        "payload_summary",
        "payload_digest",
        "data_class",
        "egress",
        "effect_summary",
        "reversibility",
        "idempotency_summary",
        "idempotency_key",
        "verification_plan",
        "rollback_plan",
        "cost_micro",
        "currency",
        "risk",
        "created_at_ms",
        "expires_at_ms",
        "always_explicit",
        "batch_eligible",
        "item_digest",
    }
    assert expected <= set(item.__dataclass_fields__)
    assert item.authority_granted is False
    assert not hasattr(item, "raw_target")
    assert not hasattr(item, "raw_payload")
    with pytest.raises(TypeError, match="created by the projection"):
        inbox.ApprovalDisplayItem(object(), host_item())
    with pytest.raises(Exception):
        item.reason = "changed"  # type: ignore[misc]


def test_source_timestamps_are_metadata_not_token_validity() -> None:
    old = host_snapshot(
        (host_item("approval-one"), host_item("approval-two")),
        captured_at_ms=1,
        valid_until_ms=2,
    )
    service, _source, clock = projection(lambda: old)
    page = service.open_page(page_size=1, environ=ON)
    assert page.items[0].created_at_ms == 100
    clock.advance(inbox.MAX_SNAPSHOT_AGE_MS - 1)
    assert service.continue_page(page.next_cursor, environ=ON).status == "ready"


def test_projection_owned_deadline_expires_without_source_callback_and_never_resurrects() -> None:
    calls = 0

    def source():
        nonlocal calls
        calls += 1
        return host_snapshot((host_item("approval-one"), host_item("approval-two")))

    service, _source, clock = projection(source)
    page = service.open_page(page_size=1, environ=ON)
    assert calls == 1 and page.next_cursor
    clock.advance(inbox.MAX_SNAPSHOT_AGE_MS)
    with pytest.raises(inbox.ApprovalInboxV3Stale, match="deadline"):
        service.continue_page(page.next_cursor, environ=ON)
    assert calls == 1
    fresh = service.open_page(page_size=1, environ=ON)
    assert fresh.snapshot_digest != page.snapshot_digest
    with pytest.raises(inbox.ApprovalInboxV3Stale):
        service.continue_page(page.next_cursor, environ=ON)


def test_monotonic_clock_rollback_latches_and_cannot_resurrect() -> None:
    service, _source, clock = projection(
        lambda: host_snapshot((host_item("approval-one"), host_item("approval-two")))
    )
    page = service.open_page(page_size=1, environ=ON)
    clock.advance(10)
    service.continue_page(page.next_cursor, environ=ON)
    clock.set_for_test(1_005)
    with pytest.raises(inbox.ApprovalInboxV3Unavailable, match="rollback"):
        service.continue_page(page.next_cursor, environ=ON)
    clock.set_for_test(2_000)
    with pytest.raises(inbox.ApprovalInboxV3Unavailable, match="rollback"):
        service.continue_page(page.next_cursor, environ=ON)


def test_same_epoch_equivocation_latches_and_restore_never_resurrects() -> None:
    original = host_snapshot((host_item("approval-one"), host_item("approval-two")))
    state = {"snapshot": original}
    service, _source, _clock = projection(lambda: state["snapshot"])
    page = service.open_page(page_size=1, environ=ON)
    state["snapshot"] = host_snapshot((host_item("approval-two"),))
    with pytest.raises(inbox.ApprovalInboxV3Stale, match="without-epoch"):
        service.continue_page(page.next_cursor, environ=ON)
    state["snapshot"] = original
    for operation in (
        lambda: service.open_page(environ=ON),
        lambda: service.continue_page(page.next_cursor, environ=ON),
        lambda: service.preview_calm_batch(
            page.snapshot_token, ("approval-one",), environ=ON
        ),
    ):
        with pytest.raises(inbox.ApprovalInboxV3Unavailable, match="integrity-failed"):
            operation()
    restarted, _source, _clock = projection(lambda: original)
    assert restarted.open_page(environ=ON).status == "ready"


def test_epoch_rollback_latches_and_restore_never_resurrects() -> None:
    current = host_snapshot(revision="revision-two", epoch=2)
    state = {"snapshot": current}
    service, _source, _clock = projection(lambda: state["snapshot"])
    page = service.open_page(environ=ON)
    state["snapshot"] = host_snapshot(revision="revision-one", epoch=1)
    with pytest.raises(inbox.ApprovalInboxV3Stale, match="rollback"):
        service.open_page(environ=ON)
    state["snapshot"] = current
    with pytest.raises(inbox.ApprovalInboxV3Unavailable, match="integrity-failed"):
        service.open_page(environ=ON)
    with pytest.raises(inbox.ApprovalInboxV3Unavailable, match="integrity-failed"):
        service.preview_calm_batch(
            page.snapshot_token, ("approval-one",), environ=ON
        )


def test_integrity_latch_is_nonresurrecting_across_concurrent_callers() -> None:
    original = host_snapshot((host_item("approval-one"), host_item("approval-two")))
    state = {"snapshot": original}
    service, _source, _clock = projection(lambda: state["snapshot"])
    page = service.open_page(page_size=1, environ=ON)
    latch_observed = threading.Event()
    results: list[str] = []

    def equivocate() -> None:
        state["snapshot"] = host_snapshot((host_item("approval-three"),))
        try:
            service.continue_page(page.next_cursor, environ=ON)
        except inbox.ApprovalInboxV3Stale:
            results.append("latched")
        finally:
            latch_observed.set()

    def restore() -> None:
        assert latch_observed.wait(timeout=2)
        state["snapshot"] = original
        try:
            service.continue_page(page.next_cursor, environ=ON)
        except inbox.ApprovalInboxV3Unavailable:
            results.append("restore-blocked")

    threads = [threading.Thread(target=equivocate), threading.Thread(target=restore)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()
    assert sorted(results) == ["latched", "restore-blocked"]


def test_query_sort_page_size_and_allowed_ids_are_bound_into_view_and_token() -> None:
    values = (
        host_item("approval-cyryx", workspace_id="cyryx-main"),
        host_item("approval-client", workspace_id="client-one"),
        host_item("approval-other", workspace_id="cyryx-main"),
    )
    service, _source, _clock = projection(lambda: host_snapshot(values))
    query = inbox.InboxQuery(workspace_id="cyryx-main", sort="item-id-asc")
    page = service.open_page(query=query, page_size=1, environ=ON)
    assert page.query == query
    assert page.page_size == 1
    assert page.total_items == 2
    assert [item.item_id for item in page.items] == ["approval-cyryx"]
    view = service._views[page.view_digest]
    assert view.allowed_item_ids == ("approval-cyryx", "approval-other")
    assert page.page_digest == inbox._sha(
        {
            "contract": "ApprovalInboxPage.v3",
            "snapshot_digest": page.snapshot_digest,
            "view_digest": page.view_digest,
            "query": query.payload(),
            "page_size": 1,
            "offset": 0,
            "total_items": 2,
            "item_digests": [page.items[0].item_digest],
            "has_next": True,
            "snapshot_token_digest": inbox._token_digest(page.snapshot_token),
            "next_cursor_digest": inbox._token_digest(page.next_cursor),
        }
    )


def test_batch_cannot_select_hidden_workspace_or_filtered_item() -> None:
    values = (
        host_item("approval-visible", workspace_id="cyryx-main", risk="low"),
        host_item("approval-hidden", workspace_id="client-one", risk="low"),
        host_item("approval-filtered", workspace_id="cyryx-main", risk="medium"),
    )
    service, _source, _clock = projection(lambda: host_snapshot(values))
    page = service.open_page(
        query=inbox.InboxQuery(workspace_id="cyryx-main", risks=("low",)),
        environ=ON,
    )
    assert [item.item_id for item in page.items] == ["approval-visible"]
    for hidden in ("approval-hidden", "approval-filtered"):
        with pytest.raises(inbox.ApprovalInboxV3ContractError, match="outside"):
            service.preview_calm_batch(page.snapshot_token, (hidden,), environ=ON)


def test_pagination_is_stable_exact_set_without_duplicate_or_omission() -> None:
    values = tuple(
        host_item(f"approval-{number:02d}", created_at_ms=100 + number)
        for number in range(17)
    )
    service, _source, _clock = projection(lambda: host_snapshot(values))
    page = service.open_page(
        query=inbox.InboxQuery(sort="item-id-asc"), page_size=4, environ=ON
    )
    seen = [item.item_id for item in page.items]
    while page.next_cursor:
        page = service.continue_page(page.next_cursor, environ=ON)
        seen.extend(item.item_id for item in page.items)
    assert seen == sorted(item.item_id for item in values)
    assert len(seen) == len(set(seen)) == 17


def test_source_drift_cannot_mix_pages() -> None:
    state = {
        "snapshot": host_snapshot((host_item("approval-one"), host_item("approval-two")))
    }
    service, _source, _clock = projection(lambda: state["snapshot"])
    page = service.open_page(page_size=1, environ=ON)
    state["snapshot"] = host_snapshot(
        (host_item("approval-one"), host_item("approval-three")),
        revision="revision-two",
        epoch=2,
    )
    with pytest.raises(inbox.ApprovalInboxV3Stale):
        service.continue_page(page.next_cursor, environ=ON)


def test_calm_batch_canonical_reorder_add_remove_substitute_and_non_authority() -> None:
    values = tuple(host_item(f"approval-{name}") for name in ("one", "two", "three"))
    service, _source, _clock = projection(lambda: host_snapshot(values))
    page = service.open_page(environ=ON)

    def preview(*ids: str) -> inbox.CalmBatchPreview:
        return service.preview_calm_batch(page.snapshot_token, ids, environ=ON)

    first = preview("approval-three", "approval-one")
    reordered = preview("approval-one", "approval-three")
    assert first.manifest_digest == reordered.manifest_digest
    assert [item.item_id for item in first.items] == ["approval-one", "approval-three"]
    base = preview("approval-one", "approval-two").manifest_digest
    assert preview("approval-one").manifest_digest != base
    assert preview("approval-one", "approval-two", "approval-three").manifest_digest != base
    assert preview("approval-one", "approval-three").manifest_digest != base
    assert first.read_only is True
    assert first.approval_action_available is False
    assert first.authority_granted is False
    assert first.execution_available is False


@pytest.mark.parametrize(
    "risk,always_explicit,batch_eligible",
    [
        ("high", False, False),
        ("critical", True, False),
        ("medium", True, False),
        ("low", False, False),
    ],
)
def test_high_critical_always_explicit_or_ineligible_never_enters_batch(
    risk: str, always_explicit: bool, batch_eligible: bool
) -> None:
    value = host_item(
        "approval-blocked",
        risk=risk,
        always_explicit=always_explicit,
        batch_eligible=batch_eligible,
    )
    service, _source, _clock = projection(lambda: host_snapshot((value,)))
    page = service.open_page(environ=ON)
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="ineligible"):
        service.preview_calm_batch(page.snapshot_token, ("approval-blocked",), environ=ON)


def test_host_cannot_mislabel_high_or_always_explicit_as_batch_eligible() -> None:
    for risk, explicit in (("high", False), ("critical", False), ("low", True)):
        value = host_item(risk=risk, always_explicit=explicit, batch_eligible=True)
        service, _source, _clock = projection(lambda value=value: host_snapshot((value,)))
        with pytest.raises(inbox.ApprovalInboxV3ContractError, match="cannot be batch"):
            service.open_page(environ=ON)


def test_batch_forbids_wildcards_categories_duplicates_and_unbounded_sequences() -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    page = service.open_page(environ=ON)
    for selected in ((), ("*",), ("all-low-risk",), ("approval-*",), ("approval-unknown",)):
        with pytest.raises(inbox.ApprovalInboxV3ContractError):
            service.preview_calm_batch(page.snapshot_token, selected, environ=ON)
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="duplicates"):
        service.preview_calm_batch(
            page.snapshot_token, ("approval-one", "approval-one"), environ=ON
        )


def test_outer_token_validation_occurs_before_hmac_and_normalizes_all_malformed_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    calls = 0
    original = inbox.hmac.new

    def observed(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(inbox.hmac, "new", observed)
    malformed = (
        None,
        b"abc",
        7,
        "",
        "abc",
        "a.b.c",
        "å.0" * 32,
        "%%%" + "." + "0" * 64,
        "abc." + "A" * 64,
        "abc." + "g" * 64,
    )
    for token in malformed:
        before = calls
        with pytest.raises(inbox.ApprovalInboxV3Stale) as caught:
            service.continue_page(token, environ=ON)
        assert calls == before
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None


def test_encode_rejects_incomplete_or_noncanonical_payload_before_hmac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("HMAC ran before payload validation")

    monkeypatch.setattr(inbox.hmac, "new", forbidden)
    for payload in (
        {},
        {"v": 2, "k": "cursor"},
        {
            "d": "A" * 64,
            "k": "snapshot",
            "q": inbox.InboxQuery().payload(),
            "v": 2,
            "vd": digest("view"),
            "z": 20,
        },
    ):
        with pytest.raises(inbox.ApprovalInboxV3ContractError):
            service._encode(payload, payload.get("k", "snapshot"))
    assert calls == 0


def test_valid_hmac_with_malformed_payload_normalizes_to_stale() -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    for payload in (
        {"v": 2, "k": "cursor"},
        {
            "d": digest("snapshot"),
            "k": "cursor",
            "o": 1,
            "q": {},
            "v": 2,
            "vd": digest("view"),
            "z": 1,
        },
    ):
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        signature = hmac.new(service._token_key, body.encode(), hashlib.sha256).hexdigest()
        with pytest.raises(inbox.ApprovalInboxV3Stale) as caught:
            service.continue_page(f"{body}.{signature}", environ=ON)
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None


def test_tampered_token_and_restart_old_token_fail_before_source_callback() -> None:
    calls = 0

    def source():
        nonlocal calls
        calls += 1
        return host_snapshot((host_item("approval-one"), host_item("approval-two")))

    service, host, _clock = projection(source)
    page = service.open_page(page_size=1, environ=ON)
    tampered = page.next_cursor[:-1] + ("0" if page.next_cursor[-1] != "0" else "1")
    with pytest.raises(inbox.ApprovalInboxV3Stale):
        service.continue_page(tampered, environ=ON)
    restarted = inbox.ApprovalInboxProjection(host, inbox.DeterministicInboxClock(1_000))
    with pytest.raises(inbox.ApprovalInboxV3Stale):
        restarted.continue_page(page.next_cursor, environ=ON)
    with pytest.raises(inbox.ApprovalInboxV3Stale):
        restarted.preview_calm_batch(page.snapshot_token, ("approval-one",), environ=ON)
    assert calls == 1


def test_source_concurrency_is_capped_at_one_and_excess_fails_closed() -> None:
    entered = threading.Event()
    release = threading.Event()
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def source():
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        entered.set()
        assert release.wait(timeout=2)
        with state_lock:
            active -= 1
        return host_snapshot()

    service, _source, _clock = projection(source)
    results: list[str] = []

    def first():
        service.open_page(environ=ON)
        results.append("first-ready")

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(timeout=1)
    with pytest.raises(inbox.ApprovalInboxV3Unavailable, match="busy") as caught:
        service.open_page(environ=ON)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    release.set()
    thread.join(timeout=2)
    assert results == ["first-ready"]
    assert max_active == inbox.MAX_SOURCE_CALLBACKS == 1


def test_source_callbacks_never_run_under_projection_lock() -> None:
    holder: dict[str, inbox.ApprovalInboxProjection] = {}
    checks: list[bool] = []

    def source():
        outcome: list[bool] = []

        def probe():
            acquired = holder["service"]._lock.acquire(timeout=0.25)
            outcome.append(acquired)
            if acquired:
                holder["service"]._lock.release()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(timeout=1)
        checks.append(outcome == [True])
        return host_snapshot((host_item("approval-one"), host_item("approval-two")))

    holder["service"], _source, _clock = projection(source)
    page = holder["service"].open_page(page_size=1, environ=ON)
    holder["service"].continue_page(page.next_cursor, environ=ON)
    holder["service"].preview_calm_batch(
        page.snapshot_token, ("approval-one",), environ=ON
    )
    assert checks == [True, True, True]


def test_result_constructors_reject_forged_or_contradictory_inputs() -> None:
    with pytest.raises(TypeError, match="created by the projection"):
        inbox.InboxPage(object(), status="disabled")
    with pytest.raises(TypeError, match="created by the projection"):
        inbox.BatchPreviewItem(object(), object())
    with pytest.raises(TypeError, match="created by the projection"):
        inbox.CalmBatchPreview(object(), object(), object(), ())
    assert not hasattr(inbox, "_RESULT_SEAL")
    assert not any("factory" in name.casefold() or "seal" in name.casefold() for name in inbox.__all__)

    service, _source, _clock = projection(
        lambda: host_snapshot((host_item("approval-one"), host_item("approval-two")))
    )
    page = service.open_page(page_size=1, environ=ON)
    snapshot = service._snapshots[page.snapshot_digest]
    view = service._views[page.view_digest]
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="next cursor"):
        inbox._make_page_result(
            service,
            status="ready",
            snapshot=snapshot,
            view=view,
            items=page.items,
            offset=0,
            snapshot_token=page.snapshot_token,
            next_cursor=None,
        )
    fake_view = inbox._View(
        snapshot.snapshot_digest,
        digest("forged-view"),
        view.query,
        view.page_size,
        view.allowed_item_ids,
        view.local_deadline_ms,
    )
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="not canonical"):
        inbox._make_page_result(
            service,
            status="ready",
            snapshot=snapshot,
            view=fake_view,
            items=page.items,
            offset=0,
            snapshot_token=page.snapshot_token,
            next_cursor=page.next_cursor,
        )
    forged_token = page.snapshot_token[:-1] + ("0" if page.snapshot_token[-1] != "0" else "1")
    with pytest.raises(inbox.ApprovalInboxV3Stale, match="invalid-authenticated"):
        inbox._make_page_result(
            service,
            status="ready",
            snapshot=snapshot,
            view=view,
            items=page.items,
            offset=0,
            snapshot_token=forged_token,
            next_cursor=page.next_cursor,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 99),
        ("source_epoch", 0),
        ("principal_id", "attacker-session"),
        ("session_id", "attacker-session"),
        ("audit_healthy", False),
        ("session_active", False),
        ("kill_switch", True),
    ],
)
def test_unknown_identity_safety_and_schema_state_fail_closed(field: str, value: object) -> None:
    altered = replace(host_snapshot(), **{field: value})
    service, _source, _clock = projection(lambda: altered)
    with pytest.raises((inbox.ApprovalInboxV3ContractError, inbox.ApprovalInboxV3Unavailable)):
        service.open_page(environ=ON)


def test_limits_and_bounded_snapshot_view_caches() -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="page_size"):
        service.open_page(page_size=inbox.MAX_PAGE_SIZE + 1, environ=ON)
    too_long = replace(host_item(), reason="a" * (inbox.MAX_SUMMARY + 1))
    invalid, _source, _clock = projection(lambda: host_snapshot((too_long,)))
    with pytest.raises(inbox.ApprovalInboxV3ContractError, match="reason"):
        invalid.open_page(environ=ON)

    state = {"epoch": 1}
    clock = inbox.DeterministicInboxClock(1_000)

    def rolling():
        epoch = state["epoch"]
        return host_snapshot(revision=f"revision-{epoch:02d}", epoch=epoch)

    bounded, _source, _clock = projection(rolling, clock)
    for epoch in range(1, inbox.MAX_SNAPSHOTS + 3):
        state["epoch"] = epoch
        clock.advance(1)
        bounded.open_page(
            query=inbox.InboxQuery(sort="item-id-asc"),
            page_size=(epoch % inbox.MAX_PAGE_SIZE) + 1,
            environ=ON,
        )
    assert len(bounded._snapshots) == inbox.MAX_SNAPSHOTS
    assert len(bounded._views) <= inbox.MAX_VIEWS


def test_no_mutation_grant_import_persistence_or_live_wiring() -> None:
    methods = {
        name
        for name, value in inspect.getmembers(inbox.ApprovalInboxProjection, inspect.isfunction)
        if not name.startswith("_")
    }
    assert methods == {"open_page", "continue_page", "preview_calm_batch"}
    source_text = Path(inbox.__file__).read_text(encoding="utf-8")
    assert "session_grants_v11" not in source_text
    assert "sqlite3" not in source_text
    assert "pathlib" not in source_text
    assert inbox.GRANT_INSPECTOR_STATUS == "omitted-phase5-2b-no-r11-import"
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "main.py",
        "ui.py",
        "core/__init__.py",
        "dashboard/server.py",
        "dashboard/static/app.html",
        "scripts/launch_onyx.pyw",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "approval_inbox_v3" not in text
        assert inbox.APPROVAL_INBOX_FLAG not in text


def test_v1_v2_and_r11_frozen_anchor_bytes_remain_exact() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = {
        "core/approval_inbox_v1.py": "01435dee3c5f2122afa05245efac73950b78fe50264c372b53ca61dabc9ad560",
        "tests/test_approval_inbox_v1.py": "605be42da065683e5b107372b4cade271e32ec7002526520dda3a7db947efcaf",
        "scripts/verify_phase5_approval_inbox_v1.py": "ed2cb194492943f70722d203e896d52088a772b3b9651b2a6c800daa8f98d029",
        "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V1-001.sha256": "c0a2a7d4d0314d2b061b826463ac9bf6828bc27a0e7ef00dd0d47ab55d19ced8",
        "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V1-001.sha256": "d67c15e1644fd1de16d485714509ca11ec01f458a1464f7457378a00f6c82e21",
        "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V2-001.sha256": "29e57a20191c2de46c4bae9476a5e072b7eddb2c9f941897b24b3a6f7d90e54d",
        "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V2-001.sha256": "cc3673ad29e69d8658ca75ffac4cc28279c1b6ca0a63d6b080bd17037f233930",
        "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256": "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071",
        "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R11-001.sha256": "0253aba6b0fed67bbac6b1eda55ea32a9928f44b036b2fbc0c5daec78e0b33d7",
        "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256": "36fb198e27ebb7e8e8bb97885d8a823d2a291ed573da3d5513d950715b113bb0",
        "docs/onyx/acceptance/VE-P51-GRANTS-R11-E6-001.md": "ff703416675653b4f1611e7f9ee633fac974c3bdf4225a16d84f302233b824d4",
    }
    for relative, wanted in expected.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == wanted


def test_r11_transitive_tamper_fixture_rejects_v10_before_recursive_execution() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v3-r11-tamper-", dir=evidence.PROJECT
    ) as directory:
        frozen = Path(directory)
        copied = evidence.materialize_r11(frozen)
        assert "core/session_grants_v10.py" in copied
        target = frozen / "core" / "session_grants_v10.py"
        target.write_bytes(target.read_bytes() + b"\n# adversarial transitive tamper\n")
        with pytest.raises(evidence.Phase52V3EvidenceError, match="session_grants_v10.py"):
            evidence.verify_historical_manifest_tree(
                frozen,
                (evidence.R11_ROOT, evidence.R11_ACCEPTANCE_MANIFEST),
            )


@pytest.mark.parametrize("field", ["limits", "base_commit", "environment", "timestamp"])
def test_regenerated_hashes_cannot_bypass_semantic_metadata(field: str) -> None:
    junit_timestamp = "2026-07-20T12:00:00.123456-04:00"
    bundle: dict[str, object] = {
        "base_commit": evidence.current_base_commit(),
        "environment": evidence.actual_environment(),
        "limits": evidence.derive_limits(),
        "timestamp": evidence.canonical_evidence_timestamp(junit_timestamp),
    }
    tampered = json.loads(json.dumps(bundle))
    if field == "limits":
        tampered["limits"]["max_items"] += 1
    elif field == "base_commit":
        tampered["base_commit"] = "0" * 40
    elif field == "environment":
        tampered["environment"]["static_tools"]["ruff"] = "ruff forged"
    else:
        tampered["timestamp"] = "2026-01-01T00:00:00+00:00"
    with tempfile.TemporaryDirectory(
        prefix=".p52-v3-semantic-tamper-", dir=evidence.PROJECT
    ) as directory:
        root = Path(directory)
        (root / "bundle.json").write_bytes(evidence._canonical(tampered))
        bundle_hash = hashlib.sha256((root / "bundle.json").read_bytes()).hexdigest()
        (root / "artifact.sha256").write_text(
            f"{bundle_hash}  bundle.json\n", encoding="utf-8", newline="\n"
        )
        artifact_hash = hashlib.sha256(
            (root / "artifact.sha256").read_bytes()
        ).hexdigest()
        (root / "root.sha256").write_text(
            f"{artifact_hash}  artifact.sha256\n", encoding="utf-8", newline="\n"
        )
        evidence._verify_entries(evidence._parse_manifest("root.sha256", root=root), root)
        evidence._verify_entries(
            evidence._parse_manifest("artifact.sha256", root=root), root
        )
        with pytest.raises(evidence.Phase52V3EvidenceError):
            evidence.validate_semantic_metadata(tampered, junit_timestamp)
