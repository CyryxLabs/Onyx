"""Default-off Microsoft Graph calendar availability and exact-grant mutation.

This successor adds the first provider mutation of Phase 8, strictly per the
PRD order: deterministic conflict/availability computation over the accepted
read contract, and single-event creation gated by a signed one-shot grant that
binds the exact local draft digest. Every mutation produces a typed receipt
and is reconciled against provider state; an uncertain outcome can never be
retried before reconciliation. The module is exactly default-off, composes
only public frozen contracts and adds no send, invitation, cancellation,
shared-calendar or delete authority. Drafts with attendees are denied in V1
because invitations are external sends with a stricter gate.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Final, Mapping, Protocol

from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import (
    IDENTITY_ORIGIN,
    JsonHttpResponseV1,
    RefreshTokenVaultV1,
)
from core.phase8_microsoft_graph_read_v1 import (
    GRAPH_ORIGIN,
    CalendarEventV1,
    LocalEventDraftV1,
)

FEATURE_FLAG: Final = "ONYX_PHASE8_MICROSOFT_GRAPH_CALENDAR_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxMicrosoftGraphCalendar.v1"
WRITE_SCOPES: Final = ("Calendars.ReadWrite", "User.Read", "offline_access")
HTTP_TIMEOUT_SECONDS: Final = 30
MAX_HTTP_BYTES: Final = 1_048_576
ACCESS_EXPIRY_SKEW: Final = 90
MAX_GRANT_TTL_MS: Final = 600_000
MAX_EVENTS: Final = 500
ACCEPTED_LIVE_E2E_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase8-microsoft-graph-live-read-e2e-v1/"
        "manifest.json",
        "63e2ff3a059aeb1c856ca73ad80ac523aac99aa33162fc200ce0fee47dcdc104",
    ),
    (
        "docs/onyx/acceptance/VE-P8-MICROSOFT-GRAPH-LIVE-READ-E2E-V1-E6-001.md",
        "688b8dfea9a687474497a0aa82bce67fc443dee8f921d98ee5b455b2596739c5",
    ),
    (
        "docs/onyx/acceptance/"
        "VE-P8-MICROSOFT-GRAPH-LIVE-READ-E2E-V1-E6-001.manifest.json",
        "47ee0cc94d177f0cc52d02df6b5f975bc24894ea5d25deae7134c32979dc571e",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-LIVE-READ-E2E-V1-E6-001.sha256",
        "14fb863e7e8a935b9c9558b6bfedb0e78c0fcf0a075641b9b74c4bbf36d0ffde",
    ),
)
_READ_PATH = re.compile(r"^/v1\.0/me(?:/calendarView|/events/[^/]{1,1536})$")
_TOKEN_PATH = re.compile(
    r"^/(?:common|organizations|consumers|[0-9a-f-]{36})/oauth2/v2\.0/token$",
    re.IGNORECASE,
)
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_CONSTRUCTION_KEY = object()


class GraphCalendarV1Error(RuntimeError):
    pass


class GraphCalendarV1ContractError(ValueError):
    pass


class GraphCalendarV1Denied(PermissionError):
    pass


class GraphCalendarV1Uncertain(RuntimeError):
    """A mutation reached the provider boundary with an unknown outcome.

    The caller must reconcile against provider state before any retry; the
    consumed grant cannot be reused and a fresh grant is required after
    reconciliation proves the event absent.
    """


@dataclass(frozen=True, slots=True)
class GraphCalendarFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GraphCalendarV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GraphCalendarFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_LIVE_E2E_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GraphCalendarV1Denied(
                "accepted live read E2E evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GraphCalendarV1Denied("accepted live read E2E evidence drift")


def _utc(value: object, *, label: str) -> datetime:
    if type(value) is not str:
        raise GraphCalendarV1ContractError(f"{label} must be an ISO string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GraphCalendarV1ContractError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise GraphCalendarV1ContractError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _event_window(event: CalendarEventV1) -> tuple[datetime, datetime] | None:
    if type(event) is not CalendarEventV1:
        raise GraphCalendarV1ContractError("exact CalendarEventV1 required")
    if event.is_cancelled:
        return None
    if event.timezone.casefold() != "utc":
        raise GraphCalendarV1Denied(
            "non-UTC event timezone is unsupported in Calendar V1"
        )
    try:
        start = datetime.fromisoformat(event.start).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(event.end).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise GraphCalendarV1ContractError("event time is invalid") from exc
    if end <= start:
        raise GraphCalendarV1ContractError("event window is inverted")
    return start, end


def find_conflicts(
    events: tuple[CalendarEventV1, ...],
    *,
    window_start: str,
    window_end: str,
) -> tuple[CalendarEventV1, ...]:
    """Return every non-cancelled event overlapping the proposed UTC window."""

    if type(events) is not tuple or len(events) > MAX_EVENTS:
        raise GraphCalendarV1ContractError("event collection is invalid")
    start = _utc(window_start, label="window_start")
    end = _utc(window_end, label="window_end")
    if end <= start:
        raise GraphCalendarV1ContractError("proposed window is inverted")
    conflicts: list[CalendarEventV1] = []
    for event in events:
        window = _event_window(event)
        if window is None:
            continue
        event_start, event_end = window
        if event_start < end and start < event_end:
            conflicts.append(event)
    return tuple(conflicts)


def free_slots(
    events: tuple[CalendarEventV1, ...],
    *,
    window_start: str,
    window_end: str,
    duration_minutes: int,
    max_slots: int = 10,
) -> tuple[tuple[str, str], ...]:
    """Deterministic earliest-first free slots of the requested duration."""

    if (
        type(duration_minutes) is not int
        or not 5 <= duration_minutes <= 480
        or type(max_slots) is not int
        or not 1 <= max_slots <= 50
    ):
        raise GraphCalendarV1ContractError("slot parameters are invalid")
    if type(events) is not tuple or len(events) > MAX_EVENTS:
        raise GraphCalendarV1ContractError("event collection is invalid")
    start = _utc(window_start, label="window_start")
    end = _utc(window_end, label="window_end")
    if end <= start:
        raise GraphCalendarV1ContractError("availability window is inverted")
    busy = sorted(
        window
        for event in events
        if (window := _event_window(event)) is not None
    )
    duration = timedelta(minutes=duration_minutes)
    slots: list[tuple[str, str]] = []
    cursor = start
    for busy_start, busy_end in busy:
        while cursor + duration <= min(busy_start, end) and len(slots) < max_slots:
            slot_end = cursor + duration
            slots.append((cursor.isoformat(), slot_end.isoformat()))
            cursor = slot_end
        cursor = max(cursor, busy_end)
        if cursor >= end or len(slots) >= max_slots:
            break
    while cursor + duration <= end and len(slots) < max_slots:
        slot_end = cursor + duration
        slots.append((cursor.isoformat(), slot_end.isoformat()))
        cursor = slot_end
    return tuple(slots)


@dataclass(frozen=True, slots=True)
class EventMutationGrantV1:
    """Signed, expiring, one-shot authority for exactly one local draft.

    Key-management invariant: the ``integrity_key`` used to sign a grant MUST be
    scoped per (workspace_id, principal_id). The workspace and principal are
    bound cryptographically inside the length-framed HMAC payload, not checked
    against session state (the session is account-scoped by design). A key
    shared across workspaces or principals would make those fields
    informational only, so the caller is responsible for per-(workspace,
    principal) key derivation.
    """

    workspace_id: str
    principal_id: str
    account_id: str
    draft_sha256: str
    issued_at_ms: int
    expires_at_ms: int
    nonce: str
    signature: str

    def __post_init__(self) -> None:
        if (
            type(self.workspace_id) is not str
            or not self.workspace_id
            or type(self.principal_id) is not str
            or not self.principal_id
            or type(self.account_id) is not str
            or not self.account_id
            or type(self.draft_sha256) is not str
            or len(self.draft_sha256) != 64
            or type(self.issued_at_ms) is not int
            or type(self.expires_at_ms) is not int
            or self.issued_at_ms < 0
            or self.expires_at_ms <= self.issued_at_ms
            or self.expires_at_ms - self.issued_at_ms > MAX_GRANT_TTL_MS
            or type(self.nonce) is not str
            or not _NONCE.fullmatch(self.nonce)
            or type(self.signature) is not str
            or len(self.signature) != 64
        ):
            raise GraphCalendarV1ContractError("event mutation grant is invalid")


def _grant_payload(
    workspace_id: str,
    principal_id: str,
    account_id: str,
    draft_sha256: str,
    issued_at_ms: int,
    expires_at_ms: int,
    nonce: str,
) -> bytes:
    # Length-prefixed, domain-separated encoding: every field is framed by its
    # exact UTF-8 byte length so no combination of field contents can collide
    # with a different field split (a plain separator like NUL is ambiguous if
    # a field may itself contain the separator).
    fields = (
        SCHEMA,
        workspace_id,
        principal_id,
        account_id.casefold(),
        draft_sha256,
        str(issued_at_ms),
        str(expires_at_ms),
        nonce,
    )
    parts = bytearray()
    for field in fields:
        encoded = field.encode("utf-8")
        parts += len(encoded).to_bytes(4, "big")
        parts += encoded
    return bytes(parts)


def _validate_identity_field(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 256
        or any(ord(character) < 32 for character in value)
    ):
        raise GraphCalendarV1ContractError(f"{label} is invalid")
    return value


def issue_event_mutation_grant_v1(
    *,
    integrity_key: bytes,
    workspace_id: str,
    principal_id: str,
    account_id: str,
    draft: LocalEventDraftV1,
    nonce: str,
    now_ms: int,
    ttl_ms: int = 300_000,
) -> EventMutationGrantV1:
    if type(integrity_key) is not bytes or len(integrity_key) < 32:
        raise GraphCalendarV1ContractError("integrity key must be >= 32 bytes")
    if type(draft) is not LocalEventDraftV1:
        raise GraphCalendarV1ContractError("exact LocalEventDraftV1 required")
    if draft.attendees:
        raise GraphCalendarV1Denied(
            "attendee invitations are denied in Calendar V1"
        )
    if type(now_ms) is not int or now_ms < 0:
        raise GraphCalendarV1ContractError("current time is invalid")
    if type(ttl_ms) is not int or not 1_000 <= ttl_ms <= MAX_GRANT_TTL_MS:
        raise GraphCalendarV1ContractError("grant TTL is invalid")
    workspace_id = _validate_identity_field(workspace_id, label="workspace_id")
    principal_id = _validate_identity_field(principal_id, label="principal_id")
    account_id = _validate_identity_field(account_id, label="account_id")
    expires = now_ms + ttl_ms
    signature = hmac.new(
        integrity_key,
        _grant_payload(
            workspace_id,
            principal_id,
            account_id,
            draft.draft_sha256,
            now_ms,
            expires,
            nonce,
        ),
        hashlib.sha256,
    ).hexdigest()
    return EventMutationGrantV1(
        workspace_id,
        principal_id,
        account_id,
        draft.draft_sha256,
        now_ms,
        expires,
        nonce,
        signature,
    )


@dataclass(frozen=True, slots=True)
class EventCreationReceiptV1:
    event_id: str
    account_id: str
    draft_sha256: str
    provider_request_id: str | None
    created_at_epoch_s: int
    reconciled: bool
    web_link: str


class GraphMutationHttpV1(Protocol):
    def post_form(
        self,
        *,
        url: str,
        fields: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1: ...

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1: ...

    def get_json(
        self,
        *,
        url: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1: ...


def _strict_json(data: bytes) -> dict[str, object]:
    if type(data) is not bytes or len(data) > MAX_HTTP_BYTES:
        raise GraphCalendarV1Denied("HTTP payload size is invalid")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise GraphCalendarV1Denied("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GraphCalendarV1Denied("HTTP JSON is invalid") from exc
    if type(value) is not dict:
        raise GraphCalendarV1Denied("HTTP JSON object required")
    return value


def _headers(value: object) -> tuple[tuple[str, str], ...]:
    items = getattr(value, "items", None)
    if not callable(items):
        return ()
    return tuple(
        (name, item)
        for name, item in items()
        if type(name) is str and type(item) is str
    )


class StdlibGraphMutationHttpV1:
    """Route-pinned HTTPS client: identity POST, events POST, calendar GET."""

    __slots__ = ("_opener",)

    def __init__(self) -> None:
        context = ssl.create_default_context()

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        self._opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=context)
        )

    def _open(self, request: urllib.request.Request) -> JsonHttpResponseV1:
        try:
            with self._opener.open(
                request, timeout=HTTP_TIMEOUT_SECONDS
            ) as response:
                data = response.read(MAX_HTTP_BYTES + 1)
                if len(data) > MAX_HTTP_BYTES:
                    raise GraphCalendarV1Denied("HTTP response exceeded size limit")
                return JsonHttpResponseV1(
                    int(response.status), _strict_json(data), _headers(response.headers)
                )
        except urllib.error.HTTPError as exc:
            data = exc.read(MAX_HTTP_BYTES + 1)
            if len(data) > MAX_HTTP_BYTES:
                raise GraphCalendarV1Denied("HTTP error exceeded size limit") from exc
            return JsonHttpResponseV1(
                int(exc.code), _strict_json(data), _headers(exc.headers)
            )
        except GraphCalendarV1Denied:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise GraphCalendarV1Uncertain(
                "provider outcome unknown; reconcile before retry"
            ) from exc

    def post_form(
        self,
        *,
        url: str,
        fields: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1:
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "login.microsoftonline.com"
            or not _TOKEN_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphCalendarV1Denied("identity POST route is invalid")
        # URL is pinned above to HTTPS and the exact Microsoft identity route.
        request = urllib.request.Request(  # noqa: S310
            url,
            data=urllib.parse.urlencode(fields).encode("ascii"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "CyryxLabs-Onyx/1",
            },
            method="POST",
        )
        try:
            return self._open(request)
        except GraphCalendarV1Uncertain as exc:
            raise GraphCalendarV1Error("Microsoft identity request failed") from exc

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1:
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or parsed.path != "/v1.0/me/events"
            or parsed.query
            or parsed.fragment
            or type(payload) is not dict
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphCalendarV1Denied("Graph mutation route is invalid")
        outbound = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "CyryxLabs-Onyx/1",
        }
        for name, value in headers:
            outbound[name] = value
        # URL is pinned above to HTTPS and the accepted Microsoft Graph route.
        request = urllib.request.Request(  # noqa: S310
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=outbound,
            method="POST",
        )
        return self._open(request)

    def get_json(
        self,
        *,
        url: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1:
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or not _READ_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphCalendarV1Denied("Graph read route is invalid")
        encoded = urllib.parse.urlencode(query)
        target = f"{url}?{encoded}" if encoded else url
        outbound = {"Accept": "application/json", "User-Agent": "CyryxLabs-Onyx/1"}
        for name, value in headers:
            outbound[name] = value
        # Base URL is pinned above; the query is encoded from structured pairs.
        request = urllib.request.Request(  # noqa: S310
            target, headers=outbound, method="GET"
        )
        try:
            return self._open(request)
        except GraphCalendarV1Uncertain as exc:
            raise GraphCalendarV1Error("Microsoft Graph read failed") from exc


def _text(value: object, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise GraphCalendarV1Denied("provider text contract drift")
    return value


class MicrosoftGraphCalendarSessionV1:
    """Write-scope session with exact-grant, receipted, reconciled creation."""

    __slots__ = (
        "_access_expires_at",
        "_access_token",
        "_clock_epoch_s",
        "_clock_ms",
        "_http",
        "_integrity_key",
        "_onboarding",
        "_used_nonces",
        "_vault",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        onboarding: MicrosoftGraphLiveOnboardingV1,
        http: GraphMutationHttpV1,
        vault: RefreshTokenVaultV1,
        integrity_key: bytes,
        clock_ms: Callable[[], int],
        clock_epoch_s: Callable[[], int],
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GraphCalendarV1ContractError(
                "use create_microsoft_graph_calendar_v1"
            )
        self._onboarding = onboarding
        self._http = http
        self._vault = vault
        self._integrity_key = integrity_key
        self._clock_ms = clock_ms
        self._clock_epoch_s = clock_epoch_s
        self._access_token: str | None = None
        self._access_expires_at: int | None = None
        self._used_nonces: set[str] = set()

    def _token_url(self) -> str:
        tenant = urllib.parse.quote(self._onboarding.tenant_id, safe="")
        return f"{IDENTITY_ORIGIN}/{tenant}/oauth2/v2.0/token"

    def _write_token(self) -> str:
        now = self._clock_epoch_s()
        if type(now) is not int:
            raise GraphCalendarV1ContractError("clock result is invalid")
        if (
            self._access_token is not None
            and self._access_expires_at is not None
            and now + ACCESS_EXPIRY_SKEW < self._access_expires_at
        ):
            return self._access_token
        refresh = self._vault.get_refresh_token()
        if refresh is None:
            raise GraphCalendarV1Denied("Microsoft sign-in is required")
        response = self._http.post_form(
            url=self._token_url(),
            fields=(
                ("client_id", self._onboarding.client_id),
                ("grant_type", "refresh_token"),
                ("refresh_token", refresh),
                ("scope", " ".join(sorted(WRITE_SCOPES, key=str.casefold))),
            ),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not JsonHttpResponseV1 or response.status_code != 200:
            raise GraphCalendarV1Error("Microsoft write-scope refresh failed")
        token_type = _text(response.payload.get("token_type"), 30)
        access = _text(response.payload.get("access_token"), 16_384)
        scope_text = _text(response.payload.get("scope"), 2_000)
        expires_in = response.payload.get("expires_in")
        if type(expires_in) is not int or not 60 <= expires_in <= 86_400:
            raise GraphCalendarV1Denied("access expiry contract drift")
        granted = frozenset(scope_text.split())
        if token_type.casefold() != "bearer" or "Calendars.ReadWrite" not in granted:
            raise GraphCalendarV1Denied("write scope was not granted")
        rotated = response.payload.get("refresh_token")
        if type(rotated) is str and rotated:
            self._vault.set_refresh_token(rotated)
        self._access_token = access
        self._access_expires_at = now + expires_in
        return access

    def _validate_grant(
        self, grant: EventMutationGrantV1, draft: LocalEventDraftV1
    ) -> None:
        if type(grant) is not EventMutationGrantV1:
            raise GraphCalendarV1ContractError("exact EventMutationGrantV1 required")
        if type(draft) is not LocalEventDraftV1:
            raise GraphCalendarV1ContractError("exact LocalEventDraftV1 required")
        now_ms = self._clock_ms()
        if type(now_ms) is not int:
            raise GraphCalendarV1ContractError("clock result is invalid")
        expected = hmac.new(
            self._integrity_key,
            _grant_payload(
                grant.workspace_id,
                grant.principal_id,
                grant.account_id,
                grant.draft_sha256,
                grant.issued_at_ms,
                grant.expires_at_ms,
                grant.nonce,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, grant.signature):
            raise GraphCalendarV1Denied("event mutation grant signature is invalid")
        if grant.account_id.casefold() != self._onboarding.account_id.casefold():
            raise GraphCalendarV1Denied("grant account does not match session")
        if not hmac.compare_digest(grant.draft_sha256, draft.draft_sha256):
            raise GraphCalendarV1Denied("grant does not cover this exact draft")
        if now_ms >= grant.expires_at_ms:
            raise GraphCalendarV1Denied("event mutation grant expired")
        if grant.nonce in self._used_nonces:
            raise GraphCalendarV1Denied("event mutation grant already used")
        if draft.attendees:
            raise GraphCalendarV1Denied(
                "attendee invitations are denied in Calendar V1"
            )
        if draft.mutation_authority is not False:
            raise GraphCalendarV1ContractError("draft mutation_authority drift")

    def create_event(
        self,
        *,
        draft: LocalEventDraftV1,
        grant: EventMutationGrantV1,
    ) -> EventCreationReceiptV1:
        self._validate_grant(grant, draft)
        access = self._write_token()
        payload: dict[str, object] = {
            "subject": draft.subject,
            "start": {"dateTime": draft.start, "timeZone": draft.timezone},
            "end": {"dateTime": draft.end, "timeZone": draft.timezone},
            "body": {"contentType": "text", "content": draft.body_text},
        }
        if draft.location:
            payload["location"] = {"displayName": draft.location}
        self._used_nonces.add(grant.nonce)
        try:
            response = self._http.post_json(
                url=f"{GRAPH_ORIGIN}/v1.0/me/events",
                payload=payload,
                headers=(("Authorization", f"Bearer {access}"),),
                timeout_seconds=HTTP_TIMEOUT_SECONDS,
            )
        except GraphCalendarV1Uncertain:
            raise
        if response.status_code == 429:
            raise GraphCalendarV1Error(
                "provider throttled the mutation; issue a fresh grant and retry "
                "after the provider delay"
            )
        if response.status_code != 201:
            raise GraphCalendarV1Error("Microsoft event creation was rejected")
        event_id = _text(response.payload.get("id"), 512)
        request_id = None
        for name, value in response.headers:
            if name.casefold() == "request-id":
                request_id = value
        reconciled = self._reconcile(event_id, draft, access)
        return EventCreationReceiptV1(
            event_id,
            self._onboarding.account_id,
            draft.draft_sha256,
            request_id,
            self._clock_epoch_s(),
            reconciled,
            _text(response.payload.get("webLink", "https://outlook.office.com"), 2_048),
        )

    def _reconcile(
        self, event_id: str, draft: LocalEventDraftV1, access: str
    ) -> bool:
        quoted = urllib.parse.quote(event_id, safe="")
        response = self._http.get_json(
            url=f"{GRAPH_ORIGIN}/v1.0/me/events/{quoted}",
            query=(("$select", "id,subject,start,end"),),
            headers=(("Authorization", f"Bearer {access}"),),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            return False
        observed_subject = response.payload.get("subject")
        start = response.payload.get("start")
        end = response.payload.get("end")
        if type(start) is not dict or type(end) is not dict:
            return False

        def _instant(value: object) -> datetime | None:
            if type(value) is not str:
                return None
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

        return (
            observed_subject == draft.subject
            and _instant(start.get("dateTime")) == _instant(draft.start)
            and _instant(end.get("dateTime")) == _instant(draft.end)
        )

    def reconcile_uncertain(
        self,
        *,
        draft: LocalEventDraftV1,
    ) -> EventCreationReceiptV1 | None:
        """Search provider state for an uncertain creation before any retry."""

        if type(draft) is not LocalEventDraftV1:
            raise GraphCalendarV1ContractError("exact LocalEventDraftV1 required")
        access = self._write_token()
        response = self._http.get_json(
            url=f"{GRAPH_ORIGIN}/v1.0/me/calendarView",
            query=(
                ("startDateTime", draft.start),
                ("endDateTime", draft.end),
                ("$select", "id,subject,start,end,webLink"),
                ("$top", "50"),
            ),
            headers=(
                ("Authorization", f"Bearer {access}"),
                ("Prefer", 'outlook.timezone="UTC"'),
            ),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise GraphCalendarV1Error("uncertain-outcome reconciliation failed")
        values = response.payload.get("value")
        if type(values) is not list:
            raise GraphCalendarV1Denied("reconciliation collection drift")
        for item in values:
            if type(item) is not dict or item.get("subject") != draft.subject:
                continue
            event_id = item.get("id")
            if type(event_id) is not str or not event_id:
                continue
            if self._reconcile(event_id, draft, access):
                return EventCreationReceiptV1(
                    event_id,
                    self._onboarding.account_id,
                    draft.draft_sha256,
                    None,
                    self._clock_epoch_s(),
                    True,
                    _text(item.get("webLink", "https://outlook.office.com"), 2_048),
                )
        return None


def create_microsoft_graph_calendar_v1(
    *,
    gate: GraphCalendarFeatureGateV1 | None = None,
    onboarding: MicrosoftGraphLiveOnboardingV1 | None = None,
    http: GraphMutationHttpV1 | None = None,
    vault: RefreshTokenVaultV1 | None = None,
    integrity_key: bytes | None = None,
    clock_ms: Callable[[], int] | None = None,
    clock_epoch_s: Callable[[], int] | None = None,
    project_root: Path | str | None = None,
) -> MicrosoftGraphCalendarSessionV1 | None:
    selected = GraphCalendarFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not GraphCalendarFeatureGateV1:
        raise GraphCalendarV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    chosen = (
        MicrosoftGraphLiveOnboardingV1.from_environ()
        if onboarding is None
        else onboarding
    )
    if type(chosen) is not MicrosoftGraphLiveOnboardingV1:
        raise GraphCalendarV1ContractError("exact onboarding identity required")
    if (
        vault is None
        or integrity_key is None
        or clock_ms is None
        or clock_epoch_s is None
    ):
        raise GraphCalendarV1ContractError("enabled session requires complete bindings")
    if type(integrity_key) is not bytes or len(integrity_key) < 32:
        raise GraphCalendarV1ContractError("integrity key must be >= 32 bytes")
    if not callable(clock_ms) or not callable(clock_epoch_s):
        raise GraphCalendarV1ContractError("exact clocks are required")
    selected_http = StdlibGraphMutationHttpV1() if http is None else http
    if (
        not hasattr(selected_http, "post_form")
        or not hasattr(selected_http, "post_json")
        or not hasattr(selected_http, "get_json")
        or not hasattr(vault, "get_refresh_token")
    ):
        raise GraphCalendarV1ContractError("mutation transport or vault is invalid")
    return MicrosoftGraphCalendarSessionV1(
        construction_key=_CONSTRUCTION_KEY,
        onboarding=chosen,
        http=selected_http,
        vault=vault,
        integrity_key=integrity_key,
        clock_ms=clock_ms,
        clock_epoch_s=clock_epoch_s,
    )


__all__ = [
    "ACCEPTED_LIVE_E2E_ROOTS",
    "EventCreationReceiptV1",
    "EventMutationGrantV1",
    "FEATURE_FLAG",
    "GraphCalendarFeatureGateV1",
    "GraphCalendarV1ContractError",
    "GraphCalendarV1Denied",
    "GraphCalendarV1Error",
    "GraphCalendarV1Uncertain",
    "MicrosoftGraphCalendarSessionV1",
    "StdlibGraphMutationHttpV1",
    "WRITE_SCOPES",
    "create_microsoft_graph_calendar_v1",
    "find_conflicts",
    "free_slots",
    "issue_event_mutation_grant_v1",
]
