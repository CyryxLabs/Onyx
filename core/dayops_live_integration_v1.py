"""Default-off, read-only DayOps projection over Microsoft Graph Read V1.

The integration deliberately does not own OAuth, credentials, HTTP, or policy.
Its injected adapter factory is invoked only by the host after authorization.
Missing configuration or an unavailable token marker returns a typed safe
status without constructing the adapter and therefore without restoring OAuth
or performing network I/O.
"""

from __future__ import annotations

import os
import re
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.phase8_microsoft_graph_read_v1 import (
    ExecutiveOfficeBriefV1,
    MicrosoftGraphReadAdapterV1,
)


FEATURE_FLAG: Final = "ONYX_DAYOPS_LIVE_INTEGRATION_V1"
IANA_TIMEZONE_KEY: Final = "ONYX_DAYOPS_IANA_TIMEZONE"
OUTLOOK_TIMEZONE_KEY: Final = "ONYX_DAYOPS_OUTLOOK_TIMEZONE"
ENABLED_VALUE: Final = "true"
TOOL_NAME: Final = "day_brief_read"
SCHEMA: Final = "OnyxDayOpsLiveIntegration.v1"
MAX_EVENTS: Final = 50
MAX_MESSAGES: Final = 50
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ZONE = re.compile(r"^[A-Za-z0-9 _./+-]{1,80}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SANITIZED_KEYS: Final = frozenset(
    {
        "status",
        "read_only",
        "verification",
        "window_start",
        "window_end",
        "generated_at",
        "calendar_has_more",
        "mail_has_more",
        "events",
        "unread_messages",
        "source_brief_sha256",
        "brief_sha256",
        "provider_content_untrusted",
    }
)
_EVENT_KEYS: Final = frozenset(
    {
        "subject",
        "start",
        "end",
        "timezone",
        "location",
        "is_all_day",
        "is_cancelled",
    }
)
_MESSAGE_KEYS: Final = frozenset(
    {
        "subject",
        "sender",
        "received_at",
        "importance",
        "has_attachments",
    }
)

AdapterFactoryV1 = Callable[[int], MicrosoftGraphReadAdapterV1 | None]


class DayOpsLiveV1Error(RuntimeError):
    pass


class DayOpsLiveV1ContractError(ValueError):
    pass


class DayOpsConfigurationRequiredV1(DayOpsLiveV1Error):
    pass


class DayOpsAuthenticationRequiredV1(DayOpsLiveV1Error):
    pass


@dataclass(frozen=True, slots=True)
class DayOpsFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise DayOpsLiveV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "DayOpsFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class DayOpsConfigurationV1:
    iana_timezone: str
    outlook_timezone: str

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "DayOpsConfigurationV1 | None":
        source = os.environ if environ is None else environ
        iana = source.get(IANA_TIMEZONE_KEY, "")
        outlook = source.get(OUTLOOK_TIMEZONE_KEY, "")
        if (
            type(iana) is not str
            or type(outlook) is not str
            or not _ZONE.fullmatch(iana)
            or not _ZONE.fullmatch(outlook)
        ):
            return None
        try:
            ZoneInfo(iana)
        except (ZoneInfoNotFoundError, ValueError):
            return None
        return cls(iana_timezone=iana, outlook_timezone=outlook)


@dataclass(frozen=True, slots=True)
class DayOpsExecutionV1:
    status: str
    result: dict[str, object]
    error_type: str = ""

    def __post_init__(self) -> None:
        if (
            self.status
            not in {
                "completed",
                "disabled",
                "configuration_required",
                "authentication_required",
                "unavailable",
                "failed",
            }
            or type(self.result) is not dict
            or type(self.error_type) is not str
        ):
            raise DayOpsLiveV1ContractError("execution result is invalid")


def tool_declaration_v1() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": (
            "Reads today's authorized Microsoft calendar and unread-mail "
            "metadata and returns a concise read-only brief. It never sends "
            "mail or changes calendar data."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date": {
                    "type": "STRING",
                    "description": "Optional local date in YYYY-MM-DD format.",
                }
            },
            "required": [],
        },
    }


def _safe_status(status: str, message: str) -> DayOpsExecutionV1:
    return DayOpsExecutionV1(
        status,
        {
            "status": status,
            "read_only": True,
            "result": message,
        },
    )


