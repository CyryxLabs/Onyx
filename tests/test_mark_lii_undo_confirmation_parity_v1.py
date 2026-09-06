from __future__ import annotations

from pathlib import Path

import pytest

from actions import computer_settings, file_controller
from core import permission_broker, undo_journal_v1
from memory import memory_manager
from memory.store import MemoryStore


@pytest.fixture(autouse=True)
def reset_process_state():
    undo_journal_v1.clear()
    permission_broker.set_permission_callback(None)
    permission_broker.configure_owner_autonomy(False, [])
    permission_broker.set_trust_profile("cautious")
    permission_broker._audit_healthy = True
    yield
    undo_journal_v1.clear()
    permission_broker.set_permission_callback(None)
    permission_broker.configure_owner_autonomy(False, [])
    permission_broker.set_trust_profile("cautious")
    permission_broker._audit_healthy = True


def _allow_test_root(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(file_controller, "_SAFE_ROOTS", [root])


def test_create_and_copy_undo_only_unchanged_onyx_artifacts(tmp_path, monkeypatch) -> None:
    _allow_test_root(monkeypatch, tmp_path)
    assert file_controller.create_file(str(tmp_path), "created.txt", "onyx").startswith(
        "File created"
    )
    assert "created file created.txt" in undo_journal_v1.peek()
    assert undo_journal_v1.undo_last().startswith("Undone:")
    assert not (tmp_path / "created.txt").exists()

    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    target_dir = tmp_path / "copies"
    target_dir.mkdir()
    assert file_controller.copy_file(str(source), destination=str(target_dir)).startswith(
        "Copied"
    )
    copied = target_dir / source.name
    copied.write_text("owner changed this", encoding="utf-8")
    result = undo_journal_v1.undo_last()
    assert result.startswith("Could not undo")
    assert copied.read_text(encoding="utf-8") == "owner changed this"


def test_move_rename_and_append_are_reversible(tmp_path, monkeypatch) -> None:
    _allow_test_root(monkeypatch, tmp_path)
    source = tmp_path / "note.txt"
    source.write_text("before", encoding="utf-8")
    destination = tmp_path / "archive"
    destination.mkdir()

    assert file_controller.move_file(str(source), destination=str(destination)).startswith(
        "Moved"
    )
    assert undo_journal_v1.undo_last().startswith("Undone:")
    assert source.read_text(encoding="utf-8") == "before"

    assert file_controller.rename_file(str(source), new_name="renamed.txt").startswith(
        "Renamed"
    )
    assert undo_journal_v1.undo_last().startswith("Undone:")
    assert source.exists()

    assert file_controller.write_file(str(source), content="+after", append=True).startswith(
        "Appended"
    )
    assert source.read_text(encoding="utf-8") == "before+after"
    assert undo_journal_v1.undo_last().startswith("Undone:")
    assert source.read_text(encoding="utf-8") == "before"


def test_setting_undo_restores_observed_value_without_guessing(monkeypatch) -> None:
    observed: list[int] = []
    current = {"value": 37}

    def set_volume(value):
        observed.append(value)
        current["value"] = value

    monkeypatch.setattr(computer_settings, "_require_pyautogui", lambda: object())
    monkeypatch.setattr(computer_settings, "volume_get", lambda: current["value"])
    monkeypatch.setattr(computer_settings, "volume_set", set_volume)

    assert computer_settings.computer_settings(
        {"action": "volume_set", "value": "68"}
    ) == "Volume set to 68%."
    assert observed == [68]
    assert undo_journal_v1.undo_last().startswith("Undone:")
    assert observed == [68, 37]


def test_setting_undo_refuses_owner_change_after_onyx_action(monkeypatch) -> None:
    current = {"value": 20}
    monkeypatch.setattr(computer_settings, "_require_pyautogui", lambda: object())
    monkeypatch.setattr(computer_settings, "volume_get", lambda: current["value"])
    monkeypatch.setattr(
        computer_settings, "volume_set", lambda value: current.__setitem__("value", value)
    )
    assert computer_settings.computer_settings(
        {"action": "volume_set", "value": "60"}
    ) == "Volume set to 60%."
    current["value"] = 75
    assert undo_journal_v1.undo_last().startswith("Could not undo")
    assert current["value"] == 75


@pytest.mark.parametrize("action", ["restart", "shutdown", "toggle_wifi"])
def test_model_confirmed_field_cannot_forge_owner_confirmation(action) -> None:
    allowed, reason = permission_broker.authorize_model_tool(
        "computer_settings", {"action": action, "confirmed": "yes"}
    )
    assert allowed is False
    assert "Permission denied" in reason


@pytest.mark.parametrize("action", ["restart", "shutdown", "toggle_wifi"])
def test_irreversible_action_requires_trusted_local_digest(action) -> None:
    requests = []

    def approve(request):
        requests.append(request)
        return request["digest"]

    permission_broker.set_permission_callback(approve)
    allowed, proof = permission_broker.authorize_model_tool(
        "computer_settings", {"action": action, "confirmed": "no"}
    )
    assert allowed is True
    assert proof == requests[0]["digest"]
    assert requests[0]["action"] == f"computer_settings.{action}"


def test_confirmation_digest_cannot_be_replayed() -> None:
    captured = {"digest": ""}

    def first(request):
        captured["digest"] = request["digest"]
        return request["digest"]

    permission_broker.set_permission_callback(first)
    assert permission_broker.authorize_model_tool(
        "computer_settings", {"action": "restart"}
    )[0]
    permission_broker.set_permission_callback(lambda _request: captured["digest"])
    allowed, reason = permission_broker.authorize_model_tool(
        "computer_settings", {"action": "restart"}
    )
    assert allowed is False
    assert "denied" in reason.casefold()


def test_undo_tool_is_prompt_free_but_has_no_model_selected_target() -> None:
    assert permission_broker.authorize_model_tool("undo", {"action": "undo"}) == (
        True,
        "",
    )


def test_description_is_materialized_before_permission_policy() -> None:
    request = computer_settings.materialize_computer_settings_request(
        {"description": "please set the volume to 42"}
    )
    assert request["action"] == "volume_set"
    assert request["value"] == 42
    assert computer_settings.materialize_computer_settings_request(
        {"description": "reiniciar computador"}
    )["action"] == "restart"
    assert computer_settings.materialize_computer_settings_request(
        {"description": "unrelated operation"}
    ).get("action", "") == ""


def test_prompt_memory_indexes_omitted_topics_without_values(tmp_path, monkeypatch) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3", enable_fts=False)
    store.initialize()
    for index in range(20):
        store.remember(
            f"private value {index}",
            source="user-approved",
            category="projects",
            key=f"project_{index}",
        )
    monkeypatch.setattr(memory_manager, "_store", store)
    prompt = memory_manager.format_memory_for_prompt(max_chars=4000)
    assert "ALSO REMEMBERED" in prompt
    assert "projects/project" in prompt
    assert len(prompt) <= 4000


def test_owner_memory_cli_lists_searches_and_forgets_exact_record(tmp_path, capsys) -> None:
    database = tmp_path / "owner-memory.sqlite3"
    base = ["--database", str(database)]
    assert memory_manager.cli([*base, "remember", "launch_plan", "alpha", "--category", "projects"]) == 0
    remembered = capsys.readouterr().out
    record_id = remembered.split("Remembered ", 1)[1].split(":", 1)[0]

    assert memory_manager.cli([*base, "search", "launch"]) == 0
    assert record_id in capsys.readouterr().out
    assert memory_manager.cli([*base, "list", "--kind", "semantic"]) == 0
    assert record_id in capsys.readouterr().out
    assert memory_manager.cli([*base, "forget", record_id]) == 0
    assert "Forgotten: 1" in capsys.readouterr().out
    assert memory_manager.cli([*base, "search", "launch"]) == 0
    assert record_id not in capsys.readouterr().out
