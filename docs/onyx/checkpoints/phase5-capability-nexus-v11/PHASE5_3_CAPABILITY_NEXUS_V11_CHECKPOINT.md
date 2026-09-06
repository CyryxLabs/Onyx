# Phase 5.3 Capability Nexus V11 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V11 is self-contained and preserves rejected V1–V10 byte-for-byte. Its only delta
is protected-name detection before all opaque length, entropy and semantic gates.

Every decoded intermediate is confusable-canonicalized and split at CamelCase,
PascalCase and arbitrary repeated namespace separators (`_`, `-`, `.`, `/` and
whitespace). All contiguous spans and all offsets inside case-free concatenations
are compared with canonical secret and credential names before every other opaque
gate. The classifier rejects either one opaque component of at least 16 characters
or a bounded aggregate of short credential-shaped chunks totaling at least 16.
Natural-word morphology terminates aggregation, so `authorization interoperability`,
`token characterization`, `auth internationalization` and related prose remain
valid. `tokenization`/`authentication` are safe only as whole semantic words and
cannot exempt opaque material attached before or after them.

Verification: focused 614; combined Phase 5 2088; stable regressions 102 plus 221
subtests; rejected V1–V10 history 57 manifests/283 leaves; frozen V10 transitive
closure and 18 tamper fixtures; Ruff, compilation, whitespace and diff pass.

V11 remains default-off, not live and externally unaccepted.
