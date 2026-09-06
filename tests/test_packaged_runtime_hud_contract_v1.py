from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from core.onyx_packaged_runtime_hud_contract_v1 import (
    PackagedRuntimeHudContractV1Error,
    RUNTIME_TEST_EVIDENCE_FILES,
    authenticated_v25_source_receipt,
    expected_exact_sets,
    verify_packaged_runtime_hud_contract,
    verify_packaged_runtime_hud_subset,
)
from scripts import build_release, package_hygiene


ROOT = Path(__file__).resolve().parents[1]


def _receipt() -> dict[str, object]:
    return authenticated_v25_source_receipt()


def _stage(tmp_path: Path, name: str = "runtime-sources") -> Path:
    destination = tmp_path / name
    package_hygiene.stage_runtime_sources(
        ROOT, destination, allowed_build_root=tmp_path
    )
    return destination


def test_curated_runtime_subset_passes_and_dev_authorities_are_absent(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    result = verify_packaged_runtime_hud_subset(stage, source_acceptance=_receipt())
    assert result["schema"] == "onyx.packaged-runtime-hud.v1"
    assert result["required_files"] > 50
    for forbidden in (
        "main.py",
        "ui.py",
        "packaging/onyx.spec",
        "scripts/build_release.py",
        "scripts/package_hygiene.py",
        "tests/conftest.py",
        "tests/test_onyx_hud_current_acceptance_v25.py",
        "core/onyx_hud_current_acceptance_v26.py",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json",
        "core/onyx_hud_current_acceptance_v27.py",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V27-E6-001.manifest.json",
        "core/onyx_hud_current_acceptance_v28.py",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V28-E6-001.manifest.json",
        "core/onyx_hud_current_acceptance_v29.py",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V29-E6-001.manifest.json",
        "core/onyx_packaged_runtime_hud_contract_v1.py",
    ):
        assert not (stage / forbidden).exists()


def test_qml_runtime_is_an_explicit_hash_bound_package_allowlist(
    tmp_path: Path,
) -> None:
    manifest_path = ROOT / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    approved = manifest["exact_sets"]["qml_runtime"]
    bound = {entry["path"] for entry in manifest["required_files"]}

    assert approved == sorted(set(approved))
    assert set(approved).issubset(bound)
    assert expected_exact_sets(ROOT)["qml_runtime"] == approved

    stage = _stage(tmp_path, "qml-allowlist")
    staged = sorted(
        path.relative_to(stage).as_posix()
        for path in (stage / "qml").rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    assert staged == approved
    assert not (stage / "qml/operations/CinematicOperationsHudV1.qml").exists()
    assert not (stage / "qml/components/HudTypographyV1.qml").exists()


def test_every_exact_runtime_member_is_individually_hash_bound() -> None:
    manifest_path = ROOT / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bound = {entry["path"] for entry in manifest["required_files"]}

    for name, members in expected_exact_sets(ROOT).items():
        assert set(members).issubset(bound), name


def test_frozen_contract_accepts_composed_runtime_sources_and_docs(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path, "composed-final-root")
    docs = tmp_path / "composed-runtime-docs" / "onyx"
    package_hygiene.stage_runtime_docs(ROOT, docs, allowed_build_root=tmp_path)
    shutil.copytree(docs, stage / "docs/onyx", dirs_exist_ok=True)
    shutil.copy2(ROOT / "main.py", stage / "main.py")
    shutil.copy2(ROOT / "ui.py", stage / "ui.py")

    result = verify_packaged_runtime_hud_contract(stage)

    assert result["source_acceptance"] == "V25-authenticated"
    assert (
        stage / "docs/onyx/acceptance/VE-HUD-CURRENT-V19-E6-001.manifest.json"
    ).is_file()


def test_runtime_evidence_membership_is_exactly_the_three_historical_files(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    manifest = __import__("json").loads(
        (stage / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    expected = list(RUNTIME_TEST_EVIDENCE_FILES)
    assert expected == sorted(expected)
    assert manifest["exact_sets"]["runtime_evidence_tests"] == expected
    assert (
        sorted(
            path.relative_to(stage).as_posix()
            for path in (stage / "tests").glob("*.py")
        )
        == expected
    )

    leaked = tmp_path / "extra-test-leak"
    shutil.copytree(stage, leaked)
    extra = leaked / "tests/test_dev_only.py"
    extra.write_text("raise AssertionError('must never ship')\n", encoding="utf-8")
    with pytest.raises(PackagedRuntimeHudContractV1Error, match="exact membership"):
        verify_packaged_runtime_hud_subset(leaked, source_acceptance=_receipt())


def test_subset_rejects_tamper_omission_addition_and_dev_leakage(
    tmp_path: Path,
) -> None:
    pristine = _stage(tmp_path, "pristine")

    tampered = tmp_path / "tampered"
    shutil.copytree(pristine, tampered)
    with (tampered / "qml/OnyxLiveShellV11.qml").open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(PackagedRuntimeHudContractV1Error, match="input drift"):
        verify_packaged_runtime_hud_subset(tampered, source_acceptance=_receipt())

    omitted = tmp_path / "omitted"
    shutil.copytree(pristine, omitted)
    (omitted / "core/onyx_live_activation_v24.py").unlink()
    with pytest.raises(PackagedRuntimeHudContractV1Error, match="unavailable"):
        verify_packaged_runtime_hud_subset(omitted, source_acceptance=_receipt())

    added = tmp_path / "added"
    shutil.copytree(pristine, added)
    (added / "qml/OnyxLiveShellV12.qml").write_text(
        "import QtQuick\n", encoding="utf-8"
    )
    with pytest.raises(PackagedRuntimeHudContractV1Error, match="exact membership"):
        verify_packaged_runtime_hud_subset(added, source_acceptance=_receipt())

    leaked = tmp_path / "leaked"
    shutil.copytree(pristine, leaked)
    shutil.copy2(ROOT / "ui.py", leaked / "ui.py")
    with pytest.raises(PackagedRuntimeHudContractV1Error, match="leaked"):
        verify_packaged_runtime_hud_subset(leaked, source_acceptance=_receipt())


def test_subset_rejects_coordinated_file_and_manifest_tamper(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path, "coordinated-tamper")
    target = stage / "qml/OnyxLiveShellV11.qml"
    target.write_bytes(target.read_bytes() + b"\n// coordinated tamper\n")
    manifest_path = stage / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["required_files"]:
        if entry["path"] == "qml/OnyxLiveShellV11.qml":
            entry["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            break
    material = "".join(
        f"{entry['path']}\0{entry['sha256']}\n"
        for entry in sorted(manifest["required_files"], key=lambda item: item["path"])
    ).encode("utf-8")
    manifest["artifact_root_sha256"] = hashlib.sha256(material).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, separators=(",", ":")) + "\n", encoding="utf-8"
    )

    with pytest.raises(PackagedRuntimeHudContractV1Error, match="manifest digest"):
        verify_packaged_runtime_hud_subset(stage, source_acceptance=_receipt())


def test_generate_runtime_sources_uses_the_same_subset_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "generated-runtime-sources"
    original_stage = package_hygiene.stage_runtime_sources

    def stage_with_test_boundary(root: Path, target: Path) -> None:
        original_stage(root, target, allowed_build_root=tmp_path)

    monkeypatch.setattr(
        package_hygiene, "stage_runtime_sources", stage_with_test_boundary
    )
    monkeypatch.setattr(build_release, "RUNTIME_SOURCES", destination)
    # Cleanup confinement is covered by the release-gate tests.  This focused
    # contract test deliberately stages below pytest's external temporary root,
    # so bypass only the redundant outer cleanup and retain the real curated
    # stager (which cleans and validates its own destination).
    monkeypatch.setattr(build_release, "clean_path", lambda _path: None)
    build_release.generate_runtime_sources()
    assert (
        verify_packaged_runtime_hud_subset(destination, source_acceptance=_receipt())[
            "required_files"
        ]
        > 50
    )


def test_frozen_contract_uses_authenticated_v25_receipt_without_dev_tree(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    # A final PyInstaller resource root carries genuine production source
    # inputs separately from the curated source stage.  Their presence must
    # not turn the frozen check back into a full repository acceptance.
    shutil.copy2(ROOT / "main.py", stage / "main.py")
    shutil.copy2(ROOT / "ui.py", stage / "ui.py")

    result = verify_packaged_runtime_hud_contract(stage)

    assert result["source_acceptance"] == "V25-authenticated"
    assert result["required_files"] > 50
    assert not (stage / "scripts/build_release.py").exists()
    assert not (stage / "tests/test_onyx_hud_current_acceptance_v25.py").exists()


def test_frozen_contract_allows_only_main_and_ui_from_forbidden_registry(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path, "final-root-forbidden")
    shutil.copy2(ROOT / "main.py", stage / "main.py")
    shutil.copy2(ROOT / "ui.py", stage / "ui.py")
    leaked = stage / "scripts/build_release.py"
    shutil.copy2(ROOT / "scripts/build_release.py", leaked)

    with pytest.raises(PackagedRuntimeHudContractV1Error, match="leaked"):
        verify_packaged_runtime_hud_contract(stage)


def test_frozen_contract_rejects_source_receipt_omission_and_tamper(
    tmp_path: Path,
) -> None:
    omitted = _stage(tmp_path, "omitted-frozen")
    (omitted / "core/onyx_hud_current_acceptance_v25.py").unlink()
    with pytest.raises(PackagedRuntimeHudContractV1Error, match="unavailable"):
        verify_packaged_runtime_hud_contract(omitted)

    tampered = _stage(tmp_path, "tampered-frozen")
    with (
        tampered / "docs/onyx/acceptance/VE-HUD-CURRENT-V25-E6-001.manifest.json"
    ).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(PackagedRuntimeHudContractV1Error, match="source receipt drift"):
        verify_packaged_runtime_hud_contract(tampered)
