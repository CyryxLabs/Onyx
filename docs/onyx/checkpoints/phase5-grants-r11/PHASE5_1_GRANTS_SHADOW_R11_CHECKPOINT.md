# Phase 5.1 Session Grants Shadow R11 Checkpoint

Status: candidate, default-off, shadow-only, not accepted. External E6 review and an externally anchored evidence root remain mandatory before acceptance or live wiring.

## R11 review closure

- Gate authority is one exact concrete `MonotonicFeatureGate`; `HostServices` rejects subclasses and callback substitutes. Raw environment state is accepted only by the gate constructor as strict default-off bootstrap input.
- Atomic store mutations acquire the gate lease before the store lock. Every public operation linearizes entry and final mutation against the same monotonic feature epoch.
- Host callbacks run with neither gate nor store lock held. A bounded two-thread host-lock/store-snapshot regression demonstrates that host re-entry into `snapshot_counts()` cannot form an AB/BA deadlock.
- `record_outcome(reservation_id, outcome_ref)` quarantines the reservation and idempotency identity before the effect-observing outcome callback, including direct calls without a prior dispatch mark.
- Callback revocation, feature epoch ABA, malformed outcome material, or a cancellation claim cannot release or downgrade the quarantine. Verified outcome material and verification audit evidence are persisted before later fallible callbacks.
- Definitive no-effect reconciliation is the only release path. Verified effect converts provisional accounting exactly once, while old-epoch uncertainty remains reconcilable without grant resurrection.

## Evidence scope

- Focused R11 authority, lock ordering, callback sequencing, direct-outcome quarantine, revocation, malformed response, epoch ABA, reconciliation, receipt, accounting, and recovery tests are captured as JUnit and raw evidence.
- The V1-R11 cross-version grant suite passes as a separate regression gate with 583 tests.
- V1-R10 source and evidence remain byte-identical and are reconstructed through the frozen R10 verifier.
- The recursive normative graph remains 20 nodes. The exact 76-path live scan still includes `scripts`, `.pyw`, and the operational launcher while excluding tests, evidence, historical phase verifiers, and historical session-grant shadows.
- Compile, Ruff `F,E9`, canonical whitespace, semantic AST, dependency closure, exact evidence DAG, historical reconstruction, launcher inclusion, and live unwired gates are re-run by the R11 verifier.

## Acceptance boundary

R11 grants no authority and is not wired into startup, UI, runtime, provider, launcher, packaging, or owner paths. The feature gate remains strict default-off. External E6 acceptance and external root anchoring are still pending.
