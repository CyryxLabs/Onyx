from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

import core.owner_profile_v8 as profile
from memory.store import MemoryStore


KEY = b"X" * 32
PROFILE_ID = "owner-primary"
RUNTIME_ID = "install-9b8e3df0"


class MemoryHead:
    def __init__(self):
        self.value = None
        self.lock = threading.Lock()

    def load(self, owner_profile_id):
        with self.lock:
            return self.value

    def compare_and_set(self, owner_profile_id, expected, desired):
        with self.lock:
            if self.value != expected:
                return False
            self.value = desired
            return True


class Lease:
    cross_session_guaranteed = True

    def __init__(self):
        self.lock = threading.RLock()
        self.local = threading.local()
        self.mode = "normal"

    @contextmanager
    def hold(self, owner_profile_id, *, timeout_seconds):
        if self.mode == "acquire-fail":
            raise profile.HostLeaseConflict("acquire failed")
        if not self.lock.acquire(timeout=timeout_seconds):
            raise profile.HostLeaseConflict("timeout")
        self.local.depth = getattr(self.local, "depth", 0) + 1
        try:
            yield self
        finally:
            self.local.depth -= 1
            self.lock.release()
            if self.mode == "release-fail":
                raise profile.HostLeaseError("release failed")

    def held(self):
        return getattr(self.local, "depth", 0) > 0


@pytest.fixture()
def stores():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = root / "config.json"
        journal = root / profile.JOURNAL_FILENAME
        memory = MemoryStore(root / "memory.sqlite3")
        memory.initialize()
        head = MemoryHead()
        lease = Lease()
        yield root, config, journal, memory, head, lease


def _authority(
    config,
    journal,
    memory,
    head,
    lease,
    *,
    max_bytes=profile.MAX_JOURNAL_BYTES,
    max_records=profile.MAX_JOURNAL_RECORDS,
):
    return profile.OwnerProfileAuthority(
        config_path=config,
        memory=memory,
        journal_path=journal,
        journal_key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        chain_head_store=head,
        transaction_lease=lease,
        _journal_max_bytes=max_bytes,
        _journal_max_records=max_records,
    )


def _bootstrap(config, journal, memory, head, lease):
    return profile.OwnerProfileAuthority.bootstrap(
        config_path=config,
        memory=memory,
        journal_path=journal,
        journal_key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        chain_head_store=head,
        transaction_lease=lease,
    )


def _owner(path):
    return json.loads(Path(path).read_text(encoding="utf-8")).get("owner_name")


def _owner_memory(memory):
    return [
        item.content
        for item in memory.list(kind="semantic", limit=None)
        if item.category == "preferences" and item.key == "owner_display_name"
    ]


def _seed_alice(config, journal, memory, head, lease):
    authority = _bootstrap(config, journal, memory, head, lease)
    assert authority.set_name("Alice").display_name == "Alice"
    return authority


def _install_terminal_snapshot(authority, *, terminal_sequence, prior, target):
    assert terminal_sequence >= 2
    base_sequence = terminal_sequence - 2
    base_mac = "a" * 64 if base_sequence else profile.GENESIS_MAC
    with authority._hold_transaction_lease():
        authority.journal_backend.bootstrap_empty()
        prepared = profile.JournalEntry(
            terminal_sequence - 1,
            profile.JournalState.PREPARED,
            "set",
            prior,
            target,
            "9" * 64,
        )
        raw_prepared = authority.journal_backend._raw_record(prepared, base_mac)
        prepared = profile.JournalEntry(
            prepared.sequence,
            prepared.state,
            prepared.operation,
            prepared.prior_name,
            prepared.target_name,
            prepared.nonce,
            raw_prepared["mac"],
        )
        terminal = profile.JournalEntry(
            terminal_sequence,
            profile.JournalState.COMMITTED,
            prepared.operation,
            prepared.prior_name,
            prepared.target_name,
            prepared.nonce,
        )
        raw_terminal = authority.journal_backend._raw_record(terminal, prepared.mac)
        terminal = profile.JournalEntry(
            terminal.sequence,
            terminal.state,
            terminal.operation,
            terminal.prior_name,
            terminal.target_name,
            terminal.nonce,
            raw_terminal["mac"],
        )
        payload = {
            "schema": profile.JOURNAL_SCHEMA,
            "base": authority.journal_backend._base(base_sequence, base_mac),
            "records": [raw_prepared, raw_terminal],
        }
        expected = authority.journal_backend._safe_file()
        authority.journal_backend._atomic_write(payload, expected=expected)
        authority._write_config(target)
        authority._write_memory(target)
        authority._chain_head_store.value = profile._head_for(PROFILE_ID, terminal)
    return terminal


