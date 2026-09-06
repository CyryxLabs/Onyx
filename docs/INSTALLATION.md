# Onyx installable releases

This document defines the target contract for self-contained Onyx desktop
releases. The current engineering candidate is **Onyx 1.2.0**. Its current
evidence-layer authority is `onyx/CURRENT_CAPABILITY_STATUS_V2.md`: the candidate
is source-only, with packaging and installation pending. The installed
predecessor is **Onyx 1.1.31 / V96**. The candidate is
**unsigned-untrusted, not released, and unverified against live providers**.
The unchanged `onyx/CURRENT_RELEASE_STATUS.md` remains the historical formal
**1.1.9 R15B NO-GO** and must not be read as the current 1.2.0 status. A listed
filename is not evidence that a current package exists. Once qualified, end users do not need
Python, pip, a virtual environment, or a separate Chromium installation. The
release bundle includes the Python runtime, application dependencies and the
single Playwright Chromium browser used by Onyx.

## Release artifacts

| Platform | Artifact | Architecture |
|---|---|---|
| Windows | `Onyx-<version>-Windows-x64-Setup.exe` | x64 |
| Windows | `Onyx-<version>-Windows-x64-Portable.zip` | x64 |
| macOS 15+ | `Onyx-<version>-macOS-arm64.dmg` | Apple Silicon, native |
| Linux | `Onyx-<version>-Linux-<arch>.deb` | x64 and arm64 |
| Linux | `Onyx-<version>-Linux-<arch>.AppImage` | x64 and arm64 |
| Linux | `Onyx-<version>-Linux-<arch>.tar.gz` | x64 and arm64 |

These are target artifact names. Every qualifying build also emits a platform
manifest and SHA-256 checksum file.

## Automated native builds

Only after the current source-freeze gate is GO, run the GitHub Actions workflow
**Release packages** manually, or push an approved tag such as `v1.2.0`. The workflow uses
a native runner for every target because a PyInstaller bundle cannot be
cross-compiled safely:

- Windows x64;
- macOS 15 or newer on Apple Silicon;
- Linux x64;
- Linux arm64.

A tag build may create or update the corresponding GitHub Release only after
every formal workflow gate passes; failure must leave publication closed. A
manual workflow run keeps artifacts on the workflow run for validation.

## Local diagnostic build

Create and activate a Python 3.13 virtual environment, then run:

```bash
python -m pip install --require-hashes -r requirements.lock
python scripts/build_release.py --version 1.2.0
```

Additional host requirements:

- Windows: Inno Setup 6 (`ISCC.exe`).
- macOS: Xcode command-line tools (`codesign`, `hdiutil`, `notarytool`,
  `stapler`, `spctl`, `lipo`) on a native Apple Silicon macOS 15+ host.
  Security-fixed `cryptography` 48+ releases no longer publish an Intel macOS
  wheel. The candidate therefore targets Apple Silicon only; formal macOS jobs
  refuse source-built dependency fallbacks rather than ship a vulnerable pin
  or an unreproducible local Rust/OpenSSL build.
- Linux: `dpkg-deb` and a verified executable `appimagetool`. A formal Linux
  release fails before packaging when AppImage tooling is absent. The explicit
  `--diagnostic-without-appimage` escape hatch is only for local diagnostics;
  it marks the release manifest `diagnostic-incomplete` and is not releasable.
  The DEB declares its desktop runtime libraries, including `libegl1`, and the
  release gate installs it with `apt` in a clean Debian 12 image before running
  the packaged, provider-free native startup smoke.

The release workflow downloads the official `appimagetool` 1.9.1 assets for
x86_64 and arm64 and verifies architecture-specific SHA-256 digests that are
pinned in the workflow. It also downloads the AppImage type-2 runtime, verifies
its architecture-specific pinned digest, and passes it explicitly through
`--runtime-file`; `appimagetool` is therefore unable to fetch an unverified
runtime during packaging. The runtime project's download path is named
`continuous`, but the accepted bytes are immutable from Onyx's perspective
because both the workflow and build script fail closed on the exact digest.
Changing the tool version or any digest is a reviewed release-configuration
change.

