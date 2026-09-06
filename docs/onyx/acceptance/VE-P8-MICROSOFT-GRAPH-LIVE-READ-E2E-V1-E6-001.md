# Phase 8 Microsoft Graph Live Read E2E V1 — E6 acceptance

- Evidence ID: `VE-P8-MICROSOFT-GRAPH-LIVE-READ-E2E-V1-E6-001`
- Decision date: `2026-07-23`
- Decision: **ACCEPTED — default-off live read-only E2E harness contract**
- Candidate manifest: `63e2ff3a059aeb1c856ca73ad80ac523aac99aa33162fc200ce0fee47dcdc104`
- Artifact root: `30bdd9e3bf1bde4effa1acb7147fcd714d763c6fcc017e6b23fe189fcfabef6b`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=9` (advisory only). The
first independent functional review returned three P2 findings (revocation
probe could certify a provider-failure terminal, exported throttle wrapper
accepted an unusable `max_retries` 3-5 range, and `report_sha256` did not bind
the `read_only` field). All three were fixed with new adversarial tests and
independently re-confirmed closed; the integrity and quality reviews then
re-verified the corrected bytes. The gate rehashed ten candidate artifacts and
reproduced **337 passed tests, 80 passed subtests, 0 failed and 0 errors** in
fifteen fresh Python processes. Eight skips are the previously accepted
platform-specific Phase 7 checks.

Accepted scope covers secret-free Microsoft Entra public-client onboarding
from the environment with fail-closed rejection of credential-shaped
variables; a throttle-aware transport wrapper honoring `429 Retry-After`
exactly (including the RFC 9110 zero-delay immediate retry), deterministic
bounded backoff (2s, 4s) when the header is absent, a two-wait retry bound
with typed failure, and no retry of non-429 responses; redacted transport
observations; a six-probe harness over the frozen OAuth V1 and Read V1
contracts (sign-in/read, access expiry forcing refresh, refresh rotation,
terminal-denial revocation classification, provider failure without automatic
retry, rate-limit Retry-After honoring); exact-type sealing of the `live`
probe mode to the real stdlib HTTPS transport; and a hash-bound redacted
report with explicit `probes_missing` and strict `live_verified` semantics.

Open P3 advisories, none acceptance-blocking: tautological account re-checks
inside three probes; no `__post_init__` on direct report construction; the
fixed four-name secret-environment list; runner store-cleanup/input/traceback
hygiene; runner report directory not gitignored; per-run control-plane sandbox
accumulation; the predecessor acceptance-verifier script not being hash-bound
in any closure (established convention); no in-verifier selection sum
cross-check; and candidate-stage self-anchoring inherent to E1-E5 status.

V1 remains exactly default-off and unwired. No Microsoft Entra application,
client ID, tenant consent or test account exists, so live identity/Graph E2E
remains `BLOCKED_BY_ACCESS` with the exact owner steps documented in
`docs/onyx/PHASE8_MICROSOFT_GRAPH_LIVE_ONBOARDING.md`. Provider failure and
real throttling cannot be forced against the live service; their behavior is
contract-proven and live reports must list unexecuted probes in
`probes_missing`. It adds no provider mutation, startup/voice/UI/dashboard
wiring, Phase 8 aggregate exit or full Onyx PRD completion.
