from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from unittest.mock import patch

import pytest

from core.control_plane import ControlPlaneStore
from core.phase7_workspace_aliases_v1 import (
    CredentialAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    ENV_ACCOUNT_ID,
    ENV_CLIENT_ID,
    ENV_TENANT_ID,
    FEATURE_FLAG,
    FORBIDDEN_SECRET_ENVIRONMENT,
    LIVE_SCOPES,
    PROBE_NAMES,
    GraphLiveE2EFeatureGateV1,
    GraphLiveE2EV1ContractError,
    GraphLiveE2EV1Denied,
    GraphLiveE2EV1Error,
    MicrosoftGraphLiveOnboardingV1,
    ThrottleAwareGraphOAuthHttpV1,
    ThrottleObservationV1,
    create_microsoft_graph_live_read_e2e_v1,
)
from core.phase8_microsoft_graph_oauth_v1 import JsonHttpResponseV1
from core.workspaces import WorkspaceRegistry

ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1_785_000_000_000
NOW_S = 1_785_000_000
KEY = bytes(range(1, 33))
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ACCOUNT_ID = "owner@cyryxlabs.com"
WINDOW = {
    "window_start": "2026-07-23T00:00:00Z",
    "window_end": "2026-07-24T00:00:00Z",
    "outlook_timezone": "UTC",
    "generated_at": "2026-07-23T01:00:00Z",
}


@dataclass
class Fixture:
    control: ControlPlaneStore
    registry: WorkspaceRegistry


@dataclass(frozen=True)
class Queued:
    method: str
    response: JsonHttpResponseV1


@dataclass(frozen=True)
class HttpCall:
    method: str
    url: str
    values: tuple[tuple[str, str], ...]
    headers: tuple[tuple[str, str], ...]


class FakeHttp:
    def __init__(self, responses: Iterable[Queued] = ()) -> None:
        self.responses = list(responses)
        self.calls: list[HttpCall] = []

    def _next(self, method: str) -> JsonHttpResponseV1:
        if not self.responses:
            raise AssertionError(f"unexpected {method} request")
        item = self.responses.pop(0)
        if item.method != method:
            raise AssertionError(f"expected {item.method}, got {method}")
        return item.response

    def post_form(
        self,
        *,
        url: str,
        fields: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1:
        assert timeout_seconds == 30
        self.calls.append(HttpCall("POST", url, fields, ()))
        return self._next("POST")

    def get_json(
        self,
        *,
        url: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1:
        assert timeout_seconds == 30
        self.calls.append(HttpCall("GET", url, query, headers))
        return self._next("GET")


class FakeVault:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.writes: list[str] = []
        self.deletes = 0

    def get_refresh_token(self) -> str | None:
        return self.value

    def set_refresh_token(self, value: str) -> None:
        self.value = value
        self.writes.append(value)

    def delete_refresh_token(self) -> bool:
        existed = self.value is not None
        self.value = None
        self.deletes += 1
        return existed


class MutableClock:
    def __init__(self, ms: int, epoch_s: int) -> None:
        self.ms = ms
        self.epoch_s = epoch_s


@pytest.fixture
def fixture(tmp_path: Path) -> Iterable[Fixture]:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=tmp_path,
    ):
        control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    registry.register(
        "cyryx-main",
        display_name="Cyryx Main",
        workspace_class="cyryx",
    )
    value = Fixture(control, registry)
    try:
        yield value
    finally:
        control.close()


def _catalog(
    fixture: Fixture,
    *,
    account_id: str = ACCOUNT_ID,
    tenant_id: str = TENANT_ID,
):
    catalog = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=fixture.registry,
        workspace_id="cyryx-main",
        principal_id="owner:pedro",
        integrity_key=KEY,
    )
    assert catalog is not None
    catalog.register(
        "microsoft-primary",
        CredentialAliasSpecV1(
            provider="microsoft-graph",
            account_id=account_id,
            tenant_id=tenant_id,
            scopes=("Calendars.Read", "Mail.Read"),
            rotate_after_ms=NOW_MS + 100_000_000,
            revoke_after_ms=NOW_MS + 200_000_000,
        ),
        now_ms=NOW_MS,
    )
    return catalog


