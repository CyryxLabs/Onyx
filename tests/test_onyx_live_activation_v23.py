from __future__ import annotations

import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v22 as v22
from core import onyx_live_activation_v23 as v23
from core.operational_event_controller_v1 import OperationalEventControllerV1
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1


def _activation(monkeypatch: pytest.MonkeyPatch):
    module = ModuleType("v23_test_host")

    class Host:
        def __init__(self, ui):
            self.ui = ui

    module.OnyxLive = Host
    base_contract = object.__new__(v22.HostContractV22)
    contract = v23.HostContractV23(module, Host, Path.cwd(), base_contract)
    base_flags = object.__new__(v22.ActivationFlagsV22)
    wiring = object.__new__(Phase6LiveWiringV1)
    wiring._lock = threading.RLock()
    wiring._installed = True
    wiring._installed_values = {"__init__": Host.__init__}
    wiring._protected = {}

    def fake_init(self, *_args, **_kwargs):
        self._installed = False
        self._wiring_controller = wiring

    def fake_install(self, *, fail_after=None):
        self._installed = fail_after is None

    def fake_instantiate(self, ui):
        return Host(ui)

    def fake_rollback(self):
        self._installed = False

    monkeypatch.setattr(v22.OnyxLiveActivationV22, "__init__", fake_init)
    monkeypatch.setattr(v22.OnyxLiveActivationV22, "install", fake_install)
    monkeypatch.setattr(v22.OnyxLiveActivationV22, "instantiate_live", fake_instantiate)
    monkeypatch.setattr(v22.OnyxLiveActivationV22, "rollback_all", fake_rollback)
    activation = v23.OnyxLiveActivationV23(
        v23.ActivationFlagsV23(True, True, base_flags),
        contract,
    )
    return module, Host, wiring, activation


def _ui():
    return SimpleNamespace(
        on_dayops_connect=lambda *_args, **_kwargs: {"status": "authentication_required"},
        on_dayops_sign_in=lambda *_args, **_kwargs: {"status": "connected"},
        on_dayops_disconnect=lambda *_args, **_kwargs: {"status": "disconnected"},
        on_dayops_today_brief=lambda: {
            "status": "completed",
            "brief_sha256": "a" * 64,
            "calendar_has_more": False,
            "mail_has_more": False,
            "events": [{"subject": "private"}],
            "unread_messages": [],
        },
    )


def test_v23_is_default_off_and_preserves_exact_v22_rollback() -> None:
    with pytest.raises(v23.ActivationV23Error, match="not canonical V23"):
        v23.ActivationFlagsV23.from_canonical_environ({})
    assert v23.exact_rollback_environment() == {v23.LIVE_ROLLBACK_FLAG: "1"}


def test_v23_wraps_dayops_callbacks_with_metadata_event_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, host, wiring, activation = _activation(monkeypatch)
    ui = _ui()
    originals = {name: getattr(ui, name) for name in v23._DAYOPS_CALLBACKS}
    observed = []

    def brief(self, payload):
        observed.append(("brief", payload))
        return {"status": "published", "published": 2, "content_captured": False}

    def connectivity(self, operation, payload):
        observed.append((operation, payload))
        return {"status": "published", "published": 1, "content_captured": False}

    monkeypatch.setattr(OperationalEventControllerV1, "publish_dayops_brief", brief)
    monkeypatch.setattr(
        OperationalEventControllerV1, "publish_connectivity_result", connectivity
    )
    original_init = host.__init__
    activation.install()
    instance = activation.instantiate_live(ui)
    try:
        brief_result = ui.on_dayops_today_brief()
        sign_in_result = ui.on_dayops_sign_in(lambda _line: None, lambda: False)
        assert brief_result["operational_event"]["published"] == 2
        assert sign_in_result["operational_event"]["published"] == 1
        assert observed[0][0] == "brief"
        assert observed[0][1]["events"][0]["subject"] == "private"
        assert type(getattr(instance, v23.OPERATIONAL_EVENT_CONTROLLER)) is (
            OperationalEventControllerV1
        )
    finally:
        activation.rollback_all()
    assert host.__init__ is original_init
    assert wiring._installed_values["__init__"] is original_init
    for name, callback in originals.items():
        assert getattr(ui, name) is callback
    assert not hasattr(host, v23.HOST_MARKER)
    assert not hasattr(module, "_onyx_live_activation_v23")


def test_v23_event_failure_does_not_fabricate_dayops_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, _wiring, activation = _activation(monkeypatch)
    ui = _ui()

    def denied(self, payload):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(OperationalEventControllerV1, "publish_dayops_brief", denied)
    activation.install()
    activation.instantiate_live(ui)
    try:
        result = ui.on_dayops_today_brief()
        assert result["status"] == "completed"
        assert result["operational_event"]["status"] == "not_published"
        assert result["operational_event"]["error"] == "RuntimeError"
        assert result["operational_event"]["content_captured"] is False
    finally:
        activation.rollback_all()


@pytest.mark.parametrize("offset", [1, 2])
def test_v23_failpoints_restore_v22_exactly(
    monkeypatch: pytest.MonkeyPatch, offset: int
) -> None:
    _module, host, wiring, activation = _activation(monkeypatch)
    original_init = host.__init__
    with pytest.raises(v23.ActivationV23Error, match="injected V23"):
        activation.install(fail_after=activation.BASE_SEAM_COUNT + offset)
    assert host.__init__ is original_init
    assert wiring._installed_values["__init__"] is original_init
    assert not hasattr(host, v23.HOST_MARKER)
