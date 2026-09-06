from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
from pathlib import Path

import pytest

import core.owner_profile_v5 as profile
from memory.store import MemoryStore


FROZEN = {
    "core/owner_profile_v1.py": "b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754",
    "tests/test_owner_profile_v1.py": "fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035",
    "core/owner_profile_v2.py": "12c459c1d34376a121e7a837d6dbeca365967c69affdc12b7d3e18ea1c76cd73",
    "tests/test_owner_profile_v2.py": "76f0481f91b82b650ece00d86ad0bfffe21fa4020e46d8e3dcaaaf7e36832714",
    "core/owner_profile_v3.py": "abf5e990b875a4ed04e9e9fed15eb550f972facf02b060683aa1e3abe88e4d16",
    "tests/test_owner_profile_v3.py": "f327a01f7d82a5df2d5e05d2bde70e3b89f06c6c4f69011e0ee257521033fe38",
    "core/owner_profile_v4.py": "a3ab381ed50c6fd539b10775ce0058b51c5a06b89bd87b1156e6793f6f438fd5",
    "tests/test_owner_profile_v4.py": "ee57cc1f0b629f72cbdd8f7d53bc2fd78451a7524995c5eac74d6e60d043d5f0",
}

KEY = b"K" * 32
PROFILE_ID = "owner-primary"
RUNTIME_ID = "install-9b8e3df0"


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


def _journal_memory(store: MemoryStore) -> list[str]:
    return [
        str(record.key)
        for record in store.list(kind="semantic", limit=None)
        if record.key in profile.RESERVED_MEMORY_JOURNAL_KEYS
    ]


@pytest.fixture()
def stores():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = root / "config" / "api_keys.json"
        journal = root / "runtime" / profile.JOURNAL_FILENAME
        memory = MemoryStore(root / "memory" / "onyx_memory.sqlite3")
        memory.initialize()
        yield root, config, journal, memory


def _authority(
    config: Path,
    journal: Path,
    memory,
    *,
    key: bytes = KEY,
    profile_id: str = PROFILE_ID,
    runtime_id: str = RUNTIME_ID,
) -> profile.OwnerProfileAuthority:
    return profile.OwnerProfileAuthority(
        config_path=config,
        memory=memory,
        journal_path=journal,
        journal_key=key,
        owner_profile_id=profile_id,
        runtime_instance=runtime_id,
    )


def _seed_alice(config: Path, journal: Path, memory) -> profile.OwnerProfileAuthority:
    _write_config(config, "Alice")
    authority = _authority(config, journal, memory)
    assert authority.reconcile().display_name == "Alice"
    return authority


def _prepared(authority: profile.OwnerProfileAuthority) -> profile.JournalEntry:
    latest = authority._read_journal()
    entry = profile.JournalEntry(
        sequence=(latest.sequence + 1 if latest else 1),
        state=profile.JournalState.PREPARED,
        operation="set",
        prior_name="Alice",
        target_name="Bob",
        nonce="1" * 64,
    )
    prepared, error = authority._persist_state(entry, profile.JournalState.PREPARED)
    assert error is None
    assert prepared is not None and prepared.state is profile.JournalState.PREPARED
    return prepared


def _mutate_journal(path: Path, mutation) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def test_v1_through_v4_are_byte_for_byte_frozen():
    root = Path(__file__).resolve().parents[1]
    for relative, expected in FROZEN.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize(
    "key",
    [None, "x" * 32, bytearray(b"x" * 32), b"", b"x" * 31, b"x" * 33],
)
def test_host_key_requires_exact_32_byte_value(stores, key):
    _root, config, journal, memory = stores
    with pytest.raises(TypeError, match="exact bytes of length 32"):
        _authority(config, journal, memory, key=key)


@pytest.mark.parametrize("identity", ["", " spaces ", "x" * 129, 1, True, "owner/escape"])
def test_host_bindings_are_strict(stores, identity):
    _root, config, journal, memory = stores
    with pytest.raises(TypeError):
        _authority(config, journal, memory, profile_id=identity)
    with pytest.raises(TypeError):
        _authority(config, journal, memory, runtime_id=identity)


