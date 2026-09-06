import copy
import hashlib
import hmac
import inspect
import json
import os
import pickle
import stat
import struct
import subprocess
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import ledger_anchor, native_vault


class InjectedCrash(RuntimeError):
    pass


class InjectedCancellation(BaseException):
    pass


class MemoryVault:
    def __init__(self, value=None):
        self.value = value
        self.fail_get = False
        self.fail_set = False
        self.corrupt_set = False
        self.set_count = 0

    def get_bytes(self):
        if self.fail_get:
            raise native_vault.NativeVaultError("unavailable")
        return self.value

    def set_bytes(self, secret):
        if self.fail_set:
            raise native_vault.NativeVaultError("unavailable")
        self.set_count += 1
        value = bytes(secret)
        self.value = value[:-1] + bytes([value[-1] ^ 1]) if self.corrupt_set else value

    def delete(self):
        existed = self.value is not None
        self.value = None
        return existed


class FakePort:
    def __init__(self, snapshot):
        self.current = snapshot

    def snapshot(self):
        return self.current


def snapshot(root="1", *, database_id="db-test", events=0, counts=None):
    return ledger_anchor.LedgerSnapshot(
        database_id,
        "a" * 64,
        root * 64,
        events,
        counts or {"events": events},
    )


class LedgerAnchorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "runtime" / "ledger_anchor.v1.journal"
        self.key_vault = MemoryVault()
        self.state_vault = MemoryVault()
        self.initial = snapshot()
        self.port = FakePort(self.initial)
        self.anchor, self.owner = ledger_anchor._open_for_testing(
            self.port,
            journal_path=self.path,
            key_vault=self.key_vault,
            state_vault=self.state_vault,
        )

    def bootstrap(self):
        return self.anchor.bootstrap(self.owner)

    def test_default_flag_is_strict_false_and_open_default_has_no_overrides(self):
        self.assertFalse(ledger_anchor.ledger_anchor_enabled({}))
        self.assertFalse(
            ledger_anchor.ledger_anchor_enabled(
                {ledger_anchor.LEDGER_ANCHOR_FLAG: "yes"}
            )
        )
        self.assertTrue(
            ledger_anchor.ledger_anchor_enabled(
                {ledger_anchor.LEDGER_ANCHOR_FLAG: "true"}
            )
        )
        self.assertEqual(list(inspect.signature(ledger_anchor.open_default).parameters), [])
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ledger_anchor.LedgerAnchorDisabled):
                ledger_anchor.open_default()
        with patch.dict(
            os.environ, {ledger_anchor.LEDGER_ANCHOR_FLAG: "true"}, clear=True
        ):
            with self.assertRaises(ledger_anchor.LedgerAnchorUnavailable):
                ledger_anchor.open_default()
        self.assertFalse(self.path.exists())

    def test_startup_does_not_import_anchor(self):
        source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("ledger_anchor", source)
        self.assertNotIn("native_vault", source)

    def test_explicit_bootstrap_and_verify(self):
        status = self.bootstrap()
        self.assertEqual(status.sequence, 0)
        self.assertEqual(status.ledger_root, self.initial.ledger_root)
        self.assertFalse(status.prepared)
        self.assertEqual(len(self.key_vault.value), 32)
        self.assertIsNotNone(self.state_vault.value)
        self.assertTrue(self.path.is_file())
        self.assertNotIn(self.key_vault.value, self.path.read_bytes())
        self.assertEqual(self.anchor.verify(self.owner), status)

    def test_process_interrupts_propagate_from_port_and_all_vault_boundaries(self):
        def fresh(label):
            key_vault = MemoryVault()
            state_vault = MemoryVault()
            port = FakePort(snapshot())
            anchor, owner = ledger_anchor._open_for_testing(
                port,
                journal_path=self.path.with_name(f"{label}.journal"),
                key_vault=key_vault,
                state_vault=state_vault,
            )
            return anchor, owner, port, key_vault, state_vault

        for exception_type in (KeyboardInterrupt, SystemExit):
            for boundary in (
                "port_snapshot",
                "key_read",
                "head_read",
                "key_write",
                "head_write",
            ):
                with self.subTest(
                    exception_type=exception_type.__name__, boundary=boundary
                ):
                    anchor, owner, port, key_vault, state_vault = fresh(
                        f"{exception_type.__name__}-{boundary}"
                    )

                    def interrupt(*_args, **_kwargs):
                        raise exception_type()

                    if boundary in {"key_read", "head_read"}:
                        anchor.bootstrap(owner)
                    target = {
                        "port_snapshot": port,
                        "key_read": key_vault,
                        "head_read": state_vault,
                        "key_write": key_vault,
                        "head_write": state_vault,
                    }[boundary]
                    attribute = {
                        "port_snapshot": "snapshot",
                        "key_read": "get_bytes",
                        "head_read": "get_bytes",
                        "key_write": "set_bytes",
                        "head_write": "set_bytes",
                    }[boundary]
                    operation = (
                        (lambda: anchor.verify(owner))
                        if boundary in {"key_read", "head_read"}
                        else (lambda: anchor.bootstrap(owner))
                    )
                    with patch.object(target, attribute, side_effect=interrupt):
                        with self.assertRaises(exception_type):
                            operation()

    def test_owner_capability_and_ticket_are_sealed_and_instance_bound(self):
        with self.assertRaises(TypeError):
            ledger_anchor.OwnerCapability(b"x" * 32, object())
        with self.assertRaises(TypeError):
            ledger_anchor.PreparedTicket(b"x" * 32, 1, "0" * 64, object())
        self.bootstrap()
        other, other_owner = ledger_anchor._open_for_testing(
            self.port,
            journal_path=self.path,
            key_vault=self.key_vault,
            state_vault=self.state_vault,
        )
        with self.assertRaises(ledger_anchor.LedgerAnchorContractError):
            other.verify(self.owner)
        self.assertEqual(other.verify(other_owner).sequence, 0)
        for operation in (
            lambda: copy.copy(self.owner),
            lambda: copy.deepcopy(self.owner),
            lambda: pickle.dumps(self.owner),
        ):
            with self.assertRaises(TypeError):
                operation()
        forged = object.__new__(ledger_anchor.OwnerCapability)
        forged._instance_token = self.owner._instance_token
        forged._seal = self.owner._seal
        with self.assertRaises(ledger_anchor.LedgerAnchorContractError):
            self.anchor.verify(forged)

    def test_prepare_finalize_and_ticket_single_use(self):
        self.bootstrap()
        candidate = snapshot("2", events=1)
        self.port.current = candidate
        ticket = self.anchor.prepare(self.owner)
        self.assertEqual(ticket.sequence, 1)
        with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
            self.anchor.verify(self.owner)
        status = self.anchor.finalize(self.owner, ticket)
        self.assertEqual(status.sequence, 1)
        self.assertEqual(status.ledger_root, candidate.ledger_root)
        self.assertFalse(status.prepared)
        with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
            self.anchor.finalize(self.owner, ticket)
        for operation in (
            lambda: copy.copy(ticket),
            lambda: copy.deepcopy(ticket),
            lambda: pickle.dumps(ticket),
        ):
            with self.assertRaises(TypeError):
                operation()

    def test_writer_session_holds_one_lock_for_verify_prepare_and_finalize(self):
        self.bootstrap()
        enters = 0
        original_enter = ledger_anchor._AnchorFileLock.__enter__

        def counted_enter(lock):
            nonlocal enters
            enters += 1
            return original_enter(lock)

        with patch.object(ledger_anchor._AnchorFileLock, "__enter__", counted_enter):
            with self.anchor.writer_session(self.owner, timeout=1.0) as session:
                baseline = session.verify_baseline()
                self.assertEqual(baseline.sequence, 0)
                self.assertEqual(session.verify_baseline(), baseline)
                self.port.current = snapshot("2", events=1)
                ticket = session.prepare_candidate()
                with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
                    session.verify_baseline()
                finalized = session.finalize_prepared(ticket)
                self.assertEqual(finalized.sequence, 1)
                self.assertFalse(finalized.prepared)
                with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
                    session.verify_baseline()
                self.assertEqual(session.verify_committed(), finalized)
        self.assertEqual(enters, 1)

    def test_writer_session_is_thread_bound_single_use_and_rejects_nesting(self):
        self.bootstrap()
        session = self.anchor.writer_session(self.owner)
        errors = []
        with session:
            with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
                self.anchor.writer_session(self.owner).__enter__()
            with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
                self.anchor.verify(self.owner)

            worker = threading.Thread(
                target=lambda: self._capture_session_error(session, errors)
            )
            worker.start()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ledger_anchor.LedgerAnchorContractError)
            session.verify_baseline()

        with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
            session.verify_baseline()
        with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
            session.__enter__()

    @staticmethod
    def _capture_session_error(session, errors):
        try:
            session.verify_baseline()
        except BaseException as error:
            errors.append(error)

    def test_writer_session_recovers_prepared_state_on_base_exception(self):
        self.bootstrap()
        session = self.anchor.writer_session(self.owner)
        with self.assertRaises(InjectedCancellation):
            with session as active:
                active.verify_baseline()
                self.port.current = snapshot("2", events=1)
                active.prepare_candidate()
                self.port.current = self.initial
                raise InjectedCancellation("cancel")

        status = self.anchor.verify(self.owner)
        self.assertEqual(status.sequence, 0)
        self.assertFalse(status.prepared)

    def test_writer_session_recovery_failure_stays_prepared_until_later_recovery(self):
        self.bootstrap()
        candidate = snapshot("2", events=1)
        session = self.anchor.writer_session(self.owner)
        with patch.object(
            self.anchor,
            "_recover_locked_operation",
            side_effect=InjectedCrash("recovery unavailable"),
        ):
            with self.assertRaises(InjectedCancellation):
                with session as active:
                    active.verify_baseline()
                    self.port.current = candidate
                    active.prepare_candidate()
                    raise InjectedCancellation("cancel")

        with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
            self.anchor.verify(self.owner)
        recovered = self.anchor.recover(self.owner)
        self.assertEqual(recovered.sequence, 1)
        self.assertEqual(recovered.ledger_root, candidate.ledger_root)
        self.assertFalse(recovered.prepared)

    def test_writer_session_timeout_is_explicitly_bounded(self):
        for value in (True, 0, -1, 31, float("inf"), "1"):
            with self.assertRaises(ledger_anchor.LedgerAnchorContractError):
                self.anchor.writer_session(self.owner, timeout=value)

    def test_prepare_rejects_no_change_and_database_identity_change(self):
        self.bootstrap()
        with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
            self.anchor.prepare(self.owner)
        self.port.current = snapshot("2", database_id="another-db")
        with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
            self.anchor.prepare(self.owner)

    def test_only_one_prepare_can_be_outstanding(self):
        self.bootstrap()
        self.port.current = snapshot("2", events=1)
        self.anchor.prepare(self.owner)
        self.port.current = snapshot("3", events=2)
        with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
            self.anchor.prepare(self.owner)

    def test_recover_rolls_back_prepared_when_database_remains_old(self):
        initial = self.bootstrap()
        self.port.current = snapshot("2", events=1)
        self.anchor.prepare(self.owner)
        self.port.current = self.initial
        recovered = self.anchor.recover(self.owner)
        self.assertEqual(recovered, initial)
        self.assertEqual(self.anchor.verify(self.owner), initial)

    def test_recover_promotes_prepared_when_database_is_candidate(self):
        self.bootstrap()
        candidate = snapshot("2", events=1)
        self.port.current = candidate
        self.anchor.prepare(self.owner)
        recovered = self.anchor.recover(self.owner)
        self.assertEqual(recovered.sequence, 1)
        self.assertEqual(recovered.ledger_root, candidate.ledger_root)
        self.assertEqual(self.anchor.verify(self.owner), recovered)

    def test_crash_after_prepare_journal_before_vault_recovers(self):
        self.bootstrap()
        candidate = snapshot("2", events=1)
        self.port.current = candidate

        def crash(point):
            if point == "after_journal_fsync":
                raise InjectedCrash(point)

        with patch.object(self.anchor, "_fault", side_effect=crash):
            with self.assertRaises(InjectedCrash):
                self.anchor.prepare(self.owner)
        recovered = self.anchor.recover(self.owner)
        self.assertEqual(recovered.sequence, 1)
        self.assertEqual(recovered.ledger_root, candidate.ledger_root)

    def test_crash_after_prepare_vault_write_recovers(self):
        self.bootstrap()
        candidate = snapshot("2", events=1)
        self.port.current = candidate

        def crash(point):
            if point == "after_vault_write":
                raise InjectedCrash(point)

        with patch.object(self.anchor, "_fault", side_effect=crash):
            with self.assertRaises(InjectedCrash):
                self.anchor.prepare(self.owner)
        recovered = self.anchor.recover(self.owner)
        self.assertEqual(recovered.sequence, 1)

    def test_crash_after_finalize_journal_before_vault_recovers(self):
        self.bootstrap()
        candidate = snapshot("2", events=1)
        self.port.current = candidate
        ticket = self.anchor.prepare(self.owner)

        def crash(point):
            if point == "after_journal_fsync":
                raise InjectedCrash(point)

        with patch.object(self.anchor, "_fault", side_effect=crash):
            with self.assertRaises(InjectedCrash):
                self.anchor.finalize(self.owner, ticket)
        recovered = self.anchor.recover(self.owner)
        self.assertEqual(recovered.sequence, 1)
        self.assertEqual(recovered.ledger_root, candidate.ledger_root)

    def test_incomplete_bootstrap_after_journal_recovers_from_pending(self):
        def crash(point):
            if point == "after_journal_fsync":
                raise InjectedCrash(point)

        with patch.object(self.anchor, "_fault", side_effect=crash):
            with self.assertRaises(InjectedCrash):
                self.anchor.bootstrap(self.owner)
        self.assertIsNotNone(self.key_vault.value)
        self.assertIn(b"AnchorBootstrapPending.v1", self.state_vault.value)
        recovered = self.anchor.recover(self.owner)
        self.assertEqual(recovered.sequence, 0)
        self.assertEqual(recovered.ledger_root, self.initial.ledger_root)
        self.assertEqual(self.anchor.verify(self.owner), recovered)

    def test_orphaned_key_fails_without_regeneration(self):
        existing = b"k" * 32
        self.key_vault.value = existing
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.bootstrap()
        self.assertEqual(self.key_vault.value, existing)
        self.assertEqual(self.key_vault.set_count, 0)

    def test_missing_key_after_bootstrap_fails_without_regeneration(self):
        self.bootstrap()
        self.key_vault.value = None
        before = self.key_vault.set_count
        with self.assertRaises(ledger_anchor.LedgerAnchorVaultError):
            self.anchor.verify(self.owner)
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.bootstrap(self.owner)
        self.assertEqual(self.key_vault.set_count, before)
        self.assertIsNone(self.key_vault.value)

    def test_missing_head_or_journal_fails_closed(self):
        self.bootstrap()
        saved_head = self.state_vault.value
        self.state_vault.value = None
        with self.assertRaises(ledger_anchor.LedgerAnchorVaultError):
            self.anchor.verify(self.owner)
        self.state_vault.value = saved_head
        self.path.unlink()
        with self.assertRaises(ledger_anchor.LedgerAnchorIOError):
            self.anchor.verify(self.owner)
        self.assertFalse(self.path.exists())

    def test_wrong_key_and_malformed_vault_state_fail_closed(self):
        self.bootstrap()
        original_key = self.key_vault.value
        self.key_vault.value = b"z" * 32
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify(self.owner)
        self.key_vault.value = original_key
        self.state_vault.value = b'{"not":"canonical", "x":1}'
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify(self.owner)

    def test_database_tamper_fails_closed(self):
        self.bootstrap()
        self.port.current = snapshot("9", events=99)
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify(self.owner)
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.recover(self.owner)

    def test_journal_byte_tamper_fails_hmac(self):
        self.bootstrap()
        raw = bytearray(self.path.read_bytes())
        raw[20] ^= 1
        self.path.write_bytes(raw)
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify(self.owner)

    def test_hmac_valid_but_semantically_invalid_transition_fails(self):
        self.bootstrap()
        self.port.current = snapshot("2", events=1)
        self.anchor.prepare(self.owner)
        raw = self.path.read_bytes()
        header_size = ledger_anchor._FRAME_HEADER.size
        _, first_length = ledger_anchor._FRAME_HEADER.unpack(raw[:header_size])
        first_end = header_size + first_length + 32
        first = raw[:first_end]
        _, second_length = ledger_anchor._FRAME_HEADER.unpack(
            raw[first_end : first_end + header_size]
        )
        payload_start = first_end + header_size
        payload = json.loads(raw[payload_start : payload_start + second_length])
        payload["transition"] = "finalize"
        encoded = ledger_anchor._canonical(payload)
        previous_mac = first[-32:]
        length = struct.pack(">I", len(encoded))
        frame_mac = hmac.new(
            self.key_vault.value,
            ledger_anchor._FRAME_DOMAIN + previous_mac + length + encoded,
            hashlib.sha256,
        ).digest()
        self.path.write_bytes(
            first
            + ledger_anchor._FRAME_HEADER.pack(ledger_anchor._JOURNAL_MAGIC, len(encoded))
            + encoded
            + frame_mac
        )
        with self.assertRaisesRegex(
            ledger_anchor.LedgerAnchorIntegrityError, "transition"
        ):
            self.anchor.recover(self.owner)

    def test_truncated_committed_frame_cannot_be_recovered(self):
        self.bootstrap()
        self.port.current = snapshot("2", events=1)
        ticket = self.anchor.prepare(self.owner)
        self.anchor.finalize(self.owner, ticket)
        raw = self.path.read_bytes()
        self.path.write_bytes(raw[:-10])
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.recover(self.owner)

    def test_one_trailing_partial_frame_is_repaired_only_by_recover(self):
        status = self.bootstrap()
        original = self.path.stat().st_size
        with self.path.open("ab") as handle:
            handle.write(b"ONX")
            handle.flush()
            os.fsync(handle.fileno())
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify(self.owner)
        self.assertEqual(self.anchor.recover(self.owner), status)
        self.assertEqual(self.path.stat().st_size, original)

    def test_partial_first_bootstrap_frame_fails_closed(self):
        self.key_vault.value = b"k" * 32
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"ONX")
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.bootstrap()
        self.assertEqual(self.path.stat().st_size, 3)

    def test_vault_readback_divergence_fails(self):
        self.state_vault.corrupt_set = True
        with self.assertRaises(ledger_anchor.LedgerAnchorVaultError):
            self.bootstrap()
        self.assertIsNone(self.key_vault.value)

    def test_vault_errors_do_not_expose_secret_material(self):
        marker = "do-not-log-this-key"
        self.bootstrap()
        self.key_vault.fail_get = True
        with self.assertRaises(ledger_anchor.LedgerAnchorVaultError) as caught:
            self.anchor.verify(self.owner)
        self.assertNotIn(marker, str(caught.exception))
        self.assertNotIn(repr(self.owner._instance_token), repr(self.owner))

    def test_entity_counts_are_canonical_and_bounded(self):
        left = snapshot(counts={"z": 2, "a": 1})
        right = snapshot(counts={"a": 1, "z": 2})
        self.assertEqual(left, right)
        with self.assertRaises(ledger_anchor.LedgerAnchorContractError):
            snapshot(counts={"Bad Name": 1})
        with self.assertRaises(ledger_anchor.LedgerAnchorContractError):
            snapshot(counts={f"x{i}": i for i in range(33)})

    def test_posix_journal_and_lock_are_owner_only(self):
        if os.name == "nt":
            self.skipTest("POSIX mode test")
        self.bootstrap()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_file_lock_cancellation_cleans_every_acquisition_seam(self):
        original_open = os.open
        original_fstat = os.fstat

        for seam in ("parent", "fstat", "permissions", "fsync"):
            with self.subTest(seam=seam):
                lock_path = self.path.with_name(f"{seam}.journal")
                cancellation = InjectedCancellation(f"cancel-{seam}")
                opened = []
                mutexes = []

                class FakeMutex:
                    def __init__(self, _path):
                        self.acquired = False
                        self.released = False
                        mutexes.append(self)

                    def acquire(self):
                        self.acquired = True

                    def release(self):
                        self.released = True

                def tracked_open(*args, **kwargs):
                    descriptor = original_open(*args, **kwargs)
                    opened.append(descriptor)
                    return descriptor

                patches = [
                    patch.object(ledger_anchor, "_BoundedWindowsMutex", FakeMutex),
                    patch.object(ledger_anchor.os, "open", side_effect=tracked_open),
                ]
                if seam == "parent":
                    patches.append(
                        patch.object(
                            ledger_anchor,
                            "_prepare_parent",
                            side_effect=cancellation,
                        )
                    )
                elif seam == "fstat":
                    patches.append(
                        patch.object(
                            ledger_anchor.os,
                            "fstat",
                            side_effect=cancellation,
                        )
                    )
                elif seam == "permissions":
                    patches.append(
                        patch.object(
                            ledger_anchor,
                            "_apply_file_permissions",
                            side_effect=cancellation,
                        )
                    )
                else:
                    patches.extend(
                        (
                            patch.object(
                                ledger_anchor, "_apply_file_permissions", return_value=None
                            ),
                            patch.object(
                                ledger_anchor.os, "fsync", side_effect=cancellation
                            ),
                        )
                    )

                entered = []
                try:
                    for context in patches:
                        context.start()
                        entered.append(context)
                    with self.assertRaises(InjectedCancellation) as caught:
                        with ledger_anchor._AnchorFileLock(lock_path):
                            self.fail("cancellation must prevent lock entry")
                    self.assertIs(caught.exception, cancellation)
                finally:
                    for context in reversed(entered):
                        context.stop()

                if os.name == "nt":
                    self.assertEqual(len(mutexes), 1)
                    self.assertTrue(mutexes[0].acquired)
                    self.assertTrue(mutexes[0].released)
                else:
                    self.assertEqual(mutexes, [])
                for descriptor in opened:
                    with self.assertRaises(OSError):
                        original_fstat(descriptor)

    def test_journal_open_cancellation_closes_descriptor_at_every_post_open_seam(self):
        self.path.parent.mkdir(parents=True)
        original_open = os.open
        original_fstat = os.fstat

        seams = {
            "fstat": (ledger_anchor.os, "fstat"),
            "identity": (ledger_anchor, "_identity_from_stat"),
            "path_identity": (ledger_anchor, "_assert_path_identity"),
            "permissions": (ledger_anchor, "_apply_file_permissions"),
        }
        for seam, (target, attribute) in seams.items():
            with self.subTest(seam=seam):
                cancellation = InjectedCancellation(f"cancel-{seam}")
                opened = []

                def tracked_open(*args, **kwargs):
                    descriptor = original_open(*args, **kwargs)
                    opened.append(descriptor)
                    return descriptor

                with ExitStack() as patches:
                    patches.enter_context(
                        patch.object(ledger_anchor.os, "open", side_effect=tracked_open)
                    )
                    patches.enter_context(
                        patch.object(target, attribute, side_effect=cancellation)
                    )
                    with self.assertRaises(InjectedCancellation) as caught:
                        self.anchor._open_journal(create=True)
                    self.assertIs(caught.exception, cancellation)

                self.assertEqual(len(opened), 1)
                with self.assertRaises(OSError):
                    original_fstat(opened[0])

                # No descriptor/identity state survives the failed attempt.
                descriptor = self.anchor._open_journal(create=True)
                os.close(descriptor)

    def test_journal_open_cleanup_failure_never_replaces_cancellation(self):
        self.path.parent.mkdir(parents=True)
        original_open = os.open
        original_close = os.close
        original_fstat = os.fstat
        opened = []
        cancellation = InjectedCancellation("cancel-primary")
        cleanup_failure = InjectedCancellation("cancel-cleanup")

        def tracked_open(*args, **kwargs):
            descriptor = original_open(*args, **kwargs)
            opened.append(descriptor)
            return descriptor

        def close_then_fail(descriptor):
            original_close(descriptor)
            raise cleanup_failure

        with (
            patch.object(ledger_anchor.os, "open", side_effect=tracked_open),
            patch.object(ledger_anchor.os, "fstat", side_effect=cancellation),
            patch.object(ledger_anchor.os, "close", side_effect=close_then_fail),
        ):
            with self.assertRaises(InjectedCancellation) as caught:
                self.anchor._open_journal(create=True)
        self.assertIs(caught.exception, cancellation)
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError):
            original_fstat(opened[0])

    def test_journal_open_propagates_base_exceptions_and_never_closes_without_fd(self):
        self.path.parent.mkdir(parents=True)

        for primary in (
            KeyboardInterrupt("cancel-keyboard"),
            SystemExit(73),
            InjectedCancellation("cancel-custom"),
        ):
            with self.subTest(exception=type(primary).__name__):
                with (
                    patch.object(ledger_anchor.os, "open", side_effect=primary),
                    patch.object(ledger_anchor.os, "close") as close,
                ):
                    with self.assertRaises(type(primary)) as caught:
                        self.anchor._open_journal(create=True)
                self.assertIs(caught.exception, primary)
                close.assert_not_called()

    def test_journal_hardlink_is_rejected(self):
        self.bootstrap()
        linked = self.path.with_name("linked.journal")
        try:
            os.link(self.path, linked)
        except OSError:
            self.skipTest("hardlink creation is unavailable")
        with self.assertRaises(ledger_anchor.LedgerAnchorIOError):
            self.anchor.verify(self.owner)

    def test_journal_frame_cap_is_fail_closed(self):
        self.bootstrap()
        self.port.current = snapshot("2", events=1)
        with patch.object(ledger_anchor, "_MAX_JOURNAL_FRAMES", 1):
            with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
                self.anchor.prepare(self.owner)

    def test_journal_byte_cap_is_streamed_and_fail_closed(self):
        self.bootstrap()
        with patch.object(ledger_anchor, "_MAX_JOURNAL_BYTES", self.path.stat().st_size - 1):
            with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
                self.anchor.verify(self.owner)
        self.assertNotIn("_read_all", inspect.getsource(ledger_anchor.LedgerAnchor))

    def test_in_process_lock_timeout_is_bounded(self):
        self.bootstrap()

        class BusyLock:
            def acquire(self, *, timeout):
                self.timeout = timeout
                return False

            def release(self):
                raise AssertionError("unacquired lock must not be released")

        busy = BusyLock()
        with patch.object(ledger_anchor, "_THREAD_LOCK", busy):
            with self.assertRaises(ledger_anchor.LedgerAnchorConflict):
                self.anchor.verify(self.owner)
        self.assertEqual(busy.timeout, ledger_anchor._LOCK_TIMEOUT_SECONDS)

    def test_linux_binary_secret_uses_fixed_argv_and_not_raw_input(self):
        calls = []

        def runner(argv, *, secret_input=None):
            calls.append((argv, secret_input))
            return subprocess.CompletedProcess(argv, 0, "", "")

        reference = native_vault.SecretReference("Onyx.Anchor.Test", "owner", "test")
        raw = bytes(range(32))
        tool = os.path.abspath("secret-tool-test")
        with patch.object(native_vault, "_validate_linux_tool", return_value=tool):
            native_vault.linux_set(reference, raw, runner=runner, tool_path=tool)
        argv, secret_input = calls[0]
        self.assertEqual(argv[0], tool)
        self.assertNotIn(raw.hex(), " ".join(argv))
        self.assertNotIn(raw.decode("latin1"), " ".join(argv))
        self.assertTrue(secret_input.startswith("onyx-native-binary-v1:"))
        self.assertIn("shell=False", inspect.getsource(native_vault._run_backend))

    def test_native_vault_namespace_is_bounded_and_has_no_file_fallback(self):
        with self.assertRaises(native_vault.NativeVaultError):
            native_vault.SecretReference("bad service", "owner", "label")
        source = inspect.getsource(native_vault.NativeSecretVault)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("Path", source)
        protected = native_vault.SecretReference(
            "Onyx.DomainLedgerAnchorKey.v1", "owner", "anchor"
        )
        with self.assertRaises(native_vault.NativeVaultError):
            native_vault.NativeSecretVault(protected, system="Windows")
        self.assertNotIn("NativeSecretVault", native_vault.__all__)
        self.assertNotIn("SecretReference", native_vault.__all__)

    def test_windows_generic_target_includes_account_and_defaults_resolve_at_call_time(self):
        reference = native_vault.SecretReference("Onyx.Test", "account-a", "test")
        targets = []

        def api():
            value = MagicMock()

            def write(pointer, _flags):
                targets.append(pointer._obj.TargetName)
                return True

            value.CredWriteW.side_effect = write
            return value

        native_vault.windows_set(reference, b"secret", api_factory=api)
        native_vault.windows_set(
            reference, b"secret", api_factory=api, legacy_target=True
        )
        self.assertEqual(targets, ["Onyx.Test:account-a", "Onyx.Test"])
        with patch.object(native_vault, "_win_api", side_effect=api) as resolved:
            native_vault.windows_set(reference, b"secret")
        resolved.assert_called_once_with()

    def test_public_anchor_constructor_and_exports_do_not_allow_injection(self):
        with self.assertRaises(TypeError):
            ledger_anchor.LedgerAnchor(
                self.port, self.path, self.key_vault, self.state_vault
            )
        for name in ("LedgerAnchor", "LedgerSnapshot", "OwnerCapability", "PreparedTicket"):
            self.assertNotIn(name, ledger_anchor.__all__)


    def test_checkpoint_rotation_is_hot_verifiable_and_cold_auditable(self):
        self.bootstrap()
        self.port.current = snapshot("2", events=1)
        with patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 3):
            ticket = self.anchor.prepare(self.owner)
            status = self.anchor.finalize(self.owner, ticket)
        archives = list(self.path.parent.glob(f"{self.path.name}.archive.*"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(self.anchor.verify(self.owner), status)
        self.assertEqual(self.anchor.verify_history(self.owner), status)
        orphan = b"content-addressed but not linked from the authenticated chain"
        orphan_digest = hashlib.sha256(orphan).hexdigest()
        self.anchor._archive_path(0, orphan_digest).write_bytes(orphan)
        self.assertEqual(self.anchor.verify_history(self.owner), status)
        head = ledger_anchor._head_from_bytes(
            self.state_vault.value, self.key_vault.value
        )
        self.assertEqual(head.generation, 1)
        self.assertEqual(head.active_frame_count, 1)

    def test_crash_after_checkpoint_replace_adopts_unique_successor(self):
        self.bootstrap()
        self.port.current = snapshot("2", events=1)

        def crash(point):
            if point == "after_checkpoint_replace":
                raise InjectedCrash(point)

        with (
            patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 3),
            patch.object(self.anchor, "_fault", side_effect=crash),
        ):
            ticket = self.anchor.prepare(self.owner)
            with self.assertRaises(InjectedCrash):
                self.anchor.finalize(self.owner, ticket)
        old_head = ledger_anchor._head_from_bytes(
            self.state_vault.value, self.key_vault.value
        )
        self.assertEqual(old_head.generation, 0)
        reopened, reopened_owner = ledger_anchor._open_for_testing(
            self.port,
            journal_path=self.path,
            key_vault=self.key_vault,
            state_vault=self.state_vault,
        )
        status = reopened.verify(reopened_owner)
        adopted = ledger_anchor._head_from_bytes(
            self.state_vault.value, self.key_vault.value
        )
        self.assertEqual(adopted.generation, 1)
        self.assertEqual(status.ledger_root, self.port.current.ledger_root)
        self.assertEqual(reopened.verify_history(reopened_owner), status)

    def test_archive_mutation_is_cold_detected_without_hot_archive_scan(self):
        self.bootstrap()
        self.port.current = snapshot("2", events=1)
        with patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 3):
            ticket = self.anchor.prepare(self.owner)
            status = self.anchor.finalize(self.owner, ticket)
        archive = next(self.path.parent.glob(f"{self.path.name}.archive.*"))
        damaged = bytearray(archive.read_bytes())
        damaged[len(damaged) // 2] ^= 1
        archive.chmod(stat.S_IREAD | stat.S_IWRITE)
        archive.write_bytes(damaged)
        self.assertEqual(self.anchor.verify(self.owner), status)
        with self.assertRaises(ledger_anchor.LedgerAnchorIntegrityError):
            self.anchor.verify_history(self.owner)

    def test_archive_collision_and_pre_replace_crash_fail_closed(self):
        self.bootstrap()
        active = self.path.read_bytes()
        digest = hashlib.sha256(active).hexdigest()
        collision = self.anchor._archive_path(0, digest)
        collision.write_bytes(b"not-the-authenticated-generation")
        with (
            patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 1),
            self.assertRaisesRegex(
                ledger_anchor.LedgerAnchorIntegrityError, "collision"
            ),
        ):
            self.anchor._maybe_rotate(self.key_vault.value)
        collision.unlink()

        def crash(point):
            if point == "after_checkpoint_temp_fsync":
                raise InjectedCrash(point)

        with (
            patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 1),
            patch.object(self.anchor, "_fault", side_effect=crash),
            self.assertRaises(InjectedCrash),
        ):
            self.anchor._maybe_rotate(self.key_vault.value)
        self.assertEqual(self.anchor.verify(self.owner).sequence, 0)
        self.assertEqual(self.anchor.verify_history(self.owner).sequence, 0)

    def test_hot_verification_is_generation_bounded_across_many_rotations(self):
        self.bootstrap()
        with patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 3):
            for index in range(1, 5):
                self.port.current = snapshot(str(index + 1), events=index)
                ticket = self.anchor.prepare(self.owner)
                self.anchor.finalize(self.owner, ticket)
        archives = list(self.path.parent.glob(f"{self.path.name}.archive.*"))
        self.assertGreaterEqual(len(archives), 4)
        measured: list[int] = []
        original = self.anchor._sha256_prefix

        def instrument(descriptor, length):
            measured.append(length)
            return original(descriptor, length)

        with (
            patch.object(self.anchor, "_sha256_prefix", side_effect=instrument),
            patch.object(
                self.anchor,
                "_adopt_successor",
                wraps=self.anchor._adopt_successor,
            ) as adopt,
        ):
            self.anchor.verify(self.owner)
        self.assertTrue(measured)
        self.assertLessEqual(max(measured), ledger_anchor._ACTIVE_JOURNAL_MAX_BYTES)
        adopt.assert_not_called()

    def test_repeated_prepare_recovery_rotates_before_exceeding_hard_cap(self):
        committed = self.bootstrap()
        with patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 3):
            for index in range(5):
                candidate = snapshot(str(index + 2), events=index + 1)
                with self.assertRaises(InjectedCrash):
                    with self.anchor.writer_session(self.owner) as session:
                        session.verify_baseline()
                        self.port.current = candidate
                        session.prepare_candidate()
                        self.port.current = self.initial
                        raise InjectedCrash("rollback prepared transition")
                head = ledger_anchor._head_from_bytes(
                    self.state_vault.value, self.key_vault.value
                )
                self.assertLessEqual(head.active_frame_count, 3)
                self.assertLessEqual(
                    self.path.stat().st_size,
                    ledger_anchor._ACTIVE_JOURNAL_MAX_BYTES,
                )
                self.assertEqual(self.anchor.verify(self.owner), committed)

    def test_repeated_prepare_recovery_rotates_at_byte_cap(self):
        committed = self.bootstrap()
        byte_cap = self.path.stat().st_size * 4
        with (
            patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 10_000),
            patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_BYTES", byte_cap),
        ):
            for index in range(4):
                candidate = snapshot(str(index + 2), events=index + 1)
                with self.assertRaises(InjectedCrash):
                    with self.anchor.writer_session(self.owner) as session:
                        session.verify_baseline()
                        self.port.current = candidate
                        session.prepare_candidate()
                        self.port.current = self.initial
                        raise InjectedCrash("rollback byte-capped transition")
                head = ledger_anchor._head_from_bytes(
                    self.state_vault.value, self.key_vault.value
                )
                self.assertLessEqual(head.tail_offset, byte_cap)
                self.assertLessEqual(self.path.stat().st_size, byte_cap)
                self.assertEqual(self.anchor.verify(self.owner), committed)

    def test_recovery_truncates_partial_suffix_before_rotating_at_frame_cap(self):
        committed = self.bootstrap()
        self.port.current = snapshot("2", events=1)
        self.anchor.prepare(self.owner)
        # The authenticated head is exactly at the patched two-frame cap.  A
        # torn next header must be removed before rotation inspects the sealed
        # generation; recovery then has room for its rollback frame.
        with self.path.open("ab") as journal:
            journal.write(ledger_anchor._JOURNAL_MAGIC[:3])
            journal.flush()
            os.fsync(journal.fileno())
        self.port.current = self.initial
        with patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 2):
            recovered = self.anchor.recover(self.owner)
        self.assertEqual(recovered, committed)
        head = ledger_anchor._head_from_bytes(
            self.state_vault.value, self.key_vault.value
        )
        self.assertLessEqual(head.active_frame_count, 2)
        self.assertLessEqual(
            self.path.stat().st_size, ledger_anchor._ACTIVE_JOURNAL_MAX_BYTES
        )

    def test_finalize_rotates_without_crossing_frame_or_byte_cap(self):
        self.bootstrap()
        self.port.current = snapshot("2", events=1)
        ticket = self.anchor.prepare(self.owner)
        with patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 2):
            status = self.anchor.finalize(self.owner, ticket)
        head = ledger_anchor._head_from_bytes(
            self.state_vault.value, self.key_vault.value
        )
        self.assertEqual(status.ledger_root, self.port.current.ledger_root)
        self.assertLessEqual(head.active_frame_count, 2)
        self.assertLessEqual(
            self.path.stat().st_size, ledger_anchor._ACTIVE_JOURNAL_MAX_BYTES
        )

    @unittest.skipIf(os.name == "nt", "POSIX immutable-mode assertion")
    def test_cold_archive_read_preserves_read_only_mode(self):
        self.bootstrap()
        self.port.current = snapshot("2", events=1)
        with patch.object(ledger_anchor, "_ACTIVE_JOURNAL_MAX_FRAMES", 3):
            ticket = self.anchor.prepare(self.owner)
            self.anchor.finalize(self.owner, ticket)
        archive = next(self.path.parent.glob(f"{self.path.name}.archive.*"))
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o400)
        self.anchor.verify_history(self.owner)
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o400)

    def test_secure_bounded_read_rejects_oversize_before_streaming(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        oversized = self.path.parent / "oversized.archive"
        oversized.write_bytes(b"x" * 129)
        with (
            patch.object(self.anchor, "_read_exact", wraps=self.anchor._read_exact) as read,
            self.assertRaisesRegex(
                ledger_anchor.LedgerAnchorIntegrityError, "bounded size"
            ),
        ):
            self.anchor._read_secure_bounded_file(
                oversized, limit=128, label="test archive"
            )
        read.assert_not_called()

    def test_secure_bounded_read_rejects_identity_swap_during_open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        target = self.path.parent / "swap-target.archive"
        displaced = self.path.parent / "swap-displaced.archive"
        replacement = self.path.parent / "swap-replacement.archive"
        target.write_bytes(b"authenticated-original")
        replacement.write_bytes(b"attacker-replacement")
        real_open = os.open
        swapped = False

        def swap_then_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if Path(path) == target and not swapped:
                swapped = True
                os.replace(target, displaced)
                os.replace(replacement, target)
            return real_open(path, flags, *args, **kwargs)

        with (
            patch.object(ledger_anchor.os, "open", side_effect=swap_then_open),
            self.assertRaisesRegex(
                ledger_anchor.LedgerAnchorIntegrityError,
                "identity changed during open",
            ),
        ):
            self.anchor._read_secure_bounded_file(
                target, limit=1024, label="test archive"
            )
        self.assertTrue(swapped)

    def test_secure_bounded_read_rejects_symlink_or_skips_when_unavailable(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        target = self.path.parent / "symlink-target.archive"
        link = self.path.parent / "symlink.archive"
        target.write_bytes(b"target")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"platform cannot create a test symlink: {exc}")
        with self.assertRaises(ledger_anchor.LedgerAnchorError):
            self.anchor._read_secure_bounded_file(
                link, limit=1024, label="test archive"
            )

    def test_secure_archive_and_temp_reads_reject_hardlinks_without_touching_target(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        target = self.path.parent / "outside-target.bin"
        target.write_bytes(b"do-not-touch")
        linked_archive = self.path.parent / "linked.archive"
        linked_temp = self.path.parent / "linked.tmp"
        try:
            os.link(target, linked_archive)
            os.link(target, linked_temp)
        except OSError as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        for path, label, immutable in (
            (linked_archive, "anchor archive generation", True),
            (linked_temp, "anchor checkpoint temporary file", False),
        ):
            with self.subTest(label=label), self.assertRaises(
                ledger_anchor.LedgerAnchorIntegrityError
            ):
                self.anchor._read_secure_bounded_file(
                    path, limit=128, label=label, immutable=immutable
                )
        self.assertEqual(target.read_bytes(), b"do-not-touch")

    @unittest.skipUnless(os.name == "nt", "Windows durability API test")
    def test_windows_atomic_replace_uses_write_through_and_flush_attempt(self):
        source = self.path.with_suffix(".tmp")
        target = self.path
        with (
            patch.object(self.anchor, "_windows_move_replace") as move,
            patch.object(self.anchor, "_fsync_parent", return_value=False) as flush,
        ):
            durable = self.anchor._atomic_replace(source, target)
        move.assert_called_once_with(source, target)
        flush.assert_called_once_with()
        self.assertFalse(durable)

    @unittest.skipUnless(os.name == "nt", "Windows real filesystem durability test")
    def test_windows_real_atomic_replace_moves_bytes_and_attempts_directory_flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        source = self.path.with_suffix(".real.tmp")
        target = self.path.with_suffix(".real.target")
        source.write_bytes(b"replacement")
        target.write_bytes(b"stale")
        attempted = []
        original_flush = self.anchor._windows_flush_directory

        def observed_flush(path):
            attempted.append(path)
            return original_flush(path)

        # This exercises the real MoveFileExW path and a real directory-flush
        # attempt. It deliberately does not claim to simulate sudden power loss.
        with patch.object(
            self.anchor, "_windows_flush_directory", side_effect=observed_flush
        ):
            durable = self.anchor._atomic_replace(source, target)
        self.assertFalse(source.exists())
        self.assertEqual(target.read_bytes(), b"replacement")
        self.assertEqual(attempted, [self.path.parent])
        self.assertIsInstance(durable, bool)

    @unittest.skipUnless(os.name == "nt", "Windows durability API test")
    def test_windows_move_replace_requests_replace_and_write_through_flags(self):
        calls = []

        class Function:
            argtypes = None
            restype = None

            def __call__(self, *args):
                calls.append(args)
                return 1

        class Kernel32:
            MoveFileExW = Function()

        with patch.object(ledger_anchor.ctypes, "WinDLL", return_value=Kernel32()):
            self.anchor._windows_move_replace(
                self.path.with_suffix(".tmp"), self.path
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], 0x1 | 0x8)


if __name__ == "__main__":
    unittest.main()
