# Onyx Current Capability Nexus V1 Acceptance

Decision: accepted as the current source-integrity authority for the versioned
Capability Nexus catalog.

This record binds the exact current bytes of all 32 versioned
`core/capability_nexus_v*.py` implementations, their 32 matching
`tests/test_capability_nexus_v*.py` regression suites, the live
`core/permission_broker.py` dependency that drifted from the frozen V14 leaf,
and the current Capability Nexus architecture record. The catalog remains
closed to versions 1 through 32: a missing, duplicate, renamed, or silently
added version fails the successor gate.

The 32 historical `VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V*-001.sha256` files are
retained byte-for-byte as superseded historical tombstones. They are parsed
only to prove canonical historical structure, exact manifest identity, record
counts, and closed membership. Their embedded digests are never compared with
live successor files and they are not current-runtime authority.

The successor verifier independently recomputes a domain-separated root over
the exact current closure. Its tests reproduce that root without importing the
production root helper and reject manifest, implementation, test,
documentation, catalog-membership, historical-manifest, and projection tamper.

This is an evidence-only successor. It changes no Capability Nexus dispatch,
authorization, startup, UI, provider, MCP, or external-mutation semantics. The
earlier V32 E6 decision remains valid only for its frozen historical candidate
and must not be cited as proof of the current working-tree bytes.
