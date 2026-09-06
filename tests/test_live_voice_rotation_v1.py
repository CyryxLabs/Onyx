from __future__ import annotations

import asyncio
import builtins
import contextlib
import hashlib
from pathlib import Path
from types import SimpleNamespace

import main
import pytest
from core import onyx_live_activation_v6 as v6
from core.audio_contract import LiveSessionRotation
from core.audio_contract import (
    InvalidLiveSessionResumeHandle,
    MAX_LIVE_SESSION_RESUME_HANDLE_BYTES,
    validate_live_session_resume_handle,
)
from core.live_voice_continuity_v1 import (
    install_live_voice_continuity_v1,
    is_clean_live_session_rotation,
    is_session_resumption_rejection,
    run_provider_loop_v1,
)


ROOT = Path(__file__).resolve().parents[1]


def test_rotation_detection_unwraps_taskgroup_without_masking_real_faults() -> None:
    rotation = builtins.ExceptionGroup(
        "provider tasks",
        [LiveSessionRotation("Gemini Live GoAway received")],
    )
    mixed = builtins.ExceptionGroup(
        "provider tasks",
        [
            LiveSessionRotation("Gemini Live GoAway received"),
            RuntimeError("1011 service unavailable"),
        ],
    )

    assert is_clean_live_session_rotation(rotation) is True
    assert is_clean_live_session_rotation(mixed) is False
    assert is_clean_live_session_rotation(RuntimeError("network")) is False


def test_continuity_seam_is_reversible_and_v6_bytes_remain_frozen() -> None:
    frozen = ROOT / "core" / "onyx_live_activation_v6.py"
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == (
        "68d75e89728355b6b26b153f19ec5d732f26369b79d7e03e700bc8b00ee95f54"
    )

    controller = object.__new__(v6.OnyxLiveActivationV6)
    original = controller._run_provider_loop
    installation = install_live_voice_continuity_v1(controller)
    assert vars(controller)["_run_provider_loop"] is installation.wrapper
    installation.rollback()
    restored = controller._run_provider_loop
    assert restored.__self__ is controller
    assert restored.__func__ is original.__func__


class _Circuit:
    stable_close_seconds = 60.0

    def __init__(self) -> None:
        self.attempts = 0
        self.failure_calls = 0

    async def begin_attempt(self) -> None:
        self.attempts += 1

    async def snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(state=v6.ProviderCircuitStateV6.CLOSED)

    async def record_stable(self) -> SimpleNamespace:
        return await self.snapshot()

    async def record_failure(self, _fault: object) -> None:
        self.failure_calls += 1
        raise AssertionError("clean rotation must not record a provider failure")


class _UI:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.states: list[str] = []

    def write_log(self, value: str) -> None:
        self.logs.append(value)

    def set_state(self, value: str) -> None:
        self.states.append(value)

    def prompt_reconfig(self) -> None:
        raise AssertionError("clean rotation must not prompt for reconfiguration")


class _Session:
    def __init__(self, attempt: int) -> None:
        self.attempt = attempt

    async def send_realtime_input(self, **_kwargs: object) -> None:
        return None

    async def receive(self):
        if self.attempt == 1:
            yield SimpleNamespace(
                session_resumption_update=SimpleNamespace(
                    resumable=True,
                    new_handle="retained-resume-handle",
                ),
                go_away=SimpleNamespace(time_left="5s"),
                data=None,
                server_content=None,
            )
        await asyncio.Event().wait()
        if False:
            yield None


class _Connect:
    def __init__(self, session: _Session, connected: asyncio.Event) -> None:
        self.session = session
        self.connected = connected

    async def __aenter__(self) -> _Session:
        if self.session.attempt == 2:
            self.connected.set()
        return self.session

    async def __aexit__(self, *_args: object) -> bool:
        return False


