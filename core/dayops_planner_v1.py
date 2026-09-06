"""Deterministic, read-only DayOps chief-of-staff projection.

Provider strings are untrusted data.  This module does not interpret message
bodies, execute instructions, perform I/O, or grant mutation authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.dayops_live_integration_v1 import (
    DayOpsLiveV1ContractError,
    sanitized_brief_sha256_v1,
)
from core.phase8_microsoft_graph_read_v1 import ExecutiveOfficeBriefV1

SCHEMA: Final = "OnyxDayOpsPlanner.v1"
MAX_SOURCE_ITEMS: Final = 500
MAX_OUTPUT_ITEMS: Final = 50
FUTURE_TOLERANCE: Final = timedelta(minutes=5)
FRESH_AFTER: Final = timedelta(hours=2)
STALE_AFTER: Final = timedelta(hours=12)
PREP_WINDOW: Final = timedelta(minutes=15)
MIN_FOCUS_GAP: Final = timedelta(minutes=45)
_SPACE = re.compile(r"\s+")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class DayOpsPlannerV1ContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AttentionItemV1:
    kind: str
    priority: int
    summary: str
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImportantUnreadV1:
    evidence_ref: str
    sender: str
    subject: str
    received_at: str
    importance: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalendarConflictV1:
    event_refs: tuple[str, str]
    start: str
    end: str
    reasons: tuple[str, ...] = ("calendar_overlap",)


@dataclass(frozen=True, slots=True)
class NextMeetingV1:
    evidence_ref: str
    subject: str
    start: str
    end: str
    prep_window_start: str
    prep_window_end: str


@dataclass(frozen=True, slots=True)
class OngoingMeetingV1:
    evidence_ref: str
    subject: str
    start: str
    end: str
    status: str = "ongoing"


@dataclass(frozen=True, slots=True)
class FollowUpCandidateV1:
    evidence_ref: str
    sender: str
    subject: str
    received_at: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FocusGapV1:
    start: str
    end: str
    minutes: int


@dataclass(frozen=True, slots=True)
class DateMentionV1:
    evidence_ref: str
    source: str
    value: str
    reason: str


@dataclass(frozen=True, slots=True)
class StructuredDeadlineV1:
    evidence_ref: str
    value: str
    source: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageDisclosureV1:
    timezone: str
    generated_at: str
    freshness: str
    age_seconds: int
    calendar_has_more: bool
    mail_has_more: bool
    source_truncated: bool
    output_truncated: bool
    dropped_invalid_events: int
    dropped_invalid_messages: int
    calendar_pagination: str = "unknown"
    mail_pagination: str = "unknown"
    clock_skew_detected: bool = False
    future_messages_excluded: int = 0
    structured_deadline_metadata_available: bool = False
    reply_metadata_available: bool = False
    provider_content_untrusted: bool = False
    bodies_used_as_instructions: bool = False


@dataclass(frozen=True, slots=True)
class DayOpsPlanV1:
    schema: str
    read_only: bool
    window_start: str
    window_end: str
    attention_items: tuple[AttentionItemV1, ...]
    important_unread: tuple[ImportantUnreadV1, ...]
    calendar_conflicts: tuple[CalendarConflictV1, ...]
    next_meeting: NextMeetingV1 | None
    ongoing_meetings: tuple[OngoingMeetingV1, ...]
    deadlines: tuple[StructuredDeadlineV1, ...]
    date_mentions: tuple[DateMentionV1, ...]
    follow_up_candidates: tuple[FollowUpCandidateV1, ...]
    focus_gaps: tuple[FocusGapV1, ...]
    coverage: CoverageDisclosureV1
    plan_sha256: str
    mutation_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _Event:
    ref: str
    subject: str
    start: datetime
    end: datetime
    is_all_day: bool
    is_cancelled: bool
    provider_identity: str


@dataclass(frozen=True, slots=True)
class _Message:
    ref: str
    subject: str
    sender: str
    received_at: datetime
    importance: str
    has_attachments: bool
    provider_identity: str


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _text(value: object, maximum: int) -> str:
    if type(value) is not str:
        return ""
    cleaned = "".join(character for character in value if ord(character) >= 32)
    return _SPACE.sub(" ", cleaned).strip()[:maximum]


def _ref(kind: str, values: Sequence[object]) -> str:
    digest = hashlib.sha256(_canonical([kind, *values])).hexdigest()
    return f"{kind}:{digest}"


def _aware(value: object, zone: ZoneInfo) -> datetime | None:
    if type(value) is not str or len(value) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    candidate_0 = parsed.replace(tzinfo=zone, fold=0)
    candidate_1 = parsed.replace(tzinfo=zone, fold=1)
    valid_0 = (
        candidate_0.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        == parsed
    )
    valid_1 = (
        candidate_1.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        == parsed
    )
    # A gap has no valid representation.  An ambiguous wall time needs an
    # explicit offset so that fall-back ordering cannot be guessed.
    if not valid_0 or not valid_1:
        return None
    utc_0 = candidate_0.astimezone(timezone.utc)
    utc_1 = candidate_1.astimezone(timezone.utc)
    if utc_0 != utc_1:
        return None
    return utc_0


def _exact_bool(value: object, default: bool = False) -> bool:
    return value if type(value) is bool else default


def _snapshot(
    source: ExecutiveOfficeBriefV1 | Mapping[str, object],
) -> tuple[dict[str, object], list[object], list[object]]:
    if type(source) is ExecutiveOfficeBriefV1:
        expected_digest = hashlib.sha256(
            _canonical(
                {
                    "workspace_id": source.workspace_id,
                    "principal_id": source.principal_id,
                    "account_id": source.account_id,
                    "window_start": source.window_start,
                    "window_end": source.window_end,
                    "events": [asdict(item) for item in source.events],
                    "mail": [asdict(item) for item in source.unread_messages],
                    "calendar_has_more": source.calendar_has_more,
                    "mail_has_more": source.mail_has_more,
                    "generated_at": source.generated_at,
                }
            )
        ).hexdigest()
        if (
            source.read_only is not True
            or source.provider_content_untrusted is not True
            or type(source.calendar_has_more) is not bool
            or type(source.mail_has_more) is not bool
            or type(source.brief_sha256) is not str
            or not hmac.compare_digest(source.brief_sha256, expected_digest)
        ):
            raise DayOpsPlannerV1ContractError(
                "accepted Executive Office brief provenance required"
            )
        return (
            {
                "window_start": source.window_start,
                "window_end": source.window_end,
                "generated_at": source.generated_at,
                "calendar_has_more": source.calendar_has_more,
                "mail_has_more": source.mail_has_more,
                "brief_sha256": source.brief_sha256,
                "read_only": source.read_only,
                "provider_content_untrusted": source.provider_content_untrusted,
            },
            list(source.events),
            list(source.unread_messages),
        )
    if not isinstance(source, Mapping) or source.get("read_only") is not True:
        raise DayOpsPlannerV1ContractError("accepted read-only snapshot required")
    if source.get("verification") != "provider_response_normalized":
        raise DayOpsPlannerV1ContractError(
            "exact normalized-provider verification marker required"
        )
    brief_sha256 = source.get("brief_sha256")
    if type(brief_sha256) is not str or not _HEX64.fullmatch(brief_sha256):
        raise DayOpsPlannerV1ContractError("normalized brief digest required")
    if source.get("provider_content_untrusted") is not True:
        raise DayOpsPlannerV1ContractError(
            "snapshot must preserve provider-content trust marking"
        )
    normalized = dict(source)
    try:
        expected_digest = sanitized_brief_sha256_v1(normalized)
    except DayOpsLiveV1ContractError as exc:
        raise DayOpsPlannerV1ContractError(
            "exact sanitized brief provenance required"
        ) from exc
    if not hmac.compare_digest(brief_sha256, expected_digest):
        raise DayOpsPlannerV1ContractError("exact sanitized brief provenance required")
    events = normalized.get("events", [])
    messages = normalized.get("unread_messages", [])
    if not isinstance(events, (list, tuple)) or not isinstance(messages, (list, tuple)):
        raise DayOpsPlannerV1ContractError("snapshot collections are invalid")
    return normalized, list(events), list(messages)


def _value(item: object, name: str, default: object = "") -> object:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _provider_identity(item: object) -> str:
    value = _value(item, "source_ref")
    if type(value) is str and _HEX64.fullmatch(value):
        return value
    return ""


def _events(raw: list[object], zone: ZoneInfo) -> tuple[list[_Event], int, bool]:
    grouped: dict[str, list[_Event]] = {}
    invalid = 0
    source_truncated = len(raw) > MAX_SOURCE_ITEMS
    for item in raw[:MAX_SOURCE_ITEMS]:
        start = _aware(_value(item, "start"), zone)
        end = _aware(_value(item, "end"), zone)
        if start is None or end is None or end <= start:
            invalid += 1
            continue
        subject = _text(_value(item, "subject"), 240) or "Untitled calendar item"
        all_day = _exact_bool(_value(item, "is_all_day"))
        cancelled = _exact_bool(_value(item, "is_cancelled"))
        provider_identity = _provider_identity(item)
        canonical = (
            subject.casefold(),
            start.isoformat(),
            end.isoformat(),
            all_day,
            cancelled,
        )
        identity = f"id:{provider_identity}" if provider_identity else ""
        event = _Event(
            _ref("event", (identity, *canonical)),
            subject,
            start,
            end,
            all_day,
            cancelled,
            identity,
        )
        grouped.setdefault(
            identity or f"record:{_ref('event-record', canonical)}", []
        ).append(event)

    result: list[_Event] = []
    for identity, candidates in grouped.items():
        ordered = sorted(
            candidates,
            key=lambda item: (
                item.subject.casefold(),
                item.start,
                item.end,
                item.is_all_day,
                item.is_cancelled,
                item.ref,
            ),
        )
        if identity.startswith("id:"):
            cancelled = any(item.is_cancelled for item in ordered)
            selected = ordered[0]
            result.append(
                _Event(
                    _ref("event", (identity,)),
                    selected.subject,
                    selected.start,
                    selected.end,
                    selected.is_all_day,
                    cancelled,
                    identity,
                )
            )
        else:
            # Preserve every id-less record.  Occurrence suffixes keep exact
            # duplicates distinct without depending on provider input order.
            for occurrence, selected in enumerate(ordered):
                result.append(
                    _Event(
                        _ref("event", (identity, occurrence)),
                        selected.subject,
                        selected.start,
                        selected.end,
                        selected.is_all_day,
                        selected.is_cancelled,
                        "",
                    )
                )
    return (
        sorted(result, key=lambda item: (item.start, item.end, item.ref)),
        invalid,
        source_truncated,
    )


def _messages(raw: list[object], zone: ZoneInfo) -> tuple[list[_Message], int, bool]:
    grouped: dict[str, list[_Message]] = {}
    invalid = 0
    source_truncated = len(raw) > MAX_SOURCE_ITEMS
    for item in raw[:MAX_SOURCE_ITEMS]:
        received = _aware(_value(item, "received_at"), zone)
        if received is None:
            invalid += 1
            continue
        subject = _text(_value(item, "subject"), 240) or "No subject"
        sender = _text(_value(item, "sender"), 254).casefold()
        if not sender:
            invalid += 1
            continue
        importance = _value(item, "importance")
        if type(importance) is not str or importance not in {"low", "normal", "high"}:
            invalid += 1
            continue
        provider_identity = _provider_identity(item)
        canonical = (
            sender,
            subject.casefold(),
            received.isoformat(),
            importance,
            _exact_bool(_value(item, "has_attachments")),
        )
        identity = f"id:{provider_identity}" if provider_identity else ""
        message = _Message(
            _ref("message", (identity, *canonical)),
            subject,
            sender,
            received,
            importance,
            canonical[-1],
            identity,
        )
        grouped.setdefault(
            identity or f"record:{_ref('message-record', canonical)}", []
        ).append(message)
    result: list[_Message] = []
    importance_rank = {"low": 0, "normal": 1, "high": 2}
    for identity, candidates in grouped.items():
        ordered = sorted(
            candidates,
            key=lambda item: (
                item.sender,
                item.subject.casefold(),
                item.received_at,
                item.importance,
                item.has_attachments,
                item.ref,
            ),
        )
        if identity.startswith("id:"):
            selected = ordered[0]
            importance = max(
                (item.importance for item in ordered), key=importance_rank.__getitem__
            )
            result.append(
                _Message(
                    _ref("message", (identity,)),
                    selected.subject,
                    selected.sender,
                    selected.received_at,
                    importance,
                    any(item.has_attachments for item in ordered),
                    identity,
                )
            )
        else:
            for occurrence, selected in enumerate(ordered):
                result.append(
                    _Message(
                        _ref("message", (identity, occurrence)),
                        selected.subject,
                        selected.sender,
                        selected.received_at,
                        selected.importance,
                        selected.has_attachments,
                        "",
                    )
                )
    ordered = sorted(result, key=lambda item: (-item.received_at.timestamp(), item.ref))
    return ordered, invalid, source_truncated


def _iso(value: datetime, zone: ZoneInfo) -> str:
    return value.astimezone(zone).isoformat()


def _freshness(generated: datetime, now: datetime) -> tuple[str, int]:
    delta = now - generated
    if delta < -FUTURE_TOLERANCE:
        return "clock_skew", 0
    age = max(0, int(delta.total_seconds()))
    if age <= int(FRESH_AFTER.total_seconds()):
        return "fresh", age
    if age <= int(STALE_AFTER.total_seconds()):
        return "aging", age
    return "stale", age


def plan_dayops_v1(
    source: ExecutiveOfficeBriefV1 | Mapping[str, object],
    *,
    timezone_name: str,
    now: datetime,
) -> DayOpsPlanV1:
    """Create a bounded plan from trusted structure and untrusted field values."""

    if type(timezone_name) is not str or not timezone_name or len(timezone_name) > 80:
        raise DayOpsPlannerV1ContractError("IANA timezone is required")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DayOpsPlannerV1ContractError("IANA timezone is invalid") from exc
    if type(now) is not datetime or now.tzinfo is None:
        raise DayOpsPlannerV1ContractError("timezone-aware clock is required")
    utc_now = now.astimezone(timezone.utc)
    snapshot, raw_events, raw_messages = _snapshot(source)
    window_start = _aware(snapshot.get("window_start"), zone)
    window_end = _aware(snapshot.get("window_end"), zone)
    generated = _aware(snapshot.get("generated_at"), zone)
    if (
        window_start is None
        or window_end is None
        or generated is None
        or window_end <= window_start
    ):
        raise DayOpsPlannerV1ContractError("snapshot time window is invalid")

    events, invalid_events, events_truncated = _events(raw_events, zone)
    messages, invalid_messages, messages_truncated = _messages(raw_messages, zone)
    active = [
        item
        for item in events
        if not item.is_cancelled and item.end > window_start and item.start < window_end
    ]
    # A future snapshot clock never expands the accepted mail horizon.
    future_message_limit = utc_now + FUTURE_TOLERANCE
    future_messages = sum(item.received_at > future_message_limit for item in messages)
    messages = [item for item in messages if item.received_at <= future_message_limit]
    invalid_messages += future_messages
    timed = [item for item in active if not item.is_all_day]

    conflicts: list[CalendarConflictV1] = []
    for index, left in enumerate(timed):
        for right in timed[index + 1 :]:
            if right.start >= left.end:
                break
            overlap_start, overlap_end = (
                max(left.start, right.start),
                min(left.end, right.end),
            )
            if overlap_start < overlap_end:
                refs = tuple(sorted((left.ref, right.ref)))
                conflicts.append(
                    CalendarConflictV1(
                        refs, _iso(overlap_start, zone), _iso(overlap_end, zone)
                    )
                )
    ongoing = [item for item in timed if item.start < utc_now < item.end]
    ongoing_meetings = tuple(
        OngoingMeetingV1(
            item.ref,
            item.subject,
            _iso(item.start, zone),
            _iso(item.end, zone),
        )
        for item in ongoing[:MAX_OUTPUT_ITEMS]
    )
    future = [item for item in timed if item.start >= utc_now]
    next_event = future[0] if future else None
    next_meeting = None
    if next_event is not None:
        prep_start = max(utc_now, next_event.start - PREP_WINDOW)
        next_meeting = NextMeetingV1(
            next_event.ref,
            next_event.subject,
            _iso(next_event.start, zone),
            _iso(next_event.end, zone),
            _iso(prep_start, zone),
            _iso(next_event.start, zone),
        )

    important: list[ImportantUnreadV1] = []
    follow_ups: list[FollowUpCandidateV1] = []
    attention: list[AttentionItemV1] = []
    for message in messages:
        age_hours = max(0.0, (utc_now - message.received_at).total_seconds() / 3600)
        reasons: list[str] = []
        priority = 0
        if message.importance == "high":
            reasons.append("provider_importance_high")
            priority += 60
        if message.has_attachments:
            reasons.append("has_attachment")
            priority += 10
        if age_hours <= 24:
            reasons.append("received_within_24h")
            priority += 20
        if message.importance == "high":
            important.append(
                ImportantUnreadV1(
                    message.ref,
                    message.sender,
                    message.subject,
                    _iso(message.received_at, zone),
                    message.importance,
                    tuple(reasons),
                )
            )
            attention.append(
                AttentionItemV1(
                    "unread_message",
                    priority,
                    message.subject,
                    tuple(reasons),
                    (message.ref,),
                )
            )
        # V1 exposes no explicit reply/follow-up metadata.  Unread status,
        # importance, age, attachment, subject and sender are not substitutes.
    attention.extend(
        AttentionItemV1(
            "calendar_conflict",
            100,
            "Overlapping calendar items",
            conflict.reasons,
            conflict.event_refs,
        )
        for conflict in conflicts
    )
    attention.sort(key=lambda item: (-item.priority, item.kind, item.evidence_refs))

    busy = sorted(
        (
            (max(item.start, window_start), min(item.end, window_end))
            for item in timed
            if item.end > window_start and item.start < window_end
        ),
        key=lambda value: value[0],
    )
    merged: list[tuple[datetime, datetime]] = []
    for start, end in busy:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        elif end > merged[-1][1]:
            merged[-1] = (merged[-1][0], end)
    gaps: list[FocusGapV1] = []
    cursor = max(utc_now, window_start)
    for start, end in merged:
        if start - cursor >= MIN_FOCUS_GAP:
            gaps.append(
                FocusGapV1(
                    _iso(cursor, zone),
                    _iso(start, zone),
                    int((start - cursor).total_seconds() // 60),
                )
            )
        cursor = max(cursor, end)
    if window_end - cursor >= MIN_FOCUS_GAP:
        gaps.append(
            FocusGapV1(
                _iso(cursor, zone),
                _iso(window_end, zone),
                int((window_end - cursor).total_seconds() // 60),
            )
        )

    # Date mentions come only from structured calendar/message timestamps.
    date_mentions = tuple(
        DateMentionV1(
            item.ref,
            "calendar_start",
            item.start.astimezone(zone).date().isoformat(),
            "structured_event_timestamp",
        )
        for item in active[:MAX_OUTPUT_ITEMS]
    )
    freshness, age = _freshness(generated, utc_now)
    output_truncated = any(
        len(items) > MAX_OUTPUT_ITEMS
        for items in (
            attention,
            important,
            conflicts,
            ongoing,
            follow_ups,
            gaps,
            active,
        )
    )
    calendar_marker = snapshot.get("calendar_has_more")
    mail_marker = snapshot.get("mail_has_more")
    calendar_pagination = (
        "incomplete"
        if calendar_marker is True
        else "complete"
        if calendar_marker is False
        else "unknown"
    )
    mail_pagination = (
        "incomplete"
        if mail_marker is True
        else "complete"
        if mail_marker is False
        else "unknown"
    )
    coverage = CoverageDisclosureV1(
        timezone_name,
        _iso(generated, zone),
        freshness,
        age,
        _exact_bool(snapshot.get("calendar_has_more")),
        _exact_bool(snapshot.get("mail_has_more")),
        events_truncated or messages_truncated,
        output_truncated,
        invalid_events,
        invalid_messages,
        calendar_pagination=calendar_pagination,
        mail_pagination=mail_pagination,
        clock_skew_detected=freshness == "clock_skew",
        future_messages_excluded=future_messages,
        provider_content_untrusted=snapshot.get("provider_content_untrusted") is True,
    )
    payload: dict[str, object] = {
        "schema": SCHEMA,
        "read_only": True,
        "window_start": _iso(window_start, zone),
        "window_end": _iso(window_end, zone),
        "attention_items": [asdict(item) for item in attention[:MAX_OUTPUT_ITEMS]],
        "important_unread": [asdict(item) for item in important[:MAX_OUTPUT_ITEMS]],
        "calendar_conflicts": [asdict(item) for item in conflicts[:MAX_OUTPUT_ITEMS]],
        "next_meeting": None if next_meeting is None else asdict(next_meeting),
        "ongoing_meetings": [asdict(item) for item in ongoing_meetings],
        # V1 Graph read exposes no structured due-date field. Subjects are not
        # parsed to manufacture deadlines.
        "deadlines": [],
        "date_mentions": [asdict(item) for item in date_mentions],
        "follow_up_candidates": [
            asdict(item) for item in follow_ups[:MAX_OUTPUT_ITEMS]
        ],
        "focus_gaps": [asdict(item) for item in gaps[:MAX_OUTPUT_ITEMS]],
        "coverage": asdict(coverage),
        "mutation_authority": False,
    }
    return DayOpsPlanV1(
        SCHEMA,
        True,
        payload["window_start"],
        payload["window_end"],
        tuple(attention[:MAX_OUTPUT_ITEMS]),
        tuple(important[:MAX_OUTPUT_ITEMS]),
        tuple(conflicts[:MAX_OUTPUT_ITEMS]),
        next_meeting,
        ongoing_meetings,
        (),
        date_mentions,
        tuple(follow_ups[:MAX_OUTPUT_ITEMS]),
        tuple(gaps[:MAX_OUTPUT_ITEMS]),
        coverage,
        hashlib.sha256(_canonical(payload)).hexdigest(),
    )


__all__ = [
    "AttentionItemV1",
    "CalendarConflictV1",
    "CoverageDisclosureV1",
    "DateMentionV1",
    "DayOpsPlanV1",
    "DayOpsPlannerV1ContractError",
    "FocusGapV1",
    "FollowUpCandidateV1",
    "ImportantUnreadV1",
    "NextMeetingV1",
    "OngoingMeetingV1",
    "SCHEMA",
    "StructuredDeadlineV1",
    "plan_dayops_v1",
]
