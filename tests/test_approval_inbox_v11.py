from __future__ import annotations

import dataclasses
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading

import pytest

from scripts import verify_phase5_approval_inbox_v11 as parent_verifier
from scripts import verify_phase5_approval_inbox_v11_worker as evidence_worker
from scripts import phase5_approval_inbox_v11_historical_projection as historical

from core.approval_inbox_v11 import (
    MAX_SNAPSHOT_AGE_MS,
    ApprovalInboxFeatureGateV11,
    ApprovalInboxProjectionV11,
    ApprovalInboxV11ContractError,
    ApprovalInboxV11State,
    ApprovalInboxV11Unavailable,
    DeterministicInboxClockV11,
    HostInboxItemV11,
    HostInboxSnapshotV11,
    HostInboxSourceV11,
    InboxQueryV11,
)


D = {
    "target": "1" * 64,
    "payload": "2" * 64,
    "attachments": "3" * 64,
    "idem": "4" * 64,
}


def item(number: int, **changes: object) -> HostInboxItemV11:
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
    return HostInboxItemV11(**values)


class Harness:
    def __init__(
        self,
        items: tuple[HostInboxItemV11, ...] | None = None,
        *,
        enabled: str = "true",
    ):
        self.flag_epoch = 7
        self.source_epoch = 1
        self.items = items if items is not None else (item(1), item(2), item(3))
        self.capture_count = 0
        self.clock = DeterministicInboxClockV11(1_000)
        self.gate = ApprovalInboxFeatureGateV11(
            environ={"ONYX_APPROVAL_INBOX_V11": enabled},
            epoch_reader=lambda: self.flag_epoch,
        )
        self.source = HostInboxSourceV11(
            principal_id="owner-primary",
            session_id="session-local",
            capture_callback=self.capture,
        )
        self.projection = ApprovalInboxProjectionV11(
            gate=self.gate,
            source=self.source,
            clock=self.clock,
        )

    def capture(self) -> HostInboxSnapshotV11:
        self.capture_count += 1
        return HostInboxSnapshotV11(self.source_epoch, 55_000, self.items)


class EpochInterlock:
    """Block one chosen callback after its epoch value has been captured."""

    def __init__(self, epoch: int = 7) -> None:
        self.epoch = epoch
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_call = 0
        self._calls: dict[int, int] = {}
        self._lock = threading.Lock()

    def arm(self, call: int) -> None:
        self.block_call = call

    def __call__(self) -> int:
        ident = threading.get_ident()
        value = self.epoch
        with self._lock:
            count = self._calls.get(ident, 0) + 1
            self._calls[ident] = count
            should_block = (
                threading.current_thread().name == "v11-interleaving"
                and count == self.block_call
            )
        if should_block:
            self.entered.set()
            assert self.release.wait(3)
        return value


def _thread_call(callable_):
    results: list[object] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            results.append(callable_())
        except BaseException as error:  # pragma: no cover - inspected by caller
            failures.append(error)

    thread = threading.Thread(target=run, name="v11-interleaving")
    thread.start()
    return thread, results, failures


@pytest.mark.parametrize("value", ["true", "TRUE", "1", " true "])
def test_exact_enable_values(value: str) -> None:
    harness = Harness(enabled=value)
    assert harness.projection.state is ApprovalInboxV11State.READY
    assert harness.projection.open_page().total_items == 3


@pytest.mark.parametrize("value", ["", "0", "yes", "on", "enabled", "false"])
def test_default_off_never_calls_source(value: str) -> None:
    harness = Harness(enabled=value)
    assert harness.projection.state is ApprovalInboxV11State.DISABLED
    with pytest.raises(ApprovalInboxV11Unavailable, match="disabled"):
        harness.projection.open_page()
    assert harness.capture_count == 0


def test_flag_is_read_once_but_epoch_change_permanently_revokes() -> None:
    environment = {"ONYX_APPROVAL_INBOX_V11": "true"}
    epoch = [4]
    gate = ApprovalInboxFeatureGateV11(
        environ=environment, epoch_reader=lambda: epoch[0]
    )
    environment["ONYX_APPROVAL_INBOX_V11"] = "false"
    assert gate.state() is ApprovalInboxV11State.READY
    epoch[0] = 5
    assert gate.state() is ApprovalInboxV11State.REVOKED
    epoch[0] = 4
    assert gate.state() is ApprovalInboxV11State.REVOKED


