from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import threading
from pathlib import Path

import pytest

import core.owner_profile_v6 as profile
from memory.store import MemoryStore


KEY = b"V" * 32
PROFILE_ID = "owner-primary"
RUNTIME_ID = "install-9b8e3df0"


class MemoryChainHeadStore:
    def __init__(self):
        self.value: profile.ChainHead | None = None
        self.lock = threading.Lock()
        self.fail_load = False
        self.cas_mode = "normal"
        self.cas_calls = 0

    def load(self, owner_profile_id: str) -> profile.ChainHead | None:
        if self.fail_load:
            raise OSError("anchor load root")
        with self.lock:
            return self.value

    def compare_and_set(self, owner_profile_id, expected, desired):
        with self.lock:
            self.cas_calls += 1
            if self.cas_mode == "before":
                raise OSError("anchor CAS before root")
            if self.value != expected:
                return False
            self.value = desired
            if self.cas_mode == "after":
                raise OSError("anchor CAS after root")
            return True


@pytest.fixture()
def stores():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = root / "config" / "api_keys.json"
        journal = root / "runtime" / profile.JOURNAL_FILENAME
        memory = MemoryStore(root / "memory" / "onyx_memory.sqlite3")
        memory.initialize()
        head = MemoryChainHeadStore()
        yield root, config, journal, memory, head


def _authority(config, journal, memory, head, *, profile_id=PROFILE_ID, key=KEY):
    return profile.OwnerProfileAuthority(
        config_path=config,
        memory=memory,
        journal_path=journal,
        journal_key=key,
        owner_profile_id=profile_id,
        runtime_instance=RUNTIME_ID,
        chain_head_store=head,
    )


def _bootstrap(config, journal, memory, head):
    return profile.OwnerProfileAuthority.bootstrap(
        config_path=config,
        memory=memory,
        journal_path=journal,
        journal_key=KEY,
        owner_profile_id=PROFILE_ID,
        runtime_instance=RUNTIME_ID,
        chain_head_store=head,
    )


def _owner(config: Path) -> str | None:
    if not config.exists():
        return None
    return json.loads(config.read_text(encoding="utf-8")).get("owner_name")


def _owner_memory(memory: MemoryStore) -> list[str]:
    return [
        item.content
        for item in memory.list(kind="semantic", limit=None)
        if item.category == "preferences" and item.key == "owner_display_name"
    ]


def _seed_alice(config, journal, memory, head):
    authority = _bootstrap(config, journal, memory, head)
    assert authority.set_name("Alice").display_name == "Alice"
    return authority


def _prepare(authority, target="Bob"):
    consistency = authority._consistency()
    latest_sequence = consistency.latest.sequence if consistency.latest else 0
    prepared = profile.JournalEntry(
        latest_sequence + 1,
        profile.JournalState.PREPARED,
        "set",
        "Alice",
        target,
        "1" * 64,
    )
    return authority.journal_backend.append(prepared), consistency.baseline


def test_v1_through_v5_are_byte_for_byte_frozen():
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
    }
    for relative, expected in frozen.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected


def test_positive_first_contact_unicode_restart_correction_and_forget(stores):
    _root, config, journal, memory, head = stores
    authority = _bootstrap(config, journal, memory, head)
    assert authority.reconcile().state is profile.OwnerProfileState.UNKNOWN
    assert authority.address() == "Sir"
    assert authority.begin_contact() == profile.FIRST_CONTACT_QUESTION
    assert authority.begin_contact() is None
    assert (
        authority.set_name("Jose\N{COMBINING ACUTE ACCENT} 李小龍").display_name
        == "José 李小龍"
    )
    restarted = _authority(config, journal, memory, head)
    assert restarted.reconcile().display_name == "José 李小龍"
    assert restarted.correct_name("Renée").display_name == "Renée"
    assert restarted.forget_name().state is profile.OwnerProfileState.UNKNOWN
    assert _owner(config) == ""
    assert _owner_memory(memory) == []
    assert restarted.address() == "Sir"
    assert "Efendim" not in restarted.prompt_directive()
    assert head.value.sequence == 6


