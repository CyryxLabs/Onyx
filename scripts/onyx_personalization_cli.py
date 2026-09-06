"""Machine-readable CLI for governed personalization records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.governed_personalization_v1 import (  # noqa: E402
    GovernedPersonalizationContractError,
    GovernedPersonalizationDenied,
    GovernedPersonalizationError,
    GovernedPersonalizationStoreV1,
    PersonalizationFeatureGateV1,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onyx-personalization")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--enable", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--allow-sensitive", action="store_true", help=argparse.SUPPRESS
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("record_id", nargs="?")
    inspect.add_argument("--include-revoked", action="store_true")
    create = commands.add_parser("create")
    create.add_argument("--key", required=True)
    create.add_argument("--value", required=True)
    create.add_argument("--provenance", action="append", required=True)
    create.add_argument("--sensitivity", default="internal")
    create.add_argument("--owner-confirmed", action="store_true")
    create.add_argument("--freshness-seconds", type=int, default=90 * 86_400)
    for name in ("confirm", "revoke"):
        command = commands.add_parser(name)
        command.add_argument("record_id")
    edit = commands.add_parser("edit")
    edit.add_argument("record_id")
    edit.add_argument("--value", required=True)
    edit.add_argument("--provenance", action="append", required=True)
    edit.add_argument("--freshness-seconds", type=int, default=90 * 86_400)
    commands.add_parser("export")
    delete = commands.add_parser("delete")
    delete.add_argument("record_id", nargs="?")
    delete.add_argument("--all", action="store_true")
    return parser


def _json_value(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GovernedPersonalizationContractError("value must be JSON") from exc


def _payload(value: Any) -> Any:
    if hasattr(value, "payload"):
        return value.payload()
    if isinstance(value, tuple):
        return [_payload(item) for item in value]
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = GovernedPersonalizationStoreV1(
            args.database,
            owner_profile_id=args.owner,
            workspace_id=args.workspace,
            gate=PersonalizationFeatureGateV1(args.enable, args.allow_sensitive),
        )
        if args.command == "inspect":
            result = store.inspect(args.record_id, include_revoked=args.include_revoked)
        elif args.command == "create":
            result = store.create(
                preference_key=args.key,
                value=_json_value(args.value),
                provenance=args.provenance,
                sensitivity=args.sensitivity,
                inferred=not args.owner_confirmed,
                freshness_seconds=args.freshness_seconds,
            )
        elif args.command == "confirm":
            result = store.confirm(args.record_id)
        elif args.command == "edit":
            result = store.edit(
                args.record_id,
                value=_json_value(args.value),
                provenance=args.provenance,
                freshness_seconds=args.freshness_seconds,
            )
        elif args.command == "revoke":
            result = store.revoke(args.record_id)
        elif args.command == "export":
            result = store.export()
        else:
            if args.record_id is None and not args.all:
                raise GovernedPersonalizationContractError(
                    "delete requires record_id or --all"
                )
            result = {"deleted": store.delete(None if args.all else args.record_id)}
        print(json.dumps({"ok": True, "result": _payload(result)}, sort_keys=True))
        return 0
    except (
        GovernedPersonalizationContractError,
        GovernedPersonalizationDenied,
        GovernedPersonalizationError,
    ) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {"code": exc.__class__.__name__, "message": str(exc)},
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
