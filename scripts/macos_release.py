"""Fail-closed macOS Developer ID signing and notarization helpers.

The module is importable on every host so its policy can be unit tested, but
all mutating operations refuse to run anywhere except a native supported Mac.
No secret bytes are written to release evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


MACOS_MINIMUM_VERSION = "15.0"
SUPPORTED_ARCHITECTURES = {"arm64": "arm64"}
FORMAL_ENVIRONMENT = (
    "APPLE_TEAM_ID",
    "APPLE_SIGNING_IDENTITY",
    "APPLE_KEYCHAIN_PATH",
    "APPLE_NOTARY_KEY_PATH",
    "APPLE_NOTARY_KEY_ID",
    "APPLE_NOTARY_ISSUER_ID",
)
TEAM_ID_RE = re.compile(r"^[A-Z0-9]{10}$")
NOTARY_KEY_ID_RE = re.compile(r"^[A-Z0-9]{10}$")
ISSUER_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class MacReleaseError(RuntimeError):
    """The macOS artifact cannot satisfy the formal release contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def supported_architecture(machine: str | None = None) -> str:
    selected = (machine or platform.machine()).lower()
    try:
        return SUPPORTED_ARCHITECTURES[selected]
    except KeyError as exc:
        raise MacReleaseError(f"unsupported native macOS architecture: {selected}") from exc


def assert_supported_host() -> str:
    if platform.system() != "Darwin":
        raise MacReleaseError("macOS release operations require a native Darwin host")
    architecture = supported_architecture()
    release = platform.mac_ver()[0]
    try:
        major = int(release.split(".", 1)[0])
    except (ValueError, IndexError) as exc:
        raise MacReleaseError(f"unreadable macOS host version: {release!r}") from exc
    if major < int(MACOS_MINIMUM_VERSION.split(".", 1)[0]):
        raise MacReleaseError(
            f"macOS {MACOS_MINIMUM_VERSION}+ is required; host is {release}"
        )
    return architecture


def require_formal_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if environment is None else environment)
    missing = [name for name in FORMAL_ENVIRONMENT if not env.get(name, "").strip()]
    if missing:
        raise MacReleaseError(
            "formal macOS release credentials are incomplete: " + ",".join(missing)
        )
    values = {name: env[name].strip() for name in FORMAL_ENVIRONMENT}
    team_id = values["APPLE_TEAM_ID"]
    identity = values["APPLE_SIGNING_IDENTITY"]
    if not TEAM_ID_RE.fullmatch(team_id):
        raise MacReleaseError("APPLE_TEAM_ID is malformed")
    if not (
        identity.startswith("Developer ID Application: ")
        and f"({team_id})" in identity
    ):
        raise MacReleaseError(
            "APPLE_SIGNING_IDENTITY is not bound to APPLE_TEAM_ID"
        )
    if not NOTARY_KEY_ID_RE.fullmatch(values["APPLE_NOTARY_KEY_ID"]):
        raise MacReleaseError("APPLE_NOTARY_KEY_ID is malformed")
    if not ISSUER_ID_RE.fullmatch(values["APPLE_NOTARY_ISSUER_ID"]):
        raise MacReleaseError("APPLE_NOTARY_ISSUER_ID is malformed")
    for name in ("APPLE_KEYCHAIN_PATH", "APPLE_NOTARY_KEY_PATH"):
        path = Path(values[name]).expanduser()
        if not path.is_file() or path.is_symlink():
            raise MacReleaseError(f"{name} is not a regular file")
        values[name] = str(path.resolve())
    return values


def _run(
    argv: Sequence[str],
    *,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=True,
        timeout=1800,
        capture_output=capture_output,
        text=True,
    )


