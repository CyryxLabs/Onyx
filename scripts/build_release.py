"""Build a native Onyx release on the current operating system.

PyInstaller bundles are platform-specific, so this script intentionally builds
only for the host OS. GitHub Actions runs it on Windows, macOS Intel/ARM and
Linux x64/ARM to produce the complete release set.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BUILD = ROOT / "build"
ASSETS = BUILD / "assets"
RUNTIME_DOCS = BUILD / "runtime-docs" / "onyx"
RUNTIME_SOURCES = BUILD / "runtime-sources"
BUNDLE_DIST = ROOT / "dist" / "bundle"
WORK = BUILD / "pyinstaller"
RUNTIME_VALIDATION_BUNDLE = BUILD / "runtime-validation-bundle"
CAPABILITIES_SMOKE_ARGUMENT = "--capabilities-smoke-v1"
PARITY_SMOKE_ARGUMENT = "--parity-smoke-v1"
PACKAGED_CAPABILITY_FAMILIES = (
    "argos",
    "budget",
    "command_center",
    "evidence",
    "google_workspace",
    "graph",
    "guild",
    "intelligence",
    "knowledge_refinery",
    "mission_context",
    "model_router",
    "nexus",
    "plugin",
    "project_execution",
    "social",
    "strategy",
    "workspace",
)
RELEASE = ROOT / "release"
BUILD_INPUT_SEAL = BUILD / "pyinstaller-first-party-inputs-v1.json"
BUILD_INPUT_SEAL_ARCHIVE = BUILD / "input-seals"
BUILD_INPUT_SEAL_CONTRACT = "OnyxPyInstallerFirstPartyInputs.v1"
ROLLBACK_RELEASES = ROOT / "rollback" / "releases"
WINDOWS_UNINSTALL_SETTLE_SECONDS = 30.0
WINDOWS_SETUP_SMOKE_TIMEOUT_SECONDS = 900.0
WINDOWS_PRODUCTION_APP_ID = "{{8F04E3B8-E681-4E10-9AC7-58EC1605CA4D}"
INNO_PACKAGED_ROOT = ROOT / "packaging" / "windows" / "inno"
INNO_DEFAULT_MESSAGES = INNO_PACKAGED_ROOT / "Default.isl"
INNO_LICENSE = INNO_PACKAGED_ROOT / "LICENSE.txt"
PORTABLE_CURRENT_ACTIVATION_ENV = "ONYX_PORTABLE_CURRENT_ACTIVATION_V1"
APPIMAGE_RUNTIME_SHA256 = {
    "x64": "1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf",
    "arm64": "7d5d772b7c32f0c84caf0a452a3072a5709027d7eac5856feb89a7a7a8881372",
}


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _resolve_packaged_supplemental_metadata(
    metadata_by_name: dict[str, list[Path]],
    *,
    name: str,
    version: str,
) -> Path | None:
    """Resolve one shipped distribution, while allowing platform absence."""

    matches = metadata_by_name.get(_canonical_distribution_name(name), [])
    if not matches:
        # The supplemental evidence set spans the cross-platform lock. Some
        # entries (WMI, PyGetWindow and win10toast) are intentionally absent
        # from non-Windows runtime bundles and therefore need no dist-info
        # notice in that artifact.
        return None
    exact = [
        path
        for path in matches
        if path.name.casefold().endswith(f"-{version}.dist-info".casefold())
    ]
    if len(exact) != 1:
        raise RuntimeError(
            f"packaged supplemental legal metadata is not unique: {name} {version}"
        )
    return exact[0]


def _matches_release_json_value(actual: object, expected: object) -> bool:
    """Compare release evidence without Python bool/int equality coercion."""

    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        actual_dict = actual
        expected_dict = expected
        return set(actual_dict) == set(expected_dict) and all(
            _matches_release_json_value(actual_dict[key], value)
            for key, value in expected_dict.items()
        )
    if type(expected) is list:
        actual_list = actual
        expected_list = expected
        return len(actual_list) == len(expected_list) and all(
            _matches_release_json_value(actual_item, expected_item)
            for actual_item, expected_item in zip(actual_list, expected_list)
        )
    return actual == expected


def validate_secure_backend_probe_requirement(
    *,
    require: bool,
    portable_current: bool,
    system: str,
) -> None:
    """Keep the official Linux probe requirement out of diagnostic gates."""

    if not require:
        return
    if system != "Linux":
        raise RuntimeError("secure-backend probe requirement is Linux-only")
    if not portable_current:
        raise RuntimeError(
            "secure-backend probe requirement needs the portable-current gate"
        )


def _create_private_smoke_data(path: Path) -> Path:
    """Create one disposable data root with the product's owner-only boundary.

    Windows temporary directories can inherit AppContainer capability ACEs from
    the process hosting the build. Frozen children do not necessarily carry
    those capabilities, and the Control Plane correctly refuses that inherited
    write/delete authority. Harden the disposable data root itself instead of
    weakening the production verifier or allowlisting an ambient SID.
    """

    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    from core.control_plane import _secure_private_directory

    _secure_private_directory(path)
    return path


def validate_formal_linux_release_contract(
    *,
    formal_release: bool,
    system: str,
    portable_current: bool,
    require_secure_backend_probe: bool,
    linux_signing_policy: str | None,
) -> None:
    """Reject incomplete formal Linux authority before any release mutation."""

    if not formal_release or system != "Linux":
        return
    if not portable_current:
        raise RuntimeError(
            "formal Linux release requires the portable-current negative-boundary gate"
        )
    if not require_secure_backend_probe:
        raise RuntimeError(
            "formal Linux release requires the trusted secure-backend probe gate"
        )
    if linux_signing_policy != "unsigned-approved":
        raise RuntimeError(
            "formal Linux release requires --linux-signing-policy unsigned-approved"
        )


PORTABLE_CURRENT_ACTIVATION_PROFILE = "portable-current-negative-boundary-default-off"
LINUX_DEB_RUNTIME_DEPENDENCIES = (
    "libasound2",
    "libportaudio2",
    "libpulse0",
    "libsecret-tools",
    "libnss3",
    "libx11-6",
    "libx11-xcb1",
    "libxtst6",
    "libxcb1",
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-keysyms1",
    "libxcb-shape0",
    "libxcb-xkb1",
    "libxkbcommon0",
    "libxkbcommon-x11-0",
    "libgl1",
    "libegl1",
    "libgtk-3-0",
    "libdbus-1-3",
)


def run(argv: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, cwd=ROOT, env=env, check=True)


def pyinstaller_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a build environment that cannot capture unrelated host DLLs.

    On Windows, PyInstaller resolves transitive PE dependencies through PATH.
    Desktop hosts (including the Codex workspace runtime) can prepend Poppler or
    other native tool directories that contain an unrelated ``icuuc.dll``.
    QtCore intentionally binds the Windows system ICU implementation, so
    capturing that unrelated DLL produces a frozen-only procedure-load failure.
    """

    env = dict(os.environ if base is None else base)
    if platform.system() != "Windows":
        return env
    python_root = Path(sys.executable).resolve().parent
    windows_root = Path(env.get("SystemRoot", r"C:\Windows")).resolve()
    safe_path = (
        python_root,
        python_root / "Scripts",
        windows_root / "System32",
        windows_root,
    )
    env["PATH"] = os.pathsep.join(str(path) for path in safe_path)
    return env


def assert_no_windows_qt_icu_collision(bundle: Path) -> None:
    """Fail closed if a foreign unversioned ICU shadows Windows ICU for Qt."""

    if platform.system() != "Windows":
        return
    internal = bundle / "_internal"
    forbidden = tuple(
        path
        for name in ("icuuc.dll", "icudt78.dll")
        if (path := internal / name).exists()
    )
    if forbidden:
        names = ", ".join(path.name for path in forbidden)
        raise RuntimeError(f"foreign Qt ICU collision entered Windows bundle: {names}")


