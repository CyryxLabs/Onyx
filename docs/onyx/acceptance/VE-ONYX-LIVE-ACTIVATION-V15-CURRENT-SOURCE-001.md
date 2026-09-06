# Onyx Live Activation V15 current source identity anchor

- Evidence ID: `VE-ONYX-LIVE-ACTIVATION-V15-CURRENT-SOURCE-001`
- Observation date: `2026-08-03`
- Decision: **authenticated source identity only**
- Current source SHA-256: `ef50ffc02dd3865fc02e9a3d4114ec55f316b3111d44383f1c6e4d7df756a211`
- Current source size: `52463` bytes

This record anchors the exact current bytes of
`core/onyx_live_activation_v15.py`. The anchor was created only after the
working-tree source was compared byte-for-byte with the canonical Onyx 1.1.8
installed payload at
`%LOCALAPPDATA%/Programs/Cyryx Labs/Onyx/_internal/core/onyx_live_activation_v15.py`.
Both observations had the SHA-256 and size above. The installed version module
reported `1.1.8`.

The earlier 1.1.7 portable rollback artifact was also inspected. Its V15 source
has SHA-256
`a239fa0e95230ddf2ee15ecb005215eed06ff37753a826bdd00ad31eaf1c7fe5`,
so no historical 1.1.7 acceptance is reused or rebound to the current bytes.

This integrity anchor does not accept functionality, release maturity,
cross-platform parity, signing, notarization, provider operation, security
review, or project completion. Those gates require their own current evidence.
