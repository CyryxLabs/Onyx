# Story ONYX-STARTUP-ATTENTION-REMEDIATION-V1 — Startup Attention Remediation

**Status:** Done
**Predecessor:** `ONYX-HUD-V41-FLICKER-STABILITY-V1`
**Release authority:** Local patch successor only; no remote push, tag or production publication is authorized.

## Story

**As the** Cyryx Labs owner,  
**I want** the installed Onyx runtime to complete governed startup without a false `ATTENTION` state,  
**so that** the assistant is live while genuine control-plane path violations still fail closed.

## Immutable Boundaries

- Preserve the installed humanoid HUD, layout, palette, voice, command behavior and capability contracts.
- Do not remove or weaken ACLs on `%LOCALAPPDATA%`, `%APPDATA%`, the Windows profile, or any other broad host directory.
- Never accept a linked/reparse, foreign-owned, non-directory or non-canonical Onyx private root.
- Preserve the current control-plane database and all owner data byte-for-byte unless SQLite performs ordinary governed writes after successful startup.
- Treat provider credentials, owner OAuth consent and external-service availability as separate gates, not local startup defects.

## Acceptance Criteria

1. A native Windows reproduction identifies the exact exception and offending ACL principal behind the installed `ATTENTION` state.
2. An existing Onyx-managed root may establish the trust boundary only when its owner, type, link state and canonical protected DACL are all verified before use.
3. An absent or non-canonical managed root beneath an unsafe ancestor remains rejected before control-plane materialization or ACL mutation.
4. Linked/reparse, foreign-owner and broad-principal protections remain covered by regression tests.
5. The control plane reopens the existing owner database successfully without broad ACL changes.
6. Runtime construction proceeds beyond the former `ControlPlanePathError`; any subsequent blocker is independently reproduced, corrected when local and in scope, or reported truthfully when external.
7. A patch successor is packaged and installed only after focused security, startup, command, shutdown and HUD continuity checks pass.

## Tasks / Subtasks

- [x] **Slice 0 — Reproduce and classify**
  - [x] Capture the exact installed startup exception and inspect only the relevant ACL chain.
  - [x] Confirm the Onyx-owned leaf is canonical and that the broad ancestor is not to be mutated.
- [x] **Slice 1 — Correct trust-boundary selection**
  - [x] Verify an existing canonical managed root before allowing it to cut off inherited ancestor permissions.
  - [x] Keep unsafe creation and unsafe existing-root paths fail-closed.
- [x] **Slice 2 — Regression and blocker sweep**
  - [x] Add native Windows positive and adversarial tests.
  - [x] Re-run control-plane, runtime-construction and startup diagnostics.
  - [x] Investigate and resolve the governance shutdown blocker exposed by the fix.
- [x] **Slice 3 — Local successor**
  - [x] Build the patch successor and preserve rollback evidence.
  - [x] Install and verify the real executable without changing the HUD contract.
- [x] **Slice 4 — Installed certification**
  - [x] Confirm startup no longer projects `ATTENTION` for this defect.
  - [x] Confirm text command, graceful exit and humanoid continuity remain intact.

## Testing

- Native Windows ACL contract tests using isolated temporary roots.
- Existing `tests/test_control_plane.py` security suite.
- Runtime-construction transaction tests and packaged startup smoke.
- Installed executable health, text-command, graceful-exit and short temporal HUD regression.

## Dev Agent Record

### Agent Model Used

- Codex / AEXOS `@dev` (Vulcan)

### Debug Log References

- Native reproduction: `ControlPlanePathError` for an untrusted `S-1-15-3-*` capability ACE on `%LOCALAPPDATA%`.

### Completion Notes List

- Release V79/1.1.16 proved the ACL trust-boundary fix; Release V80/1.1.17 incorporated the subsequently exposed governed-shutdown recovery.
- Installed 1.1.17 reached lifecycle `listening`, displayed `PRESENT`, accepted text in 0.8 ms and produced first response audio in 1317.9 ms.
- The humanoid remained stable across 150 captured frames over 30 seconds with zero collapse frames.

### File List

- `docs/stories/ONYX-STARTUP-ATTENTION-REMEDIATION-V1.story.md`
- `core/control_plane.py`
- `tests/test_control_plane.py`
- `evidence/live/startup-attention-phase6-fixed-1.1.17-installed/metrics.json`

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-09-02 | 0.1.0 | Created focused startup attention remediation with fail-closed ACL boundaries. | Chronos (`@sm`) |
| 2026-09-02 | 1.0.0 | Installed V80 successor validated without ATTENTION or HUD regression. | Vulcan (`@dev`) |

## QA Results

PASS — 38 focused control-plane/release tests passed, 1 platform skip remained expected, and 68 adversarial subtests passed. Installed evidence confirms zero `ATTENTION` tokens and a responsive V24 runtime.
