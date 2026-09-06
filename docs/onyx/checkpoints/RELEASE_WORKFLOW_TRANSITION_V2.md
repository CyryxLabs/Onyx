# Release workflow transition V2

Issued: 2026-08-03T22:40:00-04:00  
State: authenticated current release-source policy; native receipts pending  
Transition: `tests/fixtures/release_workflow_transition_v2.json`  
Transition SHA-256: `b34e19a6a34ab8384588203ae73f642df81e5b583d1caf3babe73dd02573794b`  
Domain root: `ed1b777dbf43014185cd6fb70616346f9619d5206e393e1c5773ec6d2f515050`

V2 preserves exact Release Workflow V1 and its Phase 5 V9 predecessor. It
binds 28 current release files covering the Windows, Linux and macOS builders,
autostart templates, lifecycle validators, technical dependency evidence and
their focused tests. Formal Windows release still requires a trusted signer and
clean disposable host; macOS still requires native Developer ID/notarization;
Linux and macOS still require native desktop/audio/GUI lifecycle receipts.