def _is_link_like(path: Path) -> bool:
    """Return true for symlinks and Windows junction/reparse directories."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def _validate_destructive_directory(path: Path) -> Path:
    """Pin cleanup to a real directory lexically and physically below ROOT."""

    root = ROOT.absolute()
    candidate = path.absolute()
    if candidate == root or not candidate.is_relative_to(root):
        raise RuntimeError(f"Refusing to clean unsafe path: {candidate}")
    relative = candidate.relative_to(root)
    current = root
    for component in relative.parts:
        current = current / component
        if _is_link_like(current):
            raise RuntimeError(f"Refusing to clean linked/reparse path: {current}")
    resolved = candidate.resolve(strict=False)
    resolved_root = root.resolve(strict=True)
    if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
        raise RuntimeError(f"Refusing to clean unsafe path: {resolved}")
    if candidate.exists() and not candidate.is_dir():
        raise RuntimeError(f"Refusing to clean non-directory path: {candidate}")
    return candidate


def clean_path(path: Path) -> None:
    trusted = _validate_destructive_directory(path)
    if trusted.exists():
        shutil.rmtree(trusted)


def validate_release_version(version: str) -> str:
    """Require the requested release to match the runtime product version."""

    from core.version import __version__

    if type(version) is not str or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?",
        version,
    ):
        raise RuntimeError("release version must be a canonical semantic version")
    if version != __version__:
        raise RuntimeError(
            "release version mismatch: "
            f"requested {version!r}, core.version declares {__version__!r}"
        )
    return version


def _canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _release_archive_snapshot(release_dir: Path) -> dict[str, object] | None:
    """Describe every existing release file before the build clears the directory."""

    if not release_dir.exists():
        return None
    if not release_dir.is_dir() or release_dir.is_symlink():
        raise RuntimeError(f"release path is not a trusted directory: {release_dir}")
    entries = tuple(
        sorted(release_dir.iterdir(), key=lambda item: item.name.casefold())
    )
    if not entries:
        return None
    if any(not item.is_file() or item.is_symlink() for item in entries):
        raise RuntimeError("release archive accepts direct regular files only")
    manifests = [
        item
        for item in entries
        if item.name.startswith("release-manifest-") and item.suffix == ".json"
    ]
    if len(manifests) != 1:
        raise RuntimeError("existing release requires exactly one platform manifest")
    try:
        release_manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("existing release manifest is invalid") from exc
    if type(release_manifest) is not dict or release_manifest.get("product") != "Onyx":
        raise RuntimeError("existing release manifest does not identify Onyx")
    version = release_manifest.get("version")
    if type(version) is not str or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise RuntimeError("existing release version is unavailable")
    records = [
        {
            "name": item.name,
            "size": item.stat().st_size,
            "sha256": hash_file(item),
        }
        for item in entries
    ]
    aggregate = hashlib.sha256()
    for record in records:
        aggregate.update(str(record["name"]).encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(record["size"]).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(str(record["sha256"]).encode("ascii"))
        aggregate.update(b"\n")
    root_sha256 = aggregate.hexdigest()
    activation = release_manifest.get("activation_contract")
    legacy_v19_1 = (
        version == "1.0.0"
        and type(activation) is dict
        and activation.get("normal_activation") == "v19"
    )
    archive_name = (
        "onyx-1.0.0-v19.1" if legacy_v19_1 else f"onyx-{version}-{root_sha256[:16]}"
    )
    return {
        "schema": "onyx.release-rollback-archive.v1",
        "product": "Onyx",
        "version": version,
        "archive_name": archive_name,
        "file_count": len(records),
        "root_sha256": root_sha256,
        "files": records,
    }


def _verify_release_archive(destination: Path, snapshot: dict[str, object]) -> None:
    manifest_path = destination / "archive-manifest.json"
    if (
        not destination.is_dir()
        or destination.is_symlink()
        or not manifest_path.is_file()
    ):
        raise RuntimeError(f"release rollback archive is incomplete: {destination}")
    try:
        observed = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("release rollback archive manifest is invalid") from exc
    if observed != snapshot:
        raise RuntimeError("release rollback archive differs from existing release")
    records = snapshot.get("files")
    if type(records) is not list:
        raise RuntimeError("release rollback archive records are invalid")
    expected_names = {"archive-manifest.json"}
    for record in records:
        if type(record) is not dict or type(record.get("name")) is not str:
            raise RuntimeError("release rollback archive record is invalid")
        expected_names.add(record["name"])
        candidate = destination / record["name"]
        if (
            not candidate.is_file()
            or candidate.is_symlink()
            or candidate.stat().st_size != record.get("size")
            or hash_file(candidate) != record.get("sha256")
        ):
            raise RuntimeError(f"release rollback archive file drifted: {candidate}")
    if {item.name for item in destination.iterdir()} != expected_names:
        raise RuntimeError("release rollback archive contains unexpected files")


def archive_existing_release(
    release_dir: Path = RELEASE,
    archive_root: Path = ROLLBACK_RELEASES,
) -> Path | None:
    """Copy and verify the prior release before destructive build cleanup."""

    snapshot = _release_archive_snapshot(release_dir)
    if snapshot is None:
        return None
    archive_root.mkdir(parents=True, exist_ok=True)
    destination = archive_root / str(snapshot["archive_name"])
    if destination.exists():
        _verify_release_archive(destination, snapshot)
        return destination
    temporary = archive_root / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        records = snapshot["files"]
        assert type(records) is list
        for record in records:
            assert type(record) is dict
            source = release_dir / str(record["name"])
            target = temporary / str(record["name"])
            shutil.copy2(source, target)
            if (
                target.stat().st_size != record["size"]
                or hash_file(target) != record["sha256"]
            ):
                raise RuntimeError(
                    f"release rollback copy verification failed: {source}"
                )
        (temporary / "archive-manifest.json").write_bytes(
            _canonical_json_bytes(snapshot)
        )
        _verify_release_archive(temporary, snapshot)
        try:
            temporary.rename(destination)
        except FileExistsError:
            _verify_release_archive(destination, snapshot)
            shutil.rmtree(temporary)
        _verify_release_archive(destination, snapshot)
        return destination
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def architecture() -> str:
    machine = platform.machine().lower()
    return {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine, machine.replace(" ", "-") or "unknown")


def generate_assets(version: str) -> None:
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_icons.py"),
            "--output",
            str(ASSETS),
            "--version",
            version,
        ]
    )


def generate_runtime_docs() -> None:
    """Stage only files referenced by runtime integrity/capability gates."""
    from scripts.package_hygiene import assert_package_hygiene, stage_runtime_docs

    clean_path(RUNTIME_DOCS.parent)
    selected = stage_runtime_docs(ROOT, RUNTIME_DOCS)
    assert_package_hygiene(RUNTIME_DOCS.parent)
    print(f"Staged {len(selected)} runtime documentation file(s)", flush=True)


def generate_runtime_sources() -> None:
    """Stage first-party source bytes without caches or development scripts."""
    from core.onyx_hud_current_acceptance_v48 import (
        verify_current_hud_acceptance,
    )
    from core.onyx_packaged_runtime_hud_contract_v17 import (
        verify_packaged_runtime_hud_contract,
    )
    from scripts.package_hygiene import assert_package_hygiene, stage_runtime_sources
    from scripts.verify_staged_capabilities_v1 import verify as verify_staged_capabilities

    verify_current_hud_acceptance(ROOT)
    clean_path(RUNTIME_SOURCES)
    stage_runtime_sources(ROOT, RUNTIME_SOURCES)
    verify_packaged_runtime_hud_contract(RUNTIME_SOURCES)
    verify_staged_capabilities(RUNTIME_SOURCES, project=ROOT)
    assert_package_hygiene(RUNTIME_SOURCES)


def _first_party_build_input_files() -> tuple[Path, ...]:
    """Return every first-party file consumed by PyInstaller/spec analysis."""

    from scripts.package_hygiene import (
        COMPATIBILITY_LAUNCHER_RELATIVE,
        COMPATIBILITY_NOTICE_RELATIVE,
        RUNTIME_TEST_EVIDENCE_FILES,
        assert_safe_build_input_paths,
        discover_runtime_docs,
    )

    selected: set[Path] = set()

    def add_file(path: Path) -> None:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"PyInstaller build input is unavailable: {path}")
        selected.add(path.resolve())

    def add_tree(path: Path, *, suffixes: set[str] | None = None) -> None:
        if not path.is_dir() or path.is_symlink():
            raise RuntimeError(f"PyInstaller build input tree is unavailable: {path}")
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            folded = tuple(
                part.casefold() for part in candidate.relative_to(path).parts
            )
            if any(
                part == "__pycache__" or part.startswith((".pytest", ".tmp", ".review"))
                for part in folded
            ):
                continue
            if suffixes is None or candidate.suffix.casefold() in suffixes:
                selected.add(candidate.resolve())

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
        "dashboard/static/crypto-js.LICENSE.txt",
        "dashboard/static/crypto-js.PROVENANCE.json",
        ("docs/onyx/checkpoints/phase7-workspace-memory-v1/manifest.json"),
        "docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.md",
        ("docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.manifest.json"),
        "docs/onyx/VE-ACCEPTANCE-P7-WORKSPACE-MEMORY-V1-E6-001.sha256",
    ):
        add_file(ROOT / relative)
    for relative in RUNTIME_TEST_EVIDENCE_FILES:
        add_file(ROOT / relative)
    for relative in discover_runtime_docs(ROOT):
        add_file(ROOT / relative)
    for relative in ("core", "actions", "config", "memory", "scripts"):
        add_tree(ROOT / relative, suffixes={".py", ".pyw"})
    for relative in ("dashboard", "qml"):
        add_tree(ROOT / relative)
    for staged in (RUNTIME_SOURCES, RUNTIME_DOCS, ASSETS):
        add_tree(staged)
    ordered = tuple(sorted(selected, key=lambda item: item.as_posix().casefold()))
    assert_safe_build_input_paths(ordered, ROOT)
    for item in ordered:
        relative = item.relative_to(ROOT.resolve())
        folded = tuple(part.casefold() for part in relative.parts)
        if folded[0] in {"runtime", "rollback"} or any(
            part == "__pycache__" or part.startswith((".pytest", ".tmp", ".review"))
            for part in folded
        ):
            raise RuntimeError(
                f"development/runtime path entered build-input seal: {relative}"
            )
    return ordered


def _snapshot_build_input_files(
    files: tuple[Path, ...],
    *,
    root: Path,
) -> dict[str, object]:
    """Hash stable reads and bind exact membership into one root digest."""

    root = root.resolve()
    records: list[dict[str, object]] = []
    aggregate = hashlib.sha256()
    for source in files:
        resolved = source.resolve()
        if (
            not resolved.is_relative_to(root)
            or not resolved.is_file()
            or source.is_symlink()
        ):
            raise RuntimeError(f"unsafe PyInstaller build input: {source}")
        before = resolved.stat()
        raw = resolved.read_bytes()
        after = resolved.stat()
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(raw) != after.st_size
        ):
            raise RuntimeError(f"PyInstaller build input changed while read: {source}")
        relative = resolved.relative_to(root).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(len(raw)).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
        records.append({"path": relative, "size": len(raw), "sha256": digest})
    return {
        "contract": BUILD_INPUT_SEAL_CONTRACT,
        "file_count": len(records),
        "files": records,
        "root_sha256": aggregate.hexdigest(),
    }


def _verify_build_input_snapshot(
    expected: dict[str, object],
    files: tuple[Path, ...],
    *,
    root: Path,
) -> None:
    observed = _snapshot_build_input_files(files, root=root)
    if observed != expected:
        raise RuntimeError("PyInstaller first-party build inputs changed after sealing")


def seal_pyinstaller_build_inputs() -> dict[str, object]:
    files = _first_party_build_input_files()
    snapshot = _snapshot_build_input_files(files, root=ROOT)
    encoded = _canonical_json_bytes(snapshot)
    temporary = BUILD_INPUT_SEAL.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    temporary.replace(BUILD_INPUT_SEAL)
    BUILD_INPUT_SEAL_ARCHIVE.mkdir(parents=True, exist_ok=True)
    content_path = BUILD_INPUT_SEAL_ARCHIVE / f"{snapshot['root_sha256']}.json"
    if content_path.exists():
        if content_path.is_symlink() or content_path.read_bytes() != encoded:
            raise RuntimeError("content-addressed build-input seal collision")
    else:
        content_temporary = content_path.with_suffix(".json.tmp")
        content_temporary.write_bytes(encoded)
        content_temporary.replace(content_path)
    _verify_build_input_snapshot(snapshot, _first_party_build_input_files(), root=ROOT)
    return snapshot


def verify_sealed_pyinstaller_build_inputs(snapshot: dict[str, object]) -> None:
    _verify_build_input_snapshot(
        snapshot,
        _first_party_build_input_files(),
        root=ROOT,
    )


def load_verified_build_input_seal() -> tuple[dict[str, object], Path]:
    """Load the exact post-staging build-input seal and reverify current bytes."""

    try:
        snapshot = json.loads(BUILD_INPUT_SEAL.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("PyInstaller build-input seal is unavailable") from exc
    if (
        type(snapshot) is not dict
        or snapshot.get("contract") != BUILD_INPUT_SEAL_CONTRACT
        or type(snapshot.get("root_sha256")) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", str(snapshot["root_sha256"]))
        or type(snapshot.get("files")) is not list
        or snapshot.get("file_count") != len(snapshot["files"])
    ):
        raise RuntimeError("PyInstaller build-input seal contract is invalid")
    content_path = BUILD_INPUT_SEAL_ARCHIVE / f"{snapshot['root_sha256']}.json"
    if (
        not content_path.is_file()
        or content_path.is_symlink()
        or content_path.read_bytes() != BUILD_INPUT_SEAL.read_bytes()
    ):
        raise RuntimeError(
            "content-addressed PyInstaller build-input seal is unavailable"
        )
    verify_sealed_pyinstaller_build_inputs(snapshot)
    return snapshot, content_path


def install_browser(env: dict[str, str], skip: bool) -> None:
    if skip:
        return
    # Onyx uses the full Chromium build for visible automation and for the
    # readiness probe. Shipping the separate legacy headless-shell binary
    # duplicates roughly 270 MiB without adding a capability.
    run(
        [
            sys.executable,
            "-m",
            "playwright",
            "install",
            "--no-shell",
            "chromium",
        ],
        env=env,
    )


def build_bundle(version: str, *, skip_browser: bool) -> Path:
    from scripts.verify_release_workflow_v101 import verify_release_workflow_v101

    # Authenticate current source before mutable build work. Staged capability
    # validation independently rechecks V101 before admitting the staged slice.
    verify_release_workflow_v101(ROOT)
    clean_path(BUNDLE_DIST)
    clean_path(WORK)
    BUNDLE_DIST.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    generate_assets(version)
    generate_runtime_docs()
    generate_runtime_sources()

    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = "0"
    env["ONYX_BUILD_VERSION"] = version
    install_browser(env, skip_browser)
    pyinstaller_env = pyinstaller_environment(env)
    sealed_inputs = seal_pyinstaller_build_inputs()
    try:
        run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(BUNDLE_DIST),
                "--workpath",
                str(WORK),
                str(ROOT / "packaging" / "onyx.spec"),
            ],
            env=pyinstaller_env,
        )
    finally:
        # A successful PyInstaller exit is not accepted if any first-party
        # entrypoint, import root, or packaged resource moved during analysis.
        verify_sealed_pyinstaller_build_inputs(sealed_inputs)

    system = platform.system()
    if system == "Darwin":
        result = BUNDLE_DIST / "Onyx.app"
    else:
        result = BUNDLE_DIST / "Onyx"
    if not result.exists():
        raise RuntimeError(f"PyInstaller output is missing: {result}")
    assert_no_windows_qt_icu_collision(result)
    legal_root = result / "THIRD_PARTY_LICENSES"
    legal_root.mkdir()
    shutil.copy2(ROOT / "LICENSE", result / "LICENSE.txt")
    shutil.copy2(
        ROOT / "THIRD_PARTY_NOTICES.md",
        result / "THIRD_PARTY_NOTICES.md",
    )
    shutil.copy2(
        ROOT / "packaging" / "licenses" / "LGPL-3.0.txt",
        legal_root / "LGPL-3.0.txt",
    )
    from scripts.missing_distribution_license_bundle import (
        generate_missing_distribution_license_bundle,
    )

    supplemental_legal = legal_root / "missing-distribution-evidence-v1"
    supplemental_report = generate_missing_distribution_license_bundle(
        supplemental_legal
    )
    supplemental_packages = supplemental_report.get("packages")
    if type(supplemental_packages) is not list or len(supplemental_packages) != 4:
        raise RuntimeError("supplemental distribution legal evidence is incomplete")

    metadata_by_name: dict[str, list[Path]] = {}
    for metadata_dir in result.rglob("*.dist-info"):
        match = re.fullmatch(
            r"(?P<name>.+?)-(?P<version>[0-9].*)\.dist-info", metadata_dir.name
        )
        if match is not None:
            metadata_by_name.setdefault(
                _canonical_distribution_name(match.group("name")), []
            ).append(metadata_dir)
    for package in supplemental_packages:
        name = str(package["name"])
        version = str(package["version"])
        metadata_dir = _resolve_packaged_supplemental_metadata(
            metadata_by_name,
            name=name,
            version=version,
        )
        if metadata_dir is None:
            continue
        (metadata_dir / "NOTICE-ONYX-SUPPLEMENTAL-LEGAL-EVIDENCE.txt").write_text(
            "The exact shipped distribution omitted a canonical license file.\n"
            "Onyx packages hash-bound primary-source evidence at "
            "../../THIRD_PARTY_LICENSES/missing-distribution-evidence-v1/"
            f"{name}-{version}/ and records the unresolved decision as:\n"
            f"{package['decision']}\n"
            "This technical evidence is not a legal approval.\n",
            encoding="utf-8",
        )
    from scripts.primp_license_bundle import (
        PRIMP_VERSION,
        generate_primp_license_bundle,
    )

    primp_legal = legal_root / f"primp-{PRIMP_VERSION}-native-crates"
    primp_report = generate_primp_license_bundle(
        output_dir=primp_legal,
        system=system,
        architecture=architecture(),
    )
    primp_metadata = tuple(result.rglob(f"primp-{PRIMP_VERSION}.dist-info"))
    if len(primp_metadata) != 1 or not primp_metadata[0].is_dir():
        raise RuntimeError("packaged primp distribution metadata is not unique")
    (primp_metadata[0] / "NOTICE-ONYX-NATIVE-CRATES.txt").write_text(
        "Onyx packages the native Rust dependency license inventory for "
        f"primp {PRIMP_VERSION} at ../../THIRD_PARTY_LICENSES/"
        f"{primp_legal.name}/inventory.json.\n"
        f"Cargo target: {primp_report['target']}\n"
        f"Legal-file root SHA-256: {primp_report['legalFileRootSha256']}\n",
        encoding="utf-8",
    )
    from scripts.package_hygiene import (
        assert_embedded_chromium_runtime,
        assert_package_hygiene,
        prune_duplicate_browser_payloads,
    )

    removed = prune_duplicate_browser_payloads(result)
    if removed:
        print(
            f"Removed {len(removed)} duplicate browser payload tree(s)",
            flush=True,
        )
    assert_embedded_chromium_runtime(result)
    assert_package_hygiene(result)
    return result


def smoke_test(bundle: Path) -> None:
    system = platform.system()
    executable = (
        bundle / "Contents" / "MacOS" / "Onyx"
        if system == "Darwin"
        else bundle / ("Onyx.exe" if system == "Windows" else "Onyx")
    )
    smoke_data = BUILD / "smoke-data"
    clean_path(smoke_data)
    env = os.environ.copy()
    env["ONYX_DATA_DIR"] = str(smoke_data)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop(PORTABLE_CURRENT_ACTIVATION_ENV, None)
    print(f"Smoke testing {executable}", flush=True)
    subprocess.run(
        [str(executable), "--package-smoke-test"],
        cwd=ROOT,
        env=env,
        check=True,
        timeout=90,
    )
    clean_path(smoke_data)


def clone_runtime_validation_bundle(bundle: Path) -> Path:
    """Clone one immutable production payload for all mutating runtime smokes."""

    if (
        not bundle.is_dir()
        or _is_link_like(bundle)
        or not bundle.resolve().is_relative_to(ROOT.resolve())
    ):
        raise RuntimeError("runtime-validation source bundle is unavailable or unsafe")
    clean_path(RUNTIME_VALIDATION_BUNDLE)
    RUNTIME_VALIDATION_BUNDLE.mkdir(parents=True)
    destination = RUNTIME_VALIDATION_BUNDLE / bundle.name
    shutil.copytree(bundle, destination, symlinks=True)
    return destination


def package_preflight_test(bundle: Path) -> None:
    """Traverse the packaged activation chain in fallback and stable V24 modes."""

    from core.onyx_live_activation_v24 import (
        CONTROL_FLAGS,
        exact_activation_environment,
    )

    system = platform.system()
    executable = (
        bundle / "Contents" / "MacOS" / "Onyx"
        if system == "Darwin"
        else bundle / ("Onyx.exe" if system == "Windows" else "Onyx")
    )
    # Phase 11 requires a Windows directory whose ACL grants delete-child
    # authority. A source checkout may live on a restricted-volume root, so
    # exercise the packaged writable-data boundary in the user's native temp
    # location instead of under BUILD.
    with tempfile.TemporaryDirectory(prefix="onyx-package-preflight-") as temporary:
        preflight_root = Path(temporary)
        preflight_data = preflight_root / "data"
        workspace = preflight_root / "workspace"
        _create_private_smoke_data(preflight_data)
        workspace.mkdir()

        common = os.environ.copy()
        common.pop(PORTABLE_CURRENT_ACTIVATION_ENV, None)
        if system in {"Darwin", "Linux"}:
            # A frozen POSIX executable selects portable-current when this
            # flag is absent.  This first preflight is intentionally the
            # diagnostic predecessor traversal; select that contract with the
            # documented explicit override instead of accidentally entering
            # the secure-backend path inside a child-process-denied smoke.
            common[PORTABLE_CURRENT_ACTIVATION_ENV] = "0"
        common["ONYX_DATA_DIR"] = str(preflight_data)
        common["QT_QPA_PLATFORM"] = "offscreen"
        for name in CONTROL_FLAGS:
            common.pop(name, None)

        print("Packaged fallback preflight", flush=True)
        subprocess.run(
            [str(executable), "--preflight-only"],
            cwd=ROOT,
            env=common,
            check=True,
            timeout=120,
        )

        if system == "Windows":
            active = dict(common)
            active.update(exact_activation_environment((workspace,)))
            print("Packaged V24 preflight", flush=True)
            result = subprocess.run(
                [str(executable), "--preflight-only"],
                cwd=ROOT,
                env=active,
                check=False,
                timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"packaged V24 preflight failed with exit {result.returncode}"
                )


def package_capabilities_smoke_test(bundle: Path) -> dict[str, object]:
    """Exercise the frozen capability host outside the checkout, provider-free."""

    system = platform.system()
    executable = (
        bundle / "Contents" / "MacOS" / "Onyx"
        if system == "Darwin"
        else bundle / ("Onyx.exe" if system == "Windows" else "Onyx")
    )
    if not executable.is_file() or _is_link_like(executable):
        raise RuntimeError("packaged capability smoke executable is unavailable")
    with tempfile.TemporaryDirectory(prefix="onyx-capabilities-smoke-") as temporary:
        smoke_root = Path(temporary)
        data = smoke_root / "data"
        cwd = smoke_root / "cwd"
        _create_private_smoke_data(data)
        cwd.mkdir()
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "WINDIR": os.environ.get("WINDIR", ""),
            "TEMP": str(smoke_root),
            "TMP": str(smoke_root),
            "ONYX_DATA_DIR": str(data),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "QT_QPA_PLATFORM": "offscreen",
        }
        result = subprocess.run(
            [str(executable), CAPABILITIES_SMOKE_ARGUMENT],
            cwd=cwd,
            env=environment,
            check=False,
            timeout=120,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "packaged capability smoke failed with exit "
                f"{result.returncode}: {result.stderr[-2_000:]}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "packaged capability smoke emitted invalid JSON"
            ) from exc
        if (
            payload.get("schema") != "OnyxCapabilitiesCLI.v1"
            or payload.get("command") != "safe-test"
            or payload.get("ok") is not True
            or payload.get("result", {}).get("provider_dispatch") is not False
            or payload.get("result", {}).get("families")
            != list(PACKAGED_CAPABILITY_FAMILIES)
            or payload.get("result", {}).get("families_denied")
            != list(PACKAGED_CAPABILITY_FAMILIES)
            or payload.get("result", {}).get("local_operational", {}).get("families")
            != ["clipboard", "personalization", "plugin", "social", "wellness"]
            or payload.get("result", {}).get("local_operational", {}).get("publishing")
            != "oauth-adapter-required"
            or len(
                payload.get("result", {}).get("local_operational", {}).get(
                    "receipts", ()
                )
            )
            != 9
            or any(
                receipt.get("decision") != "allow"
                or receipt.get("outcome") != "dispatched"
                for receipt in payload.get("result", {})
                .get("local_operational", {})
                .get("receipts", ())
            )
        ):
            raise RuntimeError("packaged capability smoke contract drifted")
        checkout = os.path.normcase(str(ROOT.resolve()))
        origins = payload.get("result", {}).get("module_origins")
        if type(origins) is not dict or not origins:
            raise RuntimeError("packaged capability smoke omitted module origins")
        if any(
            checkout in os.path.normcase(str(origin)) for origin in origins.values()
        ):
            raise RuntimeError("packaged capability smoke imported checkout source")
        return payload


def package_parity_smoke_test(bundle: Path) -> dict[str, object]:
    """Prove the frozen executable contains the closed parity contract."""

    system = platform.system()
    executable = (
        bundle / "Contents" / "MacOS" / "Onyx"
        if system == "Darwin"
        else bundle / ("Onyx.exe" if system == "Windows" else "Onyx")
    )
    if not executable.is_file() or _is_link_like(executable):
        raise RuntimeError("packaged parity smoke executable is unavailable")
    with tempfile.TemporaryDirectory(prefix="onyx-parity-smoke-") as temporary:
        smoke_root = Path(temporary)
        data = smoke_root / "data"
        cwd = smoke_root / "cwd"
        _create_private_smoke_data(data)
        cwd.mkdir()
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "WINDIR": os.environ.get("WINDIR", ""),
            "TEMP": str(smoke_root),
            "TMP": str(smoke_root),
            "ONYX_DATA_DIR": str(data),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "QT_QPA_PLATFORM": "offscreen",
        }
        result = subprocess.run(
            [str(executable), PARITY_SMOKE_ARGUMENT],
            cwd=cwd,
            env=environment,
            check=False,
            timeout=120,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "packaged parity smoke failed with exit "
                f"{result.returncode}: {result.stderr[-2_000:]}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("packaged parity smoke emitted invalid JSON") from exc
        if (
            payload.get("schema") != "onyx.capability-parity/v1"
            or payload.get("source_contract_coverage_percent") != 100.0
            or payload.get("capability_count") != 42
            or payload.get("package_verified") is not True
            or payload.get("installed_verified") is not False
            or payload.get("live_provider_verified") is not False
        ):
            raise RuntimeError("packaged parity smoke contract drifted")
        origins = payload.get("module_origins")
        if type(origins) is not dict or not origins:
            raise RuntimeError("packaged parity smoke omitted module origins")
        if any(Path(str(origin)).is_absolute() for origin in origins.values()):
            raise RuntimeError("packaged parity smoke exposed an absolute module origin")
        return payload


def _package_native_startup_executable_smoke_test(
    executable: Path,
    *,
    system: str,
    portable_current: bool,
    require_secure_backend_probe: bool = False,
    extra_environment: dict[str, str] | None = None,
) -> dict[str, object]:
    """Run and validate the native-startup contract from one executable."""

    validate_secure_backend_probe_requirement(
        require=require_secure_backend_probe,
        portable_current=portable_current,
        system=system,
    )

    from core.native_startup_smoke_v1 import (
        NATIVE_STARTUP_SMOKE_ARGUMENT,
        NATIVE_STARTUP_SMOKE_CONTRACT,
        NATIVE_STARTUP_SMOKE_OUTPUT_ENV,
        PORTABLE_CURRENT_NEGATIVE_BOUNDARY_GATE,
        POSIX_OWNER_BACKEND_PROBE_MAX_CALLS,
        POSIX_OWNER_BACKEND_PROBE_SURFACE,
        TERMINAL_FENCE_EVIDENCE_KEY,
    )

    if not executable.is_file():
        raise RuntimeError(f"native startup entrypoint is missing: {executable}")
    with tempfile.TemporaryDirectory(prefix="onyx-native-startup-smoke-") as temporary:
        root = Path(temporary)
        data = root / "data"
        workspace = root / "workspace"
        output = root / "native-startup-smoke-v1.json"
        _create_private_smoke_data(data)
        workspace.mkdir()
        environment = os.environ.copy()
        environment["ONYX_DATA_DIR"] = str(data)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["QSG_RHI_BACKEND"] = "software"
        environment[NATIVE_STARTUP_SMOKE_OUTPUT_ENV] = str(output)
        environment.update(extra_environment or {})
        # Release evidence must be deterministic.  Ambient user/CI activation
        # settings may otherwise select an older Windows launcher (or a newer
        # POSIX candidate) while the gate reports the current packaged entrypoint.
        from core.onyx_live_activation_v24 import (
            CONTROL_FLAGS as V24_CONTROL_FLAGS,
            exact_activation_environment as exact_v24_environment,
        )

        for name in V24_CONTROL_FLAGS:
            environment.pop(name, None)
        environment.pop(PORTABLE_CURRENT_ACTIVATION_ENV, None)
        if portable_current:
            environment[PORTABLE_CURRENT_ACTIVATION_ENV] = "1"
        elif system in {"Darwin", "Linux"}:
            # Frozen POSIX defaults to portable-current.  The baseline smoke
            # must explicitly select the capability-limited predecessor so
            # its reported activation profile matches the exercised path.
            environment[PORTABLE_CURRENT_ACTIVATION_ENV] = "0"
        elif system == "Windows":
            environment.update(exact_v24_environment((workspace,)))
        profile = "portable-current candidate" if portable_current else "baseline"
        print(f"Packaged native startup smoke ({system}, {profile})", flush=True)
        result = subprocess.run(
            [str(executable), NATIVE_STARTUP_SMOKE_ARGUMENT],
            cwd=ROOT,
            env=environment,
            check=False,
            timeout=240,
            capture_output=True,
            text=True,
        )
        failure = output.read_text(encoding="utf-8") if output.is_file() else ""
        if result.returncode != 0:
            raise RuntimeError(
                "packaged native startup smoke failed with exit "
                f"{result.returncode}: {failure} {result.stderr[-2_000:]}"
            )
        try:
            payload = json.loads(failure)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(
                "packaged native startup smoke produced no valid JSON contract"
            ) from exc
        from core.native_activation_contract_v1 import (
            activation_contract_for_system_v1,
        )

        activation_contract = activation_contract_for_system_v1(
            system,
            portable_current=portable_current,
        )
        required = {
            "activation": activation_contract["smoke_activation"],
            "activation_contract": activation_contract,
            "activation_profile": activation_contract["activation_profile"],
            "callbacks_bound": not portable_current,
            "capability_limited": activation_contract["capability_limited"],
            "contract": NATIVE_STARTUP_SMOKE_CONTRACT,
            "host_constructed": not portable_current,
            "network_calls": 0,
            "process_calls": 0,
            "provider_calls": 0,
            "real_ui": not portable_current,
            "status": "passed_limited" if portable_current else "passed",
            "system": system,
            TERMINAL_FENCE_EVIDENCE_KEY: True,
            "window_visible": not portable_current,
        }
        if any(
            not _matches_release_json_value(payload.get(key), value)
            for key, value in required.items()
        ):
            raise RuntimeError("packaged native startup smoke result is invalid")
        if portable_current:
            portable_evidence = {
                "activation_profile": PORTABLE_CURRENT_ACTIVATION_PROFILE,
                "capability_limited": True,
                "declared_activation": "v19",
                "highest_proven_activation": "v16_descriptor_ledger",
                "boundary_reached": "pre_v10",
                "limitation_reason": (
                    "portable_current_v4_owner_authority_unavailable"
                ),
                "next_unimplemented_activation": "v4_portable_owner_authority",
                "native_evidence_required": True,
                "evidence_scope": PORTABLE_CURRENT_NEGATIVE_BOUNDARY_GATE,
                "safe_unavailability": True,
                "ui_renderer": "not_started_fail_closed",
                "v15_v19_parity": False,
            }
            if (
                any(
                    not _matches_release_json_value(payload.get(key), value)
                    for key, value in portable_evidence.items()
                )
                or activation_contract.get("v15_v19_parity") is not False
                or activation_contract.get("native_evidence_required") is not True
            ):
                raise RuntimeError(
                    "packaged portable-current native evidence is invalid"
                )
        interception = payload.get("interception")
        if (
            type(interception) is not dict
            or interception.get("scope") != "best_effort_python_runtime"
            or not interception.get("network_surfaces")
            or not interception.get("process_surfaces")
            or not interception.get("provider_surfaces")
        ):
            raise RuntimeError(
                "packaged native startup interception evidence is invalid"
            )
        network_surfaces = set(interception["network_surfaces"])
        if not {
            "network:socket.getaddrinfo",
            "network:socket.socket.send",
            "network:socket.socket.sendall",
            "network:socket.socket.sendto",
        }.issubset(network_surfaces):
            raise RuntimeError(
                "packaged native startup socket-send/DNS fence is incomplete"
            )
        secure_probe_calls = payload.get("secure_backend_probe_calls")
        evidence_probe_calls = interception.get("secure_backend_probe_calls")
        evidence_probe_surfaces = interception.get("secure_backend_probe_surfaces")
        probe_enabled = portable_current and system == "Linux"
        if (
            type(secure_probe_calls) is not int
            or type(evidence_probe_calls) is not int
            or secure_probe_calls < 0
            or secure_probe_calls > POSIX_OWNER_BACKEND_PROBE_MAX_CALLS
            or evidence_probe_calls != secure_probe_calls
            or evidence_probe_surfaces
            != ([POSIX_OWNER_BACKEND_PROBE_SURFACE] if secure_probe_calls else [])
            or (not probe_enabled and secure_probe_calls != 0)
            or (require_secure_backend_probe and secure_probe_calls < 1)
        ):
            raise RuntimeError(
                "packaged native startup secure-backend probe evidence is invalid"
            )
        allowed_renderers = (
            {"not_started_fail_closed"}
            if portable_current
            else {"cinematic-v5", "safe-software-fallback"}
        )
        if payload.get("ui_renderer") not in allowed_renderers:
            raise RuntimeError("packaged native startup renderer result is invalid")
        if system == "Windows":
            v24_launcher_log = data / "runtime" / "logs" / "onyx-live-v24-startup.log"
            v24_launcher_evidence = (
                v24_launcher_log.read_text(encoding="utf-8")
                if v24_launcher_log.is_file()
                else ""
            )
            v23_launcher_log = data / "runtime" / "logs" / "onyx-live-v23-startup.log"
            v23_launcher_evidence = (
                v23_launcher_log.read_text(encoding="utf-8")
                if v23_launcher_log.is_file()
                else ""
            )
            v22_launcher_log = data / "runtime" / "logs" / "onyx-live-v22-startup.log"
            v22_launcher_evidence = (
                v22_launcher_log.read_text(encoding="utf-8")
                if v22_launcher_log.is_file()
                else ""
            )
            launcher_log = data / "runtime" / "logs" / "onyx-live-v21-startup.log"
            launcher_evidence = (
                launcher_log.read_text(encoding="utf-8")
                if launcher_log.is_file()
                else ""
            )
            predecessor_log = data / "runtime" / "logs" / "onyx-live-v20-startup.log"
            predecessor_evidence = (
                predecessor_log.read_text(encoding="utf-8")
                if predecessor_log.is_file()
                else ""
            )
            terminal_log = data / "runtime" / "logs" / "onyx-live-v19-startup.log"
            terminal_evidence = (
                terminal_log.read_text(encoding="utf-8")
                if terminal_log.is_file()
                else ""
            )
            # The provider/process fence deliberately remains installed until
            # the frozen process exits.  V20 owns that terminal exit, so the
            # The wrappers cannot append post-return markers. Prove the exact
            # chain with each entry marker plus the terminal V19 success line;
            # the JSON contract above independently proves the current host result.
            if (
                "entering stable V24 launcher" not in v24_launcher_evidence
                or "entering stable V23 launcher" not in v23_launcher_evidence
                or "entering stable V22 launcher" not in v22_launcher_evidence
                or "entering stable V21 launcher" not in launcher_evidence
                or "entering stable V20 launcher" not in predecessor_evidence
                or "Onyx native startup smoke passed" not in terminal_evidence
            ):
                raise RuntimeError(
                    "packaged native startup did not traverse the V24 launcher/log chain"
                )
        print(json.dumps(payload, sort_keys=True), flush=True)
        return payload


def package_native_startup_executable_smoke_test(
    executable: Path,
    *,
    system: str,
    extra_environment: dict[str, str] | None = None,
) -> dict[str, object]:
    """Prove the existing host-native baseline with candidate selection off."""

    return _package_native_startup_executable_smoke_test(
        executable,
        system=system,
        portable_current=False,
        extra_environment=extra_environment,
    )


def package_portable_current_startup_executable_smoke_test(
    executable: Path,
    *,
    system: str,
    extra_environment: dict[str, str] | None = None,
    require_secure_backend_probe: bool = False,
) -> dict[str, object]:
    """Prove safe unavailability at the current portable boundary."""

    if system not in {"Darwin", "Linux"}:
        raise RuntimeError(
            "portable-current negative-boundary gate requires a POSIX host"
        )
    return _package_native_startup_executable_smoke_test(
        executable,
        system=system,
        portable_current=True,
        require_secure_backend_probe=require_secure_backend_probe,
        extra_environment=extra_environment,
    )


def package_native_startup_smoke_test(bundle: Path) -> dict[str, object]:
    """Construct the packaged real UI and host without external I/O."""

    system = platform.system()
    executable = (
        bundle / "Contents" / "MacOS" / "Onyx"
        if system == "Darwin"
        else bundle / ("Onyx.exe" if system == "Windows" else "Onyx")
    )
    return package_native_startup_executable_smoke_test(
        executable,
        system=system,
    )


def package_portable_current_startup_smoke_test(
    bundle: Path,
    *,
    require_secure_backend_probe: bool = False,
) -> dict[str, object]:
    """Prove packaged portable-current safe unavailability without external I/O."""

    system = platform.system()
    executable = (
        bundle / "Contents" / "MacOS" / "Onyx"
        if system == "Darwin"
        else bundle / "Onyx"
    )
    return package_portable_current_startup_executable_smoke_test(
        executable,
        system=system,
        require_secure_backend_probe=require_secure_backend_probe,
    )


def _governance_smoke_credential_references(data: Path) -> tuple[object, ...]:
    """Return the exact disposable Windows vault references for one smoke root."""

    from core.native_vault import SecretReference

    scope = hashlib.sha256(
        os.path.normcase(str(data.resolve())).encode("utf-8")
    ).hexdigest()[:24]
    service = f"Onyx.GovernanceV1.Smoke.{scope}"
    return tuple(
        SecretReference(service, account, f"Disposable Governance smoke {label}")
        for account, label in (
            ("ledger-key", "key"),
            ("ledger-head", "head"),
            ("ledger-pending", "pending"),
        )
    )


def _founder_smoke_credential_references(
    data: Path, workspace: Path
) -> tuple[object, ...]:
    """Return every disposable Governance and Founder reference for one gate."""

    from core.native_vault import SecretReference
    from core.onyx_live_activation_v16 import governance_workspace_bindings_v1

    identity, _records = governance_workspace_bindings_v1((str(workspace),))
    suffix = identity.workspace_id.removeprefix("workspace-")
    return (
        *_governance_smoke_credential_references(data),
        SecretReference(
            "CyryxLabs.Onyx.FounderSnapshot",
            f"integrity-{suffix}",
            "Disposable Founder smoke integrity key",
        ),
        SecretReference(
            "CyryxLabs.Onyx.FounderSnapshot",
            f"receipt-{suffix}",
            "Disposable Founder smoke receipt key",
        ),
    )


def _delete_windows_smoke_credentials(references: tuple[object, ...]) -> None:
    """Idempotently remove frozen-smoke secrets before their temp root vanishes."""

    if platform.system() != "Windows":
        return
    from core.native_vault import NativeSecretVault, SecretReference

    for reference in references:
        if not isinstance(reference, SecretReference):
            raise TypeError("smoke credential reference is invalid")
        NativeSecretVault(reference).delete()


def _diagnostic_reference_from_windows_target(target: object) -> object | None:
    """Parse only credential targets owned by disposable package diagnostics."""

    if not isinstance(target, str):
        return None
    from core.native_vault import SecretReference

    governance = re.fullmatch(
        r"(Onyx\.GovernanceV1\.Smoke\.[0-9a-f]{24}):"
        r"(ledger-key|ledger-head|ledger-pending)",
        target,
    )
    if governance is not None:
        return SecretReference(
            governance.group(1),
            governance.group(2),
            "Disposable package diagnostic credential",
        )
    founder = re.fullmatch(
        r"(CyryxLabs\.Onyx\.FounderSnapshot):"
        r"((?:integrity|receipt)-[0-9a-f]{24})",
        target,
    )
    if founder is not None:
        return SecretReference(
            founder.group(1),
            founder.group(2),
            "Disposable package diagnostic credential",
        )
    return None


def _windows_diagnostic_credential_references() -> frozenset[object]:
    """Enumerate diagnostic namespaces without reading any credential secret."""

    if platform.system() != "Windows":
        return frozenset()
    import ctypes
    from ctypes import wintypes

    from core import native_vault

    api = native_vault._win_api()
    count = wintypes.DWORD()
    credentials = ctypes.POINTER(ctypes.POINTER(native_vault._CREDENTIALW))()
    api.CredEnumerateW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(native_vault._CREDENTIALW))),
    ]
    api.CredEnumerateW.restype = wintypes.BOOL
    api.CredFree.argtypes = [wintypes.LPVOID]
    api.CredFree.restype = None
    if not api.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(credentials)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
            return frozenset()
        raise native_vault.NativeVaultError(
            "Windows Credential Manager could not enumerate diagnostics"
        )
    references: set[object] = set()
    try:
        for index in range(count.value):
            reference = _diagnostic_reference_from_windows_target(
                credentials[index].contents.TargetName
            )
            if reference is not None:
                references.add(reference)
    finally:
        api.CredFree(credentials)
    return frozenset(references)


@contextlib.contextmanager
def _windows_package_diagnostic_credential_scope():
    """Remove only diagnostic credentials created by this validation scope."""

    before = _windows_diagnostic_credential_references()
    try:
        yield
    finally:
        after = _windows_diagnostic_credential_references()
        created = tuple(
            sorted(
                after - before,
                key=lambda item: (item.service, item.account),
            )
        )
        _delete_windows_smoke_credentials(created)
        remaining = _windows_diagnostic_credential_references().intersection(created)
        if remaining:
            raise RuntimeError("package diagnostics left Windows credentials behind")


def package_governance_smoke_test(bundle: Path) -> None:
    """Exercise the frozen provider-free Governance V16 host contract."""

    if platform.system() != "Windows":
        return
    from core.onyx_live_activation_v16 import (
        GOVERNANCE_SMOKE_ARGUMENT,
        GOVERNANCE_SMOKE_OUTPUT_ENV,
    )
    from core.onyx_live_activation_v23 import CONTROL_FLAGS

    executable = bundle / "Onyx.exe"
    with tempfile.TemporaryDirectory(prefix="onyx-governance-smoke-") as temporary:
        root = Path(temporary)
        data = root / "data"
        _create_private_smoke_data(data)
        output = data / "governance-smoke-v1.json"
        environment = os.environ.copy()
        # This gate must exercise the packaged bootstrap's clean fallback path.
        # Developer shells can carry a subset of live-activation flags; passing
        # that partial configuration to the frozen .pyw host can leave an error
        # dialog waiting invisibly until the build timeout.  Remove the complete
        # current control surface, just as package_preflight_test does above.
        for name in CONTROL_FLAGS:
            environment.pop(name, None)
        environment["ONYX_DATA_DIR"] = str(data)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment[GOVERNANCE_SMOKE_OUTPUT_ENV] = str(output)
        print("Packaged Governance V16 smoke", flush=True)
        references = _governance_smoke_credential_references(data)
        try:
            result = subprocess.run(
                [str(executable), GOVERNANCE_SMOKE_ARGUMENT],
                cwd=ROOT,
                env=environment,
                check=False,
                timeout=180,
            )
        finally:
            _delete_windows_smoke_credentials(references)
        if result.returncode != 0:
            failure = output.read_text(encoding="utf-8") if output.is_file() else ""
            raise RuntimeError(
                "packaged Governance V16 smoke failed with exit "
                f"{result.returncode}: {failure}"
            )
        payload = json.loads(output.read_text(encoding="utf-8"))
        required = {
            "contract": "OnyxGovernanceSmoke.v1",
            "status": "passed",
            "trusted_ui_prompts": 0,
            "grant_reused": True,
            "grant_use_count_after_two": 2,
            "grant_revoke_replaced": True,
            "grant_expiry_replaced": True,
            "restart_active_grants": 0,
            "global_kill_latched": True,
            "late_result_event": "action-late-blocked",
            "restart_kill_denied": True,
            "network_calls": 0,
            "provider_calls": 0,
        }
        if any(payload.get(key) != value for key, value in required.items()):
            raise RuntimeError("packaged Governance V16 smoke result is invalid")
        reads = payload.get("catalog_reads")
        if (
            type(reads) is not list
            or len(reads) != 2
            or any(item.get("state") != "completed" for item in reads)
        ):
            raise RuntimeError("packaged local catalog smoke result is invalid")
        print(json.dumps(payload, sort_keys=True), flush=True)


def package_founder_smoke_test(bundle: Path) -> None:
    """Exercise the frozen provider-free Founder Snapshot V17 contract."""

    if platform.system() != "Windows":
        return
    from core.onyx_live_activation_v17 import (
        FOUNDER_SMOKE_ARGUMENT,
        FOUNDER_SMOKE_CORPUS_ENV,
        FOUNDER_SMOKE_OUTPUT_ENV,
        exact_activation_environment,
    )

    executable = bundle / "Onyx.exe"
    with tempfile.TemporaryDirectory(prefix="onyx-founder-smoke-") as temporary:
        root = Path(temporary)
        data = root / "data"
        workspace = data / "workspace"
        corpus = data / "corpus"
        _create_private_smoke_data(data)
        workspace.mkdir()
        corpus.mkdir()
        output = data / "founder-smoke-v1.json"
        environment = os.environ.copy()
        environment.update(exact_activation_environment((workspace,)))
        environment["ONYX_DATA_DIR"] = str(data)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment[FOUNDER_SMOKE_CORPUS_ENV] = str(corpus)
        environment[FOUNDER_SMOKE_OUTPUT_ENV] = str(output)
        print("Packaged Founder Snapshot V17 smoke", flush=True)
        references = _founder_smoke_credential_references(data, workspace)
        try:
            result = subprocess.run(
                [str(executable), FOUNDER_SMOKE_ARGUMENT],
                cwd=ROOT,
                env=environment,
                check=False,
                timeout=240,
            )
        finally:
            _delete_windows_smoke_credentials(references)
        if result.returncode != 0:
            failure = output.read_text(encoding="utf-8") if output.is_file() else ""
            raise RuntimeError(
                "packaged Founder Snapshot V17 smoke failed with exit "
                f"{result.returncode}: {failure}"
            )
        payload = json.loads(output.read_text(encoding="utf-8"))
        required = {
            "contract": "OnyxFounderSmoke.v1",
            "status": "passed",
            "governance": "available",
            "away": "available",
            "founder_brief": "available_read_only",
            "external_agent": "health_only:founder_smoke_process_isolation",
            "trusted_ui_prompts": 0,
            "grant_reused": True,
            "network_calls": 0,
            "provider_calls": 0,
            "process_calls": 0,
        }
        if any(payload.get(key) != value for key, value in required.items()):
            raise RuntimeError("packaged Founder Snapshot V17 result is invalid")
        corpus_result = payload.get("corpus")
        if (
            type(corpus_result) is not dict
            or type(corpus_result.get("bytes")) is not int
            or corpus_result.get("bytes", 0) <= 0
            or type(corpus_result.get("sha256")) is not str
            or len(corpus_result.get("sha256", "")) != 64
            or corpus_result.get("alias") != "founder-smoke-corpus-v17"
            or not str(corpus_result.get("citation", "")).startswith(
                "onyx-artifact://v1/alias/founder-smoke-corpus-v17/sha256/"
            )
            or not str(corpus_result.get("citation", "")).endswith(
                str(corpus_result.get("sha256", ""))
            )
            or corpus_result.get("content_trust") != "untrusted_data"
        ):
            raise RuntimeError("packaged Founder corpus result is invalid")
        for cadence in ("daily", "weekly", "restart"):
            brief = payload.get(cadence)
            expected_cadence = "daily" if cadence == "restart" else cadence
            if (
                type(brief) is not dict
                or brief.get("status") != "completed"
                or brief.get("cadence") != expected_cadence
                or brief.get("read_only") is not True
                or not brief.get("citations")
                or not brief.get("portfolio")
                or any(
                    key not in brief
                    for key in (
                        "blockers",
                        "decisions",
                        "opportunities",
                        "risks",
                        "top3",
                        "delta",
                    )
                )
            ):
                raise RuntimeError(
                    f"packaged Founder {cadence} brief result is invalid"
                )
            if corpus_result["citation"] not in brief["citations"]:
                raise RuntimeError(
                    f"packaged Founder {cadence} artifact citation is not reopenable"
                )
        serialized = json.dumps(payload, sort_keys=True)
        if ".invalid" in serialized or "onyx-artifact://v1/workspace-" in serialized:
            raise RuntimeError("packaged Founder result leaked an internal locator")
        restart_delta = payload["restart"].get("delta")
        if (
            type(restart_delta) is not dict
            or restart_delta.get("baseline") is not False
            or restart_delta.get("has_previous") is not True
        ):
            raise RuntimeError("packaged Founder restart delta is invalid")
        fences = payload.get("fences")
        if type(fences) is not dict or any(
            fences.get(name) is not True
            for name in ("cancel_wins", "commit_wins", "kill_wins", "kill_latched")
        ):
            raise RuntimeError("packaged Founder fence result is invalid")
        serialized = json.dumps(payload, sort_keys=True)
        if str(root) in serialized or any(
            name in serialized
            for name in (
                "workspace_id",
                "principal_id",
                "account_id",
                "profile_id",
                "source_identity_sha256",
            )
        ):
            raise RuntimeError("packaged Founder result leaked an internal identity")
        print(serialized, flush=True)


def package_document_intake_smoke_test(bundle: Path) -> None:
    """Exercise the frozen V18.1 UI-attachment to governed-ingestion path."""

    if platform.system() != "Windows":
        return
    from core.onyx_live_activation_v18 import (
        DOCUMENT_INTAKE_SMOKE_ARGUMENT,
        DOCUMENT_INTAKE_SMOKE_CORPUS_ENV,
        DOCUMENT_INTAKE_SMOKE_OUTPUT_ENV,
        exact_activation_environment,
    )

    executable = bundle / "Onyx.exe"
    with tempfile.TemporaryDirectory(prefix="onyx-document-intake-smoke-") as temporary:
        root = Path(temporary)
        data = root / "data"
        workspace = data / "workspace"
        corpus = data / "attachment-corpus"
        output = data / "document-intake-smoke-v1.json"
        _create_private_smoke_data(data)
        workspace.mkdir()
        corpus.mkdir()
        environment = os.environ.copy()
        environment.update(exact_activation_environment((workspace,)))
        environment["ONYX_DATA_DIR"] = str(data)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment[DOCUMENT_INTAKE_SMOKE_CORPUS_ENV] = str(corpus)
        environment[DOCUMENT_INTAKE_SMOKE_OUTPUT_ENV] = str(output)
        print("Packaged Document Intake V18.1 smoke", flush=True)
        result = subprocess.run(
            [str(executable), DOCUMENT_INTAKE_SMOKE_ARGUMENT],
            cwd=ROOT,
            env=environment,
            check=False,
            timeout=240,
        )
        if result.returncode != 0:
            failure = output.read_text(encoding="utf-8") if output.is_file() else ""
            raise RuntimeError(
                "packaged Document Intake V18.1 smoke failed with exit "
                f"{result.returncode}: {failure}"
            )
        payload = json.loads(output.read_text(encoding="utf-8"))
        required = {
            "contract": "OnyxDocumentIntakeSmoke.v1",
            "status": "passed",
            "trusted_ui_prompts": 0,
            "network_calls": 0,
            "provider_calls": 0,
            "process_calls": 0,
        }
        if any(payload.get(key) != value for key, value in required.items()):
            raise RuntimeError("packaged Document Intake smoke result is invalid")
        attachment = payload.get("attachment")
        controller_reopen = payload.get("controller_reopen")
        if (
            type(attachment) is not dict
            or not str(attachment.get("alias", "")).startswith("attachment-")
            or len(str(attachment.get("sha256", ""))) != 64
            or not str(attachment.get("citation", "")).endswith(
                str(attachment.get("sha256", ""))
            )
            or type(controller_reopen) is not dict
            or controller_reopen.get("status") != "completed"
            or controller_reopen.get("reopened") is not True
        ):
            raise RuntimeError("packaged Document Intake reopen result is invalid")
        serialized = json.dumps(payload, sort_keys=True)
        if str(root) in serialized or any(
            value in serialized
            for value in ("artifact_id", "workspace_id", "principal_id")
        ):
            raise RuntimeError("packaged Document Intake result leaked host metadata")
        print(serialized, flush=True)


def package_dayops_smoke_test(bundle: Path) -> None:
    """Exercise the frozen V20/V19 disconnected profile and UI bindings."""

    if platform.system() != "Windows":
        return
    from core.onyx_live_activation_v20 import exact_activation_environment

    executable = bundle / "Onyx.exe"
    with tempfile.TemporaryDirectory(prefix="onyx-dayops-v20-smoke-") as temporary:
        root = Path(temporary)
        data = root / "data"
        workspace = data / "workspace"
        _create_private_smoke_data(data)
        workspace.mkdir()
        environment = os.environ.copy()
        # The smoke is intentionally Windows-only. Its cross-platform unit
        # harness patches ``platform.system()`` while still executing with
        # POSIX path semantics, where the canonical Windows Docker path is not
        # absolute. Bind the already-running interpreter as an existing,
        # native absolute executable only for that harness; real Windows builds
        # retain the established Docker CLI default unchanged.
        activation_options = (
            {}
            if os.name == "nt"
            else {"executable_docker_cli": str(Path(sys.executable).resolve())}
        )
        environment.update(
            exact_activation_environment((workspace,), **activation_options)
        )
        environment["ONYX_DATA_DIR"] = str(data)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        print("Packaged DayOps V20 disconnected smoke", flush=True)
        result = subprocess.run(
            [str(executable), "--dayops-smoke-test"],
            cwd=ROOT,
            env=environment,
            check=False,
            timeout=240,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "packaged DayOps V20 smoke failed with exit "
                f"{result.returncode}: {result.stderr[-2_000:]}"
            )
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise RuntimeError("packaged DayOps V20 smoke produced no contract")
        payload = json.loads(lines[-1])
        required = {
            "contract": "OnyxDayOpsSmoke.v20",
            "status": "passed",
            "connection_status": "configuration_required",
            "read_only": True,
            "callbacks_bound": True,
            "advanced_callbacks_bound": True,
            "advanced_controller_status": "waiting_for_live_session",
            "network_calls": 0,
            "provider_calls": 0,
            "process_calls": 0,
            "trusted_ui_prompts": 0,
        }
        if any(payload.get(key) != value for key, value in required.items()):
            raise RuntimeError("packaged DayOps V20 smoke result is invalid")
        interception = payload.get("interception")
        if (
            type(interception) is not dict
            or interception.get("scope") != "best_effort_python_runtime"
            or not interception.get("network_surfaces")
            or not interception.get("process_surfaces")
            or not interception.get("provider_surfaces")
        ):
            raise RuntimeError("packaged DayOps V20 interception evidence is invalid")
        print(json.dumps(payload, sort_keys=True), flush=True)


def package_advanced_operations_smoke_test(bundle: Path) -> None:
    """Exercise frozen V20 activation without starting Phase 6 or external I/O."""

    if platform.system() != "Windows":
        return
    from core.onyx_live_activation_v20 import exact_activation_environment

    executable = bundle / "Onyx.exe"
    with tempfile.TemporaryDirectory(prefix="onyx-advanced-v20-smoke-") as temporary:
        root = Path(temporary)
        data = root / "data"
        workspace = data / "workspace"
        _create_private_smoke_data(data)
        workspace.mkdir()
        environment = os.environ.copy()
        activation_options = (
            {}
            if os.name == "nt"
            else {"executable_docker_cli": str(Path(sys.executable).resolve())}
        )
        environment.update(
            exact_activation_environment((workspace,), **activation_options)
        )
        environment["ONYX_DATA_DIR"] = str(data)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        print("Packaged Advanced Operations V20 smoke", flush=True)
        result = subprocess.run(
            [str(executable), "--advanced-operations-smoke-test"],
            cwd=ROOT,
            env=environment,
            check=False,
            timeout=240,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "packaged Advanced Operations V20 smoke failed with exit "
                f"{result.returncode}: {result.stderr[-2_000:]}"
            )
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise RuntimeError(
                "packaged Advanced Operations V20 smoke produced no contract"
            )
        payload = json.loads(lines[-1])
        required = {
            "contract": "OnyxAdvancedOperationsSmoke.v20",
            "status": "passed",
            "controller_status": "waiting_for_live_session",
            "callbacks_bound": True,
            "background_workers": 0,
            "polling_interval": None,
            "network_calls": 0,
            "provider_calls": 0,
            "process_calls": 0,
            "trusted_ui_prompts": 0,
        }
        if any(payload.get(key) != value for key, value in required.items()):
            raise RuntimeError(
                "packaged Advanced Operations V20 smoke result is invalid"
            )
        interception = payload.get("interception")
        if (
            type(interception) is not dict
            or interception.get("scope") != "best_effort_python_runtime"
            or not interception.get("network_surfaces")
            or not interception.get("process_surfaces")
            or not interception.get("provider_surfaces")
        ):
            raise RuntimeError(
                "packaged Advanced Operations V20 interception evidence is invalid"
            )
        print(json.dumps(payload, sort_keys=True), flush=True)


def package_advanced_commands_smoke_test(bundle: Path) -> None:
    """Prove frozen V21 tool declaration/routing with zero external calls."""

    if platform.system() != "Windows":
        return
    from core.onyx_live_activation_v21 import exact_activation_environment

    executable = bundle / "Onyx.exe"
    with tempfile.TemporaryDirectory(prefix="onyx-commands-v21-smoke-") as temporary:
        root = Path(temporary)
        data = root / "data"
        workspace = data / "workspace"
        _create_private_smoke_data(data)
        workspace.mkdir()
        environment = os.environ.copy()
        activation_options = (
            {}
            if os.name == "nt"
            else {"executable_docker_cli": str(Path(sys.executable).resolve())}
        )
        environment.update(
            exact_activation_environment((workspace,), **activation_options)
        )
        environment["ONYX_DATA_DIR"] = str(data)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        print("Packaged Advanced Commands V21 smoke", flush=True)
        result = subprocess.run(
            [str(executable), "--advanced-commands-smoke-test"],
            cwd=ROOT,
            env=environment,
            check=False,
            timeout=240,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "packaged Advanced Commands V21 smoke failed with exit "
                f"{result.returncode}: {result.stderr[-2_000:]}"
            )
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise RuntimeError(
                "packaged Advanced Commands V21 smoke produced no contract"
            )
        payload = json.loads(lines[-1])
        required = {
            "contract": "OnyxAdvancedCommandsSmoke.v21",
            "status": "passed",
            "tool_declared_exactly_once": True,
            "tool_route_owned": True,
            "controller_status": "not_started",
            "host_constructed": False,
            "background_workers": 0,
            "polling_interval": None,
            "network_calls": 0,
            "provider_calls": 0,
            "process_calls": 0,
            "trusted_ui_prompts": 0,
        }
        if any(payload.get(key) != value for key, value in required.items()):
            raise RuntimeError("packaged Advanced Commands V21 smoke result is invalid")
        interception = payload.get("interception")
        if (
            type(interception) is not dict
            or interception.get("scope") != "best_effort_python_runtime"
            or not interception.get("network_surfaces")
            or not interception.get("process_surfaces")
            or not interception.get("provider_surfaces")
        ):
            raise RuntimeError(
                "packaged Advanced Commands V21 interception evidence is invalid"
            )
        print(json.dumps(payload, sort_keys=True), flush=True)


def package_owner_context_smoke_test(bundle: Path) -> None:
    """Prove frozen V22 owner-context wiring with zero external calls."""

    if platform.system() != "Windows":
        return
    from core.onyx_live_activation_v22 import exact_activation_environment

    executable = bundle / "Onyx.exe"
    with tempfile.TemporaryDirectory(
        prefix="onyx-owner-context-v22-smoke-"
    ) as temporary:
        root = Path(temporary)
        data = root / "data"
        workspace = data / "workspace"
        _create_private_smoke_data(data)
        workspace.mkdir()
        environment = os.environ.copy()
        activation_options = (
            {}
            if os.name == "nt"
            else {"executable_docker_cli": str(Path(sys.executable).resolve())}
        )
        environment.update(
            exact_activation_environment((workspace,), **activation_options)
        )
        environment["ONYX_DATA_DIR"] = str(data)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        print("Packaged Owner Context V22 smoke", flush=True)
        result = subprocess.run(
            [str(executable), "--owner-context-smoke-test"],
            cwd=ROOT,
            env=environment,
            check=False,
            timeout=240,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "packaged Owner Context V22 smoke failed with exit "
                f"{result.returncode}: {result.stderr[-2_000:]}"
            )
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise RuntimeError("packaged Owner Context V22 smoke produced no contract")
        payload = json.loads(lines[-1])
        required = {
            "contract": "OnyxOwnerContextSmoke.v22",
            "status": "passed",
            "tool_declared_exactly_once": True,
            "tool_route_owned": True,
            "constructor_owned": True,
            "host_constructed": False,
            "background_workers": 0,
            "polling_interval": None,
            "network_calls": 0,
            "provider_calls": 0,
            "process_calls": 0,
            "trusted_ui_prompts": 0,
        }
        if any(payload.get(key) != value for key, value in required.items()):
            raise RuntimeError("packaged Owner Context V22 smoke result is invalid")
        interception = payload.get("interception")
        if (
            type(interception) is not dict
            or interception.get("scope") != "best_effort_python_runtime"
            or not interception.get("network_surfaces")
            or not interception.get("process_surfaces")
        ):
            raise RuntimeError(
                "packaged Owner Context V22 interception evidence is invalid"
            )
        print(json.dumps(payload, sort_keys=True), flush=True)


def package_operational_events_smoke_test(bundle: Path) -> None:
    """Prove V23 event wiring without provider calls, polling or content capture."""

    if platform.system() != "Windows":
        return
    from core.onyx_live_activation_v23 import exact_activation_environment

    executable = bundle / "Onyx.exe"
    with tempfile.TemporaryDirectory(
        prefix="onyx-operational-events-v23-smoke-"
    ) as temporary:
        root = Path(temporary)
        data = root / "data"
        workspace = data / "workspace"
        _create_private_smoke_data(data)
        workspace.mkdir()
        environment = os.environ.copy()
        activation_options = (
            {}
            if os.name == "nt"
            else {"executable_docker_cli": str(Path(sys.executable).resolve())}
        )
        environment.update(
            exact_activation_environment((workspace,), **activation_options)
        )
        environment["ONYX_DATA_DIR"] = str(data)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        print("Packaged Operational Events V23 smoke", flush=True)
        result = subprocess.run(
            [str(executable), "--operational-events-smoke-test"],
            cwd=ROOT,
            env=environment,
            check=False,
            timeout=240,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "packaged Operational Events V23 smoke failed with exit "
                f"{result.returncode}: {result.stderr[-2_000:]}"
            )
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise RuntimeError(
                "packaged Operational Events V23 smoke produced no contract"
            )
        payload = json.loads(lines[-1])
        required = {
            "contract": "OnyxOperationalEventsSmoke.v23",
            "status": "passed",
            "constructor_owned": True,
            "host_constructed": False,
            "content_captured": False,
            "background_workers": 0,
            "polling_interval": None,
            "network_calls": 0,
            "provider_calls": 0,
            "process_calls": 0,
            "trusted_ui_prompts": 0,
        }
        if any(payload.get(key) != value for key, value in required.items()):
            raise RuntimeError(
                "packaged Operational Events V23 smoke result is invalid"
            )
        interception = payload.get("interception")
        if (
            type(interception) is not dict
            or interception.get("scope") != "best_effort_python_runtime"
            or not interception.get("network_surfaces")
            or not interception.get("process_surfaces")
        ):
            raise RuntimeError(
                "packaged Operational Events V23 interception evidence is invalid"
            )
        print(json.dumps(payload, sort_keys=True), flush=True)


def find_iscc() -> Path | None:
    explicit = os.environ.get("INNO_ISCC", "").strip()
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    found = shutil.which("iscc")
    if found:
        return Path(found)
    for candidate in (
        ROOT / "build" / "tools" / "inno" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "Inno Setup 6"
        / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ):
        if candidate.is_file():
            return candidate
    return None


def isolated_windows_app_id(context: Path) -> str:
    """Derive a stable, non-production Inno AppId for one smoke context."""

    resolved = context.resolve()
    identity = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://cyryxlabs.com/onyx/setup-smoke/{resolved.as_posix().casefold()}",
    )
    value = "{{" + str(identity).upper() + "}"
    if value == WINDOWS_PRODUCTION_APP_ID:
        raise RuntimeError("isolated Windows Setup AppId collided with production")
    return value


def _stage_inno_compiler(iscc: Path, destination: Path) -> Path:
    """Stage exact compiler files with the sealed English message catalog."""

    try:
        compiler = iscc.resolve(strict=True)
        source = compiler.parent.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("Inno Setup compiler is unavailable") from exc
    if (
        compiler.name.casefold() != "iscc.exe"
        or not compiler.is_file()
        or compiler.is_symlink()
        or source.is_symlink()
        or destination.exists()
    ):
        raise RuntimeError("Inno Setup compiler boundary is invalid")
    for packaged in (INNO_DEFAULT_MESSAGES, INNO_LICENSE):
        if not packaged.is_file() or packaged.is_symlink():
            raise RuntimeError(f"packaged Inno support file is unavailable: {packaged}")
    english = INNO_DEFAULT_MESSAGES.read_text(encoding="utf-8")
    license_text = INNO_LICENSE.read_text(encoding="utf-8")
    if (
        "LanguageName=English" not in english
        or "LanguageID=$0409" not in english
        or "Inno Setup License" not in license_text
    ):
        raise RuntimeError("packaged Inno support files are invalid")

    destination.mkdir(parents=True)
    for candidate in sorted(source.iterdir(), key=lambda path: path.name.casefold()):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if candidate.name.casefold() == "default.isl":
            continue
        shutil.copy2(candidate, destination / candidate.name)
    shutil.copy2(INNO_DEFAULT_MESSAGES, destination / "Default.isl")
    shutil.copy2(INNO_LICENSE, destination / "LICENSE.txt")

    language_source = source / "Languages" / "BrazilianPortuguese.isl"
    if not language_source.is_file() or language_source.is_symlink():
        raise RuntimeError("Inno Setup Brazilian Portuguese catalog is unavailable")
    languages = destination / "Languages"
    languages.mkdir()
    shutil.copy2(language_source, languages / language_source.name)
    staged = destination / "ISCC.exe"
    if not staged.is_file():
        raise RuntimeError("staged Inno Setup compiler is incomplete")
    return staged


def _compile_windows_setup(
    *,
    source_dir: Path,
    output_dir: Path,
    version: str,
    app_id: str,
    setup_basename: str,
    lifecycle_record_path: Path | None = None,
) -> Path:
    iscc = find_iscc()
    if iscc is None:
        raise RuntimeError("Inno Setup 6 is required for Windows Setup compilation")
    if not source_dir.is_dir() or source_dir.is_symlink():
        raise RuntimeError(f"Windows Setup source bundle is unavailable: {source_dir}")
    if (
        not app_id.startswith("{{")
        or not app_id.endswith("}")
        or not re.fullmatch(r"[A-Za-z0-9._-]+", setup_basename)
    ):
        raise RuntimeError("Windows Setup identity is invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "ONYX_BUILD_VERSION": version,
            "ONYX_APP_ID": app_id,
            "ONYX_SOURCE_DIR": str(source_dir),
            "ONYX_OUTPUT_DIR": str(output_dir),
            "ONYX_SETUP_BASENAME": setup_basename,
            "ONYX_ICON_PATH": str(ASSETS / "onyx.ico"),
        }
    )
    env.pop("ONYX_LIFECYCLE_RECORD_PATH", None)
    if lifecycle_record_path is not None:
        lifecycle_value = str(lifecycle_record_path.resolve())
        if not lifecycle_record_path.is_absolute() or any(
            character in lifecycle_value for character in ("'", "\r", "\n", "\0")
        ):
            raise RuntimeError("Windows Setup lifecycle override is invalid")
        env["ONYX_LIFECYCLE_RECORD_PATH"] = lifecycle_value
    with tempfile.TemporaryDirectory(prefix="onyx-inno-compiler-") as temporary:
        staged_iscc = _stage_inno_compiler(
            iscc,
            Path(temporary) / "compiler",
        )
        run(
            [str(staged_iscc), str(ROOT / "packaging" / "windows" / "onyx.iss")],
            env=env,
        )
    result = output_dir / f"{setup_basename}.exe"
    if not result.is_file():
        raise RuntimeError(
            f"Windows Setup compiler produced no expected artifact: {result}"
        )
    return result


def package_windows(
    bundle: Path,
    version: str,
    *,
    allow_archive_only: bool,
    formal_release: bool = False,
) -> list[Path]:
    RELEASE.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []
    signed_bundle_records: tuple[dict[str, object], ...] = ()
    if formal_release:
        from scripts.windows_release import sign_bundle

        signed_bundle_records = sign_bundle(bundle)
    iscc = find_iscc()
    if iscc:
        basename = f"Onyx-{version}-Windows-{architecture()}-Setup"
        artifacts.append(
            _compile_windows_setup(
                source_dir=bundle,
                output_dir=RELEASE,
                version=version,
                app_id=WINDOWS_PRODUCTION_APP_ID,
                setup_basename=basename,
            )
        )
    elif not allow_archive_only:
        raise RuntimeError(
            "Inno Setup 6 is required for the Windows installer. Install it or use "
            "--allow-archive-only for a non-installer development artifact."
        )

    archive = RELEASE / f"Onyx-{version}-Windows-{architecture()}-Portable.zip"
    _write_windows_portable_archive(bundle, archive)
    artifacts.append(archive)
    if formal_release:
        from scripts.windows_release import sign_artifacts_and_write_evidence

        evidence = sign_artifacts_and_write_evidence(
            version=version,
            architecture=architecture(),
            release_dir=RELEASE,
            artifacts=artifacts,
            bundle_records=signed_bundle_records,
        )
        artifacts.append(evidence)
    return artifacts


def _write_windows_portable_archive(bundle: Path, archive: Path) -> None:
    """Write the portable ZIP without trusting third-party file timestamps.

    ZIP metadata cannot represent dates before 1980. Some upstream legal files
    intentionally carry older reproducible-build timestamps, so copying their
    filesystem metadata into a ZIP can fail after the Setup artifact has already
    been emitted. ``strict_timestamps=False`` clamps only the unrepresentable ZIP
    metadata; it does not mutate the staged bundle or its file content.
    """

    if not bundle.is_dir() or bundle.is_symlink():
        raise RuntimeError(f"Windows portable source bundle is unavailable: {bundle}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(f".{archive.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=False,
        ) as handle:
            members = sorted(
                bundle.rglob("*"),
                key=lambda path: path.relative_to(bundle).as_posix(),
            )
            for member in members:
                if member.is_symlink():
                    raise RuntimeError(
                        f"Windows portable source contains a linked member: {member}"
                    )
                relative = member.relative_to(bundle).as_posix()
                arcname = f"{bundle.name}/{relative}"
                if member.is_dir():
                    arcname += "/"
                handle.write(member, arcname)
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)


def _version_from_windows_setup(setup: Path) -> str:
    match = re.fullmatch(
        r"Onyx-([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)-Windows-[A-Za-z0-9._-]+-Setup\.exe",
        setup.name,
    )
    if match is None:
        raise RuntimeError(
            f"Windows Setup filename has no release version: {setup.name}"
        )
    return match.group(1)


def _build_isolated_windows_smoke_setup(
    production_setup: Path,
    *,
    source_bundle: Path,
    output_dir: Path,
    version: str,
    context: Path,
) -> Path:
    if not production_setup.is_file():
        raise RuntimeError(f"production Windows Setup is missing: {production_setup}")
    identity = isolated_windows_app_id(context)
    basename = f"Onyx-{version}-Windows-{architecture()}-Setup-Smoke-{identity[2:10]}"
    return _compile_windows_setup(
        source_dir=source_bundle,
        output_dir=output_dir,
        version=version,
        app_id=identity,
        setup_basename=basename,
        lifecycle_record_path=(
            context.resolve() / "runtime" / "installer-lifecycle-v1" / "resident.json"
        ),
    )


def _run_windows_setup_smoke_install(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float = WINDOWS_SETUP_SMOKE_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run one isolated Setup and tear down its exact process tree on timeout."""

    process = subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP
            if platform.system() == "Windows"
            else 0
        ),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                cwd=cwd,
                check=False,
                timeout=30,
                capture_output=True,
                text=True,
            )
        else:
            process.kill()
        stdout, stderr = process.communicate(timeout=30)
        raise subprocess.TimeoutExpired(
            cmd=argv,
            timeout=timeout,
            output=stdout or exc.output,
            stderr=stderr or exc.stderr,
        ) from exc
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _directory_entries_if_present(directory: Path) -> tuple[Path, ...]:
    """Snapshot a directory that an uninstaller may remove concurrently."""

    try:
        if not directory.exists():
            return ()
        return tuple(directory.iterdir())
    except FileNotFoundError:
        return ()