def _onboarding(**changes: object) -> MicrosoftGraphLiveOnboardingV1:
    values: dict[str, object] = {
        "client_id": CLIENT_ID,
        "tenant_id": TENANT_ID,
        "account_id": ACCOUNT_ID,
    }
    values.update(changes)
    return MicrosoftGraphLiveOnboardingV1(**values)  # type: ignore[arg-type]


def _harness(
    fixture: Fixture,
    *,
    http: FakeHttp,
    vault: FakeVault | None = None,
    catalog=None,
    onboarding: MicrosoftGraphLiveOnboardingV1 | None = None,
    clock: MutableClock | None = None,
):
    selected_catalog = _catalog(fixture) if catalog is None else catalog
    selected_clock = MutableClock(NOW_MS + 1, NOW_S) if clock is None else clock
    sleeps: list[int] = []
    harness = create_microsoft_graph_live_read_e2e_v1(
        gate=GraphLiveE2EFeatureGateV1(True),
        onboarding=_onboarding() if onboarding is None else onboarding,
        aliases=selected_catalog,
        credential_alias_name="microsoft-primary",
        http=http,
        vault=FakeVault("refresh-token-0") if vault is None else vault,
        sleeper=sleeps.append,
        clock_ms=lambda: selected_clock.ms,
        clock_epoch_s=lambda: selected_clock.epoch_s,
        project_root=ROOT,
    )
    assert harness is not None
    return harness, sleeps, selected_clock


def _device_response() -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {
            "device_code": "device-secret-1",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
            "interval": 5,
            "message": "Open the Microsoft sign-in page and enter the code.",
        },
    )


def _token_response(
    *,
    access: str = "access-token-1",
    refresh: str | None = "refresh-token-1",
) -> JsonHttpResponseV1:
    payload: dict[str, object] = {
        "token_type": "Bearer",
        "access_token": access,
        "expires_in": 3600,
        "scope": "User.Read Calendars.Read Mail.Read",
    }
    if refresh is not None:
        payload["refresh_token"] = refresh
    return JsonHttpResponseV1(200, payload)


def _profile() -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {"id": "user-1", "mail": ACCOUNT_ID, "userPrincipalName": ACCOUNT_ID},
    )


def _empty_page() -> JsonHttpResponseV1:
    return JsonHttpResponseV1(200, {"value": []})


def test_feature_gate_is_exact_and_default_off_returns_before_entry() -> None:
    assert not GraphLiveE2EFeatureGateV1.from_environ({}).enabled
    assert GraphLiveE2EFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", "True", " true", "true ", "yes"):
        assert not GraphLiveE2EFeatureGateV1.from_environ(
            {FEATURE_FLAG: value}
        ).enabled
    assert (
        create_microsoft_graph_live_read_e2e_v1(
            gate=GraphLiveE2EFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"client_id": "not-a-client-id"},
        {"client_id": 7},
        {"tenant_id": "cyryx-labs"},
        {"account_id": "not-an-address"},
    ],
)
def test_onboarding_requires_exact_public_identifiers(
    changes: dict[str, object],
) -> None:
    with pytest.raises(GraphLiveE2EV1ContractError):
        _onboarding(**changes)


def test_onboarding_environment_rejects_secret_material_and_incomplete() -> None:
    complete = {
        ENV_CLIENT_ID: CLIENT_ID,
        ENV_TENANT_ID: TENANT_ID,
        ENV_ACCOUNT_ID: ACCOUNT_ID,
    }
    onboarding = MicrosoftGraphLiveOnboardingV1.from_environ(complete)
    assert onboarding.client_id == CLIENT_ID
    for name in FORBIDDEN_SECRET_ENVIRONMENT:
        with pytest.raises(GraphLiveE2EV1Denied, match="client secret"):
            MicrosoftGraphLiveOnboardingV1.from_environ(
                {**complete, name: "hunter2-secret-value"}
            )
    for missing in (ENV_CLIENT_ID, ENV_TENANT_ID, ENV_ACCOUNT_ID):
        partial = {
            name: value for name, value in complete.items() if name != missing
        }
        with pytest.raises(GraphLiveE2EV1Denied, match="incomplete"):
            MicrosoftGraphLiveOnboardingV1.from_environ(partial)