@pytest.mark.parametrize(
    "stage,expected,terminal",
    [
        ("prepared", "Alice", profile.JournalState.COMPENSATED),
        ("config-target", "Alice", profile.JournalState.COMPENSATED),
        ("projections-target", "Alice", profile.JournalState.COMPENSATED),
        ("terminal-before-cas", "Bob", profile.JournalState.COMMITTED),
        ("after-cas", "Bob", profile.JournalState.COMMITTED),
        ("compensated-before-cas", "Alice", profile.JournalState.COMPENSATED),
        ("compensated-after-cas", "Alice", profile.JournalState.COMPENSATED),
    ],
)
def test_crash_recovery_at_every_stage(stores, stage, expected, terminal):
    _root, config, journal, memory, head = stores
    authority = _seed_alice(config, journal, memory, head)
    prepared, baseline = _prepare(authority)
    if stage in {
        "config-target",
        "projections-target",
        "terminal-before-cas",
        "after-cas",
        "compensated-before-cas",
        "compensated-after-cas",
    }:
        authority._write_config("Bob")
    if stage in {
        "projections-target",
        "terminal-before-cas",
        "after-cas",
        "compensated-before-cas",
        "compensated-after-cas",
    }:
        authority._write_memory("Bob")
    if stage in {"terminal-before-cas", "after-cas"}:
        decided = authority._append_decision(prepared, profile.JournalState.COMMITTED)
        if stage == "after-cas":
            assert head.compare_and_set(
                PROFILE_ID, baseline, profile._head_for(PROFILE_ID, decided)
            )
    if stage in {"compensated-before-cas", "compensated-after-cas"}:
        assert authority._drive_value("Alice", prefix="test")[0]
        decided = authority._append_decision(prepared, profile.JournalState.COMPENSATED)
        if stage == "compensated-after-cas":
            assert head.compare_and_set(
                PROFILE_ID, baseline, profile._head_for(PROFILE_ID, decided)
            )

    restarted = _authority(config, journal, memory, head)
    result = restarted.reconcile()
    assert result.state is profile.OwnerProfileState.KNOWN
    assert result.display_name == expected
    assert _owner(config) == expected
    assert _owner_memory(memory) == [expected]
    assert restarted._consistency().latest.state is terminal
    assert head.value.sequence == restarted._consistency().latest.sequence


def test_post_cas_exception_is_success_when_readback_matches(stores):
    _root, config, journal, memory, head = stores
    authority = _seed_alice(config, journal, memory, head)
    head.cas_mode = "after"
    assert authority.set_name("Bob").display_name == "Bob"
    assert head.value.sequence == 4


def test_pre_cas_unavailability_is_sticky_degraded_and_never_compensates_committed(
    stores,
):
    _root, config, journal, memory, head = stores
    authority = _seed_alice(config, journal, memory, head)
    head.cas_mode = "before"
    with pytest.raises(profile.OwnerProfileTransactionError):
        authority.set_name("Bob")
    assert authority.snapshot.state is profile.OwnerProfileState.DEGRADED
    assert _owner(config) == "Bob"
    assert _owner_memory(memory) == ["Bob"]
    head.cas_mode = "normal"
    assert authority.reconcile().state is profile.OwnerProfileState.DEGRADED
    healed = _authority(config, journal, memory, head)
    assert healed.reconcile().display_name == "Bob"


def test_target_projection_failure_durably_compensates_and_restart_keeps_prior(
    stores, monkeypatch
):
    _root, config, journal, memory, head = stores
    authority = _seed_alice(config, journal, memory, head)
    real_write = authority._write_memory
    calls = {"count": 0}

    def fail_target_once(name):
        calls["count"] += 1
        if calls["count"] == 1 and name == "Bob":
            raise profile.OwnerProfileError("target memory failed") from OSError(
                "target root"
            )
        return real_write(name)

    monkeypatch.setattr(authority, "_write_memory", fail_target_once)
    with pytest.raises(profile.OwnerProfileTransactionError) as raised:
        authority.set_name("Bob")
    assert raised.value.decision is profile.JournalState.COMPENSATED
    assert head.value.sequence == 4
    assert _owner(config) == "Alice"
    assert _owner_memory(memory) == ["Alice"]
    assert _authority(config, journal, memory, head).reconcile().display_name == "Alice"


@pytest.mark.parametrize("mode", ["before", "after"])
def test_terminal_file_write_fault_is_resolved_from_durable_bytes(
    stores, monkeypatch, mode
):
    _root, config, journal, memory, head = stores
    authority = _seed_alice(config, journal, memory, head)
    real_write = authority.journal_backend._atomic_write

    def fault(payload, *, expected):
        terminal = payload["records"][-1]["decision_state"] == "COMMITTED"
        if terminal and mode == "before":
            raise OSError("terminal before root")
        real_write(payload, expected=expected)
        if terminal and mode == "after":
            raise OSError("terminal after root")

    monkeypatch.setattr(authority.journal_backend, "_atomic_write", fault)
    if mode == "before":
        with pytest.raises(profile.OwnerProfileTransactionError):
            authority.set_name("Bob")
        restarted = _authority(config, journal, memory, head)
        assert restarted.reconcile().display_name == "Alice"
    else:
        assert authority.set_name("Bob").display_name == "Bob"
        assert head.value.sequence == 4


