from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import capability_extensions_live_v1 as capability_live
from core.capability_extensions_controller_v1 import (
    CapabilityExtensionsControllerDenied,
    CapabilityExtensionsControllerV1,
)
from core.capability_extensions_live_v1 import (
    CapabilityExtensionAdaptersV1,
    CapabilityExtensionGatesV1,
    CapabilityExtensionsDenied,
    CapabilityExtensionsSessionV1,
    CapabilityExternalOutcomeUnknown,
)
from core.native_vault import SecretReference
from core.official_messaging_v1 import (
    DiscordAccountV1,
    ProviderMessageReceiptV1,
)
from core.phase6_live_wiring_v1 import (
    SESSION_ATTRIBUTE,
    LiveWiringIdentityV1,
    LiveWiringSessionV1,
)
from core.portable_accessibility_actions_v1 import NativeAccessibilityReceiptV1


CHANNEL = "123456789012345678"


def _session(tmp_path: Path) -> LiveWiringSessionV1:
    session = object.__new__(LiveWiringSessionV1)
    object.__setattr__(
        session,
        "identity",
        LiveWiringIdentityV1(
            "workspace-personal", "account-primary", "owner-primary", "principal-primary"
        ),
    )
    object.__setattr__(session, "session_key", "session_capability_extensions")
    object.__setattr__(session, "state_path", tmp_path / "phase6.sqlite3")
    object.__setattr__(session, "receipt_path", tmp_path / "receipts.sqlite3")
    object.__setattr__(session, "facade", SimpleNamespace())
    object.__setattr__(session, "binding_digest", "0" * 64)
    object.__setattr__(session, "_closed", False)
    return session


def _execute(
    controller: CapabilityExtensionsControllerV1,
    arguments: dict[str, object],
    *,
    invocation_id: str = "fc-capability-test",
    trace_id: str = "0123456789abcdef",
):
    return controller.execute(
        arguments,
        invocation_id=invocation_id,
        trace_id=trace_id,
    )


def _controller(
    tmp_path: Path,
    *,
    gates: CapabilityExtensionGatesV1,
    adapters: CapabilityExtensionAdaptersV1 | None = None,
    authorizer: object | None = None,
    governance: object | None = None,
    host_capture: list[object] | None = None,
) -> CapabilityExtensionsControllerV1:
    host = SimpleNamespace()
    if host_capture is not None:
        host_capture.append(host)
    if governance is not None:
        host._governance_nucleus_v1 = governance
    setattr(host, SESSION_ATTRIBUTE, _session(tmp_path))
    controller = CapabilityExtensionsControllerV1(
        host,
        gates=gates,
        adapters=adapters or CapabilityExtensionAdaptersV1(),
        central_authorizer=authorizer or (lambda _tool, _arguments: (True, "broker-proof")),
        audit_trace_setter=lambda _trace_id: object(),
        audit_trace_resetter=lambda _token: None,
    )
    return controller


def test_default_off_status_creates_no_sidecar_or_external_call(tmp_path: Path) -> None:
    controller = _controller(tmp_path, gates=CapabilityExtensionGatesV1())
    status_args = {"action": "status"}
    status = _execute(controller, status_args)
    assert status["features"] == {
        "device_pairing": False,
        "official_messaging": False,
        "site_recipes": False,
        "portable_accessibility": False,
        "content_lifecycle": False,
    }
    assert status["external_dispatch"] is False
    assert status["background_workers"] == 0
    assert not (tmp_path / "capability-extensions-v1").exists()


def test_local_pairing_recipe_and_content_projection_are_really_wired(tmp_path: Path) -> None:
    presented = []
    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(
            device_pairing=True,
            site_recipes=True,
            content_lifecycle=True,
        ),
        adapters=CapabilityExtensionAdaptersV1(
            pairing_presenter=lambda owner, workspace, challenge: (
                presented.append((owner, workspace, challenge.display_code)) or True
            )
        ),
    )
    pairing_args = {
        "action": "initiate_pairing",
        "device_id": "device.phone",
        "issuer": "onyx.phone",
        "ttl_seconds": 180,
    }
    paired = _execute(controller, pairing_args)
    assert presented and presented[0][2]
    assert "display_code" not in paired["pairing"]
    assert presented[0][2] not in repr(paired)
    assert paired["pairing"]["credential_issued"] is False
    assert paired["external_dispatch"] is False

    recipe_args = {
        "action": "plan_site_recipe",
        "recipe_id": "company_site",
        "project_slug": "cyryx-site",
        "title": "Cyryx Labs",
        "summary": "Governed operations for the owner.",
    }
    plan = _execute(controller, recipe_args)
    assert plan["site_plan"]["files"]
    assert plan["external_dispatch"] is False

    content_args = {
        "action": "schedule_content",
        "provider": "discord",
        "account_id": "discord.cyryx",
        "destination_id": "channel.primary",
        "content": "Body that must be represented by digest only.",
        "scheduled_for": 2_000_000_000.0,
    }
    content = _execute(controller, content_args)
    assert content["content"]["status"] == "scheduled"
    raw = (tmp_path / "capability-extensions-v1" / "content-lifecycle.sqlite3").read_bytes()
    assert b"Body that must be represented by digest only" not in raw


