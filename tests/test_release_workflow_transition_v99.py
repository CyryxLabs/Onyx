"""V99 preparation checks and post-seal source/tamper acceptance.

Before the parent's seal, run only '-k preparation'. The remaining tests must
fail closed until real V99 pins and the authorized fixture exist; no test
generates or seals the project fixture.
"""

from importlib import import_module
from pathlib import Path
import shutil

import pytest

from scripts import generate_release_workflow_v99 as generator
from scripts import verify_release_workflow_v99 as verifier
from scripts import hud_test_succession_v1 as hud_succession
from scripts.r11_memory_evidence_supplement_v3 import EDGES
from scripts.source_test_succession_v1 import load_record
from scripts.verify_release_workflow_v70 import _entries, _json, _root, _sha256
from scripts.verify_release_workflow_v99 import (
    PROJECT, V98, V98_ROOT_SHA256, V98_SHA256, V99,
    ReleaseWorkflowV99Error, verify_release_workflow_v99,
)


def test_preparation_predecessor_pins_and_coverage_plan():
    old = _json(PROJECT / V98)
    assert _sha256(PROJECT / V98) == V98_SHA256
    assert old["current_root_sha256"] == _root(old, 98) == V98_ROOT_SHA256
    assert len(_entries(old)) == 609
    succession = load_record(PROJECT)
    hud_record = hud_succession.load_record(PROJECT)
    paths = set(generator.planned_paths(old, succession, hud_record))
    assert set(succession["bindings"]).issubset(paths)
    assert set(hud_record["bindings"]).issubset(paths)
    assert set(generator.HISTORICAL_FIXTURES).issubset(paths)
    assert {
        V98.as_posix(), "scripts/verify_release_workflow_v98.py",
        "scripts/generate_release_workflow_v99.py",
        "tests/test_release_workflow_transition_v99.py", "scripts/build_release.py",
        "docs/onyx/BLOCKER_RESOLUTION_20260905.md",
        "docs/stories/ONYX-SECOND-BRAIN-PHONE-TWO-SPRINTS-V1.story.md",
    }.issubset(paths)
    assert V99.as_posix() not in paths
    assert "scripts/verify_release_workflow_v99.py" not in paths
    assert all((PROJECT / path).is_file() for path in generator.ADDITIONS)


def test_preparation_succession_routes_terminate_at_current_suites():
    succession = load_record(PROJECT)
    routes = succession["routes"]
    assert len(routes) == len({row["node"] for row in routes}) == 37
    assert len(succession["bindings"]) == 61
    assert {kind: sum(row["kind"] == kind for row in routes)
            for kind in ("release", "hud", "documentation")} == {
        "release": 34, "hud": 2, "documentation": 1,
    }
    routed_sources = {row["node"].split("::", 1)[0] for row in routes}
    successors = {row["successor"] for row in routes}
    assert successors == {
        "tests/test_release_workflow_transition_v99.py",
        "tests/test_hud_conversation_successor_v48.py",
        "tests/test_current_capability_status_v2.py",
    }
    assert routed_sources.isdisjoint(successors)
    # Binding either the current fixture or its pin-bearing verifier here would
    # create a digest cycle: V99 -> registry -> V99 (or its own verifier).
    assert {V99.as_posix(), "scripts/verify_release_workflow_v99.py"}.isdisjoint(
        succession["bindings"]
    )


def test_preparation_two_hud_routes_preserve_negatives_and_have_no_cycles():
    record = hud_succession.load_record(PROJECT)
    assert len(record["routes"]) == 2
    assert len(record["bindings"]) == 11
    assert tuple(row["node"] for row in record["routes"]) == hud_succession.NODES
    assert tuple(record["retained_nodes"]) == hud_succession.RETAINED_NODES
    source_record = load_record(PROJECT)
    routes = [*source_record["routes"], *record["routes"]]
    nodes = {row["node"] for row in routes}
    assert len(nodes) == 39
    assert nodes.isdisjoint(record["retained_nodes"])
    assert {row["successor"] for row in routes}.isdisjoint(
        node.split("::", 1)[0] for node in nodes
    )
    assert {V99.as_posix(), "scripts/verify_release_workflow_v99.py"}.isdisjoint(
        record["bindings"]
    )
    for path in source_record["bindings"].keys() & record["bindings"].keys():
        assert source_record["bindings"][path] == record["bindings"][path]


@pytest.mark.parametrize("loader", ["load_record", "load_hud_record"])
def test_preparation_generator_authenticates_registry_before_source_reads(monkeypatch, loader):
    monkeypatch.setattr(generator, "FINAL_FILE_LIST_CONFIRMED", True)

    def reject_registry(root):
        assert root == PROJECT
        raise RuntimeError("source test succession record drifted")

    def forbidden_read(*args):
        pytest.fail("Invalid registry must stop before reading release source")

    monkeypatch.setattr(generator, "load_record", lambda root: {})
    monkeypatch.setattr(generator, "load_hud_record", lambda root: {})
    monkeypatch.setattr(generator, loader, reject_registry)
    monkeypatch.setattr(generator, "_file", forbidden_read)
    with pytest.raises(RuntimeError, match="source test succession record drifted"):
        generator.generate()


