"""Default-off activation coordinator for accepted Onyx components.

This transition layer deliberately lives outside the frozen component bytes.  It
coordinates Owner Profile V8, Phase 5 Integration V3 and HUD V5 without making
network/provider calls.  The legacy launcher remains the complete execution path
unless the exact master flag and every required child flag are enabled.
"""

from __future__ import annotations

import copy
import os
import secrets
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Callable, Protocol


LIVE_MASTER_FLAG = "ONYX_LIVE_ACTIVATION_V1"
LIVE_ROLLBACK_FLAG = "ONYX_LIVE_ROLLBACK_V1"
OWNER_PROFILE_FLAG = "ONYX_OWNER_PROFILE_V8_LIVE"
HUD_FLAG = "ONYX_HUD_V5_LIVE"

PHASE5_FLAGS = (
    "ONYX_PHASE5_INTEGRATION_V3",
    "ONYX_PHASE5_RUNTIME_V3",
    "ONYX_PHASE5_GRANT_SHADOW_V3",
    "ONYX_PHASE5_APPROVAL_INBOX_V3",
    "ONYX_PHASE5_LOW_RISK_V3",
    "ONYX_PHASE5_NEXUS_PROJECTION_V3",
    "ONYX_PHASE5_LOCAL_CATALOG_READ_V3",
    "ONYX_PHASE5_DASHBOARD_PROJECTION_V3",
)
REQUIRED_CHILD_FLAGS = (OWNER_PROFILE_FLAG, HUD_FLAG, *PHASE5_FLAGS)

OWNER_PROFILE_ID = "cyryx-onyx-owner-primary-v8"
OWNER_RUNTIME_INSTANCE = "onyx-live-owner-v8"
OWNER_KEY_SERVICE = "CyryxLabs.Onyx.OwnerProfileV8"
OWNER_KEY_ACCOUNT = "journal-key-primary"
OWNER_JOURNAL_RELATIVE = Path("identity") / "owner-profile-v8.journal.json"

_TRUE = frozenset({"1", "true"})
_OWNER_TOOL_NAMES = frozenset(
    {"set_owner_name", "correct_owner_name", "forget_owner_name"}
)


class ActivationError(RuntimeError):
    """A safe transition failure with no credential or owner data."""


class ActivationState(str, Enum):
    DISABLED = "disabled"
    READY = "ready"
    DEGRADED = "degraded"
    TERMINATED = "terminated"


def _enabled(value: object) -> bool:
    return type(value) is str and value.strip().casefold() in _TRUE


@dataclass(frozen=True, slots=True)
class ActivationFlagsV1:
    master: bool = False
    rollback: bool = False
    owner_profile: bool = False
    hud_v5: bool = False
    phase5: tuple[bool, ...] = (False,) * len(PHASE5_FLAGS)

    def __post_init__(self) -> None:
        if any(
            type(item) is not bool
            for item in (self.master, self.rollback, self.owner_profile, self.hud_v5)
        ):
            raise ActivationError("activation flags must be exact booleans")
        if type(self.phase5) is not tuple or len(self.phase5) != len(PHASE5_FLAGS):
            raise ActivationError("Phase 5 activation flag set is incomplete")
        if any(type(item) is not bool for item in self.phase5):
            raise ActivationError("Phase 5 activation flags must be exact booleans")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV1":
        source = os.environ if environ is None else environ
        rollback = _enabled(source.get(LIVE_ROLLBACK_FLAG, ""))
        master = _enabled(source.get(LIVE_MASTER_FLAG, "")) and not rollback
        if not master:
            return cls(rollback=rollback)
        flags = cls(
            master=True,
            owner_profile=_enabled(source.get(OWNER_PROFILE_FLAG, "")),
            hud_v5=_enabled(source.get(HUD_FLAG, "")),
            phase5=tuple(_enabled(source.get(name, "")) for name in PHASE5_FLAGS),
        )
        if not flags.all_children:
            raise ActivationError(
                "live activation requires every accepted child flag explicitly"
            )
        return flags

    @property
    def all_children(self) -> bool:
        return self.owner_profile and self.hud_v5 and all(self.phase5)

    @property
    def active(self) -> bool:
        return self.master and not self.rollback and self.all_children


def exact_activation_environment() -> dict[str, str]:
    """Return the complete opt-in environment; never mutates ``os.environ``."""

    return {
        LIVE_MASTER_FLAG: "1",
        LIVE_ROLLBACK_FLAG: "0",
        OWNER_PROFILE_FLAG: "1",
        HUD_FLAG: "1",
        **{name: "1" for name in PHASE5_FLAGS},
        "ONYX_PHASE5_PRINCIPAL_ID": "onyx-owner",
        "ONYX_PHASE5_WORKSPACE_ID": "onyx-local-workspace",
        "ONYX_PHASE5_ACCOUNT_ID": "cyryx-local-account",
        "ONYX_PHASE5_PROFILE_ID": "onyx-owner-profile",
    }


