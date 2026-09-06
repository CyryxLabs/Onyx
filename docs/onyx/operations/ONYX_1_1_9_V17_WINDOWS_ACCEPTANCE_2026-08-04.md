# Onyx 1.1.9 V17 Windows installed acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V17 historical
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Date: 2026-08-04  
Platform: Windows x64  
Activation: V21  
Source successor: V17  
Status: **PASSED LOCAL INSTALLED ACCEPTANCE — FORMAL RELEASE GATES OPEN**

## Candidate identity

- Phase 5 V17 transition SHA-256:
  `03edb5ae160ae20ff42e0f7c434b9353637aa44b59fac0d01ea168e89c3e9319`.
- Phase 5 V17 domain root:
  `2d33d97f437df7c6fe22bb1d1625fc4394d7b73cea1de583811c3352e6194823`.
- Release Workflow V4 transition SHA-256:
  `bec9658f723fc467d888b311780d013689f6a6ac09cda58ec01827c96b60f12d`.
- Release Workflow V4 domain root:
  `690da4e1f7fd0cd5cdb7bb8f911f140fe3e1a6ccda6b1048ac999f5f56fb1a48`.
- First-party input seal: 1,303 files; root
  `6f47da5a9892d3b55cabdcf0735cea2c9e87e4a058c8ff8b6cd0f41ac8279167`.
- Input-manifest SHA-256:
  `7e86efd39d0abd5d2906991a8c3f4d4458f118a73aff4b9f4f78c15de090856a`.

## Artifacts and inventory

- Setup SHA-256:
  `3efc34707f37369dc393bd5fd3cd35096c7f51c4c8352dbba0575920a484e713`;
  484,917,499 bytes.
- Portable SHA-256:
  `af761d002d122263ebe62504218653f555706d50d910efba24d8950867525d64`;
  550,563,544 bytes.
- Release-manifest SHA-256:
  `919650fa5da96d228462f35ddcbe287d2aac9df30e7d1ead28072ddf2908d245`.
- Bundle-inventory SHA-256:
  `ef0db153f6c3d3b6b7271129370f28caef5493a42c0c23a39d992a5125c640de`.
- Bundle root:
  `9de36ba5fe444966f040b7bdaee89e939b5aa442385e16b69374d7c77d3e4bec`.
- Runtime distributions: 95; distribution root
  `6524a84b48a81bb1eb138b815d995041854066ac8461c327f8fb09dc3982ec7e`.
- Setup exit: 0.
- Exact installed comparison: 7,287 expected; 0 missing; 0 mismatched;
  0 non-uninstaller extras.

## Packaged and installed gates

The clean, hash-locked build completed in 1,366.2 seconds. Package, fallback
and V21 preflight, native startup, Governance V16, Founder V17, Document
Intake V18.1, DayOps V20, Advanced Operations V20 and Advanced Commands V21
smokes passed in both the generated bundle and the installed executable.

The technical SPDX inventory generated from the exact final artifacts passed.
`release/SBOM.spdx.json` has SHA-256
`230264e3c1de42338aa72bb93b8b542feef7181f8fe35b52ca2c455677e52e52`.

## Real voice and lifecycle gate

The real installed UI opened and remained responsive. The V21 session log
recorded connection to Gemini Native Audio plus microphone, receive and
playback channel startup.

A Win32 normal main-window close was then requested. The installed process
recorded the main-window `closeEvent`, `QApplication.aboutToQuit` and return
from the Qt event loop, and exited. The exact session slice contained zero
`RuntimeCleanupError` and zero `terminal reason invalid`, proving the V17
normalization corrected the installed V16 shutdown failure. Two Uvicorn
lifespan `CancelledError` diagnostics remain noisy but did not prevent clean
process exit or Phase 5 cleanup.

The installed V17 application was relaunched and left open for owner acoustic
acceptance. Attempt 7 ended after 180.305 seconds when that visible window
received a normal `closeEvent`; its two samples were responsive, average host
CPU was 0.440917%, memory stayed within thresholds and Windows recorded no
Application Error. It is non-qualifying duration evidence, not a crash.

The eight-hour attempt 8 monitor targets the exact relaunched minimized process
and writes under
`%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v17-soak-attempt8-*`.
That gate remains in progress until its full-duration receipt exists.

## Boundary

This record proves a local unsigned Windows candidate. It does not close owner
acoustic/name-change acceptance, the eight-hour receipt, live Microsoft Graph,
trusted Authenticode, clean-machine lifecycle, macOS/Linux native evidence,
legal approval or independent final review.
