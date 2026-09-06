from __future__ import annotations

import hashlib
import inspect
import threading
from pathlib import Path

import pytest

from core import approval_inbox_v1 as inbox


ON = {inbox.APPROVAL_INBOX_FLAG: "true"}
OFF = {inbox.APPROVAL_INBOX_FLAG: "false"}


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def item(
    item_id: str = "approval-one",
    *,
    workspace_id: str = "cyryx-main",
    mission_id: str | None = "mission-one",
    risk: str = "low",
    always_explicit: bool = False,
    batch_eligible: bool = True,
    created_at_ms: int = 100,
    expires_at_ms: int = 1_000,
    canary: str | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {
        "item_id": item_id,
        "workspace_id": workspace_id,
        "workspace_display": "Cyryx Labs",
        "account_display": "Operations account",
        "mission_id": mission_id,
        "mission_display": "Daily operations",
        "reason": "Prepare the reviewed daily work item",
        "action": "Create a reversible provider draft",
        "target_display": "Named provider draft folder",
        "target_digest": digest(f"target-{item_id}"),
        "payload_summary": "Draft with the reviewed title and summary; no raw body",
        "payload_digest": digest(f"payload-{item_id}"),
        "data_class": "internal",
        "egress": "named-account",
        "effect_summary": "Creates one non-live draft for later review",
        "reversibility": "reversible",
        "idempotency_summary": "The exact request key prevents duplicate drafts",
        "idempotency_key": digest(f"idempotency-{item_id}"),
        "verification_plan": "Read back the draft metadata and compare its digest",
        "rollback_plan": "Delete the non-live draft after a separate exact approval",
        "cost_micro": 25_000,
        "currency": "USD",
        "risk": risk,
        "created_at_ms": created_at_ms,
        "expires_at_ms": expires_at_ms,
        "always_explicit": always_explicit,
        "batch_eligible": batch_eligible,
    }
    if canary is not None:
        values["payload_summary"] = canary
    return values


def snapshot(
    items: tuple[dict[str, object], ...] | list[dict[str, object]] | None = None,
    *,
    revision: str = "revision-one",
    epoch: int = 1,
    captured_at_ms: int = 200,
    valid_until_ms: int = 900,
    audit_healthy: bool = True,
    session_active: bool = True,
    kill_switch: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": inbox.INBOX_SCHEMA_VERSION,
        "source_revision": revision,
        "source_epoch": epoch,
        "principal_id": "owner-main",
        "session_id": "session-main",
        "captured_at_ms": captured_at_ms,
        "valid_until_ms": valid_until_ms,
        "audit_healthy": audit_healthy,
        "session_active": session_active,
        "kill_switch": kill_switch,
        "items": list(items if items is not None else (item(),)),
    }


def service(callback):
    source = inbox._host_source_for_testing(callback, "owner-main", "session-main")
    return inbox.ApprovalInbox(source)


def test_flag_is_strict_and_disabled_mode_never_calls_source() -> None:
    calls = 0

    def source():
        nonlocal calls
        calls += 1
        return snapshot()

    projection = service(source)
    for raw in ("", "yes", "on", "enabled", "2", " truex "):
        page = projection.open_page(environ={inbox.APPROVAL_INBOX_FLAG: raw})
        assert page.status == "disabled"
        assert page.items == ()
        assert page.read_only is True
        assert page.authority_granted is False
    assert calls == 0
    assert projection.open_page(environ=ON).status == "ready"
    assert calls == 1


def test_trusted_source_and_items_cannot_be_caller_constructed() -> None:
    with pytest.raises(TypeError, match="trusted host"):
        inbox.HostApprovalSource(object(), lambda: snapshot(), "owner-main", "session-main")
    with pytest.raises(TypeError, match="host-materialized"):
        inbox.ApprovalInboxItem(object(), item())
    with pytest.raises(inbox.ApprovalInboxContractError, match="concrete host"):
        inbox.ApprovalInbox(lambda: snapshot())  # type: ignore[arg-type]
    source = inbox._host_source_for_testing(lambda: snapshot(), "owner-main", "session-main")
    with pytest.raises(TypeError, match="not copyable"):
        source.__copy__()
    with pytest.raises(AttributeError, match="immutable"):
        source._callback = lambda: snapshot()  # type: ignore[misc]
    assert "_host_source_for_testing" not in inbox.__all__


def test_model_style_authority_fields_and_raw_payload_are_rejected() -> None:
    for injected in ("approved", "approval_id", "raw_target", "raw_payload", "grant"):
        malicious = item()
        malicious[injected] = True
        with pytest.raises(inbox.ApprovalInboxContractError, match="fields are not exact"):
            service(lambda malicious=malicious: snapshot((malicious,))).open_page(environ=ON)


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
def test_secret_like_material_is_rejected_from_every_recoverable_display_field(field: str) -> None:
    malicious = item()
    malicious[field] = "api_key=sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
    with pytest.raises(inbox.ApprovalInboxContractError, match="secret-like"):
        service(lambda: snapshot((malicious,))).open_page(environ=ON)


@pytest.mark.parametrize("field", ["item_id", "workspace_id", "mission_id"])
def test_secret_like_or_pathish_identifiers_are_rejected(field: str) -> None:
    for value in ("../workspace", "ghp-abcdefghijklmnopqrstuvwxyz0123456789", "owner@example.com"):
        malicious = item()
        malicious[field] = value
        with pytest.raises(inbox.ApprovalInboxContractError):
            service(lambda malicious=malicious: snapshot((malicious,))).open_page(environ=ON)


def test_workspace_pattern_exactly_matches_authoritative_registry_shape() -> None:
    for valid in ("abc", "cyryx-main", "legacy-default"):
        page = service(lambda valid=valid: snapshot((item(workspace_id=valid),))).open_page(environ=ON)
        assert page.items[0].workspace_id == valid
    for invalid in ("ABc", "ab", "a_b", "a.b", "a/b", "-abc"):
        with pytest.raises(inbox.ApprovalInboxContractError, match="workspace_id"):
            service(lambda invalid=invalid: snapshot((item(workspace_id=invalid),))).open_page(environ=ON)


def test_page_exposes_every_required_safe_review_field_and_no_raw_fields() -> None:
    record = service(lambda: snapshot()).open_page(environ=ON).items[0]
    expected = inbox._ITEM_FIELDS | {"item_digest"}
    assert expected <= set(record.__slots__)
    for name in expected:
        value = getattr(record, name)
        assert value is not None
    assert not hasattr(record, "raw_target")
    assert not hasattr(record, "raw_payload")
    assert record.item_digest == digest_from_payload(record.canonical_payload())
    with pytest.raises(AttributeError, match="immutable"):
        record.reason = "changed"  # type: ignore[misc]


def digest_from_payload(payload: object) -> str:
    import json

    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_snapshot_digest_is_deterministic_and_input_order_independent() -> None:
    first = item("approval-one")
    second = item("approval-two")
    one = service(lambda: snapshot((first, second))).open_page(environ=ON)
    two = service(lambda: snapshot((second, first))).open_page(environ=ON)
    assert one.snapshot_version == inbox.SNAPSHOT_SCHEMA_VERSION
    assert one.snapshot_digest == two.snapshot_digest
    assert [value.item_id for value in one.items] == ["approval-one", "approval-two"]
    assert one.snapshot_token != two.snapshot_token  # process/session-bound tokens


def test_stable_sorting_and_exact_filters() -> None:
    values = (
        item("approval-low", workspace_id="cyryx-main", risk="low", created_at_ms=100),
        item("approval-medium", workspace_id="client-one", risk="medium", created_at_ms=110),
        item(
            "approval-high",
            workspace_id="cyryx-main",
            risk="high",
            always_explicit=True,
            batch_eligible=False,
            created_at_ms=120,
        ),
    )
    projection = service(lambda: snapshot(values))
    page = projection.open_page(
        query=inbox.InboxQuery(
            workspace_id="cyryx-main", risks=("high", "low"), sort="risk-desc"
        ),
        environ=ON,
    )
    assert [value.item_id for value in page.items] == ["approval-high", "approval-low"]
    batchable = projection.open_page(
        query=inbox.InboxQuery(batch_eligible=True, sort="item-id-asc"), environ=ON
    )
    assert [value.item_id for value in batchable.items] == ["approval-low", "approval-medium"]


def test_pagination_is_exact_set_without_duplicates_or_omissions() -> None:
    values = tuple(item(f"approval-{number:02d}", created_at_ms=100 + number) for number in range(17))
    projection = service(lambda: snapshot(values))
    page = projection.open_page(page_size=4, query=inbox.InboxQuery(sort="item-id-asc"), environ=ON)
    seen = [value.item_id for value in page.items]
    digest_value = page.snapshot_digest
    while page.next_cursor:
        page = projection.continue_page(page.next_cursor, environ=ON)
        assert page.snapshot_digest == digest_value
        seen.extend(value.item_id for value in page.items)
    assert seen == sorted(value["item_id"] for value in values)
    assert len(seen) == len(set(seen)) == 17


def test_tampered_cursor_and_stale_cursor_fail_before_source_callback() -> None:
    calls = 0

    def source():
        nonlocal calls
        calls += 1
        return snapshot((item("approval-one"), item("approval-two")))

    projection = service(source)
    page = projection.open_page(page_size=1, environ=ON)
    assert page.next_cursor
    tampered = page.next_cursor[:-1] + ("0" if page.next_cursor[-1] != "0" else "1")
    with pytest.raises(inbox.ApprovalInboxStale, match="invalid"):
        projection.continue_page(tampered, environ=ON)
    assert calls == 1
    replacement = service(source)
    with pytest.raises(inbox.ApprovalInboxStale, match="invalid"):
        replacement.continue_page(page.next_cursor, environ=ON)
    assert calls == 1


def test_source_drift_invalidates_cursor_without_mixing_pages() -> None:
    state = {"snapshot": snapshot((item("approval-one"), item("approval-two")))}
    projection = service(lambda: state["snapshot"])
    page = projection.open_page(page_size=1, environ=ON)
    assert page.next_cursor
    state["snapshot"] = snapshot(
        (item("approval-one"), item("approval-three")),
        revision="revision-two",
        epoch=2,
        captured_at_ms=210,
    )
    with pytest.raises(inbox.ApprovalInboxStale, match="drifted"):
        projection.continue_page(page.next_cursor, environ=ON)


def test_same_epoch_content_or_time_drift_is_rejected() -> None:
    state = {"snapshot": snapshot()}
    projection = service(lambda: state["snapshot"])
    projection.open_page(environ=ON)
    state["snapshot"] = snapshot(
        (item("approval-two"),), revision="revision-one", epoch=1, captured_at_ms=200
    )
    with pytest.raises(inbox.ApprovalInboxStale, match="without advancing"):
        projection.open_page(environ=ON)

    state["snapshot"] = snapshot(revision="revision-two", epoch=2, captured_at_ms=210)
    projection.open_page(environ=ON)
    state["snapshot"] = snapshot(revision="revision-three", epoch=3, captured_at_ms=205)
    with pytest.raises(inbox.ApprovalInboxStale, match="clock moved backwards"):
        projection.open_page(environ=ON)


def test_expiry_and_epoch_rollback_fail_closed() -> None:
    state = {"snapshot": snapshot((item("approval-one"), item("approval-two")))}
    projection = service(lambda: state["snapshot"])
    page = projection.open_page(page_size=1, environ=ON)
    assert page.next_cursor
    state["snapshot"] = snapshot(
        (item("approval-one"), item("approval-two")),
        captured_at_ms=1_000,
        valid_until_ms=1_100,
    )
    with pytest.raises(inbox.ApprovalInboxStale):
        projection.continue_page(page.next_cursor, environ=ON)

    state["snapshot"] = snapshot(revision="revision-two", epoch=2, captured_at_ms=210)
    projection.open_page(environ=ON)
    state["snapshot"] = snapshot(revision="revision-one", epoch=1, captured_at_ms=220)
    with pytest.raises(inbox.ApprovalInboxStale, match="backwards"):
        projection.open_page(environ=ON)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("audit_healthy", False, "audit"),
        ("session_active", False, "inactive"),
        ("kill_switch", True, "kill"),
    ],
)
def test_unhealthy_host_state_fails_closed(field: str, value: bool, reason: str) -> None:
    arguments = {field: value}
    with pytest.raises(inbox.ApprovalInboxUnavailable, match=reason):
        service(lambda: snapshot(**arguments)).open_page(environ=ON)


