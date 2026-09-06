from __future__ import annotations

import json
import ssl
import traceback
from dataclasses import replace
from urllib.parse import parse_qs

import pytest

from core import social_official_adapter_v1 as official
from core.social_publish_v1 import (
    CaptionRequestV1, ProviderDispatchV1, ProviderReceiptV1,
    SocialPublishDenied, SocialPublishFeatureGateV1, SocialPublishUncertain,
)


PAGE = "123456"
POST = PAGE + "_98765"
TOKEN = b"synthetic-test-token"
CAPTION = "Bounded evidence. Olá! & + ="


def request(**changes):
    return replace(CaptionRequestV1(
        workspace_id="workspace-test", principal_id="owner-test", account_id=PAGE,
        target=official.TARGET, caption=CAPTION,
    ), **changes)


def readback(**changes):
    return {"id": POST, "message": CAPTION, "from": {"id": PAGE},
            "is_published": True, **changes}


class FakeWire:
    def __init__(self, replies=None):
        self.replies = list(replies if replies is not None else [(200, {"id": POST}), (200, readback())])
        self.calls = []
        self.connections = []
        self.closes = 0

    def __call__(self, host, port, *, timeout, context):
        self.connections.append((host, port, timeout, context))
        assert host == official.GRAPH_HOST and port == 443
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert 1 <= timeout <= 60
        wire = self

        class Connection:
            def request(self, method, path, *, body, headers):
                wire.calls.append((method, path, body, headers))
                assert headers["Authorization"] == "Bearer " + TOKEN.decode()
                assert TOKEN.decode() not in path

            def getresponse(self):
                reply = wire.replies.pop(0)
                if isinstance(reply, Exception):
                    raise reply
                status, data = reply

                class Response:
                    def read(self, count):
                        assert count == official.MAX_RESPONSE_BYTES + 1
                        return data if isinstance(data, bytes) else json.dumps(data).encode()

                response = Response()
                response.status = status
                return response

            def close(self):
                wire.closes += 1

        return Connection()


def runtime(tmp_path, wire=None, **kwargs):
    wire = wire or FakeWire()
    service = official.create_social_official_publication_v1(
        gate=SocialPublishFeatureGateV1(True), config=official.FacebookPageConfigV1(PAGE),
        ledger_path=tmp_path / "social.sqlite3", connection_factory=wire,
        vault_reader=kwargs.get("vault_reader", lambda ref: TOKEN),
    )
    return service, wire


def consent(service, req=None):
    req = req or request()
    record = service.create_preview(req)
    service.consent(req, exact_consent=record.preview.consent_text)
    return req


