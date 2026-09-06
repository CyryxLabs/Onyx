from __future__ import annotations

from pathlib import Path

from scripts import build_release
from scripts.package_hygiene import package_hygiene_violations


def test_runtime_smokes_use_disposable_bundle_clone(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "project"
    bundle = root / "dist" / "bundle" / "Onyx"
    bundle.mkdir(parents=True)
    immutable = bundle / "Onyx.exe"
    immutable.write_bytes(b"immutable-production-payload")
    validation_root = root / "build" / "runtime-validation-bundle"
    monkeypatch.setattr(build_release, "ROOT", root)
    monkeypatch.setattr(
        build_release, "RUNTIME_VALIDATION_BUNDLE", validation_root
    )

    cloned = build_release.clone_runtime_validation_bundle(bundle)
    assert cloned != bundle
    assert (cloned / "Onyx.exe").read_bytes() == immutable.read_bytes()
    mutable = (
        cloned
        / "_internal"
        / "runtime"
        / "phase6-live-wiring-v1"
        / "sessions"
        / "session-test"
        / "state.sqlite3"
    )
    mutable.parent.mkdir(parents=True)
    mutable.write_bytes(b"diagnostic")
    assert not mutable.relative_to(cloned).is_relative_to(bundle)
    assert not (
        bundle
        / "_internal"
        / "runtime"
        / "phase6-live-wiring-v1"
        / "sessions"
    ).exists()


def test_package_hygiene_rejects_mutable_phase6_session_state(
    tmp_path: Path,
) -> None:
    mutable = (
        tmp_path
        / "_internal"
        / "runtime"
        / "phase6-live-wiring-v1"
        / "sessions"
        / "session-test"
        / "state.sqlite3"
    )
    mutable.parent.mkdir(parents=True)
    mutable.write_bytes(b"diagnostic")

    assert package_hygiene_violations(tmp_path) == (
        "runtime/phase6-live-wiring-v1/sessions/session-test/state.sqlite3: "
        "mutable Phase 6 session state",
    )


def test_release_pipeline_smokes_clone_not_production_bundle() -> None:
    source = Path(build_release.__file__).read_text(encoding="utf-8")
    assert "validation_bundle = clone_runtime_validation_bundle(bundle)" in source
    for call in (
        "smoke_test",
        "package_preflight_test",
        "package_native_startup_smoke_test",
        "package_governance_smoke_test",
        "package_founder_smoke_test",
        "package_document_intake_smoke_test",
        "package_dayops_smoke_test",
        "package_advanced_operations_smoke_test",
        "package_advanced_commands_smoke_test",
    ):
        assert f"{call}(validation_bundle)" in source
    assert "assert_package_hygiene(bundle)" in source
