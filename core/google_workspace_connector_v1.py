"""Default-off Google Workspace read-only connector foundation.

This clean-room module is intentionally absent from live activation.  It owns
no browser, worker, poller, UI, voice, or mutation authority.  The only remote
operations are Google's installed-app OAuth authorization-code exchange,
refresh/revocation, Gmail profile/message listing, and Calendar event listing.

Long-lived tokens and pending PKCE material are available only through injected
OS-vault capabilities.  Durable metadata contains digests, expiry, scopes and
provider state only.  Provider responses are untrusted and all HTTP routes,
redirect behavior, byte/time/request budgets, account binding and token
generations are checked immediately before use.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import ssl
import stat
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Final, Iterator, Mapping, Protocol
from urllib.parse import parse_qsl, quote, urlencode, urlsplit


FEATURE_FLAG: Final = "ONYX_GOOGLE_WORKSPACE_CONNECTOR_V1"
ENABLED_VALUE: Final = "true"
AUTH_ORIGIN: Final = "https://accounts.google.com"
AUTH_PATH: Final = "/o/oauth2/v2/auth"
OAUTH_ORIGIN: Final = "https://oauth2.googleapis.com"
TOKEN_PATH: Final = "/token"
REVOKE_PATH: Final = "/revoke"
GMAIL_ORIGIN: Final = "https://gmail.googleapis.com"
GMAIL_PROFILE_PATH: Final = "/gmail/v1/users/me/profile"
GMAIL_MESSAGES_PATH: Final = "/gmail/v1/users/me/messages"
CALENDAR_ORIGIN: Final = "https://www.googleapis.com"
CALENDAR_EVENTS_PATH: Final = "/calendar/v3/calendars/primary/events"
GMAIL_READ_SCOPE: Final = "https://www.googleapis.com/auth/gmail.readonly"
CALENDAR_READ_SCOPE: Final = "https://www.googleapis.com/auth/calendar.readonly"
READ_SCOPES: Final = (GMAIL_READ_SCOPE, CALENDAR_READ_SCOPE)
MAX_RESPONSE_BYTES: Final = 1_048_576
MAX_PAGES: Final = 5
MAX_RESULTS: Final = 250
MAX_REQUESTS: Final = 8
MAX_TIMEOUT_SECONDS: Final = 30.0
MAX_QUERY_BYTES: Final = 512
MAX_TOKEN_BYTES: Final = 16_384
MAX_PKCE_BYTES: Final = 4_096
MAX_METADATA_DB_BYTES: Final = 16_777_216
MAX_METADATA_SEAL_BYTES: Final = 8_192
MAX_METADATA_JOURNAL_BYTES: Final = 16_384
LOCK_TIMEOUT_SECONDS: Final = 5.0
ACCESS_SKEW_SECONDS: Final = 90
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,253}\Z")
_CLIENT_ID = re.compile(r"[A-Za-z0-9._:-]{8,255}\Z")
_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,189}\Z")
_PAGE_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]{1,2048}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_HEADER_NAME = re.compile(r"[A-Za-z0-9-]{1,80}\Z")
_RFC3339_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_RFC3339_DATETIME = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?"
    r"(?:Z|[+-]\d{2}:\d{2})\Z"
)


class GoogleWorkspaceV1Error(RuntimeError):
    pass


class GoogleWorkspaceV1ContractError(ValueError):
    pass


class GoogleWorkspaceV1Denied(PermissionError):
    pass


class GoogleWorkspaceV1UnknownOutcome(GoogleWorkspaceV1Error):
    """The provider may have observed a request; automatic retry is forbidden."""


def _external_port_call(
    operation: Callable[[], object],
    error_type: type[GoogleWorkspaceV1Error] | type[GoogleWorkspaceV1Denied],
    message: str,
) -> object:
    """Translate an external exception after its except context has ended."""
    failed = False
    result: object = None
    try:
        result = operation()
    except Exception:
        failed = True
    if failed:
        _raise_clean(error_type(message))
    return result


def _raise_clean(error: Exception) -> None:
    """Raise with both chaining attributes physically cleared."""
    try:
        raise error from None
    except Exception:
        error.__cause__ = None
        error.__context__ = None
        error.__suppress_context__ = True
        raise


class GoogleMetadataGenerationAnchorV1(Protocol):
    """Trusted monotonic state held outside the replayable DB/seal pair."""

    def read(self, store_reference: str) -> int | None: ...

    def compare_and_swap(
        self, store_reference: str, expected: int | None, replacement: int
    ) -> bool: ...


class GoogleIdentityPseudonymizerV1(Protocol):
    """Injected, secret-backed and domain-separated identity pseudonymizer."""

    def pseudonym(self, domain: str, value: str) -> str: ...


class HmacGoogleIdentityPseudonymizerV1:
    def __init__(self, key: bytes) -> None:
        if type(key) is not bytes or len(key) != 32:
            raise GoogleWorkspaceV1ContractError(
                "identity pseudonymization key must be exactly 32 bytes"
            )
        self._key = bytes(key)

    def pseudonym(self, domain: str, value: str) -> str:
        _identifier(domain, "identity domain")
        _bounded_text(value, "identity value", 512)
        payload = b"OnyxGoogleIdentity.v1\x00" + domain.encode("ascii") + b"\x00" + value.encode("utf-8")
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()


@contextmanager
def _exclusive_file_lock(
    path: Path, *, timeout_seconds: float = LOCK_TIMEOUT_SECONDS
) -> Iterator[None]:
    """Serialize cooperative readers/writers across threads and processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        metadata = path.lstat()
        attributes = getattr(metadata, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_nlink != 1
            or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise GoogleWorkspaceV1Denied(
                "durable metadata lock must be a single-link regular file"
            )
    with path.open("a+b") as stream:
        opened = os.fstat(stream.fileno())
        current = path.lstat()
        if (
            opened.st_nlink != 1
            or current.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise GoogleWorkspaceV1Denied(
                "durable metadata lock identity drift"
            )
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
            os.fsync(stream.fileno())
        stream.seek(0)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    _raise_clean(
                        GoogleWorkspaceV1Denied(
                            "durable metadata lock timeout"
                        )
                    )
                time.sleep(0.01)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        _raise_clean(GoogleWorkspaceV1ContractError("value is not canonical JSON"))


def _sha(value: object) -> str:
    raw = value if type(value) is bytes else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _bounded_text(value: object, label: str, maximum: int, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value) or "\x00" in value:
        raise GoogleWorkspaceV1ContractError(f"{label} is invalid")
    if len(value.encode("utf-8")) > maximum:
        raise GoogleWorkspaceV1ContractError(f"{label} exceeds its byte budget")
    return value


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise GoogleWorkspaceV1ContractError(f"{label} is invalid")
    return value


def _exact_scopes(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or value != READ_SCOPES:
        raise GoogleWorkspaceV1Denied("exact Google read-only scopes are required")
    return value


def _now(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise GoogleWorkspaceV1ContractError("current time is invalid")
    return value


def _rfc3339_datetime(value: object, label: str) -> datetime:
    text = _bounded_text(value, label, 64)
    if _RFC3339_DATETIME.fullmatch(text) is None:
        raise GoogleWorkspaceV1ContractError(f"{label} is not strict RFC3339")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _raise_clean(GoogleWorkspaceV1ContractError(f"{label} is invalid"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoogleWorkspaceV1ContractError(f"{label} requires a timezone")
    return parsed


def _rfc3339_date(value: object, label: str) -> date:
    text = _bounded_text(value, label, 10)
    if _RFC3339_DATE.fullmatch(text) is None:
        raise GoogleWorkspaceV1ContractError(f"{label} is not a strict date")
    try:
        return date.fromisoformat(text)
    except ValueError:
        _raise_clean(GoogleWorkspaceV1ContractError(f"{label} is invalid"))


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GoogleWorkspaceV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GoogleWorkspaceFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceBindingV1:
    owner_id: str
    workspace_id: str
    account_id: str

    def __post_init__(self) -> None:
        _identifier(self.owner_id, "owner_id")
        _identifier(self.workspace_id, "workspace_id")
        if type(self.account_id) is not str or _EMAIL.fullmatch(self.account_id) is None:
            raise GoogleWorkspaceV1ContractError("account_id must be an email address")
        if self.account_id != self.account_id.casefold():
            raise GoogleWorkspaceV1ContractError("account_id must be canonical")

    @property
    def digest(self) -> str:
        return _sha(
            {
                "schema": "OnyxGoogleWorkspaceBinding.v1",
                "owner_id": self.owner_id,
                "workspace_id": self.workspace_id,
                "account_id": self.account_id,
            }
        )


@dataclass(frozen=True, slots=True)
class GoogleOAuthSettingsV1:
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...] = READ_SCOPES

    def __post_init__(self) -> None:
        if type(self.client_id) is not str or _CLIENT_ID.fullmatch(self.client_id) is None:
            raise GoogleWorkspaceV1ContractError("Google client_id is invalid")
        _exact_scopes(self.scopes)
        parsed = urlsplit(self.redirect_uri)
        if (
            parsed.fragment
            or parsed.query
            or parsed.username is not None
            or parsed.password is not None
            or parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.path != "/oauth2/callback"
            or parsed.port is None
            or not 1024 <= parsed.port <= 65535
        ):
            raise GoogleWorkspaceV1ContractError("redirect_uri is not an exact loopback URI")


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceBudgetV1:
    maximum_pages: int = MAX_PAGES
    maximum_results: int = 100
    maximum_requests: int = MAX_REQUESTS
    maximum_response_bytes: int = MAX_RESPONSE_BYTES
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("maximum_pages", self.maximum_pages, MAX_PAGES),
            ("maximum_results", self.maximum_results, MAX_RESULTS),
            ("maximum_requests", self.maximum_requests, MAX_REQUESTS),
            ("maximum_response_bytes", self.maximum_response_bytes, MAX_RESPONSE_BYTES),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise GoogleWorkspaceV1ContractError(f"{label} is outside its bound")
        if type(self.timeout_seconds) not in {int, float} or isinstance(
            self.timeout_seconds, bool
        ):
            raise GoogleWorkspaceV1ContractError("timeout_seconds is invalid")
        if not 0.01 <= float(self.timeout_seconds) <= MAX_TIMEOUT_SECONDS:
            raise GoogleWorkspaceV1ContractError("timeout_seconds is outside its bound")


@dataclass(slots=True)
class _GoogleOperationBudgetV1:
    policy: GoogleWorkspaceBudgetV1
    clock: Callable[[], float]
    started_at: float
    deadline: float
    request_count: int = 0
    response_bytes: int = 0
    reported_elapsed_ms: int = 0
    item_count: int = 0

    @classmethod
    def start(
        cls,
        policy: GoogleWorkspaceBudgetV1,
        clock: Callable[[], float],
    ) -> "_GoogleOperationBudgetV1":
        started = float(clock())
        return cls(policy, clock, started, started + float(policy.timeout_seconds))

    def remaining_seconds(self) -> float:
        remaining = self.deadline - float(self.clock())
        simulated = float(self.policy.timeout_seconds) - (
            self.reported_elapsed_ms / 1000.0
        )
        return min(remaining, simulated)

    def before_request(self) -> tuple[float, int]:
        remaining_seconds = self.remaining_seconds()
        remaining_bytes = self.policy.maximum_response_bytes - self.response_bytes
        if remaining_seconds <= 0:
            raise GoogleWorkspaceV1Denied("Google operation deadline exhausted")
        if remaining_bytes <= 0:
            raise GoogleWorkspaceV1Denied("Google operation response budget exhausted")
        if self.request_count >= self.policy.maximum_requests:
            raise GoogleWorkspaceV1Denied("Google operation request budget exhausted")
        self.request_count += 1
        return remaining_seconds, remaining_bytes

    def after_response(self, response: "GoogleHttpResponseV1") -> None:
        self.response_bytes += response.body_bytes
        self.reported_elapsed_ms += response.elapsed_ms
        if self.response_bytes > self.policy.maximum_response_bytes:
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google operation response budget exceeded after dispatch"
            )
        if self.remaining_seconds() <= 0:
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google operation deadline exceeded after dispatch"
            )

    def add_items(self, count: int) -> None:
        if type(count) is not int or count < 0:
            raise GoogleWorkspaceV1ContractError("Google item count is invalid")
        self.item_count += count
        if self.item_count > self.policy.maximum_results:
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google operation item budget exceeded after dispatch"
            )


@dataclass(frozen=True, slots=True, repr=False)
class GoogleTokenBundleV1:
    binding_digest: str
    access_token: str
    refresh_token: str
    access_expires_at_epoch_s: int
    scopes: tuple[str, ...]
    generation: int

    def __post_init__(self) -> None:
        if type(self.binding_digest) is not str or _DIGEST.fullmatch(self.binding_digest) is None:
            raise GoogleWorkspaceV1ContractError("token binding digest is invalid")
        for label, value in (
            ("access_token", self.access_token),
            ("refresh_token", self.refresh_token),
        ):
            if type(value) is not str or not value:
                raise GoogleWorkspaceV1ContractError(f"{label} is invalid")
            if len(value.encode("utf-8", errors="strict")) > MAX_TOKEN_BYTES:
                raise GoogleWorkspaceV1ContractError(
                    f"{label} exceeds its byte budget"
                )
        if type(self.access_expires_at_epoch_s) is not int or self.access_expires_at_epoch_s <= 0:
            raise GoogleWorkspaceV1ContractError("access token expiry is invalid")
        _exact_scopes(self.scopes)
        if type(self.generation) is not int or self.generation <= 0:
            raise GoogleWorkspaceV1ContractError("token generation is invalid")

    @property
    def digest(self) -> str:
        return _sha(
            {
                "binding_digest": self.binding_digest,
                "access_token_sha256": _sha(self.access_token.encode()),
                "refresh_token_sha256": _sha(self.refresh_token.encode()),
                "access_expires_at_epoch_s": self.access_expires_at_epoch_s,
                "scopes": self.scopes,
                "generation": self.generation,
            }
        )


@dataclass(frozen=True, slots=True, repr=False)
class GooglePendingAuthorizationV1:
    binding_digest: str
    state: str
    code_verifier: str
    redirect_uri: str
    expires_at_epoch_s: int
    scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.binding_digest) is not str or _DIGEST.fullmatch(self.binding_digest) is None:
            raise GoogleWorkspaceV1ContractError("pending binding digest is invalid")
        _bounded_text(self.state, "state", 256)
        _bounded_text(self.code_verifier, "code_verifier", 128)
        if not 43 <= len(self.code_verifier) <= 128:
            raise GoogleWorkspaceV1ContractError("PKCE verifier length is invalid")
        _bounded_text(self.redirect_uri, "redirect_uri", 512)
        if type(self.expires_at_epoch_s) is not int or self.expires_at_epoch_s <= 0:
            raise GoogleWorkspaceV1ContractError("pending expiry is invalid")
        _exact_scopes(self.scopes)


class GoogleTokenResolverV1(Protocol):
    """OS-vault read capability.  Implementations must never log values."""

    def resolve(self, binding_digest: str) -> GoogleTokenBundleV1 | None: ...


class GoogleTokenPersisterV1(Protocol):
    """OS-vault CAS/write/delete capability."""

    def compare_and_set(
        self,
        binding_digest: str,
        expected_digest: str | None,
        value: GoogleTokenBundleV1,
    ) -> bool: ...

    def delete(self, binding_digest: str, expected_digest: str) -> bool: ...


class GooglePendingVaultV1(Protocol):
    """OS-vault capability for short-lived state and PKCE verifier material."""

    def store(self, state_digest: str, value: GooglePendingAuthorizationV1) -> None: ...

    def consume(self, state_digest: str) -> GooglePendingAuthorizationV1 | None: ...


@dataclass(frozen=True, slots=True, repr=False)
class GoogleHttpRequestV1:
    method: str
    origin: str
    path: str
    query: tuple[tuple[str, str], ...] = ()
    headers: tuple[tuple[str, str], ...] = ()
    form: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = 10.0
    maximum_response_bytes: int = MAX_RESPONSE_BYTES
    follow_redirects: bool = False

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST"}:
            raise GoogleWorkspaceV1ContractError("HTTP method is forbidden")
        parsed = urlsplit(self.origin)
        if parsed.scheme != "https" or parsed.path or parsed.query or parsed.fragment:
            raise GoogleWorkspaceV1ContractError("HTTP origin must be exact HTTPS")
        if not self.path.startswith("/") or "?" in self.path or "#" in self.path:
            raise GoogleWorkspaceV1ContractError("HTTP path is invalid")
        if type(self.follow_redirects) is not bool or self.follow_redirects:
            raise GoogleWorkspaceV1Denied("HTTP redirects are forbidden")
        for label, pairs, maximum in (
            ("query", self.query, MAX_QUERY_BYTES),
            ("headers", self.headers, 32_768),
            ("form", self.form, 32_768),
        ):
            if type(pairs) is not tuple or any(
                type(pair) is not tuple
                or len(pair) != 2
                or type(pair[0]) is not str
                or type(pair[1]) is not str
                or not pair[0]
                or "\r" in pair[0]
                or "\n" in pair[0]
                or "\r" in pair[1]
                or "\n" in pair[1]
                for pair in pairs
            ):
                raise GoogleWorkspaceV1ContractError(f"HTTP {label} is invalid")
            if len(urlencode(pairs).encode("utf-8")) > maximum:
                raise GoogleWorkspaceV1ContractError(f"HTTP {label} exceeds its budget")
        if any(_HEADER_NAME.fullmatch(name) is None for name, _ in self.headers):
            raise GoogleWorkspaceV1ContractError("HTTP header name is invalid")
        GoogleWorkspaceBudgetV1(
            maximum_response_bytes=self.maximum_response_bytes,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True, repr=False)
class GoogleHttpResponseV1:
    status_code: int
    payload: dict[str, object]
    body_bytes: int
    elapsed_ms: int
    final_origin: str
    final_path: str
    headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise GoogleWorkspaceV1ContractError("HTTP status is invalid")
        if type(self.payload) is not dict:
            raise GoogleWorkspaceV1ContractError("HTTP payload is invalid")
        if type(self.body_bytes) is not int or self.body_bytes < 0:
            raise GoogleWorkspaceV1ContractError("HTTP byte count is invalid")
        if type(self.elapsed_ms) is not int or self.elapsed_ms < 0:
            raise GoogleWorkspaceV1ContractError("HTTP elapsed time is invalid")
        if (
            type(self.headers) is not tuple
            or len(self.headers) > 128
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or type(pair[0]) is not str
                or type(pair[1]) is not str
                or "\r" in pair[0]
                or "\n" in pair[0]
                or "\r" in pair[1]
                or "\n" in pair[1]
                for pair in self.headers
            )
            or len(_canonical(self.headers)) > 32_768
        ):
            raise GoogleWorkspaceV1ContractError("HTTP response headers are invalid")


