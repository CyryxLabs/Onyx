"""Session-scoped composition for the clean-room capability extensions.

This layer owns no model loop, mission executor, permission broker or provider
worker.  It projects five bounded V1 capabilities through one authenticated
Phase 6 identity.  Every feature is independently default-off; provider and
native effects additionally require an injected exact adapter.

Trust boundary: model/tool inputs are untrusted.  Python code already installed
and executing inside the Onyx process is trusted computing base (TCB); pure
Python object hiding is not claimed as cryptographic isolation from that code.
Moving capability effects into an OS-isolated process is separate future
hardening and is not claimed by this module.
"""

from __future__ import annotations

import os
import platform as host_platform
import hashlib
import json
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Mapping

from core.content_lifecycle_projection_v1 import ContentLifecycleProjectionV1
from core.device_pairing_v1 import DevicePairingStoreV1, PairingChallengeV1
from core.official_messaging_v1 import (
    DiscordAccountV1,
    OfficialMessagingOutboxV1,
)
from core.portable_accessibility_actions_v1 import (
    AccessibilityActionV1,
    AccessibilityTargetV1,
    NativeAccessibilityBackendV1,
    PortableAccessibilitySessionV1,
)
from core.site_recipe_catalog_v1 import SiteRecipeCatalogV1


PAIRING_FLAG: Final = "ONYX_DEVICE_PAIRING_V1"
MESSAGING_FLAG: Final = "ONYX_OFFICIAL_MESSAGING_V1"
SITE_RECIPES_FLAG: Final = "ONYX_SITE_RECIPES_V1"
ACCESSIBILITY_FLAG: Final = "ONYX_PORTABLE_ACCESSIBILITY_ACTIONS_V1"
CONTENT_FLAG: Final = "ONYX_CONTENT_LIFECYCLE_PROJECTION_V1"
FEATURE_FLAGS: Final = (
    PAIRING_FLAG,
    MESSAGING_FLAG,
    SITE_RECIPES_FLAG,
    ACCESSIBILITY_FLAG,
    CONTENT_FLAG,
)


class CapabilityExtensionsError(RuntimeError):
    pass


class CapabilityExtensionsDenied(PermissionError):
    pass


class CapabilityExtensionsContractError(ValueError):
    pass


class CapabilityExternalOutcomeUnknown(CapabilityExtensionsError):
    """An injected adapter may have performed an effect; never retry implicitly."""