def test_onboarding_settings_compose_exact_read_scopes() -> None:
    settings = _onboarding().settings()
    assert settings.client_id == CLIENT_ID
    assert settings.tenant_id == TENANT_ID
    assert settings.scopes == LIVE_SCOPES


def test_factory_is_sealed_complete_and_bound_to_accepted_oauth(
    fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GraphLiveE2EV1ContractError, match="sealed feature gate"):
        create_microsoft_graph_live_read_e2e_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(GraphLiveE2EV1ContractError, match="complete bindings"):
        create_microsoft_graph_live_read_e2e_v1(
            gate=GraphLiveE2EFeatureGateV1(True),
            onboarding=_onboarding(),
            project_root=ROOT,
        )
    monkeypatch.setattr(
        "core.phase8_microsoft_graph_live_read_e2e_v1.ACCEPTED_OAUTH_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(GraphLiveE2EV1Denied, match="evidence unavailable"):
        create_microsoft_graph_live_read_e2e_v1(
            gate=GraphLiveE2EFeatureGateV1(True),
            project_root=ROOT,
        )
    monkeypatch.setattr(
        "core.phase8_microsoft_graph_live_read_e2e_v1.ACCEPTED_OAUTH_ROOTS",
        (
            (
                "docs/onyx/checkpoints/phase8-microsoft-graph-oauth-v1/"
                "manifest.json",
                "1" * 64,
            ),
        ),
    )
    with pytest.raises(GraphLiveE2EV1Denied, match="evidence drift"):
        create_microsoft_graph_live_read_e2e_v1(
            gate=GraphLiveE2EFeatureGateV1(True),
            project_root=ROOT,
        )


@pytest.mark.parametrize(
    ("alias_account", "alias_tenant"),
    [
        ("someone-else@cyryxlabs.com", TENANT_ID),
        (ACCOUNT_ID, "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"),
    ],
)
def test_factory_denies_onboarding_alias_identity_mismatch(
    fixture: Fixture,
    alias_account: str,
    alias_tenant: str,
) -> None:
    catalog = _catalog(
        fixture, account_id=alias_account, tenant_id=alias_tenant
    )
    with pytest.raises(GraphLiveE2EV1Denied, match="identity mismatch"):
        _harness(fixture, http=FakeHttp(), catalog=catalog)


def test_throttle_wrapper_requires_exact_construction() -> None:
    with pytest.raises(GraphLiveE2EV1ContractError, match="inner OAuth transport"):
        ThrottleAwareGraphOAuthHttpV1(inner=object(), sleeper=lambda _s: None)
    with pytest.raises(GraphLiveE2EV1ContractError, match="sleeper"):
        ThrottleAwareGraphOAuthHttpV1(inner=FakeHttp(), sleeper=None)  # type: ignore[arg-type]
    with pytest.raises(GraphLiveE2EV1ContractError, match="retry bound"):
        ThrottleAwareGraphOAuthHttpV1(
            inner=FakeHttp(),
            sleeper=lambda _s: None,
            max_retries="2",  # type: ignore[arg-type]
        )
    with pytest.raises(GraphLiveE2EV1ContractError, match="retry bound"):
        ThrottleAwareGraphOAuthHttpV1(
            inner=FakeHttp(),
            sleeper=lambda _s: None,
            max_retries=3,
        )


def test_retry_after_is_honored_exactly() -> None:
    inner = FakeHttp(
        [
            Queued(
                "GET",
                JsonHttpResponseV1(429, {}, (("Retry-After", "7"),)),
            ),
            Queued("GET", _empty_page()),
        ]
    )
    sleeps: list[int] = []
    wrapper = ThrottleAwareGraphOAuthHttpV1(inner=inner, sleeper=sleeps.append)
    response = wrapper.get_json(
        url="https://graph.microsoft.com/v1.0/me/messages",
        query=(("$top", "1"),),
        headers=(),
        timeout_seconds=30,
    )
    assert response.status_code == 200
    assert sleeps == [7]
    first, second = wrapper.observations
    assert (first.status_code, first.retry_after_seconds, first.waited_seconds) == (
        429,
        7,
        7,
    )
    assert (first.route, first.path, first.attempt) == (
        "graph",
        "/v1.0/me/messages",
        0,
    )
    assert (second.status_code, second.attempt) == (200, 1)


def test_missing_retry_after_uses_bounded_deterministic_backoff() -> None:
    inner = FakeHttp(
        [
            Queued("GET", JsonHttpResponseV1(429, {})),
            Queued("GET", JsonHttpResponseV1(429, {})),
            Queued("GET", _empty_page()),
        ]
    )
    sleeps: list[int] = []
    wrapper = ThrottleAwareGraphOAuthHttpV1(inner=inner, sleeper=sleeps.append)
    response = wrapper.get_json(
        url="https://graph.microsoft.com/v1.0/me/messages",
        query=(),
        headers=(),
        timeout_seconds=30,
    )
    assert response.status_code == 200
    assert sleeps == [2, 4]
    throttled = [item for item in wrapper.observations if item.status_code == 429]
    assert [item.retry_after_seconds for item in throttled] == [None, None]
    assert [item.waited_seconds for item in throttled] == [2, 4]


def test_throttle_bound_exhaustion_raises_typed_error() -> None:
    inner = FakeHttp(
        [
            Queued("POST", JsonHttpResponseV1(429, {}, (("Retry-After", "1"),))),
            Queued("POST", JsonHttpResponseV1(429, {}, (("Retry-After", "1"),))),
            Queued("POST", JsonHttpResponseV1(429, {}, (("Retry-After", "1"),))),
        ]
    )
    sleeps: list[int] = []
    wrapper = ThrottleAwareGraphOAuthHttpV1(inner=inner, sleeper=sleeps.append)
    with pytest.raises(GraphLiveE2EV1Error, match="throttling persisted"):
        wrapper.post_form(
            url=f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            fields=(("client_id", CLIENT_ID),),
            timeout_seconds=30,
        )
    assert sleeps == [1, 1]
    last = wrapper.observations[-1]
    assert (last.route, last.attempt, last.waited_seconds) == ("identity", 2, None)


@pytest.mark.parametrize(
    "headers",
    [
        (("Retry-After", "3"), ("retry-after", "4")),
        (("Retry-After", "soon"),),
        (("Retry-After", "301"),),
    ],
)
def test_retry_after_contract_drift_is_denied(
    headers: tuple[tuple[str, str], ...],
) -> None:
    inner = FakeHttp([Queued("GET", JsonHttpResponseV1(429, {}, headers))])
    wrapper = ThrottleAwareGraphOAuthHttpV1(
        inner=inner, sleeper=lambda _s: None
    )
    with pytest.raises(GraphLiveE2EV1Denied, match="Retry-After"):
        wrapper.get_json(
            url="https://graph.microsoft.com/v1.0/me/messages",
            query=(),
            headers=(),
            timeout_seconds=30,
        )


def test_retry_after_zero_is_honored_with_immediate_retry() -> None:
    inner = FakeHttp(
        [
            Queued("GET", JsonHttpResponseV1(429, {}, (("Retry-After", "0"),))),
            Queued("GET", _empty_page()),
        ]
    )
    sleeps: list[int] = []
    wrapper = ThrottleAwareGraphOAuthHttpV1(inner=inner, sleeper=sleeps.append)
    response = wrapper.get_json(
        url="https://graph.microsoft.com/v1.0/me/messages",
        query=(),
        headers=(),
        timeout_seconds=30,
    )
    assert response.status_code == 200
    assert sleeps == []
    throttled = wrapper.observations[0]
    assert (throttled.retry_after_seconds, throttled.waited_seconds) == (0, 0)


def test_non_429_responses_are_never_retried() -> None:
    inner = FakeHttp([Queued("GET", JsonHttpResponseV1(503, {}))])
    sleeps: list[int] = []
    wrapper = ThrottleAwareGraphOAuthHttpV1(inner=inner, sleeper=sleeps.append)
    response = wrapper.get_json(
        url="https://graph.microsoft.com/v1.0/me/messages",
        query=(),
        headers=(),
        timeout_seconds=30,
    )
    assert response.status_code == 503
    assert sleeps == []
    assert len(inner.calls) == 1
    assert wrapper.observations[0].status_code == 503


@pytest.mark.parametrize(
    "values",
    [
        ("browser", "/v1.0/me", 200, None, None, None, 0),
        ("graph", "/v1.0/me?x=1", 200, None, None, None, 0),
        ("graph", "/v1.0/me", 200, "Not An Error!", None, None, 0),
        ("graph", "/v1.0/me", 429, None, -1, None, 0),
        ("graph", "/v1.0/me", 429, None, None, None, 9),
    ],
)
def test_throttle_observation_contract_rejects_drift(
    values: tuple[object, ...],
) -> None:
    with pytest.raises(GraphLiveE2EV1ContractError):
        ThrottleObservationV1(*values)  # type: ignore[arg-type]


def test_full_probe_sequence_produces_redacted_report(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            # device sign-in
            Queued("POST", _device_response()),
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
            # sign_in_read
            Queued("GET", _empty_page()),
            Queued("GET", _empty_page()),
            # access_expiry_refresh
            Queued(
                "POST",
                _token_response(access="access-token-2", refresh="refresh-token-2"),
            ),
            Queued("GET", _profile()),
            Queued("GET", _empty_page()),
            Queued("GET", _empty_page()),
            # refresh_rotation
            Queued(
                "POST",
                _token_response(access="access-token-3", refresh="refresh-token-3"),
            ),
            Queued("GET", _profile()),
            Queued(
                "POST",
                _token_response(access="access-token-4", refresh="refresh-token-4"),
            ),
            Queued("GET", _profile()),
            # rate_limit_retry_after
            Queued("GET", JsonHttpResponseV1(429, {}, (("Retry-After", "3"),))),
            Queued("GET", _empty_page()),
            Queued("GET", _empty_page()),
            # provider_failure
            Queued(
                "GET",
                JsonHttpResponseV1(500, {"error": {"code": "InternalServerError"}}),
            ),
            # revocation
            Queued("POST", JsonHttpResponseV1(400, {"error": "invalid_grant"})),
        ]
    )
    vault = FakeVault()
    clock = MutableClock(NOW_MS + 1, NOW_S)
    harness, sleeps, clock = _harness(
        fixture, http=http, vault=vault, clock=clock
    )
    challenge = harness.begin_device_authorization()
    assert challenge.user_code == "ABCD-EFGH"
    clock.epoch_s += 5
    completed = harness.poll_device_authorization()
    assert completed.status == "complete"
    assert vault.value == "refresh-token-1"

    sign_in = harness.probe_sign_in_read(mode="injected_fault", **WINDOW)
    assert sign_in.outcome == "passed"

    expiry = harness.probe_access_expiry_refresh(mode="injected_fault", **WINDOW)
    assert vault.value == "refresh-token-2"
    assert any(item.route == "identity" for item in expiry.observations)

    rotation = harness.probe_refresh_rotation(mode="injected_fault")
    assert vault.value == "refresh-token-4"
    assert rotation.outcome == "passed"

    throttled = harness.probe_rate_limit_retry_after(
        mode="injected_fault", **WINDOW
    )
    assert sleeps == [3]
    assert any(
        item.status_code == 429 and item.waited_seconds == 3
        for item in throttled.observations
    )

    failure = harness.probe_provider_failure(mode="injected_fault", **WINDOW)
    assert "status 500" in failure.detail

    revocation = harness.probe_revocation(mode="injected_fault")
    assert "invalid_grant" in revocation.detail
    assert vault.value == "refresh-token-4"
    assert not harness.status().connected
    assert harness.status().refresh_token_present

    report = harness.report(generated_at="2026-07-23T12:00:00Z")
    assert {item.probe for item in report.probes} == set(PROBE_NAMES)
    assert report.probes_missing == ()
    assert report.live_verified is False
    assert report.account_id == ACCOUNT_ID
    assert len(report.report_sha256) == 64
    serialized = repr(report)
    for secret in (
        "access-token",
        "refresh-token",
        "device-secret",
        "Bearer",
    ):
        assert secret not in serialized
    assert not http.responses


