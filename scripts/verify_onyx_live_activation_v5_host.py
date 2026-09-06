"""Fresh-process host contract, failpoint, MIME and replay gate for V5."""

from __future__ import annotations

import asyncio
import runpy
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core import onyx_live_activation_v5 as live  # noqa: E402


LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v5.pyw"


class Snapshot:
    def __init__(self, name=None):
        self.display_name = name
        self.reconciled = True
        self.state = types.SimpleNamespace(value="known" if name else "unknown")

    @property
    def name_known(self):
        return self.display_name is not None


class Authority:
    def __init__(self):
        self.snapshot = Snapshot()

    def reconcile(self):
        return self.snapshot

    def begin_contact(self):
        return "Before we continue, what name should I use for you?"

    def prompt_directive(self):
        return "owner-directive"

    def set_name(self, value):
        self.snapshot = Snapshot(str(value))
        return self.snapshot

    correct_name = set_name

    def forget_name(self):
        self.snapshot = Snapshot()
        return self.snapshot


class UI:
    def __init__(self):
        self.logs = []

    def write_log(self, value):
        self.logs.append(value)


def seams(contract):
    module = contract.module
    host = contract.onyx_live
    window = contract.main_window
    return (
        module._load_owner_name,
        module._load_system_prompt,
        module.TOOL_DECLARATIONS,
        host.__init__,
        host._start_phase5_session,
        host._stop_phase5_session,
        host._execute_tool,
        host._send_realtime,
        host._on_text_command,
        host._process_dashboard_commands,
        host._run_live_loop,
        window._configured_owner_name,
        window._show_setup,
        window._on_setup_done,
        window.__init__,
        window.closeEvent,
    )


async def exercise_runtime_seams(controller):
    host = object.__new__(main.OnyxLive)
    host.ui = UI()
    host.out_queue = asyncio.Queue()

    class Session:
        def __init__(self):
            self.media = []

        async def send_realtime_input(self, *, media):
            self.media.append(media)
            raise RuntimeError("mime-captured")

    host.session = Session()
    await host.out_queue.put({"data": b"\x01\x02", "mime_type": "audio/pcm"})
    try:
        await host._send_realtime()
    except RuntimeError as exc:
        assert str(exc) == "mime-captured"
    else:
        raise AssertionError("send seam did not reach session")
    assert host.session.media == [
        {"data": b"\x01\x02", "mime_type": live.INPUT_AUDIO_MIME}
    ]

    host._loop = asyncio.get_running_loop()
    host._onyx_v5_recovery_event = asyncio.Event()
    host._onyx_v5_provider_circuit = live.ProviderCircuitBreakerV5(
        retry_delays=(0,), open_after=1, open_cooldown=0
    )
    host._onyx_v5_provider_circuit.record_failure(
        live.ProviderFaultKind.UNAVAILABLE
    )
    host.session = None
    host._on_text_command("ordinary command")
    assert any("not sent or replayed" in value for value in host.ui.logs)
    host._on_text_command("recover voice")
    await asyncio.sleep(0)
    assert host._onyx_v5_recovery_event.is_set()
    await controller._wait_for_retry(host, 30)
    assert not host._onyx_v5_recovery_event.is_set()
    assert (
        host._onyx_v5_provider_circuit.snapshot.state
        is live.ProviderCircuitState.HALF_OPEN
    )


async def exercise_tool_dedupe(contract, controller):
    host = object.__new__(main.OnyxLive)
    host.ui = UI()

    # The original call is captured before V4/V5 installation by main_gate.
    fc = types.SimpleNamespace(id="provider-call-1", name="probe_tool", args={})
    first = await host._execute_tool(fc)
    second = await host._execute_tool(fc)
    assert first is second
    assert first.response == {"result": "probe"}
    assert sum("Duplicate provider tool call" in value for value in host.ui.logs) == 1