def test_pairing_claim_is_only_available_to_trusted_local_receiver(tmp_path: Path) -> None:
    presented: list[str] = []
    receiver_calls: list[tuple[str, str, str]] = []
    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(device_pairing=True),
        adapters=CapabilityExtensionAdaptersV1(
            pairing_presenter=lambda _owner, _workspace, challenge: (
                presented.append(challenge.display_code) or True
            ),
            pairing_receiver_authority=lambda owner, workspace, pairing_id: (
                receiver_calls.append((owner, workspace, pairing_id)) or True
            ),
        ),
    )
    initiated = _execute(
        controller,
        {
            "action": "initiate_pairing",
            "device_id": "device.phone",
            "issuer": "onyx.phone",
        },
    )
    pairing_id = initiated["pairing"]["pairing_id"]
    assert presented and presented[0] not in repr(initiated)
    claimed = controller.claim_pairing_from_trusted_receiver(
        pairing_id=pairing_id,
        display_code=presented[0],
    )
    assert claimed.status == "claimed"
    assert receiver_calls == [("owner-primary", "workspace-personal", pairing_id)]

    with pytest.raises(ValueError, match="unknown"):
        _execute(
            controller,
            {
                "action": "claim_pairing",
                "pairing_id": pairing_id,
                "display_code": presented[0],
            },
        )


def test_pairing_without_trusted_local_presenter_fails_before_challenge(tmp_path: Path) -> None:
    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(device_pairing=True),
    )
    arguments = {
        "action": "initiate_pairing",
        "device_id": "device.phone",
        "issuer": "onyx.phone",
    }
    with pytest.raises(PermissionError, match="presenter"):
        _execute(controller, arguments)
    path = tmp_path / "capability-extensions-v1" / "device-pairing.sqlite3"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pairing_sessions").fetchone()[0] == 0


def test_direct_callers_cannot_forge_or_bypass_central_authority(tmp_path: Path) -> None:
    broker_calls: list[tuple[str, dict[str, object]]] = []
    governance_calls: list[dict[str, str]] = []

    class Governance:
        @staticmethod
        def assert_dispatch_allowed(**kwargs: str) -> None:
            governance_calls.append(dict(kwargs))

    def authorizer(tool: str, arguments: dict[str, object]):
        broker_calls.append((tool, dict(arguments)))
        return True, "real-broker-proof"

    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(device_pairing=True),
        adapters=CapabilityExtensionAdaptersV1(
            pairing_presenter=lambda *_args: True
        ),
        authorizer=authorizer,
        governance=Governance(),
    )
    assert not hasattr(controller, "_issue_authorization")
    assert not hasattr(controller, "_dispatch_exact")
    assert not hasattr(controller, "_dispatch_current")
    with pytest.raises(CapabilityExtensionsControllerDenied, match="immutable"):
        controller._dispatch_current = lambda *_args: {"status": "forged"}
    with pytest.raises(AttributeError):
        object.__setattr__(
            controller,
            "_dispatch_current",
            lambda *_args: {"status": "forged"},
        )
    controller.status()
    extension = controller._extensions
    assert type(extension) is CapabilityExtensionsSessionV1
    assert not hasattr(extension, "_issue_authorization")
    with pytest.raises(CapabilityExtensionsControllerDenied, match="immutable"):
        controller._extensions = SimpleNamespace(
            closed=False,
            execute=lambda _arguments: {"status": "forged"},
        )
    with pytest.raises(AttributeError):
        object.__setattr__(
            controller,
            "_phase6_session",
            SimpleNamespace(closed=False),
        )
    with pytest.raises(CapabilityExtensionsDenied, match="direct session dispatch"):
        extension.execute({"action": "status"})

    result = _execute(controller, {"action": "status"})
    assert result["status"] == "ready"
    assert broker_calls == [("onyx_capability_extensions", {"action": "status"})]
    assert governance_calls == [
        {
            "invocation_id": "fc-capability-test",
            "tool_name": "onyx_capability_extensions",
            "authorization_proof": "real-broker-proof",
        }
    ]

    denied = _controller(
        tmp_path / "denied",
        gates=CapabilityExtensionGatesV1(),
        authorizer=lambda *_args: (False, "denied by real broker"),
    )
    with pytest.raises(CapabilityExtensionsControllerDenied, match="denied by real broker"):
        _execute(denied, {"action": "status"})

    empty = _controller(
        tmp_path / "empty",
        gates=CapabilityExtensionGatesV1(),
        authorizer=lambda *_args: (True, ""),
    )
    with pytest.raises(CapabilityExtensionsControllerDenied, match="no authorization proof"):
        _execute(empty, {"action": "status"})


