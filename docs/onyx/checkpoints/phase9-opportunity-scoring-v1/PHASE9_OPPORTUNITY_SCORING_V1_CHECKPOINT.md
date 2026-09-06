# Phase 9 opportunity scoring V1 checkpoint

This exactly default-off candidate adds the transparent opportunity-scoring
contract, the second Phase 9 slice. Behind the flag
`ONYX_PHASE9_OPPORTUNITY_SCORING_V1`, a pure deterministic session scores an
opportunity from twelve integer dimension scores (`0..5`) — pain/economic cost,
urgency, buyer/payability, timing, competition, Cyryx advantage, time to
MVP/revenue, complexity, distribution, moat, legal/platform risk and evidence
confidence — using a fixed documented weight and an explicit benefit/cost
direction per dimension. Cost/risk dimensions are inverted (`SCORE_MAX - raw`),
weighted points are summed and normalised with deterministic integer half-up
rounding to a `0..100` total, and mapped to a fixed band ladder
(`watch`/`consider`/`pursue`/`priority`). Each result exposes the full
per-dimension breakdown (raw, direction, effective value, weight, earned points,
maximum points), a `low_confidence` flag and a batch rank (total descending,
`opportunity_id` ascending tie-break).

The slice calls no model, opens no network, persists nothing and takes no
action — a score is advisory data only and can never trigger a trade. It is
built through a sealed factory that returns `None` when the flag is unset and
otherwise entry-binds to the accepted intelligence ingestion evidence by
SHA-256.

Fifteen focused tests cover exact gating and default-off, sealed-factory and
ingestion entry-binding (both the missing-evidence and hash-drift branches),
perfect and worst-case scores, cost-dimension inversion, transparent breakdown
with total-reconciliation, the band ladder at each exact boundary
(39/40, 59/60, 79/80), independently pinned dimension directions and per-dimension
weights with per-cost and per-benefit direction checks, the low-confidence flag,
batch ranking with an id tie-break and input-order preservation, duplicate and
oversize batch rejection, malformed-score rejection (non-dict item/scores,
missing/extra dimension, out-of-range, bool-as-int, float, empty/non-str/oversize
id, NUL/oversize title), determinism with the twelve-dimension invariants, and a
source scan proving no network/model/action primitives.

The cumulative selection reproduces 454 passing tests and 80 passing subtests
across twenty-two fresh Python processes, with eight inherited, explained
platform-specific skips and zero failure/error.

Limits: contract only. No live source fetching, model-assisted or learned
weighting, opportunity clustering, autonomous acting on a score, World Monitor
connector (licence-gated) or runtime wiring is added, and no Phase 9 exit or
full Onyx PRD completion is claimed.
