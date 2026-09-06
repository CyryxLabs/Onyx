# Onyx Live Activation V6 External E6 Acceptance

- Evidence ID: `VE-ONYX-LIVE-ACTIVATION-V6-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED - Onyx Live Activation V6 frozen default-off handoff only**
- Candidate: `onyx-live-activation-v6`

## Frozen candidate anchors

This decision accepts only the exact default-off candidate represented by these
immutable anchors. It does not activate Onyx, restart a process, provision a
credential, change a shortcut, or call a real provider.

| Anchor | SHA-256 |
|---|---|
| Candidate manifest | `4b7b3bcdb7c87043e97baa952b883dcfc9f498026c272099f5222de7decb4453` |
| Independent 34-binding root | `e935133d2f08273088450c14e801b7b07d0e25503e2855cd9b324c7dc9f4839b` |
| Candidate checkpoint | `51cb9fd819b89f5e70eed4f7275c05a8a4b6a9557ae7985ea12982a5a7780495` |
| V6 core | `68d75e89728355b6b26b153f19ec5d732f26369b79d7e03e700bc8b00ee95f54` |
| V6 launcher | `de6aff494b5c9c22dc93e209c50cfa5710a6d7012b217d263c22bca3076eeb0f` |
| Candidate tests | `0eed5cad48d30d38523e50b0ce6081762175d84b29e0e062ad2400b26a1bd565` |
| External acceptance verifier | `31197fbfe39adac19b426eeb47923ebdb2b64cdb124d00f0a219b4f54f3e6df9` |
| External acceptance tests | `eecadb3265966780a7822d15db688019fd7086b16472b87d68dc1a87d9b196fb` |

The candidate manifest is the authoritative frozen file list. The external
verifier rereads and rehashes its complete **34/34** regular-file closure. The
independent root is recomputed deterministically as:

1. sort all manifest bindings by canonical `path`;
2. encode each as `path + NUL + sha256 + LF`;
3. concatenate the 34 encoded bindings;
4. compute SHA-256 over those UTF-8 bytes.

That algorithm yields the independent root
`e935133d2f08273088450c14e801b7b07d0e25503e2855cd9b324c7dc9f4839b`.
No V1-V6 candidate byte changed while producing this external record.

## Independent decision

The external result is **PASS: P0=0, P1=0, P2=0, P3=0**.

The independent historical gate reported **224 passed, 0 failed**. The focused
V6 candidate suite reported **6 passed, 0 failed**, and the combined V4 + V5 +
V6 activation suite reported **35 passed, 0 failed**.

No finding remains in the default-off handoff scope:

- exact `call_id` plus first-observed name/canonical-argument digest is bound;
- concurrent duplicates are single-flight with digest-verified immutable
  result snapshots or frozen error descriptors;
- the replay window remains bounded to 256 records, never evicts inflight
  calls, and refuses a 257th all-inflight call;
- numeric configuration rejects booleans, non-finite, non-positive, overflow,
  and above-maximum values;
- every circuit transition is serialized on one owning event loop;
- UI recovery submits a command and waits for the loop acknowledgement;
- the accepted PCM contract remains `audio/pcm;rate=16000`;
- setup remains a single visible surface.

## Reproduced evidence

- Fresh-process real-host preflight:
  `ONYX_LIVE_V6_HOST_PREFLIGHT_OK`.
- Host adversarial gate: 22/22 failpoints, exact rollback, 1,000 IDs, bounded
  256-record window, 744 evictions, 257th all-inflight refusal, name/argument
  conflicts refused without execution, concurrent success/error single-flight,
  numeric edge rejection, cross-thread recovery acknowledgement, and wrong-loop
  transition refusal.
- Provider resilience gate: local fake provider emitted `1007`, then `1011`,
  recovered automatically on attempt 3, and sustained 601 accelerated seconds
  while HUD, process, dashboard, and listeners remained alive.
- Real PyQt process with an **offscreen** scene backend: one setup surface,
  repeated requests idempotent, renderer suspended and resumed.
- Candidate cumulative verifier, manifest verifier, Ruff, and Python
  compilation: pass.

## Honest execution boundary

The provider evidence is a deterministic local **fake provider** gate. It did
not contact Gemini and does not prove current external Gemini availability.
The Qt evidence uses the real Qt implementation but an **offscreen** renderer;
it does not prove a physical display/GPU presentation path.

Activation V6 remains **default-off**. The frozen manifest states:

- `default_off=true`;
- `live_activated=false`;
- `live_restart_performed=false`;
- `provider_calls_performed=false`;
- `credential_provisioned=false`.

No live activation, restart, credential provisioning, shortcut change, or real
provider/network call occurred during this acceptance. The real live activation is the next gate.
It will be performed separately with controlled observation and the frozen
rollback switch available.

## Controlled activation recipe - recorded, not executed

The complete canonical activation environment is:

```powershell
$env:ONYX_LIVE_ACTIVATION_V6='1'
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
& .\.venv\Scripts\pythonw.exe .\scripts\launch_onyx_live_v6.pyw
```

This recipe is recorded only. The acceptance gate did not execute it.

## Exact rollback recipe - recorded, not executed

```powershell
$env:ONYX_LIVE_ROLLBACK_V6='1'
& .\.venv\Scripts\pythonw.exe .\scripts\launch_onyx_live_v6.pyw
```

The rollback launcher clears the V6 control flags in its child process and
delegates to the frozen legacy launcher. This acceptance did not execute
rollback or restart the live legacy process.

## Reproduction commands

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v6_host.py
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v6_provider.py
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v6_qt.py
.\.venv\Scripts\python.exe -B scripts\verify_onyx_live_activation_v6.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_live_activation_v6.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_live_activation_v6_acceptance.py
.\.venv\Scripts\python.exe -I -S -B scripts\verify_onyx_live_activation_v6_acceptance.py
```

The independent verifier must emit
`ONYX_LIVE_ACTIVATION_V6_ACCEPTANCE_OK`.

## Exact acceptance boundary

Accepted:

- the exact 34-file V6 candidate closure and independent computed root;
- the default-off launch and rollback definitions;
- exact-ID replay safety, bounded retention, loop-owned circuit authority,
  MIME/provider resilience, and the single setup projection;
- the reproduced host, fake-provider, offscreen Qt, preflight, focused,
  combined, and historical evidence stated above.

Not activated or proven by this decision:

- a real Gemini connection or present provider availability;
- a visible physical display/GPU presentation path;
- setting activation flags, restarting Onyx, or replacing the live legacy
  process;
- completion of Onyx as a whole beyond this Activation V6 handoff.
