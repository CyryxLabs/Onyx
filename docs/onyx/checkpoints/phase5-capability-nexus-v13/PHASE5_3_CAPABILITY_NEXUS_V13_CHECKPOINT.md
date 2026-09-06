# Phase 5.3 Capability Nexus V13 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V13 is self-contained and preserves rejected V1–V12 byte-for-byte. Its only delta
is protected-name detection before all opaque length, entropy and semantic gates.

Every decoded intermediate is normalized with NFKD, case-folded,
confusable-canonicalized and stripped of Unicode combining marks before analysis.
The classifier splits on every Unicode punctuation, symbol and separator category,
and retains CamelCase and PascalCase boundaries; no fixed delimiter list exists.
This makes composed and decomposed diacritic forms, encoded forms and confusable
variants converge before the protected-name canary runs.

V13 uses an embedded, deterministic English-likelihood model. It combines bigram
coverage (45%), trigram coverage (40%) and a vowel/shape term (15%) against an
explicit 0.50 natural-word threshold, with hard rejection for low-diversity,
repeated, keyboard-walk and alphabetic-walk sequences. A compact frozen technical
lexicon supplements short prose terms that n-grams cannot classify reliably. The
model is intentionally finite and local: unknown words are not automatically
trusted merely because they have a natural-looking suffix.

The grammar distinguishes identifiers from prose. Camel/Pascal or attached
punctuation creates identifier context; whitespace-delimited material creates prose
context. Natural lexical islands are removed only after classification, while all
remaining credential-shaped material on both sides of a protected span is
aggregated. Identifier residuals of at least 16 characters reject. Prose residuals
of at least 16 characters reject when supported by two opaque parts, one 16+
opaque part or numeric evidence. Natural-looking islands cannot erase an opaque
aggregate, and a natural suffix cannot bless an opaque prefix.

Verification: focused 1717; combined Phase 5 5246; stable regressions 102 plus 221
subtests; rejected V1–V12 history 63 manifests/301 leaves; frozen V12 transitive
closure and 20 tamper fixtures; Ruff, compilation, whitespace and diff pass.

V13 remains default-off, not live and externally unaccepted.
