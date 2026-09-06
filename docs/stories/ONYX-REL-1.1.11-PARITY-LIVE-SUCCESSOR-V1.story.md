# Story ONYX-REL-1.1.11-PARITY-LIVE-SUCCESSOR-V1 — Installed Parity and Live Qualification

**Status:** In Progress
**Predecessor:** `ONYX-REFERENCE-FUNCTIONAL-PARITY-V1`
**Release authority:** Release Workflow V76 over immutable V75 (V75/1.1.12 remains the installed rollback predecessor)

## Story

**As the** Cyryx Labs owner,  
**I want** the source-complete Onyx capability set packaged, installed and tested on the real Windows host,  
**so that** parity claims are based on the executable and live integrations rather than source contracts alone.

## Immutable Boundaries

- The accepted V40 HUD, humanoid, QML/Three.js renderer, palette, layout, motion and voice identity are unchanged.
- The product remains **Onyx** and the vendor remains **Cyryx Labs**.
- The successor is an unsigned internal candidate, not a public/formal release.
- Owner data is preserved across upgrade and a rollback copy is created before installed bytes change.
- E-mail/calendar tests are read-only. Social publication requires an exact preview, exact account/target and explicit consent; no public post is inferred from this story.
- Plugin execution remains fail-closed unless the configured native sandbox produces authenticated attestation.
- Implemented, packaged, installed, device-tested and live-provider-tested remain separate evidence states.

## Acceptance Criteria

1. Release Workflow V76 authenticates every successor source, test and release input without rebinding V75, V74 or V73.
2. Onyx 1.1.13 packages the new identity, language, caption, calorie, parity, Docker-attested plugin and canonical lifecycle-version surfaces, and `Onyx.exe --parity-smoke-v1` proves all 35 contracts from frozen package bytes outside the checkout.
3. The Windows bundle, Setup and portable ZIP pass package, native-startup, capability, parity and isolated Setup lifecycle smokes.
4. The existing installed tree and owner data are backed up before upgrade; the installed executable is byte-equal to the accepted bundle executable and a rollback path is recorded.
5. Installed startup, text command, graceful shutdown and relaunch pass without changing the accepted UI or voice.
6. Physical microphone/playback and camera attention are exercised on this host; camera tests retain no raw frames.
7. Plugin status and a bounded execution attempt are tested through the native-sandbox boundary; unavailable sandbox prerequisites are reported as a blocked live gate, never bypassed.
8. Microsoft Graph and/or Google Workspace mail/calendar are tested read-only when owner OAuth state exists; otherwise the exact missing consent/configuration gate is recorded.
9. Social caption/video preview is tested locally. Live upload occurs only to an explicitly designated test/private target after exact consent; absent adapter/OAuth/target leaves the live gate blocked.
10. The parity registry and current release status are updated from receipts and do not claim public eligibility, signing, legal approval or live providers without evidence.

## Tasks / Subtasks

- [x] **Slice 0 — Successor authority and package parity**
  - [x] Add V74, version 1.1.11 and frozen executable parity smoke.
  - [x] Preserve the visual/voice freeze and run focused regression.
- [x] **Slice 1 — Windows artifacts**
  - [x] Build bundle, Setup and portable ZIP with the repository release pipeline.
  - [x] Verify artifact structure, entrypoints, package hygiene and hashes.
- [x] **Slice 2 — Upgrade and rollback**
  - [x] Back up installed application and owner data metadata.
  - [x] Install 1.1.11 and prove bundle-to-install byte identity.
- [ ] **Slice 3 — Installed/device validation**
  - [ ] Package/install 1.1.13, then repeat installed smokes and shutdown/relaunch.
  - [x] Exercise Gemini Live voice, physical microphone/playback, camera calibration and Docker-attested plugin execution.
- [ ] **Slice 4 — Live integrations**
  - [ ] Test read-only mail/calendar under available owner OAuth (blocked: Google unconfigured; Graph onboarding identifiers absent).
  - [x] Test Gemini caption and local H.264 video preview with ffmpeg/ffprobe.
  - [ ] Dispatch only to an exact authorized test target (blocked: no provider adapter, OAuth, account or target supplied).
