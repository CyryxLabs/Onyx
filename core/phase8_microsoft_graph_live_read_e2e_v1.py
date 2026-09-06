"""Default-off Microsoft Graph live read-only E2E successor.

This successor composes the accepted Phase 8 OAuth V1 and Graph Read V1
contracts into an evidence-producing live E2E harness. It adds secret-free
Microsoft Entra public-client onboarding from the environment, a throttle-aware
transport wrapper that honors ``429 Retry-After``, and deterministic probes for
sign-in/read, access expiry, refresh rotation, revocation, provider failure and
rate-limit behavior. It adds no provider mutation route and no live runtime
surface wiring of any kind.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Final, Mapping

from core.phase7_workspace_aliases_v1 import (
    WorkspaceAliasCatalogV1,
    WorkspaceAliasV1Denied,
)
from core.phase8_microsoft_graph_oauth_v1 import (
    DeviceAuthorizationV1,
    DevicePollResultV1,
    GraphOAuthFeatureGateV1,
    GraphOAuthHttpV1,
    GraphOAuthV1Error,
    JsonHttpResponseV1,
    MicrosoftGraphOAuthSettingsV1,
    MicrosoftGraphOAuthSessionV1,
    OAuthSessionStatusV1,
    RefreshTokenVaultV1,
    StdlibGraphOAuthHttpV1,
    create_microsoft_graph_oauth_v1,
)
from core.phase8_microsoft_graph_read_v1 import (
    ExecutiveOfficeBriefV1,
    GraphReadFeatureGateV1,
    GraphReadV1Error,
    create_microsoft_graph_read_adapter_v1,
)

FEATURE_FLAG: Final = "ONYX_PHASE8_MICROSOFT_GRAPH_LIVE_READ_E2E_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxMicrosoftGraphLiveReadE2E.v1"
ENV_CLIENT_ID: Final = "ONYX_PHASE8_MS_GRAPH_CLIENT_ID"
ENV_TENANT_ID: Final = "ONYX_PHASE8_MS_GRAPH_TENANT_ID"
ENV_ACCOUNT_ID: Final = "ONYX_PHASE8_MS_GRAPH_ACCOUNT_ID"
FORBIDDEN_SECRET_ENVIRONMENT: Final = (
    "ONYX_PHASE8_MS_GRAPH_CLIENT_SECRET",
    "ONYX_PHASE8_MS_GRAPH_PASSWORD",
    "ONYX_PHASE8_MS_GRAPH_REFRESH_TOKEN",
    "ONYX_PHASE8_MS_GRAPH_ACCESS_TOKEN",
)
LIVE_SCOPES: Final = ("User.Read", "Calendars.Read", "Mail.Read", "offline_access")
MAX_THROTTLE_RETRIES: Final = 2
MAX_RETRY_AFTER_SECONDS: Final = 300
REVOCATION_ERRORS: Final = frozenset(
    {"invalid_grant", "interaction_required", "consent_required"}
)
PROBE_NAMES: Final = (
    "sign_in_read",
    "access_expiry_refresh",
    "refresh_rotation",
    "revocation",
    "provider_failure",
    "rate_limit_retry_after",
)
PROBE_MODES: Final = frozenset({"live", "injected_fault"})
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
        "docs/onyx/acceptance/" "VE-P8-MICROSOFT-GRAPH-OAUTH-V1-E6-001.manifest.json",
        "a5d72b9876269bd81b8c26e22d6e79ef96468773c560e86bc38b0b518c740123",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-OAUTH-V1-E6-001.sha256",
        "77fd9772c247308d2c18f9c911684855955a8d390705f992ac1841fee5de6bfa",
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
_OAUTH_ERROR = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RETRY_AFTER = re.compile(r"^[0-9]{1,3}$")
_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_CONSTRUCTION_KEY = object()


class GraphLiveE2EV1Error(RuntimeError):
    pass


class GraphLiveE2EV1ContractError(ValueError):
    pass


class GraphLiveE2EV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class GraphLiveE2EFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GraphLiveE2EV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GraphLiveE2EFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class MicrosoftGraphLiveOnboardingV1:
    """Secret-free public-client onboarding identity.

    Every field is a public identifier: the Entra application (client) ID, the
    tenant and the authorized test-account address. A client secret or user
    credential is structurally rejected and must never exist for this public
    native client or in this repository.
    """

    client_id: str
    tenant_id: str
    account_id: str

    def __post_init__(self) -> None:
        if type(self.client_id) is not str or not _UUID.fullmatch(self.client_id):
            raise GraphLiveE2EV1ContractError("Microsoft client_id is invalid")
        if type(self.tenant_id) is not str or not _TENANT.fullmatch(self.tenant_id):
            raise GraphLiveE2EV1ContractError("Microsoft tenant_id is invalid")
        if type(self.account_id) is not str or not _EMAIL.fullmatch(self.account_id):
            raise GraphLiveE2EV1ContractError("Microsoft account_id is invalid")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "MicrosoftGraphLiveOnboardingV1":
        source = os.environ if environ is None else environ
        for name in FORBIDDEN_SECRET_ENVIRONMENT:
            if source.get(name):
                raise GraphLiveE2EV1Denied(
                    "public-client onboarding must not carry a client secret "
                    "or user credential"
                )
        values = tuple(source.get(name) for name in (
            ENV_CLIENT_ID,
            ENV_TENANT_ID,
            ENV_ACCOUNT_ID,
        ))
        if any(type(value) is not str or not value for value in values):
            raise GraphLiveE2EV1Denied("live onboarding environment is incomplete")
        return cls(*values)

    def settings(self) -> MicrosoftGraphOAuthSettingsV1:
        return MicrosoftGraphOAuthSettingsV1(
            client_id=self.client_id,
            tenant_id=self.tenant_id,
            scopes=LIVE_SCOPES,
        )


@dataclass(frozen=True, slots=True)
class ThrottleObservationV1:
    """One redacted transport observation: route identity, never payloads."""

    route: str
    path: str
    status_code: int
    oauth_error: str | None
    retry_after_seconds: int | None
    waited_seconds: int | None
    attempt: int

    def __post_init__(self) -> None:
        if (
            self.route not in {"identity", "graph"}
            or type(self.path) is not str
            or not self.path.startswith("/")
            or "?" in self.path
            or len(self.path) > 512
            or type(self.status_code) is not int
            or not 100 <= self.status_code <= 599
            or (
                self.oauth_error is not None
                and (
                    type(self.oauth_error) is not str
                    or not _OAUTH_ERROR.fullmatch(self.oauth_error)
                )
            )
            or (
                self.retry_after_seconds is not None
                and (
                    type(self.retry_after_seconds) is not int
                    or not 0 <= self.retry_after_seconds <= MAX_RETRY_AFTER_SECONDS
                )
            )
            or (
                self.waited_seconds is not None
                and (
                    type(self.waited_seconds) is not int
                    or not 0 <= self.waited_seconds <= MAX_RETRY_AFTER_SECONDS
                )
            )
            or type(self.attempt) is not int
            or not 0 <= self.attempt <= MAX_THROTTLE_RETRIES
        ):
            raise GraphLiveE2EV1ContractError("throttle observation is invalid")


def _retry_after_seconds(headers: tuple[tuple[str, str], ...]) -> int | None:
    values = [
        value for name, value in headers if name.casefold() == "retry-after"
    ]
    if not values:
        return None
    if len(values) > 1:
        raise GraphLiveE2EV1Denied("duplicate Retry-After header")
    text = values[0].strip()
    if not _RETRY_AFTER.fullmatch(text):
        raise GraphLiveE2EV1Denied("Retry-After contract drift")
    seconds = int(text)
    if seconds > MAX_RETRY_AFTER_SECONDS:
        raise GraphLiveE2EV1Denied("Retry-After exceeds accepted bound")
    return seconds


def _oauth_error(payload: dict[str, object]) -> str | None:
    value = payload.get("error")
    if type(value) is str and _OAUTH_ERROR.fullmatch(value):
        return value
    return None


class ThrottleAwareGraphOAuthHttpV1:
    """Bounded ``429 Retry-After`` honoring wrapper with redacted observations.

    Per Microsoft Graph throttling guidance the wrapper never retries before
    the provider-supplied delay, uses deterministic bounded backoff when a 429
    omits ``Retry-After``, and never retries any non-429 response. Waiting is
    delegated to an injected sleeper so tests stay deterministic and the
    wrapper itself never blocks on a wall clock.
    """

    __slots__ = ("_inner", "_max_retries", "_observations", "_sleeper")

    def __init__(
        self,
        *,
        inner: GraphOAuthHttpV1,
        sleeper: Callable[[int], None],
        max_retries: int = MAX_THROTTLE_RETRIES,
    ) -> None:
        if not hasattr(inner, "post_form") or not hasattr(inner, "get_json"):
            raise GraphLiveE2EV1ContractError("inner OAuth transport is invalid")
        if not callable(sleeper):
            raise GraphLiveE2EV1ContractError("exact sleeper callable required")
        if type(max_retries) is not int or not 0 <= max_retries <= MAX_THROTTLE_RETRIES:
            raise GraphLiveE2EV1ContractError("throttle retry bound is invalid")
        self._inner = inner
        self._sleeper = sleeper
        self._max_retries = max_retries
        self._observations: list[ThrottleObservationV1] = []

    @property
    def observations(self) -> tuple[ThrottleObservationV1, ...]:
        return tuple(self._observations)

    def _execute(
        self,
        *,
        route: str,
        url: str,
        call: Callable[[], JsonHttpResponseV1],
    ) -> JsonHttpResponseV1:
        path = urllib.parse.urlparse(url).path
        attempt = 0
        while True:
            response = call()
            if type(response) is not JsonHttpResponseV1:
                raise GraphLiveE2EV1ContractError("inner transport response drift")
            error = _oauth_error(response.payload)
            if response.status_code != 429:
                self._observations.append(
                    ThrottleObservationV1(
                        route, path, response.status_code, error, None, None, attempt
                    )
                )
                return response
            retry_after = _retry_after_seconds(response.headers)
            if attempt >= self._max_retries:
                self._observations.append(
                    ThrottleObservationV1(
                        route, path, 429, error, retry_after, None, attempt
                    )
                )
                raise GraphLiveE2EV1Error("Microsoft throttling persisted after bound")
            waited = (
                retry_after
                if retry_after is not None
                else min(MAX_RETRY_AFTER_SECONDS, 2 ** (attempt + 1))
            )
            self._observations.append(
                ThrottleObservationV1(
                    route, path, 429, error, retry_after, waited, attempt
                )
            )
            # RFC 9110 permits Retry-After: 0, meaning retry immediately.
            if waited > 0:
                self._sleeper(waited)
            attempt += 1

    def post_form(
        self,
        *,
        url: str,
        fields: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1:
        return self._execute(
            route="identity",
            url=url,
            call=lambda: self._inner.post_form(
                url=url, fields=fields, timeout_seconds=timeout_seconds
            ),
        )

    def get_json(
        self,
        *,
        url: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1:
        return self._execute(
            route="graph",
            url=url,
            call=lambda: self._inner.get_json(
                url=url,
                query=query,
                headers=headers,
                timeout_seconds=timeout_seconds,
            ),
        )


@dataclass(frozen=True, slots=True)
class LiveProbeResultV1:
    probe: str
    mode: str
    outcome: str
    detail: str
    observations: tuple[ThrottleObservationV1, ...]

    def __post_init__(self) -> None:
        if (
            self.probe not in PROBE_NAMES
            or self.mode not in PROBE_MODES
            or self.outcome != "passed"
            or type(self.detail) is not str
            or not self.detail
            or len(self.detail) > 300
            or any(ord(character) < 32 for character in self.detail)
            or type(self.observations) is not tuple
            or any(
                type(item) is not ThrottleObservationV1 for item in self.observations
            )
        ):
            raise GraphLiveE2EV1ContractError("probe result is invalid")


@dataclass(frozen=True, slots=True)
class LiveReadE2EReportV1:
    schema: str
    workspace_id: str
    principal_id: str
    account_id: str
    tenant_id: str
    client_id: str
    probes: tuple[LiveProbeResultV1, ...]
    probes_missing: tuple[str, ...]
    live_verified: bool
    generated_at: str
    report_sha256: str
    read_only: bool = True


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_OAUTH_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GraphLiveE2EV1Denied(
                "accepted Graph OAuth evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GraphLiveE2EV1Denied("accepted Graph OAuth evidence drift")


def _generated_at(value: object) -> str:
    if type(value) is not str or not _UTC_TIMESTAMP.fullmatch(value):
        raise GraphLiveE2EV1ContractError("generated_at must be an exact UTC time")
    return value


class MicrosoftGraphLiveReadE2EHarnessV1:
    """Deterministic probe harness over the frozen OAuth and read contracts."""

    __slots__ = (
        "_clock_epoch_s",
        "_clock_ms",
        "_credential_alias_name",
        "_aliases",
        "_http",
        "_live_transport",
        "_onboarding",
        "_project_root",
        "_results",
        "_session",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        onboarding: MicrosoftGraphLiveOnboardingV1,
        aliases: WorkspaceAliasCatalogV1,
        credential_alias_name: str,
        session: MicrosoftGraphOAuthSessionV1,
        http: ThrottleAwareGraphOAuthHttpV1,
        live_transport: bool,
        clock_ms: Callable[[], int],
        clock_epoch_s: Callable[[], int],
        project_root: Path,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GraphLiveE2EV1ContractError(
                "use create_microsoft_graph_live_read_e2e_v1"
            )
        if type(live_transport) is not bool:
            raise GraphLiveE2EV1ContractError("live transport marker is invalid")
        self._live_transport = live_transport
        self._onboarding = onboarding
        self._aliases = aliases
        self._credential_alias_name = credential_alias_name
        self._session = session
        self._http = http
        self._clock_ms = clock_ms
        self._clock_epoch_s = clock_epoch_s
        self._project_root = project_root
        self._results: list[LiveProbeResultV1] = []

    def _select_mode(self, value: object) -> str:
        if type(value) is not str or value not in PROBE_MODES:
            raise GraphLiveE2EV1ContractError("probe mode is invalid")
        if value == "live" and not self._live_transport:
            raise GraphLiveE2EV1Denied(
                "live probe mode requires the real HTTPS transport"
            )
        return value

    def _now(self) -> tuple[int, int]:
        now_ms, now_epoch_s = self._clock_ms(), self._clock_epoch_s()
        if type(now_ms) is not int or type(now_epoch_s) is not int:
            raise GraphLiveE2EV1ContractError("clock result is invalid")
        return now_ms, now_epoch_s

    def status(self) -> OAuthSessionStatusV1:
        return self._session.status()

    def begin_device_authorization(self) -> DeviceAuthorizationV1:
        now_ms, now_epoch_s = self._now()
        return self._session.begin_device_authorization(
            now_ms=now_ms, now_epoch_s=now_epoch_s
        )

    def poll_device_authorization(self) -> DevicePollResultV1:
        now_ms, now_epoch_s = self._now()
        return self._session.poll_device_authorization(
            now_ms=now_ms, now_epoch_s=now_epoch_s
        )

    def restore(self) -> OAuthSessionStatusV1:
        now_ms, now_epoch_s = self._now()
        return self._session.restore(now_ms=now_ms, now_epoch_s=now_epoch_s)

    def disconnect(self) -> bool:
        now_ms, _now_epoch_s = self._now()
        return self._session.disconnect(now_ms=now_ms)

    def _daily_brief(
        self,
        *,
        window_start: str,
        window_end: str,
        outlook_timezone: str,
        generated_at: str,
        epoch_override: int | None = None,
    ) -> ExecutiveOfficeBriefV1:
        transport = self._session.create_read_transport(
            clock_epoch_s=(
                self._clock_epoch_s
                if epoch_override is None
                else (lambda: epoch_override)
            ),
            clock_ms=self._clock_ms,
        )
        adapter = create_microsoft_graph_read_adapter_v1(
            gate=GraphReadFeatureGateV1(True),
            aliases=self._aliases,
            credential_alias_name=self._credential_alias_name,
            transport=transport,
            now_ms=self._clock_ms(),
            project_root=self._project_root,
        )
        if adapter is None:
            raise GraphLiveE2EV1Error("Graph read adapter unavailable")
        return adapter.daily_brief(
            window_start=window_start,
            window_end=window_end,
            outlook_timezone=outlook_timezone,
            now_ms=self._clock_ms(),
            generated_at=generated_at,
        )

    def _record(
        self,
        *,
        probe: str,
        mode: str,
        detail: str,
        observation_start: int,
    ) -> LiveProbeResultV1:
        if any(existing.probe == probe for existing in self._results):
            raise GraphLiveE2EV1ContractError("probe already recorded")
        result = LiveProbeResultV1(
            probe,
            mode,
            "passed",
            detail,
            self._http.observations[observation_start:],
        )
        self._results.append(result)
        return result

    def probe_sign_in_read(
        self,
        *,
        mode: str,
        window_start: str,
        window_end: str,
        outlook_timezone: str,
        generated_at: str,
    ) -> LiveProbeResultV1:
        selected = self._select_mode(mode)
        start = len(self._http.observations)
        brief = self._daily_brief(
            window_start=window_start,
            window_end=window_end,
            outlook_timezone=outlook_timezone,
            generated_at=generated_at,
        )
        if brief.account_id.casefold() != self._onboarding.account_id.casefold():
            raise GraphLiveE2EV1Denied("signed-in account/onboarding mismatch")
        if not self._session.status().connected:
            raise GraphLiveE2EV1Error("session is not connected after read")
        return self._record(
            probe="sign_in_read",
            mode=selected,
            detail=(
                "daily brief read completed for the onboarded account; "
                f"events={len(brief.events)} unread={len(brief.unread_messages)}"
            ),
            observation_start=start,
        )

    def probe_access_expiry_refresh(
        self,
        *,
        mode: str,
        window_start: str,
        window_end: str,
        outlook_timezone: str,
        generated_at: str,
    ) -> LiveProbeResultV1:
        selected = self._select_mode(mode)
        status = self._session.status()
        if not status.connected or status.access_expires_at_epoch_s is None:
            raise GraphLiveE2EV1Error("expiry probe requires a connected session")
        start = len(self._http.observations)
        brief = self._daily_brief(
            window_start=window_start,
            window_end=window_end,
            outlook_timezone=outlook_timezone,
            generated_at=generated_at,
            epoch_override=status.access_expires_at_epoch_s,
        )
        observed = self._http.observations[start:]
        refreshes = [
            item
            for item in observed
            if item.route == "identity" and item.status_code == 200
        ]
        if not refreshes:
            raise GraphLiveE2EV1Error("expired access token did not force a refresh")
        if brief.account_id.casefold() != self._onboarding.account_id.casefold():
            raise GraphLiveE2EV1Denied("post-refresh account mismatch")
        return self._record(
            probe="access_expiry_refresh",
            mode=selected,
            detail=(
                "expired access token forced a token-endpoint refresh before "
                "the read succeeded"
            ),
            observation_start=start,
        )

    def probe_refresh_rotation(self, *, mode: str) -> LiveProbeResultV1:
        selected = self._select_mode(mode)
        start = len(self._http.observations)
        first = self.restore()
        second = self.restore()
        observed = self._http.observations[start:]
        refreshes = [
            item
            for item in observed
            if item.route == "identity" and item.status_code == 200
        ]
        if (
            len(refreshes) < 2
            or not first.connected
            or not second.connected
            or not second.refresh_token_present
        ):
            raise GraphLiveE2EV1Error("refresh rotation probe did not complete")
        return self._record(
            probe="refresh_rotation",
            mode=selected,
            detail=(
                "two consecutive vault-backed refreshes succeeded; rotation is "
                "provider-controlled and the vault retains only the latest token"
            ),
            observation_start=start,
        )

    def probe_revocation(self, *, mode: str) -> LiveProbeResultV1:
        selected = self._select_mode(mode)
        start = len(self._http.observations)
        try:
            self.restore()
        except GraphOAuthV1Error:
            pass
        else:
            raise GraphLiveE2EV1Error("revocation probe expected refresh denial")
        observed = self._http.observations[start:]
        identity = [item for item in observed if item.route == "identity"]
        terminal = identity[-1] if identity else None
        status = self._session.status()
        # Only the terminal (non-throttled) token-endpoint denial counts as
        # revocation evidence; a revocation-shaped error inside an earlier 429
        # or a terminal provider failure must not certify revocation.
        if (
            terminal is None
            or terminal.status_code == 429
            or terminal.oauth_error not in REVOCATION_ERRORS
            or status.connected
            or not status.refresh_token_present
        ):
            raise GraphLiveE2EV1Error("revocation was not classified honestly")
        return self._record(
            probe="revocation",
            mode=selected,
            detail=(
                f"refresh denied with {terminal.oauth_error}; session reports "
                "disconnected and the vault credential was not destructively "
                "deleted"
            ),
            observation_start=start,
        )

    def probe_provider_failure(
        self,
        *,
        mode: str,
        window_start: str,
        window_end: str,
        outlook_timezone: str,
        generated_at: str,
    ) -> LiveProbeResultV1:
        selected = self._select_mode(mode)
        start = len(self._http.observations)
        try:
            self._daily_brief(
                window_start=window_start,
                window_end=window_end,
                outlook_timezone=outlook_timezone,
                generated_at=generated_at,
            )
        except (GraphReadV1Error, GraphOAuthV1Error):
            pass
        else:
            raise GraphLiveE2EV1Error("provider failure probe expected a failure")
        observed = self._http.observations[start:]
        failures = [
            item
            for item in observed
            if item.route == "graph" and item.status_code >= 500
        ]
        if len(failures) != 1 or any(
            item.waited_seconds is not None for item in observed
        ):
            raise GraphLiveE2EV1Error(
                "provider failure must surface once without an automatic retry"
            )
        return self._record(
            probe="provider_failure",
            mode=selected,
            detail=(
                f"provider status {failures[0].status_code} surfaced as a typed "
                "error with zero automatic retries"
            ),
            observation_start=start,
        )

    def probe_rate_limit_retry_after(
        self,
        *,
        mode: str,
        window_start: str,
        window_end: str,
        outlook_timezone: str,
        generated_at: str,
    ) -> LiveProbeResultV1:
        selected = self._select_mode(mode)
        start = len(self._http.observations)
        brief = self._daily_brief(
            window_start=window_start,
            window_end=window_end,
            outlook_timezone=outlook_timezone,
            generated_at=generated_at,
        )
        observed = self._http.observations[start:]
        throttled = [item for item in observed if item.status_code == 429]
        if not throttled:
            raise GraphLiveE2EV1Error("rate-limit probe observed no 429 response")
        if any(
            item.retry_after_seconds is not None
            and item.waited_seconds != item.retry_after_seconds
            for item in throttled
        ):
            raise GraphLiveE2EV1Error("Retry-After delay was not honored exactly")
        if brief.account_id.casefold() != self._onboarding.account_id.casefold():
            raise GraphLiveE2EV1Denied("post-throttle account mismatch")
        return self._record(
            probe="rate_limit_retry_after",
            mode=selected,
            detail=(
                f"{len(throttled)} throttled response(s) honored Retry-After "
                "exactly before the read completed"
            ),
            observation_start=start,
        )

    def report(self, *, generated_at: str) -> LiveReadE2EReportV1:
        stamp = _generated_at(generated_at)
        probes = tuple(self._results)
        recorded = {item.probe for item in probes}
        if not probes:
            raise GraphLiveE2EV1ContractError("report requires at least one probe")
        missing = tuple(name for name in PROBE_NAMES if name not in recorded)
        live_verified = not missing and all(
            item.mode == "live" for item in probes
        )
        payload = {
            "schema": SCHEMA,
            "workspace_id": self._aliases.workspace_id,
            "principal_id": self._aliases.principal_id,
            "account_id": self._onboarding.account_id,
            "tenant_id": self._onboarding.tenant_id,
            "client_id": self._onboarding.client_id,
            "probes": [asdict(item) for item in probes],
            "probes_missing": list(missing),
            "live_verified": live_verified,
            "generated_at": stamp,
            "read_only": True,
        }
        return LiveReadE2EReportV1(
            SCHEMA,
            self._aliases.workspace_id,
            self._aliases.principal_id,
            self._onboarding.account_id,
            self._onboarding.tenant_id,
            self._onboarding.client_id,
            probes,
            missing,
            live_verified,
            stamp,
            hashlib.sha256(_canonical(payload)).hexdigest(),
        )


def create_microsoft_graph_live_read_e2e_v1(
    *,
    gate: GraphLiveE2EFeatureGateV1 | None = None,
    onboarding: MicrosoftGraphLiveOnboardingV1 | None = None,
    aliases: WorkspaceAliasCatalogV1 | None = None,
    credential_alias_name: str | None = None,
    http: GraphOAuthHttpV1 | None = None,
    vault: RefreshTokenVaultV1 | None = None,
    sleeper: Callable[[int], None] | None = None,
    clock_ms: Callable[[], int] | None = None,
    clock_epoch_s: Callable[[], int] | None = None,
    project_root: Path | str | None = None,
) -> MicrosoftGraphLiveReadE2EHarnessV1 | None:
    selected = GraphLiveE2EFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not GraphLiveE2EFeatureGateV1:
        raise GraphLiveE2EV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    root = (
        Path(__file__).resolve().parents[1]
        if project_root is None
        else Path(project_root).resolve()
    )
    _verify_entry(root)
    chosen_onboarding = (
        MicrosoftGraphLiveOnboardingV1.from_environ()
        if onboarding is None
        else onboarding
    )
    if type(chosen_onboarding) is not MicrosoftGraphLiveOnboardingV1:
        raise GraphLiveE2EV1ContractError(
            "exact MicrosoftGraphLiveOnboardingV1 required"
        )
    if (
        aliases is None
        or credential_alias_name is None
        or sleeper is None
        or clock_ms is None
        or clock_epoch_s is None
    ):
        raise GraphLiveE2EV1ContractError("enabled harness requires complete bindings")
    if type(aliases) is not WorkspaceAliasCatalogV1:
        raise GraphLiveE2EV1ContractError("exact WorkspaceAliasCatalogV1 required")
    if not callable(sleeper) or not callable(clock_ms) or not callable(clock_epoch_s):
        raise GraphLiveE2EV1ContractError("exact sleeper and clocks are required")
    now_ms = clock_ms()
    if type(now_ms) is not int or now_ms < 0:
        raise GraphLiveE2EV1ContractError("clock result is invalid")
    try:
        credential = aliases.get(
            kind="credential",
            alias_name=credential_alias_name,
            now_ms=now_ms,
        )
    except WorkspaceAliasV1Denied as exc:
        raise GraphLiveE2EV1Denied("Graph credential alias unavailable") from exc
    account = credential.account_id or ""
    if account.casefold() != chosen_onboarding.account_id.casefold() or (
        credential.tenant_id is not None
        and credential.tenant_id.casefold() != chosen_onboarding.tenant_id.casefold()
    ):
        raise GraphLiveE2EV1Denied("onboarding/alias identity mismatch")
    inner = StdlibGraphOAuthHttpV1() if http is None else http
    live_transport = type(inner) is StdlibGraphOAuthHttpV1
    throttle = ThrottleAwareGraphOAuthHttpV1(inner=inner, sleeper=sleeper)
    session = create_microsoft_graph_oauth_v1(
        gate=GraphOAuthFeatureGateV1(True),
        aliases=aliases,
        credential_alias_name=credential_alias_name,
        settings=chosen_onboarding.settings(),
        http=throttle,
        vault=vault,
        now_ms=now_ms,
        project_root=root,
    )
    if session is None:
        raise GraphLiveE2EV1Error("OAuth session unavailable")
    return MicrosoftGraphLiveReadE2EHarnessV1(
        construction_key=_CONSTRUCTION_KEY,
        onboarding=chosen_onboarding,
        aliases=aliases,
        credential_alias_name=credential_alias_name,
        session=session,
        http=throttle,
        live_transport=live_transport,
        clock_ms=clock_ms,
        clock_epoch_s=clock_epoch_s,
        project_root=root,
    )


__all__ = [
    "ACCEPTED_OAUTH_ROOTS",
    "ENV_ACCOUNT_ID",
    "ENV_CLIENT_ID",
    "ENV_TENANT_ID",
    "FEATURE_FLAG",
    "FORBIDDEN_SECRET_ENVIRONMENT",
    "GraphLiveE2EFeatureGateV1",
    "GraphLiveE2EV1ContractError",
    "GraphLiveE2EV1Denied",
    "GraphLiveE2EV1Error",
    "LIVE_SCOPES",
    "LiveProbeResultV1",
    "LiveReadE2EReportV1",
    "MicrosoftGraphLiveOnboardingV1",
    "MicrosoftGraphLiveReadE2EHarnessV1",
    "PROBE_NAMES",
    "ThrottleAwareGraphOAuthHttpV1",
    "ThrottleObservationV1",
    "create_microsoft_graph_live_read_e2e_v1",
]
