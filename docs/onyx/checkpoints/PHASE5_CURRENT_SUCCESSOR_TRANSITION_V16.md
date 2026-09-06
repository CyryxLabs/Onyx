# Phase 5 current successor transition V16

Status: **FROZEN SOURCE — BUILD AND INSTALLED ACCEPTANCE REQUIRED**  
Transition: `tests/fixtures/phase5_current_successor_transition_v16.json`  
Transition SHA-256: `364b186c384ac964eab21034d4049536613f50597b67e9edb6604f9edb256901`  
Domain root: `83bf7e45fed9ffbf23aff9ab824b4371d53813d317fb5ef181d8b362edb588aa`

V16 preserves the exact V15 transition as its immutable predecessor. It changes
no runtime authority, provider, voice, mission, permission, memory or HUD path.
Its only Phase 5-bound delta is `scripts/build_release.py`.

The first V15 build attempt completed PyInstaller, packaged native startup,
Governance, Founder, Document Intake and DayOps smoke gates, and emitted a Setup
file. Portable ZIP creation then failed because eleven upstream legal files had
filesystem timestamps from 1969 or 1973, outside the ZIP metadata range.
Because final manifests and checksums were not emitted, that partial Setup is
not an installable candidate.

V16 writes the Windows portable ZIP in sorted order with
`strict_timestamps=False`, which clamps only unrepresentable ZIP metadata to
1980 without changing staged source bytes or timestamps. It also rejects linked
members and atomically replaces the completed archive. The focused regression
selection passes 15 tests and Ruff is clean.

A complete traceable build, final release manifest, exact artifact hashes,
installation and proportional installed acceptance must succeed before V16 can
replace V14 operationally.
