# Phase 5.1 Session Grants Shadow R7 Checkpoint

Status: candidate, default-off, shadow-only, not accepted. External E6 review and an externally anchored evidence root remain mandatory before acceptance or live wiring.

## R7 safety closure

- The external-mutation identity is independent of grant and binding identities. It is scoped by session, workspace, provider, provider namespace, account, tool, operation, and idempotency key.
- The bounded durable ledger distinguishes `pending_before_dispatch`, `uncertain_needs_reconciliation`, `consumed_verified`, `definitive_no_effect`, and `cancelled_before_dispatch`.
- `mark_dispatch_attempted` moves a reservation into durable uncertainty before the host attempts the external effect. Absence, timeout, callback failure, drift, revocation, kill, audit failure, and session termination cannot release that identity.
- Only a definite pre-dispatch cancellation, a definite no-effect outcome, or a pinned reconciliation result of `confirmed-no-effect` makes an identity retryable.
- Pinned reconciliation uses a fresh challenge, exact typed request echoes, structural sequence-bound identifiers, response digests, and receipt replay barriers. `confirmed-effect` consumes the identity with a complete immutable receipt; `still-uncertain` remains quarantined.
- Grant generations are scoped. Revoking grant A does not invalidate grant B. Global semantic drift still blocks an in-flight commit after dispatch and leaves the identity uncertain.
- Receipt and uncertainty records retain the full external-mutation context, action/scope digests, cost, timestamps, verification state, and provider evidence after grant cleanup.

## Evidence scope

- Focused R7 semantic tests are captured as JUnit and raw key/value evidence.
- R1-R6 evidence is revalidated byte-for-byte through the frozen R6 verifier. No historical source or evidence file is rewritten.
- The normative Markdown graph is derived recursively. Bare references first try the referring document directory and then the repository root, which includes the root `readme.md` and its recursive references.
- The live-surface scan recursively covers `main.py`, `ui.py`, `dashboard`, `actions`, `memory`, `runtime`, `qml`, `packaging`, and `core`; it excludes tests, evidence, and historical `session_grants_v*.py`. The exact discovered path set and every byte hash are frozen in a dedicated manifest.
- Compile, Ruff `F,E9`, canonical whitespace, semantic AST, dependency closure, evidence DAG, and live unwired gates are re-run by the R7 verifier.

## Acceptance boundary

R7 grants no authority, does not suppress any trusted callback, and is not wired into startup, UI, runtime, provider, packaging, or owner paths. The `ONYX_GRANT_EVALUATOR` flag remains default-off. External E6 acceptance and an external root anchor are still pending.