def test_unknown_schema_fields_types_and_duplicate_authority_records_fail_closed() -> None:
    malformed = snapshot()
    malformed["approved"] = True
    with pytest.raises(inbox.ApprovalInboxContractError, match="fields are not exact"):
        service(lambda: malformed).open_page(environ=ON)
    wrong = snapshot()
    wrong["schema_version"] = 99
    with pytest.raises(inbox.ApprovalInboxContractError, match="unknown"):
        service(lambda: wrong).open_page(environ=ON)
    duplicate = snapshot((item("approval-one"), item("approval-one")))
    with pytest.raises(inbox.ApprovalInboxContractError, match="IDs are duplicated"):
        service(lambda: duplicate).open_page(environ=ON)


def test_source_principal_or_session_drift_fails_closed() -> None:
    for field in ("principal_id", "session_id"):
        altered = snapshot()
        altered[field] = "attacker-session"
        with pytest.raises(inbox.ApprovalInboxUnavailable, match="binding drifted"):
            service(lambda altered=altered: altered).open_page(environ=ON)


def test_calm_batch_is_canonical_read_only_and_reorder_invariant() -> None:
    values = (item("approval-one"), item("approval-two"), item("approval-three"))
    projection = service(lambda: snapshot(values))
    page = projection.open_page(environ=ON)
    first = projection.preview_calm_batch(
        page.snapshot_token, ["approval-three", "approval-one"], environ=ON
    )
    reordered = projection.preview_calm_batch(
        page.snapshot_token, ["approval-one", "approval-three"], environ=ON
    )
    assert first == reordered
    assert [value.item_id for value in first.items] == ["approval-one", "approval-three"]
    assert first.read_only is True
    assert first.approval_action_available is False
    assert first.authority_granted is False