def exact_rollback_environment() -> dict[str, str]:
    """Return the one-switch rollback overlay."""

    return {LIVE_ROLLBACK_FLAG: "1"}


class _ByteVault(Protocol):
    def get_bytes(self) -> bytes | None: ...
    def set_bytes(self, secret: bytes | bytearray) -> None: ...


def owner_journal_path() -> Path:
    from core.paths import private_control_plane_runtime_dir

    return private_control_plane_runtime_dir() / OWNER_JOURNAL_RELATIVE


def _owner_key_vault() -> _ByteVault:
    from core.native_vault import NativeSecretVault, SecretReference

    return NativeSecretVault(
        SecretReference(
            OWNER_KEY_SERVICE,
            OWNER_KEY_ACCOUNT,
            "Onyx Owner Profile V8 journal authentication key",
        )
    )


def _provision_key(vault: _ByteVault, *, existing_state: bool) -> bytes:
    try:
        current = vault.get_bytes()
    except Exception as exc:
        raise ActivationError("owner credential vault is unavailable") from exc
    if current is not None:
        if type(current) is not bytes or len(current) != 32:
            raise ActivationError("owner credential has an invalid representation")
        return current
    if existing_state:
        raise ActivationError("owner credential is missing for existing durable state")
    generated = secrets.token_bytes(32)
    if type(generated) is not bytes or len(generated) != 32:
        raise ActivationError("secure owner key generation failed")
    try:
        vault.set_bytes(generated)
        observed = vault.get_bytes()
    except Exception as exc:
        raise ActivationError("owner credential provisioning failed") from exc
    if type(observed) is not bytes or not secrets.compare_digest(observed, generated):
        raise ActivationError("owner credential readback failed")
    return generated


def provision_owner_authority(
    *,
    journal_path: Path | None = None,
    vault: _ByteVault | None = None,
    memory: object | None = None,
    config_path: Path | None = None,
    chain_head_store: object | None = None,
    transaction_lease: object | None = None,
) -> object:
    """Open or first-install the accepted V8 authority without silent recovery.

    Existing journal/chain state is never rewritten when its vault key is absent.
    Bootstrap is permitted only when journal and chain head are both absent; a
    valid key-only state may safely resume an interrupted first provisioning.
    """

    from core import owner_profile_v8 as owner_v8
    from core.paths import config_file
    from memory.memory_manager import get_store

    journal = (journal_path or owner_journal_path()).resolve(strict=False)
    memory_store = get_store() if memory is None else memory
    config = config_file() if config_path is None else Path(config_path)
    lease = transaction_lease or owner_v8.WindowsHostTransactionLease()
    head_store = chain_head_store or owner_v8.WindowsCredentialChainHeadStore(
        host_lease=lease
    )
    key_vault = vault or _owner_key_vault()

    journal_exists = journal.exists()
    try:
        head = head_store.load(OWNER_PROFILE_ID)
    except Exception as exc:
        raise ActivationError("owner chain-head vault is unavailable") from exc
    key = _provision_key(key_vault, existing_state=journal_exists or head is not None)

    if journal_exists != (head is not None):
        raise ActivationError("owner durable stores are incomplete")
    if not journal_exists:
        journal.parent.mkdir(parents=True, exist_ok=True)
        return owner_v8.OwnerProfileAuthority.bootstrap(
            config_path=config,
            memory=memory_store,
            journal_path=journal,
            journal_key=key,
            owner_profile_id=OWNER_PROFILE_ID,
            runtime_instance=OWNER_RUNTIME_INSTANCE,
            chain_head_store=head_store,
            transaction_lease=lease,
        )
    return owner_v8.OwnerProfileAuthority(
        config_path=config,
        memory=memory_store,
        journal_path=journal,
        journal_key=key,
        owner_profile_id=OWNER_PROFILE_ID,
        runtime_instance=OWNER_RUNTIME_INSTANCE,
        chain_head_store=head_store,
        transaction_lease=lease,
    )


OWNER_TOOL_DECLARATIONS = (
    {
        "name": "set_owner_name",
        "description": (
            "Persist the owner's real chosen display name after Onyx asks the "
            "first-contact question and the owner answers it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}},
            "required": ["name"],
        },
    },
    {
        "name": "correct_owner_name",
        "description": "Correct the owner's persisted display name on explicit request.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}},
            "required": ["name"],
        },
    },
    {
        "name": "forget_owner_name",
        "description": "Forget the owner's display name on explicit request.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
)


