"""Default-off resilient live-read transport for Microsoft Graph.

This successor composes the accepted Graph Read V1 and Graph OAuth V1
foundations without modifying either predecessor.  It adds bounded retry,
one forced token refresh after a 401, Retry-After handling, terminal error
classification and payload-free operational telemetry for GET-only routes.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Mapping

from core.phase8_microsoft_graph_oauth_v1 import (
    HTTP_TIMEOUT_SECONDS,
    GraphOAuthHttpV1,
    GraphOAuthV1ContractError,
    GraphOAuthV1Denied,
    GraphOAuthV1Error,
    JsonHttpResponseV1,
    MicrosoftGraphOAuthSessionV1,
    StdlibGraphOAuthHttpV1,
)
from core.phase8_microsoft_graph_read_v1 import (
    GraphHttpResponseV1,
    GraphReadTransportV1,
)

FEATURE_FLAG: Final = "ONYX_PHASE8_MICROSOFT_GRAPH_LIVE_READ_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxMicrosoftGraphLiveRead.v1"
MAX_QUERY_ITEMS: Final = 20
MAX_QUERY_VALUE: Final = 4_096
MAX_HEADER_VALUE: Final = 2_000
RETRYABLE_STATUS: Final = frozenset({429, 500, 502, 503, 504})
ALLOWED_CALLER_HEADERS: Final = frozenset({"prefer", "consistencylevel"})
ACCEPTED_OAUTH_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase8-microsoft-graph-oauth-v1/manifest.json",
        "81dbaba8991478737c7000519281d8c1924a3522aec40b62e3a635bcde3d2b65",
    ),
    (
        "docs/onyx/acceptance/VE-P8-MICROSOFT-GRAPH-OAUTH-V1-E6-001.md",
        "e39511e5f8e677ec0983df19102221ea1abbe68bdf7d297f13ac64c34a076473",
    ),
    (
        "docs/onyx/acceptance/VE-P8-MICROSOFT-GRAPH-OAUTH-V1-E6-001.manifest.json",
        "a5d72b9876269bd81b8c26e22d6e79ef96468773c560e86bc38b0b518c740123",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-OAUTH-V1-E6-001.sha256",
        "77fd9772c247308d2c18f9c911684855955a8d390705f992ac1841fee5de6bfa",
    ),
)
_GRAPH_READ_PATH = re.compile(
    r"^/v1\.0/me(?:$|/calendarView$|/messages(?:/[^/]{1,1536})?$)"
)
_REQUEST_ID = re.compile(r"^[\x21-\x7e]{1,200}$")
_CONSTRUCTION_KEY = object()


class GraphLiveReadV1Error(RuntimeError):
    pass


class GraphLiveReadV1ContractError(ValueError):
    pass


class GraphLiveReadV1Denied(PermissionError):
    pass


class GraphLiveReadAuthenticationRequiredV1(GraphLiveReadV1Denied):
    pass


class GraphLiveReadPermissionDeniedV1(GraphLiveReadV1Denied):
    pass


class GraphLiveReadRateLimitedV1(GraphLiveReadV1Error):
    pass


class GraphLiveReadProviderUnavailableV1(GraphLiveReadV1Error):
    pass


@dataclass(frozen=True, slots=True)
class GraphLiveReadFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GraphLiveReadV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GraphLiveReadFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class GraphLiveReadRetryPolicyV1:
    max_attempts: int = 3
    base_delay_seconds: int = 1
    max_delay_seconds: int = 60
    max_total_delay_seconds: int = 120

    def __post_init__(self) -> None:
        if (
            type(self.max_attempts) is not int
            or not 1 <= self.max_attempts <= 5
            or type(self.base_delay_seconds) is not int
            or not 1 <= self.base_delay_seconds <= 10
            or type(self.max_delay_seconds) is not int
            or not 1 <= self.max_delay_seconds <= 300
            or type(self.max_total_delay_seconds) is not int
            or not 1 <= self.max_total_delay_seconds <= 600
            or self.base_delay_seconds > self.max_delay_seconds
        ):
            raise GraphLiveReadV1ContractError("retry policy is invalid")


@dataclass(frozen=True, slots=True)
class GraphLiveReadOutcomeV1:
    route: str
    result: str
    attempts: int
    status_code: int | None
    retry_delay_seconds: int
    request_id: str | None
    refreshed_after_401: bool

    def __post_init__(self) -> None:
        if (
            type(self.route) is not str
            or not _GRAPH_READ_PATH.fullmatch(self.route)
            or self.result
            not in {
                "success",
                "client_error",
                "authentication_required",
                "permission_denied",
                "rate_limited",
                "provider_unavailable",
            }
            or type(self.attempts) is not int
            or not 1 <= self.attempts <= 5
            or (
                self.status_code is not None
                and (
                    type(self.status_code) is not int
                    or not 100 <= self.status_code <= 599
                )
            )
            or type(self.retry_delay_seconds) is not int
            or not 0 <= self.retry_delay_seconds <= 600
            or (
                self.request_id is not None
                and (
                    type(self.request_id) is not str
                    or not _REQUEST_ID.fullmatch(self.request_id)
                )
            )
            or type(self.refreshed_after_401) is not bool
        ):
            raise GraphLiveReadV1ContractError("live-read outcome is invalid")


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_OAUTH_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GraphLiveReadV1Denied(
                "accepted Graph OAuth evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GraphLiveReadV1Denied("accepted Graph OAuth evidence drift")


def _request_id(response: JsonHttpResponseV1) -> str | None:
    values = tuple(
        value for name, value in response.headers if name.casefold() == "request-id"
    )
    if not values:
        return None
    if len(values) != 1 or not _REQUEST_ID.fullmatch(values[0]):
        raise GraphLiveReadV1Denied("Microsoft request-id header is invalid")
    return values[0]


def _retry_after_seconds(response: JsonHttpResponseV1) -> int | None:
    values = tuple(
        value for name, value in response.headers if name.casefold() == "retry-after"
    )
    if not values:
        return None
    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
        raise GraphLiveReadV1Denied("Microsoft Retry-After header is invalid")
    delay = int(values[0])
    if not 1 <= delay <= 86_400:
        raise GraphLiveReadV1Denied("Microsoft Retry-After delay is invalid")
    return delay


def _validate_request(
    *,
    url: str,
    query: tuple[tuple[str, str], ...],
    headers: tuple[tuple[str, str], ...],
) -> str:
    parsed = urllib.parse.urlparse(url)
    if (
        type(url) is not str
        or parsed.scheme != "https"
        or parsed.netloc != "graph.microsoft.com"
        or not _GRAPH_READ_PATH.fullmatch(parsed.path)
        or parsed.query
        or parsed.fragment
        or type(query) is not tuple
        or len(query) > MAX_QUERY_ITEMS
        or any(
            type(name) is not str
            or type(value) is not str
            or not 1 <= len(name) <= 100
            or len(value) > MAX_QUERY_VALUE
            for name, value in query
        )
        or type(headers) is not tuple
        or any(
            type(name) is not str
            or type(value) is not str
            or name.casefold() not in ALLOWED_CALLER_HEADERS
            or len(value) > MAX_HEADER_VALUE
            or "\x00" in value
            for name, value in headers
        )
        or len({name.casefold() for name, _value in headers}) != len(headers)
    ):
        raise GraphLiveReadV1Denied("Graph live-read route is invalid")
    return parsed.path


class MicrosoftGraphLiveReadTransportV1(GraphReadTransportV1):
    __slots__ = (
        "_clock_epoch_s",
        "_clock_ms",
        "_http",
        "_last_outcome",
        "_policy",
        "_session",
        "_sleeper",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        session: MicrosoftGraphOAuthSessionV1,
        http: GraphOAuthHttpV1,
        clock_epoch_s: Callable[[], int],
        clock_ms: Callable[[], int],
        sleeper: Callable[[int], None],
        policy: GraphLiveReadRetryPolicyV1,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GraphLiveReadV1ContractError("use live-read factory")
        self._session = session
        self._http = http
        self._clock_epoch_s = clock_epoch_s
        self._clock_ms = clock_ms
        self._sleeper = sleeper
        self._policy = policy
        self._last_outcome: GraphLiveReadOutcomeV1 | None = None

    @property
    def last_outcome(self) -> GraphLiveReadOutcomeV1 | None:
        return self._last_outcome

    def _now(self) -> tuple[int, int]:
        epoch_s, now_ms = self._clock_epoch_s(), self._clock_ms()
        if (
            type(epoch_s) is not int
            or epoch_s < 0
            or type(now_ms) is not int
            or now_ms < 0
        ):
            raise GraphLiveReadV1ContractError("clock result is invalid")
        return epoch_s, now_ms

    def _record(
        self,
        *,
        route: str,
        result: str,
        attempts: int,
        status_code: int | None,
        retry_delay_seconds: int,
        request_id: str | None,
        refreshed_after_401: bool,
    ) -> None:
        self._last_outcome = GraphLiveReadOutcomeV1(
            route,
            result,
            attempts,
            status_code,
            retry_delay_seconds,
            request_id,
            refreshed_after_401,
        )

    def _sleep(self, seconds: int) -> None:
        try:
            self._sleeper(seconds)
        except Exception as exc:
            raise GraphLiveReadV1Error("retry wait failed") from exc

    def get(
        self,
        *,
        url: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
    ) -> GraphHttpResponseV1:
        route = _validate_request(url=url, query=query, headers=headers)
        total_delay = 0
        refreshed = False
        last_response: JsonHttpResponseV1 | None = None

        for attempt in range(1, self._policy.max_attempts + 1):
            now_epoch_s, now_ms = self._now()
            try:
                # Graph OAuth V1 intentionally keeps bearer access process-local.
                # This same-package successor invokes its sealed internal token
                # broker rather than copying or persisting a bearer value.
                access_token = self._session._token(
                    now_ms=now_ms,
                    now_epoch_s=now_epoch_s,
                )
            except GraphOAuthV1Denied as exc:
                self._record(
                    route=route,
                    result="authentication_required",
                    attempts=attempt,
                    status_code=None,
                    retry_delay_seconds=total_delay,
                    request_id=None,
                    refreshed_after_401=refreshed,
                )
                raise GraphLiveReadAuthenticationRequiredV1(
                    "Microsoft sign-in is required"
                ) from exc
            except GraphOAuthV1Error as exc:
                self._record(
                    route=route,
                    result="provider_unavailable",
                    attempts=attempt,
                    status_code=None,
                    retry_delay_seconds=total_delay,
                    request_id=None,
                    refreshed_after_401=refreshed,
                )
                raise GraphLiveReadProviderUnavailableV1(
                    "Microsoft token service is unavailable"
                ) from exc

            response = self._http.get_json(
                url=url,
                query=query,
                headers=(("Authorization", f"Bearer {access_token}"), *headers),
                timeout_seconds=HTTP_TIMEOUT_SECONDS,
            )
            if type(response) is not JsonHttpResponseV1:
                raise GraphLiveReadV1ContractError("exact JsonHttpResponseV1 required")
            last_response = response
            request_id = _request_id(response)

            if response.status_code == 200:
                self._record(
                    route=route,
                    result="success",
                    attempts=attempt,
                    status_code=200,
                    retry_delay_seconds=total_delay,
                    request_id=request_id,
                    refreshed_after_401=refreshed,
                )
                return GraphHttpResponseV1(200, response.payload, request_id)

            if response.status_code == 401:
                if refreshed or attempt >= self._policy.max_attempts:
                    self._record(
                        route=route,
                        result="authentication_required",
                        attempts=attempt,
                        status_code=401,
                        retry_delay_seconds=total_delay,
                        request_id=request_id,
                        refreshed_after_401=refreshed,
                    )
                    raise GraphLiveReadAuthenticationRequiredV1(
                        "Microsoft access was rejected after refresh"
                    )
                try:
                    self._session.restore(
                        now_ms=now_ms,
                        now_epoch_s=now_epoch_s,
                    )
                except (
                    GraphOAuthV1ContractError,
                    GraphOAuthV1Denied,
                    GraphOAuthV1Error,
                ) as exc:
                    self._record(
                        route=route,
                        result="authentication_required",
                        attempts=attempt,
                        status_code=401,
                        retry_delay_seconds=total_delay,
                        request_id=request_id,
                        refreshed_after_401=True,
                    )
                    raise GraphLiveReadAuthenticationRequiredV1(
                        "Microsoft authorization must be renewed"
                    ) from exc
                refreshed = True
                continue

            if response.status_code == 403:
                self._record(
                    route=route,
                    result="permission_denied",
                    attempts=attempt,
                    status_code=403,
                    retry_delay_seconds=total_delay,
                    request_id=request_id,
                    refreshed_after_401=refreshed,
                )
                raise GraphLiveReadPermissionDeniedV1(
                    "Microsoft Graph permission or license denied"
                )

            if response.status_code in RETRYABLE_STATUS:
                retry_after = _retry_after_seconds(response)
                delay = (
                    min(
                        self._policy.max_delay_seconds,
                        self._policy.base_delay_seconds * (2 ** (attempt - 1)),
                    )
                    if retry_after is None
                    else retry_after
                )
                exhausted = (
                    attempt >= self._policy.max_attempts
                    or delay > self._policy.max_delay_seconds
                    or total_delay + delay > self._policy.max_total_delay_seconds
                )
                if exhausted:
                    result = (
                        "rate_limited"
                        if response.status_code == 429
                        else "provider_unavailable"
                    )
                    self._record(
                        route=route,
                        result=result,
                        attempts=attempt,
                        status_code=response.status_code,
                        retry_delay_seconds=total_delay,
                        request_id=request_id,
                        refreshed_after_401=refreshed,
                    )
                    error_type = (
                        GraphLiveReadRateLimitedV1
                        if response.status_code == 429
                        else GraphLiveReadProviderUnavailableV1
                    )
                    raise error_type("Microsoft Graph retry budget was exhausted")
                self._sleep(delay)
                total_delay += delay
                continue

            self._record(
                route=route,
                result="client_error",
                attempts=attempt,
                status_code=response.status_code,
                retry_delay_seconds=total_delay,
                request_id=request_id,
                refreshed_after_401=refreshed,
            )
            return GraphHttpResponseV1(
                response.status_code,
                response.payload,
                request_id,
            )

        raise GraphLiveReadV1Error(
            f"unreachable retry state: {last_response is not None}"
        )


def create_microsoft_graph_live_read_transport_v1(
    *,
    gate: GraphLiveReadFeatureGateV1 | None = None,
    session: MicrosoftGraphOAuthSessionV1 | None = None,
    http: GraphOAuthHttpV1 | None = None,
    clock_epoch_s: Callable[[], int] | None = None,
    clock_ms: Callable[[], int] | None = None,
    sleeper: Callable[[int], None] | None = None,
    policy: GraphLiveReadRetryPolicyV1 | None = None,
    project_root: Path | str | None = None,
) -> MicrosoftGraphLiveReadTransportV1 | None:
    selected = GraphLiveReadFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not GraphLiveReadFeatureGateV1:
        raise GraphLiveReadV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    if (
        type(session) is not MicrosoftGraphOAuthSessionV1
        or not callable(clock_epoch_s)
        or not callable(clock_ms)
    ):
        raise GraphLiveReadV1ContractError(
            "enabled live read requires accepted OAuth session and clocks"
        )
    selected_http = StdlibGraphOAuthHttpV1() if http is None else http
    selected_sleeper = time.sleep if sleeper is None else sleeper
    selected_policy = GraphLiveReadRetryPolicyV1() if policy is None else policy
    if (
        not hasattr(selected_http, "get_json")
        or not callable(selected_sleeper)
        or type(selected_policy) is not GraphLiveReadRetryPolicyV1
    ):
        raise GraphLiveReadV1ContractError("live-read dependency is invalid")
    return MicrosoftGraphLiveReadTransportV1(
        construction_key=_CONSTRUCTION_KEY,
        session=session,
        http=selected_http,
        clock_epoch_s=clock_epoch_s,
        clock_ms=clock_ms,
        sleeper=selected_sleeper,
        policy=selected_policy,
    )


__all__ = [
    "FEATURE_FLAG",
    "GraphLiveReadAuthenticationRequiredV1",
    "GraphLiveReadFeatureGateV1",
    "GraphLiveReadOutcomeV1",
    "GraphLiveReadPermissionDeniedV1",
    "GraphLiveReadProviderUnavailableV1",
    "GraphLiveReadRateLimitedV1",
    "GraphLiveReadRetryPolicyV1",
    "GraphLiveReadV1ContractError",
    "GraphLiveReadV1Denied",
    "GraphLiveReadV1Error",
    "MicrosoftGraphLiveReadTransportV1",
    "create_microsoft_graph_live_read_transport_v1",
]
