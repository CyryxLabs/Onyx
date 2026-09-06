from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from types import SimpleNamespace

import pytest

from core.google_workspace_connector_v1 import (
    READ_SCOPES,
    GoogleProviderReceiptV1,
    GoogleReadResultV1,
)
from core.google_workspace_host_v1 import (
    GoogleWorkspaceHostServiceV1,
    GoogleWorkspaceHostStatusV1,
    GoogleWorkspaceHostV1UnknownOutcome,
)
from core.google_workspace_audit_v1 import GoogleWorkspaceAuditStoreV1
from core.google_workspace_live_v1 import (
    ACTIONS,
    GoogleWorkspaceLiveAdapterV1,
    GoogleWorkspaceLiveV1ContractError,
    GoogleWorkspaceLiveV1Denied,
    GoogleWorkspaceLiveV1UnknownOutcome,
    TOOL_NAME,
    pseudonymize_live_identity_v1,
    tool_declaration_google_workspace_v1,
    validate_google_workspace_arguments_v1,
)


_BINDING = "b" * 64
_DIGEST = "d" * 64


def _status(*, connected: bool, reconciliation: str) -> GoogleWorkspaceHostStatusV1:
    return GoogleWorkspaceHostStatusV1(
        True,
        True,
        connected,
        "source-test",
        _BINDING,
        3,
        "available",
        READ_SCOPES,
        False,
        reconciliation,
    )


def _receipt(operation: str, status: str, *, items: int = 0) -> GoogleProviderReceiptV1:
    return GoogleProviderReceiptV1(
        operation,
        status,
        _BINDING,
        _DIGEST,
        "e" * 64,
        "f" * 64,
        items,
        1 if items else 0,
    )


def _adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    authorizer=None,
    audits: list[dict[str, object]] | None = None,
    store: GoogleWorkspaceAuditStoreV1 | None = None,
) -> tuple[GoogleWorkspaceLiveAdapterV1, GoogleWorkspaceHostServiceV1, SimpleNamespace]:
    state = SimpleNamespace(connected=True, calls=[])
    service = object.__new__(GoogleWorkspaceHostServiceV1)

    def status(_self):
        state.calls.append("status")
        return _status(
            connected=state.connected,
            reconciliation="connected" if state.connected else "revoked",
        )

    def connect(_self):
        state.calls.append("connect")
        state.connected = True
        return _receipt("authorize", "connected")

    def disconnect(_self):
        state.calls.append("disconnect")
        state.connected = False
        return _receipt("revoke", "revoked")

    def gmail(_self):
        state.calls.append("gmail")
        return GoogleReadResultV1(
            ({"id": "m-1", "thread_id": "t-1"},),
            False,
            _receipt("gmail_list", "complete", items=1),
        )

    def calendar(_self, *, time_min, time_max):
        state.calls.append(("calendar", time_min, time_max))
        return GoogleReadResultV1(
            ({
                "id": "e-1",
                "summary": "bounded",
                "start": {"dateTime": "2026-08-10T00:00:00Z"},
                "end": {"dateTime": "2026-08-10T01:00:00Z"},
            },),
            False,
            _receipt("calendar_list", "complete", items=1),
        )

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "status", status)
    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "connect", connect)
    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "disconnect", disconnect)
    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "test_gmail", gmail)
    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "test_calendar", calendar)
    observed = [] if audits is None else audits

    def audit(**kwargs):
        observed.append(kwargs)
        return SimpleNamespace(event_hash="a" * 64)

    identity = pseudonymize_live_identity_v1(
        owner_id="owner-primary",
        workspace_id="workspace-personal",
        account_id="owner@example.com",
        key=b"k" * 32,
    )
    adapter = GoogleWorkspaceLiveAdapterV1(
        service=service,
        audit_identity=identity,
        expected_binding_digest=_BINDING,
        central_authorizer=(
            (lambda _tool, _arguments: (True, "c" * 64))
            if authorizer is None
            else authorizer
        ),
        reservation_port=(
            store.reserve
            if store is not None
            else lambda **_kwargs: SimpleNamespace(state="claimed", result=None)
        ),
        denied_audit_port=(
            store.record_denied
            if store is not None
            else lambda **_kwargs: SimpleNamespace(
                trace_id="denied-trace", event_hash="9" * 64
            )
        ),
        audit_port=store.finalize if store is not None else audit,
        audit_verify_port=store.verify if store is not None else lambda **_kwargs: True,
    )
    return adapter, service, state


