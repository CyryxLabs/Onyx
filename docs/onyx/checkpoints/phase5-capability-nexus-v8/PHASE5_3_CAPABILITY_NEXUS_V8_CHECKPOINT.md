# Phase 5.3 Capability Nexus V8 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V8 is self-contained and preserves rejected V1–V7 byte-for-byte. No live/runtime
wiring changed.

## Minimal correction

The compact opaque detector no longer maintains a divergent manual secret-prefix
list. For every plausible separated leading span before an opaque tail it uses the
same NFKC/confusable canonical name function as structured secret fields, then
derives rejection from `_SECRET_NAMES` plus credential-only aliases. This covers
access/refresh token forms automatically and applies before the unchanged finite
semantic allowlist. Case, confusable, percent/Base64 and 31/32 boundary probes pass.

## Verification

- Focused V8: 181 passed.
- Combined Phase 5: 1048 passed.
- Stable regressions: 162 passed plus 265 subtests.
- Rejected V1–V7 history: 48 manifests, 256 leaves, frozen V7 transitive closure
  and 15 disposable tamper fixtures.
- Ruff, compilation, whitespace and diff gates pass.

V8 remains default-off, process-local, mutation-free and externally unaccepted.
