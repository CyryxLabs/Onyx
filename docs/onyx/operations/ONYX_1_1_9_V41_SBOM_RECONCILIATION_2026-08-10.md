# Onyx 1.1.9 V41 SBOM technical reconciliation

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** This remains exact V41 historical
> technical evidence. Use `../CURRENT_RELEASE_STATUS.md` and
> `../DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md`; the R10B technical
> reconciliation does not close the final signed all-platform SBOM gate.

Status: **WINDOWS V41 TECHNICAL RECONCILIATION PASSED; FINAL SHIPPED SET OPEN**  
Candidate: **Onyx 1.1.9 Windows x64 V41 / activation V24**  
Date: 2026-08-10

## Exact Windows evidence

- SPDX document: `release/SBOM.spdx.json`.
- SPDX version: 2.3.
- SHA-256:
  `e396e6df74b390e0893c85516c3eddc4100dfc74b4d4b0d87b42e37cf4147c33`.
- Artifact-set root:
  `0ebc69730c6b5195d110ee249bf5813bfb87da9b83fa628de950bca675c32709`.
- Inventory: 159 packages, 7,471 files and 7,629 relationships.
- Bound artifacts: V41 portable archive with 7,469 members and opaque Setup.
- Bundle-inventory binding: exact.
- Runtime distributions: 112; dependency-lock count: 158.
- Dependency-lock SHA-256:
  `f40c188378f468d692c98d5ceddaa5b1210aea142ddb10305ee9648c5739c5e4`.
- Runtime-distribution root:
  `3972418bc827be9dacc6c4814539899d072704855a123bbf22346b60f0f64815`.

The technical checker emitted no SBOM defect. Its release decision remained
blocked because the candidate is unsigned diagnostic evidence, legal and
repository approvals are absent, and native Windows trust receipts are absent.
Those blockers do not invalidate the Windows inventory reconciliation; they do
prevent a formal/public release decision.

## Legal boundary

The document intentionally records `technicalOnly: true` and
`licenseReviewComplete: false`. All 112 Windows runtime distributions have at
least one packaged legal-evidence file, but six retain `NOASSERTION`:
`colorama` 0.4.6, `importlib_metadata` 8.7.0, `itsdangerous` 2.2.0, `odfpy`
1.4.1, `pdfplumber` 0.11.10 and `pycaw` 20251023.

## Why the final gate remains open

The workflow's global publish job must generate a new SBOM from the final
Windows, Linux and macOS release manifests and exact signed/notarized artifacts.
The current Windows V41 document cannot describe platform-specific Linux or
macOS payloads and cannot bind signatures or notarization tickets that do not
exist. Final reconciliation therefore requires:

1. final native artifacts for every supported target;
2. signed Windows and signed/notarized macOS bytes;
3. one global artifact inventory generated after all signatures are final;
4. resolved notices/license decisions and formal approval;
5. an independent comparison of the SBOM, manifests, package contents and
   published checksums.
