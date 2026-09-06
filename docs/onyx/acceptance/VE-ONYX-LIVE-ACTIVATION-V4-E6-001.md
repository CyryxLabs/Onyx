# Onyx Live Activation V4 External E6 Acceptance

- Evidence ID: `VE-ONYX-LIVE-ACTIVATION-V4-E6-001`
- Decision date: 2026-07-22
- Decision: **ACCEPTED - Onyx Live Activation V4 frozen default-off handoff only**
- Candidate: `onyx-live-activation-v4`

## Frozen candidate anchor

This decision accepts only the exact default-off candidate represented by the
following immutable anchors. It does not set a flag, activate Onyx, restart a
process, change a shortcut, provision a credential, or call a provider.

| Anchor | SHA-256 |
|---|---|
| Candidate manifest | `ebe3b24e641d1148e3ddb3767705b593a0d9df0898ba2654b53cd7820e0d6c09` |
| Candidate checkpoint | `3ea17bf227025f7dbe2ce4f91e15801151c6262efc01173657e7c3ce481d638f` |
| Acceptance verifier | `01bd0f31c168a1c5a03c75b4264b472763bd189944acfc977e4137fcd8978309` |
| Acceptance tests | `86b22756c450db1c12e0891eef866c75791854b3c18d8580dfe56332ac6c7b14` |

The candidate manifest is the authoritative root. Its complete **53/53** file
closure was independently read through canonical regular paths and rehashed.
The closure preserves all rejected history (V1: 7 files, V2: 8 files, V3: 9
files), the seven V4 candidate artifacts, five frozen host surfaces, ten
accepted components, and seven earlier accepted E6 records. Candidate bytes
were not changed while producing this external acceptance.

## Independent decision

The independent acceptance result is **PASS: P0=0, P1=0, P2=0, P3=1**.

The sole P3 advisory is a **bundled timeout label gap**. The frozen checkpoint
states the cancellation invariant, but the bundled real-Qt gate's final output
does not label a forced timeout/no-late-mutation result explicitly. The
external acceptance test closes the evidentiary gap without changing candidate
bytes: a real offscreen `QApplication` queues an owner-UI request, deliberately
withholds GUI event processing until the endpoint returns `TimeoutError` and
removes the request, then delivers the late queued signal repeatedly. The
controller mutation callback remains unreachable and the request remains
non-pending. A later candidate should bundle that label directly.

This advisory does not weaken the V4 cancellation implementation or justify a
P0, P1, or P2 finding. It is an evidence-label improvement only.

## Reproduced evidence

- Focused Activation V4: **13 passed, 0 failed**.
- Combined Owner Profile V8 + Phase 5 Integration V3 + HUD V5 + Activation V4:
  **67 passed, 0 failed**.
- Real host: **11/11** transactional seam failpoints; **64/64** reconnects;
  **64/64** local catalog reads; **128** unique session/trace identifiers.
- Real offscreen Qt: exact set/correct/forget readback, two-window atomicity,
  setup open/closed, affinity, no-op/wrong/getter refusal, compound rollback,
  destroyed-target handling, durable compensation, and sticky degradation.
- External real-Qt timeout: `TimeoutError`, pending membership removed before
  late delivery, and zero late mutations after repeated event processing.
- Candidate bundle verifier, acceptance verifier, Ruff, and Python compilation:
  pass.

The candidate's earlier accepted E6 anchors remain exact:

| Accepted dependency | SHA-256 |
|---|---|
| Owner Profile V8 | `61c1f7986e6de153efe41f79bf8520b555365b3e1c14c55a431f66e2519164d7` |
| Phase 5 Integration V3 | `03e23fca1a5a6772a2e5b70611b9329808bb933a386271882ed32462fcc7f82b` |
| HUD / Orb V5 Live | `db6bbcb53a249e5db5d2f3e461fb60aec44acd9d9784b33314f947e3f3215acf` |
| Runtime Core V10 | `135be5fc3e97e81466f398fcc9211da767c0e3fb251387588dfd836d02b28de0` |
| Session Grants R11 | `ff703416675653b4f1611e7f9ee633fac974c3bdf4225a16d84f302233b824d4` |
| Approval Inbox V15 | `45d9d215c0fd8024f730ec3f4436507c411658ea1e8f6d26e133ce707bc3d908` |
| Capability Nexus V32 | `b75ccb2b4bc58a4c4d72445d46eb66e550636cbb0deb02ecef304c8327f9d1dc` |

