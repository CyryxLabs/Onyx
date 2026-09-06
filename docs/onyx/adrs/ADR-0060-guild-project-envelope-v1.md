# ADR-0060 — Guild governed project envelope V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

The owner's directive for the Engineering Guild carries an explicit
termination rule: a project that does wrong or loses may cease to exist. A
rule stated in prose is sentiment; a rule encoded in types is mechanism. With
authority (A9.1), work records (A9.2), workflows (A9.3) and execution intents
(A9.4) accepted, the remaining substrate is the envelope that bounds a
project: what it may spend, what it must achieve, and what happens when it
fails.

## Decision

Add `core/guild_project_envelope_v1.py`, default-off
(`ONYX_GUILD_PROJECT_ENVELOPE_V1`), deterministic, hermetic, entry-bound to
the accepted A9.4 four-file acceptance tuple and consuming exact A9.1 and
A9.4 snapshots. It enforces, structurally:

1. **Hard budgets.** `cost_cap_micro` and `loss_budget_micro` are integers in
   the accepted session-grants micro-unit scale with a strictly positive
   floor and an absolute ceiling; the loss budget may never exceed the cost
   cap; `max_missions` is bounded. An unlimited budget is not representable.
2. **Declared KPIs.** Every envelope carries at least one `ProjectKpiV1`
   naming a metric, a non-negative integer target and a measurement
   reference. Continuation is earned with evidence, never assumed.
3. **Decommission policy as mechanism.** `DecommissionPolicyV1` is mandatory
   and complete: `max_consecutive_gate_failures >= 1`, a non-empty
   `kill_switch_ref`, and both `on_budget_breach` and `on_kpi_failure` drawn
   from the closed vocabulary `{"revoke_and_decommission"}`. In V1 no softer
   outcome exists in the type, so an envelope cannot express "warn and
   continue".
4. **Owner-gated intents.** Bound intents must exist in the A9.4 snapshot,
   must still declare `requires_owner_approval`, and no intent may be claimed
   by two envelopes.
5. **Inert in V1.** `is_active()` is structurally False. `remaining_cost_micro`
   and `is_budget_breached` are pure arithmetic projections over a declared
   cap — never permissions. Activation, real spending, measurement and
   decommission *execution* belong to the runtime slice that couples session
   grants, the approval inbox, cost observability and the kill switch.

The module calls no model, opens no network, spawns no process, persists
nothing and takes no action.

## Consequences

- The guild substrate is complete: a future runtime slice can only activate
  projects that already carry hard budgets, declared KPIs and an executable
  decommission policy.
- The owner's termination rule becomes machine-checkable: a project without
  a kill-switch reference or with a softened outcome cannot be constructed.
- Any regression in the budget, KPI, decommission or intent-coupling gates,
  the entry-bind or the cumulative gate fails the slice verifier.

## Alternatives considered

- A richer outcome vocabulary (`warn`, `pause`, `revoke`): rejected for V1 —
  the owner's rule is decommission, and a wider vocabulary would let a
  project encode a softer fate before any runtime exists to adjudicate it.
  Widening belongs to a later, separately reviewed slice.
- Optional budgets for "exploratory" projects: rejected — an unbounded
  autonomous project is precisely the failure mode this slice prevents.
- Executing decommission here: rejected — revocation touches grants and the
  kill switch, so it belongs to the runtime slice that owns both.
