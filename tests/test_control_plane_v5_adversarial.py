from __future__ import annotations

import sqlite3
import multiprocessing
import os
import time
import json
from pathlib import Path

import pytest

import core.control_plane_v5 as cp5
from core import tool_audit
from core.control_plane_v5 import (
    ControlPlaneV5Conflict,
    ControlPlaneV5ContractError,
    ControlPlaneV5IntegrityError,
    ControlPlaneV5IOError,
    ControlPlaneV5IsolationError,
    ControlPlaneV5Store,
    V4AuthorityStatus,
    V4MissionAuthority,
    stable_scope_key,
)
from p44_v5_support import (
    Authority,
    Vault,
    accept_test_audit,
    digest,
)


class FileVault:
    def __init__(self, path):
        self.path = Path(path)

    def get_bytes(self):
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None

    def set_bytes(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
        temporary.write_bytes(bytes(value))
        os.replace(temporary, self.path)

    def delete(self):
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


class DelayedSealVault(FileVault):
    def __init__(self, path, pending, release):
        super().__init__(path)
        self.pending = pending
        self.release = release
        self.saw_pending = False

    def set_bytes(self, value):
        decoded = json.loads(bytes(value).decode("ascii"))
        if decoded.get("contract") == "OnyxV5Head.v1":
            self.pending.set()
            if not self.release.wait(15):
                raise RuntimeError("pending seal release timed out")
        super().set_bytes(value)


def _cross_process_reservation_worker(
    database, key_path, state_path, pending_path, audit_path, ready, start, results
):
    import core.tool_audit as audit

    audit.AUDIT_PATH = Path(audit_path)
    def verifier(trace_id, event_hash):
        return audit.verify_audit_reference(trace_id=trace_id, event_hash=event_hash)

    def semantic_verifier(contract, event_hash):
        return audit.verify_semantic_tool_audit_reference(
            contract=contract, event_hash=event_hash
        )
    store = ControlPlaneV5Store(
        path=Path(database),
        source=Authority(),
        key_vault=FileVault(key_path),
        state_vault=FileVault(state_path),
        pending_vault=FileVault(pending_path),
        enabled=True,
        audit_reference_verifier=verifier,
        semantic_audit_verifier=semantic_verifier,
    ).initialize()
    ready.put("ready")
    start.wait(10)
    idempotency_key = stable_scope_key(
        workspace_id="workspace-a",
        mission_id="mission-a",
        operation="local_system_status",
        caller_key="cross-process",
    )
    scope = store.mission_scope(workspace_id="workspace-a", mission_id="mission-a")
    request_id = cp5.action_request_identity(idempotency_key)
    request_sha256 = cp5.action_request_contract_sha256(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request_id,
        correlation_id=scope.correlation_id,
        connector="local_mission_tools",
        operation="local_system_status",
        target="local-runtime",
        target_sha256=digest("local-runtime"),
        payload_sha256=digest("{}"),
        idempotency_key=idempotency_key,
        risk="low",
        approval_policy="shadow_only",
        dry_run=True,
        verification_plan_sha256=digest("runtime_status_observed"),
        source_context_sha256=scope.context_sha256,
    )
    lease = None
    for _attempt in range(20):
        try:
            lease = store.reserve_action_request(
                workspace_id="workspace-a",
                mission_id="mission-a",
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
            )
            break
        except ControlPlaneV5IntegrityError:
            time.sleep(0.05)
    if lease is None:
        results.put("integrity-timeout")
        return
    if not lease:
        results.put("wait")
        return
    candidate = cp5.ActionRequest(
        schema_version=cp5.RECORD_SCHEMA_VERSION,
        request_id=request_id,
        workspace_id="workspace-a",
        mission_id="mission-a",
        correlation_id=scope.correlation_id,
        connector="local_mission_tools",
        operation="local_system_status",
        target_sha256=digest("local-runtime"),
        payload_sha256=digest("{}"),
        idempotency_key=idempotency_key,
        risk="low",
        approval_policy="shadow_only",
        dry_run=True,
        audit_reference_sha256="0" * 64,
        verification_plan_sha256=digest("runtime_status_observed"),
        source_context_sha256=scope.context_sha256,
        created_at="2026-07-18T00:00:00+00:00",
        target="local-runtime",
    )
    reference = audit.append_semantic_tool_audit_reference(
        contract=cp5.action_audit_semantic_contract(candidate),
        reason="cross-process ownership test",
    )
    store.link_action_audit(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=lease.request_id,
        owner_id=lease.owner_id,
        audit_reference_sha256=reference.event_hash,
        request_sha256=request_sha256,
        idempotency_key=idempotency_key,
        connector="local_mission_tools",
        operation="local_system_status",
        target="local-runtime",
        target_sha256=digest("local-runtime"),
        payload_sha256=digest("{}"),
        risk="low",
        approval_policy="shadow_only",
        dry_run=True,
        source_context_sha256=scope.context_sha256,
        verification_plan_sha256=digest("runtime_status_observed"),
    )
    request = store.record_action_request(
        workspace_id="workspace-a",
        mission_id="mission-a",
        connector="local_mission_tools",
        operation="local_system_status",
        target="local-runtime",
        target_sha256=digest("local-runtime"),
        payload_sha256=digest("{}"),
        idempotency_key=idempotency_key,
        risk="low",
        approval_policy="shadow_only",
        dry_run=True,
        audit_reference_sha256=reference.event_hash,
        verification_plan_sha256=digest("runtime_status_observed"),
        reservation_owner_id=lease.owner_id,
    )
    store.mark_action_dispatch_unknown(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        owner_id=lease.owner_id,
    )
    results.put("dispatch")


def _pending_writer_worker(
    database, key_path, state_path, pending_path, pending, release, results
):
    store = ControlPlaneV5Store(
        path=Path(database),
        source=Authority(),
        key_vault=FileVault(key_path),
        state_vault=DelayedSealVault(state_path, pending, release),
        enabled=True,
        pending_vault=FileVault(pending_path),
        audit_reference_verifier=lambda _trace, _event: False,
    ).initialize()
    store.record_evidence(**evidence_arguments("cross-process-pending"))
    results.put("sealed")


def make_store(tmp_path, authority=None):
    key, state, pending = Vault(), Vault(), Vault()
    store = ControlPlaneV5Store(
        path=tmp_path / "v5.sqlite3",
        source=authority or Authority(),
        key_vault=key,
        state_vault=state,
        pending_vault=pending,
        enabled=True,
        audit_reference_verifier=accept_test_audit,
        semantic_audit_verifier=accept_test_audit,
    ).initialize()
    return store, key, state


class DriftingAuthority(Authority):
    def __init__(self):
        super().__init__()
        self.status_calls = 0

    def status(self):
        self.status_calls += 1
        # Initialization plus the first scope validation remain stable.  The
        # root changes only during the write-side precommit revalidation.
        if self.status_calls >= 6:
            self.root = digest("drifted-v4-root")
        return super().status()


class ReplacedAuthority(Authority):
    def __init__(self):
        super().__init__()
        self.replaced = False

    def status(self):
        status = super().status()
        if not self.replaced:
            return status
        return V4AuthorityStatus(
            "replacement-v4",
            4,
            status.schema_fingerprint,
            status.state_root,
            status.anchor_sequence,
        )


def evidence_arguments(caller_key="evidence"):
    return dict(
        workspace_id="workspace-a",
        mission_id="mission-a",
        source_kind="observation",
        source_identity_sha256=digest("source"),
        content_sha256=digest("content"),
        artifact_id=None,
        credibility_bp=10000,
        freshness="current",
        access_license_sha256=digest("internal"),
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key=caller_key,
    )


def request_arguments(
    *,
    caller_key="request",
    payload="{}",
    approval_id=None,
    workspace_id="workspace-a",
    mission_id="mission-a",
):
    return dict(
        workspace_id=workspace_id,
        mission_id=mission_id,
        connector="local_mission_tools",
        operation="local_system_status",
        target="local-runtime",
        target_sha256=digest("local-runtime"),
        payload_sha256=digest(payload),
        idempotency_key=stable_scope_key(
            workspace_id=workspace_id,
            mission_id=mission_id,
            operation="local_system_status",
            caller_key=caller_key,
        ),
        risk="low",
        approval_policy="shadow_only",
        dry_run=True,
        audit_reference_sha256=digest("audit"),
        verification_plan_sha256=digest("runtime_status_observed"),
        reservation_owner_id="owner-pending",
        approval_id=approval_id,
    )


def prepare_request(store, arguments):
    request_id = cp5.action_request_identity(arguments["idempotency_key"])
    scope = store.mission_scope(
        workspace_id=arguments["workspace_id"], mission_id=arguments["mission_id"]
    )
    request_sha256 = cp5.action_request_contract_sha256(
        workspace_id=arguments["workspace_id"],
        mission_id=arguments["mission_id"],
        request_id=request_id,
        correlation_id=scope.correlation_id,
        connector=arguments["connector"],
        operation=arguments["operation"],
        target=arguments["target"],
        target_sha256=arguments["target_sha256"],
        payload_sha256=arguments["payload_sha256"],
        idempotency_key=arguments["idempotency_key"],
        risk=arguments["risk"],
        approval_policy=arguments["approval_policy"],
        dry_run=arguments["dry_run"],
        verification_plan_sha256=arguments["verification_plan_sha256"],
        source_context_sha256=scope.context_sha256,
        approval_id=arguments.get("approval_id"),
    )
    lease = store.reserve_action_request(
        workspace_id=arguments["workspace_id"],
        mission_id=arguments["mission_id"],
        idempotency_key=arguments["idempotency_key"],
        request_sha256=request_sha256,
    )
    store.link_action_audit(
        workspace_id=arguments["workspace_id"],
        mission_id=arguments["mission_id"],
        request_id=request_id,
        owner_id=lease.owner_id,
        audit_reference_sha256=arguments["audit_reference_sha256"],
        request_sha256=request_sha256,
        idempotency_key=arguments["idempotency_key"],
        connector=arguments["connector"],
        operation=arguments["operation"],
        target=arguments["target"],
        target_sha256=arguments["target_sha256"],
        payload_sha256=arguments["payload_sha256"],
        risk=arguments["risk"],
        approval_policy=arguments["approval_policy"],
        dry_run=arguments["dry_run"],
        source_context_sha256=scope.context_sha256,
        verification_plan_sha256=arguments["verification_plan_sha256"],
        approval_id=arguments.get("approval_id"),
    )
    arguments["reservation_owner_id"] = lease.owner_id
    return arguments


def dispatched_request(store, *, caller_key: str):
    arguments = prepare_request(store, request_arguments(caller_key=caller_key))
    request = store.record_action_request(**arguments)
    store.mark_action_dispatch_unknown(
        workspace_id=request.workspace_id,
        mission_id=request.mission_id,
        request_id=request.request_id,
        owner_id=arguments["reservation_owner_id"],
    )
    return request, arguments


def provider_binding(request) -> str:
    return cp5.provider_request_binding_sha256(
        request.request_id, f"local-system-status:{request.request_id}"
    )


def positive_receipt_bindings(store, request, *, suffix: str):
    content = digest(f"output-{suffix}")
    artifact = store.record_artifact(
        workspace_id=request.workspace_id,
        mission_id=request.mission_id,
        request_id=request.request_id,
        content_sha256=content,
        relative_path=f"{content[:2]}/{content}",
        byte_length=12,
        media_type="application/json",
        metadata_sha256=digest(f"metadata-{suffix}"),
        caller_key=f"artifact-{suffix}",
        source_provenance_sha256=digest("provider-free-local"),
        artifact_created_at="2026-07-17T12:00:00+00:00",
        manifest_sha256=digest(f"manifest-{suffix}"),
    )
    notes = "cyryx-internal"
    evidence = store.record_evidence(
        workspace_id=request.workspace_id,
        mission_id=request.mission_id,
        source_kind="tool_output",
        source_identity_sha256=digest("local-system-status"),
        content_sha256=content,
        artifact_id=artifact.artifact_id,
        credibility_bp=10000,
        freshness="current",
        access_license_sha256=digest(notes),
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key=f"evidence-{suffix}",
        title="Local system status",
        uri_or_file_ref=f"artifact:{artifact.artifact_id}",
        publisher_or_owner="Cyryx Labs Onyx local runtime",
        access_and_license_notes=notes,
    )
    text = f"observed-{suffix}"
    claim = store.record_claim(
        workspace_id=request.workspace_id,
        mission_id=request.mission_id,
        claim_kind="fact",
        statement_sha256=digest(text),
        evidence_ids=(evidence.evidence_id,),
        confidence_bp=10000,
        verification_status="single_source",
        valid_until=None,
        contradiction_claim_ids=(),
        caller_key=f"claim-{suffix}",
        text=text,
        verified_at="2026-07-17T12:00:00+00:00",
        valid_from="2026-07-17T12:00:00+00:00",
    )
    return (
        artifact,
        store.get_evidence(
            workspace_id=request.workspace_id,
            mission_id=request.mission_id,
            evidence_id=evidence.evidence_id,
        ),
        claim,
    )


def test_v4_drift_between_validation_and_commit_rolls_back(tmp_path):
    authority = DriftingAuthority()
    store, _key, _state = make_store(tmp_path, authority)
    before = store.status().commit_sequence
    # Reset so the deterministic drift lands inside this write, not status().
    authority.status_calls = 1
    authority.root = digest("v4-root")
    with pytest.raises(ControlPlaneV5Conflict, match="drift"):
        store.record_evidence(**evidence_arguments("drift"))
    assert store.status().commit_sequence == before
    assert store.list_evidence(workspace_id="workspace-a", mission_id="mission-a") == ()


def test_v4_database_replacement_is_rejected(tmp_path):
    authority = ReplacedAuthority()
    store, _key, _state = make_store(tmp_path, authority)
    authority.replaced = True
    with pytest.raises(ControlPlaneV5IsolationError, match="replaced"):
        store.record_evidence(**evidence_arguments("replacement"))


@pytest.mark.parametrize(
    "tamper",
    [
        lambda connection: connection.execute("PRAGMA user_version=999"),
        lambda connection: connection.execute(
            "CREATE TABLE attacker_extra(value TEXT)"
        ),
        lambda connection: connection.execute("DROP INDEX idx_v5_event_tail"),
    ],
)
def test_unknown_extra_or_missing_schema_object_fails_without_repair(tmp_path, tamper):
    store, key, state = make_store(tmp_path)
    connection = sqlite3.connect(store.path)
    try:
        tamper(connection)
        connection.commit()
    finally:
        connection.close()
    before = store.path.read_bytes()
    reopened = ControlPlaneV5Store(
        path=store.path,
        source=Authority(),
        key_vault=key,
        state_vault=state,
        pending_vault=store.pending_vault,
        enabled=True,
    )
    with pytest.raises(ControlPlaneV5IntegrityError):
        reopened.initialize()
    assert store.path.read_bytes() == before


def test_vault_head_tamper_and_commit_tail_deletion_fail_closed(tmp_path):
    store, key, state = make_store(tmp_path)
    store.record_evidence(**evidence_arguments("head-tamper"))
    state.value = (
        b'{"contract":"OnyxV5Head.v1","sequence":999,"commit_hmac":"'
        + b"0" * 64
        + b'"}'
    )
    with pytest.raises(ControlPlaneV5IntegrityError, match="head vault"):
        store.status()

    # Restore the real head then remove the latest commit after dropping only
    # the immutable guards in this isolated adversarial fixture.
    connection = sqlite3.connect(store.path)
    try:
        latest = connection.execute(
            "SELECT sequence,commit_hmac FROM ledger_commits ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        state.set_bytes(
            cp5._canonical(
                {
                    "contract": "OnyxV5Head.v1",
                    "sequence": latest[0],
                    "commit_hmac": latest[1],
                }
            ).encode("ascii")
        )
        connection.execute("DROP TRIGGER deny_v5_ledger_entries_delete")
        connection.execute("DROP TRIGGER deny_v5_ledger_commits_delete")
        connection.execute(
            "DELETE FROM ledger_entries WHERE commit_sequence=?", (latest[0],)
        )
        connection.execute("DELETE FROM ledger_commits WHERE sequence=?", (latest[0],))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ControlPlaneV5IntegrityError):
        ControlPlaneV5Store(
            path=store.path,
            source=Authority(),
            key_vault=key,
            state_vault=state,
            pending_vault=store.pending_vault,
            enabled=True,
        ).initialize()


