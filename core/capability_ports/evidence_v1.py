"""Correlation/redaction evidence validation with sealed provider-free writes."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({"validate.receipt", "append.test"})
_TEST_WRITE_SEAL = object()


class EvidenceValidationPortV1(HostBoundCapabilityPortV1):
    def __init__(self, *, writer: Callable[[Mapping[str, object]], object] | None = None, _seal: object = None) -> None:
        super().__init__()
        if writer is not None and (_seal is not _TEST_WRITE_SEAL or not callable(writer)):
            raise GovernanceV1ContractError("evidence append authority is unavailable")
        self._writer = writer
        self._seen: set[str] = set()
        self._killed = False

    @classmethod
    def provider_free_test_double(cls, writer: Callable[[Mapping[str, object]], object]) -> "EvidenceValidationPortV1":
        return cls(writer=writer, _seal=_TEST_WRITE_SEAL)

    @staticmethod
    def _validate(arguments: Mapping[str, object]) -> str:
        correlation = arguments.get("correlation_id")
        receipt_correlation = arguments.get("receipt_correlation_id")
        if not isinstance(correlation, str) or correlation != receipt_correlation:
            raise GovernanceV1Denied("evidence receipt correlation mismatch")
        if arguments.get("redacted") is not True or "content" in arguments or "secret" in arguments:
            raise GovernanceV1Denied("evidence receipt is not redacted")
        return correlation

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        if self._killed:
            raise GovernanceV1Denied("evidence adapter kill is latched")
        correlation = self._validate(arguments)
        if correlation in self._seen:
            raise GovernanceV1Denied("evidence receipt replay denied")
        self._seen.add(correlation)
        if operation == "validate.receipt":
            return {"valid": True, "redacted": True}
        if operation == "append.test" and self._writer is not None:
            return self._writer(dict(arguments))
        raise GovernanceV1Denied("evidence append is default-deny")

    def revoke(self, binding_id: str) -> None:
        del binding_id

    def kill(self) -> bool:
        self._killed = True
        return True