def _requested_date(
    arguments: Mapping[str, object], now: datetime, zone: ZoneInfo
) -> date:
    raw = arguments.get("date")
    if raw in (None, ""):
        return now.astimezone(zone).date()
    if type(raw) is not str or not _DATE.fullmatch(raw):
        raise DayOpsLiveV1ContractError("date must use YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise DayOpsLiveV1ContractError("date is invalid") from exc


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _source_ref(kind: str, provider_id: str) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "domain": "onyx.dayops.provider-source-ref.v1",
                "kind": kind,
                "provider_id": provider_id,
            }
        )
    ).hexdigest()


def sanitized_brief_sha256_v1(source: Mapping[str, object]) -> str:
    """Hash the exact public V1 projection, excluding only its digest field."""

    if type(source) is not dict or frozenset(source) != _SANITIZED_KEYS:
        raise DayOpsLiveV1ContractError("sanitized brief shape drift")
    if (
        source.get("status") != "completed"
        or source.get("read_only") is not True
        or source.get("verification") != "provider_response_normalized"
        or source.get("provider_content_untrusted") is not True
        or type(source.get("calendar_has_more")) is not bool
        or type(source.get("mail_has_more")) is not bool
    ):
        raise DayOpsLiveV1ContractError("sanitized brief markers drift")
    for name in ("window_start", "window_end", "generated_at"):
        if type(source.get(name)) is not str:
            raise DayOpsLiveV1ContractError("sanitized brief timestamp drift")
    source_digest = source.get("source_brief_sha256")
    if type(source_digest) is not str or not _HEX64.fullmatch(source_digest):
        raise DayOpsLiveV1ContractError("source brief digest drift")
    events = source.get("events")
    messages = source.get("unread_messages")
    if type(events) is not list or type(messages) is not list:
        raise DayOpsLiveV1ContractError("sanitized brief collections drift")
    for item in events:
        if type(item) is not dict or frozenset(item) not in {
            _EVENT_KEYS,
            _EVENT_KEYS | {"source_ref"},
        }:
            raise DayOpsLiveV1ContractError("sanitized event shape drift")
        if "source_ref" in item and (
            type(item["source_ref"]) is not str
            or not _HEX64.fullmatch(item["source_ref"])
        ):
            raise DayOpsLiveV1ContractError("sanitized event source ref drift")
    for item in messages:
        if type(item) is not dict or frozenset(item) not in {
            _MESSAGE_KEYS,
            _MESSAGE_KEYS | {"source_ref"},
        }:
            raise DayOpsLiveV1ContractError("sanitized message shape drift")
        if "source_ref" in item and (
            type(item["source_ref"]) is not str
            or not _HEX64.fullmatch(item["source_ref"])
        ):
            raise DayOpsLiveV1ContractError("sanitized message source ref drift")
    payload = {key: value for key, value in source.items() if key != "brief_sha256"}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _sanitized(brief: ExecutiveOfficeBriefV1) -> dict[str, object]:
    # Reuse the accepted ExecutiveOfficeBrief provenance verifier already used
    # by the planner.  The lazy import avoids changing the Phase 8 model/factory
    # surface and prevents this lower-level integration from owning a duplicate
    # canonical-payload algorithm.
    from core.dayops_planner_v1 import _snapshot

    _snapshot(brief)
    events: list[dict[str, object]] = []
    for item in brief.events[:MAX_EVENTS]:
        event: dict[str, object] = {
            "subject": item.subject,
            "start": item.start,
            "end": item.end,
            "timezone": item.timezone,
            "location": item.location,
            "is_all_day": item.is_all_day,
            "is_cancelled": item.is_cancelled,
        }
        if item.event_id:
            event["source_ref"] = _source_ref("calendar-event", item.event_id)
        events.append(event)
    messages: list[dict[str, object]] = []
    for item in brief.unread_messages[:MAX_MESSAGES]:
        message: dict[str, object] = {
            "subject": item.subject,
            "sender": item.sender,
            "received_at": item.received_at,
            "importance": item.importance,
            "has_attachments": item.has_attachments,
        }
        if item.message_id:
            message["source_ref"] = _source_ref("unread-message", item.message_id)
        messages.append(message)
    result: dict[str, object] = {
        "status": "completed",
        "read_only": True,
        "verification": "provider_response_normalized",
        "window_start": brief.window_start,
        "window_end": brief.window_end,
        "generated_at": brief.generated_at,
        "calendar_has_more": brief.calendar_has_more,
        "mail_has_more": brief.mail_has_more,
        "events": events,
        "unread_messages": messages,
        "source_brief_sha256": brief.brief_sha256,
        "brief_sha256": "",
        "provider_content_untrusted": brief.provider_content_untrusted,
    }
    result["brief_sha256"] = sanitized_brief_sha256_v1(result)
    return result


