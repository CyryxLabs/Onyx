# Phase 9 Intelligence Ingestion V1 — E6 acceptance

- Evidence ID: `VE-P9-INTELLIGENCE-INGESTION-V1-E6-001`
- Decision date: `2026-07-24`
- Decision: **ACCEPTED — default-off deterministic intelligence ingestion contract**
- Candidate manifest: `2d7650b305b203ce9c74e576652d8221b4dac2498d37c7450ab365325e04a78f`
- Artifact root: `977132cea3f9316bb1b7a62ecc4c8368da6f2a12a7e65a62b9d5511a833cbb6a`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=1` (advisory only). This is
the first Phase 9 slice: a pure deterministic, default-off contract that records
publication and event time separately, denies a future publication time,
computes freshness, deduplicates recycled stories, types each claim against a
closed fact/inference/scenario/recommendation set, tags source health and marks
a consequential claim corroborated only when it cites a source distinct from the
item's own. It fetches no source, opens no network, calls no model, persists
nothing and takes no action. The gate rehashed eight candidate artifacts and
reproduced **439 passed tests, 80 passed subtests, 0 failed and 0 errors** in
twenty-one fresh Python processes; eight skips are inherited platform-specific
Phase 7 checks.

The three independent reviews ran adversarially. Integrity returned PASS first
pass: the artifact root recomputes exactly, the verifier re-runs the real gate,
the Phase 8 exit entry-binding genuinely gates, no predecessor was modified and
the selection counts are honest. Functional returned PASS-WITH-CONCERNS with a
P2 — the recycled-story signature tokenised with an ASCII-only class, so
non-Latin-script headlines (Cyrillic, CJK, Arabic) collapsed to one false
duplicate cluster per category — plus a P3 (the `MAX_*_BYTES` limits enforced a
character count, not a byte count) and an informational note on ISO date-only
leniency. Quality returned PASS-WITH-CONCERNS with test-adequacy gaps (the
equal-publication tie-break, the entry-bind hash-drift branch, the
corroborating-source-id bounds and the future-event-time allowance were
unexercised) plus code nits (a dead `SCHEMA` constant, an unreachable freshness
clamp and an O(n²) canonical lookup).

All actionable findings were remediated before acceptance. The signature now
tokenises with the Unicode word class (with a whitespace-collapsed fallback for
symbol-only headlines), so non-Latin headlines dedup by content and stay
distinct across categories; `_text` now enforces the UTF-8 byte budget; the dead
`SCHEMA` constant and the unreachable freshness clamp were removed; the canonical
incumbent lookup is now an O(n) dictionary; and seven focused tests were added
(non-Latin dedup, equal-publication tie-break, entry-bind hash-drift, future
event acceptance, freshness-zero boundary, corroborating-source-id bounds, and
the non-dict-claim / byte-length / non-int-clock branches), growing the suite
from eleven to eighteen. The sole residual P3 is advisory and documented: the
ISO parser accepts a bare date and coerces it to `00:00:00+00:00`, and the
internal result dataclasses are validated procedurally at the sealed session
boundary rather than in each `__post_init__` — both intended and recorded in the
sources note.

Accepted scope: the ingestion-normalisation contract only — temporal
separation, recycled-story dedup, closed claim typing, source-health tagging,
freshness and consequential-claim corroboration over already-collected items. It
remains exactly default-off and unwired. It adds no live source fetching, no
opportunity scoring, no conflicting-claim detection, no general open-text/NLP
claim understanding and no World Monitor connector (which stays
`BLOCKED_BY_LICENSE`); it can never turn an item into a trade or any other
action; and it claims no Phase 9 exit and no full Onyx PRD completion.
