"""Regenerate the deterministic packaged HUD and V32 source manifests."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.onyx_hud_current_acceptance_v32 import CURRENT_RUNTIME_PATHS  # noqa: E402
from core.onyx_packaged_runtime_hud_contract_v1 import (  # noqa: E402
    FORBIDDEN_PATHS,
    SOURCE_ONLY_HUD_AUTHORITY_FILES,
    expected_exact_sets,
)


PACKAGED = ROOT / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json"
PACKAGED_CONTRACT = ROOT / "core/onyx_packaged_runtime_hud_contract_v1.py"
V32 = ROOT / "docs/onyx/acceptance/VE-HUD-CURRENT-V32-E6-001.manifest.json"


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


def bind_packaged_manifest_digest() -> None:
    """Bind the generated packaged manifest into the compiled verifier source."""

    digest = hashlib.sha256(PACKAGED.read_bytes()).hexdigest()
    source = PACKAGED_CONTRACT.read_text(encoding="utf-8")
    pattern = re.compile(
        r'(PACKAGED_MANIFEST_SHA256: Final = \(\n\s+")[0-9a-f]{64}("\n\))'
    )
    updated, count = pattern.subn(rf"\g<1>{digest}\g<2>", source)
    if count != 1:
        raise RuntimeError("packaged manifest digest binding is ambiguous")
    PACKAGED_CONTRACT.write_text(updated, encoding="utf-8", newline="\n")


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
    bind_packaged_manifest_digest()

    records = [
        {"path": relative.as_posix(), "sha256": sha(relative)}
        for relative in CURRENT_RUNTIME_PATHS
    ]
    v32 = {
        "schema": "onyx.hud.current.v32.acceptance.v1",
        "candidate": "onyx-hud-v32-1.1.10-integration-001",
        "decision": "accepted-source",
        "current_root": "qml/OnyxLiveShellV11.qml",
        "predecessor": {
            "manifest_path": (
                "docs/onyx/acceptance/VE-HUD-CURRENT-V31-E6-001.manifest.json"
            ),
            "manifest_sha256": (
                "c294b3fe766bcd33a51451c3b1ac01eeb59e6b948d7eccf230a564ced5e3dc92"
            ),
            "acceptance_path": "core/onyx_hud_current_acceptance_v31.py",
            "acceptance_sha256": (
                "bc81427d6918403df94699864f8a5ca4c7be881cdf98c18b351c2d2afe35c405"
            ),
        },
        "runtime_inputs": records,
        "artifact_root_sha256": artifact_root(records),
        "semantics": {
            "source_acceptance": "V32-1.1.10-engineering-integration-successor",
            "frozen_acceptance": "compiled-verifier-anchored-packaged-runtime-v1",
            "release_version": "1.1.10",
            "stable_activation": "V24",
            "qml_root": "V11",
            "orb_controller": "V12",
            "new_renderer_created": False,
            "owner_scope_protections_preserved": True,
            "runtime_refusal_bypass": False,
        },
    }
    write(V32, v32)


if __name__ == "__main__":
    main()
