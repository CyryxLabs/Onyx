"""Fresh-process adversarial host gate for Activation V6."""

from __future__ import annotations

import asyncio
import math
import runpy
import sys
import threading
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core import onyx_live_activation_v5 as frozen_v5  # noqa: E402
from core import onyx_live_activation_v6 as live  # noqa: E402


LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v6.pyw"


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


async def registry_adversarial_gate():
    registry = live.ToolCallRegistryV6()
    calls = 0
    result = {"status": "ok", "items": [1]}

    async def once():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return result

    first, second = await asyncio.gather(
        registry.execute(
            call_id="exact-1", name="tool_a", arguments={"a": 1}, runner=once
        ),
        registry.execute(
            call_id="exact-1", name="tool_a", arguments={"a": 1}, runner=once
        ),
    )
    assert first == result and second == result and calls == 1
    assert first is not second
    first["items"].append(2)
    assert (
        await registry.execute(
            call_id="exact-1", name="tool_a", arguments={"a": 1}, runner=once
        )
        == result
    )
    assert calls == 1
    for changed_name, changed_args in (
        ("tool_b", {"a": 1}),
        ("tool_a", {"a": 2}),
    ):
        try:
            await registry.execute(
                call_id="exact-1",
                name=changed_name,
                arguments=changed_args,
                runner=once,
            )
        except live.ToolIdentityConflictV6:
            pass
        else:
            raise AssertionError("call ID identity conflict was not refused")
    assert calls == 1

    bad_calls = 0

    async def bad():
        nonlocal bad_calls
        bad_calls += 1
        await asyncio.sleep(0)
        raise ValueError("immutable failure")

    errors = await asyncio.gather(
        *(
            registry.execute(
                call_id="error-1", name="bad", arguments={}, runner=bad
            )
            for _ in range(12)
        ),
        return_exceptions=True,
    )
    assert bad_calls == 1
    assert all(type(item) is live.ToolExecutionReplayV6 for item in errors)
    assert len({str(item) for item in errors}) == 1

    window = live.ToolCallRegistryV6()
    executions = 0

    async def value(index):
        nonlocal executions
        executions += 1
        return ("value", index)

    for index in range(1000):
        assert await window.execute(
            call_id=f"id-{index}",
            name="bounded",
            arguments={"index": index},
            runner=lambda index=index: value(index),
        ) == ("value", index)
    snapshot = await window.snapshot()
    assert snapshot.retained == 256
    assert snapshot.completed == 256 and snapshot.inflight == 0
    assert snapshot.evictions == 744 and executions == 1000
    for index in range(744, 1000):
        assert await window.execute(
            call_id=f"id-{index}",
            name="bounded",
            arguments={"index": index},
            runner=lambda index=index: value(index),
        ) == ("value", index)
    assert executions == 1000
    # The explicitly documented replay window is the most recent 256 settled
    # IDs. An ID outside that bounded window can be observed as a new call.
    assert await window.execute(
        call_id="id-0",
        name="bounded",
        arguments={"index": 0},
        runner=lambda: value(0),
    ) == ("value", 0)
    assert executions == 1001
    assert (await window.snapshot()).retained == 256

    saturated = live.ToolCallRegistryV6()
    release = asyncio.Event()
    started = 0

    async def inflight(index):
        nonlocal started
        started += 1
        await release.wait()
        return index

    tasks = [
        asyncio.create_task(
            saturated.execute(
                call_id=f"flight-{index}",
                name="wait",
                arguments={"index": index},
                runner=lambda index=index: inflight(index),
            )
        )
        for index in range(256)
    ]
    while (await saturated.snapshot()).retained < 256:
        await asyncio.sleep(0)
    try:
        await saturated.execute(
            call_id="flight-256",
            name="wait",
            arguments={"index": 256},
            runner=lambda: inflight(256),
        )
    except live.ToolReplayWindowFullV6:
        pass
    else:
        raise AssertionError("257th inflight call did not fail closed")
    assert started <= 256
    snapshot = await saturated.snapshot()
    assert snapshot.retained == 256 and snapshot.inflight == 256
    release.set()
    assert await asyncio.gather(*tasks) == list(range(256))
    assert (await saturated.snapshot()).retained == 256


def numeric_gate():
    numeric_bad = (
        True,
        False,
        0,
        -1,
        float("nan"),
        float("inf"),
        float("-inf"),
        10**1000,
    )
    for bad in numeric_bad:
        for keyword, maximum in (
            ("retry_delays", live.MAX_RETRY_DELAY_SECONDS),
            ("open_cooldown", live.MAX_OPEN_COOLDOWN_SECONDS),
            ("jitter_seconds", live.MAX_JITTER_SECONDS),
            ("stable_close_seconds", live.MAX_STABLE_CLOSE_SECONDS),
        ):
            kwargs = (
                {keyword: (bad,)}
                if keyword == "retry_delays"
                else {keyword: bad}
            )
            try:
                live.ProviderCircuitBreakerV6(**kwargs)
            except live.ActivationV6Error:
                pass
            else:
                raise AssertionError(f"{keyword} accepted invalid value {bad!r}")
        assert math.isfinite(maximum)
    for bad in (True, False, 0, -1, 65, 1.0):
        try:
            live.ProviderCircuitBreakerV6(open_after=bad)
        except live.ActivationV6Error:
            pass
        else:
            raise AssertionError(f"open_after accepted invalid value {bad!r}")
    for kwargs in (
        {"retry_delays": (live.MAX_RETRY_DELAY_SECONDS + 0.001,)},
        {"open_cooldown": live.MAX_OPEN_COOLDOWN_SECONDS + 0.001},
        {"jitter_seconds": live.MAX_JITTER_SECONDS + 0.001},
        {"stable_close_seconds": live.MAX_STABLE_CLOSE_SECONDS + 0.001},
    ):
        try:
            live.ProviderCircuitBreakerV6(**kwargs)
        except live.ActivationV6Error:
            pass
        else:
            raise AssertionError("hard numeric maximum was not enforced")


