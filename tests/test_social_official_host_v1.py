from unittest.mock import Mock

import pytest

from core.capability_expansion_service_v1 import CapabilityExpansionServiceV1
from core import social_official_adapter_v1 as official


def service(root, **settings):
    return CapabilityExpansionServiceV1(root, config=settings, environ={})


def test_local_social_default_never_opens_official_vault(tmp_path, monkeypatch):
    factory = Mock(side_effect=AssertionError("unexpected official integration"))
    monkeypatch.setattr(official, "create_social_official_publication_v1", factory)
    host = service(tmp_path, ONYX_SOCIAL_PUBLISH_V1=True)
    assert host.social is None
    factory.assert_not_called()


def test_bad_official_configuration_does_not_crash_assistant(tmp_path):
    host = service(tmp_path, ONYX_SOCIAL_PUBLISH_V1=True,
                   ONYX_SOCIAL_OFFICIAL_FACEBOOK_V1=True,
                   ONYX_SOCIAL_FACEBOOK_PAGE_ID="https://untrusted.invalid/")
    assert host.social is None
    status = host._domain_dispatch("social", "status", {})
    assert status["official_configuration_error"] is not None
    assert status["live_publication_certified"] is False


def test_configured_host_uses_durable_owner_cli_ledger(tmp_path, monkeypatch):
    publication = Mock()
    factory = Mock(return_value=publication)
    monkeypatch.setattr(official, "create_social_official_publication_v1", factory)
    host = service(tmp_path, ONYX_SOCIAL_PUBLISH_V1=True,
                   ONYX_SOCIAL_OFFICIAL_FACEBOOK_V1=True,
                   ONYX_SOCIAL_FACEBOOK_PAGE_ID="12345")
    assert host.social is publication
    assert factory.call_args.kwargs["ledger_path"] == tmp_path / "capability_social_v1.sqlite3"
    status = host._domain_dispatch("social", "status", {})
    assert status["publishing"] == "owner-cli-ready"
    assert status["official_platforms"] == ["facebook-page-feed-text"]
    assert status["live_publication_certified"] is False
    with pytest.raises(PermissionError):
        host._domain_dispatch("social", "publish", {})
    publication.dispatch.assert_not_called()
