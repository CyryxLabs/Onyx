from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from unittest.mock import patch

import pytest

from core.control_plane import ControlPlaneStore
from core.dayops_live_integration_v1 import (
    FEATURE_FLAG,
    IANA_TIMEZONE_KEY,
    OUTLOOK_TIMEZONE_KEY,
    DayOpsAuthenticationRequiredV1,
    DayOpsFeatureGateV1,
    DayOpsLiveV1ContractError,
    create_dayops_live_integration_v1,
    sanitized_brief_sha256_v1,
    tool_declaration_v1,
)
from core.phase7_workspace_aliases_v1 import (
    CredentialAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_read_v1 import (
    GraphHttpResponseV1,
    GraphReadFeatureGateV1,
    MicrosoftGraphReadAdapterV1,
    create_microsoft_graph_read_adapter_v1,
)
from core.workspaces import WorkspaceRegistry


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1_000)
KEY = bytes(range(1, 33))


@dataclass
class Fixture:
    control: ControlPlaneStore
    registry: WorkspaceRegistry


class QueueTransport:
    def __init__(self, responses: Iterable[GraphHttpResponseV1]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def get(self, *, url: str, query, headers) -> GraphHttpResponseV1:
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("unexpected network call")
        return self.responses.pop(0)


@pytest.fixture
def fixture(tmp_path: Path) -> Iterable[Fixture]:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=tmp_path,
    ):
        control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    registry.register("cyryx-main", display_name="Cyryx", workspace_class="cyryx")
    try:
        yield Fixture(control, registry)
    finally:
        control.close()


def _environment() -> dict[str, str]:
    return {
        FEATURE_FLAG: "true",
        IANA_TIMEZONE_KEY: "America/New_York",
        OUTLOOK_TIMEZONE_KEY: "Eastern Standard Time",
    }


def _event() -> dict[str, object]:
    return {
        "id": "secret-event-id",
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
        "attendees": [{"emailAddress": {"address": "advisor@example.com"}}],
        "isAllDay": False,
        "isCancelled": False,
        "webLink": "https://outlook.office.com/calendar/private",
    }


def _message() -> dict[str, object]:
    return {
        "id": "secret-message-id",
        "subject": "Decision needed today",
        "from": {"emailAddress": {"address": "partner@example.com"}},
        "receivedDateTime": "2026-07-30T12:05:00Z",
        "importance": "high",
        "hasAttachments": True,
        "conversationId": "secret-conversation-id",
        "webLink": "https://outlook.office.com/mail/private",
    }


def _adapter_factory(fixture: Fixture, transport: QueueTransport):
    catalog = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=fixture.registry,
        workspace_id="cyryx-main",
        principal_id="owner:test",
        integrity_key=KEY,
    )
    assert catalog is not None
    catalog.register(
        "microsoft-primary",
        CredentialAliasSpecV1(
            provider="microsoft-graph",
            account_id="owner@cyryxlabs.com",
            tenant_id="cyryx-labs",
            scopes=("Calendars.Read", "Mail.Read"),
            rotate_after_ms=NOW_MS + 100_000,
            revoke_after_ms=NOW_MS + 200_000,
        ),
        now_ms=NOW_MS,
    )

    def factory(now_ms: int):
        assert now_ms == NOW_MS
        return create_microsoft_graph_read_adapter_v1(
            gate=GraphReadFeatureGateV1(True),
            aliases=catalog,
            credential_alias_name="microsoft-primary",
            transport=transport,
            now_ms=now_ms,
            project_root=ROOT,
        )

    return factory


def test_declaration_and_feature_gate_are_exact_and_default_off() -> None:
    declaration = tool_declaration_v1()
    assert declaration["name"] == "day_brief_read"
    assert declaration["parameters"]["required"] == []
    assert DayOpsFeatureGateV1.from_environ({}).enabled is False
    assert DayOpsFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "true "):
        assert not DayOpsFeatureGateV1.from_environ({FEATURE_FLAG: value}).enabled
    assert create_dayops_live_integration_v1(environ={}) is None
    with pytest.raises(DayOpsLiveV1ContractError, match="sealed feature gate"):
        create_dayops_live_integration_v1(gate=True)  # type: ignore[arg-type]


def test_missing_configuration_never_constructs_factory() -> None:
    calls: list[int] = []

    def factory(now_ms: int):
        calls.append(now_ms)
        raise AssertionError("factory must remain unopened")

    controller = create_dayops_live_integration_v1(
        gate=DayOpsFeatureGateV1(True),
        adapter_factory=factory,
    )
    assert controller is not None
    missing = controller.execute({}, environ={}, now=NOW)
    assert missing.status == "configuration_required"
    assert calls == []


