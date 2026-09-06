# Phase 4 E1-E5 checkpoint candidate R5

Evidence candidate: `VE-P4-EXIT-CANDIDATE-R5-001`  
Top-level input: `VE-SCOPE-P4-E1E5-R5-001` plus comprehensive R11  
Second level: `VE-ARTIFACTS-P4-E1E5-R5-001`  
Decision: **candidate only; E6 false; activation false; Phase 5 blocked**

## Evidence-only correction

R4 is historical/rejected as exit evidence because its bundle instructed a
future E6 record to anchor the artifact-manifest digest. The actual acyclic
dependency direction requires the external record to anchor the top-level R5
**source-manifest SHA-256**:

```text
independent external E6 registration
              |
              v
 VE-SCOPE-P4-E1E5-R5-001.sha256
              |
              v
 VE-ARTIFACTS-P4-E1E5-R5-001.sha256
              |
              v
     R5 bundle + unchanged R4 outputs
```

The source manifest binds R11, the current verifier/test/selection, this
checkpoint, the capability-matrix history and the artifact manifest. The
artifact manifest binds the R5 bundle and the unchanged R4 source JSON, raw
pytest log, JUnit and static log. Neither manifest hashes itself; the bundle
claims no bundle or manifest digest.

No external registration exists in R5. A later E6 record must independently
store the exact R5 source-manifest SHA-256 and validate both levels before it
can decide acceptance.

## Reused evidence

No long test was rerun. R5 reuses the immutable R4 canonical evidence:

- 67 pytest passes plus 6 subtests; JUnit 73, zero failures/errors/skips;
- source gate `P4_EXIT_CANDIDATE_R4_SOURCE_OK`;
- Ruff, `py_compile` and `git diff --check` exit zero;
- R11 reconstructs 79 current files;
- eight Phase 4 flags were observed default-off in the R4 evidence;
- activation and E6 remained false.

R5 adds only a focused verifier/self-test for the corrected trust direction.
It proves source, test, R11, checkpoint or artifact-manifest drift breaks the
top-level validation, while bundle/output drift breaks the second level.

## Safety boundary and retained blockers

This correction changes no product code, runtime, flags, owner data or
authority. It performs no provider/device/browser action, restart, commit or
push. Canonical Windows M1a activation, owner backfill, production workspace
isolation, external providers/connectors, physical remote-device proof,
signed cross-platform installers and licensing remain unresolved. E6 is false
and Phase 5 remains blocked.
