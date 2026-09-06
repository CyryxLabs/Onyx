# Phase 5.3 Capability Nexus V4 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V4 is a new self-contained candidate. It supersedes rejected V1, V2 and V3
without importing or modifying them. No startup, dispatcher, UI, provider,
feature flag, grant, Approval Inbox or port path imports V4.

## Minimal corrective delta

V4 preserves every V3 profile, gate, cursor, projection, ledger, no-replay and
bounded metadata decoding contract. Its behavioral delta is limited to:

- Bounded recognition of common raw OpenAI, GitHub, AWS, Stripe and Google
  credential shapes plus Bearer and valid Basic authentication payloads at every
  decoded representation. Tight family-specific length and alphabet bounds keep
  documented near-misses valid.
- Deterministic NFKC/confusable skeleton scanning for protected secret vocabulary,
  including Cyrillic and Greek lookalikes. Structured metadata rejects mixed
  scripts; unsupported invisible, bidi and combining tricks fail closed while
  unstructured international display metadata remains valid.
- A per-adapter, per-thread guard active only around the external read hook.
  Nested reads on the same adapter fail before request reservation, quota, rate
  or hook execution. Cleanup is unconditional and independent calls on other
  threads remain valid. No host callback runs under an adapter or registry lock.
- Recursive verification of the exact rejected V1/V2/V3 manifest DAGs, bounded
  cycle-safe traversal of every leaf, execution of all three frozen verifiers
  and disposable tamper probes for V1/V2 checkpoint, bundle, JUnit, raw and
  static leaves plus the V3 core.

## Verification

- Focused V4 suite: 108 passed.
- Combined Phase 5 suite: 426 passed.
- Current stable mission/regression suite: 162 passed plus 265 subtests.
- Frozen V1, V2 and V3 verifiers pass; 36 historical manifests and 220 unique
  recursive leaves verify against their exact hashes.
- Ruff, compilation, whitespace and scoped diff checks pass.
- Exact V1/V2/V3 bytes remain bound as rejected history.

## Rollback and limitations

Rollback requires no migration: remove explicit test/development imports of V4.
The live dispatcher remains unchanged.

- V4 is not live, authoritative, persisted or connected to provider/OAuth/MCP.
- The catalog remains process-local, metadata-only and mutation-free.
- Full ledger fails closed without eviction, preventing correlation replay.
- Confusable mapping is deliberately finite and security-scoped, not a general
  Unicode transliteration service.
- V1, V2 and V3 remain rejected; this candidate cannot accept itself.
- External E6 and complete Phase 5 exit remain pending independent review.
