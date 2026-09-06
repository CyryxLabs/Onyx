# Phase 5 current-successor transition V7

V7 advances only the authenticated current-byte closure required for the
Onyx 1.1.3 owner-address correction release. The immutable Phase 5 Exit
predecessor and the V1 through V6 successor-transition records remain
unchanged.

## Boundary

- Predecessor: `tests/fixtures/phase5_exit_retirement_v1.json`
- Predecessor SHA-256: `23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997`
- V7 record: `tests/fixtures/phase5_current_successor_transition_v7.json`
- V7 record SHA-256: `d5711313bd6cf136013fba5e892a12df83affdb5d0d17392f343520b10acbd98`
- V7 aggregate root: `2007c8b708487fb8a10e0d11975f8bd8883f79e9536d79be3f84c71917a8133a`

## Current-byte changes since V6

| Path | V6 current SHA-256 | V7 current SHA-256 | Reason |
|---|---|---|---|
| `.github/workflows/release-packages.yml` | `64db23d86b2901ef9db406bff565483100b83b405a7a3d8caaa9eb97d1556397` | `3ae9e9f7911b883e80189c2004b8ef113c77d72d2fdb464ffa697de9112c5013` | Release workflow default advanced to 1.1.3. |
| `packaging/onyx.spec` | `8abe39bd82031823dae3369d7f75fd5382768f71a03f5c000633a44b0fd847ad` | `47bd136426a650ca58c0a266efc26063905076d8b69e071d0f48e0eea9fd1bc6` | Frozen-package fallback version advanced to 1.1.3. |

All 18 historical binding identities, states, successors, and historical
hashes remain byte-for-byte identical to the predecessor record. All seven
named-successor predecessor and current hashes remain unchanged. The owner
tool route and explicit `Sir` address preference are implemented in V15 and
the deterministic owner-name command router, outside the retired Phase 5
authority closure.
