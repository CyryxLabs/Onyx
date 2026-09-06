# Phase 5 current-successor transition V5

V5 advances only the authenticated current-byte closure required by the
Onyx 1.1.2 native-audio compatibility release. The immutable Phase 5 Exit
predecessor and the V1 through V4 successor-transition records remain
unchanged.

## Boundary

- Predecessor: `tests/fixtures/phase5_exit_retirement_v1.json`
- Predecessor SHA-256: `23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997`
- V5 record: `tests/fixtures/phase5_current_successor_transition_v5.json`
- V5 record SHA-256: `983dc58b6a8d4135d989bab56bef6b3677da496d4c9500c7a60cd8fa30f701a9`
- V5 aggregate root: `3ab42ee516c7fc9d92623fcaacaf6384ef40386fe1d32d86d8c41321ede8b600`

## Current-byte changes since V4

| Path | V4 current SHA-256 | V5 current SHA-256 | Reason |
|---|---|---|---|
| `.github/workflows/release-packages.yml` | `2d4bd75a45b663edee5fdb90acc3018f84c15420c6152c2039f51e57d687c565` | `64db23d86b2901ef9db406bff565483100b83b405a7a3d8caaa9eb97d1556397` | Release workflow default advanced to 1.1.2. |
| `packaging/onyx.spec` | `3b0bc4e776b43d294ff44d81ad3464e0877e76c651bf12020d7022d8563cc551` | `8abe39bd82031823dae3369d7f75fd5382768f71a03f5c000633a44b0fd847ad` | Frozen-package fallback version advanced to 1.1.2. |

All 18 historical binding identities, states, successors, and historical
hashes remain byte-for-byte identical to the predecessor record. All seven
named-successor predecessor hashes remain unchanged. This transition changes
no runtime authority; the Gemini Live audio compatibility change is isolated
in `core/live_model.py`, outside the retired Phase 5 authority closure.
