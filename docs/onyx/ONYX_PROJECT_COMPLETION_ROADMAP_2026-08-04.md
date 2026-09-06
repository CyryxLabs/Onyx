# Onyx project completion roadmap — 2026-08-04

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as V30-era historical
> evidence. Use `CURRENT_RELEASE_STATUS.md` and
> `DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md` for current truth.

Status: **CURRENT EXECUTION ROADMAP — NOT A COMPLETION CLAIM**

## 2026-08-04 jarvis_MAAX clean-room successor update

The exact reference commit and capability-by-capability disposition are now
recorded in `JARVIS_MAAX_CLEAN_ROOM_GAP_ANALYSIS_2026-08-04.md`. Two genuine
local gaps are implemented in current source:

- governed durable workflow graphs, voice/tool routing and cinematic HUD
  summaries, interconnected with the existing event runtime and Phase 6;
- durable metadata-only application↔project context graph, fed only by accepted
  native events with zero polling or captured content.

The current working source is newer than the V22 release candidate described
below. It must receive a new integrity successor, clean Windows rebuild/install
and installed validation before any installed or release claim changes.

This document separates the release-critical path from later capability
expansion. `CURRENT_RELEASE_STATUS.md` remains the authority when evidence
changes.

## Current proved baseline

- Windows x64 Onyx 1.1.9 V19 is clean-built and exact-installed: 7,288/7,288
  bundle files, zero mismatches and 9/9 installed gates.
- The installed Gemini Native Audio process survived repeated real provider
  rotations with one microphone and one playback lifetime and no system-voice
  fallback.
- Current source authority is V20 / Release Workflow V6. Its exact 37-suite
  selection passes 260 tests; V12–V21 activation passes 136 tests and the
  V2–V20 transition selection passes 48 tests.
- Linux x64 diagnostic DEB/TAR/AppImage build and clean Debian DEB
  install/startup pass. Native desktop/audio/lifecycle evidence remains open.
- The V19 28,800-second installed long-session attempt remains useful
  predecessor stability evidence, but it cannot qualify V20. V20 requires a
  clean Windows rebuild/install and a new full-duration receipt.

## Release-critical path

| Order | Gate | Current state | Closure |
|---|---|---|---|
| 1 | Windows V20 rebuild and long session | Source ready; installed successor absent | Clean-build and exact-install V20, repeat installed smokes and real provider rotation, then run a new 28,800-second receipt with all samples responsive, CPU/memory/growth within thresholds and zero Application Errors |
| 2 | Owner physical acceptance | Needs owner | Speak to installed Onyx, confirm Charon natural voice and microphone/speaker loop; change the owner address by voice, restart fully and confirm persistence in speech and HUD |
| 3 | Microsoft Graph DayOps | Needs external access | Supply Entra public-client identifiers, consent and the intended account/workspace; execute live read-only calendar/mail receipts |
| 4 | Windows signing and lifecycle | Needs certificate and host | Sign/timestamp exact Setup with a trusted Cyryx Labs identity and execute clean install, reinstall, upgrade, rollback, uninstall and data-preservation harness on a disposable clean host |
| 5 | macOS native release | Needs Apple runner/credentials | Build on Apple Silicon, validate GUI/audio/autostart/lifecycle, Developer ID sign, notarize, staple and pass Gatekeeper |
| 6 | Linux native release | Diagnostic x64 build/install passed; native gates open | Reproduce on native x64/arm64 runners; validate desktop GUI/audio/systemd-user autostart, lifecycle and signing policy |
| 7 | Legal and notices | Needs owner/legal decision | Resolve the explicit worklist, approve product/third-party notices and record durable approval; technical SBOM does not provide legal approval |
| 8 | Independent final review | Needs independent reviewer | Review exact final hashes and every evidence cell; record findings and accepted/rejected disposition |

## Clean-room capability expansion after the V20 release gate

These are useful behaviors observed in the reference project but deliberately
implemented only as original Onyx modules through the existing mission,
permission, vault, memory and audit authorities. They are not reasons to copy
reference source or weaken governance.

1. Add live calendar/reminder/connectivity/mission event publishers to the
   existing low-CPU awareness queue after Graph access exists.
2. Add deeper Cyryx HUD views for workflows, devices, sites and preference
   review without creating a second UI shell or polling loop.
3. Complete device endpoint provisioning and pairing UX over the existing
   pinned TLS transport, then validate on real second devices.
4. Add concrete, receipt-bound site recipes and governed publishing adapters;
   no raw shell or token-bearing URL is permitted.
5. Add official account-bound channel connectors only where provider APIs,
   credentials, recipient scope and post-action receipts exist.
6. Add typed macOS/Linux accessibility actions only after native-host target,
   permission and postcondition validation.
7. Extend content artifact lifecycle projections; external publication remains
   a separately authorized mutation.

## Non-negotiable architecture invariants

- Gemini Native Audio/Charon has no Windows/system-voice fallback.
- Phase 6 remains the single mission engine and execution truth.
- No second permission broker, memory authority, tool dispatcher or permanent
  UI shell may be introduced.
- Unknown actions fail closed; model text alone never proves completion.
- Credentials never enter prompts, logs, URLs, command lines or flat files.
- Native events are preferred; continuous clipboard/process/screen polling and
  recursive home-directory watching remain rejected for privacy and CPU.

Any packaged-runtime source change after the V20 source hashes requires a
new successor identity, clean rebuild, exact install and restart of installed
runtime qualification. Evidence is never transferred silently.
