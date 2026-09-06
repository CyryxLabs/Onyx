"""Regenerate the deterministic packaged HUD and V27 source manifests."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.onyx_hud_current_acceptance_v27 import CURRENT_RUNTIME_PATHS  # noqa: E402
from core.onyx_packaged_runtime_hud_contract_v1 import (  # noqa: E402
    FORBIDDEN_PATHS,
    SOURCE_ONLY_HUD_AUTHORITY_FILES,
    expected_exact_sets,
)


PACKAGED = ROOT / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json"
V27 = ROOT / "docs/onyx/acceptance/VE-HUD-CURRENT-V27-E6-001.manifest.json"


def sha(relative: str | Path) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def artifact_root(records: list[dict[str, str]]) -> str:
    material = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(records, key=lambda entry: entry["path"])
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    packaged = json.loads(PACKAGED.read_text(encoding="utf-8"))
    prior_hashes = {
        entry["path"]: entry["sha256"] for entry in packaged["required_files"]
    }
    exact_sets = expected_exact_sets(ROOT)
    exact_members = {
        relative for members in exact_sets.values() for relative in members
    }
    required_paths = sorted(
        (set(prior_hashes) | exact_members | {"scripts/bootstrap_onyx.pyw"})
        - set(SOURCE_ONLY_HUD_AUTHORITY_FILES)
    )
    required = [
        {
            "path": relative,
            "sha256": sha(relative)
            if (ROOT / relative).is_file()
            else prior_hashes[relative],
        }
        for relative in required_paths
    ]
    packaged.update(
        required_files=required,
        exact_sets=exact_sets,
        forbidden_paths=list(FORBIDDEN_PATHS),
        artifact_root_sha256=artifact_root(required),
    )
    write(PACKAGED, packaged)

    records = [
        {"path": relative.as_posix(), "sha256": sha(relative)}
        for relative in CURRENT_RUNTIME_PATHS
    ]
    v27 = {
        "schema": "onyx.hud.current.v27.acceptance.v1",
        "candidate": "onyx-hud-v10-v40-single-root-accessibility-stability-009",
        "decision": "accepted-source",
        "current_root": "qml/OnyxLiveShellV10.qml",
        "predecessor": {
            "manifest_path": "docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json",
            "manifest_sha256": "9fdd2aa53fe7879c53b117f520f8704c37fdfc310bb173a5a2660f23fec77e92",
            "acceptance_path": "core/onyx_hud_current_acceptance_v26.py",
            "acceptance_sha256": "531174bd0cd847345c417a7a69835038c4bd11907f02167427ecb497a79e6027",
        },
        "runtime_inputs": records,
        "artifact_root_sha256": artifact_root(records),
        "semantics": {
            "source_acceptance": "V27-full-repository-single-root",
            "frozen_acceptance": "compiled-verifier-anchored-packaged-runtime-v1",
            "stable_activation": "V24",
            "qml_roots_published_at_construction": 1,
            "historical_root_detach": False,
            "runtime_refusal_bypass": False,
        },
    }
    write(V27, v27)


if __name__ == "__main__":
    main()
