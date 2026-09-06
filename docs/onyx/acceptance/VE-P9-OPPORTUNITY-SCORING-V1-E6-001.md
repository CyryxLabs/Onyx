# Phase 9 Opportunity Scoring V1 — E6 acceptance

- Evidence ID: `VE-P9-OPPORTUNITY-SCORING-V1-E6-001`
- Decision date: `2026-07-24`
- Decision: **ACCEPTED — default-off transparent opportunity-scoring contract**
- Candidate manifest: `9249c37f825d07f21860f82296c9eeee2dee9cf4e9948aa7d0e75230e6e68d85`
- Artifact root: `519d1e40710210dbc4527954964dc9551efc977911b9c9eec03f8b2c38b6c097`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=1` (advisory only). This is
the second Phase 9 slice: a pure deterministic, default-off transparent
opportunity scorer over the twelve PRD dimensions, each with a fixed published
weight and an explicit benefit/cost direction (cost/risk dimensions inverted),
normalised with deterministic integer rounding to a `0..100` total, mapped to a
fixed band ladder, and returned with the complete per-dimension breakdown, a
`low_confidence` flag and a batch rank. It calls no model, opens no network,
persists nothing and takes no action — a score can never trigger a trade. The
gate rehashed eight candidate artifacts and reproduced **454 passed tests, 80
passed subtests, 0 failed and 0 errors** across twenty-two fresh Python
processes; eight skips are inherited platform-specific Phase 7 checks.

The three independent reviews ran adversarially. Functional returned a clean
PASS: gating, scoring math, cost inversion, band ladder, batch ranking, input
validation, determinism and purity were all confirmed correct, with only three
informational notes (all-raw-zero scores 29 not 0 because cost dimensions
invert; the half-up rounding tie cannot occur at the fixed weight scale; the
ingestion-evidence SHA pins are the intended governance seal). Integrity
returned PASS: the artifact root and all closure hashes recompute exactly, the
verifier re-runs the real gate, the ingestion entry-binding genuinely gates and
no predecessor was modified. Quality returned PASS-WITH-CONCERNS with two P2
test-adequacy gaps proven by mutation testing — the band boundaries at exactly
40/60/80 were untested, and cost-dimension direction was pinned only for one of
the four cost dimensions because the tests derived the cost set self-referentially
— plus P3 nits (per-dimension weights pinned only in aggregate and two `_text`
branches untested).

All actionable findings were remediated before acceptance. Tests now pin the
band ladder at each exact boundary (via the `_band` function), pin the cost and
benefit dimension sets and every per-dimension weight independently of the
`DIMENSIONS` tuple, assert per-cost and per-benefit direction individually, and
exercise the non-str and oversize `_text` branches for both id and title,
growing the suite from thirteen to fifteen; the ADR now records that the half-up
rounding reduces to nearest-integer at the fixed weight scale. The sole residual
P3 is advisory: the module keeps an unraised base error class for API symmetry
with the sibling ingestion slice, and the all-raw-zero input scores 29 by design
(only benefits-zero/costs-max is the true floor) — both documented.

Accepted scope: the transparent opportunity-scoring contract only — fixed-weight
benefit/cost dimensional scoring, deterministic normalisation, band mapping,
transparency breakdown, low-confidence flagging and batch ranking. It remains
exactly default-off and unwired. It adds no live source fetching, no
model-assisted or learned weighting, no opportunity clustering, no autonomous
acting on a score and no World Monitor connector (which stays
`BLOCKED_BY_LICENSE`); it can never turn a signal into a trade or other action;
and it claims no Phase 9 exit and no full Onyx PRD completion.
