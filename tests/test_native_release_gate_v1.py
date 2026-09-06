from __future__ import annotations

import json
import hashlib
import os
import re
import runpy
import shutil
import subprocess
import sys
import tarfile
import zipfile
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.native_startup_smoke_v1 import (
    NATIVE_STARTUP_SMOKE_ARGUMENT,
    NATIVE_STARTUP_SMOKE_CONTRACT,
    NATIVE_STARTUP_SMOKE_OUTPUT_ENV,
    TERMINAL_FENCE_EVIDENCE_KEY,
)
from core.native_activation_contract_v1 import activation_contract_for_system_v1
from scripts import build_release
from scripts.verify_v19_pytest_collection import (
    V19_TEST_FILES,
    collect_v19_tests,
)


def test_directory_snapshot_accepts_concurrent_uninstall_removal() -> None:
    class VanishingDirectory:
        def exists(self) -> bool:
            return True

        def iterdir(self):
            raise FileNotFoundError("removed by uninstaller")

    assert build_release._directory_entries_if_present(VanishingDirectory()) == ()


def test_v19_collection_gate_requires_nonzero_named_files(tmp_path: Path) -> None:
    output = "\n".join(f"{path}::test_collected" for path in V19_TEST_FILES)

    def runner(argv, **kwargs):
        assert argv[:4] == [
            build_release.sys.executable,
            "-m",
            "pytest",
            "--collect-only",
        ]
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(argv, 0, output, "")

    nodes = collect_v19_tests(root=tmp_path, runner=runner)
    assert len(nodes) == len(V19_TEST_FILES)


def test_formal_linux_release_refuses_missing_appimagetool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APPIMAGETOOL", raising=False)
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: None)

    with pytest.raises(
        RuntimeError, match="formal Linux release requires appimagetool"
    ):
        build_release.resolve_appimagetool()
    assert build_release.resolve_appimagetool(diagnostic_without_appimage=True) is None


def test_formal_linux_release_requires_hash_bound_appimage_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APPIMAGE_RUNTIME_FILE", raising=False)
    with pytest.raises(RuntimeError, match="requires the pinned AppImage runtime"):
        build_release.resolve_appimage_runtime()

    runtime = tmp_path / "runtime-x86_64"
    runtime.write_bytes(b"trusted-runtime")
    monkeypatch.setenv("APPIMAGE_RUNTIME_FILE", str(runtime))
    monkeypatch.setattr(build_release, "architecture", lambda: "x64")
    monkeypatch.setitem(
        build_release.APPIMAGE_RUNTIME_SHA256,
        "x64",
        hashlib.sha256(b"trusted-runtime").hexdigest(),
    )
    assert build_release.resolve_appimage_runtime() == runtime.absolute()

    runtime.write_bytes(b"changed-runtime")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        build_release.resolve_appimage_runtime()


def test_linux_package_passes_pinned_runtime_to_appimagetool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "Onyx").write_bytes(b"binary")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "onyx.png").write_bytes(b"png")
    packaging = tmp_path / "packaging" / "linux"
    packaging.mkdir(parents=True)
    (packaging / "onyx.desktop").write_text(
        "[Desktop Entry]\nExec=/opt/cyryx-labs/onyx/Onyx\n",
        encoding="utf-8",
    )
    (packaging / "onyx.service").write_text(
        "[Service]\nExecStart=/opt/cyryx-labs/onyx/Onyx\n",
        encoding="utf-8",
    )
    (packaging / "com.cyryxlabs.onyx.metainfo.xml").write_text(
        '<component type="desktop-application"><id>com.cyryxlabs.onyx</id></component>\n',
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime-x86_64"
    runtime.write_bytes(b"runtime")
    appimagetool = tmp_path / "appimagetool"
    appimagetool.write_bytes(b"tool")
    observed: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        command = [str(item) for item in argv]
        observed.append(command)
        if command[0] == "dpkg-deb":
            Path(command[-1]).write_bytes(b"deb")
        elif command[0] == str(appimagetool):
            Path(command[-1]).write_bytes(b"appimage")

    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release, "BUILD", tmp_path / "build")
    monkeypatch.setattr(build_release, "RELEASE", tmp_path / "release")
    monkeypatch.setattr(build_release, "ASSETS", assets)
    monkeypatch.setattr(build_release, "architecture", lambda: "x64")
    monkeypatch.setattr(
        build_release, "resolve_appimagetool", lambda **_kwargs: appimagetool
    )
    monkeypatch.setattr(build_release, "resolve_appimage_runtime", lambda: runtime)
    monkeypatch.setattr(build_release, "run", fake_run)

    artifacts = build_release.package_linux(bundle, "1.1.9")

    appimage_commands = [
        command for command in observed if command[0] == str(appimagetool)
    ]
    assert appimage_commands == [
        [
            str(appimagetool),
            "--runtime-file",
            str(runtime),
            str(tmp_path / "build" / "Onyx.AppDir"),
            str(tmp_path / "release" / "Onyx-1.1.9-Linux-x64.AppImage"),
        ]
    ]
    assert any(path.suffix == ".AppImage" for path in artifacts)
    assert (
        tmp_path
        / "build"
        / "Onyx.AppDir"
        / "usr"
        / "share"
        / "metainfo"
        / "com.cyryxlabs.onyx.metainfo.xml"
    ).is_file()


def test_linux_deb_metadata_declares_exact_runtime_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "deb-root"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "Onyx").write_bytes(b"\x7fELF")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "onyx.png").write_bytes(b"png")
    desktop = tmp_path / "onyx.desktop"
    desktop.write_text("[Desktop Entry]\nExec=/opt/cyryx-labs/onyx/Onyx\n")

    monkeypatch.setattr(build_release, "ASSETS", assets)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(
        build_release.os,
        "symlink",
        lambda source, target: Path(target).write_text(str(source), encoding="utf-8"),
    )
    (tmp_path / "packaging" / "linux").mkdir(parents=True)
    desktop.replace(tmp_path / "packaging" / "linux" / "onyx.desktop")
    (tmp_path / "packaging" / "linux" / "onyx.service").write_text(
        "[Service]\nExecStart=/opt/cyryx-labs/onyx/Onyx\n",
        encoding="utf-8",
    )
    (tmp_path / "packaging" / "linux" / "com.cyryxlabs.onyx.metainfo.xml").write_text(
        '<component type="desktop-application"><id>com.cyryxlabs.onyx</id></component>\n',
        encoding="utf-8",
    )

    build_release.write_linux_tree(root, bundle, "1.1.8")

    fields = {}
    for line in (root / "DEBIAN" / "control").read_text(encoding="utf-8").splitlines():
        if ": " in line and not line.startswith(" "):
            name, value = line.split(": ", 1)
            fields[name] = value
    dependencies = tuple(item.strip() for item in fields["Depends"].split(","))
    assert dependencies == build_release.LINUX_DEB_RUNTIME_DEPENDENCIES
    assert dependencies.count("libegl1") == 1
    assert {
        "libgtk-3-0",
        "libpulse0",
        "libxcb-icccm4",
        "libxcb-keysyms1",
        "libxcb-shape0",
        "libxcb-xkb1",
        "libxkbcommon-x11-0",
        "libxtst6",
    }.issubset(dependencies)
    assert (
        root / "usr" / "share" / "metainfo" / "com.cyryxlabs.onyx.metainfo.xml"
    ).is_file()


