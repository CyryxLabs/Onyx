# Release Workflow transition V3

Status: **AUTHENTICATED CURRENT SOURCE POLICY**  
Transition: `tests/fixtures/release_workflow_transition_v3.json`  
Transition SHA-256: `ebe4cc60506b14ac6f41b7306078289e033eedfcb8308130d21b54d46c6d24c0`  
Domain root: `a8409ad8262e989e608f9368b05a9924cfcb9d6a4c203a3d2539bc9f3425e5fc`

V3 preserves exact Release Workflow V2 and V1 predecessors. It binds 29 current
release-source files, including the portable-archive regression suite. It does
not make an unsigned Windows artifact formal, permit diagnostic publication or
relax any signing, notarization, native-platform or independent-review gate.
