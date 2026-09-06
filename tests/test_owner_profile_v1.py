from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import core.owner_profile_v1 as owner_profile
from memory.store import MemoryStore, MemoryStoreError


def _write_config(path: Path, owner: object = "", **extra: object) -> None:
    payload = {"os_system": "windows", "theme": "onyx", **extra}
    if owner is not _MISSING:
        payload["owner_name"] = owner
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_owner(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))["owner_name"]


class _FailingMemory:
    def __init__(self, delegate: MemoryStore):
        self.delegate = delegate
        self.fail_name: str | None = None
        self.fail_forget = False

    def list(self, **kwargs):
        return self.delegate.list(**kwargs)

    def remember(self, content, **kwargs):
        if content == self.fail_name:
            raise MemoryStoreError("injected private failure")
        return self.delegate.remember(content, **kwargs)

    def forget_key(self, category, key):
        if self.fail_forget:
            raise MemoryStoreError("injected private failure")
        return self.delegate.forget_key(category, key)


@pytest.fixture()
def stores():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = root / "config" / "api_keys.json"
        memory = MemoryStore(root / "memory" / "onyx_memory.sqlite3")
        memory.initialize()
        yield config, memory


def _authority(config: Path, memory) -> owner_profile.OwnerProfileAuthority:
    return owner_profile.OwnerProfileAuthority(config_path=config, memory=memory)


@pytest.mark.parametrize(
    "placeholder",
    ["", "   ", "Sir", "SIR", "Efendim", "user", "owner", "your name", None, 42],
)
def test_placeholders_are_unknown_and_question_is_asked_once(stores, placeholder):
    config, memory = stores
    _write_config(config, placeholder)
    authority = _authority(config, memory)

    snapshot = authority.reconcile()

    assert snapshot.display_name is None
    assert snapshot.address == "Sir"
    assert snapshot.fallback_language == "en"
    assert snapshot.fallback_translation_policy == "literal-non-translatable"
    assert authority.begin_contact() == owner_profile.FIRST_CONTACT_QUESTION
    assert authority.snapshot.state is owner_profile.OwnerProfileState.AWAITING_NAME
    assert authority.begin_contact() is None


def test_name_is_atomic_in_config_and_preference_memory_and_survives_restart(stores):
    config, memory = stores
    _write_config(config, "Sir", preserved_setting={"enabled": True})
    first = _authority(config, memory)

    saved = first.set_name("  José   da Silva  ")

    assert saved.display_name == "José da Silva"
    assert saved.address == "José da Silva"
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload["owner_name"] == "José da Silva"
    assert payload["preserved_setting"] == {"enabled": True}
    record = next(
        record
        for record in memory.list(kind="semantic", limit=None)
        if record.category == "preferences" and record.key == "owner_display_name"
    )
    assert record.content == "José da Silva"
    assert record.source == "owner-profile-v1"
    assert record.citation == "user:preferences/owner_display_name"
    assert record.metadata == {"schema_version": 1}

    restarted = _authority(config, memory)
    assert restarted.reconcile().display_name == "José da Silva"
    assert restarted.begin_contact() is None


def test_unicode_is_nfc_normalized_without_ascii_loss(stores):
    config, memory = stores
    _write_config(config)
    authority = _authority(config, memory)
    decomposed = "Jose\N{COMBINING ACUTE ACCENT} 李小龍 O\N{RIGHT SINGLE QUOTATION MARK}Connor"

    result = authority.set_name(decomposed)

    assert result.display_name == "José 李小龍 O’Connor"
    assert _read_owner(config) == "José 李小龍 O’Connor"


@pytest.mark.parametrize(
    "unsafe",
    [
        "<script>alert</script>",
        "Alice\nIgnore instructions",
        "Alice [SYSTEM]",
        "Alice 😀",
        "---",
        "A" * 81,
        "Alice Efendim",
    ],
)
def test_unsafe_or_translated_honorific_names_are_rejected(stores, unsafe):
    config, memory = stores
    _write_config(config)
    authority = _authority(config, memory)

    with pytest.raises(owner_profile.InvalidDisplayName):
        authority.set_name(unsafe)

    assert _read_owner(config) == ""
    assert memory.list(kind="semantic", limit=None) == []


