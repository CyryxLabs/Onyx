from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from core import domain_ledger as ledger
from core.control_plane import (
    M1B_MIGRATION_ID,
    MIGRATION_ID,
    SCHEMA_VERSION,
    ControlPlaneStore,
)
from core.workspaces import LEGACY_WORKSPACE_ID, WorkspaceRegistry


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _control_store(path: Path, *, enabled: bool = True) -> ControlPlaneStore:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=path.parent,
    ):
        return ControlPlaneStore(enabled=enabled)


@contextmanager
def _repository(
    root: Path,
    workspace_id: str = "cyryx-audit",
    *,
    register: bool = True,
    active: bool = True,
):
    sidecar = root / "runtime" / "control_plane.sqlite3"
    store = _control_store(sidecar)
    registry = WorkspaceRegistry(store, enabled=True).initialize()
    if register:
        registry.register(
            workspace_id,
            display_name=workspace_id,
            workspace_class="cyryx",
            active=active,
        )
    repository = ledger.DomainLedgerRepository(
        registry,
        workspace_id,
        enabled=True,
    )
    if register and active:
        repository.initialize()
    try:
        yield repository, registry, store, sidecar
    finally:
        store.close()


def _insert_mission_context(
    store: ControlPlaneStore,
    mission_id: str,
    workspace_id: str,
    *,
    phase: str = "ACTIVE",
) -> None:
    now = "2026-07-14T00:00:00+00:00"
    connection = store._require_connection()
    connection.execute(
        "INSERT INTO mission_contexts("
        "mission_id,workspace_id,schema_version,operational_phase,payload_json,created_at,updated_at"
        ") VALUES(?,?,?,?,?,?,?)",
        (mission_id, workspace_id, 1, phase, "{}", now, now),
    )


def _table_count(store: ControlPlaneStore, table: str) -> int:
    return int(store._require_connection().execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])


def _record_request(
    repository: ledger.DomainLedgerRepository,
    *,
    caller_key: str = "request-one",
    correlation_key: str = "action-one",
    payload: str = '{"amount":1,"currency":"USD"}',
) -> ledger.ActionRequestRecord:
    return repository.record_action_request(
        caller_key,
        correlation_key,
        "test_connector",
        "create_draft",
        "target:test",
        payload,
        risk="medium",
        approval_policy="shadow_only",
        data_class="internal",
        dry_run=True,
        verification_plan="verify test fixture",
        rollback_plan="discard dry-run fixture",
    )


def _process_record_request(
    runtime_text: str,
    workspace_id: str,
    gate: object,
    results: object,
) -> None:
    store: ControlPlaneStore | None = None
    try:
        runtime = Path(runtime_text)
        with patch(
            "core.control_plane.private_control_plane_runtime_dir",
            return_value=runtime,
        ):
            store = ControlPlaneStore(enabled=True)
        registry = WorkspaceRegistry(store, enabled=True).initialize()
        repository = ledger.DomainLedgerRepository(
            registry,
            workspace_id,
            enabled=True,
        ).initialize()
        results.put(("ready", os.getpid()))
        if not gate.wait(30):
            raise RuntimeError("process convergence gate timed out")
        request = _record_request(
            repository,
            caller_key="process-shared",
            correlation_key="process-shared",
        )
        results.put(("ok", request.request_id))
    except BaseException as exc:
        results.put(("error", type(exc).__name__, str(exc)))
        raise
    finally:
        if store is not None:
            store.close()


