from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_release


def test_pyinstaller_windows_environment_excludes_ambient_native_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_release.platform, "system", lambda: "Windows")
    monkeypatch.setattr(build_release.sys, "executable", r"C:\Python313\python.exe")
    environment = {
        "PATH": (
            r"C:\Users\owner\.cache\codex-runtimes\dependencies\native\poppler;"
            r"C:\Windows\System32"
        ),
        "SystemRoot": r"C:\Windows",
        "ONYX_BUILD_VERSION": "1.1.10",
    }

    sanitized = build_release.pyinstaller_environment(environment)

    assert "poppler" not in sanitized["PATH"].casefold()
    assert str(Path(r"C:\Python313")) in sanitized["PATH"]
    assert sanitized["ONYX_BUILD_VERSION"] == "1.1.10"


def test_windows_bundle_gate_rejects_foreign_unversioned_icu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_release.platform, "system", lambda: "Windows")
    internal = tmp_path / "Onyx" / "_internal"
    internal.mkdir(parents=True)
    (internal / "icuuc.dll").write_bytes(b"foreign")

    with pytest.raises(RuntimeError, match="foreign Qt ICU collision"):
        build_release.assert_no_windows_qt_icu_collision(tmp_path / "Onyx")


def test_windows_bundle_gate_accepts_system_icu_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_release.platform, "system", lambda: "Windows")
    (tmp_path / "Onyx" / "_internal").mkdir(parents=True)

    build_release.assert_no_windows_qt_icu_collision(tmp_path / "Onyx")


def test_spec_filters_the_known_qt_icu_collision() -> None:
    spec = (
        build_release.ROOT / "packaging" / "onyx.spec"
    ).read_text(encoding="utf-8")

    assert '_forbidden_windows_qt_icu = {"icuuc.dll", "icudt78.dll"}' in spec
    assert "entry\n        for entry in a.binaries" in spec
