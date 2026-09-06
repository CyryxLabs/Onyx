from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from core.control_plane import ControlPlaneStore
from core import phase7_workspace_memory_v1 as workspace_memory
from core.phase7_workspace_memory_v1 import (
    FEATURE_FLAG,
    WorkspaceMemoryFeatureGateV1,
    WorkspaceMemoryQueryV1,
    WorkspaceMemoryV1ContractError,
    WorkspaceMemoryV1Denied,
    build_workspace_memory_metadata_v1,
    create_workspace_memory_adapter_v1,
    workspace_memory_metadata_id_v1,
)
from core.workspaces import WorkspaceRegistry
from memory.store import MemoryRecord, MemoryStore


NOW_MS = 1_785_000_000_000
KEY = bytes(range(1, 33))
ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Fixture:
    control: ControlPlaneStore
    registry: WorkspaceRegistry
    memory: MemoryStore


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=tmp_path,
    ):
        control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    registry.register(
        "cyryx-main",
        display_name="Cyryx Main",
        workspace_class="cyryx",
    )
    registry.register(
        "client-one",
        display_name="Client One",
        workspace_class="client",
    )
    memory = MemoryStore(tmp_path / "onyx_memory.sqlite3", enable_fts=False)
    memory.initialize()
    value = Fixture(control, registry, memory)
    try:
        yield value
    finally:
        control.close()


def _remember(
    fixture: Fixture,
    content: str,
    *,
    source: str,
    salience: float = 0.7,
) -> MemoryRecord:
    return fixture.memory.remember(
        content,
        source=source,
        citation=f"file:///{source}.md",
        salience=salience,
        timestamp="2026-07-23T12:00:00+00:00",
    )


def _attach(
    fixture: Fixture,
    record: MemoryRecord,
    *,
    workspace_id: str = "cyryx-main",
    principal_id: str = "owner:pedro",
    sensitivity: str = "internal",
    memory_status: str = "approved",
    source_status: str = "available",
    valid_from_ms: int = NOW_MS - 10_000,
    valid_until_ms: int | None = NOW_MS + 10_000,
    fresh_until_ms: int = NOW_MS + 5_000,
    key: bytes = KEY,
) -> dict[str, object]:
    payload = build_workspace_memory_metadata_v1(
        record=record,
        workspace_id=workspace_id,
        principal_id=principal_id,
        sensitivity=sensitivity,
        source_ids=(f"source:{record.id}",),
        valid_from_ms=valid_from_ms,
        valid_until_ms=valid_until_ms,
        fresh_until_ms=fresh_until_ms,
        integrity_key=key,
        memory_status=memory_status,
        source_status=source_status,
    )
    connection = fixture.control._require_connection()
    connection.execute(
        "INSERT INTO memory_metadata("
        "memory_metadata_id,workspace_id,source_memory_id,schema_version,status,"
        "payload_json,created_at,updated_at"
        ") VALUES(?,?,?,?,?,?,?,?)",
        (
            workspace_memory_metadata_id_v1(
                workspace_id=workspace_id,
                source_memory_id=record.id,
            ),
            workspace_id,
            record.id,
            1,
            "active",
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            "2026-07-23T12:00:00+00:00",
            "2026-07-23T12:00:00+00:00",
        ),
    )
    return payload


def _adapter(
    fixture: Fixture,
    *,
    workspace_id: str = "cyryx-main",
    principal_id: str = "owner:pedro",
    sensitivities: tuple[str, ...] = ("public", "internal"),
):
    adapter = create_workspace_memory_adapter_v1(
        gate=WorkspaceMemoryFeatureGateV1(True),
        registry=fixture.registry,
        memory_store=fixture.memory,
        workspace_id=workspace_id,
        principal_id=principal_id,
        allowed_sensitivities=sensitivities,
        integrity_key=KEY,
    )
    assert adapter is not None
    return adapter


