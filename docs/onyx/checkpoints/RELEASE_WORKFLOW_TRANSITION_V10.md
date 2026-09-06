# Release workflow transition V10

Status: current authenticated release-source policy.

Release Workflow V10 preserves exact V9 and binds 60 sorted release paths. It
adds the current V15 source-identity successor, preserving the immutable 1.1.8
anchor while authenticating the exact V15 bytes shared by source and the
installed 1.1.9 payload.

- V10 transition SHA-256:
  `1a853081a3c1aad40554e18016fbc9f9601fcbfdb139acb69179d5cb1d365102`
- V10 current root:
  `63013a5240a9cb0437705c9bfa4f04ac101306d638e358ee316df51c0142388c`
- Exact V9 predecessor SHA-256:
  `841e79d6aeba881efb59d125665d90072784424e938f691bae66e33b4ca9e37c`

This transition authenticates source policy only. It does not transfer V22
artifact, installation, runtime or voice evidence.
