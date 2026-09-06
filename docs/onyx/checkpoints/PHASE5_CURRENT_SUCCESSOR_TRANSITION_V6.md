# Phase 5 current-successor transition V6

V6 advances only the authenticated current-byte closure required to isolate
the Onyx 1.1.2 packaged Governance V16 smoke from inherited developer-shell
activation flags. The immutable Phase 5 Exit predecessor and the V1 through
V5 successor-transition records remain unchanged.

## Boundary

- Predecessor: `tests/fixtures/phase5_exit_retirement_v1.json`
- Predecessor SHA-256: `23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997`
- V6 record: `tests/fixtures/phase5_current_successor_transition_v6.json`
- V6 record SHA-256: `add8810d8295c4d298dcc3d2fc970f275d17f70eb76bbef9989af500e249a2b8`
- V6 aggregate root: `6e893178d35ee924fd8853030d94bf443c8ef5787ba1e86f23915b659bb012f2`

## Current-byte changes since V5

| Path | V5 current SHA-256 | V6 current SHA-256 | Reason |
|---|---|---|---|
| `scripts/build_release.py` | `383c70fcbc09e7151ff7fdffdd52f6869ec2f298e934e01befc5343fe227d3cf` | `75d495c7cdb1fd1f0f0711522cdff8cc5e428318733c0d348fe5049b76b3b058` | The packaged governance gate now removes the complete inherited V19 control surface before exercising the frozen fallback bootstrap. |

All 18 historical binding identities, states, successors, and historical
hashes remain byte-for-byte identical to the predecessor record. All seven
named-successor predecessor and current hashes remain unchanged. This
transition changes no runtime authority and no installed application behavior.