def package_windows_setup_install_smoke_test(
    setup: Path,
    *,
    source_bundle: Path | None = None,
    version: str | None = None,
) -> None:
    """Silently install, exercise, and remove a finished per-user Setup."""

    if not setup.is_file():
        raise RuntimeError(f"Windows Setup artifact is missing: {setup}")
    with tempfile.TemporaryDirectory(prefix="onyx-windows-setup-smoke-") as temporary:
        root = Path(temporary)
        install_dir = root / "installed" / "Onyx"
        install_log = root / "setup.log"
        isolated_setup = _build_isolated_windows_smoke_setup(
            setup,
            source_bundle=source_bundle or (BUNDLE_DIST / "Onyx"),
            output_dir=root / "installer",
            version=version or _version_from_windows_setup(setup),
            context=root,
        )
        execution_error: BaseException | None = None
        cleanup_failures: list[str] = []
        try:
            result = _run_windows_setup_smoke_install(
                [
                    str(isolated_setup),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/SP-",
                    "/CURRENTUSER",
                    "/NOICONS",
                    f"/DIR={install_dir}",
                    f"/LOG={install_log}",
                ],
                cwd=ROOT,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "isolated Windows Setup smoke install failed with exit "
                    f"{result.returncode}: {result.stderr[-2_000:]}"
                )
            package_native_startup_smoke_test(install_dir)
        except BaseException as exc:
            execution_error = exc
        finally:
            uninstaller = install_dir / "unins000.exe"
            if uninstaller.is_file():
                result = subprocess.run(
                    [
                        str(uninstaller),
                        "/VERYSILENT",
                        "/SUPPRESSMSGBOXES",
                        "/NORESTART",
                    ],
                    cwd=ROOT,
                    check=False,
                    timeout=300,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    cleanup_failures.append(
                        f"uninstall-exit-{result.returncode}:{result.stderr[-500:]}"
                    )
                deadline = time.monotonic() + WINDOWS_UNINSTALL_SETTLE_SECONDS
                remaining = _directory_entries_if_present(install_dir)
                while remaining:
                    if any(
                        not child.name.lower().startswith("unins")
                        for child in remaining
                    ):
                        break
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.1)
                    remaining = _directory_entries_if_present(install_dir)
            if _directory_entries_if_present(install_dir):
                cleanup_failures.append("installed-payload-remained")
        if execution_error is not None:
            if cleanup_failures:
                execution_error.add_note(
                    "Windows Setup cleanup failures: " + ",".join(cleanup_failures)
                )
            raise execution_error
        if cleanup_failures:
            raise RuntimeError(
                "isolated Windows Setup cleanup failed: " + ",".join(cleanup_failures)
            )
        print("Windows Setup isolated install/smoke/uninstall passed", flush=True)


