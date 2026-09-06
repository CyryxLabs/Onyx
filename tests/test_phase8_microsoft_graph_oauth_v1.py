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
from core.phase8_microsoft_graph_oauth_v1 import (
    DEVICE_GRANT,
    FEATURE_FLAG,
    DevicePollResultV1,
    GraphOAuthFeatureGateV1,
    GraphOAuthV1ContractError,
    GraphOAuthV1Denied,
    GraphOAuthV1Error,
    JsonHttpResponseV1,
    OAuthSessionStatusV1,
    MicrosoftGraphOAuthSettingsV1,
    NativeGraphRefreshTokenVaultV1,
    StdlibGraphOAuthHttpV1,
    create_microsoft_graph_oauth_v1,
)
from core.phase8_microsoft_graph_read_v1 import (
    GraphReadFeatureGateV1,
    create_microsoft_graph_read_adapter_v1,
)
from core.workspaces import WorkspaceRegistry

ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1_785_000_000_000
NOW_S = 1_785_000_000
KEY = bytes(range(1, 33))
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
SCOPES = ("User.Read", "Calendars.Read", "Mail.Read", "offline_access")


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
    provider: str = "microsoft-graph",
    tenant_id: str = TENANT_ID,
    scopes: tuple[str, ...] = ("Calendars.Read", "Mail.Read"),
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
            provider=provider,
            account_id="owner@cyryxlabs.com",
            tenant_id=tenant_id,
            scopes=scopes,
            rotate_after_ms=NOW_MS + 100_000,
            revoke_after_ms=NOW_MS + 200_000,
        ),
        now_ms=NOW_MS,
    )
    return catalog


def _settings(**changes: object) -> MicrosoftGraphOAuthSettingsV1:
    values: dict[str, object] = {
        "client_id": CLIENT_ID,
        "tenant_id": TENANT_ID,
        "scopes": SCOPES,
    }
    values.update(changes)
    return MicrosoftGraphOAuthSettingsV1(**values)  # type: ignore[arg-type]


def _session(
    fixture: Fixture,
    *,
    http: FakeHttp | None = None,
    vault: FakeVault | None = None,
    catalog=None,
    settings: MicrosoftGraphOAuthSettingsV1 | None = None,
):
    selected_catalog = _catalog(fixture) if catalog is None else catalog
    selected_http = FakeHttp() if http is None else http
    selected_vault = FakeVault() if vault is None else vault
    session = create_microsoft_graph_oauth_v1(
        gate=GraphOAuthFeatureGateV1(True),
        aliases=selected_catalog,
        credential_alias_name="microsoft-primary",
        settings=_settings() if settings is None else settings,
        http=selected_http,
        vault=selected_vault,
        now_ms=NOW_MS,
        project_root=ROOT,
    )
    assert session is not None
    return selected_catalog, selected_http, selected_vault, session


def _device_response(**changes: object) -> JsonHttpResponseV1:
    payload: dict[str, object] = {
        "device_code": "device-secret-1",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://microsoft.com/devicelogin",
        "expires_in": 900,
        "interval": 5,
        "message": "Open the Microsoft sign-in page and enter the displayed code.",
    }
    payload.update(changes)
    return JsonHttpResponseV1(200, payload)


def _token_response(
    *,
    access: str = "access-token-1",
    refresh: str | None = "refresh-token-1",
    scopes: str = "User.Read Calendars.Read Mail.Read",
) -> JsonHttpResponseV1:
    payload: dict[str, object] = {
        "token_type": "Bearer",
        "access_token": access,
        "expires_in": 3600,
        "scope": scopes,
    }
    if refresh is not None:
        payload["refresh_token"] = refresh
    return JsonHttpResponseV1(200, payload)


def _profile(
    *,
    mail: str = "owner@cyryxlabs.com",
) -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {
            "id": "user-1",
            "mail": mail,
            "userPrincipalName": mail,
        },
    )


