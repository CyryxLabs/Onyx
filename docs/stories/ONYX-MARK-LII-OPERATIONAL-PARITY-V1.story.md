# Story ONYX-MARK-LII-OPERATIONAL-PARITY-V1 — Mark LII Operational Parity and V24 Startup Recovery

**Status:** In Progress
**Reference snapshot:** `FatihMakes/Mark-LI` commit `234dd792737f3acd38ca836aadae94c24ef0ad56` (functional parent `c131a1b4f72e477bd4c6735142f3aaee36acc792`)
**Predecessor:** `ONYX-REFERENCE-FUNCTIONAL-PARITY-V1`

## Story

**As the** Cyryx Labs owner,  
**I want** Onyx to provide operational equivalents for every non-visual capability in the current reference snapshot,  
**so that** the installed assistant performs those workflows while preserving the accepted humanoid experience and Cyryx governance.

## Immutable Boundaries

- Preserve the accepted desktop and mobile layout, Three.js/QML humanoid, palette, typography, controls, motion and visual assets byte-for-byte unless a narrowly scoped defect fix is separately authorized.
- Never introduce an orb, static-avatar replacement, foreign branding, foreign prompts, third-party implementation code, or third-party license text.
- Implement from public behavioral requirements using original Onyx-owned contracts.
- CLI is the first operational surface. Existing UI may consume new contracts later without being redesigned.
- `implemented`, `tested`, `packaged`, `installed`, `physical-device verified`, `OAuth/account verified`, and `live-provider verified` remain distinct.
- Existing approval, permission, audit, secret-handling and rollback boundaries may be stricter than the reference and must not be weakened for behavioral similarity.

## Acceptance Criteria

1. A normal installed launch accepts the empty argument emitted by Windows shortcut/process forwarding while continuing to reject every unknown non-empty argument; V24 diagnostic exact-argument gates remain unchanged.
2. Owner-selectable Gemini voices support exactly `Charon`, `Puck`, `Kore`, `Fenrir`, and `Aoede`, persist locally, rotate a live session safely, and preserve or deliberately reset context according to a tested contract.
3. Audio-device discovery returns a deduplicated usable input/output list, persists selections by stable name rather than volatile index, probes devices in the same stream mode used by Onyx, and safely falls back to the OS default with an observable reason.
4. Local memory can be listed, searched and individually forgotten through an owner-controlled CLI without exposing secrets or changing the HUD layout.
5. A bounded session undo journal reverses supported Onyx file and setting mutations, refuses unsafe/stale reversals, and never lets the model forge owner confirmation.
6. Irreversible power/network actions require a locally issued, single-use, action-bound owner confirmation. Existing stronger governance remains authoritative.
7. Existing real-audio humanoid reactivity, session continuity, plugins, repetition counting, calorie tracking, social-video handling and all previously represented capabilities remain passing without visual-source changes.
8. The parity registry is updated against the exact reference snapshot and reports each capability by source, host, test, package, installed, device/account and live-provider state.
9. A successor package is built and locally installed only after focused, regression, provenance, layout-freeze, security and lifecycle gates pass. Public/formal release remains blocked unless Authenticode is valid.

## Tasks / Subtasks

- [x] **Slice 0 — Reproduce and bind scope**
  - [x] Reproduce the installed V24 empty-argument failure from the observed command line.
  - [x] Bind the exact reference commits and immutable visual boundary.
- [x] **Slice 1 — Startup recovery**
  - [x] Normalize only empty Windows launch arguments at the stable bootstrap.
  - [x] Add adversarial tests proving unknown arguments still fail closed.
- [x] **Slice 2 — Runtime parity contracts**
  - [x] Voice selection and safe live rotation.
  - [x] Audio-device discovery, probe, persistence and fallback.
  - [x] Memory owner CLI and complete bounded undo.
  - [x] Locally issued irreversible-action confirmations.
- [x] **Slice 3 — Composition and parity evidence**
  - [x] Wire contracts into the existing host without layout changes.
  - [x] Update the exact-snapshot parity registry and CLI report.
