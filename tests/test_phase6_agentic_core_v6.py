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
from core.phase6_agentic_core_v6 import (
    AgenticCoreV6,
    AgenticCoreV6ContractError,
    AgenticCoreV6Denied,
    AgenticCoreV6Error,
    AgenticFeatureGateV6,
    AgenticStateStoreV6,
    _schema_signature_v6,
    normalized_sql_v6,
    sql_tokens_v6,
)
from scripts.verify_legacy_evidence_retirement_v1 import (
    classify_historical_artifact,
    verify_recorded_manifest,
)


FROZEN_V5 = {
    "core/phase6_agentic_core_v5.py": "1b8936d96f836263607be5d9c2d00048362f38d35f0afdcac273c1dd0e3c4787",
    "tests/test_phase6_agentic_core_v5.py": "aba9ef6def4b242fc598df70117c4c934949f77f88215bf72738f3df69931faa",
    "docs/onyx/adrs/ADR-0014-phase6-agentic-core-v5-lexical-schema-authentication.md": "20fdd0dfec4e96f2f167f5f7519709093e4137107bedacbbaa16728629e53783",
    "docs/onyx/checkpoints/phase6-agentic-core-v5/PHASE6_AGENTIC_CORE_V5_CHECKPOINT.md": "a5c368d0367d688bae4423858138994787edc72fb5112c1e9803fc623f98cbdc",
    "docs/onyx/checkpoints/phase6-agentic-core-v5/manifest.json": "b879f2d3266601ec76fec2fa08c4dcb6364217d6b23d7d63811d700c769b8958",
}


def _state(tmp_path: Path) -> AgenticStateStoreV6:
    return AgenticStateStoreV6(tmp_path / "plans.sqlite3", AgenticFeatureGateV6(True))


def _rewrite_schema(state: AgenticStateStoreV6, transform) -> str:
    path = state.coordination_path
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in AgenticStateStoreV6._DDL:
            connection.execute(transform(statement))
        connection.execute("INSERT INTO metadata(schema_version) VALUES(6)")
        connection.execute("PRAGMA user_version=6")
        connection.commit()
    finally:
        connection.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _goal() -> GoalV1:
    return GoalV1(
        "goal_phase6_v6",
        "corr_phase6_v6",
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
        "step_id": "step_v6_status",
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
        "data": {"label": "v6"},
        "evidence": [],
        "postconditions": [{"name": "runtime_status_observed", "satisfied": True}],
        "waiting_for": None,
    }


def test_v5_reviewed_artifacts_remain_exactly_frozen():
    root = Path(__file__).resolve().parents[1]
    states = {
        path: classify_historical_artifact(root, path, digest)["state"]
        for path, digest in FROZEN_V5.items()
    }
    assert states["tests/test_phase6_agentic_core_v5.py"] == (
        "superseded-not-rebound"
    )
    assert set(states.values()) <= {"preserved-exact", "superseded-not-rebound"}


def test_v6_is_strict_default_off_and_not_live_wired(tmp_path: Path):
    assert AgenticFeatureGateV6.from_environ({}).enabled is False
    assert (
        AgenticFeatureGateV6.from_environ(
            {"ONYX_PHASE6_AGENTIC_CORE_V6": "true"}
        ).enabled
        is True
    )
    with pytest.raises(AgenticCoreV6Denied):
        AgenticStateStoreV6(tmp_path / "off.sqlite3", AgenticFeatureGateV6(False))
    root = Path(__file__).resolve().parents[1]
    for path in ("main.py", "ui.py", "dashboard/server.py"):
        assert "phase6_agentic_core_v6" not in (root / path).read_text(encoding="utf-8")


def test_only_proven_ascii_whitespace_and_ascii_case_are_normalized():
    canonical = "CREATE TABLE t(x TEXT CHECK(x='A  B'))"
    formatted = "create\t\r\n\f table t ( x text check ( x = 'A  B' ) )"
    assert sql_tokens_v6(canonical) == sql_tokens_v6(formatted)
    assert normalized_sql_v6(canonical) == normalized_sql_v6(formatted)


def test_kelvin_sign_never_normalizes_to_ascii_k():
    assert sql_tokens_v6("CREATE TABLE K(x)") == sql_tokens_v6("create table k(x)")
    assert sql_tokens_v6("CREATE TABLE K(x)") != sql_tokens_v6("CREATE TABLE K(x)")


def test_nbsp_and_vertical_tab_are_not_ascii_sql_whitespace():
    ascii_space = sql_tokens_v6("CREATE TABLE t(x)")
    assert ascii_space != sql_tokens_v6("CREATE\u00a0TABLE t(x)")
    assert ascii_space != sql_tokens_v6("CREATE\vTABLE t(x)")


