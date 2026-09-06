# Phase 5.3 Capability Nexus V14 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V14 is self-contained and preserves rejected V1–V13 byte-for-byte. It replaces
their heuristic decision about whether descriptor metadata resembles prose or a
credential with a closed provenance/type contract.

Metadata keys remain a fixed allowlist. Every non-hash value is now an exact,
case-sensitive ASCII member of a per-key frozen enum:

- `data_source`: `constructor_allowlist`, `healthy`, `local_catalog`;
- `dispatch_path`: `legacy_unchanged`;
- `policy_source`: `trusted_host_mapping`;
- `fallback_class`: `explicit_browser_fallback`.

`declaration_sha256` is the sole typed non-enum field and accepts exactly 64
lowercase hexadecimal characters. No arbitrary prose, pseudoword, international
display string, confidential string or encoded representation is valid metadata.
Future values require a reviewed source change; runtime callers cannot extend the
mapping. Metadata validation performs no secret/prose likelihood inference and no
decoding pass.

Content scanners remain scoped to fields that are actually free text: operation
descriptions, canonical parameter schemas including defaults/examples/descriptions,
and legacy declarations. Those surfaces retain bounded iterative decoding before
secret allowlist decisions, explicit credential-pattern detection, confusable and
diacritic normalization, and canonical secret-name field rejection. Benign human
text is therefore allowed only in a content field, not relabeled as benign metadata.

V14 remains an isolated descriptor/catalog candidate. It exposes no authority,
dispatch or write operation; imports no provider/runtime surface; opens no port;
changes no flag; inherits from no previous candidate; and has no startup or live
wiring.

Verification: focused 1752; combined Phase 5 6998; stable regressions 102 plus 221
subtests; rejected V1–V13 history 66 manifests/310 leaves; frozen V13 transitive
closure and 21 tamper fixtures; Ruff, compilation, whitespace and diff pass.

V14 remains default-off, not live and externally unaccepted.
