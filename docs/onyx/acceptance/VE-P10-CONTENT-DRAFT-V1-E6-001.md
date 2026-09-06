# Phase 10 Content Draft V1 — E6 acceptance

- Evidence ID: `VE-P10-CONTENT-DRAFT-V1-E6-001`
- Decision date: `2026-07-25`
- Decision: **ACCEPTED — default-off content-draft + provenance/policy contract**
- Candidate manifest: `f57046e1f65de10484b8ef31c706323683fd57952076d164dd0395150fdba8ff`
- Artifact root: `59308ada89f691443238644bdb18b7bc29aa66a61365b95908bc5631d8b8d449`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. This is the fourth Phase 10
slice: a default-off, deterministic, hermetic content-draft and provenance
contract, entry-bound to the accepted Phase 10 provider connector (`7aba66ad…`).
It enforces asset provenance (`original`/`licensed`/`authorized`, with
licensed/authorized requiring a `rights_ref`), claim validation (a validated
claim cites evidence, and an `approved` draft has every claim validated — the
anti-fabrication gate), accessibility (every image/video asset carries
`alt_text`), and a brand/policy review gate (`approved` requires a positive policy
review). `published` is not a representable status and there is no publish or
schedule method; `is_ready_for_calendar` is a readiness predicate only. The module
calls no model, opens no network, spawns no process, persists nothing and takes no
action. The gate reproduced **607 passed tests and 80 passed subtests, 0 failed
and 0 errors** across twenty-seven fresh Python processes; eight skips are
inherited, documented platform-specific Phase 7 contracts.

The three independent reviews ran adversarially. Integrity returned PASS: the
artifact root `59308ada` and all eight candidate artifacts recompute exactly, the
accepted provider-connector entry-bind is genuine, and no predecessor was
modified. Functional returned PASS: the provenance, claim-validation,
accessibility and policy-review gates are enforced and adversarially tested, and
`published` is structurally unrepresentable with no publish/schedule method. The
reviewer confirmed the slice does not over-claim: the PRD's "no competitor
copying" principle is caught by the human policy-review gate, not asserted as
automated detection; disclosure is a readiness (not an approval) requirement, as
in the editorial-calendar slice. Quality returned PASS: the module mirrors the
accepted Phase 10 slice idioms (sealed factory, entry-bind, frozen dataclasses,
byte-bounded text contract), and the verifier machine-checks the source
invariants, forbids network/process/publish/schedule authority tokens, asserts
`published` is not a status, and reproduces the twenty-seven-file cumulative gate
with a per-file sum check.

Scope is deliberately **drafting, provenance and policy-gating only**. No
publishing, live provider action or analytics is bound or claimed. Publishing/
scheduling and the live provider run remain later gated slices
(`BLOCKED_BY_ACCESS`). This acceptance live-wires no component, adds no action
authority, and does not claim the full Onyx PRD complete.