class DayOpsLiveIntegrationV1:
    """Pure host-bound controller; authorization remains outside this class."""

    __slots__ = ("_factory", "_gate")

    def __init__(
        self,
        *,
        gate: DayOpsFeatureGateV1,
        adapter_factory: AdapterFactoryV1 | None,
    ) -> None:
        if type(gate) is not DayOpsFeatureGateV1:
            raise DayOpsLiveV1ContractError("sealed feature gate required")
        if adapter_factory is not None and not callable(adapter_factory):
            raise DayOpsLiveV1ContractError("adapter factory must be callable")
        self._gate = gate
        self._factory = adapter_factory

    def execute(
        self,
        arguments: Mapping[str, object] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> DayOpsExecutionV1:
        if not self._gate.enabled:
            return _safe_status("disabled", "DayOps is disabled.")
        configuration = DayOpsConfigurationV1.from_environ(environ)
        if configuration is None:
            return _safe_status(
                "configuration_required",
                "DayOps Microsoft configuration is incomplete.",
            )
        selected_now = datetime.now(timezone.utc) if now is None else now
        if not isinstance(selected_now, datetime) or selected_now.tzinfo is None:
            raise DayOpsLiveV1ContractError("clock must be timezone-aware")
        selected_arguments = dict(arguments or {})
        try:
            zone = ZoneInfo(configuration.iana_timezone)
            selected_date = _requested_date(selected_arguments, selected_now, zone)
            if self._factory is None:
                return _safe_status(
                    "unavailable",
                    "DayOps Microsoft adapter is unavailable.",
                )
            local_start = datetime.combine(selected_date, time.min, tzinfo=zone)
            local_end = local_start + timedelta(days=1)
            now_ms = int(selected_now.timestamp() * 1_000)
            adapter = self._factory(now_ms)
            if type(adapter) is not MicrosoftGraphReadAdapterV1:
                return _safe_status(
                    "unavailable",
                    "DayOps Microsoft adapter is unavailable.",
                )
            try:
                brief = adapter.daily_brief(
                    window_start=local_start.astimezone(timezone.utc).isoformat(),
                    window_end=local_end.astimezone(timezone.utc).isoformat(),
                    outlook_timezone=configuration.outlook_timezone,
                    now_ms=now_ms,
                    generated_at=selected_now.astimezone(timezone.utc).isoformat(),
                )
            finally:
                close = getattr(self._factory, "close", None)
                if callable(close):
                    close()
            if (
                type(brief) is not ExecutiveOfficeBriefV1
                or brief.read_only is not True
                or brief.provider_content_untrusted is not True
            ):
                raise DayOpsLiveV1Error("Graph brief contract drift")
            return DayOpsExecutionV1("completed", _sanitized(brief))
        except DayOpsLiveV1ContractError:
            raise
        except DayOpsConfigurationRequiredV1:
            return _safe_status(
                "configuration_required",
                "DayOps Microsoft configuration is incomplete.",
            )
        except DayOpsAuthenticationRequiredV1:
            return _safe_status(
                "authentication_required",
                "Microsoft sign-in is required.",
            )
        except Exception as exc:
            return DayOpsExecutionV1(
                "failed",
                {
                    "status": "failed",
                    "read_only": True,
                    "result": "DayOps read failed safely.",
                },
                type(exc).__name__,
            )


def create_dayops_live_integration_v1(
    *,
    gate: DayOpsFeatureGateV1 | None = None,
    adapter_factory: AdapterFactoryV1 | None = None,
    environ: Mapping[str, str] | None = None,
) -> DayOpsLiveIntegrationV1 | None:
    selected = DayOpsFeatureGateV1.from_environ(environ) if gate is None else gate
    if type(selected) is not DayOpsFeatureGateV1:
        raise DayOpsLiveV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    return DayOpsLiveIntegrationV1(
        gate=selected,
        adapter_factory=adapter_factory,
    )


__all__ = [
    "AdapterFactoryV1",
    "DayOpsAuthenticationRequiredV1",
    "DayOpsConfigurationV1",
    "DayOpsConfigurationRequiredV1",
    "DayOpsExecutionV1",
    "DayOpsFeatureGateV1",
    "DayOpsLiveIntegrationV1",
    "DayOpsLiveV1ContractError",
    "DayOpsLiveV1Error",
    "FEATURE_FLAG",
    "IANA_TIMEZONE_KEY",
    "OUTLOOK_TIMEZONE_KEY",
    "SCHEMA",
    "TOOL_NAME",
    "create_dayops_live_integration_v1",
    "sanitized_brief_sha256_v1",
    "tool_declaration_v1",
]
