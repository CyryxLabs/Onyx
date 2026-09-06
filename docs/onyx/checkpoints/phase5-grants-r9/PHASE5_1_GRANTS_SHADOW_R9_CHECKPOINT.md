# Phase 5.1 Session Grants Shadow R9 Checkpoint

Status: candidate, default-off, shadow-only, not accepted. External E6 review and an externally anchored evidence root remain mandatory before acceptance or live wiring.

## R9 review closure

- Every public operation takes an exact raw feature-token lease while holding the store lock. Callback and mutation paths resample that lease after callbacks and immediately before final state changes; a removed, disabled, or textually changed token aborts with no later callback or mutation.
- Grant issuance, action evaluation and reservation, receipt commit, reconciliation, owner revocation, terminal controls, and snapshot reads have deterministic toggle tests. Callback failure after a token change cannot trigger a fail-closed mutation.
- The false reconciliation cardinality limit and separate reconciliation collection are removed. Reconciliation history remains compact and bounded exclusively by durable mutation-ledger identities using a rolling root, count, and latest sequence.
- Exact valid verifier material is persisted immediately after receipt verification and before the later fallible commit snapshot. The uncertainty record retains the verification digest, audit digest, verified bit, sequence, receipt ID, and challenge and can complete through reconciliation after a snapshot failure.
- The nonwiring surface now scans `scripts` recursively and includes `.pyw`. The operational `scripts/launch_onyx.pyw` launcher is required, hashed, compiled, and proven free of R9 wiring tokens.

## Evidence scope

- Focused R9 semantic, failure, token-toggle, reconciliation, concurrency, and post-verifier recovery tests are captured as JUnit and raw evidence.
- V1-R8 source and evidence remain byte-identical and are reconstructed through the frozen R8 verifier.
- The recursive normative graph remains 20 nodes, including root `readme.md` fallback and its recursive references.
- The exact recursive live-surface path set and hashes are frozen separately, excluding tests, evidence, historical phase verifier scripts, and every historical `session_grants_v*.py` shadow implementation.
- Compile, Ruff `F,E9`, canonical whitespace, semantic AST, dependency closure, exact evidence DAG, historical reconstruction, launcher inclusion, and live unwired gates are re-run by the R9 verifier.

## Acceptance boundary

R9 grants no authority, suppresses no trusted callback, and is not wired into startup, UI, runtime, provider, packaging, launcher, or owner paths. The feature flag remains default-off. External E6 acceptance and external root anchoring are still pending.
