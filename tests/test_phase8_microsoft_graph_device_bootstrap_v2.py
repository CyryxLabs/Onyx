from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from unittest.mock import patch

import pytest

from core.phase8_microsoft_graph_device_bootstrap_v2 import (
    ALLOWED_VERIFICATION_HOSTS,
    FEATURE_FLAG,
    DeviceBootstrapFeatureGateV2,
    DeviceBootstrapV2ContractError,
    DeviceBootstrapV2Denied,
    DeviceBootstrapV2Error,
    build_runner_credential_record,
    create_microsoft_graph_device_bootstrap_v2,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import (
    JsonHttpResponseV1,
    NativeGraphRefreshTokenVaultV1,
)

ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1_785_000_000_000
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ACCOUNT_ID = "owner@cyryxlabs.com"


@dataclass(frozen=True)
class Queued:
    method: str
    response: JsonHttpResponseV1


class FakeHttp:
    def __init__(self, responses: Iterable[Queued] = ()) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def _next(self, method: str) -> JsonHttpResponseV1:
        if not self.responses:
            raise AssertionError(f"unexpected {method} request")
        item = self.responses.pop(0)
        assert item.method == method
        return item.response

    def post_form(self, *, url, fields, timeout_seconds):
        assert timeout_seconds == 30
        self.calls.append(("POST", url))
        return self._next("POST")

    def get_json(self, *, url, query, headers, timeout_seconds):
        assert timeout_seconds == 30
        self.calls.append(("GET", url))
        return self._next("GET")


class FakeVault:
    def __init__(self) -> None:
        self.value: str | None = None
        self.writes: list[str] = []

    def get_refresh_token(self):
        return self.value

    def set_refresh_token(self, value: str) -> None:
        self.value = value
        self.writes.append(value)

    def delete_refresh_token(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


def _onboarding() -> MicrosoftGraphLiveOnboardingV1:
    return MicrosoftGraphLiveOnboardingV1(CLIENT_ID, TENANT_ID, ACCOUNT_ID)


def _device_response(uri: str = "https://login.microsoft.com/device"):
    return JsonHttpResponseV1(
        200,
        {
            "device_code": "device-secret-1",
            "user_code": "ABCD-EFGH",
            "verification_uri": uri,
            "expires_in": 900,
            "interval": 5,
        },
    )


def _token_response(scopes: str = "User.Read Calendars.Read Mail.Read"):
    return JsonHttpResponseV1(
        200,
        {
            "token_type": "Bearer",
            "access_token": "access-token-1",
            "refresh_token": "refresh-token-1",
            "expires_in": 3600,
            "scope": scopes,
        },
    )


def _profile(mail: str = ACCOUNT_ID):
    return JsonHttpResponseV1(
        200, {"id": "user-1", "mail": mail, "userPrincipalName": mail}
    )


def _bootstrap(http: FakeHttp, vault: FakeVault, *, sleeps: list[int]):
    clock = {"now": 1_785_000_000}
    bootstrap = create_microsoft_graph_device_bootstrap_v2(
        gate=DeviceBootstrapFeatureGateV2(True),
        onboarding=_onboarding(),
        http=http,
        vault=vault,
        sleeper=lambda seconds: (sleeps.append(seconds), clock.__setitem__(
            "now", clock["now"] + seconds
        ))[0] or None,
        clock_epoch_s=lambda: clock["now"],
        now_ms=NOW_MS,
    )
    assert bootstrap is not None
    return bootstrap


def test_feature_gate_is_exact_and_default_off() -> None:
    assert not DeviceBootstrapFeatureGateV2.from_environ({}).enabled
    assert DeviceBootstrapFeatureGateV2.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "yes"):
        assert not DeviceBootstrapFeatureGateV2.from_environ(
            {FEATURE_FLAG: value}
        ).enabled
    assert (
        create_microsoft_graph_device_bootstrap_v2(
            gate=DeviceBootstrapFeatureGateV2(False)
        )
        is None
    )


def test_factory_requires_complete_exact_bindings() -> None:
    with pytest.raises(DeviceBootstrapV2ContractError, match="sealed feature gate"):
        create_microsoft_graph_device_bootstrap_v2(gate=True)  # type: ignore[arg-type]
    with pytest.raises(DeviceBootstrapV2ContractError, match="complete bindings"):
        create_microsoft_graph_device_bootstrap_v2(
            gate=DeviceBootstrapFeatureGateV2(True),
            onboarding=_onboarding(),
        )


def test_runner_credential_record_matches_frozen_vault_fingerprint() -> None:
    record = build_runner_credential_record(onboarding=_onboarding(), now_ms=NOW_MS)
    assert record.workspace_id == "cyryx-live-e2e"
    assert record.alias_name == "microsoft-live-e2e"
    assert record.vault_service == "CyryxLabs.Onyx.v1.cyryx-live-e2e.microsoft-graph"
    assert record.vault_account == f"{TENANT_ID}:{ACCOUNT_ID}"
    captured = {}

    class Vault:
        def __init__(self, reference):
            captured["reference"] = reference

    with patch(
        "core.phase8_microsoft_graph_oauth_v1.native_vault.NativeSecretVault",
        Vault,
    ):
        NativeGraphRefreshTokenVaultV1(record)
    reference = captured["reference"]
    assert reference.service == "CyryxLabs.Onyx.GraphOAuth.v1"
    assert reference.account.startswith("rt_")
    assert ACCOUNT_ID.split("@")[0] not in reference.account


def test_corrected_allowlist_accepts_live_host_and_rejects_untrusted() -> None:
    assert "login.microsoft.com" in ALLOWED_VERIFICATION_HOSTS
    sleeps: list[int] = []
    http = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
        ]
    )
    vault = FakeVault()
    echoed: list[str] = []
    result = _bootstrap(http, vault, sleeps=sleeps).sign_in(echo=echoed.append)
    assert result.refresh_token_stored is True
    assert vault.writes == ["refresh-token-1"]
    assert any("login.microsoft.com/device" in line for line in echoed)
    assert all("device-secret-1" not in line for line in echoed)
    assert all("refresh-token" not in line for line in echoed)

    for uri in (
        "https://evil.example/device",
        "http://login.microsoft.com/device",
        "https://login.microsoft.com.evil.example/device",
        "https://login.microsoft.com/device#x",
    ):
        denied = FakeHttp([Queued("POST", _device_response(uri))])
        with pytest.raises(DeviceBootstrapV2Denied, match="verification URI"):
            _bootstrap(denied, FakeVault(), sleeps=[]).sign_in(echo=lambda _l: None)


