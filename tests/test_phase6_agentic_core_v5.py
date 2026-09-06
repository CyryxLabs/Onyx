from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from core.missions import MissionStore
from core.permission_broker import set_permission_callback
from core.phase6_agentic_core_v1 import (
    DataClassV1,
    GoalV1,
    MissionBudgetV1,
    PlanStateV1,
    WorkspaceScopeV1,
)
from core.phase6_agentic_core_v2 import artifact_root_v2
from core.phase6_agentic_core_v5 import (
    AgenticCoreV5,
    AgenticCoreV5ContractError,
    AgenticCoreV5Denied,
    AgenticCoreV5Error,
    AgenticFeatureGateV5,
    AgenticStateStoreV5,
    normalized_sql_v5,
    sql_tokens_v5,
)
from scripts.verify_legacy_evidence_retirement_v1 import (
    classify_historical_artifact,
    verify_recorded_manifest,
)


FROZEN_V4 = {
    "core/phase6_agentic_core_v4.py": "cfa738a42c02a5134344e2ac6364af93b63249fc1ab929d691dfeab2596daf57",
    "tests/test_phase6_agentic_core_v4.py": "1d2b5f39b426614ccdb7d977628cd9f3b384cdfe458b2f93e34f49a805b8b401",
    "docs/onyx/adrs/ADR-0013-phase6-agentic-core-v4-authenticated-state-and-process-isolation.md": "2666c3af3c27e5612aae7232d055f7d9da49e8a30db928d587dcb72df894c208",
    "docs/onyx/checkpoints/phase6-agentic-core-v4/PHASE6_AGENTIC_CORE_V4_CHECKPOINT.md": "eb436958a09dff135ee1349365baeab8342582439a16dc7d6bd2d0c0ce45a6bc",
    "docs/onyx/checkpoints/phase6-agentic-core-v4/manifest.json": "f831f52ff257b877f6dbb7b2eac279cee7c2ffd6c84b5761998ac37689e14315",
}


def _state(tmp_path: Path) -> AgenticStateStoreV5:
    return AgenticStateStoreV5(tmp_path / "plans.sqlite3", AgenticFeatureGateV5(True))


def _goal() -> GoalV1:
    return GoalV1(
        "goal_phase6_v5",
        "corr_phase6_v5",
        "workspace_personal",
        "Inspect local runtime",
        ("runtime observed",),
        ("local metadata",),
        ("no network",),
        DataClassV1.INTERNAL,
        MissionBudgetV1(
            max_steps=3,
            wall_seconds=30.0,
            max_retries_per_step=0,
            max_repair_cycles=1,
            max_compute_seconds=5.0,
        ),
    )


def _step():
    return {
        "step_id": "step_v5_status",
        "capability": "local_system_status",
        "arguments": {},
        "dependencies": [],
        "timeout_seconds": 2.0,
        "max_retries": 0,
        "postconditions": ["runtime_status_observed"],
    }


def _verified_runner(_tool: str, _arguments: dict[str, object], _key: str):
    return {
        "status": "succeeded",
        "data": {"label": "v5"},
        "evidence": [],
        "postconditions": [{"name": "runtime_status_observed", "satisfied": True}],
        "waiting_for": None,
    }


def _rewrite_schema(state: AgenticStateStoreV5, transform) -> str:
    path = state.coordination_path
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in AgenticStateStoreV5._DDL:
            connection.execute(transform(statement))
        connection.execute("INSERT INTO metadata(schema_version) VALUES(5)")
        connection.execute("PRAGMA user_version=5")
        connection.commit()
    finally:
        connection.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_reviewed_artifacts_remain_exactly_frozen():
    root = Path(__file__).resolve().parents[1]
    states = {
        path: classify_historical_artifact(root, path, digest)["state"]
        for path, digest in FROZEN_V4.items()
    }
    assert states["tests/test_phase6_agentic_core_v4.py"] == (
        "superseded-not-rebound"
    )
    assert set(states.values()) <= {"preserved-exact", "superseded-not-rebound"}


def test_v5_is_strict_default_off_and_not_live_wired(tmp_path: Path):
    assert AgenticFeatureGateV5.from_environ({}).enabled is False
    assert (
        AgenticFeatureGateV5.from_environ(
            {"ONYX_PHASE6_AGENTIC_CORE_V5": "true"}
        ).enabled
        is True
    )
    with pytest.raises(AgenticCoreV5Denied):
        AgenticStateStoreV5(tmp_path / "off.sqlite3", AgenticFeatureGateV5(False))
    root = Path(__file__).resolve().parents[1]
    for path in ("main.py", "ui.py", "dashboard/server.py"):
        assert "phase6_agentic_core_v5" not in (root / path).read_text(encoding="utf-8")


def test_only_outside_literal_whitespace_and_keyword_case_are_normalized():
    first = """CREATE  TABLE t ("Case" TEXT CHECK("Case"='A  B''C'),
    payload BLOB CHECK(payload=X'Ab 0F'))"""
    second = """create table t("Case" text check ( "Case" = 'A  B''C' ) ,
    payload blob check ( payload = x 'Ab 0F' ) )"""
    assert sql_tokens_v5(first) == sql_tokens_v5(second)
    assert normalized_sql_v5(first) == normalized_sql_v5(second)


