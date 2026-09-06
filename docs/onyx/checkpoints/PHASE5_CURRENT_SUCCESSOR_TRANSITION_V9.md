# Phase 5 current-successor transition V9

V9 authenticates the current-byte closure for the Onyx 1.1.9 cross-platform
source candidate. The immutable Phase 5 Exit record and V1 through V8
successor-transition records remain unchanged.

## Boundary

- Immediate predecessor: `tests/fixtures/phase5_current_successor_transition_v8.json`
- Immediate predecessor SHA-256: `bea8ec2ce3f240e13750e08e1d7e006ef1d8a6bc0d023eba6ebb288f05734d5a`
- Immutable Phase 5 Exit root: `tests/fixtures/phase5_exit_retirement_v1.json`
- Immutable Phase 5 Exit SHA-256: `23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997`
- V9 record: `tests/fixtures/phase5_current_successor_transition_v9.json`
- V9 record SHA-256: `27991fabab95e3220ab34d86aec00a29d84ba49a82dc6e1ea075dc8662ca2200`
- V9 aggregate root: `bb16f4cf23ae75919e5d6fb05ddb30adcb814e537b73778c8744d80e6e1e9671`

## Current-byte changes since V8

| Path | V8 current SHA-256 | V9 current SHA-256 | Reason |
|---|---|---|---|
| `.github/workflows/release-packages.yml` | `a6d4e3b7fc044ecd4b13586bdfc9fd7c5656a8a392af8105a0164548fb39bca4` | `b952c52cce03fec6fb70a5f5dc6791cdd8be3572536395e6eb380d0d0b96d935` | Default release identity advanced from 1.1.8 to 1.1.9. |
| `packaging/onyx.spec` | `5b78ab22210ed611893616d5283e5f263eb6984b1fbcc7db1ac2145567995e8a` | `be1bc66af3fd982558509672eaaaf23d4f5e889734f789f3c9bdc26635d075a1` | Frozen-package identity advanced to 1.1.9; macOS 15+ support boundary is unchanged. |
| `scripts/build_release.py` | `60e798381e464b8ec0b4c12bc35837571936ce2bd2032813ddeaaaa333301911` | `010d89f312ba579ea109efbcdbc10643a58aaeb55a592a098b7ad4e3354bcb2f` | Native macOS/POSIX packaging and packaged-mode validation fixes are included in the successor source. |

The remaining 15 historical-binding targets and all seven named successors
retain their V8 current hashes. All 18 historical identities, states,
successors and original historical hashes remain unchanged. V9 points to the
exact V8 record rather than replacing it, updates only exact current hashes and
the V9 domain-separated aggregate root, grants no runtime authority and does
not rebind any historical evidence.

Active version surfaces outside this legacy Phase 5 closure are independently
checked by `tests/test_release_version_v119.py` and the release-preparation and
documentation gates.
