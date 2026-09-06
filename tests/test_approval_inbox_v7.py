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

from core import approval_inbox_v7 as inbox
from scripts import verify_phase5_approval_inbox_v7 as evidence


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


def reviewed(page: inbox.InboxPage, *item_ids: str) -> tuple[tuple[str, str], ...]:
    by_id = {item.item_id: item.review_token for item in page.items}
    assert all(type(by_id[item_id]) is str for item_id in item_ids)
    return tuple((item_id, by_id[item_id]) for item_id in item_ids)


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
        "selections",
        "environ",
    }


def test_exact_source_output_types_only_no_subclass_or_custom_mapping() -> None:
    class SnapshotSubclass(inbox.HostInboxSnapshot):
        pass

    values = host_snapshot()
    subclass = SnapshotSubclass(*[getattr(values, field) for field in values.__dataclass_fields__])
    for result in ({"items": ()}, subclass, object()):
        service, _source, _clock = projection(lambda result=result: result)
        with pytest.raises(inbox.ApprovalInboxV7ContractError, match="concrete type"):
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
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="exceeds"):
        service.open_page(environ=ON)
    assert hooks == {"iter": 0, "deepcopy": 0, "attribute": 0}

    custom = Hook()
    service, _source, _clock = projection(lambda: host_snapshot(custom))
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="exact tuple"):
        service.open_page(environ=ON)
    assert hooks == {"iter": 0, "deepcopy": 0, "attribute": 0}

    service, _source, _clock = projection(lambda: host_snapshot((Hook(),)))
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="concrete type"):
        service.open_page(environ=ON)
    assert hooks == {"iter": 0, "deepcopy": 0, "attribute": 0}


def test_raw_callback_exception_is_not_chained_or_recoverable() -> None:
    canary = "sk-proj-SUPERSECRETCANARY1234567890"

    def source():
        raise RuntimeError(canary, {"payload": canary})

    service, _source, _clock = projection(source)
    with pytest.raises(inbox.ApprovalInboxV7Unavailable) as caught:
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
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="secret-like"):
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


def test_refreshed_source_timestamp_metadata_same_epoch_does_not_latch() -> None:
    values = (host_item("approval-one"), host_item("approval-two"))
    state = {"snapshot": host_snapshot(values, captured_at_ms=100, valid_until_ms=900)}
    service, _source, _clock = projection(lambda: state["snapshot"])
    page = service.open_page(page_size=1, environ=ON)
    state["snapshot"] = host_snapshot(
        values, captured_at_ms=300, valid_until_ms=1_500
    )
    assert service.continue_page(page.next_cursor, environ=ON).status == "ready"
    assert service._integrity_failed is False


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
    with pytest.raises(inbox.ApprovalInboxV7Stale, match="deadline"):
        service.continue_page(page.next_cursor, environ=ON)
    assert calls == 1
    fresh = service.open_page(page_size=1, environ=ON)
    assert fresh.snapshot_digest != page.snapshot_digest
    with pytest.raises(inbox.ApprovalInboxV7Stale):
        service.continue_page(page.next_cursor, environ=ON)


def test_monotonic_clock_rollback_latches_and_cannot_resurrect() -> None:
    service, _source, clock = projection(
        lambda: host_snapshot((host_item("approval-one"), host_item("approval-two")))
    )
    page = service.open_page(page_size=1, environ=ON)
    clock.advance(10)
    service.continue_page(page.next_cursor, environ=ON)
    clock.set_for_test(1_005)
    with pytest.raises(inbox.ApprovalInboxV7Unavailable, match="rollback"):
        service.continue_page(page.next_cursor, environ=ON)
    clock.set_for_test(2_000)
    with pytest.raises(inbox.ApprovalInboxV7Unavailable, match="rollback"):
        service.continue_page(page.next_cursor, environ=ON)