class GoogleHttpTransportV1(Protocol):
    def send(self, request: GoogleHttpRequestV1) -> GoogleHttpResponseV1: ...


class _NoGoogleRedirectV1(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StdlibGoogleHttpTransportV1:
    """Platform-TLS transport with redirects disabled and bounded JSON reads."""

    def __init__(self) -> None:
        context = ssl.create_default_context()
        self._opener = urllib.request.build_opener(
            _NoGoogleRedirectV1(), urllib.request.HTTPSHandler(context=context)
        )

    def send(self, request: GoogleHttpRequestV1) -> GoogleHttpResponseV1:
        if type(request) is not GoogleHttpRequestV1:
            raise GoogleWorkspaceV1ContractError("exact Google HTTP request required")
        url = f"{request.origin}{request.path}"
        if request.query:
            url = f"{url}?{urlencode(request.query)}"
        data = None
        if request.form:
            data = urlencode(request.form).encode("utf-8")
        outbound = urllib.request.Request(
            url,
            data=data,
            headers={name: value for name, value in request.headers},
            method=request.method,
        )
        started = time.monotonic()
        try:
            opened = self._opener.open(outbound, timeout=request.timeout_seconds)
        except urllib.error.HTTPError as error:
            opened = error
        with opened:
            raw = opened.read(request.maximum_response_bytes + 1)
            status = int(opened.status)
            final = urlsplit(opened.geturl())
            headers = tuple((str(key), str(value)) for key, value in opened.headers.items())
        if len(raw) > request.maximum_response_bytes:
            raise GoogleWorkspaceV1Denied("Google response byte budget exceeded")
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                _raise_clean(
                    GoogleWorkspaceV1Denied("Google response is not valid JSON")
                )
            if type(payload) is not dict:
                raise GoogleWorkspaceV1Denied("Google response JSON is not an object")
        else:
            payload = {}
        elapsed = int((time.monotonic() - started) * 1000)
        final_origin = f"{final.scheme}://{final.netloc}"
        return GoogleHttpResponseV1(
            status,
            payload,
            len(raw),
            elapsed,
            final_origin,
            final.path,
            headers,
        )


@dataclass(frozen=True, slots=True)
class GoogleGrantMetadataV1:
    binding_digest: str
    owner_digest: str
    workspace_digest: str
    account_digest: str
    scopes: tuple[str, ...]
    access_expires_at_epoch_s: int
    grant_digest: str
    provider_state: str
    updated_at_epoch_s: int

    def __post_init__(self) -> None:
        for value in (
            self.binding_digest,
            self.owner_digest,
            self.workspace_digest,
            self.account_digest,
            self.grant_digest,
        ):
            if type(value) is not str or _DIGEST.fullmatch(value) is None:
                raise GoogleWorkspaceV1ContractError("metadata digest is invalid")
        _exact_scopes(self.scopes)
        if (
            type(self.access_expires_at_epoch_s) is not int
            or self.access_expires_at_epoch_s <= 0
            or type(self.updated_at_epoch_s) is not int
            or self.updated_at_epoch_s <= 0
        ):
            raise GoogleWorkspaceV1ContractError("metadata timestamps are invalid")
        if self.provider_state not in {"connected", "revoked", "attempted_unknown"}:
            raise GoogleWorkspaceV1ContractError("provider state is invalid")


class GoogleGrantMetadataStoreV1(Protocol):
    def get(self, binding_digest: str) -> GoogleGrantMetadataV1 | None: ...

    def put(self, value: GoogleGrantMetadataV1) -> None: ...


class InMemoryGoogleGrantMetadataStoreV1:
    def __init__(self) -> None:
        self._values: dict[str, GoogleGrantMetadataV1] = {}
        self._lock = threading.RLock()

    def get(self, binding_digest: str) -> GoogleGrantMetadataV1 | None:
        with self._lock:
            return self._values.get(binding_digest)

    def put(self, value: GoogleGrantMetadataV1) -> None:
        if type(value) is not GoogleGrantMetadataV1:
            raise GoogleWorkspaceV1ContractError("metadata value is invalid")
        with self._lock:
            self._values[value.binding_digest] = value


class SqliteGoogleGrantMetadataStoreV1:
    """HMAC-authenticated digest-only metadata with an external 32-byte key."""

    _SCHEMA: Final = "OnyxGoogleGrantMetadata.sqlite.v3"
    _SEAL_SCHEMA: Final = "OnyxGoogleGrantMetadataFileSeal.v2"
    _JOURNAL_SCHEMA: Final = "OnyxGoogleGrantMetadataJournal.v1"
    _APPLICATION_ID: Final = 0x4F4E5958
    _USER_VERSION: Final = 3
    _GRANT_COLUMNS: Final = (
        "binding_digest",
        "owner_digest",
        "workspace_digest",
        "account_digest",
        "scopes_json",
        "access_expires_at_epoch_s",
        "grant_digest",
        "provider_state",
        "updated_at_epoch_s",
        "sequence",
        "row_hmac",
    )
    _GRANT_SCHEMA_INFO: Final = (
        (0, "binding_digest", "TEXT", 1, None, 1),
        (1, "owner_digest", "TEXT", 1, None, 0),
        (2, "workspace_digest", "TEXT", 1, None, 0),
        (3, "account_digest", "TEXT", 1, None, 0),
        (4, "scopes_json", "TEXT", 1, None, 0),
        (5, "access_expires_at_epoch_s", "INTEGER", 1, None, 0),
        (6, "grant_digest", "TEXT", 1, None, 0),
        (7, "provider_state", "TEXT", 1, None, 0),
        (8, "updated_at_epoch_s", "INTEGER", 1, None, 0),
        (9, "sequence", "INTEGER", 1, None, 0),
        (10, "row_hmac", "TEXT", 1, None, 0),
    )
    _HEAD_SCHEMA_INFO: Final = (
        (0, "singleton", "INTEGER", 0, None, 1),
        (1, "schema_name", "TEXT", 1, None, 0),
        (2, "sequence", "INTEGER", 1, None, 0),
        (3, "head_digest", "TEXT", 1, None, 0),
        (4, "head_hmac", "TEXT", 1, None, 0),
    )
    _EXPECTED_OBJECTS: Final = (
        (
            "table",
            "google_grant_head_v1",
            "google_grant_head_v1",
            "CREATE TABLE google_grant_head_v1 ( singleton INTEGER PRIMARY KEY "
            "CHECK(singleton = 1), schema_name TEXT NOT NULL, sequence INTEGER "
            "NOT NULL, head_digest TEXT NOT NULL, head_hmac TEXT NOT NULL )",
        ),
        (
            "table",
            "google_grants_v1",
            "google_grants_v1",
            "CREATE TABLE google_grants_v1 ( binding_digest TEXT PRIMARY KEY "
            "NOT NULL, owner_digest TEXT NOT NULL, workspace_digest TEXT NOT "
            "NULL, account_digest TEXT NOT NULL, scopes_json TEXT NOT NULL, "
            "access_expires_at_epoch_s INTEGER NOT NULL, grant_digest TEXT NOT "
            "NULL, provider_state TEXT NOT NULL, updated_at_epoch_s INTEGER NOT "
            "NULL, sequence INTEGER NOT NULL, row_hmac TEXT NOT NULL ) WITHOUT ROWID",
        ),
    )

    def __init__(
        self,
        path: Path,
        authentication_key: bytes,
        generation_anchor: GoogleMetadataGenerationAnchorV1,
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise GoogleWorkspaceV1ContractError("metadata path must be absolute")
        if type(authentication_key) is not bytes or len(authentication_key) != 32:
            raise GoogleWorkspaceV1ContractError(
                "metadata authentication key must be exactly 32 bytes"
            )
        self._path = path
        self._seal_path = path.with_name(f"{path.name}.seal")
        self._journal_path = path.with_name(f"{path.name}.journal.auth")
        self._lock_path = path.with_name(f"{path.name}.lock")
        self._key = bytes(authentication_key)
        self._lock = threading.RLock()
        if any(
            not callable(getattr(generation_anchor, method, None))
            for method in ("read", "compare_and_swap")
        ):
            raise GoogleWorkspaceV1ContractError(
                "trusted generation anchor capability is required"
            )
        self._anchor = generation_anchor
        self._store_reference = self._mac_domain(
            "store-reference", self._canonical_path().encode("utf-8")
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_file_lock(self._lock_path):
            self._recover_prepared()
            self._initialize_or_validate()

    def _initialize_or_validate(self) -> None:
        existed = self._path.exists()
        initial_manifest = self._read_external_seal() if existed else None
        if not existed and self._seal_path.exists():
            raise GoogleWorkspaceV1Denied("orphan durable metadata seal")
        if existed:
            raw = self._read_database_bytes()
            self._validate_snapshot_pair(
                initial_manifest, raw, require_anchor=True
            )
            return

        staged_database = self._path.with_name(
            f"{self._path.name}.stage-{secrets.token_hex(12)}"
        )
        staged_seal = staged_database.with_name(f"{staged_database.name}.seal")
        prepared = False
        try:
            with self._using_paths(staged_database, staged_seal):
                with self._connection() as connection:
                    mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                    if str(mode).casefold() != "delete":
                        raise GoogleWorkspaceV1Denied(
                            "rollback journal mode is unavailable"
                        )
                    connection.execute("PRAGMA synchronous=FULL")
                    connection.execute(f"PRAGMA application_id={self._APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version={self._USER_VERSION}")
                    connection.execute(
                        "CREATE TABLE google_grants_v1 ( binding_digest TEXT "
                        "PRIMARY KEY NOT NULL, owner_digest TEXT NOT NULL, "
                        "workspace_digest TEXT NOT NULL, account_digest TEXT NOT "
                        "NULL, scopes_json TEXT NOT NULL, access_expires_at_epoch_s "
                        "INTEGER NOT NULL, grant_digest TEXT NOT NULL, provider_state "
                        "TEXT NOT NULL, updated_at_epoch_s INTEGER NOT NULL, sequence "
                        "INTEGER NOT NULL, row_hmac TEXT NOT NULL ) WITHOUT ROWID"
                    )
                    connection.execute(
                        "CREATE TABLE google_grant_head_v1 ( singleton INTEGER "
                        "PRIMARY KEY CHECK(singleton = 1), schema_name TEXT NOT NULL, "
                        "sequence INTEGER NOT NULL, head_digest TEXT NOT NULL, "
                        "head_hmac TEXT NOT NULL )"
                    )
                    self._verify_schema(connection)
                    digest = _sha([])
                    connection.execute(
                        "INSERT INTO google_grant_head_v1 "
                        "(singleton, schema_name, sequence, head_digest, head_hmac) "
                        "VALUES (1, ?, 0, ?, ?)",
                        (self._SCHEMA, digest, self._head_hmac(0, digest)),
                    )
                    connection.commit()
                    self._verify(connection)
                    container = self._verify_container(connection, None)
                self._write_external_seal(container, generation=0)
                staged_manifest = self._read_external_seal()
                staged_raw = self._read_database_bytes()
                self._validate_snapshot_pair(
                    staged_manifest, staged_raw, require_anchor=False
                )
            document = self._journal_document(
                old_generation=None,
                new_generation=0,
                staged_database=staged_database,
                staged_seal=staged_seal,
            )
            self._write_prepared_journal(document)
            prepared = True
            self._replace_durable(staged_database, self._path)
            self._replace_durable(staged_seal, self._seal_path)
            manifest = self._read_external_seal()
            final_raw = self._read_database_bytes()
            self._validate_snapshot_pair(manifest, final_raw, require_anchor=False)
            if not self._anchor_cas(None, 0):
                _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                    "durable metadata initialization requires reconciliation"
                ))
            if self._anchor_read() != 0:
                raise GoogleWorkspaceV1UnknownOutcome(
                    "durable metadata initialization anchor confirmation requires reconciliation"
                ) from None
            self._journal_path.unlink()
            self._sync_parent_directory()
            self._verify_generation(manifest)
        except GoogleWorkspaceV1UnknownOutcome:
            raise
        except Exception:
            if prepared:
                _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                    "durable metadata initialization requires reconciliation"
                ))
            raise
        finally:
            if not prepared or not self._journal_path.exists():
                staged_database.unlink(missing_ok=True)
                staged_seal.unlink(missing_ok=True)

    @contextmanager
    def _connection(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        """Open SQLite while translating corrupt containers to a safe denial."""
        try:
            target = (
                f"file:{quote(self._path.as_posix(), safe='/:')}?mode=ro"
                if readonly
                else str(self._path)
            )
            with closing(sqlite3.connect(target, uri=readonly)) as connection:
                yield connection
        except sqlite3.DatabaseError:
            try:
                self._verify_external_seal()
            except GoogleWorkspaceV1Denied as seal_error:
                _raise_clean(seal_error)
            _raise_clean(GoogleWorkspaceV1Denied(
                "durable metadata sqlite container is unreadable"
            ))

    def _mac(self, value: object) -> str:
        return hmac.new(self._key, _canonical(value), hashlib.sha256).hexdigest()

    def _mac_domain(self, domain: str, raw: bytes) -> str:
        return hmac.new(
            self._key,
            b"OnyxGoogleMetadata.v3\x00" + domain.encode("ascii") + b"\x00" + raw,
            hashlib.sha256,
        ).hexdigest()

    def _canonical_path(self) -> str:
        value = str(self._path.resolve(strict=False))
        return os.path.normcase(value) if os.name == "nt" else value

    def _anchor_read(self) -> int | None:
        value = _external_port_call(
            lambda: self._anchor.read(self._store_reference),
            GoogleWorkspaceV1UnknownOutcome,
            "durable metadata generation anchor is unavailable",
        )
        if value is not None and (type(value) is not int or value < 0):
            raise GoogleWorkspaceV1UnknownOutcome(
                "durable metadata generation anchor contract drift"
            ) from None
        return value

    def _anchor_cas(self, expected: int | None, replacement: int) -> bool:
        result = _external_port_call(
            lambda: self._anchor.compare_and_swap(
                self._store_reference, expected, replacement
            ),
            GoogleWorkspaceV1UnknownOutcome,
            "durable metadata generation anchor is unavailable",
        )
        if type(result) is not bool:
            raise GoogleWorkspaceV1UnknownOutcome(
                "durable metadata generation anchor contract drift"
            ) from None
        return result

    def _head_hmac(self, sequence: int, head_digest: str) -> str:
        return self._mac(
            {
                "schema": self._SCHEMA,
                "sequence": sequence,
                "head_digest": head_digest,
            }
        )

    @staticmethod
    def _normalize_sql(value: object) -> str:
        if type(value) is not str:
            raise GoogleWorkspaceV1Denied("sqlite_master SQL is absent")
        return " ".join(value.split())

    def _sidecar_paths(self) -> tuple[Path, ...]:
        return tuple(
            Path(f"{self._path}{suffix}")
            for suffix in ("-wal", "-shm", "-journal")
        )

    def _read_database_bytes(self) -> bytes:
        return self._read_regular_file(
            self._path, maximum=MAX_METADATA_DB_BYTES, label="database"
        )

    def _read_regular_file(self, path: Path, *, maximum: int, label: str) -> bytes:
        descriptor: int | None = None
        try:
            metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_nlink != 1
            ):
                raise GoogleWorkspaceV1Denied(
                    f"durable metadata {label} is not a single-link regular file"
                )
            attributes = getattr(metadata, "st_file_attributes", 0)
            if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise GoogleWorkspaceV1Denied(
                    f"durable metadata {label} reparse point is forbidden"
                )
            flags = (
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_BINARY", 0)
            )
            descriptor = os.open(path, flags)
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise GoogleWorkspaceV1Denied(
                    f"durable metadata {label} hardlink is forbidden"
                )
            size = before.st_size
            if not 1 <= size <= maximum:
                raise GoogleWorkspaceV1Denied(
                    f"durable metadata {label} size is outside its bound"
                )
            chunks: list[bytes] = []
            remaining = size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1_048_576))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            path_after = path.lstat()
            value = b"".join(chunks)
        except GoogleWorkspaceV1Denied:
            raise
        except OSError:
            _raise_clean(GoogleWorkspaceV1Denied(
                f"durable metadata {label} is unavailable"
            ))
        finally:
            if descriptor is not None:
                os.close(descriptor)
        identity_before = (
            before.st_dev, before.st_ino, before.st_size
        )
        identity_after = (
            after.st_dev, after.st_ino, after.st_size
        )
        path_identity_before = (metadata.st_dev, metadata.st_ino, metadata.st_size)
        path_identity_after = (
            path_after.st_dev, path_after.st_ino, path_after.st_size
        )
        if (
            len(value) != size
            or identity_before != identity_after
            or identity_before != path_identity_before
            or identity_after != path_identity_after
            or path_after.st_nlink != 1
            or not stat.S_ISREG(path_after.st_mode)
            or stat.S_ISLNK(path_after.st_mode)
        ):
            raise GoogleWorkspaceV1Denied(
                f"durable metadata {label} changed while read"
            )
        return value

    def _file_payload(
        self,
        raw: bytes,
        *,
        generation: int,
        page_count: int,
        page_size: int,
        freelist_count: int,
    ) -> dict[str, object]:
        return {
            "schema": self._SEAL_SCHEMA,
            "store_reference": self._store_reference,
            "generation": generation,
            "file_length": len(raw),
            "page_count": page_count,
            "page_size": page_size,
            "freelist_count": freelist_count,
            "file_sha256": _sha(raw),
            "file_hmac": hmac.new(self._key, raw, hashlib.sha256).hexdigest(),
        }

    def _read_external_seal(self) -> dict[str, object]:
        """Return an authenticated, structurally valid external manifest.

        This intentionally does not compare the manifest with the current
        database bytes.  Callers verify the authenticated SQLite contents
        first, then use ``_verify_external_seal`` against the closed final
        container.  Consequently row/head/schema corruption retains its exact
        fail-closed error while appended bytes and other container-only drift
        are still rejected before any metadata is returned.
        """
        if any(path.exists() for path in self._sidecar_paths()):
            raise GoogleWorkspaceV1Denied(
                "durable metadata has an unexpected journal sidecar"
            )
        seal_raw = self._read_regular_file(
            self._seal_path, maximum=MAX_METADATA_SEAL_BYTES, label="file seal"
        )
        try:
            document = json.loads(seal_raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _raise_clean(GoogleWorkspaceV1Denied(
                "durable metadata file seal is corrupt"
            ))
        expected_keys = {
            "schema",
            "store_reference",
            "generation",
            "file_length",
            "page_count",
            "page_size",
            "freelist_count",
            "file_sha256",
            "file_hmac",
            "manifest_hmac",
        }
        if type(document) is not dict or set(document) != expected_keys:
            raise GoogleWorkspaceV1Denied("durable metadata file seal schema drift")
        manifest_hmac = document.pop("manifest_hmac")
        if (
            type(manifest_hmac) is not str
            or _DIGEST.fullmatch(manifest_hmac) is None
            or not hmac.compare_digest(manifest_hmac, self._mac(document))
        ):
            raise GoogleWorkspaceV1Denied(
                "durable metadata file seal authentication failed"
            )
        for field in (
            "generation", "file_length", "page_count", "page_size", "freelist_count"
        ):
            if type(document[field]) is not int or document[field] < 0:
                raise GoogleWorkspaceV1Denied(
                    "durable metadata file seal numeric drift"
                )
        if (
            document["schema"] != self._SEAL_SCHEMA
            or type(document["store_reference"]) is not str
            or _DIGEST.fullmatch(document["store_reference"]) is None
            or not hmac.compare_digest(document["store_reference"], self._store_reference)
            or type(document["file_sha256"]) is not str
            or _DIGEST.fullmatch(document["file_sha256"]) is None
            or type(document["file_hmac"]) is not str
            or _DIGEST.fullmatch(document["file_hmac"]) is None
            or document["file_length"] <= 0
            or document["page_count"] <= 0
            or document["page_size"]
            not in {512, 1024, 2048, 4096, 8192, 16384, 32768, 65536}
            or not 0 <= document["freelist_count"] <= document["page_count"]
            or document["file_length"]
            != document["page_count"] * document["page_size"]
        ):
            raise GoogleWorkspaceV1Denied("durable metadata file seal drift")
        return document

    def _verify_external_seal(self) -> dict[str, object]:
        document = self._read_external_seal()
        raw = self._read_database_bytes()
        self._verify_snapshot_bytes(document, raw)
        return document

    def _verify_snapshot_bytes(
        self, document: Mapping[str, object], raw: bytes
    ) -> None:
        if (
            document["file_length"] != len(raw)
            or document["file_sha256"] != _sha(raw)
            or not hmac.compare_digest(
                document["file_hmac"],
                hmac.new(self._key, raw, hashlib.sha256).hexdigest(),
            )
        ):
            raise GoogleWorkspaceV1Denied(
                "durable metadata file container authentication failed"
            )

    def _validate_snapshot_pair(
        self,
        document: Mapping[str, object],
        raw: bytes,
        *,
        require_anchor: bool,
    ) -> tuple[tuple[object, ...], ...]:
        if not raw.startswith(b"SQLite format 3\x00"):
            self._verify_snapshot_bytes(document, raw)
            _raise_clean(GoogleWorkspaceV1Denied(
                "durable metadata sqlite snapshot is unreadable"
            ))
        try:
            with closing(sqlite3.connect(":memory:")) as connection:
                if not callable(getattr(connection, "deserialize", None)):
                    raise GoogleWorkspaceV1Denied(
                        "durable metadata snapshot validation is unavailable"
                    )
                connection.deserialize(raw)
                connection.execute("PRAGMA query_only=ON")
                rows = self._verify(connection)
                self._verify_container(connection, document, snapshot=True)
                head_generation = connection.execute(
                    "SELECT sequence FROM google_grant_head_v1 WHERE singleton = 1"
                ).fetchone()[0]
        except sqlite3.DatabaseError:
            _raise_clean(GoogleWorkspaceV1Denied(
                "durable metadata sqlite snapshot is unreadable"
            ))
        generation = document["generation"]
        if len(raw) < 100 or raw[18:20] != b"\x01\x01":
            raise GoogleWorkspaceV1Denied(
                "durable metadata snapshot journal mode drift"
            ) from None
        if type(generation) is not int or head_generation != generation:
            raise GoogleWorkspaceV1Denied(
                "durable metadata head and seal generation drift"
            ) from None
        self._verify_snapshot_bytes(document, raw)
        if require_anchor and self._anchor_read() != generation:
            raise GoogleWorkspaceV1Denied(
                "durable metadata generation anchor drift"
            ) from None
        return rows

    def _write_external_seal(
        self, container: tuple[int, int, int], *, generation: int
    ) -> None:
        if any(path.exists() for path in self._sidecar_paths()):
            raise GoogleWorkspaceV1Denied(
                "durable metadata cannot seal with a journal sidecar"
            )
        raw = self._read_database_bytes()
        page_count, page_size, freelist_count = container
        if len(raw) != page_count * page_size:
            raise GoogleWorkspaceV1Denied(
                "durable metadata physical page boundary drift"
            )
        payload = self._file_payload(
            raw,
            generation=generation,
            page_count=page_count,
            page_size=page_size,
            freelist_count=freelist_count,
        )
        document = dict(payload)
        document["manifest_hmac"] = self._mac(payload)
        encoded = _canonical(document)
        temporary = self._seal_path.with_name(
            f"{self._seal_path.name}.tmp-{secrets.token_hex(12)}"
        )
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            view = memoryview(encoded)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise OSError("short seal write")
                written += count
            self._flush_descriptor(descriptor)
            os.close(descriptor)
            descriptor = None
            self._atomic_replace(temporary, self._seal_path)
            self._sync_parent_directory()
            if self._read_regular_file(
                self._seal_path,
                maximum=MAX_METADATA_SEAL_BYTES,
                label="file seal",
            ) != encoded:
                raise OSError("seal publication revalidation failed")
        except OSError:
            _raise_clean(GoogleWorkspaceV1Denied(
                "durable metadata file seal update failed"
            ))
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _sync_parent_directory(self) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(self._path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _flush_descriptor(descriptor: int) -> None:
        if os.name != "nt":
            os.fsync(descriptor)
            return
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(descriptor)
        if not ctypes.windll.kernel32.FlushFileBuffers(handle):
            raise OSError(ctypes.get_last_error(), "FlushFileBuffers failed")

    @staticmethod
    def _atomic_replace(source: Path, destination: Path) -> None:
        for candidate, required in ((source, True), (destination, False)):
            if not candidate.exists():
                if required:
                    raise OSError("durable replacement source is unavailable")
                continue
            metadata = candidate.lstat()
            attributes = getattr(metadata, "st_file_attributes", 0)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_nlink != 1
                or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise OSError("durable replacement hardlink or reparse point")
        if os.name != "nt":
            os.replace(source, destination)
            return
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel32.MoveFileExW
        move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        move.restype = wintypes.BOOL
        result = move(str(source), str(destination), 0x1 | 0x8)
        if not result:
            error = ctypes.get_last_error()
            raise OSError(error, "durable Windows replacement failed")

    def _verify_generation(self, manifest: Mapping[str, object]) -> int:
        generation = manifest["generation"]
        head = self._anchor_read()
        if type(generation) is not int or generation < 0 or head != generation:
            raise GoogleWorkspaceV1Denied(
                "durable metadata generation anchor drift"
            ) from None
        return generation

    @contextmanager
    def _using_paths(self, database: Path, seal: Path) -> Iterator[None]:
        original_database, original_seal = self._path, self._seal_path
        self._path, self._seal_path = database, seal
        try:
            yield
        finally:
            self._path, self._seal_path = original_database, original_seal

    def _write_file_durable(self, path: Path, raw: bytes) -> None:
        descriptor: int | None = None
        temporary = path.with_name(f"{path.name}.tmp-{secrets.token_hex(12)}")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0),
                0o600,
            )
            view = memoryview(raw)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise OSError("short durable write")
                written += count
            self._flush_descriptor(descriptor)
            os.close(descriptor)
            descriptor = None
            self._atomic_replace(temporary, path)
            self._sync_parent_directory()
            if self._read_regular_file(
                path, maximum=max(len(raw), 1), label="durable publication"
            ) != raw:
                raise OSError("durable publication revalidation failed")
        except OSError:
            _raise_clean(
                GoogleWorkspaceV1Denied("durable metadata publication failed")
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def _journal_document(
        self,
        *,
        old_generation: int | None,
        new_generation: int,
        staged_database: Path,
        staged_seal: Path,
    ) -> dict[str, object]:
        database_raw = self._read_regular_file(
            staged_database,
            maximum=MAX_METADATA_DB_BYTES,
            label="prepared database stage",
        )
        seal_raw = self._read_regular_file(
            staged_seal,
            maximum=MAX_METADATA_SEAL_BYTES,
            label="prepared seal stage",
        )
        payload: dict[str, object] = {
            "schema": self._JOURNAL_SCHEMA,
            "store_reference": self._store_reference,
            "old_generation": old_generation,
            "new_generation": new_generation,
            "staged_database": staged_database.name,
            "staged_seal": staged_seal.name,
            "database_hmac": self._mac_domain("prepared-database", database_raw),
            "seal_hmac": self._mac_domain("prepared-seal", seal_raw),
        }
        payload["journal_hmac"] = self._mac_domain("prepared-journal", _canonical(payload))
        return payload

    def _write_prepared_journal(self, document: Mapping[str, object]) -> None:
        self._write_file_durable(self._journal_path, _canonical(dict(document)))

    def _read_prepared_journal(self) -> dict[str, object]:
        try:
            raw = self._read_regular_file(
                self._journal_path,
                maximum=MAX_METADATA_JOURNAL_BYTES,
                label="prepared journal",
            )
            document = json.loads(raw.decode("ascii"))
        except (GoogleWorkspaceV1Denied, UnicodeDecodeError, json.JSONDecodeError):
            _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                "durable metadata journal requires reconciliation"
            ))
        expected = {
            "schema", "store_reference", "old_generation", "new_generation",
            "staged_database", "staged_seal", "database_hmac", "seal_hmac",
            "journal_hmac",
        }
        if type(document) is not dict or set(document) != expected:
            raise GoogleWorkspaceV1UnknownOutcome(
                "durable metadata journal requires reconciliation"
            ) from None
        journal_hmac = document.pop("journal_hmac")
        if (
            type(journal_hmac) is not str
            or not hmac.compare_digest(
                journal_hmac,
                self._mac_domain("prepared-journal", _canonical(document)),
            )
            or document["schema"] != self._JOURNAL_SCHEMA
            or document["store_reference"] != self._store_reference
            or type(document["new_generation"]) is not int
            or document["new_generation"] < 0
            or document["old_generation"] not in {None, document["new_generation"] - 1}
        ):
            raise GoogleWorkspaceV1UnknownOutcome(
                "durable metadata journal authentication requires reconciliation"
            ) from None
        document["journal_hmac"] = journal_hmac
        return document

    def _matches_prepared(self, path: Path, domain: str, expected: object) -> bool:
        if type(expected) is not str or not path.is_file():
            return False
        try:
            maximum = (
                MAX_METADATA_DB_BYTES
                if domain == "prepared-database"
                else MAX_METADATA_SEAL_BYTES
            )
            actual = self._mac_domain(
                domain,
                self._read_regular_file(path, maximum=maximum, label="prepared stage"),
            )
        except GoogleWorkspaceV1Denied:
            return False
        return hmac.compare_digest(expected, actual)

    def _replace_durable(self, source: Path, destination: Path) -> None:
        try:
            maximum = (
                MAX_METADATA_SEAL_BYTES
                if source.name.endswith(".seal")
                else MAX_METADATA_DB_BYTES
            )
            expected = self._read_regular_file(
                source, maximum=maximum, label="prepared publication"
            )
            self._atomic_replace(source, destination)
            self._sync_parent_directory()
            if self._read_regular_file(
                destination, maximum=maximum, label="published artifact"
            ) != expected:
                raise OSError("published artifact revalidation failed")
        except (OSError, GoogleWorkspaceV1Denied):
            _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                "durable metadata publication requires reconciliation"
            ))

    def _recover_prepared(self) -> None:
        if not self._journal_path.exists():
            return
        document = self._read_prepared_journal()
        staged_database = self._path.parent / str(document["staged_database"])
        staged_seal = self._path.parent / str(document["staged_seal"])
        stage_pattern = re.compile(
            rf"{re.escape(self._path.name)}\.stage-[0-9a-f]{{24}}\Z"
        )
        if (
            staged_database.parent != self._path.parent
            or staged_seal.parent != self._path.parent
            or stage_pattern.fullmatch(staged_database.name) is None
            or staged_seal.name != f"{staged_database.name}.seal"
        ):
            raise GoogleWorkspaceV1UnknownOutcome(
                "durable metadata journal path requires reconciliation"
            ) from None
        old = document["old_generation"]
        new = document["new_generation"]
        anchor = self._anchor_read()
        if anchor not in {old, new}:
            raise GoogleWorkspaceV1UnknownOutcome(
                "durable metadata journal is older than trusted authority"
            ) from None
        db_matches = self._matches_prepared(
            self._path, "prepared-database", document["database_hmac"]
        )
        if not db_matches:
            if not self._matches_prepared(
                staged_database, "prepared-database", document["database_hmac"]
            ):
                raise GoogleWorkspaceV1UnknownOutcome(
                    "durable metadata database recovery requires reconciliation"
                ) from None
            self._replace_durable(staged_database, self._path)
        seal_matches = self._matches_prepared(
            self._seal_path, "prepared-seal", document["seal_hmac"]
        )
        if not seal_matches:
            if not self._matches_prepared(
                staged_seal, "prepared-seal", document["seal_hmac"]
            ):
                raise GoogleWorkspaceV1UnknownOutcome(
                    "durable metadata seal recovery requires reconciliation"
                ) from None
            self._replace_durable(staged_seal, self._seal_path)
        manifest = self._read_external_seal()
        raw = self._read_database_bytes()
        self._validate_snapshot_pair(manifest, raw, require_anchor=False)
        if manifest["generation"] != document["new_generation"]:
            raise GoogleWorkspaceV1UnknownOutcome(
                "durable metadata generation recovery requires reconciliation"
            ) from None
        if anchor != new and not self._anchor_cas(old, new):
            raise GoogleWorkspaceV1UnknownOutcome(
                "durable metadata anchor recovery requires reconciliation"
            ) from None
        if self._anchor_read() != new:
            raise GoogleWorkspaceV1UnknownOutcome(
                "durable metadata anchor recovery confirmation requires reconciliation"
            ) from None
        self._journal_path.unlink()
        self._sync_parent_directory()
        staged_database.unlink(missing_ok=True)
        staged_seal.unlink(missing_ok=True)

    def _verify_container(
        self,
        connection: sqlite3.Connection,
        manifest: Mapping[str, object] | None,
        *,
        snapshot: bool = False,
    ) -> tuple[int, int, int]:
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        journal_mode = str(
            connection.execute("PRAGMA journal_mode").fetchone()[0]
        ).casefold()
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        freelist_count = connection.execute("PRAGMA freelist_count").fetchone()[0]
        if (
            application_id != self._APPLICATION_ID
            or user_version != self._USER_VERSION
            or (not snapshot and journal_mode != "delete")
            or type(page_count) is not int
            or page_count <= 0
            or type(page_size) is not int
            or page_size not in {512, 1024, 2048, 4096, 8192, 16384, 32768, 65536}
            or type(freelist_count) is not int
            or not 0 <= freelist_count <= page_count
        ):
            raise GoogleWorkspaceV1Denied(
                "durable metadata physical container drift"
            )
        if manifest is not None and (
            manifest["page_count"] != page_count
            or manifest["page_size"] != page_size
            or manifest["freelist_count"] != freelist_count
        ):
            raise GoogleWorkspaceV1Denied(
                "durable metadata physical seal drift"
            )
        return page_count, page_size, freelist_count

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        grant_schema = tuple(
            tuple(row)
            for row in connection.execute(
                "PRAGMA table_info(google_grants_v1)"
            ).fetchall()
        )
        head_schema = tuple(
            tuple(row)
            for row in connection.execute(
                "PRAGMA table_info(google_grant_head_v1)"
            ).fetchall()
        )
        if (
            grant_schema != self._GRANT_SCHEMA_INFO
            or head_schema != self._HEAD_SCHEMA_INFO
        ):
            raise GoogleWorkspaceV1Denied("durable metadata schema drift")
        objects = tuple(
            (
                row[0],
                row[1],
                row[2],
                self._normalize_sql(row[3]),
            )
            for row in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "ORDER BY type, name"
            ).fetchall()
        )
        if objects != self._EXPECTED_OBJECTS:
            raise GoogleWorkspaceV1Denied(
                "durable metadata sqlite_master object-set drift"
            )

    @staticmethod
    def _row_payload(row: tuple[object, ...]) -> dict[str, object]:
        return {
            "binding_digest": row[0],
            "owner_digest": row[1],
            "workspace_digest": row[2],
            "account_digest": row[3],
            "scopes_json": row[4],
            "access_expires_at_epoch_s": row[5],
            "grant_digest": row[6],
            "provider_state": row[7],
            "updated_at_epoch_s": row[8],
            "sequence": row[9],
        }

    def _verify(
        self, connection: sqlite3.Connection
    ) -> tuple[tuple[object, ...], ...]:
        self._verify_schema(connection)
        heads = connection.execute(
            "SELECT schema_name, sequence, head_digest, head_hmac "
            "FROM google_grant_head_v1"
        ).fetchall()
        if len(heads) != 1:
            raise GoogleWorkspaceV1Denied("durable metadata head cardinality drift")
        schema_name, sequence, head_digest, head_hmac = heads[0]
        if (
            schema_name != self._SCHEMA
            or type(sequence) is not int
            or sequence < 0
            or type(head_digest) is not str
            or _DIGEST.fullmatch(head_digest) is None
            or type(head_hmac) is not str
            or _DIGEST.fullmatch(head_hmac) is None
            or not hmac.compare_digest(head_hmac, self._head_hmac(sequence, head_digest))
        ):
            raise GoogleWorkspaceV1Denied("durable metadata head authentication failed")
        rows = tuple(
            connection.execute(
                "SELECT binding_digest, owner_digest, workspace_digest, "
                "account_digest, scopes_json, access_expires_at_epoch_s, "
                "grant_digest, provider_state, updated_at_epoch_s, sequence, "
                "row_hmac FROM google_grants_v1 ORDER BY binding_digest"
            ).fetchall()
        )
        if len(rows) > 1024:
            raise GoogleWorkspaceV1Denied("durable metadata row budget exceeded")
        authenticated: list[str] = []
        for row in rows:
            if (
                len(row) != len(self._GRANT_COLUMNS)
                or type(row[9]) is not int
                or not 1 <= row[9] <= sequence
                or type(row[10]) is not str
                or _DIGEST.fullmatch(row[10]) is None
                or not hmac.compare_digest(row[10], self._mac(self._row_payload(row)))
            ):
                raise GoogleWorkspaceV1Denied("durable metadata row authentication failed")
            try:
                scopes = tuple(json.loads(row[4]))
                GoogleGrantMetadataV1(
                    row[0], row[1], row[2], row[3], scopes,
                    row[5], row[6], row[7], row[8],
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                _raise_clean(
                    GoogleWorkspaceV1Denied("durable metadata row is corrupt")
                )
            authenticated.append(_sha({"payload": self._row_payload(row), "row_hmac": row[10]}))
        computed_head = _sha(authenticated)
        if not hmac.compare_digest(computed_head, head_digest):
            raise GoogleWorkspaceV1Denied("durable metadata set authentication failed")
        return rows

    def get(self, binding_digest: str) -> GoogleGrantMetadataV1 | None:
        if type(binding_digest) is not str or _DIGEST.fullmatch(binding_digest) is None:
            raise GoogleWorkspaceV1ContractError("binding digest is invalid")
        with self._lock, _exclusive_file_lock(self._lock_path):
            self._recover_prepared()
            manifest = self._read_external_seal()
            raw = self._read_database_bytes()
            rows = self._validate_snapshot_pair(
                manifest, raw, require_anchor=True
            )
            row = next((item for item in rows if item[0] == binding_digest), None)
            final_manifest = self._read_external_seal()
            final_raw = self._read_database_bytes()
            if final_manifest != manifest or final_raw != raw:
                raise GoogleWorkspaceV1UnknownOutcome(
                    "durable metadata changed during snapshot read"
                ) from None
            self._validate_snapshot_pair(
                final_manifest, final_raw, require_anchor=True
            )
        if row is None:
            return None
        try:
            scopes = tuple(json.loads(row[4]))
            return GoogleGrantMetadataV1(
                row[0], row[1], row[2], row[3], scopes, row[5], row[6], row[7], row[8]
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            _raise_clean(
                GoogleWorkspaceV1Denied("durable grant metadata is corrupt")
            )

    def put(self, value: GoogleGrantMetadataV1) -> None:
        if type(value) is not GoogleGrantMetadataV1:
            raise GoogleWorkspaceV1ContractError("metadata value is invalid")
        scopes_json = _canonical(value.scopes).decode("ascii")
        with self._lock, _exclusive_file_lock(self._lock_path):
            self._recover_prepared()
            current_manifest = self._read_external_seal()
            authenticated_raw = self._read_database_bytes()
            self._validate_snapshot_pair(
                current_manifest, authenticated_raw, require_anchor=True
            )
            current_generation = current_manifest["generation"]
            staged_database = self._path.with_name(
                f"{self._path.name}.stage-{secrets.token_hex(12)}"
            )
            staged_seal = staged_database.with_name(f"{staged_database.name}.seal")
            prepared = False
            try:
                self._write_file_durable(staged_database, authenticated_raw)
                staged_copy = self._read_regular_file(
                    staged_database,
                    maximum=MAX_METADATA_DB_BYTES,
                    label="prepared database stage",
                )
                if (
                    staged_copy != authenticated_raw
                    or self._read_database_bytes() != authenticated_raw
                ):
                    raise GoogleWorkspaceV1Denied(
                        "durable metadata source snapshot changed before mutation"
                    ) from None
                with self._using_paths(staged_database, staged_seal):
                    with self._connection() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        self._verify(connection)
                        current_sequence = connection.execute(
                            "SELECT sequence FROM google_grant_head_v1 WHERE singleton = 1"
                        ).fetchone()[0]
                        sequence = current_sequence + 1
                        base = (
                            value.binding_digest, value.owner_digest,
                            value.workspace_digest, value.account_digest,
                            scopes_json, value.access_expires_at_epoch_s,
                            value.grant_digest, value.provider_state,
                            value.updated_at_epoch_s, sequence,
                        )
                        row_hmac = self._mac(self._row_payload((*base, "")))
                        connection.execute(
                            "INSERT OR REPLACE INTO google_grants_v1 VALUES "
                            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (*base, row_hmac),
                        )
                        rows = tuple(connection.execute(
                            "SELECT binding_digest, owner_digest, workspace_digest, "
                            "account_digest, scopes_json, access_expires_at_epoch_s, "
                            "grant_digest, provider_state, updated_at_epoch_s, sequence, "
                            "row_hmac FROM google_grants_v1 ORDER BY binding_digest"
                        ).fetchall())
                        head_digest = _sha([
                            _sha({"payload": self._row_payload(row), "row_hmac": row[10]})
                            for row in rows
                        ])
                        connection.execute(
                            "UPDATE google_grant_head_v1 SET sequence = ?, head_digest = ?, "
                            "head_hmac = ? WHERE singleton = 1",
                            (sequence, head_digest, self._head_hmac(sequence, head_digest)),
                        )
                        self._verify(connection)
                        connection.commit()
                        container = self._verify_container(connection, None)
                    self._write_external_seal(
                        container, generation=current_generation + 1
                    )
                    staged_manifest = self._read_external_seal()
                    staged_raw = self._read_database_bytes()
                    self._validate_snapshot_pair(
                        staged_manifest, staged_raw, require_anchor=False
                    )
                    if staged_manifest["generation"] != current_generation + 1:
                        raise GoogleWorkspaceV1Denied(
                            "durable metadata staged generation drift"
                        )
                document = self._journal_document(
                    old_generation=current_generation,
                    new_generation=current_generation + 1,
                    staged_database=staged_database,
                    staged_seal=staged_seal,
                )
                self._write_prepared_journal(document)
                prepared = True
                self._replace_durable(staged_database, self._path)
                self._replace_durable(staged_seal, self._seal_path)
                final_manifest = self._read_external_seal()
                final_raw = self._read_database_bytes()
                self._validate_snapshot_pair(
                    final_manifest, final_raw, require_anchor=False
                )
                if final_manifest["generation"] != current_generation + 1:
                    raise GoogleWorkspaceV1UnknownOutcome(
                        "durable metadata publication requires reconciliation"
                    ) from None
                if not self._anchor_cas(current_generation, current_generation + 1):
                    raise GoogleWorkspaceV1UnknownOutcome(
                        "durable metadata anchor update requires reconciliation"
                    ) from None
                if self._anchor_read() != current_generation + 1:
                    raise GoogleWorkspaceV1UnknownOutcome(
                        "durable metadata anchor confirmation requires reconciliation"
                    ) from None
                self._journal_path.unlink()
                self._sync_parent_directory()
            except GoogleWorkspaceV1UnknownOutcome:
                raise
            except Exception:
                if prepared:
                    _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                        "durable metadata mutation requires reconciliation"
                    ))
                raise
            finally:
                if not prepared or not self._journal_path.exists():
                    staged_database.unlink(missing_ok=True)
                    staged_seal.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True, repr=False)
