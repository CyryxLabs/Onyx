# Onyx Live Activation V19 C001 — E6 acceptance

> Historical acceptance record for Onyx 1.0.0. The immutable release inputs are
> retained under `rollback/releases/onyx-1.0.0-v19.1`; current-release status is
> tracked by the project completion roadmap and later release evidence.

- Evidence ID: `VE-ONYX-LIVE-ACTIVATION-V19-C001-E6-001`
- Decision date: `2026-08-01`
- Decision: **ACCEPTED — bounded Windows installed-host operational closure**
- Findings within accepted scope: **P0=0, P1=0, P2=0**
- Open release/provider gates: **P3=4**

This decision accepts the V19.1 operational observation only. The existing V19
runtime remains unchanged.

## Accepted evidence

1. Windows x64 setup and portable artifacts exist and reproduce the release
   manifest sizes and SHA-256 values.
2. Canonical per-user installation completed with exit `0`.
3. Five security-relevant installed payload files are byte-identical to the
   built bundle, including `Onyx.exe`, Live Activation V19, its bootstrap and
   launcher, and the DayOps controller.
4. Installed package smoke, V19 preflight and provider-free native startup
   smoke passed before normal GUI startup. Native startup reported the exact
   V19/current-Windows activation contract, real UI and callbacks with zero
   network/provider/process calls.
5. The canonical installed process was observed responsive in `READY` state.
6. One command and exact `ONYX ONLINE.` response were observed visually. This
   item is manual owner evidence only and has no durable receipt.

## Non-accepted claims

The following remain explicitly unverified and must not inherit this E6:

- real Microsoft Graph calendar/mail operation;
- clean-machine installation or release readiness;
- Authenticode signing;
- native macOS/Linux V15–V19 parity.

The setup and installed executable were observed `NotSigned`. No real
Microsoft token, device code, message body or calendar content is included in
this evidence.

## Integrity and reproduction

The machine observation is recorded in
`docs/onyx/checkpoints/onyx-live-activation-v19-c001/installed-host-observation.json`.
The acceptance verifier rehashes the release artifacts, checks their exact
activation manifest, verifies the recorded installed payload when the
canonical path is available, and enforces the manual-only classification of
the command response plus all four pending gates.

This E6 is not a declaration that Onyx is complete or ready for public release.