def test_same_epoch_equivocation_latches_and_restore_never_resurrects() -> None:
    original = host_snapshot((host_item("approval-one"), host_item("approval-two")))
    state = {"snapshot": original}
    service, _source, _clock = projection(lambda: state["snapshot"])
    page = service.open_page(page_size=1, environ=ON)
    state["snapshot"] = host_snapshot((host_item("approval-two"),))
    with pytest.raises(inbox.ApprovalInboxV7Stale, match="without-epoch"):
        service.continue_page(page.next_cursor, environ=ON)
    state["snapshot"] = original
    for operation in (
        lambda: service.open_page(environ=ON),
        lambda: service.continue_page(page.next_cursor, environ=ON),
        lambda: service.preview_calm_batch(
            page.snapshot_token, reviewed(page, "approval-one"), environ=ON
        ),
    ):
        with pytest.raises(inbox.ApprovalInboxV7Unavailable, match="integrity-failed"):
            operation()
    restarted, _source, _clock = projection(lambda: original)
    assert restarted.open_page(environ=ON).status == "ready"


def test_epoch_rollback_latches_and_restore_never_resurrects() -> None:
    current = host_snapshot(revision="revision-two", epoch=2)
    state = {"snapshot": current}
    service, _source, _clock = projection(lambda: state["snapshot"])
    page = service.open_page(environ=ON)
    state["snapshot"] = host_snapshot(revision="revision-one", epoch=1)
    with pytest.raises(inbox.ApprovalInboxV7Stale, match="rollback"):
        service.open_page(environ=ON)
    state["snapshot"] = current
    with pytest.raises(inbox.ApprovalInboxV7Unavailable, match="integrity-failed"):
        service.open_page(environ=ON)
    with pytest.raises(inbox.ApprovalInboxV7Unavailable, match="integrity-failed"):
        service.preview_calm_batch(
            page.snapshot_token, reviewed(page, "approval-one"), environ=ON
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
        except inbox.ApprovalInboxV7Stale:
            results.append("latched")
        finally:
            latch_observed.set()

    def restore() -> None:
        assert latch_observed.wait(timeout=2)
        state["snapshot"] = original
        try:
            service.continue_page(page.next_cursor, environ=ON)
        except inbox.ApprovalInboxV7Unavailable:
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
            "contract": "ApprovalInboxPage.v7",
            "snapshot_digest": page.snapshot_digest,
            "view_digest": page.view_digest,
            "query": query.payload(),
            "page_size": 1,
            "offset": 0,
            "total_items": 2,
            "item_digests": [page.items[0].item_digest],
            "review_token_digests": [
                inbox._token_digest(page.items[0].review_token)
            ],
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
        with pytest.raises(inbox.ApprovalInboxV7ContractError, match="outside"):
            service.preview_calm_batch(
                page.snapshot_token,
                ((hidden, page.items[0].review_token),),
                environ=ON,
            )


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
    with pytest.raises(inbox.ApprovalInboxV7Stale):
        service.continue_page(page.next_cursor, environ=ON)


def test_calm_batch_canonical_reorder_add_remove_substitute_and_non_authority() -> None:
    values = tuple(host_item(f"approval-{name}") for name in ("one", "two", "three"))
    service, _source, _clock = projection(lambda: host_snapshot(values))
    page = service.open_page(environ=ON)

    def preview(*ids: str) -> inbox.CalmBatchPreview:
        return service.preview_calm_batch(
            page.snapshot_token, reviewed(page, *ids), environ=ON
        )

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


def test_page_size_one_requires_second_item_to_be_returned_before_batch() -> None:
    values = (host_item("approval-one"), host_item("approval-two"))
    service, _source, _clock = projection(lambda: host_snapshot(values))
    first = service.open_page(
        query=inbox.InboxQuery(sort="item-id-asc"), page_size=1, environ=ON
    )
    snapshot = service._snapshots[first.snapshot_digest]
    view = service._views[first.view_digest]
    second_source_item = next(item for item in snapshot.items if item.item_id == "approval-two")
    valid_but_unreturned = service._review_token(snapshot, view, second_source_item)
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="not returned"):
        service.preview_calm_batch(
            first.snapshot_token,
            (("approval-two", valid_but_unreturned),),
            environ=ON,
        )
    second = service.continue_page(first.next_cursor, environ=ON)
    preview = service.preview_calm_batch(
        first.snapshot_token, reviewed(second, "approval-two"), environ=ON
    )
    assert [item.item_id for item in preview.items] == ["approval-two"]


