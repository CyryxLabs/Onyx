# ADR-0018: Phase 5 exit candidate as an evidence-only composition

- Status: Accepted for local E1-E5 candidate construction
- Date: 2026-07-23
- Scope: Phase 5 exit candidate V1 only

## Context

Phase 5 has five independently accepted inputs:

1. Runtime Core V10 (`VE-P5-RUNTIME-V10-E6-001`);
2. Session Grants R11 (`VE-P51-GRANTS-R11-E6-001`);
3. Approval Inbox V15 (`VE-P52-APPROVAL-INBOX-V15-E6-001`);
4. Capability Nexus V32 (`VE-P53-CAPABILITY-NEXUS-V32-E6-001`); and
5. Integration V3 (`VE-P5-INTEGRATION-V3-E6-001`).

Each acceptance is deliberately narrower than a Phase 5 exit. Repeating their
claims in a new document is not enough to prove that the accepted roots still
coexist, that the Integration V3 transition still verifies, or that the
default-off and rollback boundaries remain intact.

## Decision

Create an evidence-only `phase5-exit-candidate-v1` composition. It contains no
runtime module, feature flag, startup import, UI hook, dashboard endpoint,
launcher change or activation instruction.

The candidate manifest binds:

- the five external E6 records and their one-line acceptance manifests;
- the accepted implementation roots and the Integration V3 adapter anchor;
- the existing external verifiers used by those acceptances;
- the full exact bytes of the accepted historical `CAPABILITY_MATRIX.md` and
  `VERIFICATION_EVIDENCE.md` projections, with no prefix reconstruction;
- the canonical startup closure: Live V1-V8 launchers, the V8 bootstrap,
  active/rollback commands and applicable packaging/release entrypoints;
- the current `main.py`, `ui.py` and `dashboard/server.py` bytes as unchanged
  live-surface anchors; and
- this ADR, the checkpoint, verifier and tests.

The verifier fails closed unless all hashes match, every acceptance manifest
resolves to its exact record, Integration V3 keeps all eight flags default
`False`, no exit-candidate symbol appears on a live surface, and the accepted
Integration V3 verifier reproduces its exact marker from a byte-exact
historical projection. That execution reproduces the Runtime V10, Approval
Inbox V15 and Capability Nexus V32 verifier closures. The exact Grants R11
verifier source is executed proportionally against its immutable root,
artifact, bundle, JUnit, log and code evidence; its obsolete historical
live-surface scan is not replayed against later accepted application changes.
Any append to either historical projection fails its full-file hash. Missing
or extra startup surfaces and Phase 5 Exit symbols on any startup or packaging
surface also fail closed.

## E1-E5 interpretation

This composition is a local Phase 5 exit candidate covering:

- E1: exact accepted-scope composition;
- E2: hash/root and provenance closure;
- E3: default-off and non-authority boundary;
- E4: deterministic rollback by removing only candidate evidence, including
  its two candidate-local immutable deltas; and
- E5: reproducible local verification.

E6 is intentionally not self-issued. A separate independent review must decide
whether these exact candidate bytes are accepted. Phase 5 remains incomplete
until that happens, Phase 6 is not unlocked by this candidate, and no claim of
Onyx or PRD completion is permitted.

## Rollback

The candidate changes no executable application surface. Before external E6,
rollback consists only of deleting the candidate checkpoint directory,
verifier, tests and this ADR. The accepted historical `CAPABILITY_MATRIX.md`
and `VERIFICATION_EVIDENCE.md` projections remain byte-identical; candidate
deltas live only inside the checkpoint. No process restart, grant revocation,
provider cleanup or data migration is required because this candidate
activates nothing.

Integration V3 retains its own kill/revoke/rollback/end-session boundary and
its accepted transition verifier remains the authority for that runtime
contract. This ADR does not widen it.

## Consequences

- Positive: the Phase 5 exit decision receives one bounded, reproducible input.
- Positive: accepted components remain byte-for-byte frozen.
- Positive: accepted historical projection documents remain byte-identical.
- Positive: the startup and packaging boundary is an exact discovered and
  hash-bound closure rather than a partial launcher sample.
- Negative: the full gate materializes and executes the accepted Integration
  V3 historical closure, including the Runtime, Inbox and Nexus verifiers.
- Limitation: R11 is checked proportionally from the exact verifier source and
  frozen evidence; its full historical live-scan replay is explicitly false.
- Limitation: stable-file hashes are not an atomic concurrent-writer boundary;
  run the gate against a non-concurrently-mutated authoritative tree.
