"""Onyx Live Activation V4: Qt-affine, transactional, default-off transition.

This candidate is independent of rejected V1/V2/V3.  Worker threads exchange only
immutable messages with a GUI-thread dispatcher.  Every QObject read and write,
including rollback verification, occurs on the object's affinity thread.
"""

from __future__ import annotations

import copy
import inspect
import os
import secrets
import sys
import threading
import time
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Callable, Protocol

from PySide6.QtCore import QEvent, QObject, QThread, Qt
from core.qt_compat import pyqtSignal, pyqtSlot
from core.qt_compat import sip
LIVE_MASTER_FLAG = "ONYX_LIVE_ACTIVATION_V4"
LIVE_ROLLBACK_FLAG = "ONYX_LIVE_ROLLBACK_V4"
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


class ActivationV4Error(RuntimeError):
    """Safe transition error without owner data or credentials."""


class UiApplyReadbackMismatch(ActivationV4Error):
    """A target setter returned but its exact readback did not match."""


class UiRollbackReadbackMismatch(ActivationV4Error):
    """A rollback setter returned but exact prior state was not restored."""


class UiTargetDestroyed(ActivationV4Error):
    """A QObject target ceased to be valid during a GUI transaction."""


class ActivationV4State(str, Enum):
    PREFLIGHTED = "preflighted"
    INSTALLED = "installed"
    READY = "ready"
    DEGRADED = "degraded"
    TERMINATED = "terminated"


