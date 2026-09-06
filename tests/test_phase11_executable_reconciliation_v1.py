import copy
import hashlib
import hmac
import unittest
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.phase11_live_mission_v1 import (
    Phase11LiveMissionError,
    Phase11LiveMissionV1,
    _canonical,
)


KEY = b"r" * 32
MISSION_ID = "mis_" + "a" * 32
EXECUTION_ID = "b" * 64
PLAN_DIGEST = "c" * 64
BINDING_DIGEST = "d" * 64


class _Store:
    def __init__(self) -> None:
        self.state = "waiting"
        self.cancel_count = 0

    def get(self, _mission_id):
        return SimpleNamespace(state=self.state)

    def cancel(self, _mission_id):
        self.cancel_count += 1
        self.state = "cancelled"
        return self.get(_mission_id)


class _Autopilot:
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint

    def checkpoint_status(self, _mission_id):
        return copy.deepcopy(self.checkpoint)


class _ExecutionLedger:
    def __init__(self, receipt):
        self.enabled = True
        self.receipt = copy.deepcopy(receipt)
        self.read_count = 0

    def authenticated_receipt(self, **binding):
        self.read_count += 1
        if (
            binding.get("mission_id") == MISSION_ID
            and binding.get("execution_id") == EXECUTION_ID
            and binding.get("attempt") == self.receipt.get("attempt")
        ):
            return copy.deepcopy(self.receipt)
        return None


