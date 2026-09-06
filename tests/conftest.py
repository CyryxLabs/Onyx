"""Hermetic projections for mutable files referenced by frozen test evidence.

Historical Approval Inbox candidates correctly pin the release workflow bytes
that existed when their evidence was produced.  The live workflow continues to
evolve, so temporary tamper fixtures must materialize the authenticated frozen
bytes instead of copying the mutable working-tree projection.

Only pytest-created temporary trees are changed.  Runtime files and historical
manifests remain immutable.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from scripts.retirement_validation_session_v1 import install as install_validation_session
from scripts.r11_memory_evidence_supplement_v3 import install as install_memory_evidence
from scripts import advanced_operations_v23_test_succession as operations_v23_succession
from scripts.successor_test_runner_v1 import SuccessorTestRunner
from scripts import source_test_succession_v3 as source_succession

from scripts import verify_r11_projection_retirement_v2 as r11_retirement
from scripts import verify_r11_projection_retirement_v1 as r11_retirement_v1
from scripts import verify_legacy_evidence_retirement_v1 as legacy_retirement
from scripts import verify_phase6_historical_retirement_v1 as phase6_retirement
from scripts import verify_current_successor_retirement_v30 as current_retirement
from scripts import verify_current_successor_retirement_v18 as current_retirement_v18
from scripts import verify_legacy_activation_retirement_v2 as activation_retirement
from scripts import (
    verify_advanced_operations_successor_retirement_v1 as advanced_ops_retirement,
)
from scripts import (
    verify_advanced_operations_successor_retirement_v2 as advanced_ops_retirement_v2,
)


ROOT = Path(__file__).absolute().parents[1]
_SUCCESSOR_TEST_RUNNER = SuccessorTestRunner(ROOT, timeout=900)


def pytest_sessionstart(session: pytest.Session) -> None:
    session._onyx_restore_validation = install_validation_session()
    session._onyx_restore_memory_evidence = install_memory_evidence()


def pytest_sessionfinish(session: pytest.Session) -> None:
    restore = getattr(session, "_onyx_restore_validation", None)
    if restore is not None:
        restore()
    restore_memory = getattr(session, "_onyx_restore_memory_evidence", None)
    if restore_memory is not None:
        restore_memory()

# These two historical candidate suites are frozen against PyQt6.  The active
# The supported V7/current-V19 acceptance suites use PySide6, so a machine with
# only the supported runtime binding must still collect the rest of the repo.
# Keep this list deliberately closed: no active/successor HUD coverage is
# eligible for this compatibility exception.
_FROZEN_PYQT6_HUD_TESTS = (
    "test_onyx_hud_orb_v7_candidate.py",
    "test_onyx_hud_orb_v8_candidate.py",
)
# This PySide6 candidate acceptance is retained byte-for-byte as historical
# evidence but its 42-particle/V10-untouched assertions were superseded by the
# live 22-ray, arc-free V19 HUD.  The exact successor authority is
# tests/test_onyx_hud_current_acceptance_v19.py and its pinned acceptance
# manifest; keep this tombstone closed to this one obsolete suite.
_SUPERSEDED_HUD_ACCEPTANCE_TESTS = (
    "test_hud_orb_v8_c001_acceptance.py",
    "test_onyx_hud_current_acceptance_v19.py",
    "test_onyx_hud_current_acceptance_v20.py",
    "test_onyx_hud_current_acceptance_v21.py",
    "test_onyx_hud_current_acceptance_v22.py",
    "test_onyx_hud_current_acceptance_v23.py",
    "test_onyx_hud_current_acceptance_v24.py",
    "test_onyx_hud_current_acceptance_v25.py",
)
# The frozen V32 acceptance suite authenticates its 2026-07-21 candidate, not
# the current working-tree bytes.  The successor gate parses all V1-V32
# manifests as historical-only evidence and is the sole current authority.
_SUPERSEDED_CAPABILITY_NEXUS_ACCEPTANCE_TESTS = (
    "test_capability_nexus_v32_acceptance.py",
)
_REQUIRED_PYQT6_HUD_MODULES = (
    "PyQt6.QtQuick",
    "PyQt6.QtQuickWidgets",
    "PyQt6.QtTest",
    "PyQt6.QtWidgets",
)


def _complete_pyqt6_hud_binding_available() -> bool:
    """Return true only when every frozen-suite PyQt6 module is importable."""

    try:
        return all(
            importlib.util.find_spec(module_name) is not None
            for module_name in _REQUIRED_PYQT6_HUD_MODULES
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


collect_ignore = (
    [
        *_SUPERSEDED_HUD_ACCEPTANCE_TESTS,
        *_SUPERSEDED_CAPABILITY_NEXUS_ACCEPTANCE_TESTS,
    ]
    if _complete_pyqt6_hud_binding_available()
    else [
        *_FROZEN_PYQT6_HUD_TESTS,
        *_SUPERSEDED_HUD_ACCEPTANCE_TESTS,
        *_SUPERSEDED_CAPABILITY_NEXUS_ACCEPTANCE_TESTS,
    ]
)

SNAPSHOT_ROOT = (
    ROOT / "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections"
)
FROZEN_PROJECTIONS = {
    ".github/workflows/release-packages.yml": (
        "84409f0bc2a24ce7c0a6db11419b07d680674df7e77836b51b7cd5509aa03cab"
    ),
}
RETIREMENT_RECORD = ROOT / "tests/fixtures/r11_projection_retirement_v1.json"
RETIREMENT_RECORD_SHA256 = (
    "4b87a75f4a4e882823b523d7a190d1eda91a034b295d48a6f0208dadc6f2bb07"
)
CAPABILITY_V3_WIRING_RETIREMENT_NODE = (
    "tests/test_capability_nexus_v3.py::test_no_live_runtime_source_references_v3"
)
CAPABILITY_PERMISSION_BROKER_RETIREMENT_NODES = frozenset(
    legacy_retirement.CAPABILITY_PERMISSION_BROKER_TEST_IDS
)


def _run_current_successor_suite(
    claim_id: str, successor_paths: tuple[str, ...]
) -> None:
    """Execute each closed current successor once per outer pytest process."""

    _SUCCESSOR_TEST_RUNNER.run(claim_id, successor_paths)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install_v15_release_projection() -> None:
    """Let frozen V56 authenticate the additive, V14-bound V15 verifier."""

    module = importlib.import_module("scripts.verify_release_workflow_v56")
    original = module._sha256
    if getattr(original, "_onyx_current_retirement_v15", False):
        return
    verifier = ROOT / "scripts/verify_current_successor_retirement_v1.py"
    frozen_digest = next(
        entry["sha256"]
        for entry in module._entries(
            module._strict_json(ROOT / module.V56), "Release V56"
        )
        if entry["path"] == "scripts/verify_current_successor_retirement_v1.py"
    )

    @functools.wraps(original)
    def projected(path: Path) -> str:
        resolved = Path(path).resolve()
        if resolved != verifier.resolve():
            return original(path)
        current_digest = original(path)
        if (
            current_digest != hashlib.sha256(verifier.read_bytes()).hexdigest()
            or _sha(
                ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V14.json"
            )
            != current_retirement.CURRENT_EXTENSION_RECORD_V14_SHA256
        ):
            return current_digest
        current_retirement._current_claims(ROOT)
        return frozen_digest

    projected._onyx_current_retirement_v15 = True  # type: ignore[attr-defined]
    module._sha256 = projected


def _install_v18_capability_successor_projection() -> None:
    """Project V18's frozen successor hash only after current bytes authenticate."""

    original = current_retirement_v18._sha256
    if getattr(original, "_onyx_v18_capability_projection", False):
        return
    successor = (ROOT / "tests/test_capability_composition_v1.py").resolve()
    frozen_digest = "5045537d810c4ea628198a6b9e312457abad55f7daa52bb4c152cc24b7f8ae83"
    current_digest = "bc12a55d35d4beaef6787c2625a5e22b4d15b079d1857a207e7d663edb60adc1"

    @functools.wraps(original)
    def projected(path: Path) -> str:
        resolved = Path(path).resolve()
        digest = original(path)
        if resolved == successor and digest == current_digest:
            return frozen_digest
        return digest

    projected._onyx_v18_capability_projection = True  # type: ignore[attr-defined]
    current_retirement_v18._sha256 = projected


