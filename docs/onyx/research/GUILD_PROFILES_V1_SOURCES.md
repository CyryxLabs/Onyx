# Guild profiles V1 — sources and design basis

Hermetic, deterministic role-profile registry. No external service is used; the
basis is the owner's directive, the first-party AEXOS framework and the target
architecture's Operator Cells design.

## Directive and design basis

- Owner directive (2026-08-17): Onyx as the owner's virtual employee replacing
  ~10 whole squads across company areas, with AEXOS as the base; autonomous
  production, owner-gated publication; termination ("decommission") as an
  executable mechanism. Recorded in
  `docs/onyx/CAPABILITY_COMPLETION_PLAN_90PCT.md` (A9 expanded) and
  `docs/stories/ONYX-GUILD-A9.1.story.md`.
- `TARGET_ARCHITECTURE.md` §4.6 Operator Cells: versioned, governed role
  profiles with capability and model registries — the slot this slice fills.

## AEXOS source (first-party)

- Local install surveyed 2026-08-17: `C:\MAAX_Assistant\.aexos-core` —
  12 agent personas (`development/agents/*.md`, markdown with embedded YAML
  carrying `agent`, `persona`, `exclusive_authority` and
  `responsibility_scope`), 5 team packs (`development/agent-teams/*.yaml`),
  214 task files, 15 workflows, checklists and Constitution v1.1.0.
- Canonical origin: `https://github.com/CyryxLabs/aexos-engine.git` — Cyryx
  Labs first-party work; no third-party license obligation beyond the
  standard provenance record (Onyx is proprietary; AEXOS is same-owner IP).
- Constitution v1.1.0 Article II ("Agent Authority", NON-NEGOTIABLE) is the
  authority ground truth this contract encodes as
  `MANDATORY_CONSTITUTIONAL_EXCLUSIVES`.

## Design decisions (each governance rule encoded as an invariant)

- **Constitutional floor** — Article II claims must be reproduced exactly;
  missing owners, unclaimed operations, wrong or extra claimants all reject.
- **One-claim exclusivity with owner sets** — claimants form the owner set
  (supporting co-owned operations like `story_creation` → `po`/`sm`); a
  non-owner listing an exclusively-claimed operation is an authority leak and
  rejects.
- **Closed delegation graph** — delegations must target an existing, distinct
  role that holds the operation, mirroring the AEXOS delegation matrix
  ("ANY agent → @devops *push").
- **Byte-pinned provenance** — profiles/packs carry the exact SHA-256 of
  their AEXOS source bytes; the sealed snapshot recomputes a deterministic
  pack root, so later slices can entry-bind to an exact ingested pack.
- **No orchestration surface** — validation and projection only; execution,
  sessions, grants and budgets arrive in later, separately gated slices.
