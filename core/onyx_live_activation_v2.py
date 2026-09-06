"""Onyx Live Activation V2: real-host, transactional, default-off transition.

V2 does not import or subclass rejected Activation V1.  It preflights the
actual ``main.OnyxLive`` and UI surfaces, installs every seam transactionally,
and only then permits Owner Profile V8 provisioning.
"""

from __future__ import annotations

import copy
import inspect
import os
import secrets
import sys
import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Callable, Protocol


LIVE_MASTER_FLAG = "ONYX_LIVE_ACTIVATION_V2"
LIVE_ROLLBACK_FLAG = "ONYX_LIVE_ROLLBACK_V2"
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
CHILD_FLAGS = (OWNER_PROFILE_FLAG, HUD_FLAG, *PHASE5_FLAGS)
CONTROL_FLAGS = (LIVE_MASTER_FLAG, LIVE_ROLLBACK_FLAG, *CHILD_FLAGS)

OWNER_PROFILE_ID = "cyryx-onyx-owner-primary-v8"
OWNER_RUNTIME_INSTANCE = "onyx-live-owner-v8"
OWNER_KEY_SERVICE = "CyryxLabs.Onyx.OwnerProfileV8"
OWNER_KEY_ACCOUNT = "journal-key-primary"
OWNER_JOURNAL_RELATIVE = Path("identity") / "owner-profile-v8.journal.json"

_OWNER_TOOLS = frozenset(
    {"set_owner_name", "correct_owner_name", "forget_owner_name"}
)


class ActivationV2Error(RuntimeError):
    """Safe transition error without owner data or credentials."""


class ActivationV2State(str, Enum):
    PREFLIGHTED = "preflighted"
    INSTALLED = "installed"
    READY = "ready"
    DEGRADED = "degraded"
    TERMINATED = "terminated"


