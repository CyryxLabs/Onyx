# Phase 5 current-successor transition V4

V4 advances only the authenticated current-byte closure required by the
reproducible 1.1.1 release preparation. The immutable Phase 5 Exit predecessor
and the V1, V2, and V3 successor-transition records remain unchanged.

## Boundary

- Predecessor: `tests/fixtures/phase5_exit_retirement_v1.json`
- Predecessor SHA-256: `23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997`
- V4 record: `tests/fixtures/phase5_current_successor_transition_v4.json`
- V4 record SHA-256: `d31c7ed4634a574eb130b5cd56cd955dd46ed0a8dadc5003be6a943fcf220936`
- V4 aggregate root: `bdf2bef3873d12f86ad7cf7fdb11376f94af9943515da1ede9313b7325132daa`

## Current-byte changes since V3

| Path | V3 current SHA-256 | V4 current SHA-256 | Reason |
|---|---|---|---|
| `.github/workflows/release-packages.yml` | `83bca1f57d1e40efe6a053abbec8f9087420aab47b62161e22bdb68526655826` | `2d4bd75a45b663edee5fdb90acc3018f84c15420c6152c2039f51e57d687c565` | Release workflow default advanced to 1.1.1. |
| `packaging/onyx.spec` | `09a3f314698ef87b0186a1f293c603830faabfa1202bd13a2366f9f9444586cb` | `3b0bc4e776b43d294ff44d81ad3464e0877e76c651bf12020d7022d8563cc551` | Frozen-package fallback version advanced to 1.1.1. |
| `scripts/build_release.py` | `135d3b1b05f763f19df8917b8e19dd9f9349572cf9c5946e4c9de34a77b2149f` | `383c70fcbc09e7151ff7fdffdd52f6869ec2f298e934e01befc5343fe227d3cf` | Build-input discovery now seals staged data and every first-party source origin consumed to produce it. |

All 18 historical binding identities, states, successors, and historical
hashes remain byte-for-byte identical to the predecessor record. All seven
named-successor predecessor hashes remain unchanged. This transition changes
no runtime authority.
