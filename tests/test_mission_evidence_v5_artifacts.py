from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from core import mission_evidence_v5 as evidence_v5
from core import tool_audit
from core.artifact_service import ArtifactService, _authorize_root_for_testing
from core.control_plane_v5 import (
    ControlPlaneV5Conflict,
    ControlPlaneV5IntegrityError,
    ControlPlaneV5IsolationError,
    ControlPlaneV5Store,
    MissionScope,
    action_audit_trace_id,
    action_request_contract_sha256,
    action_request_identity,
    stable_scope_key,
)
from core.mission_evidence_v5 import (
    ArtifactRegistrationRequired,
    ControlPlaneArtifactPublisher,
    LocalSystemStatusEvidenceService,
    MissionEvidenceV5Error,
    ReconciliationRequired,
    _default_audit_writer,
    _publication_identity,
)
from p44_v5_support import Authority, Vault


class MissionAwareAuthority(Authority):
    def read_scope(self, workspace_id, mission_id):
        if workspace_id != "workspace-a" or mission_id not in {"mission-a", "mission-b"}:
            raise RuntimeError("cross-scope")
        suffix = mission_id[-1]
        return MissionScope(
            workspace_id=workspace_id,
            mission_id=mission_id,
            correlation_id=f"correlation-{suffix}",
            context_revision=3,
            context_sha256=hashlib.sha256(f"context-{mission_id}".encode()).hexdigest(),
            source_state_root=self.root,
        )


def test_notification_registry_is_refcounted_and_10k_no_waiter_notifies_allocate_nothing():
    with evidence_v5._CONDITIONS_LOCK:
        evidence_v5._CONDITIONS.clear()
    for index in range(10_000):
        evidence_v5._notify(f"request-without-waiter-{index}")
    with evidence_v5._CONDITIONS_LOCK:
        assert evidence_v5._CONDITIONS == {}

    with evidence_v5._condition_waiter("request-with-one-waiter") as condition:
        with evidence_v5._CONDITIONS_LOCK:
            entry = evidence_v5._CONDITIONS["request-with-one-waiter"]
            assert entry.waiters == 1
            assert entry.condition is condition
        evidence_v5._notify("request-with-one-waiter")
    with evidence_v5._CONDITIONS_LOCK:
        assert evidence_v5._CONDITIONS == {}


class _PipelineCancellation(BaseException):
    pass


def build_real(
    tmp_path, monkeypatch, *, tool_runner=None, audit_writer=None,
    reservation_lease_seconds=30, source=None,
):
    audit_path = tmp_path / "audit" / "tool-audit.sqlite3"
    monkeypatch.setattr(tool_audit, "AUDIT_PATH", audit_path)
    store = ControlPlaneV5Store(
        path=tmp_path / "control-plane" / "v5.sqlite3",
        source=source or Authority(),
        key_vault=Vault(),
        state_vault=Vault(),
        pending_vault=Vault(),
        enabled=True,
        audit_reference_verifier=lambda trace_id, event_hash: tool_audit.verify_audit_reference(
            trace_id=trace_id, event_hash=event_hash
        ),
        semantic_audit_verifier=lambda contract, event_hash: tool_audit.verify_semantic_tool_audit_reference(
            contract=contract, event_hash=event_hash
        ),
    ).initialize()
    root = tmp_path / "artifacts-workspace-a"
    root.mkdir()
    if os.name != "nt":
        root.chmod(0o700)
    capability = _authorize_root_for_testing(
        root, allowlisted_roots=(root,)
    )
    bytes_service = ArtifactService(
        capability, workspace_id="workspace-a", enabled=True
    )
    publisher = ControlPlaneArtifactPublisher(store=store, service=bytes_service)
    kwargs = {}
    if tool_runner is not None:
        kwargs["tool_runner"] = tool_runner
    if audit_writer is not None:
        kwargs["audit_writer"] = audit_writer
    pipeline = LocalSystemStatusEvidenceService(
        store=store, artifacts=publisher,
        reservation_lease_seconds=reservation_lease_seconds, **kwargs
    )
    return store, root, capability, bytes_service, publisher, pipeline, audit_path


