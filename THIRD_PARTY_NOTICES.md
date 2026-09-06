# Onyx Third-Party Notices

Copyright (c) 2026 Cyryx Labs LLC. All rights reserved in the original
Cyryx Labs portions of Onyx.

Onyx includes third-party software. Those components are not owned by Cyryx
Labs and remain subject to their respective licenses. This notice is part of
the distributed product and must not be removed.

The exact package versions and artifact hashes for a release are recorded in
the accompanying `SBOM.spdx.json` and release manifests. License files supplied
by Python wheels, Playwright, browser engines, and other packaged components
remain in their original locations inside the application payload.

## Qt for Python / PySide6 and Qt

Onyx uses PySide6, PySide6 Essentials, PySide6 Addons, and shiboken6. The
release lock currently selects version 6.11.1. The packages declare
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; Onyx distributes them under
the LGPL-3.0-only option and does not claim ownership of them.

Qt/PySide shared libraries remain separate dynamically loaded files in the
application's `_internal/PySide6` and `_internal/shiboken6` directories. A
recipient may inspect, replace, and relink compatible library builds. The
corresponding source for the exact Qt for Python release is available from:

- https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.11.1
- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/

The complete GNU Lesser General Public License version 3 text is distributed as
`THIRD_PARTY_LICENSES/LGPL-3.0.txt` (SHA-256
`e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118`) and is
also available at https://www.gnu.org/licenses/lgpl-3.0.html. Nothing in the
Onyx product license limits rights granted by that third-party license.

## CryptoJS

The dashboard includes CryptoJS 4.2.0, distributed under the MIT License.
The exact vendored file is `dashboard/static/crypto-js.min.js`, SHA-256
`769a555de553babc35a3338f344dd7aa16260c93cea2c7db290707c90484e7cc`.
Its provenance record and license are distributed beside the file as
`crypto-js.PROVENANCE.json` and `crypto-js.LICENSE.txt`.

Upstream: https://github.com/brix/crypto-js/tree/4.2.0

## Playwright, Chromium, and FFmpeg

Playwright is distributed under Apache-2.0. Its driver package preserves its
`LICENSE`, `NOTICE`, and `ThirdPartyNotices.txt` files inside
`_internal/playwright/driver/package`. Browser-engine and FFmpeg notices shipped
by Playwright remain part of that payload. The SBOM binds the exact browser and
driver bytes present in each release artifact.

Upstream: https://github.com/microsoft/playwright

## CPython compatibility launcher

The immutable CPython virtual-environment compatibility launcher retained for
historical activation-integrity evidence is distributed under the Python
Software Foundation License. Its `PSF-LICENSE.txt` is included beside the
launcher. The packaged application executes through the native Onyx entrypoint
and does not activate this compatibility launcher.

## odfpy

Onyx uses odfpy 1.4.1 to preserve OpenDocument spreadsheet ingestion. The
exact upstream source release declares GPL-2.0-or-later or Apache-2.0 for the
project except for the OpenDocument schemas, while files in the shipped Python
library also contain LGPL-2.1-or-later headers. Generated grammar material
retains the OASIS OpenDocument copyright and reuse notice.

The packaged legal-evidence directory therefore includes the hash-pinned exact
`odfpy-1.4.1.tar.gz` corresponding source, its README, Apache-2.0 and GPL-2.0
texts, representative LGPL and OASIS source headers, and the official
LGPL-2.1 text. These materials preserve the upstream alternatives and notices;
Cyryx Labs does not claim ownership of odfpy or the OASIS material and does not
restrict rights granted by their governing terms.

Upstream: https://github.com/eea/odfpy/tree/release-1.4.1
PyPI source SHA-256:
`db766a6e59c5103212f3cc92ec8dd50a0f3a02790233ed0b52148b70d3c438ec`.

## Python packages and native libraries

Onyx also contains the direct and transitive Python packages enumerated in the
release SBOM. Their embedded `.dist-info` metadata and license files are
preserved whenever supplied by the upstream wheel. Common license families in
the locked dependency set include Apache-2.0, BSD-2-Clause, BSD-3-Clause, MIT,
MIT-0, MPL-2.0, PSF-2.0, LGPL-3.0-only, and compatible dual-license choices.

No entry in this file changes an upstream license. If this notice and an
upstream license differ, the upstream license controls for that component.

## Source and compliance requests

Requests for the corresponding source or a copy of an applicable third-party
license may be sent to contact@cyryxlabs.com. Include the Onyx version,
operating system, architecture, artifact filename, and SHA-256 shown in the
release manifest.
