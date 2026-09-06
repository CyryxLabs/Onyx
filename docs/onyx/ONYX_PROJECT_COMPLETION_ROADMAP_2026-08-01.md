# ONYX — Project Completion Roadmap

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as the 2026-08-01
> planning baseline. Use `CURRENT_RELEASE_STATUS.md`,
> `FINAL_EVIDENCE_INDEX_1.1.9.md` and
> `DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md` for current truth.

Current roadmap sequence: **active; factual status refreshed 2026-08-03 after
independent source review**. The original 2026-08-01 snapshot below is retained
as the planning baseline. Exact current candidate evidence and open gates are maintained in
`CURRENT_RELEASE_STATUS.md`; document precedence is defined in
`DOCUMENTATION_INDEX.md`.

## Authority, date, and scope

- **Authority:** Cyryx Labs / Onyx project workspace.
- **Snapshot date:** 2026-08-01.
- **Scope:** completion path from the currently proved source and installed baselines to a releasable, operational Onyx across Windows, macOS, and Linux.
- **Evidence rule:** this roadmap distinguishes code present in the repository, focused test evidence, installed-runtime evidence, and external validation. It does not claim 100% completion.

## 2026-08-03 execution update

### Current V21 Windows delta (supersedes older Windows-version claims below)

- Onyx 1.1.9 V21 was built, installed and started normally on Windows x64.
  Exact hashes and results are recorded in
  `operations/ONYX_1_1_9_V21_ADVANCED_OPERATIONS_WINDOWS_ACCEPTANCE_2026-08-03.md`.
- The installed V21 bootstrap migration, V20/Phase 6 seam ownership and Gemini
  voice path are working. `Mic`, `Recv` and `Play` opened with the original
  native-audio provider; no system-voice fallback was added.
- A repeatable `0xc0000374` PortAudio heap-corruption crash after the first
  voice turn was corrected by giving the native playback stream one thread
  owner. The final installed candidate survived the 90-second acceptance
  sample with zero new Onyx Application Error events.
- The installed bundle matched all 6,782 inventory entries and passed hygiene
  and Advanced Commands V21 smoke. The application remains open for owner use.
- This closes the current bounded Windows rebuild/install/startup defect. It
  does not close owner acoustic/name acceptance, live Graph, representative
  installed mission recovery, long soak, clean-host lifecycle, signing, legal,
  SBOM, macOS/Linux or independent final review.

The older 1.1.0/1.1.7/1.1.8 Windows details retained later in this document are
historical evidence only. `CURRENT_RELEASE_STATUS.md` has precedence for the
current candidate.

- Windows 1.1.7 setup and portable artifacts were built, inventoried, installed
  as an upgrade over 1.1.6 and started successfully through V19.
- The original Gemini Live native-audio contract was restored fail-closed to
  the exact 2.5 native-audio preview model and `Charon`, with session resumption
  and graceful provider rotation. A real production-config provider turn
  returned native audio; the owner's acoustic acceptance remains required.
- The 1.1.7 artifact-bound SPDX SBOM reconciles to both Windows artifacts, the
  bundle inventory and dependency lock. This is technical reconciliation, not
  legal approval.
- The attempted eight-hour installed Windows 1.1.7 soak ended after about
  0.25 hour with an indeterminate process exit. It is not a pass and cannot be
  transferred to 1.1.8.
- Windows 1.1.8 is the installed operational predecessor; its bounded soak is
  still in progress and cannot qualify 1.1.9.
- The `029175...` and `d0702...` 1.1.9 source certifications are superseded and
  build-NO-GO. A hermetic diagnostic-isolation correction is under independent
  review. No native build may start until a future V10 record and external
  zero-divergence seal bind the accepted frozen bytes.
- Cross-platform native lifecycle, signing/notarization, live Microsoft Graph,
  final legal approval and independent evidence review remain open external
  gates and must not be represented as complete.

## Definition of complete

Onyx is complete only when all of the following are true:

