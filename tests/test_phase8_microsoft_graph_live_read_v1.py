from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from unittest.mock import patch

import pytest

from core.control_plane import ControlPlaneStore
from core.phase7_workspace_aliases_v1 import (
    CredentialAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_live_read_v1 import (
    FEATURE_FLAG,
    GraphLiveReadAuthenticationRequiredV1,
    GraphLiveReadFeatureGateV1,
    GraphLiveReadPermissionDeniedV1,
    GraphLiveReadProviderUnavailableV1,
    GraphLiveReadRateLimitedV1,
    GraphLiveReadRetryPolicyV1,
    GraphLiveReadV1ContractError,
    GraphLiveReadV1Denied,
    create_microsoft_graph_live_read_transport_v1,
)
from core.phase8_microsoft_graph_oauth_v1 import (
    GraphOAuthFeatureGateV1,
    JsonHttpResponseV1,
    MicrosoftGraphOAuthSettingsV1,
    create_microsoft_graph_oauth_v1,
)
from core.phase8_microsoft_graph_read_v1 import (
    GRAPH_ORIGIN,
    GraphReadFeatureGateV1,
    create_microsoft_graph_read_adapter_v1,
)
from core.workspaces import WorkspaceRegistry

ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1_785_000_000_000
NOW_S = 1_785_000_000
KEY = bytes(range(1, 33))
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
SCOPES = ("User.Read", "Calendars.Read", "Mail.Read", "offline_access")


@dataclass
class Fixture:
    control: ControlPlaneStore
    registry: WorkspaceRegistry


@dataclass(frozen=True)
class Queued:
    method: str
    response: JsonHttpResponseV1


@dataclass(frozen=True)
class HttpCall:
    method: str
    url: str
    values: tuple[tuple[str, str], ...]
    headers: tuple[tuple[str, str], ...]


class FakeHttp:
    def __init__(self, responses: Iterable[Queued] = ()) -> None:
        self.responses = list(responses)
        self.calls: list[HttpCall] = []

    def _next(self, method: str) -> JsonHttpResponseV1:
        if not self.responses:
            raise AssertionError(f"unexpected {method} request")
        item = self.responses.pop(0)
        if item.method != method:
            raise AssertionError(f"expected {item.method}, got {method}")
        return item.response

    def post_form(
        self,
        *,
        url: str,
        fields: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1:
        assert timeout_seconds == 30
        self.calls.append(HttpCall("POST", url, fields, ()))
        return self._next("POST")

    def get_json(
        self,
        *,
        url: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1:
        assert timeout_seconds == 30
        self.calls.append(HttpCall("GET", url, query, headers))
        return self._next("GET")


class FakeVault:
    def __init__(self, value: str | None = "refresh-token-0") -> None:
        self.value = value
        self.writes: list[str] = []

    def get_refresh_token(self) -> str | None:
        return self.value

    def set_refresh_token(self, value: str) -> None:
        self.value = value
        self.writes.append(value)

    def delete_refresh_token(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


@pytest.fixture
def fixture(tmp_path: Path) -> Iterable[Fixture]:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=tmp_path,
    ):
        control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    registry.register(
        "cyryx-main",
        display_name="Cyryx Main",
        workspace_class="cyryx",
    )
    value = Fixture(control, registry)
    try:
        yield value
    finally:
        control.close()


def _catalog(fixture: Fixture):
    catalog = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=fixture.registry,
        workspace_id="cyryx-main",
        principal_id="owner:pedro",
        integrity_key=KEY,
    )
    assert catalog is not None
    catalog.register(
        "microsoft-primary",
        CredentialAliasSpecV1(
            provider="microsoft-graph",
            account_id="owner@cyryxlabs.com",
            tenant_id=TENANT_ID,
            scopes=("Calendars.Read", "Mail.Read"),
            rotate_after_ms=NOW_MS + 100_000,
            revoke_after_ms=NOW_MS + 200_000,
        ),
        now_ms=NOW_MS,
    )
    return catalog


def _token(
    *,
    access: str = "access-token-1",
    refresh: str = "refresh-token-1",
) -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {
            "token_type": "Bearer",
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": 3600,
            "scope": "User.Read Calendars.Read Mail.Read",
        },
    )


def _me() -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {
            "id": "owner-object-id",
            "mail": "owner@cyryxlabs.com",
            "userPrincipalName": "owner@cyryxlabs.com",
        },
    )