def test_batch_add_remove_and_substitute_change_manifest_digest() -> None:
    values = (item("approval-one"), item("approval-two"), item("approval-three"))
    projection = service(lambda: snapshot(values))
    page = projection.open_page(environ=ON)

    def preview(*ids: str) -> str:
        return projection.preview_calm_batch(page.snapshot_token, ids, environ=ON).manifest_digest

    base = preview("approval-one", "approval-two")
    assert preview("approval-one") != base
    assert preview("approval-one", "approval-two", "approval-three") != base
    assert preview("approval-one", "approval-three") != base


@pytest.mark.parametrize(
    "risk,always_explicit,batch_eligible",
    [
        ("high", False, False),
        ("critical", True, False),
        ("medium", True, False),
        ("low", False, False),
    ],
)
def test_high_always_explicit_and_ineligible_items_cannot_enter_batch(
    risk: str, always_explicit: bool, batch_eligible: bool
) -> None:
    value = item(
        "approval-blocked",
        risk=risk,
        always_explicit=always_explicit,
        batch_eligible=batch_eligible,
    )
    projection = service(lambda: snapshot((value,)))
    page = projection.open_page(environ=ON)
    with pytest.raises(inbox.ApprovalInboxContractError, match="ineligible"):
        projection.preview_calm_batch(page.snapshot_token, ("approval-blocked",), environ=ON)


