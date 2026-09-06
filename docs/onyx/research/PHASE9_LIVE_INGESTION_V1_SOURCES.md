# Phase 9 Live Ingestion V1 — Design sources

This connector fetches from operator-approved sources over HTTPS, but binds no
specific third-party provider — approved sources are supplied at runtime through
an injected registry. The design basis and the standards it relies on are
recorded here for auditability; verified on 2026-07-24.

## Requirement basis

- Onyx PRD, Phase 9 "Intelligence and opportunity radar", item 1:
  primary/official-source-first ingestion with upstream/source-health
  attribution (`plans/onyx-advanced-entity-redesign.md`).
- Phase 9 guards: least privilege, source health, and never turning signals into
  autonomous trading actions.

## Transport and route pinning

- The client uses the Python standard-library `urllib.request` HTTPS handler
  with a default TLS context (`ssl.create_default_context`, certificate and
  hostname verification on) and a redirect handler whose `redirect_request`
  returns `None`, so any `3xx` fails closed rather than following a `Location`
  header off the approved surface. This mirrors the accepted Phase 8 Microsoft
  Graph clients.
- Each request is pinned to `https://<origin><path>` for an approved source:
  scheme must be `https`, `netloc` must equal the approved bare host, `path`
  must equal the approved absolute path, and query/fragment are rejected — per
  the URL grammar in RFC 3986.

## Feed shape and attribution

- The neutral feed contract is a JSON object with an `items` array; each item
  supplies content fields only (`id`, `title`, `url`, `published`, `event` and
  optional `claims`). Timestamps follow ISO-8601 and are handed to the accepted
  ingestion contract unchanged for parsing.
- Source health (`tier`), `source_id` and `category` are attributed from the
  operator's approved registry, not from the feed, so upstream attribution is
  trustworthy regardless of what the fetched content claims about itself. The
  approved `origin` is validated as a bare, lowercase, ASCII DNS host (no
  userinfo, port, unicode or empty labels) and the `path` as an absolute,
  ASCII, query-free, dot-segment-free path, so the route pin's
  `netloc == origin == hostname` equality cannot be defeated by a crafted
  registry entry.

## Owner-gated live execution

- Real fetching against live sources requires the owner to register approved
  sources and permit network egress; until then the default-off flag and the
  absence of an injected registry keep the connector inert. This is the same
  owner-gating posture the accepted Phase 8 live connector runs used.

## Deliberately out of scope

- Claim typing / deduplication / corroboration (the accepted ingestion contract
  does this), opportunity scoring (a separate accepted slice), model-assisted
  parsing, and the licence-gated World Monitor connector.
