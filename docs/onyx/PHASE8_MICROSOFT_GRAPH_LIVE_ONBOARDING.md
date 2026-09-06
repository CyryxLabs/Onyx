# Phase 8 Microsoft Graph live onboarding — exact owner steps

> **CURRENT EXTERNAL PROCEDURE — NOT PASS EVIDENCE.** Completing these steps is
> necessary but does not close DayOps by itself. The authoritative gate state
> is in [`CURRENT_RELEASE_STATUS.md`](CURRENT_RELEASE_STATUS.md).

Status: `BLOCKED_BY_ACCESS` until the Cyryx owner completes these steps. The
implementation (`core/phase8_microsoft_graph_live_read_e2e_v1.py`) is complete
and contract-tested; only the authorized registration and test account are
missing. Nothing below stores a secret in the repository — a public native
client has no client secret at all.

## 1. Create or choose the tenant and test account

1. Use a Microsoft Entra tenant you control (a free developer tenant works).
2. Create or choose a **test account** (e.g. `onyx.test@<tenant>.onmicrosoft.com`)
   with a mailbox and calendar. Do not use a production mailbox for the first
   live E2E.

## 2. Register the public client application

In the [Entra admin center](https://entra.microsoft.com) → Identity →
Applications → App registrations → **New registration**:

1. Name: `Onyx by Cyryx Labs` (or similar).
2. Supported account types: single tenant is sufficient for the test.
3. Do **not** add a client secret or certificate. Ever, for this app.
4. After creation, note the **Application (client) ID** and
   **Directory (tenant) ID** — both are public identifiers.
5. Under **Authentication**: enable **Allow public client flows**
   (this enables the device-code flow).
6. Under **API permissions**: add delegated Microsoft Graph permissions
   `User.Read`, `Calendars.Read`, `Mail.Read`, `offline_access`; grant/consent
   per tenant policy (user consent during device sign-in is acceptable for
   these read scopes on most tenants).

## 3. Run the live read-only E2E

In a PowerShell session (values are public identifiers, not secrets):

```powershell
$env:ONYX_PHASE8_MICROSOFT_GRAPH_LIVE_READ_E2E_V1 = 'true'
$env:ONYX_PHASE8_MS_GRAPH_CLIENT_ID  = '<application-client-id-guid>'
$env:ONYX_PHASE8_MS_GRAPH_TENANT_ID  = '<directory-tenant-id-guid>'
$env:ONYX_PHASE8_MS_GRAPH_ACCOUNT_ID = '<test-account>@<tenant>.onmicrosoft.com'
.\.venv\Scripts\python.exe scripts\run_phase8_microsoft_graph_live_read_e2e_v1.py
```

The runner prints a `microsoft.com/devicelogin` URL and a user code. Sign in
with the **test account only**. The runner then executes the live probes
(sign-in/read, access-expiry refresh, refresh rotation) and writes a redacted
JSON report under `runtime/phase8-live-e2e/`.

For the live revocation probe, run again with `--live-revocation`; when
prompted, revoke the app's sessions/consent for the test account
(https://myaccount.microsoft.com/ → Manage sign-out, or Entra admin center →
user → Revoke sessions), then press Enter.

## 4. What the harness refuses

- Any of `ONYX_PHASE8_MS_GRAPH_CLIENT_SECRET`, `..._PASSWORD`,
  `..._REFRESH_TOKEN`, `..._ACCESS_TOKEN` set in the environment → the run is
  denied before any network activity.
- A signed-in account different from `ONYX_PHASE8_MS_GRAPH_ACCOUNT_ID` → the
  device sign-in is rejected after `GET /me` verification.
- Write scopes, non-Graph routes, non-GET Graph calls → structurally denied by
  the frozen predecessor contracts.

## 5. Evidence semantics

- `probes_missing` in the report lists probes that did not run live
  (`provider_failure` and `rate_limit_retry_after` cannot be forced against
  the live service; they are deterministically proven by
  `tests/test_phase8_microsoft_graph_live_read_e2e_v1.py`).
- `live_verified` is `true` only if every probe ran live.
- The report contains no tokens, no message bodies and no query strings; the
  refresh token lives only in the OS native vault.