def test_declaration_is_one_exact_tool_and_five_action_schema() -> None:
    declaration = tool_declaration_google_workspace_v1()
    assert declaration["name"] == TOOL_NAME
    parameters = declaration["parameters"]
    assert parameters["additionalProperties"] is False
    assert tuple(parameters["properties"]["action"]["enum"]) == ACTIONS
    assert set(parameters["properties"]) == {
        "action",
        "query",
        "time_min",
        "time_max",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        None,
        {},
        {"action": " Status"},
        {"action": "STATUS"},
        {"action": "status", "owner_id": "model-owner"},
        {"action": "connect", "approved": True},
        {"action": "list_gmail_messages", "query": "is:Unread"},
        {"action": "list_gmail_messages", "query": " is:unread"},
        {"action": "list_calendar_events", "time_min": "2026-08-10T00:00:00Z"},
    ],
)
def test_strict_argument_rejection_precedes_host_and_policy(
    monkeypatch: pytest.MonkeyPatch, arguments
) -> None:
    policy_calls = []
    adapter, _service, state = _adapter(
        monkeypatch,
        authorizer=lambda *args: policy_calls.append(args) or (True, "c" * 64),
    )
    with pytest.raises(GoogleWorkspaceLiveV1ContractError):
        adapter.execute(arguments, trace_id="trace-1")
    assert state.calls == []
    assert policy_calls == []


def test_gmail_accepts_only_absent_or_exact_default() -> None:
    assert validate_google_workspace_arguments_v1(
        {"action": "list_gmail_messages"}
    ) == {"action": "list_gmail_messages", "query": "is:unread"}


@pytest.mark.parametrize(
    ("time_min", "time_max"),
    [
        ("2026-08-10T00:00:00", "2026-08-11T00:00:00Z"),
        ("2026-08-10T00:00:00Z", "2026-08-09T00:00:00Z"),
        ("2026-08-10T00:00:00+25:00", "2026-08-11T00:00:00Z"),
    ],
)
def test_calendar_requires_ordered_timezone_aware_rfc3339_before_host(
    monkeypatch: pytest.MonkeyPatch, time_min: str, time_max: str
) -> None:
    adapter, _service, state = _adapter(monkeypatch)
    with pytest.raises(GoogleWorkspaceLiveV1ContractError):
        adapter.execute(
            {
                "action": "list_calendar_events",
                "time_min": time_min,
                "time_max": time_max,
            },
            trace_id="trace-calendar-invalid",
        )
    assert state.calls == []
    assert validate_google_workspace_arguments_v1(
        {"action": "list_gmail_messages", "query": "is:unread"}
    ) == {"action": "list_gmail_messages", "query": "is:unread"}


def test_all_five_actions_route_only_through_public_host_and_postverify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audits: list[dict[str, object]] = []
    adapter, _service, state = _adapter(monkeypatch, audits=audits)
    status = adapter.execute({"action": "status"}, trace_id="trace-status")
    gmail = adapter.execute(
        {"action": "list_gmail_messages"}, trace_id="trace-gmail"
    )
    calendar = adapter.execute(
        {
            "action": "list_calendar_events",
            "time_min": "2026-08-10T00:00:00Z",
            "time_max": "2026-08-11T00:00:00Z",
        },
        trace_id="trace-calendar",
    )
    disconnected = adapter.execute(
        {"action": "disconnect"}, trace_id="trace-disconnect"
    )
    connected = adapter.execute({"action": "connect"}, trace_id="trace-connect")
    assert status["external_dispatch"] is False
    assert gmail["provider_read_only"] is True
    assert calendar["provider_read_only"] is True
    assert disconnected["postverified"] is True
    assert connected["postverified"] is True
    assert "gmail" in state.calls
    assert any(isinstance(item, tuple) and item[0] == "calendar" for item in state.calls)
    assert len(audits) == 5
    assert all(
        "owner-primary" not in repr(entry)
        and "owner@example.com" not in repr(entry)
        and "is:unread" not in repr(entry)
        for entry in audits
    )