def test_gate_honors_completed_revocation_after_stale_epoch_callback() -> None:
    interlock = EpochInterlock(4)
    gate = ApprovalInboxFeatureGateV11(
        environ={"ONYX_APPROVAL_INBOX_V11": "true"}, epoch_reader=interlock
    )
    interlock.arm(1)
    thread, results, failures = _thread_call(gate.state)
    assert interlock.entered.wait(1)
    interlock.epoch = 5
    assert gate.state() is ApprovalInboxV11State.REVOKED
    interlock.release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert not failures
    assert results == [ApprovalInboxV11State.REVOKED]


def test_projection_state_cannot_publish_ready_after_completed_revocation() -> None:
    interlock = EpochInterlock()
    gate = ApprovalInboxFeatureGateV11(
        environ={"ONYX_APPROVAL_INBOX_V11": "true"}, epoch_reader=interlock
    )
    projection = ApprovalInboxProjectionV11(
        gate=gate,
        source=HostInboxSourceV11(
            principal_id="owner-primary",
            session_id="session-local",
            capture_callback=lambda: HostInboxSnapshotV11(1, 1, (item(1),)),
        ),
        clock=DeterministicInboxClockV11(),
    )
    interlock.arm(1)
    thread, results, failures = _thread_call(lambda: projection.state)
    assert interlock.entered.wait(1)
    interlock.epoch += 1
    assert gate.state() is ApprovalInboxV11State.REVOKED
    interlock.release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert not failures
    assert results == [ApprovalInboxV11State.REVOKED]


def test_page_contains_complete_safe_review_and_zero_authority() -> None:
    page = Harness().projection.open_page(page_size=2)
    assert page.state is ApprovalInboxV11State.READY
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
    with pytest.raises(ApprovalInboxV11ContractError):
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
    with pytest.raises(ApprovalInboxV11Unavailable, match="snapshot-stale"):
        harness.projection.open_page()
    assert harness.projection.state is ApprovalInboxV11State.STALE


def test_clock_rollback_integrity_latches() -> None:
    harness = Harness()
    harness.projection.open_page()
    harness.clock.set_for_test(999)
    with pytest.raises(ApprovalInboxV11Unavailable, match="clock-integrity-latched"):
        harness.projection.open_page()
    assert harness.projection.state is ApprovalInboxV11State.INTEGRITY_LATCHED


def test_source_epoch_rollback_and_equivocation_latch() -> None:
    rollback = Harness()
    rollback.projection.open_page()
    rollback.source_epoch = 2
    rollback.items = (item(4),)
    rollback.projection.open_page()
    rollback.source_epoch = 1
    with pytest.raises(ApprovalInboxV11Unavailable, match="source-integrity-latched"):
        rollback.projection.open_page()
    assert rollback.projection.state is ApprovalInboxV11State.INTEGRITY_LATCHED

    equivocation = Harness()
    equivocation.projection.open_page()
    equivocation.items = (item(9),)
    with pytest.raises(ApprovalInboxV11Unavailable, match="source-integrity-latched"):
        equivocation.projection.open_page()
    assert equivocation.projection.state is ApprovalInboxV11State.INTEGRITY_LATCHED


def test_ten_thousand_monotonic_epochs_retain_constant_integrity_state() -> None:
    harness = Harness(items=(item(1),))
    projection_size = sys.getsizeof(harness.projection)
    first_digest_size: int | None = None
    last_page = None

    for epoch in range(1, 10_001):
        harness.source_epoch = epoch
        last_page = harness.projection.open_page()
        if first_digest_size is None:
            first_digest_size = sys.getsizeof(
                harness.projection._current_integrity_digest
            )

        assert sys.getsizeof(harness.projection) == projection_size
        assert len(harness.projection._snapshots) == 1
        assert len(harness.projection._views) == 1

    assert last_page is not None
    assert harness.capture_count == 10_000
    assert harness.projection._highest_source_epoch == 10_000
    assert harness.projection._current_integrity_digest == last_page.snapshot_digest
    assert sys.getsizeof(harness.projection._current_integrity_digest) == (
        first_digest_size
    )
    assert not hasattr(harness.projection, "_integrity_by_epoch")


