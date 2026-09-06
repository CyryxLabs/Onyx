"""Local fake-provider E2E for V6: 1007, 1011, recovery, 601 seconds."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core import onyx_live_activation_v6 as live  # noqa: E402


class Snapshot:
    display_name = None
    reconciled = True
    state = types.SimpleNamespace(value="unknown")
    name_known = False


class Authority:
    def __init__(self):
        self.snapshot = Snapshot()

    def reconcile(self):
        return self.snapshot

    def begin_contact(self):
        return "Before we continue, what name should I use for you?"

    def prompt_directive(self):
        return "owner-directive"


class FakeUI:
    def __init__(self):
        self.logs = []
        self.states = []
        self.prompt_count = 0
        self.muted = False
        self._win = types.SimpleNamespace(_hud_v5_live=True)

    def write_log(self, value):
        self.logs.append(value)

    def set_state(self, value):
        self.states.append(value)

    def prompt_reconfig(self):
        self.prompt_count += 1


class FakeDashboard:
    def __init__(self):
        self.serve_count = 0
        self.callback_count = 0
        self.broadcasts = []
        self._command_queue = asyncio.Queue()
        self._phone_audio_queue = asyncio.Queue()

    def set_connect_callback(self, _callback):
        self.callback_count += 1

    async def serve(self):
        self.serve_count += 1
        await asyncio.Event().wait()

    async def broadcast(self, value):
        self.broadcasts.append(dict(value))


class FakeSession:
    def __init__(self, attempt):
        self.attempt = attempt
        self.media = []
        self.media_sent = asyncio.Event()

    async def send_realtime_input(self, *, media):
        self.media.append(dict(media))
        self.media_sent.set()


class FakeConnect:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


class FakeLive:
    def __init__(self, factory):
        self.factory = factory

    def connect(self, *, model, config):
        assert model == "fake-live-model"
        assert config == {"fake": "config"}
        self.factory.attempts += 1
        session = FakeSession(self.factory.attempts)
        self.factory.sessions.append(session)
        return FakeConnect(session)


class FakeClient:
    def __init__(self, factory):
        self.aio = types.SimpleNamespace(live=FakeLive(factory))


class FakeClientFactory:
    def __init__(self):
        self.attempts = 0
        self.sessions = []

    def __call__(self):
        return FakeClient(self)


async def wait_forever():
    await asyncio.Event().wait()


async def e2e(controller):
    dashboard = FakeDashboard()
    clients = FakeClientFactory()
    stable = asyncio.Event()
    simulated_seconds = 0

    host = object.__new__(main.OnyxLive)
    host.ui = FakeUI()
    host.session = None
    host.audio_in_queue = None
    host.out_queue = None
    host._loop = None
    host._dashboard = None
    host._phase5 = None
    host._briefing_sent = False
    host._speaking_lock = threading.Lock()
    host._is_speaking = False
    host._pending_vision = None
    host._vision_cam_active = False
    host._vision_close_pending = False
    host._vision_busy = False
    host._vision_last_time = 0.0
    host._interrupted = False
    host._onyx_v6_dashboard_factory = lambda: dashboard
    host._onyx_v6_client_factory = clients
    host._start_phase5_session = lambda: None
    host._stop_phase5_session = lambda _reason: None
    host._build_config = lambda: {"fake": "config"}
    host._on_phone_connected = lambda: None
    host.set_speaking = lambda _value: None
    host._run_system_monitor = wait_forever
    host._run_proactive_mode = wait_forever
    host._play_audio = wait_forever
    host._relay_phone_audio = wait_forever
    host._send_startup_briefing = wait_forever

    async def listen_audio():
        await host.out_queue.put(
            {"data": b"\x01\x00" * 128, "mime_type": "audio/pcm"}
        )
        await asyncio.Event().wait()

    async def receive_audio():
        nonlocal simulated_seconds
        session = host.session
        await session.media_sent.wait()
        if session.attempt == 1:
            raise RuntimeError(
                "1007 The audio content type (CONTENT_TYPE_AUDIO) "
                "is not supported for this model configuration."
            )
        if session.attempt == 2:
            raise RuntimeError("1011 service unavailable")
        await asyncio.sleep(0.003)
        for _ in range(601):
            simulated_seconds += 1
            assert host.ui._win._hud_v5_live
            assert host._dashboard is dashboard
            assert dashboard.serve_count == 1
            assert host.ui.prompt_count == 0
            await asyncio.sleep(0)
        stable.set()
        await asyncio.Event().wait()

    host._listen_audio = listen_audio
    host._receive_audio = receive_audio

    original_flags = main._load_launch_flags
    original_model = main.resolve_live_model
    original_trust = main.set_trust_profile
    original_autonomy = main.configure_owner_autonomy
    main._load_launch_flags = lambda: (False, False, "cautious", False, ())
    main.resolve_live_model = lambda _path: "fake-live-model"
    main.set_trust_profile = lambda _value: None
    main.configure_owner_autonomy = lambda *_values: None
    task = asyncio.create_task(host._run_live_loop())
    try:
        await asyncio.wait_for(stable.wait(), timeout=15)
        assert clients.attempts == 3
        assert len(clients.sessions) == 3
        assert simulated_seconds == 601
        assert dashboard.serve_count == 1 and dashboard.callback_count == 1
        assert host.session is clients.sessions[2]
        assert host.ui._win._hud_v5_live
        assert host.ui.prompt_count == 0
        assert sum("VOICE DEGRADED" in value for value in host.ui.logs) == 2
        assert any("voice recovered" in value for value in host.ui.logs)
        circuit = await host._onyx_v6_provider_circuit.snapshot()
        assert circuit.state is live.ProviderCircuitStateV6.CLOSED
        assert circuit.recoveries >= 1
        assert all(
            session.media
            and session.media[0]["mime_type"] == live.INPUT_AUDIO_MIME
            for session in clients.sessions
        )
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        main._load_launch_flags = original_flags
        main.resolve_live_model = original_model
        main.set_trust_profile = original_trust
        main.configure_owner_autonomy = original_autonomy
    assert dashboard.serve_count == 1
    return simulated_seconds, clients.attempts, len(dashboard.broadcasts)


def main_gate():
    controller = live.OnyxLiveActivationV6(
        live.ActivationFlagsV6.from_canonical_environ(
            live.exact_activation_environment()
        ),
        live.preflight_host(main),
        authority_factory=Authority,
        circuit_factory=lambda: live.ProviderCircuitBreakerV6(
            retry_delays=(0.001,),
            open_after=2,
            open_cooldown=0.001,
            jitter_seconds=0.001,
            stable_close_seconds=0.001,
            jitter_source=lambda: 0.5,
        ),
    )
    controller.install()
    assert controller.start() is live.ActivationV6State.READY
    seconds, attempts, broadcasts = asyncio.run(e2e(controller))
    controller.rollback_installation()
    print("ONYX_LIVE_ACTIVATION_V6_FAKE_PROVIDER_OK")
    print(
        f"failures=1007,1011 recovery=automatic simulated_seconds={seconds} "
        f"provider_attempts={attempts} dashboard_starts=1 broadcasts={broadcasts} "
        "hud=v5 process=alive listeners=persistent setup_prompts=0"
    )


if __name__ == "__main__":
    main_gate()
