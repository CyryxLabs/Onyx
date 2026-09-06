# Onyx Live Activation V1 rejection

Date: 2026-07-22

Decision: **REJECTED and frozen. Do not activate.**

V1 patched a nonexistent `main.Assistant` class instead of the actual
`main.OnyxLive` host, so its live integration could not install. Its launcher
also accepted ambiguous truthy spellings before the real host import boundary.
V1 must remain exact historical evidence and is unreachable from V2.

| Frozen V1 artifact | SHA-256 |
|---|---|
| `core/onyx_live_activation_v1.py` | `141d363f2df1a8a17a3fa92dc1e5f9f17aed400cdb65fe53f35f3ada0e3f6c51` |
| `scripts/launch_onyx_live_v1.pyw` | `d920ba4fb222532e6a54ba6cc51bb52801ed5ce693e77c12282e4fa65bb09d9d` |
| `scripts/verify_onyx_live_activation_v1.py` | `d4259167ea354cfa25e541a5090c08e42b164742d7950185fbac8e18ed6d2daa` |
| `tests/test_onyx_live_activation_v1.py` | `66cc8a5ea33df0dd453b44a92c54dfc0146905f8bb00621d0ddb3ef342c316c8` |
| V1 manifest | `3e9021893d93a7c00749d2e5e2c19fd7b90fcf5286239aecbb19e5197487fbef` |
| V1 checkpoint | `d612962e7809653ca7f46e883c4dc7e4623a26ff30e1b4061b97a685e283dbcc` |

This rejection record does not alter or retroactively reinterpret the accepted
Owner Profile V8, Integration V3, HUD V5, Runtime V10, Adapters V3, R11, V15 or
V32 candidates.
