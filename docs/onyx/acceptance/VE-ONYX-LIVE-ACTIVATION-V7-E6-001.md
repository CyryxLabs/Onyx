# Onyx Live Activation V7 External E6 Acceptance

- Evidence ID: `VE-ONYX-LIVE-ACTIVATION-V7-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED - Onyx Live Activation V7 frozen default-off handoff**
- Candidate: `onyx-live-activation-v7`

## Frozen candidate anchors

This decision accepts only the exact default-off candidate represented by these
immutable anchors. It does not activate Onyx, restart a process, alter the
currently running V6 instance, provision a credential, change a shortcut, or
call a real provider.

| Anchor | SHA-256 |
|---|---|
| Candidate manifest | `312d6654f3423f16f4b36f435638920836994bd56c3e9a8766a086e2c6d647da` |
| Independent 19-binding root | `c6c52ca0d9a7725b543989c7586fc9fe9ab535282223b7fa0e1b0d1b8f5807cc` |
| Candidate checkpoint | `fc2cb24e0593500a39f3b9c69b29008803d1a6b6a7f695fd63c8b13f5988871b` |
| V7 core | `906c7c0e31cb5efc28e5357bb158545e903d65ff1f160b3899bc3e2fb3c1dc77` |
| V7 launcher | `a5dae76af4b09af90aa89b3638e2329fbed8c79a50fbcafa0a6179f38d82c531` |
| Candidate tests | `9ec4a10de3c08cf5e90ed6d58ca0292e9ff6f3edf1467be683d7ecd20bba8b6a` |
| Host gate | `c7868cd2fa1fd42c457da96cc295be817dc1ffd5ec93ba3294162f279e6ff109` |
| Full-host fake-provider gate | `48e7a1e63046848c7b93274cf17ef2be82fc561f163eb88b52ab3a97251ffc66` |
| External acceptance verifier | `23fb601ffe783e3283f4ff2d446f21e55f1b049a3b2b50fbefc52f8c4dac06d9` |
| External acceptance tests | `bad81b091ae09ca41f289f9515f2d630ca1fffbd83f2913426899f4d38d746d9` |

The candidate manifest is the authoritative frozen file list. The external
verifier rereads and rehashes its complete **19/19** regular-file closure. The
independent root is recomputed by sorting the manifest bindings by canonical
path, encoding each as `path + NUL + sha256 + LF`, concatenating the 19
bindings, and hashing the resulting UTF-8 bytes. This yields
`c6c52ca0d9a7725b543989c7586fc9fe9ab535282223b7fa0e1b0d1b8f5807cc`.

No V1-V7 candidate byte changed while producing this external record.

## Independent decision

The external result is **PASS with documentation findings:
P0=0, P1=0, P2=0, P3=2**.

The focused V7 suite reported **6 passed, 0 failed**. The correctly bounded V4
through V7 suite reported **31 passed, 0 failed**. The correctly bounded V2
through V7 suite reported **57 passed, 0 failed**.

V7 adds exactly one transactional seam over V6:

- V6 transactional writes: 22;
- V7 transactional writes: 1;
- total installed transactional writes: 23.

No functional, security, integrity, activation, provider, replay, identity, or
rollback finding remains in the default-off V7 handoff scope.

## Known P3 documentation findings

These two low-severity findings are preserved as evidence and corrected by this
external record. The frozen candidate was not edited.

1. **core docstring label:** `OnyxLiveActivationV7` describes itself as a
   façade over the “accepted V6 runtime transition.” The precise label is:
   façade over the frozen, externally accepted **default-off V6 candidate**.
   That wording does not establish prior V6 live-runtime acceptance.
2. **checkpoint/manifest count label:** the checkpoint calls `57 passed` the
   “V4–V7 cumulative” result, and the manifest carries the corresponding
   `combined_v4_v5_v6_v7` label. The independently collected boundaries are
   **V4–V7 = 31 passed** and **V2–V7 = 57 passed**.

These are evidence-description defects only. Neither changes the candidate
code, gate outcomes, closure hashes, or activation boundary.

## Reproduced functional evidence

- The canonical active contract requires all four exact identities:
  `onyx-owner`, `onyx-local-workspace`, `cyryx-local-account`, and
  `onyx-owner-profile`.
- The real-host gate refuses 32 missing, partial, alias, noncanonical, and
  control-value variants before host import.
- Preflight materializes the exact real
  `core.phase5_integration_v3.Phase5IntegrationV3` over the 26-entry main
  catalog without network access.
- The full-host fake-provider E2E uses the actual patched `main.OnyxLive`,
  actual `configure_owner_autonomy`, and full `main.authorize_model_tool`
  broker path.
- A `1011` provider failure reconnects to a second distinct Phase5 READY
  bridge. One five-item `local_catalog_read` completes with zero cost and no
  egress.
- Replaying the same exact provider `call_id` returns the immutable retained
  result without executing a second catalog read.
- The private host reference uses the canonical
  `catalog-p<PID>-n<N>` grammar. Public provider arguments are not coerced.
- Input PCM remains exactly `audio/pcm;rate=16000`.
- V6 call identity, canonical argument binding, bounded 256-record replay,
  single-flight behavior, provider circuit, recovery authority, and Qt
  projection remain frozen.
- The denial diagnostic exposes only bounded state, reason code, and enabled
  state; it does not expose provider arguments, catalog contents, identities,
  or raw broker text.

## Honest execution boundary

The provider gate uses a deterministic local fake provider while executing the
real host, broker, bridge, replay, reconnect, and MIME code paths. It does not
contact Gemini and does not prove current external Gemini availability.

Activation V7 remains **default-off**. The frozen manifest states:

- `default_off=true`;
- `live_activated=false`;
- `live_restart_performed=false`;
- `provider_calls_performed=false`;
- `credential_provisioned=false`;
- `network_calls=0`.

No live activation, restart, credential provisioning, shortcut change, or real
provider/network call occurred during this acceptance. Controlled V7 activation
is a separate operational step with rollback available.

## Controlled activation recipe - recorded, not executed

```powershell
$env:ONYX_LIVE_ACTIVATION_V7='1'
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
& .\.venv\Scripts\pythonw.exe .\scripts\launch_onyx_live_v7.pyw
```

This recipe is recorded only. The acceptance gate did not execute it.

## Exact rollback recipe - recorded, not executed

```powershell
$env:ONYX_LIVE_ROLLBACK_V7='1'
& .\.venv\Scripts\pythonw.exe .\scripts\launch_onyx_live_v7.pyw
```

## Reproduction commands

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v7_host.py
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v7_provider.py
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v7.py
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v7_manifest.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_live_activation_v7.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_live_activation_v4.py tests\test_onyx_live_activation_v5.py tests\test_onyx_live_activation_v6.py tests\test_onyx_live_activation_v7.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_live_activation_v2.py tests\test_onyx_live_activation_v3.py tests\test_onyx_live_activation_v4.py tests\test_onyx_live_activation_v5.py tests\test_onyx_live_activation_v6.py tests\test_onyx_live_activation_v7.py
.\.venv\Scripts\python.exe -I -S -B scripts\verify_onyx_live_activation_v7_acceptance.py
```

The independent verifier must emit
`ONYX_LIVE_ACTIVATION_V7_ACCEPTANCE_OK`.

## Exact acceptance boundary

Accepted:

- the exact 19-file V7 candidate closure and independent computed root;
- the four canonical Phase5 identities and fail-closed pre-import truth table;
- the canonical private invocation reference and unchanged public arguments;
- full real-host broker authorization, one provider-free catalog read,
  reconnect continuity, exact-call replay, MIME, and exact rollback;
- the corrected 6/6, V4–V7 31/31, and V2–V7 57/57 evidence labels.

Not activated or proven by this decision:

- a real Gemini connection or present external provider availability;
- setting V7 activation flags, restarting Onyx, updating shortcuts, or
  replacing the running V6 process;
- completion of Onyx as a whole beyond this Activation V7 handoff.