@pytest.mark.parametrize("cleanup_seam", ("receipt_lookup", "receipt_persist"))
def test_pipeline_cleanup_failure_preserves_primary_cancellation_identity(
    tmp_path, monkeypatch, cleanup_seam
):
    primary = _PipelineCancellation("tool cancellation")
    dispatched = False

    def runner(_tool, _args, _key):
        nonlocal dispatched
        dispatched = True
        raise primary

    store, _root, capability, _bytes, _publisher, pipeline, _audit_path = (
        build_real(tmp_path, monkeypatch, tool_runner=runner)
    )
    original_latest = store.latest_action_receipt
    original_record = store.record_action_receipt
    if cleanup_seam == "receipt_lookup":
        def latest(**kwargs):
            if dispatched:
                raise RuntimeError("injected cleanup lookup failure")
            return original_latest(**kwargs)

        monkeypatch.setattr(store, "latest_action_receipt", latest)
    else:
        def fail_record(**_kwargs):
            raise RuntimeError("injected cleanup persistence failure")

        monkeypatch.setattr(store, "record_action_receipt", fail_record)
    try:
        with pytest.raises(_PipelineCancellation) as caught:
            pipeline.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key=f"cleanup-{cleanup_seam}",
            )
        assert caught.value is primary
        with evidence_v5._CONDITIONS_LOCK:
            assert evidence_v5._CONDITIONS == {}
    finally:
        monkeypatch.setattr(store, "latest_action_receipt", original_latest)
        monkeypatch.setattr(store, "record_action_receipt", original_record)
        capability.close()