def _event() -> dict[str, object]:
    return {
        "id": "event-1",
        "subject": "Founder review",
        "start": {
            "dateTime": "2026-07-23T09:00:00",
            "timeZone": "Eastern Standard Time",
        },
        "end": {
            "dateTime": "2026-07-23T09:30:00",
            "timeZone": "Eastern Standard Time",
        },
        "location": {"displayName": "Cyryx HQ"},
        "organizer": {"emailAddress": {"address": "owner@cyryxlabs.com"}},
        "attendees": [],
        "isAllDay": False,
        "isCancelled": False,
        "webLink": "https://outlook.office.com/calendar/item",
    }


def _message() -> dict[str, object]:
    return {
        "id": "message-1",
        "subject": "Decision needed",
        "from": {"emailAddress": {"address": "partner@example.com"}},
        "receivedDateTime": "2026-07-23T12:05:00Z",
        "importance": "high",
        "hasAttachments": False,
        "conversationId": "conversation-1",
        "webLink": "https://outlook.office.com/mail/item",
    }


def _session(fixture: Fixture, http: FakeHttp):
    catalog = _catalog(fixture)
    session = create_microsoft_graph_oauth_v1(
        gate=GraphOAuthFeatureGateV1(True),
        aliases=catalog,
        credential_alias_name="microsoft-primary",
        settings=MicrosoftGraphOAuthSettingsV1(CLIENT_ID, TENANT_ID, SCOPES),
        http=http,
        vault=FakeVault(),
        now_ms=NOW_MS,
        project_root=ROOT,
    )
    assert session is not None
    return catalog, session


