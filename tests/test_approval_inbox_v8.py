from __future__ import annotations

import dataclasses
import threading

import pytest

from core.approval_inbox_v8 import (
    MAX_SNAPSHOT_AGE_MS,
    ApprovalInboxFeatureGateV8,
    ApprovalInboxProjectionV8,
    ApprovalInboxV8ContractError,
    ApprovalInboxV8State,
    ApprovalInboxV8Unavailable,
    DeterministicInboxClockV8,
    HostInboxItemV8,
    HostInboxSnapshotV8,
    HostInboxSourceV8,
    InboxQueryV8,
)


D = {
    "target": "1" * 64,
    "payload": "2" * 64,
    "attachments": "3" * 64,
    "idem": "4" * 64,
}


def item(number: int, **changes: object) -> HostInboxItemV8:
    values: dict[str, object] = {
        "item_id": f"item-{number:03d}",
        "action_request_id": f"request-{number:03d}",
        "principal_id": "owner-primary",
        "session_id": "session-local",
        "workspace_id": "workspace-main",
        "workspace_display": "Cyryx Main",
        "mission_id": "mission-daily",
        "mission_display": "Daily operations",
        "account_id": "account-local",
        "account_display": "Local workspace account",
        "connector_id": "calendar-local",
        "connector_version": "1.0",
        "tool_id": "calendar-tool",
        "operation": "create-draft",
        "environment": "local-draft",
        "reason": f"Prepare reviewed item {number}",
        "target_display": f"Calendar draft {number}",
        "target_digest": f"{number + 10:064x}",
        "payload_summary": f"Create a reversible draft for item {number}",
        "payload_digest": f"{number + 100:064x}",
        "attachment_set_digest": D["attachments"],
        "policy_version": "onyx-policy-1",
        "action_schema_version": "action-1",
        "data_class": "internal",
        "egress": "local-only",
        "effect_summary": "Creates a draft only",
        "reversibility": "reversible",
        "idempotency_summary": f"One draft for request {number}",
        "idempotency_key": f"{number + 200:064x}",
        "verification_plan": "Read the draft back and compare its digest",
        "rollback_plan": "Delete the local draft before any external action",
        "cost_micro": number,
        "currency": "USD",
        "risk": "low",
        "created_at_ms": 10_000 + number,
        "expires_at_ms": 100_000 + number,
        "always_explicit": False,
        "batch_eligible": True,
    }
    values.update(changes)
    return HostInboxItemV8(**values)


class Harness:
    def __init__(
        self, items: tuple[HostInboxItemV8, ...] | None = None, *, enabled: str = "true"
    ):
        self.flag_epoch = 7
        self.source_epoch = 1
        self.items = items if items is not None else (item(1), item(2), item(3))
        self.capture_count = 0
        self.clock = DeterministicInboxClockV8(1_000)
        self.gate = ApprovalInboxFeatureGateV8(
            environ={"ONYX_APPROVAL_INBOX_V8": enabled},
            epoch_reader=lambda: self.flag_epoch,
        )
        self.source = HostInboxSourceV8(
            principal_id="owner-primary",
            session_id="session-local",
            capture_callback=self.capture,
        )
        self.projection = ApprovalInboxProjectionV8(
            gate=self.gate,
            source=self.source,
            clock=self.clock,
        )

    def capture(self) -> HostInboxSnapshotV8:
        self.capture_count += 1
        return HostInboxSnapshotV8(self.source_epoch, 55_000, self.items)


@pytest.mark.parametrize("value", ["true", "TRUE", "1", " true "])
def test_exact_enable_values(value: str) -> None:
    harness = Harness(enabled=value)
    assert harness.projection.state is ApprovalInboxV8State.READY
    assert harness.projection.open_page().total_items == 3


@pytest.mark.parametrize("value", ["", "0", "yes", "on", "enabled", "false"])
def test_default_off_never_calls_source(value: str) -> None:
    harness = Harness(enabled=value)
    assert harness.projection.state is ApprovalInboxV8State.DISABLED
    with pytest.raises(ApprovalInboxV8Unavailable, match="disabled"):
        harness.projection.open_page()
    assert harness.capture_count == 0


def test_flag_is_read_once_but_epoch_change_permanently_revokes() -> None:
    environment = {"ONYX_APPROVAL_INBOX_V8": "true"}
    epoch = [4]
    gate = ApprovalInboxFeatureGateV8(
        environ=environment, epoch_reader=lambda: epoch[0]
    )
    environment["ONYX_APPROVAL_INBOX_V8"] = "false"
    assert gate.state() is ApprovalInboxV8State.READY
    epoch[0] = 5
    assert gate.state() is ApprovalInboxV8State.REVOKED
    epoch[0] = 4
    assert gate.state() is ApprovalInboxV8State.REVOKED