def test_live_mode_requires_real_transport_and_valid_mode(
    fixture: Fixture,
) -> None:
    harness, _sleeps, _clock = _harness(fixture, http=FakeHttp())
    with pytest.raises(GraphLiveE2EV1Denied, match="real HTTPS transport"):
        harness.probe_refresh_rotation(mode="live")
    with pytest.raises(GraphLiveE2EV1ContractError, match="probe mode"):
        harness.probe_refresh_rotation(mode="simulated")


def test_expiry_probe_requires_connected_session(fixture: Fixture) -> None:
    harness, _sleeps, _clock = _harness(fixture, http=FakeHttp())
    with pytest.raises(GraphLiveE2EV1Error, match="connected session"):
        harness.probe_access_expiry_refresh(mode="injected_fault", **WINDOW)


def test_revocation_probe_rejects_provider_failure_terminal(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            Queued(
                "POST",
                JsonHttpResponseV1(
                    429,
                    {"error": "invalid_grant"},
                    (("Retry-After", "1"),),
                ),
            ),
            Queued("POST", JsonHttpResponseV1(500, {"error": "server_error"})),
        ]
    )
    harness, sleeps, _clock = _harness(fixture, http=http)
    with pytest.raises(GraphLiveE2EV1Error, match="not classified honestly"):
        harness.probe_revocation(mode="injected_fault")
    assert sleeps == [1]


