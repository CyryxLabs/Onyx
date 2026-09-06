"""Official Facebook Pages text publishing behind SocialPublicationV1 governance.

No network or vault I/O on import. The factory is disabled by default. No other
social platform, media upload, OAuth acquisition or automatic retry is supported.
"""

from __future__ import annotations

import http.client
import json
import re
import sqlite3
import ssl
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from core.native_vault import NativeSecretVault, SecretReference
from core.social_publish_v1 import (
    CaptionRequestV1,
    ProviderDispatchV1,
    ProviderObservationV1,
    ProviderReceiptV1,
    SocialPublicationV1,
    SocialPublishDenied,
    SocialPublishFeatureGateV1,
    create_social_publication_v1,
    preview_caption,
)


GRAPH_HOST = "graph.facebook.com"
GRAPH_VERSION = "v26.0"
TARGET = "facebook-page-feed"
MAX_RESPONSE_BYTES = 65_536
_PAGE_ID = re.compile(r"[1-9][0-9]{0,31}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(rb"[A-Za-z0-9._~+/=-]{1,2048}")


class SocialOfficialAdapterError(RuntimeError):
    """Safe-to-display error; never contains credentials or provider bodies."""


@dataclass(frozen=True, slots=True)
class FacebookPageConfigV1:
    """Explicit non-secret Page binding; no endpoint or credential overrides."""

    page_id: str
    timeout_seconds: int = 15

    def __post_init__(self) -> None:
        if type(self.page_id) is not str or _PAGE_ID.fullmatch(self.page_id) is None:
            raise SocialOfficialAdapterError("facebook_page_id_invalid")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 60:
            raise SocialOfficialAdapterError("timeout_must_be_1_to_60_seconds")


def facebook_page_vault_reference_v1(page_id: str) -> SecretReference:
    """Reference for an operator-provisioned UTF-8 Page access token."""
    FacebookPageConfigV1(page_id)
    return SecretReference("Onyx.Social.FacebookPage", page_id, "Onyx Facebook Page access token")


def _native_reader(reference: SecretReference) -> bytes | None:
    return NativeSecretVault(reference).get_bytes()


class _FacebookPagesAdapterV1:
    """Internal provider boundary. Call through the factory's governed service."""

    def __init__(self, config: FacebookPageConfigV1, ledger_path: Path,
                 vault_reader: Callable, connection_factory: Callable):
        self.config = config
        self.path = ledger_path
        self._vault_reader = vault_reader
        self._connection_factory = connection_factory

    def _token(self) -> str:
        try:
            raw = self._vault_reader(facebook_page_vault_reference_v1(self.config.page_id))
            if type(raw) is not bytes or _TOKEN.fullmatch(raw) is None:
                raise ValueError
            return raw.decode("ascii")
        except Exception:
            raise SocialOfficialAdapterError("facebook_page_vault_credential_unavailable") from None

    def _request(self, method: str, resource: str, payload: dict | None = None) -> dict:
        # Closed origin and closed path shapes: no redirects, proxy env, or caller URL.
        page = self.config.page_id
        if method == "POST" and resource == f"/{page}/feed":
            path = f"/{GRAPH_VERSION}{resource}"
        elif method == "GET" and re.fullmatch(rf"/{page}_[1-9][0-9]{{0,31}}", resource):
            path = f"/{GRAPH_VERSION}{resource}?fields=id,message,from,is_published"
        else:
            raise SocialOfficialAdapterError("endpoint_not_allowlisted")
        token = self._token()
        body = urlencode(payload).encode("utf-8") if payload is not None else None
        connection = None
        try:
            connection = self._connection_factory(
                GRAPH_HOST, 443, timeout=self.config.timeout_seconds,
                context=ssl.create_default_context(),
            )
            connection.request(method, path, body=body, headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            })
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                # Never log the provider body, redirect Location, or transport exception.
                status = response.status
                if type(status) is not int:
                    raise SocialOfficialAdapterError("provider_status_invalid")
                raise SocialOfficialAdapterError(f"facebook_http_{status}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise SocialOfficialAdapterError("provider_response_budget_exceeded")
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                raise SocialOfficialAdapterError("provider_response_invalid_json") from None
            if type(data) is not dict or "error" in data:
                raise SocialOfficialAdapterError("provider_response_error")
            return data
        except SocialOfficialAdapterError:
            raise
        except Exception:
            raise SocialOfficialAdapterError("facebook_transport_outcome_unknown") from None
        finally:
            if connection is not None:
                with suppress(Exception):
                    connection.close()

    def _ledger_request(self, *, digest: str | None = None,
                        receipt: ProviderReceiptV1 | None = None) -> tuple[CaptionRequestV1, dict]:
        """Read existing consent/payload authority without mutating core's ledger."""
        try:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
                db.row_factory = sqlite3.Row
                if digest is not None:
                    rows = db.execute(
                        "SELECT * FROM social_publications_v1 WHERE request_digest=?", (digest,)
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT * FROM social_publications_v1 "
                        "WHERE json_extract(receipt_json, '$.content_id')=? LIMIT 2",
                        (receipt.content_id,),
                    ).fetchall()
            if len(rows) != 1:
                raise ValueError
            row = dict(rows[0])
            values = json.loads(row["request_json"])
            for field in ("media_digests", "provenance", "warnings"):
                values[field] = tuple(values[field])
            request = CaptionRequestV1(**values)
            if (row["consented"] != 1 or row["dispatch_attempted"] != 1
                    or request.account_id != self.config.page_id or request.target != TARGET
                    or request.media_digests
                    or preview_caption(request).request_digest != row["request_digest"]):
                raise ValueError
            return request, row
        except Exception:
            raise SocialOfficialAdapterError("publication_ledger_binding_invalid") from None

    def dispatch(self, request: ProviderDispatchV1) -> ProviderReceiptV1:
        if (type(request) is not ProviderDispatchV1
                or type(request.request_digest) is not str
                or _DIGEST.fullmatch(request.request_digest) is None
                or request.idempotency_key != request.request_digest
                or request.account_id != self.config.page_id or request.target != TARGET
                or request.media_digests):
            raise SocialOfficialAdapterError("facebook_text_dispatch_binding_invalid")
        persisted, row = self._ledger_request(digest=request.request_digest)
        if row["status"] != "dispatching" or persisted.caption != request.caption:
            raise SocialOfficialAdapterError("publication_not_authorized_for_dispatch")
        data = self._request("POST", f"/{self.config.page_id}/feed", {
            "message": request.caption, "published": "true",
        })
        content_id = data.get("id")
        if type(content_id) is not str or re.fullmatch(
            rf"{self.config.page_id}_[1-9][0-9]{{0,31}}", content_id
        ) is None:
            raise SocialOfficialAdapterError("provider_post_id_invalid_outcome_unknown")
        # This is the provider-assigned post ID, not a fabricated request identifier.
        return ProviderReceiptV1(provider_request_id=content_id, content_id=content_id)

    def observe(self, receipt: ProviderReceiptV1) -> ProviderObservationV1:
        if (type(receipt) is not ProviderReceiptV1 or type(receipt.content_id) is not str
                or receipt.provider_request_id != receipt.content_id
                or re.fullmatch(rf"{self.config.page_id}_[1-9][0-9]{{0,31}}", receipt.content_id) is None):
            raise SocialOfficialAdapterError("provider_receipt_invalid")
        expected, row = self._ledger_request(receipt=receipt)
        if (json.loads(row["receipt_json"]) != {
                "provider_request_id": receipt.provider_request_id, "content_id": receipt.content_id}
                or row["status"] not in ("dispatching", "uncertain_needs_reconciliation", "verified")):
            raise SocialOfficialAdapterError("provider_receipt_ledger_mismatch")
        data = self._request("GET", f"/{receipt.content_id}")
        author = data.get("from")
        verified = (
            data.get("id") == receipt.content_id and data.get("message") == expected.caption
            and type(author) is dict and author.get("id") == self.config.page_id
            and data.get("is_published") is True
        )
        return ProviderObservationV1("verified" if verified else "unknown", receipt.content_id)


def create_social_official_publication_v1(
    *, gate: SocialPublishFeatureGateV1 = SocialPublishFeatureGateV1(False),
    config: FacebookPageConfigV1 | None = None, ledger_path: Path | None = None,
    vault_reader: Callable = _native_reader,
    connection_factory: Callable = http.client.HTTPSConnection,
) -> SocialPublicationV1 | None:
    """Main/CLI factory hook; construction never publishes or performs HTTP.

    Returns the existing consent/readback/single-dispatch service. Keep its ledger
    durable across restarts; dependency overrides are trusted test seams only.
    """
    if type(gate) is not SocialPublishFeatureGateV1:
        raise SocialPublishDenied("social_feature_gate_invalid")
    if not gate.enabled:
        return None
    if type(config) is not FacebookPageConfigV1:
        raise SocialPublishDenied("explicit_facebook_page_configuration_required")
    if (not isinstance(ledger_path, Path) or not ledger_path.is_absolute()
            or ledger_path.is_symlink()):
        raise SocialPublishDenied("absolute_trusted_social_ledger_required")
    adapter = _FacebookPagesAdapterV1(config, ledger_path.resolve(), vault_reader, connection_factory)
    adapter._token()  # Fail before preview/consent when the operator has no vault token.
    return create_social_publication_v1(gate=gate, adapter=adapter, ledger_path=ledger_path)
