# CORRECTION — Phase 10 provider-connector module drifted after acceptance

- Correction ID: `CORRECTION-P10-PROVIDER-CONNECTOR-POST-ACCEPTANCE-DRIFT`
- Discovered: 2026-08-17, by the Guild Profiles V1 candidate chain
  (`scripts/verify_guild_profiles_v1.py`), whose recursive predecessor
  reproduction executed `verify_phase10_provider_connector_v1.py` for the
  first time since early August and failed closed with `artifact hash drift`.
- Session: owner-authorized autonomous session (@devops), R15B soak night.

## Facts

1. `core/phase10_provider_connector_v1.py` was **edited after its E6
   acceptance** (`VE-P10-PROVIDER-CONNECTOR-V1-E6-001`, 2026-07-25):
   - Accepted: 15,892 bytes, SHA-256
     `b14688183628…` (full value in the slice-3 checkpoint manifest).
   - Current: 15,989 bytes, SHA-256
     `327f7d949ae764b6e3353e258500bc4a3ccc9f2bc87637f27b12bdbff71cb588`.
2. The other seven slice-3 candidate artifacts (tests, verifier, ADR,
   sources, checkpoint, delta, cumulative selection) recompute **exactly**;
   the slice-4 (content draft) eight-artifact closure recomputes exactly.
3. Bisect across dated candidate trees: every tree from
   `Onyx-V34-Windows-Candidate-20260810` through
   `Onyx-V53-Source-Candidate-R15B-20260811` carries the current bytes;
   pre-V34 dated trees do not contain the file. The drift window is
   therefore 2026-07-25 → 2026-08-10, and the **released 1.1.9 R15B frozen
   source contains the current bytes** (they passed the release-era global
   selections, SBOM reconciliation and the V53 source freeze).
4. The accepted 2026-07-25 bytes are **not recoverable locally**: absent
   from the git initial commit (2026-07-24, pre-slice), absent from every
   surveyed candidate tree; no diff against the accepted version can be
   produced. The editing session and rationale are undocumented.
5. Slice-3's own test file passes against the current bytes (reproduced in
   the successor verification, 32 passed).

## Disposition (forward-only; no accepted byte is rewritten)

- The historical acceptance `VE-P10-PROVIDER-CONNECTOR-V1-E6-001` remains
  valid **for its date and its recorded bytes**. Its verifier chain fails
  closed against the current tree **as designed**; that behaviour is
  correct and is retained as the historical record.
- A **current source-integrity successor** (precedent: Capability Nexus
  V32 → current successor) now binds the current bytes:
  `VE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001` with candidate root
  `90139dd8b2856a6d778356b64a747d851e5320afe2241401b7150cf9499d9054`
  (verifier: `scripts/verify_phase10_provider_connector_current_v1.py`).
- Downstream chains (content draft onward, Guild slices) reproduce
  predecessors through the successor path
  (`scripts/verify_phase10_content_draft_current_v1_acceptance.py`);
  the slice-4 artifact root `59308ada…` is unchanged.
- Post-acceptance edits to accepted artifacts remain prohibited; this
  correction documents an already-shipped deviation, it does not license
  future ones. The capability matrix row keeps citing the historical
  acceptance plus this correction and the successor.

## Honesty boundary

The successor verification passes were executed autonomously in the
owner-authorized session that discovered the drift. No independent human
review of the successor occurred; the historical E6's three-review record
is not inherited by the successor and is not claimed.
