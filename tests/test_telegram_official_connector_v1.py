from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from itertools import count

import pytest

import core.telegram_official_connector_v1 as telegram_connector
from core.native_vault import SecretReference
from core.telegram_official_connector_v1 import (
    TELEGRAM_ORIGIN,
    StdlibTelegramTransportV1,
    TelegramAccountV1,
    TelegramBudgetV1,
    TelegramCancellationV1,
    TelegramConnectorError,
    TelegramDenied,
    TelegramFeatureGateV1,
    TelegramMessageV1,
    TelegramNotDispatched,
    TelegramOfficialOutboxV1,
    TelegramOutcomeUnknown,
    TelegramProviderReceiptV1,
    TelegramReconciliationDecisionV1,
    TelegramReconciliationProofV1,
    telegram_vault_reference_v1,
)


CHAT = "-1001234567890"
OTHER_CHAT = "902100100"
TOKEN = b"123456789:AAExample_secret_token_1234567890"


def account(
    *,
    owner: str = "owner.primary",
    workspace: str = "workspace.main",
    account_id: str = "telegram.cyryx",
    reference: SecretReference | None = None,
) -> TelegramAccountV1:
    return TelegramAccountV1(
        account_id,
        owner,
        workspace,
        telegram_vault_reference_v1(owner, workspace, account_id)
        if reference is None
        else reference,
        (CHAT,),
    )


class Transport:
    def __init__(self, outcome: str = "accepted") -> None:
        self.outcome = outcome
        self.calls = []

    def send(self, telegram_account, message, budget, cancellation):
        self.calls.append((telegram_account, message, budget, cancellation))
        if self.outcome == "unknown":
            raise TelegramOutcomeUnknown("provider_outcome_unknown")
        if self.outcome == "not_dispatched":
            raise TelegramNotDispatched("request_not_dispatched")
        if self.outcome == "wrong_chat":
            return TelegramProviderReceiptV1(
                "81", OTHER_CHAT, message.content_digest, 1001.0
            )
        return TelegramProviderReceiptV1(
            "81", message.chat_id, message.content_digest, 1001.0
        )


def enabled_outbox(tmp_path, clock=None) -> TelegramOfficialOutboxV1:
    ticks = count(10_000)
    return TelegramOfficialOutboxV1(
        (tmp_path / "telegram.sqlite3").resolve(),
        gate=TelegramFeatureGateV1(True),
        clock=(lambda: float(next(ticks))) if clock is None else clock,
    )


def permit(*_args) -> bool:
    return True


