# Onyx V13 live promotion — 2026-07-23

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** This is immutable V13 observation
> evidence, not proof of the current installed runtime. See
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Status: **live, physically observed, Phase 6 Wiring V2 composed**

## Promotion

- predecessor process: Onyx Live V12;
- successor bootstrap:
  `C:\MAAX_Assistant\Onyx\scripts\bootstrap_onyx.pyw`;
- live parent PID at observation: `47820`;
- live child PID at observation: `48564`;
- window title: `Onyx — Cyryx Labs`;
- window responding: `true`;
- both physical desktop shortcuts were normalized to the V13 bootstrap.

PIDs are observation evidence only and are not persistent identity.

## Voice and provider evidence

`runtime/logs/onyx-live-v13-startup.log` recorded, without traceback or
failure:

- Gemini voice-provider connection started;
- microphone worker started;
- microphone stream opened;
- receive worker started;
- audio playback worker started;
- a real provider response arrived;
- Gemini requested `save_memory`;
- approved memory `identity/language` was saved.

This proves the unchanged real voice/Gemini path was operational at the
observation time. It does not establish permanent provider availability.

## Phase 6 session evidence

The V13 activation installed the frozen Phase 6 Live Wiring V2 candidate over
the already installed Wiring V1 before `main.main()` created the live host.
The live provider connection created a new session directory at:

`runtime/phase6-live-wiring-v1/sessions/session-8565fbaf56e4c6ecd02af3a6b0417ce2`

at `2026-07-23T14:49:26-04:00`, containing:

- `agentic-state-v6.sqlite3`;
- `agentic-state-v6.v6-coordination.sqlite3`;
- `live-integration-v2.sqlite3`;
- `live-integration-v2.v1-base.sqlite3`.

The V13 real-host test separately proves that the same lifecycle creates the
session-bound Provider Registry V1, Research Verifier Pipeline V1, Local MCP
identity, Unified Router V1, and disabled External-Agent catalog. Those
metadata-only components intentionally create no additional process or file.

## Visual and resource evidence

- renderer: HUD V9 arc-free successor;
- decorative command arcs: absent in
  `runtime/logs/onyx-v13-live.png`;
- Orb and voice particle layer: preserved;
- normalized CPU over four seconds: `0.3767%`;
- working set: `364.7 MiB`;
- private allocation: `1068.5 MiB`;
- live threads: `98`;
- window responding: `true`.

The CPU result is low and consistent with the earlier V11/V12 observations.
The approximately 1.0 GiB private allocation remains a future memory
optimization target and is not represented as resolved.

## Dashboard and LAN evidence

The V13 child owned both listeners on `0.0.0.0`.

| URL | Result | Response bytes |
|---|---:|---:|
| `https://127.0.0.1:8000` | 200 | 34053 |
| `https://127.0.0.1:8001` | 200 | 34053 |
| `https://192.168.1.236:8000` | 200 | 34053 |
| `https://192.168.1.236:8001` | 200 | 34053 |

This proves same-host and same-LAN-address reachability from the computer. A
phone result still depends on Wi-Fi client isolation, routing, certificate
acceptance, and the device browser.

## Verification

- Phase 6 Wiring V2: `15 passed`;
- V13 activation: `6 passed`;
- V12 regression: `6 passed`;
- V11 regression: `18 passed`;
- Wiring V2 predecessor regression matrix: `155 passed`;
- candidate marker: `P6_LIVE_WIRING_V2_CANDIDATE_OK`;
- V13 canonical preflight:
  `ONYX_LIVE_V13_HOST_PREFLIGHT_OK`.

Historical acceptance verifiers that assert Wiring V1 never entered a launcher
or that the repository contains exactly 204 live files are now transition
stale. Their frozen evidence bytes were not edited. Current successor gates
must verify exact hashes and current composition rather than reuse those
obsolete negative/file-count assumptions.

## Limits retained

- Unified Router V1 remains local-private-only and does not route the remote
  Gemini provider.
- Gemini remains operational through the preserved host path.
- Local MCP is metadata/call-intent only in Wiring V2; no MCP process is
  opened by the live composition.
- The External-Agent descriptor remains `BLOCKED_BY_ACCESS`.
- This promotion is not Phase 6 exit and is not completion of the full Onyx
  PRD.