def test_revocation_probe_requires_actual_denial(fixture: Fixture) -> None:
    http = FakeHttp(
        [
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
        ]
    )
    harness, _sleeps, _clock = _harness(fixture, http=http)
    with pytest.raises(GraphLiveE2EV1Error, match="expected refresh denial"):
        harness.probe_revocation(mode="injected_fault")


def test_report_lists_missing_probes_and_denies_duplicates(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
            Queued("POST", _token_response(access="access-token-2")),
            Queued("GET", _profile()),
            Queued("POST", _token_response(access="access-token-3")),
            Queued("GET", _profile()),
            Queued("POST", _token_response(access="access-token-4")),
            Queued("GET", _profile()),
        ]
    )
    harness, _sleeps, _clock = _harness(fixture, http=http)
    with pytest.raises(GraphLiveE2EV1ContractError, match="at least one probe"):
        harness.report(generated_at="2026-07-23T12:00:00Z")
    harness.probe_refresh_rotation(mode="injected_fault")
    with pytest.raises(GraphLiveE2EV1ContractError, match="already recorded"):
        harness.probe_refresh_rotation(mode="injected_fault")
    partial = harness.report(generated_at="2026-07-23T12:00:00Z")
    assert partial.live_verified is False
    assert set(partial.probes_missing) == set(PROBE_NAMES) - {"refresh_rotation"}
    assert len(partial.probes_missing) == 5


