from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "core/approval_inbox_v10.py",
    "tests/test_approval_inbox_v10.py",
    "scripts/build_phase5_approval_inbox_v10_evidence.py",
    "scripts/check_phase5_approval_inbox_v10_whitespace.py",
    "scripts/phase5_approval_inbox_v10_historical_projection.py",
    "scripts/verify_phase5_approval_inbox_v10.py",
    "scripts/verify_phase5_approval_inbox_v10_worker.py",
)


def main() -> int:
    failures: list[str] = []
    for relative in FILES:
        data = (ROOT / relative).read_bytes()
        if b"\r" in data:
            failures.append(f"{relative}: carriage-return")
        if not data.endswith(b"\n"):
            failures.append(f"{relative}: no-final-newline")
        for number, line in enumerate(data.splitlines(), 1):
            if line.rstrip(b" \t") != line:
                failures.append(f"{relative}:{number}: trailing-whitespace")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"P52_APPROVAL_INBOX_V10_WHITESPACE_OK files={len(FILES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