def create_v1_store(path, *, tamper_event: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        for statement in TelegramOfficialOutboxV1._DDL_V1:
            connection.execute(statement)
        rows = (
            (
                "telegram_v1_reserved",
                "telegram.cyryx",
                "owner.primary",
                "workspace.main",
                CHAT,
                "1" * 64,
                "2" * 64,
                "reserved",
                None,
                "legacy_reserved",
                100.0,
                100.0,
            ),
            (
                "telegram_v1_dispatching",
                "telegram.cyryx",
                "owner.primary",
                "workspace.main",
                CHAT,
                "3" * 64,
                "4" * 64,
                "dispatching",
                None,
                "legacy_dispatching",
                101.0,
                101.0,
            ),
            (
                "telegram_v1_accepted",
                "telegram.cyryx",
                "owner.primary",
                "workspace.main",
                CHAT,
                "5" * 64,
                "6" * 64,
                "accepted",
                "77",
                "legacy_accepted",
                102.0,
                102.0,
            ),
        )
        connection.executemany(
            "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        detail_json = json.dumps(
            {"provider_message_id": "77"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        event_payload = {
            "operation_id": "telegram_v1_accepted",
            "occurred_at": 102.0,
            "event": "telegram.accepted",
            "detail_json": detail_json,
            "prev_hash": "0" * 64,
        }
        event_hash = hashlib.sha256(
            json.dumps(
                event_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        connection.execute(
            "INSERT INTO message_events(operation_id,occurred_at,event,detail_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
            (
                "telegram_v1_accepted",
                102.0,
                "telegram.accepted",
                detail_json,
                "0" * 64,
                "f" * 64 if tamper_event else event_hash,
            ),
        )
        connection.execute("PRAGMA user_version=1")


def test_exact_v1_store_migrates_transactionally_to_v2(tmp_path) -> None:
    path = (tmp_path / "legacy-v1.sqlite3").resolve()
    create_v1_store(path)
    outbox = TelegramOfficialOutboxV1(
        path, gate=TelegramFeatureGateV1(True), clock=lambda: 1000.0
    )
    assert outbox.status("telegram_v1_reserved").status == "not_dispatched"
    assert outbox.status("telegram_v1_dispatching").status == "reconciliation"
    accepted = outbox.status("telegram_v1_accepted")
    assert accepted.status == "accepted"
    assert accepted.provider_message_id == "77"
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(messages)")
        }
        events = [
            row[0]
            for row in connection.execute(
                "SELECT event FROM message_events ORDER BY seq"
            )
        ]
    assert {
        "dispatch_nonce",
        "lease_owner_instance_id",
        "lease_owner_pid",
        "lease_owner_start",
        "lease_expires_at",
    }.issubset(columns)
    assert events == [
        "telegram.accepted",
        "telegram.reconciliation",
        "telegram.not_dispatched",
    ]
    reopened = TelegramOfficialOutboxV1(
        path, gate=TelegramFeatureGateV1(True), clock=lambda: 1001.0
    )
    assert reopened.status("telegram_v1_accepted") == accepted


def test_v1_tampered_event_chain_denies_and_rolls_back(tmp_path) -> None:
    path = (tmp_path / "tampered-v1.sqlite3").resolve()
    create_v1_store(path, tamper_event=True)
    with pytest.raises(TelegramConnectorError, match="event chain"):
        TelegramOfficialOutboxV1(path, gate=TelegramFeatureGateV1(True))
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(messages)")
        }
    assert "dispatch_nonce" not in columns


def test_partial_v1_migration_schema_is_denied_without_progress(tmp_path) -> None:
    path = (tmp_path / "partial-v1.sqlite3").resolve()
    create_v1_store(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE messages ADD COLUMN dispatch_nonce TEXT NOT NULL DEFAULT ''"
        )
    with pytest.raises(TelegramConnectorError, match="schema signature"):
        TelegramOfficialOutboxV1(path, gate=TelegramFeatureGateV1(True))
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(messages)")
        ]
    assert columns.count("dispatch_nonce") == 1
    assert "lease_owner_instance_id" not in columns


def test_partial_v2_schema_is_denied_fail_closed(tmp_path) -> None:
    path = (tmp_path / "partial-v2.sqlite3").resolve()
    outbox = TelegramOfficialOutboxV1(
        path, gate=TelegramFeatureGateV1(True)
    )
    outbox.close()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER message_events_no_update")
    with pytest.raises(TelegramConnectorError, match="schema signature"):
        TelegramOfficialOutboxV1(path, gate=TelegramFeatureGateV1(True))
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='message_events_no_update'"
            ).fetchone()[0]
            == 0
        )


def test_default_off_and_environment_gate_are_exact(tmp_path) -> None:
    with pytest.raises(TelegramDenied, match="disabled"):
        TelegramOfficialOutboxV1((tmp_path / "off.sqlite3").resolve())
    assert not TelegramFeatureGateV1.from_environ({}).enabled
    assert not TelegramFeatureGateV1.from_environ(
        {"ONYX_TELEGRAM_OFFICIAL_CONNECTOR_V1": "TRUE"}
    ).enabled
    assert TelegramFeatureGateV1.from_environ(
        {"ONYX_TELEGRAM_OFFICIAL_CONNECTOR_V1": "true"}
    ).enabled


def test_vault_alias_is_deterministically_bound_to_exact_scope() -> None:
    correct = telegram_vault_reference_v1(
        "owner.primary", "workspace.main", "telegram.cyryx"
    )
    assert account(reference=correct).secret_reference == correct
    wrong_workspace = telegram_vault_reference_v1(
        "owner.primary", "workspace.other", "telegram.cyryx"
    )
    with pytest.raises(TelegramDenied, match="vault alias"):
        account(reference=wrong_workspace)
    with pytest.raises(TelegramDenied, match="vault alias"):
        account(reference=SecretReference("other.service", "other.account", "Wrong"))