def test_review_token_substitution_cross_view_and_restart_replay_fail_closed() -> None:
    values = (host_item("approval-one"), host_item("approval-two"))
    service, host, _clock = projection(lambda: host_snapshot(values))
    first = service.open_page(
        query=inbox.InboxQuery(sort="item-id-asc"), environ=ON
    )
    one_token = next(item.review_token for item in first.items if item.item_id == "approval-one")
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="not returned"):
        service.preview_calm_batch(
            first.snapshot_token, (("approval-two", one_token),), environ=ON
        )
    second_view = service.open_page(
        query=inbox.InboxQuery(sort="workspace-asc"), environ=ON
    )
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="not returned"):
        service.preview_calm_batch(
            second_view.snapshot_token, (("approval-one", one_token),), environ=ON
        )
    restarted = inbox.ApprovalInboxProjection(
        host, inbox.DeterministicInboxClock(1_000)
    )
    with pytest.raises(inbox.ApprovalInboxV7Stale):
        restarted.preview_calm_batch(
            first.snapshot_token, (("approval-one", one_token),), environ=ON
        )


def test_reopening_identical_view_preserves_previously_returned_review_proofs() -> None:
    values = (host_item("approval-one"), host_item("approval-two"))
    service, _source, _clock = projection(lambda: host_snapshot(values))
    query = inbox.InboxQuery(sort="item-id-asc")
    first = service.open_page(query=query, page_size=1, environ=ON)
    first_review = reviewed(first, "approval-one")
    proof_map = service._returned_reviews[first.view_digest]

    reopened = service.open_page(query=query, page_size=1, environ=ON)

    assert reopened.view_digest == first.view_digest
    assert service._returned_reviews[first.view_digest] is proof_map
    assert proof_map["approval-one"] == first_review[0][1]
    preview = service.preview_calm_batch(
        first.snapshot_token, first_review, environ=ON
    )
    assert [item.item_id for item in preview.items] == ["approval-one"]


@pytest.mark.parametrize("corruption", ["conflicting-view", "missing-proofs"])
def test_reopening_conflicting_registered_view_state_latches_fail_closed(
    corruption: str,
) -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    page = service.open_page(environ=ON)
    view = service._views[page.view_digest]
    if corruption == "conflicting-view":
        service._views[page.view_digest] = replace(
            view, allowed_item_ids=("approval-forged",)
        )
    else:
        del service._returned_reviews[page.view_digest]

    with pytest.raises(inbox.ApprovalInboxV7Stale, match="registered-view-proof-conflict"):
        service.open_page(environ=ON)
    with pytest.raises(inbox.ApprovalInboxV7Unavailable, match="integrity"):
        service.open_page(environ=ON)


def test_batch_preview_contains_complete_human_review_fields() -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    page = service.open_page(environ=ON)
    assert type(page.items[0].review_token) is str
    preview = service.preview_calm_batch(
        page.snapshot_token, reviewed(page, "approval-one"), environ=ON
    )
    item = preview.items[0]
    required = {
        "workspace_id", "workspace_display", "account_display", "mission_id",
        "mission_display", "reason", "action", "target_display", "target_digest",
        "payload_summary", "payload_digest", "data_class", "egress", "effect_summary",
        "reversibility", "idempotency_summary", "idempotency_key",
        "verification_plan", "rollback_plan", "cost_micro", "currency", "risk",
        "created_at_ms", "expires_at_ms", "always_explicit", "batch_eligible",
        "item_id", "item_digest", "review_token",
    }
    assert required == set(item.__dataclass_fields__)
    assert item.reason == page.items[0].reason
    assert item.payload_summary == page.items[0].payload_summary


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
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="ineligible"):
        service.preview_calm_batch(
            page.snapshot_token, reviewed(page, "approval-blocked"), environ=ON
        )


