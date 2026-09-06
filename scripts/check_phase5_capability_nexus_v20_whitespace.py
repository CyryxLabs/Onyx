"""Untracked-aware whitespace gate for Phase 5.3 Capability Nexus V20."""

from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCOPE = (
    "core/capability_nexus_v20.py",
    "scripts/check_phase5_capability_nexus_v20_whitespace.py",
    "scripts/phase5_capability_nexus_v20_subtest_reporter.py",
    "scripts/verify_phase5_capability_nexus_v20.py",
    "scripts/verify_phase5_capability_nexus_v20_worker.py",
    "tests/test_capability_nexus_v20.py",
)


def verify() -> None:
    for relative in SCOPE:
        raw = (PROJECT / relative).read_bytes()
        if b"\r" in raw or not raw.endswith(b"\n"):
            raise RuntimeError(f"noncanonical line endings: {relative}")
        for number, line in enumerate(raw.decode().splitlines(), 1):
            if line.rstrip(" \t") != line:
                raise RuntimeError(f"trailing whitespace: {relative}:{number}")


def main() -> int:
    verify()
    print(f"P53_CAPABILITY_NEXUS_V20_WHITESPACE_OK files={len(SCOPE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