1. The production package is rebuilt from the approved source and installed cleanly.
2. The installed application passes startup, identity, voice, Orb-motion, mission, governance, permission, provider, DayOps, update, and recovery acceptance gates.
3. Calendar and email DayOps are demonstrated against live Microsoft Graph data with the intended account and least-privilege consent.
4. Windows, macOS, and Linux packages pass native clean-machine installation and runtime tests.
5. Release artifacts are signed where applicable, Apple notarization is complete, and required third-party notices are approved.
6. Current operational documentation matches the shipped release and stale documents are archived or clearly marked superseded.

## Proved baseline

The following baseline is supported by repository, package, installed-runtime, or focused test evidence:

- Phase 11 local candidate is approved within its stated local scope.
- DayOps source closure and provenance focused tests are green; this is not evidence of a live Microsoft Graph run.
- The name-update-by-voice and dynamic Orb-motion changes passed a final focused re-verification of **27 tests** and an integrated relevant suite of **99 tests**.
- The Orb motion remains bounded by performance and accessibility controls in source.
- The Windows 1.1.0 production build completed with exit code **0** and its release artifacts passed independent manifest, hash, input-seal, archive-structure, and rollback-integrity verification.
- The canonical Windows upgrade completed with exit code **0**, with an installation log retained; the installed version, executable hashes, and desktop/Start Menu shortcut targets were verified.
- All executed installed-runtime smokes passed. A subsequent normal live launch also passed and is the authoritative startup result for the canonical application.
- Windows remains the most mature and currently operational runtime and packaging target.
- Portable activation and host-boundary work exists as a default-off candidate and must retain honest capability-limited reporting until native evidence exists.

These statements establish the current Windows 1.1.0 installed baseline, but do not establish macOS/Linux readiness, public-release readiness, live Microsoft Graph closure, long-session qualification, or overall project completion.

## Windows 1.1.0 release and installed evidence

The earlier statement that the latest identity and Orb improvements were **source-only** is **SUPERSEDED**. The approved Windows 1.1.0 candidate has now been built and installed.

- Build command result: exit code **0**.
- Portable artifact: `Onyx-1.1.0-Windows-x64-Portable.zip`, **541,046,264 bytes**, SHA-256 `a3febd01017e8d7f3208328e5d0c319c08f6b41c0666228c946582b2f45ffea9`.
- Installer artifact: `Onyx-1.1.0-Windows-x64-Setup.exe`, **474,657,591 bytes**, SHA-256 `795560fb82a6cb27b1d6334798305b101ec2795056330e2d63a633937aac3352`.
- First-party input seal: **1,092 files**, aggregate root `bd14fbfa7648049b9958fce12d3f91f8e5539e74c726082dc6b09b954f3a7174`; serialized seal **198,589 bytes**, SHA-256 `12d8c742fcb3e784bce5758d801db138e51b6ae5f2d2a26b9d2b51102dec5474`.
- Independent integrity verdict: artifact sizes and hashes match the release manifest and `SHA256SUMS`; the input seal has no missing, altered, duplicate, order-drift, symlink, or reparse entries; the portable archive has no unsafe members; the rollback archive remains complete and unchanged.
- Canonical upgrade: exit code **0**, with the installer log retained. Installed `Onyx.exe` and `Onyx-DayOps.exe` report version **1.1.0** and match the packaged executable hashes `9fa7067f9d8055aaf9c7c1d8e64695b3f4dc6abcc8b82f45cb89b7edbe1704b4` and `49da236ed19106f84530875087ac0f8b6fa48b1b898ad183f566ec0916badb7c` respectively.
- Shortcut verification: desktop and Start Menu entries resolve to the canonical installed `Onyx.exe`, with the installed application directory as the working directory.
- Installed smokes: all executed activation, startup, DayOps, microphone, receive, playback, package, upgrade, and shortcut checks passed.
- Normal live startup: at `2026-08-01T18:23:57Z`, Onyx started through the V19 activation chain with DayOps, microphone, receive, and playback paths active and no fatal startup error.
- A UI launch attempted from the capability-sandbox automation context encountered `ControlPlanePathError`; the normal canonical launch passed. This is classified as an automation-context limitation, not a canonical runtime blocker.
- Fifteen-second live performance sample: **0.64% CPU across logical CPUs**, **408.7 MB working set**, **1,107 MB private memory**, **103 threads**, UI responding. This closes the short-sample regression check but not the long-session/thermal/leak gate.
- The voice provider invoked `correct_owner_name`, proving command routing. Physical confirmation that the changed name persists after a real spoken update and full application restart remains open unless separately evidenced.