def test_host_cannot_mislabel_high_or_always_explicit_as_batch_eligible() -> None:
    for risk, explicit in (("high", False), ("critical", False), ("low", True)):
        value = host_item(risk=risk, always_explicit=explicit, batch_eligible=True)
        service, _source, _clock = projection(lambda value=value: host_snapshot((value,)))
        with pytest.raises(inbox.ApprovalInboxV7ContractError, match="cannot be batch"):
            service.open_page(environ=ON)


def test_batch_forbids_wildcards_categories_duplicates_and_unbounded_sequences() -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    page = service.open_page(environ=ON)
    for selected in ((), ("*",), ("all-low-risk",), ("approval-*",), ("approval-unknown",)):
        with pytest.raises(inbox.ApprovalInboxV7ContractError):
            service.preview_calm_batch(page.snapshot_token, selected, environ=ON)
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="duplicates"):
        service.preview_calm_batch(
            page.snapshot_token,
            reviewed(page, "approval-one", "approval-one"),
            environ=ON,
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
        with pytest.raises(inbox.ApprovalInboxV7Stale) as caught:
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
        with pytest.raises(inbox.ApprovalInboxV7ContractError):
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
        with pytest.raises(inbox.ApprovalInboxV7Stale) as caught:
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
    with pytest.raises(inbox.ApprovalInboxV7Stale):
        service.continue_page(tampered, environ=ON)
    restarted = inbox.ApprovalInboxProjection(host, inbox.DeterministicInboxClock(1_000))
    with pytest.raises(inbox.ApprovalInboxV7Stale):
        restarted.continue_page(page.next_cursor, environ=ON)
    with pytest.raises(inbox.ApprovalInboxV7Stale):
        restarted.preview_calm_batch(
            page.snapshot_token, reviewed(page, "approval-one"), environ=ON
        )
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
    with pytest.raises(inbox.ApprovalInboxV7Unavailable, match="busy") as caught:
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
        page.snapshot_token, reviewed(page, "approval-one"), environ=ON
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
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="next cursor"):
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
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="not canonical"):
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
    with pytest.raises(inbox.ApprovalInboxV7Stale, match="invalid-authenticated"):
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
    with pytest.raises((inbox.ApprovalInboxV7ContractError, inbox.ApprovalInboxV7Unavailable)):
        service.open_page(environ=ON)


def test_limits_and_bounded_snapshot_view_caches() -> None:
    service, _source, _clock = projection(lambda: host_snapshot())
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="page_size"):
        service.open_page(page_size=inbox.MAX_PAGE_SIZE + 1, environ=ON)
    too_long = replace(host_item(), reason="a" * (inbox.MAX_SUMMARY + 1))
    invalid, _source, _clock = projection(lambda: host_snapshot((too_long,)))
    with pytest.raises(inbox.ApprovalInboxV7ContractError, match="reason"):
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
        assert "approval_inbox_v7" not in text
        assert inbox.APPROVAL_INBOX_FLAG not in text


