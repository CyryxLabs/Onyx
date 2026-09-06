"""Machine-readable CLI for opted-in clipboard and private wellness tools."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.clipboard_intelligence_v1 import (  # noqa: E402
    ClipboardIntelligenceDenied,
    ClipboardIntelligenceStoreV1,
    StaticOwnerScopeAdapterV1,
    status_payload,
)
from core.wellness_tracker_v1 import (  # noqa: E402
    WellnessTrackerDenied,
    WellnessTrackerStoreV1,
)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--workspace", required=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="onyx-personal-tools")
    domains = root.add_subparsers(dest="domain", required=True)
    clipboard = domains.add_parser("clipboard")
    clipboard_actions = clipboard.add_subparsers(dest="action", required=True)
    for action in ("status", "pause", "revoke", "clear", "opt-in", "snapshot"):
        selected = clipboard_actions.add_parser(action)
        _common(selected)
        if action == "opt-in":
            selected.add_argument("--retention-seconds", type=int, default=900)
        if action == "snapshot":
            selected.add_argument("--text", required=True, help="Explicit snapshot text")

    wellness = domains.add_parser("wellness")
    wellness_actions = wellness.add_subparsers(dest="action", required=True)
    for action in ("create-calorie", "create-exercise", "vision-draft", "list", "correct", "confirm", "remove", "totals"):
        selected = wellness_actions.add_parser(action)
        _common(selected)
        if action in {"create-calorie", "create-exercise", "vision-draft"}:
            selected.add_argument("--value", type=float, required=True)
            selected.add_argument("--occurred-at", required=True)
            selected.add_argument("--timezone", required=True)
            selected.add_argument("--idempotency-key", required=True)
        if action in {"create-exercise", "vision-draft"}:
            selected.add_argument("--activity")
            selected.add_argument("--unit", default="minutes")
        if action == "vision-draft":
            selected.add_argument("--kind", choices=("calorie", "exercise"), required=True)
        if action == "list":
            selected.add_argument("--kind", choices=("calorie", "exercise"))
        if action in {"correct", "confirm", "remove"}:
            selected.add_argument("--entry-id", required=True)
        if action == "correct":
            selected.add_argument("--value", type=float, required=True)
        if action == "totals":
            selected.add_argument("--day", required=True)
            selected.add_argument("--timezone", required=True)
    return root


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    scope = StaticOwnerScopeAdapterV1(arguments.owner, arguments.workspace)
    if arguments.domain == "clipboard":
        store = ClipboardIntelligenceStoreV1(arguments.db, owner_scope=scope)
        if arguments.action == "status":
            return dict(status_payload(store.status(arguments.owner, arguments.workspace)))
        if arguments.action == "opt-in":
            return dict(status_payload(store.opt_in(
                arguments.owner, arguments.workspace,
                retention_seconds=arguments.retention_seconds,
            )))
        if arguments.action == "pause":
            return dict(status_payload(store.pause(arguments.owner, arguments.workspace)))
        if arguments.action == "revoke":
            return dict(status_payload(store.revoke(arguments.owner, arguments.workspace)))
        if arguments.action == "clear":
            return {"contract": "OnyxClipboardClear.v1", "cleared": store.clear(arguments.owner, arguments.workspace)}
        preview = store.analyze_snapshot(
            arguments.owner, arguments.workspace, lambda: arguments.text
        )
        return {**asdict(preview), "status": "preview"}

    store = WellnessTrackerStoreV1(arguments.db, owner_scope=scope)
    if arguments.action == "create-calorie":
        entry = store.create_calorie(
            arguments.owner, arguments.workspace, calories=arguments.value,
            occurred_at=arguments.occurred_at, timezone_name=arguments.timezone,
            idempotency_key=arguments.idempotency_key,
        )
        return asdict(entry)
    if arguments.action == "create-exercise":
        entry = store.create_exercise(
            arguments.owner, arguments.workspace, activity=arguments.activity,
            value=arguments.value, unit=arguments.unit,
            occurred_at=arguments.occurred_at, timezone_name=arguments.timezone,
            idempotency_key=arguments.idempotency_key,
        )
        return asdict(entry)
    if arguments.action == "vision-draft":
        return asdict(store.create_vision_estimate(
            arguments.owner, arguments.workspace, kind=arguments.kind,
            value=arguments.value, occurred_at=arguments.occurred_at,
            timezone_name=arguments.timezone, idempotency_key=arguments.idempotency_key,
            activity=arguments.activity, unit=arguments.unit,
        ))
    if arguments.action == "list":
        return {"contract": "OnyxWellnessList.v1", "entries": [
            asdict(item) for item in store.list_entries(
                arguments.owner, arguments.workspace, kind=arguments.kind
            )
        ], "limitation": store.LIMITATION}
    if arguments.action == "correct":
        return asdict(store.correct(
            arguments.entry_id, arguments.owner, arguments.workspace, value=arguments.value
        ))
    if arguments.action == "confirm":
        return asdict(store.confirm(arguments.entry_id, arguments.owner, arguments.workspace))
    if arguments.action == "remove":
        return asdict(store.remove(arguments.entry_id, arguments.owner, arguments.workspace))
    return store.totals(
        arguments.owner, arguments.workspace, day=arguments.day,
        timezone_name=arguments.timezone,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = execute(parser().parse_args(argv))
    except (ClipboardIntelligenceDenied, WellnessTrackerDenied, ValueError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
