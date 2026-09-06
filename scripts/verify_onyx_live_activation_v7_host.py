"""Fresh-process host and launch-contract gate for Activation V7."""

from __future__ import annotations

import asyncio
import runpy
import socket
import sys
import types
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core import onyx_live_activation_v7 as live  # noqa: E402
from core import phase5_integration_v3 as phase5  # noqa: E402


LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v7.pyw"


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


class DiagnosticUI:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.states: list[str] = []
        self.muted = False

    def write_log(self, value: str) -> None:
        self.logs.append(value)

    def set_state(self, value: str) -> None:
        self.states.append(value)


def _seams(contract: live.HostContractV7) -> tuple[object, ...]:
    module = contract.module
    host = contract.base.onyx_live
    window = contract.base.main_window
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


def run() -> None:
    environment = live.exact_activation_environment()
    launcher = runpy.run_path(str(LAUNCHER), run_name="v7_host_gate")
    launch_mode = launcher["_launch_mode"]
    assert launch_mode({}) == "legacy"
    assert launch_mode(environment) == "active"
    assert launch_mode(live.exact_rollback_environment()) == "rollback"

    refused = 0
    for name in (
        live.LIVE_MASTER_FLAG,
        *live.CHILD_FLAGS,
        *live.PHASE5_IDENTITY_FLAGS,
    ):
        candidate = dict(environment)
        candidate.pop(name)
        assert launch_mode(candidate) == "refuse"
        refused += 1
    for name in live.PHASE5_IDENTITY_FLAGS:
        candidate = dict(environment)
        candidate[name] += "-wrong"
        assert launch_mode(candidate) == "refuse"
        refused += 1
    for alias in live.PHASE5_IDENTITY_ALIASES:
        candidate = dict(environment)
        candidate[alias] = environment[live.PHASE5_PRINCIPAL_ID]
        assert launch_mode(candidate) == "refuse"
        refused += 1
    for value in ("true", "TRUE", "yes", "0", ""):
        candidate = dict(environment)
        candidate[live.LIVE_MASTER_FLAG] = value
        assert launch_mode(candidate) == "refuse"
        refused += 1

    network_calls = 0

    def refuse_network(*_args: object, **_kwargs: object) -> None:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("preflight attempted a network connection")

    with patch.object(socket.socket, "connect", refuse_network):
        contract = live.preflight_host(main, environment)
    probe = contract.phase5_probe
    assert probe.bridge_type == "core.phase5_integration_v3.Phase5IntegrationV3"
    assert probe.catalog_entries == len(main.TOOL_DECLARATIONS)
    assert probe.local_catalog_declarations == 1
    assert (
        probe.principal_id,
        probe.workspace_id,
        probe.account_id,
        probe.profile_id,
    ) == (
        "onyx-owner",
        "onyx-local-workspace",
        "cyryx-local-account",
        "onyx-owner-profile",
    )
    assert network_calls == 0

    original = _seams(contract)
    failed_controller = live.OnyxLiveActivationV7(
        live.ActivationFlagsV7.from_canonical_environ(environment),
        contract,
        authority_factory=Authority,
    )
    try:
        failed_controller.install(fail_after=failed_controller.TOTAL_SEAM_COUNT)
    except live.ActivationV7Error:
        pass
    else:
        raise AssertionError("V7 seam failpoint was not injected")
    assert _seams(contract) == original

    controller = live.OnyxLiveActivationV7(
        live.ActivationFlagsV7.from_canonical_environ(environment),
        contract,
        authority_factory=Authority,
    )
    controller.install()
    assert controller.start().value == "ready"
    assert _seams(contract) != original

    bridge = phase5.create_phase5_integration_v3(
        session_id="session-v7-diagnostic",
        trace_id="trace-v7-diagnostic",
        catalog=live._main_catalog(main),
        environ=environment,
    )
    assert type(bridge) is phase5.Phase5IntegrationV3
    instance = types.SimpleNamespace(_phase5=bridge, ui=DiagnosticUI())
    function_call = types.SimpleNamespace(
        id="diagnostic-call-v7",
        name="local_catalog_read",
        args={"page_size": 0},
    )
    main.set_trust_profile("autonomous")
    main.configure_owner_autonomy(True, (str(ROOT),))
    main.set_phase5_authorization_hook(bridge.permission_hook)
    try:
        response = asyncio.run(
            controller._execute_local_catalog(
                instance, function_call, function_call.args
            )
        )
    finally:
        main.set_phase5_authorization_hook(None)
        bridge.terminate("rollback")
    diagnostic = instance._onyx_v7_phase5_last_diagnostic
    assert diagnostic == live.Phase5AuthorizationDiagnosticV7(
        "READY", "invalid-request", True
    )
    assert response.response == {
        "result": "Local catalog authorization was refused."
    }
    assert instance.ui.logs[-1] == (
        "ERR: Phase 5 local authorization denied "
        "(state=READY, reason=invalid-request, catalog=enabled)."
    )

    controller.rollback_installation()
    assert _seams(contract) == original

    active_cmd = (ROOT / "scripts" / "launch_onyx_live_v7_active.cmd").read_text(
        encoding="utf-8"
    )
    for name, value in live.CANONICAL_PHASE5_IDENTITY.items():
        assert f'set "{name}={value}"' in active_cmd

    print("ONYX_LIVE_ACTIVATION_V7_HOST_OK")
    print(
        f"canonical_identities=4 refused_variants={refused} "
        f"catalog_entries={probe.catalog_entries} bridge=real "
        f"network_calls={network_calls} seams={controller.TOTAL_SEAM_COUNT} "
        "denial_diagnostic=content-free rollback=exact "
        "live_activation=not_performed"
    )


if __name__ == "__main__":
    run()
