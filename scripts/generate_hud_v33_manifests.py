"""Generate the additive V33 HUD current-acceptance manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.onyx_hud_current_acceptance_v33 import (  # noqa: E402
    CURRENT_RUNTIME_PATHS,
    MANIFEST_RELATIVE,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_ACCEPTANCE_SHA256,
    PREDECESSOR_MANIFEST_RELATIVE,
    PREDECESSOR_MANIFEST_SHA256,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_root(records: list[dict[str, str]]) -> str:
    material = "".join(f"{item['path']}\0{item['sha256']}\n" for item in sorted(records, key=lambda entry: entry["path"])).encode()
    return hashlib.sha256(material).hexdigest()


def main() -> None:
    if sha(ROOT / PREDECESSOR_MANIFEST_RELATIVE) != PREDECESSOR_MANIFEST_SHA256 or sha(ROOT / PREDECESSOR_ACCEPTANCE_RELATIVE) != PREDECESSOR_ACCEPTANCE_SHA256:
        raise RuntimeError("V32 predecessor drifted")
    records = [{"path": relative.as_posix(), "sha256": sha(ROOT / relative)} for relative in CURRENT_RUNTIME_PATHS]
    prior = json.loads((ROOT / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json").read_text(encoding="utf-8"))
    packaged_paths = [entry["path"] for entry in prior["required_files"] if "tests" not in Path(entry["path"]).parts and (ROOT / entry["path"]).is_file()]
    packaged = [{"path": relative, "sha256": sha(ROOT / relative)} for relative in packaged_paths]
    payload = {
        "schema": "onyx.hud.current.v33.acceptance.v1", "candidate": "onyx-hud-v33-1.1.10-symlink-safe-001",
        "decision": "accepted-source", "current_root": "qml/OnyxLiveShellV11.qml",
        "predecessor": {"manifest_path": PREDECESSOR_MANIFEST_RELATIVE.as_posix(), "manifest_sha256": PREDECESSOR_MANIFEST_SHA256, "acceptance_path": PREDECESSOR_ACCEPTANCE_RELATIVE.as_posix(), "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA256},
        "runtime_inputs": records, "packaged_runtime_inputs": packaged,
        "artifact_root_sha256": artifact_root(records), "packaged_artifact_root_sha256": artifact_root(packaged),
        "semantics": {"source_acceptance": "V33-1.1.10-symlink-safe-package-successor", "frozen_acceptance": "explicit-smoke-without-packaged-test-sources", "release_version": "1.1.10", "stable_activation": "V24", "qml_root": "V11", "orb_controller": "V12", "new_renderer_created": False, "owner_scope_protections_preserved": True, "runtime_refusal_bypass": False, "symlink_and_reparse_protection_preserved": True, "staging_destination_link_protection_preserved": True, "packaged_test_sources": False},
    }
    (ROOT / MANIFEST_RELATIVE).write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