def test_preparation_exact_four_r11_snapshots():
    assert len(generator.R11_SNAPSHOTS) == 4
    assert set(generator.R11_SNAPSHOTS) == {snapshot for _, snapshot in EDGES.values()}
    for expected, snapshot in EDGES.values():
        assert _sha256(PROJECT / snapshot) == expected


@pytest.mark.parametrize("sequence", range(71, 99))
def test_preparation_historical_fixtures_keep_original_pins(sequence):
    authority = import_module(f"scripts.verify_release_workflow_v{sequence}")
    path = PROJECT / f"tests/fixtures/release_workflow_transition_v{sequence}.json"
    assert _sha256(path) == getattr(authority, f"V{sequence}_SHA256")


@pytest.mark.parametrize("pin", ["V99_SHA256", "V99_ROOT_SHA256"])
def test_preparation_unsealed_verifier_rejects_before_reading_inputs(monkeypatch, pin):
    monkeypatch.setattr(verifier, "V99_SHA256", "a" * 64)
    monkeypatch.setattr(verifier, "V99_ROOT_SHA256", "b" * 64)
    monkeypatch.setattr(verifier, pin, "UNSEALED_PENDING_PARENT_SEAL_NOW")

    def forbidden_read(*args):
        pytest.fail("Unsealed verification must stop before reading a fixture")

    monkeypatch.setattr(verifier, "_json", forbidden_read)
    with pytest.raises(ReleaseWorkflowV99Error, match="V99 unsealed"):
        verify_release_workflow_v99()


def test_preparation_generator_cannot_write_before_parent_seal(monkeypatch):
    monkeypatch.setattr(generator, "FINAL_FILE_LIST_CONFIRMED", False)

    def forbidden_read(*args):
        pytest.fail("Unconfirmed generation must stop before accessing source files")

    monkeypatch.setattr(generator, "_file", forbidden_read)
    with pytest.raises(RuntimeError, match="awaiting parent 'seal now'"):
        generator.generate()


def test_current_source_is_not_public_or_live_certification():
    result = verify_release_workflow_v99()
    assert result["transition"]["schema"] == "onyx.release-workflow-transition.v99"
    assert result["transition"]["logical_sequence"] == 99
    assert result["publishable"] is False
    assert result["formal_release_ready"] is False
    paths = {row["path"] for row in result["transition"]["current_release_paths"]}
    assert set(generator.ADDITIONS).issubset(paths)
    digests = {row["path"]: row["sha256"] for row in result["transition"]["current_release_paths"]}
    for registry in (load_record(PROJECT), hud_succession.load_record(PROJECT)):
        assert set(registry["bindings"]).issubset(paths)
        assert all(digests[path] == expected for path, expected in registry["bindings"].items())


@pytest.fixture(scope="module")
def sealed_source_copy(tmp_path_factory):
    result = verify_release_workflow_v99()
    root = tmp_path_factory.mktemp("release-v99-tamper")
    paths = {V98, V99, *(Path(row["path"]) for row in result["transition"]["current_release_paths"])}
    for path in paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / path, target)
    verify_release_workflow_v99(root)
    return root


@pytest.mark.parametrize("changed", [
    V98, V99,
    Path("core/live_voice_continuity_v1.py"),
    Path("core/telegram_official_connector_v1.py"),
    Path("core/business_document_delivery_v1.py"),
    Path("scripts/verify_release_workflow_v98.py"),
    Path("scripts/generate_release_workflow_v99.py"),
    Path("tests/test_release_workflow_transition_v99.py"),
    Path("scripts/source_test_succession_v1.py"),
    Path("tests/fixtures/source_test_succession_v1.json"),
    Path("scripts/hud_test_succession_v1.py"),
    Path("tests/fixtures/hud_test_succession_v1.json"),
    Path("tests/test_hud_test_succession_v1.py"),
    Path("tests/test_onyx_hud_current_acceptance_v36.py"),
    Path("tests/test_packaged_runtime_hud_contract_v5.py"),
    Path("docs/onyx/acceptance/VE-HUD-CURRENT-V36-E6-001.manifest.json"),
    Path("core/onyx_packaged_runtime_hud_contract_v5.manifest.json"),
    Path("docs/onyx/CURRENT_CAPABILITY_STATUS_V1.md"),
    Path("tests/test_current_capability_status_v1.py"),
    Path("tests/test_current_capability_status_v2.py"),
    Path("tests/test_hud_conversation_successor_v48.py"),
    Path("tests/test_humanoid_promotion_v47.py"),
    *(Path(path) for path in generator.R11_SNAPSHOTS),
    *(Path(f"tests/fixtures/release_workflow_transition_v{sequence}.json") for sequence in range(71, 98)),
])
def test_rejects_tampered_predecessor_manifest_runtime_and_history(sealed_source_copy, changed):
    target = sealed_source_copy / changed
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n")
        with pytest.raises(ReleaseWorkflowV99Error):
            verify_release_workflow_v99(sealed_source_copy)
    finally:
        target.write_bytes(original)


@pytest.mark.parametrize("pin", ["V99_SHA256", "V99_ROOT_SHA256", "V98_SHA256", "V98_ROOT_SHA256"])
def test_rejects_wrong_strong_pins(monkeypatch, pin):
    verify_release_workflow_v99()
    monkeypatch.setattr(verifier, pin, "0" * 64)
    with pytest.raises(ReleaseWorkflowV99Error):
        verify_release_workflow_v99()