class DomainLedgerAuditTests(unittest.TestCase):
    def test_flag_is_default_off_and_startup_path_performs_zero_writes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            sidecar = root / "runtime" / "control_plane.sqlite3"
            store = _control_store(sidecar, enabled=False)
            registry = WorkspaceRegistry(store, enabled=False)
            repository = ledger.DomainLedgerRepository(
                registry,
                "cyryx-audit",
                enabled=None,
            )

            self.assertFalse(ledger.m2a_domain_ledger_enabled())
            with self.assertRaises(ledger.DomainLedgerDisabled):
                repository.initialize()
            self.assertFalse(sidecar.exists())
            self.assertFalse(sidecar.parent.exists())

            main_source = (Path(__file__).resolve().parents[1] / "main.py").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("core.domain_ledger", main_source)
            self.assertNotIn("DomainLedgerRepository", main_source)
            self.assertNotIn(ledger.M2A_DOMAIN_LEDGER_FLAG, main_source)

    def test_flag_accepts_only_explicit_true_values(self):
        for value in ("1", " 1 ", "true", "TRUE", " true "):
            self.assertTrue(
                ledger.m2a_domain_ledger_enabled(
                    {ledger.M2A_DOMAIN_LEDGER_FLAG: value}
                )
            )
        for value in ("", "0", "false", "yes", "on", "enabled", "garbage"):
            self.assertFalse(
                ledger.m2a_domain_ledger_enabled(
                    {ledger.M2A_DOMAIN_LEDGER_FLAG: value}
                )
            )

    def test_canonical_json_is_key_order_and_unicode_stable(self):
        first = {"z": ["Ol\u00e1", "\u2603"], "a": {"b": 2, "a": 1}}
        second = {"a": {"a": 1, "b": 2}, "z": ["Ol\u00e1", "\u2603"]}
        encoded_first = ledger._canonical(first)
        encoded_second = ledger._canonical(second)
        self.assertEqual(encoded_first, encoded_second)
        self.assertEqual(json.loads(encoded_first), first)
        self.assertEqual(ledger._sha(encoded_first), ledger._sha(encoded_second))

    def test_canonical_json_rejects_non_finite_numbers_and_non_string_keys(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ledger.DomainContractError):
                ledger._canonical({"value": value})
        for payload in ({1: "numeric"}, {"safe": 1, 2: "mixed"}):
            with self.subTest(payload=payload), self.assertRaises(ledger.DomainContractError):
                ledger._canonical(payload)

    def test_canonical_json_enforces_size_and_depth_as_contract_errors(self):
        with self.assertRaises(ledger.DomainContractError):
            ledger._canonical({"value": "x" * 9000})

        nested: object = "leaf"
        for _ in range(1500):
            nested = [nested]
        with self.assertRaises(ledger.DomainContractError):
            ledger._canonical(nested)

    def test_secret_canaries_are_rejected_before_hashing_or_persistence(self):
        canaries = (
            "Authorization: Bearer super-secret-value",
            "api_key=sk-abcdefghijklmnop",
            "refresh_token: ghp_abcdefghijklmnop",
            "-----BEGIN PRIVATE KEY-----",
            "client_secret = never-store-this",
        )
        for canary in canaries:
            with self.subTest(canary=canary), self.assertRaises(
                ledger.DomainContractError
            ):
                ledger._safe_material(canary, "candidate")

    def test_legacy_workspace_is_rejected_before_repository_initialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            sidecar = Path(tmp) / "runtime" / "control_plane.sqlite3"
            store = _control_store(sidecar)
            registry = WorkspaceRegistry(store, enabled=True)
            with self.assertRaises(ledger.DomainIsolationError):
                ledger.DomainLedgerRepository(
                    registry,
                    LEGACY_WORKSPACE_ID,
                    enabled=True,
                )
            self.assertFalse(sidecar.exists())

    def test_missing_inactive_cross_workspace_and_pending_contexts_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with _repository(root, "missing-workspace", register=False) as (
                missing,
                registry,
                store,
                _path,
            ):
                with self.assertRaises(ledger.DomainIsolationError):
                    missing.initialize()

                registry.register(
                    "inactive-workspace",
                    display_name="inactive",
                    workspace_class="cyryx",
                    active=False,
                )
                inactive = ledger.DomainLedgerRepository(
                    registry,
                    "inactive-workspace",
                    enabled=True,
                )
                with self.assertRaises(ledger.DomainIsolationError):
                    inactive.initialize()

                registry.register(
                    "other-workspace",
                    display_name="other",
                    workspace_class="client",
                    active=True,
                )
                registry.register(
                    "active-workspace",
                    display_name="active",
                    workspace_class="cyryx",
                    active=True,
                )
                active = ledger.DomainLedgerRepository(
                    registry,
                    "active-workspace",
                    enabled=True,
                ).initialize()
                _insert_mission_context(store, "mission-other", "other-workspace")
                _insert_mission_context(
                    store,
                    "mission-pending",
                    "active-workspace",
                    phase="PENDING_REVIEW",
                )

                for mission_id in ("mission-missing", "mission-other", "mission-pending"):
                    with self.subTest(mission_id=mission_id), self.assertRaises(
                        ledger.DomainIsolationError
                    ):
                        active.record_evidence(
                            f"evidence-{mission_id}",
                            "scope-denial",
                            "observation",
                            "local:test",
                            "safe content",
                            mission_id=mission_id,
                        )
                self.assertEqual(_table_count(store, "evidence_records"), 0)
                self.assertEqual(_table_count(store, "event_envelopes"), 0)

    def test_evidence_idempotent_replay_and_divergent_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                first = repository.record_evidence(
                    "evidence-one",
                    "correlation-one",
                    "observation",
                    "local:test",
                    "same content",
                    credibility_bp=7500,
                    freshness="current",
                )
                replay = repository.record_evidence(
                    "evidence-one",
                    "correlation-one",
                    "observation",
                    "local:test",
                    "same content",
                    credibility_bp=7500,
                    freshness="current",
                )
                self.assertEqual(replay, first)
                with self.assertRaises(ledger.DomainConflict):
                    repository.record_evidence(
                        "evidence-one",
                        "correlation-one",
                        "observation",
                        "local:test",
                        "divergent content",
                        credibility_bp=7500,
                        freshness="current",
                    )
                self.assertEqual(_table_count(store, "evidence_records"), 1)
                self.assertEqual(_table_count(store, "event_envelopes"), 1)
                repository.verify_integrity()

    def test_entity_event_and_head_projection_roll_back_at_both_fault_seams(self):
        class InjectedFailure(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                with patch.object(
                    ledger.DomainLedgerRepository,
                    "_before_event_append",
                    side_effect=InjectedFailure("before event"),
                ):
                    with self.assertRaises(InjectedFailure):
                        repository.record_evidence(
                            "rollback-before-event",
                            "rollback",
                            "observation",
                            "local:test",
                            "content",
                        )
                for table in ("evidence_records", "event_envelopes", "projections"):
                    self.assertEqual(_table_count(store, table), 0, table)

                with patch.object(
                    ledger.DomainLedgerRepository,
                    "_before_commit",
                    side_effect=InjectedFailure("before commit"),
                ):
                    with self.assertRaises(InjectedFailure):
                        repository.record_evidence(
                            "rollback-before-commit",
                            "rollback",
                            "observation",
                            "local:test",
                            "content",
                        )
                for table in ("evidence_records", "event_envelopes", "projections"):
                    self.assertEqual(_table_count(store, table), 0, table)
                repository.verify_integrity()

    def test_action_idempotency_replay_conflict_and_workspace_coexistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp), "workspace-alpha") as (
                alpha,
                registry,
                store,
                _path,
            ):
                first = _record_request(alpha, caller_key="shared-key")
                replay = _record_request(alpha, caller_key="shared-key")
                self.assertEqual(replay, first)
                with self.assertRaises(ledger.DomainConflict):
                    _record_request(
                        alpha,
                        caller_key="shared-key",
                        payload='{"amount":2,"currency":"USD"}',
                    )

                registry.register(
                    "workspace-beta",
                    display_name="beta",
                    workspace_class="client",
                    active=True,
                )
                beta = ledger.DomainLedgerRepository(
                    registry,
                    "workspace-beta",
                    enabled=True,
                ).initialize()
                second_workspace = _record_request(beta, caller_key="shared-key")
                self.assertNotEqual(first.request_id, second_workspace.request_id)
                self.assertNotEqual(first.idempotency_key, second_workspace.idempotency_key)
                self.assertEqual(_table_count(store, "action_requests"), 2)
                with self.assertRaises(ledger.DomainIsolationError):
                    alpha.get_action_request(second_workspace.request_id)
                alpha.verify_integrity()
                beta.verify_integrity()

    def test_unknown_and_partial_require_append_only_reconciliation_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                for outcome in ("unknown", "partial"):
                    with self.subTest(outcome=outcome):
                        request = _record_request(
                            repository,
                            caller_key=f"request-{outcome}",
                            correlation_key=f"correlation-{outcome}",
                        )
                        initial = repository.record_initial_receipt(
                            request.request_id,
                            f"initial-{outcome}",
                            outcome,
                            provider_request_id=f"provider-{outcome}",
                            before="before",
                            after="uncertain",
                            verification="not yet verified",
                        )
                        current = repository.get_action_request(request.request_id)
                        self.assertEqual(current.status, "reconciliation_required")
                        self.assertEqual(repository.list_receipts(request.request_id), (initial,))

                        replay = _record_request(
                            repository,
                            caller_key=f"request-{outcome}",
                            correlation_key=f"correlation-{outcome}",
                        )
                        self.assertEqual(replay.request_id, request.request_id)
                        self.assertEqual(len(repository.list_receipts(request.request_id)), 1)
                        with self.assertRaises(ledger.DomainConflict):
                            repository.record_initial_receipt(
                                request.request_id,
                                f"other-initial-{outcome}",
                                "failed",
                            )

                        resolved = repository.record_reconciliation_receipt(
                            request.request_id,
                            f"resolution-{outcome}",
                            "succeeded",
                            initial.receipt_id,
                            provider_request_id=f"provider-{outcome}",
                            after="verified-after-state",
                            verification="deterministic read-back succeeded",
                        )
                        self.assertTrue(resolved.reconciliation)
                        self.assertEqual(resolved.supersedes_receipt_id, initial.receipt_id)
                        self.assertEqual(
                            repository.get_action_request(request.request_id).status,
                            "recorded",
                        )
                        self.assertEqual(
                            repository.list_receipts(request.request_id),
                            (initial, resolved),
                        )
                        self.assertEqual(
                            repository.record_reconciliation_receipt(
                                request.request_id,
                                f"resolution-{outcome}",
                                "succeeded",
                                initial.receipt_id,
                                provider_request_id=f"provider-{outcome}",
                                after="verified-after-state",
                                verification="deterministic read-back succeeded",
                            ),
                            resolved,
                        )
                        with self.assertRaises(ledger.DomainConflict):
                            repository.record_reconciliation_receipt(
                                request.request_id,
                                f"resolution-{outcome}",
                                "failed",
                                initial.receipt_id,
                            )
                        with self.assertRaises(ledger.DomainConflict):
                            repository.record_reconciliation_receipt(
                                request.request_id,
                                f"second-resolution-{outcome}",
                                "failed",
                                resolved.receipt_id,
                            )

                for forbidden in ("dispatch", "execute", "retry", "run", "authorize"):
                    self.assertFalse(hasattr(repository, forbidden), forbidden)
                self.assertEqual(_table_count(store, "action_requests"), 2)
                self.assertEqual(_table_count(store, "action_receipts"), 4)
                repository.verify_integrity()

    def test_receipt_status_and_event_roll_back_together(self):
        class InjectedFailure(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                request = _record_request(repository)
                events_before = _table_count(store, "event_envelopes")
                with patch.object(
                    ledger.DomainLedgerRepository,
                    "_before_commit",
                    side_effect=InjectedFailure("receipt commit"),
                ):
                    with self.assertRaises(InjectedFailure):
                        repository.record_initial_receipt(
                            request.request_id,
                            "unknown-receipt",
                            "unknown",
                        )
                self.assertEqual(_table_count(store, "action_receipts"), 0)
                self.assertEqual(_table_count(store, "event_envelopes"), events_before)
                self.assertEqual(
                    repository.get_action_request(request.request_id).status,
                    "proposed",
                )
                repository.verify_integrity()

    def test_thread_convergence_creates_one_request_and_one_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                workers = 8
                barrier = threading.Barrier(workers)

                def create() -> str:
                    barrier.wait(timeout=10)
                    return _record_request(
                        repository,
                        caller_key="thread-shared",
                        correlation_key="thread-shared",
                    ).request_id

                with ThreadPoolExecutor(max_workers=workers) as executor:
                    request_ids = list(executor.map(lambda _item: create(), range(workers)))
                self.assertEqual(len(set(request_ids)), 1)
                self.assertEqual(_table_count(store, "action_requests"), 1)
                self.assertEqual(_table_count(store, "event_envelopes"), 1)
                repository.verify_integrity()

    def test_process_convergence_creates_one_request_and_one_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sidecar = root / "runtime" / "control_plane.sqlite3"
            store = _control_store(sidecar)
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            registry.register(
                "process-workspace",
                display_name="process",
                workspace_class="cyryx",
                active=True,
            )
            store.close()

            context = multiprocessing.get_context("spawn")
            gate = context.Event()
            results = context.Queue()
            processes = [
                context.Process(
                    target=_process_record_request,
                    args=(str(sidecar.parent), "process-workspace", gate, results),
                )
                for _ in range(2)
            ]
            for process in processes:
                process.start()
            ready = [results.get(timeout=30) for _ in processes]
            self.assertTrue(all(item[0] == "ready" for item in ready), ready)
            gate.set()
            completed = [results.get(timeout=30) for _ in processes]
            for process in processes:
                process.join(30)
                self.assertEqual(process.exitcode, 0)
            self.assertTrue(all(item[0] == "ok" for item in completed), completed)
            self.assertEqual(len({item[1] for item in completed}), 1)

            store = _control_store(sidecar)
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            repository = ledger.DomainLedgerRepository(
                registry,
                "process-workspace",
                enabled=True,
            ).initialize()
            try:
                self.assertEqual(_table_count(store, "action_requests"), 1)
                self.assertEqual(_table_count(store, "event_envelopes"), 1)
                repository.verify_integrity()
            finally:
                store.close()

    def test_public_recording_rejects_secret_canaries_without_partial_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                for index, canary in enumerate(
                    (
                        "Authorization: Bearer super-secret-value",
                        "api_key=sk-abcdefghijklmnop",
                        "refresh_token: ghp_abcdefghijklmnop",
                        "-----BEGIN PRIVATE KEY-----",
                    )
                ):
                    with self.subTest(canary=canary), self.assertRaises(
                        ledger.DomainContractError
                    ):
                        repository.record_action_request(
                            f"secret-{index}",
                            "secret-canary",
                            "test_connector",
                            "create_draft",
                            "target:test",
                            canary,
                        )
                self.assertEqual(_table_count(store, "action_requests"), 0)
                self.assertEqual(_table_count(store, "event_envelopes"), 0)
                self.assertEqual(_table_count(store, "projections"), 0)

    def test_direct_sql_tamper_fork_cycle_head_and_entity_drift_are_detected(self):
        mutations = (
            "event_hash",
            "middle_payload",
            "cycle_pointer",
            "tail_head",
            "entity_digest",
            "request_digest",
            "valid_sibling_fork",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                with _repository(Path(tmp)) as (repository, _registry, store, _path):
                    evidence = repository.record_evidence(
                        "chain-evidence",
                        "chain-correlation",
                        "observation",
                        "local:test",
                        "evidence content",
                        credibility_bp=8000,
                        freshness="current",
                    )
                    repository.record_claim(
                        "chain-claim",
                        "chain-correlation",
                        "evidence-backed statement",
                        (evidence.evidence_id,),
                        claim_kind="fact",
                        confidence_bp=8000,
                        verification_status="supported",
                    )
                    request = _record_request(
                        repository,
                        caller_key="chain-request",
                        correlation_key="chain-correlation",
                    )
                    repository.record_initial_receipt(
                        request.request_id,
                        "chain-receipt",
                        "unknown",
                    )
                    events = repository.list_events(evidence.correlation_id)
                    self.assertEqual(len(events), 4)
                    connection = store._require_connection()

                    if mutation == "event_hash":
                        connection.execute(
                            "UPDATE event_envelopes SET event_hash=? WHERE event_id=?",
                            ("f" * 64, events[0].event_id),
                        )
                    elif mutation == "middle_payload":
                        payload = connection.execute(
                            "SELECT payload_json FROM event_envelopes WHERE event_id=?",
                            (events[1].event_id,),
                        ).fetchone()[0]
                        connection.execute(
                            "UPDATE event_envelopes SET payload_json=? WHERE event_id=?",
                            (str(payload) + " ", events[1].event_id),
                        )
                    elif mutation == "cycle_pointer":
                        connection.execute(
                            "UPDATE event_envelopes SET previous_hash=? WHERE event_id=?",
                            (events[-1].event_hash, events[0].event_id),
                        )
                    elif mutation == "tail_head":
                        row = connection.execute(
                            "SELECT projection_id,payload_json FROM projections "
                            "WHERE workspace_id=? AND projection_type='m2a_event_chain_head'",
                            (repository.workspace_id,),
                        ).fetchone()
                        payload = json.loads(row[1])
                        payload["head_hash"] = "0" * 64
                        connection.execute(
                            "UPDATE projections SET payload_json=? WHERE projection_id=?",
                            (
                                json.dumps(
                                    payload,
                                    ensure_ascii=True,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                                row[0],
                            ),
                        )
                    elif mutation == "entity_digest":
                        connection.execute(
                            "UPDATE evidence_records SET content_sha256=? WHERE evidence_id=?",
                            ("0" * 64, evidence.evidence_id),
                        )
                    elif mutation == "request_digest":
                        connection.execute(
                            "UPDATE action_requests SET payload_sha256=? WHERE request_id=?",
                            ("0" * 64, request.request_id),
                        )
                    else:
                        parent = events[0]
                        template = events[1]
                        payload_text = connection.execute(
                            "SELECT payload_json FROM event_envelopes WHERE event_id=?",
                            (template.event_id,),
                        ).fetchone()[0]
                        created_at = (
                            datetime.fromisoformat(template.created_at)
                            + timedelta(microseconds=1)
                        ).isoformat()
                        event_id = ledger._event_identity(
                            repository.workspace_id,
                            template.mission_id,
                            template.correlation_id,
                            template.event_type,
                            payload_text,
                            parent.event_hash,
                            created_at,
                        )
                        event_hash = ledger._row_digest(
                            (
                                event_id,
                                repository.workspace_id,
                                template.mission_id,
                                template.correlation_id,
                                ledger.DOMAIN_CONTRACT_VERSION,
                                template.event_type,
                                payload_text,
                                parent.event_hash,
                                created_at,
                            )
                        )
                        connection.execute(
                            "INSERT INTO event_envelopes VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (
                                event_id,
                                repository.workspace_id,
                                template.mission_id,
                                template.correlation_id,
                                ledger.DOMAIN_CONTRACT_VERSION,
                                template.event_type,
                                payload_text,
                                parent.event_hash,
                                event_hash,
                                created_at,
                            ),
                        )

                    with self.assertRaises(ledger.DomainIntegrityError):
                        repository.verify_integrity()

    def test_shadow_operations_leave_mission_memory_and_tool_audit_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protected = {
                "mission": root / "protected" / "onyx_missions.sqlite3",
                "memory": root / "protected" / "onyx_memory.sqlite3",
                "audit": root / "protected" / "tool_audit.sqlite3",
            }
            protected["mission"].parent.mkdir(parents=True)
            for name, path in protected.items():
                path.write_bytes((f"immutable-{name}-bytes\0" * 5).encode("utf-8"))
            before = {name: _sha256(path) for name, path in protected.items()}

            with patch("core.missions.DEFAULT_DB", protected["mission"]), patch(
                "core.tool_audit.AUDIT_PATH", protected["audit"]
            ), _repository(root / "control") as (repository, _registry, _store, _path):
                evidence = repository.record_evidence(
                    "protected-evidence",
                    "protected-correlation",
                    "observation",
                    "local:test",
                    "safe evidence",
                )
                repository.record_claim(
                    "protected-claim",
                    "protected-correlation",
                    "safe statement",
                    (evidence.evidence_id,),
                )
                request = _record_request(
                    repository,
                    caller_key="protected-request",
                    correlation_key="protected-correlation",
                )
                repository.record_initial_receipt(
                    request.request_id,
                    "protected-receipt",
                    "simulated",
                )
                repository.verify_integrity()

            self.assertEqual(
                {name: _sha256(path) for name, path in protected.items()},
                before,
            )

    def test_claim_references_cannot_cross_mission_or_missionless_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                _insert_mission_context(store, "mission-alpha", repository.workspace_id)
                _insert_mission_context(store, "mission-beta", repository.workspace_id)
                evidence_alpha = repository.record_evidence(
                    "evidence-alpha",
                    "claim-scope",
                    "observation",
                    "local:alpha",
                    "alpha evidence",
                    mission_id="mission-alpha",
                )
                evidence_beta = repository.record_evidence(
                    "evidence-beta",
                    "claim-scope",
                    "observation",
                    "local:beta",
                    "beta evidence",
                    mission_id="mission-beta",
                )
                evidence_global = repository.record_evidence(
                    "evidence-global",
                    "claim-scope",
                    "observation",
                    "local:global",
                    "global evidence",
                )
                claim_alpha = repository.record_claim(
                    "claim-alpha",
                    "claim-scope",
                    "alpha claim",
                    (evidence_alpha.evidence_id,),
                    mission_id="mission-alpha",
                )
                claim_global = repository.record_claim(
                    "claim-global",
                    "claim-scope",
                    "global claim",
                    (evidence_global.evidence_id,),
                )

                attempts = (
                    ("beta-to-alpha", "mission-beta", evidence_beta.evidence_id, claim_alpha),
                    ("global-to-alpha", None, evidence_global.evidence_id, claim_alpha),
                    ("alpha-to-global", "mission-alpha", evidence_alpha.evidence_id, claim_global),
                )
                for relation in ("contradiction", "supersedes"):
                    for label, mission_id, evidence_id, referenced in attempts:
                        kwargs = (
                            {"contradiction_claim_ids": (referenced.claim_id,)}
                            if relation == "contradiction"
                            else {"supersedes_claim_id": referenced.claim_id}
                        )
                        with self.subTest(
                            relation=relation, label=label
                        ), self.assertRaises(ledger.DomainIsolationError):
                            repository.record_claim(
                                f"{relation}-{label}",
                                "claim-scope",
                                "cross-scope claim",
                                (evidence_id,),
                                mission_id=mission_id,
                                **kwargs,
                            )
                self.assertEqual(_table_count(store, "claims"), 2)
                repository.verify_integrity()

    def test_claim_reference_sql_mission_drift_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                _insert_mission_context(store, "mission-alpha", repository.workspace_id)
                _insert_mission_context(store, "mission-beta", repository.workspace_id)
                evidence = repository.record_evidence(
                    "drift-evidence",
                    "drift-correlation",
                    "observation",
                    "local:drift",
                    "drift evidence",
                    mission_id="mission-alpha",
                )
                base = repository.record_claim(
                    "drift-base",
                    "drift-correlation",
                    "base claim",
                    (evidence.evidence_id,),
                    mission_id="mission-alpha",
                )
                repository.record_claim(
                    "drift-dependent",
                    "drift-correlation",
                    "dependent claim",
                    (evidence.evidence_id,),
                    mission_id="mission-alpha",
                    contradiction_claim_ids=(base.claim_id,),
                )
                connection = store._require_connection()
                payload = json.loads(
                    connection.execute(
                        "SELECT payload_json FROM claims WHERE claim_id=?",
                        (base.claim_id,),
                    ).fetchone()[0]
                )
                payload["mission_id"] = "mission-beta"
                connection.execute(
                    "UPDATE claims SET payload_json=? WHERE claim_id=?",
                    (
                        json.dumps(
                            payload,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        base.claim_id,
                    ),
                )
                with self.assertRaises(ledger.DomainLedgerError):
                    repository.verify_integrity()

    def test_terminal_receipts_require_material_result_proof(self):
        invalid_cases = (
            ("succeeded-no-verification", "succeeded", {"after": "observed state"}),
            (
                "succeeded-no-observation",
                "succeeded",
                {"verification": "deterministic verification"},
            ),
            (
                "failed-no-error-class",
                "failed",
                {"verification": "deterministic failure proof"},
            ),
            ("failed-no-proof", "failed", {"error_class": "provider_error"}),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                for label, outcome, details in invalid_cases:
                    request = _record_request(
                        repository,
                        caller_key=f"request-{label}",
                        correlation_key=f"correlation-{label}",
                    )
                    with self.subTest(label=label), self.assertRaises(
                        ledger.DomainContractError
                    ):
                        repository.record_initial_receipt(
                            request.request_id,
                            f"receipt-{label}",
                            outcome,
                            **details,
                        )
                    self.assertEqual(repository.list_receipts(request.request_id), ())
                    self.assertEqual(
                        repository.get_action_request(request.request_id).status,
                        "proposed",
                    )

                valid_request = _record_request(
                    repository,
                    caller_key="request-proven-success",
                    correlation_key="correlation-proven-success",
                )
                valid = repository.record_initial_receipt(
                    valid_request.request_id,
                    "receipt-proven-success",
                    "succeeded",
                    after="observed state",
                    verification="deterministic verification",
                )
                self.assertEqual(valid.outcome, "succeeded")
                self.assertEqual(_table_count(store, "action_receipts"), 1)
                repository.verify_integrity()

    def test_tied_receipt_timestamps_follow_event_chain_not_receipt_id(self):
        fixed = "2026-07-14T12:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, _store, _path):
                with patch("core.domain_ledger._now", return_value=fixed):
                    request = _record_request(
                        repository,
                        caller_key="tied-request",
                        correlation_key="tied-correlation",
                    )
                    candidates = [f"receipt-key-{index}" for index in range(100)]
                    pair = next(
                        (first, second)
                        for first in candidates
                        for second in candidates
                        if first != second
                        and ledger._entity_id(
                            "receipt",
                            repository.workspace_id,
                            f"{request.request_id}:{first}",
                        )
                        > ledger._entity_id(
                            "receipt",
                            repository.workspace_id,
                            f"{request.request_id}:{second}",
                        )
                    )
                    initial = repository.record_initial_receipt(
                        request.request_id,
                        pair[0],
                        "unknown",
                    )
                    resolved = repository.record_reconciliation_receipt(
                        request.request_id,
                        pair[1],
                        "succeeded",
                        initial.receipt_id,
                        after="observed state",
                        verification="deterministic verification",
                    )
                self.assertEqual(initial.created_at, resolved.created_at)
                self.assertGreater(initial.receipt_id, resolved.receipt_id)
                self.assertEqual(
                    repository.list_receipts(request.request_id),
                    (initial, resolved),
                )
                repository.verify_integrity()

    def test_material_hashes_are_domain_separated_and_raw_byte_secrets_deny(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (repository, _registry, store, _path):
                bytes_record = repository.record_evidence(
                    "bytes-abc",
                    "material-domain",
                    "observation",
                    b"source",
                    b"abc",
                )
                text_record = repository.record_evidence(
                    "text-abc",
                    "material-domain",
                    "observation",
                    "source",
                    "abc",
                )
                invalid_byte_record = repository.record_evidence(
                    "bytes-ff",
                    "material-domain",
                    "observation",
                    b"source",
                    b"\xff",
                )
                hex_text_record = repository.record_evidence(
                    "text-ff",
                    "material-domain",
                    "observation",
                    "source",
                    "ff",
                )
                self.assertNotEqual(bytes_record.content_sha256, text_record.content_sha256)
                self.assertNotEqual(
                    invalid_byte_record.content_sha256,
                    hex_text_record.content_sha256,
                )
                replay = repository.record_evidence(
                    "replay-domain",
                    "material-domain",
                    "observation",
                    b"source",
                    b"abc",
                )
                with self.assertRaises(ledger.DomainConflict):
                    repository.record_evidence(
                        "replay-domain",
                        "material-domain",
                        "observation",
                        b"source",
                        "abc",
                    )
                self.assertEqual(repository.get_evidence(replay.evidence_id), replay)

                requests_before = _table_count(store, "action_requests")
                events_before = _table_count(store, "event_envelopes")
                with self.assertRaises(ledger.DomainContractError):
                    repository.record_action_request(
                        "raw-byte-secret",
                        "material-domain",
                        "test_connector",
                        "create_draft",
                        "target:test",
                        b"\xffAuthorization: Bearer raw-byte-secret-value",
                    )
                self.assertEqual(_table_count(store, "action_requests"), requests_before)
                self.assertEqual(_table_count(store, "event_envelopes"), events_before)
                repository.verify_integrity()

    def test_tampered_evidence_and_claim_replay_scope_fails_closed(self):
        cases = (
            ("evidence", "workspace"),
            ("evidence", "mission"),
            ("claim", "workspace"),
            ("claim", "mission"),
        )
        for entity, scope in cases:
            with self.subTest(entity=entity, scope=scope), tempfile.TemporaryDirectory() as tmp:
                with _repository(Path(tmp), "scope-workspace") as (
                    repository,
                    registry,
                    store,
                    _path,
                ):
                    registry.register(
                        "other-workspace",
                        display_name="other",
                        workspace_class="client",
                        active=True,
                    )
                    _insert_mission_context(store, "mission-alpha", repository.workspace_id)
                    _insert_mission_context(store, "mission-beta", repository.workspace_id)
                    evidence = repository.record_evidence(
                        "scope-evidence",
                        "scope-replay",
                        "observation",
                        "local:scope",
                        "scope evidence",
                        mission_id="mission-alpha",
                    )
                    claim = repository.record_claim(
                        "scope-claim",
                        "scope-replay",
                        "scope claim",
                        (evidence.evidence_id,),
                        mission_id="mission-alpha",
                    )
                    connection = store._require_connection()
                    if entity == "evidence" and scope == "workspace":
                        connection.execute(
                            "UPDATE evidence_records SET workspace_id=? WHERE evidence_id=?",
                            ("other-workspace", evidence.evidence_id),
                        )
                    elif entity == "evidence":
                        connection.execute(
                            "UPDATE evidence_records SET mission_id=? WHERE evidence_id=?",
                            ("mission-beta", evidence.evidence_id),
                        )
                    elif scope == "workspace":
                        connection.execute(
                            "UPDATE claims SET workspace_id=? WHERE claim_id=?",
                            ("other-workspace", claim.claim_id),
                        )
                    else:
                        payload = json.loads(
                            connection.execute(
                                "SELECT payload_json FROM claims WHERE claim_id=?",
                                (claim.claim_id,),
                            ).fetchone()[0]
                        )
                        payload["mission_id"] = "mission-beta"
                        connection.execute(
                            "UPDATE claims SET payload_json=? WHERE claim_id=?",
                            (
                                json.dumps(
                                    payload,
                                    ensure_ascii=True,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                                claim.claim_id,
                            ),
                        )

                    with self.assertRaises(ledger.DomainLedgerError):
                        if entity == "evidence":
                            repository.record_evidence(
                                "scope-evidence",
                                "scope-replay",
                                "observation",
                                "local:scope",
                                "scope evidence",
                                mission_id="mission-alpha",
                            )
                        else:
                            repository.record_claim(
                                "scope-claim",
                                "scope-replay",
                                "scope claim",
                                (evidence.evidence_id,),
                                mission_id="mission-alpha",
                            )

    def test_schema_stays_v2_with_exact_m1a_m1b_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _repository(Path(tmp)) as (_repository_value, _registry, store, _path):
                connection = store._require_connection()
                self.assertEqual(
                    int(connection.execute("PRAGMA user_version").fetchone()[0]),
                    SCHEMA_VERSION,
                )
                journal = connection.execute(
                    "SELECT migration_id,schema_from,schema_to,status "
                    "FROM migration_journal ORDER BY schema_from,schema_to"
                ).fetchall()
                self.assertEqual(
                    journal,
                    [
                        (MIGRATION_ID, 0, 1, "applied"),
                        (M1B_MIGRATION_ID, 1, 2, "applied"),
                    ],
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM legacy_backfill_candidates"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM backfill_runs").fetchone()[0],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
