from __future__ import annotations

import json
import os
import hashlib
import tempfile
import threading
import unittest
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from unittest import mock

from core.phase11_executable_sandbox_v1 import (
    SCHEMA as RECEIPT_SCHEMA,
    ExecutableSandboxReceiptV1,
    _canonical as sandbox_canonical,
    _keyed,
    verify_executable_sandbox_receipt_v1,
)
from core.phase11_execution_ledger_v1 import (
    CHECKPOINT_NAME,
    ExecutionLedgerError,
    LEDGER_NAME,
    LOCK_NAME,
    Phase11ExecutionLedgerV1,
    _DOMAIN_CHECKPOINT,
    _DOMAIN_RECORD,
    _mac,
)


LEDGER_KEY = b"host-owned-ledger-secret" * 2
RECEIPT_KEY = b"host-owned-receipt-secret" * 2
BINDING = {
    "mission_id": "mis_ledger_1",
    "execution_id": "e" * 64,
    "workspace_id": "d" * 64,
    "image_digest": "a" * 64,
    "argv_digest": hashlib.sha256(sandbox_canonical(("pytest",))).hexdigest(),
    "attempt": 1,
}


class Phase11ExecutionLedgerV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "trusted"
        if os.name == "nt":
            from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

            self.boundary = WindowsTrustedDirectoryV1(root=self.root, enabled=True)
        else:
            from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

            self.boundary = PosixTrustedDirectoryV1(root=self.root, enabled=True)
        self.path = self.root / LEDGER_NAME

    def tearDown(self) -> None:
        self.boundary.close()
        self.temporary.cleanup()

    def ledger(self, **changes) -> Phase11ExecutionLedgerV1:
        values = {
            "host_secret": LEDGER_KEY,
            "trusted_directory": self.boundary,
            "receipt_signing_key": RECEIPT_KEY,
            "receipt_verifier": verify_executable_sandbox_receipt_v1,
            "enabled": True,
        }
        values.update(changes)
        return Phase11ExecutionLedgerV1(**values)

    @staticmethod
    def receipt(**changes: object) -> ExecutableSandboxReceiptV1:
        value = ExecutableSandboxReceiptV1(
            schema=RECEIPT_SCHEMA,
            execution_id=str(BINDING["execution_id"]),
            attempt=1,
            mission_hmac_sha256=_keyed(RECEIPT_KEY, b"mission", str(BINDING["mission_id"]).encode()),
            image_sha256=str(BINDING["image_digest"]),
            argv_hmac_sha256=_keyed(RECEIPT_KEY, b"argv", sandbox_canonical(("pytest",))),
            prelaunch_clone_manifest_hmac_sha256="c" * 64,
            stdout_hmac_sha256="1" * 64,
            stderr_hmac_sha256="2" * 64,
            stdout_bytes=0,
            stderr_bytes=0,
            exit_code=0,
            duration_ms=1,
            verdict="PASS",
            receipt_hmac_sha256="",
        )
        value = replace(value, **changes)
        signature = _keyed(
            RECEIPT_KEY,
            b"receipt",
            sandbox_canonical({**asdict(value), "receipt_hmac_sha256": ""}),
        )
        return replace(value, receipt_hmac_sha256=signature)

    def test_roundtrip_and_unresolved_reservation_is_unknown(self) -> None:
        ledger = self.ledger(clock_ns=lambda: 7)
        ledger.append("intent", **BINDING)
        ledger.append("dispatch_reserved", **BINDING)
        self.assertEqual(
            ledger.execution_state(
                mission_id=BINDING["mission_id"],
                execution_id=BINDING["execution_id"],
                attempt=1,
            ),
            "unknown",
        )
        receipt = self.receipt()
        ledger.append(
            "receipt",
            receipt=asdict(receipt),
            image_id=f"sha256:{BINDING['image_digest']}",
            argv=("pytest",),
            **BINDING,
        )
        records = ledger.read()
        self.assertEqual([record.sequence for record in records], [1, 2, 3])
        self.assertEqual(records[1].prev_hash, records[0].record_hash)
        self.assertEqual(records[0].timestamp, 7)
        self.assertEqual(
            ledger.authenticated_receipt(
                mission_id=str(BINDING["mission_id"]),
                execution_id=str(BINDING["execution_id"]),
                attempt=1,
            ),
            asdict(receipt),
        )

    def test_tamper_fails_closed(self) -> None:
        self.ledger().append("intent", **BINDING)
        document = json.loads(self.path.read_text())
        document["mission_id"] = "mis_tampered"
        self.path.write_text(json.dumps(document, sort_keys=True) + "\n")
        with self.assertRaises(ExecutionLedgerError):
            self.ledger()

    def test_truncation_and_complete_suffix_replay_fail_closed(self) -> None:
        ledger = self.ledger()
        ledger.append("intent", **BINDING)
        first = self.path.read_bytes()
        ledger.append("dispatch_reserved", **BINDING)
        self.path.write_bytes(first)
        with self.assertRaisesRegex(ExecutionLedgerError, "checkpoint_ahead"):
            self.ledger()

    def test_wrong_binding_and_transition_replay_fail_closed(self) -> None:
        ledger = self.ledger()
        ledger.append("intent", **BINDING)
        with self.assertRaisesRegex(ExecutionLedgerError, "binding_mismatch"):
            ledger.read(workspace_id="c" * 64)
        with self.assertRaisesRegex(ExecutionLedgerError, "replay_or_binding"):
            ledger.append("intent", **BINDING)
        changed = {**BINDING, "workspace_id": "c" * 64}
        with self.assertRaisesRegex(ExecutionLedgerError, "global_execution_replay"):
            ledger.append("dispatch_reserved", **changed)

    def test_restart_verifies_and_continues_chain(self) -> None:
        self.ledger().append("intent", **BINDING)
        restarted = self.ledger()
        restarted.append("dispatch_reserved", **BINDING)
        self.assertEqual(len(self.ledger().read()), 2)

    def test_concurrent_instances_serialize_appends(self) -> None:
        errors: list[BaseException] = []

        def write(index: int) -> None:
            binding = {
                **BINDING,
                "execution_id": f"{index:064x}",
            }
            try:
                self.ledger().append("intent", **binding)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        records = self.ledger().read()
        self.assertEqual(len(records), 12)
        self.assertEqual([record.sequence for record in records], list(range(1, 13)))

    def test_disabled_is_inert_and_does_not_require_secret_or_path(self) -> None:
        ledger = Phase11ExecutionLedgerV1(enabled=False)
        self.assertIsNone(ledger.append("intent", **BINDING))
        self.assertEqual(ledger.read(), ())
        self.assertFalse(self.path.exists())

    def test_short_secret_is_refused(self) -> None:
        with self.assertRaisesRegex(ExecutionLedgerError, "host_secret_invalid"):
            self.ledger(host_secret=b"short")

    def test_fake_receipt_and_cross_binding_replay_fail_closed(self) -> None:
        ledger = self.ledger()
        ledger.append("intent", **BINDING)
        ledger.append("dispatch_reserved", **BINDING)
        fake = asdict(self.receipt())
        fake["receipt_hmac_sha256"] = "f" * 64
        with self.assertRaisesRegex(ExecutionLedgerError, "receipt_unverified"):
            ledger.append(
                "receipt",
                receipt=fake,
                image_id=f"sha256:{BINDING['image_digest']}",
                argv=("pytest",),
                **BINDING,
            )
        other = {**BINDING, "mission_id": "mis_other"}
        with self.assertRaisesRegex(ExecutionLedgerError, "global_execution_replay"):
            ledger.append("intent", **other)

    def test_cold_reopen_rejects_invalid_receipt_with_valid_ledger_chain(self) -> None:
        ledger = self.ledger()
        ledger.append("intent", **BINDING)
        ledger.append("dispatch_reserved", **BINDING)
        ledger.append(
            "receipt",
            receipt=asdict(self.receipt()),
            image_id=f"sha256:{BINDING['image_digest']}",
            argv=("pytest",),
            **BINDING,
        )
        records = [json.loads(line) for line in self.path.read_text().splitlines()]
        receipt_record = records[-1]
        receipt = json.loads(receipt_record["receipt_payload"])
        receipt["receipt_hmac_sha256"] = "f" * 64
        payload = sandbox_canonical(receipt).decode("ascii")
        receipt_record.update(
            receipt_payload=payload,
            receipt_digest=hashlib.sha256(payload.encode("ascii")).hexdigest(),
            receipt_hmac_sha256="f" * 64,
            record_hash="",
        )
        receipt_record["record_hash"] = _mac(
            LEDGER_KEY, _DOMAIN_RECORD, receipt_record
        )
        self.path.write_bytes(
            b"".join(sandbox_canonical(record) + b"\n" for record in records)
        )
        checkpoint_path = self.root / CHECKPOINT_NAME
        checkpoint = json.loads(checkpoint_path.read_text())
        checkpoint["tail_hash"] = receipt_record["record_hash"]
        checkpoint["checkpoint_hmac"] = _mac(
            LEDGER_KEY,
            _DOMAIN_CHECKPOINT,
            {
                key: checkpoint[key]
                for key in ("schema", "sequence", "tail_hash", "size")
            },
        )
        checkpoint_path.write_bytes(sandbox_canonical(checkpoint) + b"\n")

        with self.assertRaisesRegex(
            ExecutionLedgerError, "receipt_binding_invalid"
        ):
            self.ledger()

    def test_attempt_gap_and_downgrade_fail_closed_without_takeover_api(self) -> None:
        for attempt in (2, 3):
            with self.subTest(attempt=attempt), self.assertRaisesRegex(
                ExecutionLedgerError, "retry_takeover_required"
            ):
                self.ledger().append("intent", **{**BINDING, "attempt": attempt})

    def test_valid_ledger_ahead_repairs_checkpoint_after_crash(self) -> None:
        ledger = self.ledger()
        with mock.patch.object(
            ledger, "_write_checkpoint", side_effect=RuntimeError("crash")
        ), self.assertRaisesRegex(ExecutionLedgerError, "storage_failed"):
            ledger.append("intent", **BINDING)
        restarted = self.ledger()
        self.assertEqual(len(restarted.read()), 1)
        self.assertTrue((self.root / CHECKPOINT_NAME).is_file())

    def test_limit_is_prevalidated_before_publish(self) -> None:
        ledger = self.ledger()
        with mock.patch(
            "core.phase11_execution_ledger_v1.MAX_LEDGER_BYTES", 32
        ), self.assertRaisesRegex(ExecutionLedgerError, "size_limit"):
            ledger.append("intent", **BINDING)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_divergent_legacy_lock_and_file_handle_are_refused(self) -> None:
        with self.assertRaisesRegex(ExecutionLedgerError, "legacy_storage_refused"):
            self.ledger(lock_path=self.root / "other.lock")
        with self.assertRaisesRegex(ExecutionLedgerError, "legacy_storage_refused"):
            self.ledger(file_handle=object())
        self.assertEqual(LOCK_NAME, "execution-ledger.lock")

    def test_hardlink_victims_are_refused_for_all_storage_objects(self) -> None:
        for index, name in enumerate((LEDGER_NAME, CHECKPOINT_NAME, LOCK_NAME)):
            with self.subTest(name=name):
                root = Path(self.temporary.name) / f"hardlink-{index}"
                root.mkdir()
                victim = Path(self.temporary.name) / f"victim-{index}.txt"
                victim.write_bytes(b"do-not-touch")
                os.link(victim, root / name)
                boundary_type = type(self.boundary)
                boundary = boundary_type(root=root, enabled=True)
                try:
                    with self.assertRaises(ExecutionLedgerError):
                        Phase11ExecutionLedgerV1(
                            host_secret=LEDGER_KEY,
                            trusted_directory=boundary,
                            receipt_signing_key=RECEIPT_KEY,
                            receipt_verifier=verify_executable_sandbox_receipt_v1,
                            enabled=True,
                        )
                    self.assertEqual(victim.read_bytes(), b"do-not-touch")
                finally:
                    boundary.close()

    def test_symlink_victims_are_refused_for_all_storage_objects(self) -> None:
        probe = Path(self.temporary.name) / "symlink-probe"
        target = Path(self.temporary.name) / "symlink-probe-target"
        target.write_bytes(b"probe")
        try:
            probe.symlink_to(target)
            probe.unlink()
        except OSError:
            self.skipTest("file symlink creation is unavailable")
        for index, name in enumerate((LEDGER_NAME, CHECKPOINT_NAME, LOCK_NAME)):
            with self.subTest(name=name):
                root = Path(self.temporary.name) / f"symlink-{index}"
                root.mkdir()
                victim = Path(self.temporary.name) / f"link-victim-{index}.txt"
                victim.write_bytes(b"do-not-touch")
                (root / name).symlink_to(victim)
                boundary_type = type(self.boundary)
                boundary = boundary_type(root=root, enabled=True)
                try:
                    with self.assertRaises(ExecutionLedgerError):
                        Phase11ExecutionLedgerV1(
                            host_secret=LEDGER_KEY,
                            trusted_directory=boundary,
                            receipt_signing_key=RECEIPT_KEY,
                            receipt_verifier=verify_executable_sandbox_receipt_v1,
                            enabled=True,
                        )
                    self.assertEqual(victim.read_bytes(), b"do-not-touch")
                finally:
                    boundary.close()

    def test_fixed_lock_serializes_independent_processes(self) -> None:
        script = r'''
import hashlib, os, sys
from core.phase11_execution_ledger_v1 import Phase11ExecutionLedgerV1
from core.phase11_executable_sandbox_v1 import verify_executable_sandbox_receipt_v1
if os.name == "nt":
    from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1 as Boundary
else:
    from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1 as Boundary
root, suffix = sys.argv[1], int(sys.argv[2])
boundary = Boundary(root=root, enabled=True)
try:
    ledger = Phase11ExecutionLedgerV1(
        host_secret=b"host-owned-ledger-secret" * 2,
        trusted_directory=boundary,
        receipt_signing_key=b"host-owned-receipt-secret" * 2,
        receipt_verifier=verify_executable_sandbox_receipt_v1,
        enabled=True,
    )
    ledger.append(
        "intent", mission_id=f"mis_process_{suffix}",
        execution_id=f"{suffix:064x}", workspace_id="d" * 64,
        image_digest="a" * 64, argv_digest="b" * 64, attempt=1,
    )
finally:
    boundary.close()
'''
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(self.root), str(index)],
                cwd=Path(__file__).resolve().parents[1],
            )
            for index in (10, 11)
        ]
        self.assertEqual([process.wait(timeout=30) for process in processes], [0, 0])
        self.assertEqual(len(self.ledger().read()), 2)


if __name__ == "__main__":
    unittest.main()
