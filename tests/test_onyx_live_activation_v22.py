from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v21 as v21
from core import onyx_live_activation_v22 as v22
from core.owner_context_controller_v1 import OwnerContextControllerV1
from core.phase6_live_wiring_v1 import (
    SESSION_ATTRIBUTE,
    LiveWiringSessionV1,
    Phase6LiveWiringV1,
)


def _activation(monkeypatch: pytest.MonkeyPatch):
    module = ModuleType("v22_test_host")
    module.TOOL_DECLARATIONS = []
    module.types = SimpleNamespace(
        FunctionResponse=lambda **values: SimpleNamespace(**values)
    )

    class Host:
        def __init__(self, ui):
            self.ui = ui

        async def _execute_tool(self, fc):
            return ("base", fc.name)

        def _build_config(self):
            return SimpleNamespace(system_instruction="base instruction")

    module.OnyxLive = Host
    base_contract = object.__new__(v21.HostContractV21)
    contract = v22.HostContractV22(module, Host, Path.cwd(), base_contract)
    base_flags = object.__new__(v21.ActivationFlagsV21)
    wiring = object.__new__(Phase6LiveWiringV1)
    wiring._lock = threading.RLock()
    wiring._installed = True
    wiring._installed_values = {"__init__": Host.__init__}
    wiring._protected = {"_execute_tool": Host._execute_tool}

    def fake_init(self, *_args, **_kwargs):
        self._installed = False
        self._wiring_controller = wiring

    def fake_install(self, *, fail_after=None):
        self._installed = fail_after is None

    def fake_instantiate(self, ui):
        return Host(ui)

    def fake_rollback(self):
        self._installed = False

    monkeypatch.setattr(v21.OnyxLiveActivationV21, "__init__", fake_init)
    monkeypatch.setattr(v21.OnyxLiveActivationV21, "install", fake_install)
    monkeypatch.setattr(v21.OnyxLiveActivationV21, "instantiate_live", fake_instantiate)
    monkeypatch.setattr(v21.OnyxLiveActivationV21, "rollback_all", fake_rollback)
    monkeypatch.setattr(v22, "append_tool_audit", lambda **_kwargs: None)
    activation = v22.OnyxLiveActivationV22(
        v22.ActivationFlagsV22(True, True, base_flags),
        contract,
    )
    return module, Host, wiring, activation


def _session(tmp_path: Path) -> LiveWiringSessionV1:
    result = object.__new__(LiveWiringSessionV1)
    result.identity = SimpleNamespace(
        profile_id="owner-1", workspace_id="workspace-1"
    )
    result.session_key = "session-1"
    result.state_path = tmp_path / "phase6" / "state.sqlite3"
    result.state_path.parent.mkdir(parents=True)
    result.receipt_path = tmp_path / "receipt.json"
    result.facade = SimpleNamespace()
    result.binding_digest = "digest"
    result._closed = False
    return result


def test_v22_default_off_and_schema_is_bounded() -> None:
    with pytest.raises(v22.ActivationV22Error, match="not canonical V22"):
        v22.ActivationFlagsV22.from_canonical_environ({})
    declaration = v22.tool_declaration_v22()
    assert declaration["name"] == "owner_context"
    properties = declaration["parameters"]["properties"]
    assert properties["action"]["enum"] == ["status", "get", "set", "clear", "verify"]
    assert properties["source"]["enum"] == ["owner_statement"]
    assert "password" not in properties["field"]["enum"]


def test_v22_routes_local_owner_context_and_projects_next_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, host, wiring, activation = _activation(monkeypatch)
    original_init = host.__init__
    original_execute = host._execute_tool
    activation.install()
    instance = activation.instantiate_live(SimpleNamespace())
    setattr(instance, SESSION_ATTRIBUTE, _session(tmp_path))
    try:
        set_response = asyncio.run(
            instance._execute_tool(
                SimpleNamespace(
                    name=v22.TOOL_NAME,
                    args={
                        "action": "set",
                        "field": "priorities",
                        "values": ["Ship Onyx", "Protect focus time"],
                        "source": "owner_statement",
                    },
                    id="call-1",
                )
            )
        )
        assert set_response.response["status"] == "completed"
        assert set_response.response["external_dispatch"] is False
        config = instance._build_config()
        assert config.system_instruction.startswith("base instruction")
        assert "OWNER-PROVIDED DAY-TO-DAY CONTEXT" in config.system_instruction
        assert "priorities=Ship Onyx, Protect focus time" in config.system_instruction
        assert asyncio.run(
            instance._execute_tool(
                SimpleNamespace(name="existing_tool", args={}, id="call-2")
            )
        ) == ("base", "existing_tool")
    finally:
        activation.rollback_all()
    assert host.__init__ is original_init
    assert host._execute_tool is original_execute
    assert wiring._installed_values["__init__"] is original_init
    assert wiring._protected["_execute_tool"] is original_execute
    assert module.TOOL_DECLARATIONS == []


def test_v22_mutation_requires_explicit_owner_statement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _module, _host, _wiring, activation = _activation(monkeypatch)
    activation.install()
    instance = activation.instantiate_live(SimpleNamespace())
    setattr(instance, SESSION_ATTRIBUTE, _session(tmp_path))
    try:
        response = asyncio.run(
            instance._execute_tool(
                SimpleNamespace(
                    name=v22.TOOL_NAME,
                    args={"action": "set", "field": "roles", "values": ["Founder"]},
                    id="call-3",
                )
            )
        )
        assert response.response["status"] == "rejected"
        assert response.response["external_dispatch"] is False
    finally:
        activation.rollback_all()


def test_v22_constructs_zero_polling_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, _host, _wiring, activation = _activation(monkeypatch)
    activation.install()
    instance = activation.instantiate_live(SimpleNamespace())
    controller = getattr(instance, v22.OWNER_CONTEXT_CONTROLLER)
    try:
        assert type(controller) is OwnerContextControllerV1
        assert controller.background_workers == 0
        assert controller.polling_interval is None
    finally:
        activation.rollback_all()


@pytest.mark.parametrize("offset", [1, 2, 3, 4, 5])
def test_v22_failpoints_restore_v21_exactly(
    monkeypatch: pytest.MonkeyPatch, offset: int
) -> None:
    module, host, wiring, activation = _activation(monkeypatch)
    original_init = host.__init__
    original_execute = host._execute_tool
    with pytest.raises(v22.ActivationV22Error, match="injected V22"):
        activation.install(fail_after=activation.BASE_SEAM_COUNT + offset)
    assert host.__init__ is original_init
    assert host._execute_tool is original_execute
    assert wiring._installed_values["__init__"] is original_init
    assert wiring._protected["_execute_tool"] is original_execute
    assert module.TOOL_DECLARATIONS == []
    assert not hasattr(host, v22.HOST_MARKER)