def test_page_contains_complete_safe_review_and_zero_authority() -> None:
    page = Harness().projection.open_page(page_size=2)
    assert page.state is ApprovalInboxV8State.READY
    assert page.total_items == 3
    assert page.next_cursor
    assert not page.authority_granted
    assert not page.approval_action_available
    assert not page.execution_available
    review = page.items[0]
    for field in (
        "action_request_id",
        "action_fingerprint",
        "workspace_display",
        "mission_display",
        "account_display",
        "connector_display",
        "action_display",
        "environment",
        "reason",
        "target_display",
        "target_digest",
        "payload_summary",
        "payload_digest",
        "attachment_set_digest",
        "policy_version",
        "action_schema_version",
        "data_class",
        "egress",
        "effect_summary",
        "reversibility",
        "idempotency_summary",
        "idempotency_identity",
        "verification_plan",
        "rollback_plan",
        "currency",
        "risk",
        "review_proof",
    ):
        assert getattr(review, field)
    assert not review.authority_granted
    assert not review.approval_action_available
    assert not review.execution_available


def test_pagination_is_stable_and_cursor_is_exact() -> None:
    harness = Harness()
    first = harness.projection.open_page(page_size=2)
    second = harness.projection.continue_page(first.next_cursor)
    assert first.offset == 0 and second.offset == 2
    assert {entry.item_id for entry in first.items}.isdisjoint(
        {entry.item_id for entry in second.items}
    )
    assert len(first.items) + len(second.items) == first.total_items
    assert second.next_cursor is None
    token = first.next_cursor
    assert token is not None
    replacement = "A" if token[-1] != "A" else "B"
    with pytest.raises(ApprovalInboxV8ContractError):
        harness.projection.continue_page(token[:-1] + replacement)


def test_identical_reopen_reuses_snapshot_deadline_and_review_proofs() -> None:
    harness = Harness()
    first = harness.projection.open_page(page_size=2)
    harness.clock.advance(50_000)
    second = harness.projection.open_page(page_size=2)
    assert first.snapshot_id == second.snapshot_id
    assert first.created_monotonic_ms == second.created_monotonic_ms
    assert first.deadline_monotonic_ms == second.deadline_monotonic_ms
    assert [entry.review_proof for entry in first.items] == [
        entry.review_proof for entry in second.items
    ]


def test_snapshot_reuse_never_extends_ttl() -> None:
    harness = Harness()
    harness.projection.open_page()
    harness.clock.advance(MAX_SNAPSHOT_AGE_MS + 1)
    with pytest.raises(ApprovalInboxV8Unavailable, match="snapshot-stale"):
        harness.projection.open_page()
    assert harness.projection.state is ApprovalInboxV8State.STALE


def test_clock_rollback_integrity_latches() -> None:
    harness = Harness()
    harness.projection.open_page()
    harness.clock.set_for_test(999)
    with pytest.raises(ApprovalInboxV8Unavailable, match="clock-integrity-latched"):
        harness.projection.open_page()
    assert harness.projection.state is ApprovalInboxV8State.INTEGRITY_LATCHED


def test_source_epoch_rollback_and_equivocation_latch() -> None:
    rollback = Harness()
    rollback.projection.open_page()
    rollback.source_epoch = 2
    rollback.items = (item(4),)
    rollback.projection.open_page()
    rollback.source_epoch = 1
    with pytest.raises(ApprovalInboxV8Unavailable, match="source-integrity-latched"):
        rollback.projection.open_page()
    assert rollback.projection.state is ApprovalInboxV8State.INTEGRITY_LATCHED

    equivocation = Harness()
    equivocation.projection.open_page()
    equivocation.items = (item(9),)
    with pytest.raises(ApprovalInboxV8Unavailable, match="source-integrity-latched"):
        equivocation.projection.open_page()
    assert equivocation.projection.state is ApprovalInboxV8State.INTEGRITY_LATCHED


def test_new_source_epoch_invalidates_all_old_cursors_and_review_proofs() -> None:
    harness = Harness(items=(item(1), item(2), item(3)))
    old = harness.projection.open_page(page_size=1)
    harness.source_epoch = 2
    harness.items = (item(4), item(5))
    new = harness.projection.open_page(page_size=1)
    assert new.snapshot_id != old.snapshot_id
    with pytest.raises(ApprovalInboxV8Unavailable, match="cursor-state-unavailable"):
        harness.projection.continue_page(old.next_cursor)
    with pytest.raises(ApprovalInboxV8Unavailable, match="selection-state-unavailable"):
        harness.projection.preview_calm_batch(
            old.snapshot_id, old.view_digest, _all_selections(old)
        )