def test_disabled_factory_has_no_vault_network_or_files(tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("disabled gate must not access dependencies")
    assert official.create_social_official_publication_v1(
        vault_reader=forbidden, connection_factory=forbidden,
        ledger_path=tmp_path / "absent.sqlite3",
    ) is None
    assert not list(tmp_path.iterdir())


def test_missing_config_and_vault_are_explicit_blockers(tmp_path):
    with pytest.raises(SocialPublishDenied, match="configuration_required"):
        official.create_social_official_publication_v1(gate=SocialPublishFeatureGateV1(True))
    with pytest.raises(official.SocialOfficialAdapterError, match="credential_unavailable"):
        runtime(tmp_path, vault_reader=lambda ref: None)
    assert not (tmp_path / "social.sqlite3").exists()


@pytest.mark.parametrize("page", ["me", "123/feed", "https://evil.test", "123?access_token=x", "0", "", "1\r\n", 123])
def test_page_id_injection_is_rejected(page):
    with pytest.raises(official.SocialOfficialAdapterError):
        official.FacebookPageConfigV1(page)


@pytest.mark.parametrize("timeout", [0, 61, True, 1.5])
def test_timeout_bounds(timeout):
    with pytest.raises(official.SocialOfficialAdapterError):
        official.FacebookPageConfigV1(PAGE, timeout)


@pytest.mark.parametrize("token", [None, b"", b"token\r\nX: injected", b"x" * 2049, "plaintext"])
def test_invalid_token_never_reaches_wire(tmp_path, token):
    wire = FakeWire()
    with pytest.raises(official.SocialOfficialAdapterError):
        runtime(tmp_path, wire, vault_reader=lambda ref: token)
    assert not wire.calls


def test_official_post_requires_exact_consent_and_verifies_readback(tmp_path):
    refs = []
    service, wire = runtime(tmp_path, vault_reader=lambda ref: refs.append(ref) or TOKEN)
    req = request()
    service.create_preview(req)
    assert not wire.connections
    with pytest.raises(SocialPublishDenied):
        service.dispatch(req)
    with pytest.raises(SocialPublishDenied):
        service.consent(req, exact_consent="yes")
    record = service.create_preview(req)
    service.consent(req, exact_consent=record.preview.consent_text)
    result = service.dispatch(req)
    assert result.status == "verified" and result.receipt.content_id == POST
    assert wire.calls[0][0:2] == ("POST", f"/{official.GRAPH_VERSION}/{PAGE}/feed")
    assert parse_qs(wire.calls[0][2].decode()) == {"message": [CAPTION], "published": ["true"]}
    assert wire.calls[1][0:2] == ("GET", f"/{official.GRAPH_VERSION}/{POST}?fields=id,message,from,is_published")
    assert wire.closes == 2
    assert all(ref.service == "Onyx.Social.FacebookPage" and ref.account == PAGE for ref in refs)
    assert TOKEN not in service.path.read_bytes()
    with pytest.raises(SocialPublishDenied, match="blind retry"):
        service.dispatch(req)
    assert len(wire.calls) == 2


@pytest.mark.parametrize("changes", [{"target": "instagram-feed"}, {"account_id": "654321"},
                                    {"media_digests": ("a" * 64,)}])
def test_wrong_platform_account_and_media_never_send(tmp_path, changes):
    service, wire = runtime(tmp_path)
    req = consent(service, request(**changes))
    with pytest.raises(SocialPublishUncertain):
        service.dispatch(req)
    assert not wire.calls


def test_changed_caption_invalidates_consent_without_http(tmp_path):
    service, wire = runtime(tmp_path)
    consent(service)
    with pytest.raises(SocialPublishDenied):
        service.dispatch(request(caption="changed"))
    assert not wire.calls


@pytest.mark.parametrize("changes", [{"message": "changed"}, {"from": {"id": "999"}},
                                    {"id": PAGE + "_111"}, {"is_published": False},
                                    {"is_published": "true"}, {"from": None}])
def test_readback_mismatch_never_verifies(tmp_path, changes):
    service, wire = runtime(tmp_path, FakeWire([(200, {"id": POST}), (200, readback(**changes))]))
    result = service.dispatch(consent(service))
    assert result.status == "uncertain_needs_reconciliation"
    assert len(wire.calls) == 2


@pytest.mark.parametrize("reply", [(302, {"location": "https://evil.test"}), (401, {}),
                                  (403, {}), (429, {}), (500, {}), (200, {"error": "secret"}),
                                  (200, b"bad-json"), (200, []), (200, {"id": "other_123"}),
                                  (200, b"x" * (official.MAX_RESPONSE_BYTES + 1)),
                                  TimeoutError("synthetic-test-token")])
def test_dispatch_errors_are_uncertain_redacted_and_never_retried(tmp_path, reply):
    service, wire = runtime(tmp_path, FakeWire([reply]))
    req = consent(service)
    with pytest.raises(SocialPublishUncertain) as error:
        service.dispatch(req)
    formatted = "".join(traceback.format_exception(error.value))
    assert TOKEN.decode() not in formatted
    assert len(wire.calls) == 1 and wire.closes == 1
    with pytest.raises(SocialPublishDenied):
        service.dispatch(req)
    assert len(wire.calls) == 1


def test_readback_reconciles_after_restart_with_get_only(tmp_path):
    service, wire = runtime(tmp_path, FakeWire([(200, {"id": POST}), (503, {})]))
    req = consent(service)
    digest = service.create_preview(req).preview.request_digest
    with pytest.raises(SocialPublishUncertain, match="readback"):
        service.dispatch(req)
    restarted, later = runtime(tmp_path, FakeWire([(200, readback())]))
    assert restarted.reconcile(digest).status == "verified"
    assert [call[0] for call in later.calls] == ["GET"]
    with pytest.raises(SocialPublishDenied):
        restarted.dispatch(req)
    assert len(wire.calls) == 2


def test_vault_backend_error_does_not_leak_secret(tmp_path):
    def broken(ref):
        raise RuntimeError(TOKEN.decode())
    with pytest.raises(official.SocialOfficialAdapterError) as error:
        runtime(tmp_path, vault_reader=broken)
    assert TOKEN.decode() not in "".join(traceback.format_exception(error.value))


def test_endpoint_guard_and_receipt_guard_before_network(tmp_path):
    service, wire = runtime(tmp_path)
    adapter = service._adapter
    for method, path in [("GET", "//evil.test"), ("POST", "/999/feed"), ("DELETE", f"/{POST}"),
                         ("GET", f"/{POST}?access_token=bad")]:
        with pytest.raises(official.SocialOfficialAdapterError, match="allowlisted"):
            adapter._request(method, path)
    with pytest.raises(official.SocialOfficialAdapterError):
        adapter.observe(ProviderReceiptV1("999_123", "999_123"))
    assert not wire.calls


def test_direct_adapter_dispatch_without_ledger_consent_denied(tmp_path):
    service, wire = runtime(tmp_path)
    req = request()
    preview = service.create_preview(req).preview
    with pytest.raises(official.SocialOfficialAdapterError):
        service._adapter.dispatch(ProviderDispatchV1(
            preview.request_digest, preview.request_digest, PAGE, official.TARGET, CAPTION, (),
        ))
    assert not wire.calls


def test_existing_owner_cli_factory_preview_consent_dispatch(tmp_path, monkeypatch, capsys):
    from scripts import onyx_social_cli as cli

    wire = FakeWire()
    real_factory = official.create_social_official_publication_v1
    monkeypatch.setattr(cli, "create_social_official_publication_v1", lambda **kw: real_factory(
        **kw, vault_reader=lambda ref: TOKEN, connection_factory=wire,
    ))
    monkeypatch.setenv("ONYX_SOCIAL_PUBLISH_V1", "true")
    common = ["--facebook-page-id", PAGE, "--ledger-path", str(tmp_path / "owner.sqlite3")]
    fields = ["--workspace-id", "workspace-test", "--principal-id", "owner-test",
              "--account-id", PAGE, "--target", official.TARGET, "--caption", CAPTION]
    assert cli.cli_main(common + ["publish-preview", *fields]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert not wire.calls
    assert cli.cli_main(common + ["publish-consent", *fields, "--exact-consent",
                                  preview["preview"]["consent_text"]]) == 0
    capsys.readouterr()
    assert not wire.calls
    assert cli.cli_main(common + ["publish-dispatch", *fields]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
    assert cli.cli_main(common + ["publish-dispatch", *fields]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "publication_denied"
    assert len(wire.calls) == 2


def test_windowless_owner_cli_output_is_exclusive(tmp_path, monkeypatch):
    from scripts import onyx_social_cli as cli

    monkeypatch.setattr(cli.sys, "stdout", None)
    monkeypatch.setattr(cli.sys, "stderr", None)
    path = tmp_path / "draft.json"
    args = ["--output", str(path), "generate", "--brief", "Evidence", "--brand", "Test",
            "--platform", "facebook"]
    assert cli.cli_main(args) == 0
    original = path.read_bytes()
    assert json.loads(original)["status"] == "draft"
    assert cli.cli_main(args) == 2
    assert path.read_bytes() == original
    assert cli.cli_main(["--help"]) == 0
    assert cli.cli_main(["no-such-operation", "synthetic-test-token"]) == 2


def test_output_failure_happens_before_provider_factory(tmp_path, monkeypatch, capsys):
    from scripts import onyx_social_cli as cli

    monkeypatch.setattr(cli, "create_social_official_publication_v1",
                        lambda **kw: pytest.fail("must reserve output first"))
    path = tmp_path / "existing.json"
    path.touch()
    assert cli.cli_main(["--output", str(path), "--facebook-page-id", PAGE,
                         "publish-status", "--request-digest", "a" * 64]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "local_io_unavailable"


def test_windowless_failure_writes_structured_json_without_secrets(tmp_path, monkeypatch):
    from scripts import onyx_social_cli as cli

    monkeypatch.setattr(cli.sys, "stdout", None)
    monkeypatch.setattr(cli.sys, "stderr", None)
    def failure(**kw):
        raise RuntimeError(TOKEN.decode())
    monkeypatch.setattr(cli, "create_social_official_publication_v1", failure)
    path = tmp_path / "error.json"
    assert cli.cli_main(["--output", str(path), "--facebook-page-id", PAGE,
                         "publish-status", "--request-digest", "a" * 64]) == 2
    assert json.loads(path.read_text())["status"] == "error"
    assert TOKEN.decode() not in path.read_text()


@pytest.mark.parametrize("name", ["CON.json", "NUL.json", "bad.txt", "ads:stream.json"])
def test_cli_rejects_unsafe_output_names(tmp_path, name, capsys):
    from scripts import onyx_social_cli as cli

    assert cli.cli_main(["--output", str(tmp_path / name), "generate", "--brief", "Test",
                         "--brand", "Test", "--platform", "facebook"]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "unsafe_output_path"
