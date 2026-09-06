# Guild execution-intent V1 — sources and design basis

Hermetic, deterministic execution-intent contract. No external service is
used; the basis is the accepted guild slices, the Phase 11 autopilot's own
discipline, and the owner's governance directives.

## Basis

- Owner directives (2026-08-17): autonomous production with owner-gated
  outward action; termination/decommission as executable mechanism. Encoded
  here as `requires_owner_approval` structurally `True` and
  `is_dispatchable()` structurally `False` — dispatch can only arrive with
  the slice that carries grants (A4/A9.5), approval inbox (A5), budgets
  (A15) and the kill switch (A16).
- Accepted guild chain: A9.1 (`VE-GUILD-PROFILES-V1-E6-001`), A9.2
  (`VE-GUILD-HANDOFF-V1-E6-001`), A9.3 (`VE-GUILD-WORKFLOW-V1-E6-001`) —
  registry/ledger/workflow snapshots consumed by exact type; stage
  authority and run/story coupling reused, never redeclared.
- Phase 11 project autopilot (`core/phase11_project_autopilot_v1.py`,
  `PARTIAL` in the capability matrix): mission type
  `project_autopilot_v1`; its exact-bytes, trusted-path and bounded-gate
  discipline is mirrored by pinning the module bytes (185,305 B, SHA-256
  `a5dc26eb…`) and by the closed patch-scope/argv grammar.

## Design decisions

- **Pin the target, not just the chain** — the intent's meaning depends on
  the autopilot version; byte-drift denies construction (release-style
  exact-artifact discipline applied to an internal dependency).
- **Forward-only, single open intent per stage** — intents are bindings for
  the next unit of work, never a backlog or a history rewrite.
- **Structural gates over configuration** — approval-required and
  non-dispatchable are type-level facts in V1, not settings.