## Default-off boundary

Activation V4 remains default-off and not activated. The frozen manifest says:

- `default_off=true`;
- `live_activated=false`;
- `live_restart_performed=false`;
- `provider_calls_performed=false`;
- `credential_provisioned=false`.

The canonical launcher rejects partial flags and any spelling other than the
exact string `1` before importing `main` or `ui`. No activation, restart,
credential provisioning, provider call, shortcut change, or service mutation
was performed by this acceptance work.

No activation, restart, credential provisioning, provider call, shortcut
change, or live mutation occurred during acceptance.

## Exact controlled activation recipe - recorded, not executed

Activation requires a controlled restart and the complete canonical
environment below. Omitting a child flag or using `true`, whitespace, or any
other truthy spelling is a pre-import refusal.

```powershell
$env:ONYX_LIVE_ACTIVATION_V4='1'
$env:ONYX_OWNER_PROFILE_V8_LIVE='1'
$env:ONYX_HUD_V5_LIVE='1'
$env:ONYX_PHASE5_INTEGRATION_V3='1'
$env:ONYX_PHASE5_RUNTIME_V3='1'
$env:ONYX_PHASE5_GRANT_SHADOW_V3='1'
$env:ONYX_PHASE5_APPROVAL_INBOX_V3='1'
$env:ONYX_PHASE5_LOW_RISK_V3='1'
$env:ONYX_PHASE5_NEXUS_PROJECTION_V3='1'
$env:ONYX_PHASE5_LOCAL_CATALOG_READ_V3='1'
$env:ONYX_PHASE5_DASHBOARD_PROJECTION_V3='1'
$env:ONYX_PHASE5_PRINCIPAL_ID='onyx-owner'
$env:ONYX_PHASE5_WORKSPACE_ID='onyx-local-workspace'
$env:ONYX_PHASE5_ACCOUNT_ID='cyryx-local-account'
$env:ONYX_PHASE5_PROFILE_ID='onyx-owner-profile'
& .\.venv\Scripts\pythonw.exe .\scripts\launch_onyx_live_v4.pyw
```

This is an operator recipe, not an instruction executed by the acceptance
gate. The acceptance result alone does not authorize activation.

## Exact single-switch rollback recipe - recorded, not executed

The frozen rollback switch is `ONYX_LIVE_ROLLBACK_V4=1`. The same canonical
launcher clears all V4 control flags in its child process and delegates to the
frozen legacy launcher `scripts/launch_onyx.pyw`.

```powershell
$env:ONYX_LIVE_ROLLBACK_V4='1'
& .\.venv\Scripts\pythonw.exe .\scripts\launch_onyx_live_v4.pyw
```

Rollback is accepted either as the single control flag in a clean environment
or alongside the complete active V4 control set. Partial combinations fail
closed. This acceptance did not execute rollback or restart Onyx.

## Reproduction commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_live_activation_v4.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_owner_profile_v8.py tests\test_phase5_integration_v3.py tests\test_onyx_hud_v5_live_integration.py tests\test_onyx_live_activation_v4.py
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v4_host.py
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v4_qt.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_live_activation_v4_acceptance.py
.\.venv\Scripts\python.exe -I -S -B scripts\verify_onyx_live_activation_v4_acceptance.py
```

The independent verifier must emit
`ONYX_LIVE_ACTIVATION_V4_ACCEPTANCE_OK`.

## Exact acceptance boundary

Accepted:

- the exact 53-file candidate manifest and default-off V4 transition;
- preserved V1-V3 rejected history and all seven accepted E6 anchors;
- the 11-seam preflight/install/provision order, continuity contract,
  Qt-affine transactional UI application, exact readback, compensation,
  timeout cancellation, and single-switch rollback definition;
- the external forced-timeout/no-late-mutation proof.

Not activated or accepted by this decision:

- setting activation flags, restarting Onyx, changing the desktop shortcut, or
  modifying a service;
- provisioning credentials or making provider/network calls;
- native macOS/Linux runtime or installer validation;
- completion of all later PRD phases or completion of Onyx as a whole.
