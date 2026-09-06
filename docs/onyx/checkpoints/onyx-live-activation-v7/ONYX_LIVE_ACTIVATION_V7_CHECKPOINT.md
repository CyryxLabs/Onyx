# Onyx Live Activation V7 — Candidate Checkpoint

Status: **CANDIDATE READY FOR INDEPENDENT GATE — NOT LIVE**

V7 is an additive correction over the frozen V6 candidate. It changes no V1–V6
byte and does not replace any accepted provider, replay, circuit, Qt, owner, HUD,
or Phase 5 implementation.

## Confirmed root cause

The V6 active launcher omitted all four explicit Phase 5 identities. Supplying
those identities made the real bridge READY, but the full host path still
denied Gemini's local catalog calls. The remaining mismatch was deterministic:
`main.py` generated the private invocation reference with
`os.urandom(8).hex()`. The accepted grant-shadow identifier contract classifies
that raw hexadecimal reference as token-like, so the bridge returned
`grant_shadow_failure`.

The same real bridge, flags, identity, trust profile, autonomy configuration,
and main catalog accepted canonical host references and completed the read.
This excludes bridge termination, supersession, and owner-autonomy state as the
cause.

## V7 launch identity contract

Active V7 requires exactly:

- `ONYX_PHASE5_PRINCIPAL_ID=onyx-owner`
- `ONYX_PHASE5_WORKSPACE_ID=onyx-local-workspace`
- `ONYX_PHASE5_ACCOUNT_ID=cyryx-local-account`
- `ONYX_PHASE5_PROFILE_ID=onyx-owner-profile`

Missing identities, partial identities, noncanonical values, generic aliases,
non-`1` activation flags, and mixed rollback/active controls fail before
`main`, `ui`, or the V7 core is imported.

The real-host preflight materializes an exact
`core.phase5_integration_v3.Phase5IntegrationV3` from the live
`main.TOOL_DECLARATIONS`, verifies the single `local_catalog_read` declaration,
the runtime binding, and READY local-catalog state, then terminates the probe.
No network call is made.

## Canonical local-catalog invocation

V7 adds one host seam after V6 installation, only for
`local_catalog_read`. It:

- preserves V6 exact provider `call_id` identity, canonical argument digest,
  256-record bounded replay registry, conflict refusal, immutable cached
  result, and concurrent single-flight behavior;
- never changes or coerces Gemini's public arguments;
- adds the private host reference as `catalog-p<PID>-n<N>`, satisfying the
  accepted identifier grammar;
- executes the full `main.authorize_model_tool` broker path after
  `configure_owner_autonomy`;
- dispatches through the real session bridge only after authorization;
- retains the existing two audit points and fail-closed response behavior.

Denials expose only a bounded diagnostic tuple: runtime state, an allowlisted
reason code, and whether local catalog is enabled. Provider arguments, catalog
content, identifiers, and raw broker messages are not logged in the UI
diagnostic.

## Candidate evidence

- V7 focused pytest: `6 passed`.
- V4–V7 cumulative pytest: `57 passed`.
- V7 host gate: four exact identities, 32 missing/wrong/alias/control variants
  refused, real 26-entry main catalog, real bridge, zero network calls, V7 seam
  failpoint rollback, and content-free denial diagnostic.
- Full-host fake-provider E2E: actual patched `main.OnyxLive`, actual
  `configure_owner_autonomy`, actual `main.authorize_model_tool`, real
  `Phase5IntegrationV3`, `1011` reconnect, two distinct READY bridges, exact
  `audio/pcm;rate=16000`, one completed five-item provider-free catalog read,
  and replay of the same provider call without re-execution.
- Frozen V6 manifest gate: pass.
- Ruff and `py_compile`: pass.
- No real provider/network call, live restart, shortcut update, or live
  activation was performed.

## Gate boundary

This checkpoint is candidate evidence, not production evidence. An independent
gate must verify every manifest binding and rerun the focused, cumulative,
real-host, and fake-provider suites before a controlled V7 live activation.
The currently running V6 process was not modified or restarted.

## Candidate controls

- Active candidate: `scripts\launch_onyx_live_v7_active.cmd`
- Exact rollback: `scripts\launch_onyx_live_v7_rollback.cmd`
- Preflight: run `scripts\launch_onyx_live_v7.pyw --preflight-only` with the
  complete canonical V7 activation environment.
