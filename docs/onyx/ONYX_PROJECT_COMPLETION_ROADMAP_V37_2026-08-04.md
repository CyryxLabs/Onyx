# Onyx project completion roadmap — V37 source candidate

> **SUPERSEDED FOR CURRENT-STATE CLAIMS:** V41 is now frozen, built and
> installed as an unsigned Windows diagnostic candidate. Use
> `CURRENT_RELEASE_STATUS.md`,
> `operations/ONYX_1_1_9_V41_WINDOWS_ACCEPTANCE_2026-08-10.md` and
> `FINAL_EVIDENCE_INDEX_1.1.9.md`. This file remains immutable-scope V37
> history.

Status: **V37 exists only in source; the installed product remains V31 and the
project is not complete.**

## Implemented in the current source candidate

- resident packaged close-to-background behavior with restore and explicit exit;
- HUD V10 with HUD current V24 source acceptance over immutable V23;
- Gemini-only causal farewell/runtime V35 behavior;
- safe V24 outer activation guard;
- authenticated same-user installer lifecycle IPC;
- POSIX default portable-current selection and fail-closed negative boundary.

Relevant source-focused tests passed in bounded sets. This does not establish a
global gate, artifact, installation, native platform or physical acceptance.

Source authority is the **current authenticated source evidence selected by the
[direct verifier](../../scripts/verify_phase5_exit_retirement_v1.py)**. The
verifier authenticates the current Phase and Release Workflow transitions and
their complete immutable predecessor chains. Fixture version numbers are
evidence-lineage identifiers, not product versions.

## Exact execution order

1. Preserve every verified Phase and Release Workflow predecessor as immutable;
   the current authenticated source evidence selected by the direct verifier
   authenticates the V37 source boundary. This does not satisfy build or
   installed-host gates.
2. Freeze, build and inventory the exact Windows V37 Setup and portable
   artifacts; install them and prove installed bytes match.
3. Because installed V31 predates lifecycle IPC, exit it manually once and
   prove the first V31-to-V37 upgrade preserves owner data and configuration.
4. On installed V37, accept spoken owner-name mutation through record update,
   immediate screen projection and restart persistence.
5. Physically accept Gemini natural voice and causal farewell with no system
   voice substitution.
6. Accept installed HUD/Orb motion across idle/listening/thinking/speaking,
   including accessibility, CPU, memory and thermal observations.
7. Re-run installed mission crash/reconciliation/retry/pause/cancel/audit and
   installed DayOps behavior; configure Entra for live Graph acceptance.
8. Prove future running-resident upgrade and uninstall through lifecycle IPC,
   plus failed-upgrade and prior-version rollback on clean disposable Windows
   hosts.
9. Run a fresh 28,800-second V37 Windows stability session. The V31 attempt
   failed at 2,381.543s after a clean ordinary-close exit and is not reusable.
10. Produce and test native Linux x64/arm64 GUI/audio/session/lifecycle builds.
    Portable-current POSIX negative/limited evidence is not Windows-equivalent
    and does not close this gate.
11. Produce native macOS Intel/Apple Silicon builds and pass permissions, audio,
    lifecycle, Developer ID signing, notarization and Gatekeeper acceptance.
12. Obtain trusted Cyryx Labs Authenticode credentials, sign Windows artifacts
    and repeat native trust plus clean-machine lifecycle acceptance.
13. Resolve third-party notices/licenses, obtain Cyryx Labs legal approval and
    reconcile the SBOM to the final signed shipped set.
14. Complete independent evidence review with reviewer identity, decision and
    durable signature.

## Completion rule

Every step requires linked evidence bound to the exact final artifacts. Source
tests, a local unsigned install, a short live session, a historical SBOM or a
percentage estimate cannot substitute for any missing gate.
