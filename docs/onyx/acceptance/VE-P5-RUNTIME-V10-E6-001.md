# Phase 5 Runtime Core V10 External E6 Acceptance

- Evidence ID: `VE-P5-RUNTIME-V10-E6-001`
- Decision date: 2026-07-22
- Decision: **ACCEPTED — Runtime Core V10 only, isolated/default-off implementation handoff**
- Candidate: Phase 5 Runtime Core, V10

## Frozen candidate anchor

This external record anchors the exact V10 candidate without changing any
candidate byte:

- Core: `core/phase5_runtime_v10.py`
- Core SHA-256: `f80fd636e145e669cc1ea76cfc024fcc5d385451cc1ef8624f7c9d8e0ac3f439`
- Tests: `tests/test_phase5_runtime_v10.py`
- Tests SHA-256: `b2a6d9524d2d5d1b85af3325462f7bd28793180cee0ea4295d6600750615cfff`
- Candidate manifest: `docs/onyx/checkpoints/phase5-runtime-v10/manifest.json`
- Candidate-manifest SHA-256: `1cc83a994194b3ecb87bf43a91db4219cf480d48da7821e7057eb4e068ca01cb`
- Checkpoint: `docs/onyx/checkpoints/phase5-runtime-v10/PHASE5_RUNTIME_V10_CHECKPOINT.md`
- Checkpoint SHA-256: `7f31d7ddda750f35c7b56e0af2e3569e068229f8a236e783936c28c2fff55f0d`

The candidate manifest is the frozen candidate root for this acceptance. It
binds the exact V10 core and test plus the V1-V9 historical implementation and
test anchors. Any change to an anchored digest invalidates this acceptance and
requires a new candidate, three new independent gates and a new record.

## Independent reviewer attestations

These attestations are external to the V10 candidate bundle:

| Review | Result | Reproduction evidence | Severity findings |
|---|---|---|---|
| Functional | PASS | 103 focused tests; 1,111 cumulative tests plus 221 subtests; exact-key construction, atomic termination acknowledgement, deterministic zero-pending completion, sticky crypto degradation and default-off behavior exercised | P0=0, P1=0, P2=0, P3=0 |
| Integrity | PASS | Exact core, tests, manifest and checkpoint digests independently rehashed; manifest closure and default-off/live-wiring boundary checked | P0=0, P1=0, P2=0; the prior P3 external-root/process limitation is resolved for these exact bytes by this external acceptance and its independently runnable verifier |
| Quality | PASS | Ruff and bytecode compilation passed; evaluate/consume p95 6.635800 ms; 256 termination transitions averaged 1.283404 ms with zero worker-thread delta | P0=0, P1=0, P2=0; P3 monolith advisory retained |

The focused reproduction commands are:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_phase5_runtime_v10.py
.\.venv\Scripts\python.exe -I -S -B scripts\verify_phase5_runtime_v10_acceptance.py
```

The checkpoint and its existing machine-readable manifest remain the authority
for candidate-internal counts and measurements. This record is the external
acceptance authority for the exact root above.

## Exact acceptance boundary

Accepted:

- the exact frozen Runtime Core V10 implementation and test closure above;
- fail-closed decision evaluation, bounded projections and component health;
- the host-owned four-action termination plan and atomic acknowledgement truth;
- sticky crypto degradation and exact immutable 32-byte key construction;
- implementation handoff for a separately reviewed Phase 5 integration.

Not accepted or activated:

- imports or flags in `main.py`, `ui.py`, `dashboard/`, startup or launchers;
- live dispatch, grant, connector, provider, MCP or external-mutation authority;
- execution of cleanup callbacks by the core itself;
- Phase 5 Integration, exact low-risk activation or the Phase 5 exit;
- Phase 6, any later phase or completion of Onyx or its master plan.

V10 remains isolated, default-off and unwired. Acceptance does not alter the
running Onyx process and does not authorize bypassing existing host policy,
permission, audit or safety boundaries. Activation requires an independently
reviewed integration checkpoint with extension-off equivalence, rollback,
kill/revoke propagation and live resource evidence.

## Operational limitations and P3 advisory

The integrity gate's prior external-root/process limitation is closed only for
this exact four-anchor root: the separate acceptance manifest and verifier can
be run from the authoritative project root without modifying or importing the
candidate into live surfaces. It is not a proof against concurrent filesystem
mutation or a substitute for later integration evidence.

The 2,744-line, approximately 102 KiB core remains a P3 monolith advisory.
Future maintainers should split internal concerns only in a new version with
equivalence tests; V10 bytes must remain frozen. Cleanup execution remains
host-owned, the diagnostic ring retains only its newest 128 telemetry faults,
the crypto latch requires a new runtime instance to recover, and the DLP
scanner remains defensive pattern recognition rather than proof against every
possible encoding.

## History and next transition

V1 through V9 remain historical/rejected candidates and are not retroactively
accepted. Runtime Core V10 acceptance permits only a new default-off Phase 5
integration candidate. Phase 5 remains incomplete until that integration,
exact low-risk enablement and the Phase 5 E1-E6 exit decision are separately
accepted.
