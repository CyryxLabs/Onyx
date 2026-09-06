from __future__ import annotations

import hashlib
from pathlib import Path
import statistics
import time
import tracemalloc

import pytest

from core.phase6_agentic_core_v6 import normalized_sql_v6, sql_tokens_v6
from scripts import verify_phase6_agentic_core_v6_acceptance as acceptance
from scripts.verify_legacy_evidence_retirement_v1 import (
    classify_historical_artifact,
)


def test_external_acceptance_validates_exact_frozen_candidate() -> None:
    result = acceptance.verify()
    assert result["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert result["manifest_sha256"] == acceptance.V6_MANIFEST_SHA256
    assert result["artifact_root_sha256"] == acceptance.V6_ROOT_SHA256
    assert result["mission_store_sha256"] == acceptance.MISSION_STORE_SHA256
    assert result["closure"] == {
        "v6_artifacts": 5,
        "historical_artifacts": {
            "v1": 4,
            "v2": 6,
            "v3": 6,
            "v4": 5,
            "v5": 5,
        },
    }
    assert result["severity"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert (
        result["scope"] == "phase6-agentic-core-v6-isolated-default-off-unwired-handoff"
    )


@pytest.mark.parametrize(
    ("relative", "expected"),
    tuple(acceptance.V6_ANCHORS.items())
    + (
        (acceptance.V6_MANIFEST, acceptance.V6_MANIFEST_SHA256),
        (acceptance.MISSION_STORE, acceptance.MISSION_STORE_SHA256),
    ),
)
def test_v6_candidate_anchors_are_exact(relative: str, expected: str) -> None:
    state = classify_historical_artifact(
        acceptance.PROJECT,
        relative,
        expected,
        historical_bytes=(89747 if relative == acceptance.MISSION_STORE else None),
    )
    if relative in {
        "tests/test_phase6_agentic_core_v6.py",
        acceptance.MISSION_STORE,
    }:
        assert state["state"] == "superseded-not-rebound"
    else:
        assert state["state"] == "preserved-exact"


def test_acceptance_manifest_binds_only_the_external_record() -> None:
    digest, relative = acceptance._manifest_line(
        acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST)
    )
    assert relative == acceptance.ACCEPTANCE_RECORD
    assert (
        digest
        == hashlib.sha256((acceptance.PROJECT / relative).read_bytes()).hexdigest()
    )


def test_malformed_or_tampered_acceptance_manifest_fails_closed() -> None:
    with pytest.raises(acceptance.AgenticCoreV6AcceptanceError):
        acceptance._manifest_line("bad\n")
    record = acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_RECORD)
    assert acceptance.V6_MANIFEST_SHA256 in record
    assert acceptance.V6_ROOT_SHA256 in record
    assert acceptance.MISSION_STORE_SHA256 in record


def test_v1_v5_remain_exact_rejected_and_root_closed() -> None:
    result = acceptance._verify_candidate_anchors(acceptance.PROJECT)
    assert result["historical_artifacts"] == {
        "v1": 4,
        "v2": 6,
        "v3": 6,
        "v4": 5,
        "v5": 5,
    }
    for version, expected in acceptance.REJECTIONS.items():
        relative = f"docs/onyx/rejections/PHASE6_AGENTIC_CORE_V{version}_REJECTION.md"
        assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_v6_remains_default_off_unwired_and_provider_free() -> None:
    assert acceptance._verify_unwired_and_provider_free(acceptance.PROJECT) >= 2
    manifest = acceptance._text(acceptance.PROJECT, acceptance.V6_MANIFEST)
    assert '"default": "off"' in manifest
    assert '"live_wiring": false' in manifest
    assert '"network_calls": false' in manifest
    assert '"provider_calls": false' in manifest


def test_representative_unicode_and_resource_perf_budget() -> None:
    pairs = (
        ("CREATE TABLE K(x)", "CREATE TABLE K(x)"),
        ("CREATE TABLE t(x) -- K\n", "CREATE TABLE t(x) -- K\n"),
        ("CREATE TABLE t(x\u00a0TEXT)", "CREATE TABLE t(x TEXT)"),
        ("CREATE TABLE Α(x)", "CREATE TABLE A(x)"),
        ("CREATE TABLE а(x)", "CREATE TABLE a(x)"),
        ("CREATE TABLE Ｋ(x)", "CREATE TABLE K(x)"),
        ("CREATE TABLE ß(x)", "CREATE TABLE SS(x)"),
        ("CREATE TABLE Café(x)", "CREATE TABLE CAFÉ(x)"),
    )
    for left, right in pairs:
        assert normalized_sql_v6(left) != normalized_sql_v6(right)
    assert normalized_sql_v6("CREATE\t\r\n\fTABLE t(x)") == normalized_sql_v6(
        "create table t(x)"
    )
    assert normalized_sql_v6("CREATE\vTABLE t(x)") != normalized_sql_v6(
        "CREATE TABLE t(x)"
    )

    statement = (
        "CREATE TABLE Kelvin(Α TEXT, а TEXT, Ｋ TEXT, ß TEXT, Café TEXT) "
        "/* NBSP:\u00a0 VT:\v */"
    )
    samples: list[float] = []
    tracemalloc.start()
    try:
        for _ in range(2_000):
            started = time.perf_counter_ns()
            tuple(sql_tokens_v6(statement))
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    p95 = statistics.quantiles(samples, n=100, method="inclusive")[94]
    assert p95 < 20.0
    assert peak < 8 * 1024 * 1024


def test_noncanonical_and_linked_paths_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(acceptance.AgenticCoreV6AcceptanceError):
        acceptance._canonical_relative("../core/phase6_agentic_core_v6.py")
    target = tmp_path / "target.txt"
    target.write_text("target\n", encoding="utf-8", newline="\n")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(acceptance.AgenticCoreV6AcceptanceError):
        acceptance._regular_path(tmp_path, "link.txt")
