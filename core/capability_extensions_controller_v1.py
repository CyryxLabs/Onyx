"""Controller-only bridge from untrusted tool input to V25 capabilities.

Model/tool input is untrusted.  Installed Python already executing in this
process is part of the trusted computing base; OS-process isolation is future
hardening and is not claimed here.
"""

from __future__ import annotations

import copy
import threading
import weakref
from pathlib import Path
from typing import Mapping

from core.capability_extensions_live_v1 import (
    CapabilityExtensionAdaptersV1,
    CapabilityExtensionGatesV1,
    CapabilityExtensionsDenied,
    CapabilityExtensionsSessionV1,
    _CONTROLLER_SESSION_FACTORY_V1,
)
from core.phase6_live_wiring_v1 import (
    SESSION_ATTRIBUTE,
    LiveWiringIdentityV1,
    LiveWiringSessionV1,
)


HOST_CONTROLLER = "_capability_extensions_controller_v1"


class CapabilityExtensionsControllerError(RuntimeError):
    pass


class CapabilityExtensionsControllerDenied(PermissionError):
    pass


class CapabilityExtensionsControllerV1:
    """Zero-worker controller whose trusted state is owned by the class."""

    __slots__ = ("__weakref__",)
    __state_lock = threading.RLock()
    __states: weakref.WeakKeyDictionary[object, dict[str, object]] = (
        weakref.WeakKeyDictionary()
    )

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise CapabilityExtensionsControllerDenied(
            "controller instance state is immutable"
        )

    def __init__(
        self,
        host: object,
        *,
        gates: CapabilityExtensionGatesV1,
        adapters: CapabilityExtensionAdaptersV1,
        central_authorizer: object,
        audit_trace_setter: object,
        audit_trace_resetter: object,
    ) -> None:
        if (
            host is None
            or type(gates) is not CapabilityExtensionGatesV1
            or type(adapters) is not CapabilityExtensionAdaptersV1
            or not callable(central_authorizer)
            or not callable(audit_trace_setter)
            or not callable(audit_trace_resetter)
        ):
            raise CapabilityExtensionsControllerError(
                "exact controller bindings are required"
            )
        governance = getattr(host, "_governance_nucleus_v1", None)
        assertion = getattr(governance, "assert_dispatch_allowed", None)

        def current_phase6() -> object | None:
            return getattr(host, SESSION_ATTRIBUTE, None)

        state: dict[str, object] = {
            "gates": gates,
            "adapters": adapters,
            "central_authorizer": central_authorizer,
            "audit_trace_setter": audit_trace_setter,
            "audit_trace_resetter": audit_trace_resetter,
            "governance_assertion": assertion if callable(assertion) else None,
            "current_phase6": current_phase6,
            "channel": _CONTROLLER_SESSION_FACTORY_V1.controller_channel(
                current_phase6
            ),
            "phase6": None,
            "extension": None,
            "closed": False,
            "lock": threading.RLock(),
        }
        with self.__state_lock:
            if self in self.__states:
                raise CapabilityExtensionsControllerError(
                    "controller is already initialized"
                )
            self.__states[self] = state

    @classmethod
    def __state(cls, instance: CapabilityExtensionsControllerV1) -> dict[str, object]:
        with cls.__state_lock:
            state = cls.__states.get(instance)
        if type(state) is not dict:
            raise CapabilityExtensionsControllerDenied(
                "controller state is unavailable"
            )
        return state

    @staticmethod
    def __detach_state(state: dict[str, object]) -> None:
        extension = state["extension"]
        state["extension"] = None
        state["phase6"] = None
        if extension is None:
            return
        if type(extension) is not CapabilityExtensionsSessionV1:
            raise CapabilityExtensionsControllerDenied(
                "controller extension state diverged"
            )
        state["channel"].close(extension)

    @classmethod
    def __resolve_state(
        cls,
        state: dict[str, object],
    ) -> tuple[CapabilityExtensionsSessionV1, LiveWiringSessionV1] | None:
        if state["closed"] is True:
            raise CapabilityExtensionsControllerDenied(
                "capability controller is closed"
            )
        observed = state["current_phase6"]()
        phase6 = state["phase6"]
        extension = state["extension"]
        if observed is phase6 and extension is not None:
            if (
                type(observed) is not LiveWiringSessionV1
                or observed.closed
                or type(extension) is not CapabilityExtensionsSessionV1
                or extension.closed
            ):
                raise CapabilityExtensionsControllerDenied(
                    "live capability session authority diverged"
                )
            state["channel"].assert_current(extension, observed)
            return extension, observed
        cls.__detach_state(state)
        if observed is None:
            return None
        if type(observed) is not LiveWiringSessionV1 or observed.closed:
            raise CapabilityExtensionsControllerDenied(
                "live Phase 6 session authority diverged"
            )
        identity = observed.identity
        if type(identity) is not LiveWiringIdentityV1:
            raise CapabilityExtensionsControllerDenied(
                "live Phase 6 identity diverged"
            )
        state_root = Path(observed.state_path).parent / "capability-extensions-v1"
        created = state["channel"].create(
            phase6_session=observed,
            owner_profile_id=identity.profile_id,
            workspace_id=identity.workspace_id,
            state_root=state_root,
            gates=state["gates"],
            adapters=state["adapters"],
        )
        if type(created) is not CapabilityExtensionsSessionV1:
            raise CapabilityExtensionsControllerDenied(
                "controller factory returned an invalid session"
            )
        state["phase6"] = observed
        state["extension"] = created
        return created, observed

    def _execute_current(
        self,
        exact_arguments: dict[str, object],
        invocation_id: str,
        trace_id: str,
    ) -> dict[str, object]:
        state = self.__state(self)
        lock = state["lock"]
        with lock:
            resolved = self.__resolve_state(state)
            if resolved is None:
                raise CapabilityExtensionsControllerDenied(
                    "live Phase 6 session is unavailable"
                )
            extension, phase6 = resolved
            extension.preflight_action(
                str(exact_arguments.get("action", "")).strip()
            )
            state["channel"].assert_current(extension, phase6)
            trace_token = state["audit_trace_setter"](trace_id)
            try:
                decision = state["central_authorizer"](
                    "onyx_capability_extensions", exact_arguments
                )
            finally:
                state["audit_trace_resetter"](trace_token)
            if (
                type(decision) is not tuple
                or len(decision) != 2
                or type(decision[0]) is not bool
                or type(decision[1]) is not str
            ):
                raise CapabilityExtensionsControllerDenied(
                    "central broker returned an invalid decision"
                )
            approved, proof = decision
            if not approved:
                raise CapabilityExtensionsControllerDenied(
                    proof or "central broker denied"
                )
            if not proof:
                raise CapabilityExtensionsControllerDenied(
                    "central broker returned no authorization proof"
                )
            governance_assertion = state["governance_assertion"]
            if governance_assertion is not None:
                try:
                    governance_assertion(
                        invocation_id=invocation_id,
                        tool_name="onyx_capability_extensions",
                        authorization_proof=proof,
                    )
                except PermissionError as exc:
                    raise CapabilityExtensionsControllerDenied(
                        f"governance denied dispatch: {exc}"
                    ) from exc
            if state["current_phase6"]() is not phase6 or phase6.closed:
                raise CapabilityExtensionsControllerDenied(
                    "Phase 6 session rotated during authorization"
                )
            confirmed = self.__resolve_state(state)
            if (
                confirmed is None
                or confirmed[0] is not extension
                or confirmed[1] is not phase6
            ):
                raise CapabilityExtensionsControllerDenied(
                    "capability session rotated during authorization"
                )
            state["channel"].assert_current(extension, phase6)
            return state["channel"].execute(
                extension,
                phase6,
                exact_arguments,
                proof,
            )

    @property
    def gates(self) -> CapabilityExtensionGatesV1:
        return self.__state(self)["gates"]

    @property
    def adapters(self) -> CapabilityExtensionAdaptersV1:
        return self.__state(self)["adapters"]

    @property
    def closed(self) -> bool:
        return self.__state(self)["closed"] is True

    @property
    def _phase6_session(self) -> object | None:
        return self.__state(self)["phase6"]

    @property
    def _extensions(self) -> object | None:
        return self.__state(self)["extension"]

    @property
    def background_workers(self) -> int:
        return 0

    @property
    def polling_interval(self) -> None:
        return None

    def _detach(self) -> None:
        state = self.__state(self)
        with state["lock"]:
            self.__detach_state(state)

    def _bind_current(self) -> CapabilityExtensionsSessionV1 | None:
        state = self.__state(self)
        with state["lock"]:
            resolved = self.__resolve_state(state)
            return None if resolved is None else resolved[0]

    def status(self) -> dict[str, object]:
        state = self.__state(self)
        with state["lock"]:
            resolved = self.__resolve_state(state)
            if resolved is None:
                return {
                    "contract": "OnyxCapabilityExtensionsStatus.v1",
                    "status": "waiting_for_live_session",
                    "features": state["gates"].payload(),
                    "background_workers": 0,
                    "polling_interval": None,
                    "external_dispatch": False,
                }
            return resolved[0].availability()

    def preflight_action(self, action: str) -> None:
        state = self.__state(self)
        with state["lock"]:
            resolved = self.__resolve_state(state)
            if resolved is None:
                raise CapabilityExtensionsControllerDenied(
                    "live Phase 6 session is unavailable"
                )
            try:
                resolved[0].preflight_action(action)
            except CapabilityExtensionsDenied as exc:
                raise CapabilityExtensionsControllerDenied(str(exc)) from exc

    def execute(
        self,
        arguments: Mapping[str, object],
        *,
        invocation_id: str,
        trace_id: str,
    ) -> dict[str, object]:
        if type(arguments) is not dict:
            raise CapabilityExtensionsControllerDenied(
                "exact capability arguments are required"
            )
        if (
            type(invocation_id) is not str
            or not invocation_id
            or len(invocation_id) > 192
            or type(trace_id) is not str
            or len(trace_id) != 16
        ):
            raise CapabilityExtensionsControllerDenied(
                "trusted host invocation is invalid"
            )
        return CapabilityExtensionsControllerV1._execute_current(
            self,
            copy.deepcopy(dict(arguments)),
            invocation_id,
            trace_id,
        )

    def claim_pairing_from_trusted_receiver(
        self, *, pairing_id: str, display_code: str
    ) -> object:
        state = self.__state(self)
        with state["lock"]:
            resolved = self.__resolve_state(state)
            if resolved is None:
                raise CapabilityExtensionsControllerDenied(
                    "live Phase 6 session is unavailable"
                )
            return resolved[0].claim_pairing_from_trusted_receiver(
                pairing_id=pairing_id,
                display_code=display_code,
            )

    def close(self) -> None:
        state = self.__state(self)
        with state["lock"]:
            if state["closed"] is True:
                return
            self.__detach_state(state)
            state["closed"] = True


__all__ = [
    "HOST_CONTROLLER",
    "CapabilityExtensionsControllerDenied",
    "CapabilityExtensionsControllerError",
    "CapabilityExtensionsControllerV1",
]
