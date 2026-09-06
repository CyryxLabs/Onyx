from __future__ import annotations

import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v24 as v24
from core import onyx_live_activation_v25 as v25
from core import permission_broker
from core.permission_broker import set_permission_callback
from core.capability_extensions_controller_v1 import (
    HOST_CONTROLLER,
    CapabilityExtensionsControllerV1,
)
from core.capability_extensions_live_v1 import CapabilityExtensionGatesV1
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1
from core.phase6_live_wiring_v1 import (
    SESSION_ATTRIBUTE,
    LiveWiringIdentityV1,
    LiveWiringSessionV1,
)


def _activation(monkeypatch: pytest.MonkeyPatch):
    module = ModuleType("v25_test_host")
    module.TOOL_DECLARATIONS = []

    class Response:
        def __init__(self, *, id, name, response):
            self.id = id
            self.name = name
            self.response = response

    class Host:
        def __init__(self, ui):
            self.ui = ui
            self._external_action_tasks = set()

        async def _execute_tool(self, function_call):
            return Response(id=function_call.id, name=function_call.name, response={"legacy": True})

        async def _run_external_action(self, action, /, *args, **kwargs):
            return action(*args, **kwargs)

        @staticmethod
        def _runtime_input_is_quiesced():
            return False

    module.OnyxLive = Host
    module.types = SimpleNamespace(FunctionResponse=Response)
    module.authorize_model_tool = permission_broker.authorize_model_tool
    module.set_audit_trace_id = permission_broker.set_audit_trace_id
    module.reset_audit_trace_id = permission_broker.reset_audit_trace_id

    base_contract = object.__new__(v24.HostContractV24)
    object.__setattr__(base_contract, "module", module)
    object.__setattr__(base_contract, "project", Path.cwd())
    object.__setattr__(base_contract, "base", SimpleNamespace(onyx_live=Host))
    contract = v25.HostContractV25(module, Host, Path.cwd(), base_contract)
    base_flags = object.__new__(v24.ActivationFlagsV24)
    flags = v25.ActivationFlagsV25(base_flags, CapabilityExtensionGatesV1())
    wiring = object.__new__(Phase6LiveWiringV1)
    wiring._lock = threading.RLock()
    wiring._installed = True
    wiring._installed_values = {"__init__": Host.__init__}
    wiring._protected = {}

    def fake_init(self, *_args, **_kwargs):
        self._installed = False
        self._bindings = []
        self._wiring_controller = wiring

    def fake_install(self):
        self._installed = True

    def fake_instantiate(self, ui):
        return Host(ui)

    def fake_rollback(self):
        self._installed = False
        if getattr(module, v24.HOST_MARKER, None) is self:
            delattr(module, v24.HOST_MARKER)

    monkeypatch.setattr(v24.OnyxLiveActivationV24, "__init__", fake_init)
    monkeypatch.setattr(v24.OnyxLiveActivationV24, "install", fake_install)
    monkeypatch.setattr(v24.OnyxLiveActivationV24, "instantiate_live", fake_instantiate)
    monkeypatch.setattr(v24.OnyxLiveActivationV24, "rollback_all", fake_rollback)
    activation = v25.OnyxLiveActivationV25(flags, contract)
    return module, Host, wiring, activation


def _live_session(tmp_path: Path) -> LiveWiringSessionV1:
    session = object.__new__(LiveWiringSessionV1)
    object.__setattr__(
        session,
        "identity",
        LiveWiringIdentityV1(
            "workspace-personal", "account-primary", "owner-primary", "principal-primary"
        ),
    )
    object.__setattr__(session, "session_key", "session-v25")
    object.__setattr__(session, "state_path", tmp_path / "phase6.sqlite3")
    object.__setattr__(session, "receipt_path", tmp_path / "receipts.sqlite3")
    object.__setattr__(session, "facade", SimpleNamespace())
    object.__setattr__(session, "binding_digest", "0" * 64)
    object.__setattr__(session, "_closed", False)
    return session


def test_v25_exact_environment_is_explicitly_default_off(tmp_path: Path) -> None:
    environment = v25.exact_activation_environment([tmp_path])
    flags = v25.ActivationFlagsV25.from_canonical_environ(environment)
    assert flags.gates == CapabilityExtensionGatesV1()
    assert all(environment[name] == "false" for name in v25.FEATURE_FLAGS)
    with pytest.raises(v25.ActivationV25Error, match="not canonical V25"):
        v25.ActivationFlagsV25.from_canonical_environ({})


def test_v25_model_schema_has_no_pairing_claim_or_display_code() -> None:
    declaration = v25.tool_declaration_v25()
    parameters = declaration["parameters"]
    properties = parameters["properties"]
    assert "claim_pairing" not in properties["action"]["enum"]
    assert "display_code" not in properties
    assert "claim_pairing" not in v25._ACTIONS


