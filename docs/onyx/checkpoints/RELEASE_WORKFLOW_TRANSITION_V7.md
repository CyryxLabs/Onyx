# Release workflow transition V7

Status: current authenticated release-source policy.

Release Workflow V7 preserves exact V6 and binds 35 sorted release paths. It
updates the release builder and adds the package-hygiene implementation plus its
runtime-validation-clone regression test. Package smoke tests must execute on a
disposable clone and the production bundle must remain free of mutable Phase 6
session state.

- V7 transition SHA-256:
  `67cc64a5f0cea8b3d3562ba2520771d294a6749dd152f30edd2e8c5f6ca92184`
- V7 current root:
  `b4ed1b3b1695e7498835e01675281ad14cf14d7ae5c52d13d4b8b4c69e399e44`
- Exact V6 predecessor SHA-256:
  `7e1f8bbe71773a7a0f0f0a1d7b57601b119c343f8533d91b703ef4a88b195c44`

This transition authenticates source policy only. It does not claim a Windows
artifact, installation or formal release.