The previous claims that the installed Onyx was older, that Windows still required a rebuild/install, or that the 1.1.0 identity/Orb work was only source-tested are **SUPERSEDED** by the evidence above.

## Priority roadmap

Effort estimates are engineering working days, not calendar commitments. External review, certificate issuance, account consent, hardware availability, and defect discovery can extend elapsed time.

| Priority | Work block | Completion evidence | Estimated effort |
|---|---|---|---:|
| P0 | Close the remaining Windows physical identity acceptance | Speak a real owner-name correction, confirm the intended value, restart the canonical app, and prove persisted address/name in the relaunched instance | 0.5 day |
| P0 | Preserve the Windows 1.1.9 V21 installed candidate | Retain exact hashes, manifest/input seal, 6,782-file inventory, installed smokes, heap-race correction and runtime trace | Complete for current local candidate; repeat after any source change |
| P0 | Close portable activation security and packaging gates without weakening Windows behavior | Independent security review; no arbitrary guard/factory injection; descriptor-bound POSIX setup; safe lease close; candidate-specific packaged smoke; Windows regression green | 2–4 days |
| P0 | Demonstrate DayOps with live Microsoft Graph | Entra configuration, least-privilege consent, successful calendar and unread-email retrieval, provenance trace, failure/re-auth behavior | 1–2 days after credentials/consent |
| P0 | Complete the residual installed-host acceptance items | Owner acoustic/name persistence, live Microsoft Graph, representative mission/recovery and hardware checks not covered by automated smokes | 1–2 days after access/owner test |
| P1 | Add and execute native Linux build/runtime gates | Native build, package, install, startup, file-boundary, single-instance, signal, voice/audio, GUI and mission evidence | 2–4 days plus Linux host |
| P1 | Add and execute native macOS build/runtime gates | Universal/targeted build decision, package, install, startup, permissions, audio, GUI, mission, signing and notarization evidence | 3–6 days plus Mac and Apple credentials |
| P1 | Finish release compliance | Third-party notices, dependency/license review, approved Cyryx Labs license text, SBOM-to-package consistency | 1–3 days plus legal decision |
| P1 | Sign and verify release artifacts | Windows signing and timestamp verification; macOS Developer ID signing/notarization; provenance retained | 1–3 days after certificates |
| P1 | Clean-machine and upgrade validation | Fresh Windows/macOS/Linux installs, upgrade from previous build, uninstall, data retention/removal policy, rollback | 2–4 days |
| P2 | Performance and long-session qualification | Idle/speaking CPU and memory thresholds, Orb frame pacing, thermal/battery behavior, leak and 8-hour soak tests | V11 attempt ended after 1,380.57 seconds when the app exited; observed samples passed responsiveness/CPU/error thresholds, but duration failed. Restart after the final rebuild; broader qualification remains 2–3 days |
| P2 | Agentic capability expansion under existing authority boundaries | Additional workflows, durable evaluations, failure injection, auditability, human-controlled external actions | Incremental blocks of 2–5 days |
| P2 | Documentation consolidation and stale-document cleanup | Single current index, superseded markers, operator/user/runbook alignment with shipped version | 1–2 days |

## Critical path

1. Preserve the verified Windows 1.1.9 V21 hashes, manifest, input seal, inventory, installed smokes, native voice/startup trace and heap-race regression evidence.
2. Perform the physical spoken owner-name correction and prove persistence after a full canonical restart.
3. Resolve the remaining portable security and build-gate findings; independently reverify them.
4. Configure Microsoft Entra and perform the live DayOps acceptance run.
5. Execute native Linux and macOS gates on real hosts.
6. Reconcile the final SBOM and legal notices, then complete Windows signing and macOS signing/notarization.
7. Complete clean-machine, uninstall/rollback, and long-session performance qualification.
8. Publish a final evidence index only after every required gate is closed.