def test_consequential_action_rejects_autonomous_or_model_style_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _service, state = _adapter(
        monkeypatch,
        authorizer=lambda _tool, _arguments: (
            True,
            "autonomous:google_workspace.connect",
        ),
    )
    with pytest.raises(GoogleWorkspaceLiveV1Denied) as raised:
        adapter.execute({"action": "connect"}, trace_id="trace-connect")
    assert "connect" not in state.calls
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_read_action_accepts_nonempty_trusted_autonomy_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _service, state = _adapter(
        monkeypatch,
        authorizer=lambda _tool, arguments: (
            arguments["action"] == "status",
            "autonomous:google_workspace.status",
        ),
    )
    response = adapter.execute({"action": "status"}, trace_id="trace-read")
    assert response["status"] == "succeeded"
    assert state.calls == ["status"]


def test_postverify_failure_after_provider_attempt_is_unknown_and_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _service, state = _adapter(monkeypatch)
    original_status = GoogleWorkspaceHostServiceV1.status

    def contradictory(self):
        value = original_status(self)
        if "connect" in state.calls:
            return _status(connected=False, reconciliation="revoked")
        return value

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "status", contradictory)
    state.connected = False
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome) as raised:
        adapter.execute({"action": "connect"}, trace_id="trace-unknown")
    assert state.calls.count("connect") == 1
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_contradictory_receipt_is_unknown_after_one_provider_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _service, state = _adapter(monkeypatch)

    def contradictory(_self):
        state.calls.append("connect")
        return _receipt("authorize", "complete")

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "connect", contradictory)
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome):
        adapter.execute({"action": "connect"}, trace_id="trace-receipt")
    assert state.calls.count("connect") == 1


def test_read_projection_rejects_unselected_provider_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _service, state = _adapter(monkeypatch)

    def gmail(_self):
        state.calls.append("gmail")
        return GoogleReadResultV1(
            ({"id": "m-1", "thread_id": "t-1", "snippet": "private"},),
            False,
            _receipt("gmail_list", "complete", items=1),
        )

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "test_gmail", gmail)
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome) as raised:
        adapter.execute(
            {"action": "list_gmail_messages"}, trace_id="trace-extra-field"
        )
    assert state.calls.count("gmail") == 1
    assert "private" not in str(raised.value)


def test_read_generation_drift_is_unknown_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _service, state = _adapter(monkeypatch)
    calls = 0

    def drifting_status(_self):
        nonlocal calls
        calls += 1
        value = _status(connected=True, reconciliation="connected")
        if calls > 1:
            return GoogleWorkspaceHostStatusV1(
                value.enabled,
                value.configured,
                value.connected,
                value.supported_backend,
                value.binding_digest,
                value.anchor_generation + 1,
                value.anchor_health,
                value.scopes,
                value.pending_loopback,
                value.reconciliation,
                value.trust_limit,
            )
        return value

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "status", drifting_status)
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome):
        adapter.execute(
            {"action": "list_gmail_messages"}, trace_id="trace-generation"
        )
    assert state.calls.count("gmail") == 1


def test_pre_provider_host_unknown_stays_denied_and_audited_as_not_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audits: list[dict[str, object]] = []
    adapter, _service, state = _adapter(monkeypatch, audits=audits)

    def unavailable(_self):
        raise GoogleWorkspaceHostV1UnknownOutcome("native secret")

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "status", unavailable)
    with pytest.raises(GoogleWorkspaceLiveV1Denied) as raised:
        adapter.execute({"action": "connect"}, trace_id="trace-pre-provider")
    contract = audits[0]["contract"]
    assert contract["outcome"]["provider_boundary"] == "not_reached"
    assert contract["outcome"]["completion"] == "denied"
    assert state.calls == []
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_concurrent_reads_remain_individually_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audits: list[dict[str, object]] = []
    adapter, _service, _state = _adapter(monkeypatch, audits=audits)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda index: adapter.execute(
                    {"action": "status"}, trace_id=f"trace-{index}"
                ),
                range(24),
            )
        )
    assert all(result["status"] == "succeeded" for result in results)
    assert len(audits) == 24