def test_missing_or_restored_head_and_replaced_key_fail_closed(tmp_path):
    store, key, state = make_store(tmp_path)
    bootstrap_head = bytes(state.value)
    store.record_evidence(**evidence_arguments("operational-head"))
    operational_head = bytes(state.value)

    state.value = None
    with pytest.raises(ControlPlaneV5IntegrityError, match="head vault is missing"):
        ControlPlaneV5Store(
            path=store.path,
            source=Authority(),
            key_vault=key,
            state_vault=state,
            pending_vault=store.pending_vault,
            enabled=True,
        ).initialize()

    state.value = bootstrap_head
    with pytest.raises(ControlPlaneV5IntegrityError, match="diverge"):
        ControlPlaneV5Store(
            path=store.path,
            source=Authority(),
            key_vault=key,
            state_vault=state,
            pending_vault=store.pending_vault,
            enabled=True,
        ).initialize()

    state.value = operational_head
    key.value = b"x" * 32
    with pytest.raises(ControlPlaneV5IntegrityError, match="authentication"):
        ControlPlaneV5Store(
            path=store.path,
            source=Authority(),
            key_vault=key,
            state_vault=state,
            pending_vault=store.pending_vault,
            enabled=True,
        ).initialize()


def test_mac_valid_database_and_database_key_restore_cannot_launder_head(tmp_path):
    store, key, state = make_store(tmp_path)
    backup = tmp_path / "valid-old.sqlite3"
    with sqlite3.connect(store.path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    old_key = bytes(key.value)
    store.record_evidence(**evidence_arguments("newer-state"))
    current_head = bytes(state.value)

    with sqlite3.connect(backup) as source, sqlite3.connect(store.path) as target:
        source.backup(target)
    key.value = old_key
    with pytest.raises(ControlPlaneV5IntegrityError, match="before write"):
        store.record_evidence(**evidence_arguments("rollback-launder"))
    assert state.value == current_head


def test_only_explicit_pending_marker_recovers_committed_unsealed_write(tmp_path):
    store, key, state = make_store(tmp_path)
    pending_vault = store.pending_vault
    previous = json.loads(state.value.decode("ascii"))
    store.record_evidence(**evidence_arguments("pending-recovery"))
    current = json.loads(state.value.decode("ascii"))
    state.set_bytes(store._head_bytes(previous["sequence"], previous["commit_hmac"]))
    pending_vault.set_bytes(
        store._pending_head_bytes(
            (previous["sequence"], previous["commit_hmac"]),
            (current["sequence"], current["commit_hmac"]),
        )
    )
    reopened = ControlPlaneV5Store(
        path=store.path,
        source=Authority(),
        key_vault=key,
        state_vault=state,
        pending_vault=pending_vault,
        enabled=True,
        audit_reference_verifier=accept_test_audit,
        semantic_audit_verifier=accept_test_audit,
    ).initialize()
    assert reopened.status().commit_sequence == current["sequence"]
    assert json.loads(state.value.decode("ascii"))["contract"] == "OnyxV5Head.v1"
    assert pending_vault.get_bytes() is None


def test_pending_vault_must_be_a_distinct_explicit_authority(tmp_path):
    shared = Vault()
    with pytest.raises(ControlPlaneV5IntegrityError, match="must differ"):
        ControlPlaneV5Store(
            path=tmp_path / "same-vault.sqlite3",
            source=Authority(),
            key_vault=Vault(),
            state_vault=shared,
            pending_vault=shared,
            enabled=True,
        ).initialize()
    with pytest.raises(ControlPlaneV5IntegrityError, match="pending vault is required"):
        ControlPlaneV5Store(
            path=tmp_path / "missing-pending.sqlite3",
            source=Authority(),
            key_vault=Vault(),
            state_vault=Vault(),
            enabled=True,
        ).initialize()


def test_uncommitted_or_replayed_pending_marker_never_repairs_database(tmp_path):
    store, key, state = make_store(tmp_path)
    pending_vault = store.pending_vault
    current = json.loads(state.value.decode("ascii"))
    pending_vault.set_bytes(
        store._pending_head_bytes(
            (current["sequence"], current["commit_hmac"]),
            (current["sequence"] + 1, digest("never-committed")),
        )
    )
    with pytest.raises(ControlPlaneV5IntegrityError, match="diverge"):
        ControlPlaneV5Store(
            path=store.path,
            source=Authority(),
            key_vault=key,
            state_vault=state,
            pending_vault=pending_vault,
            enabled=True,
        ).initialize()
    assert pending_vault.get_bytes() is not None


def test_r3_candidate_without_separate_pending_protocol_fails_closed(tmp_path):
    store, key, state = make_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TRIGGER deny_v5_schema_metadata_delete")
        connection.execute("DELETE FROM schema_metadata WHERE key='head_protocol'")
        connection.commit()
    with pytest.raises(ControlPlaneV5IntegrityError, match="metadata shape"):
        ControlPlaneV5Store(
            path=store.path,
            source=Authority(),
            key_vault=key,
            state_vault=state,
            pending_vault=store.pending_vault,
            enabled=True,
        ).initialize()


def test_valid_pending_marker_replay_rejects_restored_or_advanced_database(tmp_path):
    restored_dir = tmp_path / "restored"
    restored_dir.mkdir()
    store, key, state = make_store(restored_dir)
    pending_vault = store.pending_vault
    previous = json.loads(state.value.decode("ascii"))
    backup = restored_dir / "previous.sqlite3"
    with sqlite3.connect(store.path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    store.record_evidence(**evidence_arguments("marker-next"))
    current = json.loads(state.value.decode("ascii"))
    marker = store._pending_head_bytes(
        (previous["sequence"], previous["commit_hmac"]),
        (current["sequence"], current["commit_hmac"]),
    )
    with sqlite3.connect(backup) as source, sqlite3.connect(store.path) as target:
        source.backup(target)
    pending_vault.set_bytes(marker)
    with pytest.raises(ControlPlaneV5IntegrityError, match="diverge"):
        ControlPlaneV5Store(
            path=store.path,
            source=Authority(),
            key_vault=key,
            state_vault=state,
            pending_vault=pending_vault,
            enabled=True,
        ).initialize()

    advanced_dir = tmp_path / "advanced"
    advanced_dir.mkdir()
    advanced, advanced_key, advanced_state = make_store(advanced_dir)
    advanced_pending = advanced.pending_vault
    old = json.loads(advanced_state.value.decode("ascii"))
    advanced.record_evidence(**evidence_arguments("marker-middle"))
    middle = json.loads(advanced_state.value.decode("ascii"))
    old_marker = advanced._pending_head_bytes(
        (old["sequence"], old["commit_hmac"]),
        (middle["sequence"], middle["commit_hmac"]),
    )
    advanced.record_evidence(**evidence_arguments("marker-advanced"))
    advanced_pending.set_bytes(old_marker)
    with pytest.raises(ControlPlaneV5IntegrityError, match="diverge"):
        ControlPlaneV5Store(
            path=advanced.path,
            source=Authority(),
            key_vault=advanced_key,
            state_vault=advanced_state,
            pending_vault=advanced_pending,
            enabled=True,
        ).initialize()


def test_real_v4_adapter_scope_anchor_drift_and_replacement(tmp_path, monkeypatch):
    from test_mission_context_v4 import _fixture, _mission, _spec

    (tmp_path / "accepted").mkdir()
    *_prefix, v4, owner, missions, contexts = _fixture(
        tmp_path / "accepted", monkeypatch
    )
    mission = _mission(missions, "V5 real adapter")
    context = contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="v5-real-adapter-init",
    )
    adapter = V4MissionAuthority(v4, owner)
    status = adapter.status()
    assert status.schema_version == 4 and status.anchor_sequence >= 1
    key, state, pending_vault = Vault(), Vault(), Vault()
    store = ControlPlaneV5Store(
        path=tmp_path / "v5-real.sqlite3",
        source=adapter,
        key_vault=key,
        state_vault=state,
        pending_vault=pending_vault,
        enabled=True,
        audit_reference_verifier=accept_test_audit,
        semantic_audit_verifier=accept_test_audit,
    ).initialize()
    scope = store.mission_scope(workspace_id="alpha", mission_id=mission.id)
    assert scope.context_revision == context.revision
    assert scope.context_sha256 == context.revision_sha256
    assert scope.source_state_root == adapter.status().state_root

    other_mission = _mission(missions, "V4 authority drift")
    contexts.initialize_context(
        "alpha",
        other_mission.id,
        _spec("drift"),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="v5-real-adapter-drift",
    )
    drifted = store.mission_scope(workspace_id="alpha", mission_id=mission.id)
    assert drifted.context_revision == 0
    assert drifted.source_state_root == adapter.status().state_root

    (tmp_path / "replacement").mkdir()
    *_other, replacement, replacement_owner, _missions2, _contexts2 = _fixture(
        tmp_path / "replacement", monkeypatch
    )
    replacement_mission = _mission(_missions2, "Replacement authority")
    _contexts2.initialize_context(
        "alpha",
        replacement_mission.id,
        _spec("replacement"),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="v5-replacement-anchor",
    )
    store.source = V4MissionAuthority(replacement, replacement_owner)
    with pytest.raises(ControlPlaneV5IsolationError, match="replaced"):
        store.status()


def test_two_processes_persist_exactly_one_dispatch_owner(tmp_path):
    database = tmp_path / "cross-process.sqlite3"
    key_path = tmp_path / "vault" / "key.bin"
    state_path = tmp_path / "vault" / "state.bin"
    pending_path = tmp_path / "vault" / "pending.bin"
    audit_path = tmp_path / "audit" / "audit.sqlite3"
    key_vault, state_vault = FileVault(key_path), FileVault(state_path)
    ControlPlaneV5Store(
        path=database,
        source=Authority(),
        key_vault=key_vault,
        state_vault=state_vault,
        pending_vault=FileVault(pending_path),
        enabled=True,
        audit_reference_verifier=lambda _trace, _event: False,
    ).initialize()

    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    results = context.Queue()
    start = context.Event()
    arguments = (
        str(database),
        str(key_path),
        str(state_path),
        str(pending_path),
        str(audit_path),
        ready,
        start,
        results,
    )
    processes = [
        context.Process(target=_cross_process_reservation_worker, args=arguments)
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    assert [ready.get(timeout=20) for _ in processes] == ["ready", "ready"]
    start.set()
    outcomes = [results.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert outcomes.count("dispatch") == 1
    assert outcomes.count("wait") == 1


def test_cross_process_reader_fails_closed_during_pending_then_retries(tmp_path):
    database = tmp_path / "pending-reader.sqlite3"
    key_path = tmp_path / "vault" / "key.bin"
    state_path = tmp_path / "vault" / "state.bin"
    pending_path = tmp_path / "vault" / "pending.bin"
    store = ControlPlaneV5Store(
        path=database,
        source=Authority(),
        key_vault=FileVault(key_path),
        state_vault=FileVault(state_path),
        pending_vault=FileVault(pending_path),
        enabled=True,
        audit_reference_verifier=lambda _trace, _event: False,
    ).initialize()
    context = multiprocessing.get_context("spawn")
    pending, release, results = context.Event(), context.Event(), context.Queue()
    process = context.Process(
        target=_pending_writer_worker,
        args=(
            str(database),
            str(key_path),
            str(state_path),
            str(pending_path),
            pending,
            release,
            results,
        ),
    )
    process.start()
    assert pending.wait(20)
    vault_before = state_path.read_bytes()
    with sqlite3.connect(database) as connection:
        sequence_before = connection.execute(
            "SELECT MAX(sequence) FROM ledger_commits"
        ).fetchone()[0]
    with pytest.raises(ControlPlaneV5IntegrityError, match="pending write"):
        store.status()
    assert state_path.read_bytes() == vault_before
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT MAX(sequence) FROM ledger_commits").fetchone()[0]
            == sequence_before
        )
    release.set()
    assert results.get(timeout=20) == "sealed"
    process.join(timeout=20)
    assert process.exitcode == 0
    assert store.status().commit_sequence == sequence_before


def test_same_idempotency_key_with_changed_payload_conflicts(tmp_path):
    store, _key, _state = make_store(tmp_path)
    original = prepare_request(store, request_arguments(caller_key="stable"))
    store.record_action_request(**original)
    changed = dict(original)
    changed["payload_sha256"] = digest("changed")
    with pytest.raises(ControlPlaneV5Conflict, match="changed input"):
        store.record_action_request(**changed)


def test_receipt_transition_contract_rejects_illegal_states(tmp_path):
    store, _key, _state = make_store(tmp_path)
    arguments = prepare_request(store, request_arguments())
    request = store.record_action_request(**arguments)
    base = dict(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        provider_request_sha256=provider_binding(request),
        output_sha256=digest("output"),
        verification_sha256=digest("verified"),
        postcondition_sha256=digest("observed"),
        error_class="",
        supersedes_receipt_id=None,
        reconciliation=False,
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key="receipt",
        provider_request_id=request.request_id,
        provider_request_ref=f"local-system-status:{request.request_id}",
        started_at="2026-07-17T11:59:59+00:00",
    )
    with pytest.raises(ControlPlaneV5ContractError, match="cannot have succeeded"):
        store.record_action_receipt(outcome="succeeded", **base)
    store.mark_action_dispatch_unknown(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        owner_id=arguments["reservation_owner_id"],
    )
    unknown = dict(base)
    unknown["error_class"] = "observation_interrupted"
    unknown["verification_sha256"] = digest("")
    first = store.record_action_receipt(outcome="unknown", **unknown)
    branch = dict(base)
    branch.update(
        outcome="failed",
        verification_sha256=digest(""),
        error_class="provider_reconciled_failure",
        supersedes_receipt_id=first.receipt_id,
        reconciliation=True,
        caller_key="reconciled",
        completed_at="2026-07-17T12:01:00+00:00",
    )
    store.record_action_receipt(**branch)
    branch["caller_key"] = "second-branch"
    with pytest.raises(ControlPlaneV5Conflict, match="tail"):
        store.record_action_receipt(**branch)


def test_receipt_requires_dispatch_barrier_and_never_fabricates_predispatch(
    tmp_path,
):
    store, _key, _state = make_store(tmp_path)
    arguments = prepare_request(store, request_arguments(caller_key="no-dispatch"))
    request = store.record_action_request(**arguments)
    with pytest.raises(ControlPlaneV5Conflict, match="dispatch_unknown"):
        store.record_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a",
            request_id=request.request_id,
            outcome="unknown",
            provider_request_sha256=provider_binding(request),
            output_sha256=digest("none"),
            verification_sha256=digest(""),
            postcondition_sha256=digest("none"),
            error_class="observation_interrupted",
            supersedes_receipt_id=None,
            reconciliation=False,
            observed_at="2026-07-17T12:00:00+00:00",
            caller_key="must-not-exist",
            provider_request_id=request.request_id,
            provider_request_ref=f"local-system-status:{request.request_id}",
            started_at="2026-07-17T11:59:59+00:00",
        )
    assert (
        store.latest_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a",
            request_id=request.request_id,
        )
        is None
    )


