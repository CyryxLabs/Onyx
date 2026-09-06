"""Default-off Microsoft Graph calendar/mail read and local-draft foundation.

The adapter is workspace/principal/credential-alias bound. It permits only
hard-coded Microsoft Graph v1.0 GET routes and returns bounded normalized
records. Drafts are local immutable values; this module cannot create events,
send mail, or perform any other mutation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Mapping, Protocol
from urllib.parse import parse_qsl, quote, urlparse

from core.phase7_workspace_aliases_v1 import (
    WorkspaceAliasCatalogV1,
    WorkspaceAliasRecordV1,
    WorkspaceAliasV1Denied,
)

FEATURE_FLAG: Final = "ONYX_PHASE8_MICROSOFT_GRAPH_READ_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxMicrosoftGraphRead.v1"
GRAPH_ORIGIN: Final = "https://graph.microsoft.com"
GRAPH_PREFIX: Final = "/v1.0/"
MAX_PAGES: Final = 5
MAX_ITEMS: Final = 250
CALENDAR_SCOPES: Final = frozenset(
    {"Calendars.ReadBasic", "Calendars.Read", "Calendars.ReadWrite"}
)
MAIL_SCOPES: Final = frozenset({"Mail.ReadBasic", "Mail.Read", "Mail.ReadWrite"})
MAIL_BODY_SCOPES: Final = frozenset({"Mail.Read", "Mail.ReadWrite"})
PHASE7_EXIT_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase7-exit-candidate-v1/manifest.json",
        "19cb98bb51a14617538aafb9c1f17cb52818e78991b51269ee3b0f126db505e4",
    ),
    (
        "docs/onyx/acceptance/VE-P7-EXIT-CANDIDATE-V1-E6-001.md",
        "4e21bc72888ae66a2d07a21e94d08175aac163ade72802d417a4438e7728c8a5",
    ),
    (
        "docs/onyx/acceptance/VE-P7-EXIT-CANDIDATE-V1-E6-001.manifest.json",
        "c957674c6e3e543d647ed397eff777bb8b99d7af7e03a6909893af947bab91b9",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P7-EXIT-CANDIDATE-V1-E6-001.sha256",
        "214e181fac5fde6127b36bda98ec8755765143acfaac1f54921deb04db193e37",
    ),
)
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}$")
_ZONE = re.compile(r"^[A-Za-z0-9 _./+-]{1,80}$")
_SEARCH = re.compile(r'^[^\x00-\x1f"\\]{1,160}$')
_CONSTRUCTION_KEY = object()


class GraphReadV1Error(RuntimeError):
    pass


class GraphReadV1ContractError(ValueError):
    pass


class GraphReadV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class GraphReadFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GraphReadV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GraphReadFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class GraphHttpResponseV1:
    status_code: int
    payload: dict[str, object]
    request_id: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.status_code) is not int
            or not 100 <= self.status_code <= 599
            or type(self.payload) is not dict
            or (self.request_id is not None and type(self.request_id) is not str)
        ):
            raise GraphReadV1ContractError("Graph response is invalid")


class GraphReadTransportV1(Protocol):
    def get(
        self,
        *,
        url: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
    ) -> GraphHttpResponseV1: ...


@dataclass(frozen=True, slots=True)
class CalendarEventV1:
    event_id: str
    subject: str
    start: str
    end: str
    timezone: str
    location: str
    organizer: str
    attendees: tuple[str, ...]
    is_all_day: bool
    is_cancelled: bool
    web_link: str


@dataclass(frozen=True, slots=True)
class UnreadMessageV1:
    message_id: str
    subject: str
    sender: str
    received_at: str
    importance: str
    has_attachments: bool
    conversation_id: str
    web_link: str


@dataclass(frozen=True, slots=True)
class MessageDetailV1:
    message_id: str
    subject: str
    sender: str
    recipients: tuple[str, ...]
    cc: tuple[str, ...]
    received_at: str
    importance: str
    has_attachments: bool
    conversation_id: str
    web_link: str
    body_type: str
    body_content: str
    untrusted_content: bool = True


@dataclass(frozen=True, slots=True)
class LocalEventDraftV1:
    subject: str
    start: str
    end: str
    timezone: str
    location: str
    attendees: tuple[str, ...]
    body_text: str
    draft_sha256: str
    mutation_authority: bool = False


@dataclass(frozen=True, slots=True)
class LocalEmailDraftV1:
    recipients: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str
    body_text: str
    reply_to_message_id: str | None
    draft_sha256: str
    mutation_authority: bool = False


@dataclass(frozen=True, slots=True)
class ExecutiveOfficeBriefV1:
    workspace_id: str
    principal_id: str
    account_id: str
    window_start: str
    window_end: str
    events: tuple[CalendarEventV1, ...]
    unread_messages: tuple[UnreadMessageV1, ...]
    calendar_has_more: bool
    mail_has_more: bool
    generated_at: str
    brief_sha256: str
    read_only: bool = True
    provider_content_untrusted: bool = False


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in PHASE7_EXIT_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GraphReadV1Denied("Phase 7 exit evidence unavailable") from exc
        if not hmac.compare_digest(actual, expected):
            raise GraphReadV1Denied("Phase 7 exit evidence drift")


def _utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise GraphReadV1ContractError("timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise GraphReadV1ContractError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _text(value: object, maximum: int = 500) -> str:
    if value is None:
        return ""
    if type(value) is not str or len(value) > maximum or "\x00" in value:
        raise GraphReadV1Denied("provider text contract drift")
    return value


def _email(value: object) -> str:
    text = _text(value, 254).casefold()
    if not _EMAIL.fullmatch(text):
        raise GraphReadV1ContractError("email address is invalid")
    return text


def _exact_bool(value: object, *, label: str) -> bool:
    if type(value) is not bool:
        raise GraphReadV1Denied(f"{label} contract drift")
    return value


def _importance(value: object) -> str:
    selected = _text(value, 20).casefold()
    if selected not in {"low", "normal", "high"}:
        raise GraphReadV1Denied("message importance drift")
    return selected


def _graph_identifier(value: object) -> str:
    identifier = _text(value, 512)
    if (
        not identifier
        or identifier in {".", ".."}
        or any(ord(character) < 32 for character in identifier)
    ):
        raise GraphReadV1ContractError("Graph identifier is invalid")
    return identifier


def _safe_next_link(
    value: object,
    *,
    expected_path: str,
) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    if value is None:
        return None
    if type(value) is not str:
        raise GraphReadV1Denied("nextLink contract drift")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "graph.microsoft.com"
        or parsed.path != expected_path
        or parsed.fragment
    ):
        raise GraphReadV1Denied("cross-route nextLink denied")
    query = tuple(parse_qsl(parsed.query, keep_blank_values=True))
    if len(query) > 20 or any(
        len(key) > 100 or len(item) > 4_096 for key, item in query
    ):
        raise GraphReadV1Denied("nextLink query contract drift")
    return f"{GRAPH_ORIGIN}{parsed.path}", query


def _emails(value: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if type(value) not in {tuple, list} or len(value) > 100:
        raise GraphReadV1ContractError("recipient collection is invalid")
    normalized = tuple(_email(item) for item in value)
    if len(set(normalized)) != len(normalized):
        raise GraphReadV1ContractError("duplicate recipient is invalid")
    return normalized


def _draft_sha256(kind: str, payload: dict[str, object]) -> str:
    return hashlib.sha256(_canonical({"kind": kind, **payload})).hexdigest()


class MicrosoftGraphReadAdapterV1:
    __slots__ = (
        "_aliases",
        "_credential",
        "_transport",
        "_workspace_id",
        "_principal_id",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        aliases: WorkspaceAliasCatalogV1,
        credential_alias_name: str,
        transport: GraphReadTransportV1,
        now_ms: int,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GraphReadV1ContractError("use create_microsoft_graph_read_adapter_v1")
        if type(aliases) is not WorkspaceAliasCatalogV1:
            raise GraphReadV1ContractError("exact WorkspaceAliasCatalogV1 required")
        try:
            credential = aliases.get(
                kind="credential", alias_name=credential_alias_name, now_ms=now_ms
            )
        except WorkspaceAliasV1Denied as exc:
            raise GraphReadV1Denied("credential alias unavailable") from exc
        if (
            credential.provider != "microsoft-graph"
            or not (set(credential.scopes) & CALENDAR_SCOPES)
            or not (set(credential.scopes) & MAIL_SCOPES)
            or (
                credential.rotate_after_ms is not None
                and now_ms >= credential.rotate_after_ms
            )
        ):
            raise GraphReadV1Denied("least-privilege Graph read scopes unavailable")
        if not hasattr(transport, "get"):
            raise GraphReadV1ContractError("Graph read transport required")
        self._aliases = aliases
        self._credential = credential
        self._transport = transport
        self._workspace_id = aliases.workspace_id
        self._principal_id = aliases.principal_id

    def _attest(self, now_ms: int) -> WorkspaceAliasRecordV1:
        try:
            current = self._aliases.get(
                kind="credential",
                alias_name=self._credential.alias_name,
                now_ms=now_ms,
            )
        except WorkspaceAliasV1Denied as exc:
            raise GraphReadV1Denied("credential alias no longer available") from exc
        if (
            current != self._credential
            or self._aliases.workspace_id != self._workspace_id
            or self._aliases.principal_id != self._principal_id
            or (
                current.rotate_after_ms is not None
                and now_ms >= current.rotate_after_ms
            )
        ):
            raise GraphReadV1Denied("Graph adapter binding drift")
        return current

    def _pages(
        self,
        path: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
        *,
        now_ms: int,
    ) -> tuple[list[dict[str, object]], bool]:
        self._attest(now_ms)
        url = f"{GRAPH_ORIGIN}{GRAPH_PREFIX}{path.lstrip('/')}"
        expected_path = urlparse(url).path
        items: list[dict[str, object]] = []
        has_more = False
        for _page in range(MAX_PAGES):
            response = self._transport.get(url=url, query=query, headers=headers)
            if type(response) is not GraphHttpResponseV1 or response.status_code != 200:
                raise GraphReadV1Error("Microsoft Graph read failed")
            value = response.payload.get("value")
            if type(value) is not list or any(type(item) is not dict for item in value):
                raise GraphReadV1Denied("Microsoft Graph collection drift")
            items.extend(value)
            if len(items) > MAX_ITEMS:
                items = items[:MAX_ITEMS]
                has_more = True
                break
            next_page = _safe_next_link(
                response.payload.get("@odata.nextLink"),
                expected_path=expected_path,
            )
            if next_page is None:
                break
            url, query = next_page
        else:
            has_more = True
        self._attest(now_ms)
        return items, has_more

    def _object(
        self,
        path: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...] = (),
        *,
        now_ms: int,
    ) -> dict[str, object]:
        self._attest(now_ms)
        url = f"{GRAPH_ORIGIN}{GRAPH_PREFIX}{path.lstrip('/')}"
        response = self._transport.get(url=url, query=query, headers=headers)
        if type(response) is not GraphHttpResponseV1 or response.status_code != 200:
            raise GraphReadV1Error("Microsoft Graph read failed")
        if "value" in response.payload or "@odata.nextLink" in response.payload:
            raise GraphReadV1Denied("Microsoft Graph object drift")
        self._attest(now_ms)
        return response.payload

    def daily_brief(
        self,
        *,
        window_start: str,
        window_end: str,
        outlook_timezone: str,
        now_ms: int,
        generated_at: str,
    ) -> ExecutiveOfficeBriefV1:
        start, end = _utc(window_start), _utc(window_end)
        if start >= end or not _ZONE.fullmatch(outlook_timezone):
            raise GraphReadV1ContractError("calendar window or timezone is invalid")
        raw_events, calendar_more = self._pages(
            "me/calendarView",
            (
                ("startDateTime", start),
                ("endDateTime", end),
                (
                    "$select",
                    "id,subject,start,end,location,organizer,attendees,isAllDay,isCancelled,webLink",
                ),
                ("$orderby", "start/dateTime"),
                ("$top", "50"),
            ),
            (("Prefer", f'outlook.timezone="{outlook_timezone}"'),),
            now_ms=now_ms,
        )
        events = tuple(_event(item) for item in raw_events)
        raw_mail, mail_more = self._pages(
            "me/messages",
            (
                ("$filter", "isRead eq false"),
                (
                    "$select",
                    "id,subject,from,receivedDateTime,importance,hasAttachments,conversationId,webLink",
                ),
                ("$orderby", "receivedDateTime desc"),
                ("$top", "50"),
            ),
            (),
            now_ms=now_ms,
        )
        mail = tuple(_message(item) for item in raw_mail)
        payload = {
            "workspace_id": self._workspace_id,
            "principal_id": self._principal_id,
            "account_id": self._credential.account_id,
            "window_start": start,
            "window_end": end,
            "events": [asdict(event) for event in events],
            "mail": [asdict(message) for message in mail],
            "calendar_has_more": calendar_more,
            "mail_has_more": mail_more,
            "generated_at": _utc(generated_at),
        }
        return ExecutiveOfficeBriefV1(
            self._workspace_id,
            self._principal_id,
            self._credential.account_id or "",
            start,
            end,
            events,
            mail,
            calendar_more,
            mail_more,
            payload["generated_at"],
            hashlib.sha256(_canonical(payload)).hexdigest(),
            provider_content_untrusted=True,
        )

    def search_messages(
        self,
        *,
        search_text: str,
        now_ms: int,
    ) -> tuple[UnreadMessageV1, ...]:
        if type(search_text) is not str or not _SEARCH.fullmatch(search_text):
            raise GraphReadV1ContractError("mail search text is invalid")
        raw, _has_more = self._pages(
            "me/messages",
            (
                ("$search", f'"{search_text}"'),
                (
                    "$select",
                    "id,subject,from,receivedDateTime,importance,"
                    "hasAttachments,conversationId,webLink",
                ),
                ("$top", "50"),
            ),
            (("ConsistencyLevel", "eventual"),),
            now_ms=now_ms,
        )
        return tuple(_message(item) for item in raw)

    def read_message(
        self,
        *,
        message_id: str,
        now_ms: int,
    ) -> MessageDetailV1:
        if not (set(self._credential.scopes) & MAIL_BODY_SCOPES):
            raise GraphReadV1Denied("mail body scope unavailable")
        identifier = _graph_identifier(message_id)
        raw = self._object(
            f"me/messages/{quote(identifier, safe='')}",
            (
                (
                    "$select",
                    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,"
                    "importance,hasAttachments,conversationId,webLink,body",
                ),
            ),
            (("Prefer", 'outlook.body-content-type="text"'),),
            now_ms=now_ms,
        )
        return _message_detail(raw)

    def draft_event(
        self,
        *,
        subject: str,
        start: str,
        end: str,
        timezone_name: str,
        location: str = "",
        attendees: tuple[str, ...] = (),
        body_text: str = "",
    ) -> LocalEventDraftV1:
        normalized_subject = _text(subject, 1_000).strip()
        normalized_start, normalized_end = _utc(start), _utc(end)
        if (
            not normalized_subject
            or normalized_start >= normalized_end
            or type(timezone_name) is not str
            or not _ZONE.fullmatch(timezone_name)
        ):
            raise GraphReadV1ContractError("event draft is invalid")
        normalized_attendees = _emails(attendees)
        normalized_location = _text(location, 500)
        normalized_body = _text(body_text, 50_000)
        payload: dict[str, object] = {
            "subject": normalized_subject,
            "start": normalized_start,
            "end": normalized_end,
            "timezone": timezone_name,
            "location": normalized_location,
            "attendees": normalized_attendees,
            "body_text": normalized_body,
        }
        return LocalEventDraftV1(
            subject=normalized_subject,
            start=normalized_start,
            end=normalized_end,
            timezone=timezone_name,
            location=normalized_location,
            attendees=normalized_attendees,
            body_text=normalized_body,
            draft_sha256=_draft_sha256("event", payload),
        )

    def draft_email(
        self,
        *,
        recipients: tuple[str, ...],
        subject: str,
        body_text: str,
        cc: tuple[str, ...] = (),
        reply_to_message_id: str | None = None,
    ) -> LocalEmailDraftV1:
        normalized_recipients = _emails(recipients)
        normalized_cc = _emails(cc)
        if not normalized_recipients or set(normalized_recipients) & set(normalized_cc):
            raise GraphReadV1ContractError("email recipients are invalid")
        normalized_subject = _text(subject, 1_000).strip()
        normalized_body = _text(body_text, 50_000)
        if not normalized_subject or not normalized_body.strip():
            raise GraphReadV1ContractError("email draft is incomplete")
        reply_id = (
            None
            if reply_to_message_id is None
            else _graph_identifier(reply_to_message_id)
        )
        payload: dict[str, object] = {
            "recipients": normalized_recipients,
            "cc": normalized_cc,
            "subject": normalized_subject,
            "body_text": normalized_body,
            "reply_to_message_id": reply_id,
        }
        return LocalEmailDraftV1(
            recipients=normalized_recipients,
            cc=normalized_cc,
            subject=normalized_subject,
            body_text=normalized_body,
            reply_to_message_id=reply_id,
            draft_sha256=_draft_sha256("email", payload),
        )


def _event(raw: dict[str, object]) -> CalendarEventV1:
    start = raw.get("start")
    end = raw.get("end")
    organizer = raw.get("organizer") or {}
    location = raw.get("location") or {}
    if (
        type(start) is not dict
        or type(end) is not dict
        or type(organizer) is not dict
        or type(location) is not dict
    ):
        raise GraphReadV1Denied("event shape drift")
    attendees_raw = raw.get("attendees") or []
    if type(attendees_raw) is not list:
        raise GraphReadV1Denied("event attendees drift")
    attendees = []
    for item in attendees_raw:
        if type(item) is not dict or type(item.get("emailAddress")) is not dict:
            raise GraphReadV1Denied("event attendee drift")
        attendees.append(_email(item["emailAddress"].get("address")))
    organizer_address = organizer.get("emailAddress") or {}
    if type(organizer_address) is not dict:
        raise GraphReadV1Denied("organizer drift")
    return CalendarEventV1(
        _text(raw.get("id"), 512),
        _text(raw.get("subject"), 1_000),
        _text(start.get("dateTime"), 80),
        _text(end.get("dateTime"), 80),
        _text(start.get("timeZone"), 80),
        _text(location.get("displayName"), 500),
        _email(organizer_address.get("address")),
        tuple(attendees),
        _exact_bool(raw.get("isAllDay"), label="event isAllDay"),
        _exact_bool(raw.get("isCancelled"), label="event isCancelled"),
        _text(raw.get("webLink"), 2_048),
    )


def _message(raw: dict[str, object]) -> UnreadMessageV1:
    sender = raw.get("from") or {}
    if type(sender) is not dict or type(sender.get("emailAddress")) is not dict:
        raise GraphReadV1Denied("message sender drift")
    return UnreadMessageV1(
        _text(raw.get("id"), 512),
        _text(raw.get("subject"), 1_000),
        _email(sender["emailAddress"].get("address")),
        _utc(_text(raw.get("receivedDateTime"), 80)),
        _importance(raw.get("importance")),
        _exact_bool(raw.get("hasAttachments"), label="message hasAttachments"),
        _text(raw.get("conversationId"), 512),
        _text(raw.get("webLink"), 2_048),
    )


def _recipient_addresses(raw: object, *, label: str) -> tuple[str, ...]:
    if type(raw) is not list or len(raw) > 100:
        raise GraphReadV1Denied(f"{label} drift")
    values: list[str] = []
    for item in raw:
        if type(item) is not dict or type(item.get("emailAddress")) is not dict:
            raise GraphReadV1Denied(f"{label} drift")
        values.append(_email(item["emailAddress"].get("address")))
    if len(set(values)) != len(values):
        raise GraphReadV1Denied(f"{label} duplicate drift")
    return tuple(values)


def _message_detail(raw: dict[str, object]) -> MessageDetailV1:
    sender = raw.get("from") or {}
    body = raw.get("body") or {}
    if (
        type(sender) is not dict
        or type(sender.get("emailAddress")) is not dict
        or type(body) is not dict
    ):
        raise GraphReadV1Denied("message detail drift")
    body_type = _text(body.get("contentType"), 20).casefold()
    if body_type not in {"text", "html"}:
        raise GraphReadV1Denied("message body type drift")
    return MessageDetailV1(
        _text(raw.get("id"), 512),
        _text(raw.get("subject"), 1_000),
        _email(sender["emailAddress"].get("address")),
        _recipient_addresses(raw.get("toRecipients") or [], label="to recipients"),
        _recipient_addresses(raw.get("ccRecipients") or [], label="cc recipients"),
        _utc(_text(raw.get("receivedDateTime"), 80)),
        _importance(raw.get("importance")),
        _exact_bool(raw.get("hasAttachments"), label="message hasAttachments"),
        _text(raw.get("conversationId"), 512),
        _text(raw.get("webLink"), 2_048),
        body_type,
        _text(body.get("content"), 250_000),
    )


def create_microsoft_graph_read_adapter_v1(
    *,
    gate: GraphReadFeatureGateV1 | None = None,
    aliases: WorkspaceAliasCatalogV1 | None = None,
    credential_alias_name: str | None = None,
    transport: GraphReadTransportV1 | None = None,
    now_ms: int | None = None,
    project_root: Path | str | None = None,
) -> MicrosoftGraphReadAdapterV1 | None:
    selected = GraphReadFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not GraphReadFeatureGateV1:
        raise GraphReadV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    if (
        aliases is None
        or credential_alias_name is None
        or transport is None
        or now_ms is None
    ):
        raise GraphReadV1ContractError(
            "enabled adapter requires complete host bindings"
        )
    return MicrosoftGraphReadAdapterV1(
        construction_key=_CONSTRUCTION_KEY,
        aliases=aliases,
        credential_alias_name=credential_alias_name,
        transport=transport,
        now_ms=now_ms,
    )


__all__ = [
    "CalendarEventV1",
    "ExecutiveOfficeBriefV1",
    "FEATURE_FLAG",
    "GraphHttpResponseV1",
    "GraphReadFeatureGateV1",
    "GraphReadTransportV1",
    "GraphReadV1ContractError",
    "GraphReadV1Denied",
    "GraphReadV1Error",
    "LocalEmailDraftV1",
    "LocalEventDraftV1",
    "MessageDetailV1",
    "MicrosoftGraphReadAdapterV1",
    "UnreadMessageV1",
    "create_microsoft_graph_read_adapter_v1",
]