def test_audit_failure_after_read_is_unknown_and_never_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _service, state = _adapter(monkeypatch)
    adapter._audit = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("secret"))
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome) as raised:
        adapter.execute(
            {"action": "list_gmail_messages"}, trace_id="trace-audit"
        )
    assert state.calls.count("gmail") == 1
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_semantic_audit_is_exactly_once_durable_and_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    audits: list[dict[str, object]] = []
    adapter, _service, _state = _adapter(monkeypatch, audits=audits)
    adapter.execute({"action": "status"}, trace_id="trace-durable")
    assert len(audits) == 1
    contract = audits[0]["contract"]
    assert set(contract) == {
        "contract",
        "trace_id",
        "identity",
        "operation",
        "decision",
        "outcome",
    }
    assert "owner-primary" not in repr(contract)
    assert "owner@example.com" not in repr(contract)
    store = GoogleWorkspaceAuditStoreV1(
        path=tmp_path / "google-workspace-audit.sqlite3",
        authentication_key=b"a" * 32,
    )
    identity = contract["identity"]
    operation = contract["operation"]
    claim = store.reserve(
        binding_digest=identity["binding_digest"],
        action=operation["action"],
        argument_digest=operation["argument_digest"],
        idempotency_digest=operation["idempotency_digest"],
        trace_id=contract["trace_id"],
    )
    assert claim.state == "claimed"
    result = {
        "kind": "response",
        "payload": {
            "schema": "OnyxGoogleWorkspaceStatus.v1",
            "status": "succeeded",
            "action": "status",
            "result": {},
            "external_dispatch": False,
        },
    }
    reference = store.finalize(contract=contract, result=result)
    assert store.verify(
        contract=contract, result=result, event_hash=reference.event_hash
    )
    replay = store.reserve(
        binding_digest=identity["binding_digest"],
        action=operation["action"],
        argument_digest=operation["argument_digest"],
        idempotency_digest=operation["idempotency_digest"],
        trace_id="trace-replay",
    )
    assert replay.state == "completed"
    assert replay.result == result


def test_duplicate_connect_replays_without_second_provider_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = GoogleWorkspaceAuditStoreV1(
        path=tmp_path / "duplicate-connect.sqlite3",
        authentication_key=b"d" * 32,
    )
    adapter, _service, state = _adapter(monkeypatch, store=store)
    first = adapter.execute(
        {"action": "connect"},
        trace_id="trace-connect-first",
        idempotency_key="logical-connect-1",
    )
    second = adapter.execute(
        {"action": "connect"},
        trace_id="trace-connect-replay",
        idempotency_key="logical-connect-1",
    )
    assert first == second
    assert state.calls.count("connect") == 1
    with sqlite3.connect(tmp_path / "duplicate-connect.sqlite3") as database:
        assert database.execute(
            "SELECT COUNT(*) FROM logical_actions_v2"
        ).fetchone() == (1,)
        attempts = database.execute(
            "SELECT trace_id,classification,action,argument_digest,"
            "idempotency_digest,logical_event_hash,result_digest,event_hash "
            "FROM approved_attempts_v1 ORDER BY classification"
        ).fetchall()
    assert len(attempts) == 2
    assert {(row[0], row[1]) for row in attempts} == {
        ("trace-connect-first", "fresh"),
        ("trace-connect-replay", "replay"),
    }
    assert all(row[2] == "connect" for row in attempts)
    assert all(
        type(value) is str and len(value) == 64
        for row in attempts
        for value in row[3:]
    )
    with sqlite3.connect(tmp_path / "duplicate-connect.sqlite3") as database:
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                "UPDATE approved_attempts_v1 SET classification='fresh' "
                "WHERE trace_id='trace-connect-replay'"
            )
        database.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                "DELETE FROM approved_attempts_v1 "
                "WHERE trace_id='trace-connect-replay'"
            )
        database.rollback()


