"""Regenerate the deterministic packaged HUD and V26 source manifests."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.onyx_hud_current_acceptance_v26 import CURRENT_RUNTIME_PATHS  # noqa: E402
from core.onyx_packaged_runtime_hud_contract_v1 import (  # noqa: E402
    FORBIDDEN_PATHS,
    SOURCE_ONLY_HUD_AUTHORITY_FILES,
    expected_exact_sets,
)


PACKAGED = ROOT / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json"
V26 = ROOT / "docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json"


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
    v26 = {
        "schema": "onyx.hud.current.v26.acceptance.v1",
        "candidate": "onyx-hud-v10-v38-frozen-diagnostic-closure-008",
        "decision": "accepted-source",
        "current_root": "qml/OnyxLiveShellV10.qml",
        "predecessor": {
            "manifest_path": "docs/onyx/acceptance/VE-HUD-CURRENT-V25-E6-001.manifest.json",
            "manifest_sha256": "539b0026cdc5df10f01426ffb57cbc134a4dbe74172037936e3296fa741178f5",
            "acceptance_path": "core/onyx_hud_current_acceptance_v25.py",
            "acceptance_sha256": "1d65cf04a302b261c5874180ee2d8a5028a651fe507f12f720df1ec4631f2d00",
        },
        "runtime_inputs": records,
        "artifact_root_sha256": artifact_root(records),
        "semantics": {
            "source_acceptance": "V26-full-repository",
            "frozen_acceptance": "compiled-verifier-anchored-packaged-runtime-v1",
            "stable_activation": "V24",
            "native_v24_option_injection": False,
            "diagnostic_exception_mode": "noninteractive-exit-70",
            "runtime_refusal_bypass": False,
        },
    }
    write(V26, v26)


if __name__ == "__main__":
    main()
