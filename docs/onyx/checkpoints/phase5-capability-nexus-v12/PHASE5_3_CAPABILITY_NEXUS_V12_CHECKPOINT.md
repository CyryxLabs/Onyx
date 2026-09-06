# Phase 5.3 Capability Nexus V12 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V12 is self-contained and preserves rejected V1–V11 byte-for-byte. Its only delta
is protected-name detection before all opaque length, entropy and semantic gates.

Every decoded intermediate is confusable-canonicalized and split by Unicode
letter/number categories, with CamelCase and PascalCase boundaries preserved.
All other Unicode punctuation, symbols and separators are delimiters; no fixed
delimiter list exists. The classifier removes deterministic natural lexical units
and aggregates the entire remaining credential-shaped material, independent of
partition sizes. Identifier syntax is strict; whitespace prose requires contiguous
opaque lexical evidence. The natural classifier is intentionally finite: ASCII
technical words need known short vocabulary or syllabic structure plus a documented
technical affix/morpheme. This preserves broad technical prose and compounds while
unknown or numeric opaque material fails closed.

Verification: focused 1441; combined Phase 5 3529; stable regressions 102 plus 221
subtests; rejected V1–V11 history 60 manifests/292 leaves; frozen V11 transitive
closure and 19 tamper fixtures; Ruff, compilation, whitespace and diff pass.

V12 remains default-off, not live and externally unaccepted.