def test_host_cannot_mark_high_or_always_explicit_item_batch_eligible() -> None:
    for risk, explicit in (("high", False), ("critical", False), ("low", True)):
        value = item(risk=risk, always_explicit=explicit, batch_eligible=True)
        with pytest.raises(inbox.ApprovalInboxContractError, match="cannot be batch"):
            service(lambda value=value: snapshot((value,))).open_page(environ=ON)


def test_batch_requires_finite_exact_ids_and_forbids_wildcards_categories() -> None:
    projection = service(lambda: snapshot())
    page = projection.open_page(environ=ON)
    for selection in ((), ("*",), ("all-low-risk",), ("approval-*",), ("approval-unknown",)):
        with pytest.raises((inbox.ApprovalInboxContractError, inbox.ApprovalInboxStale)):
            projection.preview_calm_batch(page.snapshot_token, selection, environ=ON)
    with pytest.raises(inbox.ApprovalInboxContractError, match="duplicates"):
        projection.preview_calm_batch(
            page.snapshot_token, ("approval-one", "approval-one"), environ=ON
        )


def test_batch_selection_is_bound_to_item_digest_idempotency_and_snapshot() -> None:
    projection = service(lambda: snapshot())
    page = projection.open_page(environ=ON)
    preview = projection.preview_calm_batch(page.snapshot_token, ("approval-one",), environ=ON)
    record = page.items[0]
    assert preview.items[0].item_digest == record.item_digest
    assert preview.items[0].idempotency_key == record.idempotency_key
    assert preview.snapshot_digest == page.snapshot_digest


