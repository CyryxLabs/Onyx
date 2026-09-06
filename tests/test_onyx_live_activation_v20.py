from __future__ import annotations

import runpy
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v19 as v19
from core import onyx_live_activation_v20 as v20
from core.advanced_operations_controller_v1 import (
    HOST_CONTROLLER,
    AdvancedOperationsControllerV1,
)
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1


def _activation(monkeypatch: pytest.MonkeyPatch):
    module = ModuleType("v20_test_host")

    class Host:
        def __init__(self, ui):
            self.ui = ui
            self.constructed_by_v19 = True

        def _execute_tool(self):
            return None

        def _run_live_loop(self):
            return None

        def _send_realtime(self):
            return None

        def _start_phase5_session(self):
            return None

        def _stop_phase5_session(self):
            return None

    module.OnyxLive = Host
    base_contract = object.__new__(v19.HostContractV19)
    contract = v20.HostContractV20(module, Host, Path.cwd(), base_contract)
    base_flags = object.__new__(v19.ActivationFlagsV19)
    wiring = object.__new__(Phase6LiveWiringV1)
    wiring._lock = threading.RLock()
    wiring._installed = True
    wiring._installed_values = {"__init__": Host.__init__}

    def fake_init(self, *_args, **_kwargs):
        self._installed = False
        self.wiring_controller = wiring

    def fake_install(self, *, fail_after=None):
        self._installed = fail_after is None

    def fake_instantiate(self, ui):
        return Host(ui)

    monkeypatch.setattr(v19.OnyxLiveActivationV19, "__init__", fake_init)
    monkeypatch.setattr(v19.OnyxLiveActivationV19, "install", fake_install)
    monkeypatch.setattr(v19.OnyxLiveActivationV19, "instantiate_live", fake_instantiate)
    monkeypatch.setattr(v19.OnyxLiveActivationV19, "rollback_all", lambda _self: None)
    activation = v20.OnyxLiveActivationV20(
        v20.ActivationFlagsV20(True, True, base_flags),
        contract,
    )
    return module, Host, activation


def test_v20_is_default_off_and_restores_exact_v19(monkeypatch: pytest.MonkeyPatch) -> None:
    inactive = {"UNCHANGED": "yes"}
    assert v20.restore_v19_environment(inactive) == inactive
    with pytest.raises(v20.ActivationV20Error, match="not canonical V20"):
        v20.ActivationFlagsV20.from_canonical_environ(inactive)
    mixed = {
        "UNCHANGED": "yes",
        v20.LIVE_MASTER_FLAG: "1",
        v20.FEATURE_FLAG: "true",
        v20.LIVE_ROLLBACK_FLAG: "1",
    }
    assert v20.restore_v19_environment(mixed) == {"UNCHANGED": "yes"}


def test_v20_finds_phase6_authority_across_non_delegating_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation = _activation(monkeypatch)
    wiring = activation._base.wiring_controller
    activation._base = SimpleNamespace(
        _base=SimpleNamespace(_base=SimpleNamespace(wiring_controller=wiring))
    )
    assert activation._phase6_wiring() is wiring


def test_v20_constructs_v19_first_then_binds_lazy_controller_and_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, host, activation = _activation(monkeypatch)
    ui = SimpleNamespace()
    protected = tuple(getattr(host, name) for name in v20._PROTECTED_SEAMS)
    activation.install()
    wiring = activation._base.wiring_controller
    assert wiring._installed_values["__init__"] is host.__init__
    instance = activation.instantiate_live(ui)
    try:
        assert instance.constructed_by_v19 is True
        assert type(getattr(instance, HOST_CONTROLLER)) is AdvancedOperationsControllerV1
        assert callable(ui.on_advanced_status)
        assert callable(ui.on_advanced_attention)
        assert ui.on_advanced_status()["status"] == "waiting_for_live_session"
        assert tuple(getattr(host, name) for name in v20._PROTECTED_SEAMS) == protected
    finally:
        activation.rollback_to_v19()
    assert not hasattr(instance, HOST_CONTROLLER)
    assert not hasattr(ui, "on_advanced_status")
    assert not hasattr(ui, "on_advanced_attention")
    assert wiring._installed_values["__init__"] is host.__init__


def test_v20_rollback_restores_exact_constructor_and_preserves_later_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, host, activation = _activation(monkeypatch)
    original = host.__init__
    def prior_attention():
        return "prior"

    ui = SimpleNamespace(on_advanced_attention=prior_attention)
    activation.install()
    instance = activation.instantiate_live(ui)
    def replacement():
        return "later"

    ui.on_advanced_status = replacement
    activation.rollback_to_v19()
    assert host.__init__ is original
    assert ui.on_advanced_status is replacement
    assert ui.on_advanced_attention is prior_attention
    assert not hasattr(instance, HOST_CONTROLLER)


@pytest.mark.parametrize("offset", [1, 2])
def test_v20_install_failpoints_restore_v19_exactly(
    monkeypatch: pytest.MonkeyPatch, offset: int
) -> None:
    _module, host, activation = _activation(monkeypatch)
    original = host.__init__
    with pytest.raises(v20.ActivationV20Error, match="injected V20"):
        activation.install(fail_after=activation.BASE_SEAM_COUNT + offset)
    assert host.__init__ is original
    assert not hasattr(host, v20.HOST_MARKER)
    assert activation.advanced_operations_capability == "inactive"


def test_v20_close_is_idempotent_through_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, _host, activation = _activation(monkeypatch)
    instance = activation.install() or activation.instantiate_live(SimpleNamespace())
    controller = getattr(instance, HOST_CONTROLLER)
    activation.rollback_to_v19()
    assert controller.closed is True


def test_v20_binds_native_workspace_events_only_when_canonical_flag_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation = _activation(monkeypatch)
    calls: list[bool] = []

    def request(_self):
        calls.append(True)

    monkeypatch.setattr(
        AdvancedOperationsControllerV1, "request_native_workspace_events", request
    )
    monkeypatch.setenv(v20.NATIVE_WORKSPACE_EVENTS_FLAG, "true")
    activation.install()
    activation.instantiate_live(SimpleNamespace())
    try:
        assert calls == [True]
    finally:
        activation.rollback_to_v19()


def test_v20_bootstrap_defaults_on_windows_and_rolls_back_to_v19(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "bootstrap_onyx_live_v20.pyw"
        ),
        run_name="onyx_v20_bootstrap_test",
    )
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    monkeypatch.setitem(namespace, "_default_workspace_root", lambda: tmp_path)
    mode, environment = namespace["_bootstrap_environment"]({})
    assert mode == "v20"
    assert environment[v20.LIVE_MASTER_FLAG] == "1"
    assert environment[v20.FEATURE_FLAG] == "true"
    assert environment[v19.LIVE_MASTER_FLAG] == "1"

    mode, environment = namespace["_bootstrap_environment"](
        {"KEEP": "yes", v20.LIVE_ROLLBACK_FLAG: "1"}
    )
    assert (mode, environment) == ("v19", {"KEEP": "yes"})