class OnyxLiveActivationV1:
    """Sticky coordinator installed by the opt-in launcher exactly once."""

    def __init__(
        self,
        flags: ActivationFlagsV1,
        *,
        authority_factory: Callable[[], object] = provision_owner_authority,
    ) -> None:
        if type(flags) is not ActivationFlagsV1 or not flags.active:
            raise ActivationError("an exact active transition flag set is required")
        self.flags = flags
        self._authority_factory = authority_factory
        self._authority: object | None = None
        self._state = ActivationState.DISABLED
        self._failure_type: str | None = None
        self._contact_question: str | None = None
        self._phase5_bridge: object | None = None
        self._lock = threading.RLock()

    @property
    def state(self) -> ActivationState:
        return self._state

    @property
    def failure_type(self) -> str | None:
        return self._failure_type

    def start(self) -> ActivationState:
        with self._lock:
            if self._state in {ActivationState.READY, ActivationState.DEGRADED}:
                return self._state
            if self._state is ActivationState.TERMINATED:
                raise ActivationError("activation coordinator is terminated")
            try:
                authority = self._authority_factory()
                snapshot = authority.reconcile()
                if not snapshot.reconciled:
                    raise ActivationError("owner profile reconciliation degraded")
                self._contact_question = authority.begin_contact()
            except Exception as exc:
                self._authority = None
                self._failure_type = type(exc).__name__
                self._state = ActivationState.DEGRADED
                return self._state
            self._authority = authority
            self._failure_type = None
            self._state = ActivationState.READY
            return self._state

    def _ready_authority(self) -> object:
        if self._state is not ActivationState.READY or self._authority is None:
            raise ActivationError("owner identity authority is not writable")
        return self._authority

    def owner_name(self) -> str:
        with self._lock:
            if self._authority is None:
                return ""
            snapshot = self._authority.snapshot
            return snapshot.display_name or ""

    def owner_address(self) -> str:
        with self._lock:
            if self._authority is None:
                return "Sir"
            return self._authority.address()

    def owner_prompt_directive(self) -> str:
        with self._lock:
            if self._authority is None:
                return (
                    "[OWNER PROFILE - DEGRADED READ-ONLY]\n"
                    "The owner's name is unavailable. If an address is necessary, "
                    "use the literal English word 'Sir'. Never translate, localize, "
                    "or replace it with Efendim or another honorific."
                )
            directive = self._authority.prompt_directive()
            question = self._contact_question
            if question:
                directive += (
                    "\nAt the first real conversational contact ask exactly: "
                    f"{question} When answered, call set_owner_name exactly once."
                )
            return directive + (
                "\nThe fallback is exactly the English token 'Sir'. It is a literal "
                "proper form of address and must never be translated or localized."
            )

    def set_name(self, value: object) -> object:
        with self._lock:
            result = self._ready_authority().set_name(value)
            self._contact_question = None
            return result

    def correct_name(self, value: object) -> object:
        with self._lock:
            return self._ready_authority().correct_name(value)

    def forget_name(self) -> object:
        with self._lock:
            result = self._ready_authority().forget_name()
            self._contact_question = self._authority.begin_contact()
            return result

    def bind_phase5_bridge(self, bridge: object | None) -> None:
        with self._lock:
            if self._state is ActivationState.TERMINATED and bridge is not None:
                raise ActivationError("terminated coordinator cannot bind a session")
            self._phase5_bridge = bridge

    def terminate(self, reason: str) -> object | None:
        if reason not in {"kill", "revoke", "rollback", "reconnect", "shutdown"}:
            raise ActivationError("termination reason is outside the closed contract")
        with self._lock:
            bridge, self._phase5_bridge = self._phase5_bridge, None
            self._state = ActivationState.TERMINATED
        if bridge is None:
            return None
        terminator = getattr(bridge, reason, None)
        if not callable(terminator):
            terminator = getattr(bridge, "terminate", None)
            if not callable(terminator):
                raise ActivationError("Phase 5 bridge has no termination contract")
            return terminator(reason)
        return terminator()

    def handle_owner_tool(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
        if name not in _OWNER_TOOL_NAMES or not isinstance(arguments, Mapping):
            raise ActivationError("owner tool request is invalid")
        if name == "forget_owner_name":
            if arguments:
                raise ActivationError("forget owner name accepts no arguments")
            snapshot = self.forget_name()
        else:
            if set(arguments) != {"name"}:
                raise ActivationError("owner name tool requires exactly one name")
            snapshot = (
                self.set_name(arguments["name"])
                if name == "set_owner_name"
                else self.correct_name(arguments["name"])
            )
        return {
            "result": "owner profile updated",
            "state": snapshot.state.value,
            "name_known": snapshot.name_known,
            "address": snapshot.address,
        }

    def install_into_main(self, module: ModuleType) -> None:
        """Install host seams without altering frozen ``main.py`` bytes."""

        if self.start() not in {ActivationState.READY, ActivationState.DEGRADED}:
            raise ActivationError("activation coordinator did not start")
        if getattr(module, "_onyx_live_activation_v1", None) is not None:
            raise ActivationError("activation coordinator is already installed")

        original_prompt = module._load_system_prompt
        original_execute = module.Assistant._execute_tool
        original_start = module.Assistant._start_phase5_session
        original_stop = module.Assistant._stop_phase5_session
        controller = self

        module._load_owner_name = lambda path=None: controller.owner_name()

        def load_prompt() -> str:
            return original_prompt() + "\n\n" + controller.owner_prompt_directive()

        module._load_system_prompt = load_prompt
        existing = {
            item.get("name")
            for item in module.TOOL_DECLARATIONS
            if isinstance(item, dict)
        }
        for declaration in OWNER_TOOL_DECLARATIONS:
            if declaration["name"] not in existing:
                module.TOOL_DECLARATIONS.append(copy.deepcopy(declaration))

        async def execute_tool(instance: object, fc: object) -> object:
            if getattr(fc, "name", None) not in _OWNER_TOOL_NAMES:
                return await original_execute(instance, fc)
            try:
                response = controller.handle_owner_tool(
                    fc.name, dict(getattr(fc, "args", None) or {})
                )
            except Exception as exc:
                response = {
                    "result": "owner profile update refused",
                    "error": type(exc).__name__,
                }
            return module.types.FunctionResponse(
                id=fc.id, name=fc.name, response=response
            )

        def start_phase5(instance: object) -> None:
            original_start(instance)
            controller.bind_phase5_bridge(getattr(instance, "_phase5", None))

        def stop_phase5(instance: object, reason: str) -> None:
            controller.bind_phase5_bridge(None)
            original_stop(instance, reason)

        module.Assistant._execute_tool = execute_tool
        module.Assistant._start_phase5_session = start_phase5
        module.Assistant._stop_phase5_session = stop_phase5

        # ``main`` imports the accepted UI module before this opt-in seam is
        # installed.  Make V8 authoritative for setup and HUD addressing while
        # allowing the frozen setup handler to persist the same value as a
        # projection alongside OS/credential settings.
        ui_module = sys.modules.get("ui")
        window_type = getattr(ui_module, "MainWindow", None)
        if window_type is not None:
            original_setup_done = window_type._on_setup_done

            def configured_owner_name(_window: object) -> str:
                return controller.owner_name() or "Sir"

            def setup_done(
                window: object,
                key: str,
                os_name: str,
                owner_name: str = "",
            ) -> None:
                try:
                    if controller.owner_name():
                        controller.correct_name(owner_name)
                    else:
                        controller.set_name(owner_name)
                except Exception as exc:
                    overlay = getattr(window, "_overlay", None)
                    if overlay is not None:
                        overlay.show_error(
                            "Owner identity could not be persisted securely "
                            f"({type(exc).__name__})."
                        )
                    log = getattr(window, "_log", None)
                    if log is not None:
                        log.append_log("ERR: Owner Profile V8 update refused.")
                    return
                original_setup_done(window, key, os_name, controller.owner_name())

            window_type._configured_owner_name = configured_owner_name
            window_type._on_setup_done = setup_done
        module._onyx_live_activation_v1 = self


def activate_main(module: ModuleType, environ: Mapping[str, str] | None = None) -> OnyxLiveActivationV1:
    flags = ActivationFlagsV1.from_environ(environ)
    if not flags.active:
        raise ActivationError("live activation was not explicitly requested")
    controller = OnyxLiveActivationV1(flags)
    controller.install_into_main(module)
    return controller


__all__ = [
    "ActivationError",
    "ActivationFlagsV1",
    "ActivationState",
    "HUD_FLAG",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OWNER_JOURNAL_RELATIVE",
    "OWNER_KEY_ACCOUNT",
    "OWNER_KEY_SERVICE",
    "OWNER_PROFILE_FLAG",
    "OWNER_PROFILE_ID",
    "OWNER_RUNTIME_INSTANCE",
    "OWNER_TOOL_DECLARATIONS",
    "OnyxLiveActivationV1",
    "PHASE5_FLAGS",
    "REQUIRED_CHILD_FLAGS",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "owner_journal_path",
    "provision_owner_authority",
]