def test_batch_token_rejects_source_drift_and_disabled_mode_calls_no_source() -> None:
    calls = 0
    state = {"snapshot": snapshot()}

    def source():
        nonlocal calls
        calls += 1
        return state["snapshot"]

    projection = service(source)
    page = projection.open_page(environ=ON)
    with pytest.raises(inbox.ApprovalInboxDisabled):
        projection.preview_calm_batch(page.snapshot_token, ("approval-one",), environ=OFF)
    assert calls == 1
    state["snapshot"] = snapshot(revision="revision-two", epoch=2, captured_at_ms=210)
    with pytest.raises(inbox.ApprovalInboxStale, match="drifted"):
        projection.preview_calm_batch(page.snapshot_token, ("approval-one",), environ=ON)


def test_all_host_callbacks_run_outside_internal_lock() -> None:
    holder: dict[str, inbox.ApprovalInbox] = {}
    lock_was_available: list[bool] = []

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
        lock_was_available.append(outcome == [True])
        return snapshot((item("approval-one"), item("approval-two")))

    holder["service"] = service(source)
    page = holder["service"].open_page(page_size=1, environ=ON)
    holder["service"].continue_page(page.next_cursor, environ=ON)
    holder["service"].preview_calm_batch(
        page.snapshot_token, ("approval-one",), environ=ON
    )
    assert lock_was_available == [True, True, True]


def test_concurrent_continuations_never_mix_drifted_source_pages() -> None:
    state = {"snapshot": snapshot((item("approval-one"), item("approval-two")))}
    projection = service(lambda: state["snapshot"])
    page = projection.open_page(page_size=1, environ=ON)
    state["snapshot"] = snapshot(
        (item("approval-one"), item("approval-three")),
        revision="revision-two",
        epoch=2,
        captured_at_ms=210,
    )
    barrier = threading.Barrier(3)
    results: list[str] = []

    def worker():
        barrier.wait()
        try:
            projection.continue_page(page.next_cursor, environ=ON)
        except inbox.ApprovalInboxStale:
            results.append("stale")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)
    assert sorted(results) == ["stale", "stale"]


