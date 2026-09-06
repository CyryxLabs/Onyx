# Onyx 1.1.9 V24 Windows acceptance — 2026-08-04

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V24 historical
> evidence. Use `ONYX_1_1_9_V31_WINDOWS_ACCEPTANCE_2026-08-04.md`.

Status: **exact-installed operational candidate; formal/public release remains
blocked by external trust, lifecycle, long-session, legal and review gates**.

## Source and release authority

- Phase 5 current successor V24 SHA-256:
  `69abcde1629a7a62be7021c5085a4c5a40eab2ed4b9c1175f042c7568af71308`;
  root `0ed9beb50037fce2e6694fe5639734539399e38a90cb6ffa6073163e57413b77`.
- Release Workflow V11 SHA-256:
  `4acd3a16ed58084ae606538babaf00d77172031ed3d3d67c10e3fa5064ee1189`;
  root `f25120019fff6ef8f85a253be5ff79add7876d6ec70fa2d65f399176017ddb5e`.
- First-party input seal: 1,310 files; root
  `9611cd1760cb89d601c586d73c6c13ce8ba843630257a50efef1024333ca1159`;
  manifest SHA-256
  `3933ab5b3d4b2826526f2846725aee8a4f2498616fe20c4a7adaf97cc2563fdf`.

## Exact artifacts

| Artifact | SHA-256 |
|---|---|
| Windows Setup | `ba3164a47051008797975f5ba9556aced35cdbfccc6fd598d761f82bb1efbc86` |
| Windows Portable | `a5c3570398961757c383e5da79cd190fcdbcddae5ee50011e3cb809293c1b9aa` |
| Bundle inventory | `68475325291ae6e528846c2b851fdd844120405330bee91c956db99961df039b` |
| Release manifest | `02fd4b7a4b12b2dc3dc0dae0d6b3bd8bedb71b5e38a8d1f00e1fa11488fd6ffd` |
| SPDX SBOM | `72de431fcb1c298d55f32c33ca67756a7dca8be407fb6b1e9d0fd6dbd072b4be` |

The bundle contains 7,278 files and has root
`cb9727cc71e48579e718bb93851586aee94a951bc01baac269d8ccb48cbcd4f2`.
The candidate is intentionally classified `untrusted-candidate` because no
trusted Authenticode identity was supplied.

## Installation and installed gates

The canonical Setup exited 0 and upgraded the current-user installation at
`%LOCALAPPDATA%\Programs\Cyryx Labs\Onyx`. Exact comparison with the release
inventory found 7,278 expected files, 0 missing, 0 mismatched and no extras
other than `unins000.exe` and `unins000.dat`.

The installed executable SHA-256 is
`d0f4c647aad63640643cc8bad79bb2f17d8002978738ece3ea7a15e58ae92982`.
All 9 installed gates passed: package, fallback/V21 preflight, native cinematic
startup, Governance, Founder Snapshot, Document Intake, DayOps disconnected,
Advanced Operations and Advanced Commands.

The installed `core/missions.py` SHA-256 is
`7af0c456d14f3e8a3d6dcb49eca017521b386e5d6f519f9f8057abcab5111327`,
identical to both the V24 source file and the exact installed module exercised
by `ONYX_1_1_9_V21_INSTALLED_MISSION_RECOVERY_ACCEPTANCE_2026-08-03.md`.
That candidate-bound test created, completed, paused, cancelled, reopened and
recovered representative missions, including a deliberate interrupted child
process and audit-chain validation. Because the executable module bytes did
not change, the existing acceptance applies to this V24 package without
inferring behavior from different code.

The current diagnostic scope produced no retained delta. A separate audit then
found 406 legacy disposable diagnostic credentials from older development
runs; only entries explicitly labelled `Disposable package diagnostic
credential` were deleted. The final diagnostic credential count is 0.

## Normal operational launch

Installed PID 62548 is responsive. The V21 startup log records microphone
start/open, playback start, Gemini Native Audio connection and receive start.
No system-voice fallback was introduced; the configured native voice remains
Charon.

The post-install source binding for owner-name updates passed 30 focused tests.
Both text commands and completed microphone transcripts call the deterministic
PT/EN parser before any generic model/tool route. Phrases such as `Onyx,
atualize meu nome para Sir` are normalized to literal `Sir`, persisted only by
the V15 owner-profile authority, and projected immediately to the cinematic
HUD. The tests also prove that the provider owner tool bypasses the generic
permission broker, updates the signed journal/config projection and changes
the visible `ownerName` property. A physical spoken-command confirmation on
the owner's microphone remains an owner-observation gate, not a wiring gap.

Visual inspection of the installed window confirmed:

- title and product identity are Onyx / Cyryx Labs;
- owner projection is the literal `Sir` after a committed forget-name update;
- the cinematic central Orb is present without the removed surrounding arcs;
- particle state changed between frames captured 2.2 seconds apart;
- HUD reports `voice online` and exposes current history, access, command,
  autonomy, remote, camera and advanced-operations controls.

A 20.01-second direct PID sample measured 0.5132% of the 28-logical-processor
host, 389.3 MiB working set, +2.3 MiB change and a responsive window. The HUD's
larger CPU percentage is system-wide load, not Onyx process load.

## Long-session gate

The eight-hour monitor started at `2026-08-04T14:44:59Z` against the exact
installed PID and artifacts. Its atomic receipt is
`docs/onyx/evidence/ONYX_1_1_9_V24_WINDOWS_LONG_SESSION_RECEIPT.json`; samples
are written beside it. This gate remains `IN_PROGRESS` until 28,800 observed
seconds pass with all thresholds satisfied.

## Boundary

This record does not claim trusted Windows signing, clean disposable-host
upgrade/uninstall/rollback, owner acoustic confirmation, live Microsoft Graph
DayOps, native Linux/macOS parity, Apple notarization, legal approval or
independent final review.