async def recovery_thread_gate(controller):
    host = types.SimpleNamespace()
    host._loop = asyncio.get_running_loop()
    host._onyx_v6_loop_thread_id = threading.get_ident()
    host._onyx_v6_recovery_event = asyncio.Event()
    host._onyx_v6_provider_circuit = live.ProviderCircuitBreakerV6(
        retry_delays=(0.001,),
        open_after=1,
        open_cooldown=0.001,
        jitter_seconds=0.001,
        stable_close_seconds=0.001,
    )
    await host._onyx_v6_provider_circuit.bind_owner_loop()
    await host._onyx_v6_provider_circuit.record_failure(
        frozen_v5.ProviderFaultKind.UNAVAILABLE
    )
    result = []
    errors = []

    def request():
        try:
            result.append(
                controller.request_provider_recovery_from_thread(
                    host, timeout_seconds=2
                )
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=request, daemon=True)
    thread.start()
    while thread.is_alive():
        await asyncio.sleep(0.001)
    thread.join()
    assert not errors and len(result) == 1
    assert result[0].accepted
    assert result[0].state is live.ProviderCircuitStateV6.HALF_OPEN
    assert host._onyx_v6_recovery_event.is_set()
    assert (
        (await host._onyx_v6_provider_circuit.snapshot()).state
        is live.ProviderCircuitStateV6.HALF_OPEN
    )

    def wrong_loop():
        try:
            asyncio.run(host._onyx_v6_provider_circuit.snapshot())
        except BaseException as exc:
            return exc
        return None

    affinity_error = await asyncio.to_thread(wrong_loop)
    assert type(affinity_error) is live.CircuitLoopAffinityV6


def main_gate():
    launcher = runpy.run_path(str(LAUNCHER), run_name="v6_launcher_gate")
    mode = launcher["_launch_mode"]
    assert mode({}) == "legacy"
    assert mode(live.exact_activation_environment()) == "active"
    assert mode(live.exact_rollback_environment()) == "rollback"
    for name in (live.LIVE_MASTER_FLAG, *live.CHILD_FLAGS):
        partial = live.exact_activation_environment()
        partial.pop(name)
        assert mode(partial) == "refuse"

    numeric_gate()
    asyncio.run(registry_adversarial_gate())

    true_execute = main.OnyxLive._execute_tool
    host_calls = []

    async def probe_execute(_instance, fc):
        host_calls.append((fc.id, fc.name, dict(fc.args or {})))
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

        flags = live.ActivationFlagsV6.from_canonical_environ(
            live.exact_activation_environment()
        )
        for failpoint in range(1, live.OnyxLiveActivationV6.TOTAL_SEAM_COUNT + 1):
            failed = live.OnyxLiveActivationV6(
                flags, contract, authority_factory=factory
            )
            try:
                failed.install(fail_after=failpoint)
            except Exception:
                pass
            else:
                raise AssertionError(f"failpoint {failpoint} did not fail")
            assert seams(contract) == baseline
            assert provisions == []

        controller = live.OnyxLiveActivationV6(
            flags, contract, authority_factory=factory
        )
        controller.install()
        assert controller.start() is live.ActivationV6State.READY
        assert provisions == ["provision"]
        host = object.__new__(main.OnyxLive)
        host.ui = UI()

        async def host_contract():
            fc = types.SimpleNamespace(
                id="host-id", name="probe", args={"a": 1, "b": [2, 3]}
            )
            first = await host._execute_tool(fc)
            second = await host._execute_tool(fc)
            assert first == second and first is not second
            changed = types.SimpleNamespace(
                id="host-id", name="probe", args={"a": 9}
            )
            refused = await host._execute_tool(changed)
            assert refused.response["error"] == "ToolIdentityConflictV6"
            assert len(host_calls) == 1
            await recovery_thread_gate(controller)

        asyncio.run(host_contract())
        controller.rollback_installation()
        assert seams(contract) == baseline
    finally:
        main.OnyxLive._execute_tool = true_execute

    print("ONYX_LIVE_ACTIVATION_V6_REAL_HOST_OK")
    print(
        "seam_failpoints=22 call_id=exact args_digest=canonical "
        "single_flight=pass conflicts=fail-closed replay_window=256 "
        "ids_tested=1000 inflight_257=refused numeric_edges=pass "
        "manual_recovery=cross-thread-ack loop_affinity=pass rollback=exact"
    )


if __name__ == "__main__":
    main_gate()
