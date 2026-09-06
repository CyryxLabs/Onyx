# Phase 6 Live Wiring V1 checkpoint

Status: **isolated additive candidate, strict default-off, not live**

Date: 2026-07-23  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## Real host path inspected

The accepted V7 launcher validates an exact pre-import activation truth table,
imports `main`, calls `activate_main(main)`, then calls unchanged `main.main()`.
V7 installs/starts its accepted 23 transactional seams before the host creates
an `OnyxLive` instance.

The unchanged host:

- creates one exact `MissionStore` during `OnyxLive.__init__`;
- creates a fresh exact Phase 5 V3 bridge for each connection in
  `_start_phase5_session`;
- revokes authorization and terminates that bridge in
  `_stop_phase5_session`.

This candidate wraps that lifecycle only after exact V7 is installed and
`READY`.

## Implemented boundary

- exact feature flag `ONYX_PHASE6_LIVE_WIRING_V1=true`, default off;
- off-before-validation behavior with no patch, file, executor, thread or child
  process;
- sealed factory accepting only gate, exact V7 activation and absolute state
  root;
- immutable four-part identity derived solely from V7 and re-attested against
  every runtime Phase 5 bridge;
- exact reuse of the host MissionStore;
- internal exact Core V6 and Live Integration V2 factory construction;
- transactional wrapping of only `__init__`, `_start_phase5_session` and
  `_stop_phase5_session`;
- exact rollback to the post-V7 functions after failure before/after every
  patch write;
- V2 teardown before Phase 5 termination;
- fail-closed cleanup when runtime V2 construction fails;
- collision-resistant session-scoped state and receipt paths;
- best-effort rejection of existing symlink/reparse state-root ancestry;
- preservation of `_execute_tool`, `_run_live_loop` and `_send_realtime`.

Not implemented or claimed:

- import or configuration in any live surface;
- an update to V7 launch flags, active/rollback commands or shortcuts;
- a UI, voice, command, tool or planner route to the V2 facade;
- Gemini Live changes or a current external-provider availability test;
- installed external-agent execution;
- Phase 6 exit or Onyx completion.

## Frozen dependencies

- Live Integration V2 manifest:
  `d02b265e5d67c98fb9dd2e868440ead39360187bdd95592fcf89a44f4448833a`;
  root:
  `0b58365a0c43ea9b7133de1c0a51e77aa6bd855852849dab2bd9c433f733a334`.
- Live Integration V2 E6 record:
  `cfe947b7c81bbf7ad0fb6e75469c473c0d69c8b1b813d89c08ca1c729dd9f687`.
- Activation V7 manifest:
  `312d6654f3423f16f4b36f435638920836994bd56c3e9a8766a086e2c6d647da`;
  independent accepted root:
  `c6c52ca0d9a7725b543989c7586fc9fe9ab535282223b7fa0e1b0d1b8f5807cc`.
- Activation V7 E6 record:
  `8438769b1b597b0d66174db0c73d50a9577702c5957ba6ff24b55315d11aedb5`.
- Agentic Core V6 manifest:
  `cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15`.
- Phase 5 Integration V3 manifest:
  `9ee4b34fc87a6be5e123c83c7dd244804498891eb175b5201cf074475ff0d167`.

## Verification before manifest freeze

Focused wiring tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-live-wiring-v1-dev2 tests\test_phase6_live_wiring_v1.py -k "not manifest_recomputes"
```

Result: **16 passed, 1 manifest test deselected, in 6.10s**.

Activation V7 plus Wiring V1:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-live-wiring-v1-v7-combined tests\test_onyx_live_activation_v7.py tests\test_phase6_live_wiring_v1.py -k "not manifest_recomputes"
```

Result: **22 passed, 1 manifest test deselected, in 18.78s**.

Cumulative Phase 5 V3 + Core V1-V6 + Integration V1-V2 + Activation V7 +
Wiring V1:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-live-wiring-v1-cumulative tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py tests\test_phase6_agentic_core_v6.py tests\test_phase6_agentic_core_v6_acceptance.py tests\test_phase6_live_integration_v1.py tests\test_phase6_live_integration_v2.py tests\test_onyx_live_activation_v7.py tests\test_phase6_live_wiring_v1.py --deselect tests/test_phase6_live_wiring_v1.py::test_manifest_recomputes_artifact_root
```

Result: **263 passed, 1 manifest test deselected, in 69.70s**.

Ruff lint/format and Python byte compilation passed before freeze.

## Concurrent Phase 5 freeze dependency

After the draft manifest was created, one cumulative rerun observed a
concurrent, not-yet-frozen Phase 5 Exit edit to
`docs/onyx/CAPABILITY_MATRIX.md`. The three accepted historical Phase 5 V3
projection manifests still bound the preceding matrix hash, so that transient
run ended with **258 passed and 6 dependency-drift failures**. Wiring-focused
tests remained **17/17**, and the Activation V7 plus Wiring run remained
**23/23**.

This candidate does not edit or rebind the matrix or any historical Phase 5
manifest. After the separate Phase 5 Exit candidate isolated its deltas and
restored the accepted historical hashes, the complete cumulative gate passed
**264/264**. The transient dependency result is retained for traceability but
is not used as final Wiring evidence.

## Verification after manifest freeze

- Focused Wiring V1: **17 passed**.
- Activation V7 plus Wiring V1: **23 passed**.
- Full Phase 5 V3 + Core V1–V6 + Integration V1–V2 + Activation V7 + Wiring
  V1 cumulative gate: **264 passed in 74.26s**.
- Wiring verifier: `P6_LIVE_WIRING_V1_OK`.
- Phase 5 Integration V3 acceptance:
  `P5_INTEGRATION_V3_ACCEPTANCE_OK`.
- Agentic Core V6 acceptance: `P6_AGENTIC_CORE_V6_ACCEPTANCE_OK`.
- Live Integration V2 acceptance:
  `P6_LIVE_INTEGRATION_V2_ACCEPTANCE_OK`.
- Activation V7 acceptance: `ONYX_LIVE_ACTIVATION_V7_ACCEPTANCE_OK`.
- Ruff lint/format and Python byte compilation: **passed**.

## Adversarial coverage

- strict gate parsing and off-before-dependency/path work;
- no off-state file, thread, child or executor construction;
- factory signature and caller identity/dependency injection absence;
- exact installed/ready V7 prerequisite;
- immutable identity derivation and cross-identity drift denial;
- injected failure before the first patch and after each of three patches;
- exact post-V7 rollback and protected-seam preservation;
- actual host MissionStore reuse and exact V2/Core construction;
- no network call during real-host session attachment;
- two reconnects, distinct session paths and complete teardown;
- V2-close-before-Phase5-stop ordering;
- session-construction failure revoking Phase 5 without attachment;
- factory substitution and post-construction identity drift denial;
- symlink/reparse state-root rejection where the host permits test creation;
- frozen V7, V2, Core and live-host hashes;
- reproducible manifest root.

## Resource, rollback and limitations

Default-off impact is zero. Construction with the exact gate creates only an
in-memory controller and performs no patch. Explicit installation changes three
class callables and creates no file or executor until the next Phase 5 session.
At session start, exact Core V6/V2 construction creates bounded process-executor
objects and session-scoped SQLite sidecars; no provider call occurs.

Rollback closes tracked V2 sessions and restores the exact post-V7 lifecycle
functions. V7 rollback remains a separate later action.

The state-root checks reject currently observable links/reparse points but do
not claim strong protection against an external cross-process TOCTOU race.
The candidate exposes no user-facing or command route to V2. It remains
default-off, unwired and is not Phase 6 exit.
