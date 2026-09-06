# Phase 5 Exit Candidate V1 checkpoint

Date: 2026-07-23

Status: **local E1-E5 candidate; E6 external acceptance pending**.

## Composition

This checkpoint composes, without modifying, the five existing external
acceptances:

| Input | External acceptance | Candidate use |
|---|---|---|
| Runtime Core V10 | `VE-P5-RUNTIME-V10-E6-001` | isolated runtime/termination contract |
| Session Grants R11 | `VE-P51-GRANTS-R11-E6-001` | bounded default-off shadow decisions |
| Approval Inbox V15 | `VE-P52-APPROVAL-INBOX-V15-E6-001` | read-only, non-authoritative projection |
| Capability Nexus V32 | `VE-P53-CAPABILITY-NEXUS-V32-E6-001` | descriptor and local catalog projection |
| Integration V3 | `VE-P5-INTEGRATION-V3-E6-001` | exact low-risk transition and rollback boundary |

Component Adapters V3 is a transitive Integration V3 anchor and is rehashed;
it is not represented as a sixth independent acceptance.

## Candidate boundary

The candidate:

- adds evidence, a verifier and tests only;
- creates no runtime module and no feature flag;
- does not edit or import from `main.py`, `ui.py`, `dashboard/` or launchers;
- does not activate grants, approval, dispatch, connectors, providers, MCP,
  credentials, external mutations or remote authority;
- keeps the Integration V3 flags default-off; and
- cannot accept itself.

The candidate manifest is a local hash inventory, not E6 authority. The
historical capability matrix and verification evidence remain byte-identical.
Candidate changes are recorded in immutable local delta files inside this
checkpoint and are candidate roots. The two historical projections are also
full-file hash anchors; no prefix fallback or reconstructed projection is
allowed.

The canonical startup closure contains all Live V1-V8 `.pyw` launchers, the
V8 bootstrap, the V4-V8 active/rollback commands, the legacy launcher and the
applicable setup, build, release-eligibility, workflow and OS packaging
entrypoints. Its manifest list must equal the discovered filesystem set.

## Verification contract

The release verifier:

1. parses the manifest with a closed schema and rejects duplicate paths;
2. rehashes every candidate, acceptance, component, verifier and live-surface
   anchor;
3. parses each one-line E6 acceptance manifest and proves it names the exact
   accepted record;
4. checks the eight Integration V3 flag defaults through the Python AST;
5. rehashes both historical projection documents as exact complete files and
   rejects an appended suffix instead of recovering an old prefix;
6. requires the canonical startup closure to have no missing or extra paths,
   hash-binds every member and rejects Phase 5 Exit symbols on any member;
7. proves the exit candidate is absent from application/live surfaces;
8. executes the accepted Integration V3 verifier from its byte-exact
   historical projection, which executes the frozen Runtime V10, Approval
   Inbox V15 and Capability Nexus V32 verifier closures;
9. executes exact Grants R11 verifier code proportionally over its immutable
   root, artifact, bundle, JUnit, log and code evidence, while explicitly
   reporting that its obsolete historical live-surface scan was not replayed;
10. requires the accepted V3 transition verifier to remain in the Integration
   V3 closure; and
11. rejects any manifest claim of E6, Phase 6 unlock, activation or Onyx
   completion.

`--no-external` exists only for focused tests of the composition logic. It
cannot produce a release-pass result and reports `external_verifiers_executed:
false`.

## Default-off and rollback proof

The current `main.py`, `ui.py` and `dashboard/server.py` hashes are frozen in
the manifest so this candidate cannot silently adopt a concurrent application
change. The candidate name and flag are absent from those surfaces and from
the existing startup/launcher scope.

Rollback before E6 is evidence-only: remove this candidate's checkpoint,
verifier, tests and ADR. There is no runtime state to undo and no historical
projection document to restore. Integration V3's separately accepted
kill/revoke/rollback transition remains unchanged.

## Decision limits

This checkpoint does **not** assert external E6 acceptance. It does **not** declare the Phase 5 exit complete.
It does not unlock Phase 6, activate a live capability, or establish that Onyx
or the master PRD is complete. A separate independent
E6 record is required for the exact frozen candidate. Phase 5 remains incomplete
until that independent decision exists.
