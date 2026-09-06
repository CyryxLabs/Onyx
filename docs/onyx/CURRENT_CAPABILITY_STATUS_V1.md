# Onyx current capability status V1

Updated: 2026-08-23  
Current candidate: **Onyx 1.1.10 Windows x64 engineering candidate**  
Trust status: **unsigned-untrusted**  
Release status: **NOT RELEASED**  
Live-provider status: **UNVERIFIED**

This document is the current status authority for candidate 1.1.10. It keeps
implementation, wiring, test, package, installation, provider, trust, and
release claims separate. A positive state in one column does not imply a
positive state in any later column.

`CURRENT_RELEASE_STATUS.md` is preserved as the historical formal **Onyx 1.1.9 R15B NO-GO**.
It is evidence about that version and must not be rewritten or
promoted as the current 1.1.10 status.

## Candidate matrix

| Candidate | implemented | source-wired | host-wired | tested | packaged | installed | provider-tested | signed | released |
|---|---|---|---|---|---|---|---|---|---|
| Onyx 1.1.10 Windows x64 | `YES` | `YES` | `YES_LOCAL_WINDOWS` | `YES_FOCUSED` | `YES_LOCAL_WINDOWS` | `YES_LOCAL_WINDOWS` | `UNVERIFIED` | `NO_UNSIGNED_UNTRUSTED` | `NO` |

## Exact evidence boundaries

- **implemented / source-wired:** the 1.1.10 engineering story records the
  bounded auto-start, topic-watching, Desktop-sweep, YouTube-locale, and current
  HUD work in source. This does not prove behavior in a packaged process.
- **host-wired:** local Windows runtime wiring was exercised only within the
  recorded candidate workflow. No clean-host or second-host claim is made.
- **tested:** the story records a focused result of **109 passed + 230
  subtests**. This is not certification, full cross-platform qualification, or
  live-provider acceptance.
- **packaged / installed:** a local Windows Setup and portable candidate were
  produced, installed, hash-compared to the bundle, and the installed
  `--preflight-only` path exited successfully. This is local engineering
  evidence, not a trusted distribution.
- **provider-tested:** no candidate-bound live Gemini, Microsoft Graph, Google
  Workspace, Argos, social/content, or other external-provider test is claimed.
  Provider behavior remains **UNVERIFIED** for 1.1.10.
- **signed:** no Authenticode or other trusted signing evidence exists for this
  candidate. Treat every 1.1.10 artifact as **unsigned-untrusted**.
- **released:** no commit, push, tag, publication, public artifact, or release
  promotion is claimed. Onyx 1.1.10 is **NOT RELEASED**.

## Maintenance decisions

- **IDS — ADAPT:** current-version language in `readme.md` and
  `docs/INSTALLATION.md` is adapted from their existing installable-application
  sections.
- **IDS — CREATE:** this version-scoped authority is new because the only
  existing `CURRENT_RELEASE_STATUS.md` is an immutable 1.1.9 R15B historical
  record.
- **IDS — ADAPT:** cross-file checks follow the repository's existing
  documentation/version assertion pattern.
