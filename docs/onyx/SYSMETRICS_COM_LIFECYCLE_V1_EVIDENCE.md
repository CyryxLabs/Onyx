# System metrics COM lifecycle correction

Date: 2026-09-05. Parent story:
`docs/stories/ONYX-AGENT-EMPLOYEE-TWO-SPRINTS-V1.story.md`.
The user explicitly authorized only `_SysMetrics`, its UI lifecycle hooks, a
dedicated test and separate documentation. Parent retains story and successor
hash/manifest ownership. No manifests were regenerated here.

## Defect and correction

The preceding read-only investigation reproduced the exact pywin32 warning
`Win32 exception occurred releasing IUnknown` in 3/3 processes importing WMI
on a short-lived worker thread, and in 2/2 processes importing UI then joining
its metrics thread. All exited 0. Main-thread WMI imports were clean. WMI 1.5.1
creates global COM proxies while importing; UI previously triggered that import
from a daemon thread launched at module scope. Installed runtime: Python 3.13,
pywin32 312. The warning text was located in `pythoncom313.dll`.

`_SysMetrics` construction is now inert. `MainWindow` starts it explicitly, with
an owned thread handle and idempotent start/stop operations. Snapshot keys and
sampling cadence remain unchanged; a restarted worker takes a fresh sample.
Only the main thread may start the sampler. Optional pywin32 imports happen
there, so pythoncom's import-time initialization belongs to that owner thread.

Each worker explicitly enters an MTA apartment using `CoInitializeEx` and balances
it with `CoUninitialize` in `finally`. Temperature queries use existing pywin32
`GetObject`/`ExecQuery` interfaces directly. They do not import the WMI package
or create its module-global proxies. Query/result/row proxies are released in
the creating thread before apartment teardown. If COM cannot initialize, WMI
queries are not attempted; CPU, RAM and network collection continue.

An interruptible event replaces the polling sleep. Both accepted window close
and QApplication `aboutToQuit` request a stop and join for at most two seconds
per hook. Resident close-to-background keeps sampling. A timed-out native query
returns a failed stop and emits a diagnostic; it cannot create a duplicate worker
or claim successful cleanup. The daemon is not forcibly killed. A genuinely
blocked native API remains a bounded-shutdown limitation.

No warning filters, stderr suppression, fake temperature values or manual COM
reference-count manipulations were added. Missing thermal hardware still returns
the existing unavailable value (-1); this is not a temperature-sensor qualification.

## Verification

`tests/test_sysmetrics_com_lifecycle_v1.py` launches fresh Python processes with
temporary data paths and offscreen Qt. It verifies:

1. Importing the real host starts no metrics thread and imports no WMI package.
2. Two real Windows COM sampling cycles connect on the worker, balance init/uninit
   on that same thread, restore the native interface count to baseline, update RAM
   metrics, and exit without IUnknown warnings.
3. A deliberately blocked sample obeys a 50 ms stop budget, prevents duplicate
   starts, and joins successfully after release. This is fault injection only;
   the real COM test forwards initialization and queries to Windows.
4. Constructing the actual MainWindow starts sampling; actual Qt aboutToQuit
   stops it. No voice runtime or external account is started.
5. Resident close preserves the worker; accepted close stops it.

Final focused regression command (use a fresh empty/nonexistent basetemp path):

```powershell
python -B -m pytest --noconftest --basetemp <unique-temp-path> tests/test_sysmetrics_com_lifecycle_v1.py tests/test_missions.py tests/test_runtime_shutdown_hardening_v1.py tests/test_governed_shutdown_v35.py tests/test_humanoid_transparency_v1.py -q
python -m ruff check ui.py tests/test_sysmetrics_com_lifecycle_v1.py
```

Result: **87 passed, 47 subtests passed in 19.36 s**, exit 0; Ruff passed.
This includes the five dedicated tests, 63 mission tests, shutdown regressions
and desktop/mobile humanoid transparency checks. The initial regression attempt
had 84 passes and two fixture setup errors because the default pytest temp root
denied access; the exclusive basetemp rerun passed all tests.

`npm run lint`, `npm run typecheck`, and `npm test` were attempted and each returned
ENOENT: this Python snapshot has no package.json. No full-suite, typecheck,
packaged-release or live-device certification is claimed. Git status/log report
that the assigned snapshot is not a Git repository; no commit was made.

## IDS and self-review

Search inspected existing metrics implementation, MainWindow/OnyxUI close and
aboutToQuit hooks, shutdown tests, subprocess-test patterns and squad references.

| File | Decision | Rationale |
| --- | --- | --- |
| `ui.py` | ADAPT | Reuse the existing sampler and shutdown paths, retaining the snapshot interface and UI behavior. |
| `tests/test_sysmetrics_com_lifecycle_v1.py` | CREATE | Dedicated subprocess COM/thread/Qt proof was missing; adapt existing unittest isolation patterns. |
| `docs/onyx/SYSMETRICS_COM_LIFECYCLE_V1_EVIDENCE.md` | CREATE | Separate evidence avoids changing parent-owned story or frozen manifests. |

[AUTO-DECISION] Use pywin32 directly instead of preloading WMI: removes the demonstrated
global-proxy lifetime defect and needs no new dependency. Preloading WMI alone
previously left other threads uninitialized for COM.

Step 5.5 review addressed three risks: releasing proxies after uninitialization,
duplicate workers while a previous sample is blocked, and import-time sampling
in unrelated tests. Edge cases: resident close, unavailable temperature provider,
and stop timeout. Thread ownership and balanced teardown are explicit; the timeout
is observable. Test children are bounded and failures preserve stdout/stderr.

Step 6.5 review: real COM calls were forwarded unchanged; interface counts returned
to baseline, both Qt exit paths were exercised, regression passed, and Ruff is clean.
No design, voice, HUD selection, QML, release/package/acceptance artifacts or
manifests were edited by this change. The aexos-dev workflow supplied IDS and
self-review; full story DoD and successor artifact rebinding remain parent-owned.
