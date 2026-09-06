# Onyx 1.1.9 V19 Windows acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V19 historical
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Status: **LOCAL INSTALLED CANDIDATE — LONG SESSION IN PROGRESS**  
Platform: Windows x64  
Activation: V21 over frozen Phase 5 successor V19  
Acceptance date: 2026-08-04

This record supersedes V18 for current Windows claims. V18 remains immutable
failure evidence: its first Gemini Live rotation ended in Windows exception
`0xc0000409` in `ucrtbase.dll` after 60.305 seconds.

## Frozen identities

| Identity | Value |
|---|---|
| Phase 5 V19 transition SHA-256 | `8c1332c1e33ccfc392abddec4c7863b0bffb9290428c02d77e2c42bbbec87782` |
| Phase 5 V19 root | `c0dc1de139e86a46a046aac5799edd6e990b3ce033d3fa9e75094574a18c1b38` |
| Release Workflow V5 SHA-256 | `cf271a0669cdc5379589c10285107c83098a573c4e2598442f21ea2d2122c998` |
| Advanced Operations V17 manifest SHA-256 | `0d3648cf024a9878067d5c92a02806cc12a344b42533f773821e4ea7a23cea9e` |
| Advanced Operations V17 source root | `cfd9150d6547bc91f307fef9cf65e5e6d678c631e096f454465c064826670c3b` |

## Clean build and artifacts

The clean release build exited 0 and passed every packaged gate. It produced:

| Artifact | Evidence |
|---|---|
| Setup | 484,928,227 bytes; SHA-256 `5b43c377209dfae92ce9177f9da3b1c46bc875bec344e8183930421c73d1eb73` |
| Portable | 550,573,061 bytes; SHA-256 `6e355bccda2a64ca7c2ccfb1e1881c269b6585f551f6ecc59ac8d224d293763b` |
| Release manifest | SHA-256 `cab810c1380a7a996ada2b09675f478a5a631a8db1a15d85615b8cf8ffb43d97` |
| Bundle inventory | 7,288 files; SHA-256 `9b14a267d6caed340005b3321a5b7e6428a31d4e01d9759d99c968deb839a60f`; root `46bb6a8df8fce06bf31bdcde3b932c92462fde946309b20340b15469879dd15b` |
| First-party input seal | 1,305 files; manifest SHA-256 `1dc340a4c62bad9889345593c630c241ba7c43e889d6b2207f0a6bb2e5aa180e`; root `2971ff9aa695c2f146bc2c5a87b0f86d0b5e34c43f9edc9604eb3d37b4070937` |
| Distribution inventory | 95 distributions; root `6524a84b48a81bb1eb138b815d995041854066ac8461c327f8fb09dc3982ec7e` |
| HUD artifact root | `aa744179ab47421c58311ec859b47638a985158cb71df4953b47843f93ba2673` |
| SPDX SBOM | SHA-256 `c905de094eed10041923ba8b89b0a7490ebfe260a57847d815fba466c372dab7` |

The manifest remains `untrusted-candidate` because no trusted Cyryx Labs
Authenticode certificate or timestamp authority was supplied.

## Canonical installation

The Setup installer exited 0 at
`%LOCALAPPDATA%\Programs\Cyryx Labs\Onyx`. Exact comparison against the
bundle inventory recorded:

- expected: 7,288;
- missing: 0;
- mismatched: 0;
- non-uninstaller extras: 0;
- installed `Onyx.exe` SHA-256:
  `b84d92d70602bb79af1c68e0a88ad3581e338f9894aaaa316a9efce52b6b51cd`.

## Installed executable gates

The canonical installed directory passed 9/9 gates:

1. package smoke;
2. fallback and V21 preflight;
3. native V21 startup with the real cinematic V5 renderer;
4. Governance V16;
5. Founder Snapshot V17;
6. Document Intake V18.1;
7. DayOps V20 disconnected/read-only;
8. Advanced Operations V20;
9. Advanced Commands V21.

The isolated gates recorded zero network, provider, child-process and trusted
UI approval calls where their contracts require those fences.

## Real Gemini Native Audio rotation

The installed normal process started as PID 64880 and remained responsive.
Its V21 startup log records:

- microphone start/open: 1;
- playback start: 1;
- Gemini receive sessions: 2;
- real provider `GoAway`: observed with `time_left=50s`;
- reconnect: `Gemini Live session rotated normally`;
- Windows Application Error events for this session at the gate: 0.

This proves the V19 ownership correction in installed bytes: microphone and
playback belong to the process lifetime and are not torn down/reopened when the
Gemini transport rotates. The provider remains
`gemini-2.5-flash-native-audio-preview-12-2025` with voice `Charon`; no system
voice fallback is allowed.

## Formal long session

The 28,800-second attempt 1 is currently running without closing Onyx:

- Onyx PID: 64880;
- monitor PID at launch: 62124;
- receipt:
  `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v19-soak-attempt1-receipt.json`;
- samples:
  `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v19-soak-attempt1-samples.csv`;
- required duration: 28,800 seconds;
- maximum average whole-host CPU: 1.5%;
- maximum working set: 786,432,000 bytes;
- maximum private memory: 1,610,612,736 bytes;
- maximum working-set growth: 268,435,456 bytes;
- required responsiveness: every sample;
- permitted Application Errors: 0.

`scripts/monitor_windows_long_session.py` writes the receipt atomically at
startup, every sample and terminal disposition. `IN_PROGRESS` is not a pass.

## Remaining boundary

This record does not establish trusted signing, clean-disposable-host lifecycle,
owner acoustic/name-persistence acceptance, live Microsoft Graph DayOps, native
macOS/Linux packages, Apple notarization, legal approval, independent review or
formal completion. Those gates remain authoritative in
`../CURRENT_RELEASE_STATUS.md`.
