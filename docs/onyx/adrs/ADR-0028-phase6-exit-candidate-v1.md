# ADR-0028 — Phase 6 Exit Candidate V1

Status: accepted for candidate construction; aggregate E6 pending  
Date: 2026-07-23

## Context

Phase 6 now has separately accepted implementations for Agentic Core V6, Live
Integration V2, Gemini Live compatibility, local/text compatibility, Provider
Registry V1, provider-free Research/Verifier Cells, Local MCP V1, Unified
Router V1, the disabled External-Agent descriptor, and Live Wiring V1. Live
Wiring V2 composes the planning authorities over Wiring V1, while Activation
V13 provides point-in-time operational evidence.

Those records do not by themselves prove the Phase 6 exit. In particular:

- a fake-client Gemini compatibility gate is not permanent live availability;
- accepted local/text parity does not authorize a remote cross-route;
- a Local MCP identity/call intent is not an observed MCP process;
- a disabled external-agent descriptor grants no installation or execution
  authority;
- an individual E6 decision is not the aggregate Phase 6 E6 decision.

## Decision

Create `phase6-exit-candidate-v1` as a sealed, default-off, evidence-only
composition.

The candidate:

1. returns before filesystem validation unless
   `ONYX_PHASE6_EXIT_CANDIDATE_V1=true` exactly;
2. binds every accepted component root by full SHA-256 and rejects symlinks,
   reparse points, path escape, duplicate JSON keys, byte drift, and
   read-time identity drift;
3. reproduces component-specific modality, privacy, fallback, self-
   certification, call-counter, and blocked-authority contracts;
4. reproduces the frozen Live Wiring V2 verifier;
5. treats Activation V13 as point-in-time operational evidence only;
6. requires an explicit Phase 6 capability-matrix delta;
7. performs no provider, network, process, MCP, or live dispatch;
8. reports E1-E5 ready and ready for external review, while keeping
   `external_e6_accepted=false`, `phase6_exit=false`, and
   `phase7_unlocked=false`.

The aggregate verifier runs each selected test file in a separate interpreter.
This avoids cross-file Qt application reuse while retaining exact per-file
pass counts.

## Consequences

- Phase 6 cannot be called complete from the candidate alone.
- No additional provider or remote cross-route may be added before the
  independent aggregate E6 decision.
- The External-Agent adapter remains `BLOCKED_BY_ACCESS`.
- Disabling or omitting the candidate flag restores the exact prior runtime
  because the candidate has no runtime seam or persisted state.
- Any evidence-byte, acceptance decision, finding, modality contract, privacy
  rule, matrix delta, or V13 observation-scope drift invalidates the closure.

## Rejected alternatives

- Treating V13 live promotion as Phase 6 exit: rejected because it is a
  point-in-time operational observation and does not independently review the
  aggregate evidence.
- Editing historical acceptance files after successor transitions: rejected;
  immutable historical evidence remains intact and the current candidate binds
  successor evidence explicitly.
- Enabling a remote provider route to make the phase look complete: rejected;
  Router V1's privacy-hard local/private boundary is an accepted safety
  contract, not a missing fallback to bypass.
