"""Clean Gemini Live session rotation without degrading Onyx voice health.

Gemini may send ``GoAway`` as an expected connection-lifetime boundary.  The
host receive task turns that signal into :class:`LiveSessionRotation`; Python's
``TaskGroup`` then wraps it in an exception group.  Frozen Activation V6 treats
every such group as a provider failure.  This live seam preserves V6 for real
faults while reconnecting clean rotations immediately with the resume handle
already retained by the host.
"""

from __future__ import annotations

import asyncio
from builtins import ExceptionGroup
from collections.abc import Iterator

from core import onyx_live_activation_v5 as v5
from core import onyx_live_activation_v6 as v6
from core.audio_contract import InvalidLiveSessionResumeHandle, LiveSessionRotation
from core.live_model import adapt_live_audio_transport


class LiveVoiceContinuityError(RuntimeError):
    """The reversible continuity seam could not be installed safely."""


def _exception_leaves(exc: BaseException) -> Iterator[BaseException]:
    nested = getattr(exc, "exceptions", None)
    if isinstance(nested, tuple):
        for child in nested:
            if isinstance(child, BaseException):
                yield from _exception_leaves(child)
        return
    yield exc


def is_clean_live_session_rotation(exc: BaseException) -> bool:
    """Return true only for a rotation group with no unrelated failure leaf."""

    leaves = tuple(_exception_leaves(exc))
    meaningful = tuple(
        leaf for leaf in leaves if not isinstance(leaf, asyncio.CancelledError)
    )
    return bool(meaningful) and all(
        isinstance(leaf, LiveSessionRotation) for leaf in meaningful
    )


def is_session_resumption_rejection(
    exc: BaseException,
    attempted_handle: object,
) -> bool:
    """Recognise a failed resumed connection without masking mixed failures.

    Gemini currently reports an expired/rejected handle either explicitly or
    as WebSocket/API code 1007 with ``Request contains an invalid argument``.
    The generic form is accepted only when this exact attempt supplied a
    non-empty handle.  Exception groups with multiple meaningful leaves are
    deliberately left to the provider circuit breaker.
    """

    if not isinstance(attempted_handle, str) or not attempted_handle.strip():
        return False
    meaningful = tuple(
        leaf
        for leaf in _exception_leaves(exc)
        if not isinstance(leaf, asyncio.CancelledError)
    )
    if len(meaningful) != 1:
        return False
    leaf = meaningful[0]
    message = str(leaf).strip().casefold()
    code = getattr(leaf, "code", None)
    if code is None:
        code = getattr(leaf, "status_code", None)
    explicit_handle = any(
        marker in message
        for marker in (
            "session resumption",
            "resumption handle",
            "resume handle",
            "resume token",
        )
    )
    rejected = any(
        marker in message
        for marker in ("invalid", "expired", "rejected", "not found", "stale")
    )
    generic_invalid_argument = (
        str(code) == "1007" or "1007" in message
    ) and "invalid argument" in message
    # Gemini also refuses a stale handle as policy violation 1008 carrying
    # "BidiGenerateContent session not found", naming neither the handle nor
    # resumption.  Unrecognised, the handle is never cleared, so every retry
    # resumes the same dead session: the circuit stays open and voice is
    # wedged until the process restarts.  Safe to accept generically because
    # this function already returned False unless *this* attempt supplied a
    # non-empty handle, so a fresh session's 1008 is never swallowed here.
    generic_session_missing = (
        str(code) == "1008" or "1008" in message
    ) and "session not found" in message
    return (
        (explicit_handle and rejected)
        or generic_invalid_argument
        or generic_session_missing
    )


def _contains_invalid_resume_handle(exc: BaseException) -> bool:
    """Detect a provider protocol-boundary violation, including TaskGroups."""

    return any(
        isinstance(leaf, InvalidLiveSessionResumeHandle)
        for leaf in _exception_leaves(exc)
    )


def _write_log_best_effort(instance: object, message: str) -> None:
    """Keep a presentation/logging fault outside provider recovery authority."""

    try:
        instance.ui.write_log(message)
    except Exception as exc:
        print(f"[Onyx Voice] UI log unavailable during recovery: {exc}")


def _set_ui_state_best_effort(instance: object, state: str) -> None:
    """Keep a HUD state transition outside provider lifecycle authority."""

    try:
        instance.ui.set_state(state)
    except Exception as exc:
        print(f"[Onyx Voice] UI state unavailable during recovery: {exc}")


def _prompt_reconfig_best_effort(instance: object) -> None:
    """Do not let a presentation fault replace a credential failure."""

    try:
        instance.ui.prompt_reconfig()
    except Exception as exc:
        print(f"[Onyx Voice] UI reconfiguration prompt unavailable: {exc}")