@dataclass(frozen=True, slots=True)
class ActivationFlagsV4:
    master: bool
    owner_profile: bool
    hud_v5: bool
    phase5: tuple[bool, ...]

    def __post_init__(self) -> None:
        if any(
            type(value) is not bool
            for value in (self.master, self.owner_profile, self.hud_v5)
        ):
            raise ActivationV4Error("activation flags must be exact booleans")
        if type(self.phase5) is not tuple or len(self.phase5) != len(PHASE5_FLAGS):
            raise ActivationV4Error("Phase 5 flag set is incomplete")
        if any(type(value) is not bool for value in self.phase5):
            raise ActivationV4Error("Phase 5 flags must be exact booleans")
        if not (self.master and self.owner_profile and self.hud_v5 and all(self.phase5)):
            raise ActivationV4Error("complete active V4 flags are required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV4":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV4Error("rollback is not an active configuration")
        for name in (LIVE_MASTER_FLAG, *CHILD_FLAGS):
            if source.get(name) != "1":
                raise ActivationV4Error("activation environment is not canonical")
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
class HostContractV4:
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
_WINDOW_METHODS = (
    "__init__",
    "_configured_owner_name",
    "_on_setup_done",
    "closeEvent",
)


def _exact_function(owner: object, name: str) -> object:
    namespace = getattr(owner, "__dict__", None)
    if namespace is None or name not in namespace:
        raise ActivationV4Error(f"required host seam is absent: {name}")
    value = namespace[name]
    if not inspect.isfunction(value):
        raise ActivationV4Error(f"required host seam is not a function: {name}")
    return value


def preflight_host(module: ModuleType) -> HostContractV4:
    if type(module) is not ModuleType or module.__name__ != "main":
        raise ActivationV4Error("exact imported main module is required")
    onyx_live = getattr(module, "OnyxLive", None)
    if type(onyx_live) is not type or onyx_live.__module__ != "main":
        raise ActivationV4Error("main.OnyxLive is unavailable")
    for name in _ONYX_METHODS:
        _exact_function(onyx_live, name)
    for name in _MAIN_FUNCTIONS:
        if not inspect.isfunction(getattr(module, name, None)):
            raise ActivationV4Error(f"main host seam is unavailable: {name}")
    if type(getattr(module, "TOOL_DECLARATIONS", None)) is not list:
        raise ActivationV4Error("main tool declarations are unavailable")
    response_type = getattr(getattr(module, "types", None), "FunctionResponse", None)
    if response_type is None or not callable(response_type):
        raise ActivationV4Error("main FunctionResponse seam is unavailable")
    ui_module = sys.modules.get("ui")
    if type(ui_module) is not ModuleType or ui_module.__name__ != "ui":
        raise ActivationV4Error("real UI module is unavailable")
    main_window = getattr(ui_module, "MainWindow", None)
    if not inspect.isclass(main_window) or main_window.__module__ != "ui":
        raise ActivationV4Error("ui.MainWindow is unavailable")
    for name in _WINDOW_METHODS:
        _exact_function(main_window, name)
    projection = getattr(ui_module, "_HudV5Projection", None)
    if not inspect.isclass(projection) or not callable(
        getattr(projection, "set_owner_name", None)
    ):
        raise ActivationV4Error("HUD V5 identity projection seam is unavailable")
    return HostContractV4(module, onyx_live, ui_module, main_window)


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
        raise ActivationV4Error("owner credential vault is unavailable") from exc
    if current is not None:
        if type(current) is not bytes or len(current) != 32:
            raise ActivationV4Error("owner credential representation is invalid")
        return current
    if existing_state:
        raise ActivationV4Error("owner credential is missing for durable state")
    generated = secrets.token_bytes(32)
    if type(generated) is not bytes or len(generated) != 32:
        raise ActivationV4Error("secure owner key generation failed")
    try:
        vault.set_bytes(generated)
        observed = vault.get_bytes()
    except Exception as exc:
        raise ActivationV4Error("owner credential provisioning failed") from exc
    if type(observed) is not bytes or not secrets.compare_digest(observed, generated):
        raise ActivationV4Error("owner credential readback failed")
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
        raise ActivationV4Error("owner chain-head vault is unavailable") from exc
    key = _provision_key(key_vault, existing_state=journal_exists or head is not None)
    if journal_exists != (head is not None):
        raise ActivationV4Error("owner durable stores are incomplete")
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


@dataclass(frozen=True, slots=True)
class OwnerUiRequestV4:
    request_id: int
    address: str
    deadline_ns: int


@dataclass(frozen=True, slots=True)
class OwnerUiAckV4:
    request_id: int
    applied: bool
    target_count: int
    failure_type: str | None = None
    rollback_failure_type: str | None = None


def _normalize_address(value: object) -> str:
    return " ".join(str(value).split())[:80] or "Sir"


@dataclass(frozen=True, slots=True)
class _UiTargetV4:
    reference: weakref.ReferenceType[QObject]
    kind: str

    def resolve(self) -> QObject:
        target = self.reference()
        if target is None or sip.isdeleted(target):
            raise UiTargetDestroyed("owner UI target was destroyed")
        return target

    def read(self) -> str:
        target = self.resolve()
        if self.kind == "projection":
            return str(target.ownerName)
        if self.kind == "setup":
            return str(target.text())
        raise ActivationV4Error("owner UI target kind is invalid")

    def write(self, value: str) -> None:
        target = self.resolve()
        if self.kind == "projection":
            target.set_owner_name(value)
            return
        if self.kind == "setup":
            target.setText(value)
            return
        raise ActivationV4Error("owner UI target kind is invalid")


@dataclass(slots=True)
class _Pending:
    event: threading.Event
    ack: OwnerUiAckV4 | None = None


class OwnerUiEndpointV4:
    """Plain thread-safe endpoint; it never owns or reads a QObject."""

    def __init__(self, *, timeout_seconds: float) -> None:
        if not (0.01 <= timeout_seconds <= 30.0):
            raise ActivationV4Error("UI acknowledgement timeout is invalid")
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._sequence = 0
        self._closed = False
        self._emit: Callable[[object], None] | None = None
        self._direct: Callable[[OwnerUiRequestV4], None] | None = None
        self._is_gui_thread: Callable[[], bool] | None = None

    def bind(
        self,
        *,
        emit: Callable[[object], None],
        direct: Callable[[OwnerUiRequestV4], None],
        is_gui_thread: Callable[[], bool],
    ) -> None:
        with self._lock:
            if self._closed or self._emit is not None:
                raise ActivationV4Error("UI endpoint cannot be rebound")
            self._emit = emit
            self._direct = direct
            self._is_gui_thread = is_gui_thread

    def submit(self, address: str) -> OwnerUiAckV4:
        if type(address) is not str or not address:
            raise ActivationV4Error("owner UI address is invalid")
        with self._lock:
            self._sequence += 1
            request_id = self._sequence
            if self._closed or self._emit is None:
                return OwnerUiAckV4(request_id, False, 0, "DispatcherClosed")
            pending = _Pending(threading.Event())
            self._pending[request_id] = pending
            deadline_ns = time.monotonic_ns() + int(self._timeout * 1_000_000_000)
            request = OwnerUiRequestV4(
                request_id, _normalize_address(address), deadline_ns
            )
            emit = self._emit
            direct = self._direct
            is_gui = self._is_gui_thread
        try:
            if is_gui is not None and is_gui():
                if direct is None:
                    raise ActivationV4Error("direct GUI dispatch is unavailable")
                direct(request)
            else:
                emit(request)
        except Exception as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            return OwnerUiAckV4(request_id, False, 0, type(exc).__name__)
        remaining = max(0.0, (deadline_ns - time.monotonic_ns()) / 1_000_000_000)
        if not pending.event.wait(remaining):
            with self._lock:
                self._pending.pop(request_id, None)
            return OwnerUiAckV4(request_id, False, 0, "TimeoutError")
        with self._lock:
            ack = pending.ack
            self._pending.pop(request_id, None)
        return ack or OwnerUiAckV4(request_id, False, 0, "MissingAcknowledgement")

    def is_pending(self, request_id: int) -> bool:
        with self._lock:
            return not self._closed and request_id in self._pending

    def complete(self, ack: OwnerUiAckV4) -> None:
        with self._lock:
            pending = self._pending.get(ack.request_id)
            if pending is None:
                return
            pending.ack = ack
            pending.event.set()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            values = tuple(self._pending.items())
            for request_id, pending in values:
                pending.ack = OwnerUiAckV4(
                    request_id, False, 0, "DispatcherClosed"
                )
                pending.event.set()

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed


class OwnerUiDispatcherV4(QObject):
    requested = pyqtSignal(object)

    def __init__(
        self,
        controller: "OnyxLiveActivationV4",
        window: QObject,
        endpoint: OwnerUiEndpointV4,
    ) -> None:
        if QThread.currentThread() != window.thread():
            raise ActivationV4Error("dispatcher must be constructed on GUI thread")
        super().__init__(window)
        self._controller = controller
        self._window_ref = weakref.ref(window)
        self._endpoint = endpoint
        self._affinity = window.thread()
        affinity = self._affinity
        self.requested.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)
        endpoint.bind(
            emit=self.requested.emit,
            direct=self._dispatch,
            is_gui_thread=lambda: QThread.currentThread() == affinity,
        )
        window.installEventFilter(self)
        window.destroyed.connect(self._destroyed)

    @property
    def window(self) -> QObject | None:
        return self._window_ref()

    @pyqtSlot(object)
    def _dispatch(self, request: object) -> None:
        if type(request) is not OwnerUiRequestV4:
            return
        if QThread.currentThread() != self._affinity:
            self._endpoint.complete(
                OwnerUiAckV4(request.request_id, False, 0, "AffinityError")
            )
            return
        if not self._endpoint.is_pending(request.request_id):
            return
        ack = self._controller._gui_apply_request(request, self._endpoint)
        self._endpoint.complete(ack)

    @pyqtSlot()
    def _destroyed(self) -> None:
        self._endpoint.close()
        self._controller._gui_unregister(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        window = self._window_ref()
        if watched is window and event.type() == QEvent.Type.Close:
            self._endpoint.close()
            self._controller._gui_unregister(self)
        return False


class _Installation:
    def __init__(self, originals: list[tuple[object, str, object]]) -> None:
        self.originals = originals

    def rollback(self) -> None:
        for owner, name, value in reversed(self.originals):
            setattr(owner, name, value)
        self.originals.clear()


class OnyxLiveActivationV4:
    def __init__(
        self,
        flags: ActivationFlagsV4,
        contract: HostContractV4,
        *,
        authority_factory: Callable[[], object] = provision_owner_authority,
        ui_timeout_seconds: float = 2.0,
    ) -> None:
        if type(flags) is not ActivationFlagsV4:
            raise ActivationV4Error("exact active flags are required")
        if type(contract) is not HostContractV4:
            raise ActivationV4Error("exact preflight contract is required")
        self.flags = flags
        self.contract = contract
        self._authority_factory = authority_factory
        self._ui_timeout_seconds = ui_timeout_seconds
        self._authority: object | None = None
        self._state = ActivationV4State.PREFLIGHTED
        self._failure_type: str | None = None
        self._contact_question: str | None = None
        self._installation: _Installation | None = None
        self._session_counter = 0
        self._pending_binding: tuple[str, str] | None = None
        self._bridges: weakref.WeakKeyDictionary[object, object] = (
            weakref.WeakKeyDictionary()
        )
        self._dispatchers: list[OwnerUiDispatcherV4] = []
        self._endpoints: list[OwnerUiEndpointV4] = []
        self._lock = threading.RLock()
        self._owner_transaction_lock = threading.RLock()

    @property
    def state(self) -> ActivationV4State:
        return self._state

    @property
    def failure_type(self) -> str | None:
        return self._failure_type

    @property
    def pending_binding(self) -> tuple[str, str] | None:
        return self._pending_binding

    def _degrade(self, exc: BaseException) -> None:
        self._failure_type = type(exc).__name__
        self._state = ActivationV4State.DEGRADED

    def start(self) -> ActivationV4State:
        with self._lock:
            if self._state in {ActivationV4State.READY, ActivationV4State.DEGRADED}:
                return self._state
            if self._state is not ActivationV4State.INSTALLED:
                raise ActivationV4Error("host seams must be installed before provisioning")
            try:
                authority = self._authority_factory()
                snapshot = authority.reconcile()
                if not snapshot.reconciled:
                    raise ActivationV4Error("owner reconciliation degraded")
                question = authority.begin_contact()
            except Exception as exc:
                self._authority = None
                self._degrade(exc)
                return self._state
            self._authority = authority
            self._contact_question = question
            self._failure_type = None
            self._state = ActivationV4State.READY
            return self._state

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
                raise ActivationV4Error("Phase 5 binding was not reserved")
            runtime_binding = getattr(bridge, "_binding", None)
            expected_session, expected_trace = self._pending_binding
            if (
                getattr(runtime_binding, "session_id", None) != expected_session
                or getattr(runtime_binding, "trace_id", None) != expected_trace
            ):
                raise ActivationV4Error("Phase 5 bridge binding diverged")
            self._bridges[instance] = bridge
            self._pending_binding = None

    def unbind_phase5(self, instance: object) -> None:
        with self._lock:
            self._bridges.pop(instance, None)
            self._pending_binding = None

    def attach_window(self, window: QObject) -> OwnerUiDispatcherV4:
        if not isinstance(window, self.contract.main_window):
            raise ActivationV4Error("exact MainWindow instance is required")
        if QThread.currentThread() != window.thread():
            raise ActivationV4Error("MainWindow dispatcher requires affinity thread")
        endpoint = OwnerUiEndpointV4(timeout_seconds=self._ui_timeout_seconds)
        dispatcher = OwnerUiDispatcherV4(self, window, endpoint)
        self._dispatchers.append(dispatcher)
        with self._lock:
            self._endpoints.append(endpoint)
        if self._state is ActivationV4State.READY:
            expected = _normalize_address(self.owner_address())
            ack = endpoint.submit(expected)
            durable = _normalize_address(self.owner_address())
            if not ack.applied or durable != expected:
                self._degrade(
                    ActivationV4Error(
                        "new window owner projection did not verify exactly"
                    )
                )
        return dispatcher

    def _gui_unregister(self, dispatcher: OwnerUiDispatcherV4) -> None:
        if dispatcher in self._dispatchers:
            self._dispatchers.remove(dispatcher)
        endpoint = dispatcher._endpoint
        with self._lock:
            if endpoint in self._endpoints:
                self._endpoints.remove(endpoint)

    def _gui_apply_request(
        self, request: OwnerUiRequestV4, endpoint: OwnerUiEndpointV4
    ) -> OwnerUiAckV4:
        """Apply and verify one all-window transaction on the GUI thread."""

        if not endpoint.is_pending(request.request_id):
            return OwnerUiAckV4(request.request_id, False, 0, "Cancelled")
        targets: list[_UiTargetV4] = []
        attempted: list[tuple[_UiTargetV4, str]] = []
        apply_failure: str | None = None
        try:
            for dispatcher in tuple(self._dispatchers):
                window = dispatcher.window
                if window is None or sip.isdeleted(window):
                    raise UiTargetDestroyed("owner window was destroyed")
                if QThread.currentThread() != window.thread():
                    raise ActivationV4Error("window affinity changed")
                projection = getattr(window, "_v5_projection", None)
                if projection is not None:
                    if sip.isdeleted(projection):
                        raise UiTargetDestroyed("projection was destroyed")
                    if QThread.currentThread() != projection.thread():
                        raise ActivationV4Error("projection affinity changed")
                    targets.append(_UiTargetV4(weakref.ref(projection), "projection"))
                overlay = getattr(window, "_overlay", None)
                name_input = getattr(overlay, "_name_input", None)
                if name_input is not None:
                    if sip.isdeleted(name_input):
                        raise UiTargetDestroyed("setup input was destroyed")
                    if QThread.currentThread() != name_input.thread():
                        raise ActivationV4Error("setup input affinity changed")
                    targets.append(_UiTargetV4(weakref.ref(name_input), "setup"))
            if not targets:
                raise ActivationV4Error("no live owner UI target")
            snapshots = [(target, target.read()) for target in targets]
            for target, previous in snapshots:
                if (
                    time.monotonic_ns() >= request.deadline_ns
                    or not endpoint.is_pending(request.request_id)
                ):
                    raise TimeoutError("owner UI request expired")
                attempted.append((target, previous))
                target.write(request.address)
                observed = target.read()
                if observed != request.address:
                    raise UiApplyReadbackMismatch(
                        "owner UI apply readback mismatch"
                    )
                if (
                    time.monotonic_ns() >= request.deadline_ns
                    or not endpoint.is_pending(request.request_id)
                ):
                    raise TimeoutError("owner UI request expired")
            return OwnerUiAckV4(request.request_id, True, len(attempted))
        except Exception as exc:
            apply_failure = type(exc).__name__

        rollback_failures: list[str] = []
        for target, previous in reversed(attempted):
            try:
                target.write(previous)
                if target.read() != previous:
                    raise UiRollbackReadbackMismatch(
                        "owner UI rollback readback mismatch"
                    )
            except Exception as rollback_exc:
                rollback_failures.append(type(rollback_exc).__name__)
        rollback_failure = "+".join(rollback_failures) or None
        return OwnerUiAckV4(
            request.request_id,
            False,
            len(attempted),
            apply_failure,
            rollback_failure,
        )

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

    def _project_owner(self, address: str) -> OwnerUiAckV4:
        with self._lock:
            endpoint = next((item for item in self._endpoints if item is not None), None)
        if endpoint is None:
            return OwnerUiAckV4(0, False, 0, "DispatcherClosed")
        return endpoint.submit(address)

    def _ready_authority(self) -> object:
        if self._state is not ActivationV4State.READY or self._authority is None:
            raise ActivationV4Error("owner identity authority is not writable")
        return self._authority

    @staticmethod
    def _compensate(authority: object, prior_name: str | None) -> None:
        if prior_name is None:
            restored = authority.forget_name()
        else:
            restored = authority.correct_name(prior_name)
        if getattr(restored, "display_name", None) != prior_name:
            raise ActivationV4Error("owner durable compensation diverged")

    def _owner_operation(self, operation: str, value: object = None) -> object:
        with self._owner_transaction_lock:
            return self._owner_operation_locked(operation, value)

    def _owner_operation_locked(self, operation: str, value: object = None) -> object:
        authority = self._ready_authority()
        prior_name = authority.snapshot.display_name
        prior_question = self._contact_question
        try:
            if operation == "set":
                snapshot = authority.set_name(value)
            elif operation == "correct":
                snapshot = authority.correct_name(value)
            elif operation == "forget":
                snapshot = authority.forget_name()
            else:
                raise ActivationV4Error("unknown owner operation")
        except Exception as exc:
            self._degrade(exc)
            raise
        expected = _normalize_address(snapshot.display_name or "Sir")
        ack = self._project_owner(expected)
        durable_matches = (
            authority.snapshot.display_name == snapshot.display_name
            and _normalize_address(authority.snapshot.display_name or "Sir")
            == expected
        )
        if not ack.applied or not durable_matches:
            ui_compensation: OwnerUiAckV4 | None = None
            if ack.applied:
                ui_compensation = self._project_owner(prior_name or "Sir")
            try:
                self._compensate(authority, prior_name)
                self._contact_question = prior_question
            except Exception as compensation_exc:
                self._degrade(compensation_exc)
                raise ActivationV4Error(
                    "owner UI projection and durable compensation failed"
                ) from compensation_exc
            details = [ack.failure_type or "DurableReadbackMismatch"]
            if ack.rollback_failure_type:
                details.append("rollback=" + ack.rollback_failure_type)
            if ui_compensation is not None and not ui_compensation.applied:
                details.append(
                    "ui_compensation="
                    + (ui_compensation.failure_type or "unknown")
                )
            failure = ActivationV4Error("owner transaction failed: " + ";".join(details))
            self._degrade(failure)
            raise failure
        if operation == "set":
            self._contact_question = None
        elif operation == "forget":
            self._contact_question = authority.begin_contact()
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
            raise ActivationV4Error("owner tool request is invalid")
        if name == "forget_owner_name":
            if arguments:
                raise ActivationV4Error("forget accepts no arguments")
            snapshot = self.forget_name()
        else:
            if set(arguments) != {"name"}:
                raise ActivationV4Error("name tool requires exactly name")
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
        """Install eleven real-host seams atomically, restoring all on failure."""

        with self._lock:
            if self._state is not ActivationV4State.PREFLIGHTED:
                raise ActivationV4Error("activation is not in preflighted state")
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
                    raise ActivationV4Error("injected seam installation failure")

            original_prompt = module._load_system_prompt
            original_host_init = host_type.__init__
            original_execute = host_type._execute_tool
            original_stop = host_type._stop_phase5_session
            original_setup = window_type._on_setup_done
            original_window_init = window_type.__init__
            original_window_close = window_type.closeEvent
            controller = self

            def load_owner_name(path=None) -> str:
                return controller.owner_name()

            def load_prompt() -> str:
                return original_prompt() + "\n\n" + controller.owner_prompt_directive()

            def host_init(instance: object, *args: object, **kwargs: object) -> None:
                original_host_init(instance, *args, **kwargs)

            def start_phase5(instance: object) -> None:
                module.set_phase5_authorization_hook(None)
                instance._phase5 = None
                if not module._phase5_requested():
                    if instance._dashboard:
                        instance._dashboard.set_phase5_bridge(None)
                    return
                governance_activation = getattr(
                    type(instance), "_governance_activation_v16", None
                )
                governance_started = False
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
                    phase5_environ = None
                    if governance_activation is not None:
                        phase5_environ = (
                            governance_activation.begin_phase5_session(instance)
                        )
                        governance_started = True
                    session_id, trace_id = controller.next_session_binding()
                    bridge = create_phase5_integration_v3(
                        session_id=session_id,
                        trace_id=trace_id,
                        catalog=catalog,
                        environ=phase5_environ,
                    )
                    if bridge is not None:
                        controller.bind_phase5(instance, bridge)
                        module.set_phase5_authorization_hook(bridge.permission_hook)
                    instance._phase5 = bridge
                    if instance._dashboard:
                        instance._dashboard.set_phase5_bridge(bridge)
                except Exception as exc:
                    if governance_activation is not None and governance_started:
                        governance_activation.abort_phase5_session(
                            instance, "phase5-start-failed"
                        )
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

            def window_init(instance: object, *args: object, **kwargs: object) -> None:
                original_window_init(instance, *args, **kwargs)
                dispatcher = controller.attach_window(instance)
                instance._onyx_owner_ui_dispatcher_v4 = dispatcher

            def window_close(instance: object, event: object) -> None:
                dispatcher = getattr(
                    instance, "_onyx_owner_ui_dispatcher_v4", None
                )
                if dispatcher is not None:
                    dispatcher._endpoint.close()
                    controller._gui_unregister(dispatcher)
                original_window_close(instance, event)

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
                patch(window_type, "__init__", window_init)
                patch(window_type, "closeEvent", window_close)
            except Exception:
                for owner, name, previous in reversed(originals):
                    setattr(owner, name, previous)
                raise
            self._installation = _Installation(originals)
            self._state = ActivationV4State.INSTALLED

    def rollback_installation(self) -> None:
        with self._lock:
            for endpoint in self._endpoints:
                endpoint.close()
            self._endpoints.clear()
            self._dispatchers.clear()
            if self._installation is not None:
                self._installation.rollback()
                self._installation = None
            self._state = ActivationV4State.TERMINATED


def activate_main(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> OnyxLiveActivationV4:
    flags = ActivationFlagsV4.from_canonical_environ(environ)
    contract = preflight_host(module)
    controller = OnyxLiveActivationV4(flags, contract)
    controller.install()
    controller.start()
    module._onyx_live_activation_v4 = controller
    return controller


__all__ = [
    "ActivationFlagsV4",
    "ActivationV4Error",
    "ActivationV4State",
    "CHILD_FLAGS",
    "CONTROL_FLAGS",
    "HUD_FLAG",
    "HostContractV4",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OWNER_PROFILE_FLAG",
    "OWNER_TOOL_DECLARATIONS",
    "OnyxLiveActivationV4",
    "OwnerUiAckV4",
    "OwnerUiDispatcherV4",
    "OwnerUiEndpointV4",
    "OwnerUiRequestV4",
    "PHASE5_FLAGS",
    "UiApplyReadbackMismatch",
    "UiRollbackReadbackMismatch",
    "UiTargetDestroyed",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "owner_journal_path",
    "preflight_host",
    "provision_owner_authority",
]