def test_real_artifact_service_manifest_audit_and_replay(tmp_path, monkeypatch):
    calls = 0

    def runner(tool, args, key):
        nonlocal calls
        calls += 1
        from core import mission_tools

        return mission_tools.run(tool, args, key)

    store, root, capability, bytes_service, _publisher, pipeline, audit_path = (
        build_real(tmp_path, monkeypatch, tool_runner=runner)
    )
    try:
        result = pipeline.execute(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="real-artifact-e2e",
        )
        assert calls == 1
        assert result.artifact.manifest_sha256 == result.artifact.metadata_sha256
        assert result.artifact.source_provenance_sha256 != "0" * 64
        assert result.artifact.artifact_created_at.endswith("Z")
        assert result.artifact.status == "available"
        assert (root / result.artifact.relative_path).is_file()
        assert bytes_service.read(
            # Adapter reconstruction is independently exercised by replay.
            pipeline.artifacts.service.lookup(
                pipeline.artifacts.service._records[result.artifact.content_sha256]
            )
        )
        count, head = tool_audit.verify_audit()
        assert count == 1
        assert head == result.request.audit_reference_sha256
        connection = sqlite3.connect(audit_path)
        try:
            stored_hash = connection.execute(
                "SELECT event_hash FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        finally:
            connection.close()
        assert stored_hash == result.request.audit_reference_sha256

        replay = pipeline.execute(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="real-artifact-e2e",
        )
        assert replay.replayed and replay.public_result == result.public_result
        assert calls == 1
        assert tool_audit.verify_audit() == (1, head)
        assert store.verify_integrity(full=True).commit_sequence >= 6
    finally:
        capability.close()


def test_distinct_requests_share_one_cas_blob_with_two_authenticated_bindings(
    tmp_path, monkeypatch
):
    counts = {"audit": 0, "dispatch": 0}

    def audit(request):
        counts["audit"] += 1
        return _default_audit_writer(request)

    def runner(tool, args, key):
        counts["dispatch"] += 1
        from core import mission_tools

        return mission_tools.run(tool, args, key)

    store, _root, capability, byte_service, publisher, _pipeline, _audit_path = (
        build_real(tmp_path, monkeypatch, tool_runner=runner)
    )
    pipeline = LocalSystemStatusEvidenceService(
        store=store, artifacts=publisher, audit_writer=audit, tool_runner=runner
    )
    try:
        first = pipeline.execute(
            workspace_id="workspace-a", mission_id="mission-a", caller_key="request-one"
        )
        second = pipeline.execute(
            workspace_id="workspace-a", mission_id="mission-a", caller_key="request-two"
        )
        assert counts == {"audit": 2, "dispatch": 2}
        assert first.public_result == second.public_result
        assert first.request.request_id != second.request.request_id
        assert first.request.audit_reference_sha256 != second.request.audit_reference_sha256
        assert first.artifact.artifact_id != second.artifact.artifact_id
        assert first.artifact.request_id == first.request.request_id
        assert second.artifact.request_id == second.request.request_id
        assert first.artifact.content_sha256 == second.artifact.content_sha256
        assert len(byte_service._records) == 1
        publication = byte_service._records[first.artifact.content_sha256]
        expected_publication_id = "artifact-" + hashlib.sha256(
            json.dumps(
                ["OnyxArtifact.v1", "workspace-a", first.artifact.content_sha256],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        assert publication.artifact_id == expected_publication_id
        assert _publication_identity(
            "workspace-a", first.artifact.content_sha256
        ) == expected_publication_id
        expected_provenance = hashlib.sha256(
            json.dumps(
                {"kind": "immutable_bytes", "schema_version": 1},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        assert publication.source_provenance_sha256 == expected_provenance
        with sqlite3.connect(store.path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM artifact_records").fetchone()[0] == 2
            assert connection.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0] == 2
            assert connection.execute("SELECT COUNT(*) FROM action_receipts").fetchone()[0] == 2
        assert tool_audit.verify_audit()[0] == 2
        binding_events = [
            event
            for event in store.list_events(
                workspace_id="workspace-a", mission_id="mission-a", limit=200
            )
            if event.entity_type == "artifact_binding"
        ]
        assert len(binding_events) == 2
        assert {event.event_type for event in binding_events} == {"artifact.bound"}
        store.verify_integrity(full=True)

        raw = publisher.read_bytes(
            workspace_id="workspace-a",
            mission_id="mission-a",
            artifact_id=first.artifact.artifact_id,
            max_bytes=64 * 1024,
        )
        rebound = publisher.publish(
            workspace_id="workspace-a",
            mission_id="mission-a",
            request_id=first.request.request_id,
            content=raw,
            media_type="application/json",
            metadata={
                "caller": "must-not-enter-cas",
                "request_id": second.request.request_id,
            },
            caller_key="request-specific-metadata-is-ignored",
        )
        assert rebound == first.artifact
        assert len(byte_service._records) == 1
        assert byte_service._records[first.artifact.content_sha256] == publication

        replay = pipeline.execute(
            workspace_id="workspace-a", mission_id="mission-a", caller_key="request-one"
        )
        assert replay.replayed
        assert counts == {"audit": 2, "dispatch": 2}
        assert tool_audit.verify_audit()[0] == 2
    finally:
        capability.close()


def test_same_cas_bytes_have_isolated_bindings_across_missions(tmp_path, monkeypatch):
    counts = {"audit": 0, "dispatch": 0}

    def audit(request):
        counts["audit"] += 1
        return _default_audit_writer(request)

    def runner(tool, args, key):
        counts["dispatch"] += 1
        from core import mission_tools

        return mission_tools.run(tool, args, key)

    store, _root, capability, byte_service, publisher, _pipeline, _audit_path = (
        build_real(
            tmp_path,
            monkeypatch,
            tool_runner=runner,
            source=MissionAwareAuthority(),
        )
    )
    pipeline = LocalSystemStatusEvidenceService(
        store=store, artifacts=publisher, audit_writer=audit, tool_runner=runner
    )
    try:
        first = pipeline.execute(
            workspace_id="workspace-a", mission_id="mission-a", caller_key="shared-status"
        )
        second = pipeline.execute(
            workspace_id="workspace-a", mission_id="mission-b", caller_key="shared-status"
        )
        assert counts == {"audit": 2, "dispatch": 2}
        assert len(byte_service._records) == 1
        assert first.artifact.content_sha256 == second.artifact.content_sha256
        assert first.artifact.artifact_id != second.artifact.artifact_id
        assert first.artifact.mission_id == first.evidence.mission_id == "mission-a"
        assert second.artifact.mission_id == second.evidence.mission_id == "mission-b"
        assert first.artifact.correlation_id == first.evidence.correlation_id
        assert second.artifact.correlation_id == second.evidence.correlation_id
        assert first.artifact.correlation_id != second.artifact.correlation_id
        with pytest.raises(ControlPlaneV5IsolationError, match="another mission"):
            store.get_artifact(
                workspace_id="workspace-a",
                mission_id="mission-b",
                artifact_id=first.artifact.artifact_id,
            )
        with pytest.raises(ControlPlaneV5IsolationError, match="another mission"):
            publisher.read_bytes(
                workspace_id="workspace-a",
                mission_id="mission-a",
                artifact_id=second.artifact.artifact_id,
                max_bytes=64 * 1024,
            )
        events_a = store.list_events(
            workspace_id="workspace-a", mission_id="mission-a", limit=200
        )
        events_b = store.list_events(
            workspace_id="workspace-a", mission_id="mission-b", limit=200
        )
        assert {event.mission_id for event in events_a} == {"mission-a"}
        assert {event.mission_id for event in events_b} == {"mission-b"}
        assert first.artifact.artifact_id in {event.entity_id for event in events_a}
        assert second.artifact.artifact_id in {event.entity_id for event in events_b}
        store.verify_integrity(full=True)
    finally:
        capability.close()


def test_reusing_another_request_audit_member_denies_before_dispatch(
    tmp_path, monkeypatch
):
    dispatches = 0

    def runner(tool, args, key):
        nonlocal dispatches
        dispatches += 1
        from core import mission_tools

        return mission_tools.run(tool, args, key)

    store, _root, capability, _bytes, publisher, first_pipeline, _audit_path = (
        build_real(tmp_path, monkeypatch, tool_runner=runner)
    )
    try:
        first = first_pipeline.execute(
            workspace_id="workspace-a", mission_id="mission-a", caller_key="audit-owner"
        )
        forged = LocalSystemStatusEvidenceService(
            store=store,
            artifacts=publisher,
            audit_writer=lambda _request: first.request.audit_reference_sha256,
            tool_runner=runner,
        )
        with pytest.raises(MissionEvidenceV5Error, match="verified chain member"):
            forged.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key="audit-collision",
            )
        assert dispatches == 1
        assert tool_audit.verify_audit()[0] == 1
        forged_request_id = action_request_identity(
            stable_scope_key(
                workspace_id="workspace-a",
                mission_id="mission-a",
                operation="local_system_status",
                caller_key="audit-collision",
            )
        )
        assert store.find_action_request(
            workspace_id="workspace-a", mission_id="mission-a",
            request_id=forged_request_id,
        ) is None
        store.verify_integrity(full=True)
    finally:
        capability.close()


@pytest.mark.parametrize("audit_result", [None, "f" * 63, "0" * 64, "f" * 64])
def test_invalid_or_missing_audit_reference_denies_before_dispatch(
    tmp_path, monkeypatch, audit_result
):
    calls = 0

    def runner(*_args):
        nonlocal calls
        calls += 1

    store, _root, capability, _bytes, _publisher, pipeline, _audit_path = build_real(
        tmp_path,
        monkeypatch,
        tool_runner=runner,
        audit_writer=lambda _request: audit_result,
    )
    try:
        with pytest.raises(MissionEvidenceV5Error, match="invalid event reference|verified chain member"):
            pipeline.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key="bad-audit",
            )
        request_id = action_request_identity(
            stable_scope_key(
                workspace_id="workspace-a",
                mission_id="mission-a",
                operation="local_system_status",
                caller_key="bad-audit",
            )
        )
        assert store.find_action_request(
            workspace_id="workspace-a", mission_id="mission-a",
            request_id=request_id,
        ) is None
        assert calls == 0
    finally:
        capability.close()


def test_published_orphan_is_retained_and_explicitly_reconciled(
    tmp_path, monkeypatch
):
    calls = 0

    def runner(tool, args, key):
        nonlocal calls
        calls += 1
        from core import mission_tools

        return mission_tools.run(tool, args, key)

    store, root, capability, bytes_service, publisher, pipeline, _audit_path = (
        build_real(
            tmp_path,
            monkeypatch,
            tool_runner=runner,
        )
    )
    original = store.record_artifact

    def fail_registration(**_kwargs):
        raise RuntimeError("injected metadata commit failure")

    monkeypatch.setattr(store, "record_artifact", fail_registration)
    try:
        with pytest.raises(ArtifactRegistrationRequired) as caught:
            pipeline.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key="orphan-reconcile",
            )
        publication = caught.value.publication
        recovery_token = caught.value.recovery_token
        assert (root / publication.relative_path).is_file()
        assert bytes_service.lookup(publication) == publication
        assert calls == 1

        monkeypatch.setattr(store, "record_artifact", original)
        result = pipeline.reconcile_published_artifact(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="orphan-reconcile",
            publication=publication,
            recovery_token=recovery_token,
        )
        assert result.receipt.reconciliation
        assert result.receipt.outcome == "simulated"
        assert result.artifact.artifact_id != publication.artifact_id
        assert result.artifact.content_sha256 == publication.sha256
        assert calls == 1
        assert publisher.read_bytes(
            workspace_id="workspace-a",
            mission_id="mission-a",
            artifact_id=result.artifact.artifact_id,
            max_bytes=64 * 1024,
        )
    finally:
        capability.close()


def test_r9_artifact_publisher_preserves_metadata_cancellation_identity(
    tmp_path, monkeypatch
):
    store, root, capability, _bytes, publisher, _pipeline, _audit_path = (
        build_real(tmp_path, monkeypatch)
    )
    primary = _PipelineCancellation("metadata registration cancelled")

    def cancel_registration(**_kwargs):
        raise primary

    monkeypatch.setattr(store, "record_artifact", cancel_registration)
    try:
        with pytest.raises(_PipelineCancellation) as caught:
            publisher.publish(
                workspace_id="workspace-a",
                mission_id="mission-a",
                request_id="request-r9-cancel",
                content=b"r9 immutable publication",
                media_type="application/json",
                metadata={},
                caller_key="r9-cancel",
            )
        assert caught.value is primary
        assert any(path.is_file() for path in root.rglob("*"))
    finally:
        capability.close()


def test_r9_artifact_publisher_does_not_relabel_pre_registration_failure(
    tmp_path, monkeypatch
):
    _store, _root, capability, service, publisher, _pipeline, _audit_path = (
        build_real(tmp_path, monkeypatch)
    )
    primary = RuntimeError("publication lookup integrity failure")

    def fail_lookup(_publication):
        raise primary

    monkeypatch.setattr(service, "lookup", fail_lookup)
    try:
        with pytest.raises(RuntimeError) as caught:
            publisher.publish(
                workspace_id="workspace-a",
                mission_id="mission-a",
                request_id="request-r9-lookup",
                content=b"r9 lookup failure",
                media_type="application/json",
                metadata={},
                caller_key="r9-lookup",
            )
        assert caught.value is primary
        assert not isinstance(caught.value, ArtifactRegistrationRequired)
    finally:
        capability.close()


@pytest.mark.parametrize("cleanup_seam", ("lookup", "abandon", "link", "notify"))
def test_r9_audit_writer_recovery_cleanup_never_replaces_primary_baseexception(
    tmp_path, monkeypatch, cleanup_seam
):
    store, _root, capability, _service, publisher, _pipeline, _audit_path = (
        build_real(tmp_path, monkeypatch)
    )
    primary = _PipelineCancellation(f"audit writer cancelled before {cleanup_seam}")
    lookups = 0

    def writer(_request):
        raise primary

    def lookup(_request):
        nonlocal lookups
        lookups += 1
        if lookups == 1:
            return None
        if cleanup_seam == "lookup":
            raise RuntimeError("injected recovery lookup cleanup failure")
        if cleanup_seam == "link":
            return hashlib.sha256(b"recovered-audit").hexdigest()
        return None

    if cleanup_seam == "abandon":
        monkeypatch.setattr(
            store,
            "abandon_pre_audit_reservation",
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected abandon cleanup failure")
            ),
        )
    elif cleanup_seam == "link":
        monkeypatch.setattr(
            store,
            "link_action_audit",
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected link cleanup failure")
            ),
        )
    elif cleanup_seam == "notify":
        monkeypatch.setattr(
            evidence_v5,
            "_notify",
            lambda _request_id: (_ for _ in ()).throw(
                RuntimeError("injected notify cleanup failure")
            ),
        )
    pipeline = LocalSystemStatusEvidenceService(
        store=store,
        artifacts=publisher,
        audit_writer=writer,
        audit_lookup=lookup,
    )
    try:
        with pytest.raises(_PipelineCancellation) as caught:
            pipeline.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key=f"r9-writer-{cleanup_seam}",
            )
        assert caught.value is primary
        assert getattr(primary, "__notes__", ())
    finally:
        capability.close()