def test_v1_v2_v3_v4_v5_v6_and_r11_frozen_anchor_bytes_remain_exact() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = {
        "core/approval_inbox_v1.py": "01435dee3c5f2122afa05245efac73950b78fe50264c372b53ca61dabc9ad560",
        "tests/test_approval_inbox_v1.py": "605be42da065683e5b107372b4cade271e32ec7002526520dda3a7db947efcaf",
        "scripts/verify_phase5_approval_inbox_v1.py": "ed2cb194492943f70722d203e896d52088a772b3b9651b2a6c800daa8f98d029",
        "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V1-001.sha256": "c0a2a7d4d0314d2b061b826463ac9bf6828bc27a0e7ef00dd0d47ab55d19ced8",
        "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V1-001.sha256": "d67c15e1644fd1de16d485714509ca11ec01f458a1464f7457378a00f6c82e21",
        "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V2-001.sha256": "29e57a20191c2de46c4bae9476a5e072b7eddb2c9f941897b24b3a6f7d90e54d",
        "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V2-001.sha256": "cc3673ad29e69d8658ca75ffac4cc28279c1b6ca0a63d6b080bd17037f233930",
        "core/approval_inbox_v2.py": "99e29e8d65f35d7abea147e06aeffb5bd1db1b96953c816d4d8967b3f061dabe",
        "tests/test_approval_inbox_v2.py": "c8eac6ccc263ef1f278ad75443eead8aab681c466a823c4414550d0319c44805",
        "scripts/verify_phase5_approval_inbox_v2.py": "2024016da88ab94d81942c716c948b6b6b4c1dfb78eddcb7ffcda19d6f8e5a56",
        "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V3-001.sha256": "a780f95c0e8b2b5236ed424e4382e0be1691600d24a08a490d58be942ba149c8",
        "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V3-001.sha256": "bb86dd76bdfc94603bae7c556827062f3a0a65183bd2f3ce65ede620ad9a7192",
        "core/approval_inbox_v3.py": "af4ff749a49867fa47b6d773e8a47d4c82bcb0bad04ad3394bedb9cb4f5d05cb",
        "tests/test_approval_inbox_v3.py": "a2a1721b172a1a23c69590690059aba046b2a60f6354939df1a142ff97858606",
        "scripts/verify_phase5_approval_inbox_v3.py": "599533f7836b7dc18556758f914d00da0c1755595c6df8dd88040e60195c9db9",
        "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V4-001.sha256": "a67ffe30ca3c173823ecc061e8c0d0c0a57c0896bf0f0970bf78df8e14178351",
        "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V4-001.sha256": "db4ed6b5a229116168d2abd50743763a2839ff2ae0a49d0ee82bcf5f74aefde1",
        "core/approval_inbox_v4.py": "f517774cfad4931348cfc7326831bdeb68ace1b54dc9cbd685b2a004aa38c66d",
        "tests/test_approval_inbox_v4.py": "5c7db679e0675a00e0782f2a170e5d6e8df6d9867f9ca92225cb510a1eea3873",
        "scripts/verify_phase5_approval_inbox_v4.py": "da97a9348a9765ba0283e811ca59921b783c10f0cf24194afd7bda1d6d9d22ec",
        "scripts/check_phase5_approval_inbox_v4_whitespace.py": "ae456c28cfc7d42468b5c65ffe2575beba3435c9779b236a755aa30f1372ec31",
        "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V5-001.sha256": "e4c1ed861d51f3d0fb6d72bc82d6c01675efc5a630d795e2d053030221d11feb",
        "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V5-001.sha256": "f9c8c116d0facce83e6404c011c0dea5468314c8589227e5c4903e0e5cbc6108",
        "core/approval_inbox_v5.py": "353244a9a7b83bd79625a4f8df47582b4885dc9958647f1d4b4e5968c4d143d6",
        "tests/test_approval_inbox_v5.py": "4c9bbe9b6b49381fa092fbf99f345f484d6502bdf5401b4f6f841af3a66ce346",
        "scripts/verify_phase5_approval_inbox_v5.py": "93d51b079e8ba8736147d0c09cff18fb65a94dba3bd28c08cb1458266b440967",
        "scripts/check_phase5_approval_inbox_v5_whitespace.py": "e0e83165db713ea8e62b45134d683c488db2019223362daef658706082c98a17",
        "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V6-001.sha256": "1c8250b69c9cc006a4d2bc80babe85b256884d584c5eb08c73d5473acdfc6d21",
        "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V6-001.sha256": "178b56813c4c9c9dade23c79df1ca7181e99e3b0600b84a99b340a84163844a1",
        "core/approval_inbox_v6.py": "6978defb139ea86def1d1ce42550e82652435e9cb2b2ac7e0f90e10610b38ecf",
        "tests/test_approval_inbox_v6.py": "d7255530c95f3be46d2b15a688225d4a0106b78d6385189da45856b1bdcaf978",
        "scripts/verify_phase5_approval_inbox_v6.py": "755d75de078052ec933f731763cbe679d5f62d1b95ad337da28cc21fe8326d5b",
        "scripts/check_phase5_approval_inbox_v6_whitespace.py": "29dde13224e0fb4e835b3cff76b8479033ccbb918392c7d8c74b0daa3b6126a2",
        "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256": "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071",
        "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R11-001.sha256": "0253aba6b0fed67bbac6b1eda55ea32a9928f44b036b2fbc0c5daec78e0b33d7",
        "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256": "36fb198e27ebb7e8e8bb97885d8a823d2a291ed573da3d5513d950715b113bb0",
        "docs/onyx/acceptance/VE-P51-GRANTS-R11-E6-001.md": "ff703416675653b4f1611e7f9ee633fac974c3bdf4225a16d84f302233b824d4",
    }
    for relative, wanted in expected.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == wanted