- [ ] **Slice 4 — QA, package and installed/live proof**
  - [x] Run focused and canonical regression gates plus visual hash freeze.
  - [x] Build/install successor and execute normal/empty-argument startup smokes.
  - [ ] Execute physical voice/audio/camera and authorized provider checks where credentials/devices are available.
- [ ] **Slice 5 — Installed conversational reliability and reachable parity**
  - [x] Reproduce silent text loss and microphone blocking across Gemini transport rotation.
  - [x] Retain bounded typed commands while disconnected and retry only before any provider response/action begins.
  - [x] Make shipped local wellness, clipboard, plugin, caption, video-inspection and camera repetition paths reachable through the conversational capability dispatcher without changing visual sources.
  - [x] Recover installed startup when persisted absolute workspace roots are represented as configuration strings.
  - [ ] Replace denial-only parity evidence with positive operational source/package/installed receipts.
  - [ ] Build, install and physically validate the successor against text, voice, camera and local parity workflows.

## Testing

- Exact argv characterization and packaged launch tests.
- Pure contract tests for voice, devices, memory, undo and confirmation.
- Existing voice-continuity, permission, file, settings, plugin, social and humanoid regressions.
- Package/install/lifecycle smoke with exact artifact hashes.

## Dev Agent Record

### Agent Model Used

- Codex / AEXOS `@dev` (Vulcan)

### Debug Log References