def package_macos(
    bundle: Path,
    version: str,
    *,
    formal_release: bool,
) -> list[Path]:
    from scripts.macos_release import package_macos_release

    return package_macos_release(
        bundle,
        version=version,
        release_dir=RELEASE,
        app_entitlements=ROOT / "packaging" / "macos" / "entitlements.plist",
        browser_entitlements=(
            ROOT / "packaging" / "macos" / "browser-entitlements.plist"
        ),
        formal=formal_release,
    )


def linux_deb_arch() -> str:
    return {"x64": "amd64", "arm64": "arm64"}.get(architecture(), architecture())


def _linux_regular_file_is_executable_payload(path: Path) -> bool:
    """Recognize packaged native binaries and explicit script launchers.

    Linux release staging can inherit permissive modes from a Windows checkout
    or a bind mount.  Existing execute bits therefore cannot be trusted as the
    classification signal.  Native ELF payloads and files with a shebang are
    the only regular files that may remain executable in a shipped package.
    """

    with path.open("rb") as handle:
        header = handle.read(4)
    return header.startswith(b"\x7fELF") or header.startswith(b"#!")


def normalize_linux_tree_permissions(root: Path) -> None:
    """Apply deterministic package permissions without following links.

    This operates only on immutable application-package staging trees.  Onyx's
    owner-private mutable data directories are created separately by
    ``core.paths`` with mode 0700 and are intentionally not part of this tree.
    A directory named ``_internal/runtime`` is application code, not user data.
    """

    if _is_link_like(root) or not root.is_dir():
        raise RuntimeError(f"Linux permission root is not a real directory: {root}")
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(
                0o755 if _linux_regular_file_is_executable_payload(path) else 0o644
            )
        else:
            raise RuntimeError(f"Unsupported Linux package filesystem entry: {path}")
    root.chmod(0o755)


