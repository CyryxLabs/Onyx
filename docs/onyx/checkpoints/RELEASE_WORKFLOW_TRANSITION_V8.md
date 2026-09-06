# Release workflow transition V8

Status: current authenticated release-source policy.

Release Workflow V8 preserves exact V7 and binds 36 sorted release paths. It
updates the release builder and adds regression coverage proving that both
Windows native-vault smoke namespaces are cleaned even when a frozen child
times out.

- V8 transition SHA-256:
  `11aaf28a744c8e60db2b32373239ebafc1f2ee189bfbca2c0d899668f007dd68`
- V8 current root:
  `a2d60dfc7b7725f1d1dc4ffa15eb4b6e11e294a601013d65d485a6995eec5434`
- Exact V7 predecessor SHA-256:
  `67cc64a5f0cea8b3d3562ba2520771d294a6749dd152f30edd2e8c5f6ca92184`

This transition authenticates source policy only. It does not transfer the
preceding V21 artifact or installation evidence.
