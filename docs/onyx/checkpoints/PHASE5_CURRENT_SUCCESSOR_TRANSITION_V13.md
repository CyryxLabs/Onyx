# Phase 5 current-successor transition V13

V13 authenticates the current Onyx 1.1.9 source after extending the original
Advanced Operations surface. The HUD adds bounded non-sensitive counts for
rules, devices, sites and active style preferences. The V21 tool can author a
rule only over an already-approved exact Phase 6 plan/mission and can manage
site metadata only inside controlled roots with receipt-gated stage changes.
No second runtime authority, polling worker, provider or external dispatcher
is introduced.

## Boundary

- Immediate predecessor:
  `tests/fixtures/phase5_current_successor_transition_v12.json`
- Immediate predecessor SHA-256:
  `e57480c4e52afb6e20aa336e4387b0dd4a5e77bf554eef4e5c7410683d7c16c7`
- V13 record:
  `tests/fixtures/phase5_current_successor_transition_v13.json`
- V13 record SHA-256:
  `3b7770fb458d2350028ec764418a5ad1071cb34282e0a9e342bfcc76a1d0da42`
- V13 domain-separated aggregate root:
  `8471086587dff899727438fb31652886ae846d720c8e85a7cc42d0ba271b0568`

## Current-byte change since V12

| Path | V12 current SHA-256 | V13 current SHA-256 | Reason |
|---|---|---|---|
| `ui.py` | `045585ae7ebed693e5a4134fd970a69676ef53c34d1809f19eb82fc2e2034958` | `cbeb75cd18f320ac92a5182a8834aea894ff3ff294d3e8ab75b9178b3a06ee34` | Adds bounded rule/device/site/preference summary rendering. |

All 18 historical identities and seven named-successor identities remain
unchanged. The new core modules and tests are additionally covered by the
first-party build-input seal; this legacy-retirement domain is intentionally
not misrepresented as a complete source manifest.

## Local validation

- Expanded clean-room operational selection: **98 passed**.
- V10/V11/V12/V13 successor selection: **20 passed** after documentation
  linkage.
- Ruff on the current verifier and successor tests: **passed**.

This is source evidence only. Installed Windows artifacts and their technical
SBOM remain V11-bound until a traceable V13 rebuild, installation and runtime
acceptance pass succeeds.
