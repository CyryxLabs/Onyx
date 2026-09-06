# Story ONYX-GUILD-A9.4 — Guild Execution-Intent Binding V1

**Status:** Done (accepted 2026-08-19, `VE-GUILD-EXECUTION-INTENT-V1-E6-001`,
root `68a4fc77…`; acceptance verifier reproduced the full 31-file gate
796/0/0/17/96 after the R15B soak passed; autonomous-session honesty
boundary recorded; matrix/ledger updates batched into the V54 pass)
**Epic:** Onyx Engineering Guild (A9 expanded)
**Predecessor:** `VE-GUILD-WORKFLOW-V1-E6-001` (A9.3, root `48043dee…`)

## Story

As the Cyryx Labs owner, I want guild workflow stages to bind to **Phase 11
project-autopilot mission intents** — exact, validated, version-pinned
records of *what would run* — so that the first real dispatch (a later
slice) can only ever execute an intent the guild substrate has already
authorized, and nothing else.

## Design sketch

Module `core/guild_execution_intent_v1.py`, flag
`ONYX_GUILD_EXECUTION_INTENT_V1`, default-off, deterministic, hermetic;
entry-bound to the A9.3 four-file acceptance tuple; consuming exact A9.1
registry, A9.2 ledger and A9.3 workflow snapshots.

- `AutopilotIdentityV1`: byte-pinned identity of the exact Phase 11
  autopilot version the intent targets (`core/phase11_project_autopilot_v1.py`
  path + SHA-256 + `MISSION_TYPE == "project_autopilot_v1"` literal) — an
  intent against a drifted autopilot is rejected, mirroring the release
  discipline of binding to exact bytes.
- `ExecutionIntentV1`: `intent_id`; (`run_id`, `stage_id`) naming an
  accepted A9.3 run whose **next** (not completed) stage matches — intents
  bind forward work only; `assigned_role_id` must hold the stage's required
  operation (registry-checked, exclusive owner sets respected);
  `story_id` consistency with the run; bounded `patch_scope` (workspace-
  relative path prefixes, no traversal/absolute/link grammar) and
  `gate_argv_shape` mirroring the autopilot's own validators; explicit
  `requires_owner_approval: True` — structurally always true in V1, the
  A5/approval-inbox coupling point.
- Sealed `GuildExecutionIntentLedgerV1`: unique intent ids; at most one
  open intent per (run, stage); **no dispatch surface** — the ledger
  validates and seals; `is_dispatchable()` is a projection that is
  structurally `False` in V1 (dispatch arrives only with the later
  MissionStore-coupled slice under session grants A9.5/A4, approval inbox
  A5, cost budgets A15 and the kill switch A16).

## Acceptance criteria (draft)

1. [ ] Contracts as designed; default-off; hermetic; no dispatch surface;
       `is_dispatchable` structurally False (verifier-asserted).
2. [ ] Autopilot identity pinning: drifted/missing autopilot bytes →
       Denied.
3. [ ] Forward-only binding: completed or out-of-order stages → rejected;
       run/story/assignee/authority consistency enforced via the A9.1–A9.3
       snapshots.
4. [ ] Patch-scope and gate-argv grammar: traversal, absolute paths,
       links, empty scopes → rejected.
5. [ ] `requires_owner_approval` cannot be False.
6. [ ] Entry-bind to A9.3 tuple; ≥30 adversarial tests; 31-file gate;
       standard chain + E6; honesty boundary as established.

## Out of scope

Dispatch/MissionStore coupling, session grants, budgets, decommission
(A9.5+), any live execution, non-engineering packs, runtime wiring.

## File List

- `docs/stories/ONYX-GUILD-A9.4.story.md` (this story)

## Change Log

- 2026-08-18: Designed after the descriptive substrate (A9.1–A9.3) was
  accepted; implementation deliberately awaits owner engagement.