def test_journal_path_cannot_alias_config_or_semantic_memory(stores):
    _root, config, _journal, memory = stores
    with pytest.raises(TypeError, match="separate from owner settings"):
        _authority(config, config, memory)
    with pytest.raises(TypeError, match="separate from semantic memory"):
        _authority(config, memory.path, memory)


def test_positive_first_contact_unicode_restart_correction_forget_and_projection_only(stores):
    _root, config, journal, memory = stores
    _write_config(config, "Sir")
    authority = _authority(config, journal, memory)
    assert authority.reconcile().state is profile.OwnerProfileState.UNKNOWN
    assert authority.address() == "Sir"
    assert authority.begin_contact() == profile.FIRST_CONTACT_QUESTION
    assert authority.begin_contact() is None
    assert authority.set_name("Jose\N{COMBINING ACUTE ACCENT} 李小龍").display_name == "José 李小龍"
    restarted = _authority(config, journal, memory)
    assert restarted.reconcile().display_name == "José 李小龍"
    assert restarted.correct_name("Renée").display_name == "Renée"
    assert restarted.forget_name().state is profile.OwnerProfileState.UNKNOWN
    assert restarted.address() == "Sir"
    assert "Efendim" not in restarted.prompt_directive()
    assert _owner(config) == ""
    assert _owner_memory(memory) == []
    assert _journal_memory(memory) == []
    assert journal.exists()
    assert restarted._read_journal().state is profile.JournalState.COMMITTED


def test_stable_terminal_reconcile_is_read_only(stores, monkeypatch):
    _root, config, journal, memory = stores
    _seed_alice(config, journal, memory).set_name("Bob")
    restarted = _authority(config, journal, memory)

    def no_write(_value):
        raise AssertionError("stable terminal reconciliation attempted a write")

    monkeypatch.setattr(restarted, "_write_owner_value", no_write)
    assert restarted.reconcile().display_name == "Bob"


@pytest.mark.parametrize(
    "crash_point,expected,final_state",
    [
        ("prepared", "Alice", profile.JournalState.COMPENSATED),
        ("config-target", "Alice", profile.JournalState.COMPENSATED),
        ("both-target", "Alice", profile.JournalState.COMPENSATED),
        ("committed", "Bob", profile.JournalState.COMMITTED),
        ("compensated", "Alice", profile.JournalState.COMPENSATED),
    ],
)
def test_restart_resolves_all_v4_crash_windows(stores, crash_point, expected, final_state):
    _root, config, journal, memory = stores
    authority = _seed_alice(config, journal, memory)
    entry = _prepared(authority)
    if crash_point in {"config-target", "both-target", "committed", "compensated"}:
        authority._write_config("Bob")
    if crash_point in {"both-target", "committed", "compensated"}:
        authority._write_memory("Bob")
    if crash_point == "committed":
        assert authority._persist_state(entry, profile.JournalState.COMMITTED)[0].state is final_state
    if crash_point == "compensated":
        assert authority._persist_state(entry, profile.JournalState.COMPENSATED)[0].state is final_state

    restarted = _authority(config, journal, memory)
    snapshot = restarted.reconcile()

    assert snapshot.state is profile.OwnerProfileState.KNOWN
    assert snapshot.display_name == expected
    assert _owner(config) == expected
    assert _owner_memory(memory) == [expected]
    assert restarted._read_journal().state is final_state


def test_precommit_commit_write_failure_compensates_and_postcommit_exception_succeeds(stores, monkeypatch):
    _root, config, journal, memory = stores
    authority = _seed_alice(config, journal, memory)
    real = authority.journal_backend._atomic_write
    mode = {"value": "before"}

    def fail_commit(payload):
        state = payload["records"][-1]["decision_state"]
        if state == "COMMITTED" and mode["value"] == "before":
            raise OSError("commit before root")
        real(payload)
        if state == "COMMITTED" and mode["value"] == "after":
            raise OSError("commit after root")

    monkeypatch.setattr(authority.journal_backend, "_atomic_write", fail_commit)
    with pytest.raises(profile.OwnerProfileTransactionError) as raised:
        authority.set_name("Bob")
    assert raised.value.decision is profile.JournalState.COMPENSATED
    assert _owner(config) == "Alice"

    mode["value"] = "after"
    assert authority.reconcile().display_name == "Alice"
    assert authority.set_name("Bob").display_name == "Bob"
    assert _owner(config) == "Bob"