def test_formal_linux_structure_gate_requires_exactly_one_appimage(
    tmp_path: Path,
) -> None:
    package = tmp_path / "Onyx.deb"
    archive = tmp_path / "Onyx.tar.gz"
    package.write_bytes(b"deb")
    archive.write_bytes(b"tar")

    with pytest.raises(RuntimeError, match="requires exactly one AppImage"):
        build_release.package_artifact_structure_test(
            [package, archive],
            system="Linux",
        )

    first = tmp_path / "Onyx-a.AppImage"
    second = tmp_path / "Onyx-b.AppImage"
    first.write_bytes(b"\x7fELF-a")
    second.write_bytes(b"\x7fELF-b")
    with pytest.raises(RuntimeError, match="requires exactly one AppImage"):
        build_release.package_artifact_structure_test(
            [package, archive, first, second],
            system="Linux",
        )


def test_build_cleanup_rejects_symlink_or_junction_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    target = root / "real-build"
    target.mkdir()
    marker = target / "owner-data.txt"
    marker.write_text("preserve", encoding="utf-8")
    linked = root / "build"
    monkeypatch.setattr(build_release, "ROOT", root)
    monkeypatch.setattr(
        build_release,
        "_is_link_like",
        lambda candidate: candidate == linked,
    )

    with pytest.raises(RuntimeError, match="linked/reparse"):
        build_release.clean_path(linked)
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_v19_collection_gate_rejects_false_green_zero(tmp_path: Path) -> None:
    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, "no tests collected", "")

    with pytest.raises(RuntimeError, match="zero tests"):
        collect_v19_tests(root=tmp_path, runner=runner)


def test_appimage_desktop_exec_is_local_and_deb_source_is_unchanged(
    tmp_path: Path,
) -> None:
    source = tmp_path / "deb.desktop"
    target = tmp_path / "appimage.desktop"
    original = (
        "[Desktop Entry]\nType=Application\nExec=/opt/cyryx-labs/onyx/Onyx\nIcon=onyx\n"
    )
    source.write_text(original, encoding="utf-8")

    build_release.write_appimage_desktop(source, target)

    assert source.read_text(encoding="utf-8") == original
    rendered = target.read_text(encoding="utf-8")
    assert "Exec=onyx" in rendered
    assert "Exec=/opt/" not in rendered


