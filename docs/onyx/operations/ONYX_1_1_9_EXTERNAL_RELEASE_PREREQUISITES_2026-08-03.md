# Onyx 1.1.9 external release prerequisites

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** This V19-era host probe remains
> historical evidence only. Current external gates are recorded in
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Status: **current host probed; external access remains required**  
Last probed: 2026-08-04  
Candidate: Windows x64 V19 / activation V21

This checkpoint records what the current host can and cannot supply. It does
not expose credential values and does not convert missing access into a source
defect or a passed release gate.

## Microsoft Entra and DayOps

- The installed `Onyx-DayOps.exe` exists and exposes `status`, `prepare`,
  `sign-in` and `disconnect` commands.
- The installed `status` command requires the public client ID, tenant ID,
  account ID, workspace ID, principal ID and credential-alias name.
- No Entra/DayOps client or tenant identifier is configured in the current
  process, user or machine environment under the supported probe names.
- No client secret, token or password was requested, read or printed.
- A live Graph call was not attempted because the public registration/account
  identity and owner consent are absent from this host evidence.

Closing evidence remains the device-code flow and redacted live report defined
by `../PHASE8_MICROSOFT_GRAPH_LIVE_ONBOARDING.md`, including calendar and mail
reads with `User.Read`, `Calendars.Read`, `Mail.Read` and `offline_access`.

## Windows signing

No current-user certificate advertises the code-signing EKU. Self-signed
`CN=Petruff Technologies` certificates are present, but they are neither a
trusted Cyryx Labs release identity nor eligible evidence for the formal
Authenticode gate.

The exact V19 Windows artifacts therefore remain unsigned
`untrusted-candidate` files until a trusted Cyryx-controlled certificate and
timestamp service are available and the native eligibility receipt passes.

## Linux availability

- WSL2 is available only through the running `docker-desktop` distribution.
- Docker Desktop provides a Linux x64 engine and is sufficient for isolated
  packaging diagnostics.
- It is not a representative Linux desktop host with user session, GUI,
  microphone, speakers, desktop integration or native lifecycle evidence.
- No Linux artifact is present in the current `release/` directory.

Docker may exercise build/package contracts later, but it cannot close the
native Linux GUI/audio/install gate required by the roadmap.

## macOS availability

- The current host is Windows; there is no native macOS runner attached to the
  checkout.
- No Apple ID, team ID, app-specific password or signing-certificate path is
  configured in the current process/user/machine environment.
- No macOS artifact is present in the current `release/` directory.

The macOS gate still requires a native Apple Silicon host, Developer ID
Application identity, hardened-runtime signing, notarization, stapling,
Gatekeeper assessment and installed audio/GUI/lifecycle evidence.

## Repository runners

The checkout contains CI and formal release workflows for Windows, macOS arm64,
Linux x64 and Linux arm64. GitHub CLI authentication is available, but this
checkout has no Git remote. Consequently, its current uncommitted source state
cannot be traced to or dispatched by those workflows without a separately
authorized publication step. No remote, commit, tag or workflow run was
created by this probe.

## Required external inputs

1. Entra public-client registration, test account and owner consent.
2. Trusted Cyryx Labs Windows code-signing identity and timestamp access.
3. Native Linux x64/arm64 desktop runners with GUI/audio.
4. Native Apple Silicon runner plus Apple Developer ID/notarization secrets.
5. Clean/disposable platform hosts for install, upgrade, uninstall and
   rollback.
6. Qualified license/notices approval and durable upstream-rights reference.
7. An independent reviewer for the final frozen evidence index.

Until each relevant input is supplied and its exact acceptance harness passes,
the corresponding state remains `BLOCKED_BY_ACCESS`, `BLOCKED_BY_PLATFORM` or
`REVIEW_REQUIRED` rather than failed-open or inferred from another platform.
