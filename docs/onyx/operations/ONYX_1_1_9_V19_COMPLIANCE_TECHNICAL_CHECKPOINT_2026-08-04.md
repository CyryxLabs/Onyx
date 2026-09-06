# Onyx 1.1.9 V19 compliance technical checkpoint

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V19 historical
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md) for
> the current compliance boundary.

Status: **TECHNICAL PACKAGING PASSED — LEGAL APPROVAL REQUIRED**  
Date: 2026-08-04  
Platform/artifact set: Windows x64 V19 candidate

This checkpoint binds the technical compliance inventory to the exact V19
artifacts. It does not interpret licenses, accept terms or complete
`../LEGAL_RELEASE_APPROVAL_1.1.9.md`.

## Exact artifact binding

| Identity | SHA-256 or count |
|---|---|
| Artifact-set root | `90ac958ebcc22e7abb1ecce0b87f24aef81e6e65315a1c1692bdc199eda15cf4` |
| Setup | `5b43c377209dfae92ce9177f9da3b1c46bc875bec344e8183930421c73d1eb73` |
| Portable | `6e355bccda2a64ca7c2ccfb1e1881c269b6585f551f6ecc59ac8d224d293763b` |
| Release manifest | `cab810c1380a7a996ada2b09675f478a5a631a8db1a15d85615b8cf8ffb43d97` |
| Bundle inventory | `9b14a267d6caed340005b3321a5b7e6428a31d4e01d9759d99c968deb839a60f` |
| Bundle root | `46bb6a8df8fce06bf31bdcde3b932c92462fde946309b20340b15469879dd15b` |
| Bundle files | 7,288 |
| Runtime distributions | 95 |
| Runtime-distribution root | `6524a84b48a81bb1eb138b815d995041854066ac8461c327f8fb09dc3982ec7e` |

## Shipped compliance materials

The exact installed copy matches the bundle inventory and contains:

| Material | Installed path | SHA-256/evidence |
|---|---|---|
| Cyryx product license | `LICENSE.txt` | `e045278221225c8f0ef82a4332770b6ecb1dcc96bbefc64e976c9cc15e8b7d95` |
| Third-party notices | `THIRD_PARTY_NOTICES.md` | `243f61c7bf0681aa29781cfabdd89a56aff6f0af39e4bfe57b7da9a674d4c76c` |
| LGPL 3.0 reference | `THIRD_PARTY_LICENSES/LGPL-3.0.txt` | `e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118` |
| primp native graph | primp distribution notice and hash-pinned crate inventory | 237 graph packages, 435 legal files, two package-local gaps retained |
| Missing-distribution supplements | odfpy, WMI, PyGetWindow and win10toast distribution notices | Exact PyPI artifacts and labelled supplements retained as technical evidence |

The V19 inventory recognizes both `LICENSE` and `LICENCE`. All 95 runtime
distributions have at least one recorded legal-evidence file, so the syntactic
missing-file count is zero. Four distributions still declare `NOASSERTION`, 25
metadata declarations remain non-canonical, four supplemental-license issues
need substantive disposition, and two primp graph rows lack package-local legal
bytes. Those are legal-review items, not packaging omissions.

## Technical SBOM result

- `release/SBOM.spdx.json` SHA-256:
  `c905de094eed10041923ba8b89b0a7490ebfe260a57847d815fba466c372dab7`.
- Artifact-set root embedded in the SPDX technical inventory:
  `90ac958ebcc22e7abb1ecce0b87f24aef81e6e65315a1c1692bdc199eda15cf4`.
- 141 packages, 7,290 file entries, 7,430 relationships and two release
  artifacts.
- The focused eligibility/distribution/primp/supplement/hygiene selection
  passed 49 tests with one expected native-platform skip.

Every package record deliberately retains `licenseDeclared: NOASSERTION` and
`licenseConcluded: NOASSERTION` at the SPDX policy layer. The SBOM is therefore
an exact technical inventory, not automated legal approval.

## Remaining approval boundary

1. Resolve the four `NOASSERTION` and 25 non-canonical metadata declarations
   using authoritative, version-bound evidence.
2. Decide the odfpy licensing posture, WMI permission text, PyGetWindow
   release binding and win10toast BSD/MIT conflict.
3. Dispose the two package-local primp graph gaps and document all required
   binary-distribution obligations.
4. Approve the Cyryx license, notices and final platform-specific materials in
   the blank durable approval record.
5. Repeat artifact-bound reconciliation for future native macOS/Linux packages;
   this Windows result does not transfer across platforms.

Until those items close, engineering remains `PASSED_TECHNICAL_CURRENT` and
release approval remains `OWNER_OR_LEGAL_APPROVAL_REQUIRED`.
