# Phase 11 Project Autopilot V1 checkpoint

Status: **candidate, `PARTIAL`; no E6 or Phase 11 exit claim**

## Implemented evidence

- `core/phase11_project_autopilot_v1.py`
- additive bridge/worker wiring in `core/phase11_live_mission_v1.py`
- closed mission policy in `core/permission_broker.py`
- additive Live mission inputs in `main.py`
- `tests/test_phase11_project_autopilot_v1.py`
- `core/phase11_windows_clone_cleanup_v1.py`
- `tests/test_phase11_windows_clone_cleanup_v1.py`

## Focused validation

Run on 2026-07-30:

- handle-safe cleanup backend: `56 passed, 14 subtests passed`;
- Project Autopilot integration: `28 passed, 2 subtests passed`;
- broader Live/MissionStore/V15 selection: `2043 passed, 6 skipped,
  58 subtests passed`, with one unrelated missing historical mutable-projection
  fixture failure in `test_approval_inbox_v15.py`; this is not a full green
  repository claim;
- focused Live bridge plus Project Autopilot: `64 passed, 1 skipped,
  13 subtests passed`;
- combined Autopilot, Phase 11 bridge, local audit, Live V15 activation and
  MissionStore regression: `147 passed, 1 skipped, 60 subtests passed`;
- focused MissionStore schema, migration, authority and execution regression:
  `62 passed, 47 subtests passed`;
- Ruff `F,E9`: pass on all changed Python files;
- Python compile: pass on all changed Python files.

The vertical slice proves clean-HEAD binding, canonical signed patch paths,
isolated patch application, non-executable static gates, retained wait
checkpoint, restart-resume refusal, source-bundle scrubbing,
fail-closed clone retention, cross-process exclusion, crash-journal recovery,
preflight/live disk quotas, encrypted-patch canary scanning, stdin-only patch
application with no plaintext patch artifact, bounded stdin-writer
termination, file/directory/depth/time monitor limits, serialized
checkpoint/status/recovery/verifier access with no stale overwrite, explicit
fresh-reapproval reseed, lazy disk enumeration with immediate limit
short-circuit, exact `mission_run.fresh_reapproval` tool-schema wiring and
bridge/worker reachability in a temporary Git repository. It also proves that
2,000 hot kill checks perform zero MissionStore/history reads, an in-process
durable kill sets the event immediately, and a persisted kill is reconciled
before tool start after restart. Distinct handles work across two bridges and a
real second Windows process observes the same authenticated named Event.
Persist-before-signal crash recovery detects an Ed25519-authenticated kill even
when the native-vault anchor still trails the MissionStore head; benign worker
events ahead of that anchor do not create a false kill, and a later cancellation
event does not hide the terminal marker. The bounded absence lookup is backed by
the sealed MissionStore schema-v6 `(mission_id,event,seq)` index; the v5-to-v6
migration, rollback seam, exact reopen, tamper cases and a 2,048-event
`EXPLAIN QUERY PLAN` canary are covered. MissionStore rechecks this authority in
the same transaction that would commit step or mission success, quarantining a
late successful result after kill. Wrong-DACL precreation and `WAIT_FAILED` fail
closed, runner lifecycle prevents close/use-after-close races, handles close
safely, reseed changes event identity, and kill-cache capacity fails closed
without unsafe eviction. Owner cleanliness and bounded `.git` digest are
observed again at verification time; this is not an absolute claim that no
unobserved transient change occurred. It does not prove an installed desktop
host, automatic crash/restart replay through the Live UI or complete Phase 11
E1-E6.

## Remaining Phase 11 work

1. observe the default-off executable sandbox/ledger successor against an
   exact local image and real Docker host;
2. expose authenticated wait/resume/reconcile without weakening MissionStore;
3. add concurrent kill stress evidence on supported installed desktop hosts;
4. implement browser/computer signed envelopes, redaction and takeover;
5. independently accept the health-only external-agent adapter before any
   coding dispatch or draft-PR successor;
6. complete independent review and E6 installed-host observation.
7. independently review the default-off Windows handle-relative cleanup
   candidate and observe it on an installed desktop host before acceptance.

## Stage A-E final hardening checkpoint

Current-tree reproduction on Windows, 2026-07-30:

- focused Stage E lifecycle/adversarial selection: `7 passed, 11 subtests`;
- Local Audit + Windows namespace/cleanup: `85 passed, 25 subtests`;
- full proportional Local Audit + namespace + cleanup backend + patch engine +
  Project + Live + MissionStore + V15 selection: `2181 passed, 6 skipped,
  92 subtests passed` in 328.66 seconds;
- post-freeze lifecycle/POSIX/checkpoint correction selection:
  `6 passed, 12 subtests passed`; affected Local Audit + namespace + cleanup
  backend + patch engine + Project + Live matrix: `181 passed, 1 skipped,
  57 subtests passed` in 423.00 seconds;
- independent P1 correction selection for old-style executable Git config and
  terminal `patch_applied`/`gates_running` cleanup: `6 passed, 10 subtests
  passed`; complete Project + cleanup suites: `108 passed, 51 subtests
  passed`; affected six-suite matrix: `186 passed, 1 skipped, 67 subtests
  passed` in 440.75 seconds;
- Python compile and scoped Ruff: pass.

Stages A-E add centralized handle-relative namespace ownership, signed
pre-population provenance, a protected streamed Git bundle, typed
handle-relative patching with encrypted recovery journal, trusted Live
binding/artifact I/O, explicit Job HANDLE signatures, bounded reference-counted
mission locks, bounded non-evicting process high-water registries, expanded
Windows reserved-name refusal and best-effort directory metadata flush.

Status remains **`PARTIAL`, default off, Windows only**. The executable
sandbox plus exact host ledger are locally live-wired candidates, and the
external-agent adapter is health-only/fail-closed. There is no E6, observed
real-Docker or installed-host acceptance, accepted executable repository
test/build authority, browser/computer-control envelope, coding-agent dispatch,
PR/deploy authority
or claim of clean hardware-power-loss durability. Metadata inherits the trusted
parent ACL. Cryptographic and vault controls protect integrity; they do not
claim confidentiality or isolation from same-user processes or administrators.
Residual work includes an intentionally separate ACL design, installed-host
observation, cache-capacity operational sizing and a non-Windows handle-safe
cleanup implementation.

Maintainability debt: the Phase 11 Project/Live modules remain large
orchestrators. This correction adds only public read-only lifecycle/checkpoint
projections so Live no longer reaches into Project process/checkpoint internals;
splitting those monoliths is deferred to a separately reviewed refactor.

Reproduction uses the repository virtual environment:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_phase11_local_project_audit_v1.py tests\test_phase11_windows_namespace_v1.py tests\test_phase11_windows_clone_cleanup_v1.py tests\test_phase11_handle_patch_v1.py tests\test_phase11_project_autopilot_v1.py tests\test_phase11_live_mission_v1.py tests\test_missions.py tests\test_capability_nexus_v15.py tests\test_approval_inbox_v15.py tests\test_approval_inbox_v15_acceptance.py tests\test_onyx_live_activation_v15.py -q
.venv\Scripts\python.exe -m pytest tests\test_package_hygiene_v1.py tests\test_packaging_paths.py -q
```