def _validate_linux_permission_record(
    *,
    path: str,
    mode: int,
    entry_type: str,
    executable_payload: bool = False,
) -> None:
    """Fail closed on unsafe or non-deterministic packaged POSIX modes."""

    permissions = mode & 0o7777
    # POSIX symlink permission bits are not access-control bits and are
    # conventionally reported as 0777.  The target's mode is validated through
    # its own archive/tree entry; treating the link metadata as writable would
    # be a false positive.
    if entry_type == "link":
        return
    if permissions & 0o002:
        raise RuntimeError(f"Linux artifact contains world-writable entry: {path}")
    if permissions & 0o7000:
        raise RuntimeError(f"Linux artifact contains special permission bits: {path}")
    if entry_type == "directory":
        if permissions != 0o755:
            raise RuntimeError(
                f"Linux artifact directory mode is not 0755: {path} ({permissions:04o})"
            )
        return
    if entry_type != "file":
        raise RuntimeError(f"Unsupported Linux permission entry type: {entry_type}")
    expected = 0o755 if executable_payload else 0o644
    if permissions != expected:
        reason = (
            "executable payload mode is not 0755"
            if executable_payload
            else "unexpected executable or non-0644 static-file mode"
        )
        raise RuntimeError(f"Linux artifact {reason}: {path} ({permissions:04o})")