def test_positive_receipt_requires_request_bound_artifact_evidence_and_claim(
    tmp_path,
):
    store, _key, _state = make_store(tmp_path)
    request, _arguments = dispatched_request(store, caller_key="missing-bindings")
    with pytest.raises(ControlPlaneV5Conflict, match="record is unknown"):
        store.record_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a",
            request_id=request.request_id,
            outcome="simulated",
            provider_request_sha256=provider_binding(request),
            output_sha256=digest("output"),
            verification_sha256=digest("verification"),
            postcondition_sha256=digest("postcondition"),
            error_class="",
            supersedes_receipt_id=None,
            reconciliation=False,
            observed_at="2026-07-17T12:00:01+00:00",
            caller_key="unbound-positive",
            provider_request_id=request.request_id,
            provider_request_ref=f"local-system-status:{request.request_id}",
            started_at="2026-07-17T12:00:00+00:00",
            completed_at="2026-07-17T12:00:01+00:00",
            output_ref="artifact:artifact-missing",
            verification_ref="evidence:evidence-missing",
            after_state_ref="claim:claim-missing",
        )
    assert (
        store.latest_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a",
            request_id=request.request_id,
        )
        is None
    )


def test_receipt_verification_digest_is_bound_on_write_read_and_full_audit(
    tmp_path, monkeypatch
):
    store, _key, _state = make_store(tmp_path / "direct")
    request, _arguments = dispatched_request(
        store, caller_key="verification-binding-direct"
    )
    artifact, evidence, claim = positive_receipt_bindings(
        store, request, suffix="verification-direct"
    )
    common = dict(
        workspace_id=request.workspace_id,
        mission_id=request.mission_id,
        request_id=request.request_id,
        outcome="simulated",
        provider_request_sha256=provider_binding(request),
        output_sha256=artifact.content_sha256,
        postcondition_sha256=claim.statement_sha256,
        error_class="",
        supersedes_receipt_id=None,
        reconciliation=False,
        observed_at="2026-07-17T12:00:01+00:00",
        provider_request_id=request.request_id,
        provider_request_ref=f"local-system-status:{request.request_id}",
        started_at="2026-07-17T12:00:00+00:00",
        completed_at="2026-07-17T12:00:01+00:00",
        output_ref=f"artifact:{artifact.artifact_id}",
        verification_ref=f"evidence:{evidence.evidence_id}",
        after_state_ref=f"claim:{claim.claim_id}",
    )
    with pytest.raises(ControlPlaneV5IntegrityError, match="evidence-bound"):
        store.record_action_receipt(
            **common,
            verification_sha256=digest("unrelated-verification"),
            caller_key="verification-mismatch",
        )
    receipt = store.record_action_receipt(
        **common,
        verification_sha256=cp5.evidence_verification_sha256(evidence),
        caller_key="verification-exact",
    )
    assert (
        store.get_action_receipt(
            workspace_id=request.workspace_id,
            mission_id=request.mission_id,
            receipt_id=receipt.receipt_id,
        )
        == receipt
    )
    store.verify_integrity(full=True)

    tampered, _key, _state = make_store(tmp_path / "authenticated-tamper")
    tampered_request, _arguments = dispatched_request(
        tampered, caller_key="verification-binding-tamper"
    )
    artifact, evidence, claim = positive_receipt_bindings(
        tampered, tampered_request, suffix="verification-tamper"
    )
    original = tampered._verify_receipt_bindings
    monkeypatch.setattr(tampered, "_verify_receipt_bindings", lambda *_args: None)
    forged = tampered.record_action_receipt(
        workspace_id=tampered_request.workspace_id,
        mission_id=tampered_request.mission_id,
        request_id=tampered_request.request_id,
        outcome="simulated",
        provider_request_sha256=provider_binding(tampered_request),
        output_sha256=artifact.content_sha256,
        verification_sha256=digest("authenticated-but-unrelated"),
        postcondition_sha256=claim.statement_sha256,
        error_class="",
        supersedes_receipt_id=None,
        reconciliation=False,
        observed_at="2026-07-17T12:00:01+00:00",
        caller_key="verification-authenticated-tamper",
        provider_request_id=tampered_request.request_id,
        provider_request_ref=(f"local-system-status:{tampered_request.request_id}"),
        started_at="2026-07-17T12:00:00+00:00",
        completed_at="2026-07-17T12:00:01+00:00",
        output_ref=f"artifact:{artifact.artifact_id}",
        verification_ref=f"evidence:{evidence.evidence_id}",
        after_state_ref=f"claim:{claim.claim_id}",
    )
    monkeypatch.setattr(tampered, "_verify_receipt_bindings", original)
    with pytest.raises(ControlPlaneV5IntegrityError, match="evidence-bound"):
        tampered.get_action_receipt(
            workspace_id=tampered_request.workspace_id,
            mission_id=tampered_request.mission_id,
            receipt_id=forged.receipt_id,
        )
    with pytest.raises(ControlPlaneV5IntegrityError, match="evidence-bound"):
        tampered.verify_integrity(full=True)


