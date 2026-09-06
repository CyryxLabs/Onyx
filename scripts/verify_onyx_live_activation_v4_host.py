"""Fresh-process real-host non-GUI gate for Onyx Live Activation V4."""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core import onyx_live_activation_v4 as live  # noqa: E402
from core import phase5_integration_v3  # noqa: E402
from core.phase5_integration_v3 import LOCAL_CATALOG_TOOL  # noqa: E402


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
        window._configured_owner_name,
        window._on_setup_done,
        window.__init__,
        window.closeEvent,
    )


def main_gate():
    contract = live.preflight_host(main)
    baseline = seams(contract)
    calls = []

    def factory():
        calls.append("provision")
        return Authority()

    for failpoint in range(1, 12):
        failed = live.OnyxLiveActivationV4(
            live.ActivationFlagsV4.from_canonical_environ(),
            contract,
            authority_factory=factory,
        )
        try:
            failed.install(fail_after=failpoint)
        except live.ActivationV4Error:
            pass
        else:
            raise AssertionError(f"failpoint {failpoint} did not fail")
        assert seams(contract) == baseline
        assert calls == []

    controller = live.OnyxLiveActivationV4(
        live.ActivationFlagsV4.from_canonical_environ(),
        contract,
        authority_factory=factory,
    )
    controller.install()
    assert calls == []
    assert controller.start() is live.ActivationV4State.READY
    assert calls == ["provision"]

    host = object.__new__(main.OnyxLive)
    host.ui = UI()
    host._dashboard = None
    host._phase5 = None
    phase5_integration_v3.append_tool_audit = lambda **_values: "a" * 64
    seen = set()
    pattern = re.compile(r"(?:session|trace)-p\d+-n\d+\Z")
    for index in range(1, 65):
        host._start_phase5_session()
        bridge = host._phase5
        assert bridge is not None
        binding = bridge._binding
        assert pattern.fullmatch(binding.session_id)
        assert pattern.fullmatch(binding.trace_id)
        assert binding.session_id not in seen and binding.trace_id not in seen
        seen.update({binding.session_id, binding.trace_id})
        assert controller.pending_binding is None
        reference = f"reconnect-{index}"
        allowed, reason = bridge.permission_hook(
            LOCAL_CATALOG_TOOL,
            {"page_size": 1, "_phase5_invocation_ref": reference},
        )
        assert allowed, reason
        assert bridge.catalog_read(reference, {"page_size": 1})["state"] == "completed"
        if index == 62:
            assert bridge.kill()["data"]["state"] == "TERMINATED"
            host._stop_phase5_session("kill")
        elif index == 63:
            assert bridge.revoke()["data"]["state"] == "TERMINATED"
            host._stop_phase5_session("revoke")
        elif index == 64:
            host._stop_phase5_session("shutdown")
        else:
            host._stop_phase5_session("reconnect")
        assert host._phase5 is None

    controller.rollback_installation()
    assert seams(contract) == baseline
    print("ONYX_LIVE_ACTIVATION_V4_REAL_HOST_OK")
    print("seam_failpoints=11 reconnects=64 catalog_reads=64 session_trace_ids=128")


if __name__ == "__main__":
    main_gate()