def _linux_relative_link_parts(target: str, *, path: str) -> tuple[str, ...]:
    """Return a canonical package-internal link target or fail closed."""

    if not target or "\\" in target or "\x00" in target or target.startswith("/"):
        raise RuntimeError(f"Linux artifact link target is not relative: {path}")
    parsed = PurePosixPath(target)
    if (
        parsed.is_absolute()
        or str(parsed) != target
        or any(part in {"", ".", ".."} for part in target.split("/"))
    ):
        raise RuntimeError(
            f"Linux artifact link target is noncanonical or traverses: {path}"
        )
    return parsed.parts


def validate_linux_tree_permissions(root: Path, *, label: str) -> int:
    """Inspect an extracted Linux artifact and return its manifest size."""

    if _is_link_like(root) or not root.is_dir():
        raise RuntimeError(f"{label} permission manifest root is invalid: {root}")
    root_resolved = root.resolve(strict=True)
    count = 1
    _validate_linux_permission_record(
        path=".", mode=root.stat().st_mode, entry_type="directory"
    )
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = os.readlink(path)
            parts = _linux_relative_link_parts(target, path=relative)
            try:
                resolved = path.parent.joinpath(*parts).resolve(strict=True)
                resolved.relative_to(root_resolved)
            except (OSError, RuntimeError, ValueError) as exc:
                raise RuntimeError(
                    f"{label} link is dangling or leaves the package root: {relative}"
                ) from exc
            count += 1
            continue
        if path.is_dir():
            entry_type = "directory"
            executable = False
        elif path.is_file():
            entry_type = "file"
            executable = _linux_regular_file_is_executable_payload(path)
        else:
            raise RuntimeError(
                f"{label} contains unsupported filesystem entry: {relative}"
            )
        _validate_linux_permission_record(
            path=relative,
            mode=path.stat().st_mode,
            entry_type=entry_type,
            executable_payload=executable,
        )
        count += 1
    print(f"{label} permission manifest verified ({count} entries)", flush=True)
    return count


