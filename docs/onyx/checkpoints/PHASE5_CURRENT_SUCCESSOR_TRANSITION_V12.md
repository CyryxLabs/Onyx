# Phase 5 current-successor transition V12

V12 authenticates the current Onyx 1.1.9 source after adding the original,
owner-invoked Advanced Operations HUD projection. It preserves the exact V20
callbacks and V21 tool route, performs no polling or external dispatch, and
grants no new runtime authority. V11 and every earlier transition remain
immutable predecessors.

## Boundary

- Immediate predecessor:
  `tests/fixtures/phase5_current_successor_transition_v11.json`
- Immediate predecessor SHA-256:
  `a6153df617e9af19f82a21ee00802a2a48c22af736a3b22e437b41705608cd89`
- V12 record:
  `tests/fixtures/phase5_current_successor_transition_v12.json`
- V12 record SHA-256:
  `e57480c4e52afb6e20aa336e4387b0dd4a5e77bf554eef4e5c7410683d7c16c7`
- V12 domain-separated aggregate root:
  `dd6ac349a22e6b5fd50a089cd7fe2009dedfe2f79007af64d491d0520c18bc96`

## Current-byte change since V11

| Path | V11 current SHA-256 | V12 current SHA-256 | Reason |
|---|---|---|---|
| `ui.py` | `1b7ae34037fda58fe2a9dab07f57799d65397694842dd68d9dfa36e397d0ee00` | `045585ae7ebed693e5a4134fd970a69676ef53c34d1809f19eb82fc2e2034958` | Adds a bounded, allowlisted Advanced Operations renderer, explicit OnyxUI callback bridge and owner-invoked HUD action. |

The QML V9 byte change is separately content-addressed by the current HUD
acceptance manifest. All 18 historical identities and seven named-successor
identities remain unchanged; the other current hashes retain their V11 values.

## Local validation

- Advanced Operations UI, V20 callback and current HUD integrity selection:
  **25 passed**.
- V10/V11/V12 successor selection: **16 passed** after documentation linkage.
- Ruff on the verifier and V10/V11/V12 tests: **passed**.

These results authenticate a source candidate only. The installed Windows
artifacts and their SBOM remain bound to V11 until a traceable V12 rebuild,
installation and acceptance pass succeeds.