- Installed process inventory showed both `Onyx.exe` and `Onyx.exe ""`; V24 rejected the latter because `sys.argv[1:] == [""]` was not an accepted invocation.
- Isolated startup/audio parity gate: 9 passed.
- Relevant original voice/continuity/rotation regression: 46 passed, 110 deselected.
- Installed exact-argv smoke `Onyx.exe "" --preflight-only`: exit 0 after the local V24 hotfix.
- Stable focused parity gate: 101 passed, 15 subtests passed; the sole failure exposed underscore-delimited memory-key discovery and was corrected. Its isolated regression then passed.
- Physical callback-mode audio probe enumerated two usable inputs and four usable outputs on the owner's Windows host.
- Regression/visual audit: 131 passed, 230 subtests passed; five stale authorities were identified and reconciled to 34 governed tools plus HUD V42/package V11/renderer V16 and the required same-origin mobile humanoid frame.
- Final combined pre-build gate after all corrections: 239 passed, 245 subtests passed in 250.63s.
- Temporal verifier no longer initializes `pywinauto/comtypes` during pure analysis or test collection; native COM setup is deferred to explicit physical capture.
- First 1.1.19 package attempt reached packaged parity smoke and correctly failed because the build gate retained the historical 35-capability count; the gate was updated to the authenticated 42-capability registry before retry.
- Second package attempt passed the packaged parity, native UI, governance, Founder, DayOps and artifact-structure gates, then exposed a non-suppressible legacy-resident message box in the isolated Setup smoke. The installed Onyx process was closed by exact PID, the smoke timeout gained exact-tree cleanup, and all installer refusal messages became silent-mode-safe without weakening the fail-closed lifecycle decision.
- The corrected real Setup smoke passed isolated install, native V24 startup with `cinematic-v5`, and uninstall/cleanup for 1.1.19.
- The upstream `main` advanced to `234dd792...` only by deleting its upload-video and push-up-counter modules. Onyx retains governed equivalents and therefore remains a functional superset without importing or removing visual behavior.
- Local FFmpeg 7.1.1 generated a real MP4 that passed Onyx video inspection and digest-bound publication preview.
- Docker Desktop answered through its local engine. A Cyryx test-only plugin was installed, enabled and executed in a no-network/read-only container pinned to `sha256:b64631e...`; Unicode payload round-trip passed while default-off production policy remained intact.
- The exact installed 1.1.19 executable accepted `Onyx.exe ""`, remained alive for 20 seconds, and closed cooperatively with no V24 traceback. Successor 1.1.20 binds the refreshed upstream snapshot.
- Refreshed V83/parity/bootstrap/video/plugin focused gate: 48 passed in 190.88s using an isolated workspace basetemp; the first attempt was infrastructure-only `WinError 5` on the global pytest temp root.
- Audio playback diagnosis proved a deterministic discontinuity: 2400-byte provider slices were submitted serially to 2048-byte PortAudio callbacks, forcing zero-filled gaps while the asyncio loop waited up to 20 ms before submitting the next slice.
- V84 pipelines up to 16 bounded speech slices, preserves callback-thread ownership, explicitly discards the native buffer on interrupt, and treats PortAudio's transient `output_underflow` status as observable/recoverable instead of permanently stopping playback.
- Audio/lifecycle focused gate: 39 passed. Humanoid desktop/mobile visual-freeze gate: 25 passed. Combined voice, lifecycle, Gemini compatibility, latency and visual regression gate: 98 passed; scoped Ruff gate passed.
- The stale Gemini compatibility AST assertion now authenticates `system_instruction` in the real `live_config_kwargs` payload expanded into `LiveConnectConfig`, matching the already-working runtime contract.
- Argus identified and Vulcan closed the residual interrupt/new-turn race: every playback receipt now has a monotonic sequence, and discard applies only through the exact causal cutoff captured by the owner interrupt. The expanded audio/lifecycle gate passed 74 tests.
- A second adversarial QA pass exposed a producer/callback interleaving between sequence allocation and queue publication. V85 linearizes publication and cutoff capture without locking the realtime callback; the deterministic concurrent regression and focused gate pass.
- V86 adds a trusted local voice selector to the existing Setup surface. It loads and persists the current Gemini Live voice through the existing preference contract and preserves automatic live-session rotation without changing the humanoid or primary HUD.
- HUD V43 and packaged HUD V12 authenticate the narrow Setup delta while retaining byte-identical Three.js, QML humanoid, palette and primary-layout inputs from V42/V11. Focused selector/acceptance/release validation passed 10 tests; scoped Ruff passed.
- Installed-log analysis exposed text turns silently discarded while Gemini Live was reconnecting and a pending microphone latch surviving transport rotation. V92 adds a bounded ordered queue, one retry only before any provider response/action, an eight-second first-response deadline, and explicit release after the retry instead of leaving Onyx blocked.
- The historical capability smoke proved only that seventeen default-off ports denied dispatch. V92 retains that negative boundary and adds nine positive brokered receipts across the installed local plugin, clipboard, wellness/calorie, repetition, personalization and social-caption paths; external publication remains explicitly `oauth-adapter-required`.
- Focused source gates after the V92 correction passed 28 continuity/queue tests, then 161 tests plus 233 subtests across voice rotation, capability expansion, regression, HUD and packaged-runtime contracts. The accepted `ui.py` SHA-256 remains unchanged.
- Installed V92 exposed a real startup regression that package smokes did not cover: persisted absolute workspace roots are JSON strings, while the social-video broker intentionally accepts only absolute `Path` objects. The service now normalizes its documented `Path | str` boundary before the broker applies canonical absolute, existence and symlink policy; a real-config constructor probe and regression cover the installed shape.
- Runtime-construction failures now emit their complete local traceback to the existing startup log while preserving the bounded owner-facing recovery message and fail-closed lifecycle status.
- The current native-release fixture now derives every required humanoid HUD manifest from the packaging authority, closing the V9-only fixture drift while preserving all V10-V13 runtime requirements.
- Installed V93 live validation measured text acceptance at 1.9 ms and first Gemini audio at 1083.6 ms, proved Setup remained open, and exposed two residual lifecycle defects: configured Setup had no non-mutating return path, and cancelled Uvicorn lifespan tasks printed false-error tracebacks during a successful owner exit.
- V94 adds an Escape-only dismissal path when Setup was opened from an already-configured runtime, while first-boot Setup remains mandatory. It also disables FastAPI lifespan orchestration for both dashboard servers because the app defines no lifespan handlers; owned task cancellation and dashboard behavior remain unchanged.
- V95 reproduced the installed V24 crash from a Desktop shortcut whose argument field contained the literal pair `""`. The stable and V24 bootstraps now normalize only the sole semantic empty argument, while mixed, whitespace and unknown arguments remain fail-closed; both runtime and installer shortcut producers now emit a truly empty argument field.
- HUD V46 and packaged HUD V15 authenticate the non-visual shortcut correction while preserving the exact Three.js/QML humanoid, palette, layout and voice inputs. Current focused gate: 34 passed.
- The exact 27-file capability evidence matrix passed 489 tests plus 293 subtests with one platform/precondition skip. The extended AEXOS/learning/opportunity/Google/Graph/social/mobile/latency matrix passed 708 tests with four platform/precondition skips.
- Extended QA exposed a Windows long-path defect in the Google durable witness temp. V95 binds extended native filesystem paths for open, validation, replacement and cleanup; the Google host suite passed 94 tests with three platform skips, and the refreshed authenticated activation closure passed 50 tests.

