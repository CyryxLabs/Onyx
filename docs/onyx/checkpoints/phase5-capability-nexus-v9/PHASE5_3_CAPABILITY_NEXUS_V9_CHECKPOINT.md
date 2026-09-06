# Phase 5.3 Capability Nexus V9 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V9 is self-contained and preserves rejected V1–V8 byte-for-byte. Its only delta
is protected-name detection before all opaque length, entropy and semantic gates.

Every decoded intermediate is confusable-canonicalized, split on repeated `_`/`-`,
and all contiguous spans at every position are compared with canonical secret and
credential names. Controlled concatenated prefix/suffix boundaries reject when the
adjacent remainder is token-like, while wordlike `tokenization` and `authentication`
remain valid. Namespace-safe prefixes cannot hide later protected spans and values
under 32 characters are not exempt.

Verification: focused 223; combined Phase 5 1271; stable regressions 162 plus 265
subtests; rejected V1–V8 history 51 manifests/265 leaves; frozen V8 transitive
closure and 16 tamper fixtures; Ruff, compilation, whitespace and diff pass.

V9 remains default-off, not live and externally unaccepted.