def test_target_readback_failure_keeps_prepared_until_restart_compensates(stores, monkeypatch):
    _root, config, journal, store = stores
    authority = _seed_alice(config, journal, store)
    real_memory_name = authority._memory_name
    triggered = {"value": False}

    def fail_after_target():
        if _owner_memory(store) == ["Bob"]:
            triggered["value"] = True
        if triggered["value"]:
            raise profile.OwnerProfileError("owner read wrapper") from TimeoutError("owner read root")
        return real_memory_name()

    monkeypatch.setattr(authority, "_memory_name", fail_after_target)
    with pytest.raises(profile.OwnerProfileTransactionError):
        authority.set_name("Bob")
    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert authority._read_journal().state is profile.JournalState.PREPARED
    restarted = _authority(config, journal, store)
    assert restarted.reconcile().display_name == "Alice"
    assert restarted._read_journal().state is profile.JournalState.COMPENSATED


def test_committed_recovery_readback_failure_is_degraded_and_retains_decision(stores, monkeypatch):
    _root, config, journal, memory = stores
    authority = _seed_alice(config, journal, memory)
    entry = _prepared(authority)
    authority._write_config("Bob")
    authority._write_memory("Bob")
    assert authority._persist_state(entry, profile.JournalState.COMMITTED)[0].state is profile.JournalState.COMMITTED
    restarted = _authority(config, journal, memory)

    def fail_owner_read():
        raise profile.OwnerProfileError("owner read wrapper") from TimeoutError("owner read root")

    monkeypatch.setattr(restarted, "_semantic_state", fail_owner_read)
    result = restarted.reconcile()
    assert result.state is profile.OwnerProfileState.DEGRADED
    assert restarted.last_failure.stage == "reject-memory-journal"
    assert restarted._read_journal().state is profile.JournalState.COMMITTED
    assert _authority(config, journal, memory).reconcile().display_name == "Bob"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["records"][-1].__setitem__("target_name", "Mallory"),
        lambda data: data["records"][-1].__setitem__("mac", "0" * 64),
        lambda data: data["records"][-1].__setitem__("decision_state", "APPROVED"),
        lambda data: data["records"][-1].__setitem__("sequence", True),
        lambda data: data["records"][-1].__setitem__("nonce", "A" * 64),
        lambda data: data["records"][-1].__setitem__("unexpected", "field"),
        lambda data: data.__setitem__("unexpected", []),
    ],
)
def test_tamper_unknown_state_type_nonce_and_fields_fail_closed_degraded(stores, mutation):
    _root, config, journal, memory = stores
    authority = _seed_alice(config, journal, memory)
    authority.set_name("Bob")
    _mutate_journal(journal, mutation)
    restarted = _authority(config, journal, memory)
    result = restarted.reconcile()
    assert result.state is profile.OwnerProfileState.DEGRADED
    assert result.reconciled is False
    assert restarted.last_failure.stage == "read-journal"


@pytest.mark.parametrize("binding,value", [("profile", "owner-other"), ("runtime", "install-other")])
def test_cross_profile_and_runtime_binding_fail_closed(stores, binding, value):
    _root, config, journal, memory = stores
    _seed_alice(config, journal, memory).set_name("Bob")
    kwargs = {"profile_id": value} if binding == "profile" else {"runtime_id": value}
    restarted = _authority(config, journal, memory, **kwargs)
    assert restarted.reconcile().state is profile.OwnerProfileState.DEGRADED
    assert restarted.last_failure.stage == "read-journal"


def test_wrong_key_and_malformed_file_fail_closed_without_secret_diagnostics(stores):
    _root, config, journal, memory = stores
    _seed_alice(config, journal, memory).set_name("Bob")
    wrong = _authority(config, journal, memory, key=b"Z" * 32)
    assert wrong.reconcile().state is profile.OwnerProfileState.DEGRADED
    assert "ZZZZ" not in str(wrong.last_failure)
    journal.write_text("{not-json", encoding="utf-8")
    malformed = _authority(config, journal, memory)
    assert malformed.reconcile().state is profile.OwnerProfileState.DEGRADED