def _restored_session(
    fixture: Fixture,
    remaining: Iterable[Queued],
):
    http = FakeHttp(
        [
            Queued("POST", _token()),
            Queued("GET", _me()),
            *remaining,
        ]
    )
    catalog, session = _session(fixture, http)
    status = session.restore(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    assert status.connected
    return catalog, session, http


def _transport(session, http: FakeHttp, sleeps: list[int] | None = None, **changes):
    policy = GraphLiveReadRetryPolicyV1(**changes)
    recorded = [] if sleeps is None else sleeps
    transport = create_microsoft_graph_live_read_transport_v1(
        gate=GraphLiveReadFeatureGateV1(True),
        session=session,
        http=http,
        clock_epoch_s=lambda: NOW_S + 1,
        clock_ms=lambda: NOW_MS + 2,
        sleeper=recorded.append,
        policy=policy,
        project_root=ROOT,
    )
    assert transport is not None
    return transport


def test_gate_is_exact_and_default_off_is_side_effect_free() -> None:
    assert not GraphLiveReadFeatureGateV1.from_environ({}).enabled
    assert GraphLiveReadFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", "True", " true", "true ", "yes"):
        assert not GraphLiveReadFeatureGateV1.from_environ(
            {FEATURE_FLAG: value}
        ).enabled
    assert (
        create_microsoft_graph_live_read_transport_v1(
            gate=GraphLiveReadFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


def test_retry_policy_and_factory_are_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GraphLiveReadV1ContractError, match="retry policy"):
        GraphLiveReadRetryPolicyV1(max_attempts=0)
    with pytest.raises(GraphLiveReadV1ContractError, match="sealed feature"):
        create_microsoft_graph_live_read_transport_v1(
            gate=True,  # type: ignore[arg-type]
        )
    with pytest.raises(GraphLiveReadV1ContractError, match="OAuth session"):
        create_microsoft_graph_live_read_transport_v1(
            gate=GraphLiveReadFeatureGateV1(True),
            project_root=ROOT,
        )
    monkeypatch.setattr(
        "core.phase8_microsoft_graph_live_read_v1.ACCEPTED_OAUTH_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(GraphLiveReadV1Denied, match="evidence unavailable"):
        create_microsoft_graph_live_read_transport_v1(
            gate=GraphLiveReadFeatureGateV1(True),
            project_root=ROOT,
        )


def test_live_transport_composes_with_read_adapter_and_records_no_payload(
    fixture: Fixture,
) -> None:
    catalog, session, http = _restored_session(
        fixture,
        [
            Queued(
                "GET",
                JsonHttpResponseV1(
                    200,
                    {"value": [_event()]},
                    (("request-id", "calendar-request-1"),),
                ),
            ),
            Queued(
                "GET",
                JsonHttpResponseV1(
                    200,
                    {"value": [_message()]},
                    (("request-id", "mail-request-1"),),
                ),
            ),
        ],
    )
    transport = _transport(session, http)
    adapter = create_microsoft_graph_read_adapter_v1(
        gate=GraphReadFeatureGateV1(True),
        aliases=catalog,
        credential_alias_name="microsoft-primary",
        transport=transport,
        now_ms=NOW_MS + 2,
        project_root=ROOT,
    )
    assert adapter is not None

    brief = adapter.daily_brief(
        window_start="2026-07-23T00:00:00-04:00",
        window_end="2026-07-24T00:00:00-04:00",
        outlook_timezone="Eastern Standard Time",
        now_ms=NOW_MS + 3,
        generated_at="2026-07-23T12:10:00-04:00",
    )

    assert brief.events[0].event_id == "event-1"
    assert brief.unread_messages[0].message_id == "message-1"
    assert transport.last_outcome is not None
    assert transport.last_outcome.result == "success"
    assert transport.last_outcome.request_id == "mail-request-1"
    assert "Decision needed" not in repr(transport.last_outcome)
    assert http.responses == []


def test_429_honors_retry_after_then_succeeds(fixture: Fixture) -> None:
    _catalog_value, session, http = _restored_session(
        fixture,
        [
            Queued(
                "GET",
                JsonHttpResponseV1(
                    429,
                    {"error": {"code": "TooManyRequests"}},
                    (("Retry-After", "2"), ("request-id", "throttle-1")),
                ),
            ),
            Queued(
                "GET",
                JsonHttpResponseV1(
                    200,
                    {"value": []},
                    (("request-id", "success-1"),),
                ),
            ),
        ],
    )
    sleeps: list[int] = []
    transport = _transport(session, http, sleeps)

    response = transport.get(
        url=f"{GRAPH_ORIGIN}/v1.0/me/messages",
        query=(("$top", "5"),),
        headers=(),
    )

    assert response.status_code == 200
    assert sleeps == [2]
    assert transport.last_outcome is not None
    assert transport.last_outcome.attempts == 2
    assert transport.last_outcome.retry_delay_seconds == 2


def test_429_without_header_uses_bounded_exponential_backoff(
    fixture: Fixture,
) -> None:
    _catalog_value, session, http = _restored_session(
        fixture,
        [
            Queued("GET", JsonHttpResponseV1(429, {"error": {}})),
            Queued("GET", JsonHttpResponseV1(429, {"error": {}})),
            Queued("GET", JsonHttpResponseV1(429, {"error": {}})),
        ],
    )
    sleeps: list[int] = []
    transport = _transport(session, http, sleeps)

    with pytest.raises(GraphLiveReadRateLimitedV1, match="budget"):
        transport.get(
            url=f"{GRAPH_ORIGIN}/v1.0/me/messages",
            query=(),
            headers=(),
        )

    assert sleeps == [1, 2]
    assert transport.last_outcome is not None
    assert transport.last_outcome.result == "rate_limited"
    assert transport.last_outcome.attempts == 3


def test_retry_after_over_budget_never_sleeps_or_retries(
    fixture: Fixture,
) -> None:
    _catalog_value, session, http = _restored_session(
        fixture,
        [
            Queued(
                "GET",
                JsonHttpResponseV1(
                    429,
                    {"error": {}},
                    (("Retry-After", "300"),),
                ),
            ),
        ],
    )
    sleeps: list[int] = []
    transport = _transport(session, http, sleeps, max_delay_seconds=60)

    with pytest.raises(GraphLiveReadRateLimitedV1):
        transport.get(
            url=f"{GRAPH_ORIGIN}/v1.0/me/messages",
            query=(),
            headers=(),
        )
    assert sleeps == []
    assert http.responses == []


def test_503_retries_then_reports_provider_unavailable(
    fixture: Fixture,
) -> None:
    _catalog_value, session, http = _restored_session(
        fixture,
        [
            Queued("GET", JsonHttpResponseV1(503, {"error": {}})),
            Queued("GET", JsonHttpResponseV1(503, {"error": {}})),
        ],
    )
    sleeps: list[int] = []
    transport = _transport(session, http, sleeps, max_attempts=2)

    with pytest.raises(GraphLiveReadProviderUnavailableV1, match="budget"):
        transport.get(
            url=f"{GRAPH_ORIGIN}/v1.0/me/calendarView",
            query=(),
            headers=(),
        )
    assert sleeps == [1]
    assert transport.last_outcome is not None
    assert transport.last_outcome.result == "provider_unavailable"


def test_401_forces_one_refresh_and_retries_with_rotated_access(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            Queued("POST", _token(access="access-token-1")),
            Queued("GET", _me()),
            Queued(
                "GET",
                JsonHttpResponseV1(
                    401,
                    {"error": {"code": "InvalidAuthenticationToken"}},
                    (("request-id", "auth-1"),),
                ),
            ),
            Queued(
                "POST",
                _token(access="access-token-2", refresh="refresh-token-2"),
            ),
            Queued("GET", _me()),
            Queued("GET", JsonHttpResponseV1(200, {"value": []})),
        ]
    )
    _catalog_value, session = _session(fixture, http)
    session.restore(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    transport = _transport(session, http)

    response = transport.get(
        url=f"{GRAPH_ORIGIN}/v1.0/me/messages",
        query=(),
        headers=(),
    )

    assert response.status_code == 200
    assert transport.last_outcome is not None
    assert transport.last_outcome.refreshed_after_401
    assert transport.last_outcome.attempts == 2
    graph_calls = [
        call
        for call in http.calls
        if call.method == "GET" and call.url.endswith("/v1.0/me/messages")
    ]
    assert graph_calls[0].headers[0][1] == "Bearer access-token-1"
    assert graph_calls[1].headers[0][1] == "Bearer access-token-2"


def test_failed_refresh_after_401_requires_new_authorization(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            Queued("POST", _token()),
            Queued("GET", _me()),
            Queued("GET", JsonHttpResponseV1(401, {"error": {}})),
            Queued(
                "POST",
                JsonHttpResponseV1(
                    400,
                    {"error": "invalid_grant"},
                ),
            ),
        ]
    )
    _catalog_value, session = _session(fixture, http)
    session.restore(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    transport = _transport(session, http)

    with pytest.raises(
        GraphLiveReadAuthenticationRequiredV1,
        match="renewed",
    ):
        transport.get(
            url=f"{GRAPH_ORIGIN}/v1.0/me/messages",
            query=(),
            headers=(),
        )

    assert transport.last_outcome is not None
    assert transport.last_outcome.result == "authentication_required"
    assert transport.last_outcome.status_code == 401


def test_403_is_terminal_and_never_retried(fixture: Fixture) -> None:
    _catalog_value, session, http = _restored_session(
        fixture,
        [
            Queued(
                "GET",
                JsonHttpResponseV1(
                    403,
                    {"error": {"code": "Authorization_RequestDenied"}},
                ),
            ),
        ],
    )
    sleeps: list[int] = []
    transport = _transport(session, http, sleeps)

    with pytest.raises(GraphLiveReadPermissionDeniedV1, match="permission"):
        transport.get(
            url=f"{GRAPH_ORIGIN}/v1.0/me/messages",
            query=(),
            headers=(),
        )
    assert sleeps == []
    assert transport.last_outcome is not None
    assert transport.last_outcome.result == "permission_denied"


@pytest.mark.parametrize(
    ("url", "headers"),
    [
        ("https://evil.example/v1.0/me/messages", ()),
        ("http://graph.microsoft.com/v1.0/me/messages", ()),
        ("https://graph.microsoft.com/beta/me/messages", ()),
        ("https://graph.microsoft.com/v1.0/users", ()),
        (
            "https://graph.microsoft.com/v1.0/me/messages",
            (("Authorization", "Bearer attacker"),),
        ),
        (
            "https://graph.microsoft.com/v1.0/me/messages",
            (("X-Unsafe", "value"),),
        ),
    ],
)
def test_route_and_caller_headers_fail_closed_before_http(
    fixture: Fixture,
    url: str,
    headers: tuple[tuple[str, str], ...],
) -> None:
    _catalog_value, session, http = _restored_session(fixture, [])
    transport = _transport(session, http)

    with pytest.raises(GraphLiveReadV1Denied, match="route"):
        transport.get(url=url, query=(), headers=headers)
    assert http.responses == []