def test_unknown_receipt_preserves_queryable_nonsecret_provider_reference(
    tmp_path,
):
    store, _key, _state = make_store(tmp_path)
    request, _arguments = dispatched_request(store, caller_key="unknown-provider")
    common = dict(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        outcome="unknown",
        provider_request_sha256=provider_binding(request),
        output_sha256=digest("none"),
        verification_sha256=digest(""),
        postcondition_sha256=digest("none"),
        error_class="observation_interrupted",
        supersedes_receipt_id=None,
        reconciliation=False,
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key="unknown-provider-receipt",
        provider_request_id=request.request_id,
        provider_request_ref=f"local-system-status:{request.request_id}",
        started_at="2026-07-17T11:59:59+00:00",
    )
    receipt = store.record_action_receipt(**common)
    assert receipt.provider_request_id == request.request_id
    assert receipt.provider_request_ref == f"local-system-status:{request.request_id}"
    assert receipt.completed_at is None
    assert store.reconcile_required(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
    )

    second, _arguments = dispatched_request(store, caller_key="secret-provider")
    secret = dict(common)
    secret.update(
        request_id=second.request_id,
        caller_key="secret-provider-receipt",
        provider_request_id=second.request_id,
        provider_request_ref="token:abcdefghijklmnopqrstuvwxyz",
    )
    with pytest.raises(ControlPlaneV5ContractError):
        store.record_action_receipt(**secret)


@pytest.mark.parametrize(
    "reconciliation_created_at",
    ["2026-01-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00"],
)
def test_receipt_tail_uses_supersedes_graph_not_wall_clock(
    tmp_path,
    monkeypatch,
    reconciliation_created_at,
):
    store, _key, _state = make_store(tmp_path)
    request, _arguments = dispatched_request(store, caller_key="clock-independent")
    monkeypatch.setattr(cp5, "_now", lambda: "2027-01-01T00:00:00+00:00")
    first = store.record_action_receipt(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        outcome="unknown",
        provider_request_sha256=provider_binding(request),
        output_sha256=digest("none"),
        verification_sha256=digest(""),
        postcondition_sha256=digest("none"),
        error_class="observation_interrupted",
        supersedes_receipt_id=None,
        reconciliation=False,
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key="clock-root",
        provider_request_id=request.request_id,
        provider_request_ref=f"local-system-status:{request.request_id}",
        started_at="2026-07-17T11:59:59+00:00",
    )
    monkeypatch.setattr(cp5, "_now", lambda: reconciliation_created_at)
    final = store.record_action_receipt(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        outcome="failed",
        provider_request_sha256=provider_binding(request),
        output_sha256=digest("none"),
        verification_sha256=digest(""),
        postcondition_sha256=digest("none"),
        error_class="provider_reconciled_failure",
        supersedes_receipt_id=first.receipt_id,
        reconciliation=True,
        observed_at="2026-07-17T12:01:00+00:00",
        caller_key="clock-tail",
        provider_request_id=request.request_id,
        provider_request_ref=f"local-system-status:{request.request_id}",
        started_at="2026-07-17T11:59:59+00:00",
        completed_at="2026-07-17T12:01:00+00:00",
    )
    assert (
        store.latest_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a",
            request_id=request.request_id,
        ).receipt_id
        == final.receipt_id
    )
    assert not store.reconcile_required(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
    )


@pytest.mark.parametrize(
    ("parents", "message"),
    [
        ({"root": None, "left": "root", "right": "root"}, "fork"),
        ({"left": "right", "right": "left"}, "exactly one root"),
        ({"root": None, "left": "right", "right": "left"}, "cycle"),
        ({"left": None, "right": None}, "exactly one root"),
    ],
)
def test_receipt_graph_rejects_forks_cycles_and_multiple_tails(
    tmp_path,
    monkeypatch,
    parents,
    message,
):
    store, _key, _state = make_store(tmp_path)
    request_id = "request-graph"
    records = {}
    for name, parent in parents.items():
        receipt_id = f"receipt-{name}"
        records[receipt_id] = cp5.asdict(
            cp5.ActionReceipt(
                schema_version=cp5.RECORD_SCHEMA_VERSION,
                receipt_id=receipt_id,
                request_id=request_id,
                workspace_id="workspace-a",
                mission_id="mission-a",
                correlation_id="correlation-a",
                outcome="unknown",
                provider_request_sha256=cp5.provider_request_binding_sha256(
                    request_id, f"local-system-status:{request_id}"
                ),
                output_sha256=digest("none"),
                verification_sha256=digest(""),
                postcondition_sha256=digest("none"),
                error_class="observation_interrupted",
                supersedes_receipt_id=(
                    f"receipt-{parent}" if parent is not None else None
                ),
                reconciliation=parent is not None,
                source_context_sha256=digest("context-workspace-a"),
                observed_at="2026-07-17T12:00:00+00:00",
                created_at="2026-07-17T12:00:00+00:00",
                provider_request_id=request_id,
                provider_request_ref=f"local-system-status:{request_id}",
                started_at="2026-07-17T11:59:59+00:00",
            )
        )

    class GraphConnection:
        def execute(self, _sql, _parameters):
            return type(
                "Rows",
                (),
                {"fetchall": lambda self: [(receipt_id,) for receipt_id in records]},
            )()

    monkeypatch.setattr(
        store,
        "_verified_record",
        lambda _connection, _table, _column, entity_id: dict(records[entity_id]),
    )
    with pytest.raises(ControlPlaneV5IntegrityError, match=message):
        store._receipt_chain(GraphConnection(), request_id)