def validate_linux_tar_permissions(archive: Path) -> int:
    """Inspect TAR metadata and file signatures without trusting extraction."""

    count = 0
    with tarfile.open(archive, "r:gz") as handle:
        members = handle.getmembers()
        by_name: dict[str, tarfile.TarInfo] = {}
        for member in members:
            name = PurePosixPath(member.name)
            if (
                not member.name
                or name.is_absolute()
                or str(name) != member.name
                or any(part in {"", ".", ".."} for part in member.name.split("/"))
                or member.name in by_name
            ):
                raise RuntimeError(
                    f"Linux TAR contains noncanonical or duplicate path: {member.name}"
                )
            by_name[member.name] = member

        def require_link_target(member: tarfile.TarInfo) -> None:
            current = member
            seen: set[str] = set()
            while current.issym() or current.islnk():
                if current.name in seen:
                    raise RuntimeError(
                        f"Linux TAR link cycle is not allowed: {member.name}"
                    )
                seen.add(current.name)
                parts = _linux_relative_link_parts(
                    current.linkname,
                    path=current.name,
                )
                target = (
                    PurePosixPath(*parts)
                    if current.islnk()
                    else PurePosixPath(current.name).parent.joinpath(*parts)
                ).as_posix()
                try:
                    current = by_name[target]
                except KeyError as exc:
                    raise RuntimeError(
                        f"Linux TAR link is dangling: {member.name} -> {target}"
                    ) from exc

        for member in members:
            if member.isdir():
                entry_type = "directory"
                executable = False
            elif member.isfile():
                entry_type = "file"
                stream = handle.extractfile(member)
                if stream is None:
                    raise RuntimeError(
                        f"Linux TAR file cannot be inspected: {member.name}"
                    )
                header = stream.read(4)
                executable = header.startswith(b"\x7fELF") or header.startswith(b"#!")
            elif member.issym() or member.islnk():
                entry_type = "link"
                executable = False
                require_link_target(member)
            else:
                raise RuntimeError(
                    f"Linux TAR contains unsupported entry: {member.name}"
                )
            _validate_linux_permission_record(
                path=member.name,
                mode=member.mode,
                entry_type=entry_type,
                executable_payload=executable,
            )
            count += 1
    print(f"Linux TAR permission manifest verified ({count} entries)", flush=True)
    return count


def write_linux_tree(root: Path, bundle: Path, version: str) -> None:
    app_root = root / "opt" / "cyryx-labs" / "onyx"
    shutil.copytree(bundle, app_root, symlinks=True)
    executable = app_root / "Onyx"
    executable.chmod(0o755)

    binary = root / "usr" / "bin"
    binary.mkdir(parents=True, exist_ok=True)
    (binary / "onyx").write_text(
        '#!/bin/sh\nexec /opt/cyryx-labs/onyx/Onyx "$@"\n',
        encoding="utf-8",
    )

    applications = root / "usr" / "share" / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT / "packaging" / "linux" / "onyx.desktop", applications / "onyx.desktop"
    )

    metainfo = root / "usr" / "share" / "metainfo"
    metainfo.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT / "packaging" / "linux" / "com.cyryxlabs.onyx.metainfo.xml",
        metainfo / "com.cyryxlabs.onyx.metainfo.xml",
    )

    user_units = root / "usr" / "lib" / "systemd" / "user"
    user_units.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT / "packaging" / "linux" / "onyx.service", user_units / "onyx.service"
    )

    icons = root / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
    icons.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ASSETS / "onyx.png", icons / "onyx.png")

    control = root / "DEBIAN"
    control.mkdir(parents=True, exist_ok=True)
    installed_kb = (
        sum(path.stat().st_size for path in app_root.rglob("*") if path.is_file())
        // 1024
    )
    (control / "control").write_text(
        "\n".join(
            [
                "Package: onyx-ai-assistant",
                f"Version: {version}",
                "Section: utils",
                "Priority: optional",
                f"Architecture: {linux_deb_arch()}",
                "Maintainer: Cyryx Labs",
                f"Installed-Size: {installed_kb}",
                f"Depends: {', '.join(LINUX_DEB_RUNTIME_DEPENDENCIES)}",
                "Description: Onyx AI assistant by Cyryx Labs",
                " Real-time voice, governed local tools, local memory and configured cloud models.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    normalize_linux_tree_permissions(root)


def write_appimage_desktop(source: Path, target: Path) -> None:
    """Write AppImage-local desktop metadata without changing the DEB file."""

    desktop = source.read_text(encoding="utf-8")
    desktop = desktop.replace(
        "Exec=/opt/cyryx-labs/onyx/Onyx",
        "Exec=onyx",
    )
    if "Exec=onyx" not in desktop or "Exec=/opt/" in desktop:
        raise RuntimeError("AppImage desktop Exec could not be localized")
    target.write_text(desktop, encoding="utf-8")


def resolve_appimagetool(*, diagnostic_without_appimage: bool = False) -> Path | None:
    raw = os.environ.get("APPIMAGETOOL", "").strip()
    selected = raw or shutil.which("appimagetool")
    if not selected:
        if diagnostic_without_appimage:
            print(
                "DIAGNOSTIC ONLY: appimagetool is unavailable; AppImage omitted",
                flush=True,
            )
            return None
        raise RuntimeError(
            "formal Linux release requires appimagetool; set APPIMAGETOOL to "
            "the verified executable (or use --diagnostic-without-appimage "
            "only for a non-release diagnostic build)"
        )
    tool = Path(selected).expanduser().absolute()
    if _is_link_like(tool) or not tool.is_file() or not os.access(tool, os.X_OK):
        raise RuntimeError(
            f"appimagetool is not a trusted executable regular file: {tool}"
        )
    return tool


def resolve_appimage_runtime() -> Path:
    """Resolve the immutable type-2 runtime embedded by appimagetool.

    appimagetool otherwise downloads the runtime from the mutable
    ``continuous`` channel while packaging.  Requiring an independently
    downloaded, architecture-bound file makes the build fail closed before
    any AppImage is created.
    """

    raw = os.environ.get("APPIMAGE_RUNTIME_FILE", "").strip()
    if not raw:
        raise RuntimeError(
            "formal Linux release requires the pinned AppImage runtime; set "
            "APPIMAGE_RUNTIME_FILE to the verified architecture-specific file"
        )
    runtime = Path(raw).expanduser().absolute()
    if _is_link_like(runtime) or not runtime.is_file() or runtime.stat().st_size <= 0:
        raise RuntimeError(
            f"AppImage runtime is not a trusted nonempty regular file: {runtime}"
        )
    selected_architecture = architecture()
    expected = APPIMAGE_RUNTIME_SHA256.get(selected_architecture)
    if expected is None:
        raise RuntimeError(
            f"no trusted AppImage runtime digest for architecture: {selected_architecture}"
        )
    observed = hash_file(runtime)
    if observed != expected:
        raise RuntimeError(
            "AppImage runtime SHA-256 mismatch for "
            f"{selected_architecture}: expected {expected}, observed {observed}"
        )
    return runtime


def package_linux(
    bundle: Path,
    version: str,
    *,
    diagnostic_without_appimage: bool = False,
) -> list[Path]:
    RELEASE.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []

    package_root = BUILD / "linux-package"
    clean_path(package_root)
    write_linux_tree(package_root, bundle, version)
    deb = RELEASE / f"Onyx-{version}-Linux-{architecture()}.deb"
    run(["dpkg-deb", "--build", "--root-owner-group", str(package_root), str(deb)])
    artifacts.append(deb)

    archive = RELEASE / f"Onyx-{version}-Linux-{architecture()}.tar.gz"
    tar_root = BUILD / "linux-tar"
    clean_path(tar_root)
    tar_bundle = tar_root / "Onyx"
    shutil.copytree(bundle, tar_bundle, symlinks=True)
    normalize_linux_tree_permissions(tar_root)
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(tar_bundle, arcname="Onyx")
    artifacts.append(archive)

    appimagetool = resolve_appimagetool(
        diagnostic_without_appimage=diagnostic_without_appimage
    )
    if appimagetool is not None:
        appimage_runtime = resolve_appimage_runtime()
        appdir = BUILD / "Onyx.AppDir"
        clean_path(appdir)
        appdir.mkdir(parents=True)
        app_bundle = appdir / "usr" / "lib" / "onyx"
        app_bundle.parent.mkdir(parents=True)
        shutil.copytree(bundle, app_bundle, symlinks=True)
        (appdir / "usr" / "bin").mkdir(parents=True)
        (appdir / "usr" / "bin" / "onyx").write_text(
            '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\n'
            'exec "$HERE/../lib/onyx/Onyx" "$@"\n',
            encoding="utf-8",
        )
        write_appimage_desktop(
            ROOT / "packaging" / "linux" / "onyx.desktop",
            appdir / "onyx.desktop",
        )
        app_metainfo = appdir / "usr" / "share" / "metainfo"
        app_metainfo.mkdir(parents=True)
        shutil.copy2(
            ROOT / "packaging" / "linux" / "com.cyryxlabs.onyx.metainfo.xml",
            app_metainfo / "com.cyryxlabs.onyx.metainfo.xml",
        )
        shutil.copy2(ASSETS / "onyx.png", appdir / "onyx.png")
        app_run = appdir / "AppRun"
        app_run.write_text(
            '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexec "$HERE/usr/lib/onyx/Onyx" "$@"\n',
            encoding="utf-8",
        )
        app_run.chmod(0o755)
        normalize_linux_tree_permissions(appdir)
        appimage = RELEASE / f"Onyx-{version}-Linux-{architecture()}.AppImage"
        env = os.environ.copy()
        env["ARCH"] = "x86_64" if architecture() == "x64" else "aarch64"
        run(
            [
                str(appimagetool),
                "--runtime-file",
                str(appimage_runtime),
                str(appdir),
                str(appimage),
            ],
            env=env,
        )
        artifacts.append(appimage)
    return artifacts


def package_artifact_structure_test(
    artifacts: list[Path],
    *,
    system: str | None = None,
    require_linux_appimage: bool = True,
) -> None:
    """Inspect current-host artifacts without claiming cross-host execution."""

    selected_system = system or platform.system()
    if not artifacts:
        raise RuntimeError("release produced no artifacts to inspect")
    for artifact in artifacts:
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise RuntimeError(f"release artifact is empty: {artifact}")

    if selected_system == "Windows":
        setups = [path for path in artifacts if path.name.endswith("-Setup.exe")]
        archives = [path for path in artifacts if path.suffix.lower() == ".zip"]
        if not archives:
            raise RuntimeError("Windows portable artifact is missing")
        for setup in setups:
            with setup.open("rb") as handle:
                if handle.read(2) != b"MZ":
                    raise RuntimeError("Windows installer is not a PE artifact")
        for archive in archives:
            with zipfile.ZipFile(archive) as handle:
                names = set(handle.namelist())
                required = {
                    "Onyx/Onyx.exe",
                    "Onyx/_internal/core/onyx_live_activation_v19.py",
                    "Onyx/_internal/core/onyx_live_activation_v20.py",
                    "Onyx/_internal/core/onyx_live_activation_v21.py",
                    "Onyx/_internal/core/onyx_live_activation_v22.py",
                    "Onyx/_internal/core/onyx_live_activation_v23.py",
                    "Onyx/_internal/core/onyx_live_activation_v24.py",
                    "Onyx/_internal/core/owner_context_controller_v1.py",
                    "Onyx/_internal/core/owner_context_profile_v1.py",
                    "Onyx/_internal/core/operational_event_bridge_v1.py",
                    "Onyx/_internal/core/operational_event_controller_v1.py",
                    "Onyx/_internal/scripts/bootstrap_onyx_live_v19.pyw",
                    "Onyx/_internal/scripts/launch_onyx_live_v19.pyw",
                    "Onyx/_internal/scripts/bootstrap_onyx_live_v20.pyw",
                    "Onyx/_internal/scripts/launch_onyx_live_v20.pyw",
                    "Onyx/_internal/scripts/bootstrap_onyx_live_v21.pyw",
                    "Onyx/_internal/scripts/launch_onyx_live_v21.pyw",
                    "Onyx/_internal/scripts/bootstrap_onyx_live_v22.pyw",
                    "Onyx/_internal/scripts/launch_onyx_live_v22.pyw",
                    "Onyx/_internal/scripts/bootstrap_onyx_live_v23.pyw",
                    "Onyx/_internal/scripts/launch_onyx_live_v23.pyw",
                    "Onyx/_internal/scripts/bootstrap_onyx_live_v24.pyw",
                    "Onyx/_internal/scripts/launch_onyx_live_v24.pyw",
                }
                if not required.issubset(names):
                    raise RuntimeError(
                        "Windows portable entrypoint chain is incomplete"
                    )
                with handle.open("Onyx/Onyx.exe") as entrypoint:
                    if entrypoint.read(2) != b"MZ":
                        raise RuntimeError(
                            "Windows portable entrypoint is not a PE file"
                        )
    elif selected_system == "Darwin":
        images = [path for path in artifacts if path.suffix.lower() == ".dmg"]
        if len(images) != 1:
            raise RuntimeError("macOS DMG artifact is missing or ambiguous")
        subprocess.run(
            ["hdiutil", "verify", str(images[0])],
            cwd=ROOT,
            check=True,
            timeout=180,
        )
    elif selected_system == "Linux":
        archives = [path for path in artifacts if path.name.endswith(".tar.gz")]
        packages = [path for path in artifacts if path.suffix.lower() == ".deb"]
        if len(archives) != 1 or len(packages) != 1:
            raise RuntimeError("Linux DEB/TAR artifacts are missing or ambiguous")
        appimages = [path for path in artifacts if path.name.endswith(".AppImage")]
        if require_linux_appimage and len(appimages) != 1:
            raise RuntimeError("formal Linux release requires exactly one AppImage")
        with tarfile.open(archives[0], "r:gz") as handle:
            names = {member.name: member for member in handle.getmembers()}
            entrypoint = names.get("Onyx/Onyx")
            if (
                entrypoint is None
                or not entrypoint.isfile()
                or not entrypoint.mode & 0o111
            ):
                raise RuntimeError("Linux TAR entrypoint is missing or not executable")
        validate_linux_tar_permissions(archives[0])
        listing = subprocess.run(
            ["dpkg-deb", "--contents", str(packages[0])],
            cwd=ROOT,
            check=True,
            timeout=120,
            capture_output=True,
            text=True,
        ).stdout
        if (
            "./opt/cyryx-labs/onyx/Onyx" not in listing
            or "./usr/share/applications/onyx.desktop" not in listing
            or "./usr/share/metainfo/com.cyryxlabs.onyx.metainfo.xml" not in listing
            or "./usr/lib/systemd/user/onyx.service" not in listing
        ):
            raise RuntimeError("Linux DEB entrypoint/desktop chain is incomplete")
        with tempfile.TemporaryDirectory(
            prefix="onyx-deb-permission-manifest-"
        ) as temporary:
            deb_root = Path(temporary) / "root"
            deb_root.mkdir(mode=0o755)
            subprocess.run(
                ["dpkg-deb", "--extract", str(packages[0]), str(deb_root)],
                cwd=ROOT,
                check=True,
                timeout=180,
                capture_output=True,
                text=True,
            )
            validate_linux_tree_permissions(deb_root, label="Linux DEB")
        for appimage in appimages:
            with appimage.open("rb") as handle:
                if handle.read(4) != b"\x7fELF":
                    raise RuntimeError("Linux AppImage is not an ELF artifact")
            if not os.access(appimage, os.X_OK):
                raise RuntimeError("Linux AppImage is not executable")
            with tempfile.TemporaryDirectory(
                prefix="onyx-appimage-permission-manifest-"
            ) as temporary:
                subprocess.run(
                    [str(appimage), "--appimage-extract"],
                    cwd=temporary,
                    check=True,
                    timeout=300,
                    capture_output=True,
                    text=True,
                )
                appimage_root = Path(temporary) / "squashfs-root"
                validate_linux_tree_permissions(
                    appimage_root,
                    label="Linux AppImage",
                )
    else:
        raise RuntimeError(f"unsupported artifact inspection host: {selected_system}")
    print(
        f"Artifact structure verified on current {selected_system} host; "
        "no cross-host runtime claim",
        flush=True,
    )


def package_artifact_entrypoint_smoke_test(
    artifacts: list[Path],
    *,
    system: str | None = None,
    portable_current: bool = False,
    require_secure_backend_probe: bool = False,
    require_linux_appimage: bool = True,
) -> None:
    """Execute an entrypoint from a finished artifact on its build host."""

    selected_system = system or platform.system()
    validate_secure_backend_probe_requirement(
        require=require_secure_backend_probe,
        portable_current=portable_current,
        system=selected_system,
    )
    if portable_current and selected_system not in {"Darwin", "Linux"}:
        raise RuntimeError(
            "portable-current negative-boundary artifact gate requires a POSIX host"
        )
    bundle_smoke = (
        package_portable_current_startup_smoke_test
        if portable_current
        else package_native_startup_smoke_test
    )
    executable_smoke = (
        package_portable_current_startup_executable_smoke_test
        if portable_current
        else package_native_startup_executable_smoke_test
    )
    with tempfile.TemporaryDirectory(
        prefix="onyx-artifact-entrypoint-smoke-"
    ) as temporary:
        extracted = Path(temporary)
        if selected_system == "Windows":
            archives = [path for path in artifacts if path.suffix.lower() == ".zip"]
            if len(archives) != 1:
                raise RuntimeError("Windows portable artifact is missing or ambiguous")
            with zipfile.ZipFile(archives[0]) as handle:
                if any(
                    Path(name).is_absolute() or ".." in Path(name).parts
                    for name in handle.namelist()
                ):
                    raise RuntimeError("Windows portable artifact has an unsafe member")
                handle.extractall(extracted)
            bundle = extracted / "Onyx"
        elif selected_system == "Linux":
            packages = [path for path in artifacts if path.suffix.lower() == ".deb"]
            if len(packages) != 1:
                raise RuntimeError("Linux DEB artifact is missing or ambiguous")
            deb_root = extracted / "deb"
            deb_root.mkdir()
            subprocess.run(
                ["dpkg-deb", "--extract", str(packages[0]), str(deb_root)],
                cwd=ROOT,
                check=True,
                timeout=180,
            )
            bundle = deb_root / "opt" / "cyryx-labs" / "onyx"
        elif selected_system == "Darwin":
            images = [path for path in artifacts if path.suffix.lower() == ".dmg"]
            if len(images) != 1:
                raise RuntimeError("macOS DMG artifact is missing or ambiguous")
            mount = extracted / "mount"
            mount.mkdir()
            subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    "-readonly",
                    "-nobrowse",
                    "-mountpoint",
                    str(mount),
                    str(images[0]),
                ],
                cwd=ROOT,
                check=True,
                timeout=180,
            )
            try:
                bundle_smoke(mount / "Onyx.app")
            finally:
                subprocess.run(
                    ["hdiutil", "detach", str(mount)],
                    cwd=ROOT,
                    check=False,
                    timeout=120,
                )
            print("Artifact entrypoint smoke passed (Darwin DMG)", flush=True)
            return
        else:
            raise RuntimeError(f"unsupported artifact smoke host: {selected_system}")
        if portable_current and require_secure_backend_probe:
            bundle_smoke(
                bundle,
                require_secure_backend_probe=True,
            )
        else:
            bundle_smoke(bundle)
        if selected_system == "Windows":
            for setup in (
                path for path in artifacts if path.name.endswith("-Setup.exe")
            ):
                package_windows_setup_install_smoke_test(
                    setup,
                    source_bundle=bundle,
                    version=_version_from_windows_setup(setup),
                )
        if selected_system == "Linux":
            archives = [path for path in artifacts if path.name.endswith(".tar.gz")]
            if len(archives) != 1:
                raise RuntimeError("Linux TAR artifact is missing or ambiguous")
            tar_root = extracted / "tar"
            tar_root.mkdir()
            with tarfile.open(archives[0], "r:gz") as handle:
                handle.extractall(tar_root, filter="data")
            if portable_current and require_secure_backend_probe:
                bundle_smoke(
                    tar_root / "Onyx",
                    require_secure_backend_probe=True,
                )
            else:
                bundle_smoke(tar_root / "Onyx")
            appimages = [path for path in artifacts if path.name.endswith(".AppImage")]
            if require_linux_appimage and len(appimages) != 1:
                raise RuntimeError(
                    "formal Linux release requires exactly one AppImage smoke"
                )
            for appimage in appimages:
                smoke_options: dict[str, object] = {
                    "system": "Linux",
                    "extra_environment": {"APPIMAGE_EXTRACT_AND_RUN": "1"},
                }
                if portable_current and require_secure_backend_probe:
                    smoke_options["require_secure_backend_probe"] = True
                executable_smoke(appimage, **smoke_options)
        print(
            f"Artifact entrypoint smoke passed ({selected_system}); "
            "every finished host-native entrypoint validated",
            flush=True,
        )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    version: str,
    artifacts: list[Path],
    *,
    bundle: Path,
    formal_release: bool = False,
    platform_signing_policy: str = "not-applicable",
    diagnostic_exceptions: tuple[str, ...] = (),
) -> None:
    from core.onyx_hud_current_acceptance_v48 import (
        MANIFEST_SHA256 as HUD_V48_MANIFEST_SHA256,
        verify_current_hud_acceptance,
    )
    from core.native_activation_contract_v1 import activation_contract_for_system_v1
    from scripts.runtime_distribution_inventory import write_bundle_inventory

    snapshot, content_path = load_verified_build_input_seal()
    seal_name = f"pyinstaller-first-party-inputs-{snapshot['root_sha256']}.json"
    release_seal = RELEASE / seal_name
    if release_seal.exists():
        if (
            release_seal.is_symlink()
            or release_seal.read_bytes() != content_path.read_bytes()
        ):
            raise RuntimeError("release build-input seal path contains different bytes")
    else:
        shutil.copy2(content_path, release_seal)
    seal_sha256 = hash_file(release_seal)
    records = [
        {"name": path.name, "size": path.stat().st_size, "sha256": hash_file(path)}
        for path in sorted(artifacts)
    ]
    suffix = f"{platform.system()}-{architecture()}"
    bundle_inventory_path = RELEASE / f"bundle-inventory-{suffix}.json"
    bundle_inventory = write_bundle_inventory(
        bundle=bundle,
        output=bundle_inventory_path,
        version=version,
        system=platform.system(),
        architecture=architecture(),
        requirements_path=ROOT / "requirements.txt",
    )
    bundle_inventory_record = {
        "name": bundle_inventory_path.name,
        "size": bundle_inventory_path.stat().st_size,
        "sha256": hash_file(bundle_inventory_path),
        "contract": bundle_inventory["contract"],
        "bundle_root_sha256": bundle_inventory["bundleRootSha256"],
        "file_count": bundle_inventory["fileCount"],
        "runtime_distribution_count": bundle_inventory["runtimeDistributionCount"],
        "runtime_distribution_root_sha256": bundle_inventory[
            "runtimeDistributionRootSha256"
        ],
    }
    manifest = {
        "product": "Onyx",
        "publisher": "Cyryx Labs",
        "version": version,
        "system": platform.system(),
        "release_class": (
            "formal"
            if formal_release and not diagnostic_exceptions
            else (
                "diagnostic-incomplete"
                if "linux_appimage_omitted" in diagnostic_exceptions
                else "untrusted-candidate"
            )
        ),
        "diagnostic_exceptions": list(diagnostic_exceptions),
        "release_trust": {
            "contract": "onyx.release-trust.v1",
            "formal_requested": formal_release,
            "platform": platform.system(),
            "signing_policy": platform_signing_policy,
        },
        "activation_contract": activation_contract_for_system_v1(platform.system()),
        "runtime_integrity": {
            "hud_v48_manifest_sha256": HUD_V48_MANIFEST_SHA256,
            "hud_candidate": verify_current_hud_acceptance(ROOT)["candidate"],
        },
        "build_input_seal": {
            "contract": snapshot["contract"],
            "file_count": snapshot["file_count"],
            "root_sha256": snapshot["root_sha256"],
            "manifest": seal_name,
            "manifest_sha256": seal_sha256,
            "manifest_size": release_seal.stat().st_size,
        },
        "architecture": architecture(),
        "bundle_inventory": bundle_inventory_record,
        "artifacts": records,
    }
    (RELEASE / f"release-manifest-{suffix}.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (RELEASE / f"SHA256SUMS-{suffix}.txt").write_text(
        "".join(f"{item['sha256']}  {item['name']}\n" for item in records)
        + f"{seal_sha256}  {seal_name}\n"
        + f"{bundle_inventory_record['sha256']}  {bundle_inventory_path.name}\n",
        encoding="utf-8",
    )


