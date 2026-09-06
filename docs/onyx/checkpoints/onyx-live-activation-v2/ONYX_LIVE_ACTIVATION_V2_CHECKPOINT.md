# Onyx Live Activation V2 transition checkpoint

Date: 2026-07-22

Status: implementation candidate, default-off and not live. No feature flag,
credential, shortcut or provider was changed; no Onyx process was restarted.

## Rejected V1 preservation

Activation V1 is rejected because it targeted nonexistent `main.Assistant`
instead of the actual `main.OnyxLive` class and admitted ambiguous truthy flag
spellings. Its six files are frozen byte-for-byte and V2 neither imports nor
subclasses them. The separate V1 rejection record binds the reason and hashes.

## Canonical pre-import launcher

`scripts/launch_onyx_live_v2.pyw` evaluates the complete truth table using only
the standard library before importing `main`, `ui` or any activation module.
Every present control value must be exactly `1`; `true`, mixed case, whitespace,
`yes`, zero and partial sets refuse with the clean pre-import marker.

Valid states are: no controls for exact legacy delegation; exact master plus all
ten children for activation; or exact rollback alone / added to the complete
active set. Rollback removes every control in the new process before delegating
to the frozen historical launcher.

## Real-host preflight and transactional install

Preflight imports and verifies the real `main.OnyxLive`, its five required
methods, the main prompt/tool/authorization seams, `ui.MainWindow`, setup methods
and the HUD V5 identity projection. It performs no provisioning.

Nine host seams are installed as one reversible transaction. Any setter failure
restores every preceding function and the original declaration-list object.
Owner Profile V8 provisioning runs only after preflight and a complete install.
Fresh-process evidence uses actual `main.OnyxLive`; no `Assistant` test double is
present.

## Session continuity and owner projection

The host shim reserves non-secret monotonic IDs before each Integration V3
creation: `session-p<PID>-n<N>` and `trace-p<PID>-n<N>`. The real-host gate
completed 64 create/catalog-read/reconnect cycles with 128 unique IDs, plus kill,
revoke and shutdown termination.

Every successful V8 set, correction and forget immediately updates the live HUD
projection and any open setup-name input. Forget projects literal `Sir`. Projection
failure rolls all already-touched UI targets back to their snapshots and latches
the controller `DEGRADED`; owner-operation failure touches no UI.

## Results and reproduction

- V2 focused suite: 13 passed, 0 failed in 16.17 seconds.
- Combined accepted Owner V8, Integration V3, HUD V5 and V2 transition matrix:
  59 passed, 0 failed in 29.86 seconds.
- Fresh-process actual-host cycle: 64 reconnects, 64 provider-free catalog reads,
  128 unique session/trace IDs.
- Ruff and Python compilation: pass.
- Expected environmental warning: the shared `.pytest_cache` is inaccessible;
  explicit `--basetemp` succeeds.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_live_activation_v2.py --basetemp .pytest-onyx-live-activation-v2
.\.venv\Scripts\python.exe -m ruff check core\onyx_live_activation_v2.py scripts\launch_onyx_live_v2.pyw scripts\verify_onyx_live_activation_v2.py scripts\verify_onyx_live_activation_v2_host.py tests\test_onyx_live_activation_v2.py
.\.venv\Scripts\python.exe -m py_compile core\onyx_live_activation_v2.py scripts\launch_onyx_live_v2.pyw scripts\verify_onyx_live_activation_v2.py scripts\verify_onyx_live_activation_v2_host.py tests\test_onyx_live_activation_v2.py
.\.venv\Scripts\python.exe -I -S -B scripts\verify_onyx_live_activation_v2.py
```

Independent functional, integrity and quality gates remain mandatory before a
controlled activation/restart decision.
