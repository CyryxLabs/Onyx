from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from core.native_activation_contract_v1 import activation_contract_for_system_v1
from core.version import __version__
from scripts import build_release
from scripts.verify_windows_release_shortcuts import (
    ShortcutContractError,
    validate_shortcut_values,
)


def test_release_version_must_equal_runtime_version() -> None:
    assert build_release.validate_release_version(__version__) == __version__
    with pytest.raises(RuntimeError, match="version mismatch"):
        build_release.validate_release_version("1.0.0")
    with pytest.raises(RuntimeError, match="canonical semantic version"):
        build_release.validate_release_version("v" + __version__)


def test_windows_portable_archive_clamps_pre_1980_metadata_without_mutation(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "Onyx"
    legal = bundle / "THIRD_PARTY_LICENSES" / "native-crate"
    legal.mkdir(parents=True)
    notice = legal / "LICENSE"
    notice.write_bytes(b"upstream legal text\n")
    os.utime(notice, (1, 1))
    original_mtime_ns = notice.stat().st_mtime_ns
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    build_release._write_windows_portable_archive(bundle, first)
    build_release._write_windows_portable_archive(bundle, second)

    assert notice.stat().st_mtime_ns == original_mtime_ns
    assert build_release.hash_file(first) == build_release.hash_file(second)
    with zipfile.ZipFile(first) as archive:
        member = archive.getinfo("Onyx/THIRD_PARTY_LICENSES/native-crate/LICENSE")
        assert member.date_time == (1980, 1, 1, 0, 0, 0)
        assert archive.read(member) == b"upstream legal text\n"


def test_windows_portable_archive_rejects_linked_members(tmp_path: Path) -> None:
    bundle = tmp_path / "Onyx"
    bundle.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    linked = bundle / "linked.txt"
    try:
        linked.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are unavailable on this Windows host")

    with pytest.raises(RuntimeError, match="linked member"):
        build_release._write_windows_portable_archive(bundle, tmp_path / "portable.zip")


def _write_prior_release(release: Path) -> None:
    release.mkdir()
    setup = release / "Onyx-1.0.0-Windows-x64-Setup.exe"
    setup.write_bytes(b"MZprior-setup")
    manifest = {
        "product": "Onyx",
        "version": "1.0.0",
        "activation_contract": activation_contract_for_system_v1("Windows"),
        "artifacts": [
            {
                "name": setup.name,
                "size": setup.stat().st_size,
                "sha256": build_release.hash_file(setup),
            }
        ],
    }
    (release / "release-manifest-Windows-x64.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (release / "SHA256SUMS-Windows-x64.txt").write_text(
        f"{build_release.hash_file(setup)}  {setup.name}\n",
        encoding="utf-8",
    )


def test_prior_v19_1_release_is_archived_and_verified_before_cleanup(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    rollback = tmp_path / "rollback" / "releases"
    _write_prior_release(release)

    archived = build_release.archive_existing_release(release, rollback)

    assert archived.parent == rollback
    assert archived.name.startswith("onyx-1.0.0-")
    assert len(archived.name.rsplit("-", 1)[-1]) == 16
    assert (archived / "Onyx-1.0.0-Windows-x64-Setup.exe").read_bytes() == b"MZprior-setup"
    assert build_release.archive_existing_release(release, rollback) == archived


def test_prior_release_archive_keeps_different_bytes_in_distinct_snapshots(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    rollback = tmp_path / "rollback" / "releases"
    _write_prior_release(release)
    archived = build_release.archive_existing_release(release, rollback)
    assert archived is not None
    (release / "Onyx-1.0.0-Windows-x64-Setup.exe").write_bytes(b"MZchanged")

    changed = build_release.archive_existing_release(release, rollback)
    assert changed is not None
    assert changed != archived
    assert (archived / "Onyx-1.0.0-Windows-x64-Setup.exe").read_bytes() == (
        b"MZprior-setup"
    )
    assert (changed / "Onyx-1.0.0-Windows-x64-Setup.exe").read_bytes() == (
        b"MZchanged"
    )


def test_build_input_seal_is_content_addressed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "main.py"
    second = tmp_path / "ui.py"
    first.write_text("main", encoding="utf-8")
    second.write_text("ui", encoding="utf-8")
    stable = tmp_path / "build" / "seal.json"
    archive = tmp_path / "build" / "input-seals"
    stable.parent.mkdir()
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release, "BUILD_INPUT_SEAL", stable)
    monkeypatch.setattr(build_release, "BUILD_INPUT_SEAL_ARCHIVE", archive)
    monkeypatch.setattr(
        build_release,
        "_first_party_build_input_files",
        lambda: (first, second),
    )

    snapshot = build_release.seal_pyinstaller_build_inputs()
    content = archive / f"{snapshot['root_sha256']}.json"

    assert content.read_bytes() == stable.read_bytes()
    loaded, loaded_path = build_release.load_verified_build_input_seal()
    assert loaded == snapshot
    assert loaded_path == content


def test_release_manifest_records_content_addressed_build_input_seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    artifact = release / "Onyx-1.1.1-Windows-x64-Setup.exe"
    artifact.write_bytes(b"MZsetup")
    content = tmp_path / "abc.json"
    content.write_text('{"contract":"seal"}\n', encoding="utf-8")
    snapshot = {
        "contract": build_release.BUILD_INPUT_SEAL_CONTRACT,
        "file_count": 1,
        "root_sha256": "a" * 64,
        "files": [{"path": "main.py", "size": 1, "sha256": "b" * 64}],
    }
    monkeypatch.setattr(build_release, "RELEASE", release)
    monkeypatch.setattr(
        build_release,
        "load_verified_build_input_seal",
        lambda: (snapshot, content),
    )
    monkeypatch.setattr(build_release.platform, "system", lambda: "Windows")
    monkeypatch.setattr(build_release, "architecture", lambda: "x64")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    from scripts import runtime_distribution_inventory

    def write_inventory(**kwargs):
        output = kwargs["output"]
        inventory = {
            "contract": "OnyxBundleInventory.v1",
            "bundleRootSha256": "c" * 64,
            "fileCount": 1,
            "runtimeDistributionCount": 1,
            "runtimeDistributionRootSha256": "d" * 64,
        }
        output.write_text(json.dumps(inventory), encoding="utf-8")
        return inventory

    monkeypatch.setattr(
        runtime_distribution_inventory,
        "write_bundle_inventory",
        write_inventory,
    )

    build_release.write_manifest("1.1.1", [artifact], bundle=bundle)

    manifest = json.loads(
        (release / "release-manifest-Windows-x64.json").read_text(encoding="utf-8")
    )
    seal = manifest["build_input_seal"]
    assert seal["root_sha256"] == "a" * 64
    assert seal["file_count"] == 1
    assert (release / seal["manifest"]).read_bytes() == content.read_bytes()
    inventory = manifest["bundle_inventory"]
    assert inventory["contract"] == "OnyxBundleInventory.v1"
    assert inventory["bundle_root_sha256"] == "c" * 64


def test_windows_setup_compilation_receives_explicit_production_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "bundle"
    source.mkdir()
    output = tmp_path / "release"
    iscc = tmp_path / "ISCC.exe"
    iscc.touch()
    observed: dict[str, str] = {}

    def run(_argv, *, env):
        observed.update(
            {
                key: env[key]
                for key in (
                    "ONYX_APP_ID",
                    "ONYX_BUILD_VERSION",
                    "ONYX_SETUP_BASENAME",
                )
            }
        )
        output.mkdir(exist_ok=True)
        (output / "Onyx-1.1.1-Windows-x64-Setup.exe").touch()

    monkeypatch.setattr(build_release, "find_iscc", lambda: iscc)
    monkeypatch.setattr(
        build_release,
        "_stage_inno_compiler",
        lambda _iscc, _destination: iscc,
    )
    monkeypatch.setattr(build_release, "run", run)
    monkeypatch.setenv(
        "ONYX_LIFECYCLE_RECORD_PATH",
        str(tmp_path / "ambient-must-not-control-production.json"),
    )

    build_release._compile_windows_setup(
        source_dir=source,
        output_dir=output,
        version="1.1.1",
        app_id=build_release.WINDOWS_PRODUCTION_APP_ID,
        setup_basename="Onyx-1.1.1-Windows-x64-Setup",
    )

    assert observed["ONYX_APP_ID"] == build_release.WINDOWS_PRODUCTION_APP_ID
    assert observed["ONYX_BUILD_VERSION"] == "1.1.1"
    assert "ONYX_LIFECYCLE_RECORD_PATH" not in observed


def test_inno_discovery_checks_exact_compiler_paths_without_recursing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = tmp_path / "build" / "tools" / "inno" / "ISCC.exe"
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    examples = compiler.parent / "Examples"
    examples.mkdir()
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: None)
    monkeypatch.delenv("INNO_ISCC", raising=False)
    monkeypatch.setattr(
        Path,
        "rglob",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Inno discovery must not recurse installation trees")
        ),
    )

    assert build_release.find_iscc() == compiler


