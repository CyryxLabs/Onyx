from __future__ import annotations

import pytest

from core.portable_accessibility_actions_v1 import (
    AccessibilityActionV1,
    AccessibilityTargetV1,
    NativeAccessibilityReceiptV1,
    PortableAccessibilityDenied,
    PortableAccessibilityError,
    PortableAccessibilitySessionV1,
)


def _request(platform="Darwin", value=None, action="invoke"):
    return AccessibilityActionV1(
        "request.open",
        "owner.primary",
        "workspace.main",
        platform,
        AccessibilityTargetV1("com.apple.TextEdit", "AXButton", "Open"),
        action,
        value,
    )


class Backend:
    platform = "Darwin"

    def __init__(self, drift=False):
        self.calls = []
        self.drift = drift

    def perform(self, request):
        self.calls.append(request)
        return NativeAccessibilityReceiptV1(
            request.request_id,
            request.digest,
            request.target.application_id,
            request.target.role,
            "Wrong" if self.drift else request.target.accessible_name,
            request.action,
            True,
            1000.0,
        )


def test_typed_action_requires_authority_and_exact_postcondition_receipt() -> None:
    backend = Backend()
    session = PortableAccessibilitySessionV1(
        platform="Darwin", enabled=True, authority=lambda request: True, backend=backend
    )
    receipt = session.perform(_request())
    assert receipt.postcondition_verified is True
    assert len(backend.calls) == 1
    assert session.background_workers == 0 and session.polling_interval is None


def test_denial_prevents_native_adapter_and_receipt_drift_fails_closed() -> None:
    backend = Backend()
    denied = PortableAccessibilitySessionV1(
        platform="Darwin",
        enabled=True,
        authority=lambda request: False,
        backend=backend,
    )
    with pytest.raises(PortableAccessibilityDenied):
        denied.perform(_request())
    assert backend.calls == []
    drift = PortableAccessibilitySessionV1(
        platform="Darwin",
        enabled=True,
        authority=lambda request: True,
        backend=Backend(drift=True),
    )
    with pytest.raises(PortableAccessibilityError):
        drift.perform(_request())


def test_raw_shell_coordinates_and_secret_like_values_are_unrepresentable() -> None:
    with pytest.raises(ValueError):
        _request(action="shell")
    with pytest.raises(PortableAccessibilityDenied):
        _request(action="type_text", value="password=hidden")
    with pytest.raises(PortableAccessibilityDenied):
        PortableAccessibilitySessionV1(
            platform="Windows",
            enabled=True,
            authority=lambda request: True,
            backend=Backend(),
        )
