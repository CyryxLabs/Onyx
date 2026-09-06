# Phase 7 Approved Sources + Company Graph V1 — E6 acceptance

- Evidence ID: `VE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001`
- Decision date: `2026-07-23`
- Decision: **ACCEPTED — default-off source policy and read-only graph**
- Candidate manifest:
  `fa5fea91caf6914e559cbc22420841b602eeace0153653dc57591fb0070f23f3`
- Artifact root:
  `d9efc2186412abbf95a1cd03b901c5f797bcb7c50e6b3a6d256211dd2eeac1c3`

## Decision

Approved Sources + Company Graph V1 is accepted as the third and fourth
ordered Phase 7 slices. Findings are `P0=0`, `P1=0`, `P2=0`, and `P3=0`.

The independent gate:

- rehashed all nine candidate artifacts and recomputed the artifact root;
- rehashed and interpreted the four accepted Workspace Aliases V1 entry
  roots;
- reproduced exact default-off return-before-host-binding behavior;
- executed approved-source, graph, Domain Ledger, alias, control-plane,
  workspace and artifact suites in fresh Python processes;
- reproduced **154 passed tests, 65 passed subtests, 0 failed, 0 errors**;
- reproduced eight explained Windows platform skips for POSIX-only contracts;
- confirmed zero URL fetch, artifact-content read, graph persistence,
  network/process/provider/browser/live call or startup seam.

## Accepted behavior

The accepted source registry:

- binds sources to one active non-legacy workspace, principal, initialized
  control-plane connection and host integrity key;
- stores immutable HMAC-authenticated authority, rights, sensitivity,
  canonical citation, diversity, eight quality scores, validity and freshness;
- treats every source as untrusted data with no instruction authority;
- uses canonical HTTPS locators only as metadata and reattests artifact aliases
  without reading bytes;
- provides immutable idempotent create, bounded reads and persistent
  non-resurrecting revoke.

The accepted Company Graph:

- distinguishes approved fact, current status, evidence, metric, hypothesis,
  dependency, risk and proposed/rejected/superseded decisions;
- requires exact Domain Ledger claim/evidence/source binding and returns a
  deterministic read-only projection;
- attaches owner, verification time, confidence, blockers, next milestone,
  DoD and citations to every item;
- checks source sensitivity, lifecycle and freshness before evidence access;
- refuses to hide declared contradictions or supersessions;
- refuses `verified_complete` based only on an artifact and instead requires
  supported authoritative verification evidence, explicit DoD and no
  blockers;
- hashes every operational, provenance, relationship, freshness and trust
  field returned by the projection.

## Limits retained

- Both components remain default-off and are not wired to V13, startup, voice,
  UI or the dashboard.
- The registry does not fetch URLs or read artifact bytes.
- The graph projects exact caller-supplied ledger-bound assertions; automatic
  contradiction discovery and portfolio freshness alerts remain unimplemented.
- Founder Brief remains unimplemented.
- Phase 7 is not exited and the full Onyx PRD is incomplete.

The next slice may implement contradiction/freshness analysis and a cited
Founder Brief over these accepted boundaries without widening runtime
authority.
