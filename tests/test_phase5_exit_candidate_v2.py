from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_phase5_exit_candidate_v2.py"
SPEC = importlib.util.spec_from_file_location("_phase5_exit_candidate_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def _startup_tree(destination: Path) -> tuple[dict[str, object], dict[str, str]]:
    digests: dict[str, str] = {}
    for relative in (
        *verifier.EXPECTED_STARTUP_CLOSURE,
        *verifier.APPLICATION_SURFACES,
    ):
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        digests[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    return {"startup_closure": list(verifier.EXPECTED_STARTUP_CLOSURE)}, digests


def test_focused_v2_is_verified_but_never_a_release_pass() -> None:
    result = verifier.verify(ROOT, run_external=False)
    assert result["status"] == "focused-only-not-release-pass"
    assert result["component_verifiers_executed"] == 0
    assert result["v9_acceptance_executed"] is False
    assert result["external_e6_accepted"] is False
    assert result["phase6_unlocked"] is False
    assert result["onyx_complete"] is False
    assert result["predecessor"]["flags_default_false"] == 8
    assert result["v9_acceptance"]["acceptance_id"] == verifier.V9_ACCEPTANCE_ID
    assert result["cumulative_selection"]["expected_passed"] == 257


def test_claims_and_rollback_are_exactly_bounded() -> None:
    manifest = verifier._load_manifest(ROOT)
    assert verifier._verify_claims(manifest) == {
        "e1_e5_candidate": True,
        "external_e6_accepted": False,
        "phase5_exit_complete": False,
        "phase6_unlocked": False,
        "live_activated": False,
        "runtime_authority_added": False,
        "onyx_complete": False,
        "v9_e6_composed": True,
    }


def test_every_v2_binding_rehashes_and_manifest_is_not_self_bound() -> None:
    manifest = verifier._load_manifest(ROOT)
    entries, digests = verifier._verify_files(ROOT, manifest)
    assert len(entries) == len(digests) == manifest["independent_root"]["binding_count"]
    assert verifier.MANIFEST not in digests
    for relative, digest in digests.items():
        state = verifier._binding_state(ROOT, relative, digest)
        assert state == "current-exact" or state == "archived-exact" or state.startswith(
            "retired-delegated:"
        )
    result = verifier._verify_cumulative_selection(ROOT, manifest, digests)
    assert result == {
        "test_files": 10,
        "expected_passed": 257,
        "expected_failed": 0,
        "command": [
            r".\.venv\Scripts\python.exe",
            "-m",
            "pytest",
            "-q",
            *verifier.EXPECTED_CUMULATIVE_TESTS,
            "--disable-warnings",
            "--basetemp",
            ".pytest-p5-exit-v2-compatible",
        ],
    }
    assert verifier.C1_TESTS not in verifier.EXPECTED_CUMULATIVE_TESTS
    assert set(verifier.EXPECTED_CUMULATIVE_TESTS) <= set(digests)


def test_independent_root_is_recomputed_with_independent_byte_framing() -> None:
    manifest = verifier._load_manifest(ROOT)
    entries, _digests = verifier._verify_files(ROOT, manifest)

    # Deliberately independent implementation of the documented byte framing.
    material = bytearray(b"onyx.phase5.exit-candidate.v2.bindings.v1\0")
    ordered = sorted(entries, key=lambda entry: entry["path"].encode("utf-8"))
    material.extend(len(ordered).to_bytes(4, "big"))
    for entry in ordered:
        path = entry["path"].encode("utf-8")
        role = entry["role"].encode("utf-8")
        material.extend(b"\x01")
        material.extend(len(path).to_bytes(4, "big"))
        material.extend(path)
        material.extend(len(role).to_bytes(4, "big"))
        material.extend(role)
        material.extend(bytes.fromhex(entry["sha256"]))
    independent = hashlib.sha256(material).hexdigest()

    assert independent == manifest["independent_root"]["sha256"]
    assert independent == verifier._independent_root(entries)
    assert not independent.startswith("176ca")


def test_independent_root_binds_role_as_well_as_path_and_digest() -> None:
    manifest = verifier._load_manifest(ROOT)
    entries, _digests = verifier._verify_files(ROOT, manifest)
    changed = [dict(entry) for entry in entries]
    changed[0]["role"] += "-tampered"
    assert verifier._independent_root(changed) != verifier._independent_root(entries)


def test_predecessor_reproduces_five_components_and_eight_false_flags() -> None:
    manifest = verifier._load_manifest(ROOT)
    _module, _c1_manifest, result = verifier._verify_predecessor(ROOT, manifest)
    assert result == {
        "files": 66,
        "component_acceptances": 5,
        "flags_default_false": 8,
    }


def test_v9_acceptance_rehashes_all_twenty_frozen_bindings_and_e6_anchors() -> None:
    manifest = verifier._load_manifest(ROOT)
    _entries, digests = verifier._verify_files(ROOT, manifest)
    result = verifier._verify_v9(ROOT, manifest, digests)
    assert result == {
        "acceptance_id": verifier.V9_ACCEPTANCE_ID,
        "bindings": 20,
        "evidence_root_sha256": verifier.V9_EVIDENCE_ROOT_SHA256,
        "default_off": True,
        "live_activated": False,
    }


def test_full_file_historical_anchors_have_no_prefix_recovery() -> None:
    manifest = verifier._load_manifest(ROOT)
    _entries, digests = verifier._verify_files(ROOT, manifest)
    assert {
        relative: digests[relative] for relative in verifier.HISTORICAL_PROJECTIONS
    } == verifier.HISTORICAL_PROJECTIONS
    source = SCRIPT.read_text(encoding="utf-8")
    assert "_historical_projection_bytes" not in source
    assert "current[:" not in source


def test_startup_closure_is_exact_v1_through_v9() -> None:
    manifest = verifier._load_manifest(ROOT)
    _entries, digests = verifier._verify_files(ROOT, manifest)
    assert verifier._verify_startup_closure(ROOT, manifest, digests) == {
        "files": 32,
        "launchers": 22,
        "bootstraps": 2,
        "packaging_entrypoints": 8,
    }


def test_startup_closure_rejects_missing_v9_byte(tmp_path: Path) -> None:
    manifest, digests = _startup_tree(tmp_path)
    missing = "scripts/bootstrap_onyx_live_v9.pyw"
    (tmp_path / missing).unlink()
    with pytest.raises(
        verifier.Phase5ExitCandidateV2Error,
        match=f"startup closure path drift: {missing}",
    ):
        verifier._verify_startup_closure(tmp_path, manifest, digests)


def test_startup_closure_rejects_extra_v10_surface(tmp_path: Path) -> None:
    manifest, digests = _startup_tree(tmp_path)
    extra = tmp_path / "scripts/launch_onyx_live_v10.pyw"
    extra.write_text("raise SystemExit(1)\n", encoding="utf-8")
    with pytest.raises(
        verifier.Phase5ExitCandidateV2Error,
        match="startup closure path drift: scripts/launch_onyx_live_v10.pyw",
    ):
        verifier._verify_startup_closure(tmp_path, manifest, digests)


def test_startup_closure_rejects_exit_symbol_on_application_surface(
    tmp_path: Path,
) -> None:
    manifest, digests = _startup_tree(tmp_path)
    (tmp_path / "main.py").write_text(
        "value = 'phase5-exit-candidate-v2'\n", encoding="utf-8"
    )
    with pytest.raises(
        verifier.Phase5ExitCandidateV2Error,
        match="Phase 5 Exit symbol entered live/startup surface: main.py",
    ):
        verifier._verify_startup_closure(tmp_path, manifest, digests)


def test_v9_external_runner_requires_exact_acceptance_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="WRONG {}\n", stderr=""
        ),
    )
    with pytest.raises(
        verifier.Phase5ExitCandidateV2Error,
        match="verifier failed or marker drifted",
    ):
        verifier._run_v9_acceptance(ROOT)


def test_checkpoint_documents_single_root_algorithm_and_non_acceptance() -> None:
    verifier._verify_checkpoint(ROOT)
    checkpoint = (ROOT / verifier.CHECKPOINT).read_text(encoding="utf-8")
    assert checkpoint.count(verifier.ROOT_ALGORITHM) == 1
    assert "E6 external acceptance pending" in checkpoint
    assert "Phase 5 remains incomplete" in checkpoint
    assert "does **not** declare the Phase 5 exit complete" in checkpoint


def test_manifest_is_canonical_utf8_json_with_new_root_only() -> None:
    raw = (ROOT / verifier.MANIFEST).read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    assert raw.endswith(b"\n")
    assert manifest["candidate"] == "phase5-exit-candidate-v2"
    assert (
        manifest["independent_root"]["sha256"]
        != verifier.C1_BINDINGS[verifier.C1_MANIFEST]
    )
    assert not manifest["independent_root"]["sha256"].startswith("176ca")