class GoogleAuthorizationStartV1:
    authorization_url: str
    expires_at_epoch_s: int
    state_digest: str
    scopes: tuple[str, ...]
    browser_automation: bool = False


@dataclass(frozen=True, slots=True)
class GoogleProviderReceiptV1:
    operation: str
    status: str
    binding_digest: str
    request_digest: str
    response_digest: str
    grant_digest: str
    item_count: int
    page_count: int
    provider_content_included: bool = False
    credentials_included: bool = False


@dataclass(frozen=True, slots=True)
class GoogleReadResultV1:
    items: tuple[dict[str, object], ...]
    has_more: bool
    receipt: GoogleProviderReceiptV1
    provider_content_untrusted: bool = True


@dataclass(frozen=True, slots=True)
class GoogleConnectorStatusV1:
    connected: bool
    provider_state: str
    binding_digest: str
    scopes: tuple[str, ...]
    access_expires_at_epoch_s: int | None
    grant_digest: str
    raw_tokens_included: bool = False


class GoogleWorkspaceConnectorV1:
    """Synchronous, bounded, GET-only Google Workspace connector."""

    def __init__(
        self,
        *,
        gate: GoogleWorkspaceFeatureGateV1,
        settings: GoogleOAuthSettingsV1,
        binding: GoogleWorkspaceBindingV1,
        token_resolver: GoogleTokenResolverV1,
        token_persister: GoogleTokenPersisterV1,
        pending_vault: GooglePendingVaultV1,
        metadata_store: GoogleGrantMetadataStoreV1,
        transport: GoogleHttpTransportV1,
        identity_pseudonymizer: GoogleIdentityPseudonymizerV1,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(gate) is not GoogleWorkspaceFeatureGateV1 or not gate.enabled:
            raise GoogleWorkspaceV1Denied("Google Workspace connector is disabled")
        if type(settings) is not GoogleOAuthSettingsV1:
            raise GoogleWorkspaceV1ContractError("exact OAuth settings required")
        if type(binding) is not GoogleWorkspaceBindingV1:
            raise GoogleWorkspaceV1ContractError("exact workspace binding required")
        for label, capability, methods in (
            ("token resolver", token_resolver, ("resolve",)),
            ("token persister", token_persister, ("compare_and_set", "delete")),
            ("pending vault", pending_vault, ("store", "consume")),
            ("metadata store", metadata_store, ("get", "put")),
            ("transport", transport, ("send",)),
        ):
            if any(not callable(getattr(capability, name, None)) for name in methods):
                raise GoogleWorkspaceV1ContractError(f"{label} capability is invalid")
        self._settings = settings
        self._binding = binding
        self._resolver = token_resolver
        self._persister = token_persister
        self._pending = pending_vault
        self._metadata = metadata_store
        self._transport = transport
        if not callable(getattr(identity_pseudonymizer, "pseudonym", None)):
            raise GoogleWorkspaceV1ContractError(
                "identity pseudonymizer capability is required"
            )
        self._identity = identity_pseudonymizer
        self._binding_digest = self._pseudonym(
            "binding",
            _canonical(
                [binding.owner_id, binding.workspace_id, binding.account_id]
            ).decode("ascii"),
        )
        if not callable(monotonic_clock):
            raise GoogleWorkspaceV1ContractError("monotonic clock is invalid")
        self._clock_capability = monotonic_clock
        self._clock = self._clock_port
        self._lock = threading.RLock()

    def _pseudonym(self, domain: str, value: str) -> str:
        result = _external_port_call(
            lambda: self._identity.pseudonym(domain, value),
            GoogleWorkspaceV1Denied,
            "identity pseudonymization capability failed",
        )
        if (
            type(result) is not str
            or _DIGEST.fullmatch(result) is None
            or result != result.casefold()
        ):
            raise GoogleWorkspaceV1ContractError(
                "identity pseudonymizer contract drift"
            ) from None
        return result

    def _clock_port(self) -> float:
        result = _external_port_call(
            self._clock_capability,
            GoogleWorkspaceV1Denied,
            "monotonic clock capability is unavailable",
        )
        if type(result) not in {int, float} or isinstance(result, bool):
            raise GoogleWorkspaceV1ContractError(
                "monotonic clock capability contract drift"
            )
        return float(result)

    def _resolve_token_port(self) -> object:
        return _external_port_call(
            lambda: self._resolver.resolve(self._binding_digest),
            GoogleWorkspaceV1Denied,
            "token resolver capability is unavailable",
        )

    def _metadata_get_port(self) -> object:
        return _external_port_call(
            lambda: self._metadata.get(self._binding_digest),
            GoogleWorkspaceV1Denied,
            "grant metadata capability is unavailable",
        )

    def _metadata_put_port(self, value: GoogleGrantMetadataV1) -> None:
        result = _external_port_call(
            lambda: self._metadata.put(value),
            GoogleWorkspaceV1UnknownOutcome,
            "grant metadata persistence requires reconciliation",
        )
        if result is not None:
            raise GoogleWorkspaceV1UnknownOutcome(
                "grant metadata persistence contract drift"
            )

    def _pending_store_port(
        self, state_digest: str, value: GooglePendingAuthorizationV1
    ) -> None:
        result = _external_port_call(
            lambda: self._pending.store(state_digest, value),
            GoogleWorkspaceV1UnknownOutcome,
            "pending authorization persistence requires reconciliation",
        )
        if result is not None:
            raise GoogleWorkspaceV1UnknownOutcome(
                "pending authorization persistence contract drift"
            )

    def _pending_consume_port(self, state_digest: str) -> object:
        result = _external_port_call(
            lambda: self._pending.consume(state_digest),
            GoogleWorkspaceV1UnknownOutcome,
            "pending authorization consume requires reconciliation",
        )
        return result

    def _persist_token_port(
        self, expected_digest: str | None, value: GoogleTokenBundleV1
    ) -> object:
        result = _external_port_call(
            lambda: self._persister.compare_and_set(
                self._binding_digest, expected_digest, value
            ),
            GoogleWorkspaceV1UnknownOutcome,
            "token persistence requires reconciliation",
        )
        if type(result) is not bool:
            raise GoogleWorkspaceV1UnknownOutcome(
                "token persistence contract drift"
            )
        return result

    def _delete_token_port(self, expected_digest: str) -> object:
        result = _external_port_call(
            lambda: self._persister.delete(self._binding_digest, expected_digest),
            GoogleWorkspaceV1UnknownOutcome,
            "token deletion requires reconciliation",
        )
        if type(result) is not bool:
            raise GoogleWorkspaceV1UnknownOutcome(
                "token deletion contract drift"
            )
        return result

    def _transport_send_port(self, request: GoogleHttpRequestV1) -> object:
        return _external_port_call(
            lambda: self._transport.send(request),
            GoogleWorkspaceV1UnknownOutcome,
            "Google transport outcome is unknown",
        )

    def _operation_budget(
        self, budget: GoogleWorkspaceBudgetV1 | None
    ) -> _GoogleOperationBudgetV1:
        selected = GoogleWorkspaceBudgetV1() if budget is None else budget
        if type(selected) is not GoogleWorkspaceBudgetV1:
            raise GoogleWorkspaceV1ContractError("exact Google operation budget required")
        return _GoogleOperationBudgetV1.start(selected, self._clock)

    def begin_authorization(self, *, now_epoch_s: int) -> GoogleAuthorizationStartV1:
        _now(now_epoch_s)
        existing = self._resolve_token_port()
        existing_metadata = self._metadata_get_port()
        if existing_metadata is not None:
            if type(existing_metadata) is not GoogleGrantMetadataV1:
                raise GoogleWorkspaceV1Denied("grant metadata contract drift")
            self._validate_metadata_binding(existing_metadata)
            if existing_metadata.provider_state == "attempted_unknown":
                raise GoogleWorkspaceV1Denied(
                    "Google provider state requires reconciliation"
                )
        if existing is not None:
            if type(existing) is not GoogleTokenBundleV1:
                raise GoogleWorkspaceV1Denied("token resolver contract drift")
            raise GoogleWorkspaceV1Denied("Google account is already connected")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        state_digest = _sha(state.encode())
        expires = now_epoch_s + 600
        self._pending_store_port(
            state_digest,
            GooglePendingAuthorizationV1(
                self._binding_digest,
                state,
                verifier,
                self._settings.redirect_uri,
                expires,
                self._settings.scopes,
            ),
        )
        query = (
            ("client_id", self._settings.client_id),
            ("redirect_uri", self._settings.redirect_uri),
            ("response_type", "code"),
            ("scope", " ".join(self._settings.scopes)),
            ("access_type", "offline"),
            ("include_granted_scopes", "false"),
            ("state", state),
            ("code_challenge", challenge),
            ("code_challenge_method", "S256"),
        )
        return GoogleAuthorizationStartV1(
            f"{AUTH_ORIGIN}{AUTH_PATH}?{urlencode(query)}",
            expires,
            state_digest,
            self._settings.scopes,
        )

    def complete_authorization(
        self, callback_uri: str, *, now_epoch_s: int, budget: GoogleWorkspaceBudgetV1 | None = None
    ) -> GoogleProviderReceiptV1:
        _now(now_epoch_s)
        operation = self._operation_budget(budget)
        parsed = urlsplit(_bounded_text(callback_uri, "callback_uri", 4096))
        expected = urlsplit(self._settings.redirect_uri)
        if (
            parsed.scheme != expected.scheme
            or parsed.hostname != expected.hostname
            or parsed.port != expected.port
            or parsed.path != expected.path
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise GoogleWorkspaceV1Denied("OAuth redirect URI drift")
        try:
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            _raise_clean(
                GoogleWorkspaceV1Denied("OAuth callback query is invalid")
            )
        if len(pairs) not in {2, 3} or len({name for name, _ in pairs}) != len(pairs):
            raise GoogleWorkspaceV1Denied("OAuth callback fields are invalid")
        fields = dict(pairs)
        if set(fields) - {"code", "state", "error"} or "state" not in fields:
            raise GoogleWorkspaceV1Denied("OAuth callback fields are forbidden")
        state = _bounded_text(fields["state"], "state", 256)
        pending = self._pending_consume_port(_sha(state.encode()))
        if type(pending) is not GooglePendingAuthorizationV1:
            raise GoogleWorkspaceV1Denied("OAuth state is absent or replayed")
        if (
            not hmac.compare_digest(pending.state, state)
            or not hmac.compare_digest(pending.binding_digest, self._binding_digest)
            or pending.redirect_uri != self._settings.redirect_uri
            or pending.scopes != self._settings.scopes
            or type(now_epoch_s) is not int
            or now_epoch_s > pending.expires_at_epoch_s
        ):
            raise GoogleWorkspaceV1Denied("OAuth state, binding, or expiry drift")
        if "error" in fields:
            raise GoogleWorkspaceV1Denied("OAuth authorization was not granted")
        code = _bounded_text(fields.get("code"), "authorization code", 4096)
        token: GoogleTokenBundleV1 | None = None
        try:
            response = self._send(
                GoogleHttpRequestV1(
                    "POST",
                    OAUTH_ORIGIN,
                    TOKEN_PATH,
                    headers=(("Content-Type", "application/x-www-form-urlencoded"),),
                    form=(
                        ("client_id", self._settings.client_id),
                        ("code", code),
                        ("code_verifier", pending.code_verifier),
                        ("grant_type", "authorization_code"),
                        ("redirect_uri", self._settings.redirect_uri),
                    ),
                ),
                operation,
            )
            token = self._token_from_response(response, now_epoch_s, generation=1)
            self._verify_profile(token, operation)
        except GoogleWorkspaceV1UnknownOutcome:
            self._metadata_put_port(
                self._attempted_unknown_metadata(
                    pending.binding_digest,
                    now_epoch_s,
                    pending.expires_at_epoch_s,
                )
            )
            raise
        except GoogleWorkspaceV1Denied:
            if token is None:
                raise
            try:
                self._best_effort_revoke(token.refresh_token, operation)
            except (GoogleWorkspaceV1UnknownOutcome, GoogleWorkspaceV1Denied):
                self._metadata_put_port(
                    self._attempted_unknown_metadata(
                        pending.binding_digest,
                        now_epoch_s,
                        pending.expires_at_epoch_s,
                    )
                )
                _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                    "Google authorization cleanup requires reconciliation"
                ))
            raise
        if self._persist_token_port(None, token) is not True:
            self._metadata_put_port(
                self._attempted_unknown_metadata(
                    token.digest, now_epoch_s, token.access_expires_at_epoch_s
                )
            )
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google authorization token persistence requires reconciliation"
            )
        metadata = self._connected_metadata(token, now_epoch_s)
        self._metadata_put_port(metadata)
        return self._receipt("authorize", "connected", token.digest, response.payload, 0, 1)

    def status(self) -> GoogleConnectorStatusV1:
        token = self._resolve_token_port()
        metadata = self._metadata_get_port()
        if token is not None and type(token) is not GoogleTokenBundleV1:
            raise GoogleWorkspaceV1Denied("token resolver contract drift")
        if metadata is None:
            return GoogleConnectorStatusV1(False, "disconnected", self._binding_digest, (), None, "")
        self._validate_metadata_binding(metadata)
        connected = (
            token is not None
            and token.binding_digest == self._binding_digest
            and token.scopes == READ_SCOPES
            and metadata.provider_state == "connected"
            and hmac.compare_digest(metadata.grant_digest, token.digest)
        )
        return GoogleConnectorStatusV1(
            connected,
            metadata.provider_state,
            self._binding_digest,
            metadata.scopes,
            metadata.access_expires_at_epoch_s,
            metadata.grant_digest,
        )

    def revoke(
        self, *, now_epoch_s: int, budget: GoogleWorkspaceBudgetV1 | None = None
    ) -> GoogleProviderReceiptV1:
        _now(now_epoch_s)
        operation = self._operation_budget(budget)
        with self._lock:
            token = self._bound_token()
            try:
                response = self._send(
                    GoogleHttpRequestV1(
                        "POST",
                        OAUTH_ORIGIN,
                        REVOKE_PATH,
                        headers=(("Content-Type", "application/x-www-form-urlencoded"),),
                        form=(("token", token.refresh_token),),
                    ),
                    operation,
                )
                if response.status_code != 200 or response.payload:
                    raise GoogleWorkspaceV1UnknownOutcome(
                        "Google revocation response requires reconciliation"
                    )
                self._require_same_token_after_dispatch(token)
            except GoogleWorkspaceV1UnknownOutcome:
                self._metadata_put_port(self._state_metadata(token, "attempted_unknown", now_epoch_s))
                raise
            if self._delete_token_port(token.digest) is not True:
                self._metadata_put_port(self._state_metadata(token, "attempted_unknown", now_epoch_s))
                raise GoogleWorkspaceV1UnknownOutcome(
                    "revoked token removal requires reconciliation"
                )
            self._metadata_put_port(self._state_metadata(token, "revoked", now_epoch_s))
            return self._receipt("revoke", "revoked", token.digest, response.payload, 0, 1)

    def list_gmail_messages(
        self,
        *,
        query: str = "is:unread",
        now_epoch_s: int,
        budget: GoogleWorkspaceBudgetV1 | None = None,
    ) -> GoogleReadResultV1:
        _now(now_epoch_s)
        operation = self._operation_budget(budget)
        query = _bounded_text(query, "Gmail query", MAX_QUERY_BYTES)
        return self._paginate(
            operation="gmail_list",
            origin=GMAIL_ORIGIN,
            path=GMAIL_MESSAGES_PATH,
            item_field="messages",
            base_query=(
                ("q", query),
                ("maxResults", str(min(100, operation.policy.maximum_results))),
            ),
            now_epoch_s=now_epoch_s,
            budget=operation,
            projection=self._gmail_projection,
        )

    def list_calendar_events(
        self,
        *,
        time_min: str,
        time_max: str,
        now_epoch_s: int,
        budget: GoogleWorkspaceBudgetV1 | None = None,
    ) -> GoogleReadResultV1:
        _now(now_epoch_s)
        operation = self._operation_budget(budget)
        time_min = _bounded_text(time_min, "time_min", 64)
        time_max = _bounded_text(time_max, "time_max", 64)
        parsed_min = _rfc3339_datetime(time_min, "time_min")
        parsed_max = _rfc3339_datetime(time_max, "time_max")
        if parsed_min >= parsed_max:
            raise GoogleWorkspaceV1ContractError("calendar window is invalid")
        return self._paginate(
            operation="calendar_list",
            origin=CALENDAR_ORIGIN,
            path=CALENDAR_EVENTS_PATH,
            item_field="items",
            base_query=(
                ("timeMin", time_min),
                ("timeMax", time_max),
                ("singleEvents", "true"),
                ("orderBy", "startTime"),
                ("showDeleted", "false"),
                ("maxResults", str(min(250, operation.policy.maximum_results))),
            ),
            now_epoch_s=now_epoch_s,
            budget=operation,
            projection=self._calendar_projection,
        )

    def _paginate(self, *, operation, origin, path, item_field, base_query, now_epoch_s, budget, projection):
        token = self._fresh_token(now_epoch_s, budget)
        items: list[dict[str, object]] = []
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        seen_item_ids: set[str] = set()
        response_digests: list[str] = []
        pages = 0
        truncated = False
        policy = budget.policy
        while pages < policy.maximum_pages and len(items) < policy.maximum_results:
            current = self._bound_token()
            if not hmac.compare_digest(current.digest, token.digest):
                raise GoogleWorkspaceV1Denied("token vault changed before API dispatch")
            query = list(base_query)
            if page_token is not None:
                query.append(("pageToken", page_token))
            try:
                response = self._send(
                    GoogleHttpRequestV1(
                        "GET",
                        origin,
                        path,
                        query=tuple(query),
                        headers=(("Authorization", f"Bearer {token.access_token}"),),
                    ),
                    budget,
                )
                if response.status_code != 200:
                    raise GoogleWorkspaceV1UnknownOutcome(
                        "Google read response requires reconciliation"
                    )
                raw_items = response.payload.get(item_field, [])
                if type(raw_items) is not list or len(raw_items) > policy.maximum_results:
                    raise GoogleWorkspaceV1UnknownOutcome(
                        "Google result schema requires reconciliation"
                    )
                page_items: list[dict[str, object]] = []
                for raw in raw_items:
                    try:
                        projected = projection(raw)
                    except (GoogleWorkspaceV1Denied, GoogleWorkspaceV1ContractError):
                        _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                            "Google item schema requires reconciliation"
                        ))
                    item_id = projected.get("id")
                    if type(item_id) is not str:
                        raise GoogleWorkspaceV1UnknownOutcome(
                            "Google item identity requires reconciliation"
                        )
                    item_digest = _sha(item_id.encode())
                    if item_digest in seen_item_ids:
                        raise GoogleWorkspaceV1UnknownOutcome(
                            "Google duplicate item replay requires reconciliation"
                        )
                    seen_item_ids.add(item_digest)
                    page_items.append(projected)
                candidate = response.payload.get("nextPageToken")
                if candidate is not None:
                    if type(candidate) is not str or _PAGE_TOKEN.fullmatch(candidate) is None:
                        raise GoogleWorkspaceV1UnknownOutcome(
                            "Google page token schema requires reconciliation"
                        )
                    candidate_digest = _sha(candidate.encode())
                    if candidate_digest in seen_page_tokens:
                        raise GoogleWorkspaceV1UnknownOutcome(
                            "Google pagination replay requires reconciliation"
                        )
                    seen_page_tokens.add(candidate_digest)
                budget.add_items(len(page_items))
                self._require_same_token_after_dispatch(token)
            except GoogleWorkspaceV1UnknownOutcome:
                self._metadata_put_port(
                    self._state_metadata(token, "attempted_unknown", now_epoch_s)
                )
                raise
            remaining = policy.maximum_results - len(items)
            if len(page_items) > remaining:
                items.extend(page_items[:remaining])
                truncated = True
            else:
                items.extend(page_items)
            pages += 1
            response_digests.append(_sha(response.payload))
            page_token = candidate
            if candidate is None:
                break
        has_more = page_token is not None or truncated
        request_digest = _sha({"operation": operation, "query": base_query, "binding": self._binding_digest})
        receipt = GoogleProviderReceiptV1(
            operation,
            "complete",
            self._binding_digest,
            request_digest,
            _sha(response_digests),
            token.digest,
            len(items),
            pages,
        )
        return GoogleReadResultV1(tuple(items), has_more, receipt)

    def _fresh_token(self, now_epoch_s: int, budget: _GoogleOperationBudgetV1) -> GoogleTokenBundleV1:
        token = self._bound_token()
        if now_epoch_s + ACCESS_SKEW_SECONDS < token.access_expires_at_epoch_s:
            return token
        try:
            response = self._send(
                GoogleHttpRequestV1(
                    "POST",
                    OAUTH_ORIGIN,
                    TOKEN_PATH,
                    headers=(("Content-Type", "application/x-www-form-urlencoded"),),
                    form=(
                        ("client_id", self._settings.client_id),
                        ("refresh_token", token.refresh_token),
                        ("grant_type", "refresh_token"),
                    ),
                ),
                budget,
            )
            if response.status_code != 200:
                raise GoogleWorkspaceV1UnknownOutcome(
                    "Google refresh response requires reconciliation"
                )
            self._require_same_token_after_dispatch(token)
            refreshed = self._token_from_response(
                response,
                now_epoch_s,
                generation=token.generation + 1,
                existing_refresh=token.refresh_token,
            )
            if self._persist_token_port(token.digest, refreshed) is not True:
                raise GoogleWorkspaceV1UnknownOutcome(
                    "Google refresh persistence requires reconciliation"
                )
        except GoogleWorkspaceV1UnknownOutcome:
            self._metadata_put_port(
                self._state_metadata(token, "attempted_unknown", now_epoch_s)
            )
            raise
        self._metadata_put_port(self._connected_metadata(refreshed, now_epoch_s))
        return refreshed

    def _token_from_response(self, response, now_epoch_s, *, generation, existing_refresh=None):
        if response.status_code != 200:
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google token response requires reconciliation"
            )
        try:
            payload = response.payload
            access = _bounded_text(
                payload.get("access_token"), "access token", MAX_TOKEN_BYTES
            )
            refresh = payload.get("refresh_token", existing_refresh)
            refresh = _bounded_text(refresh, "refresh token", MAX_TOKEN_BYTES)
            expires = payload.get("expires_in")
            if type(expires) is not int or not 60 <= expires <= 86_400:
                raise GoogleWorkspaceV1ContractError("Google token expiry drift")
            if payload.get("token_type") != "Bearer":
                raise GoogleWorkspaceV1ContractError("Google token type drift")
            raw_scopes = payload.get("scope")
            if type(raw_scopes) is not str:
                raise GoogleWorkspaceV1ContractError("Google scopes are absent")
            scopes = tuple(raw_scopes.split(" "))
            if set(scopes) != set(READ_SCOPES) or len(scopes) != len(READ_SCOPES):
                raise GoogleWorkspaceV1ContractError("Google granted scope drift")
            return GoogleTokenBundleV1(
                self._binding_digest,
                access,
                refresh,
                now_epoch_s + expires,
                READ_SCOPES,
                generation,
            )
        except (GoogleWorkspaceV1ContractError, GoogleWorkspaceV1Denied):
            _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                "Google token schema requires reconciliation"
            ))

    def _verify_profile(
        self, token: GoogleTokenBundleV1, budget: _GoogleOperationBudgetV1
    ) -> None:
        response = self._send(
            GoogleHttpRequestV1(
                "GET",
                GMAIL_ORIGIN,
                GMAIL_PROFILE_PATH,
                headers=(("Authorization", f"Bearer {token.access_token}"),),
            ),
            budget,
        )
        account = response.payload.get("emailAddress")
        if (
            response.status_code != 200
            or type(account) is not str
            or _EMAIL.fullmatch(account) is None
        ):
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google account response requires reconciliation"
            )
        if not hmac.compare_digest(account.casefold(), self._binding.account_id):
            raise GoogleWorkspaceV1Denied("Google account binding drift")

    def _bound_token(self) -> GoogleTokenBundleV1:
        token = self._resolve_token_port()
        if type(token) is not GoogleTokenBundleV1:
            raise GoogleWorkspaceV1Denied("Google token is unavailable")
        if token.binding_digest != self._binding_digest or token.scopes != READ_SCOPES:
            raise GoogleWorkspaceV1Denied("Google token binding or scope drift")
        metadata = self._metadata_get_port()
        if type(metadata) is not GoogleGrantMetadataV1:
            raise GoogleWorkspaceV1Denied("Google grant metadata is unavailable")
        self._validate_metadata_binding(metadata)
        if metadata.provider_state != "connected":
            raise GoogleWorkspaceV1Denied("Google provider state requires reconciliation")
        if not hmac.compare_digest(metadata.grant_digest, token.digest):
            raise GoogleWorkspaceV1Denied("Google token and metadata generation drift")
        return token

    def _validate_metadata_binding(self, metadata: GoogleGrantMetadataV1) -> None:
        if (
            type(metadata) is not GoogleGrantMetadataV1
            or metadata.binding_digest != self._binding_digest
            or metadata.owner_digest != self._pseudonym("owner", self._binding.owner_id)
            or metadata.workspace_digest != self._pseudonym("workspace", self._binding.workspace_id)
            or metadata.account_digest != self._pseudonym("account", self._binding.account_id)
            or metadata.scopes != READ_SCOPES
        ):
            raise GoogleWorkspaceV1Denied("grant metadata binding drift")

    def _require_same_token_after_dispatch(
        self, expected: GoogleTokenBundleV1
    ) -> None:
        current = self._resolve_token_port()
        metadata = self._metadata_get_port()
        try:
            if (
                type(current) is not GoogleTokenBundleV1
                or current.binding_digest != self._binding_digest
                or current.scopes != READ_SCOPES
                or not hmac.compare_digest(current.digest, expected.digest)
                or type(metadata) is not GoogleGrantMetadataV1
            ):
                raise GoogleWorkspaceV1Denied("token generation drift")
            self._validate_metadata_binding(metadata)
            if (
                metadata.provider_state != "connected"
                or not hmac.compare_digest(metadata.grant_digest, expected.digest)
            ):
                raise GoogleWorkspaceV1Denied("metadata generation drift")
        except GoogleWorkspaceV1Denied:
            _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                "Google post-dispatch token generation requires reconciliation"
            ))

    def _send(
        self, request: GoogleHttpRequestV1, budget: _GoogleOperationBudgetV1
    ) -> GoogleHttpResponseV1:
        allowed = {
            (OAUTH_ORIGIN, TOKEN_PATH, "POST"),
            (OAUTH_ORIGIN, REVOKE_PATH, "POST"),
            (GMAIL_ORIGIN, GMAIL_PROFILE_PATH, "GET"),
            (GMAIL_ORIGIN, GMAIL_MESSAGES_PATH, "GET"),
            (CALENDAR_ORIGIN, CALENDAR_EVENTS_PATH, "GET"),
        }
        if (request.origin, request.path, request.method) not in allowed:
            raise GoogleWorkspaceV1Denied("Google route is forbidden")
        header_names = tuple(name.casefold() for name, _ in request.headers)
        query_names = tuple(name for name, _ in request.query)
        form_names = tuple(name for name, _ in request.form)
        if request.method == "GET":
            if request.form or header_names != ("authorization",):
                raise GoogleWorkspaceV1Denied("Google GET request contract drift")
            if not request.headers[0][1].startswith("Bearer "):
                raise GoogleWorkspaceV1Denied("Google authorization contract drift")
            allowed_queries = (
                {"q", "maxResults", "pageToken"}
                if request.path == GMAIL_MESSAGES_PATH
                else {
                    "timeMin",
                    "timeMax",
                    "singleEvents",
                    "orderBy",
                    "showDeleted",
                    "maxResults",
                    "pageToken",
                }
                if request.path == CALENDAR_EVENTS_PATH
                else set()
            )
            if set(query_names) - allowed_queries or len(query_names) != len(set(query_names)):
                raise GoogleWorkspaceV1Denied("Google query contract drift")
        else:
            if request.query or header_names not in {
                (),
                ("content-type",),
            }:
                raise GoogleWorkspaceV1Denied("Google POST request contract drift")
            if request.headers and request.headers[0][1] != "application/x-www-form-urlencoded":
                raise GoogleWorkspaceV1Denied("Google form content type drift")
            expected_forms = (
                {"client_id", "code", "code_verifier", "grant_type", "redirect_uri"},
                {"client_id", "refresh_token", "grant_type"},
            )
            if request.path == TOKEN_PATH:
                if set(form_names) not in expected_forms or len(form_names) != len(set(form_names)):
                    raise GoogleWorkspaceV1Denied("Google token form contract drift")
            elif set(form_names) != {"token"} or len(form_names) != 1:
                raise GoogleWorkspaceV1Denied("Google revoke form contract drift")
        remaining_seconds, remaining_bytes = budget.before_request()
        bounded_request = replace(
            request,
            timeout_seconds=min(request.timeout_seconds, remaining_seconds),
            maximum_response_bytes=min(
                request.maximum_response_bytes, remaining_bytes
            ),
        )
        response = self._transport_send_port(bounded_request)
        if type(response) is not GoogleHttpResponseV1:
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google transport response requires reconciliation"
            )
        budget.after_response(response)
        if response.body_bytes > bounded_request.maximum_response_bytes:
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google response exceeded remaining operation budget"
            )
        if (
            response.final_origin != bounded_request.origin
            or response.final_path != bounded_request.path
        ):
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google response origin requires reconciliation"
            )
        try:
            decoded_bytes = len(_canonical(response.payload))
        except GoogleWorkspaceV1ContractError:
            _raise_clean(GoogleWorkspaceV1UnknownOutcome(
                "Google decoded response requires reconciliation"
            ))
        if decoded_bytes > bounded_request.maximum_response_bytes:
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google decoded response budget requires reconciliation"
            )
        return response

    def _connected_metadata(self, token, now):
        return GoogleGrantMetadataV1(
            self._binding_digest,
            self._pseudonym("owner", self._binding.owner_id),
            self._pseudonym("workspace", self._binding.workspace_id),
            self._pseudonym("account", self._binding.account_id),
            READ_SCOPES,
            token.access_expires_at_epoch_s,
            token.digest,
            "connected",
            now,
        )

    def _state_metadata(self, token, state, now):
        connected = self._connected_metadata(token, now)
        return GoogleGrantMetadataV1(
            connected.binding_digest,
            connected.owner_digest,
            connected.workspace_digest,
            connected.account_digest,
            connected.scopes,
            connected.access_expires_at_epoch_s,
            connected.grant_digest,
            state,
            now,
        )

    def _attempted_unknown_metadata(self, grant_digest, now, expires):
        return GoogleGrantMetadataV1(
            self._binding_digest,
            self._pseudonym("owner", self._binding.owner_id),
            self._pseudonym("workspace", self._binding.workspace_id),
            self._pseudonym("account", self._binding.account_id),
            READ_SCOPES,
            max(now, expires),
            grant_digest,
            "attempted_unknown",
            now,
        )

    def _receipt(self, operation, status, grant_digest, payload, items, pages):
        return GoogleProviderReceiptV1(
            operation,
            status,
            self._binding_digest,
            _sha({"operation": operation, "binding": self._binding_digest}),
            _sha(payload),
            grant_digest,
            items,
            pages,
        )

    def _best_effort_revoke(
        self, token: str, budget: _GoogleOperationBudgetV1
    ) -> None:
        response = self._send(
            GoogleHttpRequestV1(
                "POST",
                OAUTH_ORIGIN,
                REVOKE_PATH,
                headers=(("Content-Type", "application/x-www-form-urlencoded"),),
                form=(("token", token),),
            ),
            budget,
        )
        if response.status_code != 200 or response.payload:
            raise GoogleWorkspaceV1UnknownOutcome(
                "Google cleanup revocation requires reconciliation"
            )

    @staticmethod
    def _gmail_projection(value: object) -> dict[str, object]:
        if type(value) is not dict or set(value) - {"id", "threadId"}:
            raise GoogleWorkspaceV1Denied("Gmail message contract drift")
        message_id = _bounded_text(value.get("id"), "message id", 512)
        thread_id = _bounded_text(value.get("threadId"), "thread id", 512)
        return {"id": message_id, "thread_id": thread_id}

    @staticmethod
    def _calendar_projection(value: object) -> dict[str, object]:
        if type(value) is not dict:
            raise GoogleWorkspaceV1Denied("Calendar event contract drift")
        allowed = {"id", "status", "summary", "start", "end", "location", "htmlLink"}
        selected = {key: value[key] for key in allowed if key in value}
        if "id" not in selected or "start" not in selected or "end" not in selected:
            raise GoogleWorkspaceV1Denied("Calendar event fields are incomplete")
        _bounded_text(selected["id"], "calendar event id", 1024)
        for field, maximum in (
            ("status", 32),
            ("summary", 4096),
            ("location", 4096),
            ("htmlLink", 4096),
        ):
            if field in selected:
                _bounded_text(selected[field], f"calendar {field}", maximum, empty=True)
        parsed_times: list[tuple[str, date | datetime]] = []
        for field in ("start", "end"):
            temporal = selected[field]
            if (
                type(temporal) is not dict
                or not set(temporal).issubset({"date", "dateTime", "timeZone"})
                or len({"date", "dateTime"} & set(temporal)) != 1
            ):
                raise GoogleWorkspaceV1Denied("Calendar event time contract drift")
            if "timeZone" in temporal:
                _bounded_text(temporal["timeZone"], "calendar timezone", 128)
            try:
                if "dateTime" in temporal:
                    parsed_times.append(
                        (
                            "dateTime",
                            _rfc3339_datetime(
                                temporal["dateTime"], f"calendar {field} dateTime"
                            ),
                        )
                    )
                else:
                    parsed_times.append(
                        (
                            "date",
                            _rfc3339_date(
                                temporal["date"], f"calendar {field} date"
                            ),
                        )
                    )
            except GoogleWorkspaceV1ContractError:
                _raise_clean(GoogleWorkspaceV1Denied(
                    "Calendar event time contract drift"
                ))
        if parsed_times[0][0] != parsed_times[1][0] or not (
            parsed_times[0][1] < parsed_times[1][1]
        ):
            raise GoogleWorkspaceV1Denied("Calendar event ordering drift")
        if len(_canonical(selected)) > 32_768:
            raise GoogleWorkspaceV1Denied("Calendar event exceeds its byte budget")
        return selected


def create_google_workspace_connector_v1(**kwargs) -> GoogleWorkspaceConnectorV1 | None:
    gate = kwargs.get("gate")
    if type(gate) is not GoogleWorkspaceFeatureGateV1:
        raise GoogleWorkspaceV1ContractError("exact feature gate required")
    if not gate.enabled:
        return None
    return GoogleWorkspaceConnectorV1(**kwargs)


__all__ = [name for name in globals() if name.startswith("Google") or name in {
    "CALENDAR_READ_SCOPE",
    "GMAIL_READ_SCOPE",
    "READ_SCOPES",
    "InMemoryGoogleGrantMetadataStoreV1",
    "create_google_workspace_connector_v1",
}]
