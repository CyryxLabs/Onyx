# Release Workflow transition V11

Status: **current release-source policy**  
Issued: 2026-08-04

V11 preserves exact Release Workflow V10 and binds the V24 package-hygiene
correction and its current successor evidence.

- Transition SHA-256:
  `4acd3a16ed58084ae606538babaf00d77172031ed3d3d67c10e3fa5064ee1189`.
- Current release-path root SHA-256:
  `f25120019fff6ef8f85a253be5ff79add7876d6ec70fa2d65f399176017ddb5e`.
- Exact predecessor V10 SHA-256:
  `1a853081a3c1aad40554e18016fbc9f9601fcbfdb139acb69179d5cb1d365102`.
- Bound current release paths: 63.

The policy remains fail closed: unsigned Windows artifacts are not formal,
diagnostic candidates are not publishable, and exact predecessor/source hashes
remain immutable.