def main() -> int:
    from core.version import __version__

    parser = argparse.ArgumentParser(description="Build native Onyx release packages")
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--allow-archive-only", action="store_true")
    parser.add_argument(
        "--diagnostic-without-appimage",
        action="store_true",
        help=(
            "Linux diagnostics only: omit AppImage and mark the manifest "
            "diagnostic-incomplete; never use for a formal release"
        ),
    )
    parser.add_argument(
        "--portable-current-negative-boundary-gate",
        action="store_true",
        help=("prove only fail-closed portable-current safe unavailability on POSIX"),
    )
    parser.add_argument(
        "--require-linux-secure-backend-probe",
        action="store_true",
        help=(
            "official Linux runner only: require 1..MAX trusted Secret Service "
            "probe calls in each portable-current startup smoke"
        ),
    )
    parser.add_argument(
        "--formal-release",
        action="store_true",
        help=("require all publisher, platform trust and public-release gates"),
    )
    parser.add_argument(
        "--linux-signing-policy",
        choices=("unsigned-approved",),
        help=(
            "formal Linux policy; unsigned-approved is explicit owner approval "
            "for checksum/SBOM-bound unsigned Linux packages"
        ),
    )
    args = parser.parse_args()

    selected_system = platform.system()
    validate_secure_backend_probe_requirement(
        require=args.require_linux_secure_backend_probe,
        portable_current=args.portable_current_negative_boundary_gate,
        system=selected_system,
    )
    validate_formal_linux_release_contract(
        formal_release=args.formal_release,
        system=selected_system,
        portable_current=args.portable_current_negative_boundary_gate,
        require_secure_backend_probe=args.require_linux_secure_backend_probe,
        linux_signing_policy=args.linux_signing_policy,
    )
    validate_release_version(args.version)
    archived = archive_existing_release()
    if archived is not None:
        print(f"Archived previous release at {archived}", flush=True)
    clean_path(RELEASE)
    RELEASE.mkdir(parents=True)
    bundle = build_bundle(args.version, skip_browser=args.skip_browser)
    portable_current_gate = args.portable_current_negative_boundary_gate
    if portable_current_gate and platform.system() not in {"Darwin", "Linux"}:
        raise RuntimeError(
            "portable-current negative-boundary gate requires a POSIX host"
        )
    validation_bundle = clone_runtime_validation_bundle(bundle)
    try:
        with _windows_package_diagnostic_credential_scope():
            smoke_test(validation_bundle)
            package_preflight_test(validation_bundle)
            package_capabilities_smoke_test(validation_bundle)
            package_parity_smoke_test(validation_bundle)
            package_native_startup_smoke_test(validation_bundle)
            if portable_current_gate:
                package_portable_current_startup_smoke_test(
                    validation_bundle,
                    require_secure_backend_probe=(
                        args.require_linux_secure_backend_probe
                    ),
                )
            package_governance_smoke_test(validation_bundle)
            package_founder_smoke_test(validation_bundle)
            package_document_intake_smoke_test(validation_bundle)
            package_dayops_smoke_test(validation_bundle)
            package_advanced_operations_smoke_test(validation_bundle)
            package_advanced_commands_smoke_test(validation_bundle)
            package_owner_context_smoke_test(validation_bundle)
            package_operational_events_smoke_test(validation_bundle)
    finally:
        clean_path(RUNTIME_VALIDATION_BUNDLE)
    # Runtime validation must not mutate the production payload (for example
    # by creating __pycache__ files from integrity-source data).
    from scripts.package_hygiene import assert_package_hygiene

    assert_package_hygiene(bundle)
    system = platform.system()
    if args.diagnostic_without_appimage and system != "Linux":
        raise RuntimeError("--diagnostic-without-appimage is Linux-only")
    if args.linux_signing_policy and system != "Linux":
        raise RuntimeError("--linux-signing-policy is Linux-only")
    if system == "Linux" and args.formal_release:
        if args.linux_signing_policy != "unsigned-approved":
            raise RuntimeError(
                "formal Linux release requires --linux-signing-policy unsigned-approved"
            )
    elif system == "Linux" and args.linux_signing_policy:
        raise RuntimeError("Linux signing policy is only valid with --formal-release")
    if system == "Windows":
        if args.formal_release and args.allow_archive_only:
            raise RuntimeError("formal Windows release requires the signed installer")
        artifacts = package_windows(
            bundle,
            args.version,
            allow_archive_only=args.allow_archive_only,
            formal_release=args.formal_release,
        )
    elif system == "Darwin":
        artifacts = package_macos(
            bundle,
            args.version,
            formal_release=args.formal_release,
        )
    elif system == "Linux":
        artifacts = package_linux(
            bundle,
            args.version,
            diagnostic_without_appimage=args.diagnostic_without_appimage,
        )
    else:
        raise RuntimeError(f"Unsupported release host: {system}")
    require_linux_appimage = not args.diagnostic_without_appimage
    package_artifact_structure_test(
        artifacts,
        system=system,
        require_linux_appimage=require_linux_appimage,
    )
    package_artifact_entrypoint_smoke_test(
        artifacts,
        system=system,
        require_linux_appimage=require_linux_appimage,
    )
    if portable_current_gate:
        package_artifact_entrypoint_smoke_test(
            artifacts,
            system=system,
            portable_current=True,
            require_secure_backend_probe=(args.require_linux_secure_backend_probe),
            require_linux_appimage=require_linux_appimage,
        )
    diagnostic_exceptions: tuple[str, ...] = ()
    if args.diagnostic_without_appimage:
        diagnostic_exceptions += ("linux_appimage_omitted",)
    if system == "Darwin" and not args.formal_release:
        diagnostic_exceptions += ("macos_adhoc_not_notarized",)
    if system == "Windows" and not args.formal_release:
        diagnostic_exceptions += ("windows_authenticode_untrusted",)
    if system == "Linux" and not args.formal_release:
        diagnostic_exceptions += ("linux_formal_policy_not_requested",)
    signing_policy = {
        "Windows": "authenticode-trusted"
        if args.formal_release
        else "unsigned-untrusted",
        "Darwin": "developer-id-notarized"
        if args.formal_release
        else "adhoc-untrusted",
        "Linux": args.linux_signing_policy or "unsigned-untrusted",
    }[system]
    write_manifest(
        args.version,
        artifacts,
        bundle=bundle,
        formal_release=args.formal_release,
        platform_signing_policy=signing_policy,
        diagnostic_exceptions=diagnostic_exceptions,
    )
    print(f"Built {len(artifacts)} Onyx artifact(s) in {RELEASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
