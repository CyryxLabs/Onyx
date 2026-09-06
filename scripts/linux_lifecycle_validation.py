"""Disposable-host lifecycle acceptance for native Onyx Debian packages.

Run this as the interactive desktop owner on a disposable native Debian-family
host with passwordless non-interactive sudo. The script elevates only the exact
APT package operations; native startup and owner-data checks remain in the
desktop-owner account. It refuses broad paths, links, wrong package identity,
unsealed artifacts, and a non-clean starting host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


PACKAGE = "onyx-ai-assistant"
APP = Path("/opt/cyryx-labs/onyx")
LAUNCHER = Path("/usr/bin/onyx")
DESKTOP = Path("/usr/share/applications/onyx.desktop")
ICON = Path("/usr/share/icons/hicolor/512x512/apps/onyx.png")
USER_UNIT = Path("/usr/lib/systemd/user/onyx.service")
CONFIRMATION = "ONYX_DISPOSABLE_LINUX_LIFECYCLE_V1"
SIGNING_POLICY = "unsigned-approved"
SMOKE_ARGUMENT = "--native-startup-smoke-test"
SMOKE_OUTPUT_ENV = "ONYX_NATIVE_STARTUP_SMOKE_OUTPUT"
SHA256 = re.compile(r"[0-9a-f]{64}")
DEB_NAME = re.compile(
    r"Onyx-(?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)"
    r"-Linux-(?P<architecture>[A-Za-z0-9._-]+)\.deb"
)


class LinuxLifecycleError(RuntimeError):
    """The Linux lifecycle host, artifact, package, or evidence failed closed."""


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def owner_data(environment: dict[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    configured = env.get("XDG_DATA_HOME", "").strip()
    if configured and not Path(configured).is_absolute():
        raise LinuxLifecycleError("XDG_DATA_HOME must be absolute")
    base = _absolute_lexical(Path(configured)) if configured else Path.home() / ".local" / "share"
    return base / "cyryx-labs" / "onyx"


def _unsafe_link(path: Path) -> bool:
    return path.is_symlink()


def _reject_linked_components(path: Path) -> None:
    candidate = _absolute_lexical(path)
    lineage = tuple(reversed(candidate.parents)) + (candidate,)
    for component in lineage:
        if component.is_symlink():
            raise LinuxLifecycleError(f"path contains a symbolic link: {component}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    argv: Sequence[str],
    *,
    environment: dict[str, str] | None = None,
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(argv),
        check=False,
        timeout=timeout,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LinuxLifecycleError(
            f"command failed with exit {result.returncode}: "
            f"{Path(argv[0]).name}: {result.stderr[-1000:]}"
        )
    return result


def _tool(name: str) -> str:
    selected = shutil.which(name)
    if not selected:
        raise LinuxLifecycleError(f"required native tool is unavailable: {name}")
    path = Path(selected)
    if not path.is_file() or path.is_symlink():
        raise LinuxLifecycleError(f"required native tool is unsafe: {name}")
    return str(path.resolve(strict=True))


def require_disposable_host(environment: dict[str, str] | None = None) -> None:
    env = os.environ if environment is None else environment
    if platform.system() != "Linux" or os.name != "posix":
        raise LinuxLifecycleError("native Linux host is required")
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        raise LinuxLifecycleError("run as the desktop owner, not root")
    if env.get("ONYX_DISPOSABLE_LINUX_CONFIRM") != CONFIRMATION:
        raise LinuxLifecycleError(
            "set ONYX_DISPOSABLE_LINUX_CONFIRM to the exact disposable-host token"
        )
    if env.get("ONYX_LINUX_SIGNING_POLICY") != SIGNING_POLICY:
        raise LinuxLifecycleError(
            "set ONYX_LINUX_SIGNING_POLICY to the approved formal-release policy"
        )
    data = owner_data(env)
    _reject_linked_components(data)
    home = _absolute_lexical(Path.home())
    try:
        data.relative_to(home)
    except ValueError as exc:
        raise LinuxLifecycleError("owner-data target must remain beneath the owner home") from exc
    if data in {home, home / ".local", home / ".local" / "share"}:
        raise LinuxLifecycleError("owner-data target is too broad")
    for name in ("sudo", "apt-get", "dpkg-query", "dpkg-deb", "systemctl"):
        _tool(name)
    _run([_tool("sudo"), "-n", "true"], timeout=30)


def require_regular_deb(path: Path, expected_sha256: str, expected_version: str) -> Path:
    candidate = _absolute_lexical(path)
    if not candidate.is_file() or _unsafe_link(candidate):
        raise LinuxLifecycleError(f"DEB is not a regular file: {candidate}")
    _reject_linked_components(candidate)
    match = DEB_NAME.fullmatch(candidate.name)
    if match is None or match.group("version") != expected_version:
        raise LinuxLifecycleError(f"DEB filename/version mismatch: {candidate.name}")
    expected = expected_sha256.casefold()
    if SHA256.fullmatch(expected) is None:
        raise LinuxLifecycleError("expected DEB SHA-256 is malformed")
    if sha256_file(candidate) != expected:
        raise LinuxLifecycleError(f"DEB SHA-256 mismatch: {candidate.name}")
    fields = _run(
        [_tool("dpkg-deb"), "--show", "--showformat=${Package}\n${Version}\n${Architecture}\n", str(candidate)]
    ).stdout.splitlines()
    if len(fields) != 3 or fields[0] != PACKAGE or fields[1] != expected_version:
        raise LinuxLifecycleError("DEB control identity/version is invalid")
    machine = platform.machine().casefold()
    expected_arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if expected_arch is None or fields[2] != expected_arch:
        raise LinuxLifecycleError("DEB architecture does not match the native host")
    return candidate


def require_evidence_directory(path: Path) -> Path:
    candidate = _absolute_lexical(path)
    data = owner_data()
    for managed in (APP, data):
        if candidate == managed or managed in candidate.parents:
            raise LinuxLifecycleError(
                "evidence must be outside application and owner-data paths"
            )
    if candidate.exists() and (candidate.is_symlink() or not candidate.is_dir()):
        raise LinuxLifecycleError("evidence path is not a regular directory")
    _reject_linked_components(candidate)
    candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidate.chmod(0o700)
    return candidate


def installed_version() -> str | None:
    result = subprocess.run(
        [_tool("dpkg-query"), "-W", "-f=${Status}\n${Version}\n", PACKAGE],
        check=False,
        timeout=30,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    lines = result.stdout.splitlines()
    if len(lines) != 2 or lines[0] != "install ok installed":
        raise LinuxLifecycleError("dpkg reports a non-canonical package state")
    return lines[1]


def require_clean_host() -> None:
    managed = (APP, LAUNCHER, DESKTOP, ICON, USER_UNIT, owner_data())
    if installed_version() is not None or any(path.exists() or path.is_symlink() for path in managed):
        raise LinuxLifecycleError(
            "lifecycle host is not clean; package, payload, or owner data exists"
        )


def _require_installed(version: str) -> dict[str, object]:
    observed = installed_version()
    if observed != version:
        raise LinuxLifecycleError(
            f"installed package version mismatch: expected {version}, got {observed}"
        )
    for path in (APP, APP / "Onyx"):
        if path.is_symlink() or not path.exists():
            raise LinuxLifecycleError(f"installed application payload is unsafe: {path}")
    if not APP.is_dir() or not (APP / "Onyx").is_file() or not os.access(APP / "Onyx", os.X_OK):
        raise LinuxLifecycleError("installed Onyx executable is unavailable")
    if not LAUNCHER.is_file() or LAUNCHER.is_symlink() or not os.access(LAUNCHER, os.X_OK):
        raise LinuxLifecycleError("installed launcher is unavailable")
    for path in (DESKTOP, ICON, USER_UNIT):
        if not path.is_file() or path.is_symlink():
            raise LinuxLifecycleError(f"installed desktop integration is unavailable: {path}")
    return {"package": PACKAGE, "version": observed, "executable": str(APP / "Onyx")}


def validate_user_autostart(evidence: Path, label: str) -> dict[str, object]:
    """Enable, observe and remove the package-owned systemd user service."""

    unit = USER_UNIT.read_text(encoding="utf-8")
    required = (
        "ExecStart=/opt/cyryx-labs/onyx/Onyx",
        "WantedBy=default.target",
        "Restart=no",
    )
    if any(value not in unit for value in required):
        raise LinuxLifecycleError("installed user autostart unit drifted")
    systemctl = _tool("systemctl")
    _run([systemctl, "--user", "daemon-reload"], timeout=30)
    _run([systemctl, "--user", "enable", "--now", "onyx.service"], timeout=60)
    try:
        active = _run(
            [systemctl, "--user", "is-active", "onyx.service"], timeout=30
        ).stdout.strip()
        status = _run(
            [systemctl, "--user", "show", "onyx.service", "--property=ActiveState,UnitFileState,MainPID"],
            timeout=30,
        ).stdout
        (evidence / f"systemd-user-{label}.txt").write_text(status, encoding="utf-8")
        if active != "active" or "ActiveState=active" not in status:
            raise LinuxLifecycleError("Onyx systemd user service did not become active")
    finally:
        _run([systemctl, "--user", "disable", "--now", "onyx.service"], timeout=60)
        _run([systemctl, "--user", "daemon-reload"], timeout=30)
    return {
        "manager": "systemd-user",
        "unit": "onyx.service",
        "activated": True,
        "disabled_after_gate": True,
    }


def _apt(action: str, artifact: Path | None, evidence: Path, label: str) -> None:
    if action not in {"install", "remove"}:
        raise LinuxLifecycleError("unsupported package action")
    log = evidence / f"apt-{label}.log"
    environment = os.environ.copy()
    environment["DEBIAN_FRONTEND"] = "noninteractive"
    argv = [_tool("sudo"), "-n", _tool("apt-get"), "-y"]
    if action == "install":
        if artifact is None:
            raise LinuxLifecycleError("install artifact is required")
        argv.extend(["install", str(artifact)])
    else:
        argv.extend(["remove", PACKAGE])
    result = subprocess.run(
        argv,
        check=False,
        timeout=900,
        env=environment,
        capture_output=True,
        text=True,
    )
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise LinuxLifecycleError(
            f"APT {action} failed with exit {result.returncode}: {result.stderr[-1000:]}"
        )


def install_deb(deb: Path, version: str, evidence: Path, label: str) -> dict[str, object]:
    _apt("install", deb, evidence, label)
    return _require_installed(version)


def smoke_installed_app(evidence: Path, label: str) -> dict[str, object]:
    output = evidence / f"native-smoke-{label}.json"
    environment = os.environ.copy()
    environment["ONYX_DATA_DIR"] = str(owner_data())
    environment[SMOKE_OUTPUT_ENV] = str(output)
    _run([str(LAUNCHER), SMOKE_ARGUMENT], environment=environment)
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LinuxLifecycleError(f"installed startup smoke is invalid: {label}") from exc
    if payload.get("status") != "passed" or payload.get("system") != "Linux":
        raise LinuxLifecycleError(f"installed startup smoke failed: {label}")
    return payload


def uninstall_app(evidence: Path, label: str) -> None:
    _apt("remove", None, evidence, label)
    deadline = time.monotonic() + 45.0
    while (APP.exists() or LAUNCHER.exists()) and time.monotonic() < deadline:
        time.sleep(0.1)
    if installed_version() is not None or any(
        path.exists() or path.is_symlink()
        for path in (APP, LAUNCHER, DESKTOP, ICON, USER_UNIT)
    ):
        raise LinuxLifecycleError("package uninstall left application-owned payload")


def _write_marker(name: str, content: str) -> Path:
    data = owner_data()
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    if data.is_symlink() or not data.is_dir():
        raise LinuxLifecycleError("owner-data marker target is unsafe")
    data.chmod(0o700)
    marker = data / name
    marker.write_text(content, encoding="utf-8")
    return marker


def _require_marker(marker: Path, content: str, gate: str) -> None:
    try:
        observed = marker.read_text(encoding="utf-8")
    except OSError as exc:
        raise LinuxLifecycleError(f"owner data missing after {gate}") from exc
    if observed != content:
        raise LinuxLifecycleError(f"owner data changed after {gate}")


def _reset_disposable_owner_data() -> None:
    data = owner_data()
    if not data.exists():
        return
    if data.is_symlink() or not data.is_dir():
        raise LinuxLifecycleError("owner-data reset target is unsafe")
    shutil.rmtree(data)
    if data.exists():
        raise LinuxLifecycleError("owner-data reset left residual bytes")


def run_lifecycle(
    *,
    current_deb: Path,
    current_sha256: str,
    current_version: str,
    prior_deb: Path,
    prior_sha256: str,
    prior_version: str,
    evidence_dir: Path,
) -> Path:
    require_disposable_host()
    if not current_version or not prior_version or current_version == prior_version:
        raise LinuxLifecycleError("current and prior release versions must be distinct")
    current = require_regular_deb(current_deb, current_sha256, current_version)
    prior = require_regular_deb(prior_deb, prior_sha256, prior_version)
    evidence = require_evidence_directory(evidence_dir)
    require_clean_host()
    events: list[dict[str, object]] = []

    install = install_deb(current, current_version, evidence, "clean-current")
    events.append({"gate": "clean_install_current", "install": install, "smoke": smoke_installed_app(evidence, "clean-current"), "autostart": validate_user_autostart(evidence, "clean-current")})
    marker = _write_marker("lifecycle-owner-data-marker.txt", "owner-data-must-survive\n")

    uninstall_app(evidence, "current")
    _require_marker(marker, "owner-data-must-survive\n", "app-only uninstall")
    events.append({"gate": "uninstall_app_only", "owner_data_preserved": True})

    install_deb(current, current_version, evidence, "reinstall-current")
    smoke_installed_app(evidence, "reinstall-current")
    _require_marker(marker, "owner-data-must-survive\n", "same-version reinstall")
    events.append({"gate": "reinstall_current", "owner_data_preserved": True})

    uninstall_app(evidence, "reset-current")
    _reset_disposable_owner_data()
    install_deb(prior, prior_version, evidence, "clean-prior")
    smoke_installed_app(evidence, "clean-prior")
    upgrade_marker = _write_marker("lifecycle-upgrade-marker.txt", "upgrade-data-must-survive\n")

    install_deb(current, current_version, evidence, "upgrade-current")
    smoke_installed_app(evidence, "upgrade-current")
    _require_marker(upgrade_marker, "upgrade-data-must-survive\n", "upgrade")
    events.append({"gate": "upgrade_prior_to_current", "owner_data_preserved": True})

    uninstall_app(evidence, "rollback-current")
    _require_marker(upgrade_marker, "upgrade-data-must-survive\n", "rollback uninstall")
    install_deb(prior, prior_version, evidence, "rollback-prior")
    smoke_installed_app(evidence, "rollback-prior")
    _require_marker(upgrade_marker, "upgrade-data-must-survive\n", "rollback")
    events.append({"gate": "rollback_current_to_prior", "owner_data_preserved": True})

    uninstall_app(evidence, "final-prior")
    _require_marker(upgrade_marker, "upgrade-data-must-survive\n", "final uninstall")
    events.append({"gate": "final_uninstall_app_only", "owner_data_preserved": True})

    report = evidence / "linux-lifecycle-evidence.json"
    report.write_text(
        json.dumps(
            {
                "contract": "onyx.linux-lifecycle-evidence.v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "host": {
                    "system": platform.system(),
                    "architecture": platform.machine(),
                    "release": platform.release(),
                    "version": platform.version(),
                },
                "package": PACKAGE,
                "signing_policy": SIGNING_POLICY,
                "current": {"version": current_version, "sha256": current_sha256.casefold()},
                "prior": {"version": prior_version, "sha256": prior_sha256.casefold()},
                "events": events,
                "final_app_removed": not APP.exists(),
                "final_package_removed": installed_version() is None,
                "final_owner_data_preserved": owner_data().exists(),
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
        description="Run Onyx DEB lifecycle gates on a disposable native Linux desktop"
    )
    parser.add_argument("--current-deb", type=Path, required=True)
    parser.add_argument("--current-sha256", required=True)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--prior-deb", type=Path, required=True)
    parser.add_argument("--prior-sha256", required=True)
    parser.add_argument("--prior-version", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    run_lifecycle(
        current_deb=args.current_deb,
        current_sha256=args.current_sha256,
        current_version=args.current_version,
        prior_deb=args.prior_deb,
        prior_sha256=args.prior_sha256,
        prior_version=args.prior_version,
        evidence_dir=args.evidence_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