def main_gate():
    launcher = runpy.run_path(str(LAUNCHER), run_name="v5_launcher_gate")
    mode = launcher["_launch_mode"]
    assert mode({}) == "legacy"
    assert mode(live.exact_activation_environment()) == "active"
    assert mode(live.exact_rollback_environment()) == "rollback"
    for name in (live.LIVE_MASTER_FLAG, *live.CHILD_FLAGS):
        partial = live.exact_activation_environment()
        partial.pop(name)
        assert mode(partial) == "refuse"
    for spelling in ("true", "True", "1 ", "01", "0"):
        invalid = live.exact_activation_environment()
        invalid[live.LIVE_MASTER_FLAG] = spelling
        assert mode(invalid) == "refuse"

    true_execute = main.OnyxLive._execute_tool
    calls = []

    async def probe_execute(_instance, fc):
        calls.append(fc.id)
        return main.types.FunctionResponse(
            id=fc.id, name=fc.name, response={"result": "probe"}
        )

    main.OnyxLive._execute_tool = probe_execute
    try:
        contract = live.preflight_host(main)
        baseline = seams(contract)
        provisions = []

        def factory():
            provisions.append("provision")
            return Authority()

        for failpoint in range(1, live.OnyxLiveActivationV5.TOTAL_SEAM_COUNT + 1):
            failed = live.OnyxLiveActivationV5(
                live.ActivationFlagsV5.from_canonical_environ(
                    live.exact_activation_environment()
                ),
                contract,
                authority_factory=factory,
            )
            try:
                failed.install(fail_after=failpoint)
            except (live.ActivationV5Error, Exception):
                pass
            else:
                raise AssertionError(f"failpoint {failpoint} did not fail")
            assert seams(contract) == baseline
            assert provisions == []

        controller = live.OnyxLiveActivationV5(
            live.ActivationFlagsV5.from_canonical_environ(
                live.exact_activation_environment()
            ),
            contract,
            authority_factory=factory,
        )
        controller.install()
        assert controller.start() is live.ActivationV5State.READY
        assert provisions == ["provision"]
        asyncio.run(exercise_runtime_seams(controller))
        asyncio.run(exercise_tool_dedupe(contract, controller))
        assert calls == ["provider-call-1"]

        assert live.classify_provider_fault(
            RuntimeError(
                "1007 The audio content type (CONTENT_TYPE_AUDIO) is not supported"
            )
        ) is live.ProviderFaultKind.AUDIO_CONTRACT
        assert live.classify_provider_fault(
            RuntimeError("1011 service unavailable")
        ) is live.ProviderFaultKind.UNAVAILABLE
        assert live.classify_provider_fault(
            RuntimeError("API key not valid")
        ) is live.ProviderFaultKind.CREDENTIAL

        breaker = live.ProviderCircuitBreakerV5(
            retry_delays=(1, 3), open_after=2, open_cooldown=10
        )
        breaker.begin_attempt()
        assert breaker.record_failure(live.ProviderFaultKind.AUDIO_CONTRACT) == 1
        breaker.begin_attempt()
        assert breaker.record_failure(live.ProviderFaultKind.UNAVAILABLE) == 10
        assert breaker.snapshot.state is live.ProviderCircuitState.OPEN
        breaker.manual_recovery()
        assert breaker.snapshot.state is live.ProviderCircuitState.HALF_OPEN
        breaker.record_stable()
        assert breaker.snapshot.state is live.ProviderCircuitState.CLOSED
        assert breaker.snapshot.recoveries == 1

        controller.rollback_installation()
        assert seams(contract) == baseline
    finally:
        main.OnyxLive._execute_tool = true_execute

    print("ONYX_LIVE_ACTIVATION_V5_REAL_HOST_OK")
    print(
        "seam_failpoints=18 mime=audio/pcm;rate=16000 "
        "faults=1007-audio/1011/credential replay=deduplicated rollback=exact"
    )


if __name__ == "__main__":
    main_gate()