def test_r11_transitive_tamper_fixture_rejects_v10_before_recursive_execution() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v7-r11-tamper-", dir=evidence.PROJECT
    ) as directory:
        frozen = Path(directory)
        copied = evidence.materialize_r11(frozen)
        assert "core/session_grants_v10.py" in copied
        target = frozen / "core" / "session_grants_v10.py"
        target.write_bytes(target.read_bytes() + b"\n# adversarial transitive tamper\n")
        with pytest.raises(evidence.Phase52V7EvidenceError, match="session_grants_v10.py"):
            evidence.verify_historical_manifest_tree(
                frozen,
                (evidence.R11_ROOT, evidence.R11_ACCEPTANCE_MANIFEST),
            )


def test_v2_transitive_tamper_fixture_rejects_core_v2() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v7-v2-tamper-", dir=evidence.PROJECT
    ) as directory:
        frozen = Path(directory)
        copied = evidence.materialize_v2(frozen)
        assert "core/approval_inbox_v2.py" in copied
        target = frozen / "core" / "approval_inbox_v2.py"
        target.write_bytes(target.read_bytes() + b"\n# adversarial V2 core tamper\n")
        with pytest.raises(evidence.Phase52V7EvidenceError, match="approval_inbox_v2.py"):
            evidence.verify_historical_manifest_tree(frozen, (evidence.V2_ROOT,))


def test_v3_transitive_tamper_fixture_rejects_core_v3() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v7-v3-tamper-", dir=evidence.PROJECT
    ) as directory:
        frozen = Path(directory)
        copied = evidence.materialize_v3(frozen)
        assert "core/approval_inbox_v3.py" in copied
        target = frozen / "core" / "approval_inbox_v3.py"
        target.write_bytes(target.read_bytes() + b"\n# adversarial V3 core tamper\n")
        with pytest.raises(evidence.Phase52V7EvidenceError, match="approval_inbox_v3.py"):
            evidence.verify_historical_manifest_tree(frozen, (evidence.V3_ROOT,))


def test_v5_transitive_tamper_fixture_rejects_core_v5() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v7-v5-tamper-", dir=evidence.PROJECT
    ) as directory:
        frozen = Path(directory)
        copied = evidence.materialize_v5(frozen)
        assert "core/approval_inbox_v5.py" in copied
        target = frozen / "core" / "approval_inbox_v5.py"
        target.write_bytes(target.read_bytes() + b"\n# adversarial V5 core tamper\n")
        with pytest.raises(evidence.Phase52V7EvidenceError, match="approval_inbox_v5.py"):
            evidence.verify_historical_manifest_tree(frozen, (evidence.V5_ROOT,))


def test_v6_transitive_tamper_fixture_rejects_core_v6() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v7-v6-tamper-", dir=evidence.PROJECT
    ) as directory:
        frozen = Path(directory)
        copied = evidence.materialize_v6(frozen)
        assert "core/approval_inbox_v6.py" in copied
        target = frozen / "core" / "approval_inbox_v6.py"
        target.write_bytes(target.read_bytes() + b"\n# adversarial V6 core tamper\n")
        with pytest.raises(evidence.Phase52V7EvidenceError, match="approval_inbox_v6.py"):
            evidence.verify_historical_manifest_tree(frozen, (evidence.V6_ROOT,))


