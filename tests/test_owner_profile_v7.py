from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

import core.owner_profile_v7 as profile
from memory.store import MemoryStore


KEY = b"W" * 32
PROFILE_ID = "owner-primary"
RUNTIME_ID = "install-9b8e3df0"


class MemoryHead:
    def __init__(self):
        self.value = None
        self.lock = threading.Lock()
        self.mode = "normal"

    def load(self, owner_profile_id):
        with self.lock:
            return self.value

    def compare_and_set(self, owner_profile_id, expected, desired):
        with self.lock:
            if self.mode == "before":
                raise OSError("CAS before root")
            if self.value != expected:
                return False
            self.value = desired
            if self.mode == "after":
                raise OSError("CAS after root")
            return True


class ReentrantLease:
    cross_session_guaranteed = True

    def __init__(self):
        self.lock = threading.RLock()
        self.local = threading.local()
        self.max_depth = 0
        self.mode = "normal"

    @contextmanager
    def hold(self, owner_profile_id, *, timeout_seconds):
        if self.mode == "timeout":
            raise profile.HostLeaseConflict("test timeout")
        if not self.lock.acquire(timeout=timeout_seconds):
            raise profile.HostLeaseConflict("test timeout")
        self.local.depth = getattr(self.local, "depth", 0) + 1
        self.max_depth = max(self.max_depth, self.local.depth)
        try:
            yield self
        finally:
            self.local.depth -= 1
            self.lock.release()

    def held(self):
        return getattr(self.local, "depth", 0) > 0


class UnsafeLease(ReentrantLease):
    cross_session_guaranteed = False


@pytest.fixture()
def stores():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = root / "config" / "api_keys.json"
        journal = root / "runtime" / profile.JOURNAL_FILENAME
        memory = MemoryStore(root / "memory" / "onyx_memory.sqlite3")
        memory.initialize()
        head = MemoryHead()
        lease = ReentrantLease()
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


def _owner(config):
    if not Path(config).exists():
        return None
    return json.loads(Path(config).read_text(encoding="utf-8")).get("owner_name")


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


def test_v1_through_v6_are_byte_for_byte_frozen():
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
    }
    for relative, expected in frozen.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected


def test_positive_first_contact_unicode_restart_correction_forget_and_reentrant_lease(
    stores,
):
    _root, config, journal, memory, head, lease = stores
    authority = _bootstrap(config, journal, memory, head, lease)
    assert authority.reconcile().state is profile.OwnerProfileState.UNKNOWN
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
    assert lease.max_depth >= 2


def test_unsafe_or_missing_cross_session_lease_is_rejected(stores):
    _root, config, journal, memory, head, _lease = stores
    with pytest.raises(TypeError, match="cross-session"):
        _authority(config, journal, memory, head, UnsafeLease())
    with pytest.raises(TypeError, match="host-wide lease protocol"):
        _authority(config, journal, memory, head, object())


def test_lease_timeout_is_sticky_degraded_without_any_projection_write(stores):
    _root, config, journal, memory, head, lease = stores
    _seed_alice(config, journal, memory, head, lease)
    before_config = config.read_bytes()
    before_memory = _owner_memory(memory)
    lease.mode = "timeout"
    restarted = _authority(config, journal, memory, head, lease)
    result = restarted.reconcile()
    assert result.state is profile.OwnerProfileState.DEGRADED
    assert restarted.last_failure.stage == "host-transaction-lease"
    assert config.read_bytes() == before_config
    assert _owner_memory(memory) == before_memory
    lease.mode = "normal"
    assert restarted.reconcile().state is profile.OwnerProfileState.DEGRADED


def test_journal_mutation_refuses_to_run_outside_lease(stores):
    _root, config, journal, memory, head, lease = stores
    authority = _bootstrap(config, journal, memory, head, lease)
    entry = profile.JournalEntry(
        1, profile.JournalState.PREPARED, "set", None, "Alice", "1" * 64
    )
    with pytest.raises(profile.HostLeaseError):
        authority.journal_backend.append_prepared(
            entry, current_anchor=profile.genesis_head(PROFILE_ID)
        )


