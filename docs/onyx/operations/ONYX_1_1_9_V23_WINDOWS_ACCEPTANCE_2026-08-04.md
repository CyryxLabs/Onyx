# Onyx 1.1.9 V23 Windows acceptance — 2026-08-04

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** This document preserves exact V23
> acceptance evidence only. V23 is not the current release candidate; use
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md) and the current
> evidence index before making any operational or release claim.

Status: **exact-installed operational candidate; formal/public release remains
untrusted until external trust gates close**.

## Source authority

- Phase 5 current successor: V23; SHA-256
  `0f3301d1d2d3ec425a7f3439feac6a160ccec0cae3dacc3f8d1bd4173e2a870f`.
- Release Workflow: V10; SHA-256
  `1a853081a3c1aad40554e18016fbc9f9601fcbfdb139acb69179d5cb1d365102`.
- Advanced Operations evidence root:
  `c86edde8f76a35d7ac23c8586c0769152af45aa1f7413a5bacbde254e3355dff`.
- Reference comparison: `petruff/jarvis_MAAX.git` commit
  `564c97b2cf8ad29983b3ad40411441dbc9e22af3`, clean-room behavioral method;
  no reference source, branding or license was copied.

## Build artifacts

| Artifact | SHA-256 |
|---|---|
| Setup | `9576b92a637d2959f501c9cda4858c5000415aafe9ba60e718b222bdfc4461bd` |
| Portable | `f93a4a8d29dc0c626329b3978a7f72fbbf6c5d7eccc6d1ea0ff1e95100651721` |
| Bundle inventory | `c765caefb0309d7db4652396d4846c4650004d01315e572fb8e8bdcec100d4af` |
| First-party input manifest | `bc319ab05fce8d5e06d97b92741a5e2fb351c11a2a808a3ce6c2f4fcc85a2c8c` |

- First-party input root:
  `266302e6e08b9175c00ab75ee8e356aa730158e014150b315dec3a2214eee6b7`
  across 1,310 inputs.
- Bundle root:
  `bcad5b75e19317f519ed8599e9e5c61c4bb9f83a1e06b510d26ea0b2ec902771`
  across 7,278 files.
- Release class: `untrusted-candidate`; Authenticode trust is not claimed.

## Exact installation

The canonical Setup exited 0 at
`%LOCALAPPDATA%\Programs\Cyryx Labs\Onyx`. Comparison against the final bundle
inventory recorded:

- expected: 7,278;
- missing: 0;
- mismatched: 0;
- non-uninstaller extras: 0;
- installed `Onyx.exe` SHA-256:
  `e71f90f7dd93db6b1e639c9394d6b11cb6476533978ca06a2716e21b72d94bb3`.

## Installed executable gates

The installed directory passed 9/9 gates:

1. package smoke;
2. fallback and V21 preflight;
3. native V21 startup with real cinematic renderer;
4. Governance V16;
5. Founder Snapshot V17;
6. Document Intake V18.1;
7. DayOps V20 disconnected/read-only;
8. Advanced Operations V20;
9. Advanced Commands V21.

The gates created six disposable diagnostic credential references; the exact
delta was deleted in the mandatory `finally` boundary. Final credential delta:
0. Required interception contracts recorded zero network, provider,
child-process and trusted-approval calls.

## Normal operational launch

Installed PID 29800 remained responsive. The current startup log records:

- `Mic started` and `Mic stream open`;
- `Play started`;
- `Connecting Gemini Native Audio provider`;
- `Recv started`.

The same live session created private, session-scoped
`workflow-graphs-v1.sqlite3` and `context-graph-v1.sqlite3` stores alongside
the existing governed automation, goals, sites, device mesh and Phase 6 state.
No second voice provider or system-voice fallback was introduced.

A 20.03-second idle sample on 28 logical processors measured 0.4208%
whole-host CPU. Working set was 398.5 MiB and changed by -0.3 MiB during the
sample.

## Validation summary

- focused clean-room/integration selection: 96 passed;
- current transition/source selection: 59 passed;
- broader activation/release selection: 424 passed, 1 platform skip; its three
  reported failures were resolved as one isolated Qt cross-test residue and a
  stale V15 identity anchor. The isolated Qt test passed and the V15 V2 anchor
  then passed in the 17-test correction selection;
- workflow/context append-only selection: 13 passed;
- Ruff changed-file checks: passed.

## Remaining boundary

This record does not claim trusted publisher signing, clean-disposable-host
lifecycle acceptance, owner acoustic/name-persistence acceptance, live
Microsoft Graph DayOps, native macOS/Linux release parity, Apple notarization,
legal approval, independent review or an eight-hour V23 soak. Those are
external or long-duration gates, not missing local wiring.
