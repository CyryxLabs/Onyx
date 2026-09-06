# Onyx V17 Founder Snapshot - Windows release acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V17 historical
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Date: 2026-07-31

Status: accepted for the installed Windows owner host, with the limitations
listed below. This record does not claim macOS/Linux, code signing, live Gemini,
microphone/audio, external connectors, or clean-machine acceptance.

## Delivered runtime

- The stable `Onyx.exe` chain activates V17 over the accepted V16 Governance
  base and exposes Founder Brief as a read-only capability.
- Founder daily and weekly briefs are generated from approved, cited local
  evidence. Revenue, customers, traction, runway, decisions, risks and actions
  are left empty when no supporting evidence exists.
- The smoke corpus is published through `ArtifactService`, indexed in the
  control plane and exposed only through the stable
  `founder-smoke-corpus-v17` artifact alias plus its SHA-256. After controller
  restart, the alias is resolved again, the artifact bytes are reopened and
  their digest is compared with the original corpus before acceptance.
- Founder history survives a controller close/reopen and produces a non-baseline
  daily delta after restart.
- Control-plane SID and protected-DACL operations use Win32 APIs directly. The
  managed descriptor accepts only protected control `P`, exact `FA` rights,
  `OI+CI` flags for directories, no flags for files, and canonical SYSTEM then
  owner ACEs. The complete original owner/DACL descriptor is captured before
  mutation and restored exactly after every injected apply/readback/verify
  failure; rollback failure is a distinct fail-closed error. The runtime no
  longer needs `whoami.exe` or `icacls.exe` for these operations.
- A persisted Founder receipt vault is accepted as authenticated state on
  restart instead of being incorrectly required to remain a raw 32-byte key.
- `--founder-smoke-test` is routed through the stable bootstrap and is part of
  the official package build gate.

## Source and regression evidence

- Founder/V17 source gate: `46 passed`.
- Governance V16, control plane, workspace audit and package hygiene gate:
  `77 passed, 2 skipped, 105 subtests passed`.
- Changed-file Ruff gate: passed.
- Changed-file `compileall` gate: passed.
- Direct source Founder smoke: passed with daily, weekly and restart outputs;
  grant reuse and all commit/cancel/kill fences were true; trusted UI prompts,
  network calls, provider calls and child-process calls were all zero.

## Frozen package and installed-host evidence

The official `scripts/build_release.py` run completed successfully after its
package smoke, fallback preflight, V17 preflight, Governance V16 smoke and
Founder Snapshot V17 smoke.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `Onyx-1.0.0-Windows-x64-Setup.exe` | 474204500 | `fb1b8cbee16c0a02929ba1cfa3cf5e78e891dd57b0c71a6d816fcba0fe22a617` |
| `Onyx-1.0.0-Windows-x64-Portable.zip` | 540559977 | `4864ea712cce6202ccd2cdb525cb7eb66974a1cd6828e3cf8b5d6aa2a9b8c390` |

The setup was installed silently to the canonical per-user Cyryx Labs path and
returned exit code 0. SHA-256 parity was confirmed across source, staged runtime,
frozen bundle and installed files for `core/control_plane.py`,
`core/onyx_live_activation_v17.py`, `scripts/bootstrap_onyx_live_v17.pyw` and
`scripts/launch_onyx_live_v17.pyw`.

Installed-host results:

- V17 preflight: exit 0.
- Governance smoke: exit 0, status passed, zero network/provider/UI prompts.
- Founder smoke: exit 0, status passed, daily and weekly completed, restart
  delta `baseline=false` and `has_previous=true`; the persisted alias was
  resolved and its redacted alias+digest citation reopened after restart; zero
  network/provider/process/UI prompts.
- Normal launch against the existing production data root stayed alive.
- A second normal launch exited 0 in 3.9 seconds through the single-instance
  boundary.
- The V17 startup log recorded Founder Brief `available_read_only`, Governance
  `available` and Away `available`, with no traceback or
  `cleanup_root_handle_busy` occurrence.
- Test processes were closed and a final check found zero residual `Onyx`
  processes.

## Honest remaining release limitations

- The Windows setup and installed executable are not digitally signed.
- macOS and Linux packages were not built or tested in this Windows run.
- The Founder smoke uses a real local, content-addressed source artifact. Its
  public evidence reference is the redacted stable alias+digest URI, not a
  filesystem path, workspace identifier or placeholder web domain. This proves
  local source/claim/citation/reopen contracts, not access to external business
  systems.
- Live Gemini, microphone, speakers and conversational quality were not tested
  by this provider-free release gate.
- External coding-agent capability remains health-only while an authenticated
  execution-account receipt is unavailable.