def test_complete_typed_evidence_claim_and_authenticated_inverse_projection(
    tmp_path,
):
    store, _key, _state = make_store(tmp_path)
    evidence = store.record_evidence(
        **evidence_arguments("typed-evidence"),
        title="Official Onyx runtime observation",
        uri_or_file_ref="local-runtime:status",
        publisher_or_owner="Cyryx Labs",
        published_at="2026-07-17T11:59:00+00:00",
        access_and_license_notes="internal",
    )
    assert evidence.title == "Official Onyx runtime observation"
    assert evidence.publisher_or_owner == "Cyryx Labs"
    assert evidence.published_at == "2026-07-17T11:59:00+00:00"
    claim = store.record_claim(
        workspace_id="workspace-a",
        mission_id="mission-a",
        claim_kind="fact",
        statement_sha256=digest("typed-claim"),
        evidence_ids=(evidence.evidence_id,),
        confidence_bp=9000,
        verification_status="corroborated",
        valid_until=None,
        contradiction_claim_ids=(),
        caller_key="typed-claim",
        text="typed-claim",
        verified_at="2026-07-17T12:00:00+00:00",
        valid_from="2026-07-17T11:59:00+00:00",
    )
    projected = store.get_evidence(
        workspace_id="workspace-a",
        mission_id="mission-a",
        evidence_id=evidence.evidence_id,
    )
    assert projected.claim_ids == (claim.claim_id,)
    assert store.list_evidence(workspace_id="workspace-a", mission_id="mission-a")[
        0
    ].claim_ids == (claim.claim_id,)
    assert claim.verification_status == "corroborated"
    assert claim.verified_at == "2026-07-17T12:00:00+00:00"
    assert claim.valid_from == "2026-07-17T11:59:00+00:00"
    store.verify_integrity(full=True)


def test_v3_recoverable_contract_fields_round_trip_and_legacy_rows_do_not_invent(
    tmp_path,
):
    store, _key, _state = make_store(tmp_path)
    notes = "Internal provider-free observation; no external redistribution."
    evidence_args = evidence_arguments("recoverable-fields")
    evidence_args["access_license_sha256"] = digest(notes)
    evidence = store.record_evidence(
        **evidence_args,
        title="Recoverable contract evidence",
        access_and_license_notes=notes,
    )
    claim_text = "The local runtime observation is current."
    claim = store.record_claim(
        workspace_id="workspace-a",
        mission_id="mission-a",
        claim_kind="fact",
        statement_sha256=digest(claim_text),
        evidence_ids=(evidence.evidence_id,),
        confidence_bp=9000,
        verification_status="single_source",
        valid_until=None,
        contradiction_claim_ids=(),
        caller_key="recoverable-claim",
        text=claim_text,
    )
    arguments = prepare_request(
        store,
        request_arguments(
            caller_key="recoverable-request", approval_id="approval-shadow-1"
        ),
    )
    request = store.record_action_request(**arguments)
    assert (
        store.get_evidence(
            workspace_id="workspace-a",
            mission_id="mission-a",
            evidence_id=evidence.evidence_id,
        ).access_and_license_notes
        == notes
    )
    assert (
        store.get_claim(
            workspace_id="workspace-a",
            mission_id="mission-a",
            claim_id=claim.claim_id,
        ).text
        == claim_text
    )
    projected_request = store.get_action_request(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
    )
    assert projected_request.target == "local-runtime"
    assert projected_request.approval_id == "approval-shadow-1"

    legacy_evidence = cp5.asdict(evidence)
    legacy_evidence["schema_version"] = 2
    legacy_evidence.pop("access_and_license_notes")
    assert store._evidence_from_value(legacy_evidence).access_and_license_notes is None
    legacy_claim = cp5.asdict(claim)
    legacy_claim["schema_version"] = 2
    legacy_claim.pop("text")
    assert store._claim_from_value(legacy_claim).text is None
    legacy_request = cp5.asdict(request)
    legacy_request["schema_version"] = 2
    legacy_request.pop("target")
    legacy_request.pop("approval_id")
    hydrated_request = store._request_from_value(legacy_request)
    assert hydrated_request.target is None
    assert hydrated_request.approval_id is None
    assert cp5.action_audit_semantic_contract(hydrated_request)["contract"] == (
        "OnyxToolAuditSemantic.v2"
    )
    store.verify_integrity(full=True)


def test_provider_identity_and_started_at_are_immutable_across_restart(tmp_path):
    store, _key, _state = make_store(tmp_path)
    request, _arguments = dispatched_request(store, caller_key="provider-lineage")
    provider_id = request.request_id
    provider_ref = f"local-system-status:{request.request_id}"
    first = store.record_action_receipt(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        outcome="unknown",
        provider_request_sha256=cp5.provider_request_binding_sha256(
            provider_id, provider_ref
        ),
        output_sha256=digest("none"),
        verification_sha256=digest(""),
        postcondition_sha256=digest("none"),
        error_class="observation_interrupted",
        supersedes_receipt_id=None,
        reconciliation=False,
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key="provider-lineage-root",
        provider_request_id=provider_id,
        provider_request_ref=provider_ref,
        started_at="2026-07-17T11:59:59+00:00",
    )
    reopened = ControlPlaneV5Store(
        path=store.path,
        source=Authority(),
        key_vault=store.key_vault,
        state_vault=store.state_vault,
        pending_vault=store.pending_vault,
        enabled=True,
        semantic_audit_verifier=accept_test_audit,
    ).initialize()
    common = dict(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        outcome="failed",
        output_sha256=digest("none"),
        verification_sha256=digest(""),
        postcondition_sha256=digest("none"),
        error_class="provider_reconciled_failure",
        supersedes_receipt_id=first.receipt_id,
        reconciliation=True,
        observed_at="2026-07-17T12:01:00+00:00",
        completed_at="2026-07-17T12:01:00+00:00",
    )
    provider_b_id = "provider-b-request"
    provider_b_ref = "local-system-status:provider-b-request"
    with pytest.raises(ControlPlaneV5Conflict, match="external-operation identity"):
        reopened.record_action_receipt(
            **common,
            caller_key="provider-substitution",
            provider_request_id=provider_b_id,
            provider_request_ref=provider_b_ref,
            provider_request_sha256=cp5.provider_request_binding_sha256(
                provider_b_id, provider_b_ref
            ),
            started_at="2026-07-17T11:59:59+00:00",
        )
    with pytest.raises(ControlPlaneV5Conflict, match="external-operation identity"):
        reopened.record_action_receipt(
            **common,
            caller_key="started-at-substitution",
            provider_request_id=provider_id,
            provider_request_ref=provider_ref,
            provider_request_sha256=cp5.provider_request_binding_sha256(
                provider_id, provider_ref
            ),
            started_at="2026-07-17T12:00:00+00:00",
        )
    tampered = cp5.asdict(first)
    tampered["provider_request_id"] = provider_b_id
    with pytest.raises(ControlPlaneV5IntegrityError, match="binding"):
        reopened._receipt_from_value(tampered)
    assert (
        reopened.get_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a",
            receipt_id=first.receipt_id,
        )
        == first
    )
    reopened.verify_integrity(full=True)


class SameWorkspaceMultiMissionAuthority(Authority):
    def read_scope(self, workspace_id, mission_id):
        if workspace_id != "workspace-a" or mission_id not in {
            "mission-a",
            "mission-a-alt",
        }:
            raise RuntimeError("cross-scope")
        return cp5.MissionScope(
            workspace_id,
            mission_id,
            f"correlation-{mission_id}",
            3,
            digest(f"context-{workspace_id}-{mission_id}"),
            self.root,
        )


def test_workspace_scoped_getters_cannot_read_another_mission(tmp_path):
    store, _key, _state = make_store(
        tmp_path, authority=SameWorkspaceMultiMissionAuthority()
    )
    evidence = store.record_evidence(**evidence_arguments("mission-a-evidence"))
    claim_text = "Mission A only."
    claim = store.record_claim(
        workspace_id="workspace-a",
        mission_id="mission-a",
        claim_kind="fact",
        statement_sha256=digest(claim_text),
        evidence_ids=(evidence.evidence_id,),
        confidence_bp=10000,
        verification_status="single_source",
        valid_until=None,
        contradiction_claim_ids=(),
        caller_key="mission-a-claim",
        text=claim_text,
    )
    arguments = prepare_request(
        store, request_arguments(caller_key="mission-a-request")
    )
    request = store.record_action_request(**arguments)
    store.mark_action_dispatch_unknown(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        owner_id=arguments["reservation_owner_id"],
    )
    provider_ref = f"local-system-status:{request.request_id}"
    receipt = store.record_action_receipt(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        outcome="unknown",
        provider_request_sha256=cp5.provider_request_binding_sha256(
            request.request_id, provider_ref
        ),
        output_sha256=digest("none"),
        verification_sha256=digest(""),
        postcondition_sha256=digest("none"),
        error_class="observation_interrupted",
        supersedes_receipt_id=None,
        reconciliation=False,
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key="mission-a-receipt",
        provider_request_id=request.request_id,
        provider_request_ref=provider_ref,
        started_at="2026-07-17T11:59:59+00:00",
    )
    with pytest.raises(ControlPlaneV5IsolationError, match="another mission"):
        store.get_evidence(
            workspace_id="workspace-a",
            mission_id="mission-a-alt",
            evidence_id=evidence.evidence_id,
        )
    with pytest.raises(ControlPlaneV5IsolationError, match="another mission"):
        store.get_claim(
            workspace_id="workspace-a",
            mission_id="mission-a-alt",
            claim_id=claim.claim_id,
        )
    with pytest.raises(ControlPlaneV5IsolationError, match="another mission"):
        store.get_action_request(
            workspace_id="workspace-a",
            mission_id="mission-a-alt",
            request_id=request.request_id,
        )
    with pytest.raises(ControlPlaneV5IsolationError, match="another mission"):
        store.find_action_request(
            workspace_id="workspace-a",
            mission_id="mission-a-alt",
            request_id=request.request_id,
        )
    with pytest.raises(ControlPlaneV5IsolationError, match="another mission"):
        store.get_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a-alt",
            receipt_id=receipt.receipt_id,
        )
    with pytest.raises(ControlPlaneV5IsolationError, match="another mission"):
        store.latest_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a-alt",
            request_id=request.request_id,
        )


def test_bounded_pages_and_full_cold_audit(tmp_path):
    store, _key, _state = make_store(tmp_path)
    for index in range(12):
        store.record_evidence(**evidence_arguments(f"bounded-{index}"))
    first = store.list_evidence(
        workspace_id="workspace-a", mission_id="mission-a", limit=5
    )
    second = store.list_evidence(
        workspace_id="workspace-a",
        mission_id="mission-a",
        after_id=first[-1].evidence_id,
        limit=5,
    )
    assert len(first) == len(second) == 5
    assert set(first).isdisjoint(second)
    assert store.verify_integrity(full=True).commit_sequence == 13


def test_failed_fresh_schema_create_removes_database_and_new_key(tmp_path, monkeypatch):
    path = tmp_path / "failed.sqlite3"
    key, state, pending_vault = Vault(), Vault(), Vault()
    monkeypatch.setattr(cp5, "_SCHEMA", (*cp5._SCHEMA, "THIS IS NOT SQL"))
    with pytest.raises(sqlite3.Error):
        ControlPlaneV5Store(
            path=path,
            source=Authority(),
            key_vault=key,
            state_vault=state,
            pending_vault=pending_vault,
            enabled=True,
        ).initialize()
    assert not path.exists()
    assert key.value is None
    assert state.value is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("caller_key", "sk-abcdefghijklmnop"),
        ("connector", "sk-abcdefghijklmnop"),
        ("operation", "sk-abcdefghijklmnop"),
    ],
)
def test_secret_shaped_identifiers_are_rejected(tmp_path, field, value):
    store, _key, _state = make_store(tmp_path)
    arguments = request_arguments(caller_key="safe")
    arguments[field] = value
    with pytest.raises(ControlPlaneV5ContractError, match="secret-shaped"):
        if field == "caller_key":
            stable_scope_key(
                workspace_id="workspace-a",
                mission_id="mission-a",
                operation="local_system_status",
                caller_key=value,
            )
        else:
            store.record_action_request(**arguments)