def test_current_epoch_equivocation_latches_after_high_water_replacement() -> None:
    harness = Harness(items=(item(1),))
    harness.projection.open_page()
    prior_digest = harness.projection._current_integrity_digest
    harness.source_epoch = 2
    harness.items = (item(2),)
    harness.projection.open_page()

    assert harness.projection._highest_source_epoch == 2
    assert harness.projection._current_integrity_digest != prior_digest
    harness.items = (item(3),)
    with pytest.raises(ApprovalInboxV11Unavailable, match="source-integrity-latched"):
        harness.projection.open_page()
    assert harness.projection.state is ApprovalInboxV11State.INTEGRITY_LATCHED


def test_older_epoch_rollback_latches_without_retaining_older_digest() -> None:
    harness = Harness(items=(item(1),))
    harness.projection.open_page()
    harness.source_epoch = 2
    harness.items = (item(2),)
    harness.projection.open_page()
    current_digest = harness.projection._current_integrity_digest

    harness.source_epoch = 1
    harness.items = (item(1),)
    with pytest.raises(ApprovalInboxV11Unavailable, match="source-integrity-latched"):
        harness.projection.open_page()
    assert harness.projection._current_integrity_digest == current_digest
    assert harness.projection.state is ApprovalInboxV11State.INTEGRITY_LATCHED


def test_new_source_epoch_invalidates_all_old_cursors_and_review_proofs() -> None:
    harness = Harness(items=(item(1), item(2), item(3)))
    old = harness.projection.open_page(page_size=1)
    harness.source_epoch = 2
    harness.items = (item(4), item(5))
    new = harness.projection.open_page(page_size=1)
    assert new.snapshot_id != old.snapshot_id
    with pytest.raises(ApprovalInboxV11Unavailable, match="cursor-state-unavailable"):
        harness.projection.continue_page(old.next_cursor)
    with pytest.raises(
        ApprovalInboxV11Unavailable, match="selection-state-unavailable"
    ):
        harness.projection.preview_calm_batch(
            old.snapshot_id, old.view_digest, _all_selections(old)
        )


def test_feature_epoch_change_during_capture_rejects_callback_output() -> None:
    epoch = [1]

    def rotate() -> HostInboxSnapshotV11:
        epoch[0] = 2
        return HostInboxSnapshotV11(1, 1, (item(1),))

    gate = ApprovalInboxFeatureGateV11(
        environ={"ONYX_APPROVAL_INBOX_V11": "true"}, epoch_reader=lambda: epoch[0]
    )
    projection = ApprovalInboxProjectionV11(
        gate=gate,
        source=HostInboxSourceV11(
            principal_id="owner-primary",
            session_id="session-local",
            capture_callback=rotate,
        ),
        clock=DeterministicInboxClockV11(),
    )
    with pytest.raises(ApprovalInboxV11Unavailable, match="feature-epoch-revoked"):
        projection.open_page()
    assert projection.state is ApprovalInboxV11State.REVOKED


def test_open_page_final_publication_rejects_completed_revocation() -> None:
    interlock = EpochInterlock()
    gate = ApprovalInboxFeatureGateV11(
        environ={"ONYX_APPROVAL_INBOX_V11": "true"}, epoch_reader=interlock
    )
    projection = ApprovalInboxProjectionV11(
        gate=gate,
        source=HostInboxSourceV11(
            principal_id="owner-primary",
            session_id="session-local",
            capture_callback=lambda: HostInboxSnapshotV11(1, 1, (item(1), item(2))),
        ),
        clock=DeterministicInboxClockV11(),
    )
    interlock.arm(4)
    thread, results, failures = _thread_call(lambda: projection.open_page(page_size=1))
    assert interlock.entered.wait(1)
    interlock.epoch += 1
    assert gate.state() is ApprovalInboxV11State.REVOKED
    interlock.release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert not results
    assert len(failures) == 1
    assert isinstance(failures[0], ApprovalInboxV11Unavailable)
    assert str(failures[0]) == "feature-epoch-revoked"
    assert not projection._snapshots
    assert not projection._views