def test_flag_is_exact_and_factory_returns_before_bindings() -> None:
    assert WorkspaceMemoryFeatureGateV1.from_environ({}).enabled is False
    assert (
        WorkspaceMemoryFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
        is True
    )
    for value in ("1", "TRUE", "True", " true", "true ", "yes"):
        assert (
            WorkspaceMemoryFeatureGateV1.from_environ({FEATURE_FLAG: value}).enabled
            is False
        )
    assert (
        create_workspace_memory_adapter_v1(
            gate=WorkspaceMemoryFeatureGateV1(False),
            project_root=ROOT / "missing-project",
        )
        is None
    )


def test_phase6_accepted_exit_is_an_exact_entry_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_memory._verify_phase6_entry(ROOT)
    changed = list(workspace_memory.PHASE6_EXIT_ROOTS)
    path, _digest = changed[0]
    changed[0] = (path, "0" * 64)
    monkeypatch.setattr(workspace_memory, "PHASE6_EXIT_ROOTS", tuple(changed))
    with pytest.raises(
        WorkspaceMemoryV1Denied,
        match="Phase 6 entry evidence drift",
    ):
        workspace_memory._verify_phase6_entry(ROOT)


def test_factory_is_sealed_and_requires_complete_host_bindings(
    fixture: Fixture,
) -> None:
    with pytest.raises(WorkspaceMemoryV1ContractError, match="sealed feature gate"):
        create_workspace_memory_adapter_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(
        WorkspaceMemoryV1ContractError,
        match="complete host bindings",
    ):
        create_workspace_memory_adapter_v1(
            gate=WorkspaceMemoryFeatureGateV1(True),
        )
    with pytest.raises(
        WorkspaceMemoryV1ContractError,
        match="non-legacy workspace",
    ):
        create_workspace_memory_adapter_v1(
            gate=WorkspaceMemoryFeatureGateV1(True),
            registry=fixture.registry,
            memory_store=fixture.memory,
            workspace_id="legacy-default",
            principal_id="owner:pedro",
            allowed_sensitivities=("public",),
            integrity_key=KEY,
        )


def test_authorized_workspace_results_are_ranked_after_hard_filters(
    fixture: Fixture,
) -> None:
    first = _remember(
        fixture,
        "Cyryx roadmap confirms the Onyx workspace memory milestone",
        source="cyryx-roadmap",
        salience=0.8,
    )
    second = _remember(
        fixture,
        "Onyx workspace memory implementation note",
        source="cyryx-note",
        salience=0.5,
    )
    _attach(fixture, first)
    _attach(fixture, second)

    results = _adapter(fixture).search(
        WorkspaceMemoryQueryV1("Cyryx roadmap workspace memory"),
        now_ms=NOW_MS,
    )

    assert [item.memory_id for item in results] == [first.id, second.id]
    assert all(item.workspace_id == "cyryx-main" for item in results)
    assert all(item.principal_id == "owner:pedro" for item in results)
    assert all(item.memory_status == "approved" for item in results)
    assert all(item.freshness == "fresh" for item in results)
    assert all(item.content_trust == "untrusted_data" for item in results)
    assert all(item.valid_until_ms == NOW_MS + 10_000 for item in results)
    assert all(item.fresh_until_ms == NOW_MS + 5_000 for item in results)
    assert all(len(item.memory_sha256) == 64 for item in results)
    assert results[0].score > results[1].score


def test_extremely_similar_other_workspace_record_is_never_returned(
    fixture: Fixture,
) -> None:
    allowed = _remember(
        fixture,
        "Cyryx portfolio status",
        source="cyryx-status",
        salience=0.2,
    )
    forbidden = _remember(
        fixture,
        "Cyryx portfolio status Cyryx portfolio status Cyryx portfolio status",
        source="client-confidential",
        salience=1.0,
    )
    _attach(fixture, allowed, workspace_id="cyryx-main")
    _attach(fixture, forbidden, workspace_id="client-one")

    results = _adapter(fixture).search(
        WorkspaceMemoryQueryV1("Cyryx portfolio status"),
        now_ms=NOW_MS,
    )

    assert [item.memory_id for item in results] == [allowed.id]
    assert forbidden.id not in {item.memory_id for item in results}


