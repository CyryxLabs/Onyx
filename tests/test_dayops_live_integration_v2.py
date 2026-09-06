from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core.dayops_live_integration_v1 import (
    DayOpsExecutionV1,
    DayOpsLiveIntegrationV1,
    sanitized_brief_sha256_v1,
)
from core.dayops_live_integration_v2 import (
    FEATURE_FLAG,
    DayOpsPlannerFeatureGateV2,
    create_dayops_live_integration_v2,
)

NOW = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)
ENV = {
    "ONYX_DAYOPS_IANA_TIMEZONE": "America/New_York",
    "ONYX_DAYOPS_OUTLOOK_TIMEZONE": "Eastern Standard Time",
}


def _completed() -> DayOpsExecutionV1:
    payload: dict[str, object] = {
        "status": "completed",
        "read_only": True,
        "verification": "provider_response_normalized",
        "window_start": "2026-07-30T04:00:00Z",
        "window_end": "2026-07-31T04:00:00Z",
        "generated_at": "2026-07-30T14:59:00Z",
        "calendar_has_more": False,
        "mail_has_more": True,
        "events": [
            {
                "subject": "Graph calendar item",
                "start": "2026-07-30T12:00:00-04:00",
                "end": "2026-07-30T13:00:00-04:00",
                "timezone": "Eastern Standard Time",
                "location": "",
                "is_all_day": False,
                "is_cancelled": False,
            }
        ],
        "unread_messages": [
            {
                "subject": "Graph unread",
                "sender": "partner@example.com",
                "received_at": "2026-07-30T14:00:00Z",
                "importance": "high",
                "has_attachments": False,
            }
        ],
        "provider_content_untrusted": True,
        "source_brief_sha256": "b" * 64,
        "brief_sha256": "",
    }
    payload["brief_sha256"] = sanitized_brief_sha256_v1(payload)
    return DayOpsExecutionV1("completed", payload)


def _base() -> DayOpsLiveIntegrationV1:
    return object.__new__(DayOpsLiveIntegrationV1)


def test_feature_is_exact_and_default_off() -> None:
    assert DayOpsPlannerFeatureGateV2.from_environ({}).enabled is False
    assert DayOpsPlannerFeatureGateV2.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "true "):
        assert not DayOpsPlannerFeatureGateV2.from_environ(
            {FEATURE_FLAG: value}
        ).enabled


def test_default_off_preserves_exact_v1_result() -> None:
    original = _completed()
    integration = create_dayops_live_integration_v2(base=_base(), environ={})
    with patch.object(DayOpsLiveIntegrationV1, "execute", return_value=original):
        result = integration.execute({}, environ=ENV, now=NOW)
    assert result is original
    assert "planner" not in result.result


def test_enabled_planner_wraps_fake_graph_projection_read_only() -> None:
    original = _completed()
    integration = create_dayops_live_integration_v2(
        base=_base(),
        gate=DayOpsPlannerFeatureGateV2(True),
    )
    with patch.object(DayOpsLiveIntegrationV1, "execute", return_value=original):
        result = integration.execute({}, environ=ENV, now=NOW)
    assert result.status == "completed"
    assert result.result["planner_candidate"] is True
    planner = result.result["planner"]
    assert planner["read_only"] is True
    assert planner["mutation_authority"] is False
    assert planner["important_unread"][0]["subject"] == "Graph unread"
    assert planner["coverage"]["mail_has_more"] is True
    assert "planner" not in original.result


def test_noncompleted_v1_status_is_preserved_without_planning() -> None:
    original = DayOpsExecutionV1("authentication_required", {"read_only": True})
    integration = create_dayops_live_integration_v2(
        base=_base(), gate=DayOpsPlannerFeatureGateV2(True)
    )
    with patch.object(DayOpsLiveIntegrationV1, "execute", return_value=original):
        result = integration.execute({}, environ=ENV, now=NOW)
    assert result is original


def test_invalid_completed_projection_fails_safely_and_redacts_fields() -> None:
    original = DayOpsExecutionV1(
        "completed",
        {
            "read_only": True,
            "provider_content_untrusted": True,
            "window_start": "Bearer secret",
            "window_end": "bad",
            "generated_at": "bad",
        },
    )
    integration = create_dayops_live_integration_v2(
        base=_base(), gate=DayOpsPlannerFeatureGateV2(True)
    )
    with patch.object(DayOpsLiveIntegrationV1, "execute", return_value=original):
        result = integration.execute({}, environ=ENV, now=NOW)
    assert result.status == "failed"
    assert result.error_type == "DayOpsPlannerV1ContractError"
    assert "secret" not in repr(result.result).casefold()


def test_any_planner_exception_is_redacted_but_baseexception_is_not_caught() -> None:
    original = _completed()
    integration = create_dayops_live_integration_v2(
        base=_base(), gate=DayOpsPlannerFeatureGateV2(True)
    )
    with (
        patch.object(DayOpsLiveIntegrationV1, "execute", return_value=original),
        patch(
            "core.dayops_live_integration_v2.plan_dayops_v1",
            side_effect=RuntimeError("field secret"),
        ),
    ):
        result = integration.execute({}, environ=ENV, now=NOW)
    assert result.status == "failed"
    assert result.error_type == "RuntimeError"
    assert "field secret" not in repr(result.result)
    with (
        patch.object(DayOpsLiveIntegrationV1, "execute", return_value=original),
        patch(
            "core.dayops_live_integration_v2.plan_dayops_v1",
            side_effect=KeyboardInterrupt,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        integration.execute({}, environ=ENV, now=NOW)
