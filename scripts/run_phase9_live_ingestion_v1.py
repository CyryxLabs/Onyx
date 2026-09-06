"""Owner-gated live runner for the accepted Phase 9 live ingestion connector.

This is an OPERATIONAL script, not part of any E6 acceptance closure. It performs
a REAL outbound HTTPS fetch against the sources listed in an operator-approved
registry, using the accepted route-pinned connector, and feeds the result into
the accepted intelligence ingestion contract. Because it touches the network, it
runs only when the owner has:

  1. set ONYX_PHASE9_LIVE_INGESTION_V1=true,
  2. supplied an approved-source registry JSON (--registry), and
  3. passed --confirm-live-fetch to acknowledge the outbound requests.

Without all three it makes no network call. It writes a run report (sources
fetched, item counts, upstream attribution and an ingestion summary) and prints
the report path and its SHA-256. It never mutates a source, follows a redirect,
retries, or takes any action on the fetched content.

Example:
  ONYX_PHASE9_LIVE_INGESTION_V1=true \\
  python scripts/run_phase9_live_ingestion_v1.py \\
      --registry my_sources.json --confirm-live-fetch \\
      --report-dir "%TEMP%/onyx-phase9-live"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.phase9_intelligence_ingestion_v1 import (  # noqa: E402
    IntelligenceIngestionFeatureGateV1,
    create_intelligence_ingestion_v1,
)
from core.phase9_live_ingestion_v1 import (  # noqa: E402
    ApprovedSourceV1,
    LiveIngestionFeatureGateV1,
    create_live_ingestion_v1,
)

INGESTION_FLAG = "ONYX_PHASE9_INTELLIGENCE_INGESTION_V1"


def _load_registry(path: Path) -> tuple[ApprovedSourceV1, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if type(raw) is not list or not raw:
        raise SystemExit("registry must be a non-empty JSON list of source objects")
    sources: list[ApprovedSourceV1] = []
    for entry in raw:
        if type(entry) is not dict:
            raise SystemExit("each registry entry must be a JSON object")
        missing = {"source_id", "tier", "category", "origin", "path"} - set(entry)
        if missing:
            raise SystemExit(f"registry entry missing fields {sorted(missing)}: {entry!r}")
        try:
            sources.append(
                ApprovedSourceV1(
                    entry["source_id"],
                    entry["tier"],
                    entry["category"],
                    entry["origin"],
                    entry["path"],
                )
            )
        except ValueError as exc:
            raise SystemExit(f"invalid approved source {entry!r}: {exc}") from exc
    return tuple(sources)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a consented Phase 9 live fetch.")
    parser.add_argument("--registry", required=True, help="approved-source registry JSON")
    parser.add_argument("--report-dir", required=True, help="directory for the run report")
    parser.add_argument(
        "--confirm-live-fetch",
        action="store_true",
        help="required acknowledgement that this makes real outbound HTTPS requests",
    )
    args = parser.parse_args()

    live_gate = LiveIngestionFeatureGateV1.from_environ()
    if not live_gate.enabled:
        raise SystemExit(
            "refusing: set ONYX_PHASE9_LIVE_INGESTION_V1=true to enable the connector"
        )
    if not args.confirm_live_fetch:
        raise SystemExit(
            "refusing: pass --confirm-live-fetch to acknowledge real outbound requests"
        )

    registry = _load_registry(Path(args.registry))
    session = create_live_ingestion_v1(
        gate=live_gate,
        sources=registry,
        now_epoch_s=lambda: int(time.time()),
        project_root=PROJECT,
    )
    if session is None:  # pragma: no cover - gate re-checked above
        raise SystemExit("connector unavailable")

    print(f"Fetching {len(registry)} approved source(s):")
    for source in registry:
        print(f"  - {source.source_id} [{source.tier}] https://{source.origin}{source.path}")

    fetches: list[dict[str, object]] = []
    all_items: list[dict[str, object]] = []
    for source in registry:
        result = session.fetch(source_id=source.source_id)
        fetches.append(
            {
                "source_id": result.source_id,
                "tier": result.tier,
                "category": result.category,
                "url": result.url,
                "http_status": result.http_status,
                "item_count": result.item_count,
                "attribution": result.attribution,
            }
        )
        all_items.extend(result.raw_items)
        print(f"  fetched {result.item_count} item(s) from {result.source_id}")

    ingestion_summary: dict[str, object] = {"ran": False}
    if IntelligenceIngestionFeatureGateV1.from_environ().enabled:
        ingestion = create_intelligence_ingestion_v1(
            gate=IntelligenceIngestionFeatureGateV1(True),
            now_epoch_s=lambda: int(time.time()),
            project_root=PROJECT,
        )
        if ingestion is not None:
            ingest_result = ingestion.ingest(all_items)
            ingestion_summary = {
                "ran": True,
                "canonical_count": ingest_result.canonical_count,
                "duplicate_count": ingest_result.duplicate_count,
                "unverified_source_count": ingest_result.unverified_source_count,
                "uncorroborated_consequential": len(
                    ingest_result.uncorroborated_consequential
                ),
                "by_category": dict(ingest_result.by_category),
            }
    else:
        ingestion_summary = {
            "ran": False,
            "reason": f"set {INGESTION_FLAG}=true to also normalise the fetched items",
        }

    report = {
        "schema": "onyx.phase9.live-ingestion.run.v1",
        "ran_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_count": len(registry),
        "total_items_fetched": len(all_items),
        "fetches": fetches,
        "ingestion": ingestion_summary,
    }
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"live-ingestion-run-{report['ran_at_utc'].replace(':', '')}.json"
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    print(f"\nReport: {report_path}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
