"""Generate the append-only Advanced Operations V23 source manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.generate_advanced_operations_source_acceptance_v22 import SELECTED_PATHS


PROJECT = Path(__file__).resolve().parents[1]
PREDECESSOR_RELATIVE = "docs/onyx/acceptance/VE-ADVANCED-OPS-V22-001.manifest.json"
OUTPUT = PROJECT / "docs/onyx/acceptance/VE-ADVANCED-OPS-V23-001.manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    predecessor = root / PREDECESSOR_RELATIVE
    predecessor_sha = _sha256(predecessor)
    files = [
        {"path": relative, "sha256": _sha256(root / relative)}
        for relative in SELECTED_PATHS
    ]
    payload = bytearray(
        f"ONYX-ADVANCED-OPS-SOURCE-V23\0{predecessor_sha}\n".encode()
    )
    for item in files:
        payload.extend(f"{item['path']}\0{item['sha256']}\n".encode())
    return {
        "schema": "onyx.advanced-operations-source-acceptance.v4",
        "evidence_id": "VE-ADVANCED-OPS-V23-001",
        "status": "source_candidate",
        "predecessor": {"path": PREDECESSOR_RELATIVE, "sha256": predecessor_sha},
        "domain": "ONYX-ADVANCED-OPS-SOURCE-V23",
        "root_sha256": hashlib.sha256(payload).hexdigest(),
        "selection": {
            "mode": "closed_exact_successor_set",
            "count": len(files),
            "predecessor_manifest_is_immutable": True,
            "historical_hashes_are_rebound": False,
        },
        "files": files,
    }


def main() -> None:
    OUTPUT.write_text(
        json.dumps(build(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("ADVANCED_OPERATIONS_V23_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
