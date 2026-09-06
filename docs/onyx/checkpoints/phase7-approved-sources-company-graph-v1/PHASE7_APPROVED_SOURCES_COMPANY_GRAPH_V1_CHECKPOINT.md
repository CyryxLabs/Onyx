# Phase 7 Approved Sources + Company Graph V1 checkpoint

## Scope

This candidate implements the third and fourth ordered Phase 7 slices:
workspace/principal-scoped approved-source admission and a read-only,
source-grounded Company Graph. It depends on the accepted Workspace Memory V1
and Workspace Aliases V1 checkpoints and remains exactly default-off.

## Implemented contract

- immutable approved-source registration, exact get, bounded list and
  persistent revoke;
- canonical HTTPS metadata or exact accepted artifact-alias binding;
- HMAC-authenticated source policy, rights, sensitivity, diversity, validity,
  freshness and eight quality scores;
- source content is untrusted data with zero instruction authority;
- graph semantics for approved facts, current status, proposed/rejected/
  superseded decisions, hypotheses, risks, dependencies, metrics and evidence;
- every graph item carries source citation, owner, last verification,
  confidence, blockers, next milestone and definition of done;
- source lifecycle/sensitivity/freshness prefilters before evidence access;
- exact source/evidence/claim content, rights, credibility and workspace
  binding;
- explicit contradiction/supersession closure;
- completion requires supported authoritative verification evidence and cannot
  be inferred from an artifact alone;
- complete projection digest and zero graph writes, network, process, provider,
  browser, artifact-content or live-runtime calls.

## Proportional regression result

Seven fresh Python processes reproduced:

- 154 passed tests;
- 65 passed subtests;
- 0 failed;
- 0 errors;
- 8 explained platform skips.

The skips are limited to Windows absence of POSIX mode/FIFO/link-count/
quarantine/restart contracts. Windows-specific paths in those suites passed.

## Limits

This candidate is not live-wired and adds no runtime authority. It does not
fetch URLs, read artifact bytes, automatically discover contradictions,
produce freshness alerts, generate the Founder Brief, exit Phase 7 or complete
the Onyx PRD.

E6 remains pending until an independent acceptance envelope rehashes this
candidate and reproduces the full selection.
