from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import pytest

from core.phase8_microsoft_graph_calendar_v1 import (
    FEATURE_FLAG,
    WRITE_SCOPES,
    EventMutationGrantV1,
    GraphCalendarFeatureGateV1,
    GraphCalendarV1ContractError,
    GraphCalendarV1Denied,
    GraphCalendarV1Error,
    GraphCalendarV1Uncertain,
    StdlibGraphMutationHttpV1,
    create_microsoft_graph_calendar_v1,
    find_conflicts,
    free_slots,
    issue_event_mutation_grant_v1,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import JsonHttpResponseV1
from core.phase8_microsoft_graph_read_v1 import CalendarEventV1, LocalEventDraftV1

ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1_785_000_000_000
NOW_S = 1_785_000_000
KEY = bytes(range(1, 33))
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ACCOUNT_ID = "owner@cyryxlabs.com"
NONCE = "ab" * 16


def _event(
    start: str,
    end: str,
    *,
    cancelled: bool = False,
    zone: str = "UTC",
    subject: str = "Busy",
) -> CalendarEventV1:
    return CalendarEventV1(
        "evt-" + start,
        subject,
        start,
        end,
        zone,
        "",
        "organizer@cyryxlabs.com",
        (),
        False,
        cancelled,
        "https://outlook.office.com/x",
    )


def _draft(**changes: object) -> LocalEventDraftV1:
    values: dict[str, object] = {
        "subject": "Planning sync",
        "start": "2026-07-25T14:00:00+00:00",
        "end": "2026-07-25T14:30:00+00:00",
        "timezone": "UTC",
        "location": "",
        "attendees": (),
        "body_text": "Agenda",
        "draft_sha256": hashlib.sha256(b"planning-sync").hexdigest(),
    }
    values.update(changes)
    return LocalEventDraftV1(**values)  # type: ignore[arg-type]


def _onboarding() -> MicrosoftGraphLiveOnboardingV1:
    return MicrosoftGraphLiveOnboardingV1(CLIENT_ID, TENANT_ID, ACCOUNT_ID)


@dataclass(frozen=True)
class Queued:
    method: str
    response: JsonHttpResponseV1


class FakeHttp:
    def __init__(self, responses: Iterable[object] = ()) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, object]] = []

    def _next(self, method: str) -> JsonHttpResponseV1:
        if not self.responses:
            raise AssertionError(f"unexpected {method} request")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        assert item.method == method
        return item.response

    def post_form(self, *, url, fields, timeout_seconds):
        assert timeout_seconds == 30
        self.calls.append(("POST_FORM", url, fields))
        return self._next("POST_FORM")

    def post_json(self, *, url, payload, headers, timeout_seconds):
        assert timeout_seconds == 30
        self.calls.append(("POST_JSON", url, payload))
        return self._next("POST_JSON")

    def get_json(self, *, url, query, headers, timeout_seconds):
        assert timeout_seconds == 30
        self.calls.append(("GET", url, query))
        return self._next("GET")


