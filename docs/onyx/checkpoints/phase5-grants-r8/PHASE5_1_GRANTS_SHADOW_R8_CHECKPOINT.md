# Phase 5.1 Session Grants Shadow R8 Checkpoint

Status: candidate, default-off, shadow-only, not accepted. External E6 review and an externally anchored evidence root remain mandatory before acceptance or live wiring.

## R8 review closure

- The grant-independent external idempotency identity now permanently binds one immutable action fingerprint. The fingerprint covers provider namespace, account, tool and operation, exact target identity, payload and binding digests, stable action contract, and exact declared action cost.
- Every ledger state retains that fingerprint. Pending, uncertain, consumed, definitive-no-effect, and cancelled-before-dispatch identities reject a different target, payload, binding, action contract, or cost. Released states can retry only the identical external action.
- Each accepted reconciliation advances a unique internal revision and sequence and rolls a cryptographic history root. Callback completion compares the captured revision token, preventing same-clock ABA and double application.
- Reconciliation history is bounded by ledger identities: each identity retains only its latest audit record plus rolling root, count, and latest host sequence. Existing uncertainty remains resolvable even at declared capacity. Resolved history is compacted into the durable ledger and, for confirmed effects, the immutable receipt.
- Direct and reconciled zero-cost commits share identical exhaustion semantics. A zero aggregate cap is not considered exhausted by a zero-cost action. Revocation reasons are a closed validated set.
- Reconciliation and public mutating control methods are strictly feature-flag gated. Removing `ONYX_GRANT_EVALUATOR` leaves uncertainty unchanged and invokes no reconciliation callback.
- Returned dispatch or verified-effect material is durably quarantined before any subsequent fallible clock or state snapshot. Outcome, receipt, state, and verifier failures preserve a self-sufficient uncertain record that remains reconcilable.

## Evidence scope

- Focused R8 semantic, concurrency, reconciliation-capacity, zero-cost, default-off, and post-outcome-failure tests are captured as JUnit and raw evidence.
- V1-R7 source and evidence remain byte-identical and are reconstructed through the frozen R7 verifier.
- The recursive normative graph remains 20 nodes, including root `readme.md` fallback and its recursive references.
- The unwired live scan remains recursive over `main.py`, `ui.py`, `dashboard`, `actions`, `memory`, `runtime`, `qml`, `packaging`, and `core`, excluding tests, evidence, and every `session_grants_v*.py`. Exact paths and hashes are frozen separately.
- Compile, Ruff `F,E9`, canonical whitespace, semantic AST, dependency closure, exact evidence DAG, historical reconstruction, and live unwired gates are re-run by the R8 verifier.

## Acceptance boundary

R8 grants no authority, suppresses no trusted callback, and is not wired into startup, UI, runtime, provider, packaging, or owner paths. The feature flag remains default-off. External E6 acceptance and external root anchoring are still pending.
