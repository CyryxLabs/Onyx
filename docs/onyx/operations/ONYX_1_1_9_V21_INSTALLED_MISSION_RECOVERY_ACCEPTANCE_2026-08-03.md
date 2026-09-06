# Onyx 1.1.9 V21 installed mission and recovery acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V21 historical
> mission/recovery evidence. Use
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Status: **bounded installed-predecessor acceptance passed**  
Date: 2026-08-03  
Platform: Windows x64

## Bound implementation

- Installed module:
  `%LOCALAPPDATA%\Programs\Cyryx Labs\Onyx\_internal\core\missions.py`
- Installed module SHA-256:
  `7af0c456d14f3e8a3d6dcb49eca017521b386e5d6f519f9f8057abcab5111327`
- Result contract: `OnyxInstalledMissionRecoveryAcceptance.v1`

The harness imported the installed module rather than the source checkout. It
used isolated mission state and deliberately avoided provider, network and
external-system effects.

## Reproduced lifecycle

- Created a representative mission, ran it to completion, reopened its store
  and validated the audit-chain hashes.
- Created a second mission, paused it and then cancelled it through the mission
  authority.
- Started a child process that intentionally exited with code `73` after
  durable `step.started` evidence.
- Reopened that mission. Recovery moved the interrupted running step to
  `waiting`, emitted `step.recovery_wait` and did not blindly replay work.
- Applied the explicit `retry` recovery resolution, completed the step and
  revalidated the resulting audit chain.

An earlier negative-control attempt directly altered the SQLite projection and
correctly failed closed with `Mission authority projection diverges`. That was
a successful tamper control, not an operational runtime failure.

## Boundary

This closes the representative installed mission/recovery gate for the exact
packaged mission module above. It does not qualify the pre-V14 GUI package as
the current release: the separate QML close-lifecycle correction still requires
a new build and installed-runtime acceptance. If the packaged mission module
changes, this test must be repeated against its new exact SHA-256.