def test_feature_gate_is_exact_and_default_off_returns_before_entry() -> None:
    assert not GraphOAuthFeatureGateV1.from_environ({}).enabled
    assert GraphOAuthFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", "True", " true", "true ", "yes"):
        assert not GraphOAuthFeatureGateV1.from_environ({FEATURE_FLAG: value}).enabled
    assert (
        create_microsoft_graph_oauth_v1(
            gate=GraphOAuthFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"client_id": "not-a-client-id"},
        {"tenant_id": "cyryx-labs"},
        {"scopes": ("Calendars.Read", "Mail.Read", "offline_access")},
        {"scopes": ("User.Read", "Calendars.Read", "Mail.Read")},
        {"scopes": ("User.Read", "Calendars.ReadWrite", "Mail.Read", "offline_access")},
        {"scopes": ("User.Read", "Calendars.Read", "Mail.Send", "offline_access")},
    ],
)
def test_settings_require_exact_public_client_tenant_and_read_scopes(
    changes: dict[str, object],
) -> None:
    with pytest.raises(GraphOAuthV1ContractError):
        _settings(**changes)


def test_factory_is_sealed_complete_and_bound_to_accepted_read(
    fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GraphOAuthV1ContractError, match="sealed feature gate"):
        create_microsoft_graph_oauth_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(GraphOAuthV1ContractError, match="complete bindings"):
        create_microsoft_graph_oauth_v1(
            gate=GraphOAuthFeatureGateV1(True),
            project_root=ROOT,
        )
    catalog = _catalog(fixture)
    with pytest.raises(
        GraphOAuthV1ContractError,
        match="exact MicrosoftGraphOAuthSettingsV1",
    ):
        create_microsoft_graph_oauth_v1(
            gate=GraphOAuthFeatureGateV1(True),
            aliases=catalog,
            credential_alias_name="microsoft-primary",
            settings=object(),  # type: ignore[arg-type]
            http=FakeHttp(),
            vault=FakeVault(),
            now_ms=NOW_MS,
            project_root=ROOT,
        )
    monkeypatch.setattr(
        "core.phase8_microsoft_graph_oauth_v1.ACCEPTED_READ_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(GraphOAuthV1Denied, match="evidence unavailable"):
        create_microsoft_graph_oauth_v1(
            gate=GraphOAuthFeatureGateV1(True),
            project_root=ROOT,
        )


@pytest.mark.parametrize(
    ("provider", "tenant", "scopes", "message"),
    [
        ("google", TENANT_ID, ("Calendars.Read", "Mail.Read"), "binding denied"),
        (
            "microsoft-graph",
            "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff",
            ("Calendars.Read", "Mail.Read"),
            "binding denied",
        ),
        (
            "microsoft-graph",
            TENANT_ID,
            ("Calendars.Read",),
            "binding denied",
        ),
    ],
)
def test_factory_denies_provider_tenant_or_alias_scope_drift(
    fixture: Fixture,
    provider: str,
    tenant: str,
    scopes: tuple[str, ...],
    message: str,
) -> None:
    catalog = _catalog(
        fixture,
        provider=provider,
        tenant_id=tenant,
        scopes=scopes,
    )
    with pytest.raises(GraphOAuthV1Denied, match=message):
        _session(fixture, catalog=catalog)


def test_device_authorization_exposes_only_user_challenge(
    fixture: Fixture,
) -> None:
    http = FakeHttp([Queued("POST", _device_response())])
    _catalog_value, _http, _vault, session = _session(fixture, http=http)
    challenge = session.begin_device_authorization(
        now_ms=NOW_MS + 1,
        now_epoch_s=NOW_S,
    )
    assert challenge.user_code == "ABCD-EFGH"
    assert challenge.verification_uri == "https://microsoft.com/devicelogin"
    assert challenge.expires_at_epoch_s == NOW_S + 900
    assert challenge.provider_message_untrusted is True
    assert "device-secret-1" not in repr(challenge)
    assert "device-secret-1" not in repr(http.responses)
    call = http.calls[0]
    assert call.url == (
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/devicecode"
    )
    assert call.values == (
        ("client_id", CLIENT_ID),
        (
            "scope",
            "Calendars.Read Mail.Read offline_access User.Read",
        ),
    )


def test_device_authorization_accepts_current_microsoft_verification_host(
    fixture: Fixture,
) -> None:
    verification_uri = "https://login.microsoft.com/device"
    http = FakeHttp(
        [Queued("POST", _device_response(verification_uri=verification_uri))]
    )
    _catalog_value, _http, _vault, session = _session(fixture, http=http)

    challenge = session.begin_device_authorization(
        now_ms=NOW_MS + 1,
        now_epoch_s=NOW_S,
    )

    assert challenge.verification_uri == verification_uri


@pytest.mark.parametrize(
    "verification_uri",
    [
        "http://microsoft.com/devicelogin",
        "https://evil.example/devicelogin",
        "https://microsoft.com/devicelogin#code",
    ],
)
def test_device_authorization_rejects_untrusted_verification_uri(
    fixture: Fixture,
    verification_uri: str,
) -> None:
    http = FakeHttp(
        [Queued("POST", _device_response(verification_uri=verification_uri))]
    )
    _catalog_value, _http, _vault, session = _session(fixture, http=http)
    with pytest.raises(GraphOAuthV1Denied, match="verification URI"):
        session.begin_device_authorization(
            now_ms=NOW_MS + 1,
            now_epoch_s=NOW_S,
        )


def test_poll_respects_interval_pending_slowdown_and_decline(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued(
                "POST",
                JsonHttpResponseV1(400, {"error": "authorization_pending"}),
            ),
            Queued("POST", JsonHttpResponseV1(400, {"error": "slow_down"})),
            Queued(
                "POST",
                JsonHttpResponseV1(400, {"error": "authorization_declined"}),
            ),
        ]
    )
    _catalog_value, _http, _vault, session = _session(fixture, http=http)
    session.begin_device_authorization(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    early = session.poll_device_authorization(
        now_ms=NOW_MS + 2,
        now_epoch_s=NOW_S + 4,
    )
    pending = session.poll_device_authorization(
        now_ms=NOW_MS + 3,
        now_epoch_s=NOW_S + 5,
    )
    slowed = session.poll_device_authorization(
        now_ms=NOW_MS + 4,
        now_epoch_s=NOW_S + 10,
    )
    too_early = session.poll_device_authorization(
        now_ms=NOW_MS + 5,
        now_epoch_s=NOW_S + 19,
    )
    declined = session.poll_device_authorization(
        now_ms=NOW_MS + 6,
        now_epoch_s=NOW_S + 20,
    )
    assert (early.status, early.retry_after_seconds) == (
        "authorization_pending",
        1,
    )
    assert (pending.status, pending.retry_after_seconds) == (
        "authorization_pending",
        5,
    )
    assert (slowed.status, slowed.retry_after_seconds) == ("slow_down", 10)
    assert (too_early.status, too_early.retry_after_seconds) == (
        "authorization_pending",
        1,
    )
    assert declined.status == "declined"
    assert len(http.calls) == 4


def test_device_completion_verifies_account_and_persists_refresh_only(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
        ]
    )
    vault = FakeVault()
    _catalog_value, _http, _vault, session = _session(
        fixture,
        http=http,
        vault=vault,
    )
    session.begin_device_authorization(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    result = session.poll_device_authorization(
        now_ms=NOW_MS + 2,
        now_epoch_s=NOW_S + 5,
    )
    assert result.status == "complete"
    assert result.session is not None
    assert result.session.connected is True
    assert result.session.account_id == "owner@cyryxlabs.com"
    assert result.session.access_expires_at_epoch_s == NOW_S + 5 + 3600
    assert vault.value == "refresh-token-1"
    assert vault.writes == ["refresh-token-1"]
    serialized_status = repr(result.session)
    assert "access-token-1" not in serialized_status
    assert "refresh-token-1" not in serialized_status
    assert http.calls[2].url == "https://graph.microsoft.com/v1.0/me"
    assert http.calls[2].headers == (("Authorization", "Bearer access-token-1"),)


def test_account_mismatch_fails_before_vault_write_and_consumes_device_code(
    fixture: Fixture,
) -> None:
    mismatch_http = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued("POST", _token_response()),
            Queued("GET", _profile(mail="other@example.com")),
        ]
    )
    mismatch_vault = FakeVault()
    _catalog_value, _http, _vault, mismatch = _session(
        fixture,
        http=mismatch_http,
        vault=mismatch_vault,
    )
    mismatch.begin_device_authorization(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    with pytest.raises(GraphOAuthV1Denied, match="account mismatch"):
        mismatch.poll_device_authorization(
            now_ms=NOW_MS + 2,
            now_epoch_s=NOW_S + 5,
        )
    assert mismatch_vault.writes == []
    with pytest.raises(GraphOAuthV1ContractError, match="not pending"):
        mismatch.poll_device_authorization(
            now_ms=NOW_MS + 3,
            now_epoch_s=NOW_S + 6,
        )


def test_device_completion_requires_refresh_and_exact_granted_scopes(
    fixture: Fixture,
) -> None:
    for response, message in (
        (_token_response(refresh=None), "refresh token unavailable"),
        (
            _token_response(scopes="User.Read Calendars.Read"),
            "granted scope drift",
        ),
    ):
        http = FakeHttp(
            [
                Queued("POST", _device_response()),
                Queued("POST", response),
            ]
        )
        vault = FakeVault()
        _catalog_value, _http, _vault, session = _session(
            fixture,
            http=http,
            vault=vault,
        )
        session.begin_device_authorization(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
        with pytest.raises(GraphOAuthV1Denied, match=message):
            session.poll_device_authorization(
                now_ms=NOW_MS + 2,
                now_epoch_s=NOW_S + 5,
            )
        assert session.status().connected is False
        assert vault.writes == []
        with pytest.raises(GraphOAuthV1ContractError, match="not pending"):
            session.poll_device_authorization(
                now_ms=NOW_MS + 3,
                now_epoch_s=NOW_S + 6,
            )


def test_vault_write_failure_never_caches_access_or_reuses_device_code(
    fixture: Fixture,
) -> None:
    class FailingVault(FakeVault):
        def set_refresh_token(self, value: str) -> None:
            raise RuntimeError("vault unavailable")

    http = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
        ]
    )
    vault = FailingVault()
    _catalog_value, _http, _vault, session = _session(
        fixture,
        http=http,
        vault=vault,
    )
    session.begin_device_authorization(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    with pytest.raises(RuntimeError, match="vault unavailable"):
        session.poll_device_authorization(
            now_ms=NOW_MS + 2,
            now_epoch_s=NOW_S + 5,
        )
    status = session.status()
    assert status.connected is False
    assert status.access_expires_at_epoch_s is None
    assert status.refresh_token_present is False
    with pytest.raises(GraphOAuthV1ContractError, match="not pending"):
        session.poll_device_authorization(
            now_ms=NOW_MS + 3,
            now_epoch_s=NOW_S + 6,
        )


def test_restore_without_token_is_offline_and_refresh_rotates_token(
    fixture: Fixture,
) -> None:
    empty_http = FakeHttp()
    empty_vault = FakeVault()
    _catalog_value, _http, _vault, empty = _session(
        fixture,
        http=empty_http,
        vault=empty_vault,
    )
    empty_status = empty.restore(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    assert empty_status.connected is False
    assert empty_status.refresh_token_present is False
    assert empty_http.calls == []

    http = FakeHttp(
        [
            Queued(
                "POST",
                _token_response(
                    access="access-token-2",
                    refresh="refresh-token-2",
                ),
            ),
            Queued("GET", _profile()),
        ]
    )
    vault = FakeVault("refresh-token-1")
    _catalog_value, _http, _vault, restored = _session(
        fixture,
        http=http,
        vault=vault,
    )
    status = restored.restore(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    assert status.connected is True
    assert vault.value == "refresh-token-2"
    assert http.calls[0].values == (
        ("client_id", CLIENT_ID),
        ("grant_type", "refresh_token"),
        ("refresh_token", "refresh-token-1"),
        ("scope", "Calendars.Read Mail.Read offline_access User.Read"),
    )


def test_refresh_failure_preserves_vault_and_reports_disconnected(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            Queued(
                "POST",
                JsonHttpResponseV1(
                    400,
                    {
                        "error": "temporarily_unavailable",
                        "error_description": "provider text is untrusted",
                    },
                ),
            )
        ]
    )
    vault = FakeVault("refresh-token-1")
    _catalog_value, _http, _vault, session = _session(
        fixture,
        http=http,
        vault=vault,
    )
    with pytest.raises(GraphOAuthV1Error, match="refresh failed"):
        session.restore(now_ms=NOW_MS + 1, now_epoch_s=NOW_S)
    status = session.status()
    assert status.connected is False
    assert status.access_expires_at_epoch_s is None
    assert status.refresh_token_present is True
    assert vault.value == "refresh-token-1"
    assert vault.deletes == 0
    assert "refresh-token-1" not in repr(status)


@pytest.mark.parametrize(
    ("status", "retry", "session"),
    [
        ("authorization_pending", None, None),
        ("authorization_pending", 0, None),
        ("slow_down", 5, OAuthSessionStatusV1(True, "w", "p", "a", "t", (), 1, True)),
        ("complete", 1, OAuthSessionStatusV1(True, "w", "p", "a", "t", (), 1, True)),
        ("complete", None, None),
        ("declined", None, OAuthSessionStatusV1(True, "w", "p", "a", "t", (), 1, True)),
        ("expired", 1, None),
    ],
)
def test_device_poll_result_enforces_status_field_consistency(
    status: str,
    retry: int | None,
    session: OAuthSessionStatusV1 | None,
) -> None:
    with pytest.raises(GraphOAuthV1ContractError):
        DevicePollResultV1(status, retry, session)


def test_bearer_transport_caches_token_and_forwards_get_only(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
            Queued(
                "GET",
                JsonHttpResponseV1(
                    200,
                    {"value": []},
                    (("request-id", "request-1"),),
                ),
            ),
            Queued("GET", JsonHttpResponseV1(200, {"value": []})),
        ]
    )
    vault = FakeVault("refresh-token-0")
    _catalog_value, _http, _vault, session = _session(
        fixture,
        http=http,
        vault=vault,
    )
    transport = session.create_read_transport(
        clock_epoch_s=lambda: NOW_S,
        clock_ms=lambda: NOW_MS + 1,
    )
    first = transport.get(
        url="https://graph.microsoft.com/v1.0/me/messages",
        query=(("$top", "1"),),
        headers=(),
    )
    second = transport.get(
        url="https://graph.microsoft.com/v1.0/me/calendarView",
        query=(("startDateTime", "2026-07-23T00:00:00Z"),),
        headers=(("Prefer", 'outlook.timezone="UTC"'),),
    )
    assert first.request_id == "request-1"
    assert second.status_code == 200
    assert len([call for call in http.calls if call.method == "POST"]) == 1
    assert http.calls[2].headers == (("Authorization", "Bearer access-token-1"),)
    assert http.calls[3].headers == (
        ("Authorization", "Bearer access-token-1"),
        ("Prefer", 'outlook.timezone="UTC"'),
    )


@pytest.mark.parametrize(
    ("url", "headers"),
    [
        ("https://evil.example/v1.0/me/messages", ()),
        ("http://graph.microsoft.com/v1.0/me/messages", ()),
        ("https://graph.microsoft.com/beta/me/messages", ()),
        ("https://graph.microsoft.com/v1.0/users", ()),
        (
            "https://graph.microsoft.com/v1.0/me/messages",
            (("Authorization", "Bearer caller-token"),),
        ),
    ],
)
def test_bearer_transport_denies_route_or_authorization_injection(
    fixture: Fixture,
    url: str,
    headers: tuple[tuple[str, str], ...],
) -> None:
    _catalog_value, _http, _vault, session = _session(fixture)
    transport = session.create_read_transport(
        clock_epoch_s=lambda: NOW_S,
        clock_ms=lambda: NOW_MS + 1,
    )
    with pytest.raises(GraphOAuthV1Denied, match="route"):
        transport.get(url=url, query=(), headers=headers)


def test_revoked_alias_blocks_read_but_disconnect_can_still_delete(
    fixture: Fixture,
) -> None:
    vault = FakeVault("refresh-token-1")
    catalog, _http, _vault, session = _session(fixture, vault=vault)
    catalog.revoke(
        kind="credential",
        alias_name="microsoft-primary",
        now_ms=NOW_MS + 1,
    )
    with pytest.raises(GraphOAuthV1Denied, match="alias unavailable"):
        session.restore(now_ms=NOW_MS + 2, now_epoch_s=NOW_S)
    assert session.disconnect(now_ms=NOW_MS + 2) is True
    assert vault.value is None


def test_stdlib_client_denies_invalid_routes_before_network() -> None:
    client = StdlibGraphOAuthHttpV1()
    with pytest.raises(GraphOAuthV1Denied, match="identity POST"):
        client.post_form(
            url="https://evil.example/token",
            fields=(("refresh_token", "secret"),),
            timeout_seconds=30,
        )
    with pytest.raises(GraphOAuthV1Denied, match="Graph GET"):
        client.get_json(
            url="https://graph.microsoft.com/beta/me",
            query=(),
            headers=(),
            timeout_seconds=30,
        )


def test_native_vault_reference_is_opaque_and_does_not_embed_account(
    fixture: Fixture,
) -> None:
    credential = _catalog(fixture).get(
        kind="credential",
        alias_name="microsoft-primary",
        now_ms=NOW_MS,
    )
    captured = {}

    class Vault:
        def __init__(self, reference):
            captured["reference"] = reference

    with patch(
        "core.phase8_microsoft_graph_oauth_v1.native_vault.NativeSecretVault",
        Vault,
    ):
        NativeGraphRefreshTokenVaultV1(credential)
    reference = captured["reference"]
    assert reference.service == "CyryxLabs.Onyx.GraphOAuth.v1"
    assert reference.account.startswith("rt_")
    assert "owner" not in reference.account
    assert "cyryxlabs" not in reference.account


def test_oauth_transport_composes_with_accepted_daily_brief(
    fixture: Fixture,
) -> None:
    http = FakeHttp(
        [
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
            Queued("GET", JsonHttpResponseV1(200, {"value": []})),
            Queued("GET", JsonHttpResponseV1(200, {"value": []})),
        ]
    )
    vault = FakeVault("refresh-token-0")
    catalog, _http, _vault, session = _session(
        fixture,
        http=http,
        vault=vault,
    )
    transport = session.create_read_transport(
        clock_epoch_s=lambda: NOW_S,
        clock_ms=lambda: NOW_MS + 1,
    )
    adapter = create_microsoft_graph_read_adapter_v1(
        gate=GraphReadFeatureGateV1(True),
        aliases=catalog,
        credential_alias_name="microsoft-primary",
        transport=transport,
        now_ms=NOW_MS + 1,
        project_root=ROOT,
    )
    assert adapter is not None
    brief = adapter.daily_brief(
        window_start="2026-07-23T00:00:00Z",
        window_end="2026-07-24T00:00:00Z",
        outlook_timezone="UTC",
        now_ms=NOW_MS + 2,
        generated_at="2026-07-23T01:00:00Z",
    )
    assert brief.account_id == "owner@cyryxlabs.com"
    assert brief.events == ()
    assert brief.unread_messages == ()
    assert len(http.calls) == 4
    assert all(call.method == "GET" for call in http.calls[1:])


def test_module_has_no_graph_mutation_or_live_wiring() -> None:
    source = (ROOT / "core" / "phase8_microsoft_graph_oauth_v1.py").read_text(
        encoding="utf-8"
    )
    assert "Mail.Send" not in source
    assert "Calendars.ReadWrite" not in source
    assert "def send" not in source
    assert "def create_event" not in source
    assert "def patch(" not in source
    assert "def delete(" not in source
    assert "main.py" not in source
    assert "dashboard" not in source
    assert "refresh_token" not in repr(
        JsonHttpResponseV1(200, {"refresh_token": "secret"})
    )
    assert DEVICE_GRANT in source