def test_replay_attempt_audit_failure_is_closed_without_provider_redispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    path = tmp_path / "replay-attempt-failure.sqlite3"
    store = GoogleWorkspaceAuditStoreV1(
        path=path,
        authentication_key=b"e" * 32,
    )
    adapter, _service, state = _adapter(monkeypatch, store=store)
    first = adapter.execute(
        {"action": "connect"},
        trace_id="trace-replay-audit-first",
        idempotency_key="logical-replay-audit",
    )
    original = GoogleWorkspaceAuditStoreV1._append_approved_attempt

    def fail_replay(self, database, **kwargs):
        if kwargs.get("classification") == "replay":
            raise RuntimeError("replay audit secret")
        return original(self, database, **kwargs)

    monkeypatch.setattr(
        GoogleWorkspaceAuditStoreV1,
        "_append_approved_attempt",
        fail_replay,
    )
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome):
        adapter.execute(
            {"action": "connect"},
            trace_id="trace-replay-audit-failed",
            idempotency_key="logical-replay-audit",
        )
    assert state.calls.count("connect") == 1
    with sqlite3.connect(path) as database:
        assert database.execute(
            "SELECT COUNT(*) FROM logical_actions_v2"
        ).fetchone() == (1,)
        assert database.execute(
            "SELECT COUNT(*) FROM approved_attempts_v1"
        ).fetchone() == (1,)

    monkeypatch.setattr(
        GoogleWorkspaceAuditStoreV1,
        "_append_approved_attempt",
        original,
    )
    replay = adapter.execute(
        {"action": "connect"},
        trace_id="trace-replay-audit-retry",
        idempotency_key="logical-replay-audit",
    )
    assert replay == first
    assert state.calls.count("connect") == 1
    with sqlite3.connect(path) as database:
        assert database.execute(
            "SELECT COUNT(*) FROM approved_attempts_v1"
        ).fetchone() == (2,)


def test_duplicate_read_replays_only_redacted_projection_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = GoogleWorkspaceAuditStoreV1(
        path=tmp_path / "duplicate-read.sqlite3",
        authentication_key=b"q" * 32,
    )
    adapter, _service, state = _adapter(monkeypatch, store=store)
    first = adapter.execute(
        {"action": "list_gmail_messages"},
        trace_id="trace-read-first",
        idempotency_key="logical-read-1",
    )
    second = adapter.execute(
        {"action": "list_gmail_messages"},
        trace_id="trace-read-replay",
        idempotency_key="logical-read-1",
    )
    assert first["items"] == [{"id": "m-1", "thread_id": "t-1"}]
    assert second["schema"] == "OnyxGoogleWorkspaceReadReplay.v1"
    assert second["replayed"] is True
    assert second["projection_digest"] == first["projection_digest"]
    assert "items" not in second
    assert "m-1" not in repr(second)
    assert state.calls.count("gmail") == 1
    store.close()
    for path in tmp_path.glob("duplicate-read.sqlite3*"):
        assert b"m-1" not in path.read_bytes()


def test_pending_claim_is_recovered_as_unknown_without_dispatch(tmp_path) -> None:
    path = tmp_path / "pending-recovery.sqlite3"
    store = GoogleWorkspaceAuditStoreV1(
        path=path, authentication_key=b"r" * 32
    )
    assert store.reserve(
        binding_digest="b" * 64,
        action="status",
        argument_digest="a" * 64,
        idempotency_digest="c" * 64,
        trace_id="trace-pending",
    ).state == "claimed"
    recovered = GoogleWorkspaceAuditStoreV1(
        path=path, authentication_key=b"r" * 32
    )
    assert recovered.reserve(
        binding_digest="b" * 64,
        action="status",
        argument_digest="a" * 64,
        idempotency_digest="c" * 64,
        trace_id="trace-after-restart",
    ).state == "unknown"


def test_replay_with_different_authentication_key_is_unknown_without_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    path = tmp_path / "wrong-key.sqlite3"
    first_store = GoogleWorkspaceAuditStoreV1(
        path=path, authentication_key=b"a" * 32
    )
    first, _service, first_state = _adapter(monkeypatch, store=first_store)
    first.execute(
        {"action": "status"},
        trace_id="trace-key-first",
        idempotency_key="same-logical-status",
    )
    assert first_state.calls == ["status"]
    second_store = GoogleWorkspaceAuditStoreV1(
        path=path, authentication_key=b"z" * 32
    )
    second, _service, second_state = _adapter(monkeypatch, store=second_store)
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome) as raised:
        second.execute(
            {"action": "status"},
            trace_id="trace-key-second",
            idempotency_key="same-logical-status",
        )
    assert second_state.calls == []
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_tampered_audit_schema_is_unknown_without_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    path = tmp_path / "tampered-schema.sqlite3"
    store = GoogleWorkspaceAuditStoreV1(
        path=path, authentication_key=b"s" * 32
    )
    first, _service, _state = _adapter(monkeypatch, store=store)
    first.execute(
        {"action": "status"},
        trace_id="trace-schema-first",
        idempotency_key="schema-logical-status",
    )
    with sqlite3.connect(path) as database:
        database.execute("DROP TRIGGER logical_actions_v2_no_delete")
    second, _service, state = _adapter(monkeypatch, store=store)
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome):
        second.execute(
            {"action": "status"},
            trace_id="trace-schema-second",
            idempotency_key="schema-logical-status",
        )
    assert state.calls == []


