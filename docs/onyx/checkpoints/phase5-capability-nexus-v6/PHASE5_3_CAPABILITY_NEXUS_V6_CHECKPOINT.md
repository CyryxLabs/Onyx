# Phase 5.3 Capability Nexus V6 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V6 is a new self-contained candidate preserving rejected V1–V5 byte-for-byte.
It has no live/startup, dispatcher, UI, provider, flag or port wiring.

## Minimal corrective delta

- Compact 32–512 character opaque values with upper/lower/digit classes and
  bounded entropy are rejected even without separators. Exact semantic identifiers
  with wordlike separated prefixes remain valid. A 64-hex digest is accepted only
  in the explicit `declaration_sha256` field and rejected as ordinary metadata.
- JSON/schema keys alone require canonical ASCII identifiers. Scalar values still
  receive full secret, raw credential, decoding, control, bidi and combining checks
  while benign international mixed-script human descriptions with colons remain
  valid. Confusable assignments and JSON fragments fail closed.
- Each adapter atomically claims hook admission at the first instruction of
  `read_page`, before validation, clocks, digests, reservations or counters. The
  claim is cleared by an outer `finally` on every path. No lock is held during
  validation, reservation or callback. Concurrent same-adapter reads deny without
  ledger/quota drift; separate adapters remain independent.
- Every component from project root to historical manifest/leaf is inspected with
  `lstat` and Windows reparse attributes before resolution. Ancestor and final
  symlinks/reparse points fail even when targeting inside the project.

## Verification

- Focused V6: 145 passed.
- Combined Phase 5: 705 passed.
- Stable mission/regressions: 162 passed plus 265 subtests.
- Recursive rejected V1–V5 history: 42 manifests, 238 leaves, five frozen
  verifiers and 13 disposable tamper fixtures.
- Ruff, compilation, whitespace and diff gates pass.

## Limitations

- V6 is not live, authoritative, persisted or provider/OAuth/MCP connected.
- The catalog remains process-local, metadata-only and mutation-free.
- Security detectors are finite and bounded rather than general classifiers.
- V1–V5 remain rejected; external E6 and Phase 5 exit remain pending.