class ExecutableReconciliationV1Tests(unittest.TestCase):
    def setUp(self):
        self.intent = {"index": 0, "execution_id": EXECUTION_ID}
        self.checkpoint = {
            "executable_plan_digest": PLAN_DIGEST,
            "executable_gate_index": 0,
            "executable_gate_intent": copy.deepcopy(self.intent),
            "repository_code_execution_state": "attempted_unknown",
        }
        signing_key = Ed25519PrivateKey.from_private_bytes(
            hashlib.sha256(KEY + b"authority").digest()
        )
        self.document = {
            "mission_id": MISSION_ID,
            "mission_type": "project_autopilot_v1",
            "binding_digest": BINDING_DIGEST,
            "authority_public_key": signing_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ).hex(),
            "executable_autopilot": {
                "plan_digest": PLAN_DIGEST,
                "gate_count": 1,
            },
        }
        self.events = []
        self.store = _Store()
        self.bridge = Phase11LiveMissionV1.__new__(Phase11LiveMissionV1)
        self.bridge._lock = __import__("threading").RLock()
        self.bridge._key = KEY
        self.bridge._authority_signing_key = signing_key
        self.bridge.store = self.store
        self.bridge.autopilot = _Autopilot(self.checkpoint)
        self.bridge._execution_ledger = None
        self.bridge._reconciliation_fault = lambda _point: None
        self.bridge._validate_current_binding = (
            lambda _mission_id, advance_anchor=False: self.document
        )
        self.bridge._events = lambda _mission_id: copy.deepcopy(self.events)

        def authority_event(_mission_id, event, detail):
            self.events.append(
                {
                    "event": event,
                    "detail": self.bridge._sign_authority_detail(
                        MISSION_ID, event, detail
                    ),
                }
            )

        self.bridge._authority_event = authority_event
        self.kill_count = 0

        def request_kill(_mission_id):
            self.kill_count += 1
            return True

        self.bridge.request_kill = request_kill

    def test_still_unknown_is_append_only_idempotent_and_never_dispatches(self):
        original = copy.deepcopy(self.checkpoint)
        first = self.bridge.reconcile_executable_attempt(
            MISSION_ID, decision="still_unknown"
        )
        second = self.bridge.reconcile_executable_attempt(
            MISSION_ID, decision="still_unknown"
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["detail"]["decision"], "still_unknown")
        self.assertFalse(first["dispatch_permitted"])
        self.assertEqual(self.checkpoint, original)
        self.assertEqual(self.store.state, "waiting")

    def test_abandon_anchors_before_kill_and_cancel_and_is_restart_idempotent(self):
        calls = []

        def fault(point):
            calls.append(point)
            if point == "after_reconciliation_anchor":
                raise RuntimeError("simulated restart")

        self.bridge._reconciliation_fault = fault
        with self.assertRaisesRegex(RuntimeError, "simulated restart"):
            self.bridge.reconcile_executable_attempt(
                MISSION_ID, decision="abandon"
            )
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.kill_count, 0)
        self.assertEqual(self.store.cancel_count, 0)

        self.bridge._reconciliation_fault = lambda point: calls.append(point)
        outcome = self.bridge.reconcile_executable_attempt(
            MISSION_ID, decision="abandon"
        )
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.kill_count, 1)
        self.assertEqual(self.store.cancel_count, 1)
        self.assertTrue(outcome["terminal"])
        self.assertEqual(
            calls,
            [
                "after_reconciliation_anchor",
                "after_reconciliation_anchor",
                "after_kill_anchor",
            ],
        )

    def test_receipt_and_absence_recovery_refuse_unavailable_host_proof(self):
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "receipt ledger is unavailable"
        ):
            self.bridge.reconcile_executable_attempt(
                MISSION_ID,
                decision="recovered_receipt",
                recovered_receipt={"receipt_hmac_sha256": "f" * 64},
            )
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "dispatch ledger is unavailable"
        ):
            self.bridge.reconcile_executable_attempt(
                MISSION_ID,
                decision="proven_not_executed",
                host_execution_absence_proof={"not_dispatched": True},
            )
        self.assertEqual(self.events, [])
        self.assertEqual(self.checkpoint["executable_gate_intent"], self.intent)

    def test_cold_restart_window_recovers_only_exact_committed_ledger_receipt(self):
        receipt = {
            "execution_id": EXECUTION_ID,
            "attempt": 1,
            "receipt_hmac_sha256": "f" * 64,
        }
        ledger = _ExecutionLedger(receipt)
        self.bridge._execution_ledger = ledger

        def crash_after_anchor(point):
            if point == "after_reconciliation_anchor":
                raise RuntimeError("simulated restart after reconciliation anchor")

        self.bridge._reconciliation_fault = crash_after_anchor
        with self.assertRaisesRegex(RuntimeError, "simulated restart"):
            self.bridge.reconcile_executable_attempt(
                MISSION_ID,
                decision="recovered_receipt",
                recovered_receipt=receipt,
            )
        self.assertEqual(len(self.events), 1)
        self.assertEqual(
            self.events[0]["detail"]["recovered_receipt_sha256"],
            hashlib.sha256(_canonical(receipt)).hexdigest(),
        )
        self.assertEqual(
            self.checkpoint["repository_code_execution_state"],
            "attempted_unknown",
        )

        self.bridge._reconciliation_fault = lambda _point: None
        recovered = self.bridge.reconcile_executable_attempt(
            MISSION_ID,
            decision="recovered_receipt",
            recovered_receipt=receipt,
        )
        self.assertEqual(recovered["repository_code_execution_state"], "recovered_receipt")
        self.assertFalse(recovered["dispatch_permitted"])
        self.assertEqual(len(self.events), 1)

        with self.assertRaisesRegex(
            Phase11LiveMissionError, "not authenticated"
        ):
            self.bridge.reconcile_executable_attempt(
                MISSION_ID,
                decision="recovered_receipt",
                recovered_receipt={**receipt, "receipt_hmac_sha256": "0" * 64},
            )

    def test_intent_tamper_and_non_waiting_state_fail_closed(self):
        self.bridge.autopilot.checkpoint["executable_gate_intent"][
            "execution_id"
        ] = "e" * 64
        self.bridge.autopilot.checkpoint[
            "repository_code_execution_state"
        ] = "executed_receipt"
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "attempted-unknown"
        ):
            self.bridge.reconcile_executable_attempt(
                MISSION_ID, decision="still_unknown"
            )
        self.bridge.autopilot.checkpoint = {
            "executable_plan_digest": PLAN_DIGEST,
            "executable_gate_index": 0,
            "executable_gate_intent": copy.deepcopy(self.intent),
            "repository_code_execution_state": "attempted_unknown",
        }
        self.store.state = "running"
        with self.assertRaisesRegex(
            Phase11LiveMissionError, "waiting mission"
        ):
            self.bridge.reconcile_executable_attempt(
                MISSION_ID, decision="still_unknown"
            )

    def test_reconciliation_detail_hmac_signature_and_field_tamper(self):
        projection = {
            "schema": "onyx.phase11.executable_reconciliation.v1",
            "decision": "still_unknown",
            "binding_digest": BINDING_DIGEST,
            "plan_digest": PLAN_DIGEST,
            "gate_index": 0,
            "execution_id": EXECUTION_ID,
            "intent_sha256": hashlib.sha256(
                _canonical(self.intent)
            ).hexdigest(),
            "recovered_receipt_sha256": "",
        }
        resolution_id = hmac.new(
            KEY,
            b"ONYX/PHASE11/EXECUTABLE-RECONCILIATION/V1\0"
            + b"RESOLUTION\0"
            + _canonical(projection),
            hashlib.sha256,
        ).hexdigest()
        detail = {
            **projection,
            "resolution_id": resolution_id,
            "issued_at_ns": 1,
        }
        detail["decision_hmac_sha256"] = hmac.new(
            KEY,
            b"ONYX/PHASE11/EXECUTABLE-RECONCILIATION/V1\0"
            + _canonical(detail),
            hashlib.sha256,
        ).hexdigest()
        signed = self.bridge._sign_authority_detail(
            MISSION_ID, "phase11.reconciliation", detail
        )
        self.bridge._validate_authority_detail(
            self.document, "phase11.reconciliation", signed
        )
        for field, value in (
            ("execution_id", "0" * 64),
            ("gate_index", 1),
            ("decision_hmac_sha256", "0" * 64),
            ("authority_signature", "0" * 128),
        ):
            tampered = dict(signed)
            tampered[field] = value
            with self.subTest(field=field), self.assertRaises(
                Phase11LiveMissionError
            ):
                self.bridge._validate_authority_detail(
                    self.document, "phase11.reconciliation", tampered
                )


if __name__ == "__main__":
    unittest.main()
