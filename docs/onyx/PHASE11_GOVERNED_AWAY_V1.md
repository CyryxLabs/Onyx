# Phase 11 Governed Away Mode V1

> **VERSION-BOUND V15 BASELINE — NOT CURRENT RELEASE STATUS.** This document
> preserves the V1 bounded-browser contract. See
> [`CURRENT_RELEASE_STATUS.md`](CURRENT_RELEASE_STATUS.md) for current
> packaged/runtime evidence.

Status: live-wired in Windows V15, read-only browser slice,
`WORKING_WITH_LIMITATIONS`.

## Scope

`governed_browser_away_v1` performs one exact public HTTPS observation through
a headed Playwright Chromium session. It does not call the legacy
`browser_control` or `computer_control` actions.

The immutable action envelope binds:

- local owner principal, mission, workspace root and workspace ID;
- Away session ID, lease generation, profile, provider and account class;
- exact URL, origin, domain and finite resource-domain allowlist;
- action, one-use limit, approval window and network/output/screenshot/cost
  budgets;
- MissionStore exact-plan approval digest, key epoch and stop policy.

At dispatch, Onyx signs a separate runtime deadline that binds the immutable
plan, approval, current lease/execution identity, DNS pin and `max_seconds`.
That operational clock starts from the approved lease/dispatch boundary, not
from mission creation, and expiry requires a fresh approved mission.

The only V1 action is `observe`. The profile is Onyx-owned and unique to the
approved mission/Away session. On Windows it is atomically moved by handle to a
random quarantine under its still-pinned parent after the driver exits; Onyx
never falls back to path-based deletion after releasing authority. The
supported account class is exactly `none`: the V1
executor never consumes an existing user browser profile, stored user cookies,
credentials, MFA, OTPs, payment details or authenticated account state.

## Execution contract

1. `mission_create` materializes the host-authored step and authenticated
   binding before approval.
2. The trusted MissionStore approval UI binds the exact safe plan once.
3. `mission_run` queues the already approved action without a second per-step
   dialog.
4. After executable/runtime and DNS-pin preflight, and before Playwright
   navigation, Onyx writes an authenticated, create-once intent and flushes it
   to disk.
5. A second invocation never dispatches. A crash or provider error after intent
   becomes `attempted_unknown`.
6. Success requires the exact final URL/origin/domain at the final PASS gate,
   an authenticated durable receipt, and a final cancel/takeover/global-kill/
   deadline recheck. MissionStore still wins over any late receipt.

## Browser policy

- HTTPS, canonical public DNS hostnames and port 443 only. V1 rejects all query
  strings and fragments, including auth/session/signature/credential forms.
- DNS resolution fails closed: every returned IPv4/IPv6 address must be global.
  Chromium is launched with an exact host-resolver rule pinned to one member of
  that prevalidated public set, with proxy and browser DNS-over-HTTPS disabled.
  Every later route resolution must remain within the original set; private,
  loopback, link-local, reserved, multicast, mixed or rebinding answers abort.
- Exact context-level route allowlist; no wildcard domain matching. Service
  workers are blocked and popup pages are closed.
- Every WebSocket is denied through Playwright's context-wide
  `route_web_socket` API. QUIC is disabled, and WebRTC/WebTransport are denied
  by Chromium policy plus a pre-navigation context init policy.
- Headed window, fixed viewport and an Onyx-owned ephemeral profile.
- Availability validates the actual configured Chromium executable by launching
  and closing it before mission creation. Informational results are cached for
  at most five seconds; the pre-intent dispatch preflight always performs a new,
  authoritative probe. Missing or corrupt browser runtime is `unavailable`, not
  an attempted action.
- Browser dialogs, popups, downloads, domain/target drift, network-budget
  exhaustion, password fields, MFA/OTP and CAPTCHA pause rather than guess.
- Uploads and clipboard access are absent from the executor.
- Screenshot capture first masks inputs, text areas, editable content and
  password/email/card-labeled controls. MissionStore receives no page text or
  local screenshot path: only bounded byte counts, hashes and an opaque
  protected artifact reference.
- The protected artifact is re-opened through the trusted Away directory and
  its containment, existence, size and digest are revalidated before success.