_RECOVERABLE_SECRET_CANARIES = (
    pytest.param(
        "password=synthetic-canary-123456789",
        "password:synthetic-canary-123456789",
        id="password",
    ),
    pytest.param(
        "api_key: synthetic-canary-123456789",
        "api-key:synthetic-canary-123456789",
        id="api-key",
    ),
    pytest.param(
        "Bearer synthetic-canary-123456789",
        "bearer-synthetic-canary-123456789",
        id="bearer",
    ),
    pytest.param(
        "AKIAIOSFODNN7EXAMPLE",
        "AKIAIOSFODNN7EXAMPLE",
        id="aws-access-key",
    ),
    pytest.param(
        "ghp_0123456789AbCdEfGhIjKlMnOp",
        "ghp_0123456789AbCdEfGhIjKlMnOp",
        id="github-pat",
    ),
    pytest.param(
        "xoxb-123456789012-123456789012-AbCdEfGhIjKlMnOp",
        "xoxb-123456789012-123456789012-AbCdEfGhIjKlMnOp",
        id="slack-token",
    ),
    pytest.param(
        "glpat-0123456789AbCdEfGhIj",
        "glpat-0123456789AbCdEfGhIj",
        id="gitlab-pat",
    ),
    pytest.param(
        "sk_live_0123456789AbCdEfGhIjKlMn",
        "sk_live_0123456789AbCdEfGhIjKlMn",
        id="stripe-live-key",
    ),
    pytest.param(
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        id="jwt",
    ),
    pytest.param(
        "aB3cD4eF5gH6iJ7kL8mN9pQ0rS1tU2vW",
        "aB3cD4eF5gH6iJ7kL8mN9pQ0rS1tU2vW",
        id="high-entropy",
    ),
)


_RECOVERABLE_PROSE_CONTROLS = (
    pytest.param(
        "The password and API key must never be stored in durable prose.",
        "approval-security-review-20260719",
        id="credential-policy-prose",
    ),
    pytest.param(
        "AWS access keys, GitHub PATs, Slack tokens, and JWTs are prohibited.",
        "approval-provider-policy-20260719",
        id="provider-policy-prose",
    ),
    pytest.param(
        "A high-entropy credential should be referenced by its vault identifier only.",
        "approval-vault-reference-20260719",
        id="entropy-policy-prose",
    ),
)


def _semantic_audit_contract(*, target: str, approval_id: str | None):
    return {
        "contract": "OnyxToolAuditSemantic.v3",
        "request": {
            "approval_policy": "shadow_only",
            "connector": "local_mission_tools",
            "correlation_id": "correlation-a",
            "dry_run": True,
            "idempotency_key": "onyx:v5:" + digest("semantic-audit"),
            "mission_id": "mission-a",
            "operation": "local_system_status",
            "payload_sha256": digest("{}"),
            "request_id": "request-semantic-audit",
            "request_sha256": digest("request-semantic-audit"),
            "risk": "low",
            "schema_version": 3,
            "source_context_sha256": digest("context-a"),
            "target": target,
            "target_sha256": digest(target),
            "workspace_id": "workspace-a",
            "approval_id": approval_id,
        },
        "authorization": {
            "principal": "local-owner",
            "profile": "p4.4-shadow",
            "tool": "local_mission_tools",
            "action": "local_system_status",
            "decision": "allowed",
            "outcome": "decision",
        },
    }


@pytest.mark.parametrize("canary,approval_canary", _RECOVERABLE_SECRET_CANARIES)
@pytest.mark.parametrize("field", ("target", "approval_id"))
def test_semantic_audit_rejects_secret_inputs_on_write_and_full_audit(
    tmp_path, monkeypatch, canary, approval_canary, field
):
    tool_audit.AUDIT_PATH = tmp_path / "tool-audit.sqlite3"
    contract = _semantic_audit_contract(
        target=canary if field == "target" else "local-runtime",
        approval_id=approval_canary if field == "approval_id" else None,
    )
    with pytest.raises(
        tool_audit.AuditIntegrityError, match="secret|recoverable|approval"
    ):
        tool_audit.append_semantic_tool_audit_reference(
            contract=contract, reason="secret boundary write test"
        )
    assert not tool_audit.AUDIT_PATH.exists()

    original = tool_audit._semantic_contract
    original_contains_secret = tool_audit.contains_secret
    monkeypatch.setattr(tool_audit, "_semantic_contract", lambda value: value)
    monkeypatch.setattr(tool_audit, "contains_secret", lambda *_values: False)
    tool_audit.append_semantic_tool_audit_reference(
        contract=contract, reason="authenticated secret fixture"
    )
    monkeypatch.setattr(tool_audit, "_semantic_contract", original)
    monkeypatch.setattr(tool_audit, "contains_secret", original_contains_secret)
    with pytest.raises(
        tool_audit.AuditIntegrityError, match="secret|recoverable|approval"
    ):
        tool_audit.verify_audit()


@pytest.mark.parametrize("prose,approval_id", _RECOVERABLE_PROSE_CONTROLS)
def test_semantic_audit_persists_and_full_audits_safe_prose(
    tmp_path, prose, approval_id
):
    tool_audit.AUDIT_PATH = tmp_path / "safe-tool-audit.sqlite3"
    reference = tool_audit.append_semantic_tool_audit_reference(
        contract=_semantic_audit_contract(target=prose, approval_id=approval_id),
        reason="ordinary non-secret prose control",
    )
    count, head = tool_audit.verify_audit()
    assert count == 1
    assert head == reference.event_hash


@pytest.mark.parametrize(
    "field",
    (
        "approval_policy",
        "connector",
        "correlation_id",
        "idempotency_key",
        "mission_id",
        "operation",
        "request_id",
        "risk",
        "workspace_id",
    ),
)
def test_semantic_audit_rejects_secret_in_every_free_request_string_and_full_audit(
    tmp_path, monkeypatch, field
):
    tool_audit.AUDIT_PATH = tmp_path / f"semantic-{field}.sqlite3"
    contract = _semantic_audit_contract(target="local-runtime", approval_id=None)
    contract["request"][field] = "AKIAIOSFODNN7EXAMPLE"
    with pytest.raises(tool_audit.AuditIntegrityError, match="secret"):
        tool_audit.append_semantic_tool_audit_reference(
            contract=contract, reason="free string secret boundary"
        )

    original = tool_audit._semantic_contract
    original_contains_secret = tool_audit.contains_secret
    monkeypatch.setattr(tool_audit, "_semantic_contract", lambda value: value)
    monkeypatch.setattr(tool_audit, "contains_secret", lambda *_values: False)
    tool_audit.append_semantic_tool_audit_reference(
        contract=contract, reason="authenticated free string fixture"
    )
    monkeypatch.setattr(tool_audit, "_semantic_contract", original)
    monkeypatch.setattr(tool_audit, "contains_secret", original_contains_secret)
    with pytest.raises(tool_audit.AuditIntegrityError, match="secret"):
        tool_audit.verify_audit()


@pytest.mark.parametrize("canary,approval_canary", _RECOVERABLE_SECRET_CANARIES)
def test_semantic_audit_reason_rejects_secrets_on_write_and_full_audit(
    tmp_path, monkeypatch, canary, approval_canary
):
    del approval_canary
    tool_audit.AUDIT_PATH = tmp_path / "semantic-reason.sqlite3"
    contract = _semantic_audit_contract(target="local-runtime", approval_id=None)
    with pytest.raises(tool_audit.AuditIntegrityError, match="reason"):
        tool_audit.append_semantic_tool_audit_reference(
            contract=contract, reason=canary
        )
    original_contains_secret = tool_audit.contains_secret
    monkeypatch.setattr(tool_audit, "contains_secret", lambda *_values: False)
    tool_audit.append_semantic_tool_audit_reference(contract=contract, reason=canary)
    monkeypatch.setattr(tool_audit, "contains_secret", original_contains_secret)
    with pytest.raises(tool_audit.AuditIntegrityError, match="secret"):
        tool_audit.verify_audit()


@pytest.mark.parametrize("canary,approval_canary", _RECOVERABLE_SECRET_CANARIES)
def test_recoverable_contract_fields_reject_credential_canaries_on_write(
    tmp_path, canary, approval_canary
):
    store, _key, _state = make_store(tmp_path)
    evidence_args = evidence_arguments("secret-notes")
    evidence_args.update(
        access_license_sha256=digest(canary),
        access_and_license_notes=canary,
    )
    with pytest.raises(ControlPlaneV5ContractError, match="secret material"):
        store.record_evidence(**evidence_args)

    evidence = store.record_evidence(**evidence_arguments("safe-evidence"))
    with pytest.raises(ControlPlaneV5ContractError, match="secret material"):
        store.record_claim(
            workspace_id="workspace-a",
            mission_id="mission-a",
            claim_kind="fact",
            statement_sha256=digest(canary),
            evidence_ids=(evidence.evidence_id,),
            confidence_bp=10000,
            verification_status="single_source",
            valid_until=None,
            contradiction_claim_ids=(),
            caller_key="secret-claim",
            text=canary,
        )

    request_args = request_arguments(caller_key="secret-target")
    request_args["target"] = canary
    request_args["target_sha256"] = digest(canary)
    with pytest.raises(ControlPlaneV5ContractError, match="secret material"):
        prepare_request(store, request_args)

    approval_args = request_arguments(
        caller_key="secret-approval",
        approval_id=approval_canary,
    )
    with pytest.raises(ControlPlaneV5ContractError, match="secret"):
        prepare_request(store, approval_args)

    request, _arguments = dispatched_request(
        store, caller_key="secret-provider-reference"
    )
    for provider_id, provider_ref in (
        (approval_canary, f"local-system-status:{request.request_id}"),
        (request.request_id, approval_canary),
    ):
        with pytest.raises(ControlPlaneV5ContractError, match="secret"):
            store.record_action_receipt(
                workspace_id="workspace-a",
                mission_id="mission-a",
                request_id=request.request_id,
                outcome="unknown",
                provider_request_sha256=digest("untrusted-provider-binding"),
                output_sha256=digest(""),
                verification_sha256=digest(""),
                postcondition_sha256=digest(""),
                error_class="observation_interrupted",
                supersedes_receipt_id=None,
                reconciliation=False,
                observed_at="2026-07-17T12:00:00+00:00",
                caller_key="secret-provider-receipt",
                provider_request_id=provider_id,
                provider_request_ref=provider_ref,
            )