def _cleanup_provider_attempt_best_effort(instance: object, reason: str) -> None:
    """Run all synchronous cleanup steps and report their errors as one unit.

    Cleanup is deliberately subordinate to the provider-loop outcome.  In
    particular, its failures must not replace a clean GoAway rotation, a
    provider/circuit-breaker decision, or task cancellation.
    """

    failures: list[Exception] = []
    for label, cleanup in (
        ("phase5", lambda: instance._stop_phase5_session(reason)),
        ("speaking-state", lambda: instance.set_speaking(False)),
    ):
        try:
            cleanup()
        except Exception as exc:
            exc.add_note(f"Onyx voice cleanup step: {label}")
            failures.append(exc)
    if failures:
        aggregate = ExceptionGroup("Onyx voice cleanup failures", failures)
        print(f"[Onyx Voice] Cleanup incomplete (best effort): {aggregate!r}")
        _write_log_best_effort(
            instance,
            "WARN: Voice-session cleanup was incomplete; the primary provider "
            "lifecycle outcome was preserved.",
        )


def _drain_queue_best_effort(queue: object) -> None:
    """Discard audio owned by a provider session that has already ended."""

    getter = getattr(queue, "get_nowait", None)
    if not callable(getter):
        return
    while True:
        try:
            getter()
        except asyncio.QueueEmpty:
            return
        except Exception as exc:
            print(f"[Onyx Voice] Audio queue drain unavailable: {exc}")
            return


async def _run_provider_network_loop_v1(
    controller: v6.OnyxLiveActivationV6,
    instance: object,
) -> None:
    """Rotate only Gemini transport while process-owned audio remains alive."""

    module = controller.contract.module
    circuit: v6.ProviderCircuitBreakerV6 = instance._onyx_v6_provider_circuit

    async def mark_stable(expected_session: object) -> None:
        await asyncio.sleep(circuit.stable_close_seconds)
        if instance.session is not expected_session:
            return
        prior = await circuit.snapshot()
        current = await circuit.record_stable()
        if prior.state is not v6.ProviderCircuitStateV6.CLOSED:
            _write_log_best_effort(
                instance,
                "SYS: Gemini Live voice recovered; provider circuit closed."
            )
            await controller._broadcast_status(
                instance,
                "active",
                voice="online",
                circuit=current.state.value,
            )

    while True:
        await circuit.begin_attempt()
        clean_rotation = False
        fresh_retry = False
        delay = 0.0
        attempted_resume_handle = getattr(
            instance, "_live_session_resume_handle", None
        )
        try:
            print("[Onyx Voice] Connecting Gemini Native Audio provider...")
            _set_ui_state_best_effort(instance, "THINKING")
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
                ) as raw_session,
                asyncio.TaskGroup() as tg,
            ):
                session = adapt_live_audio_transport(raw_session)
                instance.session = session
                # Playback owns clearing the drain signal. A fast reconnect must
                # not erase it before the last session's native audio finishes.
                instance._pending_vision = None
                instance._vision_cam_active = False
                instance._vision_close_pending = False
                instance._vision_busy = False
                instance._vision_last_time = 0.0
                instance._interrupted = False
                _set_ui_state_best_effort(instance, "LISTENING")
                _write_log_best_effort(instance, "SYS: Onyx voice online.")
                await controller._broadcast_status(
                    instance, "active", voice="online"
                )
                tg.create_task(instance._send_realtime())
                tg.create_task(instance._receive_audio())
                tg.create_task(instance._flush_text_commands_v1())
                tg.create_task(instance._watch_text_command_response_v1())
                tg.create_task(mark_stable(session))
                tg.create_task(instance._wait_for_voice_rotation())
                if instance._dashboard:
                    tg.create_task(instance._relay_phone_audio())
                if (
                    instance._onyx_v6_startup_briefing
                    and not instance._briefing_sent
                ):
                    instance._briefing_sent = True
                    tg.create_task(instance._send_startup_briefing())
            raise RuntimeError("Gemini Live session ended unexpectedly")
        except asyncio.CancelledError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            if _contains_invalid_resume_handle(exc):
                # The receive path normally clears this before raising.  Clear
                # again at supervisor authority so malformed pre-existing state
                # cannot survive a failed config build either.
                instance._live_session_resume_handle = None
            if is_clean_live_session_rotation(exc):
                clean_rotation = True
                print(
                    "[Onyx Voice] Gemini Live session rotated normally; "
                    "reconnecting with retained context."
                )
                _write_log_best_effort(
                    instance,
                    "SYS: Gemini Live connection rotated normally; reconnecting "
                    "with preserved conversation context."
                )
                await controller._broadcast_status(
                    instance,
                    "active",
                    voice="online",
                    connection="rotating",
                )
            elif is_session_resumption_rejection(exc, attempted_resume_handle):
                fresh_retry = True
                instance._live_session_resume_handle = None
                print(
                    "[Onyx Voice] Gemini rejected the retained session context; "
                    "retrying once with a fresh session."
                )
                _write_log_best_effort(
                    instance,
                    "SYS: Previous Gemini conversation context expired; reconnecting "
                    "once with a fresh native-audio session.",
                )
                await controller._broadcast_status(
                    instance,
                    "active",
                    voice="online",
                    connection="fresh-session-retry",
                )
            else:
                fault = v5.classify_provider_fault(exc)
                decision = await circuit.record_failure(fault)
                delay = decision.delay_seconds
                snapshot = decision.snapshot
                print(
                    f"[Onyx Voice] Voice degraded ({fault.value}, "
                    f"circuit={snapshot.state.value}, retry={delay:.3f}s): {exc}"
                )
                _set_ui_state_best_effort(instance, "ERROR")
                if fault is v5.ProviderFaultKind.CREDENTIAL:
                    _write_log_best_effort(
                        instance,
                        "ERR: Gemini credential was rejected. Local Onyx remains "
                        "online; update the credential to recover voice."
                    )
                    _prompt_reconfig_best_effort(instance)
                else:
                    _write_log_best_effort(
                        instance,
                        "VOICE DEGRADED: Gemini Live is unavailable "
                        f"({fault.value}). Local HUD, dashboard and missions remain "
                        f"online; automatic retry in {delay:.1f}s or type "
                        "'recover voice'."
                    )
                await controller._broadcast_status(
                    instance,
                    "degraded",
                    voice="offline",
                    fault=fault.value,
                    circuit=snapshot.state.value,
                )
        finally:
            instance._provider_transport_ended_v1()
            instance.session = None
            _drain_queue_best_effort(instance.out_queue)
            _drain_queue_best_effort(instance.audio_in_queue)
            # No more audio can arrive from this transport. Let the persistent
            # playback worker drain its pending writes and release the mic gate,
            # even when GoAway arrived without a provider turn_complete message.
            instance._turn_done_event.set()
            reason = (
                "provider-session-rotation"
                if clean_rotation
                else (
                    "provider-resumption-reset"
                    if fresh_retry
                    else "provider-reconnect"
                )
            )
            _cleanup_provider_attempt_best_effort(instance, reason)
        if not clean_rotation and not fresh_retry:
            await controller._wait_for_retry(instance, delay)


