# Phase 10 Provider Connector V1 — E6 acceptance

- Evidence ID: `VE-P10-PROVIDER-CONNECTOR-V1-E6-001`
- Decision date: `2026-07-25`
- Decision: **ACCEPTED — default-off route-pinned read-only provider connector contract**
- Candidate manifest: `87b3ed60dd533f29e3b42447ada20846dda231f8b5f5478da59c9d7e1d822d0c`
- Artifact root: `7aba66ad246c75b1660c70c00dbf012526de72e1592892bee0fd1ea363a35711`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. This is the third Phase 10
slice: a default-off, route-pinned, read-only social provider connector contract,
entry-bound to the accepted Phase 10 editorial-calendar (`415bbc4d…`). Over an
injected transport it reads one approved provider's account status
(`ApprovedProviderV1 → ProviderAccountStatusV1`: handle, verified, follower count,
recent post ids) via a redirect-disabled HTTPS GET whose scheme, host, port,
userinfo, path, query, fragment and timeout must match the registry exactly.
Provider id, platform and scopes are attributed from the trusted registry, and a
response whose handle differs from the registry-declared `expected_handle` is
denied (anti-spoof). There is no publish method; the module opens no real network
in evidence, spawns no process, persists nothing and takes no action beyond a
route-pinned read. The gate reproduced **570 passed tests and 80 passed subtests,
0 failed and 0 errors** across twenty-six fresh Python processes; eight skips are
inherited, documented platform-specific Phase 7 contracts.

The three independent reviews ran adversarially. Integrity returned PASS: the
artifact root `7aba66ad` and all eight candidate artifacts recompute exactly, the
accepted editorial-calendar entry-bind is genuine, and no predecessor was
modified. Functional returned PASS: read-only with no publish method (machine-
checked), the anti-spoof handle check and the route pin are enforced and
behaviourally tested (off-route, port and query rejected without any network),
the origin grammar rejects userinfo/port/uppercase/unicode/single-label/leading-
hyphen, and the response payload is bounds-checked (verified bool, follower range,
recent-post-id cap, missing handle). The reviewer's one observation — that
`test_account_only` is stored but not enforced in this read-only slice — was
considered and kept: reading the registry-declared, handle-verified account's own
status is safe, and account-type enforcement belongs to the later owner-approved
publish slice. Quality returned PASS: the module reuses the accepted Phase 9
live-ingestion connector patterns and the Phase 10 slice idioms, and the verifier
machine-checks the source invariants, forbids publish-authority tokens, asserts
no publish method, and reproduces the twenty-six-file cumulative gate with a
per-file sum check.

Scope is deliberately a **read-only, route-pinned status read only**. No
publishing, audience research or community action is bound or claimed. The real
provider fetch is owner-gated (OAuth/app-review + test account) and remains
`BLOCKED_BY_ACCESS`; the contract is verified with an injected transport. This
acceptance live-wires no component, adds no action authority, and does not claim
the full Onyx PRD complete.