class FakeVault:
    def __init__(self, value: str | None = "refresh-token-1") -> None:
        self.value = value
        self.writes: list[str] = []

    def get_refresh_token(self):
        return self.value

    def set_refresh_token(self, value: str) -> None:
        self.value = value
        self.writes.append(value)

    def delete_refresh_token(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


def _write_token_response(
    *, scopes: str = "Calendars.ReadWrite User.Read", refresh: str | None = None
) -> JsonHttpResponseV1:
    payload: dict[str, object] = {
        "token_type": "Bearer",
        "access_token": "write-access-1",
        "expires_in": 3600,
        "scope": scopes,
    }
    if refresh is not None:
        payload["refresh_token"] = refresh
    return Queued("POST_FORM", JsonHttpResponseV1(200, payload))


def _created_response(event_id: str = "event-1") -> Queued:
    return Queued(
        "POST_JSON",
        JsonHttpResponseV1(
            201,
            {"id": event_id, "webLink": "https://outlook.office.com/e/1"},
            (("request-id", "req-1"),),
        ),
    )


def _echo_response(draft: LocalEventDraftV1, *, subject: str | None = None) -> Queued:
    return Queued(
        "GET",
        JsonHttpResponseV1(
            200,
            {
                "id": "event-1",
                "subject": draft.subject if subject is None else subject,
                "start": {"dateTime": draft.start},
                "end": {"dateTime": draft.end},
            },
        ),
    )


def _session(http: FakeHttp, vault: FakeVault | None = None):
    return create_microsoft_graph_calendar_v1(
        gate=GraphCalendarFeatureGateV1(True),
        onboarding=_onboarding(),
        http=http,
        vault=FakeVault() if vault is None else vault,
        integrity_key=KEY,
        clock_ms=lambda: NOW_MS + 1,
        clock_epoch_s=lambda: NOW_S,
        project_root=ROOT,
    )


def _grant(draft: LocalEventDraftV1, **changes: object) -> EventMutationGrantV1:
    grant = issue_event_mutation_grant_v1(
        integrity_key=KEY,
        workspace_id="cyryx-live-e2e",
        principal_id="owner:live-e2e",
        account_id=ACCOUNT_ID,
        draft=draft,
        nonce=NONCE,
        now_ms=NOW_MS,
    )
    return replace(grant, **changes) if changes else grant


def test_feature_gate_is_exact_and_default_off() -> None:
    assert not GraphCalendarFeatureGateV1.from_environ({}).enabled
    assert GraphCalendarFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "yes"):
        assert not GraphCalendarFeatureGateV1.from_environ(
            {FEATURE_FLAG: value}
        ).enabled
    assert (
        create_microsoft_graph_calendar_v1(
            gate=GraphCalendarFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


def test_factory_is_sealed_complete_and_bound_to_accepted_live_e2e(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GraphCalendarV1ContractError, match="sealed feature gate"):
        create_microsoft_graph_calendar_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(GraphCalendarV1ContractError, match="complete bindings"):
        create_microsoft_graph_calendar_v1(
            gate=GraphCalendarFeatureGateV1(True),
            onboarding=_onboarding(),
            project_root=ROOT,
        )
    with pytest.raises(GraphCalendarV1ContractError, match="integrity key"):
        create_microsoft_graph_calendar_v1(
            gate=GraphCalendarFeatureGateV1(True),
            onboarding=_onboarding(),
            http=FakeHttp(),
            vault=FakeVault(),
            integrity_key=b"short",
            clock_ms=lambda: NOW_MS,
            clock_epoch_s=lambda: NOW_S,
            project_root=ROOT,
        )
    monkeypatch.setattr(
        "core.phase8_microsoft_graph_calendar_v1.ACCEPTED_LIVE_E2E_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(GraphCalendarV1Denied, match="evidence unavailable"):
        create_microsoft_graph_calendar_v1(
            gate=GraphCalendarFeatureGateV1(True),
            project_root=ROOT,
        )


def test_find_conflicts_detects_overlaps_and_ignores_cancelled() -> None:
    events = (
        _event("2026-07-25T13:00:00", "2026-07-25T14:15:00"),
        _event("2026-07-25T14:30:00", "2026-07-25T15:00:00"),
        _event("2026-07-25T10:00:00", "2026-07-25T11:00:00"),
        _event("2026-07-25T13:30:00", "2026-07-25T16:00:00", cancelled=True),
    )
    conflicts = find_conflicts(
        events,
        window_start="2026-07-25T14:00:00Z",
        window_end="2026-07-25T14:30:00Z",
    )
    assert [item.start for item in conflicts] == ["2026-07-25T13:00:00"]
    touching = find_conflicts(
        (_event("2026-07-25T14:30:00", "2026-07-25T15:00:00"),),
        window_start="2026-07-25T14:00:00Z",
        window_end="2026-07-25T14:30:00Z",
    )
    assert touching == ()


def test_find_conflicts_rejects_bad_windows_and_non_utc() -> None:
    with pytest.raises(GraphCalendarV1ContractError, match="inverted"):
        find_conflicts(
            (),
            window_start="2026-07-25T15:00:00Z",
            window_end="2026-07-25T14:00:00Z",
        )
    with pytest.raises(GraphCalendarV1Denied, match="non-UTC"):
        find_conflicts(
            (_event("2026-07-25T13:00:00", "2026-07-25T14:15:00", zone="E. South America Standard Time"),),
            window_start="2026-07-25T14:00:00Z",
            window_end="2026-07-25T14:30:00Z",
        )


def test_free_slots_are_deterministic_and_bounded() -> None:
    events = (
        _event("2026-07-25T10:00:00", "2026-07-25T11:00:00"),
        _event("2026-07-25T12:00:00", "2026-07-25T13:00:00"),
    )
    slots = free_slots(
        events,
        window_start="2026-07-25T09:00:00Z",
        window_end="2026-07-25T14:00:00Z",
        duration_minutes=60,
    )
    assert slots == (
        ("2026-07-25T09:00:00+00:00", "2026-07-25T10:00:00+00:00"),
        ("2026-07-25T11:00:00+00:00", "2026-07-25T12:00:00+00:00"),
        ("2026-07-25T13:00:00+00:00", "2026-07-25T14:00:00+00:00"),
    )
    assert (
        free_slots(
            events,
            window_start="2026-07-25T10:00:00Z",
            window_end="2026-07-25T11:00:00Z",
            duration_minutes=60,
        )
        == ()
    )
    limited = free_slots(
        (),
        window_start="2026-07-25T09:00:00Z",
        window_end="2026-07-25T18:00:00Z",
        duration_minutes=30,
        max_slots=3,
    )
    assert len(limited) == 3
    with pytest.raises(GraphCalendarV1ContractError, match="slot parameters"):
        free_slots((), window_start="2026-07-25T09:00:00Z",
                   window_end="2026-07-25T10:00:00Z", duration_minutes=1)


def test_grant_issue_and_tamper_matrix() -> None:
    draft = _draft()
    grant = _grant(draft)
    assert grant.draft_sha256 == draft.draft_sha256
    with pytest.raises(GraphCalendarV1ContractError, match="TTL"):
        issue_event_mutation_grant_v1(
            integrity_key=KEY,
            workspace_id="w",
            principal_id="p",
            account_id=ACCOUNT_ID,
            draft=draft,
            nonce=NONCE,
            now_ms=NOW_MS,
            ttl_ms=999_999_999,
        )
    with pytest.raises(GraphCalendarV1ContractError, match="grant is invalid"):
        replace(grant, nonce="not-a-nonce")


def test_create_event_happy_path_receipt_and_one_shot_grant() -> None:
    draft = _draft()
    http = FakeHttp(
        [
            _write_token_response(refresh="refresh-token-2"),
            _created_response(),
            _echo_response(draft),
        ]
    )
    vault = FakeVault()
    session = _session(http, vault)
    assert session is not None
    grant = _grant(draft)
    receipt = session.create_event(draft=draft, grant=grant)
    assert receipt.event_id == "event-1"
    assert receipt.reconciled is True
    assert receipt.provider_request_id == "req-1"
    assert receipt.draft_sha256 == draft.draft_sha256
    assert vault.value == "refresh-token-2"
    kind, url, fields = http.calls[0]
    assert kind == "POST_FORM"
    assert dict(fields)["scope"] == " ".join(sorted(WRITE_SCOPES, key=str.casefold))
    kind, url, payload = http.calls[1]
    assert (kind, url) == ("POST_JSON", "https://graph.microsoft.com/v1.0/me/events")
    assert payload["subject"] == draft.subject
    assert "attendees" not in payload
    serialized = repr(receipt)
    assert "write-access-1" not in serialized
    assert "refresh-token" not in serialized
    with pytest.raises(GraphCalendarV1Denied, match="already used"):
        session.create_event(draft=draft, grant=grant)


def test_grant_validation_denies_before_any_network() -> None:
    draft = _draft()
    http = FakeHttp()
    session = _session(http)
    assert session is not None
    cases = [
        (_grant(draft, signature="0" * 64), "signature is invalid"),
        (_grant(draft, account_id="other@cyryxlabs.com"), "signature is invalid"),
        (
            _grant(_draft(subject="Other", draft_sha256=hashlib.sha256(b"o").hexdigest())),
            "exact draft",
        ),
        (
            issue_event_mutation_grant_v1(
                integrity_key=KEY,
                workspace_id="cyryx-live-e2e",
                principal_id="owner:live-e2e",
                account_id=ACCOUNT_ID,
                draft=draft,
                nonce=NONCE,
                now_ms=NOW_MS - 500_000,
                ttl_ms=1_000,
            ),
            "expired",
        ),
    ]
    for grant, message in cases:
        with pytest.raises(GraphCalendarV1Denied, match=message):
            session.create_event(draft=draft, grant=grant)
    assert http.calls == []


def test_attendee_drafts_are_denied_at_issuance_and_creation() -> None:
    draft = _draft(attendees=("guest@example.com",))
    with pytest.raises(GraphCalendarV1Denied, match="attendee invitations"):
        issue_event_mutation_grant_v1(
            integrity_key=KEY,
            workspace_id="cyryx-live-e2e",
            principal_id="owner:live-e2e",
            account_id=ACCOUNT_ID,
            draft=draft,
            nonce=NONCE,
            now_ms=NOW_MS,
        )
    plain = _draft()
    grant = _grant(plain)
    http = FakeHttp()
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphCalendarV1Denied, match="attendee invitations"):
        session.create_event(draft=draft, grant=grant)
    assert http.calls == []


def test_grant_payload_is_unambiguous_across_field_boundaries() -> None:
    draft = _draft()
    left = issue_event_mutation_grant_v1(
        integrity_key=KEY,
        workspace_id="alpha",
        principal_id="beta:owner",
        account_id=ACCOUNT_ID,
        draft=draft,
        nonce=NONCE,
        now_ms=NOW_MS,
    )
    right = issue_event_mutation_grant_v1(
        integrity_key=KEY,
        workspace_id="alphabeta",
        principal_id="owner",
        account_id=ACCOUNT_ID,
        draft=draft,
        nonce=NONCE,
        now_ms=NOW_MS,
    )
    assert left.signature != right.signature
    for bad in ("", "with\x00null", "line\nbreak", "x" * 300):
        with pytest.raises(GraphCalendarV1ContractError):
            issue_event_mutation_grant_v1(
                integrity_key=KEY,
                workspace_id=bad,
                principal_id="owner",
                account_id=ACCOUNT_ID,
                draft=draft,
                nonce=NONCE,
                now_ms=NOW_MS,
            )


def test_free_slots_rejects_unbounded_and_non_tuple_events() -> None:
    with pytest.raises(GraphCalendarV1ContractError, match="event collection"):
        free_slots(
            [_event("2026-07-25T10:00:00", "2026-07-25T11:00:00")],  # type: ignore[arg-type]
            window_start="2026-07-25T09:00:00Z",
            window_end="2026-07-25T18:00:00Z",
            duration_minutes=30,
        )
    huge = tuple(
        _event(f"2026-07-25T{h:02d}:00:00", f"2026-07-25T{h:02d}:30:00")
        for h in range(24)
    ) * 30
    with pytest.raises(GraphCalendarV1ContractError, match="event collection"):
        free_slots(
            huge,
            window_start="2026-07-25T09:00:00Z",
            window_end="2026-07-25T18:00:00Z",
            duration_minutes=30,
        )


def test_missing_write_scope_denies_before_mutation() -> None:
    draft = _draft()
    http = FakeHttp([_write_token_response(scopes="Calendars.Read User.Read")])
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphCalendarV1Denied, match="write scope"):
        session.create_event(draft=draft, grant=_grant(draft))
    assert len(http.calls) == 1


def test_throttle_and_rejection_do_not_auto_retry() -> None:
    draft = _draft()
    throttled = FakeHttp(
        [
            _write_token_response(),
            Queued("POST_JSON", JsonHttpResponseV1(429, {}, (("Retry-After", "7"),))),
        ]
    )
    session = _session(throttled)
    assert session is not None
    with pytest.raises(GraphCalendarV1Error, match="fresh grant"):
        session.create_event(draft=draft, grant=_grant(draft))
    assert len([c for c in throttled.calls if c[0] == "POST_JSON"]) == 1

    rejected = FakeHttp(
        [
            _write_token_response(),
            Queued("POST_JSON", JsonHttpResponseV1(403, {"error": {"code": "x"}})),
        ]
    )
    session2 = _session(rejected)
    assert session2 is not None
    with pytest.raises(GraphCalendarV1Error, match="rejected"):
        session2.create_event(draft=draft, grant=_grant(draft))


def test_uncertain_outcome_requires_reconciliation_before_retry() -> None:
    draft = _draft()
    http = FakeHttp(
        [
            _write_token_response(),
            GraphCalendarV1Uncertain("provider outcome unknown"),
        ]
    )
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphCalendarV1Uncertain):
        session.create_event(draft=draft, grant=_grant(draft))

    found = FakeHttp(
        [
            Queued(
                "GET",
                JsonHttpResponseV1(
                    200,
                    {
                        "value": [
                            {
                                "id": "event-9",
                                "subject": draft.subject,
                                "webLink": "https://outlook.office.com/e/9",
                            }
                        ]
                    },
                ),
            ),
            Queued(
                "GET",
                JsonHttpResponseV1(
                    200,
                    {
                        "id": "event-9",
                        "subject": draft.subject,
                        "start": {"dateTime": draft.start},
                        "end": {"dateTime": draft.end},
                    },
                ),
            ),
        ]
    )
    session_found = _session(found)
    assert session_found is not None
    session_found._access_token = "write-access-1"
    session_found._access_expires_at = NOW_S + 3600
    receipt = session_found.reconcile_uncertain(draft=draft)
    assert receipt is not None and receipt.event_id == "event-9"
    assert receipt.reconciled is True

    absent = FakeHttp([Queued("GET", JsonHttpResponseV1(200, {"value": []}))])
    session_absent = _session(absent)
    assert session_absent is not None
    session_absent._access_token = "write-access-1"
    session_absent._access_expires_at = NOW_S + 3600
    assert session_absent.reconcile_uncertain(draft=draft) is None


