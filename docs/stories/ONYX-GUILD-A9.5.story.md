# Story ONYX-GUILD-A9.5 — Guild Governed Project Envelope V1

**Status:** Done (accepted 2026-08-19, `VE-GUILD-PROJECT-ENVELOPE-V1-E6-001`,
root `438fe075…`; acceptance verifier reproduced the full 34-file gate
910/0/0/17/96; 42 adversarial tests; autonomous-session honesty boundary
recorded; matrix/ledger updates batched into the next documentation pass)
**Epic:** Onyx Engineering Guild (A9 expanded — final slice)
**Predecessor:** A9.4 (`VE-GUILD-EXECUTION-INTENT-V1-E6-001`, pending seal)

## Story

As the Cyryx Labs owner, I want every guild project wrapped in a **governed
envelope** — hard cost and loss budgets, declared KPIs, and my termination
rule as an executable decommission policy — so that autonomous work is
always bounded, measured, and killable, and continuation is something a
project earns with evidence, never assumes.

## Design sketch

Module `core/guild_project_envelope_v1.py`, flag
`ONYX_GUILD_PROJECT_ENVELOPE_V1`, default-off, deterministic, hermetic;
entry-bound to the A9.4 four-file acceptance tuple; consuming exact
A9.1–A9.4 snapshots.

- `ProjectBudgetV1`: cost caps in micro-units mirroring the accepted
  session-grants discipline (`MAX_COST_MICRO` scale), plus a loss budget
  and per-mission use caps; zero/negative caps rejected; **budgets are
  hard**: an envelope cannot express an unlimited budget.
- `ProjectKpiV1`: declared, measurable KPI records (metric id, target,
  measurement ref) — continuation evidence, never marketing claims.
- `DecommissionPolicyV1` (the owner's rule as mechanism): mandatory
  fields — `max_consecutive_gate_failures` (≥1), `on_budget_breach` and
  `on_kpi_failure` drawn from the closed vocabulary
  `{revoke_and_decommission}` in V1 (no softer option is representable),
  and `kill_switch_ref` non-empty. A policy that omits or weakens any of
  these is rejected — "se fizer errado ou perder, pode deixar de existir"
  as a type-level fact.
- `ProjectEnvelopeV1`: project id, owning team pack (must exist in the
  A9.1 registry), bound intents (must exist in the A9.4 ledger snapshot,
  each still `requires_owner_approval`), budget, KPIs, decommission
  policy; `is_active` structurally False in V1 — activation, spending,
  measurement and the decommission EXECUTION belong to the runtime slice
  that will couple session grants (A4), the approval inbox (A5), cost
  observability (A15) and the kill switch (A16), each already accepted or
  planned in the 90% plan.
- Sealed `GuildProjectLedgerV1` + projections only; no
  dispatch/activation surface (machine-asserted).

## Acceptance criteria (draft)

1. [ ] Contracts as designed; default-off; hermetic; `is_active`
       structurally False; no execution surface.
2. [ ] Decommission policy: missing/weakened fields rejected; closed
       vocabulary enforced; kill-switch ref mandatory.
3. [ ] Budgets: unlimited/zero/negative rejected; micro-unit scale caps.
4. [ ] Envelope coupling: unknown team pack, unknown intent, intent
       without owner-approval flag → rejected.
5. [ ] Entry-bind to A9.4 tuple; ≥30 adversarial tests; 32-file gate;
       standard chain + E6; honesty boundary as established.
6. [ ] Matrix/ledger updates in the following documentation-authority
       pass.

## Out of scope

Runtime activation, real spending/measurement, decommission execution,
MissionStore/grant/inbox live coupling, non-engineering packs, live calls.

## File List

- `docs/stories/ONYX-GUILD-A9.5.story.md` (this story)

## Change Log

- 2026-08-18: Drafted while the R15B soak runs; implementation queued
  behind the A9.4 seal.
