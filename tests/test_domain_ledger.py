from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from core import domain_ledger as ledger
from core.control_plane import ControlPlaneStore
from core.domain_ledger import (
    DomainConflict,
    DomainContractError,
    DomainIntegrityError,
    DomainIsolationError,
    DomainLedgerRepository,
)
from core.workspaces import WorkspaceRegistry


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def _fixture(*, second_workspace: bool = False):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch(
            "core.control_plane.private_control_plane_runtime_dir",
            return_value=root / "runtime",
        ):
            store = ControlPlaneStore(enabled=True)
        registry = WorkspaceRegistry(store, enabled=True).initialize()
        registry.register(
            "cyryx-primary",
            display_name="Cyryx Primary",
            workspace_class="cyryx",
        )
        primary = DomainLedgerRepository(
            registry, "cyryx-primary", enabled=True
        ).initialize()
        secondary = None
        if second_workspace:
            registry.register(
                "client-secondary",
                display_name="Client Secondary",
                workspace_class="client",
            )
            secondary = DomainLedgerRepository(
                registry, "client-secondary", enabled=True
            ).initialize()
        try:
            yield root, store, registry, primary, secondary
        finally:
            store.close()


class DomainLedgerFunctionalTests(unittest.TestCase):
    def test_complete_shadow_lifecycle_is_redacted_and_integrity_verified(self):
        with _fixture() as (_root, store, _registry, repository, _secondary):
            evidence = repository.record_evidence(
                "evidence-daily-brief",
                "daily-brief",
                "observation",
                "local dashboard observation",
                "provider-free fixture content",
                credibility_bp=8_000,
                freshness="current",
                validity_seconds=3_600,
                access_license_note="fixture-public",
            )
            claim = repository.record_claim(
                "claim-daily-brief",
                "daily-brief",
                "The fixture reports a provider-free result",
                [evidence.evidence_id],
                claim_kind="fact",
                confidence_bp=8_000,
                verification_status="supported",
                validity_seconds=3_600,
            )
            request = repository.record_action_request(
                "action-daily-brief",
                "daily-brief",
                "shadow.local",
                "render.preview",
                "workspace artifact preview",
                '{"format":"markdown"}',
                risk="low",
                approval_policy="shadow_only",
                data_class="internal",
                verification_plan="compare preview digest",
                rollback_plan="discard preview",
            )
            unknown = repository.record_initial_receipt(
                request.request_id,
                "receipt-daily-brief-1",
                "unknown",
                provider_request_id="shadow-1",
                output="no observed output yet",
                verification="observation pending",
                error_class="observation_timeout",
            )
            self.assertEqual(
                repository.get_action_request(request.request_id).status,
                "reconciliation_required",
            )
            reconciled = repository.record_reconciliation_receipt(
                request.request_id,
                "receipt-daily-brief-2",
                "simulated",
                unknown.receipt_id,
                provider_request_id="shadow-1",
                output="preview observed",
                verification="digest matched",
            )
            self.assertEqual(
                repository.get_action_request(request.request_id).status, "recorded"
            )
            self.assertEqual(repository.get_evidence(evidence.evidence_id), evidence)
            self.assertEqual(repository.get_claim(claim.claim_id), claim)
            self.assertEqual(repository.get_receipt(reconciled.receipt_id), reconciled)
            self.assertEqual(
                repository.list_receipts(request.request_id), (unknown, reconciled)
            )
            self.assertEqual(len(repository.list_events(evidence.correlation_id)), 5)
            repository.verify_integrity()

            connection = store._require_connection()
            all_payloads = "\n".join(
                str(row[0])
                for table in (
                    "evidence_records",
                    "claims",
                    "action_requests",
                    "action_receipts",
                    "event_envelopes",
                    "projections",
                )
                for row in connection.execute(f'SELECT payload_json FROM "{table}"')
            )
            self.assertNotIn("provider-free fixture content", all_payloads)
            self.assertNotIn("The fixture reports", all_payloads)
            self.assertNotIn("workspace artifact preview", all_payloads)
            self.assertNotIn("preview observed", all_payloads)
            for payload in all_payloads.splitlines():
                if payload:
                    self.assertEqual(
                        payload,
                        json.dumps(
                            json.loads(payload),
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )

    def test_workspace_scoped_idempotency_coexists_and_cross_reads_deny(self):
        with _fixture(second_workspace=True) as (
            _root,
            _store,
            _registry,
            primary,
            secondary,
        ):
            assert secondary is not None
            first = primary.record_action_request(
                "same-caller-key",
                "same-correlation",
                "shadow.local",
                "render.preview",
                "primary target",
                "same payload",
            )
            second = secondary.record_action_request(
                "same-caller-key",
                "same-correlation",
                "shadow.local",
                "render.preview",
                "secondary target",
                "same payload",
            )
            self.assertNotEqual(first.idempotency_key, second.idempotency_key)
            self.assertNotEqual(first.request_id, second.request_id)
            with self.assertRaises(DomainIsolationError):
                primary.get_action_request(second.request_id)
            with self.assertRaises(DomainIsolationError):
                secondary.get_action_request(first.request_id)
            primary.verify_integrity()
            secondary.verify_integrity()

    def test_request_exact_replay_returns_current_record_and_divergence_denies(self):
        with _fixture() as (_root, _store, _registry, repository, _secondary):
            first = repository.record_action_request(
                "request-replay",
                "request-replay",
                "shadow.local",
                "render.preview",
                "same target",
                "same payload",
            )
            replay = repository.record_action_request(
                "request-replay",
                "request-replay",
                "shadow.local",
                "render.preview",
                "same target",
                "same payload",
            )
            self.assertEqual(replay, first)
            with self.assertRaises(DomainConflict):
                repository.record_action_request(
                    "request-replay",
                    "request-replay",
                    "shadow.local",
                    "render.preview",
                    "changed target",
                    "same payload",
                )

    def test_partial_and_unknown_only_require_reconciliation_and_never_retry(self):
        with _fixture() as (_root, store, _registry, repository, _secondary):
            request = repository.record_action_request(
                "unknown-request",
                "unknown-correlation",
                "shadow.local",
                "observe.preview",
                "target",
                "payload",
            )
            initial = repository.record_initial_receipt(
                request.request_id, "unknown-first", "partial"
            )
            current = repository.get_action_request(request.request_id)
            self.assertEqual(current.status, "reconciliation_required")
            self.assertEqual(len(repository.list_receipts(request.request_id)), 1)
            with self.assertRaises(DomainConflict):
                repository.record_initial_receipt(
                    request.request_id, "forbidden-second-initial", "succeeded"
                )
            second = repository.record_reconciliation_receipt(
                request.request_id,
                "unknown-second",
                "unknown",
                initial.receipt_id,
            )
            self.assertEqual(
                repository.get_action_request(request.request_id).status,
                "reconciliation_required",
            )
            self.assertEqual(len(repository.list_receipts(request.request_id)), 2)
            self.assertEqual(
                store._require_connection()
                .execute("SELECT count(*) FROM action_requests")
                .fetchone()[0],
                1,
            )
            self.assertEqual(second.outcome, "unknown")

    def test_direct_entity_event_and_head_drift_fail_closed(self):
        mutations = {
            "entity": (
                "UPDATE evidence_records SET content_sha256=? WHERE evidence_id=?",
                lambda record: ("f" * 64, record.evidence_id),
            ),
            "event": (
                "UPDATE event_envelopes SET event_hash=? WHERE event_id=(SELECT event_id "
                "FROM event_envelopes ORDER BY created_at LIMIT 1)",
                lambda _record: ("e" * 64,),
            ),
            "head": (
                "UPDATE projections SET payload_json='{}' WHERE projection_type="
                "'m2a_event_chain_head'",
                lambda _record: (),
            ),
        }
        for label, (sql, parameters) in mutations.items():
            with self.subTest(kind=label), _fixture() as (
                _root,
                store,
                _registry,
                repository,
                _secondary,
            ):
                evidence = repository.record_evidence(
                    f"tamper-{label}", "tamper", "observation", "source", "content"
                )
                connection = store._require_connection()
                connection.execute(sql, parameters(evidence))
                with self.assertRaises(DomainIntegrityError):
                    repository.verify_integrity()

    def test_concurrent_identical_requests_converge_without_duplicate_events(self):
        with _fixture() as (_root, store, _registry, repository, _secondary):
            results = []
            failures = []
            barrier = threading.Barrier(8)

            def worker() -> None:
                try:
                    barrier.wait()
                    results.append(
                        repository.record_action_request(
                            "concurrent-request",
                            "concurrent",
                            "shadow.local",
                            "render.preview",
                            "target",
                            "payload",
                        )
                    )
                except BaseException as exc:  # evidence is asserted below
                    failures.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(20)
            self.assertFalse(failures)
            self.assertEqual(len(results), 8)
            self.assertEqual({item.request_id for item in results}, {results[0].request_id})
            connection = store._require_connection()
            self.assertEqual(
                connection.execute("SELECT count(*) FROM action_requests").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM event_envelopes").fetchone()[0], 1
            )
            repository.verify_integrity()

    def test_mission_and_memory_source_files_are_not_opened_or_modified(self):
        with _fixture() as (root, _store, _registry, repository, _secondary):
            mission = root / "onyx_missions.sqlite3"
            memory = root / "onyx_memory.sqlite3"
            mission.write_bytes(b"mission-source-sentinel")
            memory.write_bytes(b"memory-source-sentinel")
            before = (_sha(mission), _sha(memory))
            with patch("sqlite3.connect", wraps=__import__("sqlite3").connect) as connect:
                repository.record_evidence(
                    "source-preservation",
                    "source-preservation",
                    "observation",
                    "safe source",
                    "safe content",
                )
            opened = " ".join(str(call.args[0]) for call in connect.call_args_list if call.args)
            self.assertNotIn(str(mission), opened)
            self.assertNotIn(str(memory), opened)
            self.assertEqual((_sha(mission), _sha(memory)), before)

    def test_operational_or_secret_shaped_inputs_deny_before_rows_exist(self):
        with _fixture() as (_root, store, _registry, repository, _secondary):
            with self.assertRaises(DomainContractError):
                repository.record_action_request(
                    "not-dry-run",
                    "denied",
                    "shadow.local",
                    "render.preview",
                    "target",
                    "payload",
                    dry_run=False,
                )
            with self.assertRaises(DomainContractError):
                repository.record_action_request(
                    "secret-payload",
                    "denied",
                    "shadow.local",
                    "render.preview",
                    "target",
                    "Authorization: Bearer canary-value",
                )
            connection = store._require_connection()
            self.assertEqual(
                connection.execute("SELECT count(*) FROM action_requests").fetchone()[0], 0
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM event_envelopes").fetchone()[0], 0
            )

    def test_material_hashes_are_type_framed_and_success_requires_observed_proof(self):
        self.assertNotEqual(
            ledger._sha(ledger._safe_material(b"abc", "bytes")),
            ledger._sha(ledger._safe_material("abc", "text")),
        )
        self.assertNotEqual(
            ledger._sha(ledger._safe_material(b"\xff", "bytes")),
            ledger._sha(ledger._safe_material("ff", "text")),
        )
        with self.assertRaises(DomainContractError):
            ledger._safe_material(
                b"Authorization: Bearer bytes-canary-secret", "bytes canary"
            )
        with _fixture() as (_root, store, _registry, repository, _secondary):
            request = repository.record_action_request(
                "proof-request",
                "proof-correlation",
                "shadow.local",
                "observe.preview",
                "target",
                "payload",
            )
            with self.assertRaises(DomainContractError):
                repository.record_initial_receipt(
                    request.request_id, "proof-missing", "succeeded"
                )
            self.assertEqual(
                store._require_connection()
                .execute("SELECT count(*) FROM action_receipts")
                .fetchone()[0],
                0,
            )

    def test_claim_relations_require_exact_same_mission_scope(self):
        with _fixture() as (_root, store, _registry, repository, _secondary):
            connection = store._require_connection()
            now = "2026-07-14T00:00:00+00:00"
            for mission_id in ("mission-a", "mission-b"):
                connection.execute(
                    "INSERT INTO mission_contexts VALUES(?,?,?,?,?,?,?)",
                    (
                        mission_id,
                        "cyryx-primary",
                        1,
                        "ACTIVE",
                        "{}",
                        now,
                        now,
                    ),
                )
            evidence_a = repository.record_evidence(
                "evidence-mission-a",
                "mission-a-correlation",
                "observation",
                "source-a",
                "content-a",
                mission_id="mission-a",
            )
            claim_a = repository.record_claim(
                "claim-mission-a",
                "mission-a-correlation",
                "claim a",
                [evidence_a.evidence_id],
                mission_id="mission-a",
            )
            evidence_b = repository.record_evidence(
                "evidence-mission-b",
                "mission-b-correlation",
                "observation",
                "source-b",
                "content-b",
                mission_id="mission-b",
            )
            with self.assertRaises(DomainIsolationError):
                repository.record_claim(
                    "claim-cross-evidence",
                    "mission-b-correlation",
                    "cross evidence",
                    [evidence_a.evidence_id],
                    mission_id="mission-b",
                )
            with self.assertRaises(DomainIsolationError):
                repository.record_claim(
                    "claim-cross-contradiction",
                    "mission-b-correlation",
                    "cross contradiction",
                    [evidence_b.evidence_id],
                    mission_id="mission-b",
                    contradiction_claim_ids=[claim_a.claim_id],
                )
            with self.assertRaises(DomainIsolationError):
                repository.record_claim(
                    "claim-cross-supersedes",
                    "mission-b-correlation",
                    "cross revision",
                    [evidence_b.evidence_id],
                    mission_id="mission-b",
                    supersedes_claim_id=claim_a.claim_id,
                )
            repository.verify_integrity()

    def test_receipt_order_uses_event_chain_when_all_timestamps_tie(self):
        tied = "2026-07-14T12:00:00+00:00"
        with _fixture() as (_root, _store, _registry, repository, _secondary), patch(
            "core.domain_ledger._now", return_value=tied
        ):
            request = repository.record_action_request(
                "tied-request",
                "tied-correlation",
                "shadow.local",
                "observe.preview",
                "target",
                "payload",
            )
            first = repository.record_initial_receipt(
                request.request_id, "z-first", "unknown"
            )
            second = repository.record_reconciliation_receipt(
                request.request_id,
                "a-second",
                "succeeded",
                first.receipt_id,
                after="observed state",
                verification="deterministic read-back",
            )
            self.assertEqual(repository.list_receipts(request.request_id), (first, second))
            self.assertEqual(
                repository.get_action_request(request.request_id).status, "recorded"
            )
            repository.verify_integrity()


if __name__ == "__main__":
    unittest.main()