def test_feature_epoch_change_during_capture_rejects_callback_output() -> None:
    epoch = [1]

    def rotate() -> HostInboxSnapshotV8:
        epoch[0] = 2
        return HostInboxSnapshotV8(1, 1, (item(1),))

    gate = ApprovalInboxFeatureGateV8(
        environ={"ONYX_APPROVAL_INBOX_V8": "true"}, epoch_reader=lambda: epoch[0]
    )
    projection = ApprovalInboxProjectionV8(
        gate=gate,
        source=HostInboxSourceV8(
            principal_id="owner-primary",
            session_id="session-local",
            capture_callback=rotate,
        ),
        clock=DeterministicInboxClockV8(),
    )
    with pytest.raises(ApprovalInboxV8Unavailable, match="feature-epoch-revoked"):
        projection.open_page()
    assert projection.state is ApprovalInboxV8State.REVOKED


def test_source_exception_is_collapsed_without_secret_cause() -> None:
    def fail() -> HostInboxSnapshotV8:
        raise RuntimeError("password=do-not-leak")

    gate = ApprovalInboxFeatureGateV8(
        environ={"ONYX_APPROVAL_INBOX_V8": "1"}, epoch_reader=lambda: 1
    )
    source = HostInboxSourceV8(
        principal_id="owner-primary", session_id="session-local", capture_callback=fail
    )
    projection = ApprovalInboxProjectionV8(
        gate=gate, source=source, clock=DeterministicInboxClockV8()
    )
    with pytest.raises(ApprovalInboxV8Unavailable) as caught:
        projection.open_page()
    assert str(caught.value) == "source-callback-failed"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_single_flight_callback_is_bounded_and_outside_projection_lock() -> None:
    entered = threading.Event()
    release = threading.Event()
    epoch = [1]

    def blocked_capture() -> HostInboxSnapshotV8:
        entered.set()
        assert release.wait(2)
        return HostInboxSnapshotV8(1, 1, (item(1),))

    gate = ApprovalInboxFeatureGateV8(
        environ={"ONYX_APPROVAL_INBOX_V8": "1"}, epoch_reader=lambda: epoch[0]
    )
    source = HostInboxSourceV8(
        principal_id="owner-primary",
        session_id="session-local",
        capture_callback=blocked_capture,
    )
    projection = ApprovalInboxProjectionV8(
        gate=gate, source=source, clock=DeterministicInboxClockV8()
    )
    failures: list[BaseException] = []

    def run() -> None:
        try:
            projection.open_page()
        except BaseException as error:  # pragma: no cover - assertion captures it
            failures.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(1)
    # State can be inspected while capture is blocked: callback is not under
    # the projection lock.
    assert projection.state is ApprovalInboxV8State.READY
    with pytest.raises(ApprovalInboxV8Unavailable, match="source-single-flight-busy"):
        projection.open_page()
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert not failures


def _all_selections(page) -> tuple[tuple[str, str], ...]:
    return tuple((entry.item_id, entry.review_proof) for entry in page.items)


def test_calm_batch_is_order_independent_idempotent_and_non_authoritative() -> None:
    harness = Harness(items=(item(1), item(2)))
    page = harness.projection.open_page(query=InboxQueryV8(batch_only=True))
    selections = _all_selections(page)
    first = harness.projection.preview_calm_batch(
        page.snapshot_id, page.view_digest, selections
    )
    second = harness.projection.preview_calm_batch(
        page.snapshot_id, page.view_digest, tuple(reversed(selections))
    )
    assert first.preview_digest == second.preview_digest
    assert first.items == second.items
    assert first.revalidation_required
    assert not first.authority_granted
    assert not first.approval_action_available
    assert not first.execution_available


def test_handoff_contains_only_review_identifiers_and_revalidation_instruction() -> (
    None
):
    harness = Harness(items=(item(1), item(2)))
    page = harness.projection.open_page()
    handoff = harness.projection.handoff_calm_batch(
        page.snapshot_id, page.view_digest, _all_selections(page)
    )
    assert (
        handoff.instruction == "future-approval-must-re-resolve-all-host-action-fields"
    )
    assert handoff.revalidation_required
    assert not handoff.authority_granted
    assert not handoff.approval_action_available
    assert not handoff.execution_available
    forbidden = {
        "target_digest",
        "payload_digest",
        "idempotency_identity",
        "review_proofs",
    }
    assert forbidden.isdisjoint(field.name for field in dataclasses.fields(handoff))


