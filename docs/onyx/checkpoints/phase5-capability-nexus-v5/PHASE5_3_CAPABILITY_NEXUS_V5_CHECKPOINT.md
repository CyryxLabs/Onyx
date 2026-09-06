# Phase 5.3 Capability Nexus V5 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V5 is a new self-contained candidate preserving rejected V1–V4 byte-for-byte.
It has no live/startup, dispatcher, UI, provider, flag, grant, Approval Inbox or
port wiring.

## Minimal corrective delta

- Precise bounded credential shapes cover OpenAI, GitHub and `github_pat`, AWS,
  Stripe, Google, Slack, npm, SendGrid, Twilio-like API key SIDs, Bearer and valid
  Basic authentication. A bounded opaque detector requires length, four character
  classes and entropy; hexadecimal digests and documentation near-misses remain
  valid. Every decoded intermediate is scanned.
- Every scalar string in recursive schema maps/lists/tuples passes the full
  normalization and credential policy. ASCII field identifiers are mandatory;
  non-ASCII/confusable/invisible/bidi/combining keys fail closed. Depth, node,
  scalar byte, cardinality and cycle budgets are enforced. Benign international
  unstructured display values remain valid.
- A dedicated per-adapter lock protects a global hook-active bit. Reads on the
  same adapter while any hook is active fail before reservation/quota/rate/hook,
  including other threads. The bit clears in `finally`; neither it nor any adapter
  lock is held during the external callback. Separate adapters remain independent.
- Historical recursion binds rejected V1–V4, executes all four frozen verifiers,
  verifies 39 manifests and 229 unique leaves, and rejects 12 disposable tamper
  fixtures. Budgets are checked before and after insertion/expansion; 4096 leaves
  is accepted and 4097 is rejected. Cycles, digest conflicts, traversal and
  symlinks fail closed.

## Verification

- Focused V5: 134 passed.
- Combined Phase 5: 560 passed.
- Stable mission/regressions: 162 passed plus 265 subtests.
- Ruff, compilation, whitespace and diff gates pass.

## Rollback and limitations

Rollback requires no migration: remove explicit test/development imports of V5.

- V5 is not live, authoritative, persisted or provider/OAuth/MCP connected.
- The catalog is process-local, metadata-only and mutation-free.
- The credential and confusable policies are finite security detectors, not
  general-purpose classification or transliteration.
- Full ledger remains bounded and fails closed without eviction.
- V1–V4 remain rejected; V5 cannot accept itself.
- External E6 and complete Phase 5 exit remain pending independent review.