def test_principal_and_sensitivity_filters_run_before_ranking(
    fixture: Fixture,
) -> None:
    wrong_principal = _remember(
        fixture,
        "Onyx secret launch priority",
        source="other-principal",
        salience=1.0,
    )
    confidential = _remember(
        fixture,
        "Onyx secret launch priority confidential",
        source="confidential",
        salience=1.0,
    )
    public = _remember(
        fixture,
        "Onyx launch priority",
        source="public",
        salience=0.4,
    )
    _attach(fixture, wrong_principal, principal_id="owner:other")
    _attach(fixture, confidential, sensitivity="confidential")
    _attach(fixture, public, sensitivity="public")

    results = _adapter(fixture).search(
        WorkspaceMemoryQueryV1("Onyx secret launch priority"),
        now_ms=NOW_MS,
    )

    assert [item.memory_id for item in results] == [public.id]


@pytest.mark.parametrize(
    ("memory_status", "source_status", "valid_from", "valid_until"),
    [
        ("candidate", "available", NOW_MS - 1, NOW_MS + 1),
        ("superseded", "available", NOW_MS - 1, NOW_MS + 1),
        ("rejected", "available", NOW_MS - 1, NOW_MS + 1),
        ("approved", "deleted", NOW_MS - 1, NOW_MS + 1),
        ("approved", "revoked", NOW_MS - 1, NOW_MS + 1),
        ("approved", "available", NOW_MS + 1, NOW_MS + 2),
        ("approved", "available", NOW_MS - 2, NOW_MS),
    ],
)
def test_invalid_unapproved_or_unavailable_records_are_excluded(
    fixture: Fixture,
    memory_status: str,
    source_status: str,
    valid_from: int,
    valid_until: int,
) -> None:
    record = _remember(
        fixture,
        f"filtered {memory_status} {source_status} {valid_from}",
        source=f"filtered-{memory_status}-{source_status}-{valid_from}",
    )
    _attach(
        fixture,
        record,
        memory_status=memory_status,
        source_status=source_status,
        valid_from_ms=valid_from,
        valid_until_ms=valid_until,
        fresh_until_ms=max(valid_from, NOW_MS + 10),
    )
    assert (
        _adapter(fixture).search(
            WorkspaceMemoryQueryV1("filtered"),
            now_ms=NOW_MS,
        )
        == ()
    )


def test_stale_memory_is_excluded_by_default_and_labeled_when_requested(
    fixture: Fixture,
) -> None:
    record = _remember(
        fixture,
        "stale roadmap status requires revalidation",
        source="stale-roadmap",
    )
    _attach(
        fixture,
        record,
        fresh_until_ms=NOW_MS - 1,
    )
    adapter = _adapter(fixture)
    assert (
        adapter.search(
            WorkspaceMemoryQueryV1("roadmap status"),
            now_ms=NOW_MS,
        )
        == ()
    )
    results = adapter.search(
        WorkspaceMemoryQueryV1("roadmap status", include_stale=True),
        now_ms=NOW_MS,
    )
    assert len(results) == 1
    assert results[0].freshness == "stale"


def test_duplicate_json_or_forged_hmac_denies_entire_retrieval(
    fixture: Fixture,
) -> None:
    record = _remember(
        fixture,
        "integrity protected memory",
        source="integrity",
    )
    payload = _attach(fixture, record)
    connection = fixture.control._require_connection()
    forged = dict(payload)
    forged["sensitivity"] = "public"
    connection.execute(
        "UPDATE memory_metadata SET payload_json=? WHERE source_memory_id=?",
        (json.dumps(forged, sort_keys=True), record.id),
    )
    with pytest.raises(
        WorkspaceMemoryV1Denied,
        match="metadata integrity denied",
    ):
        _adapter(fixture).search(
            WorkspaceMemoryQueryV1("integrity"),
            now_ms=NOW_MS,
        )

    duplicate = '{"schema":"a","schema":"b"}'
    connection.execute(
        "UPDATE memory_metadata SET payload_json=? WHERE source_memory_id=?",
        (duplicate, record.id),
    )
    with pytest.raises(WorkspaceMemoryV1Denied, match="duplicate metadata key"):
        _adapter(fixture).search(
            WorkspaceMemoryQueryV1("integrity"),
            now_ms=NOW_MS,
        )


