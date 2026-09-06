# Onyx 1.1.9 V24 external release prerequisites

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as V24 historical evidence.
> Current open gates are in `../CURRENT_RELEASE_STATUS.md`.

Status: **current host probed; external authority/platform access remains required**  
Probed: 2026-08-04  
Candidate: Windows x64 V24 / activation V21 / Release Workflow V11

This checkpoint records the boundary between defects that can be corrected in
the repository and release gates that require an external identity, platform,
owner action or independent reviewer. No secret values were read or recorded.

## Microsoft Entra and DayOps

- The installed `Onyx-DayOps.exe` exposes the governed `status`, `prepare`,
  `sign-in` and `disconnect` flows.
- No supported Entra public-client ID, tenant ID, account ID, workspace ID,
  principal ID or credential-alias configuration is present in the current
  process, user or machine environment.
- A live Microsoft Graph request was not attempted without a real public-client
  registration, test account and owner consent.

Closure requires the redacted device-code and live calendar/mail evidence in
`../PHASE8_MICROSOFT_GRAPH_LIVE_ONBOARDING.md`, bounded to `User.Read`,
`Calendars.Read`, `Mail.Read` and `offline_access`.

## Windows signing and clean lifecycle

- `signtool` is not available on the current `PATH`.
- The current-user certificate store contains no trusted code-signing identity
  suitable for the Cyryx Labs publisher contract.
- The exact V24 setup and portable artifacts are therefore intentionally
  classified `untrusted-candidate`, not formal/public release files.
- Installed inventory and current-host runtime acceptance passed, but a signed
  clean install, prior-version upgrade, uninstall and rollback sequence still
  requires a disposable Windows x64 host and trusted current/prior artifacts.

## Linux availability

- Docker Desktop 29.2.1 supplies a Linux x64 container engine.
- WSL exposes only the `docker-desktop` distribution; there is no representative
  Linux desktop session with GUI, microphone, speakers, keyring and native
  desktop integration on this host.
- Container packaging diagnostics can prove source tests, artifact structure,
  permission manifests and a clean Debian package installation. They cannot
  close the native GUI/audio or physical lifecycle gate.
- The V20 container diagnostic remains historical. A V24-isolated diagnostic
  is tracked separately and must not be described as native desktop acceptance.

## macOS availability

- No macOS runner is attached to this checkout.
- No Apple Developer ID Application identity, team identifier, notarization
  key or notarization account configuration is available in the probed
  environment.
- No signed/notarized V24 macOS artifact can be created or truthfully assessed
  from this Windows host.

Closure requires native Intel and Apple Silicon evidence, Developer ID and
hardened-runtime signing, notarization, stapling, Gatekeeper assessment, and
installed GUI/audio/lifecycle receipts.

## Repository runners and publication

GitHub CLI is present, but this checkout has no Git remote and the current V24
source is not published as a traceable remote commit/tag. No remote, branch,
commit, tag, release or workflow run was created by this probe. Repository
publication remains a separate owner-authorized action.

## Legal and independent authority

- Technical SBOM reconciliation passed for the exact V24 Windows artifacts.
- The third-party worklist still contains four `NOASSERTION` records, 25
  noncanonical expressions, four substantive supplemental decisions and two
  `primp` package-local gaps.
- The legal approval record is blank by design. Engineering cannot manufacture
  legal approval.
- The final evidence index has not been reviewed by an independent person.

## Inputs required to close the roadmap

1. Entra public-client registration, test account and owner consent.
2. Trusted Cyryx Labs Windows signing identity and timestamp access.
3. Disposable Windows x64 lifecycle host with signed current/prior candidates.
4. Native Linux x64/arm64 desktop runners with GUI/audio/keyring.
5. Native Intel and Apple Silicon runners plus Apple signing/notarization
   credentials.
6. Qualified approval of final license/notices and durable upstream-rights
   references.
7. Owner acoustic confirmation and spoken-name persistence test.
8. An independent reviewer for the frozen final evidence index.

Until the candidate-bound acceptance harness for an item passes, its state is
`BLOCKED_BY_ACCESS`, `BLOCKED_BY_PLATFORM`, `OWNER_ACCEPTANCE_REQUIRED`, or
`REVIEW_REQUIRED`; it is never inferred from a different platform or an older
candidate.