## Acceptance gates

| Gate | Required result |
|---|---|
| Source integrity | Exact revision/worktree snapshot recorded; generated package is traceable to it |
| Startup | Single instance starts without traceback, stale-lock failure, or silent capability downgrade |
| Identity | Initial name persists; an authenticated voice command can change it later; restart preserves the change; ambiguous speech requires confirmation |
| Voice/provider | Microphone capture, transcription, intended provider invocation, response, speech synthesis, cancellation, and offline/error behavior are demonstrated |
| Orb/UI | Orb visibly reacts to speaking/listening/thinking states, respects reduced-motion behavior, retains official colors, and meets CPU/frame thresholds |
| Missions | Create, execute, pause/cancel, recover, and audit representative missions without bypassing permissions or governance |
| Security boundaries | No arbitrary activation capability injection, symlink redirection, unsafe descriptor reuse, or fail-open portable behavior |
| DayOps | Live calendar and important unread-email data are retrieved with provenance, bounded coverage, least privilege, and explicit error handling |
| Packaging | Install, launch, upgrade, uninstall, rollback, version display, icon, data directories, and logs behave correctly |
| Cross-platform | Native evidence is collected separately on Windows, macOS, and Linux; no platform is inferred from another |
| Release compliance | SBOM corresponds to shipped contents; notices/licenses are approved; artifacts are signed/notarized as applicable |
| Operations | Runbooks, recovery, support diagnostics, backup/restore expectations, and known limitations match the release |

## External dependencies

The following cannot be honestly closed by source changes alone:

- Microsoft Entra Client ID, tenant/account selection, and one-time consent for the required `Calendars.Read` and `Mail.Read` scopes.
- Access to representative macOS and Linux machines or CI runners with GUI/audio capabilities for native evidence.
- Windows code-signing certificate and timestamp service access.
- Apple Developer ID credentials and notarization access.
- Cyryx Labs approval of third-party notices and final legal/license wording.
- Availability of clean machines or disposable VMs for installation, upgrade, uninstall, and rollback qualification.

## Operating-system matrix

| Platform | Source/build status | Installed/runtime status | Remaining release evidence |
|---|---|---|---|
| Windows | Local 1.1.9 V21 build completed with exit 0; Setup/Portable hashes, input seal and inventory recorded | Canonical install exit 0; 6,782/6,782 inventory; installed V21 smokes; Gemini audio channels; 90-second stability and visible cinematic HUD passed | Owner acoustic/name persistence, mission/recovery, Entra/live DayOps, signing, clean-machine and long-session evidence |
| macOS | Portable/source candidate work exists | No native installed-host proof in this snapshot | Native build, permissions/audio/GUI tests, packaging, signing, notarization, clean-machine |
| Linux | Portable/source candidate work exists | No native installed-host proof in this snapshot | Native build, desktop/audio/session tests, packaging, clean-machine and distro coverage decision |

## Stale-document handling

Documentation cleanup must preserve evidence while preventing obsolete instructions from being mistaken for current truth:

- Maintain one current release-status index linking the authoritative acceptance evidence.
- Mark older activation, packaging, layout, and completion documents as `SUPERSEDED` with a link to the replacement; do not silently delete historical evidence.
- Remove temporary development, rebranding, and generated test artifacts from production packages, not from auditable source history unless separately approved.
- Reconcile every document that calls a candidate “live,” “complete,” or “operational” against installed-host evidence.
- Keep the design system, current user/operator guide, security model, packaging guide, and acceptance matrix versioned together.

## Global completion checklist