def test_isolated_setup_compile_uses_exact_output_basename_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = tmp_path / "Onyx-1.1.1-Windows-x64-Setup.exe"
    production.touch()
    source = tmp_path / "bundle"
    source.mkdir()
    output = tmp_path / "isolated-output"
    compiler = tmp_path / "ISCC.exe"
    compiler.touch()
    observed: dict[str, str] = {}

    def run(argv: list[str], *, env: dict[str, str]) -> None:
        assert argv[0] == str(compiler)
        observed.update(env)
        destination = Path(env["ONYX_OUTPUT_DIR"])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / f"{env['ONYX_SETUP_BASENAME']}.exe").touch()

    monkeypatch.setattr(build_release, "find_iscc", lambda: compiler)
    monkeypatch.setattr(build_release, "architecture", lambda: "x64")
    monkeypatch.setattr(
        build_release,
        "_stage_inno_compiler",
        lambda _iscc, _destination: compiler,
    )
    monkeypatch.setattr(build_release, "run", run)

    result = build_release._build_isolated_windows_smoke_setup(
        production,
        source_bundle=source,
        output_dir=output,
        version="1.1.1",
        context=tmp_path / "context",
    )

    assert result == output / f"{observed['ONYX_SETUP_BASENAME']}.exe"
    assert result.is_file()
    assert observed["ONYX_APP_ID"] != build_release.WINDOWS_PRODUCTION_APP_ID
    assert observed["ONYX_LIFECYCLE_RECORD_PATH"] == str(
        (tmp_path / "context").resolve()
        / "runtime"
        / "installer-lifecycle-v1"
        / "resident.json"
    )