def test_reconciliation_mismatch_yields_unreconciled_receipt() -> None:
    draft = _draft()
    http = FakeHttp(
        [
            _write_token_response(),
            _created_response(),
            _echo_response(draft, subject="Different subject"),
        ]
    )
    session = _session(http)
    assert session is not None
    receipt = session.create_event(draft=draft, grant=_grant(draft))
    assert receipt.reconciled is False


def test_access_token_is_cached_across_mutations() -> None:
    first = _draft()
    second = _draft(
        subject="Second sync",
        draft_sha256=hashlib.sha256(b"second").hexdigest(),
    )
    http = FakeHttp(
        [
            _write_token_response(),
            _created_response("event-1"),
            _echo_response(first),
            _created_response("event-2"),
            Queued(
                "GET",
                JsonHttpResponseV1(
                    200,
                    {
                        "id": "event-2",
                        "subject": second.subject,
                        "start": {"dateTime": second.start},
                        "end": {"dateTime": second.end},
                    },
                ),
            ),
        ]
    )
    session = _session(http)
    assert session is not None
    session.create_event(draft=first, grant=_grant(first))
    second_grant = issue_event_mutation_grant_v1(
        integrity_key=KEY,
        workspace_id="cyryx-live-e2e",
        principal_id="owner:live-e2e",
        account_id=ACCOUNT_ID,
        draft=second,
        nonce="cd" * 16,
        now_ms=NOW_MS,
    )
    session.create_event(draft=second, grant=second_grant)
    assert len([c for c in http.calls if c[0] == "POST_FORM"]) == 1


