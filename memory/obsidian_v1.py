"""Owner-selected, read-only Obsidian retrieval. No Obsidian plugin is needed.

Refresh explicitly outside the audio loop. Notes never become approved personal
memories or action authority. The separate index can be discarded independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from memory.store import MemoryStore, MemoryStoreError, assemble_prompt_context, contains_secret

MAX_FILE_BYTES = 256 * 1024
MAX_VAULT_BYTES = 16 * 1024 * 1024
MAX_FILES = 1000
PRIVATE = re.compile(r"(?:^|[\W_])(private|secret|credentials?|passwords?|tokens?)(?:$|[\W_])", re.I)
OPT_OUT = re.compile(r"(?im)^\s*(?:onyx_exclude\s*:\s*true|onyx_context\s*:\s*false)\s*$")


def _checked(path: Path) -> Path:
    """Inspect the spelling before resolution, including every ancestor."""
    path = Path(os.path.abspath(path))
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise MemoryStoreError("Linked/reparse paths are not permitted for Obsidian")
    return path


def _allowed(relative: Path) -> bool:
    return (
        relative.suffix.lower() == ".md"
        and len(relative.as_posix()) < 170
        and not any(part.startswith(".") or PRIVATE.search(part) for part in relative.parts)
    )


class ObsidianVault:
    def __init__(self, vault: Path | str, database: Path | str):
        raw = Path(vault)
        if not raw.is_absolute():
            raise MemoryStoreError("An absolute owner-selected vault path is required")
        self.vault = _checked(raw)
        if not self.vault.is_dir() or self.vault == Path(self.vault.anchor):
            raise MemoryStoreError("Select a specific vault directory")
        self.identity = hashlib.sha256(str(self.vault).casefold().encode()).hexdigest()[:24]
        database = Path(os.path.abspath(database))
        if database.is_relative_to(self.vault):
            raise MemoryStoreError("Keep the index outside the read-only vault")
        _checked(database.parent)
        self.store = MemoryStore(database)

    def _read(self, relative: Path) -> tuple[str, str]:
        if relative.is_absolute() or ".." in relative.parts or not _allowed(relative):
            raise MemoryStoreError("Excluded note")
        path = _checked(self.vault / relative)
        if not path.is_relative_to(self.vault):
            raise MemoryStoreError("Note escaped the vault")
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
            raise MemoryStoreError("Note is not a bounded regular file")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not os.path.samestat(before, opened):
                raise MemoryStoreError("Note changed while opening")
            data = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
        _checked(path)
        if (len(data) > MAX_FILE_BYTES or not os.path.samestat(after, path.stat())
                or before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size):
            raise MemoryStoreError("Note changed while reading")
        text = data.decode("utf-8-sig")
        if "\0" in text or OPT_OUT.search(text) or contains_secret(text, relative.as_posix()):
            raise MemoryStoreError("Note excluded by privacy policy")
        return text, hashlib.sha256(data).hexdigest()

    def refresh(self) -> dict:
        """Bounded discovery; repeat runs only rewrite changed chunks."""
        _checked(self.vault)
        candidates = []
        excluded = 0
        total = 0
        visited = 0

        def scan_error(error):
            raise MemoryStoreError("Vault discovery failed; previous index retained") from error

        for directory, dirs, files in os.walk(self.vault, followlinks=False, onerror=scan_error):
            _checked(Path(directory))
            safe_dirs = []
            for name in dirs:
                visited += 1
                if visited > MAX_FILES * 4:
                    raise MemoryStoreError("Vault discovery limit exceeded; select a smaller vault")
                if name.startswith(".") or PRIVATE.search(name):
                    continue
                try:
                    _checked(Path(directory) / name)
                    safe_dirs.append(name)
                except (OSError, MemoryStoreError):
                    excluded += 1
            dirs[:] = sorted(safe_dirs)
            for name in sorted(files):
                visited += 1
                if visited > MAX_FILES * 4:
                    raise MemoryStoreError("Vault discovery limit exceeded; select a smaller vault")
                relative = (Path(directory) / name).relative_to(self.vault)
                if not _allowed(relative):
                    excluded += 1
                    continue
                try:
                    text, digest = self._read(relative)
                except (OSError, UnicodeError, MemoryStoreError):
                    excluded += 1
                    continue
                total += len(text.encode("utf-8"))
                candidates.append((relative, text, digest))
                if len(candidates) > MAX_FILES or total > MAX_VAULT_BYTES:
                    raise MemoryStoreError("Vault indexing limit exceeded; select a smaller vault")
        self.store.initialize()
        old = {record.key: record for record in self.store.list(limit=None)}
        if any(record.category != "obsidian" for record in old.values()):
            raise MemoryStoreError("Refusing a database containing non-Obsidian memory")
        retained = set()
        written = 0
        for relative, text, digest in candidates:
            # Character chunks keep even very long Markdown lines bounded.
            for offset in range(0, len(text), 1600):
                content = text[offset:offset + 1600].strip()
                content = re.sub(r"(?im)^\s*(system|assistant|developer|user)\s*:",
                                 "[escaped role]:", content)
                if not content:
                    continue
                key = hashlib.sha256(f"{self.identity}/{relative}/{offset}".encode()).hexdigest()
                retained.add(key)
                if key in old and (old[key].metadata or {}).get("digest") == digest:
                    continue
                self.store.remember(
                    content, source=f"obsidian:{self.identity}", category="obsidian", key=key,
                    citation=f"obsidian:{relative.as_posix()}#offset={offset}",
                    metadata={"relative": relative.as_posix(), "digest": digest, "vault": self.identity},
                )
                written += 1
        removed = 0
        for key, record in old.items():
            if key not in retained:
                removed += int(self.store.forget(record.id))
        return {"status": "indexed", "notes": len(candidates), "chunks_written": written,
                "chunks_removed": removed, "excluded": excluded, "network_requests": 0}

    def search(self, query: str, *, limit: int = 4):
        if not query.strip() or len(query) > 2000:
            return []
        if not self.store.path.exists():
            return []  # Retrieval never starts an expensive indexing operation.
        _checked(self.vault)
        selected = []
        checked = {}
        for record in self.store.search(query, limit=min(32, max(1, limit) * 4)):
            meta = record.metadata or {}
            if meta.get("vault") != self.identity:
                continue
            relative = str(meta.get("relative", ""))
            if relative not in checked:
                try:
                    _, checked[relative] = self._read(Path(relative))
                except (OSError, UnicodeError, MemoryStoreError):
                    checked[relative] = None
            if checked[relative] is not None and checked[relative] == meta.get("digest"):
                selected.append(record)
            if len(selected) >= min(8, max(1, limit)):
                break
        return selected


def configured_context(query: str, *, max_chars: int = 900) -> str:
    """Explicit owner opt-in for excerpts entering provider-visible context."""
    try:
        vault = os.environ.get("ONYX_OBSIDIAN_VAULT", "").strip()
        if vault:
            if os.environ.get("ONYX_OBSIDIAN_CONTEXT") != "1":
                return ""
            from core.paths import memory_dir
            database = memory_dir() / "onyx_obsidian.sqlite3"
        else:
            from memory.second_brain_config_v1 import load
            config = load()
            if not config or not config["context_enabled"]:
                return ""
            # An explicit environment pause overrides persisted opt-in.
            if "ONYX_OBSIDIAN_CONTEXT" in os.environ and os.environ["ONYX_OBSIDIAN_CONTEXT"] != "1":
                return ""
            vault, database = config["vault"], Path(config["database"])
        return assemble_prompt_context(ObsidianVault(vault, database).search(query), max_chars=max_chars)
    except (OSError, UnicodeError, ValueError, MemoryStoreError):
        return ""  # Optional source failure must not break the existing conversation.


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Onyx read-only Obsidian Second Brain")
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("command", choices=("refresh", "search"))
    parser.add_argument("query", nargs="?", default="")
    args = parser.parse_args(argv)
    try:
        vault = ObsidianVault(args.vault, args.database)
        result = vault.refresh() if args.command == "refresh" else {
            "context": assemble_prompt_context(vault.search(args.query), max_chars=1800)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, ValueError, MemoryStoreError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