def test_collection_page_batch_snapshot_and_string_limits() -> None:
    too_many = tuple(item(f"approval-{number:03d}") for number in range(inbox.MAX_ITEMS + 1))
    with pytest.raises(inbox.ApprovalInboxContractError, match="collection"):
        service(lambda: snapshot(too_many)).open_page(environ=ON)
    projection = service(lambda: snapshot())
    with pytest.raises(inbox.ApprovalInboxContractError, match="page_size"):
        projection.open_page(page_size=inbox.MAX_PAGE_SIZE + 1, environ=ON)
    oversized = item()
    oversized["reason"] = "a" * (inbox.MAX_SUMMARY + 1)
    with pytest.raises(inbox.ApprovalInboxContractError, match="reason"):
        service(lambda: snapshot((oversized,))).open_page(environ=ON)
    overlong_item = item(expires_at_ms=100 + inbox.MAX_ITEM_LIFETIME_MS + 1)
    with pytest.raises(inbox.ApprovalInboxContractError, match="lifetime"):
        service(lambda: snapshot((overlong_item,), valid_until_ms=900)).open_page(environ=ON)
    with pytest.raises(inbox.ApprovalInboxContractError, match="lifetime"):
        service(
            lambda: snapshot(valid_until_ms=200 + inbox.MAX_SNAPSHOT_LIFETIME_MS + 1)
        ).open_page(environ=ON)
    page = projection.open_page(environ=ON)
    with pytest.raises(inbox.ApprovalInboxContractError, match="bound"):
        projection.preview_calm_batch(
            page.snapshot_token,
            tuple(f"approval-{number:03d}" for number in range(inbox.MAX_BATCH_ITEMS + 1)),
            environ=ON,
        )

    state = {"epoch": 1}

    def rolling():
        epoch = state["epoch"]
        return snapshot(revision=f"revision-{epoch:02d}", epoch=epoch)

    bounded = service(rolling)
    for epoch in range(1, inbox.MAX_SNAPSHOTS + 3):
        state["epoch"] = epoch
        bounded.open_page(environ=ON)
    assert len(bounded._snapshots) == inbox.MAX_SNAPSHOTS


def test_no_mutation_authority_or_grant_import_surface() -> None:
    forbidden = {"approve", "deny", "revoke", "dispatch", "execute", "persist", "write", "delete"}
    public_methods = {
        name
        for name, value in inspect.getmembers(inbox.ApprovalInbox, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == {"open_page", "continue_page", "preview_calm_batch"}
    assert not (public_methods & forbidden)
    source = Path(inbox.__file__).read_text(encoding="utf-8")
    assert "session_grants_v11" not in source
    assert "sqlite" not in source
    assert "Path(" not in source
    assert inbox.GRANT_INSPECTOR_STATUS == "omitted-phase5-2b-no-r11-import"


def test_no_startup_dashboard_provider_or_runtime_wiring() -> None:
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
        assert "approval_inbox_v1" not in text
        assert inbox.APPROVAL_INBOX_FLAG not in text


def test_restart_is_empty_and_old_tokens_cannot_be_restored() -> None:
    calls = 0

    def source():
        nonlocal calls
        calls += 1
        return snapshot((item("approval-one"), item("approval-two")))

    first = service(source)
    page = first.open_page(page_size=1, environ=ON)
    assert page.next_cursor and page.snapshot_token
    restarted = service(source)
    assert restarted._snapshots == {}
    with pytest.raises(inbox.ApprovalInboxStale, match="invalid"):
        restarted.continue_page(page.next_cursor, environ=ON)
    with pytest.raises(inbox.ApprovalInboxStale, match="invalid"):
        restarted.preview_calm_batch(page.snapshot_token, ("approval-one",), environ=ON)
    assert calls == 1


def test_r11_accepted_anchor_and_frozen_roots_remain_exact() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = {
        "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256": "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071",
        "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R11-001.sha256": "0253aba6b0fed67bbac6b1eda55ea32a9928f44b036b2fbc0c5daec78e0b33d7",
        "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256": "36fb198e27ebb7e8e8bb97885d8a823d2a291ed573da3d5513d950715b113bb0",
        "docs/onyx/acceptance/VE-P51-GRANTS-R11-E6-001.md": "ff703416675653b4f1611e7f9ee633fac974c3bdf4225a16d84f302233b824d4",
    }
    for relative, wanted in expected.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == wanted