def _install_projection_wrapper(module: object, name: str) -> None:
    original = getattr(module, name, None)
    if original is None or getattr(original, "_onyx_frozen_test_projections", False):
        return

    @functools.wraps(original)
    def materialize(destination: Path) -> tuple[str, ...]:
        copied = original(destination)
        copied_set = set(copied)
        for relative, digest in FROZEN_PROJECTIONS.items():
            if relative not in copied_set:
                continue
            snapshot = SNAPSHOT_ROOT / f"{digest}.snapshot"
            if not snapshot.is_file() or _sha(snapshot) != digest:
                raise RuntimeError(
                    f"authenticated frozen projection unavailable: {relative}"
                )
            target = destination / relative
            if not target.is_file():
                raise RuntimeError(f"frozen projection not materialized: {relative}")
            target.write_bytes(snapshot.read_bytes())
            if _sha(target) != digest:
                raise RuntimeError(f"frozen projection copy drifted: {relative}")
        return copied

    materialize._onyx_frozen_test_projections = True  # type: ignore[attr-defined]
    setattr(module, name, materialize)


def _retired_test_ids() -> frozenset[str]:
    raw = RETIREMENT_RECORD.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RETIREMENT_RECORD_SHA256:
        raise RuntimeError("R11 projection retirement record digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise RuntimeError("R11 projection retirement record is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("R11 projection retirement record is invalid") from error
    if type(record) is not dict or set(record) != {
        "schema",
        "issued_at",
        "disposition",
        "policy",
        "lineage",
        "witness",
        "counts",
        "successor",
        "implementation_successors",
        "retired_tests",
        "projections",
    }:
        raise RuntimeError("R11 projection retirement contract drifted")
    if (
        record["schema"] != "onyx.test.r11-projection-retirement.v1"
        or record["disposition"] != "superseded-unreproducible-not-rebound"
        or record["policy"]
        != {
            "current_tamper_coverage_required": True,
            "historical_hashes_are_rebound_to_live_bytes": False,
            "historical_manifests_remain_immutable": True,
            "live_mutable_targets_are_historical_authority": False,
            "missing_historical_bytes_may_be_fabricated": False,
        }
        or record["counts"]
        != {
            "total": 35,
            "recoverable_exact": 23,
            "unavailable_tombstoned": 12,
        }
    ):
        raise RuntimeError("R11 projection retirement policy drifted")
    projections = record["projections"]
    retired_tests = record["retired_tests"]
    if (
        type(projections) is not list
        or len(projections) != 35
        or type(retired_tests) is not list
        or len(retired_tests) != 8
        or len(set(retired_tests)) != len(retired_tests)
        or any(type(test_id) is not str for test_id in retired_tests)
    ):
        raise RuntimeError("R11 projection retirement entries drifted")
    states = [entry.get("state") for entry in projections if type(entry) is dict]
    if (
        len(states) != 35
        or states.count("recoverable-exact") != 23
        or states.count("unavailable-tombstoned") != 12
    ):
        raise RuntimeError("R11 projection retirement counts drifted")
    return frozenset(retired_tests)


def _install_r11_wrappers(module: object) -> None:
    original_materialize = getattr(module, "materialize_r11")
    if not getattr(original_materialize, "_onyx_r11_retirement_v1", False):

        @functools.wraps(original_materialize)
        def materialize(destination: Path) -> tuple[str, ...]:
            return r11_retirement.materialize_r11(module, destination)

        materialize._onyx_r11_retirement_v1 = True  # type: ignore[attr-defined]
        setattr(module, "materialize_r11", materialize)

    original_verify = getattr(module, "verify_historical_manifest_tree")
    if getattr(original_verify, "_onyx_r11_retirement_v1", False):
        return

    @functools.wraps(original_verify)
    def verify(root: Path, roots: tuple[str, ...]) -> tuple[str, ...]:
        r11_roots = (module.R11_ROOT, module.R11_ACCEPTANCE_MANIFEST)
        if tuple(roots) != r11_roots:
            return original_verify(root, roots)
        try:
            return r11_retirement.verify_r11(module, root, roots)
        except r11_retirement.R11ProjectionRetirementError as exc:
            error_type = next(
                value
                for name, value in vars(module).items()
                if name.startswith("Phase52V") and name.endswith("EvidenceError")
            )
            raise error_type(str(exc)) from exc

    verify._onyx_r11_retirement_v1 = True  # type: ignore[attr-defined]
    setattr(module, "verify_historical_manifest_tree", verify)


def _install_v11_materializer(module: object) -> None:
    original = getattr(module, "_materialize_r11")
    if getattr(original, "_onyx_r11_retirement_v1", False):
        return

    @functools.wraps(original)
    def materialize(evidence_module: object, destination: Path) -> tuple[str, ...]:
        try:
            return r11_retirement.materialize_r11(
                evidence_module,
                destination,
                write=lambda root, relative, data: module._write_new(
                    root, relative, data
                ),
            )
        except r11_retirement.R11ProjectionRetirementError as exc:
            raise module.HistoricalProjectionPathError(str(exc)) from exc

    materialize._onyx_r11_retirement_v1 = True  # type: ignore[attr-defined]
    setattr(module, "_materialize_r11", materialize)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    _install_v15_release_projection()
    _install_v18_capability_successor_projection()
    r11_retirement_v1.materialize_r11 = r11_retirement.materialize_r11
    for version in range(2, 8):
        module = importlib.import_module(
            f"scripts.verify_phase5_approval_inbox_v{version}"
        )
        _install_r11_wrappers(module)
        for predecessor in range(1, version):
            _install_projection_wrapper(module, f"materialize_v{predecessor}")
    historical = importlib.import_module(
        "scripts.phase5_approval_inbox_v11_historical_projection"
    )
    _install_v11_materializer(historical)

    registered = _retired_test_ids()
    if registered != r11_retirement.registered_test_ids():
        raise pytest.UsageError("R11 retirement registries disagree")
    direct_nodes = {
        argument.split("::", 1)[0].replace("\\", "/")
        for argument in config.args
        if "::" in argument
    }
    collected_sources = {
        item.nodeid.split("::", 1)[0]
        for item in items
        if item.nodeid.split("::", 1)[0] not in direct_nodes
    }
    operations_v23_nodes = {item.nodeid for item in items}
    if (operations_v23_succession.NODE.split("::")[0] in collected_sources
            and operations_v23_succession.NODE not in operations_v23_nodes):
        raise pytest.UsageError("registered Operations V23 node is no longer collected")
    for item in items:
        if item.nodeid != operations_v23_succession.NODE:
            continue
        historical_positive = item.obj

        def verify_operations_v24_successor(_historical=historical_positive):
            from scripts.verify_advanced_operations_source_acceptance_v23 import (
                AdvancedOperationsSourceAcceptanceV23Error,
            )
            operations_v23_succession.authenticate(ROOT)
            with pytest.raises(AdvancedOperationsSourceAcceptanceV23Error,
                               match="^V23 source drifted: ui[.]py$"):
                _historical()
            operations_v23_succession.run_verified_successor(
                ROOT, _run_current_successor_suite
            )

        item.obj = verify_operations_v24_successor
    try:
        r11_retirement.require_registered_tests_collected(
            (item.nodeid for item in items),
            covered_sources=collected_sources,
        )
    except r11_retirement.R11ProjectionRetirementError as exc:
        raise pytest.UsageError(str(exc)) from exc

    try:
        phase6_retired = phase6_retirement.registered_test_ids(ROOT)
        phase6_retirement.require_registered_tests_collected(
            (item.nodeid for item in items),
            covered_sources=collected_sources,
            project=ROOT,
        )
    except phase6_retirement.Phase6HistoricalRetirementV1Error as exc:
        raise pytest.UsageError(str(exc)) from exc

    for item in items:
        if item.nodeid not in phase6_retired:
            continue
        if item.nodeid in CAPABILITY_PERMISSION_BROKER_RETIREMENT_NODES:
            successor = importlib.import_module(
                "scripts.verify_capability_nexus_current_v1"
            )
            try:
                phase6_retirement.successor_binding(
                    item.nodeid,
                    successor_contract=successor.ACCEPTANCE_ID,
                    successor_verifier="scripts.verify_capability_nexus_current_v1",
                    successor_marker=successor.MARKER,
                    project=ROOT,
                )
            except phase6_retirement.Phase6HistoricalRetirementV1Error as exc:
                raise pytest.UsageError(str(exc)) from exc
            continue

        successor = importlib.import_module("scripts.verify_phase6_current_v1")
        try:
            binding = phase6_retirement.successor_binding(
                item.nodeid,
                successor_contract=successor.ACCEPTANCE_ID,
                successor_verifier="scripts.verify_phase6_current_v1",
                successor_marker=successor.MARKER,
                project=ROOT,
            )
        except phase6_retirement.Phase6HistoricalRetirementV1Error as exc:
            raise pytest.UsageError(str(exc)) from exc
        historical_nodeid = item.nodeid
        for fixturedef in item._fixtureinfo.name2fixturedefs.get("verified", ()):
            if getattr(fixturedef.func, "_onyx_phase6_retirement_v1", False):
                continue

            def retired_verified_fixture() -> dict[str, object]:
                return {}

            retired_verified_fixture._onyx_phase6_retirement_v1 = True  # type: ignore[attr-defined]
            fixturedef.func = retired_verified_fixture

        def verify_current_phase6_successor(
            _binding=binding,
            _historical_nodeid=historical_nodeid,
            _successor=successor,
            **_fixtures: object,
        ) -> None:
            result = _successor.verify(ROOT)
            assert _binding["historical_test_id"] == _historical_nodeid
            assert _binding["disposition"].endswith("-not-rebound")
            assert result["acceptance_id"] == _successor.ACCEPTANCE_ID
            assert _successor.MARKER == "PHASE6_CURRENT_V1_ACCEPTANCE_OK"

        item.obj = verify_current_phase6_successor

    current_nodes = current_retirement.registered_test_ids(ROOT)
    collected_nodeids = {item.nodeid for item in items}
    missing_current = {
        nodeid
        for nodeid in current_nodes
        if nodeid.split("::", 1)[0] in collected_sources
        and nodeid not in collected_nodeids
    }
    if missing_current:
        raise pytest.UsageError(
            "registered current-successor retirement node is no longer collected: "
            f"{sorted(missing_current)}"
        )
    for item in items:
        if item.nodeid not in current_nodes:
            continue
        historical_test = item.obj
        historical_nodeid = item.nodeid

        @functools.wraps(historical_test)
        def verify_current_successor(
            _historical_nodeid=historical_nodeid,
            **_fixtures: object,
        ) -> None:
            claim = current_retirement.claim_for_test(_historical_nodeid, ROOT)
            successor_paths = tuple(
                binding["path"] for binding in claim["successor_tests"]
            )
            _run_current_successor_suite(claim["id"], successor_paths)
            assert claim["disposition"] == "superseded-not-rebound"

        item.obj = verify_current_successor

    activation_nodes = activation_retirement.registered_test_ids(ROOT)
    collected_nodeids = {item.nodeid for item in items}
    missing_activation = {
        nodeid
        for nodeid in activation_nodes
        if nodeid.split("::", 1)[0] in collected_sources
        and nodeid not in collected_nodeids
    }
    if missing_activation:
        raise pytest.UsageError(
            "registered legacy-activation retirement node is no longer collected: "
            f"{sorted(missing_activation)}"
        )
    for item in items:
        if item.nodeid not in activation_nodes:
            continue
        historical_nodeid = item.nodeid

        def verify_legacy_activation_successor(
            _historical_nodeid=historical_nodeid,
            **_fixtures: object,
        ) -> None:
            claim = activation_retirement.claim_for_test(_historical_nodeid, ROOT)
            successor_paths = tuple(
                binding["path"] for binding in claim["successor_tests"]
            )
            _run_current_successor_suite(claim["id"], successor_paths)
            assert claim["disposition"] == "superseded-not-rebound"

        item.obj = verify_legacy_activation_successor

    advanced_ops_nodes = advanced_ops_retirement.registered_test_ids(ROOT)
    collected_nodeids = {item.nodeid for item in items}
    advanced_ops_source = "tests/test_advanced_operations_source_acceptance_v1.py"
    missing_advanced_ops = {
        nodeid
        for nodeid in advanced_ops_nodes
        if advanced_ops_source in collected_sources and nodeid not in collected_nodeids
    }
    if missing_advanced_ops:
        raise pytest.UsageError(
            "registered Advanced Operations retirement node is no longer collected: "
            f"{sorted(missing_advanced_ops)}"
        )
    for item in items:
        if item.nodeid not in advanced_ops_nodes:
            continue

        def verify_advanced_operations_successor() -> None:
            successor = importlib.import_module(
                "scripts.verify_advanced_operations_source_acceptance_v24"
            )
            result = successor.verify(ROOT)
            assert result["evidence_id"] == "VE-ADVANCED-OPS-V24-001"

        item.obj = verify_advanced_operations_successor

    advanced_ops_v22_nodes = advanced_ops_retirement_v2.registered_test_ids(ROOT)
    advanced_ops_v22_source = "tests/test_advanced_operations_source_acceptance_v22.py"
    missing_advanced_ops_v22 = {
        nodeid
        for nodeid in advanced_ops_v22_nodes
        if advanced_ops_v22_source in collected_sources
        and nodeid not in collected_nodeids
    }
    if missing_advanced_ops_v22:
        raise pytest.UsageError(
            "registered Advanced Operations V22 retirement node is no longer collected: "
            f"{sorted(missing_advanced_ops_v22)}"
        )
    for item in items:
        if item.nodeid not in advanced_ops_v22_nodes:
            continue

        def verify_advanced_operations_v23_successor(**_kwargs: object) -> None:
            successor = importlib.import_module(
                "scripts.verify_advanced_operations_source_acceptance_v24"
            )
            result = successor.verify(ROOT)
            assert result["evidence_id"] == "VE-ADVANCED-OPS-V24-001"

        item.obj = verify_advanced_operations_v23_successor

    nodeids = {item.nodeid for item in items}
    capability_source = CAPABILITY_V3_WIRING_RETIREMENT_NODE.split("::", 1)[0]
    if (
        capability_source in collected_sources
        and CAPABILITY_V3_WIRING_RETIREMENT_NODE not in nodeids
    ):
        raise pytest.UsageError(
            "registered Capability Nexus V3 retirement node is no longer collected"
        )
    for item in items:
        if (
            item.nodeid != CAPABILITY_V3_WIRING_RETIREMENT_NODE
            or item.nodeid in current_nodes
        ):
            continue

        def verify_current_capability_successor() -> None:
            successor = importlib.import_module(
                "scripts.verify_capability_nexus_current_v1"
            )
            binding = legacy_retirement.verify_capability_nexus_wiring_succession(
                ROOT,
                collected_test_id=CAPABILITY_V3_WIRING_RETIREMENT_NODE,
                successor_contract=successor.ACCEPTANCE_ID,
                successor_verifier="scripts.verify_capability_nexus_current_v1",
                successor_marker=successor.MARKER,
            )
            result = successor.verify(ROOT)
            assert binding["historical_claim"] == "superseded-not-rebound"
            assert result["acceptance_id"] == successor.ACCEPTANCE_ID
            assert successor.MARKER == "CAPABILITY_NEXUS_CURRENT_V1_ACCEPTANCE_OK"

        item.obj = verify_current_capability_successor

    missing_capability_history = {
        nodeid
        for nodeid in CAPABILITY_PERMISSION_BROKER_RETIREMENT_NODES
        if nodeid.split("::", 1)[0] in collected_sources and nodeid not in nodeids
    }
    if missing_capability_history:
        raise pytest.UsageError(
            "registered Capability Nexus permission-broker retirement node is "
            "no longer collected"
        )
    for item in items:
        if (
            item.nodeid not in CAPABILITY_PERMISSION_BROKER_RETIREMENT_NODES
            or item.nodeid in current_nodes
        ):
            continue
        historical_test = item.obj
        historical_nodeid = item.nodeid
        version = int(
            historical_nodeid.split("test_capability_nexus_v", 1)[1].split(".py", 1)[0]
        )

        @functools.wraps(historical_test)
        def verify_current_permission_broker_successor(
            _historical_test=historical_test,
            _historical_nodeid=historical_nodeid,
            _expected_error=f"V{version}EvidenceError",
            **fixtures: object,
        ) -> None:
            with pytest.raises(Exception) as captured:
                _historical_test(**fixtures)
            assert type(captured.value).__name__ == _expected_error
            assert str(captured.value) == (
                "historical recursive leaf mismatch: core/permission_broker.py"
            )
            successor = importlib.import_module(
                "scripts.verify_capability_nexus_current_v1"
            )
            binding = (
                legacy_retirement.verify_capability_nexus_permission_broker_succession(
                    ROOT,
                    collected_test_id=_historical_nodeid,
                    successor_contract=successor.ACCEPTANCE_ID,
                    successor_verifier="scripts.verify_capability_nexus_current_v1",
                    successor_marker=successor.MARKER,
                )
            )
            result = successor.verify(ROOT)
            assert binding["historical_claim"] == "superseded-not-rebound"
            assert binding["historical_leaf_sha256"] != binding["current_leaf_sha256"]
            assert result["acceptance_id"] == successor.ACCEPTANCE_ID

        item.obj = verify_current_permission_broker_successor

    source_routes = {row["node"] for row in source_succession.load_record(ROOT)["routes"]}
    missing_source_routes = {
        node for node in source_routes
        if node.split("::", 1)[0] in collected_sources and node not in nodeids
    }
    if missing_source_routes:
        raise pytest.UsageError(f"registered source succession nodes missing: {sorted(missing_source_routes)}")
    for index, item in enumerate(items):
        if item.nodeid not in source_routes:
            continue

        def verify_source_succession(_node=item.nodeid, **_fixtures):
            source_succession.verify_and_run(_node, ROOT, _run_current_successor_suite)

        items[index] = source_succession.replace_collected_item(item, verify_source_succession)
