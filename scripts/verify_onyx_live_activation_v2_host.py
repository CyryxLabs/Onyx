"""Fresh-process real-host E2E for Onyx Live Activation V2."""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core import onyx_live_activation_v2 as live  # noqa: E402
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
        self.prompted = False

    def reconcile(self):
        return self.snapshot

    def begin_contact(self):
        if self.snapshot.display_name or self.prompted:
            return None
        self.prompted = True
        return "Before we continue, what name should I use for you?"

    def prompt_directive(self):
        return "owner-directive"

    def set_name(self, value):
        self.snapshot = Snapshot(str(value))
        return self.snapshot

    def correct_name(self, value):
        return self.set_name(value)

    def forget_name(self):
        self.snapshot = Snapshot()
        self.prompted = False
        return self.snapshot


class Projection:
    def __init__(self):
        self.ownerName = "Sir"

    def set_owner_name(self, value):
        self.ownerName = value


class NameInput:
    def __init__(self):
        self.value = "Sir"
        self.fail = False

    def text(self):
        return self.value

    def setText(self, value):
        if self.fail:
            self.value = value
            self.fail = False
            raise RuntimeError("projection failure")
        self.value = value


class UI:
    def __init__(self):
        self.logs = []
        self._win = types.SimpleNamespace(
            _v5_projection=Projection(),
            _overlay=types.SimpleNamespace(_name_input=NameInput()),
        )

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
    )


def main_gate():
    contract = live.preflight_host(main)
    baseline = seams(contract)
    calls = []

    def factory():
        calls.append("provision")
        return Authority()

    failed = live.OnyxLiveActivationV2(
        live.ActivationFlagsV2.from_canonical_environ(),
        contract,
        authority_factory=factory,
    )
    try:
        failed.install(fail_after=4)
    except live.ActivationV2Error:
        pass
    else:
        raise AssertionError("injected installation failure was not raised")
    assert seams(contract) == baseline
    assert calls == []

    controller = live.OnyxLiveActivationV2(
        live.ActivationFlagsV2.from_canonical_environ(),
        contract,
        authority_factory=factory,
    )
    controller.install()
    assert calls == []
    assert controller.start() is live.ActivationV2State.READY
    assert calls == ["provision"]

    host = object.__new__(main.OnyxLive)
    host.ui = UI()
    host._dashboard = None
    host._phase5 = None
    controller.bind_live_instance(host)

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
        result = bridge.catalog_read(reference, {"page_size": 1})
        assert result["state"] == "completed"
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

    assert controller.set_name("Alice").display_name == "Alice"
    assert host.ui._win._v5_projection.ownerName == "Alice"
    assert host.ui._win._overlay._name_input.value == "Alice"
    assert controller.correct_name("Renée").display_name == "Renée"
    assert host.ui._win._v5_projection.ownerName == "Renée"
    assert host.ui._win._overlay._name_input.value == "Renée"
    assert controller.forget_name().display_name is None
    assert host.ui._win._v5_projection.ownerName == "Sir"
    assert host.ui._win._overlay._name_input.value == "Sir"

    host.ui._win._overlay._name_input.fail = True
    try:
        controller.set_name("Bob")
    except live.ActivationV2Error:
        pass
    else:
        raise AssertionError("projection failure did not fail closed")
    assert host.ui._win._v5_projection.ownerName == "Sir"
    assert host.ui._win._overlay._name_input.value == "Sir"
    assert controller.state is live.ActivationV2State.DEGRADED

    controller.rollback_installation()
    assert seams(contract) == baseline
    print("ONYX_LIVE_ACTIVATION_V2_REAL_HOST_OK")
    print("reconnects=64 catalog_reads=64 session_trace_ids=128")


if __name__ == "__main__":
    main_gate()
