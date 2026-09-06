# Release Workflow transition V6

Status: current release-source policy authority.

V6 preserves exact Release Workflow V5 and binds 33 sorted release-policy
paths. It adds the pinned Rust 1.89 Linux validation image boundary and its
version regression test, and updates the release builder plus supplemental
metadata regression coverage.

- V6 transition SHA-256:
  `7e1f8bbe71773a7a0f0f0a1d7b57601b119c343f8533d91b703ef4a88b195c44`
- V6 current root:
  `80db75826acb2a06e4b5ff160b7cb93a4381dd1bef5d857af75e100946676b44`
- Exact V5 predecessor SHA-256:
  `cf271a0669cdc5379589c10285107c83098a573c4e2598442f21ea2d2122c998`
- Unsigned Windows artifacts remain ineligible for formal release and
  diagnostic candidates remain non-publishable.
