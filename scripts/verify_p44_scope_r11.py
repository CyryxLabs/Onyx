"""Verify the immutable P4.4 R11 successor source universe.

R11 preserves the accepted R10 universe and adds the shortcut durability
regression plus this successor verifier.  R10 and its verifier remain frozen
historical inputs and are never rebound to the later bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts import verify_p44_scope as r10  # noqa: E402


SELF = Path(__file__).resolve()
SUCCESSOR_INPUTS = frozenset({"tests/test_desktop_shortcut.py"})
_LINE = re.compile(r"([0-9a-f]{64}) \*([^\r\n]+)")


def expected_scope() -> set[str]:
    """Return the dependency-complete R10 universe plus R11 inputs."""
    closure = {
        (PROJECT / relative).resolve()
        for relative in r10.expected_scope()
    }
    closure.add(SELF.resolve())
    closure.update((PROJECT / relative).resolve() for relative in SUCCESSOR_INPUTS)
    missing = sorted(
        path.relative_to(PROJECT).as_posix()
        for path in closure
        if not path.is_file()
    )
    if missing:
        raise RuntimeError("missing required R11 scope input: " + ", ".join(missing))
    pending = [path for path in closure if path.suffix == ".py"]
    while pending:
        path = pending.pop()
        for dependency in r10._local_imports(path):
            if dependency not in closure:
                closure.add(dependency)
                if dependency.suffix == ".py":
                    pending.append(dependency)
    return {path.relative_to(PROJECT).as_posix() for path in closure}


def verify(manifest: Path) -> tuple[int, str]:
    raw = manifest.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise RuntimeError("manifest encoding/newlines are not canonical")
    records: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        match = _LINE.fullmatch(line)
        if match is None or match.group(2) in records:
            raise RuntimeError("manifest line is malformed or duplicated")
        records[match.group(2)] = match.group(1)
    expected = expected_scope()
    if set(records) != expected:
        missing = sorted(expected - set(records))
        extra = sorted(set(records) - expected)
        raise RuntimeError(f"manifest closure mismatch: missing={missing}, extra={extra}")
    if list(records) != sorted(records):
        raise RuntimeError("manifest paths are not ordinally sorted")
    for relative, expected_digest in records.items():
        actual = hashlib.sha256((PROJECT / relative).read_bytes()).hexdigest()
        if actual != expected_digest:
            raise RuntimeError(f"manifest digest mismatch: {relative}")
    return len(records), hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    count, digest = verify(args.manifest.resolve())
    print(f"P44_SCOPE_R11_OK files={count} manifest_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