def test_reconcile_and_entire_transaction_touch_every_authority_surface_under_lease(
    stores, monkeypatch
):
    _root, config, journal, memory, head, lease = stores
    authority = _seed_alice(config, journal, memory, head, lease)
    observed = []

    def wrap(target, name):
        original = getattr(target, name)

        def guarded(*args, **kwargs):
            assert lease.held(), f"{name} escaped the host-wide lease"
            observed.append(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(target, name, guarded)

    for name in ("_read_config", "_write_config", "_write_memory", "_memory_name"):
        wrap(authority, name)
    for name in ("load", "compare_and_set"):
        wrap(head, name)
    assert authority.reconcile().display_name == "Alice"
    assert authority.set_name("Bob").display_name == "Bob"
    assert {
        "_read_config",
        "_write_config",
        "_write_memory",
        "_memory_name",
        "load",
        "compare_and_set",
    }.issubset(observed)


def _probe_pair_requirement(root: Path) -> int:
    journal = root / "probe" / profile.JOURNAL_FILENAME

    def held():
        return True

    backend = profile.AuthenticatedJournalBackend(
        journal,
        key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        lease_held=held,
    )
    backend.bootstrap_empty()
    prepared = profile.JournalEntry(
        1, profile.JournalState.PREPARED, "set", None, "Alice", "1" * 64
    )
    return backend.pair_required_bytes(prepared)


def test_pair_capacity_exact_fit_and_compensation_consumes_reserved_bytes(stores):
    root, _config, _journal, _memory, _head, _lease = stores
    required = _probe_pair_requirement(root)
    path = root / "exact" / profile.JOURNAL_FILENAME
    backend = profile.AuthenticatedJournalBackend(
        path,
        key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        lease_held=lambda: True,
        max_journal_bytes=required,
    )
    backend.bootstrap_empty()
    prepared = profile.JournalEntry(
        1, profile.JournalState.PREPARED, "set", None, "Alice", "1" * 64
    )
    prepared = backend.append_prepared(
        prepared, current_anchor=profile.genesis_head(PROFILE_ID)
    )
    compensated = profile.JournalEntry(
        2,
        profile.JournalState.COMPENSATED,
        prepared.operation,
        prepared.prior_name,
        prepared.target_name,
        prepared.nonce,
    )
    backend.append_terminal(compensated)
    assert path.stat().st_size == required


def test_pair_capacity_one_byte_short_rejects_before_prepared(stores):
    root, _config, _journal, _memory, _head, _lease = stores
    required = _probe_pair_requirement(root)
    path = root / "short" / profile.JOURNAL_FILENAME
    backend = profile.AuthenticatedJournalBackend(
        path,
        key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        lease_held=lambda: True,
        max_journal_bytes=required - 1,
    )
    backend.bootstrap_empty()
    before = path.read_bytes()
    prepared = profile.JournalEntry(
        1, profile.JournalState.PREPARED, "set", None, "Alice", "1" * 64
    )
    with pytest.raises(
        profile.JournalIntegrityError, match="reserve PREPARED and terminal"
    ):
        backend.append_prepared(
            prepared, current_anchor=profile.genesis_head(PROFILE_ID)
        )
    assert path.read_bytes() == before
    assert backend.read_all() == []


def test_recovery_uses_capacity_reserved_by_prepared(stores):
    root, config, _journal, memory, head, lease = stores
    required = _probe_pair_requirement(root)
    journal = root / "recovery" / profile.JOURNAL_FILENAME
    authority = profile.OwnerProfileAuthority(
        config_path=config,
        memory=memory,
        journal_path=journal,
        journal_key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        chain_head_store=head,
        transaction_lease=lease,
        _journal_max_bytes=required,
    )
    with authority._hold_transaction_lease():
        authority.journal_backend.bootstrap_empty()
        assert head.compare_and_set(PROFILE_ID, None, profile.genesis_head(PROFILE_ID))
        prepared = profile.JournalEntry(
            1, profile.JournalState.PREPARED, "set", None, "Alice", "1" * 64
        )
        authority.journal_backend.append_prepared(
            prepared, current_anchor=profile.genesis_head(PROFILE_ID)
        )
        authority._write_config("Alice")
        authority._write_memory("Alice")
    restarted = _authority(config, journal, memory, head, lease, max_bytes=required)
    assert restarted.reconcile().state is profile.OwnerProfileState.UNKNOWN
    with restarted._hold_transaction_lease():
        assert restarted._consistency().latest.state is profile.JournalState.COMPENSATED
    assert journal.stat().st_size == required


def test_terminal_history_compacts_before_new_pair_admission(stores):
    root, _config, _journal, _memory, _head, _lease = stores
    path = root / "compact" / profile.JOURNAL_FILENAME

    def held():
        return True

    probe = profile.AuthenticatedJournalBackend(
        path,
        key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        lease_held=held,
    )
    probe.bootstrap_empty()
    head = profile.genesis_head(PROFILE_ID)
    for sequence, prior, target in ((1, None, "Alice"), (3, "Alice", "Bob")):
        prepared = profile.JournalEntry(
            sequence,
            profile.JournalState.PREPARED,
            "set",
            prior,
            target,
            str(sequence) * 64,
        )
        prepared = probe.append_prepared(prepared, current_anchor=head)
        terminal = probe.append_terminal(
            profile.JournalEntry(
                sequence + 1,
                profile.JournalState.COMMITTED,
                prepared.operation,
                prepared.prior_name,
                prepared.target_name,
                prepared.nonce,
            )
        )
        head = profile.v6._head_for(PROFILE_ID, terminal)
    third = profile.JournalEntry(
        5, profile.JournalState.PREPARED, "set", "Bob", "Carol", "5" * 64
    )
    before_compaction = path.read_bytes()
    required_before = probe.pair_required_bytes(third)
    assert len(probe.read_all()) == 4
    probe.compact_terminal_history(head)
    required_after = probe.pair_required_bytes(third)
    assert required_after < required_before
    assert len(probe.read_all()) == 2
    path.write_bytes(before_compaction)
    limited = profile.AuthenticatedJournalBackend(
        path,
        key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        lease_held=held,
        max_journal_bytes=required_after,
    )
    limited.append_prepared(third, current_anchor=head)
    base, records, _raw = limited.read_snapshot()
    assert base.sequence == 2
    assert len(records) == 3
    assert records[-1].state is profile.JournalState.PREPARED


@pytest.mark.parametrize(
    "stage,expected",
    [
        ("prepared", "Alice"),
        ("config-target", "Alice"),
        ("projections-target", "Alice"),
        ("terminal-before-cas", "Bob"),
        ("after-cas", "Bob"),
    ],
)
def test_crash_windows_remain_resolvable_under_lease(stores, stage, expected):
    _root, config, journal, memory, head, lease = stores
    authority = _seed_alice(config, journal, memory, head, lease)
    with authority._hold_transaction_lease():
        consistency = authority._consistency()
        prepared = profile.JournalEntry(
            3, profile.JournalState.PREPARED, "set", "Alice", "Bob", "3" * 64
        )
        prepared = authority.journal_backend.append_prepared(
            prepared, current_anchor=consistency.baseline
        )
        if stage in {
            "config-target",
            "projections-target",
            "terminal-before-cas",
            "after-cas",
        }:
            authority._write_config("Bob")
        if stage in {"projections-target", "terminal-before-cas", "after-cas"}:
            authority._write_memory("Bob")
        if stage in {"terminal-before-cas", "after-cas"}:
            terminal = authority._append_decision(
                prepared, profile.JournalState.COMMITTED
            )
            if stage == "after-cas":
                authority._advance_anchor(
                    consistency.baseline, profile.v6._head_for(PROFILE_ID, terminal)
                )
    restarted = _authority(config, journal, memory, head, lease)
    assert restarted.reconcile().display_name == expected
    assert _owner(config) == expected
    assert _owner_memory(memory) == [expected]


def test_commit_journal_and_anchor_advance_diagnostics_are_distinct(
    stores, monkeypatch
):
    _root, config, journal, memory, head, lease = stores
    authority = _seed_alice(config, journal, memory, head, lease)

    def fail_terminal(_entry):
        raise OSError("terminal root")

    monkeypatch.setattr(authority.journal_backend, "append_terminal", fail_terminal)
    with pytest.raises(profile.OwnerProfileTransactionError):
        authority.set_name("Bob")
    assert authority.last_failure.stage == "commit-journal"
    assert authority.last_failure.journal_state == "PREPARED"

    healed = _authority(config, journal, memory, head, lease)
    assert healed.reconcile().display_name == "Alice"
    head.mode = "before"
    with pytest.raises(profile.OwnerProfileTransactionError):
        healed.set_name("Bob")
    assert healed.last_failure.stage == "advance-chain-head"
    assert healed.last_failure.journal_state == "COMMITTED"


def test_stale_bob_and_preforget_snapshots_never_rewrite_or_resurrect(stores):
    _root, config, journal, memory, head, lease = stores
    authority = _seed_alice(config, journal, memory, head, lease)
    authority.set_name("Bob")
    bob = journal.read_bytes()
    authority.correct_name("Carol")
    journal.write_bytes(bob)
    stale = _authority(config, journal, memory, head, lease)
    assert stale.reconcile().state is profile.OwnerProfileState.DEGRADED
    assert _owner(config) == "Carol"
    assert _owner_memory(memory) == ["Carol"]

    # Restore the current journal, then prove that a pre-forget snapshot cannot
    # resurrect the owner after a committed forget.
    authority = _authority(config, journal, memory, head, lease)
    # The stale journal is intentionally unusable; create a fresh independent
    # case for forget resurrection.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        cfg = root / "config.json"
        mem = MemoryStore(root / "memory.sqlite3")
        mem.initialize()
        h = MemoryHead()
        local_lease = ReentrantLease()
        auth = _seed_alice(cfg, root / profile.JOURNAL_FILENAME, mem, h, local_lease)
        auth.correct_name("Bob")
        preforget = (root / profile.JOURNAL_FILENAME).read_bytes()
        auth.forget_name()
        (root / profile.JOURNAL_FILENAME).write_bytes(preforget)
        restarted = _authority(
            cfg, root / profile.JOURNAL_FILENAME, mem, h, local_lease
        )
        assert restarted.reconcile().state is profile.OwnerProfileState.DEGRADED
        assert _owner(cfg) == ""
        assert _owner_memory(mem) == []


class FileLease:
    cross_session_guaranteed = True

    def __init__(self, path):
        self.path = Path(path)
        self.local = threading.local()

    @contextmanager
    def hold(self, owner_profile_id, *, timeout_seconds):
        depth = getattr(self.local, "depth", 0)
        if depth:
            self.local.depth = depth + 1
            try:
                yield self
            finally:
                self.local.depth -= 1
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        locked = False
        try:
            while not locked:
                try:
                    if os.name == "nt":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise profile.HostLeaseConflict("file lease timeout")
                    time.sleep(0.01)
            self.local.depth = 1
            yield self
        finally:
            self.local.depth = 0
            if locked:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


class FileHead:
    def __init__(self, path):
        self.path = Path(path)

    def load(self, owner_profile_id):
        if not self.path.exists():
            return None
        value = json.loads(self.path.read_text(encoding="utf-8"))
        return profile.ChainHead(
            value["version"],
            value["owner_profile_id"],
            value["sequence"],
            value["head_mac"],
        )

    def compare_and_set(self, owner_profile_id, expected, desired):
        if self.load(owner_profile_id) != expected:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "version": desired.version,
                    "owner_profile_id": desired.owner_profile_id,
                    "sequence": desired.sequence,
                    "head_mac": desired.head_mac,
                }
            ),
            encoding="utf-8",
        )
        return self.load(owner_profile_id) == desired


