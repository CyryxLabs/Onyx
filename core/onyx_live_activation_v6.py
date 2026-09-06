"""Onyx Live Activation V6: bounded replay identity and loop-owned recovery.

V6 composes the preserved V5 candidate for its accepted MIME, provider-lifetime,
and single-setup seams, then atomically replaces the four seams whose contracts
were rejected.  V1-V5 bytes remain untouched.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import inspect
import json
import math
import os
import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import Any

from core import onyx_live_activation_v5 as v5


LIVE_MASTER_FLAG = "ONYX_LIVE_ACTIVATION_V6"
LIVE_ROLLBACK_FLAG = "ONYX_LIVE_ROLLBACK_V6"
OWNER_PROFILE_FLAG = v5.OWNER_PROFILE_FLAG
HUD_FLAG = v5.HUD_FLAG
PHASE5_FLAGS = v5.PHASE5_FLAGS
CHILD_FLAGS = (OWNER_PROFILE_FLAG, HUD_FLAG, *PHASE5_FLAGS)
CONTROL_FLAGS = (LIVE_MASTER_FLAG, LIVE_ROLLBACK_FLAG, *CHILD_FLAGS)
INPUT_AUDIO_MIME = v5.INPUT_AUDIO_MIME
RECOVERY_COMMANDS = v5.RECOVERY_COMMANDS

REPLAY_WINDOW_SIZE = 256
MAX_RETRY_DELAY_SECONDS = 300.0
MAX_OPEN_COOLDOWN_SECONDS = 900.0
MAX_JITTER_SECONDS = 30.0
MAX_STABLE_CLOSE_SECONDS = 900.0
MAX_OPEN_AFTER = 64


class ActivationV6Error(RuntimeError):
    """A V6 transition invariant failed."""


class ToolIdentityConflictV6(ActivationV6Error):
    """A provider reused a call ID with a different bound identity."""


class ToolReplayWindowFullV6(ActivationV6Error):
    """Every replay-window slot is inflight, so a new call fails closed."""


class ToolExecutionReplayV6(ActivationV6Error):
    """An immutable cached tool failure was replayed without re-execution."""


class CircuitLoopAffinityV6(ActivationV6Error):
    """A circuit transition was attempted outside its owning event loop."""


class ActivationV6State(str, Enum):
    PREFLIGHTED = "preflighted"
    INSTALLED = "installed"
    READY = "ready"
    DEGRADED = "degraded"
    TERMINATED = "terminated"


class ProviderCircuitStateV6(str, Enum):
    CLOSED = "closed"
    DEGRADED = "degraded"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class ActivationFlagsV6:
    master: bool
    owner_profile: bool
    hud_v5: bool
    phase5: tuple[bool, ...]

    def __post_init__(self) -> None:
        if type(self.phase5) is not tuple or len(self.phase5) != len(PHASE5_FLAGS):
            raise ActivationV6Error("Phase 5 flag set is incomplete")
        values = (self.master, self.owner_profile, self.hud_v5, *self.phase5)
        if any(type(value) is not bool for value in values):
            raise ActivationV6Error("activation flags must be exact booleans")
        if not all(values):
            raise ActivationV6Error("complete active V6 flags are required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV6":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV6Error("rollback is not an active configuration")
        for name in (LIVE_MASTER_FLAG, *CHILD_FLAGS):
            if source.get(name) != "1":
                raise ActivationV6Error("activation environment is not canonical")
        return cls(True, True, True, (True,) * len(PHASE5_FLAGS))


def exact_activation_environment() -> dict[str, str]:
    result = v5.exact_activation_environment()
    result.pop(v5.LIVE_MASTER_FLAG, None)
    result[LIVE_MASTER_FLAG] = "1"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


@dataclass(frozen=True, slots=True)
class HostContractV6:
    module: ModuleType
    onyx_live: type
    ui_module: ModuleType
    main_window: type
    base: v5.HostContractV5


def _exact_function(owner: object, name: str) -> object:
    namespace = getattr(owner, "__dict__", None)
    if namespace is None or name not in namespace or not inspect.isfunction(namespace[name]):
        raise ActivationV6Error(f"required host seam is absent: {name}")
    return namespace[name]


def preflight_host(module: ModuleType) -> HostContractV6:
    base = v5.preflight_host(module)
    for name in (
        "_execute_tool",
        "_on_text_command",
        "_process_dashboard_commands",
        "_run_live_loop",
    ):
        _exact_function(base.onyx_live, name)
    return HostContractV6(
        module, base.onyx_live, base.ui_module, base.main_window, base
    )


def _positive_finite_number(name: str, value: object, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ActivationV6Error(f"{name} must be an exact int or float")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ActivationV6Error(f"{name} is not a finite number") from exc
    if not math.isfinite(number) or number <= 0 or number > maximum:
        raise ActivationV6Error(f"{name} is outside its finite positive bound")
    return number


def _bounded_positive_int(name: str, value: object, maximum: int) -> int:
    if type(value) is not int or value <= 0 or value > maximum:
        raise ActivationV6Error(f"{name} must be an exact bounded positive int")
    return value


def _canonical_value(value: object) -> object:
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ActivationV6Error("tool arguments contain a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ActivationV6Error("tool argument keys must be exact strings")
            result[key] = _canonical_value(item)
        return result
    if type(value) in (list, tuple):
        return [_canonical_value(item) for item in value]
    raise ActivationV6Error("tool arguments are not canonical JSON values")


def canonical_arguments_digest(arguments: Mapping[str, object]) -> str:
    if not isinstance(arguments, Mapping):
        raise ActivationV6Error("tool arguments must be a mapping")
    canonical = _canonical_value(arguments)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolFailureV6:
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class ToolOutcomeV6:
    value: object | None = None
    value_digest: str | None = None
    failure: ToolFailureV6 | None = None


@dataclass(slots=True)
class _ToolCallRecordV6:
    name: str
    arguments_digest: str
    task: asyncio.Task[ToolOutcomeV6]
    outcome: ToolOutcomeV6 | None = None


@dataclass(frozen=True, slots=True)
class ToolRegistrySnapshotV6:
    retained: int
    inflight: int
    completed: int
    capacity: int
    evictions: int
    conflicts: int


class ToolCallRegistryV6:
    """Exact-ID, single-flight replay window with bounded LRU tombstones."""

    def __init__(self, *, capacity: int = REPLAY_WINDOW_SIZE) -> None:
        self._capacity = _bounded_positive_int("tool replay capacity", capacity, 256)
        self._records: OrderedDict[str, _ToolCallRecordV6] = OrderedDict()
        self._lock: asyncio.Lock | None = None
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._evictions = 0
        self._conflicts = 0

    def _bind_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._owner_loop is None:
            self._owner_loop = loop
            self._lock = asyncio.Lock()
        elif self._owner_loop is not loop:
            raise CircuitLoopAffinityV6("tool registry event-loop affinity changed")
        assert self._lock is not None
        return self._lock

    def _evict_settled_lru(self) -> bool:
        for call_id, record in tuple(self._records.items()):
            if record.outcome is not None:
                self._records.pop(call_id)
                self._evictions += 1
                return True
        return False

    async def _run_and_finalize(
        self,
        call_id: str,
        runner: Callable[[], Awaitable[object]],
    ) -> ToolOutcomeV6:
        try:
            prototype = copy.deepcopy(await runner())
            outcome = ToolOutcomeV6(
                value=prototype,
                value_digest=self._result_digest(prototype),
            )
        except asyncio.CancelledError as exc:
            outcome = ToolOutcomeV6(
                failure=ToolFailureV6(type(exc).__name__, str(exc)[:500])
            )
        except Exception as exc:
            outcome = ToolOutcomeV6(
                failure=ToolFailureV6(type(exc).__name__, str(exc)[:500])
            )
        lock = self._bind_loop()
        async with lock:
            record = self._records.get(call_id)
            if record is not None:
                record.outcome = outcome
                self._records.move_to_end(call_id)
        return outcome

    @staticmethod
    def _result_digest(value: object) -> str:
        if callable(getattr(value, "model_dump", None)):
            payload = {
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
                "value": value.model_dump(mode="json"),
            }
        else:
            payload = _canonical_value(value)
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _materialize(cls, outcome: ToolOutcomeV6) -> object:
        if outcome.failure is not None:
            raise ToolExecutionReplayV6(
                f"{outcome.failure.error_type}: {outcome.failure.message}"
            )
        clone = copy.deepcopy(outcome.value)
        if outcome.value_digest is None or cls._result_digest(clone) != outcome.value_digest:
            raise ActivationV6Error("cached tool result integrity diverged")
        return clone

    async def execute(
        self,
        *,
        call_id: object,
        name: object,
        arguments: Mapping[str, object],
        runner: Callable[[], Awaitable[object]],
    ) -> object:
        if type(call_id) is not str or not call_id or len(call_id) > 512:
            raise ActivationV6Error("tool call_id must be an exact non-empty string")
        if type(name) is not str or not name or len(name) > 256:
            raise ActivationV6Error("tool name must be an exact non-empty string")
        digest = canonical_arguments_digest(arguments)
        lock = self._bind_loop()
        async with lock:
            record = self._records.get(call_id)
            if record is not None:
                if record.name != name or record.arguments_digest != digest:
                    self._conflicts += 1
                    raise ToolIdentityConflictV6(
                        "tool call_id was reused with a different name or arguments"
                    )
                self._records.move_to_end(call_id)
                if record.outcome is not None:
                    return self._materialize(record.outcome)
                task = record.task
            else:
                if len(self._records) >= self._capacity and not self._evict_settled_lru():
                    raise ToolReplayWindowFullV6(
                        "tool replay window is full of inflight calls"
                    )
                task = asyncio.create_task(self._run_and_finalize(call_id, runner))
                self._records[call_id] = _ToolCallRecordV6(name, digest, task)
        outcome = await asyncio.shield(task)
        return self._materialize(outcome)

    async def snapshot(self) -> ToolRegistrySnapshotV6:
        lock = self._bind_loop()
        async with lock:
            inflight = sum(record.outcome is None for record in self._records.values())
            return ToolRegistrySnapshotV6(
                retained=len(self._records),
                inflight=inflight,
                completed=len(self._records) - inflight,
                capacity=self._capacity,
                evictions=self._evictions,
                conflicts=self._conflicts,
            )


@dataclass(frozen=True, slots=True)
class ProviderCircuitSnapshotV6:
    state: ProviderCircuitStateV6
    consecutive_failures: int
    attempts: int
    recoveries: int
    last_fault: v5.ProviderFaultKind | None


@dataclass(frozen=True, slots=True)
class RetryDecisionV6:
    delay_seconds: float
    snapshot: ProviderCircuitSnapshotV6


@dataclass(frozen=True, slots=True)
class RecoveryAckV6:
    accepted: bool
    state: ProviderCircuitStateV6
    sequence: int


class ProviderCircuitBreakerV6:
    """Every state transition is serialized on one owning asyncio loop."""

    def __init__(
        self,
        *,
        retry_delays: tuple[float, ...] = (1.0, 3.0, 10.0, 30.0),
        open_after: int = 2,
        open_cooldown: float = 30.0,
        jitter_seconds: float = 0.25,
        stable_close_seconds: float = 30.0,
        jitter_source: Callable[[], float] | None = None,
    ) -> None:
        if type(retry_delays) is not tuple or not retry_delays:
            raise ActivationV6Error("retry_delays must be a non-empty exact tuple")
        self._delays = tuple(
            _positive_finite_number(
                f"retry_delays[{index}]", value, MAX_RETRY_DELAY_SECONDS
            )
            for index, value in enumerate(retry_delays)
        )
        self._open_after = _bounded_positive_int(
            "open_after", open_after, MAX_OPEN_AFTER
        )
        self._open_cooldown = _positive_finite_number(
            "open_cooldown", open_cooldown, MAX_OPEN_COOLDOWN_SECONDS
        )
        self._jitter_seconds = _positive_finite_number(
            "jitter_seconds", jitter_seconds, MAX_JITTER_SECONDS
        )
        self._stable_close_seconds = _positive_finite_number(
            "stable_close_seconds",
            stable_close_seconds,
            MAX_STABLE_CLOSE_SECONDS,
        )
        self._jitter_source = jitter_source or (lambda: 0.5)
        if not callable(self._jitter_source):
            raise ActivationV6Error("jitter_source must be callable")
        self._state = ProviderCircuitStateV6.CLOSED
        self._failures = 0
        self._attempts = 0
        self._recoveries = 0
        self._last_fault: v5.ProviderFaultKind | None = None
        self._sequence = 0
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None

    @property
    def stable_close_seconds(self) -> float:
        return self._stable_close_seconds

    def _bind_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._owner_loop is None:
            self._owner_loop = loop
            self._lock = asyncio.Lock()
        elif self._owner_loop is not loop:
            raise CircuitLoopAffinityV6("provider circuit event-loop affinity changed")
        assert self._lock is not None
        return self._lock

    def _snapshot_unlocked(self) -> ProviderCircuitSnapshotV6:
        return ProviderCircuitSnapshotV6(
            self._state,
            self._failures,
            self._attempts,
            self._recoveries,
            self._last_fault,
        )

    async def bind_owner_loop(self) -> None:
        lock = self._bind_loop()
        async with lock:
            return None

    async def snapshot(self) -> ProviderCircuitSnapshotV6:
        lock = self._bind_loop()
        async with lock:
            return self._snapshot_unlocked()

    async def begin_attempt(self) -> ProviderCircuitSnapshotV6:
        lock = self._bind_loop()
        async with lock:
            self._attempts += 1
            self._sequence += 1
            if self._state is ProviderCircuitStateV6.OPEN:
                self._state = ProviderCircuitStateV6.HALF_OPEN
            return self._snapshot_unlocked()

    async def record_failure(
        self, fault: v5.ProviderFaultKind
    ) -> RetryDecisionV6:
        if type(fault) is not v5.ProviderFaultKind:
            raise ActivationV6Error("provider fault kind is invalid")
        lock = self._bind_loop()
        async with lock:
            sample = self._jitter_source()
            if (
                type(sample) not in (int, float)
                or not math.isfinite(float(sample))
                or not 0 <= float(sample) <= 1
            ):
                raise ActivationV6Error("jitter source returned an invalid sample")
            self._last_fault = fault
            self._failures += 1
            self._sequence += 1
            if self._failures >= self._open_after:
                self._state = ProviderCircuitStateV6.OPEN
                base = self._open_cooldown
            else:
                self._state = ProviderCircuitStateV6.DEGRADED
                base = self._delays[min(self._failures - 1, len(self._delays) - 1)]
            delay = base + self._jitter_seconds * float(sample)
            return RetryDecisionV6(delay, self._snapshot_unlocked())

    async def record_stable(self) -> ProviderCircuitSnapshotV6:
        lock = self._bind_loop()
        async with lock:
            if self._failures or self._state is not ProviderCircuitStateV6.CLOSED:
                self._recoveries += 1
            self._failures = 0
            self._last_fault = None
            self._state = ProviderCircuitStateV6.CLOSED
            self._sequence += 1
            return self._snapshot_unlocked()

    async def manual_recovery(self) -> RecoveryAckV6:
        lock = self._bind_loop()
        async with lock:
            accepted = self._state is not ProviderCircuitStateV6.CLOSED
            if accepted:
                self._state = ProviderCircuitStateV6.HALF_OPEN
            self._sequence += 1
            return RecoveryAckV6(accepted, self._state, self._sequence)


class _Installation:
    def __init__(
        self,
        base: v5.OnyxLiveActivationV5,
        originals: list[tuple[object, str, object]],
    ) -> None:
        self.base = base
        self.originals = originals

    def rollback(self) -> None:
        for owner, name, value in reversed(self.originals):
            setattr(owner, name, value)
        self.originals.clear()
        self.base.rollback_installation()


class OnyxLiveActivationV6:
    BASE_SEAM_COUNT = v5.OnyxLiveActivationV5.TOTAL_SEAM_COUNT
    V6_SEAM_COUNT = 4
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V6_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV6,
        contract: HostContractV6,
        *,
        authority_factory: Callable[[], object] = v5.v4.provision_owner_authority,
        ui_timeout_seconds: float = 2.0,
        circuit_factory: Callable[[], ProviderCircuitBreakerV6] = ProviderCircuitBreakerV6,
        registry_factory: Callable[[], ToolCallRegistryV6] = ToolCallRegistryV6,
    ) -> None:
        if type(flags) is not ActivationFlagsV6 or type(contract) is not HostContractV6:
            raise ActivationV6Error("exact V6 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v5.OnyxLiveActivationV5(
            v5.ActivationFlagsV5(True, True, True, (True,) * len(PHASE5_FLAGS)),
            contract.base,
            authority_factory=authority_factory,
            ui_timeout_seconds=ui_timeout_seconds,
        )
        self._circuit_factory = circuit_factory
        self._registry_factory = registry_factory
        self._installation: _Installation | None = None
        self._state = ActivationV6State.PREFLIGHTED
        self._lock = threading.RLock()

    @property
    def state(self) -> ActivationV6State:
        return self._state

    @property
    def failure_type(self) -> str | None:
        return self._base.failure_type

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    @staticmethod
    def _normalise_recovery_command(value: object) -> str:
        return " ".join(str(value).casefold().split())

    async def _manual_recovery_command(self, instance: object) -> RecoveryAckV6:
        circuit = instance._onyx_v6_provider_circuit
        ack = await circuit.manual_recovery()
        instance._onyx_v6_recovery_event.set()
        return ack

    def request_provider_recovery_from_thread(
        self, instance: object, *, timeout_seconds: float = 5.0
    ) -> RecoveryAckV6:
        timeout = _positive_finite_number(
            "manual recovery timeout", timeout_seconds, 30.0
        )
        loop = getattr(instance, "_loop", None)
        if loop is None or loop.is_closed():
            raise ActivationV6Error("provider event loop is unavailable")
        if threading.get_ident() == getattr(instance, "_onyx_v6_loop_thread_id", None):
            raise CircuitLoopAffinityV6(
                "synchronous recovery cannot block the owning event loop"
            )
        future = asyncio.run_coroutine_threadsafe(
            self._manual_recovery_command(instance), loop
        )
        return future.result(timeout=timeout)

    @staticmethod
    def _tool_registry(instance: object, factory: Callable[[], ToolCallRegistryV6]):
        registry = getattr(instance, "_onyx_v6_tool_registry", None)
        if not isinstance(registry, ToolCallRegistryV6):
            registry = factory()
            instance._onyx_v6_tool_registry = registry
        return registry

    async def _broadcast_status(
        self, instance: object, state: str, **details: object
    ) -> None:
        dashboard = getattr(instance, "_dashboard", None)
        if dashboard is not None:
            with contextlib.suppress(Exception):
                await dashboard.broadcast({"type": "status", "state": state, **details})

    async def _wait_for_retry(self, instance: object, delay: float) -> None:
        event = instance._onyx_v6_recovery_event
        try:
            await asyncio.wait_for(event.wait(), timeout=delay)
            event.clear()
            instance.ui.write_log("SYS: Manual voice recovery acknowledged.")
        except asyncio.TimeoutError:
            pass

    async def _run_provider_loop(self, instance: object) -> None:
        module = self.contract.module
        circuit: ProviderCircuitBreakerV6 = instance._onyx_v6_provider_circuit

        async def mark_stable(expected_session: object) -> None:
            await asyncio.sleep(circuit.stable_close_seconds)
            if instance.session is not expected_session:
                return
            prior = await circuit.snapshot()
            current = await circuit.record_stable()
            if prior.state is not ProviderCircuitStateV6.CLOSED:
                instance.ui.write_log(
                    "SYS: Gemini Live voice recovered; provider circuit closed."
                )
                await self._broadcast_status(
                    instance,
                    "active",
                    voice="online",
                    circuit=current.state.value,
                )

        while True:
            await circuit.begin_attempt()
            try:
                print("[Onyx V6] Connecting voice provider...")
                instance.ui.set_state("THINKING")
                instance._start_phase5_session()
                config = instance._build_config()
                factory = getattr(instance, "_onyx_v6_client_factory", None)
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
                    if instance._onyx_v6_startup_briefing and not instance._briefing_sent:
                        instance._briefing_sent = True
                        tg.create_task(instance._send_startup_briefing())
                raise RuntimeError("Gemini Live session ended unexpectedly")
            except asyncio.CancelledError:
                raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as exc:
                fault = v5.classify_provider_fault(exc)
                decision = await circuit.record_failure(fault)
                delay = decision.delay_seconds
                snapshot = decision.snapshot
                print(
                    f"[Onyx V6] Voice degraded ({fault.value}, "
                    f"circuit={snapshot.state.value}, retry={delay:.3f}s): {exc}"
                )
                instance.ui.set_state("ERROR")
                if fault is v5.ProviderFaultKind.CREDENTIAL:
                    instance.ui.write_log(
                        "ERR: Gemini credential was rejected. Local Onyx remains online; "
                        "update the credential to recover voice."
                    )
                    instance.ui.prompt_reconfig()
                else:
                    instance.ui.write_log(
                        "VOICE DEGRADED: Gemini Live is unavailable "
                        f"({fault.value}). Local HUD, dashboard and missions remain online; "
                        f"automatic retry in {delay:.1f}s or type 'recover voice'."
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
        instance._onyx_v6_loop_thread_id = threading.get_ident()
        instance._onyx_v6_recovery_event = asyncio.Event()
        instance._onyx_v6_provider_circuit = self._circuit_factory()
        await instance._onyx_v6_provider_circuit.bind_owner_loop()
        (
            startup_briefing_enabled,
            proactive_enabled,
            trust_profile,
            autonomy_enabled,
            autonomy_roots,
        ) = module._load_launch_flags()
        instance._onyx_v6_startup_briefing = startup_briefing_enabled
        module.set_trust_profile(trust_profile)
        module.configure_owner_autonomy(autonomy_enabled, autonomy_roots)
        autonomy_status = (
            "ON" if trust_profile == "autonomous" and autonomy_enabled else "OFF"
        )
        instance.ui.write_log(
            f"SYS: OWNER AUTONOMY {autonomy_status} ({trust_profile})."
        )
        persistent_tasks: list[asyncio.Task[Any]] = []
        try:
            if instance._dashboard is None:
                try:
                    dashboard_factory = getattr(
                        instance, "_onyx_v6_dashboard_factory", None
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
            if self._state is not ActivationV6State.PREFLIGHTED:
                raise ActivationV6Error("activation is not in preflighted state")
            if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
                raise ActivationV6Error("seam failpoint is outside V6 installation")
            base_failpoint = fail_after if fail_after and fail_after <= 18 else None
            self._base.install(fail_after=base_failpoint)
            host_type = self.contract.onyx_live
            originals: list[tuple[object, str, object]] = []
            writes = self.BASE_SEAM_COUNT

            underlying_execute = None
            base_installation = self._base._installation
            if base_installation is not None:
                for owner, name, value in base_installation.originals:
                    if owner is host_type and name == "_execute_tool":
                        underlying_execute = value
                        break
            if underlying_execute is None:
                self._base.rollback_installation()
                raise ActivationV6Error("accepted V4 execute seam is unavailable")

            original_text = host_type._on_text_command
            controller = self

            def patch(owner: object, name: str, value: object) -> None:
                nonlocal writes
                previous = getattr(owner, name)
                setattr(owner, name, value)
                originals.append((owner, name, previous))
                writes += 1
                if fail_after is not None and writes >= fail_after:
                    raise ActivationV6Error("injected V6 seam installation failure")

            async def execute_tool(instance: object, fc: object) -> object:
                try:
                    arguments = copy.deepcopy(dict(getattr(fc, "args", None) or {}))
                    registry = controller._tool_registry(
                        instance, controller._registry_factory
                    )
                    return await registry.execute(
                        call_id=getattr(fc, "id", None),
                        name=getattr(fc, "name", None),
                        arguments=arguments,
                        runner=lambda: underlying_execute(instance, fc),
                    )
                except ActivationV6Error as exc:
                    instance.ui.write_log(
                        "ERR: Provider tool call refused without execution "
                        f"({type(exc).__name__})."
                    )
                    return self.contract.module.types.FunctionResponse(
                        id=str(getattr(fc, "id", "") or ""),
                        name=str(getattr(fc, "name", "") or ""),
                        response={
                            "result": "tool call refused",
                            "error": type(exc).__name__,
                        },
                    )

            def on_text_command(instance: object, text: str) -> None:
                command = controller._normalise_recovery_command(text)
                if command in RECOVERY_COMMANDS:
                    try:
                        ack = controller.request_provider_recovery_from_thread(instance)
                        instance.ui.write_log(
                            "SYS: Voice recovery acknowledged."
                            if ack.accepted
                            else "SYS: Voice provider is already online."
                        )
                    except Exception as exc:
                        instance.ui.write_log(
                            f"VOICE DEGRADED: recovery command failed ({type(exc).__name__})."
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
                            ack = await controller._manual_recovery_command(instance)
                            instance.ui.write_log(
                                "[Web]: Voice recovery acknowledged."
                                if ack.accepted
                                else "[Web]: Voice provider is already online."
                            )
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

            try:
                patch(host_type, "_execute_tool", execute_tool)
                patch(host_type, "_on_text_command", on_text_command)
                patch(host_type, "_process_dashboard_commands", process_dashboard_commands)
                patch(host_type, "_run_live_loop", run_live_loop)
            except Exception:
                for owner, name, previous in reversed(originals):
                    setattr(owner, name, previous)
                self._base.rollback_installation()
                raise
            self._installation = _Installation(self._base, originals)
            self._state = ActivationV6State.INSTALLED

    def start(self) -> ActivationV6State:
        if self._state is not ActivationV6State.INSTALLED:
            raise ActivationV6Error("host seams must be installed before provisioning")
        observed = self._base.start()
        self._state = ActivationV6State(observed.value)
        return self._state

    def rollback_installation(self) -> None:
        with self._lock:
            if self._installation is not None:
                self._installation.rollback()
                self._installation = None
            else:
                self._base.rollback_installation()
            self._state = ActivationV6State.TERMINATED


def activate_main(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> OnyxLiveActivationV6:
    controller = OnyxLiveActivationV6(
        ActivationFlagsV6.from_canonical_environ(environ), preflight_host(module)
    )
    controller.install()
    controller.start()
    module._onyx_live_activation_v6 = controller
    return controller


__all__ = [
    "ActivationFlagsV6",
    "ActivationV6Error",
    "ActivationV6State",
    "CHILD_FLAGS",
    "CONTROL_FLAGS",
    "CircuitLoopAffinityV6",
    "HostContractV6",
    "INPUT_AUDIO_MIME",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV6",
    "ProviderCircuitBreakerV6",
    "ProviderCircuitSnapshotV6",
    "ProviderCircuitStateV6",
    "REPLAY_WINDOW_SIZE",
    "RECOVERY_COMMANDS",
    "RecoveryAckV6",
    "RetryDecisionV6",
    "ToolCallRegistryV6",
    "ToolExecutionReplayV6",
    "ToolIdentityConflictV6",
    "ToolRegistrySnapshotV6",
    "ToolReplayWindowFullV6",
    "activate_main",
    "canonical_arguments_digest",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
]
