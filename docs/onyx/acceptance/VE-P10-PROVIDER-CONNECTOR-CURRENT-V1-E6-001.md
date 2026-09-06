# Phase 10 Provider Connector CURRENT V1 — source-integrity successor acceptance

- Evidence ID: `VE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001`
- Decision date: `2026-08-17`
- Decision: **ACCEPTED_CURRENT_SUCCESSOR — binds the current module bytes**
- Candidate root: `90139dd8b2856a6d778356b64a747d851e5320afe2241401b7150cf9499d9054`
- Current module SHA-256:
  `327f7d949ae764b6e3353e258500bc4a3ccc9f2bc87637f27b12bdbff71cb588` (15,989 bytes)
- Historical acceptance: `VE-P10-PROVIDER-CONNECTOR-V1-E6-001` (2026-07-25, retained)
- Correction:
  `docs/onyx/corrections/CORRECTION-P10-PROVIDER-CONNECTOR-POST-ACCEPTANCE-DRIFT.md`

`core/phase10_provider_connector_v1.py` was edited after its 2026-07-25 E6
acceptance; the accepted bytes are locally unrecoverable and the editing
session undocumented (full facts in the correction). The current bytes are the
ones every dated candidate tree from V34 (2026-08-10) through the released
V53 R15B (2026-08-11) carries — they passed the release-era global selections,
SBOM reconciliation and the V53 source freeze. This successor re-binds
current-state reproduction to those bytes, following the Capability Nexus
V32 → current-successor precedent. Nothing historical is rewritten: the
2026-07-25 acceptance, its manifest and its verifier remain byte-exact, and
that verifier's fail-closed rejection of the current tree is the correct
historical behaviour.

Successor verification (2026-08-17, fresh process): historical four-file
acceptance tuple byte-exact; current module SHA and byte size exact; current
eight-artifact root `90139dd8…` recomputed exactly (the other seven artifacts
still match their 2026-07-25 hashes); feature gate default-off; source
invariants present (route-pinned `fetch_account_status`, anti-spoof
`expected_handle`, `ProviderConnectorV1Denied`) and authority invariants
absent (`import requests`/`subprocess`/`def publish`/`def schedule`); the
slice's own adversarial test file reproduced **32 passed, 0 failed, 0
errors** in a fresh Python process.

**Honesty boundary.** These verification passes were executed autonomously in
the owner-authorized session that discovered the drift (@devops, R15B soak
night). No independent human review of this successor occurred; the
historical E6's three-review record is not inherited and is not claimed. The
successor asserts source-integrity re-binding only — it adds no capability,
no authority and no claim beyond what the historical acceptance already
scoped.
