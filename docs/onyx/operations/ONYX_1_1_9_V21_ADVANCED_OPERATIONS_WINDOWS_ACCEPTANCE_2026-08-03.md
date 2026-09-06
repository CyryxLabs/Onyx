# Onyx 1.1.9 V21 Advanced Operations Windows installed acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V21 historical
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Status: **pre-V14 installed predecessor passed bounded gates; superseded as current source candidate**  
Date: 2026-08-03  
Platform: Windows x64

## Exact candidate

- Setup: `Onyx-1.1.9-Windows-x64-Setup.exe`
  - bytes: `484763157`
  - SHA-256: `7f7e63f02c104725f0417776b0ef285e7498b2afb038c666ecb0d0642170a0e1`
- Portable: `Onyx-1.1.9-Windows-x64-Portable.zip`
  - bytes: `551616436`
  - SHA-256: `1b965168b1579a7e3eef04bb5a7f581a62ad064b76f56514ccecab8dce2d31b6`
- Build-input seal: 1,293 files, root SHA-256
  `c35c09cadb3d110b23939571a2d255f75b29023019653e417e56bea0d6f82636`.
- Bundle inventory: 6,782 files, root SHA-256
  `aba0d40b131e2e8ffe014d4012318c5809a7dd98c9af5cebfaa025432ba4313a`.
- HUD V19 artifact root:
  `aa744179ab47421c58311ec859b47638a985158cb71df4953b47843f93ba2673`.
- Advanced Operations source evidence: 28-file root
  `f699cebdc080dbec828d35a1facce10e008d6e3d008ed4a00e960904c3a9a6cc`.
- Release class: `untrusted-candidate`; Authenticode and independent final
  review are not complete.

## Installed and runtime result

- Full release build exited 0 after packaged fallback/V21 preflights, native
  startup, Governance, Founder, document intake, DayOps, Advanced Operations,
  Advanced Commands, package hygiene and isolated lifecycle gates passed.
- Canonical silent Setup upgrade exited 0. The installer log is outside the
  source tree at `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v21-advanced-ops-install.log`.
- Installed inventory: 6,782 expected, 0 missing, 0 mismatched and 0
  unexpected application files. The two extra files are the canonical
  uninstaller pair.
- Installed Advanced Operations smoke: exit 0.
- Installed Advanced Commands smoke: exit 0.
- Installed native startup smoke, invoked with the exact output/workspace V21
  evidence contract: exit 0; real UI and callbacks constructed; zero network,
  provider and process calls in the intercepted diagnostic.
- Normal installed startup opened PID 56600 with title
  `Onyx — Cyryx Labs - Onyx`, remained responsive and connected Gemini Native
  Audio with microphone, receive and playback channels active.
- A 30-second settled sample observed 0.4594% average whole-host CPU, working
  set 431,972,352 bytes, private memory decreasing by 5,013,504 bytes and zero
  Windows Application Error events.
- Gemini `GoAway(time_left=50s)` events were handled by the existing normal
  session-rotation path with retained context; they did not activate a system
  voice or alternate TTS fallback.
- The installed mission module separately passed create/run/audit/reopen,
  pause/cancel and crash-to-waiting recovery with explicit retry. See
  `ONYX_1_1_9_V21_INSTALLED_MISSION_RECOVERY_ACCEPTANCE_2026-08-03.md`.

## Post-acceptance lifecycle finding

The installed predecessor later produced a `Qt6Core.dll` fatal application
exit during window teardown. WinDbg traced the failure through
`QQmlData::destroyed`, `QObject::~QObject` and `QQuickWidget::event` while the
PySide close callback forced QML deferred deletion. Source successor V14 fixes
that reentrant teardown and passes native close stress, but it is not part of
the artifact hashes in this document. This record therefore remains
predecessor evidence only.

## Capability result

- The cinematic arc-free HUD includes an owner-invoked, zero-polling Advanced
  Operations projection.
- Goal, automation-rule and controlled-root site lifecycle commands are live
  over the existing Phase 6/MissionStore authority.
- Style-preference suggestions remain evidence-scored; only owner-authorized
  promotions enter the next live-session prompt. Identity, voice, safety,
  tools and providers cannot be represented as preferences.
- Device enrollment requires owner authority, generates its secret in the
  host, stores it only in the native vault and exposes no credential to the
  model. This acceptance does not claim a remote transport listener or a
  physical-device pairing result.

## Technical SBOM

- `release/SBOM.spdx.json` SHA-256:
  `399b046ee49d757e06e77982aa91405e656829e11659503ad58dac4f4fad226a`.
- Artifact-set root:
  `341d61ebc26d1940bceceb063be7396b84fccea7fbeb184338923024d14722a9`.
- 141 packages, 6,784 file entries and 6,924 relationships.
- Release-eligibility tests: 21 passed, 1 platform skip.

This is technical reconciliation, not license/notices approval.

## Still open

- Owner acoustic acceptance of Charon and spoken owner-name persistence across
  a full restart.
- Eight-hour soak; this predecessor cannot qualify V14. Its final diagnostic
  monitor ended after one responsive sample when the process exited, with no
  Application Error event recorded during that 60-second monitor window.
- Live Microsoft Graph/Entra acceptance.
- Authenticode, clean disposable Windows host, legal/notices approval and
  independent final review.
- Separate native macOS and Linux build/install/audio/GUI/lifecycle evidence.
