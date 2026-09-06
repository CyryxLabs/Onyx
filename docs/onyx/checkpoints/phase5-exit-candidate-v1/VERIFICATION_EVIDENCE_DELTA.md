# `VE-P5-EXIT-CANDIDATE-V1-E1E5-001` — local composition, E6 pending

This immutable candidate-local delta is not external acceptance. It
intentionally does not mutate the historical
`docs/onyx/VERIFICATION_EVIDENCE.md` projection used by accepted Phase 5
verification closures. The candidate binds the complete historical matrix and
evidence files by exact SHA-256; it has no prefix-recovery path.

It composes five independently accepted Phase 5 inputs while retaining each
exact scope:

- Runtime Core V10: `VE-P5-RUNTIME-V10-E6-001`;
- Session Grants R11: `VE-P51-GRANTS-R11-E6-001`;
- Approval Inbox V15: `VE-P52-APPROVAL-INBOX-V15-E6-001`;
- Capability Nexus V32: `VE-P53-CAPABILITY-NEXUS-V32-E6-001`; and
- Integration V3: `VE-P5-INTEGRATION-V3-E6-001`.

The candidate authority is `manifest.json`. That manifest does not hash itself
and cannot self-accept. It binds the ADR, checkpoint, verifier, tests, these
two local deltas, five acceptance records and one-line acceptance manifests,
accepted component roots, existing external verifiers, Component Adapters V3
as a transitive Integration V3 anchor, and unchanged `main.py`, `ui.py` and
`dashboard/server.py` bytes.

The gate recalculates all listed hashes, checks the one-line acceptance
relations, proves all eight Integration V3 flags remain exact `False`, proves
the exit-candidate symbols are absent from live surfaces, and executes the
accepted Integration V3 historical closure. That closure executes the frozen
Runtime V10, Approval Inbox V15 and Capability Nexus V32 verifiers. Exact
Grants R11 verifier code executes proportionally over immutable
root/artifact/bundle/JUnit/log/code evidence; its obsolete full historical
live-surface scan is explicitly not replayed against later accepted changes.
The gate also discovers an exact 28-file startup/release closure spanning Live
V1-V8, bootstrap V8, V4-V8 active/rollback commands, legacy launch and
cross-platform packaging entrypoints. Missing or extra paths and any Phase 5
Exit symbol in that closure are rejected.

Focused `--no-external` mode is explicitly non-release and reports zero
external verifiers executed.

The default-off rollback is evidence-only: remove the candidate checkpoint,
verifier, tests and ADR. No restart or runtime cleanup is required because the
candidate adds no runtime module, flag, application import, authority or live
state.

Phase 5 remains incomplete. This record covers only a local E1-E5 candidate.
External E6 review is pending; Phase 6 is not unlocked, no capability is newly
activated, and Onyx/master-PRD completion is not established.