class _Factory:
    def __init__(self, connected: asyncio.Event) -> None:
        self.attempts = 0
        self.configs: list[dict[str, object]] = []
        self.connected = connected

    def __call__(self) -> SimpleNamespace:
        factory = self

        class _Live:
            def connect(self, *, model: str, config: dict[str, object]) -> _Connect:
                assert model == "models/gemini-2.5-flash-native-audio-preview-12-2025"
                factory.attempts += 1
                factory.configs.append(dict(config))
                return _Connect(_Session(factory.attempts), factory.connected)

        return SimpleNamespace(aio=SimpleNamespace(live=_Live()))


class _Controller:
    def __init__(self) -> None:
        module = SimpleNamespace(
            API_CONFIG_PATH=Path("api_config.json"),
            resolve_live_model=lambda _path: (
                "models/gemini-2.5-flash-native-audio-preview-12-2025"
            ),
        )
        self.contract = SimpleNamespace(module=module)
        self.broadcasts: list[dict[str, object]] = []
        self.retry_calls = 0

    async def _broadcast_status(
        self, _instance: object, state: str, **details: object
    ) -> None:
        self.broadcasts.append({"state": state, **details})

    async def _wait_for_retry(self, _instance: object, _delay: float) -> None:
        self.retry_calls += 1
        raise AssertionError("clean rotation must reconnect without backoff")


def test_goaway_reconnects_immediately_with_handle_and_no_degradation() -> None:
    asyncio.run(_exercise_goaway_rotation())


async def _exercise_goaway_rotation() -> None:
    second_connected = asyncio.Event()
    factory = _Factory(second_connected)
    circuit = _Circuit()
    controller = _Controller()
    host = main.OnyxLive.__new__(main.OnyxLive)
    host.ui = _UI()
    host.session = None
    host._dashboard = None
    host._phase5 = None
    host._briefing_sent = False
    host._onyx_v6_startup_briefing = False
    host._onyx_v6_provider_circuit = circuit
    host._onyx_v6_client_factory = factory
    host._live_session_resume_handle = None
    host._start_phase5_session = lambda: None
    stop_reasons: list[str] = []
    host._stop_phase5_session = stop_reasons.append
    host.set_speaking = lambda _value: None
    host._build_config = lambda: {
        "resume_handle": host._live_session_resume_handle,
        "voice": "Charon",
    }

    local_audio_starts = {"microphone": 0, "playback": 0}

    async def wait_forever() -> None:
        await asyncio.Event().wait()

    async def microphone_lifetime() -> None:
        local_audio_starts["microphone"] += 1
        await wait_forever()

    async def playback_lifetime() -> None:
        local_audio_starts["playback"] += 1
        await wait_forever()

    host._send_realtime = wait_forever
    host._listen_audio = microphone_lifetime
    host._receive_audio = lambda: main.OnyxLive._receive_audio(host)
    host._play_audio = playback_lifetime
    host._relay_phone_audio = wait_forever
    host._send_startup_briefing = wait_forever

    task = asyncio.create_task(run_provider_loop_v1(controller, host))
    try:
        await asyncio.wait_for(second_connected.wait(), timeout=2.0)
        assert factory.attempts == 2
        assert local_audio_starts == {"microphone": 1, "playback": 1}
        assert factory.configs == [
            {"resume_handle": None, "voice": "Charon"},
            {"resume_handle": "retained-resume-handle", "voice": "Charon"},
        ]
        assert circuit.failure_calls == 0
        assert controller.retry_calls == 0
        assert "ERROR" not in host.ui.states
        assert not any("VOICE DEGRADED" in log for log in host.ui.logs)
        assert stop_reasons[0] == "provider-session-rotation"
        assert any(
            item.get("connection") == "rotating"
            and item.get("voice") == "online"
            for item in controller.broadcasts
        )
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.parametrize(
    ("resumable", "new_handle", "expected"),
    [
        (True, "new-context", "new-context"),
        (False, "ignored-context", None),
        (None, "incomplete-context", "prior-context"),
    ],
)
def test_resumption_updates_handle_true_false_and_none(
    resumable: bool | None,
    new_handle: str,
    expected: str | None,
) -> None:
    class Session:
        async def receive(self):
            yield SimpleNamespace(
                session_resumption_update=SimpleNamespace(
                    resumable=resumable,
                    new_handle=new_handle,
                ),
                go_away=SimpleNamespace(time_left="5s"),
                data=None,
                server_content=None,
            )

    class FailingLogUI:
        def write_log(self, _message: str) -> None:
            raise RuntimeError("HUD unavailable")

    host = main.OnyxLive.__new__(main.OnyxLive)
    host.session = Session()
    host.ui = FailingLogUI()
    host._live_session_resume_handle = "prior-context"

    with pytest.raises(LiveSessionRotation):
        asyncio.run(main.OnyxLive._receive_audio(host))
    assert host._live_session_resume_handle == expected


