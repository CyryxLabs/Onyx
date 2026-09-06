# Phase 7 Workspace Aliases V1 checkpoint

## Scope

This candidate implements the second ordered Phase 7 slice: typed,
workspace/principal-scoped credential, browser-profile and artifact aliases.
It depends on the accepted Workspace Memory V1 envelope and remains exactly
default-off.

## Implemented contract

- immutable create, exact get, bounded list and persistent revoke;
- HMAC-authenticated canonical descriptor payloads;
- credential vault locator naming without secret access or storage;
- logical browser profile locators without profile/cookie/password paths;
- artifact alias registration and retrieval bound to the authoritative
  workspace `artifact_index`;
- active workspace, principal, connection, path and integrity-key attestation;
- secret-like input, duplicate JSON, tamper, lifecycle and cross-workspace
  denial;
- no credential resolution, browser launch, artifact byte read, network,
  process, provider, model, voice, UI, dashboard or live-runtime calls.

## Proportional regression result

Seven fresh Python processes reproduced:

- 160 passed tests;
- 113 passed subtests;
- 0 failed;
- 0 errors;
- 9 explained platform skips.

The skips are limited to POSIX mode/FIFO/link-count/quarantine/restart
contracts unavailable on Windows. The Windows-specific paths in those suites
passed.

## Limits

This candidate is not live-wired and adds no runtime authority. It does not
resolve credential values, open profiles, read artifacts, create approved
sources, build the Company Graph, produce the Founder Brief, exit Phase 7 or
complete the Onyx PRD.

E6 remains pending until an independent acceptance envelope rehashes the
candidate and reproduces this selection.