def test_direct_constructed_session_cannot_forge_controller_ownership(
    tmp_path: Path,
) -> None:
    with pytest.raises(CapabilityExtensionsDenied, match="controller factory"):
        CapabilityExtensionsSessionV1(
            owner_profile_id="owner-primary",
            workspace_id="workspace-personal",
            state_root=tmp_path / "direct-session",
            gates=CapabilityExtensionGatesV1(),
            adapters=CapabilityExtensionAdaptersV1(),
        )


def test_registration_and_authorization_helpers_are_not_importable() -> None:
    for name in (
        "_AuthorizedDispatchV1",
        "_register_controller_session_v1",
        "_unregister_controller_session_v1",
        "_controller_binding_v1",
        "_enter_controller_dispatch_v1",
        "_active_controller_dispatch_v1",
        "_CONTROLLER_SESSIONS",
    ):
        assert not hasattr(capability_live, name)


def test_stale_extension_denies_after_phase6_rotation(tmp_path: Path) -> None:
    hosts: list[object] = []
    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(),
        host_capture=hosts,
    )
    assert controller.status()["status"] == "ready"
    stale = controller._extensions
    assert type(stale) is CapabilityExtensionsSessionV1
    setattr(hosts[0], SESSION_ATTRIBUTE, _session(tmp_path / "rotated"))

    with pytest.raises(CapabilityExtensionsDenied, match="stale"):
        stale.execute({"action": "status"})

    assert _execute(controller, {"action": "status"})["status"] == "ready"
    assert stale.closed is True
    assert controller._extensions is not stale


def test_phase6_rotation_during_central_authorization_fails_closed(
    tmp_path: Path,
) -> None:
    hosts: list[object] = []

    def rotating_authorizer(_tool: str, _arguments: dict[str, object]):
        setattr(hosts[0], SESSION_ATTRIBUTE, _session(tmp_path / "during-authorize"))
        return True, "broker-proof"

    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(),
        authorizer=rotating_authorizer,
        host_capture=hosts,
    )
    controller.status()
    stale = controller._extensions
    assert type(stale) is CapabilityExtensionsSessionV1

    with pytest.raises(CapabilityExtensionsControllerDenied, match="rotated"):
        _execute(controller, {"action": "status"})
    with pytest.raises(CapabilityExtensionsDenied, match="stale"):
        stale.execute({"action": "status"})


class _Transport:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, account, message):
        self.calls += 1
        return ProviderMessageReceiptV1(
            "discord",
            "987654321098765432",
            message.channel_id,
            message.nonce,
            1001.0,
        )


class _AccessibilityBackend:
    platform = "Linux"

    def __init__(self) -> None:
        self.calls = 0

    def perform(self, request):
        self.calls += 1
        return NativeAccessibilityReceiptV1(
            request.request_id,
            request.digest,
            request.target.application_id,
            request.target.role,
            request.target.accessible_name,
            request.action,
            True,
            1001.0,
        )


def _account(owner: str, workspace: str, _account_id: str) -> DiscordAccountV1:
    return DiscordAccountV1(
        "discord.cyryx",
        owner,
        workspace,
        SecretReference("onyx.messaging", "discord.cyryx", "Discord bot"),
        (CHANNEL,),
    )


