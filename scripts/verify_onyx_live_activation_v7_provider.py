"""Fake-provider V7 E2E with a real Phase 5 bridge across reconnect."""

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
from core import onyx_live_activation_v6 as v6  # noqa: E402
from core import onyx_live_activation_v7 as live  # noqa: E402
from core import phase5_integration_v3 as phase5  # noqa: E402


class Snapshot:
    display_name = None
    reconciled = True
    state = types.SimpleNamespace(value="unknown")
    name_known = False


class Authority:
    def __init__(self) -> None:
        self.snapshot = Snapshot()

    def reconcile(self):
        return self.snapshot

    def begin_contact(self):
        return "Before we continue, what name should I use for you?"

    def prompt_directive(self):
        return "owner-directive"


class FakeUI:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.states: list[str] = []
        self.prompt_count = 0
        self.muted = False
        self._win = types.SimpleNamespace(_hud_v5_live=True)

    def write_log(self, value: str) -> None:
        self.logs.append(value)

    def set_state(self, value: str) -> None:
        self.states.append(value)

    def prompt_reconfig(self) -> None:
        self.prompt_count += 1


class FakeDashboard:
    def __init__(self) -> None:
        self.serve_count = 0
        self.callback_count = 0
        self.broadcasts: list[dict[str, object]] = []
        self.bridges: list[object | None] = []
        self._command_queue: asyncio.Queue[str] = asyncio.Queue()
        self._phone_audio_queue: asyncio.Queue[bytes] = asyncio.Queue()

    def set_connect_callback(self, _callback: object) -> None:
        self.callback_count += 1

    def set_phase5_bridge(self, bridge: object | None) -> None:
        self.bridges.append(bridge)

    async def serve(self) -> None:
        self.serve_count += 1
        await asyncio.Event().wait()

    async def broadcast(self, value: dict[str, object]) -> None:
        self.broadcasts.append(dict(value))


class FakeSession:
    def __init__(self, attempt: int) -> None:
        self.attempt = attempt
        self.media: list[dict[str, object]] = []
        self.media_sent = asyncio.Event()

    async def send_realtime_input(self, *, media: dict[str, object]) -> None:
        self.media.append(dict(media))
        self.media_sent.set()


class FakeConnect:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args: object) -> bool:
        return False


class FakeLive:
    def __init__(self, factory: "FakeClientFactory") -> None:
        self.factory = factory

    def connect(self, *, model: str, config: object) -> FakeConnect:
        assert model == "fake-live-model"
        assert config == {"fake": "config"}
        self.factory.attempts += 1
        session = FakeSession(self.factory.attempts)
        self.factory.sessions.append(session)
        return FakeConnect(session)


class FakeClient:
    def __init__(self, factory: "FakeClientFactory") -> None:
        self.aio = types.SimpleNamespace(live=FakeLive(factory))


class FakeClientFactory:
    def __init__(self) -> None:
        self.attempts = 0
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeClient:
        return FakeClient(self)


async def _forever() -> None:
    await asyncio.Event().wait()


async def e2e() -> tuple[int, int, int]:
    dashboard = FakeDashboard()
    clients = FakeClientFactory()
    ready = asyncio.Event()
    bridge_ids: list[int] = []
    local_reads = 0

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
    host._build_config = lambda: {"fake": "config"}
    host._on_phone_connected = lambda: None
    host.set_speaking = lambda _value: None
    host._run_system_monitor = _forever
    host._run_proactive_mode = _forever
    host._play_audio = _forever
    host._relay_phone_audio = _forever
    host._send_startup_briefing = _forever

    async def listen_audio() -> None:
        await host.out_queue.put(
            {"data": b"\x01\x00" * 128, "mime_type": "audio/pcm"}
        )
        await asyncio.Event().wait()

    async def receive_audio() -> None:
        nonlocal local_reads
        session = host.session
        await session.media_sent.wait()
        bridge = host._phase5
        assert type(bridge) is phase5.Phase5IntegrationV3
        assert bridge.local_catalog_enabled
        assert bridge.tool_declarations()[0]["name"] == "local_catalog_read"
        assert (
            bridge.binding.workspace_id,
            bridge.binding.account_id,
            bridge.binding.profile_id,
        ) == (
            "onyx-local-workspace",
            "cyryx-local-account",
            "onyx-owner-profile",
        )
        bridge_ids.append(id(bridge))
        if session.attempt == 1:
            raise RuntimeError("1011 service unavailable")
        function_call = types.SimpleNamespace(
            id="provider-call-v7-1",
            name="local_catalog_read",
            args={"page_size": 5},
        )
        response = await host._execute_tool(function_call)
        result = response.response["result"]
        assert result["state"] == "completed"
        assert result["operation"] == "catalog_read"
        assert result["egress"] == "none"
        assert len(result["items"]) == 5
        diagnostic = host._onyx_v7_phase5_last_diagnostic
        assert diagnostic == live.Phase5AuthorizationDiagnosticV7(
            "READY", "allowed", True
        )
        local_reads += 1
        replay = await host._execute_tool(function_call)
        assert replay.response == response.response
        assert host._onyx_v7_phase5_last_diagnostic == diagnostic
        ready.set()
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
        await asyncio.wait_for(ready.wait(), timeout=15)
        assert clients.attempts == 2
        assert len(set(bridge_ids)) == 2
        assert local_reads == 1
        assert dashboard.serve_count == 1
        assert dashboard.callback_count == 1
        assert host._phase5 is not None
        assert host.session is clients.sessions[1]
        assert host.ui._win._hud_v5_live
        assert host.ui.prompt_count == 0
        assert all(
            item.media and item.media[0]["mime_type"] == v6.INPUT_AUDIO_MIME
            for item in clients.sessions
        )
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        main._load_launch_flags = original_flags
        main.resolve_live_model = original_model
        main.set_trust_profile = original_trust
        main.configure_owner_autonomy = original_autonomy
    assert host._phase5 is None
    return clients.attempts, len(set(bridge_ids)), local_reads


def run() -> None:
    environment = live.exact_activation_environment()
    controller = live.OnyxLiveActivationV7(
        live.ActivationFlagsV7.from_canonical_environ(environment),
        live.preflight_host(main, environment),
        authority_factory=Authority,
        circuit_factory=lambda: v6.ProviderCircuitBreakerV6(
            retry_delays=(0.001,),
            open_after=2,
            open_cooldown=0.001,
            jitter_seconds=0.001,
            stable_close_seconds=0.001,
            jitter_source=lambda: 0.5,
        ),
    )
    controller.install()
    assert controller.start().value == "ready"
    try:
        attempts, bridges, reads = asyncio.run(e2e())
    finally:
        controller.rollback_installation()
    print("ONYX_LIVE_ACTIVATION_V7_PHASE5_E2E_OK")
    print(
        f"phase5=ready provider_attempts={attempts} bridges={bridges} "
        f"local_catalog_reads={reads} reconnect=continuous "
        "mime=audio/pcm;rate=16000 network_calls=0 live_activation=not_performed"
    )


if __name__ == "__main__":
    run()
