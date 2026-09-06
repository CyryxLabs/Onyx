# Phase 5.1 Session Grants Shadow R10 Checkpoint

Status: candidate, default-off, shadow-only, not accepted. External E6 review and an externally anchored evidence root remain mandatory before acceptance or live wiring.

## R10 review closure

- Operational gate authority is a host-owned `FeatureGateSnapshot(enabled, epoch)` supplied by an explicit monotonic tracker. The environment flag is only a strict default-off bootstrap; it is not claimed to detect invisible ABA transitions.
- Every disable or re-enable transition advances the host epoch. Every grant binds its issuance epoch into the grant and attestation. Observing a disabled or newer epoch permanently revokes older active grants with a closed reason while preserving dispatched uncertainty.
- Epoch state is revalidated between monotonic clock and state callbacks and immediately after grant/action/outcome resolvers, approval, receipt verification, and reconciliation. Off/on ABA aborts before another callback or non-revocation mutation. A malformed reconciliation returned with an epoch change cannot trigger an additional fail-closed mutation.
- Pending reservations and uncertain external actions retain provisional use and cost against their original grant. Evaluation and reservation include both sets. Confirmed-no-effect releases provisional capacity; confirmed-effect converts it into committed accounting exactly once.
- Self-sufficient uncertain and receipt records retain the original maximum uses, aggregate cost, and grant epoch. Reconciliation rejects any effect that would exceed those immutable limits.
- Quarantined external actions from a revoked old epoch may reconcile only while the gate is enabled in a newer epoch. Settlement records receipts and accounting without restoring the old grant.

## Evidence scope

- Focused R10 epoch-ABA, callback sequencing, malformed response, multi-binding provisional capacity, concurrency, reconciliation, receipt, and recovery tests are captured as JUnit and raw evidence.
- The V1-R10 cross-version grant suite passes as a separate regression gate.
- V1-R9 source and evidence remain byte-identical and are reconstructed through the frozen R9 verifier.
- The recursive normative graph remains 20 nodes. The exact 76-path live scan still includes `scripts`, `.pyw`, and the operational launcher while excluding tests, evidence, historical phase verifiers, and historical session-grant shadows.
- Compile, Ruff `F,E9`, canonical whitespace, semantic AST, dependency closure, exact evidence DAG, historical reconstruction, launcher inclusion, and live unwired gates are re-run by the R10 verifier.

## Acceptance boundary

R10 grants no authority and is not wired into startup, UI, runtime, provider, launcher, packaging, or owner paths. The feature flag remains default-off bootstrap. External E6 acceptance and external root anchoring are still pending.
