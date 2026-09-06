from dataclasses import asdict
from pathlib import Path

import pytest

from core.capability_ports.social_v1 import SocialCapabilityPortV1
from core.governance_nucleus_v1 import GovernanceV1Denied
from core.social_publish_v1 import (
    CaptionRequestV1,
    ProviderObservationV1,
    ProviderReceiptV1,
    SocialPublicationV1,
)


class _Provider:
    def __init__(self) -> None:
        self.dispatches = 0

    def dispatch(self, request: object) -> ProviderReceiptV1:
        self.dispatches += 1
        return ProviderReceiptV1("provider-request", "content-a")

    def observe(self, receipt: ProviderReceiptV1) -> ProviderObservationV1:
        return ProviderObservationV1("verified", receipt.content_id)


def _arguments() -> dict[str, object]:
    return asdict(CaptionRequestV1(
        "workspace-a", "principal-a", "account-a", "linkedin", "Exact draft",
    ))


def test_social_uses_durable_preview_consent_dispatch_observe_ledger(tmp_path: Path) -> None:
    provider = _Provider()
    port = SocialCapabilityPortV1(SocialPublicationV1(provider, tmp_path / "social.sqlite3"))
    arguments = _arguments()
    preview = port._dispatch_authorized("preview", arguments)
    assert provider.dispatches == 0
    consent = {**arguments, "exact_consent": preview.preview.consent_text}
    assert port._dispatch_authorized("consent", consent).consented is True
    verified = port._dispatch_authorized("dispatch", arguments)
    assert verified.status == "verified"
    observed = port._dispatch_authorized("observe", {"request_digest": verified.preview.request_digest})
    assert observed.status == "verified"
    assert provider.dispatches == 1


def test_social_has_no_default_blind_dispatch_and_lifecycle_is_distinct(tmp_path: Path) -> None:
    provider = _Provider()
    port = SocialCapabilityPortV1(SocialPublicationV1(provider, tmp_path / "social.sqlite3"))
    with pytest.raises(Exception, match="blind retry denied"):
        port._dispatch_authorized("dispatch", _arguments())
    assert provider.dispatches == 0
    assert port.revoke("binding-a")["status"] == "binding-revoked"
    assert port.disconnect()["status"] == "disconnected"
    assert port.close()["status"] == "closed"
    assert port.kill()["status"] == "kill-latched"
    with pytest.raises(GovernanceV1Denied, match="kill"):
        port._dispatch_authorized("preview", _arguments())
