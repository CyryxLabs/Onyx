from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_phase5_exit_candidate_v1.py"
SPEC = importlib.util.spec_from_file_location("_phase5_exit_candidate_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def _materialize_startup_closure(
    destination: Path,
) -> tuple[dict[str, object], dict[str, str]]:
    files: dict[str, str] = {}
    for relative in verifier.EXPECTED_STARTUP_CLOSURE:
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    return {"startup_closure": list(verifier.EXPECTED_STARTUP_CLOSURE)}, files


def test_focused_composition_verifies_but_never_claims_release_pass() -> None:
    result = verifier.verify(ROOT, run_external=False)
    assert result["status"] == "focused-only-not-release-pass"
    assert result["external_verifiers_executed"] is False
    assert result["external_verifier_count"] == 0
    assert result["external_e6_accepted"] is False
    assert result["phase6_unlocked"] is False
    assert result["onyx_complete"] is False
    assert result["acceptances"] == verifier.EXPECTED_ACCEPTANCE_IDS
    assert result["startup_closure"]["files"] == len(verifier.EXPECTED_STARTUP_CLOSURE)


def test_manifest_is_closed_and_candidate_claims_are_exact() -> None:
    manifest = verifier._load_manifest(ROOT)
    claims = verifier._verify_claims(manifest)
    assert claims == {
        "e1_e5_candidate": True,
        "external_e6_accepted": False,
        "phase5_exit_complete": False,
        "phase6_unlocked": False,
        "live_activated": False,
        "runtime_authority_added": False,
        "onyx_complete": False,
    }


def test_every_manifest_leaf_rehashes_and_paths_are_unique() -> None:
    manifest = verifier._load_manifest(ROOT)
    files = verifier._verify_files(ROOT, manifest)
    assert len(files) == len(manifest["files"])
    assert len(files) == len(set(files))
    for relative, expected in files.items():
        state = verifier._binding_state(ROOT, relative, expected)
        assert state == "current-exact" or state == "archived-exact" or state.startswith(
            "retired-delegated:"
        )


def test_historical_projection_files_are_full_file_hash_bound() -> None:
    manifest = verifier._load_manifest(ROOT)
    files = verifier._verify_files(ROOT, manifest)
    assert {
        relative: files[relative] for relative in verifier.HISTORICAL_PROJECTIONS
    } == verifier.HISTORICAL_PROJECTIONS


def test_five_acceptance_manifests_bind_exact_records() -> None:
    manifest = verifier._load_manifest(ROOT)
    assert verifier._verify_acceptances(ROOT, manifest) == (
        "VE-P5-RUNTIME-V10-E6-001",
        "VE-P51-GRANTS-R11-E6-001",
        "VE-P52-APPROVAL-INBOX-V15-E6-001",
        "VE-P53-CAPABILITY-NEXUS-V32-E6-001",
        "VE-P5-INTEGRATION-V3-E6-001",
    )


def test_acceptance_manifest_relation_rejects_wrong_record(
    tmp_path: Path,
) -> None:
    relative = "acceptance.sha256"
    (tmp_path / relative).write_text(f"{'0' * 64}  wrong/path.md\n", encoding="utf-8")
    with pytest.raises(
        verifier.Phase5ExitCandidateV1Error,
        match="acceptance manifest relation drift",
    ):
        verifier._parse_acceptance_manifest(
            tmp_path, relative, "expected/path.md", "0" * 64
        )


def test_integration_flags_are_eight_exact_false_and_candidate_is_unwired() -> None:
    result = verifier._verify_default_off(ROOT)
    assert result["flags"] == 8
    assert {"main.py", "ui.py", "dashboard/server.py"} <= set(result["live_surfaces"])


def test_application_surface_rejects_phase5_exit_symbol(tmp_path: Path) -> None:
    source = ROOT / "core/phase5_integration_v3.py"
    target = tmp_path / "core/phase5_integration_v3.py"
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    (tmp_path / "main.py").write_text(
        "value = 'phase5-exit-candidate-v1'\n", encoding="utf-8"
    )
    with pytest.raises(
        verifier.Phase5ExitCandidateV1Error,
        match="exit candidate entered live surface: main.py",
    ):
        verifier._verify_default_off(tmp_path)


def test_external_verifier_inventory_is_exact_and_bounded() -> None:
    manifest = verifier._load_manifest(ROOT)
    specs = verifier._external_specs(manifest)
    assert specs == verifier.EXPECTED_EXTERNAL
    assert [value[0] for value in specs] == [
        "runtime-v10",
        "grants-r11",
        "approval-inbox-v15",
        "capability-nexus-v32",
        "integration-v3",
    ]
    assert all(1 <= value[5] <= 360 for value in specs)
    assert [value[2] for value in specs] == [
        "integration-v3-historical-projection",
        "proportional-r11-frozen-evidence",
        "integration-v3-historical-projection",
        "integration-v3-historical-projection",
        "projected-current-transition",
    ]


def test_external_runner_rejects_incomplete_historical_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = verifier._load_manifest(ROOT)
    monkeypatch.setattr(
        verifier,
        "_run_grants_proportional",
        lambda _project: "P51_GRANTS_R11_EVIDENCE_OK {}",
    )
    monkeypatch.setattr(
        verifier,
        "_run_integration_projected",
        lambda _project, *, timeout: (
            "P5_INTEGRATION_V3_ACCEPTANCE_OK {}",
            {
                "transition_marker": "P5_INTEGRATION_V3_TRANSITION_OK",
                "closure_roots": {},
            },
        ),
    )
    with pytest.raises(
        verifier.Phase5ExitCandidateV1Error,
        match="did not execute the three historical verifiers",
    ):
        verifier._run_external(ROOT, manifest)