class _StringTrap:
    def __str__(self) -> str:
        raise AssertionError("an arbitrary resume-handle object must never be coerced")


class _StringSubclass(str):
    pass


@pytest.mark.parametrize(
    "invalid_handle",
    [
        None,
        "",
        "  \t",
        _StringTrap(),
        _StringSubclass("subclass-handle"),
        "x" * (MAX_LIVE_SESSION_RESUME_HANDLE_BYTES + 1),
        "\ud800",
    ],
)
def test_invalid_provider_resume_handle_is_cleared_and_raised(
    invalid_handle: object,
) -> None:
    class Session:
        async def receive(self):
            yield SimpleNamespace(
                session_resumption_update=SimpleNamespace(
                    resumable=True,
                    new_handle=invalid_handle,
                ),
                go_away=None,
                data=None,
                server_content=None,
            )

    host = main.OnyxLive.__new__(main.OnyxLive)
    host.session = Session()
    host.ui = _UI()
    host._live_session_resume_handle = "prior-context"

    with pytest.raises(InvalidLiveSessionResumeHandle):
        asyncio.run(main.OnyxLive._receive_audio(host))
    assert host._live_session_resume_handle is None


def test_resume_handle_limit_is_utf8_bytes_and_preserves_opaque_value() -> None:
    within_limit = " é" * (MAX_LIVE_SESSION_RESUME_HANDLE_BYTES // 3)
    assert len(within_limit.encode("utf-8")) <= MAX_LIVE_SESSION_RESUME_HANDLE_BYTES
    assert validate_live_session_resume_handle(within_limit) is within_limit

    over_limit = "é" * ((MAX_LIVE_SESSION_RESUME_HANDLE_BYTES // 2) + 1)
    with pytest.raises(InvalidLiveSessionResumeHandle, match="4096-byte"):
        validate_live_session_resume_handle(over_limit)


def test_build_config_rejects_invalid_retained_handle_without_coercion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = main.OnyxLive.__new__(main.OnyxLive)
    host._phase5 = None
    host._live_session_resume_handle = _StringTrap()
    monkeypatch.setattr(main, "load_memory", lambda: {})
    monkeypatch.setattr(main, "_load_owner_name", lambda: "")
    monkeypatch.setattr(main, "_load_system_prompt", lambda: "SYSTEM")

    with pytest.raises(InvalidLiveSessionResumeHandle):
        main.OnyxLive._build_config(host)


def test_invalid_preexisting_handle_is_cleared_and_hits_breaker() -> None:
    asyncio.run(_exercise_invalid_preexisting_handle())


async def _exercise_invalid_preexisting_handle() -> None:
    connected = asyncio.Event()
    factory = _Factory(connected)
    circuit = _BreakerCircuit()
    host, controller, stop_reasons = _provider_host(factory, circuit)
    host._live_session_resume_handle = _StringTrap()
    host._build_config = lambda: {
        "resume_handle": validate_live_session_resume_handle(
            host._live_session_resume_handle
        ),
        "voice": "Charon",
    }

    async def wait_for_cancel(_instance: object, _delay: float) -> None:
        controller.retry_calls += 1
        await asyncio.Event().wait()

    controller._wait_for_retry = wait_for_cancel
    task = asyncio.create_task(run_provider_loop_v1(controller, host))
    try:
        await asyncio.wait_for(circuit.failed.wait(), timeout=2.0)
        await asyncio.sleep(0)
        assert factory.attempts == 0
        assert circuit.failure_calls == 1
        assert host._live_session_resume_handle is None
        assert stop_reasons == ["provider-reconnect"]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_resumption_rejection_requires_handle_and_single_failure_leaf() -> None:
    real_provider_failure = RuntimeError(
        "1007 None. Request contains an invalid argument."
    )
    explicit_expiry = RuntimeError("Session resumption handle expired")
    mixed = builtins.ExceptionGroup(
        "mixed",
        [explicit_expiry, RuntimeError("1011 provider unavailable")],
    )

    assert is_session_resumption_rejection(real_provider_failure, "handle") is True
    assert is_session_resumption_rejection(explicit_expiry, "handle") is True
    assert is_session_resumption_rejection(real_provider_failure, None) is False
    assert is_session_resumption_rejection(real_provider_failure, "") is False
    assert is_session_resumption_rejection(mixed, "handle") is False


class _FreshRetryConnect:
    def __init__(
        self,
        attempt: int,
        connected: asyncio.Event,
        failure: BaseException | None,
    ) -> None:
        self.attempt = attempt
        self.connected = connected
        self.failure = failure

    async def __aenter__(self) -> _Session:
        if self.failure is not None:
            raise self.failure
        self.connected.set()
        return _Session(self.attempt)

    async def __aexit__(self, *_args: object) -> bool:
        return False


class _FreshRetryFactory:
    def __init__(self, connected: asyncio.Event, failure: BaseException) -> None:
        self.attempts = 0
        self.configs: list[dict[str, object]] = []
        self.connected = connected
        self.failure = failure

    def __call__(self) -> SimpleNamespace:
        factory = self

        class _Live:
            def connect(self, *, model: str, config: dict[str, object]):
                assert model == "models/gemini-2.5-flash-native-audio-preview-12-2025"
                factory.attempts += 1
                factory.configs.append(dict(config))
                failure = factory.failure if factory.attempts == 1 else None
                return _FreshRetryConnect(
                    factory.attempts, factory.connected, failure
                )

        return SimpleNamespace(aio=SimpleNamespace(live=_Live()))


def _provider_host(
    factory: object,
    circuit: object,
    *,
    handle: str = "expired-context",
    ui: object | None = None,
) -> tuple[object, _Controller, list[str]]:
    controller = _Controller()
    host = main.OnyxLive.__new__(main.OnyxLive)
    host.ui = ui or _UI()
    host.session = None
    host._dashboard = None
    host._phase5 = None
    host._briefing_sent = False
    host._onyx_v6_startup_briefing = False
    host._onyx_v6_provider_circuit = circuit
    host._onyx_v6_client_factory = factory
    host._live_session_resume_handle = handle
    host._start_phase5_session = lambda: None
    stop_reasons: list[str] = []
    host._stop_phase5_session = stop_reasons.append
    host.set_speaking = lambda _value: None
    host._build_config = lambda: {
        "resume_handle": host._live_session_resume_handle,
        "voice": "Charon",
    }

    async def wait_forever() -> None:
        await asyncio.Event().wait()

    host._send_realtime = wait_forever
    host._listen_audio = wait_forever
    host._receive_audio = wait_forever
    host._play_audio = wait_forever
    host._relay_phone_audio = wait_forever
    host._send_startup_briefing = wait_forever
    return host, controller, stop_reasons


def test_rejected_handle_gets_exactly_one_immediate_fresh_attempt() -> None:
    asyncio.run(_exercise_rejected_handle_fresh_attempt())


async def _exercise_rejected_handle_fresh_attempt() -> None:
    connected = asyncio.Event()
    factory = _FreshRetryFactory(
        connected,
        RuntimeError("1007 None. Request contains an invalid argument."),
    )
    circuit = _Circuit()

    class BrokenLogUI(_UI):
        def write_log(self, _value: str) -> None:
            raise RuntimeError("HUD logger unavailable")

    host, controller, stop_reasons = _provider_host(
        factory, circuit, ui=BrokenLogUI()
    )
    task = asyncio.create_task(run_provider_loop_v1(controller, host))
    try:
        await asyncio.wait_for(connected.wait(), timeout=2.0)
        assert factory.configs == [
            {"resume_handle": "expired-context", "voice": "Charon"},
            {"resume_handle": None, "voice": "Charon"},
        ]
        assert factory.attempts == 2
        assert host._live_session_resume_handle is None
        assert circuit.failure_calls == 0
        assert controller.retry_calls == 0
        assert stop_reasons[0] == "provider-resumption-reset"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class _BreakerCircuit(_Circuit):
    def __init__(self) -> None:
        super().__init__()
        self.failed = asyncio.Event()

    async def record_failure(self, _fault: object) -> SimpleNamespace:
        self.failure_calls += 1
        self.failed.set()
        return SimpleNamespace(
            delay_seconds=60.0,
            snapshot=SimpleNamespace(state=v6.ProviderCircuitStateV6.OPEN),
        )


def test_mixed_resumption_and_provider_failure_still_hits_breaker() -> None:
    asyncio.run(_exercise_mixed_failure_breaker())


async def _exercise_mixed_failure_breaker() -> None:
    connected = asyncio.Event()
    failure = builtins.ExceptionGroup(
        "mixed",
        [
            RuntimeError("Session resumption handle expired"),
            RuntimeError("1011 provider unavailable"),
        ],
    )
    factory = _FreshRetryFactory(connected, failure)
    circuit = _BreakerCircuit()
    host, controller, stop_reasons = _provider_host(factory, circuit)

    async def wait_for_cancel(_instance: object, _delay: float) -> None:
        controller.retry_calls += 1
        await asyncio.Event().wait()

    controller._wait_for_retry = wait_for_cancel
    task = asyncio.create_task(run_provider_loop_v1(controller, host))
    try:
        await asyncio.wait_for(circuit.failed.wait(), timeout=2.0)
        assert factory.attempts == 1
        assert circuit.failure_calls == 1
        assert host._live_session_resume_handle == "expired-context"
        assert stop_reasons[0] == "provider-reconnect"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class _ExplodingUI:
    def write_log(self, _value: str) -> None:
        raise RuntimeError("write_log unavailable")

    def set_state(self, _value: str) -> None:
        raise RuntimeError("set_state unavailable")

    def prompt_reconfig(self) -> None:
        raise RuntimeError("prompt unavailable")


def _install_failing_cleanup(host: object) -> tuple[list[str], list[bool]]:
    stops: list[str] = []
    speaking: list[bool] = []

    def fail_stop(reason: str) -> None:
        stops.append(reason)
        raise RuntimeError("phase5 cleanup failed")

    def fail_speaking(value: bool) -> None:
        speaking.append(value)
        raise RuntimeError("speaking cleanup failed")

    host._stop_phase5_session = fail_stop
    host.set_speaking = fail_speaking
    return stops, speaking


def test_goaway_survives_both_cleanup_and_ui_failures() -> None:
    asyncio.run(_exercise_goaway_cleanup_and_ui_failures())


async def _exercise_goaway_cleanup_and_ui_failures() -> None:
    connected = asyncio.Event()
    factory = _Factory(connected)
    circuit = _Circuit()
    host, controller, _ = _provider_host(
        factory, circuit, handle=None, ui=_ExplodingUI()
    )
    host._receive_audio = lambda: main.OnyxLive._receive_audio(host)
    stops, speaking = _install_failing_cleanup(host)

    task = asyncio.create_task(run_provider_loop_v1(controller, host))
    try:
        await asyncio.wait_for(connected.wait(), timeout=2.0)
        assert factory.attempts == 2
        assert stops[0] == "provider-session-rotation"
        assert speaking[0] is False
        assert circuit.failure_calls == 0
        assert controller.retry_calls == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_provider_failure_survives_both_cleanup_failures() -> None:
    asyncio.run(_exercise_provider_and_cleanup_failures())


async def _exercise_provider_and_cleanup_failures() -> None:
    connected = asyncio.Event()
    factory = _FreshRetryFactory(
        connected,
        RuntimeError("1011 provider unavailable"),
    )
    circuit = _BreakerCircuit()
    host, controller, _ = _provider_host(factory, circuit)
    stops, speaking = _install_failing_cleanup(host)
    cleanup_observed = asyncio.Event()

    original_speaking = host.set_speaking

    def signal_after_failure(value: bool) -> None:
        try:
            original_speaking(value)
        finally:
            cleanup_observed.set()

    host.set_speaking = signal_after_failure

    async def wait_for_cancel(_instance: object, _delay: float) -> None:
        controller.retry_calls += 1
        await asyncio.Event().wait()

    controller._wait_for_retry = wait_for_cancel
    task = asyncio.create_task(run_provider_loop_v1(controller, host))
    try:
        await asyncio.wait_for(cleanup_observed.wait(), timeout=2.0)
        assert circuit.failure_calls == 1
        assert stops == ["provider-reconnect"]
        assert speaking == [False]
        assert controller.retry_calls == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_cancellation_survives_both_cleanup_failures() -> None:
    asyncio.run(_exercise_cancellation_and_cleanup_failures())


async def _exercise_cancellation_and_cleanup_failures() -> None:
    connected = asyncio.Event()
    factory = _Factory(connected)
    circuit = _Circuit()
    host, controller, _ = _provider_host(factory, circuit, handle=None)
    stops, speaking = _install_failing_cleanup(host)

    # Keep the first connection open rather than inducing the factory's
    # first-attempt GoAway, so cancellation is the primary lifecycle outcome.
    async def wait_forever() -> None:
        connected.set()
        await asyncio.Event().wait()

    host._receive_audio = wait_forever
    task = asyncio.create_task(run_provider_loop_v1(controller, host))
    await asyncio.wait_for(connected.wait(), timeout=2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stops == ["provider-reconnect"]
    assert speaking == [False]


class _WebSocketRejection(Exception):
    """A provider rejection carrying a WebSocket close code."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def test_policy_violation_session_not_found_clears_the_retained_handle() -> None:
    """Gemini's live rejection form, observed 2026-08-22 on the owner's host.

    The provider refuses a stale handle as policy violation 1008 with
    "BidiGenerateContent session not found", naming neither resumption nor the
    handle. Unrecognised, the handle survives every retry, so the loop resumes
    the same dead session for ever: the circuit stays open, the log fills with
    "Voice degraded ... retry=30s", and voice never returns until the process
    is restarted.
    """
    failure = _WebSocketRejection(
        "1008 None. BidiGenerateContent session not found", 1008
    )
    assert is_session_resumption_rejection(failure, "opaque-handle") is True


def test_session_not_found_is_ignored_when_no_handle_was_attempted() -> None:
    """A fresh session's 1008 is a real fault and must reach the breaker."""
    failure = _WebSocketRejection(
        "1008 None. BidiGenerateContent session not found", 1008
    )
    for attempted in (None, "", "   ", 42):
        assert is_session_resumption_rejection(failure, attempted) is False


def test_unrelated_policy_violations_are_not_mistaken_for_stale_handles() -> None:
    """Only a missing *session* counts; other 1008s stay provider failures."""
    for message in (
        "1008 quota exceeded for project",
        "1008 policy violation",
        "connection reset by peer",
    ):
        assert is_session_resumption_rejection(
            _WebSocketRejection(message, 1008), "opaque-handle"
        ) is False