### Completion Notes List

- V24 now treats only exact empty Windows argv entries as omitted arguments. Whitespace and unknown switches remain untouched and fail closed.
- Five Gemini Native Audio voices and measured name-stable audio-device contracts are implemented and host-wired without visual changes; broader parity and package gates remain open.
- Owner memory discovery now matches natural partial searches against underscore-delimited named keys while preserving local storage, privacy and bounded retrieval.
- Undo is session-local, bounded, stale-state-aware and refuses unsupported irreversible recovery; confirmation digests are nonce-bound, expiring and single-use.
- The exact-snapshot registry contains 42 non-visual capabilities and explicitly excludes the reference orb/layout/theme from scope.
- Setup now exposes all five supported Gemini Live voices and persists the owner selection through the existing governed preference contract; no provider, audio, humanoid or primary-HUD behavior was changed.
- Typed commands now survive a normal Gemini transport rotation, preserve order, never replay after tool/audio/text output begins, and cannot keep the microphone blocked indefinitely when Gemini remains silent.
- Mark-parity local capabilities are enabled in the installed host unless explicitly opted out and are reachable through the existing conversational dispatcher; live social mutation still requires an authorized official adapter and account.
- Shortcut creation now writes no argument characters for a frozen direct launch, Setup removes its stale application-owned Desktop link before recreation, and bootstraps retain bounded compatibility for an already malformed historical `""` link.
- Google Workspace host and authenticated source activation are locally tested again, including Windows long paths, but Gmail/Calendar remain default-off until the owner supplies OAuth configuration and completes consent.

### File List

