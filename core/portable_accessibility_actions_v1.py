"""Typed macOS/Linux accessibility seam with central Onyx authority.

The contract contains no shell, coordinates, arbitrary selectors, scripts,
process launch, retries or polling.  A native adapter must resolve one exact
application/accessibility node, perform one allowlisted action and return a
postcondition receipt.  Native proof remains platform-specific.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Final, Protocol


FEATURE_FLAG: Final = "ONYX_PORTABLE_ACCESSIBILITY_ACTIONS_V1"
PLATFORMS: Final = ("Darwin", "Linux")
ACTIONS: Final = ("focus", "invoke", "set_value", "type_text")
_APP = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_SECRET = re.compile(r"(?i)(?:api[_-]?key|password|private[_-]?key|access[_-]?token|bearer)\s*[:=]")


class PortableAccessibilityContractError(ValueError):
    pass


class PortableAccessibilityDenied(PermissionError):
    pass


class PortableAccessibilityError(RuntimeError):
    pass


def _bounded(value: object, label: str, maximum: int) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value or len(value) > maximum:
        raise PortableAccessibilityContractError(f"{label} is invalid")
    return " ".join(value.split())


@dataclass(frozen=True, slots=True)
class AccessibilityTargetV1:
    application_id: str
    role: str
    accessible_name: str

    def __post_init__(self) -> None:
        if type(self.application_id) is not str or _APP.fullmatch(self.application_id) is None:
            raise PortableAccessibilityContractError("application_id is invalid")
        _bounded(self.role, "role", 80)
        _bounded(self.accessible_name, "accessible_name", 160)


@dataclass(frozen=True, slots=True)
class AccessibilityActionV1:
    request_id: str
    owner_profile_id: str
    workspace_id: str
    platform: str
    target: AccessibilityTargetV1
    action: str
    value: str | None = None

    def __post_init__(self) -> None:
        for value, label in ((self.request_id, "request_id"), (self.owner_profile_id, "owner_profile_id"), (self.workspace_id, "workspace_id")):
            if type(value) is not str or _APP.fullmatch(value) is None:
                raise PortableAccessibilityContractError(f"{label} is invalid")
        if self.platform not in PLATFORMS or self.action not in ACTIONS:
            raise PortableAccessibilityContractError("platform or action is invalid")
        if type(self.target) is not AccessibilityTargetV1:
            raise PortableAccessibilityContractError("exact target is required")
        needs_value = self.action in {"set_value", "type_text"}
        if needs_value != (self.value is not None):
            raise PortableAccessibilityContractError("action value contract is invalid")
        if self.value is not None:
            checked = _bounded(self.value, "value", 512)
            if _SECRET.search(checked):
                raise PortableAccessibilityDenied("secret-like accessibility value is forbidden")

    @property
    def digest(self) -> str:
        payload = {"request_id": self.request_id, "owner_profile_id": self.owner_profile_id,
                   "workspace_id": self.workspace_id, "platform": self.platform,
                   "application_id": self.target.application_id, "role": self.target.role,
                   "accessible_name": self.target.accessible_name, "action": self.action,
                   "value_digest": None if self.value is None else hashlib.sha256(self.value.encode()).hexdigest()}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class NativeAccessibilityReceiptV1:
    request_id: str
    request_digest: str
    application_id: str
    role: str
    accessible_name: str
    action: str
    postcondition_verified: bool
    observed_at: float


class NativeAccessibilityBackendV1(Protocol):
    platform: str
    def perform(self, request: AccessibilityActionV1) -> NativeAccessibilityReceiptV1: ...


class PortableAccessibilitySessionV1:
    def __init__(self, *, platform: str, enabled: bool, authority: Callable[[AccessibilityActionV1], bool], backend: NativeAccessibilityBackendV1) -> None:
        if platform not in PLATFORMS or type(enabled) is not bool or not enabled:
            raise PortableAccessibilityDenied("portable accessibility is unavailable")
        if not callable(authority) or getattr(backend, "platform", None) != platform or not callable(getattr(backend, "perform", None)):
            raise PortableAccessibilityContractError("accessibility dependencies are invalid")
        self.platform = platform
        self._authority = authority
        self._backend = backend
        self.background_workers = 0
        self.polling_interval = None

    def perform(self, request: AccessibilityActionV1) -> NativeAccessibilityReceiptV1:
        if type(request) is not AccessibilityActionV1 or request.platform != self.platform:
            raise PortableAccessibilityContractError("exact platform request is required")
        decision = self._authority(request)
        if type(decision) is not bool or not decision:
            raise PortableAccessibilityDenied("central authority denied accessibility action")
        receipt = self._backend.perform(request)
        if type(receipt) is not NativeAccessibilityReceiptV1:
            raise PortableAccessibilityError("native adapter returned no exact receipt")
        expected = (request.request_id, request.digest, request.target.application_id,
                    request.target.role, request.target.accessible_name, request.action, True)
        observed = (receipt.request_id, receipt.request_digest, receipt.application_id,
                    receipt.role, receipt.accessible_name, receipt.action,
                    receipt.postcondition_verified)
        if observed != expected:
            raise PortableAccessibilityError("native accessibility receipt diverged")
        return receipt


__all__ = ["FEATURE_FLAG", "PLATFORMS", "ACTIONS", "AccessibilityTargetV1",
           "AccessibilityActionV1", "NativeAccessibilityReceiptV1",
           "NativeAccessibilityBackendV1", "PortableAccessibilitySessionV1",
           "PortableAccessibilityContractError", "PortableAccessibilityDenied",
           "PortableAccessibilityError"]
