"""Closed HUD succession tests, with no application, hardware or seal changes.

The temporary V99 fixture below copies actual source/historical bytes and uses
the real verifier. Only that module's two pins are changed in test memory and
restored by monkeypatch; the project's unsealed verifier/fixture is never edited.
This exercises cache admission, not a release verdict or live HUD qualification.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core import onyx_hud_current_acceptance_v48 as hud
from core import onyx_packaged_runtime_hud_contract_v17 as packaged
from scripts import hud_test_succession_v1 as route
from scripts import verify_release_workflow_v99 as source


ROOT = Path(__file__).resolve().parents[1]


def _copy(root, relatives):
    for relative in relatives:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


def test_exact_original_bindings_closed_routes_and_retained_invariants():
    record = route.load_record(ROOT)
    assert route.registered_test_ids(ROOT) == frozenset(route.NODES)
    assert len(record["routes"]) == 2
    assert len(record["bindings"]) == 11
    assert record["retained_nodes"] == list(route.RETAINED_NODES)
    assert route.registered_test_ids(ROOT).isdisjoint(route.RETAINED_NODES)
    original = json.loads(
        (
            ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V20.json"
        ).read_bytes()
    )
    bindings = {
        item["path"]: item["sha256"]
        for item in original["additional_claims"][0]["successor_tests"]
    }
    for node in route.NODES:
        path = node.split("::", 1)[0]
        assert record["bindings"][path] == bindings[path]
    assert {
        source.V99.as_posix(),
        "scripts/verify_release_workflow_v99.py",
        route.HELPER,
        route.TESTS,
        route.RECORD,
    }.isdisjoint(record["bindings"])


def test_exact_observed_nodes_remain_collected_without_executing_hud():
    files = sorted(
        {node.split("::", 1)[0] for node in (*route.NODES, *route.RETAINED_NODES)}
    )
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "--collect-only",
            "--noconftest",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "-q",
            *files,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = {
        line
        for line in result.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    }
    assert collected == set(route.NODES) | set(route.RETAINED_NODES)
    route.require_registered_tests_collected(collected, set(files), ROOT)
    with pytest.raises(route.HudTestSuccessionError, match="nodes missing"):
        route.require_registered_tests_collected(
            collected - {route.NODES[0]}, set(files), ROOT
        )
    # Direct unrelated selection must not demand collection of an entire suite.
    route.require_registered_tests_collected({route.RETAINED_NODES[0]}, set(), ROOT)


@pytest.mark.parametrize(
    "node",
    [
        *route.RETAINED_NODES,
        "tests/test_onyx_hud_current_acceptance_v20.py::test_current_v20_manifest_and_semantics_are_exact",
        "tests/test_onyx_hud_current_acceptance_v21.py::test_current_v21_closure_is_exact",
        "tests/test_native_release_gate_v1.py::test_pyinstaller_input_discovery_covers_entrypoints_and_resources",
        route.NODES[0] + "[new-param]",
    ],
)
def test_unregistered_and_already_ignored_nodes_cannot_be_routed(node):
    with pytest.raises(route.HudTestSuccessionError, match="unregistered"):
        route.verify_and_run(
            node, ROOT, lambda *_: pytest.fail("unregistered suite ran")
        )


@pytest.mark.parametrize("relative", tuple(route.load_record(ROOT)["bindings"]))
def test_pinned_old_and_current_binding_tamper_is_rejected(tmp_path, relative):
    record = route.load_record(ROOT)
    _copy(tmp_path, {*record["bindings"], route.RECORD})
    route.load_record(tmp_path)
    with (tmp_path / relative).open("ab") as stream:
        stream.write(b"\n# changed bound source")
    with pytest.raises(route.HudTestSuccessionError, match="binding drifted"):
        route.load_record(tmp_path)


def test_registry_tamper_is_rejected(tmp_path):
    _copy(tmp_path, {route.RECORD})
    with (tmp_path / route.RECORD).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(route.HudTestSuccessionError, match="record digest drifted"):
        route.load_record(tmp_path)


def test_reparse_binding_is_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace

    record = route.load_record(ROOT)
    _copy(tmp_path, {*record["bindings"], route.RECORD})
    target = tmp_path / route.NODES[0].split("::", 1)[0]
    original = Path.lstat

    def linked(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(route.HudTestSuccessionError, match="path is linked"):
        route.load_record(tmp_path)


@pytest.fixture(scope="module")
def source_copy(tmp_path_factory):
    """Real full-source verification against an explicitly temporary test root."""
    root = tmp_path_factory.mktemp("synthetic-v99-hud-cache-admission")
    old = json.loads((ROOT / source.V98).read_bytes())
    record = route.load_record(ROOT)
    paths = {
        *(row["path"] for row in source._entries(old)),
        *record["bindings"],
        route.RECORD,
        route.HELPER,
        route.TESTS,
        *(
            f"tests/fixtures/release_workflow_transition_v{index}.json"
            for index in range(71, 99)
        ),
        "scripts/verify_release_workflow_v98.py",
        "scripts/generate_release_workflow_v99.py",
        "tests/test_release_workflow_transition_v99.py",
        "core/telegram_official_connector_v1.py",
    }
    for module in (hud, packaged):
        manifest = json.loads((ROOT / module.MANIFEST_RELATIVE).read_bytes())
        paths.update(row["path"] for row in manifest["runtime_inputs"])
        paths.update(
            {
                module.PREDECESSOR_MANIFEST.as_posix(),
                (
                    getattr(module, "PREDECESSOR_ACCEPTANCE", None)
                    or module.PREDECESSOR_MODULE
                ).as_posix(),
            }
        )
    _copy(root, paths)
    temporary = {
        "schema": "onyx.release-workflow-transition.v99",
        "logical_sequence": 99,
        "issued_at": (
            datetime.fromisoformat(old["issued_at"]) + timedelta(seconds=1)
        ).isoformat(),
        "predecessor": {"path": source.V98.as_posix(), "sha256": source.V98_SHA256},
        "policy": old["policy"],
        "current_root_sha256": "",
        "current_release_paths": [
            {"path": path, "sha256": source._sha256(root / path)}
            for path in sorted(paths)
        ],
    }
    temporary["current_root_sha256"] = source._root(temporary, 99)
    target = root / source.V99
    target.write_text(
        json.dumps(temporary, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return root, source._sha256(target), temporary["current_root_sha256"]


@pytest.fixture
def verified_copy(source_copy, monkeypatch):
    root, digest, root_digest = source_copy
    monkeypatch.setattr(source, "V99_SHA256", digest)
    monkeypatch.setattr(source, "V99_ROOT_SHA256", root_digest)
    # All three actual validators run; no success result/validator is stubbed.
    hud.verify_current_hud_acceptance(root)
    packaged.verify_packaged_runtime_hud_contract(root)
    source.verify_release_workflow_v99(root)
    return root


def _observe_validators(monkeypatch):
    calls = []
    for module, name, label in (
        (hud, "verify_current_hud_acceptance", "hud48"),
        (packaged, "verify_packaged_runtime_hud_contract", "package17"),
        (source, "verify_release_workflow_v99", "source99"),
    ):
        original = getattr(module, name)

        def observed(root, _original=original, _label=label):
            calls.append(_label)
            return _original(root)

        monkeypatch.setattr(module, name, observed)
    return calls


def test_both_routes_fully_reverify_before_shared_cached_pass(
    verified_copy, monkeypatch
):
    calls = _observe_validators(monkeypatch)
    cached = set()
    executions = []

    def run_cached(claim, paths):
        assert calls[-3:] == ["hud48", "package17", "source99"]
        assert claim == route.CLAIM_ID and paths == (route.SUCCESSOR,)
        calls.append("cache")
        if paths not in cached:
            cached.add(paths)
            executions.append(paths)

    for node in route.NODES:
        result = route.verify_and_run(node, verified_copy, run_cached)
        assert result["disposition"] == "superseded-not-rebound"
        assert (
            result["publishable"] is False and result["formal_release_ready"] is False
        )
    assert calls == ["hud48", "package17", "source99", "cache"] * 2
    assert executions == [(route.SUCCESSOR,)]


@pytest.mark.parametrize(
    "relative,expected_calls,error",
    [
        ("ui.py", ["hud48"], hud.CurrentHudAcceptanceV48Error),
        (
            "core/onyx_packaged_runtime_hud_contract_v16.py",
            ["hud48", "package17"],
            packaged.PackagedRuntimeHudContractV17Error,
        ),
        (
            "core/telegram_official_connector_v1.py",
            ["hud48", "package17", "source99"],
            source.ReleaseWorkflowV99Error,
        ),
        (route.NODES[0].split("::", 1)[0], [], route.HudTestSuccessionError),
        ("core/onyx_hud_current_acceptance_v36.py", [], route.HudTestSuccessionError),
        (
            "docs/onyx/acceptance/VE-HUD-CURRENT-V36-E6-001.manifest.json",
            [],
            route.HudTestSuccessionError,
        ),
    ],
)
def test_fresh_verification_after_prior_pass_rejects_drift_before_cache(
    verified_copy,
    monkeypatch,
    relative,
    expected_calls,
    error,
):
    calls = _observe_validators(monkeypatch)
    cache_calls = []
    route.verify_and_run(
        route.NODES[0], verified_copy, lambda *args: cache_calls.append(args)
    )
    assert calls == ["hud48", "package17", "source99"]
    target = verified_copy / relative
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# modified after prior successful admission")
        calls.clear()
        with pytest.raises(error):
            route.verify_and_run(
                route.NODES[1], verified_copy, lambda *args: cache_calls.append(args)
            )
        assert calls == expected_calls
        assert len(cache_calls) == 1
    finally:
        target.write_bytes(original)


def test_cached_suite_failure_propagates_after_fresh_verification(
    verified_copy, monkeypatch
):
    calls = _observe_validators(monkeypatch)

    def failed_cache(*args):
        assert calls == ["hud48", "package17", "source99"]
        raise AssertionError("cached successor test failure")

    with pytest.raises(AssertionError, match="cached successor test failure"):
        route.verify_and_run(route.NODES[0], verified_copy, failed_cache)


def test_unsealed_v99_pin_rejects_without_running_suite(monkeypatch):
    monkeypatch.setattr(source, "V99_SHA256", "UNSEALED_PENDING_PARENT_SEAL_NOW")
    with pytest.raises(source.ReleaseWorkflowV99Error, match="V99 unsealed"):
        route.verify_and_run(
            route.NODES[0], ROOT, lambda *_: pytest.fail("unsealed suite ran")
        )


def test_v99_must_cover_helper_registry_tests_and_all_bindings(
    verified_copy, monkeypatch
):
    target = verified_copy / source.V99
    original = target.read_bytes()
    record = json.loads(original)
    record["current_release_paths"] = [
        row for row in record["current_release_paths"] if row["path"] != route.RECORD
    ]
    record["current_root_sha256"] = source._root(record, 99)
    try:
        target.write_text(
            json.dumps(record, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        monkeypatch.setattr(source, "V99_SHA256", source._sha256(target))
        monkeypatch.setattr(source, "V99_ROOT_SHA256", record["current_root_sha256"])
        source.verify_release_workflow_v99(verified_copy)
        with pytest.raises(
            route.HudTestSuccessionError, match="V99 omits or mismatches"
        ):
            route.verify_and_run(
                route.NODES[0],
                verified_copy,
                lambda *_: pytest.fail("incomplete source admitted"),
            )
    finally:
        target.write_bytes(original)
