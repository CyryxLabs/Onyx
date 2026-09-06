# Phase 9 live ingestion — owner setup guide

Status: current owner onboarding guide for a default-off connector. This guide
is not proof of live-source configuration, execution or release completion.

This guide walks you (the Cyryx owner) through enabling and running a **real live
fetch** with the accepted Phase 9 live-source connector
(`VE-P9-LIVE-INGESTION-V1-E6-001`). The connector and its contract are already
verified and frozen; what remains is a decision only you can make — registering
approved sources and permitting the outbound network requests. Nothing here
happens automatically: until you complete these steps the connector stays inert
(default-off), and the runner refuses to make any network call.

## What a run does

For each source in your approved registry, the runner performs one HTTPS `GET`
against the exact `https://<origin><path>` you approved, over a route-pinned,
redirect-disabled client (no redirects, no retries, 1 MiB / 200-item caps). It
attributes each item's `source_id`, health `tier` and `category` **from your
registry, never from the fetched feed**, hands the items to the accepted
intelligence-ingestion contract for normalisation, and writes a run report plus
its SHA-256. It never mutates a source, follows a redirect, retries, or acts on
the content. A fetched item is data only.

## Step 1 — Register approved sources

Create a registry JSON file: a list of source objects. Each needs:

| field | meaning | constraint |
|---|---|---|
| `source_id` | your stable id for the source | non-empty, ≤256 bytes |
| `tier` | source health | one of `primary`, `official`, `reputable`, `community`, `unverified` |
| `category` | which radar category this source feeds | one of `geopolitics`, `finance_macro`, `ai_tech_cyber`, `startups_markets`, `api_changes`, `creator_economy`, `cyryx_opportunity` |
| `origin` | the host | a bare, lowercase, ASCII DNS host — **no** `https://`, port, userinfo (`@`), path, query or unicode |
| `path` | the feed path | absolute, ASCII, **query-free** (`?`/`#` not allowed), no `..` or `//` |

Example `my_sources.json`:

```json
[
  {
    "source_id": "example-gov-press",
    "tier": "official",
    "category": "geopolitics",
    "origin": "feeds.example.test",
    "path": "/onyx/press.json"
  }
]
```

The URL each source must serve is the **neutral Onyx feed shape** — a JSON object
with an `items` array, each item carrying content fields only:

```json
{
  "items": [
    {
      "id": "2026-07-25-001",
      "title": "Headline text",
      "url": "https://feeds.example.test/onyx/a",
      "published": "2026-07-25T10:00:00Z",
      "event": "2026-07-25T09:00:00Z",
      "claims": [
        {"text": "A reported fact", "claim_type": "fact",
         "consequential": true, "corroborating_source_ids": ["other-source"]}
      ]
    }
  ]
}
```

`claim_type` is one of `fact` / `inference` / `scenario` / `recommendation`;
`claims` is optional. The feed's own `source_id`/`tier`/`category`, if present,
are **ignored** — trust comes from your registry entry.

## Step 2 — Enable the flags

```bash
export ONYX_PHASE9_LIVE_INGESTION_V1=true
# optional: also normalise the fetched items in the same run
export ONYX_PHASE9_INTELLIGENCE_INGESTION_V1=true
```

(On Windows PowerShell: `$env:ONYX_PHASE9_LIVE_INGESTION_V1='true'`.)

## Step 3 — Run it, acknowledging the outbound requests

```bash
python scripts/run_phase9_live_ingestion_v1.py \
    --registry my_sources.json \
    --report-dir "$TEMP/onyx-phase9-live" \
    --confirm-live-fetch
```

`--confirm-live-fetch` is your explicit acknowledgement that this makes real
outbound HTTPS requests to the sources you registered. Without it (or without the
flag) the runner refuses and makes no network call. The runner prints each source
it will fetch **before** fetching, then the report path and its SHA-256.

## What you get

A `live-ingestion-run-<timestamp>.json` report: per-source fetch status, item
counts and upstream attribution, plus (if ingestion is enabled) a normalisation
summary — canonical vs duplicate counts, unverified-source count, uncorroborated
consequential-claim count and per-category counts. Keep the SHA-256 as the run's
anchor.

## Governance and limitations (read before running)

- **You are the trust root.** Source health and category come from your registry,
  not the feed. Approve only sources you trust for the tier you assign.
- **Least privilege.** The client is pinned to the exact approved origin/path,
  disables redirects, and never retries. A source that 3xx-redirects or returns a
  non-200 fails closed rather than following the redirect.
- **No action, ever.** The connector cannot mutate a source or act on content; it
  can never turn a geopolitical or financial signal into a trade or any other
  action.
- **Neutral feed shape only.** V1 consumes the Onyx neutral feed contract above.
  Adapting arbitrary provider formats (RSS/Atom/vendor JSON) or feeds that require
  query parameters or an API key/credential is **not** in V1 — those need a later
  gated adapter/credential successor.
- **Operational, not frozen.** `scripts/run_phase9_live_ingestion_v1.py` is an
  operational runner, not part of any E6 acceptance closure; the accepted,
  frozen artifact is the connector contract it drives.
- **Argos** (Onyx's 100%-proprietary world-intelligence, replacing the dropped
  third-party World Monitor) is a separate future component and is not part of
  this connector path.