async def run_provider_loop_v1(
    controller: v6.OnyxLiveActivationV6,
    instance: object,
) -> None:
    """Run one native-audio lifetime around any number of Gemini sessions.

    PortAudio streams are process-local resources, not provider-session
    resources.  Keeping them outside the reconnecting transport TaskGroup
    prevents concurrent native teardown/reopen during a normal Gemini GoAway.
    A genuine microphone or playback failure still fails the outer group and
    remains visible to the activation lifecycle.
    """

    instance.audio_in_queue = asyncio.Queue()
    instance.out_queue = asyncio.Queue(maxsize=200)
    instance._turn_done_event = asyncio.Event()
    instance._voice_rotation_event = asyncio.Event()
    async with asyncio.TaskGroup() as tg:
        tg.create_task(instance._listen_audio())
        tg.create_task(instance._play_audio())
        tg.create_task(_run_provider_network_loop_v1(controller, instance))


class LiveVoiceContinuityInstallationV1:
    """Reversible instance seam over the frozen V6 provider supervisor."""

    def __init__(self, controller: v6.OnyxLiveActivationV6) -> None:
        if type(controller) is not v6.OnyxLiveActivationV6:
            raise LiveVoiceContinuityError("exact V6 activation controller required")
        if "_run_provider_loop" in vars(controller):
            raise LiveVoiceContinuityError("provider supervisor seam already exists")
        self.controller = controller
        self.original = controller._run_provider_loop

        async def provider_loop(instance: object) -> None:
            await run_provider_loop_v1(controller, instance)

        self.wrapper = provider_loop
        controller._run_provider_loop = provider_loop

    def rollback(self) -> None:
        observed = vars(self.controller).get("_run_provider_loop")
        if observed is not self.wrapper:
            raise LiveVoiceContinuityError("provider supervisor seam authority drift")
        delattr(self.controller, "_run_provider_loop")
        restored = self.controller._run_provider_loop
        if (
            getattr(restored, "__self__", None) is not self.controller
            or getattr(restored, "__func__", None)
            is not getattr(self.original, "__func__", None)
        ):
            raise LiveVoiceContinuityError("frozen V6 supervisor was not restored")


def install_live_voice_continuity_v1(
    controller: v6.OnyxLiveActivationV6,
) -> LiveVoiceContinuityInstallationV1:
    return LiveVoiceContinuityInstallationV1(controller)


__all__ = [
    "LiveVoiceContinuityError",
    "LiveVoiceContinuityInstallationV1",
    "install_live_voice_continuity_v1",
    "is_clean_live_session_rotation",
    "is_session_resumption_rejection",
    "run_provider_loop_v1",
]