def test_packaged_native_smoke_executes_real_gate_contract(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    executable = bundle / "Onyx.exe"
    executable.touch()
    observed: dict[str, object] = {}

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["timeout"] = kwargs["timeout"]
        observed["activation_env"] = {
            "v24": kwargs["env"].get("ONYX_LIVE_ACTIVATION_V24"),
            "v23": kwargs["env"].get("ONYX_LIVE_ACTIVATION_V23"),
            "operational_events": kwargs["env"].get("ONYX_OPERATIONAL_EVENTS_V1"),
            "v22": kwargs["env"].get("ONYX_LIVE_ACTIVATION_V22"),
            "owner_context": kwargs["env"].get("ONYX_OWNER_CONTEXT_V1"),
            "v21": kwargs["env"].get("ONYX_LIVE_ACTIVATION_V21"),
            "commands": kwargs["env"].get("ONYX_ADVANCED_OPERATIONS_COMMANDS_V1"),
            "workspace": kwargs["env"].get("ONYX_WORKSPACE_ROOTS"),
            "ambient_v20": kwargs["env"].get("ONYX_LIVE_ACTIVATION_V20"),
        }
        output = Path(kwargs["env"][NATIVE_STARTUP_SMOKE_OUTPUT_ENV])
        output.write_text(
            json.dumps(
                {
                    "activation": "v24",
                    "activation_contract": activation_contract_for_system_v1("Windows"),
                    "activation_profile": "current-windows",
                    "callbacks_bound": True,
                    "capability_limited": False,
                    "contract": NATIVE_STARTUP_SMOKE_CONTRACT,
                    "host_constructed": True,
                    "interception": {
                        "scope": "best_effort_python_runtime",
                        "network_surfaces": [
                            "network:socket.create_connection",
                            "network:socket.getaddrinfo",
                            "network:socket.socket.send",
                            "network:socket.socket.sendall",
                            "network:socket.socket.sendto",
                        ],
                        "process_surfaces": ["process:subprocess.Popen"],
                        "provider_surfaces": ["provider:google.genai.Client"],
                        "secure_backend_probe_calls": 0,
                        "secure_backend_probe_surfaces": [],
                    },
                    "network_calls": 0,
                    "process_calls": 0,
                    "provider_calls": 0,
                    "secure_backend_probe_calls": 0,
                    "real_ui": True,
                    "status": "passed",
                    "system": "Windows",
                    TERMINAL_FENCE_EVIDENCE_KEY: True,
                    "ui_renderer": "cinematic-v5",
                    "window_visible": True,
                }
            ),
            encoding="utf-8",
        )
        v24_launcher_log = (
            Path(kwargs["env"]["ONYX_DATA_DIR"])
            / "runtime"
            / "logs"
            / "onyx-live-v24-startup.log"
        )
        v24_launcher_log.parent.mkdir(parents=True)
        v24_launcher_log.write_text(
            "entering stable V24 launcher\n",
            encoding="utf-8",
        )
        v23_launcher_log = v24_launcher_log.parent / "onyx-live-v23-startup.log"
        v23_launcher_log.write_text(
            "entering stable V23 launcher\n",
            encoding="utf-8",
        )
        v22_launcher_log = v23_launcher_log.parent / "onyx-live-v22-startup.log"
        v22_launcher_log.write_text(
            "entering stable V22 launcher\n",
            encoding="utf-8",
        )
        launcher_log = v22_launcher_log.parent / "onyx-live-v21-startup.log"
        launcher_log.parent.mkdir(parents=True, exist_ok=True)
        launcher_log.write_text(
            "entering stable V21 launcher\n",
            encoding="utf-8",
        )
        (launcher_log.parent / "onyx-live-v20-startup.log").write_text(
            "entering stable V20 launcher\n",
            encoding="utf-8",
        )
        (launcher_log.parent / "onyx-live-v19-startup.log").write_text(
            "entering stable V19 launcher\nOnyx native startup smoke passed\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0)

    with (
        patch.dict("os.environ", {"ONYX_LIVE_ACTIVATION_V20": "1"}),
        patch.object(build_release.platform, "system", return_value="Windows"),
        patch.object(build_release.subprocess, "run", side_effect=run),
    ):
        build_release.package_native_startup_smoke_test(bundle)

    assert observed["argv"] == [str(executable), NATIVE_STARTUP_SMOKE_ARGUMENT]
    assert observed["timeout"] == 240
    assert observed["activation_env"] == {
        "v24": "1",
        "v23": "1",
        "operational_events": "true",
        "v22": "1",
        "owner_context": "true",
        "v21": "1",
        "commands": "true",
        "workspace": observed["activation_env"]["workspace"],
        "ambient_v20": "1",
    }
    assert "onyx-native-startup-smoke-" in str(observed["activation_env"]["workspace"])


def _native_smoke_payload(system: str) -> dict[str, object]:
    activation_contract = activation_contract_for_system_v1(system)
    return {
        "activation": activation_contract["smoke_activation"],
        "activation_contract": activation_contract,
        "activation_profile": activation_contract["activation_profile"],
        "callbacks_bound": True,
        "capability_limited": activation_contract["capability_limited"],
        "contract": NATIVE_STARTUP_SMOKE_CONTRACT,
        "host_constructed": True,
        "interception": {
            "scope": "best_effort_python_runtime",
            "network_surfaces": [
                "network:socket.getaddrinfo",
                "network:socket.socket.send",
                "network:socket.socket.sendall",
                "network:socket.socket.sendto",
            ],
            "process_surfaces": ["process:subprocess.Popen"],
            "provider_surfaces": ["provider:google.genai.Client"],
            "secure_backend_probe_calls": 0,
            "secure_backend_probe_surfaces": [],
        },
        "network_calls": 0,
        "process_calls": 0,
        "provider_calls": 0,
        "secure_backend_probe_calls": 0,
        "real_ui": True,
        "status": "passed",
        "system": system,
        TERMINAL_FENCE_EVIDENCE_KEY: True,
        "ui_renderer": "cinematic-v5",
        "window_visible": True,
    }


def test_linux_appimage_executes_with_extract_and_run_and_json_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appimage = tmp_path / "Onyx.AppImage"
    appimage.write_bytes(b"\x7fELF-appimage")
    observed: dict[str, object] = {}

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["extract"] = kwargs["env"].get("APPIMAGE_EXTRACT_AND_RUN")
        output = Path(kwargs["env"][NATIVE_STARTUP_SMOKE_OUTPUT_ENV])
        output.write_text(
            json.dumps(_native_smoke_payload("Linux")),
            encoding="utf-8",
        )
        launcher_log = (
            Path(kwargs["env"]["ONYX_DATA_DIR"])
            / "runtime"
            / "logs"
            / "onyx-live-v19-startup.log"
        )
        launcher_log.parent.mkdir(parents=True)
        launcher_log.write_text(
            "entering stable V19 launcher\nOnyx native startup smoke passed\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(build_release.subprocess, "run", run)

    payload = build_release.package_native_startup_executable_smoke_test(
        appimage,
        system="Linux",
        extra_environment={"APPIMAGE_EXTRACT_AND_RUN": "1"},
    )

    assert observed == {
        "argv": [str(appimage), NATIVE_STARTUP_SMOKE_ARGUMENT],
        "extract": "1",
    }
    assert payload["contract"] == NATIVE_STARTUP_SMOKE_CONTRACT


def test_linux_appimage_smoke_fails_closed_on_invalid_json_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appimage = tmp_path / "Onyx.AppImage"
    appimage.write_bytes(b"\x7fELF-appimage")

    def run(argv, **kwargs):
        output = Path(kwargs["env"][NATIVE_STARTUP_SMOKE_OUTPUT_ENV])
        output.write_text("not-json", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(build_release.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="no valid JSON contract"):
        build_release.package_native_startup_executable_smoke_test(
            appimage,
            system="Linux",
            extra_environment={"APPIMAGE_EXTRACT_AND_RUN": "1"},
        )


@pytest.mark.parametrize(
    ("marker", "accepted"),
    (
        (True, True),
        (False, False),
        (1, False),
        (1.0, False),
        ("true", False),
        (None, False),
        ([], False),
        ({}, False),
    ),
)
def test_release_gate_accepts_only_literal_true_terminal_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker: object,
    accepted: bool,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()
    payload = _native_smoke_payload("Linux")
    payload[TERMINAL_FENCE_EVIDENCE_KEY] = marker

    def run(argv, **kwargs):
        output = Path(kwargs["env"][NATIVE_STARTUP_SMOKE_OUTPUT_ENV])
        output.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(build_release.subprocess, "run", run)
    if accepted:
        result = build_release.package_native_startup_executable_smoke_test(
            executable,
            system="Linux",
        )
        assert result[TERMINAL_FENCE_EVIDENCE_KEY] is True
    else:
        with pytest.raises(RuntimeError, match="result is invalid"):
            build_release.package_native_startup_executable_smoke_test(
                executable,
                system="Linux",
            )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("capability_limited", 1),
        ("v15_v19_parity", 0),
    ),
)
def test_release_gate_rejects_integer_aliases_in_activation_contract_booleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: int,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()
    payload = _native_smoke_payload("Linux")
    activation = dict(payload["activation_contract"])
    activation[field] = replacement
    payload["activation_contract"] = activation

    def run(argv, **kwargs):
        output = Path(kwargs["env"][NATIVE_STARTUP_SMOKE_OUTPUT_ENV])
        output.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(build_release.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="result is invalid"):
        build_release.package_native_startup_executable_smoke_test(
            executable,
            system="Linux",
        )


def test_linux_artifact_gate_executes_the_single_formal_appimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "Onyx.deb"
    package.touch()
    archive = tmp_path / "Onyx.tar.gz"
    tar_source = tmp_path / "tar-source" / "Onyx"
    tar_source.mkdir(parents=True)
    (tar_source / "Onyx").touch()
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(tar_source, arcname="Onyx")
    appimages = [tmp_path / "Onyx.AppImage"]
    for appimage in appimages:
        appimage.touch()
    calls: list[tuple[Path, str, dict[str, str] | None]] = []

    def extract(argv, **_kwargs):
        destination = Path(argv[-1])
        bundle = destination / "opt" / "cyryx-labs" / "onyx"
        bundle.mkdir(parents=True)
        (bundle / "Onyx").touch()
        return subprocess.CompletedProcess(argv, 0, "", "")

    def bundle_smoke(bundle: Path) -> dict[str, object]:
        calls.append((bundle / "Onyx", "bundle", None))
        return _native_smoke_payload("Linux")

    def executable_smoke(
        executable: Path,
        *,
        system: str,
        extra_environment: dict[str, str] | None = None,
    ) -> dict[str, object]:
        calls.append((executable, system, extra_environment))
        return _native_smoke_payload(system)

    monkeypatch.setattr(build_release.subprocess, "run", extract)
    monkeypatch.setattr(
        build_release, "package_native_startup_smoke_test", bundle_smoke
    )
    monkeypatch.setattr(
        build_release,
        "package_native_startup_executable_smoke_test",
        executable_smoke,
    )

    build_release.package_artifact_entrypoint_smoke_test(
        [package, archive, *appimages],
        system="Linux",
    )

    assert calls[0][1] == "bundle"
    assert calls[1][1] == "bundle"
    assert calls[2:] == [
        (appimages[0], "Linux", {"APPIMAGE_EXTRACT_AND_RUN": "1"}),
    ]


def _write_windows_portable(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as handle:
        handle.writestr("Onyx/Onyx.exe", b"MZportable-entrypoint")
        handle.writestr("Onyx/_internal/core/onyx_live_activation_v19.py", b"v19")
        handle.writestr("Onyx/_internal/core/onyx_live_activation_v20.py", b"v20")
        handle.writestr("Onyx/_internal/core/onyx_live_activation_v21.py", b"v21")
        handle.writestr("Onyx/_internal/core/onyx_live_activation_v22.py", b"v22")
        handle.writestr("Onyx/_internal/core/onyx_live_activation_v23.py", b"v23")
        handle.writestr("Onyx/_internal/core/onyx_live_activation_v24.py", b"v24")
        handle.writestr(
            "Onyx/_internal/core/owner_context_controller_v1.py", b"controller"
        )
        handle.writestr("Onyx/_internal/core/owner_context_profile_v1.py", b"profile")
        handle.writestr("Onyx/_internal/core/operational_event_bridge_v1.py", b"bridge")
        handle.writestr(
            "Onyx/_internal/core/operational_event_controller_v1.py", b"controller"
        )
        handle.writestr(
            "Onyx/_internal/scripts/bootstrap_onyx_live_v19.pyw",
            b"bootstrap",
        )
        handle.writestr(
            "Onyx/_internal/scripts/launch_onyx_live_v19.pyw",
            b"launcher",
        )
        handle.writestr(
            "Onyx/_internal/scripts/bootstrap_onyx_live_v20.pyw",
            b"bootstrap",
        )
        handle.writestr(
            "Onyx/_internal/scripts/launch_onyx_live_v20.pyw",
            b"launcher",
        )
        handle.writestr(
            "Onyx/_internal/scripts/bootstrap_onyx_live_v21.pyw",
            b"bootstrap",
        )
        handle.writestr(
            "Onyx/_internal/scripts/launch_onyx_live_v21.pyw",
            b"launcher",
        )
        handle.writestr(
            "Onyx/_internal/scripts/bootstrap_onyx_live_v22.pyw",
            b"bootstrap",
        )
        handle.writestr(
            "Onyx/_internal/scripts/launch_onyx_live_v22.pyw",
            b"launcher",
        )
        handle.writestr(
            "Onyx/_internal/scripts/bootstrap_onyx_live_v23.pyw",
            b"bootstrap",
        )
        handle.writestr(
            "Onyx/_internal/scripts/launch_onyx_live_v23.pyw",
            b"launcher",
        )
        handle.writestr(
            "Onyx/_internal/scripts/bootstrap_onyx_live_v24.pyw",
            b"bootstrap",
        )
        handle.writestr(
            "Onyx/_internal/scripts/launch_onyx_live_v24.pyw",
            b"launcher",
        )


def test_windows_finished_artifacts_have_structural_entrypoint_chain(
    tmp_path: Path,
) -> None:
    setup = tmp_path / "Onyx-1.0.0-Windows-x64-Setup.exe"
    setup.write_bytes(b"MZsetup")
    archive = tmp_path / "Onyx-1.0.0-Windows-x64-Portable.zip"
    _write_windows_portable(archive)

    build_release.package_artifact_structure_test(
        [setup, archive],
        system="Windows",
    )


def test_windows_finished_portable_executes_artifact_entrypoint_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "Onyx-1.0.0-Windows-x64-Portable.zip"
    _write_windows_portable(archive)
    setup = tmp_path / "Onyx-1.0.0-Windows-x64-Setup.exe"
    setup.touch()
    observed: list[Path] = []
    installed: list[Path] = []

    def smoke(bundle: Path) -> None:
        assert (bundle / "Onyx.exe").read_bytes().startswith(b"MZ")
        observed.append(bundle)

    monkeypatch.setattr(build_release, "package_native_startup_smoke_test", smoke)

    def setup_smoke(
        setup_path: Path,
        *,
        source_bundle: Path | None = None,
        version: str | None = None,
    ) -> None:
        assert source_bundle is not None
        assert version == "1.0.0"
        installed.append(setup_path)

    monkeypatch.setattr(
        build_release,
        "package_windows_setup_install_smoke_test",
        setup_smoke,
    )

    build_release.package_artifact_entrypoint_smoke_test(
        [archive, setup],
        system="Windows",
    )

    assert len(observed) == 1
    assert installed == [setup]


def test_windows_setup_isolated_install_smoke_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = tmp_path / "Onyx-1.0.0-Windows-x64-Setup.exe"
    setup.touch()
    commands: list[list[str]] = []
    smoke_paths: list[Path] = []

    def run(argv, **_kwargs):
        commands.append(argv)
        if Path(argv[0]) == setup:
            install_dir = Path(
                next(item[5:] for item in argv if item.startswith("/DIR="))
            )
            install_dir.mkdir(parents=True)
            (install_dir / "Onyx.exe").touch()
            (install_dir / "unins000.exe").touch()
        else:
            install_dir = Path(argv[0]).parent
            for child in tuple(install_dir.iterdir()):
                child.unlink()
            install_dir.rmdir()
        return subprocess.CompletedProcess(argv, 0, "", "")

    def smoke(bundle: Path) -> dict[str, object]:
        assert (bundle / "Onyx.exe").is_file()
        smoke_paths.append(bundle)
        return _native_smoke_payload("Windows")

    monkeypatch.setattr(
        build_release,
        "_run_windows_setup_smoke_install",
        run,
    )
    monkeypatch.setattr(build_release.subprocess, "run", run)
    monkeypatch.setattr(build_release, "package_native_startup_smoke_test", smoke)
    monkeypatch.setattr(
        build_release,
        "_build_isolated_windows_smoke_setup",
        lambda _setup, **_kwargs: setup,
    )

    build_release.package_windows_setup_install_smoke_test(setup)

    assert len(smoke_paths) == 1
    assert len(commands) == 2
    assert "/VERYSILENT" in commands[0]
    assert "/CURRENTUSER" in commands[0]
    assert "/NOICONS" in commands[0]
    assert any(item.startswith("/DIR=") for item in commands[0])
    assert Path(commands[1][0]).name == "unins000.exe"


def test_windows_setup_timeout_terminates_only_its_exact_process_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taskkill_commands: list[list[str]] = []

    class Process:
        pid = 4242
        returncode = 1

        def __init__(self) -> None:
            self.calls = 0

        def communicate(self, *, timeout: float):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(["Setup.exe"], timeout)
            return "", ""

    monkeypatch.setattr(build_release.subprocess, "Popen", lambda *_a, **_k: Process())
    monkeypatch.setattr(build_release.platform, "system", lambda: "Windows")

    def run(argv, **_kwargs):
        taskkill_commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(build_release.subprocess, "run", run)

    with pytest.raises(subprocess.TimeoutExpired):
        build_release._run_windows_setup_smoke_install(
            ["Setup.exe", "/VERYSILENT"],
            cwd=Path(__file__).resolve().parents[1],
            timeout=0.01,
        )

    assert taskkill_commands == [["taskkill", "/PID", "4242", "/T", "/F"]]


def test_windows_setup_cleanup_residual_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = tmp_path / "Onyx-1.0.0-Windows-x64-Setup.exe"
    setup.touch()

    def run(argv, **_kwargs):
        if Path(argv[0]) == setup:
            install_dir = Path(
                next(item[5:] for item in argv if item.startswith("/DIR="))
            )
            install_dir.mkdir(parents=True)
            (install_dir / "Onyx.exe").touch()
            (install_dir / "unins000.exe").touch()
            (install_dir / "residual.bin").touch()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(
        build_release,
        "_run_windows_setup_smoke_install",
        run,
    )
    monkeypatch.setattr(build_release.subprocess, "run", run)
    monkeypatch.setattr(
        build_release,
        "_build_isolated_windows_smoke_setup",
        lambda _setup, **_kwargs: setup,
    )
    monkeypatch.setattr(
        build_release,
        "package_native_startup_smoke_test",
        lambda _bundle: _native_smoke_payload("Windows"),
    )

    with pytest.raises(RuntimeError, match="installed-payload-remained"):
        build_release.package_windows_setup_install_smoke_test(setup)


def test_v19_dayops_launcher_reports_observed_not_literal_counters() -> None:
    launcher = (
        Path(__file__).resolve().parents[1] / "scripts" / "launch_onyx_live_v19.pyw"
    ).read_text(encoding="utf-8")

    assert '"network_calls": calls.network' in launcher
    assert '"provider_calls": calls.provider' in launcher
    assert '"process_calls": calls.process' in launcher
    assert '"interception": calls.evidence()' in launcher
    assert "interception_scope={INTERCEPTION_SCOPE}" in launcher


def test_packaged_dayops_requires_interception_backed_zero_counters(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "Onyx.exe").touch()
    payload = {
        "contract": "OnyxDayOpsSmoke.v20",
        "status": "passed",
        "connection_status": "configuration_required",
        "read_only": True,
        "callbacks_bound": True,
        "advanced_callbacks_bound": True,
        "advanced_controller_status": "waiting_for_live_session",
        "interception": {
            "scope": "best_effort_python_runtime",
            "network_surfaces": ["network:socket.create_connection"],
            "process_surfaces": ["process:subprocess.Popen"],
            "provider_surfaces": ["provider:google.genai.Client"],
        },
        "network_calls": 0,
        "provider_calls": 0,
        "process_calls": 0,
        "trusted_ui_prompts": 0,
    }

    def run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    with (
        patch.object(build_release.platform, "system", return_value="Windows"),
        patch.object(build_release.subprocess, "run", side_effect=run),
    ):
        build_release.package_dayops_smoke_test(bundle)


def test_ci_and_release_workflows_use_pytest_not_unittest() -> None:
    root = Path(__file__).resolve().parents[1]
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = (root / ".github/workflows/release-packages.yml").read_text(
        encoding="utf-8"
    )
    combined = ci + release
    assert "unittest discover" not in combined
    assert "verify_v19_pytest_collection.py" in ci
    assert "verify_v19_pytest_collection.py" in release
    assert "--require-hashes -r requirements.lock" in ci
    assert "--require-hashes -r requirements.lock" in release


def test_release_supply_chain_is_immutable_or_fail_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / ".github" / "workflows").glob("*.yml"))
    )
    uses = re.findall(r"uses:\s*[^\s@]+@([^\s#]+)", workflows)
    verified_action_revisions = {
        "11d5960a326750d5838078e36cf38b85af677262",  # actions/checkout v4
        "a26af69be951a213d495a4c3e4e4022e16d87065",  # actions/setup-python v5
        "ea165f8d65b6e75b540449e92b4886f43607fa02",  # actions/upload-artifact v4
        "d3f86a106a0bac45b974a628896c90dbdf5c8093",  # actions/download-artifact v4
    }

    assert uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in uses)
    assert set(uses) == verified_action_revisions
    assert "choco install innosetup --version=6.7.1" in workflows
    assert "choco install innosetup --no-progress" not in workflows


