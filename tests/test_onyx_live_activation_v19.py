from __future__ import annotations

import runpy
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v18 as v18
from core import onyx_live_activation_v19 as v19
from core.dayops_connection_v19 import DayOpsConnectionControllerV19
from core.dayops_graph_factory_v19 import PersistentDayOpsGraphFactoryV19
from core.governance_nucleus_v1 import GovernanceIdentityV1, GovernanceNucleusV1


def _activation(monkeypatch: pytest.MonkeyPatch):
    module = ModuleType("v19_test_host")

    class Host:
        pass

    module.OnyxLive = Host
    base_contract = v18.HostContractV18(module, Host, v18.Path.cwd(), object())  # type: ignore[arg-type]
    contract = v19.HostContractV19(module, Host, v18.Path.cwd(), base_contract)
    base_flags = object.__new__(v18.ActivationFlagsV18)

    def fake_init(self, *_args, **_kwargs):
        self._installed = False

    def fake_install(self, *, fail_after=None):
        self._installed = fail_after is None

    monkeypatch.setattr(v18.OnyxLiveActivationV18, "__init__", fake_init)
    monkeypatch.setattr(v18.OnyxLiveActivationV18, "install", fake_install)
    monkeypatch.setattr(v18.OnyxLiveActivationV18, "rollback_to_v17", lambda _self: None)
    controller = v19.OnyxLiveActivationV19(
        v19.ActivationFlagsV19(True, True, base_flags),
        contract,
    )
    live = object.__new__(DayOpsConnectionControllerV19)
    factory = object.__new__(PersistentDayOpsGraphFactoryV19)
    monkeypatch.setattr(DayOpsConnectionControllerV19, "close", lambda _self: None)
    controller._component_factory = lambda _instance, _identity: (live, factory)
    return module, Host, controller, live, factory


def _instance(ui: object) -> SimpleNamespace:
    identity = GovernanceIdentityV1(
        "principal-owner",
        "workspace-primary",
        "account-owner",
        "profile-owner",
        "Primary Workspace",
    )
    nucleus = object.__new__(GovernanceNucleusV1)
    nucleus.identity = identity
    return SimpleNamespace(ui=ui, _governance_nucleus_v1=nucleus)


def test_v19_is_default_off_and_restores_exact_v18() -> None:
    inactive = {"UNCHANGED": "yes"}
    assert v19.restore_v18_environment(inactive) == inactive
    with pytest.raises(v19.ActivationV19Error, match="not canonical V19"):
        v19.ActivationFlagsV19.from_canonical_environ(inactive)
    mixed = {
        "UNCHANGED": "yes",
        v19.LIVE_MASTER_FLAG: "1",
        v19.FEATURE_FLAG: "true",
        v19.LIVE_ROLLBACK_FLAG: "1",
    }
    assert v19.restore_v18_environment(mixed) == {"UNCHANGED": "yes"}


def test_v19_binds_five_host_callbacks_and_restores_exact_predecessors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, host, activation, live, _factory = _activation(monkeypatch)
    prior = {name: (lambda: None) for name in v19.UI_CALLBACKS}
    ui = SimpleNamespace(**prior)
    instance = _instance(ui)
    activation.install()
    activation.initialize_host(instance)
    try:
        assert getattr(host, v19.HOST_MARKER) is activation
        assert getattr(instance, v19.HOST_CONTROLLER) is live
        for name in v19.UI_CALLBACKS:
            assert getattr(ui, name) is not prior[name]
    finally:
        activation.rollback_to_v18()
    assert not hasattr(host, v19.HOST_MARKER)
    assert not hasattr(instance, v19.HOST_CONTROLLER)
    for name in v19.UI_CALLBACKS:
        assert getattr(ui, name) is prior[name]


def test_v19_rollback_preserves_callback_installed_by_later_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, _live, _factory = _activation(monkeypatch)
    ui = SimpleNamespace(**{name: None for name in v19.UI_CALLBACKS})
    instance = _instance(ui)
    activation.install()
    activation.initialize_host(instance)
    def replacement():
        return "later-owner"
    ui.on_dayops_status = replacement
    activation.rollback_to_v18()
    assert ui.on_dayops_status is replacement
    for name in v19.UI_CALLBACKS[1:]:
        assert getattr(ui, name) is None


def test_v19_install_failpoint_rolls_back_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, host, activation, _live, _factory = _activation(monkeypatch)
    with pytest.raises(v19.ActivationV19Error, match="marker failure"):
        activation.install(fail_after=activation.BASE_SEAM_COUNT + 1)
    assert not hasattr(host, v19.HOST_MARKER)
    assert activation.dayops_capability == "inactive"


def test_v19_bootstrap_defaults_on_windows_and_rolls_back_to_v18(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "bootstrap_onyx_live_v19.pyw"
        ),
        run_name="onyx_v19_bootstrap_test",
    )
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    monkeypatch.setitem(namespace, "_default_workspace_root", lambda: tmp_path)
    mode, environment = namespace["_bootstrap_environment"]({})
    assert mode == "v19"
    assert environment[v19.LIVE_MASTER_FLAG] == "1"
    assert environment[v19.FEATURE_FLAG] == "true"

    mode, environment = namespace["_bootstrap_environment"](
        {"KEEP": "yes", v19.LIVE_ROLLBACK_FLAG: "1"}
    )
    assert (mode, environment) == ("v18", {"KEEP": "yes"})


def test_v19_is_stable_bootstrap_and_packaged_smoke_gate() -> None:
    root = Path(__file__).resolve().parents[1]
    stable = (root / "scripts" / "bootstrap_onyx.pyw").read_text(encoding="utf-8")
    launcher = (root / "scripts" / "launch_onyx_live_v19.pyw").read_text(
        encoding="utf-8"
    )
    build = (root / "scripts" / "build_release.py").read_text(encoding="utf-8")
    spec = (root / "packaging" / "onyx.spec").read_text(encoding="utf-8")
    assert 'bootstrap_onyx_live_v19.pyw"' in stable
    assert "OnyxDayOpsSmoke.v19" in launcher
    assert "package_dayops_smoke_test(validation_bundle)" in build
    for module in (
        "core.onyx_live_activation_v19",
        "core.dayops_profile_v19",
        "core.dayops_graph_factory_v19",
        "core.dayops_identity_provisioning_v19",
        "core.dayops_connection_v19",
    ):
        assert f'"{module}"' in spec