def test_reconciliation_rejects_another_requests_schema_valid_publication(
    tmp_path, monkeypatch
):
    calls = 0

    def runner(_tool, _args, _key):
        nonlocal calls
        calls += 1
        # Both requests intentionally publish the exact same canonical bytes.
        # Only the request-specific recovery token may authorize reconciliation.
        label = "identical-runtime"
        return {
            "status": "succeeded",
            "data": {
                "platform": label,
                "python": "3.13.5",
                "provider_free": True,
                "citation": f"local-{label}",
            },
            "evidence": [{"type": "citation", "value": f"local-{label}"}],
            "postconditions": [
                {"name": "runtime_status_observed", "satisfied": True}
            ],
            "waiting_for": None,
        }

    store, _root, capability, _bytes, _publisher, pipeline, _audit_path = (
        build_real(tmp_path, monkeypatch, tool_runner=runner)
    )
    original = store.record_artifact

    def fail_registration(**_kwargs):
        raise RuntimeError("injected metadata commit failure")

    monkeypatch.setattr(store, "record_artifact", fail_registration)
    try:
        with pytest.raises(ArtifactRegistrationRequired) as caught_a:
            pipeline.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key="publication-request-a",
            )
        with pytest.raises(ArtifactRegistrationRequired) as caught_b:
            pipeline.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key="publication-request-b",
            )
        publication_a = caught_a.value.publication
        publication_b = caught_b.value.publication
        token_a = caught_a.value.recovery_token
        token_b = caught_b.value.recovery_token
        assert publication_a.sha256 == publication_b.sha256
        assert publication_a.manifest_sha256 == publication_b.manifest_sha256
        assert token_a != token_b
        assert calls == 2

        monkeypatch.setattr(store, "record_artifact", original)
        with pytest.raises(MissionEvidenceV5Error, match="original request binding"):
            pipeline.reconcile_published_artifact(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key="publication-request-a",
                publication=publication_b,
                recovery_token=token_b,
            )

        reconciled = pipeline.reconcile_published_artifact(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="publication-request-a",
            publication=publication_a,
            recovery_token=token_a,
        )
        assert reconciled.receipt.reconciliation
        assert reconciled.artifact.content_sha256 == publication_a.sha256
        assert calls == 2
        store.verify_integrity(full=True)
    finally:
        capability.close()