def _is_macho(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    result = _run(["file", "-b", str(path)], capture_output=True)
    return "Mach-O" in result.stdout


def macho_architectures(path: Path) -> tuple[str, ...]:
    result = _run(["lipo", "-archs", str(path)], capture_output=True)
    return tuple(result.stdout.strip().split())


def verify_bundle_architectures(app: Path) -> dict[str, tuple[str, ...]]:
    expected = supported_architecture()
    expected_macho = "x86_64" if expected == "x64" else "arm64"
    executable = app / "Contents" / "MacOS" / "Onyx"
    if not executable.is_file():
        raise MacReleaseError("Onyx.app main executable is missing")
    observed: dict[str, tuple[str, ...]] = {}
    for candidate in sorted(app.rglob("*"), key=lambda item: item.as_posix()):
        if not _is_macho(candidate):
            continue
        architectures = macho_architectures(candidate)
        relative = candidate.relative_to(app).as_posix()
        observed[relative] = architectures
        if expected_macho not in architectures:
            raise MacReleaseError(
                f"nested Mach-O lacks {expected_macho}: {relative}={architectures}"
            )
    if observed.get("Contents/MacOS/Onyx") != (expected_macho,):
        raise MacReleaseError(
            "main executable is not a single-architecture native build: "
            f"{observed.get('Contents/MacOS/Onyx')}"
        )
    if not observed:
        raise MacReleaseError("Onyx.app contains no inspectable Mach-O code")
    return observed


def verify_bundle_metadata(app: Path, version: str) -> None:
    info_path = app / "Contents" / "Info.plist"
    try:
        info = plistlib.loads(info_path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise MacReleaseError("Onyx.app Info.plist is invalid") from exc
    required = {
        "CFBundleIdentifier": "labs.cyryx.onyx",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": MACOS_MINIMUM_VERSION,
    }
    drift = {
        key: info.get(key)
        for key, expected in required.items()
        if info.get(key) != expected
    }
    if drift:
        raise MacReleaseError(f"Onyx.app metadata drifted: {drift}")


def _signable_paths(app: Path) -> tuple[Path, ...]:
    code: set[Path] = set()
    bundles: set[Path] = set()
    for candidate in app.rglob("*"):
        if candidate.is_symlink():
            continue
        if candidate.is_dir() and candidate.suffix.lower() in {
            ".app",
            ".framework",
            ".xpc",
        }:
            bundles.add(candidate)
        elif _is_macho(candidate):
            code.add(candidate)
    ordered_code = sorted(code, key=lambda item: (-len(item.parts), item.as_posix()))
    ordered_bundles = sorted(
        bundles,
        key=lambda item: (-len(item.parts), item.as_posix()),
    )
    return tuple([*ordered_code, *ordered_bundles, app])


def _entitlements_for(
    candidate: Path,
    app: Path,
    *,
    app_entitlements: Path,
    browser_entitlements: Path,
) -> Path | None:
    relative = candidate.relative_to(app).as_posix().casefold() if candidate != app else ""
    if candidate == app or relative == "contents/macos/onyx":
        return app_entitlements
    if any(token in relative for token in ("chromium", "chrome helper", "playwright")):
        return browser_entitlements
    return None


def sign_app_inside_out(
    app: Path,
    *,
    identity: str,
    app_entitlements: Path,
    browser_entitlements: Path,
    formal: bool,
) -> None:
    if not app.is_dir() or app.is_symlink():
        raise MacReleaseError("Onyx.app is not a regular application bundle")
    for entitlements in (app_entitlements, browser_entitlements):
        if not entitlements.is_file() or entitlements.is_symlink():
            raise MacReleaseError(f"entitlements are unavailable: {entitlements}")
        try:
            plistlib.loads(entitlements.read_bytes())
        except (OSError, plistlib.InvalidFileException) as exc:
            raise MacReleaseError(f"entitlements are invalid: {entitlements}") from exc
    for candidate in _signable_paths(app):
        argv = ["codesign", "--force", "--sign", identity, "--options", "runtime"]
        if formal:
            argv.append("--timestamp")
        entitlements = _entitlements_for(
            candidate,
            app,
            app_entitlements=app_entitlements,
            browser_entitlements=browser_entitlements,
        )
        if entitlements is not None:
            argv.extend(["--entitlements", str(entitlements)])
        argv.append(str(candidate))
        _run(argv)


def verify_signed_app(app: Path, *, gatekeeper: bool) -> None:
    _run(["codesign", "--verify", "--deep", "--strict", "--verbose=4", str(app)])
    _run(["codesign", "--display", "--verbose=4", str(app)])
    if gatekeeper:
        _run(["spctl", "--assess", "--type", "execute", "--verbose=4", str(app)])


def create_dmg(app: Path, dmg: Path) -> None:
    if dmg.exists() or dmg.is_symlink():
        dmg.unlink()
    with tempfile.TemporaryDirectory(prefix="onyx-dmg-") as temporary:
        staging = Path(temporary)
        shutil.copytree(app, staging / "Onyx.app", symlinks=True)
        os.symlink("/Applications", staging / "Applications")
        _run(
            [
                "hdiutil",
                "create",
                "-volname",
                "Onyx",
                "-srcfolder",
                str(staging),
                "-ov",
                "-format",
                "UDZO",
                str(dmg),
            ]
        )
    _run(["hdiutil", "verify", str(dmg)])


def _notary_arguments(credentials: Mapping[str, str]) -> list[str]:
    return [
        "--key",
        credentials["APPLE_NOTARY_KEY_PATH"],
        "--key-id",
        credentials["APPLE_NOTARY_KEY_ID"],
        "--issuer",
        credentials["APPLE_NOTARY_ISSUER_ID"],
    ]


def _notarize(
    artifact: Path,
    *,
    label: str,
    release_dir: Path,
    credentials: Mapping[str, str],
) -> tuple[Path, Path, dict[str, object]]:
    submission_path = release_dir / f"notary-submit-{label}.json"
    log_path = release_dir / f"notary-log-{label}.json"
    result = _run(
        [
            "xcrun",
            "notarytool",
            "submit",
            str(artifact),
            *_notary_arguments(credentials),
            "--wait",
            "--output-format",
            "json",
        ],
        capture_output=True,
    )
    submission_path.write_text(result.stdout, encoding="utf-8")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MacReleaseError("notarytool returned invalid JSON") from exc
    if (
        type(payload) is not dict
        or payload.get("status") != "Accepted"
        or not payload.get("id")
    ):
        raise MacReleaseError(f"Apple notarization was not accepted: {payload}")
    _run(
        [
            "xcrun",
            "notarytool",
            "log",
            str(payload["id"]),
            str(log_path),
            *_notary_arguments(credentials),
        ]
    )
    if not log_path.is_file() or log_path.stat().st_size <= 0:
        raise MacReleaseError("Apple notary log was not retained")
    try:
        notary_log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MacReleaseError("Apple notary log is invalid JSON") from exc
    issues = notary_log.get("issues", []) if type(notary_log) is dict else None
    if issues not in ([], None):
        raise MacReleaseError("Apple notary log contains unresolved issues")
    return submission_path, log_path, payload


def package_macos_release(
    app: Path,
    *,
    version: str,
    release_dir: Path,
    app_entitlements: Path,
    browser_entitlements: Path,
    formal: bool,
    environment: Mapping[str, str] | None = None,
) -> list[Path]:
    architecture = assert_supported_host()
    release_dir.mkdir(parents=True, exist_ok=True)
    verify_bundle_metadata(app, version)
    macho = verify_bundle_architectures(app)
    credentials = require_formal_environment(environment) if formal else {}
    identity = credentials.get("APPLE_SIGNING_IDENTITY", "-")
    if formal:
        identity_output = _run(
            [
                "security",
                "find-identity",
                "-v",
                "-p",
                "codesigning",
                credentials["APPLE_KEYCHAIN_PATH"],
            ],
            capture_output=True,
        ).stdout
        if identity not in identity_output:
            raise MacReleaseError("Developer ID identity is absent from the temporary keychain")
    sign_app_inside_out(
        app,
        identity=identity,
        app_entitlements=app_entitlements,
        browser_entitlements=browser_entitlements,
        formal=formal,
    )
    verify_signed_app(app, gatekeeper=False)

    suffix = f"macOS-{architecture}"
    evidence_files: list[Path] = []
    app_submission: dict[str, object] | None = None
    if formal:
        with tempfile.TemporaryDirectory(prefix="onyx-notary-app-") as temporary:
            archive = Path(temporary) / "Onyx.zip"
            _run(["ditto", "-c", "-k", "--keepParent", str(app), str(archive)])
            submission, log, app_submission = _notarize(
                archive,
                label=f"app-{suffix}",
                release_dir=release_dir,
                credentials=credentials,
            )
            evidence_files.extend([submission, log])
        _run(["xcrun", "stapler", "staple", str(app)])
        _run(["xcrun", "stapler", "validate", str(app)])
        verify_signed_app(app, gatekeeper=True)

    dmg = release_dir / f"Onyx-{version}-{suffix}.dmg"
    create_dmg(app, dmg)
    dmg_submission: dict[str, object] | None = None
    if formal:
        _run(["codesign", "--force", "--timestamp", "--sign", identity, str(dmg)])
        _run(["codesign", "--verify", "--strict", "--verbose=4", str(dmg)])
        submission, log, dmg_submission = _notarize(
            dmg,
            label=f"dmg-{suffix}",
            release_dir=release_dir,
            credentials=credentials,
        )
        evidence_files.extend([submission, log])
        _run(["xcrun", "stapler", "staple", str(dmg)])
        _run(["xcrun", "stapler", "validate", str(dmg)])
        _run(["hdiutil", "verify", str(dmg)])
        _run(
            [
                "spctl",
                "--assess",
                "--type",
                "open",
                "--context",
                "context:primary-signature",
                "--verbose=4",
                str(dmg),
            ]
        )

    evidence = release_dir / f"macos-release-evidence-{architecture}.json"
    evidence_payload = {
        "contract": "onyx.macos-release-evidence.v1",
        "version": version,
        "architecture": architecture,
        "minimum_macos": MACOS_MINIMUM_VERSION,
        "formal": formal,
        "developer_id_signed": formal,
        "developer_id_identity": identity if formal else None,
        "team_id": credentials.get("APPLE_TEAM_ID") if formal else None,
        "hardened_runtime": True,
        "notarized": formal,
        "stapled": formal,
        "gatekeeper_assessed": formal,
        "dmg": {
            "name": dmg.name,
            "size": dmg.stat().st_size,
            "sha256": sha256_file(dmg),
        },
        "app_notary_id": app_submission.get("id") if app_submission else None,
        "dmg_notary_id": dmg_submission.get("id") if dmg_submission else None,
        "macho_file_count": len(macho),
        "unclaimed": [
            "physical_mac_tcc_audio_camera_screen_accessibility",
            "long_session_voice_and_reconnect",
            "disposable_host_full_lifecycle",
            "macos_current_v19_capability_parity",
        ],
    }
    evidence.write_text(
        json.dumps(evidence_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return [dmg, *evidence_files, evidence]
