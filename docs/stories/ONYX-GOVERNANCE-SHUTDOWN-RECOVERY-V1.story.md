# Story ONYX-GOVERNANCE-SHUTDOWN-RECOVERY-V1 — Governed Shutdown Recovery

**Status:** Done
**Predecessor:** `ONYX-STARTUP-ATTENTION-REMEDIATION-V1`
**Release authority:** Local patch successor only; no remote push, tag or production publication is authorized.

## Story

**As the** Cyryx Labs owner,  
**I want** an ordinary Onyx shutdown to remain process-local,  
**so that** only the explicit emergency mission can latch the durable global kill and subsequent launches remain operational.

## Immutable Boundaries

- Preserve the installed humanoid HUD, layout, palette, voice and capability contracts.
- Preserve the explicit `mission_global_kill` emergency path and its fail-closed propagation.
- Never clear a durable global kill implicitly during startup.
- Require exact owner confirmation and append-only audit evidence for recovery.
- Treat OAuth consent and provider availability as external gates, not local shutdown defects.

## Acceptance Criteria

1. Normal runtime cleanup uses process-local shutdown and does not append a durable global-kill latch.
2. Explicit emergency kill remains durable across process restarts.
3. A latched kill can be released only by the exact owner recovery confirmation and records the released latch sequence.
4. The complete Phase 6 live-wiring chain initializes after an audited recovery.
5. A release successor is packaged, installed and validated against the existing owner profile.
6. The installed HUD remains unchanged and stable.

## Tasks / Subtasks

- [x] **Slice 0 — Reproduce and classify**
  - [x] Trace the Phase 6 denial to the durable governance latch.
  - [x] Correlate the latch event with ordinary runtime cleanup.
- [x] **Slice 1 — Correct shutdown semantics**
  - [x] Add idempotent process-local host shutdown.
  - [x] Route normal constructor and runtime cleanup through local shutdown.
  - [x] Preserve durable kill exclusively for the explicit emergency path.
- [x] **Slice 2 — Audited owner recovery**
  - [x] Add exact-confirmation recovery with authenticated ledger history.
  - [x] Release the accidental owner-profile latch and verify it remains released after local shutdown.
- [x] **Slice 3 — Successor and installed validation**
  - [x] Seal Release V80 and build Onyx 1.1.17.
  - [x] Install and validate Phase 6, voice startup, graceful shutdown and HUD continuity.

## Testing

- Focused governance-host, capability-composition and runtime-lifecycle suites.
- Full source Phase 6 construction with the real owner governance ledger.
- Release V80 integrity verification and packaged installed-runtime smoke.

## Dev Agent Record

### Agent Model Used

- Codex / AEXOS `@dev` (Vulcan)

### Debug Log References

- Authenticated owner ledger: accidental latch sequence `21597`; audited release sequence `21650`.

### Completion Notes List

- Release V80 root `6f1abd1bf52e3a0eaa7272987d0b4427339b6e840ef7aa4336731300664ef55f` authenticated the shutdown recovery closure.
- Installed shutdown client returned zero, the resident exited, the capability record was removed and a fresh process reached `listening` without a Phase 6 failure.
- The owner ledger remains healthy and its latest global-kill lifecycle event is the audited release at sequence `21650`, after the accidental latch at `21597`.

### File List

- `core/governance_nucleus_v1.py`
- `core/governed_capability_host_v1.py`
- `core/capability_composition_v1.py`
- `main.py`
- `tests/test_governed_capability_host_v1.py`
- `tests/test_capability_composition_v1.py`
- `tests/test_runtime_lifecycle_v1.py`
- `docs/stories/ONYX-GOVERNANCE-SHUTDOWN-RECOVERY-V1.story.md`
- `scripts/generate_release_workflow_v80.py`
- `scripts/verify_release_workflow_v80.py`
- `tests/fixtures/release_workflow_transition_v80.json`
- `tests/test_release_workflow_transition_v80.py`
- `evidence/live/startup-attention-phase6-fixed-1.1.17-installed/metrics.json`

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-09-02 | 0.1.0 | Separated local shutdown from durable global kill and added audited owner recovery. | Chronos (`@sm`) |
| 2026-09-02 | 1.0.0 | Installed V80 lifecycle, Phase 6, command latency and HUD continuity validated. | Vulcan (`@dev`) |

## QA Results

PASS — 62 governance/composition/runtime tests passed; the release build and isolated Windows Setup smoke passed; installed shutdown/restart remained healthy. A supplemental historical AST characterization still expects a literal Gemini config keyword despite the working payload-based runtime and is recorded as non-runtime test debt.
