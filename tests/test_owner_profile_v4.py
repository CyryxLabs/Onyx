from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

import core.owner_profile_v4 as profile
from memory.store import MemoryStore, MemoryStoreError


FROZEN = {
    "core/owner_profile_v1.py": "b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754",
    "tests/test_owner_profile_v1.py": "fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035",
    "core/owner_profile_v2.py": "12c459c1d34376a121e7a837d6dbeca365967c69affdc12b7d3e18ea1c76cd73",
    "tests/test_owner_profile_v2.py": "76f0481f91b82b650ece00d86ad0bfffe21fa4020e46d8e3dcaaaf7e36832714",
    "core/owner_profile_v3.py": "abf5e990b875a4ed04e9e9fed15eb550f972facf02b060683aa1e3abe88e4d16",
    "tests/test_owner_profile_v3.py": "f327a01f7d82a5df2d5e05d2bde70e3b89f06c6c4f69011e0ee257521033fe38",
}


def _write_config(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"owner_name": name, "keep": True}), encoding="utf-8")


def _owner(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["owner_name"]


def _owner_memory(store: MemoryStore) -> list[str]:
    return [
        record.content
        for record in store.list(kind="semantic", limit=None)
        if record.category == "preferences" and record.key == "owner_display_name"
    ]


def _journal_records(store: MemoryStore):
    return [
        record
        for record in store.list(kind="semantic", limit=None)
        if record.category == "preferences" and record.key == profile.JOURNAL_MEMORY_KEY
    ]


class FaultMemory:
    def __init__(self, delegate: MemoryStore):
        self.delegate = delegate
        self.cleanup = "none"
        self.commit_write = "none"
        self.fail_reads = False
        self.fail_owner_reads = False

    def list(self, **kwargs):
        if self.fail_reads:
            raise MemoryStoreError("journal read wrapper") from TimeoutError("journal root")
        records = self.delegate.list(**kwargs)
        if self.fail_owner_reads:
            raise MemoryStoreError("owner read wrapper") from TimeoutError("owner read root")
        return records

    def remember(self, content, **kwargs):
        is_journal = kwargs.get("key") == profile.JOURNAL_MEMORY_KEY
        state = json.loads(content).get("state") if is_journal else None
        if is_journal and state == "COMMITTED" and self.commit_write == "before":
            raise MemoryStoreError("commit before wrapper") from OSError("commit before root")
        result = self.delegate.remember(content, **kwargs)
        if is_journal and state == "COMMITTED" and self.commit_write == "after":
            raise MemoryStoreError("commit after wrapper") from OSError("commit after root")
        return result

    def forget_key(self, category, key):
        if key == profile.JOURNAL_MEMORY_KEY and self.cleanup == "before":
            raise MemoryStoreError("cleanup before wrapper") from PermissionError("cleanup before root")
        result = self.delegate.forget_key(category, key)
        if key == profile.JOURNAL_MEMORY_KEY and self.cleanup == "after":
            raise MemoryStoreError("cleanup after wrapper") from PermissionError("cleanup after root")
        return result


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


def _seed_alice(config: Path, memory) -> profile.OwnerProfileAuthority:
    _write_config(config, "Alice")
    authority = _authority(config, memory)
    assert authority.reconcile().display_name == "Alice"
    return authority


def _entry(state=profile.JournalState.PREPARED):
    return profile.JournalEntry("1" * 32, state, "set", "Alice", "Bob")


def test_v1_v2_v3_are_byte_for_byte_frozen():
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


@pytest.mark.parametrize(
    "crash_point,expected",
    [
        ("prepared", "Alice"),
        ("config-target", "Alice"),
        ("both-target", "Alice"),
        ("committed", "Bob"),
        ("compensated", "Alice"),
    ],
)
def test_restart_resolves_every_journal_transition(stores, crash_point, expected):
    config, memory = stores
    authority = _seed_alice(config, memory)
    entry = _entry()
    assert authority._persist_state(entry, profile.JournalState.PREPARED)[0] == entry
    if crash_point in {"config-target", "both-target", "committed"}:
        authority._write_config("Bob")
    if crash_point in {"both-target", "committed"}:
        authority._write_memory("Bob")
    if crash_point == "committed":
        assert authority._persist_state(entry, profile.JournalState.COMMITTED)[0].state is profile.JournalState.COMMITTED
    if crash_point == "compensated":
        assert authority._persist_state(entry, profile.JournalState.COMPENSATED)[0].state is profile.JournalState.COMPENSATED

    restarted = _authority(config, memory)
    snapshot = restarted.reconcile()

    assert snapshot.state is profile.OwnerProfileState.KNOWN
    assert snapshot.display_name == expected
    assert _owner(config) == expected
    assert _owner_memory(memory) == [expected]
    assert _journal_records(memory) == []


@pytest.mark.parametrize("cleanup_mode", ["before", "after"])
def test_cleanup_failure_after_commit_never_rolls_back_or_raises(stores, cleanup_mode):
    config, store = stores
    memory = FaultMemory(store)
    authority = _seed_alice(config, memory)
    memory.cleanup = cleanup_mode

    result = authority.set_name("Bob")

    assert result.state is profile.OwnerProfileState.KNOWN
    assert result.display_name == "Bob"
    assert authority.last_failure is None
    assert authority.last_cleanup_failure == profile.StageDiagnostic(
        "cleanup-journal", "PermissionError"
    )
    assert _owner(config) == "Bob"
    assert _owner_memory(store) == ["Bob"]
    restarted = _authority(config, memory)
    assert restarted.reconcile().display_name == "Bob"


def test_postcommit_committed_write_exception_is_success_when_decision_readback_matches(stores):
    config, store = stores
    memory = FaultMemory(store)
    authority = _seed_alice(config, memory)
    memory.commit_write = "after"

    result = authority.set_name("Bob")

    assert result.state is profile.OwnerProfileState.KNOWN
    assert result.display_name == "Bob"
    assert _owner(config) == "Bob"
    assert _owner_memory(store) == ["Bob"]


def test_precommit_committed_write_failure_compensates_and_raises(stores):
    config, store = stores
    memory = FaultMemory(store)
    authority = _seed_alice(config, memory)
    memory.commit_write = "before"

    with pytest.raises(profile.OwnerProfileTransactionError) as raised:
        authority.set_name("Bob")

    assert raised.value.decision is profile.JournalState.COMPENSATED
    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert _owner(config) == "Alice"
    assert _owner_memory(store) == ["Alice"]
    restarted = _authority(config, memory)
    assert restarted.reconcile().display_name == "Alice"


def test_target_readback_failure_keeps_prepared_until_restart_compensates(
    stores, monkeypatch
):
    config, store = stores
    memory = FaultMemory(store)
    authority = _seed_alice(config, memory)
    real_memory_name = authority._memory_name
    state = {"triggered": False}

    def fail_after_target():
        if _owner_memory(store) == ["Bob"]:
            state["triggered"] = True
        if state["triggered"]:
            raise profile.OwnerProfileError("owner read wrapper") from TimeoutError(
                "owner read root"
            )
        return real_memory_name()

    monkeypatch.setattr(authority, "_memory_name", fail_after_target)

    with pytest.raises(profile.OwnerProfileTransactionError):
        authority.set_name("Bob")

    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert authority.last_failure.journal_state == "PREPARED"
    assert authority.last_failure.decision is None
    assert len(_journal_records(store)) == 1
    restarted = _authority(config, memory)
    assert restarted.reconcile().display_name == "Alice"
    assert _journal_records(store) == []


def test_committed_recovery_readback_failure_is_degraded_and_retains_decision(
    stores, monkeypatch
):
    config, store = stores
    memory = FaultMemory(store)
    authority = _seed_alice(config, memory)
    entry = _entry(profile.JournalState.COMMITTED)
    authority._write_config("Bob")
    authority._write_memory("Bob")
    authority._write_journal(entry)
    restarted = _authority(config, memory)
    def fail_owner_read():
        raise profile.OwnerProfileError("owner read wrapper") from TimeoutError(
            "owner read root"
        )

    monkeypatch.setattr(restarted, "_memory_name", fail_owner_read)
    result = restarted.reconcile()

    assert result.state is profile.OwnerProfileState.DEGRADED
    assert restarted.last_failure.stage == "resolve-committed"
    assert restarted.last_failure.journal_state == "COMMITTED"
    assert len(_journal_records(store)) == 1
    healed = _authority(config, memory)
    assert healed.reconcile().display_name == "Bob"


def test_prior_reconcile_root_and_stage_are_not_overwritten_by_set(stores):
    config, memory = stores
    _write_config(config, "Alice")
    memory.remember(
        "{not-json",
        kind="semantic",
        source=profile.JOURNAL_SOURCE,
        citation=profile.JOURNAL_CITATION,
        category="preferences",
        key=profile.JOURNAL_MEMORY_KEY,
    )
    authority = _authority(config, memory)

    with pytest.raises(profile.OwnerProfileError, match="requires reconciliation"):
        authority.set_name("Bob")

    assert authority.last_failure.operation == "reconcile"
    assert authority.last_failure.stage == "read-journal"
    assert authority.last_failure.original_error_type == "JSONDecodeError"
    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED


def test_compensated_is_decision_and_cleanup_is_only_gc(stores):
    config, store = stores
    memory = FaultMemory(store)
    authority = _seed_alice(config, memory)
    entry = _entry(profile.JournalState.COMPENSATED)
    authority._write_config("Bob")
    authority._write_memory("Bob")
    authority._write_journal(entry)
    memory.cleanup = "before"

    result = _authority(config, memory).reconcile()

    assert result.display_name == "Alice"
    assert result.state is profile.OwnerProfileState.KNOWN
    assert _owner(config) == "Alice"
    assert _owner_memory(store) == ["Alice"]
    assert len(_journal_records(store)) == 1


def test_v4_is_default_off_with_no_live_import():
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py", "core/permission_broker.py"):
        assert "owner_profile_v4" not in (root / relative).read_text(encoding="utf-8")