def test_cached_continuation_final_publication_rejects_revocation() -> None:
    interlock = EpochInterlock()
    gate = ApprovalInboxFeatureGateV11(
        environ={"ONYX_APPROVAL_INBOX_V11": "true"}, epoch_reader=interlock
    )
    projection = ApprovalInboxProjectionV11(
        gate=gate,
        source=HostInboxSourceV11(
            principal_id="owner-primary",
            session_id="session-local",
            capture_callback=lambda: HostInboxSnapshotV11(1, 1, (item(1), item(2))),
        ),
        clock=DeterministicInboxClockV11(),
    )
    first = projection.open_page(page_size=1)
    interlock.arm(2)
    thread, results, failures = _thread_call(
        lambda: projection.continue_page(first.next_cursor)
    )
    assert interlock.entered.wait(1)
    interlock.epoch += 1
    assert gate.state() is ApprovalInboxV11State.REVOKED
    interlock.release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert not results
    assert len(failures) == 1
    assert isinstance(failures[0], ApprovalInboxV11Unavailable)
    assert str(failures[0]) == "feature-epoch-revoked"
    assert not projection._snapshots
    assert not projection._views


@pytest.mark.parametrize("operation", ["preview_calm_batch", "handoff_calm_batch"])
def test_batch_outputs_final_publication_rejects_revocation(operation: str) -> None:
    interlock = EpochInterlock()
    gate = ApprovalInboxFeatureGateV11(
        environ={"ONYX_APPROVAL_INBOX_V11": "true"}, epoch_reader=interlock
    )
    projection = ApprovalInboxProjectionV11(
        gate=gate,
        source=HostInboxSourceV11(
            principal_id="owner-primary",
            session_id="session-local",
            capture_callback=lambda: HostInboxSnapshotV11(1, 1, (item(1), item(2))),
        ),
        clock=DeterministicInboxClockV11(),
    )
    page = projection.open_page()
    selections = _all_selections(page)
    interlock.arm(3)
    thread, results, failures = _thread_call(
        lambda: getattr(projection, operation)(
            page.snapshot_id, page.view_digest, selections
        )
    )
    assert interlock.entered.wait(1)
    interlock.epoch += 1
    assert gate.state() is ApprovalInboxV11State.REVOKED
    interlock.release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert not results
    assert len(failures) == 1
    assert isinstance(failures[0], ApprovalInboxV11Unavailable)
    assert str(failures[0]) == "feature-epoch-revoked"
    assert not projection._snapshots
    assert not projection._views


def test_newer_source_commit_suppresses_older_page_and_cache_repopulation() -> None:
    interlock = EpochInterlock()

    def capture() -> HostInboxSnapshotV11:
        if threading.current_thread().name == "v11-interleaving":
            return HostInboxSnapshotV11(1, 1, (item(1),))
        return HostInboxSnapshotV11(2, 2, (item(9),))

    projection = ApprovalInboxProjectionV11(
        gate=ApprovalInboxFeatureGateV11(
            environ={"ONYX_APPROVAL_INBOX_V11": "true"}, epoch_reader=interlock
        ),
        source=HostInboxSourceV11(
            principal_id="owner-primary",
            session_id="session-local",
            capture_callback=capture,
        ),
        clock=DeterministicInboxClockV11(),
    )
    # Callback 3 is the view-cache publication after epoch-1 capture committed.
    interlock.arm(3)
    thread, old_results, old_failures = _thread_call(projection.open_page)
    assert interlock.entered.wait(1)
    new_page = projection.open_page()
    assert [entry.item_id for entry in new_page.items] == ["item-009"]
    interlock.release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert not old_results
    assert len(old_failures) == 1
    assert isinstance(old_failures[0], ApprovalInboxV11Unavailable)
    assert str(old_failures[0]) == "source-epoch-superseded"
    assert projection._highest_source_epoch == 2
    assert all(record.source_epoch == 2 for record in projection._snapshots.values())
    assert all(
        view.snapshot_id == new_page.snapshot_id for view in projection._views.values()
    )