@pytest.mark.skipif(
    build_release.platform.system() != "Windows",
    reason="real Inno compiler gate is Windows-only",
)
def test_real_inno_compiles_iss_with_packaged_english_and_portuguese(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.generate_icons import generate

    compiler = build_release.find_iscc()
    if compiler is None:
        pytest.skip("Inno Setup is not installed")
    source = tmp_path / "bundle"
    source.mkdir()
    (source / "Onyx.exe").write_bytes(b"MZ-real-inno-gate")
    (source / "LICENSE.txt").write_text(
        (Path(__file__).resolve().parents[1] / "LICENSE").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assets = tmp_path / "assets"
    generate(assets, "1.1.1")
    monkeypatch.setattr(build_release, "ASSETS", assets)
    monkeypatch.setattr(build_release, "architecture", lambda: "x64")
    basename = "Onyx-1.1.1-Windows-x64-Setup-Compiler-Gate"

    result = build_release._compile_windows_setup(
        source_dir=source,
        output_dir=tmp_path / "output",
        version="1.1.1",
        app_id=build_release.isolated_windows_app_id(tmp_path),
        setup_basename=basename,
    )

    assert result == tmp_path / "output" / f"{basename}.exe"
    assert result.read_bytes().startswith(b"MZ")
    assert "LanguageName=English" in build_release.INNO_DEFAULT_MESSAGES.read_text(
        encoding="utf-8"
    )
    installer = (build_release.ROOT / "packaging/windows/onyx.iss").read_text(
        encoding="utf-8"
    )
    assert 'Name: "english"' in installer
    assert 'Name: "brazilianportuguese"' in installer


def test_windows_setup_smoke_identity_is_deterministic_and_not_production(
    tmp_path: Path,
) -> None:
    first = build_release.isolated_windows_app_id(tmp_path)
    second = build_release.isolated_windows_app_id(tmp_path)
    assert first == second
    assert first != build_release.WINDOWS_PRODUCTION_APP_ID
    assert first.startswith("{{") and first.endswith("}")


def test_windows_smoke_setup_is_recompiled_with_isolated_app_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = tmp_path / "Onyx-1.1.1-Windows-x64-Setup.exe"
    production.touch()
    source = tmp_path / "bundle"
    source.mkdir()
    output = tmp_path / "smoke-output"
    observed: dict[str, object] = {}

    def compile_setup(**kwargs):
        observed.update(kwargs)
        output.mkdir(exist_ok=True)
        result = output / f"{kwargs['setup_basename']}.exe"
        result.touch()
        return result

    monkeypatch.setattr(build_release, "_compile_windows_setup", compile_setup)

    result = build_release._build_isolated_windows_smoke_setup(
        production,
        source_bundle=source,
        output_dir=output,
        version="1.1.1",
        context=tmp_path / "context",
    )

    assert result.is_file()
    assert observed["app_id"] != build_release.WINDOWS_PRODUCTION_APP_ID
    assert observed["source_dir"] == source
    assert observed["lifecycle_record_path"] == (
        (tmp_path / "context").resolve()
        / "runtime"
        / "installer-lifecycle-v1"
        / "resident.json"
    )
    assert str(observed["setup_basename"]).startswith(
        "Onyx-1.1.1-Windows-x64-Setup-Smoke-"
    )


def test_stale_source_v13_desktop_shortcut_is_rejected(tmp_path: Path) -> None:
    install = tmp_path / "Programs" / "Cyryx Labs" / "Onyx"
    install.mkdir(parents=True)
    with pytest.raises(ShortcutContractError, match="installed executable"):
        validate_shortcut_values(
            target=tmp_path / ".venv" / "Scripts" / "pythonw.exe",
            arguments=str(tmp_path / "scripts" / "bootstrap_onyx_live_v13.pyw"),
            working_directory=tmp_path,
            install_root=install,
        )


def test_installer_always_replaces_desktop_shortcut_with_installed_binary() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "packaging"
        / "windows"
        / "onyx.iss"
    ).read_text(encoding="utf-8")
    assert "AppId={#MyAppId}" in source
    assert 'Name: "{autodesktop}\\Onyx"; Filename: "{app}\\Onyx.exe"' in source
    assert "Tasks: desktopicon" not in source
    assert ".venv" not in source
    assert "bootstrap_onyx_live_v13" not in source