def test_v1_through_v7_are_byte_for_byte_frozen():
    root = Path(__file__).resolve().parents[1]
    frozen = {
        "core/owner_profile_v1.py": "b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754",
        "tests/test_owner_profile_v1.py": "fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035",
        "core/owner_profile_v2.py": "12c459c1d34376a121e7a837d6dbeca365967c69affdc12b7d3e18ea1c76cd73",
        "tests/test_owner_profile_v2.py": "76f0481f91b82b650ece00d86ad0bfffe21fa4020e46d8e3dcaaaf7e36832714",
        "core/owner_profile_v3.py": "abf5e990b875a4ed04e9e9fed15eb550f972facf02b060683aa1e3abe88e4d16",
        "tests/test_owner_profile_v3.py": "f327a01f7d82a5df2d5e05d2bde70e3b89f06c6c4f69011e0ee257521033fe38",
        "core/owner_profile_v4.py": "a3ab381ed50c6fd539b10775ce0058b51c5a06b89bd87b1156e6793f6f438fd5",
        "tests/test_owner_profile_v4.py": "ee57cc1f0b629f72cbdd8f7d53bc2fd78451a7524995c5eac74d6e60d043d5f0",
        "core/owner_profile_v5.py": "53f6de7dfb7eb1f15f4f5c309257219a2ce67af7a662f0bb7e267fd1644daa18",
        "tests/test_owner_profile_v5.py": "1a4f9e2dcd5ec4ca1e3f4ff0390200ce56a6705dceb5499203d34a45dbab36ad",
        "core/owner_profile_v6.py": "f5bc62f7c326acea61ff8e2508814cbbbd7ac2c4833b2bcccb5353d44c530e0d",
        "tests/test_owner_profile_v6.py": "72d44825c927704faae4f46802820babf89e4645d7cf16b33dc923289a155df1",
        "core/owner_profile_v7.py": "6976ee481a9e494f4fa16548ac1d6a4eb8f5c160753cef3114b4d647220114e7",
        "tests/test_owner_profile_v7.py": "79f416d5d279b32e74279bcd981fbbe777b0f7886824e82149d6179b392d9466",
    }
    for relative, expected in frozen.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected


def test_positive_first_contact_unicode_restart_correction_forget(stores):
    _root, config, journal, memory, head, lease = stores
    authority = _bootstrap(config, journal, memory, head, lease)
    assert authority.begin_contact() == profile.FIRST_CONTACT_QUESTION
    assert authority.begin_contact() is None
    assert (
        authority.set_name("Jose\N{COMBINING ACUTE ACCENT} 李小龍").display_name
        == "José 李小龍"
    )
    restarted = _authority(config, journal, memory, head, lease)
    assert restarted.reconcile().display_name == "José 李小龍"
    assert restarted.correct_name("Renée").display_name == "Renée"
    assert restarted.forget_name().state is profile.OwnerProfileState.UNKNOWN
    assert restarted.address() == "Sir"
    assert "Efendim" not in restarted.prompt_directive()


def test_anchored_sequence_4096_advances_to_4098_and_survives_restart(stores):
    _root, config, journal, memory, head, lease = stores
    authority = _authority(config, journal, memory, head, lease)
    _install_terminal_snapshot(
        authority, terminal_sequence=4096, prior=None, target="Alice"
    )
    assert authority.reconcile().display_name == "Alice"
    assert authority.correct_name("Bob").display_name == "Bob"
    assert head.value.sequence == 4098
    restarted = _authority(config, journal, memory, head, lease)
    assert restarted.reconcile().display_name == "Bob"
    with restarted._hold_transaction_lease():
        assert restarted._consistency().latest.sequence == 4098


def test_long_repeated_compactions_bound_records_but_sequence_continues(stores):
    _root, config, journal, memory, head, lease = stores
    _bootstrap(config, journal, memory, head, lease)
    authority = _authority(config, journal, memory, head, lease, max_records=4)
    authority.set_name("Owner0")
    for index in range(1, 65):
        authority.correct_name(f"Owner{index}")
    assert head.value.sequence == 130
    with authority._hold_transaction_lease():
        base, records, _raw = authority.journal_backend.read_snapshot()
        assert base.sequence > 0
        assert len(records) <= 4
        assert records[-1].sequence == 130
    restarted = _authority(config, journal, memory, head, lease, max_records=4)
    assert restarted.reconcile().display_name == "Owner64"


def test_terminal_at_63_bit_max_succeeds_then_next_operation_rejects_before_writes(
    stores,
):
    _root, config, journal, memory, head, lease = stores
    authority = _authority(config, journal, memory, head, lease)
    _install_terminal_snapshot(
        authority,
        terminal_sequence=profile.MAX_CHAIN_SEQUENCE - 2,
        prior=None,
        target="Alice",
    )
    assert authority.correct_name("Bob").display_name == "Bob"
    assert head.value.sequence == profile.MAX_CHAIN_SEQUENCE
    before_journal = journal.read_bytes()
    before_config = config.read_bytes()
    before_memory = _owner_memory(memory)
    before_head = head.value
    with pytest.raises(profile.JournalIntegrityError, match="exceed 63-bit"):
        authority.correct_name("Carol")
    assert journal.read_bytes() == before_journal
    assert config.read_bytes() == before_config
    assert _owner_memory(memory) == before_memory
    assert head.value == before_head
    assert authority.last_failure.stage == "prepare-journal"


