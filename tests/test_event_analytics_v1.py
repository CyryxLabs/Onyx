from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from core.event_analytics_v1 import (
    MAX_TIMELINE_ITEMS,
    MAX_WINDOW_SECONDS,
    AnalyticsEventV1,
    AnalyticsEventSnapshotV1,
    AnalyticsReceiptAttestationV1,
    AnalyticsSourceAttestationV1,
    EventAnalyticsContractError,
    EventAnalyticsDenied,
    EventAnalyticsError,
    EventAnalyticsProjectionV1,
    EventAnalyticsReplayDenied,
)


OWNER = "owner_personal"
WORKSPACE = "workspace_personal"
OTHER_WORKSPACE = "workspace_other"
NOW = 1_800_000_000.0
INTEGRITY_KEY = bytes.fromhex("42" * 32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Clock:
    def __init__(self, value: float = NOW) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def event(
    *,
    source_kind: str = "mission",
    event_type: str = "mission.started",
    outcome: str = "active",
    occurred_at: float = NOW - 60,
    workspace_id: str = WORKSPACE,
    entity: str = "mission-a",
    receipt: str | None = None,
    event_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> AnalyticsEventV1:
    return AnalyticsEventV1.create(
        owner_profile_id=OWNER,
        workspace_id=workspace_id,
        source_kind=source_kind,
        entity_ref=digest(entity),
        event_type=event_type,
        outcome=outcome,
        occurred_at=occurred_at,
        receipt_digest=receipt,
        event_id=event_id,
        metadata={"revision": 1} if metadata is None else metadata,
    )


def projection(
    path: Path,
    *,
    clock: Clock | None = None,
    source_acceptor=None,
    receipt_verifier=None,
) -> EventAnalyticsProjectionV1:
    def accept(item: AnalyticsEventSnapshotV1) -> AnalyticsSourceAttestationV1:
        return AnalyticsSourceAttestationV1(item.source_digest, True)

    def verify(item: AnalyticsEventSnapshotV1) -> AnalyticsReceiptAttestationV1:
        assert item.receipt_digest is not None
        return AnalyticsReceiptAttestationV1(
            item.source_digest,
            item.receipt_digest,
            item.receipt_digest == digest("receipt-ok"),
        )

    return EventAnalyticsProjectionV1(
        path,
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        source_acceptor=accept if source_acceptor is None else source_acceptor,
        receipt_verifier=verify if receipt_verifier is None else receipt_verifier,
        integrity_key=INTEGRITY_KEY,
        enabled=True,
        clock=clock or Clock(),
    )


def test_default_off_touches_no_storage_and_has_no_ambient_workers(tmp_path: Path) -> None:
    path = tmp_path / "analytics" / "events.sqlite3"
    with pytest.raises(EventAnalyticsDenied, match="disabled"):
        EventAnalyticsProjectionV1(
            path,
            owner_profile_id=OWNER,
            workspace_id=WORKSPACE,
            source_acceptor=lambda _event: True,
            receipt_verifier=lambda _event: True,
            integrity_key=INTEGRITY_KEY,
        )
    assert not path.exists()

    store = projection(path)
    assert store.background_workers == 0
    assert store.polling_interval is None
    assert store.network_calls == 0
    assert store.content_captured is False


def test_timeline_trends_and_counts_are_deterministic_for_out_of_order_events(
    tmp_path: Path,
) -> None:
    store = projection(tmp_path / "analytics.sqlite3")
    later = event(
        source_kind="workflow",
        event_type="workflow.failed",
        outcome="failed",
        occurred_at=NOW - 10,
        entity="workflow-b",
    )
    earlier = event(
        source_kind="goal",
        event_type="goal.activated",
        outcome="active",
        occurred_at=NOW - 3_700,
        entity="goal-a",
    )
    store.ingest(later)
    store.ingest(earlier)

    report = store.create_report(
        start_at=NOW - 7_200,
        end_at=NOW,
        bucket_seconds=3_600,
        timeline_limit=10,
    )
    payload = report.payload()
    assert payload["totals"] == {
        "events": 2,
        "verified_completions": 0,
        "unverified_completion_claims": 0,
        "failures": 1,
        "denials": 0,
    }
    assert [item["event_type"] for item in payload["timeline"]] == [
        "goal.activated",
        "workflow.failed",
    ]
    assert [item["events"] for item in payload["trends"]] == [1, 1]
    assert payload["authoritative"] is False
    assert payload["content_captured"] is False

    reopened = projection(tmp_path / "analytics.sqlite3")
    assert reopened.read_report(
        report.report_id,
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
    ).payload_json == report.payload_json


def test_completion_count_requires_independently_verified_receipt(tmp_path: Path) -> None:
    verifier_calls: list[str | None] = []

    def verify(item: AnalyticsEventSnapshotV1) -> AnalyticsReceiptAttestationV1:
        verifier_calls.append(item.receipt_digest)
        assert item.receipt_digest is not None
        return AnalyticsReceiptAttestationV1(
            item.source_digest, item.receipt_digest,
            item.receipt_digest == digest("receipt-ok"),
        )

    store = projection(tmp_path / "analytics.sqlite3", receipt_verifier=verify)
    no_receipt = event(
        event_type="mission.completed",
        outcome="completed",
        occurred_at=NOW - 30,
        entity="mission-no-receipt",
    )
    forged = event(
        event_type="mission.completed",
        outcome="completed",
        occurred_at=NOW - 20,
        entity="mission-forged",
        receipt=digest("forged"),
    )
    verified = event(
        event_type="mission.completed",
        outcome="completed",
        occurred_at=NOW - 10,
        entity="mission-verified",
        receipt=digest("receipt-ok"),
    )
    assert store.ingest(no_receipt).completion_verified is False
    assert store.ingest(forged).completion_verified is False
    assert store.ingest(verified).completion_verified is True
    assert verifier_calls == [digest("forged"), digest("receipt-ok")]

    totals = store.create_report(start_at=NOW - 100, end_at=NOW).payload()["totals"]
    assert totals["verified_completions"] == 1
    assert totals["unverified_completion_claims"] == 2


def test_cross_workspace_and_unaccepted_source_fail_before_append(tmp_path: Path) -> None:
    accepted: list[str] = []

    def accept(item: AnalyticsEventSnapshotV1) -> AnalyticsSourceAttestationV1:
        accepted.append(item.event_id)
        return AnalyticsSourceAttestationV1(item.source_digest, False)

    store = projection(tmp_path / "analytics.sqlite3", source_acceptor=accept)
    with pytest.raises(EventAnalyticsDenied, match="scope"):
        store.ingest(event(workspace_id=OTHER_WORKSPACE))
    assert accepted == []

    rejected = event()
    with pytest.raises(EventAnalyticsDenied, match="source authority"):
        store.ingest(rejected)
    assert accepted == [rejected.event_id]

    report = projection(tmp_path / "empty.sqlite3").create_report(
        start_at=NOW - 100, end_at=NOW
    )
    with pytest.raises(EventAnalyticsDenied, match="scope"):
        projection(tmp_path / "empty.sqlite3").read_report(
            report.report_id,
            owner_profile_id=OWNER,
            workspace_id=OTHER_WORKSPACE,
        )


def test_duplicate_id_and_semantic_replay_are_denied(tmp_path: Path) -> None:
    store = projection(tmp_path / "analytics.sqlite3")
    first = event(event_id="event_" + "1" * 32)
    store.ingest(first)
    with pytest.raises(EventAnalyticsReplayDenied):
        store.ingest(first)

    replay = event(event_id="event_" + "2" * 32)
    with pytest.raises(EventAnalyticsReplayDenied):
        store.ingest(replay)


@pytest.mark.parametrize(
    "metadata",
    [
        {"prompt": 1},
        {"email_subject": "secret"},
        {"message": "raw"},
        {"unknown": 1},
        {f"revision_{index}": index for index in range(9)},
    ],
)
def test_raw_content_and_oversized_metadata_cardinality_are_rejected(
    metadata: dict[str, object],
) -> None:
    with pytest.raises((EventAnalyticsContractError, EventAnalyticsDenied)):
        event(metadata=metadata)


def test_oversized_window_timeline_and_future_event_are_rejected(tmp_path: Path) -> None:
    store = projection(tmp_path / "analytics.sqlite3")
    with pytest.raises(EventAnalyticsContractError, match="window"):
        store.create_report(start_at=NOW - MAX_WINDOW_SECONDS - 1, end_at=NOW)
    with pytest.raises(EventAnalyticsContractError, match="timeline_limit"):
        store.create_report(
            start_at=NOW - 100,
            end_at=NOW,
            timeline_limit=MAX_TIMELINE_ITEMS + 1,
        )
    with pytest.raises(EventAnalyticsDenied, match="future"):
        store.ingest(event(occurred_at=NOW + 301))


def test_mutated_source_envelope_fails_digest_validation(tmp_path: Path) -> None:
    store = projection(tmp_path / "analytics.sqlite3")
    item = event()
    object.__setattr__(item, "entity_ref", digest("mutated-entity"))
    with pytest.raises(EventAnalyticsDenied, match="digest"):
        store.ingest(item)


def test_host_callback_cannot_mutate_event_after_initial_validation(tmp_path: Path) -> None:
    def hostile_acceptor(
        item: AnalyticsEventSnapshotV1,
    ) -> AnalyticsSourceAttestationV1:
        object.__setattr__(item, "entity_ref", digest("callback-mutated"))
        return AnalyticsSourceAttestationV1(item.source_digest, True)

    store = projection(
        tmp_path / "callback.sqlite3", source_acceptor=hostile_acceptor
    )
    with pytest.raises(EventAnalyticsDenied):
        store.ingest(event())
    assert store.list_event_page(
        owner_profile_id=OWNER, workspace_id=WORKSPACE
    ).items == ()


def test_source_kind_event_type_and_outcome_must_be_consistent() -> None:
    with pytest.raises(EventAnalyticsContractError, match="source"):
        event(source_kind="goal", event_type="mission.started")
    with pytest.raises(EventAnalyticsContractError, match="outcome"):
        event(event_type="mission.failed", outcome="active")


def test_source_chain_tamper_fails_closed_and_latches(tmp_path: Path) -> None:
    path = tmp_path / "source.sqlite3"
    store = projection(path)
    store.ingest(event())
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER analytics_events_no_update")
        connection.execute("UPDATE analytics_events SET outcome='failed'")
        connection.execute(
            """CREATE TRIGGER analytics_events_no_update
            BEFORE UPDATE ON analytics_events
            BEGIN SELECT RAISE(ABORT,'analytics events are immutable'); END"""
        )
    with pytest.raises(EventAnalyticsError):
        store.create_report(start_at=NOW - 100, end_at=NOW)
    with pytest.raises(EventAnalyticsError, match="latched"):
        store.create_report(start_at=NOW - 100, end_at=NOW)


def test_projection_tamper_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "projection.sqlite3"
    store = projection(path)
    store.ingest(event())
    report = store.create_report(start_at=NOW - 100, end_at=NOW)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER analytics_reports_no_update")
        connection.execute(
            "UPDATE analytics_reports SET payload_json='{}' WHERE report_id=?",
            (report.report_id,),
        )
        connection.execute(
            """CREATE TRIGGER analytics_reports_no_update
            BEFORE UPDATE ON analytics_reports
            BEGIN SELECT RAISE(ABORT,'analytics reports are immutable'); END"""
        )
    with pytest.raises(EventAnalyticsError):
        store.read_report(
            report.report_id,
            owner_profile_id=OWNER,
            workspace_id=WORKSPACE,
        )


def test_report_high_water_keeps_old_projection_valid_after_new_event(tmp_path: Path) -> None:
    store = projection(tmp_path / "analytics.sqlite3")
    store.ingest(event(entity="mission-a", occurred_at=NOW - 30))
    first = store.create_report(start_at=NOW - 100, end_at=NOW)
    store.ingest(event(entity="mission-b", occurred_at=NOW - 20))
    second = store.create_report(start_at=NOW - 100, end_at=NOW)

    assert store.read_report(
        first.report_id,
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
    ).payload()["totals"]["events"] == 1
    assert second.payload()["totals"]["events"] == 2
    assert first.provenance_digest != second.provenance_digest


def test_original_event_mutation_during_callback_fails_without_append(tmp_path: Path) -> None:
    original = event()

    def mutate_original(
        item: AnalyticsEventSnapshotV1,
    ) -> AnalyticsSourceAttestationV1:
        object.__setattr__(original, "entity_ref", digest("mutated-original"))
        return AnalyticsSourceAttestationV1(item.source_digest, True)

    store = projection(tmp_path / "original.sqlite3", source_acceptor=mutate_original)
    with pytest.raises(EventAnalyticsDenied, match="changed"):
        store.ingest(original)
    assert store.list_event_page(
        owner_profile_id=OWNER, workspace_id=WORKSPACE
    ).items == ()


def test_attestations_must_be_exact_and_digest_bound(tmp_path: Path) -> None:
    wrong_type = projection(
        tmp_path / "wrong-type.sqlite3", source_acceptor=lambda _item: True
    )
    with pytest.raises(EventAnalyticsDenied, match="source authority"):
        wrong_type.ingest(event())

    def wrong_receipt(
        item: AnalyticsEventSnapshotV1,
    ) -> AnalyticsReceiptAttestationV1:
        assert item.receipt_digest is not None
        return AnalyticsReceiptAttestationV1(
            digest("wrong-source"), item.receipt_digest, True
        )

    receipt_store = projection(
        tmp_path / "wrong-receipt.sqlite3", receipt_verifier=wrong_receipt
    )
    with pytest.raises(EventAnalyticsDenied, match="binding"):
        receipt_store.ingest(
            event(
                event_type="mission.completed", outcome="completed",
                receipt=digest("receipt-ok"),
            )
        )


def _restore_event_delete_trigger(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TRIGGER analytics_events_no_delete
        BEFORE DELETE ON analytics_events
        BEGIN SELECT RAISE(ABORT,'analytics events are immutable'); END"""
    )


def _restore_report_delete_trigger(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TRIGGER analytics_reports_no_delete
        BEFORE DELETE ON analytics_reports
        BEGIN SELECT RAISE(ABORT,'analytics reports are immutable'); END"""
    )


@pytest.mark.parametrize("delete_all", [False, True])
def test_event_tail_or_all_deletion_cannot_reanchor(
    tmp_path: Path, delete_all: bool
) -> None:
    path = tmp_path / f"tail-{delete_all}.sqlite3"
    store = projection(path)
    store.ingest(event(entity="one", occurred_at=NOW - 20))
    store.ingest(event(entity="two", occurred_at=NOW - 10))
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER analytics_events_no_delete")
        if delete_all:
            connection.execute("DELETE FROM analytics_events")
        else:
            connection.execute(
                "DELETE FROM analytics_events WHERE seq=(SELECT MAX(seq) FROM analytics_events)"
            )
        _restore_event_delete_trigger(connection)
    with pytest.raises(EventAnalyticsError):
        store.list_event_page(owner_profile_id=OWNER, workspace_id=WORKSPACE)


def test_report_tail_deletion_and_plain_hash_head_rewrite_fail_closed(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report-tail.sqlite3"
    report_store = projection(report_path)
    report_store.create_report(start_at=NOW - 100, end_at=NOW)
    with sqlite3.connect(report_path) as connection:
        connection.execute("DROP TRIGGER analytics_reports_no_delete")
        connection.execute("DELETE FROM analytics_reports")
        _restore_report_delete_trigger(connection)
    with pytest.raises(EventAnalyticsError):
        report_store.list_report_page(
            owner_profile_id=OWNER, workspace_id=WORKSPACE
        )

    head_path = tmp_path / "head-rewrite.sqlite3"
    head_store = projection(head_path)
    head_store.ingest(event())
    with sqlite3.connect(head_path) as connection:
        connection.execute(
            """UPDATE analytics_heads SET event_count=0,event_tail_seq=0,
            event_tail_hash=?,event_projection_digest=?,head_mac=? WHERE singleton=1""",
            ("0" * 64, "0" * 64, hashlib.sha256(b"plain-reanchor").hexdigest()),
        )
    with pytest.raises(EventAnalyticsError, match="authentication"):
        head_store.list_event_page(owner_profile_id=OWNER, workspace_id=WORKSPACE)


def test_exact_trigger_definition_is_verified_not_only_its_name(tmp_path: Path) -> None:
    path = tmp_path / "schema.sqlite3"
    store = projection(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER analytics_events_no_delete")
        connection.execute(
            """CREATE TRIGGER analytics_events_no_delete
            BEFORE DELETE ON analytics_events
            BEGIN SELECT RAISE(ABORT,'different definition'); END"""
        )
    with pytest.raises(EventAnalyticsError, match="exact schema"):
        store.list_event_page(owner_profile_id=OWNER, workspace_id=WORKSPACE)


def test_authenticated_event_and_report_pagination_use_stable_high_water(
    tmp_path: Path,
) -> None:
    store = projection(tmp_path / "pages.sqlite3")
    for index in range(5):
        store.ingest(event(entity=f"mission-{index}", occurred_at=NOW - 50 + index))
    first = store.list_event_page(
        owner_profile_id=OWNER, workspace_id=WORKSPACE, limit=2
    )
    assert len(first.items) == 2 and first.next_cursor is not None
    store.ingest(event(entity="mission-later", occurred_at=NOW - 1))
    second = store.list_event_page(
        owner_profile_id=OWNER, workspace_id=WORKSPACE, limit=2,
        cursor=first.next_cursor,
    )
    third = store.list_event_page(
        owner_profile_id=OWNER, workspace_id=WORKSPACE, limit=2,
        cursor=second.next_cursor,
    )
    assert len(second.items) == 2
    assert len(third.items) == 1
    assert third.high_water == first.high_water == 5
    assert third.next_cursor is None
    with pytest.raises(EventAnalyticsDenied, match="cursor"):
        store.list_event_page(
            owner_profile_id=OWNER, workspace_id=WORKSPACE,
            cursor=first.next_cursor[:-2] + "AA",
        )

    for _ in range(3):
        store.create_report(start_at=NOW - 100, end_at=NOW)
    reports = store.list_report_page(
        owner_profile_id=OWNER, workspace_id=WORKSPACE, limit=2
    )
    assert len(reports.items) == 2 and reports.next_cursor is not None
    final_reports = store.list_report_page(
        owner_profile_id=OWNER, workspace_id=WORKSPACE, limit=2,
        cursor=reports.next_cursor,
    )
    assert len(final_reports.items) == 1 and final_reports.next_cursor is None


def test_one_thousand_appends_use_incremental_checks_not_full_chain_scans(
    tmp_path: Path,
) -> None:
    store = projection(tmp_path / "growth.sqlite3")
    assert store.full_audits == 1
    assert store.full_audit_rows == 0
    for index in range(1_000):
        store.ingest(
            event(
                entity=f"mission-{index}", occurred_at=NOW - 2_000 + index,
                event_id="event_" + f"{index:032x}",
            )
        )
    assert store.full_audits == 1
    assert store.full_audit_rows == 0
    assert store.incremental_checks == 2_000
    report = store.create_report(start_at=NOW - 3_000, end_at=NOW)
    assert report.payload()["totals"]["events"] == 1_000
    receipt = store.verify_integrity()
    assert receipt.event_count == 1_000
    assert receipt.full_rows_verified == 1_001


@pytest.mark.parametrize("ordinary_operation", ["list", "report"])
def test_middle_event_deletion_fails_before_ordinary_read_or_report_persistence(
    tmp_path: Path, ordinary_operation: str
) -> None:
    path = tmp_path / f"middle-{ordinary_operation}.sqlite3"
    store = projection(path)
    for index in range(3):
        store.ingest(
            event(
                entity=f"middle-{index}", occurred_at=NOW - 30 + index,
                event_id="event_" + f"{index + 100:032x}",
            )
        )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER analytics_events_no_delete")
        connection.execute("DELETE FROM analytics_events WHERE seq=2")
        _restore_event_delete_trigger(connection)

    with pytest.raises(EventAnalyticsError, match="count"):
        if ordinary_operation == "list":
            store.list_event_page(
                owner_profile_id=OWNER, workspace_id=WORKSPACE, limit=1
            )
        else:
            store.create_report(start_at=NOW - 100, end_at=NOW)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM analytics_reports").fetchone()[0] == 0
