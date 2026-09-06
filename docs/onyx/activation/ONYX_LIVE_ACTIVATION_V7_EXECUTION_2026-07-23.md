# Onyx Live Activation V7 — operational execution

Date: 2026-07-23  
Platform: Windows 11, local owner session  
Decision: **LIVE for the accepted V7 scope**

## Activation result

The accepted V7 launcher was started with the complete frozen host identity:

- workspace: `onyx-local-workspace`;
- account: `cyryx-local-account`;
- profile: `onyx-owner-profile`;
- principal: `onyx-owner`.

The physical window exposed exactly one `Onyx — Cyryx Labs` surface. Its
accessibility root was
`QApplication.MainWindow.OnyxCinematicSurfaceV5`; the legacy launcher and
legacy HUD were not present. Voice input, receive and playback loops started.

## Real functional probe

The command `Call local_catalog_read with no arguments. Then say exactly
SUCCESS or FAILURE.` was submitted through the physical HUD. The provider
called `local_catalog_read`, the HUD returned `SUCCESS`, and the audit store
recorded:

- allow event `48446`, reason `phase5-exact-local-read`;
- completed dispatch event `48447`;
- canonical content-free trace `catalog-p94136-n1`;
- no public argument fields and no error type.

This closes the V6 runtime failure caused by the legacy hex invocation
reference. It does not expand the accepted read-only catalog authority.

## Official shortcut correction

Both user-facing shortcuts still referenced the legacy
`scripts/launch_onyx.pyw` entrypoint. Exact copies were retained under:

`runtime/audit/onyx-shortcuts-v7/20260723T063609Z`

The shortcuts at `C:\Users\ppetr\Desktop\Onyx.lnk` and
`C:\Users\ppetr\OneDrive\Desktop\Onyx.lnk` now launch the accepted
`scripts/launch_onyx_live_v7_active.cmd` wrapper. A controlled close and a
restart through the Desktop shortcut produced exactly one V7 window and PID
`91116` listening on ports 8000 and 8001.

## Resource and reachability probe after shortcut restart

Ten-second host-normalized sample:

- CPU: `0.173%`;
- working set: `302.1 MiB`;
- private memory: `1048.1 MiB`;
- threads: `92`.

HTTP status was `200` for all four probes:

- `https://127.0.0.1:8000`;
- `https://127.0.0.1:8001`;
- `https://192.168.1.236:8000`;
- `https://192.168.1.236:8001`.

## Boundaries

This execution establishes the accepted V7 voice/HUD/dashboard/Phase 5
read-only scope on this Windows host. It does not by itself establish Phase 6
live wiring, external-agent access, third-party account authentication,
cross-platform installer completion or full Onyx project completion.
