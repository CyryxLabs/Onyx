# Onyx final evidence independent-review protocol

Status: required closing protocol for the 1.1.9 release candidate. The same
protocol remains applicable to the preserved 1.1.8 predecessor evidence.

This protocol is not itself review evidence. Until the final frozen artifact
set exists and a qualifying independent reviewer completes the disposition
record, the state remains `REVIEW_REQUIRED`.

## Reviewer independence

The reviewer must not be the person or agent that produced the final artifact
set. The reviewer may be a Cyryx-authorized human or a separately tasked AI
with read-only access to the frozen evidence bundle. The review records the
reviewer's identity, date, input hashes, findings and disposition.

## Required review inputs

- final per-platform release manifests and checksum files;
- artifact-bound SPDX SBOM and its digest;
- exact source/build-input seals;
- native build and entrypoint logs;
- clean install, upgrade, uninstall and rollback evidence;
- Windows long-session metrics;
- physical voice, name-persistence and Orb acceptance;
- live Microsoft Graph receipts;
- Windows signature and macOS signing/notarization evidence;
- final product-license and third-party-notice approval record;
- current documentation index and release-status record.

## Required checks

1. Recompute every published SHA-256 and reject missing or extra artifacts.
2. Verify every SBOM artifact record against the final manifests and archive
   member inventories.
3. Verify the tested artifact hashes are the same hashes presented for release.
4. Verify platform claims are supported by native-host evidence for the exact
   architecture.
5. Verify unresolved, skipped or human-only gates are not represented as passed.
6. Verify historical evidence IDs were not rebound to newer bytes.
7. Verify the release-status document and installation guide match the final
   version and supported-platform evidence.

## Disposition record

The final index is accepted only when the reviewer supplies all fields:

- Reviewer:
- Independence basis:
- Reviewed at (UTC):
- Evidence-index SHA-256:
- Artifact-set root SHA-256:
- Findings:
- Disposition: `ACCEPTED` or `REJECTED`
- Signature or durable approval reference:

Blank fields mean `REVIEW_REQUIRED`; they never imply approval.

## Publication workflow binding

The automated publication gate additionally requires:

- `lifecycle-evidence-Windows-x64.json`;
- `lifecycle-evidence-Darwin-arm64.json`;
- `lifecycle-evidence-Linux-x64.json`;
- `lifecycle-evidence-Linux-arm64.json`;
- `long-session-evidence-Windows-x64.json`;
- an `onyx-final-qualification-evidence` artifact from the exact native
  qualification run passed as `qualification_run_id`;
- `final-qualification-provenance.json`, binding the exact `build_run_id`,
  qualification run, workflow SHAs, target matrix and release-manifest hashes;
- `ONYX_INDEPENDENT_REVIEW_APPROVED=true` only after the protected
  `onyx-final-evidence-review` environment is configured with an independent
  required reviewer and self-review prevention; the final publication dispatch
  repeats the gate under `onyx-public-release`.

The durable workflow-run URL is the approval reference. The final verifier
rejects a different build or qualification run, missing platform receipt,
non-terminal soak, failed lifecycle sequence, incomplete provenance or any
current-artifact byte/hash mismatch.