def test_tampered_authenticated_event_is_unknown_without_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    path = tmp_path / "tampered-event.sqlite3"
    store = GoogleWorkspaceAuditStoreV1(
        path=path, authentication_key=b"e" * 32
    )
    first, _service, first_state = _adapter(monkeypatch, store=store)
    first.execute(
        {"action": "status"},
        trace_id="trace-event-first",
        idempotency_key="event-logical-status",
    )
    assert first_state.calls == ["status"]
    with sqlite3.connect(path) as database:
        database.execute("DROP TRIGGER logical_actions_v2_final_immutable")
        database.execute(
            "UPDATE logical_actions_v2 SET event_hash=?",
            ("0" * 64,),
        )
        database.execute(
            """CREATE TRIGGER logical_actions_v2_final_immutable
            BEFORE UPDATE ON logical_actions_v2 WHEN OLD.state!='pending'
            BEGIN SELECT RAISE(ABORT,'final Google action is immutable'); END"""
        )
    second, _service, second_state = _adapter(monkeypatch, store=store)
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome) as raised:
        second.execute(
            {"action": "status"},
            trace_id="trace-event-second",
            idempotency_key="event-logical-status",
        )
    assert second_state.calls == []
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_idempotency_collision_between_actions_never_replays_or_dispatches(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = GoogleWorkspaceAuditStoreV1(
        path=tmp_path / "action-collision.sqlite3",
        authentication_key=b"c" * 32,
    )
    adapter, _service, state = _adapter(monkeypatch, store=store)
    adapter.execute(
        {"action": "status"},
        trace_id="trace-collision-status",
        idempotency_key="same-logical-id",
    )
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome):
        adapter.execute(
            {"action": "connect"},
            trace_id="trace-collision-connect",
            idempotency_key="same-logical-id",
        )
    assert state.calls == ["status"]


def test_idempotency_collision_between_argument_digests_never_dispatches(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = GoogleWorkspaceAuditStoreV1(
        path=tmp_path / "argument-collision.sqlite3",
        authentication_key=b"g" * 32,
    )
    adapter, _service, state = _adapter(monkeypatch, store=store)
    adapter.execute(
        {
            "action": "list_calendar_events",
            "time_min": "2026-08-10T00:00:00Z",
            "time_max": "2026-08-11T00:00:00Z",
        },
        trace_id="trace-argument-first",
        idempotency_key="same-calendar-logical-id",
    )
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome) as raised:
        adapter.execute(
            {
                "action": "list_calendar_events",
                "time_min": "2026-08-12T00:00:00Z",
                "time_max": "2026-08-13T00:00:00Z",
            },
            trace_id="trace-argument-second",
            idempotency_key="same-calendar-logical-id",
        )
    assert sum(
        type(call) is tuple and call[0] == "calendar" for call in state.calls
    ) == 1
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_validation_and_authorization_precede_durable_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    adapter, _service, _state = _adapter(monkeypatch)

    def authorize(_tool, _arguments):
        order.append("authorize")
        return True, "p" * 64

    def reserve(**kwargs):
        order.append("reserve")
        assert kwargs["action"] == "status"
        assert kwargs["argument_digest"] == "c725469e2b09851166cc6c037cb8c4b5d743e9c17da53d43066e6750dd6ec0b5"
        return SimpleNamespace(state="claimed", result=None)

    adapter._authorizer = authorize
    adapter._reserve = reserve
    adapter.execute({"action": "status"}, trace_id="trace-order")
    assert order == ["authorize", "reserve"]


