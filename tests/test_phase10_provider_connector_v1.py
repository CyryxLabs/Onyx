"""Focused and adversarial tests for the Phase 10 provider connector V1."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import phase10_provider_connector_v1 as mod

PROJECT = Path(__file__).resolve().parents[1]


class FakeHttp:
    """Injected transport — no real network. Returns a canned response or raises."""

    def __init__(self, response=None, raiser=None, expect=None):
        self._response = response
        self._raiser = raiser
        self._expect = expect or {}
        self.calls = []

    def get_json(self, *, url, origin, path, timeout_seconds):
        self.calls.append((url, origin, path, timeout_seconds))
        for k, v in self._expect.items():
            assert {"url": url, "origin": origin, "path": path}[k] == v
        if self._raiser is not None:
            raise self._raiser
        return self._response


def _provider(provider_id="prov1", platform="instagram", origin="api.example.com",
              path="/v1/me", handle="@cyryx_test", scopes=("read",), test_only=True):
    return mod.ApprovedProviderV1(
        provider_id=provider_id,
        platform=platform,
        api_origin=origin,
        status_path=path,
        expected_handle=handle,
        required_scopes=frozenset(scopes),
        test_account_only=test_only,
    )


def _ok_payload(handle="@cyryx_test", verified=True, followers=42, posts=("p1", "p2")):
    return {
        "handle": handle,
        "verified": verified,
        "follower_count": followers,
        "recent_post_ids": list(posts),
    }


def _session(providers, http):
    return mod.create_provider_connector_v1(
        gate=mod.ProviderConnectorFeatureGateV1(True),
        providers=tuple(providers),
        http=http,
        project_root=PROJECT,
    )


# ── feature gate + default-off factory ──────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.ProviderConnectorFeatureGateV1.from_environ({}).enabled is False


def test_factory_returns_none_when_disabled():
    out = mod.create_provider_connector_v1(
        gate=mod.ProviderConnectorFeatureGateV1(False), project_root=PROJECT
    )
    assert out is None


def test_enabled_session_requires_providers():
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        mod.create_provider_connector_v1(
            gate=mod.ProviderConnectorFeatureGateV1(True), project_root=PROJECT
        )


# ── entry-bind to the accepted editorial-calendar slice ─────────────────────

def test_entry_bind_denied_when_evidence_absent(tmp_path):
    with pytest.raises(mod.ProviderConnectorV1Denied):
        mod.create_provider_connector_v1(
            gate=mod.ProviderConnectorFeatureGateV1(True),
            providers=(_provider(),),
            http=FakeHttp(),
            project_root=tmp_path,
        )


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        mod.ProviderConnectorSessionV1(
            construction_key=object(), providers=(), http=FakeHttp()
        )


# ── happy path (injected transport) ─────────────────────────────────────────

def test_fetch_account_status_reads_and_attributes_from_registry():
    resp = mod.ProviderJsonResponseV1(200, _ok_payload())
    http = FakeHttp(response=resp)
    sess = _session([_provider()], http)
    status = sess.fetch_account_status(provider_id="prov1")
    assert status.handle == "@cyryx_test"
    assert status.provider_id == "prov1"
    assert status.platform == "instagram"          # from registry, not response
    assert status.verified is True
    assert status.follower_count == 42
    assert status.recent_post_ids == ("p1", "p2")
    assert status.http_status == 200
    # route pin was honoured
    assert http.calls[0] == ("https://api.example.com/v1/me", "api.example.com", "/v1/me", 30)


def test_no_publish_method_exists():
    sess = _session([_provider()], FakeHttp(response=mod.ProviderJsonResponseV1(200, _ok_payload())))
    assert not hasattr(sess, "publish")
    assert not hasattr(sess, "post")


def test_approved_provider_ids():
    sess = _session([_provider("a"), _provider("b", handle="@b")], FakeHttp())
    assert sess.approved_provider_ids() == ("a", "b")


# ── anti-spoof + governance ─────────────────────────────────────────────────

def test_response_handle_mismatch_is_denied():
    resp = mod.ProviderJsonResponseV1(200, _ok_payload(handle="@attacker"))
    sess = _session([_provider(handle="@cyryx_test")], FakeHttp(response=resp))
    with pytest.raises(mod.ProviderConnectorV1Denied):
        sess.fetch_account_status(provider_id="prov1")


def test_platform_attributed_from_registry_not_response():
    # Response carries a bogus 'platform' — it must be ignored.
    payload = _ok_payload()
    payload["platform"] = "tiktok"
    sess = _session([_provider(platform="instagram")],
                    FakeHttp(response=mod.ProviderJsonResponseV1(200, payload)))
    status = sess.fetch_account_status(provider_id="prov1")
    assert status.platform == "instagram"


def test_unknown_provider_rejected():
    sess = _session([_provider("prov1")], FakeHttp(response=mod.ProviderJsonResponseV1(200, _ok_payload())))
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        sess.fetch_account_status(provider_id="ghost")


def test_non_200_status_fails():
    sess = _session([_provider()], FakeHttp(response=mod.ProviderJsonResponseV1(404, {})))
    with pytest.raises(mod.ProviderConnectorV1Error):
        sess.fetch_account_status(provider_id="prov1")


# ── ApprovedProviderV1 origin/path/scope grammar (Phase 9 hardening reused) ──

@pytest.mark.parametrize("origin", [
    "good.test@evil.com",   # userinfo escape
    "api.example.com:8443",  # port
    "API.example.com",       # uppercase
    "localhost",             # single label
    "-bad.example.com",      # leading hyphen
    "exämple.com",           # unicode
])
def test_bad_origin_rejected(origin):
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        _provider(origin=origin)


@pytest.mark.parametrize("path", ["/v1/../secret", "/v1//me", "relative", "/v1?x=1"])
def test_bad_path_rejected(path):
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        _provider(path=path)


def test_unknown_platform_rejected():
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        _provider(platform="myspace")


def test_empty_scopes_rejected():
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        _provider(scopes=())


def test_duplicate_provider_id_rejected():
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        _session([_provider("dup"), _provider("dup", handle="@x")], FakeHttp())


def test_unsealed_provider_rejected():
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        _session([{"provider_id": "x"}], FakeHttp())


# ── response payload hardening ──────────────────────────────────────────────

def test_verified_must_be_bool():
    payload = _ok_payload(); payload["verified"] = "yes"
    sess = _session([_provider()], FakeHttp(response=mod.ProviderJsonResponseV1(200, payload)))
    with pytest.raises(mod.ProviderConnectorV1Denied):
        sess.fetch_account_status(provider_id="prov1")


def test_follower_count_rejects_bool_and_out_of_range():
    for bad in (True, -1, mod.MAX_FOLLOWERS + 1, "5"):
        payload = _ok_payload(); payload["follower_count"] = bad
        sess = _session([_provider()], FakeHttp(response=mod.ProviderJsonResponseV1(200, payload)))
        with pytest.raises(mod.ProviderConnectorV1Denied):
            sess.fetch_account_status(provider_id="prov1")


def test_recent_post_ids_cap_and_type():
    payload = _ok_payload(posts=tuple(f"p{i}" for i in range(mod.MAX_POST_IDS + 1)))
    sess = _session([_provider()], FakeHttp(response=mod.ProviderJsonResponseV1(200, payload)))
    with pytest.raises(mod.ProviderConnectorV1Denied):
        sess.fetch_account_status(provider_id="prov1")


def test_missing_handle_rejected():
    payload = _ok_payload(); del payload["handle"]
    sess = _session([_provider()], FakeHttp(response=mod.ProviderJsonResponseV1(200, payload)))
    with pytest.raises(mod.ProviderConnectorV1ContractError):
        sess.fetch_account_status(provider_id="prov1")


# ── the route-pinned stdlib client rejects a bad route without any network ──

def test_stdlib_client_rejects_off_route_before_network():
    client = mod.StdlibProviderConnectorHttpV1()
    with pytest.raises(mod.ProviderConnectorV1Denied):
        client.get_json(url="https://evil.com/v1/me", origin="api.example.com",
                        path="/v1/me", timeout_seconds=30)


def test_stdlib_client_rejects_query_and_port():
    client = mod.StdlibProviderConnectorHttpV1()
    with pytest.raises(mod.ProviderConnectorV1Denied):
        client.get_json(url="https://api.example.com:8443/v1/me", origin="api.example.com",
                        path="/v1/me", timeout_seconds=30)
    with pytest.raises(mod.ProviderConnectorV1Denied):
        client.get_json(url="https://api.example.com/v1/me?x=1", origin="api.example.com",
                        path="/v1/me", timeout_seconds=30)