- `docs/stories/ONYX-MARK-LII-OPERATIONAL-PARITY-V1.story.md`
- `scripts/bootstrap_onyx.pyw`
- `scripts/bootstrap_onyx_live_v24.pyw`
- `core/audio_contract.py`
- `core/live_voice_preference_v1.py`
- `core/audio_device_selection_v1.py`
- `core/capability_expansion_runtime_v1.py`
- `core/capability_expansion_service_v1.py`
- `core/live_voice_continuity_v1.py`
- `core/undo_journal_v1.py`
- `core/capability_parity_v1.py`
- `core/permission_broker.py`
- `core/version.py`
- `core/onyx_hud_current_acceptance_v43.py`
- `core/onyx_hud_current_acceptance_v45.py`
- `core/onyx_packaged_runtime_hud_contract_v12.py`
- `core/onyx_packaged_runtime_hud_contract_v12.manifest.json`
- `core/onyx_packaged_runtime_hud_contract_v14.py`
- `core/onyx_packaged_runtime_hud_contract_v14.manifest.json`
- `actions/computer_settings.py`
- `actions/file_controller.py`
- `memory/memory_manager.py`
- `memory/store.py`
- `scripts/onyx_audio_cli.py`
- `scripts/onyx_capabilities_cli.py`
- `scripts/onyx_parity_cli.py`
- `scripts/build_release.py`
- `scripts/package_hygiene.py`
- `scripts/generate_release_workflow_v82.py`
- `scripts/verify_release_workflow_v82.py`
- `scripts/generate_release_workflow_v83.py`
- `scripts/verify_release_workflow_v83.py`
- `scripts/generate_release_workflow_v84.py`
- `scripts/verify_release_workflow_v84.py`
- `scripts/generate_release_workflow_v85.py`
- `scripts/verify_release_workflow_v85.py`
- `scripts/generate_release_workflow_v86.py`
- `scripts/verify_release_workflow_v86.py`
- `scripts/generate_release_workflow_v92.py`
- `scripts/verify_release_workflow_v92.py`
- `scripts/generate_release_workflow_v93.py`
- `scripts/verify_release_workflow_v93.py`
- `scripts/generate_release_workflow_v94.py`
- `scripts/verify_release_workflow_v94.py`
- `scripts/verify_humanoid_temporal_stability_v1.py`
- `docs/onyx/ONYX_FUNCTIONAL_PARITY_V1.md`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V43-E6-001.manifest.json`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V45-E6-001.manifest.json`
- `dashboard/server.py`
- `main.py`
- `ui.py`
- `packaging/onyx.spec`
- `packaging/windows/onyx.iss`
- `tests/test_bootstrap_empty_windows_argument_v1.py`
- `tests/test_mark_lii_audio_parity_v1.py`
- `tests/test_mark_lii_undo_confirmation_parity_v1.py`
- `tests/test_capability_parity_v1.py`
- `tests/test_live_audio_stream_ownership_v1.py`
- `tests/test_regressions.py`
- `tests/test_hud_source_frozen_selection_v1.py`
- `tests/test_onyx_hud_current_acceptance_v42.py`
- `tests/test_onyx_hud_current_acceptance_v43.py`
- `tests/test_onyx_hud_current_acceptance_v44.py`
- `tests/test_onyx_hud_current_acceptance_v45.py`
- `tests/test_packaged_runtime_hud_contract_v11.py`
- `tests/test_packaged_runtime_hud_contract_v12.py`
- `tests/test_packaged_runtime_hud_contract_v13.py`
- `tests/test_packaged_runtime_hud_contract_v14.py`
- `tests/test_voice_selection_ui_v1.py`
- `tests/test_onyx_humanoid_entity_v10.py`
- `tests/test_release_workflow_transition_v82.py`
- `tests/test_release_workflow_transition_v83.py`
- `tests/test_release_workflow_transition_v84.py`
- `tests/test_release_workflow_transition_v85.py`
- `tests/test_release_workflow_transition_v86.py`
- `tests/fixtures/release_workflow_transition_v84.json`
- `tests/fixtures/release_workflow_transition_v85.json`
- `tests/fixtures/release_workflow_transition_v86.json`
- `tests/test_runtime_shutdown_hardening_v1.py`
- `tests/test_phase6_gemini_live_compat_v1.py`
- `tests/test_capability_expansion_service_v1.py`
- `tests/test_live_text_reliability_v1.py`
- `tests/test_onyx_capabilities_cli.py`
- `tests/test_release_runtime_closure_v2.py`
- `tests/test_release_workflow_transition_v92.py`
- `tests/test_release_workflow_transition_v93.py`
- `tests/test_release_workflow_transition_v94.py`
- `tests/fixtures/release_workflow_transition_v94.json`
- `tests/test_dashboard_shutdown_v1.py`
- `tests/test_runtime_construction_transaction_v1.py`
- `tests/test_native_release_gate_v1.py`
- `tests/test_text_command_latency_v1.py`
- `core/google_workspace_host_v1.py`
- `core/onyx_live_activation_google_workspace_v1.py`
- `scripts/bootstrap_onyx_live_google_workspace_v1.pyw`
- `scripts/launch_onyx_live_google_workspace_v1.pyw`
- `scripts/generate_release_workflow_v95.py`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V46-E6-001.manifest.json`
- `docs/onyx/evidence/ONYX_GWS_1_0_1_1_SOURCE_PROVENANCE_20260905.json`
- `docs/onyx/CAPABILITY_AUDIT_2026-09-04.md`
- `tests/test_desktop_shortcut.py`
- `tests/test_capability_expansion_layout_freeze_v1.py`
- `tests/test_google_workspace_host_v1.py`
- `tests/test_onyx_live_activation_google_workspace_v1.py`
- `tests/test_onyx_hud_current_acceptance_v46.py`
- `tests/test_packaged_runtime_hud_contract_v15.py`
- `tests/test_release_workflow_transition_v95.py`

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-09-02 | 0.1.0 | Created exact-snapshot operational parity and V24 startup recovery story with immutable humanoid boundary. | Chronos (`@sm`) |
| 2026-09-02 | 0.2.0 | Recovered empty-argument startup and added first-class voice/audio-device runtime contracts without touching visual sources. | Vulcan (`@dev`) |
| 2026-09-02 | 0.3.0 | Added bounded undo, replay-safe confirmation, owner memory controls, action resolution and exact 42-capability evidence; prepared successor V82/1.1.19. | Vulcan (`@dev`) |
| 2026-09-02 | 0.4.0 | Hardened the Windows Setup smoke timeout/process-tree cleanup and made lifecycle refusal dialogs safe for silent release validation. | Polaris (`@devops`) |
| 2026-09-02 | 0.5.0 | Rebound parity to current upstream HEAD, retained Onyx superset capabilities, and prepared successor V83/1.1.20. | AEXOS Master |
| 2026-09-02 | 0.5.1 | Removed deterministic PortAudio silence gaps, made transient underflow recoverable, preserved interrupt/shutdown semantics, and prepared successor V84/1.1.21 without visual changes. | Vulcan (`@dev`) |
| 2026-09-02 | 0.5.2 | Linearized concurrent audio publication with interrupt cutoff, added adversarial concurrency coverage, and prepared successor V85/1.1.22. | AEXOS Master |
| 2026-09-02 | 0.5.3 | Added persisted Gemini Live voice selection to Setup and prepared successor V86/1.1.23 without changing the primary HUD. | AEXOS Master |
| 2026-09-04 | 0.6.0 | Recovered typed turns across Gemini rotation, bounded silent-response latency, activated shipped local parity capabilities in the conversational host, added positive package receipts, and prepared V92/1.1.27 without visual changes. | AEXOS Master / Vulcan / Argus / Polaris |
| 2026-09-04 | 0.6.1 | Normalized persisted absolute social-video roots at the service boundary, added complete local startup diagnostics, and prepared V93/1.1.28 without changing UI, humanoid or voice behavior. | AEXOS Master / Vulcan / Argus / Polaris |
| 2026-09-04 | 0.6.2 | Repaired the current native-release fixture to follow the complete packaged humanoid-manifest authority without rebinding historical evidence. | AEXOS Master / Vulcan / Argus / Polaris |
| 2026-09-04 | 0.6.3 | Added non-mutating Escape dismissal for configured Setup, removed unused dashboard lifespan noise on clean exit, and prepared V94/1.1.29 without changing the accepted visual layout. | AEXOS Master / Vulcan / Argus / Polaris |
| 2026-09-05 | 0.6.4 | Repaired literal-empty shortcut launch, Windows long-path Google witness durability and authenticated Google source closure; prepared V95/1.1.30 without changing layout, humanoid, palette or voice. | AEXOS Master / Vulcan / Argus / Polaris |

## QA Results

- Voice-selector V86 slice: PASS (`71 passed` in cross-regression; V43/V12 preserve primary HUD, humanoid and voice pipeline while authenticating only the Setup control).
- Source and canonical regression gate: PASS (`239 passed`, `245 subtests passed`).
- Package/install/lifecycle gate: PASS for the exact local candidate and installed-host startup route.
- Live-provider/device gate: CONCERNS until owner OAuth, physical camera/voice and official social-provider receipts are completed; local native plugin sandbox execution is certified.
- V95 source audit: PASS for 489 tests plus 293 subtests in the 42-capability evidence matrix, 708 extended tests, 34 current shortcut/HUD tests, 94 Google host tests and 50 Google activation tests. Final package/install/live proof remains pending.
