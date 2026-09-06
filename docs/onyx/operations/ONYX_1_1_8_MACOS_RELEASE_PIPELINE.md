# Onyx 1.1.8 macOS release pipeline

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as the 1.1.8 pipeline
> design record; it is not native macOS evidence for the current candidate.
> See [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

**Source implementation date:** 2026-08-03  
**Support contract:** native Apple Silicon, macOS 15.0+  
**Current verdict:** pipeline implementation ready for native execution; no
macOS production release is claimed.

## Implemented contract

- The release matrix uses the official `macos-15` Apple Silicon runner.
- `LSMinimumSystemVersion` and `MACOSX_DEPLOYMENT_TARGET` are fixed to the
  truthful supported floor `15.0`.
- The security floor for `cryptography` is 48.0.1 and the exact lock currently
  resolves 50.0.0. These releases publish an arm64 macOS wheel but no Intel
  wheel. The only Intel-compatible reviewed pin found (46.0.7) is affected by
  GHSA-537c-gmf6-5ccf, while a local Rust/OpenSSL source build is not yet a
  reproducible release input. Onyx 1.1.8 therefore does not advertise Intel.
  macOS installation uses `--only-binary=:all:` and fails rather than compiling
  an unreviewed native dependency.
- Formal tag/manual jobs require the six Apple secret inputs, import Developer
  ID material into a temporary keychain, and destroy temporary material under
  `always()` cleanup.
- Formal packaging verifies bundle metadata and every Mach-O architecture,
  signs nested code inside-out with hardened runtime, applies browser JIT
  exceptions only to Chromium/Playwright paths, and keeps them off the Onyx
  parent.
- The signed app is notarized and stapled before it enters the DMG. The DMG is
  then signed, separately notarized, stapled, verified and Gatekeeper-assessed.
- Notary submissions and logs are retained without credential bytes. Any
  status other than `Accepted`, invalid JSON, missing log, or non-empty issue
  list fails the build.
- The architecture release includes exact checksums, a host manifest, bundle
  inventory, build-input seal, redacted signing/notary evidence and an SPDX
  technical inventory.
- A disposable-host lifecycle harness binds exact current/prior DMG hashes and
  covers clean install, app-only uninstall, reinstall, upgrade, rollback and
  owner-data preservation.

## Evidence that remains external

The source implementation cannot establish any of the following from the
current Windows host:

1. successful native arm64 PyInstaller/DMG creation;
2. successful import of a real Cyryx Labs Developer ID Application identity;
3. Apple notary acceptance, tickets, logs or Gatekeeper results;
4. a quarantined first run on a separate physical Mac;
5. microphone, original Gemini Live/Charon voice, camera, Screen Recording,
   Accessibility, Apple Events, Keychain or embedded Chromium TCC behavior;
6. full lifecycle evidence, because no accepted prior signed/notarized Onyx
   macOS DMG currently exists;
7. long-session resource/reconnect/quit/restart behavior;
8. current V19 capability parity. The present macOS activation contract remains
   capability-limited until the separate descriptor-bound POSIX governance
   work is completed and accepted.

Production macOS status remains NO-GO until those exact-artifact gates pass on
real Apple Silicon Macs and an independent reviewer reconciles the
distributed DMG hashes to the build-input seals and evidence.

## Primary dependency evidence

- PyPI cryptography 50.0.0 release metadata:
  https://pypi.org/pypi/cryptography/50.0.0/json
- Apple notarization overview:
  https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution
- GitHub-hosted runner architectures:
  https://docs.github.com/en/actions/reference/runners/github-hosted-runners
