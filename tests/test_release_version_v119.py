from pathlib import Path

from core.version import __version__
from scripts import generate_icons


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.9"


def test_runtime_version_is_1_1_9() -> None:
    assert __version__ == VERSION


def test_packaging_and_release_surfaces_default_to_1_1_9() -> None:
    spec = (ROOT / "packaging" / "onyx.spec").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release-packages.yml").read_text(
        encoding="utf-8"
    )
    linux_validation = (
        ROOT / "scripts" / "run_linux_release_validation.sh"
    ).read_text(encoding="utf-8")
    installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
    readme = (ROOT / "readme.md").read_text(encoding="utf-8")

    assert f'ONYX_BUILD_VERSION", "{VERSION}"' in spec
    assert f"default: {VERSION}" in workflow
    assert f"--version {VERSION}" in linux_validation
    assert "tests/test_release_version_v119.py" in linux_validation
    assert "tests/test_release_version_v118.py" not in linux_validation
    assert f"--version {VERSION}" in installation
    assert f"--version {VERSION}" in readme


def test_appimagetool_release_is_immutable_and_self_contained() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-packages.yml").read_text(
        encoding="utf-8"
    )

    assert 'APPIMAGETOOL_RELEASE_TAG: "1.9.1"' in workflow
    assert "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0" in workflow
    assert "f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158" in workflow
    assert "1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf" in workflow
    assert "7d5d772b7c32f0c84caf0a452a3072a5709027d7eac5856feb89a7a7a8881372" in workflow
    assert "vars.ONYX_APPIMAGETOOL" not in workflow
    assert "AppImage/appimagetool/releases/download/continuous" not in workflow
    assert "AppImage/type2-runtime/releases/download/continuous/runtime-${arch}" in workflow
    assert "APPIMAGE_RUNTIME_FILE=$RUNNER_TEMP/appimage-runtime" in workflow
    assert '"--runtime-file"' in (
        ROOT / "scripts" / "build_release.py"
    ).read_text(encoding="utf-8")


def test_linux_validation_image_pins_primp_minimum_rust_toolchain() -> None:
    dockerfile = (
        ROOT / "packaging" / "linux" / "Dockerfile.release-validation"
    ).read_text(encoding="utf-8")

    assert "FROM rust:1.89.0-bookworm AS rust-toolchain" in dockerfile
    assert "COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo" in dockerfile
    assert "COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup" in dockerfile
    assert "rustc --version | grep -F 'rustc 1.89.0 '" in dockerfile
    assert (
        "toolchains/1.89.0-x86_64-unknown-linux-gnu/bin/cargo "
        "/usr/local/bin/cargo"
    ) in dockerfile
    assert "ln -s /usr/local/cargo/bin/rustup /usr/local/bin/rustc" in dockerfile
    assert "test ! -L /usr/local/bin/cargo" in dockerfile


def test_windows_version_resource_uses_1_1_9(tmp_path: Path) -> None:
    generate_icons.generate(tmp_path, VERSION)
    version_info = (tmp_path / "version_info.txt").read_text(encoding="utf-8")
    assert "filevers=(1, 1, 9, 0)" in version_info
    assert "prodvers=(1, 1, 9, 0)" in version_info
    assert "FileVersion', '1.1.9'" in version_info
    assert "ProductVersion', '1.1.9'" in version_info
