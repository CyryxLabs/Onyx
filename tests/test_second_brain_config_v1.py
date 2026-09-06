import json

import pytest

from memory import second_brain_config_v1 as setup
from memory.obsidian_v1 import ObsidianVault, configured_context


def test_persistent_retrieval_and_pause(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / "note.md").write_text("Orchid project delivers Tuesday", encoding="utf-8")
    database = tmp_path / "index.sqlite3"
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(setup, "settings_path", lambda: settings)
    monkeypatch.delenv("ONYX_OBSIDIAN_VAULT", raising=False)
    monkeypatch.delenv("ONYX_OBSIDIAN_CONTEXT", raising=False)
    ObsidianVault(vault, database).refresh()
    setup.configure(vault, database, context_enabled=False)
    assert configured_context("Orchid") == ""
    setup.configure(vault, database, context_enabled=True)
    assert "Tuesday" in configured_context("Orchid")
    monkeypatch.setenv("ONYX_OBSIDIAN_CONTEXT", "0")
    assert configured_context("Orchid") == ""


def test_bad_settings_fail_closed(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(setup, "settings_path", lambda: settings)
    monkeypatch.delenv("ONYX_OBSIDIAN_VAULT", raising=False)
    settings.write_text('{"context_enabled": "true"}', encoding="utf-8")
    assert configured_context("anything") == ""
    with pytest.raises(ValueError):
        setup.load()


def test_cli_status_without_configuration(tmp_path, capsys):
    assert setup.cli(["--settings", str(tmp_path / "missing.json"), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_configured"
