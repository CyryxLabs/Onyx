"""Synthetic regressions for the additive native-capacity Graph successor."""
from __future__ import annotations

import pytest

import test_phase8_microsoft_graph_oauth_v1 as base
from test_phase8_microsoft_graph_oauth_v1 import fixture as fixture
from core import native_vault
from core.graph_refresh_vault_v2 import (
    NativeGraphRefreshTokenVaultV2, validate_refresh_token_v2,
)
from core.phase8_microsoft_graph_oauth_v2 import create_microsoft_graph_oauth_v2


@pytest.mark.parametrize("value", ["a" * 1801, "b" * 2048, "é" * 1024])
def test_capacity_accepts_exact_bytes_without_truncation(value):
    assert validate_refresh_token_v2(value) == value


@pytest.mark.parametrize("value", ["a" * 2049, "é" * 1025, "", "x\n", "\ud800", None, b"x"])
def test_capacity_rejects_invalid_tokens(value):
    with pytest.raises(base.GraphOAuthV1Denied):
        validate_refresh_token_v2(value)


class MemoryNative:
    def __init__(self):
        self.value = None
        self.fail_write = False
        self.fail_read = False
        self.competing = False
        self.writes = 0

    def get_bytes(self):
        if self.fail_read:
            raise native_vault.NativeVaultError("synthetic backend failure")
        return self.value

    def set_bytes(self, value):
        if self.fail_write:
            raise native_vault.NativeVaultError("synthetic backend failure")
        self.writes += 1
        self.value = b"competing" if self.competing else value


def vault_pair():
    vault = object.__new__(NativeGraphRefreshTokenVaultV2)
    vault._legacy = base.FakeVault("legacy")
    vault._vault = MemoryNative()
    return vault, vault._vault


def test_fallback_rotation_and_disconnect_never_overwrite_or_revive_v1():
    vault, backend = vault_pair()
    assert vault.get_refresh_token() == "legacy"
    assert backend.writes == 0
    vault.set_refresh_token("r" * 2048)
    assert vault.get_refresh_token() == "r" * 2048
    assert vault._legacy.value == "legacy"
    assert vault.delete_refresh_token()
    assert vault.get_refresh_token() is None
    assert not vault.delete_refresh_token()
    assert vault._legacy.writes == []


def test_rejected_or_failed_write_preserves_previous_record():
    vault, backend = vault_pair()
    vault.set_refresh_token("previous")
    with pytest.raises(base.GraphOAuthV1Denied):
        vault.set_refresh_token("r" * 2049)
    backend.fail_write = True
    with pytest.raises(base.GraphOAuthV1Error, match="outcome unknown"):
        vault.set_refresh_token("r" * 2048)
    assert backend.value == b"previous"


@pytest.mark.parametrize("failure", ["fail_read", "competing"])
def test_readback_failure_does_not_roll_back_competing_value(failure):
    vault, backend = vault_pair()
    setattr(backend, failure, True)
    with pytest.raises(base.GraphOAuthV1Error):
        vault.set_refresh_token("r" * 2048)
    assert backend.writes == 1
    assert backend.value == (b"competing" if failure == "competing" else b"r" * 2048)


def test_corrupt_successor_fails_closed_without_legacy_fallback():
    vault, backend = vault_pair()
    backend.value = b"\xff"
    with pytest.raises(base.GraphOAuthV1Error):
        vault.get_refresh_token()


def make_session(fixture, http, vault):
    return create_microsoft_graph_oauth_v2(
        gate=base.GraphOAuthFeatureGateV1(True), aliases=base._catalog(fixture),
        credential_alias_name="microsoft-primary", settings=base._settings(),
        http=http, vault=vault, now_ms=base.NOW_MS, project_root=base.ROOT,
    )


@pytest.mark.parametrize("size", [1801, 2048])
def test_restore_accepts_large_rotation_after_account_validation(fixture, size):
    vault = base.FakeVault("existing")
    http = base.FakeHttp([base.Queued("POST", base._token_response(refresh="r" * size)),
                          base.Queued("GET", base._profile())])
    session = make_session(fixture, http, vault)
    assert session.restore(now_ms=base.NOW_MS, now_epoch_s=base.NOW_S).connected
    assert vault.writes == ["r" * size]
    assert [call.method for call in http.calls] == ["POST", "GET"]


@pytest.mark.parametrize("failure", ["oversize", "scopes", "account", "commit"])
def test_rejected_rotation_never_activates_bearer(fixture, failure):
    vault, backend = vault_pair()
    backend.fail_write = failure == "commit"
    token = base._token_response(refresh="r" * (2049 if failure == "oversize" else 2048),
                                scopes="User.Read" if failure == "scopes" else "User.Read Calendars.Read Mail.Read")
    http = base.FakeHttp([base.Queued("POST", token), base.Queued("GET", base._profile(
        mail="other@example.com" if failure == "account" else "owner@cyryxlabs.com"))])
    session = make_session(fixture, http, vault)
    with pytest.raises((base.GraphOAuthV1Error, base.GraphOAuthV1Denied)):
        session.restore(now_ms=base.NOW_MS, now_epoch_s=base.NOW_S)
    assert session._access_token is None
    assert backend.value is None
    assert len(http.calls) == (1 if failure in {"oversize", "scopes"} else 2)


def test_predecessor_limit_unchanged():
    from core.phase8_microsoft_graph_oauth_v1 import _refresh_token
    with pytest.raises(base.GraphOAuthV1Denied):
        _refresh_token("r" * 1801)


def test_host_status_and_disconnect_select_the_same_successor_vault():
    from core.dayops_connection_v19 import DayOpsConnectionControllerV19
    from core.dayops_profile_v19 import DayOpsProfileV19
    profile = DayOpsProfileV19(
        client_id=base.CLIENT_ID, tenant_id=base.TENANT_ID,
        account_id="owner@cyryxlabs.com", workspace_id="cyryx-main",
        principal_id="owner:pedro", credential_alias_name="microsoft-primary",
        iana_timezone="America/New_York", outlook_timezone="Eastern Standard Time",
    )
    provisioner = DayOpsConnectionControllerV19._default_provisioner(profile)
    assert provisioner._refresh_vault_factory is NativeGraphRefreshTokenVaultV2
