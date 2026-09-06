# Onyx 1.1.9 V44 source freeze

Status: **FROZEN AND SOURCE-VALIDATED; ARTIFACT BUILDS PENDING**  
Date: 2026-08-10  
Candidate: Onyx 1.1.9 V44 cross-platform unsigned diagnostic source

## Exact identity

| Item | Value |
|---|---|
| Source root | `C:/MAAX_Assistant/Onyx-V44-Source-Candidate-20260810` |
| Source manifest | `C:/MAAX_Assistant/Onyx-V44-Source-Candidate-20260810.SOURCE_FREEZE.json` |
| Manifest SHA-256 | `aabba800431f8e3acdbcd0bc6e4ade81578a012b9b86c113c7f1ccb514e46b0a` |
| Files | 2,694 |
| Bytes | 141,166,540 |
| Aggregate root | `257d5afaf8d364117d5c560dd439653eefc57348a0cf4cacf413249d83c44df3` |
| Git trace reference | `355504cb86e97e368dc575f9968ecf4c0fabe994`, branch `master`; dirty state explicitly recorded in the manifest |
| Phase 5 V44 fixture/root | `fac94f38fd08f98e1699b73924c1ead59223228a118b8159152b0b5657942cb2` / `113def6b241d42b654c24714fd6352b44695d57e2a9baf94abb3d87565604785` |
| Release V44 fixture/root | `0d89a2a5eff3a6e0bc155ede25000a331921ae4096f952c3f1c70644e112804d` / `7f9e88230530610675be881d40bf50462917d1bb085ce0fd0517a8ec7fe9e493` |

## Validation

The release-workflow V44 verifier passed inside the frozen tree. The focused
integrated HUD, packaging, mission, monitor, documentation and historical-
retirement suite also passed **211 tests in 114.49 seconds** directly inside
the freeze with an external isolated pytest base directory.

The V44 freeze contains a deterministic 49-blob/26-HEAD-edge historical pack.
The verifier checks the archive and manifest SHA-256 values, every payload
SHA-256, and each recomputed Git blob OID without requiring `.git`.

## Predecessor diagnostics retained

- V42 authenticated its workflow but pytest collection required excluded Git
  objects.
- V43 removed the first Git dependency but exact-snapshot execution exposed
  remaining Phase 5 Exit edges and the omitted `plans/` projection.
- Neither diagnostic freeze is widened into release evidence. V44 is their
  authenticated successor and both directories/manifests remain preserved.

## Boundary

This record proves source identity and the bounded 211-test frozen-source
scope. It does not prove a Windows, Linux or macOS artifact; installed runtime;
signature/notarization; native GUI/audio behavior; lifecycle; legal approval;
final SBOM; long-session pass; or independent release approval.