def test_stale_bob_snapshot_cannot_replace_anchored_carol(stores):
    _root, config, journal, memory, head = stores
    authority = _seed_alice(config, journal, memory, head)
    authority.set_name("Bob")
    bob_snapshot = journal.read_bytes()
    authority.correct_name("Carol")
    assert _owner(config) == "Carol"
    journal.write_bytes(bob_snapshot)

    restarted = _authority(config, journal, memory, head)
    result = restarted.reconcile()
    assert result.state is profile.OwnerProfileState.DEGRADED
    assert result.reconciled is False
    assert _owner(config) == "Carol"
    assert _owner_memory(memory) == ["Carol"]
    assert head.value.sequence == 6


def test_preforget_snapshot_cannot_resurrect_forgotten_owner(stores):
    _root, config, journal, memory, head = stores
    authority = _seed_alice(config, journal, memory, head)
    authority.correct_name("Bob")
    preforget = journal.read_bytes()
    authority.forget_name()
    assert _owner(config) == ""
    assert _owner_memory(memory) == []
    journal.write_bytes(preforget)

    restarted = _authority(config, journal, memory, head)
    assert restarted.reconcile().state is profile.OwnerProfileState.DEGRADED
    assert _owner(config) == ""
    assert _owner_memory(memory) == []


@pytest.mark.parametrize(
    "failure", ["missing-anchor", "missing-journal", "future", "mac-mismatch"]
)
def test_missing_future_or_mismatched_anchor_journal_is_sticky_and_read_only(
    stores, failure
):
    _root, config, journal, memory, head = stores
    _seed_alice(config, journal, memory, head)
    before_config = config.read_bytes()
    before_memory = _owner_memory(memory)
    if failure == "missing-anchor":
        head.value = None
    elif failure == "missing-journal":
        journal.unlink()
    elif failure == "future":
        head.value = profile.ChainHead(1, PROFILE_ID, head.value.sequence + 1, "a" * 64)
    else:
        head.value = profile.ChainHead(1, PROFILE_ID, head.value.sequence, "b" * 64)
    restarted = _authority(config, journal, memory, head)
    first = restarted.reconcile()
    assert first.state is profile.OwnerProfileState.DEGRADED
    assert config.read_bytes() == before_config
    assert _owner_memory(memory) == before_memory
    assert restarted.reconcile().state is profile.OwnerProfileState.DEGRADED


def test_genesis_projection_drift_is_degraded_without_repair(stores):
    _root, config, journal, memory, head = stores
    authority = _bootstrap(config, journal, memory, head)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"owner_name": "Alice"}), encoding="utf-8")
    result = authority.reconcile()
    assert result.state is profile.OwnerProfileState.DEGRADED
    assert _owner_memory(memory) == []


def test_anchored_projection_drift_is_repaired_only_after_exact_match(stores):
    _root, config, journal, memory, head = stores
    authority = _seed_alice(config, journal, memory, head)
    authority._write_config("Mallory")
    authority._write_memory("Mallory")
    restarted = _authority(config, journal, memory, head)
    assert restarted.reconcile().display_name == "Alice"
    assert _owner(config) == "Alice"
    assert _owner_memory(memory) == ["Alice"]


def test_cross_profile_and_semantic_journal_injection_fail_closed(stores):
    _root, config, journal, memory, head = stores
    _seed_alice(config, journal, memory, head)
    other = _authority(config, journal, memory, head, profile_id="owner-other")
    assert other.reconcile().state is profile.OwnerProfileState.DEGRADED

    memory.remember(
        "forged",
        kind="semantic",
        source="memory-tool",
        citation="user:preferences/owner_profile_v6_journal",
        category="preferences",
        key="owner_profile_v6_journal",
    )
    injected = _authority(config, journal, memory, head)
    assert injected.reconcile().state is profile.OwnerProfileState.DEGRADED


def test_unavailable_anchor_and_invalid_key_fail_closed(stores):
    _root, config, journal, memory, head = stores
    _seed_alice(config, journal, memory, head)
    head.fail_load = True
    authority = _authority(config, journal, memory, head)
    assert authority.reconcile().state is profile.OwnerProfileState.DEGRADED
    for key in (b"", b"x" * 31, b"x" * 33, bytearray(b"x" * 32), "x" * 32):
        with pytest.raises(TypeError):
            _authority(config, journal, memory, head, key=key)


def test_journal_byte_cap_is_enforced_before_json_decode(stores):
    _root, config, journal, memory, head = stores
    _bootstrap(config, journal, memory, head)
    journal.write_bytes(b"{" + b" " * profile.MAX_JOURNAL_BYTES)
    authority = _authority(config, journal, memory, head)
    result = authority.reconcile()
    assert result.state is profile.OwnerProfileState.DEGRADED
    assert authority.last_failure.original_error_type == "JournalIntegrityError"