- [ ] **Slice 5 — Evidence reconciliation**
  - [ ] Record passed, failed, blocked-external and not-run gates without state inflation.

## Testing

- Focused unit/contract tests for V74, packaged parity and bootstrap dispatch.
- Canonical release/package tests plus the full repository suite where feasible.
- Exact artifact hash comparison after installation.
- Physical/live tests produce redacted receipts and retain no raw camera frames, tokens or message bodies.

## Dev Agent Record

### Agent Model Used

- Codex / AEXOS `@dev` (Vulcan)

### Debug Log References

- Gemini Live: 124800 native-audio bytes at 24 kHz, Charon, transcript returned; WAV retained only for acoustic acceptance.
- Physical audio: playback completed; five-second microphone probe passed; capture was not retained.
- Camera: 455 frames processed, 435 normalized observations, calibration `ready`, zero frames retained.
- Plugin: digest-pinned Python 3.13-slim container executed authenticated `test.echo`; network disabled; zero residual containers.
- OAuth: Google `configured=false/connected=false`; Microsoft Graph onboarding identifiers absent.
- Social: Gemini draft plus H.264 720x1280/30 fps/2 s video preview passed; provider dispatch unavailable.

### Completion Notes List

- Corrected the live voice verifier so it initializes production identity/language contracts without reading or mutating owner memory.
- Added a default-off Docker native-sandbox adapter with fresh authenticated attestation, digest-pinned image, read-only mount, no network, dropped capabilities and resource limits.
- Replaced the stale lifecycle version literal discovered after the 1.1.12 install with the canonical `core.version.__version__` source and opened immutable successor 1.1.13/V76.
- Removed the release build's live dependency on `gnu.org` by binding the previously verified LGPL-2.1 evidence as a local, hash-pinned release input; the canonical source URL and legal-review boundary remain explicit.
- Preserved the accepted QML/Three.js humanoid, palette, motion and voice identity unchanged.
- Pytest collection on this host remained anomalously slow before test execution; lint, compile, isolated contracts and live probes are recorded separately rather than inflated into a full-suite pass.

### File List

- `core/capability_expansion_service_v1.py`
- `core/plugin_docker_sandbox_v1.py`
- `core/version.py`
- `docs/stories/ONYX-REL-1.1.11-PARITY-LIVE-SUCCESSOR-V1.story.md`
- `packaging/onyx.spec`
- `packaging/legal-supplements/LGPL-2.1.txt`
- `main.py`
- `scripts/build_release.py`
- `scripts/generate_release_workflow_v75.py`
- `scripts/generate_release_workflow_v76.py`
- `scripts/onyx_plugin_cli.py`
- `scripts/missing_distribution_license_bundle.py`
- `scripts/verify_original_voice_live.py`
- `scripts/verify_release_workflow_v75.py`
- `scripts/verify_release_workflow_v76.py`
- `tests/test_installer_lifecycle_release_identity_v1.py`
- `tests/test_original_voice_contract_v1.py`
- `tests/test_missing_distribution_license_bundle_v1.py`
- `tests/test_plugin_docker_sandbox_v1.py`
- `tests/test_release_workflow_transition_v75.py`
- `tests/test_release_workflow_transition_v76.py`

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-09-01 | 0.1.0 | Created owner-authorized installed parity and live qualification successor. | Chronos (`@sm`) |
| 2026-09-01 | 0.2.0 | Recorded physical/live qualification and opened V75/1.1.12 for the Docker plugin successor. | Vulcan (`@dev`) |
| 2026-09-02 | 0.3.0 | Corrected installed lifecycle version identity and opened V76/1.1.13. | Vulcan (`@dev`) |
| 2026-09-02 | 0.4.0 | Bound LGPL-2.1 evidence locally by verified hash after the authoritative host reset the release build connection. | Polaris (`@devops`) |

## QA Results

In progress. Device/live gates and the 1.1.12 package/install are evidence-backed; OAuth and social dispatch remain blocked by owner/provider configuration, and the lifecycle-version correction requires the 1.1.13 successor package/install gate.
