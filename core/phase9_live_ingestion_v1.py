"""Default-off route-pinned live/official-source ingestion connector for Phase 9.

This slice implements the PRD live-ingestion surface as a governed connector: it
fetches only from an explicitly approved source registry (origin, path, tier and
category allowlist) over a route-pinned, redirect-disabled HTTPS client, bounds
the response and item counts, never auto-retries, and attributes source health
from the *trusted registry* rather than from the fetched feed. It parses a
strict neutral feed shape into ingestion-ready raw items (the exact shape the
accepted Phase 9 intelligence ingestion contract consumes) and adds upstream
source attribution.

It is exactly default-off. Even when enabled it requires an injected approved
source registry and an HTTP client; the real network fetch against live sources
is an owner-gated operation (registration, credentials and consent) and is not
exercised by this contract. Claim typing, deduplication and corroboration remain
the job of the accepted ingestion contract; opportunity scoring and the
licence-gated World Monitor connector are out of scope.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Final, Mapping, Protocol
from urllib.parse import urlparse

from core.phase9_intelligence_ingestion_v1 import CATEGORIES, SOURCE_TIERS

FEATURE_FLAG: Final = "ONYX_PHASE9_LIVE_INGESTION_V1"
ENABLED_VALUE: Final = "true"
HTTP_TIMEOUT_SECONDS: Final = 30
MAX_HTTP_BYTES: Final = 1_048_576
MAX_ITEMS_PER_FETCH: Final = 200
MAX_ID_BYTES: Final = 256
MAX_HOST_BYTES: Final = 253
MAX_PATH_BYTES: Final = 2_048
MAX_TEXT_BYTES: Final = 4_000
_EPOCH0: Final = datetime(1970, 1, 1, tzinfo=timezone.utc)
_CONSTRUCTION_KEY = object()
# A bare, lowercase, ASCII DNS host with at least two labels: no userinfo (@),
# no port (:), no uppercase, no unicode, no empty labels (..) or leading/trailing
# hyphen. Keeps the route pin's netloc==origin==hostname equality trustworthy.
_HOST = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)
# An absolute, ASCII, query-free path of RFC 3986 path characters. Dot-segments
# and empty segments are rejected separately.
_PATH = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*")
ACCEPTED_SCORING_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase9-opportunity-scoring-v1/manifest.json",
        "9249c37f825d07f21860f82296c9eeee2dee9cf4e9948aa7d0e75230e6e68d85",
    ),
    (
        "docs/onyx/acceptance/VE-P9-OPPORTUNITY-SCORING-V1-E6-001.md",
        "c29a3dad5802d694d3a3888d3b34872e1b317ee9404d8fea123cb36a5f5517d0",
    ),
    (
        "docs/onyx/acceptance/VE-P9-OPPORTUNITY-SCORING-V1-E6-001.manifest.json",
        "7562ccdc2d52359a72928d7437a1e5b57bd21b911ab1d2e401fd993eea4ed11c",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P9-OPPORTUNITY-SCORING-V1-E6-001.sha256",
        "d94846a68cc9e253c815acae257fa2eaca0919840198074a7fc66c3eab790bdc",
    ),
)


class LiveIngestionV1Error(RuntimeError):
    pass


class LiveIngestionV1ContractError(ValueError):
    pass


class LiveIngestionV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class LiveIngestionFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise LiveIngestionV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "LiveIngestionFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class ApprovedSourceV1:
    source_id: str
    tier: str
    category: str
    origin: str
    path: str

    def __post_init__(self) -> None:
        _text(self.source_id, MAX_ID_BYTES, field="source_id")
        if self.tier not in SOURCE_TIERS:
            raise LiveIngestionV1ContractError("source tier is unknown")
        if self.category not in CATEGORIES:
            raise LiveIngestionV1ContractError("source category is unknown")
        if (
            len(self.origin.encode("utf-8")) > MAX_HOST_BYTES
            or not _HOST.fullmatch(self.origin)
        ):
            raise LiveIngestionV1ContractError("origin must be a bare lowercase host")
        if (
            not _PATH.fullmatch(self.path)
            or ".." in self.path
            or "//" in self.path
            or len(self.path.encode("utf-8")) > MAX_PATH_BYTES
        ):
            raise LiveIngestionV1ContractError("path must be an absolute query-free path")


@dataclass(frozen=True, slots=True)
class LiveJsonResponseV1:
    status_code: int
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if (
            type(self.status_code) is not int
            or type(self.status_code) is bool
            or not 100 <= self.status_code <= 599
        ):
            raise LiveIngestionV1ContractError("http status is invalid")
        if type(self.payload) is not dict:
            raise LiveIngestionV1ContractError("http payload must be an object")


@dataclass(frozen=True, slots=True)
class FetchResultV1:
    source_id: str
    tier: str
    category: str
    url: str
    http_status: int
    fetched_at_utc: str
    item_count: int
    attribution: str
    raw_items: tuple[dict[str, object], ...]


def _text(value: object, maximum: int, *, field: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise LiveIngestionV1ContractError(f"{field} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise LiveIngestionV1ContractError(f"{field} contract violation")
    return value


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_SCORING_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise LiveIngestionV1Denied(
                "accepted scoring evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise LiveIngestionV1Denied("accepted scoring evidence drift")


def _strict_json(data: bytes) -> dict[str, object]:
    if type(data) is not bytes or len(data) > MAX_HTTP_BYTES:
        raise LiveIngestionV1Denied("HTTP payload size is invalid")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise LiveIngestionV1Denied("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LiveIngestionV1Denied("HTTP JSON is invalid") from exc
    if type(value) is not dict:
        raise LiveIngestionV1Denied("HTTP JSON object required")
    return value


class LiveIngestionHttpV1(Protocol):
    def get_json(
        self, *, url: str, origin: str, path: str, timeout_seconds: int
    ) -> LiveJsonResponseV1: ...


class StdlibLiveIngestionHttpV1:
    """Route-pinned HTTPS GET client for approved sources only."""

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
            raise LiveIngestionV1Denied("live ingestion route is invalid")
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
                    raise LiveIngestionV1Denied("HTTP response exceeded size limit")
                return LiveJsonResponseV1(int(response.status), _strict_json(data))
        except urllib.error.HTTPError as exc:
            data = exc.read(MAX_HTTP_BYTES + 1)
            if len(data) > MAX_HTTP_BYTES:
                raise LiveIngestionV1Denied("HTTP error exceeded size limit") from exc
            return LiveJsonResponseV1(int(exc.code), _strict_json(data))
        except LiveIngestionV1Denied:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise LiveIngestionV1Error("live source HTTPS request failed") from exc


class LiveIngestionSessionV1:
    """Route-pinned fetch of approved sources into ingestion-ready raw items."""

    __slots__ = ("_http", "_now_epoch_s", "_sources")

    def __init__(
        self,
        *,
        construction_key: object,
        sources: tuple[ApprovedSourceV1, ...],
        http: LiveIngestionHttpV1,
        now_epoch_s: Callable[[], int],
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise LiveIngestionV1ContractError("use create_live_ingestion_v1")
        self._sources = sources
        self._http = http
        self._now_epoch_s = now_epoch_s

    def approved_source_ids(self) -> tuple[str, ...]:
        return tuple(source.source_id for source in self._sources)

    def _raw_item(self, source: ApprovedSourceV1, feed_item: object) -> dict[str, object]:
        if type(feed_item) is not dict:
            raise LiveIngestionV1Denied("feed item drift")
        claims = feed_item.get("claims", [])
        if type(claims) is not list:
            raise LiveIngestionV1Denied("feed claims drift")
        # Source id, health tier AND category are attributed from the trusted
        # approved source, never from the fetched feed; the feed can only supply
        # content fields (id, title, url, timestamps, claims).
        return {
            "item_id": _text(feed_item.get("id"), MAX_ID_BYTES, field="feed id"),
            "category": source.category,
            "source_id": source.source_id,
            "source_tier": source.tier,
            "url": _text(feed_item.get("url"), MAX_PATH_BYTES, field="feed url"),
            "publication_datetime": _text(
                feed_item.get("published"), 64, field="feed published"
            ),
            "event_datetime": _text(feed_item.get("event"), 64, field="feed event"),
            "title": _text(feed_item.get("title"), MAX_TEXT_BYTES, field="feed title"),
            "claims": claims,
        }

    def fetch(self, *, source_id: str) -> FetchResultV1:
        source = next((s for s in self._sources if s.source_id == source_id), None)
        if source is None:
            raise LiveIngestionV1ContractError("source is not in the approved registry")
        now = self._now_epoch_s()
        if type(now) is not int:
            raise LiveIngestionV1ContractError("clock result is invalid")
        url = f"https://{source.origin}{source.path}"
        response = self._http.get_json(
            url=url,
            origin=source.origin,
            path=source.path,
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not LiveJsonResponseV1 or response.status_code != 200:
            raise LiveIngestionV1Error("live source fetch failed")
        items = response.payload.get("items")
        if type(items) is not list:
            raise LiveIngestionV1Denied("feed collection drift")
        if len(items) > MAX_ITEMS_PER_FETCH:
            raise LiveIngestionV1Denied("feed exceeded item cap")
        raw_items = tuple(self._raw_item(source, item) for item in items)
        fetched_at = (_EPOCH0 + timedelta(seconds=now)).isoformat()
        attribution = f"{source.tier}:{source.source_id} via {source.origin}{source.path}"
        return FetchResultV1(
            source.source_id,
            source.tier,
            source.category,
            url,
            response.status_code,
            fetched_at,
            len(raw_items),
            attribution,
            raw_items,
        )


def _sources(raw: object) -> tuple[ApprovedSourceV1, ...]:
    if type(raw) is not tuple or not raw or len(raw) > 512:
        raise LiveIngestionV1ContractError("approved source registry is invalid")
    seen: set[str] = set()
    for source in raw:
        if type(source) is not ApprovedSourceV1:
            raise LiveIngestionV1ContractError("sealed ApprovedSourceV1 required")
        if source.source_id in seen:
            raise LiveIngestionV1ContractError("duplicate approved source_id")
        seen.add(source.source_id)
    return raw


def create_live_ingestion_v1(
    *,
    gate: LiveIngestionFeatureGateV1 | None = None,
    sources: tuple[ApprovedSourceV1, ...] | None = None,
    http: LiveIngestionHttpV1 | None = None,
    now_epoch_s: Callable[[], int] | None = None,
    project_root: Path | str | None = None,
) -> LiveIngestionSessionV1 | None:
    selected = LiveIngestionFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not LiveIngestionFeatureGateV1:
        raise LiveIngestionV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    if sources is None or now_epoch_s is None or not callable(now_epoch_s):
        raise LiveIngestionV1ContractError("enabled session requires sources and a clock")
    registry = _sources(sources)
    selected_http = StdlibLiveIngestionHttpV1() if http is None else http
    if not hasattr(selected_http, "get_json"):
        raise LiveIngestionV1ContractError("live ingestion transport is invalid")
    return LiveIngestionSessionV1(
        construction_key=_CONSTRUCTION_KEY,
        sources=registry,
        http=selected_http,
        now_epoch_s=now_epoch_s,
    )


__all__ = [
    "ApprovedSourceV1",
    "FEATURE_FLAG",
    "FetchResultV1",
    "LiveIngestionFeatureGateV1",
    "LiveIngestionHttpV1",
    "LiveIngestionSessionV1",
    "LiveIngestionV1ContractError",
    "LiveIngestionV1Denied",
    "LiveIngestionV1Error",
    "LiveJsonResponseV1",
    "StdlibLiveIngestionHttpV1",
    "create_live_ingestion_v1",
]
