# Phase 10 Brand Passport V1 — E6 acceptance

- Evidence ID: `VE-P10-BRAND-PASSPORT-V1-E6-001`
- Decision date: `2026-07-25`
- Decision: **ACCEPTED — default-off brand + social-account inventory contract**
- Candidate manifest: `5d0a4bd6c6b3a15b112bb86a95da96a5008b784704f511e3df57ab7043b3af0e`
- Artifact root: `6f218e78ca1be45218ae8bd25448666482714edd2cd5a087d4eace45654f2483`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. This is the first Phase 10
slice: a default-off, deterministic, hermetic registry over brand passports and
their social accounts, entry-bound to the accepted Phase 9 exit
(`90d19475…`). Every passport must carry the full set of always-on policy guards
(no follower buying, no bots/automation abuse, no fake personas, no competitor
copying, no fabricated testimonials/stats/logos); every account belongs to
exactly one brand, uses a platform inside that brand's allow-list, and a
`(platform, handle)` pair can be claimed only once. `can_publish` is structurally
always `False`. The module calls no model, opens no network, spawns no process,
persists nothing and takes no action. The gate reproduced **504 passed tests and
80 passed subtests, 0 failed and 0 errors** across twenty-four fresh Python
processes; eight skips are inherited, documented platform-specific Phase 7
contracts.

The three independent reviews ran adversarially. Integrity returned PASS: the
artifact root `6f218e78` and all eight candidate artifacts recompute exactly, the
accepted Phase 9 exit entry-bind is genuine, and no predecessor was modified.
Functional returned PASS-WITH-CONCERNS with a P2, remediated before acceptance:
the initial `(platform, handle)` separation rejected only cross-brand reuse, so
two account records could share a handle within one brand and produce an
ambiguous resolution; it was tightened to global one-claim-per-`(platform,
handle)` uniqueness (which strictly implies one-brand separation) and a dedicated
adversarial test was added, growing the suite 31→32. Quality returned PASS: the
module mirrors the accepted Phase 9 slice idioms (sealed factory, entry-bind,
frozen dataclasses, byte-bounded text contract), and the verifier machine-checks
the source invariants, forbids network/process/publish authority tokens, and
reproduces the twenty-four-file cumulative gate with a per-file sum check.

Scope is deliberately **inventory only**. No live provider connection,
publishing, audience research or community action is bound or claimed. The first
real publish per account remains a later owner-approved, access-gated slice
(`BLOCKED_BY_ACCESS` until OAuth/app-review plus a test account). This acceptance
live-wires no component, adds no action authority, and does not claim the full
Onyx PRD complete.
