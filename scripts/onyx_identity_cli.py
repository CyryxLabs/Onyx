"""CLI for language memory and immutable Onyx identity preferences."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

if __package__ in {None, ""}:
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from core.assistant_identity_profile_v1 import AssistantIdentityProfileV1
from core.paths import memory_dir
from core.spoken_language_memory_v1 import SpokenLanguageMemoryV1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onyx-identity")
    parser.add_argument("--state-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    language = commands.add_parser("language-set")
    language.add_argument("language")
    commands.add_parser("language-clear")
    alias = commands.add_parser("alias-set")
    alias.add_argument("alias")
    commands.add_parser("alias-clear")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = (args.state_root or memory_dir()).resolve()
    language = SpokenLanguageMemoryV1(root / "spoken_language_memory_v1.json")
    identity = AssistantIdentityProfileV1(root / "assistant_identity_profile_v1.json")
    if args.command == "language-set":
        output = {"language": asdict(language.set_owner_language(args.language))}
    elif args.command == "language-clear":
        output = {"language": asdict(language.revoke())}
    elif args.command == "alias-set":
        output = {"identity": asdict(identity.set_alias(args.alias))}
    elif args.command == "alias-clear":
        output = {"identity": asdict(identity.clear_alias())}
    else:
        output = {
            "language": asdict(language.status()),
            "identity": asdict(identity.status()),
        }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