def _multiprocess_writer(root_text, name, queue):
    root = Path(root_text)
    memory = MemoryStore(root / "memory.sqlite3")
    memory.initialize()
    authority = profile.OwnerProfileAuthority(
        config_path=root / "config.json",
        memory=memory,
        journal_path=root / profile.JOURNAL_FILENAME,
        journal_key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        chain_head_store=FileHead(root / "head.json"),
        transaction_lease=FileLease(root / "transaction.lock"),
    )
    try:
        result = authority.set_name(name)
        queue.put(("ok", result.display_name))
    except Exception as exc:
        queue.put(("error", type(exc).__name__))


def test_multiprocess_writers_have_one_serial_order_and_no_divergence():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        memory = MemoryStore(root / "memory.sqlite3")
        memory.initialize()
        head = FileHead(root / "head.json")
        lease = FileLease(root / "transaction.lock")
        authority = profile.OwnerProfileAuthority.bootstrap(
            config_path=root / "config.json",
            memory=memory,
            journal_path=root / profile.JOURNAL_FILENAME,
            journal_key=KEY,
            owner_profile_id=PROFILE_ID,
            runtime_instance=RUNTIME_ID,
            chain_head_store=head,
            transaction_lease=lease,
        )
        authority.set_name("Alice")
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        processes = [
            context.Process(target=_multiprocess_writer, args=(temporary, name, queue))
            for name in ("Bob", "Carol")
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
        results = [queue.get(timeout=5) for _ in processes]
        assert sorted(status for status, _name in results) == ["ok", "ok"]
        final = _authority(
            root / "config.json",
            root / profile.JOURNAL_FILENAME,
            memory,
            head,
            lease,
        )
        snapshot = final.reconcile()
        assert snapshot.state is profile.OwnerProfileState.KNOWN
        assert snapshot.display_name in {"Bob", "Carol"}
        with final._hold_transaction_lease():
            consistency = final._consistency()
            assert consistency.latest.sequence == 6
            assert consistency.anchor.sequence == 6
            committed_targets = [
                item.target_name
                for item in final.journal_backend.read_all()
                if item.state is profile.JournalState.COMMITTED
            ]
            assert committed_targets[-2:] in (["Bob", "Carol"], ["Carol", "Bob"])


def test_windows_lease_is_global_bounded_and_has_no_local_false_fallback(monkeypatch):
    monkeypatch.setattr(profile.platform, "system", lambda: "Windows")
    lease = profile.WindowsHostTransactionLease()
    assert lease.cross_session_guaranteed is True
    mutex = profile._GlobalWindowsMutex(PROFILE_ID, timeout_seconds=1)
    assert mutex.name.startswith("Global\\")
    source = Path(profile.__file__).read_text(encoding="utf-8")
    assert 'f"Local\\\\CyryxLabs.Onyx.OwnerProfileTransaction' not in source
    assert "timeout_seconds" in source


def test_v7_is_default_off_with_no_live_import_restart_or_commit():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/permission_broker.py",
    ):
        assert "owner_profile_v7" not in (root / relative).read_text(encoding="utf-8")


def test_checkpoint_manifest_matches_candidate_bytes_and_declared_limits():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "docs/onyx/checkpoints/owner-profile-v7/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["isolated"] is True
    assert manifest["default_off"] is True
    assert manifest["live_wired"] is False
    assert manifest["capacity_protocol"]["exact_fit_tested"] is True
    assert manifest["lease_protocol"]["cross_session_guarantee_required"] is True
    for item in manifest["files"]:
        assert (
            hashlib.sha256((root / item["path"]).read_bytes()).hexdigest()
            == item["sha256"]
        )
    limits = " ".join(manifest["limitations"])
    assert "Global Windows mutex" in limits
    assert "test-only file-backed lease" in limits
    assert "macOS Keychain" in limits and "Linux Secret Service" in limits
