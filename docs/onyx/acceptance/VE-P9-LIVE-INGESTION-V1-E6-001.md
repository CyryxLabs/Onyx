# Phase 9 Live Ingestion V1 — E6 acceptance

- Evidence ID: `VE-P9-LIVE-INGESTION-V1-E6-001`
- Decision date: `2026-07-25`
- Decision: **ACCEPTED — default-off, route-pinned live-source ingestion connector contract**
- Candidate manifest: `0def1781c9e98c50d6728bfdec54b3866fdd5bb392a89af9ef068ff20bb7ae29`
- Artifact root: `fc1611e4ac1c896a637bab525df0d066e2eecf7f860f8f0766f4312c6f920d6a`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=1` (advisory only). This is the
third Phase 9 slice: a default-off connector that fetches only from an injected
approved-source registry over a route-pinned, redirect-disabled HTTPS client,
bounds the response and item counts, never auto-retries, and attributes source
id, health tier and category from the trusted registry — never from the fetched
feed — before handing ingestion-ready raw items to the accepted intelligence
ingestion contract. **The real network fetch against live sources is not
exercised by this acceptance**: it is owner-gated (source registration, egress,
consent) and deferred, exactly as the accepted Phase 8 live connector runs were;
the contract is verified with an injected transport. The gate rehashed eight
candidate artifacts and reproduced **472 passed tests, 80 passed subtests, 0
failed and 0 errors** across twenty-three fresh Python processes; eight skips are
inherited platform-specific Phase 7 checks.

The three independent reviews ran adversarially. Integrity returned PASS: the
artifact root recomputes exactly, the suite and verifier are hermetic (no real
network — `FakeHttp` and RFC 6761 `.test` fixtures only), the scoring
entry-binding genuinely gates and no predecessor was modified. Functional
confirmed the two governance-critical invariants hold — the feed cannot spoof
its own source id/tier and cannot steer the route (redirects fail closed) — with
no P1, and raised a P2: the approved-source `origin` grammar was weaker than the
documented "bare host" invariant, so a userinfo origin (`good.test@evil.test`)
passed the `netloc == origin` pin while urllib would connect to `evil.test`
(operator-triggered, not feed-triggered), plus P3s (loose `path` grammar, an
unvalidated response dataclass, and a feed-relabelable item category). Quality
returned PASS-WITH-CONCERNS with two P2 test-adequacy gaps proven by mutation —
redirect-disable was asserted only by string scan, and the whole real-transport
parse/error path (`_strict_json`, oversize cap, HTTPError decode) was
unexercised — plus P3s (item-cap boundary and response validation).

All actionable findings were remediated before acceptance. The `origin` grammar
is now a strict bare-lowercase-ASCII-host regex (rejecting userinfo, port,
unicode, empty labels and leading/trailing hyphens) and the `path` grammar an
absolute ASCII dot-segment-free path; the route-pin additionally checks
`hostname == origin` with no port or userinfo; `LiveJsonResponseV1` validates its
status and payload on construction; item `category` is now attributed from the
trusted source, never the feed; and six behavioural tests were added — the opener
suppresses redirects (a mutation that unwires the no-redirect handler now fails),
the real client's success/oversize/HTTPError/URLError decode paths, `_strict_json`
size/duplicate-key/non-object/invalid enforcement, the item-cap accepting
boundary, response-dataclass validation, and category authority — growing the
suite from twelve to eighteen. The verifier's authority scan additionally
forbids named POST/`while True` idioms. The sole residual P3 is advisory: the
feed-field oversize and missing-value `_text` branches are exercised only
indirectly (via the empty and NUL cases) and the registry >512-entry cap is
untested (trivial).

Accepted scope: the connector contract only — approved-source allowlist with
grammar-validated origin/path, a route-pinned redirect-disabled HTTPS GET client,
registry-attributed source health and category, bounded strict parsing with no
auto-retry, and composition into the accepted ingestion contract. It remains
exactly default-off and unwired, and the live network fetch is owner-gated and
deferred. It adds no claim typing/dedup/corroboration (the accepted ingestion
contract does this), no opportunity scoring, no model-assisted parsing and no
World Monitor connector (which stays `BLOCKED_BY_LICENSE`); a fetched item is
data only and can never become a trade; and it claims no Phase 9 exit and no full
Onyx PRD completion.
