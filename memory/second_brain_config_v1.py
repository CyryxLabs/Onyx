"""Persistent, owner-operated Second Brain setup shared by source and releases."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def settings_path() -> Path:
    from core.paths import private_control_plane_runtime_dir
    return private_control_plane_runtime_dir().parent / "Second Brain" / "settings.json"


def validate(raw: dict) -> dict:
    from memory.obsidian_v1 import ObsidianVault
    if not isinstance(raw, dict) or set(raw) != {"schema", "vault", "database", "context_enabled"}:
        raise ValueError("Invalid Second Brain settings")
    if raw["schema"] != 1 or type(raw["context_enabled"]) is not bool:
        raise ValueError("Unsupported Second Brain settings")
    if not all(isinstance(raw[key], str) and Path(raw[key]).is_absolute() for key in ("vault", "database")):
        raise ValueError("Absolute vault and index paths required")
    ObsidianVault(raw["vault"], raw["database"])
    return dict(raw)


def load(path: Path | None = None) -> dict | None:
    from memory.obsidian_v1 import _checked
    target = settings_path() if path is None else path
    if not target.exists():
        return None
    _checked(target)
    with target.open("rb") as stream:
        raw = stream.read(8193)
    if len(raw) > 8192:
        raise ValueError("Second Brain settings exceed limit")
    return validate(json.loads(raw))


def configure(vault: Path, database: Path, *, context_enabled: bool, path: Path | None = None) -> dict:
    from memory.obsidian_v1 import _checked
    raw = validate({"schema": 1, "vault": str(vault), "database": str(database),
                    "context_enabled": context_enabled})
    target = settings_path() if path is None else path
    # Validate existing ancestors before creating our dedicated settings folder.
    ancestor = target.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    _checked(ancestor)
    target.parent.mkdir(parents=True, exist_ok=True)
    _checked(target.parent)
    if target.exists() or target.is_symlink():
        _checked(target)
    descriptor, temporary = tempfile.mkstemp(prefix=".onyx-brain-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(raw, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        _checked(target.parent)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return raw


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Onyx Second Brain owner setup")
    parser.add_argument("--settings", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("configure")
    setup.add_argument("--vault", type=Path, required=True)
    setup.add_argument("--database", type=Path, required=True)
    setup.add_argument("--share-context", action="store_true",
                       help="Approve relevant non-excluded excerpts entering the configured AI context")
    commands.add_parser("status")
    commands.add_parser("refresh")
    searching = commands.add_parser("search")
    searching.add_argument("query")
    try:
        args = parser.parse_args(argv)
        if args.command == "configure":
            result = configure(args.vault, args.database, context_enabled=args.share_context, path=args.settings)
        else:
            config = load(args.settings)
            if config is None:
                result = {"status": "not_configured", "context_enabled": False}
            elif args.command == "status":
                result = {**config, "status": "configured", "index_exists": Path(config["database"]).is_file()}
            else:
                from memory.obsidian_v1 import ObsidianVault
                from memory.store import assemble_prompt_context
                vault = ObsidianVault(config["vault"], config["database"])
                result = vault.refresh() if args.command == "refresh" else {
                    "context": assemble_prompt_context(vault.search(args.query), max_chars=1800)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