def test_exact_chat_scope_and_central_authority_fail_before_reservation(tmp_path) -> None:
    outbox = enabled_outbox(tmp_path)
    transport = Transport()
    with pytest.raises(TelegramDenied, match="outside"):
        outbox.send_message(
            operation_id="telegram_scope_denied",
            account=account(),
            chat_id=OTHER_CHAT,
            text="Not sent.",
            authority=permit,
            transport=transport,
        )
    with pytest.raises(TelegramDenied, match="authority"):
        outbox.send_message(
            operation_id="telegram_authority_denied",
            account=account(),
            chat_id=CHAT,
            text="Not sent.",
            authority=lambda *_args: False,
            transport=transport,
        )
    assert transport.calls == []
    with sqlite3.connect(outbox.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_plain_text_only_and_bounded_utf8_fail_before_transport(tmp_path) -> None:
    outbox = enabled_outbox(tmp_path)
    transport = Transport()
    with pytest.raises(TelegramDenied, match="plain text"):
        outbox.send_message(
            operation_id="telegram_markdown_denied",
            account=account(),
            chat_id=CHAT,
            text="*formatted*",
            parse_mode="Markdown",  # type: ignore[arg-type]
            authority=permit,
            transport=transport,
        )
    with pytest.raises(ValueError, match="character budget"):
        outbox.send_message(
            operation_id="telegram_too_long",
            account=account(),
            chat_id=CHAT,
            text="x" * 4097,
            authority=permit,
            transport=transport,
        )
    with pytest.raises(ValueError, match="byte budget"):
        outbox.send_message(
            operation_id="telegram_too_many_bytes",
            account=account(),
            chat_id=CHAT,
            text="😀" * 4096,
            authority=permit,
            transport=transport,
        )
    assert transport.calls == []


def test_reserved_before_single_call_and_receipt_is_exactly_bound(tmp_path) -> None:
    outbox = enabled_outbox(tmp_path)

    class InspectingTransport(Transport):
        def send(self, telegram_account, message, budget, cancellation):
            with sqlite3.connect(outbox.path) as connection:
                status = connection.execute(
                    "SELECT status FROM messages WHERE operation_id=?",
                    (message.operation_id,),
                ).fetchone()[0]
            assert status == "dispatching"
            return super().send(telegram_account, message, budget, cancellation)

    transport = InspectingTransport()
    result = outbox.send_message(
        operation_id="telegram_once",
        account=account(),
        chat_id=CHAT,
        text="Operational update.",
        authority=permit,
        transport=transport,
    )
    assert result.status == "accepted"
    assert result.provider_message_id == "81"
    assert outbox.status("telegram_once") == result
    assert len(transport.calls) == 1
    assert transport.calls[0][1].provider_payload() == {
        "chat_id": CHAT,
        "text": "Operational update.",
        "link_preview_options": {"is_disabled": True},
    }


def test_duplicate_replays_terminal_result_without_vault_or_transport(tmp_path) -> None:
    outbox = enabled_outbox(tmp_path)
    first_transport = Transport()
    first = outbox.send_message(
        operation_id="telegram_idempotent",
        account=account(),
        chat_id=CHAT,
        text="Exactly once.",
        authority=permit,
        transport=first_transport,
    )
    second_transport = Transport("unknown")
    replay = outbox.send_message(
        operation_id="telegram_idempotent",
        account=account(),
        chat_id=CHAT,
        text="Exactly once.",
        authority=permit,
        transport=second_transport,
    )
    assert replay == first
    assert len(first_transport.calls) == 1
    assert second_transport.calls == []
    with pytest.raises(TelegramDenied, match="idempotency"):
        outbox.send_message(
            operation_id="telegram_idempotent",
            account=account(),
            chat_id=CHAT,
            text="Changed body.",
            authority=permit,
            transport=second_transport,
        )


def test_unknown_and_receipt_divergence_require_reconciliation_without_retry(tmp_path) -> None:
    outbox = enabled_outbox(tmp_path)
    unknown = Transport("unknown")
    result = outbox.send_message(
        operation_id="telegram_unknown",
        account=account(),
        chat_id=CHAT,
        text="One provider call.",
        authority=permit,
        transport=unknown,
    )
    assert result.status == "reconciliation"
    assert result.detail == "provider_outcome_unknown"
    replay = outbox.send_message(
        operation_id="telegram_unknown",
        account=account(),
        chat_id=CHAT,
        text="One provider call.",
        authority=permit,
        transport=unknown,
    )
    assert replay == result
    assert len(unknown.calls) == 1

    mismatch = Transport("wrong_chat")
    mismatch_result = outbox.send_message(
        operation_id="telegram_mismatch",
        account=account(),
        chat_id=CHAT,
        text="Receipt must bind.",
        authority=permit,
        transport=mismatch,
    )
    assert mismatch_result.status == "reconciliation"
    assert len(mismatch.calls) == 1


def test_explicit_reconciliation_checks_status_scope_content_and_authority(tmp_path) -> None:
    outbox = enabled_outbox(tmp_path)
    unknown = outbox.send_message(
        operation_id="telegram_reconcile",
        account=account(),
        chat_id=CHAT,
        text="Verify out of band.",
        authority=permit,
        transport=Transport("unknown"),
    )
    proof = TelegramReconciliationProofV1(
        unknown.operation_id,
        TelegramReconciliationDecisionV1.CONFIRMED_ACCEPTED,
        CHAT,
        unknown.content_digest,
        "912",
    )
    with pytest.raises(TelegramDenied, match="authority"):
        outbox.reconcile(proof, authority=lambda *_args: False)
    accepted = outbox.reconcile(proof, authority=permit)
    assert accepted.status == "accepted"
    assert accepted.provider_message_id == "912"
    with pytest.raises(TelegramDenied, match="does not require"):
        outbox.reconcile(proof, authority=permit)

    second = outbox.send_message(
        operation_id="telegram_reconcile_not_sent",
        account=account(),
        chat_id=CHAT,
        text="Confirm absent.",
        authority=permit,
        transport=Transport("unknown"),
    )
    with pytest.raises(TelegramDenied, match="binding"):
        outbox.reconcile(
            TelegramReconciliationProofV1(
                second.operation_id,
                TelegramReconciliationDecisionV1.CONFIRMED_NOT_DISPATCHED,
                OTHER_CHAT,
                second.content_digest,
            ),
            authority=permit,
        )
    closed = outbox.reconcile(
        TelegramReconciliationProofV1(
            second.operation_id,
            TelegramReconciliationDecisionV1.CONFIRMED_NOT_DISPATCHED,
            CHAT,
            second.content_digest,
        ),
        authority=permit,
    )
    assert closed.status == "not_dispatched"
    assert closed.provider_message_id is None


def test_cancel_before_dispatch_is_durable_and_never_calls_transport(tmp_path) -> None:
    outbox = enabled_outbox(tmp_path)
    cancellation = TelegramCancellationV1()
    cancellation.cancel()
    transport = Transport()
    result = outbox.send_message(
        operation_id="telegram_cancelled",
        account=account(),
        chat_id=CHAT,
        text="Cancelled.",
        authority=permit,
        transport=transport,
        cancellation=cancellation,
    )
    assert result.status == "not_dispatched"
    assert transport.calls == []


def test_audit_and_receipt_never_contain_body_token_alias_or_chat(tmp_path) -> None:
    outbox = enabled_outbox(tmp_path)
    body = "Sensitive body marker Z9Q7."
    result = outbox.send_message(
        operation_id="telegram_redacted",
        account=account(),
        chat_id=CHAT,
        text=body,
        authority=permit,
        transport=Transport(),
    )
    raw = outbox.path.read_bytes()
    receipt = json.dumps(result.receipt_payload())
    assert body.encode() not in raw
    assert TOKEN not in raw
    assert account().secret_reference.account.encode() not in raw
    assert body not in receipt
    assert TOKEN.decode() not in receipt
    with sqlite3.connect(outbox.path) as connection:
        events = " ".join(
            row[0]
            for row in connection.execute("SELECT detail_json FROM message_events")
        )
    assert body not in events
    assert TOKEN.decode() not in events
    assert CHAT not in events


def test_interrupted_dispatch_becomes_reconciliation_on_reopen(tmp_path) -> None:
    path = (tmp_path / "interrupted.sqlite3").resolve()

    class FailpointOutbox(TelegramOfficialOutboxV1):
        def _after_dispatching_commit(self):
            raise SystemExit("exact post-commit failpoint")

    outbox = FailpointOutbox(
        path, gate=TelegramFeatureGateV1(True), clock=lambda: 1000.0
    )
    transport = Transport()

    with pytest.raises(SystemExit):
        outbox.send_message(
            operation_id="telegram_interrupted",
            account=account(),
            chat_id=CHAT,
            text="May have left the process.",
            authority=permit,
            transport=transport,
        )
    assert outbox.status("telegram_interrupted").status == "dispatching"
    assert transport.calls == []
    with sqlite3.connect(path) as connection:
        events = [
            row[0]
            for row in connection.execute(
                "SELECT event FROM message_events ORDER BY seq"
            )
        ]
    assert events == ["telegram.reserved", "telegram.dispatching"]
    outbox.close()
    reopened = TelegramOfficialOutboxV1(
        path, gate=TelegramFeatureGateV1(True), clock=lambda: 1061.0
    )
    recovered = reopened.status("telegram_interrupted")
    assert recovered.status == "reconciliation"
    closed = reopened.reconcile(
        TelegramReconciliationProofV1(
            recovered.operation_id,
            TelegramReconciliationDecisionV1.CONFIRMED_NOT_DISPATCHED,
            CHAT,
            recovered.content_digest,
        ),
        authority=permit,
    )
    assert closed.status == "not_dispatched"


def test_concurrent_opposite_reconciliation_proofs_have_one_winner(tmp_path) -> None:
    path = (tmp_path / "reconcile-race.sqlite3").resolve()
    first = TelegramOfficialOutboxV1(path, gate=TelegramFeatureGateV1(True))
    pending = first.send_message(
        operation_id="telegram_reconcile_race",
        account=account(),
        chat_id=CHAT,
        text="Race must have one winner.",
        authority=permit,
        transport=Transport("unknown"),
    )
    barrier = threading.Barrier(2)
    outcomes = []
    errors = []

    def authority(*_args):
        barrier.wait(timeout=5)
        return True

    proofs = (
        TelegramReconciliationProofV1(
            pending.operation_id,
            TelegramReconciliationDecisionV1.CONFIRMED_ACCEPTED,
            CHAT,
            pending.content_digest,
            "731",
        ),
        TelegramReconciliationProofV1(
            pending.operation_id,
            TelegramReconciliationDecisionV1.CONFIRMED_NOT_DISPATCHED,
            CHAT,
            pending.content_digest,
        ),
    )

    def run(outbox, proof):
        try:
            outcomes.append(outbox.reconcile(proof, authority=authority))
        except Exception as exc:
            errors.append(exc)

    threads = (
        threading.Thread(target=run, args=(first, proofs[0])),
        threading.Thread(target=run, args=(first, proofs[1])),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert len(outcomes) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], TelegramDenied)
    terminal = first.status(pending.operation_id)
    assert terminal.status in {"accepted", "not_dispatched"}


