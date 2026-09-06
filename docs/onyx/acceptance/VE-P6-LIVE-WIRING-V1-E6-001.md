# Phase 6 Live Wiring V1 External E6 Acceptance

- Evidence ID: `VE-P6-LIVE-WIRING-V1-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED — exact default-off, unwired candidate only**
- Candidate: Phase 6 Live Wiring V1

## Frozen candidate boundary

This decision accepts only candidate manifest
`d98cdd73ae056e3afe5eac2976565d8b301fb1410a8b0498f04c6f7e8c2db6ee`
and its exact 5/5 artifact root
`272143e6419ca5ef242916569aee8e1c18e01317ba638c10dc336e99283c0dc8`.

| Artifact | SHA-256 |
|---|---|
| `core/phase6_live_wiring_v1.py` | `a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f` |
| `tests/test_phase6_live_wiring_v1.py` | `a252d4b6c1f2b0717572171bf4f2b518d105a9cf966c58d3b63c88b99730e510` |
| `docs/onyx/adrs/ADR-0019-phase6-live-wiring-v1.md` | `e75e2f76bbaafcb4a00841d6f487116df25a594c4ead49e175e90b720f3b70d8` |
| `docs/onyx/checkpoints/phase6-live-wiring-v1/PHASE6_LIVE_WIRING_V1_CHECKPOINT.md` | `ace81a864b00be6ec3e51c7a7f238fc3b268b2edefd41e521cea2e8b8e2efbda` |
| `scripts/verify_phase6_live_wiring_v1.py` | `69f1bbf465c76b6398c7cdc44f236b01b1cddb91b69103be8b4bd2d8a7985489` |

Any candidate, dependency, manifest or root drift invalidates this acceptance.
No candidate, accepted dependency, live surface or launcher byte was changed to
produce this external record.

## Independent decision

The exact candidate passes external review with
**P0=0, P1=0, P2=0, P3=0**.

The review independently reproduced:

- `P6_LIVE_WIRING_V1_OK`, with 5 artifacts and 18 frozen anchors;
- **17/17 focused tests**;
- **264/264 cumulative tests** across Phase 5 Integration V3, Agentic Core
  V1-V6, Live Integration V1-V2, Activation V7 and Wiring V1;
- Ruff lint, Ruff format and read-only Python compilation;
- the accepted Core V6 and Live Integration V2 evidence closures;
- exactly three patched lifecycle seams: `__init__`,
  `_start_phase5_session`, `_stop_phase5_session`;
- preservation of `_execute_tool`, `_run_live_loop` and `_send_realtime`;
- exact V7 installed/ready prerequisite, immutable four-field identity,
  Phase 5 bridge re-attestation and reuse of the host `MissionStore`;
- absolute state-root and observable link/reparse rejection;
- collision-resistant reconnect paths, V2-before-Phase-5 teardown,
  construction-failure cleanup, patch failpoints and exact post-V7 rollback;
- no live route, provider call or network call.

## Phase 5 entry evidence and V9 compatibility

The independently accepted Phase 5 Exit Candidate V2 record is entry evidence:

- acceptance ID: `VE-P5-EXIT-CANDIDATE-V2-E6-001`;
- record SHA-256:
  `052426cc0d62aad20af4ee8f1810d0729698fb0dd74e95cb76c1bbf0f50404d3`;
- candidate manifest:
  `b2cf8d781fc1f72a375be444c24ad74c4e59b910adab765a48c7c7b59ae15d2b`;
- evidence root:
  `2255b9a8a5315f99ab376f7f32d22ef8d39e6c2c4039a9ff77afa4ddf75e5fa6`.

This entry evidence is external to the frozen Wiring V1 manifest; that
candidate manifest is intentionally unchanged. The Phase 5 acceptance record
states `phase6_unlocked=false`, so this E6 decision does not infer an
operational Phase 6 unlock.

The current V9 chain remains compatible with the candidate's isolation:
Activation V9 binds exact V8, V8 binds exact V7, and neither the V8/V9 cores nor
their launchers import or enable `phase6_live_wiring_v1`. Wiring V1 is not
composed into V9 by this decision.

## Exact acceptance boundary

Accepted:

- the exact five-artifact Wiring V1 candidate;
- its identity-bound, session-scoped, fail-closed lifecycle implementation;
- its additive handoff for a later separately authorized wiring decision.

Not accepted or activated:

- importing or constructing Wiring V1 from a live surface;
- setting `ONYX_PHASE6_LIVE_WIRING_V1=true`;
- adding a UI, voice, command, tool, planner, provider or network route;
- restart, shortcut change, deployment, physical live handoff or Phase 6 exit;
- provider availability, installed external-agent operation or Onyx
  completeness.

The candidate remains **strict default-off, unwired and not live**. This record
does not activate Onyx and does not authorize automatic E6-to-runtime
transition.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_phase6_live_wiring_v1_acceptance.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_live_wiring_v1_acceptance.py
```

The verifier must emit `P6_LIVE_WIRING_V1_ACCEPTANCE_OK`.