@pytest.mark.parametrize("prose,approval_id", _RECOVERABLE_PROSE_CONTROLS)
def test_recoverable_contract_fields_persist_ordinary_non_secret_prose(
    tmp_path, prose, approval_id
):
    store, _key, _state = make_store(tmp_path)
    evidence_args = evidence_arguments("safe-prose-evidence")
    evidence_args.update(
        access_license_sha256=digest(prose),
        access_and_license_notes=prose,
    )
    evidence = store.record_evidence(**evidence_args)
    claim = store.record_claim(
        workspace_id="workspace-a",
        mission_id="mission-a",
        claim_kind="fact",
        statement_sha256=digest(prose),
        evidence_ids=(evidence.evidence_id,),
        confidence_bp=10000,
        verification_status="single_source",
        valid_until=None,
        contradiction_claim_ids=(),
        caller_key="safe-prose-claim",
        text=prose,
    )
    request_args = request_arguments(
        caller_key="safe-prose-request", approval_id=approval_id
    )
    request_args["target"] = prose
    request_args["target_sha256"] = digest(prose)
    request = store.record_action_request(**prepare_request(store, request_args))

    assert (
        store.get_evidence(
            workspace_id="workspace-a",
            mission_id="mission-a",
            evidence_id=evidence.evidence_id,
        ).access_and_license_notes
        == prose
    )
    assert (
        store.get_claim(
            workspace_id="workspace-a",
            mission_id="mission-a",
            claim_id=claim.claim_id,
        ).text
        == prose
    )
    persisted_request = store.get_action_request(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
    )
    assert persisted_request.target == prose
    assert persisted_request.approval_id == approval_id
    store.mark_action_dispatch_unknown(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        owner_id=request_args["reservation_owner_id"],
    )
    provider_id = f"provider-{approval_id}"
    provider_ref = f"local-system-status:{approval_id}"
    receipt = store.record_action_receipt(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        outcome="unknown",
        provider_request_sha256=cp5.provider_request_binding_sha256(
            provider_id, provider_ref
        ),
        output_sha256=digest(""),
        verification_sha256=digest(""),
        postcondition_sha256=digest(""),
        error_class="observation_interrupted",
        supersedes_receipt_id=None,
        reconciliation=False,
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key="safe-provider-receipt",
        provider_request_id=provider_id,
        provider_request_ref=provider_ref,
    )
    assert receipt.provider_request_id == provider_id
    assert receipt.provider_request_ref == provider_ref
    store.verify_integrity(full=True)


@pytest.mark.parametrize("canary,approval_canary", _RECOVERABLE_SECRET_CANARIES)
@pytest.mark.parametrize(
    "record_kind",
    ("evidence", "claim", "request", "approval", "provider_id", "provider_ref"),
)
def test_full_audit_rejects_authenticated_v3_secret_contract_text(
    tmp_path, monkeypatch, record_kind, canary, approval_canary
):
    store, _key, _state = make_store(tmp_path)
    original = cp5._recoverable_contract_text
    original_id = cp5._recoverable_contract_id
    original_opaque = cp5._opaque_reference
    original_reject = cp5._reject_secret

    def permissive(value, _label, *, optional=False, max_length=1024):
        del max_length
        if optional and value is None:
            return None
        return str(value)

    monkeypatch.setattr(cp5, "_recoverable_contract_text", permissive)
    monkeypatch.setattr(
        cp5, "_recoverable_contract_id", lambda value, _label: str(value)
    )
    monkeypatch.setattr(
        cp5,
        "_opaque_reference",
        lambda value, _label, *, optional=False: (
            None if optional and value is None else str(value)
        ),
    )
    monkeypatch.setattr(cp5, "_reject_secret", lambda _value, _label: None)
    if record_kind == "evidence":
        arguments = evidence_arguments("legacy-secret-evidence")
        arguments.update(
            access_license_sha256=digest(canary),
            access_and_license_notes=canary,
        )
        store.record_evidence(**arguments)
    elif record_kind == "claim":
        evidence = store.record_evidence(
            **evidence_arguments("legacy-secret-claim-evidence")
        )
        store.record_claim(
            workspace_id="workspace-a",
            mission_id="mission-a",
            claim_kind="fact",
            statement_sha256=digest(canary),
            evidence_ids=(evidence.evidence_id,),
            confidence_bp=10000,
            verification_status="single_source",
            valid_until=None,
            contradiction_claim_ids=(),
            caller_key="legacy-secret-claim",
            text=canary,
        )
    elif record_kind == "request":
        arguments = request_arguments(caller_key="legacy-secret-request")
        arguments["target"] = canary
        arguments["target_sha256"] = digest(canary)
        store.record_action_request(**prepare_request(store, arguments))
    elif record_kind == "approval":
        arguments = request_arguments(
            caller_key="legacy-secret-approval",
            approval_id=approval_canary,
        )
        store.record_action_request(**prepare_request(store, arguments))
    else:
        request, _arguments = dispatched_request(
            store, caller_key=f"legacy-secret-{record_kind}"
        )
        provider_id = (
            approval_canary if record_kind == "provider_id" else request.request_id
        )
        provider_ref = (
            approval_canary
            if record_kind == "provider_ref"
            else f"local-system-status:{request.request_id}"
        )
        store.record_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a",
            request_id=request.request_id,
            outcome="unknown",
            provider_request_sha256=cp5.provider_request_binding_sha256(
                provider_id, provider_ref
            ),
            output_sha256=digest(""),
            verification_sha256=digest(""),
            postcondition_sha256=digest(""),
            error_class="observation_interrupted",
            supersedes_receipt_id=None,
            reconciliation=False,
            observed_at="2026-07-17T12:00:00+00:00",
            caller_key=f"legacy-secret-{record_kind}-receipt",
            provider_request_id=provider_id,
            provider_request_ref=provider_ref,
        )
    monkeypatch.setattr(cp5, "_recoverable_contract_text", original)
    monkeypatch.setattr(cp5, "_recoverable_contract_id", original_id)
    monkeypatch.setattr(cp5, "_opaque_reference", original_opaque)
    monkeypatch.setattr(cp5, "_reject_secret", original_reject)

    with pytest.raises(ControlPlaneV5IntegrityError, match="policy"):
        store.verify_integrity(full=True)


class _CleanupFaultConnection:
    def __init__(self, connection, *, fail_rollback=False, fail_close=False):
        self._connection = connection
        self._fail_rollback = fail_rollback
        self._fail_close = fail_close

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def rollback(self):
        self._connection.rollback()
        if self._fail_rollback:
            raise RuntimeError("injected rollback cleanup failure")

    def close(self):
        self._connection.close()
        if self._fail_close:
            raise RuntimeError("injected close cleanup failure")


class _SyntheticCancellation(BaseException):
    pass


def test_reader_close_failure_preserves_cancellation_identity_and_releases_lock(
    tmp_path, monkeypatch
):
    store, _key, _state = make_store(tmp_path)
    original_connect = cp5._connect
    primary = _SyntheticCancellation("reader cancellation")

    def faulty_connect(path, *, readonly=False):
        return _CleanupFaultConnection(
            original_connect(path, readonly=readonly), fail_close=True
        )

    monkeypatch.setattr(cp5, "_connect", faulty_connect)
    with pytest.raises(_SyntheticCancellation) as caught:
        with store._reader():
            raise primary
    assert caught.value is primary
    monkeypatch.setattr(cp5, "_connect", original_connect)
    assert store.verify_integrity().commit_sequence == 1


def test_reader_close_failure_without_primary_is_typed_and_releases_lock(
    tmp_path, monkeypatch
):
    store, _key, _state = make_store(tmp_path)
    original_connect = cp5._connect

    def faulty_connect(path, *, readonly=False):
        return _CleanupFaultConnection(
            original_connect(path, readonly=readonly), fail_close=True
        )

    monkeypatch.setattr(cp5, "_connect", faulty_connect)
    with pytest.raises(ControlPlaneV5IOError, match="reader connection close"):
        with store._reader():
            pass
    monkeypatch.setattr(cp5, "_connect", original_connect)
    assert store.verify_integrity().commit_sequence == 1


def test_mutation_rollback_and_close_failures_preserve_cancellation_identity(
    tmp_path, monkeypatch
):
    store, _key, _state = make_store(tmp_path)
    scope = store.mission_scope(workspace_id="workspace-a", mission_id="mission-a")
    original_connect = cp5._connect
    primary = _SyntheticCancellation("mutation cancellation")

    def faulty_connect(path, *, readonly=False):
        return _CleanupFaultConnection(
            original_connect(path, readonly=readonly),
            fail_rollback=True,
            fail_close=True,
        )

    def cancel(_connection):
        raise primary

    monkeypatch.setattr(cp5, "_connect", faulty_connect)
    with pytest.raises(_SyntheticCancellation) as caught:
        store._write_records(
            mutation_id="cleanup-cancellation",
            scope=scope,
            operation=cancel,
        )
    assert caught.value is primary
    monkeypatch.setattr(cp5, "_connect", original_connect)
    assert store.verify_integrity().commit_sequence == 1


def test_initialize_rollback_and_close_failures_preserve_primary_identity(
    tmp_path, monkeypatch
):
    original_connect = cp5._connect
    primary = _SyntheticCancellation("initialize cancellation")
    candidate = ControlPlaneV5Store(
        path=tmp_path / "initialize-fault.sqlite3",
        source=Authority(),
        key_vault=Vault(),
        state_vault=Vault(),
        pending_vault=Vault(),
        enabled=True,
        audit_reference_verifier=accept_test_audit,
        semantic_audit_verifier=accept_test_audit,
    )

    def faulty_connect(path, *, readonly=False):
        return _CleanupFaultConnection(
            original_connect(path, readonly=readonly),
            fail_rollback=True,
            fail_close=True,
        )

    def cancel_schema(_connection, *, full=False):
        del full
        raise primary

    monkeypatch.setattr(cp5, "_connect", faulty_connect)
    monkeypatch.setattr(candidate, "_verify_schema", cancel_schema)
    with pytest.raises(_SyntheticCancellation) as caught:
        candidate.initialize()
    assert caught.value is primary


