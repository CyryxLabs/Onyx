# Story ONYX-GUILD-A9.2 — Guild Handoff & Story Contracts V1

**Status:** Done (accepted 2026-08-17, `VE-GUILD-HANDOFF-V1-E6-001`, root
`104efcc6…`; acceptance verifier reproduced the full 29-file gate
717/0/0/17/96; autonomous-session honesty boundary recorded; matrix/ledger
doc updates batched into the next documentation-authority pass)
**Epic:** Onyx Engineering Guild (A9 expanded — `CAPABILITY_COMPLETION_PLAN_90PCT.md`)
**Predecessor:** `VE-GUILD-PROFILES-V1-E6-001` (A9.1, root `818196ac…`)

## Story

As the Cyryx Labs owner, I want Onyx to hold **typed handoff artifacts and
story contracts** — the AEXOS story-driven-development discipline as data —
so that guild work always flows story → validation → implementation → QA gate
with compact, bounded agent handoffs, before any workflow engine (A9.3) is
allowed to execute anything.

## Design sketch (to be confirmed at implementation)

Module `core/guild_handoff_v1.py`, flag `ONYX_GUILD_HANDOFF_V1`, default-off,
deterministic, hermetic; entry-bound to the A9.1 four-file acceptance tuple
(checkpoint manifest + acceptance md + acceptance manifest + anchor — exact
hashes pinned at implementation). Imports role/registry contracts from
`core.guild_profiles_v1` (the slice-1→slice-4 import precedent).

- `StoryContractV1` (frozen): `story_id`, `epic_id`, `title`,
  `acceptance_criteria: tuple` (non-empty), `status` in the fixed lifecycle
  `draft → validated → in_progress → in_review → done` (no skips, no
  regression; `done` requires a positive QA verdict record), `file_list`,
  `assigned_role_id` (must exist in a supplied `GuildRegistrySnapshotV1`
  and hold the operation the story stage requires).
- `QaVerdictV1` (frozen): `story_id`, `verdict` in
  `approve/reject/blocked`, `reviewer_role_id` (must hold
  `quality_verdicts` per the authority matrix — constitutional reuse).
- `HandoffArtifactV1` (frozen): `from_role_id` ≠ `to_role_id`, both existing;
  `story_id` referencing a known story; bounded sections mirroring the AEXOS
  agent-handoff rule: ≤5 decisions, ≤10 files, ≤3 blockers, byte-capped
  total (~500-token analog); `next_action` non-empty.
- Sealed `GuildStoryLedgerV1` (`create_guild_story_ledger_v1`): validates
  lifecycle transitions as supplied history (injected, no clock), unique
  ids, role-authority consistency against the A9.1 matrix, handoff chain
  continuity (a handoff's `to_role` must be the assignee of the story's
  next stage). **No execution surface**: stories and handoffs describe;
  nothing runs, schedules or dispatches (verifier asserts).

## Acceptance criteria

1. [ ] Contracts and sealed ledger exactly as designed, default-off.
2. [ ] Lifecycle: skips/regressions rejected; `done` without a positive QA
       verdict rejected; QA verdict from a role without `quality_verdicts`
       rejected (authority-matrix reuse).
3. [ ] Handoff bounds enforced (counts + byte cap); self-handoff rejected;
       unknown roles/stories rejected.
4. [ ] Entry-bind to A9.1 acceptance tuple; tamper → Denied.
5. [ ] ≥30 adversarial tests; standard evidence chain; cumulative gate grows
       by exactly this file with re-observed per-file counts.
6. [ ] Matrix: Operator Cells row limitations updated (handoff/story
       contracts exist; workflow/dispatch still absent) only after E6.
7. [ ] Honesty: autonomous-session boundary recorded if no independent human
       review occurs.

## Tasks

- [x] T1. A9.1 acceptance tuple pinned (4 hashes in
      `ACCEPTED_GUILD_PROFILES_ROOTS`); design confirmed against the AEXOS
      lifecycle/QA-loop/handoff rules; deliberate narrowing recorded in
      ADR-0055 (stage-operation authority deferred to A9.3).
- [x] T2. `core/guild_handoff_v1.py` implemented.
- [x] T3. `tests/test_guild_handoff_v1.py` — 43 passed, 0 failed.
- [x] T4. ADR-0055 + `GUILD_HANDOFF_V1_SOURCES.md`.
- [x] T5. Checkpoint bundle + candidate verifier; full 29-file gate
      reproduced 717/0/0/17/96 (root `104efcc6…`).
- [x] T6. E6 seal written (`VE-GUILD-HANDOFF-V1-E6-001` + manifest +
      anchor + acceptance verifier); matrix/ledger updates batched into the
      next documentation-authority pass (V53, with the release-consolidation
      docs) — recorded in the acceptance scope exclusions.

## Incident found and healed en route (2026-08-17/18 night)

First collection of this slice's tests failed closed in
`verify_legacy_activation_retirement_v1` because the accepted A9.1 slice had
legitimately updated `CAPABILITY_MATRIX.md`/`VERIFICATION_EVIDENCE.md`, whose
hashes the Phase 5 current-successor transition V51 binds. Healed by the
established additive procedure: fixture
`phase5_current_successor_transition_v52.json` + V52 loader in
`verify_phase5_exit_retirement_v1.py` (V51 retained immutable and renamed
historical, exactly like V47 before it). No historical binding rewritten.

## Out of scope

Workflow execution (A9.3), autopilot binding (A9.4), away-mode projects and
budgets/decommission (A9.5), any non-engineering pack, any live call.

## File List

- `docs/stories/ONYX-GUILD-A9.2.story.md` (this story)
- `core/guild_handoff_v1.py` (new)
- `tests/test_guild_handoff_v1.py` (new)
- `scripts/verify_guild_handoff_v1.py` (new)
- `docs/onyx/adrs/ADR-0055-guild-handoff-v1.md` (new)
- `docs/onyx/research/GUILD_HANDOFF_V1_SOURCES.md` (new)
- `docs/onyx/checkpoints/guild-handoff-v1/` (4 files, new)
- `tests/fixtures/phase5_current_successor_transition_v52.json` (new)
- `scripts/verify_phase5_exit_retirement_v1.py` (V52 constants + loader;
  V51 loader renamed historical)
- `scripts/verify_guild_handoff_v1_acceptance.py` (new)
- `docs/onyx/acceptance/VE-GUILD-HANDOFF-V1-E6-001.md` + `.manifest.json` (new)
- `docs/onyx/VE-ACCEPTANCE-GUILD-HANDOFF-V1-E6-001.sha256` (new)

## Change Log

- 2026-08-18: Draft created after A9.1 acceptance, same autonomous session.
