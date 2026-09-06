# Onyx 1.1.9 V14 compliance technical checkpoint

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V14 historical
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md) for
> the current compliance boundary.

Status: **technical packaging passed; qualified legal approval remains open**  
Date: 2026-08-03  
Platform/artifact set: Windows x64 V14 candidate

This checkpoint proves which compliance materials are bound into the exact
Windows artifacts. It does not interpret licenses, accept terms or replace the
blank approval record in `../LEGAL_RELEASE_APPROVAL_1.1.9.md`.

## Exact artifact binding

- Artifact-set root SHA-256:
  `51fa86b4b033920084f5cc0f06efcc8f9aaadade0464434a5388d2bb10e92484`
- Setup SHA-256:
  `e120fbdc5b97afc25494ae71e2ccb6a5d74a807765dc384b5a5a9f9c940c3068`
- Portable SHA-256:
  `253376942110ea18084d6de73879b88e2386262a4b8b1d8562dd5a91693cf07e`
- Release-manifest SHA-256:
  `9255dcec35f6f6acba415da39534fa60f7f120b231ed5bcedadfc01db51dedf4`
- Bundle-inventory SHA-256:
  `a48b276aea1d07ef854b6ad7b848f82db13b021eb1e2b55c0962cf59d48d3b02`
- Bundle root SHA-256:
  `70185def87bb07c5520ed9800491d2b23c08f1b86bb66cb659b05a9271deef8a`
- Locked requirements SHA-256:
  `9b49382b5f5bfb2ff146a97ec00adf26faafe5dd358bc30f52a2d7cf04bc6b0f`

## Shipped compliance materials

The 6,782-file bundle inventory and installed copy contain:

| Material | Installed/bundled path | SHA-256 or evidence |
|---|---|---|
| Cyryx product license | `LICENSE.txt` | `e045278221225c8f0ef82a4332770b6ecb1dcc96bbefc64e976c9cc15e8b7d95` |
| Third-party notices | `THIRD_PARTY_NOTICES.md` | `243f61c7bf0681aa29781cfabdd89a56aff6f0af39e4bfe57b7da9a674d4c76c` |
| LGPL 3.0 text | `THIRD_PARTY_LICENSES/LGPL-3.0.txt` | `e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118` |
| CryptoJS license | `_internal/dashboard/static/crypto-js.LICENSE.txt` | Present in inventory |
| CryptoJS provenance | `_internal/dashboard/static/crypto-js.PROVENANCE.json` | Pins CryptoJS 4.2.0 and vendored SHA-256 `769a555de553babc35a3338f344dd7aa16260c93cea2c7db290707c90484e7cc` |
| Playwright license | `_internal/playwright/driver/package/LICENSE` | Present in inventory |
| Playwright notice | `_internal/playwright/driver/package/NOTICE` | Present in inventory |
| Playwright third-party notices | `_internal/playwright/driver/package/ThirdPartyNotices.txt` | Present in inventory |
| CPython launcher license | `_internal/.venv/PSF-LICENSE.txt` | Present in inventory |
| Python package licenses | `_internal/*.dist-info/licenses/*` and upstream equivalents | Preserved where supplied by each distribution |

The Qt/PySide6 shared libraries remain separate dynamically loaded files in
the payload. The notice names the exact PySide6 6.11.1 source locations and
states the recipient replacement/relinking boundary.

## Technical SBOM result

- `release/SBOM.spdx.json` SHA-256:
  `d56839b0efaa95b834d494ca0f425881c46a4552cb1de6140836507d2c14f4e6`
- 141 packages, 6,784 file entries, 6,924 relationships and two release
  artifacts.
- Release eligibility: 21 passed, 1 platform skip.
- Direct eligibility reconciliation: zero technical errors; eight expected
  formal trust/signature/receipt errors remain.

Every one of the 141 package records currently uses SPDX
`licenseDeclared: NOASSERTION` and `licenseConcluded: NOASSERTION`. The SBOM is
therefore an exact technical inventory, not an automated license-policy
decision and not proof that all obligations were legally accepted.

## Closing evidence still required

1. A qualified approver completes every field in
   `../LEGAL_RELEASE_APPROVAL_1.1.9.md` against the hashes above.
2. The executed upstream commercial-rights agreement referenced by the dated
   historical review is attached through a durable, access-controlled
   reference.
3. The approver records the accepted Qt/PySide6 distribution posture and any
   corresponding-source/source-offer process required for each platform.
4. Each future Windows, Linux or macOS artifact receives a fresh artifact-bound
   SBOM, notice check and platform-specific approval; this Windows result must
   not be transferred by filename or version alone.

Until those items close, the engineering state is
`PASSED_TECHNICAL_CURRENT` and the release state remains
`OWNER_OR_LEGAL_APPROVAL_REQUIRED`.