def test_pending_and_slow_down_poll_then_success() -> None:
    sleeps: list[int] = []
    http = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued("POST", JsonHttpResponseV1(400, {"error": "authorization_pending"})),
            Queued("POST", JsonHttpResponseV1(400, {"error": "slow_down"})),
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
        ]
    )
    vault = FakeVault()
    result = _bootstrap(http, vault, sleeps=sleeps).sign_in(echo=lambda _l: None)
    assert result.account_id == ACCOUNT_ID
    assert sleeps == [5, 10]


def test_declined_expired_and_window_expiry_fail_closed() -> None:
    for error in ("authorization_declined", "expired_token"):
        http = FakeHttp(
            [
                Queued("POST", _device_response()),
                Queued("POST", JsonHttpResponseV1(400, {"error": error})),
            ]
        )
        with pytest.raises(DeviceBootstrapV2Error, match=error):
            _bootstrap(http, FakeVault(), sleeps=[]).sign_in(echo=lambda _l: None)
    pending = [Queued("POST", _device_response())]
    pending.extend(
        Queued("POST", JsonHttpResponseV1(400, {"error": "authorization_pending"}))
        for _ in range(181)
    )
    http = FakeHttp(pending)
    with pytest.raises(DeviceBootstrapV2Error, match="window expired"):
        _bootstrap(http, FakeVault(), sleeps=[]).sign_in(echo=lambda _l: None)


def test_scope_drift_and_account_mismatch_deny_before_vault_write() -> None:
    drift = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued("POST", _token_response(scopes="User.Read Calendars.Read")),
        ]
    )
    vault = FakeVault()
    with pytest.raises(DeviceBootstrapV2Denied, match="scope drift"):
        _bootstrap(drift, vault, sleeps=[]).sign_in(echo=lambda _l: None)
    assert vault.writes == []
    mismatch = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued("POST", _token_response()),
            Queued("GET", _profile(mail="other@example.com")),
        ]
    )
    with pytest.raises(DeviceBootstrapV2Denied, match="account mismatch"):
        _bootstrap(mismatch, vault, sleeps=[]).sign_in(echo=lambda _l: None)
    assert vault.writes == []


def test_module_has_no_mutation_or_secret_material() -> None:
    source = (
        ROOT / "core" / "phase8_microsoft_graph_device_bootstrap_v2.py"
    ).read_text(encoding="utf-8")
    assert "Mail.Send" not in source
    assert "Calendars.ReadWrite" not in source
    assert "client_secret" not in source
    assert "def send" not in source
    assert "def patch(" not in source
    assert "def delete(" not in source
    assert "subprocess" not in source
    assert "main.py" not in source
    assert "dashboard" not in source
    assert "login.microsoft.com" in source
