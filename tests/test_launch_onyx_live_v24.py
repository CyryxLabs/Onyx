from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT / "scripts" / "launch_onyx_live_v24.pyw"


def _launcher_namespace() -> dict[str, object]:
    return runpy.run_path(
        str(LAUNCHER),
        run_name="onyx_v24_launcher_unit_contract",
    )


def _launcher_globals(namespace: dict[str, object]) -> dict[str, object]:
    run = namespace["run"]
    return run.__globals__


def test_native_smoke_persists_v24_entry_before_terminal_delegation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    namespace = _launcher_namespace()
    launcher_globals = _launcher_globals(namespace)
    log_path = tmp_path / "data" / "runtime" / "logs" / "onyx-live-v24-startup.log"
    calls = 0

    def terminal_delegate() -> None:
        nonlocal calls
        calls += 1
        assert log_path.is_file()
        assert "entering stable V24 launcher" in log_path.read_text(encoding="utf-8")

    monkeypatch.setitem(launcher_globals, "LOG_PATH", log_path)
    monkeypatch.setitem(launcher_globals, "ROOT", PROJECT)
    monkeypatch.setitem(
        launcher_globals,
        "_v23_contract",
        lambda: {"run": terminal_delegate},
    )
    monkeypatch.setattr(sys, "argv", [str(LAUNCHER), "--native-startup-smoke-test"])
    original_cwd = Path.cwd()
    try:
        namespace["run"]()
    finally:
        os.chdir(original_cwd)

    assert calls == 1
    evidence = log_path.read_text(encoding="utf-8")
    assert evidence.count("entering stable V24 launcher") == 1


def test_native_smoke_does_not_write_false_success_marker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    namespace = _launcher_namespace()
    launcher_globals = _launcher_globals(namespace)
    log_path = tmp_path / "onyx-live-v24-startup.log"

    def terminal_delegate() -> None:
        raise SystemExit(0)

    monkeypatch.setitem(launcher_globals, "LOG_PATH", log_path)
    monkeypatch.setitem(launcher_globals, "ROOT", PROJECT)
    monkeypatch.setitem(
        launcher_globals,
        "_v23_contract",
        lambda: {"run": terminal_delegate},
    )
    monkeypatch.setattr(sys, "argv", [str(LAUNCHER), "--native-startup-smoke-test"])
    original_cwd = Path.cwd()
    try:
        try:
            namespace["run"]()
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("terminal delegate did not exit")
    finally:
        os.chdir(original_cwd)

    evidence = log_path.read_text(encoding="utf-8")
    assert "entering stable V24 launcher" in evidence
    assert "native startup smoke passed" not in evidence.lower()