The build performs a frozen-application smoke test before creating an installer.
It fails if the prompt, dashboard assets, executable or writable data layout is
missing.

## Signing and trust

Windows and macOS signing credentials are intentionally not stored in the
repository. A tag build is formal. A manual build becomes formal when
`formal_release` is selected. Formal macOS jobs fail before packaging unless
all of these GitHub Actions secrets are configured:

- Windows Authenticode signing after Inno Setup produces the installer;
- `APPLE_TEAM_ID`;
- `APPLE_DEVELOPER_ID_P12_BASE64`;
- `APPLE_DEVELOPER_ID_P12_PASSWORD`;
- `APPLE_NOTARY_KEY_P8_BASE64`;
- `APPLE_NOTARY_KEY_ID`;
- `APPLE_NOTARY_ISSUER_ID`.

The workflow imports the Developer ID Application certificate into a temporary
keychain, derives the exact team-bound identity, and deletes the certificate,
notary key and keychain on every outcome. The app is signed inside-out with
hardened runtime and per-process entitlements. The app and DMG are submitted
with `notarytool --wait`, stapled, verified with `codesign`/`hdiutil`, and
assessed with `spctl`. Each architecture emits a checksum, SPDX inventory and
redacted notary evidence. A local build without `--formal-release` is ad-hoc,
is marked `diagnostic-incomplete`, and is not a distribution candidate.

## macOS lifecycle qualification

Full lifecycle acceptance is deliberately separate from packaging because it
modifies `/Applications/Onyx.app` and requires a disposable physical Mac plus
an accepted prior signed/notarized DMG. After both DMG hashes are independently
recorded, run:

```bash
export ONYX_DISPOSABLE_MAC_CONFIRM=ONYX_DISPOSABLE_MAC_LIFECYCLE_V1
python scripts/macos_lifecycle_validation.py \
  --current-dmg ~/Downloads/Onyx-1.2.0-macOS-arm64.dmg \
  --current-sha256 <exact-current-sha256> \
  --current-version 1.2.0 \
  --prior-dmg ~/Downloads/Onyx-<prior>-macOS-arm64.dmg \
  --prior-sha256 <exact-prior-sha256> \
  --prior-version <prior> \
  --evidence-dir ~/Desktop/onyx-macos-lifecycle-evidence
```

The harness requires quarantine, Developer ID/Gatekeeper acceptance, exact
hashes, a clean starting state and an evidence directory outside Onyx paths. It proves clean install, app-only
uninstall, reinstall, upgrade, rollback and owner-data preservation. It backs
up owner data before its controlled fresh-state transition and never acts as a
general uninstaller.

## Writable owner data

Installed program files are immutable. Onyx stores owner-controlled runtime
data in the native per-user location:

- Windows: `%LOCALAPPDATA%\Cyryx Labs\Onyx`;
- macOS: `~/Library/Application Support/Cyryx Labs/Onyx`;
- Linux: `${XDG_DATA_HOME:-~/.local/share}/cyryx-labs/onyx`.

These locations contain non-secret configuration, local memory, audit records,
certificates and uploaded files. The Gemini key remains in Windows Credential
Manager, macOS Keychain or Linux Secret Service. Set `ONYX_DATA_DIR` only for
portable testing or managed deployments.

## First launch

1. Install and open Onyx.
2. Enter the owner's name and Gemini API key.
3. Grant microphone access.
4. On macOS, grant Camera and Screen Recording permissions only if those tools
   are required.
5. On Linux, ensure a Secret Service session is available; the Debian package
   installs `libsecret-tools` as a dependency.

## Legacy source-checkout data

This packaging phase deliberately does not migrate every writable file from an
older source checkout into the installed application's data directory. Narrow
certificate, browser-profile and scheduler compatibility remains in runtime
code. A broader frozen-install migration is a separate packaging task so owner
data is never moved or deleted without a versioned, recoverable migration.