def test_future_approval_successor_import_indirection_is_rejected() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v7-import-walk-", dir=evidence.PROJECT
    ) as directory:
        root = Path(directory)
        (root / "core").mkdir()
        (root / "core" / "future").mkdir()
        (root / "scripts").mkdir()
        (root / "main.py").write_text("\n", encoding="utf-8", newline="\n")
        (root / "ui.py").write_text("\n", encoding="utf-8", newline="\n")
        (root / "scripts" / "launch_onyx.pyw").write_text(
            "import main\n", encoding="utf-8", newline="\n"
        )
        (root / "core" / "__init__.py").write_text("\n", encoding="utf-8", newline="\n")
        (root / "core" / "future" / "__init__.py").write_text(
            "\n", encoding="utf-8", newline="\n"
        )
        (root / "core" / "approval_inbox_v7.py").write_text(
            "\n", encoding="utf-8", newline="\n"
        )
        (root / "core" / "future" / "approval_inbox_v8.py").write_text(
            "import importlib as loader\n"
            "loader.import_module('..approval_inbox_v7', package='core.future')\n",
            encoding="utf-8",
            newline="\n",
        )
        with pytest.raises(evidence.Phase52V7EvidenceError, match="imports frozen approval"):
            evidence.live_scan_paths(root)


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nload = importlib.import_module\n"
        "load('core.approval_inbox_v7')\n",
        "import importlib\n"
        "getattr(importlib, 'import_module')('core.approval_inbox_v7')\n",
        "import builtins\nbuiltins.__import__('core.approval_inbox_v7')\n",
        "from builtins import __import__ as load\n"
        "load('core.approval_inbox_v7')\n",
        "import runpy\n"
        "getattr(runpy, 'run_module')('core.approval_inbox_v7')\n",
        "import importlib\nfirst = importlib.import_module\nsecond = first\n"
        "second('core.approval_inbox_v7')\n",
        "import importlib\nload = importlib.import_module\n"
        "load = unknown_loader\nload('core.approval_inbox_v7')\n",
        "eval(\"__import__('core.approval_inbox_v7')\")\n",
        "source = unknown_source\neval(source)\n",
        "exec('import core.approval_inbox_v7')\n",
        "source = unknown_source\nexec(source)\n",
        "code = compile('import core.approval_inbox_v7', '<future>', 'exec')\n",
        "source = unknown_source\ncode = compile(source, '<future>', 'exec')\n",
    ],
    ids=[
        "assignment-alias",
        "getattr-importlib",
        "builtins-dunder-import",
        "from-builtins-alias",
        "getattr-runpy",
        "alias-chain",
        "ambiguous-rebinding",
        "eval-literal",
        "eval-nonliteral",
        "exec-literal",
        "exec-nonliteral",
        "compile-literal",
        "compile-nonliteral",
    ],
)
def test_future_v8_loader_forms_fail_closed(source: str) -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v7-future-loader-", dir=evidence.PROJECT
    ) as directory:
        root = Path(directory)
        (root / "core" / "future").mkdir(parents=True)
        (root / "scripts").mkdir()
        (root / "main.py").write_text("\n", encoding="utf-8", newline="\n")
        (root / "ui.py").write_text("\n", encoding="utf-8", newline="\n")
        (root / "scripts" / "launch_onyx.pyw").write_text(
            "import main\n", encoding="utf-8", newline="\n"
        )
        for relative in ("core/__init__.py", "core/future/__init__.py"):
            (root / relative).write_text("\n", encoding="utf-8", newline="\n")
        (root / "core" / "approval_inbox_v7.py").write_text(
            "\n", encoding="utf-8", newline="\n"
        )
        (root / "core" / "future" / "approval_inbox_v8.py").write_text(
            source, encoding="utf-8", newline="\n"
        )
        with pytest.raises(evidence.Phase52V7EvidenceError):
            evidence.live_scan_paths(root)


