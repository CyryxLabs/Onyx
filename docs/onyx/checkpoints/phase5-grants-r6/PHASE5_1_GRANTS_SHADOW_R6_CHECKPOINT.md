# Phase 5.1 Session Grants Shadow R6 Checkpoint

Status: candidate, default-off, shadow-only, not accepted.

External E6 remains pending and is required before any acceptance or live wiring.

## Scope

R6 is an isolated successor to the preserved V1-R5 evidence history. It does not import into or alter any live entrypoint, startup path, dashboard, provider adapter, owner surface, or existing authorization engine.

The feature flag remains `ONYX_GRANT_EVALUATOR`, with a default value of false. Decisions remain advisory: `callback_required=True` and `authority_granted=False` are immutable.

## Receipt authenticity and exact binding

Every reservation receives a store-generated unpredictable receipt challenge. A verified outcome cannot commit by status or booleans alone. The pinned host receipt-verifier callback must return the exact concrete `HostReceiptVerification` type.

The store recomputes and constant-time compares the complete binding across:

- receipt challenge;
- reservation ID;
- grant ID;
- canonical scope digest;
- exact action-binding digest;
- action audit digest;
- idempotency key;
- structurally sequence-bound provider receipt ID;
- result digest;
- exact canonical receipt digest;
- structurally sequence-bound receipt ID;
- canonical host-verification digest.

All-zero and all-`f` reserved SHA-256 values are rejected at untrusted digest boundaries. Callback exceptions, subclasses, malformed structures, echo drift, and digest drift fail closed.

## Replay and idempotency

Host receipt sequences must increase strictly. Receipt IDs bind sequence and challenge. Provider receipt IDs bind sequence and result digest. The high-water receipt sequence survives bounded receipt cleanup, while recent receipt digests and provider identities remain bounded by `MAX_RECEIPTS`.

For each grant and exact binding, an idempotency key has three states:

- available;
- pending while one reservation exists;
- consumed after one verified commit.

Cancellation, denial, unverified receipt, reservation expiry, drift, and terminal controls release pending state. A verified commit consumes it for the remaining grant/session lifetime. Concurrent reservation and duplicate-outcome races are serialized under the store lock.

## Canonicalization

R6 additionally rejects ambiguous POSIX paths beginning with `//`. URI percent escapes may not encode unreserved characters, encoded separators, backslashes, or dot aliases. Allowed percent escapes use uppercase hexadecimal form; lowercase aliases are rejected as noncanonical.

## Evidence boundary

The focused R6 suite contains 96 passing cases covering inherited R1-R5 invariants plus R6 receipt binding, replay, idempotency, concurrency, canonicalization, exact-type, callback, capacity, cleanup, snapshot, drift, secret, and default-off behavior.

The R6 verifier:

- reconstructs and executes the preserved V1-R5 evidence chain;
- derives the exact recursive normative graph, including `docs/MISSIONS.md` and all five cited ADRs;
- requires named JUnit cases for material receipt, replay, idempotency, and canonicalization claims;
- executes Ruff F/E9 live with cache disabled;
- compiles the four authoritative R6 source files in memory without bytecode writes;
- executes the R6 whitespace checker live;
- scans the declared authoritative live entrypoint set for R6 imports or use;
- verifies the canonical bundle, environment, base commit, timestamp, limits, dependency closure, and acyclic SHA-256 manifests.

This checkpoint is not external acceptance, production authorization, or permission to wire R6 live.
