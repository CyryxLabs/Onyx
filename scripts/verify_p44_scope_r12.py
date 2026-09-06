"""Verify the immutable comprehensive P4.4 R12 successor universe."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts import verify_p44_scope_r11 as r11  # noqa: E402


SELF = Path(__file__).resolve()
_LINE = re.compile(r"([0-9a-f]{64}) \*([^\r\n]+)")


def expected_scope() -> set[str]:
    closure = {(PROJECT / relative).resolve() for relative in r11.expected_scope()}
    closure.add(SELF.resolve())
    missing = sorted(
        path.relative_to(PROJECT).as_posix() for path in closure if not path.is_file()
    )
    if missing:
        raise RuntimeError("missing required R12 scope input: " + ", ".join(missing))
    pending = [path for path in closure if path.suffix == ".py"]
    while pending:
        path = pending.pop()
        for dependency in r11.r10._local_imports(path):
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
        raise RuntimeError(
            f"manifest closure mismatch: missing={sorted(expected-set(records))}, "
            f"extra={sorted(set(records)-expected)}"
        )
    if list(records) != sorted(records):
        raise RuntimeError("manifest paths are not ordinally sorted")
    for relative, expected_digest in records.items():
        if hashlib.sha256((PROJECT / relative).read_bytes()).hexdigest() != expected_digest:
            raise RuntimeError(f"manifest digest mismatch: {relative}")
    return len(records), hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    count, digest = verify(args.manifest.resolve())
    print(f"P44_SCOPE_R12_OK files={count} manifest_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
