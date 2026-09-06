# Phase 5 current-successor transition V8

V8 advances only the authenticated current-byte closure required for the Onyx
1.1.8 release candidate. The immutable Phase 5 Exit predecessor and V1 through
V7 successor-transition records remain unchanged.

## Boundary

- Predecessor: `tests/fixtures/phase5_exit_retirement_v1.json`
- Predecessor SHA-256: `23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997`
- V8 record: `tests/fixtures/phase5_current_successor_transition_v8.json`
- V8 record SHA-256: `bea8ec2ce3f240e13750e08e1d7e006ef1d8a6bc0d023eba6ebb288f05734d5a`
- V8 aggregate root: `61f03516a28fd16591f52f7c8e951a6e071f2e8894721b6cbd85420b227c75a0`

## Current-byte changes since V7

| Path | V7 current SHA-256 | V8 current SHA-256 | Reason |
|---|---|---|---|
| `.github/workflows/release-packages.yml` | `9e9c5571cc5356ed53f1c481bb9c581953d7ff8c255df4ce8a1313add851f8bf` | `a6d4e3b7fc044ecd4b13586bdfc9fd7c5656a8a392af8105a0164548fb39bca4` | Release workflow advanced to the pinned, cross-platform 1.1.8 release candidate. |
| `docs/onyx/CAPABILITY_MATRIX.md` | `ee050523b8e1d76d270a1d230922e8ef2282242b7e134b5daface570c5889da7` | `41334289abdbb3ce5d23dd71548c958e91c67e5a870dde419d34db92f0052bc8` | Current capability truth and release caveats were refreshed. |
| `docs/onyx/VERIFICATION_EVIDENCE.md` | `e689b5739604a596be18333c032b6a03541605a52156a187151ff04e3ef351f2` | `b28691b272fac930d31febac94f771f31087a38468ac103abdc772d2efeaa436` | Current evidence register and supersession notices were refreshed. |
| `main.py` | `e23432dfadc97246d6719589d932bd4c5de5b0d6ef4d13cac10486e83b332e9c` | `efe6b376062e696dfcb3c5e1f747105f70193461c2bde313ba99dc3910ffd382` | Live voice continuity and owner-facing runtime corrections were integrated. |
| `packaging/onyx.spec` | `86370131806774f07cbca01aa95e0e770c8336a1e5f6bf5fbfa1fe9fdf3df1cc` | `5b78ab22210ed611893616d5283e5f263eb6984b1fbcc7db1ac2145567995e8a` | Frozen-package metadata advanced to 1.1.8. |
| `scripts/build_release.py` | `fc2030e0ed052026f702e1d0ff21bd5d08e611dd151a662e5e4c436e2fbe1cb6` | `60e798381e464b8ec0b4c12bc35837571936ce2bd2032813ddeaaaa333301911` | Native release packaging and portability validation were extended. |
| `scripts/package_hygiene.py` | `239009be2c8c697aada1fbe60d33740fd386481895b5215f4750001f7b1c5e3c` | `388ae616a5143c06685ab9b8d0f48ade231b8cbbdff773bb4900e450e48aa2ab` | Package hygiene follows the current 1.1.8 release boundary. |
| `tests/test_package_hygiene_v1.py` | `d8c233c4ff3dd6977570a10ecb07e8f111ac7710416beb9ffc11b830303f1bef` | `7fd51fd731ab3cfa28cfc36005a3d0302e10b150ff795f73c07f57f770a04f16` | Hygiene assertions cover the current package boundary. |

All 18 historical binding identities, states, successors, and historical
hashes remain byte-for-byte identical to the predecessor record. Named
successor predecessor hashes remain unchanged. V8 updates only exact current
hashes and their domain-separated aggregate root; it grants no new runtime
authority and does not rebind historical evidence.
