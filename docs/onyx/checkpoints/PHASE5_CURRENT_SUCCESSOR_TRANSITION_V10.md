# Phase 5 current-successor transition V10

V10 authenticates the reviewed working-byte closure for the Onyx 1.1.9 source
candidate after bounded release-policy, documentation and test-contract
corrections. It grants no build or runtime authority. V9 and every earlier
successor-transition record remain immutable predecessors.

## Boundary

- Immediate predecessor:
  `tests/fixtures/phase5_current_successor_transition_v9.json`
- Immediate predecessor SHA-256:
  `27991fabab95e3220ab34d86aec00a29d84ba49a82dc6e1ea075dc8662ca2200`
- Immutable Phase 5 Exit root:
  `tests/fixtures/phase5_exit_retirement_v1.json`
- Immutable Phase 5 Exit SHA-256:
  `23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997`
- V10 record:
  `tests/fixtures/phase5_current_successor_transition_v10.json`
- V10 record SHA-256:
  `1e8b86fc3f9f7090180d7f11f45fc2ac6dc326dc2c55782c043ee75328d40e49`
- V10 domain-separated aggregate root:
  `84de2478f97e9bfcfd2eab1e9d28f7c4b0fbe66f98ff21e000cbd53b9d3fbeb4`

## Current-byte changes since V9

| Path | V9 current SHA-256 | V10 current SHA-256 | Reason |
|---|---|---|---|
| `.github/workflows/release-packages.yml` | `b952c52cce03fec6fb70a5f5dc6791cdd8be3572536395e6eb380d0d0b96d935` | `fff4164ca9c7c58dcc68c48d98630f4080ffaeba1dab6601555a8acbc9438627` | Current formal-release, native-host and publisher-trust gates are bound without changing runtime authority. |
| `docs/onyx/CAPABILITY_MATRIX.md` | `41334289abdbb3ce5d23dd71548c958e91c67e5a870dde419d34db92f0052bc8` | `0a480d92391fd5e057f1e1cfdf6f60b7a2c954748eb846dd6aee77211aec1c4b` | Current-status precedence and the active PySide6/Qt LGPL boundary replace stale present-tense PyQt claims. |
| `scripts/build_release.py` | `010d89f312ba579ea109efbcdbc10643a58aaeb55a592a098b7ad4e3354bcb2f` | `a5e7a952987d931d53721dfd5fe3521554c896cebb769890837f9b8ab1cd1afd` | Formal versus diagnostic packaging, portable-current startup and secure-backend probes are bound fail closed. |
| `scripts/check_release_eligibility.py` | `121a3a69ee119c4397360fde265c9c24d310bc120706c593c42195e08fdfcb3d` | `5f1389a81ec07ce43e65ec6b6fb15e452142b609d9615a30cc47eec295fc1823` | Current release-eligibility policy is bound to the formal publication boundary. |
| `tests/test_package_hygiene_v1.py` | `7fd51fd731ab3cfa28cfc36005a3d0302e10b150ff795f73c07f57f770a04f16` | `ec04c64c8d10746bfda0b3fe23847259901c8e565421be5cc7a5987be63d1bd9` | The exact build-source assertion now covers the multiline portable-current secure-backend call contract. |

The other 14 historical-binding targets and six named successors retain their
V9 current hashes. All 18 historical identities, original historical hashes,
states and successor mappings remain byte-for-byte semantically identical to
V9 and the immutable Phase 5 Exit record.

## Local validation

- Successor, retirement, release, documentation and package-hygiene suites:
  **195 passed, 1 skipped**.
- Python 3.11 and 3.13 compilation of the changed verifier/test surfaces:
  **passed**.
- Ruff security/syntax selection on the changed Python surfaces: **passed**.
- Every V10 current-path digest and every predecessor record digest was
  recomputed after validation and matched its authenticated value.

These are local source gates. They do not substitute for independent review or
the required external zero-divergence seal.

## Disposition

`BUILD_NO_GO`. V10 is a local authenticated successor record only. A native
build remains prohibited until independent code review accepts the diagnostic
isolation boundary and an external content-addressed zero-divergence seal binds
the exact V10 source tree. Platform, signing, legal and owner-acoustic gates
remain independent and open.