@pytest.mark.parametrize(
    "sequence",
    [-1, True, profile.MAX_CHAIN_SEQUENCE + 1],
)
def test_chain_head_sequence_type_and_range_are_strict(sequence):
    value = profile.ChainHead(1, PROFILE_ID, sequence, "a" * 64)
    with pytest.raises(profile.ChainHeadUnavailable):
        profile._validate_head(value, PROFILE_ID)


def test_terminal_transition_requires_exact_increment_of_two():
    expected = profile.ChainHead(1, PROFILE_ID, 5000, "a" * 64)
    for sequence in (5001, 5003, 4096):
        desired = profile.ChainHead(1, PROFILE_ID, sequence, "b" * 64)
        with pytest.raises(profile.ChainHeadConflict):
            profile._validate_transition(expected, desired, PROFILE_ID)
    profile._validate_transition(
        expected, profile.ChainHead(1, PROFILE_ID, 5002, "b" * 64), PROFILE_ID
    )


def test_windows_credential_cas_accepts_high_monotonic_sequence(monkeypatch):
    lease = Lease()
    storage = {}
    monkeypatch.setattr(profile.platform, "system", lambda: "Windows")

    def get_secret(reference):
        assert lease.held()
        return storage.get(reference)

    def set_secret(reference, value):
        assert lease.held()
        storage[reference] = value

    monkeypatch.setattr(profile.native_vault, "windows_get", get_secret)
    monkeypatch.setattr(profile.native_vault, "windows_set", set_secret)
    adapter = profile.WindowsCredentialChainHeadStore(host_lease=lease)
    reference = adapter._reference(PROFILE_ID)
    expected = profile.ChainHead(1, PROFILE_ID, 4096, "a" * 64)
    desired = profile.ChainHead(1, PROFILE_ID, 4098, "b" * 64)
    storage[reference] = adapter._encode(expected)
    assert adapter.compare_and_set(PROFILE_ID, expected, desired)
    with lease.hold(PROFILE_ID, timeout_seconds=1.0):
        assert adapter.load(PROFILE_ID) == desired


def test_every_journal_entrypoint_rejects_direct_access_without_lease(stores):
    _root, config, journal, memory, head, lease = stores
    authority = _seed_alice(config, journal, memory, head, lease)
    backend = authority.journal_backend
    sample = profile.JournalEntry(
        3, profile.JournalState.PREPARED, "set", "Alice", "Bob", "8" * 64
    )
    calls = (
        backend._safe_file,
        backend._read_raw,
        backend.read_snapshot,
        backend.read_all,
        backend.bootstrap_empty,
        lambda: backend.compact_terminal_history(head.value),
        lambda: backend.pair_required_bytes(sample),
        lambda: backend.append_prepared(sample, current_anchor=head.value),
        lambda: backend.append_terminal(sample),
        lambda: backend._atomic_write({}, expected=None),
    )
    for call in calls:
        with pytest.raises(profile.HostLeaseError, match="host-wide lease"):
            call()


def _instrument_journal(monkeypatch, authority, observed):
    names = (
        "_safe_file",
        "_read_raw",
        "read_snapshot",
        "read_all",
        "bootstrap_empty",
        "compact_terminal_history",
        "pair_required_bytes",
        "append_prepared",
        "append_terminal",
        "_atomic_write",
    )
    for name in names:
        original = getattr(authority.journal_backend, name)

        def guarded(*args, __name=name, __original=original, **kwargs):
            assert authority._lease_is_held(), (
                f"{__name} accessed journal outside lease"
            )
            observed.append(__name)
            return __original(*args, **kwargs)

        monkeypatch.setattr(authority.journal_backend, name, guarded)
    return names


