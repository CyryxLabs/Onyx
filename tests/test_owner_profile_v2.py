from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

import core.owner_profile_v2 as profile
from memory.store import MemoryStore, MemoryStoreError


V1_CORE_SHA256 = "b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754"
V1_TEST_SHA256 = "fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035"


def _write_config(path: Path, name: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"owner_name": name, "os_system": "windows", "keep": True}),
        encoding="utf-8",
    )


def _owner(path: Path) -> str:
    return str(json.loads(path.read_text(encoding="utf-8"))["owner_name"])


class FaultMemory:
    def __init__(self, delegate: MemoryStore):
        self.delegate = delegate
        self.fail_reads = False
        self.post_commit_names: set[str] = set()
        self.fail_names: set[str] = set()
        self.fail_forget = False

    def list(self, **kwargs):
        if self.fail_reads:
            raise MemoryStoreError("read contains secret diagnostic")
        return self.delegate.list(**kwargs)

    def remember(self, content, **kwargs):
        if content in self.fail_names:
            raise MemoryStoreError("rollback contains secret diagnostic")
        result = self.delegate.remember(content, **kwargs)
        if content in self.post_commit_names:
            raise MemoryStoreError("post-commit contains secret diagnostic")
        return result

    def forget_key(self, category, key):
        if self.fail_forget:
            raise MemoryStoreError("forget contains secret diagnostic")
        return self.delegate.forget_key(category, key)


@pytest.fixture()
def stores():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = root / "config" / "api_keys.json"
        memory = MemoryStore(root / "memory" / "onyx_memory.sqlite3")
        memory.initialize()
        yield root, config, memory


def _authority(config: Path, memory) -> profile.OwnerProfileAuthority:
    return profile.OwnerProfileAuthority(config_path=config, memory=memory)


def test_v1_candidate_is_byte_for_byte_frozen():
    root = Path(__file__).resolve().parents[1]
    assert hashlib.sha256((root / "core/owner_profile_v1.py").read_bytes()).hexdigest() == V1_CORE_SHA256
    assert hashlib.sha256((root / "tests/test_owner_profile_v1.py").read_bytes()).hexdigest() == V1_TEST_SHA256


def test_publish_false_is_always_degraded_even_with_known_name(stores):
    _root, config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)

    snapshot = authority._publish("Alice", reconciled=False)

    assert snapshot.state is profile.OwnerProfileState.DEGRADED
    assert snapshot.display_name == "Alice"
    assert snapshot.reconciled is False


def test_positive_first_contact_unicode_restart_correction_and_forget(stores):
    _root, config, memory = stores
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
    assert [r for r in memory.list(kind="semantic", limit=None) if r.key == "owner_display_name"] == []


def test_post_commit_memory_error_latches_before_successful_rollback(stores):
    _root, config, store = stores
    _write_config(config, "Alice")
    memory = FaultMemory(store)
    authority = _authority(config, memory)
    assert authority.reconcile().state is profile.OwnerProfileState.KNOWN
    memory.post_commit_names.add("Bob")

    with pytest.raises(profile.OwnerProfileError, match="memory update failed"):
        authority.correct_name("Bob")

    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert authority.snapshot.reconciled is False
    assert authority.degraded_latched
    assert authority.last_failure is not None
    assert authority.last_failure.stage == "write-memory"
    assert authority.last_failure.original_error_type == "MemoryStoreError"
    assert authority.last_failure.rollback_error_types == ()
    assert _owner(config) == "Alice"
    assert [r.content for r in store.list(kind="semantic", limit=None) if r.key == "owner_display_name"] == ["Alice"]

    # Even a later successful write cannot self-certify health.
    memory.post_commit_names.clear()
    assert authority.correct_name("Carol").state is profile.OwnerProfileState.DEGRADED
    assert authority.reconcile().state is profile.OwnerProfileState.KNOWN
    assert authority.snapshot.display_name == "Carol"
    assert not authority.degraded_latched
    assert authority.last_failure is None