@pytest.mark.parametrize(
    ("ascii_text", "confusable"),
    [
        ("A", "Α"),
        ("a", "а"),
        ("B", "Β"),
        ("O", "О"),
        ("K", "Ｋ"),
        ("SS", "ß"),
    ],
)
def test_non_ascii_confusables_remain_exact(ascii_text: str, confusable: str):
    assert sql_tokens_v6(f"CREATE TABLE {ascii_text}(x)") != sql_tokens_v6(
        f"CREATE TABLE {confusable}(x)"
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("CREATE TABLE Café(x)", "CREATE TABLE CAFÉ(x)"),
        ("CREATE TABLE Ångström(x)", "CREATE TABLE ångström(x)"),
        ("CREATE TABLE naïve(x)", "CREATE TABLE naive(x)"),
    ],
)
def test_non_ascii_identifier_codepoints_are_never_casefolded(first: str, second: str):
    assert sql_tokens_v6(first) != sql_tokens_v6(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("CHECK(x='K  A''B')", "CHECK(x='K  A''B')"),
        ('CREATE TABLE t("K" TEXT)', 'CREATE TABLE t("K" TEXT)'),
        ("CREATE TABLE t(`K` TEXT)", "CREATE TABLE t(`K` TEXT)"),
        ("CREATE TABLE t([K] TEXT)", "CREATE TABLE t([K] TEXT)"),
        ("CREATE/* K */TABLE t(x)", "CREATE/* K */TABLE t(x)"),
        ("CREATE-- K\nTABLE t(x)", "CREATE-- K\nTABLE t(x)"),
    ],
)
def test_v5_literal_identifier_comment_and_escape_closures_remain_exact(
    first: str, second: str
):
    assert sql_tokens_v6(first) != sql_tokens_v6(second)


@pytest.mark.parametrize(
    "sql",
    ["SELECT 'open", 'SELECT "open', "SELECT `open", "SELECT [open", "SELECT /*open"],
)
def test_unterminated_states_still_fail_closed(sql: str):
    with pytest.raises(AgenticCoreV6ContractError):
        sql_tokens_v6(sql)


def test_semantically_distinct_valid_same_name_schemas_have_distinct_signatures():
    ascii_schema = sqlite3.connect(":memory:")
    unicode_schema = sqlite3.connect(":memory:")
    try:
        ascii_schema.execute("CREATE TABLE t(value K)")
        unicode_schema.execute("CREATE TABLE t(value K)")
        assert _schema_signature_v6(ascii_schema) != _schema_signature_v6(
            unicode_schema
        )
        assert ascii_schema.execute("PRAGMA table_info(t)").fetchone()[1] == "value"
        assert unicode_schema.execute("PRAGMA table_info(t)").fetchone()[1] == "value"
    finally:
        ascii_schema.close()
        unicode_schema.close()


def test_unicode_type_tamper_fails_before_writes_with_same_object_names(tmp_path: Path):
    state = _state(tmp_path)

    def transform(statement: str) -> str:
        return statement.replace("limit_seconds REAL", "limit_seconds KEAL")

    before = _rewrite_schema(state, transform)
    with pytest.raises(AgenticCoreV6Error, match="authentication failed"):
        AgenticStateStoreV6(state.plans.path, AgenticFeatureGateV6(True))
    assert hashlib.sha256(state.coordination_path.read_bytes()).hexdigest() == before


def test_benign_ascii_sqlite_formatting_reopens(tmp_path: Path):
    state = _state(tmp_path)

    def transform(statement: str) -> str:
        return statement.replace("CREATE ", "create\t\r\n\f", 1)

    _rewrite_schema(state, transform)
    reopened = AgenticStateStoreV6(state.plans.path, AgenticFeatureGateV6(True))
    assert reopened.schema_signature == state.schema_signature


def test_v6_preserves_v4_v5_end_to_end_closure(tmp_path: Path):
    state = _state(tmp_path)
    missions = MissionStore(tmp_path / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    with AgenticCoreV6(state, missions, scope) as core:
        projection = core.submit(_goal(), "request:v6:e2e:001", [_step()])
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
        "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json",
        "cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15",
        "ca7d7f3281d9926848696e25befe63373738596dbc7e9b5bdaf95325922b06b0",
        artifact_root_v2,
    )
    assert result["artifacts"] == 5
    assert result["states"]["tests/test_phase6_agentic_core_v6.py"] == (
        "superseded-not-rebound"
    )
