"""Untracked-aware whitespace gate for the exact Phase 5.1 R6 source scope."""

from __future__ import annotations

from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCOPE = (
    "core/session_grants_v6.py",
    "scripts/check_phase5_grants_r6_whitespace.py",
    "scripts/verify_phase5_grants_r6.py",
    "tests/test_session_grants_v6.py",
)


def verify() -> None:
    for relative in SCOPE:
        path = PROJECT / relative
        raw = path.read_bytes()
        if b"\r" in raw or not raw.endswith(b"\n"):
            raise RuntimeError(f"noncanonical line endings: {relative}")
        for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            if line.rstrip(" \t") != line:
                raise RuntimeError(f"trailing whitespace: {relative}:{number}")


def main() -> int:
    verify()
    print("P51_GRANTS_R6_WHITESPACE_OK files=4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