def test_memory_content_digest_drift_is_denied(fixture: Fixture) -> None:
    record = _remember(
        fixture,
        "original approved content",
        source="digest-source",
    )
    _attach(fixture, record)
    connection = fixture.memory._connect()
    try:
        connection.execute(
            "UPDATE memories SET content=? WHERE id=?",
            ("tampered content", record.id),
        )
    finally:
        connection.close()
    adapter = _adapter(fixture)
    with pytest.raises(
        WorkspaceMemoryV1Denied,
        match="memory content drift denied",
    ):
        adapter.search(
            WorkspaceMemoryQueryV1("tampered"),
            now_ms=NOW_MS,
        )


def test_ambiguous_cross_workspace_ownership_is_excluded(
    fixture: Fixture,
) -> None:
    record = _remember(
        fixture,
        "shared-looking but ambiguous memory",
        source="ambiguous",
    )
    _attach(fixture, record, workspace_id="cyryx-main")
    _attach(fixture, record, workspace_id="client-one")
    assert (
        _adapter(fixture).search(
            WorkspaceMemoryQueryV1("ambiguous memory"),
            now_ms=NOW_MS,
        )
        == ()
    )


def test_adapter_denies_workspace_sidecar_or_memory_binding_drift(
    fixture: Fixture,
    tmp_path: Path,
) -> None:
    record = _remember(fixture, "binding attestation", source="binding")
    _attach(fixture, record)
    adapter = _adapter(fixture)

    fixture.registry.set_active("cyryx-main", False)
    with pytest.raises(
        WorkspaceMemoryV1Denied,
        match="workspace attestation denied",
    ):
        adapter.search(
            WorkspaceMemoryQueryV1("binding"),
            now_ms=NOW_MS,
        )

    fixture.registry.set_active("cyryx-main", True)
    second = _adapter(fixture)
    fixture.memory.path = tmp_path / "different.sqlite3"
    with pytest.raises(WorkspaceMemoryV1Denied, match="binding drift denied"):
        second.search(
            WorkspaceMemoryQueryV1("binding"),
            now_ms=NOW_MS,
        )


def test_search_is_read_only_and_never_uses_global_memory_search_or_list(
    fixture: Fixture,
) -> None:
    record = _remember(
        fixture,
        "read only workspace retrieval",
        source="read-only",
    )
    _attach(fixture, record)
    adapter = _adapter(fixture)
    paths = (fixture.control.path, fixture.memory.path)
    before = {
        path: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in paths
    }
    with (
        patch.object(
            MemoryStore, "search", side_effect=AssertionError("global search")
        ),
        patch.object(MemoryStore, "list", side_effect=AssertionError("global list")),
    ):
        results = adapter.search(
            WorkspaceMemoryQueryV1("workspace retrieval"),
            now_ms=NOW_MS,
        )
    after = {
        path: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in paths
    }
    assert [item.memory_id for item in results] == [record.id]
    assert after == before


def test_source_contains_only_id_scoped_memory_select() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "core/phase7_workspace_memory_v1.py"
    ).read_text(encoding="utf-8")
    assert "SELECT * FROM memories WHERE id=?" in source
    assert "SELECT * FROM memories LIMIT" not in source
    assert ".search(" not in source
    assert ".list(" not in source
    assert "mode=ro" in source


def test_query_and_policy_contracts_reject_broad_or_restricted_inputs(
    fixture: Fixture,
) -> None:
    with pytest.raises(WorkspaceMemoryV1ContractError):
        WorkspaceMemoryQueryV1("")
    with pytest.raises(WorkspaceMemoryV1ContractError):
        WorkspaceMemoryQueryV1("query", limit=0)
    with pytest.raises(
        WorkspaceMemoryV1ContractError,
        match="non-restricted tuple",
    ):
        _adapter(fixture, sensitivities=("public", "restricted"))
    with pytest.raises(WorkspaceMemoryV1ContractError, match="integrity key"):
        create_workspace_memory_adapter_v1(
            gate=WorkspaceMemoryFeatureGateV1(True),
            registry=fixture.registry,
            memory_store=fixture.memory,
            workspace_id="cyryx-main",
            principal_id="owner:pedro",
            allowed_sensitivities=("public",),
            integrity_key=b"short",
        )
