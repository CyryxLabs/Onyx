# Phase 5.3 Capability Nexus V3 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V3 is a new self-contained candidate. It supersedes rejected V1 and V2 without
importing or modifying either. No startup, dispatcher, UI, provider, feature
flag, grant, Approval Inbox or port path imports V3.

## Minimal corrective delta

V3 preserves V2 profile binding, exact concrete frozen gate, lock order and
bounded no-replay reservation ledger. Its only behavioral correction is metadata
value normalization closure.

Every safe metadata value is scanned in its original form and after every
canonical intermediate representation. A bounded breadth-first closure applies
NFKC normalization, strict canonical percent decoding and strict canonical
standard/URL-safe Base64 decoding, including padded and unpadded forms. It stops
only at a fixed point. Limits cover depth, representation count, individual and
aggregate byte size; cycles, malformed/ambiguous encodings and residual character
escapes fail closed.

Secret assignment, PEM, JWT and secret-key/value canaries are checked at every
step. Controls, format characters and invalid Unicode decoding fail. Canonical
decoding is attempted only for tight valid alphabets/round trips and valid UTF-8,
so ordinary values such as `constructor_allowlist`, `legacy_unchanged`,
`trusted_host_mapping`, health labels and SHA-256 metadata remain unchanged.

## Verification

- Focused V3 suite: 69 passed.
- Combined Phase 5 suite: 318 passed.
- Stable regressions: 102 passed plus 221 subtests.
- Double/triple percent and Base64, mixed percent/Base64, URL-safe padded/
  unpadded, case/NFKC/control, malformed/ambiguous/residual, depth, expansion and
  cycle probes pass alongside benign fixtures.
- Exact V1/V2 bytes are bound as rejected history. Disposable V2 core tampering
  must fail its expected hash.
- Ruff, compilation, whitespace, scoped diff and live-source isolation pass.

## Rollback and limitations

Rollback requires no migration: remove explicit test/development imports of V3.
The live dispatcher remains unchanged.

- V3 is not live, authoritative, persisted or connected to provider/OAuth/MCP.
- The catalog remains process-local, metadata-only and mutation-free.
- Full ledger fails closed without eviction, preventing correlation replay.
- V1 and V2 remain rejected; this candidate cannot accept itself.
- External E6 and complete Phase 5 exit remain pending independent review.