def test_two_services_same_request_have_one_audit_dispatch_publish_and_receipt(
    tmp_path, monkeypatch
):
    store, _root, capability, _bytes, publisher, _pipeline, _audit_path = build_real(
        tmp_path, monkeypatch
    )
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    counts = {"audit": 0, "tool": 0, "publish": 0}

    class CountingPublisher:
        def publish(self, **kwargs):
            with lock:
                counts["publish"] += 1
            return publisher.publish(**kwargs)

        def read_bytes(self, **kwargs):
            return publisher.read_bytes(**kwargs)

        def reconcile_publication(self, **kwargs):
            return publisher.reconcile_publication(**kwargs)

    shared = CountingPublisher()

    def audit(request):
        with lock:
            counts["audit"] += 1
        return _default_audit_writer(request)

    def runner(tool, args, key):
        with lock:
            counts["tool"] += 1
        from core import mission_tools

        return mission_tools.run(tool, args, key)

    services = [
        LocalSystemStatusEvidenceService(
            store=store, artifacts=shared, audit_writer=audit, tool_runner=runner
        )
        for _ in range(2)
    ]

    def execute(service):
        barrier.wait(timeout=5)
        return service.execute(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="concurrent-status",
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(execute, services))
        assert counts == {"audit": 1, "tool": 1, "publish": 1}
        assert results[0].request == results[1].request
        assert results[0].receipt == results[1].receipt
        assert results[0].public_result == results[1].public_result
        assert {result.replayed for result in results} == {False, True}
    finally:
        capability.close()


