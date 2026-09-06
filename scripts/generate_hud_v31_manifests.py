"""Regenerate the deterministic packaged HUD and V31 source manifests."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.onyx_hud_current_acceptance_v31 import CURRENT_RUNTIME_PATHS  # noqa: E402
from core.onyx_packaged_runtime_hud_contract_v1 import (  # noqa: E402
    FORBIDDEN_PATHS,
    SOURCE_ONLY_HUD_AUTHORITY_FILES,
    expected_exact_sets,
)


PACKAGED = ROOT / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json"
V31 = ROOT / "docs/onyx/acceptance/VE-HUD-CURRENT-V31-E6-001.manifest.json"


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
        (
            set(prior_hashes)
            | exact_members
            | {
                "core/onyx_hud_orb_v11.py",
                "core/onyx_hud_orb_v12.py",
                "scripts/bootstrap_onyx.pyw",
            }
        )
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
    v31 = {
        "schema": "onyx.hud.current.v31.acceptance.v1",
        "candidate": "onyx-hud-v12-ambient-motion-001",
        "decision": "accepted-source",
        "current_root": "qml/OnyxLiveShellV11.qml",
        "predecessor": {
            "manifest_path": (
                "docs/onyx/acceptance/VE-HUD-CURRENT-V30-E6-001.manifest.json"
            ),
            "manifest_sha256": (
                "03ac350d5416afb6c801f8f1928c9be76c565d90db866ffb7ac3d907a892faa4"
            ),
            "acceptance_path": "core/onyx_hud_current_acceptance_v30.py",
            "acceptance_sha256": (
                "65ff03903196f65fc3356d097b5d981618f99def326964d1ff19ed090b74898c"
            ),
        },
        "runtime_inputs": records,
        "artifact_root_sha256": artifact_root(records),
        "semantics": {
            "source_acceptance": "V31-post-load-ambient-motion-successor",
            "frozen_acceptance": "compiled-verifier-anchored-packaged-runtime-v1",
            "stable_activation": "V24",
            "qml_roots_published_at_construction": 1,
            "post_load_lifecycle_resynchronised": True,
            "ambient_motion_policy_reused": True,
            "additional_render_timer_created": False,
            "hidden_motion_stops": True,
            "runtime_refusal_bypass": False,
        },
    }
    write(V31, v31)


if __name__ == "__main__":
    main()
