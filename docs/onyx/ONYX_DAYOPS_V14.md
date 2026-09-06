# Onyx DayOps V14

> **VERSION-BOUND V14 BASELINE — NOT CURRENT RELEASE STATUS.** Retain this
> source contract for auditability. Current packaged and live-provider evidence
> is authoritative only in [`CURRENT_RELEASE_STATUS.md`](CURRENT_RELEASE_STATUS.md).

Status: local implementation candidate; no E6 acceptance or current live
provider E2E is claimed.

## Scope

V14 preserves the complete V13 runtime and adds one tool:
`day_brief_read`. It reads calendar and unread-mail metadata through
`MicrosoftGraphReadAdapterV1.daily_brief`. It cannot send mail, create or
modify events, mark messages read, or perform any other provider mutation.

The stable V15 bootstrap delegates to V14 when the separately provisioned
Phase 11 feature is absent. DayOps itself remains default-off outside the exact
V14/V15 predecessor activation environment.

## Required non-secret configuration

- `ONYX_DAYOPS_IANA_TIMEZONE`, for example `America/New_York`
- `ONYX_DAYOPS_OUTLOOK_TIMEZONE`, for example `Eastern Standard Time`
- `ONYX_DAYOPS_WORKSPACE_ID`
- `ONYX_DAYOPS_PRINCIPAL_ID`
- `ONYX_DAYOPS_CREDENTIAL_ALIAS`
- the accepted Phase 8 public OAuth onboarding values:
  `ONYX_PHASE8_MS_GRAPH_CLIENT_ID`, `ONYX_PHASE8_MS_GRAPH_TENANT_ID` and
  `ONYX_PHASE8_MS_GRAPH_ACCOUNT_ID`

No OAuth token belongs in environment variables, logs, tool arguments or this
configuration. The workspace, accepted credential-alias binding, native-vault
alias-integrity key and refresh token must already be provisioned. Readiness is
established from the real native-vault token, not from an environment marker.

## Local onboarding

The versioned CLI accepts only public identifiers. It rejects client secrets,
passwords and supplied access/refresh tokens:

```powershell
$env:ONYX_PHASE8_MS_GRAPH_CLIENT_ID="<public-client-guid>"
$env:ONYX_PHASE8_MS_GRAPH_TENANT_ID="<tenant-guid>"
$env:ONYX_PHASE8_MS_GRAPH_ACCOUNT_ID="<expected-account>"
$env:ONYX_DAYOPS_WORKSPACE_ID="cyryx-main"
$env:ONYX_DAYOPS_PRINCIPAL_ID="owner:pedro"
$env:ONYX_DAYOPS_CREDENTIAL_ALIAS="microsoft-primary"

.\Onyx-DayOps.exe prepare
.\Onyx-DayOps.exe status
.\Onyx-DayOps.exe sign-in
```

`prepare` idempotently initializes the local workspace and exact read-only
Microsoft credential alias, and creates the 32-byte alias-integrity key in the
native OS vault. `status` performs no network request and emits only redacted
states. `sign-in` reuses the accepted Phase 8 Device Bootstrap V2; the only
interactive values printed are Microsoft's verification URL and user code.
Cancel with `Ctrl+C`; the default local timeout is 900 seconds and can be
reduced with `--timeout-seconds`.

To remove only the stored Microsoft refresh token while preserving the
workspace and alias:

```powershell
.\Onyx-DayOps.exe disconnect
```

These commands configure the local candidate. They do not constitute a live
provider E2E, release acceptance or E6 evidence.

## Security order

1. The model request reaches the existing host dispatcher.
2. The host creates the existing audit trace.
3. `authorize_model_tool("day_brief_read", exact_arguments)` runs.
4. A denial returns immediately; the DayOps controller and adapter factory are
   not called.
5. Only the authorized host branch calls the controller and its deferred
   canonical factory.
6. The factory validates configuration, the accepted workspace/credential
   alias and the real native-vault refresh token before OAuth restore or HTTP.
7. Missing configuration or token returns safely with zero HTTP calls.
8. The factory then restores OAuth and constructs the accepted Phase 8 live
   read transport and Graph read adapter.
9. The normalized response omits provider IDs, links, account identity and
   attendee addresses and is written through the existing tool audit path.

## Rollback

Set the V14 rollback environment or launch the V13 bootstrap directly.
Transactional rollback removes the DayOps declaration and permission-policy
entry and controller binding, and leaves the existing host dispatcher
untouched. V13 remains installed; full rollback then delegates to V13.

## Current evidence and limitation

Focused DayOps/factory/V14 tests passed 19 tests. The proportional local
regression for V13, DayOps/V14, Phase 6 live wiring and Phase 8 Graph
Read/OAuth/Live Read passed 136 tests with one platform skip and one
pre-existing PySide disconnect warning. These tests use injected/fake
transports and prove authorization order, cautious/autonomous owner behavior,
real Phase 5 session startup, zero-network denial/config/token states,
normalization, lifecycle, failpoints and rollback. The stable preflight also
installs and rolls back V14 while proving the canonical factory is
configurable without provider or network calls. This does not prove current
Microsoft availability, refresh-token validity or live account data.