def test_crash_after_audit_leaves_reservation_and_never_dispatches(
    tmp_path, monkeypatch
):
    store, _root, capability, _bytes, publisher, pipeline, _audit_path = build_real(
        tmp_path,
        monkeypatch,
        reservation_lease_seconds=1,
    )
    original = store.record_action_request
    calls = 0

    def fail_after_audit(**_kwargs):
        raise RuntimeError("crash after audit")

    monkeypatch.setattr(store, "record_action_request", fail_after_audit)
    try:
        with pytest.raises(RuntimeError, match="crash after audit"):
            pipeline.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key="crash-after-audit",
            )
        monkeypatch.setattr(store, "record_action_request", original)
        import time
        time.sleep(1.1)

        def forbidden(*_args):
            nonlocal calls
            calls += 1
            from core import mission_tools

            return mission_tools.run(_args[0], _args[1], _args[2])

        restarted = LocalSystemStatusEvidenceService(
            store=store,
            artifacts=publisher,
            audit_writer=lambda _request: (_ for _ in ()).throw(
                AssertionError("must not re-audit")
            ),
            tool_runner=forbidden,
            reservation_lease_seconds=1,
        )
        resumed = restarted.execute(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="crash-after-audit",
        )
        assert resumed.receipt.outcome == "simulated"
        assert calls == 1
    finally:
        capability.close()