def test_report_rejects_untrusted_generated_at(fixture: Fixture) -> None:
    harness, _sleeps, _clock = _harness(fixture, http=FakeHttp())
    with pytest.raises(GraphLiveE2EV1ContractError, match="exact UTC time"):
        harness.report(generated_at="yesterday")


def test_disconnect_delegates_and_deletes_vault_token(fixture: Fixture) -> None:
    vault = FakeVault("refresh-token-0")
    harness, _sleeps, _clock = _harness(fixture, http=FakeHttp(), vault=vault)
    assert harness.disconnect() is True
    assert vault.value is None
    assert vault.deletes == 1


def test_module_has_no_graph_mutation_or_live_wiring() -> None:
    source = (
        ROOT / "core" / "phase8_microsoft_graph_live_read_e2e_v1.py"
    ).read_text(encoding="utf-8")
    assert "Mail.Send" not in source
    assert "Calendars.ReadWrite" not in source
    assert "client_secret" not in source
    assert "def send" not in source
    assert "def create_event" not in source
    assert "def patch(" not in source
    assert "def delete(" not in source
    assert "main.py" not in source
    assert "dashboard" not in source
    assert "subprocess" not in source
    assert "time.sleep" not in source
    assert 'FEATURE_FLAG: Final = "ONYX_PHASE8_MICROSOFT_GRAPH_LIVE_READ_E2E_V1"' in (
        source
    )
