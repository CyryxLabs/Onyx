"""Independent adversarial audit for the default-off M2b-a ledger anchor.

The suite deliberately uses only the private test factory and in-memory vaults.
It must never access the owner's native vault or fixed production journal.
"""

from __future__ import annotations

import copy
import ctypes
import hashlib
import hmac
import inspect
import json
import os
import pickle
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import ledger_anchor, native_vault


class InjectedCrash(RuntimeError):
    pass


class MemoryVault:
    """A test-only vault that makes read/write history observable."""

    def __init__(self, value: bytes | None = None):
        self.value = value
        self.reads = 0
        self.writes: list[bytes] = []
        self._lock = threading.Lock()

    def get_bytes(self) -> bytes | None:
        with self._lock:
            self.reads += 1
            return self.value

    def set_bytes(self, secret: bytes | bytearray) -> None:
        value = bytes(secret)
        with self._lock:
            self.value = value
            self.writes.append(value)

    def delete(self) -> bool:
        with self._lock:
            existed = self.value is not None
            self.value = None
            return existed


class MutablePort:
    def __init__(self, current: ledger_anchor.LedgerSnapshot):
        self.current = current

    def snapshot(self) -> ledger_anchor.LedgerSnapshot:
        return self.current


def make_snapshot(
    marker: str = "1",
    *,
    database_id: str = "audit-db",
    events: int = 0,
    schema: str = "a",
    counts: dict[str, int] | None = None,
) -> ledger_anchor.LedgerSnapshot:
    return ledger_anchor.LedgerSnapshot(
        database_id,
        schema * 64,
        marker * 64,
        events,
        counts if counts is not None else {"events": events},
    )


def frame_boundaries(raw: bytes) -> list[tuple[int, int, int, int]]:
    """Return (start, payload_start, mac_start, end) for complete frames."""

    result: list[tuple[int, int, int, int]] = []
    offset = 0
    header = struct.Struct(">8sI")
    while offset + header.size <= len(raw):
        start = offset
        _magic, payload_size = header.unpack_from(raw, offset)
        payload_start = offset + header.size
        mac_start = payload_start + payload_size
        end = mac_start + 32
        if end > len(raw):
            break
        result.append((start, payload_start, mac_start, end))
        offset = end
    return result


class LedgerAnchorAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = (
            Path(self.temporary.name) / "private" / "runtime" / "ledger_anchor.v1.journal"
        )
        self.initial = make_snapshot()
        self.port = MutablePort(self.initial)
        self.key_vault = MemoryVault()
        self.state_vault = MemoryVault()
        self.anchor, self.owner = ledger_anchor._open_for_testing(
            self.port,
            journal_path=self.path,
            key_vault=self.key_vault,
            state_vault=self.state_vault,
        )

    def _new_fixture(self):
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "private" / "runtime" / "anchor.journal"
        initial = make_snapshot()
        port = MutablePort(initial)
        key_vault = MemoryVault()
        state_vault = MemoryVault()
        anchor, owner = ledger_anchor._open_for_testing(
            port,
            journal_path=path,
            key_vault=key_vault,
            state_vault=state_vault,
        )
        return temporary, path, initial, port, key_vault, state_vault, anchor, owner

    @staticmethod
    def _crash_at(point: str):
        def crash(actual: str) -> None:
            if actual == point:
                raise InjectedCrash(actual)

        return crash

    def test_p0_disabled_open_does_not_resolve_path_or_touch_vault(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            ledger_anchor,
            "_ledger_anchor_journal_path",
            side_effect=AssertionError("disabled path resolution"),
        ), patch.object(
            ledger_anchor,
            "_PRODUCTION_OPEN",
            side_effect=AssertionError("disabled vault access"),
        ):
            with self.assertRaises(ledger_anchor.LedgerAnchorDisabled):
                ledger_anchor.open_default()

        self.assertFalse(self.path.exists())
        self.assertEqual(self.key_vault.reads, 0)
        self.assertEqual(self.state_vault.reads, 0)

    def test_p0_production_factory_has_no_path_key_or_backend_override(self):
        self.assertEqual(tuple(inspect.signature(ledger_anchor.open_default).parameters), ())
        source = inspect.getsource(ledger_anchor.open_default)
        for forbidden in (
            "ONYX_ANCHOR_PATH",
            "ONYX_ANCHOR_KEY",
            "ONYX_ANCHOR_BACKEND",
            "ONYX_DATA_DIR",
        ):
            self.assertNotIn(forbidden, source)

    def test_p1_configurable_anchor_constructor_is_not_a_production_export(self):
        """Production API must not expose the path/vault injection constructor."""

        self.assertNotIn("LedgerAnchor", ledger_anchor.__all__)
        self.assertTrue(hasattr(ledger_anchor, "_open_for_testing"))

    def test_open_default_uses_fixed_distinct_namespaces_despite_poisoned_env(self):
        poison = {
            ledger_anchor.LEDGER_ANCHOR_FLAG: "true",
            "ONYX_ANCHOR_PATH": str(Path(self.temporary.name) / "attacker"),
            "ONYX_ANCHOR_KEY": "attacker-key",
            "ONYX_ANCHOR_BACKEND": "plaintext",
            "ONYX_DATA_DIR": str(Path(self.temporary.name) / "override"),
        }
        with patch.dict(os.environ, poison, clear=True):
            source = inspect.getsource(ledger_anchor._NativeAnchorVaultFacade)
        self.assertIn("Onyx.DomainLedgerAnchorKey.v1", source)
        self.assertIn("Onyx.DomainLedgerAnchorHead.v1", source)
        self.assertNotIn("environ", source)

    def test_p1_open_default_does_not_mint_owner_for_an_arbitrary_port(self):
        """A structurally matching caller must not receive the owner authority."""

        with self.assertRaises(TypeError):
            ledger_anchor.open_default(self.port)

    def test_p1_default_factory_security_dependencies_are_not_late_bound(self):
        """Runtime monkeypatching must not redirect the production path or vault."""

        dependencies = inspect.getclosurevars(ledger_anchor.open_default).globals
        self.assertNotIn("_canonical_port", dependencies)
        self.assertNotIn("_NativeAnchorVaultFacade", dependencies)
        self.assertNotIn("_ledger_anchor_journal_path", dependencies)

    def test_anchor_namespace_never_calls_public_gemini_credential_api(self):
        source = inspect.getsource(ledger_anchor)
        self.assertNotIn("core.credentials", source)
        self.assertNotIn("GEMINI_API_KEY", source)
        self.assertNotIn("GOOGLE_API_KEY", source)

    def test_p1_owner_capability_is_not_copyable_or_serializable(self):
        for operation in (
            lambda: copy.copy(self.owner),
            lambda: copy.deepcopy(self.owner),
            lambda: pickle.dumps(self.owner),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises((TypeError, pickle.PicklingError)):
                    operation()

    def test_capability_registries_are_weak_and_recovery_revokes_tickets(self):
        self.assertIsInstance(
            ledger_anchor._ISSUED_OWNER_CAPABILITIES, weakref.WeakKeyDictionary
        )
        self.assertIsInstance(
            ledger_anchor._ISSUED_PREPARED_TICKETS, weakref.WeakKeyDictionary
        )
        self.assertIsInstance(
            native_vault._ISSUED_ANCHOR_CAPABILITIES, weakref.WeakKeyDictionary
        )
        self.anchor.bootstrap(self.owner)
        self.port.current = make_snapshot("2", events=1)
        ticket = self.anchor.prepare(self.owner)
        self.assertIn(ticket, ledger_anchor._ISSUED_PREPARED_TICKETS)
        self.port.current = self.initial
        self.anchor.recover(self.owner)
        self.assertNotIn(ticket, ledger_anchor._ISSUED_PREPARED_TICKETS)

    def test_p1_owner_capability_cannot_be_forged_from_visible_slots(self):
        forged = ledger_anchor.OwnerCapability(
            self.owner._instance_token, ledger_anchor._CAPABILITY_SEAL
        )
        self.anchor.bootstrap(self.owner)
        with self.assertRaises(ledger_anchor.LedgerAnchorContractError):
            self.anchor.verify(forged)

    def test_p1_public_anchor_object_does_not_expose_a_raw_key_vault(self):
        self.anchor.bootstrap(self.owner)
        with self.assertRaises(AttributeError):
            self.anchor._key_vault.get_bytes()
        self.assertFalse(hasattr(self.anchor, "_owner"))
        self.assertFalse(hasattr(ledger_anchor, "_native_anchor_vaults"))

    def test_p1_prepared_ticket_is_not_copyable_serializable_or_forgeable(self):
        self.anchor.bootstrap(self.owner)
        self.port.current = make_snapshot("2", events=1)
        ticket = self.anchor.prepare(self.owner)

        for operation in (
            lambda: copy.copy(ticket),
            lambda: copy.deepcopy(ticket),
            lambda: pickle.dumps(ticket),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises((TypeError, pickle.PicklingError)):
                    operation()

        forged = ledger_anchor.PreparedTicket(
            ticket._instance_token,
            ticket._sequence,
            ticket._record_hmac,
            ledger_anchor._TICKET_SEAL,
        )
        with self.assertRaises(ledger_anchor.LedgerAnchorContractError):
            self.anchor.finalize(self.owner, forged)

    def test_sealed_representations_do_not_disclose_tokens_or_hmacs(self):
        self.anchor.bootstrap(self.owner)
        self.port.current = make_snapshot("2", events=1)
        ticket = self.anchor.prepare(self.owner)
        self.assertNotIn(self.owner._instance_token.hex(), repr(self.owner))
        self.assertNotIn(ticket._record_hmac, repr(ticket))

    def test_bootstrap_partial_state_matrix_never_silently_regenerates_key(self):
        existing_key = b"k" * 32
        self.key_vault.value = existing_key
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.bootstrap(self.owner)
        self.assertEqual(self.key_vault.value, existing_key)
        self.assertEqual(self.key_vault.writes, [])

        fixture = self._new_fixture()
        temporary, _path, _initial, _port, key_vault, state_vault, anchor, owner = fixture
        self.addCleanup(temporary.cleanup)
        anchor.bootstrap(owner)
        saved_key = key_vault.value
        writes_before = list(key_vault.writes)
        state_vault.value = None
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            anchor.bootstrap(owner)
        self.assertEqual(key_vault.value, saved_key)
        self.assertEqual(key_vault.writes, writes_before)

        key_vault.value = None
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            anchor.bootstrap(owner)
        self.assertIsNone(key_vault.value)

    def test_bootstrap_pending_recovers_each_durable_partial_state(self):
        for point in (
            "after_bootstrap_pending",
            "after_key_saved",
            "after_journal_fsync",
        ):
            with self.subTest(point=point):
                fixture = self._new_fixture()
                temporary, _path, initial, _port, _key, state, anchor, owner = fixture
                try:
                    with patch.object(
                        anchor, "_fault", side_effect=self._crash_at(point)
                    ):
                        with self.assertRaises(InjectedCrash):
                            anchor.bootstrap(owner)
                    self.assertIn(b"AnchorBootstrapPending.v1", state.value)
                    recovered = anchor.recover(owner)
                    self.assertEqual(recovered.sequence, 0)
                    self.assertEqual(recovered.ledger_root, initial.ledger_root)
                    self.assertEqual(anchor.verify(owner), recovered)
                finally:
                    temporary.cleanup()

    def test_frame_header_payload_and_mac_single_byte_mutations_fail_closed(self):
        self.anchor.bootstrap(self.owner)
        original = self.path.read_bytes()
        start, payload_start, mac_start, _end = frame_boundaries(original)[0]
        mutation_offsets = {
            "magic": start,
            "length": start + 11,
            "payload": payload_start,
            "mac": mac_start,
        }
        for label, offset in mutation_offsets.items():
            with self.subTest(segment=label):
                tampered = bytearray(original)
                tampered[offset] ^= 1
                self.path.write_bytes(tampered)
                with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
                    self.anchor.verify(self.owner)
                self.path.write_bytes(original)

    def test_valid_hmac_cannot_smuggle_noncanonical_json(self):
        self.anchor.bootstrap(self.owner)
        raw = self.path.read_bytes()
        _start, payload_start, mac_start, _end = frame_boundaries(raw)[0]
        payload = raw[payload_start:mac_start]
        noncanonical = payload.replace(b'{"contract"', b'{ "contract"', 1)
        self.assertNotEqual(noncanonical, payload)
        length = struct.pack(">I", len(noncanonical))
        mac = hmac.new(
            self.key_vault.value,
            ledger_anchor._FRAME_DOMAIN + (b"\0" * 32) + length + noncanonical,
            hashlib.sha256,
        ).digest()
        self.path.write_bytes(
            ledger_anchor._FRAME_HEADER.pack(ledger_anchor._JOURNAL_MAGIC, len(noncanonical))
            + noncanonical
            + mac
        )
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify(self.owner)

    def test_valid_frame_hmac_does_not_bypass_record_hmac(self):
        self.anchor.bootstrap(self.owner)
        raw = self.path.read_bytes()
        _start, payload_start, mac_start, _end = frame_boundaries(raw)[0]
        value = json.loads(raw[payload_start:mac_start])
        value["state"]["committed"]["ledger_root"] = "f" * 64
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        length = struct.pack(">I", len(payload))
        frame_mac = hmac.new(
            self.key_vault.value,
            ledger_anchor._FRAME_DOMAIN + (b"\0" * 32) + length + payload,
            hashlib.sha256,
        ).digest()
        self.path.write_bytes(
            ledger_anchor._FRAME_HEADER.pack(ledger_anchor._JOURNAL_MAGIC, len(payload))
            + payload
            + frame_mac
        )
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify(self.owner)

    def test_p1_hmac_valid_frames_must_obey_state_transition_semantics(self):
        self.anchor.bootstrap(self.owner)
        original = self.path.read_bytes()
        key = self.key_vault.value
        for transition in (
            "bootstrap",
            "prepare",
            "finalize",
            "recover_finalize",
            "recover_rollback",
        ):
            with self.subTest(transition=transition):
                self.path.write_bytes(original)
                with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
                    descriptor = self.anchor._open_journal()
                    try:
                        journal = self.anchor._read_journal(descriptor, key)
                        state = self.anchor._load_state(key)
                        self.anchor._append_frame(
                            descriptor, key, journal.frames, transition, state
                        )
                    finally:
                        os.close(descriptor)
                    self.anchor.verify(self.owner)
        self.path.write_bytes(original)

    def test_truncation_to_an_older_valid_prefix_is_detected_by_vault_head(self):
        self.anchor.bootstrap(self.owner)
        self.port.current = make_snapshot("2", events=1)
        ticket = self.anchor.prepare(self.owner)
        self.anchor.finalize(self.owner, ticket)
        raw = self.path.read_bytes()
        frames = frame_boundaries(raw)
        self.assertEqual(len(frames), 3)
        self.path.write_bytes(raw[: frames[-2][3]])
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify(self.owner)
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.recover(self.owner)

    def test_replayed_frame_and_partial_bytes_in_the_middle_are_rejected(self):
        self.anchor.bootstrap(self.owner)
        bootstrap_raw = self.path.read_bytes()
        self.port.current = make_snapshot("2", events=1)
        self.anchor.prepare(self.owner)
        prepared_raw = self.path.read_bytes()
        boundary = frame_boundaries(prepared_raw)[0][3]

        self.path.write_bytes(prepared_raw + bootstrap_raw)
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.recover(self.owner)

        self.path.write_bytes(prepared_raw[:boundary] + b"ONX" + prepared_raw[boundary:])
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.recover(self.owner)

    def test_only_recover_repairs_a_trailing_partial_frame(self):
        stable = self.anchor.bootstrap(self.owner)
        stable_size = self.path.stat().st_size
        with self.path.open("ab") as handle:
            handle.write(ledger_anchor._JOURNAL_MAGIC + b"\0\0\0\x20" + b"partial")
            handle.flush()
            os.fsync(handle.fileno())
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify(self.owner)
        self.assertEqual(self.anchor.recover(self.owner), stable)
        self.assertEqual(self.path.stat().st_size, stable_size)

    def test_prepare_fault_seams_recover_to_exact_durable_database_state(self):
        cases = [
            ("before_journal_append", False),
            ("after_journal_fsync", False),
            ("before_vault_write", False),
            ("after_vault_write", False),
            ("after_journal_fsync", True),
            ("before_vault_write", True),
            ("after_vault_write", True),
        ]
        for point, database_committed in cases:
            with self.subTest(point=point, database_committed=database_committed):
                fixture = self._new_fixture()
                temporary, path, initial, port, _key, _state, anchor, owner = fixture
                try:
                    anchor.bootstrap(owner)
                    candidate = make_snapshot("2", events=1)
                    port.current = candidate
                    with patch.object(anchor, "_fault", side_effect=self._crash_at(point)):
                        with self.assertRaises(InjectedCrash):
                            anchor.prepare(owner)
                    port.current = candidate if database_committed else initial
                    recovered = anchor.recover(owner)
                    expected = candidate if database_committed else initial
                    self.assertEqual(recovered.ledger_root, expected.ledger_root)
                    size = path.stat().st_size
                    self.assertEqual(anchor.recover(owner), recovered)
                    self.assertEqual(path.stat().st_size, size)
                finally:
                    temporary.cleanup()

    def test_finalize_fault_seams_recover_idempotently(self):
        for point in (
            "before_journal_append",
            "after_journal_fsync",
            "before_finalize_vault",
            "before_vault_write",
            "after_vault_write",
        ):
            with self.subTest(point=point):
                fixture = self._new_fixture()
                temporary, path, _initial, port, _key, _state, anchor, owner = fixture
                try:
                    anchor.bootstrap(owner)
                    candidate = make_snapshot("2", events=1)
                    port.current = candidate
                    ticket = anchor.prepare(owner)
                    with patch.object(anchor, "_fault", side_effect=self._crash_at(point)):
                        with self.assertRaises(InjectedCrash):
                            anchor.finalize(owner, ticket)
                    recovered = anchor.recover(owner)
                    self.assertEqual(recovered.ledger_root, candidate.ledger_root)
                    size = path.stat().st_size
                    self.assertEqual(anchor.recover(owner), recovered)
                    self.assertEqual(path.stat().st_size, size)
                finally:
                    temporary.cleanup()

    def test_vault_ahead_of_journal_is_not_accepted_as_a_recovery_shortcut(self):
        self.anchor.bootstrap(self.owner)
        bootstrap_end = frame_boundaries(self.path.read_bytes())[0][3]
        self.port.current = make_snapshot("2", events=1)
        ticket = self.anchor.prepare(self.owner)
        self.anchor.finalize(self.owner, ticket)
        self.path.write_bytes(self.path.read_bytes()[:bootstrap_end])
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.recover(self.owner)

    def test_thread_contention_allows_one_linear_prepare(self):
        self.anchor.bootstrap(self.owner)
        self.port.current = make_snapshot("2", events=1)
        pairs = [
            ledger_anchor._open_for_testing(
                self.port,
                journal_path=self.path,
                key_vault=self.key_vault,
                state_vault=self.state_vault,
            )
            for _ in range(8)
        ]

        def attempt(pair):
            anchor, owner = pair
            try:
                return anchor.prepare(owner)
            except ledger_anchor.LedgerAnchorConflict as exc:
                return exc

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, pairs))
        tickets = [item for item in outcomes if isinstance(item, ledger_anchor.PreparedTicket)]
        conflicts = [item for item in outcomes if isinstance(item, ledger_anchor.LedgerAnchorConflict)]
        self.assertEqual(len(tickets), 1)
        self.assertEqual(len(conflicts), 7)

    def test_cross_process_lock_serializes_same_journal_path(self):
        ready = Path(self.temporary.name) / "ready"
        code = (
            "import sys,time; from pathlib import Path; "
            "from core.ledger_anchor import _AnchorFileLock; "
            "path=Path(sys.argv[1]); ready=Path(sys.argv[2]); "
            "lock=_AnchorFileLock(path); lock.__enter__(); "
            "ready.write_text('ready', encoding='utf-8'); time.sleep(0.6); lock.__exit__()"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code, os.fspath(self.path), os.fspath(ready)],
            cwd=Path(__file__).parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not ready.exists():
            stdout, stderr = process.communicate(timeout=5)
            self.fail(f"lock holder failed: {stdout} {stderr}")

        started = time.monotonic()
        with ledger_anchor._AnchorFileLock(self.path):
            elapsed = time.monotonic() - started
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, (stdout, stderr))
        self.assertGreaterEqual(elapsed, 0.25)

    def test_p1_anchor_lock_has_a_finite_posix_wait_deadline(self):
        source = inspect.getsource(ledger_anchor._AnchorFileLock.__enter__)
        self.assertIn("LOCK_NB", source)
        self.assertIn("monotonic", source)

    def test_p1_journal_read_is_bounded_before_allocation(self):
        self.assertTrue(hasattr(ledger_anchor, "_MAX_JOURNAL_BYTES"))
        self.anchor.bootstrap(self.owner)
        requests: list[int] = []
        original = ledger_anchor.LedgerAnchor._read_exact

        def tracked(descriptor: int, length: int) -> bytes:
            requests.append(length)
            return original(descriptor, length)

        with patch.object(ledger_anchor.LedgerAnchor, "_read_exact", side_effect=tracked):
            self.anchor.verify(self.owner)
        self.assertTrue(requests)
        self.assertLessEqual(
            max(requests), ledger_anchor._MAX_FRAME_PAYLOAD + ledger_anchor._MAC_BYTES
        )
        source = inspect.getsource(ledger_anchor.LedgerAnchor._read_journal)
        self.assertIn("_MAX_JOURNAL_BYTES", source)
        self.assertNotIn("read_bytes", source)

    def test_journal_scan_keeps_only_authenticated_tail(self):
        self.anchor.bootstrap(self.owner)
        self.port.current = make_snapshot("2", events=1)
        ticket = self.anchor.prepare(self.owner)
        self.anchor.finalize(self.owner, ticket)
        descriptor = self.anchor._open_journal()
        try:
            journal = self.anchor._read_journal(descriptor, self.key_vault.value)
        finally:
            os.close(descriptor)
        # V2 authenticates the sealed prefix in the vault and retains one
        # synthetic tail frame; only a crash suffix is streamed beyond it.
        self.assertEqual(len(journal.frames), 1)
        self.assertEqual([frame.frame_sequence for frame in journal.frames], [2])
        observed: list[tuple[int, str]] = []
        original = self.anchor._validate_transition

        def track(previous, transition, state):
            observed.append((state.committed.sequence, transition))
            return original(previous, transition, state)

        with patch.object(self.anchor, "_validate_transition", side_effect=track):
            self.anchor.verify_history(self.owner)
        self.assertEqual(
            observed,
            [(0, "bootstrap"), (0, "prepare"), (1, "finalize")],
        )

    def test_fixed_journal_path_ignores_onyx_data_and_anchor_override_env(self):
        poison = {
            "ONYX_DATA_DIR": str(Path(self.temporary.name) / "data-override"),
            "ONYX_ANCHOR_PATH": str(Path(self.temporary.name) / "anchor-override"),
            "ONYX_ANCHOR_BACKEND": "plaintext",
        }
        with patch.dict(os.environ, poison, clear=False):
            path = ledger_anchor._ledger_anchor_journal_path()
        self.assertEqual(path.name, ledger_anchor.JOURNAL_FILENAME)
        self.assertNotIn("data-override", os.fspath(path))
        self.assertNotIn("anchor-override", os.fspath(path))

    def test_symlink_journal_is_rejected_without_touching_target(self):
        target = Path(self.temporary.name) / "target"
        target.write_bytes(b"sentinel")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(ledger_anchor.LedgerAnchorIOError):
            self.anchor.bootstrap(self.owner)
        self.assertEqual(target.read_bytes(), b"sentinel")

    def test_p1_hard_link_journal_is_rejected_without_touching_target(self):
        target = Path(self.temporary.name) / "hard-link-target"
        target.write_bytes(b"")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(target, self.path)
        except OSError as exc:
            self.skipTest(f"hard-link creation unavailable: {exc}")
        with self.assertRaises(ledger_anchor.LedgerAnchorIOError):
            self.anchor.bootstrap(self.owner)
        self.assertEqual(target.read_bytes(), b"")

    def test_posix_acl_is_owner_only_after_every_transition(self):
        if os.name == "nt":
            self.skipTest("POSIX permission assertion")
        self.anchor.bootstrap(self.owner)
        self.port.current = make_snapshot("2", events=1)
        ticket = self.anchor.prepare(self.owner)
        self.anchor.finalize(self.owner, ticket)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)

    def test_p1_linux_backend_executable_cannot_be_selected_through_path(self):
        calls: list[tuple[list[str], str | None]] = []

        def runner(argv, *, secret_input=None):
            calls.append((argv, secret_input))
            return subprocess.CompletedProcess(argv, 0, "", "")

        reference = native_vault.SecretReference("Onyx.Anchor.Audit", "owner", "audit")
        tool = os.fspath(Path(self.temporary.name) / "secret-tool")
        with patch.object(native_vault, "_validate_linux_tool", return_value=tool):
            native_vault.linux_set(
                reference, b"s" * 32, runner=runner, tool_path=tool
            )
        argv, secret_input = calls[0]
        self.assertTrue(Path(argv[0]).is_absolute(), argv)
        self.assertNotIn(b"s" * 32, [item.encode() for item in argv])
        self.assertIsNotNone(secret_input)
        self.assertNotIn("shutil.which", inspect.getsource(native_vault._linux_secret_tool))
        with self.assertRaises(native_vault.NativeVaultError):
            native_vault.linux_set(
                reference,
                b"s" * 32,
                runner=runner,
                tool_path=os.fspath(Path(self.temporary.name) / "untrusted"),
            )

    def _assert_linux_helper_metadata_denied(
        self, info: SimpleNamespace, *, symlink: bool = False
    ) -> None:
        reference = native_vault.SecretReference("Onyx.Anchor.Audit", "owner", "audit")
        tool = os.fspath(Path(self.temporary.name) / "secret-tool")
        runner = Mock(side_effect=AssertionError("runner must not be called"))
        with patch.object(Path, "lstat", return_value=info), patch.object(
            Path, "is_symlink", return_value=symlink
        ), self.assertRaises(native_vault.NativeVaultError):
            native_vault.linux_set(
                reference, b"s" * 32, runner=runner, tool_path=tool
            )
        runner.assert_not_called()

    def test_linux_helper_symlink_is_denied_before_runner(self):
        self._assert_linux_helper_metadata_denied(
            SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_nlink=1, st_uid=0),
            symlink=True,
        )

    def test_linux_helper_hardlink_is_denied_before_runner(self):
        self._assert_linux_helper_metadata_denied(
            SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_nlink=2, st_uid=0)
        )

    def test_linux_helper_non_root_owner_is_denied_before_runner(self):
        self._assert_linux_helper_metadata_denied(
            SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_nlink=1, st_uid=1000)
        )

    def test_linux_helper_group_writable_is_denied_before_runner(self):
        self._assert_linux_helper_metadata_denied(
            SimpleNamespace(st_mode=stat.S_IFREG | 0o775, st_nlink=1, st_uid=0)
        )

    def test_linux_helper_world_writable_is_denied_before_runner(self):
        self._assert_linux_helper_metadata_denied(
            SimpleNamespace(st_mode=stat.S_IFREG | 0o757, st_nlink=1, st_uid=0)
        )

    def test_linux_helper_root_owned_regular_metadata_reaches_runner(self):
        calls: list[list[str]] = []

        def runner(argv, *, secret_input=None):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        reference = native_vault.SecretReference("Onyx.Anchor.Audit", "owner", "audit")
        tool = os.fspath(Path(self.temporary.name) / "secret-tool")
        info = SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_nlink=1, st_uid=0)
        with patch.object(Path, "lstat", return_value=info), patch.object(
            Path, "is_symlink", return_value=False
        ):
            native_vault.linux_set(
                reference, b"s" * 32, runner=runner, tool_path=tool
            )
        self.assertEqual(calls[0][0], tool)

    def test_p1_windows_vault_target_distinguishes_accounts(self):
        class FakeFunction:
            def __init__(self, result=0):
                self.result = result
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                self.calls.append(args)
                return self.result

        class FakeApi:
            def __init__(self):
                self.CredReadW = FakeFunction(0)
                self.CredFree = FakeFunction(None)

        api = FakeApi()
        first = native_vault.SecretReference("Onyx.Shared.Service", "account-a", "a")
        second = native_vault.SecretReference("Onyx.Shared.Service", "account-b", "b")
        with patch.object(ctypes, "get_last_error", return_value=1168, create=True):
            self.assertIsNone(native_vault.windows_get(first, api_factory=lambda: api))
            self.assertIsNone(native_vault.windows_get(second, api_factory=lambda: api))
        targets = [call[0] for call in api.CredReadW.calls]
        self.assertNotEqual(targets[0], targets[1])

    def test_native_backend_runner_never_uses_shell_and_bounds_execution(self):
        completed = subprocess.CompletedProcess(["vault"], 0, "", "")
        with patch.object(subprocess, "run", return_value=completed) as run:
            result = native_vault._run_backend(["/usr/bin/secret-tool", "lookup"])
        self.assertIs(result, completed)
        kwargs = run.call_args.kwargs
        self.assertIs(kwargs["shell"], False)
        self.assertTrue(kwargs["capture_output"])
        self.assertGreater(kwargs["timeout"], 0)
        self.assertLessEqual(kwargs["timeout"], 20)

    def test_startup_surfaces_do_not_import_or_enable_ledger_anchor(self):
        root = Path(__file__).parents[1]
        for relative in ("main.py", "ui.py", "dashboard/server.py"):
            source = (root / relative).read_text(encoding="utf-8")
            self.assertNotIn("ledger_anchor", source, relative)
            self.assertNotIn(ledger_anchor.LEDGER_ANCHOR_FLAG, source, relative)


if __name__ == "__main__":
    unittest.main()