def test_second_live_instance_cannot_reconcile_owned_unknown(tmp_path) -> None:
    path = (tmp_path / "owned-reconciliation.sqlite3").resolve()
    first = TelegramOfficialOutboxV1(path, gate=TelegramFeatureGateV1(True))
    pending = first.send_message(
        operation_id="telegram_owned_reconciliation",
        account=account(),
        chat_id=CHAT,
        text="Only the lease owner may reconcile.",
        authority=permit,
        transport=Transport("unknown"),
    )
    second = TelegramOfficialOutboxV1(path, gate=TelegramFeatureGateV1(True))
    proof = TelegramReconciliationProofV1(
        pending.operation_id,
        TelegramReconciliationDecisionV1.CONFIRMED_NOT_DISPATCHED,
        CHAT,
        pending.content_digest,
    )
    with pytest.raises(TelegramDenied, match="lease is owned"):
        second.reconcile(proof, authority=permit)
    assert first.status(pending.operation_id).status == "reconciliation"
    assert first.reconcile(proof, authority=permit).status == "not_dispatched"


def test_second_live_instance_cannot_recover_active_dispatch(tmp_path) -> None:
    path = (tmp_path / "live-owner.sqlite3").resolve()
    first = TelegramOfficialOutboxV1(path, gate=TelegramFeatureGateV1(True))
    entered = threading.Event()
    release = threading.Event()
    results = []

    class BlockingTransport(Transport):
        def send(self, telegram_account, telegram_message, budget, cancellation):
            self.calls.append(
                (telegram_account, telegram_message, budget, cancellation)
            )
            entered.set()
            assert release.wait(timeout=10)
            return TelegramProviderReceiptV1(
                "442",
                telegram_message.chat_id,
                telegram_message.content_digest,
                time.time(),
            )

    transport = BlockingTransport()

    def run_first():
        results.append(
            first.send_message(
                operation_id="telegram_live_lease",
                account=account(),
                chat_id=CHAT,
                text="The active provider call must win.",
                authority=permit,
                transport=transport,
            )
        )

    worker = threading.Thread(target=run_first)
    worker.start()
    assert entered.wait(timeout=10)
    second = TelegramOfficialOutboxV1(path, gate=TelegramFeatureGateV1(True))
    assert second.status("telegram_live_lease").status == "dispatching"
    unused = Transport("unknown")
    duplicate = second.send_message(
        operation_id="telegram_live_lease",
        account=account(),
        chat_id=CHAT,
        text="The active provider call must win.",
        authority=permit,
        transport=unused,
    )
    assert duplicate.status == "dispatching"
    assert unused.calls == []
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert results[0].status == "accepted"
    assert results[0].provider_message_id == "442"
    assert second.status("telegram_live_lease") == results[0]