def test_pre_audit_failure_releases_and_retries_without_blind_dispatch(
    tmp_path, monkeypatch
):
    calls = 0

    def runner(tool, args, key):
        nonlocal calls
        calls += 1
        from core import mission_tools

        return mission_tools.run(tool, args, key)

    store, _root, capability, _bytes, publisher, failed, _audit_path = build_real(
        tmp_path, monkeypatch, tool_runner=runner,
        audit_writer=lambda _request: (_ for _ in ()).throw(
            RuntimeError("audit unavailable before append")
        ),
    )
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            failed.execute(
                workspace_id="workspace-a", mission_id="mission-a",
                caller_key="pre-audit-retry",
            )
        assert calls == 0
        recovered = LocalSystemStatusEvidenceService(
            store=store, artifacts=publisher, tool_runner=runner
        ).execute(
            workspace_id="workspace-a", mission_id="mission-a",
            caller_key="pre-audit-retry",
        )
        assert recovered.receipt.outcome == "simulated"
        assert calls == 1
    finally:
        capability.close()


@pytest.mark.parametrize("failure_stage", ["tool", "artifact", "receipt"])
def test_restart_after_pipeline_crash_never_second_dispatch(
    tmp_path, monkeypatch, failure_stage
):
    calls = 0

    def runner(tool, args, key):
        nonlocal calls
        calls += 1
        if failure_stage == "tool":
            raise RuntimeError("crash at tool dispatch")
        from core import mission_tools

        return mission_tools.run(tool, args, key)

    store, _root, capability, _bytes, publisher, pipeline, _audit_path = build_real(
        tmp_path,
        monkeypatch,
        tool_runner=runner,
    )
    if failure_stage == "artifact":
        monkeypatch.setattr(
            publisher,
            "publish",
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("crash before artifact publication")
            ),
        )
    original_receipt = store.record_action_receipt
    if failure_stage == "receipt":
        def commit_then_crash(**kwargs):
            original_receipt(**kwargs)
            raise RuntimeError("crash after receipt commit")

        monkeypatch.setattr(store, "record_action_receipt", commit_then_crash)
    try:
        with pytest.raises(RuntimeError, match="crash"):
            pipeline.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key=f"crash-{failure_stage}",
            )
        monkeypatch.setattr(store, "record_action_receipt", original_receipt)
        if failure_stage == "artifact":
            # The request now has an unknown receipt; restoring publication
            # must not cause automatic dispatch.
            monkeypatch.setattr(publisher, "publish", publisher.__class__.publish.__get__(publisher))

        def forbidden(*_args):
            nonlocal calls
            calls += 1
            raise AssertionError("restart must not dispatch")

        restarted = LocalSystemStatusEvidenceService(
            store=store,
            artifacts=publisher,
            audit_writer=lambda _request: (_ for _ in ()).throw(
                AssertionError("restart must not audit")
            ),
            tool_runner=forbidden,
        )
        if failure_stage == "receipt":
            replay = restarted.execute(
                workspace_id="workspace-a",
                mission_id="mission-a",
                caller_key=f"crash-{failure_stage}",
            )
            assert replay.replayed
        else:
            with pytest.raises(ReconciliationRequired):
                restarted.execute(
                    workspace_id="workspace-a",
                    mission_id="mission-a",
                    caller_key=f"crash-{failure_stage}",
                )
        assert calls == 1
    finally:
        capability.close()


def _audit_trace_for_request(request):
    request_sha256 = action_request_contract_sha256(
        workspace_id=request.workspace_id, mission_id=request.mission_id,
        request_id=request.request_id, correlation_id=request.correlation_id,
        connector=request.connector, operation=request.operation,
        target_sha256=request.target_sha256, payload_sha256=request.payload_sha256,
        idempotency_key=request.idempotency_key, risk=request.risk,
        approval_policy=request.approval_policy, dry_run=request.dry_run,
        verification_plan_sha256=request.verification_plan_sha256,
        source_context_sha256=request.source_context_sha256,
        target=request.target,
        approval_id=request.approval_id,
        schema_version=request.schema_version,
    )
    return action_audit_trace_id(
        workspace_id=request.workspace_id, mission_id=request.mission_id,
        request_id=request.request_id, request_sha256=request_sha256,
        idempotency_key=request.idempotency_key, connector=request.connector,
        operation=request.operation, target_sha256=request.target_sha256,
        payload_sha256=request.payload_sha256, risk=request.risk,
        approval_policy=request.approval_policy, dry_run=request.dry_run,
        correlation_id=request.correlation_id,
        source_context_sha256=request.source_context_sha256,
        target=request.target,
        approval_id=request.approval_id,
        schema_version=request.schema_version,
    )


