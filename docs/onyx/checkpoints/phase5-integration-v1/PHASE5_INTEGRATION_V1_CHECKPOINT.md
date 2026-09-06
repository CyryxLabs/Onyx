# Phase 5 Integration V1 Checkpoint

Date: 2026-07-22

Status: implementation candidate, default-off and not live-activated. This is
not an E6 acceptance record and does not complete the Phase 5 exit.

## Scope

- Bridges only the accepted Session Grants R11, Approval Inbox V15,
  Capability Nexus V32, Component Adapters V3 and Runtime Core V10 anchors.
- Adds one session-scoped host object. It creates an exact five-dimension
  runtime binding and installs its permission hook only for that live session.
- Preserves the current broker, model dispatcher and dashboard when the master
  and runtime flags are off.
- Enables only `local.catalog/catalog_read`: provider-free, read-only,
  effect `none`, egress `none`, allowlisted metadata, zero cost, low risk and
  reversible. The V10 decision is consumed once before the V32 read adapter.
- Keeps every consequential legacy tool on the existing autonomy or trusted
  callback path.
- Exposes authenticated dashboard reads for status, inbox and capabilities,
  plus POST kill. There is no remote approve, grant or dispatch route.
- Uses one host-owned kill/revoke/rollback boundary. V10 revokes authority
  first, then the host closes grant, Nexus, inbox and prepared-dispatch state
  and acknowledges each opaque termination token.

## Flags

All flags parse only exact `1` or `true` and default to false:

- `ONYX_PHASE5_INTEGRATION_V1`
- `ONYX_PHASE5_RUNTIME_V1`
- `ONYX_PHASE5_GRANT_SHADOW_V1`
- `ONYX_PHASE5_APPROVAL_INBOX_V1`
- `ONYX_PHASE5_LOW_RISK_V1`
- `ONYX_PHASE5_NEXUS_PROJECTION_V1`
- `ONYX_PHASE5_LOCAL_CATALOG_READ_V1`
- `ONYX_PHASE5_DASHBOARD_PROJECTION_V1`

An enabled runtime also requires explicit canonical principal, workspace,
account and profile identifiers. There is no implicit `legacy-default`.

## Extension-off and safety evidence

- The static legacy declaration/policy/dispatch invariants remain 26/26.
- Phase 5 dashboard routes do not exist when the dashboard flag is off.
- A Phase 5 hook supplied during a legacy-tool test was not called.
- The local tool is declared to the model only for an active, successfully
  constructed session bridge.
- Kill, revoke, rollback, end-session, reconnect and shutdown each reached
  `TERMINATED` with zero termination failures/timeouts.
- Accepted component files and `ui.py` rehashed to their pre-integration bytes.
  No Orb, QML or HUD file was edited by this slice.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  --basetemp=.pytest-p5-integration-final-run `
  tests\test_phase5_integration_v1.py tests\test_regressions.py `
  tests\test_dashboard_upload_security.py tests\test_readiness.py

.\.venv\Scripts\python.exe -m ruff check `
  core\phase5_integration_v1.py tests\test_phase5_integration_v1.py

.\.venv\Scripts\python.exe -m py_compile `
  core\phase5_integration_v1.py core\permission_broker.py `
  dashboard\server.py main.py
```

Results:

- 185 tests passed and 269 subtests passed; zero failures.
- One existing Starlette TestClient deprecation warning.
- Ruff passed for both new candidate files.
- Python compilation passed for the new bridge and all three live hook files.
- 100 sequential authorize/consume/read operations: p50 5.631 ms, p95
  21.4261 ms, maximum 73.3155 ms and zero background-thread delta.

Full-file Ruff over the already modified live files still reports 19 legacy
E701/E702/E401 findings outside this slice. They were not mechanically changed
because unrelated formatting would widen the candidate and dirty-worktree
scope.

## Honest limitations

- No live process was restarted and no flag was activated for this candidate.
- The inbox source is currently a truthful empty, session-bound host capture;
  the legacy modal callback has no accepted durable action-request feed. This
  slice therefore does not claim a populated operational approval queue.
- Grant evaluation remains shadow-only and has no live grant authority.
- The accepted V32 Nexus projection remains descriptor-only/shadow-only. The
  separately governed V32 local adapter is the only executable extension.
- The dashboard surfaces have no desktop UI controls in this slice, and no
  Orb/HUD file was changed.
- There is no provider, MCP, browser fallback or external mutation activation.
- Physical live-process resource deltas, LAN/mobile behavior and end-user voice
  behavior require a later accepted activation and observed run.
- Three isolated pytest basetemp directories remain outside the candidate
  bundle. Exact-path cleanup was attempted only after containment checks, but
  host policy blocked removal. They are not imported by the runtime.
- The candidate still requires independent functional, integrity and quality
  review before E6 acceptance or any live flag activation.

Machine-readable evidence:
`docs/onyx/checkpoints/phase5-integration-v1/manifest.json`.
