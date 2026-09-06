# ONYX-REL-MACOS-1.1.8 - Formal macOS release pipeline

## Status

Ready for native validation - source implementation and Windows-hosted static
validation complete; Apple credentials/host evidence remain external.

## Requirement source

- Owner goal: production-ready Onyx 1.1.8 packages on macOS without weakening
  the existing Windows engine or authority boundary.
- External readiness audit dated 2026-08-03.

## Acceptance criteria

- [x] Apple Silicon support and Intel non-support are explicit and consistent
  with the security-fixed locked Python 3.13 wheel set.
- [x] The app declares a truthful macOS deployment target.
- [x] A formal release fails closed when any Apple signing/notary credential
  is absent.
- [x] Developer ID material is imported into a temporary keychain and removed
  on every workflow outcome.
- [x] Nested code and the app are signed inside-out with hardened runtime and
  reviewed per-process entitlements.
- [ ] On a real Mac, the DMG is signed, submitted with `notarytool --wait`, accepted, stapled,
  verified with `codesign`, `stapler`, `hdiutil`, and assessed with `spctl`.
- [x] Release code emits checksums, an SPDX SBOM, and redacted notary
  evidence bound to the exact DMG.
- [x] Clean install, upgrade, app-only uninstall, reinstall, and rollback have
  a fail-closed disposable-host harness and unit/static coverage.
- [x] Windows-hosted and Linux-container static/focused tests pass.
- [x] Real-Mac, Apple-secret, TCC/audio, and physical lifecycle gates remain
  explicitly unclaimed until executed.

## File list

- `.github/workflows/release-packages.yml`
- `packaging/onyx.spec`
- `packaging/macos/entitlements.plist`
- `packaging/macos/browser-entitlements.plist`
- `scripts/build_release.py`
- `scripts/macos_release.py`
- `scripts/macos_lifecycle_validation.py`
- `requirements.txt`
- `requirements-dev.txt`
- `requirements.lock`
- `docs/INSTALLATION.md`
- `readme.md`
- `docs/onyx/operations/ONYX_1_1_8_MACOS_RELEASE_PIPELINE.md`
- `tests/test_macos_release_pipeline_v1.py`
- `tests/test_native_release_gate_v1.py`

## Evidence boundary

Passing source tests on Windows or Linux establishes only implementation
readiness. It does not establish a macOS build, Developer ID signature,
notarization, Gatekeeper acceptance, TCC behavior, lifecycle acceptance, or
current V19 capability parity on macOS.
