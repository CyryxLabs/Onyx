# Phase 7 Layered Memory V1 checkpoint

## Scope

This candidate implements the seven-layer lifecycle and governance slice over
the accepted Workspace Memory V1 root. It is exactly default-off and preserves
the accepted legacy-memory adapter without modification.

## Implemented contract

- session working, episodic mission, semantic institutional, decision,
  procedural, preference and temporal status layers;
- workspace/principal/key/connection binding with HMAC read-back verification;
- normalized content deduplication and stable explicit entity resolution;
- atomic correction and supersession plus preserved contradiction links;
- candidate, approved, rejected, superseded, corrected and deleted lifecycle;
- source, sensitivity, confidence, validity, freshness and retention metadata;
- hard authorization/lifecycle/freshness filters before lexical ranking;
- deterministic scoped export with integrity-key material removed;
- principal deletion, retention enforcement and source-deletion tombstones;
- content scrubbing of text, source IDs, tags and entity labels;
- prompt-injection signals, size bounds and secret-pattern rejection;
- content permanently marked untrusted with no instruction authority;
- zero global vector index, network, process, provider, model, browser, action,
  UI, dashboard or live-runtime call.

## Compatibility

Successor rows use a distinct `lmem_` ID and never use the predecessor's
`active` status. An explicit integration test inserts both record types and
proves Workspace Memory V1 still retrieves only its accepted legacy record.

## Proportional regression result

Nine fresh Python processes reproduced:

- 161 passed tests;
- 77 passed subtests;
- 0 failed;
- 0 errors;
- 1 explained platform skip.

The skip is limited to a POSIX file-mode assertion unavailable on Windows.
Windows-specific control-plane paths passed.

Ruff and Black checks passed. Strict type analysis reports no error in the new
module; pre-existing dependency diagnostics remain outside this candidate.

## Limits

The candidate is not live-wired. It accepts explicit typed entity keys and
relations; general NLP entity extraction is reserved for the governed
document-intake slice. It does not replace the legacy MemoryStore or claim
Phase 7 exit. Governed multi-format document ingestion and granular citations
remain pending.

E6 remains pending until an independent acceptance envelope rehashes this
candidate and reproduces the frozen selection.
