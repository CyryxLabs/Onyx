"""Default-off Microsoft Graph delegated OAuth and live GET transport.

This successor adds protocol-level device authorization, refresh-token
rotation in a native-vault abstraction, signed-in account verification and a
GET-only Microsoft Graph transport. It depends on the accepted Phase 8 read
adapter and does not add provider mutation routes or live startup wiring.
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

from core import native_vault
from core.phase7_workspace_aliases_v1 import (
    WorkspaceAliasCatalogV1,
    WorkspaceAliasRecordV1,
    WorkspaceAliasV1Denied,
)
from core.phase8_microsoft_graph_read_v1 import (
    GRAPH_ORIGIN,
    GRAPH_PREFIX,
    GraphHttpResponseV1,
    GraphReadTransportV1,
)

FEATURE_FLAG: Final = "ONYX_PHASE8_MICROSOFT_GRAPH_OAUTH_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxMicrosoftGraphOAuth.v1"
IDENTITY_ORIGIN: Final = "https://login.microsoftonline.com"
DEVICE_GRANT: Final = "urn:ietf:params:oauth:grant-type:device_code"
MAX_HTTP_BYTES: Final = 1_048_576
HTTP_TIMEOUT_SECONDS: Final = 30
ACCESS_EXPIRY_SKEW: Final = 90
MAX_REFRESH_TOKEN_BYTES: Final = 1_800
READ_CALENDAR_SCOPES: Final = frozenset({"Calendars.ReadBasic", "Calendars.Read"})
READ_MAIL_SCOPES: Final = frozenset({"Mail.ReadBasic", "Mail.Read"})
REQUIRED_IDENTITY_SCOPES: Final = frozenset({"User.Read", "offline_access"})
ALLOWED_SCOPES: Final = (
    READ_CALENDAR_SCOPES | READ_MAIL_SCOPES | REQUIRED_IDENTITY_SCOPES
)
READ_ADAPTER_SCOPES: Final = READ_CALENDAR_SCOPES | READ_MAIL_SCOPES
ACCEPTED_READ_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase8-microsoft-graph-read-v1/manifest.json",
        "91a97a56729e396b84da60d30db5d33d71c8e315343d544792e7183d436dc261",
    ),
    (
        "docs/onyx/acceptance/VE-P8-MICROSOFT-GRAPH-READ-V1-E6-001.md",
        "c34565135bbd7366cc51febee82ebd41bb3ed5932d928e6df0bea82920cb2325",
    ),
    (
        "docs/onyx/acceptance/" "VE-P8-MICROSOFT-GRAPH-READ-V1-E6-001.manifest.json",
        "095f5f5af0d26cf45970bae84f97181cb4f8a672e33cbaab17e37e4d29e41769",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-READ-V1-E6-001.sha256",
        "87289e933edb2d369252e6f9816785682e0f2eb4e8d8382ffc5861f2b0f920e8",
    ),
)
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_TENANT = re.compile(
    r"^(?:common|organizations|consumers|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}$")
_IDENTITY_PATH = re.compile(
    r"^/(?:common|organizations|consumers|[0-9a-f-]{36})/"
    r"oauth2/v2\.0/(?:devicecode|token)$",
    re.IGNORECASE,
)
_GRAPH_READ_PATH = re.compile(
    r"^/v1\.0/me(?:$|/calendarView$|/messages(?:/[^/]{1,1536})?$)"
)
_CONSTRUCTION_KEY = object()


class GraphOAuthV1Error(RuntimeError):
    pass


class GraphOAuthV1ContractError(ValueError):
    pass


class GraphOAuthV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class GraphOAuthFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GraphOAuthV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GraphOAuthFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class MicrosoftGraphOAuthSettingsV1:
    client_id: str
    tenant_id: str
    scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.client_id) is not str or not _UUID.fullmatch(self.client_id):
            raise GraphOAuthV1ContractError("Microsoft client_id is invalid")
        if type(self.tenant_id) is not str or not _TENANT.fullmatch(self.tenant_id):
            raise GraphOAuthV1ContractError("Microsoft tenant_id is invalid")
        if (
            type(self.scopes) is not tuple
            or not self.scopes
            or len(self.scopes) > 8
            or len(set(self.scopes)) != len(self.scopes)
            or set(self.scopes) - ALLOWED_SCOPES
            or not (set(self.scopes) & READ_CALENDAR_SCOPES)
            or not (set(self.scopes) & READ_MAIL_SCOPES)
            or not REQUIRED_IDENTITY_SCOPES.issubset(self.scopes)
        ):
            raise GraphOAuthV1ContractError("exact delegated read scopes are required")


@dataclass(frozen=True, slots=True, repr=False)
class JsonHttpResponseV1:
    status_code: int
    payload: dict[str, object]
    headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.status_code) is not int
            or not 100 <= self.status_code <= 599
            or type(self.payload) is not dict
            or type(self.headers) is not tuple
            or any(
                type(name) is not str
                or type(value) is not str
                or len(name) > 100
                or len(value) > 2_000
                for name, value in self.headers
            )
        ):
            raise GraphOAuthV1ContractError("HTTP response contract is invalid")


class GraphOAuthHttpV1(Protocol):
    def post_form(
        self,
        *,
        url: str,
        fields: tuple[tuple[str, str], ...],
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


class RefreshTokenVaultV1(Protocol):
    def get_refresh_token(self) -> str | None: ...

    def set_refresh_token(self, value: str) -> None: ...

    def delete_refresh_token(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class DeviceAuthorizationV1:
    user_code: str
    verification_uri: str
    expires_at_epoch_s: int
    interval_seconds: int
    provider_message: str
    provider_message_untrusted: bool = True


@dataclass(frozen=True, slots=True)
class OAuthSessionStatusV1:
    connected: bool
    workspace_id: str
    principal_id: str
    account_id: str
    tenant_id: str
    scopes: tuple[str, ...]
    access_expires_at_epoch_s: int | None
    refresh_token_present: bool


@dataclass(frozen=True, slots=True)
class DevicePollResultV1:
    status: str
    retry_after_seconds: int | None
    session: OAuthSessionStatusV1 | None

    def __post_init__(self) -> None:
        if self.status not in {
            "authorization_pending",
            "slow_down",
            "complete",
            "declined",
            "expired",
        }:
            raise GraphOAuthV1ContractError("device poll status is invalid")
        retry_status = self.status in {"authorization_pending", "slow_down"}
        if retry_status:
            if (
                type(self.retry_after_seconds) is not int
                or self.retry_after_seconds <= 0
                or self.session is not None
            ):
                raise GraphOAuthV1ContractError(
                    "retry poll result requires an exact positive delay only"
                )
            return
        if self.retry_after_seconds is not None:
            raise GraphOAuthV1ContractError(
                "terminal poll result cannot include a retry delay"
            )
        if self.status == "complete":
            if (
                type(self.session) is not OAuthSessionStatusV1
                or not self.session.connected
            ):
                raise GraphOAuthV1ContractError(
                    "complete poll result requires a connected session"
                )
            return
        if self.session is not None:
            raise GraphOAuthV1ContractError(
                "incomplete poll result cannot include a session"
            )


@dataclass(slots=True)
class _PendingDeviceCodeV1:
    device_code: str
    expires_at_epoch_s: int
    interval_seconds: int
    next_poll_at_epoch_s: int


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _strict_json(data: bytes) -> dict[str, object]:
    if type(data) is not bytes or len(data) > MAX_HTTP_BYTES:
        raise GraphOAuthV1Denied("HTTP payload size is invalid")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise GraphOAuthV1Denied("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise GraphOAuthV1Denied("non-finite JSON value")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GraphOAuthV1Denied("HTTP JSON is invalid") from exc
    if type(value) is not dict:
        raise GraphOAuthV1Denied("HTTP JSON object required")
    return value


def _headers(value: object) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    items = getattr(value, "items", None)
    if not callable(items):
        return ()
    result: list[tuple[str, str]] = []
    for name, item in items():
        if type(name) is str and type(item) is str:
            result.append((name, item))
    return tuple(result)


class StdlibGraphOAuthHttpV1:
    """Small HTTPS JSON client with redirects disabled and bounded responses."""

    __slots__ = ("_opener",)

    def __init__(self) -> None:
        context = ssl.create_default_context()
        self._opener = urllib.request.build_opener(
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=context),
        )

    def _open(
        self, request: urllib.request.Request, timeout_seconds: int
    ) -> JsonHttpResponseV1:
        if (
            type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= HTTP_TIMEOUT_SECONDS
        ):
            raise GraphOAuthV1ContractError("HTTP timeout is invalid")
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                data = response.read(MAX_HTTP_BYTES + 1)
                if len(data) > MAX_HTTP_BYTES:
                    raise GraphOAuthV1Denied("HTTP response exceeded size limit")
                return JsonHttpResponseV1(
                    int(response.status),
                    _strict_json(data),
                    _headers(response.headers),
                )
        except urllib.error.HTTPError as exc:
            data = exc.read(MAX_HTTP_BYTES + 1)
            if len(data) > MAX_HTTP_BYTES:
                raise GraphOAuthV1Denied("HTTP error exceeded size limit") from exc
            return JsonHttpResponseV1(
                int(exc.code),
                _strict_json(data),
                _headers(exc.headers),
            )
        except GraphOAuthV1Denied:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise GraphOAuthV1Error("Microsoft HTTPS request failed") from exc

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
            or not _IDENTITY_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or type(fields) is not tuple
            or not fields
            or any(
                type(key) is not str or type(value) is not str for key, value in fields
            )
        ):
            raise GraphOAuthV1Denied("identity POST route is invalid")
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
        return self._open(request, timeout_seconds)

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
            or not parsed.path.startswith(GRAPH_PREFIX)
            or parsed.query
            or parsed.fragment
            or type(query) is not tuple
            or type(headers) is not tuple
            or any(
                type(key) is not str or type(value) is not str for key, value in query
            )
            or any(
                type(key) is not str or type(value) is not str for key, value in headers
            )
        ):
            raise GraphOAuthV1Denied("Graph GET route is invalid")
        encoded = urllib.parse.urlencode(query)
        target = f"{url}?{encoded}" if encoded else url
        outbound = {"Accept": "application/json", "User-Agent": "CyryxLabs-Onyx/1"}
        protected = {name.casefold() for name in outbound}
        for name, value in headers:
            if name.casefold() in protected:
                raise GraphOAuthV1Denied("duplicate protected HTTP header")
            outbound[name] = value
        # Base URL is pinned above; the query is encoded from structured pairs.
        request = urllib.request.Request(  # noqa: S310
            target, headers=outbound, method="GET"
        )
        return self._open(request, timeout_seconds)


class NativeGraphRefreshTokenVaultV1:
    """Refresh-token-only native vault binding derived from an alias identity."""

    __slots__ = ("_vault",)

    def __init__(self, credential: WorkspaceAliasRecordV1) -> None:
        if (
            type(credential) is not WorkspaceAliasRecordV1
            or credential.kind != "credential"
            or credential.provider != "microsoft-graph"
            or credential.vault_service is None
            or credential.vault_account is None
        ):
            raise GraphOAuthV1ContractError("Graph credential alias is invalid")
        fingerprint = hashlib.sha256(
            f"{credential.vault_service}\0{credential.vault_account}".encode()
        ).hexdigest()
        reference = native_vault.SecretReference(
            "CyryxLabs.Onyx.GraphOAuth.v1",
            f"rt_{fingerprint[:40]}",
            "Cyryx Labs Onyx Microsoft Graph refresh token",
        )
        self._vault = native_vault.NativeSecretVault(reference)

    def get_refresh_token(self) -> str | None:
        try:
            value = self._vault.get_bytes()
        except native_vault.NativeVaultError as exc:
            raise GraphOAuthV1Error("native OAuth vault read failed") from exc
        if value is None:
            return None
        try:
            return _refresh_token(value.decode("utf-8"))
        except UnicodeError as exc:
            raise GraphOAuthV1Denied("native OAuth vault value is invalid") from exc

    def set_refresh_token(self, value: str) -> None:
        token = _refresh_token(value)
        try:
            self._vault.set_bytes(token.encode("utf-8"))
        except native_vault.NativeVaultError as exc:
            raise GraphOAuthV1Error("native OAuth vault write failed") from exc

    def delete_refresh_token(self) -> bool:
        try:
            return self._vault.delete()
        except native_vault.NativeVaultError as exc:
            raise GraphOAuthV1Error("native OAuth vault delete failed") from exc


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_READ_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GraphOAuthV1Denied(
                "accepted Graph read evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GraphOAuthV1Denied("accepted Graph read evidence drift")


def _text(value: object, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise GraphOAuthV1Denied("provider text contract drift")
    return value


def _positive_int(
    value: object,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise GraphOAuthV1Denied(f"{label} contract drift")
    return value


def _refresh_token(value: object) -> str:
    token = _text(value, MAX_REFRESH_TOKEN_BYTES)
    if len(token.encode("utf-8")) > MAX_REFRESH_TOKEN_BYTES:
        raise GraphOAuthV1Denied("refresh token exceeded vault limit")
    return token


def _header(
    headers: tuple[tuple[str, str], ...],
    name: str,
) -> str | None:
    wanted = name.casefold()
    values = [value for key, value in headers if key.casefold() == wanted]
    if len(values) > 1:
        raise GraphOAuthV1Denied("duplicate provider response header")
    return values[0] if values else None


class MicrosoftGraphOAuthSessionV1:
    __slots__ = (
        "_access_expires_at",
        "_access_token",
        "_aliases",
        "_credential",
        "_http",
        "_pending",
        "_principal_id",
        "_refresh_present",
        "_settings",
        "_vault",
        "_workspace_id",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        aliases: WorkspaceAliasCatalogV1,
        credential: WorkspaceAliasRecordV1,
        settings: MicrosoftGraphOAuthSettingsV1,
        http: GraphOAuthHttpV1,
        vault: RefreshTokenVaultV1,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GraphOAuthV1ContractError("use create_microsoft_graph_oauth_v1")
        self._aliases = aliases
        self._credential = credential
        self._settings = settings
        self._http = http
        self._vault = vault
        self._workspace_id = aliases.workspace_id
        self._principal_id = aliases.principal_id
        self._access_token: str | None = None
        self._access_expires_at: int | None = None
        self._pending: _PendingDeviceCodeV1 | None = None
        self._refresh_present = False

    def _attest(self, now_ms: int) -> None:
        try:
            current = self._aliases.get(
                kind="credential",
                alias_name=self._credential.alias_name,
                now_ms=now_ms,
            )
        except WorkspaceAliasV1Denied as exc:
            raise GraphOAuthV1Denied("Graph credential alias unavailable") from exc
        if (
            current != self._credential
            or self._aliases.workspace_id != self._workspace_id
            or self._aliases.principal_id != self._principal_id
            or (
                current.rotate_after_ms is not None
                and now_ms >= current.rotate_after_ms
            )
        ):
            raise GraphOAuthV1Denied("Graph OAuth binding drift")

    @property
    def _device_url(self) -> str:
        tenant = urllib.parse.quote(self._settings.tenant_id, safe="")
        return f"{IDENTITY_ORIGIN}/{tenant}/oauth2/v2.0/devicecode"

    @property
    def _token_url(self) -> str:
        tenant = urllib.parse.quote(self._settings.tenant_id, safe="")
        return f"{IDENTITY_ORIGIN}/{tenant}/oauth2/v2.0/token"

    def _scope_text(self) -> str:
        return " ".join(sorted(self._settings.scopes, key=str.casefold))

    def status(self) -> OAuthSessionStatusV1:
        return OAuthSessionStatusV1(
            self._access_token is not None,
            self._workspace_id,
            self._principal_id,
            self._credential.account_id or "",
            self._settings.tenant_id,
            self._settings.scopes,
            self._access_expires_at,
            self._refresh_present,
        )

    def begin_device_authorization(
        self,
        *,
        now_ms: int,
        now_epoch_s: int,
    ) -> DeviceAuthorizationV1:
        self._attest(now_ms)
        if type(now_epoch_s) is not int or now_epoch_s < 0:
            raise GraphOAuthV1ContractError("current epoch is invalid")
        response = self._http.post_form(
            url=self._device_url,
            fields=(
                ("client_id", self._settings.client_id),
                ("scope", self._scope_text()),
            ),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not JsonHttpResponseV1 or response.status_code != 200:
            raise GraphOAuthV1Error("Microsoft device authorization failed")
        expires_in = _positive_int(
            response.payload.get("expires_in"),
            label="device expiry",
            minimum=60,
            maximum=1_800,
        )
        interval = _positive_int(
            response.payload.get("interval", 5),
            label="device interval",
            minimum=1,
            maximum=60,
        )
        device_code = _text(response.payload.get("device_code"), 2_048)
        user_code = _text(response.payload.get("user_code"), 100)
        verification_uri = _text(response.payload.get("verification_uri"), 2_048)
        parsed_uri = urllib.parse.urlparse(verification_uri)
        if (
            parsed_uri.scheme != "https"
            or parsed_uri.netloc.casefold()
            not in {
                "microsoft.com",
                "www.microsoft.com",
                "login.microsoftonline.com",
                "login.microsoft.com",
            }
            or parsed_uri.fragment
        ):
            raise GraphOAuthV1Denied("device verification URI is invalid")
        message = response.payload.get("message")
        provider_message = (
            _text(message, 2_000)
            if message is not None
            else f"Open {verification_uri} and enter code {user_code}."
        )
        expires_at = now_epoch_s + expires_in
        self._pending = _PendingDeviceCodeV1(
            device_code,
            expires_at,
            interval,
            now_epoch_s + interval,
        )
        return DeviceAuthorizationV1(
            user_code,
            verification_uri,
            expires_at,
            interval,
            provider_message,
        )

    def poll_device_authorization(
        self,
        *,
        now_ms: int,
        now_epoch_s: int,
    ) -> DevicePollResultV1:
        self._attest(now_ms)
        pending = self._pending
        if pending is None:
            raise GraphOAuthV1ContractError("device authorization is not pending")
        if type(now_epoch_s) is not int or now_epoch_s < 0:
            raise GraphOAuthV1ContractError("current epoch is invalid")
        if now_epoch_s >= pending.expires_at_epoch_s:
            self._pending = None
            return DevicePollResultV1("expired", None, None)
        if now_epoch_s < pending.next_poll_at_epoch_s:
            return DevicePollResultV1(
                "authorization_pending",
                pending.next_poll_at_epoch_s - now_epoch_s,
                None,
            )
        response = self._http.post_form(
            url=self._token_url,
            fields=(
                ("grant_type", DEVICE_GRANT),
                ("client_id", self._settings.client_id),
                ("device_code", pending.device_code),
            ),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            # A successful token endpoint response consumes the device code even
            # when the returned account, scopes or vault write later fail
            # validation. Never leave that one-time authorization reusable.
            self._pending = None
            self._accept_token_payload(
                response.payload,
                now_ms=now_ms,
                now_epoch_s=now_epoch_s,
                require_refresh=True,
            )
            return DevicePollResultV1("complete", None, self.status())
        error = response.payload.get("error")
        if error == "authorization_pending":
            pending.next_poll_at_epoch_s = now_epoch_s + pending.interval_seconds
            return DevicePollResultV1(
                "authorization_pending", pending.interval_seconds, None
            )
        if error == "slow_down":
            pending.interval_seconds = min(60, pending.interval_seconds + 5)
            pending.next_poll_at_epoch_s = now_epoch_s + pending.interval_seconds
            return DevicePollResultV1("slow_down", pending.interval_seconds, None)
        self._pending = None
        if error == "authorization_declined":
            return DevicePollResultV1("declined", None, None)
        if error == "expired_token":
            return DevicePollResultV1("expired", None, None)
        raise GraphOAuthV1Error("Microsoft device token exchange failed")

    def _accept_token_payload(
        self,
        payload: dict[str, object],
        *,
        now_ms: int,
        now_epoch_s: int,
        require_refresh: bool,
        previous_refresh: str | None = None,
    ) -> None:
        # Access tokens remain process-local and are never persisted. Python
        # strings are immutable, so the runtime can drop references but cannot
        # guarantee an in-place wipe of bearer-token bytes from process memory.
        self._attest(now_ms)
        token_type = _text(payload.get("token_type"), 30)
        access_token = _text(payload.get("access_token"), 16_384)
        expires_in = _positive_int(
            payload.get("expires_in"),
            label="access expiry",
            minimum=60,
            maximum=86_400,
        )
        scope_text = _text(payload.get("scope"), 2_000)
        granted = frozenset(scope_text.split())
        required_granted = set(self._settings.scopes) - {"offline_access"}
        if token_type.casefold() != "bearer" or not required_granted.issubset(granted):
            raise GraphOAuthV1Denied("Microsoft granted scope drift")
        refresh_value = payload.get("refresh_token")
        refresh = (
            previous_refresh if refresh_value is None else _refresh_token(refresh_value)
        )
        if require_refresh and refresh is None:
            raise GraphOAuthV1Denied("Microsoft refresh token unavailable")
        self._verify_account(access_token)
        if refresh is not None:
            self._vault.set_refresh_token(refresh)
            self._refresh_present = True
        self._access_token = access_token
        self._access_expires_at = now_epoch_s + expires_in

    def _verify_account(self, access_token: str) -> None:
        response = self._http.get_json(
            url=f"{GRAPH_ORIGIN}{GRAPH_PREFIX}me",
            query=(("$select", "id,mail,userPrincipalName"),),
            headers=(("Authorization", f"Bearer {access_token}"),),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not JsonHttpResponseV1 or response.status_code != 200:
            raise GraphOAuthV1Denied("signed-in Microsoft account unavailable")
        account = self._credential.account_id or ""
        candidates = {
            value.casefold()
            for value in (
                response.payload.get("mail"),
                response.payload.get("userPrincipalName"),
            )
            if type(value) is str and _EMAIL.fullmatch(value)
        }
        if account.casefold() not in candidates:
            raise GraphOAuthV1Denied("signed-in Microsoft account mismatch")

    def restore(
        self,
        *,
        now_ms: int,
        now_epoch_s: int,
    ) -> OAuthSessionStatusV1:
        self._attest(now_ms)
        refresh = self._vault.get_refresh_token()
        self._refresh_present = refresh is not None
        if refresh is None:
            return self.status()
        self._refresh(
            refresh,
            now_ms=now_ms,
            now_epoch_s=now_epoch_s,
        )
        return self.status()

    def _refresh(
        self,
        refresh: str,
        *,
        now_ms: int,
        now_epoch_s: int,
    ) -> None:
        # Drop any stale/expired bearer reference before attempting refresh.
        # The refresh token remains in the native vault so transient provider
        # failures do not destructively force re-consent.
        self._access_token = None
        self._access_expires_at = None
        response = self._http.post_form(
            url=self._token_url,
            fields=(
                ("client_id", self._settings.client_id),
                ("grant_type", "refresh_token"),
                ("refresh_token", refresh),
                ("scope", self._scope_text()),
            ),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not JsonHttpResponseV1 or response.status_code != 200:
            raise GraphOAuthV1Error("Microsoft refresh failed")
        self._accept_token_payload(
            response.payload,
            now_ms=now_ms,
            now_epoch_s=now_epoch_s,
            require_refresh=False,
            previous_refresh=refresh,
        )

    def _token(
        self,
        *,
        now_ms: int,
        now_epoch_s: int,
    ) -> str:
        self._attest(now_ms)
        if (
            self._access_token is not None
            and self._access_expires_at is not None
            and now_epoch_s + ACCESS_EXPIRY_SKEW < self._access_expires_at
        ):
            return self._access_token
        refresh = self._vault.get_refresh_token()
        self._refresh_present = refresh is not None
        if refresh is None:
            raise GraphOAuthV1Denied("Microsoft sign-in is required")
        self._refresh(refresh, now_ms=now_ms, now_epoch_s=now_epoch_s)
        if self._access_token is None:
            raise GraphOAuthV1Denied("Microsoft access token unavailable")
        return self._access_token

    def create_read_transport(
        self,
        *,
        clock_epoch_s: Callable[[], int],
        clock_ms: Callable[[], int],
    ) -> GraphReadTransportV1:
        if not callable(clock_epoch_s) or not callable(clock_ms):
            raise GraphOAuthV1ContractError("exact clocks are required")
        return MicrosoftGraphBearerReadTransportV1(
            construction_key=_CONSTRUCTION_KEY,
            session=self,
            http=self._http,
            clock_epoch_s=clock_epoch_s,
            clock_ms=clock_ms,
        )

    def disconnect(self, *, now_ms: int) -> bool:
        if type(now_ms) is not int or now_ms < 0:
            raise GraphOAuthV1ContractError("current time is invalid")
        deleted = self._vault.delete_refresh_token()
        self._access_token = None
        self._access_expires_at = None
        self._refresh_present = False
        self._pending = None
        return deleted


class MicrosoftGraphBearerReadTransportV1:
    __slots__ = ("_clock_epoch_s", "_clock_ms", "_http", "_session")

    def __init__(
        self,
        *,
        construction_key: object,
        session: MicrosoftGraphOAuthSessionV1,
        http: GraphOAuthHttpV1,
        clock_epoch_s: Callable[[], int],
        clock_ms: Callable[[], int],
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GraphOAuthV1ContractError("transport construction is sealed")
        self._session = session
        self._http = http
        self._clock_epoch_s = clock_epoch_s
        self._clock_ms = clock_ms

    def get(
        self,
        *,
        url: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
    ) -> GraphHttpResponseV1:
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or not _GRAPH_READ_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or type(query) is not tuple
            or type(headers) is not tuple
            or any(name.casefold() == "authorization" for name, _value in headers)
        ):
            raise GraphOAuthV1Denied("Graph read transport route is invalid")
        now_epoch_s, now_ms = self._clock_epoch_s(), self._clock_ms()
        if type(now_epoch_s) is not int or type(now_ms) is not int:
            raise GraphOAuthV1ContractError("clock result is invalid")
        access_token = self._session._token(
            now_ms=now_ms,
            now_epoch_s=now_epoch_s,
        )
        response = self._http.get_json(
            url=url,
            query=query,
            headers=(("Authorization", f"Bearer {access_token}"), *headers),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        request_id = _header(response.headers, "request-id")
        return GraphHttpResponseV1(
            response.status_code,
            response.payload,
            request_id,
        )


def create_microsoft_graph_oauth_v1(
    *,
    gate: GraphOAuthFeatureGateV1 | None = None,
    aliases: WorkspaceAliasCatalogV1 | None = None,
    credential_alias_name: str | None = None,
    settings: MicrosoftGraphOAuthSettingsV1 | None = None,
    http: GraphOAuthHttpV1 | None = None,
    vault: RefreshTokenVaultV1 | None = None,
    now_ms: int | None = None,
    project_root: Path | str | None = None,
) -> MicrosoftGraphOAuthSessionV1 | None:
    selected = GraphOAuthFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not GraphOAuthFeatureGateV1:
        raise GraphOAuthV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    if (
        aliases is None
        or credential_alias_name is None
        or settings is None
        or now_ms is None
    ):
        raise GraphOAuthV1ContractError("enabled OAuth requires complete bindings")
    if type(aliases) is not WorkspaceAliasCatalogV1:
        raise GraphOAuthV1ContractError("exact WorkspaceAliasCatalogV1 required")
    if type(settings) is not MicrosoftGraphOAuthSettingsV1:
        raise GraphOAuthV1ContractError("exact MicrosoftGraphOAuthSettingsV1 required")
    try:
        credential = aliases.get(
            kind="credential",
            alias_name=credential_alias_name,
            now_ms=now_ms,
        )
    except WorkspaceAliasV1Denied as exc:
        raise GraphOAuthV1Denied("Graph credential alias unavailable") from exc
    alias_scopes = set(credential.scopes)
    settings_read_scopes = set(settings.scopes) & READ_ADAPTER_SCOPES
    if (
        credential.provider != "microsoft-graph"
        or not settings_read_scopes.issubset(alias_scopes)
        or not (settings_read_scopes & READ_CALENDAR_SCOPES)
        or not (settings_read_scopes & READ_MAIL_SCOPES)
        or (
            credential.tenant_id is not None
            and credential.tenant_id.casefold() != settings.tenant_id.casefold()
        )
        or (
            credential.rotate_after_ms is not None
            and now_ms >= credential.rotate_after_ms
        )
    ):
        raise GraphOAuthV1Denied("Graph OAuth alias/settings binding denied")
    selected_http = StdlibGraphOAuthHttpV1() if http is None else http
    selected_vault = (
        NativeGraphRefreshTokenVaultV1(credential) if vault is None else vault
    )
    if (
        not hasattr(selected_http, "post_form")
        or not hasattr(selected_http, "get_json")
        or not hasattr(selected_vault, "get_refresh_token")
        or not hasattr(selected_vault, "set_refresh_token")
        or not hasattr(selected_vault, "delete_refresh_token")
    ):
        raise GraphOAuthV1ContractError("OAuth transport or vault is invalid")
    return MicrosoftGraphOAuthSessionV1(
        construction_key=_CONSTRUCTION_KEY,
        aliases=aliases,
        credential=credential,
        settings=settings,
        http=selected_http,
        vault=selected_vault,
    )


__all__ = [
    "DeviceAuthorizationV1",
    "DevicePollResultV1",
    "GraphOAuthFeatureGateV1",
    "GraphOAuthHttpV1",
    "GraphOAuthV1ContractError",
    "GraphOAuthV1Denied",
    "GraphOAuthV1Error",
    "JsonHttpResponseV1",
    "MicrosoftGraphBearerReadTransportV1",
    "MicrosoftGraphOAuthSessionV1",
    "MicrosoftGraphOAuthSettingsV1",
    "NativeGraphRefreshTokenVaultV1",
    "OAuthSessionStatusV1",
    "RefreshTokenVaultV1",
    "StdlibGraphOAuthHttpV1",
    "create_microsoft_graph_oauth_v1",
]
