from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from unittest.mock import patch

import pytest

from core.control_plane import ControlPlaneStore
from core.dayops_graph_factory_v1 import (
    CREDENTIAL_ALIAS_KEY,
    PRINCIPAL_ID_KEY,
    WORKSPACE_ID_KEY,
    CanonicalDayOpsGraphFactoryV1,
)
from core.dayops_live_integration_v1 import (
    FEATURE_FLAG,
    IANA_TIMEZONE_KEY,
    OUTLOOK_TIMEZONE_KEY,
    DayOpsFeatureGateV1,
    create_dayops_live_integration_v1,
)
from core.phase7_workspace_aliases_v1 import (
    CredentialAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    ENV_ACCOUNT_ID,
    ENV_CLIENT_ID,
    ENV_TENANT_ID,
)
from core.phase8_microsoft_graph_oauth_v1 import JsonHttpResponseV1
from core.workspaces import WorkspaceRegistry


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1_000)
NOW_S = int(NOW.timestamp())
KEY = bytes(range(1, 33))
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


@dataclass
class Fixture:
    control: ControlPlaneStore


class FakeVault:
    def __init__(self, value: str | None) -> None:
        self.value = value
        self.reads = 0
        self.writes: list[str] = []

    def get_refresh_token(self) -> str | None:
        self.reads += 1
        return self.value

    def set_refresh_token(self, value: str) -> None:
        self.value = value
        self.writes.append(value)

    def delete_refresh_token(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


class FakeHttp:
    def __init__(self, responses: Iterable[tuple[str, JsonHttpResponseV1]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def _next(self, method: str) -> JsonHttpResponseV1:
        if not self.responses:
            raise AssertionError(f"unexpected {method} call")
        expected, response = self.responses.pop(0)
        assert expected == method
        return response

    def post_form(self, *, url: str, fields, timeout_seconds: int):
        assert timeout_seconds == 30
        self.calls.append(("POST", url))
        return self._next("POST")

    def get_json(self, *, url: str, query, headers, timeout_seconds: int):
        assert timeout_seconds == 30
        self.calls.append(("GET", url))
        return self._next("GET")


@pytest.fixture
def fixture(tmp_path: Path) -> Iterable[Fixture]:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=tmp_path,
    ):
        control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    registry.register("cyryx-main", display_name="Cyryx", workspace_class="cyryx")
    catalog = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=registry,
        workspace_id="cyryx-main",
        principal_id="owner:test",
        integrity_key=KEY,
        project_root=ROOT,
    )
    assert catalog is not None
    catalog.register(
        "microsoft-primary",
        CredentialAliasSpecV1(
            provider="microsoft-graph",
            account_id="owner@cyryxlabs.com",
            tenant_id=TENANT_ID,
            scopes=("User.Read", "Calendars.Read", "Mail.Read", "offline_access"),
            rotate_after_ms=NOW_MS + 100_000,
            revoke_after_ms=NOW_MS + 200_000,
        ),
        now_ms=NOW_MS,
    )
    try:
        yield Fixture(control)
    finally:
        control.close()


def _environment() -> dict[str, str]:
    return {
        FEATURE_FLAG: "true",
        IANA_TIMEZONE_KEY: "America/New_York",
        OUTLOOK_TIMEZONE_KEY: "Eastern Standard Time",
        WORKSPACE_ID_KEY: "cyryx-main",
        PRINCIPAL_ID_KEY: "owner:test",
        CREDENTIAL_ALIAS_KEY: "microsoft-primary",
        ENV_CLIENT_ID: CLIENT_ID,
        ENV_TENANT_ID: TENANT_ID,
        ENV_ACCOUNT_ID: "owner@cyryxlabs.com",
    }


def _token() -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {
            "token_type": "Bearer",
            "access_token": "access-token",
            "expires_in": 3600,
            "scope": "User.Read Calendars.Read Mail.Read",
            "refresh_token": "rotated-refresh-token",
        },
    )


def _profile() -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {
            "id": "owner-id",
            "mail": "owner@cyryxlabs.com",
            "userPrincipalName": "owner@cyryxlabs.com",
        },
    )


def _event() -> dict[str, object]:
    return {
        "id": "event-id",
        "subject": "Founder review",
        "start": {
            "dateTime": "2026-07-30T09:00:00",
            "timeZone": "Eastern Standard Time",
        },
        "end": {
            "dateTime": "2026-07-30T09:30:00",
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
        "id": "message-id",
        "subject": "Decision needed",
        "from": {"emailAddress": {"address": "partner@example.com"}},
        "receivedDateTime": "2026-07-30T12:05:00Z",
        "importance": "high",
        "hasAttachments": False,
        "conversationId": "conversation-id",
        "webLink": "https://outlook.office.com/mail/item",
    }


def test_canonical_factory_missing_refresh_token_makes_zero_http_calls(
    fixture: Fixture,
) -> None:
    http = FakeHttp([])
    vault = FakeVault(None)
    factory = CanonicalDayOpsGraphFactoryV1(
        environ=_environment(),
        store_factory=lambda: fixture.control,
        integrity_key_provider=lambda _binding: KEY,
        http=http,
        vault=vault,
        clock_ms=lambda: NOW_MS,
        clock_epoch_s=lambda: NOW_S,
        sleeper=lambda _seconds: None,
        project_root=ROOT,
    )
    controller = create_dayops_live_integration_v1(
        gate=DayOpsFeatureGateV1(True),
        adapter_factory=factory,
    )
    assert controller is not None
    result = controller.execute({}, environ=_environment(), now=NOW)
    assert result.status == "authentication_required"
    assert vault.reads == 1
    assert http.calls == []


def test_canonical_factory_composes_oauth_live_transport_and_graph_adapter(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            ("POST", _token()),
            ("GET", _profile()),
            ("GET", JsonHttpResponseV1(200, {"value": [_event()]})),
            ("GET", JsonHttpResponseV1(200, {"value": [_message()]})),
        ]
    )
    vault = FakeVault("refresh-token")
    factory = CanonicalDayOpsGraphFactoryV1(
        environ=_environment(),
        store_factory=lambda: fixture.control,
        integrity_key_provider=lambda _binding: KEY,
        http=http,
        vault=vault,
        clock_ms=lambda: NOW_MS,
        clock_epoch_s=lambda: NOW_S,
        sleeper=lambda _seconds: None,
        project_root=ROOT,
    )
    controller = create_dayops_live_integration_v1(
        gate=DayOpsFeatureGateV1(True),
        adapter_factory=factory,
    )
    assert controller is not None
    result = controller.execute(
        {"date": "2026-07-30"},
        environ=_environment(),
        now=NOW,
    )
    assert result.status == "completed"
    assert result.result["read_only"] is True
    assert result.result["events"][0]["subject"] == "Founder review"
    assert result.result["unread_messages"][0]["subject"] == "Decision needed"
    assert [method for method, _url in http.calls] == ["POST", "GET", "GET", "GET"]
    assert vault.writes == ["rotated-refresh-token"]