def test_all_journal_methods_are_lease_held_in_normal_error_reconcile_and_recovery(
    stores, monkeypatch
):
    _root, config, journal, memory, head, lease = stores
    authority = _seed_alice(config, journal, memory, head, lease)
    observed = []
    names = _instrument_journal(monkeypatch, authority, observed)
    assert authority.reconcile().display_name == "Alice"
    assert authority.correct_name("Bob").display_name == "Bob"

    with authority._hold_transaction_lease():
        consistency = authority._consistency()
        prepared = profile.JournalEntry(
            consistency.latest.sequence + 1,
            profile.JournalState.PREPARED,
            "set",
            "Bob",
            "Carol",
            "7" * 64,
        )
        authority.journal_backend.append_prepared(
            prepared, current_anchor=consistency.baseline
        )
        authority._write_config("Carol")
    restarted = _authority(config, journal, memory, head, lease)
    recovery_observed = []
    _instrument_journal(monkeypatch, restarted, recovery_observed)
    assert restarted.reconcile().display_name == "Bob"
    assert "append_terminal" in recovery_observed
    assert "read_snapshot" in recovery_observed
    assert {"read_snapshot", "append_prepared", "append_terminal"}.issubset(observed)

    # The instrumentation deliberately fails before the backend's own guard so
    # an accidental unlocked call is visible at the exact journal boundary.
    with pytest.raises(AssertionError, match="outside lease"):
        authority.journal_backend.read_all()
    assert set(observed).issubset(set(names))


def test_acquire_failure_diagnostic_uses_unavailable_cache_without_journal_read(
    stores, monkeypatch
):
    _root, config, journal, memory, head, lease = stores
    _seed_alice(config, journal, memory, head, lease)
    lease.mode = "acquire-fail"
    restarted = _authority(config, journal, memory, head, lease)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("diagnostic attempted journal access without lease")

    monkeypatch.setattr(restarted.journal_backend, "read_all", forbidden)
    monkeypatch.setattr(restarted.journal_backend, "read_snapshot", forbidden)
    result = restarted.reconcile()
    assert result.state is profile.OwnerProfileState.DEGRADED
    assert restarted.last_failure.journal_state == "unavailable"


def test_release_failure_diagnostic_uses_cached_state_without_extra_read(
    stores, monkeypatch
):
    _root, config, journal, memory, head, lease = stores
    _seed_alice(config, journal, memory, head, lease)
    restarted = _authority(config, journal, memory, head, lease)
    reads = {"all": 0}
    original = restarted.journal_backend.read_all

    def count_read_all(*args, **kwargs):
        reads["all"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(restarted.journal_backend, "read_all", count_read_all)
    lease.mode = "release-fail"
    result = restarted.reconcile()
    assert result.state is profile.OwnerProfileState.DEGRADED
    assert reads["all"] == 0
    assert restarted.last_failure.journal_state == "COMMITTED"


def test_stale_rollback_and_preforget_resurrection_remain_closed(stores):
    _root, config, journal, memory, head, lease = stores
    authority = _seed_alice(config, journal, memory, head, lease)
    authority.correct_name("Bob")
    bob = journal.read_bytes()
    authority.correct_name("Carol")
    journal.write_bytes(bob)
    stale = _authority(config, journal, memory, head, lease)
    assert stale.reconcile().state is profile.OwnerProfileState.DEGRADED
    assert _owner(config) == "Carol"

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        mem = MemoryStore(root / "memory.sqlite3")
        mem.initialize()
        local_head = MemoryHead()
        local_lease = Lease()
        auth = _seed_alice(
            root / "config.json",
            root / profile.JOURNAL_FILENAME,
            mem,
            local_head,
            local_lease,
        )
        preforget = (root / profile.JOURNAL_FILENAME).read_bytes()
        auth.forget_name()
        (root / profile.JOURNAL_FILENAME).write_bytes(preforget)
        restarted = _authority(
            root / "config.json",
            root / profile.JOURNAL_FILENAME,
            mem,
            local_head,
            local_lease,
        )
        assert restarted.reconcile().state is profile.OwnerProfileState.DEGRADED
        assert _owner(root / "config.json") == ""
        assert _owner_memory(mem) == []


def test_global_mutex_credential_cas_capacity_and_default_off_are_preserved():
    source = Path(profile.__file__).read_text(encoding="utf-8")
    assert "WindowsHostTransactionLease" in source
    assert "windows_get" in source and "windows_set" in source
    assert "append_prepared" in source and "MAX_CHAIN_SEQUENCE" in source
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/permission_broker.py",
    ):
        assert "owner_profile_v8" not in (root / relative).read_text(encoding="utf-8")


def test_checkpoint_manifest_matches_candidate_bytes_and_declared_limits():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "docs/onyx/checkpoints/owner-profile-v8/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["isolated"] is True
    assert manifest["default_off"] is True
    assert manifest["live_wired"] is False
    assert manifest["sequence_protocol"]["maximum_terminal_sequence"] == (2**63 - 1)
    assert manifest["lease_protocol"]["direct_unleased_journal_entrypoints"] == (
        "all rejected"
    )
    for item in manifest["files"]:
        assert (
            hashlib.sha256((root / item["path"]).read_bytes()).hexdigest()
            == item["sha256"]
        )
    limits = " ".join(manifest["limitations"])
    assert "Global mutex" in limits and "Credential Manager" in limits
    assert "macOS Keychain" in limits and "Linux Secret Service" in limits
