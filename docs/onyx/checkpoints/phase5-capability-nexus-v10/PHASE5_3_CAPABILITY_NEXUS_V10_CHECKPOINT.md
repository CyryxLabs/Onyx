# Phase 5.3 Capability Nexus V10 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V10 is self-contained and preserves rejected V1–V9 byte-for-byte. Its only delta
is protected-name detection before all opaque length, entropy and semantic gates.

Every decoded intermediate is confusable-canonicalized and split at CamelCase,
PascalCase and arbitrary repeated namespace separators (`_`, `-`, `.`, `/` and
whitespace). All contiguous spans and all offsets inside case-free concatenations
are compared with canonical secret and credential names before every other opaque
gate. A contiguous token-like component is required, preserving benign prose and
wordlike `tokenization`/`authentication` while rejecting protected names hidden by
arbitrary prefixes, suffixes, namespaces, Base64 layers and confusables.

Verification: focused 346; combined Phase 5 1474; stable regressions 102 plus 221
subtests; rejected V1–V9 history 54 manifests/274 leaves; frozen V9 transitive
closure and 17 tamper fixtures; Ruff, compilation, whitespace and diff pass.

V10 remains default-off, not live and externally unaccepted.
