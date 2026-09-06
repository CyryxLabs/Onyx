# Phase 5.3 Capability Nexus V7 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V7 is a new self-contained candidate preserving rejected V1–V6 byte-for-byte.
It has no live/startup, dispatcher, UI, provider, flag or port wiring.

## Minimal corrective delta

The only behavioral change is the separated-prefix branch of the bounded compact
opaque detector. The leading prefix is NFKC/confusable-skeleton normalized before
any exemption. Protected secret vocabulary, including token, secret, password,
passwd, auth, authorization, bearer, cookie, API/private/access key and credential
variants, rejects before semantic handling. This holds across case, confusables and
encoded intermediates.

The previous blanket alphabetic-prefix exemption is replaced by a finite allowlist
for buildartifact, documentation, reference, release, version, catalog, dataset,
source and model. Exemption requires a separated, non-empty alphanumeric wordlike
structure. Unknown prefixes with opaque tails remain rejected. Total compact length
31 remains outside the detector; 32 is enforced.

## Verification

- Focused V7: 162 passed.
- Combined Phase 5: 867 passed.
- Stable mission/regressions: 162 passed plus 265 subtests.
- Recursive rejected V1–V6 history: 45 manifests and 247 leaves.
- Frozen V6 transitive closure, 14 disposable tamper fixtures, Ruff, compilation,
  whitespace and diff gates pass.

## Limitations

- V7 is not live, authoritative, persisted or provider/OAuth/MCP connected.
- Security vocabulary and semantic exemptions are intentionally finite and bounded.
- V1–V6 remain rejected; external E6 and Phase 5 exit remain pending.
