# Phase 5 current-successor transition V11

V11 authenticates the current Onyx 1.1.9 source bytes after the V21 bootstrap,
single-thread PortAudio ownership and final packaging corrections. It grants no
new runtime authority. V10 and every earlier successor-transition record remain
immutable predecessors.

## Boundary

- Immediate predecessor:
  `tests/fixtures/phase5_current_successor_transition_v10.json`
- Immediate predecessor SHA-256:
  `1e8b86fc3f9f7090180d7f11f45fc2ac6dc326dc2c55782c043ee75328d40e49`
- V11 record:
  `tests/fixtures/phase5_current_successor_transition_v11.json`
- V11 record SHA-256:
  `a6153df617e9af19f82a21ee00802a2a48c22af736a3b22e437b41705608cd89`
- V11 domain-separated aggregate root:
  `4941c6e585837e3c7c8d2b679749acafd7807c2b5cf79faeb6a19addcb4a200f`

## Current-byte changes since V10

| Path | V10 current SHA-256 | V11 current SHA-256 | Reason |
|---|---|---|---|
| `main.py` | `efe6b376062e696dfcb3c5e1f747105f70193461c2bde313ba99dc3910ffd382` | `36b4dee2c5a22350a2c1387e8b13370973a45f2d22e6e30367fab6c37dcf37ff` | PortAudio stream start/write/stop/close now share one thread owner, preventing close/write heap races. |
| `packaging/onyx.spec` | `be1bc66af3fd982558509672eaaaf23d4f5e889734f789f3c9bdc26635d075a1` | `b81aef4fab8879c923f1d4898fd7de8531235739e1bfe36b655f28dd2be6d187` | Frozen V21 entrypoint and current packaging inputs are bound. |
| `scripts/build_release.py` | `a5e7a952987d931d53721dfd5fe3521554c896cebb769890837f9b8ab1cd1afd` | `535b4d4ce3ee47b78916a40d6c8c3ab14635ff2fe18de37974ae11f64b98437d` | Current V21 diagnostics and package gates are bound. |
| `scripts/package_hygiene.py` | `388ae616a5143c06685ab9b8d0f48ade231b8cbbdff773bb4900e450e48aa2ab` | `ccbcefd6348969976c5aa1456d845bfeb968bc9493a332a20b65c4fa4fd7ad52` | Current package hygiene rules are authenticated as the named successor. |
| `tests/test_package_hygiene_v1.py` | `ec04c64c8d10746bfda0b3fe23847259901c8e565421be5cc7a5987be63d1bd9` | `0e2cd8a69ebd9e5062e86460200ba71c19f93f479991eccf0a3733810b03d643` | Current hygiene regression contract is authenticated. |

All 18 historical identities, original hashes, states and successor mappings
remain unchanged. The other 15 historical targets and five named successors
retain their V10 current hashes.

## Local validation

- V10/V11 succession, tamper, integration-transition and acceptance selection:
  **32 passed**.
- MissionStore, mission tools, Phase 5 integration and Phase 6 V1-V6 selection:
  **248 passed** after one Windows multiprocess synchronization rerun; the two
  initially variable cases also passed **2/2** in isolation.
- Ruff on the V11 verifier and tests: **passed**.

These results authenticate the local source relationship. They do not replace
artifact build/install hashes, signing, external source seal, human acoustic
acceptance, native macOS/Linux evidence or independent final review.

