# Onyx capability completion plan — the 90% release gate

Status: **adopted by owner directive, 2026-08-17** ("antes de criar o instalador,
precisamos chegar em pelo menos 90%").

Document class: forward plan. It does not alter any accepted evidence, any
frozen candidate, or the precedence defined in `DOCUMENTATION_INDEX.md`.
Capability truth remains `CAPABILITY_MATRIX.md`; release truth remains
`CURRENT_RELEASE_STATUS.md`. Formalizing this gate inside
`FORMAL_RELEASE_CONTRACT.md` is a separately reviewed edit (planned below).

## The rule

> **No new release candidate is frozen while capability coverage is below 90%.**

- **Metric:** rows in the current section of `CAPABILITY_MATRIX.md` whose
  status is `WORKING_AND_VERIFIED` or `WORKING_WITH_LIMITATIONS`, divided by
  all current rows. Rows may be added over time; the ratio is computed against
  the matrix as it stands at freeze time, never against a trimmed subset.
- **Scope of the gate:** release candidacy only. Engineering builds and
  installs remain allowed at any coverage — several matrix rows can only be
  proven on an installed host, so builds are the verification vehicle, not the
  release.
- **Unaffected absolutes:** the public-distribution license gate
  (`BLOCKED_BY_LICENSE`, fail-closed) is independent of this percentage and
  can never be satisfied by coverage arithmetic.
- **1.1.9 R15B status under this rule:** grandfathered as an internal
  validation baseline only (its pipeline was already in its final gate when
  the rule was adopted). It is not, and was never, public-release eligible.

## Baseline (2026-08-17)

69 current rows:

| Status | Rows |
|---|---|
| `WORKING_AND_VERIFIED` | 16 |
| `WORKING_WITH_LIMITATIONS` | 20 |
| `PARTIAL` | 19 |
| `BLOCKED_BY_ACCESS` | 7 |
| `NOT_IMPLEMENTED` | 4 |
| `BLOCKED_BY_LICENSE` / `BLOCKED_BY_PLATFORM` / `HEALTH_ONLY_FAIL_CLOSED` | 3 |

**Coverage: 36/69 = 52.2%. Target: ≥ 62/69 = 89.9%. Distance: +26 rows.**

## Track A — advanceable by engineering alone (no external access)

Each item follows the standard evidence chain (module → adversarial tests →
ADR → checkpoint → candidate verifier → independent E6) and stays default-off
until its own gate. Estimated movable rows: **~20**.

| # | Row (matrix) | From → To | Work |
|---|---|---|---|
| A1 | Workspace registry/isolation | PARTIAL → verified | Shadow dual-read proof, then governed activation slice |
| A2 | Mission context sidecar | PARTIAL → verified | Startup integration + rollback gate |
| A3 | Evidence/claims/action ledgers | PARTIAL → verified | Production wiring slice (still no external mutation) |
| A4 | Bounded session grants | PARTIAL → verified | Exact low-risk enablement slice |
| A5 | Approval inbox | PARTIAL → verified | Read-only integration checkpoint into UI |
| A6 | Capability Nexus registry | PARTIAL → verified | Remaining live-integration gates |
| A7 | MCP client/server | NOT_IMPLEMENTED → verified | One local read-only MCP adapter (accepted P6 contract exists) |
| A8 | Provider/model router | PARTIAL → verified | Live/text parity + rollback gates |
| A9 | Operator Cells | NOT_IMPLEMENTED → verified | One provider-free research/verifier profile pair |
| A10 | Company Graph | PARTIAL → verified | Bind to governed retrieval/projection gates |
| A11 | Founder Brief/portfolio command | PARTIAL → verified | Bind to accepted executive-office intake |
| A12 | Intelligence claim pipeline | PARTIAL → (near) verified | Conflicting-claim evaluation slice (live fetch is B4) |
| A13 | **Argos world-intelligence** | NOT_IMPLEMENTED → first accepted slice | Proprietary build, standard evidence chain |
| A14 | Unified Command Center projections | PARTIAL → verified | Read-only mission/approval/evidence projections |
| A15 | Cost/quota/quality observability | PARTIAL → verified | Typed usage events + hard policy budgets |
| A16 | Kill switch / incident response | PARTIAL → verified | Control-plane kill state, fail-closed service checks |
| A17 | Nighttime Knowledge Refinery | NOT_IMPLEMENTED → limited | Local provider-free sources, candidate-only writes |
| A18 | M1a canonical Windows activation | BLOCKED_BY_PLATFORM → verified | Re-run canonical probe under the real installed-user token (R15B install exists) |
| A19 | Native packaging definitions | PARTIAL → limited | Lock dependencies + inventory (signing stays in license gate) |
| A20 | Phase 10 deterministic slices 5+ | strengthens rows 117–120 | Audience/trend research, 30/60/90 strategy, funnel/KPI, experiment ledger |

Also carried here: Phase 6 aggregate exit E6 and Governed Away Mode E6/installed
proof — they harden existing rows even where the row label already counts.

### A9 expanded — Onyx Engineering Guild (AEXOS-based Operator Cells)

Owner directive 2026-08-17: Onyx must gain software-architect / AI-architect /
dev / devops / QA / scrum-master skills so it can develop projects
autonomously, with AEXOS as the base. This lands exactly in the Operator
Cells slot (`TARGET_ARCHITECTURE.md` §4.6) and expands A9 into a sub-track.
AEXOS assets (personas, task files, workflows, checklists, constitution,
delegation matrix) become **data** consumed by a governed role-profile
engine — after standard provenance/license verification per
`OPEN_SOURCE_AND_API_LICENSE_REVIEW.md` discipline, since Onyx is proprietary.
Canonical AEXOS source: `https://github.com/CyryxLabs/aexos-engine.git`
(Cyryx Labs first-party).

Owner reference vision (2026-08-17): Onyx as the owner's **virtual employee
replacing ~10 whole squads** across company areas — engineering, copy,
design, legal, data, paid traffic, story/content, cyber, product/PM,
support. The guild engine is therefore domain-agnostic: role-profile packs
are data, and the owner's existing AEXOS/AIOX squad definitions load as
additional packs once the engineering pack has proven the engine.

| Slice | Content | Builds on |
|---|---|---|
| A9.1 Role-profile registry + authority matrix | Versioned governed profiles (architect/dev/qa/devops/sm-pm) with exclusive authorities mirroring the AEXOS delegation matrix (e.g. only the devops cell may push; dev commits locally; qa owns gates). Deterministic, provider-free, default-off. | Capability Nexus contracts |
| A9.2 Handoff + story contracts | AEXOS handoff artifact (compact YAML) and story lifecycle as typed mission context; story states map to mission states. | Mission store/sidecar (A2) |
| A9.3 SDC workflow engine | Story Development Cycle (create → validate → implement → QA gate) and the bounded QA loop (max-iteration, escalation) as mission templates with pre/postconditions. | Mission worker + result verification |
| A9.4 Execution binding | Guild cells bound to Phase 11 Project Autopilot: sandboxed execution, execution ledger, clean-git authority, worktree isolation, draft-PR lifecycle. External coding-agent dispatch stays fail-closed until receipts exist. | Phase 11 autopilot; code helper |
| A9.5 Governed away-mode projects | Long-running project missions under bounded session grants, approval-inbox checkpoints, per-mission cost budgets and the kill switch. First publish/deploy/spend of any project is always an explicit owner approval. | A4, A5, A15, A16 |

Revenue honesty: the guild lets Onyx **ideate, build, test and present**
shippable candidates with the standard evidence chain. Shipping, deploying,
charging money and marketing remain owner-gated (and marketing/distribution
additionally depends on the B6–B8 access unlocks). Autonomous production,
gated publication — never autonomous spending or publication.

Termination rule (owner-mandated, 2026-08-17: "se fizer errado ou perder,
ele poderá morrer ou deixar de existir"): encoded as mechanism, not
sentiment — every cell and project carries hard KPIs and loss budgets
(A15); repeated quality-gate failure or budget breach triggers automatic
authority revocation and grant expiry (A4/A16); constitutional violations
block immediately; and decommission ("death") of a cell or project
instance is an executable control-plane action reserved to gates and the
owner. Continuation is earned with evidence, never assumed.

## Track B — requires the owner

**B-quick (minutes each; unlocks 5 rows):** one-time Microsoft OAuth consents
plus one confirmed live run each, under the already-accepted contracts:

| # | Row | Consent scope | Proof |
|---|---|---|---|
| B1 | Email connector | `Mail.ReadWrite` + `Mail.Send` | One confirmed exact-recipient live send E2E |
| B2 | Calendar connector | `Calendars.ReadWrite` | One confirmed exact-grant event-create E2E |
| B3 | Tasks/notifications | `Tasks.ReadWrite` | One confirmed task-create E2E |
| B4 | Drive/office connector | `Files.Read` | One confirmed live listing E2E |
| B5 | Intelligence live fetch | egress consent to registered sources | One owner-gated live ingestion run |

**B-external (start immediately — lead time is not ours):**

| # | Row | Owner action |
|---|---|---|
| B6 | Social publishing/analytics + provider live read | Meta (then LinkedIn/TikTok/X) developer app + app review + **test account** |
| B7 | Community/inbox operations | Provider messaging scopes/webhooks (same app review) |
| B8 | Paid-media reporting (read-only first) | Marketing/Google Ads developer token + sandbox account |
| B9 | Signing certificates (Windows; Apple later) | Purchase/enroll — feeds the license gate, not the 90% number |

## The arithmetic to 90%

36 (today) + ~20 (Track A) + 5 (B-quick) = **61/69 = 88.4%**
… + any **one** B-external unlock (e.g. first Meta test-account read, or
paid-media read-only reporting) = **62/69 ≈ 90%**.

Conclusion: 90% = *all of Track A* + *all five Microsoft consents* + *at least
one external provider unlock*. That is why B6–B8 must be **started now**, in
parallel, even though their timelines belong to the providers.

Rows allowed to remain blocked inside the 10% allowance (≤7): flight booking,
paid-media mutation, Codex CLI adapter, Google Antigravity adapter, Claude
Code billable dispatch, and whichever of B6/B7 has not cleared review.

## Sequencing

1. **Now (during the 1.1.9 R15B soak):** this plan; no heavy work on the host
   until the pipeline consolidates (~03:40).
2. **Next session:** consolidate 1.1.9 evidence + update release docs; then
   open Track A with the Engineering Guild as the spine: A9.1 → A9.5 in
   order, pulling A4/A5 forward as its governance dependencies and
   interleaving the smaller slices (A20, A13 Argos, A7 MCP) between guild
   slices; then A1–A3, A6, A10–A17, A18–A19 — one accepted slice at a time.
3. **Owner, this week:** B1–B5 consents (one sitting), and file B6/B8
   applications so review clocks start.
4. **At ≥62/69:** freeze the 1.2.0 release candidate; only then does a new
   installer become a *release* candidate under this gate.
5. **Formalization:** add the gate text to `FORMAL_RELEASE_CONTRACT.md` via a
   reviewed edit in the next documentation pass.