def test_v25_adds_one_declaration_controller_and_reversible_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, host, wiring, activation = _activation(monkeypatch)
    original_init = host.__init__
    original_execute = host._execute_tool
    activation.install()
    instance = activation.instantiate_live(SimpleNamespace())
    assert [item["name"] for item in module.TOOL_DECLARATIONS] == [v25.TOOL_NAME]
    assert permission_broker.MODEL_TOOL_POLICIES[v25.TOOL_NAME] == "action_policy"
    assert "claim_pairing" not in permission_broker.MODEL_TOOL_ACTIONS[v25.TOOL_NAME]
    assert type(getattr(instance, HOST_CONTROLLER)) is CapabilityExtensionsControllerV1
    assert type(instance) is not host
    activation.rollback_to_v24()
    assert host.__init__ is original_init
    assert host._execute_tool is original_execute
    assert wiring._installed_values["__init__"] is original_init
    assert module.TOOL_DECLARATIONS == []
    assert v25.TOOL_NAME not in permission_broker.MODEL_TOOL_POLICIES
    assert type(instance) is host
    assert not hasattr(instance, HOST_CONTROLLER)
    assert getattr(module, v24.HOST_MARKER) is activation._base


@pytest.mark.parametrize("fail_after", [1, 2, 3, 4, 5])
def test_v25_failpoints_restore_every_owned_seam(
    monkeypatch: pytest.MonkeyPatch, fail_after: int
) -> None:
    module, host, wiring, activation = _activation(monkeypatch)
    original_init = host.__init__
    with pytest.raises(v25.ActivationV25Error, match="injected V25"):
        activation.install(fail_after=fail_after)
    assert host.__init__ is original_init
    assert wiring._installed_values["__init__"] is original_init
    assert module.TOOL_DECLARATIONS == []
    assert v25.TOOL_NAME not in permission_broker.MODEL_TOOL_POLICIES
    assert not hasattr(module, v24.HOST_MARKER)
    assert not hasattr(host, v25.HOST_MARKER)


def test_unknown_tool_delegates_to_v24_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, _wiring, activation = _activation(monkeypatch)
    activation.install()
    instance = activation.instantiate_live(SimpleNamespace())
    result = __import__("asyncio").run(
        instance._execute_tool(SimpleNamespace(id="fc-legacy", name="legacy_tool", args={}))
    )
    assert result.response == {"legacy": True}
    activation.rollback_all()


def test_v25_tool_dispatch_uses_registered_central_policy_and_controller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, _host, _wiring, activation = _activation(monkeypatch)
    monkeypatch.setattr(v25, "append_tool_audit", lambda **_kwargs: "a" * 64)
    activation.install()
    states = []
    ui = SimpleNamespace(muted=False, set_state=states.append)
    instance = activation.instantiate_live(ui)
    setattr(instance, SESSION_ATTRIBUTE, _live_session(tmp_path))
    set_permission_callback(lambda request: request["digest"])
    try:
        result = __import__("asyncio").run(
            instance._execute_tool(
                SimpleNamespace(id="fc-v25", name=v25.TOOL_NAME, args={"action": "status"})
            )
        )
    finally:
        set_permission_callback(None)
    assert result.response["contract"] == "OnyxCapabilityExtensionsStatus.v1"
    assert result.response["external_dispatch"] is False
    assert states[-1] == "LISTENING"
    activation.rollback_all()


def test_v25_audit_never_receives_pairing_code_content_or_accessibility_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, _wiring, activation = _activation(monkeypatch)
    observed = []
    monkeypatch.setattr(
        v25,
        "append_tool_audit",
        lambda **kwargs: observed.append(kwargs) or "a" * 64,
    )
    activation.install()
    ui = SimpleNamespace(muted=False, set_state=lambda _state: None)
    instance = activation.instantiate_live(ui)
    sensitive = {
        "action": "claim_pairing",
        "pairing_id": "pair_example",
        "display_code": "2345-6789",
        "content": "private-message-body",
        "value": "private-accessibility-value",
    }
    __import__("asyncio").run(
        instance._execute_tool(
            SimpleNamespace(id="fc-sensitive", name=v25.TOOL_NAME, args=sensitive)
        )
    )
    encoded = repr(observed[-1]["arguments"])
    assert "2345-6789" not in encoded
    assert "private-message-body" not in encoded
    assert "private-accessibility-value" not in encoded
    assert observed[-1]["arguments"]["sensitive_fields_redacted"] == (
        "content",
        "display_code",
        "value",
    )
    activation.rollback_all()


def test_v25_rejects_approved_broker_result_without_nonempty_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, _host, _wiring, activation = _activation(monkeypatch)
    module.authorize_model_tool = lambda _name, _arguments: (True, "")
    monkeypatch.setattr(v25, "append_tool_audit", lambda **_kwargs: "a" * 64)
    activation.install()
    ui = SimpleNamespace(muted=False, set_state=lambda _state: None)
    instance = activation.instantiate_live(ui)
    setattr(instance, SESSION_ATTRIBUTE, _live_session(tmp_path))
    result = __import__("asyncio").run(
        instance._execute_tool(
            SimpleNamespace(id="fc-empty-proof", name=v25.TOOL_NAME, args={"action": "status"})
        )
    )
    assert "returned no authorization proof" in result.response["result"]
    controller = getattr(instance, HOST_CONTROLLER)
    assert controller._extensions is not None
    assert not hasattr(controller, "_issue_authorization")
    assert not hasattr(controller._extensions, "_issue_authorization")
    activation.rollback_all()