def test_replay_and_stable_sequence_substitution_are_rejected_in_same_runtime(stores):
    _root, config, journal, memory = stores
    authority = _seed_alice(config, journal, memory)
    entry = _prepared(authority)
    prepared_bytes = journal.read_bytes()
    assert authority._persist_state(entry, profile.JournalState.COMPENSATED)[0].state is profile.JournalState.COMPENSATED
    journal.write_bytes(prepared_bytes)
    with pytest.raises(profile.JournalIntegrityError, match="replay"):
        authority._read_journal()


def test_semantic_memory_cannot_inject_or_decide_journal_state(stores):
    _root, config, journal, memory = stores
    _write_config(config, "Alice")
    memory.remember(
        json.dumps({"decision_state": "COMMITTED", "target_name": "Mallory"}),
        kind="semantic",
        source="memory-tool",
        citation="user:preferences/owner_profile_v5_journal",
        category="preferences",
        key="owner_profile_v5_journal",
        salience=1.0,
    )
    authority = _authority(config, journal, memory)
    result = authority.reconcile()
    assert result.state is profile.OwnerProfileState.DEGRADED
    assert result.display_name is None
    assert authority.last_failure.stage == "reject-memory-journal"
    assert not journal.exists()


def test_sequence_transition_replay_and_downgrade_are_rejected(stores):
    _root, config, journal, memory = stores
    authority = _seed_alice(config, journal, memory)
    entry = _prepared(authority)
    decided, _ = authority._persist_state(entry, profile.JournalState.COMMITTED)
    assert decided is not None
    with pytest.raises(profile.JournalIntegrityError, match="append sequence"):
        authority.journal_backend.append(entry)
    stale_decision = profile.JournalEntry(
        decided.sequence + 1,
        profile.JournalState.COMPENSATED,
        decided.operation,
        decided.prior_name,
        decided.target_name,
        decided.nonce,
    )
    with pytest.raises(profile.JournalIntegrityError, match="decision lacks preparation"):
        authority.journal_backend.append(stale_decision)


@pytest.mark.parametrize(
    "entry",
    [
        profile.JournalEntry(True, profile.JournalState.PREPARED, "set", "Alice", "Bob", "1" * 64),
        profile.JournalEntry(1, "PREPARED", "set", "Alice", "Bob", "1" * 64),
        profile.JournalEntry(1, profile.JournalState.PREPARED, "approve", "Alice", "Bob", "1" * 64),
        profile.JournalEntry(1, profile.JournalState.PREPARED, "forget", "Alice", "Bob", "1" * 64),
        profile.JournalEntry(1, profile.JournalState.PREPARED, "set", "Alice", "Bob\nInjected", "1" * 64),
    ],
)
def test_malformed_append_is_rejected_before_creating_journal(stores, entry):
    _root, config, journal, memory = stores
    authority = _seed_alice(config, journal, memory)
    with pytest.raises((TypeError, profile.JournalIntegrityError)):
        authority.journal_backend.append(entry)
    assert not journal.exists()


def test_hmac_is_canonical_constant_time_and_sensitive_values_are_not_logged():
    source = inspect.getsource(profile)
    assert "hmac.compare_digest" in source
    assert "sort_keys=True" in source
    assert "allow_nan=False" in source
    assert "print(" not in source
    assert ".logger" not in source
    assert "logging." not in source


def test_v5_is_default_off_and_has_no_live_import_or_restart():
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py", "core/permission_broker.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "owner_profile_v5" not in source
    source = inspect.getsource(profile)
    assert "subprocess" not in source
    assert "os.environ" not in source
    assert "core.native_vault" not in source


def test_checkpoint_manifest_matches_candidate_bytes_and_declares_limits():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "docs/onyx/checkpoints/owner-profile-v5/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["isolated"] is True
    assert manifest["default_off"] is True
    assert manifest["live_wired"] is False
    for item in manifest["files"]:
        assert hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    limitations = " ".join(manifest["limitations"])
    assert "power-loss" in limitations
    assert "replay of an entire older valid snapshot" in limitations
    assert "sanctioned owner-profile key namespace" in limitations
