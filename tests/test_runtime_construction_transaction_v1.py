from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import main as onyx_main
import ui as onyx_ui


class _FakeUI:
    def __init__(self) -> None:
        self.on_text_command = object()
        self.on_remote_clicked = object()
        self.on_interrupt = object()
        self.on_exit_requested = object()
        self.on_runtime_worker = object()
        self.on_file_attachment = object()
        self.on_dayops_status = object()
        self.on_dayops_connect = object()
        self.on_dayops_sign_in = object()
        self.on_dayops_disconnect = object()
        self.on_dayops_today_brief = object()


def _callbacks(ui: _FakeUI) -> dict[str, object]:
    return {
        name: getattr(ui, name)
        for name in onyx_main.OnyxLive._INITIALIZATION_UI_CALLBACKS
    }


def _minimal_components(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONYX_WORKSPACE_ROOTS", str(Path.cwd()))
    monkeypatch.setattr(onyx_main, "SystemMonitor", lambda: object())
    monkeypatch.setattr(onyx_main, "ProactiveEngine", lambda: object())
    monkeypatch.setattr(onyx_main, "MissionStore", lambda _path: object())
    monkeypatch.setattr(
        onyx_main,
        "MissionWorker",
        lambda _store, runner, **_kwargs: SimpleNamespace(runner=runner),
    )


def test_constructor_failure_closes_prior_owner_and_restores_all_ui_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class Phase11:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def runner(self, *_args, **_kwargs):
            return None

        def close(self, timeout: float) -> None:
            events.append(("phase11.close", timeout))

    class FailingGovernance:
        def initialize_host(self, _host: object) -> None:
            raise LookupError("governance construction failed")

    _minimal_components(monkeypatch)
    monkeypatch.setattr(onyx_main, "phase11_feature_enabled", lambda: True)
    monkeypatch.setattr(onyx_main, "Phase11LiveMissionV1", Phase11)
    monkeypatch.setattr(
        onyx_main.OnyxLive,
        "_governance_activation_v16",
        FailingGovernance(),
        raising=False,
    )
    ui = _FakeUI()
    original = _callbacks(ui)

    with pytest.raises(LookupError, match="governance construction failed"):
        onyx_main.OnyxLive(ui)

    assert events == [("phase11.close", 15.0)]
    assert _callbacks(ui) == original


def test_cleanup_root_handle_busy_analogue_preserves_primary_failure_and_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CloneCleanupWaiting(RuntimeError):
        pass

    class BusyPhase11:
        def __init__(self, *_args, **_kwargs) -> None:
            # The real Phase11LiveMissionV1 compensates its internal acquisition
            # before re-raising this exact construction boundary.
            raise CloneCleanupWaiting("cleanup_root_handle_busy")

    _minimal_components(monkeypatch)
    monkeypatch.setattr(onyx_main, "phase11_feature_enabled", lambda: True)
    monkeypatch.setattr(onyx_main, "Phase11LiveMissionV1", BusyPhase11)
    ui = _FakeUI()
    original = _callbacks(ui)

    with pytest.raises(CloneCleanupWaiting, match="^cleanup_root_handle_busy$"):
        onyx_main.OnyxLive(ui)

    assert _callbacks(ui) == original


def test_both_text_surfaces_use_runtime_dispatch_and_retain_exact_text() -> None:
    queued: list[tuple[str, object, object]] = []
    delivered: list[str] = []

    def dispatch(boundary: str, action: object, completion: object) -> bool:
        queued.append((boundary, action, completion))
        return True

    log = SimpleNamespace(append_log=lambda _value: None)
    cinematic = SimpleNamespace(
        on_text_command=delivered.append,
        on_runtime_worker=dispatch,
        _log=log,
        _v5_projection=None,
    )
    assert onyx_ui.MainWindow._submit_v5_command(cinematic, "cinematic exact")

    class Input:
        def text(self) -> str:
            return "  legacy exact  "

        def clear(self) -> None:
            pass

    legacy = SimpleNamespace(
        _input=Input(),
        _log=log,
        on_text_command=delivered.append,
        on_runtime_worker=dispatch,
    )
    onyx_ui.MainWindow._send(legacy)

    assert [item[0] for item in queued] == [
        "text-command-v5",
        "text-command-legacy",
    ]
    assert [item[2] for item in queued] == [None, None]
    for _boundary, action, _completion in queued:
        action()
    assert delivered == ["cinematic exact", "legacy exact"]


def test_runner_has_owner_error_surface_and_installer_construction_refusal() -> None:
    source = __import__("inspect").getsource(onyx_main.main)
    assert 'construction_status["state"] == "failed"' in source
    assert 'return "refused", construction_status["detail"]' in source
    assert "traceback.print_exception(exc, file=sys.stderr)" in source
    assert 'ui.set_state("ERROR")' in source
    assert 'ui.show_content(\n                        "STARTUP RECOVERY"' in source


def test_worker_snapshot_cannot_replace_primary_error_with_hostile_proxy() -> None:
    class HostileRecord:
        @property
        def worker(self):
            raise RuntimeError("hostile worker proxy")

    host = object.__new__(onyx_main.OnyxLive)
    host._blocking_action_workers = (HostileRecord(),)

    assert host._shutdown_worker_snapshot() == {
        "external_actions": [],
        "cleanup_worker": None,
        "audio_workers": [],
        "all_observed_workers_daemon": False,
    }
