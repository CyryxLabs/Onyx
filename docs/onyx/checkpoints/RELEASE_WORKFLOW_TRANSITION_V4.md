# Release Workflow transition V4

Status: **AUTHENTICATED CURRENT SOURCE POLICY**  
Transition: `tests/fixtures/release_workflow_transition_v4.json`  
Transition SHA-256: `bec9658f723fc467d888b311780d013689f6a6ac09cda58ec01827c96b60f12d`  
Domain root: `690da4e1f7fd0cd5cdb7bb8f911f140fe3e1a6ccda6b1048ac999f5f56fb1a48`

V4 preserves exact Release Workflow V3, V2 and V1 predecessors. It binds 31
current release-source files, including the runtime lifecycle regression that
proves provider-specific continuity reasons are normalized before Phase 5
termination.

It does not make an unsigned Windows artifact formal, permit diagnostic
publication or relax any signing, notarization, native-platform,
clean-machine, legal or independent-review gate.
