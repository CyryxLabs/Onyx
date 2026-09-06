# Phase 5 current-successor transition V3

Status: source closure only; no release or E6 claim.

This transition preserves the immutable Phase 5 Exit predecessor and every
historical path/digest binding. It supersedes only the mutable current-byte
closure recorded by V2.

V3 records the release-preparation successor after the Windows packaging
pipeline began staging an exact Inno Setup compiler boundary with the official
English message catalog. The catalog is distributed with its original Inno
Setup license and the Brazilian Portuguese language remains declared by the
installer.

The machine-readable record is
`tests/fixtures/phase5_current_successor_transition_v3.json`. It retains all 18
historical hashes and all seven named predecessor hashes unchanged, updates the
current digest of `scripts/build_release.py`, and recomputes the domain-separated
V3 root. V1 and V2 remain unchanged and reproducible.

This closure grants no runtime authority and makes no claim about canonical
installation, public distribution, code signing, notarization, or clean-machine
acceptance.
