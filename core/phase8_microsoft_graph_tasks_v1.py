"""Default-off Microsoft Graph To Do tasks and local notification routing.

This successor adds the Phase 8 tasks-and-notifications slice:

1. A pure, deterministic **notification router** — no provider, no network. It
   routes typed notification items by urgency, quiet hours, workspace policy
   and device into deliver / defer-to-morning / suppress decisions with an
   explicit reason each.
2. A **To Do task create** mutation gated by an HMAC-signed, expiring,
   one-shot grant bound to the exact local task-draft content digest, list and
   account; consumed through an injected durable nonce ledger before any
   provider mutation; a typed receipt and read-back reconciliation; and
   uncertain-outcome reconcile-before-retry. It reuses the corrected write-token
   pattern (best-effort refresh rotation).

The module is exactly default-off, composes only public frozen contracts and
adds no task update/delete/complete, list mutation, calendar/mail authority or
runtime wiring.
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
from core.phase8_microsoft_graph_read_v1 import GRAPH_ORIGIN

FEATURE_FLAG: Final = "ONYX_PHASE8_MICROSOFT_GRAPH_TASKS_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxMicrosoftGraphTasks.v1"
WRITE_SCOPES: Final = ("Tasks.ReadWrite", "User.Read", "offline_access")
HTTP_TIMEOUT_SECONDS: Final = 30
MAX_HTTP_BYTES: Final = 1_048_576
ACCESS_EXPIRY_SKEW: Final = 90
MAX_GRANT_TTL_MS: Final = 600_000
MAX_NOTIFICATIONS: Final = 500
URGENCY_ORDER: Final = ("low", "normal", "high", "urgent")
NOTIFICATION_SOURCES: Final = frozenset(
    {"calendar", "mail", "task", "deadline", "system"}
)
ROUTE_DECISIONS: Final = frozenset({"deliver", "defer", "suppress"})
ACCEPTED_MAIL_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase8-microsoft-graph-mail-v1/manifest.json",
        "98f9cc7c75cf496275ab326af352d3332cd8f604b702c8047f405df264034acf",
    ),
    (
        "docs/onyx/acceptance/VE-P8-MICROSOFT-GRAPH-MAIL-V1-E6-001.md",
        "3d6274a2705311dff80542c5ab986b2a15354b7707f96620cee668a12598ed19",
    ),
    (
        "docs/onyx/acceptance/VE-P8-MICROSOFT-GRAPH-MAIL-V1-E6-001.manifest.json",
        "8d13864bdda32113b13f676757d866c1d37a4187019c0087fe342cb59bffadaf",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-MAIL-V1-E6-001.sha256",
        "9d955b6d6cef40e20b1801a3060951b3278c335706ce83f24a608451e778da7e",
    ),
)
_TOKEN_PATH = re.compile(
    r"^/(?:common|organizations|consumers|[0-9a-f-]{36})/oauth2/v2\.0/token$",
    re.IGNORECASE,
)
_TASKS_PATH = re.compile(r"^/v1\.0/me/todo/lists/[^/]{1,256}/tasks$")
_TASK_ITEM_PATH = re.compile(
    r"^/v1\.0/me/todo/lists/[^/]{1,256}/tasks/[^/]{1,256}$"
)
_LIST_ID = re.compile(r"^[A-Za-z0-9._=+\-]{1,256}$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_CONSTRUCTION_KEY = object()


class GraphTasksV1Error(RuntimeError):
    pass


class GraphTasksV1ContractError(ValueError):
    pass


class GraphTasksV1Denied(PermissionError):
    pass


class GraphTasksV1Uncertain(RuntimeError):
    """A task create reached the provider boundary with an unknown outcome."""


# ── Notification router (pure, no provider) ────────────────────────────────


@dataclass(frozen=True, slots=True)
class NotificationItemV1:
    notification_id: str
    source: str
    urgency: str
    workspace_id: str
    device: str
    created_epoch_s: int
    summary: str

    def __post_init__(self) -> None:
        if (
            type(self.notification_id) is not str
            or not self.notification_id
            or self.source not in NOTIFICATION_SOURCES
            or self.urgency not in URGENCY_ORDER
            or type(self.workspace_id) is not str
            or not self.workspace_id
            or type(self.device) is not str
            or not self.device
            or type(self.created_epoch_s) is not int
            or self.created_epoch_s < 0
            or type(self.summary) is not str
            or not self.summary
            or len(self.summary) > 300
            or any(ord(character) < 32 for character in self.summary)
        ):
            raise GraphTasksV1ContractError("notification item is invalid")


@dataclass(frozen=True, slots=True)
class QuietHoursPolicyV1:
    start_hour_utc: int
    end_hour_utc: int
    min_urgency_in_quiet: str
    allowed_workspaces: tuple[str, ...]
    allowed_devices: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.start_hour_utc) is not int
            or not 0 <= self.start_hour_utc <= 23
            or type(self.end_hour_utc) is not int
            or not 0 <= self.end_hour_utc <= 23
            or self.min_urgency_in_quiet not in URGENCY_ORDER
            or type(self.allowed_workspaces) is not tuple
            or not self.allowed_workspaces
            or type(self.allowed_devices) is not tuple
            or not self.allowed_devices
            or any(type(item) is not str or not item for item in self.allowed_workspaces)
            or any(type(item) is not str or not item for item in self.allowed_devices)
        ):
            raise GraphTasksV1ContractError("quiet-hours policy is invalid")

    def in_quiet_hours(self, hour_utc: int) -> bool:
        if type(hour_utc) is not int or not 0 <= hour_utc <= 23:
            raise GraphTasksV1ContractError("hour is invalid")
        if self.start_hour_utc == self.end_hour_utc:
            return False
        if self.start_hour_utc < self.end_hour_utc:
            return self.start_hour_utc <= hour_utc < self.end_hour_utc
        return hour_utc >= self.start_hour_utc or hour_utc < self.end_hour_utc


@dataclass(frozen=True, slots=True)
class NotificationDecisionV1:
    notification_id: str
    decision: str
    reason: str

    def __post_init__(self) -> None:
        if (
            type(self.notification_id) is not str
            or not self.notification_id
            or self.decision not in ROUTE_DECISIONS
            or type(self.reason) is not str
            or not self.reason
        ):
            raise GraphTasksV1ContractError("notification decision is invalid")


def route_notifications(
    items: tuple[NotificationItemV1, ...],
    *,
    policy: QuietHoursPolicyV1,
    now_hour_utc: int,
) -> tuple[NotificationDecisionV1, ...]:
    """Deterministically route items into deliver/defer/suppress decisions.

    Rules, in order:
    1. An item whose workspace or device is not allowed by the policy is
       suppressed.
    2. Outside quiet hours, every allowed item is delivered.
    3. Inside quiet hours, an item at or above ``min_urgency_in_quiet`` is
       delivered; anything below is deferred to the next non-quiet window.
    """

    if type(items) is not tuple or len(items) > MAX_NOTIFICATIONS:
        raise GraphTasksV1ContractError("notification collection is invalid")
    if type(policy) is not QuietHoursPolicyV1:
        raise GraphTasksV1ContractError("exact QuietHoursPolicyV1 required")
    quiet = policy.in_quiet_hours(now_hour_utc)
    threshold = URGENCY_ORDER.index(policy.min_urgency_in_quiet)
    allowed_workspaces = frozenset(policy.allowed_workspaces)
    allowed_devices = frozenset(policy.allowed_devices)
    decisions: list[NotificationDecisionV1] = []
    for item in items:
        if type(item) is not NotificationItemV1:
            raise GraphTasksV1ContractError("exact NotificationItemV1 required")
        if item.workspace_id not in allowed_workspaces:
            decisions.append(
                NotificationDecisionV1(
                    item.notification_id, "suppress", "workspace not permitted"
                )
            )
            continue
        if item.device not in allowed_devices:
            decisions.append(
                NotificationDecisionV1(
                    item.notification_id, "suppress", "device not permitted"
                )
            )
            continue
        if not quiet:
            decisions.append(
                NotificationDecisionV1(
                    item.notification_id, "deliver", "outside quiet hours"
                )
            )
            continue
        if URGENCY_ORDER.index(item.urgency) >= threshold:
            decisions.append(
                NotificationDecisionV1(
                    item.notification_id,
                    "deliver",
                    f"urgency {item.urgency} clears quiet-hours threshold",
                )
            )
        else:
            decisions.append(
                NotificationDecisionV1(
                    item.notification_id,
                    "defer",
                    "below quiet-hours urgency threshold",
                )
            )
    return tuple(decisions)


# ── To Do task create (provider mutation) ──────────────────────────────────


@dataclass(frozen=True, slots=True)
class GraphTasksFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GraphTasksV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GraphTasksFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_MAIL_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GraphTasksV1Denied("accepted Mail V1 evidence unavailable") from exc
        if not hmac.compare_digest(actual, expected):
            raise GraphTasksV1Denied("accepted Mail V1 evidence drift")


def _validate_identity_field(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 256
        or any(ord(character) < 32 for character in value)
    ):
        raise GraphTasksV1ContractError(f"{label} is invalid")
    return value


def _text(value: object, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\t\n" for character in value)
    ):
        raise GraphTasksV1Denied("provider text contract drift")
    return value


@dataclass(frozen=True, slots=True)
class LocalTaskDraftV1:
    list_id: str
    title: str
    body_text: str
    importance: str
    due_date: str | None
    draft_sha256: str
    mutation_authority: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.list_id) is not str
            or not _LIST_ID.fullmatch(self.list_id)
            or type(self.title) is not str
            or not self.title.strip()
            or len(self.title) > 1_000
            or type(self.body_text) is not str
            or len(self.body_text) > 50_000
            or self.importance not in {"low", "normal", "high"}
            or (
                self.due_date is not None
                and (
                    type(self.due_date) is not str
                    or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.due_date)
                )
            )
            or type(self.draft_sha256) is not str
            or len(self.draft_sha256) != 64
            or self.mutation_authority is not False
        ):
            raise GraphTasksV1ContractError("local task draft is invalid")


def _expected_task_digest(
    list_id: str,
    title: str,
    body_text: str,
    importance: str,
    due_date: str | None,
) -> str:
    canonical = json.dumps(
        {
            "kind": "task",
            "list_id": list_id,
            "title": title,
            "body_text": body_text,
            "importance": importance,
            "due_date": due_date,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def build_task_draft_v1(
    *,
    list_id: str,
    title: str,
    body_text: str = "",
    importance: str = "normal",
    due_date: str | None = None,
) -> LocalTaskDraftV1:
    normalized_title = title.strip() if type(title) is str else title
    digest = _expected_task_digest(
        list_id, normalized_title, body_text, importance, due_date
    )
    return LocalTaskDraftV1(
        list_id, normalized_title, body_text, importance, due_date, digest
    )


@dataclass(frozen=True, slots=True)
class TaskCreateGrantV1:
    workspace_id: str
    principal_id: str
    account_id: str
    draft_sha256: str
    list_id: str
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
            or type(self.list_id) is not str
            or not _LIST_ID.fullmatch(self.list_id)
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
            raise GraphTasksV1ContractError("task create grant is invalid")


def _grant_payload(
    workspace_id: str,
    principal_id: str,
    account_id: str,
    draft_sha256: str,
    list_id: str,
    issued_at_ms: int,
    expires_at_ms: int,
    nonce: str,
) -> bytes:
    fields = (
        SCHEMA,
        workspace_id,
        principal_id,
        account_id.casefold(),
        draft_sha256,
        list_id,
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


def issue_task_create_grant_v1(
    *,
    integrity_key: bytes,
    workspace_id: str,
    principal_id: str,
    account_id: str,
    draft: LocalTaskDraftV1,
    nonce: str,
    now_ms: int,
    ttl_ms: int = 300_000,
) -> TaskCreateGrantV1:
    if type(integrity_key) is not bytes or len(integrity_key) < 32:
        raise GraphTasksV1ContractError("integrity key must be >= 32 bytes")
    if type(draft) is not LocalTaskDraftV1:
        raise GraphTasksV1ContractError("exact LocalTaskDraftV1 required")
    if type(now_ms) is not int or now_ms < 0:
        raise GraphTasksV1ContractError("current time is invalid")
    if type(ttl_ms) is not int or not 1_000 <= ttl_ms <= MAX_GRANT_TTL_MS:
        raise GraphTasksV1ContractError("grant TTL is invalid")
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
            draft.list_id,
            now_ms,
            expires,
            nonce,
        ),
        hashlib.sha256,
    ).hexdigest()
    return TaskCreateGrantV1(
        workspace_id,
        principal_id,
        account_id,
        draft.draft_sha256,
        draft.list_id,
        now_ms,
        expires,
        nonce,
        signature,
    )


@dataclass(frozen=True, slots=True)
class TaskCreateReceiptV1:
    task_id: str
    list_id: str
    account_id: str
    draft_sha256: str
    provider_request_id: str | None
    created_at_epoch_s: int
    reconciled: bool


class NonceLedgerV1(Protocol):
    def consume(self, nonce: str) -> bool: ...


class InMemoryNonceLedgerV1:
    """Per-instance one-shot nonce ledger.

    Durability invariant: cross-session, cross-restart one-shot protection
    requires a durable, atomic ledger; this in-memory default protects only
    within a single live object.
    """

    __slots__ = ("_used",)

    def __init__(self) -> None:
        self._used: set[str] = set()

    def consume(self, nonce: str) -> bool:
        if type(nonce) is not str or not nonce:
            raise GraphTasksV1ContractError("nonce is invalid")
        if nonce in self._used:
            return False
        self._used.add(nonce)
        return True


class GraphTasksHttpV1(Protocol):
    def post_form(
        self, *, url: str, fields: tuple[tuple[str, str], ...], timeout_seconds: int
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
        raise GraphTasksV1Denied("HTTP payload size is invalid")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise GraphTasksV1Denied("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GraphTasksV1Denied("HTTP JSON is invalid") from exc
    if type(value) is not dict:
        raise GraphTasksV1Denied("HTTP JSON object required")
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


class StdlibGraphTasksHttpV1:
    """Route-pinned HTTPS client: identity POST, tasks POST, task GET."""

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
                    raise GraphTasksV1Denied("HTTP response exceeded size limit")
                body = _strict_json(data) if data.strip() else {}
                return JsonHttpResponseV1(
                    int(response.status), body, _headers(response.headers)
                )
        except urllib.error.HTTPError as exc:
            data = exc.read(MAX_HTTP_BYTES + 1)
            if len(data) > MAX_HTTP_BYTES:
                raise GraphTasksV1Denied("HTTP error exceeded size limit") from exc
            body = _strict_json(data) if data.strip() else {}
            return JsonHttpResponseV1(int(exc.code), body, _headers(exc.headers))
        except GraphTasksV1Denied:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise GraphTasksV1Uncertain(
                "provider outcome unknown; reconcile before retry"
            ) from exc

    def post_form(self, *, url, fields, timeout_seconds):
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "login.microsoftonline.com"
            or not _TOKEN_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphTasksV1Denied("identity POST route is invalid")
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
        except GraphTasksV1Uncertain as exc:
            raise GraphTasksV1Error("Microsoft identity request failed") from exc

    def post_json(self, *, url, payload, headers, timeout_seconds):
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or not _TASKS_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or type(payload) is not dict
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphTasksV1Denied("Graph task create route is invalid")
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

    def get_json(self, *, url, query, headers, timeout_seconds):
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or not _TASK_ITEM_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphTasksV1Denied("Graph task read route is invalid")
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
        except GraphTasksV1Uncertain as exc:
            raise GraphTasksV1Error("Microsoft task read failed") from exc


class MicrosoftGraphTasksSessionV1:
    """Write-scope session with exact-grant, receipted, reconciled task create."""

    __slots__ = (
        "_access_expires_at",
        "_access_token",
        "_clock_epoch_s",
        "_clock_ms",
        "_http",
        "_integrity_key",
        "_nonce_ledger",
        "_onboarding",
        "_vault",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        onboarding: MicrosoftGraphLiveOnboardingV1,
        http: GraphTasksHttpV1,
        vault: RefreshTokenVaultV1,
        integrity_key: bytes,
        nonce_ledger: NonceLedgerV1,
        clock_ms: Callable[[], int],
        clock_epoch_s: Callable[[], int],
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GraphTasksV1ContractError("use create_microsoft_graph_tasks_v1")
        self._onboarding = onboarding
        self._http = http
        self._vault = vault
        self._integrity_key = integrity_key
        self._nonce_ledger = nonce_ledger
        self._clock_ms = clock_ms
        self._clock_epoch_s = clock_epoch_s
        self._access_token: str | None = None
        self._access_expires_at: int | None = None

    def _token_url(self) -> str:
        tenant = urllib.parse.quote(self._onboarding.tenant_id, safe="")
        return f"{IDENTITY_ORIGIN}/{tenant}/oauth2/v2.0/token"

    def _write_token(self) -> str:
        now = self._clock_epoch_s()
        if type(now) is not int:
            raise GraphTasksV1ContractError("clock result is invalid")
        if (
            self._access_token is not None
            and self._access_expires_at is not None
            and now + ACCESS_EXPIRY_SKEW < self._access_expires_at
        ):
            return self._access_token
        refresh = self._vault.get_refresh_token()
        if refresh is None:
            raise GraphTasksV1Denied("Microsoft sign-in is required")
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
            raise GraphTasksV1Error("Microsoft write-scope refresh failed")
        token_type = _text(response.payload.get("token_type"), 30)
        access = _text(response.payload.get("access_token"), 16_384)
        scope_text = _text(response.payload.get("scope"), 2_000)
        expires_in = response.payload.get("expires_in")
        if type(expires_in) is not int or not 60 <= expires_in <= 86_400:
            raise GraphTasksV1Denied("access expiry contract drift")
        granted = frozenset(scope_text.split())
        if token_type.casefold() != "bearer" or "Tasks.ReadWrite" not in granted:
            raise GraphTasksV1Denied("tasks write scope was not granted")
        rotated = response.payload.get("refresh_token")
        if type(rotated) is str and rotated:
            try:
                self._vault.set_refresh_token(rotated)
            except (PermissionError, ValueError):
                pass
        self._access_token = access
        self._access_expires_at = now + expires_in
        return access

    def _validate_grant(
        self, grant: TaskCreateGrantV1, draft: LocalTaskDraftV1
    ) -> None:
        if type(grant) is not TaskCreateGrantV1:
            raise GraphTasksV1ContractError("exact TaskCreateGrantV1 required")
        if type(draft) is not LocalTaskDraftV1:
            raise GraphTasksV1ContractError("exact LocalTaskDraftV1 required")
        now_ms = self._clock_ms()
        if type(now_ms) is not int:
            raise GraphTasksV1ContractError("clock result is invalid")
        expected = hmac.new(
            self._integrity_key,
            _grant_payload(
                grant.workspace_id,
                grant.principal_id,
                grant.account_id,
                grant.draft_sha256,
                grant.list_id,
                grant.issued_at_ms,
                grant.expires_at_ms,
                grant.nonce,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, grant.signature):
            raise GraphTasksV1Denied("task create grant signature is invalid")
        if grant.account_id.casefold() != self._onboarding.account_id.casefold():
            raise GraphTasksV1Denied("grant account does not match session")
        if not hmac.compare_digest(grant.draft_sha256, draft.draft_sha256):
            raise GraphTasksV1Denied("grant does not cover this exact draft")
        expected_digest = _expected_task_digest(
            draft.list_id, draft.title, draft.body_text, draft.importance, draft.due_date
        )
        if not hmac.compare_digest(expected_digest, draft.draft_sha256):
            raise GraphTasksV1Denied("draft content does not match its digest")
        if not hmac.compare_digest(grant.list_id, draft.list_id):
            raise GraphTasksV1Denied("grant does not cover this exact list")
        if now_ms >= grant.expires_at_ms:
            raise GraphTasksV1Denied("task create grant expired")

    def _payload(self, draft: LocalTaskDraftV1) -> dict[str, object]:
        payload: dict[str, object] = {
            "title": draft.title,
            "importance": draft.importance,
        }
        if draft.body_text:
            payload["body"] = {"contentType": "text", "content": draft.body_text}
        if draft.due_date is not None:
            payload["dueDateTime"] = {
                "dateTime": f"{draft.due_date}T00:00:00.000000",
                "timeZone": "UTC",
            }
        return payload

    def create_task(
        self,
        *,
        draft: LocalTaskDraftV1,
        grant: TaskCreateGrantV1,
    ) -> TaskCreateReceiptV1:
        self._validate_grant(grant, draft)
        if not self._nonce_ledger.consume(grant.nonce):
            raise GraphTasksV1Denied("task create grant already used")
        access = self._write_token()
        auth = (("Authorization", f"Bearer {access}"),)
        quoted_list = urllib.parse.quote(draft.list_id, safe="")
        response = self._http.post_json(
            url=f"{GRAPH_ORIGIN}/v1.0/me/todo/lists/{quoted_list}/tasks",
            payload=self._payload(draft),
            headers=auth,
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code == 429:
            raise GraphTasksV1Error(
                "provider throttled the task create; issue a fresh grant and "
                "retry after the provider delay"
            )
        if response.status_code != 201:
            raise GraphTasksV1Error("Microsoft task creation was rejected")
        task_id = _text(response.payload.get("id"), 512)
        request_id = None
        for name, value in response.headers:
            if name.casefold() == "request-id":
                request_id = value
        reconciled = self._reconcile(draft.list_id, task_id, draft, access)
        return TaskCreateReceiptV1(
            task_id,
            draft.list_id,
            self._onboarding.account_id,
            draft.draft_sha256,
            request_id,
            self._clock_epoch_s(),
            reconciled,
        )

    def _reconcile(
        self, list_id: str, task_id: str, draft: LocalTaskDraftV1, access: str
    ) -> bool:
        quoted_list = urllib.parse.quote(list_id, safe="")
        quoted_task = urllib.parse.quote(task_id, safe="")
        response = self._http.get_json(
            url=f"{GRAPH_ORIGIN}/v1.0/me/todo/lists/{quoted_list}/tasks/{quoted_task}",
            query=(("$select", "id,title,importance"),),
            headers=(("Authorization", f"Bearer {access}"),),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            return False
        return (
            response.payload.get("title") == draft.title
            and response.payload.get("importance") == draft.importance
        )


def create_microsoft_graph_tasks_v1(
    *,
    gate: GraphTasksFeatureGateV1 | None = None,
    onboarding: MicrosoftGraphLiveOnboardingV1 | None = None,
    http: GraphTasksHttpV1 | None = None,
    vault: RefreshTokenVaultV1 | None = None,
    integrity_key: bytes | None = None,
    nonce_ledger: NonceLedgerV1 | None = None,
    clock_ms: Callable[[], int] | None = None,
    clock_epoch_s: Callable[[], int] | None = None,
    project_root: Path | str | None = None,
) -> MicrosoftGraphTasksSessionV1 | None:
    selected = GraphTasksFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not GraphTasksFeatureGateV1:
        raise GraphTasksV1ContractError("sealed feature gate required")
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
        raise GraphTasksV1ContractError("exact onboarding identity required")
    if (
        vault is None
        or integrity_key is None
        or clock_ms is None
        or clock_epoch_s is None
    ):
        raise GraphTasksV1ContractError("enabled session requires complete bindings")
    if type(integrity_key) is not bytes or len(integrity_key) < 32:
        raise GraphTasksV1ContractError("integrity key must be >= 32 bytes")
    if not callable(clock_ms) or not callable(clock_epoch_s):
        raise GraphTasksV1ContractError("exact clocks are required")
    selected_ledger = (
        InMemoryNonceLedgerV1() if nonce_ledger is None else nonce_ledger
    )
    if not hasattr(selected_ledger, "consume") or not callable(
        selected_ledger.consume
    ):
        raise GraphTasksV1ContractError("nonce ledger is invalid")
    selected_http = StdlibGraphTasksHttpV1() if http is None else http
    if (
        not hasattr(selected_http, "post_form")
        or not hasattr(selected_http, "post_json")
        or not hasattr(selected_http, "get_json")
        or not hasattr(vault, "get_refresh_token")
    ):
        raise GraphTasksV1ContractError("tasks transport or vault is invalid")
    return MicrosoftGraphTasksSessionV1(
        construction_key=_CONSTRUCTION_KEY,
        onboarding=chosen,
        http=selected_http,
        vault=vault,
        integrity_key=integrity_key,
        nonce_ledger=selected_ledger,
        clock_ms=clock_ms,
        clock_epoch_s=clock_epoch_s,
    )


__all__ = [
    "ACCEPTED_MAIL_ROOTS",
    "FEATURE_FLAG",
    "GraphTasksFeatureGateV1",
    "GraphTasksV1ContractError",
    "GraphTasksV1Denied",
    "GraphTasksV1Error",
    "GraphTasksV1Uncertain",
    "InMemoryNonceLedgerV1",
    "LocalTaskDraftV1",
    "MicrosoftGraphTasksSessionV1",
    "NonceLedgerV1",
    "NotificationDecisionV1",
    "NotificationItemV1",
    "QuietHoursPolicyV1",
    "StdlibGraphTasksHttpV1",
    "TaskCreateGrantV1",
    "TaskCreateReceiptV1",
    "WRITE_SCOPES",
    "build_task_draft_v1",
    "create_microsoft_graph_tasks_v1",
    "issue_task_create_grant_v1",
    "route_notifications",
]
