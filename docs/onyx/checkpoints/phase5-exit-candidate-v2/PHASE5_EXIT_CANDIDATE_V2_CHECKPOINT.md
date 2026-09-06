# Phase 5 Exit Candidate V2 checkpoint

Date: 2026-07-23

Status: **local E1-E5 candidate; E6 external acceptance pending**.

## Composition

Candidate V2 is an evidence-only successor to Candidate V1. It preserves the
exact V1 root `3188e006fa11040eb8d743086c74f0ceae70a1d62b70e9919ca73cb41187ec80`
and adds the externally accepted, default-off Onyx Live Activation V9 closure:
`VE-ONYX-LIVE-ACTIVATION-V9-E6-001`.

The five Phase 5 component acceptances remain unchanged and are still executed
through the V1 component closure:

1. `VE-P5-RUNTIME-V10-E6-001`;
2. `VE-P51-GRANTS-R11-E6-001`;
3. `VE-P52-APPROVAL-INBOX-V15-E6-001`;
4. `VE-P53-CAPABILITY-NEXUS-V32-E6-001`; and
5. `VE-P5-INTEGRATION-V3-E6-001`.

V2 does not modify Candidate V1, any accepted component, Activation V9,
`main.py`, `ui.py`, dashboard, launcher, bootstrap, command or packaging byte.

## Canonical startup and release closure

The V2 manifest binds and the verifier independently discovers an exact
32-file startup/release closure:

- legacy launcher and Live V1-V9 launchers;
- V8 and V9 bootstraps;
- V4-V9 active and rollback commands; and
- setup, build, release-eligibility, release-workflow and Windows/macOS/Linux
  packaging entrypoints.

The manifest list and discovered filesystem set must be identical. A missing
or extra versioned launcher, bootstrap, active/rollback command, release
workflow or packaging file fails closed. Every member is a full-file SHA-256
binding. Phase 5 Exit symbols are forbidden across the complete closure and
the application surfaces.

All 20 exact Activation V9 candidate bindings are rehashed, including its
runtime core, launcher, bootstrap, commands, verifier, tests, checkpoint,
runtime manifest, accepted V8/HUD roots, hosts and runtime Python executable.
The V9 candidate manifest, E6 record, E6 metadata, acceptance verifier and
acceptance test are separately bound by V2. The externally materialized
`VE-SOURCE`, `VE-ARTIFACTS` and one-line `VE-ACCEPTANCE` anchors are also exact
V2 bindings and their record relations are reparsed.

## Independent root algorithm

V2 has one canonical independent-root algorithm:
`sha256-domain-count-u32be-path-u32be-role-digest32-v1`.

Let `entries` be the exact `files` array in the V2 manifest. Reject an empty
array, duplicate paths, noncanonical paths, invalid roles or invalid SHA-256
values. Sort entries by the raw UTF-8 bytes of `path`. Build one byte string:

1. ASCII domain bytes `onyx.phase5.exit-candidate.v2.bindings.v1` followed by
   one NUL byte;
2. the entry count as an unsigned 32-bit big-endian integer;
3. for each sorted entry:
   - one record byte `0x01`;
   - path byte length as unsigned 32-bit big-endian;
   - raw UTF-8 path bytes;
   - role byte length as unsigned 32-bit big-endian;
   - raw UTF-8 role bytes;
   - the 32 raw bytes decoded from the lowercase hexadecimal `sha256`.

The independent root is SHA-256 of that complete framed byte string. No JSON
serialization, newline convention, delimiter inference, prefix recovery or
predecessor root is part of this algorithm. The verifier and an independently
implemented test must reproduce the same root and binding count. The rejected
prior `176ca...` value is not reused.

## Verification and honest limits

The V2 gate:

- rehashes every V2 binding and recomputes the independent root;
- executes the five preserved component acceptance/evidence closures;
- retains the exact full-file `CAPABILITY_MATRIX.md` and
  `VERIFICATION_EVIDENCE.md` anchors, with no prefix fallback;
- proves the eight Integration V3 flags remain exact `False`;
- validates and executes the exact V9 external acceptance envelope;
- rejects missing/extra startup paths and forbidden Exit symbols; and
- rejects E6, Phase 6 unlock, activation, runtime-authority or completion
  overclaims.

The Grants R11 execution remains proportional over its immutable
root/artifact/bundle/JUnit/log/code evidence. Its obsolete full historical
live-surface scan is explicitly not replayed. Activation V9 acceptance is
limited to the Windows source-checkout shortcut/bootstrap contract, simulated
COM, real network-blocked preflight and default-off composition. It does not
certify packaged installations or a physical live handoff.

The legacy Candidate V1 test suite is intentionally not a cumulative V2 gate:
two of its tests rediscover the V1-V8 startup closure and therefore reject the
later V9 bootstrap as an extra path. A direct historical-suite replay produced
`275 passed, 2 failed`, with both failures limited to that obsolete V1 startup
discovery. The V2-compatible cumulative gate excludes that direct suite while
the V2 verifier still rehashes all 66 V1 bindings and reproduces its five
component closures, eight default-false flags and full-file anchors before
enforcing the new exact V1-V9 closure.

The deterministic 257-test cumulative membership and arguments are recorded in
and hash-bound through `cumulative-selection.json`. Its exact Windows command
is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_grants_v11.py tests/test_approval_inbox_v15_acceptance.py tests/test_capability_nexus_v32_acceptance.py tests/test_phase5_component_adapters_v3.py tests/test_phase5_runtime_v10.py tests/test_phase5_integration_v3.py tests/test_phase5_integration_v3_transition.py tests/test_onyx_live_activation_v9.py tests/test_onyx_live_activation_v9_acceptance.py tests/test_phase5_exit_candidate_v2.py --disable-warnings --basetemp .pytest-p5-exit-v2-compatible
```

This checkpoint does **not** declare the Phase 5 exit complete. Phase 5 remains incomplete.
It does not unlock Phase 6, activate Onyx, establish runtime authority, or
establish that Onyx or the master PRD is complete.

## Rollback

Rollback before external E6 is evidence-only: delete this V2 checkpoint,
verifier and tests. Candidate V1 and accepted Activation V9 remain unchanged.
No application restart, grant revocation, provider cleanup, data migration or
runtime rollback is required because V2 creates no executable surface or live
state.
