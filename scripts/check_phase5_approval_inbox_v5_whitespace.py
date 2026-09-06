"""Untracked-aware whitespace gate for Phase 5.2 Approval Inbox V5."""

from __future__ import annotations

from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCOPE = (
    "core/approval_inbox_v5.py",
    "scripts/check_phase5_approval_inbox_v5_whitespace.py",
    "scripts/verify_phase5_approval_inbox_v5.py",
    "tests/test_approval_inbox_v5.py",
)


def verify() -> None:
    for relative in SCOPE:
        raw = (PROJECT / relative).read_bytes()
        if b"\r" in raw or not raw.endswith(b"\n"):
            raise RuntimeError(f"noncanonical line endings: {relative}")
        for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            if line.rstrip(" \t") != line:
                raise RuntimeError(f"trailing whitespace: {relative}:{number}")


def main() -> int:
    verify()
    print(f"P52_APPROVAL_INBOX_V5_WHITESPACE_OK files={len(SCOPE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
