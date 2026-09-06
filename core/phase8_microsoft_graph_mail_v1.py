"""Default-off Microsoft Graph mail draft/send with exact-recipient grant.

This successor adds the highest-risk Phase 8 mutation: sending mail on the
owner's behalf. External send is gated by a signed, expiring, one-shot grant
that binds the exact frozen local email-draft digest AND the exact recipient
and cc sets, so a send can never reach a recipient the grant did not approve.
The send is performed as create-server-draft then send, capturing the
provider-assigned ``internetMessageId`` so the outcome is reconcilable against
Sent Items. An uncertain send outcome consumes the grant and must be reconciled
against Sent Items before any resend, preventing duplicate delivery. The module
is exactly default-off, composes only public frozen contracts, denies
attachments in V1 and adds no reply-all, forward, delete or folder authority.
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
from core.phase8_microsoft_graph_read_v1 import GRAPH_ORIGIN, LocalEmailDraftV1

FEATURE_FLAG: Final = "ONYX_PHASE8_MICROSOFT_GRAPH_MAIL_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxMicrosoftGraphMail.v1"
WRITE_SCOPES: Final = (
    "Mail.ReadWrite",
    "Mail.Send",
    "User.Read",
    "offline_access",
)
HTTP_TIMEOUT_SECONDS: Final = 30
MAX_HTTP_BYTES: Final = 1_048_576
ACCESS_EXPIRY_SKEW: Final = 90
MAX_GRANT_TTL_MS: Final = 600_000
MAX_RECIPIENTS: Final = 100
ACCEPTED_CALENDAR_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase8-microsoft-graph-calendar-v1/manifest.json",
        "e28bf370f81ac991d4a384d02783aa809d6afc59a5036f75852679679a5962e4",
    ),
    (
        "docs/onyx/acceptance/VE-P8-MICROSOFT-GRAPH-CALENDAR-V1-E6-001.md",
        "283934b419b82f346a240e604ad87ce0dba81bee2013ed14b8fd2ec9895e7314",
    ),
    (
        "docs/onyx/acceptance/"
        "VE-P8-MICROSOFT-GRAPH-CALENDAR-V1-E6-001.manifest.json",
        "7d76e98826cd62ccbd4b1d52a8021b557125a085a5d0306abf4e10e74b99eedb",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-CALENDAR-V1-E6-001.sha256",
        "93cdd20f42ef882c6b6c2357861cf923bb6d422d217fa5c95dc5b1848ff3fde8",
    ),
)
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}$")
# Provider-assigned RFC message-id. Single/double quotes are disallowed so the
# value cannot break out of the OData $filter string used for reconciliation.
_INTERNET_ID = re.compile(r"^<?[^\x00-\x1f<>'\"]{1,996}>?$")
_TOKEN_PATH = re.compile(
    r"^/(?:common|organizations|consumers|[0-9a-f-]{36})/oauth2/v2\.0/token$",
    re.IGNORECASE,
)
_SEND_PATH = re.compile(r"^/v1\.0/me/messages/[^/]{1,1536}/send$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_CONSTRUCTION_KEY = object()


class GraphMailV1Error(RuntimeError):
    pass


class GraphMailV1ContractError(ValueError):
    pass


class GraphMailV1Denied(PermissionError):
    pass


class GraphMailV1Uncertain(RuntimeError):
    """A send reached the provider boundary with an unknown outcome.

    The caller must reconcile against Sent Items before any resend; the
    consumed grant cannot be reused and a fresh grant is required after
    reconciliation proves the message unsent.
    """


@dataclass(frozen=True, slots=True)
class GraphMailFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GraphMailV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GraphMailFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_CALENDAR_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GraphMailV1Denied(
                "accepted Calendar V1 evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GraphMailV1Denied("accepted Calendar V1 evidence drift")


def _validate_identity_field(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 256
        or any(ord(character) < 32 for character in value)
    ):
        raise GraphMailV1ContractError(f"{label} is invalid")
    return value


def _recipient_key(recipients: tuple[str, ...], cc: tuple[str, ...]) -> str:
    # Canonical, order-independent, casefolded, length-framed digest of the
    # exact recipient and cc sets so a grant cannot be reused for a different
    # audience even by reordering or case changes.
    def frame(values: tuple[str, ...]) -> bytes:
        normalized = sorted(value.casefold() for value in values)
        parts = bytearray()
        for value in normalized:
            encoded = value.encode("utf-8")
            parts += len(encoded).to_bytes(4, "big")
            parts += encoded
        return bytes(parts)

    return hashlib.sha256(
        len(recipients).to_bytes(4, "big")
        + frame(recipients)
        + len(cc).to_bytes(4, "big")
        + frame(cc)
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class MailSendGrantV1:
    """Signed, expiring, one-shot authority for one draft to an exact audience.

    Key-management invariant: the ``integrity_key`` MUST be scoped per
    (workspace_id, principal_id); those fields are bound cryptographically, not
    against session state.
    """

    workspace_id: str
    principal_id: str
    account_id: str
    draft_sha256: str
    recipient_key: str
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
            or type(self.recipient_key) is not str
            or len(self.recipient_key) != 64
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
            raise GraphMailV1ContractError("mail send grant is invalid")


def _grant_payload(
    workspace_id: str,
    principal_id: str,
    account_id: str,
    draft_sha256: str,
    recipient_key: str,
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
        recipient_key,
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


def issue_mail_send_grant_v1(
    *,
    integrity_key: bytes,
    workspace_id: str,
    principal_id: str,
    account_id: str,
    draft: LocalEmailDraftV1,
    nonce: str,
    now_ms: int,
    ttl_ms: int = 300_000,
) -> MailSendGrantV1:
    if type(integrity_key) is not bytes or len(integrity_key) < 32:
        raise GraphMailV1ContractError("integrity key must be >= 32 bytes")
    if type(draft) is not LocalEmailDraftV1:
        raise GraphMailV1ContractError("exact LocalEmailDraftV1 required")
    if type(now_ms) is not int or now_ms < 0:
        raise GraphMailV1ContractError("current time is invalid")
    if type(ttl_ms) is not int or not 1_000 <= ttl_ms <= MAX_GRANT_TTL_MS:
        raise GraphMailV1ContractError("grant TTL is invalid")
    workspace_id = _validate_identity_field(workspace_id, label="workspace_id")
    principal_id = _validate_identity_field(principal_id, label="principal_id")
    account_id = _validate_identity_field(account_id, label="account_id")
    recipient_key = _recipient_key(draft.recipients, draft.cc)
    expires = now_ms + ttl_ms
    signature = hmac.new(
        integrity_key,
        _grant_payload(
            workspace_id,
            principal_id,
            account_id,
            draft.draft_sha256,
            recipient_key,
            now_ms,
            expires,
            nonce,
        ),
        hashlib.sha256,
    ).hexdigest()
    return MailSendGrantV1(
        workspace_id,
        principal_id,
        account_id,
        draft.draft_sha256,
        recipient_key,
        now_ms,
        expires,
        nonce,
        signature,
    )


@dataclass(frozen=True, slots=True)
class MailSendReceiptV1:
    message_id: str
    internet_message_id: str
    account_id: str
    draft_sha256: str
    recipient_key: str
    recipient_count: int
    provider_request_id: str | None
    sent_at_epoch_s: int
    reconciled: bool


def _expected_email_digest(draft: LocalEmailDraftV1) -> str:
    """Recompute the frozen local-email-draft digest from the draft's content.

    Mirrors the frozen read module's canonical form exactly
    (`_draft_sha256("email", payload)`), so the send path can prove the draft's
    subject/body/recipients actually match the digest the grant binds — a grant
    cannot authorize substituted content under a copied digest.
    """

    canonical = json.dumps(
        {
            "kind": "email",
            "recipients": list(draft.recipients),
            "cc": list(draft.cc),
            "subject": draft.subject,
            "body_text": draft.body_text,
            "reply_to_message_id": draft.reply_to_message_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


class NonceLedgerV1(Protocol):
    def consume(self, nonce: str) -> bool: ...


class InMemoryNonceLedgerV1:
    """Per-instance one-shot nonce ledger.

    Durability invariant: this in-memory ledger only prevents replay within a
    single live object. For cross-session and cross-restart one-shot
    protection (so a captured, still-valid grant cannot be replayed by a fresh
    session to deliver a duplicate email), the caller MUST supply a durable,
    atomic ledger bound to shared storage.
    """

    __slots__ = ("_used",)

    def __init__(self) -> None:
        self._used: set[str] = set()

    def consume(self, nonce: str) -> bool:
        if type(nonce) is not str or not nonce:
            raise GraphMailV1ContractError("nonce is invalid")
        if nonce in self._used:
            return False
        self._used.add(nonce)
        return True


class GraphMailHttpV1(Protocol):
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

    def post_empty(
        self,
        *,
        url: str,
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
        raise GraphMailV1Denied("HTTP payload size is invalid")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise GraphMailV1Denied("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GraphMailV1Denied("HTTP JSON is invalid") from exc
    if type(value) is not dict:
        raise GraphMailV1Denied("HTTP JSON object required")
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


class StdlibGraphMailHttpV1:
    """Route-pinned HTTPS client: identity POST, messages POST, send POST,
    sent-items GET."""

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
                    raise GraphMailV1Denied("HTTP response exceeded size limit")
                body = _strict_json(data) if data.strip() else {}
                return JsonHttpResponseV1(
                    int(response.status), body, _headers(response.headers)
                )
        except urllib.error.HTTPError as exc:
            data = exc.read(MAX_HTTP_BYTES + 1)
            if len(data) > MAX_HTTP_BYTES:
                raise GraphMailV1Denied("HTTP error exceeded size limit") from exc
            body = _strict_json(data) if data.strip() else {}
            return JsonHttpResponseV1(int(exc.code), body, _headers(exc.headers))
        except GraphMailV1Denied:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise GraphMailV1Uncertain(
                "provider outcome unknown; reconcile before resend"
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
            raise GraphMailV1Denied("identity POST route is invalid")
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
        except GraphMailV1Uncertain as exc:
            raise GraphMailV1Error("Microsoft identity request failed") from exc

    def post_json(self, *, url, payload, headers, timeout_seconds):
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or parsed.path != "/v1.0/me/messages"
            or parsed.query
            or parsed.fragment
            or type(payload) is not dict
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphMailV1Denied("Graph draft route is invalid")
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

    def post_empty(self, *, url, headers, timeout_seconds):
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or not _SEND_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphMailV1Denied("Graph send route is invalid")
        outbound = {"Accept": "application/json", "User-Agent": "CyryxLabs-Onyx/1"}
        for name, value in headers:
            outbound[name] = value
        # URL is pinned above to HTTPS and the exact Microsoft Graph send route.
        request = urllib.request.Request(  # noqa: S310
            url, data=b"", headers=outbound, method="POST"
        )
        return self._open(request)

    def get_json(self, *, url, query, headers, timeout_seconds):
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or parsed.path != "/v1.0/me/mailFolders/sentitems/messages"
            or parsed.query
            or parsed.fragment
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphMailV1Denied("Graph sent-items route is invalid")
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
        except GraphMailV1Uncertain as exc:
            raise GraphMailV1Error("Microsoft sent-items read failed") from exc


def _text(value: object, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise GraphMailV1Denied("provider text contract drift")
    return value


class MicrosoftGraphMailSessionV1:
    """Write-scope session with exact-recipient grant, send and reconciliation."""

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
        http: GraphMailHttpV1,
        vault: RefreshTokenVaultV1,
        integrity_key: bytes,
        nonce_ledger: NonceLedgerV1,
        clock_ms: Callable[[], int],
        clock_epoch_s: Callable[[], int],
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GraphMailV1ContractError("use create_microsoft_graph_mail_v1")
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
            raise GraphMailV1ContractError("clock result is invalid")
        if (
            self._access_token is not None
            and self._access_expires_at is not None
            and now + ACCESS_EXPIRY_SKEW < self._access_expires_at
        ):
            return self._access_token
        refresh = self._vault.get_refresh_token()
        if refresh is None:
            raise GraphMailV1Denied("Microsoft sign-in is required")
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
            raise GraphMailV1Error("Microsoft write-scope refresh failed")
        token_type = _text(response.payload.get("token_type"), 30)
        access = _text(response.payload.get("access_token"), 16_384)
        scope_text = _text(response.payload.get("scope"), 2_000)
        expires_in = response.payload.get("expires_in")
        if type(expires_in) is not int or not 60 <= expires_in <= 86_400:
            raise GraphMailV1Denied("access expiry contract drift")
        granted = frozenset(scope_text.split())
        if token_type.casefold() != "bearer" or "Mail.Send" not in granted:
            raise GraphMailV1Denied("mail send scope was not granted")
        rotated = response.payload.get("refresh_token")
        if type(rotated) is str and rotated:
            # Rotation is best-effort: a vault that rejects an oversized token
            # (frozen cap) must not abort the send. Microsoft does not revoke
            # the prior refresh token when issuing a new one, so the stored
            # token stays valid.
            try:
                self._vault.set_refresh_token(rotated)
            except (PermissionError, ValueError):
                pass
        self._access_token = access
        self._access_expires_at = now + expires_in
        return access

    def _validate_grant(
        self, grant: MailSendGrantV1, draft: LocalEmailDraftV1
    ) -> None:
        if type(grant) is not MailSendGrantV1:
            raise GraphMailV1ContractError("exact MailSendGrantV1 required")
        if type(draft) is not LocalEmailDraftV1:
            raise GraphMailV1ContractError("exact LocalEmailDraftV1 required")
        now_ms = self._clock_ms()
        if type(now_ms) is not int:
            raise GraphMailV1ContractError("clock result is invalid")
        expected = hmac.new(
            self._integrity_key,
            _grant_payload(
                grant.workspace_id,
                grant.principal_id,
                grant.account_id,
                grant.draft_sha256,
                grant.recipient_key,
                grant.issued_at_ms,
                grant.expires_at_ms,
                grant.nonce,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, grant.signature):
            raise GraphMailV1Denied("mail send grant signature is invalid")
        if grant.account_id.casefold() != self._onboarding.account_id.casefold():
            raise GraphMailV1Denied("grant account does not match session")
        if not hmac.compare_digest(grant.draft_sha256, draft.draft_sha256):
            raise GraphMailV1Denied("grant does not cover this exact draft")
        # Recompute the draft digest from its actual content so a grant cannot
        # authorize a substituted subject/body under a copied digest field.
        if not hmac.compare_digest(
            _expected_email_digest(draft), draft.draft_sha256
        ):
            raise GraphMailV1Denied("draft content does not match its digest")
        if not hmac.compare_digest(
            grant.recipient_key, _recipient_key(draft.recipients, draft.cc)
        ):
            raise GraphMailV1Denied("grant does not cover this exact audience")
        if now_ms >= grant.expires_at_ms:
            raise GraphMailV1Denied("mail send grant expired")
        if draft.mutation_authority is not False:
            raise GraphMailV1ContractError("draft mutation_authority drift")
        if draft.reply_to_message_id is not None:
            raise GraphMailV1Denied("reply drafts are denied in Mail V1")
        if not draft.recipients:
            raise GraphMailV1Denied("draft has no recipients")
        for address in (*draft.recipients, *draft.cc):
            if type(address) is not str or not _EMAIL.fullmatch(address):
                raise GraphMailV1Denied("draft recipient address is invalid")

    def _draft_payload(self, draft: LocalEmailDraftV1) -> dict[str, object]:
        def address(value: str) -> dict[str, object]:
            return {"emailAddress": {"address": value}}

        payload: dict[str, object] = {
            "subject": draft.subject,
            "body": {"contentType": "text", "content": draft.body_text},
            "toRecipients": [address(item) for item in draft.recipients],
        }
        if draft.cc:
            payload["ccRecipients"] = [address(item) for item in draft.cc]
        return payload

    def send(
        self,
        *,
        draft: LocalEmailDraftV1,
        grant: MailSendGrantV1,
    ) -> MailSendReceiptV1:
        self._validate_grant(grant, draft)
        # Consume the one-shot grant atomically before any provider mutation.
        # With a durable ledger this makes the grant one-shot across sessions
        # and restarts: a second session handed the same still-valid grant is
        # denied here, so no duplicate draft is created and no duplicate mail is
        # sent. Any later failure leaves the grant consumed (safe direction).
        if not self._nonce_ledger.consume(grant.nonce):
            raise GraphMailV1Denied("mail send grant already used")
        access = self._write_token()
        auth = (("Authorization", f"Bearer {access}"),)
        created = self._http.post_json(
            url=f"{GRAPH_ORIGIN}/v1.0/me/messages",
            payload=self._draft_payload(draft),
            headers=auth,
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if created.status_code == 429:
            raise GraphMailV1Error(
                "provider throttled the draft; issue a fresh grant and retry "
                "after the provider delay"
            )
        if created.status_code != 201:
            raise GraphMailV1Error("Microsoft draft creation was rejected")
        message_id = _text(created.payload.get("id"), 1_536)
        internet_id = _text(created.payload.get("internetMessageId"), 998)
        if not _INTERNET_ID.fullmatch(internet_id):
            raise GraphMailV1Denied("provider internetMessageId is invalid")
        request_id = None
        try:
            sent = self._http.post_empty(
                url=f"{GRAPH_ORIGIN}/v1.0/me/messages/"
                f"{urllib.parse.quote(message_id, safe='')}/send",
                headers=auth,
                timeout_seconds=HTTP_TIMEOUT_SECONDS,
            )
        except GraphMailV1Uncertain:
            raise
        if sent.status_code == 429:
            raise GraphMailV1Error(
                "provider throttled the send; reconcile Sent Items before any "
                "resend"
            )
        if sent.status_code != 202:
            raise GraphMailV1Error("Microsoft send was rejected")
        for name, value in sent.headers:
            if name.casefold() == "request-id":
                request_id = value
        reconciled = self._reconcile(internet_id, access)
        return MailSendReceiptV1(
            message_id,
            internet_id,
            self._onboarding.account_id,
            draft.draft_sha256,
            grant.recipient_key,
            len(draft.recipients),
            request_id,
            self._clock_epoch_s(),
            reconciled,
        )

    def _reconcile(self, internet_id: str, access: str) -> bool:
        response = self._http.get_json(
            url=f"{GRAPH_ORIGIN}/v1.0/me/mailFolders/sentitems/messages",
            query=(
                ("$filter", f"internetMessageId eq '{internet_id}'"),
                ("$select", "id,internetMessageId"),
                ("$top", "1"),
            ),
            headers=(("Authorization", f"Bearer {access}"),),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            return False
        values = response.payload.get("value")
        if type(values) is not list:
            return False
        for item in values:
            if type(item) is dict and item.get("internetMessageId") == internet_id:
                return True
        return False

    def reconcile_uncertain(
        self,
        *,
        internet_message_id: str,
    ) -> bool:
        """Search Sent Items for an uncertain send before any resend."""

        if type(internet_message_id) is not str or not _INTERNET_ID.fullmatch(
            internet_message_id
        ):
            raise GraphMailV1ContractError("internetMessageId is invalid")
        return self._reconcile(internet_message_id, self._write_token())


def create_microsoft_graph_mail_v1(
    *,
    gate: GraphMailFeatureGateV1 | None = None,
    onboarding: MicrosoftGraphLiveOnboardingV1 | None = None,
    http: GraphMailHttpV1 | None = None,
    vault: RefreshTokenVaultV1 | None = None,
    integrity_key: bytes | None = None,
    nonce_ledger: NonceLedgerV1 | None = None,
    clock_ms: Callable[[], int] | None = None,
    clock_epoch_s: Callable[[], int] | None = None,
    project_root: Path | str | None = None,
) -> MicrosoftGraphMailSessionV1 | None:
    selected = GraphMailFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not GraphMailFeatureGateV1:
        raise GraphMailV1ContractError("sealed feature gate required")
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
        raise GraphMailV1ContractError("exact onboarding identity required")
    if (
        vault is None
        or integrity_key is None
        or clock_ms is None
        or clock_epoch_s is None
    ):
        raise GraphMailV1ContractError("enabled session requires complete bindings")
    if type(integrity_key) is not bytes or len(integrity_key) < 32:
        raise GraphMailV1ContractError("integrity key must be >= 32 bytes")
    if not callable(clock_ms) or not callable(clock_epoch_s):
        raise GraphMailV1ContractError("exact clocks are required")
    selected_ledger = (
        InMemoryNonceLedgerV1() if nonce_ledger is None else nonce_ledger
    )
    if not hasattr(selected_ledger, "consume") or not callable(
        selected_ledger.consume
    ):
        raise GraphMailV1ContractError("nonce ledger is invalid")
    selected_http = StdlibGraphMailHttpV1() if http is None else http
    if (
        not hasattr(selected_http, "post_form")
        or not hasattr(selected_http, "post_json")
        or not hasattr(selected_http, "post_empty")
        or not hasattr(selected_http, "get_json")
        or not hasattr(vault, "get_refresh_token")
    ):
        raise GraphMailV1ContractError("mail transport or vault is invalid")
    return MicrosoftGraphMailSessionV1(
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
    "ACCEPTED_CALENDAR_ROOTS",
    "FEATURE_FLAG",
    "GraphMailFeatureGateV1",
    "GraphMailV1ContractError",
    "GraphMailV1Denied",
    "GraphMailV1Error",
    "GraphMailV1Uncertain",
    "InMemoryNonceLedgerV1",
    "MailSendGrantV1",
    "MailSendReceiptV1",
    "MicrosoftGraphMailSessionV1",
    "NonceLedgerV1",
    "StdlibGraphMailHttpV1",
    "WRITE_SCOPES",
    "create_microsoft_graph_mail_v1",
    "issue_mail_send_grant_v1",
]
