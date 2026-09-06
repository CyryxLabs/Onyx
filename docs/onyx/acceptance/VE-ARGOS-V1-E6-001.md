# Argos V1 — E6 acceptance

- Evidence ID: `VE-ARGOS-V1-E6-001`
- Decision date: `2026-08-19`
- Decision: **ACCEPTED — default-off proprietary world-signal registry**
- Candidate manifest: `docs/onyx/checkpoints/argos-v1/manifest.json`
- Artifact root: `11f51eb86be4e9e953bf0df0e7740683a291ec2f83c641b7054a0fe201738d62`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. This is the first
Argos slice: the 100% proprietary Cyryx Labs world-intelligence foundation
that replaces the dropped third-party World Monitor, from which nothing is
copied. `core/argos_v1.py` (`ONYX_ARGOS_V1`, default-off, deterministic,
hermetic) is entry-bound to the accepted Phase 9 exit four-file acceptance
tuple. It enforces registered, rights-noted sources (a source without a
`rights_note` cannot be registered; a signal citing an unregistered source
is rejected), closed taxonomies (eight signal categories, four source
kinds), injected integer `observed_at` with no clock read, severity and
confidence bounded 1–5 under exact-type discipline (bool rejected), and
deterministic ranking (severity×confidence descending, id ascending) in
`signals_for` and a bounded `brief`. `is_actionable()` is structurally
`False` — Argos informs, it never acts, inheriting the accepted Phase 9
rule verbatim. The module calls no model, opens no network, spawns no
process, persists nothing and takes no action. The gate reproduced **868
passed tests and 96 passed subtests, 0 failed and 0 errors** across
thirty-three fresh Python processes (seventeen explained platform-specific
skips).

Verification passes executed (2026-08-18/19, fresh processes): integrity —
artifact root `11f51eb8` and all eight candidate artifacts recompute
exactly; the Phase 9 exit entry-bind is genuine; functional — the
citation, rights-note, taxonomy, bounds, ranking and sealed-construction
gates are enforced and adversarially tested (35 tests), and actionability
is structurally false (machine-asserted); quality — mirrors the accepted
slice idioms; the verifier machine-checks both taxonomies, forbids
network/process/publish/fetch authority tokens and reproduces the
thirty-three-file gate with a per-file sum check.

**Honesty boundary.** All verification passes were executed autonomously in
the owner-authorized session (@devops). No independent human review
occurred. Matrix/ledger documentation updates are batched into the next
documentation-authority pass. Scope is the registry and deterministic
briefs only — no live fetching (the owner-gated Phase 9 live-ingestion
connector remains the only later path to real network), no provider
adapters, no scheduling, no action surface, no runtime wiring, and the
full Onyx PRD is not claimed complete. World-intelligence as a *live*
capability remains unproven; this acceptance covers the first-party
substrate that a later owner-gated run would populate.
