"""Machine-readable source-contract parity report for Onyx."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from core.capability_parity_v1 import (
    validate_packaged_parity_v1,
    validate_source_parity_v1,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onyx-parity")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--packaged", action="store_true")
    args = parser.parse_args(argv)
    validator = validate_packaged_parity_v1 if args.packaged else validate_source_parity_v1
    print(json.dumps(validator(args.root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
