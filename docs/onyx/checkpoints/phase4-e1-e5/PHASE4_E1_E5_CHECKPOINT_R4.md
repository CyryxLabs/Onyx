# Phase 4 E1-E5 checkpoint candidate R4

Evidence candidate: `VE-P4-EXIT-CANDIDATE-R4-001`  
Input scope: `VE-SCOPE-P4-E1E5-R4-001` plus accepted successor R11  
Output scope: `VE-ARTIFACTS-P4-E1E5-R4-001`  
Decision: **candidate only; E6 false; activation false; Phase 5 blocked**

## Successor boundary

R4 preserves the R3 default-off/authority checks and replaces only the mutable
dependency anchor with comprehensive `VE-SCOPE-P44-R11-001`. R11 is the exact
R10 universe plus `scripts/verify_p44_scope_r11.py` and the focused shortcut
regression `tests/test_desktop_shortcut.py`; current `ui.py` bytes are therefore
bound. Historical R10 and R3 files remain immutable and are not rebound.

The regression proves that the source-checkout Windows shortcut generator uses
`.venv/Scripts/pythonw.exe`, the diagnostic
`scripts/launch_onyx.pyw`, the repository working directory and the checked-in
`config/onyx.ico`, and that the COM argument is quoted. It changes no Phase 4
schema, flag, authority, provider, owner data or runtime wiring.

The R4 proportional selection explicitly retires the R3 whole-file node because
that node contains the obsolete assertion that current product bytes still
match historical R10. Its twelve behavioral/DAG/default-off test functions are
listed individually and retained; only
`test_source_only_gate_is_current_and_nonactivating` is replaced by R4's
R11-bound successor assertion. This is a deliberate successor binding, not a
skip or a mutation of R3/R10.

## Evidence DAG

```text
R11 + R4 source/docs/tests/selection
                 |
                 v
      VE-SCOPE-P4-E1E5-R4-001
                 |
                 v
     source/test/static raw outputs
                 |
                 v
     phase4-e1-e5-r4.bundle.json
                 |
                 v
    VE-ARTIFACTS-P4-E1E5-R4-001
                 |
                 v
       independent future E6 record
```

Neither manifest hashes itself. The source manifest binds the artifact
manifest, while the artifact manifest binds only generated outputs. The bundle
does not claim either manifest's hash. Only a later independent E6 record may
anchor the completed artifact-manifest digest and decide acceptance.

## Safety and operational separation

All eight Phase 4 flags remain default-off. The source gate runs an offline,
guarded import probe and a disabled-V1 zero-write probe; proportional tests use
isolated temporary stores. No owner data, live process, external provider,
connector, approval, grant, commit or push is in scope.

The already-running operational process was deliberately untouched while this
package was produced. The preceding operational snapshot reported launcher PID
41352, runtime PID 48872 and HTTPS listeners on ports 8000 and 8001. Those
ephemeral observations support operational continuity only; they are not frozen
Phase 4 proof and do not satisfy E6.

## Retained blockers

- canonical Windows M1a activation remains `BLOCKED_BY_PLATFORM`;
- owner backfill and production workspace isolation remain unproved;
- provider/connectors/MCP and physical remote-device paths are not accepted;
- exact signed cross-platform installers remain unproved;
- proprietary/public release remains `BLOCKED_BY_LICENSE`;
- E6 is false, activation is false and Phase 5 remains blocked.