@pytest.mark.parametrize(
    "changes",
    [
        {"risk": "high"},
        {"risk": "critical"},
        {"always_explicit": True},
        {"batch_eligible": False},
    ],
)
def test_ineligible_items_never_enter_calm_batch(changes: dict[str, object]) -> None:
    harness = Harness(items=(item(1, **changes),))
    page = harness.projection.open_page()
    with pytest.raises(ApprovalInboxV8ContractError, match="not calm-batch eligible"):
        harness.projection.preview_calm_batch(
            page.snapshot_id, page.view_digest, _all_selections(page)
        )
    filtered = harness.projection.open_page(query=InboxQueryV8(batch_only=True))
    assert filtered.total_items == 0


def test_hidden_unreturned_cross_view_and_tampered_proofs_fail() -> None:
    harness = Harness(items=(item(1), item(2), item(3)))
    first = harness.projection.open_page(page_size=1)
    second = harness.projection.open_page(
        query=InboxQueryV8(workspace_id="workspace-main"), page_size=1
    )
    selection = _all_selections(first)
    with pytest.raises(ApprovalInboxV8ContractError, match="not reviewed in this view"):
        harness.projection.preview_calm_batch(
            second.snapshot_id, second.view_digest, selection
        )
    proof = selection[0][1]
    with pytest.raises(ApprovalInboxV8ContractError):
        harness.projection.preview_calm_batch(
            first.snapshot_id,
            first.view_digest,
            ((selection[0][0], proof[:-1] + ("A" if proof[-1] != "A" else "B")),),
        )
    # The second item exists but its proof was not returned on the first page.
    with pytest.raises(ApprovalInboxV8ContractError, match="not reviewed in this view"):
        harness.projection.preview_calm_batch(
            first.snapshot_id,
            first.view_digest,
            (("item-002", selection[0][1]),),
        )


def test_duplicate_item_request_fingerprint_and_idempotency_identity_reject() -> None:
    # Duplicate source item id is rejected at capture.
    duplicate_id = Harness(items=(item(1), item(1, action_request_id="request-002")))
    with pytest.raises(ApprovalInboxV8ContractError, match="duplicate item_id"):
        duplicate_id.projection.open_page()

    # Duplicate request ID with distinct actions is rejected at batch selection.
    duplicate_request = Harness(
        items=(item(1), item(2, action_request_id="request-001"))
    )
    page = duplicate_request.projection.open_page()
    with pytest.raises(
        ApprovalInboxV8ContractError, match="duplicate action_request_id"
    ):
        duplicate_request.projection.preview_calm_batch(
            page.snapshot_id, page.view_digest, _all_selections(page)
        )

    # Same meaningful action, but distinct row/request/idempotency identity.
    base = item(1)
    same_action = item(
        2,
        target_digest=base.target_digest,
        payload_digest=base.payload_digest,
        idempotency_key=base.idempotency_key,
        cost_micro=base.cost_micro,
        expires_at_ms=base.expires_at_ms,
    )
    duplicate_fingerprint = Harness(items=(base, same_action))
    page = duplicate_fingerprint.projection.open_page()
    with pytest.raises(
        ApprovalInboxV8ContractError, match="duplicate action_fingerprint"
    ):
        duplicate_fingerprint.projection.preview_calm_batch(
            page.snapshot_id, page.view_digest, _all_selections(page)
        )

    duplicate_idempotency = Harness(
        items=(item(1), item(2, idempotency_key=item(1).idempotency_key))
    )
    page = duplicate_idempotency.projection.open_page()
    with pytest.raises(
        ApprovalInboxV8ContractError, match="duplicate idempotency_identity"
    ):
        duplicate_idempotency.projection.preview_calm_batch(
            page.snapshot_id, page.view_digest, _all_selections(page)
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("principal_id", "other-owner"),
        ("session_id", "other-session"),
        ("payload_summary", "token=secret-value"),
        ("risk", "unknown"),
        ("currency", "usd"),
        ("expires_at_ms", 1),
        ("batch_eligible", 1),
    ],
)
def test_malformed_or_mismatched_host_fields_fail_closed(
    field: str, value: object
) -> None:
    harness = Harness(items=(item(1, **{field: value}),))
    with pytest.raises(ApprovalInboxV8ContractError):
        harness.projection.open_page()


def test_public_surface_has_no_authority_or_mutation_methods() -> None:
    public = {
        name for name in dir(ApprovalInboxProjectionV8) if not name.startswith("_")
    }
    assert public == {
        "continue_page",
        "handoff_calm_batch",
        "open_page",
        "preview_calm_batch",
        "state",
    }
    forbidden = {
        "approve",
        "deny",
        "revoke",
        "grant",
        "dispatch",
        "execute",
        "persist",
        "save",
    }
    assert not public.intersection(forbidden)
