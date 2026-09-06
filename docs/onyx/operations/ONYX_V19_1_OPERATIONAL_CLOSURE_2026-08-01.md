# Onyx V19.1 operational closure — 2026-08-01

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V19.1 historical
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Status: **accepted for the observed Windows owner host, with explicit release
and provider limitations**.

This closure does not introduce a V20 runtime and does not alter the V19
engine. It records the bounded operational evidence produced after the V19
source acceptance.

## Machine-verifiable evidence observed in this session

- The Windows x64 build completed and produced a setup executable and portable
  archive. Their sizes and SHA-256 values are recorded in
  `release/release-manifest-Windows-x64.json` and reproduced by the V19.1 gate.
- The setup installation returned `INSTALL_EXIT=0` into the canonical per-user
  path `%LOCALAPPDATA%\Programs\Cyryx Labs\Onyx`.
- Installed `Onyx.exe`, Live Activation V19, the V19 bootstrap/launcher and the
  DayOps connection controller are byte-identical to the built bundle for the
  recorded SHA-256 values.
- Before the normal GUI was started, the installed payload passed package
  smoke, V19 preflight and native startup smoke. The final marker was
  `INSTALLED_V19_VALIDATION_OK v19 cinematic-v5 passed`.
- The native payload reported contract `OnyxNativeStartupSmoke.v1`, activation
  `v19`, profile `current-windows`, `capability_limited=false`,
  `v15_v19_parity=true`, a constructed real UI, bound callbacks and zero
  network, provider and process calls.
- The canonical installed process was subsequently observed responsive with
  title `Onyx — Cyryx Labs - Onyx` and UI state `READY`.

The original installed-smoke stdout was observed during the session but was
not retained as a standalone receipt. Reproducible artifact hashes and the
exact recorded result contract are retained in the V19.1 observation record.

## Owner-observed command response

Computer Use inspected the canonical installed window. After the command
`Responda apenas: ONYX ONLINE.`, the visible history showed the owner command
and `Onyx: ONYX ONLINE.`.

This is classified only as `owner_observed_manual`. No transcript, signed
receipt or database record was persisted, so the command-response observation
is not machine-replayable and is not promoted to independently verified E2E.

## Explicit exclusions and open gates

- No real Microsoft Graph calendar or mail response was observed. Entra public
  client registration, owner device-code consent and a redacted live read
  remain pending.
- This is the owner workstation, not an independently provisioned clean
  machine.
- The setup and installed executable are `NotSigned`; Authenticode remains
  pending.
- macOS/Linux still do not have V15–V19 capability parity.
- The session did not prove microphone, speaker, provider latency or remote-LAN
  behavior on other machines.
- A later concurrent attempt to rerun native startup smoke while the canonical
  GUI already owned the live single-instance resources was stopped after
  contention. It is excluded from pass/fail evidence and does not override the
  earlier installed smoke run performed before GUI startup.

## Post-record gate reproduction

- Dedicated V19.1 acceptance tests: `5 passed`.
- Focused V19 activation, DayOps connection, native-release, package-hygiene
  and V19.1 acceptance selection: `44 passed` using an explicit workspace
  `--basetemp`.
- Scoped Ruff `F,E9` on the new verifier and test: pass.
- Direct verifier marker:
  `ONYX_LIVE_ACTIVATION_V19_C001_ACCEPTANCE_OK`, with two release artifacts
  and the canonical installed payload rehashed successfully.

The first expanded pytest attempt used the Windows global pytest temporary
directory and reported 17 setup errors because that pre-existing directory
denied enumeration. Twenty-seven tests had already passed. Repeating the exact
selection with a fresh bounded workspace `--basetemp` produced the authoritative
44-pass result above; no product assertion was changed to hide the ACL issue.

## Acceptance meaning

E6 accepts only this statement: the recorded Windows V19 bytes were built,
installed into the canonical owner path, passed provider-free installed
startup diagnostics, opened as a responsive application and produced one
owner-observed command response. It does not accept Microsoft connectivity,
clean-machine release readiness, signing or cross-platform parity.