def test_missing_token_factory_result_is_safe() -> None:
    calls: list[int] = []

    def factory(now_ms: int):
        calls.append(now_ms)
        raise DayOpsAuthenticationRequiredV1("secret-free auth state")

    controller = create_dayops_live_integration_v1(
        gate=DayOpsFeatureGateV1(True),
        adapter_factory=factory,
    )
    assert controller is not None
    result = controller.execute({}, environ=_environment(), now=NOW)
    assert result.status == "authentication_required"
    assert calls == [NOW_MS]


def test_fake_transport_brief_is_sanitized_and_read_only(fixture: Fixture) -> None:
    transport = QueueTransport(
        [
            GraphHttpResponseV1(200, {"value": [_event()]}, "calendar-request"),
            GraphHttpResponseV1(200, {"value": [_message()]}, "mail-request"),
        ]
    )
    controller = create_dayops_live_integration_v1(
        gate=DayOpsFeatureGateV1(True),
        adapter_factory=_adapter_factory(fixture, transport),
    )
    assert controller is not None
    result = controller.execute(
        {"date": "2026-07-30"},
        environ=_environment(),
        now=NOW,
    )
    assert result.status == "completed"
    assert result.result["read_only"] is True
    assert result.result["verification"] == "provider_response_normalized"
    assert result.result["provider_content_untrusted"] is True
    assert isinstance(result.result["source_brief_sha256"], str)
    assert len(result.result["source_brief_sha256"]) == 64
    assert len(transport.calls) == 2
    assert result.result["events"][0]["subject"] == "Founder review"
    assert result.result["unread_messages"][0]["importance"] == "high"
    event_ref = result.result["events"][0]["source_ref"]
    message_ref = result.result["unread_messages"][0]["source_ref"]
    assert isinstance(event_ref, str) and len(event_ref) == 64
    assert isinstance(message_ref, str) and len(message_ref) == 64
    assert event_ref != message_ref
    assert result.result["brief_sha256"] == sanitized_brief_sha256_v1(result.result)
    serialized = repr(result.result)
    for private_value in (
        "secret-event-id",
        "secret-message-id",
        "secret-conversation-id",
        "/calendar/private",
        "/mail/private",
        "owner@cyryxlabs.com",
        "advisor@example.com",
    ):
        assert private_value not in serialized


@pytest.mark.parametrize("tamper", ("digest", "payload"))
def test_tampered_phase8_brief_fails_closed_before_sanitization(
    fixture: Fixture, tamper: str
) -> None:
    transport = QueueTransport(
        [
            GraphHttpResponseV1(200, {"value": [_event()]}, "calendar-request"),
            GraphHttpResponseV1(200, {"value": [_message()]}, "mail-request"),
        ]
    )
    factory = _adapter_factory(fixture, transport)
    adapter = factory(NOW_MS)
    assert type(adapter) is MicrosoftGraphReadAdapterV1
    brief = adapter.daily_brief(
        window_start="2026-07-30T04:00:00+00:00",
        window_end="2026-07-31T04:00:00+00:00",
        outlook_timezone="Eastern Standard Time",
        now_ms=NOW_MS,
        generated_at=NOW.isoformat(),
    )
    if tamper == "digest":
        tampered = replace(brief, brief_sha256="0" * 64)
    else:
        tampered_event = replace(brief.events[0], subject="Altered after Phase 8")
        tampered = replace(brief, events=(tampered_event,))
    controller = create_dayops_live_integration_v1(
        gate=DayOpsFeatureGateV1(True),
        adapter_factory=lambda _now_ms: adapter,
    )
    assert controller is not None
    with patch.object(
        MicrosoftGraphReadAdapterV1,
        "daily_brief",
        return_value=tampered,
    ):
        result = controller.execute({}, environ=_environment(), now=NOW)
    assert result.status == "failed"
    assert result.error_type == "DayOpsPlannerV1ContractError"
    assert "brief_sha256" not in repr(result.result)


def test_invalid_date_denies_before_factory() -> None:
    calls: list[int] = []

    def factory(now_ms: int):
        calls.append(now_ms)
        raise AssertionError("factory must remain unopened")

    controller = create_dayops_live_integration_v1(
        gate=DayOpsFeatureGateV1(True),
        adapter_factory=factory,
    )
    assert controller is not None
    with pytest.raises(DayOpsLiveV1ContractError, match="date"):
        controller.execute(
            {"date": "30/07/2026"},
            environ=_environment(),
            now=NOW,
        )
    assert calls == []


def test_factory_or_adapter_failure_is_redacted() -> None:
    def factory(_now_ms: int):
        raise RuntimeError("Bearer secret-value")

    controller = create_dayops_live_integration_v1(
        gate=DayOpsFeatureGateV1(True),
        adapter_factory=factory,
    )
    assert controller is not None
    result = controller.execute({}, environ=_environment(), now=NOW)
    assert result.status == "failed"
    assert result.error_type == "RuntimeError"
    assert "secret-value" not in repr(result.result)