@pytest.mark.parametrize(
    ("original", "changed"),
    [
        ("CHECK(x='Alpha')", "CHECK(x='alpha')"),
        ("CHECK(x='A  B')", "CHECK(x='A B')"),
        ("CHECK(x='it''s')", "CHECK(x='its')"),
        ('CREATE TABLE t("Case" TEXT)', 'CREATE TABLE t("case" TEXT)'),
        ("CREATE TABLE t(`Case` TEXT)", "CREATE TABLE t(`case` TEXT)"),
        ("CREATE TABLE t([Case] TEXT)", "CREATE TABLE t([case] TEXT)"),
        ("CHECK(x=X'Ab0F')", "CHECK(x=X'ab0f')"),
        ("CREATE/*Alpha Comment*/TABLE t(x)", "CREATE/*alpha Comment*/TABLE t(x)"),
        ("CREATE-- Alpha Comment\nTABLE t(x)", "CREATE-- alpha Comment\nTABLE t(x)"),
    ],
)
def test_literals_identifiers_escapes_blobs_and_comments_remain_byte_sensitive(
    original: str, changed: str
):
    assert sql_tokens_v5(original) != sql_tokens_v5(changed)


@pytest.mark.parametrize(
    "sql",
    ["SELECT 'open", 'SELECT "open', "SELECT `open", "SELECT [open", "SELECT /*open"],
)
def test_unterminated_lexical_states_fail_closed(sql: str):
    with pytest.raises(AgenticCoreV5ContractError):
        sql_tokens_v5(sql)


def test_benign_sqlite_whitespace_formatting_is_explicitly_equivalent(tmp_path: Path):
    state = _state(tmp_path)

    def add_spacing(statement: str) -> str:
        return statement.replace("CREATE ", "CREATE   ", 1)

    _rewrite_schema(state, add_spacing)
    reopened = AgenticStateStoreV5(state.plans.path, AgenticFeatureGateV5(True))
    assert reopened.schema_signature == state.schema_signature


@pytest.mark.parametrize(
    "tamper", ["literal_case", "literal_space", "escape", "quoted", "comment", "index"]
)
def test_same_name_semantic_or_lexical_schema_changes_fail_before_writes(
    tmp_path: Path, tamper: str
):
    state = _state(tmp_path)

    def transform(statement: str) -> str:
        if tamper == "literal_case":
            return statement.replace("'bound'", "'BOUND'")
        if tamper == "literal_space":
            return statement.replace("v5 lineage", "v5  lineage")
        if tamper == "escape":
            return statement.replace("is immutable", "isn''t mutable")
        if tamper == "quoted":
            return statement.replace(
                "CREATE TABLE runtime_plans", 'CREATE TABLE "runtime_plans"'
            )
        if tamper == "comment" and statement.startswith("CREATE INDEX budget_expired"):
            return statement.replace(
                "active_deadline_wall,account_id",
                "active_deadline_wall/*V5 Exact*/,account_id",
            )
        if tamper == "index":
            return statement.replace(
                "runtime_plans(terminal,updated_at,plan_id)",
                "runtime_plans(plan_id,terminal,updated_at)",
            )
        return statement

    before = _rewrite_schema(state, transform)
    with pytest.raises(AgenticCoreV5Error, match="authentication failed"):
        AgenticStateStoreV5(state.plans.path, AgenticFeatureGateV5(True))
    assert hashlib.sha256(state.coordination_path.read_bytes()).hexdigest() == before


def test_v5_preserves_v4_end_to_end_closure(tmp_path: Path):
    state = _state(tmp_path)
    missions = MissionStore(tmp_path / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    with AgenticCoreV5(state, missions, scope) as core:
        projection = core.submit(_goal(), "request:v5:e2e:001", [_step()])
        admission = core.materialize(projection.plan_id)
        assert admission.mission_id is not None
        set_permission_callback(lambda request: request["digest"])
        missions.approve(admission.mission_id)
        set_permission_callback(None)
        assert (
            core.execute_approved(projection.plan_id, _verified_runner).state
            == "succeeded"
        )
        assert state.get_projection(projection.plan_id).state is PlanStateV1.COMPLETE
    assert core.closed is True
    assert core._executor.worker_pid is None


def test_checkpoint_manifest_recomputes_artifact_root():
    root = Path(__file__).resolve().parents[1]
    result = verify_recorded_manifest(
        root,
        "docs/onyx/checkpoints/phase6-agentic-core-v5/manifest.json",
        "b879f2d3266601ec76fec2fa08c4dcb6364217d6b23d7d63811d700c769b8958",
        "9913b6731fd4ccdb103ce511ddb0b4133be456b4acd878dd45091f522d9d1fe4",
        artifact_root_v2,
    )
    assert result["artifacts"] == 5
    assert result["states"]["tests/test_phase6_agentic_core_v5.py"] == (
        "superseded-not-rebound"
    )