def test_universal_dependency_lock_is_exact_and_hash_verified() -> None:
    root = Path(__file__).resolve().parents[1]
    lock = (root / "requirements.lock").read_text(encoding="utf-8")
    dev = (root / "requirements-dev.txt").read_text(encoding="utf-8")
    package_lines = [
        line for line in lock.splitlines() if line and not line.startswith((" ", "#"))
    ]

    assert "--universal --python-version 3.11 --generate-hashes" in lock
    assert len(package_lines) > 100
    assert all("==" in line and line.endswith("\\") for line in package_lines)
    assert lock.count("--hash=sha256:") >= len(package_lines)
    assert "httpx2>=2.9,<3" in dev
    assert re.search(r"^httpx2==2\.9\.1 \\$", lock, re.MULTILINE)
    assert re.search(r"^httpcore2==2\.9\.1 \\$", lock, re.MULTILINE)
    assert re.search(r"^truststore==0\.10\.4 \\$", lock, re.MULTILINE)


def test_build_input_snapshot_fails_closed_on_mutation_and_membership_change(
    tmp_path: Path,
) -> None:
    first = tmp_path / "main.py"
    second = tmp_path / "ui.py"
    first.write_text("main-v1", encoding="utf-8")
    second.write_text("ui-v1", encoding="utf-8")
    files = (first, second)
    snapshot = build_release._snapshot_build_input_files(files, root=tmp_path)

    build_release._verify_build_input_snapshot(snapshot, files, root=tmp_path)
    first.write_text("main-v2", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed after sealing"):
        build_release._verify_build_input_snapshot(snapshot, files, root=tmp_path)

    first.write_text("main-v1", encoding="utf-8")
    added = tmp_path / "actions.py"
    added.write_text("new-input", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed after sealing"):
        build_release._verify_build_input_snapshot(
            snapshot,
            (*files, added),
            root=tmp_path,
        )


def test_pyinstaller_input_discovery_covers_entrypoints_and_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = Path(__file__).resolve().parents[1]
    root = tmp_path / "release-input-discovery"
    from scripts.package_hygiene import (
        COMPATIBILITY_LAUNCHER_RELATIVE,
        COMPATIBILITY_NOTICE_RELATIVE,
        HUMANOID_PRESENCE_RUNTIME_FILES,
        PACKAGED_RUNTIME_HUD_CONTRACT_MANIFEST,
        RUNTIME_TEST_EVIDENCE_FILES,
        STAGED_COMPATIBILITY_LAUNCHER,
        STAGED_COMPATIBILITY_NOTICE,
        discover_runtime_docs,
        stage_runtime_docs,
        stage_runtime_sources,
    )
    from core.onyx_hud_current_acceptance_v32 import (
        CURRENT_RUNTIME_PATHS,
        MANIFEST_RELATIVE as HUD_V32_MANIFEST_RELATIVE,
        PREDECESSOR_ACCEPTANCE_RELATIVE as HUD_V32_PREDECESSOR_ACCEPTANCE,
        PREDECESSOR_MANIFEST_RELATIVE as HUD_V32_PREDECESSOR_MANIFEST,
    )

    def copy_relative(relative: str) -> None:
        source = source_root / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    for relative in (
        "main.py",
        "ui.py",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "packaging/onyx.spec",
        "packaging/windows/onyx.iss",
        "packaging/windows/inno/Default.isl",
        "packaging/windows/inno/LICENSE.txt",
        "packaging/licenses/LGPL-3.0.txt",
        "packaging/linux/onyx.desktop",
        "packaging/linux/com.cyryxlabs.onyx.metainfo.xml",
        "packaging/linux/onyx.service",
        "packaging/macos/entitlements.plist",
        "packaging/macos/browser-entitlements.plist",
        "packaging/macos/labs.cyryx.onyx.plist",
        "packaging/assets/onyx-app-icon-master-v2.png",
        COMPATIBILITY_LAUNCHER_RELATIVE,
        COMPATIBILITY_NOTICE_RELATIVE,
        "requirements-build.txt",
        "requirements.txt",
        "requirements.lock",
        "core/prompt.txt",
        "core/onyx_packaged_runtime_hud_contract_v1.manifest.json",
        PACKAGED_RUNTIME_HUD_CONTRACT_MANIFEST,
        *(
            relative
            for relative in HUMANOID_PRESENCE_RUNTIME_FILES
            if relative.endswith(".manifest.json")
        ),
        "dashboard/static/crypto-js.LICENSE.txt",
        "dashboard/static/crypto-js.PROVENANCE.json",
        "docs/onyx/checkpoints/phase7-workspace-memory-v1/manifest.json",
        "docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.md",
        "docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.manifest.json",
        "docs/onyx/VE-ACCEPTANCE-P7-WORKSPACE-MEMORY-V1-E6-001.sha256",
        *RUNTIME_TEST_EVIDENCE_FILES,
        "tests/conftest.py",
        "tests/test_package_hygiene_v1.py",
        "tests/test_packaged_runtime_hud_contract_v1.py",
        "tests/test_pyside6_hud_collection_compat.py",
        *discover_runtime_docs(source_root),
        HUD_V32_MANIFEST_RELATIVE.as_posix(),
        HUD_V32_PREDECESSOR_ACCEPTANCE.as_posix(),
        HUD_V32_PREDECESSOR_MANIFEST.as_posix(),
        *(path.as_posix() for path in CURRENT_RUNTIME_PATHS),
    ):
        copy_relative(relative)
    for directory, suffixes in (
        ("core", {".py", ".pyw"}),
        ("actions", {".py", ".pyw"}),
        ("config", {".py", ".pyw"}),
        ("memory", {".py", ".pyw"}),
        ("scripts", {".py", ".pyw"}),
        ("dashboard", None),
        ("qml", None),
    ):
        for source in sorted((source_root / directory).rglob("*")):
            if (
                not source.is_file()
                or source.is_symlink()
                or (suffixes is not None and source.suffix.casefold() not in suffixes)
            ):
                continue
            folded = tuple(
                part.casefold()
                for part in source.relative_to(source_root / directory).parts
            )
            if any(
                part == "__pycache__" or part.startswith((".pytest", ".tmp", ".review"))
                for part in folded
            ):
                continue
            copy_relative(source.relative_to(source_root).as_posix())

    build_root = root / "build"
    build_root.mkdir(exist_ok=True)
    runtime_sources = build_root / "runtime-sources"
    runtime_docs = build_root / "runtime-docs" / "onyx"
    assets = build_root / "assets"
    stage_runtime_sources(root, runtime_sources)
    runtime_doc_sources = stage_runtime_docs(root, runtime_docs)
    asset_marker = assets / "staged-origin.ico"
    asset_marker.parent.mkdir(parents=True, exist_ok=True)
    asset_marker.write_bytes(b"sealed-staged-input")
    monkeypatch.setattr(build_release, "ROOT", root)
    monkeypatch.setattr(build_release, "RUNTIME_SOURCES", runtime_sources)
    monkeypatch.setattr(build_release, "RUNTIME_DOCS", runtime_docs)
    monkeypatch.setattr(build_release, "ASSETS", assets)
    relatives = {
        path.relative_to(root).as_posix()
        for path in build_release._first_party_build_input_files()
    }

    assert asset_marker.relative_to(root).as_posix() in relatives
    for source in RUNTIME_TEST_EVIDENCE_FILES:
        assert source in relatives
        assert (runtime_sources / source).relative_to(root).as_posix() in relatives
    for source in runtime_doc_sources:
        staged = runtime_docs / Path(source).relative_to("docs/onyx")
        assert source in relatives
        assert staged.relative_to(root).as_posix() in relatives
    for staged in (
        runtime_sources / STAGED_COMPATIBILITY_LAUNCHER,
        runtime_sources / STAGED_COMPATIBILITY_NOTICE,
    ):
        assert staged.relative_to(root).as_posix() in relatives

    for relative in (
        "main.py",
        "ui.py",
        "packaging/onyx.spec",
        "packaging/windows/onyx.iss",
        "packaging/windows/inno/Default.isl",
        "packaging/windows/inno/LICENSE.txt",
        "packaging/linux/onyx.desktop",
        "packaging/linux/com.cyryxlabs.onyx.metainfo.xml",
        "packaging/macos/entitlements.plist",
        "packaging/macos/browser-entitlements.plist",
        "packaging/assets/onyx-app-icon-master-v2.png",
        "packaging/compat/venvwlauncher-python313-x64.exe",
        "packaging/compat/PSF-LICENSE.txt",
        "requirements-build.txt",
        "requirements.txt",
        "requirements.lock",
        "scripts/bootstrap_onyx.pyw",
        "scripts/bootstrap_onyx_live_v19.pyw",
        "scripts/launch_onyx_live_v19.pyw",
        "core/prompt.txt",
        "dashboard/server.py",
        "dashboard/static/app.html",
        "actions/open_app.py",
        "actions/computer_control.py",
        "config/__init__.py",
        "memory/memory_manager.py",
        "tests/test_onyx_hud_orb_v7_candidate.py",
        "tests/test_onyx_hud_orb_v8_candidate.py",
        "tests/test_phase6_live_wiring_v2.py",
        "docs/onyx/PHASE11_LOCAL_PROJECT_AUDIT_LIVE_V1.md",
        "docs/onyx/operations/ONYX_V19_DAYOPS_ACCEPTANCE_2026-07-31.md",
    ):
        assert relative in relatives
    assert "config/__init__.py" in relatives
    assert set(RUNTIME_TEST_EVIDENCE_FILES).issubset(relatives)
    assert set(discover_runtime_docs(root)).issubset(relatives)
    assert {
        COMPATIBILITY_LAUNCHER_RELATIVE,
        COMPATIBILITY_NOTICE_RELATIVE,
    }.issubset(relatives)
    assert all(not path.startswith(("runtime/", "rollback/")) for path in relatives)
    assert all("/__pycache__/" not in f"/{path}/" for path in relatives)


def test_native_smoke_routes_through_launcher_mutex_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_native_chain_test",
    )
    events: list[object] = []

    class Mutex:
        def close(self) -> None:
            events.append("mutex.close")

    def acquire(arguments, *, factory=None):
        events.append((arguments, factory))
        return Mutex(), True

    globals_ = namespace["run"].__globals__
    monkeypatch.setitem(globals_, "_acquire_gui_mutex", acquire)
    monkeypatch.setitem(
        globals_,
        "_run_native_startup_diagnostic",
        lambda: events.append("native.diagnostic"),
    )
    monkeypatch.setattr(
        namespace["sys"], "argv", ["Onyx.exe", NATIVE_STARTUP_SMOKE_ARGUMENT]
    )

    namespace["run"]()

    assert events[0][0] == ()
    assert events[0][1] is globals_["_BoundedNativeSmokeMutexV19"]
    assert events[1:] == ["native.diagnostic", "mutex.close"]


@pytest.mark.parametrize("argument", ("--preflight-only", "--dayops-smoke-test"))
def test_v19_diagnostics_never_acquire_production_governance_mutex(
    argument: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_diagnostic_mutex_isolation_test",
    )
    events: list[str] = []

    class Mutex:
        def close(self) -> None:
            events.append("gui.close")

    globals_ = namespace["run"].__globals__
    monkeypatch.setitem(
        globals_,
        "_acquire_gui_mutex",
        lambda _arguments, *, factory=None: (Mutex(), True),
    )
    monkeypatch.setitem(
        globals_,
        "_acquire_governance_runtime_mutex",
        lambda: (_ for _ in ()).throw(AssertionError("production mutex opened")),
    )
    monkeypatch.setitem(
        globals_,
        "_run_bounded_diagnostic",
        lambda arguments: events.append(f"diagnostic:{arguments[0]}"),
    )
    monkeypatch.setattr(namespace["sys"], "argv", ["Onyx.exe", argument])

    namespace["run"]()

    assert events == [f"diagnostic:{argument}", "gui.close"]


def test_v19_normal_launch_retains_production_governance_mutex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.onyx_live_activation_v15 as v15
    import core.onyx_live_activation_v19 as v19

    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_normal_governance_mutex_test",
    )
    events: list[str] = []

    class GuiMutex:
        def close(self) -> None:
            events.append("gui.close")

    class GovernanceMutex:
        def release(self) -> None:
            events.append("governance.release")

    class Controller:
        dayops_capability = "test"

        def rollback_all(self) -> None:
            events.append("controller.rollback")

    fake_main = SimpleNamespace(runtime_dir=lambda: tmp_path / "original-runtime")

    def main() -> None:
        events.append(f"main.run:{fake_main.runtime_dir()}")

    fake_main.main = main
    globals_ = namespace["run"].__globals__
    monkeypatch.setitem(
        globals_,
        "_acquire_gui_mutex",
        lambda _arguments, *, factory=None: (GuiMutex(), True),
    )
    monkeypatch.setitem(
        globals_,
        "_acquire_governance_runtime_mutex",
        lambda: events.append("governance.acquire") or GovernanceMutex(),
    )
    monkeypatch.setitem(globals_, "runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setitem(globals_, "LOG_PATH", tmp_path / "startup.log")
    monkeypatch.setattr(v15, "verify_activation_prerequisites", lambda *_args: None)
    monkeypatch.setattr(v19, "activate_main", lambda _module: Controller())
    monkeypatch.setitem(sys.modules, "main", fake_main)
    monkeypatch.setattr(namespace["sys"], "argv", ["Onyx.exe"])

    namespace["run"]()

    assert events == [
        "governance.acquire",
        f"main.run:{(tmp_path / 'runtime' / 'phase11-authority-v1').resolve()}",
        "controller.rollback",
        "governance.release",
        "gui.close",
    ]


def test_bounded_diagnostic_passes_private_governance_path_to_v19(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.native_startup_smoke_v1 as native
    import core.onyx_live_activation_v15 as v15
    import core.onyx_live_activation_v19 as v19

    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_diagnostic_governance_path_test",
    )
    diagnostic_path = (
        tmp_path / "runtime" / "diagnostic-owned-v19" / "run" / "governance.sqlite3"
    )
    diagnostic_path.parent.mkdir(parents=True)
    diagnostic_phase11 = diagnostic_path.parent / "phase11-authority-v1"
    observed: dict[str, object] = {}

    class DayOps:
        def status(self) -> dict[str, object]:
            return {"status": "configuration_required", "read_only": True}

    class Instance:
        _dayops_connection_controller_v19 = DayOps()

    class Controller:
        def instantiate_live(self, _ui):
            return Instance()

    fake_main = SimpleNamespace(runtime_dir=lambda: tmp_path / "original-runtime")

    def activate(_module, **kwargs):
        observed.update(kwargs)
        return Controller()

    def cleanup_host(**kwargs):
        observed["phase11_runtime"] = kwargs["onyx_main"].runtime_dir()
        kwargs["onyx_main"].runtime_dir = kwargs["original_runtime_dir"]
        return ()

    monkeypatch.setattr(v15, "verify_activation_prerequisites", lambda *_args: None)
    monkeypatch.setattr(v19, "activate_main", activate)
    monkeypatch.setattr(
        native,
        "external_call_boundary_v1",
        lambda **kwargs: nullcontext(kwargs["counters"]),
    )
    monkeypatch.setattr(
        native,
        "_provider_call_boundary_v1",
        lambda *_args, **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(native, "_cleanup_host", cleanup_host)
    monkeypatch.setitem(sys.modules, "main", fake_main)
    globals_ = namespace["_run_bounded_diagnostic"].__globals__

    def nucleus_factory():
        return object()

    monkeypatch.setitem(globals_, "runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setitem(
        globals_,
        "_diagnostic_governance_root_v19",
        lambda _arguments: {
            "boundary": None,
            "canonical_path": diagnostic_path,
            "expected_identity": None,
            "lease": None,
            "path": diagnostic_path,
        },
    )
    monkeypatch.setitem(
        globals_,
        "_diagnostic_governance_factory_v19",
        lambda _path: (nucleus_factory, ()),
    )
    monkeypatch.setitem(
        globals_,
        "_diagnostic_phase11_runtime_v19",
        lambda _path: diagnostic_phase11,
    )
    monkeypatch.setitem(
        globals_,
        "_cleanup_diagnostic_activation_base_v19",
        lambda _controller: (),
    )
    monkeypatch.setitem(
        globals_,
        "_cleanup_diagnostic_governance_v19",
        lambda _path, _vaults, **_kwargs: (),
    )

    namespace["_run_bounded_diagnostic"](("--preflight-only",))

    assert observed["governance_path"] == diagnostic_path
    assert observed["nucleus_factory"] is nucleus_factory
    assert observed["phase11_runtime"] == diagnostic_phase11.resolve()
    assert observed["phase11_runtime"] != (
        tmp_path / "runtime" / "phase11-authority-v1"
    )
    assert "external_agent_factory" in observed


def test_provider_boundary_enter_failure_restores_main_aliases_and_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.native_startup_smoke_v1 as native
    import core.onyx_live_activation_v15 as v15

    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_provider_enter_failure",
    )

    def original_runtime():
        return tmp_path / "original-runtime"

    def original_memory():
        return tmp_path / "original-memory"

    def original_config():
        return tmp_path / "original-config.json"

    fake_main = SimpleNamespace(
        runtime_dir=original_runtime,
        memory_dir=original_memory,
        config_file=original_config,
    )
    locations = {
        "phase11": tmp_path / "diagnostic-phase11",
        "memory": tmp_path / "diagnostic-memory",
        "config": tmp_path / "diagnostic-config",
    }
    events: list[str] = []
    sentinel = RuntimeError("provider-enter-sentinel")

    @contextmanager
    def resources(_arguments):
        try:
            yield {"locations": locations}
        finally:
            events.append("root.cleanup")

    class ProviderBoundary:
        def __enter__(self):
            assert fake_main.runtime_dir() == locations["phase11"].resolve()
            assert fake_main.memory_dir() == locations["memory"].resolve()
            assert (
                fake_main.config_file()
                == (locations["config"] / "api_keys.json").resolve()
            )
            raise sentinel

        def __exit__(self, *_exc):
            pytest.fail("provider __exit__ must not run after __enter__ failure")

    monkeypatch.setattr(v15, "verify_activation_prerequisites", lambda *_args: None)
    monkeypatch.setattr(
        native,
        "external_call_boundary_v1",
        lambda **kwargs: nullcontext(kwargs["counters"]),
    )
    monkeypatch.setattr(
        native,
        "_provider_call_boundary_v1",
        lambda *_args, **_kwargs: ProviderBoundary(),
    )
    monkeypatch.setitem(sys.modules, "main", fake_main)
    globals_ = namespace["_run_bounded_diagnostic"].__globals__
    monkeypatch.setitem(globals_, "_diagnostic_resources_v19", resources)

    with pytest.raises(RuntimeError, match="provider-enter-sentinel") as captured:
        namespace["_run_bounded_diagnostic"](("--preflight-only",))

    assert captured.value is sentinel
    assert fake_main.runtime_dir is original_runtime
    assert fake_main.memory_dir is original_memory
    assert fake_main.config_file is original_config
    assert events == ["root.cleanup"]


@pytest.mark.parametrize(
    "failing_stage",
    ("native", "paths", "governance", "authority", "component"),
)
def test_diagnostic_resource_faults_restore_every_completed_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_stage: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name=f"onyx_v19_fault_{failing_stage}",
    )
    resource_context = namespace["_diagnostic_resources_v19"]
    globals_ = resource_context.__wrapped__.__globals__
    path = tmp_path / "diagnostic" / "governance.sqlite3"
    path.parent.mkdir(parents=True)
    events: list[str] = []
    workspace_flag = "ONYX_WORKSPACE_ROOTS"
    previous = os.environ.get(workspace_flag)

    def fail_or(stage: str, value):
        if stage == failing_stage:
            raise RuntimeError(f"fail:{stage}")
        return value

    monkeypatch.setitem(
        globals_,
        "_diagnostic_governance_root_v19",
        lambda _arguments: {
            "boundary": None,
            "canonical_path": path,
            "expected_identity": None,
            "lease": None,
            "path": path,
        },
    )
    monkeypatch.setitem(
        globals_,
        "_install_diagnostic_native_vault_namespace_v19",
        lambda _root: fail_or(
            "native",
            ([], lambda: events.append("native.restore")),
        ),
    )
    locations = {
        name: path.parent / name
        for name in (
            "audit",
            "config",
            "control_plane",
            "memory",
            "phase11",
            "workspace",
        )
    }
    monkeypatch.setitem(
        globals_,
        "_install_diagnostic_path_namespace_v19",
        lambda _path, **_kwargs: fail_or(
            "paths",
            (locations, lambda: events.append("paths.restore")),
        ),
    )
    monkeypatch.setitem(
        globals_,
        "_diagnostic_governance_factory_v19",
        lambda _path: fail_or("governance", (lambda: object(), ())),
    )
    monkeypatch.setitem(
        globals_,
        "_diagnostic_authority_factory_v19",
        lambda _locations: fail_or("authority", (lambda: object(), object())),
    )
    monkeypatch.setitem(
        globals_,
        "_diagnostic_dayops_component_factory_v19",
        lambda _locations: fail_or("component", lambda *_args: ()),
    )
    monkeypatch.setitem(
        globals_,
        "_cleanup_diagnostic_native_vaults_v19",
        lambda _vaults: (),
    )
    monkeypatch.setitem(
        globals_,
        "_cleanup_diagnostic_governance_v19",
        lambda _path, _vaults, **_kwargs: events.append("root.cleanup") or (),
    )

    with pytest.raises(RuntimeError, match=f"fail:{failing_stage}"):
        with resource_context(("--preflight-only",)):
            pytest.fail("faulted resource context unexpectedly yielded")

    assert events[-1] == "root.cleanup"
    assert ("native.restore" in events) is (failing_stage != "native")
    assert ("paths.restore" in events) is (failing_stage not in {"native", "paths"})
    assert os.environ.get(workspace_flag) == previous


