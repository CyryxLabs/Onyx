# Phase 4 E1-E5 checkpoint candidate R3

Evidence candidate: `VE-P4-EXIT-CANDIDATE-R3-001`  
Planned input scope: `VE-SCOPE-P4-E1E5-R3-001` plus accepted R10  
Planned output scope: `VE-ARTIFACTS-P4-E1E5-R3-001`  
Decision: **candidate only; E6 false; activation false; Phase 5 blocked**

This is the documentation skeleton for the R3 corrective candidate.  It does
not claim that the planned manifests, bundle, probes or test results exist.
Those artifacts must be generated from the final frozen bytes and then undergo
independent E6 review.  R1 and R2 remain immutable historical/rejected
candidates and may not be used as Phase 4 exit evidence.

## E1 — exact boundary and retained blockers

R3 remains a read-only/default-off verification package around the accepted
R10 product universe.  It may inspect source/import state in an isolated
process, exercise isolated temporary stores and package verification evidence.
It may not enable a Phase 4 flag, wire startup or owner data, invoke a provider,
create an external grant, restart the operational assistant or unlock Phase 5.

The startup policy separates two concepts that R2 conflated:

- `AUTHORITY_BEARING` is the deny set for the default-off Phase 4 repositories
  and wiring boundaries.  It excludes `core.native_vault`.  The native vault is
  a pre-existing shared credential backend reached by the stable credential
  path; treating it as a Phase 4 activation module would make the unchanged
  operational startup fail by definition.
- Exclusion from `AUTHORITY_BEARING` is not exclusion from inspection.  The
  complete local startup import closure, including `core.native_vault` where
  reached, remains inside the R3 transitive-closure observation and frozen
  input boundary.

Retained blockers are unchanged: M1a canonical Windows policy is
`BLOCKED_BY_PLATFORM`; owner backfill and production workspace isolation are
unproved; provider/connectors/MCP and physical remote/device paths are not
accepted; exact native installers are not proven; proprietary/public release
is `BLOCKED_BY_LICENSE`.

## E2 — capability delta

R3 changes evidence mechanics only.  The capability matrix therefore retains:

- M1a inert schema / canonical Windows activation: `BLOCKED_BY_PLATFORM`;
- workspace registry/isolation: `PARTIAL`;
- mission context sidecar/operational phases: `PARTIAL`;
- evidence, claims and action ledgers: `PARTIAL`.

No isolated fixture, scanner result or green test may promote these statuses or
stand in for production activation evidence.

## E3 — complete input selection and guarded observation

The planned R3 verifier must derive the local startup dependency set as a
transitive closure rather than scan four hand-selected files.  Static imports
and resolvable local dependencies are inspected structurally.  A guarded
subprocess probe observes the actual import closure with all eight Phase 4
flags explicitly disabled, a bounded timeout and machine-readable output.  The
probe must not start the assistant, instantiate the UI/dashboard, access owner
stores or contact providers.  Timeout, crash, malformed output, an unexpected
module or any observed authority-bearing module is a typed verification
failure.

The structural scanner also enforces a raw-token boundary over startup-closure
sources.  This boundary is independent of AST name resolution and rejects
forbidden dynamic-import/execution primitives even when they are reached
through dictionaries, containers, stored callables, aliases or literal
`getattr` forms.  Safe comments and string data require explicit deterministic
handling; the rule must not silently weaken on syntax or decoding failure.

The exact pytest selection is the set union of the complete R2 selection and
the R3 corrective tests.  It is sorted, duplicate-free and mechanically
compared with both source selection files.  R3 may add coverage but may not
silently remove a previously selected R2 node.

## E4 — acyclic evidence DAG and rollback boundary

R3 uses two manifests and one external acceptance anchor.  The dependency
graph is deliberately acyclic:

```text
frozen source/docs/tests/selection + accepted R10
                    |
                    v
        VE-SCOPE-P4-E1E5-R3-001
                    |
                    v
       verifier/test/static raw outputs
                    |
                    v
       phase4-e1-e5-r3.bundle.json
                    |
                    v
       VE-ARTIFACTS-P4-E1E5-R3-001
                    |
                    v
  external E6 record in VERIFICATION_EVIDENCE.md
```

The input manifest binds only inputs.  The bundle records the input-manifest
digest, commands, durations, counts and output digests.  The output manifest
binds the completed bundle and generated raw evidence; neither manifest hashes
itself, and no upstream artifact embeds the digest of a downstream artifact.
Only an independent E6 reviewer may anchor the final output-manifest SHA-256 in
`VERIFICATION_EVIDENCE.md` while recording PASS or FAIL.  Until that external
anchor exists, the package is reproducible candidate material, not accepted
Phase 4 exit proof.

Rollback remains default-off: keep all eight flags false, detach any future
integration before disable, preserve sidecars for diagnosis/export, reconcile
unknown outcomes before retry and delete only after verified export plus
explicit owner action.  R3 creates no active grant or connector to revoke.

## E5 — checkpoint inventory and operational separation

R3 is intended to add only verifier/tests/selection/documentation and generated
evidence.  It adds no product schema, API, event, migration, provider call,
dependency, production import, authority or owner write.  The accepted R10
inventory and controlling ADRs remain unchanged.

Operational liveness is a separate concern.  A clean shutdown or offline state
of the live assistant is not proof for or against this evidence package, and
this package must not relaunch it.  The root operator will relaunch and verify
the operational assistant separately.  Conversely, a successful relaunch
cannot accept R3, satisfy E6 or unlock Phase 5.

## E6 handoff state

E6 is **false**.  After the R3 bytes and both manifests are frozen, independent
review must reconstruct the full DAG, rerun proportional checks, inspect the
raw-token and subprocess boundaries, and record the output-manifest digest
externally.  Any P0/P1/P2 finding rejects R3.  Until a clean independent E6
decision is recorded, activation remains false and Phase 5 remains blocked.