@dataclass(frozen=True, slots=True)
class ActivationFlagsV2:
    master: bool
    owner_profile: bool
    hud_v5: bool
    phase5: tuple[bool, ...]

    def __post_init__(self) -> None:
        if any(
            type(value) is not bool
            for value in (self.master, self.owner_profile, self.hud_v5)
        ):
            raise ActivationV2Error("activation flags must be exact booleans")
        if type(self.phase5) is not tuple or len(self.phase5) != len(PHASE5_FLAGS):
            raise ActivationV2Error("Phase 5 flag set is incomplete")
        if any(type(value) is not bool for value in self.phase5):
            raise ActivationV2Error("Phase 5 flags must be exact booleans")
        if not (self.master and self.owner_profile and self.hud_v5 and all(self.phase5)):
            raise ActivationV2Error("complete active V2 flags are required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV2":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV2Error("rollback is not an active configuration")
        for name in (LIVE_MASTER_FLAG, *CHILD_FLAGS):
            if source.get(name) != "1":
                raise ActivationV2Error("activation environment is not canonical")
        return cls(True, True, True, (True,) * len(PHASE5_FLAGS))


def exact_activation_environment() -> dict[str, str]:
    return {
        LIVE_MASTER_FLAG: "1",
        OWNER_PROFILE_FLAG: "1",
        HUD_FLAG: "1",
        **{name: "1" for name in PHASE5_FLAGS},
        "ONYX_PHASE5_PRINCIPAL_ID": "onyx-owner",
        "ONYX_PHASE5_WORKSPACE_ID": "onyx-local-workspace",
        "ONYX_PHASE5_ACCOUNT_ID": "cyryx-local-account",
        "ONYX_PHASE5_PROFILE_ID": "onyx-owner-profile",
    }


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


@dataclass(frozen=True, slots=True)
class HostContractV2:
    module: ModuleType
    onyx_live: type
    ui_module: ModuleType
    main_window: type


_MAIN_FUNCTIONS = (
    "_load_owner_name",
    "_load_system_prompt",
    "set_phase5_authorization_hook",
)
_ONYX_METHODS = (
    "__init__",
    "_start_phase5_session",
    "_stop_phase5_session",
    "_build_config",
    "_execute_tool",
)
_WINDOW_METHODS = ("_configured_owner_name", "_on_setup_done")


def _exact_function(owner: object, name: str) -> object:
    namespace = getattr(owner, "__dict__", None)
    if namespace is None or name not in namespace:
        raise ActivationV2Error(f"required host seam is absent: {name}")
    value = namespace[name]
    if not inspect.isfunction(value):
        raise ActivationV2Error(f"required host seam is not a function: {name}")
    return value


def preflight_host(module: ModuleType) -> HostContractV2:
    """Validate the real imported host without writing any durable state."""

    if type(module) is not ModuleType or module.__name__ != "main":
        raise ActivationV2Error("exact imported main module is required")
    onyx_live = getattr(module, "OnyxLive", None)
    if type(onyx_live) is not type or onyx_live.__module__ != "main":
        raise ActivationV2Error("main.OnyxLive is unavailable")
    for name in _ONYX_METHODS:
        _exact_function(onyx_live, name)
    for name in _MAIN_FUNCTIONS:
        value = getattr(module, name, None)
        if not inspect.isfunction(value):
            raise ActivationV2Error(f"main host seam is unavailable: {name}")
    if type(getattr(module, "TOOL_DECLARATIONS", None)) is not list:
        raise ActivationV2Error("main tool declarations are unavailable")
    response_type = getattr(getattr(module, "types", None), "FunctionResponse", None)
    if response_type is None or not callable(response_type):
        raise ActivationV2Error("main FunctionResponse seam is unavailable")

    ui_module = sys.modules.get("ui")
    if type(ui_module) is not ModuleType or ui_module.__name__ != "ui":
        raise ActivationV2Error("real UI module is unavailable")
    main_window = getattr(ui_module, "MainWindow", None)
    if not inspect.isclass(main_window) or main_window.__module__ != "ui":
        raise ActivationV2Error("ui.MainWindow is unavailable")
    for name in _WINDOW_METHODS:
        _exact_function(main_window, name)
    projection = getattr(ui_module, "_HudV5Projection", None)
    if not inspect.isclass(projection) or not callable(
        getattr(projection, "set_owner_name", None)
    ):
        raise ActivationV2Error("HUD V5 identity projection seam is unavailable")
    return HostContractV2(module, onyx_live, ui_module, main_window)


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
        raise ActivationV2Error("owner credential vault is unavailable") from exc
    if current is not None:
        if type(current) is not bytes or len(current) != 32:
            raise ActivationV2Error("owner credential representation is invalid")
        return current
    if existing_state:
        raise ActivationV2Error("owner credential is missing for durable state")
    generated = secrets.token_bytes(32)
    if type(generated) is not bytes or len(generated) != 32:
        raise ActivationV2Error("secure owner key generation failed")
    try:
        vault.set_bytes(generated)
        observed = vault.get_bytes()
    except Exception as exc:
        raise ActivationV2Error("owner credential provisioning failed") from exc
    if type(observed) is not bytes or not secrets.compare_digest(observed, generated):
        raise ActivationV2Error("owner credential readback failed")
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
    from core import owner_profile_v8 as owner_v8
    from core.paths import config_file
    from memory.memory_manager import get_store

    journal = (journal_path or owner_journal_path()).resolve(strict=False)
    memory_store = get_store() if memory is None else memory
    config = config_file() if config_path is None else Path(config_path)
    lease = transaction_lease or owner_v8.WindowsHostTransactionLease()
    heads = chain_head_store or owner_v8.WindowsCredentialChainHeadStore(
        host_lease=lease
    )
    key_vault = vault or _owner_key_vault()
    journal_exists = journal.exists()
    try:
        head = heads.load(OWNER_PROFILE_ID)
    except Exception as exc:
        raise ActivationV2Error("owner chain-head vault is unavailable") from exc
    key = _provision_key(key_vault, existing_state=journal_exists or head is not None)
    if journal_exists != (head is not None):
        raise ActivationV2Error("owner durable stores are incomplete")
    if not journal_exists:
        journal.parent.mkdir(parents=True, exist_ok=True)
        return owner_v8.OwnerProfileAuthority.bootstrap(
            config_path=config,
            memory=memory_store,
            journal_path=journal,
            journal_key=key,
            owner_profile_id=OWNER_PROFILE_ID,
            runtime_instance=OWNER_RUNTIME_INSTANCE,
            chain_head_store=heads,
            transaction_lease=lease,
        )
    return owner_v8.OwnerProfileAuthority(
        config_path=config,
        memory=memory_store,
        journal_path=journal,
        journal_key=key,
        owner_profile_id=OWNER_PROFILE_ID,
        runtime_instance=OWNER_RUNTIME_INSTANCE,
        chain_head_store=heads,
        transaction_lease=lease,
    )


OWNER_TOOL_DECLARATIONS = (
    {
        "name": "set_owner_name",
        "description": "Persist the owner's chosen name after first contact.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}},
            "required": ["name"],
        },
    },
    {
        "name": "correct_owner_name",
        "description": "Correct the owner's chosen name on explicit request.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}},
            "required": ["name"],
        },
    },
    {
        "name": "forget_owner_name",
        "description": "Forget the owner's chosen name on explicit request.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
)