def test_stdlib_client_pins_routes_before_network() -> None:
    client = StdlibGraphMutationHttpV1()
    with pytest.raises(GraphCalendarV1Denied, match="mutation route"):
        client.post_json(
            url="https://graph.microsoft.com/v1.0/me/messages",
            payload={},
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphCalendarV1Denied, match="mutation route"):
        client.post_json(
            url="https://evil.example/v1.0/me/events",
            payload={},
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphCalendarV1Denied, match="read route"):
        client.get_json(
            url="https://graph.microsoft.com/v1.0/me/messages",
            query=(),
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphCalendarV1Denied, match="identity POST"):
        client.post_form(
            url="https://evil.example/token",
            fields=(("a", "b"),),
            timeout_seconds=30,
        )


def test_module_has_no_broader_mutation_or_live_wiring() -> None:
    source = (
        ROOT / "core" / "phase8_microsoft_graph_calendar_v1.py"
    ).read_text(encoding="utf-8")
    assert "Mail.Send" not in source
    assert "Mail.ReadWrite" not in source
    assert "client_secret" not in source
    assert "def send" not in source
    assert "def delete" not in source
    assert "def patch" not in source
    assert "def cancel" not in source
    assert "main.py" not in source
    assert "dashboard" not in source
    assert "subprocess" not in source
    assert "attendee invitations are denied" in source
    assert '"Calendars.ReadWrite"' in source
