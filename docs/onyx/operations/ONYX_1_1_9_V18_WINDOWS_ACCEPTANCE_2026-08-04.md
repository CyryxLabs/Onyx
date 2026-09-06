# Onyx 1.1.9 V18 Windows installed acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V18 historical
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Date: 2026-08-04  
Platform: Windows x64  
Activation: V21  
Source successor: V18  
Status: **PASSED LOCAL INSTALLED ACCEPTANCE — FORMAL RELEASE GATES OPEN**

## Candidate identity

- Phase 5 V18 transition SHA-256:
  `d8f16a1ec8c239693f0c3fbecc234f09f499f2a6004df053d846af2dadaa4179`.
- Phase 5 V18 domain root:
  `19df4b7f8465232f4b99180fda5ba51c711e08343ca7c07bcf82792f176aeecb`.
- Advanced Operations V16 evidence SHA-256:
  `3a96e8da840ad54cb510738061fee7edf62091135181af5b2607de5cfa8165fe`;
  71-file root
  `da882846696ef0d09ebf2fde60219c470f5bb5968f410b6b62447f37830f8a2f`.
- Release Workflow V4 transition SHA-256:
  `bec9658f723fc467d888b311780d013689f6a6ac09cda58ec01827c96b60f12d`;
  root `690da4e1f7fd0cd5cdb7bb8f911f140fe3e1a6ccda6b1048ac999f5f56fb1a48`.
- First-party input seal: 1,305 files; root
  `c0f9bd58521ea8cdceba347a96664b75b421d8f6234b37f4038ebd7074092d88`.
- Input-manifest SHA-256:
  `c48f50099ff057553d66417b221ef2590ac2f805169ec24b0f85acbd02b528b6`.

## Artifacts and inventory

- Setup SHA-256:
  `4cd0bd2251c48aca216767b9081e86373e95bb1f81e80997eff87c18721dd22d`;
  484,927,471 bytes.
- Portable SHA-256:
  `4f3a4fa5b8913555e2456be9336bed3177664799642fc11952ad7b4287b9262e`;
  550,573,083 bytes.
- Release-manifest SHA-256:
  `ca9b1afd61daaea97c07e73dd912471bc8b10dc0f3b0b3a867edf254ae61cf5b`.
- Bundle-inventory SHA-256:
  `59ba41dc6974274b6c025f9d51fea320048c736ca722bde4d72e1abe9641976f`.
- Bundle root:
  `2d422f2e7f2fc951d388d36b2b5e411e7512c56d65028a0367aff7b70ab1f839`.
- Runtime distributions: 95; distribution root
  `6524a84b48a81bb1eb138b815d995041854066ac8461c327f8fb09dc3982ec7e`.
- Setup exit: 0.
- Exact installed comparison: 7,288 expected; 0 missing; 0 mismatched;
  0 non-uninstaller extras.

## Source, packaged and installed gates

The daily-rhythm focused selection passed 39 tests. The 31-suite integrated
selection passed 223 tests and the unchanged V12-to-V21 activation chain
passed 136. Ruff passed on all changed core and test files.

The clean, hash-locked build completed in 1,091.9 seconds. Package, fallback
and V21 preflight, native startup, Governance V16, Founder V17, Document
Intake V18.1, DayOps V20, Advanced Operations V20 and Advanced Commands V21
smokes passed both in the generated bundle and in the installed executable.

The technical SPDX inventory generated from the exact final artifacts passed.
`release/SBOM.spdx.json` has SHA-256
`63e9539a8b27176cf16a707ccc5714e00fcd2fd4064b5afafe79892c9d0c9e63`.

## Daily rhythm and HUD gate

The installed `OperationalRhythmV1`, Advanced Operations composition,
controller and `ui.py` are byte-identical to the accepted source. The running
HUD exposed one `OPERATIONS` pill, reported `OPERATIONS / READY` and listed
`operational_rhythm` among its capabilities. The owner profile currently has
no operational goals, so the projection correctly emitted no invented focus
or action items.

The rhythm is deterministic and owner/workspace scoped. It performs zero goal
mutations, model scoring, external dispatch, polling and background work.

## Real voice and short runtime gate

The real installed V18 window opened and remained responsive. The new V21 log
session beginning `2026-08-04T06:05:14.023352+00:00` recorded connection to
Gemini Native Audio plus microphone start/open, receive start and playback
start. No system-voice fallback was selected.

With the Operations panel visible, six samples over 50 seconds were all
responsive. Average main-process CPU normalized across the whole host was
0.523990%; maximum working set was 423,841,792 bytes and maximum private memory
was 1,160,450,048 bytes. This is short acceptance, not the required eight-hour
receipt.

## Boundary

This record proves a local unsigned Windows candidate. It does not close owner
acoustic/name-change acceptance, the eight-hour receipt, live Microsoft Graph,
trusted Authenticode, clean-machine lifecycle, macOS/Linux native evidence,
legal approval or independent final review.