def test_every_sqlite_connection_is_closed_for_windows_lifecycle(tmp_path) -> None:
    root = tmp_path / "telegram-handles"
    path = (root / "outbox.sqlite3").resolve()
    outbox = TelegramOfficialOutboxV1(path, gate=TelegramFeatureGateV1(True))
    result = outbox.send_message(
        operation_id="telegram_handles",
        account=account(),
        chat_id=CHAT,
        text="Close every database handle.",
        authority=permit,
        transport=Transport(),
    )
    assert outbox.status(result.operation_id).status == "accepted"
    moved = tmp_path / "telegram-handles-moved"
    root.rename(moved)
    moved.rename(root)
    path.unlink()
    root.rmdir()


class Response:
    def __init__(self, status: int, payload: object, *, cancel=None) -> None:
        self.status = status
        self._raw = (
            payload if type(payload) is bytes else json.dumps(payload).encode("utf-8")
        )
        self._cancel = cancel

    def read(self, limit):
        if self._cancel is not None:
            self._cancel.cancel()
        return self._raw[:limit]


class Connection:
    def __init__(self, response: Response, observed: dict) -> None:
        self.response = response
        self.observed = observed

    def request(self, method, path, body, headers):
        self.observed["requests"] = self.observed.get("requests", 0) + 1
        self.observed.update(method=method, path=path, body=body, headers=headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.observed["closed"] = True


def stdlib_transport(response: Response, observed: dict, *, secret=TOKEN):
    def factory(origin, port, timeout, context):
        observed.update(origin=origin, port=port, timeout=timeout, context=context)
        return Connection(response, observed)

    return StdlibTelegramTransportV1(
        vault_reader=lambda _reference: secret,
        connection_factory=factory,
        clock=lambda: 1001.0,
    )


def message(text="Hello from Onyx.") -> TelegramMessageV1:
    item = account()
    return TelegramMessageV1(
        "telegram_transport",
        item.account_id,
        item.owner_profile_id,
        item.workspace_id,
        CHAT,
        text,
    )


_WIRE_IDS = count(1)


def wire_send(
    tmp_path,
    transport,
    *,
    telegram_account=None,
    telegram_message=None,
    budget=None,
    cancellation=None,
):
    scoped_account = account() if telegram_account is None else telegram_account
    scoped_message = message() if telegram_message is None else telegram_message
    sequence = next(_WIRE_IDS)
    outbox = TelegramOfficialOutboxV1(
        (tmp_path / f"wire-{sequence}.sqlite3").resolve(),
        gate=TelegramFeatureGateV1(True),
    )
    return outbox.send_message(
        operation_id=f"telegram_wire_{sequence}",
        account=scoped_account,
        chat_id=scoped_message.chat_id,
        text=scoped_message.text,
        authority=permit,
        transport=transport,
        budget=TelegramBudgetV1() if budget is None else budget,
        cancellation=(
            TelegramCancellationV1() if cancellation is None else cancellation
        ),
    )


def test_public_transport_denies_direct_calls_before_vault_and_http() -> None:
    assert not hasattr(telegram_connector, "_mint_dispatch_envelope_v1")
    assert not hasattr(StdlibTelegramTransportV1, "_send_from_validated_outbox")
    observed = {}
    response = Response(
        200,
        {
            "ok": True,
            "result": {
                "message_id": 812,
                "chat": {"id": int(CHAT)},
                "text": "Hello from Onyx.",
            },
        },
    )
    resolved = []

    def factory(origin, port, timeout, context):
        observed.update(origin=origin, port=port, timeout=timeout, context=context)
        return Connection(response, observed)

    transport = StdlibTelegramTransportV1(
        vault_reader=lambda reference: resolved.append(reference) or TOKEN,
        connection_factory=factory,
        clock=lambda: 1001.0,
    )
    with pytest.raises(TelegramNotDispatched, match="outbox_dispatch_required"):
        transport.send(
            account(),
            message(),
            TelegramBudgetV1(),
            TelegramCancellationV1(),
        )
    assert observed == {}
    assert resolved == []


@pytest.mark.parametrize(
    "changed_account,changed_message",
    [
        (
            account(owner="owner.secondary"),
            message(),
        ),
        (
            account(workspace="workspace.other"),
            message(),
        ),
        (
            account(account_id="telegram.other"),
            message(),
        ),
        (
            account(),
            TelegramMessageV1(
                "telegram_transport",
                "telegram.cyryx",
                "owner.primary",
                "workspace.main",
                OTHER_CHAT,
                "Hello from Onyx.",
            ),
        ),
    ],
)
def test_direct_transport_rejects_scope_or_chat_inputs(
    changed_account, changed_message
) -> None:
    observed = {}
    transport = stdlib_transport(Response(200, {}), observed)
    with pytest.raises(TelegramNotDispatched, match="outbox_dispatch_required"):
        transport.send(
            changed_account,
            changed_message,
            TelegramBudgetV1(),
            TelegramCancellationV1(),
        )
    assert observed == {}


def test_message_url_is_inert_content_and_never_an_operational_route(tmp_path) -> None:
    text = "Reference: https://example.invalid/report.pdf"
    scoped_message = message(text)
    payload = scoped_message.provider_payload()
    assert payload["text"] == text
    assert "url" not in payload
    assert "file" not in payload
    observed = {}
    transport = stdlib_transport(
        Response(
            200,
            {
                "ok": True,
                "result": {
                    "message_id": 913,
                    "chat": {"id": int(CHAT)},
                    "text": text,
                },
            },
        ),
        observed,
    )
    assert wire_send(
        tmp_path, transport, telegram_message=scoped_message
    ).provider_message_id == "913"
    assert observed["origin"] == TELEGRAM_ORIGIN
    assert observed["path"].endswith("/sendMessage")
    assert observed["requests"] == 1


def test_stdlib_transport_uses_only_official_https_route_and_exact_receipt(
    tmp_path,
) -> None:
    observed = {}
    resolved = []
    response = Response(
        200,
        {
            "ok": True,
            "result": {
                "message_id": 812,
                "chat": {"id": int(CHAT)},
                "text": "Hello from Onyx.",
            },
        },
    )
    def factory(origin, port, timeout, context):
        observed.update(origin=origin, port=port, timeout=timeout, context=context)
        return Connection(response, observed)

    transport = StdlibTelegramTransportV1(
        vault_reader=lambda reference: resolved.append(reference) or TOKEN,
        connection_factory=factory,
        clock=lambda: 1001.0,
    )
    receipt = wire_send(tmp_path, transport)
    assert receipt.status == "accepted"
    assert receipt.provider_message_id == "812"
    assert observed["origin"] == TELEGRAM_ORIGIN
    assert observed["port"] == 443
    assert observed["method"] == "POST"
    assert observed["path"] == f"/bot{TOKEN.decode()}/sendMessage"
    assert json.loads(observed["body"])["text"] == "Hello from Onyx."
    assert "parse_mode" not in json.loads(observed["body"])
    assert observed["closed"] is True
    assert transport.retry_count == 0
    assert transport.background_workers == 0
    assert resolved == [account().secret_reference]


def test_outbox_owns_wire_dispatch_only_after_atomic_commit(tmp_path) -> None:
    observed = {}
    response = Response(
        200,
        {
            "ok": True,
            "result": {
                "message_id": 990,
                "chat": {"id": int(CHAT)},
                "text": "Outbox-authorized wire call.",
            },
        },
    )
    transport = stdlib_transport(response, observed)
    outbox = enabled_outbox(tmp_path)
    result = outbox.send_message(
        operation_id="telegram_real_transport_boundary",
        account=account(),
        chat_id=CHAT,
        text="Outbox-authorized wire call.",
        authority=permit,
        transport=transport,
    )
    assert result.status == "accepted"
    assert result.provider_message_id == "990"
    assert observed["requests"] == 1


def test_stdlib_transport_forbids_redirects_and_never_exposes_provider_body(
    tmp_path,
) -> None:
    observed = {}
    transport = stdlib_transport(
        Response(302, {"description": TOKEN.decode(), "location": "https://evil.example"}),
        observed,
    )
    result = wire_send(tmp_path, transport)
    assert result.status == "rejected"
    assert TOKEN.decode() not in json.dumps(result.receipt_payload())
    assert observed["requests"] == 1


def test_stdlib_timeout_or_post_dispatch_cancel_is_unknown_not_retryable(
    tmp_path,
) -> None:
    class TimeoutConnection(Connection):
        def getresponse(self):
            raise TimeoutError("body and token must not escape")

    observed = {}

    def factory(origin, port, timeout, context):
        observed.update(origin=origin, port=port, timeout=timeout, context=context)
        return TimeoutConnection(Response(200, {}), observed)

    transport = StdlibTelegramTransportV1(
        vault_reader=lambda _reference: TOKEN,
        connection_factory=factory,
    )
    timeout = wire_send(tmp_path, transport)
    assert timeout.status == "reconciliation"
    assert TOKEN.decode() not in json.dumps(timeout.receipt_payload())
    assert transport.retry_count == 0

    cancellation = TelegramCancellationV1()
    after_dispatch = stdlib_transport(
        Response(
            200,
            {
                "ok": True,
                "result": {
                    "message_id": 1,
                    "chat": {"id": int(CHAT)},
                    "text": "Hello from Onyx.",
                },
            },
            cancel=cancellation,
        ),
        {},
    )
    cancelled = wire_send(
        tmp_path, after_dispatch, cancellation=cancellation
    )
    assert cancelled.status == "reconciliation"


def test_stdlib_missing_credential_and_pre_cancel_are_known_not_dispatched(
    tmp_path,
) -> None:
    observed = {}
    transport = stdlib_transport(Response(200, {}), observed, secret=None)
    assert wire_send(tmp_path, transport).status == "not_dispatched"
    assert observed == {}
    cancellation = TelegramCancellationV1()
    cancellation.cancel()
    assert wire_send(
        tmp_path,
        stdlib_transport(Response(200, {}), {}),
        cancellation=cancellation,
    ).status == "not_dispatched"


def test_transport_sanitizes_vault_and_connection_failures_and_enforces_budgets(
    tmp_path,
) -> None:
    def secret_failure(_reference):
        raise RuntimeError(TOKEN.decode())

    transport = StdlibTelegramTransportV1(vault_reader=secret_failure)
    vault_result = wire_send(tmp_path, transport)
    assert vault_result.status == "not_dispatched"
    assert TOKEN.decode() not in json.dumps(vault_result.receipt_payload())

    def connection_failure(*_args, **_kwargs):
        raise RuntimeError(TOKEN.decode())

    transport = StdlibTelegramTransportV1(
        vault_reader=lambda _reference: TOKEN,
        connection_factory=connection_failure,
    )
    connection_result = wire_send(tmp_path, transport)
    assert connection_result.status == "not_dispatched"
    assert TOKEN.decode() not in json.dumps(connection_result.receipt_payload())

    assert (
        wire_send(
            tmp_path,
            stdlib_transport(Response(200, {}), {}),
            budget=TelegramBudgetV1(maximum_request_bytes=1),
        ).status
        == "not_dispatched"
    )
    assert (
        wire_send(
            tmp_path,
            stdlib_transport(Response(200, b"12345"), {}),
            budget=TelegramBudgetV1(maximum_response_bytes=4),
        ).status
        == "reconciliation"
    )


def test_stdlib_receipt_wrong_chat_or_text_is_unknown(tmp_path) -> None:
    for result in (
        {"message_id": 1, "chat": {"id": int(OTHER_CHAT)}, "text": "Hello from Onyx."},
        {"message_id": 1, "chat": {"id": int(CHAT)}, "text": "Changed"},
        {"message_id": 0, "chat": {"id": int(CHAT)}, "text": "Hello from Onyx."},
    ):
        transport = stdlib_transport(Response(200, {"ok": True, "result": result}), {})
        assert wire_send(tmp_path, transport).status == "reconciliation"


def test_source_has_no_polling_webhook_or_generic_file_send() -> None:
    outbox_names = set(TelegramOfficialOutboxV1.__dict__)
    assert {"poll", "start_polling", "listen", "register_webhook"}.isdisjoint(outbox_names)
    outbox = TelegramOfficialOutboxV1.__new__(TelegramOfficialOutboxV1)
    assert "send_file" not in outbox_names
    assert "send_document" in outbox_names  # Bounded, exact-approved PDF upload.
    del outbox