def test_concurrent_compare_and_set_has_one_winner():
    store = MemoryChainHeadStore()
    genesis = profile.genesis_head(PROFILE_ID)
    assert store.compare_and_set(PROFILE_ID, None, genesis)
    first = profile.ChainHead(1, PROFILE_ID, 2, "a" * 64)
    second = profile.ChainHead(1, PROFILE_ID, 2, "b" * 64)
    barrier = threading.Barrier(3)
    outcomes = []

    def contend(desired):
        barrier.wait()
        outcomes.append(store.compare_and_set(PROFILE_ID, genesis, desired))

    threads = [
        threading.Thread(target=contend, args=(item,)) for item in (first, second)
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=3)
    assert sorted(outcomes) == [False, True]
    assert store.value in {first, second}


def test_windows_credential_adapter_uses_fixed_namespace_and_atomic_readback(
    monkeypatch,
):
    storage = {}
    references = []

    class DummyMutex:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def get(reference):
        references.append(reference)
        return storage.get((reference.service, reference.account))

    def set_value(reference, value):
        references.append(reference)
        storage[(reference.service, reference.account)] = bytes(value)

    monkeypatch.setattr(profile.platform, "system", lambda: "Windows")
    monkeypatch.setattr(profile, "_WindowsNamedMutex", DummyMutex)
    monkeypatch.setattr(profile.native_vault, "windows_get", get)
    monkeypatch.setattr(profile.native_vault, "windows_set", set_value)
    adapter = profile.WindowsCredentialChainHeadStore()
    genesis = profile.genesis_head(PROFILE_ID)
    assert adapter.compare_and_set(PROFILE_ID, None, genesis)
    assert adapter.load(PROFILE_ID) == genesis
    with pytest.raises(profile.ChainHeadConflict):
        adapter.compare_and_set(
            PROFILE_ID, None, profile.ChainHead(1, PROFILE_ID, 2, "a" * 64)
        )
    assert all(
        reference.service == profile.WINDOWS_HEAD_SERVICE for reference in references
    )
    source = inspect.getsource(profile.WindowsCredentialChainHeadStore)
    assert "windows_get" in source and "windows_set" in source
    assert "Path(" not in source and "os.environ" not in source


def test_windows_adapter_rejects_malformed_unknown_and_cross_profile_payloads(
    monkeypatch,
):
    monkeypatch.setattr(profile.platform, "system", lambda: "Windows")
    adapter = profile.WindowsCredentialChainHeadStore()
    payloads = [
        b"{not-json",
        json.dumps(
            {
                "version": 1,
                "owner_profile_id": PROFILE_ID,
                "sequence": 0,
                "head_mac": profile.GENESIS_MAC,
                "unknown": True,
            }
        ).encode(),
        json.dumps(
            {
                "version": 1,
                "owner_profile_id": "owner-other",
                "sequence": 0,
                "head_mac": profile.GENESIS_MAC,
            }
        ).encode(),
    ]
    for payload in payloads:
        with pytest.raises(profile.ChainHeadUnavailable):
            adapter._decode(payload, PROFILE_ID)


@pytest.mark.parametrize(
    "desired",
    [
        profile.ChainHead(1, PROFILE_ID, 0, profile.GENESIS_MAC),
        profile.ChainHead(1, PROFILE_ID, 1, "a" * 64),
        profile.ChainHead(1, PROFILE_ID, 4, "a" * 64),
        profile.ChainHead(1, PROFILE_ID, 2, profile.GENESIS_MAC),
    ],
)
def test_anchor_transition_rejects_downgrade_odd_sequence_jump_and_same_mac(desired):
    genesis = profile.genesis_head(PROFILE_ID)
    with pytest.raises((profile.ChainHeadConflict, profile.ChainHeadUnavailable)):
        profile._validate_head(desired, PROFILE_ID)
        profile._validate_head_transition(genesis, desired, PROFILE_ID)


def test_default_off_no_live_wiring_restart_or_file_anchor_fallback():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/permission_broker.py",
    ):
        assert "owner_profile_v6" not in (root / relative).read_text(encoding="utf-8")
    source = inspect.getsource(profile)
    assert "subprocess" not in source
    assert "os.environ" not in source
    assert "compare_and_set" in source
    assert "MAX_JOURNAL_BYTES + 1" in source
    assert "print(" not in source
    assert "logging." not in source


def test_checkpoint_manifest_matches_candidate_bytes_and_platform_limits():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "docs/onyx/checkpoints/owner-profile-v6/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["isolated"] is True
    assert manifest["default_off"] is True
    assert manifest["live_wired"] is False
    assert manifest["host_anchor"]["file_fallback"] is False
    for item in manifest["files"]:
        assert (
            hashlib.sha256((root / item["path"]).read_bytes()).hexdigest()
            == item["sha256"]
        )
    limits = " ".join(manifest["limitations"])
    assert "not a TPM-backed irreversible hardware counter" in limits
    assert "macOS Keychain" in limits
    assert "Linux Secret Service" in limits