def test_status_rejects_integer_values_for_boolean_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _service, state = _adapter(monkeypatch)

    def invalid_status(_self):
        state.calls.append("status-invalid-bool")
        return GoogleWorkspaceHostStatusV1(
            1,
            True,
            True,
            "source-test",
            _BINDING,
            3,
            "available",
            READ_SCOPES,
            False,
            "connected",
        )

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "status", invalid_status)
    with pytest.raises(GoogleWorkspaceLiveV1Denied) as raised:
        adapter.execute({"action": "status"}, trace_id="trace-bool-contract")
    assert state.calls == ["status-invalid-bool"]
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_denied_attempt_is_exactly_once_and_approved_retry_can_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    path = tmp_path / "denied-separate-idempotency.sqlite3"
    store = GoogleWorkspaceAuditStoreV1(
        path=path, authentication_key=b"n" * 32
    )
    policy = {"approved": False}

    def authorize(_tool, _arguments):
        return policy["approved"], "c" * 64

    adapter, _service, state = _adapter(
        monkeypatch, authorizer=authorize, store=store
    )
    for trace in ("trace-denied-first", "trace-denied-repeat"):
        with pytest.raises(GoogleWorkspaceLiveV1Denied):
            adapter.execute(
                {"action": "connect"},
                trace_id=trace,
                idempotency_key="same-approved-retry",
            )
    assert state.calls == []
    with sqlite3.connect(path) as database:
        assert database.execute(
            "SELECT COUNT(*) FROM denied_attempts_v1"
        ).fetchone() == (2,)
        assert database.execute(
            "SELECT COUNT(DISTINCT trace_id) FROM denied_attempts_v1"
        ).fetchone() == (2,)
        assert database.execute(
            "SELECT COUNT(*) FROM logical_actions_v2"
        ).fetchone() == (0,)
    policy["approved"] = True
    result = adapter.execute(
        {"action": "connect"},
        trace_id="trace-approved-retry",
        idempotency_key="same-approved-retry",
    )
    assert result["status"] == "succeeded"
    assert state.calls.count("connect") == 1
    with sqlite3.connect(path) as database:
        assert database.execute(
            "SELECT COUNT(*) FROM denied_attempts_v1"
        ).fetchone() == (2,)
        assert database.execute(
            "SELECT COUNT(*) FROM logical_actions_v2"
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    "field",
    ["supported_backend", "binding_digest", "anchor_health", "scope", "reconciliation", "trust_limit"],
)
def test_status_rejects_string_subclasses(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    class DerivedString(str):
        pass

    adapter, _service, state = _adapter(monkeypatch)

    def invalid_status(_self):
        values = {
            "supported_backend": "source-test",
            "binding_digest": _BINDING,
            "anchor_health": "available",
            "scopes": READ_SCOPES,
            "reconciliation": "connected",
            "trust_limit": "source-test",
        }
        if field == "scope":
            values["scopes"] = (DerivedString(READ_SCOPES[0]), READ_SCOPES[1])
        else:
            values[field] = DerivedString(values[field])
        state.calls.append("status-string-subclass")
        return GoogleWorkspaceHostStatusV1(
            True,
            True,
            True,
            values["supported_backend"],
            values["binding_digest"],
            3,
            values["anchor_health"],
            values["scopes"],
            False,
            values["reconciliation"],
            values["trust_limit"],
        )

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "status", invalid_status)
    with pytest.raises(GoogleWorkspaceLiveV1Denied):
        adapter.execute({"action": "status"}, trace_id=f"trace-str-{field}")
    assert state.calls == ["status-string-subclass"]


@pytest.mark.parametrize(
    "field",
    ["operation", "status", "binding_digest", "request_digest", "response_digest", "grant_digest"],
)
def test_receipt_rejects_string_subclasses(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    class DerivedString(str):
        pass

    adapter, _service, state = _adapter(monkeypatch)

    def invalid_connect(_self):
        state.calls.append("connect-string-subclass")
        values = {
            "operation": "authorize",
            "status": "connected",
            "binding_digest": _BINDING,
            "request_digest": _DIGEST,
            "response_digest": "e" * 64,
            "grant_digest": "f" * 64,
        }
        values[field] = DerivedString(values[field])
        return GoogleProviderReceiptV1(
            values["operation"],
            values["status"],
            values["binding_digest"],
            values["request_digest"],
            values["response_digest"],
            values["grant_digest"],
            0,
            0,
        )

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "connect", invalid_connect)
    with pytest.raises(GoogleWorkspaceLiveV1UnknownOutcome):
        adapter.execute(
            {"action": "connect"}, trace_id=f"trace-receipt-str-{field}"
        )
    assert state.calls.count("connect-string-subclass") == 1
