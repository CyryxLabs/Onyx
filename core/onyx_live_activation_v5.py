"""Onyx Live Activation V5: provider-resilient wrapper around accepted V4.

V5 does not rewrite the accepted host or V4 bytes.  It first installs the
accepted V4 transition, then atomically adds a small set of provider and setup
seams.  A Gemini Live outage can therefore degrade voice without terminating
the local UI, dashboard, mission worker, or owner/Phase 5 authorities.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import Callable

from core import onyx_live_activation_v4 as v4


LIVE_MASTER_FLAG = "ONYX_LIVE_ACTIVATION_V5"
LIVE_ROLLBACK_FLAG = "ONYX_LIVE_ROLLBACK_V5"
OWNER_PROFILE_FLAG = v4.OWNER_PROFILE_FLAG
HUD_FLAG = v4.HUD_FLAG
PHASE5_FLAGS = v4.PHASE5_FLAGS
CHILD_FLAGS = (OWNER_PROFILE_FLAG, HUD_FLAG, *PHASE5_FLAGS)
CONTROL_FLAGS = (LIVE_MASTER_FLAG, LIVE_ROLLBACK_FLAG, *CHILD_FLAGS)

INPUT_AUDIO_MIME = "audio/pcm;rate=16000"
RECOVERY_COMMANDS = frozenset(
    {
        "recover voice",
        "retry voice",
        "reconnect voice",
        "restore voice",
        "recuperar voz",
        "reconectar voz",
    }
)


class ActivationV5Error(RuntimeError):
    """A V5 transition or provider-supervisor invariant failed."""


class ActivationV5State(str, Enum):
    PREFLIGHTED = "preflighted"
    INSTALLED = "installed"
    READY = "ready"
    DEGRADED = "degraded"
    TERMINATED = "terminated"


class ProviderCircuitState(str, Enum):
    CLOSED = "closed"
    DEGRADED = "degraded"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProviderFaultKind(str, Enum):
    AUDIO_CONTRACT = "audio_contract"
    UNAVAILABLE = "unavailable"
    NETWORK = "network"
    CREDENTIAL = "credential"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ActivationFlagsV5:
    master: bool
    owner_profile: bool
    hud_v5: bool
    phase5: tuple[bool, ...]

    def __post_init__(self) -> None:
        values = (self.master, self.owner_profile, self.hud_v5, *self.phase5)
        if any(type(value) is not bool for value in values):
            raise ActivationV5Error("activation flags must be exact booleans")
        if type(self.phase5) is not tuple or len(self.phase5) != len(PHASE5_FLAGS):
            raise ActivationV5Error("Phase 5 flag set is incomplete")
        if not (self.master and self.owner_profile and self.hud_v5 and all(self.phase5)):
            raise ActivationV5Error("complete active V5 flags are required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV5":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV5Error("rollback is not an active configuration")
        for name in (LIVE_MASTER_FLAG, *CHILD_FLAGS):
            if source.get(name) != "1":
                raise ActivationV5Error("activation environment is not canonical")
        return cls(True, True, True, (True,) * len(PHASE5_FLAGS))


def exact_activation_environment() -> dict[str, str]:
    result = v4.exact_activation_environment()
    result.pop(v4.LIVE_MASTER_FLAG, None)
    result[LIVE_MASTER_FLAG] = "1"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


@dataclass(frozen=True, slots=True)
class HostContractV5:
    module: ModuleType
    onyx_live: type
    ui_module: ModuleType
    main_window: type
    base: v4.HostContractV4


def _exact_function(owner: object, name: str) -> object:
    namespace = getattr(owner, "__dict__", None)
    if namespace is None or name not in namespace or not inspect.isfunction(namespace[name]):
        raise ActivationV5Error(f"required host seam is absent: {name}")
    return namespace[name]


def preflight_host(module: ModuleType) -> HostContractV5:
    base = v4.preflight_host(module)
    for name in (
        "_send_realtime",
        "_run_live_loop",
        "_on_text_command",
        "_process_dashboard_commands",
    ):
        _exact_function(base.onyx_live, name)
    _exact_function(base.main_window, "_show_setup")
    if getattr(module, "SEND_SAMPLE_RATE", None) != 16_000:
        raise ActivationV5Error("host input audio rate diverged from accepted contract")
    if not callable(getattr(getattr(module, "genai", None), "Client", None)):
        raise ActivationV5Error("Gemini client seam is unavailable")
    return HostContractV5(
        module, base.onyx_live, base.ui_module, base.main_window, base
    )


def _leaf_messages(exc: BaseException) -> tuple[str, ...]:
    nested = getattr(exc, "exceptions", None)
    if isinstance(nested, tuple):
        values: list[str] = []
        for child in nested:
            if isinstance(child, BaseException):
                values.extend(_leaf_messages(child))
        return tuple(values) or (str(exc),)
    return (str(exc),)


def classify_provider_fault(exc: BaseException) -> ProviderFaultKind:
    text = " | ".join(_leaf_messages(exc)).casefold()
    if any(
        marker in text
        for marker in ("api key not valid", "api_key_invalid", "invalid api key")
    ):
        return ProviderFaultKind.CREDENTIAL
    if "audio content type" in text or "content_type_audio" in text:
        return ProviderFaultKind.AUDIO_CONTRACT
    if "1011" in text or "service unavailable" in text or "temporarily unavailable" in text:
        return ProviderFaultKind.UNAVAILABLE
    if any(
        marker in text
        for marker in (
            "timeouterror",
            "timed out",
            "getaddrinfo",
            "connectionrefusederror",
            "cannot connect",
            "connection reset",
            "network",
        )
    ):
        return ProviderFaultKind.NETWORK
    return ProviderFaultKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class ProviderCircuitSnapshotV5:
    state: ProviderCircuitState
    consecutive_failures: int
    attempts: int
    recoveries: int
    last_fault: ProviderFaultKind | None


class ProviderCircuitBreakerV5:
    """Deterministic bounded-backoff breaker; it never owns host lifecycle."""

    def __init__(
        self,
        *,
        retry_delays: tuple[float, ...] = (1.0, 3.0, 10.0, 30.0),
        open_after: int = 2,
        open_cooldown: float = 30.0,
    ) -> None:
        if (
            not retry_delays
            or any(type(value) not in (int, float) or value < 0 for value in retry_delays)
            or type(open_after) is not int
            or open_after < 1
            or type(open_cooldown) not in (int, float)
            or open_cooldown < 0
        ):
            raise ActivationV5Error("provider circuit configuration is invalid")
        self._delays = tuple(float(value) for value in retry_delays)
        self._open_after = open_after
        self._open_cooldown = float(open_cooldown)
        self._state = ProviderCircuitState.CLOSED
        self._failures = 0
        self._attempts = 0
        self._recoveries = 0
        self._last_fault: ProviderFaultKind | None = None

    @property
    def snapshot(self) -> ProviderCircuitSnapshotV5:
        return ProviderCircuitSnapshotV5(
            self._state,
            self._failures,
            self._attempts,
            self._recoveries,
            self._last_fault,
        )

    def begin_attempt(self) -> None:
        self._attempts += 1
        if self._state is ProviderCircuitState.OPEN:
            self._state = ProviderCircuitState.HALF_OPEN

    def record_failure(self, fault: ProviderFaultKind) -> float:
        self._last_fault = fault
        self._failures += 1
        if self._failures >= self._open_after:
            self._state = ProviderCircuitState.OPEN
            return self._open_cooldown
        self._state = ProviderCircuitState.DEGRADED
        return self._delays[min(self._failures - 1, len(self._delays) - 1)]

    def record_stable(self) -> None:
        if self._failures or self._state is not ProviderCircuitState.CLOSED:
            self._recoveries += 1
        self._failures = 0
        self._last_fault = None
        self._state = ProviderCircuitState.CLOSED

    def manual_recovery(self) -> None:
        if self._state is ProviderCircuitState.OPEN:
            self._state = ProviderCircuitState.HALF_OPEN


class _Installation:
    def __init__(
        self,
        base: v4.OnyxLiveActivationV4,
        originals: list[tuple[object, str, object]],
    ) -> None:
        self.base = base
        self.originals = originals

    def rollback(self) -> None:
        for owner, name, value in reversed(self.originals):
            setattr(owner, name, value)
        self.originals.clear()
        self.base.rollback_installation()


class OnyxLiveActivationV5:
    """Accepted V4 plus seven isolated provider/setup containment seams."""

    BASE_SEAM_COUNT = 11
    V5_SEAM_COUNT = 7
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V5_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV5,
        contract: HostContractV5,
        *,
        authority_factory: Callable[[], object] = v4.provision_owner_authority,
        ui_timeout_seconds: float = 2.0,
        circuit_factory: Callable[[], ProviderCircuitBreakerV5] = ProviderCircuitBreakerV5,
    ) -> None:
        if type(flags) is not ActivationFlagsV5 or type(contract) is not HostContractV5:
            raise ActivationV5Error("exact V5 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v4.OnyxLiveActivationV4(
            v4.ActivationFlagsV4(True, True, True, (True,) * len(PHASE5_FLAGS)),
            contract.base,
            authority_factory=authority_factory,
            ui_timeout_seconds=ui_timeout_seconds,
        )
        self._circuit_factory = circuit_factory
        self._installation: _Installation | None = None
        self._state = ActivationV5State.PREFLIGHTED
        self._lock = threading.RLock()

    @property
    def state(self) -> ActivationV5State:
        return self._state

    @property
    def failure_type(self) -> str | None:
        return self._base.failure_type

    @property
    def pending_binding(self) -> tuple[str, str] | None:
        return self._base.pending_binding

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    @staticmethod
    def _normalise_recovery_command(value: object) -> str:
        return " ".join(str(value).casefold().split())

    def request_provider_recovery(self, instance: object) -> bool:
        event = getattr(instance, "_onyx_v5_recovery_event", None)
        loop = getattr(instance, "_loop", None)
        circuit = getattr(instance, "_onyx_v5_provider_circuit", None)
        if circuit is not None:
            circuit.manual_recovery()
        if event is None or loop is None or loop.is_closed():
            return False
        loop.call_soon_threadsafe(event.set)
        return True

    @staticmethod
    def _tool_cache(instance: object) -> OrderedDict[tuple[str, str], object]:
        cache = getattr(instance, "_onyx_v5_tool_cache", None)
        if not isinstance(cache, OrderedDict):
            cache = OrderedDict()
            instance._onyx_v5_tool_cache = cache
        return cache

    async def _wait_for_retry(self, instance: object, delay: float) -> None:
        event = instance._onyx_v5_recovery_event
        try:
            await asyncio.wait_for(event.wait(), timeout=max(0.0, delay))
            event.clear()
            circuit = instance._onyx_v5_provider_circuit
            circuit.manual_recovery()
            instance.ui.write_log("SYS: Manual voice recovery requested.")
        except asyncio.TimeoutError:
            pass

    async def _broadcast_status(
        self, instance: object, state: str, **details: object
    ) -> None:
        dashboard = getattr(instance, "_dashboard", None)
        if dashboard is None:
            return
        with contextlib.suppress(Exception):
            await dashboard.broadcast({"type": "status", "state": state, **details})

    async def _run_provider_loop(self, instance: object) -> None:
        module = self.contract.module
        circuit = instance._onyx_v5_provider_circuit
        stable_seconds = float(getattr(instance, "_onyx_v5_stable_seconds", 30.0))

        async def mark_stable(expected_session: object) -> None:
            await asyncio.sleep(max(0.0, stable_seconds))
            if instance.session is not expected_session:
                return
            prior = circuit.snapshot
            circuit.record_stable()
            if prior.state is not ProviderCircuitState.CLOSED:
                instance.ui.write_log(
                    "SYS: Gemini Live voice recovered; provider circuit closed."
                )
                await self._broadcast_status(
                    instance, "active", voice="online", circuit="closed"
                )

        while True:
            circuit.begin_attempt()
            connected_at: float | None = None
            try:
                print("[Onyx V5] Connecting voice provider...")
                instance.ui.set_state("THINKING")
                instance._start_phase5_session()
                config = instance._build_config()
                factory = getattr(instance, "_onyx_v5_client_factory", None)
                client = (
                    factory()
                    if callable(factory)
                    else module.genai.Client(
                        api_key=module._get_api_key(),
                        http_options={"api_version": "v1beta"},
                    )
                )
                async with (
                    client.aio.live.connect(
                        model=module.resolve_live_model(module.API_CONFIG_PATH),
                        config=config,
                    ) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    instance.session = session
                    instance.audio_in_queue = asyncio.Queue()
                    instance.out_queue = asyncio.Queue(maxsize=200)
                    instance._turn_done_event = asyncio.Event()
                    instance._pending_vision = None
                    instance._vision_cam_active = False
                    instance._vision_close_pending = False
                    instance._vision_busy = False
                    instance._vision_last_time = 0.0
                    instance._interrupted = False
                    connected_at = time.monotonic()
                    instance.ui.set_state("LISTENING")
                    instance.ui.write_log("SYS: Onyx voice online.")
                    await self._broadcast_status(instance, "active", voice="online")

                    tg.create_task(instance._send_realtime())
                    tg.create_task(instance._listen_audio())
                    tg.create_task(instance._receive_audio())
                    tg.create_task(instance._play_audio())
                    tg.create_task(mark_stable(session))
                    if instance._dashboard:
                        tg.create_task(instance._relay_phone_audio())
                    if instance._onyx_v5_startup_briefing and not instance._briefing_sent:
                        instance._briefing_sent = True
                        tg.create_task(instance._send_startup_briefing())
                raise RuntimeError("Gemini Live session ended unexpectedly")
            except asyncio.CancelledError:
                raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as exc:
                fault = classify_provider_fault(exc)
                duration = 0.0 if connected_at is None else time.monotonic() - connected_at
                if duration >= stable_seconds:
                    circuit.record_stable()
                delay = circuit.record_failure(fault)
                snapshot = circuit.snapshot
                print(
                    f"[Onyx V5] Voice degraded ({fault.value}, "
                    f"circuit={snapshot.state.value}, retry={delay:.1f}s): {exc}"
                )
                instance.ui.set_state("ERROR")
                if fault is ProviderFaultKind.CREDENTIAL:
                    instance.ui.write_log(
                        "ERR: Gemini credential was rejected. Local Onyx remains online; "
                        "update the credential to recover voice."
                    )
                    instance.ui.prompt_reconfig()
                else:
                    instance.ui.write_log(
                        "VOICE DEGRADED: Gemini Live is unavailable "
                        f"({fault.value}). Local HUD, dashboard and missions remain online; "
                        f"automatic retry in {delay:.0f}s or type 'recover voice'."
                    )
                await self._broadcast_status(
                    instance,
                    "degraded",
                    voice="offline",
                    fault=fault.value,
                    circuit=snapshot.state.value,
                )
            finally:
                instance.session = None
                instance._stop_phase5_session("provider-reconnect")
                instance.set_speaking(False)

            await self._wait_for_retry(instance, delay)

    async def _run_live_loop(self, instance: object) -> None:
        module = self.contract.module
        instance._loop = asyncio.get_running_loop()
        instance._onyx_v5_recovery_event = asyncio.Event()
        instance._onyx_v5_provider_circuit = self._circuit_factory()
        (
            startup_briefing_enabled,
            proactive_enabled,
            trust_profile,
            autonomy_enabled,
            autonomy_roots,
        ) = module._load_launch_flags()
        instance._onyx_v5_startup_briefing = startup_briefing_enabled
        module.set_trust_profile(trust_profile)
        module.configure_owner_autonomy(autonomy_enabled, autonomy_roots)
        autonomy_status = (
            "ON" if trust_profile == "autonomous" and autonomy_enabled else "OFF"
        )
        instance.ui.write_log(
            f"SYS: OWNER AUTONOMY {autonomy_status} ({trust_profile})."
        )

        persistent_tasks: list[asyncio.Task[object]] = []
        try:
            if instance._dashboard is None:
                try:
                    dashboard_factory = getattr(
                        instance, "_onyx_v5_dashboard_factory", None
                    )
                    if callable(dashboard_factory):
                        instance._dashboard = dashboard_factory()
                    else:
                        from dashboard.server import DashboardServer

                        instance._dashboard = DashboardServer(
                            phase5_enabled=module._phase5_dashboard_requested()
                        )
                    instance._dashboard.set_connect_callback(instance._on_phone_connected)
                    persistent_tasks.append(
                        asyncio.create_task(instance._dashboard.serve())
                    )
                    persistent_tasks.append(
                        asyncio.create_task(instance._process_dashboard_commands())
                    )
                except Exception as exc:
                    print(f"[Dashboard] Disabled: {exc}")
                    instance._dashboard = None
            if proactive_enabled:
                persistent_tasks.append(
                    asyncio.create_task(instance._run_proactive_mode())
                )
            persistent_tasks.append(asyncio.create_task(instance._run_system_monitor()))
            await self._run_provider_loop(instance)
        finally:
            for task in persistent_tasks:
                task.cancel()
            if persistent_tasks:
                await asyncio.gather(*persistent_tasks, return_exceptions=True)

    def install(self, *, fail_after: int | None = None) -> None:
        with self._lock:
            if self._state is not ActivationV5State.PREFLIGHTED:
                raise ActivationV5Error("activation is not in preflighted state")
            if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
                raise ActivationV5Error("seam failpoint is outside V5 installation")
            base_failpoint = fail_after if fail_after and fail_after <= 11 else None
            self._base.install(fail_after=base_failpoint)

            host_type = self.contract.onyx_live
            window_type = self.contract.main_window
            module = self.contract.module
            originals: list[tuple[object, str, object]] = []
            writes = self.BASE_SEAM_COUNT

            def patch(owner: object, name: str, value: object) -> None:
                nonlocal writes
                previous = getattr(owner, name)
                setattr(owner, name, value)
                originals.append((owner, name, previous))
                writes += 1
                if fail_after is not None and writes >= fail_after:
                    raise ActivationV5Error("injected V5 seam installation failure")

            original_execute = host_type._execute_tool
            original_text = host_type._on_text_command
            original_show_setup = window_type._show_setup
            original_setup_done = window_type._on_setup_done
            controller = self

            async def execute_tool(instance: object, fc: object) -> object:
                call_id = str(getattr(fc, "id", "") or "")
                name = str(getattr(fc, "name", "") or "")
                if not call_id:
                    return await original_execute(instance, fc)
                key = (call_id, name)
                cache = controller._tool_cache(instance)
                if key in cache:
                    cache.move_to_end(key)
                    instance.ui.write_log(
                        f"SYS: Duplicate provider tool call suppressed ({name})."
                    )
                    return cache[key]
                inflight = getattr(instance, "_onyx_v5_tool_inflight", None)
                if not isinstance(inflight, dict):
                    inflight = {}
                    instance._onyx_v5_tool_inflight = inflight
                task = inflight.get(key)
                if task is None:
                    task = asyncio.create_task(original_execute(instance, fc))
                    inflight[key] = task
                try:
                    response = await asyncio.shield(task)
                finally:
                    if task.done() and inflight.get(key) is task:
                        inflight.pop(key, None)
                if task.done() and not task.cancelled() and task.exception() is None:
                    cache[key] = response
                    cache.move_to_end(key)
                return response

            async def send_realtime(instance: object) -> None:
                while True:
                    message = await instance.out_queue.get()
                    if isinstance(message, Mapping):
                        mime = str(message.get("mime_type", "")).casefold()
                        if mime.startswith("audio/pcm"):
                            message = dict(message)
                            message["mime_type"] = (
                                f"audio/pcm;rate={module.SEND_SAMPLE_RATE}"
                            )
                    await instance.session.send_realtime_input(media=message)

            def on_text_command(instance: object, text: str) -> None:
                command = controller._normalise_recovery_command(text)
                if command in RECOVERY_COMMANDS:
                    if controller.request_provider_recovery(instance):
                        instance.ui.write_log("SYS: Voice recovery queued.")
                    else:
                        instance.ui.write_log(
                            "VOICE DEGRADED: recovery will be available when runtime starts."
                        )
                    return
                if not getattr(instance, "session", None):
                    instance.ui.write_log(
                        "VOICE DEGRADED: command was not sent or replayed; "
                        "local Onyx remains online."
                    )
                    return
                original_text(instance, text)

            async def process_dashboard_commands(instance: object) -> None:
                while True:
                    try:
                        text = await asyncio.wait_for(
                            instance._dashboard._command_queue.get(), timeout=0.5
                        )
                        if not text:
                            continue
                        command = controller._normalise_recovery_command(text)
                        if command in RECOVERY_COMMANDS:
                            controller.request_provider_recovery(instance)
                            instance.ui.write_log("[Web]: Voice recovery requested.")
                        elif instance.session:
                            await instance.session.send_client_content(
                                turns={"parts": [{"text": text}]},
                                turn_complete=True,
                            )
                            instance.ui.write_log(f"[Web]: {text}")
                        else:
                            instance.ui.write_log(
                                "[Web] VOICE DEGRADED: command refused without replay."
                            )
                            await controller._broadcast_status(
                                instance,
                                "degraded",
                                voice="offline",
                                command="not_replayed",
                            )
                    except asyncio.TimeoutError:
                        pass
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        print(f"[Dashboard] Command error: {exc}")
                        await asyncio.sleep(0.5)

            async def run_live_loop(instance: object) -> None:
                await controller._run_live_loop(instance)

            def show_setup(window: object) -> None:
                overlay = getattr(window, "_overlay", None)
                if overlay is not None and overlay.isVisible():
                    overlay.raise_()
                    overlay.activateWindow()
                    return
                host = getattr(window, "_v5_host", None)
                if getattr(window, "_hud_v5_live", False) and host is not None:
                    host.suspend()
                original_show_setup(window)
                overlay = getattr(window, "_overlay", None)
                if overlay is not None:
                    overlay.raise_()

            def setup_done(
                window: object, key: str, os_name: str, owner_name: str = ""
            ) -> None:
                original_setup_done(window, key, os_name, owner_name)
                if not getattr(window, "_ready", False) or getattr(window, "_overlay", None):
                    return
                host = getattr(window, "_v5_host", None)
                if getattr(window, "_hud_v5_live", False) and host is not None:
                    host.load_source()
                    host.show()
                    host.sync_animation()

            try:
                patch(host_type, "_execute_tool", execute_tool)
                patch(host_type, "_send_realtime", send_realtime)
                patch(host_type, "_on_text_command", on_text_command)
                patch(host_type, "_process_dashboard_commands", process_dashboard_commands)
                patch(host_type, "_run_live_loop", run_live_loop)
                patch(window_type, "_show_setup", show_setup)
                patch(window_type, "_on_setup_done", setup_done)
            except Exception:
                for owner, name, previous in reversed(originals):
                    setattr(owner, name, previous)
                self._base.rollback_installation()
                raise
            self._installation = _Installation(self._base, originals)
            self._state = ActivationV5State.INSTALLED

    def start(self) -> ActivationV5State:
        if self._state is not ActivationV5State.INSTALLED:
            raise ActivationV5Error("host seams must be installed before provisioning")
        observed = self._base.start()
        self._state = ActivationV5State(observed.value)
        return self._state

    def rollback_installation(self) -> None:
        with self._lock:
            if self._installation is not None:
                self._installation.rollback()
                self._installation = None
            elif self._base.state is not v4.ActivationV4State.TERMINATED:
                self._base.rollback_installation()
            self._state = ActivationV5State.TERMINATED


def activate_main(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> OnyxLiveActivationV5:
    flags = ActivationFlagsV5.from_canonical_environ(environ)
    controller = OnyxLiveActivationV5(flags, preflight_host(module))
    controller.install()
    controller.start()
    module._onyx_live_activation_v5 = controller
    return controller


__all__ = [
    "ActivationFlagsV5",
    "ActivationV5Error",
    "ActivationV5State",
    "CHILD_FLAGS",
    "CONTROL_FLAGS",
    "HUD_FLAG",
    "HostContractV5",
    "INPUT_AUDIO_MIME",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV5",
    "PHASE5_FLAGS",
    "ProviderCircuitBreakerV5",
    "ProviderCircuitSnapshotV5",
    "ProviderCircuitState",
    "ProviderFaultKind",
    "RECOVERY_COMMANDS",
    "activate_main",
    "classify_provider_fault",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
]
