# Onyx 1.1.9 V24 compliance technical checkpoint — 2026-08-04

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V24 historical
> evidence. The current technical SBOM identity is in `../CURRENT_RELEASE_STATUS.md`.

Status: **technical reconciliation passed; legal approval absent**.

| Evidence | Exact value |
|---|---|
| Windows artifact count | 2 |
| Artifact-set root | `09a14a4d3c95209cb12a11cc1823560e9f42b7329cb593fa4096442084227e89` |
| Bundle inventory | `68475325291ae6e528846c2b851fdd844120405330bee91c956db99961df039b` |
| Bundle root | `cb9727cc71e48579e718bb93851586aee94a951bc01baac269d8ccb48cbcd4f2` |
| SPDX SBOM | `72de431fcb1c298d55f32c33ca67756a7dca8be407fb6b1e9d0fd6dbd072b4be` |
| Runtime distributions | 95 |
| Runtime-distribution root | `6524a84b48a81bb1eb138b815d995041854066ac8461c327f8fb09dc3982ec7e` |

The V24 SBOM is generated from and embeds the exact final Setup/portable
inventory. Formal eligibility reports no SBOM reconciliation error. It remains
blocked because the Windows candidate is unsigned/untrusted, native trust
receipts are absent, and repository/legal approvals are false.

All 95 Windows runtime distributions have at least one packaged legal-evidence
file. This does not resolve 4 `NOASSERTION` declarations, 25 non-canonical
metadata declarations, four substantive supplemental decisions or two
package-local primp graph gaps. Those items remain in
`THIRD_PARTY_LICENSE_REVIEW_WORKLIST_1.1.9.md`; the blank decision fields in
`LEGAL_RELEASE_APPROVAL_1.1.9.md` are intentional.