class _Installation:
    def __init__(self, originals: list[tuple[object, str, object]]) -> None:
        self.originals = originals

    def rollback(self) -> None:
        for owner, name, value in reversed(self.originals):
            setattr(owner, name, value)
        self.originals.clear()


class OnyxLiveActivationV2:
    def __init__(
        self,
        flags: ActivationFlagsV2,
        contract: HostContractV2,
        *,
        authority_factory: Callable[[], object] = provision_owner_authority,
    ) -> None:
        if type(flags) is not ActivationFlagsV2:
            raise ActivationV2Error("exact active flags are required")
        if type(contract) is not HostContractV2:
            raise ActivationV2Error("exact preflight contract is required")
        self.flags = flags
        self.contract = contract
        self._authority_factory = authority_factory
        self._authority: object | None = None
        self._state = ActivationV2State.PREFLIGHTED
        self._failure_type: str | None = None
        self._contact_question: str | None = None
        self._installation: _Installation | None = None
        self._live_instances: weakref.WeakSet[object] = weakref.WeakSet()
        self._session_counter = 0
        self._pending_binding: tuple[str, str] | None = None
        self._bridges: weakref.WeakKeyDictionary[object, object] = (
            weakref.WeakKeyDictionary()
        )
        self._lock = threading.RLock()

    @property
    def state(self) -> ActivationV2State:
        return self._state

    @property
    def failure_type(self) -> str | None:
        return self._failure_type

    @property
    def pending_binding(self) -> tuple[str, str] | None:
        return self._pending_binding

    def _degrade(self, exc: BaseException) -> None:
        self._failure_type = type(exc).__name__
        self._state = ActivationV2State.DEGRADED

    def start(self) -> ActivationV2State:
        with self._lock:
            if self._state in {ActivationV2State.READY, ActivationV2State.DEGRADED}:
                return self._state
            if self._state is not ActivationV2State.INSTALLED:
                raise ActivationV2Error("host seams must be installed before provisioning")
            try:
                authority = self._authority_factory()
                snapshot = authority.reconcile()
                if not snapshot.reconciled:
                    raise ActivationV2Error("owner reconciliation degraded")
                question = authority.begin_contact()
            except Exception as exc:
                self._authority = None
                self._degrade(exc)
                return self._state
            self._authority = authority
            self._contact_question = question
            self._failure_type = None
            self._state = ActivationV2State.READY
            return self._state

    def bind_live_instance(self, instance: object) -> None:
        if not isinstance(instance, self.contract.onyx_live):
            raise ActivationV2Error("exact OnyxLive instance is required")
        self._live_instances.add(instance)

    def next_session_binding(self) -> tuple[str, str]:
        with self._lock:
            self._session_counter += 1
            suffix = f"p{os.getpid()}-n{self._session_counter}"
            binding = (f"session-{suffix}", f"trace-{suffix}")
            self._pending_binding = binding
            return binding

    def bind_phase5(self, instance: object, bridge: object) -> None:
        with self._lock:
            if self._pending_binding is None:
                raise ActivationV2Error("Phase 5 binding was not reserved")
            runtime_binding = getattr(bridge, "_binding", None)
            expected_session, expected_trace = self._pending_binding
            if (
                getattr(runtime_binding, "session_id", None) != expected_session
                or getattr(runtime_binding, "trace_id", None) != expected_trace
            ):
                raise ActivationV2Error("Phase 5 bridge binding diverged")
            self._bridges[instance] = bridge
            self._pending_binding = None

    def unbind_phase5(self, instance: object) -> None:
        with self._lock:
            self._bridges.pop(instance, None)
            self._pending_binding = None

    def owner_name(self) -> str:
        if self._authority is None:
            return ""
        return self._authority.snapshot.display_name or ""

    def owner_address(self) -> str:
        return self.owner_name() or "Sir"

    def owner_prompt_directive(self) -> str:
        if self._authority is None:
            return (
                "[OWNER PROFILE - DEGRADED READ-ONLY]\nUse the literal English "
                "word 'Sir' only when needed. Never translate it to Efendim or "
                "any other honorific."
            )
        value = self._authority.prompt_directive()
        if self._contact_question:
            value += (
                "\nAt first real contact ask exactly: "
                f"{self._contact_question} Then call set_owner_name once."
            )
        return value + (
            "\n'Sir' is a literal English proper address. Never translate, "
            "localize, or replace it with Efendim."
        )

    def _projection_targets(self) -> list[tuple[Callable[[], str], Callable[[str], None]]]:
        targets: list[tuple[Callable[[], str], Callable[[str], None]]] = []
        for host in tuple(self._live_instances):
            ui = getattr(host, "ui", None)
            window = getattr(ui, "_win", None)
            if window is None:
                continue
            projection = getattr(window, "_v5_projection", None)
            if projection is not None and callable(
                getattr(projection, "set_owner_name", None)
            ):
                targets.append(
                    (
                        lambda item=projection: str(item.ownerName),
                        lambda value, item=projection: item.set_owner_name(value),
                    )
                )
            overlay = getattr(window, "_overlay", None)
            name_input = getattr(overlay, "_name_input", None)
            if name_input is not None and callable(getattr(name_input, "text", None)) and callable(
                getattr(name_input, "setText", None)
            ):
                targets.append(
                    (
                        lambda item=name_input: str(item.text()),
                        lambda value, item=name_input: item.setText(value),
                    )
                )
        return targets

    def _project_owner(self, address: str) -> None:
        targets = self._projection_targets()
        prior: list[tuple[Callable[[str], None], str]] = []
        try:
            for read, write in targets:
                previous = read()
                prior.append((write, previous))
                write(address)
        except Exception as exc:
            for write, previous in reversed(prior):
                try:
                    write(previous)
                except Exception:
                    pass
            self._degrade(exc)
            raise ActivationV2Error("owner UI projection failed") from exc

    def _ready_authority(self) -> object:
        if self._state is not ActivationV2State.READY or self._authority is None:
            raise ActivationV2Error("owner identity authority is not writable")
        return self._authority

    def _owner_operation(self, operation: str, value: object = None) -> object:
        authority = self._ready_authority()
        try:
            if operation == "set":
                snapshot = authority.set_name(value)
                self._contact_question = None
            elif operation == "correct":
                snapshot = authority.correct_name(value)
            elif operation == "forget":
                snapshot = authority.forget_name()
                self._contact_question = authority.begin_contact()
            else:
                raise ActivationV2Error("unknown owner operation")
        except Exception as exc:
            self._degrade(exc)
            raise
        self._project_owner(snapshot.display_name or "Sir")
        return snapshot

    def set_name(self, value: object) -> object:
        return self._owner_operation("set", value)

    def correct_name(self, value: object) -> object:
        return self._owner_operation("correct", value)

    def forget_name(self) -> object:
        return self._owner_operation("forget")

    def handle_owner_tool(
        self, name: str, arguments: Mapping[str, object]
    ) -> dict[str, object]:
        if name not in _OWNER_TOOLS or not isinstance(arguments, Mapping):
            raise ActivationV2Error("owner tool request is invalid")
        if name == "forget_owner_name":
            if arguments:
                raise ActivationV2Error("forget accepts no arguments")
            snapshot = self.forget_name()
        else:
            if set(arguments) != {"name"}:
                raise ActivationV2Error("name tool requires exactly name")
            snapshot = (
                self.set_name(arguments["name"])
                if name == "set_owner_name"
                else self.correct_name(arguments["name"])
            )
        return {
            "result": "owner profile updated",
            "state": snapshot.state.value,
            "name_known": snapshot.name_known,
            "address": snapshot.display_name or "Sir",
        }

    def install(self, *, fail_after: int | None = None) -> None:
        """Install every real-host seam atomically, restoring all on failure."""

        with self._lock:
            if self._state is not ActivationV2State.PREFLIGHTED:
                raise ActivationV2Error("activation is not in preflighted state")
            module = self.contract.module
            host_type = self.contract.onyx_live
            window_type = self.contract.main_window
            originals: list[tuple[object, str, object]] = []
            writes = 0

            def patch(owner: object, name: str, value: object) -> None:
                nonlocal writes
                previous = getattr(owner, name)
                setattr(owner, name, value)
                originals.append((owner, name, previous))
                writes += 1
                if fail_after is not None and writes >= fail_after:
                    raise ActivationV2Error("injected seam installation failure")

            original_prompt = module._load_system_prompt
            original_init = host_type.__init__
            original_execute = host_type._execute_tool
            original_stop = host_type._stop_phase5_session
            original_setup = window_type._on_setup_done
            controller = self

            def load_owner_name(path=None) -> str:
                return controller.owner_name()

            def load_prompt() -> str:
                return original_prompt() + "\n\n" + controller.owner_prompt_directive()

            def host_init(instance: object, *args: object, **kwargs: object) -> None:
                original_init(instance, *args, **kwargs)
                controller.bind_live_instance(instance)

            def start_phase5(instance: object) -> None:
                module.set_phase5_authorization_hook(None)
                instance._phase5 = None
                if not module._phase5_requested():
                    if instance._dashboard:
                        instance._dashboard.set_phase5_bridge(None)
                    return
                try:
                    from core.phase5_integration_v3 import (
                        CatalogSeedV3,
                        create_phase5_integration_v3,
                    )

                    catalog = tuple(
                        CatalogSeedV3(
                            item_id=str(item["name"]),
                            label=str(item["name"]).replace("_", " ").title(),
                        )
                        for item in module.TOOL_DECLARATIONS
                        if isinstance(item, dict) and isinstance(item.get("name"), str)
                    )
                    session_id, trace_id = controller.next_session_binding()
                    bridge = create_phase5_integration_v3(
                        session_id=session_id,
                        trace_id=trace_id,
                        catalog=catalog,
                    )
                    if bridge is not None:
                        controller.bind_phase5(instance, bridge)
                        module.set_phase5_authorization_hook(bridge.permission_hook)
                    instance._phase5 = bridge
                    if instance._dashboard:
                        instance._dashboard.set_phase5_bridge(bridge)
                except Exception as exc:
                    controller.unbind_phase5(instance)
                    module.set_phase5_authorization_hook(None)
                    instance._phase5 = None
                    if instance._dashboard:
                        instance._dashboard.set_phase5_bridge(None)
                    instance.ui.write_log(
                        "ERR: Phase 5 integration disabled safely "
                        f"({type(exc).__name__})."
                    )

            def stop_phase5(instance: object, reason: str) -> None:
                try:
                    original_stop(instance, reason)
                finally:
                    controller.unbind_phase5(instance)

            async def execute_tool(instance: object, fc: object) -> object:
                if getattr(fc, "name", None) not in _OWNER_TOOLS:
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

            def configured_owner_name(_window: object) -> str:
                return controller.owner_address()

            def setup_done(
                window: object, key: str, os_name: str, owner_name: str = ""
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
                    return
                original_setup(window, key, os_name, controller.owner_name())

            declarations = list(module.TOOL_DECLARATIONS)
            existing = {
                item.get("name") for item in declarations if isinstance(item, dict)
            }
            declarations.extend(
                copy.deepcopy(item)
                for item in OWNER_TOOL_DECLARATIONS
                if item["name"] not in existing
            )

            try:
                patch(module, "_load_owner_name", load_owner_name)
                patch(module, "_load_system_prompt", load_prompt)
                patch(module, "TOOL_DECLARATIONS", declarations)
                patch(host_type, "__init__", host_init)
                patch(host_type, "_start_phase5_session", start_phase5)
                patch(host_type, "_stop_phase5_session", stop_phase5)
                patch(host_type, "_execute_tool", execute_tool)
                patch(window_type, "_configured_owner_name", configured_owner_name)
                patch(window_type, "_on_setup_done", setup_done)
            except Exception:
                for owner, name, previous in reversed(originals):
                    setattr(owner, name, previous)
                raise
            self._installation = _Installation(originals)
            self._state = ActivationV2State.INSTALLED

    def rollback_installation(self) -> None:
        with self._lock:
            if self._installation is not None:
                self._installation.rollback()
                self._installation = None
            self._state = ActivationV2State.TERMINATED


def activate_main(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> OnyxLiveActivationV2:
    """Preflight, transactionally install, then provision in that exact order."""

    flags = ActivationFlagsV2.from_canonical_environ(environ)
    contract = preflight_host(module)
    controller = OnyxLiveActivationV2(flags, contract)
    controller.install()
    controller.start()
    module._onyx_live_activation_v2 = controller
    return controller


__all__ = [
    "ActivationFlagsV2",
    "ActivationV2Error",
    "ActivationV2State",
    "CHILD_FLAGS",
    "CONTROL_FLAGS",
    "HUD_FLAG",
    "HostContractV2",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OWNER_PROFILE_FLAG",
    "OWNER_TOOL_DECLARATIONS",
    "OnyxLiveActivationV2",
    "PHASE5_FLAGS",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "owner_journal_path",
    "preflight_host",
    "provision_owner_authority",
]
