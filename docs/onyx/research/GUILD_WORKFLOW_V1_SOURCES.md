# Guild workflow V1 — sources and design basis

Hermetic, deterministic workflow-template and run-projection contract. No
external service is used; the basis is first-party AEXOS workflow data and
the accepted A9.1/A9.2 guild slices.

## AEXOS basis (first-party, `CyryxLabs/aexos-engine`)

- Workflow definitions: `development/workflows/*.yaml` (15 surveyed
  2026-08-17), canonically `story-development-cycle.yaml` — the SDC phases
  create → validate → implement → QA gate. Templates are ingested as
  byte-pinned data (source bytes + SHA-256), never restated as constants
  (Constitution Article IV, No Invention).
- Task-first principle (workflow-execution rules): workflows are composed
  of tasks/stages with defined executors — encoded as per-stage
  `required_operation` bound to registry authority rather than hard-coded
  agent names.
- Story lifecycle: stage completion maps onto the accepted A9.2 lifecycle
  (`approved`/`in_progress`/`in_review`/`done`), strictly progressing and
  ending at `done`.

## Design decisions

- **Stage/authority coupling** — an assignee must hold the stage's required
  operation under the accepted A9.1 registry, exclusive owner sets
  respected; authority is never redeclared here.
- **Exact-prefix runs** — completed stages replay the template in order;
  skips, reorders and overruns reject.
- **Run/story coupling** — the A9.2 story status must equal the last
  completed stage's declared completion status (`draft` when none).
- **Entry-bound** — construction denied unless the A9.2 four-file
  acceptance tuple is byte-exact.
- **No execution surface** — dispatch belongs to A9.4, separately gated.
