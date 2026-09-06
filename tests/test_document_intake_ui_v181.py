from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main
import ui


class _ImmediateThread:
    def __init__(self, *, target, args, daemon):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self) -> None:
        self.target(*self.args)


def _synchronous_runtime_dispatch(expected_boundary: str, calls: list[str]):
    def dispatch(boundary, worker, complete):
        assert boundary == expected_boundary
        assert complete is None
        calls.append(boundary)
        worker()
        return True

    return dispatch


def test_ui_selection_prefers_v18_host_thread_and_never_calls_legacy_model() -> None:
    path = r"C:\Users\owner\secret\plan.md"
    host_values: list[str] = []
    model_values: list[str] = []
    dispatches: list[str] = []
    with patch.object(ui.threading, "Thread", _ImmediateThread):
        mode = ui._dispatch_selected_file(
            host_callback=host_values.append,
            legacy_model_callback=model_values.append,
            path=path,
            filename="plan.md",
            suffix="md",
            size="10 B",
            runtime_dispatch=_synchronous_runtime_dispatch(
                "file-intake", dispatches
            ),
        )
    assert mode == "v18-host"
    assert dispatches == ["file-intake"]
    assert host_values == [path]
    assert model_values == []


def test_ui_selection_preserves_legacy_prompt_only_without_v18_callback() -> None:
    path = r"C:\Users\owner\legacy\plan.md"
    model_values: list[str] = []
    dispatches: list[str] = []
    with patch.object(ui.threading, "Thread", _ImmediateThread):
        mode = ui._dispatch_selected_file(
            host_callback=None,
            legacy_model_callback=model_values.append,
            path=path,
            filename="plan.md",
            suffix="md",
            size="10 B",
            runtime_dispatch=_synchronous_runtime_dispatch(
                "legacy-file-message", dispatches
            ),
        )
    assert mode == "legacy-model"
    assert dispatches == ["legacy-file-message"]
    assert len(model_values) == 1
    assert path in model_values[0]


def test_v18_host_callback_sends_only_public_metadata_to_model_and_log() -> None:
    raw_path = r"C:\Users\owner\secret\board-plan.md"
    public = {
        "alias": "attachment-abc",
        "source": "attachment-source-abc",
        "logical_document_id": "attachment-abc",
        "revision_id": "sha256-" + "a" * 64,
        "filename": "board-plan.md",
        "media_type": "text/markdown",
    }

    class Controller:
        def provision_trusted_attachment(self, value: str):
            assert value == raw_path
            return dict(public)

    logs: list[str] = []
    prompts: list[str] = []
    host = object.__new__(main.OnyxLive)
    host._document_intake_controller_v18 = Controller()
    host.ui = SimpleNamespace(write_log=logs.append)
    host._on_text_command = prompts.append

    host._on_file_attachment_v18(raw_path)

    assert len(prompts) == 1
    assert len(logs) == 1
    assert raw_path not in prompts[0]
    assert raw_path not in logs[0]
    assert "artifact_id" not in prompts[0]
    assert "workspace_id" not in prompts[0]
    for key, value in public.items():
        assert key in prompts[0]
        assert value in prompts[0]


def test_v18_disables_only_implicit_legacy_file_path(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "explicit.txt"
    selected.write_text("content", encoding="utf-8")
    v18_host = SimpleNamespace(
        _document_intake_controller_v18=object(),
        ui=SimpleNamespace(current_file=str(tmp_path / "implicit.txt")),
    )
    with pytest.raises(PermissionError, match="implicit attachment"):
        main._materialize_legacy_file_processor_for_host(
            v18_host, {"action": "read"}
        )

    explicit = main._materialize_legacy_file_processor_for_host(
        v18_host,
        {"action": "read", "file_path": str(selected)},
    )
    assert explicit["file_path"] == str(selected.resolve())


def test_legacy_host_still_materializes_current_file(tmp_path: Path) -> None:
    selected = tmp_path / "legacy.txt"
    selected.write_text("legacy", encoding="utf-8")
    legacy_host = SimpleNamespace(
        _document_intake_controller_v18=None,
        ui=SimpleNamespace(current_file=str(selected)),
    )
    materialized = main._materialize_legacy_file_processor_for_host(
        legacy_host, {"action": "read"}
    )
    assert materialized["file_path"] == str(selected.resolve())
