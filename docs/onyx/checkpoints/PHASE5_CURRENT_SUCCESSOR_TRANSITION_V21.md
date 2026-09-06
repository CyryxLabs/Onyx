# Phase 5 current successor transition V21

Status: current source authority; Windows rebuild and installed acceptance
required.

V21 preserves the exact V20 record and changes three current bindings:
`scripts/build_release.py`, `scripts/package_hygiene.py` and the V19 activation
regression that verifies the disposable validation target. The release builder
now runs all mutable package validation against a disposable clone, rejects
packaged Phase 6 session state and routes the production V21 Phase 6 owner state
to the private Onyx runtime directory. The established engine and approval
authority remain unchanged.

- V21 transition SHA-256:
  `a5f720f39421d68546d1ff8e248e893b174d1f9e7ef0e604c7e8743179531b17`
- V21 current root:
  `31f90a01875c6f0558e329cdbbb125c7d805a9e3e9d56c9e008a36cf158c4980`
- Exact V20 predecessor SHA-256:
  `8ea87bb7a12bd2343bc9d4bc381c627b27c9155a24aa1eb76f47466bea2773e6`
- Policy: historical records are not rewritten; runtime-authority change is
  explicitly declared for storage location only.

No build, installed-runtime or long-session evidence transfers from V20. Those
gates must be repeated against artifacts derived from this exact transition.