def test_missing_explicit_adapter_authority_denies_external_effects(tmp_path: Path) -> None:
    transport = _Transport()
    backend = _AccessibilityBackend()
    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(
            official_messaging=True,
            portable_accessibility=True,
        ),
        adapters=CapabilityExtensionAdaptersV1(
            messaging_account_resolver=_account,
            messaging_transport=transport,
            accessibility_backend=backend,
            platform="Linux",
        ),
    )
    message = {
        "action": "send_official_message",
        "account_id": "discord.cyryx",
        "channel_id": CHANNEL,
        "content": "No implicit authority.",
    }
    result = {
        "action": "perform_accessibility_action",
        "request_id": "request.accessibility.001",
        "application_id": "org.cyryx.Editor",
        "role": "button",
        "accessible_name": "Publish",
        "accessibility_action": "invoke",
    }
    with pytest.raises(PermissionError):
        _execute(controller, message)
    with pytest.raises(PermissionError):
        _execute(controller, result)
    assert transport.calls == 0
    assert backend.calls == 0


def test_explicit_authority_and_exact_adapters_allow_one_receipted_effect(tmp_path: Path) -> None:
    transport = _Transport()
    backend = _AccessibilityBackend()
    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(
            official_messaging=True,
            portable_accessibility=True,
        ),
        adapters=CapabilityExtensionAdaptersV1(
            messaging_account_resolver=_account,
            messaging_transport=transport,
            accessibility_backend=backend,
            authority=lambda *_args: True,
            platform="Linux",
        ),
    )
    message = {
        "action": "send_official_message",
        "account_id": "discord.cyryx",
        "channel_id": CHANNEL,
        "content": "One governed message.",
    }
    sent = _execute(controller, message)
    assert sent["message"]["status"] == "accepted"
    assert sent["external_dispatch"] is True
    assert transport.calls == 1

    action = {
        "action": "perform_accessibility_action",
        "request_id": "request.accessibility.002",
        "application_id": "org.cyryx.Editor",
        "role": "button",
        "accessible_name": "Publish",
        "accessibility_action": "invoke",
    }
    performed = _execute(controller, action)
    assert performed["accessibility_receipt"]["postcondition_verified"] is True
    assert performed["external_dispatch"] is True
    assert backend.calls == 1


def test_provider_failure_is_attempted_unknown_and_never_retried(tmp_path: Path) -> None:
    class FailingTransport(_Transport):
        def send(self, account, message):
            self.calls += 1
            raise RuntimeError("provider outcome unknown")

    transport = FailingTransport()
    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(official_messaging=True),
        adapters=CapabilityExtensionAdaptersV1(
            messaging_account_resolver=_account,
            messaging_transport=transport,
            authority=lambda *_args: True,
        ),
    )
    message = {
        "action": "send_official_message",
        "account_id": "discord.cyryx",
        "channel_id": CHANNEL,
        "content": "Do not retry this message.",
    }
    with pytest.raises(CapabilityExternalOutcomeUnknown, match="reconciliation"):
        _execute(controller, message)
    assert transport.calls == 1


def test_content_reserve_needs_explicit_authority_and_publish_is_not_exposed(tmp_path: Path) -> None:
    controller = _controller(
        tmp_path,
        gates=CapabilityExtensionGatesV1(content_lifecycle=True),
    )
    schedule = {
        "action": "schedule_content",
        "provider": "discord",
        "account_id": "discord.cyryx",
        "destination_id": "channel.primary",
        "content": "Draft",
        "scheduled_for": 2_000_000_000.0,
    }
    content_id = _execute(controller, schedule)[
        "content"
    ]["content_id"]
    reserve = {"action": "reserve_content", "content_id": content_id}
    with pytest.raises(PermissionError):
        _execute(controller, reserve)
    for unavailable in ("begin_publish", "record_receipt", "mark_uncertain"):
        arguments = {"action": unavailable, "content_id": content_id}
        with pytest.raises(ValueError, match="unknown"):
            _execute(controller, arguments)


def test_session_rotation_and_close_are_zero_worker_rollback(tmp_path: Path) -> None:
    host = SimpleNamespace()
    setattr(host, SESSION_ATTRIBUTE, _session(tmp_path))
    controller = CapabilityExtensionsControllerV1(
        host,
        gates=CapabilityExtensionGatesV1(site_recipes=True),
        adapters=CapabilityExtensionAdaptersV1(),
        central_authorizer=lambda _tool, _arguments: (True, "broker-proof"),
        audit_trace_setter=lambda _trace_id: object(),
        audit_trace_resetter=lambda _token: None,
    )
    controller.status()
    first = controller._extensions
    assert first is not None
    setattr(host, SESSION_ATTRIBUTE, None)
    assert controller.status()["status"] == "waiting_for_live_session"
    assert first.closed is True
    controller.close()
    assert controller.closed is True
    assert controller.background_workers == 0