def test_diagnostic_path_namespace_keeps_control_plane_production_bytes_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.control_plane as control_plane
    import core.paths as paths

    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_control_plane_isolation",
    )
    production = tmp_path / "production"
    production.mkdir()
    production_db = production / "control_plane.sqlite3"
    production_db.write_bytes(b"production-sentinel")
    before = hashlib.sha256(production_db.read_bytes()).hexdigest()
    original_paths_binding = paths.private_control_plane_runtime_dir
    original_control_binding = control_plane.private_control_plane_runtime_dir
    monkeypatch.setattr(paths, "private_control_plane_runtime_dir", lambda: production)
    monkeypatch.setattr(
        control_plane,
        "private_control_plane_runtime_dir",
        paths.private_control_plane_runtime_dir,
    )
    governance_path = tmp_path / "owned" / "governance.sqlite3"
    governance_path.parent.mkdir()

    locations, restore = namespace["_install_diagnostic_path_namespace_v19"](
        governance_path
    )
    try:
        store = control_plane.ControlPlaneStore(enabled=True)
        assert store.path == locations["control_plane"] / "control_plane.sqlite3"
        store.initialize()
        store.close()
    finally:
        restore()

    assert hashlib.sha256(production_db.read_bytes()).hexdigest() == before
    assert paths.private_control_plane_runtime_dir() == production
    assert control_plane.private_control_plane_runtime_dir() == production
    monkeypatch.setattr(
        paths, "private_control_plane_runtime_dir", original_paths_binding
    )
    monkeypatch.setattr(
        control_plane,
        "private_control_plane_runtime_dir",
        original_control_binding,
    )


