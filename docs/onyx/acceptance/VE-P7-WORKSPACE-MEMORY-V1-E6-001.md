# Phase 7 Workspace Memory V1 — E6 acceptance

- Evidence ID: `VE-P7-WORKSPACE-MEMORY-V1-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED — default-off read-only workspace memory slice**
- Candidate manifest:
  `59ed88abd6967a73f3050d1215fed0c278b21b5c6e5335814abe8267576c9cd7`
- Artifact root:
  `fafe2c2fb2c0d0f55f0ce6fc6824b71a93c42f3527565449986e90ba1fb09f95`

## Decision

Workspace Memory V1 is accepted as the first isolated Phase 7 implementation
slice. Findings are `P0=0`, `P1=0`, `P2=0`, and `P3=0`.

The independent gate:

- rehashed all seven candidate artifacts and recomputed the artifact root;
- rehashed the accepted aggregate Phase 6 entry envelope;
- reproduced exact default-off return-before-entry validation;
- executed the focused, legacy memory, workspace registry, workspace security,
  and workspace audit suites in fresh Python processes;
- reproduced **77 passed, 73 passed subtests, 0 failed, 0 errors**;
- reproduced the single explained Windows platform skip because POSIX FIFO
  creation is unavailable;
- confirmed there is no global legacy search/list call, provider/network/
  process/live call, persistent write, runtime seam, or restricted-memory
  route.

## Accepted behavior

The accepted adapter:

- resolves signed workspace/principal/sensitivity/validity/freshness metadata
  before content access and ranking;
- opens the existing memory database read-only and fetches only authorized
  IDs;
- denies metadata forgery, duplicate JSON, content drift, binding drift and
  ambiguous cross-workspace ownership;
- excludes stale records by default and labels explicitly requested stale
  results;
- returns provenance, validity, exact legacy-row digest and
  `content_trust=untrusted_data`.

## Limits retained

- V1 remains default-off and is not wired to V13, startup, voice, UI or the
  dashboard.
- V1 provides no authoritative metadata writer, candidate promotion,
  supersession/contradiction writer, credential/profile/artifact aliases,
  approved-source registry, Company Graph or Founder Brief.
- Phase 7 is not exited.
- No full Onyx PRD completion is claimed.

The next slice may implement typed aliases and the approved-source registry on
top of this accepted retrieval boundary without weakening pre-ranking policy.
