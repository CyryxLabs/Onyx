# Phase 5.3 Capability Nexus V2 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V2 supersedes the rejected V1 candidate without changing or importing it. V1
remains byte-exact historical evidence. V2 is additive and isolated: startup,
`main.py`, the dispatcher, permission broker, UI, dashboard, launcher, providers,
ports, feature flags, session grants and Approval Inbox candidates do not import
or invoke it.

## Corrective scope

1. Registry discovery, health and snapshots now require exact workspace,
   account and profile identity. The profile participates in descriptor,
   projection, snapshot, request, receipt and signed cursor digests. Cross-profile
   discovery, projection construction and cursor replay fail closed.
2. Descriptor metadata is restricted to five declared safe keys with bounded
   string values. Secret-name normalization covers case, punctuation and percent
   encoding. Values reject assignments, PEM/JWT shapes and obvious percent/base64
   encodings. Nested secret-bearing parameter schemas also fail. Credentials are
   opaque aliases only; values are never accepted or projected.
3. `CapabilityNexusV2` accepts only the exact concrete frozen
   `NexusFeatureGateV2`. Subclasses, duck types and fakes fail. The immutable
   gate precedes the registry lock; the adapter never acquires a registry lock.
   Descriptors and projections still cannot authorize or dispatch.
4. `LocalCatalogReadAdapterV2` uses a bounded no-replay correlation ledger. It
   atomically reserves the immutable request/page/quota/rate slot as `pending`,
   releases its lock, then invokes the read hook. The same correlation and digest
   observes/reconciles existing state without invoking the hook again; digest
   drift denies. Success commits a deterministic receipt. Hook exception,
   cancellation/timeout after hook start, kill/revoke race or expired pending
   becomes `uncertain`. Cancellation/timeout/denial before hook rolls back quota
   and rate reservation. Uncertain expiry creates a retained non-replay
   tombstone. Total, pending and uncertain cardinalities are independently
   bounded.

## Verification

- Focused V2 contract/adversarial suite: 47 passed.
- Combined Phase 5 regression: 249 passed.
- Stable regression suite: 102 passed plus 221 subtests.
- Ruff, compilation, whitespace and scoped diff gates pass.
- The live-source manifest freezes the runtime boundary and rejects any V2
  reference.
- The V2 verifier checks current legacy declaration/policy parity, exact V1
  historical bytes, and a disposable V1 core tamper fixture that must fail its
  expected hash.

## Locking and reconciliation

The declared order is `gate_immutable_state -> registry_lock -> adapter_lock`.
No code path holds registry and adapter locks together. Neither the read hook nor
the injected monotonic clock is invoked while an adapter/registry lock is held.
Reentrant hook tests call adapter health and same-correlation read from the hook;
both terminate without deadlock and the hook count remains one.

`pending`, `completed`, `uncertain`, cancelled/timeout-before-hook, denied,
rate-limited, expired-uncertain and unknown-correlation are explicit. Unknown or
uncertain work is never retried automatically.

## Rollback and limitations

Rollback requires no migration: stop explicit development/test imports of V2.
The existing dispatcher remains authoritative and unchanged.

- V2 is not live, authoritative, persisted or wired to a provider, vault or MCP.
- The catalog is constructor-allowlisted, provider-free metadata only.
- Completed local reads have receipts; no external OAuth, webhook or mutation
  reconciliation is claimed.
- Total-ledger capacity intentionally fails closed instead of evicting a
  correlation and risking replay; restart clears this process-local fixture.
- V1 remains rejected; V2 does not retroactively accept it.
- External E6 and the complete Phase 5 exit remain pending independent review.