@pytest.mark.parametrize(
    "module_relative,main_import,loader",
    [
        (
            "core/loader.py",
            "import core.loader\n",
            "import importlib as dynamic_loader\n"
            "dynamic_loader.import_module('.approval_inbox_v7', package='core')\n",
        ),
        (
            "core/adapters/loader.py",
            "import core.adapters.loader\n",
            "from importlib import import_module as load\n"
            "load('..approval_inbox_v7', 'core.adapters')\n",
        ),
    ],
    ids=["single-dot-keyword-alias", "double-dot-positional-bound-alias"],
)
def test_relative_importlib_wiring_is_resolved_and_rejected(
    module_relative: str, main_import: str, loader: str
) -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v7-relative-wiring-", dir=evidence.PROJECT
    ) as directory:
        root = Path(directory)
        (root / "core" / "adapters").mkdir(parents=True)
        (root / "scripts").mkdir()
        (root / "main.py").write_text(main_import, encoding="utf-8", newline="\n")
        (root / "ui.py").write_text("\n", encoding="utf-8", newline="\n")
        (root / "scripts" / "launch_onyx.pyw").write_text(
            "import main\n", encoding="utf-8", newline="\n"
        )
        for relative in ("core/__init__.py", "core/adapters/__init__.py"):
            (root / relative).write_text("\n", encoding="utf-8", newline="\n")
        (root / "core" / "approval_inbox_v7.py").write_text(
            "\n", encoding="utf-8", newline="\n"
        )
        (root / module_relative).write_text(loader, encoding="utf-8", newline="\n")
        with pytest.raises(evidence.Phase52V7EvidenceError, match="approval inbox"):
            evidence.live_scan_paths(root)


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nname='.approval_inbox_v7'\n"
        "importlib.import_module(name, package='core')\n",
        "import importlib\npackage='core'\n"
        "importlib.import_module('.approval_inbox_v7', package=package)\n",
        "import importlib\nimportlib.import_module('.approval_inbox_v7')\n",
        "import importlib\n"
        "importlib.import_module('...approval_inbox_v7', package='core')\n",
        "from importlib import import_module as load\n"
        "load('.approval_inbox_v7', package='core..invalid')\n",
    ],
    ids=[
        "nonliteral-name",
        "nonliteral-package",
        "missing-package",
        "invalid-level",
        "invalid-package-context",
    ],
)
def test_unresolvable_relative_dynamic_imports_fail_closed(source: str) -> None:
    modules = {"core.approval_inbox_v7": "core/approval_inbox_v7.py"}
    with pytest.raises(evidence.Phase52V7EvidenceError):
        evidence._import_targets("core/loader.py", source, modules)


@pytest.mark.parametrize(
    "loader",
    [
        "import importlib\nimportlib.import_module('core.approval_inbox_v4')\n",
        "__import__('core.approval_inbox_v4')\n",
        "import runpy\nrunpy.run_module('core.approval_inbox_v4')\n",
    ],
    ids=["importlib", "dunder-import", "runpy"],
)
def test_literal_dynamic_approval_imports_are_rejected(loader: str) -> None:
    with tempfile.TemporaryDirectory(
        prefix=".p52-v7-dynamic-import-", dir=evidence.PROJECT
    ) as directory:
        root = Path(directory)
        (root / "core").mkdir()
        (root / "scripts").mkdir()
        (root / "main.py").write_text(loader, encoding="utf-8", newline="\n")
        (root / "ui.py").write_text("\n", encoding="utf-8", newline="\n")
        (root / "scripts" / "launch_onyx.pyw").write_text(
            "import main\n", encoding="utf-8", newline="\n"
        )
        (root / "core" / "__init__.py").write_text(
            "\n", encoding="utf-8", newline="\n"
        )
        (root / "core" / "approval_inbox_v4.py").write_text(
            "\n", encoding="utf-8", newline="\n"
        )
        with pytest.raises(evidence.Phase52V7EvidenceError, match="approval inbox"):
            evidence.live_scan_paths(root)


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
        prefix=".p52-v7-semantic-tamper-", dir=evidence.PROJECT
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
        with pytest.raises(evidence.Phase52V7EvidenceError):
            evidence.validate_semantic_metadata(tampered, junit_timestamp)
