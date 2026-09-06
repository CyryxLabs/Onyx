# Onyx 1.1.9 V41 Linux build failure

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact failed V41 Linux
> diagnostic evidence. Use `../CURRENT_RELEASE_STATUS.md` and
> `../DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md`; no later source or
> Windows result converts this record into native Linux acceptance.

Date: 2026-08-10  
Candidate: Onyx 1.1.9 V41 Linux x64 diagnostic  
Decision: **FAILED — PACKAGE PREFLIGHT DID NOT PASS**

## Exact evidence

- Frozen build source:
  `C:/MAAX_Assistant/Onyx-V41-Linux-Build-R2-20260810`
- Build output:
  `C:/MAAX_Assistant/Onyx-V41-Linux-Candidate-20260810`
- Exit-code receipt: `exit-code.txt`, content `1`, SHA-256
  `4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865`
- Build log: `build-and-test.log`, 41,728 bytes, SHA-256
  `6694a635e23dc121e6ed84f8057d03351e5904a74620c925934bf98eb49e47eb`

The PyInstaller bundle completed. The subsequent packaged-executable
`--preflight-only` check exited with code 70, so no DEB, TAR or AppImage from
this run is release evidence.

## Root cause

The frozen POSIX bootstrap treats an absent
`ONYX_PORTABLE_CURRENT_ACTIVATION_V1` value as portable-current. The V41
package-preflight harness removed that variable to select the predecessor
baseline. This selected portable-current instead, invoked the POSIX owner
authority and attempted the Secret Service child-process probe while the
native-startup smoke boundary was active. The boundary correctly rejected the
attempt with:

- `NativeStartupSmokeError: native startup attempted a child process`
- `PortableCurrentActivationV1Error: portable_current_v4_owner_authority_unavailable`

This is a harness-selection defect. It is not authorization to bypass or
weaken the production boundary.

## Successor correction

The post-V41 successor source explicitly selects the POSIX predecessor baseline with
`ONYX_PORTABLE_CURRENT_ACTIVATION_V1=0` in package preflight and native-startup
baseline smoke tests. Portable-current continues to require the exact value
`1`; the production frozen default is unchanged. The correction is covered by
the authenticated HUD V28 and release-workflow V44 transitions and the focused
integrated 211-test pass. It is not yet frozen, rebuilt or installed.

## Remaining Linux boundary

The container also reported unresolved native desktop/audio libraries,
including PulseAudio, Xtst, GTK 3 and several XCB/XKB dependencies. A corrected
container build may expose additional package failures. Even a passing
container build will not establish native Linux GUI, audio, permissions,
single-instance, signal, lifecycle or long-session parity; those require a
representative Linux desktop host.