@pytest.mark.parametrize("verifier", [parent_verifier, evidence_worker])
def test_authoritative_core_junction_with_identical_bytes_is_rejected(
    verifier,
) -> None:
    source = Path(__file__).resolve().parents[1] / "core/approval_inbox_v11.py"
    base = source.parents[1] / f".p52-v11-junction-{secrets.token_hex(8)}"
    clone = base / "clone"
    external_core = base / "external-core"
    external_file = external_core / "approval_inbox_v11.py"
    junction = clone / "core"
    base.mkdir()
    clone.mkdir()
    external_core.mkdir()
    try:
        external_file.write_bytes(source.read_bytes())
        if sys.platform == "win32":
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(external_core)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            assert created.returncode == 0, created.stdout
        else:
            junction.symlink_to(external_core, target_is_directory=True)
        with pytest.raises(verifier.PathIntegrityError, match="reparse-component"):
            verifier._safe_path_at(clone, "core/approval_inbox_v11.py")
    finally:
        if junction.exists() or junction.is_symlink():
            junction.rmdir()
        if external_file.exists():
            external_file.unlink()
        external_core.rmdir()
        clone.rmdir()
        base.rmdir()


def test_source_exception_is_collapsed_without_secret_cause() -> None:
    def fail() -> HostInboxSnapshotV11:
        raise RuntimeError("password=do-not-leak")

    gate = ApprovalInboxFeatureGateV11(
        environ={"ONYX_APPROVAL_INBOX_V11": "1"}, epoch_reader=lambda: 1
    )
    source = HostInboxSourceV11(
        principal_id="owner-primary", session_id="session-local", capture_callback=fail
    )
    projection = ApprovalInboxProjectionV11(
        gate=gate, source=source, clock=DeterministicInboxClockV11()
    )
    with pytest.raises(ApprovalInboxV11Unavailable) as caught:
        projection.open_page()
    assert str(caught.value) == "source-callback-failed"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_single_flight_callback_is_bounded_and_outside_projection_lock() -> None:
    entered = threading.Event()
    release = threading.Event()
    epoch = [1]

    def blocked_capture() -> HostInboxSnapshotV11:
        entered.set()
        assert release.wait(2)
        return HostInboxSnapshotV11(1, 1, (item(1),))

    gate = ApprovalInboxFeatureGateV11(
        environ={"ONYX_APPROVAL_INBOX_V11": "1"}, epoch_reader=lambda: epoch[0]
    )
    source = HostInboxSourceV11(
        principal_id="owner-primary",
        session_id="session-local",
        capture_callback=blocked_capture,
    )
    projection = ApprovalInboxProjectionV11(
        gate=gate, source=source, clock=DeterministicInboxClockV11()
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
    assert projection.state is ApprovalInboxV11State.READY
    with pytest.raises(ApprovalInboxV11Unavailable, match="source-single-flight-busy"):
        projection.open_page()
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert not failures


def _all_selections(page) -> tuple[tuple[str, str], ...]:
    return tuple((entry.item_id, entry.review_proof) for entry in page.items)


def test_calm_batch_is_order_independent_idempotent_and_non_authoritative() -> None:
    harness = Harness(items=(item(1), item(2)))
    page = harness.projection.open_page(query=InboxQueryV11(batch_only=True))
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
    with pytest.raises(ApprovalInboxV11ContractError, match="not calm-batch eligible"):
        harness.projection.preview_calm_batch(
            page.snapshot_id, page.view_digest, _all_selections(page)
        )
    filtered = harness.projection.open_page(query=InboxQueryV11(batch_only=True))
    assert filtered.total_items == 0


def test_hidden_unreturned_cross_view_and_tampered_proofs_fail() -> None:
    harness = Harness(items=(item(1), item(2), item(3)))
    first = harness.projection.open_page(page_size=1)
    second = harness.projection.open_page(
        query=InboxQueryV11(workspace_id="workspace-main"), page_size=1
    )
    selection = _all_selections(first)
    with pytest.raises(
        ApprovalInboxV11ContractError, match="not reviewed in this view"
    ):
        harness.projection.preview_calm_batch(
            second.snapshot_id, second.view_digest, selection
        )
    proof = selection[0][1]
    with pytest.raises(ApprovalInboxV11ContractError):
        harness.projection.preview_calm_batch(
            first.snapshot_id,
            first.view_digest,
            ((selection[0][0], proof[:-1] + ("A" if proof[-1] != "A" else "B")),),
        )
    # The second item exists but its proof was not returned on the first page.
    with pytest.raises(
        ApprovalInboxV11ContractError, match="not reviewed in this view"
    ):
        harness.projection.preview_calm_batch(
            first.snapshot_id,
            first.view_digest,
            (("item-002", selection[0][1]),),
        )


def test_duplicate_item_request_fingerprint_and_idempotency_identity_reject() -> None:
    # Duplicate source item id is rejected at capture.
    duplicate_id = Harness(items=(item(1), item(1, action_request_id="request-002")))
    with pytest.raises(ApprovalInboxV11ContractError, match="duplicate item_id"):
        duplicate_id.projection.open_page()

    # Duplicate request ID with distinct actions is rejected at batch selection.
    duplicate_request = Harness(
        items=(item(1), item(2, action_request_id="request-001"))
    )
    page = duplicate_request.projection.open_page()
    with pytest.raises(
        ApprovalInboxV11ContractError, match="duplicate action_request_id"
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
        ApprovalInboxV11ContractError, match="duplicate action_fingerprint"
    ):
        duplicate_fingerprint.projection.preview_calm_batch(
            page.snapshot_id, page.view_digest, _all_selections(page)
        )

    duplicate_idempotency = Harness(
        items=(item(1), item(2, idempotency_key=item(1).idempotency_key))
    )
    page = duplicate_idempotency.projection.open_page()
    with pytest.raises(
        ApprovalInboxV11ContractError, match="duplicate idempotency_identity"
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
    with pytest.raises(ApprovalInboxV11ContractError):
        harness.projection.open_page()


def test_public_surface_has_no_authority_or_mutation_methods() -> None:
    public = {
        name for name in dir(ApprovalInboxProjectionV11) if not name.startswith("_")
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


def _owned_root():
    return historical._OwnedTemporaryDirectory(
        prefix=".p52-v11-owned-", dir=historical.ROOT
    )


def test_historical_projection_binds_exactly_two_direct_v9_snapshots() -> None:
    assert set(historical.FROZEN_PROJECTIONS) == {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VERIFICATION_EVIDENCE.md",
    }
    with _owned_root() as directory:
        root = Path(directory)
        copied = historical._materialize_r11(
            __import__(
                "scripts.verify_phase5_approval_inbox_v7", fromlist=["materialize_r11"]
            ),
            root,
        )
        assert set(historical.FROZEN_PROJECTIONS).issubset(copied)
        for relative, (
            snapshot_relative,
            digest,
        ) in historical.FROZEN_PROJECTIONS.items():
            output = root / relative
            snapshot = historical.ROOT / snapshot_relative
            assert hashlib.sha256(output.read_bytes()).hexdigest() == digest
            assert output.read_bytes() == snapshot.read_bytes()
            assert output.read_bytes() != (historical.ROOT / relative).read_bytes()
    assert not root.exists()


def test_unrelated_historical_drift_still_fails_closed() -> None:
    module = __import__(
        "scripts.verify_phase5_approval_inbox_v7", fromlist=["materialize_r11"]
    )
    with _owned_root() as directory:
        root = Path(directory)
        historical._materialize_r11(module, root)
        target = root / "core/session_grants_v10.py"
        target.write_bytes(target.read_bytes() + b"\n# unrelated drift\n")
        with pytest.raises(
            module.Phase52V7EvidenceError, match="session_grants_v10.py"
        ):
            module.verify_historical_manifest_tree(
                root, (module.R11_ROOT, module.R11_ACCEPTANCE_MANIFEST)
            )


@pytest.mark.parametrize(
    "relative",
    [
        "../outside",
        "docs/onyx/../CAPABILITY_MATRIX.md",
        "docs\\onyx\\CAPABILITY_MATRIX.md",
        "/absolute",
        "",
    ],
)
def test_plugin_rejects_outside_traversal_and_noncanonical_aliases(
    relative: str,
) -> None:
    with pytest.raises(historical.HistoricalProjectionPathError, match="noncanonical"):
        historical._safe_existing(historical.ROOT, relative)


def test_plugin_rejects_exact_case_alias_before_read() -> None:
    relative = "docs/onyx/capability_matrix.md"
    with pytest.raises(
        historical.HistoricalProjectionPathError, match="missing-or-case-mismatch"
    ):
        historical._safe_existing(historical.ROOT, relative)


def test_identical_external_snapshot_file_symlink_rejects_before_read() -> None:
    relative, digest = next(iter(historical.FROZEN_PROJECTIONS.values()))
    source = historical.ROOT / relative
    base = historical.ROOT / f".p52-v11-file-link-{secrets.token_hex(8)}"
    external = historical.ROOT.parent / f".p52-v11-external-{secrets.token_hex(8)}"
    base.mkdir()
    external.write_bytes(source.read_bytes())
    link = base / "snapshot"
    try:
        os.symlink(external, link)
        assert hashlib.sha256(external.read_bytes()).hexdigest() == digest
        with pytest.raises(
            historical.HistoricalProjectionPathError, match="reparse-component"
        ):
            historical._safe_existing(base, "snapshot")
    finally:
        if link.exists() or link.is_symlink():
            link.unlink()
        if external.exists():
            external.unlink()
        base.rmdir()


def test_authority_directory_junction_and_aliased_root_reject() -> None:
    base = historical.ROOT / f".p52-v11-junction-{secrets.token_hex(8)}"
    actual = base / "actual"
    link = base / "linked"
    actual.mkdir(parents=True)
    (actual / "item").write_bytes(b"authority")
    try:
        if sys.platform == "win32":
            made = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(actual)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            assert made.returncode == 0, made.stdout
        else:
            link.symlink_to(actual, target_is_directory=True)
        with pytest.raises(
            historical.HistoricalProjectionPathError, match="reparse-component"
        ):
            historical._safe_existing(base, "linked/item")
        with pytest.raises(
            historical.HistoricalProjectionPathError,
            match="reparse-or-aliased-root",
        ):
            historical._safe_existing(link, "item")
    finally:
        if link.exists() or link.is_symlink():
            if sys.platform == "win32":
                link.rmdir()
            else:
                link.unlink()
        shutil.rmtree(base)


def test_output_target_link_and_preexisting_target_reject_before_write() -> None:
    with _owned_root() as directory:
        root = Path(directory)
        preexisting = root / "preexisting"
        preexisting.write_bytes(b"do-not-touch")
        with pytest.raises(
            historical.HistoricalProjectionPathError, match="preexisting-target"
        ):
            historical._write_new(root, "preexisting", b"replacement")
        assert preexisting.read_bytes() == b"do-not-touch"

        external = historical.ROOT.parent / f".p52-v11-target-{secrets.token_hex(8)}"
        external.write_bytes(b"external-do-not-touch")
        link = root / "linked-target"
        os.symlink(external, link)
        try:
            with pytest.raises(
                historical.HistoricalProjectionPathError, match="preexisting-target"
            ):
                historical._write_new(root, "linked-target", b"replacement")
            assert external.read_bytes() == b"external-do-not-touch"
        finally:
            link.unlink()
            external.unlink()


def test_output_ancestor_junction_and_unowned_root_reject() -> None:
    with _owned_root() as directory:
        root = Path(directory)
        external = historical.ROOT / f".p52-v11-target-dir-{secrets.token_hex(8)}"
        external.mkdir()
        link = root / "linked"
        try:
            if sys.platform == "win32":
                made = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(external)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
                assert made.returncode == 0, made.stdout
            else:
                link.symlink_to(external, target_is_directory=True)
            with pytest.raises(
                historical.HistoricalProjectionPathError,
                match="reparse-component",
            ):
                historical._write_new(root, "linked/new-file", b"forbidden")
            assert not (external / "new-file").exists()
        finally:
            if link.exists() or link.is_symlink():
                if sys.platform == "win32":
                    link.rmdir()
                else:
                    link.unlink()
            external.rmdir()

    unowned = historical.ROOT / f".p52-v11-unowned-{secrets.token_hex(8)}"
    unowned.mkdir()
    try:
        with pytest.raises(
            historical.HistoricalProjectionPathError,
            match="temporary-root-not-plugin-owned",
        ):
            historical._write_new(unowned, "forbidden", b"no")
        assert not (unowned / "forbidden").exists()
    finally:
        unowned.rmdir()