@pytest.mark.parametrize("operation", ("append", "find"))
def test_semantic_audit_cleanup_failures_preserve_cancellation_identity(
    tmp_path, monkeypatch, operation
):
    tool_audit.AUDIT_PATH = tmp_path / f"semantic-cleanup-{operation}.sqlite3"
    contract = _semantic_audit_contract(target="local-runtime", approval_id=None)
    original_connect = tool_audit._connect
    primary = _SyntheticCancellation(f"semantic {operation} cancellation")

    def faulty_connect():
        return _CleanupFaultConnection(
            original_connect(), fail_rollback=True, fail_close=True
        )

    def cancel_verify(_db):
        raise primary

    monkeypatch.setattr(tool_audit, "_connect", faulty_connect)
    monkeypatch.setattr(tool_audit, "_verify_hot_head", cancel_verify)
    with pytest.raises(_SyntheticCancellation) as caught:
        if operation == "append":
            tool_audit.append_semantic_tool_audit_reference(
                contract=contract, reason="cleanup cancellation"
            )
        else:
            tool_audit.find_semantic_tool_audit_reference(contract=contract)
    assert caught.value is primary


class _FlexibleScopeAuthority(Authority):
    def __init__(self, correlation_id="correlation-a"):
        super().__init__()
        self.correlation_id = correlation_id

    def read_scope(self, workspace_id, mission_id):
        return cp5.MissionScope(
            workspace_id=workspace_id,
            mission_id=mission_id,
            correlation_id=self.correlation_id,
            context_revision=3,
            context_sha256=digest("flexible-context"),
            source_state_root=self.root,
        )


def _generic_evidence_write(store, monkeypatch, *, field, text_canary, id_canary):
    arguments = evidence_arguments("r9-generic-evidence")
    if field == "workspace_id":
        arguments["workspace_id"] = id_canary
    elif field == "mission_id":
        arguments["mission_id"] = id_canary
    elif field == "title":
        arguments["title"] = text_canary
    elif field == "publisher_or_owner":
        arguments["publisher_or_owner"] = text_canary
    elif field == "entity_id":
        monkeypatch.setattr(
            cp5,
            "evidence_identity",
            lambda **_kwargs: id_canary,
        )
    return store.record_evidence(**arguments)


def _generic_secret_id(value):
    # Preserve an identifier-compatible Bearer credential shape.  A hyphenated
    # English label is safe; the colon form is the credential-shaped control.
    if value.startswith("bearer-"):
        return "Bearer:" + value[len("bearer-") :]
    return value


@pytest.mark.parametrize("canary,id_canary", _RECOVERABLE_SECRET_CANARIES)
@pytest.mark.parametrize(
    "field",
    (
        "workspace_id",
        "mission_id",
        "correlation_id",
        "entity_id",
        "title",
        "publisher_or_owner",
    ),
)
def test_r9_all_generic_persisted_strings_reject_secret_on_write(
    tmp_path, monkeypatch, canary, id_canary, field
):
    id_canary = _generic_secret_id(id_canary)
    authority = _FlexibleScopeAuthority(
        id_canary if field == "correlation_id" else "correlation-a"
    )
    store, _key, _state = make_store(tmp_path, authority=authority)
    with pytest.raises(ControlPlaneV5ContractError, match="invalid|secret"):
        _generic_evidence_write(
            store,
            monkeypatch,
            field=field,
            text_canary=canary,
            id_canary=id_canary,
        )


@pytest.mark.parametrize("canary,id_canary", _RECOVERABLE_SECRET_CANARIES)
@pytest.mark.parametrize(
    "field",
    (
        "workspace_id",
        "mission_id",
        "correlation_id",
        "entity_id",
        "title",
        "publisher_or_owner",
    ),
)
def test_r9_hydration_and_full_audit_reject_authenticated_generic_secrets(
    tmp_path, monkeypatch, canary, id_canary, field
):
    id_canary = _generic_secret_id(id_canary)
    authority = _FlexibleScopeAuthority(
        id_canary if field == "correlation_id" else "correlation-a"
    )
    store, _key, _state = make_store(tmp_path, authority=authority)
    original_reject = cp5._reject_secret
    monkeypatch.setattr(cp5, "_reject_secret", lambda _value, _label: None)
    record = _generic_evidence_write(
        store,
        monkeypatch,
        field=field,
        text_canary=canary,
        id_canary=id_canary,
    )
    monkeypatch.setattr(cp5, "_reject_secret", original_reject)

    with pytest.raises(ControlPlaneV5IntegrityError, match="persisted-string"):
        with store._reader() as connection:
            store._verified_record(
                connection,
                "evidence_records",
                "evidence_id",
                record.evidence_id,
            )
    with pytest.raises(ControlPlaneV5IntegrityError, match="persisted-string"):
        store.verify_integrity(full=True)


@pytest.mark.parametrize(
    "field,safe_value",
    (
        ("workspace_id", "workspace-a"),
        ("mission_id", "mission-a"),
        ("correlation_id", "correlation-a"),
        ("entity_id", "evidence-safe-r9"),
        ("title", "Security policy discusses credentials without storing them."),
        ("publisher_or_owner", "Cyryx Labs Research"),
    ),
)
def test_r9_generic_safe_prose_and_identifiers_persist_and_full_audit(
    tmp_path, monkeypatch, field, safe_value
):
    authority = _FlexibleScopeAuthority(
        safe_value if field == "correlation_id" else "correlation-a"
    )
    store, _key, _state = make_store(tmp_path, authority=authority)
    record = _generic_evidence_write(
        store,
        monkeypatch,
        field=field,
        text_canary=safe_value,
        id_canary=safe_value,
    )
    assert (
        store.get_evidence(
            workspace_id=record.workspace_id,
            mission_id=record.mission_id,
            evidence_id=record.evidence_id,
        )
        == record
    )
    store.verify_integrity(full=True)


def test_r9_hot_semantic_operations_never_call_cold_full_scan(tmp_path, monkeypatch):
    tool_audit.AUDIT_PATH = tmp_path / "hot-no-cold.sqlite3"
    first = _semantic_audit_contract(target="local-runtime-a", approval_id=None)
    second = _semantic_audit_contract(target="local-runtime-b", approval_id=None)
    first_ref = tool_audit.append_semantic_tool_audit_reference(contract=first)
    assert tool_audit.verify_audit() == (1, first_ref.event_hash)

    def forbidden_full_scan(*_args, **_kwargs):
        raise AssertionError("hot path invoked cold full-history audit")

    monkeypatch.setattr(tool_audit, "verify_audit", forbidden_full_scan)
    second_ref = tool_audit.append_semantic_tool_audit_reference(contract=second)
    assert tool_audit.find_semantic_tool_audit_reference(contract=first) == first_ref
    assert tool_audit.verify_semantic_tool_audit_reference(
        contract=second, event_hash=second_ref.event_hash
    )


@pytest.mark.parametrize("tamper", ("head", "count", "latest_event", "trace_index"))
def test_r9_hot_semantic_operations_deny_latest_meta_and_index_tamper(tmp_path, tamper):
    tool_audit.AUDIT_PATH = tmp_path / f"hot-tamper-{tamper}.sqlite3"
    contract = _semantic_audit_contract(target="local-runtime", approval_id=None)
    tool_audit.append_semantic_tool_audit_reference(contract=contract)
    connection = sqlite3.connect(tool_audit.AUDIT_PATH)
    try:
        if tamper == "head":
            connection.execute("UPDATE meta SET value=? WHERE key='head'", ("f" * 64,))
        elif tamper == "count":
            connection.execute("UPDATE meta SET value='999' WHERE key='count'")
        elif tamper == "latest_event":
            connection.execute("DROP TRIGGER events_no_update")
            connection.execute(
                "UPDATE events SET reason='tampered-latest' WHERE id=(SELECT MAX(id) FROM events)"
            )
        else:
            connection.execute(f"DROP INDEX {tool_audit._TRACE_INDEX}")
            connection.execute(
                f"CREATE INDEX {tool_audit._TRACE_INDEX} ON events(action)"
            )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(tool_audit.AuditIntegrityError):
        tool_audit.find_semantic_tool_audit_reference(contract=contract)


def test_r9_historical_tamper_is_deferred_to_explicit_cold_audit(tmp_path):
    tool_audit.AUDIT_PATH = tmp_path / "historical-cold.sqlite3"
    contracts = [
        _semantic_audit_contract(target=f"local-runtime-{index}", approval_id=None)
        for index in range(3)
    ]
    references = [
        tool_audit.append_semantic_tool_audit_reference(contract=contract)
        for contract in contracts
    ]
    connection = sqlite3.connect(tool_audit.AUDIT_PATH)
    try:
        connection.execute("DROP TRIGGER events_no_update")
        connection.execute("UPDATE events SET reason='historical-tamper' WHERE id=1")
        connection.commit()
    finally:
        connection.close()
    assert (
        tool_audit.find_semantic_tool_audit_reference(contract=contracts[-1])
        == references[-1]
    )
    with pytest.raises(tool_audit.AuditIntegrityError, match="chain"):
        tool_audit.verify_audit()


def test_r9_targeted_semantic_row_tamper_denies_hot_membership(tmp_path):
    tool_audit.AUDIT_PATH = tmp_path / "semantic-row-tamper.sqlite3"
    contract = _semantic_audit_contract(target="local-runtime", approval_id=None)
    tool_audit.append_semantic_tool_audit_reference(contract=contract)
    connection = sqlite3.connect(tool_audit.AUDIT_PATH)
    try:
        connection.execute("DROP TRIGGER semantic_events_v2_no_update")
        connection.execute(
            "UPDATE semantic_events_v2 SET semantic_digest=?", ("f" * 64,)
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(tool_audit.AuditIntegrityError, match="CAS|binding"):
        tool_audit.find_semantic_tool_audit_reference(contract=contract)


def test_r9_hot_lookup_validation_cost_is_bounded_as_history_grows(
    tmp_path, monkeypatch
):
    tool_audit.AUDIT_PATH = tmp_path / "bounded-hot.sqlite3"
    contract = _semantic_audit_contract(target="bounded-target", approval_id=None)
    reference = tool_audit.append_semantic_tool_audit_reference(contract=contract)

    def grow(start, stop):
        for index in range(start, stop):
            tool_audit.append_tool_audit_reference(
                profile="owner",
                tool="system_status",
                action="observe",
                decision="allowed",
                reason="bounded history fixture",
                trace_id=f"history-{index}",
            )

    def measured_lookup():
        calls = 0
        original = tool_audit._verify_event_row

        def counted(row):
            nonlocal calls
            calls += 1
            return original(row)

        monkeypatch.setattr(tool_audit, "_verify_event_row", counted)
        try:
            assert (
                tool_audit.find_semantic_tool_audit_reference(contract=contract)
                == reference
            )
        finally:
            monkeypatch.setattr(tool_audit, "_verify_event_row", original)
        return calls

    grow(0, 8)
    small = measured_lookup()
    grow(8, 128)
    large = measured_lookup()
    assert small <= 3
    assert large <= 3
    assert large == small
