from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from core import owner_profile_v8 as owner_v8
from core.onyx_live_activation_v15 import (
    OnyxLiveActivationV15,
    exact_activation_environment,
)
from memory.store import MemoryStore


class _Lease:
    cross_session_guaranteed = True

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._local = threading.local()

    @contextmanager
    def hold(self, _owner_profile_id: str, *, timeout_seconds: float):
        if not self._lock.acquire(timeout=timeout_seconds):
            raise owner_v8.HostLeaseConflict("timeout")
        self._local.depth = getattr(self._local, "depth", 0) + 1
        try:
            yield self
        finally:
            self._local.depth -= 1
            self._lock.release()

    def held(self) -> bool:
        return getattr(self._local, "depth", 0) > 0


class _HeadStore:
    def __init__(self) -> None:
        self.value = None
        self._lock = threading.Lock()

    def load(self, _owner_profile_id: str):
        with self._lock:
            return self.value

    def compare_and_set(self, _owner_profile_id: str, expected, desired) -> bool:
        with self._lock:
            if self.value != expected:
                return False
            self.value = desired
            return True


def _authority(root: Path):
    memory = MemoryStore(root / "memory.sqlite3")
    memory.initialize()
    lease = _Lease()
    head = _HeadStore()
    return owner_v8.OwnerProfileAuthority.bootstrap(
        config_path=root / "owner-config.json",
        memory=memory,
        journal_path=root / owner_v8.JOURNAL_FILENAME,
        journal_key=b"K" * 32,
        owner_profile_id="v15-onboarding-test-owner",
        runtime_instance="v15-onboarding-test-runtime",
        chain_head_store=head,
        transaction_lease=lease,
    )


def _owner_controller(controller: object):
    observed: set[int] = set()
    while controller is not None and id(controller) not in observed:
        observed.add(id(controller))
        if type(controller).__name__ == "OnyxLiveActivationV4":
            return controller
        controller = getattr(controller, "_base", None)
    raise AssertionError("V4 owner controller was not installed")