def test_scoped_diagnostic_vault_cleanup_skips_proven_fresh_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import native_vault

    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_fresh_vault_cleanup",
    )
    delete_calls: list[object] = []
    monkeypatch.setattr(
        native_vault.NativeSecretVault,
        "delete",
        lambda self: (
            delete_calls.append(self)
            or (_ for _ in ()).throw(
                native_vault.NativeVaultError("backend unavailable")
            )
        ),
    )
    vaults, restore = namespace["_install_diagnostic_native_vault_namespace_v19"](
        tmp_path
    )
    try:
        vault = native_vault.NativeSecretVault(
            native_vault.SecretReference("Onyx.Test", "fresh", "fresh test")
        )
        assert namespace["_cleanup_diagnostic_native_vaults_v19"](vaults) == ()
        assert vault._diagnostic_materialization_v19 == "fresh"
        assert delete_calls == []
    finally:
        restore()


def test_scoped_diagnostic_vault_cleanup_deletes_materialized_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import native_vault

    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_materialized_vault_cleanup",
    )
    delete_calls: list[object] = []
    monkeypatch.setattr(
        native_vault.NativeSecretVault,
        "set_bytes",
        lambda _self, _secret: None,
    )
    monkeypatch.setattr(
        native_vault.NativeSecretVault,
        "delete",
        lambda self: delete_calls.append(self) or True,
    )
    vaults, restore = namespace["_install_diagnostic_native_vault_namespace_v19"](
        tmp_path
    )
    try:
        vault = native_vault.NativeSecretVault(
            native_vault.SecretReference("Onyx.Test", "written", "written test")
        )
        vault.set_bytes(b"secret")
        assert namespace["_cleanup_diagnostic_native_vaults_v19"](vaults) == ()
        assert len(delete_calls) == 1
        assert vault._diagnostic_materialization_v19 == "absent"
    finally:
        restore()


