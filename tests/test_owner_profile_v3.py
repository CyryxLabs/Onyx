from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

import core.owner_profile_v3 as profile
from memory.store import MemoryStore, MemoryStoreError


FROZEN = {
    "core/owner_profile_v1.py": "b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754",
    "tests/test_owner_profile_v1.py": "fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035",
    "core/owner_profile_v2.py": "12c459c1d34376a121e7a837d6dbeca365967c69affdc12b7d3e18ea1c76cd73",
    "tests/test_owner_profile_v2.py": "76f0481f91b82b650ece00d86ad0bfffe21fa4020e46d8e3dcaaaf7e36832714",
}


def _write_config(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"owner_name": name, "os_system": "windows", "keep": True}),
        encoding="utf-8",
    )


def _owner(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["owner_name"]


def _owner_memory(store: MemoryStore) -> list[str]:
    return [
        record.content
        for record in store.list(kind="semantic", limit=None)
        if record.category == "preferences" and record.key == "owner_display_name"
    ]


def _markers(store: MemoryStore):
    return [
        record
        for record in store.list(kind="semantic", limit=None)
        if record.category == "preferences"
        and record.key == profile.RECOVERY_MEMORY_KEY
    ]


class FaultMemory:
    def __init__(self, delegate: MemoryStore):
        self.delegate = delegate
        self.fail_owner_names: set[str] = set()
        self.post_commit_owner_names: set[str] = set()
        self.fail_reads = False

    def list(self, **kwargs):
        if self.fail_reads:
            raise MemoryStoreError("wrapped read detail")
        return self.delegate.list(**kwargs)

    def remember(self, content, **kwargs):
        if kwargs.get("key") == "owner_display_name" and content in self.fail_owner_names:
            raise MemoryStoreError("wrapped memory detail")
        result = self.delegate.remember(content, **kwargs)
        if (
            kwargs.get("key") == "owner_display_name"
            and content in self.post_commit_owner_names
        ):
            raise MemoryStoreError("post-commit memory detail")
        return result

    def forget_key(self, category, key):
        return self.delegate.forget_key(category, key)


@pytest.fixture()
def stores():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = root / "config" / "api_keys.json"
        memory = MemoryStore(root / "memory" / "onyx_memory.sqlite3")
        memory.initialize()
        yield config, memory


def _authority(config: Path, memory) -> profile.OwnerProfileAuthority:
    return profile.OwnerProfileAuthority(config_path=config, memory=memory)


def _postcommit_config_failure(monkeypatch, desired: str, *, fail_rollback=False):
    real_save = profile.v1.save_settings
    state = {"primary": False, "rollback": False}

    def save(updates, path):
        value = updates.get("owner_name")
        if value == desired and not state["primary"]:
            state["primary"] = True
            real_save(updates, path)
            raise profile.v1.CredentialError("outer config wrapper") from RuntimeError(
                "root post-commit detail"
            )
        if fail_rollback and state["primary"] and not state["rollback"]:
            state["rollback"] = True
            raise profile.v1.CredentialError("rollback wrapper") from OSError(
                "root rollback config detail"
            )
        return real_save(updates, path)

    monkeypatch.setattr(profile.v1, "save_settings", save)
    return state


def test_v1_and_v2_are_byte_for_byte_frozen():
    root = Path(__file__).resolve().parents[1]
    for relative, expected in FROZEN.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected


def test_positive_first_contact_unicode_restart_correction_and_forget(stores):
    config, memory = stores
    _write_config(config, "Sir")
    authority = _authority(config, memory)
    assert authority.reconcile().state is profile.OwnerProfileState.UNKNOWN
    assert authority.begin_contact() == profile.FIRST_CONTACT_QUESTION
    assert authority.begin_contact() is None
    assert authority.set_name("Jose\N{COMBINING ACUTE ACCENT} 李小龍").display_name == "José 李小龍"
    restarted = _authority(config, memory)
    assert restarted.reconcile().display_name == "José 李小龍"
    assert restarted.correct_name("Renée").display_name == "Renée"
    assert restarted.forget_name().state is profile.OwnerProfileState.UNKNOWN
    assert _owner(config) == ""
    assert _owner_memory(memory) == []
    assert _markers(memory) == []


def test_postcommit_config_set_is_compensated_and_not_durable_after_restart(
    stores, monkeypatch
):
    config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()
    _postcommit_config_failure(monkeypatch, "Bob")

    with pytest.raises(profile.OwnerProfileTransactionError) as raised:
        authority.correct_name("Bob")

    assert raised.value.compensation_complete
    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert authority.last_failure.original_error_type == "RuntimeError"
    assert authority.last_failure.compensation_attempted
    assert authority.last_failure.compensation_complete
    assert _owner(config) == "Alice"
    assert _owner_memory(memory) == ["Alice"]
    assert _markers(memory) == []
    restarted = _authority(config, memory)
    assert restarted.reconcile().display_name == "Alice"


def test_postcommit_config_forget_is_compensated_and_not_durable_after_restart(
    stores, monkeypatch
):
    config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()
    _postcommit_config_failure(monkeypatch, "")

    with pytest.raises(profile.OwnerProfileTransactionError):
        authority.forget_name()

    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert _owner(config) == "Alice"
    assert _owner_memory(memory) == ["Alice"]
    restarted = _authority(config, memory)
    assert restarted.reconcile().display_name == "Alice"


def test_rollback_config_failure_is_structured_and_marker_recovers_on_restart(
    stores, monkeypatch
):
    config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()
    _postcommit_config_failure(monkeypatch, "Bob", fail_rollback=True)

    with pytest.raises(profile.OwnerProfileTransactionError) as raised:
        authority.correct_name("Bob")

    assert not raised.value.compensation_complete
    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert [(item.stage, item.error_type) for item in authority.last_failure.rollback] == [
        ("rollback-config", "OSError"),
        ("rollback-readback-config", "OwnerProfileError"),
    ]
    assert _owner(config) == "Bob"
    assert _owner_memory(memory) == ["Alice"]
    assert len(_markers(memory)) == 1

    restarted = _authority(config, memory)
    recovered = restarted.reconcile()
    assert recovered.state is profile.OwnerProfileState.KNOWN
    assert recovered.display_name == "Alice"
    assert _owner(config) == "Alice"
    assert _markers(memory) == []


def test_rollback_memory_failure_is_structured_and_marker_recovers_on_restart(
    stores, monkeypatch
):
    config, store = stores
    _write_config(config, "Alice")
    memory = FaultMemory(store)
    authority = _authority(config, memory)
    authority.reconcile()
    del monkeypatch
    memory.post_commit_owner_names.add("Bob")
    memory.fail_owner_names.add("Alice")

    with pytest.raises(profile.OwnerProfileTransactionError) as raised:
        authority.correct_name("Bob")

    assert not raised.value.compensation_complete
    entries = [(item.stage, item.error_type) for item in authority.last_failure.rollback]
    assert entries == [
        ("rollback-memory", "MemoryStoreError"),
        ("rollback-readback-memory", "OwnerProfileError"),
    ]
    assert _owner(config) == "Alice"
    assert _owner_memory(store) == ["Bob"]
    assert len(_markers(store)) == 1

    memory.fail_owner_names.clear()
    restarted = _authority(config, memory)
    assert restarted.reconcile().display_name == "Alice"
    assert _owner_memory(store) == ["Alice"]
    assert _markers(store) == []


def test_readback_ambiguity_is_structured_and_keeps_recovery_marker(
    stores, monkeypatch
):
    config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()
    state = _postcommit_config_failure(monkeypatch, "Bob")
    real_read = authority._read_config
    failed = {"readback": False}

    def ambiguous_read():
        if state["primary"] and not failed["readback"] and _owner(config) == "Alice":
            failed["readback"] = True
            raise profile.OwnerProfileError("readback wrapper") from TimeoutError(
                "root readback detail"
            )
        return real_read()

    monkeypatch.setattr(authority, "_read_config", ambiguous_read)
    with pytest.raises(profile.OwnerProfileTransactionError) as raised:
        authority.correct_name("Bob")

    assert not raised.value.compensation_complete
    assert ("rollback-readback-config", "TimeoutError") in [
        (item.stage, item.error_type) for item in authority.last_failure.rollback
    ]
    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert len(_markers(memory)) == 1

    restarted = _authority(config, memory)
    assert restarted.reconcile().display_name == "Alice"
    assert _markers(memory) == []


def test_diagnostics_are_root_normalized_structured_and_message_free(stores, monkeypatch):
    config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()
    _postcommit_config_failure(monkeypatch, "Bob", fail_rollback=True)

    with pytest.raises(profile.OwnerProfileTransactionError):
        authority.correct_name("Bob")

    diagnostic = authority.last_failure
    assert diagnostic.original_error_type == "RuntimeError"
    assert diagnostic.stage == "write-config"
    assert all(item.stage.startswith("rollback-") for item in diagnostic.rollback)
    rendered = repr(diagnostic)
    assert "detail" not in rendered
    assert "Alice" not in rendered
    assert "Bob" not in rendered


def test_no_exception_path_publishes_healthy_divergence(stores, monkeypatch):
    config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()
    _postcommit_config_failure(monkeypatch, "Bob", fail_rollback=True)

    with pytest.raises(profile.OwnerProfileTransactionError):
        authority.set_name("Bob")

    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert not authority.snapshot.reconciled
    assert authority.degraded_latched


def test_v3_is_default_off_with_no_live_import():
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py", "core/permission_broker.py"):
        assert "owner_profile_v3" not in (root / relative).read_text(encoding="utf-8")
