"""Default-off route-pinned read-only social provider connector for Phase 10.

Third Phase 10 (Social organic operating system) slice. It implements the PRD
"start with one official provider and test account" surface as a governed,
read-only connector contract: it reads only from an explicitly approved provider
registry (platform, api origin, status path, required scopes and the exact
account handle it represents) over a route-pinned, redirect-disabled HTTPS
client, bounds the response, never auto-retries, attributes provider identity
from the *trusted registry* rather than the fetched response, and rejects a
response whose handle does not match the registry-declared account (anti-spoof).

It is exactly default-off and read-only. There is no publish method. Even when
enabled it requires an injected approved provider registry and an HTTP client;
the real network fetch against a live provider is an owner-gated operation
(OAuth/app-review, test account, credentials, consent) and is not exercised by
this contract. Publishing, audience research and community replies are out of
scope for later gated successors.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Protocol
from urllib.parse import urlparse

from core.phase10_brand_passport_v1 import PLATFORMS

FEATURE_FLAG: Final = "ONYX_PHASE10_PROVIDER_CONNECTOR_V1"
ENABLED_VALUE: Final = "true"
HTTP_TIMEOUT_SECONDS: Final = 30
MAX_HTTP_BYTES: Final = 1_048_576
MAX_POST_IDS: Final = 200
MAX_ID_BYTES: Final = 256
MAX_HOST_BYTES: Final = 253
MAX_PATH_BYTES: Final = 2_048
MAX_SCOPES: Final = 64
MAX_FOLLOWERS: Final = 10_000_000_000
_CONSTRUCTION_KEY = object()
# A bare, lowercase, ASCII DNS host with >=2 labels: no userinfo (@), no port
# (:), no uppercase/unicode, no empty labels or leading/trailing hyphen. Keeps the
# route pin's netloc==origin==hostname equality trustworthy.
_HOST = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)
# An absolute, ASCII, query-free path of RFC 3986 path characters. Dot-segments
# and empty segments are rejected separately.
_PATH = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*")

# The accepted Phase 10 editorial-calendar four-file acceptance tuple. Building a
# connector is denied unless this frozen predecessor evidence is byte-exact.
ACCEPTED_EDITORIAL_CALENDAR_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase10-editorial-calendar-v1/manifest.json",
        "4b2fcce6cab138dbc788e7f5ba16214adf894b6cf37566229ffc91b3f8de683a",
    ),
    (
        "docs/onyx/acceptance/VE-P10-EDITORIAL-CALENDAR-V1-E6-001.md",
        "ad90c8bc971e1048082c1e6d94f63b35e6ac66568d91253c0ff7b524b6e93921",
    ),
    (
        "docs/onyx/acceptance/VE-P10-EDITORIAL-CALENDAR-V1-E6-001.manifest.json",
        "12f3edc21c5f36f2130d1e9379f13d17ff7413ab73cd815561dfa6993f8ac3a4",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P10-EDITORIAL-CALENDAR-V1-E6-001.sha256",
        "8def6e446ea34f90af2885980549106525581230685f1d67e27045b6548e4429",
    ),
)


class ProviderConnectorV1Error(RuntimeError):
    pass


class ProviderConnectorV1ContractError(ValueError):
    pass


class ProviderConnectorV1Denied(PermissionError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ProviderConnectorV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise ProviderConnectorV1ContractError(f"{field_name} contract violation")
    return value


@dataclass(frozen=True, slots=True)
class ProviderConnectorFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ProviderConnectorV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ProviderConnectorFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class ApprovedProviderV1:
    provider_id: str
    platform: str
    api_origin: str
    status_path: str
    expected_handle: str
    required_scopes: frozenset[str]
    test_account_only: bool

    def __post_init__(self) -> None:
        _text(self.provider_id, MAX_ID_BYTES, field_name="provider_id")
        _text(self.expected_handle, MAX_ID_BYTES, field_name="expected_handle")
        if self.platform not in PLATFORMS:
            raise ProviderConnectorV1ContractError("provider platform is unknown")
        if (
            len(self.api_origin.encode("utf-8")) > MAX_HOST_BYTES
            or not _HOST.fullmatch(self.api_origin)
        ):
            raise ProviderConnectorV1ContractError(
                "api_origin must be a bare lowercase host"
            )
        if (
            not _PATH.fullmatch(self.status_path)
            or ".." in self.status_path
            or "//" in self.status_path
            or len(self.status_path.encode("utf-8")) > MAX_PATH_BYTES
        ):
            raise ProviderConnectorV1ContractError(
                "status_path must be an absolute query-free path"
            )
        if type(self.required_scopes) is not frozenset or not self.required_scopes:
            raise ProviderConnectorV1ContractError("required_scopes must be non-empty")
        if len(self.required_scopes) > MAX_SCOPES:
            raise ProviderConnectorV1ContractError("too many scopes")
        for scope in self.required_scopes:
            _text(scope, MAX_ID_BYTES, field_name="scope")
        if type(self.test_account_only) is not bool:
            raise ProviderConnectorV1ContractError("test_account_only must be exact bool")


@dataclass(frozen=True, slots=True)
class ProviderJsonResponseV1:
    status_code: int
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if (
            type(self.status_code) is not int
            or type(self.status_code) is bool
            or not 100 <= self.status_code <= 599
        ):
            raise ProviderConnectorV1ContractError("http status is invalid")
        if type(self.payload) is not dict:
            raise ProviderConnectorV1ContractError("http payload must be an object")


@dataclass(frozen=True, slots=True)
class ProviderAccountStatusV1:
    provider_id: str
    platform: str
    handle: str
    verified: bool
    follower_count: int
    recent_post_ids: tuple[str, ...]
    http_status: int
    attribution: str


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_EDITORIAL_CALENDAR_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise ProviderConnectorV1Denied(
                "accepted editorial-calendar evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise ProviderConnectorV1Denied("accepted editorial-calendar evidence drift")


def _strict_json(data: bytes) -> dict[str, object]:
    if type(data) is not bytes or len(data) > MAX_HTTP_BYTES:
        raise ProviderConnectorV1Denied("HTTP payload size is invalid")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ProviderConnectorV1Denied("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderConnectorV1Denied("HTTP JSON is invalid") from exc
    if type(value) is not dict:
        raise ProviderConnectorV1Denied("HTTP JSON object required")
    return value


class ProviderConnectorHttpV1(Protocol):
    def get_json(
        self, *, url: str, origin: str, path: str, timeout_seconds: int
    ) -> ProviderJsonResponseV1: ...


class StdlibProviderConnectorHttpV1:
    """Route-pinned HTTPS GET client for approved providers only."""

    __slots__ = ("_opener",)

    def __init__(self) -> None:
        context = ssl.create_default_context()

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        self._opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=context)
        )

    def get_json(self, *, url, origin, path, timeout_seconds):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != origin
            or parsed.hostname != origin
            or parsed.port is not None
            or parsed.username is not None
            or parsed.path != path
            or parsed.query
            or parsed.fragment
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise ProviderConnectorV1Denied("provider route is invalid")
        # URL is pinned above to HTTPS, exact origin, path, and no userinfo/query.
        request = urllib.request.Request(  # noqa: S310
            url,
            headers={"Accept": "application/json", "User-Agent": "CyryxLabs-Onyx/1"},
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                data = response.read(MAX_HTTP_BYTES + 1)
                if len(data) > MAX_HTTP_BYTES:
                    raise ProviderConnectorV1Denied("HTTP response exceeded size limit")
                return ProviderJsonResponseV1(int(response.status), _strict_json(data))
        except urllib.error.HTTPError as exc:
            data = exc.read(MAX_HTTP_BYTES + 1)
            if len(data) > MAX_HTTP_BYTES:
                raise ProviderConnectorV1Denied("HTTP error exceeded size limit") from exc
            return ProviderJsonResponseV1(int(exc.code), _strict_json(data))
        except ProviderConnectorV1Denied:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise ProviderConnectorV1Error("provider HTTPS request failed") from exc


class ProviderConnectorSessionV1:
    """Route-pinned read-only fetch of an approved provider's account status."""

    __slots__ = ("_http", "_providers")

    def __init__(
        self,
        *,
        construction_key: object,
        providers: tuple[ApprovedProviderV1, ...],
        http: ProviderConnectorHttpV1,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise ProviderConnectorV1ContractError("use create_provider_connector_v1")
        self._providers = providers
        self._http = http

    def approved_provider_ids(self) -> tuple[str, ...]:
        return tuple(provider.provider_id for provider in self._providers)

    def _post_ids(self, value: object) -> tuple[str, ...]:
        if type(value) is not list:
            raise ProviderConnectorV1Denied("recent_post_ids drift")
        if len(value) > MAX_POST_IDS:
            raise ProviderConnectorV1Denied("recent_post_ids exceeded cap")
        return tuple(_text(v, MAX_ID_BYTES, field_name="post id") for v in value)

    def fetch_account_status(self, *, provider_id: str) -> ProviderAccountStatusV1:
        provider = next(
            (p for p in self._providers if p.provider_id == provider_id), None
        )
        if provider is None:
            raise ProviderConnectorV1ContractError(
                "provider is not in the approved registry"
            )
        url = f"https://{provider.api_origin}{provider.status_path}"
        response = self._http.get_json(
            url=url,
            origin=provider.api_origin,
            path=provider.status_path,
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not ProviderJsonResponseV1 or response.status_code != 200:
            raise ProviderConnectorV1Error("provider status fetch failed")
        payload = response.payload
        handle = _text(payload.get("handle"), MAX_ID_BYTES, field_name="handle")
        # Anti-spoof: the response identity must match the registry-declared
        # account. Provider id and platform are attributed from the trusted
        # registry, never from the response.
        if handle != provider.expected_handle:
            raise ProviderConnectorV1Denied("response handle does not match registry")
        verified = payload.get("verified")
        if type(verified) is not bool:
            raise ProviderConnectorV1Denied("verified flag drift")
        followers = payload.get("follower_count")
        if type(followers) is not int or type(followers) is bool or not (
            0 <= followers <= MAX_FOLLOWERS
        ):
            raise ProviderConnectorV1Denied("follower_count drift")
        post_ids = self._post_ids(payload.get("recent_post_ids", []))
        attribution = f"{provider.provider_id}:{provider.expected_handle} via {provider.api_origin}{provider.status_path}"
        return ProviderAccountStatusV1(
            provider_id=provider.provider_id,
            platform=provider.platform,
            handle=handle,
            verified=verified,
            follower_count=followers,
            recent_post_ids=post_ids,
            http_status=response.status_code,
            attribution=attribution,
        )


def _providers(raw: object) -> tuple[ApprovedProviderV1, ...]:
    if type(raw) is not tuple or not raw or len(raw) > 128:
        raise ProviderConnectorV1ContractError("approved provider registry is invalid")
    seen: set[str] = set()
    for provider in raw:
        if type(provider) is not ApprovedProviderV1:
            raise ProviderConnectorV1ContractError("sealed ApprovedProviderV1 required")
        if provider.provider_id in seen:
            raise ProviderConnectorV1ContractError("duplicate approved provider_id")
        seen.add(provider.provider_id)
    return raw


def create_provider_connector_v1(
    *,
    gate: ProviderConnectorFeatureGateV1 | None = None,
    providers: tuple[ApprovedProviderV1, ...] | None = None,
    http: ProviderConnectorHttpV1 | None = None,
    project_root: Path | str | None = None,
) -> ProviderConnectorSessionV1 | None:
    selected = ProviderConnectorFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not ProviderConnectorFeatureGateV1:
        raise ProviderConnectorV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    if providers is None:
        raise ProviderConnectorV1ContractError("enabled session requires providers")
    registry = _providers(providers)
    selected_http = StdlibProviderConnectorHttpV1() if http is None else http
    if not hasattr(selected_http, "get_json"):
        raise ProviderConnectorV1ContractError("provider transport is invalid")
    return ProviderConnectorSessionV1(
        construction_key=_CONSTRUCTION_KEY,
        providers=registry,
        http=selected_http,
    )


__all__ = [
    "ApprovedProviderV1",
    "FEATURE_FLAG",
    "ProviderAccountStatusV1",
    "ProviderConnectorFeatureGateV1",
    "ProviderConnectorHttpV1",
    "ProviderConnectorSessionV1",
    "ProviderConnectorV1ContractError",
    "ProviderConnectorV1Denied",
    "ProviderConnectorV1Error",
    "ProviderJsonResponseV1",
    "StdlibProviderConnectorHttpV1",
    "create_provider_connector_v1",
]
