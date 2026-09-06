"""Disposable-host lifecycle acceptance for signed/notarized Onyx DMGs.

This script is intentionally not a general uninstaller. It operates only on
the exact Onyx application/data paths, only on a native macOS 15+ host, and
only after an explicit disposable-host environment assertion. Evidence must
live outside both managed paths.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Iterator, Sequence

try:
    from scripts.macos_release import MACOS_MINIMUM_VERSION, assert_supported_host
except ModuleNotFoundError:  # Direct execution: sys.path[0] is the scripts directory.
    from macos_release import MACOS_MINIMUM_VERSION, assert_supported_host


APP = Path("/Applications/Onyx.app")
DATA = Path.home() / "Library" / "Application Support" / "Cyryx Labs" / "Onyx"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "labs.cyryx.onyx.plist"
LAUNCH_AGENT_TEMPLATE = (
    APP / "Contents" / "Resources" / "autostart" / "labs.cyryx.onyx.plist"
)
CONFIRMATION = "ONYX_DISPOSABLE_MAC_LIFECYCLE_V1"
SMOKE_ARGUMENT = "--native-startup-smoke-test"
SMOKE_OUTPUT_ENV = "ONYX_NATIVE_STARTUP_SMOKE_OUTPUT"


class MacLifecycleError(RuntimeError):
    """The lifecycle host or artifact failed an acceptance boundary."""


def _run(
    argv: Sequence[str],
    *,
    environment: dict[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=True,
        timeout=900,
        env=environment,
        capture_output=capture_output,
        text=True,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_disposable_host(environment: dict[str, str] | None = None) -> None:
    env = os.environ if environment is None else environment
    assert_supported_host()
    if env.get("ONYX_DISPOSABLE_MAC_CONFIRM") != CONFIRMATION:
        raise MacLifecycleError(
            "set ONYX_DISPOSABLE_MAC_CONFIRM to the exact disposable-host token"
        )
    if APP.as_posix() != "/Applications/Onyx.app":
        raise MacLifecycleError("application target contract drifted")
    expected_data = Path.home() / "Library" / "Application Support" / "Cyryx Labs" / "Onyx"
    if DATA != expected_data:
        raise MacLifecycleError("owner-data target contract drifted")


def require_regular_dmg(path: Path, expected_sha256: str) -> Path:
    candidate = path.expanduser().resolve()
    if not candidate.is_file() or candidate.is_symlink():
        raise MacLifecycleError(f"DMG is not a regular file: {candidate}")
    if len(expected_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha256):
        raise MacLifecycleError("expected DMG SHA-256 is malformed")
    observed = sha256_file(candidate)
    if observed != expected_sha256:
        raise MacLifecycleError(f"DMG SHA-256 mismatch: {candidate.name}")
    return candidate


def require_evidence_directory(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    if candidate in {APP, DATA} or APP in candidate.parents or DATA in candidate.parents:
        raise MacLifecycleError("evidence must be outside application and owner-data paths")
    if candidate.exists() and (candidate.is_symlink() or not candidate.is_dir()):
        raise MacLifecycleError("evidence path is not a regular directory")
    candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
    return candidate


@contextlib.contextmanager
def mounted_dmg(dmg: Path) -> Iterator[Path]:
    mount = Path(tempfile.mkdtemp(prefix="onyx-lifecycle-mount-"))
    _run(
        [
            "hdiutil",
            "attach",
            "-readonly",
            "-nobrowse",
            "-mountpoint",
            str(mount),
            str(dmg),
        ]
    )
    try:
        app = mount / "Onyx.app"
        if not app.is_dir() or app.is_symlink():
            raise MacLifecycleError("mounted DMG has no regular Onyx.app")
        yield app
    finally:
        _run(["hdiutil", "detach", str(mount)])
        mount.rmdir()


def assess_dmg(dmg: Path) -> None:
    _run(["xattr", "-p", "com.apple.quarantine", str(dmg)])
    _run(["hdiutil", "verify", str(dmg)])
    _run(["xcrun", "stapler", "validate", str(dmg)])
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
    with mounted_dmg(dmg) as mounted_app:
        _run(["codesign", "--verify", "--deep", "--strict", "--verbose=4", str(mounted_app)])
        _run(["spctl", "--assess", "--type", "execute", "--verbose=4", str(mounted_app)])


def app_version(app: Path = APP) -> str:
    try:
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise MacLifecycleError("installed app Info.plist is invalid") from exc
    version = info.get("CFBundleShortVersionString")
    if not isinstance(version, str) or not version:
        raise MacLifecycleError("installed app version is unavailable")
    return version


def _remove_exact_app() -> None:
    if not APP.exists():
        return
    if APP.is_symlink() or not APP.is_dir() or APP.as_posix() != "/Applications/Onyx.app":
        raise MacLifecycleError("refusing unsafe application removal target")
    shutil.rmtree(APP)
    if APP.exists():
        raise MacLifecycleError("application removal left residual bytes")


def install_from_dmg(dmg: Path, expected_version: str) -> None:
    with mounted_dmg(dmg) as mounted_app:
        stage = APP.parent / f".Onyx.install-{uuid.uuid4().hex}.app"
        if stage.exists() or stage.is_symlink():
            raise MacLifecycleError("staged application target unexpectedly exists")
        try:
            _run(["ditto", str(mounted_app), str(stage)])
            _run(["codesign", "--verify", "--deep", "--strict", "--verbose=4", str(stage)])
            _run(["spctl", "--assess", "--type", "execute", "--verbose=4", str(stage)])
            _remove_exact_app()
            stage.rename(APP)
        finally:
            if stage.exists() and stage.is_dir() and not stage.is_symlink():
                shutil.rmtree(stage)
    if app_version() != expected_version:
        raise MacLifecycleError(
            f"installed version mismatch: expected {expected_version}, got {app_version()}"
        )


def smoke_installed_app(evidence: Path, label: str) -> dict[str, object]:
    executable = APP / "Contents" / "MacOS" / "Onyx"
    if not executable.is_file() or executable.is_symlink():
        raise MacLifecycleError("installed Onyx executable is unavailable")
    output = evidence / f"native-smoke-{label}.json"
    environment = os.environ.copy()
    environment[SMOKE_OUTPUT_ENV] = str(output)
    _run([str(executable), SMOKE_ARGUMENT], environment=environment)
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MacLifecycleError(f"installed startup smoke is invalid: {label}") from exc
    if payload.get("status") != "passed":
        raise MacLifecycleError(f"installed startup smoke failed: {label}")
    return payload


def validate_launch_agent(evidence: Path, label: str) -> dict[str, object]:
    """Bootstrap, observe and remove the package-owned Aqua LaunchAgent."""

    try:
        payload = plistlib.loads(LAUNCH_AGENT_TEMPLATE.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise MacLifecycleError("installed LaunchAgent template is invalid") from exc
    if payload != {
        "Label": "labs.cyryx.onyx",
        "ProgramArguments": ["/Applications/Onyx.app/Contents/MacOS/Onyx"],
        "LimitLoadToSessionType": "Aqua",
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Interactive",
    }:
        raise MacLifecycleError("installed LaunchAgent template drifted")
    if LAUNCH_AGENT.exists() or LAUNCH_AGENT.is_symlink():
        raise MacLifecycleError("owner LaunchAgent target is not clean")
    LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(LAUNCH_AGENT_TEMPLATE, LAUNCH_AGENT)
    LAUNCH_AGENT.chmod(0o600)
    domain = f"gui/{os.getuid()}"
    _run(["launchctl", "bootstrap", domain, str(LAUNCH_AGENT)])
    try:
        status = _run(
            ["launchctl", "print", f"{domain}/labs.cyryx.onyx"],
            capture_output=True,
        ).stdout
        (evidence / f"launch-agent-{label}.txt").write_text(status, encoding="utf-8")
        if "labs.cyryx.onyx" not in status:
            raise MacLifecycleError("Onyx LaunchAgent did not become observable")
    finally:
        _run(["launchctl", "bootout", domain, str(LAUNCH_AGENT)])
        LAUNCH_AGENT.unlink()
    return {
        "manager": "launchd",
        "label": "labs.cyryx.onyx",
        "activated": True,
        "removed_after_gate": True,
    }


def backup_owner_data(evidence: Path) -> Path | None:
    if not DATA.exists():
        return None
    if DATA.is_symlink() or not DATA.is_dir():
        raise MacLifecycleError("owner-data path is unsafe")
    backup = evidence / "owner-data-backup"
    if backup.exists() or backup.is_symlink():
        raise MacLifecycleError("owner-data backup target unexpectedly exists")
    _run(["ditto", str(DATA), str(backup)])
    if not backup.is_dir():
        raise MacLifecycleError("owner-data backup was not created")
    return backup


def run_lifecycle(
    *,
    current_dmg: Path,
    current_sha256: str,
    current_version: str,
    prior_dmg: Path,
    prior_sha256: str,
    prior_version: str,
    evidence_dir: Path,
) -> Path:
    require_disposable_host()
    if not current_version or not prior_version or current_version == prior_version:
        raise MacLifecycleError("current and prior release versions must be distinct")
    current = require_regular_dmg(current_dmg, current_sha256)
    prior = require_regular_dmg(prior_dmg, prior_sha256)
    evidence = require_evidence_directory(evidence_dir)
    if APP.exists() or DATA.exists() or LAUNCH_AGENT.exists() or LAUNCH_AGENT.is_symlink():
        raise MacLifecycleError(
            "lifecycle host is not clean; app, owner data or LaunchAgent already exists"
        )
    assess_dmg(current)
    assess_dmg(prior)
    events: list[dict[str, object]] = []

    install_from_dmg(current, current_version)
    events.append({"gate": "clean_install_current", "smoke": smoke_installed_app(evidence, "clean-current"), "autostart": validate_launch_agent(evidence, "clean-current")})
    DATA.mkdir(parents=True, mode=0o700)
    marker = DATA / "lifecycle-owner-data-marker.txt"
    marker.write_text("owner-data-must-survive\n", encoding="utf-8")

    _remove_exact_app()
    if not marker.is_file():
        raise MacLifecycleError("app-only uninstall removed owner data")
    events.append({"gate": "uninstall_app_only", "owner_data_preserved": True})

    install_from_dmg(current, current_version)
    smoke_installed_app(evidence, "reinstall-current")
    if marker.read_text(encoding="utf-8") != "owner-data-must-survive\n":
        raise MacLifecycleError("same-version reinstall changed owner data")
    events.append({"gate": "reinstall_current", "owner_data_preserved": True})

    backup = backup_owner_data(evidence)
    if backup is None:
        raise MacLifecycleError("owner-data backup was unexpectedly absent")
    _remove_exact_app()
    if DATA.is_symlink() or not DATA.is_dir():
        raise MacLifecycleError("owner-data target became unsafe before upgrade gate")
    shutil.rmtree(DATA)
    if DATA.exists() or not (backup / marker.name).is_file():
        raise MacLifecycleError("owner-data reset was not safely backed up")

    install_from_dmg(prior, prior_version)
    smoke_installed_app(evidence, "clean-prior")
    DATA.mkdir(parents=True, mode=0o700)
    upgrade_marker = DATA / "lifecycle-upgrade-marker.txt"
    upgrade_marker.write_text("upgrade-data-must-survive\n", encoding="utf-8")
    install_from_dmg(current, current_version)
    smoke_installed_app(evidence, "upgrade-current")
    if not upgrade_marker.is_file():
        raise MacLifecycleError("upgrade did not preserve owner data")
    events.append({"gate": "upgrade_prior_to_current", "owner_data_preserved": True})

    install_from_dmg(prior, prior_version)
    smoke_installed_app(evidence, "rollback-prior")
    if not upgrade_marker.is_file():
        raise MacLifecycleError("rollback did not preserve owner data")
    events.append({"gate": "rollback_current_to_prior", "owner_data_preserved": True})

    _remove_exact_app()
    if not upgrade_marker.is_file():
        raise MacLifecycleError("final app-only uninstall removed owner data")
    events.append({"gate": "final_uninstall_app_only", "owner_data_preserved": True})

    report = evidence / "macos-lifecycle-evidence.json"
    report.write_text(
        json.dumps(
            {
                "contract": "onyx.macos-lifecycle-evidence.v1",
                "host": {
                    "system": platform.system(),
                    "architecture": platform.machine(),
                    "macos": platform.mac_ver()[0],
                    "minimum_macos": MACOS_MINIMUM_VERSION,
                },
                "current": {
                    "version": current_version,
                    "sha256": current_sha256,
                },
                "prior": {"version": prior_version, "sha256": prior_sha256},
                "events": events,
                "final_app_removed": not APP.exists(),
                "final_launch_agent_removed": not LAUNCH_AGENT.exists(),
                "final_owner_data_preserved": DATA.exists(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run signed/notarized Onyx lifecycle gates on a disposable Mac"
    )
    parser.add_argument("--current-dmg", type=Path, required=True)
    parser.add_argument("--current-sha256", required=True)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--prior-dmg", type=Path, required=True)
    parser.add_argument("--prior-sha256", required=True)
    parser.add_argument("--prior-version", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    run_lifecycle(
        current_dmg=args.current_dmg,
        current_sha256=args.current_sha256,
        current_version=args.current_version,
        prior_dmg=args.prior_dmg,
        prior_sha256=args.prior_sha256,
        prior_version=args.prior_version,
        evidence_dir=args.evidence_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
