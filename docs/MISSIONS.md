# Onyx governed mission worker

Onyx can execute approved, provider-free local missions in the background while
the desktop application is open. This is an application-owned worker thread, not
an operating-system daemon or unattended service.

## Lifecycle and queue behavior

- `mission_create` validates a fixed ordered plan and leaves it awaiting approval.
- `mission_run` obtains the trusted plan approval when needed, changes the mission
  to `running`, queues it, and returns without waiting for execution.
- The application worker claims only `running` missions through
  `MissionStore.claim_next`. Draft, awaiting-approval, waiting, paused, completed,
  failed, and cancelled missions cannot be claimed.
- A single-owner expiring lease and heartbeat prevent simultaneous execution.
- On clean shutdown, the worker stops polling and releases its active lease after
  the bounded local step returns. If the process disappears during a step, the
  next worker moves that step to `waiting` for explicit outcome confirmation; it
  does not replay the step automatically.

The foreground CLI remains available for diagnostics and controlled operation:

```bash
python -m core.missions worker --once
python -m core.missions worker --poll 2
```

## Result contract

Persisted step results use this redacted, bounded structure:

```json
{
  "status": "succeeded | failed | waiting",
  "data": {},
  "evidence": [],
  "postconditions": [
    {"name": "deterministic_check", "satisfied": true}
  ],
  "waiting_for": null
}
```

Plain or legacy runner values fail closed to `waiting`; completion alone is not
proof of an outcome. Every built-in provider-free tool emits an explicit
tool-specific deterministic postcondition. Existing local citations, paths,
hashes, and observed status fields are retained as data/evidence without
inventing additional provenance. A structured success must include at least one valid
postcondition and every postcondition must be satisfied. Malformed results,
unknown outcomes, and unsatisfied postconditions transition to `waiting`.
A structured failure fails once and is not treated as a transient exception.

All result fields are redacted before persistence. Evidence is provenance for the
owner to inspect; it is not interpreted as trusted instructions.

Pause and cancellation are atomic with result commit. Cancelling an active step
marks it skipped with a redacted discarded-outcome record; a late runner result
cannot mutate it. Pausing an active step moves it and the mission to `waiting`
because its outcome is unknown. The owner must explicitly resolve that step as
`succeeded`, `retry`, or `failed` before execution can continue.

## Security boundary

Mission approval is not a blanket tool grant. Every step is checked again by the
central mission permission policy immediately before execution. The worker does
not query or mutate SQLite directly, expand workspace roots, introduce shell
execution, grant a session permission, or add network/provider tools. Currently
supported mission tools remain the explicit provider-free local set reported by:

```bash
python -m core.missions doctor
```