def test_post_commit_error_and_both_rollback_failures_remain_diagnosable(
    stores, monkeypatch
):
    _root, config, store = stores
    _write_config(config, "Alice")
    memory = FaultMemory(store)
    authority = _authority(config, memory)
    authority.reconcile()
    memory.post_commit_names.add("Bob")
    memory.fail_names.add("Alice")

    real_save = profile.v1.save_settings

    def fail_rollback(updates, path):
        if updates.get("owner_name") == "Alice":
            raise profile.v1.CredentialError("rollback config secret diagnostic")
        return real_save(updates, path)

    monkeypatch.setattr(profile.v1, "save_settings", fail_rollback)
    with pytest.raises(profile.OwnerProfileTransactionError) as raised:
        authority.correct_name("Bob")

    error = raised.value
    assert isinstance(error.original_error, MemoryStoreError)
    assert len(error.rollback_errors) == 2
    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert authority.snapshot.reconciled is False
    assert authority.degraded_latched
    assert authority.last_failure is not None
    assert authority.last_failure.original_error_type == "MemoryStoreError"
    assert authority.last_failure.rollback_error_types == (
        "CredentialError",
        "MemoryStoreError",
    )
    assert "secret diagnostic" not in repr(authority.last_failure)
    # Both stores contain Bob after the injected compensation failures.
    assert _owner(config) == "Bob"
    assert [r.content for r in store.list(kind="semantic", limit=None) if r.key == "owner_display_name"] == ["Bob"]


def test_memory_read_failure_degrades_and_only_verified_reconcile_heals(stores):
    _root, config, store = stores
    _write_config(config, "Alice")
    memory = FaultMemory(store)
    authority = _authority(config, memory)
    assert authority.reconcile().state is profile.OwnerProfileState.KNOWN
    memory.fail_reads = True

    degraded = authority.reconcile()

    assert degraded.state is profile.OwnerProfileState.DEGRADED
    assert degraded.display_name == "Alice"
    assert authority.last_failure is not None
    assert authority.last_failure.stage == "read-memory"
    assert authority.begin_contact() is None

    memory.fail_reads = False
    healed = authority.reconcile()
    assert healed.state is profile.OwnerProfileState.KNOWN
    assert healed.reconciled
    assert authority.last_failure is None


def test_config_read_failure_degrades_without_discarding_last_known_address(
    stores, monkeypatch
):
    _root, config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()

    def fail_read():
        raise profile.OwnerProfileError("config secret diagnostic")

    monkeypatch.setattr(authority, "_read_config", fail_read)
    snapshot = authority.reconcile()

    assert snapshot.state is profile.OwnerProfileState.DEGRADED
    assert snapshot.display_name == "Alice"
    assert snapshot.reconciled is False
    assert authority.last_failure is not None
    assert authority.last_failure.stage == "read-config"
    assert "secret diagnostic" not in repr(authority.last_failure)


def test_config_write_failure_cannot_leave_healthy_snapshot(stores, monkeypatch):
    _root, config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()

    def fail_save(_updates, _path):
        raise profile.v1.CredentialError("config secret diagnostic")

    monkeypatch.setattr(profile.v1, "save_settings", fail_save)
    with pytest.raises(profile.OwnerProfileError):
        authority.correct_name("Bob")

    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert authority.snapshot.reconciled is False
    assert authority.last_failure is not None
    assert authority.last_failure.stage == "write-config"
    assert _owner(config) == "Alice"


def test_prior_read_exception_latches_degraded_before_escape(stores, monkeypatch):
    _root, config, memory = stores
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    authority.reconcile()

    def fail_read():
        raise profile.OwnerProfileError("prior read failure")

    monkeypatch.setattr(authority, "_read_config", fail_read)
    with pytest.raises(profile.OwnerProfileError, match="prior read failure"):
        authority.correct_name("Bob")

    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert authority.last_failure is not None
    assert authority.last_failure.operation == "set"
    assert authority.last_failure.stage == "read-prior-config"


def test_forget_failure_is_degraded_even_when_rollback_succeeds(stores):
    _root, config, store = stores
    _write_config(config, "Alice")
    memory = FaultMemory(store)
    authority = _authority(config, memory)
    authority.reconcile()
    memory.fail_forget = True

    with pytest.raises(profile.OwnerProfileError, match="memory removal failed"):
        authority.forget_name()

    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert authority.snapshot.display_name == "Alice"
    assert _owner(config) == "Alice"
    assert [r.content for r in store.list(kind="semantic", limit=None) if r.key == "owner_display_name"] == ["Alice"]


def test_v2_remains_default_off_with_no_live_import():
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py", "core/permission_broker.py"):
        assert "owner_profile_v2" not in (root / relative).read_text(encoding="utf-8")
