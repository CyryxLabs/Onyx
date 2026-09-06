# Guild project envelope V1 — sources and design basis

Hermetic, deterministic governed-envelope contract. No external service is
used; the basis is the owner's directives and the accepted guild and
governance slices.

## Basis

- Owner directives (2026-08-17): Onyx as a virtual employee that develops
  income-producing projects autonomously, with outward action always
  owner-gated; and the termination rule — a project that does wrong or loses
  may cease to exist. Encoded here as a mandatory `DecommissionPolicyV1`
  with a closed `{revoke_and_decommission}` outcome vocabulary, a required
  kill-switch reference and a `max_consecutive_gate_failures >= 1` tolerance.
- Accepted guild chain: A9.1 (`VE-GUILD-PROFILES-V1-E6-001`) for team packs
  and authority, A9.4 (`VE-GUILD-EXECUTION-INTENT-V1-E6-001`) for the
  owner-gated intents an envelope may bind. Snapshots are consumed by exact
  type; nothing is redeclared.
- Accepted session grants V11 (`VE-P51-GRANTS-R11-E6-001`): supplies the
  micro-unit cost scale and the bounded-caps discipline this slice mirrors
  (`MAX_COST_MICRO`, per-mission caps).
- Planned governance couplings named in
  `CAPABILITY_COMPLETION_PLAN_90PCT.md`: approval inbox (A5), cost/quota
  observability (A15) and kill switch (A16) — the runtime slice that will
  own activation, spending, measurement and decommission execution.

## Design decisions

- **No unlimited budget** — strictly positive floor, absolute ceiling, and
  loss budget never above the cost cap.
- **No KPI-free project** — at least one declared, measurable KPI with a
  measurement reference.
- **No softer fate** — the outcome vocabulary is closed at
  `revoke_and_decommission` in V1, so an envelope cannot encode "warn and
  continue" before a runtime exists to adjudicate it.
- **No double binding** — an intent belongs to at most one envelope.
- **Inert projections** — `remaining_cost_micro` / `is_budget_breached` are
  arithmetic over a declared cap; `is_active()` is structurally False.