def test_external_runner_executes_each_exact_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = verifier._load_manifest(ROOT)
    calls: list[str] = []

    def fake_grants(_project: Path) -> str:
        calls.append("grants")
        return "P51_GRANTS_R11_EVIDENCE_OK {}"

    def fake_integration(
        _project: Path, *, timeout: int
    ) -> tuple[str, dict[str, object]]:
        calls.append(f"integration:{timeout}")
        return (
            "P5_INTEGRATION_V3_ACCEPTANCE_OK {}",
            {
                "transition_marker": "P5_INTEGRATION_V3_TRANSITION_OK",
                "closure_roots": {
                    "runtime-v10-e6": "a" * 64,
                    "approval-inbox-v15-e6": "b" * 64,
                    "capability-nexus-v32-e6": "c" * 64,
                },
            },
        )

    monkeypatch.setattr(verifier, "_run_grants_proportional", fake_grants)
    monkeypatch.setattr(verifier, "_run_integration_projected", fake_integration)
    result = verifier._run_external(ROOT, manifest)
    assert set(result) == {value[0] for value in verifier.EXPECTED_EXTERNAL}
    assert calls == ["grants", "integration:300"]
    for name in ("runtime-v10", "approval-inbox-v15", "capability-nexus-v32"):
        assert (
            json.loads(result[name].split(" ", 1)[1])["execution"]
            == "integration-v3-historical-projection"
        )


def test_grants_proportional_gate_is_explicitly_not_a_live_scan_replay() -> None:
    marker = verifier._run_grants_proportional(ROOT)
    prefix = "P51_GRANTS_R11_EVIDENCE_OK "
    assert marker.startswith(prefix)
    payload = json.loads(marker[len(prefix) :])
    assert payload["execution"] == "proportional-r11-frozen-evidence"
    assert payload["immutable_records_rehashed"] == 8
    assert payload["stored_tests"] == 51
    assert payload["full_historical_live_scan_replayed"] is False


@pytest.mark.parametrize("relative", tuple(verifier.HISTORICAL_PROJECTIONS))
def test_historical_projection_rejects_adversarial_append(
    tmp_path: Path,
    relative: str,
) -> None:
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / relative).read_bytes() + b"\nadversarial-append\n")
    with pytest.raises(
        verifier.Phase5ExitCandidateV1Error,
        match="exact projection source drifted",
    ):
        verifier._exact_projection_bytes(
            tmp_path, relative, verifier.HISTORICAL_PROJECTIONS[relative]
        )


def test_startup_closure_is_exact_complete_and_hash_bound() -> None:
    manifest = verifier._load_manifest(ROOT)
    files = verifier._verify_files(ROOT, manifest)
    result = verifier._verify_startup_closure(ROOT, manifest, files)
    assert result == {
        "files": len(verifier.EXPECTED_STARTUP_CLOSURE),
        "launchers": 19,
        "packaging_entrypoints": 8,
    }


def test_startup_closure_rejects_missing_surface(tmp_path: Path) -> None:
    manifest, files = _materialize_startup_closure(tmp_path)
    missing = "scripts/launch_onyx_live_v3.pyw"
    (tmp_path / missing).unlink()
    with pytest.raises(
        verifier.Phase5ExitCandidateV1Error,
        match=f"startup closure path drift: {missing}",
    ):
        verifier._verify_startup_closure(tmp_path, manifest, files)


def test_startup_closure_rejects_extra_surface(tmp_path: Path) -> None:
    manifest, files = _materialize_startup_closure(tmp_path)
    extra = tmp_path / "scripts/launch_onyx_live_v9.pyw"
    extra.write_text("raise SystemExit(1)\n", encoding="utf-8")
    with pytest.raises(
        verifier.Phase5ExitCandidateV1Error,
        match="startup closure path drift: scripts/launch_onyx_live_v9.pyw",
    ):
        verifier._verify_startup_closure(tmp_path, manifest, files)


def test_startup_closure_rejects_phase5_exit_symbol(tmp_path: Path) -> None:
    manifest, files = _materialize_startup_closure(tmp_path)
    target = tmp_path / "packaging/linux/onyx.desktop"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nONYX_PHASE5_EXIT=1\n",
        encoding="utf-8",
    )
    with pytest.raises(
        verifier.Phase5ExitCandidateV1Error,
        match="Phase 5 Exit symbol entered startup surface",
    ):
        verifier._verify_startup_closure(tmp_path, manifest, files)


def test_checkpoint_and_adr_keep_explicit_non_acceptance_boundary() -> None:
    verifier._verify_projection_words(ROOT)
    checkpoint = (
        ROOT / "docs/onyx/checkpoints/phase5-exit-candidate-v1/"
        "PHASE5_EXIT_CANDIDATE_V1_CHECKPOINT.md"
    ).read_text(encoding="utf-8")
    assert "E6 external acceptance pending" in checkpoint
    assert "Phase 5 remains incomplete" in checkpoint
    assert "does **not** declare the Phase 5 exit complete" in checkpoint


def test_manifest_json_is_canonical_utf8_and_has_no_self_hash() -> None:
    raw = (ROOT / verifier.MANIFEST).read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    paths = {entry["path"] for entry in manifest["files"]}
    assert verifier.MANIFEST not in paths
    assert raw.endswith(b"\n")
