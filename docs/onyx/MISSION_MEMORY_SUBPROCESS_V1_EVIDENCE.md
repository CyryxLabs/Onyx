# Mission and memory subprocess evidence

Date: 2026-09-05. Scope: delegated local validation for
`docs/stories/ONYX-AGENT-EMPLOYEE-TWO-SPRINTS-V1.story.md`.
This is engineering evidence, not a release or acceptance manifest.

## Result

Two new process-boundary tests pass. No production defect was demonstrated by
these scenarios, so `memory/*` and `core/missions.py` required no changes.

The first test imports an actual temporary legacy JSON file into MemoryStore.
A new process retrieves the remembered filename and uses it in a deterministic
two-step MissionStore plan: read that file, then hash the path returned by step 0.
The test approves only that exact local plan through the existing permission
callback, returning the broker's nonce-bound request digest.

MissionWorker executes the real workspace tools. The child calls `os._exit(73)`
after computing the hash but before returning its result. Another process observes
the committed read and the interrupted hash. A fresh worker waits for the real
five-second lease expiry, then records `step.recovery_wait` without calling a tool.
The actual mission CLI reports idle while resolution is pending. Explicit CLI
`resolve ... retry` permits another worker process to complete only the hash.
Read/hash attempts are exactly 1/2. Stored text, citation and SHA-256 match the
temporary artifact. A subsequent CLI worker is idle and leaves events unchanged.

After verified completion, explicit `record_episode` capture stores task/session
provenance and the observed artifact digest. Another process retrieves those fields
and framed, bounded context through the same memory-manager APIs used by the host.

The second test proves legacy import idempotency across processes, source-token
and citation preservation, source-file preservation, CLI retrieval, privacy-off
write rejection, and durable forgetting. Re-running the completed migration does
not resurrect the forgotten record.

## Reproduction and results

Run from `C:\MAAX_Assistant\Onyx-Remediation-Clean-20260823-151210`:

```powershell
python -m unittest discover -s tests -p test_mission_memory_subprocess_v1.py -v
python -m pytest --noconftest tests/test_mission_memory_subprocess_v1.py tests/test_memory_store.py tests/test_missions.py tests/test_mission_tools.py -q
python -m ruff check tests/test_mission_memory_subprocess_v1.py
```

- New unittest suite: 2 passed in 8.226 seconds, exit 0.
- Focused pytest regression: 95 passed, 62 subtests passed in 32.85 seconds, exit 0.
- Ruff: all checks passed, exit 0.
- Required `npm run lint`, `npm run typecheck`, and `npm test` were attempted;
  each failed with ENOENT because this Python snapshot has no `package.json`.
  No typecheck or full-repository test pass is claimed.
- `git status --short` and `git log --oneline -5` report that this snapshot is
  not a Git repository. No commit was created.

Initial test development exposed two fixture errors, both corrected: the plan
digest is not the nonce-bound approval-request digest, and Windows text writing
changes LF bytes unless the fixture writes explicit UTF-8 bytes. Neither was a
production defect.

## Limits

No fake model response or success result is used. The deterministic test consumer
connects memory retrieval to mission creation; this does not prove natural-language
planning, provider quality, or automatic mission-to-memory wiring in `main.py`.
Episode capture is explicit. The process crash is a Python worker crash, not a
native application restart or execution while the machine is off.

Ingestion here means the existing legacy JSON importer and real workspace text
read/hash. It does not qualify document-intake activation, PDF/OCR, web ingestion,
or the gated Phase 7/9 subsystems. Stored provenance is checked against the input;
legacy citations are not cryptographic certification of a source document.

All generated artifacts, child data directories and SQLite stores are temporary
and cleaned by unittest. Workspace tools are read-only and provider-free. No live
account operations are performed. UI, QML, release/package/acceptance files,
Google activation, and the parent-owned story were not edited by this task.

## Implementation decisions and self-review

IDS search covered existing mission/memory tests, subprocess/restart tests,
workspace tool implementations, memory-manager callers, and squad references.

| File | Decision | Reason |
| --- | --- | --- |
| `tests/test_mission_memory_subprocess_v1.py` | CREATE, adapting existing unittest/API patterns | Existing restart tests reopened stores within one process; this test owns isolated child lifecycles, actual abrupt exit, CLI resolution and memory retrieval. |
| `docs/onyx/MISSION_MEMORY_SUBPROCESS_V1_EVIDENCE.md` | CREATE | Separate bounded evidence and implementation log; parent owns the story and immutable acceptance artifacts. |

[AUTO-DECISION] Workflow mode -> YOLO, as authorized. Use standard-library unittest,
subprocess and temporary directories; no added dependencies.

[AUTO-DECISION] Checklist/log destination -> this separate evidence document,
because the delegated scope permits evidence and explicitly reserves story edits
for the parent. Parent may add the two files to the story's file list.

The aexos-dev workflow supplied the IDS decision log and two self-critique
checkpoints. Requested legacy `.Codex/commands/AEXOS/agents/dev.md` was absent;
the canonical parent `.aexos-core/development/agents/dev.md` was used. Parent
constitution, technical preferences and core config were read. Configured
`docs/framework/*` standards and pt/es fallback directories, and gotchas JSON,
were unavailable in the inspected workspace locations.

Step 5.5 considered: accidental default-store access (explicit child database and
data paths); replay after crash (assert zero recovery calls and exact attempts);
hang/leaked child (subprocess deadline and bounded worker shutdown). Edge cases:
Unicode/newline artifact bytes, uncertain in-flight result, and privacy/forget
state across restart. Errors include captured stdout/stderr; approval is scoped
to the test plan; no network tools or credentials are used.

Step 6.5: existing public interfaces reused, no dependencies or production API
changes, meaningful tests and failure diagnostics present, Ruff clean, temporary
resources cleaned, and proof limits documented. Test timing constants are named
and bounded. Full story DoD remains with the parent: local delegated tests and
documentation are complete; UI/live/provider/release criteria, full suite and npm
gates are not certified by this evidence.