def test_scoped_diagnostic_vault_cleanup_reports_backend_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import native_vault

    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(root / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_vault_backend_failure",
    )
    monkeypatch.setattr(
        native_vault.NativeSecretVault,
        "delete",
        lambda _self: (_ for _ in ()).throw(
            native_vault.NativeVaultError("permission denied")
        ),
    )
    vaults, restore = namespace["_install_diagnostic_native_vault_namespace_v19"](
        tmp_path
    )
    try:
        vault = native_vault.NativeSecretVault(
            native_vault.SecretReference("Onyx.Test", "unknown", "unknown test")
        )
        vault._diagnostic_materialization_v19 = "unknown"
        assert namespace["_cleanup_diagnostic_native_vaults_v19"](vaults) == (
            "diagnostic.scoped_vault.0:NativeVaultError",
        )
    finally:
        restore()


def test_stable_bootstrap_delegates_native_smoke_to_v19_launcher() -> None:
    root = Path(__file__).resolve().parents[1]
    stable = (root / "scripts" / "bootstrap_onyx.pyw").read_text(encoding="utf-8")
    versioned = (root / "scripts" / "bootstrap_onyx_live_v19.pyw").read_text(
        encoding="utf-8"
    )
    launcher = (root / "scripts" / "launch_onyx_live_v19.pyw").read_text(
        encoding="utf-8"
    )

    assert "run_native_startup_smoke_v1" not in stable
    assert NATIVE_STARTUP_SMOKE_ARGUMENT in versioned
    assert "_run_native_startup_diagnostic" in launcher
    assert "entering stable V19 launcher" in launcher
    assert "_BoundedNativeSmokeMutexV19" in launcher
