# Phase 5 current successor transition V24

Status: **current source authority**  
Issued: 2026-08-04

V24 preserves the exact V23 predecessor and changes only the Phase 5-bound
package-hygiene test so that release validation follows the production build's
isolated validation-bundle contract.

- Transition SHA-256:
  `69abcde1629a7a62be7021c5085a4c5a40eab2ed4b9c1175f042c7568af71308`.
- Transition root SHA-256:
  `0ed9beb50037fce2e6694fe5639734539399e38a90cb6ffa6073163e57413b77`.
- Exact predecessor V23 SHA-256:
  `0f3301d1d2d3ec425a7f3439feac6a160ccec0cae3dacc3f8d1bd4173e2a870f`.
- Changed named successor:
  `tests/test_package_hygiene_v1.py`, SHA-256
  `8b875e65ddb92c4f0a9583b785fbdcc7d533e679e90b6cee89c6abc85b6e7470`.

The correction does not change the Onyx engine, authority model, runtime
features, voice provider or HUD. It makes the test require validation against
`clone_runtime_validation_bundle(bundle)` and cleanup of that disposable clone,
matching the already-established production build behavior.

Validation:

- focused V24/package selection: 16 passed;
- portable security/lifecycle/release selection: 128 passed, 1 platform skip;
- complete Phase 5 and release transition chain: 58 passed;
- Ruff for the changed transition/test surface: passed.