- Away roots, attempt/receipt/control records, artifacts and the global latch
  use the descriptor-bound Windows trusted-directory boundary. Reparse points,
  symlinks and identity changes fail closed.
- The profile path includes both profile ID and Away session ID. Its directory
  identity is pinned over the Chromium lifetime, checked before and after use,
  and quarantined by identity-preserving handle-relative rename only after the
  browser owner thread confirms shutdown. If native secure deletion is not
  proven, the quarantined orphan remains and is reported.

## Operator flow

Create one mission with:

- `mission_type`: `governed_browser_away_v1`
- exact configured `workspace_root`
- `workspace_id`
- exact `target_url`
- finite `allowed_domains`
- optional `capture_screenshot`
- integer `max_seconds` from 5 through 60, never longer than the production
  worker lease

Then use `mission_run`. `mission_status` reports browser availability, control
state, intent/receipt state and whether redispatch is allowed.

Safety controls:

- `mission_pause`: terminally taints the V1 session, persists the control record
  and requests bounded owner-thread browser shutdown.
- `mission_takeover`: terminally taints the V1 session, persists the control
  record, stops the active driver and moves its Windows profile into the
  identity-verified quarantine.
- `mission_resume`: is refused after either pause or takeover. Continued work
  requires a fresh, separately approved mission/Away session.
- `mission_cancel`: persists Phase 11 kill authority, cancels MissionStore and
  discards late results.
- `mission_global_kill`: latches a durable global stop, blocks new Away work,
  persists each live mission kill, then stops its driver. Corrupt bindings,
  kill-write failures or still-active drivers return `incomplete` with bounded
  failures rather than reporting success.
- `mission_reconcile`: `still_unknown` keeps the mission blocked; `abandon`
  kills and cancels it. Neither decision redispatches.

On host shutdown, Phase 11 first blocks new runners and durably requests stop
while its binding authority remains readable. MissionWorker is then stopped and
joined, including its final authority observer. Phase 11 confirms Away
runner/driver exit and closes protected-directory handles before activation
rollback. Incomplete shutdown is reported as a failure. Transient busy Windows
binding or Away-root acquisition degrades the affected capability to explicitly
unavailable; invalid ACL/namespace state is reported separately instead of
crashing Onyx startup.

V15 reports this state as
`away_capability=unavailable:away_storage_transient_busy` (or the exact
ACL/namespace reason). It accepts degradation only for the closed reason enum
emitted by `GovernedAwayUnavailable`; missing, empty or unknown reasons fail
runtime preflight.

## Verification

Focused deterministic gates:

```powershell
.venv\Scripts\python.exe -m pytest -q `
  tests\test_phase11_governed_away_v1.py `
  tests\test_phase11_live_away_v15.py `
  tests\test_onyx_live_activation_v15.py `
  tests\test_onyx_live_activation_v15_onboarding.py
```

Real headed public-browser smoke, explicitly opt-in:

```powershell
$env:ONYX_PHASE11_BROWSER_SMOKE = "1"
.venv\Scripts\python.exe -m pytest -q `
  tests\test_phase11_governed_away_v1.py `
  -k real_headed_playwright
```

The smoke uses only `https://example.com`, a test-specific Onyx profile and a
temporary redacted screenshot artifact.

## Known limitations

- Native computer automation is unavailable with
  `no_verified_window_dpi_driver`; the legacy coordinate/input tool is not an
  Away authority boundary.
- V1 does not click, type, upload, download, authenticate, publish, purchase,
  send, deploy, merge, delete or mutate provider state.
- DOM masking is not a general OCR/DLP proof for arbitrary visual content.
  Pages carrying confidential/restricted data are outside this public-browser
  slice.
- There is no account/provider mutation reconciliation because V1 has no
  mutations. Unknown reads still remain blocked and never replay.
- The focused tests and one real headed smoke are proportional local evidence,
  not clean-machine, installed-package, multi-site or independent E6
  certification.

## Rollback

V14 remains unchanged. V15 installs the Away constructor seam alongside the
existing Phase 11 seam. Rolling V15 back restores the original constructor and
removes the runtime integration without deleting mission, intent, receipt,
control or evidence records.
