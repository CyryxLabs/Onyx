# Onyx Governance Nucleus V1

Status: additive V16 source checkpoint, 2026-07-31. It is not an installed-host
or cross-platform release claim.

## Live authority boundary

`core/governance_nucleus_v1.py` owns an authenticated owner principal/account
and an exact registry of distinct workspace identities, durable session capabilities,
authenticated append-only action
events, bounded low-risk grants, the trusted approval-inbox decision wrapper,
truthful capability projections and a persistent global kill latch.

`core/onyx_live_activation_v16.py` layers this authority over V15 without
editing the frozen V14/V15 activation implementations. The nucleus is created
during `OnyxLive` construction, before any Gemini/provider connection or Phase
5 session. V15 executable, Away and external-agent health remain delegated to
the accepted V15 controller.

The implementation directly reuses these accepted contracts:

- `session_grants_v11.HostActionPolicy` and
  `session_grants_v11.ActionBinding` for policy/binding validation;
- `approval_inbox_v15` for the read projection; and
- `Phase5IntegrationV3` for the existing provider-free
  `local_catalog_read` Nexus path.

The historical `control_plane_v4.open_default()` production opener remains
intentionally unavailable. V16 does not mislabel that frozen candidate as
live. Its new ledger is the production owner for this additive checkpoint and
keeps the same workspace boundary.

## Authorization and receipts

Every governed action intent is committed and native-vault anchored before
authorization. The binding includes the exact principal, workspace, durable
session, provider namespace, account, tool, operation, target digest, payload
digest and accepted V11 binding digest. Secret fields are redacted, and raw
targets/payloads are not copied into the ledger.

Only the closed low-risk read policies can receive expiring, use-bounded
grants. Any binding change, logout/reconnect, owner revoke, expiry, use
exhaustion, restart or global kill prevents reuse. Mutations and unknown tools
remain structurally always-explicit and flow through the sole trusted
approval-inbox callback.

Observed execution records the exact `completed`, `denied`, `rejected` or
`failed` outcome with a result digest. A callback exception is durably marked
`action-approval-failed`, never completed. Escaped execution records
`attempted_unknown`; a result arriving after kill is quarantined as
`action-late-blocked`. A V16 downgrade receipt can be issued only after the
already-bound trusted local UI approves an inbox request. The one-shot native
vault receipt is HMAC-authenticated and bound to the exact principal,
workspace, session, account, profile, target, request, expiry and nonce; there
is no public receipt-mint or verifier API. The launcher resolves host-owned
vaults internally. Before it emits an in-process bootstrap marker, consumption
is uniquely appended and HMAC-anchored in a separate native-vault/SQLite replay
ledger. Restored receipt bytes, concurrent consumers and process restarts
therefore fail closed. If the permission-broker audit cannot be persisted,
authorization fails, the nucleus revokes the just-used grant and records the
compensating governance audit failure.

## Capability Nexus truth

V16 exposes health and catalog projections, but it adds no provider dispatcher.
The only dispatchable Nexus action remains Phase 5's provider-free
`local_catalog_read`, and it is advertised as dispatchable only when the live
Phase 5 state is exactly READY, both required flags are true and there are no
component failures. External provider rows are
`configured-unverified`, not healthy or operational.

This slice deliberately does not activate email, browser, external-agent or
other provider mutations.

## Kill and rollback

Global kill is appended and anchored before session termination and grant
revocation, then records individual confirmed/incomplete propagation receipts
for Phase 5, Phase 11, MissionWorker and legacy authorization. The latch and
propagation state survive restart, and both V16 and legacy permission paths
freeze new mutations. If the pending-marker cleanup fails after the kill event
was committed and anchored, the live process reconstructs that authenticated
tail immediately, remains killed, refuses to overwrite the stale marker and
recovers it on restart.

V16 installation is atomic. A failure in any added seam restores the exact
pre-install host, including V15/V14 rollback. Normal rollback removes runtime
wrappers and restores the prior trusted callback, but does not delete the
action ledger.

Exactly one instantiated V16 host may own the process-wide broker hook. The
ownership marker is acquired before host initialization; a second instance is
refused before it can alter callbacks or route authorization into another
nucleus. Rollback releases ownership and restores the exact original callback.

The stable desktop bootstrap now selects V16 on Windows. A Windows downgrade
to V15, V14 or rollback requires an exact, short-lived, native-vault-backed,
one-time owner approval receipt; inherited environment flags alone cannot
downgrade the live host. Non-Windows V14 fallback remains available. Packaging source
definitions include the V16 modules. No installer was rebuilt in this
checkpoint.

## Verification

Focused warnings-as-errors:

```text
pytest -q -W error
  tests/test_governance_nucleus_v1.py
  tests/test_onyx_live_activation_v16.py
  tests/test_phase5_integration_v3.py

58 passed, 1 skipped
```

The coverage includes exact grant binding/use/revoke/expiry, restart,
two-workspace identity and sequence isolation, inbox authority/capacity,
callback failure, nested-wrapper rejection, database deletion with surviving
vault anchors, exact-schema and tamper refusal, commit/anchor/stale-pending
crash recovery, post-anchor kill cleanup failure, attempted-unknown and exact outcome persistence, kill
ordering/partial propagation/crash-tail restart/late result, Phase 5 health
gating, audit-unhealthy denial and compensation, owner-autonomy bypass
prevention, trusted-only one-time downgrade receipts, durable replay and
concurrent-consume refusal, single-instance callback/hook ownership,
mission-kill ordering, real no-network host construction and
atomic per-seam failpoint rollback.

Scoped Ruff passed for the V16 nucleus/activation, permission broker,
bootstraps and focused tests. `compileall` passed for those modules plus the
live host and the adjusted wiring regression test. The existing broader
`main.py` and regression file retain unrelated historical style debt.

## Remaining evidence

- No package was rebuilt, installed or exercised on a clean Windows host.
- No macOS/Linux V16 host exists because the V15 Phase 11 base is
  Windows-only; those platforms still use V14 fallback.
- No physical microphone, Gemini, external provider, browser or LAN/mobile
  end-to-end was exercised.
- Native-vault behavior is covered through deterministic vault contracts in
  the focused suite, not a clean installed-user OS credential probe.
- V15 activation/onboarding and the adjusted central tool-wiring gates pass
  (`29 passed`, nine subtests). In the wider regression segment, 114 tests and
  221 subtests passed before the two stale tool-wiring expectations were
  corrected. The former five-test dashboard warning gate is closed by the
  Starlette-supported `httpx2` test transport, hash-pinned through
  `requirements.lock`; `tests/test_regressions.py` now passes with warnings as
  errors on Windows (105 passed) and Linux (100 passed, five platform skips).