def _arguments_digest(arguments: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(
            dict(arguments), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CapabilityExtensionsContractError(
            "capability arguments are not canonical JSON"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _build_controller_session_factory_v1() -> object:
    lock = threading.RLock()
    registry: weakref.WeakKeyDictionary[object, object] = weakref.WeakKeyDictionary()

    class Authorization:
        __slots__ = (
            "action",
            "arguments_sha256",
            "proof",
            "consumed",
            "active",
            "channel",
            "phase6_session",
            "extension",
        )

        def __init__(
            self,
            arguments: dict[str, object],
            proof: str,
            channel: object,
            phase6_session: object,
            extension: object,
        ) -> None:
            self.action = str(arguments.get("action", "")).strip()
            self.arguments_sha256 = _arguments_digest(arguments)
            self.proof = proof
            self.consumed = False
            self.active = False
            self.channel = channel
            self.phase6_session = phase6_session
            self.extension = extension

        def enter(self, arguments: Mapping[str, object]) -> None:
            if (
                self.consumed
                or self.active
                or str(arguments.get("action", "")).strip() != self.action
                or _arguments_digest(arguments) != self.arguments_sha256
            ):
                raise CapabilityExtensionsDenied(
                    "authorized dispatch binding diverged"
                )
            self.consumed = True
            self.active = True

    class Binding:
        __slots__ = ("channel", "phase6_session", "phase6_type")

        def __init__(self, channel: object, phase6_session: object) -> None:
            self.channel = channel
            self.phase6_session = phase6_session
            self.phase6_type = type(phase6_session)

    def binding_for(session: object) -> object:
        if type(session) is not CapabilityExtensionsSessionV1 or session.closed:
            raise CapabilityExtensionsDenied("controller-owned session is required")
        with lock:
            binding = registry.get(session)
        if type(binding) is not Binding:
            raise CapabilityExtensionsDenied("direct session dispatch is forbidden")
        channel = binding.channel
        try:
            current = channel.current_phase6()
        except Exception as exc:
            raise CapabilityExtensionsDenied(
                "current Phase 6 session is unavailable"
            ) from exc
        if (
            current is not binding.phase6_session
            or type(current) is not binding.phase6_type
            or getattr(current, "closed", True) is not False
        ):
            raise CapabilityExtensionsDenied("controller session is stale")
        return binding

    class Channel:
        __slots__ = ("current_phase6", "authorization_state")

        def __init__(self, current_phase6: Callable[[], object | None]) -> None:
            if not callable(current_phase6):
                raise CapabilityExtensionsDenied("current Phase 6 resolver is invalid")
            self.current_phase6 = current_phase6
            self.authorization_state = threading.local()

        def create(
            self,
            *,
            phase6_session: object,
            owner_profile_id: str,
            workspace_id: str,
            state_root: Path,
            gates: CapabilityExtensionGatesV1,
            adapters: CapabilityExtensionAdaptersV1,
        ) -> CapabilityExtensionsSessionV1:
            if (
                self.current_phase6() is not phase6_session
                or getattr(phase6_session, "closed", True) is not False
                or type(owner_profile_id) is not str
                or type(workspace_id) is not str
                or type(gates) is not CapabilityExtensionGatesV1
                or type(adapters) is not CapabilityExtensionAdaptersV1
            ):
                raise CapabilityExtensionsDenied("controller session creation is invalid")
            root = Path(state_root)
            if not root.is_absolute() or root.name in {"", ".", ".."}:
                raise CapabilityExtensionsContractError(
                    "an absolute state root is required"
                )
            session = object.__new__(CapabilityExtensionsSessionV1)
            session.owner_profile_id = owner_profile_id
            session.workspace_id = workspace_id
            session.state_root = root
            session.gates = gates
            session.adapters = adapters
            session.background_workers = 0
            session.polling_interval = None
            session.closed = False
            session.pairing = (
                DevicePairingStoreV1(root / "device-pairing.sqlite3", enabled=True)
                if gates.device_pairing
                else None
            )
            session.messaging = (
                OfficialMessagingOutboxV1(
                    root / "official-messaging.sqlite3", enabled=True
                )
                if gates.official_messaging
                else None
            )
            session.site_recipes = (
                SiteRecipeCatalogV1(enabled=True) if gates.site_recipes else None
            )
            session.content = (
                ContentLifecycleProjectionV1(
                    root / "content-lifecycle.sqlite3", enabled=True
                )
                if gates.content_lifecycle
                else None
            )
            session.accessibility = None
            backend = adapters.accessibility_backend
            if gates.portable_accessibility and backend is not None:
                session.accessibility = PortableAccessibilitySessionV1(
                    platform=adapters.effective_platform,
                    enabled=True,
                    authority=lambda request: session._authority(
                        request.owner_profile_id,
                        request.workspace_id,
                        "portable_accessibility.perform",
                        request.target.application_id,
                        request.action,
                    ),
                    backend=backend,
                )
            with lock:
                registry[session] = Binding(self, phase6_session)
            return session

        def assert_current(self, session: object, phase6_session: object) -> None:
            binding = binding_for(session)
            if binding.channel is not self or binding.phase6_session is not phase6_session:
                raise CapabilityExtensionsDenied(
                    "controller session ownership diverged"
                )

        def execute(
            self,
            session: object,
            phase6_session: object,
            arguments: dict[str, object],
            proof: str,
        ) -> dict[str, object]:
            self.assert_current(session, phase6_session)
            if type(arguments) is not dict or type(proof) is not str or not proof:
                raise CapabilityExtensionsDenied("central broker issued no exact authority")
            if getattr(self.authorization_state, "current", None) is not None:
                raise CapabilityExtensionsDenied("nested capability dispatch is forbidden")
            authorization = Authorization(
                arguments, proof, self, phase6_session, session
            )
            self.authorization_state.current = authorization
            try:
                return session.execute(arguments)
            finally:
                self.authorization_state.__dict__.pop("current", None)

        def close(self, session: object) -> None:
            with lock:
                binding = registry.get(session)
                if binding is None:
                    return
                if type(binding) is not Binding or binding.channel is not self:
                    raise CapabilityExtensionsDenied(
                        "controller session ownership diverged"
                    )
                registry.pop(session, None)
            session.close()

    class Factory:
        __slots__ = ()

        @staticmethod
        def controller_channel(
            current_phase6: Callable[[], object | None],
        ) -> object:
            return Channel(current_phase6)

        @staticmethod
        def enter(
            session: object,
            arguments: Mapping[str, object],
        ) -> object:
            binding = binding_for(session)
            channel = binding.channel
            authorization = getattr(channel.authorization_state, "current", None)
            if (
                type(authorization) is not Authorization
                or authorization.channel is not channel
                or authorization.phase6_session is not binding.phase6_session
                or authorization.extension is not session
            ):
                raise CapabilityExtensionsDenied("direct session dispatch is forbidden")
            authorization.enter(arguments)
            return authorization

        @staticmethod
        def active(session: object) -> object | None:
            try:
                binding = binding_for(session)
                channel = binding.channel
                authorization = getattr(
                    channel.authorization_state, "current", None
                )
            except CapabilityExtensionsDenied:
                return None
            if (
                type(authorization) is not Authorization
                or authorization.channel is not channel
                or authorization.phase6_session is not binding.phase6_session
                or authorization.extension is not session
                or not authorization.active
                or not authorization.consumed
            ):
                return None
            return authorization

        @staticmethod
        def ensure_current(session: object) -> None:
            binding_for(session)

    return Factory()


_CONTROLLER_SESSION_FACTORY_V1 = _build_controller_session_factory_v1()
del _build_controller_session_factory_v1


def _flag(source: Mapping[str, str], name: str) -> bool:
    value = source.get(name)
    if value is None:
        return False
    if value not in {"true", "false"}:
        raise CapabilityExtensionsContractError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True, slots=True)
class CapabilityExtensionGatesV1:
    device_pairing: bool = False
    official_messaging: bool = False
    site_recipes: bool = False
    portable_accessibility: bool = False
    content_lifecycle: bool = False

    def __post_init__(self) -> None:
        if any(
            type(value) is not bool
            for value in (
                self.device_pairing,
                self.official_messaging,
                self.site_recipes,
                self.portable_accessibility,
                self.content_lifecycle,
            )
        ):
            raise CapabilityExtensionsContractError("feature gates must be exact bools")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "CapabilityExtensionGatesV1":
        source = os.environ if environ is None else environ
        return cls(
            _flag(source, PAIRING_FLAG),
            _flag(source, MESSAGING_FLAG),
            _flag(source, SITE_RECIPES_FLAG),
            _flag(source, ACCESSIBILITY_FLAG),
            _flag(source, CONTENT_FLAG),
        )

    def environment(self) -> dict[str, str]:
        values = (
            self.device_pairing,
            self.official_messaging,
            self.site_recipes,
            self.portable_accessibility,
            self.content_lifecycle,
        )
        return {
            name: "true" if value else "false"
            for name, value in zip(FEATURE_FLAGS, values, strict=True)
        }

    def payload(self) -> dict[str, bool]:
        return {
            "device_pairing": self.device_pairing,
            "official_messaging": self.official_messaging,
            "site_recipes": self.site_recipes,
            "portable_accessibility": self.portable_accessibility,
            "content_lifecycle": self.content_lifecycle,
        }


@dataclass(frozen=True, slots=True)
class CapabilityExtensionAdaptersV1:
    pairing_presenter: Callable[[str, str, PairingChallengeV1], bool] | None = None
    pairing_receiver_authority: Callable[[str, str, str], bool] | None = None
    messaging_account_resolver: Callable[[str, str, str], DiscordAccountV1] | None = None
    messaging_transport: object | None = None
    accessibility_backend: NativeAccessibilityBackendV1 | None = None
    authority: Callable[[str, str, str, str, str], bool] | None = None
    platform: str = ""

    def __post_init__(self) -> None:
        if self.pairing_presenter is not None and not callable(self.pairing_presenter):
            raise CapabilityExtensionsContractError("pairing presenter is invalid")
        if self.pairing_receiver_authority is not None and not callable(
            self.pairing_receiver_authority
        ):
            raise CapabilityExtensionsContractError("pairing receiver authority is invalid")
        if self.messaging_account_resolver is not None and not callable(
            self.messaging_account_resolver
        ):
            raise CapabilityExtensionsContractError("messaging resolver is invalid")
        if self.authority is not None and not callable(self.authority):
            raise CapabilityExtensionsContractError("extension authority is invalid")
        if type(self.platform) is not str:
            raise CapabilityExtensionsContractError("platform is invalid")

    @property
    def effective_platform(self) -> str:
        return self.platform or host_platform.system()


class CapabilityExtensionsSessionV1:
    """One zero-worker projection bound to one owner/workspace identity."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise CapabilityExtensionsDenied(
            "capability sessions can only be created by the controller factory"
        )

    def close(self) -> None:
        self.closed = True
        self.pairing = None
        self.messaging = None
        self.site_recipes = None
        self.accessibility = None
        self.content = None

    def _require_open(self) -> None:
        if self.closed:
            raise CapabilityExtensionsDenied("capability extension session is closed")

    def _authority(
        self, owner: str, workspace: str, action: str, target: str, destination: str
    ) -> bool:
        authorization = _CONTROLLER_SESSION_FACTORY_V1.active(self)
        if (
            authorization is None
            or owner != self.owner_profile_id
            or workspace != self.workspace_id
        ):
            return False
        callback = self.adapters.authority
        if callback is None:
            return False
        decision = callback(owner, workspace, action, target, destination)
        return type(decision) is bool and decision

    @staticmethod
    def _pairing_payload(value: object) -> dict[str, object]:
        names = (
            "pairing_id",
            "owner_profile_id",
            "workspace_id",
            "device_id",
            "issuer",
            "status",
            "attempts",
            "expires_at",
            "claimed_at",
            "code_exposed",
            "credential_issued",
            "transport_hint",
            "background_workers",
            "polling_interval",
        )
        payload = {name: getattr(value, name) for name in names if hasattr(value, name)}
        payload.setdefault("code_exposed", False)
        payload.setdefault("credential_issued", False)
        return payload

    @staticmethod
    def _content_payload(value: object) -> dict[str, object]:
        names = (
            "content_id",
            "owner_profile_id",
            "workspace_id",
            "provider",
            "account_id",
            "destination_id",
            "content_digest",
            "status",
            "scheduled_for",
            "reservation_id",
            "provider_item_id",
            "detail",
            "updated_at",
        )
        return {name: getattr(value, name) for name in names}

    def availability(self) -> dict[str, object]:
        return {
            "contract": "OnyxCapabilityExtensionsStatus.v1",
            "status": "ready",
            "features": self.gates.payload(),
            "messaging_adapter_ready": (
                self.adapters.messaging_account_resolver is not None
                and callable(getattr(self.adapters.messaging_transport, "send", None))
            ),
            "accessibility_adapter_ready": self.accessibility is not None,
            "background_workers": 0,
            "polling_interval": None,
            "external_dispatch": False,
        }

    def preflight_action(self, action: str) -> None:
        self._require_open()
        groups = {
            "pairing": {
                "initiate_pairing", "cancel_pairing", "pairing_status"
            },
            "messaging": {"send_official_message", "official_message_status"},
            "site": {"list_site_recipes", "plan_site_recipe"},
            "accessibility": {"perform_accessibility_action"},
            "content": {
                "schedule_content", "reserve_content", "cancel_content",
                "get_content", "list_content",
            },
        }
        if action == "status":
            return
        if action in groups["pairing"] and self.pairing is None:
            raise CapabilityExtensionsDenied("device pairing is disabled")
        if action == "initiate_pairing" and self.adapters.pairing_presenter is None:
            raise CapabilityExtensionsDenied("trusted local pairing presenter is unavailable")
        if action in groups["messaging"]:
            if self.messaging is None:
                raise CapabilityExtensionsDenied("official messaging is disabled")
            if action == "send_official_message" and (
                self.adapters.messaging_account_resolver is None
                or not callable(getattr(self.adapters.messaging_transport, "send", None))
            ):
                raise CapabilityExtensionsDenied("official messaging adapter is unavailable")
        if action in groups["site"] and self.site_recipes is None:
            raise CapabilityExtensionsDenied("site recipes are disabled")
        if action in groups["accessibility"] and self.accessibility is None:
            raise CapabilityExtensionsDenied("portable accessibility adapter is unavailable")
        if action in groups["content"] and self.content is None:
            raise CapabilityExtensionsDenied("content lifecycle is disabled")
        if not any(action in values for values in groups.values()):
            raise CapabilityExtensionsContractError("capability action is unknown")

    def execute(self, arguments: Mapping[str, object]) -> dict[str, object]:
        if type(arguments) is not dict:
            raise CapabilityExtensionsDenied("exact capability arguments are required")
        action = str(arguments.get("action", "")).strip()
        authorization = _CONTROLLER_SESSION_FACTORY_V1.enter(self, arguments)
        try:
            self.preflight_action(action)
            result: object
            external = False
            if action == "status":
                return self.availability()
            if action == "initiate_pairing":
                result = self.pairing.initiate(
                    owner_profile_id=self.owner_profile_id,
                    workspace_id=self.workspace_id,
                    device_id=arguments.get("device_id"),
                    issuer=arguments.get("issuer"),
                    ttl_seconds=arguments.get("ttl_seconds", 180.0),
                )
                presenter = self.adapters.pairing_presenter
                try:
                    presented = presenter(
                        self.owner_profile_id,
                        self.workspace_id,
                        result,
                    )
                except Exception:
                    self.pairing.cancel(result.pairing_id)
                    raise
                if presented is not True:
                    self.pairing.cancel(result.pairing_id)
                    raise CapabilityExtensionsDenied(
                        "trusted local pairing presenter rejected the challenge"
                    )
                payload = {"pairing": self._pairing_payload(result)}
            elif action == "cancel_pairing":
                result = self.pairing.cancel(arguments.get("pairing_id"))
                payload = {"pairing": self._pairing_payload(result)}
            elif action == "pairing_status":
                result = self.pairing.status(arguments.get("pairing_id"))
                payload = {"pairing": self._pairing_payload(result)}
            elif action == "send_official_message":
                resolver = self.adapters.messaging_account_resolver
                account = resolver(
                    self.owner_profile_id,
                    self.workspace_id,
                    arguments.get("account_id"),
                )
                if (
                    type(account) is not DiscordAccountV1
                    or account.owner_profile_id != self.owner_profile_id
                    or account.workspace_id != self.workspace_id
                ):
                    raise CapabilityExtensionsDenied("messaging account scope diverged")
                try:
                    result = self.messaging.send_discord(
                        account=account,
                        channel_id=arguments.get("channel_id"),
                        content=arguments.get("content"),
                        authority=self._authority,
                        transport=self.adapters.messaging_transport,
                    )
                except PermissionError:
                    raise
                except Exception as exc:
                    raise CapabilityExternalOutcomeUnknown(
                        "official messaging outcome requires reconciliation"
                    ) from exc
                external = True
                payload = {
                    "message": {
                        "operation_id": result.operation_id,
                        "status": result.status,
                        "content_digest": result.content_digest,
                        "provider_message_id": result.provider_message_id,
                        "detail": result.detail,
                    }
                }
            elif action == "official_message_status":
                result = self.messaging.dispatch(arguments.get("operation_id"))
                payload = {
                    "message": {
                        "operation_id": result.operation_id,
                        "status": result.status,
                        "content_digest": result.content_digest,
                        "provider_message_id": result.provider_message_id,
                        "detail": result.detail,
                    }
                }
            elif action == "list_site_recipes":
                payload = {"recipes": self.site_recipes.recipes()}
            elif action == "plan_site_recipe":
                result = self.site_recipes.plan(
                    recipe_id=arguments.get("recipe_id"),
                    project_slug=arguments.get("project_slug"),
                    title=arguments.get("title"),
                    summary=arguments.get("summary"),
                    primary_action=arguments.get("primary_action", "Start a mission"),
                )
                payload = {"site_plan": result.phase6_payload()}
            elif action == "perform_accessibility_action":
                request = AccessibilityActionV1(
                    request_id=arguments.get("request_id"),
                    owner_profile_id=self.owner_profile_id,
                    workspace_id=self.workspace_id,
                    platform=self.adapters.effective_platform,
                    target=AccessibilityTargetV1(
                        arguments.get("application_id"),
                        arguments.get("role"),
                        arguments.get("accessible_name"),
                    ),
                    action=arguments.get("accessibility_action"),
                    value=arguments.get("value"),
                )
                try:
                    result = self.accessibility.perform(request)
                except (PermissionError, ValueError):
                    raise
                except Exception as exc:
                    raise CapabilityExternalOutcomeUnknown(
                        "accessibility outcome requires reconciliation"
                    ) from exc
                external = True
                payload = {
                    "accessibility_receipt": {
                        "request_id": result.request_id,
                        "request_digest": result.request_digest,
                        "application_id": result.application_id,
                        "role": result.role,
                        "accessible_name": result.accessible_name,
                        "action": result.action,
                        "postcondition_verified": result.postcondition_verified,
                        "observed_at": result.observed_at,
                    }
                }
            elif action == "schedule_content":
                result = self.content.schedule(
                    owner_profile_id=self.owner_profile_id,
                    workspace_id=self.workspace_id,
                    provider=arguments.get("provider"),
                    account_id=arguments.get("account_id"),
                    destination_id=arguments.get("destination_id"),
                    content=arguments.get("content"),
                    scheduled_for=arguments.get("scheduled_for"),
                )
                payload = {"content": self._content_payload(result)}
            elif action == "reserve_content":
                result = self.content.reserve(
                    arguments.get("content_id"),
                    owner_profile_id=self.owner_profile_id,
                    workspace_id=self.workspace_id,
                    authority=self._authority,
                )
                payload = {"content": self._content_payload(result)}
            elif action == "cancel_content":
                result = self.content.cancel(
                    arguments.get("content_id"),
                    owner_profile_id=self.owner_profile_id,
                    workspace_id=self.workspace_id,
                )
                payload = {"content": self._content_payload(result)}
            elif action == "get_content":
                result = self.content.get(
                    arguments.get("content_id"),
                    owner_profile_id=self.owner_profile_id,
                    workspace_id=self.workspace_id,
                )
                payload = {"content": self._content_payload(result)}
            elif action == "list_content":
                items = self.content.list_items(
                    owner_profile_id=self.owner_profile_id,
                    workspace_id=self.workspace_id,
                    limit=arguments.get("limit", 50),
                )
                payload = {"content_items": tuple(self._content_payload(item) for item in items)}
            else:  # pragma: no cover - preflight owns the closed action set
                raise CapabilityExtensionsContractError("capability action is unknown")
            return {
                "contract": "OnyxCapabilityExtensionsCommand.v1",
                "status": "completed",
                "action": action,
                **payload,
                "external_dispatch": external,
            }
        finally:
            authorization.active = False

    def claim_pairing_from_trusted_receiver(
        self, *, pairing_id: str, display_code: str
    ) -> object:
        self._require_open()
        _CONTROLLER_SESSION_FACTORY_V1.ensure_current(self)
        if self.pairing is None:
            raise CapabilityExtensionsDenied("device pairing is disabled")
        authority = self.adapters.pairing_receiver_authority
        if authority is None:
            raise CapabilityExtensionsDenied("trusted pairing receiver is unavailable")
        decision = authority(self.owner_profile_id, self.workspace_id, pairing_id)
        if decision is not True:
            raise CapabilityExtensionsDenied("trusted pairing receiver denied the claim")
        return self.pairing.claim(pairing_id=pairing_id, display_code=display_code)


__all__ = [
    "ACCESSIBILITY_FLAG",
    "CONTENT_FLAG",
    "FEATURE_FLAGS",
    "MESSAGING_FLAG",
    "PAIRING_FLAG",
    "SITE_RECIPES_FLAG",
    "CapabilityExtensionAdaptersV1",
    "CapabilityExtensionGatesV1",
    "CapabilityExtensionsContractError",
    "CapabilityExtensionsDenied",
    "CapabilityExtensionsError",
    "CapabilityExternalOutcomeUnknown",
    "CapabilityExtensionsSessionV1",
]