def test_denied_legacy_preseed_cannot_satisfy_semantic_v2_or_dispatch(
    tmp_path, monkeypatch
):
    dispatches = 0

    def runner(*_args):
        nonlocal dispatches
        dispatches += 1

    def denied_preseed(request):
        tool_audit.append_tool_audit_reference(
            profile="p4.4-shadow", tool=request.connector,
            action=request.operation, decision="denied", reason="adversarial preseed",
            outcome="decision", trace_id=_audit_trace_for_request(request),
        )
        return _default_audit_writer(request)

    store, _root, capability, _bytes, _publisher, pipeline, _audit_path = build_real(
        tmp_path, monkeypatch, tool_runner=runner, audit_writer=denied_preseed
    )
    try:
        with pytest.raises(tool_audit.AuditIntegrityError, match="cannot satisfy"):
            pipeline.execute(
                workspace_id="workspace-a", mission_id="mission-a",
                caller_key="semantic-preseed",
            )
        assert dispatches == 0
        assert tool_audit.verify_audit()[0] == 1
        request_id = action_request_identity(stable_scope_key(
            workspace_id="workspace-a", mission_id="mission-a",
            operation="local_system_status", caller_key="semantic-preseed",
        ))
        assert store.find_action_request(
            workspace_id="workspace-a", mission_id="mission-a",
            request_id=request_id,
        ) is None
    finally:
        capability.close()


def test_two_semantic_owners_cas_one_trace_and_one_audit_member(
    tmp_path, monkeypatch
):
    references = []

    def racing_writer(request):
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _index: _default_audit_writer(request), range(2)))
        references.extend(values)
        return values[0]

    _store, _root, capability, _bytes, _publisher, pipeline, _audit_path = build_real(
        tmp_path, monkeypatch, audit_writer=racing_writer
    )
    try:
        result = pipeline.execute(
            workspace_id="workspace-a", mission_id="mission-a",
            caller_key="semantic-cas-race",
        )
        assert references == [result.request.audit_reference_sha256] * 2
        assert tool_audit.verify_audit()[0] == 1
        with sqlite3.connect(tool_audit.AUDIT_PATH) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM semantic_events_v2"
            ).fetchone()[0] == 1
    finally:
        capability.close()


def test_audit_loss_after_execution_denies_replay_and_full_cold_audit(
    tmp_path, monkeypatch
):
    store, _root, capability, _bytes, _publisher, pipeline, audit_path = build_real(
        tmp_path, monkeypatch
    )
    try:
        pipeline.execute(
            workspace_id="workspace-a", mission_id="mission-a",
            caller_key="audit-loss-replay",
        )
        audit_path.unlink()
        with pytest.raises(ControlPlaneV5IntegrityError, match="semantic-v2"):
            pipeline.execute(
                workspace_id="workspace-a", mission_id="mission-a",
                caller_key="audit-loss-replay",
            )
        with pytest.raises(ControlPlaneV5IntegrityError, match="semantic-v2"):
            store.verify_integrity(full=True)
    finally:
        capability.close()


def test_expired_request_recorded_restart_dispatches_once_and_fences_old_owner(
    tmp_path, monkeypatch
):
    calls = 0

    def runner(tool, args, key):
        nonlocal calls
        calls += 1
        from core import mission_tools

        return mission_tools.run(tool, args, key)

    store, _root, capability, _bytes, publisher, pipeline, _audit_path = build_real(
        tmp_path, monkeypatch, tool_runner=runner, reservation_lease_seconds=1
    )
    try:
        request, old_lease = pipeline._request(
            workspace_id="workspace-a", mission_id="mission-a",
            caller_key="request-recorded-restart",
        )
        assert old_lease.owns and old_lease.stage == "reserved"
        import time

        time.sleep(1.1)
        restarted = LocalSystemStatusEvidenceService(
            store=store, artifacts=publisher, tool_runner=runner,
            reservation_lease_seconds=1,
        )
        result = restarted.execute(
            workspace_id="workspace-a", mission_id="mission-a",
            caller_key="request-recorded-restart",
        )
        assert result.request == request and calls == 1
        with pytest.raises(ControlPlaneV5Conflict, match="owner diverges"):
            store.mark_action_dispatch_unknown(
                workspace_id="workspace-a", mission_id="mission-a",
                request_id=request.request_id, owner_id=old_lease.owner_id,
            )
        replay = restarted.execute(
            workspace_id="workspace-a", mission_id="mission-a",
            caller_key="request-recorded-restart",
        )
        assert replay.replayed and calls == 1
    finally:
        capability.close()