- [ ] Approved source snapshot frozen and recorded.
- [x] Phase 11 local candidate approved within its local scope.
- [x] DayOps source closure/provenance focused tests green.
- [x] Name voice update and Orb motion source re-verification: 27 focused tests green.
- [x] Relevant integrated source verification: 99 tests green.
- [ ] Portable security and packaged-candidate gates independently approved.
- [x] Windows 1.1.9 V21 local candidate built; build and isolated install/start/uninstall pipeline exited 0.
- [x] Release artifact hashes, sizes, manifest, first-party input seal, archive structure, and rollback archive independently verified.
- [x] Latest package installed canonically; installer exited 0 and product version is 1.1.9.
- [x] Installed version, executable hashes, and desktop/Start Menu shortcut targets verified.
- [x] Installed V21 smokes passed; normal live startup connected Gemini Native Audio with microphone, receive and playback active.
- [ ] Installed name voice update demonstrated across restart.
- [x] Installed Orb/runtime short acceptance demonstrated: 90 seconds alive, UI responding, stable post-startup CPU deltas and zero new Windows Application Error events.
- [x] V14 preserves the V13 Advanced Operations zero-polling HUD projection,
  non-sensitive workflow/device/site/preference summaries, governed automation
  authoring, controlled-root site lifecycle commands, owner-authorized style
  promotion/prompt projection and native-vault device enrollment. The expanded
  integrated selection passes 144 tests, the V12→V21 activation chain passes
  57 tests, and the 32-file V14 source manifest adds two passing
  integrity/policy tests. Native QML close stress passed 8/8 subprocess runs.
- [x] Rebuild, reinstall and bounded-runtime reaccept the current V14 plus
  Advanced Operations Windows candidate. Exact Setup/Portable, build-input,
  bundle, installed inventory and SBOM roots are recorded.
- [x] Representative installed mission/recovery lifecycle passed against exact
  installed `core/missions.py` bytes: create/run/audit/reopen, pause/cancel and
  crash-to-waiting recovery with explicit retry.
- [ ] Full Windows installed-host acceptance gate passed; physical voice-name persistence, live Entra/Graph, and remaining hardware-dependent evidence are still open.
- [ ] Live Microsoft Graph DayOps acceptance passed.
- [ ] Native Linux build/install/runtime gate passed.
- [ ] Native macOS build/install/runtime gate passed.
- [ ] Windows artifacts signed and verified.
- [ ] macOS artifacts signed and notarized.
- [ ] Third-party notices and final license text approved.
- [x] Windows 1.1.9 technical SBOM reconciled to both exact final artifacts and
  bundle inventory; legal approval and future native-platform artifact merges
  remain separate gates.
- [ ] Final multi-platform SBOM reconciled after native macOS/Linux artifacts
  exist.
- [ ] Clean install, upgrade, uninstall, and rollback passed on all supported platforms.
- [ ] Long-session performance and stability thresholds passed; prior attempts
  are predecessor diagnostics. Start the qualifying eight-hour run only after
  the V14 rebuild and installation.
- [ ] Documentation consolidated; stale documents marked superseded.
- [ ] Final evidence index independently reviewed.

## Immediate next release plan

1. Preserve the pre-V14 Windows evidence as predecessor history and keep the
   installed V14 acceptance bound to its exact recorded hashes.
2. Execute the remaining physical owner-name gate: spoken correction, confirmation, full canonical restart, and persistence verification.
3. Configure Microsoft Entra and execute the live DayOps calendar/unread-email gate with least-privilege consent and provenance.
4. Complete and independently verify the remaining portable security/build-gate corrections without changing the established Windows engine or authority model.
5. Schedule native Linux and macOS build/install/runtime qualification on real hosts.
6. Preserve the reconciled Windows SBOM; after native artifacts exist, merge
   their exact inventories into the final multi-platform SBOM. Separately
   approve third-party notices and Cyryx Labs legal/license text, sign Windows
   artifacts, and sign/notarize macOS artifacts.
7. Run clean-machine and long-session qualification, including sustained CPU, memory/leak, Orb frame pacing, audio, thermal, recovery, upgrade, uninstall, and rollback behavior.
8. Keep the predecessor short-runtime and mission/recovery results bounded;
   start the full-duration soak against the rebuilt V14 artifact.
9. Declare completion only when the checklist is closed with linked evidence; until then, report the exact proven layer rather than a percentage or an unqualified “complete.”