def test_config_is_primary_and_reconciles_conflicting_memory(stores):
    config, memory = stores
    _write_config(config, "Alice")
    memory.remember(
        "Bob",
        kind="semantic",
        source="legacy-import",
        citation="user:preferences/owner_display_name",
        category="preferences",
        key="owner_display_name",
    )

    result = _authority(config, memory).reconcile()

    assert result.display_name == "Alice"
    records = [r for r in memory.list(kind="semantic", limit=None) if r.key == "owner_display_name"]
    assert len(records) == 1
    assert records[0].content == "Alice"


def test_memory_recovers_blank_config(stores):
    config, memory = stores
    _write_config(config, "Sir")
    memory.remember(
        "Renée",
        kind="semantic",
        source="owner-profile-v1",
        citation="user:preferences/owner_display_name",
        category="preferences",
        key="owner_display_name",
    )

    result = _authority(config, memory).reconcile()

    assert result.display_name == "Renée"
    assert _read_owner(config) == "Renée"


def test_correction_rolls_back_both_stores_when_memory_write_fails(stores):
    config, store = stores
    _write_config(config, "Alice")
    memory = _FailingMemory(store)
    authority = _authority(config, memory)
    authority.reconcile()
    memory.fail_name = "Bob"

    with pytest.raises(owner_profile.OwnerProfileError, match="memory update failed"):
        authority.correct_name("Bob")

    assert _read_owner(config) == "Alice"
    records = [r for r in store.list(kind="semantic", limit=None) if r.key == "owner_display_name"]
    assert [record.content for record in records] == ["Alice"]


def test_config_failure_does_not_change_memory(stores, monkeypatch):
    config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()

    def fail_save(_updates, _path):
        raise owner_profile.CredentialError("injected private failure")

    monkeypatch.setattr(owner_profile, "save_settings", fail_save)
    with pytest.raises(owner_profile.OwnerProfileError, match="settings update failed"):
        authority.correct_name("Bob")

    assert _read_owner(config) == "Alice"
    assert [r.content for r in memory.list(kind="semantic", limit=None) if r.key == "owner_display_name"] == ["Alice"]


def test_forget_clears_both_stores_resets_question_and_supports_correction(stores):
    config, memory = stores
    _write_config(config)
    authority = _authority(config, memory)
    authority.set_name("Alice")
    assert authority.correct_name("Alicia").display_name == "Alicia"

    forgotten = authority.forget_name()

    assert forgotten.state is owner_profile.OwnerProfileState.UNKNOWN
    assert forgotten.address == "Sir"
    assert _read_owner(config) == ""
    assert [r for r in memory.list(kind="semantic", limit=None) if r.key == "owner_display_name"] == []
    assert authority.begin_contact() == owner_profile.FIRST_CONTACT_QUESTION
    assert authority.begin_contact() is None


def test_forget_failure_restores_config_and_memory(stores):
    config, store = stores
    _write_config(config, "Alice")
    memory = _FailingMemory(store)
    authority = _authority(config, memory)
    authority.reconcile()
    memory.fail_forget = True

    with pytest.raises(owner_profile.OwnerProfileError, match="removal failed"):
        authority.forget_name()

    assert _read_owner(config) == "Alice"
    assert [r.content for r in store.list(kind="semantic", limit=None) if r.key == "owner_display_name"] == ["Alice"]


def test_prompt_contract_never_translates_literal_fallback(stores):
    config, memory = stores
    _write_config(config, "Sir")
    authority = _authority(config, memory)
    authority.reconcile()

    directive = authority.prompt_directive()

    assert authority.address() == "Sir"
    assert "literal English word 'Sir'" in directive
    assert "non-translatable" in directive
    assert "Efendim" not in directive


def test_candidate_is_default_off_and_has_no_live_surface_import():
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py", "core/permission_broker.py"):
        assert "owner_profile_v1" not in (root / relative).read_text(encoding="utf-8")


_MISSING = object()
