#!/usr/bin/env python3
"""
Sync the squad catalog blocks in README files from local squad manifests.

Usage:
    python squads/squad-creator/scripts/update-readme-catalog.py --write
    python squads/squad-creator/scripts/update-readme-catalog.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

CATALOG_START = "<!-- AUTO-GENERATED-SQUAD-CATALOG:START -->"
CATALOG_END = "<!-- AUTO-GENERATED-SQUAD-CATALOG:END -->"
DESCRIPTION_LIMIT = 140
SPECIAL_TITLE_PARTS = {
    "ai": "AI",
    "api": "API",
    "qa": "QA",
    "seo": "SEO",
    "ui": "UI",
    "ux": "UX",
}


@dataclass(frozen=True)
class ReadmeTarget:
    path: Path
    squad_link_prefix: str
    description_header: str
    source_header: str
    author_header: str


@dataclass(frozen=True)
class SourceInfo:
    label: str
    url: Optional[str]
    author_label: str
    author_url: Optional[str]


@dataclass(frozen=True)
class SquadEntry:
    slug: str
    label: str
    description: str
    source: SourceInfo


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[3]
SQUADS_DIR = PROJECT_ROOT / "squads"
README_TARGETS = (
    ReadmeTarget(
        path=PROJECT_ROOT / "README.md",
        squad_link_prefix="",
        description_header="O que faz",
        source_header="Origem",
        author_header="Enviado por",
    ),
    ReadmeTarget(
        path=PROJECT_ROOT / "doc" / "README.en.md",
        squad_link_prefix="../",
        description_header="What it does",
        source_header="Source",
        author_header="Submitted by",
    ),
)


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def read_yaml(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as handle:
            parsed = yaml.safe_load(handle)
    except Exception:
        return None

    return parsed if isinstance(parsed, dict) else None


def load_manifests(squad_dir: Path) -> List[Dict[str, Any]]:
    manifests: List[Dict[str, Any]] = []
    for filename in ("config.yaml", "squad.yaml"):
        parsed = read_yaml(squad_dir / filename)
        if parsed:
            manifests.append(parsed)
    return manifests


def nested_get(data: Dict[str, Any], path: Sequence[str]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def pick_string(manifests: Iterable[Dict[str, Any]], paths: Sequence[Sequence[str]]) -> Optional[str]:
    for manifest in manifests:
        for path in paths:
            value = nested_get(manifest, path)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def humanize_slug(slug: str) -> str:
    parts = []
    for part in slug.split("-"):
        lowered = part.lower()
        if lowered in SPECIAL_TITLE_PARTS:
            parts.append(SPECIAL_TITLE_PARTS[lowered])
        else:
            parts.append(lowered.capitalize())
    return " ".join(parts)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\u2014", "-")
    text = text.replace("\u2013", "-")
    return re.sub(r"\s+", " ", text).strip()


def summarize_description(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    normalized = normalize_whitespace(text)
    if not normalized:
        return ""

    first_sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    if first_sentence and len(first_sentence) <= limit:
        return first_sentence

    if len(normalized) <= limit:
        return normalized

    truncated = normalized[: limit - 3].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip(" ,;:-") + "..."


def extract_readme_summary(readme_path: Path) -> Optional[str]:
    if not readme_path.exists():
        return None

    lines = readme_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    chunks: List[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if chunks:
                break
            continue
        if line.startswith("#"):
            continue
        if line.startswith("```"):
            break
        if line.startswith(">"):
            chunks.append(line.lstrip(">").strip())
            continue
        chunks.append(line)
        if line.endswith((".", "!", "?")):
            break

    if not chunks:
        return None
    return " ".join(chunks)


def extract_description(squad_dir: Path, manifests: Sequence[Dict[str, Any]]) -> str:
    description = pick_string(
        manifests,
        (
            ("description",),
            ("pack", "description"),
            ("squad", "description"),
            ("metadata", "description"),
        ),
    )
    if not description:
        description = extract_readme_summary(squad_dir / "README.md") or humanize_slug(squad_dir.name)
    return summarize_description(description)


def markdown_link(label: str, url: Optional[str]) -> str:
    if not url:
        return escape_cell(label)
    return f"[{escape_label(label)}]({url})"


def escape_label(text: str) -> str:
    return text.replace("[", r"\[").replace("]", r"\]")


def escape_cell(text: str) -> str:
    return text.replace("|", r"\|")


def get_repo_slug() -> Optional[str]:
    repository = os.getenv("GITHUB_REPOSITORY")
    if repository:
        return repository

    remote = git("config", "--get", "remote.origin.url", check=False)
    if not remote:
        return None

    patterns = (
        re.compile(r"^https://github\.com/([^/]+/[^/.]+)(?:\.git)?$"),
        re.compile(r"^git@github\.com:([^/]+/[^/.]+)(?:\.git)?$"),
    )
    for pattern in patterns:
        match = pattern.match(remote)
        if match:
            return match.group(1)
    return None


def github_api(repo_slug: Optional[str], path: str) -> Optional[Any]:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not repo_slug:
        return None

    if token:
        url = f"https://api.github.com/repos/{repo_slug}/{path.lstrip('/')}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "AEXOS-squad-catalog-sync",
            },
        )

        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code not in {403, 404}:
                print(f"Warning: GitHub API request failed for {path}: {error}", file=sys.stderr)
        except urllib.error.URLError as error:
            print(f"Warning: Could not reach GitHub API for {path}: {error}", file=sys.stderr)

    try:
        output = subprocess.run(
            ["gh", "api", f"repos/{repo_slug}/{path.lstrip('/')}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if output.returncode == 0 and output.stdout.strip():
            return json.loads(output.stdout)
    except FileNotFoundError:
        return None

    return None


def pick_pull_request(pulls: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(pulls, list) or not pulls:
        return None

    merged = [pull for pull in pulls if pull.get("merged_at")]
    if merged:
        return sorted(merged, key=lambda item: item.get("merged_at") or "")[-1]

    current_pr_number = os.getenv("CATALOG_PR_NUMBER")
    if current_pr_number:
        for pull in pulls:
            if str(pull.get("number")) == str(current_pr_number):
                return pull

    return sorted(pulls, key=lambda item: item.get("number", 0))[-1]


def login_from_email(email: str) -> Optional[str]:
    match = re.match(r"^(?:\d+\+)?([^@]+)@users\.noreply\.github\.com$", email)
    if match:
        return match.group(1)
    return None


def commit_is_ancestor_of_base(commit_sha: str) -> bool:
    base_ref = os.getenv("CATALOG_BASE_REF")
    if not base_ref:
        return False

    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit_sha, f"origin/{base_ref}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def fallback_pr_source(repo_slug: Optional[str], commit_sha: str) -> Optional[SourceInfo]:
    pr_number = os.getenv("CATALOG_PR_NUMBER")
    pr_author = os.getenv("CATALOG_PR_AUTHOR")
    if not pr_number or not pr_author:
        return None
    if commit_is_ancestor_of_base(commit_sha):
        return None

    pr_url = f"https://github.com/{repo_slug}/pull/{pr_number}" if repo_slug else None
    author_url = f"https://github.com/{pr_author}"
    return SourceInfo(
        label=f"PR #{pr_number}",
        url=pr_url,
        author_label=f"@{pr_author}",
        author_url=author_url,
    )


def get_first_commit_details(relative_path: str) -> Tuple[str, str, str]:
    log_output = git(
        "log",
        "--diff-filter=A",
        "--format=%H%x1f%an%x1f%ae",
        "--reverse",
        "--",
        relative_path,
    )
    first_line = next((line for line in log_output.splitlines() if line.strip()), "")
    if not first_line:
        raise RuntimeError(f"Could not determine first commit for {relative_path}")

    sha, author_name, author_email = first_line.split("\x1f", 2)
    return sha, author_name, author_email


def get_initial_merge_subject(relative_path: str) -> Optional[str]:
    log_output = git(
        "log",
        "--first-parent",
        "--merges",
        "--format=%s",
        "--reverse",
        "--",
        relative_path,
        check=False,
    )
    for line in log_output.splitlines():
        if line.strip():
            return line.strip()
    return None


def build_author_source(
    repo_slug: Optional[str],
    author_name: str,
    author_email: str,
    branch_owner: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    login = login_from_email(author_email)
    repo_owner = repo_slug.split("/", 1)[0] if repo_slug else None

    if not login and branch_owner and repo_owner and branch_owner.casefold() != repo_owner.casefold():
        normalized_name = re.sub(r"[^a-z0-9]", "", author_name.casefold())
        normalized_owner = re.sub(r"[^a-z0-9]", "", branch_owner.casefold())
        if normalized_name in {"claude", "githubactionsbot"} or normalized_name == normalized_owner:
            login = branch_owner

    if login:
        return f"@{login}", f"https://github.com/{login}"
    return author_name, None


def fallback_pr_source_from_git(
    repo_slug: Optional[str],
    relative_path: str,
    author_name: str,
    author_email: str,
) -> Optional[SourceInfo]:
    subject = get_initial_merge_subject(relative_path)
    if not subject:
        return None

    match = re.match(r"^Merge pull request #(\d+) from ([^/ ]+)/", subject)
    if not match:
        return None

    pr_number = match.group(1)
    branch_owner = match.group(2)
    author_label, author_url = build_author_source(repo_slug, author_name, author_email, branch_owner)
    pr_url = f"https://github.com/{repo_slug}/pull/{pr_number}" if repo_slug else None
    return SourceInfo(
        label=f"PR #{pr_number}",
        url=pr_url,
        author_label=author_label,
        author_url=author_url,
    )


def resolve_source(
    repo_slug: Optional[str],
    relative_path: str,
    commit_sha: str,
    author_name: str,
    author_email: str,
) -> SourceInfo:
    pulls = github_api(repo_slug, f"commits/{commit_sha}/pulls")
    pull = pick_pull_request(pulls)
    if pull:
        login = nested_get(pull, ("user", "login")) or author_name
        author_url = f"https://github.com/{login}" if login and not login.startswith("@") else None
        author_label = login
        if isinstance(login, str) and login.strip() and not login.startswith("@"):
            author_label = f"@{login}"
        return SourceInfo(
            label=f"PR #{pull['number']}",
            url=pull.get("html_url") or (f"https://github.com/{repo_slug}/pull/{pull['number']}" if repo_slug else None),
            author_label=author_label,
            author_url=author_url,
        )

    git_pr_source = fallback_pr_source_from_git(repo_slug, relative_path, author_name, author_email)
    if git_pr_source:
        return git_pr_source

    fallback_pr = fallback_pr_source(repo_slug, commit_sha)
    if fallback_pr:
        return fallback_pr

    commit_data = github_api(repo_slug, f"commits/{commit_sha}") or {}
    commit_url = f"https://github.com/{repo_slug}/commit/{commit_sha}" if repo_slug else None
    login = nested_get(commit_data, ("author", "login")) or nested_get(commit_data, ("committer", "login"))
    if isinstance(login, str) and login.strip():
        author_label = f"@{login}"
        author_url = f"https://github.com/{login}"
    else:
        author_label, author_url = build_author_source(repo_slug, author_name, author_email)

    return SourceInfo(
        label=f"commit {commit_sha[:7]}",
        url=commit_url,
        author_label=author_label,
        author_url=author_url,
    )


def build_entries() -> List[SquadEntry]:
    repo_slug = get_repo_slug()
    entries: List[SquadEntry] = []

    for squad_dir in sorted(path for path in SQUADS_DIR.iterdir() if path.is_dir()):
        manifests = load_manifests(squad_dir)
        description = extract_description(squad_dir, manifests)
        label = humanize_slug(squad_dir.name)
        relative_path = squad_dir.relative_to(PROJECT_ROOT).as_posix()
        commit_sha, author_name, author_email = get_first_commit_details(relative_path)
        source = resolve_source(repo_slug, relative_path, commit_sha, author_name, author_email)
        entries.append(
            SquadEntry(
                slug=squad_dir.name,
                label=label,
                description=description,
                source=source,
            )
        )

    return entries


def render_catalog(entries: Sequence[SquadEntry], target: ReadmeTarget) -> str:
    lines = [
        CATALOG_START,
        f"| Squad | {target.description_header} | {target.source_header} | {target.author_header} |",
        "|-------|-----------|--------|-------------|",
    ]

    for entry in entries:
        squad_link = markdown_link(entry.label, f"{target.squad_link_prefix}squads/{entry.slug}/")
        source_link = markdown_link(entry.source.label, entry.source.url)
        author_link = markdown_link(entry.source.author_label, entry.source.author_url)
        lines.append(
            "| "
            + " | ".join(
                (
                    squad_link,
                    escape_cell(entry.description),
                    source_link,
                    author_link,
                )
            )
            + " |"
        )

    lines.append(CATALOG_END)
    return "\n".join(lines)


def replace_catalog_block(content: str, replacement: str) -> str:
    pattern = re.compile(
        rf"{re.escape(CATALOG_START)}.*?{re.escape(CATALOG_END)}",
        re.DOTALL,
    )
    if not pattern.search(content):
        raise RuntimeError("Catalog markers not found in README")
    return pattern.sub(replacement, content, count=1)


def sync_readmes(write: bool) -> List[Path]:
    entries = build_entries()
    changed: List[Path] = []

    for target in README_TARGETS:
        original = target.path.read_text(encoding="utf-8")
        replacement = render_catalog(entries, target)
        updated = replace_catalog_block(original, replacement)
        if updated != original:
            changed.append(target.path)
            if write:
                target.path.write_text(updated, encoding="utf-8")

    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync squad catalog blocks in README files")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the catalog is stale; do not write files",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write updated catalog blocks back to the README files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    write = args.write or not args.check

    try:
        changed = sync_readmes(write=write)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if changed:
        for path in changed:
            print(f"Updated {path.relative_to(PROJECT_ROOT)}")
        return 1 if args.check else 0

    print("Squad catalog already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