def test_unknown_owner_can_explicitly_choose_sir_and_stays_writable(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path.resolve()
    environment = exact_activation_environment((root,))
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QSG_RHI_BACKEND", "software")

    import main
    import ui
    from core import credentials
    from core.onyx_live_activation_v15 import activate_main

    api_file = root / "api-keys.json"
    api_file.write_text(
        json.dumps({"os_system": "windows", "owner_name": "Sir"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui, "API_FILE", api_file)
    monkeypatch.setattr(
        credentials,
        "status",
        lambda: {
            "configured": True,
            "source": "test",
            "backend": "test",
        },
    )
    monkeypatch.setattr(credentials, "get", lambda *, required=False: "configured")

    app = ui.QApplication.instance() or ui.QApplication([])
    authority = _authority(root)
    original_init = ui.MainWindow.__init__
    original_check = ui.MainWindow._check_config
    original_setup = ui.MainWindow._on_setup_done
    controller: OnyxLiveActivationV15 | None = None
    window = None
    owner = None
    try:
        controller = activate_main(main, authority_factory=lambda: authority)
        window = ui.MainWindow("")
        app.processEvents()
        owner = _owner_controller(controller)

        assert window._overlay is not None
        assert window._overlay._name_input.text() == ""
        owner.set_name("Sir")
        app.processEvents()
        assert owner.owner_name() == "Sir"
        assert authority.snapshot.display_name is None
        owner_config = json.loads((root / "owner-config.json").read_text("utf-8"))
        assert owner_config["owner_name"] == ""
        assert owner_config["owner_address_preference"] == "Sir"
        assert owner.state.value == "ready"

        window._create_desktop_shortcut = lambda: None
        window._on_setup_done("", "Windows", "Sir")
        app.processEvents()
        assert owner.state.value == "ready"
        assert window._ready and window._overlay is None

        owner.correct_name("Alice")
        app.processEvents()
        assert owner.state.value == "ready"
        assert authority.snapshot.display_name == "Alice"
        assert owner.owner_name() == "Alice"
        owner_config = json.loads((root / "owner-config.json").read_text("utf-8"))
        assert owner_config["owner_name"] == "Alice"
        assert owner_config["owner_address_preference"] == ""
    finally:
        if window is not None:
            window.setAttribute(ui.Qt.WidgetAttribute.WA_DeleteOnClose, True)
            window.close()
            window.deleteLater()
            for _ in range(5):
                app.processEvents()
        if controller is not None:
            controller.rollback_all()
    assert ui.MainWindow.__init__ is original_init
    assert ui.MainWindow._check_config is original_check
    assert ui.MainWindow._on_setup_done is original_setup
    assert owner is not None
    assert "set_name" not in vars(owner)
    assert "correct_name" not in vars(owner)


def test_provider_owner_tool_bypasses_generic_broker_and_updates_record_and_hud(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path.resolve()
    for name, value in exact_activation_environment((root,)).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QSG_RHI_BACKEND", "software")

    import main
    import ui
    from core import credentials
    from core.onyx_live_activation_v15 import activate_main

    api_file = root / "api-keys.json"
    api_file.write_text(
        json.dumps({"os_system": "windows", "owner_name": "Pau"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui, "API_FILE", api_file)
    monkeypatch.setattr(
        credentials,
        "status",
        lambda: {"configured": True, "source": "test", "backend": "test"},
    )
    monkeypatch.setattr(credentials, "get", lambda *, required=False: "configured")
    monkeypatch.setattr(ui.MainWindow, "_create_desktop_shortcut", lambda _self: None)

    authority = _authority(root)
    authority.set_name("Pau")
    app = ui.QApplication.instance() or ui.QApplication([])
    original_execute = main.OnyxLive._execute_tool
    controller: OnyxLiveActivationV15 | None = None
    window = None
    try:
        controller = activate_main(main, authority_factory=lambda: authority)
        owner = _owner_controller(controller)
        window = ui.MainWindow("")
        window.show()
        app.processEvents()
        assert window._v5_projection.ownerName == "Pau"

        def generic_broker_must_not_run(*_args, **_kwargs):
            raise AssertionError("generic permission broker was reached")

        monkeypatch.setattr(main, "authorize_model_tool", generic_broker_must_not_run)
        live = object.__new__(main.OnyxLive)
        response = asyncio.run(
            main.OnyxLive._execute_tool(
                live,
                SimpleNamespace(
                    id="owner-tool-sir",
                    name="correct_owner_name",
                    args={"name": "Sir"},
                ),
            )
        )
        app.processEvents()

        assert response.response["result"] == "owner profile updated"
        assert response.response["address"] == "Sir"
        assert authority.snapshot.display_name is None
        owner_config = json.loads((root / "owner-config.json").read_text("utf-8"))
        assert owner_config["owner_name"] == ""
        assert owner_config["owner_address_preference"] == "Sir"
        assert owner.owner_name() == "Sir"
        assert window._v5_projection.ownerName == "Sir"

        response = asyncio.run(
            main.OnyxLive._execute_tool(
                live,
                SimpleNamespace(
                    id="owner-tool-alice",
                    name="correct_owner_name",
                    args={"name": "Alice"},
                ),
            )
        )
        app.processEvents()
        assert response.response["address"] == "Alice"
        assert authority.snapshot.display_name == "Alice"
        assert window._v5_projection.ownerName == "Alice"
    finally:
        if window is not None:
            window.setAttribute(ui.Qt.WidgetAttribute.WA_DeleteOnClose, True)
            window.close()
            window.deleteLater()
            for _ in range(5):
                app.processEvents()
        if controller is not None:
            controller.rollback_all()
    assert main.OnyxLive._execute_tool is original_execute
