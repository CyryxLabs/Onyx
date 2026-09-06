"""Governed social preview/consent/dispatch/observation capability port."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.social_publish_v1 import CaptionRequestV1, SocialPublicationV1
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({"preview", "consent", "dispatch", "observe", "reconcile"})
_REQUEST_FIELDS = frozenset({
    "workspace_id", "principal_id", "account_id", "target", "caption",
    "media_digests", "provenance", "warnings",
})


class SocialCapabilityPortV1(HostBoundCapabilityPortV1):
    """Delegate every publication transition to the durable social ledger."""

    def __init__(self, publication: SocialPublicationV1) -> None:
        super().__init__()
        if type(publication) is not SocialPublicationV1:
            raise GovernanceV1ContractError("exact SocialPublicationV1 is required")
        self._publication = publication
        self._lock = RLock()
        self._revoked: set[str] = set()
        self._disconnected = False
        self._closed = False
        self._killed = False

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        with self._lock:
            if self._killed:
                raise GovernanceV1Denied("social port kill is latched")
            if self._closed or self._disconnected:
                raise GovernanceV1Denied("social port is unavailable")
        if operation in {"observe", "reconcile"}:
            if set(arguments) != {"request_digest"}:
                raise GovernanceV1ContractError("request_digest is required")
            digest = self._text(arguments["request_digest"])
            return self._publication.status(digest) if operation == "observe" else self._publication.reconcile(digest)
        expected = _REQUEST_FIELDS | ({"exact_consent"} if operation == "consent" else frozenset())
        if set(arguments) != expected:
            raise GovernanceV1ContractError("social request fields mismatch")
        request = CaptionRequestV1(**{key: arguments[key] for key in _REQUEST_FIELDS})
        if operation == "preview":
            return self._publication.create_preview(request)
        if operation == "consent":
            return self._publication.consent(request, exact_consent=self._text(arguments["exact_consent"]))
        if operation == "dispatch":
            return self._publication.dispatch(request)
        raise GovernanceV1Denied("unknown social operation")

    @staticmethod
    def _text(value: object) -> str:
        if type(value) is not str or not value or "\x00" in value:
            raise GovernanceV1ContractError("social identifier is invalid")
        return value

    def revoke(self, binding_id: str) -> dict[str, object]:
        with self._lock:
            self._revoked.add(binding_id)
        return {"status": "binding-revoked", "binding_id": binding_id}

    def disconnect(self) -> dict[str, object]:
        with self._lock:
            self._disconnected = True
        return {"status": "disconnected", "closed": False, "killed": False}

    def close(self) -> dict[str, object]:
        with self._lock:
            self._closed = True
        return {"status": "closed", "killed": False}

    def kill(self) -> dict[str, object]:
        with self._lock:
            self._killed = True
        return {"status": "kill-latched"}


__all__ = ["OPERATIONS", "SocialCapabilityPortV1"]
